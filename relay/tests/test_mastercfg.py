"""Master configuration convergence, MaaEnd schema/watchdog, booster switches, and essence filler."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)
# relay/ first for every part, as each part used to put it (run_parts restores sys.path after one)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub_win32(*names: str) -> None:
    """Stand-ins for the Windows-only modules the relay imports (pywin32, wmi, ...) on the Mac:
    any attribute of one is a callable returning another stand-in. setdefault: a module already
    in sys.modules stays; run_parts drops what a part added once the part is over."""
    import types

    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

    for name in names:
        sys.modules.setdefault(name, _Stub(name))


def _make_maaend_schema():
    import json
    import types

    def cache_task_enabled_for_controller(cache, controller_name, enabled: bool):
        if not controller_name:
            return cache
        return {**(cache if isinstance(cache, dict) else {}), controller_name: enabled}

    def mxu_load_save_flags(doc: dict) -> dict:
        out = json.loads(json.dumps(doc))
        for inst in out.get("instances") or []:
            for t in inst.get("tasks") or []:
                cache = cache_task_enabled_for_controller(
                    t.get("enabledByController"), inst.get("controllerName"), t.get("enabled")
                )
                if cache is None:
                    t.pop("enabledByController", None)
                else:
                    t["enabledByController"] = cache
        return out

    return types.SimpleNamespace(
        cache_task_enabled_for_controller=cache_task_enabled_for_controller,
        mxu_load_save_flags=mxu_load_save_flags,
    )


class _Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return False


class _N:
    def __init__(self):
        self.sent = []

    def send(self, title, body, alert=False, **kw):
        self.sent.append((title, alert))
        return []


def _part_mastercfg_main():
    """母本配置的读写。"""
    import json

    from ark_relay.core import mastercfg

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

        return 1 if fails else 0


    raise SystemExit(main())


def _part_mastercfg_jsonc_strings():
    """MaaEnd definitions are JSONC: comments and trailing commas go, string contents stay."""
    import json
    import re

    from ark_relay.core import mastercfg

    FX = fx_dir(Path(__file__), "fixtures") / "maaend-v2.32-autostock"

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


def _part_mastercfg_protocolspace():
    """The phone can read and write MaaEnd's ProtocolSpace (the other sanity sink)."""
    import json
    import shutil

    from ark_relay.core import mastercfg

    DEFS = fx_dir(Path(__file__), "fixtures") / "maaend-protocolspace-v2.30.0-rc.1"

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

        return 1 if fails else 0

    raise SystemExit(main())


def _part_maaend_controller_cache():
    """Every relay write of a MaaEnd task's switch leaves the master as MXU's UI saves it."""
    import json
    import types

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    sys.path.insert(0, str(HERE))

    ms = _make_maaend_schema()
    from ark_relay.core import mastercfg
    from ark_relay.features import makeup
    from ark_relay.features import sanity_plan

    FX = fx_dir(HERE, "fixtures") / "maaend-v2.33-essence"
    MASTER = json.loads((FX / "master-1016.json").read_text(encoding="utf-8"))
    CTRL = "Win32-Front"

    def put_master(doc: dict) -> Path:
        """A fresh AUTO-MAS dir holding `doc` as the MaaEnd master; returns its root."""
        root = tmpdir()
        d = root / "data" / "sid" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        (d / "mxu-MaaEnd.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return root

    def master_file(root: Path) -> Path:
        return root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"

    def task_of(doc: dict, name: str) -> dict:
        return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == name)

    def flags(doc: dict) -> list:
        return [(t.get("taskName"), t.get("enabled"), t.get("enabledByController"))
                for inst in doc.get("instances") or [] for t in inst.get("tasks") or []]

    def check_written(label: str, root: Path, touched: list[str], untouched: dict) -> None:
        """The touched tasks are consistent and survive an MXU load + save; the others
    are byte-for-byte what they were."""
        doc = json.loads(master_file(root).read_text(encoding="utf-8"))
        saved = ms.mxu_load_save_flags(doc)
        for name in touched:
            t = task_of(doc, name)
            cache = t.get("enabledByController")
            require(f"[{label}] {name}: cache is a dict", isinstance(cache, dict), cache)
            require(f"[{label}] {name}: enabled == enabledByController[{CTRL}]",
                    isinstance(cache, dict) and cache.get(CTRL) is t.get("enabled"), (t.get("enabled"), cache))
            st = task_of(saved, name)
            require(f"[{label}] {name}: an MXU load + save changes no flag",
                    (st.get("enabled"), st.get("enabledByController")) == (t.get("enabled"), cache),
                    (st.get("enabledByController"), cache))
        for name, was in untouched.items():
            require(f"[{label}] {name} left as it was", task_of(doc, name) == was, task_of(doc, name))

    def section_fixture() -> None:
        print("[fixture: the 10-16 master carries stale per-controller copies]")
        saved = ms.mxu_load_save_flags(MASTER)
        require("[fixture] ProtocolSpace enabled=False, cache {Win32-Front: true}",
                (task_of(MASTER, "ProtocolSpace")["enabled"], task_of(MASTER, "ProtocolSpace")["enabledByController"])
                == (False, {CTRL: True}))
        require("[fixture] AutoEssence cache is a bare true", task_of(MASTER, "AutoEssence")["enabledByController"] is True)
        require("[fixture] an MXU load + save of it would rewrite those two",
                [n for (n, *_a), b in zip(flags(MASTER), flags(saved), strict=True) if tuple(_a) != b[1:]]
                == ["ProtocolSpace", "AutoEssence"], flags(saved))

    def section_port() -> None:
        print("[port: the relay setter is MXU's cacheTaskEnabledForController]")
        port = ms.cache_task_enabled_for_controller
        require("[port] bare boolean -> dict", port(True, CTRL, False) == {CTRL: False})
        require("[port] missing -> dict", port(None, CTRL, True) == {CTRL: True})
        require("[port] other controllers kept", port({"ADB": False, CTRL: True}, CTRL, False) == {"ADB": False, CTRL: False})
        require("[port] no controller name -> cache as it was", port(True, None, False) is True and port(None, "", True) is None)
        setter = getattr(mastercfg, "set_maaend_enabled", None)
        require("[port] mastercfg.set_maaend_enabled exists", setter is not None)
        if setter is None:
            return
        for cache in ("<absent>", None, True, False, {}, {CTRL: True}, {CTRL: False}, {"ADB": True}, {"ADB": False, CTRL: True}):
            for ctrl in (CTRL, None, ""):
                for on in (True, False):
                    for was in (True, False):
                        t = {"taskName": "X", "enabled": was}
                        if cache != "<absent>":
                            t["enabledByController"] = json.loads(json.dumps(cache))
                        before = json.loads(json.dumps(t))
                        changed = setter(t, on, ctrl)
                        want_cache = port(before.get("enabledByController"), ctrl, on)
                        want = {"taskName": "X", "enabled": on}
                        if want_cache is not None or "enabledByController" in before:
                            want["enabledByController"] = want_cache
                        case = f"cache={cache!r} ctrl={ctrl!r} {was}->{on}"
                        if t != want or changed != (t != before):
                            require(f"[port] setter == port ({case})", False, (t, want, changed))
                            return
        require("[port] setter == port on every cache shape, controller and value", True)

    def section_write_maaend() -> None:
        print("[mastercfg.write_maaend @enabled]")
        root = put_master(MASTER)
        keep = {n: task_of(MASTER, n) for n in ("AutoEssence", "DailyRewards")}
        ok, msg = mastercfg.write_maaend(root, FX, "ProtocolSpace/@enabled", True)
        require("[write_maaend] ProtocolSpace on accepted", ok, msg)
        check_written("write_maaend on", root, ["ProtocolSpace"], keep)
        ok, msg = mastercfg.write_maaend(root, FX, "ProtocolSpace/@enabled", False)
        require("[write_maaend] ProtocolSpace off accepted", ok, msg)
        check_written("write_maaend off", root, ["ProtocolSpace"], keep)
        ok, msg = mastercfg.write_maaend(root, FX, "AutoEssence/@enabled", False)
        require("[write_maaend] AutoEssence (bare true cache) off accepted", ok, msg)
        check_written("write_maaend bare", root, ["AutoEssence"], {"DailyRewards": keep["DailyRewards"]})

    def section_sanity_plan() -> None:
        print("[sanity_plan.set_plan]")
        root = put_master(MASTER)
        before = master_file(root).read_bytes()
        ok, msg = sanity_plan.set_plan(root, "Essence")
        require("[sanity_plan] the plan already in force: no write (a stale cache alone is no change)",
                ok and master_file(root).read_bytes() == before, msg)
        keep = {"DailyRewards": task_of(MASTER, "DailyRewards")}
        ok, msg = sanity_plan.set_plan(root, "OperatorProgression", "T-Creds")
        require("[sanity_plan] switch to ProtocolSpace accepted", ok, msg)
        check_written("sanity_plan ProtocolSpace", root, ["ProtocolSpace", "AutoEssence"], keep)
        doc = json.loads(master_file(root).read_text(encoding="utf-8"))
        require("[sanity_plan] ProtocolSpace on, AutoEssence off",
                (task_of(doc, "ProtocolSpace")["enabled"], task_of(doc, "AutoEssence")["enabled"]) == (True, False))
        ok, msg = sanity_plan.set_plan(root, "Essence")
        require("[sanity_plan] switch back to essence accepted", ok, msg)
        check_written("sanity_plan Essence", root, ["ProtocolSpace", "AutoEssence"], keep)

    def section_makeup() -> None:
        print("[makeup.stash_first]")
        doc = json.loads(json.dumps(MASTER))
        doc["instances"][0]["tasks"].append({"taskName": makeup.STASH, "enabled": False,
                                             "enabledByController": True, "optionValues": {}})
        root = put_master(doc)
        cfg = types.SimpleNamespace(automas_dir=root, state_dir=tmpdir(), maaend_dir=FX)
        keep = {n: task_of(doc, n) for n in ("ProtocolSpace", "AutoEssence", "DailyRewards")}
        changed, why = makeup.stash_first(cfg, "run-1", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] 存放背包 switched on and moved first", changed and why == "", (changed, why))
        check_written("makeup bare", root, [makeup.STASH], keep)
        makeup.restore(cfg)
        require("[makeup] restore puts the original flags back",
                flags(json.loads(master_file(root).read_text(encoding="utf-8"))) == flags(doc))

        # Another controller's entry is MXU's, not the relay's: it stays as it was.
        doc2 = json.loads(json.dumps(MASTER))
        doc2["instances"][0]["tasks"].insert(0, {"taskName": makeup.STASH, "enabled": True,
                                                 "enabledByController": {"ADB": False, CTRL: True},
                                                 "optionValues": {}})
        root2 = put_master(doc2)
        cfg2 = types.SimpleNamespace(automas_dir=root2, state_dir=tmpdir(), maaend_dir=FX)
        before = master_file(root2).read_bytes()
        changed, why = makeup.stash_first(cfg2, "run-2", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] on and first already: nothing written, other controller's copy kept",
                not changed and why == "" and master_file(root2).read_bytes() == before, (changed, why))

        # On and first with a stale bare-boolean copy: a stale copy alone makes no write.
        doc3 = json.loads(json.dumps(MASTER))
        doc3["instances"][0]["tasks"].insert(0, {"taskName": makeup.STASH, "enabled": True,
                                                 "enabledByController": True, "optionValues": {}})
        root3 = put_master(doc3)
        cfg3 = types.SimpleNamespace(automas_dir=root3, state_dir=tmpdir(), maaend_dir=FX)
        before = master_file(root3).read_bytes()
        changed, why = makeup.stash_first(cfg3, "run-3", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] on and first with a bare-true copy: nothing written",
                not changed and why == "" and master_file(root3).read_bytes() == before, (changed, why))

        # This controller's copy says off while enabled is true: switched on in both.
        doc4 = json.loads(json.dumps(MASTER))
        doc4["instances"][0]["tasks"].insert(0, {"taskName": makeup.STASH, "enabled": True,
                                                 "enabledByController": {"ADB": True, CTRL: False},
                                                 "optionValues": {}})
        root4 = put_master(doc4)
        cfg4 = types.SimpleNamespace(automas_dir=root4, state_dir=tmpdir(), maaend_dir=FX)
        changed, why = makeup.stash_first(cfg4, "run-4", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] this controller's copy off: written", changed and why == "", (changed, why))
        check_written("makeup ctrl-off", root4, [makeup.STASH], keep)
        st = task_of(json.loads(master_file(root4).read_text(encoding="utf-8")), makeup.STASH)
        require("[makeup] the other controller's entry is kept", st["enabledByController"] == {"ADB": True, CTRL: True},
                st["enabledByController"])

    def main() -> int:
        for section in (section_fixture, section_port, section_write_maaend, section_sanity_plan, section_makeup):
            try:
                section()
            except Exception as exc:  # noqa: BLE001
                require(f"{section.__name__} ran", False, f"{type(exc).__name__}: {exc}")
        return 1 if fails else 0

    raise SystemExit(main())


def _part_maaend_defs_228():
    """The phone page must show Chinese names and real choices on MaaEnd v2.28."""
    import json
    import re

    from ark_relay.core import mastercfg

    HAN = re.compile(r"[一-鿿]")

    FX = fx_dir(Path(__file__), "fixtures") / "maaend228"
    root = tmpdir()
    automas = root / "AUTO-MAS"
    cf = automas / "data" / "x" / "Default" / "ConfigFile"
    cf.mkdir(parents=True)
    # The master as it was on the machine that night: AutoEssence without the two
    # new booster keys, plus the orphaned standalone task.
    (cf / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": [
        {"taskName": "AutoEssence", "enabled": True, "optionValues": {
            "AutoEssenceDoOverride": {"type": "switch", "value": False},
            "AutoEssenceObtainMode": {"type": "select", "caseName": "ObtainScaling1"},
            "AutoEssenceRepeatCount": {"type": "input", "values": {"AutoEssenceRepeatCountValue": "99"}},
            "AutoEssenceChooseLocation": {"type": "checkbox", "caseNames": ["WLSwordVaultDale"]},
            "EssenceFilterAfterBattle": {"type": "switch", "value": True},
        }},
        {"taskName": "AutoUseSpMedication", "enabled": True, "optionValues": {
            "AutoUseSpMedicationExpireWithinDays": {"type": "select", "caseName": "Days3"}}},
        {"taskName": "AutoCollect", "enabled": True, "optionValues": {
            "AutoCollectRoutes": {"type": "checkbox", "caseNames": ["Route1"]},
            "AutoCollectSchedule": {"type": "checkbox", "caseNames": ["AutoCollectScheduleMonday"]}}},
    ]}]}, ensure_ascii=False), encoding="utf-8")

    r = mastercfg.read_maaend(automas, FX)
    K = "AutoEssence/AutoEssenceSpMedicationExpireWithinDays"

    print("[每一项都要有中文名——原始键名出现在手机上就是失败]")
    raw = {k: v for k, v in r["labels"].items() if not HAN.search(v or "")}
    check("没有一项是英文键名", raw, {})
    check("没有列进「没翻译」的", r.get("untranslated"), [])
    for k in ("AutoEssence/AutoEssenceObtainMode", "AutoEssence/AutoUseSpMedication", K, "AutoCollect/AutoCollectSchedule"):
        check(f"{k} 是选择项，有可选值", bool(r["options"].get(k)), True)
    check("加强剂窗口的可选值就是 MaaEnd 定义的那五档",
          [v for _, v in r["options"].get(K, [])], ["All", "Days10", "Days7", "Days3", "Days1"])
    check("可选值的名字也是中文", all(HAN.search(l) for l, _ in r["options"].get(K, [])), True)
    check("配置里还没有的项按定义默认值显示", r["values"].get(K), "Days3")

    print("\n[这一版脚本已经没有的任务要报成孤儿，不能当成还在跑]")
    check("孤儿任务", r.get("orphans"), ["AutoUseSpMedication"])
    check("孤儿任务的设置不再当成活的展示",
          any(k.startswith("AutoUseSpMedication/") for k in r["values"]), False)

    print("\n[写：只认定义里的值；定义声明了的项可以按默认形状建出来]")
    ok, msg = mastercfg.write_maaend(automas, FX, K, "Days99")
    check("不认识的值被拒", ok, False)
    ok, msg = mastercfg.write_maaend(automas, FX, K, "All")
    check("All 写进去了", ok, True)
    check("回读是 All", mastercfg.read_maaend(automas, FX)["values"].get(K), "All")
    ok, msg = mastercfg.write_maaend(automas, FX, "AutoEssence/不存在的项", "x")
    check("定义里没有的项仍然拒绝造", ok, False)

    print("\n[死条目不光报警，要清掉——但要两个独立信号都说它死了才动手]")
    import logging

    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.recs = []
            self.titles = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))
            self.titles.append((getattr(record, "ark_alarm", None) or (None,))[0])

    _g = _Grab()
    mastercfg.log.addHandler(_g)
    removed, note = mastercfg.prune_maaend_orphans(automas, FX)
    mastercfg.log.removeHandler(_g)
    check("清掉的正是那一条", removed, ["AutoUseSpMedication"])
    check("删了就 WARNING（报群），点名删了哪一项、原来开着",
          [lv for lv, m in _g.recs if "AutoUseSpMedication（开着）" in m and "删掉" in m], [logging.WARNING])
    from ark_relay.core import texts as _tx
    check("删了的那条以自己的标题进群（「🧹 终末地配置清掉了死条目」）", _tx.MAAEND_PRUNED in _g.titles, True)
    check("话里说清清了什么、备份在哪", "AutoUseSpMedication" in note and "bak-orphans" in note, True)
    after = mastercfg.read_maaend(automas, FX)
    check("清完不再是孤儿", after.get("orphans"), [])
    check("别的任务一个没少", sorted(t["taskName"] for t in json.loads((cf / "mxu-MaaEnd.json").read_text(encoding="utf-8"))["instances"][0]["tasks"]),
          ["AutoCollect", "AutoEssence"])
    check("再跑一遍什么都不做", mastercfg.prune_maaend_orphans(automas, FX), ([], ""))
    check("备份文件在", bool(list(cf.glob("mxu-MaaEnd.json.bak-orphans-*"))), True)
    # CreditShoppingN2 is declared by a file that only parses with the full JSONC
    # stripper; the definitions index knows it, so it must never be pruned.
    (cf / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": [
        {"taskName": "CreditShoppingN2", "enabled": True, "optionValues": {}},
        {"taskName": "__MXU_WEBHOOK__", "enabled": True, "optionValues": {}}]}]}), encoding="utf-8")
    check("定义里有的不算孤儿（CreditShoppingN2）", mastercfg.read_maaend(automas, FX).get("orphans"), [])
    check("不会误删", mastercfg.prune_maaend_orphans(automas, FX)[0], [])

    print("\n[绝不删 MaaEnd 还定义着的：定义看不全就不动，WARNING 说明原因]")
    import shutil

    def _fx_copy():
        d = tmpdir() / "maaend"
        shutil.copytree(FX, d)
        return d

    def _master(tasks):
        (cf / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": tasks}]}), encoding="utf-8")

    ORPHAN_OFF = {"taskName": "AutoUseSpMedication", "enabled": False, "optionValues": {}}
    _master([dict(ORPHAN_OFF)])
    _g = _Grab()
    mastercfg.log.addHandler(_g)
    removed, note = mastercfg.prune_maaend_orphans(automas, FX)
    mastercfg.log.removeHandler(_g)
    check("关着的残留照样清掉", removed, ["AutoUseSpMedication"])
    check("关着的删了也 WARNING（每次删都报群），写明原来关着",
          [lv for lv, m in _g.recs if "AutoUseSpMedication（关着）" in m and "删掉" in m], [logging.WARNING])

    # A definition file that does not parse but names the candidate: it may still be defined.
    fx = _fx_copy()
    bad = fx / "tasks" / "CreditShopping.json"
    bad.write_text('{ "task": [ {"name": "AutoUseSpMedication"} ] <<< not json', encoding="utf-8")
    _master([dict(ORPHAN_OFF, enabled=True)])
    _g = _Grab()
    mastercfg.log.addHandler(_g)
    removed, note = mastercfg.prune_maaend_orphans(automas, fx)
    mastercfg.log.removeHandler(_g)
    check("读不了的定义文件里提到它：不删", removed, [])
    check("不删也 WARNING（报群），说明为什么", [lv for lv, m in _g.recs if "没有删" in m and "CreditShopping.json" in m],
          [logging.WARNING])
    check("说明里点名是哪个文件", "CreditShopping.json" in note and "AutoUseSpMedication" in note, True)
    check("母本一个字没动", json.loads((cf / "mxu-MaaEnd.json").read_text(encoding="utf-8"))["instances"][0]["tasks"],
          [dict(ORPHAN_OFF, enabled=True)])

    # interface.json (MaaEnd's own list of definition files) unreadable: the fallback glob may miss files.
    fx = _fx_copy()
    (fx / "interface.json").write_text("{ broken", encoding="utf-8")
    _master([dict(ORPHAN_OFF, enabled=True)])
    removed, note = mastercfg.prune_maaend_orphans(automas, fx)
    check("定义清单读不了：不删、说明原因", (removed, "interface.json" in note), ([], True))

    # A listed definition file that exists but cannot be opened.
    fx = _fx_copy()
    (fx / "tasks" / "PuzzleSolver.json").unlink()
    (fx / "tasks" / "PuzzleSolver.json").mkdir()
    _master([dict(ORPHAN_OFF, enabled=True)])
    removed, note = mastercfg.prune_maaend_orphans(automas, fx)
    check("定义文件打不开：不删、说明是哪个", (removed, "PuzzleSolver.json" in note), ([], True))


def _part_maaend_migrate_options():
    """The master config must be rewritten when MaaEnd changes an option's format."""
    import json
    import shutil
    import tempfile

    from ark_relay.core import mastercfg

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-09-10"

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # A MaaEnd install with only the two task files that matter, listed in
        # interface.json the way the real one lists them.
        maaend = d / "maaend"
        (maaend / "tasks" / "AutoEssence").mkdir(parents=True)
        shutil.copy(FIX / "tasks" / "AutoCollect.json", maaend / "tasks" / "AutoCollect.json")
        shutil.copy(FIX / "tasks" / "AutoEssence" / "AutoEssence.json",
                    maaend / "tasks" / "AutoEssence" / "AutoEssence.json")
        iface = json.loads((FIX / "interface.json").read_text(encoding="utf-8"))
        iface["import"] = ["tasks/AutoCollect.json", "tasks/AutoEssence/AutoEssence.json"]
        (maaend / "interface.json").write_text(json.dumps(iface), encoding="utf-8")
        # And the AUTO-MAS master where the relay expects it.
        automas = d / "automas"
        cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfgdir.mkdir(parents=True)
        master = cfgdir / "mxu-MaaEnd.json"
        shutil.copy(FIX / "master-before.json", master)

        def task(doc, name):
            return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == name)

        before = json.loads(master.read_text(encoding="utf-8"))
        old_routes = set(task(before, "AutoCollect")["optionValues"]["AutoCollectRoutes"]["caseNames"])
        check("样本确实还是旧写法", "AutoCollectRoutes" in task(before, "AutoCollect")["optionValues"])

        changes, note = mastercfg.migrate_maaend_options(automas, maaend)
        print("\n".join("    " + c for c in changes))
        check("有改动", bool(changes))
        after = json.loads(master.read_text(encoding="utf-8"))
        ac = task(after, "AutoCollect")["optionValues"]

        print("\n[自动采集：一份路线表拆成两个区域，勾的还是那些]")
        check("旧键没了", "AutoCollectRoutes" not in ac and "AutoCollectCommonRoutes" not in ac)
        valley = set(ac["AutoCollectValleyIVRareRoutes"]["caseNames"])
        wuling = set(ac["AutoCollectWulingRareRoutes"]["caseNames"])
        check("四号谷地的稀有路线 = 原来勾的 ∩ 该区域的", valley, {"Route4", "Route5", "Route6", "Route13", "Route14"})
        check("武陵的稀有路线 = 原来勾的 ∩ 该区域的",
              wuling, {"Route1", "Route2", "Route3", "Route7", "Route8", "Route9", "Route10", "Route11", "Route12", "Route15", "Route16", "Route17"})
        check("两边合起来一条不少", valley | wuling, old_routes)
        check("原来没勾普通路线，现在也不勾", ac["AutoCollectValleyIVCommonRoutes"]["caseNames"], [])
        check("区域开关打开", ac["AutoCollectValleyIV"]["value"] and ac["AutoCollectWuling"]["value"])
        check("模式补上 Always", ac["AutoCollectMode"]["caseName"], "Always")
        check("值的写法和 MaaEnd 自己存的一样", ac["AutoCollectValleyIVRareRoutes"]["type"], "checkbox")

        print("\n[基质刷取：地点还是藏剑谷/清波寨，菜单键补上]")
        ae = task(after, "AutoEssence")["optionValues"]
        check("地点没被动", ae["AutoEssenceChooseLocation"]["caseNames"], ["WLSwordVaultDale", "WLQingboStockade"])
        check("补上 AutoEssenceMenu=Random", ae.get("AutoEssenceMenu", {}).get("caseName"), "Random")
        check("吃药那项补上", ae.get("AutoUseSpMedication", {}).get("caseName"), "UseMedication")
        check("死键 SelectInputLanguage 去掉", "EssenceFilterAfterBattleSelectInputLanguage" not in ae)
        check("次数 99 没被动", ae["AutoEssenceRepeatCount"]["values"]["AutoEssenceRepeatCountValue"], "99")

        print("\n[不该碰的]")
        check("定义文件不在索引里的任务（CreditShoppingN2）原样",
              task(after, "CreditShoppingN2")["optionValues"], task(before, "CreditShoppingN2")["optionValues"])
        check("MXU 自己的 __ 任务原样",
              [t for t in after["instances"][0]["tasks"] if t["taskName"].startswith("__")],
              [t for t in before["instances"][0]["tasks"] if t["taskName"].startswith("__")])
        check("任务数不变", len(after["instances"][0]["tasks"]), len(before["instances"][0]["tasks"]))
        check("留了备份", any(p.name.startswith("mxu-MaaEnd.json.bak-migrate-") for p in cfgdir.iterdir()))
        check("说明是人话，带备份名", "备份" in note and "按原意改写" in note)

        print("\n[界面的「最近关闭」历史也不能留旧键——MaaEnd 每次加载都会拿它报警]")
        rc_before = before.get("recentlyClosed") or []
        rc_after = after.get("recentlyClosed") or []
        check("原样本里确实有带旧键的历史",
              any("AutoCollectRoutes" in (t.get("optionValues") or {}) for e in rc_before for t in e.get("tasks") or []))
        check("改完历史里没有 AutoCollectRoutes",
              any("AutoCollectRoutes" in (t.get("optionValues") or {}) for e in rc_after for t in e.get("tasks") or []), False)
        check("改完历史里没有 AutoEssenceChallengeMode",
              any("AutoEssenceChallengeMode" in (t.get("optionValues") or {}) for e in rc_after for t in e.get("tasks") or []), False)
        check("定义没读到的任务（SellProduct）那条历史不动",
              any(t.get("taskName") == "SellProduct" for e in rc_after for t in e.get("tasks") or []))
        check("说明里提到了清历史", "最近关闭" in note)

        print("\n[再跑一次：没有改动]")
        changes2, note2 = mastercfg.migrate_maaend_options(automas, maaend)
        check("幂等", (changes2, note2), ([], ""))


