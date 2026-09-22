"""After a run, verify **what actually got done** -- and speak up when it did not.

**Why this exists** (the reckoning of 2026-08-27):

That day OK-WW skipped the nightmare nests three runs in a row, MaaEnd got stuck on
a dialog, treated "failed" as "done" and closed itself, and the AUTO-MAS queue
stopped advancing -- **none of the three reported any error at all**, and the relay
still told the user everything was green. The user's own words:

> 他不报错，他直接把自己关掉了，他不说自己被卡在某个地方，他不提醒，
> 直接把整个队列都给卡死了。

The root cause was in `collector.py`: its criterion at the time was "the task name
appeared in the log" == it ran. **Appearing in the log != having succeeded.** A task
can open a screen, fail to find its target, and quit where it stands without
printing a single ERROR.

So the criterion here is different: **demand evidence, not traces.**
Every item asks "is there evidence this actually happened"; if not it goes into the
"did not get done" list and engine sends a notification, instead of being silently
booked as fine.

Every criterion comes from real measured logs, not guesswork; each one cites its
source.
"""
from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from collections import Counter
from dataclasses import dataclass


@dataclass
class Check:
    """One verification result. `ok=False` gets reported."""

    label: str          # plain language, goes straight into the notification
    ok: bool
    detail: str = ""    # why it was judged this way, for troubleshooting


# ── OK-WW ──────────────────────────────────────────────────────────
# Evidence that combat was actually entered. Opening a screen, teleporting or
# searching for a target do not count -- on 2026-08-27 all three runs got as far as
# `open_boss_book canxiang` and never fought once.
_NEST_ENGAGED = re.compile(r"is not complete|click_team_challenge|"
                           r"wait_in_team_and_world|echo captured")
# Two lines printed by our own patch, used to tell a normal skip from a failure.
_NEST_ALL_FULL = "指定点位都已打满，跳过"
# The overrides log which filter they applied and where it came from; every nest
# the task then enters is clicked through its count box. Real lines, 2026-09-13:
#   NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）
#   NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2
_NEST_FILTER_LINE = re.compile(r"nightmare nest: 只刷 \[")
_NEST_CLICK = re.compile(r"left_click 已击败残象[：:]\s*\d+/(\d+)")
_NEST_NOT_FOUND = "列表里没找到指定的点位"
# Marker that DailyTask finished (printed by upstream itself).
_DAILY_DONE = "Daily Task Completed"
# Evidence that stamina was actually spent vs. an explicit statement that it was not.
_STAMINA_SPENT = re.compile(r"enter combat|walk_to_treasure|used all stamina")
_STAMINA_SHORT = "not enough stamina"


# The activity points read after open_daily opens the dailies page. A first reading
# already >= 100 means the dailies were finished before this run started -- OK-WW
# correctly just claims the rewards and quits without farming anything.
_DAILY_POINTS = re.compile(r"info_set total daily points (\d+)")
_DAILY_POINTS_TARGET = 100


def latest_okww_run_log(history_dir) -> "tuple[Path, str] | None":
    """(path, text) of the newest OK-WW run log AUTO-MAS kept, looking back a week. None when there is none."""
    hist = Path(history_dir)
    if not hist.is_dir():
        return None
    days = sorted((d for d in hist.iterdir() if d.is_dir()), reverse=True)[:7]
    logs = [f for d in days for f in d.rglob("OK-WW-*.log")]
    if not logs:
        return None
    newest = max(logs, key=lambda f: f.stat().st_mtime)
    return newest, newest.read_text(encoding="utf-8", errors="replace")


