#!/usr/bin/env python3
"""The relay as a program in the logged-on user's session (the packaged install).

Same boot sequence and main loop as the Windows service (service.ArkRelayService.main
and service._loop); only the host differs. The service ran in session 0, which has no
desktop, so every screenshot, OCR read and click went through a scheduled task in the
user's session and a result file. Here the relay itself runs in that session, started
at logon by the scheduled task \\ArkRelay\\main (highest privileges: MAA runs as
administrator and a lower-privileged program cannot send input to it). The watchdog
service (packaging/watchdog/ark_watchdog.py) starts that task again when this process
is gone.

    pythonw.exe app_main.py          run (what the scheduled task does)
    python.exe  app_main.py stop     ask the running relay to stop, wait until it has
    python.exe  app_main.py rollback switch to the previous version folder and stop

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


def _prepare_env() -> None:
    """Data lives outside the version folder: point the relay at it before anything loads.

    boot_stages reads .env from the code folder and defaults the log there; .env is
    loaded here first from the data folder (the loader never overrides a set variable,
    so the later load from the code folder finds nothing new)."""
    os.environ.setdefault("ARK_HOME", str(DATA))
    os.environ.setdefault("ARK_LOG_FILE", str(DATA / "relay.log"))
    from ark_relay.__main__ import _load_dotenv  # noqa: PLC0415
    _load_dotenv(DATA / ".env")
    # The old relay's default was "./ark-state" with the working directory at the data
    # folder (config.py state_dir); the same folder, spelled out, when .env names none.
    os.environ.setdefault("ARK_STATE_DIR", str(DATA / "ark-state"))
    if pkg_layout.app_root(HERE) is not None:
        pkg_layout.link_state(HERE, DATA)
        pkg_layout.record_running_version(HERE)


def _packaged_selfupdate(log) -> bool:
    """boot_stages._stage_selfupdate for the packaged install: update a copy of the
    version folder, switch to it, restart through the scheduled task. True = exit now."""
    try:
        from ark_relay import selfupdate  # noqa: PLC0415
        if changed := pkg_layout.update(HERE, selfupdate.check):
            log.info("代码已更新，切到新版本文件夹并重启: %s", "、".join(changed))
            pkg_layout.restart_soon()
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
    _no_console_windows()
    _prepare_env()
    host = _host_class()()
    os.chdir(DATA)                   # importing service chdir'd to the code folder
    if pkg_layout.app_root(HERE) is not None:
        import boot_stages  # noqa: PLC0415
        boot_stages._stage_selfupdate = _packaged_selfupdate
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
    from ark_relay import errwatch  # noqa: PLC0415
    errwatch.drain(2.0)
    logging.shutdown()
    _ = (mutex, stop_evt)            # held to the end; the system closes them at exit
    os._exit(0)


def stop() -> int:
    """Ask the running relay to stop and wait until it is gone. 0 = stopped or not running."""
    import pywintypes  # noqa: PLC0415
    import win32api  # noqa: PLC0415
    import win32event  # noqa: PLC0415

    def running() -> bool:
        try:
            win32api.CloseHandle(win32event.OpenMutex(SYNCHRONIZE, False, MUTEX))
            return True
        except pywintypes.error:
            return False

    deadline = time.monotonic() + STOP_WAIT_S
    asked = False
    while time.monotonic() < deadline:
        if not running():
            time.sleep(1)            # the process is ending; let it unload its files
            return 0
        if not asked:
            try:
                evt = win32event.OpenEvent(EVENT_MODIFY_STATE, False, STOP_REQUEST)
                win32event.SetEvent(evt)
                win32api.CloseHandle(evt)
                asked = True
            except pywintypes.error:
                pass                 # mutex there, event not yet: retry
        time.sleep(1)
    return 1


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
    pkg_layout.restart_soon()
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    raise SystemExit({"run": run, "stop": stop, "rollback": rollback}[cmd]())
