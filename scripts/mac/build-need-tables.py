#!/usr/bin/env python3
"""Build `web/data/need.json`: what the **newest six-star operator's** full build
(with her signature weapon) needs, per material - already before her banner opens.

The phone page's 库存 tab shows, per material, 库存 | 单个角色满练所需 | 人份 (stock ÷
need). Stock is live (the page asks Skland itself, `web/inventory.js`); need is this
static table. The user's caliber (2026-09-19): one standard, the newest six-star in
the official wiki - **including one announced for a future date** - so the table
shows her materials before the banner. Nothing here runs on a timer; rerun it when a
six-star appears in the wiki, and again once the calculator lists her.

    python3 scripts/mac/build-need-tables.py                          # live -> web/data/need.json
    python3 scripts/mac/build-need-tables.py --save-fixtures DIR      # live, and keep the (trimmed) responses
    python3 scripts/mac/build-need-tables.py --offline DIR -o FILE    # rebuild from the saved responses
    python3 scripts/mac/build-need-tables.py --rarity 5               # the newest five-star instead
    python3 scripts/mac/build-need-tables.py --char 莱万汀 --weapon 熔铸火焰   # a named pair instead

Endfield only for now. The `games[]` layer is where 明日方舟 / 鸣潮 go later; inside a
game, `standards[]` holds the build standards (one today) and `rows` mirrors it.

## Who (official Skland wiki, `docs/SKLAND-API.md` §8)

1. `GET /web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true` - subtype 干员 and
   subtype 武器; rarity tag = `brief.subTypeList[subTypeId=10000].value` (`10006`
   six-star, `10005` five-star); `brief.dotType` `label_type_preview` = announced.
2. `GET /web/v1/wiki/item/info?id=<itemId>` - the entry's attributes: operators carry
   `上线时间` and `主要获取方式`, weapons those two and `类型`.
3. Newest = the latest `上线时间`, future dates included; `status` says 已实装 or
   未实装 against the server date.
4. Signature weapon = the six-star weapon with her `上线时间`, her `类型` (from
   `search-chars` `weaponType`) and `主要获取方式` 「武库交易所·限时特卖」 (熔铸火焰 for
   莱万汀, 寒夜幽影 for 提弗洛斯; the same-day 苦难的尽头 is battle-pass and is not chosen).
   Not exactly one -> the weapon is 待定 unless `--weapon` names it.

## Where the numbers come from, in order of preference

1. The calculator: `rules?charIds=<one id>` (breakthroughs + skills to 12, talents
   excluded) and `rules?weaponIds=<one id>`. Only listed after release.
2. The wiki entry itself: the 能力扩延 chapter's 精英化 and 战斗技能 widgets embed every
   material as an `entry` card (`{"kind":"entry","entry":{"id":<wiki item id>,"count":N}}`,
   names via the catalog's 物品 listings); the 天赋阵列 widget is left out, matching the
   caliber. For 提弗洛斯 these cards equal her rules number for number (checked
   2026-09-19). Weapons: the 武器总览 › 武器信息 widget, likewise equal to the rules.
3. The client's own preview table (`ForesightCharGrowthTable.json`, stage 4 = the full
   build, mirrored at github.com/rmxlinux/EndfieldData; item names from MaaEnd's
   `iconRecognition.name.*` strings). **Its 协议棱柱 / 协议棱柱组 / 折金票 include the talent
   tree**, which the caliber excludes - rows from it say so, and are replaced the moment
   source 1 or 2 has her.

Level-up gold and exp (1 -> 90) come with any `rules` response; they are read from
hers, else her weapon's, else the first listed weapon's (`coverage.sources.levels`).

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
# Third-party mirrors of client data, used only when neither the calculator nor the
# wiki entry has the operator's numbers yet (source 3 above).
FORESIGHT_URL = "https://raw.githubusercontent.com/rmxlinux/EndfieldData/main/TableCfg/ForesightCharGrowthTable.json"
ITEM_NAMES_URL = "https://raw.githubusercontent.com/MaaEnd/MaaEnd/v2/assets/locales/interface/zh_cn.json"

GAME, GAME_ID = "终末地", "endfield"
SOURCE = ("最新六星与其专武按森空岛百科的「上线时间」「类型」「主要获取方式」定；用量优先森空岛养成计算器 rules，"
          "计算器未收录时读百科词条里的养成材料卡片，两者都没有时读客户端预览表；名字和图标取自 material-list。"
          "方法见 docs/SKLAND-API.md §8")
MAX_SKILL_LEVEL = 12
EXP_CHAR, EXP_WEAPON = "exp:char", "exp:weapon"
RARITY_TAG = {"6": "10006", "5": "10005", "4": "10004"}   # brief.subTypeList[subTypeId=10000].value
SIGNATURE_OBTAIN = "武库交易所·限时特卖"
_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
SRC_CALC = "森空岛养成计算器 rules"
SRC_WIKI = "森空岛百科词条的养成材料卡片（上线前）"
SRC_FORESIGHT = "客户端预览表 ForesightCharGrowthTable（上线前，含天赋树用量）"
# Wiki chapters / widgets that hold the build materials, and the ones deliberately left out.
OP_CHAPTER, OP_WIDGETS = "能力扩延", ("精英化", "战斗技能")
WP_CHAPTER, WP_WIDGETS = "武器总览", ("武器信息",)

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
# The phone page's sections, in display order: a material family, not a standard, so
# the headings stay put when the standard changes. Rows without a section (the exp
# cards folded into the two exp rows) are not shown as rows.
SECTIONS = ("通用", "高阶素材", "采集", "经验与货币")
HIGH_TIER = {"D96钢样品四", "超距辉映管", "快子遴捡晶格", "象限拟合液", "三相纳米片", "高阶培养自选箱Ⅰ"}
LAG_MINUTES = 30
# The official calculator page's own words (game.skland.com/tools/endfield/cost-calculator,
# quoted in scripts/mac/lib/snapshot.py on 2026-08-28): 「仓库资源和干员数据等信息的同步，
# 会有 30 分钟左右的延迟」. Stated by Skland, not measured here.
LAG_NOTE = "森空岛的仓库数比游戏里晚约 30 分钟（官方养成计算器页面自己写的）"
# The preview table's lists that carry the full build (stage 4) and the talent-tainted ones.
FORESIGHT_LISTS = ("skNur", "skCol", "skPreItm", "skPreMat", "upAdv", "upCol", "upPre")
FORESIGHT_WITH_TALENTS = {"协议棱柱", "协议棱柱组", "折金票"}


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
    """Where responses come from: Skland live (plus the two mirrors), or a directory
    of saved ones. Wiki entries (`wiki-item-<id>`) share one fixture file,
    `wiki-items.json`, keyed by id; wiki documents (`wiki-doc-<id>`) likewise share
    `wiki-docs.json`."""

    MERGED = {"wiki-item-": "wiki-items.json", "wiki-doc-": "wiki-docs.json"}

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

    def _store(self, name: str, kept) -> None:
        if self.save is None:
            return
        self.save.mkdir(parents=True, exist_ok=True)
        for prefix, fname in self.MERGED.items():
            if name.startswith(prefix):
                p = self.save / fname
                allitems = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                allitems[name[len(prefix):]] = kept
                p.write_text(json.dumps(allitems, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                return
        (self.save / f"{name}.json").write_text(
            json.dumps(kept, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    def _load(self, name: str):
        for prefix, fname in self.MERGED.items():
            if name.startswith(prefix):
                p = self.offline / fname
                if not p.exists():
                    raise FileNotFoundError(f"fixture missing: {p}")
                d = json.loads(p.read_text(encoding="utf-8"))
                if name[len(prefix):] not in d:
                    raise KeyError(f"fixture {fname} has no entry {name}")
                return d[name[len(prefix):]]
        p = self.offline / f"{name}.json"
        if not p.exists():
            raise FileNotFoundError(f"fixture missing: {p}")
        return json.loads(p.read_text(encoding="utf-8"))

    def get(self, name: str, path: str, query: str = "", trim=None) -> dict:
        """One Skland response, by fixture name, in the trimmed shape `build()` reads
        (the same shape is what `--offline` reads back)."""
        if self.offline is not None:
            return self._load(name)
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
        # The trimmed shape is the one `build()` reads, live and offline alike.
        data = trim(d["data"]) if trim else d["data"]
        self._store(name, data)
        return data

    def get_url(self, name: str, url: str, trim=None) -> dict:
        """A plain JSON document from elsewhere (the client-data mirrors)."""
        if self.offline is not None:
            return self._load(name)

        def once():
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ark-need-table"}), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))

        data = _retry(once)
        data = trim(data) if trim else data
        self._store(name, data)
        return data


# ── trims: what each response is cut down to when saved as a fixture ──────────

def _catalog_items(d: dict, subtype: str) -> list[dict]:
    return next((s for s in d["catalog"][0]["typeSub"] if s["name"] == subtype), {"items": []})["items"]


def trim_catalog(d: dict) -> dict:
    """干员 and 武器 with their tags; every other subtype only as id -> name (the
    material cards in wiki documents point at 物品 / 贵重品库 entries by id)."""
    out = {"catalog": [{"typeSub": []}]}
    for sub in d["catalog"][0]["typeSub"]:
        if sub["name"] in ("干员", "武器"):
            out["catalog"][0]["typeSub"].append({"name": sub["name"], "items": [
                {"itemId": it["itemId"], "name": it["name"], "publishedAtTs": it.get("publishedAtTs"),
                 "brief": {"dotType": it["brief"].get("dotType"), "subTypeList": it["brief"].get("subTypeList", [])}}
                for it in sub["items"]]})
        else:
            out["catalog"][0]["typeSub"].append({"name": sub["name"], "items": [
                {"itemId": it["itemId"], "name": it["name"]} for it in sub["items"]]})
    return out


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


def trim_wiki_item(d: dict) -> dict:
    it = d.get("item") or {}
    a = wiki_attrs(it)
    return {"item": {"itemId": it.get("itemId"), "name": it.get("name"), "publishedAtTs": it.get("publishedAtTs"),
                     "attrs": {k: a[k] for k in ("上线时间", "主要获取方式", "类型") if k in a}}}


def trim_wiki_doc(d: dict) -> dict:
    """A wiki entry's document cut down to what `material_cards()` reads: the chapter
    -> widget titles, each widget's tab -> document ids, and each document's
    `entry` cards (wiki item id + count)."""
    doc = (d.get("item") or {}).get("document") or {}
    widgets = {}
    for wid, w in (doc.get("widgetCommonMap") or {}).items():
        tabs = {tab: v.get("content") for tab, v in (w.get("tabDataMap") or {}).items() if isinstance(v, dict) and v.get("content")}
        if tabs:
            widgets[wid] = {"tabDataMap": {tab: {"content": c} for tab, c in tabs.items()}}
    docs = {}
    for docid, dd in (doc.get("documentMap") or {}).items():
        cards = []
        for b in (dd.get("blockMap") or {}).values():
            if isinstance(b.get("text"), dict):
                for el in b["text"].get("inlineElements") or []:
                    if el.get("kind") == "entry" and (el.get("entry") or {}).get("showType") == "card-big":
                        cards.append({"id": str(el["entry"]["id"]), "count": int(el["entry"].get("count") or 0)})
        if cards:
            docs[docid] = {"cards": cards}
    return {"item": {"itemId": (d.get("item") or {}).get("itemId"), "name": (d.get("item") or {}).get("name"),
                     "document": {"chapterGroup": [{"title": g.get("title"), "widgets": [
                         {"id": w.get("id"), "title": w.get("title")} for w in g.get("widgets") or []]}
                         for g in doc.get("chapterGroup") or []],
                         "widgetCommonMap": widgets, "documentMap": docs}}}


def trim_search_chars(d: dict) -> dict:
    return {"chars": [{"id": c["id"], "name": c["name"], "rarity": c.get("rarity"), "weaponType": c.get("weaponType")}
                      for c in d.get("chars", [])]}


def trim_search_weapons(d: dict) -> dict:
    return {"weapons": [{"id": w["id"], "name": w["name"]} for w in d.get("weapons", [])]}


def trim_rules(d: dict) -> dict:
    """A rules response without `talents` (excluded from the caliber); the level
    tables stay, they are what gold / exp come from."""
    out = dict(d)
    out["chars"] = [{k: v for k, v in c.items() if k != "talents"} for c in d.get("chars", [])]
    return out


def trim_foresight(d: dict) -> dict:
    """Only the highest stage of every entry, plus its weapon ids."""
    out = {}
    for cid, e in d.items():
        st = e.get("stageMaterials") or {}
        top = str(max(int(k) for k in st)) if st else ""
        out[cid] = {"charId": e.get("charId", cid), "rarity": e.get("rarity"), "weaponIds": e.get("weaponIds") or [],
                    "stageMaterials": {top: st[top]} if top else {}}
    return out


def trim_item_names(d: dict) -> dict:
    """MaaEnd's `iconRecognition.name.<item id>` strings, for the preview table's ids."""
    return {k[len("iconRecognition.name."):]: v for k, v in d.items()
            if k.startswith("iconRecognition.name.item_")}


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


def wiki_item_names(src: RulesSource) -> dict[str, str]:
    """Every catalog entry's id -> name (the material cards point at 物品 ids)."""
    cat = src.get("wiki-catalog", "/web/v1/wiki/item/catalog", "typeMainId=1&onlyOnline=true", trim_catalog)
    return {str(it["itemId"]): it["name"] for sub in cat["catalog"][0]["typeSub"] for it in sub["items"]}


