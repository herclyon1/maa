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

print("\n[开机读信箱积压：关机期间按的红按钮不执行，其余照常]")
# 2026-09-19 17:5x the red button was pressed on the phone page while the machine
# had been off since 14:47; the 21:20 boot would have read it back and fired it
# against nothing, minutes before the 21:30 queue.
_recorded = []
class _Log:
    def warning(self, fmt, *a): _recorded.append(fmt % a)
    def info(self, fmt, *a): pass
backlog = [{"action": "estop"}, {"action": "skip_shutdown", "on": True}, {"action": "estop"}, {"action": "refresh"}]
kept = boot_stages.boot_backlog(backlog, _Log())
check("红按钮全部丢掉，别的按原顺序留下", [b["action"] for b in kept], ["skip_shutdown", "refresh"])
check("每丢一条记一行", len(_recorded), 2)
check("说清是关机期间按的、开机不执行", "关机期间" in _recorded[0] and "开机不执行" in _recorded[0], True)
check("空积压照样是空的", boot_stages.boot_backlog([], _Log()), [])
check("红按钮是唯一的 live-only 动作（活着时照旧立刻执行）", boot_stages.LIVE_ONLY_ACTIONS, ("estop",))

print("\n[刷新：一份状态已经答过就不再发（ntfy 每天 250 条，一份状态 4 条）]")
# 2026-10-02 19:19 the quota ran out: the App re-asks 4 s after every refresh and
# each ask bought a whole state (17:02:23 / 17:02:31, 18:30:05 / 18:30:12); the
# refreshes pressed while the machine was off replayed one by one at boot
# (09-30 08:46:03-08:47:44, eleven states).
import time as _time  # noqa: E402
from ark_relay import phone as _phone  # noqa: E402
_pushed = []
_pusher = _phone.StatePusher(lambda why: _pushed.append(why) or True)
_real_ensure = boot_stages.ensure_automas
_ensured = []
boot_stages.ensure_automas = lambda *a, **k: _ensured.append(1) or True
try:
    _fn = boot_stages._make_phone_cmd(Eng(False), Notes(), Log(), HB(), _pusher)
    _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time())}})
    check("第一次刷新照常答一份", _pushed, ["手机请求"])
    _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time()) + 4}})
    check("4 秒后补问的那次：刚发的那份答了，不再发", _pushed, ["手机请求"])
    check("没再发也就不用去拉 AUTO-MAS", len(_ensured), 1)
    _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time()) - 5 * 3600}})
    check("关机时按的（开机才读到）：开机那份已经答了", _pushed, ["手机请求"])
    _pusher._done -= _phone.REFRESH_ANSWERED_SEC + 5
    _fn({"action": "refresh", "_meta": {"ntfy_time": int(_time.time())}})
    check("隔久了再按：照常答", _pushed, ["手机请求", "手机请求"])
    # A plain push_state (a lambda, no `answered`) still answers every time
    _plain = []
    boot_stages._make_phone_cmd(Eng(False), Notes(), Log(), HB(),
                                lambda why: _plain.append(why))({"action": "refresh"})
    check("普通的 push_state 照旧能用", _plain, ["手机请求"])

    print("\n[开机积压：几条改配置合成一份状态]")
    _pushed.clear()
    real = C.apply_command
    C.apply_command = lambda body: (True, "改好了")
    try:
        _fn = boot_stages._make_phone_cmd(Eng(False), Notes(), Log(), HB(), _pusher)
        with _pusher.held():
            for _b in ({"action": "set_config"}, {"action": "skip_shutdown", "on": True},
                       {"action": "refresh", "_meta": {"ntfy_time": 0}}):
                _fn(_b)
    finally:
        C.apply_command = real
    check("两条改配置 + 一条旧刷新 = 一份状态", _pushed, ["改完配置（2 次合成一次）"])
finally:
    boot_stages.ensure_automas = _real_ensure

print("\n[每一个能按的按钮都有中文名字]")
missing = [a for a in ("set_stage", "set_medicine", "set_wait_time", "toggle_task",
                       "run_now", "skip_today", "debug_mode", "set_config",
                       "set_master", "weekly_boss", "skip_shutdown")
           if texts.action_name(a) == "这条设置"]
check("没有漏掉的", missing, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
