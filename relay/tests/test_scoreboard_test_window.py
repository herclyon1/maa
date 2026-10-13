#!/usr/bin/env python3
"""A run inside a test window does not count on the scoreboard (like the report rows).

10-13: the 11:07 test OK-WW run (test window 11:05:49 open) was counted as
「20261013030327: runs 1」 in state.json. split_test already keeps such runs out
of the daily report; the scoreboard now does the same.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core.config import SERVER_TZ
from ark_relay.core.ledger import State
from ark_relay.features.report import scoreboard
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + label + ("" if ok else f"  got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


V = "20261013030327"
d = tmpdir()
st = State(Path(d))
(Path(d) / "test-windows.json").write_text(json.dumps(
    [{"since": "2026-10-13T11:05:49+08:00", "until": "2026-10-13T11:57:41+08:00"}]), encoding="utf-8")
scoreboard.record(st.store, V, True, started=datetime(2026, 10, 13, 11, 5, 49, tzinfo=SERVER_TZ))
check("test run not counted", (st.store.get("versions", "scoreboard") or {}).get(V), None)
scoreboard.record(st.store, V, True, started=datetime(2026, 10, 13, 9, 0, 36, tzinfo=SERVER_TZ))
check("real run counted", ((st.store.get("versions", "scoreboard") or {}).get(V) or {}).get("runs"), 1)
# Booked with no start time while a window is still open (no until): a test.
(Path(d) / "test-windows.json").write_text(json.dumps(
    [{"since": datetime.now(tz=SERVER_TZ).replace(microsecond=0).isoformat()}]), encoding="utf-8")
scoreboard.record(st.store, V, False)
check("open window, no start: not counted", st.store.get("versions", "scoreboard")[V].get("failed"), None)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
