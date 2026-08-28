# AUTO-MAS 与 OK-WW：界面、配置与无界面操作

写于 2026-08-25。**这份文档的目的是：下次不必再摸索一遍。**
凡是这里写的结论，都是当天在真机上读源码或调 API 核对过的，不是推测。

相关：[HEADLESS.md](HEADLESS.md)（各程序的无界面入口）、
[CONFIG.md](CONFIG.md)（具体配置项与母本/副本）、[PITFALLS.md](PITFALLS.md)。

---

## 先说结论：不用点界面

AUTO-MAS 的 Electron 窗口只是外壳，后面是一个 **FastAPI 后端**，
监听 `<tailscale-ip>:36163`，**无鉴权**，126 个端点。

```bash
export ARK_HOST=100.65.39.119
scripts/mac/mas-api.py paths                       # 全部端点 + 必填字段
scripts/mac/mas-api.py get /api/queue/get
scripts/mac/mas-api.py get /api/scripts/user/get '{"scriptId":"<uid>"}'
```

**走 API 改配置不需要重启 AUTO-MAS。** 这一点很重要，因为直接改
`config/*.json` 文件**会失效**：AUTO-MAS 把配置读进内存，退出时反写，
你在它运行期间改的文件会被它的内存值覆盖。走 API 是后端自己落盘，不存在这个问题。

> 2026-08-24 就踩过：改了文件、界面没变化，误以为"没生效"，其实是写法不对。

---

## 五个界面分别是什么

| 界面 | API 前缀 | 存的是什么 | 谁引用它 |
|---|---|---|---|
| **脚本管理** | `/api/scripts/*` | 每个自动化程序一条：装在哪、超时多久、重试几次；下挂**用户** | 调度队列按 `ScriptId` 引用 |
| **计划管理** | `/api/plan/*` | 按星期几切换刷什么的**计划表**，可选功能 | 用户的 `StageMode`/`SanityMode` 填计划 uid 才生效 |
| **模拟器管理** | `/api/emulator/*` | 模拟器可执行文件、多开序号、老板键、等待超时 | 脚本的 `Emulator.Id`；端游脚本填 `-` |
| **调度队列** | `/api/queue/*` | 一条队列 = 一串**队列项**（每项一个脚本）+ 一串**定时项** | 就是每天真正跑起来的东西 |
| **调度中心** | `/api/dispatch/*` | **没有静态配置**，是运行时面板：手动起停、电源标志 | — |

### 脚本管理

一个"脚本"就是一个自动化程序的接入点。当前三个：

| 名称 | 类型 | 路径 | 备注 |
|---|---|---|---|
| MAA | `MaaConfig` | `D:\ark\maa` | 明日方舟，走模拟器 |
| MaaEnd | `MaaEndConfig` | `D:\ark\maaend` | 终末地，端游 `Win32-Front` |
| OK-WW | `OkwwConfig` | `D:\ark\okww`（字段名是 `RootPath`） | 鸣潮，端游 |

每个脚本下面挂**用户**（`/api/scripts/user/*`）：账号、启用状态、任务开关、
理智/关卡怎么配。当前各一个：`arknights` / `endfield` / `wuwa`。

**注意字段名不统一**：MAA 和 MaaEnd 用 `Info.Path`，OK-WW 用 `Info.RootPath`。

**`Script` 和 `IfUseMasConfig` 显示为 `null` 是正常的。** 这两个字段属于
`GeneralUserConfig`（"通用脚本"类型），`OkwwConfig` 根本没有它们，响应模型统一
带上所以是 `null`。界面上那个"没有脚本名字 / nodata"就是这个，不是漏配。

### 计划管理

计划表让你按星期几换刷取目标。**它是可选的**：

- MAA 用户的 `Info.StageMode`：`"Fixed"` = 用用户自己的固定关卡；否则填计划 uid。
- MaaEnd 用户的 `Info.SanityMode`：同理。

**当前两个都是 `Fixed`**（MAA 固定 AT-4、理智药 0；MaaEnd 走用户里的理智任务字段），
所以那张「新 MAA 计划表」是个**没人引用的空壳**——全字段 `-`，
`grep` 整个 config 目录只在它自己的定义文件里出现。删不删都不影响运行。

### 模拟器管理

当前一个：雷电 `D:\LD-MRFZ\LDPlayer9\ldconsole.exe`，`MaxWaitTime` 300，
`ForceKillOnClose` false。MAA 引用它，多开序号 `1000`。
MaaEnd 和 OK-WW 是端游，`EmulatorId` 都是 `-`，**这是对的，不是漏配**。

