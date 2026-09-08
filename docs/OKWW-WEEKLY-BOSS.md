# Wuthering Waves weekly boss (战歌重奏)

Built 2026-08-31. This records the mechanism, the known defects and the evidence, so the
same investigation is not repeated.

## How it is made to run

The weekly boss is not a task of its own; it is one mode of `FarmEchoTask` (farming 4C
echoes):

* In `FarmEchoTask.json`, `Teleport to Boss = "Weekly Challenge"` (Chinese name
  **战歌重奏**)
* `Which Weekly Boss to Teleport` is a **positional index**, not a name. All OK-WW knows
  is that "there are 9 weekly bosses in total" (`total_weekly_number = 9`); it knows none
  of their names. The order is the order of the in-game F2 list, and it changes when a new
  boss is released.
* `Repeat Farm Count` = how many rounds to run. **Rewards can only be claimed 3 times per
  week**, so 3 is enough; set it higher and the 4th round cannot open the instance,
  `gray_start_battle` is not found, and the task exits on an exception.
* Hooked into `DailyTask.json` under `Additional Tasks to Run After Daily Task`, with the
  value `Teleport and Farm 4C Echo` (Chinese name **传送并刷取4C声骸**).

The AUTO-MAS route does not work: `OkwwTaskIndexValidator` only allows `[1, 7]` (dailies /
multi-account dailies), which cannot point at `FarmEchoTask`. So the additional-task hook
is the only way.

To run it once on its own: use `scripts/mac/run-one.sh OK-WW`. Underneath it calls
`/api/dispatch/start` with `{"taskId": <the OK-WW script id>, "mode": "AutoProxy"}`.
**`mode` accepts only `AutoProxy` / `ScriptConfig` / `Update`** (see `TaskCreateIn` in
`app/models/schema.py`); anything else is a 422.

## Ordering patch: the weekly boss has to come before stamina farming

Upstream, `DailyTask.run()` goes "nightmare nests → stamina farming → claim rewards →
additional tasks", and the stamina step's `must_use = 180 - used_stamina` eats all 180
first, leaving only 60 for the weekly boss that runs afterwards — enough to open one of
the three chests.

The `_STAMINA` patch in `okww_patch.py` moves `run_additional_tasks()` ahead of stamina
farming, and changes the farming call to not pass `daily` (→ `must_use = 0` → farm until
there is not enough stamina to enter), so whatever is left over after the weekly boss's
180 does not sit idle either.

Two things are both required: after the boss fight the character is not on the main
screen, so `ensure_main` has to run first; and without re-reading stamina, `used_stamina`
is still the value from before the boss fight and the dailies would farm another 180.

## How the reward is actually granted (only understood on 2026-09-01, with full-screen OCR)

**After the boss is beaten, walk up to the crystal and press F; the dialog below pops up,
and clicking 「确认」 spends 60 waveplates to claim:**

> 领取奖励需消耗60点结晶波片，请确认是否领取？　[取消] [确认]

That is the exact text read by full-screen OCR at 05:09 on 2026-09-01, **word for word**,
not an inference.

### The conclusion previously written in this document was wrong and is withdrawn

On 8-31 I wrote here that "**the reward is deducted as 60 waveplates on entry and granted
directly; there is no beat-it-then-open-a-chest step**" — **that is wrong**. The line
「结晶波片不足，无法获取奖励，请确认是否继续进入？」 is only **a warning before entering**
(you do not have enough waveplates, you will not be able to claim, enter anyway?), not a
charge. I read a warning as a charge, and on that basis wrote three patches and reported
twice.

The user pointed it out directly while watching the screen in the early hours of
2026-09-01: 「打完之后拿声骸直接一直重开去刷，这不是拿宝箱奖励」「这是声骸模式」. The log
confirms it completely: all three rounds went beat the boss →
`farm echo on the face` → dismiss the exit dialog → restart, with the weekly remaining
count staying at 3/3 and not a single waveplate spent.

**`FarmEchoTask` + `Teleport to Boss = Weekly Challenge` is a "farm 4C echoes" mode to
begin with** — teleport to the weekly boss and farm it repeatedly; the claim step is
simply not on that code path.

### What is done now

Claiming is inserted before "leave the instance after beating the boss":

```python
walk_to_treasure()            # walk up to the crystal, pressing F on the way
pick_f(handle_claim=False)    # press F once more, without dismissing the dialog
_o = ocr(full screen)         # recognize the dialog
if '领取奖励需消耗' in _o and '结晶波片' in _o:
    waveplates = read "N/240" out of the OCR text
    if waveplates >= 60: click_dialog_right_button()   # 确认
    else:                click_dialog_left_button()    # 取消, so a claim is not wasted
```

