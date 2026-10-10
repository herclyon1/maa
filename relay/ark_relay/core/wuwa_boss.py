"""Wuthering Waves overworld bosses: the position in F2 → 讨伐强敌, top to bottom.

OK-WW's 「Which Boss Challenge to Teleport」 is that position and nothing else - it
clicks the Nth row and never reads a name - so a report or a phone page that shows
only a number is unreadable, and picking the wrong number farms the wrong boss.

Read off the machine's own screen on 2026-09-09 (F2 → 讨伐强敌, 索拉等级 8). Only
**1 is verified end to end**: OK-WW teleported to it and the arena banner read
「Lv.90 天傀劫煞」. The rest are the names in the order they appeared on that screen,
which is the same order OK-WW counts in - but they have not each been entered.

**Not valid forever.** The order is the game's, and 天傀劫煞 sits under a
「限时提前开放」 banner that will move once its story unlocks; a version update also
adds rows. An index that is not in this table is always shown as 「第 N 个」 rather
than guessed at - the same rule as wuwa_forgery.
"""
from __future__ import annotations

# position (1-based, as OK-WW counts) -> (name, which section it appeared under)
BOSSES: dict[int, tuple[str, str]] = {
    1: ("天傀劫煞", "限时提前开放"),
    2: ("万囿牢·朽躯", "瑝珑·梦州"),
    3: ("梦魇亚当·重锤", "索拉里斯之极·拉海洛"),
    4: ("无铭探索者", "索拉里斯之极·拉海洛"),
}

# The one position an automated run has actually reached.
VERIFIED = frozenset({1})


def label(index: int) -> str:
    """A name a person can read, or 「第 N 个」 when the table does not know it."""
    row = BOSSES.get(int(index)) if str(index).isdigit() else None
    return row[0] if row else f"第 {index} 个"


def choices() -> list[tuple[int, str]]:
    """(index, name) for the phone page, in list order."""
    return [(i, BOSSES[i][0]) for i in sorted(BOSSES)]
