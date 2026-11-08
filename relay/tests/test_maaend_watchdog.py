"""MaaEnd's watchdog: essence met and stamina out, full at the anchor, the round's upper bound, sanity (fit, one formula), the update after done, its record and restart, one push.

One part per former file, each run on its own (tests/_parts.py): test_maaend_watchdog.py, test_maaend_essence_met.py, test_maaend_essence_stamina_out.py, test_maaend_full_at_anchor.py, test_maaend_round_upper_bound.py, test_maaend_sanity.py, test_maaend_sanity_fit.py, test_maaend_sanity_one_formula.py, test_maaend_update_after_done.py, test_maaend_update_record.py, test_maaend_update_restart.py, test_maaend_update_restart_never_final.py, test_maaend_watchdog_onepush.py.
"""
from __future__ import annotations

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


def _part_main():
    """MaaEnd hung -> end MaaEnd.exe so AUTO-MAS retries now, not 45 minutes later.

2026-10-01 15:30:03: MaaEnd was on 「信用点购物」 when its plugin
D:\\ark\\maaend\\agent\\go-service.exe crashed. go-service.stderr.log line 1 was
`Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456`; maafw.log never
gained another line, MaaEnd.exe sat there alive, and only AUTO-MAS's 45-minute
limit ended it at 16:10:00. 2026-09-28 11:22:10 had the same 41-minute gap.
Normal runs never go more than 65 s between two maafw.log lines.

Replayed here with that day's shape. The clock, the AUTO-MAS snapshot, the
process list, the kill and the files are all stand-ins; nothing touches a real
process.

    Formerly test_maaend_watchdog.py.
    """
    import logging
    import os
    import threading
    import time


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.run import collect_watch, maaend_watchdog
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of


    # Every 「目录监听掉了」 the watcher logs while the test runs. It must stay empty:
    # the line Windows CI showed after the result line (2026-10-07) is the watcher
    # seeing its directory removed by _tmp's cleanup at exit, not a drop mid-test.
    class _Drops(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())


    _drops = _Drops()
    from ark_relay.core import watch as _watch
    _watch.log.addHandler(_drops)


    CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
    RUNNING = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"},
                                        {"name": "OK-WW", "status": "异常"},
                                        {"name": "MaaEnd", "status": "运行"}]}]}
    WAITING = {"tasks": [{"task_info": [{"name": "MAA", "status": "运行"},
                                        {"name": "MaaEnd", "status": "等待"}]}]}
    DONE = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}
    MAAEND_PID = 21260
    ALL_UP = [("System", 4), ("Endfield.exe", 18800), ("MaaEnd.exe", MAAEND_PID),
              ("go-service.exe", 21932), ("cpp-algo.exe", 21940), ("python.exe", 9000)]
    NO_GO = [p for p in ALL_UP if p[0] != "go-service.exe"]


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    class Rig:
        """One watchdog with every outside thing replaced."""

        def __init__(self, *, snap=RUNNING, procs=ALL_UP, kill_ok=True, active=True, paths=None):
            self.t = 1000.0
            self.snap, self.procs = snap, procs
            self.kill_ok = kill_ok
            self.killed = []
            self.notes = Notes()
            self.debug = tmpdir() / "debug"
            self.debug.mkdir()
            self.stderr = self.debug / "go-service.stderr.log"
            self.stderr.write_text("", encoding="utf-8")
            self.lines = 0
            self.stamp = "2026-10-01 15:20:00"
            agent = str(self.debug.parent / "agent")
            self.paths = paths if paths is not None else {21932: os.path.join(agent, "go-service.exe"),
                                                           21940: os.path.join(agent, "cpp-algo.exe")}
            self.images = []
            self.dog = maaend_watchdog.Watchdog(
                self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: self.snap,
                processes=lambda: self.procs, kill=self._kill, plugin_paths=lambda: self.paths,
                active=active)

        def _kill(self, pid, image):
            self.killed.append(pid)
            self.images.append(image)
            return (True, "") if self.kill_ok else (False, "退出码 128")

        def step(self, seconds, *, new_lines=0, stamp=None):
            """Let `seconds` pass, with `new_lines` appended to maafw.log meanwhile."""
            self.t += seconds
            self.lines += new_lines
            if stamp:
                self.stamp = stamp
            return self.dog.tick(self.lines, self.stamp)

        def run_for(self, seconds, every=60, **kw):
            out = []
            for _ in range(int(seconds // every)):
                if r := self.step(every, **kw):
                    out.append(r)
            return out


    print("[2026-10-01：MaaEnd 在跑，go-service 崩溃 → 结束 MaaEnd 一次，群里一条报警]")
    r = Rig()
    r.run_for(240, new_lines=40)                       # MaaEnd running fine for 4 minutes
    check("崩溃前什么都不做", (r.killed, r.notes.sent), ([], []))
    r.stderr.write_text(CRASH_LINE + "\nPC=0x7ffc630b5456\n\ngoroutine 1 gp=0xc000002380 m=0 mp=0x1 "
                        "[syscall, 5 minutes]:\n", encoding="utf-8")
    r.step(60)
    check("结束的是 MaaEnd.exe（和它的两个插件），没碰游戏", r.killed, [MAAEND_PID, 21932, 21940])
    check("只发一条", len(r.notes.sent), 1)
    title, body, alert = r.notes.sent[0]
    check("标题", title, texts.MAAEND_STUCK_KILLED)
    check("是真报警", alert, True)
    check("走群机器人", route_of(title, alert=True), "group")
    check("正文有错误码 0xc0000005", "0xc0000005" in body, True)
    check("正文说已结束", "已结束 MaaEnd" in body, True)
    check("正文是人话", texts.plain(body), [])
    r.run_for(600)
    check("同一个 MaaEnd 不再结束第二次", r.killed, [MAAEND_PID, 21932, 21940])
    check("也不再报第二次", len(r.notes.sent), 1)

    print("\n[maafw.log 10 分钟没有新行 → 结束 + 报警；9 分钟不动作]")
    r = Rig()
    r.run_for(300, new_lines=50, stamp="2026-10-01 15:30:03")
    r.run_for(540)                                     # 9 minutes with no new line
    check("9 分钟：不动作", (r.killed, r.notes.sent), ([], []))
    r.step(60)
    check("10 分钟：结束 MaaEnd", r.killed[:1], [MAAEND_PID])
    check("报警一条", len(r.notes.sent), 1)
    body = r.notes.sent[0][1] if r.notes.sent else ""
    check("正文写 10 分钟和最后一行时间", ("10 分钟" in body, "15:30:03" in body), (True, True))
    check("正文是人话", texts.plain(body), [])

    print("\n[正常：每 65 秒一行新日志 → 不动作]")
    r = Rig()
    r.run_for(65 * 40, every=65, new_lines=1)
    check("43 分钟里一次都没结束", (r.killed, r.notes.sent), ([], []))

    print("\n[MaaEnd 不是「运行」→ 不判、不杀]")
    for label, snap in (("等待", WAITING), ("完成", DONE), ("问不到快照", None)):
        r = Rig(snap=snap)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.run_for(1800)
        check(f"{label}：30 分钟没新行、stderr 有崩溃，也不动作", (r.killed, r.notes.sent), ([], []))

    print("\n[从等待变成运行：10 分钟从变成运行那一刻算，不从上一行日志算]")
    r = Rig(snap=WAITING)
    r.run_for(1800)
    r.snap = RUNNING
    r.run_for(120, new_lines=5)                        # first sight at +60 s, a new line at +120 s
    r.run_for(540)                                     # +660 s: 9 minutes since that line
    check("最后一行后 9 分钟：不动作", r.killed, [])
    r.step(60)
    check("满 10 分钟：结束", r.killed[:1], [MAAEND_PID])

    print("\n[go-service 不在：只见到一次不动作，隔 ≥60 秒连续两次才动作]")
    r = Rig()
    r.run_for(240, new_lines=20)
    r.procs = NO_GO
    r.step(60, new_lines=5)
    check("第一次不在：不动作", r.killed, [])
    r.procs = ALL_UP
    r.step(60, new_lines=5)
    r.procs = NO_GO
    r.step(30, new_lines=5)
    check("中间又见到了，重新数：不动作", r.killed, [])
    r.step(30, new_lines=5)
    check("隔 30 秒第二次不在：还不动作", r.killed, [])
    r.step(30, new_lines=5)
    check("隔 ≥60 秒第二次不在：结束（插件已不在，只结束 MaaEnd 和 cpp-algo）", r.killed, [MAAEND_PID, 21940])
    body = r.notes.sent[0][1] if r.notes.sent else ""
    check("正文说插件不在了", "go-service.exe 已经不在了" in body, True)
    check("正文是人话", texts.plain(body), [])

    print("\n[MaaEnd 刚起不满 3 分钟：插件还没起来是正常的 → 不动作]")
    r = Rig(procs=[p for p in NO_GO if p[0] != "cpp-algo.exe"])
    r.run_for(120, new_lines=10)
    check("2 分钟里不在两次：不动作", r.killed, [])
    r.run_for(180, new_lines=10)
    check("满 3 分钟后再连续两次不在：动作", r.killed[:1], [MAAEND_PID])

    print("\n[MaaEnd 换了新的一次（PID 变了）：旧的计时和旧的崩溃都不算]")
    r = Rig()
    r.run_for(240, new_lines=20)
    r.procs = [("MaaEnd.exe", 30000)]
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")   # the previous run's dump, still in the file
    r.step(60)
    check("新 PID 第一次见到时 stderr 已有的内容不算", r.killed, [])
    r.stderr.write_text("", encoding="utf-8")                   # go-service relaunched: file rewritten
    r.step(60, new_lines=5)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60, new_lines=5)
    check("重写后的新崩溃照样认得出", r.killed[:1], [30000])

    print("\n[结束失败 → 报警写没结束成]")
    r = Rig(kill_ok=False)
    r.run_for(240, new_lines=20)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("试着结束了一次", r.killed, [MAAEND_PID])
    title, body, alert = r.notes.sent[0] if r.notes.sent else ("", "", False)
    check("标题说没能结束", title, texts.MAAEND_STUCK_KILL_FAILED)
    check("是真报警，走群", (alert, route_of(title, alert=True)), (True, "group"))
    check("正文写结束没成功和原因", ("结束 MaaEnd 没成功" in body, "退出码 128" in body), (True, True))
    check("正文是人话", texts.plain(body), [])
    r.run_for(600)
    check("同一个 PID 不再试、不再报", (len(r.killed), len(r.notes.sent)), (1, 1))

    print("\n[不是 Windows：整个看门狗不动作]")
    r = Rig(active=False)
    r.run_for(240, new_lines=20)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.run_for(1800)
    check("什么都不做", (r.killed, r.notes.sent), ([], []))

    print("\n[MaaEnd.exe 不在：没东西可结束]")
    r = Rig(procs=[p for p in ALL_UP if p[0] != "MaaEnd.exe"])
    r.run_for(1800)
    check("不动作", r.killed, [])

    print("\n[maafw.log 的行数：跟轮转，变短但 bak 里有新行也算有新行]")


    class _Cfg:
        pass


    cfg = _Cfg()
    cfg.maaend_dir = str(tmpdir())
    cfg.state_dir = tmpdir()  # collect_watch.start prunes old task shots there
    (Path(cfg.maaend_dir) / "debug").mkdir()
    lp = Path(cfg.maaend_dir) / "debug" / "maafw.log"
    lp.write_text("[2026-10-01 15:29:00.000][INF] a\n" * 50, encoding="utf-8")
    w = collect_watch.Watcher(cfg, Notes())
    w.poll()
    seen = w.lines_seen
    check("读到 50 行", seen, 50)
    check("最后一行的时间", w.last_stamp, "2026-10-01 15:29:00")
    with lp.open("a", encoding="utf-8") as fh:
        fh.write("[2026-10-01 15:30:03.511][INF] b\n")
    lp.rename(lp.parent / "maafw.bak.2026.10.01-15.30.04.000.log")
    lp.write_text("", encoding="utf-8")                # MaaFW started over; the new file is empty
    w.poll()
    check("新文件更短，旧文件尾巴上那一行算新行", w.lines_seen, seen + 1)
    check("最后一行时间跟着更新", w.last_stamp, "2026-10-01 15:30:03")
    w.poll()
    check("没有新内容就不涨", w.lines_seen, seen + 1)

    print("\n[监听线程：日志不动也每隔一段时间叫一次看门狗]")
    ticks = []


    class _FakeDog:
        def __init__(self, *a, **kw):
            pass

        def tick(self, lines, stamp):
            ticks.append(lines)


    real_dog, real_tick = maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS
    maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS = _FakeDog, 0.2
    try:
        check("挂上了", collect_watch.start(cfg, Notes()), True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(ticks) < 3:
            time.sleep(0.1)
        check("文件一动不动，看门狗也被叫到了至少 3 次", len(ticks) >= 3, True)
    finally:
        maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS = real_dog, real_tick
    check("线程还活着", any(t.name == "collect-watch" for t in threading.enumerate()), True)

    print("\n[taskkill carries the image name, so a reused PID is never someone else]")
    r = Rig()
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("names passed with each PID", r.images, ["MaaEnd.exe", "go-service.exe", "cpp-algo.exe"])

    print("\n[a plugin-named program outside <maaend>\\agent is left alone]")
    r = Rig(paths={21932: "C:\\other\\go-service.exe", 21940: str(Path(tmpdir()) / "agent" / "cpp-algo.exe")})
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("only MaaEnd.exe ended", r.killed, [MAAEND_PID])
    r = Rig()
    r.paths = {21932: str(r.debug.parent / "agent2" / "go-service.exe"),
               21940: str(r.debug.parent / "agent" / "cpp-algo.exe")}
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("a sibling folder agent2 is not agent", r.killed, [MAAEND_PID, 21940])
    r = Rig(paths={})
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("paths unreadable -> plugins not ended", r.killed, [MAAEND_PID])

    print("\n[plugins left running are named in the alarm body (left=)]")
    _real_body = texts.maaend_stuck_body
    _body_calls = []
    texts.maaend_stuck_body = lambda *a, **kw: _body_calls.append((a, kw)) or "正文"
    try:
        r = Rig(paths={21932: "C:\\other\\go-service.exe"})    # cpp-algo's path unreadable
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)
        check("skipped plugins passed as left", _body_calls[-1][1].get("left"),
              ["C:\\other\\go-service.exe", "agent\\cpp-algo.exe"])
        r = Rig()
        r._kill = lambda pid, image: (r.killed.append(pid), (True, "") if image == "MaaEnd.exe" else (False, "退出码 128"))[1]
        r.dog.kill = r._kill
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)
        check("plugins whose kill failed passed as left", _body_calls[-1][1].get("left"),
              ["agent\\go-service.exe", "agent\\cpp-algo.exe"])
        r = Rig()
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)
        check("all plugins ended -> nothing left", _body_calls[-1][1].get("left", []), [])
    finally:
        texts.maaend_stuck_body = _real_body

    print("\n[not one maafw.log line read for this MaaEnd: report once, never kill]")
    from ark_relay.features.alarm import errwatch


    class _Warns(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.recs = []

        def emit(self, record):
            self.recs.append(record)


    _warns = _Warns()
    maaend_watchdog.log.addHandler(_warns)
    r = Rig()
    r.run_for(1200)                              # 20 minutes, no line at all
    maaend_watchdog.log.removeHandler(_warns)
    check("nothing ended", r.killed, [])
    check("one alarm, the blind one", [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND])
    check("it is a group alarm", route_of(texts.MAAEND_WATCH_BLIND, alert=True), "group")
    # s1: the WARNING repeating it was a second group push (every WARNING goes to the group).
    check("the WARNING repeating it is marked as already in the group, not pushed again",
          [bool(getattr(x, errwatch.PUSHED, False)) for x in _warns.recs if "读不到 maafw.log" in x.getMessage()], [True])
    # One fault, one push - per MaaEnd, not per PID number for ever: once MaaEnd is gone,
    # a later one that drew the same PID (Windows reuses them) and cannot be read either
    # is a second fault and rings again (until 2026-10-06 the blind mark was never
    # forgotten, so it stayed silent).
    r.procs = [p for p in ALL_UP if p[0] != "MaaEnd.exe"]
    r.step(60)
    r.procs = ALL_UP
    r.run_for(1200)
    check("a later MaaEnd with the same PID, unreadable too: rings again",
          [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND, texts.MAAEND_WATCH_BLIND])
    check("still nothing ended", r.killed, [])
    r = Rig()
    r.run_for(120, new_lines=5)
    r.run_for(660)
    check("lines once, then silence -> the normal stall kill", r.killed, [MAAEND_PID, 21932, 21940])

    print("\n[_taskkill reads success from the output: a filter that matches nothing still exits 0]")
    real_run = maaend_watchdog.subprocess.run
    calls = []


    def fake_run(out, rc=0):
        def run(args, **kw):
            calls.append(args)
            return type("R", (), {"returncode": rc, "stdout": out.encode("gbk"), "stderr": b""})()
        return run


    try:
        maaend_watchdog.subprocess.run = fake_run("成功: 已终止 PID 为 21260 的进程。")
        check("成功 -> ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe"), (True, ""))
        check("filters on PID and image", calls[-1], ["taskkill", "/F", "/FI", "PID eq 21260", "/FI", "IMAGENAME eq MaaEnd.exe"])
        maaend_watchdog.subprocess.run = fake_run("信息: 没有运行的带有指定标准的任务。")
        check("no match, exit 0 -> not ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe")[0], False)
        maaend_watchdog.subprocess.run = fake_run("错误: 无法终止", rc=128)
        check("exit 128 -> not ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe"), (False, "退出码 128"))
    finally:
        maaend_watchdog.subprocess.run = real_run

    check("目录监听在测试期间没掉过", _drops.msgs, [])


