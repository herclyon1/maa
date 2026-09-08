# 终末地 external reference sources (neither of us knows this game — start here)

Ordered by **how usable each tier is as evidence**. **The top two tiers can be cited
directly; tier three needs cross-checking, and a single strategy site on its own does
not count.**

## Tier 1: official game data (the only hard evidence)

| Source | Contents | How to use it |
|---|---|---|
| [3aKHP/EndFieldGameData](https://github.com/3aKHP/EndFieldGameData) | `ItemTable` (2376 entries) + `i18n/CN.json` (116k entries) + character / enemy / equipment tables | `gh release download v0.2.0 -R 3aKHP/EndFieldGameData`, see [ENDFIELD-ITEMS.md](ENDFIELD-ITEMS.md) |
| [Variante/endfield_research_kit](https://github.com/Variante/endfield_research_kit) | The **tool that produces** the dump above, exporting from a local client | Use it to export tables yourself when you need more than the dump has (e.g. the operator-investment cost table) |
| [daydreamer-json/ak-endfield-api-archive](https://github.com/daydreamer-json/ak-endfield-api-archive) | Archive of game API responses, captured every 5 minutes | Look up versions / announcements / resource manifests |

**Known gap**: that v0.2.0 dump **has no operator-investment cost table** — `CharacterTable`
carries only stats and voice lines, and not one of the 29 operators references
`item_char_skill_specialize_*`. So "who needs how much of what" is not in there; that has to
come from tier three below.

## Tier 2: wikis (structured, with per-operator material tables)

- **[BWIKI 终末地](https://wiki.biligame.com/zmd)** — the most complete Chinese one, includes the [物品图鉴](https://wiki.biligame.com/zmd/物品图鉴)
- **[end.canmoe.com](https://end.canmoe.com/zh-CN/wiki/characters/chr_0016_laevat)** — addressable directly by `charId`, and the ids line up with the game's
- [Game8](https://game8.co/games/Arknights-Endfield) / [Prydwen](https://www.prydwen.gg/arknights-endfield/) — English

## Tier 3: per-operator investment materials (where the numbers come from)

- **[enjoygm.com](https://www.enjoygm.com/zh-TW/blog/arknights-endfield/liino-materials)** — `/zh-TW/blog/arknights-endfield/<character>-materials`,
  **itemises how much of each of the five advanced materials is needed and whether it goes to
  elite promotion or skill specialisation**; the most granular source found so far
- 游民星空's "养成一图流" series — one article per operator, search for 「终末地 <角色> 一图流」
- [游民星空 满练度素材消耗一览](https://www.gamersky.com/handbook/202602/2085397.shtml) — totals only

## Tier 4: planners / tools

| Tool | What it does |
|---|---|
| [endfieldtools.dev](https://endfieldtools.dev/ascension-planner/) | Investment planning, can record inventory (WebFetch gets 403, needs a real browser) |
| [perlica.moe](https://perlica.moe/planner) / [基质优化器](https://perlica.moe/essence-optimizer) | Investment planning + essence farming optimisation |
| [cmyyx/endfield-essence-planner](https://github.com/cmyyx/endfield-essence-planner) | **Essence planner**, open source |
| [SodaXu/endfield-crafting-manual-checklist](https://github.com/SodaXu/endfield-crafting-manual-checklist) | Look up where crafting-manual materials come from |
| [Terra-Online/Atlos](https://opendfieldmap.cn/) | Interactive map |
| [Kirukata27/arknights-endfield-resources](https://reend.vallov.com/) | Operator tier lists, banner mechanics, team-building guides |

Full index: [palmcivet/awesome-arknights-endfield](https://github.com/palmcivet/awesome-arknights-endfield) (61 projects),
local snapshot at [ref/awesome-arknights-endfield-LIST.md](ref/awesome-arknights-endfield-LIST.md).

## Lesson learned the hard way: what the five advanced materials actually mean

`item_char_skill_specialize_1..5` = 超距辉映管 / D96钢样品四 / 快子遴捡晶格 / 象限拟合液 / 三相纳米片.

- All five official descriptions are **word for word identical**
  (「用于干员精英化、武器突破、干员技能专精的珍稀素材」), so **the description tells you nothing
  about how they differ in use**
- Each has its own stage `dungeon_ss01..ss05` and its own shop exchange → **the five cannot
  substitute for one another**
- **But a single operator consumes several of them at once, in very different quantities.**
  Worked example (梨诺): 象限拟合液 **136** (20 for elite tier 4 + 116 for skill specialisation),
  D96钢样品四 **116** (skill specialisation), 超距辉映管 **16** (signature weapon breakthrough)
- Therefore: **you can neither treat the five as one pooled total, nor say "each operator only
  needs one kind" — I have made both of those claims and both were wrong.**
  To work out one operator's shortfall, go to tier three and look up that operator's itemised requirements.
