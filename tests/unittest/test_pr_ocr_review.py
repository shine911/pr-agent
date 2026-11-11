import subprocess
from unittest.mock import MagicMock

import pytest

from pr_agent.agent.pr_agent import command2class
from pr_agent.algo.ocr_config import ocr_config_cli_invocation
from pr_agent.algo.run_details import command_failed, init_run_details
from pr_agent.config_loader import get_settings
from pr_agent.tools.pr_ocr_review import PROcrReview

MR_URL = "https://gitlab.example/g/p/-/merge_requests/7"
_KEYS = [
    "config.enable_auto_approval", "config.model", "config.response_language",
    "ocr_review.extra_instructions", "ocr_review.rules"]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = get_settings()
    saved = {key: settings.get(key) for key in _KEYS}
    settings.set("config.model", "openai/gpt-6-luna")
    settings.set("config.response_language", "vi-VN")
    settings.set("ocr_review.extra_instructions", "")
    settings.set("ocr_review.rules", [])
    settings.set("config.enable_auto_approval", True)
    monkeypatch.setenv("OCR_LLM_AUTH_TOKEN", "sk-test")
    monkeypatch.setenv("GITLAB_API_TOKEN", "glpat-test")
    monkeypatch.setenv("CI_COMMIT_SHA", "abc123")
    monkeypatch.setenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "develop")
    monkeypatch.setenv("CI_MERGE_REQUEST_DIFF_BASE_SHA", "base999")
    monkeypatch.delenv("CI_MERGE_REQUEST_IID", raising=False)
    token = ocr_config_cli_invocation.set(True)
    init_run_details()
    yield
    ocr_config_cli_invocation.reset(token)
    for key, value in saved.items():
        settings.set(key, value)


class _Calls(list):
    codes: dict
    provider: MagicMock


@pytest.fixture
def calls(monkeypatch):
    """Record every subprocess call; per-command return codes can be set in `codes`."""
    recorded = _Calls()
    codes = {}

    def fake_run(cmd, **kwargs):
        recorded.append((cmd, kwargs))
        key = " ".join(cmd[:3]) if cmd[0] == "ocr" else cmd[0]
        if cmd[:2] == ["ocr", "review"]:
            kwargs["stdout"].write('{"comments": []}')
            key = "ocr review"
        if cmd[0] != "ocr" and cmd[0] != "git":
            key = "post_review"
        return subprocess.CompletedProcess(cmd, codes.get(key, 0), stdout="", stderr="")

    monkeypatch.setattr("pr_agent.tools.pr_ocr_review.subprocess.run", fake_run)
    provider = MagicMock()
    provider.auto_approve.return_value = True
    monkeypatch.setattr("pr_agent.tools.pr_ocr_review.get_git_provider_with_context", lambda _url: provider)
    recorded.codes = codes
    recorded.provider = provider
    return recorded


def _commands(calls):
    return [cmd for cmd, _ in calls]


async def test_happy_path_runs_review_publishes_and_approves(calls, tmp_path):
    assert await PROcrReview(MR_URL).run() is True

    cmds = _commands(calls)
    assert ["ocr", "config", "set", "llm.model", "gpt-6-luna"] in cmds
    assert ["ocr", "config", "set", "language", "Vietnamese"] in cmds
    assert ["ocr", "llm", "test"] in cmds
    review = next(c for c in cmds if c[:2] == ["ocr", "review"])
    assert review[review.index("--from") + 1] == "base999"
    assert review[review.index("--to") + 1] == "abc123"
    assert "--rule" not in review
    post = next(kw for c, kw in calls if c[0] != "ocr" and c[0] != "git")
    assert post["env"]["CI_MERGE_REQUEST_IID"] == "7"
    calls.provider.auto_approve.assert_called_once()
    assert (tmp_path / ".ocr" / "ocr-result.json").exists()


async def test_rule_file_is_passed_to_ocr(calls):
    get_settings().set("ocr_review.extra_instructions", "- No sync fs.")
    assert await PROcrReview(MR_URL).run() is True
    review = next(c for c in _commands(calls) if c[:2] == ["ocr", "review"])
    assert review[review.index("--rule") + 1].endswith(".ocr/rule.json")


