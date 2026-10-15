"""The need table behind the App's 库存 page is the newest six-star's build
with her signature weapon, it can be built before her banner opens, and the committed
web/data/need.json still says the same.

The builder (relay/ark_relay/features/needtable/build.py, which the relay runs once a
server day and `scripts/mac/build-need-tables.py` by hand) runs over the saved responses in
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
  preview table and say so; her weapon is 待定 (pinned by --char since 2026-10-15: she
  would be the second standard there, after a released five-star this fixture has no
  numbers for).

And over fixtures/skland-endfield-1014 (pulled 2026-10-14 03:36 UTC+8): two unreleased
six-stars (祀 10-15, 明河 11-05) and four six-star entries in the preview table. The
builder used to give up there (「cannot pick hers」), so nobody's table was current;
now 明河's entry is found by elimination and weapon type, her signature weapon by her
wiki weapon tag, and the preview table's new material by the calculator's md5 ids.

And over fixtures/skland-endfield-1015 (pulled 2026-10-15 16:05 UTC+8, the day 祀 went
live; the four MaaEnd essence files and Target.json / its term names from MaaEnd's
GitHub v2 branch, data version 2026-10-08 08:40:17 UTC): the two standards of the
2026-10-15 caliber - 祀 + 玉中身 first (from the calculator), 明河 + 唤月 next (preview
table) - and the essence advice, cross-checked against CEP (github.com/cmyyx/cep
src/data/weapons.ts + dungeons.ts, read 2026-10-15).
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from ark_relay.features.needtable import build as bnt  # noqa: E402

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
# The use section each of them lands in (rules: charBreak* nodes / skill levels 2-9 and 10-12 / weapon breakthroughs).
USE_OF = {"协议圆盘组": "干员精英化", "协议圆盘": "干员精英化", "重红柱状菌": "干员精英化", "中红柱状菌": "干员精英化",
          "轻红柱状菌": "干员精英化", "快子遴捡晶格": "干员精英化", "塔罗斯菌": "干员精英化",
          "协议棱柱": "干员技能升级", "纯晶多齿叶": "干员技能升级", "至晶多齿叶": "干员技能升级", "晶化多齿叶": "干员技能升级",
          "存续的痕迹": "干员技能专精", "D96钢样品四": "干员技能专精", "红矛叶": "干员技能专精",
          "干员经验": "干员等级提升", "武器经验": "武器等级提升",
          "协议棱柱组": "多处共用", "象限拟合液": "多处共用", "折金票": "多处共用",
          **{k: "武器突破" for k in ("重型强固模具", "强固模具", "中黯石", "重黯石", "轻黯石", "协议纹石")}}
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
check("没有已公布的下一位：只有当前这一个", (st["role"], st["label"], g["coverage"]["next"], g["coverage"]["nextError"]),
      ("current", "最新六星", None, ""))
check("标准自带的节顺序 = 游戏层那份", st["groups"], g["groups"])
check("专武写实名", (st["weapon"]["name"], st["weapon"]["id"], st["weapon"]["releasedAt"], st["weapon"]["kind"], st["weapon"]["status"]),
      ("寒夜幽影", "4e7f3757fd7c98a1262bf4bca8fd9d83", "2026-09-02", "施术单元", "已收录"))
check("来源", st["sources"], {"need": bnt.SRC_CALC, "weapon": bnt.SRC_CALC, "levels": bnt.SRC_CALC})
check("rows 镜像默认标准", g["rows"], st["rows"])
cov = g["coverage"]
check("coverage", (cov["operator"], cov["status"], cov["weapon"], cov["weaponStatus"], cov["asOf"]), ("提弗洛斯", "已实装", "寒夜幽影", "已收录", TODAY))
require("coverage 里没有别人的数据", "universalCheckedOn" not in cov and "upcoming" not in cov)
for name, want in TYPHOEUS.items():
    check(f"提弗洛斯 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["owner"]), (want, USE_OF[name], "干员"))
for name, want in WEAPON.items():
    check(f"专武 寒夜幽影 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["owner"]), (want, USE_OF[name], "专武"))
for name, (want, note) in SHARED.items():
    check(f"两边都要的 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (want, "多处共用", note))
check("用在两步的写出每步用量", {n: rows[n]["uses"] for n in ("协议棱柱组", "象限拟合液")},
      {"协议棱柱组": [{"use": "干员技能升级", "need": 116}, {"use": "干员技能专精", "need": 356}],
       "象限拟合液": [{"use": "干员技能专精", "need": 116}, {"use": "武器突破", "need": 16}]})
check("节的顺序", g["groups"], ["干员精英化", "干员技能升级", "干员技能专精", "干员等级提升", "武器突破", "武器等级提升", "多处共用"])
require("用途有出处", "三相纳米片" in g["useSource"] and "至晶多齿叶" in g["useSource"])
print("\n[怎么来：百科「物品来源」原文，采集 / 理智关卡 / 其它]")
check("怎么来：每种材料都查到了", g["originMissing"], [])
check("怎么来：采集物", sorted(r["name"] for r in g["rows"] if (r.get("origin") or {}).get("kind") == "采集物"),
      sorted(["协议纹石", "红矛叶", "塔罗斯菌", "至晶多齿叶", "血菌", "中红柱状菌", "重黯石", "纯晶多齿叶", "重红柱状菌",
              "中黯石", "受蚀玉化叶", "岩天使叶", "星门菌", "武陵石", "燎石", "轻黯石", "晶化多齿叶", "轻红柱状菌"]))
check("怎么来：自选箱不是理智关卡", (rows["高阶培养自选箱Ⅰ"]["origin"]["kind"], rows["高阶培养自选箱Ⅰ"]["origin"]["其它"]),
      ("其它来源", ["协议通行证及各类活动奖励。", "四号谷地-物资调度终端购买。"]))
check("怎么来：高阶素材的理智关卡原文", rows["三相纳米片"]["origin"]["理智关卡"],
      [l for l in rows["三相纳米片"]["origin"]["理智关卡"] if "协议空间" in l])
require("怎么来：每条原文恰好落在一类", all(sorted(r["origin"]["采集"] + r["origin"]["理智关卡"] + r["origin"]["其它"]) ==
        sorted(set(r["origin"]["采集"] + r["origin"]["理智关卡"] + r["origin"]["其它"])) for r in g["rows"] if r.get("origin")))
for name in UNUSED:
    check(f"不用 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (0, None, "提弗洛斯 的满练不用它"))
require("没有一行写「因人而异」", not any("因人而异" in json.dumps(r, ensure_ascii=False) for r in g["rows"]))
check("经验行是虚拟行", (rows["干员经验"].get("virtual"), rows["干员经验"]["id"], rows["武器经验"]["id"]), (True, "exp:char", "exp:weapon"))
check("经验材料折算进虚拟行", {r["name"]: (r["exp"], r["sumInto"]) for r in g["rows"] if r.get("sumInto")},
      {"高级认知载体": (10000, "exp:char"), "初级认知载体": (1000, "exp:char"),
       "高级作战记录": (10000, "exp:char"), "中级作战记录": (1000, "exp:char"), "初级作战记录": (200, "exp:char"),
       "武器检查套组": (10000, "exp:weapon"), "武器检查装置": (1000, "exp:weapon"), "武器检查单元": (200, "exp:weapon")})
for exp_row, sid in (("干员经验", "exp:char"), ("武器经验", "exp:weapon")):
    cards = sorted((r for r in g["rows"] if r.get("sumInto") == sid), key=lambda r: (-r["rarity"], r["name"]))
    o = rows[exp_row]["origin"]
    check(f"{exp_row}：怎么来 = 折进来那几种的并集", (o["kind"], o["from"], {k: set(o[k]) for k in ("采集", "理智关卡", "其它")}),
          (cards[0]["origin"]["kind"], [r["name"] for r in cards],
           {k: {l for r in cards for l in r["origin"][k]} for k in ("采集", "理智关卡", "其它")}))
    check(f"{exp_row}：图标借最高稀有度那件", (rows[exp_row]["icon"], rows[exp_row]["note"].endswith(f"图标借{cards[0]['name']}")),
          (cards[0]["icon"], True))
check("自选箱不计人份",(rows["高阶培养自选箱Ⅰ"]["need"], rows["高阶培养自选箱Ⅰ"]["group"]), (None, None))
check("sections", g["sections"], ["通用", "高阶素材", "采集", "经验与货币"])
check("延迟那句是官方计算器页面说的", (g["lagMinutes"], "官方" in g["lagNote"]), (30, True))
check("每行都在某一节里，经验材料不在", {r["section"] for r in g["rows"] if not r.get("sumInto")}, {"通用", "高阶素材", "采集", "经验与货币"})
check("经验材料无节（折进两条经验行）", {r["section"] for r in g["rows"] if r.get("sumInto")}, {None})
check("高阶素材一节", [r["name"] for r in g["rows"] if r["section"] == "高阶素材"],
      ["快子遴捡晶格", "D96钢样品四", "象限拟合液", "三相纳米片", "超距辉映管", "高阶培养自选箱Ⅰ"])
check("经验与货币一节", [r["name"] for r in g["rows"] if r["section"] == "经验与货币"], ["干员经验", "武器经验", "折金票"])
require("每种材料都有一行（40 种 + 2 个经验虚拟行）", len(g["rows"]) == 42, str(len(g["rows"])))
require("每行都有 id / name / rarity / icon / need / group / section / stage / note",
        all({"id", "name", "rarity", "icon", "need", "group", "section", "stage", "note"} <= set(r) for r in g["rows"]))
require("名字没有首尾空白", all(r["name"] == r["name"].strip() for r in g["rows"]))
order = [r["name"] for r in g["rows"]]
require("排序：按用途节，节内需求大的在前、不用的在后、无需求的最后",
        order.index("协议圆盘组") < order.index("协议棱柱") < order.index("D96钢样品四") < order.index("干员经验") < order.index("重型强固模具")
        < order.index("武器经验") < order.index("协议棱柱组") < order.index("三相纳米片") < order.index("高级认知载体"),
        str(order[:8]))

print("\n[未来的干员：--rarity 5 时未实装的噗切娜是「下一位」；她的用量来自客户端预览表]")
# 2026-10-15: the first standard is the newest released one, the announced one the second
# (build.pick_standards). This fixture holds no numbers for the released five-star, so her
# build is pinned by name (--char), which takes the same path as the second standard.
_, ranked5 = bnt.newest(fives)
check("五星：已上线最新的那位在前，未实装的噗切娜是下一位", [(w, r) for w, r, _l, _c in bnt.pick_standards(ranked5, TODAY, "5")],
      [(next(e["name"] for e in ranked5 if e["onlineDate"] <= TODAY), "current"), ("噗切娜", "next")])
t5 = bnt.build(src, "fixture", TODAY, char_name="噗切娜", rarity="5")
g5, rows5 = rows_by_name(t5)
s5 = g5["standards"][0]
check("选中未实装的她", (s5["name"], s5["releasedAt"], s5["status"], s5["dotType"], s5["charId"], s5["wikiItemId"]),
      ("噗切娜", "2026-09-24", "未实装", "label_type_preview", "", "2117"))
check("指定的只建这一个标准", ([s["role"] for s in g5["standards"]], s5["chosenBy"], g5["coverage"]["next"]), (["named"], "--char", None))
check("用量来源 = 预览表，并记下内部代号", (s5["sources"]["need"], s5["sources"]["foresightCharId"]), (bnt.SRC_FORESIGHT, "chr_0038_purrche"))
check("等级表来自专武应答（她自己还没有）", s5["sources"]["levels"], f"{bnt.SRC_CALC}（等级表取自 寒夜幽影 的应答，各角色相同）")
check("专武待定，理由说清", (s5["weapon"]["status"], s5["weapon"]["name"]), ("待定", ""))
require("待定理由提到计算器未收录", "计算器还没收录" in s5["weapon"]["reason"], s5["weapon"]["reason"])
for name, want in PURRCHENA.items():
    check(f"噗切娜 {name}", (rows5[name]["need"], rows5[name]["group"]), (want, "噗切娜"))  # no rules yet: no per-step split
check("含天赋的两行有说明", (rows5["协议棱柱"]["note"], rows5["协议棱柱组"]["note"]), ("预览表的数含天赋树", "预览表的数含天赋树"))
check("caliber 写专武待定", g5["caliber"], "指定干员 噗切娜（2026-09-24 上线）：1→90 全突破、四技能 12、专武待定 1→90；不含天赋")
require("footnote 提醒预览表含天赋", g5["footnote"].endswith("（上线前按客户端预览表，棱柱和折金票含天赋树）"), g5["footnote"])
check("她不用的写明", (rows5["快子遴捡晶格"]["need"], rows5["快子遴捡晶格"]["note"]), (0, "噗切娜 的满练不用它"))
check("coverage 标出她未实装", (g5["coverage"]["status"], g5["coverage"]["weaponStatus"], g5["coverage"]["candidates"][0]),
      ("未实装", "待定", "噗切娜 2026-09-24（未实装）"))

print("\n[10-14：两个未实装六星、预览表里四个六星条目，照样认出明河]")
FIX14 = HERE / "fixtures" / "skland-endfield-1014"
src14 = bnt.RulesSource(FIX14, None)
ops14 = bnt.wiki_entries(src14, "干员", "6")
top14, ranked14 = bnt.newest(ops14)
check("最新六星是未实装的明河，武器类型取自百科标签", (top14["name"], top14["onlineDate"], top14.get("weaponType")),
      ("明河", "2026-11-05", "单手剑"))
check("其次是祀", (ranked14[1]["name"], ranked14[1]["onlineDate"], ranked14[1].get("weaponType")), ("祀", "2026-10-15", "双手剑"))
try:
    t14 = bnt.make(src14, char_name="明河")   # the fixture has no numbers for the then-current 提弗洛斯
    why14 = ""
except Exception as exc:  # noqa: BLE001 - the old builder raised here; any exception is the failure checked below
    t14, why14 = None, f"{type(exc).__name__}: {exc}"
check("建得出来（旧代码在这里放弃：cannot pick hers）", why14, "")
if t14 is not None:
    g14, rows14 = rows_by_name(t14)
    s14 = g14["standards"][0]
    check("她、未实装、预览表里的条目", (s14["name"], s14["status"], s14["sources"]["need"], s14["sources"]["foresightCharId"]),
          ("明河", "未实装", bnt.SRC_FORESIGHT, "chr_0037_minghe"))
    check("专武按百科标签的单手剑找到唤月（数还没有，待定）", (s14["weapon"]["name"], s14["weapon"]["kind"], s14["weapon"]["status"]),
          ("唤月", "单手剑", "待定"))
    check("built 是拉取时刻，固定写法", t14["built"], "2026-10-14 03:36 UTC+8")
    check("预览表的数", {n: rows14[n]["need"] for n in ("协议棱柱组", "协议棱柱", "象限拟合液", "三相纳米片", "红矛叶")},
          {"协议棱柱组": 562, "协议棱柱": 461, "象限拟合液": 116, "三相纳米片": 20, "红矛叶": 84})
fs14 = src14.get_url("client-foresight", "", None)
mat14 = bnt.material_table(src14.get("material-list", "", ""))
calc14 = {c["id"] for c in src14.get("search-chars", "", "")["chars"]}
check("计算器已收录的条目（md5 代号）排除掉，剩两个", sorted(e["charId"] for e in fs14.values() if str(e["rarity"]) == "6"
      and __import__("hashlib").md5(e["charId"].encode()).hexdigest() not in calc14), ["chr_0036_jsspsi", "chr_0037_minghe"])
pick = getattr(bnt, "foresight_entry", None)
check("有按淘汰和武器类型挑预览表条目的函数", pick is not None, True)
if pick is not None:
    check("剩下的按武器类型分开", (pick(fs14, "6", calc14, "单手剑", "明河")["charId"],
          pick(fs14, "6", calc14, "双手剑", "祀")["charId"]), ("chr_0037_minghe", "chr_0036_jsspsi"))
    try:
        pick(fs14, "6", calc14, "", "某人")
        gave_up = False
    except RuntimeError:
        gave_up = True
    check("不知道武器类型时两个都像：不猜", gave_up, True)
naming = getattr(bnt, "foresight_names", None)
names14 = naming(fs14["chr_0037_minghe"], src14.get_url("client-item-names", "", None), mat14) if naming else {}
check("预览表的新材料按计算器 id（md5）取名，MaaEnd 还没有它", names14.get("item_char_skill_specialize_6"), "跃迁浆体涂片")

print("\n[10-15：祀上线当天 —— 当前 = 已上线最新的祀，下一位 = 已公布的明河；专武附基质建议]")
FIX15 = HERE / "fixtures" / "skland-endfield-1015"
src15 = bnt.RulesSource(FIX15, None)
t15 = bnt.make(src15)
g15, rows15 = rows_by_name(t15)
cur, nxt = (g15["standards"] + [None, None])[:2]
check("两个标准：祀（当前）、明河（下一位）",
      [(x["name"], x["role"], x["label"], x["status"], x["releasedAt"]) for x in g15["standards"]],
      [("祀", "current", "最新六星", "已实装", "2026-10-15"), ("明河", "next", "下一位六星", "未实装", "2026-11-05")])
check("祀的专武是玉中身，祀和玉中身都已进计算器", (cur["weapon"]["name"], cur["sources"]["need"], cur["sources"]["weapon"]),
      ("玉中身", bnt.SRC_CALC, bnt.SRC_CALC))
check("明河：预览表的条目、专武唤月待定", (nxt["sources"]["need"], nxt["sources"]["foresightCharId"], nxt["weapon"]["name"], nxt["weapon"]["status"]),
      (bnt.SRC_FORESIGHT, "chr_0037_minghe", "唤月", "待定"))
check("默认标准 = 祀（旧 App 落到她）", g15["standard"], cur["charId"])
require("游戏层的 rows / caliber / footnote / groups / useSource 都镜像祀",
        g15["rows"] is cur["rows"] and (g15["caliber"], g15["footnote"], g15["groups"], g15["useSource"])
        == (cur["caliber"], cur["footnote"], cur["groups"], cur["useSource"]))
check("caliber 说的是祀", g15["caliber"], "最新六星 祀（2026-10-15 上线）：1→90 全突破、四技能 12、专武 玉中身 1→90；不含天赋")
check("明河的 caliber 叫下一位", nxt["caliber"], "下一位六星 明河（2026-11-05 上线）：1→90 全突破、四技能 12、专武 唤月 1→90；不含天赋")
check("每个标准带自己的节顺序：明河没有计算器分步，按人分节",
      (cur["groups"][:2], nxt["groups"], bool(cur["useSource"]), nxt["useSource"]),
      (["干员精英化", "干员技能升级"], ["明河", "专武 唤月", "明河 + 专武 唤月"], True, ""))
check("coverage 指当前、并写出下一位", (g15["coverage"]["operator"], g15["coverage"]["weapon"], g15["coverage"]["next"], g15["coverage"]["nextError"]),
      ("祀", "玉中身", {"name": "明河", "releasedAt": "2026-11-05", "status": "未实装", "weapon": "唤月"}, ""))


def app_default(game):
    """ark-remote Inventory.swift standardFor() with nothing picked on the phone: the file's
    `standard`, matched by charId else wikiItemId, else the first standard."""
    key = lambda x: x.get("charId") or x.get("wikiItemId") or None  # noqa: E731
    return next((x for x in game["standards"] if key(x) == game["standard"]), game["standards"][0])


check("App 不选时用的就是祀", app_default(g15)["name"], "祀")

ess = cur["weapon"]["essence"]
check("玉中身：三个词条（基础 / 附加 / 技能），用 MaaEnd 的 id 和名字",
      [(x["slot"], x["id"], x["name"]) for x in ess["terms"]],
      [("基础属性", "s1_5", "智识提升"), ("附加属性", "s2_1", "寒冷伤害提升"), ("技能属性", "s3_7", "效益")])
check("玉中身：MaaEnd 武器代号", ess["code"], "wpn_claym_0018")
# CEP, read 2026-10-15: weapons.ts 玉中身 = gat_passive_attr_wisd / gat_passive_attr_icedam / gst_passive_keyword;
# dungeons.ts points whose s2Pool and s3Pool hold the last two (names after the 「·」).
CEP_POINTS = {"玉中身": ["枢纽区", "源石研究园", "矿脉源区", "藏剑谷", "应龙关"],
              "唤月": ["源石研究园", "供能高地", "首墩", "应龙关"]}
check("玉中身：能同时出三条的地方 = CEP 算出来的五处", [x["name"] for x in ess["points"]], CEP_POINTS["玉中身"])
check("全名是游戏里的能量淤积点名", ess["points"][0]["full"], "重度能量淤积点·枢纽区")
check("MaaEnd 的目标选择能勾玉中身", ess["inMaaEndTarget"], True)
require("MaaEnd 那句：目标选择、只勾它、自己挑地方和预刻写",
        all(w in ess["maaend"] for w in ("「目标选择」", "只勾玉中身", "自己挑地方", "预刻写")), ess["maaend"])
check("预刻写那句", ess["engrave"], "预刻写：基础属性选 3 项（含智识提升），附加 / 技能属性固定寒冷伤害提升或效益")
check("数据版本和来源", (ess["dataVersion"], ess["reason"], "保存的应答" in ess["source"]), ("2026-10-08 08:40:17 UTC", "", True))
ess2 = nxt["weapon"]["essence"]
check("唤月：意志提升 / 攻击提升 / 附术，四处 = CEP", ([x["name"] for x in ess2["terms"]], [x["name"] for x in ess2["points"]]),
      (["意志提升", "攻击提升", "附术"], CEP_POINTS["唤月"]))

print("\n[基质词条：按 MaaEnd 自己的匹配法，名字用基质上的叫法]")
pools15 = src15.get_maaend(bnt.ESSENCE_POOLS)
names15 = src15.get_maaend(bnt.ESSENCE_NAMES)
check("武器栏写「源石技艺强度提升」，基质上叫「源石技艺提升」（古渠）",
      [x["name"] for x in bnt.essence_terms(["力量提升·中", "源石技艺强度提升·中", "残暴·千秋旧土"], pools15, names15)],
      ["力量提升", "源石技艺提升", "残暴"])
check("武器栏写「法术提升」，基质上叫「法术伤害提升」（全自动骇新星）",
      [x["id"] + x["name"] for x in bnt.essence_terms(["智识提升·小", "法术提升·小", "昂扬·远途起始"], pools15, names15)],
      ["s1_5智识提升", "s2_5法术伤害提升", "s3_8昂扬"])
check("终结技充能效率：取最长的那个池名", bnt.essence_terms(["敏捷提升·大", "终结技充能效率提升·大", "迸发·x"], pools15, names15)[1]["id"], "s2_11")
check("对不上就是 None，不猜", bnt.essence_terms(["智识提升·大", "不存在的词条·大", "效益·x"], pools15, names15), None)

print("\n[基质建议缺了不拖垮整张表]")
ess_old = rows_by_name(bnt.make(bnt.RulesSource(FIX, None)))[0]["standards"][0]["weapon"]["essence"]
check("旧夹具没有 MaaEnd 的基质文件：表照样建，建议写明缺什么", (ess_old["terms"], ess_old["points"], ess_old["weapon"]),
      (None, None, "寒夜幽影"))
require("缺的原因写出来", ess_old["reason"].startswith("读不到 MaaEnd 的基质数据"), ess_old["reason"])
check("MaaEnd 里没有的武器：写明没有，不猜", bnt.essence_advice(src15, "不存在的武器")["reason"],
      "MaaEnd 的基质数据（数据版本 2026-10-08 08:40:17 UTC）里还没有不存在的武器")


class NoForesight(bnt.RulesSource):
    """The 1015 fixture with the client preview table gone: 明河's numbers cannot be read."""

    def get_url(self, name, url, trim=None, loads=json.loads):
        if name == "client-foresight":
            raise RuntimeError("preview table unreachable")
        return super().get_url(name, url, trim, loads)


