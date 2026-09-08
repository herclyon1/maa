"""Wuthering Waves Tacet Fields: index -> name -> the two echo sets it always drops.

OK-WW stores only an index (the position in the F2「素材获取 → 无音清剿」list,
counting from the top), and the logs carry only that index too. This table was
verified entry by entry in-game on 2026-09-04 using the echo-set filter
(「合鸣筛选」); source of record is docs/WUWA-TACET-INDEX.md, and the TACET table
in the phone page web/app.js comes from the same source.
**Only verified entries go in here.** An unverified index is always reported as
「第 N 个无音区（对照表没登记）」 - never guess a name.
"""
from __future__ import annotations

# index -> (tacet field name, (set one, set two))
TACET: dict[int, tuple[str, tuple[str, str]]] = {
    1: ("方掌西峰", ("羽落空尘之歌", "冥途夜行之灯")),
    2: ("玄幽东岳", ("羽落空尘之歌", "清邪荡煞之心")),
    3: ("落日堤屿", ("雪落无声之愿", "剪心辑梦之影")),
    4: ("冰原运输港", ("听唤语义之愿", "长路启航之星")),
    5: ("加拉尔冠阶", ("长路启航之星", "斑驳粉饰之沫")),
}


def label(index: int) -> str:
    """Display name, e.g. 「无音区·玄幽东岳」; an unlisted index says so outright."""
    hit = TACET.get(int(index))
    return f"无音区·{hit[0]}" if hit else f"第 {index} 个无音区（对照表没登记）"


def reward(index: int) -> str:
    """Yield: the two echo sets this tacet field always drops. OK-WW never reads
    the reward screen, so the drop is reported from this table."""
    hit = TACET.get(int(index))
    if not hit:
        return f"声骸（第 {index} 个无音区，套装没登记）"
    return "声骸套装 " + "、".join(hit[1]) + "（按无音区固定掉落）"
