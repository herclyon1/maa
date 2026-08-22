"""The revival must not force-kill a window that is legitimately busy.

On 2026-08-22 an AUTO-MAS update was running its first-time environment
wizard - installing Python, pip and git, then cloning the backend. Throughout
that, no backend process exists. The revival read that as the stuck state it
guards against and ran `taskkill /IM AUTO-MAS.exe /F` twice, mid-clone. The
wizard then reported "所有镜像源都尝试失败" although every mirror was reachable
and carried the branch; the update completed on its own the moment the relay
was stopped.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# service.py imports pywin32 at module scope; stub what is missing so the
# module-level helpers can be imported on any machine.
class _Any:
    """Stands in for any pywin32 attribute: callable, subclassable, truthy."""
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


class _Out:
    def __init__(self, data): self.stdout = data


def _fake_run(mapping):
    def run(cmd, **kw):
        key = " ".join(cmd).lower()
        for needle, data in mapping.items():
            if needle in key:
                return _Out(data)
        return _Out(b"")
    return run


def check(name, got, want):
    print(f"  {'ok  ' if got == want else 'FAIL'} {name}: got {got!r}, want {want!r}")
    return got == want


def main():
    ok = True
    orig = service.subprocess.run

    # 1. Installer on screen -> veto, whatever else is true.
    service.subprocess.run = _fake_run(
        {"tasklist /nh": b"AUTO-MAS-Setup.exe  1234 Console"})
    ok &= check("安装程序在跑时 _installer_running", service._installer_running(), True)

    # 2. Ordinary process list -> no veto.
    service.subprocess.run = _fake_run({"tasklist /nh": b"explorer.exe 4 Console"})
    ok &= check("平时 _installer_running", service._installer_running(), False)

    # 3. tasklist unavailable -> assume yes, i.e. keep hands off. The wrong
    #    failure here kills a window; the right one merely delays a revival.
    def boom(cmd, **kw): raise OSError("no tasklist")
    service.subprocess.run = boom
    ok &= check("探测失败时 _installer_running 保守取 True",
                service._installer_running(), True)
    ok &= check("探测失败时 _automas_shell_running 保守取 True",
                service._automas_shell_running(), True)

    # 4. Shell detection reads the shell, not the backend.
    service.subprocess.run = _fake_run(
        {"imagename eq auto-mas.exe": b"AUTO-MAS.exe  18864 Console"})
    ok &= check("窗口在时 _automas_shell_running", service._automas_shell_running(), True)
    service.subprocess.run = _fake_run(
        {"imagename eq auto-mas.exe": b"INFO: No tasks are running"})
    ok &= check("窗口不在时 _automas_shell_running", service._automas_shell_running(), False)

    # 5. The grace period is long enough for a real first-run wizard and far
    #    shorter than the stuck state it guards against.
    ok &= check("宽限期至少 10 分钟", service.SHELL_GRACE_SECONDS >= 600, True)

    service.subprocess.run = orig
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
