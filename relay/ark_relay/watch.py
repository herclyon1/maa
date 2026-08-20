"""Wake on directory changes instead of asking "anything new yet?".

The deployed Windows service already gets this through pywin32
(FindFirstChangeNotification); this module gives the plain `local` mode
the same behaviour with no dependency at all:

    Windows        FindFirstChangeNotificationW via ctypes
    macOS / BSD    kqueue on the directory descriptor (stdlib select)
    anything else  start() returns False and the caller keeps its
                   alarm-clock cap - degrade into lateness, never into
                   a watcher that pretends to work.

One deliberate asymmetry against the pywin32 path: kqueue watches the
directory entry itself, so a file created inside a nested subdirectory
does not fire it. Acceptable for what kqueue is here - the dev harness
on a Mac - and the caller's interval backstop still exists.
"""
from __future__ import annotations

import ctypes
import logging
import os
import select
import sys
import threading

log = logging.getLogger("ark.watch")


def start(path, wake: threading.Event) -> bool:
    """Set `wake` whenever `path` changes. True when a watcher is live."""
    try:
        if sys.platform == "win32":
            return _windows(str(path), wake)
        if hasattr(select, "kqueue"):
            return _kqueue(str(path), wake)
    except Exception:  # noqa: BLE001 - no watcher is a valid outcome
        log.exception("目录监听启动失败，退回定时扫描")
    return False


def _windows(path: str, wake: threading.Event) -> bool:
    k = ctypes.windll.kernel32
    # Explicit signatures: the default int return truncates a 64-bit HANDLE.
    k.FindFirstChangeNotificationW.restype = ctypes.c_void_p
    k.FindFirstChangeNotificationW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32]
    k.WaitForSingleObject.restype = ctypes.c_uint32
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.FindNextChangeNotification.restype = ctypes.c_int
    k.FindNextChangeNotification.argtypes = [ctypes.c_void_p]

    file_name, last_write = 0x01, 0x10
    handle = k.FindFirstChangeNotificationW(path, True, file_name | last_write)
    if not handle or handle == ctypes.c_void_p(-1).value:
        return False

    def run() -> None:
        infinite = 0xFFFFFFFF
        while True:
            if k.WaitForSingleObject(handle, infinite) != 0:
                break
            wake.set()
            if not k.FindNextChangeNotification(handle):
                break
        log.warning("目录监听线程退出，此后靠定时兜底")

    threading.Thread(target=run, name="dir-watch", daemon=True).start()
    return True


def _kqueue(path: str, wake: threading.Event) -> bool:
    fd = os.open(path, os.O_RDONLY)
    kq = select.kqueue()
    ev = select.kevent(
        fd, filter=select.KQ_FILTER_VNODE,
        flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
        fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND)
    kq.control([ev], 0, 0)

    def run() -> None:
        try:
            while True:
                if kq.control(None, 1, None):
                    wake.set()
        except OSError:
            log.warning("目录监听线程退出，此后靠定时兜底")

    threading.Thread(target=run, name="dir-watch", daemon=True).start()
    return True
