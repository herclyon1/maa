"""MaaEnd farming drops read from its 「获得以下物品：」 blocks (2026-09-29).

MaaEnd prints a claim's items as a block whose item lines carry no 「获得」
(fixtures/maaend-farm-drops/2026-09-27.log lines 320-322: the header, then
one line per item with its count). `_maaend_farm` only knew 「是X基质」
lines and the single-line 「获得 X ×n」, so after the switch to 协议空间
`maaend_farm_drops` stayed empty and the daily report printed no output row.
Every log below is a real, unedited MaaEnd log from the machine
(fixtures/maaend-farm-drops/).
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import collector_maaend

D = pathlib.Path(__file__).resolve().parent / "fixtures" / "maaend-farm-drops"
fails = []


def chk(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


def farm(name):
    return collector_maaend._maaend_farm((D / name).read_text(encoding="utf-8"))


def pick(d):
    """The fields this fix is about. maaend_sanity_spent is left out on
    purpose: 2026-09-27 reads 320 where 160 was spent (the second entry hit
    「理智不足，结束任务」 before claiming) - a separate issue."""
    keys = ("maaend_farm", "maaend_farm_place", "maaend_farm_runs", "maaend_farm_drops")
    return {k: d[k] for k in keys if k in d}


# Protocol Space, 2026-09-27 09:45: two entries, one claim (lines 320-322).
# The exact dict also proves the 基建任务 / 信用点购物 / 选剑演武 /
# 日常奖励领取 blocks of the same log (信用, 武库配额, 协议棱柱 …) stay out.
chk("09-27 协议空间", pick(farm("2026-09-27.log")),
    {"maaend_farm": "协议空间", "maaend_farm_runs": 2,
     "maaend_farm_drops": {"折金票": 68000, "行动资历": 960}})

# Protocol Space, 2026-09-28 10:46: two claims (lines 310-312 and 342-344).
chk("09-28a 协议空间", pick(farm("2026-09-28a.log")),
    {"maaend_farm": "协议空间", "maaend_farm_runs": 2,
     "maaend_farm_drops": {"折金票": 136000, "行动资历": 1920}})

# Negative: 2026-09-28 12:10:45 opened 协议空间 with 17 sanity, never got
# 「进入协议空间成功」, and went straight on to 选剑演武.
r = farm("2026-09-28b.log")
chk("09-28b 没进去", pick(r), {"maaend_farm": "协议空间"})
full = collector_maaend.parse_maaend_log(D / "2026-09-28b.log")
chk("09-28b 次数", full.get("maaend_farm_runs"), None)
chk("09-28b 产出", full.get("maaend_farm_drops"), None)
chk("09-28b 理智不足", full.get("sanity_exhausted"), True)

# Essence, 2026-09-24 10:09: two runs, ten 「是X基质」 lines, no block.
chk("09-24 基质刷取", pick(farm("2026-09-24_MaaEnd-06-07-50.log")),
    {"maaend_farm": "基质刷取", "maaend_farm_place": "清波寨", "maaend_farm_runs": 2,
     "maaend_farm_drops": {"无暇基质": 6, "高纯基质": 4}})

# Essence, 2026-09-25 09:44: the claim never landed (full bag), nothing counted.
chk("09-25 基质刷取 背包满", pick(farm("2026-09-25_MaaEnd-05-25-36.log")),
    {"maaend_farm": "基质刷取", "maaend_farm_place": "清波寨"})

# The same 09-27 log has plenty of blocks outside the farming task; the
# block reader sees them, the farm reader must not.
whole = collector_maaend._item_blocks((D / "2026-09-27.log").read_text(encoding="utf-8").splitlines())
chk("09-27 全日 信用", whole.get("信用"), 20 + 400 + 300)
chk("09-27 全日 武库配额", whole.get("武库配额"), 80)
chk("09-27 产出不含信用", "信用" in (farm("2026-09-27.log").get("maaend_farm_drops") or {}), False)

# Not tied to the task name: the same log with the task renamed is still read
# as the farming task because its own lines carry 「当前理智 N/M」.
t27 = (D / "2026-09-27.log").read_text(encoding="utf-8")
renamed = t27.replace("⚔️协议空间", "⚔️某新理智玩法")
chk("改名 仍认", pick(collector_maaend._maaend_farm(renamed)),
    {"maaend_farm": "某新理智玩法", "maaend_farm_runs": 2,
     "maaend_farm_drops": {"折金票": 68000, "行动资历": 960}})
# Renamed and without the sanity readings: no farming task at all, and the
# 基建任务 / 信用点购物 blocks do not turn into one.
bare = "\n".join(x for x in renamed.splitlines() if "当前理智" not in x)
chk("改名无理智行 不认", collector_maaend._maaend_farm(bare), {})

# Block boundary: the first non-item line closes it, even at the same
# timestamp; a framework line closes it too.
lines = [
    "[2026-09-27 09:46:37.319] 获得以下物品：",
    "[2026-09-27 09:46:37.319] 折金票 ×68000",
    "[2026-09-27 09:46:37.319] 继续行动",
    "[2026-09-27 09:46:37.319] 行动资历 ×960",
    "[2026-09-27 09:46:38.000] 获得以下物品：",
    "[2026-09-27 09:46:38.000] 信用 ×20",
    "[2026-09-27 09:46:38.001][ERR][Px1][Tx1][A.cpp][L1][f] size x 16",
    "[2026-09-27 09:46:38.002] 信用 ×400",
]
chk("块边界", collector_maaend._item_blocks(lines), {"折金票": 68000, "信用": 20})

if fails:
    print("\n".join(fails)); sys.exit(1)
print("all checks passed")
