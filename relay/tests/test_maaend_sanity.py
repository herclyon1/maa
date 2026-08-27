"""MaaEnd 的「剩余理智」报的是扣费之前的数字。

终末地协议空间的流程是：打完 → 奖励结算界面 → 花理智领取。MaaEnd 的
「当前理智 x/360」是在**结算界面**打的，而扣费发生在紧随其后的
「确认领取奖励」。所以日志里最后一条读数是**扣费之前**的值——只要最后一次
真的扣成了，直接报它就会高出整整一次的消耗。

运营 2026-08-25 指出：「MAAEND的剩余理智一直显示的是消耗之前的理智量」。
复查两天的真机日志，确认如此：

    08-24  当前理智 201 → 尝试使用理智消耗许可 → 理智不足，结束任务
           报出来是 201，真实剩余 41
    08-25  当前理智 241 → 扣 → 当前理智 81 → 理智不足，尝试不使用 → 结束
           报出来是 81，真实剩余也是 81（最后一次没扣）

两天的差别正是判断依据：**只看最后一次结算扣没扣**，而不是整段里扣过几次。
"""
import os, sys, tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector      # noqa: E402

fails = []
def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def parse(text):
    p = TMP / "x.log"
    p.write_text(text, encoding="utf-8")
    return collector.parse_maaend_log(p)


print("[最后一次扣成了 —— 要减掉一次消耗]")
# 08-24 的形状：两条读数都一样，日志里看不到下降，只能用兜底常量。
got = parse("""\
[2026-08-24 09:36:31.345] 当前理智 201/360
[2026-08-24 09:36:32.000] 进入协议空间成功
[2026-08-24 09:37:24.957] 当前理智 201/360
[2026-08-24 09:37:25.648] 尝试使用理智消耗许可
[2026-08-24 09:37:26.000] 确认领取奖励
[2026-08-24 09:37:31.284] 理智不足，结束任务
""")
check("看不到下降时用兜底的单次消耗", got.get("sanity"), 201 - collector._END_PS_COST)
check("上限照报", got.get("sanity_cap"), 360)

print("\n[最后一次被拒了 —— 读数就是终值]")
# 08-25 的形状：中间有一次真实下降，可以自标定；但最后一次没扣。
got = parse("""\
[2026-08-25 09:38:08.067] 当前理智 241/360
[2026-08-25 09:38:25.358] 进入协议空间成功
[2026-08-25 09:39:21.584] 当前理智 241/360
[2026-08-25 09:39:22.286] 尝试使用理智消耗许可
[2026-08-25 09:39:31.507] 进入协议空间成功
[2026-08-25 09:40:21.032] 当前理智 81/360
[2026-08-25 09:40:21.767] 尝试使用理智消耗许可
[2026-08-25 09:40:22.006] 理智不足，尝试不使用理智消耗许可
[2026-08-25 09:40:28.560] 理智不足，结束任务
""")
check("最后一次没扣就不减", got.get("sanity"), 81)
check("协议空间次数", got.get("protocol_runs"), 2)
check("知道是理智不足才收工", got.get("sanity_exhausted"), True)

print("\n[日志里有真实下降时，用实测值而不是兜底常量]")
# 单次消耗 40 的场景（关卡等级不同）：最后一次扣成，应减 40 而不是 160。
got = parse("""\
[2026-08-25 10:00:00.000] 当前理智 120/360
[2026-08-25 10:00:01.000] 尝试使用理智消耗许可
[2026-08-25 10:01:00.000] 当前理智 80/360
[2026-08-25 10:01:01.000] 尝试使用理智消耗许可
[2026-08-25 10:01:02.000] 确认领取奖励
""")
check("按实测的 40 减，而不是兜底的 160", got.get("sanity"), 40)

print("\n[一条读数都没有时不要瞎报]")
check("没有理智行就不写这个字段",
      "sanity" in parse("[2026-08-25 09:00:00.000] 任务完成: 🎁基建任务\n"), False)

print("\n[回满时间：MAA 自己写在 JSON 里，另外两个得算]")
from datetime import datetime                 # noqa: E402
from ark_relay.config import SERVER_TZ        # noqa: E402
ref = datetime(2026, 8, 25, 9, 42, tzinfo=SERVER_TZ)
# 终末地每 7 分 12 秒 1 点：还差 279 点 → 2008.8 分钟 ≈ 33.5 小时。
check("终末地 81/360 的回满时刻",
      collector._full_at_sentence(81, 360, collector._END_SANITY_SEC_PER_POINT, ref),
      "理智将在 2026-08-26 19:10 回满。")
# 鸣潮每 6 分钟 1 点：还差 198 点 → 1188 分钟 = 19.8 小时。
ref2 = datetime(2026, 8, 25, 13, 19, tzinfo=SERVER_TZ)
check("鸣潮 42/240 的回满时刻",
      collector._full_at_sentence(42, 240, collector._OKWW_SEC_PER_POINT, ref2),
      "理智将在 2026-08-26 09:07 回满。")
check("已经满了就不说回满", collector._full_at_sentence(240, 240, 360, ref2), "")
check("超上限也不说", collector._full_at_sentence(400, 360, 432, ref), "")
# 速率本身也钉住：改错了会让每天的报告都给出错误的时刻。
check("终末地 7 分 12 秒", collector._END_SANITY_SEC_PER_POINT, 432)
check("鸣潮 6 分钟", collector._OKWW_SEC_PER_POINT, 360)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
