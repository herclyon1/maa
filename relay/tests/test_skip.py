"""Skipping a queue: a failed push, flag collisions, lost and kept receipts, sitting out, the shutdown .bat error.

One part per former file, each run on its own (tests/_parts.py): test_skip_failed_pushed.py, test_skip_flag_collision.py, test_skip_receipt_lost.py, test_skip_receipts.py, test_skip_sat_out_1101.py, test_skip_shutdown_bat_error.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmp  # loaded before the parts: its atexit cleanup and env default stay
from _parts import run_parts

_BEFORE_THE_PARTS = (_tmp,)


def _part_skip_failed_pushed():
    """A skip of a queue that did not take effect, or whose restore failed, reaches the group.

engine._observe_modes sent every message of modes.process_skip under texts.SKIP_MODE,
which notify.route_of sends to the log only - so 「跳过「早班」失败：…——没生效，今天
照常跑」 (the queue the user wanted skipped runs anyway) and 「跳过「早班」后恢复失败：…」
(the queue stays switched off) never reached anyone. The user's rule, 2026-10-06:
「不论多少次什么错误都要发」 - a failure that did not recover goes to the group every
time. The acknowledgements of a skip that took stay on the log route.

Driven through a real Engine tick step with modes.process_skip's real code; only
queues.apply (AUTO-MAS's answer) and plan.schedule are faked.

    Formerly test_skip_failed_pushed.py.
    """
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    from ark_relay.core import engine as eng_mod
    from ark_relay.features.modes import modes
    from ark_relay.core import texts
    from ark_relay.core import plan as _plan
    from ark_relay.features.schedule import queues as _q
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import route_of

    fails = []


    def check(label, got, want=True):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
        if not ok:
            fails.append(label)


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            return []


    class Src:
        def fetch(self, seen):
            return []


    ANSWER = {"早班": (True, "调度程序已确认")}
    live = {"早班": True}


    def fake_apply(d, q, enabled):
        ok, detail = ANSWER[q]
        if ok:
            live[q] = enabled
        return ok, detail


    _real = _q.apply, _plan.schedule
    _q.apply = fake_apply
    _plan.schedule = lambda d: [{"name": q, "times": ["09:00"]} for q in live if live[q]]


    def engine():
        sd = tmpdir()
        cfg = Config()
        cfg.state_dir = sd
        cfg.automas_dir = tmpdir()
        live["早班"] = True
        return eng_mod.Engine(cfg, source=Src(), state=State(sd), notifier=Notes())


    def pushed(e):
        return [(t, a, route_of(t, alert=a)) for t, b, a in e.notifier.sent]


    today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    try:
        print("[跳过没生效（调度程序没接受）：进群一条，说今天照常跑]")
        e = engine()
        ANSWER["早班"] = (False, "队列「早班」定时关闭没生效：调度程序里它仍是开启")
        modes.add_day_queue(e.state.dir, today, "早班")
        e._observe_modes()
        got = pushed(e)
        check("一条报警，走群", [(a, r) for _, a, r in got], [(True, "group")])
        check("正文就是那句失败", any("没生效，今天照常跑" in b for _, b, _ in e.notifier.sent), True)
        e._observe_modes()
        check("下一轮同一句不再推（同一个错，一次）", len(e.notifier.sent), 1)

        print("[跳过生效了：确认那条照旧只进日志]")
        e = engine()
        ANSWER["早班"] = (True, "调度程序已确认")
        modes.add_day_queue(e.state.dir, today, "早班")
        e._observe_modes()
        got = pushed(e)
        check("一条，标题是跳过模式，不带报警", [(t, a) for t, a, _ in got], [(texts.SKIP_MODE, False)])
        check("走日志", [r for _, _, r in got], ["log"])

        print("[推送没送出去：记一条 WARNING，带原话]")
        e = engine()
        ANSWER["早班"] = (False, "调度程序没有应答")
        modes.add_day_queue(e.state.dir, today, "早班")
        tries = []
        e.notifier.send = lambda t, b="", alert=False, **k: (tries.append((t, alert)), ["群机器人发送失败"])[1]
        import logging
        seen = []
        h = type("H", (logging.Handler,), {"emit": lambda self, r: seen.append((r.levelno, r.getMessage()))})()
        eng_mod.log.addHandler(h)
        try:
            e._observe_modes()
        finally:
            eng_mod.log.removeHandler(h)
        check("推了，没送出", tries, [(eng_mod.SKIP_FAILED, True)])
        check("记一条 WARNING，带那句失败（错误推送会把它补推进群）",
              [lvl for lvl, m in seen if "没生效，今天照常跑" in m and "没推出去" in m], [logging.WARNING])
    finally:
        _q.apply, _plan.schedule = _real

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_skip_flag_collision():
    """两个功能共用「skip-」这个前缀，清理陈旧标记时把对方扫掉了。

「某天跳过队列」写 skip-<YYYY-MM-DD>.flag，「下次跑完不关机」写
skip-next-shutdown.flag，两者住同一个 state 目录。process_skip 每一拍
（30 秒）都会清理「不是今天的」skip-*.flag，glob 把后者也匹配上，于是
人在手机上按下开关，半分钟内就被删掉，日志还写「未曾生效（当天机器
没开机）」——而机器正开着。发现于 2026-08-31：按下后回读 True，40 秒后
再读已经没了。

    Formerly test_skip_flag_collision.py.
    """
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.modes import modes
    from ark_relay.features.schedule import queues as _q
    from ark_relay.core import plan as _plan
    from ark_relay.core.statestore import StateStore
    from ark_relay.core.config import SERVER_TZ
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    STATE = tmpdir() / "state"; STATE.mkdir(parents=True)
    NOW = datetime(2026, 8, 31, 12, 44, tzinfo=SERVER_TZ)

    fails = []
    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
        if not ok:
            fails.append(label)

    print("\n[the bug] 清理陈旧队列标记不许碰「下次跑完不关机」")
    modes.set_skip_shutdown(STATE, True)
    check("按下之后确实开着", modes.skip_armed(STATE), True)
    modes.process_skip(STATE, None, NOW)
    check("扫过一拍还在", modes.skip_armed(STATE), True)
    for _ in range(5):                      # 引擎每 30 秒一拍，多扫几次
        modes.process_skip(STATE, None, NOW)
    check("扫过六拍还在", modes.skip_armed(STATE), True)
    check("用掉之后才消失", modes.take_skip(STATE), True)
    check("用完就没了", modes.skip_armed(STATE), False)

    print("\n[没有回归] 真正过期的队列标记照旧清掉")
    store = StateStore(STATE)
    store.set("queues", "skip_day:2026-08-20", "Evening-MAA")
    modes.set_skip_shutdown(STATE, True)
    msgs = modes.process_skip(STATE, None, NOW)
    check("过期的队列标记被清除", store.get("queues", "skip_day:2026-08-20"), None)
    check("而且说了这件事", any("过期的跳过标记" in m for m in msgs), True)
    check("关机标记没受牵连", modes.skip_armed(STATE), True)

    print("\n[边界] 名字长得像日期但不是日期的，不当队列标记处理")
    for bogus in ("next_shutdown", "2026-13-40", "", "pending"):
        check(f"{bogus!r} 不是日期", modes._is_day(bogus), False)
    check("2026-08-20 是日期", modes._is_day("2026-08-20"), True)

    print("\n[2026-09-30] 同一天跳两个队列：两个都停、取消其一不动另一个、过点各自恢复、跨日清空")
    S3 = tmpdir() / "state"; S3.mkdir(parents=True)
    AM = Path("/tmp/automas")
    T0 = datetime(2026, 9, 30, 8, 50, tzinfo=SERVER_TZ)
    D3 = T0.strftime("%Y-%m-%d")
    live = {"早班": True, "晚班": True}
    def fake_apply(d, q, enabled):
        live[q] = enabled
        return True, "ok"
    _real_apply, _real_sched = _q.apply, _plan.schedule
    _q.apply = fake_apply
    _plan.schedule = lambda d: [{"name": q, "times": {"早班": ["09:00"], "晚班": ["21:00"]}[q]}
                               for q in live if live[q]]
    try:
        # the machine's state at deploy time: 早班 engaged in the old one-dict shape
        StateStore(S3).set("queues", "skip_restore", {"queue": "早班", "day": D3, "last_time": "09:00"})
        live["早班"] = False
        check("旧格式恢复标记照读", modes.skipped_today_all(S3, T0), ["早班"])
        modes.add_day_queue(S3, D3, "晚班")
        check("再跳晚班：两个都算今天跳过", modes.skipped_today_all(S3, T0), ["晚班", "早班"])
        check("存的还是单个字符串（只有一个未生效）",
              StateStore(S3).get("queues", f"skip_day:{D3}"), "晚班")
        msgs = modes.process_skip(S3, AM, T0)
        check("晚班停用了", live["晚班"], False)
        check("早班没被提前恢复", live["早班"], False)
        check("两条恢复标记都在（列表）",
              sorted(m["queue"] for m in StateStore(S3).get("queues", "skip_restore")), ["早班", "晚班"])
        check("晚班的跳过标记用掉了", StateStore(S3).get("queues", f"skip_day:{D3}"), None)
        ok, _ = modes.unskip(S3, AM, "晚班", T0)
        check("取消晚班：晚班立刻恢复、早班仍停", (ok, live["晚班"], live["早班"]), (True, True, False))
        check("剩下早班一条，存回单个 dict（旧版也读得懂）",
              StateStore(S3).get("queues", "skip_restore"), {"queue": "早班", "day": D3, "last_time": "09:00"})
        # two flags, same tick
        modes.add_day_queue(S3, D3, "晚班")
        ok, msg = modes.unskip(S3, AM, "中班", T0)
        check("取消没跳过的：两个名字都说出来", (ok, "早班" in msg and "晚班" in msg), (False, True))
        modes.process_skip(S3, AM, T0)
        check("又停了晚班", live["晚班"], False)
        modes.process_skip(S3, AM, datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ))
        check("早班过点恢复，晚班还没到点", (live["早班"], live["晚班"]), (True, False))
        modes.process_skip(S3, AM, datetime(2026, 9, 30, 21, 31, tzinfo=SERVER_TZ))
        check("晚班过点也恢复，标记清空",
              (live["晚班"], StateStore(S3).get("queues", "skip_restore")), (True, None))
        # two flags engage in one tick; a bad entry in the list is dropped alone
        StateStore(S3).set("queues", f"skip_day:{D3}", ["早班", "晚班"])
        modes.process_skip(S3, AM, T0)
        check("同一拍两个都停", (live["早班"], live["晚班"]), (False, False))
        StateStore(S3).set("queues", "skip_restore",
                           [*StateStore(S3).get("queues", "skip_restore"), "坏的"])
        msgs = modes.process_skip(S3, AM, datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ))
        check("坏的那条单独清掉并说了", any("损坏" in m for m in msgs), True)
        check("晚班的标记没被一起清掉", modes.skipped_today_all(S3, T0), ["晚班"])
        # cross-day: yesterday's unengaged list is cleared
        StateStore(S3).set("queues", "skip_day:2026-09-29", ["早班", "晚班"])
        msgs = modes.process_skip(S3, AM, T0)
        check("跨日：昨天没生效的一串清掉",
              (StateStore(S3).get("queues", "skip_day:2026-09-29"), any("2026-09-29" in m for m in msgs)),
              (None, True))
        StateStore(S3).set("queues", f"skip_day:{D3}", [])
        check("空列表不当默认队列", modes.skipped_today_all(S3, T0), ["晚班"])
        # a skip pressed on the phone while the engine is disabling another queue
        S4 = tmpdir() / "state"; S4.mkdir(parents=True)
        live.update({"早班": True, "晚班": True})
        def apply_while_pressed(d, q, enabled):
            live[q] = enabled
            if q == "早班" and not enabled:
                modes.add_day_queue(S4, D3, "晚班")
            return True, "ok"
        _q.apply = apply_while_pressed
        StateStore(S4).set("queues", f"skip_day:{D3}", "早班")
        modes.process_skip(S4, AM, T0)
        check("停早班途中拨了晚班：晚班的跳过没被写掉",
              StateStore(S4).get("queues", f"skip_day:{D3}"), "晚班")
        modes.process_skip(S4, AM, T0)
        check("下一拍晚班也停了", (live["早班"], live["晚班"]), (False, False))
    finally:
        _q.apply, _plan.schedule = _real_apply, _real_sched


    print("\n[2026-09-15] skipped_today / unskip：手机页的队列开关要能读到、也能关回去")
    S2 = tmpdir() / "state"; S2.mkdir(parents=True)
    DAY = NOW.strftime("%Y-%m-%d")
    check("没跳过时是 None", modes.skipped_today(S2, NOW), None)
    StateStore(S2).set("queues", f"skip_day:{DAY}", "早班")
    check("标记写下就读得到", modes.skipped_today(S2, NOW), "早班")
    ok, msg = modes.unskip(S2, None, "晚班", NOW)
    check("取消别的队列不算", ok, False)
    ok, msg = modes.unskip(S2, None, "早班", NOW)
    check("标记阶段取消：成功", ok, True)
    check("标记没了", modes.skipped_today(S2, NOW), None)
    # engaged stage: marker present, queue disabled in AUTO-MAS - the restore goes through queues.apply
    calls = []
    _real_apply = _q.apply
    _q.apply = lambda d, q, enabled: (calls.append((q, enabled)) or (True, "ok"))
    try:
        StateStore(S2).set("queues", "skip_restore", {"queue": "早班", "day": DAY, "last_time": "09:00"})
        check("已生效阶段也读得到", modes.skipped_today(S2, NOW), "早班")
        ok, msg = modes.unskip(S2, Path("/tmp/automas"), "早班", NOW)
        check("已生效阶段取消：成功", ok, True)
        check("立刻把队列重新启用", calls, [("早班", True)])
        check("恢复标记清掉了", modes.skipped_today(S2, NOW), None)
        ok, msg = modes.unskip(S2, Path("/tmp/automas"), "早班", NOW)
        check("再取消一次：如实说本来就没跳过", ok, False)
    finally:
        _q.apply = _real_apply

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_skip_receipt_lost():
    """A skip that failed stays a failure when its red receipt could not be written.

Audit s1 (outside its scope, modes.py:467, 10-13): engine.skip_failed tells a failed
skip from an acknowledgement only by the red receipt modes writes with the same words.
_skip_receipt swallowed a write failure, so the failure went out on the quiet
acknowledgement route (texts.SKIP_MODE) instead of the SKIP_FAILED group alarm, and
the phone page kept showing the press's green 「已记下」.

    Formerly test_skip_receipt_lost.py.
    """
    import sys
    from pathlib import Path

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    from _tmp import tmpdir

    from ark_relay.core import engine
    from ark_relay.features.modes import modes

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
        if not ok:
            fails.append(label)


    sd = tmpdir()
    other = tmpdir()
    real_add = modes.add_receipt


    def broken_add(*a, **k):
        raise OSError(28, "No space left on device")


    modes.add_receipt = broken_add
    try:
        msg = modes._engage_failed(sd, "早班", "调度程序没回应")
    finally:
        modes.add_receipt = real_add

    check("nothing reached the receipts file", (sd / modes._RECEIPTS).exists(), False)
    check("the failure is still a failure for the engine", engine.skip_failed(sd, msg), True)
    check("the phone page lists it as red", [r["ok"] for r in modes.receipts(sd) if r["text"] == msg], [False])
    check("another state folder does not see it", engine.skip_failed(other, msg), False)

    ok_msg = "今天（2026-10-13）跳过队列「晚班」：已临时停用，过后自动恢复"
    modes._skip_receipt(sd, "skip_today", True, ok_msg)
    check("a written green receipt is still an acknowledgement", engine.skip_failed(sd, ok_msg), False)

    if fails:
        print("FAIL:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_skip_receipts():
    """Skip-queue outcomes reach the phone page's receipts, and a failed skip lets go of the day.

2026-09-30 (检查, BOARD/evidence/回执显示-0930 row 2a): process_skip only returned
strings, which the engine pushed as notifications. Nothing went to the receipts
the phone page shows, and on failure _maybe_engage kept the day flag "to retry on
the next tick", so the snapshot's 「今天跳过队列」 still listed the queue and the
page showed the switch as skipped and applied while the queue was going to run.

Now: a failed engage drops the flag and writes a red receipt saying the skip did
not take and the queue runs today; a successful one writes a green receipt whose
text is queues.apply's own answer (「调度程序已确认」 only when the backend read
the value back). Restores write receipts too. The engine pushes a fresh snapshot
after a skip step so the receipt reaches the page without waiting for a refresh.

    Formerly test_skip_receipts.py.
    """
    import os
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    from ark_relay.features.modes import modes
    from ark_relay.core import plan as _plan
    from ark_relay.features.schedule import queues as _q
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))
        if not ok:
            fails.append(label)


    T0 = datetime(2026, 9, 30, 8, 51, tzinfo=SERVER_TZ)
    DAY = T0.strftime("%Y-%m-%d")
    AM = Path("/tmp/automas-not-used")
    ANSWER = {"早班": (True, ""), "晚班": (True, "")}
    live = {"早班": True, "晚班": True}


    def fake_apply(d, q, enabled):
        ok, detail = ANSWER[q]
        if ok:
            live[q] = enabled
        return ok, detail


    _real_apply, _real_sched = _q.apply, _plan.schedule
    _q.apply = fake_apply
    _plan.schedule = lambda d: [{"name": q, "times": {"早班": ["09:00"], "晚班": ["21:00"]}[q]}
                               for q in live if live[q]]


    def fresh():
        s = tmpdir() / "state"
        s.mkdir(parents=True)
        live.update({"早班": True, "晚班": True})
        return s


    def rcpt(s):
        return [(r["action"], r["ok"], r["text"]) for r in modes.receipts(s)]


    try:
        print("[a] 生效时失败：回执红、说今天照常跑、当天跳过标记清掉、快照不再列它")
        S = fresh()
        ANSWER["早班"] = (False, "队列「早班」定时关闭没生效：调度程序里它仍是开启")
        modes.add_day_queue(S, DAY, "早班")
        msgs = modes.process_skip(S, AM, T0)
        r = rcpt(S)
        check("一条回执", len(r), 1)
        check("动作是 skip_today（手机开关发的那个）", r and r[0][0], "skip_today")
        check("ok=false", r and r[0][1], False)
        check("回执带队列名、说没生效、今天照常跑",
              bool(r) and all(w in r[0][2] for w in ("「早班」", "没生效", "今天照常跑")), True)
        check("回执带上调度程序的原话", bool(r) and "仍是开启" in r[0][2], True)
        check("推送也是同一句", bool(r) and r[0][2] in msgs, True)
        check("当天跳过标记没了", StateStore(S).get("queues", f"skip_day:{DAY}"), None)
        check("快照的今天跳过队列不再列它", modes.skipped_today_all(S, T0), [])
        check("没留恢复标记", StateStore(S).get("queues", "skip_restore"), None)
        check("队列还开着", live["早班"], True)
        msgs2 = modes.process_skip(S, AM, T0)
        check("下一拍不再重试、不再出消息", msgs2, [])
        check("下一拍不多写回执", len(modes.receipts(S)), 1)

        print("\n[a2] 没有 AUTO-MAS 目录：同样红回执、标记清掉")
        S = fresh()
        modes.add_day_queue(S, DAY, "晚班")
        msgs = modes.process_skip(S, None, T0)
        r = rcpt(S)
        check("一条红回执", [(a, ok) for a, ok, _ in r], [("skip_today", False)])
        check("说了今天照常跑", bool(r) and "今天照常跑" in r[0][2] and "「晚班」" in r[0][2], True)
        check("标记清掉", modes.skipped_today_all(S, T0), [])

        print("\n[a3] 两个队列一个成一个败：只丢败的那个")
        S = fresh()
        ANSWER["早班"] = (False, "队列「早班」定时关闭失败：调度程序报错（超时）")
        ANSWER["晚班"] = (True, "队列「晚班」：定时关闭（调度程序已确认）")
        modes.add_day_queue(S, DAY, "早班")
        modes.add_day_queue(S, DAY, "晚班")
        modes.process_skip(S, AM, T0)
        check("今天跳过的只剩晚班", modes.skipped_today_all(S, T0), ["晚班"])
        check("两条回执：早班红、晚班绿", [(ok, "早班" in t) for _, ok, t in rcpt(S)],
              [(False, True), (True, False)])

        print("\n[b] 生效成功：绿回执，文字是 queues.apply 自己的话")
        S = fresh()
        ANSWER["早班"] = (True, "队列「早班」：定时关闭（调度程序已确认）")
        modes.add_day_queue(S, DAY, "早班")
        modes.process_skip(S, AM, T0)
        r = rcpt(S)
        check("一条绿回执 skip_today", [(a, ok) for a, ok, _ in r], [("skip_today", True)])
        check("带「调度程序已确认」", bool(r) and "队列「早班」：定时关闭（调度程序已确认）" in r[0][2], True)
        check("仍算今天跳过（恢复标记在）", modes.skipped_today_all(S, T0), ["早班"])

        print("\n[b2] 走改文件那条路（调度程序没开）：不说调度程序已确认")
        S = fresh()
        ANSWER["早班"] = (True, "队列「早班」：定时关闭（备份 QueueConfig.bak-20260930-085100.json）")
        modes.add_day_queue(S, DAY, "早班")
        modes.process_skip(S, AM, T0)
        r = rcpt(S)
        check("绿回执", [(a, ok) for a, ok, _ in r], [("skip_today", True)])
        check("没有「调度程序已确认」", bool(r) and "调度程序已确认" in r[0][2], False)
        check("带备份文件名（apply 的原话）", bool(r) and "备份" in r[0][2], True)

        print("\n[c] 过点恢复成功：unskip_today 绿回执")
        ANSWER["早班"] = (True, "队列「早班」：定时开启（调度程序已确认）")
        modes.process_skip(S, AM, datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ))
        r = rcpt(S)
        check("第二条是 unskip_today 绿", r[-1][:2] if r else None, ("unskip_today", True))
        check("文字带队列名和 apply 的原话", bool(r) and "「早班」" in r[-1][2] and "调度程序已确认" in r[-1][2], True)

        print("\n[c2] 过点恢复失败：unskip_today 红回执，每拍重试但回执只写一次")
        S = fresh()
        ANSWER["早班"] = (True, "队列「早班」：定时关闭（调度程序已确认）")
        modes.add_day_queue(S, DAY, "早班")
        modes.process_skip(S, AM, T0)
        ANSWER["早班"] = (False, "队列「早班」定时开启没生效：调度程序里它仍是关闭")
        later = datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ)
        for _ in range(5):
            modes.process_skip(S, AM, later)
        r = rcpt(S)
        check("一绿一红", [(a, ok) for a, ok, _ in r], [("skip_today", True), ("unskip_today", False)])
        check("红的说了恢复失败和原话", bool(r) and "恢复失败" in r[-1][2] and "仍是关闭" in r[-1][2], True)
        check("恢复标记还在（下拍再试）", modes.skipped_today_all(S, T0), ["早班"])
        ANSWER["早班"] = (True, "队列「早班」：定时开启（调度程序已确认）")
        modes.process_skip(S, AM, later)
        check("再试成功补一条绿", rcpt(S)[-1][:2], ("unskip_today", True))

        print("\n[d] 回执文字过人话闸门")
        for _, _, t in rcpt(S):
            check(t[:30], texts.plain(t), [])
    finally:
        _q.apply, _plan.schedule = _real_apply, _real_sched

    print("\n[e] 引擎：跳过这一步有新消息就把状态推给手机页，同一句不重复推")
    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "h"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import Config
    from ark_relay.core.ledger import State


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []


    class Src:
        def fetch(self, seen):
            return []


    cfg = Config()
    cfg.state_dir = tmpdir()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    pushed = []
    e._push_state = lambda why: pushed.append(why)
    real_ps = modes.process_skip
    modes.process_skip = lambda *a, **k: ["跳过「早班」失败：x——没生效，今天照常跑；要跳过请再按一次"]
    try:
        e._observe_modes()
        check("推了一次状态", len(pushed), 1)
        e._observe_modes()
        check("同一句第二拍不再推", len(pushed), 1)
        modes.process_skip = lambda *a, **k: []
        e._observe_modes()
        check("没消息不推", len(pushed), 1)
        e._push_state = None
        modes.process_skip = lambda *a, **k: ["另一句"]
        e._observe_modes()
        check("没接手机通道（None）也不出错", len(e.notifier.sent), 2)
    finally:
        modes.process_skip = real_ps

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_skip_sat_out():
    """A queue skipped on purpose stays skipped for that day's checks after its restore.

