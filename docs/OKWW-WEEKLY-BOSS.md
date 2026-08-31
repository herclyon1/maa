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

## 已知缺陷:宝箱领不到

**打 Boss 捡声骸是免费的,开宝箱要花体力,这两件事是分开的。**
2026-08-31 实测:周本打满三轮、三次「farm echo on the face」,
而刷贝币开始时 `current_stamina` 仍是 240——**一个宝箱都没开**。

原因不是配置:这一版 `FarmEchoTask` 一共只读十个配置项——
`Boss`、`Boss Level`、`Change Time to Night`、`Combat Wait Time`、
`Echo Pickup Method`、`Repeat Farm Count`、`Teleport to Boss`、
`Use Liberation`、`Which Boss Challenge to Teleport`、
`Which Weekly Boss to Teleport`——**没有 `Auto Pick Echo Treasure`**。
那个开关的译文躺在六种语言包里,但**上游源码里没有实现**,
而 v3.6.6(2026-08-26)已经是最新正式版,升级解决不了。

打完 Boss 之后走的是「退出秘境」那条路:

```python
self.send_key('esc', after_sleep=0.5)
self.wait_click_feature('claim_cancel_button_hcenter_vcenter', relative_x=2, ...)
```

`relative_x` 按框架文档是「框内相对 X」(默认 0.5 = 点中心),
所以 **`2` 是从取消按钮左边缘往右两个按钮宽度**——本意就是去点右边的
领取按钮,不是取消。日志里实际点在 `(538, 675)`。偏够没偏够,
不看那一刻的画面说不清,所以**不许猜坐标改代码**。

`okww_patch.py` 的 `_SHOT` 补丁在那次点击之前加了一行
`self.screenshot('weekly_claim_dialog')`,**零行为改动**,
图存在 `working/screenshots/weekly_claim_dialog/`。拿到图再动手。

## 踩过的坑

* `_Patch.old` 必须是**完整的语句**。截到半个函数调用(`relative_x=2,`)
  替换后编译不过,`_verify_or_revert` 当场判「回读不对」把补丁还原。
* `present()` 不能拿会在别处出现的字符串当锚点。用过 `if need_stamina:`
  (新版把这分支删了)和 `Which to Farm`(更早的梦魇判定里也有),都判错。
  最后用 `run_additional_tasks` 是否在 `claim_daily` 之前。
* 测试夹具必须是**上游真实的形状**。只留尾巴几行、或者少一个文件,
  补丁就永远「贴不上」,测试表现为「不幂等」。
