# Optimisation plan (proposed 2026-09-06, awaiting a decision)

**Why this exists**: on 09-06 the user asked for
「对程序、仓库、项目文件、工作流程整体优化一下，按重要程度排序」.
What follows is the plan produced after sweeping the repo, and **not one item of
it has been started**. There is a single criterion: which item does most to
reduce "the machine did not do its job / he does not know about it / I make the
same mistake again".

Repo facts at scan time (all measured with tools, not impressions):

| Item | Count |
|---|---|
| Commits | 485 (since 08-14, 20+ a day) |
| Relay source | 14898 lines across 19 modules; `engine.py` 1562 lines, `_maybe_shutdown` alone 130 lines with 8 gates |
| Tests | 61, all green; own runner, executed once by lint and once by deploy |
| Docs | 36 files / 8029 lines; **16 of them are linked from nowhere**; 6 are written in English (OPERATIONS 1383 lines, PITFALLS 891 lines, CONFIG, NOTIFICATIONS, HEADLESS, GAME) |
| Places rules are kept | CLAUDE.md, TOOLING.md, PITFALLS.md, RETROSPECTIVE.md, memory (105 entries, 31 of them 「死命令」), BACKLOG.md - **six of them** |
| Loaded into every session | CLAUDE.md 7.4KB + MEMORY.md 15.2KB |
| Backlog | 15 unticked items, at least 3 of which are already expired or already done |
| Boot supervision | `queue/watchdog.json` `enabled=false`, `pause_until=08-20`, Secrets not configured |

---

## Tier one: leaving these alone means it happens again

### 1. The shutdown decision has to speak, and the "do not shut down" switch needs an expiry
**Problem**: whichever of `_maybe_shutdown`'s 8 gates says "do not shut down",
the only trace is a line in relay.log. On 09-03 and 09-04 the machine stayed on
all night two nights running, because of a `skip-next-shutdown.flag` I never
cancelled. That flag **has no expiry**, and nothing tells you "no shutdown
tonight, because X". The GitHub Actions boot supervision that should have caught
it was switched off.
**What to do**:
- When the moment to shut down passes without a shutdown, **push one message**:
  「今晚不关机：原因」 (event-driven, at most one a day, not polling).
- Write an expiry into `skip-next-shutdown.flag`: valid only for **the next
  shutdown that same day**, void once the day is over; if it is found to be from
  a previous day at boot, delete it.
- Fold "skip-shutdown flag / debug mode / next shutdown opportunity" into
  `healthcheck.py`, so the end-of-day check shows them at a glance.
- Split the shutdown decision out of `engine.py` into `shutdown.py`: one pure
  function `decide(now) -> (shut down or not, reason)`, where the reason is the
  text of the push; `test_shutdown.py` tests it directly.
- Boot supervision: you set the three Secrets, I flip `enabled` to true and
  change `pause_until` to read debug mode.

### 2. Clear out the backlog and give every remaining item a trigger
**Problem**: of the 15 unticked items, 「09-04 方舟大版本维护日」 has passed,
「队列改名+通知样式」 is probably already done, and 「1.5.3 适配」 depends on
whether MaaEnd ships a new version. You once asked 「你记不住事吗」 - a ledger
that has itself gone stale is the same as not remembering.
**What to do**: verify each item now, tick what is done, delete what is dead;
every item that stays must state **the condition under which it is next looked
at** (a version ships / a morning run finishes / you say something). No item
without a condition may stay.
For upstream issues and PRs (#5506, #5453, beta.6), write a
`scripts/mac/upstream-watch.py` that pulls every status in one command
**when I want to look** - not on a timer.

### 3. Keep each rule in one place, and turn the ones documents cannot hold into gates
**Problem**: the same lesson is repeated two or three times across PITFALLS,
RETROSPECTIVE, TOOLING, CLAUDE.md and memory, 22KB of rules is loaded into every
session, and the repeat mistakes have not gone down because of it - you said it
yourself: 「写进文档里跟放屁一样」.
**What to do**:
- Every rule takes one of three routes: **become a gate** (lint-repo / guardcheck
  / a tool that refuses) -> delete it from the docs; **one sentence** in
  CLAUDE.md; **the background story** into a single Chinese "lessons" document,
  with PITFALLS and RETROSPECTIVE merged into it.
- Merge memory's 31 「死命令」 by subject down to roughly ten (for example
  「他说什么就做什么」, 「活没干完不许停」 and 「不许说否定词」 are one rule),
  keeping the original wording and provenance.
