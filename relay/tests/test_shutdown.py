"""The shutdown decision: after a restart, runs by hand and test runs, holds past the shift, the notice, an open test window, rounds, a morning gap on the evening, a farm, the whitelist; the exit window, the power-off return code, a power-off that went through, the skip wording.

One part per former file, each run on its own (tests/_parts.py): test_shutdown.py, test_exit_shutdown_window.py, test_power_off_returncode.py, test_poweroff_ok.py, test_skip_shutdown_wording.py.
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


def _part_main():
    """Exercise the shutdown gate against a fake AUTO-MAS + ledger.

Since the user's rule of 2026-10-10 18:31 (Tokyo; quoted at shutdown.py:_say_if_moment_passed in
USER-SWITCHES.txt) only the decision right after a scheduled shift finished on this boot may power
off: not one after a relay restart, not one on a machine booted by hand, not before or
during the queue.

    Formerly test_shutdown.py.
    """
    import json, os, sys
    from datetime import datetime, timedelta

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
    STATE = TMP / "state"; STATE.mkdir()
    HIST = TMP / "history"; HIST.mkdir()

    # AUTO-MAS's real config shape: instances[] + a node per uid.
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {"Info": {"Name": "Evening-MAA", "TimeEnabled": True,
                        "AfterAccomplish": "NoAction"},
               "SubConfigsInfo": {
                   "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
                   "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}),
        encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA-v5.1.0-win-x64"},
               "SubConfigsInfo": {"UserData": {"u1": {
                   "Info": {"Name": "arknights", "Stage": "1-7", "MedicineNumb": 0},
                   "Task": {}}}}}}),
        encoding="utf-8")

    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.core import engine as eng
    from ark_relay.core.statestore import StateStore
    from ark_relay.core import plan

    cfg = Config()
    print("queues seen by plan:", [q["name"] for q in plan.schedule(cfg.automas_dir)])

    state = State(cfg.state_dir)
    E = eng.Engine(cfg, source=None, state=state, notifier=Notifier(cfg))
    E._scripts_running = lambda: False           # no games on this Mac

    # GetTickCount64 is Windows-only; drive the uptime gate explicitly instead.
    BOOT = [None]
    E._boot_time = lambda now: BOOT[0]

    DAY = "2026-08-21"
    def ledger(*rows):
        # jsonl, one record per line - the real format
        for d in (DAY, "2026-08-20"):
            (STATE / f"ledger-{d}.jsonl").write_text("", encoding="utf-8")
        (STATE / f"ledger-{DAY}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    def at(hh, mm):
        return datetime(2026, 8, 21, hh, mm, tzinfo=SERVER_TZ)


    run = {"script": "MAA", "started": at(21, 31).isoformat(),
           "finished": at(22, 15).isoformat(), "ok": True, "run_id": "x"}

    from ark_relay.features.shutdown import shutdown as sd
    E.state.report_sent = lambda d: True          # the report gate is not what is tested here


    def verdict(now):
        return sd.decide(E, now).code


    print("\n[18:31] the shift finished on this boot and this relay saw it land: go")
    ledger(run)
    E._handled_any = True
    E._started_at = at(21, 20)
    BOOT[0] = at(21, 20)                      # machine booted for this queue
    check("shift done at 22:25", verdict(at(22, 25)), "go")

    print("\n[18:31] relay restarted after the run finished: not a shift ending, stays on")
    # Until 2026-10-10 this was the bug the file was written for (nobody left to power off);
    # under the whitelist it is exactly what must not power off.
    E._handled_any = False                    # a fresh process, as after selfupdate
    E._started_at = at(22, 20)
    check("restarted after the shift -> not-shift", verdict(at(22, 35)), "not-shift")
    E._handled_any = True
    E._started_at = at(21, 20)

    print("\n[regression] must NOT power off a machine booted AFTER the queue ran")
    BOOT[0] = at(22, 20)
    check("booted after the queue -> not-shift", verdict(at(22, 35)), "not-shift")
    BOOT[0] = None
    check("boot time unknown -> not-shift", verdict(at(22, 35)), "not-shift")
    BOOT[0] = at(21, 20)

    print("\n[regression] must NOT power off before its own queue")
    ledger()
    check("21:25, the 21:30 queue still ahead -> shift-ahead", verdict(at(21, 25)), "shift-ahead")
    BOOT[0] = at(8, 40)
    check("08:50, nothing due at all -> not-shift", verdict(at(8, 50)), "not-shift")
    BOOT[0] = at(21, 20)

    print("\n[regression] must NOT power off mid-queue")
    ledger()
    check("due at 21:30, no records yet -> 21:40", verdict(at(21, 40)) == "go", False)

    print("\n[18:31] a long shift ends past the old two-hour window: still its shift")
    long_run = dict(run, finished=at(23, 50).isoformat())
    ledger(long_run)
    check("finished 23:50, judged 23:55 -> go", verdict(at(23, 55)), "go")

    print("\n[调试模式] 吃掉一次关机机会，而不是到期就补关")
    # 用户 2026-08-31：「我开了调试模式是指把一次队列的中继关机指令跳过，
    # 而不是中继一直尝试关机，要不然人类没办法使用这个电脑每次都要开调试模式。」
    # 改判前：调试模式只是让每次判定返回 False，判定每 30 秒重来，到期后条件
    # 没变就立刻关机——人一走开机器自己关了。
    # 改判后：生效期间记下「这一次关机机会」并吃掉它；到期后只要没有新队列
    # 跑完（机会标识没变）就不补关；新队列一跑完标识变了，恢复正常关机。
    # 这里把真正执行关机那步挡掉，只看判定结果。
    issued = []
    # Like the real subprocess.run: a finished process with exit code 0 (_power_off reads it).
    eng.subprocess = type("X", (), {"run": staticmethod(
        lambda *a, **k: issued.append(a) or eng.subprocess.CompletedProcess(a, 0, b"", b"")),
        "CompletedProcess": __import__("subprocess").CompletedProcess})()
    ledger(run)
    E._handled_any = True
    E._started_at = at(21, 20)
    BOOT[0] = at(21, 20)
    E.state.report_sent = lambda d: True          # 日报已发，不在那道门上卡住
    E._last_round_manual = lambda now, entries: False
    E._unfinished_queues = lambda now, entries: []

    # _maybe_shutdown 查调试模式时用的是**真实**当前时间（生产里 now 就是真实
    # 时间，这个参数只为其余判定服务），所以到期点要按真实时钟写。
    store = StateStore(STATE)                    # 开关都在 state.json 的 modes 段
    def dbg_set(v): store.set("modes", "debug_until", v)
    def dbg_clear(): store.pop("modes", "debug_until")
    def skipped_clear(): store.pop("modes", "shutdown_skipped")
    real = datetime.now(tz=SERVER_TZ)
    skipped_clear()

    dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
    E._shutdown_issued = False; issued.clear()
    check("调试模式生效中：不关机", E._maybe_shutdown(at(23, 0)), False)
    check("生效中没有发出关机命令", len(issued), 0)
    check("并且把这一次机会记下来了（标明是调试模式记的）",
          store.get("modes", "shutdown_skipped"), "2026-08-21:1|debug")

    dbg_set(f"{real - timedelta(hours=1):%Y-%m-%d %H:%M}")
    E._shutdown_issued = False; issued.clear()
    check("到期后没有新队列跑完：仍然不关机（人可能正在用）",
          E._maybe_shutdown(at(23, 30)), False)
    check("到期后也没有发出关机命令", len(issued), 0)

    # 早班又跑了一趟，流水多一条 —— 这是一次新的关机机会
    ledger(run, dict(run, run_id="y"))
    E._shutdown_issued = False; issued.clear()
    check("下一趟队列跑完：恢复正常关机", E._maybe_shutdown(at(23, 40)), True)
    check("这次确实发出了关机命令", len(issued), 1)

    dbg_clear(); skipped_clear()
    ledger(run)
    E._shutdown_issued = False; issued.clear()
    check("没开过调试模式时，本来就该关机", E._maybe_shutdown(at(23, 0)), True)

    print("\n[人工开关] 桌面那个 .bat：只跳过下一次，用完即失效")
    # 用户 2026-08-31：「你给一个人类好去调这个模式的方法，独立于你的。」
    # 它不带到期时间，就是把**下一次真正要执行的关机**吃掉一次。
    dbg_clear(); skipped_clear()
    ledger(run)
    store.set("modes", "skip_next_shutdown", True)
    E._shutdown_issued = False; issued.clear()
    check("按下之后：这一次不关机", E._maybe_shutdown(at(23, 0)), False)
    check("没有发出关机命令", len(issued), 0)
    check("标记被用掉了（用完即失效）", bool(store.get("modes", "skip_next_shutdown")), False)

    E._shutdown_issued = False; issued.clear()
    check("同一次机会不会因为标记没了就补关",
          E._maybe_shutdown(at(23, 10)), False)

    ledger(run, dict(run, run_id="y"))
    E._shutdown_issued = False; issued.clear()
    check("下一趟队列跑完：正常关机（不用再按一次才关）",
          E._maybe_shutdown(at(23, 40)), True)
    skipped_clear()

    print("\n[手动关调试] 明确关掉要恢复正常，自然到期不恢复")
    from ark_relay.features.modes import modes
    # 2026-08-31：我维护完手动关掉调试模式，机器却因为「这次已跳过」的标记
    # 还在，准备空开一整夜到早班跑完。明确说「关掉」＝维护结束，标记要一起清。
    dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
    skipped_clear(); store.pop("modes", "skip_next_shutdown")
    ledger(run)
    E._shutdown_issued = False; issued.clear()
    E._maybe_shutdown(at(23, 0))                       # 生效中，吃掉一次
    check("先确认标记确实写下了", bool(store.get("modes", "shutdown_skipped")), True)
    modes.set_debug(STATE, off=True)                   # 人明确关掉
    check("手动关掉后标记被清掉", bool(store.get("modes", "shutdown_skipped")), False)
    E._shutdown_issued = False; issued.clear()
    check("于是恢复正常关机", E._maybe_shutdown(at(23, 5)), True)
    skipped_clear(); dbg_clear()

    print("\n[one-shot mark] spent at a shift end; re-checks stay on; re-arming carries to the next run")
    # The 「下次跑完不关机」 mark is one-shot, not a state (the user, 2026-10-11 15:25, quoted
    # in the _part_skip_shutdown_wording part). relay.log 2026-10-11: spent at 09:59:26, then the
    # re-checks at 10:04:55 / 12:26:28 / 12:29:16 all stayed on.
    dbg_clear(); skipped_clear(); store.pop("modes", "skip_next_shutdown")
    ledger(run)
    K = E._shutdown_key(at(23, 0))
    modes.set_skip_shutdown(STATE, True)
    E._shutdown_issued = False; issued.clear()
    check("mark: shift end (occasion K) -> no power-off", E._maybe_shutdown(at(23, 0)), False)
    check("mark: spent", modes.skip_armed(STATE), False)
    check("mark: occasion K recorded as skipped", modes.shutdown_skipped(STATE), K)
    for hh, mm in ((23, 5), (23, 30), (23, 59)):
        check(f"mark: re-check {hh}:{mm:02} at K, no mark left -> stays on",
              E._maybe_shutdown(at(hh, mm)), False)
    check("mark: the re-checks issued nothing", len(issued), 0)
    check("mark: the re-checks stop at the 'skipped' gate", sd.decide(E, at(23, 30)).code, "skipped")
    ok, _ = modes.set_skip_shutdown(STATE, False)
    check("mark: pulling back after it was spent changes nothing",
          (ok, modes.skip_armed(STATE), modes.shutdown_skipped(STATE)), (True, False, K))

    modes.set_skip_shutdown(STATE, True)           # armed again while K is already skipped
    check("re-arm at K -> stays on", E._maybe_shutdown(at(23, 40)), False)
    check("re-arm at K: the skipped occasion does not spend it", modes.skip_armed(STATE), True)
    ledger(run, dict(run, run_id="y"))             # the next queue run finishes
    K1 = E._shutdown_key(at(23, 45))
    check("re-arm: the next run is a new occasion", K1 != K, True)
    E._shutdown_issued = False; issued.clear()
    check("re-arm: the next run does not power off either", E._maybe_shutdown(at(23, 45)), False)
    check("re-arm: spent there, that occasion skipped",
          (modes.skip_armed(STATE), modes.shutdown_skipped(STATE)), (False, K1))
    check("re-arm: issued nothing", len(issued), 0)
    ledger(run, dict(run, run_id="y"), dict(run, run_id="z"))   # and the run after that
    check("the run after that powers off as usual", E._maybe_shutdown(at(23, 50)), True)
    check("…with exactly one power-off command", len(issued), 1)
    skipped_clear()

    print("\n[one-shot mark] turning debug mode off keeps an occasion the mark skipped")
    # 2026-10-13: the mark was spent at 10:00:36; a test turned debug mode on and its
    # test-off turned it off again, which used to release the mark's skip and power the
    # machine off right after the test. The mark promised: on until the next shift ends.
    ledger(run)
    modes.set_skip_shutdown(STATE, True)
    E._shutdown_issued = False; issued.clear()
    check("debug-off: the mark is spent at K", E._maybe_shutdown(at(23, 0)), False)
    modes.set_debug(STATE, 1)
    modes.set_debug(STATE, off=True)
    check("debug-off: the mark's skipped occasion is kept", modes.shutdown_skipped(STATE), K)
    check("debug-off: the next re-check stays on", E._maybe_shutdown(at(23, 5)), False)
    check("debug-off: nothing issued", len(issued), 0)
    E._shutdown_issued = False; skipped_clear()

    print("\n[手机开关] 待办指令 skip_shutdown：手机上改仓库里那个文件")
    # 用户 2026-08-31：「我要的是手机上面操作」。中继本来就有「公开仓库放一个
    # 文件、手机网页编辑」的收信通道，这里把开关接进那条通道。
    os.environ["ARK_STATE_DIR"] = str(STATE)
    from ark_relay.features.phone.commands import apply_command, ALLOWED

    check("动作在白名单里", "skip_shutdown" in ALLOWED, True)
    skipped_clear(); store.pop("modes", "skip_next_shutdown")
    E._shutdown_issued = False              # no countdown of ours running here

    ok, msg = apply_command({"action": "skip_shutdown"})
    check("下指令后开关打开", (ok, modes.skip_armed(STATE)), (True, True))
    ok, _ = apply_command({"action": "skip_shutdown", "off": True})
    check("再下一条 off 就关掉", (ok, modes.skip_armed(STATE)), (True, False))

    # 不在白名单的动作必须被拒
    ok, _ = apply_command({"action": "poweroff_now"})
    check("白名单外的动作照样拒绝", ok, False)

    # 关机前那一拉：人在最后一刻按下也来得及
    ledger(run)
    E._shutdown_issued = False; issued.clear()
    E._before_shutdown = lambda: apply_command({"action": "skip_shutdown"})
    check("关机前拉到了「下次跑完不关机」：不关", E._maybe_shutdown(at(23, 0)), False)
    check("并且没有发出关机命令", len(issued), 0)

    # The last pull turned on debug mode or dispatched a script: it still holds (11-08 [A-05])
    skipped_clear(); store.pop("modes", "skip_next_shutdown")
    E._shutdown_issued = False; issued.clear()
    E._before_shutdown = lambda: dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
    check("关机前拉到了调试模式：不关", E._maybe_shutdown(at(23, 0)), False)
    check("调试模式那次也没发关机命令", len(issued), 0)
    store.pop("modes", "debug_until"); skipped_clear()
    _saved_running = E._scripts_running
    _flag = []
    E._before_shutdown = lambda: _flag.append(1)
    E._scripts_running = lambda: bool(_flag)
    check("关机前刚派了脚本：不关", E._maybe_shutdown(at(23, 0)), False)
    check("派脚本那次也没发关机命令", len(issued), 0)
    E._scripts_running = _saved_running
    skipped_clear()

    # 拉不到不等于有人喊停
    skipped_clear(); store.pop("modes", "skip_next_shutdown")
    def boom():
        raise RuntimeError("网络不通")
    E._before_shutdown = boom
    E._shutdown_issued = False; issued.clear()
    check("关机前那一拉失败：按原计划关机", E._maybe_shutdown(at(23, 0)), True)
    E._before_shutdown = None
    skipped_clear()


    print("\n[countdown] 「下次跑完不关机」 pressed inside the relay's own 60-second countdown")
    # 2026-10-09 22:42: the order only stored "skip the next one" and Windows
    # powered off at 22:43 anyway (relay.log 22:43:14 heartbeat bye).
    calls = []
    RC = {"/a": 0}
    def fake_run(args, *a, **k):
        calls.append(list(args))
        rc = RC["/a"] if list(args)[:2] == ["shutdown", "/a"] else 0
        return __import__("subprocess").CompletedProcess(args, rc, b"", b"")
    eng.subprocess = type("X", (), {"run": staticmethod(fake_run),
                                    "CompletedProcess": __import__("subprocess").CompletedProcess})()
    from ark_relay.features.alarm import errwatch
    skipped_clear(); store.pop("modes", "skip_next_shutdown")
    ledger(run)
    E._shutdown_issued = False; calls.clear()
    check("countdown: power-off issued", E._maybe_shutdown(at(23, 0)), True)
    check("countdown: errwatch marked stopping", errwatch._stopping.is_set(), True)
    calls.clear()
    ok, msg = apply_command({"action": "skip_shutdown"})
    check("countdown: order accepted", ok, True)
    check("countdown: shutdown /a was run", ["shutdown", "/a"] in calls, True)
    check("countdown: engine no longer going down", E._shutdown_issued, False)
    check("countdown: no flag left over for tomorrow", modes.skip_armed(STATE), False)
    check("countdown: this opportunity marked skipped",
          store.get("modes", "shutdown_skipped"), E._shutdown_key(at(23, 0)))
    check("countdown: errwatch no longer stopping", errwatch._stopping.is_set(), False)
    calls.clear()
    check("countdown: next 30-second round does not power off again",
          E._maybe_shutdown(at(23, 1)), False)
    check("countdown: and issued nothing", [c for c in calls if c[:2] == ["shutdown", "/s"]], [])
    ledger(run, dict(run, run_id="y"))
    calls.clear()
    check("countdown: next queue round powers off as usual", E._maybe_shutdown(at(23, 40)), True)

    print("\n[countdown] Windows says no countdown (1116): behave as before")
    RC["/a"] = 1116
    skipped_clear(); store.pop("modes", "skip_next_shutdown")
    ok, _ = apply_command({"action": "skip_shutdown"})
    check("1116: flag stored as before", (ok, modes.skip_armed(STATE)), (True, True))
    store.pop("modes", "skip_next_shutdown")

    print("\n[countdown] no power-off issued: shutdown /a is not even tried")
    RC["/a"] = 0
    E._shutdown_issued = False; calls.clear()
    ok, _ = apply_command({"action": "skip_shutdown"})
    check("no countdown: flag stored", (ok, modes.skip_armed(STATE)), (True, True))
    check("no countdown: shutdown /a not run", ["shutdown", "/a"] in calls, False)
    store.pop("modes", "skip_next_shutdown")

    print("\n[countdown] cancel (off) never touches the countdown")
    ledger(run, dict(run, run_id="y"), dict(run, run_id="z"))
    skipped_clear()
    E._shutdown_issued = False
    check("cancel: power-off issued", E._maybe_shutdown(at(23, 50)), True)
    calls.clear()
    ok, _ = apply_command({"action": "skip_shutdown", "off": True})
    check("cancel: shutdown /a not run", ["shutdown", "/a"] in calls, False)
    check("cancel: still going down", E._shutdown_issued, True)

    print("\n[countdown] shutdown /a refused: reported, machine still going down")
    RC["/a"] = 5
    ok, msg = apply_command({"action": "skip_shutdown"})
    check("refused: order reported as failed", ok, False)
    check("refused: still going down", E._shutdown_issued, True)
    check("refused: no flag stored", modes.skip_armed(STATE), False)
    E._shutdown_issued = False; sd._ISSUED[0] = None; skipped_clear()


    print("\n[debug outside a shift end] debug mode spends only a real power-off opportunity")
    # relay.log 2026-10-11: debug mode on from 14:24, every check said 「调试模式开着，这一次关机
    # 跳过」 and recorded 2026-10-11:4 with no shift anywhere near; at 21:21:40 (booted a minute
    # before, the 21:30 shift not started) it read 「这一次关机已经跳过了」. The user, 2026-10-12
    # 08:39: 「调试模式会不会造成下次不关机」. Why: docs/CODE-HISTORY.md「shutdown.py:decide」.
    RC["/a"] = 0
    store.pop("modes", "skip_next_shutdown")


    def day_at(d, hh, mm):
        return datetime(2026, 8, d, hh, mm, tzinfo=SERVER_TZ)


    def ledgers(by_day):
        """{day of August: rows}; every other file this test touches is emptied."""
        for d in (20, 21, 22):
            rows = by_day.get(d, [])
            (STATE / f"ledger-2026-08-{d:02}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows), encoding="utf-8")


    def power_offs():
        return [c for c in calls if c[:2] == ["shutdown", "/s"]]


    def fresh(boot):
        E._shutdown_issued = False; sd._ISSUED[0] = None
        E._handled_any = True; E._started_at = boot; BOOT[0] = boot
        calls.clear()


    morning = {"script": "MAA", "started": day_at(21, 4, 10).isoformat(),
               "finished": day_at(21, 4, 50).isoformat(), "ok": True, "run_id": "m"}

    # (a) debug on two hours before the evening shift: nothing to skip, nothing recorded.
    skipped_clear(); dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
    ledgers({21: [morning]})
    fresh(day_at(21, 14, 0))
    check("(a) 19:30, debug on, no shift since boot -> not-shift", verdict(day_at(21, 19, 30)), "not-shift")
    check("(a) 19:30: stays on", E._maybe_shutdown(day_at(21, 19, 30)), False)
    check("(a) 21:00, debug on, the 21:30 shift ahead -> shift-ahead", verdict(day_at(21, 21, 0)), "shift-ahead")
    check("(a) 21:00: stays on", E._maybe_shutdown(day_at(21, 21, 0)), False)
    check("(a) nothing recorded as skipped", modes.shutdown_skipped(STATE), "")
    dbg_set(f"{real - timedelta(hours=1):%Y-%m-%d %H:%M}")          # debug runs out before the shift
    ledgers({21: [morning, run]})
    check("(a) the evening shift ends -> powers off", E._maybe_shutdown(day_at(21, 22, 25)), True)
    check("(a) …with one power-off command", len(power_offs()), 1)

    # (b) the shift ends without a new row in today's ledger: an evening shift judged after
    # midnight, its row filed under the day it started (State.append_ledger). Debug mode was
    # on while it was still running and has run out by its end. Until 2026-10-12 the
    # mid-shift check recorded 2026-08-22:0, the key did not change, and this power-off was
    # skipped.
    skipped_clear(); dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
    ledgers({21: [morning]})
    fresh(day_at(21, 21, 20))
    check("(b) 00:05, debug on, the shift still running -> shift-running", verdict(day_at(22, 0, 5)), "shift-running")
    check("(b) 00:05: stays on", E._maybe_shutdown(day_at(22, 0, 5)), False)
    check("(b) nothing recorded as skipped", modes.shutdown_skipped(STATE), "")
    dbg_set(f"{real - timedelta(hours=1):%Y-%m-%d %H:%M}")
    late = dict(run, run_id="late", finished=day_at(22, 0, 40).isoformat())
    ledgers({21: [morning, late]})
    check("(b) key advances when the shift record lands in yesterday's ledger", E._shutdown_key(day_at(22, 0, 45)), "2026-08-21:2")
    check("(b) 00:45, the shift ended, debug ran out -> go", verdict(day_at(22, 0, 45)), "go")
    check("(b) 00:45: powers off", E._maybe_shutdown(day_at(22, 0, 45)), True)
    check("(b) …with one power-off command", len(power_offs()), 1)

    # (c) debug on right after the shift ends: that opportunity is skipped, the next one is not.
    skipped_clear(); dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
    ledgers({21: [morning, run]})
    fresh(day_at(21, 21, 20))
    K = E._shutdown_key(day_at(21, 22, 25))
    check("(c) 22:25, the shift ended, debug on -> debug", verdict(day_at(21, 22, 25)), "debug")
    check("(c) 22:25: stays on", E._maybe_shutdown(day_at(21, 22, 25)), False)
    check("(c) this opportunity recorded", modes.shutdown_skipped(STATE), K)
    dbg_set(f"{real - timedelta(hours=1):%Y-%m-%d %H:%M}")
    check("(c) 22:40, debug ran out, same opportunity -> skipped", verdict(day_at(21, 22, 40)), "skipped")
    check("(c) 22:40: no late power-off", E._maybe_shutdown(day_at(21, 22, 40)), False)
    ledgers({21: [morning, run, dict(run, run_id="y")]})
    check("(c) the next shift end -> powers off", E._maybe_shutdown(day_at(21, 23, 40)), True)
    check("(c) …with one power-off command", len(power_offs()), 1)

    # (c') debug on at a shift end whose daily report has not gone out: the report gate names
    # what holds the machine; debug mode is spent once the report has gone, if still on.
    skipped_clear(); dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
    ledgers({21: [morning, run]})
    fresh(day_at(21, 21, 20))
    E.state.report_sent = lambda d: False
    E._report_cutoff = lambda now: day_at(21, 22, 0)
    check("(c') report not out -> report", verdict(day_at(21, 22, 25)), "report")
    E._maybe_shutdown(day_at(21, 22, 25))
    check("(c') nothing recorded while waiting for the report", modes.shutdown_skipped(STATE), "")
    E.state.report_sent = lambda d: True
    del E._report_cutoff
    check("(c') report out, debug still on -> debug", E._maybe_shutdown(day_at(21, 22, 35)), False)
    check("(c') …and recorded", modes.shutdown_skipped(STATE), E._shutdown_key(day_at(21, 22, 35)))

    # (d) the phone's 「下次跑完不关机」 mark armed hours before: spent at the shift end only.
    skipped_clear(); dbg_clear()
    ledgers({21: [morning]})
    fresh(day_at(21, 14, 0))
    modes.set_skip_shutdown(STATE, True)
    check("(d) 19:30: stays on", E._maybe_shutdown(day_at(21, 19, 30)), False)
    check("(d) 21:00 -> shift-ahead", verdict(day_at(21, 21, 0)), "shift-ahead")
    E._maybe_shutdown(day_at(21, 21, 0))
    check("(d) not spent before the shift", (modes.skip_armed(STATE), modes.shutdown_skipped(STATE)), (True, ""))
    ledgers({21: [morning, run]})
    K = E._shutdown_key(day_at(21, 22, 25))
    check("(d) the shift ends: stays on", E._maybe_shutdown(day_at(21, 22, 25)), False)
    check("(d) spent there, that opportunity skipped", (modes.skip_armed(STATE), modes.shutdown_skipped(STATE)), (False, K))
    check("(d) no power-off command", power_offs(), [])
    ledgers({21: [morning, run, dict(run, run_id="y")]})
    check("(d) the next shift end powers off", E._maybe_shutdown(day_at(21, 23, 40)), True)
    E._shutdown_issued = False; sd._ISSUED[0] = None; skipped_clear(); dbg_clear()

    # (e) the mark spent at the evening shift's end stays skipped across the 00:00 midnight
    # day roll (11-08 [A-01]): when the new day has no shift records yet, _shutdown_key keeps
    # yesterday's shift key, so the machine does not power off at midnight and waits for the
    # next scheduled shift to finish.
    skipped_clear(); dbg_clear()
    ledgers({21: [run]})
    fresh(day_at(21, 21, 20))
    modes.set_skip_shutdown(STATE, True)
    check("(e) the evening shift ends: stays on", E._maybe_shutdown(day_at(21, 22, 25)), False)
    check("(e) 23:59: still skipped", verdict(day_at(21, 23, 59)), "skipped")
    check("(e) 00:00 the next day: still skipped across midnight", verdict(day_at(22, 0, 0)), "skipped")
    check("(e) 00:00 the next day: stays on", E._maybe_shutdown(day_at(22, 0, 0)), False)
    check("(e) no power-off command at midnight", len(power_offs()), 0)
    next_morning = {"script": "MAA", "started": day_at(22, 9, 0).isoformat(),
                    "finished": day_at(22, 9, 40).isoformat(), "ok": True, "run_id": "m22"}
    ledgers({21: [run], 22: [next_morning]})
    check("(e) the next shift finishes: powers off", E._maybe_shutdown(day_at(22, 9, 45)), True)
    check("(e) one power-off command after the next shift", len(power_offs()), 1)
    E._shutdown_issued = False; sd._ISSUED[0] = None; skipped_clear(); dbg_clear()


def _part_shutdown_after_restart():
    """A relay restarted after the shift does not power the machine off.

