"""boot_stages._start_phone_channel: the one state WARNING says why, a missed boot read is read again.

Two lines of the 10-06 sweep came from here:
* #42 #47 #48 「状态没能上报到手机（开机；今天 ntfy 已发 0 条）」 - no reason, and a
  count that disagreed with ntfy's own 42908. Now the line is written only
  when the phone cannot see the state at all (phone.Mailbox.publish) and
  carries Mailbox.last_error;
* #41 a boot mailbox read that timed out lost the presses made while the
  machine was off. The listener now reads it again (on_backlog), through the
  same boot_backlog filter and the same single folded state push as at boot.
Every WARNING is pushed to the group now (2026-10-06). Fakes for the mailbox,
the heartbeat and win32; no network, no thread left running.
"""
import logging
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir


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
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
             "win32com", "win32com.client"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages  # noqa: E402
from ark_relay import phone  # noqa: E402

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


class Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs: list[tuple[int, str]] = []

    def emit(self, record):
        self.recs.append((record.levelno, record.getMessage()))


WHY = "腾讯云 COS 没存上（回 403），ntfy 也没发出去（ntfy 回 502（试了 2 次））"
boxes: list = []


class FakeBox:
    def __init__(self, topic, pin, state_dir, cos=None):
        self.topic, self.cos, self.enabled = topic, cos, True
        self.quota = phone.Quota(state_dir)
        self.last_error = WHY
        self.listened: dict = {}
        boxes.append(self)

    def publish(self, body):
        return False

    def fetch(self):
        return []

    def listen(self, on_cmd, stop, **kw):
        self.listened = {"on_cmd": on_cmd, **kw}


class FakeHb:
    def __init__(self, *a, **k):
        pass

    def loop(self, stop):
        return None

    def watch(self):
        pass


saved = (phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas)
phone.Mailbox, phone.Heartbeat = FakeBox, FakeHb
phone.state_payload = lambda cfg, state_dir: {"at": 1}
boot_stages.ensure_automas = lambda *a, **k: True
logs = Logs()
log = logging.getLogger("ark.test_phone_channel_boot")
log.addHandler(logs)
log.setLevel(logging.DEBUG)
log.propagate = False
try:
    sd = tmpdir()
    cfg = types.SimpleNamespace(phone_topic="topic-abc", phone_pin="8964", state_dir=sd,
                                cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
    svc = types.SimpleNamespace(stop_event=None)
    engine = types.SimpleNamespace(scripts_running=lambda: False)
    notifier = types.SimpleNamespace(send=lambda *a, **k: True)
    push_state = boot_stages._start_phone_channel(svc, cfg, engine, notifier, log)
    for _ in range(100):           # the listener thread records its call at once
        if boxes and boxes[0].listened:
            break
        time.sleep(0.01)
    box = boxes[0]

    print("[开机那份状态没送到：一条 WARNING，带原因]")
    warns = [m for lv, m in logs.recs if lv >= logging.WARNING]
    check("一条", len(warns), 1)
    check("……写了是哪一份、为什么", ("（开机）" in (warns or [""])[0], WHY in (warns or [""])[0]), (True, True))

    print("\n[开机读信箱没成：手机通道连上后补读，走开机积压那条路]")
    on_backlog = box.listened.get("on_backlog")
    check("监听线程拿到了 on_backlog", callable(on_backlog), True)
    logs.recs.clear()
    if callable(on_backlog):
        on_backlog([{"action": "estop", "_meta": {"via": "backlog"}}])
    check("补读到的红按钮同样不执行（boot_backlog 的规矩）",
          any("开机不执行" in m for _, m in logs.recs), True)
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ {type(exc).__name__}: {exc}")
    fails.append(type(exc).__name__)
finally:
    phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas = saved

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
