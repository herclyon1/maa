# Configuration inventory

Every setting that was deliberately changed, plus the traps around it. When a
value here disagrees with the machine, the machine is right and this page is a
bug - fix it, or run `scripts/mac/check-docs.py` which will say so first.

Values below verified 2026-08-21.

## Audited against AUTO-MAS's own documentation, 2026-08-22

Every setting below was read off the live machine and checked against
[doc.auto-mas.top](https://doc.auto-mas.top) (`docs/user-guide`,
`docs/task-scheduler`, `docs/script-guide/maa`). The config had only ever been
edited through JSON before this, so the point was to find out what that missed.

### Matches the documentation

| Item | Machine | Doc says |
|---|---|---|
| MAA's own 定时执行 | 8 timers, **all disabled** | "定时执行保持关闭" |
| `Default` profile `PostActions` | `ExitArknights, ExitSelf` | after-run behaviour is AUTO-MAS's to set |
| Queue chaining | 新队列 09:00 -> MAA then MaaEnd; Evening-MAA 21:30 -> MAA | queues run scripts in series |
| `AfterAccomplish` | `NoAction` on both | the relay owns the power-off |
| Account ID / password / Skland token | **all empty** | "若同区服仅有一个账号，也可将账号ID留空" - and an empty ID is what stops MAA attempting an account switch |
| MaaEnd control | `EmulatorId`/`EmulatorIndex` = `-`, i.e. PC | "支持 PC 与模拟器控制（推荐 PC）" |
| Emulator entry | `ldplayer` + `ldconsole.exe`, index 1000 | pick the emulator and instance in 模拟器管理 |
| Notifications | 推送任务结果时机 = 不推送, 系统通知 = 否, 邮件 = 否 | - |

`Function/IfAllowSleep = False` shows in the UI as **运行时阻止系统休眠 = 否**,
which sounds wrong for an unattended machine and is not: `powercfg` reports
`STANDBYIDLE` on AC = `0x0`, so Windows never sleeps on its own anyway.

### Loaded guns - correct today, harmful the moment something else changes

| Finding | Why it matters |
|---|---|
| The MAA user still has `Notify/IfServerChan = true` **with a ServerChan key saved**, under a master `Notify/Enabled = false` | One toggle away from AUTO-MAS pushing on its own. NOTIFICATIONS.md says the relay is the only notifier; the key should be cleared, not merely switched off |
| `Timers/ForceScheduledStart = true` in MAA | Inert while all 8 timers are off. Enable any one of them later and MAA starts on its own clock, colliding with AUTO-MAS |
| ~~The **second** MAA profile (`卢智超666`) had `PostActions = Shutdown`, `RunDirectly = true` and `StartEmulator = true` pointing at `#0 guan.lnk`~~ | **已于 2026-08-24 删除**（操作者要求）。那是 MuMu 时代的遗留配置，AUTO-MAS 从不驱动它，但三个开关凑在一起意味着谁手动切过去，MAA 就会自己开模拟器、启动即跑、跑完关机。母本和 MAA 目录里的四份文件都已清掉，各留一份 `.bak-delprofile-20260824-114507` 备份 |
| `Update/CheckOnStartup = true` in MAA | MaaEnd's first-attempt failures were caused by exactly this shape of thing (self-update restarting the process). The MAA doc says update settings are AUTO-MAS's to adjust, so this is left alone and watched, not changed |

### Available and switched off, by choice

森空岛 auto sign-in is disabled and its token is empty. It is free daily
resources; the doc notes it carries some risk and processes the token locally.
Turning it on is the operator's call.

屏蔽模拟器广告 = 否. An LDPlayer ad popup can cover the screen or take focus,
which is the failure mode that cost a depot read on 2026-08-22.


## Edit the JSON first; use the UI only when the JSON cannot do it

