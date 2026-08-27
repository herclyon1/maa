# 自动过剧情 / 打活动 —— 调研结论（2026-08-26）

**结论：用户要的「全自动」（自动寻路 → 开地图传送 → 触发 NPC 对话 → 跳过）不存在。
鸣潮和终末地的全部项目都是「你把剧情触发出来，它帮你点完」。别再重复调研。**

| 项目 | 游戏 | 后台 | 自动选分支 | 寻路/传送 |
|---|---|---|---|---|
| **MaaEnd** `RealTimeTask` | 终末地 | 实时辅助性质 | ✅ `AutoSkipChoose` | ❌ `QuickTeleport` 是**用户从列表选目的地** |
| [WWA](https://github.com/wakening/WutheringWavesAssistant) `AutoStoryService` | 鸣潮 | ❌ **必须前台** | ✅ | ❌ |
| [better-wuthering-waves](https://github.com/babalae/better-wuthering-waves) | 鸣潮 | ✅ 后台 | ⚠️ 只会选最后一项 | ❌ |
| **OK-WW** `SkipDialogTask` | 鸣潮 | ✅ 后台 | ❌ | ❌ |

## 源码证据（不要信 README 的宣传语）

- **WWA** `src/service/auto_story_service.py`：`npc_interact_action` 全文三行——
  `sleep(0.5)` → `pick_up()` → return，触发条件是屏幕上**已出现** `NpcInteract.png` 交互框。
  `execute()` 第一行就是 `if not is_foreground_window(): ... return`，**不在前台不干活**。
  `explore_workflow.py` 同理，只有 `_skip`/`_play`/`_dialogue`/`_pickup`，无路线/寻路/地图节点。
- **better-wuthering-waves**（★155，C#，babalae 团队）README 功能只有一行：
  「快速点击F过剧情，可以后台过。可以自动点击跳过按钮。默认选择最后一项选项」。
  作者自述「项目随时会弃坑」。
- **MaaEnd `RealTimeTask`** 节点：`AutoFight` / `AutoPick` / `AutoZipline` / `AutoPuzzleSolving` /
  `SklandMap`（森空岛地图叠加）/ `QuickTeleport` —— 典型「你玩它帮你点」。

## MaaEnd 的自动剧情开关（已装未用）

挂在 **`RealTimeTask`** 下（`RealtimeAssist` 是精简预设）：

| 开关 | 作用 |
|---|---|
| `AutoSkip` | 自动剧情（总开关） |
| `AutoSkipAll` | 跳过所有剧情，自动点跳过按钮 |
| `AutoSkipChoose` | **自动选择剧情分支** |
| `AutoSkipNext` | 加速剧情播放（不断点屏幕） |
| `EnableCloseSpecialPanel` | 自动关剧情文档 / 语音记录界面 |

**`RealTimeTask` 是 AUTO-MAS 没接出来的 27 个任务之一**，MAS 界面里看不到，
要走 MaaEnd 自己的界面（MXU `127.0.0.1:12701`）或 API。见 [HEADLESS.md](HEADLESS.md)。

## 为什么没人做全自动

寻路要机器理解任务状态 + 地图 + 导航，比「看见按钮就点」难一个数量级。
做得最深的原神那套（[BetterGI](https://github.com/babalae/better-genshin-impact)）
也只有**用户自己录好的路线回放**，没有自主找任务点。

## 顺带记下的相关项目

- [`zzc-tongji/ok-ww-enhanced`](https://github.com/zzc-tongji/ok-ww-enhanced) ★24 ——
  OK-WW 增强版，加了 `-t/--task`、`-e/--exit` 命令行（跑完自动退出），**对无人值守调度有用**。无剧情/活动。
- [`ok-oldking/ok-end-field`](https://github.com/ok-oldking/ok-end-field) ★7 ——
  OK-WW 同作者的终末地版，有「自动跳过剧情」，但 MaaEnd（★3708）成熟得多，没必要换。
- WWA 有 `src/core/activity.py` 活动框架（版本判定/时间窗/可用性）+
  `SoarToTheBeatMacroReplayTask`（律动九霄类小游戏的宏录制回放）——**活动这块只有它有**。

## 装之前要确认的两件事

1. WWA 占前台，跟后台跑的 OK-WW **不能同时**操作鸣潮，会抢画面。
2. 两个脚本同时操作同一游戏要在调度上错开。
