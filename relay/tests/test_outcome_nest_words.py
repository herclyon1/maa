"""The nest-filter check says what the log shows, not what might have happened.

10-04 and 10-05 it told the group 「过滤没拿到点位名，按上游行为刷了全部」. The log
(ok-script.log 10-05 10:35:14-18) shows one nest clicked, 0/48, 「nightmare nest
unreachable, skip this run」 a second later: not one nest farmed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import outcome

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


# Real lines, ok-script.log 2026-10-05 (the filter was skipped: v3.7.3 find_nest).
DAY_1005 = """\
2026-10-05 10:35:06,057 INFO TaskExecutor NightmareNestTask:opened gray_book_boss
2026-10-05 10:35:14,196 INFO TaskExecutor NightmareNestTask:Box(name='已击败残象：0/48', x=889, y=374, width=198, height=30, confidence=100) is not complete
2026-10-05 10:35:14,398 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/48 (1729, 348) after_sleep 2
2026-10-05 10:35:18,183 INFO TaskExecutor NightmareNestTask:nightmare nest unreachable, skip this run: go_nest:48:18
"""

print("\n[10-05 那种：没过滤、点了一个没传送过去]")
c = outcome.nest_filter_checks(DAY_1005, "落渊南丘")[0]
check("判过滤没生效", c.ok, False)
check("不再说「刷了全部」", "刷了全部" in c.detail, False)
check("说了一个都没刷", "一个都没刷" in c.detail)

print("\n[没过滤、一个都没进]")
c = outcome.nest_filter_checks("NightmareNestTask:opened gray_book_boss\n", "落渊南丘")[0]
check("说了一个点位都没进", "一个点位都没进" in c.detail)

print("\n[过滤改动没装上、按设置这一轮不刷：不算没干成]")
text = ("NightmareNestTask:opened gray_book_boss\n"
        "NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n"
        "NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴\n")
nest = [x for x in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False,
                                       only_nest="落渊南丘") if x.label.startswith("残象聚落")]
check("巢穴几项都不算失败", [x.ok for x in nest], [True] * len(nest))

print("\n[10-05 整段：点了 0/48、传送不过去、F2 打不开、任务崩了——一次没打，不许算干成]")
CRASH = DAY_1005 + """\
2026-10-05 10:35:22,335 ERROR TaskExecutor NightmareNestTask:can't find gray_book_boss, make sure f2 is the hotkey for book
2026-10-05 10:35:22,358 ERROR TaskExecutor DailyTask:NightmareNestTask Failed Traceback (most recent call last):
"""
got = outcome.okww_checks(CRASH, expect_nest=True, expect_daily=False, expect_stamina=False, only_nest="落渊南丘")
by = {x.label: x for x in got}
check("「is not complete」那行不算打过", bool(outcome._NEST_ENGAGED.search(CRASH)), False)
check("残象聚落判没干成", by["残象聚落"].ok, False)
check("说传送不过去、一次没打", "一次没打" in by["残象聚落"].detail)
check("没打就不写「没进别的点位」", "残象聚落没进别的点位" in by, False)
from ark_relay import collector_okww  # noqa: E402
check("错误翻译不再说「打了」", "打了" in collector_okww._okww_error(
    "DailyTask:NightmareNestTask Failed Traceback (most recent call last):\nException: boom"), False)

print("\n[真打过的早上（10-03 那种）：进了战斗才算干成]")
FOUGHT = DAY_1005.replace("nightmare nest unreachable, skip this run: go_nest:48:18",
                          "enter combat None")
got = outcome.okww_checks(FOUGHT, expect_nest=True, expect_daily=False, expect_stamina=False)
check("有 enter combat 就算干成", [x.ok for x in got if x.label == "残象聚落"], [True])

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
