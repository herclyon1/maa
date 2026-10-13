"""After a run, check from the run's own log lines what actually got done.

A task name appearing in a log does not mean the task did its job: a task can
open a screen, fail to find its target and quit without an ERROR line. So each
check here looks for the line a task writes only when it did the work; an item
without it is a failed Check, and summarize() turns failed Checks into the
notification text.
"""
from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from collections import Counter
from dataclasses import dataclass

from ark_relay.core import texts


@dataclass
class Check:
    """One verification result. `ok=False` gets reported."""

    label: str          # plain language, goes straight into the notification
    ok: bool
    detail: str = ""    # why it was judged this way, for troubleshooting
    # "" = a task that did or did not do its job; SETTINGS = the run went by defaults
    # because a new version reset the user's settings (failed, but not 「没干成」);
    # SKIPPED = the task's own schedule says not today (passed, but not 「干成的」).
    kind: str = ""


SETTINGS = "settings"
SKIPPED = "skipped"


# ── OK-WW ──────────────────────────────────────────────────────────
# Lines that mean a nest fight happened. Opening the book, teleporting and reading
# the list (「Box(已击败残象：0/48) is not complete」) do not count. Only the nest
# task's own lines: upstream v3.7.4 never logs click_team_challenge or
# wait_in_team_and_world (BaseWWTask.py:678-683, :1115-1117 have no log call), and
# 「echo captured」 is only a reason stored without a log line (NightmareNestTask.py:74,
# CombatCheck.py:58-61). Those words appeared only in traceback frames of other
# tasks' errors (tests/fixtures/m6-okww/0921-weekly.log:27-28), which booked an
# unreachable nest as fought.
_NEST_ENGAGED = re.compile(r"NightmareNestTask:(?:enter combat|farm echo walk|nightmare nest: combat detected)")
# Printed by our patch when every chosen nest is at its cap (a normal skip).
_NEST_ALL_FULL = "指定点位都已打满，跳过"
# The overrides log the nest filter they applied; every nest entered is clicked
# through its count box:
#   NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）
#   NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2
_NEST_FILTER_LINE = re.compile(r"nightmare nest: 只刷 \[")
_NEST_CLICK = re.compile(r"left_click 已击败残象[：:]\s*\d+/(\d+)")
_NEST_NOT_FOUND = "列表里没找到指定的点位"
# Upstream's line when travel to a nest did not happen (NightmareNestTask
# _travel_to_nest_or_skip), e.g. 「nightmare nest unreachable, skip this run: go_nest:48:18」.
_NEST_UNREACHABLE = re.compile(r"nightmare nest unreachable")
# The overrides' line when find_nest could not be installed at all: no nests this run
# rather than upstream's 「every nest that reads 0」 (ark_overrides.tasks.py, NightmareNestTask.run).
_NEST_FILTER_MISSING = "只刷指定点位的改动没装上，这一轮不刷巢穴"
# The overrides' find_nest when a wanted nest's name was read and its count was not
# (NEST_COUNT_UNREAD there): stopped on that page, with screenshot nest_count_unread.
_NEST_COUNT_UNREAD = "指定点位的名字读到了，计数没读到"
# The overrides' line when find_nest went in adapted to a changed upstream body
# (NEST_ADAPTED there): installed, but not checked against the new body by us.
_NEST_ADAPTED = "只刷指定点位的过滤是按 OK-WW 新版适配装上的"
# Marker that DailyTask finished (printed by upstream itself).
_DAILY_DONE = "Daily Task Completed"
# Stamina is farmed by TacetTask, ForgeryTask or SimulationTask (upstream v3.7.4
# DailyTask.py:117-128; the last two are DomainTask subclasses, and the log prefix is
# the instance's class). Only their own lines count: 「enter combat」 is CombatCheck.py:181
# and 「start walk_to_treasure」 BaseWWTask.py:606, logged by every fighting task, and
# the weekly boss and the nest run before stamina farming.
_STAMINA_TASK = r"(?:TacetTask|ForgeryTask|SimulationTask):"
# A stamina fight happened.
_STAMINA_SPENT = re.compile(_STAMINA_TASK + r"(?:enter combat|start walk_to_treasure)")
# Nothing (more) to farm: TacetTask.py:105 (not_enough_stamina, logged when the total
# is under one run) and DomainTask.py:63 / :106.
_STAMINA_SHORT = re.compile(_STAMINA_TASK + r"(?:used all stamina|not enough stamina)")
# Three revives and upstream stops farming and returns quietly: TacetTask.py:79,
# DomainTask.py:73 (FarmEchoTask's own 「farm 4c: …」 is not stamina farming).
_STAMINA_DIED = re.compile(_STAMINA_TASK + r"farm_(?:tacet|domain): exceeded recovery retries \((\d+)\)")
# A stamina reading. Our get_stamina override logs 「…按没读到处理（-1）…」 and returns -1
# when 数/数 could not be read (okww_files/ark_overrides.tasks.py _read_stamina);
# upstream then compares -1 with one run's cost and says 「used all stamina」 /
# 「not enough stamina」 though nothing was read (TacetTask.py:61-66, DomainTask.py:61-63).
# A real reading is logged by info_set (BaseWWTask.py:422; -1 does not match).
_STAMINA_READ = re.compile(_STAMINA_TASK + r"(?:[^\n]*(按没读到处理（-1）)|info_set current_stamina \d)")
STAMINA_UNREAD_SAY = "体力读不出来，没刷"


