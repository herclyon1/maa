# MAA: event stages and SSS (保全派驻)

**Why this file exists**: on 2026-08-23 running event stages took an entire day,
and all of that time went into "I don't understand this, I'm just poking at it".
The operator, 2026-09-04: 「要不然的话，每次都是重搞。」
So what follows is an **order of operations you can just follow**, not background
reading. Read the relevant section through before touching anything.

Keep one sentence in mind — all three crashes of that day were the same thing
wearing different clothes:

> **MAA does not find its own way there. Put the game on the screen it wants
> first, then let it take over.**

---

## 1. Event stages

There are two completely different jobs here. Decide which one you want first.

### 1. Only farming an event stage for materials -> change config, leave copilots alone

This path runs through AUTO-MAS's daily queue; the 「明日方舟」 block on the phone
page can change it.

| What you want | Which field | Watch out |
|---|---|---|
| Farm one event stage every day | `Info.Stage` = the stage code (e.g. `AT-4`) | **the stage stops existing the moment the event ends**, and a fixed stage pointed at it makes every later round fail |
| Farm the event stage while the event is on, fall back automatically when it ends | `Task.IfActivityFirst` on + `Task.ActivityStageIndex` | the index counts **position from the top of the event stage list; the first stage is 1**, not 0 |
| How many potions that round drinks | `Task.ActivityMedicineNumb` | **this is a separate place from the regular `Info.MedicineNumb`**; changing the wrong one is the same as changing nothing |

* The culprit in the 2026-08-26 "826 incident" was exactly this: `活动关优先` was
  on while the index was misunderstood, so it farmed the wrong stage and burned
  potions on top. Before changing anything, run
  `winrun.sh --py scripts/mac/lib/effective_config.py` to see the copy that is
  **actually in effect**.
* Current settings: fixed `1-7`, 活动关优先 `false`, potions `0`.

### After switching to a new event's stage: **update MAA first, or Fight rejects it outright**

Changing `Info.Stage` (say from `1-7` to `SR-5`) is not the end of it. Whether MAA
recognises that stage code depends on its **resource version** — after a new event
goes live you have to update to get that stage data.

What "not recognised" looks like (measured 2026-09-04): `append_task` returns
**task id 0**, `asst.start()` still returns True and "finishes" in a second, and
nothing happened. `D:\ark\maa\debug\asst.log` spells it out:

```
Unknown task: SR-5 / Task SR-5 not found
The stage name is not in invalid, or is not main line stage SR-5
Cannot set stage SR-5
```

**The front door for verifying it** (no potions, no wasted sanity):

```bash
scripts/mac/winrun.sh --timeout 400 --py1 scripts/windows/copilot-run.py \
  'C:\ProgramData\fight.log' fight SR-5 1
```

`fight` mode hard-codes the potion count to 0. In the log, look at the number
after `Fight 已下发 id=`: **0 means it was not recognised, non-zero means it was**.
A real clear also prints
`StageDrops ... "stageCode": "SR-5" ... "stars": 3`; only then is it verified.

**The front door for updating is the relay's own pre-update.** Do not go replacing
`resource/stages.json` by hand — that one file is not enough, MAA also looks up the
stage's navigation definition in tasks.json and will reject it anyway:

```python
sys.path.insert(0, r"C:\ProgramData\ark-relay")
from ark_relay import preupdate
preupdate.run_maa(Path(r"D:\ark\maa"), budget_s=600, problems=[])
```

Run it with `winrun.sh --py1` (it needs an interactive desktop). Measured
2026-09-04, v6.17.0 -> v6.17.1: `stages.json` went 803222 -> 807286 bytes and Fight
recognised SR-5 immediately.

Starting MAA by hand requires the flag, otherwise it starts running the moment it
launches:
`scripts/mac/wingui.sh launch 'D:\ark\maa\MAA.exe -- --skip-startup-auto-run'`

### The event's reward popup: it blocks copilot mode, not Fight

月行水上 drops a tarot card on every clear and plays a big animation **on the map**.

* **Copilot mode gets stuck dead behind it**: after each stage it goes back to the
  map to find the next one, the popup is plastered over the map, and MAA sits in
  `Copilot@ChapterSwipeToTheRightAndPlot` unable to find the stage. It stalled
  twice while running SR-5〜SR-8 on 2026-09-04; **dismissing the popup by hand
  makes it pick up again immediately**.
