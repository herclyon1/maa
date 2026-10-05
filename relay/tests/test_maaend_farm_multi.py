"""Two farming tasks in one MaaEnd run, and farming tasks skipped by schedule.

Audit 2026-10-05: _farm_segment stopped at the first farming task's
「任务完成」, so with both 基质刷取 and 协议空间 on, the second one's runs,
drops and sanity were lost. The weekday skip was only recognised for 自动采集,
while AutoEssence and ProtocolSpace carry the same TaskSchedule option
(tests/fixtures/maaend228/tasks): a skipped day read as 「刷 基质刷取 ×0」.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector_maaend, core

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


ESSENCE = [
    "[2026-10-05 10:00:00.000] 任务开始: 🎱基质刷取",
    "[2026-10-05 10:00:01.000] 📌目标地点：枢纽区",
    "[2026-10-05 10:01:00.000] 当前理智 240/360",
    "[2026-10-05 10:02:00.000] ✅已完成一次基质刷取",
    "[2026-10-05 10:02:01.000] 是无暇基质",
    "[2026-10-05 10:03:00.000] 当前理智 160/360",
    "[2026-10-05 10:04:00.000] ✅已完成一次基质刷取",
    "[2026-10-05 10:04:01.000] 是无暇基质",
    "[2026-10-05 10:05:00.000] 任务完成: 🎱基质刷取",
]
PROTOCOL = [
    "[2026-10-05 10:06:00.000] 任务开始: ⚔️协议空间",
    "[2026-10-05 10:06:30.000] 进入协议空间成功",
    "[2026-10-05 10:07:00.000] 当前理智 80/360",
    "[2026-10-05 10:07:01.000] 尝试使用理智消耗许可",
    "[2026-10-05 10:07:02.000] 获得以下物品：",
    "[2026-10-05 10:07:02.000] 协议棱柱组 ×5",
    "[2026-10-05 10:07:03.000] 理智不足，结束任务",
    "[2026-10-05 10:07:04.000] 任务完成: ⚔️协议空间",
]

print("[两个刷取任务都开：两个都读]")
both = collector_maaend._maaend_farm("\n".join(ESSENCE + PROTOCOL))
check("两个名字都在", both.get("maaend_farm"), "基质刷取、协议空间")
check("趟数相加（基质 2 + 协议空间 1）", both.get("maaend_farm_runs"), 3)
check("掉落合在一起", both.get("maaend_farm_drops"), {"无暇基质": 2, "协议棱柱组": 5})
check("地点", both.get("maaend_farm_place"), "枢纽区")

print("\n[只开一个：和以前读法一样（反例）]")
one = collector_maaend._maaend_farm("\n".join(ESSENCE))
check("名字", one.get("maaend_farm"), "基质刷取")
check("趟数", one.get("maaend_farm_runs"), 2)
check("理智 2×80", one.get("maaend_sanity_spent"), 160)
check("掉落", one.get("maaend_farm_drops"), {"无暇基质": 2})
ps = collector_maaend._maaend_farm("\n".join(PROTOCOL))
check("只开协议空间", (ps.get("maaend_farm"), ps.get("maaend_farm_runs")), ("协议空间", 1))

print("\n[按排班跳过的刷取任务：不算刷了、不算做了]")
SKIP = [
    "[2026-10-06 10:00:00.000] 任务开始: 🎱基质刷取",
    "[2026-10-06 10:00:00.100] 现在游戏时间是周二，根据执行周期跳过任务",
    "[2026-10-06 10:00:00.200] 任务完成: 🎱基质刷取",
    "[2026-10-06 10:00:01.000] 任务开始: 🧺自动采集",
    "[2026-10-06 10:00:01.100] 现在游戏时间是周二，根据执行周期跳过任务",
    "[2026-10-06 10:00:01.200] 任务完成: 🧺自动采集",
]
skipped = collector_maaend._maaend_farm("\n".join(SKIP))
check("跳过的基质刷取不算刷取", skipped, {})
check("跳过的后面还有真刷的协议空间：只算协议空间",
      collector_maaend._maaend_farm("\n".join(SKIP + PROTOCOL)).get("maaend_farm"), "协议空间")

UNCLOSED = ["[2026-10-06 09:00:00.000] 任务开始: 🎱基质刷取",
            "[2026-10-06 09:01:00.000] ✅已完成一次基质刷取"] + SKIP[3:]
check("没收尾的刷取后面跟着自动采集的跳过行：刷取照算（只认自己的跳过行）",
      collector_maaend._maaend_farm("\n".join(UNCLOSED)).get("maaend_farm_runs"), 1)

import tempfile  # noqa: E402
log = Path(tempfile.mkdtemp()) / "skip.log"
log.write_text("\n".join(SKIP) + "\n", encoding="utf-8")
r = collector_maaend.parse_maaend_log(log)
check("每个按排班跳过的都记下", r.get("maaend_period_skipped"), {"基质刷取": "周二", "自动采集": "周二"})
check("自动采集的老字段照旧", r.get("maaend_collect_skipped"), "周二")
entry = {"script": "MaaEnd", "ok": True, "raw": r, "sanity": None}
did, cost, out, left, notes = core._block_maaend(entry, r, None)
check("报告不写「刷 基质刷取」", any("刷 基质刷取" in x for x in did), False)
check("报告写明按排班跳过", any("基质刷取 今天周二不在排班里" in x for x in notes), True)
check("自动采集的说法照旧", any("自动采集 今天周二不是采集日" in x for x in notes), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