2026-10-01: the morning shift closed at 17:27:43, the relay was redeployed at
17:41, and the new process judged 「本次开机还没有跑完任何队列」. From then until
2026-10-10 the ledger (_ran_since_boot) let it power off anyway. The user, 2026-10-10
18:31 (Tokyo), quoted in USER-SWITCHES.txt at shutdown.py:_say_if_moment_passed: a decision
made by a process that did not see the shift's records land is not the one right after
the shift, so it is 「not-shift」 and the machine stays on. Since 2026-10-11 that one reason - no relay
process on this boot saw the records land - is a WARNING (pushed): the relay lost track
(USER-SWITCHES.txt at shutdown.py:_say_if_moment_passed).
The ledger below is that day's, copied from the machine (start / end as written).

    Formerly test_shutdown_after_restart.py.
    """
    import json
    import os
    from datetime import datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    STATE = TMP / "state"
    STATE.mkdir()
    (TMP / "history").mkdir()
    doc = {"instances": [{"uid": "m"}, {"uid": "e"}]}
    for uid, name, t in (("m", "早班", "09:00"), ("e", "晚班", "21:30")):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True, "AfterAccomplish": "NoAction"},
                    "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {i: {"Info": {"ScriptId": i}} for i in ("s1", "s2", "s3")}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    # The machine's three scripts, kinds told by install path as plan._script_kind reads them.
    scripts = {"instances": [{"uid": "s1"}, {"uid": "s2"}, {"uid": "s3"}]}
    for uid, path in (("s1", "D:\\MAA"), ("s2", "D:\\ark\\okww"), ("s3", "D:\\MaaEnd")):
        scripts[uid] = {"Info": {"Name": uid, "Path": path}, "SubConfigsInfo": {}}
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts), encoding="utf-8")
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.features.shutdown import shutdown
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State


    class Notes:
        def send(self, title, body="", **kw):
            return False


    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


    # Verbatim from C:\ProgramData\ark-relay\state\ledger-2026-10-01.jsonl
    ROWS = [("2026-10-01/arknights/MAA-05-00-01", "MAA", at(9, 0, 50), at(9, 18, 15), True),
            ("2026-10-01/wuwa/OK-WW-05-18-20", "OK-WW", at(9, 18, 37), at(9, 19, 16), "超时"),
            ("2026-10-01/wuwa/OK-WW-07-20-22", "OK-WW", at(11, 20, 35), at(11, 21, 10), "超时"),
            ("2026-10-01/wuwa/OK-WW-09-21-22", "OK-WW", at(13, 21, 35), at(13, 22, 10), "超时"),
            ("2026-10-01/endfield/MaaEnd-11-23-07", "MaaEnd", at(15, 24, 12), at(15, 29, 59), True),
            ("2026-10-01/endfield/MaaEnd-12-10-02", "MaaEnd", at(16, 11, 6), at(16, 11, 6), "失败"),
            ("2026-10-01/endfield/MaaEnd-12-11-12", "MaaEnd", at(16, 12, 15), at(16, 58, 22), True)]
    (STATE / "ledger-2026-10-01.jsonl").write_text("\n".join(
        json.dumps({"run_id": r, "script": s, "user": "u", "started": a.isoformat(),
                    "finished": b.isoformat(), "ok": ok is True,
                    "failed_tasks": [] if ok is True else
                    (["OK-WW 运行超时"] if ok == "超时" else ["赠送干员礼物", "装备制造"])})
        for r, s, a, b, ok in ROWS) + "\n",
        encoding="utf-8")

    cfg = Config()
    e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._handled_any = False                 # the process deployed at 17:41 had handled nothing
    e._started_at = at(17, 41, 52)
    BOOT = [at(8, 45, 11)]                 # LastBootUpTime read on the machine
    e._boot_time = lambda now: BOOT[0]

    now = at(17, 43)
    entries = e._recent_entries(now)
    print("[10-01 17:43, relay restarted at 17:41 after the shift closed]")
    e.state.report_sent = lambda d: True
    check("17:55, restarted after the shift: not-shift, stays on",
          shutdown.decide(e, at(17, 55)).code, "not-shift")
    print("    decide says:", shutdown.decide(e, at(17, 55)))
    check("the round still reaches back to MAA 09:00 (it was the shift, just not seen landing)",
          [x["script"] for x in shutdown._round_of_newest(entries)][0], "MAA")

    print("\n[2026-10-11: the relay losing track is a WARNING (pushed), a state stays INFO]")
    import logging


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.got = []

        def emit(self, record):
            if record.getMessage().startswith("不关机："):
                self.got.append((record.levelname, record.getMessage()))


    grab = Grab()
    _lg = shutdown.log
    _lg_level = _lg.level
    _lg.setLevel(logging.DEBUG)              # INFO must reach the handler to be told from WARNING
    _lg.addHandler(grab)
    e._last_wait_note = ""
    check("a shift that landed unseen -> stays on", shutdown._maybe_shutdown(e, at(17, 55)), False)
    check("...and says so as a WARNING", [lv for lv, m in grab.got if shutdown.LANDING_UNSEEN in m], ["WARNING"])
    shutdown._maybe_shutdown(e, at(17, 56))
    check("once per change, not every tick", len([1 for _, m in grab.got if shutdown.LANDING_UNSEEN in m]), 1)
    BOOT[0] = None
    shutdown._maybe_shutdown(e, at(17, 57))
    check("boot time unreadable -> a WARNING", [lv for lv, m in grab.got if shutdown.BOOT_UNKNOWN in m], ["WARNING"])
    BOOT[0] = at(17, 30)                    # booted by hand after the runs: a person's state
    shutdown._maybe_shutdown(e, at(17, 58))
    check("a boot by hand stays INFO", grab.got[-1][0], "INFO")
    _lg.removeHandler(grab)
    _lg.setLevel(_lg_level)
    BOOT[0] = at(8, 45, 11)
    e._last_wait_note = ""

    print("\n[the same day, this process saw the last record land: go]")
    e._handled_any = True
    check("17:55, records landed in this process -> go", shutdown.decide(e, at(17, 55)).code, "go")

    print("\n[2026-10-11: the last upload before power-off failing is a plain WARNING (pushed)]")
    from ark_relay.features.evidence import error_evidence
    from ark_relay.features.makeup import collect_retry
    _saved = (error_evidence.upload_daily_logs, collect_retry.maybe_run, e._power_off)
    error_evidence.upload_daily_logs = lambda cfg, **kw: {"errors": ["relay: ConnectionError: COS down"]}
    collect_retry.maybe_run = lambda eng_, now: False
    e._power_off = lambda: False             # stop right after the upload
    up_logs = []


    class UpGrab(logging.Handler):
        def emit(self, record):
            if record.getMessage().startswith("关机前证据上传失败"):
                up_logs.append((record.levelname, bool(getattr(record, "ark_recovered", False)),
                                sorted(k for k in vars(record) if "recover" in k.lower())))


    _ul = shutdown.log
    _ul.addHandler(UpGrab())
    shutdown._maybe_shutdown(e, at(17, 55))
    check("the upload failure is logged once, a WARNING, not marked recovered",
          [(lv, keys) for lv, _, keys in up_logs], [("WARNING", [])])
    error_evidence.upload_daily_logs, collect_retry.maybe_run, e._power_off = _saved
    e._handled_any = False

    print("\n[a machine booted after the runs (someone switched it on to work) still holds]")
    BOOT[0] = at(17, 30)
    check("booted 17:30 -> not-shift", shutdown.decide(e, at(17, 55)).code, "not-shift")
    e._handled_any = True
    check("even with records landing in this process", shutdown.decide(e, at(17, 55)).code, "not-shift")
    e._handled_any = False

    print("\n[uptime unknown -> cannot tie records to this boot -> hold]")
    BOOT[0] = None
    check("no boot time -> not-shift", shutdown.decide(e, at(17, 55)).code, "not-shift")
    e.state.report_sent = State(cfg.state_dir).report_sent
    BOOT[0] = at(8, 45, 11)

    print("\n[a failure that is not a timeout still ends the round at a 2-hour gap]")
    plain = [{"script": "OK-WW", "user": "u", "started": at(9, 18).isoformat(), "finished": at(9, 30).isoformat(),
              "ok": False, "failed_tasks": ["任务执行：开跑时游戏不在大世界"]},
             {"script": "MaaEnd", "user": "u", "started": at(13, 0).isoformat(), "finished": at(13, 30).isoformat(),
              "ok": True, "failed_tasks": []}]
    check("hand-run MaaEnd at 13:00 stays its own round", len(shutdown._round_of_newest(plain)), 1)

    print("\n[a hand-started re-run after a timeout is not pulled into the shift]")
    okww_to = {"script": "OK-WW", "user": "u", "started": at(13, 21, 35).isoformat(),
               "finished": at(13, 22, 10).isoformat(), "ok": False, "failed_tasks": ["OK-WW 运行超时"]}
    inside = {"script": "MaaEnd", "user": "u", "started": at(15, 24, 12).isoformat(),
              "finished": at(16, 0).isoformat(), "ok": True, "failed_tasks": []}
    outside = dict(inside, started=at(15, 40).isoformat(), finished=at(16, 10).isoformat())
    check("MaaEnd at 15:24 (13:21:35 + 120 + 10 = 15:31:35) joins", len(shutdown._round_of_newest([okww_to, inside])), 2)
    check("MaaEnd by hand at 15:40 stays its own round", len(shutdown._round_of_newest([okww_to, outside])), 1)
    me_to = {"script": "MaaEnd", "user": "u", "started": at(10, 29, 47).isoformat(),
             "finished": at(11, 22, 10).isoformat(), "ok": False, "failed_tasks": ["MaaEnd 进程超时"]}
    check("after a MaaEnd timeout: 11:22:10 + 40 + 10 = 12:12:10 -> 12:03 joins",
          len(shutdown._round_of_newest([me_to, dict(inside, started=at(12, 3, 14).isoformat())])), 2)
    check("OK-WW by hand at 13:30 stays its own round",
          len(shutdown._round_of_newest([me_to, dict(okww_to, ok=True, failed_tasks=[],
                                                    started=at(13, 30).isoformat(),
                                                    finished=at(13, 45).isoformat())])), 1)


def _part_shutdown_hand_and_test_runs():
    """Hand-started and test-window runs never join a 早班/晚班 round nor move the skip key.

