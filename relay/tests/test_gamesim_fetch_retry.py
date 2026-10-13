"""gamesim ci_prepare: a failed fetch of the pinned OK-WW commit is retried, a commit that
never comes still fails.

Run 38434766518 (2026-10-14) lost lane u7-green-034a555d to one `git fetch --depth 1` of the
pinned v3.7.3 commit; the same fetch from the Mac worked at once. The lane now tries
FETCH_TRIES times before it gives up.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ci_prepare", HERE / "gamesim" / "okww" / "ci_prepare.py")
cp = importlib.util.module_from_spec(spec)
sys.modules["ci_prepare"] = cp
spec.loader.exec_module(cp)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def runner(fail_first):
    calls = []

    def run(*cmd):
        calls.append(cmd)
        if len(calls) <= fail_first:
            raise subprocess.CalledProcessError(128, list(cmd), stderr="fatal: unable to access")
        return ""
    return run, calls


waits = []
run, calls = runner(2)
cp.fetch_pinned(Path("w"), "https://example.invalid/r", "abc", run=run, sleep=waits.append)
check("two failures then a fetch: three tries", len(calls), 3)
check("waits between tries", waits, [10, 30])
check("it fetches the pinned commit, depth 1", calls[-1][-4:], ("--depth", "1", "https://example.invalid/r", "abc"))

waits.clear()
run, calls = runner(99)
try:
    cp.fetch_pinned(Path("w"), "https://example.invalid/r", "abc", run=run, sleep=waits.append)
    raised = None
except subprocess.CalledProcessError as exc:
    raised = exc.returncode
check("never comes: the last failure is raised", raised, 128)
check("after FETCH_TRIES tries", len(calls), cp.FETCH_TRIES)

run, calls = runner(0)
cp.fetch_pinned(Path("w"), "r", "c", run=run, sleep=waits.append)
check("a good fetch is one try", len(calls), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
