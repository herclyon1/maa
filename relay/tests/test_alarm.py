"""WeChat group alarms, error forwarding, alert log, Mac push, and notification routing."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)
# relay/ first for every part, as each part used to put it (run_parts restores sys.path after one)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []

    def went_to_group(self):
        return True


def _part_alert_dedup():
    """The alerted-today marks (state.json marks.alerted:<day>), and what still uses them."""
    import types

    from ark_relay.core.engine import Engine

    E = object.__new__(Engine)

    def _fake_state(d):
        """替身 state：带上真的 StateStore，记账走 state.json（2026-09-08 收口后）。"""
        from ark_relay.core.statestore import StateStore
        return types.SimpleNamespace(dir=d, store=StateStore(d))

    E.state = _fake_state(tmpdir())
    rec = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=["流程产生错误"])

    k = E._alert_key(rec)
    check("第一次：没报过", E._already_alerted("2026-09-01", k), False)
    E._mark_alerted("2026-09-01", k)
    check("第二次：同键当天挡住", E._already_alerted("2026-09-01", k), True)
    rec2 = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=["在完成任务前退出"])
    check("换一步失败：是新事，放行", E._already_alerted("2026-09-01", E._alert_key(rec2)), False)
    check("跨天重置", E._already_alerted("2026-09-02", k), False)
    E._mark_alerted("2026-09-01", E._alert_key(rec2))
    check("两键共存互不干扰", E._already_alerted("2026-09-01", k), True)
    rec3 = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=None)
    check("failed_tasks 为空不炸", isinstance(E._alert_key(rec3), str), True)

    print("\n[OK-WW fails twice on the same step the same day: two alarms]")
    import os
    from datetime import datetime, timedelta
    from ark_relay.core import engine as eng_mod
    from ark_relay.features import handle
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, kw.get("alert", False)))
            return []

    class Src:
        def fetch(self, seen):
            return []

    os.environ.setdefault("ARK_LLM_KEY", "")
    cfg = Config()
    cfg.state_dir, cfg.automas_dir, cfg.okww_dir = tmpdir(), None, None
    eng = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    eng._scripts_running = lambda: False
    eng._script_running = lambda name: False
    eng._verify_outcome = lambda r: None
    handle._ship_evidence = lambda e, r: ""
    handle._archive_okww_evidence = lambda e, r: None
    now = datetime.now(tz=SERVER_TZ).replace(hour=9, minute=0, second=0, microsecond=0)
    for i, run in enumerate(("09-00-00", "21-30-00")):
        t = now + timedelta(hours=12 * i, minutes=30 * i)
        eng._handle(RunRecord(run_id=f"{t:%Y-%m-%d}/wuwa/OK-WW-{run}", script="OK-WW", user="wuwa", started=t,
                              finished=t + timedelta(minutes=20), ok=False, failed_tasks=["流程产生错误"], raw={}))
        eng._flush_pending()
    check("two final alarms, same step", [x for x in eng.notifier.sent if x[1]], [("❌ OK-WW 失败", True)] * 2)


def _part_first_error_alert():  # noqa: C901
    """Every WARNING / ERROR the relay logs is pushed to the group, every time, at once;
