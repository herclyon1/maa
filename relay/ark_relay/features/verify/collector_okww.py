"""Read an OK-WW (Wuthering Waves) run log: stamina, runs, steps, failures.

OK-WW never reads a reward screen, so there are no drops to recover. This reads
the state OK-WW logs through `info_set`, finds the failure cause in its
tracebacks, and turns a task class name plus an exception name into one Chinese
sentence for the notification.

The lookup tables `_OKWW_TASK_ZH` / `_OKWW_EXC_ZH` / `_OKWW_MSG_ZH` are runtime
data: `tests/test_texts_gate.py` checks their wording.
"""
from __future__ import annotations

import bisect
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from ark_relay.features.verify import outcome
from ark_relay.features.weekly import weeklyboss
from ark_relay.core import wuwa_forgery, wuwa_tacet

# The module logger, so tests can capture it as <module>.log (scripts/mac/lib/loggernames.py).
log = logging.getLogger("ark.collector")


# Stamina reading, logged by `info_set` before each run.
_OKWW_STAMINA = re.compile(r"info_set current_stamina (\d+)")
# The reserve (green) stamina reading.
_OKWW_BACKUP = re.compile(r"info_set back_up_stamina (\d+)")
# OK-WW's own remainder line when it stops; two wordings follow the number
# (「not enough to continue」, 「must_use completed, no need to use back_up」), so
# only the first half is matched.
_OKWW_STAMINA_END = re.compile(r"current stamina:\s*(\d+)")
_OKWW_DAILY = re.compile(r"info_set current daily progress (\d+)")
_OKWW_POINTS = outcome._DAILY_POINTS
# One of these is logged per domain entry, so counting them counts the runs.
_OKWW_ENTRY = re.compile(r"使用单倍体力|当前体力大于等于双倍|使用双倍")
# Nightmare Nest progress 「已击败残象：N/M」, logged each time the list is opened;
# the last one is reported. It is OCR (a leading digit can be lost), so it is
# shown for reference only and never used to decide whether a nest was farmed.
_OKWW_NEST = re.compile(r"已击败残象[：:]\s*(\d+)\s*/\s*(\d+)")
_OKWW_NEST_FULL = re.compile(r"指定点位都已打满")
_OKWW_DAILY_TARGET = 180
# Full value of the daily activity meter; the reading can go above it.
_OKWW_POINTS_TARGET = outcome._DAILY_POINTS_TARGET

_OKWW_FORGERY_INDEX = re.compile(r"info_set Teleport to Forgery Challenge (\d+)")
# The Simulation Challenge target (one of three in OK-WW's SimulationTask);
# translations from OK-WW's ok.po.
_OKWW_SIM_TARGET = re.compile(r"info_set Target Simulation Challenge (.+?)\s*$", re.M)
_SIM_ZH = {"Shell Credit": "贝币", "Resonator EXP": "共鸣者经验", "Weapon EXP": "武器经验"}
# Shell Credits per single run at full difficulty (game8 / fandom data, 2026-09);
# a double run gives two lots.
_SIM_REWARD_PER_RUN = {"贝币": 84000}
_OKWW_DOUBLE = re.compile(r"当前体力大于等于双倍|使用双倍")
_OKWW_SINGLE = re.compile(r"使用单倍体力")
_OKWW_TACET_INDEX = re.compile(r"info_set Teleport to Tacet Suppression (\d+)")


_LOG_DAY = re.compile(r"\d{4}-\d{2}-\d{2}(?= \d\d:\d\d)")


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
        # Name and drop sets come from wuwa_tacet's table. The index is the one
        # OK-WW teleported to (info_set, from 0), else the last teleport line.
        got = (info.get("fields") or {}).get("Teleport to Tacet Suppression")
        hits = _OKWW_TACET_INDEX.findall(text)
        if got is None and not hits:
            return ("无音区（日志里没有序号）", "声骸（无音区序号没读到，套装不明）")
        idx = (int(got) if got is not None else int(hits[-1])) + 1
        # The list moved in 3.7 (wuwa_tacet.NEW_LIST_FROM): read it as of the run's own day.
        day = (_LOG_DAY.search(text) or [None])[0]
        return (wuwa_tacet.label(idx, day), wuwa_tacet.reward(idx, day))
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