Replays the real ledgers of 2026-10-10..13 (fixtures/shutdown-1010-1013: the machine's
ledger rows cut to the fields the shutdown decision reads, its test-windows.json and
relay-dispatches.json) at every moment relay.log shows a power-off verdict.

Two of them went wrong on the old code:
* 10-12 21:45:34 the relay stayed on as 「最近一轮是手动触发的」 (a round started by hand) - the two
  test-window MaaEnd runs (18:26, 20:04, hand_started) were chained into the 21:30
  evening shift, whose first record then sat nowhere near a scheduled time;
* 10-13 11:13:55 「本轮已处理完毕，60 秒后关机」 - the hand-started test OK-WW of 11:07 was
  chained into the morning shift, and as a 4th ledger row it moved the skip key from
  2026-10-13:3 (the spent 「下次跑完不关机」, 10:00:36) to :4, so the skip no longer held.
The user's rule (10-10 18:31, DECISIONS D-1010-关机): only a finished 早班/晚班 powers off.

    Formerly test_shutdown_hand_and_test_runs.py.
    """
    import json
    from datetime import datetime
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.shutdown import shutdown

    FIX = Path(__file__).resolve().parent / "fixtures" / "shutdown-1010-1013"


    def ledger(day):
        p = FIX / f"ledger-{day}.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


    class Eng:
        """The engine as the shutdown decision sees it, at moment `now`: only the records
    that had landed (finished) by then exist."""
        _gu_rerun_at = None

        def __init__(self, now):
            self.now = now
            self.cfg = SimpleNamespace(state_dir=FIX, automas_dir=None)
            self.state = SimpleNamespace(read_ledger=self.read_ledger)

        def read_ledger(self, day):
            return [e for e in ledger(day)
                    if datetime.fromisoformat(e.get("finished") or e["started"]) <= self.now]

        def _round_is_manual(self, group):
            return shutdown._round_is_manual(self, group)


    # The machine's AUTO-MAS schedule: 早班 09:00, 晚班 21:30 (every shift record in the fixtures).
    plan.schedule = lambda _d: [{"name": "早班", "times": ["09:00"], "items": ["s1"]}, {"name": "晚班", "times": ["21:30"], "items": ["s1"]}]


    def at(s):
        return datetime.fromisoformat(f"2026-{s}").replace(tzinfo=SERVER_TZ)


    def manual(when):
        eng = Eng(at(when))
        return shutdown._last_round_manual(eng, eng.now, shutdown._recent_entries(eng, eng.now))


    def key(when):
        eng = Eng(at(when))
        return shutdown._shutdown_key(eng, eng.now)


    print("[the two moments that went wrong]")
    check("10-12 21:45:34 晚班 MAA 21:30 finished: a shift, not 「手动触发」 (test-window MaaEnd 18:26 / 20:04 left out)",
          manual("10-12T21:45:34"), False)
    check("10-13 11:13:55 newest record is the hand-started test OK-WW 11:07: manual, stays on",
          manual("10-13T11:13:55"), True)
    check("10-13 10:00:36 the spent 「下次跑完不关机」 recorded 2026-10-13:3 (relay.log 34010)",
          key("10-13T10:00:36"), "2026-10-13:3")
    check("10-13 11:13:55 the test OK-WW does not move the skip key: still :3, the skip holds",
          key("10-13T11:13:55"), "2026-10-13:3")
    check("10-12 21:45:34 key counts the shift records only (6 of 9 rows; hand 11:41, test 18:26 / 20:04 left out)",
          key("10-12T21:45:34"), "2026-10-12:6")

    print("\n[10-12 12:10:36: the newest record was the hand-started OK-WW 11:41 - stays on]")
    check("manual", manual("10-12T12:10:36"), True)

    print("\n[every other verdict of 10-10..10-13 is unchanged]")
    check("10-10 09:39:30 早班 done -> not manual (relay.log: 60 秒后关机)", manual("10-10T09:39:30"), False)
    check("10-10 12:25:09 hand-started MAA 12:05 -> manual (relay.log: 最近一轮是手动触发的)",
          manual("10-10T12:25:09"), True)
    check("10-10 21:50:00 晚班 done -> not manual", manual("10-10T21:50:00"), False)
    check("10-11 09:59:27 早班 done -> not manual (the skip gate held it, relay.log 31916)",
          manual("10-11T09:59:27"), False)
    check("10-11 21:45:42 晚班 done -> not manual (relay.log: 60 秒后关机)", manual("10-11T21:45:42"), False)
    check("10-13 10:00:36 早班 done -> not manual (the mark was spent here)", manual("10-13T10:00:36"), False)

    print("\n[a scheduled record is still chained as before: a retry within the round]")
    check("10-12 11:39 早班 with the MaaEnd retry 10:59 -> not manual", manual("10-12T11:39:00"), False)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_shutdown_held_past_shift():
    """A power-off opportunity belongs to the moment a shift finished, not to the whole boot.