# The activity points read after open_daily opens the dailies page. A first reading
# already >= 100 means the dailies were finished before this run started, and OK-WW
# only claims the rewards.
_DAILY_POINTS = re.compile(r"info_set total daily points (\d+)")
_DAILY_POINTS_TARGET = 100

# The overlay's daily-chest lines (okww_files/ark_overrides.tasks.py DAILY_*): every
# chest up to the points is clicked and checked for the claimed tick. A chest not
# claimed is an item undone; so are points under 100, saying only the score
# (docs/NOTIFICATIONS.md, 「⚠️ 这一轮没干完」).
_DAILY_REWARD_POINTS = re.compile(r"活跃奖励：活跃度 (\d+)")
_DAILY_REWARD_FAILED = re.compile(r"活跃奖励没领到：(.+)")
_DAILY_REWARD_OK = "活跃奖励：领完核对通过"
_DAILY_REWARD_UNCHECKED = re.compile(r"活跃奖励：没有核对，(.+)")

# The overlay's battle-pass lines (okww_files/ark_overrides.tasks.py BATTLE_PASS_*).
# A day not claimed is an item undone (docs/NOTIFICATIONS.md, 「⚠️ 这一轮没干完」): the
# day's podcast points are lost if not claimed that day (what the user wants kept, 10-11
# 17:36), and upstream does nothing about a miss - claim_battle_pass logs one ERROR
# 「can not battle pass」, goes back to the world and returns: no screenshot, no retry,
# and the run goes on to 「Daily Task Completed」 (tests/fixtures/okww-DailyTask-v3.7.4.py.txt:210),
# so without this line a miss is a clean run. Upstream's own sentence counts too, for a
# run without the overlay (09-29 09:28 was one such line, unread).
_BATTLE_PASS_OK = "战令：页面打开了，点了领取（等级 "
_BATTLE_PASS_RETRY = "战令：第一次没打开，回大世界再开一次"
_BATTLE_PASS_FAILED = "战令没领到："
_BATTLE_PASS_UNCHECKED = "战令：没有重试，"
_BATTLE_PASS_UPSTREAM_FAILED = "can not battle pass"

# ── weekly boss claims ──
# 「周本领奖：已点确认」 is logged right after the click and proves nothing on its
# own. A claim counts only when the overlay re-reads the game's weekly counter and
# logs one of the three read-back lines (written verbatim by the overlay).
WEEKLY_CLICKED = "周本领奖：已点确认"
WEEKLY_CLAIM_OK = re.compile(r"周本领奖：回读确认领到，本周剩余 (\d+)/3→(\d+)/3")
WEEKLY_CLAIM_SAME = re.compile(r"周本领奖：回读次数没变（(\d+)/3），这次没领到")
WEEKLY_CLAIM_UNREAD = "周本领奖：回读没读到本周剩余次数"
# The pre-entry reading, e.g. 「本周剩余可收取次数：2/3」 inside 周本本周剩余次数原文.
WEEKLY_READ = re.compile(r"本周剩余可收取次数[：:]\s*(\d+)\s*[/／]\s*(\d+)")
# The overlay's end-as-failed mark (okww_files/ark_overrides.tasks.py FAILED_MARK)
# and the line it starts.
FAILED_MARK = "这一趟按失败结束："
_WEEKLY_FAILED = re.compile(FAILED_MARK + r"(.+)")
# The overlay appends what it read off the screen (「整屏读到 [0_1.00, 41/240_1.00, …]」)
# to a stop reason. That OCR dump is for the log; a reason pushed to the phone ends
# before it (audit 2026-10-13 item 14).
_SCREEN_DUMP = re.compile(r"[。，,；;\s]*整屏读到.*$", re.S)


def without_screen_dump(reason: str) -> str:
    """`reason` without the overlay's trailing 「整屏读到 …」 OCR dump."""
    return _SCREEN_DUMP.sub("", reason).strip()
# The overlay's waveplate-shortage skip lines (current and old wording); both
# overlay paths log one before ending the run. Also read by
# collector_okww._okww_steps.
WEEKLY_SHORT = re.compile(r"波片不足挡住开启挑战|结晶波片不足，取消并跳过本次周本")
WEEKLY_SHORT_SAY = "周本奖励没领：结晶波片不足"
# A weekly fight happened. 「teleport_to_boss prepared as」 is only the landing and
# 「周本领奖：打完了」 can be logged without a fight; a real fight logs upstream's
# 「FarmEchoTask:enter combat」, and the claim dialog appears only after a won fight.
_WEEKLY_FOUGHT = re.compile(r"FarmEchoTask:enter combat|周本领奖：认出弹窗|周本领奖：回读确认领到")
# The overlay's line when an additional task (weekly boss, garden, echo merge) raised
# and the daily went on without it (okww_files/ark_overrides.tasks.py open_daily_first):
#   DailyTask:附加任务出错，不拖垮当趟日常: Teleport to boss failed Traceback (most recent call last):
# The exception text can be empty (10-05 10:34:52), and the traceback header shares the line.
_ADDITIONAL_FAILED = re.compile(r"附加任务出错[^:：\n]*[:：][ \t]*(.*)")
_TRACEBACK_TAIL = re.compile(r"\s*Traceback \(most recent call last\):.*$")


