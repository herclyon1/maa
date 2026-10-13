"""Where the packaged relay keeps its code and its data, and how it moves between versions.

Packaged install (packaging/ark-relay.iss):

    {app}\\runtime\\python\\       embedded Python 3.14 + Pillow + pywin32; only the installer changes it
                                 (a deploy refuses when it is not what the repo builds)
    {app}\\versions\\<n>\\         one complete copy of relay/ per code version (n = manifest version)
    {app}\\current.txt            the name of the version folder in use
    {app}\\launch.py              reads current.txt and starts that folder's app_main.py
    {app}\\switch.py, legacy.py, handover\\
                                 the installer's steps; launch.py and these: the installer,
                                 and a deploy when they changed (scripts/mac/lib/pkg_appfiles.py)
    {app}\\watchdog\\              the watchdog service; the installer changes it, and a deploy
                                 does when packaging/watchdog/ark_watchdog.py changed
                                 (scripts/windows/pkg_deploy.py watchdog); never an update
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

import json
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


def _write_whole(path: Path, text: str) -> None:
    """Temp file + fsync + os.replace: a power cut leaves the old file or the new one,
    never a truncated one (a truncated pin reads as 0 and the rollback is forgotten).
    Local, not config.atomic_write_text: scripts/windows/pkg_deploy.py loads this module
    without the ark_relay package."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="ascii") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _set_current(app: Path, name: str) -> None:
    _write_whole(app / "current.txt", name + "\n")


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
    into it. The pin holds until a higher version is deployed (update clears it).

    The "code was updated" note goes the same way when it names a version newer than the
    folder in use: check wrote it into the shared state for a copy that never became
    current (the switch raised, or power went before it), and announcing it would say
    「中继已更新」 while the old code runs (audit s24 F1). A note for the folder in use is
    the first boot after a real switch and stays."""
    from ark_relay.features.selfupdate import selfupdate  # noqa: PLC0415
    running = version_key(here.name)[0]
    want = max(running, _pinned(here))
    if want and selfupdate._applied_version(here) != want:
        log.info("记录的代码版本改成 %s（正在用的文件夹 %s）", want, here.name)
        selfupdate._remember_version(here, want)
    note = _read_note(selfupdate._announce_path(here))
    if running and note is not None and int(note.get("version") or 0) > running:
        log.info("丢掉 v%s 的更新通知：正在用的文件夹是 %s，那一版没换上",
                 note.get("version"), here.name)
        selfupdate.take_announcement(here)


def _read_note(path: Path) -> "dict | None":
    """A JSON note's object without consuming it; None when missing or unreadable."""
    try:
        note = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return note if isinstance(note, dict) else None


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
        _write_whole(f, f"{version}\n")
    else:
        f.unlink(missing_ok=True)


def _is_link(p: Path) -> bool:
    return p.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(p)


def _dotenv_value(env_file: Path, key: str) -> str:
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            if k.strip() == key and v.strip():
                return v.split("#")[0].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def state_dir(data: Path) -> Path:
    """The relay's state folder as the relay resolves it: ARK_STATE_DIR from the
    environment (app_main has loaded <data>/.env into it), else from <data>/.env, else
    <data>/state. A relative one is under <data>, where app_main runs (os.chdir(DATA)).

    Every version folder's `state` junction points here, so selfupdate's versions.code
    and the boot's read of cfg.state_dir are one state.json whatever .env says."""
    raw = os.environ.get("ARK_STATE_DIR") or _dotenv_value(data / ".env", "ARK_STATE_DIR")
    p = Path(raw) if raw else data / "state"
    return p if p.is_absolute() else data / p


def _same_dir(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def link_state(code: Path, target: Path) -> None:
    """Make `code/state` a directory junction to `target` (state_dir(), created when
    missing). A junction to another folder - .env's ARK_STATE_DIR changed since it was
    made - is made again; only the junction goes, never the data behind it."""
    link = code / "state"
    target.mkdir(parents=True, exist_ok=True)
    if _is_link(link):
        if _same_dir(link, target):
            return
        log.info("版本文件夹的 state 连接改指 %s（ARK_STATE_DIR 变了）", target)
        if os.name == "nt":
            os.rmdir(link)          # a junction: removes the link only
        else:
            link.unlink()
    if link.exists():
        # A real folder here holds selfupdate bookkeeping written before the link
        # existed; move what the data folder does not have yet, then replace it.
        for p in link.iterdir():
            if not (target / p.name).exists():
                shutil.move(str(p), str(target / p.name))
        shutil.rmtree(link)
    if os.name != "nt":
        os.symlink(target, link, target_is_directory=True)   # the tests, off Windows
        return
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                   check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _drop(folder: Path) -> None:
    """Delete a version folder without following its state junction into the data folder."""
    link = folder / "state"
    if _is_link(link):
        if os.name == "nt":
            os.rmdir(link)      # removes the junction only
        else:
            link.unlink()       # the tests' symlink, off Windows
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
    link_state(staging, state_dir(data_root()))
    try:
        changed = check(staging)
    except Exception:
        _drop(staging)
        raise
    if not changed:
        _drop(staging)
        # check may have recorded the manifest's version even though nothing needed
        # changing; no switch happened, so the record goes back to the folder in use.
        record_running_version(here)
        return []
    from ark_relay.features.selfupdate import selfupdate  # noqa: PLC0415
    version = "0"
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
        # Not switched: the record must keep naming the folder in use, and check's
        # 「已更新」 note goes with it (record_running_version). check cleared
        # update-failed.json for a round that landed in the copy, so the owner hears
        # 「更新没生效」 only if it is written again here (audit s24 F1).
        record_running_version(here)
        selfupdate._record_failure(
            here, "新版本的文件已经下载好，换到新版本文件夹那一步出错了（原因见日志）",
            int(version), version_key(here.name)[0], changed)
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


def restart_soon(app: Path, popen=subprocess.Popen) -> None:
    """Start the relay again once this process has exited: `launch.py relaunch`, detached,
    waits for the relay's mutex to go and then runs the task (a `schtasks /run` while
    this process lives is ignored).

    Until 2026-10-11 this was `cmd /c timeout /t 3 & schtasks /run` in a detached cmd.
    It was not timeout returning early: a detached `timeout /t 3` took 2.7 s on the
    cloud runner (package-windows run 38095462157). Likely the fixed 3 s was shorter
    than the relay takes to exit after an update (its last push, the phone channel;
    SvcStop's hard exit is at 15 s), so the task run came while it still lived and was
    ignored (unmeasured); the relay came back only with the watchdog's next check, up
    to 30 s later (review rounds 2 #13 and 7 #22). Waiting for the mutex works however
    long the exit takes."""
    cmd = [str(app / "runtime" / "python" / "pythonw.exe"), str(app / "launch.py"), "relaunch"]
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    # Out of the task's job object where it allows that, so the end of the task's
    # process cannot take the helper with it.
    try:
        popen(cmd, creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
    except OSError:
        popen(cmd, creationflags=flags)