t15b = bnt.make(NoForesight(FIX15, None))
g15b = t15b["games"][0]
check("下一位建不成：表照样出，只有祀，原因写进 coverage.nextError",
      ([x["name"] for x in g15b["standards"]], g15b["coverage"]["next"], g15b["coverage"]["nextError"]),
      (["祀"], None, "明河：RuntimeError: preview table unreachable"))
require("summary 提到下一位没建成", "下一位没建成" in bnt.summary(t15b), bnt.summary(t15b))
require("summary 两个都说到", all(w in bnt.summary(t15) for w in ("祀", "玉中身", "下一位 明河", "智识提升/寒冷伤害提升/效益")), bnt.summary(t15))

print("\n[MaaEnd 的文件：游戏机上装着的那份优先（不联网），带注释也读得懂]")
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    inst = Path(tmp) / "maaend"
    (inst / "data" / "EssenceFilter").mkdir(parents=True)
    (inst / "data" / "EssenceFilter" / "matcher_config.json").write_text(
        '{\n  // installed copy\n  "data_version": "installed-1",\n}\n', encoding="utf-8")
    live = bnt.RulesSource.__new__(bnt.RulesSource)   # no Skland login: this read must not touch the network
    live.offline, live.save, live.maaend_dir, live._memo, live.maaend_from = None, None, inst, {}, {}

    def no_net(*_a, **_k):
        raise AssertionError("went to the network although the installed file is there")
    live.get_url = no_net
    check("装着的 matcher_config 读到了", live.get_maaend(bnt.ESSENCE_MATCHER, bnt.trim_essence_matcher), {"data_version": "installed-1"})
    check("来源记作游戏机上装着的 MaaEnd", live.maaend_from, {"maaend-essence-matcher": "游戏机上装着的 MaaEnd"})

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

