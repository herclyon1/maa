# 终末地 sanity stages: what each one yields, and what one five-star build needs

Three tables, built 2026-09-18 evening. **Every number carries its source**; a cell
that could not be sourced says so. "MaaEnd" below means the MaaEnd repository
(github.com/MaaEnd/MaaEnd, v2 branch) and the copy installed on the machine
(`D:\ark\maaend`, v2.29.0-rc.1 per its `interface.json`). AUTO-MAS is only the
foreman that starts MaaEnd; nothing here is read from it.

Sources, by short name:

| Short name | What it is |
|---|---|
| `ProtocolSpace.json` | MaaEnd `assets/tasks/ProtocolSpace.json` (machine: `D:\ark\maaend\tasks\ProtocolSpace.json`, same line numbers on 2026-09-18) - the option/case definitions; a case selects its stage by a template image, so **no stage id exists on the MaaEnd side** |
| `zh_cn.json` | MaaEnd `assets/locales/interface/zh_cn.json` - the Chinese labels of those cases |
| `SupplyPlanMain.json` | MaaEnd `assets/resource/pipeline/SupplyPlan/SupplyPlanMain.json`, the `SupplyPlanOverride_*` nodes (lines 57-170 and on) - MaaEnd's own item -> stage mapping; all 17 targets pick level 5 (`ProtocolSpaceLevelChoose` index 4, line 114) |
| `energy_point_gems.json` | MaaEnd `assets/data/EssenceFilter/energy_point_gems.json`, 84 entries (24 points x 7 world levels) |
| `nodes.json` | the merged pipeline on the machine, `D:\ark\maaend\resource\pipeline\nodes.json` |
| `ItemTable` | official data dump 3aKHP/EndFieldGameData v0.2.0 (2026-06-22), `ItemTable.json` `obtainWayIds` and `i18n/CN.json`; it has **no stage or drop table** |
| BWIKI | wiki.biligame.com/zmd, page 协议空间·干员经验 (updated 2026-02-07); it is the **only** 协议空间 stage page that exists there (Special:PrefixIndex on 2026-09-18 lists just that one) |
| gamersky | www.gamersky.com/handbook/202602/2085143.shtml (2026-02), level-5 numbers for all six 协议空间 stages and 高阶培养 |
| Skland | the official progression calculator, `zonai.skland.com/web/v1/game/endfield/calculate/{rules,material-list,user-game-data}`, pulled 2026-09-18 20:40 JST for the nine five-stars on the account; method in [SKLAND-API.md](SKLAND-API.md) |
| `IMS.json` | MaaEnd's depot readout on the machine, `D:\ark\maaend\debug\record\IMS.json`; see [HEADLESS.md](HEADLESS.md) |

## A. Sanity stages and what one claim yields

Every 协议空间 stage has five levels; the level-5 claim costs 80 sanity. Level 1-4
costs are 40/50/60/70 on the one stage BWIKI documents (干员经验) and on every
energy point (`energy_point_gems.json`); for the other five 协议空间 stages the
lower levels are **not sourced** (no page on BWIKI, not in the dump) and are left
blank rather than assumed. A/B = 奖励组A/B, the two claim options the game offers
(`RewardsSetOption` cases in `ProtocolSpace.json` lines 898-999; A/B letters are in
the zh_cn labels themselves, e.g. `A.协议棱柱组` / `B.协议棱柱`).

