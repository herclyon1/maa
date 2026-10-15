"""A power-off opportunity belongs to the moment a shift finished, not to the whole boot.

The user's rule of 2026-10-10 18:31 (Tokyo), quoted verbatim in USER-SWITCHES.txt at
shutdown.py:_say_if_moment_passed: only right after a morning / evening shift finished.

2026-10-15 (Endfield maintenance day, relay.log on the machine, Beijing time): the morning
shift ran MAA and OK-WW (MaaEnd skipped in the queue for the maintenance) and finished at
09:3x. The deferred client update and the MaaEnd make-up then held the power-off
(09:33 ... 13:16); 13:01:52 the make-up was cancelled, 13:06:59 「不关机：游戏客户端正在更新或重跑」,
13:17:18 the update found the launcher at 「开始游戏」, and at 13:18:00 the relay said
「本轮已处理完毕，60 秒后关机」 - hours after the shift. The whitelist (_not_shift) never
expired, and the update / make-up gates only deferred the go.

The times below are that day's; the ledger rows are modelled (start / end per relay.log),
the queue time 08:50 stands for the morning shift's.
"""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
STATE = TMP / "state"
STATE.mkdir()
(TMP / "history").mkdir()
ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
NOT_THURSDAY = [d for d in ALL_DAYS if d != "Thursday"]     # 2026-10-15 is a Thursday
doc = {"instances": [{"uid": "m"}, {"uid": "e"}]}
for uid, name, t in (("m", "早班", "08:50"), ("e", "晚班", "21:30")):
    doc[uid] = {"Info": {"Name": name, "TimeEnabled": True, "AfterAccomplish": "NoAction"},
                "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                   "QueueItem": {
                                       "i1": {"Info": {"ScriptId": "s1"}},
                                       "i2": {"Info": {"ScriptId": "s2"}},
                                       # the maintenance skip: today's weekday dropped from the item
                                       "i3": {"Info": {"ScriptId": "s3"}, "Schedule": {"Days": NOT_THURSDAY}}}}}
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
scripts = {"instances": [{"uid": "s1"}, {"uid": "s2"}, {"uid": "s3"}]}
for uid, path in (("s1", "D:\\MAA"), ("s2", "D:\\ark\\okww"), ("s3", "D:\\MaaEnd")):
    scripts[uid] = {"Info": {"Name": uid, "Path": path}, "SubConfigsInfo": {}}
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts), encoding="utf-8")
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                  ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng                     # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config          # noqa: E402
from ark_relay.core.ledger import State                      # noqa: E402
from ark_relay.core.statestore import StateStore             # noqa: E402
from ark_relay.features.alarm import errwatch                # noqa: E402
from ark_relay.features.evidence import error_evidence       # noqa: E402
from ark_relay.features.makeup import collect_retry, makeup  # noqa: E402
from ark_relay.features.phone import heartbeat               # noqa: E402
from ark_relay.features.shutdown import shutdown             # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Notes:
    def send(self, title, body="", **kw):
        return []


def at(hh, mm, ss=0, day=15):
    return datetime(2026, 10, day, hh, mm, ss, tzinfo=SERVER_TZ)


MORNING = [("MAA-1", "MAA", "arknights", at(8, 50, 40), at(9, 9, 12), True),
           ("OK-WW-1", "OK-WW", "wuwa", at(9, 9, 40), at(9, 31, 5), True)]
EVENING = [("MAA-2", "MAA", "arknights", at(21, 30, 40), at(21, 49, 2), True),
           ("OK-WW-2", "OK-WW", "wuwa", at(21, 49, 30), at(22, 8, 10), True)]


def ledger(rows):
    (STATE / "ledger-2026-10-15.jsonl").write_text("\n".join(
        json.dumps({"run_id": f"2026-10-15/x/{r}", "script": s, "user": u, "started": a.isoformat(),
                    "finished": b.isoformat(), "ok": ok, "failed_tasks": []})
        for r, s, u, a, b, ok in rows) + "\n", encoding="utf-8")


