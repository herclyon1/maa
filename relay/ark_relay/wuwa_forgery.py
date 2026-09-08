"""Wuthering Waves Forgery Challenges: index -> name -> the weapon material it yields.

OK-WW stores only an index (the position in the F2「素材获取 → 凝素领域」list,
counting from the top), and the logs carry only that index, so a report saying
「凝素领域 ×3」 is readable by a machine and not by a person. The user, 2026-08-26:
「他那个凝素领域第一个机器看得懂，人看不懂是什么啊」.

This table is the **complete** list, read screen by screen in-game on 2026-09-04;
source of record is docs/WUWA-TACET-INDEX.md, and the FORGE table in the phone
page web/app.js comes from the same source.
Indices start at **1**, matching the position in the in-game list - callers must
not apply an offset of their own.

**It is not valid forever**: the list order is decided by the game, so adding a
weapon-type filter, or a version update introducing new instances, shifts the
indices. An index that is not in the table is always reported as 「第 N 个」 -
better to say less than to report a wrong name.

2026-09-08, moved out of collector and completed: the old copy had only 4 entries
(0..3), while the phone page could already select the 5th, and selecting it wrote
「凝素领域·#5」 into tomorrow's plan - exactly the 「井号二是什么玩意儿」 class
of problem.
"""
from __future__ import annotations

# index (1-based) -> (name, weapon material it yields, region)
FORGERY: dict[int, tuple[str, str, str]] = {
    1: ("陨翼云渊", "迅刀", "瑝珑·梦州"),
    2: ("静灭云渊", "音感仪", "瑝珑·梦州"),
    3: ("裂斩云渊", "长刃", "瑝珑·梦州"),
    4: ("碎蚀云渊", "臂铠", "瑝珑·梦州"),
    5: ("沉熄云渊", "佩枪", "瑝珑·梦州"),
    6: ("荒蓁旧殿", "迅刀", "索拉里斯之极·拉海洛"),
    7: ("残照终课", "音感仪", "索拉里斯之极·拉海洛"),
    8: ("灾逆旧殿", "长刃", "索拉里斯之极·拉海洛"),
    9: ("虚诞终课", "臂铠", "索拉里斯之极·拉海洛"),
    10: ("余烬终课", "佩枪", "索拉里斯之极·拉海洛"),
    11: ("赦罪庭园", "迅刀", "黎那汐塔"),
    12: ("浸礼海渊", "音感仪", "黎那汐塔"),
    13: ("赞颂庭园", "长刃", "黎那汐塔"),
    14: ("祝祭海渊", "臂铠", "黎那汐塔"),
    15: ("告解海渊", "佩枪", "黎那汐塔"),
}


def label(index: int) -> str:
    """Display name, e.g. 「凝素领域·陨翼云渊（迅刀）」; an unlisted index reports
    its position instead - never invent a name."""
    hit = FORGERY.get(int(index))
    if not hit:
        return f"凝素领域（第 {index} 个，对照表没登记）"
    return f"凝素领域·{hit[0]}（{hit[1]}）"


def reward(index: int) -> str:
    """Yield: which weapon type's ascension material this instance gives."""
    hit = FORGERY.get(int(index))
    return f"{hit[1]}突破材料" if hit else "武器突破材料"
