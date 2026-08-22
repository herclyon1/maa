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
| The **second** MAA profile has `PostActions = Shutdown` | AUTO-MAS only drives `Default`, so it never fires - but running that profile by hand from MAA's UI powers the machine off, against the standing "never shut down without an order" |
| The same profile has `StartEmulator = true` pointing at `#0 guan.lnk` | That is the Arknights official launcher shortcut, not LDPlayer - the source of the wrong-thing-started confusion on 2026-08-22 |
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

`D:\Users\Administrator\Desktop\AUTO-MAS`, v5.3.1.

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

<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json Notify/IfServerChan False -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json Notify/IfSendStatistic False -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json Notify/IfSendMail False -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json Start/IfSelfStart True -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json Start/IfMinimizeDirectly True -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json Function/IfAllowSleep False -->

### config/QueueConfig.json

| Queue | Key | Value | Why |
|---|---|---|---|
| `新队列` | `AfterAccomplish` | `NoAction` | the **relay** powers off, after the report is delivered |
| `新队列` | `StartUpEnabled` | `false` | see below |
| `Evening-MAA` | `AfterAccomplish` | `NoAction` | same |

<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\QueueConfig.json */Info/AfterAccomplish NoAction -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\QueueConfig.json */Info/StartUpEnabled False -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\QueueConfig.json */Info/TimeEnabled True -->

`StartUpEnabled` means "run this queue whenever the program starts, regardless of
the clock" - and booting looks identical morning and evening. Left on, the BIOS
wake at 21:20 starts `新队列` again: Arknights farms a second time with no sanity
left, and Endfield runs a pointless round that usually reports a false protocol
space failure, followed by `Evening-MAA` at 21:30. With it off, both rounds are
purely time-triggered, with 15 min of slack in the morning and 10 in the evening.

### config/ScriptConfig.json (per user)

| Item | Value |
|---|---|
| MAA path | `D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64` |
| MAA `RoutineTimeLimit` | `45` min (was 10 - too short, ran into false timeouts) |
| MaaEnd path | `D:\maaend\MaaEnd-win-x86_64-v1.6.5` |
| MaaEnd `RunTimeLimit` | `40` min (was 10) |
| `Info.Stage` / `StageMode` | `1-7` / `Fixed` |
| `Info.MedicineNumb` | `0` - do not use sanity potions |
| `Info.Annihilation` | `Close` - **but see below** |
| `Game/WaitTime` | `60` s (**hard floor, see below**) |
| Emulator | LDPlayer: `ldplayer` + `ldconsole.exe` in `EmulatorConfig.json`; the **instance number lives elsewhere** - `ScriptConfig.json` -> `<script>/Emulator/Index` = `1000` |
| MaaEnd controller | `Win32-Front` - foreground, needs the game window frontmost and unobstructed |
| `Task.SanityTaskType` | `OperatorProgression` (single choice) |

<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\ScriptConfig.json */SubConfigsInfo/UserData/*/Info/Stage 1-7 -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\ScriptConfig.json */SubConfigsInfo/UserData/*/Info/StageMode Fixed -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\ScriptConfig.json */SubConfigsInfo/UserData/*/Info/MedicineNumb 0 -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\ScriptConfig.json */SubConfigsInfo/UserData/*/Info/Annihilation Close -->
<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\ScriptConfig.json */Game/WaitTime 60 -->

**`Info.Annihilation` is asymmetric and the asymmetry is silent.** AUTO-MAS
offers only a static switch - there is no "once a week" it can express - so the
relay's weekly gate closes it after a pass and reopens it when the week rolls.
The gate only reopens a week it recorded closing itself (`state/annihilation.json`,
key `done_week`). A switch closed by hand has no such record, so nothing ever
reopens it and the weekly reward stops being collected indefinitely. The daily
plan prints the switch's state for exactly this reason; if it reads
`剿灭 本周已完成/关闭` on a Monday, check that file.

### Why the stage is 1-7, and what that means for material planning

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

<!-- check: json D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json Notify/SendTaskResultTime 不推送 -->

The per-user switch does not gate the global path. That is the whole reason
turning it off changed nothing.

An older trap on the same subject: three layers must all be on for anything to
send - `SendTaskResultTime` → `IfSendStatistic` → `IfServerChan` + key. Turning
on one or two is indistinguishable from turning on none.

## MAA

`D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64`.

**The directory name is not the version.** It is whatever the package was
called when it was first unpacked; MAA updates itself in place and the folder
keeps its original name. The running version was `v6.17.0-beta.4` on
2026-08-22, read from the window title in `focus-watch.log`, with resources
last updated 2026-08-20. `resource/version.json` carries the resource date, not
the program version. Never quote the folder name as a version - it has been
wrong here by a whole major release.

<!-- check: json D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64\config\gui.new.json Configurations/*/Gui/ExternalNotification/SendWhenComplete False -->
<!-- check: json D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64\config\gui.new.json Configurations/*/Gui/ExternalNotification/SendWhenError False -->
<!-- check: json D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64\config\gui.new.json Configurations/Default/Gui/ExternalNotification/SendWhenError False -->
<!-- check: json D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64\config\gui.new.json Configurations/Default/Gui/ExternalNotification/SendWhenStalled False -->

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

`D:\maaend\MaaEnd-win-x86_64-v1.6.5`.

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
