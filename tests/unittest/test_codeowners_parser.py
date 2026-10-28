import pytest

from pr_agent.algo.codeowners import match_last_rule_per_section, parse_codeowners, required_reviews


def _owners_for(text: str, path: str) -> dict[str, tuple[str, ...]]:
    rules = parse_codeowners(text)
    return {section: rule.owners for section, rule in match_last_rule_per_section(rules, path).items()}


def test_comments_and_blank_lines_are_ignored():
    rules = parse_codeowners("# header\n\n   \n*.py @alice\n# trailing")

    assert [(rule.pattern, rule.owners) for rule in rules] == [("*.py", ("alice",))]


@pytest.mark.parametrize("path, expected", [
    ("app.py", True),
    ("src/deep/app.py", True),
    ("app.js", False),
])
def test_extension_pattern_without_slash_matches_at_any_depth(path, expected):
    matched = match_last_rule_per_section(parse_codeowners("*.py @alice"), path)

    assert bool(matched) is expected


@pytest.mark.parametrize("pattern, path, expected", [
    ("/docs/", "docs/readme.md", True),
    ("/docs/", "src/docs/readme.md", False),
    ("docs/", "src/docs/readme.md", True),
    ("docs/", "docs", True),
    ("/apps/*/README.md", "apps/web/README.md", True),
    ("/apps/*/README.md", "apps/web/deep/README.md", False),
    ("**/logs", "a/b/logs/x.txt", True),
    ("**/logs", "logs", True),
    ("docs/**", "docs/a/b.md", True),
    ("a/**/b", "a/b", True),
    ("a/**/b", "a/x/y/b", True),
    ("file?.txt", "file1.txt", True),
    ("file?.txt", "file12.txt", False),
    ("file[ab].txt", "filea.txt", True),
    ("file[ab].txt", "filec.txt", False),
    ("lib", "lib2/x.py", False),
])
def test_gitignore_style_patterns(pattern, path, expected):
    matched = match_last_rule_per_section(parse_codeowners(f"{pattern} @alice"), path)

    assert bool(matched) is expected


def test_last_matching_rule_wins_within_a_section():
    text = "* @everyone\n/src/ @backend\n/src/api/ @api-team"

    assert _owners_for(text, "src/api/handler.py") == {"": ("api-team",)}
    assert _owners_for(text, "src/main.py") == {"": ("backend",)}
    assert _owners_for(text, "README.md") == {"": ("everyone",)}


def test_entry_without_owners_is_invalid_and_skipped():
    text = "* @alice\n/vendor/"

    assert _owners_for(text, "vendor/lib.c") == {"": ("alice",)}


def test_bang_pattern_excludes_paths_from_approval():
    text = "* @alice\n!/vendor/"

    assert _owners_for(text, "vendor/lib.c") == {"": ()}
    assert _owners_for(text, "src/app.py") == {"": ("alice",)}


def test_bang_pattern_is_scoped_to_its_section():
    text = "[Core]\n* @core\n[Vendor]\n!/vendor/"

    assert _owners_for(text, "vendor/lib.c") == {"Core": ("core",), "Vendor": ()}


def test_role_owners_are_normalised_to_singular():
    rules = parse_codeowners("*.py @@developers @@Maintainer")

    assert rules[0].owners == ("@@developer", "@@maintainer")


def test_email_owner_is_kept_with_its_at_sign():
    rules = parse_codeowners("*.py dev@example.com")

    assert rules[0].owners == ("dev@example.com",)


def test_each_section_resolves_its_own_last_match():
    text = "[Backend]\n* @backend-team\n/api/ @api-lead\n[Frontend]\n*.tsx @front-team"

    assert _owners_for(text, "api/routes.py") == {"Backend": ("api-lead",)}
    assert _owners_for(text, "web/app.tsx") == {"Backend": ("backend-team",), "Frontend": ("front-team",)}


def test_section_header_owners_become_a_default_rule():
    text = "[Docs] @docs-team\n/docs/api/ @api-writer"

    assert _owners_for(text, "docs/guide.md") == {"Docs": ("docs-team",)}
    assert _owners_for(text, "docs/api/index.md") == {"Docs": ("api-writer",)}


def test_optional_section_header_is_parsed():
    rules = parse_codeowners("^[Optional] @alice")

    assert [(rule.section, rule.pattern, rule.owners) for rule in rules] == [("Optional", "*", ("alice",))]


def test_approvals_required_is_read_from_section_header():
    rules = parse_codeowners("[Security][2] @sec-group\n*.yaml @sec-group @ops")

    assert all(rule.approvals_required == 2 for rule in rules)


def test_owner_names_are_lowercased_and_email_owners_kept():
    rules = parse_codeowners("*.py @Alice @Platform/Core dev@example.com")

    assert rules[0].owners == ("alice", "platform/core", "dev@example.com")


def test_required_reviews_groups_changed_paths_by_rule():
    rules = parse_codeowners("*.py @alice\n*.md\n/vendor/ @bob")

    required = required_reviews(rules, ["a.py", "b.py", "README.md", "vendor/x.c", "c.txt"])

    summary = {rule.pattern: paths for rule, paths in required.items()}
    assert summary == {"*.py": ["a.py", "b.py"], "/vendor/": ["vendor/x.c"]}


def test_bracket_pattern_at_line_start_is_a_pattern_not_a_section():
    rules = parse_codeowners("[Dd]ocs/ @docs-team")

    assert [(rule.section, rule.pattern, rule.owners) for rule in rules] == [("", "[Dd]ocs/", ("docs-team",))]


@pytest.mark.parametrize("path, expected", [
    ("src/b.py", True),
    ("src/a.py", False),
])
def test_negated_character_class_follows_gitignore(path, expected):
    matched = match_last_rule_per_section(parse_codeowners("src/[!a]*.py @alice"), path)

    assert bool(matched) is expected


def test_invalid_character_class_skips_only_that_line():
    rules = parse_codeowners("[z-a]*.py @broken\n*.md @docs")

    assert [rule.pattern for rule in rules] == ["*.md"]
