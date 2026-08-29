# 选剑演武 08-28 的四次失败，是四个不同的失败点

**不要把它们当成一个问题。**下面每条都有日志行号或截图。

## 任务配置（`mxu-MaaEnd.json` → `instances[0].tasks[14]`，启用=True）

| 中文 | 键 | 我们的取值 |
|---|---|---|
| 模式 | `TrialOfSwordmancyMode` | `Daily`（每日选剑演武） |
| 数据溢出处理 | `TrialOfSwordmancyOverflow` | `None`（不接受溢出） |
| 启用自动战斗 | `TrialOfSwordmancyAutoFight` | 是 |
| 每次战斗前传送回复血量 | `TrialOfSwordmancyRecoverBeforeBattle` | 否 |
| 自动战斗设置 | `AutoFightSetting` | 是 |
| ├ 自动切换低血量干员到后台 | `AutoFightHealthDangerousSwitch` | 是 |
| ├ 自动闪避 | `AutoFightDodge` | 是 |
| │  └ 兼容模式 | `AutoFightDodgeCompat` | 否 |
| ├ 自动锁定目标 | `AutoFightLockTarget` | 是 |
| ├ 使用排轴 | `AutoFightAxis` | 否 |
| ├ 保留技能能量 | `AutoFightReserveSkillLevel` | 1 |
| └ 自动打断敌人蓄力 | `AutoFightBreakAccumulatingPower` | 是 |

其他模式：`Coating`（刷镀层）、`Farm25`（刷25点，无奖励、不自动战斗）。
溢出档位：`None` / `Once`（至多1次）/ `Twice`（至多2次）。
官方说明写着「开启数据溢出可以取得更高的预期收益，但**自动战斗大概率失败**」。

**这 12 项没有配错的。**`AutoFightSetting` 那 7 个子项就是它自己的子树，
同一套也出现在 `tasks[13] ProtocolSpace` 上。

## 四次失败

| # | 时间 | 抽牌 | 战斗 | 失败点 |
|---|---|---|---|---|
| 1 | 14:00:45→14:01:53 | **无** | **无** | 没进牌桌 |
| 2 | 14:05:51→14:08:04 | 有 | 打满 45 秒正常退出 | **战后收尾识别** |
| 3 | 14:17:20→ | 有 | 打满 | 同上 |
| 4 | 21:04（我手动单跑） | 无 | 无 | **没导航到场地** |

### 第一轮：连牌桌都没进

整个任务只有 4 行：

```
14:00:45.289  任务开始: 🗡️选剑演武
14:01:06.992  [ERR] TemplateMatcher __WhiteConfirmButtonType1…
14:01:06.994  [ERR] TemplateMatcher __WhiteConfirmButtonType1…
14:01:53.628  任务失败: 🗡️选剑演武
```

`EnterTrialMenuSuccess = Or(DrawCard, EnemyCard5)` 从未匹配，`EnemyCard5` 得分 0.286（阈值 0.7）。

### 第二轮：打完了，卡在战后收尾

```
14:07:03.959  进入战斗场景
14:07:04.228  共 4 名干员参战     （技能／闪避／连携／终结技全打出来）
14:07:49.411  退出战斗场景
14:07:54.554  获得 武陵调度券 ×320000   ← 这个数不可信，见下
14:08:04.217  任务失败: 🗡️选剑演武
```

框架日志 `maafw.bak.2026.08.28-14.16.02.869.log` 的 14:07:45–14:08:06 窗口里，
它在反复轮询三个收尾节点，全部 `Node.Recognition.Failed`：

```
TrialOfSwordmancyFightSuccess              73×
TrialOfSwordmancyReEnterTrialMenuSuccess  126×
TrialOfSwordmancyRewardExhausted          126×
```

**没有打任何失败原因**——它自己有一条 `trialofswordmancy.recognition_failed
=「选剑演武：识别失败」`，这次没触发。

### 第四轮（21:04 单跑）：人在大世界

`debug/on_error/2026.08.28-21.04.13.353_TrialOfSwordmancyMain.png`：
角色站在源石研究园外的大世界，左上角是「探索」模式和日常任务指引，
**根本没到演武场**。

## ⚠️「获得 武陵调度券 ×N」不能当作拿到奖励的证据

文案来自 `locales/go-service/zh_cn.json`：

```
ims.add_item_found   获得 %s ×%d
ims.item_current     当前 %s：%d
ims.sync_item_found  识别到 %s：%d
```

数字是 OCR 出来的。**所有 `调度券` 的读数都不可信**：

```
08-14  ×2790000  ×3380000  ×835000  ×1970000  ×5030000
08-25  ×49800  ┐ 两天同一个数
08-26  ×49800  ┘
08-28  ×320000（第二轮）  ×320000（第三轮）  ← 两轮同一个数
```

同期其他物品都正常：`行动资历 ×1150`、`协议棱柱 ×5`、`高级作战记录 ×1`。
而且 `nodes.json:14036` 有「识别武陵调度券是否溢出」的阈值判断，
说明它是有上限的存量，一次不可能掉几百万。

**判断「今天打完没有」要用游戏自己的话**：21:04 单跑时它报「今日奖励次数已用尽」。
第一轮没进去，所以次数是第二、三轮吃掉的。

## 已排除的假设

* **配置没配好** —— 12 项逐条核对无误，见上表。
* **难度过高打不过**（卢智超）—— 第一轮和第四轮**根本没有战斗**，不适用；
  第二三轮战斗跑满并正常退出。赢没赢日志里没写，尚不能证实也不能证伪。
* **抽卡失败**（卢智超）—— 第一轮日志里**一条手牌/牌库行都没有**，牌桌都没进。

## 上游 issue 对照（2026-08-28 搜过 MaaEnd/MaaEnd）

我们跑的是 **v2.26.0-rc.1**（`D:\ark\maaend\interface.json` 的 `version`）。

### 寻路类失败（第一轮、21:04 单跑）——**已有 issue，仍未修**

| # | 状态 | 版本 | 标题 |
|---|---|---|---|
| [#5034] | **open** | v2.25.0-beta.2 | 选剑演武-寻路异常：「传送至传送点后朝向错误跳下下一层 导致任务失败」 |
| [#5061] | **open** | v2.25.0-beta.3 | 寻路与作战bug：「选剑演武作战失败报错」 |
| #5021 / #5040 | open | v2.25.x | 多任务寻路失败合并反馈 |
| #4930 / #4987 / #4365 | closed | v2.2x | 选剑演武寻路失败 / 偶发性寻路失败 |

#5034 的描述和我们 21:04 的 `on_error` 截图吻合：**人停在大世界，没到演武场**。
两个 open issue 都是 v2.25.x 提的，我们 v2.26.0-rc.1 仍然中招——**这一类会复现。**

### 战后收尾识别失败（第二、三轮）——**没搜到对应 issue**

关键词 `选剑演武` / `TrialOfSwordmancy` / `选剑演武 识别` 全搜过，
08-20 之后没有任何 选剑演武 故障 issue。已关闭的识别类
（#3968、#4418、#4432「选剑演武：识别失败」）症状不同——
**它们会打出那条 `选剑演武：识别失败`，我们这次一个字都没打。**

所以「战斗打完、`FightSuccess` / `ReEnterTrialMenuSuccess` / `RewardExhausted`
三个节点轮询 100+ 次全 `Recognition.Failed`、无任何失败文案」这个形态，
目前**没有现成 issue**。

**但只有一天数据，且跑的是 rc 版**，先再观察一天再决定要不要报。
