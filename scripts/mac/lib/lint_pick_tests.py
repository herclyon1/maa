#!/usr/bin/env python3
"""Print the relay test files lint-repo.sh should run for the change in this checkout.

~/Claude/CLAUDE.md: run only the tests the change reaches directly or indirectly. Until 10-14
lint-repo.sh ran all ~450 relay tests on every call, even for a one-line script edit, and the
sessions waited on that after every small fix.

Selection, base = the merge base with origin/main (or argv[1]):
  1. changed_covered.tests_for(base) - the selector deploy-relay.sh uses: tests that execute a
     changed relay module (relay/tests/test-map.json) plus test files that changed;
  2. plus every test whose text names a changed file outside the relay modules (its basename,
     e.g. disk-tidy.py, lint-repo.sh), which is how the script tests reach their script;
  3. when the selector cannot decide (no map, a test missing from the map, a change outside the
     places it knows), every test - same fallback as deploy.
  When the change touches nothing a test runs or names (docs only), no relay test runs.
Output: one file name per line (test_x.py), or the single word ALL. The reason goes to stderr.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import changed_covered  # noqa: E402

REPO = changed_covered.REPO
TESTS = REPO / "relay" / "tests"
NO_BEHAVIOUR = "没有会改变行为的改动"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout.strip()


def changed_files(base: str) -> list[str]:
    tracked = _git("diff", "--name-only", base, "--").splitlines()
    untracked = _git("ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({f for f in tracked + untracked if f})


def named_by_tests(files: list[str]) -> set[str]:
    names = {Path(f).name for f in files if not f.startswith("relay/tests/") and Path(f).suffix in (".py", ".sh", ".json", ".plist", ".txt", ".md")}
    names.discard("RELEASE-NOTES.md")
    hits = set()
    for t in sorted(TESTS.glob("test_*.py")):
        text = t.read_text(encoding="utf-8", errors="replace")
        if any(n in text for n in names):
            hits.add(t.name)
    return hits


def pick(base: str) -> tuple[list[str] | None, str]:
    picked, why = changed_covered.tests_for(base)
    files = changed_files(base)
    named = named_by_tests(files)
    if picked:
        return sorted(set(picked) | named), f"{why}; plus {len(named)} test(s) naming a changed file"
    if why.startswith(NO_BEHAVIOUR):
        return sorted(named), f"no relay module changed; {len(named)} test(s) name a changed file"
    return None, why


def main(argv: list[str]) -> int:
    base = argv[0] if argv else (_git("merge-base", "HEAD", "origin/main") or "HEAD~1")
    tests, why = pick(base)
    print(why, file=sys.stderr)
    print("ALL" if tests is None else "\n".join(tests))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
