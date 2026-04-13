"""
Unit tests for GitLabProvider.get_conversation_history()

Run with:
    PYTHONPATH=. ./.venv/bin/pytest tests/unittest/test_gitlab_history_context.py -v
"""
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_note(note_id: int, author_username: str, body: str, created_at: str = "2024-01-01T10:00:00Z"):
    """Build a minimal fake GitLab note object."""
    note = MagicMock()
    note.id = note_id
    note.author = {"username": author_username}
    note.body = body
    note.created_at = created_at
    return note


def _make_provider(bot_username: str = "mybot", notes=None):
    """Build a minimal GitLabProvider-like object without touching the real class."""
    provider = MagicMock()
    provider._bot_username = bot_username

    # Simulate gl.auth() caching the username
    provider.gl = MagicMock()
    provider.gl.user = MagicMock()
    provider.gl.user.username = bot_username

    provider.id_mr = 42
    provider.mr = MagicMock()
    provider.mr.notes = MagicMock()
    provider.mr.notes.list.return_value = notes or []
    return provider


# ---------------------------------------------------------------------------
# Tests for get_conversation_history() on the real GitLabProvider class
# ---------------------------------------------------------------------------

class TestGetConversationHistory:
    """Tests for GitLabProvider.get_conversation_history()."""

    @pytest.fixture(autouse=True)
    def _patch_settings_disabled(self):
        """Default: feature is OFF — individual tests override as needed."""
        with patch("pr_agent.git_providers.gitlab_provider.get_settings") as mock_settings:
            mock_settings.return_value.get.side_effect = self._settings_side_effect(enabled=False)
            yield mock_settings

    @staticmethod
    def _settings_side_effect(enabled: bool, max_comments: int = 20):
        def _get(key, default=None):
            mapping = {
                "GITLAB.ENABLE_HISTORY_CONTEXT": enabled,
                "GITLAB.HISTORY_CONTEXT_MAX_COMMENTS": max_comments,
            }
            return mapping.get(key, default)
        return _get

    # -- import the actual method --
    from pr_agent.git_providers.gitlab_provider import GitLabProvider as _Provider

    def _call(self, provider_mock, enabled=True, max_comments=20):
        """Call the real method bound to our mock provider."""
        with patch("pr_agent.git_providers.gitlab_provider.get_settings") as ms:
            ms.return_value.get.side_effect = self._settings_side_effect(enabled, max_comments)
            ms.return_value.config = MagicMock()
            # Bind the real method to the mock object
            return self._Provider.get_conversation_history(provider_mock)

    # -----------------------------------------------------------------------

    def test_returns_empty_when_disabled(self):
        """When GITLAB.ENABLE_HISTORY_CONTEXT is False, return [] without API calls."""
        provider = _make_provider()
        result = self._call(provider, enabled=False)
        assert result == []
        provider.mr.notes.list.assert_not_called()

    def test_filters_out_notes_without_mention(self):
        """Notes that don't @-mention the bot should be excluded."""
        notes = [
            _make_note(1, "alice", "This looks good", "2024-01-01T09:00:00Z"),
            _make_note(2, "bob",   "Please @mybot review this", "2024-01-01T10:00:00Z"),
        ]
        provider = _make_provider(bot_username="mybot", notes=notes)
        result = self._call(provider, enabled=True)

        assert len(result) == 1
        assert result[0]["author"] == "bob"
        assert "@mybot" in result[0]["body"]

    def test_filters_out_bot_own_notes(self):
        """Notes authored by the bot itself must not appear in history."""
        notes = [
            _make_note(1, "mybot", "@mybot review this", "2024-01-01T10:00:00Z"),
            _make_note(2, "alice", "@mybot please ignore line 5", "2024-01-01T11:00:00Z"),
        ]
        provider = _make_provider(bot_username="mybot", notes=notes)
        result = self._call(provider, enabled=True)

        assert len(result) == 1
        assert result[0]["author"] == "alice"

    def test_respects_max_comments_limit(self):
        """Result must not exceed history_context_max_comments entries."""
        notes = [
            _make_note(i, f"user{i}", f"@mybot comment {i}", f"2024-01-01T{i:02d}:00:00Z")
            for i in range(10)
        ]
        provider = _make_provider(bot_username="mybot", notes=notes)
        result = self._call(provider, enabled=True, max_comments=3)

        assert len(result) == 3

    def test_result_sorted_oldest_first(self):
        """Comments must be returned in ascending chronological order."""
        notes = [
            _make_note(1, "bob",   "@mybot second",  "2024-01-01T12:00:00Z"),
            _make_note(2, "alice", "@mybot first",   "2024-01-01T09:00:00Z"),
            _make_note(3, "carol", "@mybot third",   "2024-01-01T15:00:00Z"),
        ]
        provider = _make_provider(bot_username="mybot", notes=notes)
        result = self._call(provider, enabled=True)

        assert [r["author"] for r in result] == ["alice", "bob", "carol"]

    def test_output_structure(self):
        """Each entry must have exactly author, body, created_at keys."""
        notes = [
            _make_note(1, "alice", "@mybot please review", "2024-01-01T10:00:00Z"),
        ]
        provider = _make_provider(bot_username="mybot", notes=notes)
        result = self._call(provider, enabled=True)

        assert len(result) == 1
        entry = result[0]
        assert set(entry.keys()) == {"author", "body", "created_at"}
        assert entry["author"] == "alice"
        assert entry["body"] == "@mybot please review"
        assert entry["created_at"] == "2024-01-01T10:00:00Z"

    def test_returns_empty_on_api_error(self):
        """Any API error must be swallowed gracefully — not raise to the caller."""
        provider = _make_provider(bot_username="mybot")
        provider.mr.notes.list.side_effect = Exception("GitLab API error")
        result = self._call(provider, enabled=True)
        assert result == []

    def test_all_noted_no_mentions(self):
        """If no note mentions the bot, result must be empty list."""
        notes = [
            _make_note(1, "alice", "LGTM!",              "2024-01-01T09:00:00Z"),
            _make_note(2, "bob",   "Please fix the bug.", "2024-01-01T10:00:00Z"),
        ]
        provider = _make_provider(bot_username="mybot", notes=notes)
        result = self._call(provider, enabled=True)
        assert result == []

    def test_body_is_stripped(self):
        """Body whitespace should be stripped in the output."""
        notes = [
            _make_note(1, "alice", "  @mybot ignore line 3  \n", "2024-01-01T10:00:00Z"),
        ]
        provider = _make_provider(bot_username="mybot", notes=notes)
        result = self._call(provider, enabled=True)
        assert result[0]["body"] == "@mybot ignore line 3"


