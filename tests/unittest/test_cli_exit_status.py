from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pr_agent import cli


def test_run_exits_nonzero_on_tool_failure():
    """A tool failure (handle_request returns False, e.g. because a tool re-raised
    an internal error) must produce a non-zero exit code so a CI pipeline can tell
    the run failed, instead of the process always exiting 0."""
    fake_settings = SimpleNamespace(litellm={}, set=MagicMock())

    async def fake_handle_request(*_args, **_kwargs):
        return False

    with patch("pr_agent.cli.get_settings", return_value=fake_settings), patch(
        "pr_agent.cli.PRAgent",
        return_value=SimpleNamespace(handle_request=fake_handle_request),
    ):
        with pytest.raises(SystemExit) as exc_info:
            cli.run(inargs=["--pr_url=https://github.com/a/b/pull/1", "describe"])

    assert exc_info.value.code == 1


def test_run_does_not_exit_on_success():
    fake_settings = SimpleNamespace(litellm={}, set=MagicMock())

    async def fake_handle_request(*_args, **_kwargs):
        return True

    with patch("pr_agent.cli.get_settings", return_value=fake_settings), patch(
        "pr_agent.cli.PRAgent",
        return_value=SimpleNamespace(handle_request=fake_handle_request),
    ):
        cli.run(inargs=["--pr_url=https://github.com/a/b/pull/1", "describe"])


def test_run_forwards_propagate_tool_errors_default():
    """cli.run() must default to propagating tool-internal errors (see the
    propagate_tool_errors handling in PRDescription/PRReviewer/PRCodeSuggestions)
    so a failed run can be told apart from an empty one, placed before args.rest
    so an explicit override from the caller still wins."""
    fake_settings = SimpleNamespace(litellm={}, set=MagicMock())
    captured = {}

    async def fake_handle_request(pr_url, request, notify=None):
        captured["request"] = request
        return True

    with patch("pr_agent.cli.get_settings", return_value=fake_settings), patch(
        "pr_agent.cli.PRAgent",
        return_value=SimpleNamespace(handle_request=fake_handle_request),
    ):
        cli.run(inargs=["--pr_url=https://github.com/a/b/pull/1", "describe"])

    assert captured["request"] == ["describe", "--config.propagate_tool_errors=true"]


def test_run_user_override_of_propagate_tool_errors_wins():
    fake_settings = SimpleNamespace(litellm={}, set=MagicMock())
    captured = {}

    async def fake_handle_request(pr_url, request, notify=None):
        captured["request"] = request
        return True

    with patch("pr_agent.cli.get_settings", return_value=fake_settings), patch(
        "pr_agent.cli.PRAgent",
        return_value=SimpleNamespace(handle_request=fake_handle_request),
    ):
        cli.run(inargs=[
            "--pr_url=https://github.com/a/b/pull/1", "describe",
            "--config.propagate_tool_errors=false",
        ])

    assert captured["request"] == [
        "describe",
        "--config.propagate_tool_errors=true",
        "--config.propagate_tool_errors=false",
    ]
