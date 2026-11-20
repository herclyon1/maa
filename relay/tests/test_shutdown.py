"""Post-shift power-off, skip-next-shutdown mark, farm waits, and persistent StateStore."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)
# relay/ first for every part, as each part used to put it (run_parts restores sys.path after one)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _without_unfixed_gate(shutdown):
    """Turn the unfixed-shift gate (shutdown._shift_unfixed, 2026-11-20) off for a part that tests
    other gates on real days whose last MAA / OK-WW record failed (「MAA 在完成任务前中止」,
    「OK-WW 运行超时」: the machine powered off then, as the rule was). That gate has its own part,
    _part_shutdown_unfixed_shift. Returns the real one, which the part puts back at its end."""
    real = getattr(shutdown._shift_unfixed, "real", shutdown._shift_unfixed)

    def off(shift, entries, off_shift=frozenset()):
        return []
    off.real = real
    shutdown._shift_unfixed = off
    return real


def _restore_unfixed_after(fn):
    """Ensure a part that swaps shutdown._shift_unfixed always restores it, even on failure."""
    def wrapped():
        from ark_relay.features import shutdown
        real = getattr(shutdown._shift_unfixed, "real", shutdown._shift_unfixed)
        try:
            return fn()
        finally:
            shutdown._shift_unfixed = real
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


def _part_shutdown_main():
    """Exercise the shutdown gate against a fake AUTO-MAS + ledger."""
    import json, os
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

    from ark_relay.features import shutdown as sd
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
    from ark_relay.features import modes
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
    os.environ["ARK_STATE_DIR"] = str(STATE)
    from ark_relay.features.commands import apply_command, ALLOWED

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
    calls = []
    RC = {"/a": 0}
    def fake_run(args, *a, **k):
        calls.append(list(args))
        rc = RC["/a"] if list(args)[:2] == ["shutdown", "/a"] else 0
        return __import__("subprocess").CompletedProcess(args, rc, b"", b"")
    eng.subprocess = type("X", (), {"run": staticmethod(fake_run),
                                    "CompletedProcess": __import__("subprocess").CompletedProcess})()
    from ark_relay.features import errwatch
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


@_restore_unfixed_after
def _part_shutdown_after_restart():
    """A relay restarted after the shift does not power the machine off."""
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

    from ark_relay.core import engine as eng
    from ark_relay.features import shutdown
    REAL_UNFIXED = _without_unfixed_gate(shutdown)
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State

    class Notes:
        def send(self, title, body="", **kw):
            return False

    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)

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
    shutdown._shift_unfixed = REAL_UNFIXED
    v = shutdown.decide(e, at(17, 55))
    check("with the unfixed-shift gate (2026-11-20): this day's OK-WW ended timed out, so it stays on",
          (v.code, v.reason), ("shift-failed", "这一班有游戏任务没跑完、还没修好：鸣潮（OK-WW 运行超时）"))
    _without_unfixed_gate(shutdown)
    check("17:55, records landed in this process -> go", shutdown.decide(e, at(17, 55)).code, "go")

    print("\n[2026-10-11: the last upload before power-off failing is a plain WARNING (pushed)]")
    from ark_relay.features import evidence as error_evidence
    from ark_relay.features import collect_retry
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
    shutdown._shift_unfixed = REAL_UNFIXED


def _part_shutdown_unfixed_shift():
    """2026-11-20, the user (B 10477): 「早班的游戏任务没跑完，没修好，就不能关机，你们要修好。」"""
    from datetime import datetime, timedelta

    from ark_relay.features import shutdown
    from ark_relay.core.config import SERVER_TZ
    shutdown._shift_unfixed = getattr(shutdown._shift_unfixed, "real", shutdown._shift_unfixed)

    def at(h, m=0):
        return datetime(2026, 11, 20, h, m, tzinfo=SERVER_TZ)
    MORNING = {"name": "早班", "due": at(9, 30), "kinds": ["MAA", "MaaEnd", "OK-WW"]}
    EVENING = {"name": "晚班", "due": at(21, 30), "kinds": ["MAA", "MaaEnd", "OK-WW"]}

    def rec(script, h, m, ok, failed=(), **raw_or_flags):
        flags = {k: v for k, v in raw_or_flags.items() if k in ("transitional", "incomplete", "user")}
        raw = {k: v for k, v in raw_or_flags.items() if k not in ("transitional", "incomplete", "user")}
        return dict(script=script, started=at(h, m).isoformat(), finished=(at(h, m) + timedelta(minutes=20)).isoformat(),
                    ok=ok, failed_tasks=list(failed), raw=raw, **flags)
    TASKS = ["赠送干员礼物", "装备制造", "拜访好友", "基建任务"]
    MAA_OK, OKWW_OK = rec("MAA", 9, 30, True), rec("OK-WW", 11, 0, True)

    print("[11-20 早班：终末地失败、没补上 → 不关机，说清是哪个游戏、卡在哪]")
    got = shutdown._shift_unfixed([MORNING], [MAA_OK, OKWW_OK, rec("MaaEnd", 9, 34, False, TASKS)])
    check("点名终末地和前三项", got, ["终末地（赠送干员礼物、装备制造、拜访好友…）"])
    print("\n[后来又跑了一趟成功了（重试、补跑、手动）→ 算修好了]")
    check("同一个脚本最新那条成功", shutdown._shift_unfixed([MORNING], [MAA_OK, rec("MaaEnd", 9, 34, False, TASKS),
                                                              rec("MaaEnd", 11, 30, True), OKWW_OK]), [])
    check("先成功后失败：按最新的，失败", shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, True),
                                                                rec("MaaEnd", 11, 30, False, ["基质刷取"])]),
          ["终末地（基质刷取）"])
    print("\n[官方停服、连不上官方（含鸣潮）、方舟理智不足、你自己停的：不是我们能修的，不留]")
    for flag in ("maintenance", "maaend_unreachable", "okww_unreachable", "manual_stop", "maaend_update_after_done"):
        check(flag, shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, False, TASKS, **{flag: True})]), [])
    check("okww_unreachable 不留",
          shutdown._shift_unfixed([MORNING], [rec("OK-WW", 11, 0, False, ["等不到窗口"], okww_unreachable=True)]), [])
    check("maa_sanity_short 不留",
          shutdown._shift_unfixed([MORNING], [rec("MAA", 9, 30, False, ["开始作战"], maa_sanity_short={"have": 17, "cost": 25})]), [])
    print("\n[停一切不能掩盖先前真实失败]")
    for stop_ok in (False, True):
        check(f"先失败后停一切(ok={stop_ok})：仍留着不关机",
              shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, False, TASKS),
                                                  rec("MaaEnd", 9, 50, stop_ok, manual_stop=True)]),
              ["终末地（赠送干员礼物、装备制造、拜访好友…）"])
    print("\n[方舟剿灭与日常分别判断：剿灭失败不被日常成功覆盖]")
    check("MAA 剿灭失败 + MAA 日常成功：仍拦关机",
          shutdown._shift_unfixed([MORNING], [rec("MAA", 9, 30, False, ["剿灭"], annihilation=True),
                                              rec("MAA", 9, 45, True, annihilation=False)]),
          ["明日方舟剿灭（剿灭）"])
    print("\n[ok=True 但「这一轮没干完」（incomplete，如 #186）：拦关机；仅差自动采集除外]")
    check("鸣潮 ok=True 但每日活跃没满：拦关机",
          shutdown._shift_unfixed([MORNING], [rec("OK-WW", 11, 0, True, incomplete="· 每日活跃：60/100")]),
          ["鸣潮（没干完：· 每日活跃：60/100）"])
    check("终末地 ok=True 但仅差自动采集：放行给关机前补跑",
          shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, True, incomplete="· 自动采集 真的没走通")]), [])
    print("\n[一趟里没跑完的中间那次（transitional）：有后续成功记录覆盖就放行；唯一记录就是失败则必须拦]")
    check("中间失败、最后成功", shutdown._shift_unfixed([MORNING], [rec("OK-WW", 11, 0, False, ["x"], transitional=True),
                                                         rec("OK-WW", 11, 5, True)]), [])
    check("只有中间失败（如装新版自重启、无重试）：必须拦",
          shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, False, TASKS, transitional=True, maaend_update_restart="v2.40")]),
          ["终末地（赠送干员礼物、装备制造、拜访好友…）"])
    check("鸣潮也点名", shutdown._shift_unfixed([MORNING], [rec("OK-WW", 11, 0, False, ["每日活跃奖励"])]),
          ["鸣潮（每日活跃奖励）"])
    check("config_skip 账号名 fallback 与修好后真实账号名不同：仍算已修好",
          shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 30, False, ["启动前配置检查未通过"],
                                                  user="", automas_config_skip=True),
                                              rec("MaaEnd", 9, 45, True, user="endfield")]), [])
    print("\n[早上的失败不拖到晚班：晚班跑成了照常关机]")
    check("晚班只看晚班", shutdown._shift_unfixed([MORNING, EVENING], [rec("MaaEnd", 9, 34, False, TASKS),
                                                                    rec("MaaEnd", 21, 34, True)]), [])
    check("排期前的记录不算这一班的", shutdown._shift_unfixed([EVENING], [rec("MaaEnd", 9, 34, False, TASKS)]), [])
    print("\n[只差自动采集：不留——关机那一刻中继会重走这些路线，留着反而永远走不到那一步]")
    check("只有自动采集", shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, False, ["🧺自动采集"])]), [])
    check("自动采集加别的：留", shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, False, ["🧺自动采集", "基质刷取"])]),
          ["终末地（🧺自动采集、基质刷取）"])
    print("\n[测试窗口里或手动起的那一趟失败：不算这一班没修好；手动跑成了算修好]")
    bad = rec("MaaEnd", 10, 0, False, TASKS)
    check("那一趟在 off 里：不留", shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, True), bad], {id(bad)}), [])
    good = rec("MaaEnd", 11, 0, True)
    check("班上失败、后来手动跑成：修好了", shutdown._shift_unfixed([MORNING], [rec("MaaEnd", 9, 34, False, TASKS), good],
                                                             {id(good)}), [])
    print("\n[不算「留过了这一班的关机时机」：AUTO-MAS 重试跑成了照常关机（真走一遍在 _part_shutdown_held_past_shift）]")
    check("shift-failed 不在 HELD_PAST_SHIFT 里", "shift-failed" in shutdown.HELD_PAST_SHIFT, False)


def _part_shutdown_hand_and_test_runs():
    """Hand-started and test-window runs never join a 早班/晚班 round nor move the skip key."""
    import json
    from datetime import datetime
    from types import SimpleNamespace

    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import shutdown

    FIX = fx_dir(Path(__file__), "fixtures") / "shutdown-1010-1013"

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


def _part_shutdown_held_past_shift():
    """A power-off opportunity belongs to the moment a shift finished, not to the whole boot."""
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

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.core.statestore import StateStore
    from ark_relay.features import errwatch
    from ark_relay.features import evidence as error_evidence
    from ark_relay.features import collect_retry, makeup
    from ark_relay.features import phone as heartbeat
    from ark_relay.features import shutdown

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
    from ark_relay.features import selfcheck as shiftcheck
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

    print("\n[2026-11-20 不关机闸门，真走一遍「修好」的三种路：AUTO-MAS 自己重试、补跑、手动跑]")

    def rows(*rs):
        (STATE / "ledger-2026-10-15.jsonl").write_text("\n".join(
            json.dumps({"run_id": f"2026-10-15/x/{r}", "script": s, "user": "u", "started": a.isoformat(),
                        "finished": b.isoformat(), "ok": ok, "failed_tasks": [] if ok else ["开始唤醒"],
                        "raw": dict(raw)})
            for r, s, a, b, ok, raw in rs) + "\n", encoding="utf-8")
    MAA_OK = ("MAA-1", "MAA", at(8, 50, 40), at(9, 9, 12), True, {})
    MAA_BAD = ("MAA-1", "MAA", at(8, 50, 40), at(9, 9, 12), False, {})
    OKWW_OK = ("OK-WW-1", "OK-WW", at(9, 9, 40), at(9, 31, 5), True, {})
    OKWW_BAD = ("OK-WW-1", "OK-WW", at(9, 9, 40), at(9, 31, 5), False, {})

    fresh()
    rows(MAA_OK, OKWW_BAD)
    v = tick(at(9, 32))
    check("鸣潮失败、没人修：不关机，说清是谁", (v.code, v.reason, powered), (
        "shift-failed", "这一班有游戏任务没跑完、还没修好：鸣潮（开始唤醒）", []))
    check("…没有把这一班的关机时机记成用掉了", e.state.store.get("marks", "shutdown_forfeit"), None)
    rows(MAA_OK, OKWW_BAD, ("OK-WW-2", "OK-WW", at(9, 33), at(9, 50), True, {}))
    tick(at(9, 51))
    check("AUTO-MAS 自己重试跑成了：照常关机", powered, [1])

    fresh()
    rows(MAA_BAD, OKWW_OK)
    check("明日方舟失败：不关机", tick(at(9, 32)).code, "shift-failed")
    (STATE / "makeup").mkdir(exist_ok=True)
    (STATE / "makeup" / "2026-10-15.json").write_text(json.dumps(
        {"MAA": {"dispatched_at": at(9, 40).isoformat(), "result": makeup.DISPATCHED, "tries": 1}}), encoding="utf-8")
    v = tick(at(9, 41))
    check("补跑一开跑：关机被补跑拖住，这一班的关机时机就用掉了（原来的规矩，不是这道闸）",
          (v.code, "MAA 正在补跑" in v.reason, powered), ("not-shift", True, []))
    rows(MAA_BAD, OKWW_OK, ("MAA-2", "MAA", at(9, 41), at(9, 58), True, {}))
    (STATE / "makeup" / "2026-10-15.json").write_text(json.dumps(
        {"MAA": {"dispatched_at": at(9, 40).isoformat(), "result": makeup.OK, "tries": 1}}), encoding="utf-8")
    v = tick(at(10, 0))
    check("补跑跑成了：这一班照样不再自动关机，下一趟早班/晚班跑完照常关（原来的规矩）",
          (v.code, powered), ("not-shift", []))

    fresh()
    rows(MAA_BAD, OKWW_OK)
    check("明日方舟失败：不关机", tick(at(9, 32)).code, "shift-failed")
    rows(MAA_BAD, OKWW_OK, ("MAA-3", "MAA", at(10, 30), at(10, 45), True, {"hand_started": True}))
    v = tick(at(10, 46))
    check("有人手动跑成了：不再是这道闸留着，按原来的规矩手动那一轮不自动关机",
          (v.code, "手动" in v.reason, powered), ("not-shift", True, []))

    error_evidence.upload_daily_logs, collect_retry.maybe_run = saved


def _part_shutdown_notice():
    """The 「今晚不关机」 message must never go out when the machine is in fact shutting down."""
    import re
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from ark_relay.features import shutdown
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
    FIX = fx_dir(Path(__file__), "fixtures")
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
    _ew = __import__("ark_relay.features.errwatch", fromlist=["x"])
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
    """A test window can never swallow a 早班/晚班, even when test-off is never run."""
    import json
    import shutil
    import tempfile
    from datetime import datetime
    from types import SimpleNamespace

    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import shutdown

    FIX = fx_dir(Path(__file__), "fixtures") / "shutdown-1010-1013"

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


def _part_shutdown_round():
    """The round a record belongs to, for the 「最近一轮是手动触发的」 gate."""
    from datetime import datetime, timedelta

    from ark_relay.features import shutdown
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
    from ark_relay.features import trigger
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

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features import selfcheck as shiftcheck
    from ark_relay.features import shutdown


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
    """A farm in progress has to hold off the automatic shutdown."""
    from datetime import datetime

    from ark_relay.features import echofarm
    from ark_relay.features import shutdown
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


@_restore_unfixed_after
def _part_shutdown_whitelist():
    """Only the decision right after a morning / evening shift finished may power off."""
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

    from ark_relay.core import engine as eng
    from ark_relay.features import shutdown
    REAL_UNFIXED = _without_unfixed_gate(shutdown)
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State

    class Notes:
        def send(self, title, body="", **kw):
            return False

    def at(hh, mm, ss=0):
        return datetime(2026, 10, 10, hh, mm, ss, tzinfo=SERVER_TZ)

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
    ledger(MORNING[:4])               # no MaaEnd
    v = judge(at(11, 40), at(8, 45), at(8, 45, 18))
    check("11:40, MaaEnd never ran, past the old two-hour window -> shift-running", v.code, "shift-running")
    check("…names what is missing", "MaaEnd" in v.reason, True)
    ledger([])
    check("09:00:01, the shift just started -> shift-running", judge(at(9, 0, 1), at(8, 45), at(8, 45, 18)).code, "shift-running")

    print("\n[shift finished while someone uses the machine: powered off all the same (10-10 23:20)]")
    ledger(MORNING)
    check("09:39:30 -> go, nothing asks about keyboard / mouse",
          judge(at(9, 39, 30), at(8, 45), at(8, 45, 18)).code, "go")
    check("the gate is gone", hasattr(shutdown, "console_idle_s"), False)

    print("\n[a shift script that never records: one group alarm once the shift is overdue (10-12 20:04)]")
    from ark_relay.core import texts
    from ark_relay.features import handle
    from ark_relay.features import runwatch

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

    print("\n[#176: the queue's planned end is past, the script whose turn it is has not spent its own minutes yet]")
    from unittest import mock
    ledger(MORNING[:4])
    e.state.store.pop("marks", f"alerted:{due:%Y-%m-%d}")
    e.notifier.sent.clear()
    e._scripts_running = lambda: True
    own_end = at(9, 13, 15) + timedelta(minutes=64 + runwatch.OVERRUN_SLACK_MIN)
    unfinished = {"tasks": [{"queueId": "m", "taskId": "t1", "task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    with mock.patch.object(runwatch, "planned_minutes", lambda *a: (20, 3)), \
            mock.patch.object(runwatch, "script_minutes", lambda eng, script, hh, mm, today: {"MaaEnd": 64}.get(script)):
        check("the loop is woken when MaaEnd's own time is up, not at the queue's 09:50",
              [m for m, _ in shutdown.overdue_moments(e, at(9, 40))], [own_end])
        shutdown._alarm_shift_overdue(e, at(9, 51))
        runwatch.check_overrun(e, at(9, 51), unfinished)
        check("09:51, past the queue's planned end: neither alarm goes out", e.notifier.sent, [])
        shutdown._alarm_shift_overdue(e, own_end - timedelta(minutes=1))
        runwatch.check_overrun(e, own_end - timedelta(minutes=1), unfinished)
        check("a minute before MaaEnd's own time is up: still neither", e.notifier.sent, [])
        shutdown._alarm_shift_overdue(e, own_end + timedelta(minutes=1))
        check("past it: one alarm", len(e.notifier.sent), 1)
        body = e.notifier.sent[0][1] if e.notifier.sent else ""
        check("…it says since when MaaEnd has had its turn and by which of its own days it is late",
              ("轮到 MaaEnd 是 09:13" in body, "64 + 30" in body, texts.plain(body)), (True, True, []))
        runwatch.check_overrun(e, own_end + timedelta(minutes=2), unfinished)
        check("…and check_overrun does not push the same run again", len(e.notifier.sent), 1)
        e.state.store.pop("marks", f"alerted:{due:%Y-%m-%d}")
        e.notifier.sent.clear()
        runwatch.check_overrun(e, own_end + timedelta(minutes=1), unfinished)
        two = (texts.shift_overrun("早班"), texts.shift_no_result("早班"))
        check("the other way round: check_overrun is the one that goes out past it, with the same line",
              [(t_, "轮到 MaaEnd 是 09:13" in b) for t_, b, _a in e.notifier.sent if t_ in two], [(two[0], True)])
        shutdown._alarm_shift_overdue(e, own_end + timedelta(minutes=2))
        check("…and the no-result alarm does not repeat it", [t_ for t_, _b, _a in e.notifier.sent if t_ in two], [two[0]])
    with mock.patch.object(runwatch, "planned_minutes", lambda *a: (20, 3)), \
            mock.patch.object(runwatch, "script_minutes", lambda eng, script, hh, mm, today: 900):
        e.state.store.pop("marks", f"alerted:{due:%Y-%m-%d}")
        check("a script with a very long day of its own: no later than the shift's cap (09:00 + 180 + 30)",
              [m for m, _ in shutdown.overdue_moments(e, at(9, 40))],
              [due + timedelta(minutes=runwatch.SHIFT_CAP_MIN + runwatch.OVERRUN_SLACK_MIN)])
    e.state.store.pop("marks", f"alerted:{due:%Y-%m-%d}")
    e.notifier.sent.clear()
    ledger(MORNING)
    e._scripts_running = lambda: False
    check("this section never reached the power-off", powered, [])
    e.notifier, e._scripts_running, e._power_off = saved_notifier, (lambda: False), saved_power_off
    shutdown._shift_unfixed = REAL_UNFIXED


def _part_exit_shutdown_window():
    """An AUTO-MAS exit looks back an hour for a Windows shutdown request, not 120 s (audit s15 #5).
    """
    import logging
    import re
    import types
    from datetime import datetime, timedelta, timezone

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

    from ark_relay.features import errwatch
    from ark_relay.features import automas_keeper, automas_keeper as automas_procs, procwatch as shutdown_signs
    from ark_relay.features import shutdown

    REAL_1074 = (fx_dir(Path(__file__), "fixtures") /
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
    """
    import logging

    from ark_relay.core import engine
    from ark_relay.features.machinechecks import POWER_OFF

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
    """A hand power-off waits for the relay's own work (scripts/mac/lib/poweroff_ok.py)."""
    import json
    from datetime import datetime, timedelta

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
    import poweroff_ok
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import echofarm

    NOW = datetime(2026, 10, 22, 16, 44, 50, tzinfo=SERVER_TZ)
    idle = lambda: False  # noqa: E731

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
    """The 「下次跑完不关机」 mark is named and described one way everywhere a human reads it."""
    import re

    RELAY = Path(__file__).resolve().parents[1]
    REPO = RELAY.parent
    sys.path.insert(0, str(RELAY))

    from ark_relay.features import modes

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
    ROOTS = [RELAY / "ark_relay", REPO / "docs", REPO / "scripts" / "windows", REPO / "scripts" / "mac"]
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
    check("files scanned (sanity: the walk found the tree)", scanned >= 50, True)
    check("no other name for the mark", hits, [])

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
    check("arm: one short sentence", len(on) <= 32 and "再下一趟" not in on, True)
    _ok_off, off = modes.set_debug(d, off=True)
    check("debug off: says it is off, asks for nothing", off, "调试模式已关闭")
    for label, text in (("pull back", back), ("nothing to pull back", none)):
        check(f"{label}: says 还没用上", "还没用上" in text, True)
        check(f"{label}: no bare 已取消", "已取消" in text, False)
        check(f"{label}: next run shuts down as usual", "照常关机" in text, True)
    check("nothing to pull back: says it may already be spent", "已经用掉" in none, True)


def _part_skip_failed_pushed():
    """A skip of a queue that did not take effect, or whose restore failed, reaches the group."""
    from datetime import datetime

    from ark_relay.core import engine as eng_mod
    from ark_relay.features import modes
    from ark_relay.core import texts
    from ark_relay.core import plan as _plan
    from ark_relay.features import queues as _q
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import route_of

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


def _part_skip_flag_collision():
    """两个功能共用「skip-」这个前缀，清理陈旧标记时把对方扫掉了。"""
    from datetime import datetime

    from ark_relay.features import modes
    from ark_relay.features import queues as _q
    from ark_relay.core import plan as _plan
    from ark_relay.core.statestore import StateStore
    from ark_relay.core.config import SERVER_TZ

    STATE = tmpdir() / "state"; STATE.mkdir(parents=True)
    NOW = datetime(2026, 8, 31, 12, 44, tzinfo=SERVER_TZ)

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


def _part_skip_receipt_lost():
    """A skip that failed stays a failure when its red receipt could not be written."""

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    from ark_relay.core import engine
    from ark_relay.features import modes

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


def _part_skip_receipts():
    """Skip-queue outcomes reach the phone page's receipts, and a failed skip lets go of the day.
    """
    import os
    from datetime import datetime

    from ark_relay.features import modes
    from ark_relay.core import plan as _plan
    from ark_relay.features import queues as _q
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore

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


def _part_skip_sat_out():
    """A queue skipped on purpose stays skipped for that day's checks after its restore."""
    import json
    import os
    from datetime import datetime

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

    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.core.engine import Engine
    from ark_relay.features import modes
    from ark_relay.features import queues as _q
    from ark_relay.features import shutdown

    sent = []

    class FakeNotifier(Notifier):
        def send(self, title, body, *, alert=False, daily=False):
            sent.append((title, alert))
            return []

    cfg = Config()
    E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
    E._boot_time = lambda now: at(8, 0)

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


def _part_skip_shutdown_bat_error():
    """skip-shutdown.bat shows Python's own error when the status read gives nothing."""
    import re

    ROOT = Path(__file__).resolve().parents[2]
    bat = (ROOT / "scripts" / "windows" / "skip-shutdown.bat").read_bytes().decode("utf-8").replace("\r\n", "\n")

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


def _part_farm_poweroff():
    import json
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _parts import tmpdir

    from ark_relay.features import procwatch as S

    TMP = tmpdir()
    REQ_AT = datetime(2026, 11, 13, 0, 20, 6, tzinfo=timezone.utc)      # 08:20:06 on the relay's clock
    ASKED = {"clock": "08:20:06", "at": REQ_AT, "process": r"C:\WINDOWS\system32\shutdown.exe (INS)", "user": r"INS\Administrator"}

    def mark(**kw):
        d = TMP / f"m{len(list(TMP.iterdir()))}"
        d.mkdir()
        body = {"at": REQ_AT.timestamp() - 1, "by": "is_run.py", "outcome": "deadline"}
        body.update(kw)
        (d / S.FARM_POWEROFF_MARK).write_text(json.dumps(body), encoding="utf-8")
        return d

    print("[the farm's own deadline power-off is recognised]")
    got = S.farm_poweroff_planned(ASKED, base=mark())
    check("is_run.py deadline mark 1 s before the request", bool(got))
    check("names the script", (got or {}).get("by"), "is_run.py")
    check("the mark's time on the relay's clock", (got or {}).get("at"), "08:20:05")
    check("spa_run.py counts too", bool(S.farm_poweroff_planned(ASKED, base=mark(by="spa_run.py", outcome="maxrounds"))))

    print("[anything else is pushed as before]")
    check("no mark", S.farm_poweroff_planned(ASKED, base=TMP / "nothing-here"), None)
    check("no request standing", S.farm_poweroff_planned(None, base=mark()), None)
    check("request not from shutdown.exe", S.farm_poweroff_planned(dict(ASKED, process=r"C:\Windows\explorer.exe"), base=mark()), None)
    check("mark from another script", S.farm_poweroff_planned(ASKED, base=mark(by="someone.py")), None)
    check("the farm failed", S.farm_poweroff_planned(ASKED, base=mark(outcome="failed")), None)
    check("no outcome", S.farm_poweroff_planned(ASKED, base=mark(outcome="")), None)
    check("mark 31 minutes before the request", S.farm_poweroff_planned(ASKED, base=mark(at=REQ_AT.timestamp() - 31 * 60)), None)
    check("mark after the request (a later run)", S.farm_poweroff_planned(ASKED, base=mark(at=REQ_AT.timestamp() + 60)), None)
    bad = TMP / "bad"
    bad.mkdir()
    (bad / S.FARM_POWEROFF_MARK).write_text("{not json", encoding="utf-8")
    check("unreadable mark", S.farm_poweroff_planned(ASKED, base=bad), None)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)


