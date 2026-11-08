"""Missed runs; and missed weekdays.

One part per former file, each run on its own (tests/_parts.py): test_missed_runs.py, test_missed_weekdays.py.
"""
from __future__ import annotations

# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():
    """A queue that was due and produced nothing must alarm - and must not alarm
when the machine simply was not awake for it.

The distinction used to be made with the relay's own start time, which every
selfupdate resets. An update that ran past the queue's time therefore made the
new process disqualify itself and swallow a real missed run.

    Formerly test_missed_runs.py.
    """
    import json, os, sys
    from datetime import datetime

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
    STATE = TMP / "state"; STATE.mkdir()
    HIST = TMP / "history"; HIST.mkdir()

    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {"Info": {"Name": "Evening-MAA", "TimeEnabled": True},
               "SubConfigsInfo": {
                   "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
                   "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA-v5.1.0-win-x64"},
               "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": "arknights"}}}}}}),
        encoding="utf-8")

    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.core.engine import Engine

    sent = []
    class FakeNotifier(Notifier):
        # 签名必须跟真的一样：漏跑告警是 alert=True 发的，桩少一个关键字
        # 就会在真实调用点炸 TypeError，而那正是告警路径。
        def send(self, title, body, *, alert=False, daily=False):
            sent.append((title, alert))
            return []

    cfg = Config()
    E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
    BOOT = [None]
    E._boot_time = lambda now: BOOT[0]

    def at(hh, mm):
        return datetime(2026, 8, 21, hh, mm, tzinfo=SERVER_TZ)


    def reset():
        sent.clear()
        E._missed_alerted.clear()
        E.state.store.pop("marks", "alerted:2026-08-21")   # the settled keys on disk too

    print("[the swallowed alarm] selfupdate restarted the relay past the queue time")
    reset()
    BOOT[0] = at(21, 20)        # the machine WAS awake for 21:30
    E._started_at = at(21, 33)  # but this process only started at 21:33
    E._check_missed_runs(at(22, 0))
    check("alarms", len(sent), 1)

    print("\n[machine really was off] must stay quiet")
    reset()
    BOOT[0] = at(22, 40)        # powered on well after the queue
    E._started_at = at(22, 42)
    E._check_missed_runs(at(23, 10))
    check("silent", len(sent), 0)

    print("\n[not late yet] grace is 25 minutes")
    reset()
    BOOT[0] = at(21, 20); E._started_at = at(21, 22)
    E._check_missed_runs(at(21, 50))
    check("silent at +20min", len(sent), 0)
    reset()
    E._check_missed_runs(at(21, 56))
    check("alarms at +26min", len(sent), 1)

    print("\n[it did run] must stay quiet")
    reset()
    (STATE / "ledger-2026-08-21.jsonl").write_text(json.dumps({
        "script": "MAA", "started": at(21, 31).isoformat(),
        "finished": at(22, 15).isoformat(), "ok": True, "run_id": "x"}), encoding="utf-8")
    BOOT[0] = at(21, 20); E._started_at = at(21, 22)
    E._check_missed_runs(at(22, 30))
    check("silent", len(sent), 0)
    (STATE / "ledger-2026-08-21.jsonl").unlink()

    print("\n[alarms once, not every tick]")
    reset()
    BOOT[0] = at(21, 20); E._started_at = at(21, 22)
    for _ in range(5):
        E._check_missed_runs(at(22, 0))
    check("exactly one", len(sent), 1)

    print("\n[uptime unknown] falls back to the relay's start time")
    reset()
    BOOT[0] = None
    E._started_at = at(21, 33)
    E._check_missed_runs(at(22, 0))
    check("silent, as before this change", len(sent), 0)

    print("\n[partial queue] MAA ran, MaaEnd never did, relay restarted past the time")
    # Same fix, second site: _check_partial_queues used the relay's start time too.
    reset()
    (STATE / "ledger-2026-08-21.jsonl").write_text(json.dumps({
        "script": "MAA", "started": at(21, 31).isoformat(),
        "finished": at(21, 55).isoformat(), "ok": True, "run_id": "x"}), encoding="utf-8")
    import ark_relay.core.plan as _plan
    _orig = _plan.recent_due_queues
    _plan.recent_due_queues = lambda d, n, window_minutes=120: [
        {"name": "Evening-MAA", "due": at(21, 30), "kinds": ["MAA", "MaaEnd"]}]
    BOOT[0] = at(21, 20)
    E._started_at = at(21, 40)          # restarted after the queue started
    E._check_partial_queues(at(23, 0), "2026-08-21",
                            E.state.read_ledger("2026-08-21"))
    check("alarms about the missing MaaEnd", len(sent), 1)

    reset()
    BOOT[0] = at(23, 0)                 # machine genuinely was not awake
    E._check_partial_queues(at(23, 30), "2026-08-21",
                            E.state.read_ledger("2026-08-21"))
    check("silent when the machine was off", len(sent), 0)
    _plan.recent_due_queues = _orig
    (STATE / "ledger-2026-08-21.jsonl").unlink()

    # 漏跑和缺项都是"人得去处理"的故障，必须走双通道。日常消息（日报、预更新）
    # 只发一处，这条断言防的是有人把 alert=True 顺手删掉。
    reset()
    BOOT[0] = at(21, 20)
    E._started_at = at(21, 20)
    _plan.recent_due_queues = lambda d, n, window_minutes=120: [
        {"name": "Evening-MAA", "due": at(21, 30), "kinds": ["MAA"]}]
    E._check_missed_runs(at(22, 0))
    _plan.recent_due_queues = _orig
    check("漏跑告警走双通道", [a for _, a in sent], [True])

    print("\n[调试模式开着也照报漏跑（2026-10-06：只要是报错都要发）]")
    from ark_relay.features.modes import modes as _modes
    reset()
    _modes.debug_active = lambda *a, **k: True
    try:
        E._check_missed_runs(at(22, 0))
    finally:
        import importlib as _il
        _il.reload(_modes)
    check("调试模式下漏跑也报群", len(sent), 1)

    print("\n[relay restarted after the alarm went out: no second push (09-17 21:55 / 23:00; audit s8 #1)]")
    reset()
    BOOT[0] = at(21, 20); E._started_at = at(21, 22)
    E._check_missed_runs(at(21, 56))
    check("first push", len(sent), 1)
    E_again = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
    E_again._boot_time = lambda now: at(21, 20)       # same boot: uptime did not reset
    E_again._started_at = at(22, 57)
    E_again._scripts_running = lambda: False
    E_again._check_missed_runs(at(23, 0))
    check("the restarted relay stays quiet", len(sent), 1)

    print("\n[same for a missing script in a queue that ran]")
    reset()
    (STATE / "ledger-2026-08-21.jsonl").write_text(json.dumps({
        "script": "MAA", "started": at(21, 31).isoformat(),
        "finished": at(21, 55).isoformat(), "ok": True, "run_id": "x"}), encoding="utf-8")
    _plan.recent_due_queues = lambda d, n, window_minutes=120: [
        {"name": "Evening-MAA", "due": at(21, 30), "kinds": ["MAA", "MaaEnd"]}]
    for eng_ in (E, E_again):
        eng_._script_running = lambda kind: False
        eng_._check_partial_queues(at(23, 0), "2026-08-21", eng_.state.read_ledger("2026-08-21"))
    _plan.recent_due_queues = _orig
    (STATE / "ledger-2026-08-21.jsonl").unlink()
    check("one push across the restart", len(sent), 1)

    print("\n[audit 11-08 C-06: a run a person started at AUTO-MAS is not the queue's run]")
    reset()
    BOOT[0] = at(21, 20)
    E._started_at = at(21, 0)
    _real_recent = E._recent_entries
    E._recent_entries = lambda now: [{"run_id": "2026-08-21/wuwa/OK-WW-17-40-00", "script": "OK-WW",
                                      "started": at(21, 40).isoformat(), "ok": True, "raw": {"hand_started": "手动"}}]
    E._check_missed_runs(at(22, 0))
    check("hand-started run only: still the missed-run alarm", len(sent), 1)
    reset()
    E._recent_entries = lambda now: [{"run_id": "2026-08-21/arknights/MAA-17-31-00", "script": "MAA",
                                      "started": at(21, 31).isoformat(), "ok": True, "raw": {"manual_stop": "停一切"}}]
    E._check_missed_runs(at(22, 0))
    check("a run 停一切 stopped did start: no missed-run alarm", len(sent), 0)
    E._recent_entries = _real_recent


def _part_missed_weekdays():
    """「🔌 晚班 没有运行」 follows AUTO-MAS v5.7's weekday rules.

AUTO-MAS fires a time only on its TimeSet's Info.Days (app/core/timer.py
_due_timed_slots) and skips an item whose Schedule.Days leave out the day
(app/core/task_manager.py _is_script_scheduled_today). 77d7ed98 taught the plan
(plan.runs_at), but _check_missed_runs still walked every time every day, so a
day off for the queue, or a day its only item (MAA in 晚班) was skipped, still
raised the missed-run alarm.

Config: tests/fixtures/automas-config-2026-10-11 (the machine's own, see SOURCE.txt).

    Formerly test_missed_weekdays.py.
    """
    #!/usr/bin/env python3

    import json
    import os
    import shutil
    from datetime import datetime


    FX = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"
    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    shutil.copytree(FX / "config", AUTOMAS / "config")
    STATE = TMP / "state"; STATE.mkdir()
    HIST = TMP / "history"; HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import texts
    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.engine import Engine
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier

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


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_missed_weekdays]))
