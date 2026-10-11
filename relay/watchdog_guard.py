"""The relay keeps its watchdog running: the other half of the two guarding each other.

The watchdog service ArkRelayWatchdog (packaging/watchdog/ark_watchdog.py) starts the
relay again when it is gone. Nothing started the watchdog again: Windows starts it once
at boot (a start that fails then is not retried - cloud run 38095391114 saw one stop
during START_PENDING and stay stopped), and its failure actions cover a crash, not a
start that never came up or a clean stop. So the relay (app_main.run, packaged install
only) looks FIRST_S after it starts and every EVERY_S after that:

  RUNNING / START_PENDING / STOP_PENDING ... nothing to do;
  STOPPED, start type automatic, no stop marker from this boot ... start it;
  start type disabled (switch.py revert, a failed switch-over) ... stopped on purpose;
  a stop marker written this boot ... stopped on purpose (below);
  not installed (a machine on the old relay, a dev run) ... nothing to do.

Stopped on purpose: switch.py stop_watchdog (the installer before it replaces files,
uninstall, revert) and scripts/mac/estop.sh write MARKER into the data folder before
`sc stop`; switch.py start_watchdog and `estop.sh --restore` delete it. A marker older
than the current boot is ignored: Windows starts the watchdog again at every boot, so
whatever stop it recorded is over, and one left by a crashed installer must not keep
the watchdog down for good.

A start that fails is logged (INFO); FAIL_LIMIT failures in a row log one ERROR, which
errwatch pushes to the group (docs/NOTIFICATIONS.md, 「🩺 中继自己报错了」), once until
the watchdog runs again.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

NAME = "ArkRelayWatchdog"
MARKER = "watchdog-stopped.txt"      # packaging/switch.py WATCHDOG_MARKER, scripts/mac/estop.sh
FIRST_S = 60
EVERY_S = 180
FAIL_LIMIT = 3

log = logging.getLogger("ark.watchdog_guard")


class Guard:
    """The decisions, apart from the service calls (relay/tests/test_watchdog_guard.py)."""

    def __init__(self, query, start, marker_this_boot) -> None:
        # query() -> (state, start_type): "RUNNING" / "STOPPED" / "PENDING" / "MISSING",
        # "AUTO" / "DISABLED" / "OTHER"; start() -> "" when started, else why not.
        self.query, self.start, self.marker_this_boot = query, start, marker_this_boot
        self.fails = 0
        self.alerted = False

    def tick(self) -> str:
        """One look; returns what it did, for the log and the tests."""
        state, start_type = self.query()
        if state == "RUNNING":
            if self.fails:
                log.info("看门服务又在跑了（之前连续 %d 次没拉起来）", self.fails)
            self.fails, self.alerted = 0, False
            return "running"
        if state != "STOPPED":
            return state.lower()                 # missing, or on its way up / down
        if start_type != "AUTO":
            return "disabled"
        if self.marker_this_boot():
            return "stopped on purpose"
        why = self.start()
        if not why:
            log.info("看门服务没在跑（不是有人停的），已重新拉起")
            self.fails, self.alerted = 0, False
            return "started"
        self.failed(why)
        return "start failed"

    def failed(self, why: str, looked: bool = True) -> None:
        """A start that did not work (looked), or a look that raised: INFO each time, one
        ERROR (pushed by errwatch) at FAIL_LIMIT in a row, none again until it runs."""
        self.fails += 1
        what = "看门服务没在跑，拉起失败" if looked else "查不了看门服务在不在跑"
        log.info("%s（%s），连续第 %d 次", what, why, self.fails)
        if self.fails >= FAIL_LIMIT and not self.alerted:
            if looked:
                log.error("看门服务停了，中继连续 %d 次没能把它拉起来（%s）。看门服务不在，中继自己"
                          "停了就没人重开，要人到游戏机上看一眼。", self.fails, why)
            else:
                log.error("中继连续 %d 次查不了看门服务在不在跑（%s），它停了也拉不回来，"
                          "要人到游戏机上看一眼。", self.fails, why)
            self.alerted = True


# ---------- Windows ----------

def _query() -> "tuple[str, str]":
    import pywintypes  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415
    try:
        state = win32serviceutil.QueryServiceStatus(NAME)[1]
    except pywintypes.error as exc:
        if exc.winerror == 1060:                 # ERROR_SERVICE_DOES_NOT_EXIST
            return "MISSING", "OTHER"
        raise
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        svc = win32service.OpenService(scm, NAME, win32service.SERVICE_QUERY_CONFIG)
        try:
            start_type = win32service.QueryServiceConfig(svc)[1]
        finally:
            win32service.CloseServiceHandle(svc)
    finally:
        win32service.CloseServiceHandle(scm)
    return ({win32service.SERVICE_RUNNING: "RUNNING",
             win32service.SERVICE_STOPPED: "STOPPED"}.get(state, "PENDING"),
            {win32service.SERVICE_AUTO_START: "AUTO",
             win32service.SERVICE_DISABLED: "DISABLED"}.get(start_type, "OTHER"))


def _start() -> str:
    import pywintypes  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415
    try:
        win32serviceutil.StartService(NAME)
    except pywintypes.error as exc:
        if exc.winerror != 1056:                 # ERROR_SERVICE_ALREADY_RUNNING
            return f"{exc.winerror} {exc.strerror}"
    return ""


def boot_time() -> float:
    """When Windows booted, as a time.time() value (GetTickCount64: ms since boot)."""
    import ctypes  # noqa: PLC0415
    k32 = ctypes.windll.kernel32
    k32.GetTickCount64.restype = ctypes.c_ulonglong
    return time.time() - k32.GetTickCount64() / 1000


def marker_this_boot(path: Path, booted: float) -> bool:
    try:
        return path.stat().st_mtime >= booted
    except OSError:
        return False


def _seconds(name: str, default: int) -> int:
    """FIRST_S / EVERY_S, shortened by the cloud test through the data folder's .env
    (app_main has loaded it into the environment)."""
    try:
        return max(1, int(os.environ.get(name, "")))
    except ValueError:
        return default


def run(stop_event, data: Path) -> None:
    """The thread app_main starts; ends when the relay stops (stop_event set)."""
    import win32event  # noqa: PLC0415
    first, every = _seconds("ARK_WDGUARD_FIRST_S", FIRST_S), _seconds("ARK_WDGUARD_EVERY_S", EVERY_S)
    # Boot time read at each look: the wall clock can be corrected after a cold boot,
    # and the marker's mtime is on the corrected one.
    guard = Guard(_query, _start, lambda: marker_this_boot(data / MARKER, boot_time()))
    wait = first
    while win32event.WaitForSingleObject(stop_event, wait * 1000) == win32event.WAIT_TIMEOUT:
        wait = every
        try:
            guard.tick()
        except Exception as exc:  # noqa: BLE001 - one bad look must not end the guard
            guard.failed(repr(exc), looked=False)