# Chinese for task class names, exception names and known raw messages, used in
# notifications; untranslated ones are quoted raw (see _okww_say).
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
    # 「farm 4c error, try handle monthly card」 is FarmEchoTask.run's catch-all
    # around do_run (FarmEchoTask.py:106-107): it names no step, so it is not
    # translated here - _okww_error reads the exception under it instead. It
    # used to read 「打完 Boss 领完奖之后没能退出副本」, which on 2026-09-21 was
    # said of a run that never got into the realm (OK-WW-05-33-53.log:1172-1177).
    ("Teleport to boss failed", "传送去打 Boss 没成（图鉴传送、选关卡、进本其中一步没过），没进本，一次没打"),
    ("can't find gray_book_boss", "按 F2 打不开图鉴——先核对键位是不是游戏默认"),
    ("NightmareNestTask Failed", "没打成"),
    ("Logger.error() got an unexpected keyword", "旧版补丁自己的日志调用写错（已撤回）"),
    ("can not battle pass", "没能进入战斗"),
    ("Game window is not connected", "连不上游戏窗口"),
    ("not in combat", "没有进入战斗"),
    ("can't find boss_proceed", "图鉴里找不到「前往」按钮"),
    # All three of the morning's failures on 2026-09-08 carried exactly this, and
    # the notification never showed it - see the wrapper branch in _okww_say.
    ("Please start in game world and in team",
     "开跑时游戏不在大世界、或者没有出战队伍，OK-WW 不肯开工"),
)
_OKWW_WRAPPER = "Daily Task exception stopped"
_OKWW_WAIT_SEC = re.compile(r"wait_until timeout .*? (\d+(?:\.\d+)?) seconds")
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

    `current task` is the step OK-WW is on, `错误` is the failure reason it
    logged, and `Teleport to Tacet Suppression` is the Tacet Suppression it
    teleported to (counting from 0).

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
    「Daily Task exception stopped」) for the same event; the innermost one
    carries the explanation.
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
    if "farm 4c error" in msg:
        # The catch-all sentence (see _OKWW_MSG_ZH): the reason is the exception
        # printed under it, e.g. 「RuntimeError: Teleport to boss failed」.
        msg = excs[-1][1].lstrip(": ").strip() if excs else ""
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
    # No generic catch-all: an untranslated error is quoted raw (_okww_say).
    return _okww_say(task, msg, exc, text, head.start())


_OKWW_TASK_BY_STEP = {
    "garden_start_game": "GardenTask", "garden": "GardenTask",
    "check": "GardenTask", "claim": "DailyTask", "farm": "FarmEchoTask",
    "tacet": "TacetTask", "nest": "NightmareNestTask",
}


# The overlay's end-as-failed mark (okww_files/ark_overrides.tasks.py FAILED_MARK).
_OKWW_ENDED_FAILED = outcome.FAILED_MARK


