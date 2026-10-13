"""append_ledger hands the run's start time to the scoreboard when it takes one.

Follow-up to d1bc5721 (2026-10-13): scoreboard.record takes an optional start
time and otherwise judges a test run by now; append_ledger did not pass it, so a
run booked after its test window closed was scored. append_ledger now passes
started=rec.started when scoreboard.record accepts it, and still calls the
older signature without it.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import ledger  # noqa: E402
from ark_relay.core.config import RunRecord, SERVER_TZ  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def rec(hms: str) -> RunRecord:
    t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
    return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                     started=t, finished=t + timedelta(minutes=20), ok=True)


real = ledger.scoreboard.record
calls = []
try:
    print("[scoreboard.record takes started]")

    def new_record(store, code_version, ok, transitional=False, started=None):
        calls.append(started)
    ledger.scoreboard.record = new_record
    st = ledger.State(tmpdir())
    st.store.set("versions", "code", "v1")
    r = rec("05-00-00")
    st.append_ledger(r)
    check("passed the run's start time", calls, [r.started])

    print("[older scoreboard.record without started]")
    calls.clear()

    def old_record(store, code_version, ok, transitional=False):
        calls.append("called")
    ledger.scoreboard.record = old_record
    st.append_ledger(rec("06-00-00"))
    check("still called, no TypeError", calls, ["called"])
finally:
    ledger.scoreboard.record = real

if fails:
    print(f"\n{len(fails)} FAIL: {fails}")
    sys.exit(1)
print("\nall ok")