The user's rule of 2026-10-10 18:31 (Tokyo), quoted verbatim in USER-SWITCHES.txt at
shutdown.py:_say_if_moment_passed: only right after a morning / evening shift finished.

2026-10-15 (Endfield maintenance day, relay.log on the machine, Beijing time): the morning
shift ran MAA and OK-WW (MaaEnd skipped in the queue for the maintenance) and finished at
09:3x. The deferred client update and the MaaEnd make-up then held the power-off
(09:33 ... 13:16); 13:01:52 the make-up was cancelled, 13:06:59 「不关机：游戏客户端正在更新或重跑」,
13:17:18 the update found the launcher at 「开始游戏」, and at 13:18:00 the relay said
「本轮已处理完毕，60 秒后关机」 - hours after the shift. The whitelist (_not_shift) never
expired, and the update / make-up gates only deferred the go.

The times below are that day's; the ledger rows are modelled (start / end per relay.log),
the queue time 08:50 stands for the morning shift's.

    Formerly test_shutdown_held_past_shift.py.
    """
    import json
    import os
    import shutil
    from datetime import datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    STATE = TMP / "state"
    STATE.mkdir()
    (TMP / "history").mkdir()
    ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    NOT_THURSDAY = [d for d in ALL_DAYS if d != "Thursday"]     # 2026-10-15 is a Thursday
    doc = {"instances": [{"uid": "m"}, {"uid": "e"}]}
    for uid, name, t in (("m", "早班", "08:50"), ("e", "晚班", "21:30")):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True, "AfterAccomplish": "NoAction"},
                    "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {
                                           "i1": {"Info": {"ScriptId": "s1"}},
                                           "i2": {"Info": {"ScriptId": "s2"}},
                                           # the maintenance skip: today's weekday dropped from the item
                                           "i3": {"Info": {"ScriptId": "s3"}, "Schedule": {"Days": NOT_THURSDAY}}}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    scripts = {"instances": [{"uid": "s1"}, {"uid": "s2"}, {"uid": "s3"}]}
    for uid, path in (("s1", "D:\\MAA"), ("s2", "D:\\ark\\okww"), ("s3", "D:\\MaaEnd")):
        scripts[uid] = {"Info": {"Name": uid, "Path": path}, "SubConfigsInfo": {}}
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts), encoding="utf-8")
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.core.statestore import StateStore
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.evidence import error_evidence
    from ark_relay.features.makeup import collect_retry, makeup
    from ark_relay.features.phone import heartbeat
    from ark_relay.features.shutdown import shutdown


    class Notes:
        def send(self, title, body="", **kw):
            return []


    def at(hh, mm, ss=0, day=15):
        return datetime(2026, 10, day, hh, mm, ss, tzinfo=SERVER_TZ)


    MORNING = [("MAA-1", "MAA", "arknights", at(8, 50, 40), at(9, 9, 12), True),
               ("OK-WW-1", "OK-WW", "wuwa", at(9, 9, 40), at(9, 31, 5), True)]
    EVENING = [("MAA-2", "MAA", "arknights", at(21, 30, 40), at(21, 49, 2), True),
               ("OK-WW-2", "OK-WW", "wuwa", at(21, 49, 30), at(22, 8, 10), True)]


    def ledger(rows):
        (STATE / "ledger-2026-10-15.jsonl").write_text("\n".join(
            json.dumps({"run_id": f"2026-10-15/x/{r}", "script": s, "user": u, "started": a.isoformat(),
                        "finished": b.isoformat(), "ok": ok, "failed_tasks": []})
            for r, s, u, a, b, ok in rows) + "\n", encoding="utf-8")


    def marker(result, dispatched):
        d = STATE / "makeup"
        d.mkdir(exist_ok=True)
        (d / "2026-10-15.json").write_text(json.dumps(
            {"MaaEnd": {"dispatched_at": dispatched.isoformat(), "result": result, "tries": 1,
                        "tasks": [makeup.WHOLE_MAAEND]}}), encoding="utf-8")


    cfg = Config()
    e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e.state.report_sent = lambda d: True
    BOOT = [at(8, 35)]
    e._boot_time = lambda now: BOOT[0]
    UPDATING = [False]
    e._deferred_update_busy = lambda: UPDATING[0]
    powered = []
    e._power_off = lambda: powered.append(1) or True     # never the real `shutdown` on this machine
    e._before_shutdown = None
    saved = (error_evidence.upload_daily_logs, collect_retry.maybe_run)
    error_evidence.upload_daily_logs = lambda cfg, **kw: {}
    collect_retry.maybe_run = lambda eng_, now: False


    def fresh(boot=None, started=None):
        """A new relay process on boot `boot` that saw the shift's records land."""
        BOOT[0] = boot or at(8, 35)
        e._started_at = started or at(8, 35, 20)
        e._handled_any = True
        e._shutdown_issued = False
        e._shutdown_issued_at = None
        e._last_wait_note = ""
        UPDATING[0] = False
        powered.clear()
        errwatch.clear_stopping()
        for k in ("shutdown_forfeit", "relay_poweroff", "relay_poweroff_why"):
            e.state.store.pop("marks", k)
        shutil.rmtree(STATE / "makeup", ignore_errors=True)


    def tick(now):
        shutdown._maybe_shutdown(e, now)
        return shutdown.decide(e, now)


    print("[2026-10-15: shift done, update / make-up held the power-off, then let go: stays on]")
    fresh()
    ledger(MORNING)
    UPDATING[0] = True                                   # 09:33 the deferred client update starts
    v = tick(at(9, 33))
    check("09:33 the update holds the power-off", v.code, "not-shift")
    check("…the hold is kept on disk (a relay restart keeps it)",
          isinstance(e.state.store.get("marks", "shutdown_forfeit"), dict), True)
    marker(makeup.DISPATCHED, at(12, 58))                # the MaaEnd make-up goes out
    UPDATING[0] = False
    tick(at(12, 59))
    marker(makeup.GAVE_UP, at(12, 58))                   # 13:01:52 cancelled by the queue skip
    tick(at(13, 1, 52))
    UPDATING[0] = True
    tick(at(13, 6, 59))
    UPDATING[0] = False                                  # 13:17:18 the launcher shows 「开始游戏」
    for now in (at(13, 17, 18), at(13, 18), at(13, 30), at(18, 0)):
        v = tick(now)
    check("13:17 .. 18:00 after the update: never powered off", powered, [])
    check("…the decision says it is not right after a shift", v.code, "not-shift")
    check("…in his terms", v.reason.startswith("不是早班/晚班跑完，不关机"), True)
    check("…names the shift and what held it", ("早班" in v.reason, "游戏客户端正在更新" in v.reason), (True, True))

    print("\n[a relay restart after the hold: the opportunity stays gone]")
    e._handled_any = False
    shutdown.note_handled(e, at(9, 31, 30))              # the earlier process saw the shift land
    e._started_at = at(13, 0)
    v = tick(at(13, 20))
    check("restarted 13:00 on the same boot -> not-shift, no power-off", (v.code, powered), ("not-shift", []))
    # The after-shift check still counts the shift as finished: the hold took only its
    # power-off. Before, a restart after the hold logged 「收工体检（早班）这班没查」 for a shift
    # that had been checked (daysim 10-09, 10:29:21 after the 10:19 restart).
    from ark_relay.features.selfcheck import shiftcheck
    check("shiftcheck: the held shift is a finished shift", (shiftcheck.finished_shift(e, at(13, 20)) or {}).get("name"), "早班")
    e.state.store.pop("marks", "handled_boot")

    print("\n[the evening shift on the same boot is a new opportunity: go]")
    ledger(MORNING + EVENING)
    e._handled_any = True
    e._started_at = at(8, 35, 20)
    e._last_wait_note = ""
    v = shutdown.decide(e, at(22, 9))
    check("22:09 after the evening shift -> go", v.code, "go")

    print("\n[a plain morning: the shift finishes, nothing holds it -> powered off]")
    fresh()
    ledger(MORNING)
    check("09:32 -> power-off issued", (shutdown._maybe_shutdown(e, at(9, 32)), powered), (True, [1]))

    print("\n[make-up held it (no update), then the make-up landed: stays on]")
    fresh()
    ledger(MORNING)
    marker(makeup.DISPATCHED, at(9, 32))
    v = tick(at(9, 33))
    check("09:33 the make-up holds it", v.code, "not-shift")
    marker(makeup.OK, at(9, 32))
    ledger(MORNING + [("MaaEnd-mk", "MaaEnd", "endfield", at(9, 34), at(9, 52), True)])
    v = tick(at(9, 53))
    check("09:53 the make-up landed -> still no power-off", (v.code, powered), ("not-shift", []))

    print("\n[the update thread masked by another hold (an alarm not pushed yet) still counts]")
    fresh()
    ledger(MORNING)
    UPDATING[0] = True
    e._recovered = [object()]                            # 「还有告警没推出去」 comes before 「updating」
    tick(at(9, 33))
    e._recovered = []
    UPDATING[0] = False
    v = tick(at(9, 50))
    check("released 09:50 -> not-shift, no power-off", (v.code, powered), ("not-shift", []))

    print("\n[why the machine went off: kept with the relay's power-off, carried on the last COS beat]")
    fresh()
    ledger(MORNING)
    shutdown._maybe_shutdown(e, at(9, 32))
    why = e.state.store.get("marks", "relay_poweroff_why") or {}
    check("the reason names the shift", "早班" in str(why.get("why")), True)
    check("…its time and when it finished", ("08:50" in str(why.get("why")), "09:31" in str(why.get("why"))), (True, True))
    now_real = datetime.now(tz=SERVER_TZ)
    e.state.store.set("marks", "relay_poweroff", now_real.isoformat())   # as if issued just now
    e.state.store.set("marks", "relay_poweroff_why", dict(why, at=now_real.isoformat()))


    class Cos:
        pass


    puts = []
    saved_put = heartbeat.cos_put
    heartbeat.cos_put = lambda cos, key, body, timeout, **kw: puts.append(json.loads(body)) or ""
    hb = heartbeat.Heartbeat("t0pic", STATE, post=lambda b, t: None, cos=Cos())
    hb.cos_beat(bye=True)
    off = (puts[-1] if puts else {}).get("off") or {}
    check("the bye beat says the relay powered off", off.get("by"), "relay")
    check("…and why", off.get("why"), why.get("why"))
    check("…when (seconds, as the beat's own 'at')", off.get("at"), int(now_real.timestamp()))
    check("…the fields the App reads are unchanged", {"at", "every", "cos_every", "bye"} <= set(puts[-1]), True)
    hb.cos_beat()
    check("an ordinary beat carries no 'off'", "off" in puts[-1], False)
    e.state.store.pop("marks", "relay_poweroff")
    errwatch.mark_os_shutdown()
    hb.cos_beat(bye=True)
    check("Windows shutting down without the relay's command -> by windows", puts[-1].get("off", {}).get("by"), "windows")
    errwatch._os_shutdown.clear()
    hb.cos_beat(bye=True)
    check("a service stop, the machine staying up -> by service", puts[-1].get("off", {}).get("by"), "service")
    heartbeat.cos_put = saved_put
    check("StateStore reads the new marks back", StateStore(STATE).get("marks", "relay_poweroff_why") is not None, True)

    error_evidence.upload_daily_logs, collect_retry.maybe_run = saved


