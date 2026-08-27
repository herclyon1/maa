# 终末地外部资料源（我们俩都不懂这游戏，先查这里）

按「能不能当证据用」排序。**上面两档可以直接引用，第三档要交叉验证，攻略站单独一条不算数。**

## 一档：官方游戏数据（唯一能当硬证据的）

| 源 | 内容 | 用法 |
|---|---|---|
| [3aKHP/EndFieldGameData](https://github.com/3aKHP/EndFieldGameData) | `ItemTable`(2376 条) + `i18n/CN.json`(11.6 万条) + 角色/敌人/装备表 | `gh release download v0.2.0 -R 3aKHP/EndFieldGameData`，见 [ENDFIELD-ITEMS.md](ENDFIELD-ITEMS.md) |
| [Variante/endfield_research_kit](https://github.com/Variante/endfield_research_kit) | 上面那份 dump 的**生产工具**，从本地客户端导出 | 需要更多表（比如干员培养消耗表）时用它自己导 |
| [daydreamer-json/ak-endfield-api-archive](https://github.com/daydreamer-json/ak-endfield-api-archive) | 游戏 API 响应存档，5 分钟一次 | 查版本/公告/资源清单 |

**已知缺口**：那份 v0.2.0 dump **没有干员培养消耗表**——`CharacterTable` 只有属性和语音，
29 个干员没有一个引用 `item_char_skill_specialize_*`。所以「谁要多少材料」查不到，得靠下面第三档。

## 二档：Wiki（结构化、有逐干员材料表）

- **[BWIKI 终末地](https://wiki.biligame.com/zmd)** — 中文最全，有[物品图鉴](https://wiki.biligame.com/zmd/物品图鉴)
- **[end.canmoe.com](https://end.canmoe.com/zh-CN/wiki/characters/chr_0016_laevat)** — 按 `charId` 直接定位，和游戏 id 对得上
- [Game8](https://game8.co/games/Arknights-Endfield) / [Prydwen](https://www.prydwen.gg/arknights-endfield/) — 英文

## 三档：逐干员培养材料（数字来源）

- **[enjoygm.com](https://www.enjoygm.com/zh-TW/blog/arknights-endfield/liino-materials)** — `/zh-TW/blog/arknights-endfield/<角色>-materials`，
  **逐项列出五种高阶素材各要多少、用在精英化还是专精**，目前找到的最细的一家
- 游民星空「养成一图流」系列 — 每个干员一篇，搜「终末地 <角色> 一图流」
- [游民星空 满练度素材消耗一览](https://www.gamersky.com/handbook/202602/2085397.shtml) — 总量口径

## 四档：规划器 / 工具

| 工具 | 干什么 |
|---|---|
| [endfieldtools.dev](https://endfieldtools.dev/ascension-planner/) | 培养规划，可录库存（WebFetch 403，要浏览器开） |
| [perlica.moe](https://perlica.moe/planner) / [基质优化器](https://perlica.moe/essence-optimizer) | 培养规划 + 基质刷取优化 |
| [cmyyx/endfield-essence-planner](https://github.com/cmyyx/endfield-essence-planner) | **基质规划器**，开源 |
| [SodaXu/endfield-crafting-manual-checklist](https://github.com/SodaXu/endfield-crafting-manual-checklist) | 简制手册素材来源查询 |
| [Terra-Online/Atlos](https://opendfieldmap.cn/) | 互动地图 |
| [Kirukata27/arknights-endfield-resources](https://reend.vallov.com/) | 干员强度榜、卡池机制、编队指南 |

索引全集：[palmcivet/awesome-arknights-endfield](https://github.com/palmcivet/awesome-arknights-endfield)（61 个项目），
本地快照 [ref/awesome-arknights-endfield-LIST.md](ref/awesome-arknights-endfield-LIST.md)。

## 血的教训：五种高阶素材的口径

`item_char_skill_specialize_1..5` = 超距辉映管 / D96钢样品四 / 快子遴捡晶格 / 象限拟合液 / 三相纳米片。

- 官方描述五条**一模一样**（「用于干员精英化、武器突破、干员技能专精的珍稀素材」），**看描述判断不了用途差异**
- 各有专属关卡 `dungeon_ss01..ss05`，也各有专属商店兑换 → **五种不能互相顶替**
- **但一个干员会同时吃好几种，数量差很多**。实例（梨诺）：
  象限拟合液 **136**（精英化四阶 20 ＋ 技能专精 116）、D96钢样品四 **116**（技能专精）、超距辉映管 **16**（专武突破）
- 所以：**既不能把五种加起来当一个池，也不能说「每人只吃一种」——我两种说法都犯过。**
  要算某个干员的缺口，去三档查那个干员的逐项需求。