def _part_maaend_no_d3d11_alarm():
    """A game started without Direct3D 11 is normal now: no group alarm after a MaaEnd record or at boot.

Until 10-17 the official launcher's 「DirectX 11 启动」 box was ticked so MaaEnd could read the
fullscreen game, and the launcher remembers it, so the owner's own play started in DX11 too. Since
10-17 the game runs windowed below the desktop for script runs (AUTO-MAS v5.7.0-beta.5
「MaaEnd 启动」, set by efstart_setup; the relay's own retry starts it the same way), which MaaEnd
reads on any graphics API, and the box is to be unticked (DECISIONS D-1016-终末地等AUTO-MAS新版).

Until then the relay read line 6 of the game's Player.log after every MaaEnd record
(handle._book) and at boot (boot_stages._stage_endfield_start), and logged a WARNING when it was
not 「Forcing GfxDevice: Direct3D 11」. errwatch pushes every WARNING to the group, so with the box
unticked that would have been a false alarm every day. Pinned here with a Player.log whose line 6
names another device (the Vulkan line has never been seen on the machine; any line that is not
Direct3D 11 made the old check warn):

* a MaaEnd record booked through handle._handle: no WARNING, nothing to the group;
* the boot stage: no WARNING either.

    Formerly test_maaend_no_d3d11_alarm.py.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    import boot_stages
    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.alarm import handle
    from ark_relay.features.gameupdate import efstart_setup
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    class Warned(logging.Handler):
        """What errwatch.ErrorKindAlert would take: every WARNING or worse (it sits on the relay's top logger)."""

        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(f"{record.name}: {record.getMessage()}")


    WARNED = Warned()
    logging.getLogger().addHandler(WARNED)

    # The game's own log, line 6 not Direct3D 11 (the first five lines as on the machine 10-16).
    player = TMP / "Administrator" / "Player.log"
    player.parent.mkdir()
    player.write_text("\n".join([
        "Mono path[0] = 'D:/endfield/Hypergryph Launcher/games/Endfield Game/Endfield_Data/Managed'",
        "Mono config path = 'D:/endfield/Hypergryph Launcher/games/Endfield Game/MonoBleedingEdge/etc'",
        "[Physics::Module] Initialized MultithreadedJobDispatcher with 15 workers.",
        "Initialize engine version: 2021.3.34f1",
        "[Subsystems] Discovering subsystems at path D:/endfield/x/UnitySubsystems",
        "Forcing GfxDevice: Direct3D 12",
        "Direct3D:",
    ]) + "\n", encoding="utf-8")
    # Before this change the relay found Player.log through this function; patched so that code
    # would read the file above. Code without the function never reads it.
    efstart_setup._player_logs = lambda: [str(player)]


    def automas_dir() -> Path:
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
        for k, p in paths.items():
            sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
        qc = {"instances": [{"uid": "q0"}],
              "q0": {"Info": {"Name": "早班", "TimeEnabled": True},
                     "SubConfigsInfo": {"TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                        "QueueItem": {"instances": [],
                                                      **{f"i{i}": {"Info": {"ScriptId": f"s-{k}"}}
                                                         for i, k in enumerate(paths)}}}}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    handle._ship_evidence = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    collect_retry.restore_master = lambda cfg: ""


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir() / "state"
        cfg.automas_dir = automas_dir()
        cfg.maaend_dir = MAAEND
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e


    print("[the capture sees a WARNING from the relay's loggers at all]")
    efstart_setup.log.warning("probe")
    check("a WARNING from efstart_setup's logger is caught", WARNED.lines, ["ark.efstart_setup: probe"])
    WARNED.lines.clear()

    print("\n[a MaaEnd record lands, Player.log line 6 is not Direct3D 11]")
    start = datetime(2026, 10, 16, 13, 26, 0, tzinfo=SERVER_TZ)
    rec = RunRecord(run_id="2026-10-16/endfield/MaaEnd-09-26-00", script="MaaEnd", user="endfield",
                    started=start, finished=start + timedelta(minutes=30), ok=True, failed_tasks=[],
                    raw={"maaend_result": "Success!"})
    e = build()
    handle._handle(e, rec)
    e._flush_pending()
    check("no WARNING (errwatch would push each one to the group)", WARNED.lines, [])
    check("nothing to the group", [s for s in e.notifier.sent if s[2]], [])

    print("\n[boot: the Endfield start stage with the same Player.log]")
    WARNED.lines.clear()
    # A later start of the game (the log written again), so the boot reads it afresh.
    _t = player.stat().st_mtime + 60
    os.utime(player, (_t, _t))
    boot_stages._endfield_launch = lambda cfg, log, when: None
    boot_stages._stage_endfield_start(Config(), Notes(), efstart_setup.log)
    check("no WARNING at boot", WARNED.lines, [])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_maaend_essence_met():
    """Essence target mode with nothing left to farm is its own ending: not a
false green, not work done.

Real record, 2026-10-16: AUTO-MAS history MaaEnd-09-53-33 and MaaEnd's own app
log 2026-10-16-3.log, both read from the game PC unchanged into
replay/2026-10-16/endfield/ (test_replay.py replays the same record through the
outcome check, verdict.json: says nothing). Only 玉中身 is ticked in
target mode; its essence was already owned, so 基质刷取 spent 180 s on the
inventory scan and ended with 「🎯目标模式：勾选武器的基质均已满足，结束任务」
(upstream autoessence/plan_action.go "all targets satisfied"). The relay knew
only 「已完成一次基质刷取|理智不足」 as work and 「根据执行周期跳过」 as a skip, so at
14:12:12 it pushed a group alert saying the task had reported done after 180 s
with no trace of farming in the log.

The negative case keeps the generic 「基质目标已满足或任务结束」 line that
AutoEssenceOnComplete prints on any target-mode ending: alone, it must still
alert.

    Formerly test_maaend_essence_met.py.
    """
    #!/usr/bin/env python3

    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import ledger as core
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.verify.collector_maaend import parse_maaend_log
    from ark_relay.features.verify.outcome import maaend_checks, summarize

    REC = Path(__file__).resolve().parent / "replay" / "2026-10-16" / "endfield"
    HIST = (REC / "MaaEnd-09-53-33.log").read_text(encoding="utf-8")
    APP = "\n" + (REC / "2026-10-16-3.log").read_text(encoding="utf-8")
    MET_LINE = "勾选武器的基质均已满足"
    GENERIC = "基质目标已满足或任务结束"
    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
        if not ok:
            FAILED.append(name)


    def bad(checks) -> dict:
        return {c.label: c.detail for c in checks if not c.ok}


    def without_met(text: str) -> str:
        return "\n".join(x for x in text.splitlines() if MET_LINE not in x) + "\n"


    def ent(raw: dict, incomplete) -> dict:
        st = datetime(2026, 10, 16, 13, 54, 57, tzinfo=SERVER_TZ)
        fin = datetime(2026, 10, 16, 14, 11, 39, tzinfo=SERVER_TZ)
        return {"run_id": "2026-10-16/endfield/MaaEnd-09-53-33", "script": "MaaEnd", "user": "u", "ok": True,
                "started": st.isoformat(), "finished": fin.isoformat(), "incomplete": incomplete,
                "duration_known": True, "transitional": False, "failed_tasks": [],
                "raw": raw, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}


    def main() -> int:
        require("fixture has the real ending lines", MET_LINE in HIST and GENERIC in HIST)

        print("[10-16 14:10 那趟：勾选的武器基质已经齐了，没刷]")
        checks = maaend_checks(HIST + APP, [], own_log=True)
        b = bad(checks)
        require("基质刷取 is not judged undone", not any(k.startswith("基质刷取") for k in b), repr(b))
        msg = summarize(checks, "MaaEnd")
        require("no group alert for the whole run", msg is None, repr(msg))

        # With a real failure in the same run the summary is written: the target-met
        # task has its own line and is not listed as done.
        fake = ("[2026-10-16 14:12:00.000] 任务开始: ⚔️协议空间\n"
                "[2026-10-16 14:12:20.000] 任务完成: ⚔️协议空间\n")
        msg2 = summarize(maaend_checks(HIST + fake + APP, [], own_log=True), "MaaEnd") or ""
        lines2 = msg2.splitlines()
        require("own line 「勾选的武器基质已经齐了、没刷：基质刷取」",
                texts.OUTCOME_ESSENCE_MET_HEAD + "基质刷取" in lines2, msg2)
        require("not listed under 干成的",
                not any(ln.startswith("干成的") and "基质刷取" in ln for ln in lines2), msg2)

        print("[只有通用那句「基质目标已满足或任务结束」：照旧报]")
        generic = without_met(HIST)
        require("negative fixture keeps the generic line only", GENERIC in generic and MET_LINE not in generic)
        bg = bad(maaend_checks(generic + APP, [], own_log=True))
        require("still judged undone, with the seconds",
                "180 秒" in bg.get("基质刷取 真的刷了", ""), repr(bg))

        print("[日报：一行说清没刷、可以换武器]")
        d = tmpdir()
        raw = parse_maaend_log(REC / "MaaEnd-09-53-33.log")
        require("parser: target met recorded", raw.get("maaend_essence_met") is True, repr(raw.get("maaend_essence_met")))
        require("parser: not booked as a farm of 0 runs", "maaend_farm" not in raw, repr(raw.get("maaend_farm")))
        _t, body = core.format_daily("2026-10-16", [ent(raw, msg)])
        require("daily report says it plainly", texts.ESSENCE_TARGET_MET in body, body)
        require("... does not say 刷 基质刷取", "刷 基质刷取" not in body, body)
        require("... the row is not ⚠️ / 没干完", "没干完" not in body and not body.startswith("⚠️"), body)

        (d / "generic.log").write_text(generic, encoding="utf-8")
        graw = parse_maaend_log(d / "generic.log")
        require("parser: generic line alone is not target met",
                "maaend_essence_met" not in graw and graw.get("maaend_farm") == "基质刷取", repr(graw.get("maaend_farm")))

        for t in (texts.ESSENCE_TARGET_MET, texts.OUTCOME_ESSENCE_MET_HEAD):
            require(f"plain language: {t}", texts.plain(t) == [], repr(texts.plain(t)))

        print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
        return 1 if FAILED else 0


    if __name__ == "__main__":
        sys.exit(main())


def _part_maaend_essence_stamina_out():
    """MaaEnd v2.34's 「体力不足，任务结束」 is the out-of-sanity ending of 基质刷取.

Real record, 2026-10-19 (fixtures/maaend-2026-10-19/MaaEnd-07-14-29.log, the
AUTO-MAS history log of the morning run's second attempt, unchanged). MaaEnd had
updated itself to v2.34.0-rc.1 at 11:14:04 between the two attempts. The first
attempt had farmed sanity 242 -> 2 already; in the retry 基质刷取 read 「当前理智
9/360」 and stopped after 76 s with 「😴**体力不足，任务结束**」. The relay knew only
「已完成一次基质刷取|理智不足」 as the trace of farming, so at 11:57:16 it pushed
「⚠️ 终末地早班没干完」 to the group (ledger #106): a normal state (out of sanity)
reported as work left undone.

The negative case keeps the same segment without the stop line: a quick
「任务完成」 with no trace must still alert.

    Formerly test_maaend_essence_stamina_out.py.
    """
    #!/usr/bin/env python3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify.collector_maaend import parse_maaend_log
    from ark_relay.features.verify.outcome import maaend_checks

    LOG_PATH = Path(__file__).parent / "fixtures" / "maaend-2026-10-19" / "MaaEnd-07-14-29.log"
    LOG = LOG_PATH.read_text(encoding="utf-8")
    STOP = "😴**体力不足，任务结束**"


    def bad(checks):
        return {c.label: c.detail for c in checks if not c.ok}


    require("the real record holds the stop line", STOP in LOG)
    got = bad(maaend_checks(LOG, []))
    require("「体力不足，任务结束」 counts as 基质刷取's ending, no 「真的刷了」 failure",
          "基质刷取 真的刷了" not in got)

    stripped = "\n".join(l for l in LOG.splitlines() if "体力不足" not in l and "如需继续刷取" not in l)
    got2 = bad(maaend_checks(stripped, []))
    require("without the stop line a 76 s 基质刷取 still alerts",
          "76 秒" in got2.get("基质刷取 真的刷了", ""))

    require("the sanity collector reads the new stop line as sanity exhausted",
          parse_maaend_log(LOG_PATH).get("sanity_exhausted") is True)

    # 协议空间 and machine check #20 read the same v2.34 ending (dispatch relay-opt-round3-1108 O-04):
    # until then both knew only 理智不足, which #106 had replaced.
    from ark_relay.features.verify import outcome
    from ark_relay.features.selfcheck.machinechecks import runs
    proto = dict((name, rx) for name, rx, _ in outcome._MAAEND_WORK)["协议空间"]
    require("协议空间 counts 「体力不足，任务结束」 as its ending", bool(proto.search(STOP)))
    require("协议空间 still counts the old 理智不足", bool(proto.search("理智不足")))
    require("#20 reads 「体力不足，任务结束」 as the stop", bool(runs._STOP.search("体力不足，任务结束")))
    require("#20 still reads the old 理智不足", bool(runs._STOP.search("理智不足")))
    require("#20 does not take any 体力不足 for the stop", runs._STOP.search("体力不足") is None)

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nall checks passed")


def _part_maaend_full_at_anchor():
    """Endfield's full-again time counts from the reading, and a floor 0 gets none.

fixtures/maaend-sanity-1013/2026-10-12_MaaEnd-06-04-00.log is that run's 协议空间
task: last reading 242 at 10:23:32, one double claim, 82 left. Skland at
10:24:03 read curStamina=82 with maxTs 1791891939 = 10-13 19:45:39 (relay.log
上机核对 #10). Anchored on the record's finish (10:58) the sentence said 20:19.
A 0 after 「理智不足，结束任务」 is max(0, …) of a subtraction, not a reading; a
time from it was 1.4-4.5 h late on 10-11 and 10-12.
An exact 0 from the per-claim rule is a reading and keeps its time: the 10-13
05:36 log with 198 changed to 160 (one double claim, 160 -> 0, then 「理智不足，
结束任务」) is full 360 x 7m12s after 09:53:22. With 198 changed to 60 the half
claim gives -20, floored to 0: no time. Before, both lost the time.

    Formerly test_maaend_full_at_anchor.py.
    """
    #!/usr/bin/env python3
    import tempfile
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.core.config import SERVER_TZ


    fin = datetime(2026, 10, 12, 10, 58, 40, tzinfo=SERVER_TZ)
    log = Path(__file__).parent / "fixtures" / "maaend-sanity-1013" / "2026-10-12_MaaEnd-06-04-00.log"
    raw: dict = {}
    collector._enrich_record(raw, "MaaEnd", log, True, [], fin)
    check("full at from the reading's time", raw.get("sanity_full_at"), "理智将在 2026-10-13 19:45 回满。")

    raw = {"sanity": 0, "sanity_exhausted": True, "sanity_cap": 360}
    collector._enrich_record(raw, "MaaEnd", Path("/nonexistent/MaaEnd.log"), True, [], fin)
    check("exhausted and 0: no sentence", raw.get("sanity_full_at") or "", "")

    src = (Path(__file__).parent / "fixtures" / "maaend-sanity-1013" / "2026-10-13_MaaEnd-05-36-57.log").read_text(encoding="utf-8")
    fin = datetime(2026, 10, 13, 9, 54, tzinfo=SERVER_TZ)
    for first, want_left, want in ((160, 0, "理智将在 2026-10-15 05:05 回满。"), (60, 0, "")):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "MaaEnd.log"
            p.write_text(src.replace("当前理智 198/360", f"当前理智 {first}/360"), encoding="utf-8")
            raw = {}
            collector._enrich_record(raw, "MaaEnd", p, True, [], fin)
        check(f"read {first}, exhausted: left", raw.get("sanity"), want_left)
        check(f"read {first}, exhausted: full-at", raw.get("sanity_full_at") or "", want)


def _part_maaend_round_upper_bound():
    """A MaaEnd round is judged on its own error pictures and app-log lines only,
not on those of the rounds after it.

Real case, 2026-10-01 (ledger-2026-10-01.jsonl; relay.log 24567-24571): round
MaaEnd-11-23-07 ran 15:24:12-15:29:59, round MaaEnd-12-11-12 ran
16:12:15-16:58:22; both were judged at 17:27:45, and the first was failed with
「有 1 张出错截图：2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png」,
a picture taken inside the second round. Audit 2026-10-13 s8 #2.

    Formerly test_maaend_round_upper_bound.py.
    """
    import os
    import types
    from datetime import datetime, timedelta


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.features.alarm import gamelogs, verdict


    def at(h, m, s=0):
        return datetime(2026, 10, 1, h, m, s, tzinfo=SERVER_TZ)


    def touch(p: Path, when: datetime):
        os.utime(p, (when.timestamp(), when.timestamp()))


    START1, END1 = at(15, 24, 12), at(15, 29, 59)
    UNTIL1 = END1 + timedelta(minutes=5)
    LATER_SHOT = "2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png"

    root = tmpdir()
    oe = root / "debug" / "on_error"
    oe.mkdir(parents=True)
    (oe / LATER_SHOT).write_bytes(b"png")
    touch(oe / LATER_SHOT, at(16, 44, 46))
    own = "2026.10.01-15.27.03.000___Own.png"
    (oe / own).write_bytes(b"png")
    touch(oe / own, at(15, 27, 3))
    app = root / "debug" / "2026-10-01-3.log"
    app.write_text("\n".join([
        "2026-10-01 15:24:20 INFO  [App] 开始任务: 🛍️信用点购物",
        "2026-10-01 15:29:50 INFO  [App] 任务完成: 🛍️信用点购物",
        "2026-10-01 16:12:20 INFO  [App] 开始任务: 🛍️信用点购物",
        "  continuation of the 16:12 line",
        "2026-10-01 16:58:20 INFO  [App] 任务失败: 🛍️信用点购物",
    ]) + "\n", encoding="utf-8")
    touch(app, at(16, 58, 20))

    def call(f, *a):
        try:
            return f(*a)
        except TypeError as exc:     # the code before the bound took no `until`
            return f"TypeError: {exc}"


    print("[pictures: only the round's own, up to finish + 5 min]")
    check("the first round's pictures", call(gamelogs._maaend_new_shots, root, START1, UNTIL1), [own])
    check("no bound -> as before", gamelogs._maaend_new_shots(root, START1), sorted([LATER_SHOT, own]))

    print("\n[app log: lines cut by their own stamps]")
    text = call(gamelogs._maaend_app_log, root, START1, UNTIL1)
    check("keeps the round's lines", "15:29:50" in text, True)
    check("drops the later round's lines", ("16:12:20" in text, "continuation" in text, "16:58:20" in text),
          (False, False, False))
    check("a file with no stamps is kept whole",
          call(getattr(gamelogs, "_in_window", lambda *a: None), "no stamp here\nnor here", START1, UNTIL1),
          "no stamp here\nnor here")

    print("\n[the outcome check, real functions: judged without the later round's picture and lines]")
    hist = root / "MaaEnd-11-23-07.log"
    hist.write_text("[2026-10-01 15:24:20.000] 任务开始: 🛍️信用点购物\n"
                    "[2026-10-01 15:29:40.000] 任务完成: 🛍️信用点购物\n", encoding="utf-8")
    rec = RunRecord(run_id="2026-10-01/endfield/MaaEnd-11-23-07", script="MaaEnd", user="endfield",
                    started=START1, finished=END1, ok=True, log_path=hist)
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=root, state_dir=root))
    msg = verdict._verify_outcome(eng, rec) or ""
    check("the later picture is not named", LATER_SHOT in msg, False)
    check("its own picture is (the round, like 10-01's, has no 「自动执行任务完成」)", own in msg, True)

    print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")


