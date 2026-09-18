"""The need table behind the phone page's 库存 tab is the newest five-star's, and
the committed web/data/need.json still says the same.

`scripts/mac/build-need-tables.py --offline` runs over the saved Skland responses in
fixtures/skland-endfield (pulled 2026-09-18 23:51 JST): the official wiki catalog
and the ten five-star entries with their 上线时间, search-chars / search-weapons,
the nine listed five-stars' rules, 遥望's rules, material-list, plus the client's
preview entry for 噗切娜 (ForesightCharGrowthTable, rmxlinux/EndfieldData
2026-09-04) and the item-name map (MaaEnd locales). The build must:

* pick 噗切娜 (上线 2026-09-24) over the nine launch five-stars (2026-01-22);
* take the universal numbers from the calculator (docs/ENDFIELD-SANITY-YIELD.md §B,
  gold/exp corrected for the level-90 sentinel) and prove them identical across all
  nine listed five-stars;
* take her own choices from the preview table by name (two high-tier materials at
  116, one at 20, one leaf at 84, one mushroom at 8: 超距辉映管, 三相纳米片, D96钢样品四,
  岩天使叶, 塔罗斯菌) - and never write 因人而异 anywhere;
* use 遥望 (wpn_sword_0026) for the weapon because 点心时刻 (wpn_sword_0023) is not in
  the calculator yet, and say so.

`--char 赛希 --weapon 遥望` must then give 赛希's own choices from her rules.
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


UNIVERSAL = {
    "协议棱柱组": 472, "协议棱柱": 328, "协议圆盘组": 60, "协议圆盘": 33, "存续的痕迹": 24,
    "纯晶多齿叶": 16, "至晶多齿叶": 16, "晶化多齿叶": 12,
    "重红柱状菌": 5, "中红柱状菌": 5, "轻红柱状菌": 3,
    "重型强固模具": 50, "强固模具": 23, "中黯石": 5, "重黯石": 5, "轻黯石": 3,
    "折金票": 841_000 + 385_420 + 125_700 + 341_390,
    "干员经验": 1_792_290, "武器经验": 2_524_080,
}
PURRCHENA = {"超距辉映管": 116, "三相纳米片": 116, "D96钢样品四": 20, "岩天使叶": 84, "塔罗斯菌": 8}
YAOWANG = {"快子遴捡晶格": 16, "协议纹石": 8}
UNUSED = ["受蚀玉化叶", "红矛叶", "星门菌", "血菌", "武陵石", "燎石", "象限拟合液"]
FIX = HERE / "fixtures" / "skland-endfield"


def rows_by_name(table):
    g = table["games"][0]
    return g, {r["name"]: r for r in g["rows"]}


print("[谁是最新五星：官方百科的上线时间]")
src = bnt.RulesSource(FIX, None)
top = bnt.newest_five_star(src)
check("最新五星", (top["name"], top["onlineDate"], top["obtain"]), ("噗切娜", "2026-09-24", "馈赠活动·我们的大菲林！来袭！"))
check("百科条目", (top["wikiItemId"], top["dotType"]), ("2117", "label_type_preview"))
check("其余九个都是开服那批", {r["onlineDate"] for r in top["all"][1:]}, {"2026-01-22"})
check("十个候选", len(top["all"]), 10)
check("日期解析", (bnt.parse_online_date("2026年9月24日"), bnt.parse_online_date("2026年1月22日"), bnt.parse_online_date("")),
      ("2026-09-24", "2026-01-22", ""))

print("\n[离线重建：噗切娜的表]")
table = bnt.build(src, "fixture", foresight=FIX / "foresight-chr_0038_purrche.json", item_names=FIX / "item-names.json")
g, rows = rows_by_name(table)
check("game 字段", (g["game"], g["gameId"]), ("终末地", "endfield"))
check("caliber", g["caliber"], "最新五星 噗切娜（2026-09-24 上线）：1→90 全突破、四技能 12、武器 遥望 1→90；不含天赋")
cov = g["coverage"]
check("coverage 干员", (cov["operator"], cov["onlineDate"], cov["chosenBy"], cov["calculator"], cov["foresightCharId"]),
      ("噗切娜", "2026-09-24", "官方百科上线时间最新", "未收录", "chr_0038_purrche"))
check("coverage 武器", (cov["weapon"], cov["weaponsPending"]), ("遥望", ["wpn_sword_0023（计算器未收录）"]))
require("武器理由写明是预览表推荐里计算器收录的第一把", "wpn_sword_0026" in cov["weaponReason"], cov["weaponReason"])
check("通用数在九个五星上核过", cov["universalCheckedOn"],
      ["佩丽卡", "大潘", "弧光", "昼雪", "狼卫", "艾维文娜", "赛希", "阿列什", "陈千语"])
for name, want in UNIVERSAL.items():
    check(f"通用 {name}", (rows[name]["need"], rows[name]["group"]), (want, "通用"))
for name, want in PURRCHENA.items():
    check(f"噗切娜 {name}", (rows[name]["need"], rows[name]["group"]), (want, "噗切娜"))
for name, want in YAOWANG.items():
    check(f"武器 遥望 {name}", (rows[name]["need"], rows[name]["group"]), (want, "武器 遥望"))
for name in UNUSED:
    check(f"不用 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (0, None, "噗切娜 的满练不用它"))
require("没有一行写「因人而异」", not any("因人而异" in json.dumps(r, ensure_ascii=False) for r in g["rows"]))
check("经验行是虚拟行", (rows["干员经验"].get("virtual"), rows["干员经验"]["id"], rows["武器经验"]["id"]),
      (True, "exp:char", "exp:weapon"))
check("经验材料折算进虚拟行", {r["name"]: (r["exp"], r["sumInto"]) for r in g["rows"] if r.get("sumInto")},
      {"高级认知载体": (10000, "exp:char"), "初级认知载体": (1000, "exp:char"),
       "高级作战记录": (10000, "exp:char"), "中级作战记录": (1000, "exp:char"), "初级作战记录": (200, "exp:char"),
       "武器检查套组": (10000, "exp:weapon"), "武器检查装置": (1000, "exp:weapon"), "武器检查单元": (200, "exp:weapon")})
check("自选箱不计人份", (rows["高阶培养自选箱Ⅰ"]["need"], rows["高阶培养自选箱Ⅰ"]["group"]), (None, None))
require("每种材料都有一行（40 种 + 2 个经验虚拟行）", len(g["rows"]) == 42, str(len(g["rows"])))
require("每行都有 id / name / rarity / icon / need / group / stage / note",
        all({"id", "name", "rarity", "icon", "need", "group", "stage", "note"} <= set(r) for r in g["rows"]))
require("名字没有首尾空白", all(r["name"] == r["name"].strip() for r in g["rows"]))
require("协议纹石是采集来的", rows["协议纹石"]["stage"] == bnt.GATHER, str(rows["协议纹石"]["stage"]))
order = [r["name"] for r in g["rows"]]
require("排序：通用 → 噗切娜 → 武器 → 不用的 → 经验材料/自选箱",
        order.index("协议棱柱组") < order.index("三相纳米片") < order.index("快子遴捡晶格") < order.index("受蚀玉化叶") < order.index("高级认知载体"),
        str(order[:8]))

print("\n[预览表：她选的素材按名字取，数量要符合 116/116/20/84/8]")
fs = json.loads((FIX / "foresight-chr_0038_purrche.json").read_text(encoding="utf-8"))
names = json.loads((FIX / "item-names.json").read_text(encoding="utf-8"))
check("预览表只此一人", list(fs), ["chr_0038_purrche"])
check("她的选择", bnt.foresight_choices(fs["chr_0038_purrche"], names), PURRCHENA)
check("她的推荐武器", fs["chr_0038_purrche"]["weaponIds"], ["wpn_sword_0023", "wpn_sword_0026"])
check("id 规则：md5(内部代号)", (bnt.calc_id("chr_0006_wolfgd"), bnt.calc_id("wpn_sword_0026")),
      ("26e3cc73ac23deb8f6a875038d2243ff", "f5d3458d700506ab2a57bc38aa4f3f65"))
sc = json.loads((FIX / "search-chars.json").read_text(encoding="utf-8"))["chars"]
require("计算器（search-chars）还没有噗切娜", all(c["name"] != "噗切娜" for c in sc), str(len(sc)))

print("\n[--char 赛希：她自己的选择来自 rules]")
t2 = bnt.build(src, "fixture", char_name="赛希", weapon_name="遥望")
g2, rows2 = rows_by_name(t2)
check("caliber", g2["caliber"], "指定干员 赛希（2026-01-22 上线）：1→90 全突破、四技能 12、武器 遥望 1→90；不含天赋")
check("coverage", (g2["coverage"]["chosenBy"], g2["coverage"]["calculator"], g2["coverage"]["weaponReason"]),
      ("--char", "已收录", "--weapon"))
check("赛希的选择（快子遴捡晶格 116 + 遥望 16）", {n: rows2[n]["need"] for n in ("快子遴捡晶格", "象限拟合液", "D96钢样品四", "受蚀玉化叶", "血菌")},
      {"快子遴捡晶格": 132, "象限拟合液": 116, "D96钢样品四": 20, "受蚀玉化叶": 84, "血菌": 8})
check("干员 + 武器共用一种时写明拆分", rows2["快子遴捡晶格"]["note"], "干员 116 + 武器 16")
check("赛希不用的", rows2["三相纳米片"]["need"], 0)

print("\n[三个坑]")
lv = json.loads((FIX / "rules-char-3839d35948216cc09368cd62167c7368.json").read_text(encoding="utf-8"))
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
check("已发布：同一个干员、同一把武器", (pg["coverage"]["operator"], pg["coverage"]["weapon"]), ("噗切娜", "遥望"))
check("已发布：行与离线重建完全一致", pg["rows"], g["rows"])

print()
if fails:
    print(f"✗ {len(fails)} failed: {fails}")
    sys.exit(1)
print(f"all checks passed ({len(UNIVERSAL)} universal numbers, {len(PURRCHENA)} of 噗切娜's own, 2 of 遥望's)")
