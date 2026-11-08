"""The engine and its loop: pending pushes, the loop's parts, network retries.

One part per former file, each run on its own (tests/_parts.py): test_engine_pending.py, test_loop_parts.py, test_netretry.py.
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


def _part_engine_pending():  # noqa: C901 - the whole body of the file this part was
    """engine.py 里没人碰过的四段：告警落盘、首启接管历史、在跑判断的缓存、tick 逐段兜底。

这个文件防的是四类损失，每一类都真的发生过或者差一点发生：

* **告警重复推 → 群里被轰炸**。2026-09-08 上午 `_persist_pending` 这一行炸了
  （它调的 `State.save_pending` 被贴了个 `@property`），失败记录永远落不了账，
  同一条每十几秒重推一次，推了半小时。`test_statestore.py` _part_state_pending 钉的是 State 那一层，
  这里钉的是 Engine 这一层：存进去、换个进程读回来，`_pending` / `_recovered` 还在。
* **中继重启就丢告警**。机器一天硬断电两次，压在内存里的告警等于没有。
* **首次启动把几百条历史当新失败推一遍**。`bootstrap` 没有任何测试调用过。
* **写配置撞上正在跑的脚本**（826 那一类）。`scripts_running` 是「现在能不能写配置」
  的唯一判据，它的三秒缓存要是把「在跑」缓存成「没在跑」，配置就会写进 AUTO-MAS
  正在读的那一份，然后被内存副本冲掉——刷错关卡、烧理智药。