# Each OK-WW override leaves a sentence in the log when its code path runs. A
# check fires only when the upstream *trigger* for that path is in the log and
# our sentence is not - "bound" is not "did its job" (nest filter, 09-10..09-13).
# (label, trigger regex, effect regex, what the trigger means)
_PATCH_EFFECTS = (
    ("周本改动在跑（进本前读剩余次数）",
     r"FarmEchoTask:left_click boss_proceed", r"周本本周剩余次数原文", "周本任务点了「前往」"),
    ("周本领奖改动在跑（打完按 F 领奖）",
     r"FarmEchoTask:info_set Teleport to Boss Weekly Challenge", r"周本领奖：", "跑了周本"),
    ("巢穴改动在跑（只刷指定点位）",
     r"NightmareNestTask:opened gray_book_boss", r"nightmare nest: 只刷 \[", "巢穴任务打开了残象聚落页"),
    ("日常改动在跑（附加任务提到刷体力之前）",
     r"NightmareNestTask:opened gray_book_boss", r"TacetTask:info_set current_stamina|ForgeryTask:info_set current_stamina|SimulationTask:info_set current_stamina", "巢穴任务先跑、刷体力后跑"),
    ("体力读数改动在跑（读字原文进日志）",
     r"(Tacet|Forgery|Simulation)Task:info_set current_stamina", r"体力读字原文", "读了体力"),
)


# Which override each effect check vouches for, and the overrides that have no
# trigger to check against yet (each with the reason). test_okww_overlay_copies
# refuses a new @override that is in neither list - that is the gate against
# 「贴了补丁，实际没运行」 recurring: every binding must come with a way to see it ran.
PATCH_COVERAGE = {
    "FarmEchoTask.click_configured_boss_level": "周本改动在跑（进本前读剩余次数）",
    "FarmEchoTask.incr_drop": "周本领奖改动在跑（打完按 F 领奖）",
    "NightmareNestTask.find_nest": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.run": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.get_nest_to_go": "巢穴改动在跑（只刷指定点位）",
    "DailyTask.run": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.open_daily": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.run_additional_tasks": "日常改动在跑（附加任务提到刷体力之前）",
    "TacetTask.use_stamina": "无音区改动在跑（结算页留图）",
    "BaseWWTask.get_stamina": "体力读数改动在跑（读字原文进日志）",
}
PATCH_NO_TRIGGER = {
    "FarmEchoTask.revive_action": "only when a character dies inside a realm during an echo farm",
    "FarmEchoTask.combat_once": "only after such a revive",
    "FarmEchoTask.run": "only after three failed laps in a row",
    "FarmEchoTask.click_team_challenge": "only when the weekly boss shows 开启挑战 with too few 波片",
    "BaseWWTask.click_on_book_target": "only for a 限时提前开放 boss",
    "FarmEchoTask.teleport_to_configured_boss": "only when the teleport screen is late",
    "FarmEchoTask.teleport_to_configured_boss_and_prepare": "only for a 限时提前开放 boss",
    "TacetTask.farm_tacet": "silent wrapper: drops daily=/used_stamina= so the farm runs to empty; visible only via 波片 0 in the report",
    "ForgeryTask.farm_forgery": "same as farm_tacet",
    "SimulationTask.farm_simulation": "same as farm_tacet",
}


def patch_effect_checks(text: str, tacet_shot_today: bool | None = None) -> list[Check]:
    """Did each override actually run where its trigger appeared? Empty entries for paths not triggered."""
    out: list[Check] = []
    for label, trig, effect, what in _PATCH_EFFECTS:
        if not re.search(trig, text):
            continue
        if label.startswith("日常改动"):
            t = re.search(trig, text); e = re.search(effect, text)
            ok = bool(t and e and t.start() < e.start())
            out.append(Check(label, ok, "" if ok else f"{what}——日志里刷体力出现在巢穴之前，或根本没有一方"))
            continue
        ok = bool(re.search(effect, text))
        out.append(Check(label, ok, "" if ok else f"{what}，但日志里没有我们那句话：改动没跑到"))
    if tacet_shot_today is not None and re.search(r"TacetTask:info_set current_stamina", text):
        out.append(Check("无音区改动在跑（结算页留图）", tacet_shot_today,
                         "" if tacet_shot_today else "今天刷了无音区，screenshots 里却没有今天的 tacet_drops 图"))
    return out


# MAA's FightTimesTaskPlugin announces the sanity it read and the stage cost before
# each attempt. Real lines, 2026-09-14 09:02 (annihilation, Monday re-arm):
#   asst::FightTimesTaskPlugin::analyze_sanity_remain Current Sanity: 17 , Max Sanity: 210
#   SubTaskExtraInfo {"class":"asst::FightTimesTaskPlugin","details":{"sanity_cost":25,"series":1,"times_finished":0}
_MAA_SANITY = re.compile(r"analyze_sanity_remain Current Sanity: (\d+) , Max Sanity: (\d+)")
_MAA_COST = re.compile(r'"sanity_cost":(\d+),"series":\d+,"times_finished":(\d+)')


