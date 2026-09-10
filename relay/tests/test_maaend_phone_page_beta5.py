"""The phone page must show the per-region gathering lists MaaEnd v2.28.0-beta.5 uses.

On 2026-09-10 the relay had already rewritten the master for the new format, but
the page's whitelist still asked for the removed AutoCollectRoutes key, so the
gathering section showed only the schedule. The user: 「手机遥控器页面你也没修啊。
按照他新版本格式去修。」 This runs read_maaend over the real beta.5 definitions and
locale (fetched off the machine that day) with the migrated master, and requires
every new key to appear with a Chinese name, real choices and the picks kept.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import mastercfg
from _tmp import tmpdir

fails = []
HAN = re.compile(r"[一-鿿]")


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


FX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-09-10"
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
check("没有列进「没翻译」的", r.get("untranslated"), [])
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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
