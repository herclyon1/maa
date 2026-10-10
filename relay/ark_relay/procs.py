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

# 2026-10-10 16:14:07: the first query of a freshly restarted relay failed with
# WBEM_E_CALL_CANCELLED (0x80041032, WMI-Activity log, pid 1436) while WMI was
# still tearing down the process-start subscription the previous relay had just
# cancelled (16:13:49, service._AsyncSubscription). The boot self-check went red
# and the keeper never got its handle on AUTO-MAS. A query that fails is tried
# again after a pause; only when every try fails is the listing unknown.
ATTEMPTS = 3
PAUSE_SECONDS = 3.0
_sleep = time.sleep
_warned = False      # one WARNING per outage (every WARNING reaches the group)


def _query() -> "list[tuple[int, str]]":
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


def _why(exc: BaseException) -> str:
    """The COM error code when there is one (0x80041032 = the call was cancelled), else the class name."""
    hr = getattr(exc, "hresult", None)
    if hr is None and getattr(exc, "args", None) and isinstance(exc.args[0], int):
        hr = exc.args[0]
    return f"错误码 0x{hr & 0xFFFFFFFF:08X}" if isinstance(hr, int) else type(exc).__name__


def python_processes() -> "list[tuple[int, str]] | None":
    """(pid, command line) of every python.exe, or None when every try of the query failed."""
    global _warned
    last = None
    for i in range(ATTEMPTS):
        try:
            rows = _query()
        except Exception as exc:  # noqa: BLE001 - the callers decide what "unknown" means
            last = exc
            log.info("进程表这次没读到（第 %d 次，%s）", i + 1, _why(exc), exc_info=True)
            if i + 1 < ATTEMPTS:
                _sleep(PAUSE_SECONDS)
            continue
        if last is not None:
            log.info("进程表第 %d 次读到了（之前：%s）", i + 1, _why(last))
        _warned = False
        return rows
    if not _warned:
        _warned = True
        log.warning("进程表读不到：试了 %d 次、每次隔 %.0f 秒都失败（%s）", ATTEMPTS, PAUSE_SECONDS, _why(last))
    return None
