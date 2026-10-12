"""A process list that cannot be read is "unknown", never a yes (review of 2026-10-07, item 2).

procs.py records the incident this guards against: from 2026-08-28 to 09-17 the
keeper read "cannot tell" as "alive" and went blind for three weeks - no
revival, no alarm, and the evening queue of the 17th was lost. Two probes still
turned "cannot tell" into a definite answer; the one left here
(gameupdate_games._alive / wait_ready went with the WuWa launcher update on
2026-10-12, AUTO-MAS item 10b):

* automas_procs._installer_running answered True ("an installer is on screen") when
  tasklist failed, and _revive then logged 「安装程序正在运行」 - a sentence that
  was not true. Now it answers None; _revive still keeps its hands off (killing
  a window mid-install is the worse mistake, see test_revive_gates.py) but says
  what actually happened: the process list could not be read.
"""
import subprocess
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
              "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(_name, _Stub(_name))

import boot_stages  # noqa: E402
from ark_relay.features.host import automas_keeper, automas_procs  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def _boom(*a, **k):
    raise OSError("tasklist is gone")


# ------------------------------------------------------------ service.py
print("[automas_procs._installer_running：进程表读不到 → None，不是「有安装程序」]")
orig_run = automas_procs.subprocess.run
automas_procs.subprocess.run = _boom
check("读不到 → None", automas_procs._installer_running(), None)
automas_procs.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"AUTO-MAS-Setup.exe 1 Console", b"")
check("有安装程序 → True", automas_procs._installer_running(), True)
automas_procs.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"explorer.exe 4 Console", b"")
check("没有 → False", automas_procs._installer_running(), False)
automas_procs.subprocess.run = orig_run


class _Log:
    def __init__(self): self.rows = []
    def info(self, msg, *a, **k): self.rows.append(("INFO", msg % a if a else msg))
    def warning(self, msg, *a, **k): self.rows.append(("WARNING", msg % a if a else msg))
    def exception(self, msg, *a, **k): self.rows.append(("ERROR", msg % a if a else msg))


class _Notifier:
    def __init__(self): self.sent = []
    def send(self, title, body, **k): self.sent.append(title); return []


print("\n[_revive：进程表读不到时不动 AUTO-MAS，但说的是「读不到」而不是「安装程序在跑」]")
k = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
k.log, k.notifier = _Log(), _Notifier()
k.revive_failures = 0
k.revive_alerted = False
k.shell_only_since = None
k.shell_grace_noted = False
k.gone = None
revived = []
saved = (automas_procs._installer_running, automas_procs._automas_shell_running, boot_stages._revive_automas)
automas_procs._installer_running = lambda: None
automas_procs._automas_shell_running = lambda: False
boot_stages._revive_automas = lambda: revived.append(1)
k._revive(1000.0)
check("不去重新打开（装到一半被关掉更糟）", revived, [])
said = " ".join(m for _, m in k.log.rows)
check("没说「安装程序正在运行」", "安装程序正在运行" in said, False)
check("说了进程表读不到", "读不到" in said, True)
check("没有待定的退出时这一句是 WARNING（不是静默）", any(lv == "WARNING" for lv, _ in k.log.rows), True)
automas_procs._installer_running, automas_procs._automas_shell_running, boot_stages._revive_automas = saved

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
