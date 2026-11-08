"""The plan text: after-accomplish, collect days from the master, queue weekdays, silence, stage modes and start-up mode.

One part per former file, each run on its own (tests/_parts.py): test_plan_after_accomplish.py, test_plan_collect_days_master.py, test_plan_queue_weekdays.py, test_plan_silent.py, test_plan_stage_modes.py, test_plan_startup_mode.py.
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


def _part_plan_after_accomplish():
    """「明日安排」 names every AUTO-MAS after-run action, not only "Shutdown".

AUTO-MAS v5.7 QueueConfig Info.AfterAccomplish takes NoAction, Shutdown,
ShutdownForce, Reboot, Hibernate, Sleep, KillSelf, Logoff (models/config.py).
The plan only recognised "Shutdown", so a queue set to force shut down or
hibernate showed no line at all. Base data: the real 10-11 config (NoAction).

    Formerly test_plan_after_accomplish.py.
    """
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    FAILED: list[str] = []
    REAL = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def power_lines(after: "str | None") -> list[str]:
        root = tmpdir()
        shutil.copytree(REAL, root / "a")
        qf = root / "a" / "config" / "QueueConfig.json"
        d = json.loads(qf.read_text(encoding="utf-8"))
        if after is not None:
            for inst in d["instances"]:
                d[inst["uid"]]["Info"]["AfterAccomplish"] = after
        qf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return [ln for ln in plan.next_plan(root / "a").splitlines() if ln.startswith("⏻")]


    require("real config (NoAction): no power line", power_lines(None) == [], repr(power_lines(None)))
    require("Shutdown still says 关机", power_lines("Shutdown") == ["⏻ 跑完自动关机"] * 2, repr(power_lines("Shutdown")))
    for value, zh in (("ShutdownForce", "强制关机"), ("Hibernate", "休眠"), ("Reboot", "重启"),
                      ("Sleep", "睡眠"), ("KillSelf", "退出 AUTO-MAS"), ("Logoff", "注销")):
        got = power_lines(value)
        require(f"{value} -> {zh}", got == [f"⏻ 跑完自动{zh}"] * 2, repr(got))

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


def _part_plan_collect_days_master():
    """The plan's gathering-day line reads the master copy, not MaaEnd's own file.

Phone edits go to the master copy only (mastercfg.write_maaend); AUTO-MAS copies
it over MaaEnd's config/mxu-MaaEnd.json before each run. Reading MaaEnd's file
showed a phone change in 「明日安排」 only after the next run. With no
AutoCollectSchedule saved, MaaEnd runs on the option's default_case (all seven
days in tasks/AutoCollect.json), so the plan must not drop the line.
Days below are the real master copy's (10-11: Monday, Thursday).
Checked through next_plan (the 「明日安排」 text), with the machine's own AUTO-MAS
config (tests/fixtures/automas-config-2026-10-11) pointing MaaEnd at a temp dir.

    Formerly test_plan_collect_days_master.py.
    """
    #!/usr/bin/env python3

    import json
    import shutil
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    FAILED: list[str] = []
    FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-09-10" / "tasks" / "AutoCollect.json"
    AUTOMAS_FX = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11" / "config"


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def doc(schedule):
        opts = {} if schedule is None else {"AutoCollectSchedule": {"type": "checkbox", "caseNames": schedule}}
        return {"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoCollect", "enabled": True, "optionValues": opts}]}]}


    def setup(master_days, own_days):
        root = tmpdir()
        automas = root / "automas"
        cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps(doc(master_days)), encoding="utf-8")
        maaend = root / "maaend"
        (maaend / "config").mkdir(parents=True)
        (maaend / "tasks").mkdir()
        (maaend / "config" / "mxu-MaaEnd.json").write_text(json.dumps(doc(own_days)), encoding="utf-8")
        (maaend / "interface.json").write_text('{"import": ["tasks/AutoCollect.json"]}', encoding="utf-8")
        shutil.copy(FIX, maaend / "tasks" / "AutoCollect.json")
        shutil.copytree(AUTOMAS_FX, automas / "config")
        sc = automas / "config" / "ScriptConfig.json"
        d = json.loads(sc.read_text(encoding="utf-8"))
        for inst in d["instances"]:
            info = d[inst["uid"]]["Info"]
            if "maaend" in str(info.get("Path", "")).lower():
                info["Path"] = str(maaend)
        sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return automas


    def maaend_lines(automas, tomorrow):
        """The MaaEnd block's gathering line(s) in next_plan, for that tomorrow."""
        plan._tomorrow = lambda: tomorrow
        text = plan.next_plan(automas)
        return [ln.strip() for ln in text.splitlines() if "自动采集" in ln]


    MON_THU = ["AutoCollectScheduleMonday", "AutoCollectScheduleThursday"]
    TUESDAY = datetime(2026, 10, 13, 12, tzinfo=SERVER_TZ)
    THURSDAY = datetime(2026, 10, 15, 12, tzinfo=SERVER_TZ)

    print("[phone moved the days to Mon/Thu; MaaEnd's own file still says Tuesday only]")
    automas = setup(MON_THU, ["AutoCollectScheduleTuesday"])
    got = maaend_lines(automas, TUESDAY)
    require("Tuesday is not a gathering day", got == ["自动采集仅 周一、四 跑"], repr(got))
    got = maaend_lines(automas, THURSDAY)
    require("Thursday is", len(got) == 1 and got[0].startswith("⏳ 先跑自动采集"), repr(got))

    print("[no AutoCollectSchedule saved: MaaEnd's default_case, every day]")
    automas = setup(None, None)
    got = maaend_lines(automas, TUESDAY)
    require("the line is still there and says it runs", len(got) == 1 and got[0].startswith("⏳ 先跑自动采集"), repr(got))

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


