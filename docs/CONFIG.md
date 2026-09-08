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
| Queue chaining | 早班 09:00 -> MAA, MaaEnd, then OK-WW; 晚班 21:30 -> MAA | queues run scripts in series |
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
| ~~The **second** MAA profile (`第二个配置`) had `PostActions = Shutdown`, `RunDirectly = true` and `StartEmulator = true` pointing at `#0 guan.lnk`~~ | **Deleted on 2026-08-24** (the operator asked for it). It was a leftover from the MuMu era and AUTO-MAS never drove it, but those three switches together mean that anyone who manually switches to it makes MAA start the emulator itself, run immediately, and power off when done. All four files in the master config and the MAA directory have been cleaned, each leaving one `.bak-delprofile-20260824-114507` backup |
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
user has it true.

**How this machine actually stands (since 2026-08-28): `IfQuickConfig` is `false` for both MaaEnd and OK-WW, so field edits made on the MAS side are never pushed down (`app/task/Okww/AutoProxy.py:320` and `MaaEnd/AutoProxy.py:537` return immediately), and what really takes effect is each program's own master config. 明日方舟 has no such switch - every dispatch writes into gui.new.json, so going through MAS is correct there.** To find out which values are really in effect, always run `scripts/mac/winrun.sh --py scripts/mac/lib/effective_config.py`.

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
| `早班` | `AfterAccomplish` | `NoAction` | the **relay** powers off, after the report is delivered |
| `早班` | `StartUpEnabled` | `false` | see below |
| `晚班` | `AfterAccomplish` | `NoAction` | same |

<!-- check: json D:\ark\automas\config\QueueConfig.json */Info/AfterAccomplish NoAction -->
<!-- check: json D:\ark\automas\config\QueueConfig.json */Info/StartUpEnabled False -->
<!-- check: json D:\ark\automas\config\QueueConfig.json */Info/TimeEnabled True -->

`StartUpEnabled` means "run this queue whenever the program starts, regardless of
the clock" - and booting looks identical morning and evening. Left on, the BIOS
wake at 21:20 starts `早班` again: Arknights farms a second time with no sanity
left, and Endfield runs a pointless round that usually reports a false protocol
space failure, followed by `晚班` at 21:30. With it off, both rounds are
purely time-triggered, with 15 min of slack in the morning and 10 in the evening.


### The two power-ons are two different mechanisms, not one

The machine powers itself on both morning and evening, but **the mechanism differs**,
and conflating them leads to wrong conclusions:

| | Mechanism | Precondition |
|---|---|---|
| **08:45, morning** | the smart plug cuts power and restores it; the motherboard's "power on after AC loss" brings the machine up | *Restore on AC Power Loss* in the BIOS must be Power On; the machine must be powered off (S5), not asleep |
| **21:20, evening** | the motherboard's RTC alarm | a scheduled power-on is set in the BIOS; it likewise requires the powered-off state |

**Why this is written down**: `powercfg /waketimers` reports 「系统中不存在活动的唤醒计时器」,
and `WakeToRun` is `False` for every `ark-*` task in `Get-ScheduledTask` - because both
mechanisms live in the BIOS/hardware layer, where Windows cannot see them at all. On
2026-08-24 I nearly concluded from that "the machine does not wake itself after a
shutdown", which is wrong; digging through event log 6005 (seven days in a row at
08:45:1x, within six seconds of each other) is what corrected it.
**Do not go looking on the Windows side for this answer again - the answer is here.**

Corollary: **shutting down is safe**, because both mechanisms require the machine to be
powered off before they work. Conversely, putting the machine to sleep (instead of
shutting it down) breaks both paths at once.

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
### `Info/Annihilation` changes with the game week and must not be checked against a fixed value

The value has two legal states, and the relay flips between them by game week
(`relay/ark_relay/annihilation.py`):

