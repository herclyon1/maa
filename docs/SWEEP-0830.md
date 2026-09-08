# System sweep of the 08-29 evening shift and the 08-30 morning shift

Done 2026-08-30 11:38. **Only three problems had been reported before, because I had only
ever looked at what the monitor pushed at me and had never done a systematic sweep. There
are at least nine.**

Debug mode was turned on before the sweep (until 14:00) so the machine would not power off
partway through - the lesson from the 08-30 morning attempt of "wait for the run to finish,
then investigate", which found the machine already off.

## 1. MAA (明日方舟)

| Symptom | Last night | This morning | Note |
|------|------|------|------|
| `VisionHelper::correct_rect roi is empty, use whole image` | 929 | 873 | **the recognition region was empty, so it degraded to searching the whole image** |
| the same (`roi is empty`, without use whole image) | 84 | 168 | 1041 lines in total this morning |
| `InfrastAbstractTask::current_room_config custom is not enabled` | 28 | 28 | **MAA says the custom base layout is not enabled** |
| `[ERR] skill has no recognition result` | 20 | 21 | an operator's skill icon could not be recognized |
| `[ERR] Unknown task: FightSeries-OldMethodFlag` | 7 | **10** | the program and resource versions do not match, **and the count is rising** |
| `InfrastAbstractTask::on_run_fails` (the base task failing as a whole) | **yes** | **no** | intermittent, not every run |

### Key points

1. **The base failure is intermittent.** On the morning of 08-30 I said "the configuration
   has not been touched, so it will most likely fail the same way this morning"; it did not
   fail this morning. Stop using that as a prediction.
2. **`roi is empty` appears over a thousand times per round**, meaning the region handed to
   recognition was empty and only a whole-image search was possible. This is quite possibly
   the same origin as "the skill cannot be recognized" and "the base task fails", but **I
   have no evidence that it is one root cause.**
3. **`custom is not enabled`, 28 times per round**: MAA believes the custom base
   configuration is off. If the user ever set up a base plan, that plan may not be in effect
   at all. **The configuration needs to be verified; it has not been checked.**

## 2. OK-WW (鸣潮), 18 ERRORs this morning

| Count | Content |
|------|------|
| ×4 | `Hiyuki:clicked liberation but no effect` (the ultimate was clicked and nothing happened) |
| ×4 | `CombatCheck:target_enemy failed, try recheck break out of combat` |
| ×4 | `BaseCombatTask:combat check not in combat` |
| ×2 | `post_message:PostMessage error: (1400, '无效的窗口句柄。')` |
| ×1 | `capture_by_bitblt invalid params: hwnd=0, w=1920, h=1080` |
| ×1 | `start_controller:Game window is not connected BitBlt_True_0x0` |
| ×1 | `waiting for game to start error 鸣潮 is not connected` |
| ×1 | `capture_by_bitblt exception: BitBlt failed` |

The last four are **the game window not being connected yet during startup** (`hwnd=0`), a
boot-time race; it did connect afterwards (that day had 1 × `Daily Task Completed` and
1 × `指定点位都已打满`).
The group above them happens inside combat and **has not been investigated**.

## 3. First run of MaaEnd v2.27.0-beta.1

- The closing marker 「自动执行任务完成」 **is present** and there were 0 ERRORs, so this
  round was fine.
- **But the "every task reached its end" backstop in `outcome.py` now matches nothing.**
  It looks for `任务开始: X` / `任务完成: X`, whereas the v2.27 log writes
  `[Task] 实例 AUTO-MAS: 开始执行任务, 数量: 17` and `[MAA] 启动任务, 实例: automas, 任务数: 16`.
  The code has an `if started:` guard, so it raises no error - **it just silently does
  nothing.**
  There is no 08-29 log to compare against (MaaEnd wipes the debug directory when it
  updates), so **I do not know whether this backstop broke in this version or never worked at
  all.**

## 4. Relay

| Symptom | Count | Status |
|------|------|------|
| `进程启动事件监听退出，改用 120 秒活性检查` | 2 | **fixed** (added resubscription with backoff) |
| `模型不可用，日报回退到结构化排版` | 2 | not investigated |
| `取不到待办文件` | 3 | **log fixed** (a single failed gate no longer alarms; it was actually fetched) |
| `取不到 manifest` / `拿到的清单更旧` | 2 / 4 | the logging on the update side is unchanged, not touched |

## 5. Mistakes I made during the sweep itself, recorded here as well

- The first version of my script reported the number of entries in MaaEnd's `debug/record/`
  directory as "5 error screenshots". Those 5 were in fact **data caches** - `IMS.json`,
  `ElasticGoodsPrices.json`, `CreditShoppingShelfSnapshots.json` and the like - not
  screenshots. Using a directory's entry count as evidence is wrong.

## Addendum: the OK-WW combat errors are the normal state, not a fault

Counted per day on 2026-08-30 (`ok-script.log`):

| Error | 08-27 | 08-28 | 08-29 | 08-30 |
|------|-------|-------|-------|-------|
| `Hiyuki:clicked liberation but no effect` | 3 | 3 | 6 | 4 |
| `CombatCheck:target_enemy failed` | 7 | 5 | 5 | 4 |
| `BaseCombatTask:combat check not in combat` | 4 | 6 | 4 | 4 |
| **✓ dailies finished / 指定点位都已打满** | ✓ | ✓ | ✓ | ✓ |

**Reported every day, completed every day.** These three are retry signals inside OK-WW's
combat; it simply logs its retries at ERROR level. They are not our fault, need no action,
and need no issue filed.

### But there was a real crash on 08-26, which has not recurred since

```
DailyTask.run → ForgeryTask.farm_forgery → DomainTask.farm_in_domain
  → BaseWWTask.walk_to_treasure → walk_to_box          (crashed while walking to the chest)

DailyTask.run → claim_battle_pass → BaseWWTask.ensure_main
  → Exception: Please start in game world and in team!  (not in the world/team state)
```

5 occurrences on 08-26, and **not one from 08-27 through 08-30**.

That day happened to be the day we found the in-game keybinds had been changed and set them
back to default, and also the day `ensure_main` was patched
(see [[wuwa-keybinds-must-be-default]] and [[okww-nest-ensure-main-patch]]).
**The timing matches, but there is no evidence for which of the two fixed it**, and both may
have contributed.
This is recorded so that if it ever comes back, the keybinds and `ensure_main` are checked
first instead of guessing from scratch.

## The daily report using the template is the normal state, not a fault

The WARNING `模型不可用，日报回退到结构化排版` appears every day and reads like something
broken. The user explained on 2026-08-30: **having a model write the daily report is an
abandoned plan (too expensive), and the structured template is the final form and is good
enough for now.** So that is the normal path; it has been downgraded to INFO and the reason
spelled out.
