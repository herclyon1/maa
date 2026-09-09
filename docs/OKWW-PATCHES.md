# OK-WW local patches — what changed, why, and what counts as success

> **Corrected 2026-09-08. Everything below the inventory describes a state that no
> longer exists** and was misleading on the one morning it was needed: 09-08's
> failure was an `ensure_main` timeout, and the first section here sends the reader
> looking for a `_ensure_main_keep_book` patch that **does not exist anywhere in the
> code**. Section 2 (「领奖顺序」) is now a deliberate *revert*, not an application,
> and section 3's "planned feature" (choosing which nest to farm) has been shipped
> for weeks. The header's 「Patched file: DailyTask.py」 is wrong too: six files are
> touched. Read the inventory first; treat the rest as history.

## The inventory — what `ensure_patches()` actually does, in order

Source of truth is `relay/ark_relay/okww_patch.py` - the `_APPLIES` and `_REVERTS` tables, read by `active_patches()`, and pinned to this page by `tests/test_patch_inventory.py`; each patch's text
lives in `relay/ark_relay/okww_patches/<name>.py`. Run it and it tells you what it
changed; an empty answer means everything was already in place.

**Applied every boot（10 条）:**

| # | What | Where |
|---|---|---|
| 1 | `NightmareNestTask.py` replaced wholesale with our copy — this is where the fixed `ensure_main` and 「只刷指定点位」 live | `okww_files/NightmareNestTask.patched.py` |
| 2 | Weekly boss runs **before** the daily stamina farming — otherwise the daily step burns all 180 stamina and the three 60-stamina chests are impossible | `okww_patches/stamina.py` |
| 3 | 「这次不刷体力」 marker honoured | `okww_patches/nofarm.py` |
| 1 | The whole `NightmareNestTask.py` file, replaced (it needs a change upstream has no hook for) | `okww_files/NightmareNestTask.patched.py` |
| — | Everything else has moved out of this table, see below |

**Moved out of this table (2026-09-09)**: twelve of the thirteen changes now live in
`okww_files/ark_overrides.tasks.py`, installed into OK-WW's own `ok_tasks/` folder by
`okww_overlay.py`. Nothing there edits an upstream file.

**Each change hooks the smallest method that contains it.** The first shape of that
file carried five whole-method copies, 30 to 90 lines each; upstream ships roughly
every other day, and each copy would have gone stale the first time they touched that
method - the pin would have said so, but the change would have stopped happening.
Hooking one call deeper removes the exposure: 「skip the weekly boss when waveplates
are short」 used to copy a 28-line teleport method and now replaces the three-line
challenge button it calls. Twelve of the fourteen bindings are wrappers that run
upstream's own body inside them; only `revive_action` and `click_team_challenge`
replace it, and both are pinned to its hash.

`test_okww_overlay_copies.py` enforces the rule: a wrapper must call the original, a
replacement must be pinned, and the names of the old copies must not come back.

Only the nest file replacement still edits OK-WW's source, because it needs a change
in the middle of a class upstream gives no hook for; it carries its own pristine
baseline (`NightmareNestTask.upstream.py`) for the same reason.

**Deliberately reverted every boot** (they are listed so an old copy left behind by
an update is removed, and so nobody re-adds them): the six earlier versions of the
claim patch, three earlier versions of the bosstip patch, tacetshot v1, count v1, nowave v1/v2/v3a/v3b, `farmerr` (its premise
was wrong - OK-WW's own `error()` already prints the stack), `shot` / `shot2` /
`teamshot` (evidence screenshots whose questions have been answered), 「领奖顺序」,
the two `DomainTask` patches, and `starve`.

**Why every historical version is reverted before the current one is applied:** the
v1/v2 replacement texts each end with the anchor they matched, so applying a new
version on top stacks another layer instead of replacing it. See
`docs/CODE-HISTORY.md`「okww_patch.py:ensure_patches」.

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
