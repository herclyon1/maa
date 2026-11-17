"""Queues, run plans, shift windows, stage gates, dispatch, runwatch, and missed runs."""
from __future__ import annotations

# ruff: noqa: PLC0415
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


class _Any:
    """Stands in for any pywin32 attribute: callable, subclassable, truthy."""
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


def _stub_pywin32():
    """boot_stages and the service helpers import pywin32 at module scope; stub what is missing."""
    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))


class _NoSource:
    """A record source with nothing new."""
    def fetch(self, seen):
        return []


class _Notes:
    """A notifier with the real send() signature that keeps (title, body, alert)."""
    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


def _pinned_clock():
    """A datetime class whose now() answers its `at`; a new class each call, `at` is the part's own."""
    from datetime import datetime

    class Clock(datetime):
        at = None

        @classmethod
        def now(cls, tz=None):
            return cls.at

    return Clock


def _queue_backend(all_days, okww=True):
    """AUTO-MAS's queue API over one queue 「早班」 of MAA, MaaEnd (and OK-WW), as a class.

    `fail_get_after_update`: the item/get after the n-th update raises (the
    write landed, the read-back timed out). `fail_update`: the n-th update
    lands and then raises (the reply was lost)."""

    class Backend:
        def __init__(self, extra=None, fail_get_after_update=0, fail_update=0):
            self.scripts = {"s-maa": {"Info": {"Name": "MAA"}}, "s-end": {"Info": {"Name": "MaaEnd"}}}
            self.queues = {"q1": {"Info": {"Name": "早班"}}}
            self.items = {"i1": {"Info": {"ScriptId": "s-maa"}, "Schedule": {"Days": list(all_days)}},
                          "i2": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(all_days)}}}
            if okww:
                self.scripts["s-ww"] = {"Info": {"Name": "OK-WW"}}
                self.items["i3"] = {"Info": {"ScriptId": "s-ww"}, "Schedule": {"Days": list(all_days)}}
            self.items.update(extra or {})
            self.updates = 0
            self.fail_get, self.fail_update = fail_get_after_update, fail_update

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/get":
                return {"data": self.queues}
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/queue/item/get":
                if self.fail_get and self.updates == self.fail_get:
                    self.fail_get = 0
                    raise TimeoutError("timed out")
                return {"index": [{"uid": u} for u in self.items], "data": json.loads(json.dumps(self.items))}
            if path == "/api/queue/item/update":
                for sec, val in body["data"].items():
                    self.items[body["queueItemId"]].setdefault(sec, {}).update(val)
                self.updates += 1
                if self.fail_update and self.updates == self.fail_update:
                    raise ConnectionResetError("reply lost")
                return {"status": "success"}
            raise AssertionError(f"unexpected call {path}")

        def days(self, uid):
            return self.items[uid]["Schedule"]["Days"]

    return Backend


def _mas_runner(commands, clock):
    """run(be, fn, at): fn() with AUTO-MAS's API answered by `be` and the clock at `at`; the real API is put back."""
    real = commands._mas

    def run(be, fn, at):
        commands._mas, clock.at = be, at
        try:
            return fn()
        finally:
            commands._mas = real

    return run


def _doc_editor(pristine, path):
    """edit(fn): write `path` as the pristine JSON document with fn applied to it."""
    def edit(fn) -> None:
        doc = json.loads(pristine)
        fn(doc)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    return edit


def _write_ledger(state, day, rows):
    """That day's ledger: one ok row per (script, started, finished)."""
    lines = [json.dumps({"run_id": f"r{i}", "script": s, "started": a.isoformat(),
                         "finished": b.isoformat(), "ok": True}) for i, (s, a, b) in enumerate(rows)]
    state.ledger_path(day.strftime("%Y-%m-%d")).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _part_stagegate_main():
    """Stage gate: can MAA navigate to the stage AUTO-MAS will hand it?"""
    import logging
    import os
    import time
    import types
    from datetime import datetime

    from _parts import stagegate_fx; fx = stagegate_fx()

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import stagegate as sg
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

    cfg, n = world(), _Notes()
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
    n2 = _Notes()
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
    cfg, n = world(), _Notes()
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
    cfg, n = world(), _Notes()
    step(cfg, n, at(10, 21, 22))
    step(cfg, n, at(11, 7, 0), busy=False)
    check("next morning: back", restored, [("晚班", "MAA")])

    print("\n[reachable or unknown: nothing]")
    skipped.clear()
    cfg, n = world(maa=fx.maa_dir(tmpdir(), yw=fx.YW_AFTERNOON)), _Notes()
    step(cfg, n, at(10, 8, 52))
    check("reachable: no pull, no alarm", (skipped, n.sent), ([], []))
    bad = fx.maa_dir(tmpdir())
    (bad / "resource" / "tasks" / "Stages" / "ZZ.json").write_text("{", encoding="utf-8")
    cfg, n = world(maa=bad), _Notes()
    step(cfg, n, at(10, 8, 52))
    check("unknown (a task file does not parse): no pull, no alarm", (skipped, n.sent), ([], []))
    cfg, n = world(fight=False), _Notes()
    step(cfg, n, at(10, 8, 52))
    check("Fight off: no pull, no alarm", (skipped, n.sent), ([], []))

    print("\n[the boot pass: the machine is up at 08:40 / 21:20 for 09:00 / 21:30]")
    skipped.clear()
    cfg, n = world(), _Notes()
    sg.step(cfg, n, at(10, 8, 46), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    check("boot at 08:46 (14 min before): a no is acted on at once", (skipped, len(n.sent)), ([("早班", "MAA")], 1))
    step(cfg, n, at(10, 8, 52))
    check("the tick in the last 10 minutes does not repeat it", (len(skipped), len(n.sent)), (1, 1))
    skipped.clear()
    cfg, n = world(stage="1-7"), _Notes()
    sg.step(cfg, n, at(10, 8, 46), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    check("boot: reachable, nothing done", (skipped, n.sent), ([], []))
    fx.automas_dir(cfg.automas_dir, stage="YW-4")      # changed after boot (e.g. from AUTO-MAS's own screen)
    step(cfg, n, at(10, 8, 52))
    check("a boot-time yes is not kept: the tick checks again and catches the change", skipped, [("早班", "MAA")])
    skipped.clear()
    cfg, n = world(), _Notes()
    sg.step(cfg, n, at(10, 9, 1), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    check("boot at 09:01 (after the due): too late for 早班, nothing", (skipped, n.sent), ([], []))

    print("\n[pull not possible]")
    cfg, n = world(), _Notes()
    step(cfg, n, at(10, 8, 52), skip=lambda q, s: None)
    check("MAA was not in the queue any more: still the one alarm (the next shift has the same stage)",
          [t for t, _b, _a in n.sent], [texts.stage_gate("早班")])
    check("... saying MAA was not in this shift", "本来就没有 MAA" in n.sent[0][1], True)
    check("... and nothing to put back", sg.skips(cfg.state_dir), [])
    cfg, n = world(), _Notes()

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
    cfg, n = world(), _Notes()
    step(cfg, n, at(10, 8, 52))
    check("no pull", skipped, [])
    check("one alarm, to the group, its own title", [(t, a) for t, _b, a in n.sent], [(texts.stage_gate_warn("早班"), True)])
    check("it says which stage, why, and that MAA still runs and will be refused",
          ("YW-4" in n.sent[0][1], "resource/tasks" in n.sent[0][1], "MAA 照跑" in n.sent[0][1]), (True, True, True))
    step(cfg, n, at(10, 8, 55))
    step(cfg, _Notes(), at(10, 8, 57))
    check("once per due, restarts included", (len(n.sent), skipped), (1, []))
    check("nothing to put back", sg.skips(cfg.state_dir), [])
    check("missed checks: not excused", (sg.excused(cfg.state_dir, "早班", at(10, 9, 0)),
                                          sg.settled_alone(cfg.state_dir, "早班", at(10, 9, 0))), (False, False))
    check("shutdown: no pulled shift", sg.recent_pulled(cfg.state_dir, at(10, 9, 10)), [])
    check("report: no 「没开跑」 section (MAA's own failure is reported as before)",
          sg.report_line(cfg.state_dir, "2026-10-10"), "")
    step(cfg, n, at(10, 21, 22))
    check("晚班: its own alarm", [t for t, _b, _a in n.sent][-1], texts.stage_gate_warn("晚班"))
    cfg, n = world(), _Notes()
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
    cfg, n = world(maa=bad), _Notes()
    sg.step(cfg, n, at(10, 8, 46), busy=lambda: False, skipper=skipper, restorer=restorer, lead_min=sg.BOOT_LEAD_MIN)
    step(cfg, n, at(10, 8, 51))
    step(cfg, n, at(10, 8, 52))
    step(cfg, _Notes(), at(10, 8, 55))             # a relay restart
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
    """
    import json
    import os
    import types
    from datetime import datetime

    from _parts import stagegate_fx; fx = stagegate_fx()

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import stagegate as sg

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

    print("\n[打开「拿掉 MAA」时：只有一个用户走不到，只报不拿（拿掉会连走得到的那个一起拿）]")
    pulled = []
    saved = sg.PULL_FROM_QUEUE
    sg.PULL_FROM_QUEUE = True
    try:
        cfg = types.SimpleNamespace(state_dir=tmpdir(), automas_dir=two_users(), maa_dir=MORNING)
        n = _Notes()
        sg.step(cfg, n, datetime(2026, 10, 10, 8, 52, tzinfo=SERVER_TZ), busy=lambda: False,
                skipper=lambda q, s: pulled.append((q, s)) or {"queue": q, "script": s}, restorer=lambda rec: True)
        check("没拿掉 MAA", pulled, [])
        check("报了一次「走不到、MAA 照跑」", [t for t, _b, _a in n.sent], [texts.stage_gate_warn("早班")])
        check("……里面点名用户", "arknights" in n.sent[0][1], True)
    finally:
        sg.PULL_FROM_QUEUE = saved


def _part_stage_set_refused():
    """Every way of setting MAA's stage refuses a stage MAA cannot navigate to, and says so."""
    import json
    import logging
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    _stub_pywin32()

    from _parts import stagegate_fx; fx = stagegate_fx()

    TMP = tmpdir()
    MORNING = fx.maa_dir(TMP / "maa-morning")
    AFTERNOON = fx.maa_dir(TMP / "maa-afternoon", yw=fx.YW_AFTERNOON)
    AUTOMAS = fx.automas_dir(TMP / "AUTO-MAS", stage="1-7")
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_AUTOMAS_DIR=str(AUTOMAS), ARK_MAA_DIR=str(MORNING),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="")
    from ark_relay.features import phone as phone_channel
    from ark_relay.features import commands, phone as inbox
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
        n, receipts = _Notes(), []
        phone_channel._phone_execute(commands.apply_command, n, logging.getLogger("ark.test_schedule"),
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
    """
    import importlib
    import json
    import os
    from datetime import datetime

    from _parts import stagegate_fx; fx = stagegate_fx()

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
    from ark_relay.features import commands
    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.features import shutdown
    from ark_relay.core.ledger import State
    from ark_relay.core.engine import Engine
    from ark_relay.core.notify import Notifier

    try:
        sg = importlib.import_module("ark_relay.features.stagegate")
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
    _rep = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "report.py").read_text(encoding="utf-8")
    check("the daily report template appends the gate's lines", "stagegate.report_line(eng.cfg.state_dir, day)" in _rep,
          True)


def _part_plan_after_accomplish():
    """「明日安排」 names every AUTO-MAS after-run action, not only "Shutdown"."""
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    REAL = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11"

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


def _part_plan_collect_days_master():
    """The plan's gathering-day line reads the master copy, not MaaEnd's own file."""
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

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-09-10" / "tasks" / "AutoCollect.json"
    AUTOMAS_FX = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11" / "config"

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


def _part_plan_queue_weekdays():
    """The relay's view of which scripts a queue runs follows AUTO-MAS v5.7's own rules."""
    #!/usr/bin/env python3

    import json
    import os
    import shutil
    from datetime import datetime

    FX = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11"
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
    from ark_relay.features import shutdown

    QC = AUTOMAS / "config" / "QueueConfig.json"
    PRISTINE = QC.read_text(encoding="utf-8")
    MORNING = "cc32e55a-55d0-408d-980d-642e66d111ae"       # 早班 09:00: MAA, OK-WW, MaaEnd
    EVENING = "6f09a385-b0ae-4ff6-9890-50339bdaddeb"       # 晚班 21:30: MAA
    MAAEND_ITEM = "572b030a-6eb2-4122-954e-07b3010c8d88"
    ALL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def at(day: int, hh: int, mm: int) -> datetime:
        return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)   # 10-12 is a Monday

    edit = _doc_editor(PRISTINE, QC)

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


def _part_plan_silent():
    """Tomorrow's plan says when a source it needs could not be read (audit
docs/SILENT-FAILURES-AUDIT.md, plan.py rows).
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
    broken = mock.patch("ark_relay.features.weeklyboss.WeeklyBossGate.settings", side_effect=OSError("state.json locked"))
    with broken:
        got = plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
        check("unknown -> says it cannot tell, not 「明天会打」", got,
              "附加 周本 战歌重奏第 2 个（90 级），本周打没打满读不到")
        check("unknown -> one WARNING", len(grab.warnings()), 1)
        plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
        check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.weeklyboss.WeeklyBossGate.settings",
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
    with mock.patch("ark_relay.features.annihilation.WeeklyGate.settings", side_effect=RuntimeError("gate broke")):
        check("unreadable -> unknown (None), not reported as done or as running",
              plan._annihilation_done_tomorrow(None), None)
        w = grab.warnings()
        check("unreadable -> one WARNING with the traceback", (len(w), bool(w and w[0].exc_info)), (1, True))
        plan._annihilation_done_tomorrow(None)
        check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.annihilation.WeeklyGate.settings", return_value={"本周已完成": False, "当前": ""}):
        plan._annihilation_done_tomorrow(None)
        check("readable -> no WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.annihilation.WeeklyGate.settings", side_effect=RuntimeError("gate broke")):
        plan._annihilation_done_tomorrow(None)
        check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)

    print("[row 5: maintenance_lines unexpected error]")
    fresh()
    import datetime as _dt
    day = _dt.date(2026, 10, 11)
    with mock.patch("ark_relay.features.maintenance.today", side_effect=KeyError("window")):
        check("error -> no line (as before)", plan.maintenance_lines(day), [])
        w = grab.warnings()
        check("error -> one WARNING with the traceback", (len(w), bool(w and w[0].exc_info)), (1, True))
        plan.maintenance_lines(day)
        check("same condition again -> no second WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.maintenance.today", return_value={}):
        plan.maintenance_lines(day)
        check("works -> no WARNING", len(grab.warnings()), 0)
    with mock.patch("ark_relay.features.maintenance.today", side_effect=KeyError("window")):
        plan.maintenance_lines(day)
        check("broken again after it worked -> WARNING again", len(grab.warnings()), 1)


def _part_plan_stage_modes():
    """「明日安排」 shows MAA's stages the way AUTO-MAS v5.7 hands them to MAA."""
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    REAL = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11"
    PLAN_UID = "c88cfe9e-6617-4fb8-9225-183ca571e3ae"

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


def _part_plan_startup_mode():
    """queue_rows' 「开机跑」 comes from AUTO-MAS v5.7's StartUpMode."""
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan

    REAL = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11"

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


def _part_queue_apply_backend():
    """A queue switch must reach the running AUTO-MAS, not just the file."""
    import json
    import urllib.error
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import commands
    from ark_relay.features import modes
    from ark_relay.features import queues
    from ark_relay.core import plan as _plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore

    def automas_dir():
        d = tmpdir()
        (d / "config").mkdir()
        (d / "config" / "QueueConfig.json").write_text(json.dumps({
            "instances": [{"uid": "q1"}, {"uid": "q2"}],
            "q1": {"Info": {"Name": "早班", "TimeEnabled": True}},
            "q2": {"Info": {"Name": "晚班", "TimeEnabled": True}},
        }, ensure_ascii=False), encoding="utf-8")
        return d

    def file_enabled(d, qid):
        return json.loads((d / "config" / "QueueConfig.json").read_text(encoding="utf-8"))[qid]["Info"]["TimeEnabled"]

    class Backend:
        """Fake AUTO-MAS backend. `sticks=False` accepts updates but never applies them."""
        def __init__(self, sticks=True):
            self.sticks = sticks
            self.calls = []
            self.mem = {"q1": {"Info": {"Name": "早班", "TimeEnabled": True}},
                        "q2": {"Info": {"Name": "晚班", "TimeEnabled": True}}}

        def __call__(self, path, body=None, timeout=20):
            self.calls.append((path, body))
            if path == "/api/queue/get":
                return {"code": 200, "data": json.loads(json.dumps(self.mem))}
            if path == "/api/queue/update":
                if self.sticks:
                    self.mem[body["queueId"]]["Info"].update(body["data"]["Info"])
                return {"code": 200}
            raise AssertionError(path)

    def down(path, body=None, timeout=20):
        raise ConnectionRefusedError("backend down")

    real_mas = commands._mas
    try:
        print("\n[backend up] the switch goes through /api/queue/update and is read back")
        d = automas_dir()
        be = Backend()
        commands._mas = be
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("reports success", ok, True)
        check("says it was read back", "调度程序已确认" in msg, True)
        check("update call body", ("/api/queue/update", {"queueId": "q1", "data": {"Info": {"TimeEnabled": False}}}) in be.calls, True)
        check("backend memory now off", be.mem["q1"]["Info"]["TimeEnabled"], False)
        check("file left alone (AUTO-MAS owns it while up)", file_enabled(d, "q1"), True)
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("same value again: no second update", (ok, sum(c[0] == "/api/queue/update" for c in be.calls)), (True, 1))
        ok, msg = queues.apply(d, "新队列", enabled=True)
        check("old name maps to 早班 and re-enables", (ok, be.mem["q1"]["Info"]["TimeEnabled"]), (True, True))
        ok, msg = queues.apply(d, "不存在", enabled=False)
        check("unknown queue fails and lists what exists", (ok, "早班" in msg and "晚班" in msg), (False, True))
        ok, msg = queues.apply(d, "早班", enabled="false")
        check("non-bool rejected before any backend write", (ok, sum(c[0] == "/api/queue/update" for c in be.calls)), (False, 2))

        print("\n[backend up, update does not stick] reported as a failure")
        d = automas_dir()
        be = Backend(sticks=False)
        commands._mas = be
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("reports failure", ok, False)
        check("says the read-back value", "没生效" in msg and "仍是开启" in msg, True)

        print("\n[backend down] falls back to editing the file")
        d = automas_dir()
        commands._mas = down
        ok, msg = queues.apply(d, "晚班", enabled=False)
        check("reports success", ok, True)
        check("file now off", file_enabled(d, "q2"), False)

        # docs/SILENT-FAILURES-AUDIT.md queues.py:127 - only a refused connection is
        # "down". A live AUTO-MAS that times out would overwrite a file edit from memory.
        print("\n[backend answers slowly or with an error] not edited, reported as a failure")
        for label, exc in (("timeout", TimeoutError("timed out")),
                           ("HTTP 500", urllib.error.HTTPError("http://x", 500, "err", {}, None))):
            def broken(path, body=None, timeout=20, exc=exc):
                raise exc
            d = automas_dir()
            commands._mas = broken
            ok, msg = queues.apply(d, "早班", enabled=False)
            check(f"{label}: reports failure", ok, False)
            check(f"{label}: says the scheduler did not answer", "调度程序没应答" in msg, True)
            check(f"{label}: file left alone", file_enabled(d, "q1"), True)
        d = automas_dir()
        commands._mas = lambda path, body=None, timeout=20: {"code": 200, "data": ["not", "a", "dict"]}
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("odd answer: reports failure, file left alone", (ok, file_enabled(d, "q1")), (False, True))
        d = automas_dir()
        commands._mas = lambda path, body=None, timeout=20: (_ for _ in ()).throw(
            urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")))
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("refused as urllib raises it: still the file path", (ok, file_enabled(d, "q1")), (True, False))

        print("\n[skip engage] a read-back mismatch drops the flag and says 跳过失败")
        S = tmpdir() / "state"; S.mkdir(parents=True)
        d = automas_dir()
        be = Backend(sticks=False)
        commands._mas = be
        real_sched = _plan.schedule
        _plan.schedule = lambda _d: [{"name": "早班", "times": ["09:00"]}, {"name": "晚班", "times": ["21:30"]}]
        try:
            T0 = datetime(2026, 9, 30, 8, 51, tzinfo=SERVER_TZ)
            day = T0.strftime("%Y-%m-%d")
            modes.add_day_queue(S, day, "早班")
            msgs = modes.process_skip(S, d, T0)
            check("message says 跳过失败", any("跳过「早班」失败" in m for m in msgs), True)
            check("never claims 已临时停用", any("已临时停用" in m for m in msgs), False)
            check("flag dropped: the page shows the queue running today",
                  StateStore(S).get("queues", f"skip_day:{day}"), None)
            check("no restore marker left behind", StateStore(S).get("queues", "skip_restore"), None)
            be.sticks = True
            modes.add_day_queue(S, day, "早班")      # the operator presses the switch again
            msgs = modes.process_skip(S, d, T0)
            check("retry succeeds: 已临时停用 only now", any("已临时停用" in m for m in msgs), True)
            check("backend memory off", be.mem["q1"]["Info"]["TimeEnabled"], False)
            msgs = modes.process_skip(S, d, datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ))
            check("restore goes through the backend too", be.mem["q1"]["Info"]["TimeEnabled"], True)
            check("marker cleared", StateStore(S).get("queues", "skip_restore"), None)
        finally:
            _plan.schedule = real_sched
    finally:
        commands._mas = real_mas


def _part_queue_apply_runnow():
    """队列启停和「现在跑一趟」不能一调用就崩。"""
    import json
    import os
    import pathlib

    os.environ["ARK_STATE_DIR"] = str(tmpdir() / "state")
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

    from ark_relay.features import commands
    from ark_relay.features import queues
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    # ---- queues.apply：真跑一遍，改完读回 ----
    tmp = tmpdir()
    (tmp / "config").mkdir()
    (tmp / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {"Info": {"Name": "早班", "TimeEnabled": True},
               "SubConfigsInfo": {"TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                  "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}},
    }, ensure_ascii=False), encoding="utf-8")
    (tmp / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"}, "SubConfigsInfo": {"UserData": {}}},
    }), encoding="utf-8")

    try:
        ok, msg = queues.apply(tmp, "早班", enabled=False)
    except Exception as exc:  # noqa: BLE001
        fails.append(f"queues.apply 抛异常：{type(exc).__name__}: {exc}")
    else:
        if not ok:
            fails.append(f"queues.apply 应成功：{msg}")
        got = json.loads((tmp / "config" / "QueueConfig.json").read_text(encoding="utf-8"))
        if got["q1"]["Info"]["TimeEnabled"] is not False:
            fails.append("queues.apply 没把定时关掉")
        # 旧名字要能认（names.canonical 的用武之地）
        ok2, msg2 = queues.apply(tmp, "新队列", enabled=True)
        if not ok2 or "早班" not in msg2:
            fails.append(f"旧名「新队列」没被换成早班：{ok2} {msg2}")
        # 不存在的队列：报错里要列出现有的
        ok3, msg3 = queues.apply(tmp, "不存在", enabled=True)
        if ok3 or "早班" not in msg3:
            fails.append(f"不存在的队列应失败并列出现有队列：{msg3}")

    # ---- commands._run_now：把后端接口换成假的 ----
    calls = []
    def fake_mas(path, body=None, timeout=20):
        calls.append((path, body))
        if path == "/api/queue/get":
            return {"data": {"qid1": {"Info": {"Name": "早班"}}, "qid2": {"Info": {"Name": "晚班"}}}}
        if path == "/api/dispatch/start":
            return {"status": "success"}
        raise AssertionError(path)
    commands._mas = fake_mas
    try:
        ok, msg = commands._run_now("Evening-MAA")   # 旧名
    except Exception as exc:  # noqa: BLE001
        fails.append(f"_run_now 抛异常：{type(exc).__name__}: {exc}")
    else:
        if not ok or "晚班" not in msg:
            fails.append(f"_run_now 旧名应映射到晚班并成功：{ok} {msg}")
        if ("/api/dispatch/start", {"taskId": "qid2", "mode": "AutoProxy"}) not in calls:
            fails.append(f"没有派发晚班：{calls}")
        ok4, msg4 = commands._run_now("没有的队列")
        if ok4 or "早班" not in msg4 or "晚班" not in msg4:
            fails.append(f"不存在的队列应失败并列出现有队列：{msg4}")


