"""AUTO-MAS refused to start a script of a running queue: said at once, with its reason.

Replays 2026-10-16. The morning shift (早班 09:00: MAA, OK-WW, MaaEnd) ran MAA and
OK-WW; at 09:34:05 AUTO-MAS's own config check refused MaaEnd (it could not find the
official Endfield launcher) and moved on, writing no history record. The relay said
nothing until the hour backstop: 10:34 「🔌 MaaEnd 没有运行（早班）」 without the
reason, a 🩺 copy of it, 12:08 「⏰ 一直没出结果」 for the same thing, a 全绿 interim
report at 11:34, and the shutdown held on 「还差 MaaEnd」 for the rest of the boot.

Sources: app.log lines 291-306 below are verbatim from D:\\ark\\automas\\debug\\app.log
(10-16), except the 09:00 「创建任务」 line, which is built from the task id in
line 306 in the shape trigger.py documents. The ledger rows are the machine's
ledger-2026-10-16.jsonl (run_id, script, user, started, finished, ok, transitional);
the relay.log timeline is relay-1016.log 220-254 (09:34:07 tick, 10:34:12 backstop).
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "debug").mkdir()
MORNING, EVENING = "cc32e55a-55d0-408d-980d-642e66d111ae", "6f09a385-b0ae-4ff6-9890-50339bdaddeb"
S_MAA, S_OKWW, S_END = ("754d129e-d587-435b-b75f-a0b91aac7020", "c5e96ddc-aae9-4a73-b6fe-1312a417382d",
                        "59da8762-8fa7-4260-8aee-10f9ca00097a")
doc = {"instances": [{"uid": MORNING, "type": "QueueConfig"}, {"uid": EVENING, "type": "QueueConfig"}]}
for uid, name, t, items in ((MORNING, "早班", "09:00", (S_MAA, S_OKWW, S_END)), (EVENING, "晚班", "21:30", (S_MAA,))):
    doc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": t}}},
                                   "QueueItem": {str(i): {"Info": {"ScriptId": s}} for i, s in enumerate(items)}}}
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
scripts = {"instances": [{"uid": s} for s in (S_MAA, S_OKWW, S_END)]}
for uid, name, path, user in ((S_MAA, "maa明日方舟", "D:\\ark\\MAA", "arknights"),
                              (S_OKWW, "鸣潮", "D:\\ark\\okww", "wuwa"),
                              (S_END, "MaaEnd", "D:\\ark\\maaend", "endfield")):
    scripts[uid] = {"Info": {"Name": name, "Path": path},
                    "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": user}}}}}
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts, ensure_ascii=False), encoding="utf-8")
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), ARK_SHUTDOWN_AFTER_RUN="1",
                  ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng                       # noqa: E402
from ark_relay.core import ledger as core, texts               # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config             # noqa: E402
from ark_relay.core.ledger import State                          # noqa: E402
from ark_relay.features.alarm import errwatch                    # noqa: E402
from ark_relay.features.run import runwatch                      # noqa: E402
from ark_relay.features.shutdown import shutdown                 # noqa: E402
from ark_relay.features.selfcheck import machinecheck as _mc     # noqa: E402
_mc.load()
_mc_real = dict(_mc.CHECKS)
_mc.CHECKS.clear()

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


def at(hh, mm, ss=0):
    return datetime(2026, 10, 16, hh, mm, ss, tzinfo=SERVER_TZ)


APPLOG = AUTOMAS / "debug" / "app.log"
LINES = [
    # Built from line 306's task id (the queue's own task), trigger.py's documented shape.
    "2026-10-16 09:00:00.780 | INFO     | 业务调度 | 创建任务: b5f541de-20a4-4b73-856a-027cd91161b2, 模式: AutoProxy, 触发来源: scheduled_task",
    # Verbatim, app.log 291-306.
    "2026-10-16 09:34:04.904 | INFO     | 配置管理 | 开始处理通用日志, 日志长度: 637, 日志标记: Success!",
    "2026-10-16 09:34:04.906 | SUCCESS  | 配置管理 | 通用日志统计完成, 日志路径: D:\\ark\\automas\\history\\2026-10-16\\wuwa\\OK-WW-05-20-13.log",
    "2026-10-16 09:34:04.917 | INFO     | OK-WW 通知工具 | 开始推送通知, 模式: 统计信息, 标题: 10-16 |√|  wuwa 的 OK-WW 自动代理统计报告",
    "2026-10-16 09:34:04.919 | SUCCESS  | OK-WW 自动代理 | 用户 50ca12aa-0288-4592-982e-60f0bd6dc74e 的 OK-WW 自动代理任务已完成",
    "2026-10-16 09:34:04.920 | INFO     | 任务执行 | 任务收尾完成: AutoProxyTask - 用时: 1.172秒",
    "2026-10-16 09:34:04.920 | INFO     | OK-WW 调度器 | 复原 OK-WW 脚本配置文件: D:\\ark\\automas\\data\\c5e96ddc-aae9-4a73-b6fe-1312a417382d\\Temp",
    "2026-10-16 09:34:04.948 | INFO     | 任务执行 | 任务执行结束，开始收尾: OkwwManager",
    "2026-10-16 09:34:04.948 | INFO     | OK-WW 调度器 | 复原 OK-WW 脚本配置文件: D:\\ark\\automas\\data\\c5e96ddc-aae9-4a73-b6fe-1312a417382d\\Temp",
    "2026-10-16 09:34:04.984 | INFO     | OK-WW 通知工具 | 开始推送通知, 模式: 代理结果, 标题: 10-16 | OK-WW的自动代理任务报告",
    "2026-10-16 09:34:04.986 | INFO     | 任务执行 | 任务收尾完成: OkwwManager - 用时: 0.031秒",
    "2026-10-16 09:34:04.988 | INFO     | 业务调度 | 任务开始: 59da8762-8fa7-4260-8aee-10f9ca00097a",
    "2026-10-16 09:34:05.023 | WARNING  | MaaEnd 调度器 | 未通过配置检查: 未找到终末地官方启动器, 请选择鹰角官方启动器 Launcher.exe 或 Games.exe！",
    "2026-10-16 09:34:05.027 | INFO     | 任务执行 | 任务执行结束，开始收尾: MaaEndManager",
    "2026-10-16 09:34:05.029 | INFO     | 任务执行 | 任务收尾完成: MaaEndManager - 用时: 0.000秒",
    "2026-10-16 09:34:05.029 | INFO     | 任务执行 | 任务执行结束，开始收尾: Task",
    "2026-10-16 09:34:05.030 | INFO     | 业务调度 | 任务结束: b5f541de-20a4-4b73-856a-027cd91161b2",
]
SKIP_AT = 12          # index of the 未通过配置检查 line

# ledger-2026-10-16.jsonl, as on the machine.
LEDGER = [("2026-10-16/arknights/MAA-05-00-24", "MAA", "arknights", at(9, 0, 27), at(9, 18, 20), True, False),
          ("2026-10-16/wuwa/OK-WW-05-18-27", "OK-WW", "wuwa", at(9, 19, 47), at(9, 20, 1), False, True),
          ("2026-10-16/wuwa/OK-WW-05-20-13", "OK-WW", "wuwa", at(9, 21, 26), at(9, 33, 54), True, False)]


def build(state_dir=None, lines=len(LINES)):
    APPLOG.write_text("".join(ln + "\n" for ln in LINES[:lines]), encoding="utf-8")
    cfg = Config()
    cfg.state_dir = state_dir or tmpdir()
    st = State(cfg.state_dir)
    if state_dir is None:
        st.ledger_path("2026-10-16").write_text("\n".join(json.dumps(
            {"run_id": r, "script": s, "user": u, "started": a.isoformat(), "finished": b.isoformat(), "ok": ok,
             "failed_tasks": [], "transitional": tr, "raw": {}}) for r, s, u, a, b, ok, tr in LEDGER) + "\n",
            encoding="utf-8")
    e = eng.Engine(cfg, source=Src(), state=st, notifier=Notes())
    e._scripts_running = lambda: False
    e._boot_time = lambda now: at(8, 45, 0)        # relay-1016.log: the relay came up 08:45-08:46
    e._started_at = at(8, 45, 18)
    e._handled_any = True                          # it saw MAA and OK-WW land (09:18:29, 09:34:07)
    e.state.report_sent = lambda d: True
    return e


def alarms(e):
    return [(t, b) for t, b, a in e.notifier.sent if a]


print("[10-16 09:34:07: the tick that read app.log tells the group at once, with AUTO-MAS's reason]")
e = build()
e._run_watch(at(9, 34, 7))
got = alarms(e)
check("one alarm", len(got), 1)
title, body = got[0] if got else ("", "")
check("title names MaaEnd and the shift", title, "🔌 MaaEnd 没有运行（早班）")
check("body gives the reason in plain words", "AUTO-MAS 开跑前检查没过：找不到终末地官方启动器" in body, True)
check("body says the run did not happen and needs a fix", "没开跑" in body and "要有人去改" in body, True)
check("body passes texts.plain()", texts.plain(body), [])
check("no English file names or 调度器 in it", ("Launcher.exe" in body, "调度器" in body), (False, False))

print("\n[the skip is the shift's MaaEnd result: on the ledger as a failed run]")
rows = [r for r in e.state.read_ledger("2026-10-16") if r["script"] == "MaaEnd"]
check("one MaaEnd row", len(rows), 1)
check("…failed, at 09:34:05", (rows[0]["ok"], rows[0]["started"][:19]) if rows else None,
      (False, "2026-10-16T09:34:05"))

print("\n[10:34 (the hour backstop) and 12:08 (the overdue check): nothing more for the same fault]")
first = list(got)
e._check_missed_runs(at(10, 34, 12))
check("no 10:34 「缺项」 alarm: only the 09:34 one", alarms(e), first)
shutdown._alarm_shift_overdue(e, at(12, 8, 1))
check("no 12:08 「一直没出结果」 alarm", alarms(e), first)
check("the 09:34 one was not empty", len(first), 1)
check("no overdue wake-up left for 早班", shutdown.overdue_moments(e, at(9, 35)), [])

print("\n[the shutdown gate: the shift is over at the skip, so the machine is not held on]")
v = shutdown.decide(e, at(9, 35))
check("not 「shift-running」 (还差 MaaEnd)", v.code != "shift-running", True)
check("…the decision right after the shift says go", v.code, "go")

print("\n[the interim / daily title is not 全绿]")
entries = e.state.read_ledger("2026-10-16")
title2, body2 = core.format_daily("2026-10-16", entries, shifts=[("早班", "09:00"), ("晚班", "21:30")])
check("title is not 全绿", "全绿" in title2, False)
check("title says 终末地早班没跑成", "终末地早班没跑成" in title2, True)
check("the row gives the reason", "开跑前检查没过：找不到终末地官方启动器" in body2, True)

print("\n[a relay restarted on the same day re-reads app.log from the top: no second alarm]")
e2 = build(state_dir=e.cfg.state_dir)
e2._run_watch(at(9, 50))
check("restarted relay: nothing pushed", alarms(e2), [])
check("still one MaaEnd row", len([r for r in e2.state.read_ledger("2026-10-16") if r["script"] == "MaaEnd"]), 1)

print("\n[the skip line lands ~100 ms after the queue moves on: one extra wake right after running stops]")
e3 = build(lines=SKIP_AT)                          # the 09:34:04.988 poll: skip line not written yet
e3._run_watch(at(9, 34, 4))
check("nothing yet", alarms(e3), [])
moments = runwatch.next_moments(e3, at(9, 34, 4), True)
check("while running: the minute recheck", [m for m, _ in moments], [at(9, 35, 4)])
moments = runwatch.next_moments(e3, at(9, 34, 7), False)
check("running went true -> false: one wake within seconds",
      len(moments) == 1 and at(9, 34, 7) < moments[0][0] <= at(9, 34, 20), True)
check("asked again before it: the same wake", runwatch.next_moments(e3, at(9, 34, 8), False), moments)
after = moments[0][0] + timedelta(seconds=1) if moments else at(9, 35)
check("after it: nothing", runwatch.next_moments(e3, after, False), [])
with APPLOG.open("a", encoding="utf-8") as fh:
    fh.write("".join(ln + "\n" for ln in LINES[SKIP_AT:]))
e3._run_watch(moments[0][0] if moments else at(9, 34, 17))
check("that wake reads the skip and alarms", len(alarms(e3)), 1)

print("\n[without a skip line, the 「缺项」 check wakes at due + partial_grace, not at the hour backstop]")
e4 = build(lines=SKIP_AT)
e4._run_watch(at(9, 34, 7))
nd = e4.next_deadline(at(9, 34, 7))
check("next wake is 10:15 (09:00 + 75)", nd and nd[0], at(10, 15))
cap = []


class _H(logging.Handler):
    def emit(self, rec):
        cap.append(rec)


h = _H()
logging.getLogger("ark.missed").addHandler(h)
try:
    e4._check_missed_runs(at(10, 15, 5))
finally:
    logging.getLogger("ark.missed").removeHandler(h)
check("the 10:15 alarm went out", [t for t, _ in alarms(e4)], ["🔌 MaaEnd 没有运行（早班）"])
check("its log line is marked as already in the group (no 🩺 copy)",
      [bool(getattr(r, errwatch.PUSHED, False)) for r in cap if r.levelno >= logging.WARNING], [True])
shutdown._alarm_shift_overdue(e4, at(12, 8, 1))
check("and 12:08 does not say it again", len(alarms(e4)), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
_mc.CHECKS.update(_mc_real)
sys.exit(1 if fails else 0)