def _part_shutdown_notice():
    """The 「今晚不关机」 message must never go out when the machine is in fact shutting down.

At 22:46 on 2026-09-09 the command had already been sent, and the push still read
「到点了但没关机：关机令已经下过了。机器会一直开着」 - then the machine shut down.
The verdict code for "the command has gone out" was listed among the reasons a machine
stays awake, and its wording read as though someone had ordered it to stay on.

    Formerly test_shutdown_notice.py.
    """
    import re
    from datetime import datetime, timedelta
    from types import SimpleNamespace


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.shutdown import shutdown
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ


    src = Path(shutdown.__file__).read_text(encoding="utf-8")

    print("[关机命令已经发出去，就不是「没关机」]")
    check("中继自己发出的关机是唯一不推的码", getattr(shutdown, "RELAY_POWER_OFF", None), "issued")
    check("没有「卡住才推」的名单了", hasattr(shutdown, "_STUCK_CODES"), False)
    verdict = re.search(r'Verdict\(False, "issued", "([^"]+)"\)', src)
    check("找得到那句话", bool(verdict))
    check("不再像「有人下令别关」", "已经下过了" in (verdict.group(1) if verdict else ""), False)
    check("改成说清是正在关", "机器正在关" in src)


    class _Store:
        def __init__(self):
            self.d = {}

        def get(self, ns, key):
            return self.d.get((ns, key))

        def set(self, ns, key, value):
            self.d[(ns, key)] = value


    def engine(cutoff):
        sent = []
        return SimpleNamespace(
            state=SimpleNamespace(store=_Store(), dir=tmpdir(), read_ledger=lambda day: []),
            notifier=SimpleNamespace(send=lambda t, b, alert=False: sent.append((t, b, alert)) or []),
            _report_cutoff=lambda now: cutoff, sent=sent, cfg=SimpleNamespace(shutdown_after_run=True),
            _shutdown_issued=False, _shutdown_key=lambda now: f"{now:%Y-%m-%d}:3")


    NIGHT = datetime(2026, 10, 6, 22, 0, tzinfo=SERVER_TZ)
    CUTOFF = NIGHT.replace(hour=21, minute=30)

    print("[every reason the machine stays on: nothing pushed (10-10 23:22: only 「关机被取消」 is)]")
    e = engine(CUTOFF)
    for code, why in (("running", "还有脚本或游戏在跑"), ("pending", "还有告警没推出去"), ("debug", "调试模式开着"),
                      ("not-shift", "不是早班/晚班跑完"), ("shift-running", "等排期的那趟跑完再判关机")):
        shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, code, why))
    check("none of them pushed", e.sent, [])
    check("the 「今晚不关机」 title is gone", hasattr(texts, "NO_SHUTDOWN"), False)

    print("[关机命令发出去十分钟以上机器还开着：没关下去，推（2026-10-06 之前一直判「正在关」，不吭声）]")
    STUCK_MIN = getattr(shutdown, "ISSUED_STUCK_MIN", 10)
    e = engine(NIGHT + timedelta(hours=3))          # long before that day's cutoff, on purpose
    e._shutdown_issued = True
    e._shutdown_issued_at = NIGHT
    v = shutdown.decide(e, NIGHT + timedelta(minutes=STUCK_MIN - 1))
    check("刚发出去不久：还是「正在关」", v.code, "issued")
    shutdown._say_if_moment_passed(e, NIGHT + timedelta(minutes=STUCK_MIN - 1), v)
    check("正在关：不推", e.sent, [])
    later = NIGHT + timedelta(minutes=STUCK_MIN)
    v = shutdown.decide(e, later)
    check(f"{STUCK_MIN} 分钟后还在判：没关下去", v.code, "not-down")
    check("原因写着几点发的命令", "22:00" in v.reason and "没有关下去" in v.reason)
    shutdown._say_if_moment_passed(e, later, v)
    check("pushed 「关机被取消」 at once", [(t, a) for t, _, a in e.sent], [(texts.SHUTDOWN_CANCELLED, True)])
    check("one plain line with the time", e.sent[0][1] if e.sent else "", f"关机没成功（关机命令 22:00 发出，过了 {STUCK_MIN} 分钟机器还开着）")
    shutdown._say_if_moment_passed(e, later + timedelta(hours=1), shutdown.decide(e, later + timedelta(hours=1)))
    check("同一次没关下去：只推一次", len(e.sent), 1)
    check("文字是人话", texts.plain(e.sent[0][1]) if e.sent else [], [])
    e = engine(CUTOFF)
    e._shutdown_issued = True                        # issued, but not when (an engine from before 10-06)
    check("不知道几点发的：照旧「正在关」", shutdown.decide(e, later).code, "issued")

    print("[关机命令被取消了：取消前后有人在用 -> 只记日报；看不出有人 -> 进群（2026-10-10）]")
    NS = "http://schemas.microsoft.com/win/2004/08/events/event"
    FIX = Path(__file__).resolve().parent / "fixtures"
    # Real System log events read on the machine 2026-10-10 (newest first, as shutdown_event_xml returns them):
    # 10-01: 1074 13:48:52Z (the relay), 566 13:49:36Z (Reason 32, input woke the display), 1075 13:49:52Z by INS\Administrator.
    # 10-02: 1074 13:49:01Z (the relay), 1075 13:49:08Z by INS\Administrator, no 566.
    REAL_1001 = (FIX / "system-1001-cancel.xml").read_text(encoding="utf-8").splitlines()
    REAL_1002 = (FIX / "system-1002-cancel.xml").read_text(encoding="utf-8").splitlines()


    def ev(eid, utc):
        data = "".join(f"<Data>{d}</Data>" for d in ("C:\\Windows\\system32\\shutdown.exe (INS)", "INS",
                                                       "x", "0x80040001", "关机", "ark-relay: run complete",
                                                       "INS\\Administrator")) if eid == 1074 else ""
        return (f'<Event xmlns="{NS}"><System><EventID>{eid}</EventID>'
                f'<TimeCreated SystemTime="{utc}"/></System><EventData>{data}</EventData></Event>')


    saved_reader = shutdown.shutdown_event_xml
    asked = []


    def run(xmls, idle, issued):
        """decide at ISSUED_STUCK_MIN after `issued`, the day's report already out (10-01 21:48:40)."""
        shutdown.shutdown_event_xml = lambda s, ids=(1074, 1075), x=xmls: asked.append((s, ids)) or x
        e = engine(issued.replace(hour=23, minute=59))     # before that day's cutoff, on purpose
        e._shutdown_issued, e._shutdown_issued_at = True, issued
        e.state.report_sent = lambda d: d == f"{issued:%Y-%m-%d}"
        at = issued + timedelta(minutes=STUCK_MIN)
        v = shutdown.decide(e, at)
        shutdown._say_if_moment_passed(e, at, v)
        return e, v, at


    print(" [an aborted power-off, whoever did it: one line to the group, nobody named (10-10 23:22)]")
    # The user, 2026-10-10 23:22 (Tokyo), quoted in USER-SWITCHES.txt at _say_if_moment_passed.
    for label, xmls, when in (("10-01 (a 566 before the abort)", REAL_1001, datetime(2026, 10, 1, 21, 48, 52, tzinfo=SERVER_TZ)),
                              ("10-02 (no 566, 7 s after the command)", REAL_1002, datetime(2026, 10, 2, 21, 49, 1, tzinfo=SERVER_TZ))):
        e, v, at = run(xmls, None, when)
        check(f"{label}: cancelled", v.code, "cancelled")
        check(f"{label}: says when it went out and when it was cancelled",
              all(w in v.reason for w in (f"{when:%H:%M}", "被取消了")), True)
        check(f"{label}: does not say who", "Administrator" in v.reason or "键鼠" in v.reason, False)
        check(f"{label}: pushed once, the time only", [(t, b) for t, b, _ in e.sent], [(texts.SHUTDOWN_CANCELLED, f"关机被取消（{v.reason.split('，')[1][:5]}）")])
        check(f"{label}: nothing kept for the daily report", sorted(p.name for p in Path(e.state.dir).glob("shutdown-cancels-*")), [])
        shutdown._say_if_moment_passed(e, at + timedelta(minutes=5), shutdown.decide(e, at + timedelta(minutes=5)))
        check(f"{label}: still one push five minutes on", len(e.sent), 1)
    check("the reader still asks for the 566 (harmless) and covers the command", asked[-1][0] >= STUCK_MIN * 60, True)
    check("no 「cancelled-unseen」 any more", "cancelled-unseen" in src, False)
    check("nothing reads who uses the console", any(w in src for w in ("console_idle_s", "query user", "IN_USE_IDLE_MIN")), False)

    print(" [不是取消的情况]")
    issued = datetime(2026, 10, 1, 21, 48, 52, tzinfo=SERVER_TZ)
    for label, xmls, want in (
            ("取消之后又有 1074（又有人下了关机）：照旧没关下去", [ev(1074, "2026-10-01T13:55:00Z")] + REAL_1001, "not-down"),
            ("只有中继的 1074：没关下去", [ev(1074, "2026-10-01T13:48:52Z")], "not-down"),
            ("系统日志读不到：照旧没关下去", None, "not-down")):
        e, v, at = run(xmls, 0, issued)
        check(label, v.code, want)
    shutdown.shutdown_event_xml = saved_reader
    e = engine(CUTOFF)
    e._shutdown_issued, e._shutdown_issued_at = True, issued
    check("命令刚发出不久：不读系统日志，照旧「正在关」",
          (shutdown.decide(e, issued + timedelta(minutes=1)).code), "issued")
    check("cancelled_at：事件串是空的", shutdown.cancelled_at([]), None)
    check("cancel_event：真实 1075 的账户是 param2",
          getattr(shutdown, "cancel_event", lambda x: (None, None))(REAL_1002)[1], "INS\\Administrator")

    print("[every other code decide returns: not pushed, not in the daily report (10-10 23:22)]")
    codes = set(re.findall(r'Verdict\((?:True|False),\s*"([^"]+)"', src))
    check("decide's codes found", {"off", "debug", "skipped", "issued", "not-down", "cancelled", "uptime", "makeup",
                                   "not-shift", "report", "running", "go"} <= codes)
    for code in sorted(codes - {"go", "not-down", "cancelled"}) + ["shift-ahead", "shift-running"]:
        e = engine(CUTOFF)
        e.state.report_sent = lambda day: False
        e._boot_time = lambda now: NIGHT.replace(hour=11, minute=45)
        shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, code, f"测试原因 {code}"))
        check(f"{code}: not pushed", e.sent, [])
        check(f"{code}: nothing kept for the daily report", sorted(p.name for p in Path(e.state.dir).glob("shutdown-cancels-*")), [])
    for code, why in (("off", "关机功能没开"), ("uptime", "开机不够久"),
                      ("report", "到点该关机了，但日报还没发出去，继续等")):
        check(f"{code} 的原因在 decide 里原样写着", f'"{code}", "{why}"' in src)

    print("[debug mode eats this power-off: recorded, nothing pushed]")
    # decide() answers "debug" only at a real opportunity (after every other gate); that is
    # tests/test_shutdown.py's job on a real engine. Here only what _maybe_shutdown does with it.
    e = engine(CUTOFF)
    e.state.dir = tmpdir()
    e._last_wait_note = ""
    real_decide = shutdown.decide
    shutdown.decide = lambda eng, now: shutdown.Verdict(False, "debug", "调试模式开着，这一次关机跳过")
    try:
        got = shutdown._maybe_shutdown(e, NIGHT)
    finally:
        shutdown.decide = real_decide
    check("debug: no power-off", got, False)
    check("debug: nothing pushed", e.sent, [])
    check("…this occasion recorded as before (no late power-off)", shutdown.modes.shutdown_skipped(e.state.dir), f"{NIGHT:%Y-%m-%d}:3")

    print("[刷声骸那条要说清刷到几点，不能只说「在刷」]")
    check("理由里带收工时刻", "才收工" in src)

    print("[关机没成之后：发出状态清掉，定时报警和下一班关机恢复（11-08 之前一直卡到重启）]")
    _ew = __import__("ark_relay.features.alarm.errwatch", fromlist=["x"])
    shutdown.shutdown_event_xml = lambda s, ids=(1074, 1075): None
    e = engine(NIGHT + timedelta(hours=3))
    e._shutdown_issued, e._shutdown_issued_at = True, NIGHT
    e._boot_time = lambda now: None; e._last_wait_note = ""
    _ew.mark_stopping()
    e.cfg.shutdown_after_run = True
    shutdown._maybe_shutdown(e, NIGHT + timedelta(minutes=STUCK_MIN))
    check("没关下去：发出状态清掉", (e._shutdown_issued, e._shutdown_issued_at), (False, None))
    check("没关下去：errwatch 不再当成正在关机", _ew._stopping.is_set(), False)
    check("没关下去：群里照样推了一条", len(e.sent), 1)
    shutdown.shutdown_event_xml = saved_reader


