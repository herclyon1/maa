#!/usr/bin/env python3
"""Build `web/data/need.json`: what the **newest five-star operator's** full build
needs, per material.

The phone page's 库存 tab shows, per material, 库存 | 单个角色满练所需 | 人份 (stock ÷
need). Stock is live (the page asks Skland itself, `web/inventory.js`); need is this
static table. The user's caliber (2026-09-18): the older operators are all built, so
the need is that of **the newest five-star only** - not an average, not a maximum.
Nothing here runs on a timer; rerun it when a new five-star appears.

    python3 scripts/mac/build-need-tables.py                          # live -> web/data/need.json
    python3 scripts/mac/build-need-tables.py --save-fixtures DIR      # live, and keep the raw responses
    python3 scripts/mac/build-need-tables.py --offline DIR -o FILE    # rebuild from saved responses
    python3 scripts/mac/build-need-tables.py --char 赛希               # a named operator instead of the newest

Endfield only for now. The `games[]` layer is where 明日方舟 / 鸣潮 go later.

## Who is "the newest five-star" (official, `docs/SKLAND-API.md` §8)

1. `GET /web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true` - the official wiki's
   character catalog; the rarity tag is `brief.subTypeList[subTypeId=10000].value`
   (`10005` = five-star, `10006` = six-star, `10004` = four-star).
2. `GET /web/v1/wiki/item/info?id=<itemId>` for each five-star - the entry's
   attribute table carries `上线时间` (e.g. 「2026年9月24日」) and `主要获取方式`.
   The newest 上线时间 wins; the account's ownership plays no part.

## Where the numbers come from

* Universal part (identical for every operator, checked here across every five-star
  the calculator knows): `calculate/rules?charIds=<one id>` - `breakthroughs[]` +
  `skills[].levels[]` up to level 12, plus `charLevelRules` 1 -> 90. Talents excluded
  (the scope of `docs/ENDFIELD-SANITY-YIELD.md` §B).
* The operator's own choices (which two high-tier materials at 116, which one at 20,
  which leaf at 84, which mushroom at 8): from her `rules?charIds=` once the
  calculator lists her (`search-chars`). **Before release the calculator does not
  know her** (2026-09-18: 噗切娜 is `label_type_preview`, `search-chars` has 32
  operators and none is she, and `rules` for her derived id answers `chars: []`).
  Then `--foresight FILE` supplies the client's own preview table
  (`ForesightCharGrowthTable.json`, stage 4 = the full build) and `--item-names FILE`
  maps its item ids to names; the amounts are cross-checked against the universal
  structure (116 / 116 / 20 / 84 / 8).
* Weapon: `--weapon NAME` if given; else the first weapon of the foresight entry's
  `weaponIds` that the calculator knows (`rules?weaponIds=`, id = md5 of the internal
  code - verified on 12 known ids); else the weapon the account has on her. Universal
  weapon rows are identical for every weapon (50 / 23 / 5 / 5 / 3); a weapon adds one
  high-tier material at 16 and one ore at 8.
* `calculate/material-list` for names, rarity, icon and exp value of all 40 materials.

## Read-off traps (each pinned by `relay/tests/test_need_table.py`)

* `charLevelRules[89]` (level 90) is `gold: "-1", exp: "-1"`: a sentinel, not a cost.
* `material-list` names carried a trailing newline on 2026-08-28. Always `strip()`.
* A material the account holds none of is absent from `itemCount`, not 0.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "relay"))

ZONAI = "https://zonai.skland.com"
ENV = Path.home() / ".config/ark/.env"
OUT_DEFAULT = REPO / "web" / "data" / "need.json"
FIXTURES = REPO / "relay" / "tests" / "fixtures" / "skland-endfield"

GAME, GAME_ID = "终末地", "endfield"
SOURCE = ("最新五星按森空岛百科的「上线时间」定；用量按森空岛养成计算器 rules 逐项求和"
          "（计算器还没收录她时，她选哪几种素材按客户端预览表 ForesightCharGrowthTable）；"
          "名字和图标取自 material-list。方法见 docs/SKLAND-API.md §8")
MAX_SKILL_LEVEL = 12
EXP_CHAR, EXP_WEAPON = "exp:char", "exp:weapon"
FIVE_STAR_TAG = "10005"       # brief.subTypeList[subTypeId=10000].value in the wiki catalog
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
UNIVERSAL_LEAVES = {"晶化多齿叶", "纯晶多齿叶", "至晶多齿叶"}
UNIVERSAL_SHROOMS = {"轻红柱状菌", "中红柱状菌", "重红柱状菌"}
WEAPON_UNIVERSAL = {"重型强固模具", "强固模具", "中黯石", "重黯石", "轻黯石"}
# The foresight table's stage-4 lists that hold the operator's own choices.
FORESIGHT_CHOICE_LISTS = ("skPreMat", "upPre", "skCol", "upCol")
# Two high-tier materials at 116, one at 20, one leaf at 84, one mushroom at 8: the
# shape every five-star's rules give (docs/ENDFIELD-SANITY-YIELD.md §B).
CHOICE_SHAPE = Counter({116: 2, 20: 1, 84: 1, 8: 1})


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


def calc_id(internal_code: str) -> str:
    """The calculator's 32-hex id is md5 of the client's internal code
    (`chr_0006_wolfgd` -> 26e3cc73…, `wpn_sword_0006` -> 熔铸火焰; 12 checked)."""
    return hashlib.md5(internal_code.encode()).hexdigest()


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
            self.role = skland.endfield_role(self.cred)

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
            kept = trim(data) if trim else data
            (self.save / f"{name}.json").write_text(
                json.dumps(kept, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return data


# ── trims: what each response is cut down to when saved as a fixture ──────────

def trim_catalog(d: dict) -> dict:
    chars = next((s for s in d["catalog"][0]["typeSub"] if s["name"] == "干员"), {"items": []})
    return {"catalog": [{"typeSub": [{"name": "干员", "items": [
        {"itemId": it["itemId"], "name": it["name"], "publishedAtTs": it.get("publishedAtTs"),
         "brief": {"dotType": it["brief"].get("dotType"), "subTypeList": it["brief"].get("subTypeList", [])}}
        for it in chars["items"]]}]}]}


def wiki_attrs(item: dict) -> dict:
    """The label/value attribute table of a wiki entry (上线时间, 主要获取方式, …)."""
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


def trim_wiki_item(d: dict) -> dict:
    it = d.get("item") or {}
    a = wiki_attrs(it)
    return {"item": {"itemId": it.get("itemId"), "name": it.get("name"), "publishedAtTs": it.get("publishedAtTs"),
                     "attrs": {k: a[k] for k in ("上线时间", "主要获取方式") if k in a}}}


def trim_search_chars(d: dict) -> dict:
    return {"chars": [{"id": c["id"], "name": c["name"], "rarity": c.get("rarity")} for c in d.get("chars", [])]}


def trim_search_weapons(d: dict) -> dict:
    return {"weapons": [{"id": w["id"], "name": w["name"]} for w in d.get("weapons", [])]}


def trim_card(d: dict) -> dict:
    return {"detail": {"chars": [
        {"id": c["id"], "charData": {"name": c["charData"]["name"], "rarity": c["charData"]["rarity"]},
         "weapon": {"weaponData": {k: v for k, v in ((c.get("weapon") or {}).get("weaponData") or {}).items()
                                   if k in ("id", "name")}}}
        for c in d["detail"]["chars"]]}}


def trim_rules(d: dict) -> dict:
    """A rules response without `talents`; the two 90-row level tables stay (7 KB)."""
    out = dict(d)
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


def newest_five_star(src: RulesSource) -> dict:
    """{name, wikiItemId, onlineDate, obtain, dotType, candidates} of the five-star
    with the latest 上线时间 in the official wiki. Ties (the launch roster all say
    2026-01-22) are broken by the entry's publish time, then by name."""
    cat = src.get("wiki-catalog", "/web/v1/wiki/item/catalog", "typeMainId=1&onlyOnline=true", trim_catalog)
    chars = next(s for s in cat["catalog"][0]["typeSub"] if s["name"] == "干员")["items"]
    fives = [it for it in chars
             if any(x.get("subTypeId") == "10000" and x.get("value") == FIVE_STAR_TAG
                    for x in it["brief"].get("subTypeList", []))]
    if not fives:
        raise RuntimeError("the wiki catalog lists no five-star operator")
    rows = []
    for it in fives:
        info = src.get(f"wiki-item-{it['itemId']}", "/web/v1/wiki/item/info", f"id={it['itemId']}", trim_wiki_item)
        item = info.get("item") or {}
        attrs = item.get("attrs") or wiki_attrs(item)
        rows.append({"name": it["name"], "wikiItemId": str(it["itemId"]),
                     "onlineDate": parse_online_date(attrs.get("上线时间", "")),
                     "onlineText": attrs.get("上线时间", ""), "obtain": attrs.get("主要获取方式", ""),
                     "dotType": it["brief"].get("dotType") or "",
                     "publishedAtTs": int(it.get("publishedAtTs") or 0)})
    rows.sort(key=lambda r: (r["onlineDate"], r["publishedAtTs"], r["name"]), reverse=True)
    top = dict(rows[0])
    top["candidates"] = [f"{r['name']} {r['onlineDate'] or '?'}" for r in rows]
    top["all"] = rows
    return top


