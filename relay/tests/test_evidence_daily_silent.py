"""evidence_daily.py must exit non-zero when a day log could not be fetched.

Silent-failure audit row scripts/mac/lib/evidence_daily.py:90: a failed COS
fetch printed 「✗ … 取不到」 and main still returned 0, so a session that checks
the exit code saw success even with both logs missing.
"""
import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay" / "tests"))
sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
import evidence_daily as ed  # noqa: E402
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def run(missing):
    def cos_get(e, u, dest):
        if any(u["key"].startswith(f"daily/{m}-") for m in missing):
            raise RuntimeError("HTTP 404 NoSuchKey")
        (dest / u["name"]).write_text("10-10 01:00:00 INFO x\n", encoding="utf-8")

    ed.DEST_ROOT = tmpdir() / "daily"
    ed.evidence_pull.env = lambda _p: {"COS_SECRET_ID": "i", "COS_SECRET_KEY": "k",
                                       "COS_BUCKET": "b-1", "COS_REGION": "ap-shanghai"}
    ed.evidence_pull.cos_get = cos_get
    old = sys.argv
    sys.argv = ["evidence_daily.py", "2026-10-10"]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = ed.main()
    finally:
        sys.argv = old
    return rc, out.getvalue()


print("[both logs fetched]")
rc, out = run(missing=[])
check("exit 0 when both are there", rc, 0)

print("[the AUTO-MAS log is missing]")
rc, out = run(missing=["automas-app"])
check("the miss is printed", "automas-app-2026-10-10.log：取不到" in out, True)
check("the relay log is still sliced", "relay-2026-10-10.log：窗口里 1 行" in out, True)
check("exit non-zero when one is missing", rc, 1)

print("[both missing]")
check("exit non-zero when both are missing", run(missing=["relay", "automas-app"])[0], 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
