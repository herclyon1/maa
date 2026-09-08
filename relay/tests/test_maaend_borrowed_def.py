"""The booster window option has no task file of its own; borrow MaaEnd's twin.

tasks/AutoUseSpMedication.json does not exist in v2.28.0-beta.4. The same option
is declared inside tasks/ProtocolSpace.json under another name, with case labels
that reference `$option.AutoUseSpMedicationExpireWithinDays.cases.*` - MaaEnd's
own statement that they are one option. Before this, the page had no choices to
show for it and write_maaend accepted any string for it unvalidated - the 826
shape, on the one setting the user asked to be put on the page.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import mastercfg
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


root = tmpdir()
automas = root / "AUTO-MAS"
cf = automas / "data" / "x" / "Default" / "ConfigFile"
cf.mkdir(parents=True)
(cf / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": [
    {"taskName": "AutoUseSpMedication", "enabled": True, "optionValues": {
        "AutoUseSpMedicationExpireWithinDays": {"type": "select", "caseName": "Days3"},
        "AutoUseSpMedicationUseCount": {"type": "input", "values": {"UseCount": "99"}},
        "AutoUseSpMedicationMaxSanity": {"type": "input", "values": {"MaxSanity": "9999"}},
    }}]}]}, ensure_ascii=False), encoding="utf-8")
maaend = root / "MaaEnd"
(maaend / "tasks").mkdir(parents=True)
# Shaped like the real file: the option lives under ProtocolSpace, cases named
# All / Days10 / Days3, labels pointing at the AutoUseSpMedication keys.
(maaend / "tasks" / "ProtocolSpace.json").write_text(json.dumps({"option": {
    "ProtocolSpaceSpMedicationExpireWithinDays": {
        "label": "$option.AutoUseSpMedicationExpireWithinDays.label",
        "type": "select", "default_case": "Days3",
        "cases": [{"name": n, "label": f"$option.AutoUseSpMedicationExpireWithinDays.cases.{n}.label"}
                  for n in ("All", "Days10", "Days3")]}}}), encoding="utf-8")

print("[读：借来的定义给页面提供可选项]")
r = mastercfg.read_maaend(automas, maaend)
key = "AutoUseSpMedication/AutoUseSpMedicationExpireWithinDays"
check("当前值读得到", r["values"].get(key), "Days3")
check("可选项来自借来的定义", [v for _, v in r["options"].get(key, [])], ["All", "Days10", "Days3"])
check("两个数字项也读得到", (r["values"].get("AutoUseSpMedication/AutoUseSpMedicationUseCount"),
                              r["values"].get("AutoUseSpMedication/AutoUseSpMedicationMaxSanity")), ("99", "9999"))

print("\n[写：只认借来的定义里有的值]")
ok, msg = mastercfg.write_maaend(automas, maaend, key, "Days99")
check("不认识的值被拒", ok, False)
check("拒绝时列出合法值", "All" in msg and "Days3" in msg, True)
ok, msg = mastercfg.write_maaend(automas, maaend, key, "All")
check("合法值写进去", ok, True)
check("回读是 All", mastercfg.read_maaend(automas, maaend)["values"].get(key), "All")
check("话里写清前后", "Days3" in msg and "All" in msg, True)

print("\n[没有借来的定义时，不认识的选项照旧拒绝而不是放行]")
(maaend / "tasks" / "ProtocolSpace.json").unlink()
ok, msg = mastercfg.write_maaend(automas, maaend, key, "Days10")
check("定义读不到时仍写得进（老行为，无表可验）", ok, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
