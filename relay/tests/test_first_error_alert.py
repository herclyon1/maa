"""The relay's first ERROR of a boot is pushed to the group once; later ones and
shutdown-time ones are not.

2026-09-17 21:21:28: 「AUTO-MAS 拉起后 45 秒内接口仍不通」 was one ERROR line that
nobody read; the 21:30 queue never ran and the first alarm came at 21:55.
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import errwatch, texts
from ark_relay.notify import route_of

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


def _wait(n, count, secs=2.0):
    t0 = time.monotonic()
    while len(n.sent) < count and time.monotonic() - t0 < secs:
        time.sleep(0.02)
    time.sleep(0.05)   # let a wrongly-sent extra one land too


print("[第一条 ERROR 报群，一次开机只报一条]")
n = _Notifier()
flag = {"down": False}
h = errwatch.install(n, lambda: flag["down"])
lg = logging.getLogger(errwatch.ARK).getChild("service")   # ark.service
lg.setLevel(logging.INFO)
lg.warning("这是警告，不报")
lg.info("这是普通信息，不报")
_wait(n, 1, 0.3)
check("WARNING/INFO 不报", n.sent, [])
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 45)
_wait(n, 1)
check("第一条 ERROR 报了一条", len(n.sent), 1)
check("标题是 texts.RELAY_ERROR", n.sent and n.sent[0][0] == texts.RELAY_ERROR)
check("正文说出在哪一部分、原话有术语就说留在日志里", n.sent and "主程序" in n.sent[0][1] and "留在中继日志里" in n.sent[0][1])
check("是报警（alert=True）", n.sent and n.sent[0][2] is True)
lg.error("第二条错误")
try:
    raise RuntimeError("boom")
except RuntimeError:
    lg.exception("第三条，带堆栈")
_wait(n, 2, 0.4)
check("后面的 ERROR 不再报", len(n.sent), 1)
logging.getLogger(errwatch.ARK).removeHandler(h)

print("\n[关机令已发出之后的 ERROR 不报]")
n2 = _Notifier()
flag2 = {"down": True}
h2 = errwatch.install(n2, lambda: flag2["down"])
lg.error("进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅")
_wait(n2, 1, 0.4)
check("关机中的 ERROR 不报", n2.sent, [])
logging.getLogger(errwatch.ARK).removeHandler(h2)

print("\n[探测函数自己坏了也不拦报警]")
n3 = _Notifier()
h3 = errwatch.install(n3, lambda: 1 / 0)
lg.error("探测坏了也要报")
_wait(n3, 1)
check("照样报", len(n3.sent), 1)
logging.getLogger(errwatch.ARK).removeHandler(h3)

print("\n[文案与路由]")
check("标题走群", route_of(texts.RELAY_ERROR, alert=True), "group")
check("原话是人话时照抄", "它说：日报没发出去" in texts.relay_error_body("ark.report", "日报没发出去", "10:47"))
check("正文是人话（两种样例）", [texts.plain(x) for x in (texts.relay_error_body("ark.service", "ConnectionRefusedError: [WinError 10061]", "21:21"), texts.relay_error_body("ark.report", "日报没发出去", "10:47"))], [[], []])

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
