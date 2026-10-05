"""The three boot-time "switch the MaaEnd dailies back on" functions, run for real.

`gameupdate.maaend_reenable_if_updated`, `maaend_reenable_next_boot` and
`maaend_reenable_spmed_if_updated` were in untested-baseline.txt: every test
that reached them stubbed them out (test_makeup.py, test_preupdate_not_alarm.py).
Each one reads a reminder from state.json, decides from MaaEnd's own files
whether to act, edits the MaaEnd master, and deletes the reminder. A reminder
deleted without the task being back on is a daily lost with nobody told, so
every branch below checks the reminder and the master together.

Inputs are real files:
* master: relay/tests/fixtures/maaend-2026-09-10/master-before.json (the
  machine's mxu-MaaEnd.json), placed at AUTO-MAS's
  data/<script id>/Default/ConfigFile/mxu-MaaEnd.json; the reminded tasks are
  switched off in the copy, which is the state the reminder describes.
* MaaEnd version: interface.json from fixtures/maaend228 (v2.28.0-beta.4),
  fixtures/maaend-2026-09-10 (v2.28.0-beta.5) and
  fixtures/maaend-v2.30.0-beta.4-spmed (see its SOURCE.txt).
* nodes.json "fixed" / "broken" shapes: the shapes described in gameupdate.py
  above spmed_fix_present (beta.5 read off the machine 09-03, upstream PR
  #5453), the same ones test_config_writers.py uses. The "no recognition
  block" shape is the one the comment inside spmed_fix_present records for
  v2.28.0-beta.4; no copy of that file was kept, so it is built from the
  comment. The renamed-node shape is real (fixtures/maaend-v2.30.0-beta.4-spmed).
* Expected messages match what the machine logged: relay.log 09-03 11:42:27
  「开机：已开回：自动采集」 (~/Claude/ark-evidence/relay-log-1006/relay.log).

Checks marked OBSERVED pin down current behaviour that is an open question
for the user, not endorsed: flip them when that is settled (the renamed spmed
node in v2.30.0-beta.4, at the end).
"""
import json
import logging
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
from ark_relay import gameupdate  # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
MASTER = FIX / "maaend-2026-09-10" / "master-before.json"
V_BETA4 = FIX / "maaend228" / "interface.json"                       # v2.28.0-beta.4
V_BETA5 = FIX / "maaend-2026-09-10" / "interface.json"                 # v2.28.0-beta.5
V_230 = FIX / "maaend-v2.30.0-beta.4-spmed"                            # interface + nodes
FOUR = ["GiftOperator", "GearAssembly", "DeliveryJobs", "EnvironmentMonitoring"]

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
logging.getLogger("ark").addHandler(CAP)
logging.getLogger("ark").setLevel(logging.DEBUG)


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
        tasks.extend(dict(t) for t in extra_tasks)
        for t in tasks:
            if t.get("taskName") in off:
                t["enabled"] = False
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


def others(target, names):
    """Every task not named, as (name, enabled) - to prove nothing else moved."""
    j = json.loads(target.read_text(encoding="utf-8"))
    return [(t.get("taskName"), t.get("enabled")) for t in j["instances"][0]["tasks"]
            if t.get("taskName") not in names]


def updates(store):
    return dict(StateStore(store.dir).section("updates"))


ORIG_OTHERS = others(MASTER, FOUR)
check("fixture versions are what the names say",
      [json.loads(p.read_text(encoding="utf-8"))["version"]
       for p in (V_BETA4, V_BETA5, V_230 / "interface.json")],
      ["v2.28.0-beta.4", "v2.28.0-beta.5", "v2.30.0-beta.4"])

# ====================================================== maaend_reenable_if_updated
R153 = {"maaend_disabled_1_5_3": {"disabled": FOUR, "since": "v2.28.0-beta.4"}}

print("\n[if_updated: no reminder - nothing happens]")
cfg, target, store = machine(version=V_BETA5, off=FOUR)
before = target.read_bytes()
check("returns nothing", gameupdate.maaend_reenable_if_updated(cfg), "")
check("master untouched", target.read_bytes(), before)