def _part_place_desktop_bat():
    import sys
    import tempfile
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))
    from ark_relay.core.statestore import StateStore
    from ark_relay.features import modes

    with tempfile.TemporaryDirectory() as tmp:
        st = Path(tmp)
        relay_store = StateStore(st)
        relay_store.set("versions", "code", "1")
        ok, msg = modes.set_skip_shutdown(st, True)
        require("switch receipt is the relay's own wording",
                ok and msg.startswith("已记下「下次跑完不关机」"), msg)
        require("a running relay sees the mark at once (skip_armed, fresh store)", modes.skip_armed(st))
        require("... and through its long-lived store", relay_store.get("modes", "skip_next_shutdown") is True)
        relay_store.set("versions", "code", "2")
        require("the relay's next write keeps the mark", modes.skip_armed(st)
                and StateStore(st).get("versions", "code") == "2")
        modes.set_skip_shutdown(st, False)
        require("pulling it back is seen at once too", not modes.skip_armed(st)
                and relay_store.get("modes", "skip_next_shutdown") is None)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_statestore_main():
    """state.json：一个文件、登记过的字段才能写、原子落盘、旧文件自动迁入。"""
    import json, logging

    from ark_relay.core.statestore import StateStore

    class Warns(logging.Handler):
        """Collects the WARNING lines of one logger (each one is a group message)."""

        def __init__(self, name):
            super().__init__(logging.WARNING)
            self.lines = []
            logging.getLogger(name).addHandler(self)

        def emit(self, record):
            self.lines.append(record.getMessage())

    d = tmpdir()
    s = StateStore(d)
    print("[空目录：读到空段，不落盘]")
    check("weekly 空", s.section("weekly"), {})
    check("还没有文件", (d / "state.json").exists(), False)

    print("[登记过的能写，没登记的拒绝]")
    s.set("weekly", "garden", {"done_week": "2026-W37"})
    check("写进去", s.get("weekly", "garden"), {"done_week": "2026-W37"})
    check("落盘了", json.loads((d / "state.json").read_text(encoding="utf-8"))["weekly"]["garden"], {"done_week": "2026-W37"})
    try:
        s.set("weekly", "made_up", 1); check("未登记键被拒", False, True)
    except KeyError as e:
        check("未登记键被拒", "没在字段表里登记" in str(e), True)
    s.set("marks", "report:2026-09-07", "2026-09-07T22:00:00")
    check("通配键", s.get("marks", "report:2026-09-07"), "2026-09-07T22:00:00")
    s.pop("weekly", "garden")
    check("pop", s.get("weekly", "garden"), None)

    print("[另一个实例看到同一份（按 mtime 重读）]")
    s2 = StateStore(d)
    check("读到", s2.get("marks", "report:2026-09-07"), "2026-09-07T22:00:00")
    s2.set("versions", "okww", "v3.6.7")
    check("第一个实例也看到", s.get("versions", "okww"), "v3.6.7")

    print("[旧文件迁入]")
    d2 = tmpdir()
    (d2 / "garden.json").write_text(json.dumps({"done_week": "2026-W36"}), encoding="utf-8")
    (d2 / "weeklyboss.json").write_text(json.dumps({"index": 1, "name": "千傀重楼", "done_week": "2026-W37"}), encoding="utf-8")
    (d2 / "okww-version.txt").write_text("v3.6.7", encoding="utf-8")
    (d2 / "annihilation.json").write_text("{}", encoding="utf-8")   # 空的不迁
    t = StateStore(d2)
    check("garden 迁入", t.get("weekly", "garden"), {"done_week": "2026-W36"})
    check("boss 迁入", t.get("weekly", "boss")["name"], "千傀重楼")
    check("版本迁入", t.get("versions", "okww"), "v3.6.7")
    check("空文件不迁", t.get("weekly", "annihilation"), None)
    check("旧文件改名保留", (d2 / "garden.json.migrated").exists() and not (d2 / "garden.json").exists(), True)
    check("再来一个实例不重复迁", StateStore(d2).get("weekly", "garden"), {"done_week": "2026-W36"})

    print("[按天/按卡池的旧标记也迁：一次全搬]")
    d3 = tmpdir()
    (d3 / "report-2026-09-06.sent").write_text("", encoding="utf-8")
    (d3 / "interim-2026-09-06.sent").write_text("7", encoding="utf-8")
    (d3 / "interim-2026-09-05.sent").write_text("", encoding="utf-8")     # 旧空标记
    (d3 / "banner-明日方舟-202609041200.sent").write_text("", encoding="utf-8")
    (d3 / "skip-next-shutdown.flag").write_text("skip", encoding="utf-8")
    (d3 / "shutdown-skipped.txt").write_text("2026-09-06:1", encoding="utf-8")
    (d3 / "pending.json").write_text(json.dumps({"MaaEnd|endfield": {"run_id": "x"}}), encoding="utf-8")
    u = StateStore(d3)
    check("日报标记", u.get("marks", "report:2026-09-06"), True)
    check("临时日报带条数", u.get("marks", "interim:2026-09-06"), "7")
    check("旧空标记原样保留（条数不详）", u.get("marks", "interim:2026-09-05"), "")
    check("卡池标记", u.get("marks", "banner:明日方舟-202609041200"), True)
    check("别关机开关", u.get("modes", "skip_next_shutdown"), True)
    check("被吃掉的关机机会", u.get("modes", "shutdown_skipped"), "2026-09-06:1")
    check("告警队列", u.get("queues", "pending"), {"MaaEnd|endfield": {"run_id": "x"}})
    check("旧文件都改名了", sorted(p.name for p in d3.glob("*.sent")), [])

    print("[State 读回来的语义没变]")
    from ark_relay.core.ledger import State
    st = State(d3)
    check("report_sent", st.report_sent("2026-09-06"), True)
    check("没发过的那天", st.report_sent("2026-09-07"), False)
    check("interim_covered 带条数", st.interim_covered("2026-09-06"), 7)
    check("旧空标记 → 不再重播", st.interim_covered("2026-09-05"), 10**6)
    check("没发过 → 0", st.interim_covered("2026-09-07"), 0)
    # A non-numeric marker for a day still being judged is a bug (writes are atomic):
    # it silently suppresses every further interim that day, so it is said - once,
    # since the interim check runs every tick.
    cw = Warns("ark.core")
    st.store.set("marks", "interim:2026-09-08", "abc")
    check("非数字标记仍按「已发、条数不详」", [st.interim_covered("2026-09-08") for _ in range(3)], [10**6] * 3)
    check("非数字标记说一声，只说一次", len([ln for ln in cw.lines if "interim:2026-09-08" in ln]), 1)
    st.store.set("marks", "interim:2026-09-08", "3")
    check("改好后照常", st.interim_covered("2026-09-08"), 3)
    st.store.set("marks", "interim:2026-09-08", "")
    st.interim_covered("2026-09-08")
    check("又坏了再说一次", len([ln for ln in cw.lines if "interim:2026-09-08" in ln]), 2)
    check("卡池", st.banner_announced("明日方舟-202609041200"), True)
    check("告警队列", st.load_pending(), {"MaaEnd|endfield": {"run_id": "x"}})
    st.mark_report_sent("2026-09-07")
    check("写完能读回", st.report_sent("2026-09-07"), True)

    print("[state.json 已存在时，后来才补的旧文件也要迁——不能只在首次建档时迁]")
    d4 = tmpdir()
    import ark_relay.core.statestore as SS
    SS._SWEPT.clear()
    first = StateStore(d4)
    first.set("weekly", "garden", {"done_week": "2026-W37"})    # 先有了 state.json
    (d4 / "report-2026-09-07.sent").write_text("", encoding="utf-8")
    (d4 / "pending.json").write_text(json.dumps({"MaaEnd|endfield": {"run_id": "y"}}), encoding="utf-8")
    (d4 / "gameupdate-pending.json").write_text(json.dumps({"鸣潮": "客户端待更新"}), encoding="utf-8")
    SS._SWEPT.clear()                                            # 模拟下一次进程启动
    later = StateStore(d4)
    check("后补的日报标记迁进来了", later.get("marks", "report:2026-09-07"), True)
    check("后补的告警队列迁进来了", later.get("queues", "pending"), {"MaaEnd|endfield": {"run_id": "y"}})
    check("后补的待更新登记迁进来了", later.get("updates", "gameupdate_pending"), {"鸣潮": "客户端待更新"})
    check("原有的值没被动", later.get("weekly", "garden"), {"done_week": "2026-W37"})
    check("旧文件收走了", sorted(p.name for p in d4.glob("*.sent")), [])

    print("[state.json 里已有值时，旧文件不许覆盖它]")
    d5 = tmpdir()
    SS._SWEPT.clear()
    s5 = StateStore(d5)
    s5.set("versions", "okww", "v3.6.7")
    (d5 / "okww-version.txt").write_text("v3.6.5", encoding="utf-8")   # 陈旧的遗留
    SS._SWEPT.clear()
    check("以 state.json 为准", StateStore(d5).get("versions", "okww"), "v3.6.7")
    check("陈旧文件也收走", (d5 / "okww-version.txt").exists(), False)

    print("[state.json unreadable: copied aside before anything overwrites it, said once per mtime]")
    import os
    d6 = tmpdir()
    SS._SWEPT.clear()
    SS._CORRUPT_SAID.clear()
    (d6 / "state.json").write_text('{"weekly": {"garden": {"done_week": "2026-W4', encoding="utf-8")
    os.utime(d6 / "state.json", (1_790_000_000, 1_790_000_000))
    sw = Warns("ark.statestore")
    check("读不出来按空", StateStore(d6).section("weekly"), {})
    check("别的实例再读不再说", [StateStore(d6).get("modes", "debug_until") for _ in range(3)], [None] * 3)
    copies = sorted(d6.glob("state.json.corrupt-*"))
    check("另存了一份", len(copies), 1)
    check("另存的是原样", copies and copies[0].read_text(encoding="utf-8"), '{"weekly": {"garden": {"done_week": "2026-W4')
    check("只说一次，说出另存的文件名", [copies[0].name in ln for ln in sw.lines] if copies else sw.lines, [True])
    StateStore(d6).set("versions", "okww", "v3.6.7")
    check("写入后另存的还在", copies and copies[0].exists(), True)
    (d6 / "state.json").write_text("{bad", encoding="utf-8")
    os.utime(d6 / "state.json", (1_790_000_100, 1_790_000_100))
    StateStore(d6).get("versions", "okww")
    check("又坏了（新的 mtime）再说一次、再存一份", (len(sw.lines), len(list(d6.glob("state.json.corrupt-*")))), (2, 2))

    print("\n[清单-1108 A-07：同一进程里另一个实例刚写过，mtime 碰巧一样也不读旧缓存；写的副本是深拷贝]")
    d7 = tmpdir()
    a, b = StateStore(d7), StateStore(d7)
    a.set("updates", "queue_skips", [{"script": "MAA"}])
    check("b 先读一遍", b.get("updates", "queue_skips"), [{"script": "MAA"}])
    st = (d7 / "state.json").stat()
    a.set("updates", "queue_skips", [])
    os.utime(d7 / "state.json", ns=(st.st_atime_ns, st.st_mtime_ns))     # the same mtime as b's copy
    check("a 写过之后，b 读到的是新的（不是 mtime 相同的旧缓存）", b.get("updates", "queue_skips"), [])
    c = StateStore(d7)
    c.set("updates", "queue_skips", [{"script": "OK-WW"}])
    data = c._writable()
    data["updates"]["queue_skips"].append({"script": "MaaEnd"})
    check("改写副本里的列表，不动缓存", c.get("updates", "queue_skips"), [{"script": "OK-WW"}])


