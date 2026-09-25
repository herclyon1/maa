#!/usr/bin/env python3
"""The phone can read and write MaaEnd's ProtocolSpace (the other sanity sink).

Until 2026-09-25 the phone had essence farming only, so there was no way to pick
T-Creds (OperatorProgression = T-Creds). The definitions here are MaaEnd
v2.30.0-rc.1 `assets/tasks/ProtocolSpace.json` verbatim, with the zh_cn strings it
references; the master entry is the one on the game machine that day
(`mxu-MaaEnd.json`, ProtocolSpace disabled, several keys not yet present).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import mastercfg
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

FAILED: list[str] = []
DEFS = Path(__file__).resolve().parent / "fixtures" / "maaend-protocolspace-v2.30.0-rc.1"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'BAD'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def _fixture() -> tuple[Path, Path]:
    root = tmpdir()
    cfgdir = root / "automas" / "data" / "sid" / "Default" / "ConfigFile"
    cfgdir.mkdir(parents=True)
    days = [f"ProtocolSpaceSchedule{d}" for d in
            ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    (cfgdir / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": [
        {"taskName": "ProtocolSpace", "enabled": False, "optionValues": {
            "ProtocolSpaceSchedule": {"type": "checkbox", "caseNames": days},
            "ProtocolSpaceTeamChoose": {"type": "select", "caseName": "ProtocolSpaceTeamChooseDefault"},
            "ProtocolSpaceMode": {"type": "select", "caseName": "ByCount"},
            "ProtocolSpaceSuccessCount": {"type": "select", "caseName": "ProtocolSpaceSuccessCountUnlimited"},
            "ProtocolSpaceFailedCount": {"type": "select", "caseName": "ProtocolSpaceFailedCount3"},
            "ProtocolSpaceTab": {"type": "select", "caseName": "OperatorProgression"},
            "OperatorProgression": {"type": "select", "caseName": "OperatorEXP"},
            "OperatorEXPRewardsSetOption": {"type": "select", "caseName": "CognitiveCarriers"},
            "ProtocolSpaceLevel": {"type": "select", "caseName": "ProtocolSpaceLevel05"},
            "SkillUpRewardsSetOption": {"type": "select", "caseName": "Protohedron"},
            "PromotionsRewardsSetOption": {"type": "select", "caseName": "Protoset"},
            "WeaponProgression": {"type": "select", "caseName": "WeaponEXP"},
            "CrisisDrills": {"type": "select", "caseName": "AdvancedProgression1"},
        }},
    ]}]}, ensure_ascii=False), encoding="utf-8")
    maaend = root / "maaend"
    shutil.copytree(DEFS, maaend)
    return root / "automas", maaend


def main() -> int:
    automas, maaend = _fixture()
    # The whole tree: every option ProtocolSpace.json itself defines. (The
    # AutoFight* sub-options live in another upstream file, not in this fixture.)
    shown = list(mastercfg._jsonc(DEFS / "tasks" / "ProtocolSpace.json")["option"])

    print("=== 1. read ===")
    got = mastercfg.read_maaend(automas, maaend)
    v, o, lb = got["values"], got["options"], got["labels"]
    missing = [k for k in shown if f"ProtocolSpace/{k}" not in v]
    require("every shown item has a value (defaults for keys not in the master yet)",
            not missing, f"missing {missing}")
    bad = [k for k in got["untranslated"] if k.startswith("ProtocolSpace/")]
    require("every item has its official Chinese name", not bad, f"untranslated {bad}")
    require("task switch reads off", v.get("ProtocolSpace/@enabled") is False)
    require("task label is MaaEnd's own", lb.get("ProtocolSpace/@enabled") == "⚔️协议空间",
            repr(lb.get("ProtocolSpace/@enabled")))
    ops = dict((val, name) for name, val in o.get("ProtocolSpace/OperatorProgression") or [])
    require("T-Creds is a choice under operator progression, with a Chinese name",
            "T-Creds" in ops and ops["T-Creds"] != "T-Creds", repr(ops))
    tabs = [val for _, val in o.get("ProtocolSpace/ProtocolSpaceTab") or []]
    require("three tabs", tabs == ["OperatorProgression", "WeaponProgression", "CrisisDrills"],
            repr(tabs))
    # Not in the master and no declared default: the current value is unknown,
    # but the choices still reach the page.
    require("weapon tune A/B offered although the master lacks it",
            [val for _, val in o.get("ProtocolSpace/WeaponTuneRewardsSetOption") or []]
            == ["CastDie", "HeavyCastDie"],
            repr(o.get("ProtocolSpace/WeaponTuneRewardsSetOption")))

    for k in ("ProtocolSpaceFailedCount", "ProtocolSpaceObtainModeClaim", "SupplyPlanLimits",
              "ProtocolSpaceSpMedicationExpireWithinDays", "ProtocolSpaceTeamChoose"):
        require(f"{k} is on the page too", f"ProtocolSpace/{k}" in v)
    sp = v.get("ProtocolSpace/SupplyPlanLimits") or {}
    boxes = dict((name, lab) for lab, name in got["inputs"].get("ProtocolSpace/SupplyPlanLimits") or [])
    require("supply limits: 15 boxes with their defaults",
            len(sp) == 15 and sp.get("SupplyPlanLimit_T_CREDS") == "3580000", repr(sp)[:200])
    require("supply limit labels are plain Chinese, no icon markup",
            boxes.get("SupplyPlanLimit_T_CREDS") == "折金票"
            and not any("![" in x for x in boxes.values()), repr(boxes)[:200])
    kids = got["children"]
    require("mode TargetInventory opens the claim mode and the limits",
            kids.get("ProtocolSpace/ProtocolSpaceMode", {}).get("TargetInventory")
            == ["ProtocolSpace/ProtocolSpaceObtainModeClaim", "ProtocolSpace/SupplyPlanLimits"],
            repr(kids.get("ProtocolSpace/ProtocolSpaceMode")))
    require("a switch's children are keyed true/false",
            "true" in kids.get("ProtocolSpace/AutoFightSetting", {}),
            repr(kids.get("ProtocolSpace/AutoFightSetting")))
    require("roots are the task's own top-level options",
            got["roots"].get("ProtocolSpace") == [
                "ProtocolSpace/ProtocolSpaceSchedule", "ProtocolSpace/AutoFightSetting",
                "ProtocolSpace/ProtocolSpaceTeamChoose", "ProtocolSpace/ProtocolSpaceMode"],
            repr(got["roots"].get("ProtocolSpace")))

    print("\n=== 2. write ===")
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "ProtocolSpace/OperatorProgression", "T-Creds")
    now = mastercfg.read_maaend(automas, maaend)["values"]
    require("switch the line to T-Creds, read back",
            ok and now["ProtocolSpace/OperatorProgression"] == "T-Creds", msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "ProtocolSpace/@enabled", True)
    now = mastercfg.read_maaend(automas, maaend)["values"]
    require("turn the task on, read back", ok and now["ProtocolSpace/@enabled"] is True, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "ProtocolSpace/ProtocolSpaceObtainMode", "ObtainScaling1")
    now = mastercfg.read_maaend(automas, maaend)["values"]
    require("a key the master lacks is created from the definition and written",
            ok and now["ProtocolSpace/ProtocolSpaceObtainMode"] == "ObtainScaling1", msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "ProtocolSpace/WeaponTuneRewardsSetOption", "HeavyCastDie")
    now = mastercfg.read_maaend(automas, maaend)["values"]
    require("a key with no declared default is created holding a declared value",
            ok and now["ProtocolSpace/WeaponTuneRewardsSetOption"] == "HeavyCastDie", msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "ProtocolSpace/CrisisDrills", "AdvancedProgression9")
    require("an undeclared value on a missing-default key is still refused", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "ProtocolSpace/OperatorProgression", "Gold")
    require("a value the definition does not declare is refused", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "ProtocolSpace/SupplyPlanLimits",
                                     {"SupplyPlanLimit_T_CREDS": "5000000"})
    now = mastercfg.read_maaend(automas, maaend)["values"]["ProtocolSpace/SupplyPlanLimits"]
    require("one supply limit box written, the others keep their defaults",
            ok and now["SupplyPlanLimit_T_CREDS"] == "5000000"
            and now["SupplyPlanLimit_CAST_DIE"] == "45", msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "ProtocolSpace/SupplyPlanLimits",
                                     {"SupplyPlanLimit_T_CREDS": "lots"})
    require("a box value failing the declared pattern is refused", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "ProtocolSpace/SupplyPlanLimits",
                                     {"SupplyPlanLimit_GOLD": "1"})
    require("a box the definition does not declare is refused", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "ProtocolSpace/AutoFightSetting", "false")
    now = mastercfg.read_maaend(automas, maaend)["values"]
    require("a switch takes the text false as false",
            ok and now["ProtocolSpace/AutoFightSetting"] is False, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "ProtocolSpace/AutoFightSetting", "maybe")
    require("a switch refuses anything but true/false", not ok, msg)
    doc = json.loads(next(automas.glob("data/*/Default/ConfigFile/mxu-MaaEnd.json"))
                     .read_text(encoding="utf-8"))
    ov = doc["instances"][0]["tasks"][0]["optionValues"]
    require("the file itself holds T-Creds",
            ov["OperatorProgression"] == {"type": "select", "caseName": "T-Creds"}, repr(ov["OperatorProgression"]))

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
