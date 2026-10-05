"""Machine checks of the relay's own machinery (ark_relay/machinechecks/system.py).

The user, 2026-10-06 04:59: the machine must check the open ledger items by itself
after a deploy, instead of a person reading logs. Each check here gets a realistic
input that passes and a broken one that fails - and every FAIL is pushed to the
group (alert=True) - and the wiring at the natural point is driven for real: the
last boot stage reading the previous session of relay.log, unresolved.send, the
overrun check, the make-up, the MaaEnd pre-update, the watchdog, the desktop agent's
trace, the busy-snapshot note and the game-update stage. The relay.log lines below
have the shape __main__._setup_logging writes; their texts are the ones the modules
log (quoted next to each constant in system.py).
"""
import json
import logging
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for _name in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
              "servicemanager", "win32process", "pythoncom"):
    sys.modules.setdefault(_name, _Stub(_name))

import boot_stages  # noqa: E402
from ark_relay import machinecheck as mc  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402
from ark_relay.machinechecks import system as sysmc  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class N:
    """A notifier that keeps what was sent; with `copies`, it also writes the alarm
    copy the way notify.Notifier does for a delivered group alarm (alertlog)."""

    def __init__(self, copies=True):
        self.sent = []
        self.copies = copies
        self.state_dir = None

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        if self.copies and alert and self.state_dir:
            from ark_relay import alertlog  # noqa: PLC0415
            alertlog.AlertLog(self.state_dir).record(title, body)
        return []

    def alert_log(self):
        return None

    def fails(self, cid):
        return [b for t, b, a in self.sent if t.startswith(f"🔬 上机核对没过：{cid} ") and a]


NOW = datetime(2026, 10, 7, 8, 50, tzinfo=SERVER_TZ)


def judge(event, ctx, d, n=None):
    n = n or N()
    got = dict(mc.judge(d, event, ctx, notifier=n, now=NOW))
    return got, n


def L(stamp, msg, level="INFO", name="ark.service", more=()):
    return "\n".join([f"{stamp} {level:<7} {name}  {msg}", *more])


START = "服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）"
MARK = "中继代码版本 v20261006120000"
BOOT_NOW = [L("10-07 08:46:10", START), L("10-07 08:46:10", MARK)]


def write_log(lines):
    d = tmpdir()
    f = d / "relay.log"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d, f


def at_boot(lines, d=None):
    """Judge the boot event against a relay.log made of `lines` (then this boot)."""
    sd, f = write_log(list(lines) + BOOT_NOW)
    sd = d or sd
    got, n = judge("boot", {"log_file": str(f)}, sd)
    return got, n, sd, f


EVENING = [
    L("10-06 21:20:05", START), L("10-06 21:20:05", MARK),
    L("10-06 21:20:40", "📱 已上报状态到手机（开机；今天 ntfy 已用 12 条）"),
    L("10-06 21:58:01", "📱 已上报状态到手机（关机前；今天 ntfy 已用 20 条）"),
    L("10-06 21:58:03", "本轮已处理完毕，60 秒后关机", name="ark.engine"),
    L("10-06 21:59:04", "中继自己发出了关机命令，AUTO-MAS 后台此时退出（退出码 0x1），按关机处理，不算故障，不再重新打开它"),
    L("10-06 21:59:05", "收到停止通知（Windows 关机）"),
    L("10-06 21:59:05", "收到停止信号，退出"),
    L("10-06 21:59:09", "📱 已上报状态到手机（停止前；今天 ntfy 已用 21 条）"),
    L("10-06 21:59:09", "主流程已返回，向 SCM 报告已停止；还活着的线程：phone-heartbeat"),
]

print("[#11 停服务时推最后一份状态：上一段日志里收到停止通知，停止前那份送到了 → 过]")
got, n, sd, f = at_boot(EVENING)
check("#11 过了", got["#11"].status, mc.PASS)
check("依据是停止通知和送达那一行", got["#11"].evidence,
      "10-06 21:59:05 收到停止通知（Windows 关机）；10-06 21:59:09 📱 已上报状态到手机（停止前；今天 ntfy 已用 21 条）")
again, n2 = judge("boot", {"log_file": str(f)}, sd)
check("下次开机读到的还是同一段：不再判", "#11" in again, False)

print("[#11 停止前那份没送出去（日志说了原因）→ 没过，进群]")
bad = [x if "停止前；" not in x else L("10-06 21:59:09", "状态没能上报到手机（停止前）：COS 403；手机上留着上一份状态",
                                         level="WARNING") for x in EVENING]
got, n, _, _ = at_boot(bad)
check("#11 没过", got["#11"].status, mc.FAIL)
check("推了一条，带原因", any("COS 403" in b for b in n.fails("#11")), True)

print("[#11 中继自己关机时停止前那份没来得及，关机前那份已送到 → 过，写明]")
cut = [x for x in EVENING if "停止前；" not in x and "主流程已返回" not in x]
got, n, _, _ = at_boot(cut)
check("#11 过了", got["#11"].status, mc.PASS)
check("说的是关机前那份", "关机前那份已送到" in got["#11"].evidence, True)

print("[#11 不是中继关的机（手动关机），停止前那份没出来 → 没过]")
manual = [x for x in cut if "关机前；" not in x and "60 秒后关机" not in x and "此时退出" not in x]
got, n, _, _ = at_boot(manual)
check("#11 没过", got["#11"].status, mc.FAIL)
check("说中继先停下了", "中继先停下了" in got["#11"].evidence, True)