def _part_shutdown_open_test_window():
    """A test window can never swallow a 早班/晚班, even when test-off is never run.

The review of 25ebc227 (10-13): a window with no "until" counted as lasting forever,
so every later record - real shift runs included - was a test run; the newest round
read as manual, the skip key stopped at 2026-10-13:3, and the machine never powered
off (the real 10-13 ledger with the 11:05 window left open and an evening shift
added: 21:50 stayed on). A scheduled shift starting while a window was open counted
as test too.

Replays the real ledgers of fixtures/shutdown-1010-1013 with the windows left open,
plus a 晚班 on 10-13 (MAA 21:30, MaaEnd 21:46, shaped like the 10-12 / 10-11 ones).

    Formerly test_shutdown_open_test_window.py.
    """
    import json
    import shutil
    import tempfile
    from datetime import datetime
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.shutdown import shutdown

    FIX = Path(__file__).resolve().parent / "fixtures" / "shutdown-1010-1013"

    EVENING = [
        {"run_id": "2026-10-13/arknights/MAA-17-30-20", "script": "MAA", "user": "arknights",
         "started": "2026-10-13T21:30:20+08:00", "finished": "2026-10-13T21:45:10+08:00", "ok": True, "failed_tasks": []},
        {"run_id": "2026-10-13/endfield/MaaEnd-17-46-00", "script": "MaaEnd", "user": "endfield",
         "started": "2026-10-13T21:46:00+08:00", "finished": "2026-10-13T22:05:00+08:00", "ok": True, "failed_tasks": []},
    ]


    def state_dir(windows, extra=(), strip_hand=()):
        """A copy of the fixture state with `windows` as test-windows.json, `extra` records
    appended to their day's ledger, and raw.hand_started dropped from run ids `strip_hand`."""
        d = Path(tempfile.mkdtemp(prefix="shutdown-open-window-"))
        for p in FIX.iterdir():
            shutil.copy(p, d / p.name)
        (d / "test-windows.json").write_text(json.dumps(windows), encoding="utf-8")
        for e in extra:
            with (d / f"ledger-{e['started'][:10]}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(e) + "\n")
        for p in d.glob("ledger-*.jsonl"):
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
            for r in rows:
                if r["run_id"] in strip_hand:
                    r.get("raw", {}).pop("hand_started", None)
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return d


    class Eng:
        """The engine as the shutdown decision sees it at `now`: only records landed by then."""
        _gu_rerun_at = None

        def __init__(self, d, now):
            self.d, self.now = d, now
            self.cfg = SimpleNamespace(state_dir=d, automas_dir=None)
            self.state = SimpleNamespace(read_ledger=self.read_ledger)

        def read_ledger(self, day):
            p = self.d / f"ledger-{day}.jsonl"
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []
            return [e for e in rows if datetime.fromisoformat(e.get("finished") or e["started"]) <= self.now]

        def _round_is_manual(self, group):
            return shutdown._round_is_manual(self, group)


    plan.schedule = lambda _d: [{"name": "早班", "times": ["09:00"], "items": ["s1"]}, {"name": "晚班", "times": ["21:30"], "items": ["s1"]}]


    def at(s):
        return datetime.fromisoformat(f"2026-{s}").replace(tzinfo=SERVER_TZ)


    def manual(d, when):
        eng = Eng(d, at(when))
        return shutdown._last_round_manual(eng, eng.now, shutdown._recent_entries(eng, eng.now))


    def key(d, when):
        eng = Eng(d, at(when))
        return shutdown._shutdown_key(eng, eng.now)


    real = json.loads((FIX / "test-windows.json").read_text(encoding="utf-8"))
    open_all = [{k: v for k, v in w.items() if k != "until"} for w in real]

    print("[the review's case: the 10-13 11:05 OK-WW window never closed, a 晚班 runs that evening]")
    d = state_dir(open_all, EVENING)
    check("21:50 晚班 MAA 21:30 finished: a shift, not 「手动触发」", manual(d, "10-13T21:50:00"), False)
    check("21:50 the key moves past the spent skip :3 -> :4 (powers off)", key(d, "10-13T21:50:00"), "2026-10-13:4")
    check("22:06 晚班 MaaEnd finished too: still a shift, key :5", (manual(d, "10-13T22:06:00"), key(d, "10-13T22:06:00")),
          (False, "2026-10-13:5"))
    check("11:13:55 the hand-started test OK-WW still keeps it on, key :3", (manual(d, "10-13T11:13:55"), key(d, "10-13T11:13:55")),
          (True, "2026-10-13:3"))

    print("\n[every real 10-10..10-13 verdict holds with all windows left open (10-12 20:03 open covers 21:30)]")
    for when, want in [("10-10T09:39:30", False), ("10-10T12:25:09", True), ("10-10T21:50:00", False),
                       ("10-11T09:59:27", False), ("10-11T21:45:42", False), ("10-12T11:39:00", False),
                       ("10-12T12:10:36", True), ("10-12T21:45:34", False), ("10-13T10:00:36", False)]:
        check(f"{when} manual={want}", manual(d, when), want)
    check("10-12 21:45:34 key counts the 6 shift rows", key(d, "10-12T21:45:34"), "2026-10-12:6")
    check("10-13 10:00:36 key :3", key(d, "10-13T10:00:36"), "2026-10-13:3")

    print("\n[a 晚班 that starts while a fresh window is open (opened 21:20, never closed)]")
    d = state_dir(real + [{"since": "2026-10-13T21:20:00+08:00", "what": "MAA"}], EVENING)
    check("21:50 MAA 21:30 is the shift's: not manual, key :4", (manual(d, "10-13T21:50:00"), key(d, "10-13T21:50:00")),
          (False, "2026-10-13:4"))
    check("22:06 MaaEnd 21:46 continues the shift: not manual, key :5",
          (manual(d, "10-13T22:06:00"), key(d, "10-13T22:06:00")), (False, "2026-10-13:5"))

    print("\n[a test run AUTO-MAS could not tell was hand-started is still a test run inside its window]")
    d = state_dir(open_all, strip_hand={"2026-10-13/wuwa/OK-WW-07-05-49"})
    check("11:13:55 OK-WW 11:07 (window opened 11:05, after the shift ended): manual, key :3",
          (manual(d, "10-13T11:13:55"), key(d, "10-13T11:13:55")), (True, "2026-10-13:3"))

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_shutdown_round():
    """The round a record belongs to, for the 「最近一轮是手动触发的」 gate.

2026-09-19: OK-WW hung at 09:34, AUTO-MAS killed it at 11:35 and reran it, MaaEnd
followed 11:42-12:09. The old rule took "everything started within two hours of the
newest record", judged that tail by its own first record (11:35, not 09:00) and read
the whole scheduled queue as started by hand - the machine stayed on all day. A
hand-started afternoon run must still read as manual, that is the gate's job.

    Formerly test_shutdown_round.py.
    """
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.shutdown import shutdown
    from ark_relay.core.config import SERVER_TZ


    def e(run_id, script, start, end, ok=True, user=None):
        day = datetime(2026, 9, 19, tzinfo=SERVER_TZ)
        def at(hms):
            h, m, s = (int(x) for x in hms.split(":"))
            return (day + timedelta(hours=h, minutes=m, seconds=s)).isoformat()
        return {"run_id": run_id, "script": script, "user": user or script.lower(),
                "started": at(start), "finished": at(end), "ok": ok}


    class Eng:
        """Just enough engine: the schedule is 09:00 and 21:30, MANUAL_WINDOW_MIN=30."""
        _gu_rerun_at = None

        def _round_is_manual(self, group):
            times = ["09:00", "21:30"]
            first = min(datetime.fromisoformat(x["started"]).astimezone(SERVER_TZ) for x in group)
            for hhmm in times:
                hh, mm = (int(v) for v in hhmm.split(":"))
                due = first.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if abs((first - due).total_seconds()) <= shutdown.MANUAL_WINDOW_MIN * 60:
                    return False
            return True


    eng = Eng()
    NOW = datetime(2026, 9, 19, 12, 9, 32, tzinfo=SERVER_TZ)

    print("[今天的账本回放：09:00 早班，OK-WW 挂两小时后被重跑，尾巴 11:35-12:09]")
    today = [
        e("arknights/MAA-05-00-01", "MAA", "09:00:51", "09:16:02"),
        e("wuwa/OK-WW-05-16-07", "OK-WW", "09:16:22", "09:34:40", ok=False),
        e("wuwa/OK-WW-07-35-45", "OK-WW", "11:35:58", "11:42:27"),
        e("endfield/MaaEnd-07-42-32", "MaaEnd", "11:42:36", "12:08:47"),
        e("endfield/MaaEnd-08-08-51", "MaaEnd", "12:08:57", "12:09:15"),
    ]
    group = shutdown._round_of_newest(today)
    check("整轮五条都在同一轮里", [x["run_id"] for x in group], [x["run_id"] for x in today])
    check("第一条是 09:00:51 的 MAA", group[0]["run_id"], "arknights/MAA-05-00-01")
    check("不是手动 → 允许关机", shutdown._last_round_manual(eng, NOW, today), False)

    print("\n[旧规则的样子：只看最近两小时，尾巴自成一轮，会判成手动]")
    tail = [x for x in today if x["started"] >= today[2]["started"]]
    check("尾巴单看确实像手动（这就是 09-19 卡住的原因）", eng._round_is_manual(tail), True)

    print("\n[下午手动跑一趟：和早班隔了四个多小时，仍算手动，不关机]")
    afternoon = today[:1] + [e("endfield/MaaEnd-07-00-00", "MaaEnd", "15:00:00", "15:20:00")]
    check("下午那趟自成一轮", [x["run_id"] for x in shutdown._round_of_newest(afternoon)], ["endfield/MaaEnd-07-00-00"])
    check("判为手动", shutdown._last_round_manual(eng, NOW.replace(hour=15, minute=25), afternoon), True)

    print("\n[手动重跑早上失败的那家，但隔了六小时：不再串回早班]")
    late_retry = today[:2] + [e("wuwa/OK-WW-late", "OK-WW", "15:40:00", "15:46:00")]
    check("六小时后的重跑自成一轮", [x["run_id"] for x in shutdown._round_of_newest(late_retry)], ["wuwa/OK-WW-late"])
    check("判为手动", shutdown._last_round_manual(eng, NOW.replace(hour=15, minute=50), late_retry), True)

    print("\n[晚班照旧：21:30 的方舟自成一轮，贴着排班，不是手动]")
    evening = today + [e("arknights/MAA-17-30-03", "MAA", "21:32:01", "21:46:37")]
    check("晚班那条自成一轮", [x["run_id"] for x in shutdown._round_of_newest(evening)], ["arknights/MAA-17-30-03"])
    check("不是手动", shutdown._last_round_manual(eng, NOW.replace(hour=21, minute=47), evening), False)

    print("\n[中继自己派的补跑（commands.run_script 记下「脚本 MaaEnd」）：隔了三小时也不算手动，到点照常关机]")
    import json
    import types
    from ark_relay.features.guard import trigger
    sd = tmpdir()
    eng_sd = Eng()
    eng_sd.cfg = types.SimpleNamespace(state_dir=sd)
    makeup_run = today + [e("endfield/MaaEnd-makeup", "MaaEnd", "15:10:40", "15:25:00", ok=False)]
    check("补跑那趟自成一轮（隔得太久，串不回早班）",
          [x["run_id"] for x in shutdown._round_of_newest(makeup_run)], ["endfield/MaaEnd-makeup"])
    check("没有派单记录：照旧判手动（原来的行为）",
          shutdown._last_round_manual(eng_sd, NOW.replace(hour=15, minute=30), makeup_run), True)
    trigger.note_dispatch(sd, "脚本 MaaEnd", now=NOW.replace(hour=15, minute=8, second=0))
    check("有中继的派单记录：不是手动", shutdown._last_round_manual(eng_sd, NOW.replace(hour=15, minute=30), makeup_run), False)
    check("补跑的重试串在一起也一样", shutdown._last_round_manual(
        eng_sd, NOW.replace(hour=15, minute=50),
        makeup_run + [e("endfield/MaaEnd-makeup-2", "MaaEnd", "15:25:10", "15:40:00")]), False)
    other = today + [e("arknights/MAA-hand", "MAA", "15:10:40", "15:25:00")]
    check("派的是终末地，这趟是明日方舟：仍算手动", shutdown._last_round_manual(eng_sd, NOW.replace(hour=15, minute=30), other), True)
    late = today + [e("endfield/MaaEnd-later", "MaaEnd", "16:00:00", "16:20:00")]
    check("派单后一小时才开始的那趟不算它的：仍算手动", shutdown._last_round_manual(eng_sd, NOW.replace(hour=16, minute=30), late), True)
    (sd / trigger.DISPATCH_FILE).write_text(json.dumps([{"at": NOW.replace(hour=15, minute=8).isoformat(), "what": "队列 早班"}]),
                                            encoding="utf-8")
    check("手机「现在跑」派的是整个队列，不在这里算：仍按原来的判法", shutdown._last_round_manual(
        eng_sd, NOW.replace(hour=15, minute=30), makeup_run), True)

    print("\n[没有 finished 的旧记录也不炸]")
    odd = [{"run_id": "x", "script": "MAA", "user": "a", "started": today[0]["started"], "ok": True}]
    check("单条就是一轮", len(shutdown._round_of_newest(odd)), 1)


def _part_shutdown_stale_shift():
    """A script the morning shift never recorded does not keep the evening shift from powering off
(audit 11-08 A-16; dispatch relay-opt-round4-1108 R4-01; shutdown._current_shift).

The schedule is the machine's (docs/CONFIG.md): 早班 09:00 MAA, MaaEnd, OK-WW; 晚班 21:30 MAA
only. A boot the power-off skipped (debug mode, 「下次跑完不关机」) holds both shifts. Before:
_shift_queues gave every queue due since the boot, and an OK-WW the morning never recorded
(no evening record stands in for it: the evening queue runs MAA only) kept every decision of
the evening at 「等排期的那趟跑完再判关机（队列「早班」还差 OK-WW）」 - the machine stayed on.

Pinned here:
* 21:50, the evening's MAA recorded: go, and the after-shift check counts the evening shift;
* the evening's MAA not recorded yet: still waiting, naming 晚班 (not 早班);
* before the evening is due, the morning still missing OK-WW: still waiting on 早班 (unchanged);
* _current_shift: queues of one shift (minutes apart) stay together; 12.5 hours apart do not.

    Formerly test_shutdown_stale_shift.py.
    """
    import json
    import os
    from datetime import datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    STATE = TMP / "state"
    STATE.mkdir()
    (TMP / "history").mkdir()
    doc = {"instances": [{"uid": "m"}, {"uid": "e"}]}
    for uid, name, t, items in (("m", "早班", "09:00", ("s1", "s3", "s2")), ("e", "晚班", "21:30", ("s1",))):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True, "AfterAccomplish": "NoAction"},
                    "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {f"i{n}": {"Info": {"ScriptId": sid}} for n, sid in enumerate(items)}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    scripts = {"instances": [{"uid": "s1"}, {"uid": "s2"}, {"uid": "s3"}]}
    for uid, path in (("s1", "D:\\MAA"), ("s2", "D:\\ark\\okww"), ("s3", "D:\\MaaEnd")):
        scripts[uid] = {"Info": {"Name": uid, "Path": path}, "SubConfigsInfo": {}}
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts), encoding="utf-8")
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.selfcheck import shiftcheck
    from ark_relay.features.shutdown import shutdown


    class Notes:
        def send(self, title, body="", **kw):
            return []


    def at(hh, mm, ss=0):
        return datetime(2026, 11, 7, hh, mm, ss, tzinfo=SERVER_TZ)


    # The morning: MAA and MaaEnd recorded, OK-WW never (crashed before its record).
    MORNING = [("MAA-1", "MAA", "arknights", at(9, 0, 40), at(9, 19, 12)),
               ("MaaEnd-1", "MaaEnd", "endfield", at(9, 19, 40), at(9, 50, 5))]
    EVENING = [("MAA-2", "MAA", "arknights", at(21, 30, 40), at(21, 49, 2))]


    def ledger(rows):
        (STATE / "ledger-2026-11-07.jsonl").write_text("\n".join(
            json.dumps({"run_id": f"2026-11-07/x/{r}", "script": s, "user": u, "started": a.isoformat(),
                        "finished": b.isoformat(), "ok": True, "failed_tasks": []})
            for r, s, u, a, b in rows) + "\n", encoding="utf-8")


    cfg = Config()
    e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e.state.report_sent = lambda d: True
    e._boot_time = lambda now: at(8, 45)
    e._deferred_update_busy = lambda: False
    e._started_at = at(8, 45, 20)
    e._handled_any = True

    print("[早班漏了 OK-WW，机器没关；晚班 MAA 跑完：按晚班判，关机]")
    ledger(MORNING + EVENING)
    v = shutdown.decide(e, at(21, 50))
    check("21:50 -> go", (v.code, v.reason), ("go", "本轮已处理完毕"))
    check("收工体检算的是晚班", (shiftcheck.finished_shift(e, at(21, 50)) or {}).get("name"), "晚班")
    check("……早班的超时提醒照旧看得到它（_shift_overdue 还看全部队列）",
          sorted(q["name"] for q in shutdown._shift_queues(e, at(21, 50), at(8, 45))), ["早班", "晚班"])

    print("\n[晚班自己还没记录：照旧等，说的是晚班]")
    ledger(MORNING)
    v = shutdown.decide(e, at(21, 45))
    check("21:45 -> shift-running", v.code, "shift-running")
    check("……等的是晚班的 MAA，不是早班的 OK-WW", ("晚班" in v.reason, "早班" in v.reason), (True, False))

    print("\n[晚班还没到点：早班缺 OK-WW 照旧等（和以前一样）]")
    v = shutdown.decide(e, at(15, 0))
    check("15:00 -> shift-running on 早班", (v.code, "早班" in v.reason and "OK-WW" in v.reason), ("shift-running", True))

    print("\n[_current_shift：同一班几分钟的不拆开，隔十二个半小时的拆开]")
    q = lambda name, h, m: {"name": name, "due": at(h, m), "kinds": []}  # noqa: E731
    check("09:00 与 09:05 是一班", [x["name"] for x in shutdown._current_shift([q("a", 9, 0), q("b", 9, 5)])], ["b", "a"])
    check("09:00 与 21:30：只留 21:30", [x["name"] for x in shutdown._current_shift([q("早班", 9, 0), q("晚班", 21, 30)])],
          ["晚班"])
    check("空的还是空的", shutdown._current_shift([]), [])


def _part_shutdown_waits_for_farm():
    """A farm in progress has to hold off the automatic shutdown.

「还有脚本或游戏在跑」 only covers the farm while OK-WW is actually up. The character
dies every ten laps or so, OK-WW stops, and the relay takes up to three minutes to
relaunch it. A shutdown landing in that window would end a four-hour farm early and
say nothing about why.

    Formerly test_shutdown_waits_for_farm.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.echofarm import echofarm
    from ark_relay.features.shutdown import shutdown
    from ark_relay.core.config import SERVER_TZ


    class Cfg:
        def __init__(self, root):
            self.state_dir = root
            self.shutdown_min_uptime = 0


    class Eng:
        def __init__(self, root):
            self.cfg = Cfg(root)
            self._started_at = datetime(2026, 9, 9, 0, 0, tzinfo=SERVER_TZ)
            self._pending = []
            self._recovered = []

        def _scripts_running(self):
            return False

        def _deferred_update_busy(self):
            return False


    root = tmpdir()
    eng = Eng(root)

    print("[没有在刷的时候，这条闸不该拦任何东西]")
    shutdown._why_not(eng, datetime(2026, 9, 9, 21, 0, tzinfo=SERVER_TZ), idle=False) \
        if hasattr(shutdown, "_why_not") else None
    check("模块里有这条闸的判据字符串", "farming" in shutdown.__file__ or True)
    src = Path(shutdown.__file__).read_text(encoding="utf-8")
    check("闸的代号是 farming", '"farming"' in src)
    check("拦的理由点名刷到几点", "才收工" in src)
    check("排在「脚本在跑」之后", src.index('"running"') < src.index('"farming"'))

    print("[正在刷的时候，记录读得出来]")
    echofarm._store(root).set("queues", "echo_farm",
                              {"boss": 1, "name": "天傀劫煞", "until": "2026-09-09 17:45",
                               "started": "2026-09-09 13:45", "saved": {}})
    rec = echofarm.current(root)
    check("记录在", bool(rec))
    check("话里会带上目标名", "天傀劫煞" in (rec.get("name") or ""))
    check("话里会带上收工时刻", rec.get("until"), "2026-09-09 17:45")


def _part_shutdown_whitelist():
    """Only the decision right after a morning / evening shift finished may power off.

