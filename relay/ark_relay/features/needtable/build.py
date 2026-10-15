"""Build the need table: what the **newest six-star operator's** full build
(with her signature weapon) needs, per material - already before her banner opens.

The App's 库存 page (ark-remote Inventory.swift, ported from the phone page's 库存 tab)
shows, per material, 库存 | 单个角色满练所需 | 人份 (stock ÷ need). Stock is live (the
App asks Skland itself); need is this table. The user's caliber (2026-09-19): the
newest six-star in the official wiki - **including one announced for a future date** -
so the table shows her materials before the banner. Refined 2026-10-15, when the
table built that morning showed only the announced 明河 while 祀 went live at noon; he
said 「app库存那边没有及时更新上新角色的数据」 (the stock page missed the new operator)
and 「养成只按照最新的一个一个来，就是玉中身」 (raise the newest only, one at a time;
玉中身 is the signature weapon of 祀). So there are two standards (next section).

## Standards (`games[].standards[]`)

1. `role: "current"` - the newest entry whose 上线时间 is today or earlier (server date):
   the one he raises now. It is `games[].standard` (the default every App falls back
   to), and the game-level `caliber`, `footnote`, `groups`, `useSource`, `originMissing`,
   `rows` and `coverage` mirror it, so an App that knows nothing of the second standard
   shows this one.
2. `role: "next"` - the announced entry with the nearest future 上线时间, kept visible as
   the next one; absent when nothing is announced. When her day comes she becomes the
   current one with no code change. A failure building her does not fail the table:
   it is written to `coverage.nextError` and the table ships with the current one.

`--char` builds one standard, `role: "named"`. Every standard carries its own `rows`,
`caliber`, `footnote`, `sources`, `weapon`, plus (additive, 2026-10-15) `role`, `label`,
`groups` (its section order: a standard whose numbers are not from the calculator has
per-owner sections 干员养成 / 武器养成 / 多处共用, not the step groups), `useSource` and `originMissing`.
`coverage.next` is `{name, releasedAt, status, weapon}` of the second standard, or null.

## Essence advice (`standards[].weapon.essence`, additive 2026-10-15)

For the signature weapon, the three essence terms it wants and the energy points that
can drop all three (user 2026-10-15: 「顺带加上基质刷取建议」). Data is MaaEnd's own
(`essence_advice`): the installed copy on the game PC (`<maaend_dir>/data/EssenceFilter/`,
`tasks/AutoEssence/Target/Target.json`, `locales/interface/zh_cn.json` - what MaaEnd will
actually farm with), else the same files on MaaEnd's GitHub `v2` branch (the Mac). Shape:

    {"weapon": "玉中身", "code": "wpn_claym_0018",
     "terms": [{"slot": "基础属性", "id": "s1_5", "name": "智识提升"},
               {"slot": "附加属性", "id": "s2_1", "name": "寒冷伤害提升"},
               {"slot": "技能属性", "id": "s3_7", "name": "效益"}],
     "points": [{"name": "枢纽区", "full": "重度能量淤积点·枢纽区"}, ...],
     "engrave": "...", "inMaaEndTarget": true, "maaend": "...",
     "dataVersion": "2026-10-08 08:40:17 UTC", "source": "...", "reason": ""}

* weapon: `weapons_output.json`, the entry whose `names.CN` is the weapon's wiki name.
* term ids: each of its three `skills.CN` up to the `·`, matched to `skill_pools.json`
  slot 1 / 2 / 3 by the longest pool name it starts with - MaaEnd's own
  `cleanDisplayToCanonical` (agent/go-service/essencefilter/matchapi/loader.go).
* term names: MaaEnd's `option.AutoEssenceSkill.s<slot>_<id>` strings - the essence's own
  wording, which differs from the weapon's skill bar for two terms (源石技艺提升 /
  法术伤害提升, see scripts/mac/gem-check.py); the text before `·` when a string is missing.
* points: `locations.json` entries whose `slot2_ids` hold the 附加 id and `slot3_ids` the
  技能 id. Base terms are not per point: MaaEnd's planner (autoessence/plan.go) offers
  the full slot-1 pool everywhere, and its option text says to pick three of the five.
* `inMaaEndTarget`: the weapon code is a case of a checkbox in Target.json, i.e. MaaEnd's
  「目标选择」 mode can be told to farm it (that mode picks the point and the
  pre-engraving itself, plan.go `SelectBestPlan`); `maaend` is the one line saying so.
* Anything missing gives `terms: null, points: null` and a `reason`; it never fails the
  table. Cross-checked 2026-10-15 against CEP (github.com/cmyyx/cep src/data/weapons.ts +
  dungeons.ts): the same three terms and the same five points for the weapon of 祀, and
  for the one of 明河 (relay/tests/test_need_table.py pins both).

Who runs it: the relay, once a server day (needtable.py: rebuilt and put next to the
phone state on COS, where the App reads it), so a new six-star, and her numbers moving
from the wiki cards to the calculator, reach the App without anyone rerunning anything.
By hand, from the Mac (the wrapper reads SKLAND_TOKEN from ~/.config/ark/.env):

    python3 scripts/mac/build-need-tables.py                          # live -> web/data/need.json
    python3 scripts/mac/build-need-tables.py --save-fixtures DIR      # live, and keep the (trimmed) responses
    python3 scripts/mac/build-need-tables.py --offline DIR -o FILE    # rebuild from the saved responses
    python3 scripts/mac/build-need-tables.py --rarity 5               # the newest five-star instead
    python3 scripts/mac/build-need-tables.py --char 莱万汀 --weapon 熔铸火焰   # a named pair instead

Endfield only for now. The `games[]` layer is where 明日方舟 / 鸣潮 go later; inside a
game, `standards[]` holds the build standards (above) and `rows` mirrors the first.

## Who (official Skland wiki, `docs/SKLAND-API.md` §8)

1. `GET /web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true` - subtype 干员 and
   subtype 武器; rarity tag = `brief.subTypeList[subTypeId=10000].value` (`10006`
   six-star, `10005` five-star); `brief.dotType` `label_type_preview` = announced.
2. `GET /web/v1/wiki/item/info?id=<itemId>` - the entry's attributes: operators carry
   `上线时间` and `主要获取方式`, weapons those two and `类型`.
3. Sorted by `上线时间`, future dates included; the current and the next standard are
   picked from that list against the server date (above); `status` says 已实装 or
   未实装 against the same date.
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

import gzip
import hashlib
import json
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ZONAI = "https://zonai.skland.com"
SERVER_TZ = timezone(timedelta(hours=8))
# `built`, the same on the Mac and on the machine (time.strftime's %Z is "JST" on one
# and the Windows zone name on the other): server time, a fixed suffix. The App reads
# the date part.
BUILT_FORMAT = "%Y-%m-%d %H:%M UTC+8"
# Third-party mirrors of client data, used only when neither the calculator nor the
# wiki entry has the operator's numbers yet (source 3 above).
FORESIGHT_URL = "https://raw.githubusercontent.com/rmxlinux/EndfieldData/main/TableCfg/ForesightCharGrowthTable.json"
ITEM_NAMES_URL = "https://raw.githubusercontent.com/MaaEnd/MaaEnd/v2/assets/locales/interface/zh_cn.json"
# MaaEnd's essence data (the essence advice above): (fixture name, path inside an installed
# MaaEnd). A release is the repo's assets/ flattened (relay/tests/gamesim/upstream/*/SOURCE.txt,
# "prefix assets/"), so the GitHub copy is MAAEND_RAW + the same path.
MAAEND_RAW = "https://raw.githubusercontent.com/MaaEnd/MaaEnd/v2/assets/"
ESSENCE_WEAPONS = ("maaend-essence-weapons", "data/EssenceFilter/weapons_output.json")
ESSENCE_POOLS = ("maaend-essence-pools", "data/EssenceFilter/skill_pools.json")
ESSENCE_LOCATIONS = ("maaend-essence-locations", "data/EssenceFilter/locations.json")
ESSENCE_MATCHER = ("maaend-essence-matcher", "data/EssenceFilter/matcher_config.json")
ESSENCE_TARGET = ("maaend-essence-target", "tasks/AutoEssence/Target/Target.json")
ESSENCE_NAMES = ("maaend-essence-names", "locales/interface/zh_cn.json")
# The three essence slots, in the order of a weapon's three skills (MaaEnd slot 1 / 2 / 3;
# its option labels are 「基础属性」 and 「附加 / 技能属性」).
ESSENCE_SLOTS = ("基础属性", "附加属性", "技能属性")
STAR = {"6": "六", "5": "五", "4": "四"}

GAME, GAME_ID = "终末地", "endfield"
SOURCE = ("最新六星与其专武按森空岛百科的「上线时间」「类型」「主要获取方式」定；用量优先森空岛养成计算器 rules，"
          "计算器未收录时读百科词条里的养成材料卡片，两者都没有时读客户端预览表；名字和图标取自 material-list。"
          "方法见 docs/SKLAND-API.md §8")
# Skills to 12: measured in the calculator's rules pulled 2026-09-19 (fixtures/skland-endfield,
# rules-char-9de117d5...): every skill's levels[].targetLevel runs 2..12.
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
HIGH_TIER = {"D96钢样品四", "超距辉映管", "快子遴捡晶格", "象限拟合液", "三相纳米片", "跃迁浆体涂片", "高阶培养自选箱Ⅰ"}
# Skland's own figure, https://game.skland.com/tools/endfield/cost-calculator (quoted below).
LAG_MINUTES = 30
# The official calculator page's own words (game.skland.com/tools/endfield/cost-calculator,
# quoted in scripts/mac/lib/snapshot.py on 2026-08-28): 「仓库资源和干员数据等信息的同步，
# 会有 30 分钟左右的延迟」. Stated by Skland, not measured here.
LAG_NOTE = "森空岛的仓库数比游戏里晚，官方养成计算器页面写的是 30 分钟"
# The preview table's lists that carry the full build (stage 4) and the talent-tainted ones.
FORESIGHT_LISTS = ("skNur", "skCol", "skPreItm", "skPreMat", "upAdv", "upCol", "upPre")
FORESIGHT_WITH_TALENTS = {"协议棱柱", "协议棱柱组", "折金票"}
# The preview table keys by internal code (chr_0037_minghe) and names nobody; MaaEnd's
# strings name items, not operators. Hers is found by elimination: an entry whose code
# the calculator lists (its ids are md5 of the code: chr_0017_yvonne, chr_0027_tangtang
# and chr_0038_purrche all are, 2026-10-14) is someone released, not her; of the rest,
# the one whose weapons (`weaponIds`, wpn_<kind>_NNNN) are of her weapon type. Code kind
# -> the wiki's weapon type, measured 2026-10-14 over every six-star weapon: MaaEnd's
# `iconRecognition.name.wpn_*` names against the wiki entries' 「类型」 (claym 18 / funnel 22
# / lance 14 / pistol 12 / sword 26 names, no exception).
WEAPON_KIND = {"claym": "双手剑", "funnel": "施术单元", "lance": "长柄武器", "pistol": "手铳", "sword": "单手剑"}
# The catalog's tag group for an operator's weapon type (`filterTagTree` 10208, titled 「武器」;
# wiki entry 2503 carries tag 10219 and 2338 tag 10216 on 2026-10-14).
WEAPON_TAG_GROUP = "10208"

# Sections by use (the rows' `group`, user 2026-09-23: 「按用途分类…哪些是角色，哪些是武器」).
# Which step a material serves is read off the calculator rules (charBreak* nodes,
# skills[].levels[].targetLevel, weapon breakthroughs, the two level tables); each
# section name is the official wiki's own wording, quoted with its entry (wiki ids 217,
# 755, 1809, 19) in USE_SOURCE. Skill levels up to SKILL_UP_MAX are upgrades - the
# wiki's own limit for them - and 10-12 are mastery.
# A material one build uses at more than one step goes to USE_SHARED, with every step
# and its count in `uses`. Only calculator rules say which step; a build read from the
# wiki cards or the preview table gets per-owner sections 干员养成 / 武器养成 / 多处共用.
USE_ELITE, USE_SKILL_UP, USE_SKILL_MASTER, USE_CHAR_LV = "干员精英化", "干员技能升级", "干员技能专精", "干员等级提升"
USE_WEAPON_BREAK, USE_WEAPON_LV, USE_SHARED = "武器突破", "武器等级提升", "多处共用"
USE_ORDER = (USE_ELITE, USE_SKILL_UP, USE_SKILL_MASTER, USE_CHAR_LV, USE_WEAPON_BREAK, USE_WEAPON_LV, USE_SHARED)
# Sections for a build without calculator step rules: by whom it serves, still named by use.
OWNER_CHAR, OWNER_WEAPON = "干员养成", "武器养成"
# 2-9 are upgrades, 10-12 mastery: the official wiki's own line, quoted in USE_SOURCE from its
# entry for that leaf material: 「作为干员升级等级不高于9级的技能时的消耗素材」 (read 2026-09-23).
SKILL_UP_MAX = 9
USE_SOURCE = ("用途按森空岛养成计算器 rules 里每种材料出现在哪一步（精英化各步 charBreak*、技能 2–9 / 10–12 级、武器突破、等级表）；"
              "步骤名取官方百科原文：三相纳米片「用于干员精英化、武器突破、干员技能专精」、至晶多齿叶「作为干员升级等级不高于9级的技能时的消耗素材」、"
              "折金票「干员及武器等级提升」；一种材料用在两步及以上的放「多处共用」，每步用量见 uses")

# Where each material comes from (user 2026-09-23: 「哪些是采集物哪些是体力消耗的产出物需要做区分」):
# the material's own official wiki entry, chapter 物品来源, one line per way. A line
# naming the protocol space (协议空间) is a sanity stage, per the wiki's sanity entry
# (id 17) quoted in ORIGIN_SOURCE; a line saying 采集 is gathering; the rest stay verbatim.
ORIGIN_CHAPTER = "物品来源"
ORIGIN_GATHER, ORIGIN_STAGE, ORIGIN_OTHER = "采集物", "理智关卡产出", "其它来源"
ORIGIN_SOURCE = ("怎么来取自森空岛百科每种材料词条的「物品来源」原文，逐条：含「采集」的算采集，含「协议空间」的算理智关卡"
                 "（百科「理智」词条：完成协议空间等玩法的战斗后，需要消耗理智领取奖励），其余原文放「其它」；"
                 "kind 按 采集物 → 理智关卡产出 → 其它来源 的先后取第一个有的")
# The self-select box. Which item is the box and which materials it can open come from
# material-list: materialSpecials type SELFSELECT_* (高阶培养自选箱Ⅰ) and priorities[RARE]
# (the five high-tier materials). What one box gives comes from the official calculator's
# own script (game.skland.com/tools/endfield/cost-calculator, CostCalculator-BGMqCZak.js +
# share_bottom_decorator-cN9de4XQ.js, read 2026-09-23 - BOARD/M4d-资源箱与分节.md): the
# box it offers is ⌈RARE total ÷ 2⌉ capped by what is held, and the pop-up's
# cost_calc_box_acquisition_tip takes count = boxes × 2, so one box = 2 of one RARE material.
# How the page spends them is the user's rule (2026-09-23 09:05): only materials short of
# one build, the shortest first, until covered or out of boxes; still short -> still 差 N.
BOX_PER = 2
BOX_SOURCE = ("箱子与可选材料取自森空岛养成计算器 material-list（materialSpecials 的 SELFSELECT 项、priorities 的 RARE 五种）；"
              "一箱开出任选一种 2 个，按官方养成计算器页面脚本（箱数 = ⌈高阶素材总需 ÷ 2⌉，说明句参数 count = 箱数 × 2）")
BOX_RULE = ("用户 2026-09-23 09:05：按不足的资源用资源箱去折算，还不足的标出来说不足，否则算已经充足；"
            "折算时依旧按人数算多少倍")


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


def github_doors(url: str) -> list[str]:
    """One raw.githubusercontent.com URL as the doors the game PC can reach: the three
    jsDelivr mirrors of the same repo path (order and figures in
    selfupdate._alternates, measured from the PC 2026-08-21), then the URL itself; any
    other URL is its own only door."""
    prefix = "https://raw.githubusercontent.com/"
    parts = url[len(prefix):].split("/", 3) if url.startswith(prefix) else []
    if len(parts) < 4:
        return [url]
    owner, repo, branch, path = parts
    ref = f"gh/{owner}/{repo}@{branch}/{path}"
    return [f"https://fastly.jsdelivr.net/{ref}", f"https://cdn.jsdelivr.net/{ref}",
            f"https://gcore.jsdelivr.net/{ref}", url]


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
    `wiki-docs.json`. MaaEnd's essence files come from the installed MaaEnd when
    `maaend_dir` has them (`get_maaend`). Every answer is kept for the rest of the
    build (`_memo`): the second standard reads the same catalog, material-list and
    物品来源 entries as the first, and asks Skland for none of them again."""

    MERGED = {"wiki-item-": "wiki-items.json", "wiki-doc-": "wiki-docs.json", "wiki-origin-": "wiki-origins.json"}

    def __init__(self, offline: Path | None, save: Path | None, token: str = "", maaend_dir: Path | None = None):
        """Live needs `token` (the Skland token: the machine's cfg.skland_token, or
        SKLAND_TOKEN of the Mac's .env read by the wrapper). `maaend_dir`: the installed
        MaaEnd (the machine's cfg.maaend_dir); None on the Mac."""
        self.offline, self.save = offline, save
        self.maaend_dir = Path(maaend_dir) if maaend_dir else None
        self.cred = None
        self._memo: dict = {}
        # Where each MaaEnd file came from (fixture name -> words for `essence.source`).
        self.maaend_from: dict[str, str] = {}
        if offline is None:
            from ark_relay.core import skland  # noqa: PLC0415 - only the live path needs it
            self.skland = skland
            if not token:
                raise RuntimeError("没有森空岛令牌（SKLAND_TOKEN）")
            self.cred = _retry(lambda: skland.refresh(skland.login(token)))

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
        if name in self._memo:
            return self._memo[name]
        if self.offline is not None:
            self._memo[name] = self._load(name)
            return self._memo[name]
        url = f"{ZONAI}{path}" + (f"?{query}" if query else "")

        def once():
            # 30 s: a whole build is 55 s for about 115 requests (measured from the Mac 2026-10-14),
            # so one answer slower than 30 s is a stall, retried by _retry.
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
        self._memo[name] = data
        return data

    def get_url(self, name: str, url: str, trim=None, loads=json.loads) -> dict:
        """A plain JSON document from elsewhere (the client-data mirrors, MaaEnd's files)."""
        if name in self._memo:
            return self._memo[name]
        if self.offline is not None:
            self._memo[name] = self._load(name)
            return self._memo[name]

        def once():
            # The jsDelivr doors first: from the game PC in Shanghai a TLS handshake with
            # raw.githubusercontent.com was reset (relay.log 2026-10-14 10:30:06, WinError
            # 10054), the same route selfupdate._alternates measured at 2/8. 60 s each: the
            # MaaEnd strings are 217 KB, 0.24 s from the Mac (measured 2026-10-14).
            err: Exception = RuntimeError("no door answered")
            for door in github_doors(url):
                try:
                    with urllib.request.urlopen(urllib.request.Request(door, headers={"User-Agent": "ark-need-table"}),
                                                timeout=60) as r:
                        return loads(r.read().decode("utf-8"))
                except Exception as e:  # noqa: BLE001 - the next door may answer
                    err = e
            raise err

        data = _retry(once, tries=2)
        data = trim(data) if trim else data
        self._store(name, data)
        self._memo[name] = data
        return data

    def get_maaend(self, what: tuple[str, str], trim=None) -> dict:
        """One of MaaEnd's files, `what` = (fixture name, path inside a MaaEnd install):
        the installed one when `maaend_dir` has it (MaaEnd farms with that copy), else
        MaaEnd's GitHub `v2` branch. Both are read as JSON with comments (MaaEnd's
        task files carry them; mastercfg._strip_jsonc)."""
        name, rel = what
        if name in self._memo:
            return self._memo[name]
        from ark_relay.core.mastercfg import _strip_jsonc  # noqa: PLC0415 - only this read needs it
        if self.offline is not None:
            self.maaend_from[name] = "保存的应答"
            return self.get_url(name, "")
        f = self.maaend_dir / rel if self.maaend_dir else None
        if f is not None and f.is_file():
            data = json.loads(_strip_jsonc(f.read_text(encoding="utf-8")))
            data = trim(data) if trim else data
            self._store(name, data)
            self._memo[name] = data
            self.maaend_from[name] = "游戏机上装着的 MaaEnd"
            return data
        self.maaend_from[name] = "MaaEnd 的 GitHub v2 分支"
        return self.get_url(name, MAAEND_RAW + rel, trim, loads=lambda t: json.loads(_strip_jsonc(t)))