def _part_queue_names():
    """队列改名「早班/晚班」后，旧名字（新队列 / Evening-MAA）仍然被认。"""
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    STATE = tmpdir()
    os.environ["ARK_STATE_DIR"] = str(STATE)
    from ark_relay.features import commands
    from ark_relay.core import config as names
    from ark_relay.core.statestore import StateStore

    print("[canonical]")
    check("新队列→早班", names.canonical("新队列"), "早班")
    check("Evening-MAA→晚班", names.canonical("Evening-MAA"), "晚班")
    check("现名原样", names.canonical("早班"), "早班")
    check("带空白也认", names.canonical(" 新队列 "), "早班")
    check("未知名原样", names.canonical("别的"), "别的")
    check("空→空", names.canonical(""), "")

    print("[skip_today 落盘的是现名]")
    ok, msg = commands._skip_today("Evening-MAA")
    marks = {k: v for k, v in StateStore(STATE).section("queues").items() if k.startswith("skip_day:")}
    check("成功", ok, True)
    check("标记内容", list(marks.values()), ["晚班"])
    check("提示用现名", "「晚班」" in msg, True)

    print("[默认队列是早班]")
    # Clear the 晚班 skip above so the default queue is the only one flagged.
    for k in marks:
        StateStore(STATE).pop("queues", k)
    ok, msg = commands.apply_command({"action": "skip_today"})
    check("默认早班", any(v == "早班" for k, v in StateStore(STATE).section("queues").items()
                        if k.startswith("skip_day:")), True)


def _part_queue_rows_times():
    """queue_rows gives each queue its start times (「时刻」), also while its timer is off."""
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan

    REAL = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11"

    print("[real 10-11 config]")
    rows = plan.queue_rows(REAL)
    want = {q["name"]: q["times"] for q in plan._queues(REAL / "config")}
    require("each queue has its times, as the plan reads them",
            all(r.get("时刻") == want[r["名"]] for r in rows) and all(r.get("时刻") for r in rows), repr(rows))

    print("[a queue skipped today: timer off, times kept]")
    root = tmpdir()
    shutil.copytree(REAL, root / "a")
    qf = root / "a" / "config" / "QueueConfig.json"
    d = json.loads(qf.read_text(encoding="utf-8"))
    uid = d["instances"][0]["uid"]
    d[uid]["Info"]["TimeEnabled"] = False
    qf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    off = plan.queue_rows(root / "a")
    require("定时 off but 时刻 still there", off[0]["定时"] is False and off[0].get("时刻") == rows[0].get("时刻"), repr(off[0]))


def _part_queue_skip_holders():
    """Today-only queue skips held by two sources, across days, and over repeated items."""
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import commands
    from ark_relay.features import queues
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import gameupdate

    ALL = list(commands.WEEKDAYS)

    Clock = _pinned_clock()

    commands.datetime = Clock
    queues.datetime = Clock
    D = datetime(2026, 10, 12, 10, 0, tzinfo=SERVER_TZ)          # a Monday
    D1 = D + timedelta(days=1)
    D2 = D + timedelta(days=2)
    WD = commands.WEEKDAYS

    def day(t):
        return t.strftime("%Y-%m-%d")

    Backend = _queue_backend(ALL)

    run = _mas_runner(commands, Clock)

    automas = tmpdir()

    print("[fix 1: a queue command replayed at the next boot keeps today's skip]")
    state, be = tmpdir(), Backend()
    run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D)
    check("day D: MaaEnd loses Monday", WD[D.weekday()] in be.days("i2"), False)
    # Boot on D+1: the mailbox replays the same command before boot_check's restore.
    ok, _msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D1.replace(hour=8))
    check("the replay succeeds", ok, True)
    rec = next(r for r in gameupdate.skips(state) if r["script"] == "MaaEnd")
    check("the record moves to D+1 and keeps the true original days", (rec["day"], rec["days"]), (day(D1), ALL))
    done = run(be, lambda: (gameupdate.restore_skips(state, before_day=day(D1), manual_too=False)
                            + gameupdate.restore_skips(state, before_day=day(D1))), D1.replace(hour=8))
    check("the boot restore of earlier days leaves it", done, [])
    check("MaaEnd still does not run on D+1", WD[D1.weekday()] in be.days("i2"), False)
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=day(D2)), D2.replace(hour=8))
    check("D+2's restore gives every weekday back (none lost for good)", (be.days("i2"), be.days("i3")), (ALL, ALL))
    check("nothing left recorded", gameupdate.skips(state), [])

    print("\n[fix 4: a queue command never undoes a maintenance skip]")
    state, be = tmpdir(), Backend()
    r = run(be, lambda: commands.skip_script_in_queue("早班", "MaaEnd"), D)
    r["why"] = "维护"
    gameupdate._add_skip(state, r)
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state), D)
    check("listing MaaEnd succeeds", ok, True)
    check("MaaEnd stays out today (maintenance)", WD[D.weekday()] in be.days("i2"), False)
    check("the maintenance record is kept as the update's",
          [gameupdate._sources(r) for r in gameupdate.skips(state) if r["script"] == "MaaEnd"], [{"update"}])
    check("the receipt does not claim it was put back", "恢复 MaaEnd" in msg, False)
    check("…and says why MaaEnd will not run", "MaaEnd 今天为游戏更新先跳过" in msg, True)

    print("\n[fix 4: a queue skip of an item the update holds survives the update's put-back]")
    state, be = tmpdir(), Backend()
    gameupdate._add_skip(state, run(be, lambda: commands.skip_script_in_queue("早班", "OK-WW"), D))
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state), D)
    check("skipping OK-WW is reported", (ok, "今天跳过 OK-WW" in msg), (True, True))
    check("one record, held by both", [gameupdate._sources(r) for r in gameupdate.skips(state)], [{"queue", "update"}])
    check("no re-run asked for (he said skip it)", gameupdate.needs_rerun(state, D, "OK-WW"), False)
    done = run(be, lambda: gameupdate.restore_skips(state, manual_too=False), D)
    check("the update's put-back leaves OK-WW out today", (done, WD[D.weekday()] in be.days("i3")), ([], False))
    check("the record stays, held by the queue command", [gameupdate._sources(r) for r in gameupdate.skips(state)],
          [{"queue"}])
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=day(D1)), D1)
    check("the next day's restore gives it back", (done, be.days("i3")), (["OK-WW→「早班」"], ALL))

    print("\n[fix 5: a script in the queue twice: both items skip, each recorded]")
    state = tmpdir()
    be = Backend({"i4": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}})
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "OK-WW"], state_dir=state), D)
    check("succeeds, one line for MaaEnd", (ok, msg.count("今天跳过 MaaEnd")), (True, 1))
    check("both MaaEnd items lose today", (WD[D.weekday()] in be.days("i2"), WD[D.weekday()] in be.days("i4")),
          (False, False))
    check("one record per item", sorted(r["queueItemId"] for r in gameupdate.skips(state)), ["i2", "i4"])
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=day(D1)), D1)
    check("both get their days back the next day", (len(done), be.days("i2"), be.days("i4")), (2, ALL, ALL))
    be = Backend({"i4": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}})
    recs = run(be, lambda: gameupdate._skip_default("早班", "MaaEnd"), D)
    check("the maintenance skip covers both items too", sorted(r["queueItemId"] for r in recs), ["i2", "i4"])