def _part_maaend_migrate_stock_switch():
    """自动囤货's buy lists must survive MaaEnd turning them from checkbox into switch."""
    import json
    import shutil
    import tempfile

    from ark_relay.core import mastercfg

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-10-10"
    KEYS = ("AutoStockBuyDailyGoodsValleyIV", "AutoStockBuyStockFactoryGoodsValleyIV",
            "AutoStockBuyCulturalGoodsValleyIV", "AutoStockBuyDailyGoodsWuling",
            "AutoStockBuyStockFactoryGoodsWuling", "AutoStockBuyCulturalGoodsWuling")

    def stock(doc):
        return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == "AutoStockStaple")["optionValues"]

    def setup(d: Path, master_doc: dict) -> "tuple[Path, Path, Path]":
        maaend = d / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        shutil.copy(FIX / "AutoStockStaple.json", maaend / "tasks" / "AutoStockStaple.json")
        (maaend / "interface.json").write_text(json.dumps({"import": ["tasks/AutoStockStaple.json"]}),
                                               encoding="utf-8")
        (maaend / "locales" / "interface").mkdir(parents=True)
        shutil.copy(FIX / "zh_cn-AutoStockStaple.json", maaend / "locales" / "interface" / "zh_cn.json")
        automas = d / "automas"
        cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfgdir.mkdir(parents=True)
        (cfgdir / "mxu-MaaEnd.json").write_text(json.dumps(master_doc, ensure_ascii=False), encoding="utf-8")
        return automas, maaend, cfgdir

    before = json.loads((FIX / "master-before.json").read_text(encoding="utf-8"))
    picks = {k: stock(before)[k]["caseNames"] for k in KEYS}
    check("样本确实还是旧写法（6 项都是多选）", all(stock(before)[k]["type"] == "checkbox" for k in KEYS))

    with tempfile.TemporaryDirectory() as d:
        automas, maaend, cfgdir = setup(Path(d), before)
        master = cfgdir / "mxu-MaaEnd.json"
        changes, note = mastercfg.migrate_maaend_options(automas, maaend)
        print("\n".join("    " + c for c in changes))
        after = json.loads(master.read_text(encoding="utf-8"))
        ov = stock(after)

        print("\n[6 个清单：开关按有没有勾设，勾的物品原样搬到 …Items]")
        check("6 项都改了", len(changes), 6)
        for k in KEYS:
            check(f"{k} 是开关", ov[k]["type"], "switch")
            check(f"{k} 开关 = 原来有没有勾", ov[k]["value"], bool(picks[k]))
            check(f"{k}Items = 原来勾的", ov[k + "Items"], {"type": "checkbox", "caseNames": picks[k]})
        check("谷地工业货品原来一样没勾 → 关（不再买探测器、罗盘）",
              ov["AutoStockBuyStockFactoryGoodsValleyIV"]["value"], False)
        check("谷地日用只勾了雅各布遗产", ov["AutoStockBuyDailyGoodsValleyIVItems"]["caseNames"], ["JakubsLegacy"])

        print("\n[不该碰的]")
        check("限购数量原样", {k: v for k, v in ov.items() if k.endswith("Limit")},
              {k: v for k, v in stock(before).items() if k.endswith("Limit")})
        check("区域开关、排班原样", {k: ov[k] for k in ("AutoStockStapleValleyIV", "AutoStockStapleWuling",
                                                       "AutoStockStapleSchedule")},
              {k: stock(before)[k] for k in ("AutoStockStapleValleyIV", "AutoStockStapleWuling",
                                             "AutoStockStapleSchedule")})
        check("定义不在索引里的任务（DailyRewards）原样",
              after["instances"][0]["tasks"][1], before["instances"][0]["tasks"][1])
        check("留了原样备份", [json.loads(p.read_text(encoding="utf-8")) for p in cfgdir.iterdir()
                           if p.name.startswith("mxu-MaaEnd.json.bak-migrate-")], [before])
        check("说明是人话，带备份名", "备份" in note and "改成了开关" in note)
        check("说明用游戏里的中文名", "四号谷地稳定物资购买 · 工业货品：改成了开关，设为关（原来一样都没勾）" in note)
        check("说明里没有英文键名", "AutoStockBuy" in note, False)

        print("\n[再跑一次：没有改动]")
        check("幂等", mastercfg.migrate_maaend_options(automas, maaend), ([], ""))

    print("\n[勾了新清单里没有的物品：不猜，原样留着让核对去报]")
    odd = json.loads(json.dumps(before))
    stock(odd)["AutoStockBuyDailyGoodsValleyIV"]["caseNames"] = ["JakubsLegacy", "NoSuchItem"]
    with tempfile.TemporaryDirectory() as d:
        automas, maaend, cfgdir = setup(Path(d), odd)
        changes, _ = mastercfg.migrate_maaend_options(automas, maaend)
        ov = stock(json.loads((cfgdir / "mxu-MaaEnd.json").read_text(encoding="utf-8")))
        check("那一项不动", ov["AutoStockBuyDailyGoodsValleyIV"], {"type": "checkbox", "caseNames": ["JakubsLegacy", "NoSuchItem"]})
        check("其余 5 项照迁", len(changes), 5)


def _part_maaend_migrate_unread_defs():
    """migrate_maaend_options does not drop a live value because a definition file was unreadable.
    """
    import json

    from ark_relay.core import mastercfg

    def setup(stash_text: str, interface: "str | None" = '{"import": ["tasks/AutoCollect.json", "tasks/StashBackpack.json"]}'):
        root = tmpdir()
        automas = root / "automas"
        cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoCollect", "enabled": True, "optionValues": {
                "AutoCollectMode": {"type": "select", "caseName": "Always"},
                "StashBackpackMode": {"type": "select", "caseName": "Deposit"},
                "OldDeadKey": {"type": "switch", "value": True}}}]}]}), encoding="utf-8")
        maaend = root / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        if interface is not None:
            (maaend / "interface.json").write_text(interface, encoding="utf-8")
        (maaend / "tasks" / "AutoCollect.json").write_text(json.dumps({
            "task": [{"name": "AutoCollect", "option": ["AutoCollectMode", "StashBackpackMode"]}],
            "option": {"AutoCollectMode": {"type": "select", "cases": [{"name": "Always"}]}}}), encoding="utf-8")
        (maaend / "tasks" / "StashBackpack.json").write_text(stash_text, encoding="utf-8")
        return automas, maaend, cfg / "mxu-MaaEnd.json"

    def values(master: Path) -> dict:
        return json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]

    GOOD = json.dumps({"option": {"StashBackpackMode": {"type": "select", "cases": [{"name": "Deposit"}]}}})
    BROKEN = GOOD[:-1] + " oops"           # StashBackpack.json does not parse but names its option

    print("[every definition read: a dead key goes, the live ones stay]")
    automas, maaend, master = setup(GOOD)
    changes, note = mastercfg.migrate_maaend_options(automas, maaend)
    require("OldDeadKey is removed", "OldDeadKey" not in values(master), note)
    require("StashBackpackMode is kept", "StashBackpackMode" in values(master), note)

    print("[StashBackpack.json does not parse]")
    automas, maaend, master = setup(BROKEN)
    changes, note = mastercfg.migrate_maaend_options(automas, maaend)
    require("StashBackpackMode is not deleted", "StashBackpackMode" in values(master), repr(values(master)))
    require("the migration refuses and names the file", not changes and "StashBackpack.json" in note, note)
    require("nothing else is rewritten either", "OldDeadKey" in values(master), repr(values(master)))

    print("[interface.json unreadable: the file list is a guess]")
    automas, maaend, master = setup(GOOD, interface="{broken")
    changes, note = mastercfg.migrate_maaend_options(automas, maaend)
    require("refuses when MaaEnd's own file list cannot be read",
            not changes and "interface.json" in note and "OldDeadKey" in values(master), note)

    print("[the AUTO-MAS instance, not just the first one (11-08 [D-08])]")
    from ark_relay.core import mastercfg as _mc
    _doc = {"instances": [{"id": "other", "tasks": [{"taskName": "T", "x": 1}]},
                          {"id": "automas", "tasks": [{"taskName": "T", "x": 2}]}]}
    require("picks id automas", (_mc._maaend_task(_doc, "T") or {}).get("x") == 2)
    require("no automas: the first",
            (_mc._maaend_task({"instances": [{"tasks": [{"taskName": "T", "x": 3}]}]}, "T") or {}).get("x") == 3)


def _part_maaend_name_mismatch():
    """When AUTO-MAS cannot name a renamed MaaEnd task, the relay judges by MaaEnd's own log."""
    import json
    import pathlib
    import shutil

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    HERE = pathlib.Path(__file__).resolve().parent
    REAL_0906 = (fx_dir(HERE, "gamesim") / "corpus" / "maaend" / "v3-0906-automas-misjudged" / "automas" / "history"
                 / "2026-09-06" / "endfield" / "MaaEnd-05-40-21")
    REAL_0918 = fx_dir(HERE, "fixtures") / "maaend-2026-09-18" / "MaaEnd-05-26-03"

    log_0906 = REAL_0906.with_suffix(".log").read_text(encoding="utf-8")
    lines_0906 = log_0906.splitlines(keepends=True)
    # What the test leans on, from the real file.
    assert "结束进程" not in log_0906 and "关闭游戏" not in log_0906, "the real 09-06 log has no closing task"
    assert log_0906.count("任务开始: ") == 16 and log_0906.count("任务完成: ") == 16 and "任务失败" not in log_0906
    CUT = next(i for i, ln in enumerate(lines_0906) if "任务开始: 🛒据点交易" in ln) + 1
    assert "任务完成: 🛒据点交易" not in "".join(lines_0906[:CUT])

    root = tmpdir()
    d = root / "2026-09-06" / "endfield"
    d.mkdir(parents=True)
    shutil.copy2(REAL_0906.with_suffix(".json"), d / "MaaEnd-05-40-21.json")
    shutil.copy2(REAL_0906.with_suffix(".log"), d / "MaaEnd-05-40-21.log")

    print("[09-06 05:40, the real record: 16/16 complete, no closing task, AUTO-MAS lists SellProduct]")
    rec = collector.parse_record(d / "MaaEnd-05-40-21.json", root)
    check("booked done", (rec.ok, rec.failed_tasks) if rec else None, (True, []))
    check("records the name AUTO-MAS could not look up", rec and rec.raw.get("maaend_name_mismatch"), ["SellProduct"])

    print("\n[the same real log cut where 据点交易 started: stuck mid-task]")
    (d / "MaaEnd-06-14-25.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"},
                                                       ensure_ascii=False), encoding="utf-8")
    (d / "MaaEnd-06-14-25.log").write_text("".join(lines_0906[:CUT]), encoding="utf-8")
    rec3 = collector.parse_record(d / "MaaEnd-06-14-25.json", root)
    check("a task started and never ended is not cleared", rec3.ok if rec3 else None, False)

    print("\n[the same real log, AUTO-MAS lists a display name that never started]")
    (d / "MaaEnd-06-20-00.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"},
                                                       ensure_ascii=False), encoding="utf-8")
    shutil.copy2(REAL_0906.with_suffix(".log"), d / "MaaEnd-06-20-00.log")
    rec5 = collector.parse_record(d / "MaaEnd-06-20-00.json", root)
    check("a listed task that never started keeps the failure (no closing task to show the round ended)",
          (rec5.ok, rec5.failed_tasks) if rec5 else None, (False, ["协议空间"]))

    print("\n[09-18 05:26, a real 「任务失败: 🎱基质刷取」]")
    d18 = root / "2026-09-18" / "endfield"
    d18.mkdir(parents=True)
    shutil.copy2(REAL_0918.with_suffix(".json"), d18 / "MaaEnd-05-26-03.json")
    shutil.copy2(REAL_0918.with_suffix(".log"), d18 / "MaaEnd-05-26-03.log")
    rec2 = collector.parse_record(d18 / "MaaEnd-05-26-03.json", root)
    check("a real failure stays a failure", (rec2.ok, rec2.failed_tasks) if rec2 else None, (False, ["基质刷取"]))

    print("\n[AUTO-MAS's 模拟器启动失败 stub]")
    (d / "MaaEnd-06-51-56.json").write_text(json.dumps({"maaend_result": "[自动采集] 模拟器启动失败"}, ensure_ascii=False),
                                            encoding="utf-8")
    (d / "MaaEnd-06-51-56.log").write_text("模拟器启动失败, 无日志记录\n", encoding="utf-8")
    rec4 = collector.parse_record(d / "MaaEnd-06-51-56.json", root)
    check("transitional, no failure", (rec4.transitional, rec4.failed_tasks) if rec4 else None, (True, []))

    print("\n[re-judging the ledger only moves towards done]")
    old_entry = {"run_id": "2026-09-06/endfield/MaaEnd-05-40-21", "script": "MaaEnd", "ok": False,
                 "failed_tasks": ["SellProduct"], "raw": {}}
    fresh = collector.refresh_raw(old_entry, root)
    check("the 09-06 entry booked failed is re-judged done", (fresh.get("ok"), fresh.get("failed_tasks")), (True, []))
    old_bad = {"run_id": "2026-09-18/endfield/MaaEnd-05-26-03", "script": "MaaEnd", "ok": False,
               "failed_tasks": ["基质刷取"], "raw": {}}
    check("a real failure is not re-judged done", bool(collector.refresh_raw(old_bad, root).get("ok")), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_maaend_phone_page_beta5():
    """The phone page must show the per-region gathering lists MaaEnd v2.28.0-beta.5 uses."""
    import re

    from ark_relay.core import mastercfg

    HAN = re.compile(r"[一-鿿]")

    FX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-09-10"
    root = tmpdir()
    automas = root / "AUTO-MAS"
    cf = automas / "data" / "x" / "Default" / "ConfigFile"
    cf.mkdir(parents=True)
    (cf / "mxu-MaaEnd.json").write_text((FX / "master-before.json").read_text(encoding="utf-8"),
                                        encoding="utf-8")
    mastercfg.migrate_maaend_options(automas, FX)
    r = mastercfg.read_maaend(automas, FX)
    A = "AutoCollect/"

    print("[新格式的每一项都在页上，而且都是中文名]")
    for opt in ("AutoCollectSchedule", "AutoCollectMode", "AutoCollectValleyIV",
                "AutoCollectValleyIVRareRoutes", "AutoCollectValleyIVCommonRoutes",
                "AutoCollectWuling", "AutoCollectWulingRareRoutes", "AutoCollectWulingCommonRoutes"):
        check(f"{opt} 有值", A + opt in r["values"], True)
        check(f"{opt} 有中文名", bool(HAN.search(r["labels"].get(A + opt) or "")), True)
    check("没有列进「没翻译」的", [k for k in r.get("untranslated") or [] if k.startswith(A)], [])
    check("旧的 AutoCollectRoutes 不再出现", A + "AutoCollectRoutes" in r["values"], False)

    print("\n[路线清单是可勾选的，名字带材料名，勾选保留原样]")
    check("四号谷地稀有路线的可选值", [v for _, v in r["options"][A + "AutoCollectValleyIVRareRoutes"]],
          ["Route4", "Route5", "Route6", "Route13", "Route14"])
    check("武陵稀有路线的可选值", [v for _, v in r["options"][A + "AutoCollectWulingRareRoutes"]],
          ["Route1", "Route2", "Route3", "Route7", "Route8", "Route9", "Route10", "Route11",
           "Route12", "Route15", "Route16", "Route17"])
    check("路线名写着材料", all("：" in l for l, _ in r["options"][A + "AutoCollectWulingRareRoutes"]), True)
    check("四号谷地勾的还是原来那几条", r["values"][A + "AutoCollectValleyIVRareRoutes"],
          ["Route4", "Route5", "Route6", "Route13", "Route14"])
    check("一般采集物没勾", r["values"][A + "AutoCollectWulingCommonRoutes"], [])
    check("地区开关是布尔", r["values"][A + "AutoCollectWuling"], True)
    check("采集模式有两档", [v for _, v in r["options"][A + "AutoCollectMode"]], ["Always", "TargetInventory"])
    check("采集模式当前是按勾选路线", r["values"][A + "AutoCollectMode"], "Always")

    print("\n[页上改了能写回去]")
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectWulingCommonRoutes", ["CommonRoute3"])
    check("勾一条一般路线", ok, True)
    check("回读是那一条", mastercfg.read_maaend(automas, FX)["values"][A + "AutoCollectWulingCommonRoutes"],
          ["CommonRoute3"])
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectMode", "TargetInventory")
    check("换采集模式", ok, True)
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectValleyIV", False)
    check("关掉一个地区", ok, True)
    check("回读关了", mastercfg.read_maaend(automas, FX)["values"][A + "AutoCollectValleyIV"], False)
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectWulingRareRoutes", ["Route99"])
    check("不存在的路线被拒", ok, False)


def _part_maaend_schedule_skip():
    """A task MaaEnd skips by its weekday schedule is reported as skipped, not done."""

    from ark_relay.features.collector_maaend import parse_maaend_log

    HERE = Path(__file__).resolve().parent

    def main() -> int:
        r = parse_maaend_log(fx_dir(HERE, "replay") / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log")
        require("skipped gathering is not listed as done", "自动采集" not in (r.get("tasks_done") or []),
                repr(r.get("tasks_done")))
        require("... it is listed as skipped with its weekday",
                (r.get("maaend_tasks_skipped") or {}).get("自动采集") == "周六", repr(r.get("maaend_tasks_skipped")))
        require("the old gathering key is kept", r.get("maaend_collect_skipped") == "周六",
                repr(r.get("maaend_collect_skipped")))

        ps = tmpdir() / "ps.log"
        ps.write_text("[2026-09-27 09:45:11.071] 任务开始: ⚔️协议空间\n"
                      "[2026-09-27 09:45:11.154] 现在游戏时间是周二，根据执行周期跳过任务\n"
                      "[2026-09-27 09:45:11.221] 任务完成: ⚔️协议空间\n", encoding="utf-8")
        p = parse_maaend_log(ps)
        require("skipped 协议空间 is not listed as done", "协议空间" not in (p.get("tasks_done") or []),
                repr(p.get("tasks_done")))
        require("... it is listed as skipped", (p.get("maaend_tasks_skipped") or {}).get("协议空间") == "周二",
                repr(p.get("maaend_tasks_skipped")))
        require("... and no 「刷 协议空间 ×0」 farming section", not p.get("maaend_farm"), repr(p.get("maaend_farm")))

        full = parse_maaend_log(fx_dir(HERE, "fixtures") / "maaend-farm-drops" / "2026-09-27.log")
        require("a run that really farmed is unchanged", full.get("maaend_farm") == "协议空间"
                and "协议空间" in (full.get("tasks_done") or []) and not full.get("maaend_tasks_skipped"),
                repr((full.get("maaend_farm"), full.get("maaend_tasks_skipped"))))
        return 1 if fails else 0

    raise SystemExit(main())


def _part_maaend_skipped_report():
    """The daily report says a weekday-skipped MaaEnd task was skipped: not done,
not missing.
    """
    from datetime import datetime, timedelta

    from ark_relay.core import ledger as core
    from ark_relay.features.collector_maaend import parse_maaend_log
    from ark_relay.core.config import SERVER_TZ

    HERE = Path(__file__).resolve().parent

    LOG = ("[2026-09-06 09:41:39.529] 任务开始: 🎁赠送干员礼物\n"
           "[2026-09-06 09:44:06.485] 任务完成: 🎁赠送干员礼物\n"
           "[2026-09-06 09:51:43.971] 任务开始: 🛒据点交易\n"
           "[2026-09-06 09:53:39.232] 任务完成: 🛒据点交易\n"
           "[2026-09-06 09:53:40.071] 任务开始: ⚔️协议空间\n"
           "[2026-09-06 09:53:40.154] 现在游戏时间是周二，根据执行周期跳过任务\n"
           "[2026-09-06 09:53:40.221] 任务完成: ⚔️协议空间\n"
           "[2026-09-06 09:53:41.000] 任务开始: 📅日常奖励领取\n"
           "[2026-09-06 09:55:00.000] 任务完成: 📅日常奖励领取\n")


    def ent(raw: dict) -> dict:
        st = datetime(2026, 9, 6, 9, 41, tzinfo=SERVER_TZ)
        return {"run_id": "2026-09-06/endfield/MaaEnd-05-40-21", "script": "MaaEnd", "user": "u", "ok": True,
                "started": st.isoformat(), "finished": (st + timedelta(minutes=14)).isoformat(),
                "duration_known": True, "transitional": False, "failed_tasks": [],
                "raw": raw, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}


    def main() -> int:
        p = tmpdir() / "MaaEnd-05-40-21.log"
        p.write_text(LOG, encoding="utf-8")
        raw = parse_maaend_log(p)
        require("parser: 协议空间 skipped on 周二", raw.get("maaend_tasks_skipped") == {"协议空间": "周二"},
                repr(raw.get("maaend_tasks_skipped")))

        # The three tasks that ran have a task-end picture each (cloud-alerts-1006:
        # done needs game evidence); the skipped one has none and is not listed anyway.
        raw = dict(raw, tasks_shot=["赠送干员礼物", "据点交易", "日常奖励领取"])
        _title, body = core.format_daily("2026-09-06", [ent(raw)])
        require("the report says it was skipped by schedule, with the weekday",
                "按排班跳过、没有做：协议空间（今天周二）" in body, body)
        require("... and does not list it as done or farmed",
                "做了 赠送干员礼物、据点交易、日常奖励领取" in body and "刷 协议空间" not in body, body)
        foot = core.daily_footnote([ent(raw)])
        require("the daily list does not count it", "协议空间" not in foot and "据点交易" in foot, foot)

        # 自动采集 keeps its own sentence, said once (not again in the generic one).
        gather = parse_maaend_log(fx_dir(HERE, "replay") / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log")
        _t3, b3 = core.format_daily("2026-09-05", [ent(gather)])
        require("a skipped 自动采集 keeps its own sentence", "自动采集 今天周六不是采集日" in b3, b3)
        require("... and is not repeated in the generic one", "按排班跳过、没有做：自动采集" not in b3, b3)
        return 1 if fails else 0


    raise SystemExit(main())


def _part_maaend_write_readback():
    """write_maaend reads back the very item it wrote and compares it with what it wrote."""
    import json

    from ark_relay.core import mastercfg

    FX = fx_dir(Path(__file__), "fixtures") / "maaend-v2.32-autostock"
    PATH = "AutoStockStaple/AutoStockReserveWuling"

    def master() -> Path:
        automas = tmpdir() / "automas"
        cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoStockStaple", "enabled": True, "optionValues": {
                "AutoStockReserveWuling": {"type": "input", "values": {"ReserveWuling": "240000"}}}},
        ]}]}), encoding="utf-8")
        return automas

    # 1. A good write names the value it read back, not None.
    ok, msg = mastercfg.write_maaend(master(), FX, PATH, "240001")
    require("write 240001 succeeds", ok, msg)
    require("the answer shows the value read back", msg.endswith("'240000' → '240001'"), msg)

    # 2. The file comes back different from what was written: refused.
    real = mastercfg.atomic_write_text
    mastercfg.atomic_write_text = lambda path, text, **k: Path(path).write_text(
        text.replace('"240001"', '"240000"'), encoding="utf-8")
    try:
        ok, msg = mastercfg.write_maaend(master(), FX, PATH, "240001")
    finally:
        mastercfg.atomic_write_text = real
    require("a read-back that differs from the write is not a success", not ok, msg)

    # 3. The task switch still reads back too.
    automas = master()
    ok, msg = mastercfg.write_maaend(automas, FX, "AutoStockStaple/@enabled", False)
    require("switching the task off succeeds and says so", ok and msg.endswith("True → False"), msg)
    mastercfg.atomic_write_text = lambda path, text, **k: Path(path).write_text(
        text.replace('"enabled": false', '"enabled": true'), encoding="utf-8")
    try:
        ok, msg = mastercfg.write_maaend(master(), FX, "AutoStockStaple/@enabled", False)
    finally:
        mastercfg.atomic_write_text = real
    require("a task switch that reads back unchanged is not a success", not ok, msg)


