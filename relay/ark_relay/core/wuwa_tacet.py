"""Wuthering Waves Tacet Fields: index -> name -> the two echo sets it always drops.

OK-WW stores only an index (the position in the F2「素材获取 → 无音清剿」list,
counting from the top), and the logs carry only that index too. This table was
verified entry by entry in-game on 2026-09-04 (and again after 3.7 on 2026-09-30) using the echo-set filter
(「合鸣筛选」); source of record is docs/WUWA-TACET-INDEX.md, and the TACET table
in the phone page web/schema.js comes from the same source.
**Only verified entries go in here.** An unverified index is always reported as
「第 N 个无音区（对照表没登记）」 - never guess a name.
"""
from __future__ import annotations

# index -> (tacet field name, (set one, set two)); the sets in the order of the
# two icons on the row, top first.
#
# Wuthering Waves 3.7 (2026-09-30) put 沉心域 / 烬心域 at the top of 瑝珑·梦州 and
# every older index moved down by 2 (F2 list and 合鸣筛选 read in game by 中继一
# 2026-09-30, BOARD/evidence/鸣潮3.7-选项-0930). A log from before that day was
# farmed under the old list, so label()/reward() take the log's day and read the
# table in force then. No OK-WW run happened on 09-30 before the update (that
# morning's 早班 was skipped; 晚班 has only MAA), so the day itself is new-list.
NEW_LIST_FROM = "2026-09-30"
TACET: dict[int, tuple[str, tuple[str, str]]] = {
    1: ("沉心域", ("衔梦照世之心", "茜染怀想之花")),
    2: ("烬心域", ("衔梦照世之心", "镜影流电之瞬")),
    3: ("方擎西峰", ("羽落空尘之歌", "冥途夜行之灯")),
    4: ("玄幽东岳", ("羽落空尘之歌", "清邪荡煞之心")),
    5: ("落日堤屿", ("雪落无声之愿", "剪心辑梦之影")),
    6: ("冰原运输港", ("听唤语义之愿", "长路启航之星")),
    7: ("加拉尔冠阶", ("长路启航之星", "斑驳粉饰之沫")),
}
# Before 3.7 (verified 2026-09-04): the same fields, two places higher.
TACET_BEFORE_3_7: dict[int, tuple[str, tuple[str, str]]] = {i - 2: v for i, v in TACET.items() if i > 2}


def _table(day: "str | None") -> dict:
    """The table in force on `day` ("YYYY-MM-DD..."); no day = today's list."""
    return TACET_BEFORE_3_7 if day and str(day)[:10] < NEW_LIST_FROM else TACET


def label(index: int, day: "str | None" = None) -> str:
    """Display name, e.g. 「无音区·玄幽东岳」; an unlisted index says so outright."""
    hit = _table(day).get(int(index))
    return f"无音区·{hit[0]}" if hit else f"第 {index} 个无音区（对照表没登记）"


def reward(index: int, day: "str | None" = None) -> str:
    """Yield: the two echo sets this tacet field always drops. OK-WW never reads
    the reward screen, so the drop is reported from this table."""
    hit = _table(day).get(int(index))
    if not hit:
        return f"声骸（第 {index} 个无音区，套装没登记）"
    return "声骸套装 " + "、".join(hit[1]) + "（按无音区固定掉落）"
