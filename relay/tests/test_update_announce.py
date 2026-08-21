"""Cover the "tell me the moment an update takes effect" path.

The tricky case is the first update after this feature ships: the process that
applies it is running the old code and cannot leave a marker, so the
announcement has to be derivable from the version file alone.
"""
import json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import selfupdate as su  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

def fresh():
    root = Path(tempfile.mkdtemp())
    (root / "state").mkdir()
    return root

print("[first update ever - old code applied it, left no marker]")
r = fresh()
(r / "state" / "code-version.txt").write_text("20260821200000")
n = su.pending_announcement(r)
check("announces", bool(n), True)
check("version", n and n["version"], 20260821200000)
check("no file list", n and n["files"], [])
check("second boot is silent", su.pending_announcement(r), None)

print("\n[normal update - marker carries the file list]")
r = fresh()
(r / "state" / "code-version.txt").write_text("20260822090000")
(r / "state" / "announced-version.txt").write_text("20260821200000")
su._record_announcement(r, {"version": 20260822090000, "previous": 20260821200000,
                            "files": ["ark_relay/engine.py"], "at": "2026-08-22T09:00:00+08:00"})
n = su.pending_announcement(r)
check("file list survives", n and n["files"], ["ark_relay/engine.py"])
check("previous version", n and n["previous"], 20260821200000)
check("not repeated", su.pending_announcement(r), None)

print("\n[no update - must stay silent]")
r = fresh()
(r / "state" / "code-version.txt").write_text("20260822090000")
(r / "state" / "announced-version.txt").write_text("20260822090000")
check("silent", su.pending_announcement(r), None)

print("\n[corrupt marker must not crash or block]")
r = fresh()
(r / "state" / "code-version.txt").write_text("20260822090000")
(r / "state" / "announced-version.txt").write_text("20260821200000")
(r / "state" / "update-announce.json").write_text("{not json")
n = su.pending_announcement(r)
check("falls back to version comparison", bool(n), True)
check("corrupt marker removed", (r / "state" / "update-announce.json").exists(), False)

print("\n[no version file at all - fresh install, nothing to say]")
r = fresh()
check("silent", su.pending_announcement(r), None)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
