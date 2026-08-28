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
前置不满足时会打印补救命令：游戏的 exe 路径**从 AUTO-MAS 的 `Game.Path` 现问**，
不写死——2026-08-28 我在 `wingui.sh` 里凭印象填过两条 exe 路径，
事后 grep 发现那两条只存在于我自己刚写的那个文件里，差点被自己印证。
`wingui.sh launch` 现在只认别名 `wuwa`（路径核实过）或**完整 exe 路径**。

跑完会打印运行日志里的匹配摘要，并生成 `D:\ark\maaend\EssencePlan.html`
（`export_calculator_script`，路径见 `plan_export.go` 的 `planRecommendHTMLPath`）。

## 2026-08-28 首次实跑记录与两个教训

首次单跑 `EssenceFilter` 成功。过程中的事实与错误一并记下。

### 教训一：远端任务不会因为我本地被打断而停

我提交了第二轮（带 `--also-pure --also-5star`），用户中断了那次工具调用，
我据此告诉用户「那次压根没启动」。**错的。** 中断掐掉的是 Mac 这边的等待，
`POST /tasks/start` 早已发出，MaaEnd 照跑不误：

    23:26:02 初始化完成 → 23:30:42 筛选完成！确认锁定物品：5   （只金、只6★）
    23:32:20 初始化完成 → 23:37:17 筛选完成！确认锁定物品：8   （金+紫、含5★）

**下不为例：本地中断之后必须去 `/api/maa/state` 和 `/api/logs` 核实远端状态，
不许拿「我这边被打断了」推断「那边没跑」。**

### 教训二：运行日志不记录基质品质

`/api/logs` 里只有「匹配到武器 X」「已锁定基质」「已确认上锁」和战利品摘要
（武器 / 技能组合 / 锁定数量），**没有金紫蓝**。
所以「锁了几个紫的」这个问题，**日志答不出来**，只能进游戏看。
要能答，得给上游提需求让摘要带上品质。

### 蚀刻界面实地所见（2026-08-28 亲眼）

* 「基质蚀刻」的候选列表里**全是无瑕（金）基质**，没有高纯（紫）——
  紫色**不能作为蚀刻目标**。
* 每枚基质带**地区标签**（例：四号谷地），与「狗粮须同地区」的说法一致。
* 满配的那几枚三条都显示「已达上限」，数值正是 +6 / +6 / +3。

### MaaEnd 没有「解锁」功能

`assets/resource/pipeline/EssenceFilter/LockDiscard.json` 只有六个节点：
锁定入口 / 点锁 / 确认已锁、废弃入口 / 点废弃 / 确认已废弃。
界面文案里搜不到任何「解锁」（仅有无关的「协议空间未解锁」）。
**解锁只能手动。**

## 基质刷取的性价比（数据出自 MaaEnd `data/EssenceFilter/energy_point_gems.json`）

**重度能量淤积点·枢纽区**（四号谷地·组1），四个体力档的产出：

| 体力 | 金色基质 | 紫色基质 | 行动资历 | 每枚金基质的理智 |
|---:|---:|---:|---:|---:|
| 50 | 1 | 2 | 300 | 50 |
| 60 | 1 | 2 | 360 | 60 |
| 70 | 2 | 2 | 420 | 35 |
| **80** | **3** | 2 | 480 | **26.7** ← 最划算 |

**低档是纯亏的**：60 体力和 50 体力都只出 1 枚金基质。**只跑 80 档。**

命中特定三词条的概率（枢纽区池子：s1 五条 / s2 八条 / s3 八条）：

* 不开预刻写：1/5 × 1/8 × 1/8 = **1/320**
* 开预刻写（基础属性三选一 + 锁死一条附加或技能）：1/3 × 1/8 = **1/24**

折算成理智（80 档，26.7 理智/枚）：

* 开预刻写：约 24 枚 → **≈ 640 理智**
* 不开：约 320 枚 → ≈ 8540 理智

**预刻写把成本压到 1/13。不开等于白刷。**

## 快速配置（`Info.IfQuickConfig`）的真实边界

2026-08-28 实测：把 MAS 的理智任务从「干员养成」改成「基质刷取」后
**完全不生效**，因为 `AutoProxy.py:622-665`：