| MaaEnd case (`ProtocolSpace.json` line) | Chinese label (`zh_cn.json`) | Official dungeon id (`ItemTable.obtainWayIds`) | Level-5 cost | Level-5 yield per claim | Lower levels |
|---|---|---|--:|---|---|
| `OperatorEXP` (762) | 干员经验 | `dungeon_0001` | 80 | A 高级认知载体×6 + 初级认知载体×8 (= 68,000 exp); B 高级作战记录×17 (= 170,000 exp); + 行动资历×480 | L1 40: 高级作战记录×4+中级×2+初级×3; L2 50: 6/9/4; L3 60: A 9/9/4 or B 高级认知载体×4; L4 70: A 13/7/2 or B 高级认知载体×5+初级×5 (BWIKI) |
| `Promotions` (777) | 干员进阶 | `dungeon_0004` | 80 | A 协议圆盘组×14; B 协议圆盘×34 (gamersky) | not sourced |
| `T-Creds` (792) | 钱币收集（折金票） | `dungeon_0005` | 80 | 折金票×34,000 (gamersky) | not sourced |
| `SkillUp` (801) | 技能提升 | `dungeon_0006` | 80 | A 协议棱柱组×17; B 协议棱柱×85 (gamersky) | not sourced |
| `WeaponEXP` (822) | 武器经验（武器检查套组、武器检查装置） | `dungeon_0002` | 80 | 武器检查套组×16 + 武器检查装置×10 (= 170,000 exp) (gamersky) | not sourced |
| `WeaponTune` (831) | 武器进阶 | `dungeon_0003` | 80 | A 重型强固模具×14; B 强固模具×34 (gamersky) | not sourced |
| `AdvancedProgression1` (852) | 高阶培养Ⅰ（D96钢样品四） | `dungeon_ss02` | 80 | D96钢样品四×8 (gamersky: "相应珍稀素材×8" for 高阶培养) | not sourced |
| `AdvancedProgression2` | 高阶培养Ⅱ（超距辉映管） | `dungeon_ss01` | 80 | 超距辉映管×8 | not sourced |
| `AdvancedProgression3` | 高阶培养Ⅲ（快子遴捡晶格） | `dungeon_ss03` | 80 | 快子遴捡晶格×8 | not sourced |
| `AdvancedProgression4` | 高阶培养Ⅳ（象限拟合液） | `dungeon_ss04` | 80 | 象限拟合液×8 | not sourced |
| `AdvancedProgression5` | 高阶培养Ⅴ（三相纳米片） | `dungeon_ss05` | 80 | 三相纳米片×8 | not sourced |
| `AutoEssence` task, `AutoEssenceSpecifiedLocation` (one of 11/12 points) | 基质刷取 (能量淤积点 / 重度能量淤积点) | `world_energy_point01_1` … (`energy_point_gems.json` `gameMechanicsId`) | world level 4/5/6/7: 50/60/70/80 (levels 1-3: 0, no sanity reward) | world level 7 (重度): 金色基质·<地区>·组N + 紫色基质·<地区>·组N (`staminaRewardGems`) + 行动资历×480 (`staminaRewardOther`); the gems are random-term essences, not materials | same file, per world level |

Notes on this table:

* **Ⅰ-Ⅴ vs `ss01-05` do not line up**: the game's 高阶培养Ⅰ is D96 (MaaEnd label, `zh_cn.json`) but the official id of D96 is `dungeon_ss02`, and 超距辉映管 (Ⅱ) is `ss01`. The mapping above is read off each item's `obtainWayIds` in `ItemTable`, not off the numeral.
* `dungeon_xxxx_untouched`: every dungeon id also appears with an `_untouched` twin (e.g. `item_obtain_dungeon_0004_untouched`), listed *before* the plain id. `CN.json` has no string for the obtain-way ids themselves, so its meaning **cannot be fixed from these files**; the closest game text is 「首通奖励」/「深潜模式未解锁，仅可领取首通奖励」. Not assumed.
* **深潜模式 (deep dive)**: `CN.json` says 「部分关卡支持深潜模式。深潜模式在探索等级5级后自动开启，挑战对应关卡，可消耗理智获得奖励」, with strings for both 「“协议空间·高阶培养”深潜模式」 and 「危境再现深潜模式」 and boss entries 「危境祸影·聂菲斯/阮一/罗丹-深潜模式」; `ItemTable` gives every one of the five high-tier materials a `dungeon_bossrush_*` / `dungeon_common` obtain way. So yes, 危境再现's deep dive is a sanity-for-high-tier-material path in the data. **Quantities per claim are not in any source here.** MaaEnd: `nodes.json` has `ProtocolSpaceDeepDivePrepareEnter` / `…FindProtocolSpaceDeepDiveEnable|Disable` (the 协议空间 deep-dive entry through 作战手册) and **nothing for 危境再现** (0 hits for 危境再现/bossrush/首通 in `nodes.json`; no task file among the 41 imported by `interface.json`).
* 双倍领取: MaaEnd option `ProtocolSpaceObtainMode` = 单倍领取 / 双倍领取 / 不领取 (`zh_cn.json` `option.ProtocolSpaceObtainMode.*`); the double claim spends a 理智消耗许可 (the account holds 234 per `IMS.json`). The yields above are single claims.
* Materials that **no sanity stage drops**: 存续的痕迹 (`item_char_skill_crown`: `item_obtain_bp` / `shop_yellowticket` / `activity`), all leaves, mushrooms and 黯石/武陵石/燎石 (gathering: `item_obtain_gather_*`, `spaceship_plant`), and 高阶培养自选箱Ⅰ (`item_obtain_bp_pay`, opens into any one of the five high-tier materials: `item_obtain_case_bp_selfselect_skillsp_1_<n>`).

