#!/usr/bin/env python3
"""母本配置的读写。

守的是这次重构的前提：终末地和鸣潮改的必须是**脚本自己那份**，
而且写之前要挡住三样东西——不存在的任务、不存在的选项、不认识的取值。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import mastercfg  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def _fixture() -> tuple[Path, Path]:
    """造一份假的 AUTO-MAS 母本目录 + 假的 MaaEnd 安装目录。"""
    root = Path(tempfile.mkdtemp())
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
        {"taskName": "AutoUseSpMedication", "enabled": False, "optionValues": {}},
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
    "task": [{"name": "AutoEssence", "label": "$task.AutoEssence.label"}],
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
    check("刻写券开关读得到（这次重构的由头）",
          v.get("AutoEssence/AutoEssenceDoOverride") is True)
    check("刻写券用官方中文名",
          lb.get("AutoEssence/AutoEssenceDoOverride") == "使用刻写券",
          f"实际 {lb.get('AutoEssence/AutoEssenceDoOverride')!r}")
    check("领取方式给出三个候选且是中文",
          o.get("AutoEssence/AutoEssenceObtainMode")
          == [["不领取（仅刷素材）", "Discard"], ["单倍领取", "ObtainScaling1"],
              ["双倍领取", "ObtainScaling2"]])
    check("地区是多选，值是列表",
          v.get("AutoEssence/AutoEssenceChooseLocation") == ["VFTheHub"])
    check("地区中文名走 $global.region 引用",
          o.get("AutoEssence/AutoEssenceChooseLocation")
          == [["枢纽区", "VFTheHub"], ["清波寨", "WLQingboStockade"]])
    check("循环次数按输入框读，保持字符串",
          v.get("AutoEssence/AutoEssenceRepeatCount") == "5")
    check("任务开关读得到", v.get("AutoUseSpMedication/@enabled") is False)

    print("\n=== 2. 终末地：写母本 ===")
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "AutoEssence/AutoEssenceDoOverride", False)
    now = mastercfg.read_maaend(automas, maaend)["values"]
    check("关掉刻写券，回读为假", ok and now["AutoEssence/AutoEssenceDoOverride"] is False, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "AutoEssence/AutoEssenceObtainMode", "ObtainScaling2")
    now = mastercfg.read_maaend(automas, maaend)["values"]
    check("改成双倍领取", ok and now["AutoEssence/AutoEssenceObtainMode"] == "ObtainScaling2", msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "AutoEssence/AutoEssenceRepeatCount", 9)
    now = mastercfg.read_maaend(automas, maaend)["values"]
    check("次数写进输入框且仍是字符串",
          ok and now["AutoEssence/AutoEssenceRepeatCount"] == "9", msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "AutoUseSpMedication/@enabled", True)
    now = mastercfg.read_maaend(automas, maaend)["values"]
    check("任务开关能开回来", ok and now["AutoUseSpMedication/@enabled"] is True, msg)

    print("\n=== 3. 终末地：该拒绝的要拒绝（826 的三条） ===")
    ok, msg = mastercfg.write_maaend(automas, maaend, "NoSuchTask/@enabled", True)
    check("不存在的任务→拒绝", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend, "AutoEssence/NoSuchOption", 1)
    check("不存在的选项→拒绝", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "AutoEssence/AutoEssenceObtainMode", "ObtainScaling9")
    check("没声明过的取值→拒绝", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "AutoEssence/AutoEssenceChooseLocation", [])
    check("地区一个都不选→拒绝（脚本会直接结束）", not ok, msg)
    ok, msg = mastercfg.write_maaend(automas, maaend,
                                     "AutoEssence/AutoEssenceChooseLocation", ["VFNowhere"])
    check("地区里混进没声明的→拒绝", not ok, msg)

    print("\n=== 4. 鸣潮：读写母本 ===")
    got = mastercfg.read_okww(automas, None)
    check("体力刷什么读得到",
          got["values"].get("DailyTask.json/Which to Farm") == "Simulation Challenge")
    check("残象聚落点位是只读的",
          got["readonly"].get("NightmareNestTask.json/Only Farm These Nests") == "落渊南丘")
    ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Which Forgery Challenge to Farm", 3)
    now = mastercfg.read_okww(automas, None)["values"]
    check("序号写进去且保持整数",
          ok and now["DailyTask.json/Which Forgery Challenge to Farm"] == 3, msg)
    ok, msg = mastercfg.write_okww(automas, "NightmareNestTask.json/Only Farm These Nests", "全部")
    check("只读项→拒绝（死命令：只刷落渊南丘）", not ok, msg)
    ok, msg = mastercfg.write_okww(automas, "DailyTask.json/Not A Key", 1)
    check("不存在的键→拒绝", not ok, msg)

    print("\n" + "=" * 46)
    if FAILED:
        print(f"❌ {len(FAILED)} 项没过：{FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