def maa_sanity_short(text: str) -> "dict | None":
    """{'have': 17, 'cost': 25} when the Fight chain never ran because sanity was below the cost; else None."""
    have = [int(m.group(1)) for m in _MAA_SANITY.finditer(text)]
    costs = [(int(m.group(1)), int(m.group(2))) for m in _MAA_COST.finditer(text)]
    if not have or not costs:
        return None
    cost, done = costs[-1]
    if done == 0 and have[-1] < cost:
        return {"have": have[-1], "cost": cost}
    return None


def nest_filter_checks(text: str, only_nest: str) -> list[Check]:
    """Did the run honour 「only these nests」? Empty when no filter is configured.

    Two facts, both from lines the run itself writes: the overrides announce the
    filter they loaded (no announcement = the filter code never had a name to work
    with), and each nest entered is clicked through its 「已击败残象 N/D」 box, so
    two different denominators in one run mean two different nests. 2026-09-10 to
    09-13 every morning clicked 0/41, 0/48, 0/48, 0/24 - all four nests - while the
    master said 落渊南丘 only, and nothing noticed for four days.
    """
    if not (only_nest or "").strip() or "NightmareNestTask" not in text:
        return []
    out: list[Check] = []
    announced = bool(_NEST_FILTER_LINE.search(text))
    out.append(Check("残象聚落只刷指定点位（过滤生效）", announced,
                     "" if announced else "日志里没有「nightmare nest: 只刷 […]」这一行：过滤没拿到点位名，按上游行为刷了全部"))
    denoms = list(dict.fromkeys(_NEST_CLICK.findall(text)))
    one_site = len(denoms) <= 1
    out.append(Check("残象聚落没进别的点位", one_site,
                     "" if one_site else f"这一趟进了 {len(denoms)} 个不同的点位（计数上限 {'、'.join(denoms)}），设置是只刷{only_nest}"))
    return out


def okww_checks(text: str, *, expect_nest: bool, expect_daily: bool = True,
                expect_stamina: bool = True, only_nest: str = "") -> list[Check]:
    """Verify one OK-WW run. `text` is the full log of that run.

    `expect_nest` comes from the config (a configured 「只刷指定点位」 nest filter or
    the daily echo option enabled means nests should have been farmed).
    `only_nest` is the configured 「Only Farm These Nests」 value; when set, the run
    must show the filter was active and must not have walked into other nests.
    """
    out: list[Check] = []
    out.extend(nest_filter_checks(text, only_nest))

    # The false alarm of 2026-08-27 13:24: on that day's second run the dailies were
    # long since finished, so OK-WW just claimed the rewards and quit -- entirely
    # correct, yet this code reported the nests and the stamina farming as failures.
    # "there was nothing to do in the first place" and "it should have been done and
    # was not" must be kept apart.
    m = _DAILY_POINTS.search(text)
    if m and int(m.group(1)) >= _DAILY_POINTS_TARGET:
        done = _DAILY_DONE in text
        out.append(Check("今日日常此前已完成，本轮仅领奖", done,
                         "" if done else "但连领奖收尾都没跑完"))
        return out

    if expect_daily:
        done = _DAILY_DONE in text
        out.append(Check("每日任务跑完", done,
                         "" if done else f"日志里没有「{_DAILY_DONE}」"))

    if expect_nest:
        if _NEST_NOT_FOUND in text:
            out.append(Check("残象聚落", False,
                             "配置里的点位名在游戏列表里没找到，请核对配置里的名字和游戏里的写法"))
        elif _NEST_ALL_FULL in text:
            out.append(Check("残象聚落（已满，跳过）", True, "指定点位都打满了"))
        elif _NEST_ENGAGED.search(text):
            out.append(Check("残象聚落", True, "有进本/战斗记录"))
        elif "NightmareNestTask" in text:
            out.append(Check("残象聚落", False,
                             "任务起来了，但既没打、也没说点位已满——"
                             "开了界面就原地退出了"))
        else:
            out.append(Check("残象聚落", False, "这一轮根本没跑到这个任务"))

    # The weekly boss is only worth running for its reward. 2026-09-14: fought
    # twice, ESC'd the claim dialog twice, and the day read 全绿.
    if "Teleport to Boss Weekly Challenge" in text:
        claimed = "周本领奖：已点确认" in text
        capped = "收取物资次数已达到上限" in text or bool(re.search(r"本周剩余可收取次数[：:]\s*0\s*/", text))
        skipped = "结晶波片不足，取消并跳过本次周本" in text or "本周周本次数已领满" in text
        ok_ = claimed or capped or skipped
        out.append(Check("周本领到了奖励", ok_, "" if ok_ else "周本打了，但没有领奖那一步：奖励没拿到"))

    if expect_stamina:
        if _STAMINA_SHORT in text and not _STAMINA_SPENT.search(text):
            out.append(Check("刷体力", True, "体力不足，本来就没得刷"))
        elif _STAMINA_SPENT.search(text):
            out.append(Check("刷体力", True, ""))
        else:
            out.append(Check("刷体力", False, "既没进本，也没说体力不足"))

    return out


