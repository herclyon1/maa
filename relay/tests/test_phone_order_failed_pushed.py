"""A phone order that did not take is an error, so it goes to the group (2026-10-06).

The user, 2026-10-06: 「只要是报错，就说这个中继程序它出现问题了，立马就向群内机器人报告错误。
不论多少次什么错误都要发」. Until then boot_stages._phone_execute sent 「📱 配置没改成」 without
alert=True, so it went to Server酱 only.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import types  # noqa: E402


class _Any:
    """Stands in for any pywin32 attribute (boot_stages pulls in service helpers)."""
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

import os  # noqa: E402
from _tmp import tmpdir  # noqa: E402
os.environ["ARK_STATE_DIR"] = str(tmpdir())
import boot_stages  # noqa: E402
from ark_relay import texts  # noqa: E402
from ark_relay.notify import route_of  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body, alert=False, **kw):
        self.sent.append((title, body, alert))
        return []


def run(ok):
    n = FakeNotifier()
    boot_stages._phone_execute(lambda body: (ok, "刷取关卡：找不到 TO-9" if not ok else "刷取关卡：TO-5"),
                               n, logging.getLogger("ark.test"), lambda *a, **k: None, lambda *a, **k: None,
                               {"action": "set_stage"}, "set_stage", None, True)
    return n.sent


print("[手机指令没改成：进群]")
bad = run(False)
check("推了一条「配置没改成」", [t for t, _, _ in bad], [texts.CONFIG_FAILED])
check("带 alert=True", [a for _, _, a in bad], [True])
check("走群", route_of(texts.CONFIG_FAILED, alert=bad[0][2]) if bad else None, "group")
print("[改成了：只是回执，不进群]")
good = run(True)
check("推的是「配置已修改」", [t for t, _, _ in good], [texts.CONFIG_CHANGED])
check("不带 alert", [a for _, _, a in good], [False])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
