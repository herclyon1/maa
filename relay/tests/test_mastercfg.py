"""The master copies: JSONC strings, protocol space.

One part per former file, each run on its own (tests/_parts.py): test_mastercfg.py, test_mastercfg_jsonc_strings.py, test_mastercfg_protocolspace.py.
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


def _part_main():
    """母本配置的读写。

守的是这次重构的前提：终末地和鸣潮改的必须是**脚本自己那份**，
而且写之前要挡住三样东西——不存在的任务、不存在的选项、不认识的取值。

    Formerly test_mastercfg.py.
    """
    #!/usr/bin/env python3

    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg

    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def _fixture() -> tuple[Path, Path]:
        """造一份假的 AUTO-MAS 母本目录 + 假的 MaaEnd 安装目录。"""
        root = tmpdir()
        cfgdir = root / "automas" / "data" / "sid" / "Default" / "ConfigFile"
        cfgdir.mkdir(parents=True)
        (cfgdir / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": [
            {"taskName": "AutoEssence", "enabled": True, "optionValues": {
                "AutoEssenceDoOverride": {"type": "switch", "value": True},
                "AutoEssenceObtainMode": {"type": "select", "caseName": "ObtainScaling1"},
                "AutoEssenceChooseLocation": {"type": "checkbox", "caseNames": ["VFTheHub"]},
                "AutoEssenceRepeatCount": {"type": "input",
                                           "values": {"AutoEssenceRepeatCountValue": "5"}},
            }},
            {"taskName": "AutoCollect", "enabled": False, "optionValues": {}},
        ]}]}, ensure_ascii=False), encoding="utf-8")
        (cfgdir / "DailyTask.json").write_text(json.dumps({
            "Which to Farm": "Simulation Challenge",
            "Material Selection": "Shell Credit",
            "Which Forgery Challenge to Farm": 1,
            "Which Tacet Suppression to Farm": 1,
        }, ensure_ascii=False), encoding="utf-8")
        (cfgdir / "NightmareNestTask.json").write_text(
            json.dumps({"Only Farm These Nests": "落渊南丘"}, ensure_ascii=False),
            encoding="utf-8")

        maaend = root / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        (maaend / "locales" / "interface").mkdir(parents=True)
        (maaend / "tasks" / "AutoEssence.json").write_text("""{
    // 带注释的 JSON，解析器要能吃掉这一行
    // task 是数组，不是对象——照真文件的形状写
    "task": [{"name": "AutoEssence", "label": "$task.AutoEssence.label",
              "option": ["AutoEssenceDoOverride", "AutoEssenceObtainMode",
                         "AutoEssenceChooseLocation", "AutoEssenceRepeatCount"]}],
    "option": {
        "AutoEssenceDoOverride": {"type": "switch",
            "label": "$option.AutoEssenceDoOverride.label"},
        "AutoEssenceObtainMode": {"type": "select",
            "label": "$option.AutoEssenceObtainMode.label",
            "cases": [{"name": "Discard", "label": "$a"},
                      {"name": "ObtainScaling1", "label": "$b"},
                      {"name": "ObtainScaling2", "label": "$c"}]},
        "AutoEssenceChooseLocation": {"type": "checkbox", "label": "$loc",
            "cases": [{"name": "VFTheHub", "label": "$global.region.TheHub"},
                      {"name": "WLQingboStockade", "label": "$global.region.QingboStockade"}]},
        "AutoEssenceRepeatCount": {"type": "input", "label": "$cnt"}
    }
}""", encoding="utf-8")
        (maaend / "locales" / "interface" / "zh_cn.json").write_text(json.dumps({
            "task.AutoEssence.label": "🎱基质刷取",
            "option.AutoEssenceDoOverride.label": "使用刻写券",
            "option.AutoEssenceObtainMode.label": "领取方式",
            "a": "不领取（仅刷素材）", "b": "单倍领取", "c": "双倍领取",
            "loc": "地区选择", "cnt": "循环执行",
            "global.region.TheHub": "枢纽区", "global.region.QingboStockade": "清波寨",
        }, ensure_ascii=False), encoding="utf-8")
        return root / "automas", maaend


    def main() -> int:
        automas, maaend = _fixture()

        print("=== 1. 终末地：读母本 ===")
        got = mastercfg.read_maaend(automas, maaend)
        v, o, lb = got["values"], got["options"], got["labels"]
        require("刻写券开关读得到（这次重构的由头）",
              v.get("AutoEssence/AutoEssenceDoOverride") is True)
        require("刻写券用官方中文名",
              lb.get("AutoEssence/AutoEssenceDoOverride") == "使用刻写券",
              f"实际 {lb.get('AutoEssence/AutoEssenceDoOverride')!r}")
        require("领取方式给出三个候选且是中文",
              o.get("AutoEssence/AutoEssenceObtainMode")
              == [["不领取（仅刷素材）", "Discard"], ["单倍领取", "ObtainScaling1"],
                  ["双倍领取", "ObtainScaling2"]])
        require("地区是多选，值是列表",
              v.get("AutoEssence/AutoEssenceChooseLocation") == ["VFTheHub"])
        require("地区中文名走 $global.region 引用",
              o.get("AutoEssence/AutoEssenceChooseLocation")
              == [["枢纽区", "VFTheHub"], ["清波寨", "WLQingboStockade"]])
        require("循环次数按输入框读，保持字符串",
              v.get("AutoEssence/AutoEssenceRepeatCount") == "5")
        require("任务开关读得到", v.get("AutoCollect/@enabled") is False)

        print("\n=== 2. 终末地：写母本 ===")
        ok, msg = mastercfg.write_maaend(automas, maaend,
                                         "AutoEssence/AutoEssenceDoOverride", False)
        now = mastercfg.read_maaend(automas, maaend)["values"]
        require("关掉刻写券，回读为假", ok and now["AutoEssence/AutoEssenceDoOverride"] is False, msg)
        ok, msg = mastercfg.write_maaend(automas, maaend,
                                         "AutoEssence/AutoEssenceObtainMode", "ObtainScaling2")
        now = mastercfg.read_maaend(automas, maaend)["values"]
        require("改成双倍领取", ok and now["AutoEssence/AutoEssenceObtainMode"] == "ObtainScaling2", msg)
        ok, msg = mastercfg.write_maaend(automas, maaend,
                                         "AutoEssence/AutoEssenceRepeatCount", 9)
        now = mastercfg.read_maaend(automas, maaend)["values"]
        require("次数写进输入框且仍是字符串",
              ok and now["AutoEssence/AutoEssenceRepeatCount"] == "9", msg)
        ok, msg = mastercfg.write_maaend(automas, maaend, "AutoCollect/@enabled", True)
        now = mastercfg.read_maaend(automas, maaend)["values"]
        require("任务开关能开回来", ok and now["AutoCollect/@enabled"] is True, msg)

        print("\n=== 3. 终末地：该拒绝的要拒绝（826 的三条） ===")
        ok, msg = mastercfg.write_maaend(automas, maaend, "NoSuchTask/@enabled", True)
        require("不存在的任务→拒绝", not ok, msg)
        ok, msg = mastercfg.write_maaend(automas, maaend, "AutoEssence/NoSuchOption", 1)
        require("不存在的选项→拒绝", not ok, msg)
        ok, msg = mastercfg.write_maaend(automas, maaend,
                                         "AutoEssence/AutoEssenceObtainMode", "ObtainScaling9")
        require("没声明过的取值→拒绝", not ok, msg)
        ok, msg = mastercfg.write_maaend(automas, maaend,
                                         "AutoEssence/AutoEssenceChooseLocation", [])
        require("地区一个都不选→拒绝（脚本会直接结束）", not ok, msg)
        ok, msg = mastercfg.write_maaend(automas, maaend,
                                         "AutoEssence/AutoEssenceChooseLocation", ["VFNowhere"])
        require("地区里混进没声明的→拒绝", not ok, msg)

        print("\n=== 4. 鸣潮：读写母本 ===")
        got = mastercfg.read_okww(automas, None)
        require("体力刷什么读得到",
              got["values"].get("DailyTask.json/Which to Farm") == "Simulation Challenge")
        require("残象聚落点位是只读的",
              got["readonly"].get("NightmareNestTask.json/Only Farm These Nests") == "落渊南丘")
        ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Which Forgery Challenge to Farm", 3)
        now = mastercfg.read_okww(automas, None)["values"]
        require("序号写进去且保持整数",
              ok and now["DailyTask.json/Which Forgery Challenge to Farm"] == 3, msg)
        ok, msg = mastercfg.write_okww(automas, "NightmareNestTask.json/Only Farm These Nests", "全部")
        require("只读项→拒绝（死命令：只刷落渊南丘）", not ok, msg)
        ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Not A Key", 1)
        require("不存在的键→拒绝", not ok, msg)
        # 2026-10-13 audit: any string was written; upstream sends anything that is not
        # Tacet or Forgery to the simulation domain (DailyTask.py:125-127).
        okww = automas.parent / "okww"
        src = okww / "data" / "apps" / "ok-ww" / "working" / "src" / "task"
        src.mkdir(parents=True)
        (src / "DailyTask.py").write_text(
            "        self.support_tasks = ['Tacet Suppression', 'Forgery Challenge', 'Simulation Challenge']\n",
            encoding="utf-8")
        ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Which to Farm", "Tacet Supression", okww)
        now = mastercfg.read_okww(automas, None)["values"]
        require("Which to Farm: a value OK-WW does not list -> refused, file unchanged",
                not ok and now["DailyTask.json/Which to Farm"] == "Simulation Challenge", msg)
        ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Which to Farm", "Forgery Challenge", okww)
        now = mastercfg.read_okww(automas, None)["values"]
        require("Which to Farm: a listed value is written",
                ok and now["DailyTask.json/Which to Farm"] == "Forgery Challenge", msg)
        mastercfg.write_okww(automas, "DailyTask.json/Which to Farm", "Simulation Challenge", okww)
        # 2026-10-13 audit: a serial past OK-WW's list was written and upstream raised
        # IndexError on the day (TacetTask.py:111-112, ForgeryTask.py:63-64).
        (src / "TacetTask.py").write_text("        self.structure = [4, 5, 5, 7]\n", encoding="utf-8")
        (src / "ForgeryTask.py").write_text("        self.structure = [5, 5, 5, 5]\n", encoding="utf-8")
        for key, bad, good in (("Which Tacet Suppression to Farm", (0, 22), (1, 21)),
                               ("Which Forgery Challenge to Farm", (0, 21), (1, 20))):
            for v in bad:
                ok, msg = mastercfg.write_okww(automas, f"DailyTask.json/{key}", v, okww)
                require(f"{key} = {v}: refused", not ok and "已拒绝" in msg, msg)
            for v in good:
                ok, msg = mastercfg.write_okww(automas, f"DailyTask.json/{key}", v, okww)
                now = mastercfg.read_okww(automas, None)["values"]
                require(f"{key} = {v}: written", ok and now[f"DailyTask.json/{key}"] == v, msg)
        (src / "ForgeryTask.py").write_text("        self.structure = [5, 5, 5, 5, 5]\n", encoding="utf-8")
        ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Which Forgery Challenge to Farm", 25, okww)
        require("the bound is read from OK-WW's own source (a fifth region: 25 accepted)", ok, msg)
        ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Which Forgery Challenge to Farm", 21)
        require("source unreadable: the v3.7.4 bound (20) still refuses 21", not ok, msg)
        mastercfg.write_okww(automas, "DailyTask.json/Which Forgery Challenge to Farm", 3, okww)

        print("\n=== 5. OK-WW: a config file that exists but cannot be read is said once ===")
        import logging

        class Grab(logging.Handler):
            def __init__(self):
                super().__init__(logging.WARNING)
                self.msgs: list[str] = []

            def emit(self, record):
                self.msgs.append(record.getMessage())

        g = Grab()
        mastercfg.log.addHandler(g)
        getattr(mastercfg, "_last_error", {}).clear()
        daily = mastercfg.okww_file(automas, "DailyTask.json")
        nest = mastercfg.okww_file(automas, "NightmareNestTask.json")
        good_daily, good_nest = daily.read_text(encoding="utf-8"), nest.read_text(encoding="utf-8")
        nest.write_text("{broken", encoding="utf-8")
        got = mastercfg.read_okww(automas, None)
        require("corrupt read-only file -> the rest still read, its rows absent (shape unchanged)",
                got["values"].get("DailyTask.json/Which to Farm") is not None
                and "NightmareNestTask.json/Only Farm These Nests" not in got["readonly"])
        require("corrupt read-only file -> one WARNING naming it",
                len(g.msgs) == 1 and "NightmareNestTask.json" in g.msgs[0], f"{len(g.msgs)} said")
        mastercfg.read_okww(automas, None)
        require("same condition again -> no second WARNING", len(g.msgs) == 1, f"{len(g.msgs)} said")
        daily.write_text("{broken", encoding="utf-8")
        mastercfg.read_okww(automas, None)
        require("a second file breaks -> its own WARNING",
                len(g.msgs) == 2 and "DailyTask.json" in g.msgs[1], f"{len(g.msgs)} said")
        daily.write_text(good_daily, encoding="utf-8")
        nest.write_text(good_nest, encoding="utf-8")
        mastercfg.read_okww(automas, None)
        require("readable again -> no WARNING", len(g.msgs) == 2, f"{len(g.msgs)} said")
        nest.write_text("{broken", encoding="utf-8")
        mastercfg.read_okww(automas, None)
        require("broken again after a good read -> WARNING again", len(g.msgs) == 3, f"{len(g.msgs)} said")
        nest.write_text(good_nest, encoding="utf-8")
        mastercfg.log.removeHandler(g)

        print("\n" + "=" * 46)
        if FAILED:
            print(f"❌ {len(FAILED)} 项没过：{FAILED}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_mastercfg_jsonc_strings():
    """MaaEnd definitions are JSONC: comments and trailing commas go, string contents stay.