# An OK-WW log also holds other loggers' lines (pyappify-update prints its whole
# changelog after an update; MainThread, ok.core.start_controller, RefreshAdb), which
# can contain the words the checks look for. The run checks read only the task
# executor's lines: 「YYYY-MM-DD HH:MM:SS,mmm LEVEL TaskExecutor msg」. A bare
# 「TaskName:msg」 line (no timestamp, no level) is kept too; the tests use that form.
_OKWW_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \w+ (\S+)")


def _task_lines(text: str) -> str:
    """Keep only the task executor's own lines of an OK-WW run log.

    Drops every line of a logger other than TaskExecutor. Idempotent.
    """
    kept = [line for line in text.splitlines()
            if (m := _OKWW_LINE.match(line)) is None or m.group(1) == "TaskExecutor"]
    return "\n".join(kept)


def weekly_claims(text: str) -> dict:
    """Count the weekly claim attempts of one log by what the read-back said.

    verified: the counter dropped. unchanged: it did not. unread: the read-back
    failed. no_readback: a click with no read-back line at all (logs from before
    the read-back existed). attempted: clicks, or read-backs if more.
    """
    verified = len(WEEKLY_CLAIM_OK.findall(text))
    unchanged = len(WEEKLY_CLAIM_SAME.findall(text))
    unread = text.count(WEEKLY_CLAIM_UNREAD)
    clicked = text.count(WEEKLY_CLICKED)
    attempted = max(clicked, verified + unchanged + unread)
    return {"verified": verified, "unchanged": unchanged, "unread": unread,
            "no_readback": attempted - verified - unchanged - unread,
            "attempted": attempted}


def weekly_left(text: str) -> "int | None":
    """Claims left this week: the newest reading of the game's own counter in the log.

    Readings are the pre-entry OCR and the read-back after a claim (its 「after」, or
    the unchanged count). A click without a read-back changes nothing here, so an
    old log keeps its pre-entry number; the 0/3 gate on the next entry catches an
    overshoot. None when the log has no reading at all.
    """
    found = [(m.start(), int(m.group(1))) for m in WEEKLY_READ.finditer(text)]
    found += [(m.start(), int(m.group(2))) for m in WEEKLY_CLAIM_OK.finditer(text)]
    found += [(m.start(), int(m.group(1))) for m in WEEKLY_CLAIM_SAME.finditer(text)]
    if not found:
        return None
    return max(max(found)[1], 0)


def weekly_unverified(c: dict) -> str:
    """The claim attempts that are not a confirmed claim, in words; "" when none."""
    parts = []
    if c["no_readback"]:
        parts.append(f"点了确认 {c['no_readback']} 次、领完没再读次数，没核实领到")
    if c["unchanged"]:
        parts.append(f"领完再读次数没变 {c['unchanged']} 次，没领到")
    if c["unread"]:
        parts.append(f"领完再读没读到剩余次数 {c['unread']} 次，没核实领到")
    return "；".join(parts)


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
# An effect is the line the override writes when it *did its job*, never one of
# its failure lines: an empty read (`周本本周剩余次数原文: []`) or 「周本领奖：这一步没做成」
# prove the code ran, not that it worked.
_PATCH_EFFECTS = (
    ("周本改动在跑（进本前读剩余次数）",
     r"FarmEchoTask:left_click boss_proceed",
     r"周本本周剩余次数原文: .*次数[^0-9]{0,6}\d\s*[/／]\s*3", "周本任务点了「前往」"),
    # Triggered only by a real fight (see _WEEKLY_FOUGHT): a 0/3 or short-on-waveplates
    # skip never reaches the crystal, so it has nothing to claim. Done means the
    # read-back confirmed a claim, or the game said this week is already capped.
    ("周本领奖改动在跑（打完按 F 领奖）",
     r"(?s)Teleport to Boss Weekly Challenge.*FarmEchoTask:enter combat",
     r"周本领奖：回读确认领到|收取物资次数已达到上限", "周本打了一场"),
    ("巢穴改动在跑（只刷指定点位）",
     r"NightmareNestTask:opened gray_book_boss", r"nightmare nest: 只刷 \[", "巢穴任务打开了残象聚落页"),
    ("巢穴进点位留图在跑（点进点位前截图）",
     r"NightmareNestTask:(farm echo walk find true|Captured echo during combat|nightmare nest unreachable)",
     r"nightmare nest: 点进点位", "巢穴任务进了点位"),
    ("巢穴传送不过去留图在跑（传送前后截图）",
     r"NightmareNestTask:nightmare nest unreachable", r"nightmare nest: 传送不过去", "巢穴传送不过去"),
    ("日常改动在跑（附加任务提到刷体力之前）",
     r"NightmareNestTask:opened gray_book_boss", r"TacetTask:info_set current_stamina|ForgeryTask:info_set current_stamina|SimulationTask:info_set current_stamina", "巢穴任务先跑、刷体力后跑"),
    ("刷到空改动在跑（上游不刷时补刷体力）",
     r"DailyTask:info_set current daily progress 180\b", r"上游这趟不刷体力", "日常读到已用 180/180"),
    ("体力读数改动在跑（读字原文进日志）",
     r"(Tacet|Forgery|Simulation)Task:info_set current_stamina", r"体力读字原文", "读了体力"),
    ("无音区分组改动在跑（鸣潮 3.7 新增两个）",
     r"TacetTask:info_set Teleport to Tacet Suppression", r"无音区分组：", "传送去了无音区"),
    ("鸣潮启动参数在跑（3.7 起要带启动器同款参数）",
     r"try execute .*Wuthering Waves\.exe", r"try execute .*Wuthering Waves\.exe .*-krqlv=hd", "OK-WW 打开了鸣潮"),
    # Upstream's own first line of claim_battle_pass, which our copy keeps; the
    # effect is our line after the page opened (its retry included).
    ("战令改动在跑（没打开时同一趟再开一次）",
     r"(?m)DailyTask:battle pass\s*$", r"战令：页面打开了，点了领取", "日常走到了领战令"),
)


