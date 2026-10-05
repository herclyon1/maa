"""Every new kind of relay error is pushed to the group once, a known-fixed kind as
「复发」 once per boot; shutdown-time ones are not.

2026-09-17 21:21:28: 「AUTO-MAS 拉起后 45 秒内接口仍不通」 was one ERROR line that
nobody read; the 21:30 queue never ran and the first alarm came at 21:55.
"""
import json
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


import tempfile
TMP = Path(tempfile.mkdtemp())

print("[新种类报一次；同种不同数字不再报；普通 INFO/WARNING 不报]")
n = _Notifier()
flag = {"down": False}
h = errwatch.install(n, lambda: flag["down"], state_dir=TMP / "a", known={})
lg = logging.getLogger(errwatch.ARK).getChild("service")   # ark.service
lg.setLevel(logging.INFO)
lg.warning("这是警告，不报")
lg.info("这是普通信息，不报")
lg.warning("鸣潮 3.7 版本活动日历读了 78 行，没找到「余心所向九死未悔」的日期")   # relay3.log 10-05 21:47:47, no failure word
_wait(n, 1, 0.3)
check("WARNING/INFO 不报", n.sent, [])
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 45)
_wait(n, 1)
check("第一条 ERROR 报了一条", len(n.sent), 1)
check("标题是新的报错", n.sent and n.sent[0][0] == texts.ERROR_NEW_KIND)
check("正文有游戏、哪一部分、日志原话", n.sent and "游戏：中继" in n.sent[0][1] and "主程序" in n.sent[0][1]
      and "AUTO-MAS 拉起后 45 秒内接口仍不通" in n.sent[0][1])
check("是报警（alert=True）", n.sent and n.sent[0][2] is True)
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 60)
eng = logging.getLogger(errwatch.ARK).getChild("engine")
eng.setLevel(logging.INFO)
eng.error("处理运行记录失败: 2026-09-08/wuwa/OK-WW-05-35-44")
_wait(n, 2)
check("同种换数字不再报、新种类再报一条", len(n.sent), 2)
eng.error("处理运行记录失败: 2026-09-08/wuwa/OK-WW-05-22-26")
eng.error("处理运行记录失败: 2026-08-26/wuwa/OK-WW-12-50-57")
_wait(n, 3, 0.4)
check("同种运行记录失败（不同日子不同批次）不再报", len(n.sent), 2)
check("运行记录失败认出是鸣潮", "游戏：鸣潮" in n.sent[1][1])
ban = logging.getLogger(errwatch.ARK).getChild("banners")
ban.setLevel(logging.INFO)
ban.warning("B 站版本资讯第 2 张图没读出来，这次不再读后面的图")      # relay3.log:27790
ban.warning("B 站版本资讯第 5 张图没读出来，这次不再读后面的图")
_wait(n, 4, 0.5)
check("失败词「没读出来」的 WARNING 报一次", len(n.sent), 3)
desk = logging.getLogger(errwatch.ARK).getChild("desktop")
desk.warning("桌面助手读图失败：ERR 使用“1”个参数调用“RecognizeAsync”时发生异常")   # relay3.log 21:47:47
_wait(n, 5, 0.5)
check("失败词「读图失败」的 WARNING 报一次", len(n.sent), 4)
try:
    raise RuntimeError("boom")
except RuntimeError:
    lg.warning("一段普通的话", exc_info=True)
_wait(n, 6, 0.5)
check("带堆栈的 WARNING 报", len(n.sent), 5)
saved = json.loads((TMP / "a" / "errsigs.json").read_text(encoding="utf-8"))
sig = errwatch.signature("ark.service", "AUTO-MAS 拉起后 45 秒内接口仍不通")
check("记下见过的种类和次数", saved.get(sig, {}).get("count"), 2)
logging.getLogger(errwatch.ARK).removeHandler(h)
h_again = errwatch.install(n, lambda: False, state_dir=TMP / "a", known={})
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 30)
_wait(n, 6, 0.4)
check("重启后见过的种类仍不再报", len(n.sent), 5)
logging.getLogger(errwatch.ARK).removeHandler(h_again)

print("\n[签名规则：真日志行]")
check("时间、数字、网址被抹掉",
      errwatch.signature("ark.handle", "🗂️ 2026-10-05/wuwa/OK-WW-05-39-25 证据包已上传（1 个文件）→ https://x.myqcloud.com/a.zip"),
      "ark.handle|🗂️ #-#-#/wuwa/OK-WW-#-#-# 证据包已上传（# 个文件）→ <url>")
check("Windows 路径被抹掉", errwatch.strip_variable(r"读不了 C:\ProgramData\ark-relay\state\x.json 了"), "读不了 <path> 了")
check("十六进制编号被抹掉", errwatch.strip_variable("hint: [1787192708189711197132387] id 76402e5b20be2c39f095a152090afddc"),
      "hint: [#] id <id>")
check("失败词表", errwatch.FAILED_WORDS, ("没做成", "失败", "取不到", "读图失败", "没读出来"))

