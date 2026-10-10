"""The steps the installer and the uninstaller run, in order, in one readable place.

    python.exe switch.py install [--skip-handover]   from the installer, after the files
    python.exe switch.py uninstall                   from the uninstaller, before the files go
    python.exe switch.py stop                        from the installer, before it replaces files
    python.exe switch.py revert                      back to the old relay (by hand)

The rule for all of them: whichever step fails, the machine is left with a relay that
runs - the new one or the old one.

install: stop the old relay -> hand AUTO-MAS its jobs (relay/handover/automas_handover.py:
plan must pass, then apply) -> register the logon task -> register and start the watchdog
-> start the relay. If any step fails, everything is reverted (as `revert`) and the old
relay is switched back on; exit code 1, and the installer exits non-zero too.
--skip-handover is for a machine without AUTO-MAS (the cloud test).

revert: the way back to the old relay, without uninstalling: stop and switch off the new
one (watchdog disabled, task disabled; files stay), put AUTO-MAS's settings back, switch
the old relay back on. Running the installer again switches over again.

uninstall: removes everything - the new relay, the old relay and what it left
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

import legacy

APP = Path(__file__).resolve().parent
PY = APP / "runtime" / "python" / "python.exe"
PYW = APP / "runtime" / "python" / "pythonw.exe"
TASK_PATH, TASK_NAME = "\\ArkRelay\\", "main"
WATCHDOG = "ArkRelayWatchdog"
HANDOVER = APP / "handover" / "automas_handover.py"
STATE = legacy.DATA / "state"


def run(*cmd: "str | Path") -> int:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    print(" ".join(map(str, cmd)), "->", r.returncode)
    for out in (r.stdout, r.stderr):
        if out.strip():
            print(out.rstrip())
    return r.returncode


def console_user(setup_user: str) -> str:
    """Whoever is logged on at the machine's console; else the user who ran Setup.

    {username} in the installer is the account Setup runs as, which is a different
    admin when Setup was elevated with someone else's credentials; the relay has to
    start in the session at the screen, where the games are."""
    try:
        import win32ts  # noqa: PLC0415
        sid = win32ts.WTSGetActiveConsoleSessionId()
        name = win32ts.WTSQuerySessionInformation(None, sid, win32ts.WTSUserName)
        domain = win32ts.WTSQuerySessionInformation(None, sid, win32ts.WTSDomainName)
        if name:
            return f"{domain}\\{name}" if domain else name
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


def stop_watchdog() -> None:
    """`sc stop` returns at once; wait until the service has really stopped, so its
    pythonservice.exe no longer holds the runtime's DLLs the installer is replacing."""
    import pywintypes  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415
    run("sc.exe", "stop", WATCHDOG)
    for _ in range(30):
        try:
            state = win32serviceutil.QueryServiceStatus(WATCHDOG)[1]
        except pywintypes.error:
            return                   # not installed
        if state == win32service.SERVICE_STOPPED:
            return
        time.sleep(1)
    print("watchdog still not stopped after 30 s")


def stop() -> int:
    """Watchdog first (it would start the relay again), then the relay; both waited for."""
    stop_watchdog()
    return run(PY, APP / "launch.py", "stop")


def _handover_rollback() -> int:
    """Put back the AUTO-MAS settings the handover changed. 0 = done or nothing to do."""
    if not (STATE / "automas-handover.json").exists():
        return 0
    rc = run(PY, HANDOVER, "rollback", "--state-dir", STATE)
    if rc != 0:
        print("AUTO-MAS settings NOT put back (exit %d): state/automas-handover.json still "
              "holds the old values; run `switch.py revert` or `uninstall` again once "
              "AUTO-MAS is idle" % rc)
    return rc


def _switch_off_new() -> None:
    """Stop the new relay and keep it from starting again; its files stay."""
    stop()
    run("sc.exe", "config", WATCHDOG, "start=", "disabled")
    run("schtasks.exe", "/change", "/tn", TASK_PATH + TASK_NAME, "/disable")


def revert() -> int:
    """Back to the old relay. 0 = the old relay is on and AUTO-MAS is as before."""
    _switch_off_new()
    rc = _handover_rollback()
    old = legacy.undo_takeover()
    if old != 0:
        print("the old relay did not start: is it still installed? (sc query ark-relay)")
    return 1 if rc or old else 0


def install(user: str, skip_handover: bool) -> int:
    user = console_user(user)
    print("task user:", user)
    legacy.takeover()
    # An upgrade over an earlier install: the handover is done and its backup holds the
    # settings from before the first one; doing it again could only change more.
    if (STATE / "automas-handover.json").exists():
        print("AUTO-MAS handover already done (state/automas-handover.json): skipped")
        skip_handover = True
    if not skip_handover:
        if run(PY, HANDOVER, "plan", "--state-dir", STATE) != 0 or \
                run(PY, HANDOVER, "apply", "--state-dir", STATE) != 0:
            print("AUTO-MAS handover failed: putting its settings back and the old relay back on")
            revert()
            return 1
    steps = [
        lambda: register_task(user),
        lambda: run(PY, APP / "watchdog" / "ark_watchdog.py", "install"),
        lambda: run("sc.exe", "config", WATCHDOG, "start=", "auto"),   # after a revert
        lambda: run("sc.exe", "failure", WATCHDOG, "reset=", "60",
                    "actions=", "restart/3000/restart/3000/restart/3000"),
        lambda: run("sc.exe", "start", WATCHDOG),
        lambda: run("schtasks.exe", "/run", "/tn", TASK_PATH + TASK_NAME),
    ]
    for step in steps:
        if step() != 0:
            print("switch-over failed after the handover: reverting to the old relay")
            revert()
            return 1
    return 0


def uninstall() -> int:
    stop()
    if _handover_rollback() != 0:
        # Removing now would leave AUTO-MAS with the handover's settings and nobody
        # holding the old ones: keep everything, start the relay again, say so.
        run("sc.exe", "start", WATCHDOG)
        run("schtasks.exe", "/run", "/tn", TASK_PATH + TASK_NAME)
        return 3
    for v in (APP / "versions").iterdir() if (APP / "versions").is_dir() else []:
        link = v / "state"
        if os.path.isjunction(link) or link.is_symlink():
            os.rmdir(link)        # removes the link only, never the data it points to
    run(PY, APP / "watchdog" / "ark_watchdog.py", "remove")
    run("schtasks.exe", "/delete", "/tn", TASK_PATH + TASK_NAME, "/f")
    legacy.remove()
    return 0


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
        _log = open(legacy.DATA / "switch.log", "a", encoding="utf-8")  # noqa: SIM115
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
    if args[:1] == ["uninstall"]:
        raise SystemExit(uninstall())
    if args[:1] == ["revert"]:
        raise SystemExit(revert())
    print(__doc__)
    raise SystemExit(2)