## B. What one five-star costs, 1 -> 90, all breakthroughs, four skills to 12, weapon 1 -> 90

Method: `rules?charIds=<id>` once per operator (comma-joined ids return nothing),
summing `breakthroughs[].materials`, `skills[].levels[].materials` up to targetLevel
12, and `charLevelRules` exp/gold; weapon likewise from `rules?weaponIds=<id>`.
Same scope as the six-star table in [ENDFIELD-STOCKPILE.md](ENDFIELD-STOCKPILE.md):
**talents (`talents[].activateRule`) are excluded there and here** (including them
adds 90-98 协议棱柱组 + 93-133 协议棱柱 + 98,400-98,600 gold per operator). Checked
against 莱万汀 + 熔铸火焰: the method reproduces that table's numbers exactly.

Nine five-stars on the account were computed (佩丽卡, 弧光, 陈千语, 阿列什, 狼卫,
赛希, 大潘, 昼雪, 艾维文娜). **Every universal number is identical across all nine,
and identical to the six-star figures**: five-star and six-star operators cost the
same to build in these rules.

Universal (operator): 协议棱柱组 472, 协议棱柱 328, 协议圆盘组 60, 协议圆盘 33,
存续的痕迹 24, 纯晶多齿叶 16, 至晶多齿叶 16, 晶化多齿叶 12, 重红柱状菌 5,
中红柱状菌 5, 轻红柱状菌 3; gold 841,000 (breakthroughs + skills) + 385,420
(levels); exp 1,792,290. (Corrected 2026-09-18 evening: the first cut said 385,419 /
1,792,289 because `charLevelRules[89]` - level 90 - is a `gold: -1, exp: -1` "no next
level" sentinel and had been summed in; `scripts/mac/build-need-tables.py` skips it
and `relay/tests/test_need_table.py` pins the corrected figures.)

Universal (weapon, any rarity - 3★, 5★ and 6★ weapons queried all return the same):
重型强固模具 50, 强固模具 23, 中黯石 5, 重黯石 5, 轻黯石 3; gold 125,700 + 341,390;
exp 2,524,080.

Variable (operator), which option each five-star takes:

| Operator | 116 of (high-tier A) | 116 of (high-tier B) | 20 of | 84 of | 8 of |
|---|---|---|---|---|---|
| 佩丽卡 | D96钢样品四 | 超距辉映管 | 快子遴捡晶格 | 受蚀玉化叶 | 血菌 |
| 弧光 | D96钢样品四 | 快子遴捡晶格 | 超距辉映管 | 岩天使叶 | 星门菌 |
| 陈千语 | D96钢样品四 | 快子遴捡晶格 | 象限拟合液 | 受蚀玉化叶 | 星门菌 |
| 阿列什 | 三相纳米片 | 象限拟合液 | 超距辉映管 | 岩天使叶 | 血菌 |
| 狼卫 | 快子遴捡晶格 | 象限拟合液 | 三相纳米片 | 岩天使叶 | 星门菌 |
| 赛希 | 快子遴捡晶格 | 象限拟合液 | D96钢样品四 | 受蚀玉化叶 | 血菌 |
| 大潘 | D96钢样品四 | 超距辉映管 | 三相纳米片 | 岩天使叶 | 血菌 |
| 昼雪 | 三相纳米片 | 超距辉映管 | 象限拟合液 | 受蚀玉化叶 | 血菌 |
| 艾维文娜 | 三相纳米片 | 象限拟合液 | 快子遴捡晶格 | 岩天使叶 | 血菌 |

