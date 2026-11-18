#!/usr/bin/env bash
# Post-merge gates. Run from anywhere in the repo after resolving conflicts (before or after the merge commit).
# Usage: verify.sh [--fast]   (--fast skips the full unit suite and pre-commit)
# Every gate runs even when an earlier one fails; the summary at the end lists each gate's result.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
SKILL_DIR=".claude/skills/sync-upstream/scripts"
STATE_DIR="$(git rev-parse --absolute-git-dir)/upstream-sync"
# shellcheck disable=SC1091
source "$STATE_DIR/state.env"
FAST="${1:-}"
declare -a SUMMARY=()

gate() {  # gate <name> <command...>
  local name="$1"; shift
  echo; echo "=== $name ==="
  if "$@"; then SUMMARY+=("PASS  $name"); else SUMMARY+=("FAIL  $name"); fi
}

no_conflicts() {
  local unmerged markers
  unmerged="$(git diff --name-only --diff-filter=U)"
  markers="$(git grep -nE '^(<<<<<<<|>>>>>>>) ' -- . ':!third_party' || true)"
  [ -n "$unmerged" ] && echo "Unmerged paths:" && echo "$unmerged"
  [ -n "$markers" ] && echo "Conflict markers:" && echo "$markers"
  [ -z "$unmerged$markers" ]
}

no_refs_to_fork_deletions() {
  local found=0 path name hits
  while IFS=$'\t' read -r status path; do
    [ "$status" = "D" ] || continue
    name="$(basename "$path")"
    # Markdown and comment lines only describe the file; code and config that load it are what break.
    hits="$(git grep -nF "$name" -- . ':!CHANGELOG.md' ':!.claude' ':!*.md' | grep -vE '^[^:]+:[0-9]+:\s*#' || true)"
    if [ -n "$hits" ]; then echo "References to fork-deleted $path:"; echo "$hits"; found=1; fi
  done < <(git diff --name-status --no-renames "$MERGE_BASE" "$OLD_HEAD")
  [ "$found" = 0 ]
}

lock_in_sync() { uv lock --locked; }

ruff_changed() {
  mapfile -t files < <(git diff --name-only --diff-filter=d "$OLD_HEAD" -- '*.py' ':!third_party')
  [ "${#files[@]}" = 0 ] && return 0
  uv run ruff check "${files[@]}"
}

config_reference() {
  local out; out="$(mktemp)"
  uv run python scripts/generate_config_reference.py "$out" >/dev/null &&
    diff -u docs/docs/usage-guide/configuration_reference.md "$out"
}

unit_suite() {
  PYTHONPATH=. uv run pytest tests/unittest -q -p no:cacheprovider --junitxml="$STATE_DIR/after.xml" \
    > "$STATE_DIR/after.log" 2>&1
  tail -n 3 "$STATE_DIR/after.log"
  python3 "$SKILL_DIR/compare_tests.py"
}

packaging() { PYTHONPATH=. uv run pytest -q tests/packaging/test_help_docs_package.py 2>&1 | tail -n 5; }

fork_delta() { python3 "$SKILL_DIR/check_fork_delta.py"; }

pre_commit_changed() {
  mapfile -t files < <(git diff --name-only --diff-filter=d "$OLD_HEAD")
  [ "${#files[@]}" = 0 ] && return 0
  # pre-commit is not a project dependency (CI uses pre-commit/action), so run it as a uv tool.
  uvx pre-commit run --files "${files[@]}"
}

gate "no unmerged paths or conflict markers" no_conflicts
gate "no references to files the fork deleted" no_refs_to_fork_deletions
gate "no stale paths from upstream directory renames" python3 "$SKILL_DIR/check_fork_delta.py" --stale-paths
gate "no method defined twice in one class" python3 "$SKILL_DIR/check_duplicate_defs.py"
gate "uv.lock matches pyproject.toml" lock_in_sync
gate "ruff on changed Python files" ruff_changed
gate "configuration_reference.md matches generator" config_reference
gate "fork delta survives (check_fork_delta.py)" fork_delta
if [ "$FAST" != "--fast" ]; then
  gate "unit suite vs baseline (compare_tests.py)" unit_suite
  gate "packaging test" packaging
  gate "pre-commit on changed files" pre_commit_changed
fi

echo; echo "=== summary ==="
printf '%s\n' "${SUMMARY[@]}"
! printf '%s\n' "${SUMMARY[@]}" | grep -q '^FAIL'
