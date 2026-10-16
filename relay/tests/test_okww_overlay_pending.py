"""An overlay install skipped because OK-WW was running is tried again before the
relay next starts a run itself, and is said to the group if it still cannot be done.

Review 2026-10-13 item 20: install() skips while OK-WW runs (a relay restart
mid-run, e.g. a deploy). Until then the old overlay stayed until the next relay
start - normally the next boot - with one 🩹 log line. Now okww_overlay.retry_pending
runs after the pre-update closed OK-WW and right before phone.commands dispatches a
script or a queue; still running there -> a WARNING (errwatch pushes every WARNING
to the group).
"""
import logging
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
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


for _name in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
              "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi",
              "pythoncom", "win32com", "win32com.client"):
    sys.modules.setdefault(_name, _Stub(_name))

import boot_stages  # noqa: E402
from ark_relay.features.okww_patch import okww_overlay as ov  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402
from ark_relay.features.preupdate import preupdate  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402

# The stubbed win32api would make GetSystemMetrics read as "Windows is going down", and the
# boot pre-update stops at once for a stopping relay (boot_stages._stage_preupdate, 10-16).
errwatch.system_shutting_down = lambda: False

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Warnings(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


W = Warnings()
ov.log.addHandler(W)
REAL_RUNNING = ov.okww_running
running = {"now": True}
ov.okww_running = lambda: running["now"]
WANT = ov.source_text().encode("utf-8")

try:
    print("[skipped at boot while OK-WW runs: pending]")
    root = tmpdir()
    dest = ov.target(root)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"# old overlay\n")
    ov.install(root)
    check("file left alone", dest.read_bytes(), b"# old overlay\n")
    check("pending", ov._pending.get("dir"), root)

    print("\n[tried again while OK-WW still runs: a WARNING (to the group), file left alone]")
    W.lines.clear()
    line = ov.retry_pending("单独开跑「OK-WW」前")
    check("one warning", len(W.lines), 1)
    check("says where and that the old overlay runs", "单独开跑「OK-WW」前" in line and "旧" in line, True)
    check("file still the old one", dest.read_bytes(), b"# old overlay\n")

    print("\n[tried again once OK-WW stopped: installed, no warning, nothing pending]")
    running["now"] = False
    W.lines.clear()
    ov.retry_pending("预更新后")
    check("installed", dest.read_bytes(), WANT)
    check("no warning", W.lines, [])
    check("nothing pending", ov._pending, {})
    check("nothing pending: no-op", ov.retry_pending("x"), "")

    print("\n[the relay's own dispatch tries it before starting]")
    order = []
    real = (ov.retry_pending, commands._mas, commands._note_dispatch)
    ov.retry_pending = lambda where: order.append(("retry", where)) or ""
    commands._note_dispatch = lambda what: None

    def mas(path, body=None):
        if path == "/api/scripts/get":
            return {"data": {"s1": {"Info": {"Name": "OK-WW"}}}}
        if path == "/api/queue/get":
            return {"data": {"q1": {"Info": {"Name": "早班"}}}}
        order.append(("dispatch", body["taskId"]))
        return {"status": "success"}
    commands._mas = mas
    try:
        commands.run_script("OK-WW")
        check("script: retry before dispatch", [k for k, _ in order], ["retry", "dispatch"])
        order.clear()
        commands._run_now("早班")
        check("queue: retry before dispatch", [k for k, _ in order], ["retry", "dispatch"])
        print("\n[the pre-update tries it after closing OK-WW]")
        order.clear()
        real_pre = (preupdate.run_okww, ov.drift_line)
        preupdate.run_okww = lambda okww, problems=None, **_k: order.append(("preupdate", "")) or ""
        ov.drift_line = lambda okww, state_dir: ""
        try:
            notes = types.SimpleNamespace(send=lambda *a, **k: [])
            cfg = types.SimpleNamespace(okww_dir=root, automas_dir=None, state_dir=tmpdir())
            boot_stages._preupdate_okww(cfg, notes, boot_stages.log, [])
        finally:
            preupdate.run_okww, ov.drift_line = real_pre
        check("pre-update, then retry", [k for k, _ in order], ["preupdate", "retry"])
    finally:
        ov.retry_pending, commands._mas, commands._note_dispatch = real
finally:
    ov.okww_running = REAL_RUNNING
    ov._pending.clear()

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