So a five-star is "5 choose 2 at 116 each + 5 choose 1 at 20" for the high-tier
materials, plus one leaf of two (84) and one mushroom of two (8). The weapon adds
16 of one high-tier material (which one depends on the weapon, not its rarity) and
8 of 武陵石, 燎石 or 协议纹石 (the third ore was missing here until 2026-09-18 evening:
曜夜的首演 / 四二式·肃阵 / 寒夜幽影 take 协议纹石, per `rules?weaponIds=`; it is newer than
the 2026-06-22 ItemTable dump, so its obtain way is not sourced).

## C. Merged: need, stage, stock, gap, sanity

Two stock columns, because they disagree and the difference is the point:

* **Last scan (IMS.json)**: the file's `updated_at` is 2026-09-18 01:33 UTC, but
  that timestamp is refreshed daily by a two-number OCR in the shop
  (`SyncShopItemData`); the 培养素材 entries come from the last grid scan, which
  is **older than 2026-09-10** (the go-service log since 2026-09-10 16:56 shows no
  valuables/transfer grid scan at all). 待扫 = the id is not in the file; the
  帝江号仓库 materials (leaves, mushrooms, stones) are `Normal:*` storage and only a
  `SyncDepotItemData` scan - never run on this machine - would put them there; the
  few that do appear are A3 reward increments, not stock.
* **Official inventory**: Skland `calculate/user-game-data` `itemCount`, pulled
  2026-09-18 20:40 JST. Shortfall and sanity are computed from this column.

Sanity to close = ceil(shortfall / level-5 yield) x 80, using the yield in table A;
the A/B option with the material itself is used (no conversion between 组 and
单品). 高阶培养自选箱Ⅰ is not applied: the account holds 120 (official) and each
box opens into one high-tier material of choice, so the high-tier shortfalls below
can be closed without any sanity by opening boxes.

### C1. Universal (every five-star needs exactly this)

| Material | Per five-star build | Stage (五级) | Last scan (IMS.json) | Official inventory 2026-09-18 20:40 | Shortfall | Sanity to close |
|---|--:|---|--:|--:|--:|---|
| 协议棱柱组 | 472 | 技能提升 A | 4112 | 3547 | 0 | 0 |
| 协议棱柱 | 328 | 技能提升 B | 1688 | 1131 | 0 | 0 |
| 协议圆盘组 | 60 | 干员进阶 A | 3002 | 2789 | 0 | 0 |
| 协议圆盘 | 33 | 干员进阶 B | 1947 | 1954 | 0 | 0 |
| 存续的痕迹 | 24 | 通行证/黄票商店/活动（非理智产出） | 286 | 297 | 0 | — |
| 纯晶多齿叶 | 16 | 采集/仓库（帝江号两仓） | 待扫 | 603 | 0 | — |
| 至晶多齿叶 | 16 | 采集/仓库（帝江号两仓） | 待扫 | 362 | 0 | — |
| 晶化多齿叶 | 12 | 采集/仓库（帝江号两仓） | 待扫 | 799 | 0 | — |
| 重红柱状菌 | 5 | 采集/仓库（帝江号两仓） | 16 | 104 | 0 | — |
| 中红柱状菌 | 5 | 采集/仓库（帝江号两仓） | 待扫 | 208 | 0 | — |
| 轻红柱状菌 | 3 | 采集/仓库（帝江号两仓） | 待扫 | 416 | 0 | — |
| 重型强固模具 | 50 | 武器进阶 A | 359 | 230 | 0 | 0 |
| 强固模具 | 23 | 武器进阶 B | 235 | 229 | 0 | 0 |
| 中黯石 | 5 | 采集/仓库（帝江号两仓） | 待扫 | 235 | 0 | — |
| 重黯石 | 5 | 采集/仓库（帝江号两仓） | 45 | 168 | 0 | — |
| 轻黯石 | 3 | 采集/仓库（帝江号两仓） | 待扫 | 304 | 0 | — |
| 折金票 | 1693510 | 钱币收集 | 7862367 | 3407887 | 0 | 0 |
| 干员经验 (exp) | 1792290 | 干员经验 A 68000/次 或 B 170000/次 | 25778000 | 21900200 | 0 | 0 |
| 武器经验 (exp) | 2524080 | 武器经验 170000/次 | 20094000 | 12377400 | 0 | 0 |

### C2. Variable groups (one build uses one option per group; the table shows every option)