def _part_queue_skip_partial():
    """A today-only queue skip that fails part-way keeps its undo record."""
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import gameupdate
    from ark_relay.features import commands
    from ark_relay.features import queues

    ALL = list(commands.WEEKDAYS)

    Clock = _pinned_clock()

    commands.datetime = Clock
    queues.datetime = Clock
    D = datetime(2026, 10, 12, 10, 0, tzinfo=SERVER_TZ)          # a Monday
    D1 = D + timedelta(days=1)
    MON = commands.WEEKDAYS[D.weekday()]

    Backend = _queue_backend(ALL, okww=False)

    run = _mas_runner(commands, Clock)

    def caught(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            return exc
        return None

    automas = tmpdir()

    print("[one item: the write lands, the read-back times out]")
    be = Backend(fail_get_after_update=1)
    exc = run(be, lambda: caught(lambda: commands.skip_script_in_queue("早班", "MaaEnd")), D)
    check("the write landed (Monday removed)", MON in be.days("i2"), False)
    check("the error carries the undo record with the original days",
          [(r["queueItemId"], r["days"]) for r in getattr(exc, "recs", [])], [("i2", ALL)])

    print("\n[two items of one script: the second item's reply is lost]")
    be = Backend({"i3": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}}, fail_update=2)
    exc = run(be, lambda: caught(lambda: commands.skip_script_all_items("早班", "MaaEnd")), D)
    check("both writes landed", (MON in be.days("i2"), MON in be.days("i3")), (False, False))
    check("the error carries both records (the first is not thrown away)",
          sorted(r["queueItemId"] for r in getattr(exc, "recs", [])), ["i2", "i3"])

    print("\n[queues.apply keeps the records of a skip that failed part-way]")
    state = tmpdir()
    be = Backend({"i3": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}}, fail_get_after_update=2)
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D)
    check("the reply says it failed", (ok, "失败" in msg), (False, True))
    kept = gameupdate.skips(state)
    check("both items' records are kept, held by the queue command",
          sorted((r["queueItemId"], r["days"], tuple(gameupdate._sources(r))) for r in kept),
          [("i2", ALL, ("queue",)), ("i3", ALL, ("queue",))])
    run(be, lambda: gameupdate.restore_skips(state, before_day=D1.strftime("%Y-%m-%d")), D1)
    check("the next day's restore gives Monday back to both", (be.days("i2"), be.days("i3")), (ALL, ALL))

    print("\n[gameupdate's maintenance skip keeps the record of a skip that failed part-way]")
    import ark_relay.core.plan as plan

    state = tmpdir()
    be = Backend(fail_get_after_update=1)

    class Cfg:
        pass

    cfg = Cfg()
    cfg.state_dir, cfg.automas_dir, cfg.maa_dir, cfg.maaend_dir, cfg.okww_dir = state, state, None, None, None
    plan_backup = plan.schedule
    plan.schedule = lambda d: [{"name": "早班", "times": ["11:00"], "items": ["s1"]}]
    src = {"终末地": lambda n: (D.replace(hour=10), D.replace(hour=12), "官方公告")}
    try:
        notes, probs = run(be, lambda: gameupdate.boot_check(cfg, budget_s=0, now=D, maint_sources=src,
                                                             hint=lambda n: ""), D)
    finally:
        plan.schedule = plan_backup
    check("the failure is reported", any("跳过 MaaEnd 失败" in p for p in probs), True)
    check("the record is kept with the original days",
          [(r["queueItemId"], r["days"], r.get("why")) for r in gameupdate.skips(state)], [("i2", ALL, "官方公告")])


def _part_queue_skip_partial_receipt():
    """A queue's today-only script list that fails part-way names what it had already changed."""
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import commands
    from ark_relay.features import queues
    from ark_relay.core.config import SERVER_TZ

    ALL = list(commands.WEEKDAYS)

    Clock = _pinned_clock()

    commands.datetime = Clock
    queues.datetime = Clock
    D = datetime(2026, 10, 12, 10, 0, tzinfo=SERVER_TZ)          # a Monday
    WD = commands.WEEKDAYS

    def day(t):
        return t.strftime("%Y-%m-%d")

    Backend = _queue_backend(ALL)

    run = _mas_runner(commands, Clock)

    automas = tmpdir()

    class Failing(Backend):
        fail_item = ""

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/item/update" and body["queueItemId"] == self.fail_item:
                raise ConnectionResetError("调度程序没应答")
            return super().__call__(path, body, timeout)

    print("[restore MaaEnd lands, then skipping OK-WW fails]")
    state, be = tmpdir(), Failing()
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "OK-WW"], state_dir=state), D)
    check("setup: MaaEnd skipped today", (ok, WD[D.weekday()] in be.days("i2")), (True, False))
    be.fail_item = "i3"
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state), D)
    check("reported as failed", ok, False)
    check("MaaEnd really was put back in AUTO-MAS", WD[D.weekday()] in be.days("i2"), True)
    check("the receipt names the failing step", "跳过 OK-WW 失败" in msg, True)
    check("the receipt also says MaaEnd was already put back", "这之前已经改了：恢复 MaaEnd" in msg, True)

    print("[nothing landed before the failure -> the receipt is the error alone]")
    state, be = tmpdir(), Failing()
    be.fail_item = "i2"
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D)
    check("failed, no 「这之前已经改了」", (ok, "这之前已经改了" in msg), (False, False))


def _part_queue_skip_scripts():
    """A queue command's script list skips the rest for today, through Schedule.Days."""
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import commands
    from ark_relay.features import queues
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import gameupdate

    ALL = list(commands.WEEKDAYS)
    NOW = datetime.now(tz=SERVER_TZ)
    TODAY = commands.WEEKDAYS[NOW.weekday()]
    NOT_TODAY = [d for d in ALL if d != TODAY]

    class Backend:
        def __init__(self, up=True):
            self.up = up
            self.calls = []
            self.scripts = {"s-maa": {"Info": {"Name": "MAA"}}, "s-end": {"Info": {"Name": "MaaEnd"}},
                            "s-ww": {"Info": {"Name": "OK-WW"}}}
            self.queues = {"q1": {"Info": {"Name": "早班"}}}
            self.items = {"i1": {"Info": {"ScriptId": "s-maa"}, "Schedule": {"Days": list(ALL)}},
                          "i2": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}},
                          "i3": {"Info": {"ScriptId": "s-ww"}, "Schedule": {"Days": list(ALL)}}}

        def __call__(self, path, body=None, timeout=20):
            self.calls.append(path)
            if not self.up:
                raise ConnectionRefusedError(61, "Connection refused")
            if path == "/api/queue/get":
                return {"data": self.queues}
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/queue/item/get":
                return {"index": [{"uid": u} for u in self.items], "data": json.loads(json.dumps(self.items))}
            if path == "/api/queue/item/update":
                for sec, val in body["data"].items():
                    self.items[body["queueItemId"]].setdefault(sec, {}).update(val)
                return {"status": "success"}
            raise AssertionError(f"unexpected call {path}")

        def days(self):
            return {u: it["Schedule"]["Days"] for u, it in self.items.items()}

    real = commands._mas

    def run(be, fn):
        commands._mas = be
        try:
            return fn()
        finally:
            commands._mas = real

    automas = tmpdir()
    state = tmpdir()

    print("[run only MAA today: the other two skip today, nothing deleted]")
    be = Backend()
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["maa"], state_dir=state))
    check("succeeds", ok, True)
    check("the receipt names both skips", ("今天跳过 MaaEnd" in msg, "今天跳过 OK-WW" in msg), (True, True))
    check("MAA keeps every day, the others lose today", be.days(),
          {"i1": ALL, "i2": NOT_TODAY, "i3": NOT_TODAY})
    check("no item is deleted or added", [c for c in be.calls if c.endswith(("delete", "add", "order"))], [])
    check("no removed-*.json next to the config", list(automas.glob("**/removed-*.json")), [])
    recs = gameupdate.skips(state)
    check("two records, source queue, original days kept",
          sorted((r["script"], r["source"], r["days"] == ALL) for r in recs),
          [("MaaEnd", "queue", True), ("OK-WW", "queue", True)])

    print("\n[the game-update side leaves a queue command's skip alone]")
    check("needs_rerun ignores it", gameupdate.needs_rerun(state, NOW, "MaaEnd"), False)
    done = gameupdate.restore_skips(state, restorer=lambda r: True, manual_too=False)
    check("restore after the re-run keeps it", (done, len(gameupdate.skips(state))), ([], 2))
    done = gameupdate.restore_skips(state, restorer=lambda r: True, before_day=NOW.strftime("%Y-%m-%d"))
    check("the boot restore on the same day keeps it too", (done, len(gameupdate.skips(state))), ([], 2))

    print("\n[same command again: nothing more to do]")
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state))
    check("already so", (ok, msg), (True, "已经是这个状态，无需改动"))

    print("\n[list MaaEnd again the same day: its skip is undone, the record dropped]")
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state))
    check("succeeds and says so", (ok, "恢复 MaaEnd" in msg), (True, True))
    check("MaaEnd has today back", be.days()["i2"], ALL)
    check("only OK-WW is still recorded", [r["script"] for r in gameupdate.skips(state)], ["OK-WW"])

    print("\n[next morning's boot restore gives OK-WW its day back]")
    tomorrow = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=tomorrow))
    check("restored", (done, be.days()["i3"], gameupdate.skips(state)), (["OK-WW→「早班」"], ALL, []))

    print("\n[refusals]")
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["Nope"], state_dir=state))
    check("an unknown script is refused and named", (ok, "Nope" in msg), (False, True))
    ok, msg = run(be, lambda: queues.apply(automas, "晚班", scripts=["MAA"], state_dir=state))
    check("an unknown queue is refused", (ok, "晚班" in msg), (False, True))
    down = Backend(up=False)
    ok, msg = run(down, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state))
    check("backend down: refused, no file edit", (ok, "调度程序没应答" in msg), (False, True))
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"]))
    check("no state dir: refused before touching anything", (ok, be.days()["i2"]), (False, ALL))


def _part_dayroll_skips():
    """A machine left on past midnight puts back the queue-command skips of the day before."""
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    _stub_pywin32()

    from ark_relay.features import automas_keeper as day_roll
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import gameupdate
    from ark_relay.features import commands

    class Log:
        def __init__(self): self.lines = []
        def info(self, msg, *a, **k): self.lines.append(msg % a)
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): self.lines.append("exception")

    D = datetime(2026, 10, 12, 23, 0, tzinfo=SERVER_TZ)
    state = tmpdir()

    def rec(script, item, **kw):
        return dict({"queue": "早班", "queueId": "q1", "queueItemId": item, "script": script, "scriptId": "s-" + item,
                     "position": 0, "day": "2026-10-12", "days": ["Monday"]}, **kw)

    gameupdate._add_skip(state, rec("MaaEnd", "i2", source="queue"))       # a queue command's skip
    gameupdate._add_skip(state, rec("OK-WW", "i3", why="维护"))           # the update's
    gameupdate._add_skip(state, rec("MAA", "i1", why="维护"))
    gameupdate._add_skip(state, rec("MAA", "i1", source="queue"))          # held by both

    put = []
    ok_restore = [False]

    def restorer(r):
        put.append(r["script"])
        return ok_restore[0]

    commands.restore_script_in_queue = restorer
    cfg = types.SimpleNamespace(state_dir=state)
    log = Log()
    roll = day_roll._DayRoll(cfg, log, now=D)

    print("[the loop wakes just past midnight]")
    check("23:59:30 with an hour to sleep: 31 s", roll.cap_wait(3600, D.replace(minute=59, second=30)), 31.0)
    check("a nearer alarm stays", roll.cap_wait(10, D.replace(minute=59, second=30)), 10)

    print("\n[before midnight nothing is put back]")
    check("23:59:59, first check after start (today's records only)",
          (roll.check(D.replace(minute=59, second=59)), put, roll.pending), ([], [], False))

    print("\n[a relay restart (not a reboot) after midnight puts back the day before's at once]")
    fresh = day_roll._DayRoll(cfg, Log(), now=D + timedelta(hours=1))
    ok_restore[0] = True
    check("first check", fresh.check(D + timedelta(hours=1)), ["MaaEnd→「早班」"])
    gameupdate._add_skip(state, rec("MaaEnd", "i2", source="queue"))       # same state again for the rest
    ok_restore[0] = False
    put.clear()
    for r in gameupdate.skips(state):
        if r["script"] == "MAA":
            gameupdate._add_skip(state, dict(r, source="queue", sources=["queue"]))

    print("\n[past midnight: AUTO-MAS not answering, kept and tried again]")
    n1 = D + timedelta(hours=1, seconds=1)
    check("first try fails", (roll.check(n1), put, roll.pending), ([], ["MaaEnd"], True))
    check("…and the loop wakes in 2 minutes to try again, not at the next alarm (清单-1108 A-04)",
          roll.cap_wait(3600, n1), day_roll._DayRoll.RETRY_S)
    ok_restore[0] = True
    put.clear()
    check("the next wake puts it back", (roll.check(n1 + timedelta(minutes=5)), put),
          (["MaaEnd→「早班」"], ["MaaEnd"]))
    check("…and logs it", any("过了零点" in line for line in log.lines), True)

    print("\n[every round hands the loop's moment to the log back-fill, which starts once per start and per day]")
    from ark_relay.features import evidence as error_evidence
    calls = []
    real_step = error_evidence.backfill_step
    error_evidence.backfill_step = lambda c, now=None, **kw: calls.append((c is cfg, now)) or True
    try:
        at = D + timedelta(hours=2)
        roll.check(at)
        roll.check(at + timedelta(minutes=1))
        check("each check calls the step with this relay's config and the round's moment",
              calls, [(True, at), (True, at + timedelta(minutes=1))])
        error_evidence.backfill_step = lambda c, now=None, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        said = log.lines.count("exception")
        check("a step that breaks does not break the midnight put-back", roll.check(at + timedelta(minutes=2)), [])
        check("……and it is said (one log.exception)", log.lines.count("exception") - said, 1)
    finally:
        error_evidence.backfill_step = real_step
        error_evidence._backfill.update(day=None, thread=None)
    left = sorted((r["script"], tuple(sorted(gameupdate._sources(r)))) for r in gameupdate.skips(state))
    check("the update's holds stay (MAA keeps the update's, loses the queue's)", left,
          [("MAA", ("update",)), ("OK-WW", ("update",))])
    put.clear()
    check("nothing more the same day", (roll.check(n1 + timedelta(hours=3)), put, roll.pending), ([], [], False))
    check("nothing open: no 2-minute wakes", roll.cap_wait(3600, n1 + timedelta(hours=3)), 3600)


def _part_due_weekdays_everywhere():
    """Every place that reads a queue's times asks plan.runs_at whether the time runs anything
that day (audit 10-13: raw queue times were read without the weekday rule in five places,
and the daily report's 「明日安排」 listed skipped items).
    """
    #!/usr/bin/env python3

    import os
    import shutil
    from datetime import datetime
    from unittest import mock

    FX = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11"
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
    from ark_relay.features import gameupdate
    from ark_relay.features import preupdate
    from ark_relay.features import runwatch
    from ark_relay.features import shutdown

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    QC = AUTOMAS / "config" / "QueueConfig.json"
    PRISTINE = QC.read_text(encoding="utf-8")
    MORNING = "cc32e55a-55d0-408d-980d-642e66d111ae"       # 早班 09:00: MAA, OK-WW, MaaEnd
    EVENING = "6f09a385-b0ae-4ff6-9890-50339bdaddeb"       # 晚班 21:30: MAA
    MAAEND_ITEM = "572b030a-6eb2-4122-954e-07b3010c8d88"
    ALL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def at(day: int, hh: int, mm: int) -> datetime:
        return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)   # 10-12 is a Monday

    edit = _doc_editor(PRISTINE, QC)

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


