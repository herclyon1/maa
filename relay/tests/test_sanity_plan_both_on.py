"""Both sanity tasks on: the evening plan must name both, not only the first.

mastercfg.MAAEND_TREE_TASKS: MaaEnd puts ProtocolSpace and AutoEssence in the
same "sanity_sink" group and runs them in list order, so with both enabled the
first spends sanity and the second takes what is left. sanity_plan.read() took
on[0] only, so plan.py's 「理智用于 …」 line dropped 基质刷取 entirely.

Input is the real master copy from the machine (2026-09-25 05:47 evidence
bundle, logs/config/mxu-MaaEnd.json): AutoEssence on, ProtocolSpace off with its
real options (干员养成 → 干员经验). The both-on case flips only ProtocolSpace's
`enabled`, the switch MaaEnd's own task list exposes.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import sanity_plan

FX = Path(__file__).parent / "fixtures" / "maaend-master-2026-09-25" / "mxu-MaaEnd.json"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def automas_with(data: dict, name: str) -> Path:
    root = tmpdir() / name / "automas"
    d = root / "data" / "59da8762" / "Default" / "ConfigFile"
    d.mkdir(parents=True)
    (d / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


real = json.loads(FX.read_text(encoding="utf-8"))
tasks = [t for i in real["instances"] if i.get("id") == "automas" for t in i["tasks"]]
order = [t["taskName"] for t in tasks if t["taskName"] in sanity_plan.SANITY_TASKS]
check("真母本里协议空间排在基质刷取前面", order, ["ProtocolSpace", "AutoEssence"])

print("\n[真母本原样：只开基质刷取]")
r = sanity_plan.read(automas_with(real, "as-is"))
check("只写基质刷取", r.get("label"), "基质刷取 → 枢纽区")
check("没有第二项", "also" in r, False)

print("\n[两个都开：先协议空间，剩下的给基质刷取]")
both = json.loads(json.dumps(real))
for i in both["instances"]:
    for t in i.get("tasks") or []:
        if t["taskName"] == "ProtocolSpace":
            t["enabled"] = True
r = sanity_plan.read(automas_with(both, "both"))
check("第一项仍是协议空间", r.get("tab"), "OperatorProgression")
check("基质刷取没漏", "基质刷取" in (r.get("label") or ""), True)
check("两项都写、按顺序", r.get("label"), "干员养成 → 干员经验，再 基质刷取 → 枢纽区")
check("第二项单列", [p.get("tab") for p in r.get("also") or []], ["Essence"])

print("\n[协议空间开着但没选页：说没读到，不给空白]")
notab = json.loads(json.dumps(both))
for i in notab["instances"]:
    for t in i.get("tasks") or []:
        if t["taskName"] == "ProtocolSpace":
            t["optionValues"].pop("ProtocolSpaceTab")
r = sanity_plan.read(automas_with(notab, "notab"))
check("写明没读到", r.get("label"), "协议空间（没读到选的哪一页），再 基质刷取 → 枢纽区")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
