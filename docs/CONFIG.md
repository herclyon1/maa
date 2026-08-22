# Configuration inventory

Every setting that was deliberately changed, plus the traps around it. When a
value here disagrees with the machine, the machine is right and this page is a
bug - fix it, or run `scripts/mac/check-docs.py` which will say so first.

Values below verified 2026-08-21.

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
| `Notify.IfServerChan` | `true` | global Server酱 channel |
| `Notify.ServerChanKey` | *(set)* | kept deliberately - muting by deleting a key hides the real switch and breaks other uses |
| `Notify.IfSendStatistic` | `false` | statistics are the relay's job |
| `Notify.IfSendMail` / `IfPushPlyer` | `false` | |
| `Start.IfSelfStart` | `true` | was false; the machine would boot and AUTO-MAS would never start |
| `Start.IfMinimizeDirectly` | `true` | stay out of the game window's way |
| `Function.IfAllowSleep` | `false` | actively blocks system sleep |

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
| Emulator | LDPlayer: `ldplayer` + `ldconsole.exe`, `Index: 1000` |
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

`StageMode: Fixed` with all alternates disabled means an expired event stage
fails every run. Whenever the current stage is an event stage, its end time is a
hard deadline for changing it.

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

**`config/gui.new.json` is the live file. `config/gui.json` is a dead older
format** - reading it yields confidently outdated answers, e.g. "external
notification is not configured".

There are two profiles in it. `Default` is the automated one;
`<the owner's manual profile>` is what the machine's owner uses by hand and has
`PostActions: Shutdown` - **do not touch it**. Changing only one profile is the
usual way to change nothing.

| Key | Value | Note |
|---|---|---|
| `Gui.ExternalNotification.ShowWhenCompleteWithDetails` | `true` | without it the completion push has no content at all |
| `SendWhenComplete` / `SendWhenError` / `SendWhenStalled` | `false` on both profiles | the relay is the only sender |
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
MaaEnd-win-x86_64-v1.6.5\config\mxu-MaaEnd.json.bak-20260814
```