def _part_maaend_sanity():
    """MaaEnd 的「剩余理智」报的是扣费之前的数字。

终末地协议空间的流程是：打完 → 奖励结算界面 → 花理智领取。MaaEnd 的
「当前理智 x/360」是在**结算界面**打的，而扣费发生在紧随其后的
「确认领取奖励」。所以日志里最后一条读数是**扣费之前**的值——只要最后一次
真的扣成了，直接报它就会高出整整一次的消耗。

运营 2026-08-25 指出：「MAAEND的剩余理智一直显示的是消耗之前的理智量」。
复查两天的真机日志，确认如此：

    08-24  当前理智 201 → 尝试使用理智消耗许可 → 理智不足，结束任务
           报出来是 201，真实剩余 41
    08-25  当前理智 241 → 扣 → 当前理智 81 → 理智不足，尝试不使用 → 结束
           报出来是 81，真实剩余也是 81（最后一次没扣）

两天的差别正是判断依据：**只看最后一次结算扣没扣**，而不是整段里扣过几次。

    Formerly test_maaend_sanity.py.
    """
    import os, sys

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features.verify import collector_maaend


    def parse(text):
        p = TMP / "x.log"
        p.write_text(text, encoding="utf-8")
        return collector.parse_maaend_log(p)


    print("[最后一次扣成了 —— 要减掉一次消耗]")
    # 08-24 的形状：两条读数都一样，日志里看不到下降，只能用兜底常量。
    got = parse("""\
[2026-08-24 09:36:31.345] 当前理智 201/360
[2026-08-24 09:36:32.000] 进入协议空间成功
[2026-08-24 09:37:24.957] 当前理智 201/360
[2026-08-24 09:37:25.648] 尝试使用理智消耗许可
[2026-08-24 09:37:26.000] 确认领取奖励
[2026-08-24 09:37:31.284] 理智不足，结束任务
""")
    check("看不到下降时用兜底的单次消耗", got.get("sanity"), 201 - collector_maaend._END_PS_COST)
    check("上限照报", got.get("sanity_cap"), 360)

    print("\n[最后一次被拒了 —— 读数就是终值]")
    # 08-25 的形状：中间有一次真实下降，可以自标定；但最后一次没扣。
    got = parse("""\
[2026-08-25 09:38:08.067] 当前理智 241/360
[2026-08-25 09:38:25.358] 进入协议空间成功
[2026-08-25 09:39:21.584] 当前理智 241/360
[2026-08-25 09:39:22.286] 尝试使用理智消耗许可
[2026-08-25 09:39:31.507] 进入协议空间成功
[2026-08-25 09:40:21.032] 当前理智 81/360
[2026-08-25 09:40:21.767] 尝试使用理智消耗许可
[2026-08-25 09:40:22.006] 理智不足，尝试不使用理智消耗许可
[2026-08-25 09:40:28.560] 理智不足，结束任务
""")
    check("最后一次没扣就不减", got.get("sanity"), 81)
    check("协议空间次数", got.get("protocol_runs"), 2)
    check("知道是理智不足才收工", got.get("sanity_exhausted"), True)

    print("\n[日志里有真实下降时，用实测值而不是兜底常量]")
    # 单次消耗 40 的场景（关卡等级不同）：最后一次扣成，应减 40 而不是 160。
    got = parse("""\
[2026-08-25 10:00:00.000] 当前理智 120/360
[2026-08-25 10:00:01.000] 尝试使用理智消耗许可
[2026-08-25 10:01:00.000] 当前理智 80/360
[2026-08-25 10:01:01.000] 尝试使用理智消耗许可
[2026-08-25 10:01:02.000] 确认领取奖励
""")
    check("按实测的 40 减，而不是兜底的 160", got.get("sanity"), 40)

    print("\n[一条读数都没有时不要瞎报]")
    check("没有理智行就不写这个字段",
          "sanity" in parse("[2026-08-25 09:00:00.000] 任务完成: 🎁基建任务\n"), False)

    print("\n[回满时间：MAA 自己写在 JSON 里，另外两个得算]")
    from datetime import datetime
    from ark_relay.core.config import SERVER_TZ
    ref = datetime(2026, 8, 25, 9, 42, tzinfo=SERVER_TZ)
    # 终末地每 7 分 12 秒 1 点：还差 279 点 → 2008.8 分钟 ≈ 33.5 小时。
    check("终末地 81/360 的回满时刻",
          collector._full_at_sentence(81, 360, collector._END_SANITY_SEC_PER_POINT, ref),
          "理智将在 2026-08-26 19:10 回满。")
    # 鸣潮每 6 分钟 1 点：还差 198 点 → 1188 分钟 = 19.8 小时。
    ref2 = datetime(2026, 8, 25, 13, 19, tzinfo=SERVER_TZ)
    check("鸣潮 42/240 的回满时刻",
          collector._full_at_sentence(42, 240, collector._OKWW_SEC_PER_POINT, ref2),
          "理智将在 2026-08-26 09:07 回满。")
    check("已经满了就不说回满", collector._full_at_sentence(240, 240, 360, ref2), "")
    check("超上限也不说", collector._full_at_sentence(400, 360, 432, ref), "")
    # 速率本身也钉住：改错了会让每天的报告都给出错误的时刻。
    check("终末地 7 分 12 秒", collector._END_SANITY_SEC_PER_POINT, 432)
    check("鸣潮 6 分钟", collector._OKWW_SEC_PER_POINT, 360)

    print("\n[自动采集：没走通的路线要点名，不只数个数（2026-09-11 那趟真实日志）]")
    real = Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11" / "automas-MaaEnd-06-17-17.log"
    got = collector.parse_maaend_log(real)
    check("走通 15/17（线路1-3 和 路线4-17 两种写法都算）", (got.get("maaend_collect_done"), got.get("maaend_collect_total")), (15, 17))
    check("没走通的名字", got.get("maaend_collect_failed"), ["路线15：红矛叶", "路线16：协议纹石"])
    check("没走通的路线号（给收窄用）", got.get("maaend_collect_failed_ids"), ["Route15", "Route16"])

    # Narrowing from records was removed on 2026-09-14 (AUTO-MAS writes all attempts'
    # records at the end of the task, so a record can never precede the retry); the
    # live-log version is tested in test_collect.py.
    print("\n[自动采集：不是采集日的 0 分钟不算「做了」（2026-09-05 周六真实日志）]")
    real = Path(__file__).resolve().parent / "replay" / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log"
    got = collector.parse_maaend_log(real)
    check("记下是哪天被排班跳过的", got.get("maaend_collect_skipped"), "周六")
    check("跳过的那天没有路线计数", "maaend_collect_total" in got, False)
    from ark_relay.core import ledger as _core
    _e = {"ok": True, "raw": got, "started": "2026-09-05T09:00:00+08:00"}
    _did, _cost, _out, _left, _notes = _core._block_maaend(_e, got, datetime(2026, 9, 5, 9, 55, tzinfo=SERVER_TZ))
    check("备注说的是按排班跳过", any("周六不是采集日" in n and "按排班跳过" in n for n in _notes), True)
    check("「做了」里不再出现自动采集", any("自动采集" in n and "做了" in n for n in _notes), False)