- Wire `check-docs.py` into `lint-repo.sh` (it is not wired in today) and add one
  more check: every file in docs must be indexed from README or CLAUDE.md, else
  fail - that is exactly how 16 orphan documents came about.

## Tier two: worth doing, but nothing breaks immediately

### 4. Convert all docs to Chinese, split the large files, deal with the orphans
- Convert the 6 English documents to Chinese; split `OPERATIONS.md` into three
  (machine paths and schedule / remote driving / the update mechanism of the four
  programs).
- Judge the 16 orphan documents one by one: hook the still-useful ones into the
  index, delete the expired ones (SWEEP-0830, for instance, was a one-off).

### 5. Turn start-of-day and end-of-day into scripts instead of ad-hoc commands
- `scripts/mac/start.sh`: machine time, debug mode, skip-shutdown flag,
  pre-update result, today's queues - on one screen.
- `scripts/mac/confirm-off.sh`: the two criteria for confirming a shutdown (ssh
  refuses to connect + tailscale rx not increasing) hard-coded into it. On 09-05
  I reported 「已关机」 wrongly on the strength of a ping; that judgement should
  never be reassembled by hand again.
- Both go into the CLAUDE.md tool table.

### 6. Split the large relay modules
`engine.py` is 1562 lines: shutdown (see item 1), `_handle` and the daily report
each become their own module; `okww_patch.py` at 1264 lines splits one file per
patch. Move only, change nothing; tests untouched.

## Tier three: when there is time

### 7. Unify tests under unittest, run once
Each of the 61 tests starts its own python; most of lint's 13.8 seconds is that,
and deploy runs the whole thing again. Move to
`python -m unittest discover` in one pass, with the gate criteria unchanged.

### 8. Merge `scripts/win` into `scripts/windows`
Two directories hold Windows scripts with no reason to distinguish them.

### 9. Choose between `queue/config.json` and `inbox/todo.json` - **done 2026-09-08**: deleted `inbox/`, which nothing referenced, leaving only `queue/config.json`; and cleared the stale `debug_mode` left inside it (a version bump would have replayed it)
The phone page is already the main entry point; one file-delivery channel is
enough.

---

**Not in the plan**: the phone page's single 900-line `app.js` (it works, it
changes often, and splitting it would make it harder to change);
`MedicineNumb=999` (your setting); the HP cloud server (shelved).

**Why this order**: the three tier-one items correspond to the three heaviest
things you have said - 「怎么没关机」, 「你记不住事吗」, 「写进文档里跟放屁一样」.


---

## 2026-09-06: the user's decisions, and what was done

The user made three points; the plan is reordered around them:
1. Docs stay in English - I am their only reader. The half-sentence about
   converting to Chinese in tier-two item 4 is void; splitting the large files
   still stands.
2. 「同一条教训记两三遍、错照样犯」 - the answer is not to write more rules, it
   is: turn judgement-type rules into a **mandatory tool path** (a status may
   only be reported by pasting a script's output; a config change must print the
   read-back diff); cut the number of rules down to what fits in one head; reduce
   the number of times I act by hand.
3. The real loss is **his time**: 95 deploys in the last 6 days, 128 feature
   commits and 81 bug fixes in 14 days, and the bugs are ones I create daily.
   The user rejected cutting features or freezing, and required that the software
   be **read through and fixed in place**.