# Which override each effect check vouches for. test_okww_overlay_copies refuses
# an @override that is neither here nor in BEHAVIOUR_TESTS - that is the gate
# against 「贴了补丁，实际没运行」 recurring: every binding must come with a way to see it ran.
PATCH_COVERAGE = {
    "FarmEchoTask.click_configured_boss_level": "周本改动在跑（进本前读剩余次数）",
    "FarmEchoTask.incr_drop": "周本领奖改动在跑（打完按 F 领奖）",
    "FarmEchoTask.handle_claim_button": "周本领奖改动在跑（打完按 F 领奖）",
    "NightmareNestTask.find_nest": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.run": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.run_capture_mode": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.get_nest_to_go": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.combat_nest": "巢穴进点位留图在跑（点进点位前截图）",
    "NightmareNestTask._travel_to_nest_or_skip": "巢穴传送不过去留图在跑（传送前后截图）",
    "DailyTask.run": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.open_daily": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.run_additional_tasks": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.claim_daily": "刷到空改动在跑（上游不刷时补刷体力）",
    "TacetTask.use_stamina": "无音区改动在跑（结算页留图）",
    "BaseWWTask.get_stamina": "体力读数改动在跑（读字原文进日志）",
    "TacetTask.teleport_to_tacet": "无音区分组改动在跑（鸣潮 3.7 新增两个）",
    "start_controller.execute": "鸣潮启动参数在跑（3.7 起要带启动器同款参数）",
    "DailyTask.claim_battle_pass": "战令改动在跑（没打开时同一趟再开一次）",
}
# Overrides whose path has no upstream line to check against in a run log (a death
# in the realm, three failed laps, a late teleport screen...). Each is pinned by a
# behaviour test instead: the file named here drives that method with a fake task.
# The gate checks the file exists and names the method.
BEHAVIOUR_TESTS = {
    "FarmEchoTask.combat_once": "test_okww_weekly_entry_paths.py",
    "FarmEchoTask.click_team_challenge": "test_okww_weekly_entry_paths.py",
    "BaseWWTask.click_on_book_target": "test_okww_weekly_entry_paths.py",
    "FarmEchoTask.teleport_to_configured_boss": "test_okww_weekly_entry_paths.py",
    "FarmEchoTask.teleport_to_configured_boss_and_prepare": "test_okww_weekly_entry_paths.py",
    "FarmEchoTask.revive_action": "test_okww_revive_and_retry.py",
    "FarmEchoTask.run": "test_okww_revive_and_retry.py",
    "TacetTask.farm_tacet": "test_okww_farm_hook.py",
    "ForgeryTask.farm_forgery": "test_okww_farm_hook.py",
    "SimulationTask.farm_simulation": "test_okww_farm_hook.py",
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
        out.append(Check(label, ok, "" if ok else f"{what}，但日志里没有我们那句做成了的话：改动没跑到或没做成"))
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
    two different denominators in one run mean two different nests.
    """
    text = _task_lines(text)
    if not (only_nest or "").strip() or "NightmareNestTask" not in text:
        return []
    out: list[Check] = []
    announced = bool(_NEST_FILTER_LINE.search(text))
    denoms = list(dict.fromkeys(_NEST_CLICK.findall(text)))
    if announced:
        why = ""
    else:
        # Say what the log shows: nests entered, or entered and unreachable.
        entered = (f"进了 {len(denoms)} 个点位（计数上限 {'、'.join(denoms)}）" if denoms
                   else "一个点位都没进")
        if denoms and len(_NEST_UNREACHABLE.findall(text)) >= len(denoms):
            entered = f"点了 {len(denoms)} 个点位，都没传送过去，一个都没刷"
        why = f"日志里没有「nightmare nest: 只刷 […]」这一行，只刷{only_nest}的过滤没生效；这一趟{entered}"
    out.append(Check("残象聚落只刷指定点位（过滤生效）", announced, why))
    # One denominator per nest asked for (user 10-12 11:2x: the first two nests);
    # more different ones than names means a nest outside the setting was entered.
    wanted = max(1, len([n for n in re.split(r"[,，]", only_nest) if n.strip()]))
    in_scope = len(denoms) <= wanted
    if len(denoms) <= 1 and not _NEST_ENGAGED.search(text):
        return out      # nothing was fought, so 「没进别的点位」 says nothing worth a green line
    out.append(Check("残象聚落没进别的点位", in_scope,
                     "" if in_scope else f"这一趟进了 {len(denoms)} 个不同的点位（计数上限 {'、'.join(denoms)}），设置是只刷{only_nest}"))
    return out


def daily_reward_checks(text: str) -> list[Check]:
    """The daily activity chests and points, from the overlay's lines (none: nothing said)."""
    out: list[Check] = []
    if failed := _DAILY_REWARD_FAILED.findall(text):
        out.append(Check("每日活跃奖励领到了", False, failed[-1].strip()))
    elif unchecked := _DAILY_REWARD_UNCHECKED.findall(text):
        out.append(Check("每日活跃奖励领到了", False, "领完没有核对：" + unchecked[-1].strip()))
    elif _DAILY_REWARD_OK in text:
        out.append(Check("每日活跃奖励领到了", True, ""))
    if points := _DAILY_REWARD_POINTS.findall(text):
        n = int(points[-1])
        full = n >= _DAILY_POINTS_TARGET
        out.append(Check("每日活跃满 100", full, "" if full else f"今天活跃 {n} 分，没满 100"))
    return out


def battle_pass_checks(text: str) -> list[Check]:
    """The battle-pass claim, from the overlay's lines or upstream's own (none: step not reached).

    Red when the page did not open after the overlay's second try, or when upstream's
    「can not battle pass」 is there (a run without the overlay, or our fallback to
    upstream's body). The overlay logs that sentence too on its final miss, so it is
    read only after the overlay's own lines."""
    if _BATTLE_PASS_FAILED in text:
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_FAILED)]
    if _BATTLE_PASS_UPSTREAM_FAILED in text:
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_UNCLAIMED)]
    if _BATTLE_PASS_OK in text:
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, True,
                      texts.OKWW_BATTLE_PASS_RETRIED if _BATTLE_PASS_RETRY in text else "")]
    if _BATTLE_PASS_UNCHECKED in text:
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, True, texts.OKWW_BATTLE_PASS_UNCHECKED)]
    return []


