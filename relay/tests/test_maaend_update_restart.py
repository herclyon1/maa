"""A MaaEnd attempt spent installing its own update is not a game failure.

2026-10-01: the 15:24 attempt found v2.31.0-beta.6 and only downloaded it
(「已保存待安装更新信息」). The next launch, 16:11:06, installed it and restarted
MaaEnd; the process AUTO-MAS watched exited and all 15 tasks were booked failed.
The 16:12 attempt then succeeded. MXU log lines below are verbatim from
D:\\ark\\maaend\\debug\\2026-10-01-3.log / -4.log.
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
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(TMP / "history").mkdir()
MAAEND = TMP / "maaend"
(MAAEND / "debug").mkdir(parents=True)
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collect_retry, handle             # noqa: E402
from ark_relay import engine as eng_mod                 # noqa: E402
from ark_relay.collector_maaend import update_restart_version  # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core import State                        # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
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
    return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


(MAAEND / "debug" / "2026-10-01-3.log").write_text("\n".join([
    "2026-10-01 15:24:11 INFO  [App] 检查更新: MaaEnd, 当前版本: v2.31.0-beta.5, 频道: beta",
    "2026-10-01 15:24:12 INFO  [App] 发现新版本: v2.31.0-beta.6",
    "2026-10-01 15:24:14 INFO  [App] 已保存待安装更新信息: v2.31.0-beta.6",
]) + "\n", encoding="utf-8")
(MAAEND / "debug" / "2026-10-01-4.log").write_text("\n".join([
    "2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6",
    "2026-10-01 16:11:06 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\10697.zip -> D:\\ark\\maaend",
    "2026-10-01 16:11:07 INFO  [App] 增量更新: deleted=0, added=0, modified=4",
    "2026-10-01 16:11:07 INFO  [App] 更新安装完成",
    "2026-10-01 16:11:07 INFO  [App] 已清除待安装更新信息",
]) + "\n", encoding="utf-8")

FIFTEEN = ["赠送干员礼物", "装备制造", "拜访好友", "基建任务", "信用点购物", "转交委托", "据点交易",
           "环境监测", "自动囤货", "售卖弹性物资", "购买稳定物资", "协议空间", "选剑演武", "自动采集", "日常奖励领取"]


def runs(with_success=True):
    out = [RunRecord(run_id="2026-10-01/endfield/MaaEnd-11-23-07", script="MaaEnd", user="endfield",
                     started=at(15, 24, 12), finished=at(16, 10, 0), ok=False,
                     failed_tasks=["MaaEnd 进程超时"], raw={"maaend_result": "MaaEnd 进程超时"}),
           RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-10-02", script="MaaEnd", user="endfield",
                     started=at(16, 11, 6), finished=at(16, 11, 6), ok=False, failed_tasks=list(FIFTEEN),
                     raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})]
    if with_success:
        out.append(RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-11-12", script="MaaEnd", user="endfield",
                             started=at(16, 12, 15), finished=at(16, 58, 22), ok=True, failed_tasks=[],
                             raw={"maaend_result": "Success!", "tasks_done": ["日常奖励领取"]}))
    return out


handle._ship_evidence = lambda eng, rec: ""
collect_retry.restore_master = lambda cfg: ""
handle._weekly_gates = lambda eng, rec: None


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    e._alert_key = lambda r: handle._alert_key(e, r)
    return e


def alarms(e):
    return [(t, b) for t, b, a in e.notifier.sent if a]


print("[the reader: only the attempt that installed counts]")
check("16:11:06 attempt installed beta.6", update_restart_version(MAAEND, at(16, 11, 6)),
      "v2.31.0-beta.6")
check("15:24 attempt only downloaded", update_restart_version(MAAEND, at(15, 24, 12)), "")
check("no MaaEnd dir", update_restart_version(None, at(16, 11, 6)), "")

print("\n[an attempt killed 50 s before the next one installs stays a failure]")
(MAAEND / "debug" / "2026-10-02-1.log").write_text("\n".join([
    "2026-10-02 10:00:50 INFO  [App] 检测到待安装更新: v9.9.9",
    "2026-10-02 10:00:51 INFO  [App] 更新安装完成"]) + "\n", encoding="utf-8")
killed_start = datetime(2026, 10, 2, 9, 20, tzinfo=SERVER_TZ)      # killed at 10:00:00
check("the killed attempt is not the one that installed", update_restart_version(MAAEND, killed_start), "")
check("the attempt that started at 10:00:50 is", update_restart_version(MAAEND, datetime(2026, 10, 2, 10, 0, 50, tzinfo=SERVER_TZ)), "v9.9.9")
check("install line too long after the start does not count",
      update_restart_version(MAAEND, datetime(2026, 10, 2, 10, 0, 0, tzinfo=SERVER_TZ)), "")

print("\n[10-01 replay: crash, update restart, success -> the update attempt is not a failure]")
e = build()
for r in runs():
    handle._handle(e, r)
e._flush_pending()
ledger = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}
mid = ledger["2026-10-01/endfield/MaaEnd-12-10-02"]
check("booked as an update restart", (mid.get("raw") or {}).get("maaend_update_restart"), "v2.31.0-beta.6")
check("transitional in the ledger", mid.get("transitional"), True)
check("its failure names the update, not 15 tasks", mid.get("failed_tasks"),
      ["MaaEnd 装新版 v2.31.0-beta.6 后自己重启，这一次重试被用掉"])
check("no failure alarm (the day healed)", alarms(e), [])

print("\n[daily report: only the update attempt is an episode; the 15:24 crash stays listed]")
from ark_relay import core  # noqa: E402
entries = e.state.read_ledger("2026-10-01")
kinds = core.episode_kinds(entries)
check("16:11 update restart is the episode", kinds.get("2026-10-01/endfield/MaaEnd-12-10-02"), "update")
check("15:24 crash is not folded into it", kinds.get("2026-10-01/endfield/MaaEnd-11-23-07"), None)
check("15:24 reads as failed then retried", core.retried_notes(entries).get("2026-10-01/endfield/MaaEnd-11-23-07"),
      "MaaEnd 进程超时　后来在 16:58 那趟重试里做成了")
title, body = core.format_daily("2026-10-01", entries)
print("    " + title)
print("    " + body.replace("\n", "\n    ")[:600])
check("the crash line is there with ↻", any(l.startswith("↻ MaaEnd") for l in body.splitlines()), True)
check("the update line is there with ↪️", any(l.startswith("↪️ MaaEnd") for l in body.splitlines()), True)
check("its note names the update", "MaaEnd 装新版 v2.31.0-beta.6 后自己重启，用掉一次重试，不算失败" in body, True)

print("\n[the title names the game: 10-01's full ledger shape]")
okww = [{"run_id": f"o{i}", "script": "OK-WW", "user": "wuwa", "started": at(h, 0).isoformat(),
         "finished": at(h + 2, 0).isoformat(), "ok": False, "failed_tasks": ["OK-WW 运行超时"], "raw": {}}
        for i, h in enumerate((9, 11, 13))]
done = dict(entries[-1], incomplete="MaaEnd 这一轮有 2 项没干成")
t_full, _ = core.format_daily("2026-10-01", okww + entries[:-1] + [done])
print("    " + t_full)
check("title", t_full, "📋 10-01 · 鸣潮失败 3 次、终末地 1 项没干完 ⚠️")

print("\n[a timeout clears only itself: a named task still undone keeps the record failed]")
mixed = [dict(entries[0], failed_tasks=["MaaEnd 进程超时", "据点交易"]),
         dict(entries[-1], raw=dict(entries[-1]["raw"], tasks_done=["赠送干员礼物"]))]
check("据点交易 not done later -> not retried", core.retried_notes(mixed), {})
mixed[1]["raw"]["tasks_done"].append("据点交易")
check("据点交易 done later -> retried", bool(core.retried_notes(mixed)), True)

print("\n[all tasks done, MaaEnd did not exit: not 「没干完」, named as such]")
from ark_relay import outcome  # noqa: E402
own = "2026-10-01 16:12:28 INFO  [Task] 实例 AUTO-MAS: 开始执行任务, 数量: 2\n"
hung_log = own + ("[2026-10-01 16:12:29] 任务开始: 🎁赠送干员礼物\n[2026-10-01 16:14:10] 任务完成: 🎁赠送干员礼物\n"
                  "[2026-10-01 16:58:19] 任务开始: ❌关闭游戏（PC）\n[2026-10-01 16:58:22] 任务完成: ❌关闭游戏（PC）\n")
shot = ["2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png"]
check("no-exit detected", outcome.maaend_no_self_exit(hung_log, own_log=True), True)
check("checks pass (screenshot counted as recovered)",
      outcome.summarize(outcome.maaend_checks(hung_log, shot, own_log=True), "MaaEnd"), None)
check("a failed task is still a failure",
      outcome.maaend_no_self_exit(hung_log + "[2026-10-01 16:59:00] 任务失败: 🧺自动采集\n", own_log=True), False)
print("    case 1: MaaEnd's own log not read (09-17 truncated shape)")
history_only = hung_log.replace(own, "")
check("not read -> not 「all done」", outcome.maaend_no_self_exit(history_only, own_log=False), False)
check("not read -> still 「MaaEnd 跑完」 failed",
      "MaaEnd 跑完" in [c.label for c in outcome.maaend_checks(history_only, [], own_log=False) if not c.ok], True)
print("    case 2: crashed between tasks - 16 scheduled, 2 began and finished")
crashed = hung_log.replace("数量: 2", "数量: 16")
check("unstarted scheduled tasks -> not 「all done」", outcome.maaend_no_self_exit(crashed, own_log=True), False)
check("…and 「MaaEnd 跑完」 failed",
      "MaaEnd 跑完" in [c.label for c in outcome.maaend_checks(crashed, [], own_log=True) if not c.ok], True)
hung = dict(entries[-1], raw=dict(entries[-1]["raw"], maaend_no_self_exit=29))
hung.pop("incomplete", None)
t_hung, b_hung = core.format_daily("2026-10-01", okww + entries[:-1] + [hung])
print("    " + t_hung)
check("title", t_hung, "📋 10-01 · 鸣潮失败 3 次、终末地任务全完成，但跑完没自己退出（空等 29 分钟） ⚠️")
check("no 「没干完」 anywhere", "没干完" in t_hung + b_hung, False)
check("row says it", "· 注意　终末地任务全完成，但跑完没自己退出（空等 29 分钟）" in b_hung, True)

print("\n[the idle minutes come from AUTO-MAS's own result line, onto the ledger]")
(TMP / "debug").mkdir(exist_ok=True)
(TMP / "debug" / "app.log").write_text(
    "2026-10-01 17:27:43.100 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放\n", encoding="utf-8")
e9 = build()
last = runs()[-1]
e9.state.append_ledger(last)
handle._mark_no_self_exit(e9, last)
row = {x["run_id"]: x for x in e9.state.read_ledger("2026-10-01")}[last.run_id]
check("16:58:22 -> 17:27:43 = 29 minutes on the ledger", (row.get("raw") or {}).get("maaend_no_self_exit"), 29)

print("\n[the update ate the last attempt -> no group alarm since 2026-10-05; the ledger says it]")
# A MaaEnd failure gets one make-up run and then goes to the daily report only
# (makeup.py); a day that has rolled over is past its make-up and is dropped.
e = build()
for r in runs(with_success=False):
    handle._handle(e, r)
e._flush_pending()
check("no alarm", alarms(e), [])
check("no longer held", dict(e._pending), {})
upd = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}["2026-10-01/endfield/MaaEnd-12-10-02"]
check("the ledger names the update", (upd.get("raw") or {}).get("maaend_update_restart"), "v2.31.0-beta.6")
check("the update attempt is counted: 2 attempts", handle._attempts(e, runs(False)[-1], "2026-10-01"), 2)

print("\n[no install lines in MXU's log -> an ordinary failure, as before]")
(MAAEND / "debug" / "2026-10-01-4.log").write_text("2026-10-01 16:11:06 INFO  [App] 启动\n", encoding="utf-8")
e = build()
for r in runs(with_success=False):
    handle._handle(e, r)
mid = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}["2026-10-01/endfield/MaaEnd-12-10-02"]
check("not marked", (mid.get("raw") or {}).get("maaend_update_restart"), None)
check("keeps AUTO-MAS's 15 tasks", len(mid.get("failed_tasks") or []), 15)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
