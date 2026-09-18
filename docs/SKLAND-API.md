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

## 8. The depot for the phone page (库存 tab), and the need table behind it

Endfield only for now; the JSON keeps a `games[]` layer so 明日方舟 / 鸣潮 can be added
without changing its shape, and inside a game `standards[]` holds the build standards
(one today) with `rows` mirroring it. Built 2026-09-18/19 (branch `data`).

**Live stock** - the page asks Skland itself (`web/inventory.js`, on the user's action
only, no timer), with the session the machine hands over in the snapshot and the
signing helpers of `web/stamina.js` (`skRefresh` / `skGet`, exported for this):

| Call | What the page takes from it |
|---|---|
| `GET /web/v1/game/endfield/calculate/user-game-data?roleId=&serverId=` | `userGameData.itemCount` `{material id: count}` - **a material the account has none of is absent, not 0** (2026-09-18: 38 of 40 present); also `gameLevel` |
| `GET /web/v1/game/endfield/calculate/material-list` | id -> name / rarity / `icon` / `exp` for all 40 (5 char exp + 3 weapon exp + 32); cached in localStorage for seven days, refetched early when the inventory names an id the cache does not know. The `icon` URLs (`bbs.hycdn.cn`) are the pictures the page shows |

CORS: both endpoints (and `rules`) answer the preflight with `access-control-allow-origin: *`
and `allow-headers: Cred,Sign,Platform,Timestamp,Did,Vname` (measured 2026-09-18 from
`https://herclyon1.github.io`). One read of the tab is three requests, about half a second.

**Static need** - `web/data/need.json`, generated by `scripts/mac/build-need-tables.py`
and published with the page (`deploy-web.sh` copies `web/` recursively for it). The
user's caliber (2026-09-19): one standard, **the newest six-star in the official wiki -
a future one included - with her signature weapon**, so the page shows her materials
before her banner opens. `--rarity 5` takes the newest five-star, `--char` / `--weapon`
a named pair. Rerun it when a six-star appears in the wiki and again once the
calculator lists her (the source upgrades itself, see below).

### Who, and which weapon (official wiki, no account data)

| Call | Field |
|---|---|
| `GET /web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true` | subtype 干员 / 武器 with tags (rarity `brief.subTypeList[subTypeId=10000].value`: `10006` six-star, `10005` five-star; `brief.dotType` `label_type_preview` = announced, `label_type_up` = on a banner now); every other subtype as id -> name, because the material cards below point at 物品 ids |
| `GET /web/v1/wiki/item/info?id=<itemId>` | attributes (`{label, value}` pairs in `document`): operators `上线时间` / `主要获取方式`; weapons `上线时间` / `类型` / `主要获取方式`. Also the whole document, see the cards below |
| `GET /web/v1/wiki/update-log/list?itemId=<itemId>&limit=100` | every edit of an entry with `createdAtTs` (no summary) |

* Newest = the latest `上线时间`, **future dates included**; `standards[].status` says
  已实装 / 未实装 against the server date. 2026-09-18: 提弗洛斯 (2116) 2026年9月2日, then 梨诺
  08-09, 诀 07-16, 卡缪 06-26, 弭弗 06-05, 庄方宜 04-17, 洛茜 03-29, 汤汤 03-12, the launch
  roster 01-22. Five-stars: 噗切娜 (2117, 2026年9月24日, preview) then nine at 01-22.
