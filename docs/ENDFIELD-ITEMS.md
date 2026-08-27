# 终末地物品表 - id、中文名、用途

全量扫库(`debug/record/IMS.json`)给的是 id，这里是怎么把它变成人能看的东西。

## 数据源（按可信度）

1. **官方数据表镜像 `3aKHP/EndFieldGameData`** - 权威，首选。
   `tables/ItemTable.json`(2376 条) + `i18n/CN.json`(11.6 万条)。
   ```bash
   gh release download v0.2.0 -R 3aKHP/EndFieldGameData   # endfield-tables.zip 23MB
   ```
   `ItemTable[id]` 有 `name`/`desc`(int64 哈希，去 `i18n/CN.json` 里按 **字符串** 键取)、
   `rarity`、`type`(用途分类)、`valuableTabType`(仓库页签)、`obtainWayIds`(获取途径)。
   注意 zip 是 2026-06-22 的快照，之后新增的物品会缺（已知缺 `item_plant_mushroom_seed_2_3` 塔罗斯菌块）。
2. **MaaEnd 自带 `locales/interface/zh_cn.json`** - 只有名字没有用途，但不用下载。
   拍平成 `{key 最后一段: 字符串}` 后按 **最后一段精确匹配**；
   模糊匹配会串到 `task.ProtocolSpace.focus.supply_plan.*` 的提示语模板，
   查出「折金票 未达标，准备刷取协议空间」这种垃圾。
3. 攻略站（游民星空/17173/game8/Prydwen）- 只用来查“培养一个干员要多少”，不用来查 id。

## IMS.json 里的两套 id

- `item_*` / `ap_*`（49 个）= **真正的仓库库存**，在官方 ItemTable 里全能查到。
- 14 个大写 id（`T_CREDS`/`OROBERYL`/`VALLEY_STOCK_BILL`/`PROTOPRISM`…）
  = MaaEnd 各任务的**定点 OCR 节点**，用游戏英文名命名。证据：
  官方 ItemTable 里 **一个都没有**，MaaEnd 目录里除 `IMS.json` 外**一个文件都不出现**，
  且同名条目数字和 `item_*` 对不上（`T_CREDS` 47,500 vs `item_gold` 6,671,367）。
  **统计库存时忽略这 14 个。**

## 扫库覆盖的页签（重要：不是全仓库）

官方 `ItemTable` 的 `valuableTabType` 一共 8 个值，**MaaEnd 扫库只回了其中 4 个**：

| 页签 | 全表条目 | 扫库回了几个 | 内容 |
|---:|---:|---:|---|
| 1 | 71 | 0 | |
| **2** | **181** | **0** | **基质 `gem_*`（156 条全在这里）** |
| 3 | 220 | 0 | 装备 |
| 4 | 40 | 33 | 养成素材 |
| 5 | 111 | 0 | |
| 6 | 1438 | 12 | 货币等 |
| 7 | 65 | 1 | 行动资历 |
| 10 | 250 | 2 | 理智相关 |

**所以「基质有多少个」扫库答不出来。** 基质是 `type=19`、页签 2 的装备类物品，
每把武器 1 个位、最多 3 条词条；蚀刻每次固定吃 1 个五星无瑕基质使词条 +1 级，
失败返 10 冷却脂，词条上限 6/6/3 = 15 级 → 满练一把武器 ≥ 16 个基质。
分母清楚，分子拿不到。

**原因已定位，不是「本来就空」也不是 MaaEnd 的能力上限：**
我们的扫库不是 MaaEnd 开放的功能，是绕过界面直接调内部 entry `SyncItemData`。
它的链条是 `SyncItemData -> SyncItemDataBegin -> **SyncItemDataInProgressionTab**
-> SyncItemDataRunFull` —— **进的是「养成」页签**，`RunFull` 是「把这一栏扫全」，
不是「扫整个仓库」。页签 4/6/7/10 正是从养成栏能够到的，基质在页签 2，压根没去。