def _part_maaend_sanity_fit():
    """Endfield sanity is reported as a figure only when the log's readings fit the
per-claim rule (40 per 「补充理智」 booster, collector_maaend._claims_fit).

The real 10-08 MaaEnd-05-29-15.log fits: 237 - 160 + 1 booster = 117 read next.
With that one 「补充理智」 line taken out the same readings no longer fit
(237 - 160 = 77, yet 117 is read 79 s later): the report must say
「理智消耗没读到」, not a number. Before: 「理智 720，加强剂 13」.

    Formerly test_maaend_sanity_fit.py.
    """
    #!/usr/bin/env python3

    import tempfile
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import ledger_rows
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.verify.collector_maaend import parse_maaend_log

    LOG = Path(__file__).resolve().parent / "fixtures" / "maaend-sanity-1013" / "2026-10-08_MaaEnd-05-29-15.log"


    fin = datetime(2026, 10, 8, 9, 57, tzinfo=SERVER_TZ)


    def cost_row(o):
        return ledger_rows._block_maaend({"ok": True, "raw": o, "sanity": o.get("sanity")}, o, fin)[1]


    real = parse_maaend_log(LOG)
    require("real log fits: 720 spent", real.get("maaend_sanity_spent") == 720 and not real.get("maaend_sanity_unfit"),
            f"got {real.get('maaend_sanity_spent')!r}, unfit {real.get('maaend_sanity_unfit')!r}")
    require("real log cost row", cost_row(real) == ["理智 720，加强剂 14"], f"got {cost_row(real)!r}")

    lines = LOG.read_text(encoding="utf-8").splitlines(keepends=True)
    first = next(i for i, x in enumerate(lines) if "补充理智" in x)
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / LOG.name
        bad.write_text("".join(lines[:first] + lines[first + 1:]), encoding="utf-8")
        o = parse_maaend_log(bad)
    require("misfit: no spent figure", o.get("maaend_sanity_spent") is None, f"got {o.get('maaend_sanity_spent')!r}")
    require("misfit: not filled in later", o.get("maaend_sanity_runs_only") is None, f"got {o.get('maaend_sanity_runs_only')!r}")
    require("misfit: cost row says 没读到", cost_row(o) == ["理智消耗没读到，加强剂 13"], f"got {cost_row(o)!r}")


def _part_maaend_sanity_one_formula():
    """Endfield sanity spent and left come from one rule, checked on real logs.

Fixtures (fixtures/maaend-sanity-1013/) are the 协议空间 task of real machine
logs, movement and template-matcher lines dropped. Each expected 「left」 is
checked against the next run's first reading at ~1 sanity per 7.2 minutes:
  10-13 05:36  198, one double claim            -> 160 spent, 38 left
  10-07 05:29  277, double + half claim         -> 240 spent, 37 left (10-08 reads 237)
  10-08 05:29  237, 4 double + 1 half, 14 potions (「补充理智」, 40 each)
                                                -> 720 spent, 78 left (06:34 reads 85)
  10-08 06:34  85, one half claim               -> 80 spent, 5 left (10-09 reads 194)
Before: spent 0 for one run (two equal readings), 0 left after a half claim,
and the report row said 「理智不足，一次没开成」 on a run that claimed its reward.

    Formerly test_maaend_sanity_one_formula.py.
    """
    #!/usr/bin/env python3

    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import ledger_rows
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.verify.collector_maaend import parse_maaend_log

    D = Path(__file__).resolve().parent / "fixtures" / "maaend-sanity-1013"


    CASES = [
        ("2026-10-13_MaaEnd-05-36-57.log", 1, 160, 38, None),
        ("2026-10-07_MaaEnd-05-29-05.log", 2, 240, 37, None),
        ("2026-10-08_MaaEnd-05-29-15.log", 5, 720, 78, 14),
        ("2026-10-08_MaaEnd-06-34-21.log", 1, 80, 5, None),
    ]
    for name, runs, spent, left, potions in CASES:
        o = parse_maaend_log(D / name)
        check(f"{name} runs", o.get("maaend_farm_runs"), runs)
        check(f"{name} spent", o.get("maaend_sanity_spent"), spent)
        check(f"{name} left", o.get("sanity"), left)
        check(f"{name} potions", o.get("maaend_medicine"), potions)

    # The report row: a run that claimed is never 「一次没开成」, even with no figure.
    fin = datetime(2026, 10, 13, 9, 54, tzinfo=SERVER_TZ)
    raw = {"maaend_farm": "协议空间", "maaend_farm_runs": 1, "sanity_exhausted": True,
           "maaend_farm_drops": {"折金票": 68000}}
    _did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": raw}, raw, fin)
    check("ran, no figure: not 一次没开成", cost, ["理智消耗没读到"])
    raw = {"maaend_farm": "协议空间", "sanity_exhausted": True}
    _did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": raw}, raw, fin)
    check("no run, exhausted: 一次没开成", cost, ["理智不足，一次没开成"])
    o = parse_maaend_log(D / "2026-10-13_MaaEnd-05-36-57.log")
    _did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": o, "sanity": o["sanity"]}, o, fin)
    check("10-13 cost row", cost, ["理智 160，加强剂 0"])


