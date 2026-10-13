#!/usr/bin/env python3
"""The relay's view of which scripts a queue runs follows AUTO-MAS v5.7's own rules.

AUTO-MAS (v5.7.0-beta.2) skips a queue item whose Schedule.Days leave out the
day (app/core/task_manager.py _is_script_scheduled_today), fires a time only on
its TimeSet's Info.Days and never times a cycle queue (app/core/timer.py
_due_timed_slots), and an item with ScriptId "-" is not a script
(_queue_script_entries). The relay's one-day skip writes exactly Schedule.Days,
so before this a skipped MaaEnd still raised 「MaaEnd 没有运行（早班）」 and held
off the power-off for two hours.

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

from ark_relay.core import plan                        # noqa: E402
from ark_relay.core.config import Config, SERVER_TZ    # noqa: E402
from ark_relay.core.engine import Engine               # noqa: E402
from ark_relay.core.ledger import State                # noqa: E402
from ark_relay.core.notify import Notifier             # noqa: E402
from ark_relay.features.shutdown import shutdown       # noqa: E402

QC = AUTOMAS / "config" / "QueueConfig.json"
PRISTINE = QC.read_text(encoding="utf-8")
MORNING = "cc32e55a-55d0-408d-980d-642e66d111ae"       # 早班 09:00: MAA, OK-WW, MaaEnd
EVENING = "6f09a385-b0ae-4ff6-9890-50339bdaddeb"       # 晚班 21:30: MAA
MAAEND_ITEM = "572b030a-6eb2-4122-954e-07b3010c8d88"
ALL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def at(day: int, hh: int, mm: int) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)   # 10-12 is a Monday


def edit(fn) -> None:
    doc = json.loads(PRISTINE)
    fn(doc)
    QC.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def timeset(doc, queue):
    ts = doc[queue]["SubConfigsInfo"]["TimeSet"]
    return ts[ts["instances"][0]["uid"]]["Info"]


def due(now, window=120):
    return {q["name"]: q["kinds"] for q in plan.recent_due_queues(AUTOMAS, now, window_minutes=window)}


def without(day):
    return [d for d in ALL if d != day]


print("[the machine's own config, nothing skipped]")
edit(lambda d: None)
require("早班 at 09:30 waits for MAA, OK-WW and MaaEnd",
        due(at(12, 9, 30)) == {"早班": ["MAA", "OK-WW", "MaaEnd"]}, repr(due(at(12, 9, 30))))

print("[MaaEnd skipped today through Schedule.Days, as the relay's skip writes it]")
edit(lambda d: d[MORNING]["SubConfigsInfo"]["QueueItem"][MAAEND_ITEM]["Schedule"].update(Days=without("Monday")))
require("早班 no longer waits for MaaEnd on Monday",
        due(at(12, 9, 30)) == {"早班": ["MAA", "OK-WW"]}, repr(due(at(12, 9, 30))))
require("on Tuesday it waits for MaaEnd again",
        due(at(13, 9, 30)) == {"早班": ["MAA", "OK-WW", "MaaEnd"]}, repr(due(at(13, 9, 30))))

sent: list = []


class FakeNotifier(Notifier):
    def send(self, title, body, *, alert=False, daily=False):
        sent.append(title)
        return []


cfg = Config()
E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
E._boot_time = lambda now: at(12, 8, 45)
E._started_at = at(12, 8, 46)
(STATE / "ledger-2026-10-12.jsonl").write_text("\n".join(json.dumps(
    {"script": s, "started": at(12, h, m).isoformat(), "finished": at(12, h, m + 20).isoformat(),
     "ok": True, "run_id": s}) for s, h, m in (("MAA", 9, 1), ("OK-WW", 9, 25))) + "\n", encoding="utf-8")
entries = E.state.read_ledger("2026-10-12")
E._check_partial_queues(at(12, 11, 0), "2026-10-12", entries)
require("no 「MaaEnd 没有运行（早班）」 for the skipped MaaEnd", sent == [], repr(sent))
require("the skipped MaaEnd does not hold off the power-off",
        shutdown._unfinished_queues(E, at(12, 10, 0), entries) == [],
        repr(shutdown._unfinished_queues(E, at(12, 10, 0), entries)))

print("[a time whose weekdays leave out today]")
edit(lambda d: timeset(d, MORNING).update(Days=without("Monday")))
require("早班 is not due on Monday", "早班" not in due(at(12, 9, 30)), repr(due(at(12, 9, 30))))
require("早班 is due on Tuesday", "早班" in due(at(13, 9, 30)), repr(due(at(13, 9, 30))))

print("[yesterday's 21:30 still counts after midnight, by yesterday's weekday]")
edit(lambda d: timeset(d, EVENING).update(Days=["Monday"]))
require("Monday's 晚班 is still due at Tuesday 00:10", due(at(13, 0, 10), 180) == {"晚班": ["MAA"]},
        repr(due(at(13, 0, 10), 180)))
require("Sunday's 晚班 (not a run day) is not due at Monday 00:10", due(at(12, 0, 10), 180) == {},
        repr(due(at(12, 0, 10), 180)))

print("[a cycle queue ignores its timed settings]")
edit(lambda d: d[MORNING]["Info"].update(CycleEnabled=True))
require("早班 as a cycle queue is not timed", [q["name"] for q in plan.schedule(AUTOMAS)] == ["晚班"],
        repr([q["name"] for q in plan.schedule(AUTOMAS)]))


def add_empty_item(d):
    items = d[MORNING]["SubConfigsInfo"]["QueueItem"]
    items["instances"].append({"uid": "empty", "type": "QueueItem"})
    items["empty"] = {"Info": {"ScriptId": "-"}, "Schedule": {"Days": ALL}}


print("[an item with no script picked]")
edit(add_empty_item)
morning = next(q for q in plan.schedule(AUTOMAS) if q["name"] == "早班")
require("ScriptId \"-\" is not a script", "-" not in morning["items"], repr(morning["items"]))

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