* **Fight mode is unaffected**: 终端 → 活动 → 关卡 → 打 → 结算 → 「再来一次」, never
  going back to the map. In that run it dropped the tarot card 「节制」 and MAA
  still finished the results screen normally.

So farming an event stage from the queue (which goes through Fight) does not care
about this popup; only manual back-to-back copilot runs need watching.

### When navigation suddenly fails, check whether it got logged out

If `SwipeToStage` swipes a few times and then goes quiet, sitting on some other
stage page, **take a screenshot first and check for
「登录认证已失效，请重新登录」**. The account being logged in elsewhere kicks the
emulator off, the screen stays on the old UI, and it looks exactly like broken
navigation. Run `copilot-run.py <log> startup` once to log back in — see memory
`game-relogin-is-just-restart`.

### 2. Actually clearing a stage (EX, 突袭, story stages) -> use a copilot

#### Where copilots come from

* **The 神秘代码 from prts.plus**, pasted into MAA's auto-battle box; or
* **local JSON**: `D:\ark\maa\config\copilot\` (48 of them) and MAA's own
  `resource\copilot\`.
* Measured 2026-08-22: `prts.plus` and the `prts.maa.plus/copilot/get/<id>`
  endpoint MAA actually calls are both reachable from the game machine;
  **`prts.wiki` returns 403 from that machine**. Do not conflate the two.

#### Pulling copilots in bulk over the API (curl straight from the Mac works, no browser needed)

```bash
# All copilots for one event: levelKeyword is the event code (e.g. act54side)
curl -s 'https://prts.maa.plus/copilot/query?page=1&limit=100&levelKeyword=act54side'

