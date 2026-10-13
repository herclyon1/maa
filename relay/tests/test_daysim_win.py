"""Day simulator, unit W2: the Windows fakes (daysim/fake_win.py) and the subprocess router
(daysim/fake_proc.py), driven through the relay's own code wherever the relay has it.

What this proves (design section 6, row W2):
  - an unrouted command aborts the day: a sim error is recorded and SimAbort gets through
    the relay's `except Exception`; nothing reaches a real program on this Mac;
  - `shutdown /s` (engine._power_off itself) changes the World's power state, `/a`
    (engine._abort_power_off) cancels it, and the countdown's end flips
    errwatch.system_shutting_down();
  - a python.exe start in the World's process table reaches procwatch's real WMI listener
    on its own thread and wakes the main loop's wait; a pythonw.exe start does not;
    stopping the listener cancels the subscription without hanging.
Plus the relay's own parsers over every answer the router gives (tasklist, taskkill,
schtasks, sc, wevtutil, PowerShell) and the directory watches.

W1's scheduler is not in the repo yet, so a stand-in with the same five calls
(now/at/park/advance/out, design section 2) drives the waits here.
"""
import heapq
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "daysim"))

import fake_proc  # noqa: E402
import fake_win  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        print(f"      want {want!r}")
        fails.append(label)


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}{f'  ({detail})' if detail and not ok else ''}")
    if not ok:
        fails.append(name)


class StandIn:
    """W1's scheduler interface, just enough for these checks: sim seconds, one Condition.

    advance() moves the clock only once every other live thread is parked with nothing
    to do (its ready() false), as W1 does; it gives up waiting for that after 5 s of
    real time (W1 calls that an unparked-thread sim error)."""

    def __init__(self, t0: float):
        self.t = t0
        self.cv = threading.Condition()
        self.timers: list = []
        self.seq = 0
        self.outs: list = []
        self.parked: dict = {}       # thread ident -> its ready()

    def now(self) -> float:
        return self.t

    def at(self, t, fn, tag):
        self.seq += 1
        heapq.heappush(self.timers, (t, self.seq, fn, tag))

    def out(self, kind, **f):
        self.outs.append((kind, f))

    def kick(self):
        with self.cv:
            self.cv.notify_all()

    def park(self, timeout, ready):
        deadline = None if timeout is None else self.t + timeout
        me = threading.get_ident()
        with self.cv:
            self.parked[me] = ready
            self.cv.notify_all()
            try:
                while not ready():
                    if deadline is not None and self.t >= deadline:
                        return False
                    self.cv.wait(0.05)
                return True
            finally:
                del self.parked[me]
                self.cv.notify_all()

    def _settled(self) -> bool:
        main = threading.main_thread()
        helpers = [t for t in threading.enumerate() if t is not main and t.is_alive()]
        return all(t.ident in self.parked and not self.parked[t.ident]() for t in helpers)

    def advance(self, handles_ready, timeout_ms):
        deadline = float("inf") if timeout_ms is None else self.t + timeout_ms / 1000.0
        while True:
            while self.timers and self.timers[0][0] <= self.t:
                heapq.heappop(self.timers)[2]()
            if (i := handles_ready()) is not None:
                return i
            with self.cv:
                self.cv.wait_for(lambda: handles_ready() is not None or self._settled(), 5.0)
            if (i := handles_ready()) is not None:
                return i
            nxt = min(deadline, self.timers[0][0] if self.timers else float("inf"))
            if nxt == float("inf"):
                raise RuntimeError("stand-in: the main thread would wait forever")
            self.t = nxt
            if nxt >= deadline and not (self.timers and self.timers[0][0] <= self.t):
                return handles_ready()

    def kinds(self, kind):
        return [f for k, f in self.outs if k == kind]


