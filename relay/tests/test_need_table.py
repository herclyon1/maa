"""The need table behind the phone page's 库存 tab is 提弗洛斯's build with her
signature weapon 寒夜幽影 - nobody else's - and the committed web/data/need.json
still says the same.

`scripts/mac/build-need-tables.py --offline` runs over the eight saved Skland
responses in fixtures/skland-endfield (pulled 2026-09-19 00:25 JST, judged as of
2026-09-18): the official wiki catalog (干员 / 武器) and the wiki entries of every
six-star operator and six-star weapon (上线时间 / 类型 / 主要获取方式), search-chars /
search-weapons, her rules, 寒夜幽影's rules, material-list. The build must:

* pick 提弗洛斯 (上线 2026-09-02) as the newest released six-star, ahead of 梨诺
  (08-09), and list nobody as upcoming;
* pick 寒夜幽影 as her signature weapon: released the same day, a 施术单元 like her,
  sold in 「武库交易所·限时特卖」 - while 苦难的尽头 (same day, same type, battle pass) is not;
* write her numbers only, read from her rules and the weapon's (level-90 sentinel
  skipped), never a 因人而异 and never another operator's figure.
"""
import importlib.util
import json
import sys
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


# 提弗洛斯 1→90, every breakthrough, four skills to 12 (from rules?charIds=9de117d5…).
TYPHOEUS = {
    "协议棱柱组": 472, "协议棱柱": 328, "协议圆盘组": 60, "协议圆盘": 33, "存续的痕迹": 24,
    "纯晶多齿叶": 16, "至晶多齿叶": 16, "晶化多齿叶": 12, "重红柱状菌": 5, "中红柱状菌": 5, "轻红柱状菌": 3,
    "D96钢样品四": 116, "快子遴捡晶格": 20, "红矛叶": 84, "塔罗斯菌": 8,
    "干员经验": 1_792_290,
}
# 寒夜幽影 1→90, every breakthrough (from rules?weaponIds=4e7f3757…).
WEAPON = {"重型强固模具": 50, "强固模具": 23, "中黯石": 5, "重黯石": 5, "轻黯石": 3, "协议纹石": 8, "武器经验": 2_524_080}
SHARED = {"象限拟合液": (132, "干员 116 + 专武 16"), "折金票": (841_000 + 385_420 + 125_700 + 341_390, "干员 1,226,420 + 专武 467,090")}
UNUSED = ["三相纳米片", "超距辉映管", "受蚀玉化叶", "岩天使叶", "星门菌", "血菌", "武陵石", "燎石"]
FIX = HERE / "fixtures" / "skland-endfield"
TODAY = "2026-09-18"


def rows_by_name(table):
    g = table["games"][0]
    return g, {r["name"]: r for r in g["rows"]}


print("[夹具只有八份：她、她的专武、两张清单、百科目录和词条、材料表]")
check("夹具文件", sorted(p.name for p in FIX.iterdir()),
      ["material-list.json", "pulled-at.txt", "rules-char-9de117d5969945ecfdbd70dac3a632e6.json",
       "rules-weapon-4e7f3757fd7c98a1262bf4bca8fd9d83.json", "search-chars.json", "search-weapons.json",
       "wiki-catalog.json", "wiki-items.json"])

print("\n[谁是最新六星：官方百科的上线时间，只算已实装的]")
src = bnt.RulesSource(FIX, None)
ops = bnt.wiki_entries(src, "干员", "6")
newest, released, upcoming = bnt.newest_released(ops, TODAY)
check("最新六星", (newest["name"], newest["onlineDate"], newest["wikiItemId"], newest["obtain"], newest["dotType"]),
      ("提弗洛斯", "2026-09-02", "2116", "干员寻访·特许寻访", "label_type_up"))
check("其次是梨诺", (released[1]["name"], released[1]["onlineDate"]), ("梨诺", "2026-08-09"))
check("没有未实装的六星", upcoming, [])
check("把「今天」推到 09-02 前，最新六星就是梨诺", bnt.newest_released(ops, "2026-09-01")[0]["name"], "梨诺")
check("日期解析", (bnt.parse_online_date("2026年9月2日"), bnt.parse_online_date("")), ("2026-09-02", ""))

print("\n[专武：同日上线、同类型、限时特卖，唯一一把]")
weapons = bnt.wiki_entries(src, "武器", "6")
sig = bnt.signature_weapon(weapons, newest, "施术单元")
check("提弗洛斯的专武", (sig["name"], sig["onlineDate"], sig["kind"], sig["obtain"], sig["wikiItemId"]),
      ("寒夜幽影", "2026-09-02", "施术单元", "武库交易所·限时特卖", "2118"))
same_day = sorted(w["name"] + "/" + w["obtain"] for w in weapons if w["onlineDate"] == "2026-09-02")
check("同日的另一把是通行证武器，不算专武", same_day, ["寒夜幽影/武库交易所·限时特卖", "苦难的尽头/协议通行证·武器补给"])
try:
    bnt.signature_weapon(weapons, newest, "手铳")
    require("类型对不上就拒绝，不猜", False)