2026-11-01: 晚班 was skipped (skip_today), the machine stayed on, the restore re-enabled the
queue at 22:03:45 (Beijing) and at 22:03:47 the missed-run check pushed 「🔌 晚班 没有运行」;
the overdue check and the shutdown wait also still counted 晚班 as missing MAA.

    Formerly test_skip_sat_out_1101.py.
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
    STATE = TMP / "state"
    STATE.mkdir()
    HIST = TMP / "history"
    HIST.mkdir()

    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {"Info": {"Name": "晚班", "TimeEnabled": True},
               "SubConfigsInfo": {
                   "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
                   "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA-v5.1.0-win-x64"},
               "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": "arknights"}}}}}}),
        encoding="utf-8")

    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.core.engine import Engine
    from ark_relay.features.modes import modes
    from ark_relay.features.schedule import queues as _q
    from ark_relay.features.shutdown import shutdown

    sent = []


    class FakeNotifier(Notifier):
        def send(self, title, body, *, alert=False, daily=False):
            sent.append((title, alert))
            return []


    cfg = Config()
    E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
    E._boot_time = lambda now: at(8, 0)

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
        if not ok:
            fails.append(label)


    def at(hh, mm):
        return datetime(2026, 11, 1, hh, mm, 45, tzinfo=SERVER_TZ)


    DAY = "2026-11-01"


    def reset():
        sent.clear()
        E._missed_alerted.clear()
        E.state.store.pop("marks", f"alerted:{DAY}")
        E.state.store.pop("queues", f"skip_done:{DAY}")


    print("[control] not skipped: 22:03 with no 21:30 record still alarms")
    reset()
    E._check_missed_runs(at(22, 3))
    check("alarms", len(sent), 1)

    print("\n[the 11-01 false alarm] skipped, engaged, restored after the slot: silent")
    reset()
    real_apply = _q.apply
    _q.apply = lambda d, q, enabled: (True, "")
    try:
        modes.add_day_queue(STATE, DAY, "晚班")
        modes.process_skip(STATE, AUTOMAS, at(21, 8))     # engages: marker for today
        check("engaged", modes.skipped_today_all(STATE, at(21, 9)), ["晚班"])
        modes.process_skip(STATE, AUTOMAS, at(22, 3))     # past the slot: restored, marker dropped
        check("phone switch is off again", modes.skipped_today_all(STATE, at(22, 4)), [])
        check("but the day remembers it sat out", modes.sat_out(STATE, DAY), ["晚班"])
    finally:
        _q.apply = real_apply
    E._check_missed_runs(at(22, 3))
    check("no 「没有运行」", sent, [])

    print("\n[overdue and shutdown] the skipped queue owes no script")
    q = {"name": "晚班", "due": at(21, 30).replace(second=0), "kinds": ["MAA"]}
    check("missing kinds", shutdown._missing_kinds(E, q, []), [])

    print("\n[only that day] tomorrow's 21:30 is checked as usual")
    check("tomorrow not sat out", modes.sat_out(STATE, "2026-11-02"), [])

    print("\nall checks passed" if not fails else f"\n{len(fails)} FAILED: {fails}")
    sys.exit(1 if fails else 0)