print("\n[if_updated: MaaEnd still on the version that broke them]")
cfg, target, store = machine(version=V_BETA4, off=FOUR, record=R153)
before = target.read_bytes()
check("returns nothing", gameupdate.maaend_reenable_if_updated(cfg), "")
check("master untouched", target.read_bytes(), before)
check("reminder kept", "maaend_disabled_1_5_3" in updates(store), True)

print("\n[if_updated: MaaEnd version unreadable (no interface.json)]")
cfg, target, store = machine(version=None, off=FOUR, record=R153)
check("returns nothing", gameupdate.maaend_reenable_if_updated(cfg), "")
check("reminder kept", "maaend_disabled_1_5_3" in updates(store), True)
check("tasks still off", set(enabled(target, FOUR).values()), {False})

print("\n[if_updated: MaaEnd moved on - the four come back on]")
cfg, target, store = machine(version=V_BETA5, off=FOUR, record=R153)
msg = gameupdate.maaend_reenable_if_updated(cfg)
check("message names version and all four",
      msg, "MaaEnd 已更新到 v2.28.0-beta.5（之前是 v2.28.0-beta.4），关掉的 4 项日常已开回来："
           "赠送干员礼物、装备制造、转交委托、环境监测")
check("all four on in the master", enabled(target, FOUR), {n: True for n in FOUR})
check("no other task moved", others(target, FOUR), ORIG_OTHERS)
check("reminder removed", "maaend_disabled_1_5_3" in updates(store), False)
check("second boot: nothing more to say", gameupdate.maaend_reenable_if_updated(cfg), "")

print("\n[if_updated: moved on, but they were already switched on by hand]")
cfg, target, store = machine(version=V_BETA5, off=(), record=R153)
before = target.read_bytes()
check("returns nothing", gameupdate.maaend_reenable_if_updated(cfg), "")
check("master not rewritten", target.read_bytes(), before)
check("reminder removed (nothing left to do)", "maaend_disabled_1_5_3" in updates(store), False)

print("\n[if_updated: moved on, master missing]")
cfg, target, store = machine(version=V_BETA5, master=False, record=R153)
# It used to return "" here (silent, unlike the two siblings which say so)
check("says it could not, like the two siblings",
      gameupdate.maaend_reenable_if_updated(cfg),
      "MaaEnd 的母本找不到，为 1.5.3 关掉的日常还没能开回来，下次开机再试")
check("reminder kept for the next boot", "maaend_disabled_1_5_3" in updates(store), True)

print("\n[if_updated: moved on, master unreadable]")
cfg, target, store = machine(version=V_BETA5, off=FOUR, record=R153)
target.write_text("{ truncated", encoding="utf-8")
try:
    gameupdate.maaend_reenable_if_updated(cfg)
    raised = ""
except ValueError as exc:
    raised = type(exc).__name__
check("raises (the boot stage logs 「开回 MaaEnd 任务出错」)", raised, "JSONDecodeError")
check("reminder kept", "maaend_disabled_1_5_3" in updates(store), True)

print("\n[if_updated: reminder in the shape statestore.py documents ({tasks, since})]")
# statestore.py documents updates.maaend_disabled_1_5_3 as {tasks, since};
# the reader takes the names from "disabled" (gameupdate.py, the
# `rec.get("disabled")` line). No code writes this reminder - it was written
# by hand on 2026-09-02 (commit 4619518b) - so whoever writes it next from the
# documented shape used to get nothing switched on and the reminder deleted.
# Both keys are read now.
cfg, target, store = machine(version=V_BETA5, off=FOUR,
                             record={"maaend_disabled_1_5_3": {"tasks": FOUR, "since": "v2.28.0-beta.4"}})
check("the four come back on", (gameupdate.maaend_reenable_if_updated(cfg),
                                set(enabled(target, FOUR).values())),
      ("MaaEnd 已更新到 v2.28.0-beta.5（之前是 v2.28.0-beta.4），关掉的 4 项日常已开回来："
       "赠送干员礼物、装备制造、转交委托、环境监测", {True}))