print("[#11 上一个进程没收到停止通知就没了（Windows 关机没通知到中继）→ 没过]")
died = EVENING[:4]
got, n, _, _ = at_boot(died)
check("#11 没过", got["#11"].status, mc.FAIL)
check("依据是那一段的最后一行", got["#11"].evidence.endswith("10-06 21:58:01 📱 已上报状态到手机（关机前；今天 ntfy 已用 20 条）"), True)

print("[#11 上一段是部署前的老代码（没有版本那一行）→ 不判；自更新那一段跳过，判再前一段]")
old = [x for x in EVENING if MARK not in x]
got, _, _, _ = at_boot(old)
check("老代码不判", "#11" in got, False)
selfupd = [L("10-07 08:45:50", START), L("10-07 08:45:50", MARK),
           L("10-07 08:46:01", "代码已更新，重启以立即生效: ark_relay/engine.py")]
got, _, _, _ = at_boot(EVENING + selfupd)
check("跳过自更新那一段，判前一晚", got["#11"].evidence.startswith("10-06 21:59:05"), True)

print("\n[#37/#38 中继自己关机后：后台退出按关机处理、没去重开 → 都过]")
got, n, _, _ = at_boot(EVENING)
check("#37 过了", got["#37"].status, mc.PASS)
check("#37 依据是「按关机处理」那一行", "按关机处理，不算故障" in got["#37"].evidence, True)
check("#38 过了", got["#38"].status, mc.PASS)
print("[#37/#38 关机后后台「意外退出」、中继去重开 → 都没过，进群]")
broke = EVENING[:5] + [
    L("10-06 21:59:04", "AUTO-MAS 后台意外退出了（退出码 0x1，窗口也没了，当时机器没在关机，也没在装更新）；重新起来了写进日报，查 3 次还没起来报到群里"),
    L("10-06 21:59:04", "AUTO-MAS 没在运行，中继正在重新打开它（第 1 次）"),
] + EVENING[6:]
got, n, _, _ = at_boot(broke)
check("#37 没过", got["#37"].status, mc.FAIL)
check("#38 没过", got["#38"].status, mc.FAIL)
check("两条都推了", (len(n.fails("#37")), len(n.fails("#38"))), (1, 1))
check("#38 依据是重开那一行", "中继正在重新打开它" in got["#38"].evidence, True)
got, _, _, _ = at_boot(manual)
check("不是中继关的机：#37/#38 不判", ("#37" in got, "#38" in got), (False, False))

print("\n[#59 系统的程序启动通知断了又自己订上：只进日报（errkinds 记成自己好了），diag 说出是哪种]")
WMI = ("系统的程序启动通知断过 12 秒（远程过程调用失败，0x800706BE），已经自己重新订上")
DIAG = ("diag: hresult 0x80020009, scode 0x800706BE, source SWbemEventSource, text 远程过程调用失败。; "
        "subscription up 37.0 s, 0 events, last -; relay up 37 s; machine up 0:12:01; "
        "WMI hosts at subscribe [winmgmt pid 1234; WmiPrvSE pids 5,6] now [winmgmt pid 1234; WmiPrvSE pids 6]; "
        "hypothesis: H2 WMI provider host gone (WmiPrvSE pid 5)")
wmi_session = EVENING[:3] + [L("10-06 21:25:00", WMI, level="WARNING", more=[DIAG])] + EVENING[3:]


def errkinds(sd, line, recovered=True):
    (sd / "errkinds").mkdir(parents=True, exist_ok=True)
    (sd / "errkinds" / "2026-10-06.json").write_text(json.dumps(
        {"ark.service|x": {"first": "2026-10-06 21:25:00", "count": 1, "pushed": 0, "level": "WARNING",
                           "where": "ark.service", "line": line, **({"recovered": True} if recovered else {})}},
        ensure_ascii=False), encoding="utf-8")


sd, f = write_log(wmi_session + BOOT_NOW)
errkinds(sd, WMI)
got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
check("#59 过了", got["#59"].status, mc.PASS)
check("说出原因（H2）", got["#59"].evidence.endswith("原因：WMI 的提供程序宿主（WmiPrvSE）没了一个"), True)
sd, f = write_log(wmi_session + BOOT_NOW)
errkinds(sd, WMI, recovered=False)
got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
check("errkinds 没记成自己好了 → 没过", got["#59"].status, mc.FAIL)
sd, f = write_log(wmi_session + BOOT_NOW)
errkinds(sd, WMI)
(sd / "alerts").mkdir()
(sd / "alerts" / "20261006.jsonl").write_text(json.dumps({"title": "🩺 中继自己报错", "text": "ark.service：" + WMI}, ensure_ascii=False) + "\n", encoding="utf-8")
got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
check("自己好了却进了群 → 没过", (got["#59"].status, "进了群" in got["#59"].evidence), (mc.FAIL, True))
old_diag = DIAG.split("; hypothesis:")[0]
sd, f = write_log(EVENING[:3] + [L("10-06 21:25:00", WMI, level="WARNING", more=[old_diag])] + EVENING[3:] + BOOT_NOW)
errkinds(sd, WMI)
got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
check("diag 说不出是哪种 → 没过，原样带上 diag", (got["#59"].status, "WMI hosts at subscribe" in got["#59"].evidence),
      (mc.FAIL, True))
got, _, _, _ = at_boot(EVENING)
check("没断过：不判", "#59" in got, False)

