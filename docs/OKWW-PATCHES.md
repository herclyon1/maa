# OK-WW local patches — what changed, why, and what counts as success

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
