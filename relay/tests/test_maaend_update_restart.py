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
check("16:11:06 attempt installed beta.6", update_restart_version(MAAEND, at(16, 11, 6), at(16, 11, 6)),
      "v2.31.0-beta.6")
check("15:24 attempt only downloaded", update_restart_version(MAAEND, at(15, 24, 12), at(16, 10, 0)), "")
check("no MaaEnd dir", update_restart_version(None, at(16, 11, 6), at(16, 11, 6)), "")

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

print("\n[the update ate the last attempt -> the final alarm says so]")
e = build()
for r in runs(with_success=False):
    handle._handle(e, r)
e._flush_pending()
got = alarms(e)
check("one alarm", len(got), 1)
check("it names the update", bool(got) and "装新版 v2.31.0-beta.6" in got[0][1], True)

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