print("\n[#63 开机后 state.json 里没有 maaend_disabled_spmed 了 → 过；还在 → 没过]")
from ark_relay.statestore import StateStore  # noqa: E402
sd = tmpdir()
got, n = judge("boot", {}, sd)
check("#63 过了", got["#63"].status, mc.PASS)
StateStore(sd).set("updates", "maaend_disabled_spmed", {"tasks": ["AutoUseSpMedication"], "since": "2026-09-03"})
got, n = judge("boot", {}, sd)
check("#63 没过", got["#63"].status, mc.FAIL)
check("依据带那条记录", "AutoUseSpMedication" in got["#63"].evidence, True)
check("推了", len(n.fails("#63")), 1)

print("\n[#14 往返核对：机器核不了，写明原因]")
check("#14 在核不了的单子上", "#14" in mc.CANNOT, True)
check("原因一句话", "机器自己从不改它" in mc.CANNOT["#14"][1], True)

print("\n[#17 预更新前终末地程序开着：先关掉再改设置 → 过；关不掉 → 没过；没开着 → 不判]")
got, _ = judge("preupdate", {"script": "MaaEnd", "steps": [{"open_before": [4321], "left": []}]}, tmpdir())
check("#17 过了", got["#17"].status, mc.PASS)
got, n = judge("preupdate", {"script": "MaaEnd", "steps": [{"open_before": [4321], "left": [4321]}]}, tmpdir())
check("#17 没过，推了", (got["#17"].status, len(n.fails("#17"))), (mc.FAIL, 1))
got, _ = judge("preupdate", {"script": "MaaEnd", "steps": [{"open_before": None, "left": None}]}, tmpdir())
check("进程表读不到 → 没过", got["#17"].status, mc.FAIL)
got, _ = judge("preupdate", {"script": "MaaEnd", "steps": [{"open_before": [], "left": []}]}, tmpdir())
check("没开着：不判", "#17" in got, False)

print("\n[#18 调度程序开着非自动代理的任务：快照算在忙 → 过；算不忙 → 没过；判过的不再判]")
sd = tmpdir()
(sd / sysmc.BUSY_FILE).write_text(json.dumps({"seen": [
    {"at": "10-06 20:01:02", "task": "ab12", "mode": "ScriptConfig", "busy": True, "line": "快照里列着、没完成：MAA 运行"}]},
    ensure_ascii=False), encoding="utf-8")
got, _ = judge("boot", {}, sd)
check("#18 过了", got["#18"].status, mc.PASS)
got, _ = judge("boot", {}, sd)
check("判过的不再判", "#18" in got, False)
(sd / sysmc.BUSY_FILE).write_text(json.dumps({"seen": [
    {"at": "10-06 20:05:00", "task": "cd34", "mode": "ScriptConfig", "busy": False, "line": "调度程序日志 20:04:10 创建任务 cd34"}]},
    ensure_ascii=False), encoding="utf-8")
got, n = judge("boot", {}, sd)
check("#18 没过，推了", (got["#18"].status, len(n.fails("#18"))), (mc.FAIL, 1))

print("\n[#21/#34 报警真的进了群（报警抄送里有这一条）→ 过；抄送里没有 → 没过]")
for cid, kind in (("#21", "手动"), ("#34", "未解决")):
    sd = tmpdir()
    n = N()
    n.state_dir = sd
    title, body = "❌ 明日方舟早班没跑成", f"{'这一趟是有人在 AUTO-MAS 上手动开的，不是定时开的。' if kind == '手动' else ''}卡在 开始唤醒"
    n.send(title, body, alert=True)
    ctx = {"kind": kind, "run_id": "2026-10-06/arknights/MAA-09-05-00", "title": title, "body": body,
           "sent": True, "copies": True}
    got, _ = judge("unresolved", ctx, sd)
    check(f"{cid} 过了", got[cid].status, mc.PASS)
    got, n2 = judge("unresolved", ctx, tmpdir())
    check(f"{cid} 抄送里没有：没过，推了", (got[cid].status, len(n2.fails(cid))), (mc.FAIL, 1))
    got, _ = judge("unresolved", dict(ctx, copies=False), tmpdir())
    check(f"{cid} 发送方不留抄送：不判", cid in got, False)
got, _ = judge("unresolved", {"kind": "理智", "run_id": "x", "title": "t", "body": "b", "sent": True, "copies": True}, tmpdir())
check("别的种类不归 #21/#34", ("#21" in got, "#34" in got), (False, False))

print("\n[#55 班次超时：有人手动开的不报 → 过；报的是班次自己的 → 过；日志里找不到是谁开的 → 没过]")
base = {"kind": "队列超时", "queue": "晚班", "hhmm": "21:30", "task_id": "68b6e221"}
got, _ = judge("unresolved", dict(base, alarmed=False, create="10-03 00:19:50 创建任务 68b6e221，模式 AutoProxy，触发来源 manual_task"), tmpdir())
check("#55 手动的没报：过", got["#55"].status, mc.PASS)
got, _ = judge("unresolved", dict(base, alarmed=True, sent=True, create="09-25 21:30:00 创建任务 e715210d，模式 AutoProxy，触发来源 scheduled_task"), tmpdir())
check("#55 班次自己的报了：过", got["#55"].status, mc.PASS)
got, n = judge("unresolved", dict(base, alarmed=True, sent=True, create=""), tmpdir())
check("#55 找不到是谁开的：没过，推了", (got["#55"].status, len(n.fails("#55"))), (mc.FAIL, 1))

