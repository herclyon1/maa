"""boot_stages._seconds_to_next_queue skips a queue time that runs nothing today (audit s23 F4, 10-13).

232948ba moved five readers of queue times to plan.runs_at (a time fires only on its
weekdays, and only when some item does not sit the day out) and missed this one. Run
by the audit on a schedule of 09:00 Saturday-only plus 21:30 daily, at Tuesday 08:40:
the budget aimed at the 09:00 queue that does not fire (1110 s) instead of 21:30. The
budget decides whether a pre-update item gets its second try (_once_more).
The real QueueConfig has both times on all seven days, so this did not bite yet.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boot_stages  # noqa: E402
from ark_relay.core import plan  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def at(day, hh, mm):
    return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)     # 10-13 is a Tuesday


ALL = list(plan._WEEKDAYS)
SCHEDULES = {
    # 早班 09:00 fires on Saturdays only; 晚班 21:30 every day.
    "saturday_morning": [
        {"name": "早班", "times": ["09:00"], "items": ["maa"], "days": {"09:00": ["Saturday"]}},
        {"name": "晚班", "times": ["21:30"], "items": ["maa2"]},
    ],
    # 早班 fires every day, but its only item sits Tuesdays out.
    "item_off_tuesday": [
        {"name": "早班", "times": ["09:00"], "items": ["maaend"],
         "entries": [("maaend", [d for d in ALL if d != "Tuesday"])]},
        {"name": "晚班", "times": ["21:30"], "items": ["maa2"]},
    ],
}

real_schedule = plan.schedule
try:
    to_evening = (at(13, 21, 30) - at(13, 8, 40)).total_seconds() - 90

    print("[09:00 fires on Saturdays only; Tuesday 08:40]")
    plan.schedule = lambda automas_dir: SCHEDULES["saturday_morning"]
    check("aims at 21:30, not the 09:00 that does not fire",
          boot_stages._seconds_to_next_queue(None, at(13, 8, 40)), to_evening)
    check("on a Saturday 08:40 the 09:00 queue counts",
          boot_stages._seconds_to_next_queue(None, at(17, 8, 40)), 20 * 60 - 90.0)

    print("[09:00's only item sits Tuesdays out]")
    plan.schedule = lambda automas_dir: SCHEDULES["item_off_tuesday"]
    check("aims at 21:30", boot_stages._seconds_to_next_queue(None, at(13, 8, 40)), to_evening)
    check("Wednesday 08:40: the 09:00 queue counts",
          boot_stages._seconds_to_next_queue(None, at(14, 8, 40)), 20 * 60 - 90.0)

    print("[unchanged: the floor, and nothing left today]")
    plan.schedule = lambda automas_dir: SCHEDULES["saturday_morning"]
    check("21:29 -> the floor", boot_stages._seconds_to_next_queue(None, at(13, 21, 29)), 120.0)
    check("after the last queue -> the no-queue-left figure",
          boot_stages._seconds_to_next_queue(None, at(13, 22, 0)), 3600.0)
finally:
    plan.schedule = real_schedule

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