# nest_state() keys -> the verdict's (label, ok, detail). collector_okww._nest_step
# maps the same keys to the daily report's step text.
_NEST_VERDICT = {
    # Not farming the other nests is right when the filter is gone, but the nest he
    # asked for was not farmed either: that is a failure and goes to the group now.
    # The boot drift line alone can arrive only at the next relay boot (a refused
    # find_nest), i.e. after the run.
    "filter_missing": ("残象聚落", False, "只刷指定点位的补丁没贴上，这一轮没刷巢穴（没去乱刷别的点位）"),
    "not_found": ("残象聚落", False, "配置里的点位名在游戏列表里没找到，请核对配置里的名字和游戏里的写法"),
    "count_unread": ("残象聚落", False, "列表里指定点位的计数没读到，停下没刷（截图 nest_count_unread）"),
    "full": ("残象聚落（已满，跳过）", True, "指定点位都打满了"),
    "fought": ("残象聚落", True, "有进本/战斗记录"),
    "unreachable": ("残象聚落", False, "点了点位，但传送不过去，一次没打"),
    "failed": ("残象聚落", False, "任务中途出错退出，一次没打"),
    "quit": ("残象聚落", False, "任务起来了，但既没打、也没说点位已满——开了界面就原地退出了"),
    "not_run": ("残象聚落", False, "这一轮根本没跑到这个任务"),
}


def nest_state(text: str) -> str:
    """What the nightmare-nest task did in one OK-WW run log, as one key of _NEST_VERDICT.

    The one classifier behind both the run's verdict (okww_checks) and the daily
    report's step (collector_okww._nest_step), so the two cannot disagree. Reads only
    the task executor's lines (_task_lines), whatever text it is given.
    """
    text = _task_lines(text)
    engaged = bool(_NEST_ENGAGED.search(text))
    if _NEST_FILTER_MISSING in text:
        return "filter_missing"
    if _NEST_NOT_FOUND in text:
        return "not_found"
    if _NEST_COUNT_UNREAD in text and not engaged:
        return "count_unread"
    # A fight first, then 「all full」: the run farmed the nest until it was full.
    # That is 「fought」; 「full」 (skipped) is for a run that found it full before
    # fighting at all (audit 2026-10-13 item 11).
    if engaged:
        return "fought"
    if _NEST_ALL_FULL in text:
        return "full"
    if _NEST_UNREACHABLE.search(text):
        return "unreachable"
    if "NightmareNestTask Failed" in text:
        return "failed"
    if "NightmareNestTask" in text:
        return "quit"
    return "not_run"