**Why not `has_claim_stamina()`**: it looks for the `claim_stamina_sign` template, and
measured on 2026-09-01 it **does not recognize this dialog** — the dialog is plainly on
screen and full-screen OCR read it word for word, yet the template still returns false.
OCR is the one that is measurably reliable on this path.

### The difficulty level must be the highest

`Boss Level` can be `50/60/70/80/90`. Upstream's description is
**"Choose the Lowest that Drop a Echo"** — that is the **echo-farming** line of thinking:
the lowest level that still drops an echo is the easiest to beat. **For the weekly boss it
is the exact opposite: the level determines the reward tier, so it must be the highest,
90.** The master config was 80; the user pointed out on 2026-08-31 that this was wrong.
The weekly boss gate now owns this setting and pins it to 90.

Our `FarmEchoTask` is used by the weekly boss only (daily echo farming goes through
`NightmareNestTask`, the nightmare nests), so there is no conflict of two uses fighting
over the same setting.

### Withdrawn inferences

I reached two wrong conclusions during the investigation; both are recorded here so they
are not repeated:

1. **"OK-WW cannot claim the weekly boss chest"** — does not hold; there is no chest in
   the first place.
2. **"The exception was swallowed by `logger.error(msg, e)` treating it as a printf
   argument"** — also does not hold. The signature in `ok/util/logger.py` is
   `error(self, message, exception=None)`; the second parameter is meant to be an
   exception, and internally it prints the stack via `exception_to_str(exception)`.
   **The full stack trace had been sitting in the log since 12:35**; I simply had not read
   it and went guessing instead. Going by my impression of the standard library I added
   `exc_info=True`, which that wrapper does not accept — an immediate `TypeError` that
   wrecked the whole 16:00 run. Lesson: a third-party logger is not `logging.Logger`.

## Why the morning run of 2026-08-31 did not do the weekly boss

The gate was not broken; **the config landed later than the queue did**. Modification
times of the master config:

| File | Written | Content |
|---|---|---|
| `FarmEchoTask.json` | 08-31 **08:06:23** | teleport=Weekly Challenge, index 1, 3 rounds |
| `DailyTask.json` | 08-31 **12:52:53** | only then did the additional-task list contain `Teleport and Farm 4C Echo` |

When the morning queue ran, 09:xx→10:14, the additional-task list **did not yet have** the
weekly boss entry, so `FarmEchoTask` was never invoked at all: `boss_string is [Lv`
appears **0 times** in the morning log, `GardenTask` has 990 lines, and stamina 240→160→80
all went to Shell Credit.

`WeeklyBossGate.enforce()` was running on every tick and its logic was correct too — on
the machine it was verified that the master config it read was complete and it returned
`False` (nothing needed changing). The real lesson is that
**after changing a config you have to confirm it landed in the master config before the
queue starts**; "I changed it" does not count, the file's timestamp does.

Config paths (the ones `master_config_dir` resolves to — the authoritative source):

```
D:\ark\automas\data\<uuid>\Default\ConfigFile\DailyTask.json
D:\ark\automas\data\<uuid>\Default\ConfigFile\FarmEchoTask.json
```

