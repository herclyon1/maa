"""An overlay that is not in place reaches the group, whatever its words.

Audit 2026-10-13 (A1): when the overrides could not be installed, or the master
pointer could not be written, the lines said 没装上 / 装不上 / 写不了 / 找不到 -
none of them in texts._PATCH_TROUBLE - so the push title was the healthy
「🩹 OK-WW 补丁」, which notify.route_of keeps in the log. OK-WW ran as plain
upstream while every report stayed green.

install() and write_master_pointer() now raise OverlayTrouble on each failure path,
and boot_stages._stage_patch_okww counts those as failures by construction. Each
path is driven through the boot stage here and must end with the ⚠️ title routed
to the group; the healthy install stays 🩹 / log.
"""
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
from ark_relay.core import texts  # noqa: E402
from ark_relay.core.notify import route_of  # noqa: E402
from ark_relay.features.okww_patch import okww_overlay as ov  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


REAL = {k: getattr(ov, k) for k in ("atomic_write_text", "master_config_dir", "MASTER_POINTER", "REPORT")}
MASTER = TMP / "master"
MASTER.mkdir()


def boot(okww_dir, *, write=None, master="ok"):
    """Run the boot stage once with a fresh pointer and no report; ([(title, alert)], [body])."""
    ov.MASTER_POINTER = tmpdir() / "pointer.txt"
    ov.REPORT = tmpdir() / "report.json"           # absent: report_line says nothing
    ov.master_config_dir = lambda automas_dir, marker: MASTER if master == "ok" else None
    ov.atomic_write_text = write or REAL["atomic_write_text"]
    cfg = types.SimpleNamespace(okww_dir=okww_dir, automas_dir=None, state_dir=tmpdir())
    notes = Notes()
    try:
        boot_stages._stage_patch_okww(cfg, notes, boot_stages.log)
    finally:
        for k, v in REAL.items():
            setattr(ov, k, v)
    return [(t, a) for t, _, a in notes.sent], [b for _, b, _ in notes.sent]


def is_alarm(label, sent):
    check(f"{label}: one push", len(sent), 1)
    title, alert = sent[0] if sent else ("", False)
    check(f"{label}: ⚠️ title", title.startswith("⚠️"), True)
    check(f"{label}: routed to the group", route_of(title, alert=alert), "group")


def raising(name):
    """atomic_write_text that raises OSError for the file called `name`."""
    def w(path, text, newline=None):
        if Path(path).name == name:
            raise OSError(13, "Access is denied")
        return REAL["atomic_write_text"](path, text, newline)
    return w


def garbling(name):
    """atomic_write_text that writes something else into the file called `name`."""
    def w(path, text, newline=None):
        return REAL["atomic_write_text"](path, text + "x" if Path(path).name == name else text, newline)
    return w


print("[healthy: installed once -> 🩹, log only]")
sent, bodies = boot(tmpdir())
check("one push", len(sent), 1)
check("🩹 title", sent[0][0].startswith("🩹") if sent else False, True)
check("log only", route_of(sent[0][0], alert=sent[0][1]) if sent else "", "log")
check("says where it went", "ok_tasks" in (bodies[0] if bodies else ""), True)

print("\n[every failure path: ⚠️, group]")
sent, _ = boot(None)
is_alarm("no OK-WW directory", sent)
sent, _ = boot(tmpdir(), write=garbling(ov.FILE_NAME))
is_alarm("overrides read back different", sent)
sent, _ = boot(tmpdir(), write=raising(ov.FILE_NAME))
is_alarm("overrides cannot be written", sent)
sent, _ = boot(tmpdir(), master=None)
is_alarm("no master directory", sent)
sent, _ = boot(tmpdir(), write=raising("pointer.txt"))
is_alarm("pointer cannot be written", sent)
sent, _ = boot(tmpdir(), write=garbling("pointer.txt"))
is_alarm("pointer reads back different", sent)

print("\n[the raise itself, not the words, makes it a failure]")
try:
    ov.install(None)
    check("install(None) raises", False, True)
except ov.OverlayTrouble as exc:
    check("install(None) raises OverlayTrouble with a plain line", "OK-WW" in str(exc), True)
check("a fault counts even when no trouble word matches",
      texts.patches(1, ["随便什么话"], ["随便什么话"]).startswith("⚠️"), True)
check("a fault that also has a trouble word is counted once",
      "1 条没贴上" in texts.patches(1, ["OK-WW 有改动没贴上"], ["OK-WW 有改动没贴上"]), True)
check("the old two-argument call is unchanged", texts.patches(2, ["a", "b"]), "🩹 OK-WW 补丁（2 条）")

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
