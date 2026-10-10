"""Where the stage gate is wired in: setting a stage, and what a stage-gate pull means
for the missed-run checks and the shutdown decision.

2026-10-10 04:25 the stage was set to YW-4, a stage MAA had no navigation for
(resource/tasks/Stages/YW.json lacked the key; asst.log in _stagegate_fx.py), and
the 09:00 MAA run stopped at its first task. Setting such a stage is refused now.
A queue run the gate took MAA out of is not "a run that never happened": the missed
checks stay quiet about MAA for it, and an MAA-only shift that was pulled lets the
machine power off instead of waiting for a run that was cancelled on purpose.
"""
import importlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
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
from ark_relay import commands  # noqa: E402
from ark_relay.config import Config, SERVER_TZ  # noqa: E402
from ark_relay import shutdown  # noqa: E402
from ark_relay.core import State  # noqa: E402
from ark_relay.engine import Engine  # noqa: E402
from ark_relay.notify import Notifier  # noqa: E402

try:
    sg = importlib.import_module("ark_relay.stagegate")
except ImportError:
    sg = None

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


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
import inspect  # noqa: E402
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
_rep = (Path(__file__).resolve().parents[1] / "ark_relay" / "report.py").read_text(encoding="utf-8")
check("the daily report template appends the gate's lines", "stagegate.report_line(eng.cfg.state_dir, day)" in _rep,
      True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
