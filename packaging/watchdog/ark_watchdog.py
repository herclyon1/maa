"""ArkRelayWatchdog: a Windows service that keeps the relay's main program running.

The relay runs in the logged-on user's session (relay/app_main.py, started at logon by
the scheduled task \\ArkRelay\\main). This service only:
  1. looks every CHECK_S seconds for the mutex the relay holds while it runs;
  2. when it is gone and someone is logged on, runs the scheduled task again
     (the task, not CreateProcessAsUser: a program started that way read 0 lines of
     OCR where the scheduled task read 45, commit 1737aede);
  3. after FAIL_LIMIT failed starts in a row, pushes one line to the WeCom group
     bot itself - the relay that normally pushes is the thing that is down (08-15);
  4. when Windows shuts down, sends the relay's last 「停止前」 state to the phone page
     unless the relay's own push already got out (last_push, below).
It passes no business messages of its own and runs the relay's code only through
launch.py, so it needs no version handshake. Windows restarts it if it dies (failure
actions set by the installer).

Why the shutdown push is here. The relay is a program in the user's session; it hears
of a shutdown through WM_ENDSESSION and pushes then, but programs in the user's session
are shut down before services are (learn.microsoft.com, LPHANDLER_FUNCTION_EX remarks:
the applications' shutdown notification "occurs before services are shut down"), and a
forced shutdown - `shutdown /r /t 5`, where /t above 0 implies /f (learn.microsoft.com,
windows-commands/shutdown) - ends them without waiting: 2026-10-11 14:25:10 the relay
logged its stop notice and nothing after it. A service that accepts
SERVICE_ACCEPT_PRESHUTDOWN is told after that, before SERVICE_CONTROL_SHUTDOWN, and the
SCM waits until it stops or its preshutdown time-out runs out (default 10 s since build
15063; install() sets PRESHUTDOWN_MS). pywin32's ServiceFramework advertises only STOP,
PAUSE_CONTINUE and SHUTDOWN (GetAcceptedControls) and hands any other control to
SvcOtherEx, so both are overridden below.

    python.exe ark_watchdog.py install   register (auto start); the installer runs it
    python.exe ark_watchdog.py remove    unregister; the uninstaller runs it
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pywintypes
import servicemanager
import win32api
import win32event
import win32service
import win32serviceutil
import win32ts

NAME = "ArkRelayWatchdog"
MAIN_TASK = r"\ArkRelay\main"
MUTEX = "Global\\ArkRelayMain"
SYNCHRONIZE = 0x00100000
SM_SHUTTINGDOWN = 0x2000
CHECK_S = 30
FAIL_LIMIT = 3
NOBODY_LIMIT_S = 15 * 60
DATA = Path(os.environ.get("ARK_HOME") or r"C:\ProgramData\ark-relay")
# The two group-bot messages, both rows of docs/NOTIFICATIONS.md's route table (group:
# a person has to act). Plain words only: relay/tests/test_watchdog_copy.py runs them
# through texts.plain(), the check every relay push passes.
ALERT_DOWN = ("🔌 中继停了，自己重开没成功\n"
              "游戏机上的中继没在跑，重开了 {n} 次（每次隔 {s} 秒）都没起来，要人到机器上看一眼。")
ALERT_NOBODY = ("🔌 游戏机开着，没人登录\n"
                "游戏机开着已经 15 分钟，桌面没有人登录，中继要登录以后才会跑。要人登录一下。")
LOG = DATA / "watchdog.log"
APP = Path(__file__).resolve().parents[1]      # {app}: watchdog\ark_watchdog.py, launch.py
# relay/app_main.py SESSION_ENDING: the relay writes it when its session ends (logoff or
# shutdown) and deletes it when it starts. Programs in that session are going away, so a
# relay started then would only be cut off again - and a shutdown push it took over
# would be lost. Held at most ENDING_HOLD_S: a logoff with nobody logging on again is
# then an ordinary "nobody logged on".
SESSION_ENDING = DATA / "session-ending.txt"
ENDING_HOLD_S = 10 * 60
# Shutdown push budget, all inside the preshutdown time-out install() registers: wait up
# to ALIVE_WAIT_S for a relay still running to finish its own push, then give
# `launch.py stop-push` (relay/app_main.py STOP_PUSH_WAIT_S = 35 s for the send itself)
# PUSH_TIMEOUT_S including the Python start. The SCM moves on at PRESHUTDOWN_MS anyway.
PRESHUTDOWN_MS = 60_000
ALIVE_WAIT_S = 5
PUSH_TIMEOUT_S = 45


def _log(line: str) -> None:
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def main_running() -> bool:
    try:
        h = win32event.OpenMutex(SYNCHRONIZE, False, MUTEX)
    except pywintypes.error as exc:
        # Access denied: it exists, held by an elevated process (the phone page's rule).
        return exc.winerror == 5
    win32api.CloseHandle(h)
    return True


def someone_logged_on() -> bool:
    sid = win32ts.WTSGetActiveConsoleSessionId()
    if sid == 0xFFFFFFFF:
        return False
    try:
        user = win32ts.WTSQuerySessionInformation(win32ts.WTS_CURRENT_SERVER_HANDLE, sid, win32ts.WTSUserName)
    except pywintypes.error:
        return False
    return bool(user)


def session_ending(now: float) -> bool:
    """The relay's session is ending (SESSION_ENDING written within ENDING_HOLD_S)."""
    try:
        return now - SESSION_ENDING.stat().st_mtime < ENDING_HOLD_S
    except OSError:
        return False


