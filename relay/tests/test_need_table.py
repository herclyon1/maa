"""The need table behind the phone page's 库存 tab is the newest six-star's build
with her signature weapon, it can be built before her banner opens, and the committed
web/data/need.json still says the same.

`scripts/mac/build-need-tables.py --offline` runs over the saved responses in
fixtures/skland-endfield (pulled 2026-09-19 00:47 JST, judged as of 2026-09-18): the
official wiki catalog, the wiki entries of every six- and five-star operator and
every six-star weapon (上线时间 / 类型 / 主要获取方式), three wiki documents cut down to
their material cards (提弗洛斯 2116, 寒夜幽影 2118, 噗切娜 2117 - hers has none yet),
search-chars / search-weapons, 提弗洛斯's rules, 寒夜幽影's rules, material-list, and
the client preview table (rmxlinux/EndfieldData, 2026-09-04) with MaaEnd's item names.

Three things are pinned:

* the default: 提弗洛斯 (上线 2026-09-02, 已实装) + 寒夜幽影, numbers from the calculator;
* the pre-release source: the wiki entry's 精英化 + 战斗技能 cards for 提弗洛斯 equal her
  rules number for number, and 寒夜幽影's 武器信息 cards equal the weapon's rules - so a
  future operator's wiki entry can stand in for the calculator;
* the future path (`--rarity 5`): 噗切娜 (上线 2026-09-24, 未实装) is chosen although her
  date is in the future, her wiki entry has no cards yet, so the numbers come from the
  preview table and say so; her weapon is 待定.
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

spec = importlib.util.spec_from_file_location("build_need_tables", REPO / "scripts/mac/build-need-tables.py")
bnt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bnt)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}{(' - ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(name)


# 提弗洛斯 1→90, every breakthrough, four skills to 12 (rules?charIds=9de117d5…).
TYPHOEUS = {
    "协议棱柱组": 472, "协议棱柱": 328, "协议圆盘组": 60, "协议圆盘": 33, "存续的痕迹": 24,
    "纯晶多齿叶": 16, "至晶多齿叶": 16, "晶化多齿叶": 12, "重红柱状菌": 5, "中红柱状菌": 5, "轻红柱状菌": 3,
    "D96钢样品四": 116, "快子遴捡晶格": 20, "红矛叶": 84, "塔罗斯菌": 8,
    "干员经验": 1_792_290,
}
# 寒夜幽影 1→90, every breakthrough (rules?weaponIds=4e7f3757…).
WEAPON = {"重型强固模具": 50, "强固模具": 23, "中黯石": 5, "重黯石": 5, "轻黯石": 3, "协议纹石": 8, "武器经验": 2_524_080}
SHARED = {"象限拟合液": (132, "干员 116 + 专武 16"), "折金票": (841_000 + 385_420 + 125_700 + 341_390, "干员 1,226,420 + 专武 467,090")}
UNUSED = ["三相纳米片", "超距辉映管", "受蚀玉化叶", "岩天使叶", "星门菌", "血菌", "武陵石", "燎石"]
# 噗切娜 from the client preview table: her choices, and the two rows that carry talents.
PURRCHENA = {"超距辉映管": 116, "三相纳米片": 116, "D96钢样品四": 20, "岩天使叶": 84, "塔罗斯菌": 8,
             "协议圆盘组": 60, "协议圆盘": 33, "存续的痕迹": 24, "纯晶多齿叶": 16, "至晶多齿叶": 16, "晶化多齿叶": 12,
             "协议棱柱组": 562, "协议棱柱": 461}
FIX = HERE / "fixtures" / "skland-endfield"
TODAY = "2026-09-18"


def rows_by_name(table):
    g = table["games"][0]
    return g, {r["name"]: r for r in g["rows"]}


print("[谁是最新六星：官方百科的上线时间，未来的也算]")
src = bnt.RulesSource(FIX, None)
ops = bnt.wiki_entries(src, "干员", "6")
top, ranked = bnt.newest(ops)
check("最新六星", (top["name"], top["onlineDate"], top["wikiItemId"], top["obtain"], top["dotType"]),
      ("提弗洛斯", "2026-09-02", "2116", "干员寻访·特许寻访", "label_type_up"))
check("其次是梨诺", (ranked[1]["name"], ranked[1]["onlineDate"]), ("梨诺", "2026-08-09"))
fives = bnt.wiki_entries(src, "干员", "5")
ftop, _ = bnt.newest(fives)
check("五星那边：未实装的噗切娜排第一", (ftop["name"], ftop["onlineDate"], ftop["dotType"]), ("噗切娜", "2026-09-24", "label_type_preview"))
check("日期解析", (bnt.parse_online_date("2026年9月2日"), bnt.parse_online_date("")), ("2026-09-02", ""))

print("\n[专武：同日上线、同类型、限时特卖，唯一一把]")
weapons = bnt.wiki_entries(src, "武器", "6")
sig = bnt.signature_weapon(weapons, top, "施术单元")
check("提弗洛斯的专武", (sig["name"], sig["onlineDate"], sig["kind"], sig["obtain"], sig["wikiItemId"]),
      ("寒夜幽影", "2026-09-02", "施术单元", "武库交易所·限时特卖", "2118"))
same_day = sorted(w["name"] + "/" + w["obtain"] for w in weapons if w["onlineDate"] == "2026-09-02")
check("同日的另一把是通行证武器，不算专武", same_day, ["寒夜幽影/武库交易所·限时特卖", "苦难的尽头/协议通行证·武器补给"])
lai = next(o for o in ops if o["name"] == "莱万汀")
check("同一规则给莱万汀找到熔铸火焰", bnt.signature_weapon(weapons, lai, "单手剑")["name"], "熔铸火焰")
check("类型对不上就是没有，不猜", bnt.signature_weapon(weapons, top, "手铳"), None)

print("\n[上线前的来源：百科词条的材料卡片 == 计算器 rules]")
names = bnt.wiki_item_names(src)
doc = src.get("wiki-doc-2116", "", "")
cards = bnt.material_cards(doc, bnt.OP_CHAPTER, bnt.OP_WIDGETS, names)
rule = src.get("rules-char-9de117d5969945ecfdbd70dac3a632e6", "", "")
mat = bnt.material_table(src.get("material-list", "", ""))
need, gold = bnt.char_need(rule)
from_rules = Counter({mat[mid]["name"]: c for mid, c in need.items()})
from_cards = Counter({k: v for k, v in cards.items() if k != "折金票"})
check("提弗洛斯：卡片材料 == rules 材料（17 种）", from_cards, from_rules)
check("卡片的折金票 = rules 里精英化+技能的金币减去装备位解锁", (cards["折金票"], gold - cards["折金票"]), (814_900, 26_100))
wdoc = src.get("wiki-doc-2118", "", "")
wcards = bnt.material_cards(wdoc, bnt.WP_CHAPTER, bnt.WP_WIDGETS, names)
wrule = src.get("rules-weapon-4e7f3757fd7c98a1262bf4bca8fd9d83", "", "")
wneed, wgold = bnt.weapon_need(wrule)
check("寒夜幽影：卡片 == rules（材料和金币）", (Counter({k: v for k, v in wcards.items() if k != "折金票"}), wcards["折金票"]),
      (Counter({mat[mid]["name"]: c for mid, c in wneed.items()}), wgold))
check("噗切娜的词条还没有材料卡片", dict(bnt.material_cards(src.get("wiki-doc-2117", "", ""), bnt.OP_CHAPTER, bnt.OP_WIDGETS, names)), {})

print("\n[默认：提弗洛斯 + 寒夜幽影，用量来自计算器]")
table = bnt.build(src, "fixture", TODAY)
g, rows = rows_by_name(table)
check("game 字段", (g["game"], g["gameId"]), ("终末地", "endfield"))
check("caliber", g["caliber"], "最新六星 提弗洛斯（2026-09-02 上线）：1→90 全突破、四技能 12、专武 寒夜幽影 1→90；不含天赋")
check("footnote", g["footnote"], "人份 = 库存 ÷ 提弗洛斯满练所需（1→90 全突破、四技能 12、专武 寒夜幽影 1→90，不含天赋；2026-09-02 上线的最新六星）")
st = g["standards"][0]
check("standards 只有一个，就是她", [(s["charId"], s["name"], s["rarity"], s["releasedAt"], s["status"]) for s in g["standards"]],
      [("9de117d5969945ecfdbd70dac3a632e6", "提弗洛斯", 6, "2026-09-02", "已实装")])
check("默认标准 = 她", g["standard"], "9de117d5969945ecfdbd70dac3a632e6")
check("专武写实名", (st["weapon"]["name"], st["weapon"]["id"], st["weapon"]["releasedAt"], st["weapon"]["kind"], st["weapon"]["status"]),
      ("寒夜幽影", "4e7f3757fd7c98a1262bf4bca8fd9d83", "2026-09-02", "施术单元", "已收录"))
check("来源", st["sources"], {"need": bnt.SRC_CALC, "weapon": bnt.SRC_CALC, "levels": bnt.SRC_CALC})
check("rows 镜像默认标准", g["rows"], st["rows"])
cov = g["coverage"]
check("coverage", (cov["operator"], cov["status"], cov["weapon"], cov["weaponStatus"], cov["asOf"]), ("提弗洛斯", "已实装", "寒夜幽影", "已收录", TODAY))
require("coverage 里没有别人的数据", "universalCheckedOn" not in cov and "upcoming" not in cov)
for name, want in TYPHOEUS.items():
    check(f"提弗洛斯 {name}", (rows[name]["need"], rows[name]["group"]), (want, "提弗洛斯"))
for name, want in WEAPON.items():
    check(f"专武 寒夜幽影 {name}", (rows[name]["need"], rows[name]["group"]), (want, "专武 寒夜幽影"))
for name, (want, note) in SHARED.items():
    check(f"两边都要的 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (want, "提弗洛斯 + 专武 寒夜幽影", note))
for name in UNUSED:
    check(f"不用 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (0, None, "提弗洛斯 的满练不用它"))
require("没有一行写「因人而异」", not any("因人而异" in json.dumps(r, ensure_ascii=False) for r in g["rows"]))
check("经验行是虚拟行", (rows["干员经验"].get("virtual"), rows["干员经验"]["id"], rows["武器经验"]["id"]), (True, "exp:char", "exp:weapon"))
check("经验材料折算进虚拟行", {r["name"]: (r["exp"], r["sumInto"]) for r in g["rows"] if r.get("sumInto")},
      {"高级认知载体": (10000, "exp:char"), "初级认知载体": (1000, "exp:char"),
       "高级作战记录": (10000, "exp:char"), "中级作战记录": (1000, "exp:char"), "初级作战记录": (200, "exp:char"),
       "武器检查套组": (10000, "exp:weapon"), "武器检查装置": (1000, "exp:weapon"), "武器检查单元": (200, "exp:weapon")})
check("自选箱不计人份", (rows["高阶培养自选箱Ⅰ"]["need"], rows["高阶培养自选箱Ⅰ"]["group"]), (None, None))
check("sections", g["sections"], ["通用", "高阶素材", "采集", "经验与货币"])
check("延迟那句是官方计算器页面说的", (g["lagMinutes"], "官方" in g["lagNote"]), (30, True))
check("每行都在某一节里，经验材料不在", {r["section"] for r in g["rows"] if not r.get("sumInto")}, {"通用", "高阶素材", "采集", "经验与货币"})
check("经验材料无节（折进两条经验行）", {r["section"] for r in g["rows"] if r.get("sumInto")}, {None})
check("高阶素材一节", [r["name"] for r in g["rows"] if r["section"] == "高阶素材"],
      ["象限拟合液", "D96钢样品四", "快子遴捡晶格", "三相纳米片", "超距辉映管", "高阶培养自选箱Ⅰ"])
check("经验与货币一节", [r["name"] for r in g["rows"] if r["section"] == "经验与货币"], ["武器经验", "干员经验", "折金票"])
require("每种材料都有一行（40 种 + 2 个经验虚拟行）", len(g["rows"]) == 42, str(len(g["rows"])))
require("每行都有 id / name / rarity / icon / need / group / section / stage / note",
        all({"id", "name", "rarity", "icon", "need", "group", "section", "stage", "note"} <= set(r) for r in g["rows"]))
require("名字没有首尾空白", all(r["name"] == r["name"].strip() for r in g["rows"]))
order = [r["name"] for r in g["rows"]]
require("排序：按节，节内需求大的在前、不用的在后、无需求的最后",
        order.index("协议棱柱组") < order.index("象限拟合液") < order.index("三相纳米片") < order.index("红矛叶") < order.index("燎石") < order.index("折金票") < order.index("高级认知载体"),
        str(order[:8]))

print("\n[未来的干员：--rarity 5 选中未实装的噗切娜，用量来自客户端预览表]")
t5 = bnt.build(src, "fixture", TODAY, rarity="5")
g5, rows5 = rows_by_name(t5)
s5 = g5["standards"][0]
check("选中未实装的她", (s5["name"], s5["releasedAt"], s5["status"], s5["dotType"], s5["charId"], s5["wikiItemId"]),
      ("噗切娜", "2026-09-24", "未实装", "label_type_preview", "", "2117"))
check("chosenBy 写明含未实装", s5["chosenBy"], "百科上线时间最新的五星（含未实装）")
check("用量来源 = 预览表，并记下内部代号", (s5["sources"]["need"], s5["sources"]["foresightCharId"]), (bnt.SRC_FORESIGHT, "chr_0038_purrche"))
check("等级表来自专武应答（她自己还没有）", s5["sources"]["levels"], f"{bnt.SRC_CALC}（等级表取自 寒夜幽影 的应答，各角色相同）")
check("专武待定，理由说清", (s5["weapon"]["status"], s5["weapon"]["name"]), ("待定", ""))
require("待定理由提到计算器未收录", "计算器还没收录" in s5["weapon"]["reason"], s5["weapon"]["reason"])
for name, want in PURRCHENA.items():
    check(f"噗切娜 {name}", (rows5[name]["need"], rows5[name]["group"]), (want, "噗切娜"))
check("含天赋的两行有说明", (rows5["协议棱柱"]["note"], rows5["协议棱柱组"]["note"]), ("预览表的数含天赋树", "预览表的数含天赋树"))
check("caliber 写专武待定", g5["caliber"], "最新五星 噗切娜（2026-09-24 上线）：1→90 全突破、四技能 12、专武待定 1→90；不含天赋")
require("footnote 提醒预览表含天赋", g5["footnote"].endswith("（上线前按客户端预览表，棱柱和折金票含天赋树）"), g5["footnote"])
check("她不用的写明", (rows5["快子遴捡晶格"]["need"], rows5["快子遴捡晶格"]["note"]), (0, "噗切娜 的满练不用它"))
check("coverage 标出她未实装", (g5["coverage"]["status"], g5["coverage"]["weaponStatus"], g5["coverage"]["candidates"][0]),
      ("未实装", "待定", "噗切娜 2026-09-24（未实装）"))

print("\n[三个坑]")
lv = src.get("rules-char-9de117d5969945ecfdbd70dac3a632e6", "", "")
check("90 级那行是 -1 哨兵，不能当成本", lv["charLevelRules"][-1], {"level": 90, "gold": "-1", "exp": "-1"})
check("哨兵被跳过", bnt.level_totals(lv["charLevelRules"]), (385_420, 1_792_290))
check("武器表尾是 0", bnt.level_totals(lv["weaponLevelRules"]), (341_390, 2_524_080))
mt = bnt.material_table({"charExpMaterials": {}, "weaponExpMaterials": {},
                         "materials": {"x": {"name": "D96钢样品四\n", "rarity": {"value": "5"}, "icon": "", "exp": "0"}}})
check("名字尾巴的换行被去掉", mt["x"]["name"], "D96钢样品四")

print("\n[已提交的 web/data/need.json 和上面说的是同一回事]")
pub = json.loads((REPO / "web/data/need.json").read_text(encoding="utf-8"))
pg, prow = rows_by_name(pub)
require("built 有时间戳", bool(pub.get("built")), str(pub.get("built")))
check("game 层级", [(x["game"], x["gameId"]) for x in pub["games"]], [("终末地", "endfield")])
check("已发布：同一个标准", [(s["name"], s["weapon"]["name"], s["status"]) for s in pg["standards"]], [("提弗洛斯", "寒夜幽影", "已实装")])
check("已发布：行与离线重建完全一致", pg["rows"], g["rows"])

print()
if fails:
    print(f"✗ {len(fails)} failed: {fails}")
    sys.exit(1)
print(f"all checks passed ({len(TYPHOEUS)} of 提弗洛斯's numbers, {len(WEAPON)} of 寒夜幽影's, {len(PURRCHENA)} of 噗切娜's from the preview table)")