print("\n[复发：known-fixed.json 里的种类，每次开机报一次，标修好的版本]")
known = errwatch.load_known()
check("known-fixed.json 读得到两条", len(known), 2)
n7 = _Notifier()
h7 = errwatch.install(n7, lambda: False, state_dir=TMP / "b")
ban.warning("库街区官方资讯里没找到 3.7 版本资讯帖")                # relay3.log:27777 (no failure word, still a recurrence)
_wait(n7, 1)
check("库街区没找到资讯帖 → 复发", n7.sent and n7.sent[0][0].startswith("♻️ 复发：v20261005151027"), True)
check("复发正文说修的是什么、是鸣潮", n7.sent and "库街区官方资讯里找不到当期版本资讯帖" in n7.sent[0][1] and "游戏：鸣潮" in n7.sent[0][1])
try:
    from PIL_absent_for_test import Image  # noqa: F401
except ModuleNotFoundError as exc:
    # relay3.log:27778-27785: the real record is a WARNING with a ModuleNotFoundError for PIL
    try:
        raise ModuleNotFoundError("No module named 'PIL'") from exc
    except ModuleNotFoundError:
        ban.warning("官方图转 PNG 失败，原样交给系统 OCR", exc_info=True)
_wait(n7, 2)
check("缺 Pillow 堆栈 → 复发", len(n7.sent) == 2 and n7.sent[1][0].startswith("♻️ 复发：v20261005151027"), True)
check("复发正文带堆栈的异常类型", len(n7.sent) == 2 and "ModuleNotFoundError: No module named 'PIL'" in n7.sent[1][1])
ban.warning("库街区官方资讯里没找到 3.8 版本资讯帖")
_wait(n7, 3, 0.4)
check("同一次开机同一复发只报一次", len(n7.sent), 2)
logging.getLogger(errwatch.ARK).removeHandler(h7)
h8 = errwatch.install(n7, lambda: False, state_dir=TMP / "b")      # next boot, same seen-list
ban.warning("库街区官方资讯里没找到 3.8 版本资讯帖")
_wait(n7, 3)
check("下一次开机复发再报（见过的名单不拦复发）", len(n7.sent), 3)
logging.getLogger(errwatch.ARK).removeHandler(h8)

print("\n[推送时自己打的日志、抄送 COS 的日志不回到这里]")
class _LoudNotifier(_Notifier):
    def send(self, title, body, *, alert=False, daily=False):
        super().send(title, body, alert=alert)
        logging.getLogger("ark.notify").error("通知一条渠道都没送到：x ｜ 标题：%s", title)
        return ["x"]
n9 = _LoudNotifier()
h9 = errwatch.install(n9, lambda: False, state_dir=TMP / "c", known={})
lg.error("一种新错")
_wait(n9, 2, 0.6)
check("推送里打的 ERROR 不再引出第二条", len(n9.sent), 1)
logging.getLogger("ark.alertlog").warning("群报警抄送 COS 没成：timed out")
_wait(n9, 2, 0.4)
check("抄送 COS 失败的 WARNING 不报", len(n9.sent), 1)
logging.getLogger(errwatch.ARK).removeHandler(h9)

print("\n[关机令已发出之后的 ERROR 不报]")
n2 = _Notifier()
flag2 = {"down": True}
h2 = errwatch.install(n2, lambda: flag2["down"], state_dir=TMP / "d2", known={})
lg.error("进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅")
_wait(n2, 1, 0.4)
check("关机中的 ERROR 不报", n2.sent, [])
logging.getLogger(errwatch.ARK).removeHandler(h2)

print("\n[手动 shutdown /s：中继自己没下过关机令，但服务收到了停止/关机控制 → 不报]")
# The real record, 2026-09-18 02:20 (the machine was being switched off by hand;
# the group got 「🩺 中继自己报错了（主程序）」 for it).
REAL = "进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅"
n4 = _Notifier()
h4 = errwatch.install(n4, lambda: False, state_dir=TMP / "d4", known={})          # relay's own flag not set - it did not issue the shutdown
errwatch.mark_stopping()                          # what SvcStop now does (Windows routes SERVICE_CONTROL_SHUTDOWN there)
lg.error(REAL)
_wait(n4, 1, 0.4)
check("服务已收到停止/关机控制 → 不报", n4.sent, [])
logging.getLogger(errwatch.ARK).removeHandler(h4)
errwatch._stopping.clear()

print("\n[Windows 自己说正在关机（GetSystemMetrics）→ 不报]")
n5 = _Notifier()
h5 = errwatch.install(n5, lambda: False, state_dir=TMP / "d5", known={})
orig_ssd = errwatch.system_shutting_down
errwatch.system_shutting_down = lambda: True
lg.error(REAL)
_wait(n5, 1, 0.4)
check("系统关机中 → 不报", n5.sent, [])
errwatch.system_shutting_down = orig_ssd
logging.getLogger(errwatch.ARK).removeHandler(h5)

print("\n[平时同一条 ERROR 照报（不是关机就是真掉了）]")
n6 = _Notifier()
h6 = errwatch.install(n6, lambda: False, state_dir=TMP / "d6", known={})
lg.error(REAL)
_wait(n6, 1)
check("不在关机就报", len(n6.sent), 1)
logging.getLogger(errwatch.ARK).removeHandler(h6)

print("\n[探测函数自己坏了也不拦报警]")
n3 = _Notifier()
h3 = errwatch.install(n3, lambda: 1 / 0, state_dir=TMP / "d3", known={})
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
