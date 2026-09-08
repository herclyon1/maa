# Wuthering Waves daily run: every step from power-on to finish

**Every line in this file was read off the machine as it stood at 2026-08-27
08:20** — not copied from the upstream README, and not from memory. The config
names are the key names in `working/configs/*.json`; the source line numbers are
the line numbers of the copy on the machine (the one carrying our four patches).

When the config changes, come back and update this file, or the whole thing has to
be looked up from scratch next time.

## 0. Who starts it, and when

| Time (Beijing) | Who | What it does |
|---|---|---|
| 08:45 | smart plug powers on | the box gets mains power and boots |
| after boot | the `ark-relay` service | pre-update: brings up MAA / MaaEnd / AUTO-MAS / OK-WW in turn to check for updates, then re-applies our four patches |
| 09:00 | AUTO-MAS queue 「早班」 (morning shift) | 1. MAA → 2. MaaEnd → **3. OK-WW** |
| 21:30 | AUTO-MAS queue 「晚班」 (evening shift) | MAA only |

OK-WW's entry in AUTO-MAS: `RootPath=D:\ark\okww`, `Game.WaitTime=60`,
`RunTimesLimit=3` (at most 3 retries on failure), `RunTimeLimit=120` minutes.
**The evening shift has no Wuthering Waves**; Wuthering Waves runs once a day, on
the morning shift only.

## 1. Once OK-WW is up

In `Basic Options`:

* `Auto Start Game When App Starts = true` — OK-WW starts the game itself the
  moment it launches
* `Kill Launcher After Start = true` — kill the launcher once the game is in
* `Auto Resize Game Window = true`, `capture = WGC`, `interaction = PostMessage`
* The real game process is `Client-Win64-Shipping.exe`
  (`Wuthering Waves.exe` is only a shell; do not use it to decide whether the game
  is alive)

Login is handled by `AutoLoginTask`.

> **The keybinds have to be the game's defaults**: `Game Hotkey` is currently
> `Echo=q / Liberation=r / Resonance=e / Tool=t / Jump=space / Dodge=lshift`.
> OK-WW's `load_hotkey()` **only actually writes Echo and Liberation**; the
> Resonance / Tool lines are commented out upstream — so if the resonance key was
> changed inside the game, the script silently gets nothing. The 2026-08-26
> "can't farm stamina" was exactly this.

## 2. The daily task itself (`DailyTask.run`, lines 77–139 on the machine)

```
78   validate_additional_tasks()      # check the additional tasks' preconditions first
80   WWOneTimeTask.run(self)          # common opening
82   ensure_main(180)                 # make sure we are on the main screen

88   used_stamina, daily_reward_ready = open_daily()
89   need_stamina   = daily reward not claimed AND stamina used < 180
90   need_nightmare = daily reward not claimed AND Which to Farm != 声之领域

96   ── Nightmare Nest (get the daily echo)
117  ── farm stamina
133  run_additional_tasks()           # ← our patch: moved ahead of claiming rewards
135  claim_daily()                    # claim the daily activity rewards
136  claim_mail()                     # claim mail
138  claim_battle_pass()              # claim the battle pass
139  print 「Daily Task Completed」 and notify
```

### 2.1 The Nightmare Nest section (lines 96–115)

The current config is `Farm Nightmare Nest for Daily Echo = true` and
`Which to Farm = Forgery Challenge` (≠ 声之领域), so this section **does run**, and
it goes through `run_capture_mode()` (lines 90–103), not the full `run()`:

```
while nest := _next_nest_with_progress():
    combat_nest(nest)
    if _capture_success:      # one echo dropped, leave
        break
```

* `NightmareNestTask`'s config is
  `Which to Farm = ["Tacet Discord Nest"]` and
  **`Only Farm These Nests = "落渊南丘"`**
* `find_nest()` only picks nests that are **not yet full**
  (`numerator != denominator`), and `_wanted_nest_rows()` then narrows the range to
  the single spot 落渊南丘.
* **So: 南丘 not full → go in and fight; 南丘 full → `get_nest_to_go()` returns
  empty → the while loop never runs once → the whole section is skipped.** That is
  exactly the wanted behaviour.
* The point is to get **one** daily echo toward the activity count, not to farm
  南丘 to the cap.
* If the count did not go up after a fight, that spot is skipped permanently
  (`_next_nest_with_progress`, our patch), instead of re-entering on the spot every
  two minutes forever the way upstream does.
* This section is wrapped in a try/except: a blown-up nest no longer takes the
  reward claiming after it down with it (our patch).

### 2.2 The stamina section (lines 117–128)

`Which to Farm = "Forgery Challenge"` → goes to `ForgeryTask.farm_forgery()`, and
`Which Forgery Challenge to Farm = 1` → **凝素领域·陨翼云渊（迅刀）**. It farms until
180 stamina is spent.

### 2.3 Additional tasks (line 133)

`Additional Tasks to Run After Daily Task = ["Check Weekly Garden"]`
— the weekly garden only. `Monthly Card Config` is separate:
`Check Monthly Card = true`, `Monthly Card Time = 4` (claim the monthly card after
04:00 each day).

## 3. Finishing

`DailyTask`'s `Exit After Task = true` → quit the game when the task is done;
`Basic Options`' `Exit App when Game Exits = true` → OK-WW quits when the game
does. AUTO-MAS sees the process end and counts that queue entry as complete.

## 4. What we added on top of upstream

Four patches, re-applied by `ark_relay/okww_patch.py` after every OK-WW auto-update
(an upstream update overwrites the whole of `src`). Details in
[OKWW-PATCHES.md](OKWW-PATCHES.md).

1. **Reward order** — additional tasks moved ahead of `claim_daily`, otherwise the
   rewards from a finished weekly garden are never collected
2. **A failed domain no longer drags down the daily task** — `DomainTask`'s
   exception no longer propagates all the way up into `DailyTask.run`
3. **The nest task** (whole file replaced, with a hash guard) — resume farming /
   no spinning in place / **a specific spot can be named**
4. **Main-DPS starvation fallback** — `BaseCombatTask`

Upstream v3.6.6 has **none of these four** (relative to beta.1, v3.6.6 only changed
`pyproject.toml` and `requirements.txt`), so we still have to apply them ourselves.