check("reminder removed", "maaend_disabled_1_5_3" in updates(store), False)

print("\n[if_updated: reminder names no task at all - keep it, switch nothing, warn]")
cfg, target, store = machine(version=V_BETA5, off=FOUR,
                             record={"maaend_disabled_1_5_3": {"since": "v2.28.0-beta.4"}})
before = target.read_bytes()
CAP.lines.clear()
check("returns nothing", gameupdate.maaend_reenable_if_updated(cfg), "")
check("master untouched", target.read_bytes(), before)
check("reminder kept", "maaend_disabled_1_5_3" in updates(store), True)
check("warned", any(lv == "WARNING" and "没有任务名" in m for lv, m in CAP.lines), True)

# ====================================================== maaend_reenable_next_boot
print("\n[next_boot: no reminder]")
cfg, target, store = machine(version=V_BETA5, off=["AutoCollect"])
check("returns nothing", gameupdate.maaend_reenable_next_boot(cfg), "")
check("AutoCollect still off", enabled(target, ["AutoCollect"]), {"AutoCollect": False})

print("\n[next_boot: AutoCollect switched off for a re-run comes back (relay.log 09-03 11:42:27)]")
cfg, target, store = machine(version=V_BETA5, off=["AutoCollect"],
                             record={"maaend_reenable_next_boot": {"tasks": ["AutoCollect"]}})
check("message as on the machine", gameupdate.maaend_reenable_next_boot(cfg), "已开回：自动采集")
check("AutoCollect on", enabled(target, ["AutoCollect"]), {"AutoCollect": True})
check("no other task moved", others(target, ["AutoCollect"]), others(MASTER, ["AutoCollect"]))
check("reminder removed", "maaend_reenable_next_boot" in updates(store), False)

print("\n[next_boot: master missing - keep the reminder and say so]")
cfg, target, store = machine(master=False, record={"maaend_reenable_next_boot": {"tasks": ["AutoCollect"]}})
check("says it could not", gameupdate.maaend_reenable_next_boot(cfg),
      "MaaEnd 的母本找不到，临时关掉的日常还没能开回来，下次开机再试")
check("reminder kept", "maaend_reenable_next_boot" in updates(store), True)

print("\n[next_boot: already on]")
cfg, target, store = machine(off=(), record={"maaend_reenable_next_boot": {"tasks": ["AutoCollect"]}})
before = target.read_bytes()
check("returns nothing", gameupdate.maaend_reenable_next_boot(cfg), "")
check("master not rewritten", target.read_bytes(), before)
check("reminder removed", "maaend_reenable_next_boot" in updates(store), False)

# ====================================================== maaend_reenable_spmed_if_updated
SPMED = {"taskName": "AutoUseSpMedication", "enabled": False, "optionValues": {}}
RSP = {"maaend_disabled_spmed": {"tasks": ["AutoUseSpMedication"], "since": "v2.28.0-beta.4"}}
FIXED = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
    "YellowConfirmButtonType2", {"recognition": "OCR", "expected": "确认"}]}}}}
BROKEN = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
    "YellowConfirmButtonType2", {"param": {"expected": "确认"}, "type": "OCR"}]}}}}
NO_RECOGNITION = {"AutoUseSpMedicationQuickUse": {"next": ["AutoUseSpMedicationDialogText"]}}

