"""A script the morning shift never recorded does not keep the evening shift from powering off
(audit 11-08 A-16; dispatch relay-opt-round4-1108 R4-01; shutdown._current_shift).

The schedule is the machine's (docs/CONFIG.md): 早班 09:00 MAA, MaaEnd, OK-WW; 晚班 21:30 MAA
only. A boot the power-off skipped (debug mode, 「下次跑完不关机」) holds both shifts. Before:
_shift_queues gave every queue due since the boot, and an OK-WW the morning never recorded
(no evening record stands in for it: the evening queue runs MAA only) kept every decision of
the evening at 「等排期的那趟跑完再判关机（队列「早班」还差 OK-WW）」 - the machine stayed on.

Pinned here:
* 21:50, the evening's MAA recorded: go, and the after-shift check counts the evening shift;
* the evening's MAA not recorded yet: still waiting, naming 晚班 (not 早班);
* before the evening is due, the morning still missing OK-WW: still waiting on 早班 (unchanged);
* _current_shift: queues of one shift (minutes apart) stay together; 12.5 hours apart do not.
"""
import json
import os
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
doc = {"instances": [{"uid": "m"}, {"uid": "e"}]}
for uid, name, t, items in (("m", "早班", "09:00", ("s1", "s3", "s2")), ("e", "晚班", "21:30", ("s1",))):
    doc[uid] = {"Info": {"Name": name, "TimeEnabled": True, "AfterAccomplish": "NoAction"},
                "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                   "QueueItem": {f"i{n}": {"Info": {"ScriptId": sid}} for n, sid in enumerate(items)}}}
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
from ark_relay.features.selfcheck import shiftcheck           # noqa: E402
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


def at(hh, mm, ss=0):
    return datetime(2026, 11, 7, hh, mm, ss, tzinfo=SERVER_TZ)


# The morning: MAA and MaaEnd recorded, OK-WW never (crashed before its record).
MORNING = [("MAA-1", "MAA", "arknights", at(9, 0, 40), at(9, 19, 12)),
           ("MaaEnd-1", "MaaEnd", "endfield", at(9, 19, 40), at(9, 50, 5))]
EVENING = [("MAA-2", "MAA", "arknights", at(21, 30, 40), at(21, 49, 2))]


def ledger(rows):
    (STATE / "ledger-2026-11-07.jsonl").write_text("\n".join(
        json.dumps({"run_id": f"2026-11-07/x/{r}", "script": s, "user": u, "started": a.isoformat(),
                    "finished": b.isoformat(), "ok": True, "failed_tasks": []})
        for r, s, u, a, b in rows) + "\n", encoding="utf-8")


cfg = Config()
e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
e._scripts_running = lambda: False
e.state.report_sent = lambda d: True
e._boot_time = lambda now: at(8, 45)
e._deferred_update_busy = lambda: False
e._started_at = at(8, 45, 20)
e._handled_any = True

print("[早班漏了 OK-WW，机器没关；晚班 MAA 跑完：按晚班判，关机]")
ledger(MORNING + EVENING)
v = shutdown.decide(e, at(21, 50))
check("21:50 -> go", (v.code, v.reason), ("go", "本轮已处理完毕"))
check("收工体检算的是晚班", (shiftcheck.finished_shift(e, at(21, 50)) or {}).get("name"), "晚班")
check("……早班的超时提醒照旧看得到它（_shift_overdue 还看全部队列）",
      sorted(q["name"] for q in shutdown._shift_queues(e, at(21, 50), at(8, 45))), ["早班", "晚班"])

print("\n[晚班自己还没记录：照旧等，说的是晚班]")
ledger(MORNING)
v = shutdown.decide(e, at(21, 45))
check("21:45 -> shift-running", v.code, "shift-running")
check("……等的是晚班的 MAA，不是早班的 OK-WW", ("晚班" in v.reason, "早班" in v.reason), (True, False))

print("\n[晚班还没到点：早班缺 OK-WW 照旧等（和以前一样）]")
v = shutdown.decide(e, at(15, 0))
check("15:00 -> shift-running on 早班", (v.code, "早班" in v.reason and "OK-WW" in v.reason), ("shift-running", True))

print("\n[_current_shift：同一班几分钟的不拆开，隔十二个半小时的拆开]")
q = lambda name, h, m: {"name": name, "due": at(h, m), "kinds": []}  # noqa: E731
check("09:00 与 09:05 是一班", [x["name"] for x in shutdown._current_shift([q("a", 9, 0), q("b", 9, 5)])], ["b", "a"])
check("09:00 与 21:30：只留 21:30", [x["name"] for x in shutdown._current_shift([q("早班", 9, 0), q("晚班", 21, 30)])],
      ["晚班"])
check("空的还是空的", shutdown._current_shift([]), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
