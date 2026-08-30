# 08-29 晚班 / 08-30 早班 系统排查

2026-08-30 11:38 做的。**之前只报了三个问题，是因为我只看了监视器推给我的东西，
从来没做过系统排查。实际至少九个。**

排查前先开了调试模式（至 14:00），机器不会中途关机——这是 08-30 早上
「等跑完再查、结果机器已经关了」那次的教训。

## 一、MAA（明日方舟）

| 现象 | 昨晚 | 今早 | 说明 |
|------|------|------|------|
| `VisionHelper::correct_rect roi is empty, use whole image` | 929 | 873 | **识别区域为空，退化成整图搜索** |
| 同上（`roi is empty`，不带 use whole image） | 84 | 168 | 合计今早 1041 条 |
| `InfrastAbstractTask::current_room_config custom is not enabled` | 28 | 28 | **MAA 说自定义基建没启用** |
| `[ERR] skill has no recognition result` | 20 | 21 | 干员技能图标识别不出来 |
| `[ERR] Unknown task: FightSeries-OldMethodFlag` | 7 | **10** | 程序和资源版本对不上，**次数在涨** |
| `InfrastAbstractTask::on_run_fails`（基建整体失败） | **是** | **否** | 间歇性，不是每次 |

### 要点

1. **基建失败是间歇的。** 我 08-30 早上说「配置没动过，今早大概率还这么失败」，
   实际今早没失败。别再拿这个当预测。
2. **`roi is empty` 每轮上千条**，意思是识别时给的区域是空的、只能拿整张图去搜。
   这和「技能识别不出来」「基建失败」很可能同源，但**我没有证据说是同一个根因**。
3. **`custom is not enabled` 每轮 28 条**：MAA 认为自定义基建配置没开。
   如果用户设过基建方案，那方案可能根本没生效。**需要核对配置，没查。**

## 二、OK-WW（鸣潮）今早 18 条 ERROR

| 次数 | 内容 |
|------|------|
| ×4 | `Hiyuki:clicked liberation but no effect`（点了大招没反应） |
| ×4 | `CombatCheck:target_enemy failed, try recheck break out of combat` |
| ×4 | `BaseCombatTask:combat check not in combat` |
| ×2 | `post_message:PostMessage error: (1400, '无效的窗口句柄。')` |
| ×1 | `capture_by_bitblt invalid params: hwnd=0, w=1920, h=1080` |
| ×1 | `start_controller:Game window is not connected BitBlt_True_0x0` |
| ×1 | `waiting for game to start error 鸣潮 is not connected` |
| ×1 | `capture_by_bitblt exception: BitBlt failed` |

后四条是**启动阶段游戏窗口还没连上**（`hwnd=0`），属于开机竞态，之后连上了
（当天 `Daily Task Completed` 有 1 次、`指定点位都已打满` 有 1 次）。
前面那组是战斗里的，**没查**。

## 三、MaaEnd v2.27.0-beta.1 首跑

- 收尾标记「自动执行任务完成」**有**，ERROR 0 条，这一轮是好的。
- **但 `outcome.py` 里「每个任务都收了尾」那道兜底现在匹配不到任何东西。**
  它找的是 `任务开始: X` / `任务完成: X`，而 v2.27 的日志写的是
  `[Task] 实例 AUTO-MAS: 开始执行任务, 数量: 17` 和 `[MAA] 启动任务, 实例: automas, 任务数: 16`。
  代码里有 `if started:` 的守卫，所以不报错——**它只是静默地什么都不做了。**
  没有 08-29 的日志可比对（MaaEnd 更新时会清空 debug 目录），
  所以**我不知道这道兜底是从这一版才失效的，还是一直就没生效过。**

## 四、中继

| 现象 | 次数 | 状态 |
|------|------|------|
| `进程启动事件监听退出，改用 120 秒活性检查` | 2 | **已修**（加了退避重订阅） |
| `模型不可用，日报回退到结构化排版` | 2 | 没查 |
| `取不到待办文件` | 3 | **已修日志**（单门失败不再报警；实际取到了） |
| `取不到 manifest` / `拿到的清单更旧` | 2 / 4 | update 那边的日志还是老样子，没改 |

## 五、我自己在排查中犯的错，一并记下

- 我第一版脚本把 MaaEnd `debug/record/` 目录里的条目数报成「出错截图 5 张」。
  实际那 5 个是 `IMS.json`、`ElasticGoodsPrices.json`、
  `CreditShoppingShelfSnapshots.json` 等**数据缓存**，不是截图。
  按目录条目数当证据是错的。

## 补：OK-WW 战斗那组报错是常态，不是故障

2026-08-30 按天统计（`ok-script.log`）：

| 报错 | 08-27 | 08-28 | 08-29 | 08-30 |
|------|-------|-------|-------|-------|
| `Hiyuki:clicked liberation but no effect` | 3 | 3 | 6 | 4 |
| `CombatCheck:target_enemy failed` | 7 | 5 | 5 | 4 |
| `BaseCombatTask:combat check not in combat` | 4 | 6 | 4 | 4 |
| **✓ 日常完成 / 指定点位都已打满** | ✓ | ✓ | ✓ | ✓ |

**天天报、天天完成。** 这三条是 OK-WW 战斗内的重试信号，
它用 ERROR 级别打重试日志而已。不是我们的故障，不用管、不用提 issue。

### 但 08-26 那天有真崩溃，之后没再出现

```
DailyTask.run → ForgeryTask.farm_forgery → DomainTask.farm_in_domain
  → BaseWWTask.walk_to_treasure → walk_to_box          （走向宝箱时崩）

DailyTask.run → claim_battle_pass → BaseWWTask.ensure_main
  → Exception: Please start in game world and in team!  （不在世界/队伍状态）
```

08-26 共 5 次，**08-27 到 08-30 一次都没有**。

那天正好是我们发现游戏内键位被改过、改回默认，以及给 `ensure_main` 打补丁的日子
（见 [[wuwa-keybinds-must-be-default]]、[[okww-nest-ensure-main-patch]]）。
**时间吻合，但没有证据说是哪一个修好的**，也可能两个都有份。
记在这里是为了：万一以后又冒出来，先查键位和 ensure_main，别从头猜。

## 日报走模板是常态，不是故障

`模型不可用，日报回退到结构化排版` 这条 WARNING 天天出现，读起来像坏了。
用户 2026-08-30 说明：**模型写日报是废除的规划（太贵），结构化模板就是最终形态、
目前够用。** 所以那是常态路径，已降为 INFO 并写明。
