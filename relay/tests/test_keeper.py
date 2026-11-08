"""The AUTO-MAS keeper: blind back-off, exits, one hold.

One part per former file, each run on its own (tests/_parts.py): test_keeper_blind_backoff.py, test_keeper_exit.py, test_keeper_hold_once.py.
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


def _part_keeper_blind_backoff():
    """The keeper does not back off when it revived nothing (audit s15 #1, 2026-10-13).

Machine record (tests/fixtures/keeper_blind_20261010.log, relay.log 10-10 16:14:07):
the process table could not be read (「读得到每个程序是怎么启动的…读不到」) while
AUTO-MAS answered (「✓ 调度程序有应答」). Five relay starts from 16:14 to 17:21 got no
backend handle. In that state _automas_running() is True (it falls back to the
API), nothing is revived, and every handle-less check still doubled revive_wait:
checks at 180, 360, 720, 1440, 2880 s ... out to every 30 minutes, with not one
keeper line in the log. A backend that died then was found up to 30 minutes late.

Now: the wait doubles only after a real revival; a backend that is up but cannot
be attached is checked every procwatch.AUTOMAS_CHECK_SECONDS, and that is said
once at INFO.

    Formerly test_keeper_blind_backoff.py.
    """
    import itertools
    import logging
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


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                  "win32evtlog", "win32gui"):
        sys.modules.setdefault(_name, _Stub(_name))

    import time

    import boot_stages
    from ark_relay.features.host import automas_keeper, automas_procs, procwatch
    from ark_relay.features.phone import commands


    # The machine's state, read from its own self-check lines.
    lines = (Path(__file__).parent / "fixtures" / "keeper_blind_20261010.log").read_text(encoding="utf-8").splitlines()
    procs_unreadable = any("读得到每个程序是怎么启动的" in ln and "读不到" in ln for ln in lines)
    api_answers = any("✓ 调度程序有应答" in ln for ln in lines)
    check("record: process table unreadable", procs_unreadable, True)
    check("record: API answering", api_answers, True)

    clock = [1000.0]
    time.monotonic = lambda: clock[0]
    automas_procs._python_processes = lambda: None if procs_unreadable else []
    commands.mas_up = lambda: api_answers
    procwatch._start_process_watch = lambda evt, alive, log: True
    revives = []
    boot_stages._revive_automas = lambda: revives.append(clock[0])


    class _Keep(logging.Handler):
        def __init__(self):
            super().__init__()
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage()))


    keep = _Keep()
    log = automas_keeper.log
    log.addHandler(keep)
    log.setLevel(logging.INFO)


    class _Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, *a, **k):
            self.sent.append(title)


    print("[进程表读不到、接口有应答：没拉起过就不退避，按活性检查间隔查]")
    k = automas_keeper._AutomasKeeper(log, _Notifier())
    check("no handle at start", k.handle, None)
    keep.rows.clear()
    checks = []
    start = clock[0]
    while clock[0] - start < 2 * 3600:
        clock[0] += k.cap_wait(3600.0)
        due = k.revive_deadline
        k.check(False, clock[0])
        if due is not None and clock[0] >= due:
            checks.append(clock[0])
    gaps = [round(b - a) for a, b in itertools.pairwise(checks)]
    check("checks within the first two hours (>= 40, was 5)", len(checks) >= 40, True)
    check("no gap longer than the liveness interval", max(gaps) if gaps else None, procwatch.AUTOMAS_CHECK_SECONDS)
    check("nothing revived", revives, [])
    said = [m for lv, m in keep.rows if "挂不上它的进程句柄" in m]
    check("said once", len(said), 1)
    check("at INFO", [lv for lv, m in keep.rows if "挂不上它的进程句柄" in m], ["INFO"])

    print("[真拉起过、没起来：照旧翻倍退避]")
    automas_procs._python_processes = lambda: []
    commands.mas_up = lambda: False
    automas_procs._installer_running = lambda: False
    automas_procs._automas_shell_running = lambda: False
    clock[0] = 50000.0
    k2 = automas_keeper._AutomasKeeper(log, _Notifier())
    waits = []
    for _ in range(4):
        clock[0] = k2.revive_deadline
        k2.check(False, clock[0])
        waits.append(round(k2.revive_deadline - clock[0]))
    check("180, 360, 720, 1440", waits, [180, 360, 720, 1440])
    check("four revivals", len(revives), 4)

    print("[拦着没拉（安装程序开着）：不翻倍]")
    automas_procs._installer_running = lambda: True
    revives.clear()
    clock[0] = 90000.0
    k3 = automas_keeper._AutomasKeeper(log, _Notifier())
    waits = []
    for _ in range(3):
        clock[0] = k3.revive_deadline
        k3.check(False, clock[0])
        waits.append(round(k3.revive_deadline - clock[0]))
    check("held: the wait stays 180", waits, [180, 180, 180])
    check("held: nothing revived", revives, [])


def _part_keeper_exit():  # noqa: C901 - the whole body of the file this part was
    """The AUTO-MAS keeper: an exit while the machine goes down is INFO with its reason; any other exit is decided by whether the backend comes back.

2026-10-06 log sweep (08-20 to 10-05): 「AUTO-MAS 后端退出了」 68 times and
「AUTO-MAS 后端不在，正在拉起（第 1 次）」 62 times, every one at WARNING. The keeper
never asked whether the machine was going down - and the relay powers the machine
off after every queue (`shutdown /s /t 60`), so Windows closing the session took
the backend with it, the keeper read that as a crash and started a revival
against a closing session. Every WARNING now reaches the group (2026-10-06).

The going-down signals are errwatch's (mark_stopping: the relay's power-off and
SvcStop/SvcShutdown; Windows' SM_SHUTTINGDOWN), and the keeper waits a moment
for one when the exit comes first. Time is a virtual clock: nothing here waits.

Since the user's rule of 2026-10-06 05:07 (「报错后自己好了的，只进日报、不进群」)
any other exit is INFO with its evidence and decided later: the backend back
(the relay's revival, or by itself after an update) -> one WARNING marked
errwatch.recovered(), the daily report only; not back at the
REVIVE_ALERT_AFTER-th check -> 「🔌 AUTO-MAS 启动不起来」 (alert=True) after three
failed revivals, a WARNING while the relay holds off (an installer on screen);
not back when the service stops -> a WARNING. A real errwatch handler on each
keeper's logger shows what is pushed and what the daily report lists.

    Formerly test_keeper_exit.py.
    """
    import logging
    import subprocess
    import tempfile
    import time
    import types
    from datetime import datetime

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


    SYNCHRONIZE = 0x00100000
    closed, opened = [], []
    exit_codes = {}

    w32api = _Stub("win32api")
    w32api.CloseHandle = lambda h: closed.append(h)


    def open_process(access, inherit, pid):
        opened.append(access)
        if access != SYNCHRONIZE and refuse_query[0]:
            raise OSError("access denied")
        return f"handle:{pid}"


    w32api.OpenProcess = open_process
    refuse_query = [False]
    w32con = _Stub("win32con")
    w32con.SYNCHRONIZE = SYNCHRONIZE
    w32process = _Stub("win32process")


    def get_exit_code(h):
        if h not in exit_codes:
            raise OSError("no query right")
        return exit_codes[h]


    w32process.GetExitCodeProcess = get_exit_code
    w32event = _Stub("win32event")
    w32event.CreateEvent = lambda *a: object()
    w32event.SetEvent = lambda h: None

    FAKES = {"win32api": w32api, "win32con": w32con, "win32process": w32process, "win32event": w32event}
    for name in ("win32serviceutil", "win32service", "win32file", "servicemanager", "win32security",
                 "win32ts", "win32profile", "wmi", "pythoncom", "win32com", "win32com.client"):
        FAKES[name] = _Stub(name)
    saved = {k: sys.modules.get(k) for k in [*FAKES, "service"]}
    sys.modules.update(FAKES)
    sys.modules.pop("service", None)
    import boot_stages
    import service  # a fresh copy built on the fakes above
    from ark_relay.features.host import automas_keeper, automas_procs, dirwatch, mainloop, procwatch, shutdown_signs
    from ark_relay.features.alarm import errwatch
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ

    # The backend's API answers unless a case says otherwise (清单-1108 A-06: a handle is
    # adopted only once the API answers; the cases on that are at the end).
    api = {"up": True}
    automas_keeper._api_up = lambda: api["up"]


    def set_time(t):
        """service.py's code now lives in several modules, each reading its own `time`; swap it in all."""
        for m in (service, shutdown_signs, procwatch, dirwatch, automas_keeper, mainloop):
            m.time = t


    class VClock:
        def __init__(self):
            self.now, self.due = 5000.0, []

        def monotonic(self):
            return self.now

        def sleep(self, s):
            self.now += max(0.0, s)
            for item in [d for d in self.due if d[0] <= self.now]:
                self.due.remove(item)
                item[1]()

        def at(self, delay, fn):
            self.due.append((self.now + delay, fn))

        def time(self):
            return self.now


    TASKS = {"plain": b"explorer.exe 4 Console", "setup": b"AUTO-MAS-Setup.exe 1234 Console",
             "shell": b"AUTO-MAS.exe 18864 Console"}
    tasks = {"list": TASKS["plain"]}


    def fake_run(cmd, **kw):
        key = " ".join(cmd).lower()
        if key.startswith("tasklist /fi imagename eq auto-mas.exe"):
            out = TASKS["shell"] if b"auto-mas.exe" in tasks["list"].lower() else b"INFO: No tasks are running"
        elif key.startswith("tasklist"):
            out = tasks["list"]
        else:
            out = b""
        return types.SimpleNamespace(stdout=out, returncode=0)


    class Records(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def at(self, level):
            return [r.getMessage() for r in self.records if r.levelno == level]


    class Notifier:
        def __init__(self):
            self.sent = []
            self.calls = []

        def send(self, title, body, **k):
            self.sent.append(title)
            self.calls.append((title, body, k.get("alert", False)))
            return []


    class Pushes:
        """errwatch's notifier: what its WARNING / ERROR records pushed to the group."""

        def __init__(self):
            self.sent = []

        def send(self, title, body, **k):
            self.sent.append((title, body))
            return []


    def pushed(rec, want=0, secs=3.0):
        """The group pushes errwatch made from the keeper's records (waits for its push thread)."""
        end = time.time() + secs
        while time.time() < end and (rec.errwatch.pending() or len(rec.pushes.sent) < want):
            time.sleep(0.02)
        time.sleep(0.1)
        return [b for _, b in rec.pushes.sent]


    def stop(k):
        """The service's stop reaching the keeper (absent before 2026-10-06: nothing happens)."""
        getattr(k, "stopping", lambda: None)()


    def daily(rec):
        return errwatch.daily_section(rec.state, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))


    orig = (errwatch.system_shutting_down, procwatch.time, subprocess.run, boot_stages._revive_automas,
            automas_procs._automas_running, automas_procs._automas_handle, procwatch._start_process_watch,
            automas_procs._python_processes)
    errwatch.system_shutting_down = lambda: False
    subprocess.run = fake_run
    events = {"xml": []}      # the System log's 1074 / 1075 events, newest first
    shutdown_signs._shutdown_event_xml = lambda *a: events["xml"]


    def ev1074(when_utc, process, user):
        """A User32 1074 as EvtRender gives it (layout per the event's param1..param7)."""
        params = [process, "INS", "Other (Unplanned)", "0x0", "power off", "", user]
        data = "".join(f'<Data Name="param{i}">{v}</Data>' for i, v in enumerate(params, 1))
        return ('<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
                '<Provider Name="User32"/><EventID Qualifiers="32768">1074</EventID>'
                f'<TimeCreated SystemTime="{when_utc}"/><Channel>System</Channel></System>'
                f'<EventData>{data}</EventData></Event>')


    def ev1075(when_utc):
        return ('<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
                '<Provider Name="User32"/><EventID Qualifiers="32768">1075</EventID>'
                f'<TimeCreated SystemTime="{when_utc}"/></System><EventData><Data Name="param1">x</Data>'
                '</EventData></Event>')
    revived = []
    boot_stages._revive_automas = lambda: revived.append(procwatch.time.now)


    def keeper(handle="handle:21932"):
        """A keeper holding `handle`, as _loop builds it (its own __init__, WMI listener faked)."""
        rec = Records()
        log = logging.getLogger(f"ark.test.keeper.{len(revived)}.{id(rec)}")
        log.propagate = False
        log.setLevel(logging.DEBUG)
        log.addHandler(rec)
        rec.state, rec.pushes = Path(tempfile.mkdtemp(prefix="keeper-exit-")), Pushes()
        rec.errwatch = errwatch.ErrorKindAlert(rec.pushes, state_dir=rec.state, known={}, pace=0, retry=(0.05,))
        log.addHandler(rec.errwatch)
        automas_procs._automas_handle = lambda: handle
        procwatch._start_process_watch = lambda evt, alive, lg: True
        k = automas_keeper._AutomasKeeper(log, Notifier())
        return k, rec


    def run_exit(code, task_list="plain", down=None, down_after=None, running_after=False, down_after_fn=None):
        """The backend's handle signals; returns (records, revivals)."""
        exit_codes.clear()
        if code is not None:
            exit_codes["handle:21932"] = code
        tasks["list"] = TASKS[task_list]
        revived.clear()
        vt = VClock()
        set_time(vt)
        k, rec = keeper()
        if down:
            down()
        if down_after is not None:
            vt.at(down_after, down_after_fn or errwatch.mark_stopping)
        automas_procs._automas_running = lambda: running_after
        automas_procs._automas_handle = lambda: None
        try:
            k.check(True, vt.now)
        finally:
            set_time(orig[1])
            errwatch._stopping.clear()
            errwatch._relay_poweroff[0] = lambda: False
        return rec, list(revived), k


    def relay_poweroff():
        """The relay itself issued the machine power-off (errwatch.relay_shutdown_issued)."""
        errwatch._relay_poweroff[0] = lambda: True


    def first(msg):
        return msg.splitlines()[0]


    try:
        print("[the relay's own power-off (issued 60 s before): INFO, no revival]")
        rec, rv, k = run_exit(0x40010004, down=relay_poweroff)
        check("no WARNING", rec.at(logging.WARNING), [])
        check("INFO says it is the relay's own power-off, with the exit code",
              any("不算故障" in m and "0x40010004" in m and "中继自己发出了关机命令" in m for m in rec.at(logging.INFO)))
        check("no revival against the closing session", rv, [])
        check("handle let go", k.handle, None)

        # Mute audit 10-12 item 10: after an exit put down to the relay's own power-off no
        # deadline was armed, so when that power-off was cancelled (「下次跑完不关机」) and the
        # machine stayed up, nothing ever revived AUTO-MAS or said it was gone.
        print("\n[the relay's power-off cancelled after the exit: the next check revives it and says so]")
        rec, rv, k = run_exit(0x40010004, down=relay_poweroff)   # run_exit puts the power-off back: cancelled
        check("a check is armed while the power-off is under way", k.revive_deadline is not None, True)
        # cap_wait reads time.monotonic(), so ask it on the virtual clock the deadline was set
        # on (a fresh VClock reads the same 5000.0 run_exit's check got). On the real clock the
        # answer depended on the machine's uptime: a Mac up for days read the deadline as long
        # past (1 s), a Windows runner booted minutes before (monotonic counts from boot there)
        # read it as over an hour away (3600 s, run 38360295330).
        vt = VClock()
        set_time(vt)
        try:
            check("so the loop wakes for it, no later than the deadline",
                  k.cap_wait(3600.0), max(1.0, (k.revive_deadline or 0) - vt.now))
            check("which is well inside the hour", k.cap_wait(3600.0) < 3600.0, True)
        finally:
            set_time(orig[1])
        vt = VClock()
        set_time(vt)
        revived.clear()
        automas_procs._automas_running = lambda: False
        try:
            k.check(False, (k.revive_deadline or 0) + 1)
        finally:
            set_time(orig[1])
        check("revived once the power-off is off", len(revived), 1)
        check("one WARNING (pushed): AUTO-MAS is not running", [("没在运行" in m) for m in rec.at(logging.WARNING)], [True])

        # 清单-1108 A-06: the relay issues its power-off from this same loop thread
        # (engine.tick -> shutdown._maybe_shutdown), so nothing can set the flag while the
        # keeper rules on an exit there; the 15 s settle wait only held the loop.
        print("\n[a power-off 2 s after the exit cannot come from another thread: the keeper does not wait]")
        rec, rv, k = run_exit(1, down_after=2.0, down_after_fn=relay_poweroff)
        check("ruled at once: an exit nothing explained, no 15 s stall",
              (k.gone is not None, any("不算故障" in m for m in rec.at(logging.INFO))), (True, False))

        # The user, 2026-10-06: only the planned power-off the relay itself started may
        # stay out of the group; every other shutdown is pushed.
        print("\n[a `shutdown /s` by hand: the service stop control comes 2 s later - pushed at the stop]")
        rec, rv, k = run_exit(1, down_after=2.0)
        check("not called 「not a fault」", any("不算故障" in m for m in rec.at(logging.INFO)), False)
        stop(k)
        warns = rec.at(logging.WARNING)
        check("the stop: one WARNING, the backend not back", len(warns) == 1 and "中继停下时还没重新起来" in warns[0])
        check("it reached the group", len(pushed(rec, 1)), 1)
        stop(k)
        check("said once", len(rec.at(logging.WARNING)), 1)

        print("\n[10-10 04:28: Windows shut down by hand, the stop notice right after the exit was ruled on - pushed, said as the shutdown]")
        rec, rv, k = run_exit(1)
        vt = VClock()
        vt.now = k.gone["at"] + 1.0     # relay.log 04:28:44 the exit line, 04:28:45 「收到停止通知（Windows 关机）」
        set_time(vt)
        errwatch.mark_os_shutdown()
        errwatch.mark_stopping()
        try:
            stop(k)
        finally:
            set_time(orig[1])
            errwatch._stopping.clear()
            errwatch._os_shutdown.clear()
        warns = rec.at(logging.WARNING)
        check("one WARNING", len(warns), 1)
        check("it says Windows shut down, not 「意外退出…没在关机」",
              bool(warns) and "Windows 关机" in warns[0] and "没在关机" not in warns[0] and "意外" not in warns[0])
        check("it reached the group", len(pushed(rec, 1)), 1)

        # 2026-10-10 04:28 (machine clock): `shutdown /s /t 60` by hand wrote its 1074 at
        # 04:27:24 (20:27:24 UTC); AUTO-MAS exited ~04:28:29; the stop notice came 04:28:45.
        print("\n[10-10 04:28 sample: a 1074 80 s before the exit - no revival, the stop says who shut down]")
        events["xml"] = [ev1074("2026-10-09T20:27:24.5512345Z", r"C:\Windows\system32\shutdown.exe (INS)",
                                r"INS\Administrator")]
        try:
            rec, rv, k = run_exit(1)
            check("no revival into the closing session", rv, [])
            check("INFO names the requester and the time",
                  any("shutdown.exe" in m and "04:27:24" in m for m in rec.at(logging.INFO)))
            check("not called 「意外退出」", any("意外退出" in m for m in rec.at(logging.INFO)), False)
            vt = VClock()
            vt.now = k.gone["at"] + 1.0
            set_time(vt)
            k.check(False, vt.now)                   # a loop wake before the stop: still no revival
            check("still no revival on the next wake", list(revived), [])
            errwatch.mark_os_shutdown()
            errwatch.mark_stopping()
            try:
                stop(k)
            finally:
                set_time(orig[1])
                errwatch._stopping.clear()
                errwatch._os_shutdown.clear()
            warns = rec.at(logging.WARNING)
            check("one WARNING at the stop", len(warns), 1)
            check("it says Windows shut down, by whom and when",
                  bool(warns) and "Windows 关机" in warns[0] and "shutdown.exe" in warns[0]
                  and "INS\\Administrator" in warns[0] and "04:27:24" in warns[0])
            check("it reached the group", len(pushed(rec, 1)), 1)
        finally:
            events["xml"] = []

        print("\n[a 1074 followed by a 1075 (shutdown /a): not a shutdown - revived at once, said as unexpected]")
        events["xml"] = [ev1075("2026-10-09T20:27:40Z"),
                         ev1074("2026-10-09T20:27:24Z", r"C:\Windows\system32\shutdown.exe (INS)", r"INS\Administrator")]
        try:
            rec, rv, k = run_exit(1)
        finally:
            events["xml"] = []
        check("revived once", len(rv), 1)
        check("said as an unexpected exit", any("意外退出" in m for m in rec.at(logging.INFO)))

        print("\n[a 1074 but the machine stays up past SHUTDOWN_NO_SHOW_SECONDS: revived then]")
        events["xml"] = [ev1074("2026-10-09T20:27:24Z", r"C:\Windows\system32\shutdown.exe (INS)", r"INS\Administrator")]
        try:
            rec, rv, k = run_exit(1)
            check("not revived at once", rv, [])
            vt = VClock()
            vt.now = k.gone["at"] + automas_keeper.SHUTDOWN_NO_SHOW_SECONDS + 1
            set_time(vt)
            automas_procs._automas_running = lambda: False
            try:
                k.check(False, vt.now)
            finally:
                set_time(orig[1])
            check("revived once the shutdown did not come", len(revived), 1)
            check("said why", any("还没关机" in m for m in rec.at(logging.INFO)))
        finally:
            events["xml"] = []

        print("\n[the relay's own power-off (10-09 21:41:51 / 21:49:11 wrote a 1074 too): INFO, nothing pushed]")
        events["xml"] = [ev1074("2026-10-09T13:41:51Z", r"C:\Windows\system32\shutdown.exe (INS)", "NT AUTHORITY\\SYSTEM")]
        try:
            rec, rv, k = run_exit(1, down=relay_poweroff)
            stop(k)
        finally:
            events["xml"] = []
        check("no WARNING", rec.at(logging.WARNING), [])
        check("no revival", rv, [])
        check("nothing reached the group", pushed(rec), [])

        print("\n[shutdown_requested reads the newest event: 1074 alone, 1075 newest, nothing]")
        got = shutdown_signs.shutdown_requested([ev1074("2026-10-09T20:27:24.5512345Z", "p.exe (INS)", "INS\\u")])
        check("process / user / clock (UTC -> the machine's clock)",
              (got or {}).get("process") == "p.exe (INS)" and (got or {}).get("user") == "INS\\u"
              and (got or {}).get("clock") == "04:27:24")
        check("1075 newest -> None", shutdown_signs.shutdown_requested([ev1075("2026-10-09T20:28:00Z"),
                                                                ev1074("2026-10-09T20:27:24Z", "p", "u")]), None)
        check("no events -> None", shutdown_signs.shutdown_requested([]), None)

        print("\n[Windows itself says it is shutting down (SM_SHUTTINGDOWN), not the relay: pushed at the stop]")
        errwatch.system_shutting_down = lambda: True
        try:
            rec, rv, k = run_exit(1)
        finally:
            errwatch.system_shutting_down = lambda: False
        check("not called 「not a fault」", any("不算故障" in m for m in rec.at(logging.INFO)), False)
        stop(k)
        check("the stop: one WARNING", len(rec.at(logging.WARNING)), 1)
        check("it reached the group", len(pushed(rec, 1)), 1)

        print("\n[an exit nothing explains: INFO with the evidence, then the revival at INFO; nothing pushed yet]")
        rec, rv, k = run_exit(0xC0000005)
        check("no WARNING yet (undecided)", rec.at(logging.WARNING), [])
        said = [m for m in rec.at(logging.INFO) if "意外退出" in m]
        line = first(said[0]) if said else ""
        check("one INFO line on the exit", len(said), 1)
        check("it is plain Chinese", texts.plain(line), [])
        check("it carries the exit code", "0xC0000005" in line)
        check("and what was ruled out", "没在关机" in line and "没在装更新" in line)
        check("and whether the window was there", "窗口也没了" in line)
        check("revived once", len(rv), 1)
        check("the revival line itself is INFO",
              any("正在重新打开" in m for m in rec.at(logging.INFO)))
        check("nothing reached the group", pushed(rec), [])

        print("\n[... and the relay's revival brings it back: ONE WARNING, pushed - why it exits is not known (2026-10-10)]")
        set_time(VClock())
        automas_procs._automas_running = lambda: True
        automas_procs._automas_handle = lambda: "handle:31000"
        try:
            k.check(False, k.revive_deadline + 1)
        finally:
            set_time(orig[1])
        warns = rec.at(logging.WARNING)
        check("one WARNING", len(warns), 1)
        line = first(warns[0]) if warns else ""
        check("「AUTO-MAS 后台意外退出过（…退出码…），中继已重新打开」",
              line.startswith("AUTO-MAS 后台意外退出过（") and "退出码 0xC0000005" in line and "中继已重新打开" in line)
        check("it is plain Chinese (the daily report quotes it)", texts.plain(line), [])
        check("not marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rec.records
                                       if r.levelno == logging.WARNING], [False])
        check("pushed, once", [("中继已重新打开" in x) for x in pushed(rec)], [True])
        section = daily(rec)
        check("the daily report lists it, not tagged 「自己好了，只进日报」",
              "中继已重新打开" in section and "自己好了，只进日报" not in section)
        check("the keeper holds the new backend", (k.handle, k.gone), ("handle:31000", None))

        print("\n[the exit code cannot be read: said so, at INFO]")
        rec, rv, _ = run_exit(None, task_list="shell")
        said = [m for m in rec.at(logging.INFO) if "意外退出" in m]
        check("INFO saying the code could not be read and the window is up",
              len(said) == 1 and "读不到" in said[0] and "窗口还在" in said[0])
        check("no WARNING yet", rec.at(logging.WARNING), [])

        print("\n[an update installer is running when it exits: INFO, hands off]")
        rec, rv, k = run_exit(0, task_list="setup")
        said = [m for m in rec.at(logging.INFO) if "退出了" in m]
        check("INFO saying an installer was up", len(said) == 1 and "安装" in said[0])
        check("no WARNING yet", rec.at(logging.WARNING), [])
        check("not called 「not a fault」", any("不算故障" in m for m in rec.at(logging.INFO)), False)
        check("no revival while it installs", rv, [])

        print("\n[... the update done, AUTO-MAS starts its backend itself: one WARNING, daily report only]")
        automas_procs._automas_handle = lambda: "handle:32000"
        k.on_process_started()
        warns = rec.at(logging.WARNING)
        line = first(warns[0]) if warns else ""
        check("one WARNING: back, and not by the relay",
              len(warns) == 1 and "现在又在运行了" in line and "不是中继打开的" in line)
        check("marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rec.records
                                   if r.levelno == logging.WARNING], [True])
        check("not pushed", pushed(rec), [])

        print("\n[an installer run that never comes back: pushed at the REVIVE_ALERT_AFTER-th check]")
        rec, rv, k = run_exit(0, task_list="setup")
        vt = VClock()
        set_time(vt)
        automas_procs._automas_running = lambda: False
        automas_procs._automas_handle = lambda: None
        tasks["list"] = TASKS["setup"]
        try:
            for _ in range(automas_keeper.REVIVE_ALERT_AFTER - 1):
                vt.now = k.revive_deadline + 1
                k.check(False, vt.now)
        finally:
            set_time(orig[1])
        warns = rec.at(logging.WARNING)
        check("one WARNING (not marked recovered)",
              [getattr(r, errwatch.RECOVERED, False) for r in rec.records if r.levelno == logging.WARNING], [False])
        line = first(warns[0]) if warns else ""
        check("it says it has not come back, with the exit and the installer",
              "还没回来" in line and "退出码 0x0" in line and "安装或卸载程序还开着" in line)
        check("it reached the group", len(pushed(rec, 1)), 1)
        check("still no revival while the installer is up", rv + revived, [])
        stop(k)
        check("the stop does not push it a second time", len(rec.at(logging.WARNING)), 1)

        print("\n[the relay's revivals fail: 「🔌 AUTO-MAS 启动不起来」 really fires, with the exit that started it]")
        rec, rv, k = run_exit(0xC0000005)
        vt = VClock()
        set_time(vt)
        automas_procs._automas_running = lambda: False
        automas_procs._automas_handle = lambda: None
        tasks["list"] = TASKS["plain"]
        try:
            for _ in range(automas_keeper.REVIVE_ALERT_AFTER - 1):
                vt.now = k.revive_deadline + 1
                k.check(False, vt.now)
        finally:
            set_time(orig[1])
        calls = k.notifier.calls
        check("one alarm: 🔌 AUTO-MAS 启动不起来, alert=True",
              [(t, a) for t, _, a in calls], [(texts.AUTOMAS_DOWN, True)])
        from ark_relay.core.notify import route_of
        check("that title goes to the group", route_of(texts.AUTOMAS_DOWN, alert=True), "group")
        body = calls[0][1] if calls else ""
        check("its body names the exit that started it", "起因" in body and "0xC0000005" in body)
        check("the revivals up to it were INFO (no WARNING)", rec.at(logging.WARNING), [])
        set_time(vt)
        try:
            vt.now = k.revive_deadline + 1
            k.check(False, vt.now)
        finally:
            set_time(orig[1])
        check("a revival after the alarm is a WARNING again (pushed, as before)",
              len(rec.at(logging.WARNING)), 1)

        print("\n[the deadline passes with no backend (not after an exit): plain WARNING]")
        revived.clear()
        vt = VClock()
        set_time(vt)
        tasks["list"] = TASKS["plain"]
        k, rec = keeper(handle=None)
        automas_procs._automas_running = lambda: False
        automas_procs._automas_handle = lambda: None
        try:
            k.check(False, k.revive_deadline + 1)
        finally:
            set_time(orig[1])
        warns = rec.at(logging.WARNING)
        check("one WARNING", len(warns), 1)
        check("plain Chinese, says what is wrong", bool(warns) and not texts.plain(warns[0])
              and "没在运行" in warns[0], True)
        check("revived", len(revived), 1)

        print("\n[the deadline passes while the relay's own power-off is under way: leave it]")
        revived.clear()
        vt = VClock()
        set_time(vt)
        k, rec = keeper(handle=None)
        relay_poweroff()
        try:
            vt.now = k.revive_deadline + 1
            k.check(False, vt.now)
            wait = k.cap_wait(3600.0)
        finally:
            set_time(orig[1])
            errwatch._stopping.clear()
            errwatch._relay_poweroff[0] = lambda: False
        check("no revival", revived, [])
        check("no WARNING", rec.at(logging.WARNING), [])
        check("and the loop is not woken every second meanwhile", wait >= 60, True)

        print("\n[the keeper's stopping() reaches the WMI listener]")
        stops = []
        k, rec = keeper()
        k.wmi_alive["watch"] = types.SimpleNamespace(stopping=lambda: stops.append(1))
        stop(k)
        check("the listener was told", stops, [1])
        check("nothing pending, nothing said", rec.at(logging.WARNING), [])

        print("\n[the listener found itself broken before _start_process_watch returned]")
        automas_procs._automas_handle = lambda: "handle:1"
        procwatch._start_process_watch = lambda evt, alive, lg: (alive.update(ok=False), True)[1]
        k = automas_keeper._AutomasKeeper(logging.getLogger("ark.test_keeper"), Notifier())
        check("the keeper does not overwrite that with 'alive'", k.wmi_alive["ok"], False)

        print("\n[the handle is opened with the right to read the exit code, and without it if refused]")
        automas_procs._automas_handle = orig[5]
        automas_procs._python_processes = lambda: [(21932, r"D:\ark\automas\runtime\python.exe D:\ark\automas\repo\main.py")]
        opened.clear()
        refuse_query[0] = False
        check("got a handle", automas_procs._automas_handle(), "handle:21932")
        check("asked for SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION", opened, [SYNCHRONIZE | 0x1000])
        opened.clear()
        refuse_query[0] = True
        check("refused: still a handle", automas_procs._automas_handle(), "handle:21932")
        check("second try with SYNCHRONIZE alone", opened, [SYNCHRONIZE | 0x1000, SYNCHRONIZE])

        print("\n[清单-1108 A-06: a revived backend is adopted only once its API answers]")
        vt = VClock()
        set_time(vt)
        try:
            k, rec = keeper(handle=None)
            k.revive_failures, k.revive_wait = 2, 720.0
            automas_procs._automas_handle = lambda: "handle:31000"
            api["up"] = False
            k.on_process_started()
            check("process up, API silent: handle held, the revivals still counted",
                  (k.handle, k.revive_failures, k.api_since is not None), ("handle:31000", 2, True))
            check("the loop wakes to ask again", k.cap_wait(3600.0), automas_keeper.API_RECHECK_SECONDS)
            k.check(False, vt.now + 30)
            check("still silent: nothing reset, no WARNING yet", (k.revive_failures, rec.at(logging.WARNING)), (2, []))
            vt.now += automas_keeper.API_GRACE_SECONDS
            k.check(False, vt.now)
            k.check(False, vt.now + 30)
            check("silent past the grace: one WARNING (pushed), said once",
                  [("接口一直没响应" in m) for m in rec.at(logging.WARNING)], [True])
            api["up"] = True
            k.check(False, vt.now + 60)
            check("the API answers: adopted, the revival state reset",
                  (k.revive_failures, k.revive_wait, k.api_since, k.cap_wait(3600.0)),
                  (0, float(automas_keeper.REVIVE_FIRST_WAIT), None, 3600.0))
            api["up"] = False
            k.handle, k.revive_deadline = None, vt.now + 61
            automas_procs._automas_running = lambda: True
            k.check(False, vt.now + 62)
            check("found by the liveness check with the API silent: held, not adopted", k.api_since is not None, True)
            exit_codes["handle:31000"] = 1
            automas_procs._automas_running = lambda: False
            automas_procs._automas_handle = lambda: None
            k.check(True, vt.now + 120)
            check("its exit clears the API wait", (k.api_since, k.api_warned), (None, False))
        finally:
            set_time(orig[1])
            api["up"] = True


        print("\n[清单-1108 A-06: a revival kills the process trees and any leftover backend, and says what schtasks answered]")
        ran = []
        real_run, real_bt = subprocess.run, boot_stages.time
        subprocess.run = lambda cmd, **kw: (ran.append(cmd), types.SimpleNamespace(
            returncode=0x41301 if cmd[:2] == ["schtasks", "/run"] else 0, stdout=b"already running"))[1]
        boot_stages.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic, time=time.time)
        automas_procs._python_processes = lambda: [(31000, r"D:\ark\automas\runtime\python.exe D:\ark\automas\repo\main.py"),
                                                   (2, r"C:\python.exe other.py")]
        grab = Records()
        boot_stages.log.addHandler(grab)
        lvl = boot_stages.log.level
        boot_stages.log.setLevel(logging.DEBUG)
        try:
            orig[3]()
        finally:
            subprocess.run, boot_stages.time = real_run, real_bt
            boot_stages.log.removeHandler(grab)
            boot_stages.log.setLevel(lvl)
        check("the shell and the runtime with their children (/T)",
              ran[:2], [["taskkill", "/IM", "AUTO-MAS.exe", "/F", "/T"], ["taskkill", "/IM", "auto-mas-runtime.exe", "/F", "/T"]])
        check("the leftover backend by its pid, nothing else", [c for c in ran if "/PID" in c], [["taskkill", "/PID", "31000", "/F", "/T"]])
        check("schtasks /run's refusal is said with its code", any("0x41301" in m for m in grab.at(logging.INFO)), True)
    finally:
        (errwatch.system_shutting_down, procwatch.time, subprocess.run, boot_stages._revive_automas,
         automas_procs._automas_running, automas_procs._automas_handle, procwatch._start_process_watch,
         automas_procs._python_processes) = orig
        errwatch._stopping.clear()
        for key, v in saved.items():
            if v is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = v