def _part_skip_shutdown_bat_error():
    """skip-shutdown.bat shows Python's own error when the status read gives nothing.

The status read sent stderr to nul (`2^>nul`), so every failure - an import error
after a version change, an unreadable state.json - showed the same 「读不出来 ——
中继没装好，或者 Python 路径不对」. Now stderr goes to a temp file that is typed
when the read gives nothing (and the missing-Python case says that). STATE is
also cleared before each read: a menu redraw after a failed read showed the
previous value. No cmd.exe on the Mac, so the file is read as text.

    Formerly test_skip_shutdown_bat_error.py.
    """
    import re
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    bat = (ROOT / "scripts" / "windows" / "skip-shutdown.bat").read_bytes().decode("utf-8").replace("\r\n", "\n")

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    read = next((ln for ln in bat.splitlines() if ln.startswith("for /f") and "skip_armed" in ln), "")
    check("the status read is there", bool(read), True)
    check("its stderr is not thrown away", "2^>nul" in read, False)
    m = re.search(r'2\^>"(%\w+%)"', read)
    check("its stderr goes to a file", bool(m), True)
    var = m.group(1) if m else "%ERRF%"
    empty = bat[bat.find('if "%STATE%"==""'):bat.find(") else (", bat.find('if "%STATE%"==""'))]
    check("an empty read types that file", f'type "{var}"' in empty, True)
    check("the old blanket reason is gone", "中继没装好，或者 Python 路径不对" in empty, False)
    before = bat[:bat.find(read)] if read else ""
    check("STATE is cleared before each read", 'set "STATE="' in before[before.rfind(":menu"):], True)
    check("the error file is cleared before each read", f'del "{var}"' in before[before.rfind(":menu"):], True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_skip_failed_pushed, _part_skip_flag_collision, _part_skip_receipt_lost, _part_skip_receipts, _part_skip_sat_out, _part_skip_shutdown_bat_error]))
