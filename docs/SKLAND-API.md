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
(one today) with `rows` mirroring the default one. Built 2026-09-18/19 (branch `data`).

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
user's caliber (2026-09-18, final): every older operator is built, so the need is **the
newest released six-star's full build with her signature weapon** - one standard, no
averages, no roster maximum. `--rarity 5` takes the newest five-star instead, `--char` /
`--weapon` a named pair.

*Who is the newest six-star, which weapon is hers* (official wiki, no account data):

| Call | Field |
|---|---|
| `GET /web/v1/wiki/item/catalog?typeMainId=1&onlyOnline=true` | subtype 干员 and subtype 武器; rarity tag `brief.subTypeList[subTypeId=10000].value` (`10006` six-star, `10005` five-star, `10004` four-star); `brief.dotType` `label_type_preview` = announced, not yet released, `label_type_up` = on a banner now |
| `GET /web/v1/wiki/item/info?id=<itemId>` | the entry's attribute table, `{label, value}` pairs inside `document`: operators `上线时间` / `主要获取方式`; weapons `上线时间` / `类型` / `主要获取方式` |

* Newest six-star = latest `上线时间` **not after today** (server date). 2026-09-18: 提弗洛斯
  (item 2116) 2026年9月2日, ahead of 梨诺 08-09, 诀 07-16, 卡缪 06-26, 弭弗 06-05, 庄方宜 04-17,
  洛茜 03-29, 汤汤 03-12 and the launch roster 01-22. An entry with a future date (噗切娜,
  item 2117, 2026年9月24日, `label_type_preview`) goes to `coverage.upcoming`, never chosen.
* Signature weapon = the six-star weapon with the same `上线时间`, her `类型` (`search-chars`
  `weaponType`) and `主要获取方式` 「武库交易所·限时特卖」 - the limited-sale slot every banner
  weapon is sold in. 2026-09-02 has two new 施术单元: 寒夜幽影 (限时特卖, item 2118) and
  苦难的尽头 (协议通行证·武器补给) - the rule names 寒夜幽影 alone. The same rule gives
  熔铸火焰 for 莱万汀 (01-22). Not unique -> the build stops and asks for `--weapon`.
  Cross-checks, not inputs: the version bulletin runs 「幽寒申领」 with 寒夜幽影 as the UP
  weapon next to her banner 「冬猎」; the client's `CharWpnRecommendTable` lists
  `wpn_funnel_0019` (= 寒夜幽影, md5 of the code is the calculator's id) first for
  `chr_0034_typhoea`; the account has it on her.
* Why not other fields: `search-chars` orders by rarity and carries no date; the catalog's
  `publishedAtTs` is the wiki editor's publish time (the launch roster was published
  2026-01-10 ~ 01-12); the account's `ownTs` is when *this* account got someone.

*Numbers*: `rules?charIds=<her id>` (breakthroughs + skills to 12, talents excluded, §B
of ENDFIELD-SANITY-YIELD.md) and `rules?weaponIds=<the weapon's id>` - **hers only**; no
other operator's rules are pulled, compared or kept (the user, 2026-09-19: 老角色的东西一律
不看). Each row's `group` says where the count comes from: 提弗洛斯, 专武 寒夜幽影, or both
(象限拟合液 116 + 16, 折金票). 提弗洛斯 + 寒夜幽影 on 2026-09-18: 协议棱柱组 472, 协议棱柱 328,
协议圆盘组 60, 协议圆盘 33, 存续的痕迹 24, 多齿叶 16/16/12, 红柱状菌 5/5/3, D96钢样品四 116,
象限拟合液 132, 快子遴捡晶格 20, 红矛叶 84, 塔罗斯菌 8; 重型强固模具 50, 强固模具 23, 黯石 5/5/3,
协议纹石 8; 折金票 1,693,510, 干员经验 1,792,290, 武器经验 2,524,080. The calculator's 32-hex ids
are `md5(<internal code>)` (`chr_0006_wolfgd` -> `26e3cc73…`, `wpn_funnel_0019` ->
`4e7f3757…`), which is how a client-side code can be turned into a calculator query.

*For the page*: every row carries `section` (通用 / 高阶素材 / 采集 / 经验与货币, the order in
`games[].sections`; the eight exp cards have none and fold into 干员经验 / 武器经验),
`games[].footnote` is the 人份 caption, and `games[].lagMinutes` / `lagNote` quote the
official calculator page's own line 「仓库资源和干员数据等信息的同步，会有 30 分钟左右的延迟」.
`web/data/inventory-demo.json` is the live object's exact shape with invented counts.
Fixtures for the test are eight files: her rules, the weapon's, the two catalogs'
listings, the wiki catalog and its entries (one merged file), material-list.

Read-off traps, each pinned by `relay/tests/test_need_table.py`:

* `charLevelRules[89]` (level 90) is `gold: "-1", exp: "-1"` - a sentinel, not a cost.
  Summed in, it produced the 385,419 / 1,792,289 / 1,693,509 that ENDFIELD-SANITY-YIELD.md
  carried for a day; the real figures are 385,420 / 1,792,290 / 1,693,510
  (`weaponLevelRules` ends in `0 / 0`).
* `material-list` names had a trailing newline on 2026-08-28 (`"D96钢样品四\n"`) and did
  not on 2026-09-18 - always strip.
* 诀 takes 三相纳米片 as both a main and the third high-tier material (136 = 116 + 20);
  "116 / 116 / 20" is the common case, not the rule.
