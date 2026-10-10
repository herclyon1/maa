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

log = logging.getLogger("ark.procs")


def python_processes() -> "list[tuple[int, str]] | None":
    """(pid, command line) of every python.exe, or None when the query itself failed."""
    try:
        import pythoncom  # noqa: PLC0415
        import win32com.client  # noqa: PLC0415
        pythoncom.CoInitialize()
        try:
            wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
            rows = wmi.ExecQuery(
                "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='python.exe'")
            return [(int(r.ProcessId), str(r.CommandLine or "")) for r in rows]
        finally:
            pythoncom.CoUninitialize()
    except Exception:  # the callers decide what "unknown" means
        log.debug("进程表读不到", exc_info=True)
        return None
