#!/usr/bin/env python3
"""Build `web/data/need.json`: what the **newest six-star operator's** full build
(with her signature weapon) needs, per material.

The phone page's 库存 tab shows, per material, 库存 | 单个角色满练所需 | 人份 (stock ÷
need). Stock is live (the page asks Skland itself, `web/inventory.js`); need is this
static table. The user's caliber (2026-09-18, final): the older operators are all
built, so the need is that of **the newest released six-star only** - no averages,
no roster maximum. Nothing here runs on a timer; rerun it when a six-star appears.

    python3 scripts/mac/build-need-tables.py                          # live -> web/data/need.json
    python3 scripts/mac/build-need-tables.py --save-fixtures DIR      # live, and keep the (trimmed) responses
    python3 scripts/mac/build-need-tables.py --offline DIR -o FILE    # rebuild from saved responses
    python3 scripts/mac/build-need-tables.py --char 莱万汀 --weapon 熔铸火焰   # a named pair instead
    python3 scripts/mac/build-need-tables.py --rarity 5                # the newest five-star instead

Endfield only for now. The `games[]` layer is where 明日方舟 / 鸣潮 go later; inside a
game, `standards[]` holds the build standards (one today) and `rows` mirrors the
default one for the page.

## Who is "the newest six-star", and which weapon is "her signature weapon"

All official, from the Skland wiki (`docs/SKLAND-API.md` §8), no account data involved:

1. `GET /web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true` - the wiki's catalog;
   subtype 干员 and subtype 武器. Rarity tag = `brief.subTypeList[subTypeId=10000].value`
   (`10006` six-star, `10005` five-star, `10004` four-star).
2. `GET /web/v1/wiki/item/info?id=<itemId>` - the entry's attribute table: operators
   carry `上线时间` and `主要获取方式`; weapons carry those two and `类型` as well.
3. Newest six-star = the six-star with the latest `上线时间` **not after today**
   (server date). A six-star announced for a future date (`label_type_preview`) is
   listed under `coverage.upcoming`, never chosen.
4. Signature weapon = the six-star weapon whose `上线时间` equals hers, whose `类型`
   equals her `weaponType` (from `search-chars`) and whose `主要获取方式` is
   「武库交易所·限时特卖」 - the limited-sale slot every banner weapon is sold in
   (熔铸火焰 for 莱万汀 on 2026-01-22, 寒夜幽影 for 提弗洛斯 on 2026-09-02; the other new
   weapon of that day, 苦难的尽头, is 「协议通行证·武器补给」 and is not chosen). If that
   does not name exactly one weapon the build stops and asks for `--weapon`.

## Where the numbers come from

* `calculate/rules?charIds=<one id>` (comma-joined ids return nothing):
  `breakthroughs[]` + `skills[].levels[]` up to level 12, plus `charLevelRules` 1 -> 90.
  Talents excluded, the scope of `docs/ENDFIELD-SANITY-YIELD.md` §B.
* `calculate/rules?weaponIds=<one id>`: `weapons[].breakthroughs[]` + `weaponLevelRules`.
* The universal rows (identical for every operator) are verified on every build across
  every six-star the calculator lists; a material whose count differs between them is
  the operator's own choice and is written with her name.
* `calculate/material-list` for names, rarity, icon and exp value of all 40 materials.

## Read-off traps (each pinned by `relay/tests/test_need_table.py`)

* `charLevelRules[89]` (level 90) is `gold: "-1", exp: "-1"`: a sentinel, not a cost.
* `material-list` names carried a trailing newline on 2026-08-28. Always `strip()`.
* A material the account holds none of is absent from `itemCount`, not 0.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "relay"))

ZONAI = "https://zonai.skland.com"
ENV = Path.home() / ".config/ark/.env"
OUT_DEFAULT = REPO / "web" / "data" / "need.json"
SERVER_TZ = timezone(timedelta(hours=8))

GAME, GAME_ID = "终末地", "endfield"
SOURCE = ("最新六星与其专武按森空岛百科的「上线时间」「类型」「主要获取方式」定；"
          "用量按森空岛养成计算器 rules 逐项求和；名字和图标取自 material-list。方法见 docs/SKLAND-API.md §8")
MAX_SKILL_LEVEL = 12
EXP_CHAR, EXP_WEAPON = "exp:char", "exp:weapon"
RARITY_TAG = {"6": "10006", "5": "10005", "4": "10004"}   # brief.subTypeList[subTypeId=10000].value
SIGNATURE_OBTAIN = "武库交易所·限时特卖"
_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")

# Which sanity stage drops it - MaaEnd's item -> stage mapping (`SupplyPlanMain.json`)
# and `ItemTable.obtainWayIds`, as tabulated in docs/ENDFIELD-SANITY-YIELD.md §A. No
# entry = `stage: null`; unknown is written as unknown.
STAGE = {
    "协议棱柱组": "技能提升 A", "协议棱柱": "技能提升 B",
    "协议圆盘组": "干员进阶 A", "协议圆盘": "干员进阶 B",
    "折金票": "钱币收集",
    "重型强固模具": "武器进阶 A", "强固模具": "武器进阶 B",
    "D96钢样品四": "高阶培养Ⅰ", "超距辉映管": "高阶培养Ⅱ", "快子遴捡晶格": "高阶培养Ⅲ",
    "象限拟合液": "高阶培养Ⅳ", "三相纳米片": "高阶培养Ⅴ",
    "存续的痕迹": "通行证 / 黄票商店 / 活动（不耗理智）",
    "高阶培养自选箱Ⅰ": "通行证（不耗理智）",
}
GATHER = "采集 / 帝江号仓库（不耗理智）"
# `ItemTable.obtainWayIds` = item_obtain_gather_* for every leaf, mushroom and stone
# (client table of 2026-09-04, rmxlinux/EndfieldData; 协议纹石 = item_plant_spcstone_2_3).
GATHERED = {"纯晶多齿叶", "至晶多齿叶", "晶化多齿叶", "受蚀玉化叶", "岩天使叶", "红矛叶",
            "重红柱状菌", "中红柱状菌", "轻红柱状菌", "星门菌", "血菌", "塔罗斯菌",
            "中黯石", "重黯石", "轻黯石", "武陵石", "燎石", "协议纹石"}
WEAPON_UNIVERSAL = {"重型强固模具", "强固模具", "中黯石", "重黯石", "轻黯石"}
# The phone page's sections, in display order. A material family, not a standard,
# so the headings stay put when the standard changes. Rows without a section (the
# exp cards folded into the two exp rows) are not shown as rows.
SECTIONS = ("通用", "高阶素材", "采集", "经验与货币")
HIGH_TIER = {"D96钢样品四", "超距辉映管", "快子遴捡晶格", "象限拟合液", "三相纳米片", "高阶培养自选箱Ⅰ"}
LAG_MINUTES = 30
# The official calculator page's own words (game.skland.com/tools/endfield/cost-calculator,
# quoted in scripts/mac/lib/snapshot.py on 2026-08-28): 「仓库资源和干员数据等信息的同步，
# 会有 30 分钟左右的延迟」. Stated by Skland, not measured here.
LAG_NOTE = "森空岛的仓库数比游戏里晚约 30 分钟（官方养成计算器页面自己写的）"


def section_of(name: str, kind: str) -> str | None:
    if kind != "materials":
        return None                      # exp cards: folded into 干员经验 / 武器经验
    if name in HIGH_TIER:
        return "高阶素材"
    if name in GATHERED:
        return "采集"
    if name == "折金票":
        return "经验与货币"
    return "通用"


def _retry(fn, tries=4, wait=2):
    """Tokyo -> Shanghai wobbles; a first TLS handshake timing out is routine."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - whatever it was, the next try may pass
            last = e
            if i < tries - 1:
                time.sleep(wait)
    raise last


