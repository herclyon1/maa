"""MaaEnd tasks the relay once switched off come back on at boot; nothing keeps them off.

The user, 2026-10-06, on the sanity booster: 「那个要一直开着，如果上游maaend改了导致没生效就要报警」,
and on who switched it off: 「我开的任务是谁说要关的」. Until then three boot-time functions in gameupdate.py
kept tasks off: the booster until its confirm node read as "fixed" and MaaEnd had
changed version, the four 1.5.3 dailies until MaaEnd changed version. Now every
leftover record (updates.maaend_disabled_1_5_3 / maaend_reenable_next_boot /
maaend_disabled_spmed) has its tasks switched on at the next boot, whatever the
version or the node shape, and is dropped; switching on is logged at INFO and not
pushed. The booster step is still read at every boot, and a shape the relay does not
know to work rings the group each time (texts.SPMED_UNRECOGNISED).

Run through boot_stages._stage_reenable_maaend, the entry the service calls at boot.

Inputs are real files:
* master: relay/tests/fixtures/maaend-2026-09-10/master-before.json (the
  machine's mxu-MaaEnd.json), placed at AUTO-MAS's
  data/<script id>/Default/ConfigFile/mxu-MaaEnd.json; the recorded tasks are
  switched off in the copy, which is the state the record describes. The
  standalone AutoUseSpMedication task (gone from MaaEnd since v2.28) is added to the
  copy the way the 09-03 master had it.
* MaaEnd version: interface.json from fixtures/maaend228 (v2.28.0-beta.4),
  fixtures/maaend-2026-09-10 (v2.28.0-beta.5) and
  fixtures/maaend-v2.30.0-beta.4-spmed (see its SOURCE.txt).
* nodes.json shapes: "fixed" / "broken" are the shapes described in gameupdate.py
  above SPMED_NODE (beta.5 read off the machine 09-03, upstream PR #5453); the
  "no recognition block" shape is the one gameupdate.py records for v2.28.0-beta.4
  (no copy of that file was kept, so it is built from the comment). The renamed-node
  shape is real (fixtures/maaend-v2.30.0-beta.4-spmed).
"""
import json
import logging
import shutil
import sys
import types
from pathlib import Path
from types import SimpleNamespace

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


for _n in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
           "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(_n, _Stub(_n))

import boot_stages  # noqa: E402
from ark_relay import collect_retry, errwatch, gameupdate, mastercfg, notify, texts  # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
MASTER = FIX / "maaend-2026-09-10" / "master-before.json"
V_BETA4 = FIX / "maaend228" / "interface.json"                       # v2.28.0-beta.4
V_BETA5 = FIX / "maaend-2026-09-10" / "interface.json"                 # v2.28.0-beta.5
V_230 = FIX / "maaend-v2.30.0-beta.4-spmed"                            # interface + nodes
NODES_230 = V_230 / "resource" / "pipeline" / "nodes.json"
# The confirm step under neither of its names: v2.30's real file has it as
# __AutoUseSpMedicationUseEmergencySpBooster, in the fixed shape (test_spmed_v232.py).
NODES_GONE = {k: v for k, v in json.loads(NODES_230.read_text(encoding="utf-8")).items()
              if k not in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster")}
FOUR = ["GiftOperator", "GearAssembly", "DeliveryJobs", "EnvironmentMonitoring"]
SP = "AutoUseSpMedication"
SPMED = {"taskName": SP, "enabled": False, "enabledByController": {"Win32-Front": False}, "optionValues": {}}
RSP = {"maaend_disabled_spmed": {"tasks": [SP], "since": "v2.28.0-beta.4"}}
FIXED = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
    "YellowConfirmButtonType2", {"recognition": "OCR", "expected": "确认"}]}}}}
BROKEN = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
    "YellowConfirmButtonType2", {"param": {"expected": "确认"}, "type": "OCR"}]}}}}
NO_RECOGNITION = {"AutoUseSpMedicationQuickUse": {"next": ["AutoUseSpMedicationDialogText"]}}

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelname, record.getMessage()))


CAP = Capture()
logging.getLogger(errwatch.ARK).addHandler(CAP)
logging.getLogger(errwatch.ARK).setLevel(logging.DEBUG)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, bool(kw.get("alert"))))
        return []


class Log:
    def __init__(self):
        self.lines = []

    def _rec(self, *a, **k):
        self.lines.append(a)

    info = warning = error = debug = exception = _rec


# Only the re-enable and the booster check are under test: the later steps of the
# stage (dead entries, option migration, route restore) are stubbed.
mastercfg.prune_maaend_orphans = lambda *a: ([], "")
mastercfg.migrate_maaend_options = lambda *a: ([], "")
collect_retry.restore_master = lambda cfg: ""
TITLE = getattr(texts, "SPMED_UNRECOGNISED", "<no such title>")


