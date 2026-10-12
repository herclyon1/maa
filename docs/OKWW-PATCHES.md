# OK-WW local patches — what changed, why, and what counts as success

> **Corrected 2026-09-08, inventory rewritten 2026-10-12. Everything below the
> overlay sections describes a state that no longer exists** and was misleading on the one morning it was needed: 09-08's
> failure was an `ensure_main` timeout, and the first section here sends the reader
> looking for a `_ensure_main_keep_book` patch that **does not exist anywhere in the
> code**. Section 2 (「领奖顺序」) is now a deliberate *revert*, not an application,
> and section 3's "planned feature" (choosing which nest to farm) has been shipped
> for weeks. The header's 「Patched file: DailyTask.py」 is wrong too: six files are
> touched. Read the inventory first; treat the rest as history.

## The inventory — what edits OK-WW's source: nothing

No upstream source file is edited any more. The text patches and the whole-file
`NightmareNestTask.py` replacement were moved into the overlay on 2026-09-09; from then
until 2026-10-12 the relay only put upstream's text back wherever an old copy was still
on the machine (`okww_patch.py`'s revert tables, `okww_patches/<name>.py`, the stored
`NightmareNestTask.upstream.py` / `.patched.py`). On 2026-10-12 the machine was checked
clean - of the 41 recorded reverts none was still patched, the nest file
upstream's own, no `*.py.bak-*` in `src/task` - and that restore-only code was removed.

**Where the changes live (since 2026-09-09)**: all of them, in
`okww_files/ark_overrides.tasks.py`, installed into OK-WW's own `ok_tasks/` folder by
`okww_overlay.py`. Nothing there edits an upstream file.

**Each change hooks the smallest method that contains it.** The first shape of that
file carried five whole-method copies, 30 to 90 lines each; upstream ships roughly
every other day, and each copy would have gone stale the first time they touched that
method - the pin would have said so, but the change would have stopped happening.
Hooking one call deeper removes the exposure: 「skip the weekly boss when waveplates
are short」 used to copy a 28-line teleport method and now replaces the three-line
challenge button it calls. Most bindings are wrappers that run upstream's own body
inside them; only `revive_action`, `click_team_challenge` and `get_stamina` (M7,
2026-09-23: an unread 数/数 became 「0 current」) replace it, and each is pinned to
its hash.

**Daily activity chests (2026-10-10)**: the user, 10-10 19:4x (relayed by 网页-验收):
「鸣潮的每日为什么okww没有领，中继也不报错？」 `DailyTask.claim_daily` is wrapped by
`claim_daily_after_farm`; when upstream's body still hashes to `2b4977b62f7c` it runs
our copy of that body up to its one blind click on the 100 chest, then
`_claim_tiers`: every chest up to the points read is clicked (found from the OCR'd
tier labels, in units of one tier step), and each is checked for the claimed tick
(normalised correlation against a 20x20 tick taken from the user's screenshot
`BOARD/evidence/ww-daily-80-1010.png`; claimed 0.94-0.99, unclaimed 0.49). Two tries,
then 「活跃奖励没领到：…」 with a screenshot. Any other hash: upstream's claim runs and
the log says 「活跃奖励：没有核对，…」. The relay turns these lines, and points under 100,
into items undone (`outcome.daily_reward_checks`). Test: `tests/test_okww_daily_chests.py`.
2026-10-11 09:29 all five were claimed at 140 points and the log still said
「100 档点了没领到」 (100: 0.35): chests were placed from each label's box centre, and
「100」 is a digit wider than 「20」-「80」 while the chest keeps one distance from the
label's right edge, so the 100 chest was looked for 14 px left of its tick (0.96 at the
tick, with the reward preview the click opens still on screen above it). Labels are now
placed by the centre of their last two digits; the run's screenshot is the fixture
`ww-daily-140-1011-row.png`.

**Battle pass, one retry (2026-10-11)**: what is wanted (the user, 10-11 17:36): the daily podcast points
not lost. Why a miss must be an item undone pushed to the group (not his words - the code): upstream's `DailyTask.claim_battle_pass` (sha `e9e8d67cb3bc`, v3.7.4 and master on
10-11; fixture `relay/tests/fixtures/okww-DailyTask-v3.7.4.py.txt`) Alt-clicks the podcast icon and waits
10 s for the level number; with none it logs 「can not battle pass, maybe ended」 (fixture line 210), keeps no
screenshot, does not try again, and the run still ends 「Daily Task Completed」, which the relay read as a clean
run - so a missed day had no make-up and no trace a person would see; pushing it costs one message. In the AUTO-MAS history (08-14 .. 10-11) that happened on 08-26 21:13
(a test evening; the game was off the world screen) and 09-29 09:28 (period still open: 3.6 ran to
09-30 03:59), both unreported. The override keeps upstream's body and adds: a miss is photographed
(`battle_pass_unopened_1`) with the whole screen's text in the log, `ensure_main`, one more open in the same
run; a second miss logs `battle_pass_unopened_2`, upstream's own ERROR sentence and 「战令没领到：…」. An
opened page gets upstream's clicks unchanged and 「战令：页面打开了，点了领取（等级 N）」 - the claim itself is
not verified (no picture of the page to check against yet). Any other upstream hash: upstream's own body
runs and the log says 「战令：没有重试，…」. The relay turns these lines (and upstream's sentence alone) into
the item 「战令（先约电台）点了领取」 (`outcome.battle_pass_checks`, also in the 「dailies done before the run」
branch); red goes to the group in 「⚠️ 这一轮没干完」. Test: `relay/tests/test_okww_battle_pass_claim.py`.

**Tacet list groups (2026-09-30, WuWa 3.7):** `TacetTask.teleport_to_tacet` is wrapped so an instance still
carrying upstream's pre-3.7 `structure = [2, 5, 5, 7]` clicks by `[4, 5, 5, 7]` (沉心域 / 烬心域 added at
the top of F2 「无音清剿」, read in game). Any other list - upstream's own fix, or the hand edit made on the
machine that day - is left alone. Each call logs 「无音区分组：…」, checked by `outcome.patch_effect_checks`;
`tests/test_okww_tacet_groups.py` runs upstream's real v3.6.9-beta.1 `TacetTask.py` against it.

