#!/usr/bin/env python3
"""The relay as a program in the logged-on user's session (the packaged install).

Same boot sequence and main loop as the Windows service (service.ArkRelayService.main
and service._loop); only the host differs. The service ran in session 0, which has no
desktop, so every screenshot, OCR read and click went through a scheduled task in the
user's session and a result file. Here the relay itself runs in that session, started
at logon by the scheduled task \\ArkRelay\\main (highest privileges: MAA runs as
administrator and a lower-privileged program cannot send input to it). The watchdog
service (packaging/watchdog/ark_watchdog.py) starts that task again when this process
is gone, and this process starts the watchdog again when it is not running and nobody
stopped it on purpose (watchdog_guard.py).

    pythonw.exe app_main.py          run (what the scheduled task does)
    python.exe  app_main.py stop     ask the running relay to stop, wait until it has
    python.exe  app_main.py rollback switch to the previous version folder and stop
    python.exe  app_main.py stop-push the last state at a Windows shutdown (the watchdog runs it)

How a stop reaches it, in place of the SCM's stop / shutdown controls:
- Windows shutting down or the user logging off: WM_ENDSESSION to a hidden top-level
  window this process owns (a message-only window does not get it).
- `app_main.py stop` (the uninstaller, the installer before replacing files): the
  named event STOP_REQUEST.
Both run the service's own SvcStop / SvcShutdown, so the last state push, closing the
phone channel and the 15-second hard exit are the same code as before.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pkg_layout  # noqa: E402

DATA = pkg_layout.data_root()

MUTEX = "Global\\ArkRelayMain"              # held while the relay runs; the watchdog looks for it
STOP_REQUEST = "Global\\ArkRelayStopRequest"
STOP_WAIT_S = 40                            # SvcStop's own hard exit is at 15 s
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
ENDSESSION_LOGOFF = 0x80000000
# Written in the data folder when WM_ENDSESSION arrives, deleted when the relay starts:
# the watchdog (packaging/watchdog/ark_watchdog.py SESSION_ENDING) does not start the
# relay again while the session it ran in is going away.
SESSION_ENDING = "session-ending.txt"
# `stop-push`: how long the watchdog's last state may take. The watchdog gives the whole
# command STOP_PUSH_WAIT_S + its own margin, inside the preshutdown time it registers.
STOP_PUSH_WAIT_S = 35
# The self-update's line in relay.log; machine check #11 (machinechecks/system.py
# SELF_UPDATE) skips a session that logged it: it ended in a restart, not a stop.
SELF_UPDATE_LINE = "代码已更新，切到新版本文件夹并重启"


def _no_console_windows() -> None:
    """Started by pythonw.exe, this process has no console, so every console program the
    relay runs (tasklist, schtasks, sc, pwsh, ...) would get a new visible console window
    on his desktop (learn.microsoft.com, "Creation of a Console"), over the games while
    they take input. In session 0 nobody saw them. Make CREATE_NO_WINDOW the default for
    every subprocess; a call that already asks for a console or detaches keeps its own."""
    import subprocess  # noqa: PLC0415
    if os.name != "nt" or sys.stdout is not None:
        return                       # a console is there (python.exe): nothing would pop up
    own = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    init = subprocess.Popen.__init__

    def popen_init(self, *args, creationflags=0, **kwargs):
        if not creationflags & own:
            creationflags |= subprocess.CREATE_NO_WINDOW
        init(self, *args, creationflags=creationflags, **kwargs)

    subprocess.Popen.__init__ = popen_init


def state_default(data: Path) -> Path:
    """The relay's state folder when .env names none (pkg_layout.state_dir)."""
    return data / "state"


def _prepare_env() -> None:
    """Data lives outside the version folder: point the relay at it before anything loads,
    then link this version folder's `state` to the one state folder."""
    state = _relay_env()
    if pkg_layout.app_root(HERE) is not None:
        pkg_layout.link_state(HERE, state)
        pkg_layout.record_running_version(HERE)


