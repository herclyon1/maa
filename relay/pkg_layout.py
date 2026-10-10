"""Where the packaged relay keeps its code and its data, and how it moves between versions.

Packaged install (packaging/ark-relay.iss):

    {app}\\runtime\\python\\       embedded Python 3.14 + Pillow + pywin32; only the installer changes it
    {app}\\versions\\<n>\\         one complete copy of relay/ per code version (n = manifest version)
    {app}\\current.txt            the name of the version folder in use
    {app}\\launch.py              reads current.txt and starts that folder's app_main.py
    {app}\\watchdog\\              the watchdog service; only the installer changes it
    C:\\ProgramData\\ark-relay\\    data: .env, state\\, relay.log - shared by every version

Each version folder's `state` is a directory junction to the data folder's `state`, so
the code that keeps its bookkeeping under `<code root>/state` (selfupdate's applied
version and announcement, boot_stages' release notes) keeps reading and writing the
one real state folder, exactly as when code and data shared C:\\ProgramData\\ark-relay.

An update never touches the folder in use: it copies it, lets selfupdate.check bring
the copy up to the deployed manifest (only changed files are downloaded, as before),
and switches current.txt to the copy only when check reports changed files. Going
back is switching current.txt to the previous folder; the last KEEP_VERSIONS stay.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("ark.pkg")

DATA_DEFAULT = Path(r"C:\ProgramData\ark-relay")
KEEP_VERSIONS = 3
MAIN_TASK = r"\ArkRelay\main"
STAGING = ".staging"


def app_root(here: Path) -> "Path | None":
    """The install folder when `here` is a version folder of a packaged install, else None."""
    if here.parent.name == "versions" and (here.parent.parent / "current.txt").is_file():
        return here.parent.parent
    return None


def data_root() -> Path:
    """The data folder (.env, state, relay.log): ARK_HOME, else C:\\ProgramData\\ark-relay."""
    return Path(os.environ.get("ARK_HOME") or DATA_DEFAULT)


def current(app: Path) -> str:
    return (app / "current.txt").read_text(encoding="ascii").strip()


def _set_current(app: Path, name: str) -> None:
    tmp = app / "current.txt.tmp"
    tmp.write_text(name + "\n", encoding="ascii")
    os.replace(tmp, app / "current.txt")


def version_key(name: str) -> tuple[int, int]:
    """'1234' -> (1234, 0); '1234-2' (a re-deploy of 1234) -> (1234, 2); else (0, 0)."""
    head, _, tail = name.partition("-")
    try:
        return int(head), int(tail or 0)
    except ValueError:
        return 0, 0


def versions(app: Path) -> list[str]:
    """Version folders, oldest first (names are manifest versions, compared as numbers)."""
    names = [p.name for p in (app / "versions").iterdir()
             if p.is_dir() and not p.name.startswith(".")]
    return sorted(names, key=version_key)


def record_running_version(here: Path) -> None:
    """Make selfupdate's recorded version the version of the folder that is running.

    The record lives in the shared state folder, the code in per-version folders, and
    the two can part: a switch that failed after check recorded the new version, a
    rollback, or an install over the old relay whose record is newer than the installed
    code. selfupdate.check trusts the record, so each start sets it from the folder.

    After a rollback the record is the version rolled away from (PIN), not the running
    one: otherwise check would see the deployed version as new and update straight back
    into it. The pin holds until a higher version is deployed (update clears it)."""
    from ark_relay import selfupdate  # noqa: PLC0415
    running = version_key(here.name)[0]
    want = max(running, _pinned(here))
    if want and selfupdate._applied_version(here) != want:
        log.info("记录的代码版本改成 %s（正在用的文件夹 %s）", want, here.name)
        selfupdate._remember_version(here, want)


# A file of its own, not a state.json field: StateStore only writes registered fields
# (docs/STATE-MODEL.md), and this one belongs to the packaged layout alone.
PIN_FILE = "rolled-back-from.txt"


def _pinned(code: Path) -> int:
    try:
        return int((code / "state" / PIN_FILE).read_text(encoding="ascii").strip() or 0)
    except (OSError, ValueError):
        return 0


def _pin(code: Path, version: int) -> None:
    f = code / "state" / PIN_FILE
    if version:
        f.write_text(f"{version}\n", encoding="ascii")
    else:
        f.unlink(missing_ok=True)


def _drop(folder: Path) -> None:
    """Delete a version folder without following its state junction into the data folder."""
    link = folder / "state"
    if _is_link(link):
        os.rmdir(link)          # removes the junction only
    shutil.rmtree(folder, ignore_errors=True)


def update(here: Path, check) -> list[str]:
    """Bring a copy of the folder in use up to the deployed manifest and switch to it.

    `check` is selfupdate.check. Returns its lines; [] means nothing changed (or the
    round failed and was recorded by check) and the folder in use is untouched.
    """
    app = app_root(here)
    if app is None:
        raise RuntimeError(f"{here} is not a version folder of a packaged install")
    staging = app / "versions" / STAGING
    if staging.exists():
        _drop(staging)
    def skip(folder: str, names: list[str]) -> set[str]:
        top = Path(folder) == here
        return {n for n in names if n == "__pycache__" or (top and n == "state")}

    shutil.copytree(here, staging, ignore=skip)
    link_state(staging, data_root())
    try:
        changed = check(staging)
    except Exception:
        _drop(staging)
        raise
    if not changed:
        _drop(staging)
        return []
    from ark_relay import selfupdate  # noqa: PLC0415
    try:
        version = str(selfupdate._applied_version(staging) or 0)
        name, n = version, 0
        while (app / "versions" / name).exists():
            # The same version number came again (a re-deploy): keep another copy.
            n += 1
            name = f"{version}-{n}"
        os.replace(staging, app / "versions" / name)
        _set_current(app, name)
        if _pinned(here):
            _pin(here, 0)            # a newer version than the one rolled away from
    except Exception:
        # Not switched: the record must keep naming the folder in use.
        record_running_version(here)
        if staging.exists():
            _drop(staging)
        raise
    log.info("新版本放进 %s，下次启动用它（原来是 %s）", name, here.name)
    _prune(app, keep={name, here.name})
    return changed


def _prune(app: Path, keep: set[str]) -> None:
    names = versions(app)
    for old in names[:-KEEP_VERSIONS]:
        if old not in keep:
            _drop(app / "versions" / old)


def rollback(app: Path) -> "str | None":
    """Switch current.txt to the version before the one in use. The new name, or None."""
    names = versions(app)
    cur = current(app)
    if cur not in names or names.index(cur) == 0:
        return None
    prev = names[names.index(cur) - 1]
    # Keep the next start from updating straight back into `cur` (record_running_version).
    _pin(app / "versions" / cur, max(version_key(cur)[0], _pinned(app / "versions" / cur)))
    _set_current(app, prev)
    log.warning("退回上一版：%s → %s", cur, prev)
    return prev


def restart_soon() -> None:
    """Start the main task again a few seconds after this process has exited.

    The task is still running while this process lives, and `schtasks /run` on a
    running task does nothing; the detached cmd outlives us and runs it once we are
    gone. The watchdog would restart the relay anyway, within its check interval."""
    subprocess.Popen(
        ["cmd", "/c", f'timeout /t 3 /nobreak >nul & schtasks /run /tn "{MAIN_TASK}"'],
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS))
