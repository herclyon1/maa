# 残象聚落有两种模式，我们一直跑的是「只抓一个声骸」那种

**2026-08-29 查实。不是死选项，是界面上的复选框，我们没勾。**

## 两条分支（`working/src/task/DailyTask.py:85-106`）

```python
condition1 = AUTO_FARM_NIGHTMARE_NEST in additional_tasks   # 'Auto Farm all Nightmare Nest'
condition2 = self.config.get('Farm Nightmare Nest for Daily Echo')

if condition1:    self.run_task_by_class(NightmareNestTask)  # 刷满
elif condition2:  ...run_capture_mode()                      # 抓一个声骸就停
```

我们母本里 `Additional Tasks = []`、`Farm Nightmare Nest for Daily Echo = True`
→ 走 `elif`，**每次只打一轮就收工**。

## 捕获模式为什么「打两只就完成」——两层都在叫停

```python
def run_capture_mode(self):
    ...
    while nest := self._next_nest_with_progress():
        self.combat_nest(nest)
        if self._capture_success:
            break                    # ① 抓到一个声骸 → 整段结束

def _should_continue_combat_after_pickup(self):
    return not self._capture_mode and self.wait_combat(...)
                                     # ② 捕获模式恒为 False → combat_nest 打完一轮就 break
```

开关自己的说明也写着：`'Farm 1 Echo from Nightmare Nest to complete Daily Task when needed.'`
——**「Farm 1 Echo」，它就是设计成只刷一个的**，用来凑日常，不是用来刷满的。

## 08-28 早班实测（`history/2026-08-28/wuwa/OK-WW-09-34-19.log`）

```
13:36:24  已击败残象：0/41 is not complete
13:37:25  farm echo yolo find False
13:37:25  no echo collected, re-teleport to current nest as fallback   ← 重新传送是捡声骸兜底
13:38:19  已击败残象：2/41 is not complete
13:40:06  已击败残象：6/41 is not complete
13:40:47  Captured echo during combat, skipping search.                ← 只有捕获模式才打这行
13:40:48  ForgeryTask 开始                                             ← 6/41 就换任务了
```

**那几次重新传送不是「怪只刷几只」**（我一度这么说过，错的，用户当场纠正），
是 `combat_nest` 里没捡到声骸时的兜底重传。

## 同一个任务有两条入口，行为完全不同

| 入口 | 走哪个方法 | 行为 |
|---|---|---|
| AUTO-MAS 队列（`main.py -t 1`）→ **每日任务** | `DailyTask` → `elif condition2` → `run_capture_mode()` | 抓一个声骸就停 |
| 界面上「噩梦巢穴任务」的开始按钮 / `okww-task.sh <下标>` | `NightmareNestTask.run()` | 刷到打满 |

memory [[okww-nest-truth]] 里「一晚清空四个点位」说的是**第二条**入口，
和队列里跑的不是同一条路。两条都成立，别互相拿来否定。

## ⚠️ 日志里的计数不能当进度证据

`已击败残象：0/41` 里的 `0` **可能是 OCR 吞掉了前导数字**（实际是 10/41）。
2026-08-29 我拿 08-26 日志里一片 `0/41` 断言「从来没有点位被清空过」，
错的——[[okww-nest-truth]] 第一条就明文警告过这一点。
**判断进度看游戏界面，不看日志里那个数。**

## 改法

母本 `<automas>/data/c5e96ddc-…/Default/ConfigFile/DailyTask.json`：

```json
"Additional Tasks to Run After Daily Task": ["Auto Farm all Nightmare Nest"]
```

* **中继不会冲掉它**：`garden.py:enforce()` 读出整个列表后只增删
  `"Check Weekly Garden"` 一个元素，其余原样保留。
* `Only Farm These Nests = '落渊南丘'` 继续生效——刷满模式同样走 `find_nest`，
  死命令[[okww-only-nanqiu]]不受影响。
* `Farm Nightmare Nest for Daily Echo` 留着不用动：`if condition1` 优先，
  `elif` 不会再进。

**代价**：刷满 41 只比抓 1 个声骸慢得多，会挤占早班队列时间。改之前要先算这笔账。

## UI 能不能改？能。三个问题一起答

| 问 | 答 | 依据 |
|---|---|---|
| 界面上真的啥都改不了？ | **能改**，`ADDITIONAL_TASKS` 是 `multi_selection`，四个选项的复选框 | `DailyTask.__init__` 的 `config_type` |
| 我们的补丁在界面上有显示吗？ | **有**，`Only Farm These Nests` 带 `config_description`，ok-script 会渲染成带说明的文本框 | `NightmareNestTask.__init__:59-61` |
| 是不是只是没法用无头 API 调？ | **不是**，配置就是 `configs/*.json` 纯文本，AUTO-MAS 每轮把母本整个拷过去，改母本即可 | `AutoProxy.py:514-515` |

## 那个复选框的标签是误导的（2026-08-29 定论）

界面上叫「**自动刷所有梦魇巢穴**」，但它**不控制刷什么范围**，只控制走哪个方法：

```
勾上  → run_task_by_class(NightmareNestTask) → run()   刷满模式（_capture_mode=False）
不勾  → run_capture_mode()                             抓一个声骸就停
```

（`ok/task/task.py:1111 run_task_by_class` → `task.run()`，已核实。）

范围由**噩梦巢穴任务自己的两个选项**决定，我们早就设好了：

* `Which to Farm = ['Tacet Discord Nest']` —— 只残象聚落，**不碰梦魇拔除**
* `Only Farm These Nests = '落渊南丘'` —— 只那一个点位

所以「只刷完落渊南丘那一个残象聚落」**不用写一行代码**，勾上即可。
打满后 `find_nest` 返回 None → 日志「指定点位都已打满，跳过」→ 收工，
符合死命令 [[okww-only-nanqiu]]。

**已改**（母本 + 实运行两份）：
`"Additional Tasks to Run After Daily Task": ["Auto Farm all Nightmare Nest"]`

## ⚠️ 杀 OK-WW 必须连 pythonw 一起杀

`ok-ww.exe` 只是 pyappify 启动器，真正跑的是
`data\apps\ok-ww\python\pythonw.exe ...\working\main.py`。

2026-08-29 我 `taskkill /IM ok-ww.exe /F` 之后向用户报了「无残留进程」——
**错的**：pythonw 子进程还活着，一直占着命名互斥锁
`ok-script-<hash>`（属主记录在 `%TEMP%\ok-script-<hash>.pid`），
导致后续每次启动都以
`RuntimeError: Another application instance is still running` 退出码 1 结束。

检查残留时**必须把 `pythonw` 也算进去**，并用命令行而不是进程名判断：

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' or Name='python.exe'" |
  ForEach-Object { $_.ProcessId.ToString() + ' :: ' + $_.CommandLine }
```

顺带两条工具坑：
* `wmic` 在这台机器上已经没有了（新版 Windows 移除），用 `Get-CimInstance`。
* pwsh 里 `\"` 不是转义。内联 PowerShell 带引号必须落成 `.ps1` 文件再 `-File` 跑，
  否则命令**静默返回空**——我据此三次得出「没有相关进程」，全是假的。
