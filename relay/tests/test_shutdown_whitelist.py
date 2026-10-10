"""Only the decision right after a morning / evening shift finished may power off.

The user's rules of 2026-10-10 18:31 (Tokyo; only after a morning / evening shift) and 18:30
(not while someone uses the machine), quoted verbatim in USER-SWITCHES.txt at
shutdown.py:_note_not_shift and shutdown.py:_note_in_use.

The ledger is that day's, copied from C:\\ProgramData\\ark-relay\\state\\ledger-2026-10-10.jsonl
(start / end / ok as written). The boots are from the machine: the relay started at 08:45:18
(relay.log 「中继代码版本」) for the 09:00 shift and judged 「本轮已处理完毕」 at 09:39:30;
LastBootUpTime 11:45:20 for the boot by hand, after which MAA was started by hand at 12:05:54.
The evening shift is the morning one moved to 21:30.
"""
import json
import os
import sys
from datetime import datetime, timedelta
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
from ark_relay.core import State                        # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Notes:
    def send(self, title, body="", **kw):
        return False


def at(hh, mm, ss=0):
    return datetime(2026, 10, 10, hh, mm, ss, tzinfo=SERVER_TZ)


# Verbatim from the machine's ledger-2026-10-10.jsonl (the fields decide reads).
MORNING = [("MAA-05-00-01", "MAA", "arknights", at(9, 0, 51), at(9, 1, 10), False),
           ("MAA-05-01-15", "MAA", "arknights", at(9, 1, 59), at(9, 2, 14), False),
           ("MAA-05-02-18", "MAA", "arknights", at(9, 3, 1), at(9, 3, 17), False),
           ("OK-WW-05-03-21", "OK-WW", "wuwa", at(9, 3, 36), at(9, 13, 15), True),
           ("MaaEnd-05-13-19", "MaaEnd", "endfield", at(9, 14, 23), at(9, 37, 28), True)]
BY_HAND = [("MAA-08-05-07", "MAA", "arknights", at(12, 5, 54), at(12, 24, 26), True)]
EVENING = [(r.replace("-05-", "-17-"), s, u, a + timedelta(hours=12, minutes=30), b + timedelta(hours=12, minutes=30), ok)
           for r, s, u, a, b, ok in MORNING]


def ledger(rows):
    (STATE / "ledger-2026-10-10.jsonl").write_text("\n".join(
        json.dumps({"run_id": f"2026-10-10/x/{r}", "script": s, "user": u, "started": a.isoformat(),
                    "finished": b.isoformat(), "ok": ok,
                    "failed_tasks": [] if ok else ["MAA 在完成任务前中止"]})
        for r, s, u, a, b, ok in rows) + "\n", encoding="utf-8")


cfg = Config()
e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
e._scripts_running = lambda: False
e.state.report_sent = lambda d: True
BOOT = [None]
e._boot_time = lambda now: BOOT[0]
IDLE = [20 * 60]
shutdown.console_idle_s = lambda: IDLE[0]


def judge(now, boot, started, handled=True):
    BOOT[0], e._started_at, e._handled_any = boot, started, handled
    return shutdown.decide(e, now)


print("[morning shift finished on its own boot, this relay saw it land: go]")
ledger(MORNING)
v = judge(at(9, 39, 30), at(8, 45), at(8, 45, 18))
check("10-10 09:39:30 (the machine powered off here)", v.code, "go")

print("\n[evening shift finished on its own boot: go]")
ledger(MORNING + BY_HAND + EVENING)
check("22:09:30, booted 21:15", judge(at(22, 9, 30), at(21, 15), at(21, 15, 18)).code, "go")
check("the machine left on since the morning: the evening shift still ends it",
      judge(at(22, 9, 30), at(8, 45), at(8, 45, 18)).code, "go")

print("\n[booted by hand at 11:45, then a run by hand: never powered off]")
ledger(MORNING + BY_HAND)
for now in (at(11, 55, 30), at(12, 25, 9), at(17, 31, 44), at(20, 20)):
    v = judge(now, at(11, 45, 20), at(11, 45, 29))
    check(f"{now:%H:%M:%S} -> not-shift", v.code, "not-shift")
check("the reason says so in his terms", v.reason.startswith("不是早班/晚班跑完，不关机"), True)
check("…and names the boot", "10-10 11:45 开的机" in v.reason, True)
check("21:00, the 21:30 shift ahead -> waits for it (shift-ahead)",
      judge(at(21, 0), at(11, 45, 20), at(11, 45, 29)).code, "shift-ahead")
ledger(MORNING + BY_HAND + EVENING)
check("…and the evening shift on that boot ends it -> go",
      judge(at(22, 9, 30), at(11, 45, 20), at(11, 45, 29)).code, "go")

print("\n[relay restarted after the shift: not the decision right after it, stays on]")
ledger(MORNING)
v = judge(at(10, 1), at(8, 45), at(9, 50), handled=False)
check("10:01, restarted 09:50 -> not-shift", v.code, "not-shift")
check("…says the relay restarted", "重启" in v.reason, True)
check("restarted mid-shift and the last record landed after it -> go",
      judge(at(9, 49), at(8, 45), at(9, 20), handled=True).code, "go")

print("\n[before the shift, booted for it: waiting, not a refusal]")
ledger([])
check("08:55:19, booted 08:45 -> shift-ahead", judge(at(8, 55, 19), at(8, 45), at(8, 45, 18)).code, "shift-ahead")

print("\n[a shift that never finished: stays on, and says why (pushed after the cutoff)]")
ledger(MORNING[:4])               # no MaaEnd
v = judge(at(11, 40), at(8, 45), at(8, 45, 18))
check("11:40, MaaEnd never ran, past the old two-hour window -> unfinished", v.code, "unfinished")
check("…names what is missing", "MaaEnd" in v.reason, True)

print("\n[shift finished but someone is using the machine (18:30)]")
ledger(MORNING)
IDLE[0] = 0
check("input within the minute -> in-use", judge(at(9, 39, 30), at(8, 45), at(8, 45, 18)).code, "in-use")
IDLE[0] = 14 * 60 + 59
check("14 min 59 s idle -> in-use", judge(at(9, 39, 30), at(8, 45), at(8, 45, 18)).code, "in-use")
IDLE[0] = 20 * 60
check("idle 20 min -> go", judge(at(9, 39, 30), at(8, 45), at(8, 45, 18)).code, "go")
IDLE[0] = None
check("idle unreadable -> unchanged (go)", judge(at(9, 39, 30), at(8, 45), at(8, 45, 18)).code, "go")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