def _part_plan_queue_weekdays():
    """The relay's view of which scripts a queue runs follows AUTO-MAS v5.7's own rules.

AUTO-MAS (v5.7.0-beta.2) skips a queue item whose Schedule.Days leave out the
day (app/core/task_manager.py _is_script_scheduled_today), fires a time only on
its TimeSet's Info.Days and never times a cycle queue (app/core/timer.py
_due_timed_slots), and an item with ScriptId "-" is not a script
(_queue_script_entries). The relay's one-day skip writes exactly Schedule.Days,
so before this a skipped MaaEnd still raised 「MaaEnd 没有运行（早班）」 and held
off the power-off for two hours.

Config: tests/fixtures/automas-config-2026-10-11 (the machine's own, see SOURCE.txt).

    Formerly test_plan_queue_weekdays.py.
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

    from ark_relay.core import plan
    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.engine import Engine
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.features.shutdown import shutdown

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


def _part_plan_silent():
    """Tomorrow's plan says when a source it needs could not be read (audit
docs/SILENT-FAILURES-AUDIT.md, plan.py rows).

The plan is rebuilt on every phone-state publish, and a WARNING is a group
message: each unreadable source is said once per condition, again only after it
read fine in between.

    Formerly test_plan_silent.py.
    """
    import json
    import logging
    import os
    from unittest import mock

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    os.environ["ARK_STATE_DIR"] = str(tmpdir())
    os.environ.pop("ARK_OKWW_DIR", None)
    from ark_relay.core import plan


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def warnings(self):
            out = [r for r in self.records if r.levelno >= logging.WARNING]
            self.records.clear()
            return out


    grab = Grab()
    plan.log.addHandler(grab)


    def fresh():
        getattr(plan, "_last_error", {}).clear()
        grab.records.clear()


    def farm_dir(text):
        d = tmpdir()
        if text is not None:
            (d / "FarmEchoTask.json").write_text(text, encoding="utf-8")
        return d


    print("[row 1: FarmEchoTask.json unreadable]")
    fresh()
    bad = farm_dir("{not json")
    got = plan._okww_extra_bit(bad, ["Teleport and Farm 4C Echo"], {"Teleport and Farm 4C Echo": "传送刷4C声骸"})
    check("unreadable -> says the slot cannot be read, not the 4C name", got, "附加 周本/4C 设置读不到")
    check("unreadable -> one WARNING", len(grab.warnings()), 1)
    plan._okww_extra_bit(bad, ["Teleport and Farm 4C Echo"], {})
    check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    good = farm_dir(json.dumps({"Teleport to Boss": "Normal"}))
    check("readable -> named as the echo task",
          plan._okww_extra_bit(good, ["Teleport and Farm 4C Echo"], {"Teleport and Farm 4C Echo": "传送刷4C声骸"}),
          "附加 传送刷4C声骸")
    check("readable -> no WARNING", len(grab.warnings()), 0)
    plan._okww_extra_bit(bad, ["Teleport and Farm 4C Echo"], {})
    check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)
    check("missing file is not an error -> echo name, no WARNING",
          (plan._okww_extra_bit(farm_dir(None), ["Teleport and Farm 4C Echo"], {}), len(grab.warnings())),
          ("附加 Teleport and Farm 4C Echo", 0))

    print("[row 2: weekly-boss bookkeeping unreadable]")
    fresh()
    weekly = farm_dir(json.dumps({"Teleport to Boss": "Weekly Challenge", "Boss Level": "90",
                                  "Which Weekly Boss to Teleport": 2}))
    broken = mock.patch("ark_relay.features.weekly.weeklyboss.WeeklyBossGate.settings", side_effect=OSError("state.json locked"))
    with broken:
        got = plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
        check("unknown -> says it cannot tell, not 「明天会打」", got,
              "附加 周本 战歌重奏第 2 个（90 级），本周打没打满读不到")
        check("unknown -> one WARNING", len(grab.warnings()), 1)
        plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
        check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.weekly.weeklyboss.WeeklyBossGate.settings",
                    return_value={"本周已打": False, "名字": ""}):
        check("readable -> 明天会打",
              plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {}).endswith("明天会打"), True)
    with broken:
        plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
        check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)

    print("[row 3: AUTO-MAS ScriptConfig.json unreadable]")
    fresh()


    def automas(script_config):
        root = tmpdir()
        d = root / "data" / "okww-sid" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        (d / "DailyTask.json").write_text(json.dumps({
            "Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
            "Additional Tasks to Run After Daily Task": ["Some Master Task"]}), encoding="utf-8")
        (root / "config").mkdir()
        (root / "config" / "ScriptConfig.json").write_text(script_config, encoding="utf-8")
        return root


    bad_root = automas("{broken")
    bits = plan._okww_plan_bits(bad_root)
    check("unreadable -> 附加任务读不到 instead of the master's list",
          [b for b in bits if b.startswith("附加")], ["附加任务读不到"])
    check("unreadable -> one WARNING", len(grab.warnings()), 1)
    plan._okww_plan_bits(bad_root)
    check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    off_root = automas(json.dumps({}))
    check("readable, quick config off -> the master's list",
          [b for b in plan._okww_plan_bits(off_root) if b.startswith("附加")], ["附加 Some Master Task"])
    check("readable -> no WARNING", len(grab.warnings()), 0)
    plan._okww_plan_bits(bad_root)
    check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)

    print("[row 4: annihilation weekly status unreadable]")
    fresh()
    with mock.patch("ark_relay.features.weekly.annihilation.WeeklyGate.settings", side_effect=RuntimeError("gate broke")):
        check("unreadable -> unknown (None), not reported as done or as running",
              plan._annihilation_done_tomorrow(None), None)
        w = grab.warnings()
        check("unreadable -> one WARNING with the traceback", (len(w), bool(w and w[0].exc_info)), (1, True))
        plan._annihilation_done_tomorrow(None)
        check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.weekly.annihilation.WeeklyGate.settings", return_value={"本周已完成": False, "当前": ""}):
        plan._annihilation_done_tomorrow(None)
        check("readable -> no WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.weekly.annihilation.WeeklyGate.settings", side_effect=RuntimeError("gate broke")):
        plan._annihilation_done_tomorrow(None)
        check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)

    print("[row 5: maintenance_lines unexpected error]")
    fresh()
    import datetime as _dt
    day = _dt.date(2026, 10, 11)
    with mock.patch("ark_relay.features.maintenance.maintenance.today", side_effect=KeyError("window")):
        check("error -> no line (as before)", plan.maintenance_lines(day), [])
        w = grab.warnings()
        check("error -> one WARNING with the traceback", (len(w), bool(w and w[0].exc_info)), (1, True))
        plan.maintenance_lines(day)
        check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.maintenance.maintenance.today", return_value={}):
        plan.maintenance_lines(day)
        check("works -> no WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.maintenance.maintenance.today", side_effect=KeyError("window")):
        plan.maintenance_lines(day)
        check("broken again after it worked -> WARNING again", len(grab.warnings()), 1)


def _part_plan_stage_modes():
    """「明日安排」 shows MAA's stages the way AUTO-MAS v5.7 hands them to MAA.

