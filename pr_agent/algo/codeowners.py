import re
from dataclasses import dataclass, field

from pr_agent.log import get_logger

# Locations GitLab reads CODEOWNERS from, in priority order. The first file found is used.
CODEOWNERS_FILE_PATHS = ("CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS")

# Access levels for the `@@role` owner form. GitLab matches only direct members with exactly this role.
ROLE_ACCESS_LEVELS = {"developer": 30, "maintainer": 40, "owner": 50}

_SECTION_RE = re.compile(r"^\^?\[(?P<name>[^\]]+)\](?:\[(?P<approvals>\d+)\])?(?P<rest>.*)$")


@dataclass(frozen=True)
class CodeOwnerRule:
    """One CODEOWNERS line. `owners` holds lowercase names without '@', `@@role` for role owners, and
    the full address for email owners. Empty means the matched paths are excluded from approval (`!pattern`)."""

    section: str
    pattern: str
    owners: tuple[str, ...]
    approvals_required: int = 1
    regex: re.Pattern = field(compare=False, repr=False, default=None)


def _owner_names(tokens: list[str]) -> tuple[str, ...]:
    # Owners are `@user`, `@group`, `@group/subgroup`, `@@role` (plural accepted) or an email address.
    owners = []
    for token in tokens:
        if token.startswith("@@"):
            role = token[2:].lower()
            owners.append("@@" + (role.removesuffix("s")))
        elif "@" in token:
            owners.append(token.removeprefix("@").lower())
    return tuple(owners)


def _glob_to_regex(glob: str) -> str:
    out = []
    index = 0
    while index < len(glob):
        if glob.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if glob.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        char = glob[index]
        if char == "[" and (end := glob.find("]", index)) != -1:
            # gitignore writes a negated class as `[!abc]`, while Python regex uses `[^abc]`.
            body = glob[index + 1:end]
            out.append("[^" + body[1:] + "]" if body.startswith("!") else "[" + body + "]")
            index = end + 1
            continue
        out.append({"*": "[^/]*", "?": "[^/]"}.get(char, re.escape(char)))
        index += 1
    return "".join(out)


def _pattern_regex(pattern: str) -> re.Pattern:
    # A pattern with a slash before its last character is anchored to the repository root, as in gitignore.
    # Otherwise it matches at any depth. A matching directory also matches every file under it.
    anchored = pattern.startswith("/") or "/" in pattern.strip("/")
    prefix = "" if anchored else "(?:.*/)?"
    return re.compile(f"^{prefix}{_glob_to_regex(pattern.strip('/'))}(?:/.*)?$")


def parse_codeowners(text: str) -> list[CodeOwnerRule]:
    """Parse CODEOWNERS text into rules in file order.

    Supports `[Section]` and optional `^[Section]` headers, `[Section][N]` for N required approvals, and owners on
    a section header, which become a default rule for every file in that section. A `!pattern` line excludes the
    matched paths from approval. Blank lines and `#` comments are skipped, and an entry without owners is invalid
    in GitLab, so it is skipped too.
    """
    rules = []
    section = ""
    approvals_required = 1
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        header = _SECTION_RE.match(line)
        # A header carries only owners after the brackets. `[Dd]ocs/ @team` is a pattern, not a section named `Dd`.
        if header and all("@" in token for token in header.group("rest").split()):
            section = header.group("name").strip()
            approvals_required = int(header.group("approvals") or 1)
            owners = _owner_names(header.group("rest").split())
            if owners:
                rules.append(CodeOwnerRule(section, "*", owners, approvals_required, _pattern_regex("*")))
            continue
        tokens = line.split()
        pattern = tokens[0]
        excluded = pattern.startswith("!")
        pattern = pattern.removeprefix("!")
        owners = () if excluded else _owner_names(tokens[1:])
        if not excluded and not owners:
            continue
        try:
            regex = _pattern_regex(pattern)
        except re.error as e:
            get_logger().warning(f"Skipping CODEOWNERS line with an invalid pattern '{pattern}': {e}")
            continue
        rules.append(CodeOwnerRule(section, pattern, owners, approvals_required, regex))
    return rules


def match_last_rule_per_section(rules: list[CodeOwnerRule], path: str) -> dict[str, CodeOwnerRule]:
    """Return the last matching rule for each section. Rules later in the file override earlier ones."""
    matched = {}
    for rule in rules:
        if rule.regex.match(path):
            matched[rule.section] = rule
    return matched


def required_reviews(rules: list[CodeOwnerRule], paths: list[str]) -> dict[CodeOwnerRule, list[str]]:
    """Map each rule that requires owners to the changed paths it governs."""
    required: dict[CodeOwnerRule, list[str]] = {}
    for path in paths:
        for rule in match_last_rule_per_section(rules, path).values():
            if rule.owners:
                required.setdefault(rule, []).append(path)
    return required
