"""The AUTO-MAS processes as tasklist and OpenProcess see them: the Electron shell, the Python backend and its handle, an installer running.

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import subprocess

import win32api
import win32con

import boot_stages  # relay/boot_stages.py; service.py / app_main.py put relay/ on sys.path


# Processes whose presence vetoes any revival outright.
INSTALLER_HINTS = (b"auto-mas-setup", b"unins")


# OpenProcess right that lets GetExitCodeProcess read the backend's exit code
# (PROCESS_QUERY_LIMITED_INFORMATION; not every win32con build names it).
_QUERY_LIMITED = 0x1000


def _automas_shell_running() -> bool:
    """True if the Electron shell is up, whatever the backend is doing."""
    return boot_stages.shell_running()


def _installer_running() -> "bool | None":
    """True while a setup or uninstaller is on screen (never touch it); None when
    the process list cannot be read.

    None used to be True, and _revive then logged 「安装程序正在运行」 for a list
    it had not read - the "cannot tell" read as a definite answer that procs.py
    records (three weeks blind). The caller still keeps its hands off on None,
    but says why."""
    out = _tasklist()
    if out is None:
        return None
    return any(h in out for h in INSTALLER_HINTS)


def is_backend(cmd: str) -> bool:
    """True if a python.exe command line is AUTO-MAS's backend: main.py run from under the
    install root's \\automas\\ directory.

    On the machine (2026-10-10, relay/tests/test_procs_wmi.py) it reads
    `D:\\ark\\automas\\runtime\\environment\\venv\\Scripts\\python.exe main.py`. "main.py"
    alone also matched OK-WW (`D:\\ark\\okww\\data\\apps\\ok-ww\\working\\main.py`, which
    may run as python.exe - preupdate_okww.py): a dead backend then read as alive,
    and an OK-WW start was adopted as the backend (audit s15 #3)."""
    low = (cmd or "").lower().replace("/", "\\")
    return "main.py" in low and "\\automas\\" in low


def _python_processes() -> "list[tuple[int, str]] | None":
    """(pid, command line) of every python.exe, or None when the query itself failed. See procs.py."""
    from ark_relay.core import procs  # noqa: PLC0415
    return procs.python_processes()


def _automas_running() -> bool:
    """True if AUTO-MAS's Python backend is up.

    Checks the backend rather than the Electron shell: the shell can sit there
    perfectly happily with a dead backend, which is precisely the state the
    machine was found in - the UI looked fine and nothing was scheduling runs.

    When the process list cannot be read at all, the API answers instead: an
    answering API is a live backend by definition, and a silent one is not
    assumed alive any more (that assumption is what blinded the keeper, see
    _python_processes).
    """
    procs = _python_processes()
    if procs is None:
        from ark_relay.features.phone import commands  # noqa: PLC0415
        return commands.mas_up()
    return any(is_backend(cmd) for _, cmd in procs)


def _automas_handle():
    """A waitable handle on the AUTO-MAS backend, or None if it is not up.

    Waiting on the process itself replaces asking every two minutes whether it
    is still there. Windows signals the handle the instant the process exits,
    so a backend that dies at 09:05 is revived at 09:05 rather than at 09:07 -
    and in between, the relay is not doing anything at all.
    """
    for pid, cmd in (_python_processes() or []):
        if not is_backend(cmd):
            continue
        # With the query right as well, its exit code can be read when it goes
        # (_exit_code); without it only the exit itself is visible.
        for access in (lambda: win32con.SYNCHRONIZE | _QUERY_LIMITED, lambda: win32con.SYNCHRONIZE):
            try:
                return win32api.OpenProcess(access(), False, pid)
            except Exception:  # noqa: BLE001
                continue
        # This pid could not be opened (gone since the query, or refused): the
        # next match may be the live backend, so it is tried too.
    return None


def _exit_code(handle) -> "int | None":
    """The exited backend's exit code, None where it cannot be read."""
    try:
        import win32process  # noqa: PLC0415
        return int(win32process.GetExitCodeProcess(handle))
    except Exception:  # noqa: BLE001 - evidence only; never stops the revival
        return None


def _tasklist() -> "bytes | None":
    """`tasklist /NH`, lowercased; None when it could not be run."""
    try:
        return subprocess.run(["tasklist", "/NH"], capture_output=True,
                              timeout=25).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return None
