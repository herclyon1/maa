"""The sanity plan: both tasks on, the master copy, reward names, the weekday and the span.

One part per former file, each run on its own (tests/_parts.py): test_sanity_plan_both_on.py, test_sanity_plan_master.py, test_sanity_plan_reward_names.py, test_sanity_plan_weekday.py, test_sanity_span.py.
"""
from __future__ import annotations

# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_sanity_plan_both_on():
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

    Formerly test_sanity_plan_both_on.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import sanity_plan

    FX = Path(__file__).parent / "fixtures" / "maaend-2026-09-10" / "master-before.json"


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
          "干员养成 → 干员经验 → 高级认知载体、初级认知载体，用完再 基质刷取 → 藏剑谷 → 清波寨（2 项都开着，按母本顺序先打前面的）")
    check("understood", r.get("understood"), True)

    print("\n[ProtocolSpace on with no tab chosen: say it is unreadable, no blank]")
    notab = edit_protocolspace(both, lambda t: t["optionValues"].pop("ProtocolSpaceTab"))
    r = sanity_plan.read(automas_with(notab, "notab"))
    check("not understood", r.get("understood"), False)
    check("label says no tab was chosen, and still names the other task",
          r.get("label", "").split("，用完再 ")[:2],
          ["读不懂：ProtocolSpace 没有选页签，不知道理智会用在哪", "基质刷取 → 藏剑谷 → 清波寨（2 项都开着，按母本顺序先打前面的）"])


def _part_sanity_plan_master():
    """理智方案读写母本——不再依赖 AUTO-MAS 的快速配置。

2026-08-28：原实现写 MAS 用户配置的 `Task.SanityTaskType`，那条路要求
`Info.IfQuickConfig` 开着。快速配置被废掉后整个功能失效，这组用例
把新的口径钉住：母本里 `ProtocolSpace` / `AutoEssence` 谁 enabled 谁生效。

    Formerly test_sanity_plan_master.py.
    """
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.weekly import sanity_plan

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

            print("\n[基质刷取在「目标选择」模式：写地点没用，拒绝，不替他切回随机（审计 11-08 D-13）]")
            mf = am / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json"
            doc = json.loads(mf.read_text(encoding="utf-8"))
            ess = next(x for x in doc["instances"][0]["tasks"] if x["taskName"] == "AutoEssence")
            ess["optionValues"]["AutoEssenceMenu"] = {"type": "select", "caseName": "Target"}
            mf.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            before = mf.read_text(encoding="utf-8")
            ok, msg = sanity_plan.set_plan(am, "Essence", location="VFTheHub")
            check("目标选择 + 地点：拒绝", ok, False)
            check("……说清楚是哪种模式、为什么不生效", ("目标选择" in msg, "随机模式" in msg), (True, True))
            check("……母本一个字没动", mf.read_text(encoding="utf-8"), before)
            ok, _ = sanity_plan.set_plan(am, "Essence")
            check("目标选择、不写地点：照常", ok, True)
            check("……读出来的标签说目标选择，不说那个不生效的地点", sanity_plan.read(am)["label"], "基质刷取 → 目标选择")
            ess["optionValues"]["AutoEssenceMenu"] = {"type": "select", "caseName": "Random"}
            mf.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            ok, _ = sanity_plan.set_plan(am, "Essence", location="VFTheHub")
            check("随机模式 + 地点：照常写", (ok, sanity_plan.read(am)["locations"]), (True, ["VFTheHub"]))

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