def _okww_say(task: str, msg: str, exc: str, text: str = "", at: int = 0) -> str:
    """Turn (task, raw message, exception name) into one plain-language
    sentence. When it cannot be translated, say so outright -- never be vague.
    """
    task_zh = _OKWW_TASK_ZH.get(task)
    if _OKWW_ENDED_FAILED in msg:
        # The overlay ended the run as failed and logged why in Chinese.
        why = msg.split(_OKWW_ENDED_FAILED, 1)[1].strip()
        who = task_zh or "某个任务"
        return why if why.startswith(who + "：") else f"{who}：{why}"
    msg_zh = next((zh for en, zh in _OKWW_MSG_ZH if en in msg), "")
    exc_zh = _OKWW_EXC_ZH.get(exc)
    if task_zh is not None and not (msg_zh or exc_zh) and _OKWW_WRAPPER in msg:
        # Only the outermost traceback (the daily list stopped) was found. Use
        # OK-WW's own 「错误 …」 line when it has one, else say the list stopped.
        # The wrapper is not in _OKWW_MSG_ZH because that table also decides which
        # traceback is reported, and the wrapper must not win there.
        err = (okww_info(text).get("error") or "").strip() if text else ""
        if err and _OKWW_WRAPPER not in err:
            return _okww_say(task, err, "")      # text="" so this branch cannot recurse
        return f"{task_zh}：日常清单整个停了（真正的原因在它上面那条）"
    if task_zh is None or not (msg_zh or exc_zh):
        sig = (task, exc, msg[:80])
        if sig not in _OKWW_UNTRANSLATED:      # Warn once per process for the same raw message
            _OKWW_UNTRANSLATED.add(sig)
            log.warning(
                "OK-WW 报错中继还没有翻译，通知里只能说不认识：任务 %s，异常 %s，原文「%s」",
                task, exc or "（没抓到异常名）", msg)
        who = task_zh or "某个任务"
        # The raw text goes into the notification itself: the machine is often
        # off by the time the alert is read, so the log cannot be looked up.
        raw = " ".join((msg or "").split())[:110] or exc or "（连原文都没抓到）"
        return f"{who}：中继还不认识这条错，原文照抄——「{raw}」"
    what = msg_zh or exc_zh
    if "Teleport to boss failed" in msg and text and re.search(
            r"找不到开启挑战|都没进开启挑战", text[max(0, at - 3000):at]):
        what = "选了等级后没等到「开启挑战」，没进本，一次没打"
    # The 「wait_until timeout … N seconds」 line right before the traceback says
    # how long it waited.
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
    if "游戏更新成功, 游戏即将重启" in text:
        out["okww_restart_dialog"] = True
        out["okww_client_change"], out["okww_client_files"] = _client_change(log_path, text)
    return out


_OKWW_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", re.M)


