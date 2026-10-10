"""自动囤货's buy lists must survive MaaEnd turning them from checkbox into switch.

Real files, 2026-10-10: the AUTO-MAS master (only the AutoStockStaple task and
one untouched task kept) and MaaEnd's AutoStockStaple.json of that day. From
10-03 every MaaEnd launch logged 「选项 "AutoStockBuy…" 的类型已从 "checkbox" 变更为
"switch"，已重置为默认值」 six times and bought by the defaults, not by the
per-item lists the master holds. The migration carries each list over to the
new `<key>Items` checkbox, with the switch on when anything was picked.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import mastercfg

FIX = Path(__file__).parent / "fixtures" / "maaend-2026-10-10"
KEYS = ("AutoStockBuyDailyGoodsValleyIV", "AutoStockBuyStockFactoryGoodsValleyIV",
        "AutoStockBuyCulturalGoodsValleyIV", "AutoStockBuyDailyGoodsWuling",
        "AutoStockBuyStockFactoryGoodsWuling", "AutoStockBuyCulturalGoodsWuling")
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