**Operator's rule, 2026-08-23.** The two routes reach the same place - a human
opens the program, changes the UI, closes it, and only then is the change
applied; the file route closes the program, edits, and reopens. Same steps in a
different order. For an agent the file route is strictly better: the change is a
diff, the check is a read-back, and nothing depends on clicking the right pixel.

The procedure, and every step of it is load-bearing:

1. **Stop the program.** AUTO-MAS keeps its configuration in memory and writes
   it out on exit; editing while it runs writes to a copy it will overwrite.
   Measured: toggling a checkbox in the UI left `Config.json` untouched, mtime
   still on the previous restart.
2. **Edit with a structural diff.** Parse, change the one field, walk both trees
   and assert that exactly the intended path differs. A typo that adds a key is
   invisible in a text diff of pretty-printed JSON.
3. **Back up next to the file** before writing, and write atomically.
4. **Restart, then read back.** Not the value you wrote - the value the program
   has after loading it.

Fall back to the UI when the JSON genuinely cannot answer:

- **The legal values are unknown.** `Info/Stage` takes a bare string, and only
  the dropdown knows that this event's stages are `SSReopen-AT`, `AT-8`, `AT-7`,
  `AT-6`, `AT-4`. Guessing a literal into a field with no validator is how a
  queue silently farms nothing.
- **The program must not be stopped** - mid-run, or mid-update.
- **The field does not exist yet**: a first-time setup the UI creates.

### Where the field names come from

`app/models/config.py` defines all 335 fields - name, group, default,
validator - but carries **no descriptions**. `app/models/schema.py` does: every
field there is a pydantic `Field(..., description="...")` in Chinese, and it is
the only human-readable field reference that exists. Neither is published as
documentation. Read `schema.py` for what a field means and `config.py` for what
values it accepts.

## Where authority lives

```
AUTO-MAS config/  ──rewrites──▶  MAA config/gui.new.json
                  ──rewrites──▶  MaaEnd config/mxu-MaaEnd.json (optionValues)
```

AUTO-MAS regenerates the downstream configs before every run, so **editing MAA's
or MaaEnd's own config is a no-op that looks like it worked**. It even forces
`task_set["Fight"]["UseWeeklySchedule"] = False` on MAA. It has happened twice
for real: someone set Endfield's sanity task to weapon growth in MaaEnd's own UI
on 2026-08-16, and the relay wrote to the same doomed copy that night.

The one exception is `Info.IfQuickConfig`. The rewrite only happens when that
user has it true; this machine does.

## AUTO-MAS

`D:\ark\automas`, v5.3.1.

### config/Config.json (global)

| Key | Value | Why |
|---|---|---|
| `Notify.SendTaskResultTime` | `不推送` | **This is the switch that mattered.** See "two layers of notification switches" below |
| `Notify.IfServerChan` | `false` | verified 2026-08-22. This page said `true`, inherited from an older doc. AUTO-MAS must not push at all - only the relay does |
| `Notify.ServerChanKey` | *(set)* | kept deliberately - muting by deleting a key hides the real switch and breaks other uses |
| `Notify.IfSendStatistic` | `false` | statistics are the relay's job |
| `Notify.IfSendMail` / `IfPushPlyer` | `false` | |
| `Start.IfSelfStart` | `true` | was false; the machine would boot and AUTO-MAS would never start |
| `Start.IfMinimizeDirectly` | `true` | stay out of the game window's way |
| `Function.IfAllowSleep` | `false` | actively blocks system sleep |

<!-- check: json D:\ark\automas\config\Config.json Notify/IfServerChan False -->
<!-- check: json D:\ark\automas\config\Config.json Notify/IfSendStatistic False -->
<!-- check: json D:\ark\automas\config\Config.json Notify/IfSendMail False -->
<!-- check: json D:\ark\automas\config\Config.json Start/IfSelfStart True -->
<!-- check: json D:\ark\automas\config\Config.json Start/IfMinimizeDirectly True -->
<!-- check: json D:\ark\automas\config\Config.json Function/IfAllowSleep False -->

