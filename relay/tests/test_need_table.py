"""The need table behind the phone page's 库存 tab reproduces
docs/ENDFIELD-SANITY-YIELD.md §B number for number, and the committed
web/data/need.json still says the same.

Two builds are checked. The first runs `scripts/mac/build-need-tables.py --offline`
over the saved Skland responses in fixtures/skland-endfield (the nine five-stars,
one six-star, the eight weapons they wear, pulled 2026-09-18) - that is the
document's own input, so every §B figure must come back exactly. The second reads
the committed web/data/need.json (built from the whole account) and demands the
same universal numbers, so the published table cannot drift from the fixtures
without this going red.

Three traps the builder must not fall into, each pinned here: the level-90
`-1` sentinel (summing it gives the off-by-one 385,419 / 1,792,289 that §B
carried until 2026-09-18), names with a trailing newline, and a material the
account has none of being absent from `itemCount` rather than zero.
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


# §B universal, operator side then weapon side; gold and exp from §B corrected for
# the sentinel (docs/ENDFIELD-STOCKPILE.md §1 had the right figures all along).
UNIVERSAL = {
    "协议棱柱组": 472, "协议棱柱": 328, "协议圆盘组": 60, "协议圆盘": 33, "存续的痕迹": 24,
    "纯晶多齿叶": 16, "至晶多齿叶": 16, "晶化多齿叶": 12,
    "重红柱状菌": 5, "中红柱状菌": 5, "轻红柱状菌": 3,
    "重型强固模具": 50, "强固模具": 23, "中黯石": 5, "重黯石": 5, "轻黯石": 3,
    "折金票": 841_000 + 385_420 + 125_700 + 341_390,
    "干员经验": 1_792_290, "武器经验": 2_524_080,
}
# §B variable: which option each five-star takes (116 / 116 / 20 / 84 / 8).
FIVE_STARS = {
    "佩丽卡": ("D96钢样品四", "超距辉映管", "快子遴捡晶格", "受蚀玉化叶", "血菌"),
    "弧光": ("D96钢样品四", "快子遴捡晶格", "超距辉映管", "岩天使叶", "星门菌"),
    "陈千语": ("D96钢样品四", "快子遴捡晶格", "象限拟合液", "受蚀玉化叶", "星门菌"),
    "阿列什": ("三相纳米片", "象限拟合液", "超距辉映管", "岩天使叶", "血菌"),
    "狼卫": ("快子遴捡晶格", "象限拟合液", "三相纳米片", "岩天使叶", "星门菌"),
    "赛希": ("快子遴捡晶格", "象限拟合液", "D96钢样品四", "受蚀玉化叶", "血菌"),
    "大潘": ("D96钢样品四", "超距辉映管", "三相纳米片", "岩天使叶", "血菌"),
    "昼雪": ("三相纳米片", "超距辉映管", "象限拟合液", "受蚀玉化叶", "血菌"),
    "艾维文娜": ("三相纳米片", "象限拟合液", "快子遴捡晶格", "岩天使叶", "血菌"),
}
FIX = HERE / "fixtures" / "skland-endfield"


def rows_by_name(table):
    g = table["games"][0]
    return g, {r["name"]: r for r in g["rows"]}


print("[从保存的森空岛应答离线重建，§B 的每个数都要回来]")
table = bnt.build(bnt.RulesSource(FIX, None), "fixture")
g, rows = rows_by_name(table)
check("game 字段", (g["game"], g["gameId"]), ("终末地", "endfield"))
check("覆盖的干员", g["coverage"]["operators"],
      ["佩丽卡", "弧光", "陈千语", "阿列什", "狼卫", "赛希", "大潘", "昼雪", "艾维文娜", "汤汤"])
for name, want in UNIVERSAL.items():
    check(f"通用 {name}", (rows[name]["need"], rows[name]["group"]), (want, "通用"))
check("经验行是虚拟行", (rows["干员经验"].get("virtual"), rows["干员经验"]["id"], rows["武器经验"]["id"]),
      (True, "exp:char", "exp:weapon"))
check("经验材料折算进虚拟行", {r["name"]: (r["exp"], r["sumInto"]) for r in g["rows"] if r.get("sumInto")},
      {"高级认知载体": (10000, "exp:char"), "初级认知载体": (1000, "exp:char"),
       "高级作战记录": (10000, "exp:char"), "中级作战记录": (1000, "exp:char"), "初级作战记录": (200, "exp:char"),
       "武器检查套组": (10000, "exp:weapon"), "武器检查装置": (1000, "exp:weapon"), "武器检查单元": (200, "exp:weapon")})

print("\n[§B 可变组：五星各自选到的那份，116 / 116 / 20 / 84 / 8]")
for op, (a, b, c, leaf, shroom) in FIVE_STARS.items():
    rule = json.loads((FIX / f"rules-char-{next(x['id'] for x in json.loads((FIX / 'card.json').read_text())['detail']['chars'] if x['charData']['name'] == op)}.json").read_text())
    need, gold = bnt.char_need(rule)
    mat = bnt.material_table(json.loads((FIX / "material-list.json").read_text(encoding="utf-8")))
    by_name = {mat[k]["name"]: v for k, v in need.items()}
    check(f"{op}", (by_name.get(a), by_name.get(b), by_name.get(c), by_name.get(leaf), by_name.get(shroom), gold),
          (116, 116, 20, 84, 8, 841_000))
for name in ("D96钢样品四", "超距辉映管", "快子遴捡晶格", "象限拟合液", "三相纳米片"):
    check(f"高阶 {name} 按最大量算人份", (rows[name]["need"], rows[name]["group"]), (116, "高阶素材（因人而异）"))
    require(f"高阶 {name} 的说明列出三种用量", "116" in rows[name]["note"] and "20" in rows[name]["note"] and "16" in rows[name]["note"], rows[name]["note"])
check("叶 84", {rows[n]["need"] for n in ("受蚀玉化叶", "岩天使叶")}, {84})
check("菌 8", {rows[n]["need"] for n in ("星门菌", "血菌")}, {8})
check("武器矿石 8", {rows[n]["need"] for n in ("武陵石", "燎石")}, {8})
check("自选箱不计人份", (rows["高阶培养自选箱Ⅰ"]["need"], rows["高阶培养自选箱Ⅰ"]["group"]), (None, None))

print("\n[三个坑]")
lv = json.loads((FIX / "level-rules.json").read_text(encoding="utf-8"))
check("90 级那行是 -1 哨兵，不能当成本", lv["charLevelRules"][-1], {"level": 90, "gold": "-1", "exp": "-1"})
check("哨兵被跳过", bnt.level_totals(lv["charLevelRules"]), (385_420, 1_792_290))
check("武器表尾是 0", bnt.level_totals(lv["weaponLevelRules"]), (341_390, 2_524_080))
mat = bnt.material_table({"charExpMaterials": {}, "weaponExpMaterials": {},
                          "materials": {"x": {"name": "D96钢样品四\n", "rarity": {"value": "5"}, "icon": "", "exp": "0"}}})
check("名字尾巴的换行被去掉", mat["x"]["name"], "D96钢样品四")
require("每种材料都有一行（40 种 + 2 个经验虚拟行）", len(g["rows"]) == 42, str(len(g["rows"])))
require("每行都有 id / name / rarity / icon / need / group / stage / note",
        all({"id", "name", "rarity", "icon", "need", "group", "stage", "note"} <= set(r) for r in g["rows"]))
require("名字没有首尾空白", all(r["name"] == r["name"].strip() for r in g["rows"]))
require("未知来源写成 null 不猜", rows["协议纹石"]["stage"] is None)

print("\n[已提交的 web/data/need.json 和上面说的是同一回事]")
pub = json.loads((REPO / "web/data/need.json").read_text(encoding="utf-8"))
pg, prow = rows_by_name(pub)
require("built 有时间戳", bool(pub.get("built")), str(pub.get("built")))
check("game 层级", [(x["game"], x["gameId"]) for x in pub["games"]], [("终末地", "endfield")])
for name, want in UNIVERSAL.items():
    check(f"已发布 通用 {name}", (prow[name]["need"], prow[name]["group"]), (want, "通用"))
require("已发布表覆盖整个账号（≥ 夹具的 10 个干员）", len(pg["coverage"]["operators"]) >= 10, str(len(pg["coverage"]["operators"])))
check("已发布表的行数", len(pg["rows"]), 42)
check("同一个 id 集合", {r["id"] for r in pg["rows"]}, {r["id"] for r in g["rows"]})
for name in ("D96钢样品四", "超距辉映管", "快子遴捡晶格", "象限拟合液", "三相纳米片"):
    require(f"已发布 {name} 的人份基数 ≥ 116", (prow[name]["need"] or 0) >= 116, str(prow[name]["need"]))
check("已发布 协议纹石 是武器矿石 8", (prow["协议纹石"]["need"], prow["协议纹石"]["group"]), (8, "矿石（三选一）"))

print()
if fails:
    print(f"✗ {len(fails)} failed: {fails}")
    sys.exit(1)
print(f"all checks passed ({len(UNIVERSAL)} universal numbers, {len(FIVE_STARS)} five-stars)")
