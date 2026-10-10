"""ArkRelayWatchdog: a Windows service that keeps the relay's main program running.

The relay runs in the logged-on user's session (relay/app_main.py, started at logon by
the scheduled task \\ArkRelay\\main). This service only:
  1. looks every CHECK_S seconds for the mutex the relay holds while it runs;
  2. when it is gone and someone is logged on, runs the scheduled task again
     (the task, not CreateProcessAsUser: a program started that way read 0 lines of
     OCR where the scheduled task read 45, commit 1737aede);
  3. after FAIL_LIMIT failed starts in a row, pushes one line to the WeCom group
     bot itself - the relay that normally pushes is the thing that is down (08-15).
It passes no business messages and never changes, so it needs no version handshake.
Windows restarts it if it dies (failure actions set by the installer).

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
LOG = DATA / "watchdog.log"


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
    except pywintypes.error:
        return False
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

    def tick(self, now: float) -> None:
        if win32api.GetSystemMetrics(SM_SHUTTINGDOWN):
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
                push("游戏机开着，但 15 分钟没人登录桌面，中继主程序起不来。")
                self.nobody_alerted = True
            return
        self.nobody_since = None
        ok = start_main()
        self.fails += 1
        _log(f"主程序不在，跑了一次计划任务（{'成功' if ok else '失败'}），连续第 {self.fails} 次")
        if self.fails >= FAIL_LIMIT and not self.alerted:
            push(f"中继主程序连续 {self.fails} 次没拉起来（每次隔 {CHECK_S} 秒），机器上要有人看一下。")
            self.alerted = True


class WatchdogService(win32serviceutil.ServiceFramework):
    _svc_name_ = NAME
    _svc_display_name_ = "Ark Relay watchdog"
    _svc_description_ = "Starts the Ark Relay main program again when it is not running."

    def __init__(self, args) -> None:
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 1, 0, None)

    def SvcStop(self) -> None:  # noqa: N802 - name required by the framework
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcShutdown(self) -> None:  # noqa: N802 - Windows is going down: just stop
        self.SvcStop()

    def SvcDoRun(self) -> None:  # noqa: N802
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ""))
        _log("看门服务启动")
        watch = Watch(time.monotonic())
        while win32event.WaitForSingleObject(self.stop_event, CHECK_S * 1000) == win32event.WAIT_TIMEOUT:
            try:
                watch.tick(time.monotonic())
            except Exception as exc:  # noqa: BLE001 - the watchdog itself must keep going
                _log(f"检查出错：{exc!r}")
        _log("看门服务停止")


def install() -> None:
    """Register with pythonservice.exe next to this Python (packaging/build.py puts it there)."""
    exe = Path(sys.executable).with_name("pythonservice.exe")
    win32serviceutil.InstallService(
        win32serviceutil.GetServiceClassString(WatchdogService), NAME,
        WatchdogService._svc_display_name_, startType=win32service.SERVICE_AUTO_START,
        exeName=str(exe), description=WatchdogService._svc_description_)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(WatchdogService)
        servicemanager.StartServiceCtrlDispatcher()
    elif sys.argv[1] == "install":
        install()
    else:
        win32serviceutil.HandleCommandLine(WatchdogService)