class RulesSource:
    """Where responses come from: Skland live, or a directory of saved ones."""

    def __init__(self, offline: Path | None, save: Path | None):
        self.offline, self.save = offline, save
        self.cred = None
        if offline is None:
            from ark_relay import skland  # noqa: PLC0415 - only the live path needs it
            self.skland = skland
            tok = next(line.split("=", 1)[1].strip()
                       for line in ENV.read_text(encoding="utf-8").splitlines()
                       if line.startswith("SKLAND_TOKEN="))
            self.cred = _retry(lambda: skland.refresh(skland.login(tok)))

    def get(self, name: str, path: str, query: str = "", trim=None) -> dict:
        """One response, by fixture name. `trim` cuts it to what `build()` reads
        before it is saved for `--offline`."""
        if self.offline is not None:
            p = self.offline / f"{name}.json"
            if not p.exists():
                raise FileNotFoundError(f"fixture missing: {p}")
            return json.loads(p.read_text(encoding="utf-8"))
        url = f"{ZONAI}{path}" + (f"?{query}" if query else "")

        def once():
            req = urllib.request.Request(url, headers=self.skland.sign_headers(self.cred, url))
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))

        d = _retry(once)
        if d.get("code") not in (0, None):
            raise RuntimeError(f"{path} → code {d.get('code')} {d.get('message')}")
        data = d["data"]
        if self.save is not None:
            self.save.mkdir(parents=True, exist_ok=True)
            kept = trim(data, self) if trim else data
            (self.save / f"{name}.json").write_text(
                json.dumps(kept, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return data


# ── trims: what each response is cut down to when saved as a fixture ──────────

def _catalog_items(d: dict, subtype: str) -> list[dict]:
    return next((s for s in d["catalog"][0]["typeSub"] if s["name"] == subtype), {"items": []})["items"]


def trim_catalog(d: dict, _src=None) -> dict:
    return {"catalog": [{"typeSub": [
        {"name": sub, "items": [
            {"itemId": it["itemId"], "name": it["name"], "publishedAtTs": it.get("publishedAtTs"),
             "brief": {"dotType": it["brief"].get("dotType"), "subTypeList": it["brief"].get("subTypeList", [])}}
            for it in _catalog_items(d, sub)]}
        for sub in ("干员", "武器")]}]}


def wiki_attrs(item: dict) -> dict:
    """The label/value attribute table of a wiki entry (上线时间, 类型, 主要获取方式, …)."""
    out = {}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("label"), str) and "value" in o:
                out[o["label"]] = o["value"]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(item.get("document"))
    return out


def trim_wiki_item(d: dict, _src=None) -> dict:
    it = d.get("item") or {}
    a = wiki_attrs(it)
    return {"item": {"itemId": it.get("itemId"), "name": it.get("name"), "publishedAtTs": it.get("publishedAtTs"),
                     "attrs": {k: a[k] for k in ("上线时间", "主要获取方式", "类型") if k in a}}}


def trim_search_chars(d: dict, _src=None) -> dict:
    return {"chars": [{"id": c["id"], "name": c["name"], "rarity": c.get("rarity"), "weaponType": c.get("weaponType")}
                      for c in d.get("chars", [])]}


def trim_search_weapons(d: dict, _src=None) -> dict:
    return {"weapons": [{"id": w["id"], "name": w["name"]} for w in d.get("weapons", [])]}


def trim_rules(d: dict, src=None) -> dict:
    """A rules response without `talents` and without the two 90-row level tables -
    those are identical in every response and are kept once as `level-rules.json`."""
    if src is not None and src.save is not None:
        lv = src.save / "level-rules.json"
        if not lv.exists() and "charLevelRules" in d:
            lv.write_text(json.dumps({k: d[k] for k in ("charLevelRules", "weaponLevelRules")},
                                     ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    out = {k: v for k, v in d.items() if k not in ("charLevelRules", "weaponLevelRules")}
    out["chars"] = [{k: v for k, v in c.items() if k != "talents"} for c in d.get("chars", [])]
    return out


# ── the arithmetic ────────────────────────────────────────────────────────────

def material_table(mat: dict) -> dict[str, dict]:
    """id -> {name, rarity, icon, exp, kind} for all 40 materials, names stripped."""
    out = {}
    for kind in ("charExpMaterials", "weaponExpMaterials", "materials"):
        for mid, m in mat[kind].items():
            out[mid] = {"name": str(m.get("name", "")).strip(),
                        "rarity": int(m["rarity"]["value"]) if m.get("rarity") else None,
                        "icon": m.get("icon", ""), "exp": int(m.get("exp") or 0), "kind": kind}
    return out


def char_need(rule: dict) -> tuple[Counter, int]:
    """Materials and gold for every breakthrough plus every skill level up to 12."""
    c = rule["chars"][0]
    need, gold = Counter(), 0
    for b in c["breakthroughs"]:
        gold += int(b["gold"])
        for m in b["materials"]:
            need[m["resourceId"]] += int(m["count"])
    for s in c["skills"]:
        for lv in s["levels"]:
            if int(lv["targetLevel"]) <= MAX_SKILL_LEVEL:
                gold += int(lv["gold"])
                for m in lv["materials"]:
                    need[m["resourceId"]] += int(m["count"])
    return need, gold


def weapon_need(rule: dict) -> tuple[Counter, int]:
    w = rule["weapons"][0]
    need, gold = Counter(), 0
    for b in w["breakthroughs"]:
        gold += int(b["gold"])
        for m in b["materials"]:
            need[m["resourceId"]] += int(m["count"])
    return need, gold


def level_totals(rows: list[dict]) -> tuple[int, int]:
    """Gold and exp for 1 -> 90. Negative entries are the level-90 sentinel, skipped."""
    return (sum(int(r["gold"]) for r in rows if int(r["gold"]) >= 0),
            sum(int(r["exp"]) for r in rows if int(r["exp"]) >= 0))


def parse_online_date(s: str) -> str:
    m = _DATE.search(s or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def wiki_entries(src: RulesSource, subtype: str, rarity: str) -> list[dict]:
    """Every catalog entry of `subtype` (干员 / 武器) at `rarity`, with its wiki
    attributes: name, wikiItemId, onlineDate, obtain, kind (类型), dotType."""
    cat = src.get("wiki-catalog", "/web/v1/wiki/item/catalog", "typeMainId=1&onlyOnline=true", trim_catalog)
    items = [it for it in _catalog_items(cat, subtype)
             if any(x.get("subTypeId") == "10000" and x.get("value") == RARITY_TAG[rarity]
                    for x in it["brief"].get("subTypeList", []))]
    rows = []
    for it in items:
        info = src.get(f"wiki-item-{it['itemId']}", "/web/v1/wiki/item/info", f"id={it['itemId']}", trim_wiki_item)
        item = info.get("item") or {}
        attrs = item.get("attrs") or wiki_attrs(item)
        rows.append({"name": it["name"], "wikiItemId": str(it["itemId"]),
                     "onlineDate": parse_online_date(attrs.get("上线时间", "")), "onlineText": attrs.get("上线时间", ""),
                     "obtain": attrs.get("主要获取方式", ""), "kind": attrs.get("类型", ""),
                     "dotType": it["brief"].get("dotType") or "", "publishedAtTs": int(it.get("publishedAtTs") or 0)})
    return rows


def newest_released(entries: list[dict], today: str) -> tuple[dict, list[dict], list[dict]]:
    """(newest entry released on or before `today`, all released newest-first, upcoming)."""
    released = sorted((e for e in entries if e["onlineDate"] and e["onlineDate"] <= today),
                      key=lambda r: (r["onlineDate"], r["publishedAtTs"], r["name"]), reverse=True)
    upcoming = sorted((e for e in entries if e["onlineDate"] > today), key=lambda r: r["onlineDate"])
    if not released:
        raise RuntimeError("no released entry with an 上线时间 on or before today")
    return released[0], released, upcoming


def signature_weapon(weapons: list[dict], op: dict, weapon_type: str) -> dict:
    """The weapon sold in 限时特卖 on the operator's release day, of her weapon type."""
    hits = [w for w in weapons
            if w["onlineDate"] == op["onlineDate"] and w["kind"] == weapon_type and w["obtain"] == SIGNATURE_OBTAIN]
    if len(hits) != 1:
        raise RuntimeError(f"signature weapon for {op['name']} ({op['onlineDate']}, {weapon_type}) is not unique: "
                           f"{[w['name'] for w in hits]} - pass --weapon")
    return hits[0]


def build(src: RulesSource, pulled_at: str, today: str, char_name: str = "", weapon_name: str = "",
          rarity: str = "6") -> dict:
    mat = material_table(src.get("material-list", "/web/v1/game/endfield/calculate/material-list"))
    listed = src.get("search-chars", "/web/v1/game/endfield/search-chars", "", trim_search_chars)["chars"]
    calc_ids = {c["name"]: c["id"] for c in listed}
    weapon_types = {c["name"]: str(((c.get("weaponType") or {}).get("value")) or "") for c in listed}
    # Keyed by name, first entry wins: 管理员 is listed twice (female / male) with the
    # same name and the same rules; one copy is enough for the universal check.
    six_ids = {}
    for c in listed:
        if str((c.get("rarity") or {}).get("value")) == rarity and c["name"] not in six_ids:
            six_ids[c["name"]] = c["id"]
    weapons_listed = src.get("search-weapons", "/web/v1/game/endfield/search-weapons", "", trim_search_weapons)["weapons"]
    wid_of = {w["name"]: w["id"] for w in weapons_listed}

    # 1. who, and her signature weapon - both from the official wiki
    ops = wiki_entries(src, "干员", rarity)
    newest, released, upcoming = newest_released(ops, today)
    who = char_name or newest["name"]
    op = next((e for e in ops if e["name"] == who), None) or {"name": who, "wikiItemId": "", "onlineDate": "", "obtain": ""}
    if who not in calc_ids:
        raise RuntimeError(f"{who} is not in the calculator yet (search-chars lists {len(listed)} operators)")
    if weapon_name:
        weapon, weapon_reason = {"name": weapon_name, "wikiItemId": "", "onlineDate": "", "obtain": "", "kind": ""}, "--weapon"
    else:
        weapon = signature_weapon(wiki_entries(src, "武器", rarity), op, weapon_types.get(who, ""))
        weapon_reason = (f"百科：与 {who} 同日（{weapon['onlineDate']}）上线、同为{weapon['kind']}、"
                         f"主要获取方式「{SIGNATURE_OBTAIN}」的唯一一把六星武器")
    if weapon["name"] not in wid_of:
        raise RuntimeError(f"weapon {weapon['name']} is not in the calculator (search-weapons)")

    # 2. the universal part, checked across every six-star the calculator lists
    ref_rules = {nm: src.get(f"rules-char-{cid}", "/web/v1/game/endfield/calculate/rules", f"charIds={cid}", trim_rules)
                 for nm, cid in six_ids.items()}
    if who not in ref_rules:
        ref_rules[who] = src.get(f"rules-char-{calc_ids[who]}", "/web/v1/game/endfield/calculate/rules",
                                 f"charIds={calc_ids[who]}", trim_rules)
    needs = {nm: char_need(r) for nm, r in ref_rules.items()}
    golds = {g for _, g in needs.values()}
    if len(golds) != 1:
        raise RuntimeError(f"breakthrough/skill gold differs between {rarity}-stars: {golds}")
    op_gold = golds.pop()
    all_ids = set().union(*[n.keys() for n, _ in needs.values()])
    universal = {mid for mid in all_ids if len({n.get(mid, 0) for n, _ in needs.values()}) == 1}
    uni_counts = {mid: needs[who][0][mid] for mid in universal}
    lv = next((r for r in ref_rules.values() if "charLevelRules" in r), None)
    if lv is None:
        if src.offline is None:
            raise RuntimeError("no level tables in any rules response")
        lv = json.loads((src.offline / "level-rules.json").read_text(encoding="utf-8"))
    char_gold, char_exp = level_totals(lv["charLevelRules"])
    weap_gold, weap_exp = level_totals(lv["weaponLevelRules"])

    # 3. her own choices, and the weapon's
    own = {mat[mid]["name"]: c for mid, c in needs[who][0].items() if mid not in universal}
    wrule = src.get(f"rules-weapon-{wid_of[weapon['name']]}", "/web/v1/game/endfield/calculate/rules",
                    f"weaponIds={wid_of[weapon['name']]}", trim_rules)
    wneed, w_gold = weapon_need(wrule)
    wneed_by_name = {mat[mid]["name"]: c for mid, c in wneed.items()}
    gold_total = op_gold + char_gold + w_gold + weap_gold

    # 4. rows: every material, with this build's need (0 when the build does not use it)
    rows = []
    for mid, m in mat.items():
        nm = m["name"]
        row = {"id": mid, "name": nm, "rarity": m["rarity"], "icon": m["icon"], "need": 0, "group": None,
               "section": section_of(nm, m["kind"]),
               "stage": STAGE.get(nm) or (GATHER if nm in GATHERED else None), "note": None}
        w = wneed_by_name.get(nm, 0)
        if m["kind"] != "materials":
            row.update(need=None, exp=m["exp"], sumInto=EXP_CHAR if m["kind"] == "charExpMaterials" else EXP_WEAPON,
                       stage="干员经验" if m["kind"] == "charExpMaterials" else "武器经验")
        elif nm == "折金票":
            row.update(need=gold_total, group="通用", note=f"干员 {op_gold + char_gold:,} + 武器 {w_gold + weap_gold:,}")
        elif mid in universal:
            row.update(need=uni_counts[mid], group="通用")
        elif nm in own:
            row.update(need=own[nm] + w, group=who, note=(f"干员 {own[nm]} + 专武 {w}" if w else None))
        elif w and nm in WEAPON_UNIVERSAL:
            row.update(need=w, group="通用")
        elif w:
            row.update(need=w, group=f"专武 {weapon['name']}")
        elif nm == "高阶培养自选箱Ⅰ":
            row.update(need=None, note="开出任意一种高阶素材，不计入人份")
        else:
            row["note"] = f"{who} 的满练不用它"
        rows.append(row)
    rows.append({"id": EXP_CHAR, "name": "干员经验", "rarity": None, "icon": "", "need": char_exp, "group": "通用",
                 "section": "经验与货币", "stage": "干员经验", "virtual": True, "note": "五种作战记录 / 认知载体按经验值折算"})
    rows.append({"id": EXP_WEAPON, "name": "武器经验", "rarity": None, "icon": "", "need": weap_exp, "group": "通用",
                 "section": "经验与货币", "stage": "武器经验", "virtual": True, "note": "武器检查套组 / 装置 / 单元按经验值折算"})
    sec = {name: i for i, name in enumerate(SECTIONS)}
    rows.sort(key=lambda r: (sec.get(r["section"], len(SECTIONS)), 2 if r["need"] is None else 1 if r["need"] == 0 else 0,
                             -(r["need"] or 0), r["name"]))

    label = {"6": "最新六星", "5": "最新五星", "4": "最新四星"}[rarity] if who == newest["name"] and not char_name else "指定干员"
    online = f"（{op['onlineDate']} 上线）" if op.get("onlineDate") else ""
    caliber = f"{label} {who}{online}：1→90 全突破、四技能 12、专武 {weapon['name']} 1→90；不含天赋"
    footnote = (f"人份 = 库存 ÷ {who}满练所需（1→90 全突破、四技能 12、专武{weapon['name']} 1→90，不含天赋"
                + (f"；{op['onlineDate']} 上线的{label}" if op.get("onlineDate") and label != "指定干员" else "") + "）")
    standard = {
        "charId": calc_ids[who], "name": who, "rarity": int(rarity), "releasedAt": op.get("onlineDate", ""),
        "wikiItemId": op.get("wikiItemId", ""), "obtain": op.get("obtain", ""),
        "chosenBy": "--char" if char_name else f"百科上线时间最新的已实装{ {'6': '六', '5': '五', '4': '四'}[rarity] }星",
        "weapon": {"id": wid_of[weapon["name"]], "name": weapon["name"], "releasedAt": weapon.get("onlineDate", ""),
                   "kind": weapon.get("kind", ""), "obtain": weapon.get("obtain", ""), "wikiItemId": weapon.get("wikiItemId", ""),
                   "reason": weapon_reason},
        "caliber": caliber, "footnote": footnote, "rows": rows,
    }
    return {
        "built": pulled_at,
        "games": [{
            "game": GAME, "gameId": GAME_ID, "caliber": caliber, "footnote": footnote, "source": SOURCE,
            "sections": list(SECTIONS), "lagMinutes": LAG_MINUTES, "lagNote": LAG_NOTE,
            "standard": standard["charId"], "standards": [standard], "rows": rows,
            "coverage": {
                "operator": who, "releasedAt": op.get("onlineDate", ""), "weapon": weapon["name"],
                "asOf": today, "universalCheckedOn": sorted(ref_rules),
                "releasedSixStars": [f"{r['name']} {r['onlineDate']}" for r in released],
                "upcoming": [f"{r['name']} {r['onlineDate']}（{r['dotType'] or '未标注'}）" for r in upcoming],
            },
        }],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--offline", type=Path, help="directory of saved responses; no network")
    ap.add_argument("--save-fixtures", type=Path, help="keep the (trimmed) responses in this directory")
    ap.add_argument("--char", default="", help="build for this operator instead of the newest six-star")
    ap.add_argument("--weapon", default="", help="weapon name (must be in the calculator); default: her signature weapon")
    ap.add_argument("--rarity", default="6", choices=("6", "5", "4"),
                    help="which rarity the newest operator is taken from (default 6)")
    ap.add_argument("--today", default="", help="server date YYYY-MM-DD to judge 'released' against (default: now, UTC+8)")
    ap.add_argument("-o", "--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args(argv)
    src = RulesSource(a.offline, a.save_fixtures)
    stamp = time.strftime("%Y-%m-%d %H:%M %Z")
    today = a.today or datetime.now(SERVER_TZ).strftime("%Y-%m-%d")
    if a.offline is not None:
        meta = a.offline / "pulled-at.txt"
        if meta.exists():
            stamp, _, saved_today = meta.read_text(encoding="utf-8").strip().partition("\t")
            today = a.today or saved_today or today
    elif a.save_fixtures is not None:
        a.save_fixtures.mkdir(parents=True, exist_ok=True)
        (a.save_fixtures / "pulled-at.txt").write_text(f"{stamp}\t{today}\n", encoding="utf-8")
    table = build(src, stamp, today, a.char, a.weapon, a.rarity)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    g = table["games"][0]
    st = g["standards"][0]
    print(f"✅ {a.out}: {st['name']}（{st['releasedAt'] or '?'} 上线）+ 专武 {st['weapon']['name']}，"
          f"{len(g['rows'])} rows，通用数核过 {len(g['coverage']['universalCheckedOn'])} 个六星，built {table['built']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
