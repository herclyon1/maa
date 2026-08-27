# 鸣潮日常：从开机到结束，每一步是什么

**这份文档的每一行都是 2026-08-27 08:20 从机器上原样读出来的**，不是从
上游 README 抄的，也不是回忆。配置项名字就是 `working/configs/*.json`
里的键名，源码行号就是机器上那份（含我们四个补丁）的行号。

改了配置就回来更新这里，否则下次又要从头查一遍。

## 0. 谁在什么时候拉起它

| 时刻（北京） | 谁 | 干什么 |
|---|---|---|
| 08:45 | 智能插座通电 | 主机上电开机 |
| 开机后 | `ark-relay` 服务 | 预更新：依次拉起 MAA / MaaEnd / AUTO-MAS / OK-WW 检查更新，更新完把我们的四个补丁重新贴回去 |
| 09:00 | AUTO-MAS 队列「新队列」 | 1. MAA → 2. MaaEnd → **3. OK-WW** |
| 21:30 | AUTO-MAS 队列「Evening-MAA」 | 只有 MAA |

OK-WW 在 AUTO-MAS 里的条目：`RootPath=D:\ark\okww`、`Game.WaitTime=60`、
`RunTimesLimit=3`（失败最多重来 3 次）、`RunTimeLimit=120` 分钟。
**晚班没有鸣潮**，鸣潮一天只跑早班这一次。

## 1. OK-WW 起来之后

`Basic Options` 里：

* `Auto Start Game When App Starts = true` —— OK-WW 一启动就自己开游戏
* `Kill Launcher After Start = true` —— 进游戏后杀掉启动器
* `Auto Resize Game Window = true`、`capture = WGC`、`interaction = PostMessage`
* 真正的游戏进程是 `Client-Win64-Shipping.exe`
  （`Wuthering Waves.exe` 只是个壳，别拿它判断游戏死没死）

登录由 `AutoLoginTask` 负责。

> **键位必须是游戏默认**：`Game Hotkey` 现在是
> `Echo=q / Liberation=r / Resonance=e / Tool=t / Jump=space / Dodge=lshift`。
> OK-WW 的 `load_hotkey()` **只把 Echo 和 Liberation 真的写进去**，
> Resonance / Tool 那两行在上游是注释掉的——所以游戏里改过共鸣键，
> 脚本会安静地一无所获。2026-08-26 的「刷不动体力」就是这么来的。

## 2. 日常任务本体（`DailyTask.run`，机器上第 77–139 行）

```
78   validate_additional_tasks()      # 附加任务的前置条件先检查
80   WWOneTimeTask.run(self)          # 通用开场
82   ensure_main(180)                 # 确保站在主界面

88   used_stamina, daily_reward_ready = open_daily()
89   need_stamina   = 没领日常奖励 且 已用体力 < 180
90   need_nightmare = 没领日常奖励 且 Which to Farm ≠ 声之领域

96   ── 梦魇巢穴（拿每日声骸）
117  ── 刷体力
133  run_additional_tasks()           # ← 我们的补丁：提到领奖之前
135  claim_daily()                    # 领日常活跃奖励
136  claim_mail()                     # 领邮件
138  claim_battle_pass()              # 领通行证
139  「Daily Task Completed」并通知
```

### 2.1 梦魇巢穴这一段（第 96–115 行）

当前配置 `Farm Nightmare Nest for Daily Echo = true`、
`Which to Farm = Forgery Challenge`（≠ 声之领域），所以这段**会跑**，
走的是 `run_capture_mode()`（第 90–103 行），不是全量的 `run()`：

```
while nest := _next_nest_with_progress():
    combat_nest(nest)
    if _capture_success:      # 掉出一个声骸就走人
        break
```

* `NightmareNestTask` 的配置是
  `Which to Farm = ["Tacet Discord Nest"]`、**`Only Farm These Nests = "落渊南丘"`**
* `find_nest()` 只挑**没打满**的巢穴（`numerator != denominator`），
  `_wanted_nest_rows()` 再把范围收到「落渊南丘」这一个点位。
* **所以：南丘没满 → 进去打；南丘满了 → `get_nest_to_go()` 返回空 →
  while 一次都不进 → 整段跳过。** 这正是要的行为。
* 目的是拿**一个**每日声骸凑活跃度，不是把南丘刷满。
* 打完计数没涨就永久跳过这个点位（`_next_nest_with_progress`，我们的补丁），
  不会像上游那样每两分钟原地重进、无限循环。
* 这一段外面套了 try/except：巢穴炸了也不会带走后面的领奖（我们的补丁）。

### 2.2 刷体力这一段（第 117–128 行）

`Which to Farm = "Forgery Challenge"` → 走 `ForgeryTask.farm_forgery()`，
`Which Forgery Challenge to Farm = 1` → **凝素领域·陨翼云渊（迅刀）**。
刷到 180 体力为止。

### 2.3 附加任务（第 133 行）

`Additional Tasks to Run After Daily Task = ["Check Weekly Garden"]`
—— 只有周常乐园。`Monthly Card Config` 另外管：
`Check Monthly Card = true`、`Monthly Card Time = 4`（每天 4 点后领月卡）。

## 3. 结束

`DailyTask` 的 `Exit After Task = true` → 任务完了退出游戏；
`Basic Options` 的 `Exit App when Game Exits = true` → 游戏退了 OK-WW 也退。
AUTO-MAS 看到进程结束，这个队列条目就算完。

## 4. 我们在上游之上加了什么

四个补丁，每次 OK-WW 自动更新后由 `ark_relay/okww_patch.py` 重新贴回去
（上游更新会整段覆盖 `src`）。细节见 [OKWW-PATCHES.md](OKWW-PATCHES.md)。

1. **领奖顺序** —— 附加任务提到 `claim_daily` 之前，否则周常乐园打完的奖励永远领不到
2. **副本失败不拖垮每日任务** —— `DomainTask` 的异常不再一路穿到 `DailyTask.run`
3. **巢穴任务**（整文件替换，带哈希护栏）—— 续刷 / 不空转 / **可指定点位**
4. **主C饿死兜底** —— `BaseCombatTask`

上游 v3.6.6 里**这四个补丁一个都没有**（v3.6.6 相对 beta.1 只改了
`pyproject.toml` 和 `requirements.txt`），所以还得靠我们自己贴。