### config/QueueConfig.json

| Queue | Key | Value | Why |
|---|---|---|---|
| `新队列` | `AfterAccomplish` | `NoAction` | the **relay** powers off, after the report is delivered |
| `新队列` | `StartUpEnabled` | `false` | see below |
| `Evening-MAA` | `AfterAccomplish` | `NoAction` | same |

<!-- check: json D:\ark\automas\config\QueueConfig.json */Info/AfterAccomplish NoAction -->
<!-- check: json D:\ark\automas\config\QueueConfig.json */Info/StartUpEnabled False -->
<!-- check: json D:\ark\automas\config\QueueConfig.json */Info/TimeEnabled True -->

`StartUpEnabled` means "run this queue whenever the program starts, regardless of
the clock" - and booting looks identical morning and evening. Left on, the BIOS
wake at 21:20 starts `新队列` again: Arknights farms a second time with no sanity
left, and Endfield runs a pointless round that usually reports a false protocol
space failure, followed by `Evening-MAA` at 21:30. With it off, both rounds are
purely time-triggered, with 15 min of slack in the morning and 10 in the evening.


### 两次开机是两套机制，不是同一套

早晚都会自己开机，但**原理不同**，混为一谈会得出错误结论：

| | 机制 | 前提 |
|---|---|---|
| **早上 08:45** | 智能插座断电再通电，主板「来电自启」把机器带起来 | BIOS 里 *Restore on AC Power Loss* 必须是 Power On；机器必须处于关机态（S5），不能是睡眠 |
| **晚上 21:20** | 主板 RTC 定时开机 | BIOS 里设置了定时开机；同样要求关机态 |

**为什么要写下来**：`powercfg /waketimers` 报「系统中不存在活动的唤醒计时器」，
`Get-ScheduledTask` 里所有 `ark-*` 任务的 `WakeToRun` 也都是 `False`——因为这两套
机制都在 BIOS/硬件层，Windows 根本看不见。2026-08-24 我据此差点得出"关机后不会
自己醒"的错误结论，是靠翻事件日志 6005（连续七天 08:45:1x，误差六秒内）才纠正
过来。**下次不要再从 Windows 侧找答案，这里就是答案。**

推论：**关机是安全的**，两套机制都要求机器处于关机态才生效。反过来，让机器
睡眠（而不是关机）会同时废掉这两条路。

### config/ScriptConfig.json (per user)

| Item | Value |
|---|---|
| MAA path | `D:\ark\maa` |
| MAA `RoutineTimeLimit` | `45` min (was 10 - too short, ran into false timeouts) |
| MaaEnd path | `D:\ark\maaend` |
| MaaEnd `RunTimeLimit` | `40` min (was 10) |
| `Info.Stage` / `StageMode` | `AT-4` / `Fixed` |
| `Info.MedicineNumb` | `0` - do not use sanity potions |
| `Info.Annihilation` | `Close` - **but see below** |
| `Game/WaitTime` | `60` s (**hard floor, see below**) |
| Emulator | LDPlayer: `ldplayer` + `ldconsole.exe` in `EmulatorConfig.json`; the **instance number lives elsewhere** - `ScriptConfig.json` -> `<script>/Emulator/Index` = `1000` |
| MaaEnd controller | `Win32-Front` - foreground, needs the game window frontmost and unobstructed |
| `Task.SanityTaskType` | `OperatorProgression` (single choice) |

