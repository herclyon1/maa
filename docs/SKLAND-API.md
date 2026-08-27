# 森空岛（终末地）接口

2026-08-27 打通并实测。凭证链路和签名在 `relay/ark_relay/skland.py`。
**token 等同账号登录凭证，只放机器上的 `.env`，任何日志/报告/仓库里都不许出现。**

## 一、签名（三处错了就是 403，且它不告诉你错在哪）

```
sign = MD5(HMAC-SHA256(签名token, path + query + timestamp + json({platform,timestamp,dId,vName})))
```

* `platform` = **"3"**（不是 1）
* `vName` = **"1.0.0"**（不是空串）
* `dId`（设备指纹）必须**和 cred 是同一次会话产生的一对**：换 cred 的那次请求就要带上它，
  之后每个请求和签名里都用同一个。不带的话 cred 能换到，但 refresh 直接回「设备信息无效」。
* 时间戳要和服务器对齐：先 `GET /web/v1/auth/refresh`（它不需要 sign），
  记下服务器时间与本地时间的差，之后按差值校正。长期用固定值会被判「请勿修改设备本地时间」。
* `roleId` 取 `bindingList[].roles[].roleId`，`serverId` 取同一层的 `serverId`，
  **都不是 `channelMasterId`，也不是绑定项外层的 uid**。

## 二、账号与练度

| 接口 | 给什么 |
|---|---|
| `GET /api/v1/game/endfield/card/detail?roleId=&serverId=` | 全量个人数据，练度在 `data.detail.chars[]` |
| `GET /api/v1/game/endfield/card/war-echoes` | 战争回响 |
| `GET /api/v1/game/endfield/card/crisis-contract` | 危机合约 |

`chars[]` 每项：`level`、`evolvePhase`（突破）、`potentialLevel`（潜能）、
`userSkills{技能id:{level,maxLevel}}`、`weapon{level,refineLevel,breakthroughLevel,gem}`、
`bodyEquip`/`armEquip`/`firstAccessory`/`secondAccessory`（各带 `enhance` 逐条词条强化等级）、
`tacticalItem`、`talent{attrNodes,latestPassiveSkillNodes,latestFactorySkillNodes,latestSpaceshipSkillNodes}`。

> 词条只给英文字段名（`equip_attr_agi` 之类），**这份数据里没有译名表**，不许自己编中文名。

出报表：`scripts/mac/endfield-report.py <ef_card.json> [输出.xlsx]`

## 三、官方养成计算器（`game.skland.com/tools/endfield/*` 底下真正调的接口）

接口地址是从工具页的 JS 包里挖出来的（`assets.skland.com/_static_assets/game-tools/*.js`，
搜 `/web/v1/game/endfield`）。全部在 `zonai.skland.com` 上，用同一套签名。

| 接口 | 给什么 |
|---|---|
| `GET /web/v1/game/endfield/calculate/rules` | `charLevelRules`/`weaponLevelRules` 各 90 条，逐级的 gold 与 exp |
| `GET /web/v1/game/endfield/calculate/material-list` | 32 种材料（含 exp 值、稀有度）+ `priorities`（各类材料的消耗优先级） |
| `GET /web/v1/game/endfield/calculate/user-game-data` | **你的库存**：`userChars` 30、`userWeapons` 60、`itemCount` 37 |
| `POST /web/v1/game/endfield/calculate/record/submit` | 提交一次养成计算 |
| `GET /web/v1/game/endfield/calculate/record/view` | 取回计算结果 |
| `GET /web/v1/game/endfield/enums` | 全部枚举（属性、装备等级、职业……） |
| `GET /web/v1/game/endfield/game-terms` | 游戏术语表 |
| `GET /web/v1/game/endfield/search-chars` / `-weapons` / `-equipments` / `-tactical-items` | 图鉴检索 |
| `GET /web/v1/game/endfield/char-pair` / `char-pair/char-list` | 配队工具的数据 |
| `GET /web/v1/game/endfield/team/user-char-data` / `user-game-data` | 配队工具用的账号数据 |