print("\n[spmed: no reminder]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, extra_tasks=[SPMED])
check("returns nothing", gameupdate.maaend_reenable_spmed_if_updated(cfg), "")
check("task still off", enabled(target, ["AutoUseSpMedication"]), {"AutoUseSpMedication": False})

print("\n[spmed: same version as when it broke]")
cfg, target, store = machine(version=V_BETA4, nodes=FIXED, extra_tasks=[SPMED], record=RSP)
check("returns nothing", gameupdate.maaend_reenable_spmed_if_updated(cfg), "")
check("reminder kept", "maaend_disabled_spmed" in updates(store), True)

print("\n[spmed: new version, confirm node in the fixed shape]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, extra_tasks=[SPMED], record=RSP)
check("says it is fixed", gameupdate.maaend_reenable_spmed_if_updated(cfg),
      "MaaEnd 已是 v2.28.0-beta.5，加强剂那一步已经修好，任务开回来")
check("task on", enabled(target, ["AutoUseSpMedication"]), {"AutoUseSpMedication": True})
check("reminder removed", "maaend_disabled_spmed" in updates(store), False)

print("\n[spmed: new version, confirm node still in the broken shape]")
cfg, target, store = machine(version=V_BETA5, nodes=BROKEN, extra_tasks=[SPMED], record=RSP)
CAP.lines.clear()
check("returns nothing", gameupdate.maaend_reenable_spmed_if_updated(cfg), "")
check("task stays off", enabled(target, ["AutoUseSpMedication"]), {"AutoUseSpMedication": False})
check("reminder kept", "maaend_disabled_spmed" in updates(store), True)
check("logged why", ("INFO", "MaaEnd 已是 v2.28.0-beta.5，但加强剂那条判据还是坏的写法，继续关着") in CAP.lines, True)

print("\n[spmed: new version, fixed, master missing]")
cfg, target, store = machine(version=V_BETA5, nodes=FIXED, master=False, record=RSP)
check("says it could not", gameupdate.maaend_reenable_spmed_if_updated(cfg),
      "MaaEnd 的母本找不到，加强剂任务还没能开回来，下次开机再试")
check("reminder kept", "maaend_disabled_spmed" in updates(store), True)

print("\n[spmed: spmed_fix_present answers None (node has no recognition block)]")
# Until 2026-10-06 (09-09 decision) None switched the task back on with
# 「要是明天又失败就再关」 and deleted the reminder - and nothing in the relay
# ever switches it off again. Now it stays off and is said once per version.
cfg, target, store = machine(version=V_BETA5, nodes=NO_RECOGNITION, extra_tasks=[SPMED], record=RSP)
check("spmed_fix_present is None for this shape", gameupdate.spmed_fix_present(cfg.maaend_dir), None)
probs = []
check("returns nothing (no 「已开回」 push)", gameupdate.maaend_reenable_spmed_if_updated(cfg, problems=probs), "")
check("task stays off", enabled(target, ["AutoUseSpMedication"]), {"AutoUseSpMedication": False})
check("one problem naming the version and the node's keys", probs,
      ["终末地：MaaEnd 已是 v2.28.0-beta.5，加强剂那一步的写法认不出（这一步里有：next），"
       "看不出修没修，任务继续关着"])
check("reminder kept, since moved to this version",
      updates(store).get("maaend_disabled_spmed"),
      {"tasks": ["AutoUseSpMedication"], "since": "v2.28.0-beta.5"})
probs = []
check("next boot on the same version: nothing more", (gameupdate.maaend_reenable_spmed_if_updated(
    cfg, problems=probs), probs), ("", []))

print("\n[spmed: the real v2.30.0-beta.4 nodes.json - the node was renamed]")
cfg, target, store = machine(version=V_230 / "interface.json", nodes=V_230 / "resource" / "pipeline" / "nodes.json",
                             extra_tasks=[SPMED], record=RSP)
CAP.lines.clear()
check("real file has no AutoUseSpMedicationQuickUse", "AutoUseSpMedicationQuickUse" in json.loads(
    (cfg.maaend_dir / "resource" / "pipeline" / "nodes.json").read_text(encoding="utf-8")), False)
check("OBSERVED: a missing node reads as 'not fixed' (False), not 'unknown' (None)",
      gameupdate.spmed_fix_present(cfg.maaend_dir), False)
check("OBSERVED: stays off, says nothing", gameupdate.maaend_reenable_spmed_if_updated(cfg), "")
check("OBSERVED: reminder kept, so this repeats every boot", "maaend_disabled_spmed" in updates(store), True)
check("OBSERVED: the only trace is an INFO line calling it the broken shape",
      ("INFO", "MaaEnd 已是 v2.30.0-beta.4，但加强剂那条判据还是坏的写法，继续关着") in CAP.lines, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
