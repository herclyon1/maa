# Skland (Endfield) API

Worked out and measured on 2026-08-27. The credential chain and the signing live in
`relay/ark_relay/skland.py`.
**A token is equivalent to account login credentials: it stays in `.env` on the machine
and must never appear in any log, report, or in this repository.**

## 1. Signing (get any of three things wrong and you get a 403, with no hint which)

```
sign = MD5(HMAC-SHA256(signing token, path + query + timestamp + json({platform,timestamp,dId,vName})))
```

* `platform` = **"3"** (not 1)
* `vName` = **"1.0.0"** (not an empty string)
* `dId` (device fingerprint) must be **the same pair produced in the same session as the
  cred**: the request that exchanges for the cred has to carry it, and every request and
  signature afterwards uses that same one. Without it you can still obtain a cred, but
  refresh answers 「设备信息无效」 outright.
* The timestamp must be aligned with the server: call `GET /web/v1/auth/refresh` first (it
  needs no sign), note the difference between server time and local time, and correct by
  that difference from then on. Using a fixed offset long-term gets you judged as
  「请勿修改设备本地时间」.
* `roleId` comes from `bindingList[].roles[].roleId` and `serverId` from the `serverId` at
  the same level — **neither is `channelMasterId`, nor the uid on the outer binding
  entry**.

## 2. Account and character progression

| Endpoint | What it gives |
|---|---|
| `GET /api/v1/game/endfield/card/detail?roleId=&serverId=` | The whole personal dataset; progression is in `data.detail.chars[]` |
| `GET /api/v1/game/endfield/card/war-echoes` | War echoes |
| `GET /api/v1/game/endfield/card/crisis-contract` | Crisis contract |

Each entry of `chars[]`: `level`, `evolvePhase` (ascension), `potentialLevel`,
`userSkills{skill id:{level,maxLevel}}`, `weapon{level,refineLevel,breakthroughLevel,gem}`,
`bodyEquip`/`armEquip`/`firstAccessory`/`secondAccessory` (each carrying `enhance`, the
per-substat enhancement level), `tacticalItem`,
`talent{attrNodes,latestPassiveSkillNodes,latestFactorySkillNodes,latestSpaceshipSkillNodes}`.

> Substats come only as English field names (`equip_attr_agi` and the like). **This dataset
> contains no translation table, so do not invent Chinese names for them.**

To produce a report: `scripts/mac/endfield-report.py <ef_card.json> [output.xlsx]`

## 3. The official progression calculator (the endpoints actually called under `game.skland.com/tools/endfield/*`)

The endpoint addresses were dug out of the tool page's JS bundle
(`assets.skland.com/_static_assets/game-tools/*.js`, search for
`/web/v1/game/endfield`). They all live on `zonai.skland.com` and use the same signing.

| Endpoint | What it gives |
|---|---|
| `GET /web/v1/game/endfield/calculate/rules` | `charLevelRules`/`weaponLevelRules`, 90 entries each, gold and exp per level |
| `GET /web/v1/game/endfield/calculate/material-list` | 32 materials (with exp value and rarity) + `priorities` (the consumption priority of each material class) |
| `GET /web/v1/game/endfield/calculate/user-game-data` | **Your inventory**: `userChars` 30, `userWeapons` 60, `itemCount` 37 |
| `POST /web/v1/game/endfield/calculate/record/submit` | Submit one progression calculation |
| `GET /web/v1/game/endfield/calculate/record/view` | Fetch the calculation result back |
| `GET /web/v1/game/endfield/enums` | All enums (attributes, equipment tiers, classes, …) |
| `GET /web/v1/game/endfield/game-terms` | Glossary of game terms |
| `GET /web/v1/game/endfield/search-chars` / `-weapons` / `-equipments` / `-tactical-items` | Compendium search |
| `GET /web/v1/game/endfield/char-pair` / `char-pair/char-list` | Data behind the team-building tool |
| `GET /web/v1/game/endfield/team/user-char-data` / `user-game-data` | The account data the team-building tool uses |