Done that day (no new features; everything has a test or a gate):
* Read through all 26 relay modules + service.py + the phone page.
* Fixed: in `queues.apply` and `commands._run_now` a local variable shadowed the
  `names` module, so every call had crashed since 09-02 (skip-queue, the todo
  queue switch, and the phone page's 「现在跑一趟」 had been dead for four days).
  `test_queue_apply_runnow.py`.
* Fixed: one failing section of `tick()` took the daily report and the shutdown
  with it (the 09-04 incident) - each section now has its own fallback.
  `test_tick_isolation.py`.
* Fixed: one bad time in a ledger line -> the daily report cannot be sent -> the
  machine stays on all night. `test_ledger_bad_times.py`.
* Changed: `_scripts_running` now caches for three seconds, which saves a dozen
  `tasklist` invocations per round.
* Fixed: `GetTickCount64` had no 64-bit return declared; an invalid escape in
  okww_patch (3.14 warns about it); the PowerShell 5.1 fallbacks in preupdate and
  check-docs deleted, pwsh 7 only; check-docs referenced a `_has_pwsh` that was
  never defined; 8 unused imports / fake f-strings across scripts.
* Gates: lint item 9 = zero pyflakes reports + a strict compile with the
  machine's Python 3.14; lint item 2's regex extended to the list form;
  guardcheck gained two bad samples.
* Deploy: RELEASE-NOTES written; **the machine is off, so deploy immediately
  after it powers on at 09-06 08:40**.

## How to fix the mess (night of 2026-09-06, the user asked 「那现在这个软件要怎么改」)

No features cut, no freeze: turn it, in place, into something where changing one
thing tells you what else it affects. The order cannot be rearranged:

1. **Build the defence before touching the structure**: a replay test of a real
   day. Take a real day that has already run (AUTO-MAS history + the three
   programs' logs + that day's pushes and shutdown decisions) into
   `relay/tests/replay/`, have the relay replay it, and require byte-identical
   push text and shutdown decisions. From then on, every bug fixed adds its day
   to the corpus. This is the one thing the mess lacks: proof that **changing A
   did not break B**. The current 64 tests use hand-written inputs and cannot
   prove it.
2. **Cut along the seams, do not rewrite**: `engine.py` into three pure pieces -
   bookkeeping (`_handle`), reporting (daily report / on-demand view) and the
   shutdown decision (returning "shut down or not + reason"); `service.py`'s main
   into per-stage boot functions; `okww_patch.py` into one file per patch. Every
   step moves code without changing it, and is only finished when the replay tests
   all pass.
3. **Move the incident history out of the comments**: the code keeps one sentence
   of "why it is written this way", the story goes into docs. Half the lines
   today are history, and a reader cannot tell which line is a rule and which is
   a war story.
4. ~~Change cadence: at most one deploy per day~~ **rejected by the user on
   09-06: 「这就是在偷懒，所有事故都由你偷懒引起，闸门全是为了防止你偷懒。设计一个彻底让你不能偷懒的东西。」**
   Replaced by:
   **Being lazy made impossible - four gates enforced by machines, with no place
   for a sentence from me:**
   a. **No change may be deployed without a replay case.** The deploy script reads
      which modules the git diff touched, and every one of them must actually be
      exercised by at least one replay case (coverage recorded during the replay);
      a commit that changes a criterion must bring a new case with it, or the
      deploy is refused outright. Whatever you changed, you have to prove.
   b. **The words "deploy complete" may only be printed by the script.** After
      restarting the service the deploy script runs its own smoke test on the
      machine: import every module, call the changed functions once against the
      real config (no dispatch, no sanity burned), and read relay.log to confirm
      zero 「出错」 lines - only if all of that passes does it print "deploy
      complete", and I may not say those words before it does.
   c. **The next real shift scores this version automatically.** A fixed line at
      the end of the daily report: 「代码 v…，这版跑过 N 趟，失败 M 趟」. The relay
      computes that line; it does not pass through me. If I say "fixed" while it
      says one run failed, the lie is visible on the spot.
   d. **Status conclusions may only be pasted script output.** 「已关机」 =
      the output of `confirm-off.sh`; 「已生效」 = the output of the deploy script;
      「配置已改」 = the read-back diff. Three scripts, each printing machine time
      and the criterion text; to say any of those three things, I can only paste
      their output wholesale.
5. **Metric**: 「连续 N 天你没动过它」 at the end of the daily report, next to the
   line from 4c.

The user's characterisation of step 1 (09-06): 「你这个软件是外置的，相当于工头，
只要 MAS 和它管的三个脚本这四个程序的输出固定一次，中继每次跑的结果就该一致，
能在 Mac 上实战演练。」 That sentence is the basis of the replay tests: the input
is what the four programs write to disk, the output is the push text and the
shutdown decision, and both ends can be pinned down.

Effort: one working day for step 1, one for step 2, step 3 in odd moments.

## Late night 2026-09-06: steps two and three are done (the user's call: 「先做二三」)

Step two (commit 4592315):
* engine.py 1595 lines -> engine 477 / handle 512 / missed 145 / report 239 /
  shutdown 369. All 49 functions compared one by one: 47 are identical to the
  character, `_archive_maaend_evidence` only lost a local import, and
  `_maybe_shutdown` was deliberately turned into the pure decision
  `shutdown.decide()` (returning shut down or not + reason + which gate) with the
  side effects kept separate.
* service.py's 675-line main -> 10 stage functions, with main left as the order
  they run in.
* okww_patch.py 1264 lines -> okww_patches/, one file per patch; 25 functions and
  every constant compared one by one, all identical.
Step three: roughly 370 lines of dated incident history in comments and
docstrings moved into `docs/CODE-HISTORY.md`, leaving the first sentence in the
code plus a pointer to the full account; rule lines containing "must" or "must
not" stay where they are.
Only the files touched by step two were done; the remaining modules get the same
script next time.

**Not deployed**: the machine is off. The split added new files, and the
self-update at boot does not pick up new files, so `deploy-relay.sh` must be run
by hand after tomorrow's boot (after the 09:00 queue starts, so it does not
collide with the pre-update window).

