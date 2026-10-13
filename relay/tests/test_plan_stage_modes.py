#!/usr/bin/env python3
"""「明日安排」 shows MAA's stages the way AUTO-MAS v5.7 hands them to MAA.

task/MAA/AutoProxy.py: StageMode "Fixed" takes Stage/Stage_1..3/MedicineNumb
from the user's settings, any other StageMode is a PlanConfig uid; "-" is an
empty slot, "*" becomes "" (MAA: current / last stage). The old plan printed
「理智 -（固定）」 for an empty stage, the raw "*", the plan uid as the mode,
ignored Stage_1..3, and called 999 potions "unlimited" with no source.
Base data: the real 10-11 AUTO-MAS config (YW-4, Fixed, 999).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import plan

# next_plan's maintenance notices come from the official sites; nothing here is about
# them, and no relay test may reach the internet (run 38363145659 sat in those
# fetches on Windows until the 180 s limit).
plan.maintenance_lines = lambda day: []

FAILED: list[str] = []
REAL = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"
PLAN_UID = "c88cfe9e-6617-4fb8-9225-183ca571e3ae"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def maa_block(edit_info=None, edit_plan=None) -> list[str]:
    root = tmpdir()
    shutil.copytree(REAL, root / "a")
    cfg = root / "a" / "config"
    sf = cfg / "ScriptConfig.json"
    d = json.loads(sf.read_text(encoding="utf-8"))
    for inst in d["instances"]:
        node = d[inst["uid"]]
        if node["Info"].get("Name") == "MAA" and edit_info:
            for u in node["SubConfigsInfo"]["UserData"].values():
                if isinstance(u, dict):
                    u["Info"].update(edit_info)
    sf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    if edit_plan:
        pf = cfg / "PlanConfig.json"
        pd = json.loads(pf.read_text(encoding="utf-8"))
        edit_plan(pd[PLAN_UID])
        pf.write_text(json.dumps(pd, ensure_ascii=False), encoding="utf-8")
    text = plan.next_plan(root / "a")
    lines = text.splitlines()
    i = lines.index("▸ 明日方舟")
    out = []
    for ln in lines[i + 1:]:
        if not ln.startswith("　"):
            break
        out.append(ln.strip())
    return out


print("[real config: YW-4, Fixed, 999]")
got = maa_block()
require("stage line", "理智 YW-4（固定）" in got, repr(got))
require("999 is a number of potions, not 'unlimited'", "理智药最多 999 个" in got, repr(got))

print("[empty stage '-']")
got = maa_block({"Stage": "-"})
require("no '理智 -'", not any(b.startswith("理智 -") for b in got) and "理智 没设关卡（固定）" in got, repr(got))

print("[\"*\" and fallback stages]")
got = maa_block({"Stage": "*", "Stage_1": "1-7", "Stage_2": "-", "Stage_3": "CE-6"})
require("current/last stage, then the fallbacks in order",
        "理智 当前/上次关卡（固定），打不了依次换 1-7、CE-6" in got, repr(got))

print("[StageMode is a plan table (Weekly)]")


def weekly(node):
    node["Info"]["Mode"] = "Weekly"
    for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
        node[day].update({"Stage": f"S-{day[:3]}", "MedicineNumb": 2})


got = maa_block({"StageMode": PLAN_UID}, weekly)
day = plan._tomorrow().strftime("%A")[:3]
require("stage from tomorrow's row, plan named, no raw uid",
        f"理智 S-{day}（计划表「新 MAA 计划表」）" in got and not any(PLAN_UID in b for b in got), repr(got))
require("potions from the plan table, not the user's 999", "理智药最多 2 个" in got, repr(got))

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