nothing is dropped when the group refuses; nothing loops back from the push path.
    """
    import importlib
    import json
    import logging
    import os
    import threading
    import time
    import types
    from datetime import datetime


    TMP = tmpdir()
    B = TMP / "b"   # section_2's state dir; the daily-report part at the end reads it too
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                      COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="")
    from ark_relay.features import errwatch as alertlog, errwatch, errwatch as known_fixed
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core import notify as notify_mod
    from ark_relay.core.notify import route_of


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


    def _settled():
        """No handler on the ark logger has anything left to send. A record is queued by
    the logging call itself (ErrorKindAlert.emit runs on the caller's thread) and an
    item leaves the queue only after it was delivered and counted, so once every queue
    is empty no further push can come: a wrongly-sent extra one would still be queued."""
        return not any(pending(x) for x in ARK.handlers if isinstance(x, errwatch.ErrorKindAlert))


    def _wait(n, count, secs=3.0):
        """Until nothing is left to send (n then has every push it will get, `count` of
    them when the code is right; the check after the call says), or `secs`. Until 10-16
    a wait that got fewer than `count` sat out all of `secs` - every "no more is
    pushed" check - and each wait added 0.1 s: 7.9 of the file's 8.7 s were those sleeps."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < secs:
            if _settled():
                return
            time.sleep(0.01)


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
        import inspect
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
        check("正文说出在哪一部分、中文原话照抄（里面有我们自己的术语也抄）",
              "主程序" in n.sent[0][1] and "它说：AUTO-MAS 拉起后 45 秒内接口仍不通" in n.sent[0][1])
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
        check("带异常名的那条说的是原因，不抄英文、不说半截话（账本 #162）",
              ("中途断开" in n.sent[2][1], "ConnectionResetError" in n.sent[2][1], "留在中继日志里" in n.sent[2][1]),
              (True, False, False))
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


    def section_5b():
        print("\n[the queue file on disk is unreadable at start: the group hears it]")
        Q = TMP / "q5b"
        Q.mkdir()
        (Q / errwatch.QUEUE_FILE).write_text('[{"title": "重启前排着的', encoding="utf-8")
        n = _Notifier()
        h = make(n, Q)
        h.drain(timeout=5.0)
        check("one push saying the queued alarms were lost", [texts.LOST_ALARM_QUEUE in b for t, b, _ in n.sent], [True])
        check("its text reads as plain words", texts.plain(texts.LOST_ALARM_QUEUE), [])
        check("no daily-only row", [r for r in faults(Q) if r.get("daily_only")], [])
        check("counted for the technical log", [errwatch.QUEUE_FILE in r.get("line", "") for r in faults(Q)], [True])
        drop(h)
        M = TMP / "q5b-missing"
        M.mkdir()
        n = _Notifier()
        h = make(n, M)
        h.drain(timeout=2.0)
        check("no queue file yet: nothing pushed, no row", (n.sent, faults(M)), ([], []))
        drop(h)


    section(section_5b)


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
        # "Waited long enough" is the handler's clock minus the record's time, and the
        # first attempt's wait already includes the two fsync'd writes the log call does
        # (queue file, day file). With a real 0.2 s fallback a slow disk (the Windows
        # runner, 8 test files at once) put the first attempt past it: straight to
        # the usual route, no robot. So the fallback is the product's and the test moves the
        # clock past it once the robot has refused.
        n = _Robot(fail=1000)
        skew = [0.0]
        h = make(n, TMP / "robot2", retry=(0.05,), fallback_after=errwatch.FALLBACK_AFTER_S,
                 clock=lambda: time.time() + skew[0])
        eng.error("机器人一直不收")
        t0 = time.monotonic()
        while "group" not in n.via and time.monotonic() - t0 < 3:
            time.sleep(0.02)
        check("没等够：只走机器人", ("group" in n.via, "send" in n.via), (True, False))
        skew[0] = errwatch.FALLBACK_AFTER_S + 1
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
        check("没登记的照普通报错推", [t for t, _, _ in n.sent[:2]], [texts.RELAY_ERROR] * 2)
        check("复发有自己的标题，带修好的版本", n.sent[2][0] if len(n.sent) > 2 else None,
              texts.relay_error_recurred("20261005151027"))
        check("复发标题照样进群", route_of(texts.relay_error_recurred("20261005151027"), alert=True), "group")
        check("复发正文说当时修的是什么", len(n.sent) > 2 and "游戏机缺读图组件" in n.sent[2][1])
        check("日报写「复发：v… 修过的又出现了」",
              errwatch.daily_section(C, TODAY).count("复发：v20261005151027 修过的又出现了"), 1)
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
        print("\n[所有 WARNING 均直推企微群，彻底废除 recovered() 与「自己好了，只进日报」]")
        R = TMP / "recovered"
        n = _Notifier()
        h = make(n, R)
        lg.warning("手机通道断了 20 秒，已重新连上")
        lg.warning("维护公告：终末地 取不到")
        _wait(n, 2)
        check("两条 WARNING 都直推群", len(n.sent), 2)
        check("不存在 recovered() 接口", hasattr(errwatch, "recovered"), False)
        check("技术日志摘要绝不写「自己好了，只进日报」", "自己好了，只进日报" not in errwatch.daily_section(R, TODAY))
        drop(h)


    section(section_recovered)


    def section_recovered_push_thread():
        print("\n[推送线程上的报错不回环到推送里，且仍记入当天报错表]")
        R = TMP / "recovered-push" / "state"
        n = _Notifier()
        h = make(n, R)
        pushlog = notify_mod.log

        def on_push_thread():
            pushlog.warning("企业微信机器人推送失败: 推送线程样例")
        t = threading.Thread(target=on_push_thread, name=errwatch.PUSH_THREAD + "-z")
        t.start()
        t.join()
        _wait(n, 0)
        check("推送线程上的报错不回到推送里", n.sent, [])
        check("记进当天报错表且无 recovered 标记",
              [bool(r.get("recovered")) for r in faults(R) if "推送线程样例" in str(r.get("line"))], [False])
        drop(h)


    section(section_recovered_push_thread)


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
        _wait(n2, 0)
        check("新进程（开机）不再重发同一条", n2.sent, [])
        drop(h)
        drop(h2)


    section(section_drain)


    print("\n[这一段进技术日志，不进日报（D-1010；report.write_daily_techlog）]")
    from ark_relay.features import report
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import Config
    from ark_relay.core.ledger import State

    # No network: the banner section and the report-writing model are stubbed, as in test_daily.py's _part_report_due.
    report.plan = types.SimpleNamespace(next_plan=lambda d: "", activity_countdown=lambda d: "",
                                        schedule=lambda d: [])
    report.banners = types.SimpleNamespace(
        collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
        read_image=None, state_dir=None: ([], {}),
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
    check("日报不带「中继自己记下的报错」", "中继自己记下的报错" in body, False)
    check("技术日志写成了", report.write_daily_techlog(e, TODAY), True)
    tech = (TMP / "tech" / f"{TODAY}.md").read_text(encoding="utf-8")
    check("技术日志带「中继自己记下的报错」", "中继自己记下的报错" in tech)
    check("技术日志写已报群", "已报群" in tech)
    check("排队中的写「还在排队等着报群」", "还在排队等着报群" in texts.relay_faults_section(
        [{"where": "ark.report", "line": "日报没发出去", "count": 2, "pushed": 0}]))

    print("\n[文案与路由]")
    check("标题走群", route_of(texts.RELAY_ERROR, alert=True), "group")
    check("原话是人话时照抄", "它说：日报没发出去" in texts.relay_error_body("ark.report", "日报没发出去", "10:47"))
    check("正文是人话（两种样例）", [texts.plain(x) for x in (texts.relay_error_body("ark.service", "ConnectionRefusedError: [WinError 10061]", "21:21"), texts.relay_error_body("ark.report", "日报没发出去", "10:47"))], [[], []])
    check("正文不再说「同一次开机只报这一条」", "同一次开机只报这一条" in texts.relay_error_body("ark.report", "x", ""), False)

    print("\n[ledger #162: a long line cut for the queue keeps the cause its end names]")
    _long = "维护公告：" + "很长的一段说明" * 30 + " ｜ URLError: <urlopen error [Errno 11001] getaddrinfo failed>"
    _cut = errwatch._kept(_long, 160)
    check("长行截到 160 字以内，末尾的原因还在", (len(_cut) <= 160, texts.fault_cause(_cut)),
          (True, texts.fault_cause(_long)))
    check("开头照旧是原话的开头", _cut.startswith("维护公告：很长的一段说明"), True)
    check("截出来的那条推送说的是原因", "域名解析失败" in texts.relay_error_body("ark.maintenance", _cut, "05:20:16"), True)
    check("短行原样", errwatch._kept("日报没发出去", 160), "日报没发出去")
    check("开头就读得出原因的长行照旧只取开头", errwatch._kept("TimeoutError: timed out " + "x" * 400, 160),
          ("TimeoutError: timed out " + "x" * 400)[:160])
    check("读不出原因的长行照旧只取开头", errwatch._kept("长" * 400, 160), "长" * 160)

    for x in HANDLERS:
        drop(x)
    print()
    print("\n[audit 11-08 C-05: two faults alike in their first 160 characters are two queue keys]")
    _h = errwatch.ErrorKindAlert(None, lambda: False, tmpdir(), known={})
    _same = "收集器读不了 " + "x" * 170
    _r1 = logging.LogRecord("ark.handle", logging.WARNING, __file__, 1, _same + " A 模块", None, None)
    _r2 = logging.LogRecord("ark.handle", logging.WARNING, __file__, 1, _same + " B 模块", None, None)
    check("different tails, different keys",
          _h._item(_r1, "s1", "t")["key"] != _h._item(_r2, "s2", "t")["key"], True)
    _h.close()

    if fails:
        print("FAILED:", fails)
        sys.exit(1)


def _part_failure_alert():
    """The immediate failure alert, and the three marks nobody ever read back."""
    from datetime import datetime, timedelta

    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.core.ledger import State, format_failure

    def rec(**kw):
        now = datetime(2026, 9, 8, 9, 18, tzinfo=SERVER_TZ)
        base = dict(run_id="2026-09-08/wuwa/OK-WW-09-00-00", script="OK-WW", user="wuwa",
                    started=now - timedelta(minutes=18), finished=now, ok=False,
                    failed_tasks=["任务执行：残象聚落"], raw={})
        base.update(kw)
        return RunRecord(**base)

    print("[标题就是失败标题，脚本名原样带出去]")
    title, body = format_failure(rec())
    check("标题", title, texts.failed("OK-WW"))
    check("正文带账号", "账号 wuwa" in body, True)

    print("\n[时间可信时才写用时]")
    check("写了用时 18 分钟", "用时 18 分钟" in body, True)
    check("不带偏差提示", "可能有偏差" in body, False)
    check("起止都在", ("09:00" in body and "09:18" in body), True)

    print("\n[时间不可信时一个字都不许写成事实——文件名时间在这台机器上差好几小时]")
    _, body2 = format_failure(rec(duration_known=False))
    check("不写用时", "用时 18 分钟" in body2, False)
    check("明说时长未知", "时长未知" in body2, True)
    check("明说时间取自文件名", "时间取自文件名，不是日志" in body2, True)

    print("\n[哪一步坏了必须一眼看见（08-27 丢过「失败于」三个字）]")
    check("单项带「失败于」", "失败于：任务执行：残象聚落" in body, True)
    _, many = format_failure(rec(failed_tasks=["一", "二", "三", "四", "五"]))
    check("多项写清共几项", "失败于 5 项：" in many, True)
    check("多项只列前三个", many.count("、") >= 2 and "四" not in many, True)
    _, none = format_failure(rec(failed_tasks=[]))
    check("一项都没有时不留空", "失败于：未知" in none, True)

    print("\n[理智有就写，没有就不许凭空出现]")
    _, with_sanity = format_failure(rec(raw={"sanity": 42, "sanity_full_at": "今天 21:30 回满"}))
    check("写了剩余理智", "剩余理智 42" in with_sanity, True)
    check("写了回满时刻", "今天 21:30 回满" in with_sanity, True)
    check("没有理智就不写这行", "剩余理智" in body, False)

    print("\n[诊断接在正文后面，没诊断就不加分隔线]")
    _, diag = format_failure(rec(), diagnosis="游戏没到主界面")
    check("诊断在正文里", diag.endswith("游戏没到主界面"), True)
    check("有诊断才有分隔线", "─" in diag and "─" not in body, True)

    print("\n[三个标记：写进去，换一个实例读回来还在（机器一天硬断电两次）]")
    d = tmpdir()
    st = State(d)
    check("没写过时临时日报没发过", st.interim_sent("2026-09-08"), False)
    st.mark_interim_sent("2026-09-08", covered=7)
    check("写完读回来算发过", State(d).interim_sent("2026-09-08"), True)
    check("覆盖条数读得回来", State(d).interim_covered("2026-09-08"), 7)
    check("别的日子不受影响", State(d).interim_sent("2026-09-07"), False)

    check("没写过时卡池没播报过", st.banner_announced("鸣潮|2026-09-10 10:00"), False)
    st.mark_banner_announced("鸣潮|2026-09-10 10:00")
    check("写完读回来算播报过", State(d).banner_announced("鸣潮|2026-09-10 10:00"), True)
    check("另一个游戏同一天不算", State(d).banner_announced("终末地|2026-09-10 10:00"), False)

    st.mark_report_sent("2026-09-08")
    check("日报标记独立于临时日报", (State(d).report_sent("2026-09-08"),
                                    State(d).report_sent("2026-09-09")), (True, False))


def _part_group_long_alarm():
    """One alarm must never flood the group (2026-11-05 北京 10:56)."""
    from datetime import datetime

    from ark_relay.core import notify, texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import runwatch

    LOG = "\n".join(f"[2026-11-05 11:{i // 60:02d}:{i % 60:02d}.212] 正在识别画面并点击开始唤醒按钮第 {i} 次，等待游戏响应中……" * 2
                    for i in range(343)) + "\n[2026-11-05 11:26:30.212] 正在连接窗口... Endfield\n\n"

    print("[runwatch.last_log_line]")
    check("the last non-empty line", runwatch.last_log_line(LOG), "[2026-11-05 11:26:30.212] 正在连接窗口... Endfield")
    check("nothing: empty", runwatch.last_log_line(None), "")
    long_line = "x" * 500
    check("a long last line is cut to 200", len(runwatch.last_log_line("a\n" + long_line)), 200)

    print("[the overrun alarm text]")
    due, now = datetime(2026, 11, 5, 9, 0, tzinfo=SERVER_TZ), datetime(2026, 11, 5, 10, 57, tzinfo=SERVER_TZ)
    body = texts.shift_overrun_body("早班", due, now, 87, 30, "MAA 完成、MaaEnd 运行", runwatch.last_log_line(LOG), 7)
    check("built from the whole log it is still one robot message", len(notify.WeCom._split(body, notify.WeComBot._LIMIT)), 1)
    check("it quotes the last line", "AUTO-MAS 最后一句：[2026-11-05 11:26:30.212] 正在连接窗口... Endfield" in body, True)

    print("[WeComBot: at most MAX_PARTS messages]")
    posts = []
    notify._post_json = lambda url, payload: posts.append(payload["text"]["content"]) or {"errcode": 0}
    bot = notify.WeComBot.__new__(notify.WeComBot)
    bot.url = "https://fake.test/robot"
    huge = "⏰ 早班还没跑完\n早班 09:00 开跑……\nAUTO-MAS 最后一句：" + LOG
    check("the 11-05 text would have been many messages", len(notify.WeCom._split(huge, notify.WeComBot._LIMIT)) > 20, True)
    bot.send_text(huge)
    check("now at most MAX_PARTS messages", len(posts) <= notify.WeComBot.MAX_PARTS, True)
    check("the first message starts with the title", posts[0].split("\n", 1)[1].startswith("⏰ 早班还没跑完"), True)
    check("the last message ends with the plain note", posts[-1].endswith("（后面还有很长一段没发，免得刷屏）"), True)
    check("every message within the robot's 2048 bytes", all(len(p.encode("utf-8")) <= 2048 for p in posts), True)
    check("numbering says the real count", posts[-1].startswith(f"（{len(posts)}/{len(posts)}）"), True)
    posts.clear()
    bot.send_text("一" * 20000)
    check("one huge line without breaks: also at most MAX_PARTS", len(posts) <= notify.WeComBot.MAX_PARTS, True)
    posts.clear()
    bot.send_text("短消息")
    check("a short text: one message, unchanged", posts, ["短消息"])
    posts.clear()
    two = "甲" * 500 + "\n" + "乙" * 500
    bot.send_text(two)
    check("a two-part text: two messages as before, no note", (len(posts), any("免得刷屏" in p for p in posts)), (2, False))

    print("\n[audit 11-08 C-04: a capped message keeps its evidence link at the end]")
    _long = "终末地早班没跑成\n" + "\n".join("日志行 " + "x" * 200 + f" {i}" for i in range(400)) \
        + "\n证据包：https://example.invalid/e/abc"
    _capped = notify.WeComBot._cap(_long)
    check("capped to MAX_PARTS", len(notify.WeCom._split(_capped, notify.WeComBot._LIMIT)) <= notify.WeComBot.MAX_PARTS, True)
    check("the head is kept", _capped.splitlines()[0], "终末地早班没跑成")
    check("the evidence link is the last line", _capped.splitlines()[-1], "证据包：https://example.invalid/e/abc")
    check("the cut is said, in the middle", "（中间还有很长一段没发，免得刷屏）" in _capped, True)


def _part_uptime_alarm():
    """The shutdown floor is an alarm: once 「开机不够久」 passes, the relay judges again."""
    import json
    import os
    from datetime import datetime

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", ARK_CHECK_TIMES="",
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State

    class Notes:
        def send(self, title, body="", **kw):
            return False

    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)

    def build(after_run=True):
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.shutdown_after_run = after_run
        e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._started_at = at(18, 3, 57)
        return e

    print("[10-01: restarted 18:03:57, floor 600 s -> the next alarm is 18:13:57]")
    when, why = build().next_deadline(at(18, 4, 15))
    check("when", when, at(18, 13, 57))
    check("why", why, "开机满下限，重新判一次关机")

    print("\n[past the floor it is no longer an alarm]")
    d = build().next_deadline(at(18, 20))
    check("not the floor any more", bool(d) and d[1] == "开机满下限，重新判一次关机", False)

    print("\n[shutdown switched off -> no floor alarm]")
    d = build(after_run=False).next_deadline(at(18, 4, 15))
    check("no floor alarm", bool(d) and d[1] == "开机满下限，重新判一次关机", False)


def _part_errwatch_midnight_counts():
    """errwatch's per-day counts survive the switch to the next day."""
    import json
    import logging
    from datetime import datetime

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import errwatch

    class Notes:
        def send(self, title, body="", **kw):
            return []

    def record(at: datetime, msg: str) -> logging.LogRecord:
        r = logging.LogRecord("ark.report", logging.WARNING, __file__, 1, msg, None, None)
        r.created = at.timestamp()
        return r

    state = tmpdir()
    h = errwatch.ErrorKindAlert(Notes(), state_dir=state, known={}, clock=lambda: 1000.0, pace=0, retry=(0,))
    try:
        h.handle(record(datetime(2026, 10, 12, 23, 59, 40, tzinfo=SERVER_TZ), "日报没发出去"))
        h.handle(record(datetime(2026, 10, 12, 23, 59, 50, tzinfo=SERVER_TZ), "日报没发出去"))   # unsaved repeat
        h.handle(record(datetime(2026, 10, 13, 0, 0, 5, tzinfo=SERVER_TZ), "补跑没派出去"))     # next day
    finally:
        h.close()
    day = json.loads((state / errwatch.DAY_DIR / "2026-10-12.json").read_text(encoding="utf-8"))
    check("10-12 keeps both records", [r.get("count") for r in day.values()], [2])


def _part_known_fixed_live():
    """Every known_fixed entry can still match: its message is logged at WARNING or above."""
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from ark_relay.features import errwatch as known_fixed

    CALL = re.compile(r"\.(warning|error|exception|critical|info|debug)\(\s*(f?\"[^\"]*\"|f?'[^']*')", re.S)
    levels: dict[str, set[str]] = {}
    for f in (ROOT / "ark_relay").rglob("*.py"):
        if f.name == "known_fixed.py":
            continue
        for m in CALL.finditer(f.read_text(encoding="utf-8")):
            levels.setdefault(m.group(2), set()).add(m.group(1))

    LOUD = {"warning", "error", "exception", "critical"}
    for key in known_fixed.KNOWN:
        msg = key.split("|")[1]
        head = re.split(r"#|<path>|<url>|<id>", msg)[0].strip()
        found = {lv for lit, lvs in levels.items() if head in lit for lv in lvs}
        check(f"{key!r}: logged at WARNING or above", bool(found & LOUD), True)


def _part_unresolved():
    """A MAA / MaaEnd problem the relay could not fix goes to the group - every time."""
    import json
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from ark_relay.features import handle, handle as unresolved
    from ark_relay.features import makeup
    from ark_relay.features import outcome
    from ark_relay.features import report
    from ark_relay.core import texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import route_of
    from ark_relay.features import machinecheck as _mc
    _mc.load()
    _mc_real = dict(_mc.CHECKS)   # put back at the end: the coverage pass runs every test file in one process
    _mc.CHECKS.clear()   # the alarms themselves are tested here; the machine checks in tests/test_mc.py

    def automas_dir(queues) -> Path:
        """An AUTO-MAS config dir: queues = [(name, [times], [script kinds])]."""
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
        for k, p in paths.items():
            sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
        qc = {"instances": []}
        for n, (name, times, kinds) in enumerate(queues):
            uid = f"q{n}"
            qc["instances"].append({"uid": uid})
            ts = {"instances": []}
            for i, t in enumerate(times):
                ts[f"t{i}"] = {"Info": {"Enabled": True, "Time": t}}
            items = {"instances": []}
            for i, k in enumerate(kinds):
                items[f"i{i}"] = {"Info": {"ScriptId": f"s-{k}"}}
            qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                       "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root

    AUTOMAS = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
    # Today (real clock): makeup.eligible and _flush_pending read today's date.
    DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    D = f"{DAY:%Y-%m-%d}"
    PAGE = "https://cos.example/run.zip"

    def at(hh, mm=0, day=DAY):
        return day.replace(hour=hh, minute=mm)

    class Notes:
        def __init__(self, fail=False):
            self.sent, self.fail = [], fail

        def send(self, title, body="", **kw):
            if self.fail:
                return ["企业微信机器人：发不出去"]
            self.sent.append((title, body, kw.get("alert", False)))
            return []

    class Src:
        def fetch(self, seen):
            return []

    def build(automas=AUTOMAS, notes=None):
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = automas
        cfg.maa_dir = None
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=notes or Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._maintenance_today = lambda game: False
        return e

    def ship(eng, rec):
        rec.raw["evidence_page"] = PAGE
        return PAGE

    handle._ship_evidence = ship
    dispatched = []
    makeup._dispatch = lambda script: (dispatched.append(script) or (True, "已开跑"))
    makeup._kill_game = lambda: None

    def rec(script, started, ok=False, failed=None, raw=None, tag=""):
        user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
        return RunRecord(run_id=f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}{tag}", script=script, user=user,
                         started=started, finished=started + timedelta(minutes=20), ok=ok,
                         failed_tasks=list(failed if failed is not None else ([] if ok else ["开始唤醒"])),
                         raw=dict(raw or {}))

    def alarms(e):
        return [t for t, _, a in e.notifier.sent if a]

    def last_body(e):
        bodies = [b for _, b, a in e.notifier.sent if a]
        return bodies[-1] if bodies else ""

    def fail_and_makeup_fails(e, script, started, failed=None):
        """A failure held, its make-up dispatched, the make-up's record failed too."""
        first = rec(script, started, failed=failed)
        handle._handle(e, first)
        e._flush_pending()
        held = (dict(e._pending), len(alarms(e)))
        makeup.maybe_run(e, started + timedelta(hours=1))
        e._flush_pending()
        waiting = dict(e._pending)
        handle._handle(e, rec(script, started + timedelta(hours=1, minutes=1), failed=failed))
        e._flush_pending()
        return held, waiting

    print("[哪一班：按 AUTO-MAS 的队列时刻，读不到就按中午前后]")
    e = build()
    check("09:05 → 早班", unresolved.where(e, rec("MAA", at(9, 5)))[1], "早班")
    check("14:00 的补跑也算早班", unresolved.where(e, rec("MAA", at(14)))[1], "早班")
    check("21:35 → 晚班", unresolved.where(e, rec("MAA", at(21, 35)))[1], "晚班")
    check("班前五分钟开的也算这一班", unresolved.where(e, rec("MAA", at(21, 26)))[1], "晚班")
    e = build(automas=None)
    check("没配置：11:00 → 早班", unresolved.where(e, rec("MAA", at(11)))[1], "早班")
    check("没配置：13:00 → 晚班", unresolved.where(e, rec("MAA", at(13)))[1], "晚班")

    print("\n[早班失败 → 补跑也没成 → 进群一次，带游戏、班次、原因、证据包]")
    e = build()
    held, waiting = fail_and_makeup_fails(e, "MAA", at(9, 5))
    check("补跑前压着，不推", (list(held[0]), held[1]), ([("MAA", "arknights")], 0))
    check("补跑派下去了，还在等它", list(waiting), [("MAA", "arknights")])
    check("一条进群", alarms(e), [texts.unresolved("明日方舟", "早班")])
    check("标题进群", route_of(texts.unresolved("明日方舟", "早班"), alert=True), "group")
    head = last_body(e).splitlines()[0]
    check("头一行", head, f"明日方舟早班没跑成，补跑也没成：卡在 开始唤醒（证据包 {PAGE}）")
    check("证据链接只出现一次", last_body(e).count(PAGE), 1)
    check("不再压着", dict(e._pending), {})
    e._flush_pending()
    check("下一轮不再推", len(alarms(e)), 1)
    handle._handle(e, rec("MAA", at(9, 50), tag="b"))
    e._flush_pending()
    check("同一班再失败一次：再推一条", alarms(e), [texts.unresolved("明日方舟", "早班")] * 2)
    check("…不再压着", dict(e._pending), {})
    handle._handle(e, rec("MAA", at(21, 35), failed=["开始唤醒"]))
    e._flush_pending()
    check("晚班再失败：推晚班", alarms(e)[2:], [texts.unresolved("明日方舟", "晚班")])
    check("晚班那条说补跑一天只有一次", "没补跑：补跑一天只有一次，今天的已经用过了" in last_body(e), True)
    handle._handle(e, rec("MAA", at(22, 10), failed=["开始唤醒"]))
    e._flush_pending()
    check("晚班再来：再推", len(alarms(e)), 4)
    e._flush_pending()
    check("同一条记录不推两次", len(alarms(e)), 4)

    print("\n[终末地找不到母本、补跑没能开跑 → 进群，说补跑为什么没开跑]")
    e = build()
    fail_and_makeup_fails(e, "MaaEnd", at(10), failed=["基质刷取"])
    # No make-up went out, so the second failed record is a failure of its own: it rings too.
    check("两条进群（补跑没开跑的那条、后来又失败的那条）", alarms(e), [texts.unresolved("终末地", "早班")] * 2)
    check("头一行", ([b for _, b, a in e.notifier.sent if a] or [""])[0].splitlines()[:1],
          [f"终末地早班没跑成，补跑没能开跑（找不到终末地的母本）：卡在 基质刷取（证据包 {PAGE}）"])
    check("没有派补跑", makeup.read_marker(e.cfg.state_dir, D)["MaaEnd"]["result"], makeup.GAVE_UP)

    print("\n[11-20 (#187)：三个任务是同一个原因，「卡在」后面只说一次]")
    from ark_relay.features.collector_maaend import AGREEMENT, BAG_FULL
    TASKS = ["赠送干员礼物", "装备制造", "拜访好友", "基建任务"]
    check("同一个原因：说一次，放在后面", handle._stuck(TASKS, {t: AGREEMENT for t in TASKS}, False),
          f"赠送干员礼物、装备制造、拜访好友…（{AGREEMENT}）")
    check("前 3 项相同但第 4 项不同/无原因：不把尾因硬挂到省略号后",
          handle._stuck(TASKS, {t: AGREEMENT for t in TASKS[:3]}, False),
          f"赠送干员礼物（{AGREEMENT}）、装备制造（{AGREEMENT}）、拜访好友（{AGREEMENT}）…")
    check("三个以内也一样", handle._stuck(TASKS[:2], {t: AGREEMENT for t in TASKS}, False),
          f"赠送干员礼物、装备制造（{AGREEMENT}）")
    check("原因不同：各说各的（跟以前一样）",
          handle._stuck(["基质刷取", "装备制造"], {"基质刷取": BAG_FULL, "装备制造": AGREEMENT}, False),
          f"基质刷取（{BAG_FULL}）、装备制造（{AGREEMENT}）")
    check("有的有原因、有的没有：各说各的", handle._stuck(["基质刷取", "装备制造"], {"基质刷取": BAG_FULL}, False),
          f"基质刷取（{BAG_FULL}）、装备制造")
    check("都没有原因：跟以前一样", handle._stuck(TASKS, {}, False), "赠送干员礼物、装备制造、拜访好友…")
    check("只有一个：照旧带在它后面", handle._stuck(["基质刷取"], {"基质刷取": BAG_FULL}, False), f"基质刷取（{BAG_FULL}）")
    check("手动停的不算卡点", handle._stuck([texts.AUTOMAS_MANUAL_STOP, "装备制造"], {}, True), "装备制造")
    e = build()
    causes = {t: AGREEMENT for t in TASKS}
    first = rec("MaaEnd", at(9, 34), failed=TASKS, raw={"maaend_fail_causes": causes})
    handle._handle(e, first)
    e._flush_pending()
    makeup.maybe_run(e, at(10, 34))
    e._flush_pending()
    handle._handle(e, rec("MaaEnd", at(10, 35), failed=TASKS, raw={"maaend_fail_causes": causes}))
    e._flush_pending()
    heads = [b.splitlines()[0] for _, b, a in e.notifier.sent if a]
    check("进群那条的头一行：卡在 … 后面原因只说一次",
          [h.split("；", 1)[-1].split("：", 1)[-1] for h in heads[-1:]],
          [f"卡在 赠送干员礼物、装备制造、拜访好友…（{AGREEMENT}）（证据包 {PAGE}）"])

    print("\n[补跑走通：中途失败属于真实故障，直推企微群排查，绝不进日报（2026-11-28 规则）]")
    e = build()
    handle._handle(e, rec("MAA", at(9, 5)))
    e._flush_pending()
    makeup.maybe_run(e, at(10, 5))
    handle._handle(e, rec("MAA", at(10, 6), ok=True))
    e._flush_pending()
    check("补跑记成走通", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.OK)
    check("补跑走通立即直推群（带 alert=True）", [(t, a) for t, _, a in e.notifier.sent],
          [(texts.makeup_passed("明日方舟", "早班"), True)])
    check("日报 makeup_line 严格返回空串（细节仅进技术日志）",
          (report.makeup_line(e.cfg.state_dir, D),
           report._makeup_tech_line(e.cfg.state_dir, D)),
          ("", "明日方舟失败后自动补跑，走通了（原来失败于：开始唤醒）"))
    check("不再压着（且引擎已移除 _recovered）", (dict(e._pending), hasattr(e, "_recovered")), ({}, False))
    before_again = len(e.notifier.sent)
    e._flush_pending()
    check("下一轮不重复推", len(e.notifier.sent), before_again)

    print("\n[不符合补跑条件的明日方舟失败（打过仗）：进群一次，写为什么没补跑]")
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), raw={"sanity_spent": 120}))
    e._flush_pending()
    makeup.maybe_run(e, at(10, 5))
    check("没派补跑", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.GAVE_UP)
    e._flush_pending()
    check("一条进群", alarms(e), [texts.unresolved("明日方舟", "早班")])
    check("写了没补跑的原因", "没补跑：这一轮已经开始干活（花过理智），再跑一遍会再吃一份理智药" in last_body(e), True)

    print("\n[派不下去，次数用完：进群一次，说补跑没能开跑]")
    e = build()
    handle._handle(e, rec("MAA", at(9, 5)))
    makeup._dispatch = lambda script: (False, "AUTO-MAS 没回话")
    for i in range(makeup.MAX_TRIES):
        e._flush_pending()
        makeup.maybe_run(e, at(10, 5 + 3 * i))
    makeup._dispatch = lambda script: (dispatched.append(script) or (True, "已开跑"))
    e._flush_pending()
    check("一条进群", alarms(e), [texts.unresolved("明日方舟", "早班")])
    check("说补跑没能开跑", "补跑没能开跑（AUTO-MAS 没回话）" in last_body(e), True)

    print("\n[没干完：每次都进群，同一班的失败也照报]")
    e = build()
    e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：日志里没有换班"
    handle._handle(e, rec("MAA", at(9, 5), ok=True))
    check("一条进群", alarms(e), [texts.unresolved_undone("明日方舟", "早班")])
    check("头一行", last_body(e).splitlines()[0],
          f"明日方舟早班跑完了但没干完：基建换班，这一类不补跑（证据包 {PAGE}）")
    check("账本记了没干完", bool(e.state.read_ledger(D)[0].get("incomplete")), True)
    e._verify_outcome = lambda r: None
    fail_and_makeup_fails(e, "MAA", at(9, 40))
    check("同一班后来失败、补跑也没成：照报", alarms(e),
          [texts.unresolved_undone("明日方舟", "早班"), texts.unresolved("明日方舟", "早班")])
    e = build()
    fail_and_makeup_fails(e, "MAA", at(9, 5))
    e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：日志里没有换班"
    handle._handle(e, rec("MAA", at(11, 30), ok=True))
    check("先失败已报过，同一班再没干完：照报", alarms(e),
          [texts.unresolved("明日方舟", "早班"), texts.unresolved_undone("明日方舟", "早班")])
    handle._handle(e, rec("MAA", at(21, 35), ok=True))
    check("晚班没干完：再报", alarms(e)[2:], [texts.unresolved_undone("明日方舟", "晚班")])

    print("\n[终末地只是设置被新版本重置：照样进群，但说「没按你的设置跑」，不说没干完]")
    e = build()
    _reset = outcome.summarize([outcome.Check("任务全部完成（跑完没自己退出）", True),
                                *outcome._dropped_checks(["AutoStockBuyDailyGoodsValleyIV", "AutoStockBuyDailyGoodsWuling"])],
                               "MaaEnd")
    e._verify_outcome = lambda r: _reset
    handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
    check("进群一条，标题是没按你的设置跑", alarms(e), [texts.unresolved_settings("终末地", "早班")])
    check("头一行", last_body(e).splitlines()[0],
          f"终末地早班跑完了，但新版本把设置重置成了默认值：自动囤货的设置，这一类不补跑（证据包 {PAGE}）")
    check("整条不说没干完 / 没干成", "没干" not in last_body(e), True)
    e = build()
    _mixed = outcome.summarize([outcome.Check("自动采集 真的走了路线", False, "自动采集 38 秒就报「任务完成」，日志里没有走了路线的痕迹"),
                                *outcome._dropped_checks(["AutoCollectRoutes", "SendWrongGift"])], "MaaEnd")
    e._verify_outcome = lambda r: _mixed
    handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
    check("真没干成 + 设置被重置：按没干完进群", alarms(e), [texts.unresolved_undone("终末地", "早班")])
    check("头一行只点名真没干成的那项，不把设置算进没干完", last_body(e).splitlines()[0],
          f"终末地早班跑完了但没干完：自动采集，这一类不补跑（证据包 {PAGE}）")
    check("设置那两行还在正文里", "· 自动采集的设置：" in last_body(e) and "· 其他的设置：" in last_body(e), True)

    print("\n[终末地没干完的是自动采集：照样当场进群，第一句不再说「这一类不补跑」，说路线会单独补（账本 #166 #170）]")
    from ark_relay.features import collect_retry as _cr
    _only = outcome.summarize([outcome.Check("自动采集 真的走了路线", False, "路线2：协议纹石采集失败")], "MaaEnd")
    _routes = ["采集血菌", "采集协议纹石（路线2）"]
    _saved_ahead = _cr.retry_ahead
    try:
        for _state, _want in ((_cr.AHEAD, "中继会在关机前单独补一次，补的结果另报"),
                              (_cr.AHEAD_DEBUG, "现在调试模式开着、中继不关机，所以还没有补"),
                              (_cr.AHEAD_SPENT, "不再补：今天单独补路线的那一次已经用过")):
            _cr.retry_ahead = lambda eng, r, _s=_state: (list(_routes), _s)
            e = build()
            e._verify_outcome = lambda r: _only
            handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
            _first = last_body(e).splitlines()[0]
            check(f"{_state}：进群一条「没干完」，第一句说不整轮补、点名路线、说清会不会单独补",
                  (alarms(e), "这一类不整轮补跑" in _first, "这一类不补跑" in _first, _want in _first, "采集协议纹石（路线2）" in _first),
                  ([texts.unresolved_undone("终末地", "早班")], True, False, True, True))
            check(f"{_state}：是人话", texts.plain(_first.replace(PAGE, "")), [])
        _cr.retry_ahead = lambda eng, r: ([], "")
        e = build()
        e._verify_outcome = lambda r: _only
        handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
        check("日志里读不出没走通的路线（单独补没有可补的）：还是原来那句", last_body(e).splitlines()[0],
              f"终末地早班跑完了但没干完：自动采集，这一类不补跑（证据包 {PAGE}）")
        _cr.retry_ahead = lambda eng, r: (_ for _ in ()).throw(OSError("boom"))
        e = build()
        e._verify_outcome = lambda r: _only
        handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
        check("读路线时出错：报警照样进群，用原来那句", (alarms(e), last_body(e).splitlines()[0]),
              ([texts.unresolved_undone("终末地", "早班")], f"终末地早班跑完了但没干完：自动采集，这一类不补跑（证据包 {PAGE}）"))
        _asked = []
        _cr.retry_ahead = lambda eng, r: _asked.append(r.script) or (list(_routes), _cr.AHEAD)
        e = build()
        e._verify_outcome = lambda r: outcome.summarize([outcome.Check("基建换班 真的换了", False, "没换")], "MAA")
        handle._handle(e, rec("MAA", at(9, 5), ok=True))
        check("明日方舟的没干完不问采集路线，照旧说这一类不补跑", (_asked, "这一类不补跑" in last_body(e).splitlines()[0]), ([], True))
        e = build()
        e._verify_outcome = lambda r: outcome.summarize([outcome.Check("基质刷取 真的刷了", False, "没刷")], "MaaEnd")
        handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
        check("终末地没干完的不是自动采集：也不问，照旧", (_asked, "这一类不补跑" in last_body(e).splitlines()[0]), ([], True))
    finally:
        _cr.retry_ahead = _saved_ahead

    print("\n[终末地只差自动采集 / 应急理智加强剂：照样进群]")
    e = build()
    e._verify_outcome = lambda r: ("MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n"
                                   "· 自动采集 真的走了路线：自动采集 38 秒就报「任务完成」，日志里没有走了路线的痕迹\n干成的：MaaEnd 跑完")
    handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
    check("没干完只差自动采集：进群", alarms(e), [texts.unresolved_undone("终末地", "早班")])
    check("头一行写出自动采集", last_body(e).startswith("终末地早班跑完了但没干完：自动采集"), True)
    e._verify_outcome = lambda r: "MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 🧺自动采集 真的采集了：🧺自动采集 38 秒就报「任务完成」，日志里没有采集的痕迹"
    handle._handle(e, rec("MaaEnd", at(9, 30), ok=True))
    check("只有自动采集没收尾：也进群", len(alarms(e)), 2)
    e._verify_outcome = lambda r: None
    handle._handle(e, rec("MaaEnd", at(9, 50), failed=["自动采集", "应急理智加强剂"]))
    check("失败只在自动采集 / 应急理智加强剂：压着等补跑，不丢", list(e._pending), [("MaaEnd", "endfield")])
    e._flush_pending()
    makeup.maybe_run(e, at(10, 30))
    e._flush_pending()
    check("补跑之后没成：进群", alarms(e)[2:], [texts.unresolved("终末地", "早班")])
    check("写了卡在哪", "卡在 自动采集、应急理智加强剂" in last_body(e), True)
    for only in ("应急理智加强剂", "自动采集"):
        e = build()
        handle._handle(e, rec("MaaEnd", at(9, 50), failed=[only]))
        e._flush_pending()
        makeup.maybe_run(e, at(10, 30))
        e._flush_pending()
        check(f"只有「{only}」失败：进群", alarms(e), [texts.unresolved("终末地", "早班")])
    check("SOFT_FAILS 没了", hasattr(e, "SOFT_FAILS") or hasattr(unresolved, "soft_only"), False)

    print("\n[进不了游戏、理智不够、手动开的、更新日、红按钮停的都响]")
    e = build()
    # 「进不了游戏」needs official evidence (handle._confirm_unreachable); here the
    # update notice. Without it the shape alone rings: test_unreachable.py.
    real_hint = handle.efstatus.update_hint
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: "官方公告：今天 10:00 「雪凇幽梦」版本更新"
    handle._handle(e, rec("MaaEnd", at(9, 5), raw={"maaend_unreachable_shape": True}))
    handle.efstatus.update_hint = real_hint
    e._flush_pending()
    check("进不了游戏（有更新公告）：进群", alarms(e), [texts.cant_enter("MaaEnd")])
    check("…写着那条官方公告", "官方依据：官方公告：今天 10:00 「雪凇幽梦」版本更新" in last_body(e), True)
    e = build()
    e._maintenance_today = lambda game: True
    handle._handle(e, rec("MAA", at(9, 5)))
    check("更新日：马上进群，不压着、不补跑", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
    check("更新日：头一行说是更新日", last_body(e).splitlines()[:1], [getattr(texts, "UPDATE_DAY_NOTE", "-")])
    check("更新日：带证据包", PAGE in last_body(e), True)
    e._flush_pending()
    check("更新日：下一轮不重推", len(alarms(e)), 1)
    e = build()
    real_short = outcome.maa_sanity_short
    outcome.maa_sanity_short = lambda text: {"have": 17, "cost": 25}
    handle._handle(e, rec("MAA", at(9, 5)))
    e._flush_pending()
    check("理智不够：马上进群、不压着", (alarms(e), dict(e._pending)), ([getattr(texts, "MAA_SANITY_SHORT", "-")], {}))
    check("…写着两个数", "理智 17" in last_body(e) and "一次要 25" in last_body(e), True)
    handle._handle(e, rec("MAA", at(9, 5)))      # the same record replayed
    check("…同一条记录不推两次", (len(alarms(e)), dict(e._pending)), (1, {}))
    outcome.maa_sanity_short = real_short
    e = build()
    real_hand = handle._hand_started
    handle._hand_started = lambda eng, r: "手动开始"
    handle._handle(e, rec("MAA", at(9, 5)))
    check("手动开的失败：先压着，等同一任务后面那次", (alarms(e), list(e._pending)), ([], [("MAA", "arknights")]))
    e._flush_pending()
    check("手动开的失败：同一任务里没有后来跑成的，进群", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
    check("…头一行说是手动开的", last_body(e).splitlines()[:1], [getattr(texts, "HAND_STARTED_NOTE", "-")])
    handle._hand_started = lambda eng, r: "又一个手动任务"
    e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：x"
    handle._handle(e, rec("MAA", at(9, 40), ok=True))
    handle._hand_started = real_hand
    e._flush_pending()
    check("手动开的没干完：也进群", alarms(e), [texts.failed("MAA"), texts.ROUND_INCOMPLETE])
    check("…说是手动开的", last_body(e).startswith(getattr(texts, "HAND_STARTED_NOTE", "-")), True)
    check("不补跑（没派）", makeup.read_marker(e.cfg.state_dir, D).get("MAA"), None)
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), raw={"manual_stop": "停一切"}))
    e._flush_pending()
    check("红按钮停的失败：进群，不压着", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
    check("…说是停一切停掉的", last_body(e).startswith("这一趟是停一切停掉的（停一切）"), True)
    e = build()
    handle._handle(e, rec("MAA", at(9, 5)))
    check("压着的失败：先不进群", (alarms(e), list(e._pending)), ([], [("MAA", "arknights")]))
    real_hand = handle._hand_started
    handle._hand_started = lambda eng, r: "手动开始"
    handle._handle(e, rec("MAA", at(12, 5), ok=True))
    handle._hand_started = real_hand
    e._flush_pending()
    check("后来有人手动跑成了：压着的失败照报进群", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
    check("…头一行说是有人手动跑成的", last_body(e).splitlines()[:1],
          [texts.hand_fixed_note("12:05") if hasattr(texts, "hand_fixed_note") else "-"])

    print("\n[推不出去：留着，下一轮再推]")
    notes = Notes(fail=True)
    e = build(notes=notes)
    fail_and_makeup_fails(e, "MAA", at(9, 5))
    check("推不出去：还压着", list(e._pending), [("MAA", "arknights")])
    check("…没记成已报", e._already_alerted(D, unresolved.alert_key(e._pending[("MAA", "arknights")])), False)
    notes.fail = False
    e._flush_pending()
    check("下一轮推出去一条", alarms(e), [texts.unresolved("明日方舟", "早班")])
    check("推出去了才放下", dict(e._pending), {})
    notes = Notes(fail=True)
    e = build(notes=notes)
    e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：x"
    handle._handle(e, rec("MAA", at(9, 5), ok=True))
    check("没干完推不出去：留着", len(e._unsent_unresolved), 1)

    notes.fail = False
    e._flush_pending()
    check("下一轮推出去", alarms(e), [texts.unresolved_undone("明日方舟", "早班")])
    check("推出去就不再留", e._unsent_unresolved, [])
    e._flush_pending()
    check("不重复推", len(alarms(e)), 1)

    print("\n[没干完推不出去，中继先重启了：重启后还在，推出去一次（audit s8 #3）]")
    notes = Notes(fail=True)
    e = build(notes=notes)
    e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：x"
    handle._handle(e, rec("MAA", at(9, 5), ok=True))
    notes2 = Notes()
    e_re = eng_mod.Engine(e.cfg, source=Src(), state=State(e.cfg.state_dir), notifier=notes2)
    check("重启后还留着", [x[3] for x in e_re._unsent_unresolved], [x[3] for x in e._unsent_unresolved])
    e_re._flush_pending()
    check("重启后推出去", alarms(e_re), [texts.unresolved_undone("明日方舟", "早班")])
    e_re2 = eng_mod.Engine(e.cfg, source=Src(), state=State(e.cfg.state_dir), notifier=notes2)
    check("推出去后再重启，盘上不再留", e_re2._unsent_unresolved, [])

    print("\n[程序说做完了但没证据：一轮跑完、重试也没补上证据，进群一次（用户 10-08 13:31「这个为什么不报警」）]")
    GIFT = {"tasks_done": ["赠送干员礼物", "装备制造"],
            "tasks_evidence": {"赠送干员礼物": "", "装备制造": "正在检查画面，提示登出账号是正常现象"}}
    e = build()
    handle._handle(e, rec("MaaEnd", at(9, 5), ok=True, raw=dict(GIFT)))
    title = texts.unverified_alarm("终末地", "早班", 1)
    check("终末地 1 项没证据：进群", alarms(e), [title])
    check("标题走群", route_of(title, alert=True), "group")
    check("头一行写出哪一项、为什么不算、证据包", last_body(e).splitlines()[0],
          "终末地早班：赠送干员礼物 程序说做完了，但游戏里拿不出证据（日志里没有游戏回显），"
          f"不算完成，已交给我们这边去查（证据包 {PAGE}）")
    handle._handle(e, rec("MaaEnd", at(9, 40), ok=True, raw=dict(GIFT)))
    check("同一天同样这几项又没证据：这一趟也进群（D210，audit 11-08 C-01）", alarms(e), [title, title])
    e = build()
    # The desktop picture is taken 5-8 s after the task ended and shows the next task
    # (task_shots.py, verify ledger #28): booked now, it backs nothing. What backs these
    # four is MaaFW's own steps (test_mc28.py), and here there is no MaaFW log.
    handle._handle(e, rec("MaaEnd", at(9, 5), ok=True, raw=dict(GIFT, tasks_shot=["赠送干员礼物"])))
    check("只有一张任务结束截图不算证据：照推", alarms(e), [title])
    e = build()
    handle._handle(e, rec("MaaEnd", at(9, 5), failed=["基建任务"], raw=dict(GIFT)))
    handle._handle(e, rec("MaaEnd", at(9, 40), ok=True,
                          raw={"tasks_done": ["赠送干员礼物"], "tasks_evidence": {"赠送干员礼物": "获得 物品"}}))
    e._flush_pending()
    check("前一趟有失败、重试那趟补上了：仅推中途失败重试通过，不误报没证据",
          alarms(e), [texts.self_healed("MaaEnd")])
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), ok=True, raw={"annihilation": "Annihilation"}))
    check("明日方舟剿灭没有进度行：进群", alarms(e), [texts.unverified_alarm("明日方舟", "早班", 1)])
    check("写出剿灭和原因", "剿灭 程序说做完了" in last_body(e) and "剿灭模式 x/y" in last_body(e), True)
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), ok=True, raw={"annihilation": "Annihilation", "maa_sanity_short": True}))
    check("理智不够没打剿灭是正常状态：不推", alarms(e), [])
    real_short = outcome.maa_sanity_short
    outcome.maa_sanity_short = lambda text: {"have": 20, "cost": 25}
    try:
        e = build()
        r = rec("MAA", at(9, 3), ok=True, raw={"annihilation": "Annihilation"})
        handle._handle(e, r)
        check("剿灭记成功、其实理智不够：报理智不够，不报没证据", alarms(e), [texts.MAA_SANITY_SHORT])
        check("…写着两个数、写明 AUTO-MAS 记成了成功",
              "理智 20" in last_body(e) and "剿灭一次要 25" in last_body(e) and "记成成功" in last_body(e), True)
        check("…记在这一趟上", r.raw.get("maa_sanity_short"), {"have": 20, "cost": 25})
        handle._handle(e, rec("MAA", at(9, 3), ok=True, raw={"annihilation": "Annihilation"}))   # replayed
        check("…同一条记录不推两次", len(alarms(e)), 1)
        e = build()
        handle._handle(e, rec("MAA", at(9, 3), ok=True,
                              raw={"annihilation": "Annihilation", "annihilation_progress": [400, 400]}))
        check("有进度行的剿灭不去读理智：不推", alarms(e), [])
        e = build()
        handle._handle(e, rec("MAA", at(9, 3), ok=True, raw={}))
        check("不是剿灭那一趟：不读", alarms(e), [])
    finally:
        outcome.maa_sanity_short = real_short
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), ok=True,
                          raw={"annihilation": "Annihilation", "annihilation_progress": "400/400"}))
    check("剿灭有进度行：不推", alarms(e), [])
    e = build()
    handle._handle(e, rec("OK-WW", at(9, 5), ok=True, raw={"okww_steps": ["周常乐园（没读到做完，不算完成）"]}))
    check("鸣潮一步没读到做完：进群", alarms(e), [texts.unverified_alarm("鸣潮", "早班", 1)])

    print("\n[send 自己拼去重的键：一种报警 + 一条记录（2026-10-06 之前调用方拼好了递进来，看不出是不是一条记录）]")
    e = build()
    check("键是「种类|记录号」，和 state.json 里旧的标记一样", unresolved.alert_key(rec("MAA", at(9, 5))),
          f"未解决|{rec('MAA', at(9, 5)).run_id}")
    check("推出去了", unresolved.send(e, D, "手动", "rid-1", "t1", "b1"), True)
    check("记的是「手动|rid-1」", e._already_alerted(D, "手动|rid-1"), True)
    check("同一条记录再来一遍：不重推，算推过", (unresolved.send(e, D, "手动", "rid-1", "t1", "b1"), len(alarms(e))), (True, 1))
    check("另一条记录：照推", (unresolved.send(e, D, "手动", "rid-2", "t2", "b2"), len(alarms(e))), (True, 2))
    check("同一条记录的另一种报警：照推", (unresolved.send(e, D, "重启", "rid-1", "t3", "b3"), len(alarms(e))), (True, 3))

    print("\n[补跑被红按钮（停一切）停掉：不说「补跑也没成」，AUTO-MAS 的「任务被用户手动停止」不当卡点（11-05 13:19）]")
    DAYS = f"{DAY:%Y-%m-%d}"
    for label, mk_raw in (("停一切时段当时还没补上（13:19 原样，只有 AUTO-MAS 那句话）", {}),
                          ("停一切时段已经标上", {"manual_stop": "10:20"})):
        e = build()
        handle._handle(e, rec("MAA", at(9, 5), failed=["开始唤醒"]))
        e._flush_pending()
        makeup.maybe_run(e, at(10, 5))
        e._flush_pending()
        handle._handle(e, rec("MAA", at(10, 6), failed=["任务被用户手动停止"], raw=mk_raw))
        e._flush_pending()
        m_ent = makeup.read_marker(e.cfg.state_dir, DAYS).get("MAA") or {}
        check(label + "：补跑记成被停掉", (m_ent.get("result"), m_ent.get("note")), (makeup.FAILED, makeup.STOPPED_NOTE))
        heads = [b.splitlines()[0] for t, b, a in e.notifier.sent if a]
        check(label + "：没有「补跑也没成」", any("补跑也没成" in h for h in heads), False)
        check(label + "：没有把「任务被用户手动停止」当卡点", any("卡在 " + texts.AUTOMAS_MANUAL_STOP in h for h in heads), False)
        if not mk_raw:
            check(label + "：一条进群，头一行说补跑被红按钮停掉", heads,
                  [f"明日方舟早班没跑成，{texts.MAKEUP_STOPPED_PHRASE}（证据包 {PAGE}）"])
    check("没被停掉、自己失败的补跑照旧说「补跑也没成」", makeup.STOPPED_NOTE != "开始唤醒", True)

    print("\n[整天报警没了]")
    check("dayfail.py 删了", (ROOT / "ark_relay" / "dayfail.py").exists(), False)
    src = (ROOT / "ark_relay" / "core" / "engine.py").read_text(encoding="utf-8")
    check("引擎每轮没有「全天没成」这一步", "全天没成" in src or "dayfail" in src, False)
    check("文案里没有「一整天一趟都没跑成」", any("一整天" in s for s in texts.samples()), False)

    _mc.CHECKS.update(_mc_real)


