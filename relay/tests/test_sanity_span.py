"""理智/波片的「消耗」和「剩余」不能漏掉最后一趟。

两个游戏同一个毛病：读数都在每趟**开打前**播报。
* 终末地 09-03：五次领取只看到五个读数、四个步长，相邻差求和得 320，真花 400。
  正确写法是「趟数 × 步长」。
* 终末地 09-04：只刷一趟，一个读数零个步长，这一条自己算不出，
  要拿当天上一条的余量来补（116 → 37）。
* 鸣潮 09-04：收尾那行写的是 `current stamina: 37 must_use completed`，
  原正则只认 `not enough to continue`，于是最后一趟整个漏掉，
  报成「消耗 159、剩余 77」，真实是 199 和 37。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import collector, report  # noqa: E402

fails = []

def chk(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")

# 终末地：五次领取，读数 979→659
end5 = "\n".join([
    "[2026-09-03 09:00:00.000] 任务开始: 🎱基质刷取",
    *[f"[2026-09-03 09:0{i}:00.000] 当前理智 {979 - 80 * i}/360" for i in range(5)],
    *["[2026-09-03 09:06:00.000] ✅已完成一次基质刷取"] * 5,
    "[2026-09-03 09:07:00.000] 任务完成: 🎱基质刷取",
])
chk("终末地五趟消耗", collector._maaend_farm(end5).get("maaend_sanity_spent"), 400)

# 终末地：只刷一趟，一个读数——这一条算不出，交给上层补
end1 = "\n".join([
    "[2026-09-04 09:42:45.603] 任务开始: 🎱基质刷取",
    "[2026-09-04 09:44:00.149] ✅已完成一次基质刷取",
    "[2026-09-04 09:44:45.736] 当前理智 37/360",
    "[2026-09-04 09:44:49.380] 任务完成: 🎱基质刷取",
])
one = collector._maaend_farm(end1)
chk("单趟不硬编数字", one.get("maaend_sanity_spent"), None)
chk("单趟留了口子", one.get("maaend_sanity_runs_only"), 1)
es = [{"script": "MaaEnd", "sanity": 116, "raw": {}},
      {"script": "MaaEnd", "sanity": 37, "raw": dict(one)}]
report._fill_single_run_sanity(es)
chk("单趟由上一条补出", es[1]["raw"].get("maaend_sanity_spent"), 79)

# 鸣潮：收尾用的是另一种句式
ok = "\n".join([
    "info_set current_stamina 236", "info_set current_stamina 157",
    "info_set current_stamina 77",
    "current stamina: 37 must_use completed, no need to use back_up",
])
got = collector._okww_stamina(ok) if hasattr(collector, "_okww_stamina") else None
if got is None:
    import re
    tail = collector._OKWW_STAMINA_END.findall(ok)
    chk("鸣潮收尾读数认得出", tail[-1] if tail else None, "37")
    series = [int(m.group(1)) for m in collector._OKWW_STAMINA.finditer(ok)] + [int(tail[-1])]
    chk("鸣潮消耗", sum(a - b for a, b in zip(series, series[1:]) if a > b), 199)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