def _part_shift_clock_after_retry():
    """A script that timed out and was retried by AUTO-MAS restarts the shift's clock (ledger #138).
    """
    import json
    import types
    from datetime import datetime, timedelta
    from unittest import mock

    TMP = tmpdir()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import runwatch
    from ark_relay.features import shutdown

    class Store:
        def __init__(self, marks):
            self.marks = marks

        def get(self, ns, key):
            return self.marks.get(key) if ns == "marks" else None

    def eng_with(marks):
        return types.SimpleNamespace(state=types.SimpleNamespace(store=Store(marks)))

    def t(h, m, s=0, day=5):
        return datetime(2026, 11, day, h, m, s, tzinfo=SERVER_TZ)

    due = t(9, 0)
    LIMIT = 87          # 「近 7 天最长 87 分钟跑完」 in the 10:57 alarm
    DAY = "alerted:2026-11-05"

    print("[retry_clock]")
    check("no marks: nothing restarts the clock", runwatch.retry_clock(eng_with({}), due, LIMIT), None)
    check("no state at all (bare engine): None", runwatch.retry_clock(types.SimpleNamespace(), due, LIMIT), None)
    e = eng_with({DAY: ["超时|MAA|09:48:12", "队列超时|早班|09:00"]})
    check("MAA timed out at 09:48 and was retried: from 09:48", runwatch.retry_clock(e, due, LIMIT), t(9, 48, 12))
    e = eng_with({DAY: ["超时|MAA|09:48:12", "超时|MAA|10:30:00"]})
    check("two timeouts in the run: the later one", runwatch.retry_clock(e, due, LIMIT), t(10, 30))
    e = eng_with({DAY: ["超时|MAA|08:59:59"]})
    check("a timeout before the shift's time does not count", runwatch.retry_clock(e, due, LIMIT), None)
    e = eng_with({DAY: ["超时|MaaEnd|10:57:01"]})
    check("a timeout after the planned end (10:57) moves nothing", runwatch.retry_clock(e, due, LIMIT), None)
    e = eng_with({DAY: ["超时|MAA|bad", "nonsense"]})
    check("malformed marks are skipped", runwatch.retry_clock(e, due, LIMIT), None)
    eve = t(21, 20)
    e = eng_with({DAY: [], "alerted:2026-11-06": ["超时|OK-WW|00:10:00"]})
    check("an evening shift's timeout after midnight is read from the next day",
          runwatch.retry_clock(e, eve, 180), t(0, 10, 0, day=6))

    print("[shutdown._overdue_from: the no-result clock]")
    e = eng_with({DAY: ["超时|MAA|09:48:12"]})
    check("without the limit: the queue's time, as before", shutdown._overdue_from(e, due, ["MaaEnd"]), due)
    check("with the limit: from the retry", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(9, 48, 12))
    e._gu_rerun_at, e._gu_reran = t(12, 2, 15), {"MaaEnd"}
    check("a later update re-run still wins", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(12, 2, 15))
    e._gu_rerun_at = t(9, 30)
    check("an earlier update re-run loses to the later retry", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(9, 48, 12))
    deadline = shutdown._overdue_from(eng_with({DAY: ["超时|MAA|09:48:12"]}), due, ["MaaEnd"], LIMIT) \
        + timedelta(minutes=LIMIT + runwatch.OVERRUN_SLACK_MIN)
    check("the 11-05 case: no alarm at 10:57", t(10, 57) < deadline, True)
    check("a MaaEnd that hangs after the retry is still caught (11:45)", deadline, t(11, 45, 12))

    print("[runwatch.overrun_moments: the overrun deadline]")
    auto = TMP / "automas"
    (auto / "config").mkdir(parents=True)
    doc = {"instances": [{"uid": "q1", "type": "QueueConfig"}],
           "q1": {"Info": {"Name": "早班", "TimeEnabled": True},
                  "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                     "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}}}}}
    (auto / "config" / "QueueConfig.json").write_text(json.dumps(doc), encoding="utf-8")
    with mock.patch.object(runwatch, "planned_minutes", lambda *a: (LIMIT, 7)):
        for label, marks, want in (("no retry: 09:00 + 87 + 30", {}, t(10, 57)),
                                   ("MAA retried at 09:48: 09:48 + 87 + 30", {DAY: ["超时|MAA|09:48:12"]}, t(11, 45, 12))):
            stub = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=auto), state=types.SimpleNamespace(store=Store(marks)))
            got = [dl for _, hhmm, _, d, _, dl, _ in runwatch.overrun_moments(stub, t(10, 57)) if hhmm == "09:00"]
            check(label, got, [want])

    print("[texts: what the alarm says]")
    old = texts.shift_no_result_body("早班", due, t(11, 50), "MaaEnd", LIMIT, 30, 7)
    check("no retry: the no-result text has no restart clause", "重新算" in old, False)
    new = texts.shift_no_result_body("早班", due, t(11, 50), "MaaEnd", LIMIT, 30, 7, restarted=t(9, 48, 12))
    check("after a retry it says when the clock restarted", "AUTO-MAS 09:48 重试，从那时重新算" in new, True)
    ov = texts.shift_overrun_body("早班", due, t(11, 50), LIMIT, 30, "", "", 7, restarted=t(9, 48, 12))
    check("the overrun text ends at the restarted deadline", "该在 11:45 前结束" in ov, True)
    ov0 = texts.shift_overrun_body("早班", due, t(11, 50), LIMIT, 30, "", "", 7)
    check("without a retry the overrun deadline is 10:57 as before", "该在 10:57 前结束" in ov0 and "重新算" not in ov0, True)


def _part_shiftcheck():
    """After-shift check (selfcheck/shiftcheck.py): the four sign-off items the relay had no
check for, judged once after every finished morning / evening shift.
    """
    import inspect
    import json
    import logging
    import tempfile
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore
    from ark_relay.features import selfcheck, selfcheck as shiftcheck
    from ark_relay.features import shutdown

    def by_name(checks, name):
        return next(c for c in checks if c.name == name)

    print("[each item: green, red, unreadable]")
    green = shiftcheck.judge("", False, False, "", [])
    check("four items", len(green), 4)
    check("all green", [c.ok for c in green], [True] * 4)
    check("all green -> one line saying so", shiftcheck.summary("晚班", green), "收工体检（晚班）4 项都对")
    check("his own MAA settings are not judged (活动关优先 / 作战开关)",
          [c.name for c in green if "活动关" in c.name or "作战" in c.name], [])

    red = shiftcheck.judge(texts.annihilation_off_body("明日方舟 · 剿灭"), True, True, "2026-10-11 20:50",
                           [{"since": "2026-10-11 09:12:00", "until": "2026-10-11 09:40:00"},
                            {"since": "2026-10-11 10:00:00", "until": None}])
    check("annihilation Close, week not done -> red with the boot alarm's words",
          (by_name(red, texts.SHIFTCHECK_ANNIHILATION).ok, by_name(red, texts.SHIFTCHECK_ANNIHILATION).detail),
          (False, texts.annihilation_off_body("明日方舟 · 剿灭")))
    check("「下次跑完不关机」 armed -> holds, with a note", by_name(red, texts.SHIFTCHECK_SKIP).ok, True)
    check("debug mode on -> holds, the note says until when",
          (by_name(red, texts.SHIFTCHECK_DEBUG).ok, "2026-10-11 20:50" in by_name(red, texts.SHIFTCHECK_DEBUG).detail),
          (True, True))
    check("switches off -> no note", [c.detail for c in green], [""] * 4)
    check("a test window still open -> red, names the open one (not the closed one)",
          (by_name(red, texts.SHIFTCHECK_TEST_WINDOW).ok, "10:00:00" in by_name(red, texts.SHIFTCHECK_TEST_WINDOW).detail),
          (False, True))
    check("closed test windows only -> green",
          by_name(shiftcheck.judge("", False, False, "", [{"since": "a", "until": "b"}]),
                  texts.SHIFTCHECK_TEST_WINDOW).ok, True)
    line = shiftcheck.summary("早班", red)
    check("red line counts two not held", line.startswith("收工体检（早班）4 项里 2 项不对、0 项判不了："), True)
    check("his switches follow as a note, not among 不对",
          line.split("；你自己开着的：")[1:], [f"{texts.SHIFTCHECK_SKIP}：{texts.SHIFTCHECK_SKIP_ON}；"
                                            f"{texts.SHIFTCHECK_DEBUG}：{texts.shiftcheck_debug_on('2026-10-11 20:50')}"])
    skip_only = shiftcheck.summary("早班", shiftcheck.judge("", True, False, "", []))
    check("only the skip mark armed -> 都对 plus the note (10-13 10:00:31 said 1 项不对)",
          skip_only, f"收工体检（早班）4 项都对；你自己开着的：{texts.SHIFTCHECK_SKIP}：{texts.SHIFTCHECK_SKIP_ON}")
    check("red line is plain language", texts.plain(line), [])
    check("red line is one line (the daily report reads relay.log line by line)", "\n" in line, False)

    unread = shiftcheck.judge(None, False, False, "", [])
    check("annihilation switch unreadable -> cannot be judged (None), not green",
          by_name(unread, texts.SHIFTCHECK_ANNIHILATION).ok, None)
    check("unreadable line says 判不了", "1 项判不了" in shiftcheck.summary("晚班", unread), True)

    print("\n[once per finished shift, on the tick, before the report and the shutdown]")
    src = inspect.getsource(__import__("ark_relay.core.engine", fromlist=["Engine"]).Engine.tick)
    check("tick runs 收工体检 before 日报 and 关机",
          0 < src.index('"收工体检"') < src.index('"日报"') < src.index('"关机"'), True)

    class Gate:
        def __init__(self, line=""):
            self.line = line

        def switch_off_line(self, now=None):
            return self.line

    class Rec(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    rec = Rec()
    shiftcheck._log_shiftcheck.addHandler(rec)
    shiftcheck._log_shiftcheck.setLevel(logging.DEBUG)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "automas" / "config").mkdir(parents=True)

        due = datetime(2026, 10, 11, 21, 30, tzinfo=SERVER_TZ)
        booted = due - timedelta(minutes=15)
        now = due + timedelta(hours=1)
        store = StateStore(td)
        eng = SimpleNamespace(
            cfg=SimpleNamespace(state_dir=td, automas_dir=td / "automas"),
            state=SimpleNamespace(store=store, dir=td),
            _annihilation=Gate(""), _handled_any=True,
            _boot_time=lambda now: booted,
            _recent_entries=lambda now: [{"script": "MAA", "started": (due + timedelta(minutes=2)).isoformat()}],
            _last_round_manual=lambda now, entries: False,
        )
        real_queues = shutdown._shift_queues
        shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due, "kinds": ["MAA"]}]
        try:
            got = shiftcheck.maybe_run(eng, now)
            check("finished shift -> checked", got is not None and [c.ok for c in got], [True] * 4)
            check("the line went to relay.log at INFO", [(r.levelno, r.getMessage()) for r in rec.records],
                  [(logging.INFO, "收工体检（晚班）4 项都对")])
            check("second tick of the same shift -> not again", shiftcheck.maybe_run(eng, now + timedelta(minutes=1)), None)
            check("the shift is remembered across a restart (state.json marks)",
                  StateStore(td).get("marks", shiftcheck.MARK), due.isoformat())

            # A new shift (next morning) is checked again; this one with every item red.
            due2 = datetime(2026, 10, 12, 5, 0, tzinfo=SERVER_TZ)
            shutdown._shift_queues = lambda e, n, b: [{"name": "早班", "due": due2, "kinds": ["MAA"]}]
            eng._boot_time = lambda now: due2 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": "MAA", "started": (due2 + timedelta(minutes=1)).isoformat()}]
            eng._annihilation = Gate(texts.annihilation_off_body("明日方舟 · 剿灭"))
            store.set("modes", "skip_next_shutdown", True)
            store.set("modes", "debug_until", "2099-01-01 00:00")
            (td / "test-windows.json").write_text(json.dumps([{"since": "2026-10-12 04:50:00", "until": None}]),
                                                  encoding="utf-8")
            rec.records.clear()
            got = shiftcheck.maybe_run(eng, due2 + timedelta(hours=2))
            check("next shift, faults red and switches noted, read from the state files", got and [c.ok for c in got],
                  [False, True, True, False])
            check("switch notes read from the state files", got and [bool(c.detail) for c in got][1:3], [True, True])
            check("red goes out as a WARNING (errwatch takes it to the group)",
                  [r.levelno for r in rec.records], [logging.WARNING])
            check("red line names the morning shift", rec.records[0].getMessage().startswith("收工体检（早班）4 项里 2 项不对"),
                  True)

            # Not finished / not a scheduled shift: nothing.
            due3 = due2 + timedelta(hours=16, minutes=30)
            shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due3, "kinds": ["MAA", "OK-WW"]}]
            eng._boot_time = lambda now: due3 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": "MAA", "started": (due3 + timedelta(minutes=1)).isoformat()}]
            check("a script of the shift not recorded yet -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)),
                  None)
            check("still running -> no line (it may yet finish)", rec.records[-1:] and rec.records[-1].getMessage().startswith(
                "收工体检（早班）"), True)
            rec.records.clear()
            eng._recent_entries = lambda now: [{"script": k, "started": (due3 + timedelta(minutes=1)).isoformat()}
                                               for k in ("MAA", "OK-WW")]
            eng._last_round_manual = lambda now, entries: True
            check("last round started by hand -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
            check("a due shift not judged says so once at INFO, in words the daily report quotes",
                  [(r.levelno, r.getMessage()) for r in rec.records],
                  [(logging.INFO, "收工体检（晚班）这班没查：最近一轮是手动触发的")])
            shiftcheck.maybe_run(eng, due3 + timedelta(hours=1, minutes=1))
            check("not repeated on the next tick", len(rec.records), 1)
            check("the daily report quotes it",
                  selfcheck.daily_lines("2026-10-12", "10-12 22:31:05 INFO    ark.shiftcheck  " + rec.records[0].getMessage()
                                        + "\n")[2:], ["· 收工体检（晚班）这班没查：最近一轮是手动触发的"])
            rec.records.clear()
            eng._last_round_manual = lambda now, entries: False
            eng._handled_any = False
            check("records never seen landing on this boot (relay restarted after the shift) -> not checked",
                  shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
            eng._handled_any = True
            eng._boot_time = lambda now: None
            check("boot time unknown -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
            eng._boot_time = lambda now: due3 - timedelta(minutes=15)
            shutdown._shift_queues = lambda e, n, b: []
            check("no scheduled shift on this boot -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)

            # A queue with no name (plan gives "?"): labelled by its time.
            due4 = due3 + timedelta(hours=8)
            shutdown._shift_queues = lambda e, n, b: [{"name": "?", "due": due4, "kinds": ["MAA"]}]
            eng._boot_time = lambda now: due4 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": "MAA", "started": (due4 + timedelta(minutes=1)).isoformat()}]
            rec.records.clear()
            shiftcheck.maybe_run(eng, due4 + timedelta(hours=1))
            check("unnamed 05:xx queue -> 早班", rec.records and rec.records[0].getMessage().startswith("收工体检（早班）"), True)
            eng._boot_time = lambda now: due3 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": k, "started": (due3 + timedelta(minutes=1)).isoformat()}
                                               for k in ("MAA", "OK-WW")]

            # A crash inside the check: ERROR, said in the line, not run again on the next tick.
            shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due3, "kinds": ["MAA", "OK-WW"]}]
            real_read = shiftcheck.read
            shiftcheck.read = lambda e, n: 1 / 0
            rec.records.clear()
            try:
                check("crash -> []", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), [])
            finally:
                shiftcheck.read = real_read
            check("crash is a relay fault: ERROR with its traceback (errwatch pushes it), saying the shift was not checked",
                  [(r.levelno, r.getMessage(), bool(r.exc_info)) for r in rec.records],
                  [(logging.ERROR, texts.shiftcheck_broken("晚班"), True)])
            check("crashed shift not retried on every tick", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1, minutes=1)),
                  None)
        finally:
            shutdown._shift_queues = real_queues

    print("\n[the daily report's relay section quotes each shift's line]")
    log = """10-11 21:20:00 INFO    ark.service  服务模式启动
10-11 21:21:00 INFO    ark.service  AUTO-MAS 自己起来了（等了 21 秒）
10-11 22:31:05 INFO    ark.shiftcheck  收工体检（晚班）4 项里 1 项不对、0 项判不了：调试模式：开着，到 2026-10-12 04:50，这期间跑完不关机
10-10 22:31:05 INFO    ark.shiftcheck  收工体检（晚班）4 项都对
10-11 06:40:00 INFO    ark.shiftcheck  收工体检（早班）4 项都对
"""
    lines = selfcheck.daily_lines("2026-10-11", log)
    check("both shifts of the day quoted after the two relay lines, not yesterday's",
          lines[2:], ["· 收工体检（晚班）4 项里 1 项不对、0 项判不了：调试模式：开着，到 2026-10-12 04:50，这期间跑完不关机",
                      "· 收工体检（早班）4 项都对"])
    check("the shift line does not count as a boot", lines[1], "· 调度程序开机：21:21 自己起来了（等了 21 秒）")
    check("no shift line -> still the two lines", len(selfcheck.daily_lines("2026-10-09", log)), 2)

    print("\n[audit 11-08 C-07: a test window left open does not take later scheduled runs out of the report]")
    from ark_relay.core import ledger as _lr
    _open = [{"since": "2026-10-12T04:50:00+08:00", "until": None}]
    _test_run = {"run_id": "t", "started": "2026-10-12T05:10:00+08:00"}
    _shift_run = {"run_id": "s", "started": "2026-10-12T09:00:00+08:00"}
    _real, _tests = _lr.split_test([_test_run, _shift_run], _open)
    check("the run inside the window is a test", [e["run_id"] for e in _tests], ["t"])
    check("the 09:00 shift, 4 h after it opened, is real", [e["run_id"] for e in _real], ["s"])


def _part_overdue_after_update_rerun():
    """「⏰ 一直没出结果」 after a client update: the scripts the relay re-ran itself are timed from the re-run.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import shutdown

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


def _part_next_deadline():
    """When the loop is allowed to sleep until - the one number that decides