**下一步（要机器在线）**：翻 `resource/pipeline/nodes.json` 里所有 `SyncItemData*`
节点和那个切页签的节点，看页签是不是参数化的。是 → 用 `pipeline_override` 指到基质栏
重跑，diff `IMS.json`；不是 → 才算真缺口，值得提 issue。
调用方式见 [HEADLESS.md](HEADLESS.md#maaend-扫库要用-tasksstart不是-tasksrun)。

## 按官方 `type` 分的用途

| type | 用途 | 物品 |
|---|---|---|
| 7 | 干员经验 | 初/中/高级作战记录(1-60级)、初/高级认知载体(61-90级) |
| 27 | 干员晋升/技能 | 协议圆盘(精英一二)、协议圆盘组(精英三四)、协议棱柱+棱柱组(技能等级) |
| 95 | 高阶稀有素材 | 超距辉映管、快子遴捡晶格、象限拟合液、三相纳米片（精英化+武器突破+技能专精共用） |
| 96 | 技能专精 | 存续的痕迹 |
| 8 | 晋升用晶植成品 | 重红柱状菌(60级)、星门菌/血菌(80级)、重黯石(武器60) |
| 34 | 晶植**种子** | 各种子簇/菌块/根茎 - 进培养舱种出 type=8 的成品 |
| 25 / 26 | 武器经验 / 武器突破 | 武器检查单元-装置-套组 / 强固模具、重型强固模具 |
| 61 / 87 / 88 | 基质技能 / 武器潜能 / 装备精锻 | 冷却脂 / 协议化武器原型 / 武陵精锻助剂 |
| 1,2,29,44,53,79 | 货币 | 折金票、嵌晶玉、衍质源石、信用、武陵/谷地调度券、武库配额 |
| 37 / 84 | 账号/通行证经验 | 行动资历、通行证经验 |
| 62 / 98 | 理智 | 应急理智加强剂(+40)、理智消耗许可(双倍) |

## 满练一个干员的成本（游民星空 2026-02）

1-60级 74 高级作战记录+7 中级+2 初级；61-90级 94 高级认知载体+2 初级。
精英化 33 协议圆盘 + 57 协议圆盘组 + 各色菌 + 20 高阶。
四技能全专三 328 协议棱柱 + 492 协议棱柱组 + 24 存续的痕迹 + 232 高阶 + 各色晶植。
合计约 **120 万折金票、10720 理智**，纯自然恢复 53 天，算日常奖励约 39 天。
→ **高阶稀有素材(type=95)每人 252 个是绝对瓶颈**，其余都不卡。

## 在线规划器

- <https://endfieldtools.dev/ascension-planner/> - 能录库存算差额（WebFetch 403，要浏览器开）
- <https://perlica.moe/planner>

## 武器词条的三层等级（2026-08-28 全量验证）

`card/detail` 里每把武器实例的 `weapon.skills[]` 是核对基质的**正确字段**，
不用绕 CEP、不用比中文：

    { key, name, gemTermId, level, currentBaseLevel, currentMaxLevel }

* **`gemTermId` 与 `gem.terms[].id` 是同一套 hash id。** 核对一句话：
  `{s.gemTermId} == {t.id}`。本账号 19 把带基质的武器 18 把相等，
  唯一不等的是狼卫的同类相食（装了夜幕、武器要附术）——
  和绕 CEP 那条路结论完全一致，互为独立验证。
* **`level = currentBaseLevel + 该词条在基质上的 cost`**，83/83 条实例成立。
  `currentBaseLevel` 是武器自带的底（6★ 属性位 3、技能位 1；莱万汀精炼1 → 技能底 2）。
* **`terms[].cost` 是词条的加成级数**，不是固定属性——同一词条在不同基质上
  出现过 1/2/6。上限：属性词条 6、技能词条 3，合计 15。
  出处：游民星空《武器基质系统详解》「基质的技能属性至多加成 3 级，
  而其余两个词条可以至多加成 6 级」，本账号 57 条实例无一越界。

### `currentMaxLevel` 由武器练度决定，`skillInfos[].maxLevel` 是静态天花板

`weaponData.skillInfos[].maxLevel` 恒为 9/9/4（3★ 是 9/4），与星级、精炼、
突破全无关——那是满突破零精炼时的上限。真正当下的上限是 `currentMaxLevel`：

| 突破 | 属性位 | | 精炼 | 技能位 |
|---:|---|---|---:|---|
| 0 | 3 / 3 | | 0 | 4（3★ 为 3） |
| 2 | 6 / 6 | | 1 | 5 |
| 3 | 8 / 7 | | 2 | 6 |
| 4 | 9 / 9 | | | |

即：**属性两位只看突破，技能位只看精炼**，5★ 与 6★ 同表。
（本账号 25 把武器覆盖到的组合，未覆盖的突破 1 未验证。）

## MaaEnd 对基质能做什么、不能做什么

任务清单取自上游 `assets/locales/interface/zh_cn.json`：

| 能做 | 任务 | 说明 |
|---|---|---|
| 刷 | `AutoEssence` 🎱基质刷取 | 自动挑战重度淤积点。可选地区（枢纽区 10 个）、单倍/双倍/不领取、循环次数、是否**使用刻写券**（需事先在淤积点开始界面选好要刻写的属性） |
| 筛 | `EssenceFilter` 🔒基质筛选锁定 | 战后自动筛选并锁定有用的。可设「保留未来可期基质」（三条齐全且总等级 ≥ 阈值，默认 6）、「保留实用基质」（词条3 等级 ≥ 阈值）、「未匹配时废弃」 |

**不能做：蚀刻。** 整份界面文案里没有「蚀刻」二字，也没有对应任务。
蚀刻是把基质词条从 1~3 级练到 6/6/3 的唯一途径（每次吃 1 个同地区金色基质，
失败返冷却脂可换必成），**只能手动**。
所以「自动养成基质」目前是：**自动刷 + 自动筛选锁定，手动蚀刻**。

## 蚀刻：已查实的 / 没查实的

**已查实**（[dvg.cn/danjigl/116572](https://www.dvg.cn/danjigl/116572.html)，
与多处二手转述一致）：

* 一次蚀刻消耗 **1 个同地区的金色（无瑕）品质基质**当狗粮。
* 成功率分四档：**极高 / 高 / 低 / 极低**。
* **失败得「冷却脂」**；攒够冷却脂可以走「消耗冷却脂」蚀刻，**必定成功**（大保底）。
* 瓶颈在狗粮不在胚子——B站实测帖标题即「难在狗粮而不是胚子」。

**没查实，不许编**（三个来源都写「未明确说明」）：

* 被强化的是**已装备在武器上**的基质，还是仓库里任意基质？
* 一次蚀刻升的是**哪一条**词条——随机，还是可以指定？

→ 机器开机后到游戏里打开蚀刻界面直接看，别再从攻略推。

**顺带纠正一个常见误解**：蚀刻的目标不是「已经完美的基质」。
已经 6/6/3 的基质不需要蚀刻。目标是**词条组合正确但等级不够**的那一个，
把它从 1~3 级顶到 6/6/3；「没用的」是被吃掉的狗粮。

## CEP 的基质规划 ≠ MaaEnd 的基质筛选锁定

两者**不是同一个功能**，在流程的两端，互补：

| | CEP（网页，`/essence`） | MaaEnd `EssenceFilter` |
|---|---|---|
| 在哪跑 | 浏览器，不碰游戏 | 游戏里实际点击 |
| 输入 | 你要练的武器 | 战斗掉落的基质 |
| 输出 | 去哪个淤积点、预刻写锁哪三条 | 锁定有用的 / 废弃没用的 |
| 它的「筛选」指什么 | 筛**方案列表**（按属性、按地区），文案见 `essence.attrFilterTitle` / `essence.regionFilter` | 筛**掉落物**（按武器匹配、未来可期、实用基质） |

用法：**CEP 定去哪、锁什么 → MaaEnd `AutoEssence` 去打并 `EssenceFilter` 处理掉落 → 蚀刻手动。**

## 单独调用「基质筛选锁定」（不跑整条队列）

工具：`scripts/mac/lib/maaend_essence.py`，用 winrun 送到游戏机上跑。

```
winrun.sh --py scripts/mac/lib/maaend_essence.py          # 只体检，不动手
winrun.sh --py scripts/mac/lib/maaend_essence.py --go     # 真跑
```

**调查结论（2026-08-28，全部读上游源码得出，机器当时不在线）：**

* 任务名 `EssenceFilter`，入口节点 **`EssenceFilterMain`**，
  controller 支持 `Win32-Front`——**可以单独调用**。
* **不要求游戏停在某个界面。** `EssenceFilterMain.next` 里挂着
  `[JumpBack]SceneEnterMenuValuables`，不在基质页就自己跳贵重品库，
  再切「武器库 → 武器基质」页签。但游戏必须在跑、且能开菜单。
* 分工（`agent/go-service/essencefilter/README.md`）：
  C++ `RecoGrid`/`GridTracker`/`EssenceGrid` 扫网格挑格子 →
  Pipeline 逐格 OCR 三条技能和等级 → Go `matchapi` 匹配 →
  Go 只通过 `ctx.OverrideNext` 选分支，**点击全在 Pipeline**。
* **匹配的是该稀有度的全部武器**（`weapons_output.json`），
  不是「我拥有的武器」。所以命中 = 这枚基质对某把 6★ 武器是毕业词条。
* 必须 `/tasks/start` 不能 `/tasks/run`——run 不拉 agent 子进程，
  识别匹配全在里面，会一路 `Action is null`。见 [HEADLESS.md](HEADLESS.md)。

**脚本里写死的两件事，故意不给开关：**

* `discard_unmatched: false`——废弃是不可逆的，要废弃自己去界面点。
* 跑完必定 `POST /agent/stop`，否则两个子进程一直挂着。

**前置检查**（不满足就直接退出，不硬闯）：`MaaEnd.exe` 和 `Endfield.exe`
在跑；`GET /api/maa/state` 里存在一个 `connected` + `resource_loaded` +
`tasker_inited` 三项皆真、且 `is_running` 为假的实例。
**本脚本不新建实例**——新建的这三项都是假的。
字段名抄自 MXU `src-tauri/src/web_server.rs` 的 `handle_get_maa_state`。

跑完会打印运行日志里的匹配摘要，并生成 `D:\ark\maaend\EssencePlan.html`
（`export_calculator_script`，路径见 `plan_export.go` 的 `planRecommendHTMLPath`）。