<!-- check: json D:\ark\automas\config\ScriptConfig.json */SubConfigsInfo/UserData/*/Info/Stage AT-4 -->
<!-- check: json D:\ark\automas\config\ScriptConfig.json */SubConfigsInfo/UserData/*/Info/StageMode Fixed -->
<!-- check: json D:\ark\automas\config\ScriptConfig.json */SubConfigsInfo/UserData/*/Info/MedicineNumb 0 -->
### `Info/Annihilation` 是随游戏周变化的，不能写死校验

这个值有两个合法状态，中继按游戏周在两者之间来回切（`relay/ark_relay/annihilation.py`）：

| 时机 | 值 | 原因 |
|---|---|---|
| 游戏周开始（周一 04:00 后第一次开机） | `Annihilation` | 本周剿灭还没打，要打 |
| 本周剿灭跑成功之后 | `Close` | 打过了，再打是白扔理智 |

原先这里写死校验 `Close`，结果 2026-08-24 早上开机后必然报错——那天正是新游戏周，
中继刚打了日志 `新的一周，剿灭已恢复为 Annihilation`，**机器是对的，校验是错的**。
写死一个随时间变化的值，只会每周一制造一次假警报。

所以这里不设固定校验。要确认状态，看中继日志里的那两句话，或者直接读
`ScriptConfig.json` 的 `*/SubConfigsInfo/UserData/*/Info/Annihilation`
并对照上表判断是否合理。
<!-- check: json D:\ark\automas\config\ScriptConfig.json */Game/WaitTime 60 -->

**`Info.Annihilation` is asymmetric and the asymmetry is silent.** AUTO-MAS
offers only a static switch - there is no "once a week" it can express - so the
relay's weekly gate closes it after a pass and reopens it when the week rolls.
The gate only reopens a week it recorded closing itself (`state/annihilation.json`,
key `done_week`). A switch closed by hand has no such record, so nothing ever
reopens it and the weekly reward stops being collected indefinitely. The daily
plan prints the switch's state for exactly this reason; if it reads
`剿灭 本周已完成/关闭` on a Monday, check that file.

### The stage is AT-4 until the event ends - then it must be changed

**Changed from 1-7 to AT-4 on 2026-08-23**, at the operator's instruction, to
farm the 墟 event. AT-4's listed value is 搓玉效率 0.91.

⚠️ **AT-4 stops existing when the event closes, 2026-09-01 04:00 server time.**
A fixed stage that no longer exists fails every run after that. The relay's
daily report carries an activity countdown and flags an event that has ended,
but **changing the stage back is a manual act** - nothing does it automatically.

The alternative is AUTO-MAS's own `Task/IfActivityFirst` (界面上的「优先刷取活动关」),
which asks each run whether an event is live: if so it farms the event stage at
`ActivityStageIndex`, and if not it falls back to the fixed stage. That is the
setting to use if this should stop needing a human.

### Why the fallback stage is 1-7, and what that means for material planning

1-7 is farmed daily for 固源岩 (T2 green), which is the input to the operator's
standing 搓玉 loop:

```
2 固源岩 + 1,600 LMD  ->  1 源石碎片        (factory, 1 hour)
2 源石碎片            ->  20 合成玉          (trading post)
```

1-7 is the cheapest 固源岩 stage per sanity, which is the whole reason it is
the default rather than something with a richer drop table.

**Consequence, and it is a standing rule from the operator: treat 固源岩 and
装置 (the green rock and the green device) as though the stock were zero.**
They are consumed continuously and are permanently in deficit; whatever number
a depot readout shows for them is working stock on its way into the factory,
not a reserve. Never count them toward a T3 total, and never conclude "we have
plenty of 固源岩" from a large number - that number is the queue, not a surplus.

This changes material decisions. Converting a green stock into "how many blues
could it make" is only valid for greens that nothing else is spending:

| Green | Spent on 搓玉? | Counts toward its T3 total? |
|---|---|---|
| 固源岩 | yes, daily | **no - treat as 0** |
| 装置 | yes (alternate recipe) | **no - treat as 0** |
| 酮凝集, 糖, 聚酸酯, 异铁 … | no | yes, at that material's own ratio |

And the ratios are not uniform - check each one rather than assuming:

| T3 | Recipe |
|---|---|
| 固源岩组 | 固源岩 **x5** + 200 LMD |
| 酮凝集组 | 酮凝集 **x4** + 200 LMD |

