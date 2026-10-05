"""理智方案读写母本——不再依赖 AUTO-MAS 的快速配置。

2026-08-28：原实现写 MAS 用户配置的 `Task.SanityTaskType`，那条路要求
`Info.IfQuickConfig` 开着。快速配置被废掉后整个功能失效，这组用例
把新的口径钉住：母本里 `ProtocolSpace` / `AutoEssence` 谁 enabled 谁生效。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import sanity_plan

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def make(root: Path, *, essence_on: bool) -> Path:
    d = root / "automas" / "data" / "59da8762" / "Default" / "ConfigFile"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mxu-MaaEnd.json").write_text(json.dumps({
        "instances": [{
            "id": "automas", "name": "AUTO-MAS",
            "tasks": [
                {"id": "a1", "taskName": "DailyRewards", "enabled": True,
                 "optionValues": {}},
                {"id": "a2", "taskName": "ProtocolSpace", "enabled": not essence_on,
                 "optionValues": {
                     "ProtocolSpaceTab": {"type": "select",
                                          "caseName": "OperatorProgression"},
                     "OperatorProgression": {"type": "select", "caseName": "Promotions"},
                     "PromotionsRewardsSetOption": {"type": "select",
                                                    "caseName": "Protoset"},
                 }},
                {"id": "a3", "taskName": "AutoEssence", "enabled": essence_on,
                 "optionValues": {
                     "AutoEssenceChooseLocation": {"type": "checkbox",
                                                   "caseNames": ["VFTheHub"]},
                 }},
            ],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    return root / "automas"


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        am = make(root, essence_on=False)

        print("[读：协议空间]")
        r = sanity_plan.read(am)
        check("tab", r["tab"], "OperatorProgression")
        check("line", r["line"], "Promotions")
        check("有人话标签", "干员养成" in r["label"] and "干员进阶" in r["label"], True)

        print("\n[切到基质刷取]")
        ok, msg = sanity_plan.set_plan(am, "Essence", location="WLQingboStockade")
        check("写成功", ok, True)
        r = sanity_plan.read(am)
        check("tab 变了", r["tab"], "Essence")
        check("地点写进去了", r["locations"], ["WLQingboStockade"])
        check("标签是人话", r["label"], "基质刷取 → 清波寨")
        d = json.loads((am / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json")
                       .read_text(encoding="utf-8"))
        tasks = {x["taskName"]: x for x in d["instances"][0]["tasks"]}
        check("AutoEssence 开了", tasks["AutoEssence"]["enabled"], True)
        check("ProtocolSpace 关了", tasks["ProtocolSpace"]["enabled"], False)
        check("别的任务没被动", tasks["DailyRewards"]["enabled"], True)

        print("\n[切回协议空间]")
        ok, _ = sanity_plan.set_plan(am, "OperatorProgression", "SkillUp")
        check("写成功", ok, True)
        r = sanity_plan.read(am)
        check("line 变了", r["line"], "SkillUp")

        print("\n[拒绝造字段 / 拒绝造任务]")
        ok, msg = sanity_plan.set_plan(am, "WeaponProgression", "WeaponEXP")
        check("母本里没有 WeaponProgression 键就拒绝", ok, False)
        check("说清原因", "中继不会自己新建" in msg, True)

        am2 = make(root / "no_ess", essence_on=False)
        d2 = am2 / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json"
        dd = json.loads(d2.read_text(encoding="utf-8"))
        dd["instances"][0]["tasks"] = [
            x for x in dd["instances"][0]["tasks"] if x["taskName"] != "AutoEssence"]
        d2.write_text(json.dumps(dd, ensure_ascii=False), encoding="utf-8")
        ok, msg = sanity_plan.set_plan(am2, "Essence")
        check("母本里没有 AutoEssence 就拒绝（这正是那个静默故障）", ok, False)
        check("说清要先加任务", "拒绝新建" in msg, True)

        # Audit 2026-10-05 (C, sanity_plan.py:140-145): with both sanity tasks
        # on (mastercfg.MAAEND_TREE_TASKS says MaaEnd runs them in list order),
        # read() reported only the first, so tomorrow's plan never mentioned
        # essence farming (AutoEssence).
        print("\n[两项理智任务都开着]")
        am3 = make(root / "both", essence_on=False)
        f3 = am3 / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json"
        d3 = json.loads(f3.read_text(encoding="utf-8"))
        for x in d3["instances"][0]["tasks"]:
            if x["taskName"] in ("ProtocolSpace", "AutoEssence"):
                x["enabled"] = True
        f3.write_text(json.dumps(d3, ensure_ascii=False), encoding="utf-8")
        r = sanity_plan.read(am3)
        check("两项都报", [t["tab"] for t in r["tasks"]], ["OperatorProgression", "Essence"])
        check("标签里有基质刷取", "基质刷取 → 枢纽区" in r["label"], True)
        check("标签按母本顺序：协议空间在前",
              r["label"].index("干员养成") < r["label"].index("基质刷取"), True)
        check("顶层仍是第一项（老调用方不变）", r["tab"], "OperatorProgression")
        check("看得懂", r["understood"], True)
        # Counter-example: one task on keeps the old single label exactly.
        r1 = sanity_plan.read(am2)
        check("只开一项：标签不带「都开着」", "都开着" in r1["label"], False)
        check("只开一项：tasks 只有一个", len(r1["tasks"]), 1)

        print("\n[页签读不懂就说读不懂]")
        for x in d3["instances"][0]["tasks"]:
            if x["taskName"] == "ProtocolSpace":
                x["optionValues"]["ProtocolSpaceTab"] = {"type": "select", "caseName": "NewTabV3"}
        f3.write_text(json.dumps(d3, ensure_ascii=False), encoding="utf-8")
        r = sanity_plan.read(am3)
        check("不认识的页签：understood False", r["understood"], False)
        check("标签说读不懂并带原值", "读不懂" in r["label"] and "NewTabV3" in r["label"], True)
        check("另一项照常报", "基质刷取" in r["label"], True)

        print("\n[找不到母本]")
        check("返回空而不是炸", sanity_plan.read(root / "nowhere"), {})
        ok, _ = sanity_plan.set_plan(root / "nowhere", "Essence")
        check("写也不炸", ok, False)

    print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