# ---------------------------------------------------------------------------
# Tests for the _get_gitlab_history_context() helper in pr_reviewer.py
# ---------------------------------------------------------------------------

class TestGetGitlabHistoryContextHelper:
    """Tests for the module-level helper used by PRReviewer and PRCodeSuggestions."""

    @staticmethod
    def _get_helper():
        from pr_agent.tools.pr_reviewer import _get_gitlab_history_context
        return _get_gitlab_history_context

    def test_returns_empty_when_feature_disabled(self):
        provider = MagicMock()
        helper = self._get_helper()
        with patch("pr_agent.tools.pr_reviewer.get_settings") as ms:
            ms.return_value.get.return_value = False
            result = helper(provider)
        assert result == []
        provider.get_conversation_history.assert_not_called()

    def test_returns_empty_when_provider_has_no_method(self):
        provider = MagicMock(spec=[])  # no attributes
        helper = self._get_helper()
        with patch("pr_agent.tools.pr_reviewer.get_settings") as ms:
            ms.return_value.get.return_value = True
            result = helper(provider)
        assert result == []

    def test_delegates_to_provider_when_enabled(self):
        fake_history = [{"author": "alice", "body": "@bot fix this", "created_at": "2024-01-01"}]
        provider = MagicMock()
        provider.get_conversation_history.return_value = fake_history
        helper = self._get_helper()
        with patch("pr_agent.tools.pr_reviewer.get_settings") as ms:
            ms.return_value.get.return_value = True
            result = helper(provider)
        assert result == fake_history

    def test_returns_empty_on_provider_exception(self):
        provider = MagicMock()
        provider.get_conversation_history.side_effect = RuntimeError("network error")
        helper = self._get_helper()
        with patch("pr_agent.tools.pr_reviewer.get_settings") as ms:
            ms.return_value.get.return_value = True
            result = helper(provider)
        assert result == []