print("\n[自选箱：只补不够一人份的高阶素材，最缺的先补（用户 2026-09-23 09:05）]")
box = pg["box"]
check("箱子 = material-list 的 SELFSELECT 项", (box["id"], box["name"], box["per"]), ("e55ebf79deddbe781f2a33fb65fd7c61", "高阶培养自选箱Ⅰ", 2))
check("可选 = priorities RARE 五种", box["pickNames"], ["超距辉映管", "D96钢样品四", "快子遴捡晶格", "象限拟合液", "三相纳米片"])
check("已发布的 box 与离线重建一致", box, g["box"])
check("箱子那行仍不算人份", prow["高阶培养自选箱Ⅰ"]["need"], None)
# web/inventory.js applyBox, run in macOS JavaScriptCore (osascript -l JavaScript; the
# tests run on the Mac, deploy-relay.sh). Counts are the account's 2026-09-23 08:4x read
# (BOARD/M4d-资源箱与分节.md): D96 6, 快子 1, 象限 1, 三相 49, 133 boxes.
ids = {r["name"]: r["id"] for r in pg["rows"]}
def apply_box(held):
    counts = {ids["D96钢样品四"]: 6, ids["快子遴捡晶格"]: 1, ids["象限拟合液"]: 1, ids["三相纳米片"]: 49}
    if held:
        counts[box["id"]] = held
    js = ("var window={}; var localStorage={getItem(){return null},setItem(){},removeItem(){}};\n"
          + (REPO / "web/inventory.js").read_text(encoding="utf-8")
          + f"\nvar g={json.dumps(pg, ensure_ascii=False)}; var I=window.Inventory; var rows=I.rowsFor(g,{json.dumps(counts)},{{}});"
          + "var u=I.applyBox(rows,g.box); JSON.stringify({u:u, rows:rows.map(function(r){return [r.name,r.box,r.servings,r.short,r.boxUsed,r.boxLeft]})})")
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", js], capture_output=True, text=True, timeout=60)
    require(f"applyBox 在 JavaScriptCore 里跑通（{held} 箱）", out.returncode == 0, out.stderr[-300:])
    d = json.loads(out.stdout) if out.returncode == 0 else {"u": None, "rows": []}
    return d["u"], {r[0]: r[1:] for r in d["rows"]}
