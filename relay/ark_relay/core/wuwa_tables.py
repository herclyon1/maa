"""WuWa boss, forgery, and tacet-field drop/label lookup tables."""
from __future__ import annotations

import types


def _make_wuwa_boss():

    # position (1-based, as OK-WW counts) -> (name, which section it appeared under)
    BOSSES: dict[int, tuple[str, str]] = {
        1: ("天傀劫煞", "瑝珑·梦州"),
        2: ("万囿牢·朽躯", "瑝珑·梦州"),
        3: ("梦魇亚当·重锤", "索拉里斯之极·拉海洛"),
        4: ("无铭探索者", "索拉里斯之极·拉海洛"),
    }


    def label(index: int) -> str:
        """A name a person can read, or 「第 N 个」 when the table does not know it."""
        row = BOSSES.get(int(index)) if str(index).isdigit() else None
        return row[0] if row else f"第 {index} 个"


    def choices() -> list[tuple[int, str]]:
        """(index, name) for the phone page, in list order."""
        return [(i, BOSSES[i][0]) for i in sorted(BOSSES)]

    return types.SimpleNamespace(BOSSES=BOSSES, label=label, choices=choices)


wuwa_boss = _make_wuwa_boss()
BOSSES = wuwa_boss.BOSSES


def _make_wuwa_forgery():

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
        16: ("熔毁废都", "迅刀", "瑝珑·今州"),
        17: ("旋雾之森", "音感仪", "瑝珑·今州"),
        18: ("侵蚀废都", "长刃", "瑝珑·今州"),
        19: ("流月之森", "臂铠", "瑝珑·今州"),
        20: ("欲燃之森", "佩枪", "瑝珑·今州"),
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


    def choices() -> list[tuple[int, str]]:
        """(index, display label) for the phone/snapshot option list, in F2 order."""
        return [(i, f"{i} · {FORGERY[i][1]}（{FORGERY[i][0]}）") for i in sorted(FORGERY)]

    return types.SimpleNamespace(FORGERY=FORGERY, label=label, reward=reward, choices=choices)


wuwa_forgery = _make_wuwa_forgery()
FORGERY = wuwa_forgery.FORGERY


def _make_wuwa_tacet():

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
    TACET_BEFORE_3_7: dict[int, tuple[str, tuple[str, str]]] = {i - 2: v for i, v in TACET.items() if i > 2}


    def _table(day: "str | None") -> dict:
        """The table in force on `day` ("YYYY-MM-DD..."); no day = today's list."""
        return TACET_BEFORE_3_7 if day and str(day)[:10] < NEW_LIST_FROM else TACET


    def label(index: int, day: "str | None" = None) -> str:
        """Display name, e.g. 「无音区·玄幽东岳」; an unlisted index says so outright."""
        hit = _table(day).get(int(index))
        return f"无音区·{hit[0]}" if hit else f"第 {index} 个无音区（对照表没登记）"


    def sets(index: int, day: "str | None" = None) -> "tuple[str, str] | None":
        """The two echo sets this tacet field drops, or None when unlisted (never guessed)."""
        if isinstance(index, bool) or not str(index).isdigit():
            return None
        hit = _table(day).get(int(index))
        return hit[1] if hit else None


    def sets_label(index: int, day: "str | None" = None) -> str:
        """Human-readable echo sets for snapshots / remote UI, e.g. 「衔梦照世之心 ＋ 茜染怀想之花」."""
        pair = sets(index, day)
        if not pair:
            return f"第 {index} 个无音区（声骸套装没登记）"
        return " ＋ ".join(pair)


    def choices(day: "str | None" = None) -> list[tuple[int, str]]:
        """(index, echo sets label) for the phone/snapshot option list, in F2 order."""
        tbl = _table(day)
        return [(i, " ＋ ".join(tbl[i][1])) for i in sorted(tbl)]


    def reward(index: int, day: "str | None" = None) -> str:
        """Yield: the two echo sets this tacet field always drops. OK-WW never reads
        the reward screen, so the drop is reported from this table."""
        hit = _table(day).get(int(index))
        if not hit:
            return f"声骸（第 {index} 个无音区，套装没登记）"
        return "声骸套装 " + "、".join(hit[1]) + "（按无音区固定掉落）"

    return types.SimpleNamespace(
        NEW_LIST_FROM=NEW_LIST_FROM, TACET=TACET, TACET_BEFORE_3_7=TACET_BEFORE_3_7,
        _table=_table, label=label, sets=sets, sets_label=sets_label, choices=choices, reward=reward,
    )


wuwa_tacet = _make_wuwa_tacet()
NEW_LIST_FROM = wuwa_tacet.NEW_LIST_FROM
TACET = wuwa_tacet.TACET
TACET_BEFORE_3_7 = wuwa_tacet.TACET_BEFORE_3_7