def _watchdog_agreement(Rig, MAAEND_PID, RUNNING, texts, collect_watch):
    """#187 (11-20): MaaEnd held at the 「协议更新」 dialog. Called from _part_maaend_watchdog_main with
    its Rig; a function of its own so that part stays under the complexity limit."""
    print("\n[11-20 (#187)：开屏停在「协议更新」窗口——日志一直在写，第二个任务开头又读到就结束 MaaEnd]")

    class Agree(Rig):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.seen = 0

        def step(self, seconds, *, new_lines=40, stamp=None, seen=0):
            self.t += seconds
            self.lines += new_lines
            self.seen += seen
            return self.dog.tick(self.lines, self.stamp, self.seen)
    r = Agree()
    r.step(60)
    r.step(30, seen=1)                                 # 09:34:28 the dialog read
    r.step(30)
    check("只读到一次：不动", (r.killed, r.notes.sent), ([], []))
    r.run_for(240)
    check("日志一直在写：老的 10 分钟判据不会出手", r.killed, [])
    got = r.step(30, seen=1)                            # 09:40:03 read again at the next task's start
    check("隔 5 分多钟又读到：结束 MaaEnd（没碰游戏）", (got, r.killed[:1]), (texts.MAAEND_STUCK_KILLED, [MAAEND_PID]))
    title, body, alert = r.notes.sent[0]
    check("一条群报警，说清是协议窗口、要人点同意", (len(r.notes.sent), alert, "协议更新" in body, "点「同意」" in body),
          (1, True, True, True))
    check("正文是人话", texts.plain(body), [])
    r = Agree()
    r.step(60, seen=1)
    r.step(30)
    r.step(40, seen=1)
    check("隔 70 秒又读到：结束（不用等任务失败）", r.killed[:1], [MAAEND_PID])
    r = Agree()
    r.step(60, seen=1)
    r.step(20, seen=1)
    check("20 秒内读到两次（同一屏）：还不算", r.killed, [])
    r.run_for(600)
    check("之后再没读到、也没任务失败（有人点了同意）：不动", r.killed, [])

    print("\n[AUTO-MAS 重试拉起的下一个 MaaEnd 又停在那儿：照样结束，跟别的卡死一样每结束一个报一条]")
    r = Agree()
    r.step(60, seen=1)
    r.step(70, seen=1)
    r.procs = [(n, (p + 100 if n.lower() == "maaend.exe" else p)) for n, p in r.procs]
    r.step(30)
    r.step(30, seen=1)
    r.step(70, seen=1)
    check("两个 MaaEnd 都结束了", [p for p in r.killed if p in (MAAEND_PID, MAAEND_PID + 100)], [MAAEND_PID, MAAEND_PID + 100])
    check("每结束一个 MaaEnd 报一条（不压）", len(r.notes.sent), 2)

    print("\n[上一个 MaaEnd 读到过、这个只读到一次：不算到这个头上]")
    r = Agree()
    r.step(60, seen=1)
    r.snap = {"tasks": []}                              # that MaaEnd finished
    r.step(30)
    r.snap = RUNNING
    r.step(40, seen=1)
    r.run_for(300)
    check("新的一趟只读到一次：不动", r.killed, [])

    print("\n[真数据回放：11-20 09:32-10:13 的任务事件和弹窗读字行（两份轮转日志里原样摘出），一行一行喂]")
    import types
    from datetime import datetime as _dt
    real = (fx_dir(Path(__file__), "fixtures") / "maaend-2026-11-20" / "maafw-0932-1013-events-and-dialog.log"
            ).read_text(encoding="utf-8").splitlines()
    r = Rig()
    w = collect_watch.Watcher(types.SimpleNamespace(maaend_dir="", state_dir=str(tmpdir())), r.notes)
    killed_at = None
    for ln in real:
        stamp = ln[1:24]
        line_t = _dt.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f").timestamp()
        # Between two of these lines MaaFW wrote thousands more and the watcher thread woke at least
        # every TICK_SECONDS: tick on that clock too, with no new dialog read.
        while r.t + collect_watch.TICK_SECONDS < line_t:
            r.t += collect_watch.TICK_SECONDS
            r.lines += 100
            if r.dog.tick(r.lines, stamp[:19], w.agreement_seen) and killed_at is None:
                killed_at = _dt.fromtimestamp(r.t).strftime("%H:%M:%S")
        r.t = line_t
        w.feed(ln)
        r.lines += 1
        if r.dog.tick(r.lines, stamp[:19], w.agreement_seen) and killed_at is None:
            killed_at = stamp[11:19]
    check("读到几次（每个任务开头一次，09:34-10:07 共 7 个任务）", w.agreement_seen, 7)
    check("09:40:03 第二个任务开头又读到，下一眼（至多 1 分钟内）就结束 MaaEnd，不是 10:57",
          killed_at is not None and "09:40:03" <= killed_at <= "09:41:03", True)
    print("    结束于", killed_at)


def _part_maaend_watchdog_main():
    """MaaEnd hung -> end MaaEnd.exe so AUTO-MAS retries now, not 45 minutes later."""
    import logging
    import os
    import threading
    import time

    from ark_relay.features import collect_watch, maaend_watchdog
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of

    class _Drops(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())

    _drops = _Drops()
    from ark_relay.core import watch as _watch
    _watch.log.addHandler(_drops)

    CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
    RUNNING = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"},
                                        {"name": "OK-WW", "status": "异常"},
                                        {"name": "MaaEnd", "status": "运行"}]}]}
    WAITING = {"tasks": [{"task_info": [{"name": "MAA", "status": "运行"},
                                        {"name": "MaaEnd", "status": "等待"}]}]}
    DONE = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}
    MAAEND_PID = 21260
    ALL_UP = [("System", 4), ("Endfield.exe", 18800), ("MaaEnd.exe", MAAEND_PID),
              ("go-service.exe", 21932), ("cpp-algo.exe", 21940), ("python.exe", 9000)]
    NO_GO = [p for p in ALL_UP if p[0] != "go-service.exe"]

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

    class Rig:
        """One watchdog with every outside thing replaced."""

        def __init__(self, *, snap=RUNNING, procs=ALL_UP, kill_ok=True, active=True, paths=None):
            self.t = 1000.0
            self.snap, self.procs = snap, procs
            self.kill_ok = kill_ok
            self.killed = []
            self.notes = Notes()
            self.debug = tmpdir() / "debug"
            self.debug.mkdir()
            self.stderr = self.debug / "go-service.stderr.log"
            self.stderr.write_text("", encoding="utf-8")
            self.lines = 0
            self.stamp = "2026-10-01 15:20:00"
            agent = str(self.debug.parent / "agent")
            self.paths = paths if paths is not None else {21932: os.path.join(agent, "go-service.exe"),
                                                           21940: os.path.join(agent, "cpp-algo.exe")}
            self.images = []
            self.dog = maaend_watchdog.Watchdog(
                self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: self.snap,
                processes=lambda: self.procs, kill=self._kill, plugin_paths=lambda: self.paths,
                active=active)

        def _kill(self, pid, image):
            self.killed.append(pid)
            self.images.append(image)
            return (True, "") if self.kill_ok else (False, "退出码 128")

        def step(self, seconds, *, new_lines=0, stamp=None):
            """Let `seconds` pass, with `new_lines` appended to maafw.log meanwhile."""
            self.t += seconds
            self.lines += new_lines
            if stamp:
                self.stamp = stamp
            return self.dog.tick(self.lines, self.stamp)

        def run_for(self, seconds, every=60, **kw):
            out = []
            for _ in range(int(seconds // every)):
                if r := self.step(every, **kw):
                    out.append(r)
            return out

    print("[2026-10-01：MaaEnd 在跑，go-service 崩溃 → 结束 MaaEnd 一次，群里一条报警]")
    r = Rig()
    r.run_for(240, new_lines=40)                       # MaaEnd running fine for 4 minutes
    check("崩溃前什么都不做", (r.killed, r.notes.sent), ([], []))
    r.stderr.write_text(CRASH_LINE + "\nPC=0x7ffc630b5456\n\ngoroutine 1 gp=0xc000002380 m=0 mp=0x1 "
                        "[syscall, 5 minutes]:\n", encoding="utf-8")
    r.step(60)
    check("结束的是 MaaEnd.exe（和它的两个插件），没碰游戏", r.killed, [MAAEND_PID, 21932, 21940])
    check("只发一条", len(r.notes.sent), 1)
    title, body, alert = r.notes.sent[0]
    check("标题", title, texts.MAAEND_STUCK_KILLED)
    check("是真报警", alert, True)
    check("走群机器人", route_of(title, alert=True), "group")
    check("正文有错误码 0xc0000005", "0xc0000005" in body, True)
    check("正文说已结束", "已结束 MaaEnd" in body, True)
    check("正文是人话", texts.plain(body), [])
    r.run_for(600)
    check("同一个 MaaEnd 不再结束第二次", r.killed, [MAAEND_PID, 21932, 21940])
    check("也不再报第二次", len(r.notes.sent), 1)

    _watchdog_agreement(Rig, MAAEND_PID, RUNNING, texts, collect_watch)


    print("\n[maafw.log 10 分钟没有新行 → 结束 + 报警；9 分钟不动作]")
    r = Rig()
    r.run_for(300, new_lines=50, stamp="2026-10-01 15:30:03")
    r.run_for(540)                                     # 9 minutes with no new line
    check("9 分钟：不动作", (r.killed, r.notes.sent), ([], []))
    r.step(60)
    check("10 分钟：结束 MaaEnd", r.killed[:1], [MAAEND_PID])
    check("报警一条", len(r.notes.sent), 1)
    body = r.notes.sent[0][1] if r.notes.sent else ""
    check("正文写 10 分钟和最后一行时间", ("10 分钟" in body, "15:30:03" in body), (True, True))
    check("正文是人话", texts.plain(body), [])

    print("\n[正常：每 65 秒一行新日志 → 不动作]")
    r = Rig()
    r.run_for(65 * 40, every=65, new_lines=1)
    check("43 分钟里一次都没结束", (r.killed, r.notes.sent), ([], []))

    print("\n[MaaEnd 不是「运行」→ 不判、不杀]")
    for label, snap in (("等待", WAITING), ("完成", DONE), ("问不到快照", None)):
        r = Rig(snap=snap)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.run_for(1800)
        check(f"{label}：30 分钟没新行、stderr 有崩溃，也不动作", (r.killed, r.notes.sent), ([], []))

    print("\n[从等待变成运行：10 分钟从变成运行那一刻算，不从上一行日志算]")
    r = Rig(snap=WAITING)
    r.run_for(1800)
    r.snap = RUNNING
    r.run_for(120, new_lines=5)                        # first sight at +60 s, a new line at +120 s
    r.run_for(540)                                     # +660 s: 9 minutes since that line
    check("最后一行后 9 分钟：不动作", r.killed, [])
    r.step(60)
    check("满 10 分钟：结束", r.killed[:1], [MAAEND_PID])

    print("\n[go-service 不在：只见到一次不动作，隔 ≥60 秒连续两次才动作]")
    r = Rig()
    r.run_for(240, new_lines=20)
    r.procs = NO_GO
    r.step(60, new_lines=5)
    check("第一次不在：不动作", r.killed, [])
    r.procs = ALL_UP
    r.step(60, new_lines=5)
    r.procs = NO_GO
    r.step(30, new_lines=5)
    check("中间又见到了，重新数：不动作", r.killed, [])
    r.step(30, new_lines=5)
    check("隔 30 秒第二次不在：还不动作", r.killed, [])
    r.step(30, new_lines=5)
    check("隔 ≥60 秒第二次不在：结束（插件已不在，只结束 MaaEnd 和 cpp-algo）", r.killed, [MAAEND_PID, 21940])
    body = r.notes.sent[0][1] if r.notes.sent else ""
    check("正文说插件不在了", "go-service.exe 已经不在了" in body, True)
    check("正文是人话", texts.plain(body), [])

    print("\n[MaaEnd 刚起不满 3 分钟：插件还没起来是正常的 → 不动作]")
    r = Rig(procs=[p for p in NO_GO if p[0] != "cpp-algo.exe"])
    r.run_for(120, new_lines=10)
    check("2 分钟里不在两次：不动作", r.killed, [])
    r.run_for(180, new_lines=10)
    check("满 3 分钟后再连续两次不在：动作", r.killed[:1], [MAAEND_PID])

    print("\n[MaaEnd 换了新的一次（PID 变了）：旧的计时和旧的崩溃都不算]")
    r = Rig()
    r.run_for(240, new_lines=20)
    r.procs = [("MaaEnd.exe", 30000)]
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")   # the previous run's dump, still in the file
    r.step(60)
    check("新 PID 第一次见到时 stderr 已有的内容不算", r.killed, [])
    r.stderr.write_text("", encoding="utf-8")                   # go-service relaunched: file rewritten
    r.step(60, new_lines=5)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60, new_lines=5)
    check("重写后的新崩溃照样认得出", r.killed[:1], [30000])

    print("\n[结束失败 → 报警写没结束成]")
    r = Rig(kill_ok=False)
    r.run_for(240, new_lines=20)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("试着结束了一次", r.killed, [MAAEND_PID])
    title, body, alert = r.notes.sent[0] if r.notes.sent else ("", "", False)
    check("标题说没能结束", title, texts.MAAEND_STUCK_KILL_FAILED)
    check("是真报警，走群", (alert, route_of(title, alert=True)), (True, "group"))
    check("正文写结束没成功和原因", ("结束 MaaEnd 没成功" in body, "退出码 128" in body), (True, True))
    check("正文是人话", texts.plain(body), [])
    r.run_for(600)
    check("同一个 PID 不再试、不再报", (len(r.killed), len(r.notes.sent)), (1, 1))

    print("\n[不是 Windows：整个看门狗不动作]")
    r = Rig(active=False)
    r.run_for(240, new_lines=20)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.run_for(1800)
    check("什么都不做", (r.killed, r.notes.sent), ([], []))

    print("\n[MaaEnd.exe 不在：没东西可结束]")
    r = Rig(procs=[p for p in ALL_UP if p[0] != "MaaEnd.exe"])
    r.run_for(1800)
    check("不动作", r.killed, [])

    print("\n[maafw.log 的行数：跟轮转，变短但 bak 里有新行也算有新行]")

    class _Cfg:
        pass

    cfg = _Cfg()
    cfg.maaend_dir = str(tmpdir())
    cfg.state_dir = tmpdir()  # collect_watch.start prunes old task shots there
    (Path(cfg.maaend_dir) / "debug").mkdir()
    lp = Path(cfg.maaend_dir) / "debug" / "maafw.log"
    lp.write_text("[2026-10-01 15:29:00.000][INF] a\n" * 50, encoding="utf-8")
    w = collect_watch.Watcher(cfg, Notes())
    w.poll()
    seen = w.lines_seen
    check("读到 50 行", seen, 50)
    check("最后一行的时间", w.last_stamp, "2026-10-01 15:29:00")
    with lp.open("a", encoding="utf-8") as fh:
        fh.write("[2026-10-01 15:30:03.511][INF] b\n")
    lp.rename(lp.parent / "maafw.bak.2026.10.01-15.30.04.000.log")
    lp.write_text("", encoding="utf-8")                # MaaFW started over; the new file is empty
    w.poll()
    check("新文件更短，旧文件尾巴上那一行算新行", w.lines_seen, seen + 1)
    check("最后一行时间跟着更新", w.last_stamp, "2026-10-01 15:30:03")
    w.poll()
    check("没有新内容就不涨", w.lines_seen, seen + 1)

    print("\n[监听线程：日志不动也每隔一段时间叫一次看门狗]")
    ticks = []

    class _FakeDog:
        def __init__(self, *a, **kw):
            pass

        def tick(self, lines, stamp, agreement_seen=0):
            ticks.append(lines)

    real_dog, real_tick = maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS
    maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS = _FakeDog, 0.2
    try:
        check("挂上了", collect_watch.start(cfg, Notes()), True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(ticks) < 3:
            time.sleep(0.1)
        check("文件一动不动，看门狗也被叫到了至少 3 次", len(ticks) >= 3, True)
    finally:
        maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS = real_dog, real_tick
    check("线程还活着", any(t.name == "collect-watch" for t in threading.enumerate()), True)

    print("\n[taskkill carries the image name, so a reused PID is never someone else]")
    r = Rig()
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("names passed with each PID", r.images, ["MaaEnd.exe", "go-service.exe", "cpp-algo.exe"])

    print("\n[a plugin-named program outside <maaend>\\agent is left alone]")
    r = Rig(paths={21932: "C:\\other\\go-service.exe", 21940: str(Path(tmpdir()) / "agent" / "cpp-algo.exe")})
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("only MaaEnd.exe ended", r.killed, [MAAEND_PID])
    r = Rig()
    r.paths = {21932: str(r.debug.parent / "agent2" / "go-service.exe"),
               21940: str(r.debug.parent / "agent" / "cpp-algo.exe")}
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("a sibling folder agent2 is not agent", r.killed, [MAAEND_PID, 21940])
    r = Rig(paths={})
    r.run_for(240, new_lines=40)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.step(60)
    check("paths unreadable -> plugins not ended", r.killed, [MAAEND_PID])

    print("\n[plugins left running are named in the alarm body (left=)]")
    _real_body = texts.maaend_stuck_body
    _body_calls = []
    texts.maaend_stuck_body = lambda *a, **kw: _body_calls.append((a, kw)) or "正文"
    try:
        r = Rig(paths={21932: "C:\\other\\go-service.exe"})    # cpp-algo's path unreadable
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)
        check("skipped plugins passed as left", _body_calls[-1][1].get("left"),
              ["C:\\other\\go-service.exe", "agent\\cpp-algo.exe"])
        r = Rig()
        r._kill = lambda pid, image: (r.killed.append(pid), (True, "") if image == "MaaEnd.exe" else (False, "退出码 128"))[1]
        r.dog.kill = r._kill
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)
        check("plugins whose kill failed passed as left", _body_calls[-1][1].get("left"),
              ["agent\\go-service.exe", "agent\\cpp-algo.exe"])
        r = Rig()
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)
        check("all plugins ended -> nothing left", _body_calls[-1][1].get("left", []), [])
    finally:
        texts.maaend_stuck_body = _real_body

    print("\n[not one maafw.log line read for this MaaEnd: report once, never kill]")
    from ark_relay.features import errwatch

    class _Warns(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.recs = []

        def emit(self, record):
            self.recs.append(record)

    _warns = _Warns()
    maaend_watchdog.log.addHandler(_warns)
    r = Rig()
    r.run_for(1200)                              # 20 minutes, no line at all
    maaend_watchdog.log.removeHandler(_warns)
    check("nothing ended", r.killed, [])
    check("one alarm, the blind one", [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND])
    check("it is a group alarm", route_of(texts.MAAEND_WATCH_BLIND, alert=True), "group")
    # s1: the WARNING repeating it was a second group push (every WARNING goes to the group).
    check("the WARNING repeating it is marked as already in the group, not pushed again",
          [bool(getattr(x, errwatch.PUSHED, False)) for x in _warns.recs if "读不到 maafw.log" in x.getMessage()], [True])
    r.procs = [p for p in ALL_UP if p[0] != "MaaEnd.exe"]
    r.step(60)
    r.procs = ALL_UP
    r.run_for(1200)
    check("a later MaaEnd with the same PID, unreadable too: rings again",
          [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND, texts.MAAEND_WATCH_BLIND])
    check("still nothing ended", r.killed, [])
    r = Rig()
    r.run_for(120, new_lines=5)
    r.run_for(660)
    check("lines once, then silence -> the normal stall kill", r.killed, [MAAEND_PID, 21932, 21940])

    print("\n[_taskkill reads success from the output: a filter that matches nothing still exits 0]")
    real_run = maaend_watchdog.subprocess.run
    calls = []

    def fake_run(out, rc=0):
        def run(args, **kw):
            calls.append(args)
            return type("R", (), {"returncode": rc, "stdout": out.encode("gbk"), "stderr": b""})()
        return run

    try:
        maaend_watchdog.subprocess.run = fake_run("成功: 已终止 PID 为 21260 的进程。")
        check("成功 -> ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe"), (True, ""))
        check("filters on PID and image", calls[-1], ["taskkill", "/F", "/FI", "PID eq 21260", "/FI", "IMAGENAME eq MaaEnd.exe"])
        maaend_watchdog.subprocess.run = fake_run("信息: 没有运行的带有指定标准的任务。")
        check("no match, exit 0 -> not ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe")[0], False)
        maaend_watchdog.subprocess.run = fake_run("错误: 无法终止", rc=128)
        check("exit 128 -> not ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe"), (False, "退出码 128"))
    finally:
        maaend_watchdog.subprocess.run = real_run

    check("目录监听在测试期间没掉过", _drops.msgs, [])


