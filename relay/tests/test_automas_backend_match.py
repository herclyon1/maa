"""Only AUTO-MAS's own main.py is the backend; a failed OpenProcess tries the next match (audit s15 #3).

_automas_running / _automas_handle took any python.exe with "main.py" on its command
line. OK-WW runs `D:\\ark\\okww\\data\\apps\\ok-ww\\working\\main.py`
(tests/fixtures/okww_argv_20261012.log, ok-script.2026-10-12.log line 1) and may run
as python.exe (preupdate_okww.py). Then a dead backend read as alive while OK-WW ran
(nothing revived), and with no handle held an OK-WW start was adopted as the backend
(its exit logged as 「AUTO-MAS 后台意外退出了」). And the first match whose OpenProcess
failed ended the search, so a live backend listed after it was never attached.

The backend's command line as WMI returned it on the machine (2026-10-10, see
test_procs_wmi.py): `D:\\ark\\automas\\runtime\\environment\\venv\\Scripts\\python.exe main.py`.
"""
import ast
import re
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

from ark_relay.features.host import automas_procs  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


line = (Path(__file__).parent / "fixtures" / "okww_argv_20261012.log").read_text(encoding="utf-8")
okww_script = ast.literal_eval(re.search(r"(\[.*?\])", line).group(1))[0]
OKWW = rf"D:\ark\okww\data\apps\ok-ww\python\python.exe {okww_script}"
BACKEND = r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"
check("record: OK-WW runs a main.py", okww_script.endswith("main.py"), True)

commands.mas_up = lambda: (_ for _ in ()).throw(AssertionError("the list was readable"))

print("[后台没在跑、只有鸣潮脚本在跑：不算后台在跑]")
automas_procs._python_processes = lambda: [(25244, OKWW)]
check("_automas_running", automas_procs._automas_running(), False)
opened = []


def _open(access, inherit, pid):
    opened.append(pid)
    return f"handle:{pid}"


automas_procs.win32api.OpenProcess = _open
check("_automas_handle does not adopt OK-WW", automas_procs._automas_handle(), None)
check("OK-WW's pid never opened", opened, [])

print("[后台在跑：认得出]")
automas_procs._python_processes = lambda: [(25244, OKWW), (5088, BACKEND)]
check("_automas_running", automas_procs._automas_running(), True)
check("_automas_handle takes the backend", automas_procs._automas_handle(), "handle:5088")
automas_procs._python_processes = lambda: [(6000, "d:/ARK/AutoMAS/repo/Main.py")]
check("forward slashes and case do not matter", automas_procs._automas_running(), True)

print("[第一个匹配打不开：接着试下一个]")
opened.clear()


def _open_second(access, inherit, pid):
    opened.append(pid)
    if pid == 4100:
        raise OSError("access denied / gone")
    return f"handle:{pid}"


automas_procs.win32api.OpenProcess = _open_second
automas_procs._python_processes = lambda: [(4100, BACKEND), (5088, BACKEND)]
check("the second match is attached", automas_procs._automas_handle(), "handle:5088")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
