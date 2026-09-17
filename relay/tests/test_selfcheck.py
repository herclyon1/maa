"""Boot self-check: every broken assumption is named and pushed to the group at
once; the daily report gets the two relay lines a person used to run by hand.

2026-09-17: the process table had been unreadable for three weeks (wmic gone)
and the relay found out from a lost queue. The self-check exists so a boot
tells on itself instead.
"""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import selfcheck, texts
from ark_relay.notify import route_of

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Notifier:
    channels = ["企业微信机器人"]

    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


with tempfile.TemporaryDirectory() as td:
    import os
    os.environ["ARK_LOG_FILE"] = str(Path(td) / "log" / "relay.log")
    cfg = types.SimpleNamespace(automas_dir=td, state_dir=Path(td) / "state", history_dir=td,
                                phone_topic="ark-x", phone_pin="1234")
    good = dict(procs=lambda: [(1, r"D:\ark\automas\repo\main.py")], mas_up=lambda: True,
                schedule=lambda: [{"name": "早班", "times": ["09:00"]}], channels=lambda: ["群"],
                run_ok=lambda cmd: (True, ""))

    print("[一切正常：全部成立、不报警]")
    cs = selfcheck.run(cfg, **good)
    check("11 项", len(cs), 11)
    check("全部成立", [c.name for c in cs if not c.ok], [])
    check("每一项的名字都是人话", [texts.plain(c.name) for c in cs if texts.plain(c.name)], [])

    print("\n[09-17 那种机器：进程表读不到、调度程序没应答、任务计划没了]")
    bad = dict(good, procs=lambda: None, mas_up=lambda: False,
               run_ok=lambda cmd: (False, "退出码 1") if cmd[0] == "schtasks" else (True, ""))
    cs = selfcheck.run(cfg, **bad)
    names = [c.name for c in cs if not c.ok]
    check("点名进程表", any("怎么启动" in n for n in names))
    check("点名调度程序没应答", "调度程序有应答" in names)
    check("点名后台程序", "调度程序的后台程序在跑" in names)
    check("点名任务计划", "调度程序的开机任务计划还在" in names)
    check("别的项照常成立", len(names), 4)

    print("\n[report：不成立就群报一条，全成立不报]")
    n = _Notifier()
    selfcheck.run = (lambda _run: lambda cfg, **kw: _run(cfg, **dict(bad, channels=kw.get("channels"))))(selfcheck.run)
    selfcheck.report(cfg, n)
    check("报了一条", len(n.sent), 1)
    check("标题", n.sent and n.sent[0][0] == texts.SELFCHECK_FAILED)
    check("是报警", n.sent and n.sent[0][2] is True)
    check("正文列出不成立的项", n.sent and "任务计划" in n.sent[0][1] and "4 项不成立" in n.sent[0][1])
    check("正文是人话", n.sent and texts.plain(n.sent[0][1]), [])
    check("走群", route_of(texts.SELFCHECK_FAILED, alert=True), "group")

print("\n[日报两行：从当天 relay.log 来]")
log = """09-17 08:45:28 WARNING ark.service  AUTO-MAS 接口不在，拉起它
09-17 08:46:46 INFO    ark.service  AUTO-MAS 已拉起（24 秒）
09-17 10:48:40 ERROR   ark.service  进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅
09-17 21:20:39 WARNING ark.service  AUTO-MAS 接口不在，拉起它
09-17 21:21:28 ERROR   ark.service  AUTO-MAS 拉起后 45 秒内接口仍不通
09-16 21:21:00 ERROR   ark.service  昨天的，不算
09-18 08:45:50 INFO    ark.service  AUTO-MAS 自己起来了（等了 21 秒）
"""
lines = selfcheck.daily_lines("2026-09-17", log)
check("两行", len(lines), 2)
check("错误计数 2、第一条 10:48、出在主程序", "报错 2 条" in lines[0] and "10:48" in lines[0] and "主程序" in lines[0])
check("原话有术语就不照抄", "留在" in lines[0] or "见中继日志" in lines[0])
check("开机两次：重开后起来了 24 秒；重开后还是没应答", "24 秒" in lines[1] and "还是没应答" in lines[1])
lines2 = selfcheck.daily_lines("2026-09-18", log)
check("没报错就说没报错", lines2[0], "· 中继今天没有报错")
check("自己起来了 21 秒", "自己起来了（等了 21 秒）" in lines2[1])
check("两行都是人话", [texts.plain(x) for x in lines + lines2 if texts.plain(x)], [])
check("没有日志文件就空", selfcheck.daily_section("2026-09-18", "/nonexistent/relay.log"), "")

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
