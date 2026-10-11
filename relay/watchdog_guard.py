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

A start counts only when the service reaches RUNNING and is still RUNNING STEADY_S later
(_start, as packaging/switch.py start_watchdog does): `StartService` returns while the
service is START_PENDING, and the one in cloud run 38095391114 stopped right there. A
start that ends stopped, or not running within START_WAIT_S, is a failure; so is finding
it stopped again at the next look after a start that did work (it did not stay up). Each
failure is logged (INFO); FAIL_LIMIT in a row log one ERROR, which errwatch pushes to the
group (docs/NOTIFICATIONS.md, 「🩺 中继自己报错了」), once until a look finds it running.
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
# packaging/switch.py WATCHDOG_WAIT_S: the SCM's own start timeout is 30 s by default.
START_WAIT_S = 45
STEADY_S = 5           # still RUNNING this long after it first showed RUNNING = it came up
# The two ERRORs errwatch pushes to the group as they are (test_watchdog_copy.py: plain()).
ALERT_GAVE_UP = ("看门服务留不住：中继连着 %d 次查看都发现它停了（%s）。它不在的时候，"
                 "中继自己停了就没人重开，要人到游戏机上看一眼。")
ALERT_CANNOT_LOOK = ("中继连着 %d 次查不了看门服务在不在跑（%s），它停了中继也没法重新打开它，"
                     "要人到游戏机上看一眼。")

log = logging.getLogger("ark.watchdog_guard")


class Guard:
    """The decisions, apart from the service calls (relay/tests/test_watchdog_guard.py)."""

    def __init__(self, query, start, marker_this_boot) -> None:
        # query() -> (state, start_type): "RUNNING" / "STOPPED" / "PENDING" / "MISSING",
        # "AUTO" / "DISABLED" / "OTHER"; start() -> "" when it came up and stayed (_start),
        # why not otherwise, None when the relay is stopping meanwhile.
        self.query, self.start, self.marker_this_boot = query, start, marker_this_boot
        self.fails = 0
        self.alerted = False
        self.just_started = False        # the last look started it, and that start worked

    def tick(self) -> str:
        """One look; returns what it did, for the log and the tests."""
        state, start_type = self.query()
        # Only the look right before this one counts as "the last start": any other look
        # in between (on purpose, pending, disabled) clears it.
        stayed_down, self.just_started = self.just_started, False
        if state == "RUNNING":
            if self.fails:
                log.info("看门服务又在跑了（之前连续 %d 次没能让它一直跑着）", self.fails)
            self.fails, self.alerted = 0, False
            return "running"
        if state != "STOPPED":
            return state.lower()                 # missing, or on its way up / down
        if start_type != "AUTO":
            return "disabled"
        if self.marker_this_boot():
            return "stopped on purpose"
        # The count is reset only by a look that finds it running: a watchdog that comes
        # up and stops again before the next look must still reach the ERROR.
        why = self.start()
        if why is None:
            return "relay stopping"
        self.just_started = not why
        if why:
            self.failed(why)
            return "start failed"
        if stayed_down:
            self.failed("上次重新打开后没撑到这次查看，又停了，这次又打开了")
            return "started again"
        log.info("看门服务没在跑（不是有人停的），已重新打开，确认在跑")
        return "started"

    def failed(self, why: str, looked: bool = True) -> None:
        """A start that did not work (looked), or a look that raised: INFO each time, one
        ERROR (pushed by errwatch) at FAIL_LIMIT in a row, none again until it runs."""
        self.fails += 1
        what = "看门服务停了，没能让它一直跑着" if looked else "查不了看门服务在不在跑"
        log.info("%s（%s），连续第 %d 次", what, why, self.fails)
        if self.fails >= FAIL_LIMIT and not self.alerted:
            log.error(ALERT_GAVE_UP if looked else ALERT_CANNOT_LOOK, self.fails, why)
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


def _start(wait=time.sleep, clock=time.monotonic) -> "str | None":
    """Start the watchdog and watch it come up: "" once it has been RUNNING for STEADY_S,
    else why not; None when wait() says the relay is stopping.

    The same watch as packaging/switch.py start_watchdog, not shared with it: switch.py
    sits in the install folder, written by the installer and a deploy but never by the
    self-update, while this runs from a version folder that self-updates; it also deletes the stop marker, prints instead
    of logging and tries 3 times in a row, where the guard's next look is the next try.
    wait(seconds) -> True when the relay is stopping (run() waits on its stop event)."""
    import pywintypes  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415
    try:
        win32serviceutil.StartService(NAME)
    except pywintypes.error as exc:
        # 1056 ERROR_SERVICE_ALREADY_RUNNING: started, or still starting - watched all the same.
        if exc.winerror != 1056:
            return f"{exc.winerror} {exc.strerror}"
    deadline = clock() + START_WAIT_S
    running_since = None
    was_running = False
    while True:
        try:
            state = win32serviceutil.QueryServiceStatus(NAME)[1]
        except pywintypes.error as exc:
            return f"开了以后查不了它的状态：{exc.winerror} {exc.strerror}"
        now = clock()
        if state == win32service.SERVICE_RUNNING:
            was_running = True
            if running_since is None:
                running_since = now
            elif now - running_since >= STEADY_S:
                return ""
        elif state == win32service.SERVICE_STOPPED:
            return "刚跑起来就又停了" if was_running else "开到一半自己停了"
        else:
            running_since = None                 # pending: on its way up, or down again
            if now >= deadline:
                return "跑起来后又一直在停" if was_running else f"开了 {START_WAIT_S} 秒还没跑起来"
        if wait(1):
            return None


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
    def stopping(seconds: float) -> bool:
        return win32event.WaitForSingleObject(stop_event, int(seconds * 1000)) != win32event.WAIT_TIMEOUT

    guard = Guard(_query, lambda: _start(stopping), lambda: marker_this_boot(data / MARKER, boot_time()))
    wait = first
    while win32event.WaitForSingleObject(stop_event, wait * 1000) == win32event.WAIT_TIMEOUT:
        wait = every
        try:
            guard.tick()
        except Exception as exc:  # noqa: BLE001 - one bad look must not end the guard
            guard.failed(repr(exc), looked=False)