def _part_sanity_plan_reward_names():
    """The sanity plan speaks MaaEnd's own reward-set names, not AUTO-MAS's A / B.

Audit 2026-10-13 (weekly block, finding 1): sanity_plan keyed its reward table by
"RewardsSetA" / "RewardsSetB" - the names of AUTO-MAS's quick-config field
(fixtures/automas-models/config.py.txt:286-288), which this module does not use.
MaaEnd's master copy holds one case per line, defined in ProtocolSpace.json as
f"{line}RewardsSetOption" (fixtures/maaend-protocolspace-v2.30.0-rc.1,
tasks/ProtocolSpace.json:898-1010; Chinese labels in locales/interface/zh_cn.json).
On the machine's own master (fixtures/maaend-2026-09-10/master-before.json:
OperatorEXPRewardsSetOption = CognitiveCarriers) the old code:
- named no reward item (read()["item"] == ""),
- refused every value MaaEnd defines ("只能 RewardsSetA / RewardsSetB"),
- accepted "RewardsSetA", wrote a case MaaEnd does not define, and the phone's
  answer said ✅ (phone/inbox.py _apply).

MaaEnd's install is found the way production finds it: AUTO-MAS's own config
(fixtures/automas-config-2026-10-11) with the MaaEnd script's path pointed at
the v2.30.0-rc.1 definition fixture.

    Formerly test_sanity_plan_reward_names.py.
    """

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg
    from ark_relay.features.phone import inbox
    from ark_relay.features.weekly import sanity_plan

    FX = Path(__file__).resolve().parent / "fixtures"
    MASTER = FX / "maaend-2026-09-10" / "master-before.json"
    MAAEND = FX / "maaend-protocolspace-v2.30.0-rc.1"
    AUTOMAS_FX = FX / "automas-config-2026-10-11" / "config"

    FAILED: list[str] = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
        if not ok:
            FAILED.append(name)


    def setup(name: str) -> Path:
        """The real master with ProtocolSpace on, under an AUTO-MAS dir whose
    ScriptConfig points the MaaEnd script at the definition fixture."""
        automas = tmpdir() / name / "automas"
        cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        data = json.loads(MASTER.read_text(encoding="utf-8"))
        for t in data["instances"][0]["tasks"]:
            if t["taskName"] == "ProtocolSpace":
                t["enabled"] = True
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        shutil.copytree(AUTOMAS_FX, automas / "config")
        sc = automas / "config" / "ScriptConfig.json"
        d = json.loads(sc.read_text(encoding="utf-8"))
        for inst in d["instances"]:
            info = d[inst["uid"]]["Info"]
            if "maaend" in str(info.get("Path", "")).lower():
                info["Path"] = str(MAAEND)
        sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return automas


    def protocolspace(automas: Path) -> dict:
        f = next((automas / "data").glob("*/Default/ConfigFile/mxu-MaaEnd.json"))
        d = json.loads(f.read_text(encoding="utf-8"))
        return next(t for t in d["instances"][0]["tasks"] if t["taskName"] == "ProtocolSpace")["optionValues"]


    print("[the reward table names exactly MaaEnd's cases, with MaaEnd's own Chinese]")
    opts, _ = mastercfg._maaend_defs(MAAEND)
    zh = json.loads((MAAEND / "locales" / "interface" / "zh_cn.json").read_text(encoding="utf-8"))
    want_table = {}
    for key, opt in opts.items():
        if key.endswith("RewardsSetOption"):
            line = key[: -len("RewardsSetOption")]
            for c in opt["cases"]:
                label = zh[c["label"][1:]]
                want_table[(line, c["name"])] = label.split(".", 1)[1]   # drop the "A." / "B." prefix
    check("REWARD == MaaEnd's cases and labels", sanity_plan.REWARD, want_table)

    print("\n[read(): the machine's master names the item that drops]")
    am = setup("read")
    r = sanity_plan.read(am)
    check("line", r.get("line"), "OperatorEXP")
    check("rewards_set is MaaEnd's case", r.get("rewards_set"), "CognitiveCarriers")
    check("item named", r.get("item"), "高级认知载体、初级认知载体")
    check("label ends with the item",
          r.get("label", "").split("，用完再 ")[0], "干员养成 → 干员经验 → 高级认知载体、初级认知载体")

    print("\n[set_plan(): a case MaaEnd defines is accepted and written]")
    ok, msg = sanity_plan.set_plan(am, "OperatorProgression", "OperatorEXP", "AdvancedCombatRecord")
    check("accepted", ok, True)
    check("written as MaaEnd's case",
          protocolspace(am).get("OperatorEXPRewardsSetOption"), {"type": "select", "caseName": "AdvancedCombatRecord"})
    check("read() now names B", sanity_plan.read(am).get("item"), "高级作战记录")
    ok, msg = sanity_plan.set_plan(am, "OperatorProgression", "Promotions", "Protodisk")
    check("Promotions + Protodisk accepted", ok, True)
    check("written", protocolspace(am).get("PromotionsRewardsSetOption", {}).get("caseName"), "Protodisk")

    print("\n[set_plan(): a value MaaEnd does not define is refused, nothing written]")
    am2 = setup("refuse")
    before = protocolspace(am2)
    ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "OperatorEXP", "RewardsSetA")
    check("AUTO-MAS's RewardsSetA refused", ok, False)
    check("refusal names MaaEnd's cases", "AdvancedCombatRecord" in msg and "CognitiveCarriers" in msg, True)
    check("master untouched", protocolspace(am2), before)
    ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "OperatorEXP", "Protodisk")
    check("another line's case refused", ok, False)
    ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "T-Creds", "CognitiveCarriers")
    check("a line with no reward set refuses any", ok, False)
    check("master still untouched", protocolspace(am2), before)

    print("\n[set_plan(): MaaEnd's definition unreadable -> refuse rather than guess]")
    am3 = setup("nodefs")
    sc = am3 / "config" / "ScriptConfig.json"
    d = json.loads(sc.read_text(encoding="utf-8"))
    for inst in d["instances"]:
        info = d[inst["uid"]]["Info"]
        if str(info.get("Path", "")) == str(MAAEND):
            info["Path"] = str(tmpdir() / "no-maaend-here")
    sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    ok, msg = sanity_plan.set_plan(am3, "OperatorProgression", "OperatorEXP", "CognitiveCarriers")
    check("refused", ok, False)
    check("says the definition could not be read", "读不到" in msg, True)

    print("\n[the phone's answer: no ✅ for a value MaaEnd does not define]")
    am4 = setup("phone")
    box = inbox.Inbox(tmpdir() / "state", automas_dir=am4)
    out = box._apply([{"action": "sanity_plan", "tab": "OperatorProgression",
                       "line": "OperatorEXP", "rewards_set": "RewardsSetA"}])
    check("answer is a refusal", [o.startswith("✗ 理智方案") for o in out], [True])
    out = box._apply([{"action": "sanity_plan", "tab": "OperatorProgression",
                       "line": "OperatorEXP", "rewards_set": "AdvancedCombatRecord"}])
    check("a real case gets ✅", [o.startswith("✅ 理智方案") for o in out], [True])

    print("\n[orders run in the order written (11-08 [D-08])]")
    _saved_ac = inbox.apply_command
    inbox.apply_command = lambda c: (True, "first")
    out = box._apply([{"action": "skip_today", "queue": "x"},
                      {"action": "sanity_plan", "tab": "OperatorProgression",
                       "line": "OperatorEXP", "rewards_set": "AdvancedCombatRecord"}])
    inbox.apply_command = _saved_ac
    check("the earlier order answers first", [o.startswith("✅ first") for o in out], [True, False])

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    sys.exit(1 if FAILED else 0)