whether the relay wakes up at all.
    """
    import json
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)

    def write_queues(times_by_name):
        """A QueueConfig.json shaped the way AUTO-MAS writes it."""
        doc = {"instances": []}
        for i, (name, times) in enumerate(times_by_name.items()):
            uid = f"q{i}"
            doc["instances"].append({"uid": uid})
            doc[uid] = {
                "Info": {"Name": name, "TimeEnabled": True},
                "SubConfigsInfo": {
                    "TimeSet": {str(n): {"Info": {"Enabled": True, "Time": t}}
                                for n, t in enumerate(times)},
                    "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}},
                },
            }
        (AUTOMAS / "config" / "QueueConfig.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    write_queues({"早班": ["09:00"], "晚班": ["21:30"]})
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(
        json.dumps({"instances": []}), encoding="utf-8")

    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    (TMP / "history").mkdir(exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.handle import MISSED_GRACE_MIN

    class Notes:
        def send(self, title, body="", **kw):
            return False

    def build(state_dir=None):
        cfg = Config()
        cfg.state_dir = state_dir or tmpdir()
        e = eng.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        return e

    def at(hh, mm, day=8):
        return datetime(2026, 9, day, hh, mm, tzinfo=SERVER_TZ)

    print("[08:00: the next moment is 「早班漏没漏跑」 (09:25); no wake-up checkpoint since 2026-10-10]")
    e = build()
    when, why = e.next_deadline(at(8, 0))
    check("时刻", when, at(9, 0) + timedelta(minutes=MISSED_GRACE_MIN))
    check("理由点名了队列", "早班" in why, True)
    check("no checkpoint reason", "检查点" in why, False)

    print("\n[09:10: still 「早班漏没漏跑」 (09:25)]")
    when, why = e.next_deadline(at(9, 10))
    check("时刻", when, at(9, 0) + timedelta(minutes=MISSED_GRACE_MIN))

    print("\n[已经告警过的队列不再排队，否则同一件事反复叫醒]")
    e._missed_alerted.add("2026-09-08/早班/09:00")
    when, why = e.next_deadline(at(9, 10))
    check("跳到晚班那一档", when.hour >= 21, True)

    print("\n[日报没发时，21:30 的截止时刻必须在候选里]")
    e2 = build()
    when, why = e2.next_deadline(at(21, 0))
    check("21:30 截止", (when, why), (at(21, 30), "日报截止"))

    print("\n[日报发过了就不再为它醒——不然每轮都算一遍已经做完的事]")
    e2.state.mark_report_sent("2026-09-08")
    when, why = e2.next_deadline(at(21, 0))
    check("换成别的理由", why != "日报截止", True)
    check("仍然有下一个时刻", when is not None, True)

    print("\n[永远不给一个已经过去的时刻：给了循环就空转]")
    e3 = build()
    bad = []
    for hh in range(24):
        for mm in (0, 1, 29, 30, 31, 59):
            now = at(hh, mm)
            got = e3.next_deadline(now)
            if got is None:
                bad.append(f"{hh:02d}:{mm:02d} 没有下一个时刻")
            elif got[0] <= now:
                bad.append(f"{hh:02d}:{mm:02d} 给了过去的 {got[0]}")
    check("一天 144 个时刻全部合法", bad[:3], [])

    print("\n[今天的都过完了就滚到明天，不许返回 None]")
    when, why = e3.next_deadline(at(23, 59))
    check("落在明天", when.date(), at(0, 0, day=9).date())

    print("\n[已经下过关机令就别再醒了——机器马上就没了]")
    e4 = build()
    e4._shutdown_issued = True
    check("返回 None", e4.next_deadline(at(9, 0)), None)

    print("\n[关机令发出后只醒一次：到点核对关机有没有关下去（audit s2 F2）]")
    e4._shutdown_issued_at = at(9, 0)
    from ark_relay.features.shutdown import ISSUED_STUCK_MIN
    got = e4.next_deadline(at(9, 1))
    check("醒在发令后 ISSUED_STUCK_MIN 分钟", got and got[0], at(9, 0) + timedelta(minutes=ISSUED_STUCK_MIN))
    check("那一刻过了就不再给过去的时刻", e4.next_deadline(at(9, 0) + timedelta(minutes=ISSUED_STUCK_MIN)), None)

    print("\n[队列时间改了，醒来的时刻跟着改（读的是 AUTO-MAS 自己那份）]")
    write_queues({"早班": ["07:15"], "晚班": ["21:30"]})
    e5 = build()
    when, why = e5.next_deadline(at(6, 0))
    check("跟着挪到 07:15 那一档", when, at(7, 15) + timedelta(minutes=MISSED_GRACE_MIN))
    check("理由点名新队列时刻", "07:15" in why, True)
    write_queues({"早班": ["09:00"], "晚班": ["21:30"]})

    print("\n[队列时间写坏了不许把整个循环带走]")
    doc = json.loads((AUTOMAS / "config" / "QueueConfig.json").read_text(encoding="utf-8"))
    doc["q0"]["SubConfigsInfo"]["TimeSet"]["0"]["Info"]["Time"] = "坏掉的时刻"
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                         encoding="utf-8")
    e6 = build()
    raised = ""
    try:
        got = e6.next_deadline(at(6, 0))
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("不抛异常", raised, "")
    check("坏的那档被跳过，好的还在", got is not None, True)

    print("\n[正在刷声骸时，收工时刻和「看一眼还活着没」都要能把循环叫醒]")
    from ark_relay.features import echofarm
    e7 = build()
    _store = echofarm._store(e7.cfg.state_dir)
    _store.set("queues", "echo_farm", {"boss": 1, "name": "天傀劫煞",
                                       "until": at(8, 30).strftime("%Y-%m-%d %H:%M"),
                                       "started": at(6, 2).strftime("%Y-%m-%d %H:%M"),
                                       "saved": {}})
    try:
        when, why = e7.next_deadline(at(7, 0))
        check("先去看一眼它还活着没", "刷声骸" in why, True)
        check("而且很快就看", (when - at(7, 0)).total_seconds() / 60.0,
              float(echofarm.RESTART_QUIET_MINUTES))
        when2, why2 = e7.next_deadline(at(8, 29))
        check("快到点时叫醒的是收工那一下", "收工" in why2, True)
        check("就是 08:30 那一刻", when2.strftime("%H:%M"), "08:30")
    finally:
        _store.pop("queues", "echo_farm")
    check("没在刷的时候不多这两个闹钟", "刷声骸" in build().next_deadline(at(7, 0))[1], False)


def _part_next_plan_imports():
    """next_plan 能不能被调起来——2026-09-04 就是这里断的。"""
    import sys, tempfile, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import plan

    with tempfile.TemporaryDirectory() as d:
        # 没有 AUTO-MAS 目录也必须能返回，不能抛
        out = plan.next_plan(d)
        assert isinstance(out, str), f"next_plan 应返回字符串，得到 {type(out)}"
        out2 = plan.next_plan(None)
        assert isinstance(out2, str)
        # 那个被搬过来的辅助函数也得在，且对空输入安全
        assert plan._asar_value_labels(None, d) == {}
        assert plan._asar_value_labels(d, d) == {}
    print("✅ next_plan 调得起来 — all checks passed")


def _part_next_queue_weekdays():
    """boot_stages._seconds_to_next_queue skips a queue time that runs nothing today (audit s23 F4, 10-13).
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ

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


def _part_dispatch_guard_idle():
    """run-one.sh wait-idle waits on dispatch_guard.py idle's exit code, not on the status wording.
    """
    import runpy
    import subprocess

    ROOT = Path(__file__).resolve().parents[2]
    GUARD = ROOT / "scripts" / "windows" / "dispatch_guard.py"

    def idle_exit(tasklist: str, okww_pids: str = "") -> int:
        """dispatch_guard.py idle's exit code with `tasklist` as the process list and
    `okww_pids` as the PowerShell query for OK-WW's own python (okww_pids)."""
        real_run = subprocess.run

        def fake(cmd, *a, **k):
            out = tasklist if cmd == ["tasklist"] else okww_pids
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        subprocess.run = fake
        argv = sys.argv
        sys.argv = [str(GUARD), "idle"]
        try:
            runpy.run_path(str(GUARD), run_name="__main__")
        except SystemExit as e:
            return int(e.code or 0)
        finally:
            subprocess.run, sys.argv = real_run, argv
        return 0

    print("[idle：只看有没有脚本或游戏在跑，退出码说话]")
    check("什么都没在跑 → 0", idle_exit("System Idle Process  0\nexplorer.exe  1234\n"), 0)
    check("MaaEnd 在跑 → 3", idle_exit("MaaEnd.exe  4321\n"), 3)
    check("只有游戏开着 → 3", idle_exit("Endfield.exe  5555\n"), 3)
    check("OK-WW 自己的 python 在跑 → 3", idle_exit("explorer.exe  1234\n", okww_pids="7996\n"), 3)
    run_one = (ROOT / "scripts" / "mac" / "run-one.sh").read_text(encoding="utf-8")
    check("run-one.sh wait-idle 用的是 idle 的退出码，不 grep 状态那一行", ("--py \"$G\" idle" in run_one, "grep" in run_one), (True, False))