def newest(entries: list[dict]) -> tuple[dict, list[dict]]:
    """(the entry with the latest 上线时间 - future dates count -, all sorted newest-first)."""
    dated = sorted((e for e in entries if e["onlineDate"]),
                   key=lambda r: (r["onlineDate"], r["publishedAtTs"], r["name"]), reverse=True)
    if not dated:
        raise RuntimeError("no entry with an 上线时间")
    return dated[0], dated


def signature_weapon(weapons: list[dict], op: dict, weapon_type: str) -> dict | None:
    """The weapon sold in 限时特卖 on the operator's release day, of her weapon type;
    None unless exactly one."""
    hits = [w for w in weapons
            if w["onlineDate"] == op["onlineDate"] and w["kind"] == weapon_type and w["obtain"] == SIGNATURE_OBTAIN]
    return hits[0] if len(hits) == 1 else None


def material_cards(doc: dict, chapter: str, widgets: tuple[str, ...], names: dict[str, str]) -> Counter:
    """{material name: count} summed over the `entry` cards of the documents behind
    the named widgets of the named chapter; empty when the entry has no such cards."""
    d = (doc.get("item") or {}).get("document") or {}
    wcm = d.get("widgetCommonMap") or {}
    dm = d.get("documentMap") or {}
    out: Counter = Counter()
    for grp in d.get("chapterGroup") or []:
        if grp.get("title") != chapter:
            continue
        for w in grp.get("widgets") or []:
            if w.get("title") not in widgets:
                continue
            for tab in ((wcm.get(w["id"]) or {}).get("tabDataMap") or {}).values():
                docid = tab.get("content") if isinstance(tab, dict) else None
                for card in (dm.get(docid) or {}).get("cards") or []:
                    out[names.get(card["id"], f"?{card['id']}")] += int(card["count"])
    return out