def stamina_failure(text: str) -> str:
    """Why stamina farming failed in one OK-WW run log, or "" when no known failure.

    Read by okww_checks (the 刷体力 item) and collector_okww._okww_progress (why it
    stopped), so the two say the same. Two failures:
      - upstream gave up after three revives (_STAMINA_DIED);
      - the stamina task stopped right after a reading our override could not make
        (-1), with no stamina fight at all: its 「used all stamina」 / 「not enough
        stamina」 was judged on nothing. A -1 followed by a real reading (TacetTask's
        click and second read, TacetTask.py:63-64) is a real reading.
    """
    text = _task_lines(text)
    if m := _STAMINA_DIED.search(text):
        return f"刷体力时角色死了 {m.group(1)} 次，OK-WW 停止刷体力，体力没刷完"
    if _STAMINA_SPENT.search(text):
        return ""
    reads = list(_STAMINA_READ.finditer(text))
    for stop in _STAMINA_SHORT.finditer(text):
        last = [r for r in reads if r.start() < stop.start()]
        if last and last[-1].group(1):
            return STAMINA_UNREAD_SAY
    return ""


def okww_checks(text: str, *, expect_nest: bool, expect_daily: bool = True,
                expect_stamina: bool = True, only_nest: str = "") -> list[Check]:
    """Verify one OK-WW run. `text` is the full log of that run.

    `expect_nest` comes from the config (a configured 「只刷指定点位」 nest filter or
    the daily echo option enabled means nests should have been farmed).
    `only_nest` is the configured 「Only Farm These Nests」 value; when set, the run
    must show the filter was active and must not have walked into other nests.
    """
    text = _task_lines(text)
    out: list[Check] = []
    out.extend(nest_filter_checks(text, only_nest))

    # Dailies already done before this run: no stamina farming is owed, and the nest
    # is judged only when its task ran. The weekly boss still is: it runs as an
    # additional task either way, and returning here hid the 10-12 11:45 stop of a
    # second run (claim confirmed, no settlement) - nothing was pushed.
    m = _DAILY_POINTS.search(text)
    dailies_done = bool(m and int(m.group(1)) >= _DAILY_POINTS_TARGET)
    if dailies_done:
        done = _DAILY_DONE in text
        out.append(Check("今日日常此前已完成，本轮仅领奖", done,
                         "" if done else "但连领奖收尾都没跑完"))
        expect_daily = expect_stamina = False
        expect_nest = expect_nest and "NightmareNestTask" in text

    if expect_daily:
        done = _DAILY_DONE in text
        out.append(Check("每日任务跑完", done,
                         "" if done else f"日志里没有「{_DAILY_DONE}」"))
    out.extend(daily_reward_checks(text))
    out.extend(battle_pass_checks(text))

    if expect_nest:
        label, ok, why = _NEST_VERDICT[nest_state(text)]
        out.append(Check(label, ok, why))

    # The weekly boss passes only on a confirmed reward claim.
    if "Teleport to Boss Weekly Challenge" in text:
        c = weekly_claims(text)
        capped = "收取物资次数已达到上限" in text or bool(re.search(r"本周剩余可收取次数[：:]\s*0\s*/", text))
        # 「本周周本次数已领满」: the game's own counter read 0/3 before entering.
        # A waveplate shortage is red, an item undone (pushed): the claim of this run
        # was not made, and nothing checks that the week's three are made later. The
        # dialog alone cannot tell a cause that is normal from one that is not (a run
        # minutes after another that farmed, the farm left on, waveplates spent by
        # hand). In the AUTO-MAS history read 10-11 (450 logs, 126 with the weekly
        # boss) the skip line is in 6 runs, all 08-31 18:44 - 09-01 11:01 while runs
        # were repeated minutes apart (current_stamina 8 and 2 read in the same runs),
        # none in a shift since; the 10-06 09:28 「结晶波片不够领奖」 that had it called a
        # normal state on 10-07 was the changelog false match fixed in 12edfb0b, not a
        # shortage. From 10-07 until 10-11 it was green. It is read from the overlay's
        # skip line (WEEKLY_SHORT) and tested before `stopped`, because older logs also
        # carry the failed mark after the skip line. Any other stop is red too.
        stopped = _WEEKLY_FAILED.search(text)
        short = bool(WEEKLY_SHORT.search(text))
        ok_ = (c["verified"] > 0 or capped or "本周周本次数已领满" in text) and not (stopped or short)
        # 「info_set Teleport to Boss Weekly Challenge 0」 is logged before the book
        # is opened (the 0 is the boss's index). Getting in is 「teleport_to_boss
        # prepared as …」 (FarmEchoTask.py:240); fighting is _WEEKLY_FOUGHT.
        entered = "teleport_to_boss prepared as" in text
        fought = bool(_WEEKLY_FOUGHT.search(text))
        if ok_:
            out.append(Check("周本领到了奖励", True, ""))
        elif short:
            label = (f"周本（这一趟领到了 {c['verified']} 次，之后结晶波片不足，剩下的奖励没领）"
                     if c["verified"] else "周本（结晶波片不足，奖励没领）")
            out.append(Check(label, False, WEEKLY_SHORT_SAY))
        elif stopped:
            got = f"（这一趟领到了 {c['verified']} 次）" if c["verified"] else ""
            out.append(Check("周本领到了奖励", False, without_screen_dump(stopped.group(1)) + got))
        elif c["attempted"]:
            out.append(Check("周本领到了奖励", False,
                             weekly_unverified(c)))
        elif not entered:
            why = ("选了等级后没等到「开启挑战」" if re.search(r"找不到开启挑战|都没进开启挑战", text)
                   else "传送去 Boss 没成")
            out.append(Check("周本", False, f"没进本，一次没打：{why}"))
        elif not fought:
            out.append(Check("周本", False, "进了本，但日志里没有开打的记录：一次没打"))
        else:
            out.append(Check("周本领到了奖励", False, "周本打了，但没有领奖那一步：奖励没拿到"))

    if expect_stamina:
        if why := stamina_failure(text):
            out.append(Check("刷体力", False, why))
        elif _STAMINA_SPENT.search(text):
            out.append(Check("刷体力", True, ""))
        elif _STAMINA_SHORT.search(text):
            out.append(Check("刷体力", True, "体力不足，本来就没得刷"))
        else:
            out.append(Check("刷体力", False, "既没进本，也没说体力不足"))

    out.extend(_ended_failed_checks(text, out))
    return out