class Log:
    def __init__(self):
        self.lines = []

    def _add(self, level, msg, *a, **k):
        self.lines.append((level, msg % a if a else msg))

    def info(self, msg, *a, **k):
        self._add("INFO", msg, *a)

    def warning(self, msg, *a, **k):
        self._add("WARNING", msg, *a)

    def error(self, msg, *a, **k):
        self._add("ERROR", msg, *a)

    def exception(self, msg, *a, **k):
        self._add("ERROR", msg, *a)


# 2026-10-12 08:40 Beijing, the probe's start; the machine powered on two minutes before.
T0 = datetime.fromisoformat("2026-10-12T08:40:00+08:00").timestamp()
sched = StandIn(T0)
win = fake_proc.WinState(sched, power_on=T0 - 120)
win.add_baseline(T0 - 120)
fw = fake_win.FakeWin(sched, win).install()

# Nothing may reach a real program: count every attempt of the real Popen.
REAL_SPAWNS = []
subprocess.Popen._execute_child = lambda self, *a, **k: REAL_SPAWNS.append(a) or (_ for _ in ()).throw(
    OSError("real spawn"))
router = fake_proc.ProcRouter(sched, win).install()

import win32api  # noqa: E402
import win32event  # noqa: E402
import win32process  # noqa: E402

from ark_relay.core import desktop, engine, procs  # noqa: E402
from ark_relay.core import watch  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.host import automas_procs, dirwatch, procwatch, wmi_diag, wmi_subscription  # noqa: E402
from ark_relay.features.makeup import collect_retry  # noqa: E402
from ark_relay.features.phone import snapshot  # noqa: E402
from ark_relay.features.preupdate import preupdate_common, preupdate_okww  # noqa: E402
from ark_relay.features.run import maaend_watchdog  # noqa: E402
from ark_relay.features.selfcheck import selfcheck  # noqa: E402
from ark_relay.features.shutdown import shutdown  # noqa: E402

BACKEND = r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"
OKWW = r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe D:\ark\okww\data\apps\ok-ww\working\main.py -t 2 -e"
pr = win.procs
shell = pr.start("AUTO-MAS.exe", exe=r"D:\ark\automas\AUTO-MAS.exe", t=T0)
maa = pr.start("MAA.exe", exe=r"D:\ark\maa\MAA.exe", t=T0)


