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
import time

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

    def _open():
        h = k.FindFirstChangeNotificationW(path, True, file_name | last_write)
        return None if not h or h == ctypes.c_void_p(-1).value else h

    handle = _open()
    if handle is None:
        return False

    def run() -> None:
        # 掉了要重建。原来这里退出就完了，剩下整个进程生命周期都只靠定时兜底
        # ——和 service.py 的 WMI 订阅、目录监听是同一族 bug，
        # 2026-08-30 全量审查时一起修的。
        nonlocal handle
        infinite = 0xFFFFFFFF
        delay = 5.0
        while True:
            while handle is not None:
                if k.WaitForSingleObject(handle, infinite) != 0:
                    break
                wake.set()
                if not k.FindNextChangeNotification(handle):
                    break
            handle = None
            wake.set()          # 让调用方立刻走一次兜底扫描
            log.warning("目录监听掉了，%.0f 秒后重建；期间靠定时兜底", delay)
            time.sleep(delay)
            handle = _open()
            if handle is not None:
                log.info("目录监听已重建")
                delay = 5.0
            else:
                delay = min(delay * 2, 60.0)

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
        # 同上：掉了要重建，不是退出就算了。
        nonlocal fd, kq
        delay = 5.0
        while True:
            try:
                while True:
                    if kq.control(None, 1, None):
                        wake.set()
            except OSError:
                pass
            wake.set()
            log.warning("目录监听掉了，%.0f 秒后重建；期间靠定时兜底", delay)
            for closer in (kq.close, lambda: os.close(fd)):
                try:
                    closer()
                except OSError:
                    pass
            time.sleep(delay)
            try:
                fd = os.open(path, os.O_RDONLY)
                kq = select.kqueue()
                kq.control([select.kevent(
                    fd, filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                    fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND)], 0, 0)
                log.info("目录监听已重建")
                delay = 5.0
            except OSError:
                delay = min(delay * 2, 60.0)

    threading.Thread(target=run, name="dir-watch", daemon=True).start()
    return True