print("\n[#31 看门狗结束 MaaEnd：进程表里没了 → 过；还在 / 结束不了 / 读不到 → 没过]")
res = {"pid": 30000, "reason": "插件崩溃", "ok": True, "why": "", "gone": True, "waited": 30}
got, _ = judge("watchdog", {"action": "kill", "result": res}, tmpdir())
check("#31 过了", got["#31"].status, mc.PASS)
for label, extra in (("还在", {"gone": False}), ("结束不了", {"ok": False, "gone": False, "why": "退出码 128"}),
                     ("读不到", {"gone": None})):
    got, n = judge("watchdog", {"action": "kill", "result": dict(res, **extra)}, tmpdir())
    check(f"#31 {label}：没过，推了", (got["#31"].status, len(n.fails("#31"))), (mc.FAIL, 1))

print("\n[#32 关机前补跑采集路线：跑出结论 → 过；没结论 → 没过]")
done = {"routes": ["AutoCollectRoute15", "AutoCollectRoute16"], "passed": ["AutoCollectRoute16"],
        "failed": ["AutoCollectRoute15"], "unknown": [], "note": "",
        "nodes": {"AutoCollectRoute16": "[2026-10-06 21:40:01.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute16End\"}"}}
labels = {"AutoCollectRoute15": "路线15：红矛叶", "AutoCollectRoute16": "路线16：协议纹石"}
got, _ = judge("makeup", {"kind": "采集路线", "result": done, "labels": labels}, tmpdir())
check("#32 过了", got["#32"].status, mc.PASS)
check("依据带 maafw.log 那一行", "AutoCollectRoute16End" in got["#32"].evidence, True)
got, n = judge("makeup", {"kind": "采集路线", "result": dict(done, unknown=["AutoCollectRoute15"],
                                                           note="MaaEnd 起来 60 秒了还不响应"), "labels": labels}, tmpdir())
check("#32 没结论：没过，推了", (got["#32"].status, len(n.fails("#32"))), (mc.FAIL, 1))

from ark_relay import collect_retry as cr  # noqa: E402
maafw = ("[2026-10-06 21:20:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15End\"}\n"
         "[2026-10-06 21:40:01.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute16End\"}\n"
         "[2026-10-06 21:41:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15Failed\"}\n")
nodes = cr.node_lines(maafw, ["AutoCollectRoute15", "AutoCollectRoute16"], "21:30:00")
check("补跑判结论用的那几行 maafw.log 留下来（窗口之前那次不算）",
      {k: v.split('"name":"')[1][:-2] for k, v in nodes.items()},
      {"AutoCollectRoute15": "AutoCollectRoute15Failed", "AutoCollectRoute16": "AutoCollectRoute16End"})

print("\n[#33 补跑：派下去、记录落地 → 过；没跑出记录 / 没跑成 → 没过；按规矩不补 → 不判]")
ent = {"result": "ok", "record": "2026-10-06/endfield/MaaEnd-14-02-11", "dispatched_at": "2026-10-06T14:01:30+08:00"}
got, _ = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": ent}, tmpdir())
check("#33 走通：过", got["#33"].status, mc.PASS)
got, _ = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": dict(ent, result="failed", note="基质刷取")}, tmpdir())
check("#33 补跑也没成（但跑了）：过", got["#33"].status, mc.PASS)
got, n = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": {"result": "no_record", "dispatched_at": ent["dispatched_at"]}}, tmpdir())
check("#33 没跑出记录：没过，推了", (got["#33"].status, len(n.fails("#33"))), (mc.FAIL, 1))
got, _ = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": {"result": "gave_up", "note": "找不到终末地的母本"}}, tmpdir())
check("#33 没跑成：没过", got["#33"].status, mc.FAIL)
got, _ = judge("makeup", {"kind": "补跑", "script": "MAA", "result": {"result": "gave_up", "note": "不补跑：调试模式开着"}}, tmpdir())
check("#33 按规矩不补：不判", "#33" in got, False)

print("\n[#65 明日方舟没进游戏：中继还不写 maa_unreachable → 没过，带上存下的日志；同一条只判一次]")
sd = tmpdir()
cap = {"gui": 3, "asst": 2, "path": "state/machinecheck/maa-not-started/x.log", "last": "[2026-10-06 09:05:30][ERR] 连接失败"}
ctx = {"kind": "没进游戏", "script": "MAA", "run_id": "2026-10-06/arknights/MAA-09-05-00", "failed": "开始唤醒", "captured": cap}
got, n = judge("makeup", ctx, sd)
check("#65 没过，推了", (got["#65"].status, len(n.fails("#65"))), (mc.FAIL, 1))
check("依据带存下的日志路径和最后一行", ("x.log" in got["#65"].evidence, "连接失败" in got["#65"].evidence), (True, True))
got, _ = judge("makeup", ctx, sd)
check("同一条不再判", "#65" in got, False)
got, _ = judge("makeup", dict(ctx, run_id="2026-10-06/arknights/MAA-21-30-00", written=True), sd)
check("写了 maa_unreachable：过", got["#65"].status, mc.PASS)

print("\n[#60 桌面助手：找不到窗口传回 focus_missing、不点；两个字整行才点]")
agent_missing = {"what": "agent", "focus": "Games", "acts": ["ocr"], "clicks": False, "focus_missing": True,
                 "log": ["focus: 没有 Games 的窗口", "ocr 3 行"], "clicked": []}