def _part_maaend_no_d3d11_alarm():
    """A game started without Direct3D 11 is normal now: no group alarm after a MaaEnd record or at boot.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    import boot_stages
    from ark_relay.features import collect_retry
    from ark_relay.features import handle
    from ark_relay.features import efstart as efstart_setup
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    class Warned(logging.Handler):
        """What errwatch.ErrorKindAlert would take: every WARNING or worse (it sits on the relay's top logger)."""

        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(f"{record.name}: {record.getMessage()}")

    WARNED = Warned()
    logging.getLogger().addHandler(WARNED)

    player = TMP / "Administrator" / "Player.log"
    player.parent.mkdir()
    player.write_text("\n".join([
        "Mono path[0] = 'D:/endfield/Hypergryph Launcher/games/Endfield Game/Endfield_Data/Managed'",
        "Mono config path = 'D:/endfield/Hypergryph Launcher/games/Endfield Game/MonoBleedingEdge/etc'",
        "[Physics::Module] Initialized MultithreadedJobDispatcher with 15 workers.",
        "Initialize engine version: 2021.3.34f1",
        "[Subsystems] Discovering subsystems at path D:/endfield/x/UnitySubsystems",
        "Forcing GfxDevice: Direct3D 12",
        "Direct3D:",
    ]) + "\n", encoding="utf-8")
    # Before this change the relay found Player.log through this function; patched so that code
    # would read the file above. Code without the function never reads it.
    efstart_setup._player_logs = lambda: [str(player)]

    def automas_dir() -> Path:
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
        for k, p in paths.items():
            sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
        qc = {"instances": [{"uid": "q0"}],
              "q0": {"Info": {"Name": "早班", "TimeEnabled": True},
                     "SubConfigsInfo": {"TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                        "QueueItem": {"instances": [],
                                                      **{f"i{i}": {"Info": {"ScriptId": f"s-{k}"}}
                                                         for i, k in enumerate(paths)}}}}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root

    class Src:
        def fetch(self, seen):
            return []

    handle._ship_evidence = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    collect_retry.restore_master = lambda cfg: ""

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir() / "state"
        cfg.automas_dir = automas_dir()
        cfg.maaend_dir = MAAEND
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e

    print("[the capture sees a WARNING from the relay's loggers at all]")
    efstart_setup._log_efstart_setup.warning("probe")
    check("a WARNING from efstart_setup's logger is caught", WARNED.lines, ["ark.efstart_setup: probe"])
    WARNED.lines.clear()

    print("\n[a MaaEnd record lands, Player.log line 6 is not Direct3D 11]")
    start = datetime(2026, 10, 16, 13, 26, 0, tzinfo=SERVER_TZ)
    rec = RunRecord(run_id="2026-10-16/endfield/MaaEnd-09-26-00", script="MaaEnd", user="endfield",
                    started=start, finished=start + timedelta(minutes=30), ok=True, failed_tasks=[],
                    raw={"maaend_result": "Success!"})
    e = build()
    handle._handle(e, rec)
    e._flush_pending()
    check("no WARNING (errwatch would push each one to the group)", WARNED.lines, [])
    check("nothing to the group", [s for s in e.notifier.sent if s[2]], [])

    print("\n[boot: the Endfield start stage with the same Player.log]")
    WARNED.lines.clear()
    # A later start of the game (the log written again), so the boot reads it afresh.
    _t = player.stat().st_mtime + 60
    os.utime(player, (_t, _t))
    boot_stages._endfield_launch = lambda cfg, log, when: None
    boot_stages._stage_endfield_start(Config(), _Notes(), efstart_setup._log_efstart_setup)
    check("no WARNING at boot", WARNED.lines, [])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_maaend_essence_met():
    """Essence target mode with nothing left to farm is its own ending: not a
false green, not work done.
    """
    from datetime import datetime

    from ark_relay.core import ledger as core
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.collector_maaend import parse_maaend_log
    from ark_relay.features.outcome import maaend_checks, summarize

    REC = fx_dir(Path(__file__), "replay") / "2026-10-16" / "endfield"
    HIST = (REC / "MaaEnd-09-53-33.log").read_text(encoding="utf-8")
    APP = "\n" + (REC / "2026-10-16-3.log").read_text(encoding="utf-8")
    MET_LINE = "勾选武器的基质均已满足"
    GENERIC = "基质目标已满足或任务结束"

    def bad(checks) -> dict:
        return {c.label: c.detail for c in checks if not c.ok}


    def without_met(text: str) -> str:
        return "\n".join(x for x in text.splitlines() if MET_LINE not in x) + "\n"


    def ent(raw: dict, incomplete) -> dict:
        st = datetime(2026, 10, 16, 13, 54, 57, tzinfo=SERVER_TZ)
        fin = datetime(2026, 10, 16, 14, 11, 39, tzinfo=SERVER_TZ)
        return {"run_id": "2026-10-16/endfield/MaaEnd-09-53-33", "script": "MaaEnd", "user": "u", "ok": True,
                "started": st.isoformat(), "finished": fin.isoformat(), "incomplete": incomplete,
                "duration_known": True, "transitional": False, "failed_tasks": [],
                "raw": raw, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}


    def main() -> int:
        require("fixture has the real ending lines", MET_LINE in HIST and GENERIC in HIST)

        print("[10-16 14:10 那趟：勾选的武器基质已经齐了，没刷]")
        checks = maaend_checks(HIST + APP, [], own_log=True)
        b = bad(checks)
        require("基质刷取 is not judged undone", not any(k.startswith("基质刷取") for k in b), repr(b))
        msg = summarize(checks, "MaaEnd")
        require("no group alert for the whole run", msg is None, repr(msg))

        # With a real failure in the same run the summary is written: the target-met
        # task has its own line and is not listed as done.
        fake = ("[2026-10-16 14:12:00.000] 任务开始: ⚔️协议空间\n"
                "[2026-10-16 14:12:20.000] 任务完成: ⚔️协议空间\n")
        msg2 = summarize(maaend_checks(HIST + fake + APP, [], own_log=True), "MaaEnd") or ""
        lines2 = msg2.splitlines()
        require("own line 「勾选的武器基质已经齐了、没刷：基质刷取」",
                texts.OUTCOME_ESSENCE_MET_HEAD + "基质刷取" in lines2, msg2)
        require("not listed under 干成的",
                not any(ln.startswith("干成的") and "基质刷取" in ln for ln in lines2), msg2)

        print("[只有通用那句「基质目标已满足或任务结束」：照旧报]")
        generic = without_met(HIST)
        require("negative fixture keeps the generic line only", GENERIC in generic and MET_LINE not in generic)
        bg = bad(maaend_checks(generic + APP, [], own_log=True))
        require("still judged undone, with the seconds",
                "180 秒" in bg.get("基质刷取 真的刷了", ""), repr(bg))

        print("[日报：一行说清没刷、可以换武器]")
        d = tmpdir()
        raw = parse_maaend_log(REC / "MaaEnd-09-53-33.log")
        require("parser: target met recorded", raw.get("maaend_essence_met") is True, repr(raw.get("maaend_essence_met")))
        require("parser: not booked as a farm of 0 runs", "maaend_farm" not in raw, repr(raw.get("maaend_farm")))
        _t, body = core.format_daily("2026-10-16", [ent(raw, msg)])
        require("daily report says it plainly", texts.ESSENCE_TARGET_MET in body, body)
        require("... does not say 刷 基质刷取", "刷 基质刷取" not in body, body)
        require("... the row is not ⚠️ / 没干完", "没干完" not in body and not body.startswith("⚠️"), body)

        (d / "generic.log").write_text(generic, encoding="utf-8")
        graw = parse_maaend_log(d / "generic.log")
        require("parser: generic line alone is not target met",
                "maaend_essence_met" not in graw and graw.get("maaend_farm") == "基质刷取", repr(graw.get("maaend_farm")))

        for t in (texts.ESSENCE_TARGET_MET, texts.OUTCOME_ESSENCE_MET_HEAD):
            require(f"plain language: {t}", texts.plain(t) == [], repr(texts.plain(t)))

        return 1 if fails else 0


    sys.exit(main())


def _part_maaend_essence_stamina_out():
    """MaaEnd v2.34's 「体力不足，任务结束」 is the out-of-sanity ending of 基质刷取."""
    from ark_relay.features.collector_maaend import parse_maaend_log
    from ark_relay.features.outcome import maaend_checks

    LOG_PATH = fx_dir(Path(__file__), "fixtures") / "maaend-2026-10-19" / "MaaEnd-07-14-29.log"
    LOG = LOG_PATH.read_text(encoding="utf-8")
    STOP = "😴**体力不足，任务结束**"

    def bad(checks):
        return {c.label: c.detail for c in checks if not c.ok}

    require("the real record holds the stop line", STOP in LOG)
    got = bad(maaend_checks(LOG, []))
    require("「体力不足，任务结束」 counts as 基质刷取's ending, no 「真的刷了」 failure",
          "基质刷取 真的刷了" not in got)

    stripped = "\n".join(l for l in LOG.splitlines() if "体力不足" not in l and "如需继续刷取" not in l)
    got2 = bad(maaend_checks(stripped, []))
    require("without the stop line a 76 s 基质刷取 still alerts",
          "76 秒" in got2.get("基质刷取 真的刷了", ""))

    require("the sanity collector reads the new stop line as sanity exhausted",
          parse_maaend_log(LOG_PATH).get("sanity_exhausted") is True)

    from ark_relay.features import outcome
    from ark_relay.features import machinechecks as runs
    proto = dict((name, rx) for name, rx, _ in outcome._MAAEND_WORK)["协议空间"]
    require("协议空间 counts 「体力不足，任务结束」 as its ending", bool(proto.search(STOP)))
    require("协议空间 still counts the old 理智不足", bool(proto.search("理智不足")))
    require("#20 reads 「体力不足，任务结束」 as the stop", bool(runs._STOP.search("体力不足，任务结束")))
    require("#20 still reads the old 理智不足", bool(runs._STOP.search("理智不足")))
    require("#20 does not take any 体力不足 for the stop", runs._STOP.search("体力不足") is None)

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)


def _part_maaend_full_at_anchor():
    """Endfield's full-again time counts from the reading, and a floor 0 gets none."""
    import tempfile
    from datetime import datetime

    from ark_relay.core import collector
    from ark_relay.core.config import SERVER_TZ

    fin = datetime(2026, 10, 12, 10, 58, 40, tzinfo=SERVER_TZ)
    log = fx_dir(Path(__file__), "fixtures") / "maaend-sanity-1013" / "2026-10-12_MaaEnd-06-04-00.log"
    raw: dict = {}
    collector._enrich_record(raw, "MaaEnd", log, True, [], fin)
    check("full at from the reading's time", raw.get("sanity_full_at"), "理智将在 2026-10-13 19:45 回满。")

    raw = {"sanity": 0, "sanity_exhausted": True, "sanity_cap": 360}
    collector._enrich_record(raw, "MaaEnd", Path("/nonexistent/MaaEnd.log"), True, [], fin)
    check("exhausted and 0: no sentence", raw.get("sanity_full_at") or "", "")

    src = (fx_dir(Path(__file__), "fixtures") / "maaend-sanity-1013" / "2026-10-13_MaaEnd-05-36-57.log").read_text(encoding="utf-8")
    fin = datetime(2026, 10, 13, 9, 54, tzinfo=SERVER_TZ)
    for first, want_left, want in ((160, 0, "理智将在 2026-10-15 05:05 回满。"), (60, 0, "")):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "MaaEnd.log"
            p.write_text(src.replace("当前理智 198/360", f"当前理智 {first}/360"), encoding="utf-8")
            raw = {}
            collector._enrich_record(raw, "MaaEnd", p, True, [], fin)
        check(f"read {first}, exhausted: left", raw.get("sanity"), want_left)
        check(f"read {first}, exhausted: full-at", raw.get("sanity_full_at") or "", want)


def _part_maaend_round_upper_bound():
    """A MaaEnd round is judged on its own error pictures and app-log lines only,
not on those of the rounds after it.
    """
    import os
    import types
    from datetime import datetime, timedelta


    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.features import handle as gamelogs, handle as verdict


    def at(h, m, s=0):
        return datetime(2026, 10, 1, h, m, s, tzinfo=SERVER_TZ)


    def touch(p: Path, when: datetime):
        os.utime(p, (when.timestamp(), when.timestamp()))


    START1, END1 = at(15, 24, 12), at(15, 29, 59)
    UNTIL1 = END1 + timedelta(minutes=5)
    LATER_SHOT = "2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png"

    root = tmpdir()
    oe = root / "debug" / "on_error"
    oe.mkdir(parents=True)
    (oe / LATER_SHOT).write_bytes(b"png")
    touch(oe / LATER_SHOT, at(16, 44, 46))
    own = "2026.10.01-15.27.03.000___Own.png"
    (oe / own).write_bytes(b"png")
    touch(oe / own, at(15, 27, 3))
    app = root / "debug" / "2026-10-01-3.log"
    app.write_text("\n".join([
        "2026-10-01 15:24:20 INFO  [App] 开始任务: 🛍️信用点购物",
        "2026-10-01 15:29:50 INFO  [App] 任务完成: 🛍️信用点购物",
        "2026-10-01 16:12:20 INFO  [App] 开始任务: 🛍️信用点购物",
        "  continuation of the 16:12 line",
        "2026-10-01 16:58:20 INFO  [App] 任务失败: 🛍️信用点购物",
    ]) + "\n", encoding="utf-8")
    touch(app, at(16, 58, 20))

    def call(f, *a):
        try:
            return f(*a)
        except TypeError as exc:     # the code before the bound took no `until`
            return f"TypeError: {exc}"


    print("[pictures: only the round's own, up to finish + 5 min]")
    check("the first round's pictures", call(gamelogs._maaend_new_shots, root, START1, UNTIL1), [own])
    check("no bound -> as before", gamelogs._maaend_new_shots(root, START1), sorted([LATER_SHOT, own]))

    print("\n[app log: lines cut by their own stamps]")
    text = call(gamelogs._maaend_app_log, root, START1, UNTIL1)
    check("keeps the round's lines", "15:29:50" in text, True)
    check("drops the later round's lines", ("16:12:20" in text, "continuation" in text, "16:58:20" in text),
          (False, False, False))
    check("a file with no stamps is kept whole",
          call(getattr(gamelogs, "_in_window", lambda *a: None), "no stamp here\nnor here", START1, UNTIL1),
          "no stamp here\nnor here")

    print("\n[the outcome check, real functions: judged without the later round's picture and lines]")
    hist = root / "MaaEnd-11-23-07.log"
    hist.write_text("[2026-10-01 15:24:20.000] 任务开始: 🛍️信用点购物\n"
                    "[2026-10-01 15:29:40.000] 任务完成: 🛍️信用点购物\n", encoding="utf-8")
    rec = RunRecord(run_id="2026-10-01/endfield/MaaEnd-11-23-07", script="MaaEnd", user="endfield",
                    started=START1, finished=END1, ok=True, log_path=hist)
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=root, state_dir=root))
    msg = verdict._verify_outcome(eng, rec) or ""
    check("the later picture is not named", LATER_SHOT in msg, False)
    check("its own picture is (the round, like 10-01's, has no 「自动执行任务完成」)", own in msg, True)


