# Event stages without an operator in the loop - design

**Status: proposal (2026-09-13). Nothing here is built.** The user asked for a plan
first: 「能不能不依赖你然后自动打活动关，先思考方案」.

## What today's manual run actually consisted of

SR-EX-1〜6 of 月行水上, 40 minutes, 2026-09-13 16:41-17:25. Every step was one of
five kinds, and each has a mechanical replacement:

| Step today | How it was done by hand | Mechanical replacement |
|---|---|---|
| Bring the game up | `copilot-run.py startup` | same |
| Get to the EX map | 3 taps read off screenshots (banner → 殡仪堂 → stage label → 开始行动) | **per-event entry recipe** (see §2) |
| Pick a copilot | prts.maa.plus query, sorted by views, read `doc.details` | same query; rank by roster coverage (§3) |
| Handle a refused formation | read `reason`, tap 确认, run the next copilot | state machine (§4) |
| Know it worked / what it cost | look at the results screen; read sanity | OCR of the results screen and the sanity counter (§5) |

Nothing in the loop needs judgement once the stage is on screen. The two things
that do need a person are picking *which* day's sanity to spend (§6) and writing
the entry recipe for a new event (§2) - five minutes, once per event.

## 1. Where it runs

In the relay, as a stage like `collect_retry`: MaaCore driven directly through
`copilot-run.py`'s code (no MAA GUI), the emulator started by `emu-start.py`,
input by MaaCore's minitouch for battles and adb taps for the map. Started by
a phone order `event_stages` (with `mode: normal | raid`) or by the schedule
in §6. One run = "clear as many stages as the sanity allows, then stop".

## 2. Getting to the stage: the per-event entry recipe

MAA cannot navigate every event map (today's ASCENT tower: `copilot_list`
swiped 30 times and gave up). A generic navigator by OCR is possible but
fragile; the honest design is a tiny recipe per event, kept in
`state/event/<event>.json`:

```json
{"event": "act54side", "hub_taps": [[1440, 240], [1376, 696]],
 "stage_label_x": 240, "start_button": [1344, 840],
 "stages": ["SR-EX-1", "SR-EX-2", "...", "SR-EX-8"], "raid_button": [1180, 840]}
```

* `hub_taps` gets from the main screen to the EX map. The banner is always
  top-right; the second tap is the only event-specific pixel.
* Stage labels are a vertical list whose position scrolls; the runner takes a
  screenshot, OCRs the label texts (the relay has no OCR today - `rapidocr-onnxruntime`
  on the machine, ~30 MB, is the candidate) and taps the one it wants. Fallback
  when OCR is not available: `stage_label_x` plus the y read from a template
  match of the label box.
* Written by me at the start of each event (the first time I tap through it by
  hand, the taps are recorded). The user never touches it.

Alternative considered: **MAA's own `Fight` navigation** knows the stage codes
of most events and would remove the recipe entirely - but `Fight` starts the
battle with the current squad, and there is no "navigate only" option in
MaaCore. Not usable.

## 3. Choosing a copilot without guessing the roster

Today's formation failures were guesses: 结城理 (`Unavailable`) and 泡普卡
(`Missing`). MAA has an **OperBox** task that reads the owned-operator list
from the game (干员识别). Run it once a week into `state/operbox.json`; then:

1. `query?levelKeyword=<level id>` (level id from MAA's `resource/Arknights-Tile-Pos/levels.json`
   by stage code), keep `difficulty` matching the mode (normal: 1 or 3; raid: 2 or 3).
2. `get/<id>` for the top 6 by views; drop any whose `doc.details` contains
   无法自动 / 手动 / 剧情卡 / MAA 直接瘫痪.
3. Rank by (all named `opers` owned, all `groups` satisfiable, rating, views).
4. Keep the ranked list; the state machine walks it.

## 4. The per-stage state machine

```
for stage in recipe.stages (mode order):
    if progress[stage][mode] == done: continue
    if sanity < cost(stage): notify 「理智不够，停在 X」; stop
    tap into stage; if mode == raid: tap raid button, verify title turned red
    tap 开始行动 (or 开始突袭)
    for copilot in ranked(stage, mode):
        run single(copilot)
        if formation refused: tap 确认; continue            # no sanity spent
        if result screen shows 行动结束 with 3 stars (raid: 1 star): mark done; break
        if 任务失败: tap out; continue                        # no sanity spent (verified 09-04)
        if MaaCore timed out inside the battle (story dialog): mark 「要人工」; break
    else: notify 「X 所有作业都没过」; mark blocked
    back to map
```

Hard limits: never `use_sanity_potion`; at most 2 attempts per stage per day;
stop the whole run on the first unrecognised screen and send the screenshot.

## 5. Knowing what happened

* Results screen: OCR 「行动结束」 and count the star icons (samples: today's
  `g8/g11/g16/g20/g23/g30.png` in the session scratchpad - to be stored under
  `relay/tests/fixtures/event-ex/` as templates). Raid: one white star.
* Sanity: OCR the top-right `N/210` on the stage detail page before each stage;
  the stage cost is the `-N` next to 开始行动.
* Every run writes `state/event/progress.json` and ships an evidence bundle of
  its screenshots; the notification lists cleared / refused / stopped-at.

## 6. Whose sanity is it - the one decision that stays with the user

Clearing an event fully costs about 240 sanity (8 normal ≈ 110, 8 raids ≈ 130);
the daily queue spends all regenerated sanity on SR-5. So the runner can only
work by displacing farming. Proposed switch on the phone page, 「活动关优先」
(different from MAA's own `IfActivityFirst`, which farms an event stage):

* on: at 08:5x, before the 09:00 queue, the relay runs the event loop until sanity
  is below the next stage's cost, then hands over to AUTO-MAS as usual;
* off: nothing changes.

The 08:45 power-on gives only 15 minutes before 09:00; either the queue start
is moved to 09:15 on those days (config change, reverted automatically when the
event's EX list is fully done), or the loop runs at the 21:20 boot before the
21:30 MAA queue instead (evening sanity is usually near full). Evening is the
simpler choice.

## 7. Build order and effort

1. OperBox weekly snapshot + copilot ranking (pure API + one MaaCore task): ½ day.
2. Results/sanity OCR with today's screenshots as fixtures: ½ day.
3. Entry recipe + tap runner + state machine, tested against 月行水上 EX-7/8 and the
   eight raids (they still need doing, so the test is real work): 1 day.
4. Phone switch + evening scheduling + notifications: ½ day.

Each step is usable on its own; step 3 is where today's manual loop disappears.