task/MAA/AutoProxy.py: StageMode "Fixed" takes Stage/Stage_1..3/MedicineNumb
from the user's settings, any other StageMode is a PlanConfig uid; "-" is an
empty slot, "*" becomes "" (MAA: current / last stage). The old plan printed
「理智 -（固定）」 for an empty stage, the raw "*", the plan uid as the mode,
ignored Stage_1..3, and called 999 potions "unlimited" with no source.
Base data: the real 10-11 AUTO-MAS config (YW-4, Fixed, 999).

    Formerly test_plan_stage_modes.py.
    """
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    FAILED: list[str] = []
    REAL = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"
    PLAN_UID = "c88cfe9e-6617-4fb8-9225-183ca571e3ae"


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def maa_block(edit_info=None, edit_plan=None) -> list[str]:
        root = tmpdir()
        shutil.copytree(REAL, root / "a")
        cfg = root / "a" / "config"
        sf = cfg / "ScriptConfig.json"
        d = json.loads(sf.read_text(encoding="utf-8"))
        for inst in d["instances"]:
            node = d[inst["uid"]]
            if node["Info"].get("Name") == "MAA" and edit_info:
                for u in node["SubConfigsInfo"]["UserData"].values():
                    if isinstance(u, dict):
                        u["Info"].update(edit_info)
        sf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        if edit_plan:
            pf = cfg / "PlanConfig.json"
            pd = json.loads(pf.read_text(encoding="utf-8"))
            edit_plan(pd[PLAN_UID])
            pf.write_text(json.dumps(pd, ensure_ascii=False), encoding="utf-8")
        text = plan.next_plan(root / "a")
        lines = text.splitlines()
        i = lines.index("▸ 明日方舟")
        out = []
        for ln in lines[i + 1:]:
            if not ln.startswith("　"):
                break
            out.append(ln.strip())
        return out


    print("[real config: YW-4, Fixed, 999]")
    got = maa_block()
    require("stage line", "理智 YW-4（固定）" in got, repr(got))
    require("999 is a number of potions, not 'unlimited'", "理智药最多 999 个" in got, repr(got))

    print("[empty stage '-']")
    got = maa_block({"Stage": "-"})
    require("no '理智 -'", not any(b.startswith("理智 -") for b in got) and "理智 没设关卡（固定）" in got, repr(got))

    print("[no StageMode read, no annihilation: still one line]")
    got = maa_block({"StageMode": "", "Annihilation": ""})
    require("a line saying the stage setting was not read", got == ["理智 读不到关卡设置"], repr(got))

    print("[\"*\" and fallback stages]")
    got = maa_block({"Stage": "*", "Stage_1": "1-7", "Stage_2": "-", "Stage_3": "CE-6"})
    require("current/last stage, then the fallbacks in order",
            "理智 当前/上次关卡（固定），打不了依次换 1-7、CE-6" in got, repr(got))

    print("[StageMode is a plan table (Weekly)]")


    def weekly(node):
        node["Info"]["Mode"] = "Weekly"
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
            node[day].update({"Stage": f"S-{day[:3]}", "MedicineNumb": 2})


    got = maa_block({"StageMode": PLAN_UID}, weekly)
    day = plan._tomorrow().strftime("%A")[:3]
    require("stage from tomorrow's row, plan named, no raw uid",
            f"理智 S-{day}（计划表「新 MAA 计划表」）" in got and not any(PLAN_UID in b for b in got), repr(got))
    require("potions from the plan table, not the user's 999", "理智药最多 2 个" in got, repr(got))

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


def _part_plan_startup_mode():
    """queue_rows' 「开机跑」 comes from AUTO-MAS v5.7's StartUpMode.

