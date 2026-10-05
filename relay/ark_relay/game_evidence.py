"""Game evidence for 「done」.

2026-10-05: four things were reported done that the game never showed - the
鸣潮 weekly boss (stamina stayed 240/240), the 残象聚落 (never fought), and four
终末地 dailies with not one reading line between their start and end. Each was
the program's own 「success」. A task now counts as done only when the run read
something from the game that shows it; otherwise it is 「没证据，按没做」.
"""
from __future__ import annotations

import re

NO_EVIDENCE = "没证据，按没做"

# ── 鸣潮 weekly boss ────────────────────────────────────────────────
# FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：3/3_1.00, x60_0.79]
_WEEKLY_LEFT = re.compile(r"本周剩余可收取次数[：:]\s*(\d+)\s*/\s*(\d+)")
_WEEKLY_FULL = re.compile(r"周本领奖：本周三次已领满|本周周本次数已领满")
# Getting into the fight. 「teleport_to_boss prepared as」 is only the book.
_WEEKLY_COMBAT = "FarmEchoTask:enter combat"


def okww_weekly(text: str) -> tuple[bool, str]:
    """(done, evidence or why not) for the weekly boss in one OK-WW log text.

    Evidence is the game's own 「本周剩余可收取次数：N/3」 read before entering
    and the count going down: a later read, 「本周三次已领满」, or a reward
    dialog confirmed (「周本领奖：已点确认」) after the last read; and at least one
    「FarmEchoTask:enter combat」. 「teleport_to_boss prepared as」 is only the book.
    """
    reads: list[tuple[int, int]] = []   # (line index, left)
    full_at = None
    total = 3
    combat = False
    confirms: list[int] = []
    for i, line in enumerate(text.splitlines()):
        if m := _WEEKLY_LEFT.search(line):
            reads.append((i, int(m.group(1))))
            total = int(m.group(2))
        elif _WEEKLY_FULL.search(line) or "收取物资次数已达到上限" in line:
            full_at = i
        elif "周本领奖：已点确认" in line:
            confirms.append(i)
        elif _WEEKLY_COMBAT in line:
            combat = True
    if not reads:
        return False, "进本前没读到本周剩余次数，" + NO_EVIDENCE
    first = reads[0][1]
    if first == 0 and not confirms:
        # Read 0/N before entering and skipped: the week was already full.
        return True, f"进本前读到本周 0/{total}，早已领满，这一趟没领"
    last = max(0, reads[-1][1] - sum(1 for c in confirms if c > reads[-1][0]))
    if full_at is not None and full_at > reads[0][0]:
        last = 0
    claims = first - last
    if claims <= 0:
        return False, f"本周次数 {first}/{total} 没变，{NO_EVIDENCE}"
    if not combat:
        return False, f"次数 {first}/{total}→{last}/{total}，但没有进战斗的记录，{NO_EVIDENCE}"
    return True, f"本周次数 {first}/{total}→{last}/{total}，领 {claims} 次"


# ── 鸣潮 残象聚落 ────────────────────────────────────────────────────
_NEST_FOUGHT = re.compile(r"NightmareNestTask:enter combat|farm echo walk find true")
_NEST_READ = re.compile(r"已击败残象[：:]\s*\d+\s*/\s*\d+")
_NEST_ALL_FULL = "指定点位都已打满，跳过"


def okww_nest(text: str) -> tuple[bool, str]:
    """(done, evidence or why not) for the 残象聚落."""
    if _NEST_FOUGHT.search(text):
        return True, "有进战斗记录"
    full = text.find(_NEST_ALL_FULL)
    if full >= 0:
        m = None
        for m in _NEST_READ.finditer(text[:full]):
            pass
        if m:
            return True, f"读到「{m.group(0)}」后点位已满"
        return False, "说点位已满，但之前没读到击败数，" + NO_EVIDENCE
    return False, "没有进战斗记录，" + NO_EVIDENCE


# ── 鸣潮 stamina ────────────────────────────────────────────────────
# TacetTask:体力读字原文（第 1 次）: ['104', '240/240', '+']
_STAMINA_READ = re.compile(r"体力读字原文[^:：]*[:：].*?'(\d+)/(\d+)'")


def okww_stamina(text: str) -> "tuple[int, int] | None":
    """(first, last) stamina read in this text, or None when fewer than two reads."""
    vals = [int(m.group(1)) for m in _STAMINA_READ.finditer(text)]
    if len(vals) < 2:
        return None
    last = vals[-1]
    # OK-WW's own 「used all stamina」 after the last read means it went to 0.
    tail = text[text.rfind("体力读字原文"):]
    if re.search(r"used all stamina|stamina 0\b", tail):
        last = 0
    return vals[0], last


# ── 终末地 ─────────────────────────────────────────────────────────
_END_READING = re.compile(
    r"获得以下物品|当前理智|理智[：:]?\s*\d+\s*/\s*\d+|已完成交易|购买成功|拜访好友次数已满|"
    r"路线\d+[：:]|理智不足|进入协议空间成功|已完成一次基质刷取")


def _plain(name: str) -> str:
    return re.sub(r"^[^\w一-鿿]+", "", name).strip()


def maaend_tasks(text: str, shot_names=()) -> dict[str, str]:
    """{task name: evidence} for every 「任务完成」 task; evidence "" = none.

    A reading line between 「任务开始: X」 and 「任务完成: X」, or a task-end
    screenshot whose name carries X (task_shots.py), counts. A screenshot is
    something that can be checked later, so it is said as 「有截图」.
    """
    out: dict[str, str] = {}
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if m := re.search(r"任务开始[:：]\s*(\S.+?)\s*$", line):
            start = (i, _plain(m.group(1)))
            continue
        if start is None:
            continue
        if m := re.search(r"任务完成[:：]\s*(\S.+?)\s*$", line):
            name = _plain(m.group(1))
            if name != start[1]:
                continue
            seg = "\n".join(lines[start[0]:i + 1])
            ev = ""
            if r := _END_READING.search(seg):
                ev = r.group(0)
            elif any(name in s for s in shot_names):
                ev = "有截图"
            if name not in out or ev:
                out[name] = ev
            start = None
    return out


def maaend_no_evidence(text: str, shot_names=()) -> list[str]:
    return [n for n, ev in maaend_tasks(text, shot_names).items() if not ev]

