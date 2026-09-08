# Endfield items - id, Chinese name, purpose

The full depot scan (`debug/record/IMS.json`) hands back ids; this is how to turn them
into something a human can read.

## Data sources (by trustworthiness)

1. **Official data-table mirror `3aKHP/EndFieldGameData`** - authoritative, use this first.
   `tables/ItemTable.json` (2376 entries) + `i18n/CN.json` (116k entries).
   ```bash
   gh release download v0.2.0 -R 3aKHP/EndFieldGameData   # endfield-tables.zip 23MB
   ```
   `ItemTable[id]` carries `name`/`desc` (int64 hashes - look them up in `i18n/CN.json`
   by **string** key), `rarity`, `type` (purpose category), `valuableTabType` (depot tab),
   `obtainWayIds` (how it is obtained).
   Note the zip is a 2026-06-22 snapshot, so anything added later is missing
   (known gap: `item_plant_mushroom_seed_2_3` 塔罗斯菌块).
2. **MaaEnd's bundled `locales/interface/zh_cn.json`** - names only, no purposes, but no download needed.
   Flatten it to `{last key segment: string}` and match on the **last segment exactly**;
   fuzzy matching leaks into the hint templates under `task.ProtocolSpace.focus.supply_plan.*`
   and returns garbage like 「折金票 未达标，准备刷取协议空间」.
3. Guide sites (游民星空 / 17173 / game8 / Prydwen) - only for "how much does maxing one operator cost",
   never for ids.

## The two kinds of id inside IMS.json

- `item_*` / `ap_*` (49 of them) = **the actual depot inventory**; every one is in the official ItemTable.
- 14 uppercase ids (`T_CREDS`/`OROBERYL`/`VALLEY_STOCK_BILL`/`PROTOPRISM`…)
  = **fixed-position OCR nodes** belonging to individual MaaEnd tasks, named after the English in-game names. Evidence:
  **not one of them** appears in the official ItemTable, **not one file** in the MaaEnd directory other than
  `IMS.json` mentions them, and where the meaning matches an `item_*` entry the numbers disagree
  (`T_CREDS` 47,500 vs `item_gold` 6,671,367).
  **Ignore these 14 when counting inventory.**

## Which tabs the scan covers (important: not the whole depot)

The official `ItemTable` has 8 distinct `valuableTabType` values, and **the MaaEnd scan came back with only 4 of them**:

| Tab | Entries in full table | Returned by scan | Contents |
|---:|---:|---:|---|
| 1 | 71 | 0 | |
| **2** | **181** | **0** | **Essences `gem_*` (all 156 of them are here)** |
| 3 | 220 | 0 | Equipment |
| 4 | 40 | 33 | Ascension materials |
| 5 | 111 | 0 | |
| 6 | 1438 | 12 | Currency etc. |
| 7 | 65 | 1 | 行动资历 |
| 10 | 250 | 2 | Sanity-related |

**So "how many essences do I have" is a question the scan cannot answer.** Essences are `type=19`
equipment-class items on tab 2: one slot per weapon, at most 3 terms; each etch consumes exactly one
five-star 无瑕 essence and raises a term by one level, a failure refunds 10 冷却脂, and the term caps are
6/6/3 = 15 levels → fully building one weapon takes ≥ 16 essences.
The denominator is clear; the numerator is out of reach.

**The cause is identified - it is neither "genuinely empty" nor a limit of what MaaEnd can do:**
our depot scan is not a feature MaaEnd exposes, it bypasses the UI and calls the internal entry `SyncItemData` directly.
Its chain is `SyncItemData -> SyncItemDataBegin -> **SyncItemDataInProgressionTab**
-> SyncItemDataRunFull` -- **it enters the 「养成」 (ascension) tab**, and `RunFull` means
"scan this one column completely", not "scan the whole depot". Tabs 4/6/7/10 are exactly what is reachable
from the ascension column; essences sit on tab 2, which it never visits.

