"""What the relay left on the game machine before it was an installed program.

The list itself is relay/handover/legacy-items.json (網页-检查, 10-11: every item with
its source line or commit). This file only carries it out:

    takeover()  at install: stop the old relay so two never run at once (both would
                push and power off). Its service and launcher are disabled, not
                deleted: until the uninstall, `switch.py revert` switches it back
                on (undo_takeover).
    remove()    at uninstall: delete every item marked `remove` or `takeover` - the
                uninstall removes the old relay too; the way back to it is
                `switch.py revert`, not the uninstaller.

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


def _run(*cmd: str) -> int:
    r = subprocess.run(list(cmd), capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    print(" ".join(cmd), "->", r.returncode)
    return r.returncode


def items() -> list[dict]:
    return json.loads(ITEMS.read_text(encoding="utf-8"))["items"]


def _task_names() -> list[str]:
    out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"], capture_output=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout.decode("mbcs", "replace")
    return sorted({line.split('","')[0].strip('"').lstrip("\\") for line in out.splitlines() if line})


def takeover() -> None:
    _run("sc", "stop", OLD_SERVICE)
    _run("sc", "config", OLD_SERVICE, "start=", "disabled")
    _run("schtasks", "/end", "/tn", OLD_LAUNCHER_TASK)
    _run("schtasks", "/change", "/tn", OLD_LAUNCHER_TASK, "/disable")


def undo_takeover() -> int:
    """Back to the old relay (switch.py revert, or a switch-over that failed).
    0 = its service is running (1056: it already was)."""
    _run("sc", "config", OLD_SERVICE, "start=", "auto")
    _run("schtasks", "/change", "/tn", OLD_LAUNCHER_TASK, "/enable")
    rc = _run("sc", "start", OLD_SERVICE)
    return 0 if rc in (0, 1056) else rc


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


if __name__ == "__main__":
    import sys
    {"takeover": takeover, "undo-takeover": undo_takeover, "remove": remove}[sys.argv[1]]()
