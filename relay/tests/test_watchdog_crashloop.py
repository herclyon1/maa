"""The watchdog says why the relay does not start, and rings when it keeps crashing.

Two gaps between the installed relay and the old service, 2026-10-11:
  a. A relay that dies before its log is open (an import error, a broken .env) left
     no trace: the scheduled task runs pythonw.exe, which has no console, and the
     watchdog's 「重开 3 次都没起来」 alarm said nothing about why. packaging/launch.py now
     appends the traceback to <data>\\start-error.txt, and the watchdog puts its last
     lines into the alarm when it was written in that stretch.
  b. A relay that comes up and dies again a while later never reached FAIL_LIMIT: each
     look that found it running reset the count (2026-10-10 16:28: 15 restarts, no
     alarm). The watchdog now rings once when it had to start the relay LOOP_STARTS
     times within LOOP_WINDOW_S, at most once per LOOP_QUIET_S, not during a shutdown.

Runs on any OS: pywin32 is faked, the watchdog's Windows calls are replaced.
"""
import os
import sys
import time
import types
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))
from _tmp import tmpdir  # noqa: E402

DATA = tmpdir()
os.environ["ARK_HOME"] = str(DATA)

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def _module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class _PyError(Exception):
    pass


SHUTTING = {"on": 0}
_module("pywintypes", error=_PyError)
_module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
_module("win32api", GetSystemMetrics=lambda i: SHUTTING["on"], CloseHandle=lambda h: None)
_module("win32event", CreateEvent=lambda *a: None, SetEvent=lambda e: None, WaitForSingleObject=lambda *a: 0,
        WAIT_TIMEOUT=258)
_module("win32service", SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_PRESHUTDOWN=0xF,
        SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)
_module("win32serviceutil", ServiceFramework=object)
_module("win32ts")

import ark_watchdog as W  # noqa: E402
import launch  # noqa: E402

# ---------------------------------------------------------------- a. the record
print("[launch.py: a start that dies with a Python error leaves its traceback]")
check("same file name on both sides", W.START_ERROR.name, launch.START_ERROR)
check("same data folder on both sides", (W.DATA, launch.DATA), (DATA, DATA))
code = tmpdir() / "versions" / "20261011120000"
code.mkdir(parents=True)
(code / "app_main.py").write_text("import ark_relay_module_that_is_not_there\n", encoding="utf-8")
real_folder, real_argv = launch._code_folder, sys.argv
launch._code_folder = lambda: code
sys.argv = ["launch.py"]
try:
    launch.main()
    raised = None
except ModuleNotFoundError as exc:
    raised = exc
finally:
    sys.argv = real_argv
check("the error still goes on (the task sees the process fail)", type(raised).__name__, "ModuleNotFoundError")
rec = (DATA / launch.START_ERROR).read_text(encoding="utf-8")
check("the record names the error", "No module named 'ark_relay_module_that_is_not_there'" in rec)
check("the record names the version folder and the command", (str(code) in rec, "launch.py run" in rec), (True, True))
check("the record holds the traceback", "Traceback (most recent call last)" in rec)

