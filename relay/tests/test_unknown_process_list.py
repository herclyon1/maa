"""A process list that cannot be read is "unknown", never a yes (review of 2026-10-07, item 2).

procs.py records the incident this guards against: from 2026-08-28 to 09-17 the
keeper read "cannot tell" as "alive" and went blind for three weeks - no
revival, no alarm, and the evening queue of the 17th was lost. Two probes still
turned "cannot tell" into a definite answer:

* gameupdate_games._alive answered True ("still running") when tasklist failed.
  Now it answers None, and wait_ready treats None as unknown: it keeps reading
  the screen (the screen decides), and only False - the game really missing
  from a list that was read - ends the wait.
* service._installer_running answered True ("an installer is on screen") when
  tasklist failed, and _revive then logged 「安装程序正在运行」 - a sentence that
  was not true. Now it answers None; _revive still keeps its hands off (killing
  a window mid-install is the worse mistake, see test_revive_gates.py) but says
  what actually happened: the process list could not be read.
"""
import logging
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
import service  # noqa: E402
from ark_relay import gameupdate_games as gug  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def _boom(*a, **k):
    raise OSError("tasklist is gone")


# ------------------------------------------------------------ service.py
print("[service._installer_running：进程表读不到 → None，不是「有安装程序」]")
orig_run = service.subprocess.run
service.subprocess.run = _boom
check("读不到 → None", service._installer_running(), None)
service.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"AUTO-MAS-Setup.exe 1 Console", b"")
check("有安装程序 → True", service._installer_running(), True)
service.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"explorer.exe 4 Console", b"")
check("没有 → False", service._installer_running(), False)
service.subprocess.run = orig_run


class _Log:
    def __init__(self): self.rows = []
    def info(self, msg, *a, **k): self.rows.append(("INFO", msg % a if a else msg))
    def warning(self, msg, *a, **k): self.rows.append(("WARNING", msg % a if a else msg))
    def exception(self, msg, *a, **k): self.rows.append(("ERROR", msg % a if a else msg))


class _Notifier:
    def __init__(self): self.sent = []
    def send(self, title, body, **k): self.sent.append(title); return []


print("\n[_revive：进程表读不到时不动 AUTO-MAS，但说的是「读不到」而不是「安装程序在跑」]")
k = service._AutomasKeeper.__new__(service._AutomasKeeper)
k.log, k.notifier = _Log(), _Notifier()
k.revive_failures = 0
k.revive_alerted = False
k.shell_only_since = None
k.shell_grace_noted = False
k.gone = None
revived = []
saved = (service._installer_running, service._automas_shell_running, boot_stages._revive_automas)
service._installer_running = lambda: None
service._automas_shell_running = lambda: False
boot_stages._revive_automas = lambda: revived.append(1)
k._revive(1000.0)
check("不去重新打开（装到一半被关掉更糟）", revived, [])
said = " ".join(m for _, m in k.log.rows)
check("没说「安装程序正在运行」", "安装程序正在运行" in said, False)
check("说了进程表读不到", "读不到" in said, True)
check("没有待定的退出时这一句是 WARNING（不是静默）", any(lv == "WARNING" for lv, _ in k.log.rows), True)
service._installer_running, service._automas_shell_running, boot_stages._revive_automas = saved

# ------------------------------------------------------- gameupdate_games
print("\n[gameupdate_games._alive：tasklist 读不出 → None，不是「还在」]")
real_run = subprocess.run
try:
    subprocess.run = _boom
    check("抛异常 → None", gug._alive("Client-Win64-Shipping.exe")(), None)
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b"")
    check("空输出 → None", gug._alive("Client-Win64-Shipping.exe")(), None)
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, b"ERROR", b"")
    check("退出码非 0 → None", gug._alive("Client-Win64-Shipping.exe")(), None)
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"Client-Win64-Shipping.exe 1\n", b"")
    check("列表里有 → True", gug._alive("Client-Win64-Shipping.exe")(), True)
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"explorer.exe 1\n", b"")
    check("列表里没有 → False", gug._alive("Client-Win64-Shipping.exe")(), False)
finally:
    subprocess.run = real_run


class _Scr:
    def __init__(self, lines): self.lines, self.error, self.shot = lines, "", ""
    def has(self, *words): return any(w in ln for w in words for ln in self.lines)
    def dump(self, n=6): return " / ".join(self.lines[:n])


class _Desk:
    def __init__(self, screens): self.screens = list(screens)
    def read(self, focus=None, settle_ms=0):
        return _Scr(self.screens.pop(0) if len(self.screens) > 1 else self.screens[0])


class _Keep(logging.Handler):
    def __init__(self):
        super().__init__(); self.msgs = []

    def emit(self, r):
        self.msgs.append((r.levelname, r.getMessage()))


keep = _Keep()
gug.log.addHandler(keep)
print("\n[wait_ready：存活读不出（None）不算「进程没了」，接着看屏幕]")
desk = _Desk([["加载中"], ["点击连接"]])
how = gug.wait_ready(desk, "鸣潮", focus="Client-Win64-Shipping", alive=lambda: None,
                     budget_s=600, poll_s=1, sleep=lambda s: None)
check("读到登录界面就算到了", how, "读到「点击连接」")
check("没说「进程没了」", any("进程没了" in m for _, m in keep.msgs), False)

print("\n[wait_ready：列表读到了、游戏不在（False）→ 立刻停]")
keep.msgs.clear()
desk = _Desk([["点击连接"]])
how = gug.wait_ready(desk, "鸣潮", focus="Client-Win64-Shipping", alive=lambda: False,
                     budget_s=600, poll_s=1, sleep=lambda s: None)
check("返回空", how, "")
check("说了进程没了", any("进程没了" in m for _, m in keep.msgs), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