| Group | Material | Per build | Stage (五级) | Last scan | Official 2026-09-18 | Shortfall | Sanity to close |
|---|---|--:|---|--:|--:|--:|---|
| 高阶素材 ×116（五选二，每种 116） | D96钢样品四 | 116 | 高阶培养Ⅰ | 待扫 | 0 | 116 | 1200 (15×80, 高阶培养Ⅰ 8/次) |
| 高阶素材 ×116（五选二，每种 116） | 超距辉映管 | 116 | 高阶培养Ⅱ | 22 | 0 | 116 | 1200 (15×80, 高阶培养Ⅱ 8/次) |
| 高阶素材 ×116（五选二，每种 116） | 快子遴捡晶格 | 116 | 高阶培养Ⅲ | 3 | 1 | 115 | 1200 (15×80, 高阶培养Ⅲ 8/次) |
| 高阶素材 ×116（五选二，每种 116） | 象限拟合液 | 116 | 高阶培养Ⅳ | 3 | 1 | 115 | 1200 (15×80, 高阶培养Ⅳ 8/次) |
| 高阶素材 ×116（五选二，每种 116） | 三相纳米片 | 116 | 高阶培养Ⅴ | 84 | 48 | 68 | 720 (9×80, 高阶培养Ⅴ 8/次) |
| 高阶素材 ×20（五选一） | D96钢样品四 | 20 | 高阶培养Ⅰ | 待扫 | 0 | 20 | 240 (3×80, 高阶培养Ⅰ 8/次) |
| 高阶素材 ×20（五选一） | 超距辉映管 | 20 | 高阶培养Ⅱ | 22 | 0 | 20 | 240 (3×80, 高阶培养Ⅱ 8/次) |
| 高阶素材 ×20（五选一） | 快子遴捡晶格 | 20 | 高阶培养Ⅲ | 3 | 1 | 19 | 240 (3×80, 高阶培养Ⅲ 8/次) |
| 高阶素材 ×20（五选一） | 象限拟合液 | 20 | 高阶培养Ⅳ | 3 | 1 | 19 | 240 (3×80, 高阶培养Ⅳ 8/次) |
| 高阶素材 ×20（五选一） | 三相纳米片 | 20 | 高阶培养Ⅴ | 84 | 48 | 0 | 0 |
| 武器高阶素材 ×16（五选一） | D96钢样品四 | 16 | 高阶培养Ⅰ | 待扫 | 0 | 16 | 160 (2×80, 高阶培养Ⅰ 8/次) |
| 武器高阶素材 ×16（五选一） | 超距辉映管 | 16 | 高阶培养Ⅱ | 22 | 0 | 16 | 160 (2×80, 高阶培养Ⅱ 8/次) |
| 武器高阶素材 ×16（五选一） | 快子遴捡晶格 | 16 | 高阶培养Ⅲ | 3 | 1 | 15 | 160 (2×80, 高阶培养Ⅲ 8/次) |
| 武器高阶素材 ×16（五选一） | 象限拟合液 | 16 | 高阶培养Ⅳ | 3 | 1 | 15 | 160 (2×80, 高阶培养Ⅳ 8/次) |
| 武器高阶素材 ×16（五选一） | 三相纳米片 | 16 | 高阶培养Ⅴ | 84 | 48 | 0 | 0 |
| 叶（二选一） | 受蚀玉化叶 | 84 | 采集/仓库 | 待扫 | 484 | 0 | — |
| 叶（二选一） | 岩天使叶 | 84 | 采集/仓库 | 待扫 | 585 | 0 | — |
| 菌（二选一） | 星门菌 | 8 | 采集/仓库 | 7 | 222 | 0 | — |
| 菌（二选一） | 血菌 | 8 | 采集/仓库 | 15 | 176 | 0 | — |
| 武器矿石（二选一） | 武陵石 | 8 | 采集/仓库 | 6 | 273 | 0 | — |
| 武器矿石（二选一） | 燎石 | 8 | 采集/仓库 | 7 | 182 | 0 | — |


Reading: for one five-star build the universal materials are all in stock; exp and
gold are in surplus; the only shortfalls are the high-tier materials (D96 and
超距辉映管 at 0, 快子/象限 at 1, 三相 at 48), and those are exactly what the 120
自选箱Ⅰ cover. The old scan file still shows 22 超距辉映管 and 84 三相纳米片 - both
spent since; that is the practical measure of how stale a pre-09-10 scan is.
