"""Both sanity tasks on: the evening plan must name both, not only the first.

mastercfg.MAAEND_TREE_TASKS: MaaEnd puts ProtocolSpace and AutoEssence in the
same "sanity_sink" group and runs them in list order, so with both enabled the
first spends sanity and the second takes what is left. sanity_plan.read() took
on[0] only, so plan.py's 「理智用于 …」 line dropped 基质刷取 entirely.

Input is a real master copy already in the repo
(fixtures/maaend-2026-09-10/master-before.json): AutoEssence on, ProtocolSpace
off with its real options (干员养成 → 干员经验). The both-on case flips only
ProtocolSpace's `enabled`, the switch MaaEnd's own task list exposes.

Adapted from audit-maa-core-1006's test of the same name, which carried a
56 KB copy of the 2026-09-25 master for the same two facts; the labels are
the ones sanity_plan writes since the relay2-patchC-1005 version was chosen
(an unknown or missing ProtocolSpace tab is reported as unreadable).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import sanity_plan

FX = Path(__file__).parent / "fixtures" / "maaend-2026-09-10" / "master-before.json"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def automas_with(data: dict, name: str) -> Path:
    root = tmpdir() / name / "automas"
    d = root / "data" / "59da8762" / "Default" / "ConfigFile"
    d.mkdir(parents=True)
    (d / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


def edit_protocolspace(data: dict, fn) -> dict:
    out = json.loads(json.dumps(data))
    for ins in out["instances"]:
        for t in ins.get("tasks") or []:
            if t["taskName"] == "ProtocolSpace":
                fn(t)
    return out


real = json.loads(FX.read_text(encoding="utf-8"))
tasks = [t for i in real["instances"] if i.get("id") == "automas" for t in i["tasks"]]
order = [t["taskName"] for t in tasks if t["taskName"] in sanity_plan.SANITY_TASKS]
check("real master: ProtocolSpace is listed before AutoEssence", order,
      ["ProtocolSpace", "AutoEssence"])

print("\n[real master as is: only AutoEssence on]")
r = sanity_plan.read(automas_with(real, "as-is"))
check("label names essence farming only", r.get("label"), "基质刷取 → 藏剑谷 → 清波寨")
check("one task", [t["tab"] for t in r.get("tasks") or []], ["Essence"])
check("no 'both on' wording", "都开着" in (r.get("label") or ""), False)

print("\n[both on: ProtocolSpace first, AutoEssence gets what is left]")
both = edit_protocolspace(real, lambda t: t.__setitem__("enabled", True))
r = sanity_plan.read(automas_with(both, "both"))
check("top level still describes the first task", r.get("tab"), "OperatorProgression")
check("each task in list order", [t["tab"] for t in r.get("tasks") or []],
      ["OperatorProgression", "Essence"])
check("label names both, in order",
      r.get("label"),
      "干员养成 → 干员经验，用完再 基质刷取 → 藏剑谷 → 清波寨（2 项都开着，按母本顺序先打前面的）")
check("understood", r.get("understood"), True)

print("\n[ProtocolSpace on with no tab chosen: say it is unreadable, no blank]")
notab = edit_protocolspace(both, lambda t: t["optionValues"].pop("ProtocolSpaceTab"))
r = sanity_plan.read(automas_with(notab, "notab"))
check("not understood", r.get("understood"), False)
check("label says no tab was chosen, and still names the other task",
      r.get("label", "").split("，用完再 ")[:2],
      ["读不懂：ProtocolSpace 没有选页签，不知道理智会用在哪", "基质刷取 → 藏剑谷 → 清波寨（2 项都开着，按母本顺序先打前面的）"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
