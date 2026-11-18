#!/usr/bin/env bash
# Record the pre-merge state the post-merge checks compare against.
# Usage: snapshot.sh [--skip-tests]
# Writes <git-dir>/upstream-sync/{state.env,inventory.md,baseline.xml,baseline-packaging.txt}
# and creates the backup tag backup/pre-upstream-sync-<timestamp>.
set -euo pipefail

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
UPSTREAM_URL="https://github.com/The-PR-Agent/pr-agent.git"

cd "$(git rev-parse --show-toplevel)"
STATE_DIR="$(git rev-parse --absolute-git-dir)/upstream-sync"
mkdir -p "$STATE_DIR"

if [ -e "$(git rev-parse --git-dir)/MERGE_HEAD" ]; then
  echo "A merge is already in progress; finish or abort it first." >&2; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Tracked files have uncommitted changes; commit or stash them first:" >&2
  git status --short --untracked-files=no >&2; exit 1
fi

if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
fi
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_BRANCH" --quiet

UPSTREAM_REF="$UPSTREAM_REMOTE/$UPSTREAM_BRANCH"
OLD_HEAD="$(git rev-parse HEAD)"
UPSTREAM_SHA="$(git rev-parse "$UPSTREAM_REF")"
MERGE_BASE="$(git merge-base HEAD "$UPSTREAM_REF")"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_TAG="backup/pre-upstream-sync-$TS"
git tag "$BACKUP_TAG" "$OLD_HEAD"

cat > "$STATE_DIR/state.env" <<EOF
OLD_HEAD=$OLD_HEAD
UPSTREAM_REF=$UPSTREAM_REF
UPSTREAM_SHA=$UPSTREAM_SHA
MERGE_BASE=$MERGE_BASE
BACKUP_TAG=$BACKUP_TAG
BRANCH=$(git branch --show-current)
EOF

{
  echo "# Fork inventory ($TS)"
  echo
  echo "- branch: $(git branch --show-current) @ $OLD_HEAD"
  echo "- upstream: $UPSTREAM_REF @ $UPSTREAM_SHA"
  echo "- merge-base: $MERGE_BASE"
  echo "- upstream commits to merge: $(git rev-list --count "$MERGE_BASE..$UPSTREAM_SHA")"
  echo "- fork commits not in upstream: $(git rev-list --count "$UPSTREAM_SHA..$OLD_HEAD")"
  echo
  echo "## Fork-only commits (no merges)"
  echo
  git log --no-merges --format='- %h %s' "$MERGE_BASE..$OLD_HEAD"
  echo
  echo "## Files the fork changed vs merge-base (A=added M=modified D=deleted R=renamed)"
  echo
  git diff --name-status -M "$MERGE_BASE" "$OLD_HEAD" | sed 's/^/    /'
  echo
  echo "## Upstream renames since merge-base (fork paths under these move too)"
  echo
  git diff --name-status -M --diff-filter=R "$MERGE_BASE" "$UPSTREAM_SHA" | sed 's/^/    /'
  echo
  echo "## Upstream deletions of files the fork touched"
  echo
  comm -12 <(git diff --name-only --diff-filter=D -M "$MERGE_BASE" "$UPSTREAM_SHA" | sort) \
           <(git diff --name-only "$MERGE_BASE" "$OLD_HEAD" | sort) | sed 's/^/    /'
  echo
  echo "## Predicted conflicts"
  echo
  git merge-tree --write-tree --name-only "$OLD_HEAD" "$UPSTREAM_SHA" 2>/dev/null | grep '^CONFLICT' | sed 's/^/    /' || true
} > "$STATE_DIR/inventory.md"
echo "Inventory: $STATE_DIR/inventory.md"

if [ "${1:-}" != "--skip-tests" ]; then
  echo "Running baseline unit suite (junit -> baseline.xml)..."
  PYTHONPATH=. uv run pytest tests/unittest -q -p no:cacheprovider --junitxml="$STATE_DIR/baseline.xml" \
    > "$STATE_DIR/baseline.log" 2>&1 || true
  tail -n 3 "$STATE_DIR/baseline.log"
  PYTHONPATH=. uv run pytest -q tests/packaging/test_help_docs_package.py > "$STATE_DIR/baseline-packaging.txt" 2>&1 \
    || true
  tail -n 1 "$STATE_DIR/baseline-packaging.txt"
fi

echo "Backup tag: $BACKUP_TAG"
echo "State: $STATE_DIR/state.env"
