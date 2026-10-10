"""A run a person starts from AUTO-MAS's own screen is told apart from the shift, and
its failures are pushed like any other's, saying whose run it was.

2026-10-03 00:40-02:35 (JST) someone ran 自动肉鸽 ten times from AUTO-MAS
(app.log: 「创建任务: …, 模式: AutoProxy, 触发来源: manual_task」, 「任务被用户手动中止」).
The relay booked them as the evening shift's failures, held them for the final alarm
and pushed 「⏰ 晚班 21:30 开跑…还没跑完」 at 00:43. From then until 2026-10-06 such a
run was booked for the daily report only; the user's order of 2026-10-06 (「不论多少次
什么错误都要发」) puts its failures, 「没干完」 and timeouts back in the group. It is
still not the shift: no make-up, no hold, no shift-overrun alarm.

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
2026-09-25 22:01:10.000 | INFO     | 业务调度 | 任务结束: e715210d-7445-4ff4-97c4-642e1a55afe7
2026-10-03 00:19:50.991 | INFO     | 业务调度 | 创建任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy, 触发来源: manual_task
2026-10-03 00:19:50.993 | SUCCESS  | 业务调度 | 任务 68b6e221-419d-444b-aff7-8643822c64ce 检索完成，包含 1 个脚本项
2026-10-03 00:19:50.994 | INFO     | 业务调度 | 开始运行任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy
2026-10-03 00:40:01.000 | INFO     | 业务调度 | 任务 68b6e221-419d-444b-aff7-8643822c64ce 已结束
2026-10-03 01:00:00.100 | INFO     | 业务调度 | 创建任务: 0000aaaa-1111-2222-3333-444455556666, 模式: AutoProxy, 触发来源: manual_task
"""
(AUTOMAS / "debug" / "app.log").write_text(APP_LOG, encoding="utf-8")


class Notes:
    def __init__(self):
        self.sent, self.bodies = [], []

    def send(self, title, body="", **kw):
        self.sent.append((title, kw.get("alert", False)))
        self.bodies.append(body)
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
handle._ship_evidence = lambda eng, r: ""      # no bundle upload in a test

print("\n[读 AUTO-MAS 自己写的「触发来源」]")
tasks = trigger.read(AUTOMAS)
check("读到三个任务", [t.source for t in tasks], ["scheduled_task", "manual_task", "manual_task"])
check("结束时间也读到了", tasks[1].ended, at(3, 0, 40, 1))
check("「任务结束:」这种写法也认", tasks[0].ended, at(25, 22, 1, 10))
check("00:20 那趟属于 00:19:50 建的手动任务", [t.id[:8] for t in trigger.tasks_at(tasks, at(3, 0, 20))], ["68b6e221"])
check("定时那趟属于定时任务", [t.source for t in trigger.tasks_at(tasks, at(25, 21, 31))], ["scheduled_task"])

print("\n[同时开着两个任务（10-02 23:43 就有）：有一个不是手动的就不算手动]")
both = trigger.parse("""\
2026-10-04 09:00:00.100 | INFO     | 业务调度 | 创建任务: aaaa0000-0000-0000-0000-000000000001, 模式: AutoProxy, 触发来源: scheduled_task
2026-10-04 09:10:00.100 | INFO     | 业务调度 | 创建任务: bbbb0000-0000-0000-0000-000000000002, 模式: AutoProxy, 触发来源: manual_task
""".splitlines())
check("两个都开着", len(trigger.tasks_at(both, at(4, 9, 20))), 2)
check("不算手动", trigger.hand_started_at(both, at(4, 9, 20), TMP / "state"), None)
check("只有手动那个开着时才算", trigger.hand_started_at(both[1:], at(4, 9, 20), TMP / "state").id[:4], "bbbb")

print("\n[有人手动开的失败：记账、不压着、不补跑，马上报群并写明是手动开的]")
from ark_relay import texts  # noqa: E402
e = build()
r = rec("m1", at(3, 0, 20))
e._handle(r)
check("没进待推队列", ("MAA", "arknights") in e._pending, False)
check("报群一条", e.notifier.sent, [(texts.failed("MAA"), True)])
check("头一行写明是手动开的", e.notifier.bodies[-1].splitlines()[:1] if e.notifier.bodies else [],
      [getattr(texts, "HAND_STARTED_NOTE", "-")])
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