**What can be computed**: with the rules, the material table and your inventory all in
hand, "which materials, and how many, are still missing to take this character/weapon to
level X" can be computed entirely locally, without opening the web page.

**What cannot be computed**: there is **no** official endpoint that decides who to level
first. `priorities` is material consumption priority, not a character recommendation.
The 「养成建议」 entry in the quick links (`/tools/endfield/build-guide`) is **guides written
by players**, not a conclusion computed by the official side.

## 4. Quick links (`detail.quickaccess`, returned verbatim)

| Name | Web address |
|---|---|
| 养成计算器 | `game.skland.com/tools/endfield/cost-calculator` |
| 养成建议 | `game.skland.com/tools/endfield/build-guide` |
| 配队工具 | `game.skland.com/tools/endfield/rec-team` |
| 地图工具 | `game.skland.com/map/endfield` |
| 每日签到 | `game.skland.com/endfield/sign-in` |

The web version requires a login; we go through the API and do not need to log into the
site.

## 5. Community tools (these do judge "who to level", but that is written by people)

| Project | What it has |
|---|---|
| [cmyyx/cep](https://github.com/cmyyx/cep) | Endfield planner: essence planning, **character progression and gear recommendations**, refinement planning, banner calendar |
| [caffuchin0/zmdgraph](https://caffuchin0.github.io/zmdgraph/) | Progression planning calculator, wired up to Skland, supports live inventory sync |
| [FubukiProto/…Essences-Calculator](https://fubukiproto.github.io/Arknights-Endfield-Essences-Calculator/) | Essence calculator |
| [JamboChen/endfield-calc](https://github.com/JamboChen/endfield-calc) | Factory production-line number crunching |
| [otae-1204/otae-bot-entari](https://github.com/otae-1204/otae-bot-entari) | `docs/skland_endfield_personal_api.md`, the source for the signing section of this document |

## 6. Progression advice and team guides (i.e. that 「养成建议」 tool)

**There is no build-guide endpoint.** The tool page calls these two underneath, both with
the same signing:

| Endpoint | What it gives |
|---|---|
| `GET /web/v1/game/endfield/char-pair/char-list?charId=<32-char id>` | Progression pairings: `pairId`, the main character, the partner, `content.title`, `content.pairReason` (the recommendation text verbatim) |
| `GET /web/v1/game/endfield/team/char-list?charId=<32-char id>` | Team guides: `chars[].skills[].recRank` (**recommended skill level**), `mainWeapon`, `backupWeapons` |
| `GET /web/v1/game/endfield/team/tag/list` | Tags: 新手推荐 / 高玩进阶 / 影拓丰碑 / 战争回响 / 蚀像寻遗 / 趣味搭配 |

**`charId` is mandatory**; without it you get nothing but `{"list": []}` — which is exactly
how this got misdiagnosed as "the endpoint does not work" on 2026-08-27. The front end's
`toCommonId()` returns ordinary characters unchanged and only merges the male/female
versions of 「管理员」 into a single id, so the 32-character id straight off the character
card works.

`team/index` (the full guide listing) still answers 「参数错误」; its parameters have not
been worked out. Querying per character is already enough.

## 7. The four official "progression templates"

The numbers come from front-end constants
(`assets.skland.com/_static_assets/game-tools/*.js`, search for `cost_calc_template_`);
**they are not my estimates**:

| Tier | Level | Skills | Weapon |
|---|--:|--:|--:|
| 基础 basic | 60 | 6 | 60 |
| 晋级 advanced | 80 | 9 | 80 |
| 高阶 high_tier | 90 | 9 | 90 |
| 完美 perfect | 90 | 12 | 90 |

Compute the gap against a tier; do not default to the top one. On 2026-08-27 I started by
computing against level 90 and concluded "there is a big shortfall", when in fact every
material needed up to 「晋级」 was already there.

Consumption rules: `GET /web/v1/game/endfield/calculate/rules?charIds=<a single id>`
returns `breakthroughs` (gold and materials per ascension node), `skills[].levels[]` (gold
and materials per skill level) and `talents[].activateRule`. **Comma-joining several ids
returns an empty table**; they have to be asked for one at a time.
