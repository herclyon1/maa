#!/usr/bin/env python3
"""「🔌 晚班 没有运行」 follows AUTO-MAS v5.7's weekday rules.

AUTO-MAS fires a time only on its TimeSet's Info.Days (app/core/timer.py
_due_timed_slots) and skips an item whose Schedule.Days leave out the day
(app/core/task_manager.py _is_script_scheduled_today). 77d7ed98 taught the plan
(plan.runs_at), but _check_missed_runs still walked every time every day, so a
day off for the queue, or a day its only item (MAA in 晚班) was skipped, still
raised the missed-run alarm.

Config: tests/fixtures/automas-config-2026-10-11 (the machine's own, see SOURCE.txt).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

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

from ark_relay.core import texts                       # noqa: E402
from ark_relay.core.config import Config, SERVER_TZ    # noqa: E402
from ark_relay.core.engine import Engine               # noqa: E402
from ark_relay.core.ledger import State                # noqa: E402
from ark_relay.core.notify import Notifier             # noqa: E402

QC = AUTOMAS / "config" / "QueueConfig.json"
PRISTINE = QC.read_text(encoding="utf-8")
EVENING = "6f09a385-b0ae-4ff6-9890-50339bdaddeb"       # 晚班 21:30: MAA only
ALL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def at(day: int, hh: int, mm: int) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)   # 10-13 is a Tuesday


def edit(fn) -> None:
    doc = json.loads(PRISTINE)
    fn(doc)
    QC.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def evening_timeset(doc):
    ts = doc[EVENING]["SubConfigsInfo"]["TimeSet"]
    return ts[ts["instances"][0]["uid"]]["Info"]


def skip_evening_items(day):
    def fn(doc):
        items = doc[EVENING]["SubConfigsInfo"]["QueueItem"]
        for inst in items["instances"]:
            items[inst["uid"]].setdefault("Schedule", {})["Days"] = [d for d in ALL if d != day]
    return fn


sent: list[str] = []


class FakeNotifier(Notifier):
    def send(self, title, body, *, alert=False, daily=False):
        sent.append(title)
        return []


cfg = Config()
E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
E._boot_time = lambda now: at(13, 20, 0)     # awake well before 21:30
E._started_at = at(13, 20, 1)
E._scripts_running = lambda: False
NOT_RUN = texts.not_run("晚班")


def evening_alarms() -> list[str]:
    sent.clear()
    E._missed_alerted.clear()
    E._check_missed_runs(at(13, 22, 10))     # Tuesday, 40 min past 晚班, nothing recorded
    return [t for t in sent if NOT_RUN in t]


print("[normal Tuesday: 晚班 due and nothing ran]")
edit(lambda d: None)
got = evening_alarms()
require("「晚班 没有运行」 is pushed", len(got) == 1, repr(sent))

print("[晚班's time runs on Monday only; today is Tuesday]")
edit(lambda d: evening_timeset(d).update(Days=["Monday"]))
got = evening_alarms()
require("no missed-run alarm on a day the time does not fire", got == [], repr(sent))

print("[晚班's only item (MAA) skipped for Tuesday through Schedule.Days]")
edit(skip_evening_items("Tuesday"))
got = evening_alarms()
require("no missed-run alarm when every item sits today out", got == [], repr(sent))

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
