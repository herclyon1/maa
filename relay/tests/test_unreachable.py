"""Unreachable: the evidence, the note pushed now.

One part per former file, each run on its own (tests/_parts.py): test_unreachable_evidence.py, test_unreachable_note_pushed_now.py.
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


def _part_unreachable_evidence():
    """「进不了游戏」needs official evidence; the log's shape alone silences nothing.

The shape (every task fails within 30 s, none completes, >= 3 fails;
collector_maaend.maaend_unreachable) is what the 2026-09-02 maintenance looked
like, but a local fault can look the same. The fixture is the real 2026-09-25
09:55 MaaEnd round (bag full - a local fault: three tasks failed, none
completed), every line kept, with the first two failure times moved to within
30 s of their start (24 s and 28 s, like its third task's real 24 s) - the
same local fault, failing a little faster. No real log in ark-evidence or
relay/tests has the shape at all (0 of 80), so this is the nearest real round.

* shape, no maintenance window, no update notice -> an ordinary failure:
  held, make-up eligible, not booked as 「进不了游戏」, no client update
  registered, and the final alarm goes to the group naming the shape;
* shape + an official maintenance window -> no make-up, a client update
  registered, and one group alarm 「进不了游戏」 naming the official notice. From
  2026-09-02 until 2026-10-06 it was one explanation to Server酱 and no alarm (the
  user's words then: 「检测到服务器在维护时候就跳过，不报警」); his order of 2026-10-06,
  「不论多少次什么错误都要发」, reverses that;
* shape + an official update notice for today -> the same, naming that notice.

    Formerly test_unreachable_evidence.py.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from ark_relay.core import collector, texts
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.features.alarm import handle
    from ark_relay.features.makeup import makeup
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    FIX = ROOT / "tests" / "fixtures" / "maaend_shape_local_fault_2026-09-25.log"


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    class Src:
        def fetch(self, seen):
            return []


    DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    START = DAY.replace(hour=9, minute=55)


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = None
        cfg.maa_dir = None
        cfg.maaend_dir = tmpdir()
        (Path(cfg.maaend_dir) / "debug").mkdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._verify_outcome = lambda r: None
        e._maintenance_today = lambda game: False
        return e


    handle._ship_evidence = lambda eng, rec: ""
    makeup._dispatch = lambda script: (True, "已开跑")
    makeup._kill_game = lambda: None


    def rec_from_fixture():
        raw = collector.parse_maaend_log(FIX)
        return RunRecord(run_id=f"{START:%Y-%m-%d}/endfield/MaaEnd-{START:%H-%M-%S}", script="MaaEnd",
                         user="endfield", started=START, finished=START + timedelta(minutes=4), ok=False,
                         failed_tasks=["🎁赠送干员礼物", "🎱基质刷取", "📅日常奖励领取"], raw=raw)


    def ledger_raw(e, r):
        p = Path(e.cfg.state_dir) / f"ledger-{START:%Y-%m-%d}.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            ent = json.loads(line)
            if ent.get("run_id") == r.run_id:
                return ent.get("raw") or {}
        return None


    def cant_enter_sent(e):
        return any(t == texts.cant_enter("MaaEnd") for t, _b, _a in e.notifier.sent)


    check("反例日志确实是「秒败、零完成」的形状", collector.maaend_unreachable(FIX.read_text(encoding="utf-8")), True)

    print("[形状有、没有官方维护也没有更新公告 → 普通故障]")
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: ""
    e = build()
    r = rec_from_fixture()


    class _Loud(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, rec_):
            self.lines.append(rec_.getMessage())


    loud = _Loud()
    handle.log.addHandler(loud)
    handle._handle(e, r)
    handle.log.removeHandler(loud)
    # Audit 2026-10-13 s7 #5: errwatch pushed this WARNING at once as a relay error
    # while the failure was still held for its retry; the final alarm says it.
    check("held failure: no 「像没进游戏」 WARNING (errwatch would push it now)",
          [m for m in loud.lines if "像没进游戏" in m], [])
    check("压着等补跑", ("MaaEnd", "endfield") in e._pending)
    check("不记成进不了游戏", r.raw.get("maaend_unreachable"), None)
    check("账本上也不是进不了游戏", (ledger_raw(e, r) or {}).get("maaend_unreachable"), None)
    check("补跑有份", makeup.eligible(r), True)
    check("没登记客户端待更新", gameupdate.pending(e.cfg.state_dir), {})
    e._flush_pending()
    check("没发「进不了游戏」的说明", cant_enter_sent(e), False)
    check("没被当维护丢掉（还压着等补跑）", ("MaaEnd", "endfield") in e._pending)
    # The make-up did not fix it: the alarm goes to the group and names the shape.
    handle._push_unresolved(e, r, "补跑也没成", 1)
    body = e.notifier.sent[-1][1] if e.notifier.sent else ""
    check("报警里说了像没进游戏、按故障报", "像没进游戏" in body and "按故障报" in body, True)

    print("[形状有、公告读不到 → 普通故障，但记下「没读到」，不说成「没有公告」（审计 10-13 s1 #3）]")


    def hint_unreadable(now=None, fetch=None, strict=False):
        # efstatus.update_hint's own contract: "" on a failed read unless strict.
        if strict:
            raise OSError("notice page unreachable")
        return ""


    handle.efstatus.update_hint = hint_unreadable
    e = build()
    r = rec_from_fixture()
    handle._handle(e, r)
    check("还是普通故障", r.raw.get("maaend_unreachable"), None)
    check("记下公告没读到", r.raw.get("maaend_unreachable_unread"), True)
    check("账本上也记着", (ledger_raw(e, r) or {}).get("maaend_unreachable_unread"), True)
    check("没读到的说法不说「没有公告」", "没有官方" in getattr(texts, "UNREACHABLE_UNREAD_NOTE", "没有官方"), False)
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: ""
    e = build()
    r = rec_from_fixture()
    handle._handle(e, r)
    check("读到了、确实没有公告：不记没读到", r.raw.get("maaend_unreachable_unread"), None)

    print("[形状有 + 官方维护窗口 → 不补跑，进群一条，写明官方依据（2026-10-06 起）]")
    e = build()
    gameupdate._store(e.cfg.state_dir).set("updates", "maintenance_windows", {"终末地": {
        "start": DAY.replace(hour=6).isoformat(), "end": DAY.replace(hour=10).isoformat(),
        "why": "官方公告：06:00–10:00 停服维护"}})
    r = rec_from_fixture()
    handle._handle(e, r)
    check("记成进不了游戏", r.raw.get("maaend_unreachable"), True)
    check("账本上也是", (ledger_raw(e, r) or {}).get("maaend_unreachable"), True)
    check("补跑没份", makeup.eligible(r), False)
    check("登记了客户端待更新", "终末地" in gameupdate.pending(e.cfg.state_dir))
    e._flush_pending()
    check("进群一条「进不了游戏」", [t for t, _b, a in e.notifier.sent if a], [texts.cant_enter("MaaEnd")])
    check("…写着官方依据", any("官方依据：官方公告：06:00–10:00 停服维护" in b for t, b, a in e.notifier.sent if a), True)
    check("不再压着", dict(e._pending), {})
    e._flush_pending()
    check("下一轮不再推", len([t for t, _b, a in e.notifier.sent if a]), 1)

    print("[形状有 + 官方更新公告 → 不补跑，进群一条，写明那条公告]")
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: "官方公告：今天 10:00 「雪凇幽梦」版本更新"
    e = build()
    r = rec_from_fixture()
    handle._handle(e, r)
    check("记成进不了游戏", r.raw.get("maaend_unreachable"), True)
    check("补跑没份", makeup.eligible(r), False)
    e._flush_pending()
    check("进群一条「进不了游戏」", [t for t, _b, a in e.notifier.sent if a], [texts.cant_enter("MaaEnd")])
    check("…写着那条官方公告", any("官方依据：官方公告：今天 10:00 「雪凇幽梦」版本更新" in b
                              for t, b, a in e.notifier.sent if a), True)

    print("[形状有、公告没读到 → 报警用「没读到公告」那句，不说今天没有公告]")
    UNREAD = "（测试）官方公告没读到"
    texts.UNREACHABLE_UNREAD_NOTE = UNREAD
    e = build()
    r = rec_from_fixture()
    r.raw["maaend_unreachable_shape"] = True
    r.raw["maaend_unreachable_unread"] = True
    handle._push_unresolved(e, r, "补跑也没成", 1)
    body = e.notifier.sent[-1][1] if e.notifier.sent else ""
    check("用了没读到公告那句", UNREAD in body, True)
    check("没说今天没有公告", texts.UNREACHABLE_SHAPE_NOTE in body, False)

    if fails:
        print(f"\n✗ {len(fails)} 项失败")
        sys.exit(1)
    print("\nall checks passed")


def _part_unreachable_note_pushed_now():
    """The 「像没进游戏」 note is on every MaaEnd failure alarm, not only the held one.

Review of s7 #5 (5a407a4f): _confirm_unreachable's WARNING became INFO and only
pushes._push_unresolved (the held final alarm) adds texts.UNREACHABLE_SHAPE_NOTE.
A MaaEnd failure alarmed outside that path - a run a person started at AUTO-MAS
(held only for its own task's retries, then pushed by the flush), a run 停一切 cut
short - said it nowhere. Both now carry it (or the 「公告没读到」 note when
the notices could not be read), as the held alarm does.

    Formerly test_unreachable_note_pushed_now.py.
    """
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                      ARK_AUTOMAS_DIR=str(TMP / "nowhere"), ARK_MAAEND_DIR="", SERVERCHAN_KEY="",
                      ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng_mod
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import handle


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []


    class Src:
        def fetch(self, seen):
            return []


    handle._ship_evidence = lambda eng, r: ""
    handle._weekly_gates = lambda eng, r: None
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: ""   # no official notice today
    WHO = {"hand": ("", "task-hand"), "stop": ("06:10 停一切", "")}


    def build(state_dir):
        cfg = Config()
        cfg.state_dir = state_dir
        cfg.maaend_dir = None
        e = eng_mod.Engine(cfg, source=Src(), state=State(state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._archive_maaend_evidence = lambda r: None
        return e


    T0 = datetime(2026, 10, 12, 6, 4, tzinfo=SERVER_TZ)

    for how, label in (("hand", "有人在 AUTO-MAS 上手动开的"), ("stop", "停一切停掉的")):
        print(f"\n[{label}那趟终末地：每个任务秒败、零完成、没有官方公告 → 报警里写「像没进游戏」]")
        stop, hand = WHO[how]
        handle._estop_overlap = lambda eng, r, s=stop: s
        handle._hand_started = lambda eng, r, h=hand: h
        state = TMP / how
        state.mkdir()
        e = build(state)
        rec = RunRecord(run_id=f"2026-10-12/endfield/MaaEnd-06-04-{how}", script="MaaEnd", user="endfield",
                        started=T0, finished=T0 + timedelta(minutes=1), ok=False,
                        failed_tasks=["协议空间", "自动采集"], raw={"maaend_unreachable": True})
        handle._handle(e, rec)
        e._flush_pending()   # a hand-started failure waits for its task's retries (handle._hold_hand_started)
        check("按普通失败处理（形状留着）", (rec.raw.get("maaend_unreachable_shape"), rec.raw.get("maaend_unreachable")),
              (True, None))
        check("当场报了一条", len(e.notifier.sent), 1)
        check("那条里写了「像没进游戏」", texts.UNREACHABLE_SHAPE_NOTE in (e.notifier.sent or [("", "")])[0][1])

    print("\n[公告没读到 → 写「没读到」那句]")
    handle._estop_overlap = lambda eng, r: ""
    handle._hand_started = lambda eng, r: "task-hand"


    def _unread(now=None, fetch=None, strict=False):
        raise OSError("efstatus down")


    handle.efstatus.update_hint = _unread
    state = TMP / "unread"
    state.mkdir()
    e = build(state)
    rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-unread", script="MaaEnd", user="endfield",
                    started=T0, finished=T0 + timedelta(minutes=1), ok=False,
                    failed_tasks=["协议空间"], raw={"maaend_unreachable": True})
    handle._handle(e, rec)
    e._flush_pending()
    body = (e.notifier.sent or [("", "")])[0][1]
    check("写了「没读到」", texts.UNREACHABLE_UNREAD_NOTE in body)
    check("不写「今天没有官方公告」", texts.UNREACHABLE_SHAPE_NOTE in body, False)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_unreachable_evidence, _part_unreachable_note_pushed_now]))