def machine(*, version=None, nodes=None, off=(), extra_tasks=(), master=True, record=None):
    """state dir + MaaEnd dir + AUTO-MAS dir. Returns (cfg, master path, store)."""
    root = tmpdir()
    state = root / "state"
    state.mkdir()
    maaend = root / "maaend"
    maaend.mkdir()
    if version is not None:
        shutil.copy(version, maaend / "interface.json")
    if nodes is not None:
        (maaend / "resource" / "pipeline").mkdir(parents=True)
        if isinstance(nodes, Path):
            shutil.copy(nodes, maaend / "resource" / "pipeline" / "nodes.json")
        else:
            (maaend / "resource" / "pipeline" / "nodes.json").write_text(
                json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
    automas = root / "automas"
    target = automas / "data" / "59da8762-sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    if master:
        target.parent.mkdir(parents=True)
        j = json.loads(MASTER.read_text(encoding="utf-8"))
        tasks = j["instances"][0]["tasks"]
        tasks.extend(json.loads(json.dumps(t)) for t in extra_tasks)
        for t in tasks:
            if t.get("taskName") in off:
                t["enabled"] = False
                if isinstance(t.get("enabledByController"), dict):
                    t["enabledByController"] = {k: False for k in t["enabledByController"]}
        target.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
    store = StateStore(state)
    for key, value in (record or {}).items():
        store.set("updates", key, value)
    cfg = SimpleNamespace(state_dir=state, maaend_dir=maaend, automas_dir=automas)
    return cfg, target, store


def enabled(target, names):
    j = json.loads(target.read_text(encoding="utf-8"))
    by = {t.get("taskName"): t.get("enabled") for t in j["instances"][0]["tasks"]}
    return {n: by.get(n) for n in names}


def controllers(target, name):
    j = json.loads(target.read_text(encoding="utf-8"))
    return next((t.get("enabledByController") for t in j["instances"][0]["tasks"] if t.get("taskName") == name), None)


def others(target, names):
    """Every task not named, as (name, enabled, controllers) - to prove nothing else moved."""
    j = json.loads(target.read_text(encoding="utf-8"))
    return [(t.get("taskName"), t.get("enabled"), json.dumps(t.get("enabledByController")))
            for t in j["instances"][0]["tasks"] if t.get("taskName") not in names]


def updates(store):
    return dict(StateStore(store.dir).section("updates"))


def boot(cfg):
    """One boot's re-enable stage. Returns (pushes, log lines of ark.*)."""
    n = Notes()
    CAP.lines.clear()
    boot_stages._stage_reenable_maaend(cfg, n, Log())
    return n.sent, list(CAP.lines)


def spmed_pushes(sent):
    return [(t, a) for t, _b, a in sent if t == TITLE]


ORIG_OTHERS = others(MASTER, FOUR)
check("fixture versions are what the names say",
      [json.loads(p.read_text(encoding="utf-8"))["version"]
       for p in (V_BETA4, V_BETA5, V_230 / "interface.json")],
      ["v2.28.0-beta.4", "v2.28.0-beta.5", "v2.30.0-beta.4"])
check("the real v2.30.0-beta.4 nodes.json has no AutoUseSpMedicationQuickUse",
      "AutoUseSpMedicationQuickUse" in json.loads(NODES_230.read_text(encoding="utf-8")), False)

print("\n[booster record, MaaEnd v2.30 with the step under neither name, same version as the record: on at once, group told]")
cfg, target, store = machine(version=V_230 / "interface.json", nodes=NODES_GONE, extra_tasks=[SPMED],
                             record={"maaend_disabled_spmed": {"tasks": [SP], "since": "v2.30.0-beta.4"}})
sent, lines = boot(cfg)
check("应急理智加强剂 on", enabled(target, [SP]), {SP: True})
check("its per-controller switch on too", controllers(target, SP), {"Win32-Front": True})
check("record dropped", "maaend_disabled_spmed" in updates(store), False)
check("switching on is an INFO line", [lv for lv, m in lines if "已开回" in m and "应急理智加强剂" in m], ["INFO"])
check("switching on is not pushed", [t for t, b, _a in sent if "开回" in t or "开回" in b], [])
check("the unknown booster step rings the group", spmed_pushes(sent), [(TITLE, True)])
check("that title routes to the group", notify.route_of(TITLE, alert=True), "group")
body = next((b for t, b, _a in sent if t == TITLE), "")
check("the text says the task stays on and why it rings", ("一直开着" in body, "找不到" in body), (True, True))
check("the text is plain Chinese", texts.plain(body), [])
check("no other task moved", others(target, FOUR + [SP]), others(MASTER, FOUR + [SP]))
sent2, _ = boot(cfg)
check("next boot: rings again (each time it is seen)", len(spmed_pushes(sent2)), 1)
check("next boot: still on", enabled(target, [SP]), {SP: True})

print("\n[booster record, MaaEnd changed version, node with no recognition block: on, group told]")
cfg, target, store = machine(version=V_BETA5, nodes=NO_RECOGNITION, extra_tasks=[SPMED], record=RSP)
sent, _ = boot(cfg)
check("on", enabled(target, [SP]), {SP: True})
check("record dropped", "maaend_disabled_spmed" in updates(store), False)
check("group told", len(spmed_pushes(sent)), 1)
check("not the old 「游戏更新没能确认」 info push", [t for t, _b, _a in sent if "没能确认" in t], [])

print("\n[booster record, the 09-03 broken shape: on anyway, group told]")
cfg, target, store = machine(version=V_BETA5, nodes=BROKEN, extra_tasks=[SPMED], record=RSP)
sent, _ = boot(cfg)
check("on", enabled(target, [SP]), {SP: True})
check("record dropped", "maaend_disabled_spmed" in updates(store), False)
check("group told", len(spmed_pushes(sent)), 1)

print("\n[booster record, fixed shape: on, nothing pushed at all]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, extra_tasks=[SPMED], record=RSP)
sent, lines = boot(cfg)
check("on", enabled(target, [SP]), {SP: True})
check("record dropped", "maaend_disabled_spmed" in updates(store), False)
check("no push (switching on is only logged)", sent, [])

print("\n[booster task on, no record, booster step unknown: the task is not touched, group told]")
on_sp = dict(SPMED, enabled=True, enabledByController={"Win32-Front": True})
cfg, target, store = machine(version=V_230 / "interface.json", nodes=NODES_GONE, extra_tasks=[on_sp])
before = target.read_bytes()
sent, _ = boot(cfg)
check("master not rewritten", target.read_bytes(), before)
check("group told", len(spmed_pushes(sent)), 1)

print("\n[no record, fixed shape: nothing written, nothing pushed]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR)
before = target.read_bytes()
sent, _ = boot(cfg)
check("master not rewritten", target.read_bytes(), before)
check("no push", sent, [])

print("\n[1.5.3 record (hand-written {disabled, since}), MaaEnd still on that version: on at once]")
cfg, target, store = machine(version=V_BETA4, nodes=FIXED, off=FOUR,
                             record={"maaend_disabled_1_5_3": {"disabled": FOUR, "since": "v2.28.0-beta.4"}})
sent, lines = boot(cfg)
check("all four on", enabled(target, FOUR), {n: True for n in FOUR})
check("no other task moved", others(target, FOUR), ORIG_OTHERS)
check("record dropped", "maaend_disabled_1_5_3" in updates(store), False)
check("INFO line names the four", [m for lv, m in lines if lv == "INFO" and "已开回" in m],
      ["开机：中继以前关掉的终末地任务已开回：赠送干员礼物、装备制造、转交委托、环境监测（记录 maaend_disabled_1_5_3 已删）"])
check("no push", sent, [])

print("\n[1.5.3 record in the documented shape ({tasks, since}), MaaEnd version unreadable: on]")
cfg, target, store = machine(version=None, nodes=FIXED, off=FOUR,
                             record={"maaend_disabled_1_5_3": {"tasks": FOUR, "since": "v2.28.0-beta.4"}})
boot(cfg)
check("all four on", enabled(target, FOUR), {n: True for n in FOUR})
check("record dropped", "maaend_disabled_1_5_3" in updates(store), False)

print("\n[make-up record ({tasks}): 自动采集 on, nothing pushed]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=["AutoCollect"],
                             record={"maaend_reenable_next_boot": {"tasks": ["AutoCollect"]}})
sent, _ = boot(cfg)
check("自动采集 on", enabled(target, ["AutoCollect"]), {"AutoCollect": True})
check("no other task moved", others(target, ["AutoCollect"]), others(MASTER, ["AutoCollect"]))
check("record dropped", "maaend_reenable_next_boot" in updates(store), False)
check("no push", sent, [])

print("\n[already on: record dropped, master not rewritten]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=(),
                             record={"maaend_reenable_next_boot": {"tasks": ["AutoCollect"]}})
before = target.read_bytes()
sent, lines = boot(cfg)
check("master not rewritten", target.read_bytes(), before)
check("record dropped", "maaend_reenable_next_boot" in updates(store), False)
check("said at INFO", [lv for lv, m in lines if "已经开着" in m], ["INFO"])

print("\n[master missing: WARNING (a relay WARNING reaches the group), record kept for the next boot]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, master=False, record=RSP)
sent, lines = boot(cfg)
check("record kept", "maaend_disabled_spmed" in updates(store), True)
check("one WARNING naming the task and the reason",
      [m for lv, m in lines if lv == "WARNING"],
      ["开机：中继以前关掉的终末地任务 应急理智加强剂 没能开回（找不到终末地的母本），记录留着，下次开机再试"])

print("\n[master unreadable: WARNING, record kept, the stage does not fall over]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR,
                             record={"maaend_disabled_1_5_3": {"disabled": FOUR}})
target.write_text("{ truncated", encoding="utf-8")
sent, lines = boot(cfg)
check("record kept", "maaend_disabled_1_5_3" in updates(store), True)
check("WARNING says it could not be read", any(lv == "WARNING" and "读不出来" in m for lv, m in lines), True)

print("\n[record naming no task: WARNING with the record, dropped]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR,
                             record={"maaend_disabled_1_5_3": {"since": "v2.28.0-beta.4"}})
before = target.read_bytes()
sent, lines = boot(cfg)
check("master untouched", target.read_bytes(), before)
check("record dropped", "maaend_disabled_1_5_3" in updates(store), False)
check("warned", any(lv == "WARNING" and "没有任务名" in m for lv, m in lines), True)

print("\n[record naming a task the master no longer has (the booster task is gone since v2.28): WARNING, dropped]")
cfg, target, store = machine(version=V_230 / "interface.json", nodes=NODES_230, record=RSP)
before = target.read_bytes()
sent, lines = boot(cfg)
check("master untouched", target.read_bytes(), before)
check("record dropped", "maaend_disabled_spmed" in updates(store), False)
check("warned, naming it", [m for lv, m in lines if lv == "WARNING"],
      ["开机：中继以前关掉的终末地任务里，应急理智加强剂 母本里已经没有了，没法开回（记录 maaend_disabled_spmed 已删）"])

print("\n[all three records at once: every task on, every record gone]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR + ["AutoCollect"], extra_tasks=[SPMED],
                             record={"maaend_disabled_1_5_3": {"disabled": FOUR},
                                     "maaend_reenable_next_boot": {"tasks": ["AutoCollect"]},
                                     **RSP})
boot(cfg)
check("all on", set(enabled(target, FOUR + ["AutoCollect", SP]).values()), {True})
check("no record left", [k for k in ("maaend_disabled_1_5_3", "maaend_reenable_next_boot", "maaend_disabled_spmed")
                         if k in updates(store)], [])
check("no other task moved", others(target, FOUR + ["AutoCollect", SP]), others(MASTER, FOUR + ["AutoCollect", SP]))

print("\n[the writer itself: only ever switches on]")
fn = getattr(gameupdate, "maaend_enable", None)
cfg, target, store = machine(off=["AutoCollect"])
check("maaend_enable exists", callable(fn), True)
if callable(fn):
    check("switches on, names what it changed and what the master lacks",
          fn(cfg, {"AutoCollect", "NoSuchTask"}), (["AutoCollect"], ["NoSuchTask"], ""))
    before = target.read_bytes()
    check("already on: no change, no write", (fn(cfg, {"AutoCollect"}), target.read_bytes() == before),
          (([], [], ""), True))
    try:
        fn(cfg, {"AutoCollect"}, False)
        took_off = True
    except TypeError:
        took_off = False
    check("there is no way to ask it to switch off", (took_off, enabled(target, ["AutoCollect"])),
          (False, {"AutoCollect": True}))
    check("master missing: says so", fn(machine(master=False)[0], {"AutoCollect"}), ([], [], "找不到终末地的母本"))
check("the old on/off writer is gone", hasattr(gameupdate, "maaend_set_enabled"), False)

print("\n[the booster step's shape, read from nodes.json]")
shape = getattr(gameupdate, "spmed_shape", None)
check("spmed_shape exists", callable(shape), True)
if callable(shape):
    for label, nodes, want in (("fixed", FIXED, "fixed"), ("broken", BROKEN, "broken"),
                               ("no recognition block", NO_RECOGNITION, "unknown"),
                               ("v2.30: the step under its new name, fixed shape", NODES_230, "fixed"),
                               ("the step under neither name", NODES_GONE, "missing")):
        check(label, shape(machine(nodes=nodes)[0].maaend_dir), want)
    check("nodes.json missing", shape(machine()[0].maaend_dir), "unreadable")
    check("no MaaEnd directory", shape(None), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