# Download one complete copilot
curl -s 'https://prts.maa.plus/copilot/get/<id>'
```

**The two endpoints return different things, and using the wrong one costs half an
hour** (learned the hard way 2026-09-04):

| Endpoint | What is in `content` |
|---|---|
| `query` | only `doc` / `opers` / `groups` / `stage_name` — **no `actions`** |
| `get` | the full copilot, **including `actions`** (the real deployment actions live here) |

`query` is for the listing page; the body of the copilot is trimmed out. Save its
`content` to a file and feed it to MAA and **MaaCore rejects it at the
`append_task` stage**: the returned task id is **0**, while `asst.start()` still
returns True and "finishes" in a second, having done nothing.

The front door for debugging this is **`D:\ark\maa\debug\asst.log`**, which says it
plainly:

```
[ERR] Json parse failed <path> invalid map<K, T> key
[ERR] CopilotConfig parse failed
[ERR] asst::Assistant::append_task | invalid params: {...}
```

**`append_task` returning 0 means the parameters were rejected.** Do not guess
which field — read those three lines first. On 2026-09-04 I tried 11 parameter
combinations one after another and every one was rejected, when a single log line
already said the problem was the copilot file.

Pick copilots by `views`, and look at `rating_level` (out of 10) and
`rating_ratio`. The author writes in `doc.details` whether the stage can be
automated at all, and **that sentence has to be read** — for 月行水上's SR-4, the
authors of all five copilots said the same thing: MAA gets stuck on the story, it
has to be done by hand.

#### Which screen to start from — the main source of last time's crashes

| Mode | Must be sitting on this screen |
|---|---|
| single copilot | the squad screen, the one with **开始行动** |
| multi-copilot / battle list | the **map screen the stage is on**, not the squad screen |
| 保全派驻 | finish the manual prep, stop at **开始部署** |
| 悖论模拟 | **turn off 自动编队**, pick skills by hand, stop at **开始模拟** |

In multi-copilot mode every stage has to be in the same area (reachable by swiping
the map left and right only). Not enough sanity, a loss, or any non-3-star result
each stop the queue.

#### The recipe that got an event EX cleared (measured working 2026-08-23)

1. Run MAA's `StartUp` task first and let it bring the game up to the main screen
   itself. **Do not try to time the boot by hand.**
2. **Tap in by hand** to the event map (banner → section). This step is safe
   precisely because step 1 guarantees the starting screen.
3. Then run `copilot_list`; inside the event map it can navigate.
4. On `BattleFormationTask` + `reason: Missing`, switch to the next copilot for
   that stage.

Four assumptions that turned out wrong. Do not repeat them:

| What I assumed | What is true |
|---|---|
| `filename` mode finds its own way | it does not. It only knows the squad screen; started anywhere else it fails right at `BattleStartAll`. The one that navigates is `copilot_list` |
| you can navigate to an event stage from the main screen | you cannot. It goes leafing through main-line chapters — 224 swipes and 100 chapter flips looking for AT-5, once |
| pressing back a few times returns to a neutral screen | back on the main screen pops 「是否确认退出游戏」, and the tap used to dismiss that opened the event shop, twice |
| MAA can navigate to any stage | it cannot find this event's **EX** map. Tap over by hand and then use `filename` mode; that worked first try |

#### When 自动编队 is refused — read `reason`, not `why`

The outer layer always says `"why": "OperatorMissing"`; the useful field is
`reason` inside `details.opers`:

| `reason` | Meaning | Fix |
|---|---|---|
| `Unavailable` | the operator **is owned, and was found**. The copilot declares a training requirement (usually mastery level) that is not met | set **`ignore_requirements: true`** |
| `Missing` | MAA did not find this operator in the list at all | **remove that operator's 「特别关注」** (the official FAQ's own words) |

* `ignore_requirements: true` is the **default thing to do**: training requirements
  are the copilot author's preference, not a restriction of the game itself.
  On 2026-08-23 all three refused operators were in fact owned, and with that
  parameter the same copilot filled all six slots and started.
* `Missing` **does not mean the operator is absent**. That is how it was read last
  time, and two usable copilots were thrown away for nothing.
* When debugging, **do not truncate the callback log** — the field that separates
  these two cases sits past character 260.

#### When in-stage story blocks MAA: MAA cannot recover, deploy by hand

Some stages **pop in-stage dialogue repeatedly during combat** (月行水上 SR-4 plays
one every time a 告解车 arrives, with a 「往左/往右」 choice). Copilot authors
normally say so in `doc.details` — for SR-4 **all five** authors independently
wrote it: 「本关没办法自动」「MAA 直接瘫痪」「被剧情卡住没招」.
**Take that sentence at face value.**

**Why MAA cannot recover** (measured 2026-09-04, all three orderings tried): after
it issues the first `CopilotAction: Deploy` it enters
`Copilot@WaitUntilEndOfAction`; the moment story covers the battlefield it can no
longer recognise the state, and **exactly 58 seconds later** it throws
`TaskChainError` and exits.

* Adding `pre_delay` to the copilot **does nothing**: at 25 / 60 / 100 seconds the
  timeout still fired 58 seconds after the Deploy went out — that timeout and
  pre_delay are unrelated, and waiting does not push it back.
* **Clearing the story before starting MAA does not work either**: MAA abandons the
  current attempt and navigates into the stage again from the map, and the story
  plays through all over again.
* **Clearing the story right after it issues Deploy does not work either**: cleared
  in 16 seconds with 42 still to go before its timeout, the screen long since
  clean, and it still did nothing until the timeout.

**So these stages have to be deployed by hand**, and the tooling is already built:

| What you need | What to use |
|---|---|
| convert a copilot's `location: [x, y]` into screen pixels | `scripts/mac/lib/tilepos.py` (a transcription of MAA's `TileCalc2`) |
| the stage's tile table and camera parameters | on the game machine, `D:\ark\maa\resource\Arknights-Tile-Pos\<stage>-*.json` |
| actually dragging an operator onto a tile | `scripts/windows/deploy.py` (through MAA's bundled MaaTouch) |

**Three things a deployment needs** (all learned the hard way; miss one and the
operator does not go down):

1. **Start by pulling the operator straight up out of the card slot** (about 120px),
   then move toward the tile. Dragging diagonally off the card leaves the card strip
   on the first movement and the game reads it as scrolling the operator list.
2. **Do it in one continuous touch.** "Drag to the tile and release, then press
   again to pick a facing" is wrong — the second press cancels the deployment.
3. After the release the game sits on the **facing** screen, and that flick can be
   finished with an ordinary `adbdo.sh swipe`. Operators on high ground are **drawn
   about 115px above the tile centre**, so the facing flick has to start from the
   drawn position and go outward.

To tell whether it went down: check whether **the operator card is still there**,
whether cost was deducted, and whether "剩余可放置角色" went down.

**Do not deploy with `adb shell input swipe`**: it is a constant-velocity straight
line and the game does not accept it. `input motionevent` needs Android 11+, and
this LDPlayer is **Android 9**, which does not have that command.

**Retrying costs no sanity** (measured against the sanity number on 2026-09-04):

* **Abandoning the operation refunds it in full**; the dialog says
  「放弃行动将会恢复 N 理智（全部返还）」.
* **Losing the stage does not deduct it either.** At the time I saw no refund
  marker next to "任务失败" on the results screen, assumed it had been deducted,
  and wrote that into this document — **that was wrong**. Reading the sanity back
  on the stage page afterwards: 169 after the first 5 stages, 185 an hour and
  forty-eight minutes later, which is 2 points off pure natural regeneration
  (1 per 6 minutes) — a dozen-odd trips in and out of SR-4 cost nothing.
  **Do not infer it from how the results screen looks; go back to the stage detail
  page and read that number.**

So these stages can be retried freely. The stage detail page also has a 「演习」
button that likewise costs no sanity; the battlefield is identical to the real
thing, and the advantage is not having to sit through the results animation, which
makes coordinate tuning faster.

#### 突袭 (the second difficulty of an EX stage)

* Switch with 突袭模式 at the bottom of the stage detail page; the title turns red,
  an extra condition appears, and the button becomes 开始突袭.
* **突袭 finishes at one star, and that is correct** — 突袭 has no three-star. Using
  three stars as the success test reports a perfectly good round as a failure.
* Copilots declare which they support with `difficulty`: `1` normal, `2` 突袭,
  `3` either, `0` unspecified.
* The copilot site numbers 突袭 variants separately, in the form `act44side_ex08#f#`.