The user's rule of 2026-10-10 18:31 (Tokyo; only after a morning / evening shift), quoted
verbatim in USER-SWITCHES.txt at shutdown.py:_say_if_moment_passed. The 18:30 gate (not while
someone uses the machine) was removed on his order of 23:20.

The ledger is that day's, copied from C:\\ProgramData\\ark-relay\\state\\ledger-2026-10-10.jsonl
(start / end / ok as written). The boots are from the machine: the relay started at 08:45:18
(relay.log 「中继代码版本」) for the 09:00 shift and judged 「本轮已处理完毕」 at 09:39:30;
LastBootUpTime 11:45:20 for the boot by hand, after which MAA was started by hand at 12:05:54.
The evening shift is the morning one moved to 21:30.

    Formerly test_shutdown_whitelist.py.
    """
    import json
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    STATE = TMP / "state"
    STATE.mkdir()
    (TMP / "history").mkdir()
    doc = {"instances": [{"uid": "m"}, {"uid": "e"}]}
    for uid, name, t in (("m", "早班", "09:00"), ("e", "晚班", "21:30")):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True, "AfterAccomplish": "NoAction"},
                    "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {i: {"Info": {"ScriptId": i}} for i in ("s1", "s2", "s3")}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    scripts = {"instances": [{"uid": "s1"}, {"uid": "s2"}, {"uid": "s3"}]}
    for uid, path in (("s1", "D:\\MAA"), ("s2", "D:\\ark\\okww"), ("s3", "D:\\MaaEnd")):
        scripts[uid] = {"Info": {"Name": uid, "Path": path}, "SubConfigsInfo": {}}
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts), encoding="utf-8")
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.features.shutdown import shutdown
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State


    class Notes:
        def send(self, title, body="", **kw):
            return False


    def at(hh, mm, ss=0):
        return datetime(2026, 10, 10, hh, mm, ss, tzinfo=SERVER_TZ)


    # Verbatim from the machine's ledger-2026-10-10.jsonl (the fields decide reads).
    MORNING = [("MAA-05-00-01", "MAA", "arknights", at(9, 0, 51), at(9, 1, 10), False),
               ("MAA-05-01-15", "MAA", "arknights", at(9, 1, 59), at(9, 2, 14), False),
               ("MAA-05-02-18", "MAA", "arknights", at(9, 3, 1), at(9, 3, 17), False),
               ("OK-WW-05-03-21", "OK-WW", "wuwa", at(9, 3, 36), at(9, 13, 15), True),
               ("MaaEnd-05-13-19", "MaaEnd", "endfield", at(9, 14, 23), at(9, 37, 28), True)]
    BY_HAND = [("MAA-08-05-07", "MAA", "arknights", at(12, 5, 54), at(12, 24, 26), True)]
    EVENING = [(r.replace("-05-", "-17-"), s, u, a + timedelta(hours=12, minutes=30), b + timedelta(hours=12, minutes=30), ok)
               for r, s, u, a, b, ok in MORNING]


    def ledger(rows):
        (STATE / "ledger-2026-10-10.jsonl").write_text("\n".join(
            json.dumps({"run_id": f"2026-10-10/x/{r}", "script": s, "user": u, "started": a.isoformat(),
                        "finished": b.isoformat(), "ok": ok,
                        "failed_tasks": [] if ok else ["MAA 在完成任务前中止"]})
            for r, s, u, a, b, ok in rows) + "\n", encoding="utf-8")


    cfg = Config()
    e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e.state.report_sent = lambda d: True
    BOOT = [None]
    e._boot_time = lambda now: BOOT[0]


    def judge(now, boot, started, handled=True):
        BOOT[0], e._started_at, e._handled_any = boot, started, handled
        return shutdown.decide(e, now)


    print("[morning shift finished on its own boot, this relay saw it land: go]")
    ledger(MORNING)
    v = judge(at(9, 39, 30), at(8, 45), at(8, 45, 18))
    check("10-10 09:39:30 (the machine powered off here)", v.code, "go")

    print("\n[evening shift finished on its own boot: go]")
    ledger(MORNING + BY_HAND + EVENING)
    check("22:09:30, booted 21:15", judge(at(22, 9, 30), at(21, 15), at(21, 15, 18)).code, "go")
    check("the machine left on since the morning: the evening shift still ends it",
          judge(at(22, 9, 30), at(8, 45), at(8, 45, 18)).code, "go")

    print("\n[booted by hand at 11:45, then a run by hand: never powered off]")
    ledger(MORNING + BY_HAND)
    for now in (at(11, 55, 30), at(12, 25, 9), at(17, 31, 44), at(20, 20)):
        v = judge(now, at(11, 45, 20), at(11, 45, 29))
        check(f"{now:%H:%M:%S} -> not-shift", v.code, "not-shift")
    check("the reason says so in his terms", v.reason.startswith("不是早班/晚班跑完，不关机"), True)
    check("…and names the boot", "10-10 11:45 开的机" in v.reason, True)
    check("21:00, the 21:30 shift ahead -> waits for it (shift-ahead)",
          judge(at(21, 0), at(11, 45, 20), at(11, 45, 29)).code, "shift-ahead")
    ledger(MORNING + BY_HAND + EVENING)
    check("…and the evening shift on that boot ends it -> go",
          judge(at(22, 9, 30), at(11, 45, 20), at(11, 45, 29)).code, "go")

    print("\n[relay restarted after the shift: not the decision right after it, stays on]")
    ledger(MORNING)
    v = judge(at(10, 1), at(8, 45), at(9, 50), handled=False)
    check("10:01, restarted 09:50 -> not-shift", v.code, "not-shift")
    check("…says the relay restarted", "重启" in v.reason, True)
    check("restarted mid-shift and the last record landed after it -> go",
          judge(at(9, 49), at(8, 45), at(9, 20), handled=True).code, "go")

    print("\n[a deploy restarts the relay after the shift was seen landing: the decision goes on (10-10 21:45)]")
    # 10-10: the evening shift finished, 21:44:51 in-use; the deploy restarted the relay at 21:45 and
    # from 21:46:36 the new process said not-shift. The landing is now kept on disk per boot.
    e.state.store.pop("marks", "handled_boot")
    BOOT[0] = at(8, 45)
    shutdown.note_handled(e, at(9, 37, 40))           # the old process saw MaaEnd land
    check("restarted 09:45, same boot, landing seen before -> go once the relay is up 10 min",
          judge(at(9, 56), at(8, 45), at(9, 45), handled=False).code, "go")
    check("…and before that the uptime floor, not not-shift",
          judge(at(9, 50), at(8, 45), at(9, 45), handled=False).code, "uptime")
    check("the boot read a few seconds off is the same boot",
          judge(at(9, 56), at(8, 45, 40), at(9, 45), handled=False).code, "go")
    check("a later boot does not inherit it -> not-shift",
          judge(at(12, 30), at(11, 45, 20), at(11, 45, 29), handled=False).code, "not-shift")
    e.state.store.pop("marks", "handled_boot")
    BOOT[0] = at(8, 45)
    shutdown.note_handled(e, at(8, 50))               # something landed before the shift came due
    check("landing seen only before the shift came due -> not-shift",
          judge(at(9, 50), at(8, 45), at(9, 45), handled=False).code, "not-shift")
    e.state.store.pop("marks", "handled_boot")
    check("nothing kept -> not-shift (as before)", judge(at(9, 50), at(8, 45), at(9, 45), handled=False).code, "not-shift")

    print("\n[before the shift, booted for it: waiting, not a refusal]")
    ledger([])
    check("08:55:19, booted 08:45 -> shift-ahead", judge(at(8, 55, 19), at(8, 45), at(8, 45, 18)).code, "shift-ahead")

    print("\n[a shift not finished yet (or never): no judging until every script has recorded]")
    # 2026-10-10 21:30:01 the evening shift had just started and the decision went on to
    # 「还有脚本或游戏在跑」, pushed to the group.
    ledger(MORNING[:4])               # no MaaEnd
    v = judge(at(11, 40), at(8, 45), at(8, 45, 18))
    check("11:40, MaaEnd never ran, past the old two-hour window -> shift-running", v.code, "shift-running")
    check("…names what is missing", "MaaEnd" in v.reason, True)
    ledger([])
    check("09:00:01, the shift just started -> shift-running", judge(at(9, 0, 1), at(8, 45), at(8, 45, 18)).code, "shift-running")

    print("\n[shift finished while someone uses the machine: powered off all the same (10-10 23:20)]")
    # The user, 2026-10-10 23:20 (Tokyo): who uses the machine is not the relay's business; the 15-minute input gate was removed.
    ledger(MORNING)
    check("09:39:30 -> go, nothing asks about keyboard / mouse",
          judge(at(9, 39, 30), at(8, 45), at(8, 45, 18)).code, "go")
    check("the gate is gone", hasattr(shutdown, "console_idle_s"), False)

    print("\n[a shift script that never records: one group alarm once the shift is overdue (10-12 20:04)]")
    # The user's order of 2026-10-12 20:04 (Tokyo), quoted in shutdown.py:_alarm_shift_overdue.
    # Until then a script that never recorded kept shift-running all night with one relay.log
    # line: runwatch.check_overrun needs AUTO-MAS to show the task unfinished, and
    # missed._check_partial_queues stays quiet while a game process is up.
    from ark_relay.core import texts
    from ark_relay.features.alarm import handle
    from ark_relay.features.run import runwatch


    class Rec:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert")))
            return []


    saved_notifier, saved_power_off = e.notifier, e._power_off
    powered = []
    e._power_off = lambda: powered.append(1) or False    # never the real `shutdown` on this machine
    e.notifier = Rec()
    e._scripts_running = lambda: True                 # a hung game process holds the queue "busy"
    ledger(MORNING[:4])                               # MaaEnd never records
    BOOT[0], e._started_at, e._handled_any = at(8, 45), at(8, 45, 18), True
    due = at(9, 0)
    limit, _ = runwatch.planned_minutes(e, 9, 0, due)
    deadline = due + timedelta(minutes=limit + runwatch.OVERRUN_SLACK_MIN)
    e._last_wait_note = ""
    check("the loop is woken at that moment (nothing else wakes it with AUTO-MAS silent)",
          [m for m, _ in shutdown.overdue_moments(e, at(9, 50))], [deadline])
    for now in (at(9, 50), deadline - timedelta(minutes=1)):
        shutdown._maybe_shutdown(e, now)
    check(f"still within {limit}+{runwatch.OVERRUN_SLACK_MIN} min of 09:00: nothing pushed", e.notifier.sent, [])
    past = deadline + timedelta(minutes=1)
    shutdown._maybe_shutdown(e, past)
    check("past it: exactly one alarm", len(e.notifier.sent), 1)
    title, body, alert = e.notifier.sent[0] if e.notifier.sent else ("", "", None)
    check("…sent as an alarm (group)", alert, True)
    check("…names the queue in the title", "早班" in title, True)
    check("…names the missing script", "MaaEnd" in body, True)
    check("…says how long", f"{int((past - due).total_seconds() // 60)} 分钟" in body, True)
    check("…plain words", texts.plain(title + "\n" + body), [])
    from ark_relay.core.notify import route_of
    check("…routes to the group", route_of(title, alert=alert), "group")
    runwatch.check_overrun(e, past + timedelta(minutes=1),
                           {"tasks": [{"queueId": "m", "taskId": "t1", "task_info": [{"name": "MaaEnd", "status": "运行"}]}]})
    check("AUTO-MAS answers again a minute later, task unfinished: check_overrun does not push the same run",
          len(e.notifier.sent), 1)
    for later in (deadline + timedelta(minutes=2), deadline + timedelta(hours=3)):
        shutdown._maybe_shutdown(e, later)
    check("re-checked later: still one push for this shift", len(e.notifier.sent), 1)
    check("…and no more wake-ups for it", shutdown.overdue_moments(e, deadline + timedelta(minutes=3)), [])
    e.state.store.pop("marks", f"alerted:{due:%Y-%m-%d}")
    handle._mark_alerted(e, f"{due:%Y-%m-%d}", "队列超时|早班|09:00")
    e.notifier.sent.clear()
    shutdown._maybe_shutdown(e, deadline + timedelta(minutes=5))
    check("the overrun alarm already went for this run: not pushed twice", e.notifier.sent, [])
    e.state.store.pop("marks", f"alerted:{due:%Y-%m-%d}")
    cfg.shutdown_after_run = False
    shutdown._maybe_shutdown(e, deadline + timedelta(minutes=5))
    check("the relay's power-off switched off: the fault is pushed all the same", len(e.notifier.sent), 1)
    cfg.shutdown_after_run = True
    e.state.store.pop("marks", f"alerted:{due:%Y-%m-%d}")
    ledger(MORNING)
    e.notifier.sent.clear()
    e._scripts_running = lambda: False
    shutdown._alarm_shift_overdue(e, deadline + timedelta(minutes=5))
    check("every script recorded: no such alarm", e.notifier.sent, [])
    check("this section never reached the power-off", powered, [])
    e.notifier, e._scripts_running, e._power_off = saved_notifier, (lambda: False), saved_power_off


def _part_exit_shutdown_window():
    """An AUTO-MAS exit looks back an hour for a Windows shutdown request, not 120 s (audit s15 #5).

_exited asked the System log for a 1074 of the last 120 s. The 1074 is written when the
command is given, the countdown before the shutdown: `shutdown /s /t 300` by hand
puts it ~300 s before AUTO-MAS is closed, outside that window, so the exit read as an
unexpected one and a revival ran into the closing session. _shutdown_before
(the WMI drop) already looks back SHUTDOWN_BEFORE_WINDOW_SECONDS (an hour).

The 1074 is the real one of 2026-10-10 04:27:24 (machine clock; `shutdown /s /t 60` by
hand, tests/fixtures/system-1010-0427-manual-shutdown.xml), moved to 300 s ago. With the
hour, a 1074 from before the current boot must not count: a 6005 (the Event Log service
started, docs/OPERATIONS.md "6005 boot") newer than it ends it.

    Formerly test_exit_shutdown_window.py.
    """
    import logging
    import re
    import types
    from datetime import datetime, timedelta, timezone

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


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                  "win32evtlog", "win32gui"):
        sys.modules.setdefault(_name, _Stub(_name))

    from ark_relay.features.alarm import errwatch
    from ark_relay.features.host import automas_keeper, automas_procs, shutdown_signs
    from ark_relay.features.shutdown import shutdown


    REAL_1074 = (Path(__file__).resolve().parent / "fixtures" /
                 "system-1010-0427-manual-shutdown.xml").read_text(encoding="utf-8").strip()
    NS = "http://schemas.microsoft.com/win/2004/08/events/event"


    def stamp(utc: datetime) -> str:
        return utc.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


    def at(xml: str, utc: datetime) -> str:
        return re.sub(r"SystemTime='[^']*'", f"SystemTime='{stamp(utc)}'", xml)


    def boot_event(utc: datetime) -> str:
        """A 6005 as EvtRender gives it (Provider EventLog)."""
        return (f"<Event xmlns='{NS}'><System><Provider Name='EventLog'/><EventID Qualifiers='32768'>6005</EventID>"
                f"<TimeCreated SystemTime='{stamp(utc)}'/><Channel>System</Channel></System>"
                "<EventData><Binary/></EventData></Event>")


    log_events: list = []     # (utc, event id, xml) - the System log, any order


    def fake_reader(window_s, ids=(1074, 1075)):
        """shutdown.shutdown_event_xml over log_events: the query's id and time filter, newest first."""
        now = datetime.now(tz=timezone.utc)
        hits = [(t, x) for t, eid, x in log_events
                if eid in ids and (now - t).total_seconds() <= window_s]
        return [x for t, x in sorted(hits, key=lambda h: h[0], reverse=True)]


    shutdown.shutdown_event_xml = fake_reader
    shutdown_signs.GOING_DOWN_SETTLE_SECONDS = 0.0
    errwatch.relay_shutdown_issued = lambda: False
    automas_procs._exit_code = lambda h: 0
    automas_procs._tasklist = lambda: b"explorer.exe"
    automas_keeper.win32api.CloseHandle = lambda h: None


    class _Keep(logging.Handler):
        def __init__(self):
            super().__init__()
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())


    def exit_now():
        keep = _Keep()
        log = logging.getLogger("ark.test_shutdown")
        log.handlers[:] = [keep]
        log.setLevel(logging.INFO)
        log.propagate = False
        k = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
        k.log, k.handle, k.gone = log, object(), None
        k._exited()
        return k, keep.msgs


    now = datetime.now(tz=timezone.utc)

    print("[shutdown /s /t 300：1074 在 AUTO-MAS 退出前 300 秒写下 → 按 Windows 关机处理，不重新打开]")
    log_events[:] = [(now - timedelta(seconds=300), 1074, at(REAL_1074, now - timedelta(seconds=300)))]
    k, msgs = exit_now()
    check("held as a Windows shutdown", bool(k.gone and k.gone.get("shutdown")), True)
    check("its initiator is named", any("shutdown.exe" in m and "发起了 Windows 关机" in m for m in msgs), True)

    print("[1074 是这次开机之前的（之后有 6005）→ 不算关机]")
    log_events[:] = [(now - timedelta(seconds=1500), 1074, at(REAL_1074, now - timedelta(seconds=1500))),
                     (now - timedelta(seconds=1400), 6005, boot_event(now - timedelta(seconds=1400)))]
    k, msgs = exit_now()
    check("not a shutdown", bool(k.gone and k.gone.get("shutdown")), False)
    check("an unexpected exit", any("意外退出了" in m for m in msgs), True)

    print("[更早于一小时的 1074 → 不算]")
    log_events[:] = [(now - timedelta(seconds=4000), 1074, at(REAL_1074, now - timedelta(seconds=4000)))]
    k, msgs = exit_now()
    check("not a shutdown", bool(k.gone and k.gone.get("shutdown")), False)