def _part_maaend_update_after_done():
    """MaaEnd restarting itself into a new build after its shift's round was done: no make-up, no push.

relay.log, 10-04 09:51:26 (and the same shape 10-05 11:30:44), three lines in one
second: the round 2026-10-04/endfield/MaaEnd-05-26-41 booked as done (静默记账),
the attempt MaaEnd-05-50-53 held as MaaEnd's restart into v2.32.0-beta.1, then
the final failure pushed to the group (「最终失败，告警已推送（尝试 2 次）」).

The round had got everything done; the next attempt was only MaaEnd installing
v2.32.0-beta.1 and restarting. With no success after it, it was pushed as the
final failure; with the make-up rules it would have been held, given no make-up
and pushed to the group as unresolved. The user, 10-05 13:07: 「中继我就要求一个，
他不要再报错了」 - from then until 2026-10-06 such an attempt was a log line only.
His order of 2026-10-06, 「不论多少次什么错误都要发」, put it in the group under its
own title (「⚠️ 终末地装新版重启了这一趟（前面那趟已做完）」); at 05:07 that day he
took that back for what had recovered: 「报错后自己好了的，只进日报、不进群。」 The
round was done, so nothing is left broken. Pinned here:

* success first, then the update restart, in the same shift -> not held, no
  make-up, nothing pushed, one log line saying 「只进日报」; the ledger keeps it,
  and the daily report books it as the update (a ↪️ row naming the build), not
  as a failure;
* the same pair arriving the other way round -> the same;
* the success was in another shift -> the restart is held and rings as before;
* a success that left work undone does not count;
* 10-05's pair (06-39-48 / 07-30-14, v2.32.0-beta.2) -> dropped as well.

Started times are the run ids + 4 h, which matches every number in relay.log:
10-04 09:26:41 + 23 min ends 09:49, the restart starts 09:50:53, the records
land 09:51:26; 10-05 10:39:48 + 49 min ends 11:28, restart 11:30:14, land 11:30:44.

    Formerly test_maaend_update_after_done.py.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.alarm import handle, unresolved
    from ark_relay.core import ledger as core
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    def automas_dir(queues) -> Path:
        """An AUTO-MAS config dir shaped like the machine's: queues = [(name, [times], [kinds])]."""
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


    # The machine: 早班 09:00 runs MaaEnd, 晚班 21:30 is MAA only.
    MACHINE = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
    # For the other-shift case MaaEnd has to be in both.
    BOTH = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA", "MaaEnd"])])


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    class Lines(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    LINES = Lines()
    handle.log.addHandler(LINES)
    handle.log.setLevel(logging.DEBUG)

    handle._ship_evidence = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    collect_retry.restore_master = lambda cfg: ""


    def mxu_install(at: datetime, version: str) -> None:
        """MXU's own log for the attempt that installed `version` at its start."""
        f = MAAEND / "debug" / f"{at:%Y-%m-%d}-1.log"
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        s = at.strftime("%Y-%m-%d %H:%M:%S")
        f.write_text(old + "\n".join([
            f"{s} INFO  [App] 检测到待安装更新: {version}",
            f"{s} INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11002.zip -> D:\\ark\\maaend",
            f"{s} INFO  [App] 更新安装完成",
            f"{s} INFO  [App] 已清除待安装更新信息",
        ]) + "\n", encoding="utf-8")


    def t(day, hh, mm, ss=0):
        return datetime(2026, 10, day, hh, mm, ss, tzinfo=SERVER_TZ)


    def success(day, run, start, minutes):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(minutes=minutes), ok=True, failed_tasks=[],
                         raw={"maaend_result": "Success!"})


    def restart(day, run, start):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(seconds=30), ok=False,
                         failed_tasks=["赠送干员礼物", "据点交易", "日常奖励领取"],
                         raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})


    mxu_install(t(4, 9, 50, 53), "v2.32.0-beta.1")
    mxu_install(t(4, 21, 50, 53), "v2.32.0-beta.9")
    mxu_install(t(5, 11, 30, 14), "v2.32.0-beta.2")
    S4 = success(4, "05-26-41", t(4, 9, 26, 41), 23)
    R4 = restart(4, "05-50-53", t(4, 9, 50, 53))
    S5 = success(5, "06-39-48", t(5, 10, 39, 48), 49)
    R5 = restart(5, "07-30-14", t(5, 11, 30, 14))


    def build(automas, undone=None):
        cfg = Config()
        cfg.state_dir = tmpdir() / "state"   # its own tech/ next to it (techlog.tech_dir)
        cfg.automas_dir = automas
        cfg.maaend_dir = MAAEND
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: undone
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e


    def run(e, recs):
        LINES.lines.clear()
        for r in recs:
            handle._handle(e, r)
        e._flush_pending()
        return [(ti, b) for ti, b, a in e.notifier.sent if a]


    def said(fragment):
        return any(fragment in ln for ln in LINES.lines)


    DROPPED = "前面那趟已经做完"

    print("[10-04 as it landed: success, then the update restart, same second, same shift]")
    e = build(MACHINE)
    got = run(e, [S4, R4])
    check("nothing to the group", got, [])
    check("no notice of any kind (not Server酱 either)", e.notifier.sent, [])
    check("not held", dict(e._pending), {})
    check("no self-heal either", dict(e._recovered), {})
    check("the log says the earlier round was done, this was the update, daily report only",
          said(f"{R4.run_id} 前面那趟已经做完（{S4.run_id}），这趟是装新版 v2.32.0-beta.1 重启，只进日报"))
    check("no 「先压着」", said("先压着看后面的重试"), False)
    check("no 「最终失败」", said("最终失败"), False)
    ledger = {x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}
    check("the restart stays in the ledger, named as the update",
          (ledger.get(R4.run_id, {}).get("raw") or {}).get("maaend_update_restart"), "v2.32.0-beta.1")
    check("the success stays in the ledger", ledger.get(S4.run_id, {}).get("ok"), True)
    entries = e.state.read_ledger("2026-10-04")
    check("daily report books the restart as the update", core.episode_kinds(entries).get(R4.run_id), "update")
    tech: list = []
    title, body = core.format_daily("2026-10-04", entries, tech=tech)
    print("    " + title)
    print("    " + body.replace("\n", "\n    ")[:500])
    check("the daily title counts no MaaEnd failure", "终末地失败" in title, False)
    check("the daily row says it was the update", "终末地装了新版后自己重启，用掉一次重试，不算失败" in body)
    check("the version is in the technical log line, not the report",
          ("v2.32.0-beta.1" in body, any("MaaEnd 装新版 v2.32.0-beta.1" in t for t in tech)), (False, True))
    e._flush_pending()
    check("a later tick says nothing", e.notifier.sent, [])
    handle._handle(e, R4)      # the same record replayed (handling broke off midway)
    check("a replay of the same record says nothing either", e.notifier.sent, [])

    print("\n[the same pair the other way round: the update restart lands first]")
    e = build(MACHINE)
    got = run(e, [R4, S4])
    check("nothing to the group", got, [])
    check("not held", dict(e._pending), {})
    check("not turned into a self-heal", dict(e._recovered), {})
    check("the log says why", said(f"{R4.run_id} 前面那趟已经做完（{S4.run_id}）"))
    check("no 「重试后成功」 (nothing was retried)", said("重试后成功"), False)
    check("no notice of any kind", e.notifier.sent, [])
    check("the daily report books it as the update too",
          core.episode_kinds(e.state.read_ledger("2026-10-04")).get(R4.run_id), "update")

    print("\n[10-05 as it landed: 06-39-48 done, 07-30-14 installs v2.32.0-beta.2]")
    e = build(MACHINE)
    got = run(e, [S5, R5])
    check("nothing to the group", got, [])
    check("not held", dict(e._pending), {})
    check("the log says why", said(f"{R5.run_id} 前面那趟已经做完（{S5.run_id}），这趟是装新版 v2.32.0-beta.2 重启，只进日报"))

    print("\n[the success was in another shift: the restart is held and rings as before]")
    late = restart(4, "17-50-53", t(4, 21, 50, 53))
    e = build(BOTH)
    check("the two are in different shifts",
          (unresolved.where(e, S4)[1], unresolved.where(e, late)[1]), ("早班", "晚班"))
    got = run(e, [S4, late])
    check("not dropped", said(DROPPED), False)
    check("held, then one alarm for 晚班", (len(got), bool(got) and "晚班" in got[0][0]), (1, True))
    e = build(BOTH)
    got = run(e, [late, S4])
    check("reverse order: not dropped either", said(DROPPED), False)
    check("the daily report does not hide it", core.episode_kinds(e.state.read_ledger("2026-10-04")).get(late.run_id), None)

    print("\n[a success that left work undone does not count]")
    e = build(MACHINE, undone="MaaEnd 这一轮有 1 项没干成：\n· 据点交易：没做")
    LINES.lines.clear()
    handle._handle(e, S4)
    handle._handle(e, R4)
    check("not dropped", said(DROPPED), False)
    check("held as before", list(e._pending), [("MaaEnd", "endfield")])
    e = build(MACHINE, undone="MaaEnd 这一轮有 1 项没干成：\n· 据点交易：没做")
    LINES.lines.clear()
    handle._handle(e, R4)
    handle._handle(e, S4)
    check("reverse order: not dropped either", said(DROPPED), False)
    check("reverse order: the held restart takes the usual path (retry healed)",
          (list(e._pending), list(e._recovered)), ([], [("MaaEnd", "endfield")]))
    check("reverse order: not marked as the update on the ledger",
          ({x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}[R4.run_id].get("raw") or {})
          .get("maaend_update_after_done"), None)

    print("\n[a success stopped by the red button does not count]")
    e = build(MACHINE)
    e.state.append_ledger(S4)
    e.state.mark_raw("2026-10-04", S4.run_id, "manual_stop", "10-04 09:49 停一切")
    check("no done round", unresolved.done_in_shift(e, R4), "")
    e.state.mark_raw("2026-10-04", S4.run_id, "manual_stop", "")
    check("without the stop it is the done round", unresolved.done_in_shift(e, R4), S4.run_id)

    print("\n[without any success the restart is held as before (10-01's path)]")
    e = build(MACHINE)
    LINES.lines.clear()
    handle._handle(e, R4)
    check("held", list(e._pending), [("MaaEnd", "endfield")])
    check("「先压着」 as before", said("先压着看后面的重试"))


    def reds(e, fragment):
        """Red items in e's technical log whose text names `fragment`."""
        from ark_relay.core import techlog
        return [x for f in sorted(techlog.tech_dir(e.cfg.state_dir).glob("*.md"))
                for _, x in techlog.unhandled(f.read_text(encoding="utf-8")) if fragment in x]


    # 2026-10-12, relay.log 11:38:52 (machine check #6): MaaEnd-06-58-11 restarted into
    # v2.33.0-beta.2 and MaaEnd-06-58-38, started 27 s AFTER it, got everything done.
    # done_in_shift used to count that later round as "already done before the restart",
    # so the restart was let go as not-a-fault with no red item. A round after the restart
    # is the retry that healed it: the self-heal path, one red item, nothing pushed.
    mxu_install(t(12, 10, 58, 11), "v2.33.0-beta.2")
    R12 = restart(12, "06-58-11", t(12, 10, 58, 11))
    S12 = success(12, "06-58-38", t(12, 10, 58, 38), 30)

    print("\n[10-12: the success started after the restart lands first -> healed by retry, one red item]")
    e = build(MACHINE)
    e.state.append_ledger(S12)
    check("a round started after the restart is not the shift's done round", unresolved.done_in_shift(e, R12), "")
    e = build(MACHINE)
    got = run(e, [S12, R12])
    check("not let go as 「前面那趟已经做完」", said(DROPPED), False)
    check("nothing to the group", got, [])
    check("not held (its retry already got through)", (dict(e._pending), dict(e._recovered)), ({}, {}))
    check("one 「自愈待查」 red item naming the restart", len(reds(e, R12.run_id)), 1)
    check("the daily report books it as the update",
          core.episode_kinds(e.state.read_ledger("2026-10-12")).get(R12.run_id), "update")

    print("\n[10-12, the other way round: the restart lands first -> healed by retry, one red item]")
    e = build(MACHINE)
    got = run(e, [R12, S12])
    check("not let go as 「前面那趟已经做完」", said(DROPPED), False)
    check("nothing to the group", got, [])
    check("nothing left held", (dict(e._pending), dict(e._recovered)), ({}, {}))
    check("one 「自愈待查」 red item naming the restart", len(reds(e, R12.run_id)), 1)

    # 2026-10-12, relay.log lines 468-483: MaaEnd-06-04-00 failed on 协议空间 and was held;
    # the update restart MaaEnd-06-58-11 then replaced it in _pending, and the red item at
    # 11:38:52 named only 「装新版 v2.33.0-beta.2」 - the real failed task was lost.
    F12 = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-00", script="MaaEnd", user="endfield",
                    started=t(12, 10, 4, 0), finished=t(12, 10, 40, 0), ok=False, failed_tasks=["协议空间"],
                    raw={"maaend_result": "MaaEnd 部分任务执行失败: 协议空间"})

    print("\n[10-12: a held failure is not replaced by the update restart that follows it]")
    e = build(MACHINE)
    LINES.lines.clear()
    handle._handle(e, F12)
    handle._handle(e, R12)
    check("the held record is still the failure", [r.run_id for r in e._pending.values()], [F12.run_id])
    handle._handle(e, S12)
    e._flush_pending()
    check("nothing to the group", [x for x in e.notifier.sent if x[2]], [])
    check("the red item names the failure and its task",
          [("协议空间" in x) for x in reds(e, F12.run_id)], [True])


