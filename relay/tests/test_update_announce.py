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

print("\n[failure is announced too - a silent one leaves old code running]")
r = fresh()
su._record_failure(r, "缓存未刷新", 20260821113000, 20260821111012,
                   ["ark_relay/engine.py", "ark_relay/core.py"])
f = su.take_failure(r)
check("reported", bool(f), True)
check("reason", f and f["reason"], "缓存未刷新")
check("file list", f and f["files"], ["ark_relay/engine.py", "ark_relay/core.py"])
check("count", f and f["count"], 2)
check("not repeated", su.take_failure(r), None)

print("\n[a later success clears the stale complaint]")
r = fresh()
su._record_failure(r, "x", 1, 2, ["a.py"])
su._clear_failure(r)
check("cleared", su.take_failure(r), None)

print("\n[corrupt failure marker is removed, not retried forever]")
r = fresh()
(r / "state" / "update-failed.json").write_text("{broken")
check("returns nothing", su.take_failure(r), None)
check("file removed", (r / "state" / "update-failed.json").exists(), False)

print("\n[failure and success markers are independent]")
r = fresh()
(r / "state" / "code-version.txt").write_text("20260822090000")
su._record_failure(r, "x", 1, 2, ["a.py"])
check("failure present", bool(su.take_failure(r)), True)
check("announcement still works", bool(su.pending_announcement(r)), True)

print("\n[raw gets a timeout above its measured median]")
check("RAW_TIMEOUT > 38s median", su.RAW_TIMEOUT > 38, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
