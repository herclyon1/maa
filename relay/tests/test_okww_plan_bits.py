"""Tomorrow's OK-WW plan lines, read from the master config that takes effect.

plan._okww_plan_bits and plan._okww_extra_bit had no test (audit 2026-10-05,
E). They are not dead code - plan.py:665 and :365 call them - so they get
behaviour tests instead of deletion. Pinned here: the master DailyTask.json is
read, quick config overrides it when on, the weekly-boss commandeering of
「Teleport and Farm 4C Echo」 is reported as the weekly boss, and nothing at all
is said when there is nothing to read.
"""
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

os.environ["ARK_STATE_DIR"] = str(tmpdir())        # no no-stamina-farm flag
os.environ.pop("ARK_OKWW_DIR", None)
from ark_relay import plan

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def automas(daily, *, farm=None, quick=None):
    root = tmpdir()
    d = root / "data" / "okww-sid" / "Default" / "ConfigFile"
    d.mkdir(parents=True)
    (d / "DailyTask.json").write_text(json.dumps(daily), encoding="utf-8")
    if farm is not None:
        (d / "FarmEchoTask.json").write_text(json.dumps(farm), encoding="utf-8")
    if quick is not None:
        (root / "config").mkdir()
        (root / "config" / "ScriptConfig.json").write_text(json.dumps({
            "s9": {"Info": {"Name": "OK-WW"},
                   "SubConfigsInfo": {"UserData": {"u1": {
                       "Info": {"IfQuickConfig": True}, "Task": quick}}}}}), encoding="utf-8")
    return root, d


print("[_okww_plan_bits]")
check("no AUTO-MAS dir -> nothing", plan._okww_plan_bits(None), [])
check("no data dir -> nothing", plan._okww_plan_bits(tmpdir()), [])

root, _ = automas({"Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
                   "Additional Tasks to Run After Daily Task": ["Auto Farm all Nightmare Nest"]})
bits = plan._okww_plan_bits(root)
check("master read: stamina line", bits[0], "体力刷 模拟领域·贝币")
check("master read: nest farmed to full", any("全部点位，刷到打满" in b for b in bits), True)
check("nest-full is not repeated as an extra task", any(b.startswith("附加") for b in bits), False)

root, _ = automas({"Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
                   "Additional Tasks to Run After Daily Task": []},
                  quick={"WhichToFarm": "Simulation Challenge", "MaterialSelection": "Weapon EXP",
                         "WhichTacetSuppressionToFarm": 1, "WhichForgeryChallengeToFarm": 1,
                         "FarmNightmareNestForDailyEcho": False, "AdditionalTasks": []})
check("quick config on -> its value wins over the master",
      plan._okww_plan_bits(root)[0], "体力刷 模拟领域·武器经验")

print("[_okww_extra_bit]")
_, d = automas({}, farm={"Teleport to Boss": "Weekly Challenge", "Boss Level": "90",
                         "Which Weekly Boss to Teleport": 2})
with mock.patch.object(plan, "_weekly_boss_state", lambda: (False, "")):
    check("weekly-boss commandeered, not done -> fought tomorrow",
          plan._okww_extra_bit(d, ["Teleport and Farm 4C Echo"], {}),
          "附加 周本 战歌重奏第 2 个（90 级），明天会打")
with mock.patch.object(plan, "_weekly_boss_state", lambda: (True, "鸣式·利维亚坦")):
    check("weekly-boss quota full -> says not fought",
          plan._okww_extra_bit(d, ["Teleport and Farm 4C Echo"], {}),
          "附加 周本 鸣式·利维亚坦（90 级），本周已打满，明天不打")
_, d2 = automas({}, farm={"Teleport to Boss": "Normal"})
check("not commandeered -> named as the echo task (translated when the pack has it)",
      plan._okww_extra_bit(d2, ["Teleport and Farm 4C Echo"], {"Teleport and Farm 4C Echo": "传送刷4C声骸"}),
      "附加 传送刷4C声骸")
check("more than two -> first two and a count",
      plan._okww_extra_bit(d2, ["A", "B", "C"], {}), "附加 A、B 等 3 项")
check("only nest-full / nothing -> no line",
      (plan._okww_extra_bit(d2, ["Auto Farm all Nightmare Nest"], {}), plan._okww_extra_bit(d2, [], {})),
      ("", ""))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