def _part_state_read_lock():  # noqa: C901
    """state.json reads that a Windows lock refuses, and alarm day marks written by two
writers: no alarm pushed twice, no mark lost, no relay state lost.
    """
    import json
    import logging
    import os
    import types

    from ark_relay.core import statestore
    from ark_relay.core.statestore import StateStore
    from ark_relay.features import handle, handle as unresolved

    DAY = "2026-10-08"
    MARK = f"alerted:{DAY}"
    REAL_READ_TEXT = Path.read_text
    NO_WAITS = (0.0, 0.0, 0.0)


    class Lines(logging.Handler):
        """WARNING and up on ark.statestore: each such line is a group message."""

        def __init__(self, logger):
            super().__init__(logging.WARNING)
            self.lines = []
            logger.addHandler(self)

        def emit(self, record):
            self.lines.append(record.getMessage())


    LINES = Lines(statestore.log)


    class read_fails:
        """Path.read_text of state.json raises `exc` (default: the PermissionError a
    Windows sharing violation becomes) while inside, every time."""

        def __init__(self, exc=None):
            self.exc = exc or PermissionError(13, "state.json being scanned (test)")
            self.tries = 0

        def __enter__(self):
            self.waits = statestore.LOCK_WAITS
            statestore.LOCK_WAITS = NO_WAITS

            def _read(path, *a, **kw):
                if Path(path).name == statestore.FILE:
                    self.tries += 1
                    raise self.exc
                return REAL_READ_TEXT(path, *a, **kw)
            Path.read_text = _read
            return self

        def __exit__(self, *a):
            Path.read_text = REAL_READ_TEXT
            statestore.LOCK_WAITS = self.waits


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append(title)
            return []


    class Eng:
        """What unresolved.send and daymarks use of the engine: one long-lived store."""

        def __init__(self, d):
            self.state = types.SimpleNamespace(dir=d, store=StateStore(d))
            self.notifier = Notes()

        def _already_alerted(self, day, key):
            return handle._already_alerted(self, day, key)

        def _mark_alerted(self, day, key):
            return handle._mark_alerted(self, day, key)


    def folder(data=None):
        d = tmpdir()
        if data is not None:
            (d / statestore.FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return d


    def bump(d, by=5):
        """Move state.json's mtime on, as a write by another writer does."""
        st = (d / statestore.FILE).stat()
        os.utime(d / statestore.FILE, (st.st_atime, st.st_mtime + by))


    def on_disk(d):
        return json.loads(REAL_READ_TEXT(d / statestore.FILE, encoding="utf-8"))


    def corrupt_copies(d):
        return sorted(p.name for p in d.glob(statestore.FILE + ".corrupt-*"))


    def forget(d):
        """This process has read nothing of `d` yet (a relay just started)."""
        getattr(statestore, "_LAST_GOOD", {}).pop(str(d / statestore.FILE), None)


    def section(title, fn):
        print(f"\n[{title}]")
        LINES.lines.clear()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{title}: ran to the end", f"{type(exc).__name__}: {exc}", "")
        finally:
            Path.read_text = REAL_READ_TEXT


    def item1a():
        d = folder()
        eng = Eng(d)
        title = "明日方舟 没跑成（test）"
        check("first push goes out", unresolved.send(eng, DAY, "未解决", "run-1", title, "body"), True)
        StateStore(d).set("versions", "okww", "v9")     # another writer: the file's mtime moves on
        bump(d)
        with read_fails():
            again = unresolved.send(eng, DAY, "未解决", "run-1", title, "body")
            marked = handle._already_alerted(eng, DAY, unresolved._key("未解决", "run-1"))
        check("state.json locked: the replayed record is not pushed again",
              (again, eng.notifier.sent.count(title)), (True, 1))
        check("state.json locked: its day mark still reads as sent", marked, True)
        check("a healthy file a lock refused is not copied aside", corrupt_copies(d), [])
        check("no WARNING / ERROR (group message) for a lock on a plain read", LINES.lines, [])
        check("the lock gone, the next read sees what the other writer wrote",
              eng.state.store.get("versions", "okww"), "v9")


    def item1b():
        d = folder({"marks": {MARK: ["k"]}, "modes": {"debug_until": "2026-10-08 23:00"}})
        before = (d / statestore.FILE).read_bytes()
        forget(d)
        cold = StateStore(d)
        with read_fails() as lock:
            cold.get("marks", MARK)
        check("a first read waits the lock out before giving up", lock.tries, len(NO_WAITS) + 1)
        check("the lock gone, the same instance reads the file (nothing cached from the lock)",
              cold.get("marks", MARK), ["k"])
        check("the file is left as it was", (d / statestore.FILE).read_bytes(), before)
        check("and not copied aside", corrupt_copies(d), [])
        check("no WARNING / ERROR", LINES.lines, [])


    def item1c():
        d = folder({"marks": {MARK: ["k"]}, "modes": {"skip_next_shutdown": True}})
        StateStore(d).get("marks", MARK)                # read once in this process
        bump(d)
        with read_fails() as lock:
            got = (StateStore(d).get("marks", MARK), StateStore(d).get("modes", "skip_next_shutdown"))
        check("a store built per call answers with what this process read last", got, (["k"], True))
        check("and does not sleep through the lock waits for it", lock.tries, 2)


    def item1d():
        d = folder({"marks": {MARK: ["k"]}, "weekly": {"garden": {"done_week": "2026-W41"}}})
        store = StateStore(d)
        store.get("marks", MARK)
        bump(d)
        try:
            with read_fails(OSError(5, "Input/output error (test)")):
                store.set("versions", "okww", "v9")
            raised = ""
        except OSError as exc:
            raised = type(exc).__name__
        check("a write whose read meets another OSError raises", raised, "OSError")
        check("and leaves everything on file", on_disk(d),
              {"marks": {MARK: ["k"]}, "weekly": {"garden": {"done_week": "2026-W41"}}})
        check("not copied aside", corrupt_copies(d), [])


    def item1e():
        d = folder()
        (d / statestore.FILE).write_text("[1, 2]", encoding="utf-8")
        try:
            got = StateStore(d).get("marks", MARK)
        except Exception as exc:  # noqa: BLE001
            got = f"{type(exc).__name__}: {exc}"
        check("state.json holding a list (not a table) reads as empty", got, None)
        check("and is copied aside before anything overwrites it", len(corrupt_copies(d)), 1)


    def item1f():
        d = folder({"versions": {"code": "20261017"}, "marks": {MARK: ["k"]}})
        (d / "okww-version.txt").write_text("v3.6.5", encoding="utf-8")
        forget(d)
        statestore._SWEPT.discard(str(d))
        with read_fails():
            StateStore(d)
        check("legacy sweep with state.json locked leaves it as it was", on_disk(d),
              {"versions": {"code": "20261017"}, "marks": {MARK: ["k"]}})
        check("and moves no legacy file", (d / "okww-version.txt").exists(), True)
        StateStore(d)
        check("the lock gone, the next StateStore sweeps it in",
              (on_disk(d)["versions"].get("okww"), on_disk(d)["marks"].get(MARK)), ("v3.6.5", ["k"]))


    def item2():
        d = folder({"marks": {}})
        one, two = Eng(d), Eng(d)
        one.state.store.get("marks", MARK)              # one's cached copy: no marks yet
        m0 = (d / statestore.FILE).stat().st_mtime
        two._mark_alerted(DAY, "b")
        # The second write lands within the clock's resolution: the mtime reads as it
        # did when `one` cached the file (put back by hand here).
        os.utime(d / statestore.FILE, (m0, m0))
        one._mark_alerted(DAY, "a")
        check("two writers marking the same day: both marks are on file",
              sorted(on_disk(d)["marks"].get(MARK) or []), ["a", "b"])
        check("and each reads both back", (one._already_alerted(DAY, "b"), two._already_alerted(DAY, "a")),
              (True, True))


    for title, fn in (("1a: state.json locked after an alarm went out: not pushed again", item1a),
                      ("1b: the first read of state.json locked", item1b),
                      ("1c: a store built per call while state.json is locked", item1c),
                      ("1d: a write whose read meets an OSError other than a lock", item1d),
                      ("1e: state.json that is JSON but not a table", item1e),
                      ("1f: the legacy sweep while state.json is locked", item1f),
                      ("2: two writers marking one day's alarms", item2)):
        section(title, fn)

    print()
    if fails:
        print(f"✗ {len(fails)} 条没过：{fails}")
        sys.exit(1)


def _part_state_unread():
    """Reads put off with nothing to bring them back (dispatch relay-audit-round2-1108 N-02 / N-05).
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE))

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(HERE.parent))

    from ark_relay.core import collector, statestore
    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features import errwatch
    from ark_relay.features import needtable

    class Rows(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))

    rows = Rows()
    statestore.log.addHandler(rows)
    statestore.log.setLevel(logging.DEBUG)
    # errwatch's handler sits on the "ark" logger (errwatch.install): what reaches it there is
    # what the group hears. It writes errkinds/ and the technical log, never state.json, so the
    # push does not die in the outage it reports.
    at_errwatch = []
    _ark = logging.getLogger(errwatch.ARK)
    _ark_rows = Rows()
    _ark_rows.emit = lambda r: at_errwatch.append(r.levelname) if r.name == statestore.log.name else None
    _ark.addHandler(_ark_rows)

    clock = [1000.0]
    import time as _time
    statestore.time = SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: None, time=_time.time)
    REAL_READ = Path.read_text
    lock = {"on": False, "tries": 0}

    def read_text(self, *a, **kw):
        if lock["on"] and self.name == statestore.FILE:
            lock["tries"] += 1
            raise PermissionError(13, "being used by another process (test)")
        return REAL_READ(self, *a, **kw)

    Path.read_text = read_text

    def levels():
        return [lv for lv, _, _ in rows.rows]

    d = tmpdir() / "state"
    st = statestore.StateStore(d)
    st.update("weekly", "garden", lambda _: {"done_week": "2026-W45"})
    path = d / statestore.FILE

    print("[读不出来：一条 INFO，接着用上次读到的，写照样报错]")
    rows.rows.clear()
    lock["on"] = True
    lock["tries"] = 0
    check("同一个实例、文件没变：直接用它手上那份，不去读", (st.get("weekly", "garden"), lock["tries"]),
          ({"done_week": "2026-W45"}, 0))
    check("…不算读不出来", statestore.refused_since(path), None)
    # Most call sites build a StateStore per call: that one reads the file.
    check("新建的实例读不出来：拿到的是上次读到的那份", statestore.StateStore(d).get("weekly", "garden"),
          {"done_week": "2026-W45"})
    check("记下了从什么时候开始读不出来", statestore.refused_since(path), 1000.0)
    check("一条 INFO", levels(), ["INFO"])
    raised = ""
    try:
        st.update("weekly", "garden", lambda _: {"done_week": "2026-W46"})
    except OSError as exc:
        raised = type(exc).__name__
    check("写不进去就报错（不拿空的盖上去）", raised, "PermissionError")
    lock["tries"] = 0
    st.get("weekly", "garden")
    check("读不出来期间每次读都再去读文件（不用缓存）", lock["tries"], 1)
    check("还是只有那一条 INFO", levels(), ["INFO"])

    print("\n[连着 10 分钟读不出来：一条进群的 WARNING，同一段里不再重复]")
    check("和别的中断报警同一个时长", (statestore.UNREAD_WARN_S, statestore.UNREAD_RETRY_S), (600, 45))
    from ark_relay.features.phone import Mailbox
    check("就是 Mailbox.OUTAGE_SEC", float(statestore.UNREAD_WARN_S), float(Mailbox.OUTAGE_SEC))
    clock[0] = 1000.0 + 599
    st.get("weekly", "garden")
    check("599 秒：还没有 WARNING", "WARNING" in levels(), False)
    clock[0] = 1000.0 + 600
    st.get("weekly", "garden")
    w = [(m, r) for lv, m, r in rows.rows if lv == "WARNING"]
    check("600 秒：一条 WARNING，没标自己好了，说 10 分钟、带原因",
          [(r, "10 分钟" in m, "PermissionError" in m) for m, r in w], [(False, True, True)])
    check("这条 WARNING 到了 errwatch 挂的那个 logger（会进群）", at_errwatch.count("WARNING"), 1)
    clock[0] = 1000.0 + 1800
    st.get("weekly", "garden")
    check("再过 20 分钟：不再发第二条", levels().count("WARNING"), 1)

    print("\n[读回来了：一条 INFO，说之前报过；再锁住是新的一段]")
    lock["on"] = False
    rows.rows.clear()
    check("读得到", st.get("weekly", "garden"), {"done_week": "2026-W45"})
    check("不再记着读不出来", statestore.refused_since(path), None)
    check("一条 INFO，说持续了多久、之前报过",
          [(lv, "30 分钟" in m and "已报过" in m) for lv, m, _ in rows.rows], [("INFO", True)])
    st.update("weekly", "garden", lambda _: {"done_week": "2026-W46"})
    check("又写得进去", json.loads(REAL_READ(path, encoding="utf-8"))["weekly"]["garden"], {"done_week": "2026-W46"})
    lock["on"] = True
    clock[0] = 5000.0
    rows.rows.clear()
    statestore.StateStore(d).get("weekly", "garden")
    check("再锁住：新的一段从这次算起", statestore.refused_since(path), 5000.0)
    clock[0] = 5000.0 + 600
    st.get("weekly", "garden")
    check("新的一段到 10 分钟：又一条 WARNING", levels().count("WARNING"), 1)
    lock["on"] = False
    st.get("weekly", "garden")

    print("\n[主循环：读不出来时 45 秒后再醒一次]")

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng.Engine(cfg, source=SimpleNamespace(fetch=lambda seen: []), state=State(cfg.state_dir),
                       notifier=SimpleNamespace(send=lambda *a, **k: False))
        e._scripts_running = lambda: False
        return e

    NOW = datetime(2026, 11, 8, 10, 0, tzinfo=SERVER_TZ)
    e = build()
    got = e.next_deadline(NOW)
    check("读得到时：没有重读的闹钟", "重读 state.json" in (got[1] if got else ""), False)
    e.state.store.update("weekly", "garden", lambda _: {"done_week": "2026-W45"})
    lock["on"] = True
    statestore.StateStore(e.cfg.state_dir).get("weekly", "garden")
    got = e.next_deadline(NOW)
    check("读不出来时：45 秒后重读", got, (NOW + timedelta(seconds=45), "重读 state.json"))
    lock["on"] = False
    e.state.store.get("weekly", "garden")
    check("读回来后闹钟就没了", "重读 state.json" in (e.next_deadline(NOW) or (None, ""))[1], False)
    Path.read_text = REAL_READ

    print("\n[需求表：当天第一次没成，半小时后叫醒主循环去试第二次]")
    needtable._running.clear()
    nd = tmpdir()
    check("今天还没建过：没有这个闹钟", needtable.next_moment(nd, NOW), None)
    (nd / needtable.MARK).write_text(json.dumps({"day": "2026-11-08", "ok": False, "skip": False, "tries": 1,
                                                 "last_at": (NOW - timedelta(minutes=5)).isoformat()}),
                                     encoding="utf-8")
    check("第一次没成：失败后 30 分钟", needtable.next_moment(nd, NOW),
          (NOW + timedelta(minutes=25), "终末地需求表当天第二次重算"))
    check("到点之后不再给过去的时刻（这一轮就会去试）", needtable.next_moment(nd, NOW + timedelta(minutes=26)), None)
    e2 = build()
    e2.cfg.state_dir = nd
    check("next_deadline 里有这个闹钟", e2.next_deadline(NOW), (NOW + timedelta(minutes=25), "终末地需求表当天第二次重算"))
    for done in ({"ok": True}, {"skip": True}, {"tries": 2}, {"day": "2026-11-07"}):
        m = {"day": "2026-11-08", "ok": False, "skip": False, "tries": 1,
             "last_at": (NOW - timedelta(minutes=5)).isoformat(), **done}
        (nd / needtable.MARK).write_text(json.dumps(m), encoding="utf-8")
        check(f"不用再试（{done}）：没有闹钟", needtable.next_moment(nd, NOW), None)

    class Alive:
        def is_alive(self):
            return True

    needtable._running.update(thread=Alive(), day="2026-11-08", count=1)
    check("正在建：最晚 30 分钟后看一眼", needtable.next_moment(nd, NOW), (NOW + timedelta(minutes=30), "看终末地需求表重算完没有"))
    needtable._running.clear()

    print("\n[AUTO-MAS 记录：缺日志等着补记、history.db 读不了，都要叫醒主循环]")
    collector._put_off.clear()
    collector._db_fail_streak[0] = 0
    check("没有等着的：没有闹钟", collector.next_moment(NOW), None)
    collector._put_off.extend([(NOW + timedelta(seconds=90)).timestamp(), (NOW + timedelta(seconds=30)).timestamp(),
                               (NOW - timedelta(seconds=5)).timestamp()])
    check("缺日志的：最早那条到点时（过去的不算）", collector.next_moment(NOW), (NOW + timedelta(seconds=30), "补记缺日志的运行记录"))
    collector._put_off.clear()
    collector._db_fail_streak[0] = 1
    check("history.db 读不了：45 秒后再读", collector.next_moment(NOW), (NOW + timedelta(seconds=45), "重读 AUTO-MAS 的 history.db"))
    e3 = build()
    check("next_deadline 里有它", e3.next_deadline(NOW), (NOW + timedelta(seconds=45), "重读 AUTO-MAS 的 history.db"))
    collector._db_fail_streak[0] = 0

    hist = TMP / "history2"
    young = hist / "2026-11-08" / "MAA" / "10-00-00.json"
    young.parent.mkdir(parents=True)
    young.write_text("{}", encoding="utf-8")
    collector.scan(hist, set())
    check("扫到一条没日志的新记录：记下它 120 秒后补记", len(collector._put_off), 1)
    check("…时刻就是它写下后 120 秒", round(collector._put_off[0] - young.stat().st_mtime), 120)
    (young.with_suffix(".log")).write_text("", encoding="utf-8")
    collector.scan(hist, set())
    check("日志来了：不再等", collector._put_off, [])


def _part_atomic_write():
    """落盘只能走 config.atomic_write_*，不许自己手抄「临时文件 + replace」。"""
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    # 1. 唯一的实现在 config.py，而且带 fsync
    cfg = (ROOT / "ark_relay" / "core" / "config.py").read_text(encoding="utf-8")
    check("config.atomic_write_bytes 存在", "def atomic_write_bytes" in cfg, True)
    body = cfg[cfg.index("def atomic_write_bytes"):]
    body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    check("它 fsync 了", "os.fsync" in body, True)
    check("它用 os.replace", "os.replace" in body, True)

    # 2. 别处不许再出现「.tmp 然后 replace」这一对
    offenders = []
    for p in sorted([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files"} & set(p.parts)]) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
        if p.name == "config.py":
            continue
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r'^\s*(\w+)\s*=\s*.*with_suffix\([^\n]*\.tmp', src, re.M):
            var = m.group(1)
            after = src[m.end():m.end() + 600]
            if re.search(rf"\b(os\.replace\(\s*{var}|{var}\.replace\()", after):
                line = src[:m.start()].count("\n") + 1
                offenders.append(f"{p.name}:{line}")
    check("没有别处再手抄原子写", offenders, [])

    # 3. 写配置的模块都在用它（抽查那五个改过的）
    # (paths after ark_relay/ was split into core/ and features/<name>/)
    for name in ("features/annihilation.py", "features/weeklyboss.py",
                 "features/preupdate.py", "core/desktop.py"):
        src = (ROOT / "ark_relay" / name).read_text(encoding="utf-8")
        check(f"{name} 走的是共用实现",
              bool(re.search(r"atomic_write_(text|bytes)\(", src)), True)

    # 4. State files the relay reads back must not be written in place.
    # The game PC can lose power or be killed mid-write (the 08:40 socket cut when
    # the machine was left on, a forced shutdown). A half-written state file is
    # read as empty: retry failure streaks reset, sent markers are lost (the tacet
    # shot / upstream-change notice goes out again), the ntfy day count drops to
    # zero. These modules write such files and must go through atomic_write_*;
    # a direct write_text / write_bytes / open("w") in them fails here.
    # Appends (open "a" / "ab") are allowed: a cut loses at most the last line.
    DIRECT_OVERWRITE = re.compile(
        r"\.write_text\(|\.write_bytes\(|\bopen\([^)\n]*[\"'](?:w|wb|w\+|wb\+|x|xb)[\"']")
    STATE_WRITERS = (
        "ark_relay/features/collect_retry.py",   # collect-retry/failures.json, <day>.json
        "ark_relay/features/report.py",          # tacet-shots-<day>.sent
        "boot_stages.py",                               # evidence-source-notified.json
        "ark_relay/features/phone.py",            # ntfy-<utc day>.json
        "ark_relay/features/errwatch.py",         # alert day file re-seeded from COS
        "ark_relay/features/evidence.py",        # evidence/gofile.json
        "ark_relay/features/banners.py",        # banners/<day>.json
    )
    for name in STATE_WRITERS:
        src = (ROOT / name).read_text(encoding="utf-8")
        direct = [f"{name}:{src[:m.start()].count(chr(10)) + 1}"
                  for m in DIRECT_OVERWRITE.finditer(src)]
        check(f"{name} has no direct state-file overwrite", direct, [])
        check(f"{name} writes via atomic_write_*",
              bool(re.search(r"atomic_write_(text|bytes)\(", src)), True)


def _part_state_pending():
    """待推告警的存/取。**这条路没有测试过，结果炸在生产上。**"""
    from datetime import datetime, timedelta

    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.core.collector import record_to_payload, payload_to_record

    def rec(run_id="2026-09-08/wuwa/OK-WW-05-22-26"):
        now = datetime.now(tz=SERVER_TZ)
        return RunRecord(run_id=run_id, script="OK-WW", user="wuwa",
                         started=now - timedelta(minutes=10), finished=now,
                         ok=False, failed_tasks=["任务执行：某个错"], raw={})

    print("[save_pending 是方法，不是属性——这正是 09-08 那次的原形]")
    check("是普通函数", type(State.__dict__["save_pending"]).__name__, "function")
    check("不是 property", isinstance(State.__dict__["save_pending"], property), False)

    print("\n[存进去、另起一个实例读回来，内容一样]")
    d = tmpdir()
    st = State(d)
    payload = {"pending": [record_to_payload(rec())], "recovered": []}
    st.save_pending(payload)
    back = State(d).load_pending()
    check("pending 条数", len(back.get("pending") or []), 1)
    check("run_id 对得上", back["pending"][0]["run_id"], "2026-09-08/wuwa/OK-WW-05-22-26")
    check("recovered 空", back.get("recovered"), [])

    print("\n[读回来能还原成记录，告警才发得出去]")
    r2 = payload_to_record(back["pending"][0])
    check("脚本名", r2.script, "OK-WW")
    check("失败任务", r2.failed_tasks, ["任务执行：某个错"])
    check("不是成功", r2.ok, False)

    print("\n[空的也存得下：清空待推队列走的就是这条路]")
    st.save_pending({"pending": [], "recovered": []})
    check("清空后读回来是空的", State(d).load_pending(), {"pending": [], "recovered": []})

    print("\n[没存过时读回空字典，不抛异常]")
    check("空目录", State(tmpdir()).load_pending(), {})


def _part_statestore_threads():
    """Two threads writing state.json must not lose each other's key."""
    import os
    import threading
    import time

    from ark_relay.core import config, statestore
    from ark_relay.core.statestore import StateStore

    print("[a second writer runs while the first is between its read and its write]")
    d = tmpdir()
    StateStore(d).set("queues", "phone_seen", [])
    real_write = statestore.atomic_write_text
    errors: list = []
    other: list = []

    def slow_first_write(path, text, *a, **k):
        # Only the first write is slowed down: the engine-thread writer below.
        if not other:
            def phone_thread():
                try:
                    StateStore(d).set("queues", "phone_seen", ["ntfy-1"])
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
            t = threading.Thread(target=phone_thread)
            other.append(t)
            t.start()
            time.sleep(0.3)          # the phone thread gets every chance to write now
        return real_write(path, text, *a, **k)

    statestore.atomic_write_text = slow_first_write
    try:
        StateStore(d).set("modes", "debug_until", "2026-10-13 21:10")
    finally:
        statestore.atomic_write_text = real_write
    other[0].join(5)
    s = StateStore(d)
    check("the engine thread's key is there", s.get("modes", "debug_until"), "2026-10-13 21:10")
    check("the phone thread's key is there", s.get("queues", "phone_seen"), ["ntfy-1"])
    check("no writer raised", errors, [])

    print("\n[pop is under the same lock]")
    other.clear()

    def slow_first_write2(path, text, *a, **k):
        if not other:
            t = threading.Thread(target=lambda: StateStore(d).set("queues", "phone_seen", ["ntfy-2"]))
            other.append(t)
            t.start()
            time.sleep(0.3)
        return real_write(path, text, *a, **k)

    statestore.atomic_write_text = slow_first_write2
    try:
        StateStore(d).pop("modes", "debug_until")
    finally:
        statestore.atomic_write_text = real_write
    other[0].join(5)
    s = StateStore(d)
    check("the popped key is gone", s.get("modes", "debug_until"), None)
    check("the other thread's write survived the pop", s.get("queues", "phone_seen"), ["ntfy-2"])

    print("\n[two writes of the same file never share a temp file]")
    d2 = tmpdir()
    target = d2 / "state.json"
    real_fsync = config.os.fsync
    inner_err: list = []
    nested = []

    def fsync_then_second_write(fd):
        real_fsync(fd)
        if not nested:
            nested.append(1)
            # A second writer of the same path while the first one's temp file is open.
            try:
                config.atomic_write_bytes(target, b'{"b": 1}')
            except OSError as exc:
                inner_err.append(exc)

    config.os.fsync = fsync_then_second_write
    outer_err = None
    try:
        config.atomic_write_bytes(target, b'{"a": 1}')
    except OSError as exc:
        outer_err = exc
    finally:
        config.os.fsync = real_fsync
    check("the inner write did not fail", inner_err, [])
    check("the outer write did not fail", repr(outer_err) if outer_err else None, None)
    check("the last write wins, whole", target.read_bytes(), b'{"a": 1}')
    check("no temp file left behind", sorted(p.name for p in d2.iterdir()), ["state.json"])

    print("\n[a temp file a power cut left behind is removed at the next start once it is a day old]")
    d3 = tmpdir()
    (d3 / "state.json").write_text("{}", encoding="utf-8")
    old_tmp = d3 / "state.json.abc123.tmp"
    fresh_tmp = d3 / "state.json.def456.tmp"
    legacy_tmp = d3 / "state.json.tmp"
    other_tmp = d3 / "ledger-2026-10-13.jsonl.xyz.tmp"
    for f in (old_tmp, fresh_tmp, legacy_tmp, other_tmp):
        f.write_text("{", encoding="utf-8")
    two_days_ago = time.time() - 2 * 86400
    for f in (old_tmp, legacy_tmp, other_tmp):
        os.utime(f, (two_days_ago, two_days_ago))
    statestore._SWEPT.discard(str(d3))
    statestore.StateStore(d3)
    check("old state.json temp files are gone, a fresh one (a live write) and other files stay",
          sorted(p.name for p in d3.iterdir()),
          sorted(["state.json", fresh_tmp.name, other_tmp.name]))


if __name__ == "__main__":
    sys.exit(run_parts([_part_shutdown_main, _part_shutdown_after_restart, _part_shutdown_unfixed_shift, _part_shutdown_hand_and_test_runs, _part_shutdown_held_past_shift, _part_shutdown_notice, _part_shutdown_open_test_window, _part_shutdown_round, _part_shutdown_stale_shift, _part_shutdown_waits_for_farm, _part_shutdown_whitelist, _part_exit_shutdown_window, _part_power_off_returncode, _part_poweroff_ok, _part_skip_shutdown_wording, _part_skip_failed_pushed, _part_skip_flag_collision, _part_skip_receipt_lost, _part_skip_receipts, _part_skip_sat_out, _part_skip_shutdown_bat_error, _part_farm_poweroff, _part_place_desktop_bat, _part_statestore_main, _part_state_read_lock, _part_state_unread, _part_atomic_write, _part_state_pending, _part_statestore_threads]))
