"""Every way of setting MAA's stage refuses a stage MAA cannot navigate to, and says so.

What the user asked for is USER_SAID below (2026-10-10 16:58, Osaka), verbatim.

All of them end in commands.apply_command: the phone page and the App (live, or
queued while a script runs and drained afterwards, or read from the mailbox backlog
at boot), scripts/mac/order-now.sh (the same ntfy channel) - all through
boot_stages._phone_execute, whose receipt is what the phone shows - and
scripts/mac/order.sh (the repo inbox, inbox.Inbox._apply). The stage arrives as
set_stage (Info.Stage) or set_config (Info.Stage / Stage_1..3). A definite "no" is
refused before anything is written, the receipt is a failure whose text contains
「MAA 走不到，修改失败」, the stage and why; "could not tell" goes through.
"""
import json
import logging
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


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

from _tmp import tmpdir  # noqa: E402
import _stagegate_fx as fx  # noqa: E402

TMP = tmpdir()
MORNING = fx.maa_dir(TMP / "maa-morning")
AFTERNOON = fx.maa_dir(TMP / "maa-afternoon", yw=fx.YW_AFTERNOON)
AUTOMAS = fx.automas_dir(TMP / "AUTO-MAS", stage="1-7")
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_AUTOMAS_DIR=str(AUTOMAS), ARK_MAA_DIR=str(MORNING),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="")
import boot_stages  # noqa: E402
from ark_relay import commands, inbox, texts  # noqa: E402

USER_SAID = ("2026-10-10 16:58 (Osaka): 「我自己在离线设定的时候，就是手机遥控器那边一定一定要提示我maa走不到，"
             "修改失败。如果是我通过你们去改关卡，你们自己要核实能不能做到。如果走不到就报修改失败。」")
PHRASE = "MAA 走不到，修改失败"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


writes = []
commands._backend_scripts = lambda: ({"stub": {}}, "")        # the backend answers
commands._user_item_report = lambda s, p, v: (writes.append((s, p, v)), (True, f"{p}：→ {v}"))[1]
commands._user_item_via_api = lambda s, p, v: (writes.append((s, p, v)), ("", "1-7", v))[1]


class Note:
    def __init__(self):
        self.sent = []

    def send(self, title, body, alert=False, **kw):
        self.sent.append((title, body, alert))
        return []


def phone(body):
    """One order through the phone channel's executor, as live / drained / boot backlog do."""
    n, receipts = Note(), []
    boot_stages._phone_execute(commands.apply_command, n, logging.getLogger("ark.test_stage_set_refused"),
                               lambda *a, **k: None, lambda a, s, ok, msg: receipts.append((ok, msg)),
                               dict(body, confirmed=True), body["action"], None, True)
    return receipts[0], n.sent


print("[the phone page / App / order-now.sh: set_stage]")
writes.clear()
(ok, msg), sent = phone({"action": "set_stage", "value": "YW-4"})
check("refused: the receipt is a failure", ok, False)
check("the receipt says 「MAA 走不到，修改失败」, the stage and why",
      (PHRASE in msg, "YW-4" in msg, "resource/tasks" in msg), (True, True, True))
check("nothing written", writes, [])
check("and the group hears 「📱 配置没改成」 with the same text", [(t, a, PHRASE in b) for t, b, a in sent],
      [(texts.CONFIG_FAILED, True, True)])

print("\n[set_config, the App's and the page's stage box]")
for path in ("Info.Stage", "Info.Stage_1", "Info.Stage_3"):
    writes.clear()
    (ok, msg), _sent = phone({"action": "set_config", "script": "MAA", "path": path, "value": "YW-4"})
    check(f"{path}: refused with the phrase, nothing written", (ok, PHRASE in msg, writes), (False, True, []))
writes.clear()
(ok, msg), _sent = phone({"action": "set_config", "script": "MAA", "path": "Info.Stage", "value": "1-7"})
check("a reachable stage is written", (ok, writes), (True, [("MAA", "Info.Stage", "1-7")]))

print("\n[the MAA script under another display name]")
data = json.loads((AUTOMAS / "config" / "ScriptConfig.json").read_text(encoding="utf-8"))
data["S-MAA"]["Info"]["Name"] = "maa明日方舟"
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
writes.clear()
(ok, msg), _sent = phone({"action": "set_config", "script": "maa明日方舟", "path": "Info.Stage", "value": "YW-4"})
check("refused by the script's install path, not its name", (ok, PHRASE in msg, writes), (False, True, []))
data["S-MAA"]["Info"]["Name"] = "MAA"
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

print("\n[order.sh: the repo inbox applied at boot / before power-off]")
box = inbox.Inbox(TMP / "state", automas_dir=AUTOMAS)
writes.clear()
lines = box._apply([{"action": "set_stage", "value": "YW-4"}])
check("the inbox line is a failure with the phrase", (lines[0].startswith("✗"), PHRASE in lines[0]), (True, True))
check("nothing written", writes, [])

print("\n[AUTO-MAS down: set_stage would edit the file - refused before that]")
commands._backend_scripts = lambda: (None, "")
before = (AUTOMAS / "config" / "ScriptConfig.json").read_text(encoding="utf-8")
ok, msg = commands.apply_command({"action": "set_stage", "value": "YW-4", "confirmed": True})
check("refused with the phrase", (ok, PHRASE in msg), (False, True))
check("the config file is untouched", (AUTOMAS / "config" / "ScriptConfig.json").read_text(encoding="utf-8"),
      before)
commands._backend_scripts = lambda: ({"stub": {}}, "")

print("\n[reachable / could not tell: goes through]")
os.environ["ARK_MAA_DIR"] = str(AFTERNOON)
writes.clear()
(ok, msg), _sent = phone({"action": "set_stage", "value": "YW-4"})
check("afternoon files: YW-4 is written", (ok, writes), (True, [("MAA", "Info.Stage", "YW-4")]))
os.environ["ARK_MAA_DIR"] = str(TMP / "no-such-maa")
writes.clear()
(ok, msg), _sent = phone({"action": "set_stage", "value": "YW-4"})
check("task files unreadable: written (unknown never blocks)", (ok, writes), (True, [("MAA", "Info.Stage", "YW-4")]))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
