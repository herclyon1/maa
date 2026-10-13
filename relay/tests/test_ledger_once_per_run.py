"""One run is one ledger line, however many times its record is handled.

Follow-up to 359fea45 (2026-10-13): a record whose handling raises after its
ledger line is written is handled again on every retry tick, and once more
after a deploy if it was given up. handle._append_ledger_once skips the append
when read_ledger already has the run, but that check sits outside the ledger
lock and any other caller of State.append_ledger had no guard at all, so the
same run could be booked twice. State.append_ledger now keeps the existing
line for a (day, run_id) already in the ledger.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import ledger
from ark_relay.core.config import RunRecord, SERVER_TZ

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def rec(hms: str, ok: bool = True) -> RunRecord:
    t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
    return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                     started=t, finished=t + timedelta(minutes=20), ok=ok)


def lines(st, day="2026-10-13"):
    p = st.ledger_path(day)
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


print("[handling raises after the ledger write; the record is retried 3 times]")
st = ledger.State(tmpdir())
st.store.set("versions", "code", "v1")
r = rec("05-00-00")
for _ in range(3):
    try:
        st.append_ledger(r)
        raise RuntimeError("judging failed after the ledger write")
    except RuntimeError:
        pass
got = lines(st)
check("exactly one ledger line for the run", [e["run_id"] for e in got], [r.run_id])

print("[a mark written after the first append survives the retry]")
st.mark_incomplete("2026-10-13", r.run_id, "no evidence")
st.append_ledger(r)
got = lines(st)
check("still one line, mark kept", ([e["run_id"] for e in got], got[0].get("incomplete")),
      ([r.run_id], "no evidence"))

print("[the scoreboard counts the run once]")
board = st.store.get("versions", "scoreboard") or {}
check("one run scored for v1", (board.get("v1") or {}).get("runs"), 1)

print("[another run on the same day is still appended]")
st.append_ledger(rec("06-00-00"))
check("two runs, two lines", len(lines(st)), 2)

if fails:
    print(f"\n{len(fails)} FAIL: {fails}")
    sys.exit(1)
print("\nall checks passed")