def _part_maaend_update_record():
    """AUTO-MAS's own MaaEnd update record is not a run; stage prefixes are not failures.

AUTO-MAS v5.7.0-beta.2 installs a MaaEnd update between stages and writes that
step as a history record of its own (app/task/MaaEnd/AutoProxy.py
_update_after_first_stage, the 「更新」 phase label at ~2203; Config.save_maaend_log
in app/core/config.py ~4387 puts 「[<label>] 」 in front of the result). Stage runs
get the same prefix: 「[送货]」「[日常]」「[自动采集]」 (app/utils/constants.py
MAAEND_RUN_MOOD_BOOK).

2026-10-12 Endfield, machine time (AUTO-MAS app.log lines 601-668 of
ark-evidence/daily/2026-10-12/automas-app-2026-10-12.log):
  10:04:00 MaaEnd-06-04-00  「MaaEnd 部分任务执行失败: ⚔️协议空间」  (Source stage, no prefix)
  10:58:11 MaaEnd-06-58-11  「[更新] Success!」  4 log lines, 「MaaEnd 已更新到 v2.33.0-beta.2」
  10:58:38 MaaEnd-06-58-38  「Success!」  (Source stage, attempt 2/3)
The relay booked the update record as a failed run, labelled it 「装新版 v2.33.0-beta.2
后自己重启，这一次重试被用掉」 and said 「跑了 3 次」 (relay-2026-10-12.log lines 472-483).
Should be: 2 runs, the first recovered by the retry, the update in the technical log only.

The raw history JSON/logs of that day are not on this Mac (the update record went to the
cloud evidence pack MaaEnd-06-58-11 only). The JSONs below are rebuilt from AUTO-MAS's
result lines and its save_maaend_log format; the update log is the four status lines
AUTO-MAS logged at 10:58:11-10:58:15; the MXU install lines are reconstructed to sit in
update_restart_version's window, as relay log line 475 shows they did.

    Formerly test_maaend_update_record.py.
    """
    import json
    import logging
    import os
    from datetime import datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HISTORY = TMP / "history"
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    os.environ.update(ARK_HISTORY_DIR=str(HISTORY), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector
    from ark_relay.features.alarm import errwatch
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import handle, records
    from ark_relay.features.makeup import collect_retry


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines: list[tuple[str, int, str]] = []

        def emit(self, r):
            self.lines.append((r.name, r.levelno, r.getMessage()))


    grab = Grab()
    logging.getLogger(errwatch.ARK).addHandler(grab)
    logging.getLogger(errwatch.ARK).setLevel(logging.DEBUG)


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    DAY = HISTORY / "2026-10-12" / "endfield"
    DAY.mkdir(parents=True)


    def write(stem, result, log_lines, mtime):
        (DAY / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False, indent=4),
                                          encoding="utf-8")
        (DAY / f"{stem}.log").write_text("".join(x + "\n" for x in log_lines), encoding="utf-8")
        t = datetime(2026, 10, 12, *mtime, tzinfo=SERVER_TZ).timestamp()
        for suffix in (".json", ".log"):
            os.utime(DAY / f"{stem}{suffix}", (t, t))


    CLOSE = "❌关闭游戏（PC）"

    # Attempt 1: 协议空间 fails, the round closes.
    write("MaaEnd-06-04-00", "MaaEnd 部分任务执行失败: ⚔️协议空间", [
        "[2026-10-12 10:04:05.000] 窗口连接成功: Endfield",
        "[2026-10-12 10:05:19.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-12 10:07:43.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-12 10:07:43.100] 任务开始: 🔧装备制造",
        "[2026-10-12 10:08:02.000] 任务完成: 🔧装备制造",
        "[2026-10-12 10:08:02.100] 任务开始: ⚔️协议空间",
        "[2026-10-12 10:57:50.000] 任务失败: ⚔️协议空间",
        f"[2026-10-12 10:57:50.100] 任务开始: {CLOSE}",
        f"[2026-10-12 10:57:53.000] 任务完成: {CLOSE}",
    ], (11, 38, 13))
    # AUTO-MAS's update step: its four status lines (AUTO-MAS app.log 605-608), no timestamps.
    write("MaaEnd-06-58-11", "[更新] Success!", [
        "首阶段检测到 MaaEnd 更新，正在确认安装结果",
        "正在准备 MaaEnd 更新会话",
        "MaaEnd 正在检查并安装更新",
        "MaaEnd 已更新到 v2.33.0-beta.2",
    ], (11, 38, 13))
    # Attempt 2: everything done.
    write("MaaEnd-06-58-38", "Success!", [
        "[2026-10-12 10:58:40.000] 窗口连接成功: Endfield",
        "[2026-10-12 10:59:55.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-12 11:01:43.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-12 11:01:43.100] 任务开始: 🔧装备制造",
        "[2026-10-12 11:01:59.000] 任务完成: 🔧装备制造",
        "[2026-10-12 11:01:59.100] 任务开始: ⚔️协议空间",
        "[2026-10-12 11:30:00.000] 任务完成: ⚔️协议空间",
        f"[2026-10-12 11:38:05.000] 任务开始: {CLOSE}",
        f"[2026-10-12 11:38:08.000] 任务完成: {CLOSE}",
    ], (11, 38, 13))
    # MXU's own log: the install AUTO-MAS triggered right after the update step began.
    (MAAEND / "debug" / "2026-10-12-4.log").write_text("\n".join([
        "2026-10-12 10:58:12 INFO  [App] 检测到待安装更新: v2.33.0-beta.2",
        "2026-10-12 10:58:13 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11021.zip -> D:\\ark\\maaend",
        "2026-10-12 10:58:14 INFO  [App] 更新安装完成",
    ]) + "\n", encoding="utf-8")

    handle._ship_evidence = lambda eng, rec: ""
    collect_retry.restore_master = lambda cfg: ""
    handle._weekly_gates = lambda eng, rec: None


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e


    def collector_lines(level):
        return [m for n, lv, m in grab.lines if n == "ark.collector" and lv == level]


    print("[10-12 replay: the collector sees two runs, not three]")
    got = collector.scan(HISTORY, set(), MAAEND)
    check("run ids", [r.run_id.rsplit("/", 1)[1] for r in got], ["MaaEnd-06-04-00", "MaaEnd-06-58-38"])
    check("verdicts", [(r.ok, r.failed_tasks) for r in got], [(False, ["协议空间"]), (True, [])])
    update_info = [m for m in collector_lines(logging.INFO) if "MaaEnd-06-58-11" in m]
    check("the update is one technical-log line", len(update_info), 1)
    check("it carries AUTO-MAS's words", bool(update_info) and "[更新] Success!" in update_info[0], True)
    check("no collector warning (group) for it", collector_lines(logging.WARNING), [])
    collector.scan(HISTORY, {r.run_id for r in got}, MAAEND)
    check("the next scan does not log it again",
          len([m for m in collector_lines(logging.INFO) if "MaaEnd-06-58-11" in m]), 1)

    print("\n[10-12 replay through the handler: recovered on retry, no update label]")
    grab.lines.clear()
    e = build()
    for r in got:
        handle._handle(e, r)
    e._flush_pending()
    ledger = e.state.read_ledger("2026-10-12")
    check("ledger rows", [x["run_id"].rsplit("/", 1)[1] for x in ledger], ["MaaEnd-06-04-00", "MaaEnd-06-58-38"])
    check("no 「重试被用掉」 anywhere in the ledger",
          any("重试被用掉" in t for x in ledger for t in x.get("failed_tasks") or []), False)
    check("no update-restart mark", [(x.get("raw") or {}).get("maaend_update_restart") for x in ledger], [None, None])
    check("attempts", records._attempts(e, got[-1], "2026-10-12"), 2)
    healed = [m for n, lv, m in grab.lines if "自己好了" in m]
    check("one recovery line", len(healed), 1)
    check("it says a retry healed it, ran 2 times",
          bool(healed) and healed[0].startswith("⚠️ MaaEnd 中途失败过，重试后成功") and "跑了 2 次" in healed[0], True)
    check("nothing says 重试被用掉", [m for n, lv, m in grab.lines if "重试被用掉" in m], [])
    # (Machine-check pushes about task-end pictures fire here because the fixture has none;
    # they are not about this record.)
    check("no push mentions the update", [t for t, b, a in e.notifier.sent if "更新" in t + b], [])


    def judge(stem, result, log_lines=("[2026-10-13 12:00:00.000] 窗口连接成功: Endfield",)):
        d = HISTORY / "2026-10-13" / "endfield"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False), encoding="utf-8")
        (d / f"{stem}.log").write_text("".join(x + "\n" for x in log_lines), encoding="utf-8")
        return collector.parse_record(d / f"{stem}.json", HISTORY, MAAEND)


    print("\n[stage prefixes are stripped before judging]")
    r = judge("MaaEnd-01-00-00", "[日常] Success!")
    check("[日常] Success! is a success", (r.ok, r.failed_tasks), (True, []))
    r = judge("MaaEnd-01-00-01", "[自动采集] MaaEnd 部分任务执行失败: 🧺自动采集")
    check("[自动采集] failure names its task", (r.ok, r.failed_tasks), (False, ["自动采集"]))
    r = judge("MaaEnd-01-00-02", "[送货] 未捕获到日志")
    check("[送货] stub stays transitional", (r.ok, r.transitional), (False, True))

    print("\n[update records]")
    grab.lines.clear()
    check("[更新] 跳过更新 is not a run", judge("MaaEnd-01-00-03", "[更新] 跳过更新"), None)
    check("…technical log only", ([m for m in collector_lines(logging.INFO) if "MaaEnd-01-00-03" in m] != [],
                                  collector_lines(logging.WARNING)), (True, []))
    upd_fail = "MaaEnd 更新失败，已停止后续任务: MXU 日志报告安装失败，已停止后续任务"
    r = judge("MaaEnd-06-58-11", f"[更新] {upd_fail}", [upd_fail])
    check("a failed update is a real failure", (r.ok, r.failed_tasks), (False, [upd_fail]))
    r.started = datetime(2026, 10, 12, 10, 58, 11, tzinfo=SERVER_TZ)   # inside the MXU install window
    records._mark_update_restart(build(), r)
    check("…the restart rule leaves it alone", (r.transitional, r.raw.get("maaend_update_restart")), (False, None))
    r = judge("MaaEnd-01-00-05", "[更新] MaaEnd 更新被中止")
    check("an aborted update is a real failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 更新被中止"]))

    print("\n[a failed update through the handler: booked as a failure, not as an update restart]")
    d14 = HISTORY / "2026-10-14" / "endfield"
    d14.mkdir(parents=True)
    (d14 / "MaaEnd-06-58-11.json").write_text(json.dumps({"maaend_result": f"[更新] {upd_fail}"}, ensure_ascii=False),
                                              encoding="utf-8")
    (d14 / "MaaEnd-06-58-11.log").write_text(upd_fail + "\n", encoding="utf-8")
    (MAAEND / "debug" / "2026-10-14-1.log").write_text(
        "2026-10-14 10:58:12 INFO  [App] 检测到待安装更新: v9.9.9\n2026-10-14 10:58:14 INFO  [App] 更新安装完成\n",
        encoding="utf-8")
    e14 = build()
    for rec in collector.scan(HISTORY, {x["run_id"] for d in ("2026-10-12", "2026-10-13")
                                        for x in e.state.read_ledger(d)} | {r.run_id for r in got}, MAAEND):
        if rec.run_id.startswith("2026-10-14/"):
            handle._handle(e14, rec)
    row = {x["run_id"]: x for x in e14.state.read_ledger("2026-10-14")}.get("2026-10-14/endfield/MaaEnd-06-58-11") or {}
    check("booked, failed, with AUTO-MAS's words, not relabelled",
          (row.get("ok"), row.get("failed_tasks"), (row.get("raw") or {}).get("maaend_update_restart"), row.get("transitional")),
          (False, [upd_fail], None, False))

    print("\n[an unknown prefix is not judged a success]")
    grab.lines.clear()
    r = judge("MaaEnd-01-00-06", "[新阶段] Success!")
    check("booked as a failure with AUTO-MAS's words", (r.ok, r.failed_tasks), (False, ["[新阶段] Success!"]))
    said = [m for m in collector_lines(logging.INFO) if "[新阶段]" in m]
    check("one technical-log line naming the prefix, no group warning",
          (len(said), collector_lines(logging.WARNING)), (1, []))
    judge("MaaEnd-01-00-06", "[新阶段] Success!")
    check("not repeated on the next read", len([m for m in collector_lines(logging.INFO) if "[新阶段]" in m]), 1)