### 调度队列

一条队列由两组东西构成，各有独立端点：

- **队列项** `/api/queue/item/*` —— 有序的脚本列表，字段只有 `Info.ScriptId`
- **定时项** `/api/queue/time/*` —— `Enabled` + `Days`（星期数组）+ `Time`

队列自身 `Info` 有 `Name` / `TimeEnabled` / `StartUpEnabled` / `AfterAccomplish`。

当前两条见 [CONFIG.md](CONFIG.md)。两条都是 `AfterAccomplish=NoAction`——
**关机归中继管，不归 AUTO-MAS**。

### 调度中心

运行时面板，没有要配的东西。`/api/dispatch/start` 手动起一个任务，
`/api/dispatch/stop` 中止，`/api/dispatch/get|set/power` 读写电源标志
（当前 `NoAction`，与队列一致）。

---

## OK-WW（鸣潮）能做什么

OK-WW 是 ok-script 系，任务清单可以直接从
`D:\ark\okww\data\apps\ok-ww\working\configs\*.json` 的文件名读出来，
每个任务类在 `src/task/*.py`。

| 任务 | 类 | 说明 |
|---|---|---|
| 📅 日常 | `DailyTask` | 体力打无音区/凝素领域/模拟领域三选一，可带附加任务 |
| 👥 多账号日常 | `MultiAccountDailyTask` | |
| 🌊 无音区 | `TacetTask` | 按 F2 列表序号 |
| ⚒️ 凝素领域 | `ForgeryTask` | 按 F2 列表序号，`structure=[5,5,5,5]` 共 20 个，**每次 40 体力** |
| 🧪 模拟领域 | `SimulationTask` | 按材料选：共鸣者经验 / 武器经验 / 贝币，**每次 40 体力** |
| 🌙 梦魇巢穴 | `NightmareNestTask` | 跑图清「梦魇净化」「无音区巢穴」，**没有体力常量，不吃波片，只吃时间** |
| 🎡 周常乐园 | `GardenTask` | |
| 🌀 声骸刷取 | `FarmEchoTask` | **周本就在这里**，见下 |
| 其余 | | 自动战斗、五合一、批量强化/改主属性、星轨刷图、自动登录、跳过对话、防鼠标漂移、诊断 |

### 周本：**做不了**，别浪费时间配

2026-08-25 读 `FarmEchoTask.py` 源码确认：**它只捡声骸，不领 boss 的材料奖励。**
唯一处理收获的是 `pick_echo()` / `yolo_find_echo()`，**没有任何消耗波片吸收、
点击领取奖励的逻辑**；也**不检查每周三次的限制**（`total_weekly_number = 9`
只用于 UI 选项校验，`Repeat Farm Count: 10000` 就是个重复次数，不会自动停）。

所以周本材料（如「万囮牢·朽躯」）**只能手动打和领**。

（教训：我一度看到 `Teleport to Boss = Weekly Challenge` 就说"有周本功能"，
只验证了它能传送过去，没验证到了之后干什么。用户当场指出。）

### 周本传送本身是有的（但如上，只捡声骸）

`FarmEchoTask` 的 `Teleport to Boss` 有三档：`No` / **`Weekly Challenge`** / `Boss Challenge`。

- 选 `Weekly Challenge` 时的子项：`Which Weekly Boss to Teleport`（1 起，F2 列表从上往下，
  共 9 个）、`Boss Level`（50/60/70/80/90）
- 选 `Boss Challenge` 时：`Which Boss Challenge to Teleport`（共 20 个）、`Boss Level`

**但它接不进 AUTO-MAS 的队列。** 两道限制：

1. `OkwwTaskIndexValidator` 只允许 `TaskIndex ∈ {1, 7}`，即 AUTO-MAS 只能启动
   **日常**或**多账号日常**，起不了别的任务。
2. `FarmEchoTask` 没有 `support_schedule_task = True`，OK-WW 自带的调度器也排不了它
   （`DailyTask`/`TacetTask`/`ForgeryTask`/`NightmareNestTask` 都有，它没有）。

**可行的路子**：直接命令行跑，这条已经验证过——
`python.exe -m ok run_task <任务名> -e`（见 HEADLESS.md）。要定期跑就挂到中继上。

### 没有"库存保持"功能

OK-WW 只有**次数**概念，没有"刷到库存够 N 就停"：

- `FarmEchoTask` 的 `Repeat Farm Count`（默认 10000）是重复次数
- AUTO-MAS 侧的 `ProxyTimesLimit`（每日代理次数）、`RunTimesLimit`（重试）、
  `RunTimeLimit`（单次超时）也都是次数/时间，不是库存目标