async def test_diff_base_falls_back_to_target_branch(calls, monkeypatch):
    monkeypatch.setenv("CI_MERGE_REQUEST_DIFF_BASE_SHA", "")
    assert await PROcrReview(MR_URL).run() is True
    review = next(c for c in _commands(calls) if c[:2] == ["ocr", "review"])
    assert review[review.index("--from") + 1] == "origin/develop"


async def test_api_triggered_pipeline_resolves_target_from_provider(calls, monkeypatch):
    monkeypatch.delenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME")
    monkeypatch.delenv("CI_MERGE_REQUEST_DIFF_BASE_SHA")
    mr = MagicMock(target_branch="main", diff_refs=None)
    monkeypatch.setattr(
        "pr_agent.tools.pr_ocr_review.get_git_provider_with_context", lambda _url: MagicMock(mr=mr))
    assert await PROcrReview(MR_URL).run() is True
    review = next(c for c in _commands(calls) if c[:2] == ["ocr", "review"])
    assert review[review.index("--from") + 1] == "origin/main"


async def test_ocr_failure_still_publishes_but_fails_and_skips_approval(calls):
    calls.codes["ocr review"] = 2
    assert await PROcrReview(MR_URL).run() is False
    assert any(c[0] not in ("ocr", "git") for c in _commands(calls))  # post_review still ran
    assert command_failed() is True
    calls.provider.auto_approve.assert_not_called()


async def test_post_review_failure_fails_and_skips_approval(calls):
    calls.codes["post_review"] = 1
    assert await PROcrReview(MR_URL).run() is False
    assert command_failed() is True
    calls.provider.auto_approve.assert_not_called()


async def test_llm_test_failure_stops_before_review(calls):
    calls.codes["ocr llm test"] = 1
    assert await PROcrReview(MR_URL).run() is False
    assert not any(c[:2] == ["ocr", "review"] for c in _commands(calls))
    assert command_failed() is True


async def test_missing_token_fails_fast(calls, monkeypatch):
    monkeypatch.delenv("GITLAB_API_TOKEN")
    assert await PROcrReview(MR_URL).run() is False
    assert calls == []
    assert command_failed() is True


async def test_refuses_outside_cli_entrypoint(calls):
    token = ocr_config_cli_invocation.set(False)
    try:
        assert await PROcrReview(MR_URL).run() is False
    finally:
        ocr_config_cli_invocation.reset(token)
    assert calls == []


def test_ocr_review_registered():
    assert command2class["ocr_review"] is PROcrReview


def _fake_result(calls, monkeypatch, content):
    """Make `ocr review` write `content` as its result."""
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ocr", "review"]:
            kwargs["stdout"].write(content)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("pr_agent.tools.pr_ocr_review.subprocess.run", fake_run)


async def test_comments_unapprove_instead_of_approve(calls, monkeypatch):
    _fake_result(calls, monkeypatch, '{"comments": [{"path": "a.js", "body": "bug"}]}')
    assert await PROcrReview(MR_URL).run() is True
    calls.provider.auto_approve.assert_not_called()
    calls.provider.auto_unapprove.assert_called_once()


@pytest.mark.parametrize("content", ["not json", "{}", '{"comments": null}', '{"comments": "x"}', "[]"])
async def test_unreadable_result_changes_nothing(calls, monkeypatch, content):
    _fake_result(calls, monkeypatch, content)
    assert await PROcrReview(MR_URL).run() is True
    calls.provider.auto_approve.assert_not_called()
    calls.provider.auto_unapprove.assert_not_called()


async def test_flag_off_changes_nothing(calls):
    get_settings().set("config.enable_auto_approval", False)
    assert await PROcrReview(MR_URL).run() is True
    calls.provider.auto_approve.assert_not_called()
    calls.provider.auto_unapprove.assert_not_called()


async def test_failed_approval_does_not_fail_the_review(calls):
    calls.provider.auto_approve.return_value = False
    assert await PROcrReview(MR_URL).run() is True
    assert command_failed() is False