def foresight_choices(entry: dict, item_names: dict) -> dict[str, int]:
    """{material name: count} of the operator's own choices at the full build (the
    highest stage): high-tier materials for skills (skPreMat) and breakthroughs
    (upPre), the leaf beyond the three universal 多齿叶 (skCol) and the mushroom
    beyond the three universal 红柱状菌 (upCol)."""
    stages = entry["stageMaterials"]
    st = stages[str(max(int(k) for k in stages))]
    out: dict[str, int] = {}
    for key in FORESIGHT_CHOICE_LISTS:
        for iid, cnt in zip(st.get(key + "Ids", []), st.get(key + "Cnt", [])):
            nm = item_names.get(iid)
            if not nm:
                raise RuntimeError(f"foresight item id without a name: {iid} (add it to the item-names map)")
            if (key == "skCol" and nm in UNIVERSAL_LEAVES) or (key == "upCol" and nm in UNIVERSAL_SHROOMS):
                continue
            out[nm] = out.get(nm, 0) + int(cnt)
    return out


def foresight_entry(fs: dict, who: str, item_names: dict) -> dict:
    """The entry whose charId names `who`, or the only entry in the file."""
    for cid, e in fs.items():
        if item_names.get(cid) == who or (e.get("name") or {}).get("text") == who:
            return e
    if len(fs) == 1:
        return next(iter(fs.values()))
    raise RuntimeError(f"no foresight entry for {who} among {sorted(fs)}")