```python
target_sanity_task_exists = any(t["taskName"] == target_task_name for t in maaend_tasks)
sanity_missing = sanity_switch_enabled and not target_sanity_task_exists
...
if sanity_missing:
    warning_message = f"...当前 MaaEnd 配置中缺少 {target_task_name} 任务，已跳过理智任务快速配置"
```

**快速配置只能开关 MaaEnd 配置里「已经存在」的任务，它不会替你新建。**
母本 `<automas>/data/<scriptId>/Default/ConfigFile/mxu-MaaEnd.json` 的
AUTO-MAS 实例里 18 个任务只有 `ProtocolSpace`，没有 `AutoEssence`，
所以 MAS 打一条警告就跳过，照旧跑协议空间。

它能管的只有三样：`If<TaskName>` 的任务开关、理智任务类型+详细、基质地点
（写进 `AutoEssenceChooseLocation`）。**刻写券、领取方式、循环次数、战后筛选、
AutoFight 细节——MAS 一个都不管**，全部沿用 MaaEnd 自己那份配置。

另注：AUTO-MAS 跑前 `shutil.rmtree` 掉 `<maaend>/config` 再 `copytree` 自己那份
（`AutoProxy.py:514-515`），和 OK-WW 同一个母本/副本套路。
**改 `D:\ark\maaend\config` 那份不作数。**

## 三个候选点位的真实差别（2026-08-28 更正）

我先前说「三个点位词条池完全相同」**不准确**。逐条比对 `energy_point_gems.json`：

* **对诀而言没有区别**：三个点位都是 s1=5 / s2=8 / s3=8，且都含
  `attr_wisd` / `attr_usp` / `burst`，开预刻写都是 1/24。
* **但池子内容不同**，差的是**别的**词条：

  | 点位 | s2 相对枢纽区 | s3 相对枢纽区 |
  |---|---|---|
  | 武陵城 | +治疗效率/暴击率/生命　−自然伤害/灼热/源石技艺 | +医疗/残暴/切骨/夜幕　−追袭/效益/压制/巧技 |
  | 清波寨 | +治疗效率/物理伤害/生命　−自然伤害/攻击/灼热 | +医疗/昂扬/切骨/夜幕　−追袭/流转/效益/强攻 |

  这才是 CEP「顺带满足几把武器」数字不同的原因。

**MaaEnd 说的「成功率」不是出货率。** 原文在 `AutoEssenceChooseLocation`
的选项说明里：「受地形影响，目前成功率最高的地区是藏剑谷和清波寨，
成功率最低的地区是试验园区」——指的是**自动化能不能顺利跑图打完**，
和基质词条毫无关系。

**狗粮地区这条我先前也高估了。** 枢纽区属四号谷地、武陵城/清波寨属武陵，
蚀刻狗粮确实必须同地区；但刷 24 枚才命中一枚，同一批就顺带产出 23 枚同地区
狗粮，蚀刻满一枚只要 ~15 枚——**自给自足**。所以现有 1440 枚存货不是决定性理由。

## 体力档由世界等级决定，不是每次能选的

| 世界等级 | 推荐等级 | 体力 | 金基质 | 每枚理智 |
|---:|---:|---:|---:|---:|
| 4 | 40 | 50 | 1 | 50 |
| 5 | 50 | 60 | 1 | 60 |
| 6 | 55 | 70 | 2 | 35 |
| 7 | 60 | 80 | 3 | **26.7** |

**世界等级 7 的效率是 4 级的近两倍。**

## MAS 那六个「摆设开关」是结构性错配，不是谁点错了

`IfSeizeEntrustTask` / `IfAutoEcoFarm` / `IfAutoCollect` / `IfTrialOfSwordmancy` /
`IfResourceRecycleStation` / `IfPullCountCalculator`——MAS 界面上有，
MaaEnd 母本的 AUTO-MAS 实例里没有对应任务，所以**从来没跑过**。

成因：AUTO-MAS 的 schema 里固定声明了这一整套 MaaEnd 任务开关
（`models/schema.py:960-970`），而**任务是否存在取决于 MaaEnd 那边的任务列表**。
两边不是同一份清单。我们仓库里从未写过这些字段（`git log -S` 全空），
不是哪一次操作造成的。

