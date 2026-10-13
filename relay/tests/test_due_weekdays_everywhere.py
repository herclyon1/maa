#!/usr/bin/env python3
"""Every place that reads a queue's times asks plan.runs_at whether the time runs anything
that day (audit 10-13: raw queue times were read without the weekday rule in five places,
and the daily report's 「明日安排」 listed skipped items).

AUTO-MAS fires a time only on its TimeSet Days and skips an item whose Schedule.Days leave
out the day (the relay's own one-day skip writes exactly that); test_plan_queue_weekdays.py
covers plan itself. Here: the shift / hand-start split (shutdown._near_due), the loop's
missed-run wake-up (Engine.next_deadline), the overrun watch (runwatch.overrun_moments),
the pre-update's 「a queue still to come runs OK-WW」 (preupdate.wanted_today), the
maintenance skip (gameupdate._queues_today) and plan.next_plan.

Config: tests/fixtures/automas-config-2026-10-11 (the machine's own, see SOURCE.txt).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

FX = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"
TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
shutil.copytree(FX / "config", AUTOMAS / "config")
STATE = TMP / "state"; STATE.mkdir()
HIST = TMP / "history"; HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import plan                                # noqa: E402
from ark_relay.core.config import Config, SERVER_TZ            # noqa: E402
from ark_relay.core.engine import Engine                       # noqa: E402
from ark_relay.core.ledger import State                        # noqa: E402
from ark_relay.core.notify import Notifier                     # noqa: E402
from ark_relay.features.gameupdate import gameupdate           # noqa: E402
from ark_relay.features.preupdate import preupdate             # noqa: E402
from ark_relay.features.run import runwatch                    # noqa: E402
from ark_relay.features.shutdown import shutdown               # noqa: E402

QC = AUTOMAS / "config" / "QueueConfig.json"
PRISTINE = QC.read_text(encoding="utf-8")
MORNING = "cc32e55a-55d0-408d-980d-642e66d111ae"       # 早班 09:00: MAA, OK-WW, MaaEnd
EVENING = "6f09a385-b0ae-4ff6-9890-50339bdaddeb"       # 晚班 21:30: MAA
MAAEND_ITEM = "572b030a-6eb2-4122-954e-07b3010c8d88"
ALL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        fails.append(label)


def at(day: int, hh: int, mm: int) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)   # 10-12 is a Monday


def edit(fn) -> None:
    doc = json.loads(PRISTINE)
    fn(doc)
    QC.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def timeset(doc, queue):
    ts = doc[queue]["SubConfigsInfo"]["TimeSet"]
    return ts[ts["instances"][0]["uid"]]["Info"]


def without(day):
    return [d for d in ALL if d != day]


def morning_off_monday(d):
    timeset(d, MORNING).update(Days=without("Monday"))


def maaend_off_tuesday(d):
    d[MORNING]["SubConfigsInfo"]["QueueItem"][MAAEND_ITEM]["Schedule"].update(Days=without("Tuesday"))


def dues_today(now):
    return {q["name"]: [x.strftime("%H:%M") for x in q["dues"]] for q in gameupdate._queues_today(AUTOMAS, now)}


class QuietNotifier(Notifier):
    def send(self, title, body, *, alert=False, daily=False):
        return []


cfg = Config()
E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=QuietNotifier(cfg))

print("[shutdown: a start next to a time that does not fire that day is a hand start]")
edit(lambda d: timeset(d, EVENING).update(Days=["Monday"]))
times = shutdown._schedule_times(E)
check("Monday 21:35 is next to Monday's 晚班", shutdown._near_due(at(12, 21, 35), times), True)
check("Tuesday 21:35 is not (晚班 runs on Mondays only)", shutdown._near_due(at(13, 21, 35), times), False)

print("[engine: no missed-run wake-up for a time that runs nothing that day]")
edit(lambda d: None)
first = E.next_deadline(at(12, 8, 59))
check("control: Monday 08:59 wakes for 早班 09:00", "早班" in (first or (None, ""))[1], True)
edit(morning_off_monday)
first = E.next_deadline(at(12, 8, 59))
check("早班 off on Monday: that wake-up is gone", "早班" in (first or (None, ""))[1], False)

print("[runwatch: no overrun watch over a time that ran nothing]")
with mock.patch.object(runwatch, "planned_minutes", lambda *a: (60, 0)):
    edit(lambda d: None)
    got = [(q["name"], hhmm) for q, hhmm, *_ in runwatch.overrun_moments(E, at(12, 12, 0))]
    check("control: Monday noon watches 早班 09:00", ("早班", "09:00") in got, True)
    edit(morning_off_monday)
    got = [(q["name"], hhmm) for q, hhmm, *_ in runwatch.overrun_moments(E, at(12, 12, 0))]
    check("早班 off on Monday: not watched", ("早班", "09:00") in got, False)
    check("晚班 (Sunday 21:30) still watched", ("晚班", "21:30") in got, True)

print("[preupdate: only a time that runs OK-WW that day wants the pre-update]")
edit(lambda d: None)
check("control: Monday 08:00, 早班 runs OK-WW", preupdate.wanted_today(AUTOMAS, at(12, 8, 0)), True)
edit(morning_off_monday)
check("早班 off on Monday: no pre-update wanted", preupdate.wanted_today(AUTOMAS, at(12, 8, 0)), False)

print("[gameupdate: the maintenance skip only sees today's dues that run something]")
edit(lambda d: None)
check("control: Monday 08:00 sees 早班 09:00", dues_today(at(12, 8, 0)).get("早班"), ["09:00"])
edit(morning_off_monday)
check("早班 off on Monday: no 早班 due", dues_today(at(12, 8, 0)).get("早班"), [])
check("晚班 21:30 still there", dues_today(at(12, 8, 0)).get("晚班"), ["21:30"])

print("[明日安排: tomorrow's skipped item and off time are not listed]")
with mock.patch.object(plan, "_tomorrow", lambda: at(13, 12, 0)):     # a Tuesday
    edit(lambda d: None)
    text = plan.next_plan(AUTOMAS)
    check("control: 终末地 listed under 早班", "▸ 终末地" in text, True)
    edit(maaend_off_tuesday)
    text = plan.next_plan(AUTOMAS)
    check("MaaEnd skipped on Tuesday: not listed", "▸ 终末地" in text, False)
    check("the rest of 早班 still listed", ("🕘 09:00" in text, "▸ 鸣潮" in text), (True, True))
    edit(lambda d: timeset(d, MORNING).update(Days=without("Tuesday")))
    text = plan.next_plan(AUTOMAS)
    check("早班 off on Tuesday: its time is not listed", "🕘 09:00" in text, False)
    check("晚班 still listed", "🕘 21:30" in text, True)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
