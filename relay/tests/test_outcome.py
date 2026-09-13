"""结果核对：出现在日志里 != 做成了。

样本全部取自 2026-08-27 当天的真实日志——那天 OK-WW 连着三轮没打残象聚落、
MaaEnd 卡在弹窗上自己关掉，两边都没报错，而中继报了「全绿」。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.outcome import maaend_checks, okww_checks, patch_effect_checks, summarize

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def bad_labels(checks):
    return sorted(c.label for c in checks if not c.ok)


def main() -> int:
    print("[三轮真实日志：任务起来了但一场没打]")
    # 11:13 那轮：找到了任务、开了界面，然后原地退出
    text = ("NightmareNestTask:opened gray_book_boss\n"
            "NightmareNestTask:open_boss_book canxiang\n"
            "DailyTask:Daily Task Completed\n"
            "ForgeryTask:not enough stamina\n")
    got = okww_checks(text, expect_nest=True)
    check("残象聚落被判为没干成", "残象聚落" in bad_labels(got), True)
    check("每日任务算跑完", "每日任务跑完" not in bad_labels(got), True)
    check("体力不足不算故障", "刷体力" not in bad_labels(got), True)

    print("\n[配置里的点位名对不上——这是故障，不是「已满」]")
    text2 = ("NightmareNestTask:nightmare nest: 列表里没找到指定的点位 ['落渊南丘']\n"
             "DailyTask:Daily Task Completed\n"
             "ForgeryTask:enter combat None\n")
    got2 = okww_checks(text2, expect_nest=True)
    check("点位找不到算故障", "残象聚落" in bad_labels(got2), True)
    check("说清是名字对不上，让人去核对（不写「多半」）",
          any("核对配置里的名字" in c.detail and "多半" not in c.detail for c in got2 if not c.ok), True)

    print("\n[真的打了——这才算干成]")
    text3 = ("NightmareNestTask:open_boss_book canxiang\n"
             "Box(name='已击败残象：0/41', x=890, y=373) is not complete\n"
             "DailyTask:Daily Task Completed\n"
             "ForgeryTask:enter combat None\n")
    got3 = okww_checks(text3, expect_nest=True)
    check("有战斗证据就算干成", bad_labels(got3), [])
    check("全都干成时不报警", summarize(got3, "OK-WW"), None)

    print("\n[点位已打满：正常，不该报警]")
    text4 = ("NightmareNestTask:nightmare nest: 指定点位都已打满，跳过\n"
             "DailyTask:Daily Task Completed\n"
             "ForgeryTask:used all stamina\n")
    got4 = okww_checks(text4, expect_nest=True)
    check("已满不算故障", bad_labels(got4), [])

    print("\n[没配残象聚落时不该凭空要求它]")
    got5 = okww_checks("DailyTask:Daily Task Completed\nenter combat None\n",
                       expect_nest=False)
    check("不检查没配置的项", bad_labels(got5), [])

    print("\n[MaaEnd 卡弹窗：自己不报错，靠 on_error 截图抓出来]")
    mtext = "2026-08-27 09:51:24 INFO [App] 自动执行任务完成，关闭自身\n"
    shots = ["2026.08.27-09.44.59.746_SceneAnyEnterWorld.png",
             "2026.08.27-09.51.23.972_SceneAnyEnterWorld.png"]
    mgot = maaend_checks(mtext, shots)
    check("「跑完了」不等于「没卡住」", "界面没卡住" in bad_labels(mgot), True)
    check("跑完这一项仍算通过", "MaaEnd 跑完" not in bad_labels(mgot), True)
    msg = summarize(mgot, "MaaEnd")
    check("会给出人话告警", msg is not None and "没干成" in msg, True)
    check("告警里带上截图名", "SceneAnyEnterWorld" in (msg or ""), True)

    print("\n[MaaEnd 干净跑完]")
    check("没有截图就不报警", summarize(maaend_checks(mtext, []), "MaaEnd"), None)

    # ── 2026-08-27 13:24 的误报：日常早已完成的第二轮，不许再报「没干成」──
    text6 = ("DailyTask:info_set current daily progress 0\n"
             "DailyTask:info_set total daily points 110\n"
             "DailyTask:info_set current task claim daily\n"
             "DailyTask:Daily Task Completed\n")
    got6 = okww_checks(text6, expect_nest=True)
    check("开始时已完成→不报警", summarize(got6, "OK-WW"), None)
    check("开始时已完成→只有一条「仅领奖」",
          [c.label for c in got6], ["今日日常此前已完成，本轮仅领奖"])
    # 已完成但连领奖收尾都没跑完——这个才要报
    got7 = okww_checks("DailyTask:info_set total daily points 110\n",
                       expect_nest=True)
    check("已完成但没收尾→要报", summarize(got7, "OK-WW") is not None, True)
    # 正常早班：开始时 90 分未满，照常核对
    text8 = ("DailyTask:info_set total daily points 90\n"
             "NightmareNestTask:open_boss_book canxiang\n"
             "DailyTask:Daily Task Completed\n"
             "ForgeryTask:not enough stamina\n")
    got8 = okww_checks(text8, expect_nest=True)
    check("未满时照常核对（巢穴没打要报）",
          any(c.label == "残象聚落" and not c.ok for c in got8), True)

    print("\n[每条改动：触发了就得有它那句话（2026-09-07 周本、09-13 巢穴真实行）]")
    wk = ("2026-09-07 10:06:33,670 INFO TaskExecutor FarmEchoTask:left_click boss_proceed (1824, 416) after_sleep 1\n"
          "2026-09-07 10:06:35,359 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：2/3_1.00, x60_0.79]\n")
    check("周本触发且有痕迹", bad_labels(patch_effect_checks(wk)), [])
    wk_bad = wk.splitlines()[0] + "\n"
    check("周本触发但没痕迹＝改动没跑到", "周本改动在跑（进本前读剩余次数）" in bad_labels(patch_effect_checks(wk_bad)), True)
    check("没触发就不评判", patch_effect_checks("DailyTask:Daily Task Completed\n"), [])
    day = ("2026-09-13 09:21:58,916 INFO TaskExecutor NightmareNestTask:opened gray_book_boss\n"
           "2026-09-13 12:45:52,773 INFO TaskExecutor NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n"
           "2026-09-13 09:33:01,760 INFO TaskExecutor TacetTask:info_set current_stamina 239\n")
    check("巢穴＋顺序都对", bad_labels(patch_effect_checks(day, tacet_shot_today=True)), [])
    check("刷了无音区但没留图", "无音区改动在跑（结算页留图）" in bad_labels(patch_effect_checks(day, tacet_shot_today=False)), True)
    day_old = day.replace("nightmare nest: 只刷 ['落渊南丘']（设置来自母本）", "left_click 已击败残象：0/48")
    check("09-13 09:19 那种：打开了页面却没有「只刷」＝没跑到", "巢穴改动在跑（只刷指定点位）" in bad_labels(patch_effect_checks(day_old)), True)
    wrong_order = "\n".join(day.splitlines()[2:3] + day.splitlines()[0:2]) + "\n"
    check("刷体力在巢穴之前＝顺序改动没生效", "日常改动在跑（附加任务提到刷体力之前）" in bad_labels(patch_effect_checks(wrong_order)), True)

    print("\n[只刷落渊南丘：2026-09-13 真实日志——四个点位全进了，四天没人发现]")
    # Verbatim from history/2026-09-13/wuwa/OK-WW-05-19-22.log (nest lines only).
    text5 = ("2026-09-13 09:22:07,105 INFO TaskExecutor NightmareNestTask:Box(name='已击败残象：0/41', x=889, y=373, width=195, height=30, confidence=100) is not complete\n"
             "2026-09-13 09:22:07,306 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2\n"
             "2026-09-13 09:24:38,554 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/48 (1729, 567) after_sleep 2\n"
             "2026-09-13 09:26:59,672 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/48 (1729, 722) after_sleep 2\n"
             "2026-09-13 09:30:25,602 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/24 (1729, 868) after_sleep 2\n"
             "2026-09-13 09:31:27,063 INFO TaskExecutor NightmareNestTask:nightmare nest: combat detected after pickup\n"
             "DailyTask:Daily Task Completed\n"
             "ForgeryTask:used all stamina\n")
    got5 = okww_checks(text5, expect_nest=True, only_nest="落渊南丘")
    check("没有「只刷」那一行 = 过滤没生效", "残象聚落只刷指定点位（过滤生效）" in bad_labels(got5), True)
    check("三种计数上限 = 进了别的点位", "残象聚落没进别的点位" in bad_labels(got5), True)
    check("细节点名 41、48、24", any("41、48、24" in c.detail for c in got5 if not c.ok), True)
    check("旧判据仍把它当「有战斗记录」——所以以前是绿的", "残象聚落" not in bad_labels(got5), True)

    print("\n[只刷落渊南丘：2026-09-09 09:21 真实日志——只进了 0/41，正确]")
    text6 = ("NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n"
             "2026-09-09 09:21:24 NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2\n"
             "2026-09-09 09:22:21 NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2\n"
             "2026-09-09 09:26:01 NightmareNestTask:nightmare nest: 指定点位都已打满，跳过\n"
             "DailyTask:Daily Task Completed\n"
             "ForgeryTask:used all stamina\n")
    got6 = okww_checks(text6, expect_nest=True, only_nest="落渊南丘")
    check("过滤生效且只进一个点位", bad_labels(got6), [])
    check("没配过滤就不加这两条", [c.label for c in okww_checks(text6, expect_nest=True) if "指定点位" in c.label or "别的点位" in c.label], [])

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
