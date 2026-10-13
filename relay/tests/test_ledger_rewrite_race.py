"""An append landing during a ledger rewrite must not be lost.

Audit s4 A6 (2026-10-13): State._rewrite_entry (mark_incomplete / mark_raw /
mark_evidence) reads the day's ledger, edits one line and replaces the whole file.
append_ledger runs on another thread (the engine's next record) with no lock; an
append between the read and the replace vanished from the day, so the daily report
and the boot-check missed that run.

Made deterministic: the rewrite is held just before its replace while the append runs.
"""
import sys
import threading
import time
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


def rec(hms: str) -> RunRecord:
    t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
    return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                     started=t, finished=t + timedelta(minutes=20), ok=True)


print("[an append runs while mark_incomplete is between its read and its replace]")
st = ledger.State(tmpdir())
st.append_ledger(rec("05-00-00"))
real_write = ledger.atomic_write_text
other: list = []


def slow_write(path, text, *a, **k):
    if not other:
        t = threading.Thread(target=lambda: st.append_ledger(rec("06-00-00")))
        other.append(t)
        t.start()
        time.sleep(0.3)          # the append gets every chance to land now
    return real_write(path, text, *a, **k)


ledger.atomic_write_text = slow_write
try:
    hit = st.mark_incomplete("2026-10-13", "2026-10-13/arknights/05-00-00", "no evidence")
finally:
    ledger.atomic_write_text = real_write
other[0].join(5)
rows = {e["run_id"]: e for e in st.read_ledger("2026-10-13")}
check("the rewrite found its line", hit, True)
check("the rewritten line carries the mark",
      rows.get("2026-10-13/arknights/05-00-00", {}).get("incomplete"), "no evidence")
check("the appended run is still in the day", "2026-10-13/arknights/06-00-00" in rows, True)

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
sys.exit(1 if fails else 0)