def _part_dispatch_guard_self():
    """The busy gate must not mistake itself for a running script."""
    import re

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    SRC = (Path(__file__).resolve().parents[2] / "scripts" / "windows"
           / "dispatch_guard.py").read_text(encoding="utf-8")

    pattern = re.search(r"CommandLine -like '([^']+)'", SRC)
    print("[判据必须是安装路径，不是一个能出现在参数里的词]")
    check("找得到那条匹配", bool(pattern))
    like = pattern.group(1) if pattern else ""
    check(f"带路径分隔符（{like}）", "\\" in like)

    def matches(cmdline: str) -> bool:
        """PowerShell -like, case-insensitive, * only."""
        body = re.escape(like).replace(r"\*", ".*")
        return re.fullmatch(body, cmdline, re.IGNORECASE) is not None

    print("[真在跑的两种起法都要认出来]")
    check("AUTO-MAS 起的 pythonw",
          matches(r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe D:\ark\okww\data\apps\ok-ww\working\main.py -t 1 -e"))
    check("手动起的 python",
          matches(r"D:\ark\okww\data\apps\ok-ww\python\python.exe main.py -t 2"))

    print("[闸门自己和别的脚本不许被算进去]")
    check("闸门自己（参数里带 OK-WW）",
          matches(r"C:\Python314\python.exe C:\ProgramData\winrun-run-123.py OK-WW"), False)
    check("参数里带小写 ok-ww 的别的命令",
          matches(r"C:\Python314\python.exe something.py --script ok-ww"), False)
    check("中继自己",
          matches(r"C:\Program Files\Python314\pythonservice.exe"), False)


def _part_dispatch_guard_silent():
    """dispatch_guard.py must not read "cannot ask" as "nothing there"."""
    import contextlib
    import io
    import json
    import urllib.error

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "windows"))
    import dispatch_guard as g

    class Answer:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

    def quiet(fn, *a):
        """(value or SystemExit code, stdout) of fn(*a)."""
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                got = fn(*a)
        except SystemExit as e:
            got = ("exit", e.code)
        return got, out.getvalue()

    REFUSED = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
    SNAP_EMPTY = json.dumps({"tasks": []}).encode()
    SNAP_MAA = json.dumps({"tasks": [{"taskId": "t1", "task_info": [{"name": "MAA"}]}]}).encode()

    def snapshots(*answers):
        """urlopen answering the runtime-snapshot with each item in turn (the last one repeats);
    an exception item is raised."""
        left = list(answers)

        def urlopen(*a, **k):
            item = left.pop(0) if len(left) > 1 else left[0]
            if isinstance(item, BaseException):
                raise item
            return Answer(item)
        return urlopen

    print("[live_tasks: cannot ask is None, nothing running is []]")
    g.urllib.request.urlopen = snapshots(REFUSED)
    check("connection refused -> None", quiet(g.live_tasks)[0], None)
    g.urllib.request.urlopen = snapshots(TimeoutError("timed out"))
    check("timeout -> None", quiet(g.live_tasks)[0], None)
    g.urllib.request.urlopen = snapshots(b"<html>not json</html>")
    check("not JSON -> None", quiet(g.live_tasks)[0], None)
    g.urllib.request.urlopen = snapshots(SNAP_EMPTY)
    check("an empty snapshot -> []", quiet(g.live_tasks)[0], [])

    def stop_with(urlopen, running_seq):
        """stop_all with the snapshot answered by `urlopen` and running() giving `running_seq` in turn."""
        kills = []
        runs = list(running_seq)
        g.urllib.request.urlopen = urlopen
        g.running = lambda: runs.pop(0) if len(runs) > 1 else runs[0]
        g.post = lambda *a, **k: {"message": "操作成功"}
        g.subprocess.run = lambda args, **k: kills.append(args)
        g.okww_pids = lambda: []
        g.time.sleep = lambda s: None
        ok, out = quiet(g.stop_all)
        return ok, out, [k for k in kills if k and k[0] == "taskkill"]

    print("[stop with AUTO-MAS unreachable and MAA still up: no taskkill]")
    ok, out, kills = stop_with(snapshots(REFUSED), [(["MAA"], [])])
    check("no taskkill was run", kills, [])
    check("stop_all reports failure", ok, False)
    check("it does not claim nothing is running", "没有在跑的任务" in out, False)
    check("it says why it refused to kill", "不 taskkill" in out, True)

    print("[the 12 s recheck cannot ask: still no taskkill]")
    ok, out, kills = stop_with(snapshots(SNAP_MAA, REFUSED), [(["MAA"], [])])
    check("no taskkill after a failed recheck", kills, [])
    check("stop_all reports failure after a failed recheck", ok, False)

    print("[AUTO-MAS answered nothing running and a game is left: taskkill as before]")
    ok, out, kills = stop_with(snapshots(SNAP_EMPTY), [([], ["Endfield"]), ([], [])])
    check("taskkill was run", len(kills) > 0, True)
    check("stop_all reports clean after taskkill", ok, True)

    print("[AUTO-MAS unreachable but nothing running: clean]")
    ok, out, kills = stop_with(snapshots(REFUSED), [([], [])])
    check("no taskkill when nothing runs", kills, [])
    check("stop_all reports clean when nothing runs", ok, True)

    print("[a corrupt test-windows.json is not 'no window open']")
    d = tmpdir()
    g.TEST_WINDOWS = str(d / "test-windows.json")
    check("missing file: test-status says closed (exit 0)", quiet(g.test_status)[0], 0)
    Path(g.TEST_WINDOWS).write_text('[{"since": "2026-10-10T01:00:00+08:00", "until": nu', encoding="utf-8")
    before = Path(g.TEST_WINDOWS).read_bytes()
    got, out = quiet(g.test_status)
    check("test-status exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
    check("it does not print the closed status line", "测试窗口：没开" in out, False)
    got, out = quiet(g.test_on, "MAA")
    check("test_on exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
    got, out = quiet(g.test_off)
    check("test_off exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
    check("the file is untouched", Path(g.TEST_WINDOWS).read_bytes(), before)


def _part_dispatch_guard_test_debug():
    """A test dispatch turns debug mode on first, and test-off turns off only what it turned on.
    """
    import contextlib
    import inspect
    import io
    import json

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "windows"))
    import dispatch_guard as g
    from ark_relay.features import modes

    def setup():
        state = tmpdir()
        g.STATE_DIR = str(state)
        g.TEST_WINDOWS = str(state / "test-windows.json")
        return state

    dispatched = []
    g.status = lambda: []
    g.ids = lambda: {"OK-WW": "sid-okww"}
    g.post = lambda path, body=None: dispatched.append(body["taskId"]) or {"status": "success"}
    g._modes = lambda: modes

    def run(fn, *a, **k):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = fn(*a, **k)
        return rc, out.getvalue()

    def windows():
        return json.loads(Path(g.TEST_WINDOWS).read_text(encoding="utf-8"))

    print("[debug off -> the test start turns it on before dispatching, and records it]")
    state = setup()
    dispatched.clear()
    rc, out = run(g.start, "OK-WW", test=True)
    check("dispatched", (rc, dispatched), (0, ["sid-okww"]))
    check("debug mode on", modes.debug_active(state), True)
    check("the window records the debug_until it wrote", windows()[-1].get("debug_set"), modes.debug_until(state))
    rc, out = run(g.test_status)
    check("test-status says this window turned it on", "调试模式是这个窗口开的" in out, True)
    rc, out = run(g.test_off)
    check("test-off: window closed", windows()[-1]["until"] is not None, True)
    check("test-off: debug mode off again", (rc, modes.debug_active(state)), (0, False))

    print("\n[10-13: the morning shift spent 「下次跑完不关机」 (key :3), then a test -> test-off keeps that skip]")
    state = setup()
    modes.mark_shutdown_skipped(state, "2026-10-13:3")       # what take_skip's caller writes
    run(g.start, "OK-WW", test=True)
    rc, out = run(g.test_off)
    check("test-off: debug mode off", (rc, modes.debug_active(state)), (0, False))
    check("test-off: the spent mark's skipped occasion is still there (no power-off after the test)",
          modes.shutdown_skipped(state), "2026-10-13:3")

    print("\n[a skip debug mode itself recorded during the window -> test-off releases it]")
    state = setup()
    run(g.start, "OK-WW", test=True)
    can_tag = "by_debug" in inspect.signature(modes.mark_shutdown_skipped).parameters
    check("debug mode's own skip is told apart from the mark's", can_tag, True)
    if can_tag:
        modes.mark_shutdown_skipped(state, "2026-10-13:4", by_debug=True)   # shutdown._maybe_shutdown, verdict "debug"
        run(g.test_off)
        check("test-off: debug mode's own skip is cleared", modes.shutdown_skipped(state), "")

    print("\n[debug already on -> left on, and not turned off at test-off]")
    state = setup()
    modes.set_debug(state, 2)
    before = modes.debug_until(state)
    dispatched.clear()
    rc, out = run(g.start, "OK-WW", test=True)
    check("dispatched", (rc, dispatched), (0, ["sid-okww"]))
    check("debug untouched", modes.debug_until(state), before)
    check("the window does not claim it", "debug_set" in windows()[-1], False)
    rc, out = run(g.test_off)
    check("test-off leaves it on", (rc, modes.debug_until(state)), (0, before))

    print("\n[changed during the window (e.g. extended from the phone) -> test-off leaves it]")
    state = setup()
    run(g.start, "OK-WW", test=True)
    modes.set_debug(state, 3)
    extended = modes.debug_until(state)
    run(g.test_off)
    check("left as extended", modes.debug_until(state), extended)

    print("\n[debug mode cannot be written -> the test dispatch is refused]")
    state = setup()

    class Broken:
        debug_active = staticmethod(lambda sd: False)
        debug_until = staticmethod(lambda sd: "")

        @staticmethod
        def set_debug(sd, cycles=1, off=False):
            raise OSError(13, "Access is denied")

    g._modes = lambda: Broken
    dispatched.clear()
    rc, out = run(g.start, "OK-WW", test=True)
    check("refused, non-zero", rc, 6)
    check("nothing dispatched", dispatched, [])
    check("says why", "调试模式开不了" in out and "Access is denied" in out, True)
    check("no test window opened", Path(g.TEST_WINDOWS).exists(), False)

    print("\n[test-windows.json unreadable -> refused before debug mode is switched on]")
    state = setup()
    g._modes = lambda: modes
    Path(g.TEST_WINDOWS).write_text("{not json", encoding="utf-8")
    dispatched.clear()
    try:
        rc, out = run(g.start, "OK-WW", test=True)
    except SystemExit as exc:
        rc = exc.code
    check("refused with exit 5", rc, 5)
    check("debug mode left off (nothing would ever turn it off again)", modes.debug_active(state), False)
    check("nothing dispatched", dispatched, [])
    check("the window file is left as it was", Path(g.TEST_WINDOWS).read_text(encoding="utf-8"), "{not json")

    print("\n[a normal (non-test) dispatch does not touch debug mode]")
    state = setup()
    g._modes = lambda: modes
    dispatched.clear()
    rc, out = run(g.start, "OK-WW")
    check("dispatched, debug still off", (rc, modes.debug_active(state)), (0, False))


def _part_dispatch_note_timing():
    """The relay notes "this run is mine" right before the dispatch call, after the
OK-WW overlay step.
    """
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import trigger
    from ark_relay.features import okww_overlay as ov
    from ark_relay.features import commands

    clock = {"t": datetime(2026, 10, 13, 8, 0, 0, tzinfo=SERVER_TZ)}
    created: list[trigger.Task] = []

    def slow_overlay(where):
        clock["t"] += timedelta(seconds=120)     # an overlay step that takes two minutes
        return ""

    def mas(path, body=None):
        if path == "/api/scripts/get":
            return {"data": {"s1": {"Info": {"Name": "OK-WW"}}}}
        if path == "/api/queue/get":
            return {"data": {"q1": {"Info": {"Name": "早班"}}}}
        # AUTO-MAS labels the relay's start manual_task, like a click on its screen.
        created.append(trigger.Task(id=body["taskId"], mode="AutoProxy", source=trigger.MANUAL,
                                    created=clock["t"] + timedelta(seconds=2)))
        return {"status": "success"}

    real = (ov.retry_pending, commands._mas, trigger.note_dispatch)
    real_note = trigger.note_dispatch
    ov.retry_pending = slow_overlay
    commands._mas = mas
    trigger.note_dispatch = lambda state_dir, what, now=None: real_note(state_dir, what, now=clock["t"])
    state = Path(os.environ["ARK_STATE_DIR"])
    try:
        print("[a slow overlay step before a single-script dispatch]")
        check("dispatched", commands.run_script("OK-WW")[0], True)
        check("the relay's own run is not hand-started", trigger.hand_started_task(created[-1], state), False)

        print("\n[a slow overlay step before a queue dispatch]")
        clock["t"] += timedelta(hours=1)
        check("dispatched", commands._run_now("早班")[0], True)
        check("the relay's own run is not hand-started", trigger.hand_started_task(created[-1], state), False)
    finally:
        ov.retry_pending, commands._mas, trigger.note_dispatch = real


def _part_runwatch_main():
    """Watch a running queue: push every timeout at once, and a shift that overruns."""
    import json
    import os
    import types
    from datetime import datetime, timedelta

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    MORNING_UID, EVENING_UID = "cc32e55a-55d0-408d-980d-642e66d111ae", "6f09a385-b0ae-4ff6-9890-50339bdaddeb"
    doc = {"instances": [{"uid": MORNING_UID, "type": "QueueConfig"}, {"uid": EVENING_UID, "type": "QueueConfig"}]}
    for uid, name, t in ((MORNING_UID, "早班", "09:00"), (EVENING_UID, "晚班", "21:30")):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                    "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features import machinecheck as _mc
    _mc.load()
    _mc_real = dict(_mc.CHECKS)   # put back at the end: the coverage pass runs every test file in one process
    _mc.CHECKS.clear()   # the alarms themselves are tested here; the machine checks in tests/test_mc.py

    class Notes:
        def __init__(self):
            self.sent = []
            self.fail = False

        def send(self, title, body="", **kw):
            if self.fail:
                return ["群机器人发送失败"]
            self.sent.append((title, body, kw.get("alert", False)))
            return False

    APPLOG = AUTOMAS / "debug" / "app.log"
    LINES = [
        "2026-10-01 09:18:20.376 | INFO     | OK-WW 自动代理 | 用户 wuwa - 尝试次数: 1/3",
        "2026-10-01 09:18:20.701 | INFO     | OK-WW 自动代理 | 启动 OK-WW 进程: D:\\ark\\okww\\ok-ww.exe -t 1 -e",
        "2026-10-01 11:20:12.246 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 11:20:12.255 | WARNING  | OK-WW 自动代理 | 用户 wuwa - OK-WW 代理异常: OK-WW 运行超时",
        "2026-10-01 11:20:22.291 | INFO     | OK-WW 自动代理 | 用户 wuwa - 尝试次数: 2/3",
        "2026-10-01 13:21:12.400 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 13:21:22.468 | INFO     | OK-WW 自动代理 | 用户 wuwa - 尝试次数: 3/3",
        "2026-10-01 15:23:06.615 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 15:23:07.031 | INFO     | MaaEnd 自动代理 | 用户 endfield - 原配置阶段尝试次数: 1/3",
        "2026-10-01 16:10:00.012 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 进程超时, 日志锁已释放",
        "2026-10-01 16:10:02.996 | INFO     | MaaEnd 自动代理 | 用户 endfield - 原配置阶段尝试次数: 2/3",
    ]

    def at(hh, mm, day=1, month=10):
        return datetime(2026, month, day, hh, mm, tzinfo=SERVER_TZ)

    def write_log(upto):
        APPLOG.write_text("".join(l + "\n" for l in LINES[:upto]), encoding="utf-8")

    def append_log(frm, upto):
        with APPLOG.open("a", encoding="utf-8") as fh:
            fh.write("".join(l + "\n" for l in LINES[frm:upto]))

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        return e

    def run_watch(e, now):
        step = getattr(e, "_run_watch", None)     # absent before the fix: nothing ever looks
        if step is not None:
            step(now)

    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]

    print("[10-01 replay: OK-WW's first timeout at 11:20 is pushed at once]")
    write_log(4)
    e = build()
    run_watch(e, at(11, 21))
    got = alarms(e)
    check("one alarm", len(got), 1)
    check("names the game and script", bool(got) and "鸣潮（OK-WW）" in got[0][0], True)
    check("says attempt 1/3, start and end", bool(got) and "第 1/3 次跑超时：09:18 开跑，11:20" in got[0][1], True)
    check("says how many retries are left", bool(got) and "再试 2 次" in got[0][1], True)

    print("\n[the second and third OK-WW timeouts the same day are pushed too]")
    append_log(4, 8)
    run_watch(e, at(13, 22))
    run_watch(e, at(15, 24))
    got = alarms(e)
    check("three alarms", len(got), 3)
    check("second: attempt 2/3", len(got) > 1 and "第 2/3 次跑超时：11:20 开跑，13:21" in got[1][1], True)
    check("third: the last attempt", len(got) > 2 and "第 3/3 次跑超时" in got[2][1] and "这已是最后一次" in got[2][1], True)
    check("no 「不重复报」 promise any more", any("不重复报" in b for _, b in got), False)
    run_watch(e, at(15, 25))
    check("the same line is not pushed twice", len(alarms(e)), 3)

    print("\n[MaaEnd's first timeout at 16:10 is its own alarm]")
    append_log(8, 11)
    run_watch(e, at(16, 11))
    got = alarms(e)
    check("four alarms now", len(got), 4)
    check("the fourth is 终末地", len(got) == 4 and "终末地（MaaEnd）" in got[3][0], True)
    check("first attempt, 15:23 to 16:10", len(got) == 4 and "第 1/3 次跑超时：15:23 开跑，16:10" in got[3][1], True)

    print("\n[a relay started later does not replay the morning]")
    write_log(11)
    e2 = build()
    run_watch(e2, at(17, 30))
    check("nothing older than 30 minutes is news", alarms(e2), [])

    print("\n[an alarm that could not be sent is retried next tick]")
    write_log(4)
    e3 = build()
    e3.notifier.fail = True
    run_watch(e3, at(11, 21))
    check("nothing sent while the channel fails", alarms(e3), [])
    e3.notifier.fail = False
    run_watch(e3, at(11, 22))
    check("sent on the next tick", len(alarms(e3)), 1)

    print("\n[an alarm still unsent when it goes stale: one WARNING, not dropped silently (audit s18 F3)]")
    import logging as _logging
    from ark_relay.features import runwatch
    _said = []
    _h = type("H", (_logging.Handler,), {"emit": lambda self, r: _said.append((r.levelno, r.getMessage()))})()
    runwatch.log.addHandler(_h)
    try:
        write_log(4)
        e3b = build()
        e3b.notifier.fail = True
        run_watch(e3b, at(11, 21))
        _said.clear()
        run_watch(e3b, at(12, 0))
        gave_up = [m for lv, m in _said if lv == _logging.WARNING and "不再重试" in m]
        check("one WARNING says the timeout alarm was given up", len(gave_up), 1)
        check("it names the script and the time", bool(gave_up) and "OK-WW 11:20" in gave_up[0], True)
        _said.clear()
        run_watch(e3b, at(12, 1))
        check("not said again", [m for lv, m in _said if "不再重试" in m], [])
        check("a stale line read fresh from app.log is still dropped quietly",
              runwatch.check_timeouts(e3b, [runwatch.Timeout(at(9, 0), "MAA", "进程超时")], at(12, 0)), [])
        check("... with no WARNING", [m for lv, m in _said if "不再重试" in m], [])
    finally:
        runwatch.log.removeHandler(_h)

    print("\n[app.log rotated (AUTO-MAS restarted): read from the start again]")
    write_log(0)
    e4 = build()
    run_watch(e4, at(11, 0))
    write_log(4)
    run_watch(e4, at(11, 21))
    check("timeout found in the new file", len(alarms(e4)), 1)

    # ---------------------------------------------------------------- shift overrun
    from ark_relay.features import runwatch

    ledger = _write_ledger

    def t(day, hh, mm, ss=0, month=9):
        return datetime(2026, month, day, hh, mm, ss, tzinfo=SERVER_TZ)

    def seed(state):
        """Ledger shapes of 09-24..09-30 (morning) plus a 21:30 evening run each day."""
        morning_end = {24: (10, 50), 25: (10, 0), 26: (9, 49), 27: (9, 53), 29: (9, 49), 30: (9, 47)}
        for d, (hh, mm) in morning_end.items():
            rows = [("MAA", t(d, 9, 0, 50), t(d, 9, 18)), ("OK-WW", t(d, 9, 18, 30), t(d, 9, 30)),
                    ("MaaEnd", t(d, 9, 31), t(d, hh, mm))]
            if d == 30:     # a make-up run hours later is not part of the shift
                rows.append(("MaaEnd", t(d, 15, 33), t(d, 15, 48)))
            rows.append(("MAA", t(d, 21, 30, 50), t(d, 21, 45 + d % 5)))
            ledger(state, t(d, 0, 0), rows)
        ledger(state, t(28, 0, 0), [
            ("MAA", t(28, 9, 0, 52), t(28, 9, 4, 4)), ("MAA", t(28, 9, 4, 8), t(28, 9, 27, 32)),
            ("OK-WW", t(28, 9, 27, 53), t(28, 10, 28, 37)), ("MaaEnd", t(28, 10, 29, 47), t(28, 11, 22, 10)),
            ("MaaEnd", t(28, 12, 3, 14), t(28, 12, 40, 2)), ("MAA", t(28, 21, 30, 54), t(28, 21, 46, 29))])

    def snap(okww, maaend, queue=MORNING_UID):
        return {"tasks": [{"taskId": "8f47a684", "mode": "AutoProxy", "queueId": queue, "log": "正在启动游戏...",
                           "task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": okww},
                                         {"name": "MaaEnd", "status": maaend}]}]}

    print("\n[planned end = longest finish of the last 7 days, from the ledger]")
    e5 = build()
    seed(e5.state)
    check("早班: 220 minutes (09-28, hole included)", runwatch.planned_minutes(e5, 9, 0, at(9, 0)), (220, 7))
    check("晚班: 19 minutes", runwatch.planned_minutes(e5, 21, 30, at(21, 30))[0], 19)
    check("make-up run on 09-30 is not counted",
          runwatch.run_minutes(e5.state.read_ledger("2026-09-30"), t(30, 9, 0)), 47)
    check("no history -> fallback", runwatch.planned_minutes(build(), 9, 0, at(9, 0)), (180, 0))

    print("\n[10-01 itself (failed, seven hours) does not become tomorrow's limit]")
    ledger(e5.state, at(0, 0), [
        ("MAA", at(9, 0), at(9, 18)),
        ("OK-WW", at(9, 18), at(11, 20)), ("OK-WW", at(11, 20), at(13, 21)), ("OK-WW", at(13, 21), at(15, 23))])
    rows = [json.loads(x) for x in e5.state.ledger_path("2026-10-01").read_text(encoding="utf-8").splitlines()]
    for r in rows[1:]:
        r["ok"], r["failed_tasks"] = False, ["OK-WW 运行超时"]
    rows.append({"run_id": "me", "script": "MaaEnd", "started": at(15, 23).isoformat(),
                 "finished": at(17, 40).isoformat(), "ok": True})
    e5.state.ledger_path("2026-10-01").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    check("10-02 早班 limit stays 220", runwatch.planned_minutes(e5, 9, 0, at(9, 0, day=2))[0], 220)
    e5.state.ledger_path("2026-10-01").unlink()

    print("\n[a MaaEnd that did every task and then hung (booked ok) is a timeout, not a clean day (audit 11-08 B-D17)]")
    ledger(e5.state, at(0, 0), [("MAA", at(9, 0), at(9, 18)), ("OK-WW", at(9, 18), at(10, 20)),
                                ("MaaEnd", at(10, 20), at(15, 40))])
    rows = [json.loads(x) for x in e5.state.ledger_path("2026-10-01").read_text(encoding="utf-8").splitlines()]
    rows[-1]["raw"] = {"maaend_result": "MaaEnd 进程超时", "maaend_done_then_hung": True}
    e5.state.ledger_path("2026-10-01").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    check("the hung record reads as a timeout", runwatch._timed_out(rows[-1]), True)
    check("……so 10-01's 400 minutes do not raise 10-02's 早班 limit", runwatch.planned_minutes(e5, 9, 0, at(9, 0, day=2))[0], 220)
    check("an MAA record whose own result says 超时 too", runwatch._timed_out({"ok": True, "raw": {"maa_result": "MAA 进程超时"}}), True)
    check("a plain clean record is not", runwatch._timed_out({"ok": True, "raw": {"maaend_result": "Success!"}}), False)
    e5.state.ledger_path("2026-10-01").unlink()

    def fail_day(state, day, timeout=False):
        """Mark every record of 09-<day> failed, the way a retry day looks in the ledger."""
        p = state.ledger_path(f"2026-09-{day}")
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
        for r in rows:
            r["ok"], r["failed_tasks"] = False, ["OK-WW 运行超时" if timeout else "MAA 未能正确登录 PRTS"]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    print("\n[the real 09-24..09-30 mix: only 26/27/28 clean in the morning -> still 220]")
    e9 = build()
    seed(e9.state)
    for d in (24, 25, 29, 30):
        fail_day(e9.state, d)
    check("three clean days are enough", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (220, 3))

    print("\n[fewer than three clean days: every day that did not time out, never the 180 default]")
    fail_day(e9.state, 26)
    check("2 clean -> the 7 non-timeout days", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (220, 7))
    fail_day(e9.state, 28, timeout=True)
    check("a timed-out day never counts", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (110, 6))
    for d in (24, 25, 26, 27, 29, 30):
        fail_day(e9.state, d, timeout=True)
    check("only when every day timed out -> 180", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (180, 0))

    print("\n[10-01: still running at 13:10 (09:00 + 220 + 30) -> one alarm]")
    real_win, real_snap = eng.config.IS_WINDOWS, eng._automas_snapshot
    try:
        eng.config.IS_WINDOWS = True
        write_log(0)
        eng._automas_snapshot = lambda: snap("运行", "等待")
        run_watch(e5, at(13, 9))
        check("13:09: not yet", alarms(e5), [])
        run_watch(e5, at(13, 10))
        got = alarms(e5)
        check("13:10: one alarm", len(got), 1)
        check("title", bool(got) and got[0][0] == "⏰ 早班超时还没跑完", True)
        check("body has the numbers", bool(got) and "已跑 250 分钟" in got[0][1] and "220 + 30" in got[0][1], True)
        check("body has each script's state", bool(got) and "OK-WW 运行" in got[0][1], True)
        run_watch(e5, at(14, 0))
        check("not repeated the same day", len(alarms(e5)), 1)

        print("\n[the shift already finished, or another queue is the one running -> nothing]")
        e6 = build()
        seed(e6.state)
        eng._automas_snapshot = lambda: snap("异常", "完成")
        run_watch(e6, at(13, 30))
        check("finished queue", alarms(e6), [])
        eng._automas_snapshot = lambda: snap("运行", "等待", queue="someone-else")
        run_watch(e6, at(13, 30))
        check("a task of another queue", alarms(e6), [])
        eng._automas_snapshot = lambda: None
        run_watch(e6, at(13, 30))
        check("AUTO-MAS cannot be asked", alarms(e6), [])

        print("\n[晚班: 21:30 + 19 + 30 = 22:19]")
        e7 = build()
        seed(e7.state)
        eng._automas_snapshot = lambda: snap("等待", "等待", queue=EVENING_UID)
        run_watch(e7, at(22, 18))
        check("22:18: not yet", alarms(e7), [])
        run_watch(e7, at(22, 19))
        check("22:19: alarm", [x[0] for x in alarms(e7)], ["⏰ 晚班超时还没跑完"])

        print("\n[a 晚班 the relay starts late (the phone's run_now) is timed from its own start (11-09 #151)]")
        from ark_relay.features import handle as _handle
        from ark_relay.features import trigger as _trigger
        late_at = datetime(2026, 10, 2, 0, 52, 21, tzinfo=SERVER_TZ)

        def late_engine(noted_at=late_at, created="2026-10-02 00:52:21.335", source="manual_task"):
            e = build()
            seed(e.state)
            APPLOG.write_text(f"{created} | INFO     | 业务调度 | 创建任务: 8f47a684-1111-4222-8333-944455556666, "
                              f"模式: AutoProxy, 触发来源: {source}\n", encoding="utf-8")
            # phone/commands.py notes every run_now it dispatches; one noted hours away is not this task's
            _trigger.note_dispatch(e.cfg.state_dir, "run_now 晚班", now=noted_at)
            return e

        eng._automas_snapshot = lambda: snap("等待", "等待", queue=EVENING_UID)
        el = late_engine()
        run_watch(el, datetime(2026, 10, 2, 0, 52, 28, tzinfo=SERVER_TZ))
        check("00:52:28, 7 s into the late run: no alarm", alarms(el), [])
        run_watch(el, datetime(2026, 10, 2, 1, 41, tzinfo=SERVER_TZ))
        check("01:41, before 00:52:21 + 19 + 30: no alarm", alarms(el), [])
        run_watch(el, datetime(2026, 10, 2, 1, 42, tzinfo=SERVER_TZ))
        got = alarms(el)
        check("01:42, past its own end: one alarm", [x[0] for x in got], ["⏰ 晚班超时还没跑完"])
        body = got[0][1] if got else ""
        check("the body counts from 00:52, not 21:30",
              ("晚班排的是 21:30，这趟 00:52 才开跑，到现在 01:42 还没跑完，已跑 49 分钟" in body,
               "该在 01:41 前结束" in body, "22:19" in body, "重试" in body), (True, True, False, False))
        el = late_engine()
        _handle._mark_alerted(el, "2026-10-02", "超时|MAA|01:10:00")
        run_watch(el, datetime(2026, 10, 2, 1, 42, tzinfo=SERVER_TZ))
        check("a timeout AUTO-MAS retried at 01:10 inside the late run restarts its clock", alarms(el), [])
        run_watch(el, datetime(2026, 10, 2, 1, 59, tzinfo=SERVER_TZ))
        got = alarms(el)
        check("……so it alarms at 01:10 + 19 + 30 = 01:59, saying both",
              bool(got) and "这趟 00:52 才开跑" in got[0][1] and "AUTO-MAS 01:10 重试" in got[0][1]
              and "该在 01:59 前结束" in got[0][1], True)
        el = late_engine(created="2026-10-01 21:30:00.780", source="scheduled_task")
        run_watch(el, at(22, 18))
        run_watch(el, at(22, 19))
        got = alarms(el)
        check("AUTO-MAS's own timer task (created 21:30:00.780) keeps the 21:30 clock",
              bool(got) and "晚班 21:30 开跑" in got[0][1] and "才开跑" not in got[0][1], True)
        el = late_engine(noted_at=late_at - timedelta(hours=2))
        run_watch(el, datetime(2026, 10, 2, 1, 42, tzinfo=SERVER_TZ))
        check("the same late task started by a person: not the shift, no overrun alarm", alarms(el), [])
        write_log(0)

        print("\n[no usable day: the body says the 180 is a default, not a 7-day record (audit s1 #4)]")
        e10 = build()
        eng._automas_snapshot = lambda: snap("运行", "等待")
        run_watch(e10, at(12, 30))
        got = alarms(e10)
        check("no history: 09:00 + 180 + 30 -> alarm at 12:30", len(got), 1)
        check("no history: says there is no record to go by",
              bool(got) and "没有可参考的记录，按 180 分钟算" in got[0][1] and "近 7 天" not in got[0][1], True)
        check("with history: still quotes the 7 days", "近 7 天和前两周同一天里最长 220 分钟跑完" in alarms(e5)[0][1], True)
    finally:
        eng.config.IS_WINDOWS, eng._automas_snapshot = real_win, real_snap

    print("\n[the loop comes back every minute while something runs, never when idle]")
    e8 = build()
    e8._scripts_running = lambda: True
    d = e8.next_deadline(at(10, 0))
    check("next moment one minute away", d and d[0] == at(10, 0) + timedelta(seconds=60), True)
    e8._scripts_running = lambda: False
    d = e8.next_deadline(at(10, 0))
    check("idle: no one-minute wake", bool(d) and d[0] == at(10, 0) + timedelta(seconds=60), False)

    print("\n[a queue time not exactly HH:MM: still watched, or said once (audit row runwatch.py:250)]")
    import logging
    from unittest import mock
    from ark_relay.core import plan as _plan
    from ark_relay.features import runwatch as _rw

    odd = TMP / "odd-automas"
    (odd / "config").mkdir(parents=True)
    odd_doc = {"instances": [{"uid": "q1", "type": "QueueConfig"}]}
    odd_doc["q1"] = {"Info": {"Name": "早班", "TimeEnabled": True},
                     "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": "09:00:00"}},
                                                    "1": {"Info": {"Enabled": True, "Time": "nine"}}},
                                        "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}}}}
    (odd / "config" / "QueueConfig.json").write_text(json.dumps(odd_doc), encoding="utf-8")
    warned = []
    wh = type("W", (logging.Handler,), {"emit": lambda self, r: warned.append(r.getMessage())})(level=logging.WARNING)
    _plan.log.addHandler(wh)
    try:
        getattr(_plan, "_last_error", {}).clear()
        stub = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=odd))
        at = datetime(2026, 10, 10, 12, 0, tzinfo=SERVER_TZ)
        with mock.patch.object(_rw, "planned_minutes", lambda *a: (60, 0)):
            got = [(hhmm, due.strftime("%H:%M")) for _, hhmm, _, due, _, _, _ in _rw.overrun_moments(stub, at)]
            check("09:00:00 is watched as 09:00", got, [("09:00", "09:00")])
            check("an unparsable time is said, naming it", sum("nine" in w for w in warned), 1)
            list(_rw.overrun_moments(stub, at))
            check("same condition again -> no second WARNING", sum("nine" in w for w in warned), 1)
    finally:
        _plan.log.removeHandler(wh)

    _mc.CHECKS.update(_mc_real)