The two files under `D:\ark\okww\...\working\configs\` are **stale copies** (08-24 /
08-29). They are what the "OK-WW(本体)" section of `config-check.py` reads, and judging the
current configuration by them leads to the opposite conclusion. I misdiagnosed it that way
once, on 2026-08-31.

## When to catch up

2026-08-31 was a **Monday**, the weekly boss had just reset at 04:00, and the whole week
was still ahead. Stamina that day was down to 26, while one chest costs 60 —
**beating the boss and picking up echoes is free and unlimited; what is limited is the
chest (3 per week)** — so dispatching another run that day would only have fought for
nothing without opening a chest. The configuration is correct now, and the next queue with
full stamina will do all three by itself: 180 for the chests, the remaining 60 for Shell
Credit.

## The 16:52 run of 2026-08-31: behaviour after the fix

| Item | Result |
|---|---|
| Difficulty level | `left_click 推荐等级90` — **level 90 was selected** |
| Boss rounds | three: 16:52:56 / 16:54:02 / 16:55:19, each with `farm echo on the face` |
| Spinning | `farm 4c error` **0 times** (the previous run had 21 loops over 12 minutes) |
| Stamina | read as 27 after the run, **so it really was spent** (the previous run went 56→56, untouched) |

**Not yet proven**: whether all three rewards were actually claimed. There was no hard
reading taken before the run, so it can only be inferred, which does not count. The real
acceptance test is **a run with full waveplates** (180 for three claims): does the
waveplate count drop by 180.

### Two traps already stepped in, recorded here

* **The `present()` predicate has to change along with `new`.** I added a debug line to
  this patch but left the predicate as the same log line as before, so `_apply_one` decided
  it was "already in place" and returned, the new version **was silently not deployed**,
  and I sat waiting for that output in the log — a wasted run.
* **Stopping OK-WW is not just a matter of finding `python.exe`.** It runs inside
  `pythonw.exe` (`D:\ark\okww\data\apps\ok-ww\python\pythonw.exe ...\main.py -t 1 -e`), and
  after it is killed AUTO-MAS starts it again; `/api/dispatch/stop` does not clear the
  "task already running" state either. `wmic` no longer exists on current Windows, so use
  `Get-CimInstance` from `C:\Program Files\PowerShell\7\pwsh.exe`.

## The evening of 2026-08-31: three linked truths

Only after capturing the screen did the whole chain come out right; two rounds of earlier
inference are withdrawn. In order:

### 1. The reward is charged on entry, and the dialog comes **after** 「开启挑战」

The order is: team screen → (click 「开启挑战」) → the dialog
「结晶波片不足，无法获取奖励，请确认是否继续进入？」 → [取消] [确认].

Upstream's `click_team_challenge()` reads:

```python
self.wait_click_feature('team_start_challenge', raise_if_not_found=True, ...)
self.wait_click_skip_dialog_confirm()      # ← clicks the 「确认」 on that dialog
```

**「确认」 means exactly "go in even without the reward".** So when waveplates are short it
still fights three rounds of the boss and claims nothing.

My first two patch versions put the check **before** that click, when the screen was still
the team screen and OCR read an empty table (`v2 开启挑战前读到: []`, corroborated by a
screenshot from the same moment); it never hit once. v3 splits `click_team_challenge()`
into two steps, checks after the click, and if the dialog is there clicks 「取消」 and
raises `TaskDisabledException` to skip cleanly.

### 2. Not one claim had been made this week

The game screen says it outright: **本周剩余可收取次数：3/3**, 💎×60 per claim. That was
**read**, not calculated — I had previously inferred "2 already used" from stamina
consumption, which was wrong; those 120 points went to Shell Credit and the nightmare
nests.

Some good news alongside it: level 90 only took effect at 16:20, and all three claims were
still available, so **not one of them was wasted at level 80**.

### 3. "The run finished" is not "all claims taken"

`on_success` originally recorded `done_week` and removed the switch as soon as the task
finished. But how many claims one run can take depends on waveplates: 60 each, 180 for
three. Measured, Shell Credit farming ate the waveplates down to 1
(`current stamina: 1 not enough to continue`), and by the next morning they had only
recovered to about 147, enough for two claims — accounting by "finished = done" would lose
the third one forever, and silently.

The patch now OCRs 「本周剩余可收取次数」 before entering and writes it into the log, and
`on_success` reads that: greater than 0 means do not record it, leave the switch on; only
zero records it. If it cannot be read, prefer not to record (look again next run) — do not
use a guess to switch off something that is still usable.

### Stepping in the same trap again

The `present()` predicate has to change along with `new`. I had written this into the
document that very morning, and in the afternoon while making v2 I forgot the predicate
again: `_apply_one` decided it was "already in place" and returned, the new version was
**silently not deployed**, and I sat looking in the log for that debug output — another
wasted run. All three patches now key their predicate on a string unique to their own
version.

## Wrapping up: the measured numbers from the 18:58 run of 2026-08-31

| Item | Before the fix | After the fix |
|---|---|---|
| When waveplates are short | goes in anyway, fights 3 rounds for nothing | **skips once, exits cleanly** |
| `farm 4c error` | 3 lines (21 lines and 12 minutes of spinning on the earliest run) | **0 lines** |
| Wasted boss fights | 3 rounds | **0 rounds** |
| Weekly remaining count | unreadable, inferred from stamina (wrongly, twice) | **read directly as 3/3** |

Four local patches hold this result up, and none can be dropped:

1. **Ordering** (`_STAMINA`) — the weekly boss goes ahead of the daily stamina farming, or
   the 180 waveplates are eaten first.
2. **Skip when waveplates are short** (`_NOWAVE` v3) — the check must sit **after**
   「开启挑战」 is clicked, which is when the dialog appears; before that you read the team
   screen and OCR returns an empty table.
3. **Read the remaining count** (`_COUNT`) — so the relay accounts by the real count
   instead of "finished = done".
4. **Let the deliberate-skip signal through** (`_LETPASS`) —
   `teleport_to_configured_boss_and_prepare` wraps every exception into a `RuntimeError`,
   including the deliberate skip; `run()` never sees it and treats it as an error to be
   retried three times.

The difficulty level is pinned to **90** (of 50/60/70/80/90), owned by the weekly boss
gate, and written to **both** the master config and OK-WW's own copy — writing only the
master config does not take effect, measured.

### Not yet proven

The moment all three rewards actually land. The reward costs 60 waveplates on entry, 180
for three; on the evening of 2026-08-31 Shell Credit farming had eaten the waveplates down
to 1 and there was no making it up that day. Under the new "finished ≠ all claimed"
accounting the switch stays on, claiming one whenever there is enough, filling up over the
course of the week.

## It works: the complete evidence from 07:27 on 2026-09-01

| Time | Evidence |
|---|---|
| 07:26 | read **3/3** before entering |
| 07:27:47 | `周本领奖：认出弹窗，点确认` |
| 07:27:49 | `周本领奖：波片不够，动用备用体力` |
| 07:27:57 | `周本领奖：已点确认` |
| 07:28 | on screen 「**挑战成功**」: ×450, ×180, Shell Credit ×54000, ×10, ×3, ×8 |
| 07:33 / 07:36 | read twice more, **2/3** both times |

52 waveplates + 34 reserve − 60 ≈ 1 left, so **60 really was deducted**.

## How the whole thing runs (the same rhythm as Annihilation)

### Automatic reset Monday 04:00

`WeeklyBossGate` and Annihilation **share** `annihilation.week_key` (the boundary is Monday
04:00; before 04:00 still counts as the previous week). At the boundary `done_week` no
longer matches the current week and the switch comes back on by itself.

### Ordering: the weekly boss goes before the stamina instances

The actual order in `DailyTask.run()` (read on the machine):

```
ensure_main → open_daily → run_additional_tasks (the weekly boss is here)
            → farm_tacet / farm_forgery / farm_simulation (stamina instances)
            → claim_daily → claim_mail → claim_battle_pass