def _part_maaend_sanity():
    """MaaEnd 的「剩余理智」报的是扣费之前的数字。"""
    import os

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    from ark_relay.core import collector
    from ark_relay.features import collector_maaend

    def parse(text):
        p = TMP / "x.log"
        p.write_text(text, encoding="utf-8")
        return collector.parse_maaend_log(p)

    print("[最后一次扣成了 —— 要减掉一次消耗]")
    got = parse("""\
[2026-08-24 09:36:31.345] 当前理智 201/360
[2026-08-24 09:36:32.000] 进入协议空间成功
[2026-08-24 09:37:24.957] 当前理智 201/360
[2026-08-24 09:37:25.648] 尝试使用理智消耗许可
[2026-08-24 09:37:26.000] 确认领取奖励
[2026-08-24 09:37:31.284] 理智不足，结束任务
""")
    check("看不到下降时用兜底的单次消耗", got.get("sanity"), 201 - collector_maaend._END_PS_COST)
    check("上限照报", got.get("sanity_cap"), 360)

    print("\n[最后一次被拒了 —— 读数就是终值]")
    got = parse("""\
[2026-08-25 09:38:08.067] 当前理智 241/360
[2026-08-25 09:38:25.358] 进入协议空间成功
[2026-08-25 09:39:21.584] 当前理智 241/360
[2026-08-25 09:39:22.286] 尝试使用理智消耗许可
[2026-08-25 09:39:31.507] 进入协议空间成功
[2026-08-25 09:40:21.032] 当前理智 81/360
[2026-08-25 09:40:21.767] 尝试使用理智消耗许可
[2026-08-25 09:40:22.006] 理智不足，尝试不使用理智消耗许可
[2026-08-25 09:40:28.560] 理智不足，结束任务
""")
    check("最后一次没扣就不减", got.get("sanity"), 81)
    check("协议空间次数", got.get("protocol_runs"), 2)
    check("知道是理智不足才收工", got.get("sanity_exhausted"), True)

    print("\n[日志里有真实下降时，用实测值而不是兜底常量]")
    # 单次消耗 40 的场景（关卡等级不同）：最后一次扣成，应减 40 而不是 160。
    got = parse("""\
[2026-08-25 10:00:00.000] 当前理智 120/360
[2026-08-25 10:00:01.000] 尝试使用理智消耗许可
[2026-08-25 10:01:00.000] 当前理智 80/360
[2026-08-25 10:01:01.000] 尝试使用理智消耗许可
[2026-08-25 10:01:02.000] 确认领取奖励
""")
    check("按实测的 40 减，而不是兜底的 160", got.get("sanity"), 40)

    print("\n[一条读数都没有时不要瞎报]")
    check("没有理智行就不写这个字段",
          "sanity" in parse("[2026-08-25 09:00:00.000] 任务完成: 🎁基建任务\n"), False)

    print("\n[回满时间：MAA 自己写在 JSON 里，另外两个得算]")
    from datetime import datetime
    from ark_relay.core.config import SERVER_TZ
    ref = datetime(2026, 8, 25, 9, 42, tzinfo=SERVER_TZ)
    # 终末地每 7 分 12 秒 1 点：还差 279 点 → 2008.8 分钟 ≈ 33.5 小时。
    check("终末地 81/360 的回满时刻",
          collector._full_at_sentence(81, 360, collector._END_SANITY_SEC_PER_POINT, ref),
          "理智将在 2026-08-26 19:10 回满。")
    # 鸣潮每 6 分钟 1 点：还差 198 点 → 1188 分钟 = 19.8 小时。
    ref2 = datetime(2026, 8, 25, 13, 19, tzinfo=SERVER_TZ)
    check("鸣潮 42/240 的回满时刻",
          collector._full_at_sentence(42, 240, collector._OKWW_SEC_PER_POINT, ref2),
          "理智将在 2026-08-26 09:07 回满。")
    check("已经满了就不说回满", collector._full_at_sentence(240, 240, 360, ref2), "")
    check("超上限也不说", collector._full_at_sentence(400, 360, 432, ref), "")
    # 速率本身也钉住：改错了会让每天的报告都给出错误的时刻。
    check("终末地 7 分 12 秒", collector._END_SANITY_SEC_PER_POINT, 432)
    check("鸣潮 6 分钟", collector._OKWW_SEC_PER_POINT, 360)

    print("\n[自动采集：没走通的路线要点名，不只数个数（2026-09-11 那趟真实日志）]")
    real = fx_dir(Path(__file__), "fixtures") / "collect-retry-2026-09-11" / "automas-MaaEnd-06-17-17.log"
    got = collector.parse_maaend_log(real)
    check("走通 15/17（线路1-3 和 路线4-17 两种写法都算）", (got.get("maaend_collect_done"), got.get("maaend_collect_total")), (15, 17))
    check("没走通的名字", got.get("maaend_collect_failed"), ["路线15：红矛叶", "路线16：协议纹石"])
    check("没走通的路线号（给收窄用）", got.get("maaend_collect_failed_ids"), ["Route15", "Route16"])

    print("\n[自动采集：不是采集日的 0 分钟不算「做了」（2026-09-05 周六真实日志）]")
    real = fx_dir(Path(__file__), "replay") / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log"
    got = collector.parse_maaend_log(real)
    check("记下是哪天被排班跳过的", got.get("maaend_collect_skipped"), "周六")
    check("跳过的那天没有路线计数", "maaend_collect_total" in got, False)
    from ark_relay.core import ledger as _core
    _e = {"ok": True, "raw": got, "started": "2026-09-05T09:00:00+08:00"}
    _did, _cost, _out, _left, _notes = _core._block_maaend(_e, got, datetime(2026, 9, 5, 9, 55, tzinfo=SERVER_TZ))
    check("备注说的是按排班跳过", any("周六不是采集日" in n and "按排班跳过" in n for n in _notes), True)
    check("「做了」里不再出现自动采集", any("自动采集" in n and "做了" in n for n in _notes), False)


def _part_maaend_sanity_fit():
    """Endfield sanity is reported as a figure only when the log's readings fit the
per-claim rule (40 per 「补充理智」 booster, collector_maaend._claims_fit).
    """
    import tempfile
    from datetime import datetime

    from ark_relay.core import ledger as ledger_rows
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.collector_maaend import parse_maaend_log

    LOG = fx_dir(Path(__file__), "fixtures") / "maaend-sanity-1013" / "2026-10-08_MaaEnd-05-29-15.log"


    fin = datetime(2026, 10, 8, 9, 57, tzinfo=SERVER_TZ)


    def cost_row(o):
        return ledger_rows._block_maaend({"ok": True, "raw": o, "sanity": o.get("sanity")}, o, fin)[1]


    real = parse_maaend_log(LOG)
    require("real log fits: 720 spent", real.get("maaend_sanity_spent") == 720 and not real.get("maaend_sanity_unfit"),
            f"got {real.get('maaend_sanity_spent')!r}, unfit {real.get('maaend_sanity_unfit')!r}")
    require("real log cost row", cost_row(real) == ["理智 720，加强剂 14"], f"got {cost_row(real)!r}")

    lines = LOG.read_text(encoding="utf-8").splitlines(keepends=True)
    first = next(i for i, x in enumerate(lines) if "补充理智" in x)
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / LOG.name
        bad.write_text("".join(lines[:first] + lines[first + 1:]), encoding="utf-8")
        o = parse_maaend_log(bad)
    require("misfit: no spent figure", o.get("maaend_sanity_spent") is None, f"got {o.get('maaend_sanity_spent')!r}")
    require("misfit: not filled in later", o.get("maaend_sanity_runs_only") is None, f"got {o.get('maaend_sanity_runs_only')!r}")
    require("misfit: cost row says 没读到", cost_row(o) == ["理智消耗没读到，加强剂 13"], f"got {cost_row(o)!r}")


def _part_maaend_sanity_one_formula():
    """Endfield sanity spent and left come from one rule, checked on real logs."""
    from datetime import datetime

    from ark_relay.core import ledger as ledger_rows
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.collector_maaend import parse_maaend_log

    D = fx_dir(Path(__file__), "fixtures") / "maaend-sanity-1013"

    CASES = [
        ("2026-10-13_MaaEnd-05-36-57.log", 1, 160, 38, None),
        ("2026-10-07_MaaEnd-05-29-05.log", 2, 240, 37, None),
        ("2026-10-08_MaaEnd-05-29-15.log", 5, 720, 78, 14),
        ("2026-10-08_MaaEnd-06-34-21.log", 1, 80, 5, None),
    ]
    for name, runs, spent, left, potions in CASES:
        o = parse_maaend_log(D / name)
        check(f"{name} runs", o.get("maaend_farm_runs"), runs)
        check(f"{name} spent", o.get("maaend_sanity_spent"), spent)
        check(f"{name} left", o.get("sanity"), left)
        check(f"{name} potions", o.get("maaend_medicine"), potions)

    # The report row: a run that claimed is never 「一次没开成」, even with no figure.
    fin = datetime(2026, 10, 13, 9, 54, tzinfo=SERVER_TZ)
    raw = {"maaend_farm": "协议空间", "maaend_farm_runs": 1, "sanity_exhausted": True,
           "maaend_farm_drops": {"折金票": 68000}}
    _did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": raw}, raw, fin)
    check("ran, no figure: not 一次没开成", cost, ["理智消耗没读到"])
    raw = {"maaend_farm": "协议空间", "sanity_exhausted": True}
    _did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": raw}, raw, fin)
    check("no run, exhausted: 一次没开成", cost, ["理智不足，一次没开成"])
    o = parse_maaend_log(D / "2026-10-13_MaaEnd-05-36-57.log")
    _did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": o, "sanity": o["sanity"]}, o, fin)
    check("10-13 cost row", cost, ["理智 160，加强剂 0"])


def _part_maaend_update_after_done():
    """MaaEnd restarting itself into a new build after its shift's round was done: no make-up, no push.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.features import collect_retry
    from ark_relay.features import handle, handle as unresolved
    from ark_relay.core import ledger as core
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    def automas_dir(queues) -> Path:
        """An AUTO-MAS config dir shaped like the machine's: queues = [(name, [times], [kinds])]."""
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
        for k, p in paths.items():
            sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
        qc = {"instances": []}
        for n, (name, times, kinds) in enumerate(queues):
            uid = f"q{n}"
            qc["instances"].append({"uid": uid})
            ts = {"instances": []}
            for i, t in enumerate(times):
                ts[f"t{i}"] = {"Info": {"Enabled": True, "Time": t}}
            items = {"instances": []}
            for i, k in enumerate(kinds):
                items[f"i{i}"] = {"Info": {"ScriptId": f"s-{k}"}}
            qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                       "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root

    # The machine: 早班 09:00 runs MaaEnd, 晚班 21:30 is MAA only.
    MACHINE = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
    # For the other-shift case MaaEnd has to be in both.
    BOTH = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA", "MaaEnd"])])

    class Src:
        def fetch(self, seen):
            return []

    class Lines(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    LINES = Lines()
    handle.log.addHandler(LINES)
    handle.log.setLevel(logging.DEBUG)

    handle._ship_evidence = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    collect_retry.restore_master = lambda cfg: ""

    def mxu_install(at: datetime, version: str) -> None:
        """MXU's own log for the attempt that installed `version` at its start."""
        f = MAAEND / "debug" / f"{at:%Y-%m-%d}-1.log"
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        s = at.strftime("%Y-%m-%d %H:%M:%S")
        f.write_text(old + "\n".join([
            f"{s} INFO  [App] 检测到待安装更新: {version}",
            f"{s} INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11002.zip -> D:\\ark\\maaend",
            f"{s} INFO  [App] 更新安装完成",
            f"{s} INFO  [App] 已清除待安装更新信息",
        ]) + "\n", encoding="utf-8")

    def t(day, hh, mm, ss=0):
        return datetime(2026, 10, day, hh, mm, ss, tzinfo=SERVER_TZ)

    def success(day, run, start, minutes):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(minutes=minutes), ok=True, failed_tasks=[],
                         raw={"maaend_result": "Success!"})

    def restart(day, run, start):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(seconds=30), ok=False,
                         failed_tasks=["赠送干员礼物", "据点交易", "日常奖励领取"],
                         raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})

    mxu_install(t(4, 9, 50, 53), "v2.32.0-beta.1")
    mxu_install(t(4, 21, 50, 53), "v2.32.0-beta.9")
    mxu_install(t(5, 11, 30, 14), "v2.32.0-beta.2")
    S4 = success(4, "05-26-41", t(4, 9, 26, 41), 23)
    R4 = restart(4, "05-50-53", t(4, 9, 50, 53))
    S5 = success(5, "06-39-48", t(5, 10, 39, 48), 49)
    R5 = restart(5, "07-30-14", t(5, 11, 30, 14))

    def build(automas, undone=None):
        cfg = Config()
        cfg.state_dir = tmpdir() / "state"   # its own tech/ next to it (techlog.tech_dir)
        cfg.automas_dir = automas
        cfg.maaend_dir = MAAEND
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: undone
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e

    def run(e, recs):
        LINES.lines.clear()
        for r in recs:
            handle._handle(e, r)
        e._flush_pending()
        return [(ti, b) for ti, b, a in e.notifier.sent if a]

    def said(fragment):
        return any(fragment in ln for ln in LINES.lines)

    DROPPED = "前面那趟已经做完"

    print("[10-04 as it landed: success, then the update restart, same second, same shift]")
    e = build(MACHINE)
    got = run(e, [S4, R4])
    check("nothing to the group", got, [])
    check("no notice of any kind (not Server酱 either)", e.notifier.sent, [])
    check("not held", dict(e._pending), {})
    check("no self-heal either", dict(e._recovered), {})
    check("the log says the earlier round was done, this was the update, daily report only",
          said(f"{R4.run_id} 前面那趟已经做完（{S4.run_id}），这趟是装新版 v2.32.0-beta.1 重启，只进日报"))
    check("no 「先压着」", said("先压着看后面的重试"), False)
    check("no 「最终失败」", said("最终失败"), False)
    ledger = {x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}
    check("the restart stays in the ledger, named as the update",
          (ledger.get(R4.run_id, {}).get("raw") or {}).get("maaend_update_restart"), "v2.32.0-beta.1")
    check("the success stays in the ledger", ledger.get(S4.run_id, {}).get("ok"), True)
    entries = e.state.read_ledger("2026-10-04")
    check("daily report books the restart as the update", core.episode_kinds(entries).get(R4.run_id), "update")
    tech: list = []
    title, body = core.format_daily("2026-10-04", entries, tech=tech)
    print("    " + title)
    print("    " + body.replace("\n", "\n    ")[:500])
    check("the daily title counts no MaaEnd failure", "终末地失败" in title, False)
    check("the daily row says it was the update", "终末地装了新版后自己重启，用掉一次重试，不算失败" in body)
    check("the version is in the technical log line, not the report",
          ("v2.32.0-beta.1" in body, any("MaaEnd 装新版 v2.32.0-beta.1" in t for t in tech)), (False, True))
    e._flush_pending()
    check("a later tick says nothing", e.notifier.sent, [])
    handle._handle(e, R4)      # the same record replayed (handling broke off midway)
    check("a replay of the same record says nothing either", e.notifier.sent, [])

    print("\n[the same pair the other way round: the update restart lands first]")
    e = build(MACHINE)
    got = run(e, [R4, S4])
    check("nothing to the group", got, [])
    check("not held", dict(e._pending), {})
    check("not turned into a self-heal", dict(e._recovered), {})
    check("the log says why", said(f"{R4.run_id} 前面那趟已经做完（{S4.run_id}）"))
    check("no 「重试后成功」 (nothing was retried)", said("重试后成功"), False)
    check("no notice of any kind", e.notifier.sent, [])
    check("the daily report books it as the update too",
          core.episode_kinds(e.state.read_ledger("2026-10-04")).get(R4.run_id), "update")

    print("\n[10-05 as it landed: 06-39-48 done, 07-30-14 installs v2.32.0-beta.2]")
    e = build(MACHINE)
    got = run(e, [S5, R5])
    check("nothing to the group", got, [])
    check("not held", dict(e._pending), {})
    check("the log says why", said(f"{R5.run_id} 前面那趟已经做完（{S5.run_id}），这趟是装新版 v2.32.0-beta.2 重启，只进日报"))

    print("\n[the success was in another shift: the restart is held and rings as before]")
    late = restart(4, "17-50-53", t(4, 21, 50, 53))
    e = build(BOTH)
    check("the two are in different shifts",
          (unresolved.where(e, S4)[1], unresolved.where(e, late)[1]), ("早班", "晚班"))
    got = run(e, [S4, late])
    check("not dropped", said(DROPPED), False)
    check("held, then one alarm for 晚班", (len(got), bool(got) and "晚班" in got[0][0]), (1, True))
    e = build(BOTH)
    got = run(e, [late, S4])
    check("reverse order: not dropped either", said(DROPPED), False)
    check("the daily report does not hide it", core.episode_kinds(e.state.read_ledger("2026-10-04")).get(late.run_id), None)

    print("\n[a success that left work undone does not count]")
    e = build(MACHINE, undone="MaaEnd 这一轮有 1 项没干成：\n· 据点交易：没做")
    LINES.lines.clear()
    handle._handle(e, S4)
    handle._handle(e, R4)
    check("not dropped", said(DROPPED), False)
    check("held as before", list(e._pending), [("MaaEnd", "endfield")])
    e = build(MACHINE, undone="MaaEnd 这一轮有 1 项没干成：\n· 据点交易：没做")
    LINES.lines.clear()
    handle._handle(e, R4)
    handle._handle(e, S4)
    check("reverse order: not dropped either", said(DROPPED), False)
    check("reverse order: the held restart takes the usual path (retry healed)",
          (list(e._pending), list(e._recovered)), ([], [("MaaEnd", "endfield")]))
    check("reverse order: not marked as the update on the ledger",
          ({x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}[R4.run_id].get("raw") or {})
          .get("maaend_update_after_done"), None)

    print("\n[a success stopped by the red button does not count]")
    e = build(MACHINE)
    e.state.append_ledger(S4)
    e.state.mark_raw("2026-10-04", S4.run_id, "manual_stop", "10-04 09:49 停一切")
    check("no done round", unresolved.done_in_shift(e, R4), "")
    e.state.mark_raw("2026-10-04", S4.run_id, "manual_stop", "")
    check("without the stop it is the done round", unresolved.done_in_shift(e, R4), S4.run_id)

    print("\n[without any success the restart is held as before (10-01's path)]")
    e = build(MACHINE)
    LINES.lines.clear()
    handle._handle(e, R4)
    check("held", list(e._pending), [("MaaEnd", "endfield")])
    check("「先压着」 as before", said("先压着看后面的重试"))

    def reds(e, fragment):
        """Red items in e's technical log whose text names `fragment`."""
        from ark_relay.core import statestore as techlog
        return [x for f in sorted(techlog.tech_dir(e.cfg.state_dir).glob("*.md"))
                for _, x in techlog.unhandled(f.read_text(encoding="utf-8")) if fragment in x]

    mxu_install(t(12, 10, 58, 11), "v2.33.0-beta.2")
    R12 = restart(12, "06-58-11", t(12, 10, 58, 11))
    S12 = success(12, "06-58-38", t(12, 10, 58, 38), 30)

    print("\n[10-12: the success started after the restart lands first -> healed by retry, one red item]")
    e = build(MACHINE)
    e.state.append_ledger(S12)
    check("a round started after the restart is not the shift's done round", unresolved.done_in_shift(e, R12), "")
    e = build(MACHINE)
    got = run(e, [S12, R12])
    check("not let go as 「前面那趟已经做完」", said(DROPPED), False)
    check("nothing to the group", got, [])
    check("not held (its retry already got through)", (dict(e._pending), dict(e._recovered)), ({}, {}))
    check("one 「自愈待查」 red item naming the restart", len(reds(e, R12.run_id)), 1)
    check("the daily report books it as the update",
          core.episode_kinds(e.state.read_ledger("2026-10-12")).get(R12.run_id), "update")

    print("\n[10-12, the other way round: the restart lands first -> healed by retry, one red item]")
    e = build(MACHINE)
    got = run(e, [R12, S12])
    check("not let go as 「前面那趟已经做完」", said(DROPPED), False)
    check("nothing to the group", got, [])
    check("nothing left held", (dict(e._pending), dict(e._recovered)), ({}, {}))
    check("one 「自愈待查」 red item naming the restart", len(reds(e, R12.run_id)), 1)

    F12 = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-00", script="MaaEnd", user="endfield",
                    started=t(12, 10, 4, 0), finished=t(12, 10, 40, 0), ok=False, failed_tasks=["协议空间"],
                    raw={"maaend_result": "MaaEnd 部分任务执行失败: 协议空间"})

    print("\n[10-12: a held failure is not replaced by the update restart that follows it]")
    e = build(MACHINE)
    LINES.lines.clear()
    handle._handle(e, F12)
    handle._handle(e, R12)
    check("the held record is still the failure", [r.run_id for r in e._pending.values()], [F12.run_id])
    handle._handle(e, S12)
    e._flush_pending()
    check("nothing to the group", [x for x in e.notifier.sent if x[2]], [])
    check("the red item names the failure and its task",
          [("协议空间" in x) for x in reds(e, F12.run_id)], [True])


