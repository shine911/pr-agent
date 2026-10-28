import asyncio
from unittest.mock import MagicMock, patch

import pytest

from pr_agent.tools.pr_codeowners import MARKER_PREFIX, PRCodeOwners

CODEOWNERS_TEXT = "*.py @alice\n/infra/ @ops-group\n*.md @docs-lead"


def _settings(enabled=True, publish=True):
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: {
        "CODEOWNERS.ENABLE_CODEOWNERS_CHECK": enabled,
        "CONFIG.PUBLISH_OUTPUT": publish,
    }.get(key, default)
    return settings


def _provider(paths, approvers, groups=None, codeowners=CODEOWNERS_TEXT, thread_exists=False, roles=None):
    provider = MagicMock()
    provider.get_codeowners_content.return_value = codeowners
    provider.get_pr_file_paths.return_value = [{"old_path": path, "new_path": path} for path in paths]
    provider.get_codeowner_approvers.return_value = approvers
    provider.get_group_member_usernames.side_effect = lambda name: (groups or {}).get(name)
    provider.get_role_member_usernames.side_effect = lambda level: (roles or {}).get(level)
    provider.find_codeowners_thread.return_value = thread_exists
    return provider


def _run(provider, settings=None):
    with patch("pr_agent.tools.pr_codeowners.get_git_provider", return_value=lambda pr_url: provider), \
            patch("pr_agent.tools.pr_codeowners.get_settings", return_value=settings or _settings()):
        tool = PRCodeOwners("https://gitlab.example.com/group/project/-/merge_requests/1")
        return asyncio.run(tool.run())


def test_disabled_check_does_nothing():
    provider = _provider(["a.py"], approvers=set())

    _run(provider, _settings(enabled=False))

    provider.publish_codeowners_thread.assert_not_called()
    provider.get_codeowners_content.assert_not_called()


def test_no_codeowners_file_publishes_nothing():
    provider = _provider(["a.py"], approvers=set(), codeowners="")

    _run(provider)

    provider.publish_codeowners_thread.assert_not_called()


def test_renamed_file_out_of_owned_path_still_needs_review():
    provider = _provider([], approvers=set(), codeowners="/infra/ @ops")
    provider.get_pr_file_paths.return_value = [{"old_path": "infra/main.tf", "new_path": "docs/main.tf"}]

    _run(provider)

    body = provider.publish_codeowners_thread.call_args.args[0]
    assert "`infra/main.tf`" in body


def test_changed_files_outside_rules_publish_nothing():
    provider = _provider(["src/main.go"], approvers=set())

    _run(provider)

    provider.publish_codeowners_thread.assert_not_called()


def test_missing_owner_approval_opens_thread_mentioning_owner():
    provider = _provider(["a.py"], approvers=set())

    _run(provider)

    provider.publish_codeowners_thread.assert_called_once()
    body = provider.publish_codeowners_thread.call_args.args[0]
    assert "@alice" in body
    assert "`a.py`" in body
    assert f"<!-- {MARKER_PREFIX} key=" in body


def test_owner_approval_suppresses_thread():
    provider = _provider(["a.py"], approvers={"alice"})

    _run(provider)

    provider.publish_codeowners_thread.assert_not_called()


def test_group_member_approval_satisfies_group_owner():
    provider = _provider(["infra/main.tf"], approvers={"carol"}, groups={"ops-group": {"carol", "dave"}})

    _run(provider)

    provider.publish_codeowners_thread.assert_not_called()


def test_group_without_approval_is_mentioned():
    provider = _provider(["infra/main.tf"], approvers={"eve"}, groups={"ops-group": {"carol", "dave"}})

    _run(provider)

    body = provider.publish_codeowners_thread.call_args.args[0]
    assert "@ops-group" in body


def test_every_unapproved_owner_is_mentioned_for_multi_owner_rule():
    provider = _provider(["a.py"], approvers=set(), codeowners="*.py @alice @bob")

    _run(provider)

    body = provider.publish_codeowners_thread.call_args.args[0]
    assert "@alice @bob" in body


def test_approvals_required_counts_distinct_approvers():
    text = "[Security][2] @alice @bob"
    provider = _provider(["a.py"], approvers={"alice"}, codeowners=text)

    _run(provider)

    body = provider.publish_codeowners_thread.call_args.args[0]
    assert "(đã có 1/2)" in body


def test_existing_thread_with_same_key_is_not_duplicated():
    provider = _provider(["a.py"], approvers=set(), thread_exists=True)

    _run(provider)

    provider.publish_codeowners_thread.assert_not_called()


def test_role_owner_approval_by_a_member_with_that_role_satisfies_the_rule():
    provider = _provider(["a.py"], approvers={"maya"}, codeowners="*.py @@maintainers", roles={40: {"maya"}})

    _run(provider)

    provider.get_role_member_usernames.assert_called_with(40)
    provider.publish_codeowners_thread.assert_not_called()


def test_role_owner_without_approval_is_mentioned_with_role_syntax():
    provider = _provider(["a.py"], approvers={"eve"}, codeowners="*.py @@maintainers", roles={40: {"maya"}})

    _run(provider)

    body = provider.publish_codeowners_thread.call_args.args[0]
    assert "@@maintainer" in body
    assert "@@@" not in body


def test_unknown_role_is_mentioned_but_cannot_be_satisfied():
    provider = _provider(["a.py"], approvers={"eve"}, codeowners="*.py @@reporter")

    _run(provider)

    body = provider.publish_codeowners_thread.call_args.args[0]
    assert "@@reporter" in body


def test_bang_exclusion_publishes_nothing_for_excluded_paths():
    provider = _provider(["vendor/lib.c"], approvers=set(), codeowners="* @alice\n!/vendor/")

    _run(provider)

    provider.publish_codeowners_thread.assert_not_called()


def test_email_only_owner_is_not_mentioned():
    provider = _provider(["a.py"], approvers=set(), codeowners="*.py dev@example.com")

    _run(provider)

    provider.publish_codeowners_thread.assert_not_called()


def test_approvals_unreadable_skips_check_without_publishing():
    provider = _provider(["a.py"], approvers=None)

    result = _run(provider)

    assert result is False
    provider.publish_codeowners_thread.assert_not_called()


def test_publish_output_disabled_skips_thread():
    provider = _provider(["a.py"], approvers=set())

    _run(provider, _settings(publish=False))

    provider.publish_codeowners_thread.assert_not_called()


@pytest.mark.parametrize("many_files", [3, 12])
def test_long_file_lists_are_truncated(many_files):
    paths = [f"pkg/mod{i}.py" for i in range(many_files)]
    provider = _provider(paths, approvers=set(), codeowners="*.py @alice")

    _run(provider)

    body = provider.publish_codeowners_thread.call_args.args[0]
    assert ("và 2 file khác" in body) is (many_files == 12)


def test_resolved_thread_for_pending_owner_is_reopened_as_new_thread():
    provider = _provider(["a.py"], approvers=set())
    provider.find_codeowners_thread.return_value = False

    _run(provider)

    provider.publish_codeowners_thread.assert_called_once()


def test_unknown_discussion_state_publishes_nothing():
    provider = _provider(["a.py"], approvers=set())
    provider.find_codeowners_thread.return_value = None

    result = _run(provider)

    assert result is False
    provider.publish_codeowners_thread.assert_not_called()
