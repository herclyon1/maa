# AUTO-MAS and OK-WW: the UI, the config, and headless operation

Written 2026-08-25. **The purpose of this document is that nobody has to work this out again.**
Every conclusion here was checked that day on the real machine, either by reading source or by
calling the API. None of it is guesswork.

Related: [HEADLESS.md](HEADLESS.md) (headless entry points for each program),
[CONFIG.md](CONFIG.md) (the individual config items, and master copy vs working copy),
[PITFALLS.md](PITFALLS.md).

---

## Conclusion first: you do not have to click the UI

The AUTO-MAS Electron window is only a shell. Behind it is a **FastAPI backend** listening on
`<tailscale-ip>:36163`, **with no authentication**, exposing 126 endpoints.

```bash
export ARK_HOST=100.65.39.119
scripts/mac/mas-api.py paths                       # every endpoint + required fields
scripts/mac/mas-api.py get /api/queue/get
scripts/mac/mas-api.py get /api/scripts/user/get '{"scriptId":"<uid>"}'
```

**Changing config through the API does not require restarting AUTO-MAS.** This matters, because
editing the `config/*.json` files directly **does not take effect**: AUTO-MAS reads the config
into memory and writes it back on exit, so any file you edit while it is running gets overwritten
by its in-memory values. Going through the API means the backend itself persists the change, so
the problem does not arise.

> Already stepped in this on 2026-08-24: edited the files, saw no change in the UI, concluded
> "it did not take effect" — when in fact the writing method was simply wrong.

---

## What the five screens are

| Screen | API prefix | What it stores | Who references it |
|---|---|---|---|
| **脚本管理** | `/api/scripts/*` | One entry per automation program: where it is installed, timeout, retry count; **users** hang beneath it | The dispatch queue references it by `ScriptId` |
| **计划管理** | `/api/plan/*` | A **plan table** that switches what to farm by day of week; optional feature | Only takes effect once a user's `StageMode`/`SanityMode` holds a plan uid |
| **模拟器管理** | `/api/emulator/*` | Emulator executable, multi-instance index, boss key, wait timeout | A script's `Emulator.Id`; PC-client scripts hold `-` |
| **调度队列** | `/api/queue/*` | One queue = a list of **queue items** (one script each) + a list of **timer items** | This is the thing that actually runs every day |
| **调度中心** | `/api/dispatch/*` | **No static config**; it is a runtime panel: manual start/stop, power flag | — |

### 脚本管理

A "script" is the integration point for one automation program. Currently three:

| Name | Type | Path | Notes |
|---|---|---|---|
| MAA | `MaaConfig` | `D:\ark\maa` | 明日方舟, runs through the emulator |
| MaaEnd | `MaaEndConfig` | `D:\ark\maaend` | 终末地, PC client, `Win32-Front` |
| OK-WW | `OkwwConfig` | `D:\ark\okww` (the field is called `RootPath`) | 鸣潮, PC client |

**Users** hang beneath each script (`/api/scripts/user/*`): account, enabled state, task
toggles, and how sanity/stages are configured. Currently one each: `arknights` / `endfield` / `wuwa`.

**Note that the field names are not consistent**: MAA and MaaEnd use `Info.Path`, OK-WW uses
`Info.RootPath`.

**`Script` and `IfUseMasConfig` showing as `null` is normal.** Those two fields belong to
`GeneralUserConfig` (the "通用脚本" type); `OkwwConfig` simply does not have them, and the
response model includes them uniformly, hence `null`. That is what the "no script name / nodata"
in the UI is; it is not a missing setting.

### 计划管理

Plan tables let you change farming targets by day of week. **They are optional**:

- A MAA user's `Info.StageMode`: `"Fixed"` = use the user's own fixed stage; otherwise it holds a plan uid.
- A MaaEnd user's `Info.SanityMode`: same idea.

**Both are currently `Fixed`** (MAA fixed on AT-4 with 0 sanity potions; MaaEnd uses the sanity
task fields on the user), so the 「新 MAA 计划表」 plan table is an **empty shell that nothing
references** — every field is `-`, and a `grep` across the whole config directory finds it only in
its own definition file. Deleting it or keeping it makes no difference to operation.

### 模拟器管理