def _relay_env() -> Path:
    """The environment part of _prepare_env, also what `stop-push` (run by the watchdog
    service, which must not relink folders or rewrite the recorded version) needs.

    boot_stages reads .env from the code folder and defaults the log there; .env is
    loaded here first from the data folder (the loader never overrides a set variable,
    so the later load from the code folder finds nothing new)."""
    os.environ.setdefault("ARK_HOME", str(DATA))
    os.environ.setdefault("ARK_LOG_FILE", str(DATA / "relay.log"))
    from ark_relay.__main__ import _load_dotenv  # noqa: PLC0415
    _load_dotenv(DATA / ".env")
    # One state folder for everything, as on the old relay (config.NO_STAMINA_FARM_FLAG
    # and docs/OPERATIONS.md both use C:\ProgramData\ark-relay\state): selfupdate keeps
    # versions.code / versions.announced under <code>/state, and the boot reads
    # cfg.state_dir. <code>/state is a junction to that same folder, resolved once here
    # (.env's ARK_STATE_DIR, else <data>/state) and handed to Config as an absolute path.
    # Two different state.json files made every boot log "code version v?" (cloud
    # package smoke, 2026-10-10 22:37:41 and 22:38:00).
    os.environ.setdefault("ARK_STATE_DIR", str(state_default(DATA)))
    state = pkg_layout.state_dir(DATA)
    os.environ["ARK_STATE_DIR"] = str(state)
    return state


def _packaged_selfupdate(log) -> bool:
    """boot_stages._stage_selfupdate for the packaged install: update a copy of the
    version folder, switch to it, restart through the scheduled task. True = exit now."""
    try:
        from ark_relay.features.selfupdate import selfupdate  # noqa: PLC0415
        if changed := pkg_layout.update(HERE, selfupdate.check):
            log.info("%s: %s", SELF_UPDATE_LINE, "、".join(changed))
            pkg_layout.restart_soon(pkg_layout.app_root(HERE))
            return True
    except Exception:
        log.exception("自更新出错，跳过")
    return False


def _host_class():
    """ArkRelayService's stop code on a host without the SCM. Built on first use: importing
    service pulls in pywin32 and changes the working directory to the code folder."""
    import service  # noqa: PLC0415

    class AppHost:
        """The attributes and methods service.main, boot_stages and service._loop use."""

        _svc_name_ = service.ArkRelayService._svc_name_
        SvcStop = service.ArkRelayService.SvcStop
        SvcShutdown = service.ArkRelayService.SvcShutdown
        _wait_stop_push = service.ArkRelayService._wait_stop_push
        main = service.ArkRelayService.main
        _stop_in_boot = service.ArkRelayService._stop_in_boot

        def __init__(self) -> None:
            import win32event  # noqa: PLC0415
            # Manual reset, as in the service: three threads wait on it.
            self.stop_event = win32event.CreateEvent(None, 1, 0, None)
            self._stop_how = "停止中继"
            self._stop_asked = threading.Event()
            self._stop_pushed = threading.Event()

        def ReportServiceStatus(self, *_args) -> None:  # noqa: N802 - SvcStop calls it
            """No SCM to report to."""

    return AppHost


