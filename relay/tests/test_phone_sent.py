"""A phone order keeps the time it was sent: in relay.log and on its receipt.

2026-09-30: three skip orders were found in the mailbox at 08:46 and nobody could
say when they had been sent - relay.log and the receipts held only the moment the
relay acted, and ntfy drops a message after 12 hours. The user asked 「谁干的？」
and there was no answer. Pinned here: the log line names the envelope's ts, ntfy's
time and id; the receipt stores "sent" and keeps its text plain (the page shows
「HH:MM 发出 · HH:MM 执行」 from sent / at); no command body ever sees "_meta".
"""
import json
import logging
import sys
import types
from datetime import datetime
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


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

from _tmp import tmpdir                # noqa: E402
import ark_relay.commands as C         # noqa: E402
import boot_stages                     # noqa: E402
from ark_relay import modes, phone     # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


grab = Grab()
phone.log.addHandler(grab)
phone.log.setLevel(logging.INFO)

T = int(datetime(2026, 9, 30, 8, 46, 23, tzinfo=SERVER_TZ).timestamp())
ENV = {"id": "rkCjnh9nJkyU", "time": T + 2, "event": "message"}

print("[收到指令：relay.log 记发出时刻、ntfy 收到时刻和 id]")
body = phone.stamp({"ts": T, "body": {"action": "skip_today", "queue": "晚班"}}, ENV, "live")
line = grab.lines[-1] if grab.lines else ""
check("记了一行", line.startswith("📱 收到手机指令 skip_today："), True)
check("行里有信封 ts 的北京时刻", "09-30 08:46:23 发出" in line, True)
check("行里有 ntfy 收到时刻", "ntfy 09-30 08:46:25 收到" in line, True)
check("行里有 ntfy id", "rkCjnh9nJkyU" in line, True)
check("说明是在线收到", line.endswith("在线收到"), True)
check("_meta 带上 sent / id / via", (body["_meta"]["sent"], body["_meta"]["ntfy_id"], body["_meta"]["via"]),
      (T, "rkCjnh9nJkyU", "live"))
check("原指令键不动", {k: v for k, v in body.items() if k != "_meta"}, {"action": "skip_today", "queue": "晚班"})

print("\n[页面自己的刷新 / 看着 不记行（每次开页面都发，会淹掉指令）]")
n = len(grab.lines)
phone.stamp({"ts": T, "body": {"action": "refresh"}}, ENV, "live")
phone.stamp({"ts": T, "body": {"action": "watch"}}, ENV, "live")
check("没多出行", len(grab.lines), n)


class Eng:
    def scripts_running(self):
        return False


class Notes:
    def send(self, *a, **k):
        return False


class Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): pass


class HB:
    def watch(self): pass


def run(stamped):
    d = tmpdir()
    got = []
    real = C.apply_command
    C.apply_command = lambda b: (got.append(dict(b)), (True, "今天（2026-09-30）将跳过队列「晚班」"))[1]
    try:
        boot_stages._make_phone_cmd(Eng(), Notes(), Log(), HB(), lambda *_: None, d)(stamped)
    finally:
        C.apply_command = real
    return got, modes.receipts(d)


print("\n[在线指令：回执多存 sent，文字不变，指令体里没有 _meta]")
got, rec = run(phone.stamp({"ts": T, "body": {"action": "skip_today", "queue": "晚班"}}, ENV, "live"))
check("apply_command 收到的就是原指令", got, [{"action": "skip_today", "queue": "晚班"}])
check("回执 sent = 发出的 月-日 时:分", rec[-1].get("sent"), "09-30 08:46")
check("回执文字照原样", rec[-1]["text"], "今天（2026-09-30）将跳过队列「晚班」")

print("\n[开机读积压：回执存 sent，文字不加前缀（页面按 sent / at 自己显示两个时刻）]")
got, rec = run(phone.stamp({"ts": T, "body": {"action": "skip_today", "queue": "晚班"}}, ENV, "backlog"))
check("apply_command 收到的就是原指令", got, [{"action": "skip_today", "queue": "晚班"}])
check("回执文字照原样，不加「发出 / 执行」前缀", rec[-1]["text"], "今天（2026-09-30）将跳过队列「晚班」")
check("sent 照样存", rec[-1].get("sent"), "09-30 08:46")
check("积压那一行说是开机读的", grab.lines[-1].endswith("开机读信箱积压"), True)

print("\n[没有 _meta 的老调用：照旧，不带 sent]")
got, rec = run({"action": "skip_today", "queue": "晚班"})
check("照旧执行", got, [{"action": "skip_today", "queue": "晚班"}])
check("没有 sent 键", "sent" in rec[-1], False)

print("\n[add_receipt 直接调用：sent 可选]")
d = tmpdir()
modes.add_receipt(d, "debug_mode", True, "开了", sent=T)
modes.add_receipt(d, "debug_mode", True, "开了")
r = modes.receipts(d)
check("给了就存", r[0].get("sent"), "09-30 08:46")
check("没给就没有", "sent" in r[1], False)

print("\n[太老丢弃时也记发出时刻]")
old = json.dumps({"v": 1, "kind": "cmd", "pin": "p", "ts": T, "body": {"action": "x"}})
check("丢掉", phone.unpack("p", old, now=T + 30 * 3600), None)
check("那一行有发出时刻", "09-30 08:46:23 发出" in grab.lines[-1], True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
