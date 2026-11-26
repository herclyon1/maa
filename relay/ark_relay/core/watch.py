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
import threading
import time

from ark_relay.core import config

_monotonic = time.monotonic

log = logging.getLogger("ark.watch")


def start(path, wake: threading.Event) -> bool:
    """Set `wake` whenever `path` changes. True when a watcher is live."""
    try:
        if config.IS_WINDOWS:
            return _windows(str(path), wake)
        if hasattr(select, "kqueue"):
            return _kqueue(str(path), wake)
    except Exception:
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
    k.FindCloseChangeNotification.restype = ctypes.c_int
    k.FindCloseChangeNotification.argtypes = [ctypes.c_void_p]

    file_name, last_write = 0x01, 0x10

    def _open():
        h = k.FindFirstChangeNotificationW(path, True, file_name | last_write)
        return None if not h or h == ctypes.c_void_p(-1).value else h

    handle = _open()
    if handle is None:
        return False

    def run() -> None:
        # Rebuild the handle when it drops; otherwise only the interval backstop
        # would be left for the rest of the process.
        nonlocal handle
        infinite = 0xFFFFFFFF
        delay = 5.0
        drop_at: float | None = None
        warned_drop_at: float | None = None
        while True:
            while handle is not None:
                if k.WaitForSingleObject(handle, infinite) != 0:
                    break
                wake.set()
                if not k.FindNextChangeNotification(handle):
                    break
            if handle is not None:
                k.FindCloseChangeNotification(handle)
            handle = None
            wake.set()          # Make the caller run one backstop scan right away
            if drop_at is None:
                drop_at = _monotonic()
            # one fault, one push: one directory watcher outage starting at drop_at
            if warned_drop_at != drop_at:
                warned_drop_at = drop_at
                log.warning("目录监听掉了，%.0f 秒后重建；期间靠定时兜底", delay)
            else:
                log.info("目录监听仍未重建，%.0f 秒后再试；期间靠定时兜底", delay)
            time.sleep(delay)
            handle = _open()
            if handle is not None:
                log.info("目录监听已重建")
                delay = 5.0
                drop_at = None
                warned_drop_at = None
            else:
                delay = min(delay * 2, 60.0)

    threading.Thread(target=run, name="dir-watch", daemon=True).start()
    return True


def _kqueue(path: str, wake: threading.Event) -> bool:
    def _open():
        new_fd = os.open(path, os.O_RDONLY)
        new_kq = None
        try:
            new_kq = select.kqueue()
            ev = select.kevent(
                new_fd, filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND)
            new_kq.control([ev], 0, 0)
        except Exception:
            if new_kq is not None:
                try:
                    new_kq.close()
                except OSError:
                    pass
            try:
                os.close(new_fd)
            except OSError:
                pass
            raise
        return new_fd, new_kq

    fd: int | None
    fd, kq = _open()

    def _close() -> None:
        nonlocal fd, kq
        cur_kq, kq = kq, None
        cur_fd, fd = fd, None
        if cur_kq is not None:
            try:
                cur_kq.close()
            except OSError:
                pass
        if cur_fd is not None:
            try:
                os.close(cur_fd)
            except OSError:
                pass

    def run() -> None:
        # Same as above: rebuild when it drops, do not just return.
        nonlocal fd, kq
        delay = 5.0
        drop_at: float | None = None
        warned_drop_at: float | None = None
        while True:
            if kq is not None:
                try:
                    while True:
                        if kq.control(None, 1, None):
                            wake.set()
                except OSError:
                    pass
                _close()
            wake.set()
            if drop_at is None:
                drop_at = _monotonic()
            # one fault, one push: one directory watcher outage starting at drop_at
            if warned_drop_at != drop_at:
                warned_drop_at = drop_at
                log.warning("目录监听掉了，%.0f 秒后重建；期间靠定时兜底", delay)
            else:
                log.info("目录监听仍未重建，%.0f 秒后再试；期间靠定时兜底", delay)
            time.sleep(delay)
            try:
                fd, kq = _open()
                log.info("目录监听已重建")
                delay = 5.0
                drop_at = None
                warned_drop_at = None
            except OSError:
                delay = min(delay * 2, 60.0)

    threading.Thread(target=run, name="dir-watch", daemon=True).start()
    return True
