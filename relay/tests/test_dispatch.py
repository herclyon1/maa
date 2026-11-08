"""Dispatching a script: the guards (idle, self, silent, test / debug) and the note's timing.

One part per former file, each run on its own (tests/_parts.py): test_dispatch_guard_idle.py, test_dispatch_guard_self.py, test_dispatch_guard_silent.py, test_dispatch_guard_test_debug.py, test_dispatch_note_timing.py.
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


def _part_dispatch_guard_idle():
    """run-one.sh wait-idle waits on dispatch_guard.py idle's exit code, not on the status wording.

2026-10-24 a hand-written wait grepped 「脚本在跑: []」 while the status line says 「脚本在跑: 无」,
and kept waiting long after the morning shift had ended (he asked 「不是已经跑完了吗？」).

    Formerly test_dispatch_guard_idle.py.
    """
    import runpy
    import subprocess
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    GUARD = ROOT / "scripts" / "windows" / "dispatch_guard.py"
    fails = []


    def check(label, got, want=True):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    def idle_exit(tasklist: str, okww_pids: str = "") -> int:
        """dispatch_guard.py idle's exit code with `tasklist` as the process list and
    `okww_pids` as the PowerShell query for OK-WW's own python (okww_pids)."""
        real_run = subprocess.run

        def fake(cmd, *a, **k):
            out = tasklist if cmd == ["tasklist"] else okww_pids
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        subprocess.run = fake
        argv = sys.argv
        sys.argv = [str(GUARD), "idle"]
        try:
            runpy.run_path(str(GUARD), run_name="__main__")
        except SystemExit as e:
            return int(e.code or 0)
        finally:
            subprocess.run, sys.argv = real_run, argv
        return 0


    print("[idle：只看有没有脚本或游戏在跑，退出码说话]")
    check("什么都没在跑 → 0", idle_exit("System Idle Process  0\nexplorer.exe  1234\n"), 0)
    check("MaaEnd 在跑 → 3", idle_exit("MaaEnd.exe  4321\n"), 3)
    check("只有游戏开着 → 3", idle_exit("Endfield.exe  5555\n"), 3)
    check("OK-WW 自己的 python 在跑 → 3", idle_exit("explorer.exe  1234\n", okww_pids="7996\n"), 3)
    run_one = (ROOT / "scripts" / "mac" / "run-one.sh").read_text(encoding="utf-8")
    check("run-one.sh wait-idle 用的是 idle 的退出码，不 grep 状态那一行", ("--py \"$G\" idle" in run_one, "grep" in run_one), (True, False))

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_dispatch_guard_self():
    """The busy gate must not mistake itself for a running script.

2026-09-09: `run-one.sh OK-WW` refused every dispatch with 「ok-ww 还在跑」 while
`run-one.sh status` reported the machine idle. The gate looked for 「ok-ww」 anywhere
in a python process's command line, PowerShell's -like is case-insensitive, and the
gate's own argument is the string OK-WW. It was seeing itself. A gate that blocks
everything is as broken as one that blocks nothing.

    Formerly test_dispatch_guard_self.py.
    """
    import re
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    SRC = (Path(__file__).resolve().parents[2] / "scripts" / "windows"
           / "dispatch_guard.py").read_text(encoding="utf-8")

    fails = []


    def check(label, got, want=True):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    pattern = re.search(r"CommandLine -like '([^']+)'", SRC)
    print("[判据必须是安装路径，不是一个能出现在参数里的词]")
    check("找得到那条匹配", bool(pattern))
    like = pattern.group(1) if pattern else ""
    check(f"带路径分隔符（{like}）", "\\" in like)


    def matches(cmdline: str) -> bool:
        """PowerShell -like, case-insensitive, * only."""
        body = re.escape(like).replace(r"\*", ".*")
        return re.fullmatch(body, cmdline, re.IGNORECASE) is not None


    print("[真在跑的两种起法都要认出来]")
    check("AUTO-MAS 起的 pythonw",
          matches(r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe D:\ark\okww\data\apps\ok-ww\working\main.py -t 1 -e"))
    check("手动起的 python",
          matches(r"D:\ark\okww\data\apps\ok-ww\python\python.exe main.py -t 2"))

    print("[闸门自己和别的脚本不许被算进去]")
    check("闸门自己（参数里带 OK-WW）",
          matches(r"C:\Python314\python.exe C:\ProgramData\winrun-run-123.py OK-WW"), False)
    check("参数里带小写 ok-ww 的别的命令",
          matches(r"C:\Python314\python.exe something.py --script ok-ww"), False)
    check("中继自己",
          matches(r"C:\Program Files\Python314\pythonservice.exe"), False)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_dispatch_guard_silent():
    """dispatch_guard.py must not read "cannot ask" as "nothing there".

Silent-failure audit rows:
* scripts/windows/dispatch_guard.py:98 - live_tasks returned [] when AUTO-MAS's
  runtime-snapshot was unreachable, timed out or not JSON. stop then printed
  「AUTO-MAS 没有在跑的任务」 and went straight to taskkill: the 2026-09-01 chain
  (taskkill read as a crash, AUTO-MAS retries the queue) the module exists to
  prevent.
* scripts/windows/dispatch_guard.py:164 - a corrupt test-windows.json read as
  "no window open": test-status exited 0 and test_on overwrote the history.

    Formerly test_dispatch_guard_silent.py.
    """
    import contextlib
    import io
    import json
    import sys
    import urllib.error
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "windows"))
    import dispatch_guard as g
    from _tmp import tmpdir

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
        if not ok:
            fails.append(label)


    class Answer:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body


    def quiet(fn, *a):
        """(value or SystemExit code, stdout) of fn(*a)."""
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                got = fn(*a)
        except SystemExit as e:
            got = ("exit", e.code)
        return got, out.getvalue()


    REFUSED = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
    SNAP_EMPTY = json.dumps({"tasks": []}).encode()
    SNAP_MAA = json.dumps({"tasks": [{"taskId": "t1", "task_info": [{"name": "MAA"}]}]}).encode()


    def snapshots(*answers):
        """urlopen answering the runtime-snapshot with each item in turn (the last one repeats);
    an exception item is raised."""
        left = list(answers)

        def urlopen(*a, **k):
            item = left.pop(0) if len(left) > 1 else left[0]
            if isinstance(item, BaseException):
                raise item
            return Answer(item)
        return urlopen


    print("[live_tasks: cannot ask is None, nothing running is []]")
    g.urllib.request.urlopen = snapshots(REFUSED)
    check("connection refused -> None", quiet(g.live_tasks)[0], None)
    g.urllib.request.urlopen = snapshots(TimeoutError("timed out"))
    check("timeout -> None", quiet(g.live_tasks)[0], None)
    g.urllib.request.urlopen = snapshots(b"<html>not json</html>")
    check("not JSON -> None", quiet(g.live_tasks)[0], None)
    g.urllib.request.urlopen = snapshots(SNAP_EMPTY)
    check("an empty snapshot -> []", quiet(g.live_tasks)[0], [])


    def stop_with(urlopen, running_seq):
        """stop_all with the snapshot answered by `urlopen` and running() giving `running_seq` in turn."""
        kills = []
        runs = list(running_seq)
        g.urllib.request.urlopen = urlopen
        g.running = lambda: runs.pop(0) if len(runs) > 1 else runs[0]
        g.post = lambda *a, **k: {"message": "操作成功"}
        g.subprocess.run = lambda args, **k: kills.append(args)
        g.okww_pids = lambda: []
        g.time.sleep = lambda s: None
        ok, out = quiet(g.stop_all)
        return ok, out, [k for k in kills if k and k[0] == "taskkill"]


    print("[stop with AUTO-MAS unreachable and MAA still up: no taskkill]")
    ok, out, kills = stop_with(snapshots(REFUSED), [(["MAA"], [])])
    check("no taskkill was run", kills, [])
    check("stop_all reports failure", ok, False)
    check("it does not claim nothing is running", "没有在跑的任务" in out, False)
    check("it says why it refused to kill", "不 taskkill" in out, True)

    print("[the 12 s recheck cannot ask: still no taskkill]")
    ok, out, kills = stop_with(snapshots(SNAP_MAA, REFUSED), [(["MAA"], [])])
    check("no taskkill after a failed recheck", kills, [])
    check("stop_all reports failure after a failed recheck", ok, False)

    print("[AUTO-MAS answered nothing running and a game is left: taskkill as before]")
    ok, out, kills = stop_with(snapshots(SNAP_EMPTY), [([], ["Endfield"]), ([], [])])
    check("taskkill was run", len(kills) > 0, True)
    check("stop_all reports clean after taskkill", ok, True)

    print("[AUTO-MAS unreachable but nothing running: clean]")
    ok, out, kills = stop_with(snapshots(REFUSED), [([], [])])
    check("no taskkill when nothing runs", kills, [])
    check("stop_all reports clean when nothing runs", ok, True)

    print("[a corrupt test-windows.json is not 'no window open']")
    d = tmpdir()
    g.TEST_WINDOWS = str(d / "test-windows.json")
    check("missing file: test-status says closed (exit 0)", quiet(g.test_status)[0], 0)
    Path(g.TEST_WINDOWS).write_text('[{"since": "2026-10-10T01:00:00+08:00", "until": nu', encoding="utf-8")
    before = Path(g.TEST_WINDOWS).read_bytes()
    got, out = quiet(g.test_status)
    check("test-status exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
    check("it does not print the closed status line", "测试窗口：没开" in out, False)
    got, out = quiet(g.test_on, "MAA")
    check("test_on exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
    got, out = quiet(g.test_off)
    check("test_off exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
    check("the file is untouched", Path(g.TEST_WINDOWS).read_bytes(), before)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_dispatch_guard_test_debug():
    """A test dispatch turns debug mode on first, and test-off turns off only what it turned on.

2026-10-13 11:05 (Beijing) `run-one.sh OK-WW --test` ran after the morning shift
had spent the one-shot 「下次跑完不关机」 mark; when the run ended the relay logged
11:13:55 「本轮已处理完毕，60 秒后关机」 and powered the machine off, which cannot be
undone remotely. The rule 「临时跑不改排班；维护先开调试模式」 was a habit with
nothing enforcing it. dispatch_guard.start(test=True) now writes the relay's debug
mode (modes.set_debug, the state the debug_mode command writes) before dispatching,
records in the test window that it did, refuses the dispatch when it cannot, and
test_off turns it off again only if this window turned it on.

    Formerly test_dispatch_guard_test_debug.py.
    """
    import contextlib
    import inspect
    import io
    import json
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))
    sys.path.insert(0, str(ROOT / "relay" / "tests"))
    sys.path.insert(0, str(ROOT / "scripts" / "windows"))
    import dispatch_guard as g
    from _tmp import tmpdir
    from ark_relay.features.modes import modes

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    def setup():
        state = tmpdir()
        g.STATE_DIR = str(state)
        g.TEST_WINDOWS = str(state / "test-windows.json")
        return state


    dispatched = []
    g.status = lambda: []
    g.ids = lambda: {"OK-WW": "sid-okww"}
    g.post = lambda path, body=None: dispatched.append(body["taskId"]) or {"status": "success"}
    g._modes = lambda: modes


    def run(fn, *a, **k):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = fn(*a, **k)
        return rc, out.getvalue()


    def windows():
        return json.loads(Path(g.TEST_WINDOWS).read_text(encoding="utf-8"))


    print("[debug off -> the test start turns it on before dispatching, and records it]")
    state = setup()
    dispatched.clear()
    rc, out = run(g.start, "OK-WW", test=True)
    check("dispatched", (rc, dispatched), (0, ["sid-okww"]))
    check("debug mode on", modes.debug_active(state), True)
    check("the window records the debug_until it wrote", windows()[-1].get("debug_set"), modes.debug_until(state))
    rc, out = run(g.test_status)
    check("test-status says this window turned it on", "调试模式是这个窗口开的" in out, True)
    rc, out = run(g.test_off)
    check("test-off: window closed", windows()[-1]["until"] is not None, True)
    check("test-off: debug mode off again", (rc, modes.debug_active(state)), (0, False))

    print("\n[10-13: the morning shift spent 「下次跑完不关机」 (key :3), then a test -> test-off keeps that skip]")
    state = setup()
    modes.mark_shutdown_skipped(state, "2026-10-13:3")       # what take_skip's caller writes
    run(g.start, "OK-WW", test=True)
    rc, out = run(g.test_off)
    check("test-off: debug mode off", (rc, modes.debug_active(state)), (0, False))
    check("test-off: the spent mark's skipped occasion is still there (no power-off after the test)",
          modes.shutdown_skipped(state), "2026-10-13:3")

    print("\n[a skip debug mode itself recorded during the window -> test-off releases it]")
    state = setup()
    run(g.start, "OK-WW", test=True)
    can_tag = "by_debug" in inspect.signature(modes.mark_shutdown_skipped).parameters
    check("debug mode's own skip is told apart from the mark's", can_tag, True)
    if can_tag:
        modes.mark_shutdown_skipped(state, "2026-10-13:4", by_debug=True)   # shutdown._maybe_shutdown, verdict "debug"
        run(g.test_off)
        check("test-off: debug mode's own skip is cleared", modes.shutdown_skipped(state), "")

    print("\n[debug already on -> left on, and not turned off at test-off]")
    state = setup()
    modes.set_debug(state, 2)
    before = modes.debug_until(state)
    dispatched.clear()
    rc, out = run(g.start, "OK-WW", test=True)
    check("dispatched", (rc, dispatched), (0, ["sid-okww"]))
    check("debug untouched", modes.debug_until(state), before)
    check("the window does not claim it", "debug_set" in windows()[-1], False)
    rc, out = run(g.test_off)
    check("test-off leaves it on", (rc, modes.debug_until(state)), (0, before))

    print("\n[changed during the window (e.g. extended from the phone) -> test-off leaves it]")
    state = setup()
    run(g.start, "OK-WW", test=True)
    modes.set_debug(state, 3)
    extended = modes.debug_until(state)
    run(g.test_off)
    check("left as extended", modes.debug_until(state), extended)

    print("\n[debug mode cannot be written -> the test dispatch is refused]")
    state = setup()


    class Broken:
        debug_active = staticmethod(lambda sd: False)
        debug_until = staticmethod(lambda sd: "")

        @staticmethod
        def set_debug(sd, cycles=1, off=False):
            raise OSError(13, "Access is denied")


    g._modes = lambda: Broken
    dispatched.clear()
    rc, out = run(g.start, "OK-WW", test=True)
    check("refused, non-zero", rc, 6)
    check("nothing dispatched", dispatched, [])
    check("says why", "调试模式开不了" in out and "Access is denied" in out, True)
    check("no test window opened", Path(g.TEST_WINDOWS).exists(), False)

    print("\n[test-windows.json unreadable -> refused before debug mode is switched on]")
    state = setup()
    g._modes = lambda: modes
    Path(g.TEST_WINDOWS).write_text("{not json", encoding="utf-8")
    dispatched.clear()
    try:
        rc, out = run(g.start, "OK-WW", test=True)
    except SystemExit as exc:
        rc = exc.code
    check("refused with exit 5", rc, 5)
    check("debug mode left off (nothing would ever turn it off again)", modes.debug_active(state), False)
    check("nothing dispatched", dispatched, [])
    check("the window file is left as it was", Path(g.TEST_WINDOWS).read_text(encoding="utf-8"), "{not json")

    print("\n[a normal (non-test) dispatch does not touch debug mode]")
    state = setup()
    g._modes = lambda: modes
    dispatched.clear()
    rc, out = run(g.start, "OK-WW")
    check("dispatched, debug still off", (rc, modes.debug_active(state)), (0, False))

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
    sys.exit(1 if fails else 0)


def _part_dispatch_note_timing():
    """The relay notes "this run is mine" right before the dispatch call, after the
OK-WW overlay step.

Evidence audit 2026-10-13: commands.run_script / _run_now called _note_dispatch
first and okww_overlay.retry_pending second. The overlay step has no time limit,
so a slow one let AUTO-MAS create the task more than trigger.MATCH_AFTER_S (60 s)
after the note, and trigger.hand_started_task then booked the relay's own run as
hand-started (no make-up, no overrun alarm).

    Formerly test_dispatch_note_timing.py.
    """
    import os
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.guard import trigger
    from ark_relay.features.okww_patch import okww_overlay as ov
    from ark_relay.features.phone import commands

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    clock = {"t": datetime(2026, 10, 13, 8, 0, 0, tzinfo=SERVER_TZ)}
    created: list[trigger.Task] = []


    def slow_overlay(where):
        clock["t"] += timedelta(seconds=120)     # an overlay step that takes two minutes
        return ""


    def mas(path, body=None):
        if path == "/api/scripts/get":
            return {"data": {"s1": {"Info": {"Name": "OK-WW"}}}}
        if path == "/api/queue/get":
            return {"data": {"q1": {"Info": {"Name": "早班"}}}}
        # AUTO-MAS labels the relay's start manual_task, like a click on its screen.
        created.append(trigger.Task(id=body["taskId"], mode="AutoProxy", source=trigger.MANUAL,
                                    created=clock["t"] + timedelta(seconds=2)))
        return {"status": "success"}


    real = (ov.retry_pending, commands._mas, trigger.note_dispatch)
    real_note = trigger.note_dispatch
    ov.retry_pending = slow_overlay
    commands._mas = mas
    trigger.note_dispatch = lambda state_dir, what, now=None: real_note(state_dir, what, now=clock["t"])
    state = Path(os.environ["ARK_STATE_DIR"])
    try:
        print("[a slow overlay step before a single-script dispatch]")
        check("dispatched", commands.run_script("OK-WW")[0], True)
        check("the relay's own run is not hand-started", trigger.hand_started_task(created[-1], state), False)

        print("\n[a slow overlay step before a queue dispatch]")
        clock["t"] += timedelta(hours=1)
        check("dispatched", commands._run_now("早班")[0], True)
        check("the relay's own run is not hand-started", trigger.hand_started_task(created[-1], state), False)
    finally:
        ov.retry_pending, commands._mas, trigger.note_dispatch = real

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_dispatch_guard_idle, _part_dispatch_guard_self, _part_dispatch_guard_silent, _part_dispatch_guard_test_debug, _part_dispatch_note_timing]))
