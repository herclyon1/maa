"""Watch a running queue: push the first timeout at once, and a shift that overruns.

Replays 2026-10-01: OK-WW timed out at 11:20, 13:21 and 15:23 (two hours each),
MaaEnd at 16:10, and the morning shift that normally ends within an hour was
still running past 16:00. Not one alarm went out that day. The app.log lines
below are copied from the machine; the ledger shapes from 09-24..09-30.
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

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

from ark_relay import engine as eng                       # noqa: E402
from ark_relay.config import SERVER_TZ, Config             # noqa: E402
from ark_relay.core import State                          # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, title, body="", **kw):
        if self.fail:
            return ["群机器人发送失败"]
        self.sent.append((title, body, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


APPLOG = AUTOMAS / "debug" / "app.log"
# Verbatim from D:\ark\automas\debug\app.log, 2026-10-01.
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
    e = eng.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
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

print("\n[the second and third OK-WW timeouts the same day are not pushed again]")
append_log(4, 8)
run_watch(e, at(13, 22))
run_watch(e, at(15, 24))
check("still one alarm", len(alarms(e)), 1)

print("\n[MaaEnd's first timeout at 16:10 is its own alarm]")
append_log(8, 11)
run_watch(e, at(16, 11))
got = alarms(e)
check("two alarms now", len(got), 2)
check("second one is 终末地", len(got) == 2 and "终末地（MaaEnd）" in got[1][0], True)
check("first attempt, 15:23 to 16:10", len(got) == 2 and "第 1/3 次跑超时：15:23 开跑，16:10" in got[1][1], True)

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

print("\n[app.log rotated (AUTO-MAS restarted): read from the start again]")
write_log(0)
e4 = build()
run_watch(e4, at(11, 0))
write_log(4)
run_watch(e4, at(11, 21))
check("timeout found in the new file", len(alarms(e4)), 1)

# ---------------------------------------------------------------- shift overrun
from ark_relay import runwatch  # noqa: E402


def ledger(state, day, rows):
    lines = [json.dumps({"run_id": f"r{i}", "script": s, "started": a.isoformat(),
                         "finished": b.isoformat(), "ok": True}) for i, (s, a, b) in enumerate(rows)]
    state.ledger_path(day.strftime("%Y-%m-%d")).write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    # 09-28 verbatim: a 41-minute hole between two MaaEnd records of the same shift
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

print("\n[10-01: still running at 13:10 (09:00 + 220 + 30) -> one alarm]")
real_os, real_snap = eng.os, eng._automas_snapshot
try:
    eng.os = types.SimpleNamespace(name="nt")
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
finally:
    eng.os, eng._automas_snapshot = real_os, real_snap

print("\n[the loop comes back every minute while something runs, never when idle]")
e8 = build()
e8._scripts_running = lambda: True
d = e8.next_deadline(at(10, 0))
check("next moment one minute away", d and d[0] == at(10, 0) + timedelta(seconds=60), True)
e8._scripts_running = lambda: False
d = e8.next_deadline(at(10, 0))
check("idle: no one-minute wake", bool(d) and d[0] == at(10, 0) + timedelta(seconds=60), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
