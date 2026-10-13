"""watch._windows must close a dropped change handle before opening a new one.

Audit s2 F5 (2026-10-13): when WaitForSingleObject / FindNextChangeNotification
failed, the loop dropped the handle and called FindFirstChangeNotificationW again
without FindCloseChangeNotification, leaking one kernel handle per rebuild.
kernel32 is faked here so the Windows path runs on any machine.
"""
import ctypes
import sys
import threading
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import watch

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


class Fn:
    """A kernel32 function: restype / argtypes are set on it, calls go to `body`."""

    def __init__(self, body):
        self.body = body

    def __call__(self, *a):
        return self.body(*a)


opened: list = []
closed: list = []
second_open = threading.Event()
park = threading.Event()        # never set: the rebuilt handle just waits


def first(path, sub, flags):
    h = len(opened) + 100
    opened.append(h)
    if len(opened) == 2:
        second_open.set()
    return h


def wait(h, ms):
    if h == 100:
        return 0xFFFFFFFF       # WAIT_FAILED: the first handle drops
    park.wait()
    return 0


k = types.SimpleNamespace(
    FindFirstChangeNotificationW=Fn(first),
    WaitForSingleObject=Fn(wait),
    FindNextChangeNotification=Fn(lambda h: 1),
    FindCloseChangeNotification=Fn(lambda h: closed.append(h) or 1),
)
ctypes.windll = types.SimpleNamespace(kernel32=k)
watch.time = types.SimpleNamespace(sleep=lambda s: None)

print("[the first handle drops; it is closed before the rebuild opens another]")
check("watcher started", watch._windows("C:/x", threading.Event()), True)
check("a second handle was opened", second_open.wait(5), True)
check("the dropped handle was closed", closed, [100])

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
sys.exit(1 if fails else 0)
