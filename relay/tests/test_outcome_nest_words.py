"""The nest-filter check says what the log shows, not what might have happened.

10-04 and 10-05 it told the group 「过滤没拿到点位名，按上游行为刷了全部」. The log
(ok-script.log 10-05 10:35:14-18) shows one nest clicked, 0/48, 「nightmare nest
unreachable, skip this run」 a second later: not one nest farmed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import outcome

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
from ark_relay.features.verify import collector_okww  # noqa: E402
check("错误翻译不再说「打了」", "打了" in collector_okww._okww_error(
    "DailyTask:NightmareNestTask Failed Traceback (most recent call last):\nException: boom"), False)

print("\n[真打过的早上（10-03 那种）：进了战斗才算干成]")
FOUGHT = DAY_1005.replace("nightmare nest unreachable, skip this run: go_nest:48:18",
                          "enter combat None")
got = outcome.okww_checks(FOUGHT, expect_nest=True, expect_daily=False, expect_stamina=False)
check("有 enter combat 就算干成", [x.ok for x in got if x.label == "残象聚落"], [True])

print("\n[只刷两个（他 10-12 11:2x：梦枢天罗、落渊南丘）：进两个点位不算进了别的]")
TWO = ("NightmareNestTask:nightmare nest: 只刷 ['梦枢天罗', '落渊南丘']（设置来自母本）\n"
       "NightmareNestTask:left_click 已击败残象：0/48 (1729, 348) after_sleep 2\n"
       "NightmareNestTask:enter combat None\n"
       "NightmareNestTask:left_click 已击败残象：0/41 (1729, 420) after_sleep 2\n"
       "NightmareNestTask:enter combat None\n")
got = {x.label: x.ok for x in outcome.nest_filter_checks(TWO, "梦枢天罗,落渊南丘")}
check("两个点位：没进别的点位", got.get("残象聚落没进别的点位"), True)
got = {x.label: x.ok for x in outcome.nest_filter_checks(TWO, "落渊南丘")}
check("设置只一个却进了两个：照旧判进了别的", got.get("残象聚落没进别的点位"), False)
THREE = TWO + "NightmareNestTask:left_click 已击败残象：0/45 (1729, 500) after_sleep 2\n"
got = {x.label: x.ok for x in outcome.nest_filter_checks(THREE, "梦枢天罗，落渊南丘")}
check("设置两个却进了三个：判进了别的", got.get("残象聚落没进别的点位"), False)

from ark_relay.core import mastercfg_okww  # noqa: E402
check("他定的两个", list(mastercfg_okww.ONLY_NESTS), ["梦枢天罗", "落渊南丘"])
check("全角逗号也认", mastercfg_okww.nest_names(" 梦枢天罗，落渊南丘 "), ["梦枢天罗", "落渊南丘"])

print("\n[日常早做完的第二趟（10-12 11:41 补跑）：周本停下照样判没干成]")
SECOND = ("DailyTask:info_set total daily points 160\n"
          "FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
          "FarmEchoTask:teleport_to_boss prepared as Weekly Challenge\n"
          "FarmEchoTask:周本领奖：认出弹窗，点确认。读到 ...\n"
          "FarmEchoTask:周本领奖：已点确认\n"
          "FarmEchoTask:" + outcome.FAILED_MARK + "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。\n"
          "NightmareNestTask:nightmare nest: 只刷 ['梦枢天罗', '落渊南丘']（设置来自母本）\n"
          "NightmareNestTask:left_click 已击败残象：0/48 (1729, 348) after_sleep 2\n"
          "NightmareNestTask:enter combat None\n"
          "NightmareNestTask:nightmare nest: 指定点位都已打满，跳过（截图 nest_all_full）\n"
          "DailyTask:Daily Task Completed\n")
got = {x.label: x for x in outcome.okww_checks(SECOND, expect_nest=True, only_nest="梦枢天罗,落渊南丘")}
check("认出日常早做完", got["今日日常此前已完成，本轮仅领奖"].ok)
check("周本判没干成", got["周本领到了奖励"].ok, False)
check("说了停在哪", "没等到结算页" in got["周本领到了奖励"].detail)
nest = [x.ok for k, x in got.items() if k.startswith("残象聚落") and "点位" not in k]
check("聚落照判（跑了就判）", nest, [True])
check("不要刷体力那项", "刷体力" in got, False)
got = {x.label for x in outcome.okww_checks(SECOND.replace("NightmareNestTask", "X"), expect_nest=True)}
check("这趟没跑聚落就不判聚落", [k for k in got if k.startswith("残象聚落") and "点位" not in k], [])

# Since a8cc86b6 the overlay no longer ends the run as failed here: it logs the line below
# (okww_files/ark_overrides.tasks.py, weekly claim) and hands the lap back to upstream.
# Same run with today's line: still no confirmed claim, so still not claimed.
SECOND_NOW = SECOND.replace(
    "FarmEchoTask:" + outcome.FAILED_MARK + "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。\n",
    "FarmEchoTask:周本领奖：点了确认后没看到「退出副本」，交回上游。整屏读到 挑战成功\n")
check("新句子样本确实换掉了旧句子", outcome.FAILED_MARK in SECOND_NOW, False)
got = {x.label: x for x in outcome.okww_checks(SECOND_NOW, expect_nest=True, only_nest="梦枢天罗,落渊南丘")}
check("新句子：认出日常早做完", got["今日日常此前已完成，本轮仅领奖"].ok)
check("新句子：周本照样判没领到", got["周本领到了奖励"].ok, False)

print("\n[兜底：日志有「这一趟按失败结束」或「附加任务出错」，不管别的分支怎么判，这趟都不算干成]")
# The 11:41 run's own log was never archived (ark-evidence has only the 05:18 run and
# screenshots for 10-12), so the lines are real ones from other days in the 11:41 order:
# the weekly boss runs in open_daily_first, before the dailies page reads the points.
# 附加任务出错 wording: OK-WW log 2026-09-21 10:21:00,184 and 2026-10-05 10:34:52,359.
WHY = "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。"
TAIL = ("2026-10-12 07:45:20,100 INFO TaskExecutor DailyTask:info_set total daily points 160\n"
        "2026-10-12 07:58:51,996 INFO TaskExecutor DailyTask:Daily Task Completed\n")
REAL_1141 = ("2026-10-12 07:44:30,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
             "2026-10-12 07:44:40,000 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as Weekly Challenge\n"
             "2026-10-12 07:44:52,609 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
             "2026-10-12 07:45:02,499 ERROR TaskExecutor FarmEchoTask:" + outcome.FAILED_MARK + WHY + "\n"
             "2026-10-12 07:45:02,600 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常: " + WHY
             + " Traceback (most recent call last):\n"
             '  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\src\\task\\DailyTask.py", line 1, in run\n'
             + TAIL)
got = outcome.okww_checks(REAL_1141, expect_nest=False)
bad = [x for x in got if not x.ok]
check("11:41 那种：判没干成", bool(bad))
check("11:41 那种：同一个原因只报一条（周本那项已经说了）", len(bad), 1)
check("11:41 那种：说了停在哪", "没等到结算页" in bad[0].detail if bad else False)

# The shape no other branch catches: dailies done, the additional task raised before the
# weekly book was opened (no 「Teleport to Boss Weekly Challenge」), so origin/main judged
# every item green and the run was booked silently.
ADD_ONLY = ("2026-10-05 10:34:52,359 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常:  "
            "Traceback (most recent call last):\n" + TAIL)
got = outcome.okww_checks(ADD_ONLY, expect_nest=False)
check("只有附加任务出错：判没干成", [x.ok for x in got if x.label == "附加任务出错"], [False])
check("只有附加任务出错：会推送", outcome.summarize(got, "OK-WW") is not None)
check("没写原因就照实说", [x.detail for x in got if x.label == "附加任务出错"], ["日志里只有这一句，没写原因"])

REASON = ("2026-09-21 10:21:00,184 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常: "
          "Teleport to boss failed Traceback (most recent call last):\n" + TAIL)
got = outcome.okww_checks(REASON, expect_nest=False)
check("原因去掉 Traceback 尾巴", [x.detail for x in got if x.label == "附加任务出错"], ["Teleport to boss failed"])

ENDED = ("2026-10-12 07:50:00,000 ERROR TaskExecutor FarmEchoTask:" + outcome.FAILED_MARK
         + "连续 3 次失败，退出本次任务，不再重试\n" + TAIL)
got = outcome.okww_checks(ENDED, expect_nest=False)
check("刷声骸按失败结束（不是周本）：判没干成",
      [(x.ok, x.detail) for x in got if x.label == "这一趟按失败结束"],
      [(False, "连续 3 次失败，退出本次任务，不再重试")])
check("干净的日常早做完：照旧全绿", outcome.summarize(outcome.okww_checks(TAIL, expect_nest=False), "OK-WW"), None)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