**Game launch argument (2026-10-01, WuWa 3.7):** since the 3.7 client, a bare start of
`Wuthering Waves.exe` asserts about ten seconds in ("kuro: Use launcher to start game!") and
the dialog keeps the process open, so OK-WW waited for a window until AUTO-MAS's 120-minute
limit - three times on 10-01. `ok.core.start_controller.execute` is wrapped to append
`-krqlv=hd`, the one argument the official launcher passes (read from Win32_Process while the
launcher had the game up), whenever the target is `Wuthering Waves.exe` and no `-krqlv` is
present; with it the same exe reaches the login screen. OK-WW has no setting for this:
`start_controller.start_device` only builds arguments for "Launch with DX11", and the exe
path from `calculate_pc_exe_path` must pass `os.path.exists` (`DeviceManager.get_exe_path`).
It is installed in its own `try` ahead of the others, because nothing else matters if the
game never starts. Proof on the machine is ok-script's own line
`try execute D:\Wuthering Waves Game\Wuthering Waves.exe -krqlv=hd with start`.

**How a weekly-boss / echo-farm run ends (2026-10-06):** OK-WW's
`TaskDisabledException` ends a task as *skipped*, and the overlay used it for every
stop. The user, 2026-10-06: 「只要是报错…不论多少次什么错误都要发」. Now:

| Stop | Trigger | Ends as |
|---|---|---|
| `_stop` (screenshot + `log_error`) | a screen or number the overlay does not know: count unread before entry or on the read-back, read-back unchanged / off by more than one, re-entry failed, no settlement page after the claim, an unknown dialog after 开启挑战 or at the claim | **failed** |
| `FarmEchoTask.run` retry cap | `_MAX_FARM_RETRIES` (3) failures in a row | **failed** |
| `click_team_challenge` | the game's 「结晶波片不足，无法获取奖励」 dialog (取消 is clicked, no fight for nothing) | skipped (`_skip_short`, since 2026-10-07): no FAILED_MARK, no ArkStopped, so AUTO-MAS does not retry a run that a retry minutes later could not fix; the relay reads the skip line (`outcome.WEEKLY_SHORT`) as an item undone and pushes it in 「⚠️ 这一轮没干完」 (since 2026-10-11; 10-07..10-11 daily report only, on a lazy verdict: the 10-06 alarm behind it was the changelog false match fixed in `12edfb0b`, and a real shortage is in 6 of 126 weekly-boss runs, all 08-31/09-01 hand-runs - see `outcome.okww_checks`) |
| `click_configured_boss_level` | the level page reads 「本周剩余可收取次数：0/3」 (also how the week's last claim ends) | skipped - the game says nothing is left; the daily report says 「进本前读到本周 0/3」 |

The way out is unchanged and still presses nothing: `_end_failed` records the reason
on the task and raises `ArkStop`, a `TaskDisabledException` subclass made at install
time, which upstream lets through every catch-all (do_run re-raises it, run() returns
on it, the teleport wrapper unwraps it). The outermost `FarmEchoTask.run` then logs
「这一趟按失败结束：…」 and raises `ArkStopped` (a plain `Exception`), which OK-WW
counts as a failure. Inside the AUTO-MAS daily (`-t 1`) the weekly boss is an
additional task: `open_daily_first` catches the failure (「附加任务出错，不拖垮当趟日常」)
so the daily goes on, and AUTO-MAS still judges the run by 「Daily Task Completed」 -
the relay sees the weekly boss's outcome from the log (`outcome.okww_checks`).

`test_okww_overlay_copies.py` enforces the rule: a wrapper must call the original, a
replacement must be pinned, and the names of the old copies must not come back.

**Withdrawn, not to be re-added** (each was reverted on every boot until 2026-10-12,
when the machine was found clean): the six earlier versions of the claim patch, three
earlier versions of the bosstip patch, tacetshot v1, count v1, nowave v1/v2/v3a/v3b,
`farmerr` (its premise was wrong - OK-WW's own `error()` already prints the stack),
`shot` / `shot2` / `teamshot` (evidence screenshots whose questions have been
answered), 「领奖顺序」, the two `DomainTask` patches, and `starve`. Why text patches
were given up - versions stacking on their own anchors, silent 「贴不上」 - is in
`docs/CODE-HISTORY.md`「okww_patch.py:ensure_patches」 and `docs/PITFALLS.md`.

---

## History (out of date, kept for the upstream detail)

Patched file: `D:\ark\okww\data\apps\ok-ww\working\src\task\DailyTask.py`
Backups: `.bak-20260825-132036`, `.bak3-20260825-133303`
**OK-WW's auto-update overwrites these changes** (updates come over CNB git). Until upstream merges
them, they have to be re-applied after every update.

Upstream repository: <https://github.com/ok-oldking/ok-wuthering-waves> (★7154)

---

## Patch 1: make `ensure_main` conditional

### Upstream already has a version of this, and it is broken

In `DailyTask.run()`, first seen 2026-06-16 (PR #1393, author `1w1w11w1`):

```python
self.get_task_by_class(NightmareNestTask).ensure_main = lambda *args, **kwargs: None
...
finally:
    self.get_task_by_class(NightmareNestTask).__dict__.pop('ensure_main', None)
```

That turns `ensure_main` into a no-op **unconditionally**. But `NightmareNestTask.run()` goes:

```
ensure_main() → _init_queue() → get_nest_to_go() → openF2Book("gray_book_boss")
```

With `ensure_main` disabled, the task **can never get back to the main screen**. If the screen is
not already on the main screen when the task starts, `openF2Book` is bound to fail →
**`can't find gray_book_boss`**.
**Upstream suppressed too much, and that is the bug itself** — this is not a case of "upstream
already fixed it and we are duplicating the fix".

### Our version

```python
nest_task = self.get_task_by_class(NightmareNestTask)
_real_ensure_main = nest_task.ensure_main
def _ensure_main_keep_book(*args, **kwargs):
    if nest_task.find_one('gray_book_boss', box='box_gray_book', threshold=0.3):
        return None                                 # 书开着 → 别关
    return _real_ensure_main(*args, **kwargs)       # 书没开 → 真的回主界面
nest_task.ensure_main = _ensure_main_keep_book
```

It stays out of the way only while the book is already open; otherwise it returns to the main
screen as before. A strict improvement.

### The only test that decides whether it works

**Run the dailies once and see whether `can't find gray_book_boss` still shows up. If it does not,
it works — file the PR.**
Not "verify that the patch was executed".

---

## Patch 2: move the additional tasks ahead of reward claiming

Upstream order (end of `DailyTask.run()`):

```
claim_daily() → claim_mail() → claim_battle_pass() → run_additional_tasks()
```

The additional tasks (including 周常乐园, `CHECK_WEEKLY_GARDEN`) run last. The problem: finishing
the weekly **leaves rewards to collect**, but by then reward claiming has already run. We moved
`run_additional_tasks()` ahead of `claim_daily()`.

**Note that the upstream order is deliberate** — it is stated in `config_description`:

> "Nightmare Nest runs before stamina farming to help complete the daily task;
> **the other tasks run afterward.**"

**So the PR has to be phrased as "make it configurable", not as a straight reordering**, or the
author will most likely refuse it.

---

## Planned feature: farm specific 残象聚落 sites

**Half of the plumbing already exists** — `find_nest()` computes a unique identifier for every
site, and a "skip these sites" mechanism is already running:

```python
cache_key = f'{action_name}:{denominator}:{row_slot}'   # 例如 go_nest:41:23
if cache_key in self._unreachable_nests:                # 传送不过去的点位就是这么跳掉的
    continue
```

**What is missing is a name a human can pick.** `cache_key` is derived from position
(action name:denominator:row slot) — usable by the machine, impossible for a person to type.
The OCR region of `find_nest()`, `(0.35,0.13)→(1,0.96)`, already covers the whole row; it is just
filtered down with `match=self.count_re` so only counters like `0/41` survive — **the site name on
that same row is right next to it**.

Three steps to implement:
1. Once the counter box is located, run OCR again on the left part of the same row without the
   filter, to get the site name
2. Add a config option `'Which Nests to Farm'` (`multi_selection`, empty = farm everything, which
   keeps the current behaviour)
3. Add a name allowlist filter next to the existing `if cache_key in self._unreachable_nests` —
   reusing the mechanism that is already there, without touching the main flow

A fragile spot worth reporting in the same PR:

```python
if numerator != denominator and denominator in ['24','36','48','41'] and numerator == '0':
```

The denominator is a **hard-coded allowlist** (a new site with `0/52` would be invisible), and
`numerator == '0'` means **a half-cleared site is never resumed**.

---

## Things not to look into again

- `Which to Farm` (the multi-select of `NightmareNestTask`) **was set to 残象聚落 only long ago**,
  with 梦魇净化 removed. See memory `okww-already-configured`.
- `Which Tacet Suppression to Farm` / `Which Forgery Challenge to Farm` are ready-made
  "farm the Nth one" options; they only apply to 无音清剿 and 凝素领域, not to 残象聚落.
