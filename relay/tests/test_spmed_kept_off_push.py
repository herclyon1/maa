"""应急理智加强剂 is never kept off; a booster step the relay cannot recognise rings the
group at every boot (2026-10-06).

Until 2026-10-06 boot_stages._stage_reenable_maaend kept the task off while
gameupdate could not tell whether upstream had fixed the booster's confirm node, and
said so under 「⚠️ 游戏更新没能确认」 (info route), once per MaaEnd version. The user,
2026-10-06, on the sanity booster: 「那个要一直开着，如果上游maaend改了导致没生效就要报警」,
and on who switched it off: 「我开的任务是谁说要关的」. Now the task is not touched, and every boot that finds the step in a shape the
relay does not know to work pushes texts.SPMED_UNRECOGNISED to the group
(docs/NOTIFICATIONS.md). (The file keeps its old name: the test map lists it.)

Input: the real v2.30.0-beta.4 nodes.json (fixtures/maaend-v2.30.0-beta.4-spmed) with
the confirm step removed under both of its names (AutoUseSpMedicationQuickUse and,
from v2.30/v2.32, __AutoUseSpMedicationUseEmergencySpBooster) - the real file has the
new one in the fixed shape and rings nothing (test_spmed_v232.py) - and the machine's
master (fixtures/maaend-2026-09-10/master-before.json) with the booster task on.
"""
import json
import shutil
import sys
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
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages                                   # noqa: E402
from ark_relay import collect_retry, gameupdate as gu, mastercfg, notify, texts  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notifier:
    def __init__(self): self.sent = []
    def send(self, title, body, **k): self.sent.append((title, body, bool(k.get("alert"))))


class Log:
    def __init__(self): self.lines = []
    def info(self, *a, **k): self.lines.append(("info", a))
    def warning(self, *a, **k): self.lines.append(("warning", a))
    def exception(self, *a, **k): self.lines.append(("exception", a))


mastercfg.prune_maaend_orphans = lambda *a: ([], "")
mastercfg.migrate_maaend_options = lambda *a: ([], "")
collect_retry.restore_master = lambda cfg: ""
FIX = Path(__file__).resolve().parent / "fixtures"
TITLE = getattr(texts, "SPMED_UNRECOGNISED", "<no such title>")

root = tmpdir()
maaend = root / "maaend"
(maaend / "resource" / "pipeline").mkdir(parents=True)
shutil.copy(FIX / "maaend-v2.30.0-beta.4-spmed" / "interface.json", maaend / "interface.json")
_nodes = json.loads((FIX / "maaend-v2.30.0-beta.4-spmed" / "resource" / "pipeline" / "nodes.json")
                    .read_text(encoding="utf-8"))
for _gone in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster"):
    _nodes.pop(_gone, None)
(maaend / "resource" / "pipeline" / "nodes.json").write_text(json.dumps(_nodes, ensure_ascii=False),
                                                             encoding="utf-8")
master = root / "automas" / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
master.parent.mkdir(parents=True)
doc = json.loads((FIX / "maaend-2026-09-10" / "master-before.json").read_text(encoding="utf-8"))
doc["instances"][0]["tasks"].append({"taskName": "AutoUseSpMedication", "enabled": True,
                                     "enabledByController": {"Win32-Front": True}})
master.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
(root / "state").mkdir()
cfg = types.SimpleNamespace(automas_dir=root / "automas", maaend_dir=maaend, state_dir=root / "state")
before = master.read_bytes()

print("[the booster step under neither of its names - every boot rings the group, the task is left on]")
for boot in (1, 2, 3):
    n, lg = Notifier(), Log()
    boot_stages._stage_reenable_maaend(cfg, n, lg)
    check(f"boot {boot}: one push, to the group", [(t, a) for t, _b, a in n.sent], [(TITLE, True)])
check("the master is not touched", master.read_bytes() == before, True)
check("the title routes to the group", notify.route_of(TITLE, alert=True), "group")
body = n.sent[-1][1] if n.sent else ""
check("the text is plain Chinese", texts.plain(body), [])
check("the text says the task stays on", "一直开着，中继不会关它" in body, True)
check("not the old info title", [t for t, _b, _a in n.sent if "没能确认" in t], [])

print("\n[the check failing does not take the stage down]")
real = getattr(gu, "spmed_check", None)
gu.spmed_check = lambda cfg: (_ for _ in ()).throw(OSError("磁盘读不了"))
n, lg = Notifier(), Log()
boot_stages._stage_reenable_maaend(cfg, n, lg)
check("logged as an exception, nothing pushed", ([x[0] for x in lg.lines if x[0] == "exception"], n.sent),
      (["exception"], []))
if real is not None:
    gu.spmed_check = real

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
