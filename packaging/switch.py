"""The steps the installer and the uninstaller run, in order, in one readable place.

    python.exe switch.py install [--skip-handover]   from the installer, after the files
    python.exe switch.py uninstall                   from the uninstaller, before the files go
    python.exe switch.py stop                        from the installer, before it replaces files;
                                                     by hand, to keep the relay down (docs/OPERATIONS.md)
    python.exe switch.py start                       by hand: the way back after `stop` (watchdog, task)
    python.exe switch.py revert                      by hand: says the way back is `launch.py
                                                     rollback` (exit 6); changes nothing
    python.exe switch.py resume [--current=<name>]   from the installer, when it ends between
                                                     `stop` and `install` (cancelled, a file
                                                     that could not be copied)

The rule for all of them: whichever step fails, the machine is left with a relay that
runs - the new one or the old one.

install: refuse while the old relay is present (below) -> hand AUTO-MAS its jobs
(relay/handover/automas_handover.py: plan must pass, then apply) -> register the logon task -> register and start the watchdog
-> start the relay (with someone at the console: running within 60 s and still 15 s
later, else a failure;
nobody there: the watchdog starts it at logon). If any step fails, everything is reverted (as `revert`) and the old
relay is switched back on; exit code 1, and the installer exits non-zero too.
--skip-handover is for a machine without AUTO-MAS (the cloud test).

The old relay (service ark-relay) was retired on 2026-10-11 (scripts/windows/retire_legacy.py,
BOARD DECISIONS 【现状 10-12】), so nothing here switches it on or off any more. install
refuses while it is still present (exit 8): two relays would both push and power off.

revert: there is no old relay to go back to: nothing changes, exit 6, and it says the way
back is the previous version folder (`launch.py rollback`).

resume: an upgrade ran `stop` and then ended before `install` - he pressed Cancel, or a
file could not be replaced and Setup rolled back. Nothing else would start the relay
before his next logon, so the version that ran before is started again: current.txt goes
back to --current (the name the installer read before `stop`) when it names something
else and that folder is complete, then the watchdog and the task start as at the end of
an install.

uninstall: removes everything - the new relay and what the old relay left
(legacy.py remove, relay/handover/legacy-items.json); only his data
(C:\\ProgramData\\ark-relay: .env, state, logs) and his settings backups stay.
First the watchdog and the relay stop and AUTO-MAS's settings are put back. If that
cannot be done (AUTO-MAS busy or not answering), nothing is removed: the relay is started
again, exit code 3, and the uninstaller stops before deleting anything and says why.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# The embedded runtime has a ._pth file, which turns on isolated mode
# (docs.python.org/3/library/sys_path_init.html); -I implies -P, "don't prepend the
# script's directory" (docs.python.org/3/using/cmdline.html). legacy.py sits next to
# this file. Cloud run 38090475340 exited 1 here before writing a log.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import legacy

APP = Path(__file__).resolve().parent
PY = APP / "runtime" / "python" / "python.exe"
PYW = APP / "runtime" / "python" / "pythonw.exe"
TASK_PATH, TASK_NAME = "\\ArkRelay\\", "main"
WATCHDOG = "ArkRelayWatchdog"
HANDOVER = APP / "handover" / "automas_handover.py"
STATE = legacy.DATA / "state"
MUTEX = "Global\\ArkRelayMain"     # held by relay/app_main.py while it runs
START_WAIT_S = 60
STEADY_S = 15        # still running this long after its mutex showed = it stayed up
# The watchdog has to reach RUNNING; each start is given this long (the SCM's own start
# timeout is 30 s by default) and is tried this many times.
WATCHDOG_WAIT_S = 45
WATCHDOG_TRIES = 3
# "Stopped on purpose": the relay starts a stopped watchdog again (relay/watchdog_guard.py
# MARKER) unless this file was written since the last boot. Written before every stop
# here, deleted by every start.
WATCHDOG_MARKER = legacy.DATA / "watchdog-stopped.txt"
# An update's restart helper (pkg_layout.restart_soon: pythonw.exe launch.py relaunch);
# the same match as scripts/mac/estop.sh, in PowerShell -like wildcards.
HELPER_LIKE = "*launch.py*relaunch*"


def run(*cmd: "str | Path") -> int:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    print(" ".join(map(str, cmd)), "->", r.returncode)
    for out in (r.stdout, r.stderr):
        if out.strip():
            print(out.rstrip())
    return r.returncode


def _console_session_user() -> str:
    """The user logged on at the console, '' when nobody is."""
    import win32ts  # noqa: PLC0415
    sid = win32ts.WTSGetActiveConsoleSessionId()
    if sid == 0xFFFFFFFF:
        return ""
    name = win32ts.WTSQuerySessionInformation(None, sid, win32ts.WTSUserName)
    if not name:
        return ""
    domain = win32ts.WTSQuerySessionInformation(None, sid, win32ts.WTSDomainName)
    return f"{domain}\\{name}" if domain else name


def main_running() -> bool:
    """The relay's mutex exists. Access denied means it exists, held by the elevated
    relay (the phone page's and the watchdog's rule)."""
    import pywintypes  # noqa: PLC0415
    import win32api  # noqa: PLC0415
    import win32event  # noqa: PLC0415
    try:
        win32api.CloseHandle(win32event.OpenMutex(0x00100000, False, MUTEX))  # SYNCHRONIZE
        return True
    except pywintypes.error as exc:
        return exc.winerror == 5


def console_user(setup_user: str) -> str:
    """Whoever is logged on at the machine's console; else the user who ran Setup.

    {username} in the installer is the account Setup runs as, which is a different
    admin when Setup was elevated with someone else's credentials; the relay has to
    start in the session at the screen, where the games are."""
    try:
        user = _console_session_user()
        if user:
            return user
    except Exception as e:  # noqa: BLE001 - no console session is a normal case
        print("console user unknown:", e)
    return setup_user


def register_task(user: str) -> int:
    """At logon of `user`, in that session, highest privileges (MAA runs as administrator
    and a lower-privileged program cannot send it input), no execution time limit (the
    default ends a task after 72 hours), never a second copy, normal priority (a task's
    default is 7, below normal, and the programs it starts inherit that;
    learn.microsoft.com, TaskSettings.Priority: 4-6 are the normal priority class)."""
    ps = (f"$a=New-ScheduledTaskAction -Execute '{PYW}' -Argument '\"{APP / 'launch.py'}\"';"
          f"$t=New-ScheduledTaskTrigger -AtLogOn -User '{user}';"
          f"$p=New-ScheduledTaskPrincipal -UserId '{user}' -LogonType Interactive -RunLevel Highest;"
          "$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) "
          "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew "
          "-Priority 4;"
          f"Register-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{TASK_NAME}' "
          "-Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null")
    return run("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps)


def _mark_watchdog_stopped(on: bool) -> None:
    try:
        if on:
            WATCHDOG_MARKER.parent.mkdir(parents=True, exist_ok=True)
            WATCHDOG_MARKER.write_text(time.strftime("%Y-%m-%d %H:%M:%S switch.py\n"), encoding="utf-8")
        else:
            WATCHDOG_MARKER.unlink(missing_ok=True)
    except OSError as exc:
        print("watchdog marker:", exc)


def stop_watchdog() -> None:
    """`sc stop` returns at once; wait until the service has really stopped, so its
    pythonservice.exe no longer holds the runtime's DLLs the installer is replacing.
    The marker goes first, so the relay (still running until launch.py stop) does not
    start the watchdog again meanwhile; should it be running again anyway, stop it again."""
    import pywintypes  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415
    _mark_watchdog_stopped(True)
    run("sc.exe", "stop", WATCHDOG)
    for _ in range(30):
        try:
            state = win32serviceutil.QueryServiceStatus(WATCHDOG)[1]
        except pywintypes.error:
            return                   # not installed
        if state == win32service.SERVICE_STOPPED:
            return
        if state == win32service.SERVICE_RUNNING:
            run("sc.exe", "stop", WATCHDOG)
        time.sleep(1)
    print("watchdog still not stopped after 30 s")


def start_watchdog() -> int:
    """Start the watchdog and wait until it is RUNNING; 0 = it is.

    `sc start` returns while the service is still START_PENDING, and one that ends during
    its start is not brought back by its failure actions: cloud run 38095391114, first
    switch-over, START_PENDING, then STOPPED without its 「看门服务启动」 line, still
    stopped 30 s later (the next two installs started it at once). So each start is
    watched, and a start that ends stopped is tried again."""
    import pywintypes  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415
    state = None
    _mark_watchdog_stopped(False)
    for attempt in range(1, WATCHDOG_TRIES + 1):
        run("sc.exe", "start", WATCHDOG)      # 1056: already started or starting
        deadline = time.monotonic() + WATCHDOG_WAIT_S
        while time.monotonic() < deadline:
            try:
                state = win32serviceutil.QueryServiceStatus(WATCHDOG)[1]
            except pywintypes.error as exc:
                print("watchdog status unknown:", exc)
                return 1
            if state == win32service.SERVICE_RUNNING:
                if attempt > 1:
                    print(f"watchdog running (start attempt {attempt})")
                return 0
            if state == win32service.SERVICE_STOPPED:
                break
            time.sleep(1)
        print(f"watchdog not running after start attempt {attempt} (state {state})")
    return 1


def end_relaunch_helpers() -> int:
    """End any update restart helper. Within two minutes of a self-update or rollback
    one is waiting for the relay to exit so it can start it again; at an upgrade it would
    bring the relay back under the installer (and its pythonw.exe holds the runtime's
    DLLs), at an uninstall leave one running (review round 8 #23). The helper gives up
    by itself once a running watchdog stops, but not one that started while the watchdog
    was down, and not a helper from a package before that change."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" -EA SilentlyContinue | "
          f"Where-Object {{ $_.CommandLine -like '{HELPER_LIKE}' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue; "
          "Write-Output ('helper ended: ' + $_.ProcessId) }")
    return run("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps)


def stop() -> int:
    """Watchdog first (it would start the relay again), then any update restart helper
    (likewise), then the relay; all waited for."""
    stop_watchdog()
    end_relaunch_helpers()
    return run(PY, APP / "launch.py", "stop")


def start() -> int:
    """Start the watchdog (which deletes the stop marker) and run the logon task: the way
    back after `stop` when no switch-over follows. The task runs even when the watchdog
    did not come up: the relay's guard starts it then (relay/watchdog_guard.py), the
    marker being gone. 0 = the watchdog is running."""
    rc = start_watchdog()
    run("schtasks.exe", "/run", "/tn", TASK_PATH + TASK_NAME)
    return rc


def _restore_current(name: str) -> None:
    """current.txt back to `name`, the version folder in use before the upgrade.

    Setup's rollback deletes only the files that did not exist before; a file it had
    already replaced keeps the new content (Inno Setup, Setup.UninstallLog.pas: rollback
    skips utDeleteFile records flagged utDeleteFile_ExistedBeforeInstall, and nothing
    restores them). So a cancel after current.txt was copied leaves it naming the new
    version, whose folder the rollback may have removed. Written as
    relay/pkg_layout._set_current does (that module lives in the version folders)."""
    path = APP / "current.txt"
    try:
        now = path.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        now = ""
    if not name or now == name:
        print(f"current.txt: {now or '(none)'}, unchanged")
        return
    if not (APP / "versions" / name / "app_main.py").is_file():
        print(f"current.txt left on {now or '(none)'}: the previous version {name} is not complete")
        return
    try:
        tmp = APP / "current.txt.tmp"
        tmp.write_text(name + "\n", encoding="ascii")
        os.replace(tmp, path)
        print(f"current.txt: {now or '(none)'} -> {name} (in use before the upgrade)")
    except OSError as exc:
        print("current.txt not written:", exc)


def resume(current: str) -> int:
    """After `stop`, Setup ended without `install`: start the version that ran before.
    0 = its watchdog is running."""
    _restore_current(current)
    return start()


def _handover_rollback() -> int:
    """Put back the AUTO-MAS settings the handover changed. 0 = done or nothing to do."""
    if not (STATE / "automas-handover.json").exists():
        return 0
    rc = run(PY, HANDOVER, "rollback", "--state-dir", STATE)
    if rc != 0:
        print("AUTO-MAS settings NOT put back (exit %d): state/automas-handover.json still "
              "holds the old values; run `switch.py uninstall` again once AUTO-MAS is idle" % rc)
    return rc


def _switch_on_new() -> None:
    run("sc.exe", "config", WATCHDOG, "start=", "auto")
    run("schtasks.exe", "/change", "/tn", TASK_PATH + TASK_NAME, "/enable")
    start_watchdog()
    run("schtasks.exe", "/run", "/tn", TASK_PATH + TASK_NAME)


def revert() -> int:
    """By hand. Once it switched back to the old relay; that relay is retired, so nothing
    changes: 6, and the way back named is the previous version folder."""
    print("没有退回：老中继已经撤掉了，没有老中继可以退。新中继照常在跑，什么都没改。"
          "要退回请用新版的上一个版本："
          f'"{PY}" "{APP / "launch.py"}" rollback')
    return 6


def _back_to_old_after_failed_install() -> None:
    """The switch-over failed part way: there is no old relay to switch on, so the new
    one is switched on again as it is (the watchdog retries it and alerts), AUTO-MAS's
    settings stay handed over, and the way back is the previous version folder."""
    print("old relay retired: the new relay is switched on again as it is; go back "
          f'with "{PY}" "{APP / "launch.py"}" rollback')
    _switch_on_new()


def install(user: str, skip_handover: bool) -> int:
    user = console_user(user)
    print("task user:", user)
    if legacy.old_relay_present():
        # Stopping and disabling it was legacy.takeover(), removed with the old relay's
        # retirement; starting the new relay next to it would have both push and power off.
        print(f"没有切换：老中继（服务 {legacy.OLD_SERVICE}）还在这台电脑上，两个中继不能同时跑。"
              "新中继没有打开；先撤掉老中继（scripts/windows/retire_legacy.py --go）再装。")
        return 8
    # An upgrade over an earlier install: the handover is done and its backup holds the
    # settings from before the first one; doing it again could only change more.
    if (STATE / "automas-handover.json").exists():
        print("AUTO-MAS handover already done (state/automas-handover.json): skipped")
        skip_handover = True
    if not skip_handover:
        if run(PY, HANDOVER, "plan", "--state-dir", STATE) != 0 or \
                run(PY, HANDOVER, "apply", "--state-dir", STATE) != 0:
            print("AUTO-MAS handover failed: putting its settings back and the old relay back on")
            _back_to_old_after_failed_install()
            return 1
    steps = [
        lambda: register_task(user),
        lambda: run(PY, APP / "watchdog" / "ark_watchdog.py", "install"),
        lambda: run("sc.exe", "config", WATCHDOG, "start=", "auto"),
        lambda: run("sc.exe", "failure", WATCHDOG, "reset=", "60",
                    "actions=", "restart/3000/restart/3000/restart/3000"),
        start_watchdog,
    ]
    for step in steps:
        if step() != 0:
            print("switch-over failed after the handover: reverting to the old relay")
            _back_to_old_after_failed_install()
            return 1
    # The task runs only in the user's logon session. Nobody at the console yet (Setup
    # over RDP, a fresh boot, the cloud test) is a normal state: the watchdog runs the
    # task once someone logs on. With someone there, the new relay must really come
    # up (its mutex), or the old one goes back on - a machine without a working relay
    # would otherwise wait for the watchdog's third failed start to say so.
    try:
        at_console = _console_session_user()
    except Exception as e:  # noqa: BLE001
        print("console user unknown:", e)
        at_console = ""
    started = run("schtasks.exe", "/run", "/tn", TASK_PATH + TASK_NAME) == 0
    if not at_console:
        print("nobody logged on at the console: the watchdog starts the relay at logon")
        return 0
    # A relay that dies during its boot holds the mutex for a moment too, so it has to be
    # there again STEADY_S later. Gone by then is not final at once: a first boot that
    # updates itself exits and comes back through the task (pkg_layout.restart_soon).
    deadline = time.monotonic() + START_WAIT_S
    while time.monotonic() < deadline:
        if main_running():
            time.sleep(STEADY_S)
            if main_running():
                print(f"relay running, still up {STEADY_S} s later")
                return 0
            print(f"relay came up and was gone again within {STEADY_S} s")
        time.sleep(2)
    print(f"relay not running steadily {START_WAIT_S} s after the start (schtasks /run "
          f"{'ok' if started else 'failed'}, {at_console} at the console): reverting "
          "to the old relay")
    _back_to_old_after_failed_install()
    return 1


def uninstall() -> int:
    stop()
    if _handover_rollback() != 0:
        # Removing now would leave AUTO-MAS with the handover's settings and nobody
        # holding the old ones: keep everything, start the relay again, say so.
        start()
        return 3
    for v in (APP / "versions").iterdir() if (APP / "versions").is_dir() else []:
        link = v / "state"
        if os.path.isjunction(link) or link.is_symlink():
            os.rmdir(link)        # removes the link only, never the data it points to
    run(PY, APP / "watchdog" / "ark_watchdog.py", "remove")
    _mark_watchdog_stopped(False)          # no watchdog left to keep down
    run("schtasks.exe", "/delete", "/tn", TASK_PATH + TASK_NAME, "/f")
    delete_task_folder()
    legacy.remove()
    return 0


def delete_task_folder(connect=None) -> bool:
    """Remove the now empty \\ArkRelay\\ folder in Task Scheduler: `schtasks /delete`
    removes the task and leaves its folder, and schtasks has no verb for folders. The Task
    Scheduler COM API has one (ITaskFolder::DeleteFolder, flags 0; it fails while the
    folder still holds a task, which then stays visible). Never fails the uninstall.
    `connect` returns a connected Schedule.Service (tests pass a fake)."""
    name = TASK_PATH.strip("\\")
    try:
        if connect is None:
            import win32com.client  # noqa: PLC0415 - pywin32 is in the package's runtime

            def connect():
                svc = win32com.client.Dispatch("Schedule.Service")
                svc.Connect()
                return svc
        connect().GetFolder("\\").DeleteFolder(name, 0)
    except Exception as e:  # noqa: BLE001
        print(f"task folder \\{name} not deleted:", e)
        return False
    print(f"task folder \\{name} deleted")
    return True


class _Tee:
    """Everything this script prints also goes to <data>\\switch.log: the installer's
    Exec keeps only the exit code, and the data folder survives an uninstall."""

    def __init__(self, *streams) -> None:
        self.streams = [s for s in streams if s is not None]

    def write(self, text: str) -> int:
        for s in self.streams:
            s.write(text)
            s.flush()
        return len(text)

    def flush(self) -> None:
        for s in self.streams:
            s.flush()


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        legacy.DATA.mkdir(parents=True, exist_ok=True)
        _log = open(legacy.DATA / "switch.log", "a", encoding="utf-8")
        _log.write(f"\n== {time.strftime('%Y-%m-%d %H:%M:%S')} switch.py {' '.join(args)}\n")
        sys.stdout = _Tee(sys.stdout, _log)
        sys.stderr = _Tee(sys.stderr, _log)
    except OSError:
        pass
    if args[:1] == ["install"]:
        user = next((a.split("=", 1)[1] for a in args if a.startswith("--user=")), "")
        raise SystemExit(install(user, "--skip-handover" in args))
    if args[:1] == ["stop"]:
        raise SystemExit(stop())
    if args[:1] == ["start"]:
        raise SystemExit(start())
    if args[:1] == ["uninstall"]:
        raise SystemExit(uninstall())
    if args[:1] == ["revert"]:
        raise SystemExit(revert())
    if args[:1] == ["resume"]:
        raise SystemExit(resume(next((a.split("=", 1)[1] for a in args
                                      if a.startswith("--current=")), "")))
    print(__doc__)
    raise SystemExit(2)
