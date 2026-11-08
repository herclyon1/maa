"""Alarms and the error watch: dedup, the first error, failures, long alarms split, uptime, midnight counts, known-fixed lines, unresolved, silent greens.

One part per former file, each run on its own (tests/_parts.py): test_alert_dedup.py, test_first_error_alert.py, test_failure_alert.py, test_group_long_alarm.py, test_uptime_alarm.py, test_errwatch_midnight_counts.py, test_known_fixed_live.py, test_unresolved.py, test_silent_green_guards.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_alert_dedup():
    """The alerted-today marks (state.json marks.alerted:<day>), and what still uses them.

2026-09-01 the group got the same OK-WW failure three times (17:00/08:29/11:54), and
the user said 「赶紧去修，报了三次了。」 From then until 2026-10-06 the key script +
failed step kept a second final alarm for the same step off the group that day. The
user's order of 2026-10-06, 「不论多少次什么错误都要发」, replaced that: every final
failure is pushed, the same step again included (checked at the end). The marks
stay for what is one event checked again and again (a queue overrun, a timeout
line, the same record handled twice) and for the self-heal notice.

    Formerly test_alert_dedup.py.
    """
    import sys, types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    from ark_relay.features.alarm import handle
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


def _part_first_error_alert():  # noqa: C901 - the whole body of the file this part was
    """Every WARNING / ERROR the relay logs is pushed to the group, every time, at once;
nothing is dropped when the group refuses; nothing loops back from the push path.

