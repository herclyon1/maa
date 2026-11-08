"""The watchdogs: the service watchdog's copy, crash loops, the guard (and a missing one), push delivery; and the GitHub Actions boot watchdog.

One part per former file, each run on its own (tests/_parts.py): test_watchdog_copy.py, test_watchdog_crashloop.py, test_watchdog_guard.py, test_watchdog_guard_missing.py, test_watchdog_push_delivery.py, test_gh_watchdog.py.
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


def _part_watchdog_copy():
    """The watchdog's three group-bot messages read as plain words, like every relay push.

packaging/watchdog/ark_watchdog.py imports pywin32, so its texts are read with ast,
not imported. Every title must also be a row of docs/NOTIFICATIONS.md's route table
(test_notify_routing.py then checks that they route to the group).

The other way round, relay/watchdog_guard.py's two ERRORs go to the group as they are,
through errwatch (「🩺 中继自己报错了」), so they are held to the same plain words (review
round 10 #29: 「拉起」 got through because log lines skip plain()). Every Chinese line the
guard logs is checked too.

    Formerly test_watchdog_copy.py.
    """
    import ast

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))

    from ark_relay.core.texts import plain

    src = (ROOT / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
    texts = {t.id: ast.literal_eval(n.value) for n in ast.parse(src).body
             if isinstance(n, ast.Assign) for t in n.targets
             if isinstance(t, ast.Name) and t.id.startswith(("ALERT_", "REASON_HEAD", "REASON_NONE"))}
    doc = (ROOT / "docs" / "NOTIFICATIONS.md").read_text(encoding="utf-8")

    bad = 0
    if set(texts) != {"ALERT_DOWN", "ALERT_NOBODY", "ALERT_CRASHLOOP", "REASON_HEAD", "REASON_NONE"}:
        print("FAIL: expected ALERT_DOWN, ALERT_NOBODY, ALERT_CRASHLOOP and the two REASON_ lines, found",
              sorted(texts))
        bad += 1
    for name, text in texts.items():
        filled = text.format(n=3, s=30, m=30)
        problems = plain(filled)
        title = filled.split("\n", 1)[0]
        # The REASON_ lines are appended to an alert, not alerts of their own.
        row = name.startswith("REASON_") or f"| {title} | group |" in doc
        print(f"{'ok' if not problems and row else 'FAIL'} {name}: {problems or 'plain'}; table row: {row}")
        bad += bool(problems) or not row
    import watchdog_guard as G

    guard_alerts = {k: v for k, v in vars(G).items() if k.startswith("ALERT_")}
    if set(guard_alerts) != {"ALERT_GAVE_UP", "ALERT_CANNOT_LOOK"}:
        print("FAIL: expected ALERT_GAVE_UP and ALERT_CANNOT_LOOK in watchdog_guard, found", sorted(guard_alerts))
        bad += 1
    for name, text in guard_alerts.items():
        # Filled the way failed() fills it; the reason is one _start writes.
        problems = plain(text % (3, "开到一半自己停了"))
        print(f"{'ok' if not problems else 'FAIL'} watchdog_guard.{name}: {problems or 'plain'}")
        bad += bool(problems)
    guard_src = (ROOT / "relay" / "watchdog_guard.py").read_text(encoding="utf-8")
    logged = [c.value for c in ast.walk(ast.parse(guard_src))
              if isinstance(c, ast.Constant) and isinstance(c.value, str) and "\n" not in c.value
              and any("\u4e00" <= ch <= "\u9fff" for ch in c.value)]   # docstrings have line breaks
    for text in logged:
        problems = plain(text.replace("%d", "3").replace("%s", "原因").replace("{START_WAIT_S}", "45"))
        if problems:
            print(f"FAIL watchdog_guard copy {text!r}: {problems}")
            bad += 1
    print(f"{'ok' if logged else 'FAIL'} watchdog_guard: {len(logged)} Chinese strings read")
    bad += not logged
    print("\n" + ("FAILED" if bad else "all checks passed"))
    sys.exit(1 if bad else 0)


def _part_watchdog_crashloop():
    """The watchdog says why the relay does not start, and rings when it keeps crashing.

Two gaps between the installed relay and the old service, 2026-10-11:
  a. A relay that dies before its log is open (an import error, a broken .env) left
     no trace: the scheduled task runs pythonw.exe, which has no console, and the
     watchdog's 「重开 3 次都没起来」 alarm said nothing about why. packaging/launch.py now
     appends the traceback to <data>\\start-error.txt, and the watchdog puts its last
     lines into the alarm when it was written in that stretch.
  b. A relay that comes up and dies again a while later never reached FAIL_LIMIT: each
     look that found it running reset the count (2026-10-10 16:28: 15 restarts, no
     alarm). The watchdog now rings once when it had to start the relay LOOP_STARTS
     times within LOOP_WINDOW_S, at most once per LOOP_QUIET_S, not during a shutdown.

Runs on any OS: pywin32 is faked, the watchdog's Windows calls are replaced.

    Formerly test_watchdog_crashloop.py.
    """
    import os
    import time
    import types

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging"))
    sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))

    DATA = tmpdir()
    os.environ["ARK_HOME"] = str(DATA)


    def _module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m


    class _PyError(Exception):
        pass


    SHUTTING = {"on": 0}
    _module("pywintypes", error=_PyError)
    _module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
    _module("win32api", GetSystemMetrics=lambda i: SHUTTING["on"], CloseHandle=lambda h: None)
    _module("win32event", CreateEvent=lambda *a: None, SetEvent=lambda e: None, WaitForSingleObject=lambda *a: 0,
            WAIT_TIMEOUT=258)
    _module("win32service", SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_PRESHUTDOWN=0xF,
            SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)
    _module("win32serviceutil", ServiceFramework=object)
    _module("win32ts")

    import ark_watchdog as W
    import launch

    # ---------------------------------------------------------------- a. the record
    print("[launch.py: a start that dies with a Python error leaves its traceback]")
    check("same file name on both sides", W.START_ERROR.name, launch.START_ERROR)
    check("same data folder on both sides", (W.DATA, launch.DATA), (DATA, DATA))
    code = tmpdir() / "versions" / "20261011120000"
    code.mkdir(parents=True)
    (code / "app_main.py").write_text("import ark_relay_module_that_is_not_there\n", encoding="utf-8")
    real_folder, real_argv = launch._code_folder, sys.argv
    launch._code_folder = lambda: code
    sys.argv = ["launch.py"]
    try:
        launch.main()
        raised = None
    except ModuleNotFoundError as exc:
        raised = exc
    finally:
        sys.argv = real_argv
    check("the error still goes on (the task sees the process fail)", type(raised).__name__, "ModuleNotFoundError")
    rec = (DATA / launch.START_ERROR).read_text(encoding="utf-8")
    check("the record names the error", "No module named 'ark_relay_module_that_is_not_there'" in rec)
    check("the record names the version folder and the command", (str(code) in rec, "launch.py run" in rec), (True, True))
    check("the record holds the traceback", "Traceback (most recent call last)" in rec)

    print("[launch.py: a stop / rollback / stop-push exit code is not an error]")
    (DATA / launch.START_ERROR).unlink()
    (code / "app_main.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    sys.argv = ["launch.py", "stop"]
    try:
        launch.main()
    except SystemExit:
        pass
    finally:
        sys.argv = real_argv
        launch._code_folder = real_folder
    check("no record for SystemExit", (DATA / launch.START_ERROR).exists(), False)

    print("[launch.py: only a start leaves a record; a stop / stop-push / rollback that dies does not]")
    # s26 audit 2026-10-13: the watchdog quotes this file as 「最后一次起不来时留下的记录」,
    # so a stop-push that died at shutdown read as a failed start.
    (code / "app_main.py").write_text("raise RuntimeError('stop-push blew up')\n", encoding="utf-8")
    launch._code_folder = lambda: code
    for cmd in (["stop"], ["stop-push"], ["rollback"], [], ["run"]):
        sys.argv = ["launch.py", *cmd]
        try:
            launch.main()
        except RuntimeError:
            pass
        finally:
            sys.argv = real_argv
        there = (DATA / launch.START_ERROR).exists()
        check(f"launch.py {' '.join(cmd) or '(no argument)'}: {'recorded' if cmd in ([], ['run']) else 'no record'}",
              there, cmd in ([], ["run"]))
        if there:
            (DATA / launch.START_ERROR).unlink()
    launch._code_folder = real_folder

    print("[launch.py: the file keeps only the newest failures]")
    for i in range(400):
        launch.record_start_error(["run"], code, f"Traceback (most recent call last):\nboom number {i}\n" + "x" * 200)
    rec = (DATA / launch.START_ERROR).read_text(encoding="utf-8")
    check("capped", len(rec) <= launch.START_ERROR_MAX, True)
    check("the newest one is kept", rec.rstrip().endswith("x" * 200) and "boom number 399" in rec, True)

    # ---------------------------------------------------------------- the watchdog
    pushed, started = [], []
    running = {"on": False}
    W.main_running = lambda: running["on"]
    W.someone_logged_on = lambda: True
    W.start_main = lambda: started.append(1) or True
    W.push = lambda text: pushed.append(text) or True   # delivered
    W._log = lambda line: None
    NOW = time.time()


    def tick(w, minute, up=False, wall_base=NOW):
        running["on"] = up
        w.tick(minute * 60.0, wall=wall_base + minute * 60.0)


    print("\n[never comes up: 「中继停了」 at the 3rd start, with the record's last lines]")
    (DATA / launch.START_ERROR).unlink()
    launch.record_start_error(["run"], code, 'Traceback (most recent call last):\n  File "app_main.py", line 1\n'
                              "ModuleNotFoundError: No module named 'win32event'")
    os.utime(DATA / launch.START_ERROR, (NOW + 30, NOW + 30))
    w = W.Watch()
    for m in (0, 0.5, 1):
        tick(w, m)
    check("one push", len(pushed), 1)
    check("it is 「中继停了」", pushed[0].startswith("🔌 中继停了"), True)
    check("with the record's head line", W.REASON_HEAD in pushed[0], True)
    check("with the error line", pushed[0].rstrip().endswith("No module named 'win32event'"), True)
    check("short enough for the group bot", len(pushed[0].encode("utf-8")) < 2048, True)
    for m in (1.5, 2, 2.5, 3):
        tick(w, m)
    check("no crash-loop alarm on top of 「中继停了」 for the same stretch", len(pushed), 1)

    print("[a record from before this stretch is not shown]")
    os.utime(DATA / launch.START_ERROR, (NOW - 3600, NOW - 3600))
    pushed.clear()
    w = W.Watch()
    for m in (0, 0.5, 1):
        tick(w, m)
    check("「中继停了」 says there is no record", (W.REASON_HEAD in pushed[0], W.REASON_NONE in pushed[0]), (False, True))

    print("[comes up and dies again: 4 starts in 30 minutes quiet, the 5th rings once]")
    pushed.clear()
    w = W.Watch()
    for k in range(4):
        tick(w, 5 * k, up=True)
        tick(w, 5 * k + 0.5)                # gone again: the watchdog starts it
    check("4 starts: nothing", len(pushed), 0)
    tick(w, 20, up=True)
    tick(w, 20.5)
    check("5th start: one push", len(pushed), 1)
    check("it is the crash-loop alarm", pushed[0].startswith("🔌 中继反复崩溃重开"), True)
    check("it says 5 times in 30 minutes", "30 分钟内重开了 5 次" in pushed[0], True)
    check("no fresh record: says so", W.REASON_NONE in pushed[0], True)
    for k in range(5, 16):                  # still crashing every 5 minutes, to 75.5: within the hour
        tick(w, 5 * k, up=True)
        tick(w, 5 * k + 0.5)
    check("no second push within the hour", len(pushed), 1)
    tick(w, 80, up=True)
    tick(w, 80.5)                           # 60 minutes after the first push
    check("again after an hour while it still crashes", len(pushed), 2)

    print("[spread out: 5 starts over more than 30 minutes do not ring]")
    pushed.clear()
    w = W.Watch()
    for k in range(6):
        tick(w, 10 * k, up=True)
        tick(w, 10 * k + 0.5)
    check("one start every 10 minutes: nothing", len(pushed), 0)

    print("[starts at a shutdown are not counted]")
    pushed.clear()
    started.clear()
    w = W.Watch()
    SHUTTING["on"] = 1
    for k in range(6):
        tick(w, k)
    SHUTTING["on"] = 0
    check("no start, no push while Windows shuts down", (len(started), len(pushed)), (0, 0))
    W.SESSION_ENDING.write_text("x", encoding="utf-8")
    for k in range(6):
        tick(w, k)                          # within ENDING_HOLD_S of the marker
    W.SESSION_ENDING.unlink()
    check("none while the relay's session ends", (len(started), len(pushed), len(w.starts)), (0, 0, 0))

    print("[a record in Chinese is cut by bytes, so the alarm stays one group message]")
    launch.record_start_error(["run"], code, "Traceback (most recent call last):\n" + "\n".join(
        "RuntimeError: " + "读不了配置文件" * 30 for _ in range(8)))
    os.utime(DATA / launch.START_ERROR, (NOW + 30, NOW + 30))
    pushed.clear()
    w = W.Watch()
    for m in (0, 0.5, 1):
        tick(w, m)
    check("Chinese tail: under 2048 bytes", len(pushed[0].encode("utf-8")) < 2048, True)

    print("[the crash-loop record: one written during the stretch is shown]")
    pushed.clear()
    w = W.Watch()
    os.utime(DATA / launch.START_ERROR, (NOW + 10 * 60, NOW + 10 * 60))
    for k in range(5):
        tick(w, 5 * k, up=True)
        tick(w, 5 * k + 0.5)
    check("crash-loop push carries the record", (len(pushed), W.REASON_HEAD in pushed[-1]), (1, True))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_watchdog_guard():  # noqa: C901 - the whole body of the file this part was
    """The relay starts its watchdog again (watchdog_guard.py), except when it was stopped on purpose.

2026-10-11 (收尾1011): the watchdog starts the relay again, but nothing started the
watchdog again - Windows starts it once at boot (cloud run 38095391114: one start
ended during START_PENDING and stayed stopped). Now each guards the other. Checked:
the decisions (Guard.tick), the stop marker being scoped to this boot, every stopper
(switch.py stop_watchdog, estop.sh) writing the marker before `sc stop` and every
starter deleting it, and app_main starting the thread in the packaged install only.

    Formerly test_watchdog_guard.py.
    """
    import os
    import re
    import tempfile
    import time
    import types

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(ROOT / "packaging"))

    import watchdog_guard as G


    class Logs:
        def __init__(self):
            self.lines = []

        def __enter__(self):
            self.real = G.log.info, G.log.error
            G.log.info = lambda msg, *a, **k: self.lines.append(("INFO", msg % a))
            G.log.error = lambda msg, *a, **k: self.lines.append(("ERROR", msg % a))
            return self

        def __exit__(self, *exc):
            G.log.info, G.log.error = self.real


    def guard(states, start_results=(), marker=False):
        states, results, started = list(states), list(start_results), []

        def start():
            started.append(1)
            return results.pop(0) if results else ""
        g = G.Guard(lambda: states.pop(0) if len(states) > 1 else states[0], start, lambda: marker)
        return g, started


    print("[what it does on each look]")
    for label, state, marker, want in [
            ("running: nothing", ("RUNNING", "AUTO"), False, "running"),
            ("starting up: wait", ("PENDING", "AUTO"), False, "pending"),
            ("not installed (old relay, dev run): nothing", ("MISSING", "OTHER"), False, "missing"),
            ("stopped, disabled (revert): leave it", ("STOPPED", "DISABLED"), False, "disabled"),
            ("stopped, manual start type: leave it", ("STOPPED", "OTHER"), False, "disabled"),
            ("stopped, marker from this boot: leave it", ("STOPPED", "AUTO"), True, "stopped on purpose"),
            ("stopped, automatic, no marker: start it", ("STOPPED", "AUTO"), False, "started")]:
        g, started = guard([state], marker=marker)
        with Logs():
            got = g.tick()
        check(label, (got, len(started)), (want, 1 if want == "started" else 0))

    print("[a start that fails: INFO each time, one ERROR at the third, quiet until it runs]")
    g, started = guard([("STOPPED", "AUTO")] * 6 + [("RUNNING", "AUTO")] + [("STOPPED", "AUTO")] * 3,
                       ["1053 timeout"] * 9)
    with Logs() as logs:
        for _ in range(10):
            g.tick()
    errors = [m for lvl, m in logs.lines if lvl == "ERROR"]
    check("two ERRORs in two outages of 3+ failures (errwatch pushes each)", len(errors), 2)
    check("ERROR says what failed", "1053 timeout" in errors[0], True)
    check("ERROR says our side has it, not a person to go and look",
          ("已交给我们这边" in errors[0], "看一眼" in errors[0]), (True, False))
    check("recovery is INFO only", [lvl for lvl, m in logs.lines if "又在跑了" in m], ["INFO"])
    check("the ERROR comes with the third failure, not before",
          [lvl for lvl, _ in logs.lines][:5], ["INFO", "INFO", "INFO", "ERROR", "INFO"])

    print("[a look that raises counts as a failure]")
    g = G.Guard(lambda: ("STOPPED", "AUTO"), lambda: "", lambda: False)
    with Logs() as logs:
        for _ in range(3):
            g.failed("OSError()", looked=False)
    check("third raise -> one ERROR", [lvl for lvl, _ in logs.lines].count("ERROR"), 1)
    check("it says the relay could not look, not that the watchdog is down",
          "查不了" in logs.lines[-1][1] and "看门服务停了" not in logs.lines[-1][1], True)

    print("[a watchdog found stopped that nobody stopped: WARNING to the group (audit 10-12 #6)]")
    # Until 2026-10-12 a stop the relay then undid was one INFO line: the watchdog going
    # down with no stop marker has no known cause, so it is not a normal state.
    from ark_relay.features.alarm import errwatch


    class WarnLogs(Logs):
        """Logs, plus WARNINGs with their recovered mark ("WARNING" / "RECOVERED")."""

        def __enter__(self):
            super().__enter__()
            self.real_warning = G.log.warning
            G.log.warning = lambda msg, *a, **k: self.lines.append(
                ("RECOVERED" if (k.get("extra") or {}).get(errwatch.RECOVERED) else "WARNING", msg % a))
            return self

        def __exit__(self, *exc):
            G.log.warning = self.real_warning
            super().__exit__(*exc)


    g, started = guard([("STOPPED", "AUTO"), ("RUNNING", "AUTO")])
    with WarnLogs() as logs:
        got = [g.tick(), g.tick()]
    check("started, then running", got, ["started", "running"])
    check("one WARNING (pushed), saying it was started again", [(lvl, "重新打开" in m) for lvl, m in logs.lines
                                                                 if lvl != "INFO"], [("WARNING", True)])

    g, started = guard([("STOPPED", "AUTO")] * 2 + [("RUNNING", "AUTO")], ["1053 timeout", ""])
    with WarnLogs() as logs:
        got = [g.tick() for _ in range(3)]
    check("a failed start, then one that worked", got, ["start failed", "started", "running"])
    check("the stop is pushed once, at the first look, with why the start failed",
          [(lvl, "1053 timeout" in m) for lvl, m in logs.lines if lvl != "INFO"], [("WARNING", True)])

    g, started = guard([("STOPPED", "AUTO")] * 3, ["1053 timeout"] * 3)
    with WarnLogs() as logs:
        for _ in range(3):
            g.tick()
    check("three failed starts: the WARNING at the first look, the ERROR at the third",
          [lvl for lvl, _ in logs.lines if lvl != "INFO"], ["WARNING", "ERROR"])

    print("[a look that raised, then a look that worked: recovered, one red item, not pushed]")
    g, started = guard([("RUNNING", "AUTO")])
    with WarnLogs() as logs:
        g.failed("OSError()", looked=False)
        g.tick()
    check("one WARNING marked recovered, saying the relay could look again",
          [(lvl, "查不了" in m) for lvl, m in logs.lines if lvl != "INFO"], [("RECOVERED", True)])
    g, started = guard([("RUNNING", "AUTO")])
    with WarnLogs() as logs:
        for _ in range(3):
            g.failed("OSError()", looked=False)
        g.tick()
    check("after the ERROR was pushed, the end is not a second report",
          [lvl for lvl, _ in logs.lines if lvl != "INFO"], ["ERROR"])

    print("[the marker counts only when written since the boot]")
    with tempfile.TemporaryDirectory() as d:
        m = Path(d) / G.MARKER
        check("no marker", G.marker_this_boot(m, time.time() - 100), False)
        m.write_text("x")
        check("written after the boot", G.marker_this_boot(m, time.time() - 100), True)
        old = time.time() - 3600
        os.utime(m, (old, old))
        check("left from before the boot (crashed installer, earlier estop): ignored",
              G.marker_this_boot(m, time.time() - 100), False)

    print("[one marker, the same on every side]")
    fake = {}
    for name in ("pywintypes", "win32service", "win32serviceutil"):
        fake[name] = sys.modules.get(name)
    pywintypes = types.ModuleType("pywintypes")
    pywintypes.error = type("error", (Exception,), {})
    win32service = types.ModuleType("win32service")
    win32service.SERVICE_STOPPED, win32service.SERVICE_RUNNING = 1, 4
    win32serviceutil = types.ModuleType("win32serviceutil")
    sys.modules.update(pywintypes=pywintypes, win32service=win32service, win32serviceutil=win32serviceutil)
    import switch

    check("switch.py's marker is the guard's (data folder, same name)",
          (switch.WATCHDOG_MARKER.name, str(switch.WATCHDOG_MARKER.parent)),
          (G.MARKER, r"C:\ProgramData\ark-relay"))
    estop = (ROOT / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8")
    stop_ps = estop[estop.index('PS_PKG_STOP="'):estop.index('PS_PKG_START="')]
    start_ps = estop[estop.index('PS_PKG_START="'):]
    marker_ps = r"'C:\\ProgramData\\ark-relay\\" + G.MARKER + "'"
    check("estop writes it", f"Set-Content -Path {marker_ps}" in stop_ps, True)
    check("estop writes it before sc stop",
          stop_ps.find("Set-Content -Path") < stop_ps.find("sc.exe stop ArkRelayWatchdog"), True)
    check("estop --restore deletes it before sc start",
          0 <= start_ps.find(f"Remove-Item -Path {marker_ps}") < start_ps.find("sc.exe start ArkRelayWatchdog"),
          True)

    print("[switch.py: marker before sc stop, deleted before sc start]")
    with tempfile.TemporaryDirectory() as d:
        switch.WATCHDOG_MARKER = Path(d) / G.MARKER
        steps = []
        states = [4, 1]          # RUNNING once (the relay raced it), then STOPPED

        def run(*cmd):
            steps.append(("marker" if switch.WATCHDOG_MARKER.exists() else "no marker",) + tuple(map(str, cmd)))
            return 0
        real_run, real_sleep = switch.run, switch.time.sleep
        switch.run, switch.time.sleep = run, lambda s: None
        win32serviceutil.QueryServiceStatus = lambda name: (0, states.pop(0) if len(states) > 1 else states[0])
        try:
            switch.stop_watchdog()
            check("every sc stop with the marker already there",
                  [s[0] for s in steps], ["marker", "marker"])
            check("stopped again after it came back", [s[1:3] for s in steps], [("sc.exe", "stop")] * 2)
            steps.clear()
            win32serviceutil.QueryServiceStatus = lambda name: (0, 4)
            check("start_watchdog -> 0", switch.start_watchdog(), 0)
            check("marker gone before sc start", steps[0][:3], ("no marker", "sc.exe", "start"))
        finally:
            switch.run, switch.time.sleep = real_run, real_sleep

    print("[the real start counts only a watchdog that comes up and stays (review round 10 #30)]")
    # Only the two Windows calls are stubbed: StartService and QueryServiceStatus.
    # 2 = START_PENDING, 1 = STOPPED, 4 = RUNNING (winsvc.h).


    class Clock:
        def __init__(self):
            self.t = 0.0

        def now(self):
            return self.t

        def wait(self, seconds):
            self.t += seconds
            return False


    def fake_service(states, start_error=None):
        """StartService records the call (raising start_error if given); each status query
    returns the next state, the last one from then on."""
        calls = {"start": 0}
        states = list(states)

        def start_service(name):
            calls["start"] += 1
            if start_error is not None:
                exc = pywintypes.error()
                exc.winerror, exc.strerror = start_error, {1056: "already running"}.get(start_error, "disabled")
                raise exc
        win32serviceutil.StartService = start_service
        win32serviceutil.QueryServiceStatus = lambda name: (0, states.pop(0) if len(states) > 1 else states[0])
        return calls


    def real_start(states, start_error=None):
        clock = Clock()
        calls = fake_service(states, start_error)
        return G._start(clock.wait, clock.now), calls["start"], clock.t


    got, starts, waited = real_start([2, 2, 1])
    check("START_PENDING then STOPPED (cloud run 38095391114) is a failure, not a start",
          (got, starts), ("开到一半自己停了", 1))
    got, starts, waited = real_start([2, 4])
    check("RUNNING and still RUNNING STEADY_S later: started", got, "")
    check("... after waiting the steady time, not at the first RUNNING", waited >= G.STEADY_S, True)
    check("RUNNING, then STOPPED within the steady time: a failure",
          real_start([2, 4, 4, 1])[0], "刚跑起来就又停了")
    check("never leaves START_PENDING: a failure at START_WAIT_S",
          real_start([2])[:1] + (real_start([2])[2] >= G.START_WAIT_S,),
          (f"开了 {G.START_WAIT_S} 秒还没跑起来", True))
    check("1056 (already starting) is watched too, and ends stopped: a failure",
          real_start([2, 1], start_error=1056)[0], "开到一半自己停了")
    check("another start error is the failure itself",
          real_start([1], start_error=1058)[0], "1058 disabled")
    fake_service([2])
    check("relay stopping while it waits: neither success nor failure",
          G._start(lambda s: True, Clock().now), None)

    print("[the guard over the real start: a watchdog that starts then stops reaches the ERROR]")


    def guard_over_real_start(looks, service_each_start):
        """looks: what each look finds; service_each_start: the states a start then goes through."""
        looks, clock = list(looks), Clock()

        def start():
            fake_service(service_each_start)
            return G._start(clock.wait, clock.now)
        return G.Guard(lambda: looks.pop(0) if len(looks) > 1 else looks[0], start, lambda: False)


    g = guard_over_real_start([("STOPPED", "AUTO")], [2, 2, 1])
    with Logs() as logs:
        got = [g.tick() for _ in range(3)]
    check("every start stops during START_PENDING: three failures", got, ["start failed"] * 3)
    errors = [m for lvl, m in logs.lines if lvl == "ERROR"]
    check("one ERROR at the third, with the reason", len(errors) == 1 and "开到一半自己停了" in errors[0], True)

    g = guard_over_real_start([("STOPPED", "AUTO")], [2, 4])
    with Logs() as logs:
        got = [g.tick() for _ in range(4)]
    check("comes up and stays, but is stopped again at every look: counted from the second",
          got, ["started", "started again", "started again", "started again"])
    check("... one ERROR, at the fourth look", [lvl for lvl, _ in logs.lines].count("ERROR"), 1)

    g = guard_over_real_start([("STOPPED", "AUTO"), ("RUNNING", "AUTO"), ("STOPPED", "AUTO")], [2, 4])
    with Logs() as logs:
        got = [g.tick() for _ in range(3)]
    check("a start that is still running at the next look: no failure, a later stop starts afresh",
          (got, g.fails), (["started", "running", "started"], 0))

    looks = [("STOPPED", "AUTO"), ("STOPPED", "AUTO"), ("STOPPED", "AUTO")]
    marks = [False, True, False]
    g = guard_over_real_start(looks, [2, 4])
    g.marker_this_boot = lambda: marks.pop(0)
    with Logs() as logs:
        got = [g.tick() for _ in range(3)]
    check("a look in between (stopped on purpose) means the next start is not 'stopped again'",
          (got, g.fails), (["started", "stopped on purpose", "started"], 0))
    check("the group ERROR does not claim it is down after a start that worked: it says found stopped",
          "留不住" in G.ALERT_GAVE_UP and "发现它停了" in G.ALERT_GAVE_UP, True)

    for name, mod in fake.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod

    src = (ROOT / "packaging" / "switch.py").read_text(encoding="utf-8")
    check("no other starter in switch.py (each goes through start_watchdog)",
          re.findall(r'run\("sc\.exe", "start", WATCHDOG\)', src), ['run("sc.exe", "start", WATCHDOG)'])

    print("[app_main starts the guard, packaged install only, stopping with the relay]")
    app = (RELAY / "app_main.py").read_text(encoding="utf-8")
    gate = app.index("if pkg_layout.app_root(HERE) is not None:")
    body = app[gate:app.index("threading.Thread(target=_end_session_window")]
    check("thread inside the packaged-install gate",
          "target=watchdog_guard.run, args=(host.stop_event, DATA)" in body, True)
    check("logger under ark. (errwatch hooks ark)", G.log.name.startswith("ark."), True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_watchdog_guard_missing():
    """A watchdog service that vanishes after the relay saw it installed is pushed once.

Audit s24 F3 (10-13): Guard.tick returned "missing" with no log line at every look,
right for a machine where the service was never installed (a dev run, the old relay),
but on the game machine the service is installed (switch.log 10-11 10:04:35). If it
were deleted, nothing would start the relay again and nobody would hear of it. Now the
first look that finds it MISSING after a look that found it installed logs one WARNING
(errwatch pushes it), unless a stop marker from this boot says it was taken down on
purpose (switch.py uninstall stops it with the marker before removing it).

    Formerly test_watchdog_guard_missing.py.
    """

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    import watchdog_guard as G


    class Logs:
        def __enter__(self):
            self.lines = []
            self.real = G.log.info, G.log.warning, G.log.error
            G.log.info = lambda msg, *a, **k: self.lines.append(("INFO", msg % a))
            G.log.warning = lambda msg, *a, **k: self.lines.append(("WARNING", msg % a))
            G.log.error = lambda msg, *a, **k: self.lines.append(("ERROR", msg % a))
            return self

        def __exit__(self, *exc):
            G.log.info, G.log.warning, G.log.error = self.real


    def run(states, marker=False):
        states = list(states)
        g = G.Guard(lambda: states.pop(0), lambda: "", lambda: marker)
        with Logs() as logs:
            got = [g.tick() for _ in range(len(states))]
        return got, [lvl for lvl, _ in logs.lines if lvl != "INFO"], logs.lines


    R, M, S = ("RUNNING", "AUTO"), ("MISSING", "OTHER"), ("STOPPED", "AUTO")

    print("[never installed (dev run, old relay): quiet]")
    got, loud, _ = run([M, M, M])
    check("missing at every look", got, ["missing"] * 3)
    check("no WARNING or ERROR", loud, [])

    print("[installed, then gone: one WARNING, not one per look]")
    got, loud, lines = run([R, M, M, M])
    check("looks", got, ["running", "missing", "missing", "missing"])
    check("one WARNING", loud, ["WARNING"])
    check("it says the service is gone and our side has it",
          [("不见了" in m and "已交给我们这边" in m) for lvl, m in lines if lvl == "WARNING"], [True])

    print("[seen stopped counts as installed too]")
    got, loud, _ = run([S, M])
    check("STOPPED_UNASKED, then one WARNING for the gone service", loud, ["WARNING", "WARNING"])

    print("[back, then gone again: a second WARNING]")
    got, loud, _ = run([R, M, R, M])
    check("two WARNINGs", loud, ["WARNING", "WARNING"])

    print("[removed on purpose (stop marker from this boot): quiet]")
    got, loud, _ = run([R, M, M], marker=True)
    check("no WARNING", loud, [])

    if fails:
        print("FAIL:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_watchdog_push_delivery():
    """The watchdog's own group alarm counts as sent only when the group bot took it.

s26 audit, finding 1 (2026-10-13): packaging/watchdog/ark_watchdog.py `push` sent once,
caught only OSError and logged 「进群」 on any HTTP 200, and every caller marked its
alarm as sent whatever happened. So:
  a. a WeCom refusal inside HTTP 200 (errcode != 0, the way relay/ark_relay/core/notify.py
     reads it) or a transport error right after boot (relay.log 10-12 08:45:26
     WinError 10051, the network not up yet) lost the one 「中继停了」 alarm for good;
  b. http.client.HTTPException is not an OSError: it escaped push(), the tick logged
     「检查出错」, the flag stayed False and the alarm was re-sent every 30 s with no end.
Now push() returns whether the bot answered errcode 0, an undelivered alarm is tried
again on the next looks, and after PUSH_TRIES failed pushes in one stretch the
watchdog gives up and says so in watchdog.log.

Runs on any OS: pywin32 is faked, urlopen is replaced at the HTTP layer.

    Formerly test_watchdog_push_delivery.py.
    """
    import http.client
    import io
    import json
    import os
    import types

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))

    DATA = tmpdir()
    os.environ["ARK_HOME"] = str(DATA)
    (DATA / ".env").write_text("WECOM_BOT_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test\n",
                               encoding="utf-8")


    def _module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m


    class _PyError(Exception):
        pass


    _module("pywintypes", error=_PyError)
    _module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
    _module("win32api", GetSystemMetrics=lambda i: 0, CloseHandle=lambda h: None)
    _module("win32event", CreateEvent=lambda *a: None, SetEvent=lambda e: None, WaitForSingleObject=lambda *a: 0,
            WAIT_TIMEOUT=258)
    _module("win32service", SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_PRESHUTDOWN=0xF,
            SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)
    _module("win32serviceutil", ServiceFramework=object)
    _module("win32ts")

    import ark_watchdog as W


    class _Resp:
        def __init__(self, status, obj):
            self.status = status
            self._raw = io.BytesIO(json.dumps(obj).encode("utf-8"))

        def read(self):
            return self._raw.read()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    answers = []      # what each urlopen call does, in order: a reply or an exception
    posts = []


    def fake_urlopen(req, timeout=None):
        posts.append(json.loads(req.data.decode("utf-8"))["text"]["content"])
        a = answers.pop(0) if answers else _Resp(200, {"errcode": 0, "errmsg": "ok"})
        if isinstance(a, BaseException):
            raise a
        return a


    def refused():
        return _Resp(200, {"errcode": 45009, "errmsg": "api freq out of limit"})


    def dropped():
        # BadStatusLine is an HTTPException and not an OSError (RemoteDisconnected is both).
        return http.client.BadStatusLine("")


    W.urllib.request.urlopen = fake_urlopen
    logged = []
    W._log = logged.append
    running = {"on": False}
    logon = {"on": True}
    W.main_running = lambda: running["on"]
    W.someone_logged_on = lambda: logon["on"]
    W.start_main = lambda: True
    # No start record in these stretches: the alarm says so (REASON_NONE).
    W.START_ERROR = DATA / "no-start-error.txt"
    CAP = getattr(W, "PUSH_TRIES", 3)


    def new_watch():
        try:
            return W.Watch()
        except TypeError:               # the old signature, Watch(now)
            return W.Watch(0.0)


    def deliver(text):
        """push() as a bool; the old one returned None and let HTTPException out."""
        try:
            return W.push(text)
        except http.client.HTTPException as exc:
            return f"raised {type(exc).__name__}"


    print("[push(): delivered only on HTTP 200 with errcode 0]")
    answers[:] = [_Resp(200, {"errcode": 0, "errmsg": "ok"})]
    check("errcode 0: delivered", deliver("x"), True)
    answers[:] = [refused()]
    check("HTTP 200 with errcode 45009: not delivered", deliver("x"), False)
    check("... and the log says it did not get through", logged[-1].startswith("进群失败"), True)
    answers[:] = [dropped()]
    check("http.client.HTTPException is caught: not delivered", deliver("x"), False)
    answers[:] = [OSError(10051, "A socket operation was attempted to an unreachable network")]
    check("network not up (WinError 10051): not delivered", deliver("x"), False)
    answers[:] = [_Resp(200, "not a dict")]
    check("an answer that is not WeCom's: not delivered", deliver("x"), False)

    print("\n[「中继停了」 refused once: tried again at the next look, flag set only once it got through]")
    posts.clear()
    w = new_watch()
    answers[:] = [refused()]
    for t in (0, 30, 60):
        w.tick(t, wall=1_000_000.0 + t)
    check("3rd start: one push, refused", len(posts), 1)
    check("the alarm is not marked sent", w.alerted, False)
    w.tick(90, wall=1_000_090.0)
    check("next look: pushed again", len(posts), 2)
    check("delivered this time: marked sent", w.alerted, True)
    w.tick(120, wall=1_000_120.0)
    check("no third push once delivered", len(posts), 2)

    print(f"\n[「中继停了」 never gets through: {CAP} pushes, then give up and say so]")
    posts.clear()
    logged.clear()
    w = new_watch()
    answers[:] = [refused() for _ in range(10)]
    for k in range(10):
        w.tick(30 * k, wall=1_000_000.0 + 30 * k)
    check(f"pushed exactly {CAP} times", len(posts), CAP)
    check("given up: no more pushes this stretch", w.alerted, True)
    check("the give-up is in watchdog.log", any("不再重试" in x for x in logged), True)
    running["on"] = True
    w.tick(2900, wall=1_002_900.0)     # up again, past LOOP_WINDOW_S: no crash-loop alarm mixed in
    running["on"] = False
    answers[:] = [refused()]
    for k in range(100, 103):
        w.tick(30 * k, wall=1_000_000.0 + 30 * k)
    check("a new stretch after the relay ran again: tried again", len(posts), CAP + 1)

    print("\n[HTTPException from the bot: no endless re-send every 30 s]")
    posts.clear()
    w = new_watch()
    answers[:] = [dropped() for _ in range(20)]
    for k in range(20):
        try:
            w.tick(30 * k, wall=1_000_000.0 + 30 * k)
        except http.client.HTTPException:
            pass                        # what SvcDoRun's 「检查出错」 caught on the old code
    check(f"bounded by {CAP}", len(posts), CAP)

    print("\n[「没人登录」: same rule]")
    posts.clear()
    logon["on"] = False
    w = new_watch()
    answers[:] = [dropped(), refused()]
    for t in range(0, W.NOBODY_LIMIT_S + 30 * 5, 30):
        try:
            w.tick(float(t), wall=1_000_000.0 + t)
        except http.client.HTTPException:
            pass
    check("two failed, the third delivered", len(posts), 3)
    check("marked sent", w.nobody_alerted, True)
    logon["on"] = True

    print("\n[crash loop: refused, tried again at the next start]")
    posts.clear()
    w = new_watch()
    answers[:] = [refused()]
    for k in range(6):
        running["on"] = True
        w.tick(300.0 * k, wall=1_000_000.0 + 300 * k)
        running["on"] = False
        w.tick(300.0 * k + 30, wall=1_000_030.0 + 300 * k)
    check("5th start refused, 6th start delivered", (len(posts), w.loop_alerted_at), (2, 300.0 * 5 + 30))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_gh_watchdog():
    """The GitHub Actions boot watchdog (scripts/watchdog.py; queue/watchdog.json has it off since
08-20): a daytime run by hand judges tonight's checks as not due, and a watchdog that cannot
ask Tailscale says so (audit 11-08 A-25; dispatch relay-opt-round5-1108 R5-02).

Pinned here:
* today_at: 00:30 (a 23:10 check run late past midnight) still means last night's 23:10;
  10:00 by hand means tonight's 23:10 (until 11-08: last night's, so 「还在线」 was judged);