def marker(result, dispatched):
    d = STATE / "makeup"
    d.mkdir(exist_ok=True)
    (d / "2026-10-15.json").write_text(json.dumps(
        {"MaaEnd": {"dispatched_at": dispatched.isoformat(), "result": result, "tries": 1,
                    "tasks": [makeup.WHOLE_MAAEND]}}), encoding="utf-8")


cfg = Config()
e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
e._scripts_running = lambda: False
e.state.report_sent = lambda d: True
BOOT = [at(8, 35)]
e._boot_time = lambda now: BOOT[0]
UPDATING = [False]
e._deferred_update_busy = lambda: UPDATING[0]
powered = []
e._power_off = lambda: powered.append(1) or True     # never the real `shutdown` on this machine
e._before_shutdown = None
saved = (error_evidence.upload_daily_logs, collect_retry.maybe_run)
error_evidence.upload_daily_logs = lambda cfg, **kw: {}
collect_retry.maybe_run = lambda eng_, now: False


def fresh(boot=None, started=None):
    """A new relay process on boot `boot` that saw the shift's records land."""
    BOOT[0] = boot or at(8, 35)
    e._started_at = started or at(8, 35, 20)
    e._handled_any = True
    e._shutdown_issued = False
    e._shutdown_issued_at = None
    e._last_wait_note = ""
    UPDATING[0] = False
    powered.clear()
    errwatch.clear_stopping()
    for k in ("shutdown_forfeit", "relay_poweroff", "relay_poweroff_why"):
        e.state.store.pop("marks", k)
    shutil.rmtree(STATE / "makeup", ignore_errors=True)


def tick(now):
    shutdown._maybe_shutdown(e, now)
    return shutdown.decide(e, now)


print("[2026-10-15: shift done, update / make-up held the power-off, then let go: stays on]")
fresh()
ledger(MORNING)
UPDATING[0] = True                                   # 09:33 the deferred client update starts
v = tick(at(9, 33))
check("09:33 the update holds the power-off", v.code, "not-shift")
check("…the hold is kept on disk (a relay restart keeps it)",
      isinstance(e.state.store.get("marks", "shutdown_forfeit"), dict), True)
marker(makeup.DISPATCHED, at(12, 58))                # the MaaEnd make-up goes out
UPDATING[0] = False
tick(at(12, 59))
marker(makeup.GAVE_UP, at(12, 58))                   # 13:01:52 cancelled by the queue skip
tick(at(13, 1, 52))
UPDATING[0] = True
tick(at(13, 6, 59))
UPDATING[0] = False                                  # 13:17:18 the launcher shows 「开始游戏」
for now in (at(13, 17, 18), at(13, 18), at(13, 30), at(18, 0)):
    v = tick(now)
check("13:17 .. 18:00 after the update: never powered off", powered, [])
check("…the decision says it is not right after a shift", v.code, "not-shift")
check("…in his terms", v.reason.startswith("不是早班/晚班跑完，不关机"), True)
check("…names the shift and what held it", ("早班" in v.reason, "游戏客户端正在更新" in v.reason), (True, True))

print("\n[a relay restart after the hold: the opportunity stays gone]")
e._handled_any = False
shutdown.note_handled(e, at(9, 31, 30))              # the earlier process saw the shift land
e._started_at = at(13, 0)
v = tick(at(13, 20))
check("restarted 13:00 on the same boot -> not-shift, no power-off", (v.code, powered), ("not-shift", []))
# The after-shift check still counts the shift as finished: the hold took only its
# power-off. Before, a restart after the hold logged 「收工体检（早班）这班没查」 for a shift
# that had been checked (daysim 10-09, 10:29:21 after the 10:19 restart).
from ark_relay.features.selfcheck import shiftcheck   # noqa: E402
check("shiftcheck: the held shift is a finished shift", (shiftcheck.finished_shift(e, at(13, 20)) or {}).get("name"), "早班")
e.state.store.pop("marks", "handled_boot")

