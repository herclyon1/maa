"""OK-WW's battle-pass line is about the battle pass, not about a fight.

DailyTask.claim_battle_pass (upstream src/task/DailyTask.py) opens the battle-pass
page and logs 「can not battle pass, maybe ended」 when no level digits are read
there; the claim is skipped and the run goes on. The relay's table read it as
「没能进入战斗」 until 10-11 (found by the 游戏-中继二 session on 10-10, BOARD
被指出.txt line 742). The lines below are the real ones of the 2026-09-29 09:28 run
(D:\\ark\\automas\\history\\2026-09-29\\wuwa\\OK-WW-05-20-18.log, the ERROR line at
09:28:53 and its neighbours), read off the game machine on 10-11.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts
from ark_relay.features.verify import collector_okww

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


REAL = """2026-09-29 09:28:42,334 INFO TaskExecutor DailyTask:info_set current task in main esc=True
2026-09-29 09:28:43,334 INFO TaskExecutor DailyTask:battle pass
2026-09-29 09:28:53,798 INFO TaskExecutor TaskExecutor:wait_until timeout <function OCR.wait_ocr.<locals>.<lambda> at 0x000002BC775F9C60> 10 seconds
2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended
2026-09-29 09:28:53,807 INFO TaskExecutor DailyTask:info_set current task wait main esc=True
"""
REAL = REAL.replace("maybe ended\n", "maybe ended \n")    # upstream's line ends in a space
WANT = f"日常清单：{texts.OKWW_BATTLE_PASS_UNCLAIMED}"

print("[the battle-pass line is translated as the battle pass]")
said = collector_okww._okww_say("DailyTask", "can not battle pass, maybe ended", "")
check("the sentence for the raw line", said, WANT)
check("it names 战令", "战令" in said)
check("it no longer says 没能进入战斗", "没能进入战斗" in said, False)
check("plain language", texts.plain(said), [])
# When OK-WW records the line as the run's 错误 (info_set), the report takes this path.
recorded = REAL.replace(
    "maybe ended \n",
    "maybe ended \n2026-09-29 09:28:53,799 INFO TaskExecutor DailyTask:info_set 错误 can not battle pass, maybe ended\n")
recorded = "2026-09-29 09:27:30,000 INFO TaskExecutor DailyTask:info_set current task claim mail\n" + recorded
check("recorded as the run's reason -> the same battle-pass sentence", collector_okww._okww_error(recorded), WANT)
check("the 「not in combat」 line keeps its own fight wording",
      collector_okww._okww_say("BaseCombatTask", "combat check not in combat", ""), "战斗：没有进入战斗")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
