"""AUTO-MAS's own MaaEnd update record is not a run; stage prefixes are not failures.

AUTO-MAS v5.7.0-beta.2 installs a MaaEnd update between stages and writes that
step as a history record of its own (app/task/MaaEnd/AutoProxy.py
_update_after_first_stage, the 「更新」 phase label at ~2203; Config.save_maaend_log
in app/core/config.py ~4387 puts 「[<label>] 」 in front of the result). Stage runs
get the same prefix: 「[送货]」「[日常]」「[自动采集]」 (app/utils/constants.py
MAAEND_RUN_MOOD_BOOK).

2026-10-12 Endfield, machine time (AUTO-MAS app.log lines 601-668 of
ark-evidence/daily/2026-10-12/automas-app-2026-10-12.log):
  10:04:00 MaaEnd-06-04-00  「MaaEnd 部分任务执行失败: ⚔️协议空间」  (Source stage, no prefix)
  10:58:11 MaaEnd-06-58-11  「[更新] Success!」  4 log lines, 「MaaEnd 已更新到 v2.33.0-beta.2」
  10:58:38 MaaEnd-06-58-38  「Success!」  (Source stage, attempt 2/3)
The relay booked the update record as a failed run, labelled it 「装新版 v2.33.0-beta.2
后自己重启，这一次重试被用掉」 and said 「跑了 3 次」 (relay-2026-10-12.log lines 472-483).
Should be: 2 runs, the first recovered by the retry, the update in the technical log only.

The raw history JSON/logs of that day are not on this Mac (the update record went to the
cloud evidence pack MaaEnd-06-58-11 only). The JSONs below are rebuilt from AUTO-MAS's
result lines and its save_maaend_log format; the update log is the four status lines
AUTO-MAS logged at 10:58:11-10:58:15; the MXU install lines are reconstructed to sit in
update_restart_version's window, as relay log line 475 shows they did.
"""
import json
import logging
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
HISTORY = TMP / "history"
MAAEND = TMP / "maaend"
(MAAEND / "debug").mkdir(parents=True)
os.environ.update(ARK_HISTORY_DIR=str(HISTORY), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import collector                        # noqa: E402
from ark_relay.core import engine as eng_mod                # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config        # noqa: E402
from ark_relay.core.ledger import State                    # noqa: E402
from ark_relay.features.alarm import handle, records       # noqa: E402
from ark_relay.features.makeup import collect_retry        # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[tuple[str, int, str]] = []

    def emit(self, r):
        self.lines.append((r.name, r.levelno, r.getMessage()))


grab = Grab()
logging.getLogger("ark").addHandler(grab)
logging.getLogger("ark").setLevel(logging.DEBUG)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


DAY = HISTORY / "2026-10-12" / "endfield"
DAY.mkdir(parents=True)


def write(stem, result, log_lines, mtime):
    (DAY / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False, indent=4),
                                      encoding="utf-8")
    (DAY / f"{stem}.log").write_text("".join(x + "\n" for x in log_lines), encoding="utf-8")
    t = datetime(2026, 10, 12, *mtime, tzinfo=SERVER_TZ).timestamp()
    for suffix in (".json", ".log"):
        os.utime(DAY / f"{stem}{suffix}", (t, t))


CLOSE = "❌关闭游戏（PC）"

