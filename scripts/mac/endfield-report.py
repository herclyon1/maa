#!/usr/bin/env python3
"""把森空岛拉回来的终末地数据做成一张 Excel。

    scripts/mac/endfield-report.py <ef_card.json> [输出.xlsx] [--all]

默认**只保留六星**——用户 2026-08-27：「非六星我们不考虑」。
真要看全部就加 `--all`。

数据怎么来的见 `relay/ark_relay/skland.py`：森空岛官方接口，
`detail.chars` 里每个角色带等级、突破、潜能、每个技能的等级与上限、
武器、四件装备、战术道具、天赋节点。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from xlsx import Sheet, write_xlsx  # noqa: E402

CST = timezone(timedelta(hours=8))


def ts(v) -> str:
    try:
        return datetime.fromtimestamp(int(v), CST).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def equip_name(e) -> str:
    if not isinstance(e, dict):
        return ""
    d = e.get("equipData") or e.get("tacticalItemData") or {}
    return d.get("name", "")


def equip_detail(e) -> dict:
    """一件装备的练度。

    `enhance` 是 {"1": 2, "2": 2, "3": 2}——键是 `properties` 里第几条词条
    （1 开始），值是那条词条的强化等级。词条本身官方只给了原始字段名
    （`equip_attr_agi` 之类），这份数据里**没有**译名表，所以原样输出，
    不自己编中文名。
    """
    if not isinstance(e, dict):
        return {}
    d = e.get("equipData") or {}
    props = d.get("properties") or []
    enh = e.get("enhance") or {}
    pairs = [f"{p}+{enh.get(str(i + 1), 0)}" for i, p in enumerate(props)]
    levels = [int(enh.get(str(i + 1), 0) or 0) for i in range(len(props))]
    return {
        "名称": d.get("name", ""),
        "品质": (d.get("rarity") or {}).get("value", ""),
        "部位": (d.get("type") or {}).get("value", ""),
        "档位": (d.get("level") or {}).get("value", ""),
        "套组": (d.get("suit") or {}).get("name", ""),
        "基础值": d.get("baseAttrValue", 0),
        "强化合计": sum(levels),
        "词条与强化": " / ".join(pairs),
    }


SLOTS = [("身体", "bodyEquip"), ("手臂", "armEquip"),
         ("饰品一", "firstAccessory"), ("饰品二", "secondAccessory")]


def build(detail: dict, min_rarity: int = 6) -> list[Sheet]:
    base = detail.get("base") or {}
    chars = [c for c in (detail.get("chars") or [])
             if int(((c.get("charData") or {}).get("rarity") or {}).get("value", 0) or 0)
             >= min_rarity]

    main = Sheet("角色练度", [
        "名字", "稀有度", "职业", "属性", "武器类型",
        "等级", "突破阶段", "潜能",
        "技能等级", "技能上限", "技能满级数",
        "武器", "武器稀有度", "武器等级", "武器精炼", "武器突破", "武器基质",
        "装备强化合计", "套组",
        "天赋节点数", "被动节点数", "工厂节点数", "飞船节点数",
        "身体", "手臂", "饰品一", "饰品二", "战术道具", "获得日期",
    ])
    skills = Sheet("技能明细", ["角色", "技能名", "类型", "等级", "上限", "是否满级"])
    equips = Sheet("装备明细", [
        "角色", "槽位", "名称", "部位", "品质", "档位", "套组",
        "基础值", "强化合计", "词条与强化",
    ])

    for c in chars:
        cd = c.get("charData") or {}
        us = c.get("userSkills") or {}
        lv, mx, full = [], [], 0
        for s in cd.get("skills") or []:
            u = us.get(s.get("id")) or {}
            a, b = u.get("level", 0), u.get("maxLevel", 0)
            lv.append(a)
            mx.append(b)
            if b and a >= b:
                full += 1
            skills.rows.append([cd.get("name", ""), s.get("name", ""),
                                (s.get("type") or {}).get("value", ""),
                                a, b, "是" if b and a >= b else "否"])
        w = c.get("weapon") or {}
        wd = w.get("weaponData") or {}
        gem = ((w.get("gem") or {}).get("gemData") or {}).get("name", "")

        enh_total, suits = 0, []
        for slot, key in SLOTS:
            info = equip_detail(c.get(key))
            if not info:
                continue
            enh_total += info["强化合计"]
            if info["套组"]:
                suits.append(info["套组"])
            equips.rows.append([
                cd.get("name", ""), slot, info["名称"], info["部位"], info["品质"],
                info["档位"], info["套组"], info["基础值"], info["强化合计"],
                info["词条与强化"],
            ])
        suit_txt = " / ".join(f"{n}×{suits.count(n)}" for n in dict.fromkeys(suits))

        tal = c.get("talent") or {}
        main.rows.append([
            cd.get("name", ""),
            int((cd.get("rarity") or {}).get("value", 0) or 0),
            (cd.get("profession") or {}).get("value", ""),
            (cd.get("property") or {}).get("value", ""),
            (cd.get("weaponType") or {}).get("value", ""),
            c.get("level", 0), c.get("evolvePhase", 0), c.get("potentialLevel", 0),
            "/".join(str(x) for x in lv), "/".join(str(x) for x in mx), full,
            wd.get("name", ""),
            int((wd.get("rarity") or {}).get("value", 0) or 0),
            w.get("level", 0), w.get("refineLevel", 0), w.get("breakthroughLevel", 0),
            gem,
            enh_total, suit_txt,
            len(tal.get("attrNodes") or []),
            len(tal.get("latestPassiveSkillNodes") or []),
            len(tal.get("latestFactorySkillNodes") or []),
            len(tal.get("latestSpaceshipSkillNodes") or []),
            equip_name(c.get("bodyEquip")), equip_name(c.get("armEquip")),
            equip_name(c.get("firstAccessory")), equip_name(c.get("secondAccessory")),
            equip_name(c.get("tacticalItem")), ts(c.get("ownTs")),
        ])

    main.rows.sort(key=lambda r: (-r[1], -r[5], -r[6]))

    account = Sheet("账号", ["项目", "值"], [
        ["昵称", base.get("name", "")],
        ["角色 ID", base.get("roleId", "")],
        ["等级", base.get("level", 0)],
        ["世界等级", base.get("worldLevel", 0)],
        ["干员数", base.get("charNum", 0)],
        ["武器数", base.get("weaponNum", 0)],
        ["图鉴数", base.get("docNum", 0)],
        ["建号日期", ts(base.get("createTime"))],
        ["上次登录", ts(base.get("lastLoginTime"))],
        ["当前主线", ((base.get("mainMission") or {}).get("description", ""))],
        ["本表范围", f"只统计 {MIN_RARITY} 星及以上，共 {len(chars)} 名"
                       if MIN_RARITY > 1 else f"全部 {len(chars)} 名"],
        ["数据抓取自", "森空岛 /api/v1/game/endfield/card/detail"],
        ["词条为什么是英文", "官方接口只给字段名，这份数据里没有译名表，不自己编"],
    ])
    return [main, equips, skills, account]


MIN_RARITY = 6


def main() -> int:
    global MIN_RARITY
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        MIN_RARITY = 1
    if not args:
        print(__doc__)
        return 2
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else src.with_suffix(".xlsx")
    d = json.loads(src.read_text(encoding="utf-8"))
    detail = d.get("detail") or d
    sheets = build(detail, MIN_RARITY)
    write_xlsx(str(out), sheets)
    print(f"已生成 {out}")
    for s in sheets:
        print(f"  「{s.name}」{len(s.rows)} 行 × {len(s.header)} 列")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