* Signature weapon = the six-star weapon with her `上线时间`, her `类型` (`search-chars`
  `weaponType`) and `主要获取方式` 「武库交易所·限时特卖」. 2026-09-02 has two new 施术单元:
  寒夜幽影 (限时特卖, 2118) and 苦难的尽头 (协议通行证·武器补给) - the rule names 寒夜幽影 alone;
  the same rule gives 熔铸火焰 for 莱万汀. Not exactly one (or the operator not yet in
  `search-chars`, so her weapon type is unknown) -> `weapon.status` 待定 with the reason.
  Cross-checks, not inputs: the version bulletin runs 「幽寒申领」 with 寒夜幽影 as the UP
  weapon next to her banner 「冬猎」; the client's `CharWpnRecommendTable` lists
  `wpn_funnel_0019` (= 寒夜幽影, md5 of the code is the calculator's id `4e7f3757…`) first
  for `chr_0034_typhoea`; the account has it on her.
* Why not other fields: `search-chars` orders by rarity and carries no date; the catalog's
  `publishedAtTs` is the wiki editor's publish time; the account's `ownTs` is when *this*
  account got someone.

### Where her numbers come from, in order (`standards[].sources`)

1. **The calculator** - `rules?charIds=<one id>` (breakthroughs + skills to 12, talents
   excluded, §B of ENDFIELD-SANITY-YIELD.md) and `rules?weaponIds=<one id>`. Only after
   release: on 2026-09-18 `search-chars` lists 32 operators and no 噗切娜, and `rules`
   for her derived id (`md5("chr_0038_purrche")`) answers `chars: []`.
2. **The wiki entry's own material cards** - the 能力扩延 chapter's 精英化 and 战斗技能
   widgets embed every material as `{"kind":"entry","entry":{"id":<wiki item id>,
   "count":N,"showType":"card-big"}}` (`chapterGroup` -> widget id -> `widgetCommonMap`
   `tabDataMap[].content` -> `documentMap` document -> block inline elements); names via
   the catalog. The 天赋阵列 widget is left out, which is exactly the caliber. Checked
   2026-09-19 on 提弗洛斯: the cards equal her rules for all 17 materials (472 / 328 /
   116 / 116 / 84 / 60 / 33 / 24 / 20 / 16 / 16 / 12 / 8 / 5 / 5 / 3) and the gold differs
   only by the 装备位 unlock nodes (814,900 vs 841,000). Weapons: the 武器总览 › 武器信息
   widget (寒夜幽影: equal to the rules, gold included).
3. **The client's preview table** - `ForesightCharGrowthTable.json` (mirrored at
   github.com/rmxlinux/EndfieldData; the tables are new in client 1.5 and do not exist in
   the 1.4 snapshots), highest stage = the full build; item names from MaaEnd's
   `iconRecognition.name.<item id>` locale strings (github.com/MaaEnd/MaaEnd, branch v2).
   **Its 协议棱柱 / 协议棱柱组 / 折金票 include the talent tree** (461 / 562 for 噗切娜 against
   the 328 / 472 every operator's rules give): those rows carry `note` 「预览表的数含天赋树」
   and the footnote says so. Replaced automatically once source 1 or 2 has her.

Level-up gold / exp (1 -> 90) are the same table in every `rules` response; taken from
hers, else her weapon's, else the first listed weapon's (`sources.levels` says which).

### How early a new operator's needs can be known (measured 2026-09-19)

| | 提弗洛斯 (six-star, version launch) | 噗切娜 (five-star, gifted mid-version) |
|---|---|---|
| Wiki entry first published (`update-log` first edit / catalog `publishedAtTs`) | 2026-08-21 20:21:04 (item 2116; weapon 2118 at 20:22:54), 25 edits up to 09-15 | 2026-08-21 20:21:12 (item 2117), 4 edits, all 08-21 |
| Wiki 上线时间 | 2026年9月2日 | 2026年9月24日 |
| Actually obtainable | banner 「冬猎」: 「雪凇幽梦」版本更新后 (maintenance 2026/09/02 06:00 - 12:00 UTC+8) to 2026/09/30 11:59; bulletin 版本更新说明 cid 3029, `game-hub.hypergryph.com/bulletin/v2/aggregate` (fixture `relay/tests/fixtures/ef_bulletin_full_2026-09-03.json`), published 09-02 09:00 | gift event 「我们的大菲林！来袭！」 from 2026/09/24 12:00 (same bulletin); no banner |
| Calculator (`search-chars` / `rules`) | listed by 2026-09-18 23:11 (our first look); **the first day cannot be fixed** - nobody archives Skland's calculator (daydreamer-json/ak-endfield-api-archive keeps launcher, bulletin and package APIs only) | not listed on 09-18 |
| Client preview table | none: the Foresight tables first appear in client 1.5 (package 1.5.3 published by the launcher API 2026-09-01 22:17 UTC per that archive; mirror commit 6e71850 「Update 1.5」 09-02 09:43 UTC+8), where she is already in `CharGrowthTable` as a released operator | present since client 1.5 (09-02), 22 days ahead, full stage-4 materials |
| Wiki material cards today | present (equal to the rules) | none (the entry has only 干员资料 / 官方情报 chapters) |

So before a banner the earliest official numbers are the wiki entry's cards - its
entry appears about two weeks ahead (12 days for 提弗洛斯), and the update log does not
say on which edit the cards arrived. Where the wiki has no cards yet, the client preview
table (from the version's launch, 22 days ahead for 噗切娜) is the only source, talents
included. The script tries them in that order.

### For the page

Every row carries `section` (通用 / 高阶素材 / 采集 / 经验与货币, the order in
`games[].sections`; the eight exp cards have none and fold into 干员经验 / 武器经验),
`games[].footnote` is the 人份 caption, and `games[].lagMinutes` / `lagNote` quote the
official calculator page's own line 「仓库资源和干员数据等信息的同步，会有 30 分钟左右的延迟」.
`web/data/inventory-demo.json` is the live object's exact shape with invented counts.

Read-off traps, each pinned by `relay/tests/test_need_table.py`:

* `charLevelRules[89]` (level 90) is `gold: "-1", exp: "-1"` - a sentinel, not a cost.
  Summed in, it produced the 385,419 / 1,792,289 / 1,693,509 that ENDFIELD-SANITY-YIELD.md
  carried for a day; the real figures are 385,420 / 1,792,290 / 1,693,510
  (`weaponLevelRules` ends in `0 / 0`).
* `material-list` names had a trailing newline on 2026-08-28 (`"D96钢样品四\n"`) and did
  not on 2026-09-18 - always strip.
* 诀 takes 三相纳米片 as both a main and the third high-tier material (136 = 116 + 20);
  "116 / 116 / 20" is the common case, not the rule.