def _part_maaend_update_restart():
    """A MaaEnd attempt spent installing its own update is not a game failure; healed, it is not pushed.

2026-10-01: the 15:24 attempt found v2.31.0-beta.6 and only downloaded it
(「已保存待安装更新信息」). The next launch, 16:11:06, installed it and restarted
MaaEnd; the process AUTO-MAS watched exited and all 15 tasks were booked failed.
The 16:12 attempt then succeeded. MXU log lines below are verbatim from
D:\\ark\\maaend\\debug\\2026-10-01-3.log / -4.log.

    Formerly test_maaend_update_restart.py.
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
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.alarm import handle
    from ark_relay.core import engine as eng_mod
    from ark_relay.features.verify.collector_maaend import update_restart_version
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


    (MAAEND / "debug" / "2026-10-01-3.log").write_text("\n".join([
        "2026-10-01 15:24:11 INFO  [App] 检查更新: MaaEnd, 当前版本: v2.31.0-beta.5, 频道: beta",
        "2026-10-01 15:24:12 INFO  [App] 发现新版本: v2.31.0-beta.6",
        "2026-10-01 15:24:14 INFO  [App] 已保存待安装更新信息: v2.31.0-beta.6",
    ]) + "\n", encoding="utf-8")
    (MAAEND / "debug" / "2026-10-01-4.log").write_text("\n".join([
        "2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6",
        "2026-10-01 16:11:06 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\10697.zip -> D:\\ark\\maaend",
        "2026-10-01 16:11:07 INFO  [App] 增量更新: deleted=0, added=0, modified=4",
        "2026-10-01 16:11:07 INFO  [App] 更新安装完成",
        "2026-10-01 16:11:07 INFO  [App] 已清除待安装更新信息",
    ]) + "\n", encoding="utf-8")

    FIFTEEN = ["赠送干员礼物", "装备制造", "拜访好友", "基建任务", "信用点购物", "转交委托", "据点交易",
               "环境监测", "自动囤货", "售卖弹性物资", "购买稳定物资", "协议空间", "选剑演武", "自动采集", "日常奖励领取"]


    def runs(with_success=True):
        out = [RunRecord(run_id="2026-10-01/endfield/MaaEnd-11-23-07", script="MaaEnd", user="endfield",
                         started=at(15, 24, 12), finished=at(16, 10, 0), ok=False,
                         failed_tasks=["MaaEnd 进程超时"], raw={"maaend_result": "MaaEnd 进程超时"}),
               RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-10-02", script="MaaEnd", user="endfield",
                         started=at(16, 11, 6), finished=at(16, 11, 6), ok=False, failed_tasks=list(FIFTEEN),
                         raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})]
        if with_success:
            out.append(RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-11-12", script="MaaEnd", user="endfield",
                                 started=at(16, 12, 15), finished=at(16, 58, 22), ok=True, failed_tasks=[],
                                 raw={"maaend_result": "Success!", "tasks_done": ["日常奖励领取"],
                                      "tasks_evidence": {"日常奖励领取": "获得 通行证经验 ×2000"}}))
        return out


    handle._ship_evidence = lambda eng, rec: ""
    collect_retry.restore_master = lambda cfg: ""
    handle._weekly_gates = lambda eng, rec: None


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e


    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]


    print("[the reader: only the attempt that installed counts]")
    check("16:11:06 attempt installed beta.6", update_restart_version(MAAEND, at(16, 11, 6)),
          "v2.31.0-beta.6")
    check("15:24 attempt only downloaded", update_restart_version(MAAEND, at(15, 24, 12)), "")
    check("no MaaEnd dir", update_restart_version(None, at(16, 11, 6)), "")

    print("\n[an attempt killed 50 s before the next one installs stays a failure]")
    (MAAEND / "debug" / "2026-10-02-1.log").write_text("\n".join([
        "2026-10-02 10:00:50 INFO  [App] 检测到待安装更新: v9.9.9",
        "2026-10-02 10:00:51 INFO  [App] 更新安装完成"]) + "\n", encoding="utf-8")
    killed_start = datetime(2026, 10, 2, 9, 20, tzinfo=SERVER_TZ)      # killed at 10:00:00
    check("the killed attempt is not the one that installed", update_restart_version(MAAEND, killed_start), "")
    check("the attempt that started at 10:00:50 is", update_restart_version(MAAEND, datetime(2026, 10, 2, 10, 0, 50, tzinfo=SERVER_TZ)), "v9.9.9")
    check("install line too long after the start does not count",
          update_restart_version(MAAEND, datetime(2026, 10, 2, 10, 0, 0, tzinfo=SERVER_TZ)), "")

    print("\n[10-01 replay: crash, update restart, success -> the update attempt is not a failure]")
    e = build()
    for r in runs():
        handle._handle(e, r)
    e._flush_pending()
    ledger = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}
    mid = ledger["2026-10-01/endfield/MaaEnd-12-10-02"]
    check("booked as an update restart", (mid.get("raw") or {}).get("maaend_update_restart"), "v2.31.0-beta.6")
    check("transitional in the ledger", mid.get("transitional"), True)
    check("its failure names the update, not 15 tasks", mid.get("failed_tasks"),
          ["MaaEnd 装新版 v2.31.0-beta.6 后自己重启，这一次重试被用掉"])
    # The rerun went through, so the day healed: nothing is pushed, the daily report
    # below carries the update attempt (↪️) and the 15:24 timeout (↻). The user, 2026-10-06
    # 05:07, on what fixed itself: 「报错后自己好了的，只进日报、不进群。」 From the morning of
    # 2026-10-06 until 05:07 it was pushed as 「⚠️ MaaEnd 更新时失败过，重跑后成功」.
    check("nothing pushed (the rerun went through: daily report only)", e.notifier.sent, [])
    check("nothing left held", (dict(e._pending), dict(e._recovered)), ({}, {}))

    print("\n[daily report: only the update attempt is an episode; the 15:24 crash stays listed]")
    from ark_relay.core import ledger as core
    entries = e.state.read_ledger("2026-10-01")
    kinds = core.episode_kinds(entries)
    check("16:11 update restart is the episode", kinds.get("2026-10-01/endfield/MaaEnd-12-10-02"), "update")
    check("15:24 crash is not folded into it", kinds.get("2026-10-01/endfield/MaaEnd-11-23-07"), None)
    check("15:24 reads as failed then retried", core.retried_notes(entries).get("2026-10-01/endfield/MaaEnd-11-23-07"),
          "MaaEnd 进程超时　后来在 16:12（东京 17:12）开始的那趟重试里做成了")
    tech: list = []
    title, body = core.format_daily("2026-10-01", entries, tech=tech)
    print("    " + title)
    print("    " + body.replace("\n", "\n    ")[:600])
    check("the crash line is there with ↻", any(l.startswith("↻ 终末地") for l in body.splitlines()), True)
    check("the update line is there with ↪️", any(l.startswith("↪️ 终末地") for l in body.splitlines()), True)
    check("its note names the update", "终末地装了新版后自己重启，用掉一次重试，不算失败" in body, True)
    check("the version goes to the technical log, not the report",
          ("v2.31.0-beta.6" in body, any("MaaEnd 装新版 v2.31.0-beta.6 后自己重启" in t for t in tech)), (False, True))

    print("\n[the title names the game: 10-01's full ledger shape]")
    okww = [{"run_id": f"o{i}", "script": "OK-WW", "user": "wuwa", "started": at(h, 0).isoformat(),
             "finished": at(h + 2, 0).isoformat(), "ok": False, "failed_tasks": ["OK-WW 运行超时"], "raw": {}}
            for i, h in enumerate((9, 11, 13))]
    done = dict(entries[-1], incomplete="MaaEnd 这一轮有 2 项没干成")
    t_full, _ = core.format_daily("2026-10-01", okww + entries[:-1] + [done])
    print("    " + t_full)
    # 2026-10-11 (验收): the three bare 鸣潮 failures in a row are one title item.
    check("title", t_full, "📋 10-01 · 鸣潮没跑成、终末地 1 项没干完 ⚠️")

    print("\n[a timeout clears only itself: a named task still undone keeps the record failed]")
    mixed = [dict(entries[0], failed_tasks=["MaaEnd 进程超时", "据点交易"]),
             dict(entries[-1], raw=dict(entries[-1]["raw"], tasks_done=["赠送干员礼物"]))]
    check("据点交易 not done later -> not retried", core.retried_notes(mixed), {})
    mixed[1]["raw"]["tasks_done"].append("据点交易")
    check("据点交易 done later -> retried", bool(core.retried_notes(mixed)), True)

    print("\n[all tasks done, MaaEnd did not exit: not 「没干完」, named as such]")
    from ark_relay.features.verify import outcome
    own = "2026-10-01 16:12:28 INFO  [Task] 实例 AUTO-MAS: 开始执行任务, 数量: 2\n"
    hung_log = own + ("[2026-10-01 16:12:29] 任务开始: 🎁赠送干员礼物\n[2026-10-01 16:14:10] 任务完成: 🎁赠送干员礼物\n"
                      "[2026-10-01 16:58:19] 任务开始: ❌关闭游戏（PC）\n[2026-10-01 16:58:22] 任务完成: ❌关闭游戏（PC）\n")
    shot = ["2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png"]
    check("no-exit detected", outcome.maaend_no_self_exit(hung_log, own_log=True), True)
    check("checks pass (screenshot counted as recovered)",
          outcome.summarize(outcome.maaend_checks(hung_log, shot, own_log=True), "MaaEnd"), None)
    check("a failed task is still a failure",
          outcome.maaend_no_self_exit(hung_log + "[2026-10-01 16:59:00] 任务失败: 🧺自动采集\n", own_log=True), False)
    print("    case 1: MaaEnd's own log not read (09-17 truncated shape)")
    history_only = hung_log.replace(own, "")
    check("not read -> not 「all done」", outcome.maaend_no_self_exit(history_only, own_log=False), False)
    check("not read -> still 「MaaEnd 跑完」 failed",
          "MaaEnd 跑完" in [c.label for c in outcome.maaend_checks(history_only, [], own_log=False) if not c.ok], True)
    print("    case 2: crashed between tasks - 16 scheduled, 2 began and finished")
    crashed = hung_log.replace("数量: 2", "数量: 16")
    check("unstarted scheduled tasks -> not 「all done」", outcome.maaend_no_self_exit(crashed, own_log=True), False)
    check("…and 「MaaEnd 跑完」 failed",
          "MaaEnd 跑完" in [c.label for c in outcome.maaend_checks(crashed, [], own_log=True) if not c.ok], True)
    hung = dict(entries[-1], raw=dict(entries[-1]["raw"], maaend_no_self_exit=29))
    hung.pop("incomplete", None)
    hung_tech: list = []
    t_hung, b_hung = core.format_daily("2026-10-01", okww + entries[:-1] + [hung], tech=hung_tech)
    print("    " + t_hung)
    # Not exiting by itself is the relay's own wrap-up (it closed it): technical log, not title or row.
    check("title", t_hung, "📋 10-01 · 鸣潮没跑成 ⚠️")
    check("no 「没干完」 anywhere", "没干完" in t_hung + b_hung, False)
    check("the technical log says it, the report does not",
          (any("终末地任务全完成，但跑完没自己退出（空等 29 分钟）" in t for t in hung_tech), "没自己退出" in b_hung), (True, False))

    print("\n[the idle minutes come from AUTO-MAS's own result line, onto the ledger]")
    (TMP / "debug").mkdir(exist_ok=True)
    (TMP / "debug" / "app.log").write_text(
        "2026-10-01 17:27:43.100 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放\n", encoding="utf-8")
    e9 = build()
    last = runs()[-1]
    e9.state.append_ledger(last)
    handle._mark_no_self_exit(e9, last)
    row = {x["run_id"]: x for x in e9.state.read_ledger("2026-10-01")}[last.run_id]
    check("16:58:22 -> 17:27:43 = 29 minutes on the ledger", (row.get("raw") or {}).get("maaend_no_self_exit"), 29)

    print("\n[the update ate the last attempt -> nothing got it done: one alarm for the shift; the ledger says it]")
    # A MaaEnd failure gets one make-up run (makeup.py); a day that has rolled over
    # is past its make-up, and the failure is still not fixed: the group hears of it
    # once (unresolved.py, the user 2026-10-05 15:38: 「你们不是没处理好吗？」).
    e = build()
    for r in runs(with_success=False):
        handle._handle(e, r)
    e._flush_pending()
    got = alarms(e)
    check("one alarm", len(got), 1)
    check("it names the game and says no make-up ran",
          bool(got) and got[0][0].startswith("❌ 终末地") and "没补跑：没等到补跑就过了零点" in got[0][1], True)
    check("no longer held", dict(e._pending), {})
    e._flush_pending()
    check("a second tick says nothing more", len(alarms(e)), 1)
    upd = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}["2026-10-01/endfield/MaaEnd-12-10-02"]
    check("the ledger names the update", (upd.get("raw") or {}).get("maaend_update_restart"), "v2.31.0-beta.6")
    check("the update attempt is counted: 2 attempts", handle._attempts(e, runs(False)[-1], "2026-10-01"), 2)

    print("\n[no install lines in MXU's log -> an ordinary failure, as before]")
    (MAAEND / "debug" / "2026-10-01-4.log").write_text("2026-10-01 16:11:06 INFO  [App] 启动\n", encoding="utf-8")
    e = build()
    for r in runs(with_success=False):
        handle._handle(e, r)
    mid = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}["2026-10-01/endfield/MaaEnd-12-10-02"]
    check("not marked", (mid.get("raw") or {}).get("maaend_update_restart"), None)
    check("keeps AUTO-MAS's 15 tasks", len(mid.get("failed_tasks") or []), 15)


def _part_maaend_update_restart_never_final():  # noqa: C901 - the whole body of the file this part was
    """A done MaaEnd round followed by MaaEnd restarting into its new build never ends in an alarm.

The operator, 2026-10-06: the only two group alarms of three days were both false,
10-04 09:51:26 and 10-05 11:30:44 (Beijing), each 「❌ MaaEnd 最终失败，告警已推送（尝试
2 次）」 right after 「✅ MaaEnd … 静默记账」 and 「↪️ … 是装新版 v2.32.0-beta.x 后的自重启，
先压着看后面的重试」. The user on it, 10-05 13:07: 「他不要再报错了」. Main fixed it on
10-05 (handle._drop_update_after_done, unresolved.done_in_shift); this drives the
same records through handle and the push step and pins that nothing reaches the
group - no alarm, no 「最终失败」, no WARNING / ERROR line (errwatch pushes those):

* the records as they landed (success, then the restart, then the push step);
* the restart landing while the shift could not be looked up (it is held), the
  push step then finds the done round and lets it go (handle._update_restart_done);
* the restart landing first, the success after it;
* a restart whose every task failed at once (the 「never got into the game」 shape):
  no 「像没进游戏…按普通失败处理」 WARNING about it (handle._confirm_unreachable).
