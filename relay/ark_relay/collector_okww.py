"""Read an OK-WW (Wuthering Waves) run log: stamina, runs, steps, failures.

Split out of collector.py on 2026-09-08 (moved verbatim), the largest of the
three seams. OK-WW is a pure image-recognition combat script: it never reads a
reward screen, so nothing here recovers drops. What it does instead has no
counterpart in the other two parsers -- reading the structured state OK-WW
publishes through `info_set`, digging the real cause out of its triple
traceback, and turning a task class name plus an exception name into one
plain-language Chinese sentence for the notification.

The three lookup tables `_OKWW_TASK_ZH` / `_OKWW_EXC_ZH` / `_OKWW_MSG_ZH` are
runtime data, not documentation: `tests/test_texts_gate.py` checks their
wording word for word.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from . import wuwa_forgery, wuwa_tacet


# OK-WW is the third shape. It never reads the reward screen, so there is no
# drop list to recover - it is a pure image-recognition combat script and the
# only numbers it ever knows are its own. What it *does* publish, through
# ok-script's `info_set` (which logs every call), is enough for a useful line:
# how much stamina went in, how many domain entries that bought, and where the
# daily quest ended up. Asked for on 2026-08-25 with "虽然它没有掉落物的显示，
# 但只能说够用了".
_OKWW_STAMINA = re.compile(r"info_set current_stamina (\d+)")
# The green reserve value. get_stamina() has always stored two separate
# fields; we only used one of them.
_OKWW_BACKUP = re.compile(r"info_set back_up_stamina (\d+)")
# The real remainder at the end: OK-WW prints this line itself when it stops.
# `info_set current_stamina` is recorded **before each round**, so taking the
# last one as "remaining" always overcounts by one round -- on 2026-08-28 it
# actually farmed down to 0 while the report said 「剩余波片 80/240」, and the
# user pointed out the misreport on the spot. The per-run cost also switches
# between 40 and 80 on its own, so deriving it from outside is unreliable too;
# only the number OK-WW reports itself is accepted.
# 2026-09-04: this regex used to hardcode the second half
# `not enough to continue` as well, but OK-WW has a second wrap-up wording --
# recorded that day as
# `current stamina: 37 must_use completed, no need to use back_up`.
# Failing to match cost that day's report the entire last run: the truth was
# 236 -> 37 (199 spent, 37 left) and it was reported as 「消耗 159、剩余 77」.
# So only the first half is matched, and whatever follows is fine.
_OKWW_STAMINA_END = re.compile(r"current stamina:\s*(\d+)")
_OKWW_DAILY = re.compile(r"info_set current daily progress (\d+)")
_OKWW_POINTS = re.compile(r"info_set total daily points (\d+)")
# One of these is logged per domain entry, so counting them counts the runs.
_OKWW_ENTRY = re.compile(r"使用单倍体力|当前体力大于等于双倍|使用双倍")
# Real Nightmare Nest progress. The user, 2026-08-29: 「能不能给一下残像聚落的
# 真实刷取结果，xx/41 这种」("can you give the real farming result for the
# Nightmare Nests, something like xx/41"). The log prints a line
# `已击败残象：N/M` every time the compendium is opened; take the last one.
# WARNING: this number comes from OCR and a leading digit can be swallowed
# (10/41 read as 0/41), so it is for reference only -- never draw the "did it
# actually farm anything" conclusion from it; that is what nest_cleared is for.
_OKWW_NEST = re.compile(r"已击败残象[：:]\s*(\d+)\s*/\s*(\d+)")
_OKWW_NEST_FULL = re.compile(r"指定点位都已打满")
_OKWW_DAILY_TARGET = 180
# The full value of the in-game daily activity meter. It can go above this
# (the weekly garden and others keep adding), so the cap must be reported
# alongside it, or 「活跃度 110」looks like an error.
_OKWW_POINTS_TARGET = 100

_OKWW_FORGERY_INDEX = re.compile(r"info_set Teleport to Forgery Challenge (\d+)")
# The Simulation Challenge target: one of three in OK-WW's SimulationTask
# source; the translations come from its own ok.po
_OKWW_SIM_TARGET = re.compile(r"info_set Target Simulation Challenge (.+?)\s*$", re.M)
_SIM_ZH = {"Shell Credit": "贝币", "Resonator EXP": "共鸣者经验", "Weapon EXP": "武器经验"}
# At full difficulty (Union Level >= 70 / SOL3 tier 8) the Shell Credit
# Simulation Challenge gives 84,000 Shell Credits per run for 40 waveplates
# (game8 / fandom data, 2026-09; the user's Union Level has long been maxed and
# he fights the level 90 weekly boss). Double = 80 waveplates for two lots.
# The user, 2026-09-02: 「产出必须显示出来，不许标游戏未显示数量」("the yield
# must be shown; do not label it as a quantity the game did not display").
_SIM_REWARD_PER_RUN = {"贝币": 84000}
_OKWW_DOUBLE = re.compile(r"当前体力大于等于双倍|使用双倍")
_OKWW_SINGLE = re.compile(r"使用单倍体力")
_OKWW_TACET_INDEX = re.compile(r"info_set Teleport to Tacet Suppression (\d+)")


def _okww_farm(text: str, info: dict | None = None) -> "tuple[str, str]":
    """(the domain farmed, the yield category). OK-WW never reads the reward
    screen, so the yield can only be stated as a category.
    """
    info = info if info is not None else okww_info(text)
    if "SimulationTask:" in text:
        hits = _OKWW_SIM_TARGET.findall(text)
        tgt = _SIM_ZH.get(hits[-1].strip(), hits[-1].strip()) if hits else ""
        return (f"模拟领域·{tgt}" if tgt else "模拟领域", tgt or "模拟领域奖励")
    if "ForgeryTask:" in text:
        hits = _OKWW_FORGERY_INDEX.findall(text)
        idx = int(hits[-1]) + 1 if hits else 0
        return (_forgery_label(text), wuwa_forgery.reward(idx))
    if "TacetTask:" in text:
        # Wording like 「无音区 #2 / 声骸与角色突破材料」means nothing to a
        # reader (user, 2026-09-06). Look the index up in wuwa_tacet's table
        # and write the name plus the two sets it always drops; when it is not
        # registered, say so outright.
        # For the index, prefer what upstream reports itself -- "which one it
        # actually teleported to" (info_set, counting from 0) -- and only fall
        # back to scraping it out of the prompt text. The config says "which one
        # do we want to farm"; what is needed here is "which one was actually
        # farmed" -- and the two possibly differing is exactly what the user was
        # uneasy about on 2026-09-07.
        got = (info.get("fields") or {}).get("Teleport to Tacet Suppression")
        hits = _OKWW_TACET_INDEX.findall(text)
        if got is None and not hits:
            return ("无音区（日志里没有序号）", "声骸（无音区序号没读到，套装不明）")
        idx = (int(got) if got is not None else int(hits[-1])) + 1
        return (wuwa_tacet.label(idx), wuwa_tacet.reward(idx))
    return ("", "")


def _forgery_label(text: str) -> str:
    """Which instance follows 「凝素领域」. When it cannot be identified, only
    the index is stated.

    The index in the log counts from 0 (`Teleport to Forgery Challenge 0`);
    the lookup table counts from 1 (matching the game's F2 list). **The
    conversion happens only here**, and callers always get plain language.
    """
    hits = _OKWW_FORGERY_INDEX.findall(text)
    if not hits:
        return "凝素领域"          # The step list reads 「做了 凝素领域 ×5」; do not stuff brackets in
    return wuwa_forgery.label(int(hits[-1]) + 1)


_OKWW_GAME_ERR = "waiting for game to start error"
_OKWW_ACTIVITY = re.compile(r" INFO TaskExecutor \w+:")
_OKWW_TB_HEAD = re.compile(r" ERROR TaskExecutor (\w+):(.*?) Traceback \(most recent call last\):")
_OKWW_EXC_LINE = re.compile(r"^\s*([\w.]*(?:Exception|Error)\w*)\b(.*)$", re.M)


def _okww_got_in(text: str) -> bool:
    """Whether any task executor was still working after the last
    "cannot get the game window". If so, it got in later on.
    """
    i = text.rfind(_OKWW_GAME_ERR)
    return bool(_OKWW_ACTIVITY.search(text, i if i >= 0 else 0))


# Notifications may contain plain language only (user, 2026-09-07:
# 「你写进通知的任何东西都要是人话」-- "anything you put in a notification has
# to be plain language"). Task class names, exception names and raw log text
# stay in the log; here they are translated into Chinese. (The original note
# added "and when it cannot be translated it just says 「这一步出错」"; see
# _okww_say -- that catch-all was later removed on purpose.)
_OKWW_TASK_ZH = {
    "DailyTask": "日常清单", "FarmEchoTask": "周本", "TacetTask": "无音区",
    "NightmareNestTask": "残象聚落", "GardenTask": "周常乐园", "DomainTask": "模拟领域",
    "FarmWorldBossTask": "世界 Boss", "CombatCheck": "战斗", "BaseCombatTask": "战斗",
    "TaskExecutor": "任务执行", "AutoCombatTask": "战斗",
}
_OKWW_EXC_ZH = {
    "WaitFailedException": "等一个画面没等到", "CannotFindException": "画面上找不到要点的东西",
    "NotInCombatException": "没有进入战斗", "CharDeadException": "角色倒下了",
    "TimeoutError": "超时", "TaskDisabledException": "任务被关掉了",
}
_OKWW_MSG_ZH = (
    ("farm 4c error", "打完 Boss 领完奖之后没能退出副本"),
    ("can't find gray_book_boss", "按 F2 打不开图鉴，多半是键位改过了"),
    ("NightmareNestTask Failed", "打了但没打成"),
    ("Logger.error() got an unexpected keyword", "旧版补丁自己的日志调用写错（已撤回）"),
    ("can not battle pass", "打不过，可能已经结束"),
    ("Game window is not connected", "连不上游戏窗口"),
    ("not in combat", "没有进入战斗"),
    ("can't find boss_proceed", "图鉴里找不到「前往」按钮"),
    # The outermost of the three tracebacks OK-WW prints for one failure: it only
    # says the daily list stopped, and the reason is in the innermost one. Seen on
    # 2026-09-08 21:50 as 「📅 Daily Task exception stopped」 with exception name
    # `Exception`, which no table entry matched, so the notification could only say
    # it did not recognise it. `Exception` itself is deliberately left untranslated:
    # a bare exception name carries no meaning, and mapping it would silence every
    # other genuinely unknown failure that happens to be raised as one.
    ("Daily Task exception stopped", "日常清单整个停了（真正的原因是上面那条）"),
)
_OKWW_WAIT_SEC = re.compile(r"wait_until timeout .*? (\d+(?:\.\d+)?) seconds")
_ASCII_LETTER = re.compile(r"[A-Za-z]")
_OKWW_ANY_ERR = re.compile(r" ERROR TaskExecutor (\w+):(.*)")
_OKWW_UNTRANSLATED: set = set()


_OKWW_INFO = re.compile(r" INFO TaskExecutor (\w+):info_set (.+)$", re.M)
_OKWW_INFO_NUM = ("current_stamina", "back_up_stamina", "current daily progress",
                  "total daily points", "Teleport to Tacet Suppression",
                  "Teleport to Boss Weekly Challenge")
# Keys whose value contains spaces: the rest of the line is the value, so it
# must not be split on the last space
_OKWW_INFO_REST = ("Chars", "Revive", "Target Simulation Challenge")


def okww_info(text: str, until: int | None = None) -> dict:
    """The structured state OK-WW writes itself (`info_set key value`), taking
    the last occurrence of each key.

    This is **the state upstream reports itself**, not something guessed out of
    prose: `current task` is the step it believes it is on, `错误` is the
    failure reason it decided on, and `Teleport to Tacet Suppression` is which
    Tacet Suppression it **actually** teleported to (counting from 0).
    Before 2026-09-08 all of this was scraped out of the prompt text with
    regexes, which broke the moment upstream reworded anything.

    Returns {"fields": {key: value}, "tasks": [current task in order of
    appearance], "error": the reason, or empty}.
    """
    fields: dict = {}
    tasks: list[str] = []
    error = ""
    for m in _OKWW_INFO.finditer(text):
        if until is not None and m.start() >= until:
            break           # Only the state before this point
        body = m.group(2).strip()
        if body.startswith("current task"):
            what = body[len("current task"):].strip()
            if what and not what.startswith(("wait main", "in main")):
                tasks.append(what)
            continue
        if body == "错误" or body.startswith("错误 "):
            error = body[len("错误"):].strip()
            continue
        key, _, value = body.rpartition(" ")
        for whole in _OKWW_INFO_REST:
            if body.startswith(whole + " "):
                key, value = whole, body[len(whole) + 1:]
                break
        if not key:
            continue
        if key in _OKWW_INFO_NUM:
            try:
                fields[key] = int(value)
            except ValueError:
                continue
        else:
            fields[key] = value
    return {"fields": fields, "tasks": tasks, "error": error}


def _okww_error(text: str) -> str:
    """The real reason for the failure, in plain language. Taken from the
    innermost task's section of the last traceback cluster.

    When OK-WW raises, it prints three tracebacks in a row (the task itself,
    DailyTask.run_task_by_class, and TaskExecutor's
    「Daily Task exception stopped」); all three describe the same event, and the
    innermost one carries the explanation (such as
    「farm 4c error, try handle monthly card」). Before 2026-09-07 the daily
    report only carried AUTO-MAS's 「流程产生错误，请检查游戏状态」, which does
    not say which step it was.
    """
    info = okww_info(text)
    heads = list(_OKWW_TB_HEAD.finditer(text))
    if not heads:
        # No traceback, but upstream said 「错误 …」itself: write what it said
        if info["error"] and info["tasks"]:
            step = info["tasks"][-1].split()[0]
            return _okww_say(_OKWW_TASK_BY_STEP.get(step, step), info["error"], "")
        return ""
    last = heads[-1]
    cluster = [m for m in heads if last.start() - m.start() < 6000]
    inner = [m for m in cluster if m.group(1) not in ("DailyTask", "TaskExecutor")]
    head = (inner or cluster)[0]
    task, msg = head.group(1), head.group(2).strip()
    nxt = heads[heads.index(head) + 1].start() if heads.index(head) + 1 < len(heads) else len(text)
    excs = _OKWW_EXC_LINE.findall(text[head.end():nxt])
    exc = excs[-1][0].rsplit(".", 1)[-1] if excs else ""
    # The current task upstream recorded itself is more reliable than the
    # wrapper layer's class name: `run_task_by_class <class …>` only says who
    # called it, while `current task` says which step is being done.
    if task in ("DailyTask", "TaskExecutor"):
        before_tasks = okww_info(text, until=head.start())["tasks"]
        if before_tasks:
            task = _OKWW_TASK_BY_STEP.get(before_tasks[-1].split()[0], task)
    if task in ("DailyTask", "TaskExecutor"):
        # Raised by the wrapper layer itself (such as
        # 「NightmareNestTask Failed」or 「run_task_by_class <class …>」): the real
        # task name is in that sentence, and the real reason is in the ERROR
        # line before it
        if m := re.search(r"<class '[\w.]*\.(\w+)'>", msg):
            task = m.group(1)
        elif m := re.match(r"(\w+Task) Failed", msg):
            task = m.group(1)
        before = text[max(0, head.start() - 1500):head.start()]
        prior = [m for m in _OKWW_ANY_ERR.finditer(before)
                 if m.group(1) not in ("DailyTask", "TaskExecutor", "CombatCheck", "BaseCombatTask")]
        if prior:
            task, msg = prior[-1].group(1), prior[-1].group(2).strip()
    # A vague description is banned even harder than English (user,
    # 2026-09-07: 「描述模糊是第一大禁止」-- "vague descriptions are the number
    # one prohibition"). So there is no 「这一步出错」catch-all here: if it can
    # be translated, say something specific; if it cannot, say outright that
    # 「中继还不认识这条错」and put the raw text in the log, pending a
    # translation -- saying clearly that we do not know is not fobbing him off.
    return _okww_say(task, msg, exc, text, head.start())


_OKWW_TASK_BY_STEP = {
    "garden_start_game": "GardenTask", "garden": "GardenTask",
    "check": "GardenTask", "claim": "DailyTask", "farm": "FarmEchoTask",
    "tacet": "TacetTask", "nest": "NightmareNestTask",
}


def _okww_say(task: str, msg: str, exc: str, text: str = "", at: int = 0) -> str:
    """Turn (task, raw message, exception name) into one plain-language
    sentence. When it cannot be translated, say so outright -- never be vague.
    """
    task_zh = _OKWW_TASK_ZH.get(task)
    msg_zh = next((zh for en, zh in _OKWW_MSG_ZH if en in msg), "")
    exc_zh = _OKWW_EXC_ZH.get(exc)
    if task_zh is None or not (msg_zh or exc_zh):
        sig = (task, exc, msg[:80])
        if sig not in _OKWW_UNTRANSLATED:      # Warn once per process for the same raw message
            _OKWW_UNTRANSLATED.add(sig)
            logging.getLogger("ark.collector").warning(
                "OK-WW 报错中继还没有翻译，通知里只能说不认识：任务 %s，异常 %s，原文「%s」",
                task, exc or "（没抓到异常名）", msg)
        who = task_zh or "某个任务"
        # **Copy the raw text into the notification**; do not only say
        # 「已记进日志」("recorded in the log"). Hit on 2026-09-08: OK-WW failed
        # three times in a row on the morning shift, the notification said the
        # raw text was in the log -- and the machine powers off as soon as the
        # morning shift ends, so the log is out of reach until the 21:20 boot.
        # The moment someone reads the alert and wants to know what happened is
        # exactly the moment the log is least reachable. The raw text is
        # English, but one line of English he can read beats not knowing what
        # happened; banning English exists so he can understand, not so that he
        # has nothing to look at.
        raw = " ".join((msg or "").split())[:110] or exc or "（连原文都没抓到）"
        return f"{who}：中继还不认识这条错，原文照抄——「{raw}」"
    what = msg_zh or exc_zh
    # The 「wait_until timeout … N seconds」line right before the traceback says
    # how long it waited
    before = text[max(0, at - 600):at] if text else ""
    if (w := _OKWW_WAIT_SEC.findall(before)) and "等" in what:
        sec = w[-1][:-2] if w[-1].endswith(".0") else w[-1]
        what += f"（等了 {sec} 秒）"
    return f"{task_zh}：{what}"


def parse_okww_log(log_path: Path) -> dict:
    """Recover stamina spend / entry count / daily progress from an OK-WW log.

    Stamina is summed from the *drops* between consecutive readings rather than
    from first-minus-last: the reserve tops the bar back up mid-run, and a
    naive subtraction reads that refill as if it had never been spent.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    out: dict = {}
    readings, entries = _okww_stamina_fields(text, out)
    _okww_health(text, out, entries)
    _okww_farm_fields(text, out)
    _okww_stamina_left(text, out, readings)
    _okww_progress(text, out)
    if steps := _okww_steps(text, entries):
        out["okww_steps"] = steps
    return out


def _okww_stamina_fields(text: str, out: dict) -> "tuple[list[int], int]":
    """Waveplates spent, domain entries, reserve stamina. Returns
    (the series of readings, the entry count) for the checks that follow.
    """
    readings = [int(m.group(1)) for m in _OKWW_STAMINA.finditer(text)]
    # The wrap-up line 「current stamina: 8 not enough to continue」is the last
    # reading; leaving it out loses the final run's cost (recorded 2026-09-02:
    # 168 -> 88 -> 8 came out as only 80).
    tail = [int(x) for x in _OKWW_STAMINA_END.findall(text)]
    series = readings + tail[-1:]
    spent = sum(a - b for a, b in zip(series, series[1:]) if a > b)
    if spent:
        out["okww_stamina_spent"] = spent
    entries = len(_OKWW_ENTRY.findall(text))
    if entries:
        out["okww_runs"] = entries
    if back := _OKWW_BACKUP.findall(text):
        out["okww_backup_stamina"] = int(back[-1])
        backs = [int(x) for x in back]
        if used := sum(a - b for a, b in zip(backs, backs[1:]) if a > b):
            out["okww_backup_spent"] = used
    return readings, entries


def _okww_health(text: str, out: dict, entries: int) -> None:
    """Whether it got into the game, and the real reason for a failure."""
    # Never got into the game: the window wait errored, not a single run
    # started, **and nothing else was done afterwards**. On a major version
    # update day the Kuro launcher sits on the 「更新」button and OK-WW just
    # waits for the game window (recorded 2026-09-02 09:18).
    # The "nothing else was done afterwards" clause was added 2026-09-07: that
    # day all three rounds opened with
    # 「waiting for game to start error … is not connected」(a transient window
    # connection error that cleared a few seconds later), then ran for 41
    # minutes, fell over on the weekly boss settlement screen and never started
    # a Tacet Suppression run -- so all of them were judged "cannot get into
    # the game (server maintenance / client waiting to update)". The user: the
    # classification mechanism is broken.
    if "waiting for game to start error" in text and not entries and not _okww_got_in(text):
        out["okww_unreachable"] = True
    if err := _okww_error(text):
        out["okww_error"] = err


def _okww_farm_fields(text: str, out: dict) -> None:
    """Which domain was farmed, how many single and double runs, and the yield
    estimated at full difficulty.
    """
    info = okww_info(text)
    if info["fields"] or info["tasks"]:
        out["okww_info"] = info["fields"]
    farm, reward = _okww_farm(text, info)
    if farm:
        out["okww_farm"] = farm
        out["okww_farm_reward"] = reward
        double = len(_OKWW_DOUBLE.findall(text))
        single = len(_OKWW_SINGLE.findall(text))
        if double:
            out["okww_runs_double"] = double
        if single:
            out["okww_runs_single"] = single
        if (per := _SIM_REWARD_PER_RUN.get(reward)) and (double or single):
            out["okww_farm_drops"] = {reward: per * (2 * double + single)}


def _okww_stamina_left(text: str, out: dict, readings: list) -> None:
    if end := _OKWW_STAMINA_END.findall(text):
        out["okww_stamina_left"] = int(end[-1])
        out["okww_stamina_left_exact"] = True
    elif readings:
        # Only when the wrap-up line was not caught does it fall back to the
        # pre-run reading, flagged as not being the final remainder.
        out["okww_stamina_left"] = readings[-1]
        out["okww_stamina_left_exact"] = False


def _okww_progress(text: str, out: dict) -> None:
    """Nightmare Nests, daily progress, daily points, and why it stopped."""
    if nest := _OKWW_NEST.findall(text):
        out["okww_nest"] = f"{nest[-1][0]}/{nest[-1][1]}"
    if _OKWW_NEST_FULL.search(text):
        out["okww_nest_full"] = True
    if daily := _OKWW_DAILY.findall(text):
        out["okww_daily"] = f"{max(int(x) for x in daily)}/{_OKWW_DAILY_TARGET}"
    if points := _OKWW_POINTS.findall(text):
        top = max(int(x) for x in points)
        out["okww_points"] = f"{top}/{_OKWW_POINTS_TARGET}"
        if top >= _OKWW_POINTS_TARGET:
            out["okww_points"] += "（已满）"
        # The very first activity reading already >= the target means the
        # dailies were finished before this round started (the second run of
        # the day). Farming nothing this round is **correct behaviour**; both
        # the rendering and the result check downstream need this flag, so that
        # "nothing to do" is not judged as "failed to do it".
        if int(points[0]) >= _OKWW_POINTS_TARGET:
            out["okww_daily_done_at_start"] = True
    # Why it stopped, in its own words. "used all stamina" is the good ending.
    if "used all stamina" in text:
        # "Used up" is wrong: OK-WW's `used all stamina` means **what is left
        # is not enough for another run** (a Forgery Challenge run costs 40, so
        # 37 left cannot get in), not that 0 is left. The user called this out
        # on 2026-08-29: 「用尽不是零吗？还剩 20 多」("doesn't used up mean
        # zero? there are still 20-odd left").
        out["okww_stopped"] = "体力不够再开一局"
    elif "not enough stamina" in text:
        out["okww_stopped"] = "体力不够，一局都没开成"


def _okww_steps(text: str, entries: int) -> list[str]:
    """The step list in the daily report's 「备注」, each item marked with its
    own success or failure.
    """
    # Only report what carries information: collecting mail, the radio and the
    # daily reward happen every round and are pure noise in a report.
    # The operator, 2026-08-25: 「除了周常乐园、刷取的关卡、残像聚落之外也别写
    # 上去了」("apart from the weekly garden, the stage farmed and the
    # Nightmare Nests, do not list anything else either").
    # Appearing in the log != having succeeded. A Forgery Challenge may never
    # have been entered for want of stamina, and a Nightmare task may have
    # raised an exception that DailyTask swallowed -- writing either of those
    # up as "done" would be a lie. So each item is marked with its own outcome.
    steps = []
    for needle, name in (
        ("ForgeryTask:", _forgery_label(text)),
        ("TacetTask:", "无音区"),
        ("SimulationTask:", "模拟领域"),
    ):
        if needle not in text:
            continue
        if entries:
            steps.append(f"{name} ×{entries}")
        else:
            steps.append(f"{name}（未进本）")
    if "NightmareNestTask:" in text:
        nest = "残象聚落" if "canxiang" in text else "梦魇巢穴"
        # Appearing in the log != having fought. On 2026-08-27 three rounds in
        # a row reached `open_boss_book canxiang` without a single fight, while
        # this still wrote 「残象聚落」-- so the daily report came out all green.
        # The criterion is now "did it actually enter", and "skipped because
        # full" is stated separately from "location not found".
        if "NightmareNestTask Failed" in text:
            steps.append(f"{nest}（失败）")
        elif "列表里没找到指定的点位" in text:
            steps.append(f"{nest}（点位名对不上，一次没打）")
        elif "指定点位都已打满" in text:
            # 「跳过」("skipped") is find_nest's internal wording and must not
            # leak into a report a person reads: hitting the cap means it is
            # **done**, not that it did nothing.
            steps.append(f"{nest}（已刷满）")
        elif re.search(r"is not complete|click_team_challenge|echo captured", text):
            steps.append(nest)
        else:
            steps.append(f"{nest}（开了界面就退出，一次没打）")
    # The weekly boss (Sonata Reverb): it was not in this list at all, so the
    # "record it when done, reset on Monday" bookkeeping was never triggered by
    # a record (on 2026-09-07 all three rewards were claimed and the books
    # still said 「本周还没领满」).
    if "Teleport to Boss Weekly Challenge" in text:
        claims = text.count("周本领奖：已点确认")
        left = [int(m) for m in re.findall(r"本周剩余可收取次数[：:]\s*(\d+)\s*/", text)]
        if "farm 4c error" in text:
            steps.append(f"周本（领了 {claims} 次，然后没能退出副本）" if claims
                         else "周本（没做完，原因见失败于）")
        elif "收取物资次数已达到上限" in text or (left and left[-1] == 0 and not claims):
            steps.append("周本（已完成，本周已领满）")
        elif claims:
            remain = max((left[-1] if left else claims) - claims, 0)
            steps.append(f"周本（已完成，领了 {claims} 次，本周还剩 {remain} 次）")
        else:
            steps.append("周本（打了，没领到奖励）")
    if "weekly garden already completed" in text:
        steps.append("周常乐园（本周已完成）")
    elif "GardenTask:" in text:
        steps.append("周常乐园")
    if "check discarded echo" in text:
        steps.append("声骸五合一")
    return steps
