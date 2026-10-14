"""The need table's trims: what each keeps of a live Skland / GitHub answer.

The relay runs these on every live answer of the daily build (needtable/build.py,
RulesSource.get / get_url); the offline tests read fixtures that were trimmed already, so
until 2026-10-14 no test ran them (the deploy's coverage gate: 9 new functions never
touched). Each case feeds an answer shaped like the live one, with the extra fields the
trim must drop, and checks exactly what is kept.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.features.needtable import build  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


cat = {"catalog": [{"typeSub": [
    {"name": "干员", "filterTagTree": [{"id": build.WEAPON_TAG_GROUP, "children": [{"id": "1", "name": "长柄"}]},
                                        {"id": "x", "children": [{"id": "9", "name": "无关"}]}],
     "items": [{"itemId": "100", "name": "明河", "publishedAtTs": 5, "cover": "url",
                "brief": {"dotType": 2, "subTypeList": [{"id": "1"}], "desc": "长"}}]},
    {"name": "物品", "items": [{"itemId": "7", "name": "折金票", "cover": "url", "brief": {}}]}]}]}
got = build.trim_catalog(cat)["catalog"][0]["typeSub"]
check("干员 keeps weapon tags, id/name/published/brief bits", got[0],
      {"name": "干员", "weaponTags": {"1": "长柄"}, "items": [
          {"itemId": "100", "name": "明河", "publishedAtTs": 5, "brief": {"dotType": 2, "subTypeList": [{"id": "1"}]}}]})
check("other subtypes only id -> name", got[1], {"name": "物品", "items": [{"itemId": "7", "name": "折金票"}]})

item = {"item": {"itemId": "2", "name": "X", "publishedAtTs": 3, "cover": "u", "document": {"a": [
    {"label": "上线时间", "value": "2026-11-05"}, {"label": "类型", "value": "材料"},
    {"label": "主要获取方式", "value": "采集"}, {"label": "别的", "value": "丢掉"}]}}}
check("wiki item keeps three attrs", build.trim_wiki_item(item),
      {"item": {"itemId": "2", "name": "X", "publishedAtTs": 3,
                "attrs": {"上线时间": "2026-11-05", "类型": "材料", "主要获取方式": "采集"}}})

doc = {"item": {"itemId": "5", "name": "D", "document": {
    "chapterGroup": [{"title": "武器信息", "widgets": [{"id": "w1", "title": "突破", "extra": 1}]}],
    "widgetCommonMap": {"w1": {"tabDataMap": {"t": {"content": "d1"}, "e": {"content": ""}}}, "w2": {"tabDataMap": {}}},
    "documentMap": {"d1": {"blockMap": {"b": {"text": {"inlineElements": [
        {"kind": "entry", "entry": {"id": 42, "count": "3", "showType": "card-big"}},
        {"kind": "entry", "entry": {"id": 43, "count": "1", "showType": "inline"}},
        {"kind": "text", "text": "说明"}]}}}},
        "d2": {"blockMap": {"b": {"text": {"inlineElements": []}}}}}}}}
check("wiki doc keeps chapters, widget tabs and big cards only", build.trim_wiki_doc(doc),
      {"item": {"itemId": "5", "name": "D", "document": {
          "chapterGroup": [{"title": "武器信息", "widgets": [{"id": "w1", "title": "突破"}]}],
          "widgetCommonMap": {"w1": {"tabDataMap": {"t": {"content": "d1"}}}},
          "documentMap": {"d1": {"cards": [{"id": "42", "count": 3}]}}}}})

check("search chars", build.trim_search_chars({"chars": [{"id": "a", "name": "N", "rarity": 6, "weaponType": 2, "x": 1}]}),
      {"chars": [{"id": "a", "name": "N", "rarity": 6, "weaponType": 2}]})
check("search weapons", build.trim_search_weapons({"weapons": [{"id": "w", "name": "唤月", "x": 1}]}),
      {"weapons": [{"id": "w", "name": "唤月"}]})
check("rules drop talents only", build.trim_rules({"chars": [{"id": "a", "talents": [1], "levels": [2]}], "weaponLevelRules": [3]}),
      {"chars": [{"id": "a", "levels": [2]}], "weaponLevelRules": [3]})
check("foresight keeps the top stage and weapon ids", build.trim_foresight(
    {"c1": {"rarity": 6, "weaponIds": ["w"], "stageMaterials": {"1": ["a"], "4": ["d"], "3": ["c"]}, "x": 1},
     "c2": {"stageMaterials": {}}}),
      {"c1": {"charId": "c1", "rarity": 6, "weaponIds": ["w"], "stageMaterials": {"4": ["d"]}},
       "c2": {"charId": "c2", "rarity": None, "weaponIds": [], "stageMaterials": {}}})
check("item names: only iconRecognition.name.item_*", build.trim_item_names(
    {"iconRecognition.name.item_gold": "折金票", "iconRecognition.name.other": "x", "ui.ok": "好"}),
      {"item_gold": "折金票"})
origin = {"item": {"itemId": "9", "name": "O", "document": {
    "chapterGroup": [{"title": build.ORIGIN_CHAPTER, "widgets": [{"id": "w"}]}, {"title": "别的", "widgets": [{"id": "v"}]}],
    "widgetCommonMap": {"w": {"tabDataMap": {"t": {"content": "c"}}}, "v": {"tabDataMap": {"t": {"content": "z"}}}},
    "documentMap": {"c": {"blockIds": ["b2", "b1"], "blockMap": {
        "b1": {"text": "采集：", "children": [{"text": "四号谷地"}]}, "b2": {"text": "  "}}},
        "z": {"blockMap": {"b": {"text": "不要"}}}}}}}
check("origin keeps the 物品来源 chapter's blocks in order", build.trim_wiki_origin(origin),
      {"itemId": "9", "name": "O", "lines": ["采集：四号谷地"]})

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