def _part_keeper_hold_once():
    """A hold that lasts is said at WARNING once, not at every check (review of bd80586d, 2026-10-13).

bd80586d stopped doubling revive_wait when a check revived nothing, so a hold
(an installer on screen, or the program list unreadable) re-armed at 180 s for as
long as it lasted, and each check logged its hold line at WARNING through `say`,
which errwatch pushes to the group: 40 pushes in 2 hours against 8 before (when
every check doubled the wait). Now the hold keeps the 180 s check and is said at
WARNING the first time, at INFO while it lasts; a real revival says it again.

    Formerly test_keeper_hold_once.py.
    """
    import logging
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


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                  "win32evtlog", "win32gui"):
        sys.modules.setdefault(_name, _Stub(_name))

    import time

    import boot_stages
    from ark_relay.features.host import automas_keeper, automas_procs, procwatch
    from ark_relay.features.phone import commands


    clock = [1000.0]
    time.monotonic = lambda: clock[0]
    automas_procs._python_processes = lambda: []
    commands.mas_up = lambda: False
    automas_procs._automas_shell_running = lambda: False
    procwatch._start_process_watch = lambda evt, alive, log: True
    revives = []
    boot_stages._revive_automas = lambda: revives.append(clock[0])


    class _Keep(logging.Handler):
        def __init__(self):
            super().__init__()
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage()))


    keep = _Keep()
    log = automas_keeper.log
    log.addHandler(keep)
    log.setLevel(logging.INFO)


    class _Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, *a, **k):
            self.sent.append(title)


    OLD_COUNT = 8   # before bd80586d: checks at 180, 540, 1260, 2700, 4500, 6300 s ... within 2 hours


    def two_hours(label, installer, hint):
        print(f"[{label}：两小时只报一次]")
        automas_procs._installer_running = lambda: installer
        revives.clear()
        clock[0] += 100000.0
        k = automas_keeper._AutomasKeeper(log, _Notifier())
        keep.rows.clear()
        checks = 0
        start = clock[0]
        while clock[0] - start < 2 * 3600:
            clock[0] = k.revive_deadline
            k.check(False, clock[0])
            checks += 1
        warned = [m for lv, m in keep.rows if lv == "WARNING" and hint in m]
        infos = [m for lv, m in keep.rows if lv == "INFO" and hint in m]
        check(f"{label}: still checked every 180 s", checks >= 40, True)
        check(f"{label}: nothing revived", revives, [])
        check(f"{label}: WARNINGs at most the old count ({OLD_COUNT})", len(warned) <= OLD_COUNT, True)
        check(f"{label}: one WARNING", len(warned), 1)
        check(f"{label}: the rest at INFO", len(infos), checks - 1)
        return k


    two_hours("安装程序开着", True, "安装程序正在运行")
    k = two_hours("读不到程序列表", None, "读不到正在运行的程序列表")

    print("[拦着之后真拉起过、又拦住：再说一次]")
    automas_procs._installer_running = lambda: False
    clock[0] = k.revive_deadline
    k.check(False, clock[0])
    check("revived once", len(revives), 1)
    automas_procs._installer_running = lambda: True
    keep.rows.clear()
    for _ in range(3):
        clock[0] = k.revive_deadline
        k.check(False, clock[0])
    check("a new hold after a revival: one WARNING",
          [lv for lv, m in keep.rows if "安装程序正在运行" in m], ["WARNING", "INFO", "INFO"])


if __name__ == "__main__":
    sys.exit(run_parts([_part_keeper_blind_backoff, _part_keeper_exit, _part_keeper_hold_once]))