# ── MaaEnd ─────────────────────────────────────────────────────────
# A failed universal jump saves an on_error screenshot. During the 2026-08-27 dialog
# hang it saved three of them in 20 minutes, while MaaEnd itself reported not one
# ERROR.
# MaaEnd's completion marker. **It is written to MaaEnd's own app log**
# (`<maaend>/debug/YYYY-MM-DD-N.log`: `INFO [App] 自动执行任务完成，关闭自身`),
# not to the AUTO-MAS history log. On 2026-08-29 only the latter was fed in, so this
# check was always false and falsely reported "MaaEnd did not finish" every day.
# The fix was the data source, not the criterion.
_MAAEND_DONE = "自动执行任务完成"
_MAAEND_STUCK = re.compile(r"SceneAnyEnterWorld|PipelineTask bad next")
# MaaEnd's own app log, on loading a config written for an older version:
#   WARN  [Config] 选项 "AutoCollectRoutes" 已不存在，已丢弃保存值
_MAAEND_DROPPED = re.compile(r'选项 "([^"]+)" 已不存在，已丢弃保存值')
# What a task leaves in the AUTO-MAS log when it actually does its job. The
# task name is matched as a substring of the 「任务开始」 line (it carries an
# emoji prefix). Wording from real logs: routes 2026-09-01, essence and
# protocol 2026-08-25.
_MAAEND_WORK = (
    ("自动采集", re.compile(r"路线\d+[：:]"), "走了路线"),
    ("基质刷取", re.compile(r"已完成一次基质刷取|理智不足"), "刷了"),
    ("协议空间", re.compile(r"进入协议空间成功|理智不足"), "进了"),
)
_MAAEND_SKIPPED = re.compile(r"根据执行周期跳过")
_MAAEND_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def _maaend_segments(text: str):
    """(task name, its lines, seconds it took) for every 「任务开始」…「任务完成」 pair."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if m := re.search(r"任务开始[:：]\s*(\S.+?)\s*$", line):
            start = (i, m.group(1).strip())
            continue
        if start is None:
            continue
        if m := re.search(r"任务(?:完成|失败)[:：]\s*(\S.+?)\s*$", line):
            if m.group(1).strip() != start[1]:
                continue
            seg = "\n".join(lines[start[0]:i + 1])
            secs = 0
            t0, t1 = _MAAEND_TS.match(lines[start[0]]), _MAAEND_TS.match(line)
            if t0 and t1:
                fmt = "%Y-%m-%d %H:%M:%S"
                secs = int((datetime.strptime(t1.group(1), fmt)
                            - datetime.strptime(t0.group(1), fmt)).total_seconds())
            yield start[1], seg, secs
            start = None


def maaend_checks(text: str, on_error_names: list[str]) -> list[Check]:
    """Verify one MaaEnd run.

    `on_error_names` are the screenshot filenames newly added during that run.
    """
    out: list[Check] = []
    done = _MAAEND_DONE in text
    out.append(Check("MaaEnd 跑完", done,
                     "" if done else "日志里没有「自动执行任务完成」"))

    # An additional structural criterion: every 「任务开始」 should have a matching
    # 「任务完成」/「任务失败」. It does not depend on any single fixed phrase, so if the
    # completion marker gets renamed again this still catches the problem.
    started = re.findall(r"任务开始[:：]\s*(\S+)", text)
    ended = re.findall(r"任务(?:完成|失败)[:：]\s*(\S+)", text)
    dangling = Counter(started) - Counter(ended)
    if started:
        out.append(Check("每个任务都收了尾", not dangling,
                         "" if not dangling else
                         "开了没收尾：" + "、".join(sorted(dangling))))

    # A failed universal jump (SceneAnyEnterWorld / PipelineTask bad next) always
    # counts as a fault -- 2026-08-27 was exactly the "stuck on a dialog, reports no
    # error itself, only the screenshots catch it" case, so this must not be relaxed.
    # Screenshots from other nodes are different: MaaEnd retries, and a successful
    # retry completes the task as normal. The 2026-08-29 morning run saved 6
    # ScenePrivateMapZoomOut shots while both the environment survey and the essence
    # farming reported 「任务完成」 -- calling that a failure is a false alarm. So a
    # fault is only declared when the run **really did not finish**; otherwise the
    # screenshots are listed honestly but not counted as a fault.
    # 2026-09-10: MaaEnd v2.28.0-beta.5 renamed 自动采集's route options. The
    # master config still carried the old keys, MaaEnd dropped them on load
    # (「選項 "AutoCollectRoutes" 已不存在，已丢弃保存值」), the scheduler found
    # nothing to walk, wrote 「任务完成」 after 38 seconds, AUTO-MAS said Success,
    # and the daily report said 全绿. Every check above passed, because every
    # check above only asks whether the run *ended*, not whether it *did*
    # anything. The user's words for why this is worse than a false red: 「明明没有完成任务，却按照完成任务的通知去报」.
    # So each farming/collecting task must show the trace it leaves when it
    # really works, and a new version discarding settings is itself a fault.
    dropped = sorted(set(_MAAEND_DROPPED.findall(text)))
    if dropped:
        head = "、".join(dropped[:5]) + ("…" if len(dropped) > 5 else "")
        out.append(Check("新版本认得全部旧设置", False,
                         f"MaaEnd 新版本不认 {len(dropped)} 项旧设置，这些项按默认值跑了：{head}"))
    else:
        out.append(Check("新版本认得全部旧设置", True))
    for name, seg, secs in _maaend_segments(text):
        for key, evidence, what in _MAAEND_WORK:
            if key not in name:
                continue
            if evidence.search(seg):
                out.append(Check(f"{key} 真的{what}", True))
            elif _MAAEND_SKIPPED.search(seg):
                # The task itself said it was not due today (weekday schedule);
                # a quick completion is then the right outcome, not a false green.
                # The real line from 2026-09-11 10:01 is in test_maaend_false_green.
                out.append(Check(f"{key} 真的{what}", True))
            else:
                out.append(Check(f"{key} 真的{what}", False,
                                 f"{key} {secs} 秒就报「任务完成」，日志里没有{what}的痕迹"))

    stuck = [n for n in on_error_names if _MAAEND_STUCK.search(n)]
    if stuck:
        out.append(Check("界面没卡住", False,
                         f"万能跳转失败 {len(stuck)} 次，存了截图："
                         + "、".join(stuck[:3])))
    elif on_error_names and not done:
        out.append(Check("界面没卡住", False,
                         f"有 {len(on_error_names)} 张出错截图："
                         + "、".join(on_error_names[:3])))
    elif on_error_names:
        out.append(Check(f"出错截图 {len(on_error_names)} 张（已重试恢复）", True))
    else:
        out.append(Check("界面没卡住", True))
    return out


# ── MAA ────────────────────────────────────────────────────────────
# Before 2026-08-30 there was **nothing here**: `_verify_outcome` reached MAA and
# simply returned None (= everything succeeded), so MAA was permanently green as
# long as the process exited normally.
#
# The first version judged by "how many times an error string appears", and a dry
# run against real logs immediately proved it wrong: **both** the 08-29 evening and
# the 08-30 morning runs would have been pushed, and what they pushed was
# `skill has no recognition result` and `Unknown task` -- two lines already confirmed
# to be harmless noise. Replacing "always green" with "two false alarms per run" is
# worse than before: cry wolf often enough and nobody looks on the day it is real.
#
# So the criterion became structural: MAA prints a pair for every task chain
#   TaskChainStart  {"taskchain":"Infrast", ...}
#   TaskChainCompleted {"taskchain":"Infrast", ...}
# Measured across both runs: one pair each of StartUp/Fight/Infrast/Recruit/Mall/
# Award/CloseDown, zero Error, zero Stopped, zero dangling. **Started but never
# closed out** is the real failure -- that is exactly the shape of "the queue is
# wedged and the script says nothing".
_MAA_CHAIN = re.compile(
    r'TaskChain(Start|Completed|Error|Stopped)\b.*?"taskchain":"(\w+)"')


_MAA_STARTUP = re.compile(
    r'TaskChainStart\b.*?"taskchain":"StartUp"')


def _one_run_only(text: str) -> str:
    """Keep only this run. Everything after the second StartUp belongs to the next
    run and is cut off.

    The time window is [start, end + 5 minutes], those 5 minutes being slack for the
    closing lines. When two runs sit close together the slack reaches into the next
    one: on the evening of 2026-08-31 the first run went 21:30:50 -> 21:33:38 (window
    out to 21:38:38) while the second started at 21:33:43, with `Infrast` starting
    21:35 and completing 21:43 -- so the first run's window picked up the next run's
    "Infrast started" but could not reach its "completed", and reported a dangling
    Infrast. Infrastructure had in fact finished fine; a pure false alarm.

    Every MAA run begins with StartUp, so the second StartUp marks the boundary.
    With only one StartUp (or none) the text is returned unchanged.
    """
    hits = list(_MAA_STARTUP.finditer(text))
    if len(hits) < 2:
        return text
    cut = text.rfind("\n", 0, hits[1].start())
    return text[:cut] if cut > 0 else text


def maa_checks(text: str) -> list[Check]:
    """Verify one MAA run. `text` is the asst.log within that run's time window."""
    text = _one_run_only(text)
    started: Counter = Counter()
    ended: Counter = Counter()
    bad: list[str] = []
    for kind, chain in _MAA_CHAIN.findall(text):
        if kind == "Start":
            started[chain] += 1
        else:
            # A stop receipt for a chain that already completed is not an
            # abort: 2026-09-22 21:47:10.864 "TaskChainCompleted CloseDown" +
            # "AllTasksCompleted", then 0.5 s later "TaskChainStopped CloseDown"
            # (asst.log in report_09-22_21-47-18_part01.zip) - the game had
            # already been closed and the report said "被中止".
            if kind == "Stopped" and ended[chain] >= started[chain] > 0:
                continue
            ended[chain] += 1
            if kind in ("Error", "Stopped"):
                bad.append(f"{chain}({'报错' if kind == 'Error' else '被中止'})")

    out: list[Check] = []
    if not started:
        # Not a single task chain event = the window was cut wrong or the log is the
        # wrong one. This must never be treated as "no problem".
        out.append(Check("MAA 的日志里有这一轮的记录", False,
                         "MAA 自己的日志里没有这一轮开始的记录，核对不了"))
        return out

    dangling = started - ended
    out.append(Check("每一项都做到了结尾", not dangling,
                     "" if not dangling else
                     "开了没收尾：" + "、".join(sorted(dangling))))
    out.append(Check("没有哪一项报错或被中止", not bad,
                     "" if not bad else "、".join(sorted(set(bad)))))
    return out


def summarize(checks: list[Check], who: str) -> str | None:
    """Return a plain-language paragraph if anything failed; None if all succeeded."""
    bad = [c for c in checks if not c.ok]
    if not bad:
        return None
    lines = [f"{who} 这一轮有 {len(bad)} 项没干成，但它自己没报错："]
    lines += [f"· {c.label}：{c.detail}" if c.detail else f"· {c.label}"
              for c in bad]
    ok = [c.label for c in checks if c.ok]
    if ok:
        lines.append("干成的：" + "、".join(ok))
    return "\n".join(lines)
