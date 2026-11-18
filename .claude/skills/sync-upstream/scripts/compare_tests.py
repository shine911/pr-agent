#!/usr/bin/env python3
"""Compare the post-merge unit-suite run against the pre-merge baseline.

    python3 .claude/skills/sync-upstream/scripts/compare_tests.py [after.xml]

Defaults to <git-dir>/upstream-sync/{baseline.xml,after.xml}. Prints:
  - REGRESSED: passed before, failed/errored now;
  - VANISHED: passed before, absent now (a same-named test elsewhere is shown as a candidate rename);
  - FAILING: failing now and not passing before (new or upstream tests).
Exit code 1 when any REGRESSED, VANISHED-without-candidate or FAILING test exists.
"""
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def load(path: Path) -> dict:
    results = {}
    for case in ET.parse(path).iter("testcase"):
        key = f"{case.get('classname')}::{case.get('name')}"
        status = "passed"
        for child in case:
            if child.tag in ("failure", "error"):
                status = "failed"
            elif child.tag == "skipped":
                status = "skipped"
        results[key] = status
    return results


def main() -> int:
    git_dir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], check=True, capture_output=True,
                             text=True).stdout.strip()
    state_dir = Path(git_dir) / "upstream-sync"
    before = load(state_dir / "baseline.xml")
    after = load(Path(sys.argv[1]) if len(sys.argv) > 1 else state_dir / "after.xml")
    by_name = defaultdict(list)
    for key in after:
        by_name[key.split("::", 1)[1]].append(key)

    regressed = [k for k, s in before.items() if s == "passed" and after.get(k) == "failed"]
    vanished = [k for k, s in before.items() if s == "passed" and k not in after]
    failing = [k for k, s in after.items() if s == "failed" and before.get(k) != "passed"]
    blocking = len(regressed) + len(failing)

    def count(results: dict, status: str) -> int:
        return sum(1 for s in results.values() if s == status)

    for label, res in (("before", before), ("after", after)):
        print(f"{label}: passed={count(res, 'passed')} failed={count(res, 'failed')} skipped={count(res, 'skipped')}")
    for key in regressed:
        print(f"REGRESSED {key}")
    for key in failing:
        print(f"FAILING   {key}")
    for key in vanished:
        candidates = [c for c in by_name.get(key.split("::", 1)[1], []) if after[c] == "passed"]
        if candidates:
            print(f"VANISHED  {key}  -> candidate: {', '.join(candidates[:3])}")
        else:
            blocking += 1
            print(f"VANISHED  {key}  (no same-named passing test)")
    print(f"regressed={len(regressed)} failing={len(failing)} vanished={len(vanished)}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