def run_stop_push(timeout: float) -> str:
    """`launch.py stop-push` (relay/app_main.py stop_push) with the install's python.exe
    (runtime\\python, packaging/build.py): the code of the version folder current.txt
    names, its log lines in relay.log."""
    py = APP / "runtime" / "python" / "python.exe"
    try:
        r = subprocess.run([str(py), str(APP / "launch.py"), "stop-push"], capture_output=True,
                           timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return f"{timeout:.0f} 秒没结束，不再等"
    except OSError as exc:
        return f"起不来（{exc}）"
    return {0: "送到了", 1: "没送到（原因在 relay.log）", 2: "不用发"}.get(r.returncode, f"退出码 {r.returncode}")


def last_push(relay_running=None, push=run_stop_push, sleep=time.sleep, clock=time.monotonic) -> str:
    """Windows is shutting down: send the relay's 「停止前」 state if the relay could not.

    A relay still running is given ALIVE_WAIT_S to finish its own push and exit (the
    docs put the user's programs first, so normally it is gone already). Then
    `stop-push` runs once; it sends nothing when the relay's own push got out (the
    relay's marker, phone.STOP_PUSHED_FILE), so the phone gets one state, not two."""
    relay_running = relay_running or main_running
    deadline = clock() + ALIVE_WAIT_S
    while relay_running() and clock() < deadline:
        sleep(0.5)
    return push(PUSH_TIMEOUT_S)


def start_main() -> bool:
    r = subprocess.run(["schtasks", "/run", "/tn", MAIN_TASK], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return r.returncode == 0


def _env(name: str) -> str:
    """A value from the relay's .env, read each time (no restart needed after an edit)."""
    try:
        for line in (DATA / ".env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == name:
                return value.split("#")[0].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get(name, "")


def _bot_url() -> str:
    """WECOM_BOT_URL from the relay's .env (the same group bot the relay pushes to)."""
    return _env("WECOM_BOT_URL")


def _test_no_logon() -> bool:
    """CI only (scripts/ci/package_smoke.py): the runner has no logged-on session, so
    the test runs the task without one and sets this to skip the logon check below."""
    return _env("ARK_WATCHDOG_TEST_NO_LOGON") == "1"


def push(text: str) -> None:
    url = _bot_url()
    if not url:
        _log("想进群但没有 WECOM_BOT_URL：" + text)
        return
    body = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            _log(f"进群：{text}（{resp.status}）")
    except OSError as exc:
        _log(f"进群失败（{exc}）：{text}")


class Watch:
    """The decisions, apart from the service plumbing."""

    def __init__(self, now: float) -> None:
        self.fails = 0
        self.alerted = False
        self.nobody_since: "float | None" = None
        self.nobody_alerted = False
        self.started = now
        self.shutting_down = False      # set on SERVICE_CONTROL_PRESHUTDOWN

    def tick(self, now: float) -> None:
        # SM_SHUTTINGDOWN asks about this service's own session 0, which is not the one
        # that ends first; the preshutdown flag and the relay's marker cover the rest.
        if self.shutting_down or win32api.GetSystemMetrics(SM_SHUTTINGDOWN) or session_ending(time.time()):
            return
        if main_running():
            if self.alerted:
                _log("主程序又跑起来了")     # the group hears only what needs a person (CLAUDE.md)
            self.fails, self.alerted = 0, False
            self.nobody_since, self.nobody_alerted = None, False
            return
        if not someone_logged_on() and not _test_no_logon():
            self.nobody_since = self.nobody_since or now
            if now - self.nobody_since >= NOBODY_LIMIT_S and not self.nobody_alerted:
                push(ALERT_NOBODY)
                self.nobody_alerted = True
            return
        self.nobody_since = None
        ok = start_main()
        self.fails += 1
        _log(f"主程序不在，跑了一次计划任务（{'成功' if ok else '失败'}），连续第 {self.fails} 次")
        if self.fails >= FAIL_LIMIT and not self.alerted:
            push(ALERT_DOWN.format(n=self.fails, s=CHECK_S))
            self.alerted = True


class WatchdogService(win32serviceutil.ServiceFramework):
    _svc_name_ = NAME
    _svc_display_name_ = "Ark Relay watchdog"
    _svc_description_ = "Starts the Ark Relay main program again when it is not running."

    def __init__(self, args) -> None:
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 1, 0, None)
        self.watch = Watch(time.monotonic())

    def GetAcceptedControls(self) -> int:  # noqa: N802 - pywin32 hook
        """STOP and SHUTDOWN as pywin32 works them out, plus PRESHUTDOWN (module docstring)."""
        return super().GetAcceptedControls() | win32service.SERVICE_ACCEPT_PRESHUTDOWN

    def SvcOtherEx(self, control, event_type, data):  # noqa: N802 - pywin32 hook
        if control != win32service.SERVICE_CONTROL_PRESHUTDOWN:
            return super().SvcOtherEx(control, event_type, data)
        # A control handler returns at once (learn.microsoft.com, "Service Control
        # Handler Function"): the push runs in SvcDoRun's thread once the loop ends.
        self.watch.shutting_down = True
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=PRESHUTDOWN_MS)
        win32event.SetEvent(self.stop_event)
        return None

    def SvcStop(self) -> None:  # noqa: N802 - name required by the framework
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcShutdown(self) -> None:  # noqa: N802 - Windows is going down: just stop
        self.SvcStop()

    def SvcDoRun(self) -> None:  # noqa: N802
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ""))
        _log("看门服务启动")
        while win32event.WaitForSingleObject(self.stop_event, CHECK_S * 1000) == win32event.WAIT_TIMEOUT:
            try:
                self.watch.tick(time.monotonic())
            except Exception as exc:  # noqa: BLE001 - the watchdog itself must keep going
                _log(f"检查出错：{exc!r}")
        if self.watch.shutting_down:
            try:
                _log(f"Windows 关机，停止前那份状态：{last_push()}")
            except Exception as exc:  # noqa: BLE001 - shutdown goes on regardless
                _log(f"Windows 关机，停止前那份状态出错：{exc!r}")
        _log("看门服务停止")