* **一段出错带走后面的段**。2026-09-04 明日安排那段的 ImportError 把日报和关机
  一起带走，机器整夜没关。`test_tick_isolation.py` 只试了「漏跑检查」这一段，
  这里把八段逐个弄坏一遍，确认剩下七段照跑。

    Formerly test_engine_pending.py.
    """
    import json
    import os
    import time
    import types
    from datetime import datetime, timedelta


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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.features.modes import modes
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    class Notes:
        """假通知渠道：只记下来，不发出去。"""

        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return False        # False = 送出去了（真 Notifier 的口径：返回值是「有没有失败」）


    class Src:
        """假记录源：只给没见过的记录。"""

        def __init__(self, records=()):
            self.records = list(records)
            self.calls = 0

        def fetch(self, seen):
            self.calls += 1
            return [r for r in self.records if r.run_id not in (seen or set())]


    def rec(run_id, script="OK-WW", user="wuwa", ok=False):
        now = datetime.now(tz=SERVER_TZ)
        return RunRecord(run_id=run_id, script=script, user=user,
                         started=now - timedelta(minutes=10), finished=now,
                         ok=ok, failed_tasks=[] if ok else ["任务执行：某个错"], raw={})


    def build(state_dir=None, source=None):
        """一台干净的中继。state_dir 复用同一个就等于「重启一次」。"""
        cfg = Config()
        cfg.state_dir = state_dir or tmpdir()
        e = eng.Engine(cfg, source=source or Src(), state=State(cfg.state_dir),
                       notifier=Notes())
        e._scripts_running = lambda: False
        return e


    # ---------------------------------------------------------------- 告警落盘

    print("[待推告警落盘：存进去，重启后还在（09-08 轰炸事故就炸在这一行）]")
    sdir = tmpdir()
    e1 = build(sdir)
    e1._pending[("OK-WW", "wuwa")] = rec("2026-09-08/wuwa/OK-WW-05-22-26")
    e1._recovered[("MaaEnd", "endfield")] = rec("2026-09-08/endfield/MaaEnd-06-01-00",
                                                script="MaaEnd", user="endfield")
    raised = ""
    try:
        e1._persist_pending()
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("_persist_pending 不抛异常", raised, "")

    e2 = build(sdir)          # 重启：同一个 state 目录，全新实例
    check("重启后待推告警还在", list(e2._pending), [("OK-WW", "wuwa")])
    check("重启后自愈告警也还在", list(e2._recovered), [("MaaEnd", "endfield")])
    check("内容没走样", e2._pending[("OK-WW", "wuwa")].failed_tasks, ["任务执行：某个错"])
    check("run_id 对得上", e2._pending[("OK-WW", "wuwa")].run_id,
          "2026-09-08/wuwa/OK-WW-05-22-26")
    check("重启不算「已处理」", e2._pending[("OK-WW", "wuwa")].ok, False)

    print("\n[重启后压着的失败还带着日志尾巴，再重启一次也还在（audit s2 F4）]")
    sdir_t = tmpdir()
    logf = sdir_t / "OK-WW-05-22-26.log"
    logf.write_text("2026-09-08 05:30:01 任务执行：某个错\n", encoding="utf-8")
    et = build(sdir_t)
    held = rec("2026-09-08/wuwa/OK-WW-05-22-26")
    held.log_path = logf
    et._pending[("OK-WW", "wuwa")] = held
    et._persist_pending()
    logf.unlink()             # after the restart only the copy on disk is left
    et2 = build(sdir_t)
    check("重启后日志尾巴还在", "某个错" in et2.log_tails.get(held.run_id, ""), True)
    et2._persist_pending()
    et3 = build(sdir_t)
    check("再重启一次也还在", "某个错" in et3.log_tails.get(held.run_id, ""), True)

    print("\n[推出去之后要能清干净，否则下次开机又推一遍]")
    e2._pending.clear()
    e2._recovered.clear()
    e2._persist_pending()
    e3 = build(sdir)
    check("清空后重启是空的", (dict(e3._pending), dict(e3._recovered)), ({}, {}))

    print("\n[盘上有一条残缺记录，不许连累好的那条]")
    sdir2 = tmpdir()
    st = State(sdir2)
    from ark_relay.core.transport import record_to_payload
    try:
        st.save_pending({"pending": [record_to_payload(rec("2026-09-08/wuwa/OK-WW-1")),
                                     {"run_id": "缺时间字段"}],
                         "recovered": []})
    except Exception as exc:  # noqa: BLE001 - 保住 FAILED 那一行，别变成一串回溯
        fails.append(f"save_pending 抛异常：{type(exc).__name__}: {exc}")
    import logging


    class _Warnings(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    _w = _Warnings()
    eng.log.addHandler(_w)
    try:
        e4 = build(sdir2)
    finally:
        eng.log.removeHandler(_w)
    check("好的那条读回来了", [r.run_id for r in e4._pending.values()],
          ["2026-09-08/wuwa/OK-WW-1"])
    # Until 2026-10-10 the broken one was dropped with no word (only an INFO count of
    # the ones that did restore): an alarm held across a restart vanished.
    check("丢掉的那条说了一声（WARNING，带 run_id）",
          [ln for ln in _w.lines if "恢复不出来" in ln and "缺时间字段" in ln] != [], True)

    print("\n[从没存过时不许抛异常（全新机器第一次开机走的就是这条）]")
    raised = ""
    try:
        build(tmpdir())
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("空目录能起来", raised, "")


    # ---------------------------------------------------------------- 首次启动

    print("\n[bootstrap：第一次启动把已有历史当作已处理]")
    old = [rec(f"2026-09-01/wuwa/OK-WW-0{i}") for i in range(1, 4)]
    sdir3 = tmpdir()
    src = Src(old)
    e5 = build(sdir3, source=src)
    check("接管了 3 条历史", e5.bootstrap(), 3)
    check("三条都记成已处理", sorted(e5.state.seen), sorted(r.run_id for r in old))
    check("seen 文件已落盘", e5.state.seen_path.exists(), True)

    print("\n[接管完再跑一轮，一条都不许推出去]")
    # The two wall-clock steps are held still: this check is about records. Left live, a run
    # after the evening shutdown point (Beijing) pushed 「🌙 今晚不关机」 and failed it
    # (2026-10-10 00:40 JST, nothing to do with bootstrap).
    e5._maybe_shutdown = lambda *a, **k: False
    e5._maybe_daily_report = lambda *a, **k: False
    before = len(e5.notifier.sent)
    check("这一轮没有新记录", e5.tick(), 0)
    check("没有推送", len(e5.notifier.sent), before)

    print("\n[第二次启动不是「第一次」：历史不再接管，新记录才算新闻]")
    e6 = build(sdir3, source=Src(old))
    check("不再接管", e6.bootstrap(), 0)

    print("\n[历史是空的时候也要留下记号，否则下次开机又被当成第一次]")
    sdir4 = tmpdir()
    e7 = build(sdir4, source=Src([]))
    check("没有可接管的", e7.bootstrap(), 0)
    check("空文件也要建出来", e7.state.seen_path.exists(), True)
    e8 = build(sdir4, source=Src([rec("2026-09-08/wuwa/OK-WW-新的")]))
    check("下次启动不再当第一次", e8.bootstrap(), 0)


    # ---------------------------------------------------------------- 在跑判断

    print("\n[scripts_running：三秒缓存——一轮里十几处都在问，只许问一次]")
    real_win, real_busy, real_sub = eng.config.IS_WINDOWS, eng._automas_busy, eng.subprocess
    asked = []


    def fake_busy():
        asked.append(1)
        return fake_busy.answer


    try:
        eng.config.IS_WINDOWS = True     # the machine: the busy check asks AUTO-MAS
        eng._automas_busy = fake_busy

        fake_busy.answer = True
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
        check("第一次问 AUTO-MAS", eng.Engine._scripts_running(), True)
        check("确实问了一次", len(asked), 1)
        check("三秒内直接用上次的答案", eng.Engine._scripts_running(), True)
        check("没有再问第二次", len(asked), 1)

        fake_busy.answer = False
        eng.subprocess = types.SimpleNamespace(     # AUTO-MAS 说没在跑时才会去翻进程表
            run=lambda *a, **k: types.SimpleNamespace(stdout=b""),
            SubprocessError=real_sub.SubprocessError)
        check("缓存期内答案不变", eng.Engine._scripts_running(), True)
        check("缓存命中就没去问", len(asked), 1)
        eng._SCRIPTS_CACHE["at"] -= eng._SCRIPTS_TTL + 1        # 缓存过期
        check("过期后重新问", eng.Engine._scripts_running(), False)
        check("确实又问了", len(asked), 2)

        print("\n[缓存只敢缓存三秒：写配置要靠它判断，缓存久了就写进正在跑的那一份（826 那一类）]")
        check("TTL 不超过 3 秒", eng._SCRIPTS_TTL <= 3.0, True)

        print("\n[public 的 scripts_running 和内部判断必须是同一个答案]")
        e9 = build()
        del e9._scripts_running                     # 用回真的那个
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
        fake_busy.answer = True
        check("对外一致", e9.scripts_running(), True)

        print("\n[问不出来的时候宁可当作在跑：判断错方向就是写坏配置]")
        fake_busy.answer = None

        def blow_up(*a, **k):
            raise OSError("tasklist 跑不起来")

        eng.subprocess = types.SimpleNamespace(run=blow_up,
                                               SubprocessError=real_sub.SubprocessError)
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
        check("进程表也问不到 → 当作在跑", eng.Engine._scripts_running(), True)

        print("\n[Endfield.exe 也要算：MaaEnd 自己没有进程，只盯 MaaEnd.exe 会整段瞎掉]")
        for name, want in ((b"Endfield.exe", True), (b"MAA.exe", True),
                           (b"MaaEnd.exe", True), (b"explorer.exe", False)):
            eng.subprocess = types.SimpleNamespace(
                run=lambda *a, **k: types.SimpleNamespace(stdout=b'"%s","123"\r\n' % name),
                SubprocessError=real_sub.SubprocessError)
            eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
            check(f"进程表里只有 {name.decode()}", eng.Engine._scripts_running(), want)

        print("\n[OK-WW counts too, however it was started (10-27: a make-up run outside AUTO-MAS was 「nothing running」)]")
        from ark_relay.features.okww_patch import okww_overlay
        real_okww, real_env = okww_overlay.okww_running, os.environ.get("ARK_OKWW_DIR")
        okww_dir = tmpdir()
        logs = okww_dir / "data" / "apps" / "ok-ww" / "working" / "logs"
        logs.mkdir(parents=True)
        os.environ["ARK_OKWW_DIR"] = str(okww_dir)
        eng.subprocess = types.SimpleNamespace(                 # tasklist: only explorer
            run=lambda *a, **k: types.SimpleNamespace(stdout=b'"explorer.exe","123"\r\n'),
            SubprocessError=real_sub.SubprocessError)
        try:
            for up, quiet_s, want, label in (
                    (True, 30, True, "OK-WW up, its log written 30 s ago: running"),
                    (True, 120, True, "the 120 s travel wait (10-27 09:23:04-09:25:04): still running"),
                    (True, eng.OKWW_QUIET_MIN * 60 + 60, False, "log quiet past OKWW_QUIET_MIN: hung, not running"),
                    (False, 30, False, "no OK-WW process: not running"),
                    (None, 30, False, "process list unreadable: adds nothing")):
                okww_overlay.okww_running = lambda up=up: up
                log_file = logs / "ok-script.log"
                log_file.write_text("x", encoding="utf-8")
                os.utime(log_file, (time.time() - quiet_s, time.time() - quiet_s))
                eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
                check(label, eng.Engine._scripts_running(), want)
            okww_overlay.okww_running = lambda: True
            log_file.unlink()
            eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
            check("OK-WW up, no log to read: counted (cannot tell -> wait)", eng.Engine._scripts_running(), True)
        finally:
            okww_overlay.okww_running = real_okww
            if real_env is None:
                os.environ.pop("ARK_OKWW_DIR", None)
            else:
                os.environ["ARK_OKWW_DIR"] = real_env
    finally:
        eng.config.IS_WINDOWS, eng._automas_busy, eng.subprocess = real_win, real_busy, real_sub
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)


    # ---------------------------------------------------------------- tick 逐段兜底

    print("\n[tick 逐段兜底：八段里随便哪一段炸，另外七段照跑]")
    STEPS = ("_monthcard_notice", "_flush_pending",
             "_weekly_gates", "_check_missed_runs", "_maybe_interim_report",
             "_maybe_deferred_update", "_maybe_daily_report", "_maybe_shutdown")


    def arm(engine, broken):
        """把八段全换成记录器，其中一段改成会炸的。

    只写一个 `step`，坏不坏由闭包里的 name 决定——原来写成 if/else 里各一个
    同名 def，死代码闸门会判成「后一个把前一个盖掉」。那道闸门看不懂分支，
    而它拦住的那类错（同作用域重名，后者静静覆盖前者）值得留着，所以改测试。
    """
        ran = []

        def make(name):
            def step(*a, **k):
                ran.append(name)            # 记下来再炸，证明它确实被调到了
                if name == broken:
                    raise RuntimeError(f"「{name}」这一段坏了")
            return step

        for name in STEPS:
            setattr(engine, name, make(name))
        return ran


    e10 = build()
    for broken in STEPS:
        ran = arm(e10, broken)
        raised = ""
        try:
            e10.tick()
        except Exception as exc:  # noqa: BLE001
            raised = f"{type(exc).__name__}: {exc}"
        check(f"「{broken}」炸了不许把异常抛出 tick", raised, "")
        missing = [s for s in STEPS if s not in ran]
        check(f"「{broken}」炸了，其余七段照跑", missing, [])

    print("\n[日报和关机是最后两段，被前面任何一段带走 = 机器整夜不关]")
    for broken in STEPS[:-2]:
        ran = arm(e10, broken)
        try:
            e10.tick()
        except Exception as exc:  # noqa: BLE001 - 保住 FAILED 那一行，别变成一串回溯
            fails.append(f"「{broken}」把异常抛出了 tick：{type(exc).__name__}")
        check(f"「{broken}」炸了，日报和关机仍然跑到",
              ("_maybe_daily_report" in ran, "_maybe_shutdown" in ran), (True, True))

    print("\n[跳过模式那一段炸了也不许带走 tick（它在逐段循环之外）]")
    real_skip = modes.process_skip
    try:
        def boom(*a, **k):
            raise RuntimeError("QueueConfig 读不了")

        modes.process_skip = boom
        ran = arm(e10, None)
        raised = ""
        try:
            e10.tick()
        except Exception as exc:  # noqa: BLE001
            raised = f"{type(exc).__name__}: {exc}"
        check("跳过模式出错不抛出 tick", raised, "")
        check("八段照跑", [s for s in STEPS if s not in ran], [])
    finally:
        modes.process_skip = real_skip

    print("\n[同一条跳过模式的报错，一轮一轮地重复推 = 又一次群轰炸]")
    try:
        modes.process_skip = lambda *a, **k: ["队列「早班」不见了，恢复标记还压着"]
        e11 = build()
        e11._scripts_running = lambda: False
        for _ in range(5):
            e11._observe_modes()
        check("同一句只推一次", len(e11.notifier.sent), 1)
    finally:
        modes.process_skip = real_skip

    print("\n[处理单条记录出错，不许带走同一轮里的其他记录]")
    e12 = build(source=Src([rec("r1"), rec("r2"), rec("r3")]))
    handled = []


    def flaky(r):
        handled.append(r.run_id)
        if r.run_id == "r2":
            raise RuntimeError("这条记录处理不了")


    e12._handle = flaky
    for name in STEPS:
        setattr(e12, name, lambda *a, **k: None)
    check("三条都试过了", (e12.tick(), sorted(handled)), (3, ["r1", "r2", "r3"]))
    check("成功的两条记成已处理", sorted(e12.state.seen), ["r1", "r3"])

    print("\n[一条记录次次处理都出错：重试 HANDLE_TRIES 轮就放弃，群里只收到一条（audit s2 F3）]")
    from ark_relay.features.alarm import errwatch


    class GroupCount(errwatch.ErrorKindAlert):
        """The real errwatch handler (its level and filters), with the push replaced by a list."""

        def _take(self, record):
            self.taken.append(record.getMessage())


    sdir13 = tmpdir()
    src13 = Src([rec("bad")])
    e13 = build(sdir13, source=src13)
    e13.state.store.set("versions", "code", "v1")
    broken = [True]
    calls13 = []


    def _bad(r):
        calls13.append(r.run_id)
        if broken[0]:
            raise RuntimeError("这条记录永远处理不了")


    e13._handle = _bad
    for name in STEPS:
        setattr(e13, name, lambda *a, **k: None)
    group = GroupCount(Notes(), state_dir=tmpdir())
    group.taken = []
    ARK_ROOT = "ark"   # the parent of every relay logger
    logging.getLogger(ARK_ROOT).addHandler(group)
    for _ in range(6):                       # more ticks than the cap allows
        e13.tick()
    logging.getLogger(ARK_ROOT).removeHandler(group)
    check("群里只收到一条：最后那句「不再重试」", (len(group.taken), "不再重试" in "".join(group.taken)), (1, True))
    check("放弃后不再每轮重试", len(calls13), eng.HANDLE_TRIES)
    check("放弃的记录没混进「已处理」，记在放弃清单里带代码版本",
          ("bad" in e13.state.seen, (e13.state.store.get("queues", "given_up") or {}).get("bad", {}).get("code")),
          (False, "v1"))

    # Restart with new code (a deploy that fixed it): the record is tried again and booked.
    e13b = build(sdir13, source=src13)
    e13b.state.store.set("versions", "code", "v2")
    broken[0] = False
    e13b._handle = _bad
    for name in STEPS:
        setattr(e13b, name, lambda *a, **k: None)
    e13b.tick()
    check("部署新版后再试一次，成功就记成已处理、从放弃清单删掉",
          ("bad" in e13b.state.seen, e13b.state.store.get("queues", "given_up")), (True, None))

    # Same code after a restart: no retry.
    sdir13c = tmpdir()
    e13c = build(sdir13c, source=Src([rec("bad")]))
    e13c.state.store.set("versions", "code", "v1")
    e13c.state.store.set("queues", "given_up", {"bad": {"code": "v1", "at": datetime.now(tz=SERVER_TZ).isoformat()}})
    tried = []
    e13c._handle = lambda r: tried.append(r.run_id)
    for name in STEPS:
        setattr(e13c, name, lambda *a, **k: None)
    e13c.tick()
    check("代码没变就不再试", tried, [])


    print("[读模式开关炸了，也不许带走整轮——日报和关机在最后]")
    eng2 = build()
    ran = []
    eng2._observe_modes = lambda: (_ for _ in ()).throw(RuntimeError("模式文件读坏了"))
    for name in ("_monthcard_notice", "_flush_pending", "_maybe_daily_report"):
        setattr(eng2, name, (lambda n=name: (lambda *a, **k: ran.append(n)))())
    try:
        eng2.tick()
        check("tick 没有把异常抛出去", True, True)
    except Exception as e:                      # noqa: BLE001
        check(f"tick 没有把异常抛出去（抛了 {e}）", False, True)
    check("后面的段照样跑到了", "_maybe_daily_report" in ran, True)


def _part_loop_parts():  # noqa: C901 - the whole body of the file this part was
    """主循环拆出来的两个部件：目录监听的退避、AUTO-MAS 保活的睡眠上限与退避。

