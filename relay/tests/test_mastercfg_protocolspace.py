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
    shown = mastercfg.MAAEND_SHOWN["ProtocolSpace"]

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