**Next step (needs the machine online)**: go through every `SyncItemData*` node in
`resource/pipeline/nodes.json` plus the node that switches tabs, and see whether the tab is parameterized.
If it is → point it at the essence column with `pipeline_override`, rerun, and diff `IMS.json`;
if it is not → only then is this a real gap worth an issue.
For how to call it, see [HEADLESS.md](HEADLESS.md#maaend-depot-scan-use-tasksstart-not-tasksrun).

## Purposes by official `type`

| type | Purpose | Items |
|---|---|---|
| 7 | Operator EXP | 初/中/高级作战记录 (levels 1-60)、初/高级认知载体 (levels 61-90) |
| 27 | Operator promotion / skills | 协议圆盘 (elite 1 and 2)、协议圆盘组 (elite 3 and 4)、协议棱柱 + 棱柱组 (skill levels) |
| 95 | High-tier rare materials | 超距辉映管、快子遴捡晶格、象限拟合液、三相纳米片 (shared by elite promotion + weapon breakthrough + skill mastery) |
| 96 | Skill mastery | 存续的痕迹 |
| 8 | Finished crystal-plants for promotion | 重红柱状菌 (level 60)、星门菌/血菌 (level 80)、重黯石 (weapon 60) |
| 34 | Crystal-plant **seeds** | the assorted 子簇/菌块/根茎 - grown in the incubator into the type=8 finished goods |
| 25 / 26 | Weapon EXP / weapon breakthrough | 武器检查单元-装置-套组 / 强固模具、重型强固模具 |
| 61 / 87 / 88 | Essence skills / weapon potential / gear refinement | 冷却脂 / 协议化武器原型 / 武陵精锻助剂 |
| 1,2,29,44,53,79 | Currency | 折金票、嵌晶玉、衍质源石、信用、武陵/谷地调度券、武库配额 |
| 37 / 84 | Account / battle-pass EXP | 行动资历、通行证经验 |
| 62 / 98 | Sanity | 应急理智加强剂 (+40)、理智消耗许可 (double) |

## Cost of fully building one operator (游民星空, 2026-02)

Levels 1-60: 74 高级作战记录 + 7 中级 + 2 初级; levels 61-90: 94 高级认知载体 + 2 初级.
Elite promotion: 33 协议圆盘 + 57 协议圆盘组 + assorted 菌 + 20 high-tier materials.
All four skills at mastery 3: 328 协议棱柱 + 492 协议棱柱组 + 24 存续的痕迹 + 232 high-tier + assorted crystal-plants.
That comes to roughly **1.2 million 折金票 and 10720 sanity**, i.e. 53 days on natural regen alone,
about 39 days counting daily rewards.
→ **The 252 high-tier rare materials (type=95) per operator are the absolute bottleneck**; nothing else binds.

## Online planners

- <https://endfieldtools.dev/ascension-planner/> - can take an inventory and compute the shortfall (WebFetch gets 403, needs a browser)
- <https://perlica.moe/planner>

## The three levels of a weapon term (fully verified 2026-08-28)

`weapon.skills[]` on each weapon instance under `card/detail` is the **correct field** for cross-checking
essences - no CEP detour, no comparing Chinese strings:

    { key, name, gemTermId, level, currentBaseLevel, currentMaxLevel }

* **`gemTermId` and `gem.terms[].id` are the same hash-id namespace.** The check is one line:
  `{s.gemTermId} == {t.id}`. Of the 19 weapons on this account that carry an essence, 18 match;
  the single mismatch is 狼卫的同类相食 (it has 夜幕 fitted while the weapon wants 附术) --
  exactly the conclusion the CEP detour reached, so the two verify each other independently.
* **`level = currentBaseLevel + that term's `cost` on the essence`**, and it holds for 83/83 instances.
  `currentBaseLevel` is the weapon's own floor (6★: 3 on stat slots, 1 on the skill slot;
  莱万汀 at refinement 1 → skill floor 2).