def _part_silent_green_guards():
    """前置条件不满足时，绝不许静默变成「全绿」。"""
    from datetime import datetime

    from ark_relay.features import outcome
    from ark_relay.features.handle import _maa_app_log, _okww_nest_expected

    def main():
        print("1) MAA 日志读不到 → 必须 None，不能是空串")
        check("没配目录", _maa_app_log(None, datetime.now()), None)
        check("目录不存在", _maa_app_log("/no/such/dir", datetime.now()), None)

        print("2) 空文本现在也拦得住了（两道防线，不是只靠一道）")
        # 第一版判据按错误字符串计数，空文本会全部判过 = 假全绿，全靠 _maa_app_log
        # 返回 None 兜着。换成任务链结构判定之后，空文本自己就会报
        # 「读到了这一轮的任务链事件：否」。两道都留着：判据自己站得住，
        # 上游读不到时也照样说得出「无从核对」。
        check("空文本会被判据自己拦下",
              outcome.summarize(outcome.maa_checks(""), "MAA") is not None, True)

        print("3) OK-WW 配置读不到 → 必须 None，不能是 False")
        check("没配 automas_dir", _okww_nest_expected(None), None)
        check("目录不存在", _okww_nest_expected("/no/such/dir"), None)

        print("4) 读不到配置时，残象聚落不许悄悄消失")
        # 直接验判据本身：expect_nest=False 时确实没有这一项，
        # 所以 engine 必须自己补一条「读不到配置」，否则整项蒸发。
        got = outcome.okww_checks("Daily Task Completed", expect_nest=False)
        check("expect_nest=False 时残象聚落这一项确实不存在（故必须另行补报）",
              any("残象" in c.label for c in got), False)

        print("5) 补报的那一条必须是「没干成」，会被 summarize 报出去")
        checks = outcome.okww_checks("Daily Task Completed", expect_nest=False)
        checks.append(outcome.Check("能读到 OK-WW 生效中的配置", False, "读不到"))
        check("summarize 会把它报出来", outcome.summarize(checks, "OK-WW") is not None,
              True)

        return 0 if not fails else 1

    raise SystemExit(main())