def _client_change(log_path: Path, text: str) -> "tuple[str, list[str]]":
    """What the game client changed on disk during this run: (「none」 (nothing
    outside saves) / 「anticheat」 (only files under AntiCheatExpert) / 「patch」
    (anything else) / 「unknown」 (game root not found), the changed paths relative
    to the game root, at most twelve).

    OK-WW logs 「游戏更新成功, 游戏即将重启」 for any dialog that says 游戏即将重启
    (BaseWWTask.py:777), including an anti-cheat refresh, so the files on disk
    decide which it was.
    """
    stamps = _OKWW_TS.findall(text)
    if not stamps:
        return "unknown", []
    try:
        lo = datetime.strptime(stamps[0], "%Y-%m-%d %H:%M:%S")
        hi = datetime.strptime(stamps[-1], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "unknown", []
    root = wuwa_game_root(log_path)
    if root is None:
        return "unknown", []
    anticheat: list[str] = []
    other: list[str] = []
    for p in (root / "Client").rglob("*"):
        try:
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            if "\\Saved\\" in rel or "/Saved/" in rel or ".quality" in rel:
                continue
            if lo.timestamp() <= p.stat().st_mtime <= hi.timestamp():
                # Shown as the part under Client\Binaries\Win64 when it is there:
                # 「AntiCheatExpert\pld.dat」 says more than the full path.
                short = rel.split("Win64" + ("\\" if "\\" in rel else "/"), 1)[-1]
                (anticheat if "AntiCheatExpert" in rel else other).append(short)
        except OSError:
            continue
    if other:
        return "patch", sorted(other)[:12]
    return ("anticheat", sorted(anticheat)[:12]) if anticheat else ("none", [])


def wuwa_game_root(log_path: Path) -> "Path | None":
    """The game install root, from OK-WW's own devices.json (the exe it launches)."""
    base = Path(os.environ.get("ARK_OKWW_DIR") or r"D:\ark\okww")
    dev = base / "data" / "apps" / "ok-ww" / "working" / "configs" / "devices.json"
    try:
        # JSON-escaped Windows path (D:\\Wuthering...) on the machine; a plain
        # POSIX path in the tests.
        m = re.search(r"(?:[A-Z]:\\\\|/)[^\"]*?Client-Win64-Shipping\.exe", dev.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if not m:
        return None
    exe = Path(m.group(0).replace("\\\\", "\\"))
    # <root>\Client\Binaries\Win64\Client-Win64-Shipping.exe
    root = exe.parents[3] if len(exe.parents) > 3 else None
    return root if root and root.is_dir() else None


def _okww_stamina_fields(text: str, out: dict) -> "tuple[list[int], int]":
    """Waveplates spent, domain entries, reserve stamina. Returns
    (the series of readings, the entry count) for the checks that follow.
    """
    readings = [int(m.group(1)) for m in _OKWW_STAMINA.finditer(text)]
    fixes = _okww_settled(text)
    if wrong := [(readings[i], v) for i, v in sorted(fixes.items()) if readings[i] != v]:
        out["okww_stamina_mismatch"] = wrong[-1]
    readings = [fixes.get(i, r) for i, r in enumerate(readings)]
    # The wrap-up line 「current stamina: 8 not enough to continue」 is the last
    # reading and holds the final run's cost.
    tail = [int(x) for x in _OKWW_STAMINA_END.findall(text)]
    if readings and len(readings) - 1 in fixes:
        tail = []      # the wrap-up line repeats the reading the dialog corrected
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
    # Never got into the game: the window wait errored, no run started, and no
    # task worked after the last window error (a transient window error can be
    # followed by a normal run).
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


_OKWW_SETTLE_LEFT = re.compile(r"体力读字原文领奖框（第 \d+ 次）: [^\n]*?剩余\s*[:：]?\s*(\d+)")


def _okww_settled(text: str) -> dict:
    """{index of an `info_set current_stamina` reading: 剩余 N on the same dialog}.

    OK-WW can misread the bar on the settlement dialog. The get_stamina override
    logs the dialog's raw text before OK-WW stores its reading, so the dialog's
    own 剩余 is paired with the reading that follows it and replaces it.
    """
    starts = [m.start() for m in _OKWW_STAMINA.finditer(text)]
    fixes = {}
    for m in _OKWW_SETTLE_LEFT.finditer(text):
        i = bisect.bisect_left(starts, m.end())
        if i < len(starts):
            fixes[i] = int(m.group(1))
    return fixes


def _okww_stamina_left(text: str, out: dict, readings: list) -> None:
    if readings and len(readings) - 1 in _okww_settled(text):
        out["okww_stamina_left"] = readings[-1]
        out["okww_stamina_left_exact"] = True
    elif end := _OKWW_STAMINA_END.findall(text):
        out["okww_stamina_left"] = int(end[-1])
        out["okww_stamina_left_exact"] = True
    elif readings:
        # No wrap-up line: the last pre-run reading, flagged as not final.
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
        # The first reading already at the target: the dailies were done before
        # this run started, so farming nothing is expected.
        if int(points[0]) >= _OKWW_POINTS_TARGET:
            out["okww_daily_done_at_start"] = True
    # Why it stopped, in its own words. "used all stamina" is the good ending.
    if "used all stamina" in text:
        # OK-WW's `used all stamina` means what is left is less than one run,
        # not that 0 is left.
        out["okww_stopped"] = "体力不够再开一局"
    elif "not enough stamina" in text:
        out["okww_stopped"] = "体力不够，一局都没开成"


def _nest_step(text: str) -> str:
    """The nightmare-nest item of the daily report's step list."""
    nest = "残象聚落" if "canxiang" in text else "梦魇巢穴"
    # A nest counts as farmed only on a fight line (outcome._NEST_ENGAGED), not
    # on the task appearing in the log.
    if "NightmareNestTask Failed" in text:
        line = f"{nest}（失败）" if outcome._NEST_ENGAGED.search(text) else f"{nest}（失败，一次没打）"
    elif outcome._NEST_NOT_FOUND in text:
        line = f"{nest}（点位名对不上，一次没打）"
    elif outcome._NEST_COUNT_UNREAD in text and not outcome._NEST_ENGAGED.search(text):
        line = f"{nest}（计数没读到，停下没刷）"
    elif _OKWW_NEST_FULL.search(text):
        # Every chosen nest at its cap: reported as done.
        line = f"{nest}（已刷满）"
    elif outcome._NEST_ENGAGED.search(text):
        # Same test as the verdict; 「is not complete」 is only the list being read.
        line = nest
    else:
        line = f"{nest}（开了界面就退出，一次没打）"
    if outcome._NEST_ADAPTED in text:
        # find_nest was installed adapted to a changed upstream body.
        line += "（只刷指定点位的过滤按 OK-WW 新版适配，请核对）"
    return line


def _okww_steps(text: str, entries: int) -> list[str]:
    """The step list in the daily report's 「备注」, each item marked with its
    own success or failure.
    """
    # Listed: the farmed domain, Nightmare Nests, the weekly boss, the weekly
    # garden and echo merging; each with its own outcome. Mail, radio and daily
    # rewards are not listed.
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
        steps.append(_nest_step(text))
    # The weekly boss; handle.py books the week from this step.
    if "Teleport to Boss Weekly Challenge" in text:
        # Only a claim the overlay re-read the counter for counts (outcome.weekly_claims);
        # 「已点确认」 alone is a click, not a claim. handle.py books the week on
        # 「周本…已完成」, so no unverified wording below may contain 已完成.
        c = outcome.weekly_claims(text)
        claims, tried = c["verified"], c["attempted"]
        unverified = outcome.weekly_unverified(c)
        left = [int(m) for m in re.findall(r"本周剩余可收取次数[：:]\s*(\d+)\s*/", text)]
        # The same shortage reading as the run's result check (outcome.WEEKLY_SHORT).
        short = bool(outcome.WEEKLY_SHORT.search(text))
        if "本周周本次数已领满" in text and not tried:
            # Read 0/3 before entering and skipped: full, but not by this run.
            steps.append("周本（已完成：进本前读到本周 0/3，早已领满，这一趟没领）")
        elif "Teleport to boss failed" in text and not tried:
            steps.append("周本（没进本，一次没打，原因见失败于）")
        elif short and not tried:
            # The overrides' own skip lines (old and current wording).
            steps.append("周本（奖励没领：结晶波片不足，这一趟没打）")
        elif "farm 4c error" in text:
            steps.append(f"周本（领了 {claims} 次，之后出错，原因见失败于）" if claims
                         else f"周本（{unverified}，之后出错，原因见失败于）" if tried
                         else "周本（没做完，原因见失败于）")
        elif not claims and ("收取物资次数已达到上限" in text or (left and left[-1] == 0 and not tried)):
            steps.append("周本（已完成，本周已领满）")
        elif claims:
            # The newest reading of the game's counter, pre-entry or read-back.
            remain = weeklyboss.left_after_claims(text)
            if remain is None:
                where = "本周剩余次数没读到"
            elif remain == 0:
                where = "本周已领满"
            else:
                where = f"本周还剩 {remain} 次"
            extra = f"；另有{unverified}" if unverified else ""
            if short:
                extra += "；剩下的奖励没领：结晶波片不足"
            steps.append(f"周本（已完成，领了 {claims} 次，{where}{extra}）")
        elif tried:
            steps.append(f"周本（{unverified}）")
        elif outcome._WEEKLY_FOUGHT.search(text):
            steps.append("周本（打了，没领到奖励）")
        elif "teleport_to_boss prepared as" in text:
            # Landed in the realm, no fight line.
            steps.append("周本（进了本，没打起来，没领到奖励）")
        else:
            steps.append("周本（没进本，一次没打）")
    # GardenTask logs 「乐园任务完成, 已达到上限」 when the week is already done and
    # right after finishing it; the English line is the older wording.
    if "weekly garden already completed" in text or "乐园任务完成" in text:
        steps.append("周常乐园（本周已完成）")
    elif "GardenTask:" in text:
        # Ran, but no 「乐园任务完成」: the counter read alone does not show it done
        # (core.UNVERIFIED_STEP; the daily title counts it as unverified).
        steps.append("周常乐园（没读到做完，不算完成）")
    if "check discarded echo" in text:
        steps.append("声骸五合一")
    return steps