def _part_maaend_update_record():
    """AUTO-MAS's own MaaEnd update record is not a run; stage prefixes are not failures."""
    import json
    import logging
    import os
    from datetime import datetime

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HISTORY = TMP / "history"
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    os.environ.update(ARK_HISTORY_DIR=str(HISTORY), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.core import collector
    from ark_relay.features import errwatch
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features import handle, handle as records
    from ark_relay.features import collect_retry

    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines: list[tuple[str, int, str]] = []

        def emit(self, r):
            self.lines.append((r.name, r.levelno, r.getMessage()))

    grab = Grab()
    logging.getLogger(errwatch.ARK).addHandler(grab)
    logging.getLogger(errwatch.ARK).setLevel(logging.DEBUG)

    class Src:
        def fetch(self, seen):
            return []

    DAY = HISTORY / "2026-10-12" / "endfield"
    DAY.mkdir(parents=True)

    def write(stem, result, log_lines, mtime):
        (DAY / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False, indent=4),
                                          encoding="utf-8")
        (DAY / f"{stem}.log").write_text("".join(x + "\n" for x in log_lines), encoding="utf-8")
        t = datetime(2026, 10, 12, *mtime, tzinfo=SERVER_TZ).timestamp()
        for suffix in (".json", ".log"):
            os.utime(DAY / f"{stem}{suffix}", (t, t))

    CLOSE = "❌关闭游戏（PC）"

    # Attempt 1: 协议空间 fails, the round closes.
    write("MaaEnd-06-04-00", "MaaEnd 部分任务执行失败: ⚔️协议空间", [
        "[2026-10-12 10:04:05.000] 窗口连接成功: Endfield",
        "[2026-10-12 10:05:19.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-12 10:07:43.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-12 10:07:43.100] 任务开始: 🔧装备制造",
        "[2026-10-12 10:08:02.000] 任务完成: 🔧装备制造",
        "[2026-10-12 10:08:02.100] 任务开始: ⚔️协议空间",
        "[2026-10-12 10:57:50.000] 任务失败: ⚔️协议空间",
        f"[2026-10-12 10:57:50.100] 任务开始: {CLOSE}",
        f"[2026-10-12 10:57:53.000] 任务完成: {CLOSE}",
    ], (11, 38, 13))
    # AUTO-MAS's update step: its four status lines (AUTO-MAS app.log 605-608), no timestamps.
    write("MaaEnd-06-58-11", "[更新] Success!", [
        "首阶段检测到 MaaEnd 更新，正在确认安装结果",
        "正在准备 MaaEnd 更新会话",
        "MaaEnd 正在检查并安装更新",
        "MaaEnd 已更新到 v2.33.0-beta.2",
    ], (11, 38, 13))
    # Attempt 2: everything done.
    write("MaaEnd-06-58-38", "Success!", [
        "[2026-10-12 10:58:40.000] 窗口连接成功: Endfield",
        "[2026-10-12 10:59:55.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-12 11:01:43.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-12 11:01:43.100] 任务开始: 🔧装备制造",
        "[2026-10-12 11:01:59.000] 任务完成: 🔧装备制造",
        "[2026-10-12 11:01:59.100] 任务开始: ⚔️协议空间",
        "[2026-10-12 11:30:00.000] 任务完成: ⚔️协议空间",
        f"[2026-10-12 11:38:05.000] 任务开始: {CLOSE}",
        f"[2026-10-12 11:38:08.000] 任务完成: {CLOSE}",
    ], (11, 38, 13))
    # MXU's own log: the install AUTO-MAS triggered right after the update step began.
    (MAAEND / "debug" / "2026-10-12-4.log").write_text("\n".join([
        "2026-10-12 10:58:12 INFO  [App] 检测到待安装更新: v2.33.0-beta.2",
        "2026-10-12 10:58:13 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11021.zip -> D:\\ark\\maaend",
        "2026-10-12 10:58:14 INFO  [App] 更新安装完成",
    ]) + "\n", encoding="utf-8")

    handle._ship_evidence = lambda eng, rec: ""
    collect_retry.restore_master = lambda cfg: ""
    handle._weekly_gates = lambda eng, rec: None

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e

    def collector_lines(level):
        return [m for n, lv, m in grab.lines if n == "ark.collector" and lv == level]

    print("[10-12 replay: the collector sees two runs, not three]")
    got = collector.scan(HISTORY, set(), MAAEND)
    check("run ids", [r.run_id.rsplit("/", 1)[1] for r in got], ["MaaEnd-06-04-00", "MaaEnd-06-58-38"])
    check("verdicts", [(r.ok, r.failed_tasks) for r in got], [(False, ["协议空间"]), (True, [])])
    update_info = [m for m in collector_lines(logging.INFO) if "MaaEnd-06-58-11" in m]
    check("the update is one technical-log line", len(update_info), 1)
    check("it carries AUTO-MAS's words", bool(update_info) and "[更新] Success!" in update_info[0], True)
    check("no collector warning (group) for it", collector_lines(logging.WARNING), [])
    collector.scan(HISTORY, {r.run_id for r in got}, MAAEND)
    check("the next scan does not log it again",
          len([m for m in collector_lines(logging.INFO) if "MaaEnd-06-58-11" in m]), 1)

    print("\n[10-12 replay through the handler: recovered on retry, no update label]")
    grab.lines.clear()
    e = build()
    for r in got:
        handle._handle(e, r)
    e._flush_pending()
    ledger = e.state.read_ledger("2026-10-12")
    check("ledger rows", [x["run_id"].rsplit("/", 1)[1] for x in ledger], ["MaaEnd-06-04-00", "MaaEnd-06-58-38"])
    check("no 「重试被用掉」 anywhere in the ledger",
          any("重试被用掉" in t for x in ledger for t in x.get("failed_tasks") or []), False)
    check("no update-restart mark", [(x.get("raw") or {}).get("maaend_update_restart") for x in ledger], [None, None])
    check("attempts", records._attempts(e, got[-1], "2026-10-12"), 2)
    healed = [m for n, lv, m in grab.lines if "自己好了" in m]
    check("one recovery line", len(healed), 1)
    check("it says a retry healed it, ran 2 times",
          bool(healed) and healed[0].startswith("⚠️ MaaEnd 中途失败过，重试后成功") and "跑了 2 次" in healed[0], True)
    check("nothing says 重试被用掉", [m for n, lv, m in grab.lines if "重试被用掉" in m], [])
    # (Machine-check pushes about task-end pictures fire here because the fixture has none;
    # they are not about this record.)
    check("no push mentions the update", [t for t, b, a in e.notifier.sent if "更新" in t + b], [])

    def judge(stem, result, log_lines=("[2026-10-13 12:00:00.000] 窗口连接成功: Endfield",)):
        d = HISTORY / "2026-10-13" / "endfield"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False), encoding="utf-8")
        (d / f"{stem}.log").write_text("".join(x + "\n" for x in log_lines), encoding="utf-8")
        return collector.parse_record(d / f"{stem}.json", HISTORY, MAAEND)

    print("\n[stage prefixes are stripped before judging]")
    r = judge("MaaEnd-01-00-00", "[日常] Success!")
    check("[日常] Success! is a success", (r.ok, r.failed_tasks), (True, []))
    r = judge("MaaEnd-01-00-01", "[自动采集] MaaEnd 部分任务执行失败: 🧺自动采集")
    check("[自动采集] failure names its task", (r.ok, r.failed_tasks), (False, ["自动采集"]))
    r = judge("MaaEnd-01-00-02", "[送货] 未捕获到日志")
    check("[送货] stub stays transitional", (r.ok, r.transitional), (False, True))

    print("\n[update records]")
    grab.lines.clear()
    check("[更新] 跳过更新 is not a run", judge("MaaEnd-01-00-03", "[更新] 跳过更新"), None)
    check("…technical log only", ([m for m in collector_lines(logging.INFO) if "MaaEnd-01-00-03" in m] != [],
                                  collector_lines(logging.WARNING)), (True, []))
    upd_fail = "MaaEnd 更新失败，已停止后续任务: MXU 日志报告安装失败，已停止后续任务"
    r = judge("MaaEnd-06-58-11", f"[更新] {upd_fail}", [upd_fail])
    check("a failed update is a real failure", (r.ok, r.failed_tasks), (False, [upd_fail]))
    r.started = datetime(2026, 10, 12, 10, 58, 11, tzinfo=SERVER_TZ)   # inside the MXU install window
    records._mark_update_restart(build(), r)
    check("…the restart rule leaves it alone", (r.transitional, r.raw.get("maaend_update_restart")), (False, None))
    r = judge("MaaEnd-01-00-05", "[更新] MaaEnd 更新被中止")
    check("an aborted update is a real failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 更新被中止"]))

    print("\n[a failed update through the handler: booked as a failure, not as an update restart]")
    d14 = HISTORY / "2026-10-14" / "endfield"
    d14.mkdir(parents=True)
    (d14 / "MaaEnd-06-58-11.json").write_text(json.dumps({"maaend_result": f"[更新] {upd_fail}"}, ensure_ascii=False),
                                              encoding="utf-8")
    (d14 / "MaaEnd-06-58-11.log").write_text(upd_fail + "\n", encoding="utf-8")
    (MAAEND / "debug" / "2026-10-14-1.log").write_text(
        "2026-10-14 10:58:12 INFO  [App] 检测到待安装更新: v9.9.9\n2026-10-14 10:58:14 INFO  [App] 更新安装完成\n",
        encoding="utf-8")
    e14 = build()
    for rec in collector.scan(HISTORY, {x["run_id"] for d in ("2026-10-12", "2026-10-13")
                                        for x in e.state.read_ledger(d)} | {r.run_id for r in got}, MAAEND):
        if rec.run_id.startswith("2026-10-14/"):
            handle._handle(e14, rec)
    row = {x["run_id"]: x for x in e14.state.read_ledger("2026-10-14")}.get("2026-10-14/endfield/MaaEnd-06-58-11") or {}
    check("booked, failed, with AUTO-MAS's words, not relabelled",
          (row.get("ok"), row.get("failed_tasks"), (row.get("raw") or {}).get("maaend_update_restart"), row.get("transitional")),
          (False, [upd_fail], None, False))

    print("\n[an unknown prefix is not judged a success]")
    grab.lines.clear()
    r = judge("MaaEnd-01-00-06", "[新阶段] Success!")
    check("booked as a failure with AUTO-MAS's words", (r.ok, r.failed_tasks), (False, ["[新阶段] Success!"]))
    said = [m for m in collector_lines(logging.INFO) if "[新阶段]" in m]
    check("one technical-log line naming the prefix, no group warning",
          (len(said), collector_lines(logging.WARNING)), (1, []))
    judge("MaaEnd-01-00-06", "[新阶段] Success!")
    check("not repeated on the next read", len([m for m in collector_lines(logging.INFO) if "[新阶段]" in m]), 1)


def _part_maaend_update_restart():
    """A MaaEnd attempt spent installing its own update is not a game failure; healed, it is not pushed.
    """
    import json
    import os
    from datetime import datetime

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (TMP / "history").mkdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.features import collect_retry
    from ark_relay.features import handle
    from ark_relay.core import engine as eng_mod
    from ark_relay.features.collector_maaend import update_restart_version
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    class Src:
        def fetch(self, seen):
            return []

    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)

    (MAAEND / "debug" / "2026-10-01-3.log").write_text("\n".join([
        "2026-10-01 15:24:11 INFO  [App] 检查更新: MaaEnd, 当前版本: v2.31.0-beta.5, 频道: beta",
        "2026-10-01 15:24:12 INFO  [App] 发现新版本: v2.31.0-beta.6",
        "2026-10-01 15:24:14 INFO  [App] 已保存待安装更新信息: v2.31.0-beta.6",
    ]) + "\n", encoding="utf-8")
    (MAAEND / "debug" / "2026-10-01-4.log").write_text("\n".join([
        "2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6",
        "2026-10-01 16:11:06 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\10697.zip -> D:\\ark\\maaend",
        "2026-10-01 16:11:07 INFO  [App] 增量更新: deleted=0, added=0, modified=4",
        "2026-10-01 16:11:07 INFO  [App] 更新安装完成",
        "2026-10-01 16:11:07 INFO  [App] 已清除待安装更新信息",
    ]) + "\n", encoding="utf-8")

    FIFTEEN = ["赠送干员礼物", "装备制造", "拜访好友", "基建任务", "信用点购物", "转交委托", "据点交易",
               "环境监测", "自动囤货", "售卖弹性物资", "购买稳定物资", "协议空间", "选剑演武", "自动采集", "日常奖励领取"]

    def runs(with_success=True):
        out = [RunRecord(run_id="2026-10-01/endfield/MaaEnd-11-23-07", script="MaaEnd", user="endfield",
                         started=at(15, 24, 12), finished=at(16, 10, 0), ok=False,
                         failed_tasks=["MaaEnd 进程超时"], raw={"maaend_result": "MaaEnd 进程超时"}),
               RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-10-02", script="MaaEnd", user="endfield",
                         started=at(16, 11, 6), finished=at(16, 11, 6), ok=False, failed_tasks=list(FIFTEEN),
                         raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})]
        if with_success:
            out.append(RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-11-12", script="MaaEnd", user="endfield",
                                 started=at(16, 12, 15), finished=at(16, 58, 22), ok=True, failed_tasks=[],
                                 raw={"maaend_result": "Success!", "tasks_done": ["日常奖励领取"],
                                      "tasks_evidence": {"日常奖励领取": "获得 通行证经验 ×2000"}}))
        return out

    handle._ship_evidence = lambda eng, rec: ""
    collect_retry.restore_master = lambda cfg: ""
    handle._weekly_gates = lambda eng, rec: None

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._alert_key = lambda r: handle._alert_key(e, r)
        return e

    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]

    print("[the reader: only the attempt that installed counts]")
    check("16:11:06 attempt installed beta.6", update_restart_version(MAAEND, at(16, 11, 6)),
          "v2.31.0-beta.6")
    check("15:24 attempt only downloaded", update_restart_version(MAAEND, at(15, 24, 12)), "")
    check("no MaaEnd dir", update_restart_version(None, at(16, 11, 6)), "")

    print("\n[an attempt killed 50 s before the next one installs stays a failure]")
    (MAAEND / "debug" / "2026-10-02-1.log").write_text("\n".join([
        "2026-10-02 10:00:50 INFO  [App] 检测到待安装更新: v9.9.9",
        "2026-10-02 10:00:51 INFO  [App] 更新安装完成"]) + "\n", encoding="utf-8")
    killed_start = datetime(2026, 10, 2, 9, 20, tzinfo=SERVER_TZ)      # killed at 10:00:00
    check("the killed attempt is not the one that installed", update_restart_version(MAAEND, killed_start), "")
    check("the attempt that started at 10:00:50 is", update_restart_version(MAAEND, datetime(2026, 10, 2, 10, 0, 50, tzinfo=SERVER_TZ)), "v9.9.9")
    check("install line too long after the start does not count",
          update_restart_version(MAAEND, datetime(2026, 10, 2, 10, 0, 0, tzinfo=SERVER_TZ)), "")

    print("\n[10-01 replay: crash, update restart, success -> the update attempt is not a failure]")
    e = build()
    for r in runs():
        handle._handle(e, r)
    e._flush_pending()
    ledger = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}
    mid = ledger["2026-10-01/endfield/MaaEnd-12-10-02"]
    check("booked as an update restart", (mid.get("raw") or {}).get("maaend_update_restart"), "v2.31.0-beta.6")
    check("transitional in the ledger", mid.get("transitional"), True)
    check("its failure names the update, not 15 tasks", mid.get("failed_tasks"),
          ["MaaEnd 装新版 v2.31.0-beta.6 后自己重启，这一次重试被用掉"])
    check("nothing pushed (the rerun went through: daily report only)", e.notifier.sent, [])
    check("nothing left held", (dict(e._pending), dict(e._recovered)), ({}, {}))

    print("\n[daily report: only the update attempt is an episode; the 15:24 crash stays listed]")
    from ark_relay.core import ledger as core
    entries = e.state.read_ledger("2026-10-01")
    kinds = core.episode_kinds(entries)
    check("16:11 update restart is the episode", kinds.get("2026-10-01/endfield/MaaEnd-12-10-02"), "update")
    check("15:24 crash is not folded into it", kinds.get("2026-10-01/endfield/MaaEnd-11-23-07"), None)
    check("15:24 reads as failed then retried", core.retried_notes(entries).get("2026-10-01/endfield/MaaEnd-11-23-07"),
          "MaaEnd 进程超时　后来在 16:12（东京 17:12）开始的那趟重试里做成了")
    tech: list = []
    title, body = core.format_daily("2026-10-01", entries, tech=tech)
    print("    " + title)
    print("    " + body.replace("\n", "\n    ")[:600])
    check("the crash line is there with ↻", any(l.startswith("↻ 终末地") for l in body.splitlines()), True)
    check("the update line is there with ↪️", any(l.startswith("↪️ 终末地") for l in body.splitlines()), True)
    check("its note names the update", "终末地装了新版后自己重启，用掉一次重试，不算失败" in body, True)
    check("the version goes to the technical log, not the report",
          ("v2.31.0-beta.6" in body, any("MaaEnd 装新版 v2.31.0-beta.6 后自己重启" in t for t in tech)), (False, True))

    print("\n[the title names the game: 10-01's full ledger shape]")
    okww = [{"run_id": f"o{i}", "script": "OK-WW", "user": "wuwa", "started": at(h, 0).isoformat(),
             "finished": at(h + 2, 0).isoformat(), "ok": False, "failed_tasks": ["OK-WW 运行超时"], "raw": {}}
            for i, h in enumerate((9, 11, 13))]
    done = dict(entries[-1], incomplete="MaaEnd 这一轮有 2 项没干成")
    t_full, _ = core.format_daily("2026-10-01", okww + entries[:-1] + [done])
    print("    " + t_full)
    check("title", t_full, "📋 10-01 · 鸣潮没跑成、终末地 1 项没干完 ⚠️")

    print("\n[a timeout clears only itself: a named task still undone keeps the record failed]")
    mixed = [dict(entries[0], failed_tasks=["MaaEnd 进程超时", "据点交易"]),
             dict(entries[-1], raw=dict(entries[-1]["raw"], tasks_done=["赠送干员礼物"]))]
    check("据点交易 not done later -> not retried", core.retried_notes(mixed), {})
    mixed[1]["raw"]["tasks_done"].append("据点交易")
    check("据点交易 done later -> retried", bool(core.retried_notes(mixed)), True)

    print("\n[all tasks done, MaaEnd did not exit: not 「没干完」, named as such]")
    from ark_relay.features import outcome
    own = "2026-10-01 16:12:28 INFO  [Task] 实例 AUTO-MAS: 开始执行任务, 数量: 2\n"
    hung_log = own + ("[2026-10-01 16:12:29] 任务开始: 🎁赠送干员礼物\n[2026-10-01 16:14:10] 任务完成: 🎁赠送干员礼物\n"
                      "[2026-10-01 16:58:19] 任务开始: ❌关闭游戏（PC）\n[2026-10-01 16:58:22] 任务完成: ❌关闭游戏（PC）\n")
    shot = ["2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png"]
    check("no-exit detected", outcome.maaend_no_self_exit(hung_log, own_log=True), True)
    check("checks pass (screenshot counted as recovered)",
          outcome.summarize(outcome.maaend_checks(hung_log, shot, own_log=True), "MaaEnd"), None)
    check("a failed task is still a failure",
          outcome.maaend_no_self_exit(hung_log + "[2026-10-01 16:59:00] 任务失败: 🧺自动采集\n", own_log=True), False)
    print("    case 1: MaaEnd's own log not read (09-17 truncated shape)")
    history_only = hung_log.replace(own, "")
    check("not read -> not 「all done」", outcome.maaend_no_self_exit(history_only, own_log=False), False)
    check("not read -> still 「MaaEnd 跑完」 failed",
          "MaaEnd 跑完" in [c.label for c in outcome.maaend_checks(history_only, [], own_log=False) if not c.ok], True)
    print("    case 2: crashed between tasks - 16 scheduled, 2 began and finished")
    crashed = hung_log.replace("数量: 2", "数量: 16")
    check("unstarted scheduled tasks -> not 「all done」", outcome.maaend_no_self_exit(crashed, own_log=True), False)
    check("…and 「MaaEnd 跑完」 failed",
          "MaaEnd 跑完" in [c.label for c in outcome.maaend_checks(crashed, [], own_log=True) if not c.ok], True)
    hung = dict(entries[-1], raw=dict(entries[-1]["raw"], maaend_no_self_exit=29))
    hung.pop("incomplete", None)
    hung_tech: list = []
    t_hung, b_hung = core.format_daily("2026-10-01", okww + entries[:-1] + [hung], tech=hung_tech)
    print("    " + t_hung)
    # Not exiting by itself is the relay's own wrap-up (it closed it): technical log, not title or row.
    check("title", t_hung, "📋 10-01 · 鸣潮没跑成 ⚠️")
    check("no 「没干完」 anywhere", "没干完" in t_hung + b_hung, False)
    check("the technical log says it, the report does not",
          (any("终末地任务全完成，但跑完没自己退出（空等 29 分钟）" in t for t in hung_tech), "没自己退出" in b_hung), (True, False))

    print("\n[the idle minutes come from AUTO-MAS's own result line, onto the ledger]")
    (TMP / "debug").mkdir(exist_ok=True)
    (TMP / "debug" / "app.log").write_text(
        "2026-10-01 17:27:43.100 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放\n", encoding="utf-8")
    e9 = build()
    last = runs()[-1]
    e9.state.append_ledger(last)
    handle._mark_no_self_exit(e9, last)
    row = {x["run_id"]: x for x in e9.state.read_ledger("2026-10-01")}[last.run_id]
    check("16:58:22 -> 17:27:43 = 29 minutes on the ledger", (row.get("raw") or {}).get("maaend_no_self_exit"), 29)

    print("\n[the update ate the last attempt -> nothing got it done: one alarm for the shift; the ledger says it]")
    e = build()
    for r in runs(with_success=False):
        handle._handle(e, r)
    e._flush_pending()
    got = alarms(e)
    check("one alarm", len(got), 1)
    check("it names the game and says no make-up ran",
          bool(got) and got[0][0].startswith("❌ 终末地") and "没补跑：没等到补跑就过了零点" in got[0][1], True)
    check("no longer held", dict(e._pending), {})
    e._flush_pending()
    check("a second tick says nothing more", len(alarms(e)), 1)
    upd = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}["2026-10-01/endfield/MaaEnd-12-10-02"]
    check("the ledger names the update", (upd.get("raw") or {}).get("maaend_update_restart"), "v2.31.0-beta.6")
    check("the update attempt is counted: 2 attempts", handle._attempts(e, runs(False)[-1], "2026-10-01"), 2)

    print("\n[no install lines in MXU's log -> an ordinary failure, as before]")
    (MAAEND / "debug" / "2026-10-01-4.log").write_text("2026-10-01 16:11:06 INFO  [App] 启动\n", encoding="utf-8")
    e = build()
    for r in runs(with_success=False):
        handle._handle(e, r)
    mid = {x["run_id"]: x for x in e.state.read_ledger("2026-10-01")}["2026-10-01/endfield/MaaEnd-12-10-02"]
    check("not marked", (mid.get("raw") or {}).get("maaend_update_restart"), None)
    check("keeps AUTO-MAS's 15 tasks", len(mid.get("failed_tasks") or []), 15)