2026-09-08 把 241 行的 `_loop` 拆成 `_DirWatch` + `_AutomasKeeper` + 一段短循环。
拆之前这些状态是循环里的十来个局部变量，没法单独测，只能靠上机跑一整轮。

    Formerly test_loop_parts.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import service
    from ark_relay.features.host import automas_keeper, automas_procs, dirwatch, mainloop, procwatch, shutdown_signs


    def set_time(t):
        """service.py's code now lives in several modules, each reading its own `time`; swap it in all."""
        for m in (service, shutdown_signs, procwatch, dirwatch, automas_keeper, mainloop):
            m.time = t

    # Real numbers for the flags _DirWatch ORs together: the stub's class placeholder
    # only ORs on Python 3.10+, and the Mac's python3 is 3.9 (the deploy gate failed on
    # it 2026-10-06: every rebuild raised TypeError there, so none ever "worked").
    dirwatch.win32con.FILE_NOTIFY_CHANGE_FILE_NAME = 0x1
    dirwatch.win32con.FILE_NOTIFY_CHANGE_LAST_WRITE = 0x10
    # `_revive_automas` 2026-09-08 随开机流程搬去了 boot_stages.py，
    # `_AutomasKeeper._revive` 现在调的是那一份，所以要替换的也是那一份。
    import boot_stages


    class Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): pass


    class Notifier:
        def __init__(self): self.sent = []
        def send(self, title, body, **k): self.sent.append(title); return []


    print("[目录监听：重建失败按 5→10→20…封顶 60 秒退避]")
    cfg = types.SimpleNamespace(history_dir=Path("/nope"))
    w = dirwatch._DirWatch(cfg, Notifier(), Log())
    w.handle = None
    boom = _Stub("win32file")
    boom.FindFirstChangeNotification = lambda *a: (_ for _ in ()).throw(OSError("no"))
    orig_file = dirwatch.win32file
    dirwatch.win32file = boom
    delays = []
    now = [1000.0]
    set_time(types.SimpleNamespace(monotonic=lambda: now[0], sleep=lambda s: None))
    for _ in range(5):
        now[0] = w.retry_at
        w.maybe_rebuild()
        delays.append(w.retry_delay)
    check("退避翻倍到 60 封顶", delays, [10.0, 20.0, 40.0, 60.0, 60.0])
    check("失败期间句柄仍是空", w.handle, None)
    now[0] = w.retry_at - 1
    before = w.retry_delay
    w.maybe_rebuild()
    check("没到点不重试", w.retry_delay, before)
    dirwatch.win32file = orig_file

    class RecLog:
        """Records (level, message, recovered) - what errwatch would push or put in the daily report."""

        def __init__(self):
            self.lines = []

        def _add(self, level, fmt, *a, **k):
            from ark_relay.features.alarm import errwatch
            rec = bool((k.get("extra") or {}).get(errwatch.RECOVERED))
            self.lines.append((level, fmt % a if a else fmt, rec))

        def info(self, fmt, *a, **k): self._add("INFO", fmt, *a, **k)
        def warning(self, fmt, *a, **k): self._add("WARNING", fmt, *a, **k)
        def exception(self, fmt, *a, **k): self._add("ERROR", fmt, *a, **k)

        def loud(self):
            """WARNING / ERROR lines errwatch pushes (not marked recovered)."""
            return [m for lv, m, rec in self.lines if lv != "INFO" and not rec]

        def recovered(self):
            return [m for lv, m, rec in self.lines if lv != "INFO" and rec]


    def lost_watch():
        """A _DirWatch whose re-arm has just failed (the 2026-10-06 rule: decided by the rebuild)."""
        lg, n = RecLog(), Notifier()
        w = dirwatch._DirWatch(types.SimpleNamespace(history_dir=Path("/nope")), n, lg)
        rearm_fail = _Stub("win32file")
        rearm_fail.FindNextChangeNotification = lambda h: (_ for _ in ()).throw(OSError("rearm"))
        rearm_fail.FindCloseChangeNotification = lambda h: None
        dirwatch.win32file = rearm_fail
        w.rearm()
        return w, lg, n


    print("[目录监听：重新武装失败、几秒后自己重建好了 -> 报群（断开的原因还没查清，2026-10-10 起）]")
    now[0] = 5000.0
    w, lg, n = lost_watch()
    check("re-arm failure: nothing pushed yet", (lg.loud(), n.sent), ([], []))
    ok_file = _Stub("win32file")
    ok_file.FindFirstChangeNotification = lambda *a: "handle:9"
    dirwatch.win32file = ok_file
    now[0] = w.retry_at
    w.maybe_rebuild()
    # Why the watch is lost is not known: the rebuild is pushed (2026-10-10; daily report only before).
    check("rebuilt: one WARNING for the group, none marked recovered", (len(lg.loud()), lg.recovered()), (1, []))
    check("it says how long and that results are handled at once again",
          bool(lg.loud()) and "目录变更通知断过" in lg.loud()[0] and "马上处理" in lg.loud()[0], True)
    check("no WATCH_LOST alarm on top", n.sent, [])
    check("armed again", (w.handle, w.lost_since), ("handle:9", None))

    print("[目录监听：断满 10 分钟还没重建 -> 报群一次；之后每次重建失败只记 INFO（一件事只报一次）；最后重建好了 -> 只进日报（这次断开已经报过群）]")
    now[0] = 6000.0
    w, lg, n = lost_watch()
    dirwatch.win32file = boom
    for _ in range(6):
        now[0] = max(w.retry_at, now[0])
        w.maybe_rebuild()
        now[0] += 100
    check("under 10 minutes: no alarm", n.sent, [])
    now[0] = w.lost_since + procwatch.OUTAGE_ALARM_SECONDS + 1
    w.retry_at = now[0]
    w.maybe_rebuild()
    check("10 minutes: the 「⚠️ 中继暂时不能…」 alarm, once", n.sent, [dirwatch.texts.WATCH_LOST])
    now[0] += 61
    w.retry_at = now[0]
    w.maybe_rebuild()
    # Audit s15 #2 (2026-10-13): these were WARNINGs, which errwatch pushes - about 50
    # an hour after the one alarm, each with different numbers so none merged.
    check("a failed rebuild after the alarm: INFO (not pushed), no second alarm",
          (len(lg.loud()), n.sent), (0, [dirwatch.texts.WATCH_LOST]))
    check("the failed rebuild is still in the log", [lv for lv, m, _ in lg.lines if "重建失败" in m][-1:], ["INFO"])
    for _ in range(60):     # an hour of failed rebuilds at the 60 s cap
        now[0] += 61
        w.retry_at = now[0]
        w.maybe_rebuild()
    check("an hour after the alarm: still nothing pushed, still one alarm",
          (len(lg.loud()), n.sent), (0, [dirwatch.texts.WATCH_LOST]))
    dirwatch.win32file = ok_file
    now[0] += 61
    w.retry_at = now[0]
    w.maybe_rebuild()
    check("rebuilt at last: one recovered WARNING that says it was pushed meanwhile",
          [("期间报过群" in m) for m in lg.recovered()], [True])

    print("[目录监听：断着时服务停了 -> WARNING（报群）]")
    now[0] = 9000.0
    w, lg, n = lost_watch()
    w.stopping()
    check("one WARNING", [("到中继停下时还没重建" in m) for m in lg.loud()], [True])
    w.stopping()
    check("said once", len(lg.loud()), 1)
    dirwatch.win32file = orig_file

    print("[目录监听：没配历史目录就彻底不管]")
    w2 = dirwatch._DirWatch(types.SimpleNamespace(history_dir=None), Notifier(), Log())
    w2.retry_at = 0
    w2.maybe_rebuild()
    check("不重建", w2.handle, None)

    print("[保活：句柄不在时不许睡过「该来了」那一刻]")
    k = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    k.log, k.notifier = Log(), Notifier()
    k.handle = None
    k.wmi_alive = {"ok": True}
    k.revive_deadline = 1030.0
    now[0] = 1000.0
    check("睡到 deadline（30 秒），不是一小时", k.cap_wait(3600.0), 30.0)
    k.revive_deadline = 999.0
    check("已经过点了也至少睡 1 秒", k.cap_wait(3600.0), 1.0)
    k.wmi_alive = {"ok": False}
    k.revive_deadline = None
    check("订阅不可用时退回活性检查间隔",
          k.cap_wait(3600.0), procwatch.AUTOMAS_CHECK_SECONDS)
    k.handle = object()
    check("句柄在就不压缩", k.cap_wait(3600.0), 3600.0)

    print("[保活：连败到阈值才告警，且只告一次]")
    k2 = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    n = Notifier()
    k2.log, k2.notifier = Log(), n
    k2.handle = None
    k2.wmi_alive = {"ok": True}
    k2.revive_deadline = None
    k2.revive_wait = float(automas_keeper.REVIVE_FIRST_WAIT)
    k2.revive_failures = automas_keeper.REVIVE_ALERT_AFTER - 1
    k2.revive_alerted = False
    k2.shell_only_since = None
    k2.shell_grace_noted = False
    k2.next_check = 0.0
    k2.gone = None          # no unexplained exit pending (since 2026-10-06)
    orig_running, orig_shell, orig_inst, orig_revive = (
        automas_procs._automas_running, automas_procs._automas_shell_running,
        automas_procs._installer_running, boot_stages._revive_automas)
    automas_procs._automas_running = lambda: False
    automas_procs._automas_shell_running = lambda: False
    automas_procs._installer_running = lambda: False
    boot_stages._revive_automas = lambda: None
    k2._revive(1000.0)
    check("到阈值告一次", n.sent, [dirwatch.texts.AUTOMAS_DOWN])
    k2._revive(1000.0)
    check("再败不重复告", n.sent, [dirwatch.texts.AUTOMAS_DOWN])
    automas_procs._automas_running, automas_procs._automas_shell_running = orig_running, orig_shell
    automas_procs._installer_running, boot_stages._revive_automas = orig_inst, orig_revive

    print("[保活：窗口在、后端不在 → 先给宽限，超时才动手]")
    k3 = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    k3.log, k3.notifier = Log(), Notifier()
    k3.revive_failures = 0
    k3.revive_alerted = False
    k3.shell_only_since = None
    k3.shell_grace_noted = False
    k3.gone = None
    revived = []
    automas_procs._automas_running = lambda: False
    automas_procs._automas_shell_running = lambda: True
    automas_procs._installer_running = lambda: False
    boot_stages._revive_automas = lambda: revived.append(1)
    k3._revive(1000.0)
    check("宽限期内不拉起", revived, [])
    k3._revive(1000.0 + automas_keeper.SHELL_GRACE_SECONDS - 1)
    check("还在宽限期，仍不拉起", revived, [])
    k3._revive(1000.0 + automas_keeper.SHELL_GRACE_SECONDS)
    check("超过宽限才拉起", revived, [1])
    automas_procs._automas_running, automas_procs._automas_shell_running = orig_running, orig_shell
    automas_procs._installer_running, boot_stages._revive_automas = orig_inst, orig_revive

    print("\n[清单-1108 A-04：目录监听断开时，循环按重建时刻醒，不再一觉睡到一小时的备用闹钟]")
    set_time(types.SimpleNamespace(monotonic=lambda: 5000.0, sleep=lambda s: None))
    cw = dirwatch._DirWatch(types.SimpleNamespace(history_dir=Path("/nope"), poll_seconds=300), Notifier(), Log())
    cw.handle, cw.retry_at = None, 5005.0
    check("断开、5 秒后重建：最多睡 5 秒", cw.cap_wait(3600.0), 5.0)
    cw.retry_at = 4000.0
    check("重建时刻已过：睡 1 秒就醒", cw.cap_wait(3600.0), 1.0)
    cw.retry_at = 99999.0
    check("退避再长也按定时扫描间隔醒来看记录", cw.cap_wait(3600.0), 300.0)
    cw.handle = object()
    check("挂着的时候不管", cw.cap_wait(3600.0), 3600.0)
    cw.handle = None
    cw.cfg.history_dir = None
    check("没有历史目录：不管", cw.cap_wait(3600.0), 3600.0)

    print("\n[清单-1108 A-04：几个句柄同时亮，每一个都处理，不只处理编号最小的那个]")
    lit = {1, 2, 3}
    mainloop.win32event = types.SimpleNamespace(
        WAIT_OBJECT_0=0,
        WaitForSingleObject=lambda h, ms: (_ for _ in ()).throw(OSError("closed")) if h == "gone" else (0 if h in lit else 258))
    check("等到 1 号（进程启动），2、3 号（目录变更、AUTO-MAS 退出）也亮着", mainloop._fired([0, 1, 2, 3], 1), {1, 2, 3})
    check("超时：谁也没亮", mainloop._fired([0, 5, 6], 258), set())
    check("已关掉的句柄算没亮", mainloop._fired([0, "gone", 2], 0), {0, 2})

    print("\n[清单-1108 A-05：脚本刚停，先补做推迟的待办，再跑 tick（关机判断要看见它）]")
    order = []


    def _keeper(*a):
        return types.SimpleNamespace(proc_evt="proc", handle=None, cap_wait=lambda w: w,
                                     on_process_started=lambda: order.append("proc"),
                                     stopping=lambda: None, check=lambda *x: None)


    def _roll(*a):
        return types.SimpleNamespace(cap_wait=lambda w: w, check=lambda: order.append("dayroll"))


    class _Watch:
        handle = None
        def __init__(self, *a): pass
        def maybe_rebuild(self): pass
        def cap_wait(self, w): return w
        def stopping(self): pass
        def close(self): pass


    waits = iter([258, 0])
    mainloop.win32event = types.SimpleNamespace(WAIT_OBJECT_0=0, WaitForMultipleObjects=lambda h, a, ms: next(waits),
                                                WaitForSingleObject=lambda h, ms: 258)
    saved = (mainloop.automas_keeper._AutomasKeeper, mainloop.day_roll._DayRoll, mainloop.dirwatch._DirWatch)
    mainloop.automas_keeper._AutomasKeeper, mainloop.day_roll._DayRoll, mainloop.dirwatch._DirWatch = _keeper, _roll, _Watch
    eng = types.SimpleNamespace(next_deadline=lambda: None, scripts_running=lambda: False, tick=lambda: order.append("tick"))
    try:
        mainloop._loop(types.SimpleNamespace(stop_event="stop"), types.SimpleNamespace(), eng, Notifier(),
                       types.SimpleNamespace(last_fetch_ok=True), lambda why: order.append(f"collect:{why}"), [True], Log())
    finally:
        mainloop.automas_keeper._AutomasKeeper, mainloop.day_roll._DayRoll, mainloop.dirwatch._DirWatch = saved
    check("推迟的待办在 tick 之前补做", order, ["collect:推迟补做", "tick", "dayroll"])