def build(src: RulesSource, pulled_at: str, char_name: str = "", weapon_name: str = "",
          foresight: Path | None = None, item_names: Path | None = None) -> dict:
    mat = material_table(src.get("material-list", "/web/v1/game/endfield/calculate/material-list"))
    listed = src.get("search-chars", "/web/v1/game/endfield/search-chars", "", trim_search_chars)["chars"]
    calc_ids = {c["name"]: c["id"] for c in listed}
    five_ids = {c["name"]: c["id"] for c in listed if str((c.get("rarity") or {}).get("value")) == "5"}

    # 1. who
    newest = newest_five_star(src)
    who = char_name or newest["name"]
    target = dict(next((r for r in newest["all"] if r["name"] == who), {"name": who}))
    target["candidates"] = newest["candidates"]
    target["chosenBy"] = "--char" if char_name else "官方百科上线时间最新"

    # 2. the universal part, from every five-star the calculator knows
    ref_rules = {nm: src.get(f"rules-char-{cid}", "/web/v1/game/endfield/calculate/rules", f"charIds={cid}", trim_rules)
                 for nm, cid in five_ids.items()}
    if not ref_rules:
        raise RuntimeError("search-chars lists no five-star; nothing to take the universal numbers from")
    needs = {nm: char_need(r) for nm, r in ref_rules.items()}
    golds = {g for _, g in needs.values()}
    if len(golds) != 1:
        raise RuntimeError(f"breakthrough/skill gold differs between five-stars: {golds}")
    op_gold = golds.pop()
    all_ids = set().union(*[n.keys() for n, _ in needs.values()])
    universal = {mid for mid in all_ids if len({n.get(mid, 0) for n, _ in needs.values()}) == 1}
    uni_counts = {mid: next(iter(needs.values()))[0][mid] for mid in universal}
    any_rule = next(iter(ref_rules.values()))
    char_gold, char_exp = level_totals(any_rule["charLevelRules"])
    weap_gold, weap_exp = level_totals(any_rule["weaponLevelRules"])

    # 3. the operator's own choices
    own: dict[str, int] = {}
    weapon_codes: list[str] = []
    if who in calc_ids:
        rule = ref_rules.get(who) or src.get(f"rules-char-{calc_ids[who]}", "/web/v1/game/endfield/calculate/rules",
                                             f"charIds={calc_ids[who]}", trim_rules)
        need, _ = char_need(rule)
        own = {mat[mid]["name"]: c for mid, c in need.items() if mid not in universal}
        target["calculator"] = "已收录"
    else:
        if foresight is None or item_names is None:
            raise RuntimeError(f"{who} is not in the calculator yet (search-chars); pass --foresight and --item-names")
        fs = json.loads(foresight.read_text(encoding="utf-8"))
        names = json.loads(item_names.read_text(encoding="utf-8"))
        entry = foresight_entry(fs, who, names)
        own = foresight_choices(entry, names)
        weapon_codes = list(entry.get("weaponIds") or [])
        target["calculator"] = "未收录"
        target["foresightCharId"] = entry.get("charId", "")
    if Counter(own.values()) != CHOICE_SHAPE:
        raise RuntimeError(f"{who}'s choices do not fit the 116/116/20/84/8 shape: {own}")

    # 4. the weapon
    weapons_listed = src.get("search-weapons", "/web/v1/game/endfield/search-weapons", "", trim_search_weapons)["weapons"]
    wname_of = {w["id"]: w["name"] for w in weapons_listed}
    wid_of = {w["name"]: w["id"] for w in weapons_listed}
    weapon_id, weapon_reason, pending = "", "", []
    if weapon_name:
        weapon_id, weapon_reason = wid_of.get(weapon_name, ""), "--weapon"
        if not weapon_id:
            raise RuntimeError(f"weapon {weapon_name} is not in the calculator (search-weapons)")
    for code in weapon_codes:
        if weapon_id:
            break
        wid = calc_id(code)
        if wid in wname_of:
            weapon_id, weapon_name = wid, wname_of[wid]
            weapon_reason = f"客户端预览表给她推荐的武器里，计算器已收录的第一把（{code}）"
        else:
            pending.append(code)
    if not weapon_id:
        card = src.get("card", "/api/v1/game/endfield/card/detail",
                       f"roleId={src.role[0]}&serverId={src.role[1]}" if src.cred else "", trim_card)
        for c in card["detail"]["chars"]:
            wd = (c.get("weapon") or {}).get("weaponData") or {}
            if c["charData"]["name"] == who and wd.get("id"):
                weapon_id, weapon_name, weapon_reason = wd["id"], wd.get("name", ""), "账号里她当前装备的武器"
    if not weapon_id:
        raise RuntimeError(f"no weapon for {who}: pass --weapon")
    wrule = src.get(f"rules-weapon-{weapon_id}", "/web/v1/game/endfield/calculate/rules", f"weaponIds={weapon_id}")
    wneed, w_gold = weapon_need(wrule)
    wneed_by_name = {mat[mid]["name"]: c for mid, c in wneed.items()}
    gold_total = op_gold + char_gold + w_gold + weap_gold

    # 5. rows: every material, with this build's need (0 when the build does not use it)
    rows = []
    for mid, m in mat.items():
        nm = m["name"]
        row = {"id": mid, "name": nm, "rarity": m["rarity"], "icon": m["icon"], "need": 0, "group": None,
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
            row.update(need=own[nm] + w, group=who, note=(f"干员 {own[nm]} + 武器 {w}" if w else None))
        elif w and nm in WEAPON_UNIVERSAL:
            row.update(need=w, group="通用")
        elif w:
            row.update(need=w, group=f"武器 {weapon_name}")
        elif nm == "高阶培养自选箱Ⅰ":
            row.update(need=None, note="开出任意一种高阶素材，不计入人份")
        else:
            row["note"] = f"{who} 的满练不用它"
        rows.append(row)
    rows.append({"id": EXP_CHAR, "name": "干员经验", "rarity": None, "icon": "", "need": char_exp, "group": "通用",
                 "stage": "干员经验", "virtual": True, "note": "五种作战记录 / 认知载体按经验值折算"})
    rows.append({"id": EXP_WEAPON, "name": "武器经验", "rarity": None, "icon": "", "need": weap_exp, "group": "通用",
                 "stage": "武器经验", "virtual": True, "note": "武器检查套组 / 装置 / 单元按经验值折算"})
    order = {"通用": 0, who: 1, f"武器 {weapon_name}": 2}
    rows.sort(key=lambda r: (4 if r["need"] is None else 3 if r["need"] == 0 else order.get(r["group"], 3),
                             -(r["need"] or 0), r["name"]))

    online = f"（{target['onlineDate']} 上线）" if target.get("onlineDate") else ""
    label = "最新五星" if who == newest["name"] else "指定干员"
    caliber = f"{label} {who}{online}：1→90 全突破、四技能 12、武器 {weapon_name} 1→90；不含天赋"
    return {
        "built": pulled_at,
        "games": [{
            "game": GAME, "gameId": GAME_ID, "caliber": caliber, "source": SOURCE,
            "coverage": {
                "operator": who, "wikiItemId": target.get("wikiItemId", ""), "onlineDate": target.get("onlineDate", ""),
                "obtain": target.get("obtain", ""), "chosenBy": target["chosenBy"],
                "calculator": target.get("calculator", ""), "foresightCharId": target.get("foresightCharId", ""),
                "candidates": target["candidates"], "universalCheckedOn": sorted(ref_rules),
                "weapon": weapon_name, "weaponReason": weapon_reason,
                "weaponsPending": [f"{c}（计算器未收录）" for c in pending],
            },
            "rows": rows,
        }],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--offline", type=Path, help="directory of saved responses; no network")
    ap.add_argument("--save-fixtures", type=Path, help="keep the (trimmed) responses in this directory")
    ap.add_argument("--char", default="", help="build for this operator instead of the newest five-star")
    ap.add_argument("--weapon", default="", help="weapon name (must be in the calculator)")
    ap.add_argument("--foresight", type=Path, default=FIXTURES / "foresight-chr_0038_purrche.json",
                    help="client ForesightCharGrowthTable entry, used only when the calculator does not list the operator")
    ap.add_argument("--item-names", type=Path, default=FIXTURES / "item-names.json",
                    help="client item id -> name map for --foresight")
    ap.add_argument("-o", "--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args(argv)
    src = RulesSource(a.offline, a.save_fixtures)
    stamp = time.strftime("%Y-%m-%d %H:%M %Z")
    if a.offline is not None:
        meta = a.offline / "pulled-at.txt"
        stamp = meta.read_text(encoding="utf-8").strip() if meta.exists() else stamp
    elif a.save_fixtures is not None:
        a.save_fixtures.mkdir(parents=True, exist_ok=True)
        (a.save_fixtures / "pulled-at.txt").write_text(stamp + "\n", encoding="utf-8")
    table = build(src, stamp, a.char, a.weapon, a.foresight, a.item_names)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cov = table["games"][0]["coverage"]
    print(f"✅ {a.out}: {cov['operator']}（{cov['onlineDate'] or '?'} 上线，计算器{cov['calculator']}），"
          f"武器 {cov['weapon']}，{len(table['games'][0]['rows'])} rows，built {table['built']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