Currently one: LDPlayer at `D:\LD-MRFZ\LDPlayer9\ldconsole.exe`, `MaxWaitTime` 300,
`ForceKillOnClose` false. MAA references it, with multi-instance index `1000`.
MaaEnd and OK-WW are PC-client games, so their `EmulatorId` is `-`; **that is correct, not a
missing setting**.

### 调度队列

A queue is made of two groups of things, each with its own endpoints:

- **Queue items** `/api/queue/item/*` — an ordered list of scripts; the only field is `Info.ScriptId`
- **Timer items** `/api/queue/time/*` — `Enabled` + `Days` (array of weekdays) + `Time`

The queue's own `Info` has `Name` / `TimeEnabled` / `StartUpEnabled` / `AfterAccomplish`.

The two current queues are in [CONFIG.md](CONFIG.md). Both are `AfterAccomplish=NoAction` —
**shutdown is the relay's job, not AUTO-MAS's**.

### 调度中心

A runtime panel; there is nothing to configure. **Manual dispatch always goes through
`scripts/mac/run-one.sh MAA|MaaEnd|OK-WW`**, which has the busy/idle gate built in. Calling
`/api/dispatch/start` bare fights with AUTO-MAS's own whole-queue retry — that is exactly how, on
the morning of 2026-09-01, we ended up with 「MAA 重复吃药、三个游戏同时在线」 and had to pull the
power to recover.

`/api/dispatch/start` starts one task manually, `/api/dispatch/stop` aborts it, and
`/api/dispatch/get|set/power` reads and writes the power flag (currently `NoAction`, matching the
queues).

---

## What OK-WW (鸣潮) can do

OK-WW is an ok-script family program. Its task list can be read straight off the filenames in
`D:\ark\okww\data\apps\ok-ww\working\configs\*.json`, and each task class lives in `src/task/*.py`.

| Task | Class | Notes |
|---|---|---|
| 📅 日常 | `DailyTask` | Spends stamina on one of 无音区 / 凝素领域 / 模拟领域, optionally with additional tasks |
| 👥 多账号日常 | `MultiAccountDailyTask` | |
| 🌊 无音区 | `TacetTask` | By index in the F2 list |
| ⚒️ 凝素领域 | `ForgeryTask` | By index in the F2 list, `structure=[5,5,5,5]` for 20 total, **40 stamina each time** |
| 🧪 模拟领域 | `SimulationTask` | Chosen by material: 共鸣者经验 / 武器经验 / 贝币, **40 stamina each time** |
| 🌙 梦魇巢穴 | `NightmareNestTask` | Runs the map clearing 「梦魇净化」 and 「无音区巢穴」; **has no stamina constant, spends no waveplates, only time** |
| 🎡 周常乐园 | `GardenTask` | |
| 🌀 声骸刷取 | `FarmEchoTask` | **The weekly boss lives here**, see below |
| Everything else | | Auto combat, five-in-one merge, batch enhance / reroll main stat, star-track farming, auto login, dialogue skip, mouse-drift protection, diagnostics |

### Weekly bosses: **cannot be done**, do not waste time configuring it

Confirmed 2026-08-25 by reading the `FarmEchoTask.py` source: **it only picks up echoes, it does
not claim the boss's material rewards.** The only thing that handles the harvest is
`pick_echo()` / `yolo_find_echo()`; there is **no logic at all for spending waveplates to absorb
or for clicking to claim rewards**. It also **does not check the three-per-week limit**
(`total_weekly_number = 9` is only used to validate the UI option, and `Repeat Farm Count: 10000`
is just a repeat count, it will not stop on its own).

So weekly boss materials (e.g. 「万囮牢·朽躯」) **can only be fought and claimed by hand**.

(Lesson: at one point I saw `Teleport to Boss = Weekly Challenge` and declared "it has weekly boss
support", having verified only that it can teleport there and not what it does once it arrives.
The user caught it on the spot.)

### The weekly-boss teleport itself does exist (but as above, it only picks up echoes)

`FarmEchoTask`'s `Teleport to Boss` has three settings: `No` / **`Weekly Challenge`** / `Boss Challenge`.

- Sub-options when `Weekly Challenge` is selected: `Which Weekly Boss to Teleport` (1-based,
  top-to-bottom in the F2 list, 9 total), `Boss Level` (50/60/70/80/90)