# ── trims: what each response is cut down to when saved as a fixture ──────────

def _weapon_tags(d: dict, subtype: str) -> dict[str, str]:
    """tag id -> weapon type name of `subtype`'s 「武器」 tag group (absent in fixtures saved before 2026-10-14)."""
    sub = next((s for s in d["catalog"][0]["typeSub"] if s["name"] == subtype), {})
    return sub.get("weaponTags") or {}


def _catalog_items(d: dict, subtype: str) -> list[dict]:
    return next((s for s in d["catalog"][0]["typeSub"] if s["name"] == subtype), {"items": []})["items"]


def trim_catalog(d: dict) -> dict:
    """干员 and 武器 with their tags; every other subtype only as id -> name (the
    material cards in wiki documents point at 物品 / 贵重品库 entries by id)."""
    out = {"catalog": [{"typeSub": []}]}
    for sub in d["catalog"][0]["typeSub"]:
        if sub["name"] in ("干员", "武器"):
            tags = next((g.get("children") or [] for g in sub.get("filterTagTree") or [] if g.get("id") == WEAPON_TAG_GROUP), [])
            out["catalog"][0]["typeSub"].append({"name": sub["name"], "weaponTags": {t["id"]: t["name"] for t in tags}, "items": [
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


def trim_essence_weapons(d: dict) -> dict:
    """weapons_output.json: weapon code -> its Chinese name and three Chinese skill strings."""
    return {code: {"name": str((w.get("names") or {}).get("CN") or ""), "skills": list((w.get("skills") or {}).get("CN") or []),
                   "type": w.get("weapon_type", ""), "rarity": w.get("rarity")}
            for code, w in d.items() if isinstance(w, dict)}


def trim_essence_pools(d: dict) -> dict:
    """skill_pools.json: slot1 / slot2 / slot3 -> [{id, cn}]."""
    return {slot: [{"id": int(e["id"]), "cn": str(e.get("cn") or "")} for e in d.get(slot) or []]
            for slot in ("slot1", "slot2", "slot3")}


def trim_essence_locations(d: list) -> list:
    """locations.json: each energy point's name and the 附加 / 技能 term ids it drops."""
    return [{"name": str(e.get("name") or ""), "slot2_ids": [int(x) for x in e.get("slot2_ids") or []],
             "slot3_ids": [int(x) for x in e.get("slot3_ids") or []]} for e in d]


def trim_essence_matcher(d: dict) -> dict:
    """matcher_config.json: only its data version."""
    return {"data_version": str(d.get("data_version") or "")}


def trim_essence_target(d: dict) -> dict:
    """Target.json (目标选择): every checkbox option -> its case names, the weapon codes it can farm."""
    return {k: [c.get("name") for c in v.get("cases") or []] for k, v in (d.get("option") or {}).items()
            if isinstance(v, dict) and v.get("type") == "checkbox"}


def trim_essence_names(d: dict) -> dict:
    """MaaEnd's `option.AutoEssenceSkill.s<slot>_<id>` strings: the essence terms' own names."""
    pre = "option.AutoEssenceSkill."
    return {k[len(pre):]: v for k, v in d.items() if k.startswith(pre)}


# ── essence advice (the docstring's section) ──────────────────────────────────

def essence_terms(skills: list, pools: dict, names: dict) -> list[dict] | None:
    """A weapon's three skill strings as essence terms, or None when one does not match:
    the text before `·`, matched to its slot's pool by the longest pool name it starts with
    (MaaEnd's cleanDisplayToCanonical), named by MaaEnd's option string for that term."""
    out = []
    for i, text in enumerate(skills[:3]):
        core = str(text).split("·")[0].strip()
        hit = max((e for e in pools.get(f"slot{i + 1}") or [] if e["cn"] and core.startswith(e["cn"])),
                  key=lambda e: len(e["cn"]), default=None)
        if hit is None:
            return None
        tid = f"s{i + 1}_{hit['id']}"
        out.append({"slot": ESSENCE_SLOTS[i], "id": tid, "name": names.get(tid) or core})
    return out if len(out) == 3 else None


def _essence(src: RulesSource, weapon: str, out: dict) -> None:
    weapons = src.get_maaend(ESSENCE_WEAPONS, trim_essence_weapons)
    out["dataVersion"] = src.get_maaend(ESSENCE_MATCHER, trim_essence_matcher).get("data_version", "")
    hits = [(code, w) for code, w in weapons.items() if w.get("name") == weapon]
    if len(hits) != 1:
        out["reason"] = (f"MaaEnd 的基质数据（数据版本 {out['dataVersion'] or '未知'}）里"
                         + (f"还没有{weapon}" if not hits else f"有 {len(hits)} 把叫{weapon}的武器，不猜是哪把"))
        return
    code, w = hits[0]
    out["code"] = code
    terms = essence_terms(w.get("skills") or [], src.get_maaend(ESSENCE_POOLS, trim_essence_pools),
                          src.get_maaend(ESSENCE_NAMES, trim_essence_names))
    if terms is None:
        out["reason"] = f"MaaEnd 的基质数据里{weapon}的词条 {w.get('skills')} 对不上它的词条表"
        return
    s2, s3 = (int(t["id"].split("_")[1]) for t in terms[1:])
    points = [{"name": e["name"].split("·")[-1], "full": e["name"]}
              for e in src.get_maaend(ESSENCE_LOCATIONS, trim_essence_locations)
              if s2 in e["slot2_ids"] and s3 in e["slot3_ids"]]
    in_target = any(code in cases for cases in src.get_maaend(ESSENCE_TARGET, trim_essence_target).values())
    t1, t2, t3 = (t["name"] for t in terms)
    # The two option texts MaaEnd shows for a point's pre-engraving: 「选择 3 项基础属性」 and
    # 「选择 1 项该地区可用的附加属性或技能属性」 (option.AutoEssenceLocationSlot1 / Secondary).
    # Target mode (plan_action.go TargetPlanAction): only ticked weapons with no matching essence
    # in the bag count; the plan that covers the most of them wins (plan.go SelectBestPlan), and
    # with none left the task ends - so ticking only this weapon is what makes it farm for it.
    out.update(terms=terms, points=points, inMaaEndTarget=in_target,
               engrave=f"预刻写：基础属性选 3 项（含{t1}），附加 / 技能属性固定{t2}或{t3}" if points else "",
               maaend=(f"MaaEnd「基质刷取」切到「目标选择」、只勾{weapon}：它自己挑地方、自己预刻写，背包里有了对得上的基质就停"
                       if in_target else f"MaaEnd「目标选择」里还没有{weapon}，只能照上面的地方手动刷"),
               reason="" if points else f"没有一处能量淤积点同时出{t2}和{t3}")


def essence_advice(src: RulesSource, weapon: str) -> dict:
    """`standards[].weapon.essence` (the docstring's section). Never raises: whatever is
    missing leaves `terms` / `points` null and says why in `reason`."""
    out = {"weapon": weapon, "code": "", "terms": None, "points": None, "engrave": "", "inMaaEndTarget": False,
           "maaend": "", "dataVersion": "", "source": "", "reason": ""}
    try:
        _essence(src, weapon, out)
    except Exception as e:  # noqa: BLE001 - advice is optional; the need table must still ship
        out.update(terms=None, points=None, reason=f"读不到 MaaEnd 的基质数据：{type(e).__name__}: {e}")
    where = "、".join(dict.fromkeys(src.maaend_from.values())) or "无"
    out["source"] = ("词条和能量淤积点取自 MaaEnd 的 data/EssenceFilter（weapons_output / skill_pools / locations），"
                     f"词条名取自 MaaEnd 界面文字，「目标选择」能勾哪些武器取自它的 Target.json；来自{where}")
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


def self_select_box(raw: dict, mat: dict[str, dict]) -> dict | None:
    """games[].box: the first SELFSELECT item (the calculator takes the first too) and
    the RARE materials it opens into; None when material-list names neither."""
    sel = [s["id"] for s in raw.get("materialSpecials") or [] if str(s.get("type", "")).startswith("SELFSELECT")]
    picks = next((p["ids"] for p in raw.get("priorities") or [] if p.get("type") == "RARE"), [])
    if not sel or not picks or sel[0] not in mat:
        return None
    name = mat[sel[0]]["name"]
    return {"id": sel[0], "name": name, "per": BOX_PER, "picks": list(picks),
            "pickNames": [mat[i]["name"] for i in picks if i in mat],
            "note": f"箱 N = {name}补进来的数：一箱换任选一种高阶素材 {BOX_PER} 个，只补不够一人份的，人份最低的先补",
            "source": BOX_SOURCE, "rule": BOX_RULE}


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


def char_uses(rule: dict) -> dict[str, Counter]:
    """material id -> {use: count} for the same breakthroughs and skills `char_need` sums."""
    c = rule["chars"][0]
    out: dict[str, Counter] = {}
    for b in c["breakthroughs"]:
        if not b["materials"]:
            continue
        if not str(b.get("nodeId", "")).startswith("charBreak"):
            raise RuntimeError(f"breakthrough node {b.get('nodeId')!r} carries materials; no use name is known for it")
        for m in b["materials"]:
            out.setdefault(m["resourceId"], Counter())[USE_ELITE] += int(m["count"])
    for s in c["skills"]:
        for lv in s["levels"]:
            t = int(lv["targetLevel"])
            if t <= MAX_SKILL_LEVEL:
                for m in lv["materials"]:
                    out.setdefault(m["resourceId"], Counter())[USE_SKILL_UP if t <= SKILL_UP_MAX else USE_SKILL_MASTER] += int(m["count"])
    return out


def weapon_uses(wneed: Counter) -> dict[str, Counter]:
    """Every weapon material (rules or the 武器信息 cards) is a breakthrough material."""
    return {mid: Counter({USE_WEAPON_BREAK: n}) for mid, n in wneed.items()}


def trim_wiki_origin(d: dict) -> dict:
    """A wiki entry cut down to its 物品来源 chapter: one string per block, in order."""
    doc = (d.get("item") or {}).get("document") or {}
    dm, wc = doc.get("documentMap") or {}, doc.get("widgetCommonMap") or {}

    def text(o) -> str:
        if isinstance(o, dict):
            return (o["text"] if isinstance(o.get("text"), str) else "") + "".join(
                text(v) for k, v in o.items() if not (k == "text" and isinstance(v, str)))
        if isinstance(o, list):
            return "".join(text(v) for v in o)
        return ""
    lines = []
    for ch in doc.get("chapterGroup") or []:
        if ch.get("title") != ORIGIN_CHAPTER:
            continue
        for w in ch.get("widgets") or []:
            for tab in ((wc.get(w.get("id")) or {}).get("tabDataMap") or {}).values():
                c = dm.get((tab or {}).get("content")) or {}
                bm = c.get("blockMap") or {}
                for bid in c.get("blockIds") or list(bm):
                    t = text(bm.get(bid)).strip()
                    if t:
                        lines.append(t)
    return {"itemId": (d.get("item") or {}).get("itemId"), "name": (d.get("item") or {}).get("name"), "lines": lines}


def material_origin(src: RulesSource, name: str, wiki_ids: dict[str, str]) -> dict | None:
    """The material's 物品来源 lines sorted into 采集 / 理智关卡 / 其它; None when the wiki has
    no entry or the entry has no 物品来源 lines (the caller lists those, nothing is guessed)."""
    wid = wiki_ids.get(name)
    if not wid:
        return None
    lines = src.get(f"wiki-origin-{wid}", "/web/v1/wiki/item/info", f"id={wid}", trim_wiki_origin)["lines"]
    if not lines:
        return None
    by = {"采集": [l for l in lines if "采集" in l]}
    by["理智关卡"] = [l for l in lines if "协议空间" in l and l not in by["采集"]]
    by["其它"] = [l for l in lines if l not in by["采集"] and l not in by["理智关卡"]]
    kind = ORIGIN_GATHER if by["采集"] else ORIGIN_STAGE if by["理智关卡"] else ORIGIN_OTHER
    return {"kind": kind, **by, "wikiItemId": wid}


def folded_origin(parts: list[dict]) -> dict | None:
    """An exp row's origin: the union of the origins of the cards folded into it, each
    line once, in the order of `parts`; kind by material_origin's rule (first present).
    None when none of the cards has an origin."""
    got = [r for r in parts if r.get("origin")]
    if not got:
        return None
    by = {k: list(dict.fromkeys(l for r in got for l in r["origin"][k])) for k in ("采集", "理智关卡", "其它")}
    kind = ORIGIN_GATHER if by["采集"] else ORIGIN_STAGE if by["理智关卡"] else ORIGIN_OTHER
    return {"kind": kind, **by, "wikiItemId": None,
            "from": [r["name"] for r in got], "wikiItemIds": [r["origin"]["wikiItemId"] for r in got]}


def folded_cards(rows: list[dict], sid: str) -> tuple[list[dict], str, str]:
    """The exp cards folded into `sid`, highest rarity first; the icon an exp row borrows
    (the first of them that has one) and the note's words naming it ("" when none has)."""
    parts = sorted((r for r in rows if r.get("sumInto") == sid), key=lambda r: (-(r["rarity"] or 0), r["name"]))
    top = next((r for r in parts if r["icon"]), None)
    return parts, top["icon"] if top else "", f"；图标借{top['name']}" if top else ""


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
    wtags = _weapon_tags(cat, subtype)
    rows = []
    for it in items:
        info = src.get(f"wiki-item-{it['itemId']}", "/web/v1/wiki/item/info", f"id={it['itemId']}", trim_wiki_item)
        item = info.get("item") or {}
        attrs = item.get("attrs") or wiki_attrs(item)
        rows.append({"name": it["name"], "wikiItemId": str(it["itemId"]),
                     "onlineDate": parse_online_date(attrs.get("上线时间", "")), "onlineText": attrs.get("上线时间", ""),
                     "obtain": attrs.get("主要获取方式", ""), "kind": attrs.get("类型", ""),
                     "dotType": it["brief"].get("dotType") or "", "publishedAtTs": int(it.get("publishedAtTs") or 0),
                     "weaponType": next((wtags[x["value"]] for x in it["brief"].get("subTypeList", [])
                                         if x.get("subTypeId") == WEAPON_TAG_GROUP and x.get("value") in wtags), "")})
    return rows


def wiki_item_names(src: RulesSource) -> dict[str, str]:
    """Every catalog entry's id -> name (the material cards point at 物品 ids)."""
    cat = src.get("wiki-catalog", "/web/v1/wiki/item/catalog", "typeMainId=1&onlyOnline=true", trim_catalog)
    return {str(it["itemId"]): it["name"] for sub in cat["catalog"][0]["typeSub"] for it in sub["items"]}


def wiki_material_ids(src: RulesSource) -> dict[str, str]:
    """name -> wiki item id for the 物品 and 贵重品库 listings (where every calculator material has its entry)."""
    cat = src.get("wiki-catalog", "/web/v1/wiki/item/catalog", "typeMainId=1&onlyOnline=true", trim_catalog)
    return {it["name"]: str(it["itemId"]) for sub in cat["catalog"][0]["typeSub"] if sub["name"] in ("物品", "贵重品库")
            for it in sub["items"]}


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


def foresight_entry(fs: dict, rarity: str, calc_ids: set[str], wtype: str, who: str) -> dict:
    """Her entry of the preview table (see WEAPON_KIND): of `rarity`, not listed by the
    calculator, then of her weapon type when more than one is left. Anything but exactly
    one raises: a guess would put someone else's numbers on the page."""
    cands = [e for e in fs.values() if str(e.get("rarity")) == rarity
             and hashlib.md5(str(e.get("charId", "")).encode("utf-8")).hexdigest() not in calc_ids]
    if len(cands) > 1 and wtype:
        cands = [e for e in cands if wtype in {WEAPON_KIND.get(w.split("_")[1] if w.count("_") >= 2 else "", "")
                                               for w in e.get("weaponIds") or []}]
    if len(cands) != 1:
        codes = "、".join(str(e.get("charId")) for e in cands) or "无"
        raise RuntimeError(f"{who}: not in the calculator, no material cards in the wiki entry, and the preview "
                           f"table has {len(cands)} unlisted {rarity}-star entries of weapon type {wtype or '?'} "
                           f"({codes}) - cannot pick hers")
    return cands[0]


def foresight_names(entry: dict, maaend: dict[str, str], mat: dict[str, dict]) -> dict[str, str]:
    """Item code -> name for the codes of `entry`: the calculator's material-list first
    (its ids are md5 of the code - item_char_skill_specialize_6 -> 跃迁浆体涂片, which
    MaaEnd's strings did not have on 2026-10-14), MaaEnd's `iconRecognition.name.*` else
    (折金票 = item_gold is not a calculator material)."""
    out = dict(maaend)
    for st in (entry.get("stageMaterials") or {}).values():
        for key, codes in st.items():
            if key.endswith("Ids"):
                for code in codes:
                    m = mat.get(hashlib.md5(str(code).encode("utf-8")).hexdigest())
                    if m and m.get("name"):
                        out[code] = m["name"]
    return out


def foresight_need(entry: dict, item_names: dict[str, str]) -> tuple[Counter, int]:
    """{material name: count} and gold from the preview table's highest stage."""
    stages = entry["stageMaterials"]
    st = stages[str(max(int(k) for k in stages))]
    need, gold = Counter(), 0
    for key in FORESIGHT_LISTS:
        for iid, cnt in zip(st.get(key + "Ids", []), st.get(key + "Cnt", []), strict=True):
            nm = item_names.get(iid)
            if not nm:
                raise RuntimeError(f"preview-table item id without a name: {iid}")
            need[nm] += int(cnt)
    for key in ("skGold", "upGold"):
        for iid, cnt in zip(st.get(key + "Ids", []), st.get(key + "Cnt", []), strict=True):
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


def pick_standards(ranked: list[dict], today: str, rarity: str, char_name: str = "") -> list[tuple[str, str, str, str]]:
    """(who, role, label, chosenBy) of each standard, in order (the docstring's Standards
    section): the newest released entry, then the announced one with the nearest date."""
    star = STAR[rarity]
    if char_name:
        return [(char_name, "named", "指定干员", "--char")]
    released = [e for e in ranked if e["onlineDate"] <= today]
    upcoming = [e for e in ranked if e["onlineDate"] > today]
    picks = []
    if released:
        picks.append((released[0]["name"], "current", f"最新{star}星", f"百科上线时间最新、已上线的{star}星"))
    if upcoming:
        picks.append((upcoming[-1]["name"], "next", f"下一位{star}星", f"百科里已公布、上线日期最近的未上线{star}星"))
    return picks


def build(src: RulesSource, pulled_at: str, today: str, char_name: str = "", weapon_name: str = "",
          rarity: str = "6") -> dict:
    raw_mat = src.get("material-list", "/web/v1/game/endfield/calculate/material-list")
    mat = material_table(raw_mat)
    box = self_select_box(raw_mat, mat)
    listed = src.get("search-chars", "/web/v1/game/endfield/search-chars", "", trim_search_chars)["chars"]
    weapons_listed = src.get("search-weapons", "/web/v1/game/endfield/search-weapons", "", trim_search_weapons)["weapons"]
    ctx = {"mat": mat, "calc_ids": {c["name"]: c["id"] for c in listed},
           "weapon_types": {c["name"]: str(((c.get("weaponType") or {}).get("value")) or "") for c in listed},
           "weapons_listed": weapons_listed, "wid_of": {w["name"]: w["id"] for w in weapons_listed},
           "wnames": wiki_item_names(src), "today": today, "rarity": rarity}

    # 1. who - from the official wiki: the current standard and the announced next one
    ops = wiki_entries(src, "干员", rarity)
    _top, ranked = newest(ops)
    picks = pick_standards(ranked, today, rarity, char_name)
    if not picks:
        raise RuntimeError("no entry to build a standard for")
    standards, next_error = [], ""
    for i, (who, role, label, chosen_by) in enumerate(picks):
        try:
            standards.append(build_standard(src, ctx, ops, who, role, label, chosen_by, weapon_name if i == 0 else ""))
        except Exception as exc:  # the next one is optional; the current one is not (re-raised)
            if i == 0:
                raise
            next_error = f"{who}：{type(exc).__name__}: {exc}"
    first = standards[0]
    nxt = next((s for s in standards[1:] if s["role"] == "next"), None)
    return {
        "built": pulled_at,
        "games": [{
            "game": GAME, "gameId": GAME_ID, "caliber": first["caliber"], "footnote": first["footnote"], "source": SOURCE,
            "sections": list(SECTIONS), "groups": first["groups"], "useSource": first["useSource"],
            "originSource": ORIGIN_SOURCE, "originMissing": first["originMissing"],
            "lagMinutes": LAG_MINUTES, "lagNote": LAG_NOTE, "box": box,
            "standard": first["charId"] or first["wikiItemId"], "standards": standards, "rows": first["rows"],
            "coverage": {
                "operator": first["name"], "releasedAt": first["releasedAt"], "status": first["status"],
                "weapon": first["weapon"]["name"], "weaponStatus": first["weapon"]["status"], "asOf": today,
                "sources": first["sources"],
                "candidates": [f"{r['name']} {r['onlineDate']}{'（未实装）' if r['onlineDate'] > today else ''}" for r in ranked],
                "next": ({"name": nxt["name"], "releasedAt": nxt["releasedAt"], "status": nxt["status"],
                          "weapon": nxt["weapon"]["name"]} if nxt else None),
                "nextError": next_error,
            },
        }],
    }


def build_standard(src: RulesSource, ctx: dict, ops: list[dict], who: str, role: str, label: str, chosen_by: str,
                   weapon_name: str = "") -> dict:
    """One entry of `standards[]`: her (and her signature weapon's) numbers, rows and essence advice."""
    mat, calc_ids, weapon_types = ctx["mat"], ctx["calc_ids"], ctx["weapon_types"]
    weapons_listed, wid_of, wnames = ctx["weapons_listed"], ctx["wid_of"], ctx["wnames"]
    today, rarity = ctx["today"], ctx["rarity"]
    op = next((e for e in ops if e["name"] == who), None) or {"name": who, "wikiItemId": "", "onlineDate": "", "obtain": "", "dotType": ""}
    status = "已实装" if op["onlineDate"] and op["onlineDate"] <= today else "未实装"
    # The calculator's weaponType once she is listed, else her wiki entry's weapon tag.
    wtype = weapon_types.get(who, "") or op.get("weaponType", "")
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
    cuses: dict[str, Counter] | None = None
    need_by_id: Counter
    op_gold: int
    need_note = {}
    lv = None
    if who in calc_ids:
        rule = src.get(f"rules-char-{calc_ids[who]}", "/web/v1/game/endfield/calculate/rules", f"charIds={calc_ids[who]}", trim_rules)
        need_by_id, op_gold = char_need(rule)
        cuses = char_uses(rule)
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
            entry = foresight_entry(fs, rarity, set(calc_ids.values()), wtype, who)
            by_name, op_gold = foresight_need(entry, foresight_names(entry, names, mat))
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
    # Fallback sections when the calculator has no step rules for her yet (the next one, read
    # from the preview table): named by use, not by her name - user 2026-09-23 「按用途分类…
    # 哪些是角色，哪些是武器」; the App shows the same three names (Stockpile.groupTitle).
    who_group, weapon_group = OWNER_CHAR, OWNER_WEAPON
    wuses = weapon_uses(wneed)
    wiki_ids = wiki_material_ids(src)
    origin_missing = []

    def by_use(mid: str) -> tuple[list[dict], str | None]:
        """`uses` and the use-section of one material; group None when the operator's
        numbers did not come from the calculator (no per-step split to read)."""
        if cuses is None and need_by_id.get(mid):
            return [], None
        u = cuses.get(mid, Counter()) + wuses.get(mid, Counter()) if cuses is not None else wuses.get(mid, Counter())
        uses = [{"use": k, "need": u[k]} for k in USE_ORDER if u.get(k)]
        return uses, (uses[0]["use"] if len(uses) == 1 else USE_SHARED if uses else None)

    # 4. rows: every material, with this build's need (0 when the build does not use it)
    rows = []
    for mid, m in mat.items():
        nm = m["name"]
        row = {"id": mid, "name": nm, "rarity": m["rarity"], "icon": m["icon"], "need": 0, "group": None,
               "section": section_of(nm, m["kind"]),
               "stage": STAGE.get(nm) or (GATHER if nm in GATHERED else None), "note": need_note.get(nm)}
        c, w = need_by_id.get(mid, 0), wneed.get(mid, 0)
        row["origin"] = material_origin(src, nm, wiki_ids)
        if row["origin"] is None:
            origin_missing.append(nm)
        row["owner"] = "干员 + 专武" if c and w else "干员" if c else "专武" if w else None
        uses, use_group = by_use(mid)
        row["uses"] = uses
        if m["kind"] != "materials":
            row.update(need=None, exp=m["exp"], sumInto=EXP_CHAR if m["kind"] == "charExpMaterials" else EXP_WEAPON,
                       stage="干员经验" if m["kind"] == "charExpMaterials" else "武器经验")
        elif nm == "折金票":
            row.update(need=gold_total, group=USE_SHARED, owner="干员 + 专武",
                       note=("；".join(x for x in (row["note"], f"干员 {op_gold + char_gold:,} + 专武 {w_gold + weap_gold:,}") if x)))
        elif c and w:
            row.update(need=c + w, group=use_group or USE_SHARED, note=f"干员 {c} + 专武 {w}")
        elif c:
            row.update(need=c, group=use_group or who_group)
        elif w:
            row.update(need=w, group=use_group or weapon_group)
        elif nm == "高阶培养自选箱Ⅰ":
            row.update(need=None, note=f"一箱换任选一种高阶素材 {BOX_PER} 个；页面拿它补不够一人份的高阶素材（games[].box）")
        else:
            row["note"] = f"{who} 的满练不用它"
        rows.append(row)
    # The two exp rows have no wiki entry of their own: origin is the union of the folded
    # cards' origins, the icon is the highest-rarity card's (the note names it).
    cparts, cicon, cnote = folded_cards(rows, EXP_CHAR)
    wparts, wicon, wnote = folded_cards(rows, EXP_WEAPON)
    rows.append({"id": EXP_CHAR, "name": "干员经验", "rarity": None, "icon": cicon, "need": char_exp,
                 "group": USE_CHAR_LV if cuses is not None else who_group, "owner": "干员",
                 "uses": [{"use": USE_CHAR_LV, "need": char_exp}], "origin": folded_origin(cparts),
                 "section": "经验与货币", "stage": "干员经验", "virtual": True, "note": "五种作战记录 / 认知载体按经验值折算" + cnote})
    rows.append({"id": EXP_WEAPON, "name": "武器经验", "rarity": None, "icon": wicon, "need": weap_exp,
                 "group": USE_WEAPON_LV if cuses is not None else weapon_group, "owner": "专武",
                 "uses": [{"use": USE_WEAPON_LV, "need": weap_exp}], "origin": folded_origin(wparts),
                 "section": "经验与货币", "stage": "武器经验", "virtual": True, "note": "武器检查套组 / 装置 / 单元按经验值折算" + wnote})
    # Rows in section order (the page takes sections in first-seen order): the use
    # sections, then any per-owner fallback groups, then rows with no group.
    order = {g: i for i, g in enumerate(USE_ORDER[:-1] + (who_group, weapon_group, USE_SHARED))}
    rows.sort(key=lambda r: (order.get(r["group"], len(order)), 2 if r["need"] is None else 1 if r["need"] == 0 else 0,
                             -(r["need"] or 0), r["name"]))
    groups = list(dict.fromkeys(r["group"] for r in rows if r["group"]))

    online = f"（{op['onlineDate']} 上线）" if op.get("onlineDate") else ""
    wlabel = f"专武 {weapon['name']}" if weapon else "专武待定"
    caliber = f"{label} {who}{online}：1→90 全突破、四技能 12、{wlabel} 1→90；不含天赋"
    footnote = (f"人份 = 库存 ÷ {who}满练所需（1→90 全突破、四技能 12、{wlabel} 1→90，不含天赋"
                + (f"；{op['onlineDate']} 上线的{label}" if op.get("onlineDate") and role != "named" else "") + "）")
    if sources["need"] == SRC_FORESIGHT:
        footnote += "（上线前按客户端预览表，棱柱和折金票含天赋树）"
    weapon_out = ({"id": wid_of.get(weapon["name"], ""), "name": weapon["name"], "releasedAt": weapon.get("onlineDate", ""),
                   "kind": weapon.get("kind", ""), "obtain": weapon.get("obtain", ""), "wikiItemId": weapon.get("wikiItemId", ""),
                   "status": weapon_status, "reason": weapon_reason} if weapon else
                  {"id": "", "name": "", "status": "待定", "reason": weapon_reason})
    if weapon:
        weapon_out["essence"] = essence_advice(src, weapon["name"])
    return {
        "charId": calc_ids.get(who, ""), "name": who, "rarity": int(rarity), "releasedAt": op.get("onlineDate", ""),
        "status": status, "wikiItemId": op.get("wikiItemId", ""), "obtain": op.get("obtain", ""), "dotType": op.get("dotType", ""),
        "role": role, "label": label, "chosenBy": chosen_by, "weapon": weapon_out,
        "sources": sources, "caliber": caliber, "footnote": footnote,
        "groups": groups, "useSource": USE_SOURCE if cuses is not None else "", "originMissing": origin_missing,
        "rows": rows,
    }


def make(src: RulesSource, *, today: str = "", char_name: str = "", weapon_name: str = "",
         rarity: str = "6") -> dict:
    """One table from `src`: live, its `built` and server date are now; offline, the
    saved directory's pulled-at.txt gives both (so a rebuild from fixtures says when
    they were pulled), and saving fixtures writes it."""
    stamp = datetime.now(SERVER_TZ).strftime(BUILT_FORMAT)
    now_today = datetime.now(SERVER_TZ).strftime("%Y-%m-%d")
    if src.offline is not None:
        meta = src.offline / "pulled-at.txt"
        if meta.exists():
            stamp, _, saved_today = meta.read_text(encoding="utf-8").strip().partition("\t")
            now_today = saved_today or now_today
    today = today or now_today
    if src.offline is None and src.save is not None:
        src.save.mkdir(parents=True, exist_ok=True)
        (src.save / "pulled-at.txt").write_text(f"{stamp}\t{today}\n", encoding="utf-8")
    return build(src, stamp, today, char_name, weapon_name, rarity)


def summary(table: dict) -> str:
    """One line on what a table holds (the wrapper prints it, the relay logs it)."""
    g = table["games"][0]

    def one(st: dict) -> str:
        ess = st["weapon"].get("essence") or {}
        essence = ("，基质 " + "/".join(t["name"] for t in ess["terms"]) + f" 在 {len(ess['points'] or [])} 处"
                   if ess.get("terms") else f"，基质建议缺：{ess['reason']}" if ess else "")
        return (f"{st['name']}（{st['releasedAt'] or '?'} 上线，{st['status']}）+ {st['weapon']['name'] or '专武待定'}"
                f"（{st['weapon']['status']}），用量来自 {st['sources']['need']}{essence}")
    nxt = "；下一位 " + one(g["standards"][1]) if len(g["standards"]) > 1 else ""
    err = f"；下一位没建成：{g['coverage']['nextError']}" if (g.get("coverage") or {}).get("nextError") else ""
    return f"{one(g['standards'][0])}{nxt}{err}，{len(g['rows'])} rows，built {table['built']}"