def _part_alertlog_main():
    """Every group alarm is also kept in COS alerts/<Beijing YYYYMMDD>.jsonl, one JSON line each.
    """
    import io
    import json
    import logging
    import os
    import time
    import urllib.error
    import urllib.request
    from datetime import datetime, timezone

    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                      COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="")
    # The Mac is in Tokyo; the copy must not care. time.tzset() exists on Unix only
    # ("Availability: Unix", docs.python.org/3/library/time.html#time.tzset), so on
    # Windows the zone stays the machine's own - UTC on the GitHub runner, which is
    # not +8 either, so "computed from UTC, whatever the machine's zone" is still
    # what the checks below exercise there (test_banners.py guards it the same way).
    if hasattr(time, "tzset"):
        os.environ.update(TZ="Asia/Tokyo")
        time.tzset()
    from ark_relay.features import errwatch as alertlog
    from ark_relay.features import phone
    from ark_relay.core import texts
    from ark_relay.core.config import Config
    from ark_relay.core.notify import Notifier
    from ark_relay.core.statestore import StateStore

    class FakeCos:
        """put/get the way alertlog.for_config wires phone.cos_put / cos_get."""

        def __init__(self):
            self.objects = {}
            self.puts = []
            self.put_fail = ""
            self.get_fail = ""
            self.delay = 0.0

        def put(self, key, data):
            time.sleep(self.delay)
            self.puts.append(key)
            if self.put_fail:
                return self.put_fail
            self.objects[key] = data
            return None

        def get(self, key):
            if self.get_fail:
                return None, self.get_fail
            return self.objects.get(key), ""

    def lines(cos, key):
        return [json.loads(x) for x in cos.objects.get(key, b"").decode("utf-8").splitlines()]

    def wait_puts(cos, n, secs=3.0):
        t0 = time.monotonic()
        while len(cos.puts) < n and time.monotonic() - t0 < secs:
            time.sleep(0.02)
        time.sleep(0.05)

    WW_BODY = ("OK-WW 2026-10-05/wuwa/OK-WW-05-39-25 有项目没干成：\n"
               "· 周本领到了奖励：周本打了，但没有领奖那一步：奖励没拿到\n"
               "干成的：每日任务跑完、刷体力")
    END_BODY = texts.unresolved_head("终末地", "早班", "补跑也没成", "基质刷取",
                                     "https://ark-1250000000.cos.ap-shanghai.myqcloud.com/"
                                     "2026-10-05_endfield_MaaEnd-07-30-14/MaaEnd.zip")

    print("[一行正好七个字段；ts 是北京时间，从 UTC 算，机器在东京也一样]")
    at = datetime(2026, 10, 5, 14, 39, 0, tzinfo=timezone.utc)          # Beijing 22:39, Tokyo 23:39
    r = alertlog.row(texts.ROUND_INCOMPLETE, WW_BODY, "20261005153900", now=at)
    check("字段", list(r), ["ts", "game", "title", "text", "version", "evidence_run", "channel"])
    check("北京时间", r["ts"], "2026-10-05 22:39:00")
    check("鸣潮认得出", r["game"], "鸣潮")
    check("运行编号", r["evidence_run"], "2026-10-05/wuwa/OK-WW-05-39-25")
    check("正文原样（含换行）", r["text"], WW_BODY)
    check("版本", r["version"], "20261005153900")
    now_bj = datetime.now(timezone.utc).timestamp() + 8 * 3600
    got = datetime.strptime(alertlog.row("x", "y")["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    check("不传时间：用当前 UTC + 8 小时（不是东京钟）", abs(got - now_bj) < 3)

    def _raises(f):
        try:
            f()
        except ValueError:
            return True
        return False

    check("裸时间（不知道时区）不收", _raises(lambda: alertlog.beijing(datetime(2026, 10, 5, 12, 0))))
    r2 = alertlog.row(texts.RELAY_ERROR, texts.relay_error_body("ark.report", "日报没发出去", "21:21"), "", now=at)
    check("中继自己的报错：游戏、运行编号、版本都空", (r2["game"], r2["evidence_run"], r2["version"]), ("", "", ""))
    r3 = alertlog.row(texts.unresolved("终末地", "早班"), END_BODY, "v", now=at)
    check("终末地认得出", r3["game"], "终末地")
    check("证据链接里的运行编号也认得出", r3["evidence_run"], "2026-10-05/endfield/MaaEnd-07-30-14")
    check("MAA 失败认成明日方舟", alertlog.row(texts.failed("MAA"), "", now=at)["game"], "明日方舟")
    check("MaaEnd 不会被认成明日方舟", alertlog.row(texts.failed("MaaEnd"), "", now=at)["game"], "终末地")
    check("标题没说、正文提到两个游戏：空", alertlog.row("早班 没有运行", "明日方舟 和 鸣潮 都没跑", now=at)["game"], "")
    check("东京 00:30 = 北京前一天 23:30：放前一天的对象",
          alertlog.row("x", "", now=datetime(2026, 10, 5, 15, 30, tzinfo=timezone.utc))["ts"][:10], "2026-10-05")
    check("对象名", alertlog.key_for("20261005"), "alerts/20261005.jsonl")

    TODAY_BJ = alertlog.beijing()
    AT_TODAY = TODAY_BJ.replace(hour=22, minute=39, second=0, microsecond=0)
    DAY_TODAY = AT_TODAY.strftime("%Y%m%d")
    KEY_TODAY = alertlog.key_for(DAY_TODAY)

    print("\n[本地先记一行，再把整天的文件 PUT 上去；第二条追加在后面]")
    cos = FakeCos()
    al = alertlog.AlertLog(TMP / "s1", put=cos.put, get=cos.get)
    al.copy(texts.ROUND_INCOMPLETE, WW_BODY, "1", now=AT_TODAY).join(3)
    al.copy(texts.unresolved("终末地", "早班"), END_BODY, "1", now=AT_TODAY).join(3)
    got = lines(cos, KEY_TODAY)
    check("两行都在、顺序对", [x["title"] for x in got], [texts.ROUND_INCOMPLETE, texts.unresolved("终末地", "早班")])
    check("每行都是 FIELDS 那几个字段", all(list(x) == list(alertlog.FIELDS) for x in got))
    check("本地也有这一天", (TMP / "s1" / "alerts" / f"{DAY_TODAY}.jsonl").exists())

    print("\n[COS 写不进：行留在本地、只记一条 WARNING；下一条报警把前面的一起补上]")
    records = []

    class _Grab(logging.Handler):
        def emit(self, record):
            records.append(record)

    grab = _Grab()
    alertlog._log_alertlog.addHandler(grab)
    alertlog._log_alertlog.setLevel(logging.INFO)
    cos = FakeCos()
    cos.put_fail = "回 503"
    al = alertlog.AlertLog(TMP / "s2", put=cos.put, get=cos.get)
    al.copy("⚠️ 一", "a", now=AT_TODAY).join(3)
    al.copy("⚠️ 二", "b", now=AT_TODAY).join(3)
    check("COS 上还没有", cos.objects, {})
    check("只记了一条 WARNING（不是每条报警一条）", [x.levelname for x in records], ["WARNING"])
    cos.put_fail = ""
    al.copy("⚠️ 三", "c", now=AT_TODAY).join(3)
    check("三条一起上去了", [x["title"] for x in lines(cos, KEY_TODAY)], ["⚠️ 一", "⚠️ 二", "⚠️ 三"])
    check("恢复时记一条 INFO", records[-1].levelname, "INFO")
    al2 = alertlog.AlertLog(TMP / "s2", put=cos.put, get=cos.get)
    n_puts = len(cos.puts)
    al2.sync()
    check("都上去了以后，开机补传什么都不做", len(cos.puts), n_puts)
    alertlog._log_alertlog.removeHandler(grab)

    print("\n[本地没有这一天（状态目录被清过）：先读回 COS 上的，读不回来就不写，免得盖掉]")
    cos = FakeCos()
    cos.objects[KEY_TODAY] = (json.dumps(alertlog.row("⚠️ 早上的", "", now=AT_TODAY), ensure_ascii=False)
                              + "\n").encode("utf-8")
    cos.get_fail = "timed out"
    al = alertlog.AlertLog(TMP / "s3", put=cos.put, get=cos.get)
    al.copy("⚠️ 晚上的", "", now=AT_TODAY).join(3)
    check("读不回来：没有 PUT", cos.puts, [])
    cos.get_fail = ""
    al.sync()
    check("读回来以后：早上的在前，晚上的在后", [x["title"] for x in lines(cos, KEY_TODAY)],
          ["⚠️ 早上的", "⚠️ 晚上的"])

    print("\n[Notifier：送到群的报警才抄；日报、普通信息、只记日志的、没送到的都不抄；COS 慢不拖推送]")
    cfg = Config()
    cfg.state_dir = TMP / "n1"
    StateStore(cfg.state_dir).set("versions", "code", "20261005153900")
    n = Notifier(cfg)
    n._fan_out = lambda title, body, **kw: (["企业微信机器人"], {})
    fake = FakeCos()
    fake.delay = 0.8
    n._alerts = alertlog.AlertLog(cfg.state_dir, put=fake.put, get=fake.get)
    t0 = time.monotonic()
    check("报警送达", n.send(texts.ROUND_INCOMPLETE, WW_BODY, alert=True), [])
    check("COS 慢 0.8 秒，推送不等它", time.monotonic() - t0 < 0.5)
    n.send("📋 10-05 · 全绿 ✅", "正文", daily=True)
    n.send("🆕 游戏更新", "正文")
    n.send("🔄 中继已更新", "正文", alert=True)
    n.send_group("📣 明天开卡池", "正文")
    fake.delay = 0.0
    wait_puts(fake, 2)
    time.sleep(0.3)
    key = alertlog.key_for(alertlog.beijing().strftime("%Y%m%d"))
    got = lines(fake, key)
    check("群报警和 send_group 抄了，日报、普通信息、只记日志的没抄", [x["title"] for x in got],
          [texts.ROUND_INCOMPLETE, "📣 明天开卡池"])
    check("版本是这台机器正在跑的代码版本", got and got[0]["version"], "20261005153900")
    n._fan_out = lambda title, body, **kw: ([], {"企业微信机器人": "60020"})
    n.send("❌ OK-WW 失败", "没送到", alert=True)
    time.sleep(0.3)
    check("没送到的报警不抄（调用方每轮重发，抄了就是一串重复）",
          [x["title"] for x in lines(fake, key)][-1], "📣 明天开卡池")

    print("\n[这台机器没配 COS：照常送达，只在本地记]")
    cfg2 = Config()
    cfg2.state_dir = TMP / "n2"
    n2 = Notifier(cfg2)
    n2._fan_out = lambda title, body, **kw: (["企业微信机器人"], {})
    check("照常送达", n2.send(texts.RELAY_ERROR, "x", alert=True), [])
    check("没有上传器", n2.alert_log()._put, None)
    check("本地有一行", len(list((TMP / "n2" / "alerts").glob("*.jsonl"))), 1)

    print("\n[真的 PUT：私有（不带 public-read），404 当成还没有]")

    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append((req.get_method(), req.full_url, {k.lower(): v for k, v in req.header_items()}))
        if req.get_method() == "GET":
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return _Resp(b"")

    class _Cos:
        host = "bucket.cos.ap-shanghai.myqcloud.com"

        def authorization(self, method, key, now=None, ttl=3600):
            return f"sig-{method}-{key}"

    real = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        check("404：没有这个对象，不算出错", phone.cos_get(_Cos(), "alerts/20261006.jsonl", 5), (None, ""))
        check("私有 PUT 成功", phone.cos_put(_Cos(), "alerts/20261006.jsonl", b"{}\n", 5, public=False,
                                        content_type="application/x-ndjson; charset=utf-8"), None)
        check("不带 x-cos-acl", "x-cos-acl" in seen[-1][2], False)
        check("带签名", seen[-1][2].get("authorization"), "sig-PUT-alerts/20261006.jsonl")
        phone.cos_put(_Cos(), "state/x.json", b"{}", 5)
        check("手机状态照旧 public-read", seen[-1][2].get("x-cos-acl"), "public-read")
    finally:
        urllib.request.urlopen = real

    print()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)


def _part_alertlog_channel():
    """The alarm copy (alertlog row) names the channel that actually delivered it."""
    import json
    import os
    import threading

    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                      COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="",
                      ARK_ALERT_PUSH_URL="")
    from ark_relay.core.config import Config
    from ark_relay.core.notify import Notifier
    from ark_relay.features import errwatch as alertlog
    from ark_relay.features import machinecheck as mc

    FIX = fx_dir(Path(__file__), "fixtures") / "alerts-20261013-old-row.jsonl"

    class Fake:
        def __init__(self, name, broken=False):
            self.name, self.broken, self.enabled = name, broken, True

        def send_text(self, *a):
            if self.broken:
                raise RuntimeError(f"{self.name} down")

    class Pushes:
        """Stands in for macpush: keeps the rows instead of POSTing them."""

        def __init__(self):
            self.rows = []

        def push(self, row):
            self.rows.append(row)

    def build(name, broken=()):
        cfg = Config()
        cfg.state_dir = TMP / name
        n = Notifier(cfg)
        n.serverchan = Fake("Server酱", "Server酱" in broken)
        n.wecom_bot = Fake("企业微信机器人", "企业微信机器人" in broken)
        n.wecom = Fake("企业微信", "企业微信" in broken)
        n._alerts = alertlog.AlertLog(cfg.state_dir)       # local only, no COS
        n._mac = Pushes()
        return n

    def rows(n):
        day = alertlog.beijing().strftime("%Y%m%d")
        return mc.alert_rows(n._cfg.state_dir, day)

    print("[group robot takes the alarm: channel 企业微信机器人]")
    n = build("ok")
    check("delivered", n.send("⚠️ 出错了", "正文", alert=True), [])
    got = rows(n)
    check("one row", len(got), 1)
    check("channel", got and got[0].get("channel"), "企业微信机器人")
    check("the Mac gets the same row", n._mac.rows, got)

    print("\n[group robot refuses, Server酱 takes it: channel Server酱]")
    n = build("fallback", broken=("企业微信机器人",))
    n._announcing = True          # no outage notice in this case
    check("delivered", n.send("⚠️ 出错了", "正文", alert=True), [])
    got = rows(n)
    check("channel is the fallback", [r.get("channel") for r in got], ["Server酱"])

    print("\n[with the outage notice: each row names its own channel]")
    n = build("outage", broken=("企业微信机器人",))
    n.send("⚠️ 出错了", "正文", alert=True)
    got = rows(n)
    check("alarm and notice copied", [r["title"].startswith(("⚠️ 出错了", "🔌")) for r in got], [True, True])
    check("both went by Server酱", [r.get("channel") for r in got], ["Server酱", "Server酱"])

    print("\n[send_group: 企业微信机器人]")
    n = build("group")
    n.send_group("📣 明天开卡池", "正文")
    check("channel", [r.get("channel") for r in rows(n)], ["企业微信机器人"])

    print("\n[unknown channel: empty]")
    check("row() default", alertlog.row("t", "x").get("channel"), "")
    check("FIELDS ends with channel", alertlog.FIELDS[-1], "channel")

    print("\n[a day file with a pre-channel machine row still reads and merges]")
    old = FIX.read_bytes()
    check("fixture row has no channel field", "channel" in json.loads(old), False)

    class Cos:
        def __init__(self):
            self.objects = {}

        def put(self, key, data):
            self.objects[key] = data

        def get(self, key):
            return self.objects.get(key), ""

    cos = Cos()
    day = alertlog.beijing().strftime("%Y%m%d")
    cos.objects[alertlog.key_for(day)] = old
    n = build("merge", broken=("企业微信机器人",))
    n._announcing = True
    n._alerts = alertlog.AlertLog(TMP / "merge", put=cos.put, get=cos.get)
    n.send("⚠️ 新的", "正文", alert=True)
    for th in threading.enumerate():
        if th.name == "alarm-copy":
            th.join(5)
    merged = [json.loads(x) for x in cos.objects[alertlog.key_for(day)].decode("utf-8").splitlines()]
    check("old row kept first, new row after", [r["title"] for r in merged], ["🖼️ 无音区产出", "⚠️ 新的"])
    check("old row reads as unknown channel", merged[0].get("channel", ""), "")
    check("new row has it", merged[1]["channel"], "Server酱")
    check("machinecheck reads both", len(mc.alert_rows(TMP / "merge", day)), 2)

    for th in threading.enumerate():
        if th.name in ("alarm-copy", "alarm-mac"):
            th.join(5)


def _part_alertlog_no_lock_on_cos():
    """alertlog: no lock held across a COS call; a failure first met on the push path
does not silence the next one.
    """
    import logging
    import threading


    from ark_relay.features import errwatch as alertlog, errwatch


    print("[a slow PUT does not hold record() up, and what it records is not lost]")
    cos: dict[str, bytes] = {}
    in_put, release = threading.Event(), threading.Event()


    def slow_put(key, data):
        in_put.set()
        release.wait(5)
        cos[key] = data
        return None


    al = alertlog.AlertLog(tmpdir(), put=slow_put, get=lambda key: (None, ""))
    al.record("❌ MAA 失败", "第一条")
    syncer = threading.Thread(target=al.sync, daemon=True)
    syncer.start()
    in_put.wait(5)
    rec = threading.Thread(target=al.record, args=("❌ MaaEnd 失败", "第二条"), daemon=True)
    rec.start()
    rec.join(1)
    check("record() returns while the PUT is still out", rec.is_alive(), False)
    release.set()
    syncer.join(5)
    rec.join(5)
    in_put.clear()
    release.set()
    al.sync()
    lines = b"".join(cos.values()).decode("utf-8")
    check("both lines reach COS", ("第一条" in lines, "第二条" in lines), (True, True))


    print("\n[a failure first met on the push path does not silence the next one]")


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, r):
            self.lines.append((r.threadName, r.getMessage()))


    grab = Grab()
    logging.getLogger(alertlog._log_alertlog.name).addHandler(grab)
    al = alertlog.AlertLog(tmpdir(), put=lambda key, data: "COS 503", get=lambda key: (None, ""))
    al.record("❌ MAA 失败", "x")
    t = threading.Thread(target=al.sync, name=f"{errwatch.PUSH_THREAD}-copy")
    t.start()
    t.join(5)
    al.sync()          # on this (non-push) thread: errwatch would take this WARNING
    logging.getLogger(alertlog._log_alertlog.name).removeHandler(grab)
    said = [n for n, m in grab.lines if "COS 没成" in m]
    check("the failure is said off the push path too", said, [f"{errwatch.PUSH_THREAD}-copy", "MainThread"])