- When `Boss Challenge` is selected: `Which Boss Challenge to Teleport` (20 total), `Boss Level`

**But it cannot be wired into an AUTO-MAS queue.** Two constraints:

1. `OkwwTaskIndexValidator` only permits `TaskIndex ∈ {1, 7}`, i.e. AUTO-MAS can only launch
   **日常** or **多账号日常**; it cannot launch anything else.
2. `FarmEchoTask` does not set `support_schedule_task = True`, so OK-WW's own scheduler cannot
   schedule it either (`DailyTask`/`TacetTask`/`ForgeryTask`/`NightmareNestTask` all set it; this
   one does not).

**The workable route**: run it from the command line directly, which has already been verified —
`python.exe -m ok run_task <task name> -e` (see HEADLESS.md). To run it periodically, hang it off
the relay.

### There is no "maintain inventory" feature

OK-WW only has the concept of **counts**; there is no "farm until inventory reaches N, then stop":

- `FarmEchoTask`'s `Repeat Farm Count` (default 10000) is a repeat count
- On the AUTO-MAS side, `ProxyTimesLimit` (daily proxy runs), `RunTimesLimit` (retries) and
  `RunTimeLimit` (per-run timeout) are also counts/times, not inventory targets

To decide whether to farm based on inventory, the decision has to be made outside. **终末地 does
have inventory data** (IMS, see HEADLESS.md); 鸣潮 has no equivalent.

### Nor is there a material index

`ForgeryTask` only understands **the index in the F2 list**, not material names, and there is
certainly no table of "which materials weapon X needs". To farm a specific weapon-breakthrough
material, you have to know yourself where that 凝素领域 sits in the F2 list and put that index in.

---

## Master copy vs working copy (this is the easiest thing to get wrong)

AUTO-MAS keeps its **own master copy** of the config for each script, and before every run it
overwrites the program's own working copy with the master.
**Editing the copy inside the program's directory achieves nothing.**

On the OK-WW side this is governed by the user config's `Info.IfQuickConfig` (**currently `false`,
since 2026-08-28**), and the scope AUTO-MAS takes over is the high-frequency fields of
`DailyTask` / `MultiAccountDailyTask`.