def _ended_failed_checks(text: str, out: list[Check]) -> list[Check]:
    """A failed Check for every 「这一趟按失败结束：」 or 「附加任务出错」 line that no failed
    Check in `out` already reports.

    Whatever the branches above judged, a run whose log carries either line did not
    get its work done. On 10-12 the 11:41 hand-started run (OK-WW-07-41-07) had the
    dailies already done and a weekly stop, okww_checks returned after the dailies
    item, and the run was booked silently (relay log 11:49:23). This catch-all does
    not depend on any branch reaching its own check. A reason already in a failed
    Check's detail (the weekly block quotes the failed mark; the additional-task line
    repeats the same ArkStopped text) is not listed twice, and neither is a weekly-boss
    reason (the overlay starts those with 「周本」) once the weekly block has a failed
    item: older logs carry the failed mark after the waveplate-shortage line, which the
    weekly block already reports as the shortage.
    """
    found: list[tuple[str, str]] = []
    for m in _WEEKLY_FAILED.finditer(text):
        found.append(("这一趟按失败结束", without_screen_dump(_TRACEBACK_TAIL.sub("", m.group(1)))))
    for m in _ADDITIONAL_FAILED.finditer(text):
        found.append(("附加任务出错", without_screen_dump(_TRACEBACK_TAIL.sub("", m.group(1)))))
    weekly_red = any(c.label.startswith("周本") and not c.ok for c in out)
    extra: list[Check] = []
    for label, why in found:
        if why and any(why in c.detail for c in out + extra if not c.ok):
            continue
        if why.startswith("周本") and weekly_red:
            continue
        if not why and any(c.label == label for c in extra):
            continue
        extra.append(Check(label, False, why or "日志里只有这一句，没写原因"))
    return extra


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
# MaaEnd drops a saved option two ways on load: the key is gone (2026-09-10,
# 「选项 "AutoCollectRoutes" 已不存在，已丢弃保存值」), or the key stayed and its
# type changed, so the saved value is thrown away for the default (2026-10-03
# to 10-10, every launch: 「选项 "AutoStockBuyDailyGoodsValleyIV" 的类型已从
# "checkbox" 变更为 "switch"，已重置为默认值」 - the per-item buy lists in the
# master were replaced by the defaults, and this check stayed green).
_MAAEND_DROPPED = re.compile(r'选项 "([^"]+)" (?:已不存在，已丢弃保存值'
                             r'|的类型已从 "[^"]*" 变更为 "[^"]*"，已重置为默认值)')
# Which task a reset option belongs to, told by its key prefix, and what the user
# loses with it. Only the prefixes with a known owner: AutoStockBuy* are 自动囤货's
# buy lists (test_maaend_migrate_stock_switch, 2026-10-10), AutoCollect* are
# 自动采集's routes (2026-09-10 above). Any other key is counted as 「其他」, not guessed.
_DROPPED_OWNER = (
    ("AutoStockBuy", "自动囤货", "购买", "买"),
    ("AutoCollect", "自动采集", "路线", "走"),
)


def _dropped_checks(dropped: list[str]) -> list[Check]:
    """One failed SETTINGS Check per task whose saved options MaaEnd threw away."""
    groups: dict[tuple[str, str, str], list[str]] = {}
    for key in dropped:
        owner = next(((task, what, verb) for prefix, task, what, verb in _DROPPED_OWNER
                      if key.startswith(prefix)), ("其他", "", "跑"))
        groups.setdefault(owner, []).append(key)
    out = []
    for (task, what, verb), keys in groups.items():
        head = "、".join(keys[:5]) + ("…" if len(keys) > 5 else "")
        out.append(Check(f"{task}的设置", False,
                         f"{len(keys)} 个{what}选项被 MaaEnd 新版本重置成默认值，"
                         f"今天没按你的设置{verb}（{head}）", kind=SETTINGS))
    return out


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


# MaaEnd's own log states how many tasks this run was given:
#   2026-10-01 15:24:25 INFO  [Task] 实例 AUTO-MAS: 开始执行任务, 数量: 16
_MAAEND_SCHEDULED = re.compile(r"开始执行任务, 数量: (\d+)")


