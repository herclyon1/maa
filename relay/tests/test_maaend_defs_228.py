"""The phone page must show Chinese names and real choices on MaaEnd v2.28.

On 2026-09-09 the user's phone showed AutoEssenceDoOverride, AutoEssenceObtainMode
and friends as raw keys, with the claim-mode select collapsed into a text box.
v2.28.0-beta.4 had moved tasks/AutoEssence.json into a subfolder, the relay read
definitions by file name, found nothing, and fell back to the key - silently.
He asked: 「不是说强制要求了人话界面吗？」 This test runs read_maaend over the real
v2.28 files (fetched off the machine that night) and refuses any raw key.

The same release removed the standalone AutoUseSpMedication task; the config
still carries it. That has to be reported as an orphan, not shown as a live
setting.
"""
import json
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


FX = Path(__file__).resolve().parent / "fixtures" / "maaend228"
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
for k in ("AutoEssence/AutoEssenceObtainMode", "AutoEssence/AutoUseSpMedication", K, "AutoCollect/AutoCollectRoutes"):
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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
