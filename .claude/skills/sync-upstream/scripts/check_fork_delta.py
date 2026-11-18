#!/usr/bin/env python3
"""Check that every line the fork added before the merge still exists after it.

Compares the fork delta (merge-base -> pre-merge HEAD) against the current working tree, following upstream
file and directory renames. Run from the repository root, during or after conflict resolution:

    python3 .claude/skills/sync-upstream/scripts/check_fork_delta.py [--all | --stale-paths]

--stale-paths instead lists references to directories upstream renamed (e.g. old import paths, mock.patch targets).

Reports, per file:
  - LOST: lines the fork added that no longer appear in the mapped file, with no close match either;
  - FUZZY (informational, not counted): a lost line with a close match (>= 85% similar), printed next to it; usually
    an upstream rename such as a variable or import path, but read each one;
  - BACK: lines the fork deleted that reappeared in the mapped file;
  - files the fork added that are missing, and files the fork deleted that are back.

A finding is acknowledged by a TSV line in <git-dir>/upstream-sync/ack.tsv:
    <kind>\t<path>\t<stripped line or "*">\t<reason>
where kind is LOST, BACK, MISSING_FILE or RESTORED_FILE, and "*" acknowledges every line of that kind in the
path. Exit code 0 means every finding is acknowledged; 1 means some are not (they are printed).
"""
import difflib
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

