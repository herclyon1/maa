"""diag-pull.py must not exit 0 when a record could not be fetched.

Silent-failure audit row scripts/mac/diag-pull.py:54: a per-object GET that
failed was printed to stderr, then the summary said 「新取回 N 条」 and the tool
exited 0, so a session that checks only the exit code believed every record
was on disk. The bucket deletes records after 7 days, so a missed one is lost.
"""
import contextlib
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay" / "tests"))
from _tmp import tmpdir  # noqa: E402

spec = importlib.util.spec_from_file_location("diag_pull", ROOT / "scripts" / "mac" / "diag-pull.py")
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def run(get):
    d = tmpdir()
    dp.DEST = d / "ark-diag"
    dp.env = lambda _p: {"COS_SECRET_ID": "i", "COS_SECRET_KEY": "k", "COS_DIAG_BUCKET": "b-1"}
    dp.listing = lambda _cos: [("diag/a.json", 3, "2026-10-10T01:00:00"),
                               ("diag/b.json", 3, "2026-10-10T02:00:00")]
    dp.get = get
    old = sys.argv
    sys.argv = ["diag-pull.py"]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = dp.main()
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue(), d


print("[one of two records fails to fetch]")
rc, out, err, d = run(lambda _cos, key, params="": (500, b"boom") if key == "diag/b.json" else (200, b"{}"))
check("exit code is non-zero", rc, 1)
check("the good record is on disk", (d / "ark-diag" / "a.json").exists(), True)
check("the summary names the failure count", "失败 1 条" in out, True)
check("the per-record error is still on stderr", "取回失败 500" in err, True)

print("[every record fetched]")
rc, out, err, d = run(lambda _cos, key, params="": (200, b"{}"))
check("exit code is 0", rc, 0)
check("no failure count in the summary", "失败" in out, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