* **`terms[].cost` is how many levels that term grants**, not a fixed property - the same term has
  turned up at 1, 2 and 6 on different essences. Caps: 6 for a stat term, 3 for a skill term, 15 combined.
  Source: 游民星空《武器基质系统详解》, 「基质的技能属性至多加成 3 级，
  而其余两个词条可以至多加成 6 级」; not one of the 57 instances on this account exceeds it.

### `currentMaxLevel` follows weapon investment; `skillInfos[].maxLevel` is a static ceiling

`weaponData.skillInfos[].maxLevel` is always 9/9/4 (9/4 for 3★), with no relation to rarity, refinement or
breakthrough - that is the ceiling at full breakthrough and zero refinement. The real current ceiling is
`currentMaxLevel`:

| Breakthrough | Stat slots | | Refinement | Skill slot |
|---:|---|---|---:|---|
| 0 | 3 / 3 | | 0 | 4 (3 for 3★) |
| 2 | 6 / 6 | | 1 | 5 |
| 3 | 8 / 7 | | 2 | 6 |
| 4 | 9 / 9 | | | |

That is: **the two stat slots depend only on breakthrough, the skill slot only on refinement**,
and 5★ and 6★ share one table.
(Covers the combinations present across the 25 weapons on this account; breakthrough 1 is uncovered and unverified.)

## What MaaEnd can and cannot do with essences

Task list taken from upstream `assets/locales/interface/zh_cn.json`:

| Can | Task | Notes |
|---|---|---|
| Farm | `AutoEssence` 🎱基质刷取 | Auto-challenges heavy energy points. Selectable region (枢纽区, 10 of them), single/double/no-claim, loop count, and whether to **使用刻写券** (the attributes to inscribe have to be chosen beforehand on the energy point's start screen) |
| Filter | `EssenceFilter` 🔒基质筛选锁定 | After the fight it filters and locks the useful ones automatically. Settings: 「保留未来可期基质」 (all three terms present and total level ≥ threshold, default 6), 「保留实用基质」 (term 3 level ≥ threshold), 「未匹配时废弃」 |

**Cannot do: etching.** The characters 「蚀刻」 do not appear anywhere in the interface text, and there is no
task for it. Etching is the only way to take essence terms from level 1~3 up to 6/6/3 (each attempt eats one
gold essence from the same region; a failure refunds 冷却脂, which can be spent for a guaranteed success),
and it is **manual only**.
So "automated essence development" today means: **auto-farm + auto-filter/lock, etch by hand.**

## Etching: what is confirmed / what is not

**Confirmed** ([dvg.cn/danjigl/116572](https://www.dvg.cn/danjigl/116572.html),
consistent with several second-hand retellings):

* One etch consumes **one gold (无瑕) essence from the same region** as fodder.
* Success rate comes in four tiers: **极高 / 高 / 低 / 极低**.
* **A failure yields 「冷却脂」**; once enough is banked you can etch through 「消耗冷却脂」,
  which **always succeeds** (the pity mechanic).
* The bottleneck is the fodder, not the base essence - the title of the Bilibili field-test thread says
  exactly that: 「难在狗粮而不是胚子」.

**Not confirmed, do not invent** (all three sources say it is unspecified):

* Does it strengthen an essence **already fitted to a weapon**, or any essence in the depot?
* **Which** term does one etch raise - random, or can it be chosen?

→ Once the machine is up, open the etching screen in the game and look; stop inferring it from guides.

**And a common misreading, corrected**: etching does not target "an already perfect essence".
An essence already at 6/6/3 needs no etching. The target is the one whose **term combination is right but
whose levels are too low** - take that one from 1~3 up to 6/6/3; the "useless" ones are the fodder being eaten.

## CEP's essence planning ≠ MaaEnd's essence filter/lock

They are **not the same feature**. They sit at opposite ends of the flow and complement each other:

| | CEP (web, `/essence`) | MaaEnd `EssenceFilter` |
|---|---|---|
| Runs where | Browser, never touches the game | Actually clicks inside the game |
| Input | The weapon you want to build | Essences dropped in combat |
| Output | Which energy point to go to, which three to pre-inscribe and lock | Lock the useful ones / discard the useless ones |
| What its "filter" means | Filters the **plan list** (by attribute, by region); wording in `essence.attrFilterTitle` / `essence.regionFilter` | Filters the **drops** (by weapon match, 未来可期, 实用基质) |

Usage: **CEP decides where to go and what to lock → MaaEnd `AutoEssence` runs the fight and `EssenceFilter`
handles the drops → etching by hand.**

## Calling 「基质筛选锁定」 on its own (without running the whole queue)

Tool: `scripts/mac/lib/maaend_essence.py`, delivered to the game machine with winrun.

```
winrun.sh --py scripts/mac/lib/maaend_essence.py          # checks only, changes nothing
winrun.sh --py scripts/mac/lib/maaend_essence.py --go     # actually runs
```

**Findings (2026-08-28, all from reading upstream source; the machine was offline at the time):**

* Task name `EssenceFilter`, entry node **`EssenceFilterMain`**,
  controller supports `Win32-Front` -- **so it can be invoked on its own**.
* **It does not require the game to be sitting on any particular screen.** `EssenceFilterMain.next` carries
  `[JumpBack]SceneEnterMenuValuables`, so if it is not on the essence page it jumps to the valuables depot
  itself and then switches to the 「武器库 → 武器基质」 tab. But the game must be running and able to open the menu.
* Division of labour (`agent/go-service/essencefilter/README.md`):
  C++ `RecoGrid`/`GridTracker`/`EssenceGrid` scans the grid and picks cells →
  Pipeline OCRs the three skills and the level cell by cell → Go `matchapi` matches →
  Go only picks a branch through `ctx.OverrideNext`, **every click happens in Pipeline**.
* **It matches against every weapon of that rarity** (`weapons_output.json`),
  not "the weapons I own". So a hit means this essence is an endgame term set for some 6★ weapon.
* Must be `/tasks/start`, never `/tasks/run` -- run does not spawn the agent subprocess, and all the
  recognition and matching lives in there, so it fails all the way through with `Action is null`.
  See [HEADLESS.md](HEADLESS.md).

**Two things hard-coded in the script, deliberately with no switch:**

* `discard_unmatched: false` -- discarding is irreversible; go click it in the UI yourself.
* It always ends with `POST /agent/stop`, otherwise the two subprocesses hang around forever.

**Preflight checks** (if they fail it exits instead of forcing its way through): `MaaEnd.exe` and `Endfield.exe`
are running; `GET /api/maa/state` contains an instance with `connected` + `resource_loaded` +
`tasker_inited` all true and `is_running` false.
**This script does not create an instance** -- a freshly created one has all three false.
Field names copied from `handle_get_maa_state` in MXU's `src-tauri/src/web_server.rs`.
When a preflight fails it prints the remedy commands: the game's exe path is **asked from AUTO-MAS's
`Game.Path` at that moment**, never hard-coded -- on 2026-08-28 I filled two exe paths into `wingui.sh`
from memory, then grepped afterwards and found those two strings existed only in the file I had just
written; I nearly confirmed myself with my own invention.
`wingui.sh launch` now accepts only the alias `wuwa` (path verified) or a **full exe path**.

When it finishes it prints the match summary from the run log and produces `D:\ark\maaend\EssencePlan.html`
(`export_calculator_script`; the path is `planRecommendHTMLPath` in `plan_export.go`).

## 2026-08-28: the first real run, and two lessons

The first standalone run of `EssenceFilter` succeeded. Recording the facts and the mistakes together.

### Lesson one: a remote task does not stop because I got interrupted locally

I submitted a second round (with `--also-pure --also-5star`), the user interrupted that tool call, and on
that basis I told the user "that run never started at all". **Wrong.** The interrupt killed the wait on the
Mac side; `POST /tasks/start` had already gone out, and MaaEnd ran it regardless:

    23:26:02 初始化完成 → 23:30:42 筛选完成！确认锁定物品：5   （只金、只6★）
    23:32:20 初始化完成 → 23:37:17 筛选完成！确认锁定物品：8   （金+紫、含5★）

**Not again: after a local interrupt I must verify the remote state through `/api/maa/state` and `/api/logs`,
and must not infer "it did not run over there" from "I got interrupted over here".**

### Lesson two: the run log does not record essence quality

`/api/logs` has only 「匹配到武器 X」, 「已锁定基质」, 「已确认上锁」 and the loot summary
(weapon / skill combination / lock count) -- **no gold, purple or blue**.
So "how many purple ones did it lock" is a question **the log cannot answer**; only looking in the game can.
To make it answerable, upstream would have to be asked to put quality into the summary.

### What the etching screen actually looks like (seen first-hand 2026-08-28)

* The candidate list under 「基质蚀刻」 is **entirely 无瑕 (gold) essences**, no 高纯 (purple) --
  purple **cannot be an etching target**.
* Every essence carries a **region tag** (example: 四号谷地), consistent with the "fodder must be same-region" claim.
* On the fully built ones all three terms read 「已达上限」, and the numbers are exactly +6 / +6 / +3.

### MaaEnd has no "unlock" function

`assets/resource/pipeline/EssenceFilter/LockDiscard.json` has only six nodes:
lock entry / click lock / confirm locked, discard entry / click discard / confirm discarded.
Searching the interface text finds no 「解锁」 anywhere (only the unrelated 「协议空间未解锁」).
**Unlocking is manual only.**

## Cost-efficiency of essence farming (data from MaaEnd `data/EssenceFilter/energy_point_gems.json`)

**重度能量淤积点·枢纽区** (四号谷地, group 1), output at the four stamina tiers:

| Stamina | Gold essences | Purple essences | 行动资历 | Sanity per gold essence |
|---:|---:|---:|---:|---:|
| 50 | 1 | 2 | 300 | 50 |
| 60 | 1 | 2 | 360 | 60 |
| 70 | 2 | 2 | 420 | 35 |
| **80** | **3** | 2 | 480 | **26.7** ← best value |

**The low tiers are a straight loss**: 60 stamina and 50 stamina both yield only one gold essence.
**Run the 80 tier only.**

Odds of hitting one specific three-term set (枢纽区 pools: s1 five / s2 eight / s3 eight):

* Without pre-inscription: 1/5 × 1/8 × 1/8 = **1/320**
* With pre-inscription (one of three base attributes + one locked additional or skill term): 1/3 × 1/8 = **1/24**

Converted to sanity (80 tier, 26.7 sanity each):

* With pre-inscription: about 24 essences → **≈ 640 sanity**
* Without: about 320 essences → ≈ 8540 sanity

**Pre-inscription cuts the cost to 1/13. Farming without it is farming for nothing.**

## The real boundary of quick config (`Info.IfQuickConfig`)

Measured 2026-08-28: switching the MAS sanity task from 「干员养成」 to 「基质刷取」
**has no effect whatsoever**, because of `AutoProxy.py:622-665`:

```python
target_sanity_task_exists = any(t["taskName"] == target_task_name for t in maaend_tasks)
sanity_missing = sanity_switch_enabled and not target_sanity_task_exists
...
if sanity_missing:
    warning_message = f"...当前 MaaEnd 配置中缺少 {target_task_name} 任务，已跳过理智任务快速配置"
```

**Quick config can only toggle tasks that already exist in the MaaEnd config; it will not create one for you.**
In the master copy `<automas>/data/<scriptId>/Default/ConfigFile/mxu-MaaEnd.json`, the AUTO-MAS instance's
18 tasks include `ProtocolSpace` but no `AutoEssence`, so MAS logs one warning, skips, and goes on
running protocol space as before.

It only governs three things: the `If<TaskName>` task switches, the sanity task type + detail, and the
essence location (written into `AutoEssenceChooseLocation`). **Inscription vouchers, claim mode, loop count,
post-fight filtering, AutoFight details -- MAS governs none of them**; they all stay on MaaEnd's own config.

Also note: before running, AUTO-MAS does `shutil.rmtree` on `<maaend>/config` and then `copytree`s its own
(`AutoProxy.py:514-515`), the same master/copy pattern as OK-WW.
**Editing the copy at `D:\ark\maaend\config` counts for nothing.**

## The real difference between the three candidate locations (corrected 2026-08-28)

What I said earlier -- "the three locations have identical term pools" -- was **not accurate**.
Comparing `energy_point_gems.json` entry by entry:

* **For 诀 there is no difference**: all three locations are s1=5 / s2=8 / s3=8 and all contain
  `attr_wisd` / `attr_usp` / `burst`, so pre-inscription is 1/24 in every case.
* **But the pool contents do differ** -- what differs is the **other** terms:

  | Location | s2 relative to 枢纽区 | s3 relative to 枢纽区 |
  |---|---|---|
  | 武陵城 | +治疗效率/暴击率/生命　−自然伤害/灼热/源石技艺 | +医疗/残暴/切骨/夜幕　−追袭/效益/压制/巧技 |
  | 清波寨 | +治疗效率/物理伤害/生命　−自然伤害/攻击/灼热 | +医疗/昂扬/切骨/夜幕　−追袭/流转/效益/强攻 |

  That is why CEP's "weapons satisfied along the way" numbers differ.

**What MaaEnd calls 「成功率」 is not a drop rate.** The original text is in the option description for
`AutoEssenceChooseLocation`: 「受地形影响，目前成功率最高的地区是藏剑谷和清波寨，
成功率最低的地区是试验园区」 -- it refers to **whether the automation can run the map and finish the fight**,
and has nothing to do with essence terms.

**I also overrated the fodder-region point.** 枢纽区 belongs to 四号谷地 while 武陵城/清波寨 belong to 武陵,
and etching fodder does have to be same-region; but it takes 24 farmed essences to hit one, so the same
batch incidentally produces 23 same-region fodder essences, while fully etching one takes only about 15 --
**it is self-sufficient**. So the existing stock of 1440 is not a decisive argument.

## The stamina tier is set by world level; it is not chosen per run

| World level | Recommended level | Stamina | Gold essences | Sanity each |
|---:|---:|---:|---:|---:|
| 4 | 40 | 50 | 1 | 50 |
| 5 | 50 | 60 | 1 | 60 |
| 6 | 55 | 70 | 2 | 35 |
| 7 | 60 | 80 | 3 | **26.7** |

**World level 7 is nearly twice as efficient as level 4.**

## Those six "ornamental switches" in MAS are a structural mismatch, not somebody's misclick

`IfSeizeEntrustTask` / `IfAutoEcoFarm` / `IfAutoCollect` / `IfTrialOfSwordmancy` /
`IfResourceRecycleStation` / `IfPullCountCalculator` -- they exist in the MAS UI, but the AUTO-MAS instance
in the MaaEnd master copy has no matching tasks, so they **have never run, not once**.

Cause: the AUTO-MAS schema hard-declares this entire set of MaaEnd task switches
(`models/schema.py:960-970`), while **whether a task exists depends on MaaEnd's task list**.
The two are not one list. These fields were never written in our repo (`git log -S` returns nothing),
so no action of ours caused it.

It is the same hole as the missing `AutoEssence`: **MAS can only toggle tasks that already exist; it will not create them.**

## How to find an energy point in the game (walked through on site 2026-08-28)

**行动手册 → 索引 → 能量淤积点** → pick a location → **查看** → **前往传送**.

Shortcut: 贵重品库 → 武器基质 → pick any essence → on the right, 「获取方式 → 重度能量淤积点 ≫」;
clicking that arrow jumps straight to the index page above.

The teleport lands you at **the nearest protocol teleport point** (the same one as MaaEnd's
`GotoTriggerPointSetAnchor_VFTheHub`), and the energy point is still a short walk further: MaaEnd's path is
`ZONE ValleyIV_Base → NAVMESH (456.92, 932.86) → (463.41, 938.85)`.

**Note: `wingui.sh key` can only send single key presses; it cannot hold WASD down, so that last stretch
cannot be walked with it.** Either let MaaEnd's `AutoEssence` walk it (which is exactly what it does),
or walk it by hand.

### 枢纽区 can only drop 8 kinds of skill term

The energy point detail page's 「消耗理智领取奖励」 lists 9 icons = that location's `battleRandomPresets`:

    无瑕基质（无技能词条）、强攻、压制、追袭、粉碎、巧技、迸发、流转、效益

**「夜幕」「切骨」「医疗」「残暴」「附术」「昂扬」 cannot be farmed in 枢纽区** --
which matches 枢纽区's `skillTermIds` in `energy_point_gems.json` exactly.
The skill attribute pre-inscription can lock has to come from those 8, and 诀's 「迸发」 is among them.

## How to set pre-inscription (actually done 2026-08-28)

**Where**: the energy point's 「开启挑战」 screen → 「属性选择」 at the bottom right.
It is not a settings item in some menu; you must walk to that location and trigger it before it exists.

**Use MaaEnd to walk there, but do not start the fight**:

```
winrun.sh --py scripts/mac/lib/maaend_task.py --entry AutoEssenceMain \
    --override-b64 <base64 of {
      "GotoTriggerPointSetAnchor_VFTheHub": {"enabled": true},
      "AutoEssenceClickEssenceStartButton": {"action": {"type": "DoNothing"}, "next": []}
    }> --go
```

30 seconds to walk there and trigger it, stopping on the 开启挑战 screen, **costing no stamina**
(stamina is only deducted when the reward is claimed).
`AutoEssenceClickEssenceStartPrepare` is that screen; cutting off its next step
`AutoEssenceClickEssenceStartButton` makes it stop there.

**The options on screen match CEP's data exactly** (this was checked on the spot after the user challenged it):

    基础属性 5 个：敏捷 / 力量 / 意志 / 智识 / 主能力        ← s1Pool = 5
    附加属性 8 个：攻击 / 灼热 / 电磁 / 寒冷 / 自然 / 源石技艺 / 终结技充能 / 法术
    技能属性 8 个：强攻 / 压制 / 追袭 / 粉碎 / 巧技 / 迸发 / 流转 / 效益   ← s3Pool = 8

The rules are printed on the screen: **pick 3 基础属性 and the reward essence rolls 1 of those 3 at random;
pick 1 附加 or 技能 attribute and that one is guaranteed to appear, while the remaining 1 is fully random.**
So the hit rate is 1/3 × 1/8 = 1/24, matching the earlier calculation.

**The price**: while pre-inscription is in effect, claiming the reward costs **one extra 刻写券**
(current balance 599).

诀's setup has been changed to CEP plan 1: **基础 智识/力量/敏捷 ｜ 技能锁 迸发**.

## winrun now ships same-directory dependencies automatically

When `maaend_task.py` imported `maaend_essence` the remote side raised `ModuleNotFoundError` --
winrun only shipped the single file. It now reads the import statements of the script being shipped and
brings `scripts/mac/lib/*.py` along with it.

**pipeline_override must go through base64**: raw JSON crossing bash → ssh → cmd → PowerShell has its
quotes chewed off at four layers; measured, it arrives as `{GotoTrigger...`.
`--override-b64` is the only way in.
