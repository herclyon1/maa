"""Start the relay from the version folder named in current.txt (the packaged install).

The scheduled task \\ArkRelay\\main runs `runtime\\python\\pythonw.exe launch.py`. This file
sits outside the version folders and never changes, so an update or a rollback only has
to rewrite current.txt. `launch.py stop` / `launch.py rollback` pass through to app_main.

`launch.py relaunch` (started by pkg_layout.restart_soon, detached) waits until the relay
that started it has exited - its mutex is gone - and runs the task again. It lives here,
not in a version folder, because the folder it would restart into may hold other code.
It gives up, without a start, once the watchdog service it saw running stops:
switch.py stop() (before an upgrade, uninstall and revert) and estop.sh stop the
watchdog first, and a start then would hold the files the installer replaces or leave
a relay running after an uninstall (review round 8 #23). deploy-pkg.sh does not stop the
watchdog: it switches current.txt first, then `launch.py stop` and its own task run, so
a helper start there only races that run (the task ignores the second, the mutex lets
one relay through) and either one starts the folder just deployed (review round 9 #26).
"""
import runpy
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
MUTEX = "Global\\ArkRelayMain"          # relay/app_main.py
MAIN_TASK = "\\ArkRelay\\main"
WATCHDOG = "ArkRelayWatchdog"           # packaging/switch.py, watchdog/ark_watchdog.py
EXIT_WAIT_S = 120                      # app_main's own stop gives up after 15 s, then exits
TASK_UP_S = 10                         # after a /run, how long until the mutex must show
TASK_TRIES = 3


def _key(name):
    head, _, tail = name.partition("-")
    return (int(head), int(tail or 0)) if (head + tail).isdigit() else (0, 0)


def _code_folder():
    """current.txt's folder; when that is missing or broken, the newest complete one
    (otherwise every start would fail the same way until someone fixed the file)."""
    try:
        cur = APP / "versions" / (APP / "current.txt").read_text(encoding="ascii").strip()
        if (cur / "app_main.py").is_file():
            return cur
    except (OSError, ValueError):
        pass
    ok = [p for p in (APP / "versions").iterdir()
          if not p.name.startswith(".") and (p / "app_main.py").is_file()]
    return max(ok, key=lambda p: _key(p.name))


def _main_running() -> bool:
    """The relay's mutex exists (access denied: it exists, held by the elevated relay)."""
    import pywintypes  # noqa: PLC0415 - the package's Python has pywin32
    import win32api  # noqa: PLC0415
    import win32event  # noqa: PLC0415
    try:
        win32api.CloseHandle(win32event.OpenMutex(0x00100000, False, MUTEX))  # SYNCHRONIZE
        return True
    except pywintypes.error as exc:
        return exc.winerror == 5


def _run_task() -> None:
    subprocess.run(["schtasks.exe", "/run", "/tn", MAIN_TASK], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _watchdog_stopping() -> "bool | None":
    """True: the watchdog is stopped or stopping; False: any other state; None: it is
    not installed (or cannot be asked), which counts as stopped."""
    import pywintypes  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415
    try:
        state = win32serviceutil.QueryServiceStatus(WATCHDOG)[1]
    except pywintypes.error:
        return None
    return state in (win32service.SERVICE_STOPPED, win32service.SERVICE_STOP_PENDING)


def relaunch(running=_main_running, run_task=_run_task, sleep=time.sleep,
             clock=time.monotonic, watchdog_stopping=_watchdog_stopping) -> int:
    """Wait for the relay to exit, then start it through the task. `schtasks /run` on a
    task whose process still runs is ignored (MultipleInstances IgnoreNew), so the start
    waits for the mutex to go, not for a fixed time, and is tried again if the relay
    does not show. 0 = running again, 1 = the old one never exited, 2 = no start took,
    3 = the watchdog was stopped meanwhile: someone is stopping the relay on purpose.

    Only a change counts: when the watchdog is already down as the helper starts (CI's
    package_smoke stage 4c, a machine in maintenance) the helper is the only thing that
    brings the relay back and it does. Known limits: a stop() that comes while the
    watchdog was already down is not seen; a watchdog that crashes reads as stopped for
    the moment before Windows restarts it, and then it starts the relay itself."""
    watched = watchdog_stopping() is False

    def stopped_since() -> bool:
        return watched and watchdog_stopping() is not False

    deadline = clock() + EXIT_WAIT_S
    while running():
        if stopped_since():
            return 3
        if clock() > deadline:
            return 1
        sleep(0.5)
    for _ in range(TASK_TRIES):
        if stopped_since():
            return 3
        run_task()
        up_by = clock() + TASK_UP_S
        while clock() < up_by:
            if running():
                return 0
            sleep(0.5)
    return 2


def main() -> None:
    if sys.argv[1:2] == ["relaunch"]:
        raise SystemExit(relaunch())
    code = _code_folder()
    sys.path.insert(0, str(code))
    sys.argv[0] = str(code / "app_main.py")
    runpy.run_path(str(code / "app_main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
