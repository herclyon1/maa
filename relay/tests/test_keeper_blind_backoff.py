"""The keeper does not back off when it revived nothing (audit s15 #1, 2026-10-13).

Machine record (tests/fixtures/keeper_blind_20261010.log, relay.log 10-10 16:14:07):
the process table could not be read (「读得到每个程序是怎么启动的…读不到」) while
AUTO-MAS answered (「✓ 调度程序有应答」). Five relay starts from 16:14 to 17:21 got no
backend handle. In that state _automas_running() is True (it falls back to the
API), nothing is revived, and every handle-less check still doubled revive_wait:
checks at 180, 360, 720, 1440, 2880 s ... out to every 30 minutes, with not one
keeper line in the log. A backend that died then was found up to 30 minutes late.

Now: the wait doubles only after a real revival; a backend that is up but cannot
be attached is checked every procwatch.AUTOMAS_CHECK_SECONDS, and that is said
once at INFO.
"""
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
              "win32con", "win32file", "servicemanager", "win32process",
              "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
              "win32evtlog", "win32gui"):
    sys.modules.setdefault(_name, _Stub(_name))

import time  # noqa: E402

import boot_stages  # noqa: E402
from ark_relay.features.host import automas_keeper, automas_procs, procwatch  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


# The machine's state, read from its own self-check lines.
lines = (Path(__file__).parent / "fixtures" / "keeper_blind_20261010.log").read_text(encoding="utf-8").splitlines()
procs_unreadable = any("读得到每个程序是怎么启动的" in ln and "读不到" in ln for ln in lines)
api_answers = any("✓ 调度程序有应答" in ln for ln in lines)
check("record: process table unreadable", procs_unreadable, True)
check("record: API answering", api_answers, True)

clock = [1000.0]
time.monotonic = lambda: clock[0]
automas_procs._python_processes = lambda: None if procs_unreadable else []
commands.mas_up = lambda: api_answers
procwatch._start_process_watch = lambda evt, alive, log: True
revives = []
boot_stages._revive_automas = lambda: revives.append(clock[0])


class _Keep(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelname, record.getMessage()))


keep = _Keep()
log = logging.getLogger("ark.service")
log.addHandler(keep)
log.setLevel(logging.INFO)


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, *a, **k):
        self.sent.append(title)


print("[进程表读不到、接口有应答：没拉起过就不退避，按活性检查间隔查]")
k = automas_keeper._AutomasKeeper(log, _Notifier())
check("no handle at start", k.handle, None)
keep.rows.clear()
checks = []
start = clock[0]
while clock[0] - start < 2 * 3600:
    clock[0] += k.cap_wait(3600.0)
    due = k.revive_deadline
    k.check(False, clock[0])
    if due is not None and clock[0] >= due:
        checks.append(clock[0])
gaps = [round(b - a) for a, b in zip(checks, checks[1:])]
check("checks within the first two hours (>= 40, was 5)", len(checks) >= 40, True)
check("no gap longer than the liveness interval", max(gaps) if gaps else None, procwatch.AUTOMAS_CHECK_SECONDS)
check("nothing revived", revives, [])
said = [m for lv, m in keep.rows if "挂不上它的进程句柄" in m]
check("said once", len(said), 1)
check("at INFO", [lv for lv, m in keep.rows if "挂不上它的进程句柄" in m], ["INFO"])

print("[真拉起过、没起来：照旧翻倍退避]")
automas_procs._python_processes = lambda: []
commands.mas_up = lambda: False
automas_procs._installer_running = lambda: False
automas_procs._automas_shell_running = lambda: False
clock[0] = 50000.0
k2 = automas_keeper._AutomasKeeper(log, _Notifier())
waits = []
for _ in range(4):
    clock[0] = k2.revive_deadline
    k2.check(False, clock[0])
    waits.append(round(k2.revive_deadline - clock[0]))
check("180, 360, 720, 1440", waits, [180, 360, 720, 1440])
check("four revivals", len(revives), 4)

print("[拦着没拉（安装程序开着）：不翻倍]")
automas_procs._installer_running = lambda: True
revives.clear()
clock[0] = 90000.0
k3 = automas_keeper._AutomasKeeper(log, _Notifier())
waits = []
for _ in range(3):
    clock[0] = k3.revive_deadline
    k3.check(False, clock[0])
    waits.append(round(k3.revive_deadline - clock[0]))
check("held: the wait stays 180", waits, [180, 180, 180])
check("held: nothing revived", revives, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