## Late night 2026-09-07: five root-cause items, approved by the user (「根治的那五项你都可以跑了，我批准了」)

The picture measured that day: 15.7k lines of relay, 13 OK-WW patches, 76 tests,
280 dated incident comments; 388 commits in 14 days, 113 of them deploys; 36
commits and 12 deploys that day alone. Almost every bug fixed that day was a
"judgement written to the shape of the log as it looked at the time" that had
stopped holding: OK-WW missing from the process list, an old version number
overwritten by a new process, the weekly boss never reaching the step list, a
failure reason classified from a single log line, the wrong event type for
stopping a service.

| # | Item | What it means | Machine needed | State |
|---|---|---|---|---|
| 1 | Feed judgements from upstream structured interfaces | AUTO-MAS runtime-snapshot (already in use), MaaEnd task state through the MXU 12701 API, OK-WW's info_set state, MAA's callback file; logs and OCR only as fallback | Yes (inspect the interfaces, verify on the machine) | To do |
| 2 | Offline replay test corpus | Redacted history and logs from the machine into tests/replay; judgement functions run against the replay first; a new bug adds its sample before it is fixed | Yes (pull samples) | To do |
| 3 | Consolidate state | One state file plus a field table, replacing a dozen scattered files; phone page, daily report and shutdown decision all read from it | No | To do |
| 4 | Centralise notification text | All notification text into one module, with no English, no vagueness, and one phrasing per kind, guarded by tests | No | To do |
| 5 | Split the long functions | `_loop` 251 lines, `parse_record` 140, `parse_okww_log` 140; preupdate split per program | No | To do |

