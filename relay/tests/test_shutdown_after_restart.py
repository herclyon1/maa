"""A relay restarted after the shift does not power the machine off.

2026-10-01: the morning shift closed at 17:27:43, the relay was redeployed at
17:41, and the new process judged 「本次开机还没有跑完任何队列」. From then until
2026-10-10 the ledger (_ran_since_boot) let it power off anyway. The user, 2026-10-10
18:31 (Tokyo), quoted in USER-SWITCHES.txt at shutdown.py:_say_if_moment_passed: a decision
made by a process that did not see the shift's records land is not the one right after
the shift, so it is 「not-shift」 and the machine stays on (daily report only).
The ledger below is that day's, copied from the machine (start / end as written).
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
for uid, name, t in (("m", "早班", "09:00"), ("e", "晚班", "21:30")):
    doc[uid] = {"Info": {"Name": name, "TimeEnabled": True, "AfterAccomplish": "NoAction"},
                "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                   "QueueItem": {i: {"Info": {"ScriptId": i}} for i in ("s1", "s2", "s3")}}}
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
# The machine's three scripts, kinds told by install path as plan._script_kind reads them.
scripts = {"instances": [{"uid": "s1"}, {"uid": "s2"}, {"uid": "s3"}]}
for uid, path in (("s1", "D:\\MAA"), ("s2", "D:\\ark\\okww"), ("s3", "D:\\MaaEnd")):
    scripts[uid] = {"Info": {"Name": uid, "Path": path}, "SubConfigsInfo": {}}
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts), encoding="utf-8")
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                  ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import engine as eng, shutdown           # noqa: E402
from ark_relay.config import SERVER_TZ, Config          # noqa: E402
from ark_relay.ledger import State                        # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def send(self, title, body="", **kw):
        return False


def at(hh, mm, ss=0):
    return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


# Verbatim from C:\ProgramData\ark-relay\state\ledger-2026-10-01.jsonl
ROWS = [("2026-10-01/arknights/MAA-05-00-01", "MAA", at(9, 0, 50), at(9, 18, 15), True),
        ("2026-10-01/wuwa/OK-WW-05-18-20", "OK-WW", at(9, 18, 37), at(9, 19, 16), "超时"),
        ("2026-10-01/wuwa/OK-WW-07-20-22", "OK-WW", at(11, 20, 35), at(11, 21, 10), "超时"),
        ("2026-10-01/wuwa/OK-WW-09-21-22", "OK-WW", at(13, 21, 35), at(13, 22, 10), "超时"),
        ("2026-10-01/endfield/MaaEnd-11-23-07", "MaaEnd", at(15, 24, 12), at(15, 29, 59), True),
        ("2026-10-01/endfield/MaaEnd-12-10-02", "MaaEnd", at(16, 11, 6), at(16, 11, 6), "失败"),
        ("2026-10-01/endfield/MaaEnd-12-11-12", "MaaEnd", at(16, 12, 15), at(16, 58, 22), True)]
(STATE / "ledger-2026-10-01.jsonl").write_text("\n".join(
    json.dumps({"run_id": r, "script": s, "user": "u", "started": a.isoformat(),
                "finished": b.isoformat(), "ok": ok is True,
                "failed_tasks": [] if ok is True else
                (["OK-WW 运行超时"] if ok == "超时" else ["赠送干员礼物", "装备制造"])})
    for r, s, a, b, ok in ROWS) + "\n",
    encoding="utf-8")

cfg = Config()
e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
e._scripts_running = lambda: False
e._handled_any = False                 # the process deployed at 17:41 had handled nothing
e._started_at = at(17, 41, 52)
BOOT = [at(8, 45, 11)]                 # LastBootUpTime read on the machine
e._boot_time = lambda now: BOOT[0]

now = at(17, 43)
entries = e._recent_entries(now)
print("[10-01 17:43, relay restarted at 17:41 after the shift closed]")
e.state.report_sent = lambda d: True
check("17:55, restarted after the shift: not-shift, stays on",
      shutdown.decide(e, at(17, 55)).code, "not-shift")
print("    decide says:", shutdown.decide(e, at(17, 55)))
check("the round still reaches back to MAA 09:00 (it was the shift, just not seen landing)",
      [x["script"] for x in shutdown._round_of_newest(entries)][0], "MAA")

print("\n[the same day, this process saw the last record land: go]")
e._handled_any = True
check("17:55, records landed in this process -> go", shutdown.decide(e, at(17, 55)).code, "go")
e._handled_any = False

print("\n[a machine booted after the runs (someone switched it on to work) still holds]")
BOOT[0] = at(17, 30)
check("booted 17:30 -> not-shift", shutdown.decide(e, at(17, 55)).code, "not-shift")
e._handled_any = True
check("even with records landing in this process", shutdown.decide(e, at(17, 55)).code, "not-shift")
e._handled_any = False

print("\n[uptime unknown -> cannot tie records to this boot -> hold]")
BOOT[0] = None
check("no boot time -> not-shift", shutdown.decide(e, at(17, 55)).code, "not-shift")
e.state.report_sent = State(cfg.state_dir).report_sent
BOOT[0] = at(8, 45, 11)

print("\n[a failure that is not a timeout still ends the round at a 2-hour gap]")
plain = [{"script": "OK-WW", "user": "u", "started": at(9, 18).isoformat(), "finished": at(9, 30).isoformat(),
          "ok": False, "failed_tasks": ["任务执行：开跑时游戏不在大世界"]},
         {"script": "MaaEnd", "user": "u", "started": at(13, 0).isoformat(), "finished": at(13, 30).isoformat(),
          "ok": True, "failed_tasks": []}]
check("hand-run MaaEnd at 13:00 stays its own round", len(shutdown._round_of_newest(plain)), 1)

print("\n[a hand-started re-run after a timeout is not pulled into the shift]")
okww_to = {"script": "OK-WW", "user": "u", "started": at(13, 21, 35).isoformat(),
           "finished": at(13, 22, 10).isoformat(), "ok": False, "failed_tasks": ["OK-WW 运行超时"]}
inside = {"script": "MaaEnd", "user": "u", "started": at(15, 24, 12).isoformat(),
          "finished": at(16, 0).isoformat(), "ok": True, "failed_tasks": []}
outside = dict(inside, started=at(15, 40).isoformat(), finished=at(16, 10).isoformat())
check("MaaEnd at 15:24 (13:21:35 + 120 + 10 = 15:31:35) joins", len(shutdown._round_of_newest([okww_to, inside])), 2)
check("MaaEnd by hand at 15:40 stays its own round", len(shutdown._round_of_newest([okww_to, outside])), 1)
me_to = {"script": "MaaEnd", "user": "u", "started": at(10, 29, 47).isoformat(),
         "finished": at(11, 22, 10).isoformat(), "ok": False, "failed_tasks": ["MaaEnd 进程超时"]}
check("after a MaaEnd timeout: 11:22:10 + 40 + 10 = 12:12:10 -> 12:03 joins",
      len(shutdown._round_of_newest([me_to, dict(inside, started=at(12, 3, 14).isoformat())])), 2)
check("OK-WW by hand at 13:30 stays its own round",
      len(shutdown._round_of_newest([me_to, dict(okww_to, ok=True, failed_tasks=[],
                                                started=at(13, 30).isoformat(),
                                                finished=at(13, 45).isoformat())])), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