print("[launch.py: a stop / rollback / stop-push exit code is not an error]")
(DATA / launch.START_ERROR).unlink()
(code / "app_main.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
sys.argv = ["launch.py", "stop"]
try:
    launch.main()
except SystemExit:
    pass
finally:
    sys.argv = real_argv
    launch._code_folder = real_folder
check("no record for SystemExit", (DATA / launch.START_ERROR).exists(), False)

print("[launch.py: the file keeps only the newest failures]")
for i in range(400):
    launch.record_start_error(["run"], code, f"Traceback (most recent call last):\nboom number {i}\n" + "x" * 200)
rec = (DATA / launch.START_ERROR).read_text(encoding="utf-8")
check("capped", len(rec) <= launch.START_ERROR_MAX, True)
check("the newest one is kept", rec.rstrip().endswith("x" * 200) and "boom number 399" in rec, True)

# ---------------------------------------------------------------- the watchdog
pushed, started = [], []
running = {"on": False}
W.main_running = lambda: running["on"]
W.someone_logged_on = lambda: True
W.start_main = lambda: started.append(1) or True
W.push = pushed.append
W._log = lambda line: None
NOW = time.time()


def tick(w, minute, up=False, wall_base=NOW):
    running["on"] = up
    w.tick(minute * 60.0, wall=wall_base + minute * 60.0)


print("\n[never comes up: 「中继停了」 at the 3rd start, with the record's last lines]")
(DATA / launch.START_ERROR).unlink()
launch.record_start_error(["run"], code, 'Traceback (most recent call last):\n  File "app_main.py", line 1\n'
                          "ModuleNotFoundError: No module named 'win32event'")
os.utime(DATA / launch.START_ERROR, (NOW + 30, NOW + 30))
w = W.Watch(0.0)
for m in (0, 0.5, 1):
    tick(w, m)
check("one push", len(pushed), 1)
check("it is 「中继停了」", pushed[0].startswith("🔌 中继停了"), True)
check("with the record's head line", W.REASON_HEAD in pushed[0], True)
check("with the error line", pushed[0].rstrip().endswith("No module named 'win32event'"), True)
check("short enough for the group bot", len(pushed[0].encode("utf-8")) < 2048, True)
for m in (1.5, 2, 2.5, 3):
    tick(w, m)
check("no crash-loop alarm on top of 「中继停了」 for the same stretch", len(pushed), 1)

print("[a record from before this stretch is not shown]")
os.utime(DATA / launch.START_ERROR, (NOW - 3600, NOW - 3600))
pushed.clear()
w = W.Watch(0.0)
for m in (0, 0.5, 1):
    tick(w, m)
check("「中继停了」 says there is no record", (W.REASON_HEAD in pushed[0], W.REASON_NONE in pushed[0]), (False, True))

print("[comes up and dies again: 4 starts in 30 minutes quiet, the 5th rings once]")
pushed.clear()
w = W.Watch(0.0)
for k in range(4):
    tick(w, 5 * k, up=True)
    tick(w, 5 * k + 0.5)                # gone again: the watchdog starts it
check("4 starts: nothing", len(pushed), 0)
tick(w, 20, up=True)
tick(w, 20.5)
check("5th start: one push", len(pushed), 1)
check("it is the crash-loop alarm", pushed[0].startswith("🔌 中继反复崩溃重开"), True)
check("it says 5 times in 30 minutes", "30 分钟内重开了 5 次" in pushed[0], True)
check("no fresh record: says so", W.REASON_NONE in pushed[0], True)
for k in range(5, 16):                  # still crashing every 5 minutes, to 75.5: within the hour
    tick(w, 5 * k, up=True)
    tick(w, 5 * k + 0.5)
check("no second push within the hour", len(pushed), 1)
tick(w, 80, up=True)
tick(w, 80.5)                           # 60 minutes after the first push
check("again after an hour while it still crashes", len(pushed), 2)

print("[spread out: 5 starts over more than 30 minutes do not ring]")
pushed.clear()
w = W.Watch(0.0)
for k in range(6):
    tick(w, 10 * k, up=True)
    tick(w, 10 * k + 0.5)
check("one start every 10 minutes: nothing", len(pushed), 0)

print("[starts at a shutdown are not counted]")
pushed.clear()
started.clear()
w = W.Watch(0.0)
SHUTTING["on"] = 1
for k in range(6):
    tick(w, k)
SHUTTING["on"] = 0
check("no start, no push while Windows shuts down", (len(started), len(pushed)), (0, 0))
W.SESSION_ENDING.write_text("x", encoding="utf-8")
for k in range(6):
    tick(w, k)                          # within ENDING_HOLD_S of the marker
W.SESSION_ENDING.unlink()
check("none while the relay's session ends", (len(started), len(pushed), len(w.starts)), (0, 0, 0))

print("[a record in Chinese is cut by bytes, so the alarm stays one group message]")
launch.record_start_error(["run"], code, "Traceback (most recent call last):\n" + "\n".join(
    "RuntimeError: " + "读不了配置文件" * 30 for _ in range(8)))
os.utime(DATA / launch.START_ERROR, (NOW + 30, NOW + 30))
pushed.clear()
w = W.Watch(0.0)
for m in (0, 0.5, 1):
    tick(w, m)
check("Chinese tail: under 2048 bytes", len(pushed[0].encode("utf-8")) < 2048, True)

print("[the crash-loop record: one written during the stretch is shown]")
pushed.clear()
w = W.Watch(0.0)
os.utime(DATA / launch.START_ERROR, (NOW + 10 * 60, NOW + 10 * 60))
for k in range(5):
    tick(w, 5 * k, up=True)
    tick(w, 5 * k + 0.5)
check("crash-loop push carries the record", (len(pushed), W.REASON_HEAD in pushed[-1]), (1, True))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