# Attempt 1: 协议空间 fails, the round closes.
write("MaaEnd-06-04-00", "MaaEnd 部分任务执行失败: ⚔️协议空间", [
    "[2026-10-12 10:04:05.000] 窗口连接成功: Endfield",
    "[2026-10-12 10:05:19.000] 任务开始: 🎁赠送干员礼物",
    "[2026-10-12 10:07:43.000] 任务完成: 🎁赠送干员礼物",
    "[2026-10-12 10:07:43.100] 任务开始: 🔧装备制造",
    "[2026-10-12 10:08:02.000] 任务完成: 🔧装备制造",
    "[2026-10-12 10:08:02.100] 任务开始: ⚔️协议空间",
    "[2026-10-12 10:57:50.000] 任务失败: ⚔️协议空间",
    f"[2026-10-12 10:57:50.100] 任务开始: {CLOSE}",
    f"[2026-10-12 10:57:53.000] 任务完成: {CLOSE}",
], (11, 38, 13))
# AUTO-MAS's update step: its four status lines (AUTO-MAS app.log 605-608), no timestamps.
write("MaaEnd-06-58-11", "[更新] Success!", [
    "首阶段检测到 MaaEnd 更新，正在确认安装结果",
    "正在准备 MaaEnd 更新会话",
    "MaaEnd 正在检查并安装更新",
    "MaaEnd 已更新到 v2.33.0-beta.2",
], (11, 38, 13))
# Attempt 2: everything done.
write("MaaEnd-06-58-38", "Success!", [
    "[2026-10-12 10:58:40.000] 窗口连接成功: Endfield",
    "[2026-10-12 10:59:55.000] 任务开始: 🎁赠送干员礼物",
    "[2026-10-12 11:01:43.000] 任务完成: 🎁赠送干员礼物",
    "[2026-10-12 11:01:43.100] 任务开始: 🔧装备制造",
    "[2026-10-12 11:01:59.000] 任务完成: 🔧装备制造",
    "[2026-10-12 11:01:59.100] 任务开始: ⚔️协议空间",
    "[2026-10-12 11:30:00.000] 任务完成: ⚔️协议空间",
    f"[2026-10-12 11:38:05.000] 任务开始: {CLOSE}",
    f"[2026-10-12 11:38:08.000] 任务完成: {CLOSE}",
], (11, 38, 13))
# MXU's own log: the install AUTO-MAS triggered right after the update step began.
(MAAEND / "debug" / "2026-10-12-4.log").write_text("\n".join([
    "2026-10-12 10:58:12 INFO  [App] 检测到待安装更新: v2.33.0-beta.2",
    "2026-10-12 10:58:13 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11021.zip -> D:\\ark\\maaend",
    "2026-10-12 10:58:14 INFO  [App] 更新安装完成",
]) + "\n", encoding="utf-8")

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


def collector_lines(level):
    return [m for n, lv, m in grab.lines if n == "ark.collector" and lv == level]


print("[10-12 replay: the collector sees two runs, not three]")
got = collector.scan(HISTORY, set(), MAAEND)
check("run ids", [r.run_id.rsplit("/", 1)[1] for r in got], ["MaaEnd-06-04-00", "MaaEnd-06-58-38"])
check("verdicts", [(r.ok, r.failed_tasks) for r in got], [(False, ["协议空间"]), (True, [])])
update_info = [m for m in collector_lines(logging.INFO) if "MaaEnd-06-58-11" in m]
check("the update is one technical-log line", len(update_info), 1)
check("it carries AUTO-MAS's words", bool(update_info) and "[更新] Success!" in update_info[0], True)
check("no collector warning (group) for it", collector_lines(logging.WARNING), [])
collector.scan(HISTORY, {r.run_id for r in got}, MAAEND)
check("the next scan does not log it again",
      len([m for m in collector_lines(logging.INFO) if "MaaEnd-06-58-11" in m]), 1)

print("\n[10-12 replay through the handler: recovered on retry, no update label]")
grab.lines.clear()
e = build()
for r in got:
    handle._handle(e, r)
e._flush_pending()
ledger = e.state.read_ledger("2026-10-12")
check("ledger rows", [x["run_id"].rsplit("/", 1)[1] for x in ledger], ["MaaEnd-06-04-00", "MaaEnd-06-58-38"])
check("no 「重试被用掉」 anywhere in the ledger",
      any("重试被用掉" in t for x in ledger for t in x.get("failed_tasks") or []), False)
check("no update-restart mark", [(x.get("raw") or {}).get("maaend_update_restart") for x in ledger], [None, None])
check("attempts", records._attempts(e, got[-1], "2026-10-12"), 2)
healed = [m for n, lv, m in grab.lines if "自己好了" in m]
check("one recovery line", len(healed), 1)
check("it says a retry healed it, ran 2 times",
      bool(healed) and healed[0].startswith("⚠️ MaaEnd 中途失败过，重试后成功") and "跑了 2 次" in healed[0], True)
check("nothing says 重试被用掉", [m for n, lv, m in grab.lines if "重试被用掉" in m], [])
# (Machine-check pushes about task-end pictures fire here because the fixture has none;
# they are not about this record.)
check("no push mentions the update", [t for t, b, a in e.notifier.sent if "更新" in t + b], [])


