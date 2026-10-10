"""What the relay left on the game machine before it was an installed program, and what
the installer / uninstaller does with each item.

    python.exe legacy.py takeover   at install: stop the old relay so two never run at
                                    once (both would push and power off); its files stay
                                    so the old relay can be switched back on
    python.exe legacy.py remove     at uninstall: delete every item below except data

Every item here is written out by name: what is on the machine has to be readable from
this file (the user, 10-11: 「看代码就说得清」). Data the user may want kept (.env,
state, logs) is not touched here; the uninstaller asks about it separately.
"""
from __future__ import annotations

import fnmatch
import shutil
import subprocess
import sys
from pathlib import Path

PD = Path(r"C:\ProgramData")
OLD_ROOT = PD / "ark-relay"           # the old install: code and data in one folder

# The old relay service (C:\Program Files\Python314\pythonservice.exe, sc qc ark-relay,
# read on the machine 10-11 03:40).
OLD_SERVICES = ["ark-relay"]

# Scheduled tasks ours by name. `\ark-relay` is the logon launcher disabled since
# 08-15 23:42; the others are created by relay code at run time
# (ark_relay/preupdate_common.py _spawn_via_task: ark-preupdate-launch-<program>;
# ark_relay/echofarm.py: ark-okww-farm, ark-okww-stop) or by scripts/windows/setup-tasks.ps1
# and the operator tools (ark-do, ark-shot, ark-focus-watch, ark-gui, ark-okww).
# AUTO-MAS_AutoStart is AUTO-MAS's own task and is left alone.
OLD_TASKS = ["ark-relay", "ark-gui", "ark-okww", "ark-okww-farm", "ark-okww-stop",
             "ark-do", "ark-shot", "ark-focus-watch"]
OLD_TASK_PATTERNS = ["ark-preupdate-launch-*"]

# Files of the old install (code, not data) under C:\ProgramData\ark-relay.
OLD_CODE = ["ark_relay", "run.py", "service.py", "boot_stages.py", "manifest.json",
            "RELEASE-NOTES.md", "ark-relay.ps1", "requirements.txt", "make-manifest.py",
            "USER-SWITCHES.txt", "README.md", "app_main.py", "pkg_layout.py"]
# Loose files ours under C:\ProgramData (scripts the old tasks ran, their outputs).
OLD_FILES = ["ark-gui.ps1", "ark-gui.txt", "ark-do.ps1", "ark-shot.ps1", "ark-shot.png",
             "focus-watch.py", "okww-run.bat", "ark-okww-farm.bat", "ark-okww-stop.bat",
             "ark-okww-farm.no-claim", "ark-okww-overlay.json", "ark-okww-master.txt"]


def _run(*cmd: str) -> int:
    r = subprocess.run(list(cmd), capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    print(" ".join(cmd), "->", r.returncode)
    return r.returncode


def _tasks() -> list[str]:
    out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"], capture_output=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout.decode("mbcs", "replace")
    names = {line.split('","')[0].strip('"').lstrip("\\") for line in out.splitlines() if line}
    return sorted(n for n in names if n in OLD_TASKS
                  or any(fnmatch.fnmatch(n, p) for p in OLD_TASK_PATTERNS))


# Only what starts the old relay is switched off at install; the other tasks are tools
# the new relay (and the operator's scripts) keep using.
OLD_LAUNCHERS = ["ark-relay"]


def takeover() -> None:
    for svc in OLD_SERVICES:
        _run("sc", "stop", svc)
        _run("sc", "config", svc, "start=", "disabled")
    for task in OLD_LAUNCHERS:
        _run("schtasks", "/end", "/tn", task)
        _run("schtasks", "/change", "/tn", task, "/disable")


def _env(key: str) -> str:
    try:
        for line in (OLD_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            if k.strip() == key:
                return v.split("#")[0].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _okww_overlay() -> "Path | None":
    """The file the relay puts into OK-WW (ark_relay/okww_overlay.py: ok-script runs every
    .py under <OK-WW working dir>/ok_tasks/ at startup)."""
    root = _env("ARK_OKWW_DIR")
    if not root:
        return None
    for working in (Path(root) / "data" / "apps" / "ok-ww" / "working", Path(root)):
        f = working / "ok_tasks" / "ark_overrides.py"
        if f.exists():
            return f
    return None


def remove() -> None:
    for svc in OLD_SERVICES:
        _run("sc", "stop", svc)
        _run("sc", "delete", svc)
    for task in _tasks():
        _run("schtasks", "/delete", "/tn", task, "/f")
    for name in OLD_CODE:
        p = OLD_ROOT / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink(missing_ok=True)
    for name in OLD_FILES:
        (PD / name).unlink(missing_ok=True)
    if overlay := _okww_overlay():
        overlay.unlink(missing_ok=True)
        print("removed", overlay)


if __name__ == "__main__":
    {"takeover": takeover, "remove": remove}[sys.argv[1]]()
