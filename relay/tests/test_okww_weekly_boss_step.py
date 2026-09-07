"""周本要进 OK-WW 的步骤清单，否则「领满记账、周一恢复」永远触发不了。

2026-09-07：三趟各领一次（3/3→0），手动补跑碰上「次数已达上限」正常退出，
账本步骤里只有「无音区 ×1、残象聚落、周常乐园」，周本一个字没有，
handle 里找「4C声骸 已完成」自然找不到，周本状态一直是「本周还没领满」。
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

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

check("领满后进本：已完成、已领满", steps(HEAD + OCR.format(k=0) + CAP), ["周本（已完成，本周已领满）"])
check("领了一次正常退出", steps(HEAD + OCR.format(k=3) + CLAIM), ["周本（已完成，领了 1 次，本周还剩 2 次）"])
check("领了一次但卡结算页（今早）", steps(HEAD + OCR.format(k=3) + CLAIM + ERR), ["周本（领了 1 次，然后没能退出副本）"])
check("没开周本就不写", steps("2026-09-07 11:34:06,670 INFO TaskExecutor DailyTask:open_daily\n"), [])
check("剩余 0 次、没弹上限对话（09-02 的样本）：也算已领满", steps(HEAD + OCR.format(k=0)), ["周本（已完成，本周已领满）"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