def _part_runwatch_chain_retry():
    """The overrun limit counts a shift whose failed attempt AUTO-MAS retried successfully as clean.
    """
    import json
    from datetime import datetime

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import runwatch

    FIX = fx_dir(RELAY, "fixtures") / "runwatch-chain-1005-1012"

    def morning(day):
        rows = [json.loads(x) for x in (FIX / f"ledger-2026-10-{day:02d}-morning.jsonl").read_text(
            encoding="utf-8").splitlines() if x.strip()]
        return runwatch._chain(rows, datetime(2026, 10, day, 9, 0, tzinfo=SERVER_TZ))

    check("10-12: MaaEnd 10:05 failed, its 10:59 retry succeeded -> clean; "
          "the hand-started OK-WW 11:41-11:49 does not lengthen it", morning(12), (158, True, False))
    check("10-08: three failed MaaEnd attempts, the last (10:35-11:12) succeeded -> clean", morning(8),
          (132, True, False))
    check("10-05: MaaEnd's last record failed (a retry used up by its self-update) -> not clean",
          morning(5), (150, False, False))


def _part_run_limit():
    """Endfield's failure retry limit in AUTO-MAS kept at 1 (run_limit.py)."""
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.notify import route_of
    from ark_relay.features import commands
    from ark_relay.features import queues as R

    Notifier = _Notes

    class Eng:
        def __init__(self):
            self.notifier = Notifier()

    state = {"limit": 1, "up": True, "refuse": "", "writes": 0}

    def fake_backend():
        if not state["up"]:
            return None, ""
        return {"data": {"sid-end": {"Info": {"Name": "MaaEnd"}, "Run": {"RunTimesLimit": state["limit"]}},
                         "sid-ark": {"Info": {"Name": "MAA"}, "Run": {"RunTimesLimit": 3}}}}, ""

    def fake_write(reply, script, path, value):
        state["writes"] += 1
        check("只改终末地的 Run.RunTimesLimit、改成 1", (script, path, value), ("MaaEnd", "Run.RunTimesLimit", 1))
        if state["refuse"]:
            return False, "调度程序没有接受这次修改：" + state["refuse"]
        state["limit"] = value
        return True, "失败重试上限 3 → 1（调度程序已确认）"

    commands._backend_scripts = fake_backend
    commands._script_item_via_api = fake_write
    DAY = datetime(2026, 11, 6, 9, 0, tzinfo=SERVER_TZ)
    NEXT_DAY = datetime(2026, 11, 7, 9, 0, tzinfo=SERVER_TZ)

    print("[是 1：不写、不通知]")
    e = Eng()
    R.step(e, DAY)
    check("没写", state["writes"], 0)
    check("没通知", e.notifier.sent, [])

    print("\n[被改回 3：改回 1，Server酱说一句，同一天只说一次]")
    state["limit"] = 3
    R.step(e, DAY)
    check("改回 1", (state["writes"], state["limit"]), (1, 1))
    check("说了一句，不进群", [(t, a) for t, _, a in e.notifier.sent], [(texts.RUN_LIMIT_RESET, False)])
    check("这句走 Server酱", route_of(texts.RUN_LIMIT_RESET), "info")
    check("说清楚是几改回几", "变成了 3" in e.notifier.sent[0][1] and "改回 1" in e.notifier.sent[0][1], True)
    state["limit"] = 3
    R.step(e, DAY)
    check("同一天又被改回：照改", (state["writes"], state["limit"]), (2, 1))
    check("同一天不再说第二遍", len(e.notifier.sent), 1)
    state["limit"] = 3
    R.step(e, NEXT_DAY)
    check("第二天又被改回：再说一句", len(e.notifier.sent), 2)

    print("\n[调度程序在跑、不收改动：不算失败，下一轮改]")
    e = Eng()
    state.update(limit=3, refuse="正在运行，无法更新配置项", writes=0)
    for _ in range(R.ALARM_AFTER + 1):
        R.step(e, DAY)
    check("每一轮都试了", state["writes"], R.ALARM_AFTER + 1)
    check("在跑时改不了：不报警", e.notifier.sent, [])
    state["refuse"] = ""
    R.step(e, DAY)
    check("跑完那一轮改回去了", state["limit"], 1)
    check("改回来了说一句", [t for t, _, _ in e.notifier.sent], [texts.RUN_LIMIT_RESET])

    print("\n[别的原因连着改不回来：进群一次]")
    e = Eng()
    state.update(limit=3, refuse="写入失败: 连接被拒绝", writes=0)
    for _ in range(R.ALARM_AFTER):
        R.step(e, DAY)
    check("第 3 次进群报警一次", [(t, a) for t, _, a in e.notifier.sent], [(texts.RUN_LIMIT_STUCK, True)])
    check("报警进群", route_of(texts.RUN_LIMIT_STUCK, alert=True), "group")
    check("报警里有调度程序的原话", "连接被拒绝" in e.notifier.sent[0][1], True)
    R.step(e, DAY)
    check("第 4 次不再重复报", len(e.notifier.sent), 1)

    print("\n[读不到调度程序、或者回放 11-05 以前的日子：什么都不做]")
    e = Eng()
    state.update(limit=3, up=False, refuse="", writes=0)
    R.step(e, DAY)
    check("调度程序没开：没写", state["writes"], 0)
    state["up"] = True
    R.step(e, datetime(2026, 10, 13, 8, 55, tzinfo=SERVER_TZ))
    check("11-05 以前的日子：没写", state["writes"], 0)
    check("什么都没说", e.notifier.sent, [])

    print("\n[文案]")
    for s in (texts.run_limit_reset_body("终末地", 3, 1), texts.run_limit_stuck_body("终末地", 3, 1, "x")):
        check("没有英文变量名", "RunTimesLimit" in s, False)

    print("\n[audit 11-08 B-07: an alarm whose send failed is sent again on the next failed tick]")
    e = Eng()
    _down = {"n": 0}

    def _send_fails_once(title, body, *, alert=False, daily=False):
        _down["n"] += 1
        e.notifier.sent.append((title, body, alert))
        return ["群机器人没回"] if _down["n"] == 1 else []

    e.notifier.send = _send_fails_once
    state.update(limit=3, refuse="写入失败: 连接被拒绝", writes=0)
    for _ in range(R.ALARM_AFTER + 2):
        R.step(e, DAY)
    check("the 3rd tick's send failed, the 4th sent it, the 5th is quiet",
          [t for t, _, _ in e.notifier.sent], [texts.RUN_LIMIT_STUCK, texts.RUN_LIMIT_STUCK])