* main(): Tailscale's API failing is one 「🔌 开机监督自身异常」 alert and exit 1 on a
  scheduled run, a print only on a run by hand (no CHECK_CRON).

    Formerly test_gh_watchdog.py.
    """
    import importlib.util
    import json
    from datetime import datetime

    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("gh_watchdog", ROOT / "scripts" / "watchdog.py")
    wd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wd)


    def srv(d, hh, mm):
        return datetime(2026, 11, d, hh, mm, tzinfo=wd.SERVER_TZ)


    print("[today_at：凌晨迟到的检查算前一晚，白天手动跑算今晚]")
    check("11-09 00:30 查 23:10：是 11-08 那晚的", wd.today_at("23:10", srv(9, 0, 30)), srv(8, 23, 10))
    check("11-08 10:00 查 23:10：是今晚的（还没到点）", wd.today_at("23:10", srv(8, 10, 0)), srv(8, 23, 10))
    check("11-08 10:00 查 08:40：今天早上的", wd.today_at("08:40", srv(8, 10, 0)), srv(8, 8, 40))
    check("UTC 时间传进来也按北京时间算（11-08 02:00 UTC = 10:00 北京）",
          wd.today_at("23:10", datetime(2026, 11, 8, 2, 0, tzinfo=wd.timezone.utc)), srv(8, 23, 10))
    last = srv(8, 9, 50)
    check("白天手动跑：晚上收工那项不判（之前会说「该关机了还在线」）",
          wd.run_check("shutdown", {"label": "晚上收工", "boot_since": "21:15", "min_off": "21:50", "off_by": "22:35"},
                       last, srv(8, 10, 0).astimezone(wd.timezone.utc)), None)

    print("\n[问不到 Tailscale：报一条「开机监督自身异常」，退出码 1；手动跑只打印]")
    cfg = tmpdir() / "watchdog.json"
    cfg.write_text(json.dumps({"enabled": True, "pause_until": "2000-01-01", "device": "ins",
                               "checks": {"20 1 * * *": {"kind": "boot", "label": "早上开机", "since": "08:40"}}}),
                   encoding="utf-8")
    sent = []
    saved = (wd.CONFIG, wd.alert, wd.tailscale_last_seen, dict(wd.os.environ))


    def broken(device):
        raise RuntimeError("缺 TS_OAUTH_CLIENT_ID / TS_OAUTH_SECRET secrets")


    wd.CONFIG, wd.alert, wd.tailscale_last_seen = cfg, (lambda t, b: sent.append((t, b)) or True), broken
    try:
        wd.os.environ["CHECK_CRON"] = "20 1 * * *"
        rc = wd.main()
        check("定时跑：退出码 1", rc, 1)
        check("……推了一条，标题是开机监督自身异常", [t for t, _b in sent], ["🔌 开机监督自身异常"])
        check("……正文说了原因", "TS_OAUTH" in sent[0][1], True)
        sent.clear()
        wd.os.environ.pop("CHECK_CRON")
        check("手动跑：退出码 1", wd.main(), 1)
        check("……不推送", sent, [])
    finally:
        wd.CONFIG, wd.alert, wd.tailscale_last_seen = saved[:3]
        wd.os.environ.clear()
        wd.os.environ.update(saved[3])


if __name__ == "__main__":
    sys.exit(run_parts([_part_watchdog_copy, _part_watchdog_crashloop, _part_watchdog_guard, _part_watchdog_guard_missing, _part_watchdog_push_delivery, _part_gh_watchdog]))