print("\n[有人手动开的跑完了但有项目没干成：报「这一轮没干完」，写明是手动开的]")
e = build()
e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成"
e._handle(rec("m2", at(3, 0, 25), ok=True))
check("报群一条", e.notifier.sent, [(texts.ROUND_INCOMPLETE, True)])
check("写明是手动开的", bool(e.notifier.bodies) and e.notifier.bodies[-1].startswith(
    getattr(texts, "HAND_STARTED_NOTE", "-")))

print("\n[之前压着定时的失败、后来有人手动跑成：不发「重试后成功」]")
e = build()
e._handle(rec("s2", at(3, 0, 10, 0).replace(day=2, hour=21, minute=31)))
had = ("MAA", "arknights") in e._pending
e._verify_outcome = lambda r: None
e._handle(rec("m3", at(3, 0, 30), ok=True))
check("先压着了", had)
check("压着的那条清掉了", ("MAA", "arknights") in e._pending, False)
check("不记成自愈", ("MAA", "arknights") in e._recovered, False)

print("\n[超时：手动那趟也报（写明是手动开的），定时那趟照报]")
e = build()
now = at(3, 0, 30)
ev = runwatch.Timeout(at(3, 0, 29), "MAA", "运行超时", 1, 3, at(3, 0, 20))
check("手动那趟：发出去了", runwatch.check_timeouts(e, [ev], now), [])
check("手动那趟也报", [a for _, a in e.notifier.sent], [True])
check("…写明是手动开的", bool(e.notifier.bodies) and e.notifier.bodies[-1].startswith(
    getattr(texts, "HAND_STARTED_NOTE", "-")))
(AUTOMAS / "debug" / "app.log").write_text(
    APP_LOG.replace("触发来源: manual_task", "触发来源: scheduled_task", 1), encoding="utf-8")
runwatch.check_timeouts(e, [runwatch.Timeout(at(3, 0, 29, 30), "MAA", "运行超时", 2, 3, at(3, 0, 20))], now)
check("定时那趟照报", [a for _, a in e.notifier.sent], [True, True])
check("…不写手动", e.notifier.bodies[-1].startswith(getattr(texts, "HAND_STARTED_NOTE", "-")), False)
(AUTOMAS / "debug" / "app.log").write_text(APP_LOG, encoding="utf-8")

print("\n[班次超时：只算定时器开的那个任务（手动开的不是这一班，说它「这一班还没跑完」不对）]")
e = build()
check("手动任务不算班次超时", runwatch._not_the_shift(e, {"taskId": "68b6e221-419d-444b-aff7-8643822c64ce"}))
check("定时任务照算", runwatch._not_the_shift(e, {"taskId": "e715210d-7445-4ff4-97c4-642e1a55afe7"}), False)
check("日志里没有的照算", runwatch._not_the_shift(e, {"taskId": "deadbeef"}), False)
check("中继自己开的照算", runwatch._not_the_shift(e, {"taskId": "0000aaaa-1111-2222-3333-444455556666"}), False)

print("\n[读不到 AUTO-MAS 日志：一切照旧]")
(AUTOMAS / "debug" / "app.log").unlink()
e = build()
e._handle(rec("x1", at(3, 0, 20)))
check("进了待推队列", ("MAA", "arknights") in e._pending)

print("\n[the relay's own-starts file is unreadable: said once, not on every read]")
# Until 2026-10-10 a corrupt file read as [] with no word, and the relay's own
# make-up starts were booked as a person's (no further make-up, 手动 label).
# Read every tick (shutdown decision, runwatch), so once per condition.
import logging                                             # noqa: E402


class _Warn(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


_w = _Warn()
logging.getLogger("ark.trigger").addHandler(_w)
try:
    sd = tmpdir()
    check("no file: [] and nothing said", (trigger._read_dispatches(sd), _w.lines), ([], []))
    (sd / trigger.DISPATCH_FILE).write_text('[{"at": "2026-10-0', encoding="utf-8")
    got = [trigger._read_dispatches(sd) for _ in range(3)]
    check("corrupt: still []", got, [[], [], []])
    check("corrupt: one WARNING naming the consequence",
          len([ln for ln in _w.lines if "当成有人手动开的" in ln and trigger.DISPATCH_FILE in ln]), 1)
    (sd / trigger.DISPATCH_FILE).write_text("[]", encoding="utf-8")
    trigger._read_dispatches(sd)
    (sd / trigger.DISPATCH_FILE).write_text("{bad", encoding="utf-8")
    trigger._read_dispatches(sd)
    check("readable in between: said again when it breaks again", len(_w.lines), 2)
finally:
    logging.getLogger("ark.trigger").removeHandler(_w)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
