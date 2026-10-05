"""A run a person starts from AUTO-MAS's own screen is reported, never alarmed.

2026-10-03 00:40-02:35 (JST) someone ran 自动肉鸽 ten times from AUTO-MAS
(app.log: 「创建任务: …, 模式: AutoProxy, 触发来源: manual_task」, 「任务被用户手动中止」).
The relay booked them as the evening shift's failures, held them for the final alarm
and pushed 「⏰ 晚班 21:30 开跑…还没跑完」 at 00:43.

trigger.py reads who created each task; the relay notes its own starts, because
/api/dispatch/start is 「manual_task」 too and a rerun the relay makes keeps its alarms.
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
(AUTOMAS / "debug").mkdir()
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import handle, runwatch, trigger            # noqa: E402
from ark_relay import engine as eng_mod                    # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core import State                           # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


# Real lines (automas-app.log in the 10-02 23:4x / 10-03 00:19 evidence; 09-25 21:30 for
# the timer's own), shortened to the four tasks used here.
APP_LOG = """\
2026-09-25 21:30:00.780 | INFO     | 业务调度 | 创建任务: e715210d-7445-4ff4-97c4-642e1a55afe7, 模式: AutoProxy, 触发来源: scheduled_task
2026-09-25 22:01:10.000 | INFO     | 业务调度 | 任务 e715210d-7445-4ff4-97c4-642e1a55afe7 已结束
2026-10-03 00:19:50.991 | INFO     | 业务调度 | 创建任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy, 触发来源: manual_task
2026-10-03 00:19:50.993 | SUCCESS  | 业务调度 | 任务 68b6e221-419d-444b-aff7-8643822c64ce 检索完成，包含 1 个脚本项
2026-10-03 00:19:50.994 | INFO     | 业务调度 | 开始运行任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy
2026-10-03 00:40:01.000 | INFO     | 业务调度 | 任务 68b6e221-419d-444b-aff7-8643822c64ce 已结束
2026-10-03 01:00:00.100 | INFO     | 业务调度 | 创建任务: 0000aaaa-1111-2222-3333-444455556666, 模式: AutoProxy, 触发来源: manual_task
"""
(AUTOMAS / "debug" / "app.log").write_text(APP_LOG, encoding="utf-8")


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


def at(d, hh, mm, ss=0):
    return datetime(2026, 9 if d == 25 else 10, d, hh, mm, ss, tzinfo=SERVER_TZ)


def rec(run_id, started, ok=False, script="MAA"):
    return RunRecord(run_id=run_id, script=script, user="arknights", started=started,
                     finished=started.replace(minute=started.minute + 5), ok=ok,
                     failed_tasks=[] if ok else ["自动肉鸽"], raw={})


def build():
    cfg = Config()
    cfg.state_dir = TMP / "state"
    cfg.state_dir.mkdir(exist_ok=True)
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._verify_outcome = lambda r: None
    return e


handle._weekly_gates = lambda eng, r: None

print("\n[读 AUTO-MAS 自己写的「触发来源」]")
tasks = trigger.read(AUTOMAS)
check("读到三个任务", [t.source for t in tasks], ["scheduled_task", "manual_task", "manual_task"])
check("结束时间也读到了", tasks[1].ended, at(3, 0, 40, 1))
check("00:20 那趟属于 00:19:50 建的手动任务", trigger.task_at(tasks, at(3, 0, 20)).id[:8], "68b6e221")
check("定时那趟属于定时任务", trigger.task_at(tasks, at(25, 21, 31)).source, "scheduled_task")

print("\n[有人手动开的失败：记账、不压着等最终报警、不推]")
e = build()
r = rec("m1", at(3, 0, 20))
e._handle(r)
check("没进待推队列", ("MAA", "arknights") in e._pending, False)
check("一条都没推", e.notifier.sent, [])
check("账上记了是手动开的", [x.get("raw", {}).get("hand_started", "")[:8]
                           for x in e.state.read_ledger("2026-10-03")], ["68b6e221"])

print("\n[定时的失败：和以前一样压着]")
e = build()
e._handle(rec("s1", at(25, 21, 31)))
check("进了待推队列", ("MAA", "arknights") in e._pending)

print("\n[中继自己开的（AUTO-MAS 也记 manual_task）：和以前一样压着]")
trigger.note_dispatch(TMP / "state", "队列 晚班", now=at(3, 0, 59, 58))
e = build()
e._handle(rec("r1", at(3, 1, 1)))
check("进了待推队列", ("MAA", "arknights") in e._pending)

print("\n[有人手动开的跑完了但有项目没干成：记日报，不推「这一轮没干完」]")
e = build()
e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成"
e._handle(rec("m2", at(3, 0, 25), ok=True))
check("一条都没推", e.notifier.sent, [])

print("\n[第一次超时：手动那趟不报，定时那趟照报]")
e = build()
now = at(3, 0, 30)
ev = runwatch.Timeout(at(3, 0, 29), "MAA", "运行超时", 1, 3, at(3, 0, 20))
check("手动那趟不报", runwatch.check_timeouts(e, [ev], now), [])
check("一条都没推", e.notifier.sent, [])
(AUTOMAS / "debug" / "app.log").write_text(
    APP_LOG.replace("触发来源: manual_task", "触发来源: scheduled_task", 1), encoding="utf-8")
runwatch.check_timeouts(e, [ev], now)
check("定时那趟照报", [a for _, a in e.notifier.sent], [True])
(AUTOMAS / "debug" / "app.log").write_text(APP_LOG, encoding="utf-8")

print("\n[班次超时：只算定时器开的那个任务]")
e = build()
check("手动任务不算班次超时", runwatch._not_the_shift(e, {"taskId": "68b6e221-419d-444b-aff7-8643822c64ce"}))
check("定时任务照算", runwatch._not_the_shift(e, {"taskId": "e715210d-7445-4ff4-97c4-642e1a55afe7"}), False)
check("日志里没有的照算", runwatch._not_the_shift(e, {"taskId": "deadbeef"}), False)

print("\n[读不到 AUTO-MAS 日志：一切照旧]")
(AUTOMAS / "debug" / "app.log").unlink()
e = build()
e._handle(rec("x1", at(3, 0, 20)))
check("进了待推队列", ("MAA", "arknights") in e._pending)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