def main():
    print("\n[1] an unrouted command aborts the day")
    n_err = len(sched.kinds("sim_errors"))
    caught = ""
    try:
        try:
            subprocess.run(["cmd", "/c", "mklink", "/J", "a", "b"], capture_output=True)
        except Exception:  # noqa: BLE001 - the relay's own catch-all must not swallow it
            caught = "swallowed by except Exception"
    except fake_proc.SimAbort as exc:
        caught = f"SimAbort: {exc}"
    require("SimAbort passes `except Exception`", caught.startswith("SimAbort"), caught)
    check("one sim error recorded", len(sched.kinds("sim_errors")) - n_err, 1)
    check("it names the command", sched.kinds("sim_errors")[-1]["detail"].startswith("cmd /c mklink"), True)
    for what, call in (("os.system", lambda: os.system("shutdown -h now")),
                       ("unknown PowerShell", lambda: subprocess.run(
                           ["pwsh", "-NoProfile", "-Command", "Restart-Computer -Force"], capture_output=True)),
                       ("unknown tasklist flag", lambda: subprocess.run(["tasklist", "/V"], capture_output=True)),
                       ("shutdown /r", lambda: subprocess.run(["shutdown", "/r", "/t", "0"], capture_output=True)),
                       ("unknown WMI class", lambda: fw.get_object("winmgmts:").ExecQuery(
                           "SELECT * FROM Win32_Service WHERE Name='x'")),
                       ("unknown kernel32 call", lambda: __import__("ctypes").windll.kernel32.ExitWindowsEx)):
        try:
            call()
            got = "answered"
        except fake_proc.SimAbort:
            got = "aborted"
        except AttributeError:
            got = "aborted" if sched.kinds("sim_errors")[-1]["detail"] == "ExitWindowsEx" else "AttributeError"
        check(f"{what} is not answered", got, "aborted")
    check("power untouched by the refused shutdown /r", win.power, "on")

    print("\n[2] shutdown /s and /a: the relay's own calls change the World's power")
    eng = types.SimpleNamespace()
    check("_power_off accepted", engine.Engine._power_off(eng), True)
    check("power is counting down", win.power, "countdown")
    check("the countdown ends 60 s later", win.shutdown_at - sched.now(), 60.0)
    power = sched.kinds("power")
    check("one power output, the relay's command", [p["cmd"] for p in power],
          ["shutdown /s /t 60 /d p:4:1 /c ark-relay: run complete"])
    check("its time is Beijing ISO", power[-1]["t"], "2026-10-12T08:40:00+08:00")
    check("a second /s is refused with 1190", engine.Engine._power_off(eng), False)
    check("Windows logged 1074 for the power-off", [ev.event_id for ev in win.sys_events][-1:], [1074])
    check("_abort_power_off cancels: 0", engine.Engine._abort_power_off(eng), 0)
    check("power back on", win.power, "on")
    check("nothing to abort now: 1116", engine.Engine._abort_power_off(eng), fake_proc.NO_SHUTDOWN)
    check("System log: 1074 then 1075, read the relay's way",
          shutdown.cancel_event(shutdown.shutdown_event_xml(600) or [])[1], "NT AUTHORITY\\SYSTEM")
    downs = []
    win.on_power_off = downs.append
    check("_power_off again", engine.Engine._power_off(eng), True)
    stop = win32event.CreateEvent(None, 1, 0, None)
    check("not shutting down during the countdown", errwatch.system_shutting_down(), False)
    rc = win32event.WaitForMultipleObjects([stop], False, 30_000)
    check("30 s wait times out", rc, win32event.WAIT_TIMEOUT)
    check("still counting down at +30 s", win.power, "countdown")
    rc = win32event.WaitForMultipleObjects([stop], False, 31_000)
    check("power-off began at +60 s", win.power, "going_down")
    check("the World heard it at +60 s", [t - T0 for t in downs], [60.0])
    check("GetSystemMetrics(SM_SHUTTINGDOWN) now 1", errwatch.system_shutting_down(), True)
    check("the wait still timed out (nothing signalled)", rc, win32event.WAIT_TIMEOUT)
    check("sim clock moved 61 s", sched.now() - T0, 61.0)
    check("stale /a after the power-off began: 1116", engine.Engine._abort_power_off(eng), fake_proc.NO_SHUTDOWN)
    win.power, win.on_power_off = "on", None      # the record keeps the machine up from here

    print("\n[3] python.exe starts reach procwatch's real WMI listener")
    proc_evt = win32event.CreateEvent(None, 0, 0, None)     # as automas_keeper makes it
    alive = {}
    log = Log()
    check("_start_process_watch", procwatch._start_process_watch(proc_evt, alive, log), True)
    for _ in range(200):
        if fw.live_subscriptions():
            break
        threading.Event().wait(0.01)
    check("one live subscription", fw.live_subscriptions(), 1)
    require("listener said it subscribed", alive.get("ok") is True, str(log.lines[-3:]))
    t_before = sched.now()
    backend = pr.start("python.exe", BACKEND, exe=r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe",
                       t=sched.now())
    rc = win32event.WaitForMultipleObjects([stop, proc_evt], False, 60_000)
    check("the main wait wakes on the start", rc, win32event.WAIT_OBJECT_0 + 1)
    check("at once, not after the timeout", sched.now(), t_before)
    check("the listener counted it", alive["watch"].sub["events"], 1)
    pr.start("pythonw.exe", OKWW, exe=r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe", t=sched.now())
    rc = win32event.WaitForMultipleObjects([stop, proc_evt], False, 5_000)
    check("a pythonw.exe start does not wake it", rc, win32event.WAIT_TIMEOUT)
    check("python_processes reads the table", procs.python_processes(), [(backend.pid, BACKEND)])
    check("both hosts when asked", len(procs.python_processes(hosts=("python.exe", "pythonw.exe"))), 2)
    h = automas_procs._automas_handle()
    require("backend handle opened", h is not None)
    check("backend running: STILL_ACTIVE", win32process.GetExitCodeProcess(h), fake_proc.STILL_ACTIVE)
    pr.end(backend.pid, 3, sched.now())
    check("backend exit signals its handle", win32event.WaitForSingleObject(h, 0), win32event.WAIT_OBJECT_0)
    check("its exit code is read", automas_procs._exit_code(h), 3)
    try:
        win32api.OpenProcess(0x100000, False, backend.pid)
        check("OpenProcess on a dead pid", "opened", "error 87")
    except fake_win.error as exc:
        check("OpenProcess on a dead pid", f"error {exc.winerror}", "error 87")
    alive["watch"].stopping()
    check("stopping() cancelled the subscription", fw.live_subscriptions(), 0)
    check("the listener thread ended", alive["watch"].ended.is_set(), True)
    require("no listener ERROR", not [m for lv, m in log.lines if lv == "ERROR"], str(log.lines))

    print("\n[4] a subscription drop and a WMI outage")
    sub_stop = win32event.CreateEvent(None, 1, 0, None)
    sub = wmi_subscription._AsyncSubscription(sub_stop)
    pr.start("python.exe", BACKEND, t=sched.now())
    check("a start reads as an event", sub.wait(), "event")
    check("drop_wmi ends one subscription", fw.drop_wmi(), 1)
    got = sub.wait()
    check("the drop reads as done", got[0], "done")
    check("with the machine's words for 0x800706BE", "远程过程调用失败" in got[1][0], True)
    sub.cancel()
    win.wmi_ok = False
    rows, why = procs._query_once()
    check("WMI down: the query fails with its code", (rows, why), (None, "错误码 0x80041003"))
    win.wmi_ok = True

    print("\n[5] directory watches: win32file (main loop) and kernel32 (collect_watch)")
    hist = Path(tempfile.mkdtemp(prefix="daysim-w2-"))
    (hist / "2026-10-12").mkdir()
    cfg = types.SimpleNamespace(history_dir=hist)
    dw = dirwatch._DirWatch(cfg, None, Log())
    require("_DirWatch armed", dw.handle is not None)
    check("a drop under it signals once", fw.files_changed(hist / "2026-10-12" / "u1" / "MAA-04-40-10.json"), 1)
    check("main wait returns the watch", win32event.WaitForMultipleObjects([stop, dw.handle], False, 1000),
          win32event.WAIT_OBJECT_0 + 1)
    check("still set until re-armed (manual)", win32event.WaitForSingleObject(dw.handle, 0), win32event.WAIT_OBJECT_0)
    sys.modules["win32file"].FindNextChangeNotification(dw.handle)
    check("re-armed: clear", win32event.WaitForSingleObject(dw.handle, 0), win32event.WAIT_TIMEOUT)
    check("a sibling path does not count", fw.files_changed(str(hist) + "x/a.json"), 0)
    flat = fw.find_first(hist, False, 1)
    check("without subtree only direct entries", fw.files_changed(hist / "2026-10-12" / "deep.json"), 1)
    check("... the subtree watch took it, not the flat one", flat.signaled, False)
    fw.close(flat)
    try:
        sys.modules["win32file"].FindFirstChangeNotification(str(hist / "missing"), True, 1)
        check("a missing directory", "armed", "error 3")
    except fake_win.error as exc:
        check("a missing directory", f"error {exc.winerror}", "error 3")
    dw.close()
    wake = threading.Event()
    check("watch._windows starts its thread", watch._windows(str(hist), wake), True)
    fw.files_changed(hist / "app.log")
    check("its thread wakes the Event", wake.wait(5), True)
    shutil.rmtree(hist, ignore_errors=True)

    print("\n[6] the relay's parsers over the router's answers")
    check("maaend_watchdog._tasklist sees MAA.exe", ("MAA.exe", maa.pid) in (maaend_watchdog._tasklist() or []), True)
    check("collect_retry._running", collect_retry._running(("MAA.exe", "Endfield.exe")), {"MAA.exe"})
    require("wmi_diag._wmi_hosts", wmi_diag._wmi_hosts().startswith(f"winmgmt pid {win.services['winmgmt']['pid']}; "
                                                                     "WmiPrvSE pids "), wmi_diag._wmi_hosts())
    win.log_event(sched.now() - 30, 7036, "Service Control Manager",
                  {"param1": "Windows Management Instrumentation", "param2": "正在运行"},
                  binary_hex="winmgmt/4".encode("utf-16-le").hex())
    check("wmi_diag._wmi_scm_events reads wevtutil", wmi_diag._wmi_scm_events().startswith("SCM winmgmt: 7036 "), True)
    now = datetime.fromtimestamp(sched.now(), SERVER_TZ)
    check("shutdown._boot_time = power-on", shutdown._boot_time(None, now).timestamp(), T0 - 120)
    with_shell = __import__("boot_stages").shell_running()
    check("boot_stages.shell_running with the shell up", with_shell, True)
    check("tasklist text=True decodes GBK", "信息" in subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq nothing.exe"], capture_output=True, text=True).stdout, True)
    check("Popen().communicate() answers too", b"MAA.exe" in subprocess.Popen(
        ["tasklist", "/NH"], stdout=subprocess.PIPE).communicate()[0], True)
    check("check_output", b"AUTO-MAS.exe" in subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"]), True)
    check("selfcheck: AUTO-MAS task exists", selfcheck._run_ok(["schtasks", "/query", "/tn", "AUTO-MAS_AutoStart"]),
          (True, "退出码 0"))
    check("selfcheck: unknown task", selfcheck._run_ok(["schtasks", "/query", "/tn", "nope"]), (False, "退出码 1"))
    ran = []
    win.on_task_run = lambda name, task: ran.append(name)
    check("schtasks /run calls the World", subprocess.call(["schtasks", "/run", "/tn", "AUTO-MAS_AutoStart"]), 0)
    check("... with the task name", ran, ["AUTO-MAS_AutoStart"])
    check("schtasks /create then /delete", [
        subprocess.run(["schtasks", "/create", "/tn", "ark-x", "/tr", "x.bat", "/sc", "once", "/st", "00:00",
                        "/ru", "Administrator", "/it", "/f"], capture_output=True).returncode,
        subprocess.run(["schtasks", "/delete", "/tn", "ark-x", "/f"], capture_output=True).returncode,
        subprocess.run(["schtasks", "/delete", "/tn", "ark-x", "/f"], capture_output=True).returncode], [0, 0, 1])
    held = fw.hold_mutex("Global\\ArkRelayMain")
    check("snapshot._relay_state with the main mutex", snapshot._relay_state(), "RUNNING")
    fw.close(held)
    check("... without it, sc query: no such service", snapshot._relay_state(), "STOPPED")
    win.add_service("ark-relay", "RUNNING", 0)
    check("... and with the old service running", snapshot._relay_state(), "RUNNING")
    gone = pr.start("MaaEnd.exe", t=sched.now())
    check("maaend_watchdog._taskkill", maaend_watchdog._taskkill(gone.pid, "MaaEnd.exe"), (True, ""))
    check("... the process is gone", pr.get(gone.pid).alive, False)
    check("... again: the /FI-only no-match is rc 0, read as gone",
          maaend_watchdog._taskkill(gone.pid, "MaaEnd.exe"), (False, "要结束的那个已经不在了"))
    check("desktop.kill: running and not-running both fine", desktop.kill("MAA.exe", "nothere.exe"), True)
    game = pr.start("Client-Win64-Shipping.exe", t=sched.now(), protected=True)
    check("desktop.kill refused by anti-cheat", desktop.kill("Client-Win64-Shipping.exe"), False)
    check("... the game is still up", pr.get(game.pid).alive, True)
    parent = pr.start("AUTO-MAS.exe", t=sched.now())
    child = pr.start("auto-mas-runtime.exe", t=sched.now(), parent=parent.pid)
    subprocess.run(["taskkill", "/IM", "AUTO-MAS.exe", "/T", "/F"], capture_output=True)
    check("/T ends the children", (pr.get(parent.pid).alive, pr.get(child.pid).alive, shell.alive), (False, False, False))
    check("shell_running after the kill", __import__("boot_stages").shell_running(), False)
    kills = [f for f in sched.kinds("procs") if f["action"] == "taskkill"]
    require("taskkills are outputs with their pids", child.pid in kills[-1]["pids"], str(kills[-1:]))

    print("\n[7] PowerShell pipelines")
    log_errors = []
    preupdate_common.log.error = lambda msg, *a, **k: log_errors.append(msg % a)
    okww_pid = [p.pid for p in pr.named("pythonw.exe")]
    check("okww_python_pids", preupdate_okww.okww_python_pids(), okww_pid)
    preupdate_okww._stop_okww_python()
    check("_stop_okww_python ended them", preupdate_okww.okww_python_pids(), [])
    pr.start("launcher.exe", exe=r"D:\Wuthering Waves\launcher.exe", t=sched.now())
    pr.start("launcher.exe", exe=r"D:\other\launcher.exe", t=sched.now())
    check("two launcher rows as a JSON list", len(preupdate_okww._wuwa_launcher_procs(timeout=5) or []) >= 1, True)
    go = pr.start("go-service.exe", exe=r"D:\ark\maaend\go-service.exe", t=sched.now())
    check("maaend_watchdog._plugin_paths", maaend_watchdog._plugin_paths(), {go.pid: r"D:\ark\maaend\go-service.exe"})
    n_before = len(pr.named("ok-ww.exe"))
    check("_spawn_via_task", preupdate_common._spawn_via_task(Path(r"D:\ark\okww\ok-ww.exe"), Path(r"D:\ark\okww"),
                                                               ("-t", "2")), True)
    check("... a World process started", len(pr.named("ok-ww.exe")), n_before + 1)
    check("... with its arguments", pr.named("ok-ww.exe")[-1].cmdline, '"D:\\ark\\okww\\ok-ww.exe" -t 2')
    require("the Mac lacks C:\\Program Files\\PowerShell\\7\\pwsh.exe: _pwsh() logs an ERROR (W5/W0 to settle)",
            bool(log_errors), "no ERROR seen")

    print("\n[8] kernel objects")
    m1 = win32event.CreateMutex(None, False, "Global\\X")
    check("first CreateMutex: last error 0", win32api.GetLastError(), 0)
    m2 = win32event.CreateMutex(None, False, "Global\\X")
    check("second: ERROR_ALREADY_EXISTS, same object", (win32api.GetLastError(), m2 is m1), (183, True))
    try:
        win32event.OpenEvent(2, False, "Global\\ArkRelayStopRequest")
        check("OpenEvent of a missing name", "opened", 2)
    except fake_win.error as exc:
        check("OpenEvent of a missing name", exc.winerror, 2)
    auto = win32event.CreateEvent(None, 0, 1, None)
    check("auto-reset: first wait takes it", win32event.WaitForSingleObject(auto, 0), win32event.WAIT_OBJECT_0)
    check("auto-reset: second finds it clear", win32event.WaitForSingleObject(auto, 0), win32event.WAIT_TIMEOUT)
    check("WTSQueryUserToken fails as on the machine", preupdate_common._tcb_enabled(), False)
    check("FormatMessage of an unknown code raises", _raises(lambda: win32api.FormatMessage(12345)), "error")

    router.uninstall()
    check("uninstall restores subprocess.run", subprocess.run is router.run, False)
    check("no real program was started", REAL_SPAWNS, [])
    check("calls were logged", len(router.calls) > 20, True)


def _raises(fn) -> str:
    try:
        fn()
    except fake_win.error:
        return "error"
    return "no error"


main()
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