def _part_macpush():  # noqa: C901
    import json
    import os
    import socket
    import sys
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _parts import tmpdir

    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                      COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="")
    from ark_relay.features import errwatch as alertlog, macpush
    from ark_relay.core import texts
    from ark_relay.core.config import Config
    from ark_relay.core.notify import Notifier
    from ark_relay.core.statestore import StateStore

    class Mac:
        """A stand-in for the Mac's listener: keeps every body it was POSTed."""

        def __init__(self):
            self.got, self.paths, self.types = [], [], []
            self.status = 200
            self.delay = 0.0
            # hold: the handler stops after reading the request until `release` is set (2 s at most);
            # `entered` says the request arrived. For "push did not wait for the POST" without a stopwatch.
            self.hold = False
            self.entered, self.release = threading.Event(), threading.Event()
            mac = self

            class H(BaseHTTPRequestHandler):
                def do_POST(self):
                    n = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(n)
                    mac.entered.set()
                    if mac.hold:
                        mac.release.wait(2.0)
                    if mac.delay:
                        time.sleep(mac.delay)
                    if mac.status == 200:
                        mac.got.append(json.loads(body.decode("utf-8")))
                        mac.paths.append(self.path)
                        mac.types.append(self.headers.get("Content-Type"))
                    self.send_response(mac.status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

                def log_message(self, *a):
                    pass

            self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
            self.srv.daemon_threads = True
            threading.Thread(target=self.srv.serve_forever, daemon=True).start()
            self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/alert"

        def titles(self):
            return [x.get("title") for x in self.got]

    def closed_port_url():
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return f"http://127.0.0.1:{port}/alert"

    def join(t):
        if t is not None:
            t.join(10)

    class FakeCos:
        def __init__(self):
            self.puts = []

        def put(self, key, data):
            self.puts.append((key, data))
            return None

        def get(self, key):
            return None, ""

    def notifier(name, url):
        cfg = Config()
        cfg.state_dir = TMP / name
        cfg.alert_push_url = url
        StateStore(cfg.state_dir).set("versions", "code", "20261011190000")
        n = Notifier(cfg)
        n._fan_out = lambda title, body, **kw: (["企业微信机器人"], {})
        cos = FakeCos()
        n._alerts = alertlog.AlertLog(cfg.state_dir, put=cos.put, get=cos.get)
        return n, cos

    def last_threads(n):
        """Wait for the Mac push and the COS copy threads this notifier started."""
        for t in threading.enumerate():
            if t.name in ("alarm-mac", "alarm-copy"):
                t.join(10)

    print("\n[默认地址：Mac 的 Tailscale 地址、验收端口 8931；.env 可改；测试里一律关着]")
    saved = os.environ.pop("ARK_ALERT_PUSH_URL", None)
    check("默认地址", Config().alert_push_url, "http://100.110.87.36:8931/alert")
    os.environ["ARK_ALERT_PUSH_URL"] = "http://10.0.0.9:1/x"
    check(".env 覆盖", Config().alert_push_url, "http://10.0.0.9:1/x")
    os.environ["ARK_ALERT_PUSH_URL"] = saved if saved is not None else ""
    check("测试环境里默认关着（_tmp.py），测试报警不会发到真的 Mac", Config().alert_push_url, "")
    check("关着时不排队、不发", macpush.MacPush(TMP / "off", "").push({"title": "x"}), None)
    check("关着时没有队列文件", (TMP / "off" / macpush.QUEUE_FILE).exists(), False)

    print("\n[POST 成功：送的就是 COS 那一行，一字不差；送到就从队列里删]")
    mac = Mac()
    n, cos = notifier("ok", mac.url)
    check("群报警照常送达", n.send(texts.ROUND_INCOMPLETE, "鸣潮 OK-WW 这一轮没干完", alert=True), [])
    last_threads(n)
    check("Mac 收到一条", mac.titles(), [texts.ROUND_INCOMPLETE])
    check("路径 /alert", mac.paths, ["/alert"])
    check("Content-Type 是 JSON", mac.types, ["application/json; charset=utf-8"])
    cos_row = json.loads(cos.puts[-1][1].decode("utf-8").splitlines()[-1]) if cos.puts else {}
    check("字段正好是 COS 那几个", mac.got and tuple(mac.got[0]), alertlog.FIELDS)
    check("和 COS 那一行完全一样（同一个 ts）", mac.got and mac.got[0], cos_row)
    check("版本是本机代码版本", mac.got and mac.got[0]["version"], "20261011190000")
    check("送到后队列空了", n.mac_push().pending(), [])
    check("队列文件删掉了", (TMP / "ok" / macpush.QUEUE_FILE).exists(), False)
    n.send("📋 10-11 · 全绿 ✅", "正文", daily=True)
    n.send("🆕 游戏更新", "正文")
    n.send("🔄 中继已更新", "正文", alert=True)
    n.send_group("📣 明天开卡池", "正文")
    last_threads(n)
    check("日报、普通信息、只记日志的不送；send_group 送", mac.titles(),
          [texts.ROUND_INCOMPLETE, "📣 明天开卡池"])

    print("\n[POST 超时（3 秒上限，测试里缩短）：进队列，推送不等它]")
    gate = Mac()
    gate.hold = True
    mp0 = macpush.MacPush(TMP / "gate", gate.url, timeout=5.0)
    th0 = mp0.push(alertlog.row("⚠️ 卡住的", "a"))
    check("push 立刻返回（POST 在自己的线程里）", (th0 is not None and th0.is_alive(), gate.release.is_set()), (True, False))
    check("请求已经发到假 Mac（它还没回话）", gate.entered.wait(5.0))
    gate.release.set()
    join(th0)
    check("放行后送到，队列空", (gate.titles(), mp0.pending()), (["⚠️ 卡住的"], []))
    slow = Mac()
    slow.delay = 1.0
    mp = macpush.MacPush(TMP / "slow", slow.url, timeout=0.3)
    th = mp.push(alertlog.row("⚠️ 慢的", "a"))
    join(th)
    check("超时的留在队列里", [x["title"] for x in mp.pending()], ["⚠️ 慢的"])
    check("落了盘", json.loads((TMP / "slow" / macpush.QUEUE_FILE).read_text("utf-8"))[0]["title"], "⚠️ 慢的")
    check("超时上限默认 3 秒", macpush.TIMEOUT, 3.0)

    print("\n[Mac 没人听（积极拒绝）：进队列；下一条报警时先补旧的再发新的，按先后]")
    down = closed_port_url()
    mp = macpush.MacPush(TMP / "later", down)
    join(mp.push(alertlog.row("⚠️ 一", "a")))
    join(mp.push(alertlog.row("⚠️ 二", "b")))
    check("两条都留着", [x["title"] for x in mp.pending()], ["⚠️ 一", "⚠️ 二"])
    mac2 = Mac()
    mp.url = mac2.url                      # the Mac's listener is up again
    join(mp.push(alertlog.row("⚠️ 三", "c")))
    check("下一条报警时三条按先后送到", mac2.titles(), ["⚠️ 一", "⚠️ 二", "⚠️ 三"])
    check("全送到后队列空了", mp.pending(), [])

    print("\n[开机补发：新进程读回盘上的队列，开机那一下全送出去；送到才删]")
    mp = macpush.MacPush(TMP / "boot", down)
    join(mp.push(alertlog.row("⚠️ 关机前没送到", "x")))
    check("关机前没送到的在盘上", (TMP / "boot" / macpush.QUEUE_FILE).exists())
    mac3 = Mac()
    cfg = Config()
    cfg.state_dir = TMP / "boot"
    cfg.alert_push_url = mac3.url
    fresh = Notifier(cfg)                  # the process after the reboot
    check("新进程读回了队列", [x["title"] for x in fresh.mac_push().pending()], ["⚠️ 关机前没送到"])
    join(fresh.mac_push().flush_async())   # what boot_stages.py does at start
    check("开机补发送到了", mac3.titles(), ["⚠️ 关机前没送到"])
    check("送到后才删", (TMP / "boot" / macpush.QUEUE_FILE).exists(), False)
    src = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("boot_stages.py 开机时调了补发", "notifier.mac_push().flush_async()" in src)

    print("\n[Mac 拒收（4xx）：丢掉，不卡住后面的；5xx 留着]")
    picky = Mac()
    picky.status = 400
    mp = macpush.MacPush(TMP / "picky", picky.url)
    join(mp.push(alertlog.row("⚠️ 拒收的", "x")))
    check("4xx 丢掉", mp.pending(), [])
    picky.status = 503
    join(mp.push(alertlog.row("⚠️ 忙", "x")))
    check("5xx 留着", [x["title"] for x in mp.pending()], ["⚠️ 忙"])
    picky.status = 429
    join(mp.flush_async())
    check("429 也留着", len(mp.pending()), 1)

    print("\n[POST 失败不影响群报警，也不影响 COS 那份；不出 WARNING（WARNING 会进群）]")
    import logging
    seen = []

    class Grab(logging.Handler):
        def emit(self, record):
            seen.append(record)

    grab = Grab(level=logging.DEBUG)
    logging.getLogger("ark.test_alarm").parent.addHandler(grab)
    logging.getLogger("ark.test_alarm").parent.setLevel(logging.DEBUG)
    n, cos = notifier("down", down)
    check("Mac 连不上，群报警照常送达", n.send(texts.RELAY_ERROR, "x", alert=True), [])
    last_threads(n)
    check("COS 那份照常写了", len(cos.puts), 1)
    check("没送到的留着", [x["title"] for x in n.mac_push().pending()], [texts.RELAY_ERROR])
    check("第二条报警时也照常送达", n.send(texts.RELAY_ERROR, "x2", alert=True), [])
    last_threads(n)
    check("两条都留着", len(n.mac_push().pending()), 2)
    mine = [r for r in seen if r.name == "ark.macpush"]
    check("Mac 没开是正常状态：只记 INFO，没有 WARNING", sorted({r.levelname for r in mine}), ["INFO"])
    check("连续两次不通只说一次", len(mine), 1)

    class Boom:
        def push(self, row):
            raise RuntimeError("boom")

    n._mac = Boom()
    seen.clear()
    check("直送 Mac 这段抛异常，群报警照常送达", n.send(texts.RELAY_ERROR, "y", alert=True), [])
    last_threads(n)
    check("COS 那份照常写了（抛异常时）", len(cos.puts), 3)
    check("真出错（代码坏了）才是 WARNING", [r.getMessage() for r in seen if r.levelno >= logging.WARNING],
          ["报警没能直送 Mac"])
    logging.getLogger("ark.test_alarm").parent.removeHandler(grab)

    print("\n[同时来几条：只有一个在发，后来的不丢]")
    mac4 = Mac()
    mac4.delay = 0.2
    mp = macpush.MacPush(TMP / "burst", mac4.url)
    ts = [mp.push(alertlog.row(f"⚠️ {i}", "")) for i in range(5)]
    for t in ts:
        join(t)
    check("五条都送到，按先后", mac4.titles(), [f"⚠️ {i}" for i in range(5)])
    check("队列空了", mp.pending(), [])

    print("\n[队列最多留 MAX_QUEUE 条（留新的）；坏掉的队列文件按空处理]")
    mp = macpush.MacPush(TMP / "cap", down)
    for i in range(macpush.MAX_QUEUE + 3):
        mp.add({"title": str(i)})
    check("留最新的 MAX_QUEUE 条", (len(mp.pending()), mp.pending()[0]["title"]),
          (macpush.MAX_QUEUE, "3"))
    (TMP / "bad").mkdir()
    (TMP / "bad" / macpush.QUEUE_FILE).write_text("{not json", encoding="utf-8")
    check("坏文件按空队列", macpush.MacPush(TMP / "bad", down).pending(), [])

    print()
    print("\n[audit 11-08 C-09: a corrupt queue file is kept aside and said at WARNING, not read as empty]")
    import logging as _logging
    _bad_dir = TMP / "corrupt"
    _bad_dir.mkdir()
    (_bad_dir / macpush.QUEUE_FILE).write_text("[{not json", encoding="utf-8")
    _seen = []

    class _H(_logging.Handler):
        def emit(self, r):
            _seen.append(r.levelno)

    _h = _H()
    macpush.log.addHandler(_h)
    _mp = macpush.MacPush(_bad_dir, "http://127.0.0.1:9/")
    macpush.log.removeHandler(_h)
    check("the queue reads as empty", _mp.pending(), [])
    check("one WARNING", _seen.count(_logging.WARNING), 1)
    check("the broken file is kept aside", len(list(_bad_dir.glob("*.corrupt-*"))), 1)

    print()
    print("\n[11-13: an alarm left queued is sent after the next phone push, not only with the next alarm]")

    class _Cfg:
        def __init__(self, d, url):
            self.state_dir, self.alert_push_url = d, url

    _got = []
    _cfg = _Cfg(TMP / "netok", "http://127.0.0.1:9/")
    check("for_config hands out one instance per queue", macpush.for_config(_cfg) is macpush.for_config(_Cfg(TMP / "netok", "http://127.0.0.1:9/")), True)
    check("another queue, another instance", macpush.for_config(_cfg) is macpush.for_config(_Cfg(TMP / "netok2", "http://127.0.0.1:9/")), False)
    check("nothing queued: no send", macpush.flush_after_network_ok(_cfg), None)
    _shared = macpush.for_config(_cfg)
    _shared._post = lambda row: (_got.append(row.get("title")), ("ok", ""))[1]
    _shared.add({"title": "08:22 queued"})
    _t = macpush.flush_after_network_ok(_cfg)
    if _t is not None:
        _t.join(5)
    check("queued row sent after the network came back", _got, ["08:22 queued"])
    check("queue empty after", _shared.pending(), [])
    check("switched off (no URL): nothing", macpush.flush_after_network_ok(_Cfg(TMP / "netoff", "")), None)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)