def install() -> None:
    """Register with pythonservice.exe next to this Python (packaging/build.py puts it there)."""
    exe = Path(sys.executable).with_name("pythonservice.exe")
    args = (win32serviceutil.GetServiceClassString(WatchdogService), NAME)
    kwargs = dict(startType=win32service.SERVICE_AUTO_START, exeName=str(exe),
                  displayName=WatchdogService._svc_display_name_,
                  description=WatchdogService._svc_description_)
    try:
        win32serviceutil.InstallService(*args, **kwargs)
    except pywintypes.error as exc:
        if exc.winerror != 1073:        # ERROR_SERVICE_EXISTS: an upgrade, update it
            raise
        win32serviceutil.ChangeServiceConfig(*args, **kwargs)
    try:
        set_preshutdown_timeout()
    except Exception as exc:  # noqa: BLE001 - the default 10 s still sends most pushes: never fail the install
        print("preshutdown timeout not set:", exc)


def set_preshutdown_timeout(ms: int = PRESHUTDOWN_MS) -> None:
    """Give the shutdown push its time: SERVICE_CONFIG_PRESHUTDOWN_INFO (ChangeServiceConfig2;
    learn.microsoft.com, SERVICE_PRESHUTDOWN_INFO - the SCM waits for the service to stop
    or this much, whichever comes first, so a stuck push never holds shutdown longer)."""
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        svc = win32service.OpenService(scm, NAME, win32service.SERVICE_CHANGE_CONFIG)
        try:
            win32service.ChangeServiceConfig2(svc, win32service.SERVICE_CONFIG_PRESHUTDOWN_INFO, ms)
        finally:
            win32service.CloseServiceHandle(svc)
    finally:
        win32service.CloseServiceHandle(scm)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(WatchdogService)
        servicemanager.StartServiceCtrlDispatcher()
    elif sys.argv[1] == "install":
        install()
    else:
        win32serviceutil.HandleCommandLine(WatchdogService)
