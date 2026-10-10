"""Stage gate: can MAA navigate to the stage AUTO-MAS will hand it?

2026-10-10: the stage was set to YW-4 at 04:25; MAA's stages.json knew it, but its
navigation file resource/tasks/Stages/YW.json had no YW-4 key yet, so MAA core
refused the Fight task (asst.log lines in _stagegate_fx.py) and the whole 09:00 run
stopped. The gate replicates MAA's own decision (FightTask.cpp / StageNavigationTask.cpp)
on the same task files, and pulls MAA from that one queue run when the answer is a
definite no - never on "could not tell".
"""
import logging
import os
import sys
import time
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
import _stagegate_fx as fx

os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import stagegate as sg, texts
from ark_relay.config import SERVER_TZ

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