要按库存决定刷不刷，只能在外面自己判断。**终末地那边有库存数据**
（IMS，见 HEADLESS.md），鸣潮这边没有等价物。

### 也没有材料图鉴

`ForgeryTask` 只认 **F2 列表里的序号**，不认材料名，更没有"某某武器要什么材料"的表。
想刷特定武器突破材料，得自己知道那个凝素领域在 F2 列表里排第几，把序号填进去。

---

## 母本与副本（这是最容易搞错的地方）

AUTO-MAS 为每个脚本存一份**自己的配置母本**，每次跑之前用母本覆盖程序自己的副本。
**改程序目录里那份是白改的。**

OK-WW 这边由用户配置的 `Info.IfQuickConfig`（当前 `true`）控制，
AUTO-MAS 接管的范围是 `DailyTask` / `MultiAccountDailyTask` 的高频字段。

| 字段 | AUTO-MAS 母本（`wuwa` 用户 `Task`） | OK-WW 副本（`configs/DailyTask.json`） |
|---|---|---|
| 体力用途 | `WhichToFarm` = Tacet Suppression | `Which to Farm` = Tacet Suppression |
| 无音区序号 | 1 | 1 |
| 凝素领域序号 | 1 | 1 |
| 模拟领域材料 | Shell Credit | Shell Credit |
| 日常声骸走梦魇巢穴 | true | true |
| **附加任务** | **`["Check Weekly Garden"]`** | **`["Check Weekly Garden", "Auto Farm all Nightmare Nest"]`** |
| 跑完退出 | 母本不管 | `Exit After Task` = true |

**只有附加任务一处不同。** 附加任务总共就两个可选值
（`CHECK_WEEKLY_GARDEN`、`AUTO_FARM_NIGHTMARE_NEST`），所以副本比母本多的就是「全梦魇巢穴」。
因为母本覆盖副本，**实际生效的是只有周常乐园**。

`Info.Mode` 有三档：`脚本`（用脚本级配置）/ `用户`（用用户级）/ `直控`
（直接用 OK-WW 自己的配置，不覆盖）。当前 `wuwa` 是 `脚本`。

---

## 游戏由谁启动

| 脚本 | 谁拉起游戏 | 依据 |
|---|---|---|
| MAA | AUTO-MAS 起模拟器 | `Emulator.Id` |
| MaaEnd | AUTO-MAS 起端游 | `Game.Path` 指向 `Endfield.exe` |
| OK-WW | **OK-WW 自己** | MAS 侧 `Game.Enabled=false`；OK-WW 侧 `Basic Options.json` 的 `Auto Start Game When App Starts=true` |

OK-WW 的游戏客户端路径在它自己的 `configs/devices.json`：
`pc_full_path = D:\Wuthering Waves Game\Client\Binaries\Win64\Client-Win64-Shipping.exe`。

所以 OK-WW 那条 `Game.Enabled=false` **是对的，别去打开它**——打开了会变成两边都想启动游戏。

## 母本 vs 脚本自己那份：你在 MaaEnd 界面上的改动会被冲掉

2026-08-28：用户说「我记得手动在 MaaEnd 上加过自动采集」，而我报的任务表里没有。
两份一比就清楚了：

    D:\ark\maaend\config\mxu-MaaEnd.json          08-28 10:41  AUTO-MAS 实例 15 个（有 AutoCollect）
    <automas>\data\<sid>\Default\ConfigFile\...   08-21 12:39  AUTO-MAS 实例 14 个（没有）

`AutoProxy.py:514-515` 每轮跑之前 `shutil.rmtree` 掉 `<maaend>\config` 再
`copytree` 母本过去。**在 MaaEnd 界面里加的任务，下一轮就没了。**
和 OK-WW 是同一个套路，见 [[maa-config-master-copy]]。

要让改动长期生效，必须写进**母本**。已把 live 的任务表同步进母本
（AutoCollect 因此保住），并加了 `AutoEssence`、停用 `ProtocolSpace`。

### MAS 那六个「摆设开关」的正解

`IfAutoCollect` / `IfTrialOfSwordmancy` / `IfAutoEcoFarm` / `IfSeizeEntrustTask` /
`IfResourceRecycleStation` / `IfPullCountCalculator`——**MaaEnd 确实有这六个功能**，
不是 MAS 凭空造的开关。它们成为摆设，是因为**母本的任务表里没有这些任务**：
MAS 只能开关已存在的任务，不会新建。要用就先把任务加进母本。

