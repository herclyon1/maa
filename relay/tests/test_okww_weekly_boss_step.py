"""周本要进 OK-WW 的步骤清单，否则「领满记账、周一恢复」永远触发不了。

2026-09-07：三趟各领一次（3/3→0），手动补跑碰上「次数已达上限」正常退出，
账本步骤里只有「无音区 ×1、残象聚落、周常乐园」，周本一个字没有，
handle 里找「4C声骸 已完成」自然找不到，周本状态一直是「本周还没领满」。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

d = tmpdir()
def steps(text):
    f = d / "x.log"; f.write_text(text, encoding="utf-8")
    return collector.parse_okww_log(f).get("okww_steps") or []

HEAD = "2026-09-07 11:28:57,378 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
OCR = "2026-09-07 11:29:12,120 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：{k}/3_0.99, x60_0.79]\n"
CLAIM = "2026-09-07 10:00:32,309 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
CAP = "2026-09-07 11:31:04,847 INFO TaskExecutor FarmEchoTask:周本领奖：没认出领奖弹窗，整屏读到 [提示_1.00, 收取物资次数已达到上限，是否退出副本？_0.99, 退出副本_1.00]\n"
ERR = "2026-09-07 10:00:43,366 ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card Traceback (most recent call last):\n"

# The overlay's read-back after a claim (format fixed with the overlay; see outcome.WEEKLY_CLAIM_OK).
BACK = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 {k}/3→{n}/3\n"
SAME = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（{k}/3），这次没领到\n"
UNREAD = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读没读到本周剩余次数\n"
LAND = "2026-09-07 10:06:50,862 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n"
FIGHT = "2026-09-07 10:06:52,779 INFO TaskExecutor FarmEchoTask:enter combat None\n"

check("领满后进本：已完成、已领满", steps(HEAD + OCR.format(k=0) + CAP), ["周本（已完成，本周已领满）"])
check("领了一次、回读确认：正常退出", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2)),
      ["周本（已完成，领了 1 次，本周还剩 2 次）"])
check("领了一次但卡结算页（09-07 早）、回读确认", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + ERR),
      ["周本（领了 1 次，之后出错，原因见失败于）"])

print("\n[「已点确认」只是点了，回读确认才算领到]")
check("旧日志只有「已点确认」：不算领到、不写已完成", steps(HEAD + OCR.format(k=3) + CLAIM),
      ["周本（点了确认 1 次、领完没再读次数，没核实领到）"])
check("旧日志只有「已点确认」又出错（09-07 早的原样）", steps(HEAD + OCR.format(k=3) + CLAIM + ERR),
      ["周本（点了确认 1 次、领完没再读次数，没核实领到，之后出错，原因见失败于）"])
check("回读次数没变：没领到", steps(HEAD + OCR.format(k=2) + CLAIM + SAME.format(k=2)),
      ["周本（领完再读次数没变 1 次，没领到）"])
check("回读没读到：不算领到", steps(HEAD + OCR.format(k=2) + CLAIM + UNREAD),
      ["周本（领完再读没读到剩余次数 1 次，没核实领到）"])
check("一次确认、一次没变：领了 1 次另说那次", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + CLAIM + SAME.format(k=2)),
      ["周本（已完成，领了 1 次，本周还剩 2 次；另有领完再读次数没变 1 次，没领到）"])

print("\n[剩余次数没读到不等于领满]")
# A verified claim with no counter reading anywhere: unknown, never 「本周已领满」.
no_read = HEAD + CLAIM + "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 ?/3→?/3\n"
check("这种行不会被当成回读确认", steps(no_read), ["周本（点了确认 1 次、领完没再读次数，没核实领到）"])
from ark_relay import outcome  # noqa: E402
orig = outcome.weekly_left
outcome.weekly_left = lambda text: None
try:
    check("领到了但读不到剩余：说没读到，不说领满", steps(HEAD + CLAIM + BACK.format(k=3, n=2)),
          ["周本（已完成，领了 1 次，本周剩余次数没读到）"])
finally:
    outcome.weekly_left = orig

print("\n[没有开打的记录就不说「打了」]")
check("打了没领（有 enter combat）", steps(HEAD + OCR.format(k=3) + LAND + FIGHT), ["周本（打了，没领到奖励）"])
check("进了本没打（10-05 早：只有 prepared as）", steps(HEAD + OCR.format(k=3) + LAND), ["周本（进了本，没打起来，没领到奖励）"])
check("没进本", steps(HEAD + OCR.format(k=3)), ["周本（没进本，一次没打）"])
# Real line, replay 2026-09-01 OK-WW-06-58-23 (11:01:39): used to read 「打了，没领到奖励」.
NOWAVE = "2026-09-01 11:01:39,518 INFO TaskExecutor FarmEchoTask:波片不足挡住开启挑战，点取消跳过本次周本\n"
check("波片不够跳过：说奖励没领、没打", steps(HEAD + OCR.format(k=1) + NOWAVE), ["周本（奖励没领：结晶波片不足，这一趟没打）"])
# Since 2026-10-06 the overlay also ends the run as failed right after the skip line
# (constructed from ark_overrides.tasks.py's click_team_challenge path).
NOWAVE_END = ("2026-09-01 11:01:40,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本：结晶波片不够领奖"
          "（游戏提示「结晶波片不足，无法获取奖励」），点了取消，这一趟没打\n")
check("波片不够跳过＋按失败结束：日报同一行", steps(HEAD + OCR.format(k=1) + NOWAVE + NOWAVE_END),
      ["周本（奖励没领：结晶波片不足，这一趟没打）"])
check("领到一次后波片不够：日报说剩下的没领", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + NOWAVE + NOWAVE_END),
      ["周本（已完成，领了 1 次，本周还剩 2 次；剩下的奖励没领：结晶波片不足）"])
check("没开周本就不写", steps("2026-09-07 11:34:06,670 INFO TaskExecutor DailyTask:open_daily\n"), [])
check("剩余 0 次、没弹上限对话（09-02 的样本）：也算已领满", steps(HEAD + OCR.format(k=0)), ["周本（已完成，本周已领满）"])

print("\n[周常乐园：上游现在记的是中文「乐园任务完成, 已达到上限」（GardenTask.run，2026-09-14 读的源码）]")
G = "2026-09-14 10:02:11,001 INFO TaskExecutor GardenTask:Garden current: [Box(name='2000/2000')]\n"
check("做完了（中文）", steps(G + "2026-09-14 10:02:12,001 INFO TaskExecutor GardenTask:乐园任务完成, 已达到上限\n"), ["周常乐园（本周已完成）"])
check("做完了（旧英文）", steps("x GardenTask:weekly garden already completed\n"), ["周常乐园（本周已完成）"])
# Only the counter read, no 「乐园任务完成」: not shown as done (2026-10-05 evidence rule).
check("跑了但没有完成那句：不算完成", steps(G), ["周常乐园（没读到做完，不算完成）"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