except RuntimeError as e:
    require("类型对不上就拒绝，不猜", "--weapon" in str(e), str(e))

print("\n[离线重建：提弗洛斯 + 寒夜幽影，只有她的数]")
table = bnt.build(src, "fixture", TODAY)
g, rows = rows_by_name(table)
check("game 字段", (g["game"], g["gameId"]), ("终末地", "endfield"))
check("caliber", g["caliber"], "最新六星 提弗洛斯（2026-09-02 上线）：1→90 全突破、四技能 12、专武 寒夜幽影 1→90；不含天赋")
check("footnote", g["footnote"], "人份 = 库存 ÷ 提弗洛斯满练所需（1→90 全突破、四技能 12、专武寒夜幽影 1→90，不含天赋；2026-09-02 上线的最新六星）")
check("standards 只有一个，就是她", [(s["charId"], s["name"], s["rarity"], s["releasedAt"]) for s in g["standards"]],
      [("9de117d5969945ecfdbd70dac3a632e6", "提弗洛斯", 6, "2026-09-02")])
check("默认标准 = 她", g["standard"], "9de117d5969945ecfdbd70dac3a632e6")
st = g["standards"][0]
check("专武写实名", (st["weapon"]["name"], st["weapon"]["id"], st["weapon"]["releasedAt"], st["weapon"]["kind"]),
      ("寒夜幽影", "4e7f3757fd7c98a1262bf4bca8fd9d83", "2026-09-02", "施术单元"))
require("专武理由写明规则", "限时特卖" in st["weapon"]["reason"] and "同日" in st["weapon"]["reason"], st["weapon"]["reason"])
check("rows 镜像默认标准", g["rows"], st["rows"])
cov = g["coverage"]
check("coverage", (cov["operator"], cov["weapon"], cov["asOf"], cov["upcoming"]), ("提弗洛斯", "寒夜幽影", TODAY, []))
require("coverage 里没有别人的数据", "universalCheckedOn" not in cov)
for name, want in TYPHOEUS.items():
    check(f"提弗洛斯 {name}", (rows[name]["need"], rows[name]["group"]), (want, "提弗洛斯"))
for name, want in WEAPON.items():
    check(f"专武 寒夜幽影 {name}", (rows[name]["need"], rows[name]["group"]), (want, "专武 寒夜幽影"))
for name, (want, note) in SHARED.items():
    check(f"两边都要的 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (want, "提弗洛斯 + 专武 寒夜幽影", note))
for name in UNUSED:
    check(f"不用 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (0, None, "提弗洛斯 的满练不用它"))
require("没有一行写「因人而异」", not any("因人而异" in json.dumps(r, ensure_ascii=False) for r in g["rows"]))
check("经验行是虚拟行", (rows["干员经验"].get("virtual"), rows["干员经验"]["id"], rows["武器经验"]["id"]),
      (True, "exp:char", "exp:weapon"))
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

print("\n[三个坑]")
lv = json.loads((FIX / "rules-char-9de117d5969945ecfdbd70dac3a632e6.json").read_text(encoding="utf-8"))
check("90 级那行是 -1 哨兵，不能当成本", lv["charLevelRules"][-1], {"level": 90, "gold": "-1", "exp": "-1"})
check("哨兵被跳过", bnt.level_totals(lv["charLevelRules"]), (385_420, 1_792_290))
check("武器表尾是 0", bnt.level_totals(lv["weaponLevelRules"]), (341_390, 2_524_080))
mat = bnt.material_table({"charExpMaterials": {}, "weaponExpMaterials": {},
                          "materials": {"x": {"name": "D96钢样品四\n", "rarity": {"value": "5"}, "icon": "", "exp": "0"}}})
check("名字尾巴的换行被去掉", mat["x"]["name"], "D96钢样品四")

print("\n[已提交的 web/data/need.json 和上面说的是同一回事]")
pub = json.loads((REPO / "web/data/need.json").read_text(encoding="utf-8"))
pg, prow = rows_by_name(pub)
require("built 有时间戳", bool(pub.get("built")), str(pub.get("built")))
check("game 层级", [(x["game"], x["gameId"]) for x in pub["games"]], [("终末地", "endfield")])
check("已发布：同一个标准", [(s["name"], s["weapon"]["name"]) for s in pg["standards"]], [("提弗洛斯", "寒夜幽影")])
check("已发布：行与离线重建完全一致", pg["rows"], g["rows"])

print()
if fails:
    print(f"✗ {len(fails)} failed: {fails}")
    sys.exit(1)
print(f"all checks passed ({len(TYPHOEUS)} of 提弗洛斯's numbers, {len(WEAPON)} of 寒夜幽影's, {len(SHARED)} shared)")