def _part_maaend_update_restart_never_final():  # noqa: C901
    """A done MaaEnd round followed by MaaEnd restarting into its new build never ends in an alarm.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    MAAEND = TMP / "maaend"
    (MAAEND / "debug").mkdir(parents=True)
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.features import collect_retry
    from ark_relay.features import handle
    try:   # absent from the code that sent the two alarms (8f8250ea); the test still runs there
        from ark_relay.features import handle as unresolved
    except ImportError:
        unresolved = None
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    def automas_dir() -> Path:
        """AUTO-MAS config as on the machine: 早班 09:00 runs MaaEnd, 晚班 21:30 is MAA only."""
        root = tmpdir()
        (root / "config").mkdir()
        paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
        sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
        for k, p in paths.items():
            sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
        qc = {"instances": []}
        for n, (name, times, kinds) in enumerate((("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]),
                                                  ("晚班", ["21:30"], ["MAA"]))):
            uid = f"q{n}"
            qc["instances"].append({"uid": uid})
            ts = {"instances": []}
            for i, t in enumerate(times):
                ts[f"t{i}"] = {"Info": {"Enabled": True, "Time": t}}
            items = {"instances": []}
            for i, k in enumerate(kinds):
                items[f"i{i}"] = {"Info": {"ScriptId": f"s-{k}"}}
            qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                       "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root

    MACHINE = automas_dir()

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

        def send_group(self, title, body=""):
            self.sent.append((title, body, True))
            return []

    class Src:
        def fetch(self, seen):
            return []

    class Lines(logging.Handler):
        """Every ark.* line, with its level: a WARNING / ERROR one reaches the group (errwatch)."""

        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelno, record.getMessage()))

    LINES = Lines()
    ARK = logging.getLogger(handle.log.name.rsplit(".", 1)[0])
    ARK.addHandler(LINES)
    ARK.setLevel(logging.DEBUG)

    handle._ship_evidence = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    collect_retry.restore_master = lambda cfg: ""

    def mxu_install(at: datetime, version: str) -> None:
        """MXU's own log for the attempt that installed `version` at its start (real shape, 10-01)."""
        f = MAAEND / "debug" / f"{at:%Y-%m-%d}-1.log"
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        s = at.strftime("%Y-%m-%d %H:%M:%S")
        f.write_text(old + "\n".join([
            f"{s} INFO  [App] 检测到待安装更新: {version}",
            f"{s} INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11002.zip -> D:\\ark\\maaend",
            f"{s} INFO  [App] 更新安装完成",
            f"{s} INFO  [App] 已清除待安装更新信息",
        ]) + "\n", encoding="utf-8")

    def t(day, hh, mm, ss=0):
        return datetime(2026, 10, day, hh, mm, ss, tzinfo=SERVER_TZ)

    def success(day, run, start, minutes):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(minutes=minutes), ok=True, failed_tasks=[],
                         raw={"maaend_result": "Success!"})

    def restart(day, run, start, raw=None):
        return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                         started=start, finished=start + timedelta(seconds=30), ok=False,
                         failed_tasks=["赠送干员礼物", "据点交易", "日常奖励领取"],
                         raw=dict(raw or {}, maaend_result="MaaEnd 部分任务执行失败: 🎁赠送干员礼物"))

    # The two mornings, run ids + 4 h as relay.log shows them (the _part_maaend_update_after_done part).
    mxu_install(t(4, 9, 50, 53), "v2.32.0-beta.1")
    mxu_install(t(5, 11, 30, 14), "v2.32.0-beta.2")

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = MACHINE
        cfg.maaend_dir = MAAEND
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        return e

    def drive(e, recs, flushes=1):
        LINES.lines.clear()
        for r in recs:
            handle._handle(e, r)
        for _ in range(flushes):
            e._flush_pending()

    def said(fragment):
        return any(fragment in m for _, m in LINES.lines)

    def alarms(e):
        return [ti for ti, _, a in e.notifier.sent if a]

    def loud(e):
        """WARNING / ERROR lines: errwatch pushes each one to the group."""
        return [m for lv, m in LINES.lines if lv >= logging.WARNING]

    for day, s_run, s_at, mins, r_run, r_at in ((4, "05-26-41", t(4, 9, 26, 41), 23, "05-50-53", t(4, 9, 50, 53)),
                                                 (5, "06-39-48", t(5, 10, 39, 48), 49, "07-30-14", t(5, 11, 30, 14))):
        S, R = success(day, s_run, s_at, mins), restart(day, r_run, r_at)
        print(f"\n[10-0{day} as it landed: {S.run_id} done, then {R.run_id} restarts into its new build, then the push step]")
        e = build()
        drive(e, [S, R], flushes=2)
        check("the round was booked silently (「✅ … 静默记账」)", said(f"✅ MaaEnd {S.run_id}（{mins} 分钟）静默记账"))
        check("no 「最终失败」", said("最终失败"), False)
        check("no alarm of any kind went to the group", alarms(e), [])
        check("no WARNING / ERROR line (errwatch would push it)", loud(e), [])
        check("nothing held for a later push", dict(e._pending), {})

    print("\n[the shift could not be looked up when the restart landed: held; the push step lets it go]")
    S, R = success(4, "05-26-41", t(4, 9, 26, 41), 23), restart(4, "05-50-53", t(4, 9, 50, 53))
    e = build()
    real = getattr(unresolved, "done_in_shift", None) if unresolved is not None else None
    check("unresolved.done_in_shift exists", real is not None)
    if real is not None:
        calls = []

        def flaky(eng, rec):
            calls.append(rec.run_id)
            if len(calls) == 1:
                raise OSError("ledger busy")
            return real(eng, rec)
        unresolved.done_in_shift = flaky
        try:
            LINES.lines.clear()
            handle._handle(e, S)
            handle._handle(e, R)
            check("held when the lookup failed", list(e._pending), [("MaaEnd", "endfield")])
            e._flush_pending()
            e._flush_pending()
        finally:
            unresolved.done_in_shift = real
        check("let go at the push step: nothing held", dict(e._pending), {})
        check("no alarm went to the group", alarms(e), [])
        check("no 「最终失败」", said("最终失败"), False)
        check("the log says why", said(f"{R.run_id} 前面那趟已经做完（{S.run_id}）"))
        led = {x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}
        check("the ledger books the restart as the update",
              (led[R.run_id].get("raw") or {}).get("maaend_update_after_done"), S.run_id)

    print("\n[the restart lands first, the done round after it]")
    S, R = success(5, "06-39-48", t(5, 10, 39, 48), 49), restart(5, "07-30-14", t(5, 11, 30, 14))
    e = build()
    drive(e, [R, S], flushes=2)
    check("no alarm went to the group", alarms(e), [])
    check("no 「最终失败」", said("最终失败"), False)
    check("no WARNING / ERROR line", loud(e), [])
    check("nothing held", (dict(e._pending), dict(e._recovered)), ({}, {}))

    print("\n[every task of the restart failed at once (the 「never got into the game」 shape)]")
    S = success(4, "05-26-41", t(4, 9, 26, 41), 23)
    R = restart(4, "05-50-53", t(4, 9, 50, 53), raw={"maaend_unreachable_shape": True})
    e = build()
    drive(e, [S, R], flushes=2)
    check("no 「像没进游戏…按普通失败处理」 WARNING about the restart", [m for m in loud(e) if "像没进游戏" in m], [])
    check("no WARNING / ERROR line at all", loud(e), [])
    check("no alarm went to the group", alarms(e), [])
    check("the record carries no 「never got in」 note for an alarm", R.raw.get("maaend_unreachable_shape"), None)


def _part_maaend_watchdog_onepush():
    """One MaaEnd hang the watchdog ends, one group message (验收 2026-10-11 22:5x)."""
    import logging
    import os

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.core import texts
    from ark_relay.features import errwatch
    from ark_relay.features import maaend_watchdog

    CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
    RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    MAAEND_PID = 21260
    ALL_UP = [("System", 4), ("Endfield.exe", 18800), ("MaaEnd.exe", MAAEND_PID),
              ("go-service.exe", 21932), ("cpp-algo.exe", 21940)]
    NO_GO = [p for p in ALL_UP if p[0] != "go-service.exe"]
    ROBOT = "企业微信机器人"

    class Notes:
        """The relay's notifier: `refuse` returns errors, `fallback` delivers by Server酱 instead of the robot."""

        def __init__(self, refuse=False, fallback=False):
            self.sent, self.refuse, self.fallback = [], refuse, fallback

        def send(self, title, body="", **kw):
            self.sent.append(title)
            return ["企业微信机器人：拒收", "Server酱：拒收"] if self.refuse else []

        def went_to_group(self):
            return not self.fallback

    class Refuses:
        """errwatch's own notifier: the group refuses, so what it queues stays queued (readable)."""

        def send_group(self, title, body):
            return [f"{ROBOT}：拒收"]

        def send(self, title, body, **kw):
            return ["拒收"]

    ARK_LOGGER = logging.getLogger(errwatch.ARK)

    class Rig:
        def __init__(self, notes, kill_ok=True, state_dir=None):
            self.t, self.lines, self.stamp = 1000.0, 0, "2026-10-01 15:20:00"
            self.procs, self.kill_ok, self.killed, self.notes = list(ALL_UP), kill_ok, [], notes
            self.debug = tmpdir() / "debug"
            self.debug.mkdir()
            self.stderr = self.debug / "go-service.stderr.log"
            self.stderr.write_text("", encoding="utf-8")
            agent = str(self.debug.parent / "agent")
            paths = {21932: os.path.join(agent, "go-service.exe"), 21940: os.path.join(agent, "cpp-algo.exe")}
            self.dog = maaend_watchdog.Watchdog(
                notes, self.debug, clock=lambda: self.t, snapshot=lambda: RUNNING,
                processes=lambda: list(self.procs), kill=self._kill, plugin_paths=lambda: paths,
                active=True, state_dir=state_dir)
            self.h = errwatch.ErrorKindAlert(Refuses(), state_dir=tmpdir() / "ew", known={}, retry=(3600.0,),
                                             fallback_after=1e9)
            ARK_LOGGER.addHandler(self.h)

        def _kill(self, pid, image):
            self.killed.append(pid)
            if not self.kill_ok:
                return False, "退出码 128"
            self.procs = [p for p in self.procs if p[1] != pid]
            return True, ""

        def step(self, seconds, new_lines=0, stamp=None):
            self.t += seconds
            self.lines += new_lines
            self.stamp = stamp or self.stamp
            return self.dog.tick(self.lines, self.stamp)

        def run_for(self, seconds, every=60, **kw):
            for _ in range(int(seconds // every)):
                self.step(every, **kw)

        def group(self):
            """Everything that went or would go to the group: the watchdog's own sends, then errwatch's queue."""
            return list(self.notes.sent) + [str(x.get("line"))[:40] for x in self.h.pending()]

        def done(self):
            ARK_LOGGER.removeHandler(self.h)
            self.h.close()

    def crash(r):
        r.run_for(240, new_lines=40)
        r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        r.step(60)

    print("[2026-10-01 go-service crash -> MaaEnd ended: one group message, the ⚠️]")
    r = Rig(Notes())
    crash(r)
    check("ended MaaEnd and its plugins", r.killed, [MAAEND_PID, 21932, 21940])
    check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.run_for(600)
    check("nothing more for the same PID", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.done()

    print("\n[maafw.log stood still 10 minutes -> ended: one group message]")
    r = Rig(Notes())
    r.run_for(300, new_lines=50, stamp="2026-10-01 15:30:03")
    r.run_for(600)
    check("ended", r.killed[:1], [MAAEND_PID])
    check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.done()

    print("\n[go-service gone twice 60 s apart -> ended: one group message]")
    r = Rig(Notes())
    r.run_for(240, new_lines=20)
    r.procs = NO_GO
    r.step(60, new_lines=5)
    r.step(60, new_lines=5)
    check("ended MaaEnd and cpp-algo", r.killed, [MAAEND_PID, 21940])
    check("group: the ⚠️ only", r.group(), [texts.MAAEND_STUCK_KILLED])
    r.done()

    print("\n[the kill did not take -> the ⚠️, plus machine check #31's FAIL (a check of its own)]")
    r = Rig(Notes(), kill_ok=False, state_dir=tmpdir() / "relaystate")
    crash(r)
    check("group: ⚠️ 没能结束 and 🔬 #31, no 「卡死」 WARNING",
          [t[:12] for t in r.group()], [texts.MAAEND_STUCK_KILL_FAILED[:12], "🔬 上机核对没过：#31"])
    r.done()

    print("\n[the ⚠️ send was refused -> the WARNING is pushed instead: the fault still reaches the group once]")
    r = Rig(Notes(refuse=True))
    crash(r)
    check("errwatch queues the 「卡死」 WARNING", [x[:9] for x in r.group()[1:]], ["MaaEnd 卡死"])
    r.done()

    print("\n[the ⚠️ fell back to Server酱 -> the WARNING goes to the group]")
    r = Rig(Notes(fallback=True))
    crash(r)
    check("errwatch queues the 「卡死」 WARNING", [x[:9] for x in r.group()[1:]], ["MaaEnd 卡死"])
    r.done()

    print("\n[audit 11-08 B-06: a kill restarts the shift's overrun clock, as MAA's does]")
    from datetime import datetime as _dt
    from ark_relay.core.config import SERVER_TZ as _TZ
    from ark_relay.core.statestore import StateStore as _SS
    _sd = tmpdir() / "relaystate-mark"
    r = Rig(Notes(), state_dir=_sd)
    r.dog.wall = lambda: _dt(2026, 11, 8, 10, 31, 5, tzinfo=_TZ)
    crash(r)
    r.run_for(600)
    check("killed", bool(r.killed), True)
    check("「超时|MaaEnd|10:31:05」 is left for runwatch.retry_clock",
          "超时|MaaEnd|10:31:05" in (_SS(_sd).get("marks", "alerted:2026-11-08") or []), True)
    r.done()
    r = Rig(Notes(), kill_ok=False, state_dir=tmpdir() / "relaystate-nokill")
    r.dog.wall = lambda: _dt(2026, 11, 8, 10, 31, 5, tzinfo=_TZ)
    crash(r)
    r.run_for(600)
    check("a failed kill leaves no mark (nothing restarts)",
          _SS(r.dog.state_dir).get("marks", "alerted:2026-11-08"), None)
    r.done()


def _part_spmed_kept_off_push():
    """应急理智加强剂 is never kept off; a booster step the relay cannot recognise rings the
group at every boot (2026-10-06).
    """
    import json
    import shutil
    import types


    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom")

    import boot_stages
    from ark_relay.features import collect_retry
    from ark_relay.features import gameupdate as gu
    from ark_relay.core import mastercfg, notify, texts


    class Notifier:
        def __init__(self): self.sent = []
        def send(self, title, body, **k): self.sent.append((title, body, bool(k.get("alert"))))


    class Log:
        def __init__(self): self.lines = []
        def info(self, *a, **k): self.lines.append(("info", a))
        def warning(self, *a, **k): self.lines.append(("warning", a))
        def exception(self, *a, **k): self.lines.append(("exception", a))


    mastercfg.prune_maaend_orphans = lambda *a: ([], "")
    mastercfg.migrate_maaend_options = lambda *a: ([], "")
    collect_retry.restore_master = lambda cfg: ""
    FIX = fx_dir(Path(__file__), "fixtures")
    TITLE = getattr(texts, "SPMED_UNRECOGNISED", "<no such title>")

    root = tmpdir()
    maaend = root / "maaend"
    (maaend / "resource" / "pipeline").mkdir(parents=True)
    shutil.copy(FIX / "maaend-v2.30.0-beta.4-spmed" / "interface.json", maaend / "interface.json")
    _nodes = json.loads((FIX / "maaend-v2.30.0-beta.4-spmed" / "resource" / "pipeline" / "nodes.json")
                        .read_text(encoding="utf-8"))
    for _gone in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster"):
        _nodes.pop(_gone, None)
    (maaend / "resource" / "pipeline" / "nodes.json").write_text(json.dumps(_nodes, ensure_ascii=False),
                                                                 encoding="utf-8")
    master = root / "automas" / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    master.parent.mkdir(parents=True)
    doc = json.loads((FIX / "maaend-2026-09-10" / "master-before.json").read_text(encoding="utf-8"))
    doc["instances"][0]["tasks"].append({"taskName": "AutoUseSpMedication", "enabled": True,
                                         "enabledByController": {"Win32-Front": True}})
    master.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "state").mkdir()
    cfg = types.SimpleNamespace(automas_dir=root / "automas", maaend_dir=maaend, state_dir=root / "state")
    before = master.read_bytes()

    print("[the booster step under neither of its names - every boot rings the group, the task is left on]")
    for boot in (1, 2, 3):
        n, lg = Notifier(), Log()
        boot_stages._stage_reenable_maaend(cfg, n, lg)
        check(f"boot {boot}: one push, to the group", [(t, a) for t, _b, a in n.sent], [(TITLE, True)])
    check("the master is not touched", master.read_bytes() == before, True)
    check("the title routes to the group", notify.route_of(TITLE, alert=True), "group")
    body = n.sent[-1][1] if n.sent else ""
    check("the text is plain Chinese", texts.plain(body), [])
    check("the text says the task stays on", "一直开着，中继不会关它" in body, True)
    check("not the old info title", [t for t, _b, _a in n.sent if "没能确认" in t], [])

    print("\n[the check failing does not take the stage down]")
    real = getattr(gu, "spmed_check", None)
    gu.spmed_check = lambda cfg: (_ for _ in ()).throw(OSError("磁盘读不了"))
    n, lg = Notifier(), Log()
    boot_stages._stage_reenable_maaend(cfg, n, lg)
    check("logged as an exception, nothing pushed", ([x[0] for x in lg.lines if x[0] == "exception"], n.sent),
          (["exception"], []))
    if real is not None:
        gu.spmed_check = real


def _part_spmed_v232():
    """The booster's confirm step under its v2.32 name is the fixed shape: no boot alarm."""
    import json
    import shutil
    import types

    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom")

    import boot_stages
    from ark_relay.features import gameupdate
    from ark_relay.core import mastercfg, texts

    LIVE = fx_dir(Path(__file__), "fixtures") / "maaend-v2.32-spmed"

    def maaend_with(nodes: dict) -> Path:
        d = tmpdir()
        (d / "resource" / "pipeline").mkdir(parents=True)
        (d / "resource" / "pipeline" / "nodes.json").write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        return d

    class Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): pass

    def boot_alarms(maaend_dir) -> list:
        """What the boot stage pushes about the booster for this MaaEnd folder."""
        real = mastercfg.prune_maaend_orphans
        mastercfg.prune_maaend_orphans = lambda *a: ([], "")
        try:
            n = _N()
            cfg = types.SimpleNamespace(maaend_dir=str(maaend_dir), automas_dir=None, state_dir=str(tmpdir()))
            boot_stages._stage_reenable_maaend(cfg, n, Log())
            return [t for t, a in n.sent if t == texts.SPMED_UNRECOGNISED and a]
        finally:
            mastercfg.prune_maaend_orphans = real

    print("[v2.32 的真实节点（机器上的 nodes.json）：认得是修好的写法，不报群]")
    live = tmpdir() / "maaend"
    shutil.copytree(LIVE, live)
    check("认得", gameupdate.spmed_shape(live), "fixed")
    check("开机不报群", boot_alarms(live), [])

    print("[09-03 那种坏写法（行内 OCR 没有自己的 recognition）：报群]")
    broken_inline = {"param": {"expected": ["使用"]}, "type": "OCR"}
    for name in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster"):
        d = maaend_with({name: {"recognition": {"param": {"all_of": ["YellowConfirmButtonType2", broken_inline]},
                                                "type": "And"}}})
        check(f"{name}：判成坏的", gameupdate.spmed_shape(d), "broken")
        check(f"{name}：开机报群一条", len(boot_alarms(d)), 1)

    print("[两个名字都没有：报群]")
    d = maaend_with({"SomethingElse": {}})
    check("判成没有这个节点", gameupdate.spmed_shape(d), "missing")
    check("开机报群一条", len(boot_alarms(d)), 1)

    print("[旧名字下修好的写法（PR #5453）照样认得]")
    d = maaend_with({"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
        "YellowConfirmButtonType2", {"recognition": {"param": {"expected": ["使用"]}, "type": "OCR"}}]}, "type": "And"}}})
    check("认得", gameupdate.spmed_shape(d), "fixed")

    print("[all_of 空着或里面有认不出的东西：判成认不出，报群]")
    for label, all_of in (("空的", []), ("有个数字", ["YellowConfirmButtonType2", 3])):
        d = maaend_with({"__AutoUseSpMedicationUseEmergencySpBooster": {"recognition": {"param": {"all_of": all_of},
                                                                                         "type": "And"}}})
        check(f"{label}：认不出", gameupdate.spmed_shape(d), "unknown")
        check(f"{label}：报群", len(boot_alarms(d)), 1)