MIN_LEN = 6
FUZZY_CUTOFF = 0.85
TRIVIAL = re.compile(r"^[\s\-=#*`|{}\[\]()<>/.,:;'\"]*$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def load_state(state_dir: Path) -> dict:
    state = {}
    for line in (state_dir / "state.env").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            state[key] = value
    return state


def significant(line: str) -> bool:
    s = line.strip()
    return len(s) >= MIN_LEN and not TRIVIAL.match(s)


def rename_maps(base: str, upstream: str):
    """Return (exact file renames, directory prefix renames) upstream made since the merge-base."""
    files, dirs = {}, Counter()
    for row in git("diff", "--name-status", "-M", "--diff-filter=R", base, upstream).splitlines():
        _, old, new = row.split("\t")
        files[old] = new
        old_dir, new_dir = os.path.dirname(old), os.path.dirname(new)
        if old_dir != new_dir and os.path.basename(old) == os.path.basename(new):
            dirs[(old_dir, new_dir)] += 1
    prefixes = sorted({pair for pair, n in dirs.items() if n >= 2}, key=lambda p: -len(p[0]))
    return files, prefixes


def map_path(path: str, files: dict, prefixes: list) -> str:
    if path in files:
        return files[path]
    for old_dir, new_dir in prefixes:
        if path.startswith(old_dir + "/"):
            return new_dir + path[len(old_dir):]
    return path


def line_variants(line: str, prefixes: list) -> set:
    """The stripped line plus forms with renamed directories substituted (path and dotted-module forms)."""
    s = line.strip()
    variants = {s}
    for old_dir, new_dir in prefixes:
        for old, new in ((old_dir, new_dir), (old_dir.replace("/", "."), new_dir.replace("/", "."))):
            variants |= {v.replace(old, new) for v in list(variants)}
        old_leaf, new_leaf = os.path.basename(old_dir), os.path.basename(new_dir)
        variants |= {v.replace(f"{old_leaf}/", f"{new_leaf}/") for v in list(variants)}
    return variants


def fork_hunks(base: str, head: str):
    """Yield (old_path, new_path, added_lines, deleted_lines) for each file in the fork delta."""
    diff = git("diff", "-M", "--no-color", "--unified=0", base, head)
    old_path = new_path = None
    added, deleted = [], []
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            if new_path or old_path:
                yield old_path, new_path, added, deleted
            old_path = new_path = None
            added, deleted = [], []
        elif raw.startswith("--- "):
            old_path = None if raw[4:] == "/dev/null" else raw[6:]
        elif raw.startswith("+++ "):
            new_path = None if raw[4:] == "/dev/null" else raw[6:]
        elif raw.startswith("+") and not raw.startswith("+++"):
            added.append(raw[1:])
        elif raw.startswith("-") and not raw.startswith("---"):
            deleted.append(raw[1:])
    if new_path or old_path:
        yield old_path, new_path, added, deleted


def load_acks(path: Path) -> dict:
    acks = defaultdict(set)
    if path.exists():
        for row in path.read_text().splitlines():
            parts = row.split("\t")
            if len(parts) >= 4 and not row.startswith("#"):
                acks[(parts[0], parts[1])].add(parts[2])
    return acks


def stale_paths(prefixes: list) -> int:
    """Print references to directories upstream renamed (old path and dotted-module forms); return 1 if any."""
    found = 0
    for old_dir, _ in prefixes:
        for needle in (old_dir + "/", old_dir.replace("/", ".") + "."):
            hits = subprocess.run(["git", "grep", "-nF", needle, "--", ".", ":!CHANGELOG.md", ":!.claude"],
                                  capture_output=True, text=True).stdout
            # A URL into another repository keeps its own paths.
            hits = "".join(h + "\n" for h in hits.splitlines() if "://" not in h)
            if hits:
                found = 1
                print(f"Stale references to renamed {needle!r}:\n{hits}")
    return found


def main() -> int:
    show_all = "--all" in sys.argv
    os.chdir(git("rev-parse", "--show-toplevel").strip())
    state_dir = Path(git("rev-parse", "--absolute-git-dir").strip()) / "upstream-sync"
    state = load_state(state_dir)
    base, old_head, upstream = state["MERGE_BASE"], state["OLD_HEAD"], state["UPSTREAM_SHA"]
    files, prefixes = rename_maps(base, upstream)
    if "--stale-paths" in sys.argv:
        print("Upstream directory renames: " + (", ".join(f"{o} -> {n}" for o, n in prefixes) or "none"))
        return stale_paths(prefixes)
    acks = load_acks(state_dir / "ack.tsv")

    def acked(kind: str, path: str, line: str) -> bool:
        keys = acks.get((kind, path), set())
        return "*" in keys or line.strip() in keys

    findings = []  # (kind, path, line)
    fuzzy = []  # (path, fork line, closest current line)
    for old_path, new_path, added, deleted in fork_hunks(base, old_head):
        if (new_path or old_path).startswith(".claude/"):
            continue  # the sync tooling itself; it changes during the run
        if new_path is None:  # fork deleted the file
            target = map_path(old_path, files, prefixes)
            if Path(target).exists():
                findings.append(("RESTORED_FILE", target, ""))
            continue
        target = map_path(new_path, files, prefixes)
        if not Path(target).exists():
            if old_path is None or old_path != new_path:
                findings.append(("MISSING_FILE", target, ""))
            else:
                findings.append(("MISSING_FILE", target, "(file the fork modified is gone; upstream deleted it?)"))
            continue
        try:
            current_lines = [ln.strip() for ln in Path(target).read_text(errors="replace").splitlines()]
            current = set(current_lines)
        except IsADirectoryError:
            continue
        old_fork = {ln.strip() for ln in git("show", f"{old_head}:{new_path}").splitlines()}
        for line in added:
            if significant(line) and not (line_variants(line, prefixes) & current):
                close = difflib.get_close_matches(line.strip(), current_lines, n=1, cutoff=FUZZY_CUTOFF)
                if close:
                    fuzzy.append((target, line.strip(), close[0]))
                else:
                    findings.append(("LOST", target, line.strip()))
        findings.extend(("BACK", target, line.strip()) for line in deleted
                        if significant(line) and line.strip() not in old_fork and line.strip() in current)

    if fuzzy:
        print("# FUZZY: fork lines whose closest current line is a near match (not counted; skim for real changes)")
        for path, line, close in fuzzy:
            print(f"  {path}\n    fork: {line}\n    now:  {close}")
    open_findings = [f for f in findings if not acked(*f)]
    shown = findings if show_all else open_findings
    by_file = defaultdict(list)
    for kind, path, line in shown:
        by_file[path].append((kind, line))
    for path in sorted(by_file):
        print(f"\n## {path}")
        for kind, line in by_file[path]:
            mark = "ok " if (kind, path, line) not in open_findings else ""
            print(f"  {mark}{kind}: {line}")
    counts = Counter(kind for kind, _, _ in open_findings)
    print(f"\nfindings={len(findings)} unacknowledged={len(open_findings)} {dict(counts)} fuzzy={len(fuzzy)}")
    print(f"acknowledge in: {state_dir / 'ack.tsv'}")
    return 1 if open_findings else 0


if __name__ == "__main__":
    sys.exit(main())