v5.7 replaced the bool StartUpEnabled with StartUpMode (Never / Always /
DailyFirst; app/models/config.py migrates True -> Always, False -> Never). The
relay still read StartUpEnabled, so on the real 10-11 config every queue said
「开机跑」: None.

    Formerly test_plan_startup_mode.py.
    """
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan

    FAILED: list[str] = []
    REAL = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    print("[real 10-11 config: both queues StartUpMode Never]")
    rows = plan.queue_rows(REAL)
    require("开机跑 is False, not None", [r["开机跑"] for r in rows] == [False, False], repr(rows))

    print("[Always and DailyFirst both run at start-up]")
    root = tmpdir()
    shutil.copytree(REAL, root / "a")
    qf = root / "a" / "config" / "QueueConfig.json"
    d = json.loads(qf.read_text(encoding="utf-8"))
    uids = [i["uid"] for i in d["instances"]]
    d[uids[0]]["Info"]["StartUpMode"] = "Always"
    d[uids[1]]["Info"]["StartUpMode"] = "DailyFirst"
    qf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    rows = plan.queue_rows(root / "a")
    require("both say True", [r["开机跑"] for r in rows] == [True, True], repr(rows))

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_plan_after_accomplish, _part_plan_collect_days_master, _part_plan_queue_weekdays, _part_plan_silent, _part_plan_stage_modes, _part_plan_startup_mode]))