def _end_session_window(host) -> None:
    """A hidden top-level window: WM_ENDSESSION is how a windowed program learns that
    Windows is shutting down or the user is logging off."""
    import win32api  # noqa: PLC0415
    import win32con  # noqa: PLC0415
    import win32gui  # noqa: PLC0415

    def proc(hwnd, msg, wparam, lparam):
        if msg == win32con.WM_QUERYENDSESSION:
            return True
        if msg == win32con.WM_ENDSESSION and wparam:
            _mark_session_ending()
            # lParam carries ENDSESSION_LOGOFF on a logoff (learn.microsoft.com,
            # WM_ENDSESSION): that is a stop, not a power-off.
            if lparam & ENDSESSION_LOGOFF:
                host.SvcStop()
            else:
                host.SvcShutdown()
            # Returning lets Windows end the process; give SvcStop's push its time.
            host._stop_pushed.wait(10)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "ArkRelayEndSession"
    wc.lpfnWndProc = proc
    wc.hInstance = win32api.GetModuleHandle(None)
    win32gui.RegisterClass(wc)
    win32gui.CreateWindow(wc.lpszClassName, "ArkRelay", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
    win32gui.PumpMessages()


def _mark_session_ending() -> None:
    try:
        (DATA / SESSION_ENDING).write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"), encoding="utf-8")
    except OSError:
        pass                         # the watchdog's own shutdown flag still holds it back


def _stop_requests(host, evt) -> None:
    import win32event  # noqa: PLC0415
    win32event.WaitForSingleObject(evt, win32event.INFINITE)
    logging.getLogger("ark.app").info("收到停止请求（app_main.py stop）")
    host.SvcStop()


def run() -> int:
    import win32api  # noqa: PLC0415
    import win32event  # noqa: PLC0415
    import winerror  # noqa: PLC0415

    # Mutex and stop event first, before any setup work: a second copy leaves at once,
    # and a stop asked for while this one is still starting is not lost (stop() waits
    # for the event to appear). Both handles stay open until the process ends, so
    # "mutex gone" means the process and its loaded files are gone.
    mutex = win32event.CreateMutex(None, False, MUTEX)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return 0                     # already running: the scheduled task or the watchdog raced
    stop_evt = win32event.CreateEvent(None, 1, 0, STOP_REQUEST)
    try:
        (DATA / SESSION_ENDING).unlink(missing_ok=True)   # a session this relay runs in
    except OSError:
        pass
    _no_console_windows()
    _prepare_env()
    host = _host_class()()
    os.chdir(DATA)                   # importing service chdir'd to the code folder
    if pkg_layout.app_root(HERE) is not None:
        import boot_stages  # noqa: PLC0415
        import watchdog_guard  # noqa: PLC0415
        boot_stages._stage_selfupdate = _packaged_selfupdate
        # The watchdog starts this program again; this starts the watchdog again.
        threading.Thread(target=watchdog_guard.run, args=(host.stop_event, DATA), daemon=True,
                         name="watchdog-guard").start()
    threading.Thread(target=_end_session_window, args=(host,), daemon=True, name="end-session").start()
    threading.Thread(target=_stop_requests, args=(host, stop_evt), daemon=True, name="stop-request").start()
    log = logging.getLogger("ark.app")
    try:
        host.main()
    except Exception:
        log.exception("中继主流程出错退出")
    # As SvcDoRun after main returns: let the last push finish, then a hard exit
    # (threads stuck in C calls would hold up interpreter shutdown).
    host._wait_stop_push()
    for t in threading.enumerate():
        if t.name == "phone-heartbeat":
            t.join(3)
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    errwatch.drain(2.0)
    logging.shutdown()
    _ = (mutex, stop_evt)            # held to the end; the system closes them at exit
    os._exit(0)


MAIN_TASK = pkg_layout.MAIN_TASK
ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5


def _stop(running, ask, end_task, sleep=time.sleep, clock=time.monotonic,
          note=lambda _msg: None) -> int:
    """stop()'s loop with the Windows calls passed in (relay/tests/test_stop_denied.py).

    `ask()` sets the stop event: "asked", "not yet" (no event: the relay is still
    starting) or "denied" (the event is there but this account may not set it - a relay
    running as another account, e.g. SYSTEM on the cloud runner). Denied used to count
    as "not yet", and stop() waited its 40 s for nothing (package-windows runs
    38095462157 and 38095838036): now the task is ended at once (`schtasks /end`, the
    same fallback estop.sh uses), without the relay's last push. `note` puts a line
    in the relay's log first, so a hard end can be found afterwards (review round 9 #25)."""
    deadline = clock() + STOP_WAIT_S
    asked = ended = False
    while clock() < deadline:
        if not running():
            sleep(1)                 # the process is ending; let it unload its files
            return 0
        if not asked and not ended:
            got = ask()
            if got == "asked":
                asked = True
            elif got == "denied":
                print(f"stop event {STOP_REQUEST}: access denied (the relay runs as another "
                      f"account); ending the task {MAIN_TASK} instead", flush=True)
                note(f"停止请求被拒（中继以别的账号运行）：{_caller()} 硬结束计划任务 {MAIN_TASK}，"
                     "这次没有最后一次推送")
                end_task()
                ended = True
        sleep(1)
    return 1


def stop() -> int:
    """Ask the running relay to stop and wait until it is gone. 0 = stopped or not running."""
    import subprocess  # noqa: PLC0415
    import pywintypes  # noqa: PLC0415
    import win32api  # noqa: PLC0415
    import win32event  # noqa: PLC0415

    def running() -> bool:
        try:
            win32api.CloseHandle(win32event.OpenMutex(SYNCHRONIZE, False, MUTEX))
            return True
        except pywintypes.error as exc:
            return exc.winerror == ERROR_ACCESS_DENIED   # still there, held elevated

    def ask() -> str:
        try:
            evt = win32event.OpenEvent(EVENT_MODIFY_STATE, False, STOP_REQUEST)
        except pywintypes.error as exc:
            if exc.winerror == ERROR_ACCESS_DENIED:
                return "denied"
            return "not yet"         # ERROR_FILE_NOT_FOUND: mutex there, event not yet
        try:
            win32event.SetEvent(evt)
        finally:
            win32api.CloseHandle(evt)
        return "asked"

    def end_task() -> None:
        r = subprocess.run(["schtasks.exe", "/end", "/tn", MAIN_TASK], capture_output=True,
                           text=True, errors="replace")
        print(f"schtasks /end exit {r.returncode}: {(r.stdout + r.stderr).strip()}", flush=True)

    return _stop(running, ask, end_task, note=_log_line)


def _caller() -> str:
    """Who is stopping: account, process id, command line."""
    import getpass  # noqa: PLC0415
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "?"
    return f"账号 {user}、进程 {os.getpid()}（{' '.join(sys.argv)}）"


def _log_line(msg: str) -> None:
    """One line in the relay's log from this separate process (`app_main.py stop`), in
    the relay's own format (ark_relay/__main__.py), through its rotation-safe handler."""
    try:
        from ark_relay.core.logfile import RelayLogHandler  # noqa: PLC0415
        path = os.environ.get("ARK_LOG_FILE") or str(DATA / "relay.log")
        h = RelayLogHandler(path)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s",
                                         datefmt="%m-%d %H:%M:%S"))
        lg = logging.getLogger("ark.app.stop")
        lg.propagate = False
        lg.addHandler(h)
        try:
            lg.warning(msg)
        finally:
            lg.removeHandler(h)
            h.close()
    except Exception as exc:  # noqa: BLE001 - the stop must go on without its log line
        print(f"could not write the relay log: {exc}", flush=True)