---

## 2. SSS (保全派驻)

### Current season

**#12 废都安保派驻**, deployment period ends 2026-12-16 03:59. Two maps:

* **荒废灯塔** (审判庭)
* **日达诺夫园区** (索罗科夫集团)

### MAA ships the copilots; no need to go looking online

Under `D:\ark\maa\resource\copilot\` (checked on the machine 2026-09-04):

| Stage | Copilot file | Core operators | 导能元件 | 战术装备 |
|---|---|---|---|---|
| 荒废灯塔 | `SSS_荒废灯塔-重岳核v2.0（兼容应急）.json` | 重岳、纯烬艾雅法拉、塞雷娅、拉普兰德 | 战地援护无人机 | 狙击 B, the rest A |
| 荒废灯塔 | `SSS_（新）荒废灯塔_圣聆初雪+遥_战地援护无人机.json` | 圣聆初雪、遥 | 战地援护无人机 | 术士 B, the rest A |
| 荒废灯塔 | `SSS_荒废灯塔_浊蒂纯艾版.json` | 塞雷娅、号角、澄闪、提丰、铃兰、纯烬艾雅法拉、浊心斯卡蒂 | 战地援护无人机 | item 3 B, the rest A |
| 日达诺夫园区 | `SSS_日达诺夫园区_圣聆初雪+遥+斩业星熊_可充能督战音响.json` | 斩业星熊、圣聆初雪、遥 | 可充能督战音响 | 术士 B, the rest A |

日达诺夫园区 **has only this one**. For 荒废灯塔, pick whichever one you can field
the core operators for.

### Check for 全权委托 first — if it is there, do not play it by hand

**This is the biggest time saver; take it first.** (The operator, 2026-09-04:
「如果有自动通关就用那个东西。」)

* Unlock condition: **clear at least one floor within the current deployment period
  with a squad containing no support unit**; only then does that map's 全权委托
  light up. Maps never cleared carry a lock on it.
* Cost: **2 常态事务代理卡** per use, and the reward is based on the **highest floor
  reached during this period**.
* So the order is: play it by hand once to push the floor count to 6/6 (or as far
  as you are happy with), then for the rest of the same period use 全权委托 only —
  2 cards, full reward, a few seconds.
* Measured 2026-09-04: 荒废灯塔's best this period is floor 6; one 全权委托 returned
  数据增补条 ×20 and 增补仪 ×10 in a few seconds.

Where it is in the UI: bottom-right of the stage detail page, the small square to
the left of 「开始保全作战」. Ticking it puts a `PRTS -2` badge on the button;
pressing it opens a confirmation dialog listing the expected rewards and how many
cards are left.

### Four ways SSS differs from an ordinary copilot

1. **`自动编队` does not work for SSS** (the official docs' own words). The squad has
   to be built by hand.
2. You have to **finish the initial mission prep by hand**, all the way until
   **开始部署** appears in the stage detail, before MAA can take over.
3. **导能元件** has to be the one the copilot specifies (the 导能元件 column above).
4. **战术装备** follows the copilot's A/B table.

How to pick the filler operators (the same set of requirements repeated across
several copilots' notes):

* Training **preferably E2, at minimum E1 max level**; prefer **low cost**.
* Do not pick skills that **only fire once** (山's S2 kind), skills that **only
  trigger on contact** (锏's S3 kind), or skills with a **strange attack range**
  (黑's S3 kind) — otherwise MAA fires skills nonstop.
* Medic preferably 流明, sniper preferably a fast-shot sniper, vanguard has to be
  able to hold a lane.
* Do not bring extra supporters, and do not bring 小车.

### How to get to 保全派驻 (do not go through the to-do list)

**终端 → the 「常态事务」 tab along the bottom → 保全派驻 → 进入.**

The bottom navigation has six cells left to right; 常态事务 is the one at x≈930. Do
not use the shortcut in the home screen's to-do list: its contents change, and on
2026-09-04 I tapped the remembered coordinates and landed in **集成战略**, one tap
away from 「放弃本次探索」. If you do land there, back out with the top-left back
button; the run is not lost.

### Collecting rewards: there are three places, do not stop at one

1. **周期任务** (the button in the top-right of the list page): clear a given map,
   reach floor N this many times — collected one at a time.
2. **周期清理记录** (the block in the **top-right** of the stage page, labelled
   BEST RECORD n/6): it opens the 1/6…6/6 milestone rewards, with **一键领取** at
   the top. When something is collectable, that block carries an **orange diamond**
   badge in its top-right corner. On 2026-09-04 I missed this one and only found it
   after the operator pointed it out; it paid out 模组数据块 ×5, 数据增补仪 ×10 and
   数据增补条 ×30 in one go.
3. **报酬进度条** (bottom-left of the stage page): 数据增补条 / 增补仪 are
   **credited automatically**. Those two bars are only this period's cap progress;
   「查看酬劳明细」 is explanation only, with no collect button.

### 全权委托: the button is dead when the reward is 0

Once the cap is full, opening 全权委托 again shows all ×0 under 「预计可获得」, and at
that point **确认使用 does not respond** (「取消」 in the same dialog does respond, so
it is not that the tap failed — the game is refusing to let you waste cards). To
farm more 周期任务 counts you have to actually play a round.

### The manual prep, step by step (walked end to end on 2026-09-04; follow this)

1. Deployment list page → tap the map's **thumbnail** (tapping the title bar does
   nothing).
2. Stage detail page → **开始保全作战**.
3. **Step 1, 选定向导能元件**: pick the one the copilot wants (table above), then
   **确认选择** at bottom right.
4. **Step 2, 战术装备**: tap the eight cells per the copilot's A/B table.
   The order is `先锋 重装 术师 辅助 / 近卫 狙击 医疗 特种` — that order was
   cross-checked against the equipment arrays of two copilots, not guessed.
   Then **装备确认** at bottom right.
5. **Step 3, 首批作战小队选任**: **快捷编队** at top right opens the picker →
   **清空选择** at bottom left → **职业** at top right expands the class bar → pick
   enough of each class → **确认** → back on the squad page, **阵容确认**.
6. The first visit to a map pops a tutorial page; **关闭** at top left.
7. That leaves you on the screen with the **开始部署** button.
   **MAA takes over from here.**

Two traps in the picker:
* The grid runs **by column**: position n is in column `⌈n/2⌉`, odd numbers on the
  top row and even ones on the bottom. Already-selected operators get moved to the
  front, so **always tap the position "number already selected + 1"** — after that
  tap it does not move, and neither does anything after it.
* Horizontal scrolling **has inertia**, and one flick overshoots. To move columns
  precisely use **slow small steps** (distance 180 pixels, duration 900 ms), one
  step per column.

### Two ways to hand over to MAA

* **GUI**: 自动战斗 → import the local JSON copilot → check the stage name is right
  → start.
* **Headless**: call MaaCore's **`SSSCopilot`** task directly (a **different task**
  from the ordinary `Copilot`):

```json
{ "enable": true, "filename": "sss/plan.json", "loop_times": 1 }
```

`filename` may be absolute or relative, and **cannot be set at runtime**.
`loop_times` can be set; but **MAA does not borrow operators**, so do not loop if a
support unit is needed.

Three practical points for running it (learned the hard way 2026-09-04):

1. **`os.chdir` into the MAA directory inside the process first**, otherwise the DLL
   is not found and the script dies silently.
2. **Do not detach it with `subprocess.Popen`**: winrun runs through Task Scheduler,
   and when the task ends it takes the whole process tree down with it — not one
   character gets written to the log. The right way is to **register a second,
   independent scheduled task** (`schtasks /create` + `/run`), which belongs to Task
   Scheduler and has nothing to do with the ssh session.
3. **The script must not return early**: the moment Asst is garbage-collected,
   combat stops on the spot. One SSS run takes twenty to thirty minutes — loop and
   wait for the chain event (`TaskChainCompleted`) before exiting.

Once it is running the log shows `SSSStage {"stage": "LT-1"}` and
`CopilotAction {...}`; that is it actually playing. A completed set prints
`SSSGamePass {}` followed by `链 TaskChainCompleted SSSCopilot` — **only those two
lines mean it cleared.**

`SSSStage` repeats for the same floor (MAA re-recognises every few minutes);
**that is not a failed restart.** Judge whether something went wrong from the life
count and the enemy count, not from how many times this line appears.

One six-floor run is about 20 minutes: measured 2026-09-04, LT-1 to LT-6 took
01:16 → 01:56.

---

## 3. Red lines common to both

* **`自动编队` wipes the current squad** and rebuilds it from the copilot's operator
  list. Do not run it on a squad you care about.
* **AUTO-MAS cannot run copilots**: its MAA integration has only `IfFight`,
  `IfSeizeEntrustTask`, `SanityTaskType`, `TaskTransitionMethod` — **no copilot
  field** — so copilots cannot get into the nightly queue. Manual, or MaaCore.
* **Hard prerequisites**: the emulator at 60 FPS (**confirmed by measurement from
  MaaCore's callback on 2026-09-04**: `EmulatorFPS {"fps": 60}`; the earlier
  "cannot be confirmed" note in the docs is obsolete) plus touch mode MiniTouch or
  MaaTouch. **A plain adb `input tap` does not count**: a deployment is a
  press-drag-release with a directional flick, at frame-level timing, which tapping
  cannot do.
* **Judge "stuck" by repetition, not by silence**: navigation that cannot find the
  stage keeps emitting callbacks, so the silence timer never fires. What
  `scripts/windows/copilot-drive.py` does is count consecutive identical subtasks
  and give up at 30.
* Do not launch `MAA.exe` directly (it is a launcher); go through the existing
  scripts.

---

## 4. Next time, just say it

* "farm the event stage for materials" → I change config, use the queue, no
  copilots.
* "clear the event EX / 突袭" → I follow the recipe in section 1, part 2: `StartUp`
  first, then tap into the map by hand, then `copilot_list`.
* "run SSS" → **I do the whole thing myself**, you do not have to touch anything.
  First check whether 全权委托 is unlocked: if it is, use it directly (2 proxy
  cards, a few seconds); if not, do the manual prep from section 2 up to
  **开始部署**, hand over to MAA to clear a floor, and 全权委托 unlocks with it.
  "自动编队 does not work for SSS" refers to **MAA's** auto-squad, not to me being
  unable to build one — I drive the emulator directly with
  `scripts/mac/adbdo.sh` and can tap through the squad, 导能元件 and 战术装备 just
  the same. Walked end to end on 2026-09-04.

Sources:
[MAA auto-battle manual](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/manual/introduction/copilot.md),
[integration protocol](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/protocol/integration.md),
[SSS protocol](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/protocol/sss-schema.md).
MAA's default branch is **`dev-v2`**; `dev` links 404.
More detailed measurement notes are in the "MAA's auto-battle" section of
`docs/OPERATIONS.md`.