def _part_every_failure_pushed():
    import json
    import logging
    import os
    import sys
    import types
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _parts import tmpdir

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

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
                  "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi",
                  "pythoncom", "win32com", "win32com.client"):
        sys.modules.setdefault(_name, _Stub(_name))

    import boot_stages
    from ark_relay.features import gameupdate
    from ark_relay.features import handle
    from ark_relay.features import makeup
    from ark_relay.features import okww_overlay
    from ark_relay.features import preupdate
    from ark_relay.core import texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import route_of
    from ark_relay.features import errwatch

    errwatch.system_shutting_down = lambda: False

    def automas_dir(queues) -> Path:
        """An AUTO-MAS config dir: queues = [(name, [times], [script kinds])]."""
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
        for k, p in paths.items():
            sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
        qc = {"instances": []}
        for n, (name, times, kinds) in enumerate(queues):
            uid = f"q{n}"
            qc["instances"].append({"uid": uid})
            ts = {"instances": [], **{f"t{i}": {"Info": {"Enabled": True, "Time": t}} for i, t in enumerate(times)}}
            items = {"instances": [], **{f"i{i}": {"Info": {"ScriptId": f"s-{k}"}} for i, k in enumerate(kinds)}}
            qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                       "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root

    AUTOMAS = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
    DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    D = f"{DAY:%Y-%m-%d}"

    def at(hh, mm=0):
        return DAY.replace(hour=hh, minute=mm)

    class Src:
        def fetch(self, seen):
            return []

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = AUTOMAS
        cfg.maa_dir = None
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._maintenance_today = lambda game: False
        return e

    def rec(script, started, ok=False, failed=None, raw=None, transitional=False):
        user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
        return RunRecord(run_id=f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}", script=script, user=user,
                         started=started, finished=started + timedelta(minutes=20), ok=ok,
                         failed_tasks=list(failed if failed is not None else ([] if ok or transitional else ["日常"])),
                         raw=dict(raw or {}), transitional=transitional)

    def alarms(e):
        return [t for t, _, a in e.notifier.sent if a]

    handle._ship_evidence = lambda eng, r: ""
    handle._archive_okww_evidence = lambda eng, r: None
    handle._weekly_gates = lambda eng, r: None

    class Lines(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    LINES = Lines()
    for name in ("ark.handle", "ark.makeup", "ark.engine"):
        logging.getLogger(name).addHandler(LINES)
        logging.getLogger(name).setLevel(logging.DEBUG)

    print("[OK-WW overrides that did not bind: alert=True from both boot stages]")
    BAD = ["OK-WW 升级后，中继的改动有 1 处和新版对不上：NightmareNestTask.find_nest 这一处先按 OK-WW 新版跑，等我们重抄"]
    GOOD = ["中继给 OK-WW 的改动文件已装到 D:\\ark\\okww"]
    check("the title routes to the group", route_of(texts.patches(1, BAD), alert=True), "group")
    check("the healthy title stays log-only even with alert=True", route_of(texts.patches(1, GOOD), alert=True), "log")
    # okww_overlay.report_line() wording: a skipped override and a crashed override file are trouble too
    for line in ["OK-WW 有改动没贴上（上游源码和登记的不一致）：x（y）", "中继给 OK-WW 的改动文件自己报错了，改动一条都没生效：boom"]:
        check(f"report_line trouble routes to the group: {line[:12]}", route_of(texts.patches(1, [line]), alert=True), "group")

    LOG = boot_stages.log
    CFG = types.SimpleNamespace(automas_dir=None, maaend_dir=Path("maaend"), okww_dir=Path("okww"), state_dir=TMP)
    real = (okww_overlay.install, okww_overlay.write_master_pointer,
            okww_overlay.report_line, okww_overlay.drift_line, preupdate.run_okww)
    okww_overlay.install = lambda okww: ""
    okww_overlay.write_master_pointer = lambda automas_dir: ""
    okww_overlay.report_line = lambda *a, **k: ""
    okww_overlay.drift_line = lambda okww, state_dir: BAD[0]
    preupdate.run_okww = lambda okww, problems=None, **_k: ""
    notes = _Notes()
    boot_stages._stage_patch_okww(CFG, notes, LOG)
    check("boot: sent as an alarm", [(t, a) for t, _, a in notes.sent], [(texts.patches(1, BAD), True)])
    notes = _Notes()
    boot_stages._preupdate_okww(CFG, notes, LOG, [])
    check("pre-update: sent as an alarm", [(t, a) for t, _, a in notes.sent], [(texts.patches(1, BAD), True)])
    (okww_overlay.install, okww_overlay.write_master_pointer,
     okww_overlay.report_line, okww_overlay.drift_line, preupdate.run_okww) = real

    print("\n[the game update after the queue could not confirm: alert=True]")
    e = build()
    e.state.append_ledger(rec("OK-WW", datetime.now(tz=SERVER_TZ), ok=True))
    real_gu = (gameupdate.pending, gameupdate.run_deferred)
    gameupdate.pending = lambda state_dir: {"终末地": "今天 MaaEnd 进不了游戏"}
    gameupdate.run_deferred = lambda cfg, now, dispatch: ([], ["终末地：启动器没响应，没能确认有没有新版本"], [])
    e._maybe_deferred_update()
    e._gu_thread.join(10)
    gameupdate.pending, gameupdate.run_deferred = real_gu
    check("sent as an alarm", [(t, a) for t, _, a in e.notifier.sent], [(texts.unconfirmed("游戏更新", 1), True)])
    check("…the title routes to the group", route_of(texts.unconfirmed("游戏更新", 1), alert=True), "group")

    print("\n[a MAA failure that had fought gets no make-up: the log does not say 「只进日报」, the group hears it]")
    e = build()
    LINES.lines.clear()
    handle._handle(e, rec("MAA", at(9, 5), raw={"sanity_spent": 120}))
    e._flush_pending()
    makeup.maybe_run(e, at(10, 5))
    check("no make-up", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.GAVE_UP)
    check("the log line does not say 「只进日报」", any("只进日报" in ln for ln in LINES.lines), False)
    check("…it says the failure goes to the group", any("明日方舟这次不补" in ln and "进群" in ln for ln in LINES.lines))
    e._flush_pending()
    check("the failure reached the group", alarms(e), [texts.unresolved("明日方舟", "早班")])


def _part_recovered_daily_only():  # noqa: C901
    import json
    import logging
    import os
    import sys
    import urllib.error
    import urllib.request
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _parts import tmpdir

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.features import errwatch, handle
    from ark_relay.features import makeup
    from ark_relay.core import notify, texts
    from ark_relay.features import report
    from ark_relay.core import ledger as core
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.features import machinecheck as _mc
    _mc.load()
    _mc_real = dict(_mc.CHECKS)   # put back at the end: the coverage pass runs every test file in one process
    _mc.CHECKS.clear()   # the alarms themselves are tested here; the machine checks in tests/test_mc.py
    from ark_relay.core.ledger import State

    def automas_dir() -> Path:
        """AUTO-MAS's config with one 早班 09:00 queue running all three scripts."""
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths], **{f"s-{k}": {"Info": {"Name": k, "Path": p}}
                                                                for k, p in paths.items()}}
        qc = {"instances": [{"uid": "q0"}],
              "q0": {"Info": {"Name": "早班", "TimeEnabled": True},
                     "SubConfigsInfo": {"TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                        "QueueItem": {"instances": [], **{f"i{i}": {"Info": {"ScriptId": f"s-{k}"}}
                                                                          for i, k in enumerate(paths)}}}}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root

    AUTOMAS = automas_dir()
    # Today (real clock): makeup.eligible and _flush_pending read today's date.
    DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    D = f"{DAY:%Y-%m-%d}"
    UPDATE = "游戏更新成功，即将重启任务"

    def at(hh, mm=0):
        return DAY.replace(hour=hh, minute=mm)

    class Src:
        def fetch(self, seen):
            return []

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = AUTOMAS
        cfg.maa_dir = None
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._maintenance_today = lambda game: False
        return e

    def rec(script, started, ok=False, failed=None, raw=None, transitional=False):
        user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
        return RunRecord(run_id=f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}", script=script, user=user,
                         started=started, finished=started + timedelta(minutes=20), ok=ok,
                         failed_tasks=list(failed if failed is not None else ([] if ok or transitional else ["日常"])),
                         raw=dict(raw or {}), transitional=transitional)

    def restart(script, started):
        """An attempt AUTO-MAS recorded as a restart (collector._TRANSITIONAL)."""
        key = {"MAA": "maa_result", "MaaEnd": "maaend_result", "OK-WW": "general_result"}[script]
        return rec(script, started, raw={key: UPDATE if script == "OK-WW" else "未捕获到日志"}, transitional=True)

    def alarms(e):
        return [t for t, _, a in e.notifier.sent if a]

    def body_of(e, title):
        return next((b for t, b, a in e.notifier.sent if a and t == title), "")

    def daily(e):
        return core.format_daily(D, e.state.read_ledger(D))

    handle._ship_evidence = lambda eng, r: ""
    handle._archive_okww_evidence = lambda eng, r: None
    handle._weekly_gates = lambda eng, r: None
    makeup._dispatch = lambda script: (True, "已开跑")
    makeup._kill_game = lambda: None

    class Lines(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def said(self, *parts):
            return any(all(p in r.getMessage() for p in parts) for r in self.records)

    LINES = Lines()
    for _name in ("ark.handle", "ark.notify"):
        logging.getLogger(_name).addHandler(LINES)
        logging.getLogger(_name).setLevel(logging.DEBUG)

    print("[AUTO-MAS 自己重试过去了：中途失败立即直推企微群，绝不进日报]")
    e = build()
    handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
    handle._handle(e, rec("OK-WW", at(9, 40), ok=True, raw={"tasks_done": ["日常"]}))
    e._flush_pending()
    check("中途失败重试后通过立即直推群", alarms(e), [texts.self_healed("OK-WW")])
    check("放下了", (dict(e._pending), hasattr(e, "_recovered")), ({}, False))
    check("日志不再写只进日报", LINES.said(texts.self_healed("OK-WW"), "只进日报"), False)
    title, body = daily(e)
    check("日报不含失败/重试做成文案", ("重试里做成了" in body, "❌" in body), (False, False))
    check("日报标题中性不误标全绿，也不塞失败词", title, f"📋 {D[5:]} · 今日日报")
    print("  …没有后来那次成功：照样进群")
    e = build()
    handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
    e._flush_pending()
    check("最终失败进群", alarms(e), [texts.failed("OK-WW")])

    print("\n[中继补跑走通了：中途失败直推企微群，日报严格省略（细节仅记技术日志）]")
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), failed=["开始唤醒"]))
    e._flush_pending()
    makeup.maybe_run(e, at(10, 5))
    handle._handle(e, rec("MAA", at(10, 6), ok=True))
    e._flush_pending()
    check("补跑记成走通", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.OK)
    check("补跑走通立即直推群", alarms(e), [texts.makeup_passed("明日方舟", "早班")])
    check("放下了", dict(e._pending), {})
    check("日志不再写只进日报", LINES.said(texts.makeup_passed("明日方舟", "早班"), "只进日报"), False)
    check("日报 makeup_line 为空，细节仅在技术日志",
          (report.makeup_line(e.cfg.state_dir, D), report._makeup_tech_line(e.cfg.state_dir, D)),
          ("", "明日方舟失败后自动补跑，走通了（原来失败于：开始唤醒）"))
    check("日报正文不含补跑失败字样", "补跑里做成了" in daily(e)[1], False)
    print("  …补跑也没成：进群")
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), failed=["开始唤醒"]))
    e._flush_pending()
    makeup.maybe_run(e, at(10, 5))
    handle._handle(e, rec("MAA", at(10, 6), failed=["开始唤醒"]))
    e._flush_pending()
    check("没跑成进群", alarms(e), [texts.unresolved("明日方舟", "早班")])

    print("\n[更新那一串后面有一次成功：属正常更新重启闭环，仅记 INFO，不推群也不进日报]")
    e = build()
    handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
    handle._handle(e, restart("OK-WW", at(9, 18)))
    check("前面压着的失败还是它（重启不顶替它）", e._pending[("OK-WW", "wuwa")].started, at(9, 10))
    handle._handle(e, rec("OK-WW", at(9, 28), ok=True))
    e._flush_pending()
    check("正常更新重启闭环什么都不推", e.notifier.sent, [])
    check("日志记为更新/中途重启后重跑成功（INFO）", LINES.said("更新/中途重启后重跑成功"))
    title, body = daily(e)
    check("日报全绿且不塞更新重启 ↪️ 过渡行", ("全绿 ✅" in title, body.count("↪️ 鸣潮"), "不算失败" in body), (True, 0, False))
    print("  …那一串后面没有成功：照样进群，报的是前面那次失败")
    e = build()
    handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
    handle._handle(e, restart("OK-WW", at(9, 18)))
    e._flush_pending()
    check("最终失败进群", alarms(e), [texts.failed("OK-WW")])
    check("…说的是 09:10 那次的日常", "· 失败于：日常" in body_of(e, texts.failed("OK-WW")))

    print("\n[AUTO-MAS 记成重启的那一次：落地时不发，压着，后面那次定]")
    e = build()
    handle._handle(e, restart("OK-WW", at(9, 18)))
    check("落地时什么都没发", e.notifier.sent, [])
    check("压着", list(e._pending), [("OK-WW", "wuwa")])
    check("日志：先压着", LINES.said("是中途重启", "先压着"))
    handle._handle(e, rec("OK-WW", at(9, 28), ok=True))
    e._flush_pending()
    check("后面成功了：什么都没发", e.notifier.sent, [])
    check("放下了", dict(e._pending), {})
    check("日报不含 ↪️ 更新过渡行", ("↪️ 鸣潮" in daily(e)[1], "更新后重跑" in daily(e)[1]), (False, False))
    print("  …后面没有再跑：最终失败进群，写着 AUTO-MAS 记的什么")
    e = build()
    handle._handle(e, restart("OK-WW", at(9, 18)))
    e._flush_pending()
    check("最终失败进群", alarms(e), [texts.failed("OK-WW")])
    got = body_of(e, texts.failed("OK-WW"))
    check("…写着那次的时间和结果", f"09:18 开始的这一次，AUTO-MAS 记的结果是「{UPDATE}」" in got)
    check("…写着之后没有再跑出记录", "这次之后没有再跑出一次记录" in got)
    check("放下了", dict(e._pending), {})
    print("  …后面那次失败了：报的是后面那次")
    e = build()
    handle._handle(e, restart("OK-WW", at(9, 18)))
    handle._handle(e, rec("OK-WW", at(9, 20), failed=["周常乐园"]))
    e._flush_pending()
    check("一条最终失败进群", alarms(e), [texts.failed("OK-WW")])
    got = body_of(e, texts.failed("OK-WW"))
    check("…说的是 09:20 那次（周常乐园），不带重启那句", ("周常乐园" in got, "这次之后没有再跑出一次记录" in got), (True, False))
    print("  …重启那条比后面成功的那条晚落地：已经好了，不压着、不发")
    e = build()
    handle._handle(e, rec("OK-WW", at(9, 28), ok=True))
    handle._handle(e, restart("OK-WW", at(9, 18)))
    e._flush_pending()
    check("什么都没发", e.notifier.sent, [])
    check("不压着", dict(e._pending), {})
    check("日志：后面那次已经成功，不报也不进日报", LINES.said("是中途重启", "已经成功"))
    check("日报不含 ↪️", "↪️ 鸣潮" in daily(e)[1], False)
    print("  …终末地的空壳记录（未捕获到日志）也一样：落地不发，压着")
    e = build()
    handle._handle(e, restart("MaaEnd", at(10, 1)))
    check("落地时什么都没发", e.notifier.sent, [])
    check("压着", list(e._pending), [("MaaEnd", "endfield")])

    print("\n[推送传输：后一次送到了 → 一条标「自己好了」的 WARNING，只进日报；全没送到 → 照样报]")

    class Resp:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.data).encode("utf-8")

    def fake_urlopen(script):
        """urlopen that, for each URL in turn, raises (an Exception in `script`) or answers (a dict)."""
        calls = []

        def urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            calls.append(url)
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return Resp(step)
        urlopen.calls = calls
        return urlopen

    class Refuses:
        """errwatch's notifier: the group refuses, so whatever it queues stays queued."""
        def send_group(self, title, body):
            return ["企业微信机器人：拒收"]

        def send(self, title, body, **kw):
            return ["拒收"]

    def watch():
        sd = tmpdir()
        h = errwatch.ErrorKindAlert(Refuses(), state_dir=sd, known={}, retry=(3600.0,), fallback_after=1e9)
        logging.getLogger(errwatch.ARK).addHandler(h)
        LINES.records.clear()
        return h, sd

    def unwatch(h):
        logging.getLogger(errwatch.ARK).removeHandler(h)
        h.close()

    def warnings():
        return [r for r in LINES.records if r.levelno >= logging.WARNING]

    real_urlopen, real_sleep = urllib.request.urlopen, notify.time.sleep
    notify.time.sleep = lambda s: None
    REQ = urllib.request.Request("https://push.example/send", data=b"{}")
    try:
        h, sd = watch()
        urllib.request.urlopen = fake_urlopen([urllib.error.URLError("handshake timed out"), {"errcode": 0}])
        check("第二次送到了", notify._post(REQ), {"errcode": 0})
        check("失败的那一次是 INFO", [r.levelname for r in LINES.records if "推送传输失败（第 1/3 次）" in r.getMessage()],
              ["INFO"])
        check("瞬态重试送到记 INFO，不发 WARNING、不排进群队",
              (warnings(), h.pending(),
               any(r.levelname == "INFO" and "推送传输前 1 次没成，第 2 次送到了" in r.getMessage() for r in LINES.records)),
              ([], [], True))
        rows = errwatch.day_faults(sd, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
        check("不写进报错表", rows, [])
        unwatch(h)

        print("  …三次都没送到：_post 抛出去，调用方报 ERROR，errwatch 排进推群的队")
        h, sd = watch()
        urllib.request.urlopen = fake_urlopen([urllib.error.URLError("down")] * 3)
        try:
            notify._post(REQ)
            raised = False
        except urllib.error.URLError:
            raised = True
        check("抛出去了", raised)
        check("_post 自己没写「送到了」", any("送到了" in r.getMessage() for r in LINES.records), False)
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.wecom_bot_url = "https://bot.example/send"
        cfg.serverchan_key = ""
        cfg.wecom_corpid = ""
        n = notify.Notifier(cfg)
        urllib.request.urlopen = fake_urlopen([urllib.error.URLError("down")] * 3)
        check("一条渠道都没送到：返回错误", bool(n.send("❌ OK-WW 失败", "正文", alert=True)), True)
        check("…调用方记录 ERROR", [r.levelname for r in warnings()], ["ERROR"])
        check("…排进了推群的队", len(h.pending()), 1)
        unwatch(h)

        print("  …Server酱 第一个地址没送到、第二个送到了：真实入口异常直推群（不再标自己好了）")
        h, sd = watch()
        sc = notify.ServerChan(type("C", (), {"serverchan_key": "sctp123tabc"})())
        urllib.request.urlopen = fake_urlopen([urllib.error.URLError("down")] * 3 + [{"code": 0}])
        sc.send_text("📋 日报", "正文")
        check("两个地址都试了", len(urllib.request.urlopen.calls), 4)
        check("一条直推群的 WARNING",
              [r.getMessage().startswith("Server酱 前面的地址没送到") for r in warnings()], [True])
        check("排进推群队列", len(h.pending()), 1)
        unwatch(h)
    finally:
        urllib.request.urlopen, notify.time.sleep = real_urlopen, real_sleep

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    _mc.CHECKS.update(_mc_real)
    sys.exit(1 if fails else 0)


def _part_manual_stop_backfill():
    """Runs the red button cut short before the press was recorded get ⏹ at the next boot."""
    import json
    import os
    import types
    from datetime import datetime

    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.features import commands
    from ark_relay.features import handle
    from ark_relay.features import report
    handle._screenshot_to = lambda out: False   # the real one waits up to 10 s for a Windows screenshot file
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    # No network: the banner section and the report-writing model are stubbed, as in
    # test_daily.py.
    report.plan = types.SimpleNamespace(next_plan=lambda d: "", activity_countdown=lambda d: "",
                                        schedule=lambda d: [])
    report.banners = types.SimpleNamespace(
        collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
        read_image=None, state_dir=None: ([], {}),
        image_reader=lambda state_dir: None,
        render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
        Trace=types.SimpleNamespace(new=lambda: None),
        save_trace=lambda state_dir, now, text, tr: None,
        update_history=lambda state_dir, now: [],
        opening_tomorrow=lambda now, nxt: [],
    )
    report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []

        def send_group(self, title, body):
            return []

    class Src:
        def fetch(self, seen):
            return []

    def at(d, hh, mm, ss=0):
        return datetime(2026, 9, d, hh, mm, ss, tzinfo=SERVER_TZ)

    def line(rid, script, user, s, f, ok, failed=None):
        return {"run_id": rid, "script": script, "user": user, "started": s.isoformat(),
                "finished": f.isoformat(), "ok": ok, "failed_tasks": failed or [],
                "duration_known": True, "transitional": False, "raw": {"tasks_done": ["日常"]} if ok else {}}

    OKWW = line("OK-WW-05-40-56", "OK-WW", "wuwa", at(30, 9, 38), at(30, 9, 46, 58), True)
    MAAEND = line("MaaEnd-05-46-45", "MaaEnd", "endfield", at(30, 9, 46, 58), at(30, 9, 47, 10), False,
                  ["据点交易"])
    MAA = line("MAA-09-00-00", "MAA", "ark", at(30, 9, 0), at(30, 9, 30), True)
    TORN = '{"run_id": "half'

    def build(windows=None):
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.history_dir = None
        cfg.automas_dir = None
        st = State(cfg.state_dir)
        p = st.ledger_path("2026-09-30")
        p.write_text("\n".join([json.dumps(MAA, ensure_ascii=False), json.dumps(OKWW, ensure_ascii=False),
                                TORN, json.dumps(MAAEND, ensure_ascii=False)]) + "\n", encoding="utf-8")
        if windows is not None:
            (Path(cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).write_text(json.dumps(windows), encoding="utf-8")
        e = eng_mod.Engine(cfg, source=Src(), state=st, notifier=Notes())
        e._scripts_running = lambda: False
        return e

    def stops(e, day="2026-09-30"):
        return {x["run_id"]: (x.get("raw") or {}).get("manual_stop") for x in e.state.read_ledger(day)}

    def kind_line(body, script):
        return next((ln for ln in body.splitlines() if f" {script}" in ln and ln[:1] in "✅❌⏹↻⚠"), "")

    EVENING = at(30, 21, 25)

    print("[改前的日报：OK-WW 记为 ✅，未标手动停止的失败 MaaEnd 由白名单省略]")
    e = build(windows=[])
    _, body0 = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30"))
    check("OK-WW 原来是 ✅", kind_line(body0, "鸣潮")[:1], "✅")
    check("MaaEnd 失败行不进日报", kind_line(body0, "终末地"), "")

    print("\n[窗口文件里有这次按下：两趟补记，窗口外的不动，第二次是空操作]")
    e = build(windows=[{"start": "2026-09-30T09:46:28+08:00", "end": "2026-09-30T09:47:22+08:00"}])
    n = handle.backfill_manual_stops(e, EVENING)
    got = stops(e)
    check("补了两趟", n, 2)
    check("OK-WW 记停一切", got.get("OK-WW-05-40-56"), "09:46 停一切")
    check("MaaEnd 记停一切", got.get("MaaEnd-05-46-45"), "09:46 停一切")
    check("窗口外的 MAA 不动", got.get("MAA-09-00-00"), None)
    raw_text = e.state.ledger_path("2026-09-30").read_text(encoding="utf-8")
    check("残行原样保留", TORN in raw_text.splitlines(), True)
    check("行数不变", len(raw_text.splitlines()), 4)
    before = raw_text
    check("再跑一次什么都不补", handle.backfill_manual_stops(e, EVENING), 0)
    check("文件逐字节不变", e.state.ledger_path("2026-09-30").read_text(encoding="utf-8"), before)

    print("\n[日报走 _compose_daily（report 命令同一个函数）：两趟都是 ⏹]")
    title, body = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30"))
    check("OK-WW 那行是 ⏹", kind_line(body, "鸣潮")[:1], "⏹")
    check("MaaEnd 那行是 ⏹", kind_line(body, "终末地")[:1], "⏹")
    check("有被停一切停掉的备注", "被停一切中途停掉，本轮已中止" in body, True)
    check("标题不算失败", "失败" in title, False)
    check("两趟都写「已停，未补」", body.count("已停，未补"), 2)

    print("\n[停掉之后同一脚本又跑过一趟：那趟停的不写「未补」]")
    later = line("OK-WW-10-30-00", "OK-WW", "wuwa", at(30, 10, 30), at(30, 10, 50), True)
    title, body = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30") + [later])
    check("只剩 MaaEnd 那条写「已停，未补」", body.count("已停，未补"), 1)
    from ark_relay.core import ledger as _core
    check("共用判定：有 manual_stop 才算", [_core.manual_stop(x) for x in (
        {"raw": {"manual_stop": "09:46 停一切"}}, {"raw": {}}, {"raw": None}, {})], [True, False, False, False])

    W0930 = [{"start": "2026-09-30T09:46:28+08:00", "end": "2026-09-30T09:47:22+08:00"}]

    print("\n[no press recorded: nothing is booked (the shipped seed went, audit 11 #7)]")
    e = build(windows=None)
    check("no window file: nothing booked", handle.backfill_manual_stops(e, EVENING), 0)
    check("and no window file written", (Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).exists(), False)
    check("the seed's names are gone", [n for n in ("ESTOP_SEED", "merge_estop_seed") if hasattr(commands, n)], [])

    print("\n[another press on record: the file is left as it is]")
    e = build(windows=[{"start": "2026-09-30T20:00:00+08:00", "end": "2026-09-30T20:01:00+08:00"}])
    handle.backfill_manual_stops(e, EVENING)
    w = json.loads((Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))
    check("only that press", [x.get("start")[11:16] for x in w], ["20:00"])

    print("\n[过了午夜（北京时间）：昨天的账本照样补]")
    e = build(windows=W0930)
    check("10-01 00:30 开机也补了两趟", handle.backfill_manual_stops(e, datetime(2026, 10, 1, 0, 30, tzinfo=SERVER_TZ)), 2)

    print("\n[压着的告警：被停掉的两趟相关的清掉，别的不动]")

    def rec_of(d, **over):
        x = dict(d, **over)
        return RunRecord(run_id=x["run_id"], script=x["script"], user=x["user"],
                         started=datetime.fromisoformat(x["started"]),
                         finished=datetime.fromisoformat(x["finished"]), ok=x["ok"],
                         failed_tasks=x["failed_tasks"], raw=dict(x["raw"]))

    e = build(windows=W0930)
    # The stopped MaaEnd run itself, held for the final alarm.
    e._pending[("MaaEnd", "endfield")] = rec_of(MAAEND)
    # Something unrelated that must stay.
    other = rec_of(MAA, run_id="MAA-08-00-00", ok=False, failed_tasks=["x"], raw={})
    e._pending[("MAA", "ark")] = other
    e._persist_pending()
    handle.backfill_manual_stops(e, EVENING)
    check("MaaEnd 不再等着重试", ("MaaEnd", "endfield") in e._pending, False)
    check("MAA 的照旧压着", list(e._pending), [("MAA", "ark")])
    check("被停掉的 MaaEnd 失败进群", sorted(t for t, _ in e.notifier.sent), ["❌ MaaEnd 失败"])
    check("说明后面那趟是停一切停掉的", all("停一切停掉" in b for _, b in e.notifier.sent), True)
    disk = State(e.cfg.state_dir).load_pending()
    check("磁盘上也清掉了（重启读回一致）", len(disk.get("pending") or []), 1)

    print("\n[被停掉那趟之后的新失败：不清]")
    e = build(windows=W0930)
    late = rec_of(MAAEND, run_id="MaaEnd-10-30-00", started=at(30, 10, 30).isoformat(),
                  finished=at(30, 10, 50).isoformat())
    e._pending[("MaaEnd", "endfield")] = late
    handle.backfill_manual_stops(e, EVENING)
    check("10:30 的失败还压着", ("MaaEnd", "endfield") in e._pending, True)

    print("\n[开机阶段：出错不抛、写一行日志]")
    sys.modules.setdefault("win32event", types.ModuleType("win32event"))
    import boot_stages

    class Log:
        def __init__(self):
            self.lines = []

        def info(self, *a, **k):
            self.lines.append(a)

        def exception(self, *a, **k):
            self.lines.append(("EXC",) + a)

    lg = Log()
    e = build(windows=W0930)
    _real_backfill = handle.backfill_manual_stops
    handle.backfill_manual_stops = lambda eng, now=None: _real_backfill(eng, now or EVENING)
    try:
        boot_stages._stage_backfill_manual_stops(e, lg)
    finally:
        handle.backfill_manual_stops = _real_backfill
    check("阶段跑完两趟有停一切", sorted(v for v in stops(e).values() if v), ["09:46 停一切", "09:46 停一切"])
    real = handle.backfill_manual_stops
    handle.backfill_manual_stops = lambda *a, **k: 1 / 0
    try:
        boot_stages._stage_backfill_manual_stops(e, lg)
        check("出错不抛", True, True)
        check("记了异常", any(x and x[0] == "EXC" for x in lg.lines), True)
    finally:
        handle.backfill_manual_stops = real


def _part_manual_stop_not_selfheal():
    """A run the red button (停一切) cut short is a manual stop, not the retry that healed the day.
    """
    import json
    import os
    from datetime import datetime

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.features import collect_retry
    from ark_relay.features import commands
    from ark_relay.features import handle
    from ark_relay.core import ledger as core
    handle._screenshot_to = lambda out: False   # the real one waits up to 10 s for a Windows screenshot file
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return False

    class Src:
        def fetch(self, seen):
            return []

    def at(hh, mm, ss=0):
        return datetime(2026, 9, 30, hh, mm, ss, tzinfo=SERVER_TZ)

    def rec(run_id, started, finished, script="OK-WW", user="wuwa", ok=False):
        return RunRecord(run_id=run_id, script=script, user=user, started=started, finished=finished,
                         ok=ok, failed_tasks=[] if ok else ["任务执行：卡在对话框"],
                         raw={"tasks_done": ["日常"]} if ok else {})

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._verify_outcome = lambda r: None
        return e

    def press(e, start, end):
        (Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).write_text(
            json.dumps([{"start": start.isoformat(timespec="seconds"),
                         "end": end.isoformat(timespec="seconds")}]), encoding="utf-8")

    gates = []
    handle._weekly_gates = lambda eng, r: gates.append(r.run_id)

    def morning(e):
        """The two genuine failures of 09-30, booked and held the way _hold_for_retry leaves them."""
        for rid, s, f in (("2026-09-30/wuwa/09-19-00", at(9, 12), at(9, 19)),
                          ("2026-09-30/wuwa/09-30-00", at(9, 21), at(9, 30))):
            r = rec(rid, s, f)
            e.state.append_ledger(r)
            e._pending[("OK-WW", "wuwa")] = r
        e._persist_pending()

    print("[09-30 原样：两次失败在等，第三趟被停一切停掉、AUTO-MAS 记成功]")
    e = build()
    morning(e)
    press(e, at(9, 46, 40), at(9, 47, 30))
    stopped = rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True)
    e._handle(stopped)
    check("引擎无 _recovered 旁路", hasattr(e, "_recovered"), False)
    check("前面的失败不再等着重试", dict(e._pending), {})
    check("重启读回来也是空的", dict(State(e.cfg.state_dir).load_pending() or {}).get("pending") or [], [])
    check("没走成功那条路（周常门没碰）", gates, [])
    check("停一切之前那次失败进群一条", [t for t, _ in e.notifier.sent], ["❌ OK-WW 失败"])
    check("说明后面那趟是停一切停掉的", all("停一切停掉" in b for _, b in e.notifier.sent), True)
    ledger = e.state.read_ledger("2026-09-30")
    row = [x for x in ledger if x["run_id"] == stopped.run_id]
    check("账本记了这一趟", len(row), 1)
    check("账本那行记着是停一切停掉的", (row[0]["raw"] or {}).get("manual_stop"), "09:46 停一切")
    check("前两次失败还在账本里", sum(1 for x in ledger if not x["ok"]), 2)

    print("\n[被停掉的那趟 AUTO-MAS 记成失败：也不当新失败压着等推]")
    e = build()
    press(e, at(9, 46, 40), at(9, 47, 30))
    e._handle(rec("2026-09-30/endfield/09-47-10", at(9, 47, 0), at(9, 47, 12),
                  script="MaaEnd", user="endfield"))
    check("没进待推", dict(e._pending), {})
    check("AUTO-MAS 记的失败照报一条（2026-10-06）", [t for t, _ in e.notifier.sent], ["❌ MaaEnd 失败"])
    check("说明是停一切停掉的", all("停一切停掉" in b for _, b in e.notifier.sent), True)

    print("\n[MaaEnd 被停掉：母本路线照样改回]")
    restored = []
    real_restore = collect_retry.restore_master
    collect_retry.restore_master = lambda cfg: restored.append(1) or ""
    e = build()
    press(e, at(9, 46, 40), at(9, 47, 30))
    e._handle(rec("2026-09-30/endfield/09-47-11", at(9, 47, 0), at(9, 47, 12),
                  script="MaaEnd", user="endfield", ok=True))
    check("restore_master 跑了", restored, [1])
    collect_retry.restore_master = real_restore

    print("\n[回归：窗口外的成功照旧算重试后通过，立即直推群排查]")
    gates.clear()
    e = build()
    morning(e)
    press(e, at(8, 0), at(8, 1))
    ok_later = rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True)
    e._handle(ok_later)
    check("清空待推并直推群说明中途失败重试通过",
          (dict(e._pending), [t for t, _ in e.notifier.sent]), ({}, ["⚠️ OK-WW 中途失败过，重试后成功"]))
    check("走了成功那条路", gates, [ok_later.run_id])
    row = [x for x in e.state.read_ledger("2026-09-30") if x["run_id"] == ok_later.run_id]
    check("账本那行没有手动停止记号", (row[0]["raw"] or {}).get("manual_stop"), None)

    print("\n[没有按过红按钮（没有文件）：照旧]")
    e = build()
    morning(e)
    e._handle(rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True))
    check("清空待推并直推群", (dict(e._pending), [t for t, _ in e.notifier.sent]),
          ({}, ["⚠️ OK-WW 中途失败过，重试后成功"]))

    print("\n[日报：停掉的那趟是 ⏹ 不是 ✅，失败行不进日报]")

    def entry(rid, s, f, ok, raw=None, failed=None):
        return {"run_id": rid, "script": "OK-WW", "user": "wuwa",
                "started": s.isoformat(), "finished": f.isoformat(), "ok": ok,
                "failed_tasks": failed or [], "duration_known": True, "transitional": False,
                "raw": raw or {}}

    fail1 = entry("r1", at(9, 12), at(9, 19), False, failed=["日常"])
    fail2 = entry("r2", at(9, 21), at(9, 30), False, failed=["日常"])
    manual = entry("r3", at(9, 38), at(9, 47, 5), True,
                   raw={"manual_stop": "09:46 停一切", "tasks_done": ["日常"]})
    entries = [fail1, fail2, manual]
    check("episode_kinds 把它记成 manual", core.episode_kinds(entries).get("r3"), "manual")
    check("retried_notes 不把它当后来做成了", core.retried_notes(entries), {})
    title, body = core.format_daily("2026-09-30", entries)
    row3 = [ln for ln in body.splitlines() if "09:38" in ln]
    check("那一行的图标是 ⏹", bool(row3) and row3[0].startswith("⏹"), True)
    check("那一行不是 ✅", bool(row3) and row3[0].startswith("✅"), False)
    check("有备注说明被停一切停掉", "被停一切中途停掉，本轮已中止" in body, True)
    check("标题不含「重试后成功」", "重试后成功" in title, False)
    check("前两次失败不进日报，且标题中性不误标全绿", (title, "❌" in body, "没跑成" in body),
          ("📋 09-30 · 今日日报", False, False))

    title, body = core.format_daily("2026-09-30", [manual])
    check("只有停掉的那趟：标题说有一趟被手动停止", title.endswith("其余全绿 ✅（有一趟被手动停止）"), True)

    ok_run = entry("r4", at(10, 0), at(10, 20), True, raw={"tasks_done": ["日常"]})
    retried = [fail1, ok_run, dict(manual, run_id="r5", started=at(11, 0).isoformat())]
    title, _ = core.format_daily("2026-09-30", retried)
    check("存在真失败的一天不误标全绿", title, "📋 09-30 · 今日日报")

    print("\n[记分牌不算停掉的那趟]")
    from ark_relay.features import report as scoreboard
    calls = []
    real_record = scoreboard.record
    scoreboard.record = lambda *a, **k: calls.append(a)
    st = State(tmpdir())
    st.append_ledger(rec("x/1", at(9, 38), at(9, 47), ok=True))
    m = rec("x/2", at(9, 38), at(9, 47), ok=True)
    m.raw["manual_stop"] = "09:46 停一切"
    st.append_ledger(m)
    check("只记了正常那趟", len(calls), 1)
    scoreboard.record = real_record


