"""Log every foreground-window change, to find out what steals focus.

MaaEnd on Windows can only drive the game through its foreground controller:
the game window must stay on top and unobstructed. Runs keep failing a few
seconds after MaaEnd connects (MaaEnd/MaaEnd#4820), and the open question is
which process takes the foreground at that moment.

This uses SetWinEventHook(EVENT_SYSTEM_FOREGROUND), a push notification from
the window manager - no polling. Each change is appended to a log with the
timestamp, PID, process name and window title.

Must run in the interactive session (session 1); a service in session 0 sees
no desktop. Launch it through the ark-do scheduled task.
"""
import ctypes
import ctypes.wintypes as wt
import os
import time

LOG = r"C:\ProgramData\focus-watch.log"
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


def process_name(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wt.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return "?"
    finally:
        kernel32.CloseHandle(h)


def write(line):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def on_event(hook, event, hwnd, id_object, id_child, thread, ts):
    try:
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        write("%s  pid=%-6d %-24s %s" % (
            time.strftime("%H:%M:%S"), pid.value,
            process_name(pid.value), buf.value[:60]))
    except Exception as exc:  # noqa: BLE001 - a probe must never die
        write("%s  ERROR %s" % (time.strftime("%H:%M:%S"), exc))


WinEventProc = ctypes.WINFUNCTYPE(
    None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)
cb = WinEventProc(on_event)

write("=== focus watch started %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
hook = user32.SetWinEventHook(
    EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, 0, cb, 0, 0,
    WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
if not hook:
    write("SetWinEventHook failed")
    raise SystemExit(1)

msg = wt.MSG()
while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
    user32.TranslateMessage(ctypes.byref(msg))
    user32.DispatchMessageW(ctypes.byref(msg))