def _part_sanity_plan_weekday():
    """Tomorrow's sanity line honours MaaEnd's weekday ticks for the sanity tasks.

Audit 2026-10-13 (weekly block, finding 2): sanity_plan.read() took every
enabled ProtocolSpace / AutoEssence as "runs tomorrow", and plan.py printed
「理智用于 …」 for it, though MaaEnd runs a task only on the weekdays ticked in
its f"{task}Schedule" option (the master holds ProtocolSpaceSchedule /
AutoEssenceSchedule; with none saved MaaEnd uses the option's default_case).
plan._maaend_extra_bits already applies that rule to AutoCollect.

Input is the machine's own master (fixtures/maaend-2026-09-10/master-before.json:
AutoEssence on, ProtocolSpace off, all seven days ticked), with MaaEnd's
definitions from the same day's install fixture (AutoEssenceSchedule default_case
is all seven days). Checked through next_plan (the 「明日安排」 text), with the
machine's AUTO-MAS config (fixtures/automas-config-2026-10-11) pointing MaaEnd at
a temp install.

    Formerly test_sanity_plan_weekday.py.
    """

    import json
    import shutil
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.names import GAME_ZH

    FX = Path(__file__).resolve().parent / "fixtures"
    MASTER = FX / "maaend-2026-09-10" / "master-before.json"
    MAAEND_FX = FX / "maaend-2026-09-10"
    AUTOMAS_FX = FX / "automas-config-2026-10-11" / "config"
    DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

    FAILED: list[str] = []

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and run 38363145659 (Windows) sat in those fetches until the 180 s limit.
    plan.maintenance_lines = lambda day: []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
        if not ok:
            FAILED.append(name)


    def setup(name: str, edit) -> Path:
        root = tmpdir() / name
        automas = root / "automas"
        cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        data = json.loads(MASTER.read_text(encoding="utf-8"))
        for t in data["instances"][0]["tasks"]:
            if t["taskName"] == "AutoCollect":
                t["enabled"] = False         # keeps the gathering line out of the way
            edit(t)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        maaend = root / "maaend"
        maaend.mkdir()
        shutil.copy(MAAEND_FX / "interface.json", maaend / "interface.json")
        shutil.copytree(MAAEND_FX / "tasks", maaend / "tasks")
        shutil.copytree(AUTOMAS_FX, automas / "config")
        sc = automas / "config" / "ScriptConfig.json"
        d = json.loads(sc.read_text(encoding="utf-8"))
        for inst in d["instances"]:
            info = d[inst["uid"]]["Info"]
            if "maaend" in str(info.get("Path", "")).lower():
                info["Path"] = str(maaend)
        sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return automas


    def sanity_lines(automas: Path, tomorrow: datetime) -> list[str]:
        """The sanity line(s) of the Endfield (MaaEnd) block in next_plan."""
        plan._tomorrow = lambda: tomorrow
        out, inside = [], False
        for ln in plan.next_plan(automas).splitlines():
            if ln.startswith("▸"):
                inside = ln == f"▸ {GAME_ZH['MaaEnd']}"
            elif inside and "理智" in ln:
                out.append(ln.strip())
        return out


    def days_but(task: str, skip: str):
        def edit(t):
            if t["taskName"] == task:
                t["optionValues"][f"{task}Schedule"]["caseNames"] = [
                    f"{task}Schedule{d}" for d in DAYS if d != skip]
        return edit


    def both_on(t):
        if t["taskName"] == "ProtocolSpace":
            t["enabled"] = True


    TUESDAY = datetime(2026, 10, 13, 12, tzinfo=SERVER_TZ)
    WEDNESDAY = datetime(2026, 10, 14, 12, tzinfo=SERVER_TZ)

    print("[the machine's master as is: AutoEssence on every day]")
    am = setup("as-is", lambda t: None)
    check("Tuesday names essence farming", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

    print("\n[AutoEssence not ticked for Tuesday]")
    am = setup("no-tue", days_but("AutoEssence", "Tuesday"))
    got = sanity_lines(am, TUESDAY)
    check("Tuesday: not 「理智用于 基质刷取」", any(ln.startswith("理智用于") for ln in got), False)
    check("Tuesday: says the sanity task sits the day out", len(got) == 1 and "不跑" in got[0], True)
    check("Wednesday: still runs", sanity_lines(am, WEDNESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

    print("\n[both on, ProtocolSpace not ticked for Tuesday: only essence farming]")
    def both_no_tue_ps(t):
        both_on(t)
        days_but("ProtocolSpace", "Tuesday")(t)
    am = setup("both-no-tue", both_no_tue_ps)
    check("Tuesday: essence farming only", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])
    got = sanity_lines(am, WEDNESDAY)
    check("Wednesday: both, ProtocolSpace first",
          len(got) == 1 and got[0].startswith("理智用于 干员养成") and "基质刷取" in got[0], True)

    print("\n[no AutoEssenceSchedule saved: MaaEnd's default_case (all seven days)]")
    am = setup("default", lambda t: t["optionValues"].pop("AutoEssenceSchedule", None)
               if t["taskName"] == "AutoEssence" else None)
    check("Tuesday names essence farming", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

    print("\n[the default_case itself comes from MaaEnd's definition]")
    from ark_relay.features.weekly import sanity_plan
    bare = {"taskName": "AutoEssence", "optionValues": {}}
    check("all seven days from tasks/AutoEssence", sanity_plan._ticked_days(bare, MAAEND_FX), list(range(7)))
    check("no definition -> unknown (kept by read)", sanity_plan._ticked_days(bare, None), None)
    am = setup("say", days_but("AutoEssence", "Tuesday"))
    check("the sit-out line", sanity_lines(am, TUESDAY),
          ["理智任务明天（周二）不跑（基质刷取仅周一、三、四、五、六、日 跑）"])

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    sys.exit(1 if FAILED else 0)


def _part_sanity_span():
    """理智/波片的「消耗」和「剩余」不能漏掉最后一趟。

两个游戏同一个毛病：读数都在每趟**开打前**播报。
* 终末地 09-03：五次领取只看到五个读数、四个步长，相邻差求和得 320，真花 400。
  正确写法是「趟数 × 步长」。
* 终末地 09-04：只刷一趟，一个读数零个步长，这一条自己算不出，
  要拿当天上一条的余量来补（116 → 37）。
* 鸣潮 09-04：收尾那行写的是 `current stamina: 37 must_use completed`，
  原正则只认 `not enough to continue`，于是最后一趟整个漏掉，
  报成「消耗 159、剩余 77」，真实是 199 和 37。

    Formerly test_sanity_span.py.
    """
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_maaend, collector_okww
    from ark_relay.features.report import report


    def chk(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    # 终末地：五次领取，读数 979→659
    end5 = "\n".join([
        "[2026-09-03 09:00:00.000] 任务开始: 🎱基质刷取",
        *[f"[2026-09-03 09:0{i}:00.000] 当前理智 {979 - 80 * i}/360" for i in range(5)],
        *["[2026-09-03 09:06:00.000] ✅已完成一次基质刷取"] * 5,
        "[2026-09-03 09:07:00.000] 任务完成: 🎱基质刷取",
    ])
    chk("终末地五趟消耗", collector_maaend._maaend_farm(end5).get("maaend_sanity_spent"), 400)

    # 终末地：只刷一趟，一个读数——这一条算不出，交给上层补
    end1 = "\n".join([
        "[2026-09-04 09:42:45.603] 任务开始: 🎱基质刷取",
        "[2026-09-04 09:44:00.149] ✅已完成一次基质刷取",
        "[2026-09-04 09:44:45.736] 当前理智 37/360",
        "[2026-09-04 09:44:49.380] 任务完成: 🎱基质刷取",
    ])
    one = collector_maaend._maaend_farm(end1)
    chk("单趟不硬编数字", one.get("maaend_sanity_spent"), None)
    chk("单趟留了口子", one.get("maaend_sanity_runs_only"), 1)
    es = [{"script": "MaaEnd", "sanity": 116, "raw": {}},
          {"script": "MaaEnd", "sanity": 37, "raw": dict(one)}]
    report._fill_single_run_sanity(es)
    chk("单趟由上一条补出", es[1]["raw"].get("maaend_sanity_spent"), 79)

    # 鸣潮：收尾用的是另一种句式
    ok = "\n".join([
        "info_set current_stamina 236", "info_set current_stamina 157",
        "info_set current_stamina 77",
        "current stamina: 37 must_use completed, no need to use back_up",
    ])
    got = collector_okww._okww_stamina(ok) if hasattr(collector_okww, "_okww_stamina") else None
    if got is None:
        tail = collector_okww._OKWW_STAMINA_END.findall(ok)
        chk("鸣潮收尾读数认得出", tail[-1] if tail else None, "37")
        series = [int(m.group(1)) for m in collector_okww._OKWW_STAMINA.finditer(ok)] + [int(tail[-1])]
        chk("鸣潮消耗", sum(a - b for a, b in zip(series, series[1:], strict=False) if a > b), 199)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_sanity_plan_both_on, _part_sanity_plan_master, _part_sanity_plan_reward_names, _part_sanity_plan_weekday, _part_sanity_span]))
