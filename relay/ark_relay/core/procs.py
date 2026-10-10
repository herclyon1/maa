"""Process listing through WMI's COM interface - the one door that still exists.

`wmic.exe` is gone from Windows 11 25H2 (this machine, build 26200). From
2026-08-28 to 2026-09-17 the keeper in service.py kept calling it, took the
FileNotFoundError as "cannot tell" and read that as "alive": three weeks blind,
no revival, no alarm, and on the 17th the evening queue was lost. The WMI
service itself is fine - the process-start subscription uses it - so the same
door is used here, and the boot self-check verifies it opens.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("ark.procs")

# Properties are read through SWbemObject.Properties_, not as attributes
# (`item.ProcessId`): once the relay's DispatchWithEvents
# (service._AsyncSubscription) has generated pywin32's early-bound wrapper of the
# WMI scripting library (C:\Windows\Temp\gen_py\...), an early-bound SWbemObject
# has only the interface's own members and `item.ProcessId` raises
# AttributeError. Properties_ works bound either way.
#
# Each try lets go of every COM object - and of the exception, whose traceback
# holds them - before CoUninitialize. Released after it, they raise inside
# Release ("Win32 exception occurred releasing IUnknown"), and keeping the
# exception across tries crashed pythonservice.exe in pythoncom314.dll. A failed
# try is repeated after a pause.
ATTEMPTS = 3
PAUSE_SECONDS = 3.0
_sleep = time.sleep
_state = {"warned": False, "why": ""}   # one WARNING per outage (every WARNING reaches the group)
_QUERY = "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='python.exe'"


def _code(exc: BaseException) -> str:
    """The COM error code when there is one (0x80041032 = the call was cancelled), else the class name."""
    hr = getattr(exc, "hresult", None)
    if hr is None and getattr(exc, "args", None) and isinstance(exc.args[0], int):
        hr = exc.args[0]
    return f"错误码 0x{hr & 0xFFFFFFFF:08X}" if isinstance(hr, int) else type(exc).__name__


def _prop(item, name: str):
    return item.Properties_(name).Value


def _query_once(query: str = _QUERY) -> "tuple[list[tuple[int, str]] | None, str]":
    """One try in its own COM initialisation: (rows, "") or (None, why). Never raises,
    and no COM object or exception outlives the CoUninitialize."""
    try:
        import pythoncom  # noqa: PLC0415
        import win32com.client  # noqa: PLC0415
    except ImportError:
        return None, "没有 pywin32"
    pythoncom.CoInitialize()
    try:
        wmi = res = item = None
        rows, why = [], ""
        try:
            wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
            res = wmi.ExecQuery(query)
            for item in res:
                rows.append((int(_prop(item, "ProcessId")), str(_prop(item, "CommandLine") or "")))
        except Exception as exc:  # noqa: BLE001 - becomes a plain string; the object must not live on
            why = _code(exc)
            rows = None
        item = res = wmi = None
        return rows, why
    finally:
        pythoncom.CoUninitialize()


def last_failure() -> str:
    """Why the last call returned None (plain words), '' after a success."""
    return _state["why"]


def python_processes(*, warn: bool = True) -> "list[tuple[int, str]] | None":
    """(pid, command line) of every python.exe, or None when every try of the query failed.

    `warn=False` is for a caller that reports the failure itself (the boot self-check
    pushes one alarm naming it); that report counts as this outage's one, so a later
    caller does not push the same cause again."""
    whys = []
    for i in range(ATTEMPTS):
        rows, why = _query_once()
        if rows is not None:
            if whys:
                log.info("程序列表第 %d 次读到了（之前：%s）", i + 1, "、".join(whys))
            _state["warned"] = False
            _state["why"] = ""
            return rows
        whys.append(why)
        if why == "没有 pywin32":
            break
        log.info("程序列表这次没读到（第 %d 次，%s）", i + 1, why)
        if i + 1 < ATTEMPTS:
            _sleep(PAUSE_SECONDS)
    _state["why"] = f"试了 {len(whys)} 次都失败（{'、'.join(whys)}）"
    if not warn:
        _state["warned"] = True
    elif not _state["warned"]:
        _state["warned"] = True
        log.warning("程序列表读不到：试了 %d 次都失败（%s）", len(whys), "、".join(whys))
    return None