| When | Value | Why |
|---|---|---|
| start of the game week (first boot after Monday 04:00) | `Annihilation` | this week's annihilation has not been run yet, so run it |
| after this week's annihilation succeeds | `Close` | it has been run; running it again throws sanity away |

This page used to hard-code a check for `Close`, which then failed by construction at the
2026-08-24 morning boot - that day was the start of a new game week, and the relay had just
logged `新的一周，剿灭已恢复为 Annihilation`. **The machine was right and the check was
wrong.** Hard-coding a value that changes over time only manufactures one false alarm every
Monday.

So there is no fixed check here. To confirm the state, read those two lines in the relay log,
or read `*/SubConfigsInfo/UserData/*/Info/Annihilation` out of `ScriptConfig.json` directly
and judge it against the table above.
<!-- check: json D:\ark\automas\config\ScriptConfig.json */Game/WaitTime 60 -->

**`Info.Annihilation` is asymmetric and the asymmetry is silent.** AUTO-MAS
offers only a static switch - there is no "once a week" it can express - so the
relay's weekly gate closes it after a pass and reopens it when the week rolls.
The gate only reopens a week it recorded closing itself (`state/annihilation.json`,
key `done_week`). A switch closed by hand has no such record, so nothing ever
reopens it and the weekly reward stops being collected indefinitely. The daily
plan prints the switch's state for exactly this reason; if it reads
`剿灭 本周已完成/关闭` on a Monday, check that file.

### The fixed stage is 1-7 today (measured with config-check.py on 2026-08-31)

It was changed to the event stage AT-4 on 2026-08-23 to farm 「墟」, and **has since been
changed back to 1-7**. `活动关优先` is false, so nothing breaks when the event ends at
09-01 04:00.

⚠️ This section used to say "it is AT-4 now" while the machine had long been on 1-7.
**A document that lies is more dangerous than no document** - the 826 incident started from
a wrong idea of what a field meant. Therefore:
**before asserting anything about the configuration, run `scripts/mac/config-check.py` and
paste its output, then state the conclusion.**

The event-stage route still works as such; it just needs a human to switch it. To take the
human out of it, use AUTO-MAS's own `Task/IfActivityFirst` (「优先刷取活动关」 in the UI):
when an event is running it farms the event stage that `ActivityStageIndex` points at, and
otherwise it falls back to the fixed stage.

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

### Two shapes of queue error, do not conflate them

Both look like "something went wrong with the login" and their causes are entirely
different. **Work out which one it is before touching anything** - I have confused these
two in both directions.

| Shape | Signature | Cause |
|---|---|---|
| **Red all day** | 明日方舟 fails 6 attempts in a row, 终末地 fails 3 in a row, all of them. **It has happened on exactly one day** | the account credentials are half-filled (`Info/Id` non-empty while `Info/Password` is empty). On every other day the account fields are filled in correctly |
| **Fourteen items erroring together in the first round** | the login screen has just come up, and then fourteen task items all error at once | **an update interrupted it**. This is the routine case, not an account problem |

**How to decide**: look at **the scope and the count**, not at the error text.

- across both games, failing repeatedly all day → check the account configuration
- one round, fourteen items blowing up together right after the login screen → an update interrupted it

**Do not attribute every login-shaped error to the account just because of one account
incident.** The reverse holds too: the batch of ERRORs at 2026-08-20 09:00 coincided with a
MAA update, and on that basis I wrote "an update interrupted the queue" - while that day was
precisely the account day. **The timing coincidence fooled me both times**: once into
blaming an update, and once into nearly blaming everything on the account.

The game itself is signed in: the title screen shows 「账户登出」 rather than 「切换账号」.

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

### MAA's notification switches exist in two copies, and the one that gets overwritten does not count

**Editing MAA's own `config/gui.new.json` achieves nothing.** AUTO-MAS keeps a master copy
for every script and **overwrites** MAA's directory with it before each launch:

```
D:\ark\automas\data\754d129e-d587-435b-b75f-a0b91aac7020\Default\ConfigFile\gui.new.json
```

(The uid in that path is the MAA script's id inside AUTO-MAS, see `/api/scripts/get`.
The merge logic lives in `app/task/MAA/tools/UpdateMAA.py` and is bidirectional - so a change
made in MAA's UI may also be synced back into the master copy, and vice versa.)

This is exactly what went wrong on 2026-08-24: all four switches in MAA's directory were
`false` and all 84 `check-docs.py` items were green, yet the phone still received
`[MAA] 任务已全部完成`. Because **the checks were looking at the copy**, while
`SendWhenComplete` was `true` in the master and got written back over the copy before every
run. The `gui.new.json.bak-notify-off` backup in that directory shows this had been dealt
with before and was later reverted by the sync.

**So both copies must be turned off, and both copies must be checked.** The check directives
below now cover the master copy.

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
| `ARK_OKWW_DIR` | OK-WW root (`D:\ark\okww`). The weekly boss master/copy configs and OK-WW's own logs are all derived from this |
| `ARK_OKWW_LOG` | names OK-WW's log file directly. Unset, it takes the newest file under `ARK_OKWW_DIR`'s `data/apps/ok-ww/working/logs` |
| `ARK_KEEP_TMP` | affects tests only: set it to 1 and temporary directories are not cleaned up, so the scene is left intact for investigation |

| `ARK_PHONE_TOPIC` | the ntfy topic the phone remote uses. **Without it the whole phone page is deaf** - the machine receives no commands and the page sees no status |
| `ARK_PHONE_PIN` | the phone page's passphrase. A command is only accepted when it carries the right one; leaving it unset means anyone who learns the topic name can issue commands |
| `ARK_INBOX_URL` | the address of the repository inbox's `queue/config.json`. Unset, it uses the built-in GitHub address; change it only when moving to another repository |
| `SKLAND_TOKEN` | the 森空岛 login credential. Sanity, banners and investment levels in the daily report all depend on it; when it expires those sections quietly go empty |
| `WECOM_TOUSER` | who WeCom pushes to, default `@all`. The WeCom channel is currently unusable because of 60020, so all pushes go through Server酱 |
| `ARK_LLM_KEY` | the model key for the one plain-language summary sentence at the top of the daily report. **Leaving it unset raises no error**, it just drops that sentence |
| `ARK_LLM_BASE_URL` | that model's address, default `https://api.deepseek.com` |
| `ARK_LLM_MODEL` | the model name, default `deepseek-chat` |

The following are not on the game machine; they are used by the Mac-side scripts and by
GitHub Actions:

| Variable | Meaning |
|---|---|
| `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET` | the read-only OAuth client that boot supervision (`scripts/watchdog.py`) uses to ask Tailscale whether that machine is online. They belong in the repository secrets, see `docs/BACKLOG.md` |
| `CHECK_CRON` | same context: the schedule expression GitHub Actions passes in; an empty value means a manual trigger (check everything, but only print, do not push) |
| `IDMAP_STORE` | for the gate self-check only: makes `idmap.py` write into a temporary table instead of polluting the real registry |
| `UPSTREAM_POST_OFFLINE` | for the gate self-check only: makes `upstream-post.py` read from cache instead of going online |


**There is no `.env.example`.** It was deleted on 2026-09-08: the code read none of the four
variables it listed, and none of the thirty-odd that actually have to be set were in it -
filling it in was the same as setting nothing. This table is the authority on what to set,
and it is watched by the `[env]` section of `scripts/mac/check-docs.py`, which goes red if a
variable is missing from it.
(On 2026-09-08 that gate itself was fixed: it used to recognize only the `ARK_` prefix, only
scan `relay/`, and only recognize the `environ("X")` spelling, so 13 variables slipped
through the cracks while this very sentence claimed "it goes red if one is missing" -
claiming a check exists when it does not is worse than having none.)
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
