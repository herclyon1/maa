"""判断改用 OK-WW 自己写的结构化状态（info_set），散文只做兜底。

根治第 1 项：上游自己报的状态才是判据。2026-09-08 之前，「实际刷了哪个无音区」
「哪一步出的错」都是从提示语里刮的，上游一改措辞就失效——今天修的一串 bug
全是这么来的。OK-WW 每一步都写 `info_set 键 值`，那是它自己的状态。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay import collector  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

REAL = (ROOT / "tests" / "replay" / "2026-09-07" / "wuwa" / "OK-WW-07-27-50.log"
        ).read_text(encoding="utf-8", errors="replace")

print("[真实日志：读出上游自己报的状态]")
info = collector.okww_info(REAL)
check("实际传送到第几个无音区（0 起算）", info["fields"].get("Teleport to Tacet Suppression"), 1)
check("体力", info["fields"].get("current_stamina"), 75)
check("备用体力", info["fields"].get("back_up_stamina"), 26)
check("日常进度", info["fields"].get("current daily progress"), 180)
check("角色名整行都是值，不按空格切", info["fields"].get("Chars"), "千咲, 洛瑟菈, 绯雪")
check("走过哪几步", info["tasks"][:3], ["check weekly garden", "claim daily", "claim mail"])
check("上游没报错误", info["error"], "")

print("[刷的是哪个无音区：以上游报的实际序号为准]")
check("玄幽东岳（配置写 2、上游报 1）", collector._okww_farm(REAL)[0], "无音区·玄幽东岳")
faked = REAL.replace("info_set Teleport to Tacet Suppression 1",
                     "info_set Teleport to Tacet Suppression 3")
check("上游报 3 就是第 4 个", collector._okww_farm(faked)[0], "无音区·冰原运输港")

print("[上游自己说「错误 …」时，照它说的写，不用刮 traceback]")
said = ("2026-09-08 01:00:00,000 INFO TaskExecutor DailyTask:info_set current task farm echo\n"
        "2026-09-08 01:00:01,000 INFO TaskExecutor DailyTask:info_set 错误 combat check not in combat\n")
check("说清哪一步、什么事", collector._okww_error(said), "周本：没有进入战斗")

print("[包装层抛的错：任务名取出错那一刻的 current task，不是全程最后一个]")
wrapped = (
    "2026-09-08 01:00:00,000 INFO TaskExecutor DailyTask:info_set current task nest start\n"
    "2026-09-08 01:00:01,000 ERROR TaskExecutor DailyTask:NightmareNestTask Failed Traceback (most recent call last):\n"
    "ok.task.exceptions.WaitFailedException\n"
    "2026-09-08 01:00:02,000 INFO TaskExecutor DailyTask:info_set current task claim daily\n")
check("说的是残象聚落，不是后面那步领日常",
      collector._okww_error(wrapped), "残象聚落：打了但没打成")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