click_ok = {"what": "agent", "focus": "Endfield", "acts": ["click_text"], "text": "确认", "clicks": True,
            "focus_missing": False, "log": ["focus: Endfield 「Endfield」", "click_text: 点了「确认」", "click 960,700"],
            "clicked": [[960, 700]]}
got, _ = judge("gameupdate", {"screens": [agent_missing, click_ok]}, tmpdir())
check("#60 过了", got["#60"].status, mc.PASS)
old_agent = dict(agent_missing, focus_missing=False)
got, n = judge("gameupdate", {"screens": [old_agent]}, tmpdir())
check("#60 没传回 focus_missing：没过，推了", (got["#60"].status, len(n.fails("#60"))), (mc.FAIL, 1))
clicked_anyway = dict(agent_missing, acts=["click_text"], clicks=True, text="更新游戏", clicked=[[1, 2]])
got, _ = judge("gameupdate", {"screens": [clicked_anyway]}, tmpdir())
check("#60 找不到窗口还点了：没过", got["#60"].status, mc.FAIL)
wrong_line = dict(click_ok, log=["click_text: 点了「确认更新」"])
got, _ = judge("gameupdate", {"screens": [wrong_line]}, tmpdir())
check("#60 两个字点到别的行：没过", got["#60"].status, mc.FAIL)
got, _ = judge("gameupdate", {"screens": [dict(click_ok, log=["click 960,700"])]}, tmpdir())
check("#60 没说点的是哪行：没过", got["#60"].status, mc.FAIL)

print("\n[#61 启动器下载时屏上的字：认出「正在下载」→ 过；一个也认不出 → 没过]")
waiting = {"what": "launcher", "game": "终末地", "stage": "wait", "unread": "", "busy": "正在下载", "ready": False,
           "line": "正在下载 1.2GB/8.5GB", "dump": "正在下载 1.2GB/8.5GB / 暂停", "shot": "shot-1.png"}
got, _ = judge("gameupdate", {"screens": [waiting]}, tmpdir())
check("#61 过了", got["#61"].status, mc.PASS)
unknown = dict(waiting, busy="", line="", dump="版本更新公告 / 活动")
got, n = judge("gameupdate", {"screens": [waiting, unknown]}, tmpdir())
check("#61 认不出：没过，推了", (got["#61"].status, len(n.fails("#61"))), (mc.FAIL, 1))

print("\n[#62 方舟预热点满 5 下：后来到了登录界面 → 过；没到 → 没过；没点满 → 不判]")
pre = {"what": "ak_prewarm", "taps": 5, "full": True, "reached": True, "dump_after": "START", "shot_after": "s5.png",
       "dump_last": "", "shot_last": ""}
got, _ = judge("gameupdate", {"screens": [pre]}, tmpdir())
check("#62 过了", got["#62"].status, mc.PASS)
got, n = judge("gameupdate", {"screens": [dict(pre, reached=False, dump_last="网络连接异常 / 点击重试")]}, tmpdir())
check("#62 没到：没过，推了", (got["#62"].status, len(n.fails("#62"))), (mc.FAIL, 1))
got, _ = judge("gameupdate", {"screens": [dict(pre, taps=2, full=False)]}, tmpdir())
check("#62 没点满：不判", "#62" in got, False)

print("\n[#64 终末地公告读不到：报警进了群 → 过；抄送里没有 → 没过]")
sd = tmpdir()
n = N()
n.state_dir = sd
probs = ["终末地：官方公告读不到，今天有没有版本更新不知道"]
title, body = "⚠️ 游戏更新有 1 项没能确认", "· " + probs[0]
n.send(title, body, alert=True)
gctx = {"problems": probs, "title": title, "body": body, "sent": True, "copies": True}
got, _ = judge("gameupdate", gctx, sd)
check("#64 过了", got["#64"].status, mc.PASS)
got, n2 = judge("gameupdate", gctx, tmpdir())
check("#64 抄送里没有：没过，推了", (got["#64"].status, len(n2.fails("#64"))), (mc.FAIL, 1))
got, _ = judge("gameupdate", dict(gctx, problems=["鸣潮：官方公告读不到，今天是不是维护日不知道"]), sd)
check("别的问题不归 #64", "#64" in got, False)

# ------------------------------------------------------------------ wiring

print("\n[接线：最后一个开机步骤读上一段 relay.log 判 #11/#37/#38/#63]")
sd, f = write_log(EVENING + BOOT_NOW)
n = N()
cfg = types.SimpleNamespace(state_dir=sd)
saved_env = os.environ.get("ARK_LOG_FILE")
os.environ["ARK_LOG_FILE"] = str(f)
try:
    boot_stages._stage_machinecheck(cfg, n, logging.getLogger("ark.service"))
finally:
    if saved_env is None:
        os.environ.pop("ARK_LOG_FILE", None)
    else:
        os.environ["ARK_LOG_FILE"] = saved_env
rows = mc.read(sd)
check("记进了 machinecheck.json", {k: rows.get(k, {}).get("status") for k in ("#11", "#37", "#38", "#63")},
      {"#11": "PASS", "#37": "PASS", "#38": "PASS", "#63": "PASS"})