The old trailing-comma regex also ran inside strings and turned the `\\d{6,}` of
AutoStockStaple.json's verify rule into `\\d{6}`, so writing 12000000 (a value
MaaEnd's own rule accepts) to 自动囤货's reserve was refused as 「不合格式」.
Fixture: tests/fixtures/maaend-v2.32-autostock (upstream excerpt, see SOURCE.txt).

    Formerly test_mastercfg_jsonc_strings.py.
    """
    #!/usr/bin/env python3

    import json
    import re

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg

    FX = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-autostock"
    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def master_with_reserve(value: str) -> Path:
        automas = tmpdir() / "automas"
        cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoStockStaple", "enabled": True, "optionValues": {
                "AutoStockReserveWuling": {"type": "input", "values": {"ReserveWuling": value}}}},
        ]}]}), encoding="utf-8")
        return automas


    # 1. The walker itself: string contents survive, commas outside strings go.
    src = '{"a": "x,}", "b": "\\\\d{6,}", "c": [1, 2, ], // note\n "d": {"e": 1, },}'
    got = json.loads(mastercfg._strip_jsonc(src))
    require("「,}」 inside a string is kept", got["a"] == "x,}", repr(got["a"]))
    require("a regex quantifier {6,} inside a string is kept", got["b"] == "\\d{6,}", repr(got["b"]))
    require("trailing commas outside strings are dropped", got["c"] == [1, 2] and got["d"] == {"e": 1})

    # 2. The real definition reads back with MaaEnd's own rule intact.
    rule = mastercfg._maaend_defs(FX)[0]["AutoStockReserveWuling"]["inputs"][0]["verify"]
    require("AutoStockReserveWuling's verify rule is upstream's", rule.endswith("\\d{6,})$"), rule)
    require("MaaEnd's own rule accepts 12000000", bool(re.fullmatch(rule, "12000000")))

    # 3. Writing that value is accepted and lands in the master copy.
    automas = master_with_reserve("240000")
    ok, msg = mastercfg.write_maaend(automas, FX, "AutoStockStaple/AutoStockReserveWuling", "12000000")
    require("write 12000000 is accepted", ok, msg)
    doc = json.loads(mastercfg.maaend_master(automas).read_text(encoding="utf-8"))
    landed = doc["instances"][0]["tasks"][0]["optionValues"]["AutoStockReserveWuling"]["values"]["ReserveWuling"]
    require("12000000 is in the master copy", landed == "12000000", landed)

    # 4. A value the rule really rejects is still refused.
    ok, msg = mastercfg.write_maaend(automas, FX, "AutoStockStaple/AutoStockReserveWuling", "1000")
    require("write 1000 (below the rule) is refused", not ok, msg)

    # 5. _jsonc takes a file that is already JSON as it is (the walker cost 0.33 s per
    #    _read_maaend_defs, about five a boot: daysim 10-12, 2026-10-16) and gives the
    #    walker's result for every file, plain or not.
    walked: list[str] = []
    real_strip = mastercfg._strip_jsonc
    mastercfg._strip_jsonc = lambda t: (walked.append(t), real_strip(t))[1]
    try:
        d5 = tmpdir()
        plain = d5 / "plain.json"
        plain.write_text('{"url": "https://x/a,]", "re": "\\\\d{6,}", "n": [1, 2]}', encoding="utf-8")
        jsonc = d5 / "jsonc.json"
        jsonc.write_text('{"a": false // 不购买\n, "b": [1, /* x */ 2, ], }', encoding="utf-8")
        got_plain, n_plain = mastercfg._jsonc(plain), len(walked)
        got_jsonc = mastercfg._jsonc(jsonc)
        require("a plain JSON file is not walked", n_plain == 0, f"walked {n_plain}")
        require("a plain JSON file reads as JSON", got_plain == {"url": "https://x/a,]", "re": "\\d{6,}", "n": [1, 2]},
                repr(got_plain))
        require("a JSONC file is walked and reads back", len(walked) == 1 and got_jsonc == {"a": False, "b": [1, 2]},
                repr(got_jsonc))
        files = sorted(FX.rglob("*.json"))
        same = [f.name for f in files if mastercfg._jsonc(f) == json.loads(real_strip(f.read_text(encoding="utf-8")))]
        require("every fixture definition reads the same as through the walker", len(same) == len(files) > 0,
                f"{len(same)}/{len(files)}")
    finally:
        mastercfg._strip_jsonc = real_strip

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


def _part_mastercfg_protocolspace():
    """The phone can read and write MaaEnd's ProtocolSpace (the other sanity sink).

Until 2026-09-25 the phone had essence farming only, so there was no way to pick
T-Creds (OperatorProgression = T-Creds). The definitions here are MaaEnd
v2.30.0-rc.1 `assets/tasks/ProtocolSpace.json` verbatim, with the zh_cn strings it
references; the master entry is the one on the game machine that day
(`mxu-MaaEnd.json`, ProtocolSpace disabled, several keys not yet present).

    Formerly test_mastercfg_protocolspace.py.
    """
    #!/usr/bin/env python3

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg

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


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_mastercfg_jsonc_strings, _part_mastercfg_protocolspace]))