## OK-WW 的 `-t` 与「周常」

`AutoProxy.py:257-258`：`okww_args = ["-t", str(TaskIndex), "-e"]`。
`-t` 是 OK-WW `onetime_tasks` 的下标（1 起算），`-e` 是跑完自行退出。

    1 DailyTask   2 FarmEchoTask  3 NightmareNestTask  4 TacetTask   5 ForgeryTask
    6 SimulationTask  7 MultiAccountDailyTask  8 MergeEchoTask
    9 EnhanceEchoTask  10 ChangeEchoTask  11 GardenTask

**TaskIndex = 1 → 只跑 DailyTask（每日一条龙）。每周乐园是第 11 个独立任务**，
只能通过 DailyTask 的「附加任务」带起来。

**没有「记忆周常已完成」这种功能。** 有的是 `Check Weekly Garden`：
原文「领完每日奖励后检查每周乐园进度，不足 6000 分就跑乐园任务」——
**每次去查进度**，不是记住结果。它在「附加任务」里；2026-08-28 之前
MAS 的快速配置把附加任务覆盖成 `[]`，**所以每周乐园一直没跑过**。
现在已加回 `["Check Weekly Garden"]`。

另两个附加任务没加（很花时间，要用自己开）：
`Merge Echo If discarded > 1000`、`Teleport and Farm 4C Echo`。

### DailyTask 里两个键容易念混

* `Which to Farm = "Forgery Challenge"` → **凝素领域**（`.po`：「凝素領域」）
* `Which Forgery Challenge to Farm = 1` → 「**F2 列表中的第几个**凝素领域」
* `Material Selection = "Shell Credit"` → 原文是
  「Resonator EXP / Weapon EXP / Shell Credit」，是**模拟领域**那个任务的材料选择，
  和凝素领域无关。**别把这两个并成一句念。**

## 关快速配置 ≠ 不再覆盖配置目录

2026-08-28 用户问：「我不是已经关了快速配置吗，不是说不会覆盖吗？」——
是我前面把两件事说混了。它们是分开的：

| | 受什么控制 | 现在的状态 |
|---|---|---|
| **整个 config 目录被替换**（`rmtree` + `copytree`） | **无条件**，`AutoProxy.py:514-515` 没有任何 `if` | **每轮都做** |
| **替换之后再往里覆盖字段**（`If*` 开关 / 理智任务 / 地点） | `Info.IfQuickConfig` | 已关，不再覆盖 |

`Info.Mode` 只决定从**哪个**母本目录拷（`简洁` → `Default`，否则 → 用户 UUID），
不决定拷不拷（`AutoProxy.py:499-507`）。

**所以：在 MaaEnd / OK-WW 界面里改的东西，不管快速配置开不开，下一轮都会被冲掉。**
唯一长期生效的地方是母本 `<automas>\data\<scriptId>\<Default|uuid>\ConfigFile\`。

## MAA 的 `StageMode`

`Info.StageMode` 是关卡配置模式，只有两种取值：

* **`"Fixed"`（固定）** —— 关卡和药量全部直接取 `Info.*`，见
  `AutoProxy.py:727-731`。参与的键是 `MAA_STAGE_KEY`（`constants.py`）：
  `MedicineNumb / SeriesNumb / Stage / Stage_1 / Stage_2 / Stage_3 / Stage_Remain`。
* **一个计划表的 UUID** —— 走 `PlanConfig.json`，按星期几取不同关卡和药量
  （`AutoProxy.py:733-739`）。`AutoProxy.py:421` 也用它判断是否走计划表分支。

当前是 `Fixed`：`Stage=AT-4`、`MedicineNumb=999`、`SeriesNumb=0`。
**计划表里那份（所有天 `Stage='-' MedicineNumb=0`）根本不读。**

## 战后自动筛选与手动 EssenceFilter 的规则已对齐

用户要求两者一致、都只锁无瑕。已把 `AutoEssence` 的战后筛选打开并逐项对齐
`maaend_essence.py` 的默认值，写完当场回读比对，9 项全部一致：

    input_language CN｜rarity6 ✓ rarity5 ✗ rarity4 ✗
    flawless ✓ pure ✗｜keep_future_promising ✗ keep_slot3 ✗ discard_unmatched ✗

注意子选项名和手动那套**不同前缀**：战后的全部是
`EssenceFilterAfterBattle*`（如 `EssenceFilterAfterBattleFlawlessEssence`），
手动那套是 `FlawlessEssence`。改一边不会自动同步另一边。