u, rb = apply_box(133)
check("133 箱：用 131、剩 2", u, {"held": 133, "used": 131, "left": 2})
check("D96 补 110 → 1.0 人份、不差", rb["D96钢样品四"][:3], [110, 1, 0])
check("快子 补 20（奇数差 19 进一箱）→ 1.0、不差", rb["快子遴捡晶格"][:3], [20, 1, 0])
check("象限 补 132 → 1.0、不差", rb["象限拟合液"][:3], [132, 1, 0])
check("三相 这套不用，不补", rb["三相纳米片"][:3], [0, None, None])
check("箱子那行记用了几箱、剩几箱", rb["高阶培养自选箱Ⅰ"][3:], [131, 2])
u, rb = apply_box(40)
check("40 箱：全用完", u, {"held": 40, "used": 40, "left": 0})
check("箱子不够：最缺的先补，三行拉平到 0.3，仍标差", [rb[n][:3] for n in ("快子遴捡晶格", "D96钢样品四", "象限拟合液")],
      [[6, 0.3, 13], [32, 0.3, 78], [42, 0.3, 89]])
u, rb = apply_box(0)
check("没箱子：照旧差 N", (u, rb["D96钢样品四"][:3]), ({"held": 0, "used": 0, "left": 0}, [0, 0, 110]))

print()
if fails:
    print(f"✗ {len(fails)} failed: {fails}")
    sys.exit(1)
print(f"all checks passed ({len(TYPHOEUS)} of 提弗洛斯's numbers, {len(WEAPON)} of 寒夜幽影's, {len(PURRCHENA)} of 噗切娜's from the preview table)")