Red on the code that sent those two alarms.

    Formerly test_maaend_update_restart_never_final.py.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.alarm import handle
    try:   # absent from the code that sent the two alarms (8f8250ea); the test still runs there
        from ark_relay.features.alarm import unresolved
    except ImportError:
        unresolved = None
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    def automas_dir() -> Path:
        """AUTO-MAS config as on the machine: 早班 09:00 runs MaaEnd, 晚班 21:30 is MAA only."""
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
        for k, p in paths.items():
            sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
        qc = {"instances": []}
        for n, (name, times, kinds) in enumerate((("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]),
                                                  ("晚班", ["21:30"], ["MAA"]))):
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


    MACHINE = automas_dir()


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

        def send_group(self, title, body=""):
            self.sent.append((title, body, True))
            return []


    class Src:
        def fetch(self, seen):
            return []


    class Lines(logging.Handler):
        """Every ark.* line, with its level: a WARNING / ERROR one reaches the group (errwatch)."""

        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelno, record.getMessage()))


    LINES = Lines()
    ARK = logging.getLogger(handle.log.name.rsplit(".", 1)[0])
    ARK.addHandler(LINES)
    ARK.setLevel(logging.DEBUG)

    handle._ship_evidence = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    collect_retry.restore_master = lambda cfg: ""


    def mxu_install(at: datetime, version: str) -> None:
        """MXU's own log for the attempt that installed `version` at its start (real shape, 10-01)."""
        f = MAAEND / "debug" / f"{at:%Y-%m-%d}-1.log"
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        s = at.strftime("%Y-%m-%d %H:%M:%S")
        f.write_text(old + "\n".join([
            f"{s} INFO  [App] 检测到待安装更新: {version}",
            f"{s} INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11002.zip -> D:\\ark\\maaend",
            f"{s} INFO  [App] 更新安装完成",
            f"{s} INFO  [App] 已清除待安装更新信息",
        ]) + "\n", encoding="utf-8")


    def t(day, hh, mm, ss=0):
        return datetime(2026, 10, day, hh, mm, ss, tzinfo=SERVER_TZ)


    def success(day, run, start, minutes):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(minutes=minutes), ok=True, failed_tasks=[],
                         raw={"maaend_result": "Success!"})


    def restart(day, run, start, raw=None):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(seconds=30), ok=False,
                         failed_tasks=["赠送干员礼物", "据点交易", "日常奖励领取"],
                         raw=dict(raw or {}, maaend_result="MaaEnd 部分任务执行失败: 🎁赠送干员礼物"))


    # The two mornings, run ids + 4 h as relay.log shows them (the _part_maaend_update_after_done part).
    mxu_install(t(4, 9, 50, 53), "v2.32.0-beta.1")
    mxu_install(t(5, 11, 30, 14), "v2.32.0-beta.2")


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = MACHINE
        cfg.maaend_dir = MAAEND
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        return e


    def drive(e, recs, flushes=1):
        LINES.lines.clear()
        for r in recs:
            handle._handle(e, r)
        for _ in range(flushes):
            e._flush_pending()


    def said(fragment):
        return any(fragment in m for _, m in LINES.lines)


    def alarms(e):
        return [ti for ti, _, a in e.notifier.sent if a]


    def loud(e):
        """WARNING / ERROR lines: errwatch pushes each one to the group."""
        return [m for lv, m in LINES.lines if lv >= logging.WARNING]


    for day, s_run, s_at, mins, r_run, r_at in ((4, "05-26-41", t(4, 9, 26, 41), 23, "05-50-53", t(4, 9, 50, 53)),
                                                 (5, "06-39-48", t(5, 10, 39, 48), 49, "07-30-14", t(5, 11, 30, 14))):
        S, R = success(day, s_run, s_at, mins), restart(day, r_run, r_at)
        print(f"\n[10-0{day} as it landed: {S.run_id} done, then {R.run_id} restarts into its new build, then the push step]")
        e = build()
        drive(e, [S, R], flushes=2)
        check("the round was booked silently (「✅ … 静默记账」)", said(f"✅ MaaEnd {S.run_id}（{mins} 分钟）静默记账"))
        check("no 「最终失败」", said("最终失败"), False)
        check("no alarm of any kind went to the group", alarms(e), [])
        check("no WARNING / ERROR line (errwatch would push it)", loud(e), [])
        check("nothing held for a later push", dict(e._pending), {})

    print("\n[the shift could not be looked up when the restart landed: held; the push step lets it go]")
    S, R = success(4, "05-26-41", t(4, 9, 26, 41), 23), restart(4, "05-50-53", t(4, 9, 50, 53))
    e = build()
    real = getattr(unresolved, "done_in_shift", None) if unresolved is not None else None
    check("unresolved.done_in_shift exists", real is not None)
    if real is not None:
        calls = []

        def flaky(eng, rec):
            calls.append(rec.run_id)
            if len(calls) == 1:
                raise OSError("ledger busy")
            return real(eng, rec)
        unresolved.done_in_shift = flaky
        try:
            LINES.lines.clear()
            handle._handle(e, S)
            handle._handle(e, R)
            check("held when the lookup failed", list(e._pending), [("MaaEnd", "endfield")])
            e._flush_pending()
            e._flush_pending()
        finally:
            unresolved.done_in_shift = real
        check("let go at the push step: nothing held", dict(e._pending), {})
        check("no alarm went to the group", alarms(e), [])
        check("no 「最终失败」", said("最终失败"), False)
        check("the log says why", said(f"{R.run_id} 前面那趟已经做完（{S.run_id}）"))
        led = {x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}
        check("the ledger books the restart as the update",
              (led[R.run_id].get("raw") or {}).get("maaend_update_after_done"), S.run_id)

    print("\n[the restart lands first, the done round after it]")
    S, R = success(5, "06-39-48", t(5, 10, 39, 48), 49), restart(5, "07-30-14", t(5, 11, 30, 14))
    e = build()
    drive(e, [R, S], flushes=2)
    check("no alarm went to the group", alarms(e), [])
    check("no 「最终失败」", said("最终失败"), False)
    check("no WARNING / ERROR line", loud(e), [])
    check("nothing held", (dict(e._pending), dict(e._recovered)), ({}, {}))

    print("\n[every task of the restart failed at once (the 「never got into the game」 shape)]")
    S = success(4, "05-26-41", t(4, 9, 26, 41), 23)
    R = restart(4, "05-50-53", t(4, 9, 50, 53), raw={"maaend_unreachable_shape": True})
    e = build()
    drive(e, [S, R], flushes=2)
    check("no 「像没进游戏…按普通失败处理」 WARNING about the restart", [m for m in loud(e) if "像没进游戏" in m], [])
    check("no WARNING / ERROR line at all", loud(e), [])
    check("no alarm went to the group", alarms(e), [])
    check("the record carries no 「never got in」 note for an alarm", R.raw.get("maaend_unreachable_shape"), None)


def _part_maaend_watchdog_onepush():
    """One MaaEnd hang the watchdog ends, one group message (验收 2026-10-11 22:5x).

Watchdog._end sent the ⚠️ group alarm for a crash / stall / plugin-gone, or a kill
that did not take, and logged the 「MaaEnd 卡死」 WARNING right before it, which
errwatch pushed to the group too: one event, two group messages (three for a crash: the crash line itself was a
WARNING too). The crash line is INFO now (the kill's push names the crash and
its code), and the 「卡死」 WARNING now
follows the send and carries errwatch.group_pushed, so it stays out of the group
only when the ⚠️ really reached the group robot; a refused send, or one that fell
back to Server酱, leaves the WARNING to errwatch and the fault still reaches the
group once.

Replayed with test_maaend_watchdog.py's shapes (the 2026-10-01 15:30:03 go-service
crash, maafw.log standing still 10 minutes, go-service gone twice 60 s apart) and
errwatch attached (its group robot refuses, so what it would push stays readable
in pending()). Group messages per event, before -> after (A/B of the code before
and after this change on these shapes): crash 3 -> 1, stall 2 -> 1, plugin gone
2 -> 1, kill that did not take 4 -> 2 - the second is machine check #31's FAIL, a
check of its own pushed every time it is judged (docs/NOTIFICATIONS.md 🔬 row).

    Formerly test_maaend_watchdog_onepush.py.
    """
    import logging
    import os


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.run import maaend_watchdog


    CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
    RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    MAAEND_PID = 21260
    ALL_UP = [("System", 4), ("Endfield.exe", 18800), ("MaaEnd.exe", MAAEND_PID),
              ("go-service.exe", 21932), ("cpp-algo.exe", 21940)]
    NO_GO = [p for p in ALL_UP if p[0] != "go-service.exe"]
    ROBOT = "企业微信机器人"


    class Notes:
        """The relay's notifier: `refuse` returns errors, `fallback` delivers by Server酱 instead of the robot."""

        def __init__(self, refuse=False, fallback=False):
            self.sent, self.refuse, self.fallback = [], refuse, fallback

        def send(self, title, body="", **kw):
            self.sent.append(title)
            return ["企业微信机器人：拒收", "Server酱：拒收"] if self.refuse else []

        def went_to_group(self):
            return not self.fallback


    class Refuses:
        """errwatch's own notifier: the group refuses, so what it queues stays queued (readable)."""

        def send_group(self, title, body):
            return [f"{ROBOT}：拒收"]

        def send(self, title, body, **kw):
            return ["拒收"]


    ARK_LOGGER = logging.getLogger(errwatch.ARK)


    class Rig:
        def __init__(self, notes, kill_ok=True, state_dir=None):
            self.t, self.lines, self.stamp = 1000.0, 0, "2026-10-01 15:20:00"
            self.procs, self.kill_ok, self.killed, self.notes = list(ALL_UP), kill_ok, [], notes
            self.debug = tmpdir() / "debug"
            self.debug.mkdir()
            self.stderr = self.debug / "go-service.stderr.log"
            self.stderr.write_text("", encoding="utf-8")
            agent = str(self.debug.parent / "agent")
            paths = {21932: os.path.join(agent, "go-service.exe"), 21940: os.path.join(agent, "cpp-algo.exe")}
            self.dog = maaend_watchdog.Watchdog(
                notes, self.debug, clock=lambda: self.t, snapshot=lambda: RUNNING,
                processes=lambda: list(self.procs), kill=self._kill, plugin_paths=lambda: paths,
                active=True, state_dir=state_dir)
            self.h = errwatch.ErrorKindAlert(Refuses(), state_dir=tmpdir() / "ew", known={}, retry=(3600.0,),
                                             fallback_after=1e9)
            ARK_LOGGER.addHandler(self.h)

        def _kill(self, pid, image):
            self.killed.append(pid)
            if not self.kill_ok:
                return False, "退出码 128"
            self.procs = [p for p in self.procs if p[1] != pid]
            return True, ""

        def step(self, seconds, new_lines=0, stamp=None):
            self.t += seconds
            self.lines += new_lines
            self.stamp = stamp or self.stamp
            return self.dog.tick(self.lines, self.stamp)

        def run_for(self, seconds, every=60, **kw):
            for _ in range(int(seconds // every)):
                self.step(every, **kw)

        def group(self):
            """Everything that went or would go to the group: the watchdog's own sends, then errwatch's queue."""
            return list(self.notes.sent) + [str(x.get("line"))[:40] for x in self.h.pending()]

        def done(self):
            ARK_LOGGER.removeHandler(self.h)
            self.h.close()


    def crash(r):
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)


    print("[2026-10-01 go-service crash -> MaaEnd ended: one group message, the ⚠️]")
    r = Rig(Notes())
    crash(r)
    check("ended MaaEnd and its plugins", r.killed, [MAAEND_PID, 21932, 21940])
    check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.run_for(600)
    check("nothing more for the same PID", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.done()

    print("\n[maafw.log stood still 10 minutes -> ended: one group message]")
    r = Rig(Notes())
    r.run_for(300, new_lines=50, stamp="2026-10-01 15:30:03")
    r.run_for(600)
    check("ended", r.killed[:1], [MAAEND_PID])
    check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.done()

    print("\n[go-service gone twice 60 s apart -> ended: one group message]")
    r = Rig(Notes())
    r.run_for(240, new_lines=20)
    r.procs = NO_GO
    r.step(60, new_lines=5)
    r.step(60, new_lines=5)
    check("ended MaaEnd and cpp-algo", r.killed, [MAAEND_PID, 21940])
    check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.done()

    print("\n[the kill did not take -> the ⚠️, plus machine check #31's FAIL (a check of its own)]")
    r = Rig(Notes(), kill_ok=False, state_dir=tmpdir() / "relaystate")
    crash(r)
    check("group: ⚠️ 没能结束 and 🔬 #31, no 「卡死」 WARNING",
          [t[:12] for t in r.group()], [texts.MAAEND_STUCK_KILL_FAILED[:12], "🔬 上机核对没过：#31"])
    r.done()

    print("\n[the ⚠️ send was refused -> the WARNING is pushed instead: the fault still reaches the group once]")
    r = Rig(Notes(refuse=True))
    crash(r)
    check("errwatch queues the 「卡死」 WARNING", [x[:9] for x in r.group()[1:]], ["MaaEnd 卡死"])
    r.done()

    print("\n[the ⚠️ fell back to Server酱 -> the WARNING goes to the group]")
    r = Rig(Notes(fallback=True))
    crash(r)
    check("errwatch queues the 「卡死」 WARNING", [x[:9] for x in r.group()[1:]], ["MaaEnd 卡死"])
    r.done()

    print("\n[audit 11-08 B-06: a kill restarts the shift's overrun clock, as MAA's does]")
    from datetime import datetime as _dt
    from ark_relay.core.config import SERVER_TZ as _TZ
    from ark_relay.core.statestore import StateStore as _SS
    _sd = tmpdir() / "relaystate-mark"
    r = Rig(Notes(), state_dir=_sd)
    r.dog.wall = lambda: _dt(2026, 11, 8, 10, 31, 5, tzinfo=_TZ)
    crash(r)
    r.run_for(600)
    check("killed", bool(r.killed), True)
    check("「超时|MaaEnd|10:31:05」 is left for runwatch.retry_clock",
          "超时|MaaEnd|10:31:05" in (_SS(_sd).get("marks", "alerted:2026-11-08") or []), True)
    r.done()
    r = Rig(Notes(), kill_ok=False, state_dir=tmpdir() / "relaystate-nokill")
    r.dog.wall = lambda: _dt(2026, 11, 8, 10, 31, 5, tzinfo=_TZ)
    crash(r)
    r.run_for(600)
    check("a failed kill leaves no mark (nothing restarts)",
          _SS(r.dog.state_dir).get("marks", "alerted:2026-11-08"), None)
    r.done()


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_maaend_no_d3d11_alarm, _part_maaend_essence_met, _part_maaend_essence_stamina_out, _part_maaend_full_at_anchor, _part_maaend_round_upper_bound, _part_maaend_sanity, _part_maaend_sanity_fit, _part_maaend_sanity_one_formula, _part_maaend_update_after_done, _part_maaend_update_record, _part_maaend_update_restart, _part_maaend_update_restart_never_final, _part_maaend_watchdog_onepush]))
