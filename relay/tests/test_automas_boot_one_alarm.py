"""One AUTO-MAS start failure at boot is one group message (audit s23 F2, 10-13).

Before: ensure_automas logged 「AUTO-MAS 拉起后 120 秒内接口仍不通」 as a plain ERROR
(errwatch pushes it: 🩺), then the boot caller phone_channel._start_phone_channel sent
「🔌 AUTO-MAS 启动不起来」 for the same fault; on the morning boot _stage_preupdate
called ensure_automas() again - another 150 s wait, kill, 120 s wait and the same
ERROR (a second 🩺) - before its own 「预更新没能确认」. Last real cases: 09-04 22:49:26
and 09-17 21:21:28.

Now the boot caller hands ensure_automas the notifier: 🔌 goes out and the ERROR line
is marked as already in the group (errwatch.group_pushed). The pre-update asks
mas_up() and, when AUTO-MAS is still not answering, skips its AUTO-MAS item with one
problem line instead of waiting again; OK-WW's item does not need AUTO-MAS and runs.
"""
import logging
import sys
import time
import types
from datetime import datetime, timezone
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
from ark_relay.core import texts  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.okww_patch import okww_overlay  # noqa: E402
from ark_relay.features.phone import commands, phone, phone_channel  # noqa: E402
from ark_relay.features.preupdate import preupdate  # noqa: E402

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Records(logging.Handler):
    """Every record under the "ark" logger, as errwatch sees them."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.recs: list[logging.LogRecord] = []

    def emit(self, record):
        self.recs.append(record)

    def pushed_by_errwatch(self) -> list[str]:
        """WARNING / ERROR lines errwatch would push: not marked as already in the group."""
        return [r.getMessage() for r in self.recs if r.levelno >= logging.WARNING
                and not getattr(r, errwatch.PUSHED, False) and not getattr(r, errwatch.RECOVERED, False)]


class Notes:
    def __init__(self):
        self.sent: list[tuple[str, bool]] = []

    def send(self, title, body="", **kw):
        self.sent.append((title, bool(kw.get("alert"))))
        return []

    def went_to_group(self):
        return True

    def alarms(self) -> list[str]:
        return [t for t, alert in self.sent if alert]


REC = Records()
ARK = logging.getLogger(errwatch.ARK)
ARK.addHandler(REC)
ARK.setLevel(logging.DEBUG)

# AUTO-MAS never answers; a fake clock so the 120 s wait costs nothing.
clock = {"t": 0.0}
real_sleep, real_monotonic = boot_stages.time.sleep, boot_stages.time.monotonic
saved = (commands.mas_up, boot_stages.shell_running, boot_stages._revive_automas,
         boot_stages._stop_requested, phone.Mailbox, phone.Heartbeat, phone.state_payload,
         phone_channel._make_phone_cmd)


def advance(s):
    clock["t"] += s


class FakeBox:
    def __init__(self, topic, pin, state_dir, cos=None):
        self.topic, self.cos, self.enabled = topic, cos, True
        self.quota = phone.Quota(state_dir)
        self.last_error = ""

    def publish(self, body):
        return True

    def fetch(self):
        return []

    def listen(self, on_cmd, stop, **kw):
        pass


class FakeHb:
    def __init__(self, *a, **k): pass
    def loop(self, stop): return None
    def watch(self): pass


def fake_make_phone_cmd(*a, **k):
    def run(body):
        pass
    run.drain = lambda: None
    return run


try:
    boot_stages.time.sleep = advance
    boot_stages.time.monotonic = lambda: clock["t"]
    commands.mas_up = lambda: False
    boot_stages.shell_running = lambda: False
    boot_stages._revive_automas = lambda: None
    boot_stages._stop_requested = lambda: False
    phone.Mailbox, phone.Heartbeat = FakeBox, FakeHb
    phone.state_payload = lambda cfg, state_dir: {"at": 1}
    phone_channel._make_phone_cmd = fake_make_phone_cmd

    print("[boot: AUTO-MAS does not come up after the revival]")
    sd = tmpdir()
    cfg = types.SimpleNamespace(phone_topic="topic-abc", phone_pin="8964", state_dir=sd,
                                cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
    engine = types.SimpleNamespace(scripts_running=lambda: False, _started_at=datetime.now(timezone.utc))
    notes = Notes()
    log = logging.getLogger("ark.test_automas_boot_one_alarm")
    phone_channel._start_phone_channel(types.SimpleNamespace(stop_event=None), cfg, engine, notes, log)
    time.sleep(0.05)               # the listener thread
    # Only the AUTO-MAS ones: the fake state payload fails a machine check of its own.
    down = [t for t in notes.alarms() if "AUTO-MAS" in t]
    loud = [m for m in REC.pushed_by_errwatch() if "AUTO-MAS" in m]
    check("the 🔌 alarm went out once", down, [texts.AUTOMAS_DOWN])
    check("errwatch has nothing more to push for it", loud, [])
    check("so the group gets one message", len(down) + len(loud), 1)
    check("the ERROR line is still in relay.log (selfcheck reads 「秒内…仍不通」)",
          any("秒内接口仍不通" in r.getMessage() for r in REC.recs), True)

    print("[the morning pre-update right after: no second wait, one problem line]")
    REC.recs.clear()
    ensured: list[int] = []
    real_ensure = boot_stages.ensure_automas
    boot_stages.ensure_automas = lambda *a, **k: ensured.append(1) or real_ensure(*a, **k)
    asked = {"automas": 0, "okww": 0}

    def run_automas(*a, problems=None, **k):
        asked["automas"] += 1
        problems.append("AUTO-MAS 预更新：接口不通，没查到版本")
        return ""

    def run_okww(*a, problems=None, **k):
        asked["okww"] += 1
        return ""

    saved_pre = (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run,
                 preupdate.run_automas, preupdate.run_okww, okww_overlay.retry_pending,
                 okww_overlay.drift_line, boot_stages._seconds_to_next_queue)
    preupdate.wanted_today = lambda *a, **k: True
    preupdate.should_run = lambda *a, **k: True
    marks: list[bool] = []
    preupdate.mark_run = lambda state_dir, now, clean: marks.append(clean)
    preupdate.run_automas, preupdate.run_okww = run_automas, run_okww
    okww_overlay.retry_pending = lambda *a, **k: None
    okww_overlay.drift_line = lambda *a, **k: ""
    boot_stages._seconds_to_next_queue = lambda automas_dir, now: 3600.0
    t0 = clock["t"]
    notes = Notes()
    pcfg = types.SimpleNamespace(automas_dir=None, okww_dir=Path("okww"), state_dir=None)
    try:
        boot_stages._stage_preupdate(pcfg, notes, log)
    finally:
        (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run,
         preupdate.run_automas, preupdate.run_okww, okww_overlay.retry_pending,
         okww_overlay.drift_line, boot_stages._seconds_to_next_queue) = saved_pre
        boot_stages.ensure_automas = real_ensure
    check("no second ensure_automas", ensured, [])
    check("no second 150 + 120 s wait", clock["t"] - t0, 0.0)
    check("the AUTO-MAS item is skipped, OK-WW still runs", asked, {"automas": 0, "okww": 1})
    check("no second 「仍不通」 ERROR", any("仍不通" in r.getMessage() for r in REC.recs), False)
    unconfirmed = [t for t in notes.alarms() if t.startswith(texts.unconfirmed("预更新", 1)[:6])]
    check("one 「没能确认」 alarm with one line", unconfirmed, [texts.unconfirmed("预更新", 1)])
    check("the day's pre-update is not clean (tried again next boot)", marks, [False])
finally:
    boot_stages.time.sleep, boot_stages.time.monotonic = real_sleep, real_monotonic
    (commands.mas_up, boot_stages.shell_running, boot_stages._revive_automas,
     boot_stages._stop_requested, phone.Mailbox, phone.Heartbeat, phone.state_payload,
     phone_channel._make_phone_cmd) = saved
    ARK.removeHandler(REC)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
