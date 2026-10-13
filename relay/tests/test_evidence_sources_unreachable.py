"""The upstream-source check says why it could not fetch, and when it tries again.

relay.log since 2026-10-11 10:04 has the boot line 「上游导出代码核对：3 个文件今天拉不到，
明天再比」 on almost every boot: sources.check_sources swallowed the exception, so
nobody could tell a DNS failure from a timeout or a jsDelivr refusal, and 「明天再比」
was wrong - the stage runs on every boot (audit s17 F5).
"""
import sys
import tempfile
import types
import urllib.error
import urllib.request
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

import boot_stages  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Log:
    def __init__(self): self.lines = []
    def warning(self, *a): self.lines.append(a[0] % a[1:])
    def info(self, *a): self.lines.append(a[0] % a[1:] if len(a) > 1 else a[0])
    def exception(self, *a): self.lines.append(a[0])


def down(*a, **k):
    raise urllib.error.URLError(TimeoutError("timed out"))


print("[jsDelivr unreachable on boot: the log line carries the reason]")
saved, urllib.request.urlopen = urllib.request.urlopen, down
try:
    log = _Log()
    boot_stages._stage_evidence_sources(types.SimpleNamespace(state_dir=Path(tempfile.mkdtemp())), None, log)
finally:
    urllib.request.urlopen = saved
line = next((ln for ln in log.lines if ln.startswith("上游导出代码核对")), "")
print("   ", line)
check("one line about the unreachable files", line.startswith("上游导出代码核对：3 个文件"))
check("it names the exception", "timed out" in line and "URLError" in line)
check("it says the next boot compares again, not tomorrow", ("下次开机再比" in line, "明天" in line), (True, False))

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall passed")