check("事件是开机", rows.get("#11", {}).get("event"), "boot")
src = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
check("开机写那一行的字和核对认的字一样", f'log.info("{sysmc.CODE_MARK} v%s"' in src, True)
check("service.main 最后跑这一步", "boot_stages._stage_machinecheck(cfg, notifier, log)\n        _loop(" in
      (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8"), True)

print("\n[接线：unresolved.send 推出去后判 #21/#34（真抄送）]")
from ark_relay import engine as eng_mod, unresolved  # noqa: E402
from ark_relay.config import Config  # noqa: E402
from ark_relay.core import State  # noqa: E402


class Src:
    def fetch(self, seen):
        return []


def engine(sd, n):
    cfg = Config()
    cfg.state_dir = sd
    cfg.automas_dir = None
    return eng_mod.Engine(cfg, source=Src(), state=State(sd), notifier=n)


sd = tmpdir()
n = N()
n.state_dir = sd
e = engine(sd, n)
unresolved.send(e, "2026-10-06", "手动", "2026-10-06/arknights/MAA-01-02-03", "❌ 明日方舟晚班没跑成",
                "这一趟是有人在 AUTO-MAS 上手动开的，不是定时开的。\n卡在 开始唤醒")
check("#21 记了过", mc.read(sd).get("#21", {}).get("status"), "PASS")
sd = tmpdir()
n = N(copies=False)
e = engine(sd, n)
unresolved.send(e, "2026-10-06", "未解决", "2026-10-06/arknights/MAA-09-05-00", "❌ 明日方舟早班没跑成", "补跑也没成")
check("#34 抄送里没有：记了没过", mc.read(sd).get("#34", {}).get("status"), "FAIL")
check("…并且进群", len(n.fails("#34")), 1)

print("\n[接线：班次超时检查——有人手动开的任务不报，#55 记过（依据是 app.log 那一行）]")
from ark_relay import runwatch  # noqa: E402
sd = tmpdir()
automas = tmpdir()
(automas / "debug").mkdir()
(automas / "debug" / "app.log").write_text(
    "2026-10-03 00:19:50.991 | INFO     | 业务调度 | 创建任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy, 触发来源: manual_task\n",
    encoding="utf-8")
n = N()
e = engine(sd, n)
e.cfg.automas_dir = automas
q = {"name": "晚班", "uid": "q-evening"}
saved = runwatch.overrun_moments
runwatch.overrun_moments = lambda eng, now: iter([(q, "21:30", "q-evening", datetime(2026, 10, 2, 21, 30, tzinfo=SERVER_TZ),
                                                   19, datetime(2026, 10, 2, 22, 19, tzinfo=SERVER_TZ))])
try:
    runwatch.check_overrun(e, datetime(2026, 10, 3, 0, 43, tzinfo=SERVER_TZ), {"tasks": [
        {"taskId": "68b6e221-419d-444b-aff7-8643822c64ce", "queueId": "q-evening", "mode": "AutoProxy",
         "task_info": [{"name": "MAA", "status": "运行"}]}]})
finally:
    runwatch.overrun_moments = saved
check("没报超时", [t for t, _, a in n.sent if a], [])
row = mc.read(sd).get("#55", {})
check("#55 记了过", row.get("status"), "PASS")
check("依据是 app.log 的 manual_task 那一行", "触发来源 manual_task" in row.get("evidence", ""), True)

print("\n[接线：明日方舟没进游戏 → 存下 MAA 自己的 gui.log / asst.log 那一段，#65 没过并进群，同一条只一次]")
from ark_relay import makeup  # noqa: E402
from ark_relay.config import RunRecord  # noqa: E402
sd = tmpdir()
maa = tmpdir()
(maa / "debug").mkdir()
(maa / "debug" / "gui.log").write_text("[2026-10-06 08:00:00][INF] 早上那趟\n[2026-10-06 09:05:10][INF] 开始唤醒\n"
                                       "[2026-10-06 09:05:40][ERR] 连接模拟器失败\n", encoding="utf-8")
(maa / "debug" / "asst.log").write_text("[2026-10-06 09:05:12.100][INF] Connect\n  continued line\n"
                                        "[2026-10-06 09:20:00.000][INF] 下一趟\n", encoding="utf-8")
n = N()
e = engine(sd, n)
e.cfg.maa_dir = maa
rec = RunRecord(run_id="2026-10-06/arknights/MAA-09-05-00", script="MAA", user="arknights",
                started=datetime(2026, 10, 6, 9, 5, tzinfo=SERVER_TZ), finished=datetime(2026, 10, 6, 9, 6, tzinfo=SERVER_TZ),
                ok=False, failed_tasks=["开始唤醒"])
makeup.never_started(e, rec)
makeup.never_started(e, rec)
check("#65 没过，推了一次", len(n.fails("#65")), 1)
saved_log = sd / "machinecheck" / "maa-not-started" / "2026-10-06_arknights_MAA-09-05-00.log"
text = saved_log.read_text(encoding="utf-8") if saved_log.exists() else ""
check("存下了这一趟的 gui.log 两行", ("开始唤醒" in text, "连接模拟器失败" in text, "早上那趟" in text), (True, True, False))
check("asst.log 那一段（续行跟着）", ("Connect" in text, "continued line" in text, "下一趟" in text), (True, True, False))
check("依据里写了存的位置", str(saved_log) in mc.read(sd).get("#65", {}).get("evidence", "") or
      "maa-not-started" in mc.read(sd).get("#65", {}).get("evidence", ""), True)

print("\n[接线：补跑记录落地 → #33 记过]")
sd = tmpdir()
n = N()
e = engine(sd, n)
day = "2026-10-06"
(sd / "makeup").mkdir()
(sd / "makeup" / f"{day}.json").write_text(json.dumps({"MaaEnd": {
    "result": "dispatched", "dispatched_at": "2026-10-06T14:01:30+08:00", "run_id": "2026-10-06/endfield/MaaEnd-09-30-00",
    "tries": 1}}), encoding="utf-8")
mrec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-14-02-11", script="MaaEnd", user="endfield",
                 started=datetime(2026, 10, 6, 14, 2, 11, tzinfo=SERVER_TZ), finished=datetime(2026, 10, 6, 14, 30, tzinfo=SERVER_TZ),
                 ok=True)
makeup.on_record(e, mrec)
check("#33 记了过", mc.read(sd).get("#33", {}).get("status"), "PASS")

print("\n[接线：预更新前终末地开着 → 先关再写设置，#17 记过]")
from ark_relay import preupdate_maaend as pm  # noqa: E402
md = tmpdir()
(md / "MaaEnd.exe").write_text("", encoding="utf-8")
(md / "config").mkdir()
(md / "config" / "mxu-MaaEnd.json").write_text(json.dumps({"settings": {"autoStartInstanceId": "inst-1"}}), encoding="utf-8")
order = []
lists = [[4321], []]
saved = (pm._maaend_pids, pm._close, pm._run_maaend)
pm._maaend_pids = lambda: (order.append("tasklist"), lists.pop(0) if lists else [])[1]
pm._close = lambda exe: order.append("close")


def fake_run(maaend_dir, exe, budget_s, problems, state_dir, sleep):
    order.append("launch:" + json.loads((maaend_dir / "config" / "mxu-MaaEnd.json").read_text())["settings"]["autoStartInstanceId"])
    return ""


pm._run_maaend = fake_run
sd = tmpdir()
n = N()
try:
    boot_stages._preupdate_maaend(md, types.SimpleNamespace(state_dir=sd, automas_dir=None), n,
                                  logging.getLogger("ark.service"), [])
finally:
    pm._maaend_pids, pm._close, pm._run_maaend = saved
check("先看、关掉、再确认没了，然后才改设置启动", order[:4], ["tasklist", "close", "tasklist", "launch:"])
check("#17 记了过", mc.read(sd).get("#17", {}).get("status"), "PASS")

print("\n[接线：看门狗结束 MaaEnd 说成功了，下一眼进程表里它还在 → 警告 + #31 没过进群]")
from ark_relay import maaend_watchdog as wd  # noqa: E402
sd = tmpdir()
debug = tmpdir() / "debug"
debug.mkdir()
(debug / "go-service.stderr.log").write_text("", encoding="utf-8")
t = [1000.0]
procs = [("MaaEnd.exe", 30000), ("go-service.exe", 21932)]
n = N()
dog = wd.Watchdog(n, debug, clock=lambda: t[0], snapshot=lambda: {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]},
                  processes=lambda: procs, kill=lambda pid, image: (True, ""), plugin_paths=lambda: {},
                  active=True, state_dir=sd)