def foresight_need(entry: dict, item_names: dict[str, str]) -> tuple[Counter, int]:
    """{material name: count} and gold from the preview table's highest stage."""
    stages = entry["stageMaterials"]
    st = stages[str(max(int(k) for k in stages))]
    need, gold = Counter(), 0
    for key in FORESIGHT_LISTS:
        for iid, cnt in zip(st.get(key + "Ids", []), st.get(key + "Cnt", [])):
            nm = item_names.get(iid)
            if not nm:
                raise RuntimeError(f"preview-table item id without a name: {iid}")
            need[nm] += int(cnt)
    for key in ("skGold", "upGold"):
        for iid, cnt in zip(st.get(key + "Ids", []), st.get(key + "Cnt", [])):
            if item_names.get(iid) == "折金票":
                gold += int(cnt)
    return need, gold


def by_name_to_ids(counts: Counter, mat: dict[str, dict]) -> Counter:
    ids = {m["name"]: mid for mid, m in mat.items()}
    out: Counter = Counter()
    for nm, c in counts.items():
        if nm == "折金票":
            continue
        if nm not in ids:
            raise RuntimeError(f"material named in the source but not in material-list: {nm}")
        out[ids[nm]] += c
    return out


def build(src: RulesSource, pulled_at: str, today: str, char_name: str = "", weapon_name: str = "",
          rarity: str = "6") -> dict:
    mat = material_table(src.get("material-list", "/web/v1/game/endfield/calculate/material-list"))
    listed = src.get("search-chars", "/web/v1/game/endfield/search-chars", "", trim_search_chars)["chars"]
    calc_ids = {c["name"]: c["id"] for c in listed}
    weapon_types = {c["name"]: str(((c.get("weaponType") or {}).get("value")) or "") for c in listed}
    weapons_listed = src.get("search-weapons", "/web/v1/game/endfield/search-weapons", "", trim_search_weapons)["weapons"]
    wid_of = {w["name"]: w["id"] for w in weapons_listed}
    wnames = wiki_item_names(src)

    # 1. who, and her signature weapon - both from the official wiki
    ops = wiki_entries(src, "干员", rarity)
    top, ranked = newest(ops)
    who = char_name or top["name"]
    op = next((e for e in ops if e["name"] == who), None) or {"name": who, "wikiItemId": "", "onlineDate": "", "obtain": "", "dotType": ""}
    status = "已实装" if op["onlineDate"] and op["onlineDate"] <= today else "未实装"
    wtype = weapon_types.get(who, "")
    weapon: dict | None
    if weapon_name:
        weapon, weapon_reason = {"name": weapon_name, "wikiItemId": "", "onlineDate": "", "obtain": "", "kind": ""}, "--weapon"
    else:
        weapon = signature_weapon(wiki_entries(src, "武器", rarity), op, wtype)
        if weapon:
            weapon_reason = f"百科：与 {who} 同日（{op['onlineDate']}）上线、同为{wtype}、主要获取方式「{SIGNATURE_OBTAIN}」的唯一一把"
        elif not wtype:
            weapon_reason = f"计算器还没收录 {who}，拿不到她的武器类型；百科词条也不写类型，专武等她收录后再定"
        else:
            weapon_reason = f"百科里没有与 {who} 同日上线、同为{wtype}、「{SIGNATURE_OBTAIN}」的六星武器"

    # 2. her numbers: calculator -> wiki cards -> client preview table
    sources = {}
    need_by_id: Counter
    op_gold: int
    need_note = {}
    lv = None
    if who in calc_ids:
        rule = src.get(f"rules-char-{calc_ids[who]}", "/web/v1/game/endfield/calculate/rules", f"charIds={calc_ids[who]}", trim_rules)
        need_by_id, op_gold = char_need(rule)
        lv = rule
        sources["need"] = SRC_CALC
    else:
        cards = Counter()
        if op.get("wikiItemId"):
            doc = src.get(f"wiki-doc-{op['wikiItemId']}", "/web/v1/wiki/item/info", f"id={op['wikiItemId']}", trim_wiki_doc)
            cards = material_cards(doc, OP_CHAPTER, OP_WIDGETS, wnames)
        if cards:
            need_by_id, op_gold = by_name_to_ids(cards, mat), cards.get("折金票", 0)
            sources["need"] = SRC_WIKI
        else:
            fs = src.get_url("client-foresight", FORESIGHT_URL, trim_foresight)
            names = src.get_url("client-item-names", ITEM_NAMES_URL, trim_item_names)
            entry = next((e for e in fs.values() if names.get(e.get("charId")) == who), None)
            if entry is None:
                # The preview table keys by internal code (chr_0038_purrche); MaaEnd's
                # strings name items, not operators. Match by the only entry whose
                # rarity fits when there is one, else give up loudly.
                cands = [e for e in fs.values() if str(e.get("rarity")) == rarity]
                if len(cands) != 1:
                    raise RuntimeError(f"{who}: not in the calculator, no material cards in the wiki entry, "
                                       f"and the preview table has {len(cands)} {rarity}-star entries - cannot pick hers")
                entry = cands[0]
            by_name, op_gold = foresight_need(entry, names)
            need_by_id = by_name_to_ids(by_name, mat)
            sources["need"] = SRC_FORESIGHT
            sources["foresightCharId"] = entry.get("charId", "")
            need_note = {nm: "预览表的数含天赋树" for nm in FORESIGHT_WITH_TALENTS}

    # 3. the weapon's numbers: calculator -> wiki cards -> 待定
    wneed: Counter = Counter()
    w_gold = 0
    weapon_status = "待定"
    if weapon and weapon["name"] in wid_of:
        wrule = src.get(f"rules-weapon-{wid_of[weapon['name']]}", "/web/v1/game/endfield/calculate/rules",
                        f"weaponIds={wid_of[weapon['name']]}", trim_rules)
        wneed, w_gold = weapon_need(wrule)
        lv = lv or wrule
        sources["weapon"], weapon_status = SRC_CALC, "已收录"
    elif weapon and weapon.get("wikiItemId"):
        doc = src.get(f"wiki-doc-{weapon['wikiItemId']}", "/web/v1/wiki/item/info", f"id={weapon['wikiItemId']}", trim_wiki_doc)
        cards = material_cards(doc, WP_CHAPTER, WP_WIDGETS, wnames)
        if cards:
            wneed, w_gold = by_name_to_ids(cards, mat), cards.get("折金票", 0)
            sources["weapon"], weapon_status = SRC_WIKI, "百科卡片"
    if weapon_status == "待定":
        sources["weapon"] = "待定：" + (f"{weapon['name']} 既不在计算器里也没有百科材料卡片" if weapon else weapon_reason)
    if lv is None:
        # Level-up gold / exp are the same table in every rules response; take them
        # from the first listed weapon when neither hers nor her weapon's is available.
        first = weapons_listed[0]
        lv = src.get(f"rules-weapon-{first['id']}", "/web/v1/game/endfield/calculate/rules", f"weaponIds={first['id']}", trim_rules)
        sources["levels"] = f"{SRC_CALC}（等级表取自 {first['name']} 的应答，各角色相同）"
    else:
        sources["levels"] = SRC_CALC
    char_gold, char_exp = level_totals(lv["charLevelRules"])
    weap_gold, weap_exp = level_totals(lv["weaponLevelRules"])
    gold_total = op_gold + char_gold + w_gold + weap_gold
    who_group = who
    weapon_group = f"专武 {weapon['name']}" if weapon else "专武（待定）"

    # 4. rows: every material, with this build's need (0 when the build does not use it)
    rows = []
    for mid, m in mat.items():
        nm = m["name"]
        row = {"id": mid, "name": nm, "rarity": m["rarity"], "icon": m["icon"], "need": 0, "group": None,
               "section": section_of(nm, m["kind"]),
               "stage": STAGE.get(nm) or (GATHER if nm in GATHERED else None), "note": need_note.get(nm)}
        c, w = need_by_id.get(mid, 0), wneed.get(mid, 0)
        if m["kind"] != "materials":
            row.update(need=None, exp=m["exp"], sumInto=EXP_CHAR if m["kind"] == "charExpMaterials" else EXP_WEAPON,
                       stage="干员经验" if m["kind"] == "charExpMaterials" else "武器经验")
        elif nm == "折金票":
            row.update(need=gold_total, group=f"{who_group} + {weapon_group}",
                       note=("；".join(x for x in (row["note"], f"干员 {op_gold + char_gold:,} + 专武 {w_gold + weap_gold:,}") if x)))
        elif c and w:
            row.update(need=c + w, group=f"{who_group} + {weapon_group}", note=f"干员 {c} + 专武 {w}")
        elif c:
            row.update(need=c, group=who_group)
        elif w:
            row.update(need=w, group=weapon_group)
        elif nm == "高阶培养自选箱Ⅰ":
            row.update(need=None, note="开出任意一种高阶素材，不计入人份")
        else:
            row["note"] = f"{who} 的满练不用它"
        rows.append(row)
    rows.append({"id": EXP_CHAR, "name": "干员经验", "rarity": None, "icon": "", "need": char_exp, "group": who_group,
                 "section": "经验与货币", "stage": "干员经验", "virtual": True, "note": "五种作战记录 / 认知载体按经验值折算"})
    rows.append({"id": EXP_WEAPON, "name": "武器经验", "rarity": None, "icon": "", "need": weap_exp, "group": weapon_group,
                 "section": "经验与货币", "stage": "武器经验", "virtual": True, "note": "武器检查套组 / 装置 / 单元按经验值折算"})
    sec = {name: i for i, name in enumerate(SECTIONS)}
    rows.sort(key=lambda r: (sec.get(r["section"], len(SECTIONS)), 2 if r["need"] is None else 1 if r["need"] == 0 else 0,
                             -(r["need"] or 0), r["name"]))

    label = {"6": "最新六星", "5": "最新五星", "4": "最新四星"}[rarity] if who == top["name"] and not char_name else "指定干员"
    online = f"（{op['onlineDate']} 上线）" if op.get("onlineDate") else ""
    wlabel = f"专武 {weapon['name']}" if weapon else "专武待定"
    caliber = f"{label} {who}{online}：1→90 全突破、四技能 12、{wlabel} 1→90；不含天赋"
    footnote = (f"人份 = 库存 ÷ {who}满练所需（1→90 全突破、四技能 12、{wlabel} 1→90，不含天赋"
                + (f"；{op['onlineDate']} 上线的{label}" if op.get("onlineDate") and label != "指定干员" else "") + "）")
    if sources["need"] == SRC_FORESIGHT:
        footnote += "（上线前按客户端预览表，棱柱和折金票含天赋树）"
    standard = {
        "charId": calc_ids.get(who, ""), "name": who, "rarity": int(rarity), "releasedAt": op.get("onlineDate", ""),
        "status": status, "wikiItemId": op.get("wikiItemId", ""), "obtain": op.get("obtain", ""), "dotType": op.get("dotType", ""),
        "chosenBy": "--char" if char_name else f"百科上线时间最新的{ {'6': '六', '5': '五', '4': '四'}[rarity] }星（含未实装）",
        "weapon": ({"id": wid_of.get(weapon["name"], ""), "name": weapon["name"], "releasedAt": weapon.get("onlineDate", ""),
                    "kind": weapon.get("kind", ""), "obtain": weapon.get("obtain", ""), "wikiItemId": weapon.get("wikiItemId", ""),
                    "status": weapon_status, "reason": weapon_reason} if weapon else
                   {"id": "", "name": "", "status": "待定", "reason": weapon_reason}),
        "sources": sources, "caliber": caliber, "footnote": footnote, "rows": rows,
    }
    return {
        "built": pulled_at,
        "games": [{
            "game": GAME, "gameId": GAME_ID, "caliber": caliber, "footnote": footnote, "source": SOURCE,
            "sections": list(SECTIONS), "lagMinutes": LAG_MINUTES, "lagNote": LAG_NOTE,
            "standard": standard["charId"] or standard["wikiItemId"], "standards": [standard], "rows": rows,
            "coverage": {
                "operator": who, "releasedAt": op.get("onlineDate", ""), "status": status,
                "weapon": weapon["name"] if weapon else "", "weaponStatus": weapon_status, "asOf": today, "sources": sources,
                "candidates": [f"{r['name']} {r['onlineDate']}{'（未实装）' if r['onlineDate'] > today else ''}" for r in ranked],
            },
        }],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--offline", type=Path, help="directory of saved responses; no network")
    ap.add_argument("--save-fixtures", type=Path, help="keep the (trimmed) responses in this directory")
    ap.add_argument("--char", default="", help="build for this operator instead of the newest")
    ap.add_argument("--weapon", default="", help="weapon name (must be in the calculator); default: her signature weapon")
    ap.add_argument("--rarity", default="6", choices=("6", "5", "4"), help="which rarity the newest operator is taken from (default 6)")
    ap.add_argument("--today", default="", help="server date YYYY-MM-DD for the 已实装/未实装 label (default: now, UTC+8)")
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
    print(f"✅ {a.out}: {st['name']}（{st['releasedAt'] or '?'} 上线，{st['status']}）+ {st['weapon']['name'] or '专武待定'}"
          f"（{st['weapon']['status']}），用量来自 {st['sources']['need']}，{len(g['rows'])} rows，built {table['built']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
