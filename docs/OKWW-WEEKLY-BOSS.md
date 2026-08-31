# 鸣潮周本(战歌重奏)

2026-08-31 做的。本文记录机制、已知缺陷和证据,避免重复排查。

## 怎么跑起来的

周本不是独立任务,它是 `FarmEchoTask`(刷 4C 声骸)的一个模式:

* `FarmEchoTask.json` 里 `Teleport to Boss = "Weekly Challenge"`(译名**战歌重奏**)
* `Which Weekly Boss to Teleport` 是**位置序号**,不是名字。OK-WW 只知道
  「周本一共 9 个」(`total_weekly_number = 9`),不知道任何一个叫什么。
  顺序是游戏 F2 列表的顺序,新 Boss 上线会变。
* `Repeat Farm Count` = 打几轮。**周本一周只能领 3 次奖励**,填 3 就够;
  填多了第 4 轮开不了本,`gray_start_battle` 找不到会抛异常退出任务。
* 挂进 `DailyTask.json` 的 `Additional Tasks to Run After Daily Task`,
  值是 `Teleport and Farm 4C Echo`(译名**传送并刷取4C声骸**)。

AUTO-MAS 那条路走不通:`OkwwTaskIndexValidator` 只允许 `[1, 7]`
(日常 / 多账号日常),指不到 `FarmEchoTask`。所以只能挂附加任务。

单独跑一次:`/api/dispatch/start` 传 `{"taskId": <OK-WW 脚本 id>,
"mode": "AutoProxy"}`。**mode 只接受 `AutoProxy` / `ScriptConfig` / `Update`**
(见 `app/models/schema.py` 的 `TaskCreateIn`),传别的一律 422。

## 顺序补丁:周本要排在刷体力之前

`DailyTask.run()` 上游顺序是「残象聚落 → 刷体力 → 领奖 → 附加任务」,
而刷体力那步 `must_use = 180 - used_stamina` 会先把 180 吃光,
排在后面的周本只剩 60,三个宝箱只开得到一个。

`okww_patch.py` 的 `_STAMINA` 补丁把 `run_additional_tasks()` 提到刷体力之前,
并把刷取改成不传 `daily`(→ `must_use = 0` → 刷到体力不够进本为止),
这样周本花掉的 180 之外剩下的也不闲置。

两件事一件不能少:打完 Boss 人不在主界面,要先 `ensure_main`;
不重读体力的话 `used_stamina` 还是打 Boss 之前的值,日常会再刷 180。

## 奖励怎么给的（2026-08-31 拍到画面才搞清）

**周本没有「打完开宝箱」这一步。** 奖励是**进本时扣 60 结晶波片**直接给的。

波片不够时，游戏在「开启挑战」之前弹：

> 提示 —— 结晶波片不足，无法获取奖励，请确认是否继续进入？ [取消] [确认]

这个弹窗**挡住了「开启挑战」按钮**，于是
`click_team_challenge()` → `wait_click_feature('team_start_challenge',
raise_if_not_found=True)` 超时抛 `WaitFailedException`，
`run()` 的兜底又递归重来 —— 2026-08-31 12:35→12:47 空转 21 圈就是这么来的。
而选「确认」是**不拿奖励地进去**，所以有一趟三轮打完体力 56→56 一动没动，
纯白打。

本地补丁「波片不足时跳过周本」：检测到该弹窗就点「取消」，
抛 `TaskDisabledException` —— `run()` 对它的处理是 `pass`，
FarmEchoTask 静默结束、日常继续往下跑，不会像抛普通异常那样把整个日常带崩。

### 难度等级必须选最高

`Boss Level` 可选 `50/60/70/80/90`。上游的说明是
**"Choose the Lowest that Drop a Echo"** —— 那是**刷声骸**的思路，
能掉声骸的最低级最好打。**周本正相反，等级决定奖励档次，必须选最高的 90。**
母本原来是 80，2026-08-31 用户指出是错的。周本门现在接管这一项并钉在 90。

我们的 `FarmEchoTask` 只被周本用（日常刷声骸走 `NightmareNestTask`
残象聚落），所以不存在两种用途抢同一个配置项的问题。

### 作废的推断

排查过程中我下过两次错结论，都记在这里免得再犯：

