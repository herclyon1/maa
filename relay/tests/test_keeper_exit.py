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
"""
import logging
import subprocess
import sys
import tempfile
import time
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


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
import boot_stages  # noqa: E402
import service  # noqa: E402 - a fresh copy built on the fakes above
from ark_relay import errwatch, texts  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402


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


orig = (errwatch.system_shutting_down, service.time, subprocess.run, boot_stages._revive_automas,
        service._automas_running, service._automas_handle, service._start_process_watch,
        service._python_processes)
errwatch.system_shutting_down = lambda: False
subprocess.run = fake_run
revived = []
boot_stages._revive_automas = lambda: revived.append(service.time.now)


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
    service._automas_handle = lambda: handle
    service._start_process_watch = lambda evt, alive, lg: True
    k = service._AutomasKeeper(log, Notifier())
    return k, rec


def run_exit(code, task_list="plain", down=None, down_after=None, running_after=False, down_after_fn=None):
    """The backend's handle signals; returns (records, revivals)."""
    exit_codes.clear()
    if code is not None:
        exit_codes["handle:21932"] = code
    tasks["list"] = TASKS[task_list]
    revived.clear()
    vt = VClock()
    service.time = vt
    k, rec = keeper()
    if down:
        down()
    if down_after is not None:
        vt.at(down_after, down_after_fn or errwatch.mark_stopping)
    service._automas_running = lambda: running_after
    service._automas_handle = lambda: None
    try:
        k.check(True, vt.now)
    finally:
        service.time = orig[1]
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

    print("\n[the relay's power-off lands 2 s after the exit: still INFO]")
    rec, rv, _ = run_exit(1, down_after=2.0, down_after_fn=relay_poweroff)
    check("no WARNING", rec.at(logging.WARNING), [])
    check("INFO, not a fault", any("不算故障" in m for m in rec.at(logging.INFO)))

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

    print("\n[... and the relay's revival brings it back: ONE WARNING, daily report only]")
    service.time = VClock()
    service._automas_running = lambda: True
    service._automas_handle = lambda: "handle:31000"
    try:
        k.check(False, k.revive_deadline + 1)
    finally:
        service.time = orig[1]
    warns = rec.at(logging.WARNING)
    check("one WARNING", len(warns), 1)
    line = first(warns[0]) if warns else ""
    check("「AUTO-MAS 后台意外退出过（…退出码…），中继已重新打开」",
          line.startswith("AUTO-MAS 后台意外退出过（") and "退出码 0xC0000005" in line and "中继已重新打开" in line)
    check("it is plain Chinese (the daily report quotes it)", texts.plain(line), [])
    check("marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rec.records
                               if r.levelno == logging.WARNING], [True])
    check("not pushed", pushed(rec), [])
    section = daily(rec)
    check("the daily report lists it, tagged 「自己好了，只进日报」",
          "中继已重新打开" in section and "自己好了，只进日报" in section)
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
    service._automas_handle = lambda: "handle:32000"
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
    service.time = vt
    service._automas_running = lambda: False
    service._automas_handle = lambda: None
    tasks["list"] = TASKS["setup"]
    try:
        for _ in range(service.REVIVE_ALERT_AFTER - 1):
            vt.now = k.revive_deadline + 1
            k.check(False, vt.now)
    finally:
        service.time = orig[1]
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
    service.time = vt
    service._automas_running = lambda: False
    service._automas_handle = lambda: None
    tasks["list"] = TASKS["plain"]
    try:
        for _ in range(service.REVIVE_ALERT_AFTER - 1):
            vt.now = k.revive_deadline + 1
            k.check(False, vt.now)
    finally:
        service.time = orig[1]
    calls = k.notifier.calls
    check("one alarm: 🔌 AUTO-MAS 启动不起来, alert=True",
          [(t, a) for t, _, a in calls], [(texts.AUTOMAS_DOWN, True)])
    from ark_relay.notify import route_of
    check("that title goes to the group", route_of(texts.AUTOMAS_DOWN, alert=True), "group")
    body = calls[0][1] if calls else ""
    check("its body names the exit that started it", "起因" in body and "0xC0000005" in body)
    check("the revivals up to it were INFO (no WARNING)", rec.at(logging.WARNING), [])
    service.time = vt
    try:
        vt.now = k.revive_deadline + 1
        k.check(False, vt.now)
    finally:
        service.time = orig[1]
    check("a revival after the alarm is a WARNING again (pushed, as before)",
          len(rec.at(logging.WARNING)), 1)

    print("\n[the deadline passes with no backend (not after an exit): plain WARNING]")
    revived.clear()
    vt = VClock()
    service.time = vt
    tasks["list"] = TASKS["plain"]
    k, rec = keeper(handle=None)
    service._automas_running = lambda: False
    service._automas_handle = lambda: None
    try:
        k.check(False, k.revive_deadline + 1)
    finally:
        service.time = orig[1]
    warns = rec.at(logging.WARNING)
    check("one WARNING", len(warns), 1)
    check("plain Chinese, says what is wrong", bool(warns) and not texts.plain(warns[0])
          and "没在运行" in warns[0], True)
    check("revived", len(revived), 1)

    print("\n[the deadline passes while the relay's own power-off is under way: leave it]")
    revived.clear()
    vt = VClock()
    service.time = vt
    k, rec = keeper(handle=None)
    relay_poweroff()
    try:
        vt.now = k.revive_deadline + 1
        k.check(False, vt.now)
        wait = k.cap_wait(3600.0)
    finally:
        service.time = orig[1]
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
    service._automas_handle = lambda: "handle:1"
    service._start_process_watch = lambda evt, alive, lg: (alive.update(ok=False), True)[1]
    k = service._AutomasKeeper(logging.getLogger("ark.test_keeper_exit"), Notifier())
    check("the keeper does not overwrite that with 'alive'", k.wmi_alive["ok"], False)

    print("\n[the handle is opened with the right to read the exit code, and without it if refused]")
    service._automas_handle = orig[5]
    service._python_processes = lambda: [(21932, r"D:\ark\automas\runtime\python.exe D:\ark\automas\repo\main.py")]
    opened.clear()
    refuse_query[0] = False
    check("got a handle", service._automas_handle(), "handle:21932")
    check("asked for SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION", opened, [SYNCHRONIZE | 0x1000])
    opened.clear()
    refuse_query[0] = True
    check("refused: still a handle", service._automas_handle(), "handle:21932")
    check("second try with SYNCHRONIZE alone", opened, [SYNCHRONIZE | 0x1000, SYNCHRONIZE])
finally:
    (errwatch.system_shutting_down, service.time, subprocess.run, boot_stages._revive_automas,
     service._automas_running, service._automas_handle, service._start_process_watch,
     service._python_processes) = orig
    errwatch._stopping.clear()
    for key, v in saved.items():
        if v is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = v

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
