"""What the relay left on the game machine before it was an installed program.

The list itself is relay/handover/legacy-items.json (網页-检查, 10-11: every item with
its source line or commit). This file only carries it out:

    takeover()  at install: stop the old relay so two never run at once (both would
                push and power off). Its service and launcher are disabled, not
                deleted: until the uninstall, `switch.py revert` switches it back
                on (undo_takeover) - as each was before the first takeover, which
                is recorded in state\\legacy-takeover.json (the launcher task was
                already disabled on the machine, 2026-10-11 03:41; enabling it
                would start a second old relay at logon next to the service).
    remove()    at uninstall: delete every item marked `remove` or `takeover` - the
                uninstall removes the old relay too; the way back to it is
                `switch.py revert`, not the uninstaller.

Once scripts/windows/retire_legacy.py has retired the old relay (its service deleted, its
code moved to RETIRED), there is nothing to switch back to: old_relay_present() is
False, takeover() and undo_takeover() do nothing, remove() skips what is already gone
and switch.py revert says so instead of stopping the new relay first.

Data the user may want kept is never deleted here: in C:\\ProgramData\\ark-relay only the
old relay's code files go; .env, state\\ and the logs stay, and the uninstaller asks
about that folder separately.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path

ITEMS = Path(__file__).resolve().parent / "handover" / "legacy-items.json"
DATA = Path(r"C:\ProgramData\ark-relay")
# The old relay's code files inside the data folder (deployed there by
# scripts/mac/deploy-relay.sh; manifest.json lists them). Everything else there is data.
OLD_CODE = ["ark_relay", "run.py", "service.py", "boot_stages.py", "app_main.py",
            "pkg_layout.py", "manifest.json", "RELEASE-NOTES.md", "requirements.txt",
            "make-manifest.py", "USER-SWITCHES.txt", "README.md", "ark-relay.ps1"]
# What starts the old relay: switched off at install.
OLD_SERVICE = "ark-relay"
OLD_LAUNCHER_TASK = "ark-relay"
# The launcher task's state before the first takeover (see takeover / undo_takeover).
TAKEOVER_RECORD = DATA / "state" / "legacy-takeover.json"
# Where scripts/windows/retire_legacy.py moved the old relay's files (kept 30 days).
RETIRED = Path(r"C:\ProgramData\ark-relay-retired-1011")
ERROR_SERVICE_DOES_NOT_EXIST = 1060


def _run(*cmd: str) -> int:
    r = subprocess.run(list(cmd), capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    print(" ".join(cmd), "->", r.returncode)
    return r.returncode


def service_exists(name: str) -> bool:
    """`sc query` answers anything but 1060 (no such service): an access error or a busy
    SCM counts as present, so a doubt keeps the old behaviour."""
    r = subprocess.run(["sc", "query", name], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return r.returncode != ERROR_SERVICE_DOES_NOT_EXIST


def old_relay_present() -> bool:
    """False once the old relay is retired (retire_legacy.py) or uninstalled."""
    return service_exists(OLD_SERVICE)


def items() -> list[dict]:
    return json.loads(ITEMS.read_text(encoding="utf-8"))["items"]


def _task_names() -> list[str]:
    out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"], capture_output=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout.decode("mbcs", "replace")
    return sorted({line.split('","')[0].strip('"').lstrip("\\") for line in out.splitlines() if line})


def _launcher_enabled() -> "bool | None":
    """Whether the old launcher task is enabled; None when there is none. Through the
    Task Scheduler's COM interface: schtasks prints its status in the system's language."""
    import pywintypes  # noqa: PLC0415
    import win32com.client  # noqa: PLC0415
    try:
        sched = win32com.client.Dispatch("Schedule.Service")
        sched.Connect()
        return bool(sched.GetFolder("\\").GetTask(OLD_LAUNCHER_TASK).Enabled)
    except pywintypes.com_error:
        return None


def takeover() -> None:
    if not old_relay_present():
        print(f"old relay retired (no service {OLD_SERVICE}): nothing to stop")
        return
    # What to put back on `revert`. Only before the first takeover: on an upgrade over
    # an earlier install both are already switched off by us.
    if not TAKEOVER_RECORD.exists():
        TAKEOVER_RECORD.parent.mkdir(parents=True, exist_ok=True)
        TAKEOVER_RECORD.write_text(json.dumps({"launcher_task_enabled": _launcher_enabled()}),
                                   encoding="utf-8")
    _run("sc", "stop", OLD_SERVICE)
    _run("sc", "config", OLD_SERVICE, "start=", "disabled")
    _run("schtasks", "/end", "/tn", OLD_LAUNCHER_TASK)
    _run("schtasks", "/change", "/tn", OLD_LAUNCHER_TASK, "/disable")


def undo_takeover() -> int:
    """Back to the old relay (switch.py revert, or a switch-over that failed): its
    service on automatic start and started, the launcher task as it was before the
    takeover (left disabled when that is unknown). 0 = the service is running (1056:
    it already was; 1060: there is no old relay any more)."""
    if not old_relay_present():
        print(f"old relay retired (no service {OLD_SERVICE}, files in {RETIRED}): not switched on")
        return ERROR_SERVICE_DOES_NOT_EXIST
    try:
        was = json.loads(TAKEOVER_RECORD.read_text(encoding="utf-8")).get("launcher_task_enabled")
    except (OSError, ValueError, AttributeError):
        was = None
    _run("sc", "config", OLD_SERVICE, "start=", "auto")
    if was:
        _run("schtasks", "/change", "/tn", OLD_LAUNCHER_TASK, "/enable")
    rc = _run("sc", "start", OLD_SERVICE)
    if rc in (0, 1056):
        TAKEOVER_RECORD.unlink(missing_ok=True)   # the next install records afresh
        return 0
    return rc


def _delete_path(p: Path) -> None:
    if p == DATA:
        for name in OLD_CODE:
            _delete_path(DATA / name)
        return
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink(missing_ok=True)
    else:
        return
    print("deleted", p)


def remove() -> None:
    tasks = None
    for it in items():
        if it.get("action") not in ("remove", "takeover"):
            continue
        kind = it.get("kind")
        if kind == "service":
            if not service_exists(it["name"]):
                print("skipped (already gone):", it["name"])
                continue
            _run("sc", "stop", it["name"])
            _run("sc", "delete", it["name"])
        elif kind in ("task", "task-prefix"):
            tasks = tasks if tasks is not None else _task_names()
            for t in tasks:
                if t == it["name"] or (kind == "task-prefix" and t.startswith(it["name"])):
                    _run("schtasks", "/delete", "/tn", t, "/f")
        elif kind in ("dir", "file", "glob"):
            path = os.path.expandvars(it["path"])
            if "<" in path:
                print("skipped (path known only on the machine):", path)
                continue
            for p in (glob.glob(path) if kind == "glob" else [path]):
                _delete_path(Path(p))
    TAKEOVER_RECORD.unlink(missing_ok=True)   # nothing left to switch back to


if __name__ == "__main__":
    import sys
    {"takeover": takeover, "undo-takeover": undo_takeover, "remove": remove}[sys.argv[1]]()