def judge(stem, result, log_lines=("[2026-10-13 12:00:00.000] 窗口连接成功: Endfield",)):
    d = HISTORY / "2026-10-13" / "endfield"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False), encoding="utf-8")
    (d / f"{stem}.log").write_text("".join(x + "\n" for x in log_lines), encoding="utf-8")
    return collector.parse_record(d / f"{stem}.json", HISTORY, MAAEND)


print("\n[stage prefixes are stripped before judging]")
r = judge("MaaEnd-01-00-00", "[日常] Success!")
check("[日常] Success! is a success", (r.ok, r.failed_tasks), (True, []))
r = judge("MaaEnd-01-00-01", "[自动采集] MaaEnd 部分任务执行失败: 🧺自动采集")
check("[自动采集] failure names its task", (r.ok, r.failed_tasks), (False, ["自动采集"]))
r = judge("MaaEnd-01-00-02", "[送货] 未捕获到日志")
check("[送货] stub stays transitional", (r.ok, r.transitional), (False, True))

print("\n[update records]")
grab.lines.clear()
check("[更新] 跳过更新 is not a run", judge("MaaEnd-01-00-03", "[更新] 跳过更新"), None)
check("…technical log only", ([m for m in collector_lines(logging.INFO) if "MaaEnd-01-00-03" in m] != [],
                              collector_lines(logging.WARNING)), (True, []))
upd_fail = "MaaEnd 更新失败，已停止后续任务: MXU 日志报告安装失败，已停止后续任务"
r = judge("MaaEnd-06-58-11", f"[更新] {upd_fail}", [upd_fail])
check("a failed update is a real failure", (r.ok, r.failed_tasks), (False, [upd_fail]))
r.started = datetime(2026, 10, 12, 10, 58, 11, tzinfo=SERVER_TZ)   # inside the MXU install window
records._mark_update_restart(build(), r)
check("…the restart rule leaves it alone", (r.transitional, r.raw.get("maaend_update_restart")), (False, None))
r = judge("MaaEnd-01-00-05", "[更新] MaaEnd 更新被中止")
check("an aborted update is a real failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 更新被中止"]))

print("\n[a failed update through the handler: booked as a failure, not as an update restart]")
d14 = HISTORY / "2026-10-14" / "endfield"
d14.mkdir(parents=True)
(d14 / "MaaEnd-06-58-11.json").write_text(json.dumps({"maaend_result": f"[更新] {upd_fail}"}, ensure_ascii=False),
                                          encoding="utf-8")
(d14 / "MaaEnd-06-58-11.log").write_text(upd_fail + "\n", encoding="utf-8")
(MAAEND / "debug" / "2026-10-14-1.log").write_text(
    "2026-10-14 10:58:12 INFO  [App] 检测到待安装更新: v9.9.9\n2026-10-14 10:58:14 INFO  [App] 更新安装完成\n",
    encoding="utf-8")
e14 = build()
for rec in collector.scan(HISTORY, {x["run_id"] for d in ("2026-10-12", "2026-10-13")
                                    for x in e.state.read_ledger(d)} | {r.run_id for r in got}, MAAEND):
    if rec.run_id.startswith("2026-10-14/"):
        handle._handle(e14, rec)
row = {x["run_id"]: x for x in e14.state.read_ledger("2026-10-14")}.get("2026-10-14/endfield/MaaEnd-06-58-11") or {}
check("booked, failed, with AUTO-MAS's words, not relabelled",
      (row.get("ok"), row.get("failed_tasks"), (row.get("raw") or {}).get("maaend_update_restart"), row.get("transitional")),
      (False, [upd_fail], None, False))

print("\n[an unknown prefix is not judged a success]")
grab.lines.clear()
r = judge("MaaEnd-01-00-06", "[新阶段] Success!")
check("booked as a failure with AUTO-MAS's words", (r.ok, r.failed_tasks), (False, ["[新阶段] Success!"]))
said = [m for m in collector_lines(logging.INFO) if "[新阶段]" in m]
check("one technical-log line naming the prefix, no group warning",
      (len(said), collector_lines(logging.WARNING)), (1, []))
judge("MaaEnd-01-00-06", "[新阶段] Success!")
check("not repeated on the next read", len([m for m in collector_lines(logging.INFO) if "[新阶段]" in m]), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