def _all_done_no_exit(text: str, own_log: bool) -> bool:
    """Every scheduled task finished, none failed, and no wrap-up line.

    Needs MaaEnd's own log (`own_log`): the wrap-up line and the scheduled count
    live only there, and without it a truncated log would read as 「all done」.
    「All done」 is checked against the scheduled count, not just against the
    tasks that started: a crash between two tasks leaves later ones never begun.
    """
    if not own_log or _MAAEND_DONE in text:
        return False
    counts = [int(n) for n in _MAAEND_SCHEDULED.findall(text)]
    if not counts:
        return False
    started = re.findall(r"任务开始[:：]\s*(\S+)", text)
    finished = re.findall(r"任务完成[:：]\s*(\S+)", text)
    ended = re.findall(r"任务(?:完成|失败)[:：]\s*(\S+)", text)
    return (bool(started) and not (Counter(started) - Counter(ended))
            and not re.search(r"任务失败[:：]", text)
            and len(finished) >= counts[-1])


def maaend_no_self_exit(text: str, own_log: bool = False) -> bool:
    """Every scheduled task finished, none failed, and MaaEnd never wrote its wrap-up line."""
    return _all_done_no_exit(text, own_log)


def maaend_checks(text: str, on_error_names: list[str], own_log: bool = False) -> list[Check]:
    """Verify one MaaEnd run.

    `on_error_names` are the screenshot filenames newly added during that run.
    `own_log`: MaaEnd's own app log is part of `text` (see _all_done_no_exit).
    """
    out: list[Check] = []
    done = _MAAEND_DONE in text
    # No "every 「任务开始」 has its 「任务完成」/「任务失败」" check here any more: AUTO-MAS
    # lists the enabled tasks that never completed and reports the run as
    # 「MaaEnd 部分任务执行失败」 (app/task/MaaEnd/AutoProxy.py, unfinished_tasks), so
    # the run arrives as a failure (hand-over grey item 3, 2026-10-11). What stays
    # below is the evidence AUTO-MAS does not look at.
    # Every task finished and none failed, but MaaEnd never wrote its wrap-up line
    # and never closed itself (2026-10-01 16:58:22; 2026-09-28 11:22:10): the
    # work is done, MaaEnd just did not exit. That is not 「没干完」 - the user read
    # it as tasks left undone. Said separately (all_done_no_exit).
    all_done_no_exit = _all_done_no_exit(text, own_log)
    if all_done_no_exit:
        out.append(Check("任务全部完成（跑完没自己退出）", True))
    else:
        out.append(Check("MaaEnd 跑完", done,
                         "" if done else "日志里没有「自动执行任务完成」"))
    done = done or all_done_no_exit

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
    out += _dropped_checks(dropped) or [Check("新版本认得全部旧设置", True)]
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
                # Not listed as 「干成的」 though: it did nothing today (summarize).
                out.append(Check(key, True, kind=SKIPPED))
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
# MAA prints a pair for every task chain:
#   TaskChainStart  {"taskchain":"Infrast", ...}
#   TaskChainCompleted {"taskchain":"Infrast", ...}
# A chain started and never completed, or ended by Error / Stopped, is a failure.
# Error strings in the log are not counted: harmless ones (`skill has no
# recognition result`, `Unknown task`) appear in normal runs.
_MAA_CHAIN = re.compile(
    r'TaskChain(Start|Completed|Error|Stopped)\b.*?"taskchain":"(\w+)"')


_MAA_STARTUP = re.compile(
    r'TaskChainStart\b.*?"taskchain":"StartUp"')


def _one_run_only(text: str) -> str:
    """Keep only this run: everything from the second StartUp on belongs to the
    next run and is cut off.

    The caller's window is [start, end + 5 minutes], which can reach into a run that
    started right after. Every MAA run begins with StartUp, so the second StartUp
    marks the boundary. With only one StartUp (or none) the text is returned
    unchanged.
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
            # A Stopped receipt for a chain that already completed is not an
            # abort (MAA can log TaskChainStopped CloseDown after
            # TaskChainCompleted CloseDown).
            if kind == "Stopped" and ended[chain] >= started[chain] > 0:
                continue
            ended[chain] += 1
            if kind in ("Error", "Stopped"):
                bad.append(f"{chain}({'报错' if kind == 'Error' else '被中止'})")

    out: list[Check] = []
    if not started:
        # No task chain event at all: the window or the log is wrong; not a pass.
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
    undone = [c for c in bad if c.kind != SETTINGS]
    reset = [c for c in bad if c.kind == SETTINGS]
    lines = []
    if undone:
        lines.append(f"{who} 这一轮有 {len(undone)} 项没干成，但它自己没报错：")
        lines += [_bullet(c) for c in undone]
    if reset:
        # 2026-10-12: six reset buy lists were said as 「有 1 项没干成」; the work was done,
        # by the defaults instead of the user's settings.
        lines.append(f"{who} {_SETTINGS_HEAD}" if not undone else f"另外{_SETTINGS_HEAD}")
        lines += [_bullet(c) for c in reset]
    if skipped := [c.label for c in checks if c.ok and c.kind == SKIPPED]:
        lines.append("按周期今天不跑：" + "、".join(skipped))
    ok = [c.label for c in checks if c.ok and c.kind != SKIPPED]
    if ok:
        lines.append("干成的：" + "、".join(ok))
    return "\n".join(lines)


_SETTINGS_HEAD = texts.OUTCOME_SETTINGS_HEAD


def _bullet(c: Check) -> str:
    return f"· {c.label}：{c.detail}" if c.detail else f"· {c.label}"