和 `AutoEssence` 缺失是同一个洞：**MAS 只能开关已存在的任务，不会新建。**

## 淤积点在游戏里怎么找（2026-08-28 实地走通）

**行动手册 → 索引 → 能量淤积点** → 选点位 → **查看** → **前往传送**。

捷径：贵重品库 → 武器基质 → 选任一基质 → 右侧「获取方式 → 重度能量淤积点 ≫」，
点那个箭头会直接跳到上面那个索引页。

传送落点是**最近的协议传送点**（和 MaaEnd 的 `GotoTriggerPointSetAnchor_VFTheHub`
一致），淤积点还要再走一小段：MaaEnd 的路径是
`ZONE ValleyIV_Base → NAVMESH (456.92, 932.86) → (463.41, 938.85)`。

**注意：`wingui.sh key` 只能发单次按键，按不住 WASD，最后这段走不了。**
要么让 MaaEnd 的 `AutoEssence` 自己走（它就是这么做的），要么人工走。

### 枢纽区能出的技能词条只有 8 种

淤积点详情页「消耗理智领取奖励」列出 9 个图标 = 该点位的 `battleRandomPresets`：

    无瑕基质（无技能词条）、强攻、压制、追袭、粉碎、巧技、迸发、流转、效益

**「夜幕」「切骨」「医疗」「残暴」「附术」「昂扬」在枢纽区刷不到**——
这和 `energy_point_gems.json` 里枢纽区的 `skillTermIds` 完全一致。
预刻写能锁的技能属性只能从这 8 种里选，诀要的「迸发」在其中。

## 预刻写怎么设（2026-08-28 实际做成）

**位置**：淤积点的「开启挑战」界面 → 右下「属性选择」。
不是菜单里某个设置项，必须走到那个点位、激发之后才有。

**用 MaaEnd 走过去、但不要开打**：

```
winrun.sh --py scripts/mac/lib/maaend_task.py --entry AutoEssenceMain \
    --override-b64 <base64 of {
      "GotoTriggerPointSetAnchor_VFTheHub": {"enabled": true},
      "AutoEssenceClickEssenceStartButton": {"action": {"type": "DoNothing"}, "next": []}
    }> --go
```

30 秒走到并激发，停在开启挑战界面，**不花体力**（体力是领奖时才扣的）。
`AutoEssenceClickEssenceStartPrepare` 才是那个界面，它的下一步
`AutoEssenceClickEssenceStartButton` 被掐掉就停住了。

**界面上的选项和 CEP 的数据完全一致**（这条是用户质疑后当场核对的）：

    基础属性 5 个：敏捷 / 力量 / 意志 / 智识 / 主能力        ← s1Pool = 5
    附加属性 8 个：攻击 / 灼热 / 电磁 / 寒冷 / 自然 / 源石技艺 / 终结技充能 / 法术
    技能属性 8 个：强攻 / 压制 / 追袭 / 粉碎 / 巧技 / 迸发 / 流转 / 效益   ← s3Pool = 8

规则写在界面上：**基础属性选 3 条，奖励基质的基础属性在这 3 条里随机出 1 条；
附加或技能属性选 1 条，该条必定出现，剩下 1 条完全随机。**
所以命中率 = 1/3 × 1/8 = 1/24，和先前算的一致。

**代价**：预刻写生效时收取奖励额外消耗 **1 张刻写券**（当前余额 599）。

诀的设置已改为 CEP 方案 1：**基础 智识/力量/敏捷 ｜ 技能锁 迸发**。

## winrun 现在会自动带上同目录依赖

`maaend_task.py` import `maaend_essence` 时远端报 `ModuleNotFoundError`——
winrun 只送单文件。已改成按被送脚本的 import 语句自动带上 `scripts/mac/lib/*.py`。

**pipeline_override 必须走 base64**：裸 JSON 穿过 bash → ssh → cmd → PowerShell
四层会被啃掉引号，实测变成 `{GotoTrigger...`。`--override-b64` 是唯一入口。