def _part_run_probe():
    """run-probe.py (watch-run.sh's probe on the game machine): a MaaEnd update install is UPD, not FAIL.
    """
    import contextlib
    import importlib.util
    import io
    import json

    ROOT = Path(__file__).resolve().parents[2]
    FIX = fx_dir(Path(__file__), "fixtures") / "automas-runprobe"
    spec = importlib.util.spec_from_file_location("run_probe", ROOT / "scripts" / "windows" / "run-probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    def lines(day):
        probe.HISTORY = str(FIX)
        out = io.StringIO()
        sys.argv = ["run-probe.py", day]
        with contextlib.redirect_stdout(out):
            probe.main()
        rows = {}
        for ln in out.getvalue().splitlines():
            tag, stem, kind, ok, res = ln.split("|", 4)
            rows[stem] = (tag, kind, ok, json.loads(res))
        return rows

    rows = lines("2026-10-13")
    print("[the 10-13 MaaEnd update record]")
    check("UPD, ok 1, not a FAIL", rows.get("MaaEnd-05-59-12"), ("UPD", "MaaEnd", "1", "[更新] Success!"))
    print("[real runs are judged as before]")
    check("MaaEnd Success!: REC ok", rows.get("MaaEnd-05-13-19"), ("REC", "MaaEnd", "1", "Success!"))
    check("MaaEnd partial failure: REC fail", rows.get("MaaEnd-05-29-15", ("",) * 4)[:3], ("REC", "MaaEnd", "0"))
    check("MAA Success!: REC ok", rows.get("MAA-05-00-23", ("",) * 4)[:3], ("REC", "MAA", "1"))
    print("[the same rule as the relay's collector]")
    check("「[更新] 跳过更新」 is not a run either", probe.judge("MaaEnd", "[更新] 跳过更新"), ("UPD", "1"))
    check("a failed update is a failed record", probe.judge("MaaEnd", "[更新] MaaEnd 更新失败，已停止后续任务: x"), ("REC", "0"))
    check("a stage-labelled success is a success", probe.judge("MaaEnd", "[日常] Success!"), ("REC", "1"))
    check("an unknown label is a failure (as collector._split_stage)", probe.judge("MaaEnd", "[新阶段] Success!"), ("REC", "0"))
    sys.path.insert(0, str(ROOT / "relay"))
    from ark_relay.core import collector
    check("the labels match collector.py", (probe.STAGE_LABELS, probe.UPDATE_LABEL, probe.UPDATE_FINE),
          (collector._STAGE_LABELS, collector._UPDATE_LABEL, collector._UPDATE_FINE))


def _part_same_weekday():
    """The shift's planned end counts the same weekday one and two weeks back when that day was clean (#155, 11-09).
    """
    import json
    import types
    from datetime import datetime, timedelta

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.features import runwatch

    em = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=None), state=State(tmpdir()))

    ledger = _write_ledger

    print("[11-09 (Monday): the same weekday back counts when clean - #155, 11-02 was not clean, 10-26 was]")
    mins = {(10, 26): (142, True), (10, 27): (56, True), (10, 28): (63, True), (10, 29): (87, True),
            (10, 30): (65, True), (10, 31): (62, True), (11, 1): (62, True), (11, 2): (151, False),
            (11, 3): (80, False), (11, 4): (81, True), (11, 6): (68, True), (11, 7): (80, True), (11, 8): (60, True)}
    for (mo, d), (m, ok) in mins.items():
        start = datetime(2026, mo, d, 9, 0, 50, tzinfo=SERVER_TZ)
        ledger(em.state, start, [("MAA", start, start + timedelta(minutes=10)),
                                 ("OK-WW", start + timedelta(minutes=11), start + timedelta(minutes=m))])
        if not ok:
            pth = em.state.ledger_path(start.strftime("%Y-%m-%d"))
            rows = [json.loads(x) for x in pth.read_text(encoding="utf-8").splitlines()]
            rows[-1]["ok"], rows[-1]["failed_tasks"] = False, ["OK-WW 没打完周本"]
            pth.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monday = datetime(2026, 11, 9, 9, 0, tzinfo=SERVER_TZ)
    check("Monday 11-09: 10-26's clean 142 (14 days back) is the limit, not 11-04's 81",
          runwatch.planned_minutes(em, 9, 0, monday), (142, 4))   # 4 clean days in 11-02..11-08: 04, 06, 07, 08
    check("……a 7-day window alone (11-02 not clean) would have given 81",
          max(m for (mo, d), (m, ok) in mins.items() if ok and datetime(2026, mo, d, tzinfo=SERVER_TZ) >= datetime(2026, 11, 2, tzinfo=SERVER_TZ)), 81)
    check("Tuesday 11-10: last Tuesday 11-03 was not clean, 10-27's 56 is below the week's 81",
          runwatch.planned_minutes(em, 9, 0, datetime(2026, 11, 10, 9, 0, tzinfo=SERVER_TZ))[0], 81)

    print("\n[a Monday that raised 「队列超时」 and still finished clean is the next Monday's limit (#176)]")
    from unittest import mock
    from ark_relay.features import handle
    e2 = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=None), state=State(tmpdir()))
    week = {(11, 2): (151, False), (11, 9): (123, True), (11, 10): (60, True), (11, 11): (62, True),
            (11, 12): (65, True), (11, 13): (58, True), (11, 14): (58, True), (11, 15): (59, True)}
    for (mo, d), (m, ok) in week.items():
        start = datetime(2026, mo, d, 9, 0, 50, tzinfo=SERVER_TZ)
        ledger(e2.state, start, [("MAA", start, start + timedelta(minutes=10)),
                                 ("OK-WW", start + timedelta(minutes=11), start + timedelta(minutes=m))])
        if not ok:
            pth = e2.state.ledger_path(start.strftime("%Y-%m-%d"))
            rows = [json.loads(x) for x in pth.read_text(encoding="utf-8").splitlines()]
            rows[-1]["ok"], rows[-1]["failed_tasks"] = False, ["OK-WW 没打完周本"]
            pth.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monday16 = datetime(2026, 11, 16, 9, 0, tzinfo=SERVER_TZ)
    with mock.patch.object(runwatch.plan, "schedule", lambda _dir: [{"name": "早班"}]):
        check("before the alarm mark: 11-09's 123 is the Monday limit", runwatch.planned_minutes(e2, 9, 0, monday16), (123, 7))
        handle._mark_alerted(e2, "2026-11-09", "队列超时|早班|09:00")
        check("11-09 raised the alarm and was clean: still Monday 11-16's limit (was 65)",
              runwatch.planned_minutes(e2, 9, 0, monday16), (123, 6))
        check("……but not a weekday's: Tuesday 11-10 keeps its own days (no clean one yet in its window -> fallback)",
              runwatch.planned_minutes(e2, 9, 0, datetime(2026, 11, 10, 9, 0, tzinfo=SERVER_TZ)), (180, 0))
        check("……and Sunday 11-15's limit is the week's 65, not the alarmed Monday's 123",
              runwatch.planned_minutes(e2, 9, 0, datetime(2026, 11, 15, 9, 0, tzinfo=SERVER_TZ))[0], 65)
        handle._mark_alerted(e2, "2026-11-02", "队列超时|早班|09:00")
        check("an alarmed Monday that was not clean (11-02) still does not count",
              runwatch._past_run(e2, monday16, 14, 9, 0, ["早班"], alarmed_counts=True), (151, False))
        pth = e2.state.ledger_path("2026-11-09")
        rows = [json.loads(x) for x in pth.read_text(encoding="utf-8").splitlines()]
        rows[-1]["raw"] = {"general_result": "OK-WW 运行超时"}
        pth.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        check("an alarmed Monday that timed out never counts", runwatch.planned_minutes(e2, 9, 0, monday16), (65, 6))

    print("\n[#176, the 11-16 timeline: once the queue's planned minutes are spent, the script whose turn it is has its own]")
    e3 = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=None), state=State(tmpdir()))

    def shift_day(d, okww, maaend, okww_ok=True):
        t0 = datetime(2026, 11, d, 9, 0, 30, tzinfo=SERVER_TZ)
        a = t0 + timedelta(minutes=17)
        b = a + timedelta(minutes=2) + timedelta(minutes=okww)
        ledger(e3.state, t0, [("MAA", t0, a), ("OK-WW", a + timedelta(minutes=2), b),
                              ("MaaEnd", b + timedelta(minutes=3), b + timedelta(minutes=3 + maaend))])
        if not okww_ok:
            pth = e3.state.ledger_path(t0.strftime("%Y-%m-%d"))
            rows = [json.loads(x) for x in pth.read_text(encoding="utf-8").splitlines()]
            rows[1]["ok"], rows[1]["failed_tasks"] = False, ["没进游戏"]
            pth.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    for d, okww, maaend, ok in ((10, 11, 25, True), (11, 11, 23, True), (12, 11, 64, False), (13, 11, 24, True),
                                (14, 11, 23, True), (15, 11, 26, True)):
        shift_day(d, okww, maaend, ok)
    due16 = datetime(2026, 11, 16, 9, 0, tzinfo=SERVER_TZ)
    kinds = ["MAA", "OK-WW", "MaaEnd"]
    check("MaaEnd's own longest clean run of the week is Thursday's 64 (its own record was clean that day)",
          runwatch.script_minutes(e3, "MaaEnd", 9, 0, due16), 64)
    check("鸣潮's own: 11 (Thursday's failed one does not count)", runwatch.script_minutes(e3, "OK-WW", 9, 0, due16), 11)
    check("a script never recorded: nothing to go by", runwatch.script_minutes(e3, "X", 9, 0, due16), None)
    limit16 = runwatch.planned_minutes(e3, 9, 0, due16)[0]
    check("the queue's limit that Monday is a weekday's (no clean Monday, Thursday not clean)", limit16 < 70, True)
    queue_end = due16 + timedelta(minutes=limit16 + runwatch.OVERRUN_SLACK_MIN)

    def rows16(*rows):
        return [{"script": s_, "started": a.isoformat(), "finished": b.isoformat(), "ok": True} for s_, a, b in rows]

    def hm(h, m, sec=0):
        return datetime(2026, 11, 16, h, m, sec, tzinfo=SERVER_TZ)

    at_1035 = rows16(("MAA", hm(9, 0, 30), hm(9, 17)), ("OK-WW", hm(9, 19), hm(10, 12, 48)))
    hold, turn = runwatch.turn_deadline(e3, due16, due16, queue_end, kinds, at_1035)
    check("11-16 at 10:35: it is MaaEnd's turn since 鸣潮's record ended at 10:12:48, its own day is 64",
          turn, ("MaaEnd", hm(10, 12, 48), 64))
    check("……so both alarms wait until 10:12:48 + 64 + 30 = 11:46:48, and MaaEnd finished at 11:19: no alarm that day",
          (hold, hold > hm(11, 19, 14)), (hm(11, 46, 48), True))
    e3.state.ledger_path("2026-11-12").unlink()
    hold, turn = runwatch.turn_deadline(e3, due16, due16, queue_end, kinds, at_1035)
    check("without a gathering day in its history (longest 26): 10:12:48 + 26 + 30 = 11:08:48, before its 11:19 end",
          (hold, turn[2]), (hm(11, 8, 48), 26))
    shift_day(12, 11, 64, False)
    early = rows16(("MAA", hm(9, 0, 30), hm(9, 17)))
    check("never earlier than the queue's own deadline: 鸣潮's turn since 09:17, 11 + 30 ends before it",
          runwatch.turn_deadline(e3, due16, due16, queue_end, kinds, early), (queue_end, None))
    check("every script recorded: the queue's deadline",
          runwatch.turn_deadline(e3, due16, due16, queue_end, kinds, at_1035 + rows16(("MaaEnd", hm(10, 15), hm(11, 19)))),
          (queue_end, None))
    check("no record yet: the first script's turn runs from the shift's start",
          runwatch.own_turn(e3, due16, due16, kinds, []), ("MAA", due16, 17))
    by_hand = rows16(("MAA", hm(9, 0, 30), hm(9, 17)))
    by_hand.append({"script": "OK-WW", "started": hm(9, 20).isoformat(), "finished": hm(9, 40).isoformat(), "ok": True,
                    "raw": {"hand_started": True}})
    check("a run somebody started by hand is not the queue's record", runwatch.own_turn(e3, due16, due16, kinds, by_hand)[:2],
          ("OK-WW", hm(9, 17)))
    with mock.patch.object(runwatch, "script_minutes", lambda *a: 900):
        check("capped at the shift's start + 180 + 30 however long the script's own day was",
              runwatch.turn_deadline(e3, due16, due16, queue_end, kinds, at_1035)[0],
              due16 + timedelta(minutes=runwatch.SHIFT_CAP_MIN + runwatch.OVERRUN_SLACK_MIN))
    check("the chain reads as before the split: 11-10 took 58 minutes, clean, no timeout",
          runwatch._chain(e3.state.read_ledger("2026-11-10"), datetime(2026, 11, 10, 9, 0, tzinfo=SERVER_TZ)), (58, True, False))


def _part_missed_runs_main():
    """A queue that was due and produced nothing must alarm - and must not alarm
when the machine simply was not awake for it.
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

    for title, boot, started, now, label, want in (
            # the machine WAS awake for 21:30, but this process only started at 21:33
            ("[the swallowed alarm] selfupdate restarted the relay past the queue time",
             at(21, 20), at(21, 33), at(22, 0), "alarms", 1),
            # powered on well after the queue
            ("\n[machine really was off] must stay quiet", at(22, 40), at(22, 42), at(23, 10), "silent", 0),
            ("\n[not late yet] grace is 25 minutes", at(21, 20), at(21, 22), at(21, 50), "silent at +20min", 0)):
        print(title)
        reset()
        BOOT[0], E._started_at = boot, started
        E._check_missed_runs(now)
        check(label, len(sent), want)
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
    from ark_relay.features import modes as _modes
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
    """「🔌 晚班 没有运行」 follows AUTO-MAS v5.7's weekday rules."""
    #!/usr/bin/env python3

    import os
    import shutil
    from datetime import datetime

    FX = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11"
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

    def at(day: int, hh: int, mm: int) -> datetime:
        return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)   # 10-13 is a Tuesday

    edit = _doc_editor(PRISTINE, QC)

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


def _part_debug_window():
    import os
    import tempfile
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import modes
    from ark_relay.features.commands import apply_command
    from ark_relay.core.statestore import StateStore
    from ark_relay.core.config import SERVER_TZ

    def at(s):
        return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=SERVER_TZ)

    def main(tmp: Path):
        # The exact case from the incident.
        ok, msg = modes.set_debug(tmp, 1, now=at("2026-08-22 21:00"))
        check("设置成功", ok, True)
        check("到期时刻 = 08:40 前 10 分钟",
              modes.debug_until(tmp), "2026-08-23 08:30")

        for label, when, want in (("当晚 23:30 仍然生效", "2026-08-22 23:30", True),
                                  ("跨过午夜 00:10 仍然生效（旧实现在这里失效）", "2026-08-23 00:10", True),
                                  ("次日 08:29 仍然生效", "2026-08-23 08:29", True),
                                  ("次日 08:31 已经失效", "2026-08-23 08:31", False)):
            check(label, modes.debug_active(tmp, at(when)), want)

        # Set in the morning -> the evening power-on is the next boundary.
        modes.set_debug(tmp, 1, now=at("2026-08-23 10:00"))
        check("上午设置 -> 到 21:20 前 10 分钟",
              modes.debug_until(tmp), "2026-08-23 21:10")

        # Two cycles sits out one more power-on.
        modes.set_debug(tmp, 2, now=at("2026-08-22 21:00"))
        check("cycles=2 跨到晚班开机前",
              modes.debug_until(tmp), "2026-08-23 21:10")

        # Legacy bare-date files on disk must keep meaning end-of-day, not "off".
        StateStore(tmp).set("modes", "debug_until", "2026-08-22")
        check("旧格式当天 23:59 仍生效",
              modes.debug_active(tmp, at("2026-08-22 23:59")), True)
        check("旧格式次日 00:01 失效",
              modes.debug_active(tmp, at("2026-08-23 00:01")), False)

        # Garbage fails towards ON: the wrong failure powers off a box in use.
        StateStore(tmp).set("modes", "debug_until", "???")
        check("值损坏时保守取生效",
              modes.debug_active(tmp, at("2026-08-23 12:00")), True)

        # Off removes it outright.
        modes.set_debug(tmp, off=True)
        check("关闭后不再生效",
              modes.debug_active(tmp, at("2026-08-22 22:00")), False)

        store = StateStore(tmp)
        store.set("modes", "shutdown_skipped", "2026-10-14:3")
        modes.set_debug(tmp, off=True)
        check("test-off keeps a skip the mark recorded",
              store.get("modes", "shutdown_skipped"), "2026-10-14:3")
        modes.set_debug(tmp, off=True, release_skip=True)
        check("off by hand releases it", store.get("modes", "shutdown_skipped"), None)
        store.set("modes", "shutdown_skipped", "2026-10-14:3|debug")
        modes.set_debug(tmp, off=True)
        check("debug mode's own skip is released either way", store.get("modes", "shutdown_skipped"), None)
        os.environ["ARK_STATE_DIR"] = str(tmp)
        store.set("modes", "shutdown_skipped", "2026-10-14:3")
        ok, _ = apply_command({"action": "debug_mode", "off": True, "confirmed": True})
        check("the debug_mode off order releases the mark's skip",
              (ok, StateStore(tmp).get("modes", "shutdown_skipped")), (True, None))

    with tempfile.TemporaryDirectory() as d:
        main(Path(d))


if __name__ == "__main__":
    sys.exit(run_parts([_part_stagegate_main, _part_stagegate_users, _part_stage_set_refused, _part_stagegate_hooks, _part_plan_after_accomplish, _part_plan_collect_days_master, _part_plan_queue_weekdays, _part_plan_silent, _part_plan_stage_modes, _part_plan_startup_mode, _part_queue_apply_backend, _part_queue_apply_runnow, _part_queue_names, _part_queue_rows_times, _part_queue_skip_holders, _part_queue_skip_partial, _part_queue_skip_partial_receipt, _part_queue_skip_scripts, _part_dayroll_skips, _part_due_weekdays_everywhere, _part_shift_clock_after_retry, _part_shiftcheck, _part_overdue_after_update_rerun, _part_next_deadline, _part_next_plan_imports, _part_next_queue_weekdays, _part_dispatch_guard_idle, _part_dispatch_guard_self, _part_dispatch_guard_silent, _part_dispatch_guard_test_debug, _part_dispatch_note_timing, _part_runwatch_main, _part_runwatch_chain_retry, _part_run_limit, _part_run_probe, _part_same_weekday, _part_missed_runs_main, _part_missed_weekdays, _part_debug_window]))