# The words of `stop-push` in relay.log. The push's own line is phone.send_state's,
# the one machine check #11 reads (「已上报状态到手机（停止前」 / 「状态没能上报到手机（停止前」).
STOP_PUSH_START = "Windows 正在关机，中继停止前那份状态没送出去，看门服务代发"
STOP_PUSH_SKIP = "Windows 正在关机，中继停止前那份状态自己已经送到手机，看门服务不再代发"
# stop-push's own per-step limits (seconds per socket operation, one try each), set on
# this process only: the ntfy notice after the state is on COS, each Skland call of the
# fresh session the state carries, each official-site read for tomorrow's plan.
STOP_PUSH_NOTICE_S = 5
STOP_PUSH_SKLAND_S = 4
STOP_PUSH_SITE_S = 4


def stop_push(wait_s: float = STOP_PUSH_WAIT_S) -> int:
    """`app_main.py stop-push`: the last 「停止前」 state at a Windows shutdown, sent from
    the watchdog service (packaging/watchdog/ark_watchdog.py, SERVICE_CONTROL_PRESHUTDOWN).

    The relay sends that state itself from WM_ENDSESSION (service.SvcStop), but it is a
    program in the user's session, and those end before any service is told of the
    shutdown; a forced one (`shutdown /r /t 5`: /t above 0 implies /f) ends it without
    waiting, cutting the push off (relay.log 2026-10-11 14:25:10: the stop notice, then
    nothing until the next boot). A service gets its preshutdown notice after that, with
    time to finish. Same data folder and .env as the relay, the same push and log line
    (phone.send_state), nothing else of the relay's start-up (_relay_env, not
    _prepare_env). 0 = sent, 1 = not sent (the line says why), 2 = nothing to send: the
    relay's own push already got out (phone.STOP_PUSHED_FILE) or no phone mailbox is set.

    Every step is bounded so the push ends well inside wait_s (2026-10-11 15:41:53, the
    first real run: the payload took 15 s, 4 of them on two refused AUTO-MAS calls; the
    state was on COS and its ntfy notice reached ntfy at 15:42:09, but the notice's
    answer never came back and the 20 s wait for it ran the 35 s out - a delivered state
    logged as not delivered). So: errwatch.mark_stopping() makes snapshot.read skip the
    AUTO-MAS sections (the backend is gone, as at the relay's own stop); the notice gets
    one try of STOP_PUSH_NOTICE_S (a state stored on COS counts as delivered without it,
    Mailbox.publish); Skland and the official sites get short limits and one try. Whatever
    still hangs (a DNS lookup, which socket time-outs do not cover) meets wait_s."""
    state = _relay_env()
    from ark_relay.__main__ import _setup_logging  # noqa: PLC0415
    _setup_logging(verbose=False)
    log = logging.getLogger("ark.app.stop_push")
    from ark_relay.features.phone import phone  # noqa: PLC0415
    if phone.stop_pushed(state):
        log.info(STOP_PUSH_SKIP)
        return 2
    from ark_relay.core.config import Config  # noqa: PLC0415
    cfg = Config()
    box = phone.Mailbox(cfg.phone_topic, cfg.phone_pin, cfg.state_dir, cos=phone.state_cos(cfg))
    if not box.enabled:
        return 2
    log.info(STOP_PUSH_START)
    _stop_push_limits(box)
    marks = _time_phases(box)
    sent: list = []
    worker = threading.Thread(target=lambda: sent.append(phone.send_state(box, cfg, phone.STOP_WHY, log)),
                              daemon=True, name="stop-push")
    worker.start()
    worker.join(wait_s)
    log.info("看门服务代发用时：%s", _phases(marks))
    if not sent:
        log.warning("状态没能上报到手机（%s）：看门服务等了 %.0f 秒还没发完，Windows 要关机了不再等；"
                    "手机上留着上一份状态", phone.STOP_WHY, wait_s)
        return 1
    return 0 if sent[0][0] else 1


