"""The stage gate, and several MAA users; a refused stage set, the gate's hooks.

One part per former file, each run on its own (tests/_parts.py): test_stagegate.py, test_stage_set_refused.py, test_stagegate_hooks.py.
"""
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
    """Stage gate: can MAA navigate to the stage AUTO-MAS will hand it?

2026-10-10: the stage was set to YW-4 at 04:25; MAA's stages.json knew it, but its
navigation file resource/tasks/Stages/YW.json had no YW-4 key yet, so MAA core
refused the Fight task (asst.log lines in _stagegate_fx.py) and the whole 09:00 run
stopped. The gate replicates MAA's own decision (FightTask.cpp / StageNavigationTask.cpp)
on the same task files, and pulls MAA from that one queue run when the answer is a
definite no - never on "could not tell".

    Formerly test_stagegate.py.
    """
    import logging
    import os
    import time
    import types
    from datetime import datetime

    import _stagegate_fx as fx

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.schedule import stagegate as sg
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ


    def at(d, hh, mm):
        return datetime(2026, 10, d, hh, mm, tzinfo=SERVER_TZ)


    MORNING = fx.maa_dir(tmpdir())
    AFTERNOON = fx.maa_dir(tmpdir(), yw=fx.YW_AFTERNOON)

    print("[what MAA core decides, on the 2026-10-10 task files]")
    v, why = sg.check("YW-4", MORNING)
    check("morning: YW-4 is a definite no", v, sg.NO)
    check("the reason names the stage and the folder", ("YW-4" in why, "resource/tasks" in why), (True, True))
    check("afternoon (YW-4 in YW.json): yes", sg.check("YW-4", AFTERNOON)[0], sg.YES)
    check("morning: YW-6 (in YW.json) yes", sg.check("YW-6", MORNING)[0], sg.YES)
    check("empty stage = current / last stage: yes", sg.check("", MORNING)[0], sg.YES)
    check("main line 1-7 with Episode1: yes", sg.check("1-7", MORNING)[0], sg.YES)
    check("main line 9-3 without Episode9: no", sg.check("9-3", MORNING)[0], sg.NO)
    check("prefixed main line H12-3 with Episode12: yes", sg.check("H12-3", MORNING)[0], sg.YES)
    check("SSReopen-YW with YW-OpenOpt: yes", sg.check("SSReopen-YW", AFTERNOON)[0], sg.YES)
    check("SSReopen-YW without YW-OpenOpt: no", sg.check("SSReopen-YW", MORNING)[0], sg.NO)
    check("SSReopen-OR (OR-OpenOpt exists): yes", sg.check("SSReopen-OR", MORNING)[0], sg.YES)
    check("SSReopen- with a 3-letter code is not the reopen form: no", sg.check("SSReopen-ORX", MORNING)[0], sg.NO)
    check("12-17-Hard with ChapterDifficultyHard: yes", sg.check("12-17-Hard", MORNING)[0], sg.YES)
    check("12-17-hard: MAA capitalises the suffix: yes", sg.check("12-17-hard", MORNING)[0], sg.YES)
    check("12-17-Tough: only Normal / Hard: no", sg.check("12-17-Tough", MORNING)[0], sg.NO)
    check("5-3-Hard: no difficulty below chapter 10: no", sg.check("5-3-Hard", MORNING)[0], sg.NO)
    check("15-2-Hard with ChangeToRaidDifficulty + RaidConfirm: yes", sg.check("15-2-Hard", MORNING)[0], sg.YES)
    check("15-2-Normal without NormalConfirm: no", sg.check("15-2-Normal", MORNING)[0], sg.NO)
    check("Episode15 exists but 15-2 has no suffix: yes", sg.check("15-2", MORNING)[0], sg.YES)
    check("a key only in cache/resource/tasks (hot update): yes", sg.check("HotFix-1", MORNING)[0], sg.YES)
    check("a key in a sub-folder (Roguelike/): yes", sg.check("Sami@Roguelike@Begin", MORNING)[0], sg.YES)
    check("an unknown name with '@' (MAA may derive it): unknown", sg.check("YW-9@SideStoryStage", MORNING)[0],
          sg.UNKNOWN)
    check("non-ASCII digits are not \\d for MAA: no", sg.check("１-7", MORNING)[0], sg.NO)

    print("\n[could not read -> unknown, never no]")
    check("no MAA folder configured", sg.check("YW-4", None)[0], sg.UNKNOWN)
    check("MAA folder without resource/tasks", sg.check("YW-4", tmpdir())[0], sg.UNKNOWN)
    broken = fx.maa_dir(tmpdir())
    (broken / "resource" / "tasks" / "Stages" / "ZZ.json").write_text("{ not json", encoding="utf-8")
    check("one task file does not parse", sg.check("YW-4", broken)[0], sg.UNKNOWN)
    nocache = fx.maa_dir(tmpdir())
    (nocache / "cache" / "resource" / "tasks" / "tasks.json").unlink()
    check("no hot update folder content is fine (MAA loads none)", sg.check("YW-4", nocache)[0], sg.NO)

    print("\n[which stage AUTO-MAS will send (AutoProxy.set_maa)]")
    SAT9 = at(10, 9, 0)        # Saturday 09:00 Beijing = Saturday 05:00 game day (UTC+4)
    check("Fixed: Info.Stage YW-4 -> no", sg.run_verdict(fx.automas_dir(tmpdir()), MORNING, SAT9)[:2], (sg.NO, "YW-4"))
    check("Fight switched off: nothing to check", sg.run_verdict(fx.automas_dir(tmpdir(), fight=False), MORNING, SAT9)[0],
          sg.YES)
    check("'*' is sent as '' (current stage): yes",
          sg.run_verdict(fx.automas_dir(tmpdir(), stage="*"), MORNING, SAT9)[0], sg.YES)
    check("'-' everywhere: no stage, yes", sg.run_verdict(fx.automas_dir(tmpdir(), stage="-"), MORNING, SAT9)[0], sg.YES)
    check("YW-4 first, 1-7 as an alternate: not a definite no",
          sg.run_verdict(fx.automas_dir(tmpdir(), stage_1="1-7"), MORNING, SAT9)[0] != sg.NO, True)
    check("afternoon: yes", sg.run_verdict(fx.automas_dir(tmpdir()), AFTERNOON, SAT9)[0], sg.YES)
    check("no ScriptConfig.json: unknown", sg.run_verdict(tmpdir(), MORNING, SAT9)[0], sg.UNKNOWN)
    UID = "6a2c3a4e-0000-4000-8000-000000000001"
    blank = {k: "-" for k in ("Stage", "Stage_1", "Stage_2", "Stage_3")}
    plan_all = {"instances": [{"uid": UID, "type": "MaaPlanConfig"}],
                UID: {"Info": {"Name": "p", "Mode": "ALL"}, "ALL": dict(blank, Stage="YW-4")}}
    check("plan table, ALL: YW-4 -> no",
          sg.run_verdict(fx.automas_dir(tmpdir(), mode=UID, plan=plan_all), MORNING, SAT9)[:2], (sg.NO, "YW-4"))
    plan_week = {"instances": [{"uid": UID}],
                 UID: {"Info": {"Name": "p", "Mode": "Weekly"}, "ALL": dict(blank, Stage="1-7"),
                       "Saturday": dict(blank, Stage="YW-4")}}
    check("plan table, Weekly, Saturday: YW-4 -> no",
          sg.run_verdict(fx.automas_dir(tmpdir(), mode=UID, plan=plan_week), MORNING, SAT9)[0], sg.NO)
    check("plan table, Weekly, Friday falls back to ALL (1-7): yes",
          sg.run_verdict(fx.automas_dir(tmpdir(), mode=UID, plan=plan_week), MORNING, at(9, 21, 30))[0], sg.YES)
    check("03:30 Beijing: game day (UTC+4) and local day disagree -> unknown",
          sg.run_verdict(fx.automas_dir(tmpdir(), mode=UID, plan=plan_week), MORNING, at(10, 3, 30))[0], sg.UNKNOWN)
    check("StageMode names a plan that is not there: unknown",
          sg.run_verdict(fx.automas_dir(tmpdir(), mode=UID, plan={"instances": []}), MORNING, SAT9)[0], sg.UNKNOWN)


    SHIPPED = getattr(sg, "PULL_FROM_QUEUE", None)
    print("\n[as shipped, the queue pull is off: no user quote for it in USER-SWITCHES.txt]")
    check("PULL_FROM_QUEUE is False", SHIPPED, False)

    print("\n[pull switched on (PULL_FROM_QUEUE = True): before each MAA due, pull MAA from that queue run, one alarm]")
    sg.PULL_FROM_QUEUE = True


    class Note:
        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []


    def world(maa=None, **kw):
        st = tmpdir()
        return types.SimpleNamespace(state_dir=st, automas_dir=fx.automas_dir(tmpdir(), **kw),
                                     maa_dir=maa or fx.maa_dir(tmpdir()))


    skipped, restored = [], []


    def skipper(queue, script):
        skipped.append((queue, script))
        return {"queue": queue, "queueId": "Q-" + queue, "script": script, "scriptId": "S-MAA", "position": 0,
                "day": "2026-10-10"}


    def restorer(rec):
        restored.append((rec["queue"], rec["script"]))
        return True


    def step(cfg, n, now, busy=False, **kw):
        sg.step(cfg, n, now, busy=lambda: busy, skipper=kw.get("skip", skipper), restorer=restorer)


    cfg, n = world(), Note()
    step(cfg, n, at(10, 8, 45))
    check("08:45: outside the 10-minute lead, nothing", (skipped, n.sent), ([], []))
    step(cfg, n, at(10, 8, 52))
    check("08:52: MAA pulled from 早班 only", skipped, [("早班", "MAA")])
    check("exactly one alarm, to the group", [(t, a) for t, _b, a in n.sent], [(texts.stage_gate("早班"), True)])
    check("the alarm says which stage and why", ("YW-4" in n.sent[0][1], "resource/tasks" in n.sent[0][1]),
          (True, True))
    step(cfg, n, at(10, 8, 53))
    step(cfg, n, at(10, 8, 59))
    check("later ticks: no second pull, no second alarm", (len(skipped), len(n.sent)), (1, 1))
    n2 = Note()
    step(cfg, n2, at(10, 8, 56))            # a relay restart reads the same state
    check("after a relay restart: still one", (len(skipped), n2.sent), (1, []))
    check("excused: 早班 09:00", sg.excused(cfg.state_dir, "早班", at(10, 9, 0)), True)
    check("not excused: 晚班 21:30", sg.excused(cfg.state_dir, "晚班", at(10, 21, 30)), False)
    check("早班 still had MaaEnd: not settled alone", sg.settled_alone(cfg.state_dir, "早班", at(10, 9, 0)), False)

    print("\n[putting MAA back]")
    step(cfg, n, at(10, 9, 3))
    check("09:03: the queue has just started, not yet", restored, [])
    step(cfg, n, at(10, 9, 20), busy=True)
    check("09:20, MaaEnd still running: not yet", restored, [])
    step(cfg, n, at(10, 9, 41))
    check("09:41, nothing running: put back into 早班", restored, [("早班", "MAA")])
    check("the pull record is gone", sg.skips(cfg.state_dir), [])
    check("still excused after the put-back (the report / missed checks keep knowing)",
          sg.excused(cfg.state_dir, "早班", at(10, 9, 0)), True)
    line = sg.report_line(cfg.state_dir, "2026-10-10")
    check("the daily report says it, with the reason", ("早班" in line, "YW-4" in line), (True, True))
    step(cfg, n, at(10, 21, 22))
    check("21:22 晚班: checked on its own, pulled on its own", skipped[-1], ("晚班", "MAA"))
    check("one alarm for that due", [t for t, _b, _a in n.sent][-1], texts.stage_gate("晚班"))
    check("晚班 had only MAA: settled alone", sg.settled_alone(cfg.state_dir, "晚班", at(10, 21, 30)), True)
    check("recent_pulled gives that run to the shutdown check",
          [q["name"] for q in sg.recent_pulled(cfg.state_dir, at(10, 21, 40))], ["晚班"])

    print("\n[it becomes reachable before the due: put back at once]")
    skipped.clear()
    restored.clear()
    cfg, n = world(), Note()
    step(cfg, n, at(10, 8, 52))
    check("pulled", skipped, [("早班", "MAA")])
    time.sleep(0.01)
    fx.set_yw(cfg.maa_dir, fx.YW_AFTERNOON)
    st = os.stat(cfg.maa_dir / "resource" / "tasks" / "Stages" / "YW.json")
    os.utime(cfg.maa_dir / "resource" / "tasks" / "Stages" / "YW.json", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    step(cfg, n, at(10, 8, 55))
    check("YW.json gained YW-4: back into 早班 before 09:00", restored, [("早班", "MAA")])
    check("no second alarm", len(n.sent), 1)

    print("\n[a pull left over from yesterday: put back]")
    restored.clear()
    cfg, n = world(), Note()
    step(cfg, n, at(10, 21, 22))
    step(cfg, n, at(11, 7, 0), busy=False)
    check("next morning: back", restored, [("晚班", "MAA")])

    print("\n[reachable or unknown: nothing]")
    skipped.clear()
    cfg, n = world(maa=fx.maa_dir(tmpdir(), yw=fx.YW_AFTERNOON)), Note()
    step(cfg, n, at(10, 8, 52))
    check("reachable: no pull, no alarm", (skipped, n.sent), ([], []))
    bad = fx.maa_dir(tmpdir())
    (bad / "resource" / "tasks" / "Stages" / "ZZ.json").write_text("{", encoding="utf-8")
    cfg, n = world(maa=bad), Note()
    step(cfg, n, at(10, 8, 52))
    check("unknown (a task file does not parse): no pull, no alarm", (skipped, n.sent), ([], []))
    cfg, n = world(fight=False), Note()
    step(cfg, n, at(10, 8, 52))
    check("Fight off: no pull, no alarm", (skipped, n.sent), ([], []))

    print("\n[the boot pass: the machine is up at 08:40 / 21:20 for 09:00 / 21:30]")
    skipped.clear()
    cfg, n = world(), Note()
    sg.step(cfg, n, at(10, 8, 46), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    check("boot at 08:46 (14 min before): a no is acted on at once", (skipped, len(n.sent)), ([("早班", "MAA")], 1))
    step(cfg, n, at(10, 8, 52))
    check("the tick in the last 10 minutes does not repeat it", (len(skipped), len(n.sent)), (1, 1))
    skipped.clear()
    cfg, n = world(stage="1-7"), Note()
    sg.step(cfg, n, at(10, 8, 46), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    check("boot: reachable, nothing done", (skipped, n.sent), ([], []))
    fx.automas_dir(cfg.automas_dir, stage="YW-4")      # changed after boot (e.g. from AUTO-MAS's own screen)
    step(cfg, n, at(10, 8, 52))
    check("a boot-time yes is not kept: the tick checks again and catches the change", skipped, [("早班", "MAA")])
    skipped.clear()
    cfg, n = world(), Note()
    sg.step(cfg, n, at(10, 9, 1), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    check("boot at 09:01 (after the due): too late for 早班, nothing", (skipped, n.sent), ([], []))

    print("\n[pull not possible]")
    cfg, n = world(), Note()
    step(cfg, n, at(10, 8, 52), skip=lambda q, s: None)
    check("MAA was not in the queue any more: still the one alarm (the next shift has the same stage)",
          [t for t, _b, _a in n.sent], [texts.stage_gate("早班")])
    check("... saying MAA was not in this shift", "本来就没有 MAA" in n.sent[0][1], True)
    check("... and nothing to put back", sg.skips(cfg.state_dir), [])
    cfg, n = world(), Note()


    def boom(q, s):
        raise RuntimeError("queue api down")


    step(cfg, n, at(10, 8, 52), skip=boom)
    check("the pull failed: still the one alarm", [t for t, _b, _a in n.sent], [texts.stage_gate("早班")])
    check("... and it says MAA could not be taken out", "没能" in n.sent[0][1], True)
    check("nothing to put back", sg.skips(cfg.state_dir), [])

    print("\n[as shipped (pull off): before each due, one alarm only - MAA still runs and is refused by MAA]")
    sg.PULL_FROM_QUEUE = False
    skipped.clear()
    restored.clear()
    cfg, n = world(), Note()
    step(cfg, n, at(10, 8, 52))
    check("no pull", skipped, [])
    check("one alarm, to the group, its own title", [(t, a) for t, _b, a in n.sent], [(texts.stage_gate_warn("早班"), True)])
    check("it says which stage, why, and that MAA still runs and will be refused",
          ("YW-4" in n.sent[0][1], "resource/tasks" in n.sent[0][1], "MAA 照跑" in n.sent[0][1]), (True, True, True))
    step(cfg, n, at(10, 8, 55))
    step(cfg, Note(), at(10, 8, 57))
    check("once per due, restarts included", (len(n.sent), skipped), (1, []))
    check("nothing to put back", sg.skips(cfg.state_dir), [])
    check("missed checks: not excused", (sg.excused(cfg.state_dir, "早班", at(10, 9, 0)),
                                          sg.settled_alone(cfg.state_dir, "早班", at(10, 9, 0))), (False, False))
    check("shutdown: no pulled shift", sg.recent_pulled(cfg.state_dir, at(10, 9, 10)), [])
    check("report: no 「没开跑」 section (MAA's own failure is reported as before)",
          sg.report_line(cfg.state_dir, "2026-10-10"), "")
    step(cfg, n, at(10, 21, 22))
    check("晚班: its own alarm", [t for t, _b, _a in n.sent][-1], texts.stage_gate_warn("晚班"))
    cfg, n = world(), Note()
    sg.step(cfg, n, at(10, 8, 46), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    step(cfg, n, at(10, 8, 52))
    check("boot pass + tick: still one alarm", (len(n.sent), skipped), (1, []))

    print("\n[task files unreadable: one WARNING per due, not one per check]")


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    grab = Grab()
    sg.log.addHandler(grab)
    bad = fx.maa_dir(tmpdir())
    (bad / "resource" / "tasks" / "Stages" / "ZZ.json").write_text("{", encoding="utf-8")
    cfg, n = world(maa=bad), Note()
    sg.step(cfg, n, at(10, 8, 46), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    step(cfg, n, at(10, 8, 51))
    step(cfg, n, at(10, 8, 52))
    step(cfg, Note(), at(10, 8, 55))             # a relay restart
    check("boot pass, ticks and a restart: one WARNING for 早班", len(grab.lines), 1)
    check("it names the file it could not read", "ZZ.json" in (grab.lines or [""])[0], True)
    step(cfg, n, at(10, 21, 22))
    check("晚班 is another due: one more", len(grab.lines), 2)
    check("no alarm, no pull", (n.sent, skipped), ([], []))
    sg.log.removeHandler(grab)


def _part_stagegate_users():
    """Several MAA users: one user's stage MAA cannot reach is said, users AUTO-MAS does not run
are not looked at, and a pull never takes MAA from a user whose stage is reachable
(audit 11-08 B-D23; dispatch relay-opt-round4-1108 R4-06; stagegate.run_verdict / _gate_due).

Before: run_verdict answered "no" only when every user was "no", so with a second account on
a reachable stage the first account's unreachable one went unsaid (its MAA run then stops at
「Cannot set stage」), and a user AUTO-MAS skips (Info.Status off, RemainedDay 0 -
app/task/manager_base.py is_user_selected) counted like the others.

Not changed, on purpose: several stages for one user, the first unreachable and another
reachable, stays "unknown" - AUTO-MAS sends the Routine fight with UseOptionalStage True
(app/task/MAA/AutoProxy.py ~1883, the v6.19.0 copy under gamesim/upstream) and MAA's GUI
picks the first stage open today, which the relay does not replicate.

    Formerly test_stagegate_users_1108.py.
    """
    import json
    import os
    import types
    from datetime import datetime

    import _stagegate_fx as fx

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.schedule import stagegate as sg


    SAT9 = datetime(2026, 10, 10, 9, 0, tzinfo=SERVER_TZ)
    MORNING = fx.maa_dir(tmpdir())          # YW-4 has no navigation task here; 1-7 has


    def two_users(second_stage="1-7", first_info=None):
        """The fixture's MAA user 「arknights」 on YW-4, plus 「小号」 on `second_stage`."""
        d = fx.automas_dir(tmpdir())
        p = d / "config" / "ScriptConfig.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        users = data["S-MAA"]["SubConfigsInfo"]["UserData"]
        users["U1"]["Info"].update(first_info or {})
        users["instances"].append({"uid": "U3"})
        users["U3"] = {"Info": {"Name": "小号", "Stage": second_stage, "Stage_1": "-", "Stage_2": "-", "Stage_3": "-",
                                "StageMode": "Fixed", "MedicineNumb": 0}, "Task": {"IfFight": True}}
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return d


    print("[两个用户，一个走不到：说走不到，点名是哪个用户]")
    every = []
    v, stage, why = sg.run_verdict(two_users(), MORNING, SAT9, [], every)
    check("结论是走不到", (v, stage), (sg.NO, "YW-4"))
    check("原因点名用户", why.startswith("用户「arknights」："), True)
    check("每个用户的结论都给出来", [x[0] for x in every], [sg.NO, sg.YES])
    check("两个都走不到：照旧走不到", sg.run_verdict(two_users("YW-4"), MORNING, SAT9)[0], sg.NO)
    check("两个都走得到：走得到", sg.run_verdict(two_users("1-7", {"Stage": "1-7"}), MORNING, SAT9)[0], sg.YES)

    print("\n[AUTO-MAS 不跑的用户不看（Status 关、RemainedDay 0）]")
    check("走不到的那个 Status 关着：走得到", sg.run_verdict(two_users(first_info={"Status": False}), MORNING, SAT9)[0],
          sg.YES)
    check("走不到的那个 RemainedDay 0：走得到", sg.run_verdict(two_users(first_info={"RemainedDay": 0}), MORNING, SAT9)[0],
          sg.YES)
    check("RemainedDay 还有天数：照看", sg.run_verdict(two_users(first_info={"RemainedDay": 3}), MORNING, SAT9)[0], sg.NO)
    one = fx.automas_dir(tmpdir())
    p1 = one / "config" / "ScriptConfig.json"
    d1 = json.loads(p1.read_text(encoding="utf-8"))
    d1["S-MAA"]["SubConfigsInfo"]["UserData"]["U1"]["Info"]["Status"] = False
    p1.write_text(json.dumps(d1, ensure_ascii=False), encoding="utf-8")
    check("只有一个用户、它不跑：没有用户可看，不拦", sg.run_verdict(one, MORNING, SAT9), (sg.YES, "", "MAA 没有用户"))

    print("\n[一个用户、首关走不到、备选走得到：照旧不拦（MAA 按开放日挑，中继不复刻）]")
    check("首关 YW-4、备选 1-7：不知道", sg.run_verdict(fx.automas_dir(tmpdir(), stage_1="1-7"), MORNING, SAT9)[0],
          sg.UNKNOWN)


    class Note:
        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []


    print("\n[打开「拿掉 MAA」时：只有一个用户走不到，只报不拿（拿掉会连走得到的那个一起拿）]")
    pulled = []
    saved = sg.PULL_FROM_QUEUE
    sg.PULL_FROM_QUEUE = True
    try:
        cfg = types.SimpleNamespace(state_dir=tmpdir(), automas_dir=two_users(), maa_dir=MORNING)
        n = Note()
        sg.step(cfg, n, datetime(2026, 10, 10, 8, 52, tzinfo=SERVER_TZ), busy=lambda: False,
                skipper=lambda q, s: pulled.append((q, s)) or {"queue": q, "script": s}, restorer=lambda rec: True)
        check("没拿掉 MAA", pulled, [])
        check("报了一次「走不到、MAA 照跑」", [t for t, _b, _a in n.sent], [texts.stage_gate_warn("早班")])
        check("……里面点名用户", "arknights" in n.sent[0][1], True)
    finally:
        sg.PULL_FROM_QUEUE = saved


def _part_stage_set_refused():
    """Every way of setting MAA's stage refuses a stage MAA cannot navigate to, and says so.

What the user asked for is USER_SAID below (2026-10-10 16:58, Osaka), verbatim.

All of them end in commands.apply_command: the phone page and the App (live, or
queued while a script runs and drained afterwards, or read from the mailbox backlog
at boot), scripts/mac/order-now.sh (the same ntfy channel) - all through
phone_channel._phone_execute, whose receipt is what the phone shows - and
scripts/mac/order.sh (the repo inbox, inbox.Inbox._apply). The stage arrives as
set_stage (Info.Stage) or set_config (Info.Stage / Stage_1..3). A definite "no" is
refused before anything is written, the receipt is a failure whose text contains
「MAA 走不到，修改失败」, the stage and why; "could not tell" goes through.

    Formerly test_stage_set_refused.py.
    """
    import json
    import logging
    import os
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        """Stands in for any pywin32 attribute (boot_stages pulls in service helpers)."""
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    import _stagegate_fx as fx

    TMP = tmpdir()
    MORNING = fx.maa_dir(TMP / "maa-morning")
    AFTERNOON = fx.maa_dir(TMP / "maa-afternoon", yw=fx.YW_AFTERNOON)
    AUTOMAS = fx.automas_dir(TMP / "AUTO-MAS", stage="1-7")
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_AUTOMAS_DIR=str(AUTOMAS), ARK_MAA_DIR=str(MORNING),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="")
    from ark_relay.features.phone import phone_channel
    from ark_relay.features.phone import commands, inbox
    from ark_relay.core import texts

    USER_SAID = ("2026-10-10 16:58 (Osaka): 「我自己在离线设定的时候，就是手机遥控器那边一定一定要提示我maa走不到，"
                 "修改失败。如果是我通过你们去改关卡，你们自己要核实能不能做到。如果走不到就报修改失败。」")
    PHRASE = "MAA 走不到，修改失败"
    print("  (the user's words this part holds the relay to:", USER_SAID + ")")


    writes = []
    commands._backend_scripts = lambda: ({"stub": {}}, "")        # the backend answers
    commands._user_item_report = lambda s, p, v: (writes.append((s, p, v)), (True, f"{p}：→ {v}"))[1]
    commands._user_item_via_api = lambda s, p, v: (writes.append((s, p, v)), ("", "1-7", v))[1]


    class Note:
        def __init__(self):
            self.sent = []

        def send(self, title, body, alert=False, **kw):
            self.sent.append((title, body, alert))
            return []


    def phone(body):
        """One order through the phone channel's executor, as live / drained / boot backlog do."""
        n, receipts = Note(), []
        phone_channel._phone_execute(commands.apply_command, n, logging.getLogger("ark.test_stagegate"),
                                   lambda *a, **k: None, lambda a, s, ok, msg, **k: receipts.append((ok, msg)),
                                   dict(body, confirmed=True), body["action"], None, True)
        return receipts[0], n.sent


    print("[the phone page / App / order-now.sh: set_stage]")
    writes.clear()
    (ok, msg), sent = phone({"action": "set_stage", "value": "YW-4"})
    check("refused: the receipt is a failure", ok, False)
    check("the receipt says 「MAA 走不到，修改失败」, the stage and why",
          (PHRASE in msg, "YW-4" in msg, "resource/tasks" in msg), (True, True, True))
    check("nothing written", writes, [])
    check("and the group hears 「📱 配置没改成」 with the same text", [(t, a, PHRASE in b) for t, b, a in sent],
          [(texts.CONFIG_FAILED, True, True)])

    print("\n[set_config, the App's and the page's stage box]")
    for path in ("Info.Stage", "Info.Stage_1", "Info.Stage_3"):
        writes.clear()
        (ok, msg), _sent = phone({"action": "set_config", "script": "MAA", "path": path, "value": "YW-4"})
        check(f"{path}: refused with the phrase, nothing written", (ok, PHRASE in msg, writes), (False, True, []))
    writes.clear()
    (ok, msg), _sent = phone({"action": "set_config", "script": "MAA", "path": "Info.Stage", "value": "1-7"})
    check("a reachable stage is written", (ok, writes), (True, [("MAA", "Info.Stage", "1-7")]))

    print("\n[the MAA script under another display name]")
    data = json.loads((AUTOMAS / "config" / "ScriptConfig.json").read_text(encoding="utf-8"))
    data["S-MAA"]["Info"]["Name"] = "maa明日方舟"
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    writes.clear()
    (ok, msg), _sent = phone({"action": "set_config", "script": "maa明日方舟", "path": "Info.Stage", "value": "YW-4"})
    check("refused by the script's install path, not its name", (ok, PHRASE in msg, writes), (False, True, []))
    data["S-MAA"]["Info"]["Name"] = "MAA"
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    print("\n[order.sh: the repo inbox applied at boot / before power-off]")
    box = inbox.Inbox(TMP / "state", automas_dir=AUTOMAS)
    writes.clear()
    lines = box._apply([{"action": "set_stage", "value": "YW-4"}])
    check("the inbox line is a failure with the phrase", (lines[0].startswith("✗"), PHRASE in lines[0]), (True, True))
    check("nothing written", writes, [])

    print("\n[AUTO-MAS down: set_stage would edit the file - refused before that]")
    commands._backend_scripts = lambda: (None, "")
    before = (AUTOMAS / "config" / "ScriptConfig.json").read_text(encoding="utf-8")
    ok, msg = commands.apply_command({"action": "set_stage", "value": "YW-4", "confirmed": True})
    check("refused with the phrase", (ok, PHRASE in msg), (False, True))
    check("the config file is untouched", (AUTOMAS / "config" / "ScriptConfig.json").read_text(encoding="utf-8"),
          before)
    commands._backend_scripts = lambda: ({"stub": {}}, "")

    print("\n[reachable / could not tell: goes through]")
    os.environ["ARK_MAA_DIR"] = str(AFTERNOON)
    writes.clear()
    (ok, msg), _sent = phone({"action": "set_stage", "value": "YW-4"})
    check("afternoon files: YW-4 is written", (ok, writes), (True, [("MAA", "Info.Stage", "YW-4")]))
    os.environ["ARK_MAA_DIR"] = str(TMP / "no-such-maa")
    writes.clear()
    (ok, msg), _sent = phone({"action": "set_stage", "value": "YW-4"})
    check("task files unreadable: written (unknown never blocks)", (ok, writes), (True, [("MAA", "Info.Stage", "YW-4")]))


def _part_stagegate_hooks():
    """Where the stage gate is wired in: setting a stage, and what a stage-gate pull means
for the missed-run checks and the shutdown decision.

2026-10-10 04:25 the stage was set to YW-4, a stage MAA had no navigation for
(resource/tasks/Stages/YW.json lacked the key; asst.log in _stagegate_fx.py), and
the 09:00 MAA run stopped at its first task. Setting such a stage is refused now.
A queue run the gate took MAA out of is not "a run that never happened": the missed
checks stay quiet about MAA for it, and an MAA-only shift that was pulled lets the
machine power off instead of waiting for a run that was cancelled on purpose.

    Formerly test_stagegate_hooks.py.
    """
    import importlib
    import json
    import os
    from datetime import datetime

    import _stagegate_fx as fx

    TMP = tmpdir()
    MORNING = fx.maa_dir(TMP / "maa-morning")
    AFTERNOON = fx.maa_dir(TMP / "maa-afternoon", yw=fx.YW_AFTERNOON)
    AUTOMAS = fx.automas_dir(TMP / "AUTO-MAS")
    STATE = TMP / "state"
    STATE.mkdir()
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS), ARK_STATE_DIR=str(STATE),
                      ARK_MAA_DIR=str(MORNING), SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.phone import commands
    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.features.shutdown import shutdown
    from ark_relay.core.ledger import State
    from ark_relay.core.engine import Engine
    from ark_relay.core.notify import Notifier

    try:
        sg = importlib.import_module("ark_relay.features.schedule.stagegate")
    except ImportError:
        sg = None


    def at(hh, mm, d=10):
        return datetime(2026, 10, d, hh, mm, tzinfo=SERVER_TZ)


    print("[setting a stage MAA cannot navigate to is refused]")
    backend_calls = []
    commands._backend_scripts = lambda: (backend_calls.append(1), (None, "backend stub"))[1]
    api_calls = []
    commands._user_item_via_api = lambda s, p, v: (api_calls.append((s, p, v)), ("", "1-7", v))[1]

    ok, msg = commands._set_stage("YW-4")
    check("morning files: refused", ok, False)
    check("the reason names the stage and says 「MAA 走不到，修改失败」", ("YW-4" in msg, "MAA 走不到，修改失败" in msg),
          (True, True))
    check("refused before anything is written", backend_calls, [])
    ok, msg = commands._set_stage("yw-4")
    check("lower case is upper-cased first, still refused", ok, False)
    os.environ["ARK_MAA_DIR"] = str(AFTERNOON)
    commands._set_stage("YW-4")
    check("afternoon files: goes on to the backend", backend_calls, [1])
    os.environ["ARK_MAA_DIR"] = str(TMP / "no-such-maa")
    backend_calls.clear()
    commands._set_stage("YW-4")
    check("task files unreadable: not refused (unknown never blocks)", backend_calls, [1])
    os.environ["ARK_MAA_DIR"] = str(MORNING)
    backend_calls.clear()
    commands._set_stage("1-7")
    check("1-7 (Episode1 exists): goes on", backend_calls, [1])

    ok, msg = commands._set_config({"script": "MAA", "path": "Info.Stage", "value": "YW-4"})
    check("the phone's generic setter: refused too", (ok, "YW-4" in msg), (False, True))
    check("... and nothing written", api_calls, [])
    commands._set_config({"script": "MAA", "path": "Info.Stage", "value": "1-7"})
    check("a reachable stage via set_config goes through", api_calls, [("MAA", "Info.Stage", "1-7")])
    commands._set_config({"script": "MAA", "path": "Info.MedicineNumb", "value": 3})
    check("other items are not the gate's business", api_calls[-1], ("MAA", "Info.MedicineNumb", 3))
    commands._set_config({"script": "MAA", "path": "Info.Stage_1", "value": "-"})
    check("'-' (no alternate) is not a stage", api_calls[-1], ("MAA", "Info.Stage_1", "-"))


    print("\n[a queue run the gate pulled MAA from: no missed-run alarm for MAA]")
    sent = []


    class FakeNotifier(Notifier):
        def send(self, title, body, *, alert=False, daily=False):
            sent.append((title, alert))
            return []


    cfg = Config()
    E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
    E._boot_time = lambda now: at(8, 40)
    E._started_at = at(8, 41)
    E._scripts_running = lambda: False
    E._script_running = lambda kind: False


    def pull(queue, due, others):
        """Record a stage-gate pull the way stagegate.step leaves it."""
        if sg is None:
            return
        sg.note_pull(cfg.state_dir, {"queue": queue, "queueId": "Q", "script": "MAA", "scriptId": "S-MAA",
                                     "position": 0, "day": due.strftime("%Y-%m-%d")},
                     due=due, stage="YW-4", why="它的关卡资料里没有这一关的导航", others=others)


    # The morning queue ran MaaEnd only (MAA was pulled at 08:52).
    E.state.ledger_path("2026-10-10").write_text(
        json.dumps({"run_id": "r1", "script": "MaaEnd", "ok": True, "started": at(9, 1).isoformat(),
                    "finished": at(9, 30).isoformat()}) + "\n",
        encoding="utf-8")
    pull("早班", at(9, 0), ["MaaEnd"])
    E._check_missed_runs(at(10, 30))
    check("早班: MaaEnd ran, MAA was pulled -> no alarm about 早班", [t for t, _a in sent if "早班" in t], [])
    check("shutdown: 早班 is not unfinished", E._unfinished_queues(at(10, 30), E._recent_entries(at(10, 30))), [])

    print("\n[an MAA-only shift that was pulled: no 「没有运行」, and the machine may power off]")
    sent.clear()
    E._missed_alerted.clear()
    E._boot_time = lambda now: at(21, 10)
    E._started_at = at(21, 11)
    # While MAA is out, AUTO-MAS's queue file has no item left in 晚班.
    fx.automas_dir(AUTOMAS, queues={"早班": ("09:00", ["MAA", "MaaEnd"]), "晚班": ("21:30", [])})
    pull("晚班", at(21, 30), [])
    E._check_missed_runs(at(22, 0))
    check("晚班 pulled: no 「晚班 没有运行」", [t for t, _a in sent if "晚班" in t], [])
    shift = shutdown._shift_queues(E, at(21, 45), at(21, 10))
    check("shutdown: the pulled shift counts as this boot's shift, done",
          ([q["name"] for q in shift], shutdown._missing_scripts(E, shift, E._recent_entries(at(21, 45)))), (["晚班"], []))

    print("\n[without a pull the old alarms still fire]")
    sent.clear()
    E._missed_alerted.clear()
    fresh = tmpdir()
    cfg2 = Config()
    cfg2.state_dir = fresh
    E2 = Engine(cfg2, source=None, state=State(fresh), notifier=FakeNotifier(cfg2))
    E2._boot_time = lambda now: at(21, 10)
    E2._started_at = at(21, 11)
    E2._scripts_running = lambda: False
    fx.automas_dir(AUTOMAS)
    E2._check_missed_runs(at(22, 0))
    check("晚班 not pulled, nothing ran: 「晚班 没有运行」 alarms", [t for t, _a in sent if "晚班" in t] != [], True)
    check("not pulled: the shutdown check still waits for 晚班's MAA",
          shutdown._missing_scripts(E2, shutdown._shift_queues(E2, at(21, 45), at(21, 10)),
                                    E2._recent_entries(at(21, 45))) != [], True)

    print("\n[wiring: the tick runs the gate before the missed check and the shutdown; boot runs it once]")
    import inspect
    _tick = inspect.getsource(Engine.tick)
    check("tick: 关卡门 before 漏跑检查 before 关机",
          0 < _tick.find("self._stage_gate") < _tick.find("self._check_missed_runs") < _tick.find("self._maybe_shutdown"),
          True)
    seen = []
    if sg is not None:
        _real = sg.step
        sg.step = lambda cfg_, n_, now_=None, **kw: seen.append(kw["busy"])
        E._stage_gate()
        sg.step = _real
        sg.step = lambda cfg_, n_, now_=None, **kw: seen.append(kw["lead_min"])
        E._stage_gate(lead_min=sg.BOOT_LEAD_MIN)
        sg.step = _real
    check("Engine._stage_gate passes the scripts-running probe, and the boot lead when asked",
          seen, [E._scripts_running, sg.BOOT_LEAD_MIN if sg else None])
    _svc = (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8")
    check("boot sequence calls the gate stage right after AUTO-MAS answers, before the pre-update",
          0 < _svc.find("_stage_inbox_and_phone(") < _svc.find("boot_stages._stage_stagegate(engine, log)")
          < _svc.find("boot_stages._stage_preupdate("), True)
    _boot = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("the boot stage runs the gate (boot_stages needs pywin32, read as text)",
          ("def _stage_stagegate(engine, log)" in _boot, "engine._stage_gate(lead_min=stagegate.BOOT_LEAD_MIN)" in _boot),
          (True, True))
    _rep = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "report" / "report.py").read_text(encoding="utf-8")
    check("the daily report template appends the gate's lines", "stagegate.report_line(eng.cfg.state_dir, day)" in _rep,
          True)


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_stagegate_users, _part_stage_set_refused, _part_stagegate_hooks]))
