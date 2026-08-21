"""A held failure survives a relay restart through pending.json. Everything the
alert wording depends on has to survive with it - the relay now restarts itself
for every selfupdate, so this path runs far more often than it used to.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.config import RunRecord, SERVER_TZ            # noqa: E402
from ark_relay.transport import record_to_payload, payload_to_record  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

T0 = datetime(2026, 8, 21, 21, 30, tzinfo=SERVER_TZ)
T1 = datetime(2026, 8, 21, 22, 15, tzinfo=SERVER_TZ)

def rec(**kw):
    base = dict(run_id="2026-08-21/arknights/21-30-00", script="MAA",
                user="arknights", started=T0, finished=T1, ok=False,
                failed_tasks=["协议空间"], raw={"sanity": 6})
    base.update(kw)
    return RunRecord(**base)

print("[an untrustworthy duration must stay untrustworthy]")
# The filename is on a UTC+4 clock, so a run with no timestamped log has times
# that are hours off. duration_known=False is what stops the alert presenting
# that as fact - and it used to be dropped on the way to disk.
back = payload_to_record(record_to_payload(rec(duration_known=False)))
check("duration_known", back.duration_known, False)

print("\n[a trustworthy one stays trustworthy]")
check("duration_known", payload_to_record(record_to_payload(rec())).duration_known, True)

print("\n[payloads written before this field existed]")
check("defaults to True", payload_to_record({
    "run_id": "z", "script": "MAA", "started": T0.isoformat(),
    "finished": T1.isoformat(), "ok": False}).duration_known, True)

print("\n[everything else the alert needs]")
back = payload_to_record(record_to_payload(rec()))
for field in ("run_id", "script", "user", "started", "finished", "ok",
              "failed_tasks", "raw"):
    check(field, getattr(back, field), getattr(rec(), field))
check("duration_min", back.duration_min, 45)
check("sanity", back.sanity, 6)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