def _part_netretry():
    """Another try, inside the caller's own limit, for a request the network cut short
(dispatch relay-opt-round3-1108 O-03; core/netretry.py).

Pinned here:
* transient(): timeouts, short bodies, resets, DNS failures and the gateway statuses
  502 / 503 / 504 are tried again; any other HTTP status (404, 403, 500) is not;
* call(): at most notify._RETRIES attempts, the first with the whole limit and each later one
  with what is left; no retry once the pause would use the rest (an 8 s COS write that timed
  out is not tried again, so the 30 s service stop still fits); INFO per failed attempt, one
  WARNING marked recovered when a later one went through, the last failure raised;
* cos_put / cos_get: a reset is tried again, a 404 / 403 is not, and they still never raise;
* efstatus.update_hint: a gateway 503 is tried again within its 8 s;
* needtable build._retry: a 404 is raised at once, a 503 or a reset is asked again.

    Formerly test_netretry.py.
    """
    import http.client
    import logging
    import urllib.error
    import urllib.request
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import netretry, notify
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.maintenance import efstatus
    from ark_relay.features.needtable import build
    from ark_relay.features.phone import cos_store


    class Rows(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False)), record.getMessage()))


    rows = Rows()
    netretry.log.addHandler(rows)
    netretry.log.setLevel(logging.DEBUG)
    netretry.log.propagate = False
    notify._rng.seed(7)


    def http_error(code):
        return urllib.error.HTTPError("https://x.invalid/k", code, "test", {}, None)


    print("[什么算网络掐断、值得再试]")
    for exc, want in ((TimeoutError("timed out"), True), (http.client.IncompleteRead(b"half"), True),
                      (http.client.RemoteDisconnected("closed"), True), (ConnectionResetError(54, "reset"), True),
                      (urllib.error.URLError("no dns"), True), (http_error(502), True), (http_error(503), True),
                      (http_error(504), True), (http_error(404), False), (http_error(403), False),
                      (http_error(500), False), (ValueError("odd"), False)):
        check(f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip(), netretry.transient(exc), want)


    class Clock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t

        def sleep(self, s):
            self.t += s


    def run(answers, limit=8.0, cost=0.3):
        """call() over a scripted fn: each answer is raised or returned, costing `cost` seconds."""
        clock, seen = Clock(), []

        def fn(left):
            seen.append(round(left, 2))
            clock.t += cost
            got = answers.pop(0)
            if isinstance(got, BaseException):
                raise got
            return got
        rows.rows.clear()
        try:
            out = netretry.call(fn, "读测试页", limit, detail="https://x.invalid/k", clock=clock, sleep=clock.sleep)
        except Exception as exc:  # noqa: BLE001
            out = exc
        return out, seen, list(rows.rows)


    print("\n[call：在原来的时限里再试]")
    out, seen, logged = run([ConnectionResetError(54, "reset"), "ok"])
    check("断了一次、第二次成了", out, "ok")
    check("第一次用整个时限，第二次用剩下的", (seen[0], 0 < seen[1] < 8.0 - 0.3), (8.0, True))
    check("一条 INFO、一条标自己好了的 WARNING", [(lv, r) for lv, r, _ in logged], [("INFO", False), ("WARNING", True)])
    out, seen, logged = run([http_error(503), http_error(502), http_error(504)])
    check("三次都是网关错：报最后一次", (getattr(out, "code", None), len(seen)), (504, notify._RETRIES))
    check("……没有 WARNING（由调用方报）", [lv for lv, _, _ in logged], ["INFO", "INFO"])
    out, seen, _ = run([http_error(404)])
    check("404：不再试，原样报出", (getattr(out, "code", None), len(seen)), (404, 1))
    out, seen, _ = run([TimeoutError("timed out"), "ok"], limit=8.0, cost=8.0)
    check("超时把时限用完：不再试（服务停止的 30 秒里放得下）", (type(out).__name__, len(seen)), ("TimeoutError", 1))
    out, seen, _ = run([ValueError("odd"), "ok"])
    check("别的错：不再试", (type(out).__name__, len(seen)), ("ValueError", 1))


    class Resp:
        def __init__(self, body=b"", status=200):
            self.body, self.status = body, status

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    def scripted(answers):
        calls = []

        def urlopen(req, timeout=None):
            calls.append(timeout)
            got = answers.pop(0)
            if isinstance(got, BaseException):
                raise got
            return got
        return urlopen, calls


    REAL = urllib.request.urlopen
    cos = SimpleNamespace(host="b.cos.example.invalid", authorization=lambda method, key: "sig")
    real_sleep = netretry._sleep
    netretry._sleep = lambda s: None
    try:
        print("\n[腾讯云 COS：断一下再写一次；404 / 403 照旧]")
        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("写入：断了一次又写进去了", (cos_store.cos_put(cos, "state/k.json", b"{}", 8), len(calls)), (None, 2))
        urllib.request.urlopen, calls = scripted([http_error(403)])
        check("写入：403 不再试，说回 403", (cos_store.cos_put(cos, "state/k.json", b"{}", 8), len(calls)), ("回 403", 1))
        urllib.request.urlopen, calls = scripted([http_error(503), Resp(b"body")])
        check("读取：网关 503 后读到", (cos_store.cos_get(cos, "k", 8), len(calls)), ((b"body", ""), 2))
        urllib.request.urlopen, calls = scripted([http_error(404)])
        check("读取：404 就是没有这个对象，不再试", (cos_store.cos_get(cos, "k", 8), len(calls)), ((None, ""), 1))
        urllib.request.urlopen, calls = scripted([OSError("odd")])
        check("读取：别的错照旧不抛、说原因", (cos_store.cos_get(cos, "k", 8)[1], len(calls)), ("odd", 1))

        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("写入 retry=False：只写一次，说原因", (bool(cos_store.cos_put(cos, "state/k.json", b"{}", 8, retry=False)),
                                              len(calls)), (True, 1))

        print("\n[心跳：平时一跳只写一次（下一跳就是重试），关机那一跳在 8 秒里再写一次]")
        # dispatch relay-opt-round3b-1108: a 30 s beat retried in the call wrote one 自愈待查 red
        # item per healed beat on a flaky link; the bye has no next beat.
        from ark_relay.features.phone import phone
        from _tmp import tmpdir
        hb = phone.Heartbeat("ark-test-topic", tmpdir(), post=lambda p, t: None, cos=cos)
        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("平时那一跳：断了就算这一跳没写上，只写一次", (hb.cos_beat(), len(calls)), (False, 1))
        urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
        check("关机那一跳：断了再写一次，写上了", (hb.cos_beat(bye=True), len(calls)), (True, 2))

        print("\n[终末地官方公告：网关 503 后在 8 秒里再读一次]")
        body = b'{"data": {"list": []}}'
        urllib.request.urlopen, calls = scripted([http_error(503), Resp(body)])
        check("读到了（今天没有版本更新）", (efstatus.update_hint(strict=True), len(calls)), ("", 2))
        check("第一次用 8 秒", calls[0], 8)
    finally:
        urllib.request.urlopen = REAL
        netretry._sleep = real_sleep

    print("\n[需求表建表：404 当场报，503 和断线照旧再问]")
    real_bsleep = build.time.sleep
    build.time.sleep = lambda s: None
    try:
        n = []

        def nf():
            n.append(1)
            raise http_error(404)
        try:
            build._retry(nf)
            out = None
        except urllib.error.HTTPError as exc:
            out = exc.code
        check("404：问一次就报", (out, len(n)), (404, 1))
        seq = [http_error(503), ConnectionResetError(54, "reset"), "ok"]

        def flaky():
            got = seq.pop(0)
            if isinstance(got, BaseException):
                raise got
            return got
        check("503、断线之后第三次成了", build._retry(flaky), "ok")
    finally:
        build.time.sleep = real_bsleep


if __name__ == "__main__":
    sys.exit(run_parts([_part_engine_pending, _part_loop_parts, _part_netretry]))