Order: tonight 4 -> 5 -> 3 (no machine needed, all guarded by tests); items 1 and
2 in tomorrow's window after the morning shift finishes, with the deploy and
on-machine verification in that same window, leaving the morning shift alone.

### Early hours of 2026-09-08: progress on the five, and the interface list for item 1

Done and on the machine (two deploys at 09-07 23:24 and 23:34, verified there):
* Item 4, centralised notification text: `ark_relay/texts.py` +
  `tests/test_texts_gate.py`.
* Item 5, splitting long functions: `preupdate` ->
  `preupdate_common/_maaend/_maa/_automas/_okww` (AST comparison 68/68);
  `collector.parse_okww_log / parse_record` split into named steps.
  `service._loop` (251 lines) is left for the daytime window - verifying that
  split requires watching a whole tick round.
* Item 2, the replay corpus: `tests/replay/` + `scripts/mac/pull-replay.sh` +
  `tests/test_replay.py`; 10 real records from the whole of 2026-09-07 are in,
  with the decisions checked by hand.
* Item 3, consolidating state: `ark_relay/statestore.py` (a single `state.json`,
  a field table, migration). The three weekly gates and the version bookkeeping
  have moved in (migration succeeded on the machine:
  annihilation/garden/weeklyboss/okww-version/maaend-version). Remaining: the
  day's markers and switches, the update flow, and the alert queue, in the order
  given by docs/STATE-MODEL.md.
* Incidentally: `collector.scan` used to re-parse all several hundred history
  entries every cycle; anything already seen is now skipped by path.

Item 1 (feeding judgements from upstream interfaces) - the interfaces have all
been established; the work has to happen in a window with the programs running:
| Program | Interface | State |
|---|---|---|
| AUTO-MAS | `GET /api/dispatch/runtime-snapshot` (per script: finished / error / running / waiting) | Already used for "is a script running" |
| MaaEnd (MXU) | `http://127.0.0.1:12701/api/maa/state`, `/api/ws` (event stream), `/api/logs`, `/api/maa/instances/:id/*` | Only listens while MXU is running; to be wired up in the morning window |
| OK-WW | ships its own fastapi: `/api/tasks`, `/api/logs`, `/api/events` (ws), `/api/executor/*` | Only started when `gui.type == "web"` (config.py); needs one patch to set `type: web, launch_mode: server` with a fixed port; try it in the window first |
| MAA | AUTO-MAS already hands over the result JSON; per-task granularity is in `debug/asst.log` | Good enough as it stands |


## Early hours of 2026-09-08: all five items handled, one by one

| # | Item | Result |
|---|---|---|
| 1 | Feed judgements from upstream structured interfaces | **AUTO-MAS**: `/api/dispatch/runtime-snapshot` is used for "is a script running". **OK-WW**: switched to the `info_set 键 值` lines it writes itself (`current task`, `错误`, `Teleport to Tacet Suppression`, sanity, daily progress), with prose only as fallback; the 无音区 named in the daily report is **the one actually farmed**, and if that disagrees with the setting, both are stated. **MaaEnd**: its log is structured markers to begin with (`任务开始/完成/失败`) and is already used that way; MXU's 12701 API only exists while MaaEnd is running, so using it would mean polling during a run - not done, per the standing order that polling needs approval, and left pending the user's nod |
| 2 | Offline replay test corpus | `tests/replay/` + `scripts/mac/pull-replay.sh` + `tests/test_replay.py`. **On 2026-09-08 grown from 1 day / 10 records to 4 days / 42 records**: the run of the weekly boss stuck on the settlement page that night on 09-01, the two 09-04/09-05 rounds that farmed essence in the wrong region, and an ordinary day on 09-07. Every decision checked by hand, and `FLOOR` raised from 10 to 40 so the corpus cannot quietly disappear |
| 3 | Consolidate state | `statestore.py`: a single `state.json`, six sections, writes only for fields registered in the field table, and a scan for old files that migrates them at every start. 60 old files have been migrated on the machine; the only things still kept as files are the ledger, seen, evidence, locks, the heartbeat and pure caches |
| 4 | Centralise notification text | `texts.py` + `tests/test_texts_gate.py`: titles may not be hard-coded in the code, and the text may not contain English or be vague |
| 5 | Split the long functions | `preupdate` split into five modules (AST comparison 68/68), `collector`'s two 140-line functions split into named steps, `_loop` (241 lines) split into `_DirWatch` + `_AutomasKeeper` + a short loop with unit tests added. **On 2026-09-08 the remaining 15 were split too, and there is now no function over 80 lines left** (the longest used to be test_banners.main at 215). At the same time, tests were added for the two untested writers `maaend.apply_changes` and `inbox.poll`; the new tests are green against the pre-split code as well, so "the behaviour did not change" is verified, not assumed |

