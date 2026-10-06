"""结果核对：出现在日志里 != 做成了。

样本全部取自 2026-08-27 当天的真实日志——那天 OK-WW 连着三轮没打残象聚落、
MaaEnd 卡在弹窗上自己关掉，两边都没报错，而中继报了「全绿」。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.outcome import maa_sanity_short, maaend_checks, okww_checks, patch_effect_checks, summarize

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
             "NightmareNestTask:enter combat None\n"
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
    # An empty read proves the override ran, not that it read the count.
    wk_empty = wk.replace("[本周剩余可收取次数：2/3_1.00, x60_0.79]", "[]")
    check("读到空列表不算痕迹", "周本改动在跑（进本前读剩余次数）" in bad_labels(patch_effect_checks(wk_empty)), True)
    # The real line from 10-01 13:21, the third of the three runs that never got a window.
    bare = ("2026-10-01 13:21:38,841 INFO ok.core.start_controller process:try execute "
            "D:\\Wuthering Waves Game\\Wuthering Waves.exe None with start\n")
    check("鸣潮不带参数拉起＝启动参数改动没跑到",
          "鸣潮启动参数在跑（3.7 起要带启动器同款参数）" in bad_labels(patch_effect_checks(bare)), True)
    check("带了 -krqlv=hd 就过", bad_labels(patch_effect_checks(bare.replace(" None ", " -krqlv=hd "))), [])
    day = ("2026-09-13 09:21:58,916 INFO TaskExecutor NightmareNestTask:opened gray_book_boss\n"
           "2026-09-13 12:45:52,773 INFO TaskExecutor NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n"
           "2026-09-13 09:33:01,760 INFO TaskExecutor TacetTask:info_set current_stamina 239\n")
    # M7 (09-23): get_stamina logs its raw read. 09-13 predates it, so the real day alone
    # must now flag the stamina override; with the M7 line (format from _read_stamina,
    # not a real log line) the day is clean again.
    check("M7 之前的日志没有体力原文＝体力改动没跑", bad_labels(patch_effect_checks(day, tacet_shot_today=True)),
          ["体力读数改动在跑（读字原文进日志）"])
    day += "2026-09-13 09:33:01,700 INFO TaskExecutor TacetTask:体力读字原文（第 1 次）: ['55', '239/240', '+']\n"
    check("巢穴＋顺序都对", bad_labels(patch_effect_checks(day, tacet_shot_today=True)), [])
    check("刷了无音区但没留图", "无音区改动在跑（结算页留图）" in bad_labels(patch_effect_checks(day, tacet_shot_today=False)), True)
    day_old = day.replace("nightmare nest: 只刷 ['落渊南丘']（设置来自母本）", "left_click 已击败残象：0/48")
    check("09-13 09:19 那种：打开了页面却没有「只刷」＝没跑到", "巢穴改动在跑（只刷指定点位）" in bad_labels(patch_effect_checks(day_old)), True)
    wrong_order = "\n".join(day.splitlines()[2:3] + day.splitlines()[0:2]) + "\n"
    check("刷体力在巢穴之前＝顺序改动没生效", "日常改动在跑（附加任务提到刷体力之前）" in bad_labels(patch_effect_checks(wrong_order)), True)

    print("\n[MAA 理智不够没打：2026-09-14 09:02 剿灭真实行]")
    sh = ("[2026-09-14 09:02:17.941][INF][Px14564][Tx21613] asst::FightTimesTaskPlugin::analyze_sanity_remain Current Sanity: 17 , Max Sanity: 210\n"
          '[2026-09-14 09:02:17.941][INF][Px14564][Tx21613] Assistant::append_callback | SubTaskExtraInfo {"class":"asst::FightTimesTaskPlugin","details":{"sanity_cost":25,"series":1,"times_finished":0},"subtask":"FightTimesTask","taskchain":"Fight","taskid":2}\n')
    check("17 < 25 且 0 次 = 理智不够", maa_sanity_short(sh), {"have": 17, "cost": 25})
    check("打了一次就不算", maa_sanity_short(sh.replace('"times_finished":0', '"times_finished":1')), None)
    check("理智够就不算", maa_sanity_short(sh.replace("Current Sanity: 17", "Current Sanity: 90")), None)
    check("没有这些行就不判", maa_sanity_short("TaskChainStart Fight\n"), None)

    print("\n[周本没领奖＝没干成（2026-09-14 09:19 真实行）]")
    wb = ("2026-09-14 10:02:00,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
          "2026-09-14 10:02:15,000 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：3/3_1.00, x60_0.79]\n"
          "2026-09-14 10:02:30,615 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n"
          "2026-09-14 10:02:32,000 INFO TaskExecutor FarmEchoTask:enter combat None\n"
          "2026-09-14 10:04:16,000 INFO TaskExecutor FarmEchoTask:left_click claim_cancel_button_hcenter_vcenter (538, 675) after_sleep 0\n"
          "DailyTask:Daily Task Completed\n"
          "ForgeryTask:used all stamina\n")
    check("打了没领＝红", "周本领到了奖励" in bad_labels(okww_checks(wb, expect_nest=False)), True)
    # 2026-09-21: the key is logged before the book opens; no 「prepared as」 = never got in.
    nowb = wb.replace("2026-09-14 10:02:30,615 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n", "")
    nowb = nowb.replace("2026-09-14 10:02:32,000 INFO TaskExecutor FarmEchoTask:enter combat None\n", "")
    check("没进本不说「打了」", bad_labels(okww_checks(nowb, expect_nest=False)).count("周本"), 1)
    check("触发→痕迹也报", "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(patch_effect_checks(wb)), True)
    ok_line = "2026-09-14 10:04:25,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3\n"
    click = "2026-09-14 10:04:20,000 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
    wb_ok = wb + click + ok_line
    check("回读确认领到＝绿", "周本领到了奖励" not in bad_labels(okww_checks(wb_ok, expect_nest=False)), True)
    check("回读确认领到＝改动有痕迹", bad_labels(patch_effect_checks(wb_ok)), [])
    # The click alone is logged before anything shows the claim landed.
    only_click = okww_checks(wb + click, expect_nest=False)
    check("只有「已点确认」＝不算领到", "周本领到了奖励" in bad_labels(only_click), True)
    check("只有「已点确认」：说没回读",
          [c.detail for c in only_click if c.label == "周本领到了奖励"],
          ["点了确认 1 次、领完没再读次数，没核实领到"])
    check("只有「已点确认」＝改动没做成", "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(patch_effect_checks(wb + click)), True)
    same = wb + click + "2026-09-14 10:04:25,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（3/3），这次没领到\n"
    check("回读次数没变＝红、说没领到",
          [c.detail for c in okww_checks(same, expect_nest=False) if c.label == "周本领到了奖励"],
          ["领完再读次数没变 1 次，没领到"])
    unread = wb + click + "2026-09-14 10:04:25,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读没读到本周剩余次数\n"
    check("回读没读到＝红", "周本领到了奖励" in bad_labels(okww_checks(unread, expect_nest=False)), True)
    # Failure lines of the claim hook are not its trace (they used to match 「周本领奖：」).
    for fail_line in ("周本领奖：这一步没做成 WaitFailedException()",
                      "周本领奖：没认出领奖弹窗，整屏读到 [x60_0.79]"):
        got = patch_effect_checks(wb + f"2026-09-14 10:04:20,000 INFO TaskExecutor FarmEchoTask:{fail_line}\n")
        check(f"失败行不算痕迹：{fail_line[:12]}", "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(got), True)
    wb_cap = wb.replace("3/3_1.00", "0/3_0.99") + "FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过\n"
    check("本周领满＝绿", "周本领到了奖励" not in bad_labels(okww_checks(wb_cap, expect_nest=False)), True)
    # 2026-10-07: a waveplate shortage is a normal state, not an error: green, not in
    # the group, and the check says the reward was not claimed (old and new wording).
    short_label = "周本（结晶波片不足，奖励没领）"
    short_old = wb + "2026-09-14 10:04:20,000 INFO TaskExecutor FarmEchoTask:结晶波片不足，取消并跳过本次周本\n"
    got_old = okww_checks(short_old, expect_nest=False)
    check("波片不足（旧行）＝绿、不进群", (bad_labels(got_old), summarize(got_old, "OK-WW")), ([], None))
    check("波片不足（旧行）＝说奖励没领", [(c.label, c.ok, c.detail) for c in got_old if c.label.startswith("周本")],
          [(short_label, True, "周本奖励没领：结晶波片不足")])
    short_new = short_old + ("2026-09-14 10:04:21,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束："
                             "周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）\n")
    got_new = okww_checks(short_new, expect_nest=False)
    check("波片不足（新行，覆盖层按失败结束）＝绿、不进群", (bad_labels(got_new), summarize(got_new, "OK-WW")), ([], None))
    check("波片不足（新行）＝说奖励没领", [c.label for c in got_new if c.label.startswith("周本")], [short_label])
    got_part = okww_checks(wb_ok + short_new.replace(wb, ""), expect_nest=False)
    check("领到一次后波片不足＝绿、说领到几次",
          [(c.label, c.ok) for c in got_part if c.label.startswith("周本")],
          [("周本（结晶波片不足，奖励没领，这一趟领到了 1 次）", True)])
    check("领到一次后波片不足＝不进群", summarize(got_part, "OK-WW"), None)
    # A genuinely incomplete weekly run still fails and reaches the group: the claim
    # step is absent AND no waveplate shortage explains it.
    check("没进本的周本仍然进群", summarize(okww_checks(nowb, expect_nest=False), "OK-WW") is not None, True)
    # 2026-10-06 true root cause (ticket 1006b item H): line 104 of this log is
    # the changelog pyappify-update prints, which contains 「结晶波片不足」. The
    # substring match of `short` against the whole log hit it and raised a false
    # 「结晶波片不够领奖」 into the group. The fix reads only the TaskExecutor's
    # own lines. The regression uses the evidence-package lines verbatim (do not
    # edit them; fixture okww-1006-weekly-full.log holds lines 104/153/175/176).
    weekly_full = (Path(__file__).resolve().parent / "fixtures"
                   / "okww-1006-weekly-full.log").read_text(encoding="utf-8")
    wfull = okww_checks(weekly_full, expect_nest=False, expect_daily=False, expect_stamina=False)
    check("更新说明里的「结晶波片不足」不再判没干完", "周本领到了奖励" not in bad_labels(wfull), True)
    check("更新说明里的「结晶波片不足」不进群", summarize(wfull, "OK-WW"), None)
    # A real waveplate shortage, constructed (no real sample yet: the 10-06 log above
    # was the changelog false alarm). Lines follow the overlay's click_team_challenge
    # path (okww_files/ark_overrides.tasks.py): its skip line, then the failed mark.
    # It is a normal state now, so it no longer reaches the group.
    real_short = ("2026-10-06 09:21:23,627 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
                  "2026-10-06 09:21:52,194 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：3/3_0.99, x60_0.79]\n"
                  "2026-10-06 09:21:59,000 INFO TaskExecutor FarmEchoTask:波片不足挡住开启挑战，点取消跳过本次周本\n"
                  "2026-10-06 09:22:00,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」），点了取消，这一趟没打\n")
    got_real = okww_checks(real_short, expect_nest=False, expect_daily=False, expect_stamina=False)
    check("真的波片不足不进群", summarize(got_real, "OK-WW"), None)
    check("真的波片不足＝说奖励没领", [(c.label, c.ok) for c in got_real], [(short_label, True)])
    # A changelog or other non-task line carrying the overlay's wording does not count.
    fake = real_short.replace("INFO TaskExecutor FarmEchoTask:波片不足", "INFO MainThread pyappify-update:波片不足")
    check("别的进程行里的波片不足不算", summarize(okww_checks(fake, expect_nest=False, expect_daily=False,
                                                         expect_stamina=False), "OK-WW") is not None, True)
    stop_unknown = wb + "2026-09-14 10:04:21,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本：回读没读到本周剩余次数\n"
    check("不认识的画面停下＝红", "周本领到了奖励" in bad_labels(okww_checks(stop_unknown, expect_nest=False)), True)
    # Any other reason the week's claim was not made still reaches the group.
    check("周本别的原因没领仍进群", summarize(okww_checks(stop_unknown, expect_nest=False), "OK-WW") is not None, True)
    check("周本打了没领（没有波片不足）仍进群", summarize(okww_checks(wb, expect_nest=False), "OK-WW") is not None, True)
    skip_day = nowb.replace("3/3_1.00", "0/3_0.99") + "FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过\n"
    check("0/3 跳过的日子不评判领奖改动（没打就没得领）", bad_labels(patch_effect_checks(skip_day)), [])

    print("\n[进了本没打：2026-10-05 早班真实行（ark-evidence 2026-10-05_wuwa_OK-WW-05-39-25）]")
    # Landed, 「打完了」 20 seconds later, no 「FarmEchoTask:enter combat」 at all.
    oct5 = ("2026-10-05 10:33:22,369 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
            "2026-10-05 10:33:35,438 INFO TaskExecutor FarmEchoTask:left_click boss_proceed (1824, 416) after_sleep 1\n"
            "2026-10-05 10:33:48,793 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n"
            "2026-10-05 10:33:49,173 INFO TaskExecutor FarmEchoTask:start wait in combat\n"
            "2026-10-05 10:33:49,217 INFO TaskExecutor FarmEchoTask:boss_string is []\n"
            "2026-10-05 10:34:08,629 INFO TaskExecutor FarmEchoTask:farm echo walk_find_echo None\n"
            "2026-10-05 10:34:08,702 INFO TaskExecutor FarmEchoTask:周本领奖：打完了，去结晶按 F\n"
            "2026-10-05 10:34:08,702 INFO TaskExecutor FarmEchoTask:start walk_to_treasure\n"
            "2026-10-05 10:34:38,744 INFO TaskExecutor FarmEchoTask:周本领奖：这一步没做成 WaitFailedException()\n"
            "2026-10-05 10:35:53,304 INFO TaskExecutor TacetTask:enter combat None\n")
    got = okww_checks(oct5, expect_nest=False, expect_daily=False, expect_stamina=False)
    check("10-05：说进了本一次没打，不说「打了没领」",
          [(c.label, c.detail) for c in got], [("周本", "进了本，但日志里没有开打的记录：一次没打")])
    check("10-05：别的任务的 enter combat 不算周本开打",
          "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(patch_effect_checks(oct5)), False)

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
