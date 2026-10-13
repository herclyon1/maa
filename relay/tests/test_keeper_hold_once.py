"""A hold that lasts is said at WARNING once, not at every check (review of bd80586d, 2026-10-13).

bd80586d stopped doubling revive_wait when a check revived nothing, so a hold
(an installer on screen, or the program list unreadable) re-armed at 180 s for as
long as it lasted, and each check logged its hold line at WARNING through `say`,
which errwatch pushes to the group: 40 pushes in 2 hours against 8 before (when
every check doubled the wait). Now the hold keeps the 180 s check and is said at
WARNING the first time, at INFO while it lasts; a real revival says it again.
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


clock = [1000.0]
time.monotonic = lambda: clock[0]
automas_procs._python_processes = lambda: []
commands.mas_up = lambda: False
automas_procs._automas_shell_running = lambda: False
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
log = automas_keeper.log
log.addHandler(keep)
log.setLevel(logging.INFO)


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, *a, **k):
        self.sent.append(title)



OLD_COUNT = 8   # before bd80586d: checks at 180, 540, 1260, 2700, 4500, 6300 s ... within 2 hours


def two_hours(label, installer, hint):
    print(f"[{label}：两小时只报一次]")
    automas_procs._installer_running = lambda: installer
    revives.clear()
    clock[0] += 100000.0
    k = automas_keeper._AutomasKeeper(log, _Notifier())
    keep.rows.clear()
    checks = 0
    start = clock[0]
    while clock[0] - start < 2 * 3600:
        clock[0] = k.revive_deadline
        k.check(False, clock[0])
        checks += 1
    warned = [m for lv, m in keep.rows if lv == "WARNING" and hint in m]
    infos = [m for lv, m in keep.rows if lv == "INFO" and hint in m]
    check(f"{label}: still checked every 180 s", checks >= 40, True)
    check(f"{label}: nothing revived", revives, [])
    check(f"{label}: WARNINGs at most the old count ({OLD_COUNT})", len(warned) <= OLD_COUNT, True)
    check(f"{label}: one WARNING", len(warned), 1)
    check(f"{label}: the rest at INFO", len(infos), checks - 1)
    return k


two_hours("安装程序开着", True, "安装程序正在运行")
k = two_hours("读不到程序列表", None, "读不到正在运行的程序列表")

print("[拦着之后真拉起过、又拦住：再说一次]")
automas_procs._installer_running = lambda: False
clock[0] = k.revive_deadline
k.check(False, clock[0])
check("revived once", len(revives), 1)
automas_procs._installer_running = lambda: True
keep.rows.clear()
for _ in range(3):
    clock[0] = k.revive_deadline
    k.check(False, clock[0])
check("a new hold after a revival: one WARNING",
      [lv for lv, m in keep.rows if "安装程序正在运行" in m], ["WARNING", "INFO", "INFO"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
