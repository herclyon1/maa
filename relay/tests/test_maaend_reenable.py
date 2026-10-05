"""MaaEnd dailies switched off on purpose come back on only when they should.

The three maaend_reenable_* functions in gameupdate.py were in
untested-baseline.txt (audit 2026-10-05, E). Each one reads a reminder record
from state.json, flips `enabled` in the master mxu-MaaEnd.json, and deletes the
record. The behaviour pinned here: nothing is switched on, and the reminder is
kept, whenever the condition is not met or the master cannot be found - a
deleted reminder with the dailies still off is the silent failure these
functions were written against.

maaend_reenable_spmed_if_updated is tested on its True / False paths only; its
None branch (spmed_fix_present cannot tell) is owned by another change.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import gameupdate as G
from ark_relay.statestore import StateStore

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def setup(*, version="v2.27.0-beta.5", master=True, off=("GiftOperator", "GearAssembly"),
          nodes=None):
    root = tmpdir()
    state, maaend, automas = root / "state", root / "MaaEnd", root / "AUTO-MAS"
    state.mkdir()
    maaend.mkdir()
    (maaend / "interface.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    if nodes is not None:
        (maaend / "resource" / "pipeline").mkdir(parents=True)
        (maaend / "resource" / "pipeline" / "nodes.json").write_text(
            json.dumps({"AutoUseSpMedicationQuickUse": nodes}), encoding="utf-8")
    f = automas / "data" / "59da8762" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    if master:
        f.parent.mkdir(parents=True)
        tasks = [{"taskName": n, "enabled": n not in off}
                 for n in ("DailyRewards", "GiftOperator", "GearAssembly",
                           "AutoCollect", "AutoUseSpMedication")]
        f.write_text(json.dumps({"instances": [{"id": "automas", "tasks": tasks}]}),
                     encoding="utf-8")
    cfg = SimpleNamespace(state_dir=state, maaend_dir=maaend, automas_dir=automas)
    return cfg, StateStore(state), f


def enabled(f):
    return {t["taskName"]: t["enabled"]
            for t in json.loads(f.read_text(encoding="utf-8"))["instances"][0]["tasks"]}


print("[maaend_reenable_if_updated]")
cfg, st, f = setup()
check("no reminder -> nothing", G.maaend_reenable_if_updated(cfg), "")
st.set("updates", "maaend_disabled_1_5_3",
       {"since": "v2.27.0-beta.5", "disabled": ["GiftOperator", "GearAssembly"]})
check("same version -> nothing", G.maaend_reenable_if_updated(cfg), "")
check("same version -> still off", enabled(f)["GiftOperator"], False)
check("same version -> reminder kept",
      bool(StateStore(cfg.state_dir).get("updates", "maaend_disabled_1_5_3")), True)
(cfg.maaend_dir / "interface.json").write_text(json.dumps({"version": "v2.27.0"}), encoding="utf-8")
msg = G.maaend_reenable_if_updated(cfg)
check("new version -> names both", "赠送干员礼物" in msg and "装备制造" in msg, True)
check("new version -> both on", (enabled(f)["GiftOperator"], enabled(f)["GearAssembly"]), (True, True))
check("new version -> reminder gone",
      StateStore(cfg.state_dir).get("updates", "maaend_disabled_1_5_3"), None)

cfg, st, f = setup(version="v2.27.0", master=False)
st.set("updates", "maaend_disabled_1_5_3", {"since": "v2.27.0-beta.5", "disabled": ["GiftOperator"]})
check("no master -> nothing", G.maaend_reenable_if_updated(cfg), "")
check("no master -> reminder kept",
      bool(StateStore(cfg.state_dir).get("updates", "maaend_disabled_1_5_3")), True)

print("[maaend_reenable_next_boot]")
cfg, st, f = setup(off=("AutoCollect",))
check("no reminder -> nothing", G.maaend_reenable_next_boot(cfg), "")
st.set("updates", "maaend_reenable_next_boot", {"tasks": ["AutoCollect"]})
check("reminder -> switched on", G.maaend_reenable_next_boot(cfg), "已开回：自动采集")
check("reminder -> on in master", enabled(f)["AutoCollect"], True)
check("reminder -> cleared", StateStore(cfg.state_dir).get("updates", "maaend_reenable_next_boot"), None)

cfg, st, f = setup(master=False)
st.set("updates", "maaend_reenable_next_boot", {"tasks": ["AutoCollect"]})
check("no master -> says so", "母本找不到" in G.maaend_reenable_next_boot(cfg), True)
check("no master -> reminder kept",
      bool(StateStore(cfg.state_dir).get("updates", "maaend_reenable_next_boot")), True)

print("[maaend_reenable_spmed_if_updated: True / False paths]")
BROKEN = {"recognition": {"param": {"all_of": ["YellowConfirmButtonType2",
                                               {"type": "OCR", "param": {}}]}}}
FIXED = {"recognition": {"param": {"all_of": ["YellowConfirmButtonType2",
                                              {"recognition": {"type": "OCR", "param": {}}}]}}}
cfg, st, f = setup(version="v2.28.0", off=("AutoUseSpMedication",), nodes=BROKEN)
st.set("updates", "maaend_disabled_spmed", {"since": "v2.27.0-beta.5", "tasks": ["AutoUseSpMedication"]})
check("new version but still broken -> nothing", G.maaend_reenable_spmed_if_updated(cfg), "")
check("still broken -> stays off", enabled(f)["AutoUseSpMedication"], False)
check("still broken -> reminder kept",
      bool(StateStore(cfg.state_dir).get("updates", "maaend_disabled_spmed")), True)

cfg, st, f = setup(version="v2.27.0-beta.5", off=("AutoUseSpMedication",), nodes=FIXED)
st.set("updates", "maaend_disabled_spmed", {"since": "v2.27.0-beta.5", "tasks": ["AutoUseSpMedication"]})
check("fixed but same version -> nothing", G.maaend_reenable_spmed_if_updated(cfg), "")
(cfg.maaend_dir / "interface.json").write_text(json.dumps({"version": "v2.28.0"}), encoding="utf-8")
check("fixed + new version -> on", "已经修好" in G.maaend_reenable_spmed_if_updated(cfg), True)
check("fixed -> on in master", enabled(f)["AutoUseSpMedication"], True)
check("fixed -> reminder gone", StateStore(cfg.state_dir).get("updates", "maaend_disabled_spmed"), None)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
