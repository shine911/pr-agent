import json
import subprocess

import pytest

from pr_agent.agent.pr_agent import command2class
from pr_agent.algo.ocr_config import build_ocr_rules, ocr_config_cli_invocation
from pr_agent.algo.run_details import command_failed, init_run_details
from pr_agent.config_loader import get_settings
from pr_agent.tools.pr_ocr_config import PROcrConfig

MR_URL = "https://gitlab.example/g/p/-/merge_requests/1"
_KEYS = [
    "config.model", "config.response_language", "config.cli_mode", "ocr_review.extra_instructions",
    "ocr_review.rules", "openai.key", "gitlab.personal_access_token"]


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = get_settings()
    saved = {key: settings.get(key) for key in _KEYS}
    settings.set("ocr_review.extra_instructions", "")
    settings.set("ocr_review.rules", [])
    settings.set("config.model", "openai/gpt-6-luna")
    settings.set("config.response_language", "vi-VN")
    token = ocr_config_cli_invocation.set(True)
    init_run_details()
    yield
    ocr_config_cli_invocation.reset(token)
    for key, value in saved.items():
        settings.set(key, value)


def _source_env(tmp_path):
    out = subprocess.run(
        ["bash", "-c", "source .ocr/ocr.env && env -0"], cwd=tmp_path, capture_output=True, check=True)
    return dict(item.split("=", 1) for item in out.stdout.decode().split("\0") if "=" in item)


async def test_run_writes_env_and_rules(tmp_path):
    settings = get_settings()
    settings.set("ocr_review.extra_instructions", "- No sync fs.")
    settings.set("openai.key", "sk-secret-123")
    settings.set("gitlab.personal_access_token", "glpat-secret")

    assert await PROcrConfig(MR_URL).run() is True

    env = _source_env(tmp_path)
    assert env["OCR_LLM_MODEL"] == "gpt-6-luna"
    assert env["OCR_LLM_URL"] == "https://api.openai.com/v1"
    assert env["OCR_LLM_PROTOCOL"] == "openai-responses"
    assert env["OCR_LANGUAGE"] == "Vietnamese"
    assert env["OCR_FAIL_ON_SEVERITY"] == ""
    assert env["OCR_RULE_FILE"] == str(tmp_path / ".ocr" / "rule.json")
    rule_path = tmp_path / ".ocr" / "rule.json"
    assert json.loads(rule_path.read_text()) == build_ocr_rules("- No sync fs.", [])
    for path in (tmp_path / ".ocr" / "ocr.env", rule_path):
        content = path.read_text()
        assert "sk-secret-123" not in content
        assert "glpat-secret" not in content


async def test_run_without_rules_has_empty_rule_file(tmp_path):
    assert await PROcrConfig(MR_URL).run() is True
    assert _source_env(tmp_path)["OCR_RULE_FILE"] == ""
    assert not (tmp_path / ".ocr" / "rule.json").exists()


async def test_run_refuses_outside_cli_entrypoint(tmp_path):
    get_settings().set("CONFIG.CLI_MODE", True)
    token = ocr_config_cli_invocation.set(False)
    try:
        assert await PROcrConfig(MR_URL).run() is False
    finally:
        ocr_config_cli_invocation.reset(token)
    assert not (tmp_path / ".ocr").exists()


async def test_run_config_error_records_failure(tmp_path):
    get_settings().set("config.model", "gemini/x")
    assert await PROcrConfig(MR_URL).run() is False
    assert command_failed() is True
    assert not (tmp_path / ".ocr" / "ocr.env").exists()


def test_constructor_does_not_touch_git_provider(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("git provider must not be created")

    monkeypatch.setattr("pr_agent.git_providers.get_git_provider", boom)
    PROcrConfig(MR_URL)


def test_ocr_config_registered():
    assert command2class["ocr_config"] is PROcrConfig
