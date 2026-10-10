"""The steps the installer and the uninstaller run, in order, in one readable place.

    python.exe switch.py install [--skip-handover]   from the installer, after the files
    python.exe switch.py uninstall                   from the uninstaller, before the files go

install: stop the old relay -> hand AUTO-MAS its jobs (relay/handover/automas_handover.py:
plan must pass, then apply) -> register the logon task -> register and start the watchdog
-> start the relay. When the handover fails, nothing new is registered and the old relay
is switched back on, so the machine is never left with no relay; exit code 1.
--skip-handover is for a machine without AUTO-MAS (the cloud test).

uninstall: stop the watchdog and the relay -> put AUTO-MAS's settings back -> remove the
version folders' state junctions -> unregister the watchdog and the task -> remove what
the old relay left (legacy.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
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


def register_task(user: str) -> int:
    """At logon of `user`, in that session, highest privileges (MAA runs as administrator
    and a lower-privileged program cannot send it input), no execution time limit (the
    default ends a task after 72 hours), never a second copy."""
    ps = (f"$a=New-ScheduledTaskAction -Execute '{PYW}' -Argument '\"{APP / 'launch.py'}\"';"
          f"$t=New-ScheduledTaskTrigger -AtLogOn -User '{user}';"
          f"$p=New-ScheduledTaskPrincipal -UserId '{user}' -LogonType Interactive -RunLevel Highest;"
          "$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) "
          "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew;"
          f"Register-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{TASK_NAME}' "
          "-Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null")
    return run("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps)


def install(user: str, skip_handover: bool) -> int:
    legacy.takeover()
    if not skip_handover:
        if run(PY, HANDOVER, "plan", "--state-dir", STATE) != 0 or \
                run(PY, HANDOVER, "apply", "--state-dir", STATE) != 0:
            print("AUTO-MAS handover failed: putting its settings back and the old relay back on")
            run(PY, HANDOVER, "rollback", "--state-dir", STATE)
            legacy.undo_takeover()
            return 1
    steps = [
        lambda: register_task(user),
        lambda: run(PY, APP / "watchdog" / "ark_watchdog.py", "install"),
        lambda: run("sc.exe", "failure", WATCHDOG, "reset=", "60",
                    "actions=", "restart/3000/restart/3000/restart/3000"),
        lambda: run("sc.exe", "start", WATCHDOG),
        lambda: run("schtasks.exe", "/run", "/tn", TASK_PATH + TASK_NAME),
    ]
    return 1 if any(step() != 0 for step in steps) else 0


def uninstall() -> int:
    run("sc.exe", "stop", WATCHDOG)
    run(PY, APP / "launch.py", "stop")
    if (STATE / "automas-handover.json").exists():
        run(PY, HANDOVER, "rollback", "--state-dir", STATE)
    for v in (APP / "versions").iterdir() if (APP / "versions").is_dir() else []:
        link = v / "state"
        if os.path.isjunction(link) or link.is_symlink():
            os.rmdir(link)        # removes the link only, never the data it points to
    run(PY, APP / "watchdog" / "ark_watchdog.py", "remove")
    run("schtasks.exe", "/delete", "/tn", TASK_PATH + TASK_NAME, "/f")
    legacy.remove()
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["install"]:
        user = next((a.split("=", 1)[1] for a in args if a.startswith("--user=")), "")
        raise SystemExit(install(user, "--skip-handover" in args))
    raise SystemExit(uninstall())
