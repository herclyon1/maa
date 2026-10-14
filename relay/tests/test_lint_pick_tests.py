"""lint-repo.sh runs only the relay tests a change reaches (scripts/mac/lib/lint_pick_tests.py).

Until 10-14 it ran every relay test (about 450 files) on each call, even for a one-line script
edit, and a session waited on that after every small fix; ~/Claude/CLAUDE.md asks to run only the
tests a change reaches. These checks pin the selection: the deploy selector's picks, plus tests
that name a changed script; everything when the selector cannot decide; nothing for a docs-only
change.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/mac/lib"))
import lint_pick_tests as lp  # noqa: E402

fails = []
# Built from parts so this file itself does not name it.
UNNAMED_DOC = "docs/NOT-NAMED-" + "BY-ANY-TEST.md"


def check(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + f" {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(name)


check("a changed script reaches the test that names it",
      "test_disk_tidy.py" in lp.named_by_tests(["scripts/mac/disk-tidy.py"]), True)
check("a doc no test reads names no test", lp.named_by_tests([UNNAMED_DOC]), set())

real_tests_for, real_changed = lp.changed_covered.tests_for, lp.changed_files
try:
    lp.changed_files = lambda base: ["scripts/mac/disk-tidy.py"]
    lp.changed_covered.tests_for = lambda base: ([], lp.NO_BEHAVIOUR + "，全量跑（便宜的保险）")
    got, _ = lp.pick("x")
    check("no relay module changed: only the tests naming the changed script", "test_disk_tidy.py" in got and len(got) < 20, True)
    lp.changed_covered.tests_for = lambda base: (["test_heartbeat.py"], "picked")
    got, _ = lp.pick("x")
    check("selector picks plus naming tests", set(got) >= {"test_heartbeat.py", "test_disk_tidy.py"}, True)
    lp.changed_covered.tests_for = lambda base: ([], "没有测试映射表，全量跑")
    check("selector cannot decide: everything", lp.pick("x")[0], None)
    lp.changed_files = lambda base: [UNNAMED_DOC]
    lp.changed_covered.tests_for = lambda base: ([], lp.NO_BEHAVIOUR)
    check("a doc no test reads: no relay test", lp.pick("x")[0], [])
finally:
    lp.changed_covered.tests_for, lp.changed_files = real_tests_for, real_changed

lint = (ROOT / "scripts/mac/lint-repo.sh").read_text()
check("lint-repo.sh runs the picked list, all only on ALL or LINT_ALL_TESTS",
      "scripts/mac/lib/lint_pick_tests.py" in lint and '[ "$picked" = ALL ]' in lint and "LINT_ALL_TESTS" in lint, True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
