"""Every WARNING / ERROR the relay logs is pushed to the group, every time, at once;
nothing is dropped when the group refuses; nothing loops back from the push path.

The user's order of 2026-10-06 (full words in docs/NOTIFICATIONS.md, the 🩺 row)
ends with the rule itself: 「不论多少次什么错误都要发」. Before that:
one push per new ERROR kind (state/errsigs.json), WARNINGs to the daily report only,
at most 3 pushes an hour, nothing while the machine was going down - each of which
is checked here as gone.
2026-09-17 21:21:28: 「AUTO-MAS 拉起后 45 秒内接口仍不通」 was one ERROR line that
nobody read; the 21:30 queue never ran and the first alarm came at 21:55.
"""
import importlib
import json
import logging
import os
import sys
import threading
import time
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
B = TMP / "b"   # section_2's state dir; the daily-report part at the end reads it too
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                  COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import alertlog, errwatch, known_fixed, texts  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402
from ark_relay import notify as notify_mod  # noqa: E402
from ark_relay.notify import route_of  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Notifier:
    """Records what reached the group; `fail` > 0 refuses that many sends first."""

    def __init__(self, fail=0):
        self.sent, self.fail, self.tries = [], fail, 0

    def send(self, title, body, *, alert=False, daily=False):
        self.tries += 1
        if self.fail:
            self.fail -= 1
            return ["企业微信机器人: errcode 45009 api freq out of limit"]
        self.sent.append((title, body, alert))
        return []


def _wait(n, count, secs=3.0):
    t0 = time.monotonic()
    while len(n.sent) < count and time.monotonic() - t0 < secs:
        time.sleep(0.02)
    time.sleep(0.1)   # let a wrongly-sent extra one land too


ARK = logging.getLogger(errwatch.ARK)
lg = ARK.getChild("service")   # ark.service
eng = ARK.getChild("engine")
ban = ARK.getChild("banners")
han = ARK.getChild("handle")
for x in (lg, eng, ban, han):
    x.setLevel(logging.INFO)
TODAY = datetime.now(SERVER_TZ).strftime("%Y-%m-%d")
HANDLERS = []


def make(n, d, **kw):
    """A handler on the ark logger with no pacing (pace / retry in seconds)."""
    kw.setdefault("known", {})
    kw.setdefault("pace", 0)
    kw.setdefault("retry", (0.05,))
    # Only what this version of the handler takes (the old one had no pacing),
    # so the checks below run against either.
    import inspect  # noqa: PLC0415
    takes = inspect.signature(errwatch.ErrorKindAlert.__init__).parameters
    h = errwatch.ErrorKindAlert(n, lambda: False, d, **{k: v for k, v in kw.items() if k in takes})
    ARK.addHandler(h)
    HANDLERS.append(h)
    return h


def drop(h):
    ARK.removeHandler(h)
    h.close()


def pending(h):
    return h.pending() if hasattr(h, "pending") else []


def faults(d):
    return errwatch.day_faults(d, TODAY)


