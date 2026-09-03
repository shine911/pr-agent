import asyncio
import time

import pytest

from pr_agent.agent.pr_agent import PRAgent
from pr_agent.config_loader import get_settings
from tests.unittest._settings_helpers import restore_settings, snapshot_settings


class _HangingTool:
    """Simulates a command whose underlying call (LLM, git provider, ticket
    tracker...) stalls forever instead of raising - the exact failure mode
    that used to hang /review until an external CI pipeline killed it."""

    def __init__(self, pr_url, ai_handler=None, args=None):
        pass

    async def run(self):
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_command_timeout_bounds_a_stalled_command(monkeypatch):
    snapshot = snapshot_settings(["config.command_timeout"])
    try:
        get_settings().config.command_timeout = 0.05
        monkeypatch.setitem(
            __import__("pr_agent.agent.pr_agent", fromlist=["command2class"]).command2class,
            "review",
            _HangingTool,
        )

        start = time.monotonic()
        result = await PRAgent().handle_request("http://example.com/pr/1", "/review")
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 5  # bounded by command_timeout, not the 3600s hang
    finally:
        restore_settings(snapshot)