def _part_spmed_v233_rc1():
    """The booster's confirm step in MaaEnd v2.33.0-rc.1 (OCR on the dialog's button region) is known-good.
    """
    import json
    import shutil
    import types

    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom")

    import boot_stages
    from ark_relay.features import gameupdate
    from ark_relay.core import mastercfg, texts

    LIVE = fx_dir(Path(__file__), "fixtures") / "maaend-v2.33.0-rc.1-spmed"
    V232 = fx_dir(Path(__file__), "fixtures") / "maaend-v2.32-spmed"

    def maaend_with(nodes: dict) -> Path:
        d = tmpdir()
        (d / "resource" / "pipeline").mkdir(parents=True)
        (d / "resource" / "pipeline" / "nodes.json").write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        return d

    class Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): pass

    def boot_alarms(maaend_dir) -> list:
        """What the boot stage pushes about the booster for this MaaEnd folder."""
        real = mastercfg.prune_maaend_orphans
        mastercfg.prune_maaend_orphans = lambda *a: ([], "")
        try:
            n = _N()
            cfg = types.SimpleNamespace(maaend_dir=str(maaend_dir), automas_dir=None, state_dir=str(tmpdir()))
            boot_stages._stage_reenable_maaend(cfg, n, Log())
            return [t for t, a in n.sent if t == texts.SPMED_UNRECOGNISED and a]
        finally:
            mastercfg.prune_maaend_orphans = real

    print("[v2.33.0-rc.1 的真实节点（机器上的 nodes.json）：认得，不报群]")
    live = tmpdir() / "maaend"
    shutil.copytree(LIVE, live)
    check("认得是按文字认确认按钮的写法", gameupdate.spmed_shape(live), "ocr")
    check("开机不报群", boot_alarms(live), [])

    print("[v2.32 的老写法照样认得]")
    old = tmpdir() / "maaend"
    shutil.copytree(V232, old)
    check("认得", gameupdate.spmed_shape(old), "fixed")
    check("开机不报群", boot_alarms(old), [])

    rc1 = json.loads((LIVE / "resource" / "pipeline" / "nodes.json").read_text(encoding="utf-8"))
    NAME = "__AutoUseSpMedicationUseEmergencySpBooster"

    def variant(edit, name=NAME):
        node = json.loads(json.dumps(rc1[NAME]))
        edit(node)
        return maaend_with({name: node})

    print("[和 rc.1 不一样的文字识别写法：认不出，报群]")
    for label, edit in (
            ("没有 roi（会点到背后奖励页的领取）", lambda n: n["recognition"]["param"].pop("roi")),
            ("roi 不是四个数", lambda n: n["recognition"]["param"].update(roi=[860, 465, 300])),
            ("expected 是空的", lambda n: n["recognition"]["param"].update(expected=[])),
            ("没有点击动作", lambda n: n.pop("action")),
            ("识别类型不是 OCR", lambda n: n["recognition"].update(type="TemplateMatch")),
            ("认的字是「领取」（背后奖励页的按钮）", lambda n: n["recognition"]["param"].update(expected=["领取"])),
            ("认的字是任意文字", lambda n: n["recognition"]["param"].update(expected=[".*"])),
            ("确认之外还认「领取」", lambda n: n["recognition"]["param"]["expected"].append("领取")),
            ("认的字里没有「确认」", lambda n: n["recognition"]["param"].update(expected=["(?i)Confirm"])),
            ("roi 是全屏", lambda n: n["recognition"]["param"].update(roi=[0, 0, 1280, 720])),
            ("roi 是 [0,0,0,0]（框架当全屏）", lambda n: n["recognition"]["param"].update(roi=[0, 0, 0, 0])),
            ("roi 挪到左上角", lambda n: n["recognition"]["param"].update(roi=[0, 0, 10, 10])),
            ("roi 上游微调过", lambda n: n["recognition"]["param"].update(roi=[860, 465, 300, 100])),
            ("roi 带小数", lambda n: n["recognition"]["param"].update(roi=[860.0, 465, 300, 90])),
            ("roi 是节点名", lambda n: n["recognition"]["param"].update(roi="SomeNode")),
            ("expected 是一个字符串", lambda n: n["recognition"]["param"].update(expected="确认")),
            ("识别结果取反", lambda n: n.update(inverse=True)),
            ("节点被停用", lambda n: n.update(enabled=False)),
            ("点击位置另给（target）", lambda n: n.update(target=[100, 100, 10, 10])),
            ("点击位置偏移（target_offset）", lambda n: n.update(target_offset=[0, 300, 0, 0])),
            ("OCR 里又夹了 all_of", lambda n: n["recognition"]["param"].update(all_of=["X"])),
            ("type/param 摊平（九月那种错写法）", lambda n: n.update(
                recognition={"type": "OCR", "roi": [860, 465, 300, 90], "expected": ["确认"]})),
            ("action 写成 {type: Click}", lambda n: n.update(action={"type": "Click"}))):
        d = variant(edit)
        check(f"{label}：认不出", gameupdate.spmed_shape(d), "unknown")
        check(f"{label}：开机报群一条", len(boot_alarms(d)), 1)

    print("[识别结果不取反、节点明写启用、v2.36.0 扩大的确认框：照样认得]")
    for label, edit in (("inverse: false", lambda n: n.update(inverse=False)),
                        ("enabled: true", lambda n: n.update(enabled=True)),
                        ("v2.36.0 roi [860,465,390,120] (PR #6933)", lambda n: n["recognition"]["param"].update(roi=[860, 465, 390, 120]))):
        v = variant(edit)
        check(f"{label}：认得", gameupdate.spmed_shape(v), "ocr")
        check(f"{label}：开机不报群", boot_alarms(v), [])

    print("[同样的写法挂在 v2.32 以前的旧名字下：认不出，报群]")
    d = variant(lambda n: None, name="AutoUseSpMedicationQuickUse")
    check("认不出", gameupdate.spmed_shape(d), "unknown")
    check("开机报群一条", len(boot_alarms(d)), 1)


def _part_essence_filler_main():
    """基质刷取: tick 唤月 next to 玉中身 (target mode), and once every ticked weapon's
essence is owned, switch to filler mode (刷垫子) by itself.
    """
    import json
    import logging
    import os
    import shutil


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    for name in ("QueueConfig.json", "ScriptConfig.json"):
        (AUTOMAS / "config" / name).write_text(json.dumps({"instances": []}), encoding="utf-8")
    CONF = AUTOMAS / "data" / "59da8762-8fa7-4260-8aee-10f9ca00097a" / "Default" / "ConfigFile"
    CONF.mkdir(parents=True)
    MASTER = CONF / "mxu-MaaEnd.json"
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    from ark_relay.core import engine as eng_mod
    from ark_relay.core import ledger as core
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features import errwatch, handle
    from ark_relay.features.collector_maaend import parse_maaend_log

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-v2.33-essence"
    REC = fx_dir(Path(__file__), "replay") / "2026-10-16" / "endfield"
    HIST_LOG = (REC / "MaaEnd-09-53-33.log").read_text(encoding="utf-8")
    MET_LINE = "勾选武器的基质均已满足"
    GENERIC = "基质目标已满足或任务结束"
    DAY = "2026-10-16"
    ESS = "AutoEssence"

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    class Catch(logging.Handler):
        def __init__(self):
            super().__init__(logging.INFO)
            self.records: list[logging.LogRecord] = []

        def emit(self, record):
            self.records.append(record)

        def alarms(self) -> list[tuple]:
            return [getattr(r, errwatch.ALARM) for r in self.records
                    if r.levelno >= logging.WARNING and hasattr(r, errwatch.ALARM)]


    CATCH = Catch()
    logging.getLogger(errwatch.ARK).addHandler(CATCH)
    logging.getLogger(errwatch.ARK).setLevel(logging.INFO)
    handle._weekly_gates = lambda eng, r: None
    handle._ship_evidence = lambda eng, r: ""      # no bundle upload in a test


    def build(maaend_dir: Path = FIX):
        cfg = Config()
        cfg.state_dir = TMP / "state"
        cfg.state_dir.mkdir(exist_ok=True)
        cfg.automas_dir = AUTOMAS
        cfg.maaend_dir = maaend_dir
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._verify_outcome = lambda r: None
        return e


    def record(run_id: str, log_text: str) -> RunRecord:
        from datetime import datetime
        f = TMP / f"{run_id.replace('/', '_')}.log"
        f.write_text(log_text, encoding="utf-8")
        return RunRecord(run_id=run_id, script="MaaEnd", user="endfield",
                         started=datetime(2026, 10, 16, 13, 54, 57, tzinfo=SERVER_TZ),
                         finished=datetime(2026, 10, 16, 14, 11, 39, tzinfo=SERVER_TZ),
                         ok=True, raw=parse_maaend_log(f))


    def master() -> dict:
        return json.loads(MASTER.read_text(encoding="utf-8"))


    def ov(doc: dict) -> dict:
        return next(t for t in doc["instances"][0]["tasks"] if t["taskName"] == ESS)["optionValues"]


    def others(doc: dict) -> list:
        return [t for t in doc["instances"][0]["tasks"] if t["taskName"] != ESS]


    def backups(tag: str) -> list[Path]:
        return sorted(CONF.glob(f"mxu-MaaEnd.json.bak-essence-{tag}-*"))


    def put_master(doc: dict) -> None:
        MASTER.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


    def without_met(text: str) -> str:
        return "\n".join(x for x in text.splitlines() if MET_LINE not in x) + "\n"


    def main() -> int:
        from ark_relay.features import essence  # missing before this change
        shutil.copyfile(FIX / "master-1016.json", MASTER)
        real = master()
        cfg = build().cfg
        regions = json.loads((FIX / "tasks/AutoEssence/Location/ChooseLocation.json").read_text(encoding="utf-8"))
        all_regions = [c["name"] for c in regions["option"]["AutoEssenceChooseLocation"]["cases"]]
        require("real master: target mode, only 玉中身 ticked, 刻写券 on, one region",
                ov(real)["AutoEssenceMenu"]["caseName"] == "Target"
                and ov(real)["AutoEssenceWeaponsClaymore"]["caseNames"] == ["wpn_claym_0018"]
                and "AutoEssenceWeaponsSword" not in ov(real)
                and ov(real)["AutoEssenceDoOverride"]["value"] is True
                and ov(real)["AutoEssenceChooseLocation"]["caseNames"] == ["WLSwordVaultDale"], repr(ov(real)))

        print("[A: 勾上唤月（玉中身留着），只在没有任务在跑时]")
        require("refused while an AUTO-MAS task runs", essence.busy(cfg, lambda: True) == "AUTO-MAS 还有任务在跑")
        require("free when nothing runs", essence.busy(cfg, lambda: False) == "")
        res = essence.apply(cfg, essence.pick_weapons, "pick", ["wpn_claym_0018", "wpn_sword_0025"])
        after = master()
        a = ov(after)
        require("written, backup is the original bytes",
                res.changed and len(backups("pick")) == 1
                and backups("pick")[0].read_bytes() == (FIX / "master-1016.json").read_bytes(), res.note)
        require("单手剑 on with exactly 唤月 (not the default: every ★6 sword)",
                a["AutoEssenceWeaponTypeSword"] == {"type": "switch", "value": True}
                and a["AutoEssenceWeaponsSword"] == {"type": "checkbox", "caseNames": ["wpn_sword_0025"]}, repr(a))
        require("双手剑 still exactly 玉中身", a["AutoEssenceWeaponTypeClaymore"]["value"] is True
                and a["AutoEssenceWeaponsClaymore"]["caseNames"] == ["wpn_claym_0018"])
        require("手铳 / 施术单元 / 长柄武器 off", all(a[f"AutoEssenceWeaponType{t}"] == {"type": "switch", "value": False}
                                            for t in ("Pistol", "Wand", "Lance")))
        require("before/after printed", res.before == {"weapons": {"AutoEssenceWeaponsClaymore": ["wpn_claym_0018"]}}
                and res.after == {"weapons": {"AutoEssenceWeaponsClaymore": ["wpn_claym_0018"],
                                              "AutoEssenceWeaponsSword": ["wpn_sword_0025"]}}, f"{res.before} {res.after}")
        changed = {"AutoEssenceWeaponTypeSword", "AutoEssenceWeaponsSword"}
        require("nothing else in 基质刷取 changed (target mode kept)",
                {k: v for k, v in a.items() if k not in changed} == {k: v for k, v in ov(real).items() if k not in changed})
        require("the other tasks unchanged", others(after) == others(real))
        require("names from MaaEnd's language pack",
                essence.weapon_names(FIX, ["wpn_claym_0018", "wpn_sword_0025"]) == ["玉中身", "唤月"])
        again = essence.apply(cfg, essence.pick_weapons, "pick", ["wpn_claym_0018", "wpn_sword_0025"])
        require("run again: nothing written, no second backup", not again.changed and len(backups("pick")) == 1, again.note)
        picked = master()

        print("[B: 只有通用那句「基质目标已满足或任务结束」：不切]")
        e = build()
        generic = without_met(HIST_LOG)
        require("negative fixture keeps the generic line only", GENERIC in generic and MET_LINE not in generic)
        e._handle(record(f"{DAY}/endfield/MaaEnd-generic", generic))
        e._essence_filler()
        require("master untouched, no backup", master() == picked and not backups("filler"))
        require("nothing pending", e.state.store.get(essence.SECTION, essence.PENDING) is None)

        print("[B: 10-16 那趟（勾选的都齐了）：有任务在跑就等，空了切成刷垫子]")
        rec = record(f"{DAY}/endfield/MaaEnd-09-53-33", HIST_LOG)
        require("real record parsed as target met", rec.raw.get("maaend_essence_met") is True)
        e._handle(rec)
        require("pending after the record", (e.state.store.get(essence.SECTION, essence.PENDING) or {}).get("run_id")
                == rec.run_id)
        e._scripts_running = lambda: True
        e._essence_filler()
        require("busy: master untouched, still pending", master() == picked and not backups("filler")
                and e.state.store.get(essence.SECTION, essence.PENDING) is not None)
        e._scripts_running = lambda: False
        e._essence_filler()
        f = ov(master())
        require("random mode", f["AutoEssenceMenu"] == {"type": "select", "caseName": "Random"}, repr(f["AutoEssenceMenu"]))
        require("使用刻写券 off", f["AutoEssenceDoOverride"] == {"type": "switch", "value": False})
        require("every region, in MaaEnd's order", f["AutoEssenceChooseLocation"]["caseNames"] == all_regions
                and len(all_regions) == 12, repr(f["AutoEssenceChooseLocation"]))
        sw = {"AutoEssenceMenu", "AutoEssenceDoOverride", "AutoEssenceChooseLocation"}
        require("领取方式 / 循环 / 应急理智加强剂 / weapons untouched",
                {k: v for k, v in f.items() if k not in sw} == {k: v for k, v in ov(picked).items() if k not in sw})
        require("the other tasks unchanged", others(master()) == others(real))
        require("one backup, the master before the switch", len(backups("filler")) == 1
                and json.loads(backups("filler")[0].read_text(encoding="utf-8")) == picked)
        require("no group alarm", CATCH.alarms() == [], repr(CATCH.alarms()))
        require("pending cleared", e.state.store.get(essence.SECTION, essence.PENDING) is None)
        line = next((x for x in e.state.read_ledger(DAY) if x["run_id"] == rec.run_id), {})
        sw_raw = (line.get("raw") or {}).get(essence.RAW_KEY) or {}
        require("ledger line marked with the weapons' names", sorted(sw_raw.get("weapons") or []) == sorted(["玉中身", "唤月"]),
                repr(sw_raw))
        _t, body = core.format_daily(DAY, [line])
        want = texts.essence_filler_on(sw_raw.get("weapons") or [])
        require("daily report says it once, plainly", body.count(want) == 1 and texts.ESSENCE_TARGET_MET not in body, body)
        require("plain language", texts.plain(want) == [] and texts.plain(texts.ESSENCE_FILLER_FAILED) == []
                and texts.plain(texts.essence_filler_failed("写进去之后读出来和写的不一样")) == [], repr(texts.plain(want)))

        print("[B: 再来一趟同样的记录 / 已经是刷垫子：什么都不动]")
        e._handle(rec)                       # the same record handled again
        require("a record already acted on is not armed again",
                e.state.store.get(essence.SECTION, essence.PENDING) is None)
        filler = master()
        rec2 = record(f"{DAY}/endfield/MaaEnd-later", HIST_LOG)
        e._handle(rec2)
        e._essence_filler()
        require("already filler mode: no write, no new backup", master() == filler and len(backups("filler")) == 1)
        line2 = next((x for x in e.state.read_ledger(DAY) if x["run_id"] == rec2.run_id), {})
        require("... and no switch line for it", essence.RAW_KEY not in (line2.get("raw") or {}))

        print("[他自己改回目标选择：不跟他拧，等下一次「都齐了」才再切]")
        put_master(picked)
        for _ in range(3):
            e._essence_filler()
        require("no record, no switch", master() == picked)
        rec3 = record(f"{DAY}/endfield/MaaEnd-next", HIST_LOG)
        e._handle(rec3)
        e._essence_filler()
        require("the next target-met run switches again", ov(master())["AutoEssenceMenu"]["caseName"] == "Random")

        print("[A 在刷垫子模式下拒绝（勾武器没意义）]")
        try:
            essence.apply(cfg, essence.pick_weapons, "pick", ["wpn_sword_0025"])
            require("refused outside target mode", False)
        except essence.Refused as exc:
            require("refused outside target mode", "不是「目标选择」" in str(exc), str(exc))

        print("[写不成：进群一次，不重试]")
        put_master(picked)
        empty = TMP / "no-maaend"
        empty.mkdir()
        e2 = build(empty)
        e2._handle(record(f"{DAY}/endfield/MaaEnd-nodefs", HIST_LOG))
        e2._essence_filler()
        e2._essence_filler()
        require("master untouched", master() == picked)
        require("one group alarm under its own title", [t for t, _ in CATCH.alarms()] == [texts.ESSENCE_FILLER_FAILED],
                repr(CATCH.alarms()))

        print("[母本一时被占着（OSError）：下一轮再试，后来成了只进日报；连着 OS_ATTEMPTS 次才进群（审计 11-08 D-10）]")
        put_master(picked)
        CATCH.records.clear()
        e3 = build()
        e3._handle(record(f"{DAY}/endfield/MaaEnd-locked", HIST_LOG))
        real_apply, held = essence.apply, [1]

        def locked(*a, **k):
            if held[0]:
                held[0] -= 1
                raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return real_apply(*a, **k)
        essence.apply = locked
        try:
            e3._essence_filler()
            require("first try held: still pending, master untouched, nothing pushed",
                    e3.state.store.get(essence.SECTION, essence.PENDING) is not None and master() == picked
                    and CATCH.alarms() == [], repr(CATCH.alarms()))
            e3._essence_filler()
            require("next tick: switched", ov(master())["AutoEssenceMenu"]["caseName"] == "Random")
            healed = [r for r in CATCH.records if r.levelno == logging.WARNING and getattr(r, errwatch.RECOVERED, False)]
            require("one WARNING marked recovered (daily report, not the group)", len(healed) == 1 and CATCH.alarms() == [],
                    repr([r.getMessage() for r in CATCH.records]))
            require("……its first line is plain words", texts.plain(healed[0].getMessage().splitlines()[0]) == [])
            put_master(picked)
            CATCH.records.clear()
            e3._handle(record(f"{DAY}/endfield/MaaEnd-locked-2", HIST_LOG))
            held[0] = essence.OS_ATTEMPTS
            for _ in range(essence.OS_ATTEMPTS):
                e3._essence_filler()
            require(f"{essence.OS_ATTEMPTS} in a row: given up, one group alarm",
                    (e3.state.store.get(essence.SECTION, essence.PENDING), [t for t, _ in CATCH.alarms()])
                    == (None, [texts.ESSENCE_FILLER_FAILED]), repr(CATCH.alarms()))
        finally:
            essence.apply = real_apply

        return 1 if fails else 0


    sys.exit(main())


def _part_essence_filler_pushes_state():
    """After essence.step switches MaaEnd to filler mode, the phone page is told (11-08 [D-08]).
    """
    import types

    from ark_relay.features import essence

    class Store:
        def __init__(self):
            self.d = {(essence.SECTION, essence.PENDING): {"run_id": "r1", "day": "2026-11-08"}}

        def get(self, s, k):
            return self.d.get((s, k))

        def set(self, s, k, v):
            self.d[(s, k)] = v

        def pop(self, s, k):
            self.d.pop((s, k), None)

    pushed = []
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=None), _scripts_running=lambda: False,
                                state=types.SimpleNamespace(mark_raw=lambda *a: None),
                                _push_state=pushed.append)
    store = Store()
    essence._store = lambda e: store
    essence.busy = lambda cfg, running: ""
    essence.apply = lambda cfg, fn, label: types.SimpleNamespace(changed=True, names=[], before="a", after="b", note="")
    essence.weapon_names = lambda d, n: []
    essence.step(eng)
    check("switched: phone state pushed once", pushed, ["基质切刷垫子"])


if __name__ == "__main__":
    sys.exit(run_parts([_part_mastercfg_main, _part_mastercfg_jsonc_strings, _part_mastercfg_protocolspace, _part_maaend_controller_cache, _part_maaend_defs_228, _part_maaend_migrate_options, _part_maaend_migrate_stock_switch, _part_maaend_migrate_unread_defs, _part_maaend_name_mismatch, _part_maaend_phone_page_beta5, _part_maaend_schedule_skip, _part_maaend_skipped_report, _part_maaend_write_readback, _part_maaend_watchdog_main, _part_maaend_no_d3d11_alarm, _part_maaend_essence_met, _part_maaend_essence_stamina_out, _part_maaend_full_at_anchor, _part_maaend_round_upper_bound, _part_maaend_sanity, _part_maaend_sanity_fit, _part_maaend_sanity_one_formula, _part_maaend_update_after_done, _part_maaend_update_record, _part_maaend_update_restart, _part_maaend_update_restart_never_final, _part_maaend_watchdog_onepush, _part_spmed_kept_off_push, _part_spmed_v232, _part_spmed_v233_rc1, _part_essence_filler_main, _part_essence_filler_pushes_state]))
