"""A relay restarted after the shift still knows this boot did its work.

2026-10-01: the morning shift closed at 17:27:43, the relay was redeployed at
17:41, and the new process judged 「本次开机还没有跑完任何队列」 - it had handled
no record itself, and 09:00 was long outside _work_is_done's two-hour window.
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
                                   "QueueItem": {"i": {"Info": {"ScriptId": "s1"}}}}}
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                  ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import engine as eng, shutdown           # noqa: E402
from ark_relay.config import SERVER_TZ, Config          # noqa: E402
from ark_relay.core import State                        # noqa: E402

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
e._idle_checkpoint = lambda now=None: False
e._handled_any = False                 # the process deployed at 17:41 had handled nothing
e._started_at = at(17, 41, 52)
BOOT = [at(8, 45, 11)]                 # LastBootUpTime read on the machine
e._boot_time = lambda now: BOOT[0]

now = at(17, 43)
entries = e._recent_entries(now)
print("[10-01 17:43, relay restarted at 17:41 after the shift closed]")
check("the old gates alone say nothing ran",
      bool(e._handled_any or e._work_is_done(now, entries)), False)
check("decide no longer stops at 「本次开机还没有跑完任何队列」",
      shutdown.decide(e, now).code != "nothing-done", True)
print("    decide now says:", shutdown.decide(e, now))
e.state.report_sent = lambda d: True
check("17:55, uptime floor passed: the round is the 09:00 shift, not a hand-run one",
      shutdown.decide(e, at(17, 55)).code, "go")
check("the round reaches back to MAA 09:00",
      [x["script"] for x in shutdown._round_of_newest(entries)][0], "MAA")
e.state.report_sent = State(cfg.state_dir).report_sent
check("the ledger says this boot ran", shutdown._ran_since_boot(e, now, entries), True)

print("\n[a machine booted after the runs (someone switched it on to work) still holds]")
BOOT[0] = at(17, 30)
check("nothing started after boot", shutdown._ran_since_boot(e, now, entries), False)
check("decide holds at nothing-done", shutdown.decide(e, now).code, "nothing-done")

print("\n[uptime unknown -> cannot tie records to this boot -> hold]")
BOOT[0] = None
check("no boot time", shutdown._ran_since_boot(e, now, entries), False)

print("\n[before the morning queue, booted 08:45: nothing in the ledger yet]")
BOOT[0] = at(8, 45, 11)
check("empty ledger", shutdown._ran_since_boot(e, at(8, 50), []), False)

print("\n[a failure that is not a timeout still ends the round at a 2-hour gap]")
plain = [{"script": "OK-WW", "user": "u", "started": at(9, 18).isoformat(), "finished": at(9, 30).isoformat(),
          "ok": False, "failed_tasks": ["任务执行：开跑时游戏不在大世界"]},
         {"script": "MaaEnd", "user": "u", "started": at(13, 0).isoformat(), "finished": at(13, 30).isoformat(),
          "ok": True, "failed_tasks": []}]
check("hand-run MaaEnd at 13:00 stays its own round", len(shutdown._round_of_newest(plain)), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