dog.tick(1, "")
(debug / "go-service.stderr.log").write_text("Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456\n", encoding="utf-8")
t[0] += 31
dog.tick(2, "")
check("结束了一次（报了卡死）", [x for x, _, _ in n.sent if "卡" in x] != [], True)
check("还没下结论", "#31" in mc.read(sd), False)
t[0] += 31
dog.tick(3, "")
check("#31 没过，进群", (mc.read(sd).get("#31", {}).get("status"), len(n.fails("#31"))), ("FAIL", 1))
sd2 = tmpdir()
n = N()
procs2 = [("MaaEnd.exe", 30001)]
dog = wd.Watchdog(n, debug, clock=lambda: t[0], snapshot=lambda: {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]},
                  processes=lambda: procs2, kill=lambda pid, image: (procs2.clear(), (True, ""))[1],
                  plugin_paths=lambda: {}, active=True, state_dir=sd2)
dog.tick(1, "")
(debug / "go-service.stderr.log").write_text("panic: runtime error\n", encoding="utf-8")
t[0] += 31
dog.tick(2, "")
t[0] += 31
dog.tick(3, "")
check("真结束了：#31 记过", mc.read(sd2).get("#31", {}).get("status"), "PASS")

print("\n[接线：桌面助手每次运行都记进 trace；更新流程把读到的启动器画面记下 → #60/#61 判得出]")
from ark_relay import desktop as dk, gameupdate, gameupdate_games as gg  # noqa: E402


def agent(results):
    def spawn(exe, cwd, args):
        res = Path(args[-1])
        res.write_text(json.dumps(results.pop(0), ensure_ascii=False), encoding="utf-8")
        return True
    return spawn


desk = dk.Desktop(tmpdir(), spawn=agent([
    {"ok": True, "focus_missing": True, "clicked": [], "ocr": [], "log": ["focus: 没有 Games 的窗口"]},
    {"ok": True, "clicked": [[960, 700]], "ocr": [{"text": "确认", "x": 900, "y": 690, "w": 120, "h": 20}],
     "log": ["focus: Endfield 「Endfield」", "click_text: 点了「确认」", "click 960,700"]},
]), timeout=5)
desk.read(focus="Games")
desk.click_text("确认", focus="Endfield")
check("两次运行都记了", [x.get("what") for x in desk.trace], ["agent", "agent"])
check("记下 focus_missing 字段", desk.trace[0].get("focus_missing"), True)
got, _ = judge("gameupdate", {"screens": desk.trace}, tmpdir())
check("#60 判过", got["#60"].status, mc.PASS)
check("脚本里点之前会说点了哪一行", "click_text: 点了「$($hit.text)」" in dk.AGENT_PS, True)


