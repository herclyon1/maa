"""主循环拆出来的两个部件：目录监听的退避、AUTO-MAS 保活的睡眠上限与退避。

2026-09-08 把 241 行的 `_loop` 拆成 `_DirWatch` + `_AutomasKeeper` + 一段短循环。
拆之前这些状态是循环里的十来个局部变量，没法单独测，只能靠上机跑一整轮。
"""
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


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

import service  # noqa: E402
# `_revive_automas` 2026-09-08 随开机流程搬去了 boot_stages.py，
# `_AutomasKeeper._revive` 现在调的是那一份，所以要替换的也是那一份。
import boot_stages  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): pass


class Notifier:
    def __init__(self): self.sent = []
    def send(self, title, body, **k): self.sent.append(title); return []


print("[目录监听：重建失败按 5→10→20…封顶 60 秒退避]")
cfg = types.SimpleNamespace(history_dir=Path("/nope"))
w = service._DirWatch(cfg, Notifier(), Log())
w.handle = None
boom = _Stub("win32file")
boom.FindFirstChangeNotification = lambda *a: (_ for _ in ()).throw(OSError("no"))
orig_file = service.win32file
service.win32file = boom
delays = []
now = [1000.0]
service.time = types.SimpleNamespace(monotonic=lambda: now[0], sleep=lambda s: None)
for _ in range(5):
    now[0] = w.retry_at
    w.maybe_rebuild()
    delays.append(w.retry_delay)
check("退避翻倍到 60 封顶", delays, [10.0, 20.0, 40.0, 60.0, 60.0])
check("失败期间句柄仍是空", w.handle, None)
now[0] = w.retry_at - 1
before = w.retry_delay
w.maybe_rebuild()
check("没到点不重试", w.retry_delay, before)
service.win32file = orig_file

print("[目录监听：没配历史目录就彻底不管]")
w2 = service._DirWatch(types.SimpleNamespace(history_dir=None), Notifier(), Log())
w2.retry_at = 0
w2.maybe_rebuild()
check("不重建", w2.handle, None)

print("[保活：句柄不在时不许睡过「该来了」那一刻]")
k = service._AutomasKeeper.__new__(service._AutomasKeeper)
k.log, k.notifier = Log(), Notifier()
k.handle = None
k.wmi_alive = {"ok": True}
k.revive_deadline = 1030.0
now[0] = 1000.0
check("睡到 deadline（30 秒），不是一小时", k.cap_wait(3600.0), 30.0)
k.revive_deadline = 999.0
check("已经过点了也至少睡 1 秒", k.cap_wait(3600.0), 1.0)
k.wmi_alive = {"ok": False}
k.revive_deadline = None
check("订阅不可用时退回活性检查间隔",
      k.cap_wait(3600.0), service.AUTOMAS_CHECK_SECONDS)
k.handle = object()
check("句柄在就不压缩", k.cap_wait(3600.0), 3600.0)

print("[保活：连败到阈值才告警，且只告一次]")
k2 = service._AutomasKeeper.__new__(service._AutomasKeeper)
n = Notifier()
k2.log, k2.notifier = Log(), n
k2.handle = None
k2.wmi_alive = {"ok": True}
k2.revive_deadline = None
k2.revive_wait = float(service.REVIVE_FIRST_WAIT)
k2.revive_failures = service.REVIVE_ALERT_AFTER - 1
k2.revive_alerted = False
k2.shell_only_since = None
k2.shell_grace_noted = False
k2.next_check = 0.0
orig_running, orig_shell, orig_inst, orig_revive = (
    service._automas_running, service._automas_shell_running,
    service._installer_running, boot_stages._revive_automas)
service._automas_running = lambda: False
service._automas_shell_running = lambda: False
service._installer_running = lambda: False
boot_stages._revive_automas = lambda: None
k2._revive(1000.0)
check("到阈值告一次", n.sent, [service.texts.AUTOMAS_DOWN])
k2._revive(1000.0)
check("再败不重复告", n.sent, [service.texts.AUTOMAS_DOWN])
service._automas_running, service._automas_shell_running = orig_running, orig_shell
service._installer_running, boot_stages._revive_automas = orig_inst, orig_revive

print("[保活：窗口在、后端不在 → 先给宽限，超时才动手]")
k3 = service._AutomasKeeper.__new__(service._AutomasKeeper)
k3.log, k3.notifier = Log(), Notifier()
k3.revive_failures = 0
k3.revive_alerted = False
k3.shell_only_since = None
k3.shell_grace_noted = False
revived = []
service._automas_running = lambda: False
service._automas_shell_running = lambda: True
service._installer_running = lambda: False
boot_stages._revive_automas = lambda: revived.append(1)
k3._revive(1000.0)
check("宽限期内不拉起", revived, [])
k3._revive(1000.0 + service.SHELL_GRACE_SECONDS - 1)
check("还在宽限期，仍不拉起", revived, [])
k3._revive(1000.0 + service.SHELL_GRACE_SECONDS)
check("超过宽限才拉起", revived, [1])
service._automas_running, service._automas_shell_running = orig_running, orig_shell
service._installer_running, boot_stages._revive_automas = orig_inst, orig_revive

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
