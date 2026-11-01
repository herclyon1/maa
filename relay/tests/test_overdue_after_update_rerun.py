"""「⏰ 一直没出结果」 after a client update: the scripts the relay re-ran itself are timed from the re-run.

2026-11-01: 明日方舟 updated, MAA was skipped in the 09:00 早班 and re-run at 12:02 (relay.log
12:02:15 「补跑 MAA → 脚本「MAA」已单独开跑」); at 12:04:27 the overdue alarm counted 142 + 30
minutes from 09:00. Checks shutdown._overdue_from, the clock start _shift_overdue uses.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.shutdown import shutdown

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Eng:
    pass


due = datetime(2026, 11, 1, 9, 0, tzinfo=SERVER_TZ)
rerun = datetime(2026, 11, 1, 12, 2, 15, tzinfo=SERVER_TZ)

e = Eng()
check("no re-run: the queue's time", shutdown._overdue_from(e, due, ["MAA"]), due)
e._gu_rerun_at, e._gu_reran = rerun, {"MAA"}
check("MAA re-run after the update: from 12:02", shutdown._overdue_from(e, due, ["MAA"]), rerun)
check("another script also missing: still from the queue's time", shutdown._overdue_from(e, due, ["MAA", "OK-WW"]), due)
e._gu_reran = {"OK-WW"}
check("a different script was re-run: from the queue's time", shutdown._overdue_from(e, due, ["MAA"]), due)
e._gu_reran, e._gu_rerun_at = {"MAA"}, datetime(2026, 10, 31, 22, 0, tzinfo=SERVER_TZ)
check("yesterday's re-run does not move today's shift", shutdown._overdue_from(e, due, ["MAA"]), due)

print("all checks passed" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