def section(fn):
    """Run one section; an exception (the old code has no such function) fails it and the rest still run."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(f"{fn.__name__} ran", f"{type(exc).__name__}: {exc}", "no exception")


def section_1():
    print("[同一条 ERROR 出两次：报两次]")
    A = TMP / "a"
    n = _Notifier()
    h = make(n, A)
    lg.info("这是普通信息，不报")
    lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 45)
    _wait(n, 1)
    lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 45)
    _wait(n, 2)
    check("两条一样的 ERROR：两条推送", len(n.sent), 2)
    check("INFO 不报", any("普通信息" in b for _, b, _ in n.sent), False)
    check("标题是 texts.RELAY_ERROR", [t for t, _, _ in n.sent], [texts.RELAY_ERROR] * 2)
    check("是报警（alert=True）", [a for _, _, a in n.sent], [True, True])
    check("正文说出在哪一部分、原话有术语就说留在日志里", "主程序" in n.sent[0][1] and "留在中继日志里" in n.sent[0][1])
    check("正文带时刻", datetime.now(SERVER_TZ).strftime("%H:") in n.sent[0][1])
    check("正文不再说「只报这一次」", any("只报这一次" in b or "只记进日报" in b for _, b, _ in n.sent), False)
    lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 60)
    _wait(n, 3)
    check("换了数字的同种：照报", len(n.sent), 3)
    drop(h)
    h = make(n, A)                              # a restart: same state dir
    lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 30)
    _wait(n, 4)
    check("重启后同种照报", len(n.sent), 4)
    check("不再有 errsigs.json（种类不再记成见过）", (A / "errsigs.json").exists(), False)
    drop(h)


section(section_1)


def section_2():
    print("\n[WARNING 也报群：自己兜过去的也算报错]")
    n = _Notifier()
    h = make(n, B)
    ban.warning("B 站版本资讯第 2 张图没读出来，这次不再读后面的图")   # relay3.log:27790
    _wait(n, 1)
    ban.warning("B 站版本资讯第 5 张图没读出来，这次不再读后面的图")
    _wait(n, 2)
    try:
        raise ConnectionResetError("reset")
    except ConnectionResetError:
        ban.warning("PRTS 接口取不到 %s，改读页面", "卡池一览", exc_info=True)
    _wait(n, 3)
    lg.warning("鸣潮 3.7 版本活动日历读了 78 行，没找到日期")          # no failure word: still a WARNING
    _wait(n, 4)
    check("四条 WARNING 四条推送", len(n.sent), 4)
    check("带异常名的那条把异常写进去（原话有术语，留日志）", "留在中继日志里" in n.sent[2][1])
    check("人话原样说出来", "它说：鸣潮 3.7 版本活动日历读了 78 行，没找到日期" in n.sent[3][1])
    rows = faults(B)
    check("日报记下种类和次数", [(r["where"], r["count"], r["pushed"]) for r in rows],
          [("ark.banners", 2, 2), ("ark.banners", 1, 1), ("ark.service", 1, 1)])
    section = errwatch.daily_section(B, TODAY)
    check("日报一段：都「已报群」", section.count("已报群"), 3)
    check("日报一段：次数", "（2 次）" in section)
    check("日报一段是人话", texts.plain(section), [])
    drop(h)


section(section_2)


def section_3():
    print("\n[一小时超过 3 条：全报]")
    F = TMP / "f"
    n = _Notifier()
    h = make(n, F)
    for word in ("甲", "乙", "丙", "丁", "戊", "己"):
        eng.error(f"{word}出了错")
        _wait(n, 1, 0.05)
    _wait(n, 6)
    check("六种 ERROR 六条推送", len(n.sent), 6)
    check("一条不少", sorted(b.split("它说：")[1][:1] for _, b, _ in n.sent), sorted("甲乙丙丁戊己"))
    check("MAX_PER_HOUR 没了", hasattr(errwatch, "MAX_PER_HOUR"), False)
    drop(h)


section(section_3)


def section_4():
    print("\n[群不收：留在盘上排队，过后再推，一条不丢]")
    G = TMP / "g"
    n = _Notifier(fail=2)
    h = make(n, G, retry=(0.3,))
    eng.error("一种错")
    time.sleep(0.05)
    check("推不出去：排着队", [x["line"] for x in pending(h)], ["一种错"])
    QF = G / getattr(errwatch, "QUEUE_FILE", "errwatch-queue.json")
    check("队列存在盘上", QF.exists() and json.loads(QF.read_text(encoding="utf-8"))[0]["line"], "一种错")
    eng.error("另一种错")
    eng.error("另一种错")
    _wait(n, 1, 3)
    check("群收了：一条合并的推送", len(n.sent), 1)
    title, body = n.sent[0][:2]
    check("合并的标题带条数", title, texts.relay_errors_merged(texts.RELAY_ERROR, 2))
    check("三条都在里面（一样的两条合成一行，写了次数）",
          ("一种错" in body, "另一种错" in body, "共 2 次" in body), (True, True, True))
    check("标题进群", route_of(title, alert=True), "group")
    check("送达后队列空了", pending(h), [])
    check("盘上的队列也空了", QF.exists() and json.loads(QF.read_text(encoding="utf-8")), [])
    check("日报记成已报群 3 次", sum(int(r["pushed"]) for r in faults(G)), 3)
    eng.error("又一种错")
    _wait(n, 2)
    check("通了以后又是一条一推", (len(n.sent), n.sent[-1][0]), (2, texts.RELAY_ERROR))
    drop(h)


section(section_4)


def section_5():
    print("\n[群一直不收时重启：盘上的队列开机后照样送出]")
    H = TMP / "h"
    n = _Notifier(fail=1000)
    h = make(n, H, retry=(10,))
    eng.error("重启前没送出去的错")
    time.sleep(0.2)
    drop(h)
    QH = H / getattr(errwatch, "QUEUE_FILE", "errwatch-queue.json")
    check("还在盘上", QH.exists() and [x["line"] for x in json.loads(QH.read_text(encoding="utf-8"))],
          ["重启前没送出去的错"])
    n2 = _Notifier()
    h = make(n2, H)
    _wait(n2, 1)
    check("新进程把它送出去了", len(n2.sent) == 1 and "重启前没送出去的错" in n2.sent[0][1])
    drop(h)


section(section_5)


def section_robot():
    print("\n[群机器人配了：只走群机器人；它不收就排队，不落到 Server酱；等太久才按报警的老路走]")

    class _Robot(_Notifier):
        channels = ["企业微信机器人", "Server酱"]

        def __init__(self, fail=0):
            super().__init__(fail)
            self.via = []

        def send_group(self, title, body):
            self.via.append("group")
            return _Notifier.send(self, title, body, alert=True)

        def send(self, title, body, *, alert=False, daily=False):
            self.via.append("send")
            return _Notifier.send(self, title, body, alert=alert)

    n = _Robot(fail=1)
    h = make(n, TMP / "robot", retry=(0.2,))
    eng.error("机器人第一次没收")
    _wait(n, 1)
    check("机器人不收：排队，过一会儿还是走机器人", n.via, ["group", "group"])
    check("送到了", len(n.sent), 1)
    drop(h)
    n = _Robot(fail=1000)
    h = make(n, TMP / "robot2", retry=(0.05,), fallback_after=0.2)
    eng.error("机器人一直不收")
    t0 = time.monotonic()
    while "send" not in n.via and time.monotonic() - t0 < 3:
        time.sleep(0.02)
    check("等够了才按报警老路（先机器人再 Server酱）走", ("group" in n.via, "send" in n.via), (True, True))
    check("走老路之前一直在排队", [x["line"] for x in pending(h)], ["机器人一直不收"])
    n.fail = 0
    _wait(n, 1)
    check("老路送到了就放下", (len(n.sent), pending(h)), (1, []))
    drop(h)

    class _Fell(_Notifier):
        def went_to_group(self):
            return False

    check("报警落到 Server酱（没进群）：这一行照报",
          errwatch.group_pushed(texts.ROUND_INCOMPLETE, [], _Fell()), {})


section(section_robot)


def section_6():
    print("\n[推送途中自己记的 WARNING / ERROR 不回到这里]")


    class _LoudNotifier(_Notifier):
        def send(self, title, body, *, alert=False, daily=False):
            super().send(title, body, alert=alert)
            notify_mod.log.error("通知一条渠道都没送到：x ｜ 标题：%s", title)
            notify_mod.log.warning("企业微信机器人推送失败: x")
            return []


    n = _LoudNotifier()
    h = make(n, TMP / "loop")
    lg.error("一种新错")
    _wait(n, 3, 1.0)
    check("推送里打的 ERROR / WARNING 不再引出第二条", len(n.sent), 1)
    check("在推送线程上认得出来", errwatch.in_push_path(), False)
    seen = []
    t = threading.Thread(target=lambda: seen.append(errwatch.in_push_path()), name=errwatch.PUSH_THREAD + "-x")
    t.start()
    t.join()
    check("推送线程上 in_push_path 为真", seen, [True])
    drop(h)


section(section_6)


def section_7():
    print("\n[报警抄到 COS 失败：推送线程里抄的不回来，平常的照报]")
    n = _Notifier()
    h = make(n, TMP / "copy")
    names = []


    def bad_put(key, data):
        names.append(threading.current_thread().name)
        return "COS 403"


    def copy_in_push_path():
        alertlog.AlertLog(TMP / "copy-a", put=bad_put, get=lambda k: (b"", "")).copy("t", "x").join()


    t = threading.Thread(target=copy_in_push_path, name=errwatch.PUSH_THREAD + "-y")
    t.start()
    t.join()
    _wait(n, 1, 0.5)
    check("推送线程里起的抄送线程也算推送途中", names[-1].startswith(errwatch.PUSH_THREAD), True)
    check("它记的 COS 失败不回来推", n.sent, [])
    alertlog.AlertLog(TMP / "copy-b", put=bad_put, get=lambda k: (b"", "")).copy("t", "x").join()
    _wait(n, 1)
    check("平常线程抄送失败：照报", len(n.sent) == 1 and "报警抄送" in n.sent[0][1])
    drop(h)


section(section_7)


def section_8():
    print("\n[已经推进群的同一件事：调用方带了标记就不重推；没推出去就照报]")
    n = _Notifier()
    h = make(n, TMP / "flag")
    han.warning("⚠️ MAA 有项目没干成", extra=errwatch.group_pushed(texts.ROUND_INCOMPLETE, []))
    _wait(n, 1, 0.4)
    check("推出去了：这一行不再推", n.sent, [])
    han.warning("⚠️ MAA 有项目没干成", extra=errwatch.group_pushed(texts.ROUND_INCOMPLETE, ["发不出去"]))
    _wait(n, 1)
    check("没推出去：这一行照报", len(n.sent), 1)
    check("只进日志的标题不算进了群", errwatch.group_pushed("🗓️ 周常", []), {})
    check("进群的标题、送达了：带标记", errwatch.group_pushed(texts.ROUND_INCOMPLETE, []), {errwatch.PUSHED: True})
    drop(h)


section(section_8)


def section_9():
    print("\n[带自己标题和正文的报错]")
    n = _Notifier()
    h = make(n, TMP / "own")
    eng.warning("剿灭开关重新关闭失败: x", extra=errwatch.alarm("⚠️ 剿灭开关没能关上", "正文一句"))
    _wait(n, 1)
    check("用它自己的标题", n.sent and n.sent[0][0], "⚠️ 剿灭开关没能关上")
    check("正文是它的，带时刻", bool(n.sent) and n.sent[0][1].startswith("正文一句\n（"))
    drop(h)


section(section_9)


def section_10():
    print("\n[已修好的毛病又出现：打上复发标记，每次都报]")
    check("登记表都写了修好的版本和说法", all(v.get("fixed_in") and v.get("what") for v in known_fixed.KNOWN.values()))
    check("登记表的说法是人话", [texts.plain(v["what"]) for v in known_fixed.KNOWN.values()],
          [[] for _ in known_fixed.KNOWN])
    C = TMP / "c"
    n = _Notifier()
    h = make(n, C, known=known_fixed.KNOWN, version=lambda: "20261005153900")
    ban.warning("库街区官方资讯里没找到 %s 版本资讯帖", "3.7")      # relay3.log:27777
    _wait(n, 1)
    ban.warning("库街区官方资讯里没找到 %s 版本资讯帖", "当期")
    _wait(n, 2)
    try:
        try:
            importlib.import_module("PIL_absent_for_test")
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError("No module named 'PIL'") from exc
    except ModuleNotFoundError:
        ban.warning("官方图转 PNG 失败，原样交给系统 OCR", exc_info=True)   # relay3.log:27778-27785
    _wait(n, 3)
    check("复发的 WARNING 也报，三条三推", len(n.sent), 3)
    check("复发有自己的标题，带修好的版本", {t for t, _, _ in n.sent}, {texts.relay_error_recurred("20261005151027")})
    check("复发标题照样进群", route_of(texts.relay_error_recurred("20261005151027"), alert=True), "group")
    check("复发正文说当时修的是什么", "库街区官方资讯翻得不够多页" in n.sent[0][1])
    check("日报写「复发：v… 修过的又出现了」",
          errwatch.daily_section(C, TODAY).count("复发：v20261005151027 修过的又出现了"), 3)
    drop(h)
    KNOWN_ERR = {errwatch.signature("ark.engine", "处理运行记录失败: <path>"): {"fixed_in": "20261006000000",
                                                                           "what": "运行记录读到一半就处理"}}
    E = TMP / "e"
    n = _Notifier()
    h = make(n, E, known=KNOWN_ERR, version=lambda: "20261005153900")   # running code older than the fix
    eng.error("处理运行记录失败: /x/y/t")
    _wait(n, 1)
    check("运行的版本比修复还旧：不算复发，按普通的报", n.sent and n.sent[0][0], texts.RELAY_ERROR)
    check("也不打复发标记", [r.get("fixed_in") for r in faults(E)], [None])
    drop(h)


section(section_10)


def section_11():
    print("\n[关机途中也报（他不要把关机时的 WMI 断开藏起来）]")
    REAL = "进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅"
    n = _Notifier()
    h = make(n, TMP / "down")
    errwatch.mark_stopping()                          # what SvcStop does (and SERVICE_CONTROL_SHUTDOWN)
    lg.error(REAL)
    _wait(n, 1)
    check("服务已收到停止/关机控制：照报", len(n.sent), 1)
    check("going_down() 还在、还认得停止", errwatch.going_down(), True)
    errwatch._stopping.clear()
    orig_ssd = errwatch.system_shutting_down
    errwatch.system_shutting_down = lambda: True
    lg.error(REAL)
    _wait(n, 2)
    check("Windows 说正在关机：照报", len(n.sent), 2)
    errwatch.system_shutting_down = orig_ssd
    check("探测函数坏了，going_down 答「没在关机」", errwatch.going_down(lambda: 1 / 0), False)
    drop(h)
    n = _Notifier()
    h = errwatch.install(n, lambda: True, state_dir=TMP / "inst", known={})
    HANDLERS.append(h)
    lg.error("装上去的那个也报，关机探测说在关机也报")
    _wait(n, 1, 4)
    check("install() 装的处理器照报（传进来的关机探测不再拦）", len(n.sent), 1)
    drop(h)


section(section_11)


def section_12():
    print("\n[积压时：合并、一样的合成一行]")
    items = [{"title": texts.RELAY_ERROR, "where": "ark.report", "line": "日报没发出去", "n": 3,
              "first": f"{TODAY} 21:21:05", "last": f"{TODAY} 21:25:10"},
             {"title": "⚠️ 剿灭开关没能关上", "body": "正文", "n": 1, "first": f"{TODAY} 21:30:00",
              "last": f"{TODAY} 21:30:00"}]
    check("span：一条", errwatch.span(items[1]), "21:30:00")
    check("span：合成的", errwatch.span(items[0]), "21:21:05 起共 3 次，最后一次 21:25:10")
    check("render：自己的正文", errwatch.render(items[1]), ("⚠️ 剿灭开关没能关上", "正文\n（21:30:00）"))
    t2, b2 = errwatch.merge(items)
    check("merge：标题", t2, texts.relay_errors_merged(texts.RELAY_ERROR, 2))
    check("merge：每条一段，结尾一句", ("【⚠️ 剿灭开关没能关上】" in b2, "共 3 次" in b2, b2.endswith(texts.RELAY_ERROR_TAIL)),
          (True, True, True))
    check("merge：一条就是它自己", errwatch.merge(items[1:]), errwatch.render(items[1]))
    check("merge 出来的是人话", texts.plain(b2), [])


section(section_12)

def section_recovered():
    print("\n[自己好了的：只进日报，不进群（用户 2026-10-06 05:07）]")
    R = TMP / "recovered"
    n = _Notifier()
    h = make(n, R)
    lg.warning("手机通道断了 20 秒，自己重新连上了", extra=errwatch.recovered())
    lg.warning("维护公告：终末地 取不到")              # still broken: pushed
    _wait(n, 1)
    time.sleep(0.3)
    check("没好的照报，自己好了的不报", [b for _, b, _ in n.sent if "重新连上" in b], [])
    check("没好的那条进群", len(n.sent), 1)
    rows = faults(R)
    got = [r for r in rows if "重新连上" in str(r.get("line"))]
    check("自己好了的记进当天的报错表", bool(got) and got[0].get("recovered"), True)
    check("日报那一段写「自己好了，只进日报」", "自己好了，只进日报" in errwatch.daily_section(R, TODAY))
    drop(h)


section(section_recovered)


def section_drain():
    print("\n[关机前送着、硬杀前 drain：送完的落盘，开机不再重发（2026-10-06 06:21:36 又进群）]")

    class _Slow(_Notifier):
        def send(self, title, body, *, alert=False, daily=False):
            time.sleep(0.3)
            return super().send(title, body, alert=alert, daily=daily)

    D = TMP / "drain"
    n = _Slow()
    h = make(n, D, pace=0)
    eng.error("关机前送着的错")
    QF = D / getattr(errwatch, "QUEUE_FILE", "errwatch-queue.json")
    h.drain(2.0)
    check("drain 后盘上队列空（已落盘，不会重发）", json.loads(QF.read_text(encoding="utf-8")), [])
    check("群收到一条", len(n.sent), 1)
    n2 = _Notifier()
    h2 = make(n2, D, pace=0)
    time.sleep(0.2)
    check("新进程（开机）不再重发同一条", n2.sent, [])
    drop(h)
    drop(h2)


section(section_drain)


print("\n[日报里有这一段（report._compose_daily）]")
from ark_relay import report  # noqa: E402
from ark_relay import engine as eng_mod  # noqa: E402
from ark_relay.config import Config  # noqa: E402
from ark_relay.core import State  # noqa: E402

# No network: the banner section and the report-writing model are stubbed, as in test_report_due.py.
report.plan = types.SimpleNamespace(next_plan=lambda d: "", activity_countdown=lambda d: "",
                                    schedule=lambda d: [])
report.banners = types.SimpleNamespace(
    collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
    read_image=None: ([], {}),
    image_reader=lambda state_dir: None,
    render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
    Trace=types.SimpleNamespace(new=lambda: None),
    save_trace=lambda state_dir, now, text, tr: None,
    update_history=lambda state_dir, now: [],
    opening_tomorrow=lambda now, nxt: [],
)
report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")
cfg = Config()
cfg.state_dir, cfg.history_dir, cfg.automas_dir = B, None, None


class _Src:
    def fetch(self, seen):
        return []


e = eng_mod.Engine(cfg, source=_Src(), state=State(B), notifier=_Notifier())
now = datetime.now(SERVER_TZ)
entry = {"run_id": f"{TODAY}/ark/MAA-09-00-00", "script": "MAA", "user": "ark", "started": now.isoformat(),
         "finished": now.isoformat(), "ok": True, "failed_tasks": [], "duration_known": True,
         "transitional": False, "raw": {"tasks_done": ["日常"]}}
_, body = e._compose_daily(TODAY, [entry])
check("日报带「中继自己记下的报错」", "中继自己记下的报错" in body)
check("日报写已报群", "已报群" in body)
check("排队中的写「还在排队等着报群」", "还在排队等着报群" in texts.relay_faults_section(
    [{"where": "ark.report", "line": "日报没发出去", "count": 2, "pushed": 0}]))

print("\n[文案与路由]")
check("标题走群", route_of(texts.RELAY_ERROR, alert=True), "group")
check("原话是人话时照抄", "它说：日报没发出去" in texts.relay_error_body("ark.report", "日报没发出去", "10:47"))
check("正文是人话（两种样例）", [texts.plain(x) for x in (texts.relay_error_body("ark.service", "ConnectionRefusedError: [WinError 10061]", "21:21"), texts.relay_error_body("ark.report", "日报没发出去", "10:47"))], [[], []])
check("正文不再说「同一次开机只报这一条」", "同一次开机只报这一条" in texts.relay_error_body("ark.report", "x", ""), False)

for x in HANDLERS:
    drop(x)
print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