Sources: [固源岩组](https://prts.wiki/w/%E5%9B%BA%E6%BA%90%E5%B2%A9%E7%BB%84),
[酮凝集组](https://prts.wiki/w/%E9%85%AE%E5%87%9D%E9%9B%86%E7%BB%84) on PRTS.

`StageMode: Fixed` with all alternates disabled means an expired event stage
fails every run. Whenever the current stage is an event stage, its end time is a
hard deadline for changing it.

### 队列报错的两种形态，别混为一谈

两种看起来都像"登录出问题"，原因完全不同。**先分清是哪一种再动手**，
这两个我都搞混过。

| 形态 | 特征 | 原因 |
|---|---|---|
| **整天全红** | 明日方舟连试 6 次、终末地连试 3 次，全部失败。**只发生过一天** | 账号密码没填全（`Info/Id` 非空而 `Info/Password` 为空）。这天之外账号都是填好的 |
| **首轮十四项齐报错** | 刚进到登录界面，紧接着十四个任务项一次性全部报错 | **更新打断**。这是常态性的，不是账号问题 |

**判定方法**：看**范围和次数**，不要看报错文字。

- 跨两个游戏、整天反复失败 → 查账号配置
- 单轮、进登录界面后十四项一起炸 → 更新打断

**不要因为一次账号事故就把所有登录类报错都归因于账号。** 反过来也一样：
2026-08-20 09:00 那批 ERROR 和一次 MAA 更新时间重合，我据此写下"更新打断了队列"，
而那天恰恰是账号那天——**时间重合两次都骗到了我**，一次骗我怪更新，
一次差点骗我把所有事都怪到账号头上。

游戏本身是登录着的：标题界面显示「账户登出」而非「切换账号」。

**`Info/Id` must stay empty unless `Info/Password` is filled too.**
`app/task/MaaEnd/AutoProxy.py` short-circuits on it:

```python
if self.cur_user_config.get("Info", "Id") == "" or await login(
    self.cur_user_config.get("Info", "Id"),
    self.cur_user_config.get("Info", "Password"), ...
```

Empty id means the whole login path is skipped and the run starts. A non-empty
id sends it into `login()`, which hunts for the game's "切换账号" control to
raise the login dialog. Filled-in id with an empty password is therefore a
configuration that can only fail - and it fails expensively: the recognition
task retries for about fourteen minutes before giving up, three times per round.

That is exactly what it did on 2026-08-22, costing Endfield an entire day's run
with an error message ("「明日方舟：终末地」登录失败") that points at the
account rather than at the config. The account was fine the whole time - the
game was already signed in, which is why the title screen offers 账户登出 and
not 切换账号.

It got into that state because this system's own operator half-configured it:
the id was entered while explaining the feature as "automatic login", and the
password could not be entered. **Never start this feature without the password.**
Either both fields or neither.

The Endfield sanity plan is three fields that must agree:

| Field | Meaning |
|---|---|
| `Task.SanityTaskType` | which tab: `OperatorProgression` / `WeaponProgression` / `CrisisDrills` / `Essence` |
| `Task.<that tab>` | which line, e.g. `OperatorProgression` → `OperatorEXP` |
| `Task.RewardsSetOption` | set A or B - same line, different drops |

`relay/ark_relay/sanity_plan.py` writes all three together, and the inbox applies
that batch all-or-nothing, because half a plan farms something nobody asked for.

**The emulator type must be `ldplayer` + `ldconsole.exe`.** AUTO-MAS's
`EMULATOR_PATH_BOOK["ldplayer"]["executables"][0]` is that filename and the
validator rejects other values - but writing `general` + `dnplayer.exe` passes
validation, silently ignores `Index`, and launches a different emulator instance
with no error at all.

**`Game/WaitTime` has a floor of 60.** `app/models/schema.py` declares
`WaitTime: Optional[int] = Field(default=None, ge=60)`. Writing 30 succeeds,
reads back as 30, and is silently 60 again after the next launch. The relay's
`set_wait_time` now refuses anything outside 60-600 and says why. Other numeric
fields may carry similar `ge`/`le` bounds - check the schema before believing a
write failed.

### Autostart is a scheduled task, not a registry entry

```
Task     AUTO-MAS_AutoStart
Trigger  at logon
Level    highest
```

Nothing appears in the Run key or the Startup folder, so looking there gives a
confident wrong answer. `set_SelfStart()` did not manage to create it; it was
created by hand:

```
schtasks /create /tn "AUTO-MAS_AutoStart" /tr "\"D:\...\AUTO-MAS.exe\"" /sc onlogon /rl highest /f
```

Because it is logon-triggered, the machine must reach the desktop unattended.
`AutoAdminLogon` is not configured explicitly, but the single passwordless local
account logs in on its own.

### Two layers of notification switches

Turning off notifications for both users still produced
`[MAA] 任务已全部完成！` on the phone. MAA cannot send it - there is no Server酱
key anywhere under MAA. The sender is AUTO-MAS, and the decision is in
`app/task/MAA/tools/notify.py`:

```python
if mode == "任务结果" and (
    Config.get("Notify", "SendTaskResultTime") == "任何时刻"
    or (Config.get("Notify", "SendTaskResultTime") == "仅失败时"
        and message["uncompleted_count"] != 0)
):
```

| Switch | File | Governs |
|---|---|---|
| `Notify/Enabled`, one per user | `config/ScriptConfig.json` | that user's notifications |
| `Notify/SendTaskResultTime`, global | `config/Config.json` | "task result" pushes: `不推送` / `任何时刻` / `仅失败时` |

<!-- check: json D:\ark\automas\config\Config.json Notify/SendTaskResultTime 不推送 -->

The per-user switch does not gate the global path. That is the whole reason
turning it off changed nothing.

An older trap on the same subject: three layers must all be on for anything to
send - `SendTaskResultTime` → `IfSendStatistic` → `IfServerChan` + key. Turning
on one or two is indistinguishable from turning on none.

## MAA

`D:\ark\maa`.

**The directory name is not the version.** It is whatever the package was
called when it was first unpacked; MAA updates itself in place and the folder
keeps its original name. The running version was `v6.17.0-beta.4` on
2026-08-22, read from the window title in `focus-watch.log`, with resources
last updated 2026-08-20. `resource/version.json` carries the resource date, not
the program version. Never quote the folder name as a version - it has been
wrong here by a whole major release.

### MAA 的通知开关有两份，会被覆盖的那份不算数

**改 MAA 自己的 `config/gui.new.json` 是没用的。** AUTO-MAS 为每个脚本存着一份
母本，每次拉起 MAA 之前把它**覆盖**进 MAA 的目录：

```
D:\ark\automas\data\754d129e-d587-435b-b75f-a0b91aac7020\Default\ConfigFile\gui.new.json
```

（路径里的 uid 是 MAA 脚本在 AUTO-MAS 里的 id，见 `/api/scripts/get`。
合并逻辑在 `app/task/MAA/tools/UpdateMAA.py`，是双向的——所以在 MAA 界面里改完
也可能被同步回母本，反过来同样。）

2026-08-24 就栽在这上面：MAA 目录里四个开关全是 `false`，`check-docs.py` 84 项
全绿，但手机照样收到 `[MAA] 任务已全部完成`。因为**校验查的是副本**，而母本里
`SendWhenComplete` 是 `true`，每次运行前又被盖回去。目录里那个
`gui.new.json.bak-notify-off` 备份说明这事以前处理过、后来被同步回滚了。

**所以两份都要关，而且两份都要校验。** 下面的检查项现在覆盖母本。

<!-- check: json D:\ark\automas\data\754d129e-d587-435b-b75f-a0b91aac7020\Default\ConfigFile\gui.new.json Configurations/*/Gui/ExternalNotification/SendWhenComplete False -->
<!-- check: json D:\ark\automas\data\754d129e-d587-435b-b75f-a0b91aac7020\Default\ConfigFile\gui.new.json Configurations/*/Gui/ExternalNotification/SendWhenError False -->
<!-- check: json D:\ark\automas\data\754d129e-d587-435b-b75f-a0b91aac7020\Default\ConfigFile\gui.new.json Configurations/*/Gui/ExternalNotification/SendWhenStalled False -->

<!-- check: json D:\ark\maa\config\gui.new.json Configurations/*/Gui/ExternalNotification/SendWhenComplete False -->
<!-- check: json D:\ark\maa\config\gui.new.json Configurations/*/Gui/ExternalNotification/SendWhenError False -->
<!-- check: json D:\ark\maa\config\gui.new.json Configurations/Default/Gui/ExternalNotification/SendWhenError False -->
<!-- check: json D:\ark\maa\config\gui.new.json Configurations/Default/Gui/ExternalNotification/SendWhenStalled False -->

**`RunDirectly: true` and `PostActions: "ExitArknights, ExitSelf"` on Default
are the normal state** - MAA is launched by AUTO-MAS, runs, and closes the game
and itself. Opening MAA by hand therefore starts a run and then shuts the game
down, which makes the 小工具 tools (仓库识别 etc.) hard to reach. To use them,
flip both temporarily and **put them back**; check-docs.py will catch it if you
forget, which is how the 2026-08-22 depot run was caught.

**`config/gui.new.json` is the live file. `config/gui.json` is a dead older
format** - reading it yields confidently outdated answers, e.g. "external
notification is not configured".

There are two profiles under `Configurations`. `Default` is the one AUTO-MAS
drives. The second one is **also an automation profile**, not a
"played by hand" one - it carries `RunDirectly: true` and
`PostActions: Shutdown`, i.e. start immediately and power the machine off when
done. (This page previously described it as the owner's manual configuration.
That was inherited and wrong.)

**Leave the second profile alone**, for a reason that can be checked: its
Server酱 key is not the same as `Default`'s, so whatever it pushes goes to a
different person. Compare the keys before touching either.

Changing only one profile is also the usual way to change nothing, so read back
whichever one you meant.

| Key | Value | Note |
|---|---|---|
| `Gui.ExternalNotification.ShowWhenCompleteWithDetails` | `true` | without it the completion push has no content at all |
| `ExternalNotification.SendWhenComplete/Error/Stalled` (Default) | `false` since 2026-08-22 | the relay is the only sender |
| `ExternalNotification.SendWhen*` (the other profile) | `false` since 2026-08-22 | **every** profile is silent - only the relay notifies, see [NOTIFICATIONS.md](NOTIFICATIONS.md). A differing Server酱 key is not a reason to leave one on |
| `Gui.PostActions` (Default) | `None` | shutdown belongs to the relay |
| `SendKey` | DPAPI-encrypted | cannot be read, and does not need to be |

`cache/gui/StageActivityV2.json` holds the current event's end time. The relay
reads it to put the countdown in every report.

## MaaEnd

`D:\ark\maaend`.

Same trap as MAA: **the directory name is not the version.** The running build
was `v2.25.0-rc.1` on 2026-08-21, read from the window title in
`focus-watch.log`. The folder still says v1.6.5 because that is what the
package was called when it was unpacked.

`config/mxu-MaaEnd.json`'s "full daily" config carried three
`__MXU_WEBHOOK__` tasks, all now `enabled: false`: one "task started", and two
identical "task finished" copies, so the finish line fired twice.

They are not misconfigured, they are **unconfigurable**: `__MXU_WEBHOOK__` GETs a
hardcoded URL with `title` and `desp` baked into the query string. It has no
access to any run result. The only correct action is to disable them.

Editing trap: in `tasks[16]` a `customName` key sits between `taskName` and
`enabled`, so a naive regex misses it and instead damages history entries under
`recentlyClosed`. Structural diff caught this; that is why the diff step exists.

## Power and SSH

See [OPERATIONS.md](OPERATIONS.md) - `powercfg` values and the
`administrators_authorized_keys` rule.

OpenSSH was installed from the [Win32-OpenSSH](https://github.com/PowerShell/Win32-OpenSSH)
standalone MSI; `Add-WindowsCapability` failed with a corrupt component store.
Auto-restart on failure:

```
sc.exe failure sshd reset= 86400 actions= restart/5000/restart/10000/restart/30000
```

## Relay environment

`relay/.env` on the machine, never committed.

| Variable | Meaning |
|---|---|
| `ARK_HISTORY_DIR` | AUTO-MAS's `history` directory (required) |
| `ARK_AUTOMAS_DIR` | AUTO-MAS root - schedule reading and config edits |
| `ARK_MAAEND_DIR` | MaaEnd root |
| `ARK_MAS_PORT` | AUTO-MAS backend port, default `36163`. The pre-update asks it over HTTP on localhost rather than launching anything. |
| `ARK_STATE_DIR` | relay state, default `./ark-state` |
| `ARK_LAST_RUN_AFTER` | fallback for the day's last run time, default `21:30`; the real cutoff comes from QueueConfig |
| `ARK_SHUTDOWN_AFTER_RUN` | `1` - the relay powers the machine off |
| `ARK_REPORT_BEFORE_SHUTDOWN` | `1` - backstop: send progress from inside the shutdown path if the interim never went out |
| `ARK_INTERIM_REPORT` | `1` - the interim summary after each finished daytime round; set `0` to keep only the daily report |
| `ARK_BOOT_TIMES` | scheduled power-on times, server clock, default `08:40,21:20`. Debug mode releases 10 minutes before the next one. Nothing on the machine records these - the morning wake is a Mi Home plug, the evening one a BIOS RTC alarm - so **moving either means changing this** |
| `ARK_SHUTDOWN_MIN_UPTIME` | minimum uptime before a shutdown is allowed |
| `ARK_LOG_FILE` | where the relay logs; `service.py` sets it itself, because the service does not run `ark-relay.ps1` |
| `ARK_CHECK_TIMES` | extra checkpoint times, beyond the queue times read from AUTO-MAS |
| `ARK_PARTIAL_WINDOW_MIN` / `ARK_PARTIAL_GRACE_MIN` | how long a partially-complete round may stay open before it is judged |
| `ARK_HOST` | the machine's Tailscale address; used by the Mac-side scripts, not by the relay |
| `ARK_POLL_SECONDS` | fallback scan interval, default 300 - **only used if the directory watch cannot be established**; the production path never reaches it |
| `SERVERCHAN_KEY` | Server酱 |
| `WECOM_CORPID` / `WECOM_SECRET` / `WECOM_AGENTID` | WeCom self-built app - dies with `60020` whenever the home IP changes |
| `WECOM_BOT_URL` | WeCom group bot webhook - no trusted-IP list, better fit for a dial-up home line |
| `ARK_LLM_PROVIDER` / `_BASE_URL` / `_KEY` / `_MODEL` | prose only; the report is complete without it |

## Backups

Every config touched was backed up first:

```
AUTO-MAS\config.bak-20260814\                              (whole directory, 9 files)
AUTO-MAS\config\Config.json.bak-20260814
AUTO-MAS\config\QueueConfig.json.bak-20260814
MAA-v5.1.0-win-x64\config\gui.new.json.bak-20260814
```

The older documents also listed
`MaaEnd-win-x86_64-v1.6.5\config\mxu-MaaEnd.json.bak-20260814` under the claim
that "everything touched was backed up first". **That file does not exist**
(checked 2026-08-22), so the MaaEnd webhook edit went in without one. The claim
was not true when it was written, or the backup was later removed; either way,
do not rely on a backup being there because a document says so.