class Desk:
    """A launcher that is downloading, then ready."""

    def __init__(self, screens):
        self.screens = screens
        self.trace = []

    def note(self, **kw):
        self.trace.append(kw)

    def read(self, focus=None, settle_ms=0):
        if focus == "Endfield":
            return scr("点击任意位置继续")        # the game's title screen after the update
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

    def click_text(self, text, focus=None):
        return True

    def click(self, x, y, focus=None):
        return True


def scr(*texts):
    return dk.Screen([dk.Line(t, 0, i * 30, 100, 20) for i, t in enumerate(texts)], Path("shot.png"))


d = Desk([scr("更新游戏"), scr("正在下载 1.2GB/8.5GB", "暂停"), scr("开始游戏")])
saved = (gg.kill, gg._spawn)
gg.kill, gg._spawn = (lambda *a: None), (lambda *a, **k: True)
try:
    gg.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), budget_s=60, poll_s=0, sleep=lambda s: None)
finally:
    gg.kill, gg._spawn = saved
stages = [(x.get("stage"), x.get("busy")) for x in d.trace if x.get("what") == "launcher"]
check("第一眼和等待中都记下了", stages[:2], [("first", ""), ("wait", "正在下载")])
got, _ = judge("gameupdate", {"screens": d.trace}, tmpdir())
check("#61 判过", got["#61"].status, mc.PASS)

print("\n[接线：方舟预热点满 5 下之后那一屏记下来 → #62]")
d = Desk([scr("加载中") for _ in range(6)] + [scr("开始唤醒")])
how = gg.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", d, run=lambda args, *a, **k: "Physical size: 1600x900",
                    sleep=lambda s: None, budget_s=10_000)
check("到了登录界面", how, "读到「开始唤醒」")
pw = [x for x in d.trace if x.get("what") == "ak_prewarm"]
check("记下点满 5 下、后来到了", (pw[0].get("taps"), pw[0].get("full"), pw[0].get("reached")) if pw else None, (5, True, True))
got, _ = judge("gameupdate", {"screens": d.trace}, tmpdir())
check("#62 判过", got["#62"].status, mc.PASS)
check("run_deferred 用过的那张桌子的 trace 拿得到", (gameupdate._LAST_DESK.__setitem__(0, d), gameupdate.last_trace())[1] == d.trace, True)

print("\n[接线：开机游戏更新那步报了「终末地公告读不到」→ #64 判过（真抄送）]")
sd = tmpdir()
n = N()
n.state_dir = sd
saved = (gameupdate.should_run, gameupdate.boot_check, gameupdate.mark_run, boot_stages._seconds_to_next_queue)
gameupdate.should_run = lambda *a, **k: True
gameupdate.boot_check = lambda cfg, budget_s, now: ([], ["终末地：官方公告读不到，今天有没有版本更新不知道"])
gameupdate.mark_run = lambda *a, **k: None
boot_stages._seconds_to_next_queue = lambda *a: 600.0
try:
    boot_stages._stage_gameupdate(types.SimpleNamespace(state_dir=sd, automas_dir=None), n, logging.getLogger("ark.service"))
finally:
    gameupdate.should_run, gameupdate.boot_check, gameupdate.mark_run, boot_stages._seconds_to_next_queue = saved
check("#64 记了过", mc.read(sd).get("#64", {}).get("status"), "PASS")

print("\n[接线：问调度程序忙不忙时，开着非自动代理的任务记一笔（#18 开机时判）]")
sd = tmpdir()
automas = tmpdir()
(automas / "debug").mkdir()
now = datetime(2026, 10, 6, 20, 5, tzinfo=SERVER_TZ)
(automas / "debug" / "app.log").write_text(
    "2026-10-06 20:04:10.100 | INFO     | 业务调度 | 创建任务: cd34ef56-0000-1111-2222-333344445555, 模式: ScriptConfig, 触发来源: manual_task\n",
    encoding="utf-8")
saved = dict(eng_mod._BUSY_SEEN)
eng_mod._BUSY_SEEN.update(state_dir=sd, automas_dir=automas)
try:
    eng_mod._note_other_modes({"tasks": []}, False, now=now)
    eng_mod._note_other_modes({"tasks": []}, False, now=now)
    eng_mod._note_other_modes({"tasks": [{"taskId": "ab12", "mode": "ScriptConfig",
                                          "task_info": [{"name": "MAA", "status": "运行"}]}]}, True, now=now)
finally:
    eng_mod._BUSY_SEEN.clear()
    eng_mod._BUSY_SEEN.update(saved)
seen = json.loads((sd / sysmc.BUSY_FILE).read_text(encoding="utf-8"))["seen"]
check("记了两笔（同一个任务同一个答案只记一次）", [(o["task"][:4], o["busy"]) for o in seen], [("cd34", False), ("ab12", True)])
got, n = judge("boot", {}, sd)
check("#18 有一笔算不忙：没过，推了", (got["#18"].status, len(n.fails("#18"))), (mc.FAIL, 1))
check("依据是 app.log 那一行", "模式 ScriptConfig" in got["#18"].evidence, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