The user's order of 2026-10-06 (full words in docs/NOTIFICATIONS.md, the 🩺 row)
ends with the rule itself: 「不论多少次什么错误都要发」. Before that:
one push per new ERROR kind (state/errsigs.json), WARNINGs to the daily report only,
at most 3 pushes an hour, nothing while the machine was going down - each of which
is checked here as gone.
2026-09-17 21:21:28: 「AUTO-MAS 拉起后 45 秒内接口仍不通」 was one ERROR line that
nobody read; the 21:30 queue never ran and the first alarm came at 21:55.

    Formerly test_first_error_alert.py.
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.alarm import alertlog, errwatch, known_fixed
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


    def section_5b():
        print("\n[the queue file on disk is unreadable at start: the group hears it]")
        # Until 2026-10-10 the alarms queued before the restart were lost with no word;
        # until 2026-10-11 a daily-only row said it. errwatch cannot log about itself (its
        # own records never come back in), so the lost queue is the new queue's first item.
        # The user's words of 2026-10-11 17:43 are in relay/USER-SWITCHES.txt's header.
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
        # The 库街区 keys left the registry once that message became log.info
        # (audit s8 #5, the _part_known_fixed_live part): logged as a WARNING anyway,
        # it is an ordinary relay error.
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
        print("\n[自己好了的：只进日报，不进群（用户 2026-10-06 05:07）]")
        R = TMP / "recovered"
        n = _Notifier()
        h = make(n, R)
        lg.warning("手机通道断了 20 秒，自己重新连上了", extra=errwatch.recovered())
        lg.warning("维护公告：终末地 取不到")              # still broken: pushed
        _wait(n, 1)
        check("没好的照报，自己好了的不报", [b for _, b, _ in n.sent if "重新连上" in b], [])
        check("没好的那条进群", len(n.sent), 1)
        rows = faults(R)
        got = [r for r in rows if "重新连上" in str(r.get("line"))]
        check("自己好了的记进当天的报错表", bool(got) and got[0].get("recovered"), True)
        check("日报那一段写「自己好了，只进日报」", "自己好了，只进日报" in errwatch.daily_section(R, TODAY))
        drop(h)


    section(section_recovered)


    def section_recovered_push_thread():
        print("\n[推送途中自己好了的（推送重试送到了）：照样记一条「自愈待查」红项]")
        # notify.py:_post logs a transport failure that went through on a later attempt
        # with errwatch.recovered(); on the errwatch push thread that record used to be
        # dropped by the thread-name filter before the recovered check (audit 10-12 #8).
        from ark_relay.core import techlog
        R = TMP / "recovered-push" / "state"
        n = _Notifier()
        h = make(n, R)
        pushlog = notify_mod.log

        def on_push_thread():
            pushlog.warning("推送传输失败 1 次，第 2 次送到了: 推送线程自愈样例", extra=errwatch.recovered())
            pushlog.warning("企业微信机器人推送失败: 推送线程样例")       # not recovered: still not looped back
        t = threading.Thread(target=on_push_thread, name=errwatch.PUSH_THREAD + "-z")
        t.start()
        t.join()
        _wait(n, 0)
        check("推送线程上的报错不回到推送里", n.sent, [])
        got = [r for r in faults(R) if "推送线程自愈样例" in str(r.get("line"))]
        check("推送线程上自己好了的记进当天的报错表", bool(got) and got[0].get("recovered"), True)
        red = [x for f in sorted(techlog.tech_dir(R).glob("*.md"))
               for _, x in techlog.unhandled(f.read_text(encoding="utf-8")) if "推送线程自愈样例" in x]
        check("推送线程上自己好了的写一条「自愈待查」红项", [techlog.SELF_HEAL in x for x in red], [True])
        # audit 11-08 C-05: counted (errkinds keeps a trace of a fault on the push path), never as recovered.
        check("没好的那条记进报错表，但不记成自己好了",
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
    from ark_relay.features.report import report
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
    print("all checks passed")


def _part_failure_alert():
    """The immediate failure alert, and the three marks nobody ever read back.

`core.format_failure` builds the message the user gets on his phone the moment
a run fails - the single most-read thing the relay produces - and no test had
ever called it. Neither had `State.interim_sent` nor
`State.mark_banner_announced`, both of which are one half of a writer/reader
pair: a mark written under one key and read back under another silently means
"never sent", and the symptom is not an error but a missing report, or the
same banner announced every hour.

What is pinned here:

* A run whose duration came from the filename must not print a duration as
  fact. That fallback is hours wrong on this install, and it is exactly the
  class of run (「未捕获到日志」) most likely to end up in a failure alert.
* Which step broke has to be visible. The daily report of 2026-08-27 lost the
  words 「失败于」 and became unreadable - a bare list of task names that could
  equally have been the list of things that ran.
* Every mark survives a restart, because the machine is hard power-cut twice a
  day and an in-memory mark is not a mark.

    Formerly test_failure_alert.py.
    """
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    """One alarm must never flood the group (2026-11-05 北京 10:56).

runwatch's overrun alarm took runtime-snapshot's task `log` as 「AUTO-MAS 最后一句」, but that field
is the task's whole log (38151 characters in 343 lines that morning). WeComBot split the text into
44 messages and sent 20 before the robot's 20-a-minute cap refused the 21st (45009); the user saw
20 pieces of log in the group, and every other alarm of that minute failed.

Checked here: runwatch.last_log_line keeps only the last non-empty line, cut to 200 characters;
the overrun text built from such a log stays one message; WeComBot sends at most MAX_PARTS
messages for any text (many lines or one huge line), the last ending with a plain note, and
leaves short and two-part texts exactly as before.

    Formerly test_group_long_alarm.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import notify, texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.run import runwatch


    # A task log shaped like the 11-05 one: 343 lines, about 38000 characters, mostly Chinese.
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

    print("all checks passed" if not fails else f"FAILED: {fails}")


def _part_uptime_alarm():
    """The shutdown floor is an alarm: once 「开机不够久」 passes, the relay judges again.

2026-10-01: the relay restarted at 18:03:57, judged 「开机不够久」 at 18:04:15
(floor 600 s) and then slept until its next alarm, 21:30. Nothing judged again
when the floor passed at 18:13:57.

    Formerly test_uptime_alarm.py.
    """
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    """errwatch's per-day counts survive the switch to the next day.

Audit 2026-10-13 s7 #7: the count cache holds one day, and _count saves a
repeat only every SAVE_EVERY seconds; the first record after midnight replaced
the cache and the previous day's unsaved repeat was lost, so the daily report's
「中继自己记下的报错」 undercounted.

    Formerly test_errwatch_midnight_counts.py.
    """
    import json
    import logging
    from datetime import datetime


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.alarm import errwatch


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

    print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")


def _part_known_fixed_live():
    """Every known_fixed entry can still match: its message is logged at WARNING or above.

errwatch only sees WARNING and above, so a known_fixed key whose message is now
logged at INFO is dead weight - a recurrence of that kind could never be tagged.
The two 「库街区官方资讯里没找到 … 版本资讯帖」 keys were such entries after that
message became log.info (banners/wuwa_posters.py), audit s8 #5.

For each key: the fixed text before its first blanked part (# / <path> / ...) must
appear inside a .warning( / .error( / .exception( / .critical( call somewhere under
ark_relay/.

    Formerly test_known_fixed_live.py.
    """
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from ark_relay.features.alarm import known_fixed


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

    print("\n" + (f"✗ {len(fails)} failed" if fails else "all checks passed"))


def _part_unresolved():
    """A MAA / MaaEnd problem the relay could not fix goes to the group - every time.

From 13:07 to 15:38 on 2026-10-05 such failures went to the daily report only,
and the group heard of a game only after a whole day without a good run
(dayfail.py, now removed). The user, 15:38: 「为啥群里不响？你们不是没处理好吗？
你这样不会错失第一时间修复的那个吗。」 Until 2026-10-06 a shift then rang at most
once, a MaaEnd round short of only 自动采集 / 应急理智加强剂 (engine.SOFT_FAILS)
stayed in the daily report, and runs started by hand at AUTO-MAS and MAA failures
on the update day were never pushed; the user's order of 2026-10-06, 「不论多少次
什么错误都要发」, ended all four, and put in the group as well a failure the make-up
got past, could-not-enter on an official notice and MAA short of sanity. At 05:07
that day he took the make-up that got past it back out of the group: 「报错后自己好了
的，只进日报、不进群。」 Pinned here, against a queue config shaped like AUTO-MAS's own
(早班 09:00 MAA + MaaEnd + OK-WW, 晚班 21:30 MAA):

* 早班 failed -> held for its make-up; the make-up failed too -> an alarm naming
  the game, the shift, what came of the make-up, where it failed and the
  evidence link; another 早班 failure rings again; a 晚班 failure (the day's
  make-up spent) rings for 晚班, and so does the next one;
* the make-up went through -> nothing pushed; the daily report's make-up line says
  「失败过，补跑后走通了」 with where it failed;
* a MAA failure the make-up is not for (it had fought already) -> one alarm,
  with the reason no make-up ran;
* every 「没干完」 rings, a failure of the same shift too; MaaEnd short of only
  自动采集 / 应急理智加强剂 rings like any other, and fails into the make-up path;
* a run started by hand and a MAA failure on the update day ring at once;
* could not enter (official notice), MAA short of sanity and a failure cut short by
  the red button (his own 停一切) ring at once, not held;
* a push that did not go out is tried again on the next tick, and the same
  record is never pushed twice;
* the whole-day alarm is gone.

    Formerly test_unresolved.py.
    """
    import json
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from ark_relay.features.alarm import handle, unresolved
    from ark_relay.features.makeup import makeup
    from ark_relay.features.verify import outcome
    from ark_relay.features.report import report
    from ark_relay.core import texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import route_of
    from ark_relay.features.selfcheck import machinecheck as _mc
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

    print("\n[补跑走通：自己好了，不进群，只进日报（用户 2026-10-06 05:07）]")
    e = build()
    handle._handle(e, rec("MAA", at(9, 5)))
    e._flush_pending()
    makeup.maybe_run(e, at(10, 5))
    handle._handle(e, rec("MAA", at(10, 6), ok=True))
    e._flush_pending()
    check("补跑记成走通", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.OK)
    check("什么都没推（群、Server酱都没有）", e.notifier.sent, [])
    check("日报的补跑那一行说失败过、补跑后走通了",
          report.makeup_line(e.cfg.state_dir, D), "明日方舟失败后自动补跑，走通了（原来失败于：开始唤醒）")
    check("不再压着", (dict(e._pending), dict(e._recovered)), ({}, {}))
    e._flush_pending()
    check("下一轮也不推", e.notifier.sent, [])

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
    # 2026-10-12: six reset buy lists went out as 「终末地早班没干完」 / 「有 1 项没干成」.
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
    # Held until the same AUTO-MAS task's later attempts decide (handle._hold_hand_started,
    # 2026-10-16), never handed to the make-up.
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
    # da99a04d (2026-10-06): a failure cut short by 停一切 is pushed, saying so - it did not recover.
    check("红按钮停的失败：进群，不压着", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
    check("…说是停一切停掉的", last_body(e).startswith("这一趟是停一切停掉的（停一切）"), True)
    # Audit 2026-10-13 s7 #2: a held failure a person's own run got past was dropped
    # with one INFO line. A person fixing it is not "fixed itself": pushed, saying so.
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
    check("前一趟没证据、重试那趟补上了：不推", alarms(e), [])
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), ok=True, raw={"annihilation": "Annihilation"}))
    check("明日方舟剿灭没有进度行：进群", alarms(e), [texts.unverified_alarm("明日方舟", "早班", 1)])
    check("写出剿灭和原因", "剿灭 程序说做完了" in last_body(e) and "剿灭模式 x/y" in last_body(e), True)
    e = build()
    handle._handle(e, rec("MAA", at(9, 5), ok=True, raw={"annihilation": "Annihilation", "maa_sanity_short": True}))
    check("理智不够没打剿灭是正常状态：不推", alarms(e), [])
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
    """前置条件不满足时，绝不许静默变成「全绿」。

2026-08-30 一次排查里同一个形状的 bug 出现了三次：
  1. `_verify_outcome` 压根没有 MAA 分支，走到就 return None（=全干成）
  2. `_okww_nest_expected` 读不到配置返回 False，和「配置说不用打」不可区分，
     残象聚落那一项**整个消失**
  3. 我给 MAA 加核对时，`_maa_app_log` 读不到日志返回 ""，
     空文本喂给 `maa_checks` 全部判过——又一次假全绿
外加 `_verify_outcome` 的 except 分支直接 return None：核对自己崩了也报全绿。

这个文件把这四条钉死。

    Formerly test_silent_green_guards.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.verify import outcome
    from ark_relay.features.alarm.handle import _maa_app_log, _okww_nest_expected

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


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

        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


if __name__ == "__main__":
    sys.exit(run_parts([_part_alert_dedup, _part_first_error_alert, _part_failure_alert, _part_group_long_alarm, _part_uptime_alarm, _part_errwatch_midnight_counts, _part_known_fixed_live, _part_unresolved, _part_silent_green_guards]))
