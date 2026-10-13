"""errwatch's per-day counts survive the switch to the next day.

Audit 2026-10-13 s7 #7: the count cache holds one day, and _count saves a
repeat only every SAVE_EVERY seconds; the first record after midnight replaced
the cache and the previous day's unsaved repeat was lost, so the daily report's
「中继自己记下的报错」 undercounted.
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.alarm import errwatch

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def send(self, title, body="", **kw):
        return []


def record(at: datetime, msg: str) -> logging.LogRecord:
    r = logging.LogRecord("ark.report", logging.WARNING, __file__, 1, msg, None, None)
    r.created = at.timestamp()
    return r


state = tmpdir()
h = errwatch.ErrorKindAlert(Notes(), state_dir=state, known={}, clock=lambda: 1000.0, pace=0, retry=(0,))
try:
    h.handle(record(datetime(2026, 10, 12, 23, 59, 40, tzinfo=SERVER_TZ), "日报没发出去"))
    h.handle(record(datetime(2026, 10, 12, 23, 59, 50, tzinfo=SERVER_TZ), "日报没发出去"))   # unsaved repeat
    h.handle(record(datetime(2026, 10, 13, 0, 0, 5, tzinfo=SERVER_TZ), "补跑没派出去"))     # next day
finally:
    h.close()
day = json.loads((state / errwatch.DAY_DIR / "2026-10-12.json").read_text(encoding="utf-8"))
check("10-12 keeps both records", [r.get("count") for r in day.values()], [2])

print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
