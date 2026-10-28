import asyncio
import hashlib
from dataclasses import dataclass

from pr_agent.algo.codeowners import ROLE_ACCESS_LEVELS, CodeOwnerRule, parse_codeowners, required_reviews
from pr_agent.config_loader import get_settings
from pr_agent.git_providers import get_git_provider
from pr_agent.log import get_logger

MAX_LISTED_FILES = 10
MARKER_PREFIX = "pr-agent:codeowners"


@dataclass
class PendingReview:
    rule: CodeOwnerRule
    paths: list[str]
    approved_count: int
    mentions: list[str]


class PRCodeOwners:
    """Open an unresolved thread on a merge request when changed files need a code owner's approval.

    The check is deterministic and does not call a model. It reads CODEOWNERS from the target branch, matches it
    against the changed files, and compares the rules with the merge request's approvals.
    """

    def __init__(self, pr_url: str, args: list = None, ai_handler=None):
        self.git_provider = get_git_provider()(pr_url)

    async def run(self):
        if not get_settings().get("CODEOWNERS.ENABLE_CODEOWNERS_CHECK", False):
            get_logger().debug("CODEOWNERS check is disabled")
            return None
        if not hasattr(self.git_provider, "get_codeowners_content"):
            get_logger().info("CODEOWNERS check is not supported by this git provider")
            return None
        return await asyncio.to_thread(self._check)

    def _check(self) -> bool:
        rules = parse_codeowners(self.git_provider.get_codeowners_content())
        if not rules:
            return True
        # Both sides of a rename count, so moving a file out of an owned path still needs review.
        paths = sorted({
            change[key] for change in self.git_provider.get_pr_file_paths() for key in ("old_path", "new_path")
            if change.get(key)
        })
        required = required_reviews(rules, paths)
        if not required:
            return True
        approvers = self.git_provider.get_codeowner_approvers()
        if approvers is None:
            return False
        pending = self._pending_reviews(required, approvers)
        if not pending:
            get_logger().info("All CODEOWNERS approvals are present")
            return True
        if not get_settings().get("CONFIG.PUBLISH_OUTPUT", True):
            get_logger().info("Skipping CODEOWNERS thread: publish_output is disabled")
            return True

        marker = f"{MARKER_PREFIX} key={_pending_key(pending)}"
        existing = self.git_provider.find_codeowners_thread(marker)
        if existing is None:
            # Publishing without knowing whether the thread exists would duplicate it on every run.
            return False
        if existing:
            get_logger().info("CODEOWNERS thread already exists for the same pending reviews")
            return True
        self.git_provider.publish_codeowners_thread(_render_thread(pending, marker))
        return True

    def _pending_reviews(self, required: dict[CodeOwnerRule, list[str]], approvers: set[str]) -> list[PendingReview]:
        members_cache: dict[str, set[str] | None] = {}

        def members_of(owner: str) -> set[str] | None:
            if owner not in members_cache:
                if owner.startswith("@@"):
                    level = ROLE_ACCESS_LEVELS.get(owner[2:])
                    members_cache[owner] = self.git_provider.get_role_member_usernames(level) if level else None
                else:
                    members_cache[owner] = self.git_provider.get_group_member_usernames(owner)
            return members_cache[owner]

        pending = []
        for rule, paths in required.items():
            # Email owners cannot be matched to GitLab approvers, so they are neither counted nor mentioned.
            owners = [owner for owner in rule.owners if "@" not in owner or owner.startswith("@@")]
            if not owners:
                get_logger().debug(f"CODEOWNERS rule '{rule.pattern}' has no verifiable owner; skipped")
                continue
            approved_users: set[str] = set()
            mentions: list[str] = []
            for owner in owners:
                if not owner.startswith("@@") and owner in approvers:
                    approved_users.add(owner)
                    continue
                hits = (members_of(owner) or set()) & approvers
                if hits:
                    approved_users |= hits
                else:
                    mentions.append(owner)
            if len(approved_users) >= rule.approvals_required:
                continue
            pending.append(PendingReview(rule, sorted(paths), len(approved_users), mentions))
        return pending


def _pending_key(pending: list[PendingReview]) -> str:
    # The key ignores approval counts, so a partial approval does not reopen a thread that is already open.
    identities = sorted(
        f"{item.rule.section}|{item.rule.pattern}|{','.join(sorted(item.mentions))}" for item in pending
    )
    return hashlib.sha256("\n".join(identities).encode()).hexdigest()[:16]


def _mention(owner: str) -> str:
    # Role owners are already stored as `@@role`, so only user and group owners get a leading `@` here.
    return owner if owner.startswith("@@") else f"@{owner}"


def _render_thread(pending: list[PendingReview], marker: str) -> str:
    lines = [
        "### Cần Code Owner review",
        "",
        "Các file thay đổi trong MR này thuộc phạm vi CODEOWNERS nhưng chưa đủ approve từ Code Owner. "
        "Thread này đang chặn MR cho đến khi Code Owner review và approve.",
        "",
    ]
    for item in pending:
        label = item.rule.section or "CODEOWNERS"
        mentions = " ".join(_mention(owner) for owner in item.mentions)
        lines.append(
            f"- **{label}** (`{item.rule.pattern}`): cần approve từ {mentions} "
            f"(đã có {item.approved_count}/{item.rule.approvals_required})"
        )
        listed = ", ".join(f"`{path}`" for path in item.paths[:MAX_LISTED_FILES])
        hidden = len(item.paths) - MAX_LISTED_FILES
        lines.append(f"  - File: {listed}" + (f" và {hidden} file khác" if hidden > 0 else ""))
    lines += ["", "Hãy resolve thread này sau khi Code Owner đã review và approve.", "", f"<!-- {marker} -->"]
    return "\n".join(lines)
