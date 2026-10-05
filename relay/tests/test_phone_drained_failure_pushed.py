"""A phone order that waited for the run and then failed goes to the group too.

Found while writing the machine check #23 (machinechecks/phone_banners.py): an
order pressed during a run waits in phone.CmdQueue and is applied by drain()
with notify=False, and boot_stages._phone_execute pushed nothing at all then -
a failure after the run was only a red receipt on the phone page. The user's
rule of 2026-10-06 is every error to the group, every time (「不论多少次什么错误都要发」;
docs/NOTIFICATIONS.md, the 「📱 配置没改成」 row: his phone order failed - the
group). A drained order that went through still pushes nothing: the receipt is
the answer.
"""
import os
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


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

from _tmp import tmpdir  # noqa: E402

os.environ.update(ARK_STATE_DIR=str(tmpdir()), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

import ark_relay.commands as C  # noqa: E402
import boot_stages  # noqa: E402
from ark_relay import modes, phone, texts  # noqa: E402
from ark_relay.notify import route_of  # noqa: E402

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
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

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        return []


class Log:
    def _rec(self, *a, **k):
        pass

    info = warning = debug = exception = _rec


class HB:
    def watch(self):
        pass


def order(action, mid, **kw):
    body = {"action": action, "confirmed": True, **kw}
    body["_meta"] = {"sent": int(time.time()), "ntfy_time": int(time.time()), "ntfy_id": mid, "via": "live"}
    return body


real = C.apply_command
C.apply_command = lambda body: ((False, "刷取关卡：找不到 TO-9") if body.get("value") == "TO-9"
                                else (True, f"刷取关卡：{body.get('value')}"))
try:
    d = tmpdir()
    eng, notes = Eng(True), Notes()
    fn = boot_stages._make_phone_cmd(eng, notes, Log(), HB(), phone.StatePusher(lambda why: True), d)
    fn(order("set_config", "m1", value="TO-9"))
    fn(order("set_config", "m2", value="1-7"))
    print("[跑着的时候：排队，什么都不推]")
    check("没推", notes.sent, [])
    eng.busy = False
    fn.drain()
    print("\n[跑完执行：没改成的那条进群，改成的那条不推]")
    check("推了一条「配置没改成」", [t for t, _b, _a in notes.sent], [texts.CONFIG_FAILED])
    check("带 alert=True，走群", [(a, route_of(t, alert=a)) for t, _b, a in notes.sent], [(True, "group")])
    check("正文是那条指令自己的回答", [b for _t, b, _a in notes.sent], ["刷取关卡：找不到 TO-9"])
    check("两张最终回执照旧", [(r["action"], r["ok"]) for r in modes.receipts(d) if not r.get("queued")],
          [("set_config", False), ("set_config", True)])
finally:
    C.apply_command = real

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