**The one thing not done, and why**: MaaEnd's MXU 12701 API. It only listens
while the MaaEnd process is alive, and the relay is event-driven (file changes +
alarm clock), so getting per-task state during a run would mean standing up a
poll. The user's standing order of 2026-08-31 is 「不许默认轮询，要用先问」, so
this stays pending a nod. The gain is limited anyway: MaaEnd's own log is already
structured markers, and that is what we judge from.


## 2026-09-08: one item explicitly not being done

**Mixed Chinese and English in comments will not be unified.** One review finding
said "comments and docstrings mix Chinese and English with no boundary; the same
reason is written six different ways, so one grep only hits half of them" - and
the count is accurate: 1121 lines of Chinese comments and 747 of English in the
relay, with 29 files containing both.

But the user already decided on 2026-09-06:
「文档留英文——只有我读，英文对我更准；不要提改中文」.
So this is filed as not-doing, and only the boundary goes into `CLAUDE.md`: text
the user will read must be Chinese (notifications, the phone page, RELEASE-NOTES,
the backlog, open questions - `texts.py` has a gate for it), while code comments
and the rest of docs follow whoever writes them, and **no translation campaign
may be started**.


## 2026-09-08: all 67 review findings landed

The user's words on 2026-09-08:
「全做完，我发现你怎么做事情爱做一半，派 agent 之前的那些任务也这样。」
Eight dimensions reviewed in parallel produced 67 findings, all handled:

**66 changed**, across eight to twelve batches of commits. The ones most worth
remembering are not about mess, they are about **false normality**:

* `purge-cdn.py` reported "1 file still not served correctly" after every deploy
  - that file is always the release notes itself, and the discrepancy is how the
  deploy flow is designed. A false alarm teaches people to stop reading alarms.
* The environment-variable gate had three holes of its own and 13 variables slid
  through them, while the docs said "miss one and it goes red".
* `check()` was written 66 different ways across 66 tests, and two of them had
  the meaning of the second and third arguments backwards; in those two files,
  writing the comparison the way most people do degraded the assertion into "is
  the actual value truthy", which always passes.
* 521 `# noqa` comments had never been verified by anything, and one of them
  carried a misspelled rule number, `PLC4015`.
* The FleetMonitor binary in the repo was four days older than the source -
  older exactly across the fix for "a powered-off machine always shows green".
* `core.is_last_run_of_day` decided the daily report's timing from "the moment
  the last run finished" - precisely the broken approach PITFALLS records, where
  an early finish to the evening shift means the daily report is never sent and
  the machine never powers off, left sitting there for someone to copy.

**5 new gates** (lint 15->19, guardcheck 28->34, each verified with a bad sample
to prove it really refuses): the logger name must equal `ark.<module>`; the
arguments of `check()` / `require()` must mean one thing only; CODE-HISTORY
anchors must be unique and the sentence above a pointer must be complete; `ruff`
+ RUF100 so that every noqa really suppresses a rule; and the dead-code check
extended to cover `relay/ark_relay/`.