def _part_notify_routing_main():
    """日常消息只发一个渠道，报警才全发。"""
    import os

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                      SERVERCHAN_KEY="", WECOM_CORPID="", ARK_LLM_KEY="")
    from ark_relay.core.config import Config
    from ark_relay.core.notify import Notifier

    class Fake:
        """一个够用的假通道：记下被调用过、可以被设成必然失败。"""
        def __init__(self, log, name, broken=False):
            self.log, self.name, self.broken = log, name, broken
            self.enabled = True
        def send_text(self, *a):
            # 企业微信收的是 "标题\n\n正文" 拼好的一串，Server酱 收的是分开的两段。
            # 只记标题那一段，调用方才好按标题筛。
            self.log.append((self.name, a[0].split("\n")[0]))
            if self.broken:
                raise RuntimeError(f"{self.name} 挂了")

    def build(broken=()):
        log = []
        n = Notifier(Config())
        n.serverchan = Fake(log, "Server酱", "Server酱" in broken)
        n.wecom_bot = Fake(log, "企业微信机器人", "企业微信机器人" in broken)
        n.wecom = Fake(log, "企业微信", "企业微信" in broken)
        return n, log

    print("[三个通道各司其职：真报警进群，日报和其余走 Server酱，私聊永远不自动发]")
    n, log = build()
    check("日报发出去了", n.send("📋 日报", "正文", daily=True), [])
    check("日报只走 Server酱（群机器人 2048 字节就截断成好几条）", [c for c, _ in log], ["Server酱"])
    n, log = build()
    check("报警发出去了", n.send("⚠️ 出错了", "正文", alert=True), [])
    check("报警只进群机器人", [c for c, _ in log], ["企业微信机器人"])
    n, log = build()
    check("其余通知发出去了", n.send("🆕 游戏更新", "正文"), [])
    check("其余通知只走 Server酱", [c for c, _ in log], ["Server酱"])

    print("\n[Server酱 挂了：日报回退到群机器人（分条也比没有强），绝不落到私聊]")
    n, log = build(broken=("Server酱",))
    n._announcing = True
    check("日报仍算送达", n.send("📋 日报", "正文", daily=True), [])
    check("先试 Server酱，回退到群机器人", [c for c, t in log if t == "📋 日报"], ["Server酱", "企业微信机器人"])

    print("\n[群机器人挂了：报警回退到 Server酱，绝不落到私聊]")
    n, log = build(broken=("企业微信机器人",))
    n._announcing = True
    check("仍算送达", n.send("⚠️ 出错了", "正文", alert=True), [])
    check("试了群机器人，回退到 Server酱", [c for c, t in log if t == "⚠️ 出错了"], ["企业微信机器人", "Server酱"])
    check("企业微信私聊没被惊动", any(c == "企业微信" for c, _ in log), False)

    print("\n[这条报警到底进没进群（errwatch 据此决定那行日志要不要再推）]")
    n, log = build()
    n.send("⚠️ 出错了", "正文", alert=True)
    check("群机器人收了：进了群", n.went_to_group(), True)
    n, log = build(broken=("企业微信机器人",))
    n._announcing = True
    n.send("⚠️ 出错了", "正文", alert=True)
    check("群机器人没收、Server酱 收了：没进群", n.went_to_group(), False)
    n, log = build()
    n.send("🆕 游戏更新", "正文")
    check("普通通知：没进群", n.went_to_group(), False)
    check("只发群机器人的：进了群", (n.send_group("⚠️ 出错了", "正文"), n.went_to_group()), ([], True))

    print("\n[Server酱 挂了：普通通知不往群里塞，也不进私聊，返回没送到]")
    n, log = build(broken=("Server酱",))
    n._announcing = True
    check("返回失败", bool(n.send("🆕 游戏更新", "正文")), True)
    check("只试了 Server酱", sorted({c for c, _ in log}), ["Server酱"])

    print("\n[日报或手机页已经有的不再推：只记日志，算送达]")
    from ark_relay.core.notify import route_of
    for t in ("🔄 中继已更新（3 个文件）", "🗓️ 周常", "⏭️ 跳过模式", "🛑 已停一切", "📱 配置已修改",
              "🗂️ 证据包已送出机器", "✅ 自动采集：补跑后全部走完",
              "🩹 OK-WW 补丁（18 条）", "🥚 开始刷声骸", "✅ 无音区结算截图：不发了"):
        check(f"只记日志：{t}", route_of(t, alert=t.startswith("⚠️")), "log")
    # Success and acknowledgements only: a healthy patch round is log-only even when
    # the caller sends texts.patches() with alert=True for its failure variant.
    check("补丁全贴上（alert=True 也只记日志）", route_of("🩹 OK-WW 补丁（18 条）", alert=True), "log")
    n, log = build()
    check("只记日志的返回空（调用方不再重推）", n.send("🔄 中继已更新", "正文"), [])
    check("一个通道都没碰", log, [])

    print("\n[还会推的：报警进群，其余进 Server酱]")
    for t in ("❌ OK-WW 失败", "⚠️ 这一轮没干完", "早班 没有运行", "🔌 AUTO-MAS 启动不起来", "⚠️ 中继自更新没成功",
              "🛑 没能停干净",
              "⚠️ 终末地 MaaEnd 卡住，已结束它让 AUTO-MAS 接着走", "⚠️ 终末地 MaaEnd 卡死，没能结束",
              "⏱️ 鸣潮（OK-WW）跑超时，AUTO-MAS 正在重试", "⏰ 早班超时还没跑完",
              "❌ 明日方舟早班没跑成", "⚠️ 终末地晚班没干完",
              "⚠️ 自动采集：补跑仍有路线没走通", "🚩 自动采集：有路线连续两天补跑失败，是复发性问题",
              "⚠️ 森空岛给了不止一个终末地角色，没有读",
              "🩺 中继自己报错了（3 条）",
              "⚠️ 明日方舟理智不够，这一趟没打",
              "⏸ MaaEnd 进不了游戏，稍后补跑", "📱 配置没改成", "🧹 终末地配置清掉了死条目", "⚠️ 终末地配置里的死条目没能清", "⚠️ 预更新没能确认（1 项）", "⚠️ 游戏更新没能确认（2 项）",
              "⚠️ OK-WW 补丁有 1 条没贴上（共 18 条）", "🔌 推送通道故障：企业微信机器人"):
        check(f"进群：{t}", route_of(t, alert=True), "group")
    for t in ("🆕 预更新", "🆕 游戏更新", "🔁 更新后重跑", "🥚 刷声骸收工", "⏸ MaaEnd 进不了游戏，稍后补跑", "🌙 关机被取消",
              "📱 配置没改成", "✗ set_stage: 找不到", "🔓 终末地日常已开回", "🗓️ 新的一周", "⚠️ OK-WW 补丁有 1 条没贴上（共 18 条）",
              "🔌 推送通道故障：企业微信", "💳 月卡快到期"):
        check(f"Server酱：{t}", route_of(t), "info")
    check("预更新没能确认：带 alert 就进群，不再降到 Server酱", route_of("⚠️ 预更新没能确认（1 项）", alert=True), "group")
    check("日报走 Server酱", route_of("📋 09-14 · 全绿 ✅", daily=True), "daily")

    print("\n[docs/NOTIFICATIONS.md 的表和代码一致]")
    import re
    from pathlib import Path as _P
    _doc = (_P(__file__).resolve().parents[2] / "docs" / "NOTIFICATIONS.md").read_text(encoding="utf-8")
    _rows = re.findall(r"^\| (.+?) \| (group|daily|info|log) \| ", _doc, flags=re.M)
    check("表里至少 25 行", len(_rows) >= 25, True)
    _probe = {"📋 日报 / 🔎 临时查看 / （补发）": ("📋 09-14 · 全绿", True, False),
              "❌ <script> 失败": ("❌ OK-WW 失败", False, True),
              "<队列> 没有运行 / 机器没开机": ("早班 没有运行", False, True),
              "⏸ <script> 进不了游戏，稍后补跑": ("⏸ MaaEnd 进不了游戏，稍后补跑", False, True),
              "📱 配置没改成 / ✗ …": ("✗ set_stage: 没有这个字段", False, True),
              "⏭️ 跳过模式 / 🛑 已停一切 / 📱 配置已修改 / ✅ …": ("✅ 刷取关卡：TO-5 → 1-7", False, False),
              "🩹 OK-WW 补丁（N 条）": ("🩹 OK-WW 补丁（18 条）", False, False),
              "⚠️ OK-WW 补丁有 N 条没贴上": ("⚠️ OK-WW 补丁有 1 条没贴上（共 18 条）", False, True),
              "⚠️ 预更新没能确认 / ⚠️ 游戏更新没能确认": ("⚠️ 预更新没能确认（1 项）", False, True)}
    for cell, want in _rows:
        if cell in _probe:
            title, daily, alert = _probe[cell]
        else:
            title, daily, alert = cell.split(" / ")[0], False, want == "group"
        check(f"表：{cell} → {want}", route_of(title, alert=alert, daily=daily), want)

    print("\n[自己好了的：一条都不发，日报里有（用户 2026-10-06 05:07）]")
    _sec = _doc.split("### Recovered by itself", 1)
    check("文档有「Recovered by itself」那张表", len(_sec), 2)
    _rec_rows = re.findall(r"^\| ([^|]+?) \| [^|]+ \| [^|]+ \|$", _sec[1].split("\n### ", 1)[0], flags=re.M) if len(_sec) == 2 else []
    _rec_rows = [c for c in _rec_rows if not c.startswith(("Title", "---"))]
    NOT_SENT = {"⚠️ <script> 中途失败过，重试后成功": "self_healed",
                "⚠️ <script> 更新时失败过，重跑后成功": "healed_after_update",
                "⚠️ <游戏><班>失败过，补跑后走通了": "makeup_passed",
                "⚠️ 终末地装新版重启了这一趟（前面那趟已做完）": "MAAEND_UPDATE_AFTER_DONE",
                "🔁 自动采集：只补跑失败的路线": "COLLECT_RETRY_START"}
    for cell in NOT_SENT:
        check(f"表里有：{cell}", cell in _rec_rows, True)
        check(f"主表里没有它（它不再有路由）：{cell}", any(c == cell for c, _ in _rows), False)
    check("中途重启那一行在（压着，后面那次定）", any(c.startswith("(an attempt AUTO-MAS recorded as a restart") for c in _rec_rows), True)
    check("推送重试那一行在", any("推送传输失败" in c for c in _rec_rows), True)
    _src = "\n".join(f.read_text(encoding="utf-8") for f in sorted([p for p in (_P(__file__).resolve().parents[1] / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks", "machinechecks.py"} & set(p.parts)]))
    for cell, name in NOT_SENT.items():
        sent = re.findall(r"(?:\.send|\.send_group|_push_now|unresolved\.send)\((?:[^()]|\([^()]*\))*?texts\." + name + r"\b", _src)
        check(f"没有哪个 send 发它：texts.{name}", sent, [])
    from ark_relay.core import texts as _texts
    check("只补跑失败的路线：不再被 route_of 硬塞进群", route_of(_texts.COLLECT_RETRY_START), "info")

    print("\n[通道坏了：每一次被拒都报，不是每种故障报一次（2026-10-06）]")
    n, log = build(broken=("企业微信机器人",))
    check("第一条报警送到了（Server酱）", n.send("⚠️ 出错了", "正文", alert=True), [])
    check("第二条报警送到了（Server酱）", n.send("⚠️ 又出错了", "正文", alert=True), [])
    check("两次被拒，两条通道故障", len([t for c, t in log if t.startswith("🔌") and c == "Server酱"]), 2)
    check("故障通知只走还活着的渠道，不再重打刚失败的群机器人",
          [c for c, t in log if t.startswith("🔌")], ["Server酱", "Server酱"])
    n_sc, log_sc = build(broken=("Server酱",))
    check("Server酱挂了日报回退群机器人", n_sc.send("📋 日报", "正文", daily=True), [])
    check("故障通知走群机器人且不再死磕刚失败的 Server酱",
          [c for c, t in log_sc if t.startswith("🔌")], ["企业微信机器人"])
    n_other, log_other = build()
    n_other._announce_outage({"企业微信": "60020"}, ["Server酱"])
    check("非群组通道故障仍按群组顺序先发群机器人并一次即停",
          [c for c, t in log_other if t.startswith("🔌")], ["企业微信机器人"])

    print("\n[每条送到的推送记一行：走哪一路、哪个渠道收下（审查 10-13 s5 #4）]")
    import logging

    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelno, record.getMessage()))

    _g = _Grab()
    from ark_relay.core import notify as _notify_mod
    _nlog = _notify_mod.log
    _nlog.addHandler(_g)
    _lvl = _nlog.level
    _nlog.setLevel(logging.INFO)
    try:
        n, log = build(broken=("Server酱",))
        n._announcing = True
        n.send("📋 日报", "正文", daily=True)
        n, log = build()
        n.send("⚠️ 出错了", "正文", alert=True)
        n.send("🆕 游戏更新", "正文")
        n.send_group("🎴 明天开新卡池：鸣潮", "正文")
    finally:
        _nlog.removeHandler(_g)
        _nlog.setLevel(_lvl)
    _info = [m for lv, m in _g.lines if lv == logging.INFO and "送到" in m]
    check("日报回退到群机器人：这一行写了 daily 路和群机器人",
          any("daily" in m and "企业微信机器人" in m and "📋 日报" in m for m in _info), True)
    check("报警：group 路、群机器人", any("group" in m and "企业微信机器人" in m and "⚠️ 出错了" in m for m in _info), True)
    check("其余通知：info 路、Server酱", any("info" in m and "Server酱" in m and "🆕 游戏更新" in m for m in _info), True)
    check("只发群的：group 路、群机器人", any("group" in m and "企业微信机器人" in m and "🎴" in m for m in _info), True)
    check("一条送到的推送只记一行", len(_info), 4)

    print("\n[一个线程正在报通道故障时，另一个线程的被拒照样报（审查 10-13 s5 #5）]")
    # The flag was one per Notifier: while errwatch's push thread announced an outage,
    # a refusal on the main loop was only a WARNING line.
    import threading
    n, log = build(broken=("企业微信机器人",))
    inside, release = threading.Event(), threading.Event()
    _sc_send = n.serverchan.send_text

    def _slow(title, body=""):
        if title.startswith("🔌") and not inside.is_set():
            inside.set()                     # thread A is now inside its announcement
            release.wait(5)
        return _sc_send(title, body)

    n.serverchan.send_text = _slow
    ta = threading.Thread(target=lambda: n.send("⚠️ 甲线程的报警", "正文", alert=True))
    ta.start()
    check("甲线程进了通道故障通知", inside.wait(5), True)
    n.send("⚠️ 乙线程的报警", "正文", alert=True)
    release.set()
    ta.join(5)
    check("两条报警各报了一次通道故障（Server酱 收到两条 🔌）",
          len([t for c, t in log if c == "Server酱" and t.startswith("🔌")]), 2)

    print("\n[默认就是日常，不是报警]")
    n, log = build()
    n.send("🆕 预更新", "")
    check("预更新只走一处", [c for c, _ in log], ["Server酱"])


def _part_notify_channels():  # noqa: C901
    """推送通道自己那一层：一个挂了不能拖垮其余，失败原因必须回到调用方手里。"""
    import json
    import os
    import types
    import urllib.error
    import urllib.parse
    import urllib.request

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                      SERVERCHAN_KEY="", WECOM_CORPID="", WECOM_BOT_URL="",
                      ARK_LLM_KEY="")
    from ark_relay.core import notify
    from ark_relay.core.config import Config
    from ark_relay.core.notify import (
        Notifier, ServerChan, WeCom, WeComBot, _image_bytes_for_wecom,
    )

    def _short(v):
        # 这个文件里有整段日报那么长的值，原样打出来会把屏幕刷满，反而看不见哪条红了。
        text = repr(v)
        return text if len(text) <= 120 else text[:117] + "..."

    # ---------------------------------------------------------------- fake HTTP
    # Replaces urlopen for this process only. An unrouted URL is a hard failure:
    # a test that quietly reaches the real sctapi.ftqq.com is worse than no test.

    class _Resp:
        def __init__(self, text: str):
            self._b = text.encode("utf-8")

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    ROUTES: list = []       # [(url fragment, handler)]
    CALLS: list = []        # [(url, decoded request body)]

    def route(fragment, handler):
        ROUTES.append((fragment, handler))

    def reset(*routes):
        ROUTES.clear()
        CALLS.clear()
        for frag, handler in routes:
            route(frag, handler)

    def once(*results):
        """A handler that hands back one result per call, then repeats the last."""
        box = list(results)

        def handler(_req):
            return box.pop(0) if len(box) > 1 else box[0]
        return handler

    def fake_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        body = ""
        if not isinstance(req, str) and req.data:
            body = req.data.decode("utf-8", "replace")
        CALLS.append((url, body))
        for frag, handler in ROUTES:
            if frag in url:
                out = handler(req)
                if isinstance(out, BaseException):
                    raise out
                return _Resp(json.dumps(out) if isinstance(out, dict) else out)
        raise AssertionError(f"没挂假响应的 URL，测试差点真的联网: {url}")

    urllib.request.urlopen = fake_urlopen

    class _Clock:
        """Stand-in for the `time` module inside notify: records the backoff sleeps
    instead of actually waiting, so a 3-attempt retry test stays instant."""

        def __init__(self):
            self.slept: list = []
            self.now = 1_000_000.0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.slept.append(seconds)

    CLOCK = _Clock()
    notify.time = CLOCK

    def posted(fragment):
        return [b for u, b in CALLS if fragment in u]

    def urls(fragment=""):
        return [u for u, _ in CALLS if fragment in u]

    OK = {"errcode": 0, "errmsg": "ok"}
    TOKEN = {"errcode": 0, "access_token": "tok-1", "expires_in": 7200}

    def transport_error(_req):
        return urllib.error.URLError("TLS handshake timed out")

    def http_403(_req):
        return urllib.error.HTTPError("https://x/", 403, "Forbidden", {}, None)

    # --------------------------------------------------- _post: 什么该重试什么不该
    print("[传输失败要重试：告警是一次性的，没人补发]")
    reset(("fake.test", once(transport_error(None), transport_error(None), OK)))
    CLOCK.slept.clear()
    check("第三次通了就算成功", notify._post_json("https://fake.test/send", {}), OK)
    check("一共试了 3 次", len(CALLS), 3)
    check("退避了 2 次", len(CLOCK.slept), 2)
    check("每次都在 [0, 上限] 里随机（full jitter）",
          all(0 <= w <= hi for w, hi in zip(CLOCK.slept, (1.5, 3.0), strict=True)), True)

    class _Edge:
        """Stand-in for notify._rng that always draws one end of the interval."""

        def __init__(self, top):
            self.top = top

        def uniform(self, lo, hi):
            return hi if self.top else lo

    print("\n[退避上限按指数翻倍、封顶；随机从 0 起，几台一起失败也不会一起重试]")
    real_rng = notify._rng
    notify._rng = _Edge(True)
    reset(("fake.test", once(transport_error(None), transport_error(None), OK)))
    CLOCK.slept.clear()
    notify._post_json("https://fake.test/send", {})
    check("上限依次 1.5、3.0 秒（指数）", CLOCK.slept, [1.5, 3.0])
    check("上限封顶", notify._backoff(20), notify._BACKOFF_CAP)
    notify._rng = _Edge(False)
    check("下限是 0", notify._backoff(1), 0.0)
    notify._rng = real_rng
    draws = {round(notify._backoff(1), 6) for _ in range(50)}
    check("真随机：50 次不全一样", len(draws) > 1, True)

    print("\n[errcode -1「系统繁忙」：文档说稍候重试、不超过 3 次]")
    reset(("fake.test", once({"errcode": -1, "errmsg": "system busy"}, OK)))
    CLOCK.slept.clear()
    check("第二次通了", notify._post_json("https://fake.test/send", {}), OK)
    check("试了 2 次", len(CALLS), 2)
    reset(("fake.test", once({"errcode": -1, "errmsg": "system busy"})))
    got = notify._post_json("https://fake.test/send", {})
    check("三次都忙：把 -1 原样交回调用方", (got.get("errcode"), len(CALLS)), (-1, 3))

    print("\n[三次都失败：把传输失败的原因抛给调用方，不许悄悄返回空]")
    reset(("fake.test", once(transport_error(None))))
    try:
        notify._post_json("https://fake.test/send", {})
        check("必须抛异常", "没抛", "抛了")
    except Exception as exc:  # noqa: BLE001
        check("抛的是传输失败本身", "TLS handshake timed out" in str(exc), True)
    check("试满 3 次才放弃", len(CALLS), 3)

    print("\n[HTTP 状态码是服务器的回答，不是传输失败：立刻抛，不许干等退避]")
    reset(("fake.test", once(http_403(None))))
    CLOCK.slept.clear()
    try:
        notify._post_form("https://fake.test/send", {"a": "b"})
        check("必须抛异常", "没抛", "抛了")
    except urllib.error.HTTPError as exc:
        check("原样把状态码抛出去", exc.code, 403)
    check("只试了 1 次", len(CALLS), 1)
    check("一秒都没等", CLOCK.slept, [])

    # ------------------------------------------------------------- Server酱
    print("\n[Server酱：sctp 是三代，多一个 uid 端点；SCT 是 Turbo，只有一个]")
    check("SCT 只有一个端点",
          ServerChan(types.SimpleNamespace(serverchan_key="SCTabc"))._endpoints(),
          ["https://sctapi.ftqq.com/SCTabc.send"])
    sctp = ServerChan(types.SimpleNamespace(serverchan_key="sctp123t456"))
    check("sctp 两个端点，sctapi 在前",
          [u.split("/")[2] for u in sctp._endpoints()],
          ["sctapi.ftqq.com", "123.push.ft07.com"])

    print("\n[第一个端点挂了就换第二个，一样算送达]")
    reset(("sctapi.ftqq.com", once(http_403(None))),
          ("push.ft07.com", once({"code": 0})))
    sctp.send_text("⚠️ OK-WW 失败", "正文")
    check("两个端点都试过", len(CALLS), 2)

    print("\n[两个都失败：抛出来的原因里两个主机、两条理由都在]")
    reset(("sctapi.ftqq.com", once(http_403(None))),
          ("push.ft07.com", once({"code": 40001, "message": "bad pushkey"})))
    try:
        sctp.send_text("⚠️ 失败", "正文")
        check("必须抛异常", "没抛", "抛了")
    except RuntimeError as exc:
        msg = str(exc)
        check("第一个主机在里面", "sctapi.ftqq.com" in msg, True)
        check("第二个主机也在", "123.push.ft07.com" in msg, True)
        check("403 这条理由没被吞", "403" in msg, True)
        check("40001 这条理由也没被吞", "40001" in msg, True)

    print("\n[code 非 0 不许当成功：0 只代表 API 收下了，本来就不保证送达]")
    reset(("sctapi.ftqq.com", once({"code": 40001, "message": "bad pushkey"})))
    sct = ServerChan(types.SimpleNamespace(serverchan_key="SCTabc"))
    try:
        sct.send_text("标题", "正文")
        check("必须抛异常", "没抛", "抛了")
    except RuntimeError as exc:
        check("原因里带着返回码", "40001" in str(exc), True)

    print("\n[正文换行要加倍：Server酱 按 Markdown 渲染，单换行会被吃掉，日报糊成一坨]")
    reset(("sctapi.ftqq.com", once({"code": 0})))
    sct.send_text("标" * 200, "第一行\n第二行")
    form = urllib.parse.parse_qs(posted("sctapi.ftqq.com")[0])
    check("换行变成空行", form["desp"][0], "第一行\n\n第二行")
    check("标题截到 100 字", len(form["title"][0]), 100)

    # ------------------------------------------- 企业微信 2048 字节上限的切分
    print("\n[短消息原样一条，不加「（1/1）」这种噪声]")
    check("原样返回", WeCom._split("今天全绿"), ["今天全绿"])

    # 企业微信 text 消息的真实硬上限。`_LIMIT` 比它小，留出「（1/3）」那个序号的位置——
    # 序号是**打包之后**才贴上去的，所以要验的是成品，不是打包时用的那个数。
    API_CAP = 2048

    def widest(parts):
        return max(len(p.encode("utf-8")) for p in parts)

    print("\n[中文长日报：按 utf-8 **字节**算上限（按字数算，中文会整段漏过去）]")
    # 这一段是专门挑的：字数**没到**上限，字节数早就超了。判据写成 len(text) 的话，
    # 它会被原样当成一条发出去——自建应用悄悄截断尾巴，群机器人整条拒收。
    long_zh = "\n".join(f"第 {i} 行：明日方舟今天刷了理智，掉落记在账上" for i in range(40))
    check("字数没到 1800，字节数超过 2048",
          (len(long_zh) <= WeCom._LIMIT, len(long_zh.encode("utf-8")) > API_CAP),
          (True, True))
    parts = WeCom._split(long_zh)
    check("确实切开了", len(parts) > 1, True)
    check("每段都进得了 2048 字节", widest(parts) <= API_CAP, True)
    check("带序号", parts[0].startswith(f"（1/{len(parts)}）"), True)
    rejoined = "\n".join(p.split("\n", 1)[1] for p in parts)
    check("一行不丢、一行不改", rejoined, long_zh)

    print("\n[没有换行的超长单行也必须切得开——群机器人是整条拒收，重试一万次也过不去]")
    one_line = "刷" * 3000
    parts = WeCom._split(one_line)
    check("切开了", len(parts) > 1, True)
    check("每段都进得了 2048 字节", widest(parts) <= API_CAP, True)
    check("一个字都没丢",
          "".join(p.split("\n", 1)[1].replace("\n", "") for p in parts), one_line)
    check("_hard_wrap 按字节切，不按字数",
          max(len(c.encode("utf-8")) for c in WeCom._hard_wrap(one_line, 50)) <= 50,
          True)

    # ------------------------------------------------------ 企业微信自建应用
    WECOM_CFG = types.SimpleNamespace(
        wecom_corpid="cid", wecom_secret="sec", wecom_agentid="1000002",
        wecom_touser="@all")

    print("\n[发送要带上 token；errcode 非 0 抛出，错误码必须留在原因里]")
    reset(("gettoken", once(TOKEN)),
          ("message/send", once({"errcode": 60020,
                                 "errmsg": "not allow to access from your ip"})))
    w = WeCom(WECOM_CFG)
    try:
        w.send_text("⚠️ 失败")
        check("必须抛异常", "没抛", "抛了")
    except RuntimeError as exc:
        check("原因里有 60020", "60020" in str(exc), True)
    check("请求带上了 token", "access_token=tok-1" in urls("message/send")[0], True)

    print("\n[token 缓存住：连发两条只换一次 token]")
    reset(("gettoken", once(TOKEN)), ("message/send", once(OK)))
    w2 = WeCom(WECOM_CFG)
    w2.send_text("第一条")
    w2.send_text("第二条")
    check("只取了一次 token", len(urls("gettoken")), 1)
    check("两条都发出去了", len(urls("message/send")), 2)

    print("\n[取 token 本身失败就抛，不许拿着空 token 去发]")
    # message/send 也挂上假响应：万一真的被调用了，要红在「没有硬着头皮去发」这条上，
    # 而不是红成一个看不懂的「URL 没挂假响应」。
    reset(("gettoken", once({"errcode": 40001, "errmsg": "invalid secret",
                             "access_token": ""})),
          ("message/send", once(OK)))
    try:
        WeCom(WECOM_CFG).send_text("正文")
        check("必须抛异常", "没抛", "抛了")
    except RuntimeError as exc:
        check("说清是 gettoken 失败", "gettoken" in str(exc) and "40001" in str(exc), True)
    check("没有硬着头皮去发", urls("message/send"), [])

    # ------------------------------------------------------------ 群机器人
    print("\n[群机器人：errcode 非 0 抛出；它的字节上限比自建应用更严]")
    check("上限 1800", WeComBot._LIMIT, 1800)
    reset(("qyapi.weixin.qq.com/cgi-bin/webhook",
           once({"errcode": 93000, "errmsg": "invalid webhook url"})))
    bot = WeComBot(types.SimpleNamespace(
        wecom_bot_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"))
    try:
        bot.send_text("正文")
        check("必须抛异常", "没抛", "抛了")
    except RuntimeError as exc:
        check("原因里有 93000", "93000" in str(exc), True)

    print("\n[超长日报按段发出去，不是一整条撞上限被拒]")
    reset(("webhook", once(OK)))
    bot.send_text("刷" * 3000)
    check("拆成了多条", len(posted("webhook")) > 1, True)
    check("每条正文都进得了 2048 字节",
          max(len(json.loads(b)["text"]["content"].encode("utf-8"))
              for b in posted("webhook")) <= API_CAP, True)

    # ------------------------------------ Notifier：一个挂了不能拖垮其余
    print("\n[真通道走完整条 HTTP 路径：日报进群、其余进 Server酱、自建应用不碰]")
    cfg = Config()
    cfg.serverchan_key = "SCTabc"
    cfg.wecom_corpid, cfg.wecom_secret = "cid", "sec"
    cfg.wecom_agentid, cfg.wecom_touser = "1000002", "@all"
    cfg.wecom_bot_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"
    reset(("gettoken", once(TOKEN)),
          ("message/send", once({"errcode": 0})),
          ("sctapi.ftqq.com", once({"code": 0})),
          ("webhook", once({"errcode": 0})))
    n = Notifier(cfg)
    check("三个通道都算配好了", n.channels, ["企业微信", "企业微信机器人", "Server酱"])
    check("日报算送达", n.send("📋 日报", "正文", daily=True), [])
    check("Server酱 收到了日报（群机器人 2048 字节就截成好几条）", len(posted("sctapi.ftqq.com")), 1)
    check("群机器人没收到日报", posted("webhook"), [])
    check("普通通知算送达", n.send("🆕 游戏更新", "正文"), [])
    check("Server酱 收到了普通通知", len(posted("sctapi.ftqq.com")), 2)
    check("群机器人还是没收到", posted("webhook"), [])
    check("自建应用从头到尾没被碰", posted("message/send"), [])

    print("\n[群机器人拒收报警：回退到 Server酱；自建应用仍然不碰]")
    reset(("gettoken", once(TOKEN)),
          ("message/send", once({"errcode": 0})),
          ("sctapi.ftqq.com", once({"code": 0})),
          ("webhook", once({"errcode": 45009, "errmsg": "api freq out of limit"})))
    n2 = Notifier(cfg)
    check("报警仍算送达", n2.send("⚠️ OK-WW 失败", "正文", alert=True), [])
    check("Server酱 接住了", len(posted("sctapi.ftqq.com")) >= 1, True)
    check("自建应用没被碰", posted("message/send"), [])

    print("\n[群通知没配机器人时必须报错，不能返回空当作发过了]")
    # 卡池播报靠这个非空返回值决定「先别落记号，下轮再播」；返回空的话明天开的卡池就永远
    # 不会有人知道。
    cfg_nobot = Config()
    cfg_nobot.serverchan_key = "SCTabc"
    reset(("sctapi.ftqq.com", once({"code": 0})))
    check("说清是机器人没开", Notifier(cfg_nobot).send_group("📣 明天开卡池", "正文"),
          ["企业微信机器人没开"])
    check("绝不偷偷改走 Server酱", posted("sctapi.ftqq.com"), [])

    print("\n[发图出错要把原因返回，不许抛——它跑在日报发出之后，抛出去会把那一轮带走]")
    check("没配机器人时说清楚",
          Notifier(cfg_nobot).send_group_image(Path("/nonexistent.png")),
          ["群机器人未配置"])
    cfg_bot = Config()
    cfg_bot.wecom_bot_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"
    reset(("webhook", once({"errcode": 40006, "errmsg": "invalid media size"})))
    got = Notifier(cfg_bot).send_group_image(TMP / "shot.png")
    check("发图失败返回原因而不是抛出", len(got), 1)
    check("原因里有真东西", got[0] != "", True)

    print("\n[一个通道都没配：配置闸门挡在启动之前，send 自己也不许报绿]")
    blank = Config()
    check("闸门认得出「没有任何推送渠道」",
          any("推送渠道" in p for p in blank.validate()), True)
    got = Notifier(blank).send("标题", "正文")
    check("没有通道时 send() 必须报「没送到」，不许返回空", got != [], True)
    check("原因说的是没配渠道", any("渠道" in x for x in got), True)

    # ---------------------------------------------------- 发图前的体积处理
    print("\n[超过 2MB 的截图要压下去，否则无音区结算截图整张发不出去]")
    from PIL import Image
    big = TMP / "big.png"
    Image.frombytes("RGB", (1920, 1080), os.urandom(1920 * 1080 * 3)).save(big, "PNG")
    check("原图确实超限", big.stat().st_size > 1_800_000, True)
    check("压完在限内", len(_image_bytes_for_wecom(big)) <= 1_800_000, True)
    small = TMP / "small.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(small, "PNG")
    check("没超限的原样返回（重编码会让 md5 对不上）",
          _image_bytes_for_wecom(small), small.read_bytes())


def _part_notify_resilience():
    """HTTPException retries in _post, alive-only outage announcements, and netretry budget guard."""
    import http.client
    import json
    import logging
    import os
    import urllib.error
    import urllib.request

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP),
                      SERVERCHAN_KEY="", WECOM_CORPID="", WECOM_BOT_URL="",
                      ARK_LLM_KEY="")
    from ark_relay.core import notify
    from ark_relay.core.config import Config
    from ark_relay.features import errwatch

    class _Resp:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    real_open, real_sleep = urllib.request.urlopen, notify.time.sleep
    notify.time.sleep = lambda s: None
    try:
        print("[_post 重试 IncompleteRead / BadStatusLine / 截断 UTF-8]")
        calls: list[str] = []
        seq: list = [
            http.client.IncompleteRead(b'{"err'),
            http.client.BadStatusLine("HTTP/1.1"),
            _Resp(json.dumps({"errcode": 0}).encode("utf-8")),
        ]

        def scripted(req, timeout=None):
            calls.append(req.full_url if hasattr(req, "full_url") else str(req))
            got = seq.pop(0)
            if isinstance(got, BaseException):
                raise got
            return got

        urllib.request.urlopen = scripted
        check("IncompleteRead 与 BadStatusLine 均会重试并最终送达",
              notify._post_json("https://fake.test/bot", {"k": 1}), {"errcode": 0})
        check("一共尝试 3 次", len(calls), 3)

        calls.clear()
        seq[:] = [_Resp(b"\xff\xfe"), _Resp(json.dumps({"errcode": 0}).encode("utf-8"))]
        check("损坏 UTF-8 响应也会重试并最终送达",
              notify._post_json("https://fake.test/bot", {"k": 2}), {"errcode": 0})
        check("损坏 UTF-8 重试后第 2 次成功", len(calls), 2)

        calls.clear()
        seq[:] = [http.client.IncompleteRead(b"")] * notify._RETRIES
        try:
            notify._post_json("https://fake.test/bot", {"k": 3})
            raised = ""
        except http.client.IncompleteRead:
            raised = "IncompleteRead"
        check("连续 3 次 IncompleteRead 最终原样抛出", (raised, len(calls)), ("IncompleteRead", 3))

        print("\n[_announce_outage 不再重复猛打刚失败的通道，同时保持 errwatch.PUSHED 契约]")
        cfg = Config()
        cfg.state_dir = TMP
        cfg.wecom_bot_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"
        cfg.serverchan_key = "SCTabc"
        bot_hits, sc_hits = [], []

        def fake_channels(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "webhook" in url:
                bot_hits.append(url)
                raise http.client.IncompleteRead(b"cut")
            sc_hits.append(url)
            return _Resp(json.dumps({"code": 0}).encode("utf-8"))

        urllib.request.urlopen = fake_channels
        seen_warn = []

        class _WarnGrab(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.WARNING:
                    seen_warn.append((record.getMessage(), bool(getattr(record, errwatch.PUSHED, False))))

        grab = _WarnGrab()
        notify.log.addHandler(grab)
        try:
            n = notify.Notifier(cfg)
            check("群机器人连续 IncompleteRead 后回退 Server酱送达",
                  n.send("⚠️ 故障测试", "正文", alert=True), [])
            check("群机器人仅在原发送试了 3 次，故障通告不再重打群机器人", len(bot_hits), notify._RETRIES)
            check("Server酱 收到原消息与通道故障通告共 2 次", len(sc_hits), 2)
            outage_warns = [x for x in seen_warn if "企业微信机器人推送失败" in x[0]]
            check("仅送达 Server酱时保留 PUSHED=False 契约（等机器人恢复再进群）",
                  [p for _, p in outage_warns], [False])

            bot_hits.clear()
            sc_hits.clear()
            seen_warn.clear()

            def sc_down(req, timeout=None):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if "sctapi" in url:
                    sc_hits.append(url)
                    raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
                bot_hits.append(url)
                return _Resp(json.dumps({"errcode": 0}).encode("utf-8"))

            urllib.request.urlopen = sc_down
            check("Server酱 502 时日报回退群机器人送达", n.send("📋 日报", "正文", daily=True), [])
            check("Server酱 仅原发送试 1 次，故障通告不再重打 Server酱", len(sc_hits), 1)
            check("群机器人收到日报与通道故障通告共 2 次", len(bot_hits), 2)
            sc_warns = [x for x in seen_warn if "Server酱推送失败" in x[0]]
            check("群机器人已收到通道故障通告时标 PUSHED=True（errwatch 不重复推送）",
                  [p for _, p in sc_warns], [True])
        finally:
            notify.log.removeHandler(grab)
    finally:
        urllib.request.urlopen, notify.time.sleep = real_open, real_sleep


if __name__ == "__main__":
    sys.exit(run_parts([_part_alert_dedup, _part_first_error_alert, _part_failure_alert, _part_group_long_alarm, _part_uptime_alarm, _part_errwatch_midnight_counts, _part_known_fixed_live, _part_unresolved, _part_silent_green_guards, _part_alertlog_main, _part_alertlog_channel, _part_alertlog_no_lock_on_cos, _part_macpush, _part_every_failure_pushed, _part_recovered_daily_only, _part_manual_stop_backfill, _part_manual_stop_not_selfheal, _part_notify_routing_main, _part_notify_channels, _part_notify_resilience]))