print("\n[the evening shift on the same boot is a new opportunity: go]")
ledger(MORNING + EVENING)
e._handled_any = True
e._started_at = at(8, 35, 20)
e._last_wait_note = ""
v = shutdown.decide(e, at(22, 9))
check("22:09 after the evening shift -> go", v.code, "go")

print("\n[a plain morning: the shift finishes, nothing holds it -> powered off]")
fresh()
ledger(MORNING)
check("09:32 -> power-off issued", (shutdown._maybe_shutdown(e, at(9, 32)), powered), (True, [1]))

print("\n[make-up held it (no update), then the make-up landed: stays on]")
fresh()
ledger(MORNING)
marker(makeup.DISPATCHED, at(9, 32))
v = tick(at(9, 33))
check("09:33 the make-up holds it", v.code, "not-shift")
marker(makeup.OK, at(9, 32))
ledger(MORNING + [("MaaEnd-mk", "MaaEnd", "endfield", at(9, 34), at(9, 52), True)])
v = tick(at(9, 53))
check("09:53 the make-up landed -> still no power-off", (v.code, powered), ("not-shift", []))

print("\n[the update thread masked by another hold (an alarm not pushed yet) still counts]")
fresh()
ledger(MORNING)
UPDATING[0] = True
e._recovered = [object()]                            # 「还有告警没推出去」 comes before 「updating」
tick(at(9, 33))
e._recovered = []
UPDATING[0] = False
v = tick(at(9, 50))
check("released 09:50 -> not-shift, no power-off", (v.code, powered), ("not-shift", []))

print("\n[why the machine went off: kept with the relay's power-off, carried on the last COS beat]")
fresh()
ledger(MORNING)
shutdown._maybe_shutdown(e, at(9, 32))
why = e.state.store.get("marks", "relay_poweroff_why") or {}
check("the reason names the shift", "早班" in str(why.get("why")), True)
check("…its time and when it finished", ("08:50" in str(why.get("why")), "09:31" in str(why.get("why"))), (True, True))
now_real = datetime.now(tz=SERVER_TZ)
e.state.store.set("marks", "relay_poweroff", now_real.isoformat())   # as if issued just now
e.state.store.set("marks", "relay_poweroff_why", dict(why, at=now_real.isoformat()))


class Cos:
    pass


puts = []
saved_put = heartbeat.cos_put
heartbeat.cos_put = lambda cos, key, body, timeout: puts.append(json.loads(body)) or ""
hb = heartbeat.Heartbeat("t0pic", STATE, post=lambda b, t: None, cos=Cos())
hb.cos_beat(bye=True)
off = (puts[-1] if puts else {}).get("off") or {}
check("the bye beat says the relay powered off", off.get("by"), "relay")
check("…and why", off.get("why"), why.get("why"))
check("…when (seconds, as the beat's own 'at')", off.get("at"), int(now_real.timestamp()))
check("…the fields the App reads are unchanged", {"at", "every", "cos_every", "bye"} <= set(puts[-1]), True)
hb.cos_beat()
check("an ordinary beat carries no 'off'", "off" in puts[-1], False)
e.state.store.pop("marks", "relay_poweroff")
errwatch.mark_os_shutdown()
hb.cos_beat(bye=True)
check("Windows shutting down without the relay's command -> by windows", puts[-1].get("off", {}).get("by"), "windows")
errwatch._os_shutdown.clear()
hb.cos_beat(bye=True)
check("a service stop, the machine staying up -> by service", puts[-1].get("off", {}).get("by"), "service")
heartbeat.cos_put = saved_put
check("StateStore reads the new marks back", StateStore(STATE).get("marks", "relay_poweroff_why") is not None, True)

error_evidence.upload_daily_logs, collect_retry.maybe_run = saved
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