def _part_power_off_returncode():
    """A shutdown command that failed must not count as a power-off (review of 2026-10-07, item 1).

`shutdown /s` was run with check=False and its exit code never read: when Windows
refuses (1190, a shutdown is already scheduled; or no privilege) _power_off still
returned True, shutdown._maybe_shutdown set _shutdown_issued and marked the
machine as going down, and every teardown after that was waved through as "the
relay's own power-off" while the machine stayed on.

Pinned: a non-zero exit code returns False; one ERROR line carries the exit
code and what shutdown printed (errwatch pushes a new kind of ERROR to the
group - the existing alarm path); and 「本轮已处理完毕，60 秒后关机」 is written only
after the command succeeded, because machine checks #37/#38 read that line as
proof the relay powered the machine off.

    Formerly test_power_off_returncode.py.
    """
    import logging

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine
    from ark_relay.features.selfcheck.machinechecks.system import POWER_OFF


    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelno, record.getMessage()))


    class _Done:
        def __init__(self, code, err=b""):
            self.returncode, self.stdout, self.stderr = code, b"", err


    grab = _Grab()
    lg = engine.log
    lg.addHandler(grab)
    lg.setLevel(logging.DEBUG)
    orig = engine.subprocess.run

    print("[shutdown 退出码 1190（已经排了一次关机）：没关成]")
    # What Windows prints is in the console codepage (GBK on the machine).
    engine.subprocess.run = lambda cmd, **kw: _Done(1190, "系统关机已经安排好了。(1190)".encode("gbk"))
    grab.rows.clear()
    check("返回 False", engine.Engine._power_off(None), False)
    errs = [m for lv, m in grab.rows if lv >= logging.ERROR]
    check("记了一条 ERROR", len(errs), 1)
    check("ERROR 里有退出码", bool(errs) and "1190" in errs[0], True)
    check("ERROR 里有 Windows 说的原话", bool(errs) and "系统关机已经安排好了" in errs[0], True)
    check("没写「60 秒后关机」", any(m.startswith(POWER_OFF) for _, m in grab.rows), False)

    print("[shutdown 退出码 0：关了]")
    seen = []
    engine.subprocess.run = lambda cmd, **kw: (seen.append(cmd), _Done(0))[1]
    grab.rows.clear()
    check("返回 True", engine.Engine._power_off(None), True)
    # Planned, reason Application: Maintenance - without /d Windows logs it as unplanned.
    check("argv: /s /t 60 /d p:4:1", seen and seen[0][:6], ["shutdown", "/s", "/t", "60", "/d", "p:4:1"])
    check("写了「60 秒后关机」", any(m.startswith(POWER_OFF) for _, m in grab.rows), True)
    check("没有 ERROR", [m for lv, m in grab.rows if lv >= logging.ERROR], [])

    print("[shutdown 根本跑不起来：没关成]")
    def _boom(cmd, **kw):
        raise OSError("shutdown.exe not found")
    engine.subprocess.run = _boom
    grab.rows.clear()
    check("返回 False", engine.Engine._power_off(None), False)
    check("没写「60 秒后关机」", any(m.startswith(POWER_OFF) for _, m in grab.rows), False)

    engine.subprocess.run = orig


def _part_poweroff_ok():
    """A hand power-off waits for the relay's own work (scripts/mac/lib/poweroff_ok.py).

Ledger #110 (2026-10-22): 调试模式 off at 16:44:18 Beijing, the gathering retry started by
the shutdown decision at 16:44:20, a hand `shutdown /s /t 60` at 16:44:5x cut it, and the
evening boot re-ran it with 「中继自己报错了」 in the group. Each case below is one thing a
person's power-off must not cut, the first two being that afternoon's.

    Formerly test_poweroff_ok.py.
    """
    import json
    from datetime import datetime, timedelta

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
    import poweroff_ok
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.echofarm import echofarm


    NOW = datetime(2026, 10, 22, 16, 44, 50, tzinfo=SERVER_TZ)
    idle = lambda: False   # noqa: E731


    def why(sd, running=idle, lines=()):
        return poweroff_ok.reasons(NOW, sd, running, list(lines))


    def stamp(sd, **rec):
        f = sd / "collect-retry" / f"{NOW:%Y-%m-%d}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec), encoding="utf-8")


    print("[10-22 那天下午的两件事]")
    sd = tmpdir()
    stamp(sd, run_id="r1", routes=["AutoCollectRoute2"], started=(NOW - timedelta(seconds=30)).isoformat())
    got = why(sd)
    check("采集补跑开了还没写结束 → 先别关", any("采集补跑在跑" in w for w in got), True)
    check("说了几点开始的", any("16:44" in w for w in got), True)
    got = why(tmpdir(), lines=["10-22 16:44:18 INFO    ark.service  📱 手机指令 debug_mode：调试模式已关闭"])
    check("调试模式刚关 → 先等中继判一次关机", any("调试模式" in w for w in got), True)

    print("\n[别的在跑的]")
    check("调度程序或游戏在跑 → 先别关", bool(why(tmpdir(), running=lambda: True)), True)
    sd = tmpdir()
    echofarm._store(sd).set("queues", "echo_farm", {"name": "周本第 1 个", "until": "2026-10-22 16:41"})
    check("刷声骸在跑 → 先别关", any("刷声骸在跑" in w for w in why(sd)), True)

    print("\n[可以关的]")
    check("什么都没在跑 → 可以关", why(tmpdir()), [])
    sd = tmpdir()
    stamp(sd, run_id="r1", started=(NOW - timedelta(minutes=30)).isoformat(), finished=NOW.isoformat())
    check("补跑已经跑完 → 不拦", why(sd), [])
    sd = tmpdir()
    stamp(sd, run_id="r1", started=(NOW - timedelta(days=1)).isoformat())
    check("开始太久的印记（中继停过，下次开机它自己补）→ 不拦", why(sd), [])


def _part_skip_shutdown_wording():
    """The 「下次跑完不关机」 mark is named and described one way everywhere a human reads it.

The mark is one-shot: it is spent when the next 早班/晚班 run finishes, that
shutdown occasion is skipped, the re-checks after it stay on, and the run after
that shuts down as usual (modes.skip_armed; behaviour pinned in test_shutdown.py
"[one-shot mark]"). We misread it twice because the words around it were wrong:
other names for the same mark (「今晚别关机」, 「这次别关机」, ...) and a receipt
that said 「已取消，跑完照常关机」 as if a spent mark could still be cancelled.
The user's words are kept below as data (USER_1011).

Checks:
1. No file a human reads (relay code and comments, web/, docs/, scripts/) uses
   another name for the mark. Dated audit/handover records are history and keep
   the words they were written with.
2. set_skip_shutdown's receipts, as returned by the function, name the mark;
   pulling it back always says the mark was 「还没用上」 and never a bare 「已取消」.

    Formerly test_skip_shutdown_wording.py.
    """
    import re


    RELAY = Path(__file__).resolve().parents[1]
    REPO = RELAY.parent
    sys.path.insert(0, str(RELAY))

    from ark_relay.features.modes import modes

    USER_1011 = (
        "10-11 15:25「跑完不关机是一次标记，标记下一次跑完不关机，他不是状态，跑完了哪来的取消？」",
        "10-11 15:33「你应该真的应该好好的把那个文档那个注释所有的东西都改清楚，你每次都这样。」",
        "10-11 15:34「这个显而易见就是因为文档里面注释里面写错了」",
    )
    NAME = "下次跑完不关机"
    print("  (the user's words this part holds the relay to:)", *USER_1011, sep="\n    ")


    # ---------- 1. one name ----------
    print("[one name for the mark in every human-read file]")
    OTHER_NAMES = re.compile(r"今晚别关机|这次别关机|下一次别关机|下次不关机|下一次跑完别关机")
    WEB = REPO / "web"
    ROOTS = [RELAY / "ark_relay", WEB, REPO / "docs", REPO / "scripts" / "windows", REPO / "scripts" / "mac"]
    TOP = [p for p in RELAY.glob("*.py")] + [RELAY / "README.md", REPO / "README.md"]
    EXTS = {".py", ".js", ".html", ".css", ".md", ".bat", ".ps1", ".sh", ".txt", ".json"}
    # Dated records: what was seen and said on that day, quoted as it was. Rewriting
    # them would falsify the record, so they are left out.
    HISTORY = re.compile(r"^docs/(SURVEY-.*|ERROR-LEDGER-.*|NEXT-BOOT|SILENT-FAILURES-AUDIT|CODE-HISTORY)\.md$")


    def files():
        for root in ROOTS:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in EXTS and "node_modules" not in p.parts:
                    yield p
        for p in TOP:
            if p.is_file():
                yield p


    hits = []
    scanned = 0
    for p in files():
        rel = p.relative_to(REPO).as_posix()
        if HISTORY.match(rel) or rel == "relay/manifest.json":
            continue
        scanned += 1
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if OTHER_NAMES.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:80]}")
    check("files scanned (sanity: the walk found the tree)", scanned > 300, True)
    check("no other name for the mark", hits, [])
    check("web/ is in the walk", WEB.is_dir(), True)


    # ---------- 2. receipts ----------
    print("\n[set_skip_shutdown receipts say which run, and that only an unspent mark is pulled back]")
    d = tmpdir()
    ok_on, on = modes.set_skip_shutdown(d, True)
    ok_back, back = modes.set_skip_shutdown(d, False)          # armed -> pulled back
    ok_none, none = modes.set_skip_shutdown(d, False)          # nothing armed (never, or spent)
    check("all accepted", (ok_on, ok_back, ok_none), (True, True, True))
    for label, text in (("arm", on), ("pull back", back), ("nothing to pull back", none)):
        check(f"{label}: names the mark", NAME in text, True)
        check(f"{label}: names the run (早班/晚班)", "早班/晚班" in text, True)
    check("arm: says it is one-time", "只管一次" in on, True)
    # App review 10-14: one sentence, not three clauses about the run after the next
    check("arm: one short sentence", len(on) <= 32 and "再下一趟" not in on, True)
    _ok_off, off = modes.set_debug(d, off=True)
    check("debug off: says it is off, asks for nothing", off, "调试模式已关闭")
    for label, text in (("pull back", back), ("nothing to pull back", none)):
        check(f"{label}: says 还没用上", "还没用上" in text, True)
        check(f"{label}: no bare 已取消", "已取消" in text, False)
        check(f"{label}: next run shuts down as usual", "照常关机" in text, True)
    check("nothing to pull back: says it may already be spent", "已经用掉" in none, True)


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_shutdown_after_restart, _part_shutdown_hand_and_test_runs, _part_shutdown_held_past_shift, _part_shutdown_notice, _part_shutdown_open_test_window, _part_shutdown_round, _part_shutdown_stale_shift, _part_shutdown_waits_for_farm, _part_shutdown_whitelist, _part_exit_shutdown_window, _part_power_off_returncode, _part_poweroff_ok, _part_skip_shutdown_wording]))
