"""The one button that is only ever pressed while a run is going must not be gated.

Everything the phone can change goes through one gate: 「a script is running, so
writing config now would be clobbered by AUTO-MAS's in-memory copy」. That is
correct for the settings AUTO-MAS owns, and wrong for the two switches that live
in the relay's own StateStore - 「下次跑完不关机」 above all, which is pressed
*because* a run is going. It was refused every time it mattered, and the message
said to press it again after the run, by which time the machine has powered off.

Also pinned here: the refusal names the button in Chinese. It used to interpolate
the raw action id, so the push read 「set_config」現在不能执行 - an identifier is
not an answer.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
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

import ark_relay.commands as C        # noqa: E402
import boot_stages                    # noqa: E402
from ark_relay import texts          # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class Eng:
    def __init__(self, busy):
        self.busy = busy

    def scripts_running(self):
        return self.busy


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return False


class Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): pass


class HB:
    def watch(self): pass


def run(action, busy, applied):
    notes = Notes()
    real = C.apply_command
    # _make_phone_cmd binds apply_command into its closure, so the module
    # attribute has to be swapped before the closure is built.
    C.apply_command = lambda body: (applied.append(body["action"]), (True, "改好了"))[1]
    try:
        fn = boot_stages._make_phone_cmd(Eng(busy), notes, Log(), HB(), lambda *_: None)
        fn({"action": action, "confirmed": True})
    finally:
        C.apply_command = real
    return notes


print("[跑着的时候：改 AUTO-MAS 的设置照旧挡下来]")
applied = []
n = run("set_config", busy=True, applied=applied)
check("没有真去改", applied, [])
check("推了一条「等跑完」", n.sent and n.sent[0][0], texts.PHONE_DEFERRED)
check("话里说的是中文按钮名", "改设置" in n.sent[0][1], True)
check("话里没有指令 id", "set_config" in n.sent[0][1], False)

print("\n[跑着的时候：「下次跑完不关机」必须放行——它只有这时候按才有意义]")
applied = []
n = run("skip_shutdown", busy=True, applied=applied)
check("真的执行了", applied, ["skip_shutdown"])
check("没有推「等跑完」", [t for t, _ in n.sent if t == texts.PHONE_DEFERRED], [])

print("\n[调试模式同理：它写的也是中继自己的状态]")
applied = []
run("debug_mode", busy=True, applied=applied)
check("真的执行了", applied, ["debug_mode"])

print("\n[没在跑的时候，什么都照常]")
applied = []
run("set_config", busy=False, applied=applied)
check("改设置执行了", applied, ["set_config"])

print("\n[每一个能按的按钮都有中文名字]")
missing = [a for a in ("set_stage", "set_medicine", "set_wait_time", "toggle_task",
                       "run_now", "skip_today", "debug_mode", "set_config",
                       "set_master", "weekly_boss", "skip_shutdown")
           if texts.action_name(a) == "这条设置"]
check("没有漏掉的", missing, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