1. **「OK-WW 不支持拿周本宝箱」** —— 不成立，压根没有宝箱这回事。
2. **「异常被 `logger.error(msg, e)` 当 printf 参数吞掉了」** —— 也不成立。
   `ok/util/logger.py` 的签名是 `error(self, message, exception=None)`，
   第二个参数本来就是异常，内部走 `exception_to_str(exception)` 打印堆栈。
   **完整堆栈从 12:35 起就躺在日志里**，是我没去读、跑去猜。
   我照标准库的印象加了 `exc_info=True`，那个封装不认，当场 `TypeError`，
   把 16:00 那趟整个搞崩了。教训：第三方 logger 不等于 `logging.Logger`。

## 2026-08-31 早班为什么没打周本

不是门坏了，是**配置落地比队列晚**。母本改动时间：

| 文件 | 写入 | 内容 |
|---|---|---|
| `FarmEchoTask.json` | 08-31 **08:06:23** | 传送=Weekly Challenge、序号 1、打 3 次 |
| `DailyTask.json` | 08-31 **12:52:53** | 附加任务表里才有 `Teleport and Farm 4C Echo` |

早班队列 09:xx→10:14 跑的时候，附加任务表里**还没有**周本那一项，
所以 `FarmEchoTask` 压根没被调起来：早班日志 `boss_string is [Lv` 出现
**0 次**，`GardenTask` 990 行，体力 240→160→80 全花在贝币上。

`WeeklyBossGate.enforce()` 每一拍都在跑，逻辑也对——上机实测它读到的
母本是全的、返回 `False`（本来就不用改）。真正的教训是
**改完配置要确认它在队列开跑之前已经落到母本**，
光看「我改过了」不算数，要看文件时间。

配置路径（`master_config_dir` 解出来的那条，权威源）：

```
D:\ark\automas\data\<uuid>\Default\ConfigFile\DailyTask.json
D:\ark\automas\data\<uuid>\Default\ConfigFile\FarmEchoTask.json
```

`D:\ark\okww\...\working\configs\` 下面那两份是**过期副本**
（08-24 / 08-29），`config-check.py` 的「OK-WW(本体)」读的就是它，
拿它判断当前配置会得出相反结论。2026-08-31 我据此误判过一次。

## 什么时候补

2026-08-31 是**周一**，周本 04:00 刚重置，整周都在。当天体力只剩 26，
而宝箱一个 60——**打 Boss 捡声骸免费且不限次，受限的是宝箱（每周 3 次）**，
所以当天再派发一趟只会白打不开箱。配置现在是对的，
下一趟满体力的队列会自己打满三次，180 开箱 + 剩 60 刷贝币。

## 2026-08-31 16:52 那趟：修好之后的表现

| 项 | 结果 |
|---|---|
| 难度等级 | `left_click 推荐等级90` —— **90 级选中了** |
| Boss 轮次 | 三轮：16:52:56 / 16:54:02 / 16:55:19，每轮都 `farm echo on the face` |
| 空转 | `farm 4c error` **0 次**（此前一趟是 21 圈、12 分钟） |
| 体力 | 跑完读到 27，**确实被消耗了**（此前一趟是 56→56 一点没动） |

**还没证到的**：三次奖励是不是都拿到了。跑之前没有硬读数，只能推算，
不算数。真正的验收是**满波片那趟**（三次共 180），看波片是不是掉 180。

### 两个已经踩过的坑，记在这里

* **`present()` 的判据必须跟着 `new` 一起改。** 我给这条补丁加了调试行，
  判据还是那句没变过的日志，`_apply_one` 判成「已在位」直接返回，
  新版本**一声不吭地没部署**，我却在日志里找那行输出，白等一趟。
* **停 OK-WW 不能只找 `python.exe`。** 它跑在 `pythonw.exe` 里
  （`D:\ark\okww\data\apps\ok-ww\python\pythonw.exe ...\main.py -t 1 -e`），
  而且杀掉之后 AUTO-MAS 会把它再拉起来，`/api/dispatch/stop` 也清不掉
  「任务已在运行」这个状态。`wmic` 在新版 Windows 已经没有了，
  要用 `C:\Program Files\PowerShell\7\pwsh.exe` 的 `Get-CimInstance`。
