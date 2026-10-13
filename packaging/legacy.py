"""What the relay left on the game machine before it was an installed program.

The list itself is relay/handover/legacy-items.json (網页-检查, 10-11: every item with
its source line or commit). This file only carries it out:

    old_relay_present()  whether the old relay's service still exists; switch.py install
                         refuses while it does (two relays would both push and power off)
    remove()             at uninstall: delete every item marked `remove` or `takeover`

scripts/windows/retire_legacy.py retired the old relay on 2026-10-11 (its service deleted,
its code moved to C:\\ProgramData\\ark-relay-retired-1011), so nothing here switches it on
or off any more; remove() skips what is already gone.

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
# The old relay's service; switch.py install refuses while it exists.
OLD_SERVICE = "ark-relay"
# Written at install by packages from before the old relay's retirement (it recorded the
# launcher task's state for a way back that no longer exists); kept by retire_legacy.py,
# deleted at uninstall.
TAKEOVER_RECORD = DATA / "state" / "legacy-takeover.json"
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


def _delete_path(p: Path) -> "list[str]":
    """Delete p (a file or a whole folder); what could not be deleted, as text."""
    if p == DATA:
        failed = []
        for name in OLD_CODE:
            failed += _delete_path(DATA / name)
        return failed
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink(missing_ok=True)
    else:
        return []
    if p.exists():
        return [f"{p}: still there"]
    print("deleted", p)
    return []


def _remove_one(it: dict, tasks: "list[str] | None") -> "tuple[list[str], list[str] | None]":
    failed: "list[str]" = []
    kind = it.get("kind")
    if kind == "service":
        if not service_exists(it["name"]):
            print("skipped (already gone):", it["name"])
            return failed, tasks
        _run("sc", "stop", it["name"])
        if _run("sc", "delete", it["name"]) != 0:
            failed.append(f"service {it['name']}: sc delete failed")
    elif kind in ("task", "task-prefix"):
        tasks = tasks if tasks is not None else _task_names()
        for t in tasks:
            if t == it["name"] or (kind == "task-prefix" and t.startswith(it["name"])):
                if _run("schtasks", "/delete", "/tn", t, "/f") != 0:
                    failed.append(f"task {t}: schtasks /delete failed")
    elif kind in ("dir", "file", "glob"):
        path = os.path.expandvars(it["path"])
        if "<" in path:
            print("skipped (path known only on the machine):", path)
            return failed, tasks
        for p in (glob.glob(path) if kind == "glob" else [path]):
            failed += _delete_path(Path(p))
    return failed, tasks


def remove() -> "list[str]":
    """Delete every item marked `remove` or `takeover`, each on its own: one that fails
    (or raises) does not stop the rest. Returns what was not deleted, as text."""
    try:
        todo = [it for it in items() if it.get("action") in ("remove", "takeover")]
    except (OSError, ValueError, KeyError) as exc:
        return [f"{ITEMS.name} not read: {exc}"]
    failed: "list[str]" = []
    tasks = None
    for it in todo:
        try:
            more, tasks = _remove_one(it, tasks)
            failed += more
        except Exception as exc:  # noqa: BLE001 - one leftover must not stop the rest
            failed.append(f"{it.get('name') or it.get('path')}: {type(exc).__name__}: {exc}")
    try:
        TAKEOVER_RECORD.unlink(missing_ok=True)
    except OSError as exc:
        failed.append(f"{TAKEOVER_RECORD}: {exc}")
    for line in failed:
        print("not removed:", line)
    return failed


if __name__ == "__main__":
    import sys
    {"remove": remove}[sys.argv[1]]()
