# OK-WW 卡死排查：模态弹窗 → 全线 `target_enemy failed`

2026-08-26 补跑时 OK-WW 连续四次 `📅 Daily Task exception stopped`
（16:04、16:27、16:29、16:32），此后进程直接不在了。这份记录写清楚
**真因是什么**、**我在哪几步误判了**，以及**下次怎么一步到位**。

## 症状

```
ERROR CombatCheck: target lost try retarget 10
ERROR CombatCheck: target_enemy failed, try recheck break out of combat
Exception: can't find gray_book_boss, make sure f2 is the hotkey for book
```

统计：开残象书 16 次 / 进入战斗 9 次 / **战斗成功结束 0 次** / 计数一直 0/41。
体力刷取（ForgeryTask）被完全挡住：领日常奖励 0 行、日常完成 0 行。

## 真因

游戏被一个**「选择复苏物品」模态弹窗**挡住了，而且挡了至少 20 分钟。

OK-WW 不认识这个弹窗，它的 `click_skip_dialog_confirm` 试过、超时了。
弹窗一直在，于是每一次特征识别都落在同一张被遮挡的画面上：
锁不到敌人 → `target_enemy failed` → 上游 `CombatCheck` 直接
`break out of combat` → `DomainTask.farm_in_domain` 顺着往下走到
`walk_to_treasure()` 去捡宝箱 → 副本里一个敌人都没杀，当然没有宝箱 →
`WaitFailedException` → 整个 Daily Task 异常退出。

完整调用链（`ok-script.log` 16:32:15）：

```
DailyTask.run → ForgeryTask.farm_forgery → DomainTask.farm_domain_with_recovery_loop
  → DomainTask.farm_in_domain → BaseWWTask.walk_to_treasure
  → walk_to_box → do_walk_to_box → wait_until → WaitFailedException
```

**处置**：对游戏窗口发一个 `{ESC}` 把弹窗关掉。不点「确认」——
那会消耗一个复苏物品（当时库存 9 + 4）。ESC 之后画面立刻正常：
角色满血 17267/17267、Lv.90，正站在凝素领域里，倒计时在走，限时击败敌人 0/5。
重新触发 OK-WW 后，`target_enemy failed` **归零**，
`switch_next_char Chisa(Healer) ↔ Lucilla(SubDps)` 连招轮换正常跑起来。

## 我误判的三步（下次直接跳过）

### 1. 「游戏崩了，进程只剩 3MB 空壳」——错

`Wuthering Waves.exe` 只是外壳，**真正的游戏进程是
`Client-Win64-Shipping.exe`**（当时 331 个线程，活得好好的）。
查游戏死活一律查后者。

### 2. 「游戏机锁屏了」——错，而且是我自己的工具骗了我

我在 ssh 会话里调 `GetCursorPos`，拿到 `err=1459`
（`ERROR_REQUIRES_INTERACTIVE_WINDOWSTATION`），据此推断桌面被切走。

实际上 **ssh 会话本来就没有交互窗口站**，这个错和游戏机状态毫无关系。
同理跨会话拿 `MainWindowHandle` 和 `WorkingSetSize` 也不可信——
那天真实游戏进程的 `MainWindowHandle` 报的是 0。

**凡是要知道「屏幕现在到底什么样」，用 `scripts/mac/wingui.sh shot`**，
它注册一个 `/it`（交互式）计划任务，在 session 1 里真截屏。

### 3. 「看 OK-WW 自己存的截图就知道现在什么样」——错

OK-WW 只在**出错时**存截图，而且当时 16:27:11 和 16:32:15 两张
**一模一样**。看着像「游戏卡死不动」，其实是它对着同一张被弹窗遮挡的画面
反复识别失败。它存的是它看到的，不是现在的。

## 工具

`scripts/mac/wingui.sh`（2026-08-26 因这件事写的）：

```bash
ARK_HOST=100.65.39.119 scripts/mac/wingui.sh shot 现在.png   # 真实屏幕
ARK_HOST=100.65.39.119 scripts/mac/wingui.sh key esc         # 关弹窗
ARK_HOST=100.65.39.119 scripts/mac/wingui.sh key f2          # 开传送目录
```

`key` 一律先 `SetForegroundWindow`：**鸣潮失焦时照常渲染但不收输入**，
不置前台的话按键全部落空，而且没有任何报错。

## 还没解决的

* **上游不认识这个弹窗。** `click_skip_dialog_confirm` 覆盖不到
  「选择复苏物品」。值得给 ok-oldking/ok-wuthering-waves 提一个 issue：
  任意模态弹窗兜底 ESC，而不是只认已知的几个。
* **弹窗当初怎么冒出来的**没有定论。角色满血，不像是阵亡触发；
  更可能是自动战斗过程中误触了物品栏。日志里没有对应记录。
* **凝素领域「第 1 个」到底是哪个副本**，代码里查不到。上游写死了
  `'The Forgery Challenge number in the F2 list.'`，即
  `serial_number - 1` 点游戏内 F2 列表的第几行，顺序由游戏决定。
  只能实拍一次 F2 列表定下来，**而且游戏更新后顺序可能变**，不是一劳永逸。
