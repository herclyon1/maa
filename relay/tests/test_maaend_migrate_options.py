"""The master config must be rewritten when MaaEnd changes an option's format.

Real files, 2026-09-10: the AUTO-MAS master as it was that morning, and the
v2.28.0-beta.5 definitions of AutoCollect and AutoEssence. MaaEnd discards a
saved value whose option it no longer has, so the old 自动采集 route list has to
become the per-region lists it replaced - with the same routes picked - and
the location list of 基质刷取 needs the AutoEssenceMenu key it now hangs under.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import mastercfg

FIX = Path(__file__).parent / "fixtures" / "maaend-2026-09-10"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


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

    print("\n[再跑一次：没有改动]")
    changes2, note2 = mastercfg.migrate_maaend_options(automas, maaend)
    check("幂等", (changes2, note2), ([], ""))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