```

Upstream had it as "stamina instances → additional tasks", which lets the dailies eat the
180 waveplates first, leaving nothing for the weekly boss. The `_STAMINA` patch moves
`run_additional_tasks()` to the front.

### Accounting: only three claims count as done

**"The run finished" is not "all claims taken".** One claim is 60 waveplates, three is 180,
and when waveplates are short a single run only gets one or two. So `on_success` **reads
the 「本周剩余可收取次数」 reported by the game screen** (the patch OCRs it before entering
and writes it into the log) and only writes `done_week` when it reaches zero; greater than
zero means do not record it, leave the switch on, and the next run carries on claiming. If
it cannot be read, prefer not to record — do not use a guess to switch off something that
is still usable.

### The claiming step

```
beat the boss → walk_to_treasure() (walk up to the crystal, pressing F on the way)
              → pick_f(handle_claim=False) (press F again, without dismissing the dialog)
              → full-screen OCR recognizes 「领取奖励需消耗60点结晶波片，请确认是否领取？」
              → click_dialog_right_button() (确认)
              → if gem_add_stamina pops up (asking whether to use reserve stamina) → dismiss it
```

**`has_claim_stamina()` must not be used**: it looks for the `claim_stamina_sign` template,
and measured it does not recognize this dialog — the dialog is plainly on screen and
full-screen OCR read it word for word, yet the template still returns false. **On this path
OCR is reliable and the template is not.**

### Difficulty locked at 90

`Boss Level` can be 50/60/70/80/90, and **the weekly boss must use the highest** (the level
determines the reward tier). Upstream's description "Choose the Lowest that Drop a Echo" is
the **echo-farming** line of thinking and is the exact opposite of what the weekly boss
needs. The weekly boss gate owns this setting and writes it to **both** the master config
and OK-WW's own copy (writing only the master config does not take effect, measured).

## The two easiest wrong turns when investigating

1. **"It cannot win the fight" is an illusion.** Seeing 「挑战失败」, do not blame character
   investment first: if the log shows `target_enemy failed` and `boss_string is []` within
   seconds of `enter combat`, then **the screen cannot be read** (WGC capture failed and it
   fell back to BitBlt, which grabs black frames) — the fight was not lost. That is exactly
   what happened on 2026-09-01 after I killed and restarted the game; restarting OK-WW so
   it re-initializes capture fixed it on the first try.
2. **Do not burn all the waveplates for the sake of testing.** While testing the weekly
   boss, stop the daily stamina farming with
   `C:\ProgramData\ark-relay\state\no-stamina-farm.flag`, and delete it afterwards to
   restore. See [[never-burn-the-resource-youre-testing-for]].