**1 explicitly not done**: unifying Chinese and English in comments (it conflicts
with the user's 09-06 decision that docs stay in English; reasons in the previous
section).
**1 awaiting your decision**: the real name and login method in the git history.
Rewriting public history is irreversible, so it is recorded in `BACKLOG.md`.

The two remaining items from the five root-cause items were also finished in the
same period:
* all 15 functions over 80 lines split up, and there are now none (the longest
  was 215 lines);
* the replay corpus grown from 1 day / 10 records to 4 days / 42 records, with
  FLOOR raised from 10 to 40.


## 2026-09-08 (afternoon): what "hard to maintain" actually measured, and what was done

The user asked "is it maintainable now?" and I answered with an adjective ("no, today
proves it"). He called that out as giving up. He was right: the answer has to be a
number that can move.

**The measurement.** Run the whole suite with a tracer and record which code is never
executed:

    671 functions in the relay, 243 (36%) never touched by any test
    modules never reached at all: __main__.py  skland.py  snapshot.py  watch.py

That morning's bug — a stray `@property` on `State.save_pending` that made the relay
re-push the same failure alert every twelve seconds for half an hour — landed exactly
in those 243. The function had never been called by a test, so a wrong decorator went
green all the way onto the machine.

**What was done.**

| | morning | after |
|---|---|---|
| functions no test ever executes | 243 / 671 (36%) | 34 / 671 (5%) |
| modules never reached | 4 | 0 |
| tests | 90 | 96 (+300 assertions) |
| gates (lint / guardcheck) | 19 / 35 | 19 / 36 |
| deploy wall clock | 183 s | 66 s |

Six new test files, each written against "what breaks silently if this test does not
exist" rather than for coverage: notifications not delivered (a fault nobody learns
about), the daily report not sent (shutdown waits on it — the machine stays up all
night), config written wrong (wrong stage, burnt sanity potions — the 826 incident),
alerts re-pushed (that morning), self-update unable to fetch new code while the screen
stays green. Every assertion was mutation-verified: break the production code on
purpose, confirm the test goes red — 53 mutations in total.

**Two real defects fell out of writing them**, neither guessed:

* `Engine.tick()` read the mode switches *outside* the per-step guard. One throw there
  takes the whole tick with it — including the daily report and the shutdown decision —
  every single round. Same shape as the 2026-09-04 incident, different entrance.
* `Notifier.send()` returned `[]` — the "delivered" contract — when no channel was
  configured at all. `send_group` had guarded that case; `send` had not.

**The ratchet.** Finishing all 243 at once is not realistic and a coverage threshold
would only produce useless tests. So the remaining 34 are registered in
`relay/tests/untested-baseline.txt` and the list may only shrink: adding a public
function that no test executes is refused at deploy time. Proven with a bad sample in
`guardcheck.sh`. It reuses the tracer run that `changed_covered.py` already does, so it
costs nothing extra.

**Deploy speed.** Stage timings showed the gates were never the bottleneck — the file
transfer was. One `scp` per file cost 1.7 s each even with connection reuse (190 ms
cross-border round trip, several exchanges per session); 71 files took 119 s, two thirds
of the whole deploy. One `tar` stream does the same 71 files in 2 s. The hash check
after the push is unchanged. The coverage gate went 36 s → 9 s by dropping `uvx
coverage` for a `sys.settrace` call-event recorder (this gate needs one bit per file,
not per-line accounting) and sharding across cores. Three tests were sleeping on the
real clock for 17 s combined — spotted by CPU share, not by reading: `test_gameupdate`
spent 6.5 s at 3% CPU, which is waiting, not computing.

**The first thing the new smoke check caught** was the tar switch itself: macOS `tar`
ships extended attributes as `._name` AppleDouble entries, so the first packed push
littered 18 of them on the machine. Per-file hash verification cannot see that — it only
checks that the files in the manifest are present and correct, never that nothing extra
arrived. The "import every module on the machine" smoke step, added the day before,
found them.
