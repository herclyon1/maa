"""procs.python_processes on the machine as it was after 2026-10-10 16:05.

16:05:10 the relay's DispatchWithEvents generated pywin32's early-bound wrapper
of the WMI scripting library. From then on every Win32_Process row came back as
an early-bound SWbemObject: `row.ProcessId` raised AttributeError, the process
table was unreadable, the 16:14:07 boot self-check went red and the keeper never
attached its handle to AUTO-MAS. Reproduced on the machine 16:40 (AttributeError
"ISWbemObject ... has no attribute 'ProcessId'", then "Win32 exception occurred
releasing IUnknown" for the rows the traceback had kept past CoUninitialize).

The fakes below behave the same way: rows without the attributes, only
Properties_; and every COM object records whether it is still alive when
CoUninitialize runs (the 16:27 retry crashed pythonservice.exe that way).
"""
import gc
import logging
import sys
import types
import weakref
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import procs

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _ComError(Exception):
    def __init__(self, hresult):
        super().__init__(hresult, "fake", None, None)
        self.hresult = hresult


_alive = weakref.WeakSet()
_leaked = []          # objects still alive at a CoUninitialize


class _Com:
    def __init__(self):
        _alive.add(self)


class _Prop(_Com):
    def __init__(self, value):
        super().__init__()
        self.Value = value


class _EarlyBoundRow(_Com):
    """An early-bound SWbemObject: the class's properties only through Properties_."""

    def __init__(self, pid, cmd):
        super().__init__()
        self._p = {"ProcessId": pid, "CommandLine": cmd}

    def Properties_(self, name):  # noqa: N802 - COM's name
        if name not in self._p:
            raise _ComError(-2147352567)          # 0x80020009, as on the machine
        return _Prop(self._p[name])


class _Result(_Com):
    def __init__(self, rows, fail_at=None):
        super().__init__()
        self.rows, self.fail_at = rows, fail_at

    def __iter__(self):
        for i, r in enumerate(self.rows):
            if i == self.fail_at:
                raise _ComError(-2147217358)      # 0x80041032 WBEM_E_CALL_CANCELLED
            yield r


plan = []             # per try: "ok" | "cancel"


class _Services(_Com):
    def ExecQuery(self, q):  # noqa: N802 - COM's name
        step = plan.pop(0) if plan else "ok"
        rows = [_EarlyBoundRow(5088, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                _EarlyBoundRow(2076, r"C:\Program Files\Python314\python.exe x.py")]
        return _Result(rows, fail_at=0 if step == "cancel" else None)


def _co_uninit():
    gc.collect()
    _leaked.extend(type(o).__name__ for o in list(_alive))


sys.modules["pythoncom"] = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=_co_uninit)
client = types.SimpleNamespace(GetObject=lambda moniker: _Services())
sys.modules["win32com"] = types.SimpleNamespace(client=client)
sys.modules["win32com.client"] = client


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


logs = _Logs()
procs.log.addHandler(logs)
procs.log.setLevel(logging.DEBUG)
slept = []
procs._sleep = slept.append

print("[16:05 之后那台机器：每一行都是早绑定对象，只能从 Properties_ 读]")
rows = procs.python_processes()
check("读得到两行", rows, [(5088, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                         (2076, r"C:\Program Files\Python314\python.exe x.py")])
check("反初始化时没有活着的 COM 对象", _leaked, [])
check("没报警", [r for r in logs.records if r.levelno >= logging.WARNING], [])

print("\n[一次失败后读到：等一下再试，不报警]")
plan[:] = ["cancel", "ok"]
logs.records.clear()
rows = procs.python_processes()
check("第二次读到", rows is not None and len(rows), 2)
check("中间等了一次", slept, [procs.PAUSE_SECONDS])
check("失败那次带错误码", any("0x80041032" in r.getMessage() for r in logs.records))
check("没报警", [r for r in logs.records if r.levelno >= logging.WARNING], [])
check("失败那次也没有对象活过反初始化", _leaked, [])

print("\n[每次都失败：只报一条警告，带错误码；同一段没恢复不再报]")
plan[:] = ["cancel"] * 6
logs.records.clear()
slept.clear()
check("读不到返回 None", procs.python_processes(), None)
check("试了 3 次、中间等 2 次", slept, [procs.PAUSE_SECONDS] * 2)
warns = [r.getMessage() for r in logs.records if r.levelno >= logging.WARNING]
check("一条警告", len(warns), 1)
check("警告带错误码", bool(warns) and "0x80041032" in warns[0])
check("说得出为什么", "0x80041032" in procs.last_failure())
check("第二轮仍读不到也不再报", (procs.python_processes(), len([r for r in logs.records if r.levelno >= logging.WARNING])), (None, 1))
check("异常没有让对象活过反初始化", _leaked, [])

print("\n[自检调用时不另报：自检自己报那一条]")
procs._state["warned"] = False
plan[:] = ["cancel"] * 3
logs.records.clear()
check("warn=False 读不到也返回 None", procs.python_processes(warn=False), None)
check("不报警", [r for r in logs.records if r.levelno >= logging.WARNING], [])
plan[:] = ["cancel"] * 3
check("自检报过的那段，看门狗再读不到也不重复报",
      (procs.python_processes(), [r for r in logs.records if r.levelno >= logging.WARNING]), (None, []))

print("\n[没有 pywin32 的机器：一次就停，不等]")
del sys.modules["pythoncom"]
sys.modules["pythoncom"] = None
slept.clear()
check("返回 None", procs.python_processes(warn=False), None)
check("没等", slept, [])

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