**能算什么**：规则 + 材料表 + 你的库存三者齐全，
「把某角色/武器练到 X 级还差哪些材料、差多少」可以完全自己算，不必开网页。

**不能算什么**：官方**没有**「该优先练谁」的算法接口。
`priorities` 是材料消耗优先级，不是角色推荐。
快捷入口里的「养成建议」(`/tools/endfield/build-guide`) 是**玩家发布的攻略**，
不是官方算出来的结论。

## 四、快捷入口（`detail.quickaccess` 原样返回）

| 名字 | 网页地址 |
|---|---|
| 养成计算器 | `game.skland.com/tools/endfield/cost-calculator` |
| 养成建议 | `game.skland.com/tools/endfield/build-guide` |
| 配队工具 | `game.skland.com/tools/endfield/rec-team` |
| 地图工具 | `game.skland.com/map/endfield` |
| 每日签到 | `game.skland.com/endfield/sign-in` |

网页版要登录才能用；我们走接口，不需要登录网页。

## 五、社区工具（有「该练谁」的判断，但那是人写的攻略）

| 项目 | 有什么 |
|---|---|
| [cmyyx/cep](https://github.com/cmyyx/cep) | 终末地规划器：基质规划、**角色养成与配装推荐**、精锻规划、卡池日历 |
| [caffuchin0/zmdgraph](https://caffuchin0.github.io/zmdgraph/) | 养成规划计算器，已接入森空岛，支持实时仓库材料同步 |
| [FubukiProto/…Essences-Calculator](https://fubukiproto.github.io/Arknights-Endfield-Essences-Calculator/) | 基质计算器 |
| [JamboChen/endfield-calc](https://github.com/JamboChen/endfield-calc) | 工厂产线数值计算 |
| [otae-1204/otae-bot-entari](https://github.com/otae-1204/otae-bot-entari) | `docs/skland_endfield_personal_api.md`，本文签名部分的出处 |

## 六、养成建议与配队攻略（就是「养成建议」那个工具）

**没有 build-guide 这个接口**。工具页底下调的是这两个，都用同一套签名：

| 接口 | 给什么 |
|---|---|
| `GET /web/v1/game/endfield/char-pair/char-list?charId=<32位id>` | 养成搭配方案：`pairId`、主角色、搭档、`content.title`、`content.pairReason`（推荐理由原文） |
| `GET /web/v1/game/endfield/team/char-list?charId=<32位id>` | 配队攻略：`chars[].skills[].recRank`（**推荐技能等级**）、`mainWeapon`、`backupWeapons` |
| `GET /web/v1/game/endfield/team/tag/list` | 标签：新手推荐 / 高玩进阶 / 影拓丰碑 / 战争回响 / 蚀像寻遗 / 趣味搭配 |

**`charId` 必须传**，不传只会拿到 `{"list": []}`——2026-08-27 就是这么误判成
「接口不通」的。前端那个 `toCommonId()` 对普通角色是原样返回，只把
「管理员」的男/女版本合并成一个 id，所以直接用角色卡里的 32 位 id 即可。

`team/index`（攻略总列表）仍回「参数错误」，参数没摸清；按角色查已经够用。

## 七、官方四档「培养模版」

数值取自前端常量（`assets.skland.com/_static_assets/game-tools/*.js`，
搜 `cost_calc_template_`），**不是我估的**：

| 档 | 等级 | 技能 | 武器 |
|---|--:|--:|--:|
| 基础 basic | 60 | 6 | 60 |
| 晋级 advanced | 80 | 9 | 80 |
| 高阶 high_tier | 90 | 9 | 90 |
| 完美 perfect | 90 | 12 | 90 |

算缺口要按档，别默认拿最高档——2026-08-27 我一上来按 90 级算，
结论是「缺口很大」，其实到「晋级」为止全部材料都够。

消耗规则：`GET /web/v1/game/endfield/calculate/rules?charIds=<单个id>` 返回
`breakthroughs`（突破节点的金币与材料）、`skills[].levels[]`（每级技能的金币与材料）、
`talents[].activateRule`。**多个 id 用逗号拼会返回空表**，只能一个一个问。