| Field | AUTO-MAS master (`wuwa` user's `Task`) | OK-WW working copy (`configs/DailyTask.json`) |
|---|---|---|
| What stamina is spent on | `WhichToFarm` = Tacet Suppression | `Which to Farm` = Tacet Suppression |
| 无音区 index | 1 | 1 |
| 凝素领域 index | 1 | 1 |
| 模拟领域 material | Shell Credit | Shell Credit |
| Daily echoes via 梦魇巢穴 | true | true |
| **Additional tasks** | **`["Check Weekly Garden"]`** | **`["Check Weekly Garden", "Auto Farm all Nightmare Nest"]`** |
| Exit after run | Not managed by the master | `Exit After Task` = true |

**Additional tasks are the only difference.** There are only two possible values for additional
tasks (`CHECK_WEEKLY_GARDEN`, `AUTO_FARM_NIGHTMARE_NEST`), so what the working copy has beyond the
master is "all nightmare nests". Because the master overwrites the working copy, **what actually
takes effect is 周常乐园 only**.

`Info.Mode` has three settings: `脚本` (use script-level config) / `用户` (use user-level) /
`直控` (use OK-WW's own config directly, no overwrite). `wuwa` is currently `脚本`.

---

## Who launches the game

| Script | Who brings the game up | Basis |
|---|---|---|
| MAA | AUTO-MAS starts the emulator | `Emulator.Id` |
| MaaEnd | AUTO-MAS starts the PC client | `Game.Path` points at `Endfield.exe` |
| OK-WW | **OK-WW itself** | On the MAS side `Game.Enabled=false`; on the OK-WW side `Basic Options.json` has `Auto Start Game When App Starts=true` |

OK-WW's game client path lives in its own `configs/devices.json`:
`pc_full_path = D:\Wuthering Waves Game\Client\Binaries\Win64\Client-Win64-Shipping.exe`.

So OK-WW's `Game.Enabled=false` **is correct; do not turn it on** — turning it on means both sides
try to launch the game.

## Master copy vs the script's own copy: your edits in the MaaEnd UI get wiped

2026-08-28: the user said 「我记得手动在 MaaEnd 上加过自动采集」, and the task list I had reported
did not contain it. Comparing the two copies made it obvious:

    D:\ark\maaend\config\mxu-MaaEnd.json          08-28 10:41  AUTO-MAS instance, 15 tasks (has AutoCollect)
    <automas>\data\<sid>\Default\ConfigFile\...   08-21 12:39  AUTO-MAS instance, 14 tasks (does not)

`AutoProxy.py:514-515` does a `shutil.rmtree` of `<maaend>\config` before every run and then
`copytree`s the master over. **A task added in the MaaEnd UI is gone on the next run.**
This is the same pattern as OK-WW, see [[maa-config-master-copy]].

For a change to survive, it has to be written into the **master**. The live task list has now been
synced into the master (which is how AutoCollect was saved), plus `AutoEssence` was added and
`ProtocolSpace` disabled.

### What is really going on with those six "decorative" MAS switches

`IfAutoCollect` / `IfTrialOfSwordmancy` / `IfAutoEcoFarm` / `IfSeizeEntrustTask` /
`IfResourceRecycleStation` / `IfPullCountCalculator` — **MaaEnd really does have these six
features**; MAS did not invent the switches. They became decorative because **the master's task
list does not contain those tasks**: MAS can only toggle tasks that already exist, it will not
create them. To use one, first add the task to the master.

## OK-WW's `-t` and 「周常」

`AutoProxy.py:257-258`: `okww_args = ["-t", str(TaskIndex), "-e"]`.
`-t` is the index into OK-WW's `onetime_tasks` (1-based), `-e` means exit on completion.

    1 DailyTask   2 FarmEchoTask  3 NightmareNestTask  4 TacetTask   5 ForgeryTask
    6 SimulationTask  7 MultiAccountDailyTask  8 MergeEchoTask
    9 EnhanceEchoTask  10 ChangeEchoTask  11 GardenTask

**TaskIndex = 1 → runs DailyTask only (the daily all-in-one). 周常乐园 is a separate task, number
11**, and can only be pulled in through DailyTask's 「附加任务」.

**There is no such thing as "remember that the weekly is done".** What exists is
`Check Weekly Garden`, whose original description reads
「领完每日奖励后检查每周乐园进度，不足 6000 分就跑乐园任务」 — it **checks the progress every
time**, it does not remember a result. It lives under 「附加任务」; before 2026-08-28 the MAS
quick-config overwrote additional tasks with `[]`, **which is why 周常乐园 had never once run**.
It is now back to `["Check Weekly Garden"]`.

The other two additional tasks were not added (they take a lot of time; enable them yourself when
you want them): `Merge Echo If discarded > 1000`, `Teleport and Farm 4C Echo`.

### Two keys in DailyTask that are easy to conflate

* `Which to Farm = "Forgery Challenge"` → **凝素领域** (in the `.po`: 「凝素領域」)
* `Which Forgery Challenge to Farm = 1` → 「**which** 凝素领域 **in the F2 list**」
* `Material Selection = "Shell Credit"` → the original reads
  「Resonator EXP / Weapon EXP / Shell Credit」; it is the material choice for the **模拟领域**
  task and has nothing to do with 凝素领域. **Do not read these two as one sentence.**

## Turning quick-config off ≠ the config directory stops being overwritten

2026-08-28, the user asked 「我不是已经关了快速配置吗，不是说不会覆盖吗？」 — I had earlier
conflated two separate things. They are separate:

| | Governed by | Current state |
|---|---|---|
| **The whole config directory being replaced** (`rmtree` + `copytree`) | **Unconditional**; `AutoProxy.py:514-515` has no `if` at all | **Happens every run** |
| **Fields being overwritten afterwards** (the `If*` switches / sanity tasks / locations) | `Info.IfQuickConfig` | Off, no longer overwritten |

`Info.Mode` only decides **which** master directory is copied from (`简洁` → `Default`, otherwise
→ the user UUID); it does not decide whether the copy happens (`AutoProxy.py:499-507`).

**So: anything changed in the MaaEnd / OK-WW UI gets wiped on the next run, whether quick-config
is on or off.** The only place a change survives is the master at
`<automas>\data\<scriptId>\<Default|uuid>\ConfigFile\`.

## MAA's `StageMode`

`Info.StageMode` is the stage configuration mode, and has only two kinds of value:

* **`"Fixed"`** — the stage and the potion count are taken directly from `Info.*`, see
  `AutoProxy.py:727-731`. The keys involved are `MAA_STAGE_KEY` (`constants.py`):
  `MedicineNumb / SeriesNumb / Stage / Stage_1 / Stage_2 / Stage_3 / Stage_Remain`.
* **A plan table's UUID** — goes through `PlanConfig.json`, taking a different stage and potion
  count per day of week (`AutoProxy.py:733-739`). `AutoProxy.py:421` also uses it to decide
  whether to take the plan-table branch.

Currently `Fixed`: `Stage=AT-4`, `MedicineNumb=999`, `SeriesNumb=0`.
**The copy in the plan table (every day `Stage='-' MedicineNumb=0`) is never read at all.**

## Post-battle auto-filter and the manual EssenceFilter rules are now aligned

The user asked for the two to match, both locking flawless only. `AutoEssence`'s post-battle
filter has been enabled and aligned item by item with the defaults in `maaend_essence.py`; the
values were read back and compared immediately after writing, and all 9 items match:

    input_language CN｜rarity6 ✓ rarity5 ✗ rarity4 ✗
    flawless ✓ pure ✗｜keep_future_promising ✗ keep_slot3 ✗ discard_unmatched ✗

Note that the sub-option names use a **different prefix** from the manual set: the post-battle
ones are all `EssenceFilterAfterBattle*` (e.g. `EssenceFilterAfterBattleFlawlessEssence`), while
the manual set is `FlawlessEssence`. Changing one does not sync the other.

## 2026-08-28: quick-config abolished, the relay now reads and writes the master directly

That day I first turned `IfQuickConfig` off for MaaEnd and OK-WW, on the grounds that "MAS's
coverage is incomplete and it manufactures silent failures". **That was wrong, because our own
relay works through MAS's user fields:**

| Relay feature | Which MAS field it writes | After quick-config is off |
|---|---|---|
| `garden.py` weekly-garden memory | OK-WW `Task.AdditionalTasks` | **Broken** |
| `sanity_plan.py` sanity plan | MaaEnd `Task.SanityTaskType` etc. | **Broken** |
| `annihilation.py` annihilation memory | MAA `Info.Annihilation` | Unaffected (MAA has no quick-config) |

**The relay was changed the same day so that it no longer depends on it** (the user's words:
「中继依赖你就改成不依赖呀，你怎么就这么会偷懒？」 — turning the switch back on is a detour, not
a fix):

* `garden.py` now rewrites `Additional Tasks to Run After Daily Task` in the master's
  `DailyTask.json`
* `sanity_plan.py` now reads and writes the master's `mxu-MaaEnd.json` — the sanity plan is simply
  which of `ProtocolSpace` / `AutoEssence` is `enabled`, and it also supports writing the
  sedimentation-point region
* Both locate the master directory via `config.master_config_dir()`, using a marker file
* When the master has no corresponding task, they now **refuse explicitly and say why**, instead
  of silently skipping

`IfQuickConfig` is now `false` for both, and the relay features were verified on the machine:
`sanity_plan.read()` returned 「基质刷取 → 枢纽区」, and `garden` read `done_week=2026-W35` with
`enforce()` deciding no change was needed.

### Two more misjudgements the same day

1. **OK-WW's `AdditionalTasks=[]` was not "MAS overwriting it with empty"**; `garden.py` turned it
   off deliberately — `state/garden.json` says `{"done_week": "2026-W35"}`, this week's garden is
   already done, and `Check Weekly Garden` gets added back automatically at 04:00 on Monday.
   I added that entry to the master on the strength of the wrong reading, which would have made it
   run pointlessly for six days this week; that has been reverted.
   **To check garden status read `garden.json`, not the config.**

2. **Those six MAS switches are not "decorative"; the tasks were lost in the config corruption on
   08-14.** In `mxu-MaaEnd.json.corrupt-20260814-054934` the AUTO-MAS instance has **17** tasks,
   including `SeizeEntrustTask` / `AutoCollect` / `ResourceRecycleStation` / `AutoEcoFarm` /
   `AutoEssence`; every config after that has only 14. Three have been restored from that backup
   (AutoCollect and AutoEssence were added back separately), and the master now has 19.

   **`TrialOfSwordmancy` (选剑演武) is not even in that backup**, so there is nothing to restore
   from. To use it, it has to be re-added in the MaaEnd UI and then **synced into the master**, or
   it will be gone again on the next run.

## MaaEnd task list and order (settled 2026-08-28)

| # | Task | Notes |
|---:|---|---|
| 1 | 🎁赠送干员礼物 | Give gifts and collect the return gifts |
| 2 | 🔧装备制造 | Auto-craft equipment of the specified tier |
| 3 | 🤝拜访好友 | Production assistance and intel exchange |
| 4 | 🎁基建任务 | Collect base products, restock, and collect/place clues |
| 5 | CreditShoppingN2 | Credit store |
| 6 | 🚚转交委托 | Accept and hand over commissions |
| 7 | 🛒售卖产品 | Sell the first page of goods for dispatch vouchers |
| 8 | 🌿环境监测 | |
| 9 | 📦自动囤货 | Buy elastic-demand supplies |
| 10 | 💰售卖弹性物资 | |
| 11 | 🏪购买稳定物资 | The ones that refresh weekly |
| 12 | 💊应急理智加强剂 | +40 sanity, **must come before any task that spends sanity** |
| 13 | ⚔️协议空间 (**off**) | Spends sanity farming 协议空间 — where the sanity used to go |
| 14 | 🗡️选剑演武 | Daily 选剑演武: auto card draw by expected value + auto combat |
| 15 | 🎱基质刷取 | 重度淤积点·枢纽区, spends sanity |
| 16 | 🧺自动采集 | **Monday/Thursday**, 15 routes, about 30 minutes, **needs to stay in the foreground and the mouse must not be touched** |
| 17 | 📅日常奖励领取 | Wrap-up, must be last |

**自动采集 was moved from position 1 to position 16**: it is the longest and the most fragile (it
needs the foreground and no mouse movement), so putting it first meant one stall took out all 16
tasks behind it. Moved to the back, the short tasks in front are already done. Placing it before
日常奖励领取 does not disturb the wrap-up.

`AutoCollectSchedule` has only `Monday` + `Thursday` ticked — **twice a week**, skipped the other
five days.

**`Run.RunTimeLimit = 40` is not a total-duration cap**; it is a stall timeout measured from the
**last log line** (`AutoProxy.py:877-880`). As long as MaaEnd keeps writing logs, a 30-minute
collection run will not be cut off.

## Morning queue order

`MAA → OK-WW → MaaEnd` (changed 2026-08-28; it used to be MAA → MaaEnd → OK-WW).
Reason: on Mondays and Thursdays MaaEnd takes an extra half hour for 自动采集, so putting it last
keeps it from blocking 鸣潮.
How to change it: `POST /api/queue/item/order`, where `indexList` is the **queue-item IDs**
arranged in the new order.

## 选剑演武: succeeds in the game, reported as a failure by MaaEnd — now disabled

It broke on 2026-08-28, the very day it was first enabled, and has been set to `enabled: false`.

**Symptom**: the task ran to completion in the game and the reward arrived
(`获得 武陵调度券 ×320000`, exactly the 「奖励数额 320000」 shown on the challenge screen), yet
MaaEnd still reported `任务失败: 🗡️选剑演武`.

**Root cause** (`maafw.log`): the recognition node `TrialOfSwordmancyEnemyCard5` scored only
**0.286** on template matching against a threshold of 0.7, so it could not identify the enemy
cards → `Tasker.Task.Failed`.

**Why it must be disabled rather than shrugged off as "the reward arrived anyway"**:

1. **When it fails it leaves the character inside the challenge arena.** The 基质刷取 that follows
   therefore failed as a knock-on — from the MXU log: `↩️返回大世界` (21 seconds, could not get
   out) → `✈️准备传送到最近锚点` (33 seconds, not in the open world) → task failed.
   **The root cause of that 基质 failure was this task, not the 基质 config.**
2. **It burns AUTO-MAS's retry budget** (`RunTimesLimit=3`). All three rounds that day were
   consumed by it.

**To re-enable it**, fix the recognition first: switch to `刷镀层` mode (which does not enter
combat and does not need to identify cards), or confirm that the game's resolution and graphics
settings match the upstream templates. **Do not turn it on before the recognition is fixed.**