def _stop_push_limits(box) -> None:
    """stop-push's per-step limits (stop_push docstring), on this process only."""
    from ark_relay.core import skland  # noqa: PLC0415
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
    errwatch.mark_stopping()
    box.POST_TIMEOUT, box.ATTEMPTS = STOP_PUSH_NOTICE_S, 1
    skland._TIMEOUT = STOP_PUSH_SKLAND_S
    maintenance.GET_TIMEOUT, maintenance.GET_ATTEMPTS = STOP_PUSH_SITE_S, 1


def _time_phases(box) -> dict:
    """When the state was built, stored on COS and sent on, for the timing line: the
    next real shutdown says where the time went instead of leaving a silent gap."""
    marks = {"start": time.monotonic()}
    publish, cos_put = box.publish, getattr(box, "_cos_put", None)

    def timed_publish(body, *a, **k):
        marks["payload"] = time.monotonic()
        try:
            return publish(body, *a, **k)
        finally:
            marks["publish"] = time.monotonic()

    def timed_cos(data):
        try:
            return cos_put(data)
        finally:
            marks["cos"] = time.monotonic()

    box.publish = timed_publish
    if cos_put is not None:
        box._cos_put = timed_cos
    return marks


def _phases(marks: dict) -> str:
    now, t0 = time.monotonic(), marks["start"]
    parts = [f"状态拼好 {marks['payload'] - t0:.1f} 秒" if "payload" in marks else "状态没拼完"]
    if "cos" in marks:
        parts.append(f"存腾讯云到 {marks['cos'] - t0:.1f} 秒")
    parts.append(f"发完到 {marks['publish'] - t0:.1f} 秒" if "publish" in marks else f"到 {now - t0:.1f} 秒还没发完")
    return "，".join(parts)


def _stop_push_exit() -> int:
    """stop_push, then a hard exit: a send still stuck in a socket read must not hold the
    process (the watchdog waits for it) in interpreter shutdown."""
    try:
        code = stop_push()
    except Exception:  # logged where the relay's errors go
        logging.getLogger("ark.app.stop_push").exception("看门服务代发停止前那份状态出错")
        code = 1
    logging.shutdown()
    os._exit(code)


def rollback() -> int:
    app = pkg_layout.app_root(HERE)
    if app is None:
        print("not a packaged install")
        return 2
    prev = pkg_layout.rollback(app)
    if prev is None:
        print("no earlier version folder")
        return 1
    print(f"current -> {prev}")
    stop()
    pkg_layout.restart_soon(app)
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    raise SystemExit({"run": run, "stop": stop, "rollback": rollback,
                      "stop-push": _stop_push_exit}[cmd]())
