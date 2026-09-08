# The Tacet Discord Nest has two modes, and the one we have always run is "grab a single echo"

**Established 2026-08-29. It is not a fixed choice, it is a checkbox in the UI that we never ticked.**

## The two branches (`working/src/task/DailyTask.py:85-106`)

```python
condition1 = AUTO_FARM_NIGHTMARE_NEST in additional_tasks   # 'Auto Farm all Nightmare Nest'
condition2 = self.config.get('Farm Nightmare Nest for Daily Echo')

if condition1:    self.run_task_by_class(NightmareNestTask)  # 刷满
elif condition2:  ...run_capture_mode()                      # 抓一个声骸就停
```

Our master config has `Additional Tasks = []` and
`Farm Nightmare Nest for Daily Echo = True`, so it takes the `elif` branch and
**runs exactly one round before calling it a day**.

## Why capture mode "finishes after two kills" - two layers both stop it

```python
def run_capture_mode(self):
    ...
    while nest := self._next_nest_with_progress():
        self.combat_nest(nest)
        if self._capture_success:
            break                    # ① 抓到一个声骸 → 整段结束

def _should_continue_combat_after_pickup(self):
    return not self._capture_mode and self.wait_combat(...)
                                     # ② 捕获模式恒为 False → combat_nest 打完一轮就 break
```

① one echo captured, and the whole loop ends. ② in capture mode this is always
False, so `combat_nest` breaks after a single round.

The switch's own description says it too:
`'Farm 1 Echo from Nightmare Nest to complete Daily Task when needed.'`
- **"Farm 1 Echo": it is designed to farm exactly one**, to satisfy the daily,
not to clear the nest.

## Measured on the 08-28 morning round (`history/2026-08-28/wuwa/OK-WW-09-34-19.log`)

```
13:36:24  已击败残象：0/41 is not complete
13:37:25  farm echo yolo find False
13:37:25  no echo collected, re-teleport to current nest as fallback   ← 重新传送是捡声骸兜底
13:38:19  已击败残象：2/41 is not complete
13:40:06  已击败残象：6/41 is not complete
13:40:47  Captured echo during combat, skipping search.                ← 只有捕获模式才打这行
13:40:48  ForgeryTask 开始                                             ← 6/41 就换任务了
```

(The annotations: the re-teleport is the fallback for picking an echo up; the
"Captured echo during combat" line is only printed in capture mode; the task
switched away at 6/41.)

**Those re-teleports are not "only a few monsters spawn"** - I said that once,
it was wrong, and the operator corrected it on the spot. They are the fallback
re-teleport inside `combat_nest` when no echo was picked up.

## The same task has two entry points, and they behave completely differently

| Entry point | Which method it takes | Behaviour |
|---|---|---|
| AUTO-MAS queue (`main.py -t 1`) -> **daily task** | `DailyTask` -> `elif condition2` -> `run_capture_mode()` | stops after grabbing one echo |
| The start button for 「噩梦巢穴任务」 in the UI / `okww-task.sh <index>` | `NightmareNestTask.run()` | farms until the nest is cleared |

The line in memory [[okww-nest-truth]] about clearing four sites in one night
(「一晚清空四个点位」) is about **the second** entry point, not the one the queue
runs. Both are true; do not use one to disprove the other.

## ⚠️ The counter in the log is not evidence of progress

In `已击败残象：0/41` the `0` **may be OCR having swallowed the leading digit**
(the real value being 10/41). On 2026-08-29 I took a run of `0/41` lines in the
08-26 log and asserted "no site has ever been cleared" - wrong, and the first
line of [[okww-nest-truth]] warns about exactly this in plain words.
**Judge progress from the game screen, not from that number in the log.**

## How to change it

Master config `<automas>/data/c5e96ddc-…/Default/ConfigFile/DailyTask.json`:

```json
"Additional Tasks to Run After Daily Task": ["Auto Farm all Nightmare Nest"]
```

* **The relay will not clobber it**: `garden.py:enforce()` reads the whole list
  and only adds or removes the single element `"Check Weekly Garden"`, leaving
  the rest as it is.
* `Only Farm These Nests = '落渊南丘'` still applies - the clear-the-nest mode
  goes through `find_nest` as well, so the standing order [[okww-only-nanqiu]]
  is unaffected.
* Leave `Farm Nightmare Nest for Daily Echo` alone: `if condition1` wins, and
  the `elif` is never reached again.

**The cost**: clearing all 41 is far slower than grabbing one echo, and it eats
into the morning queue's time. Work that out before making the change.

## Can the UI do it? Yes. Three questions answered together

| Question | Answer | Basis |
|---|---|---|
| Can really nothing be changed from the UI? | **It can**: `ADDITIONAL_TASKS` is `multi_selection`, four checkboxes | the `config_type` in `DailyTask.__init__` |
| Does our patch show up in the UI? | **Yes**: `Only Farm These Nests` carries a `config_description`, which ok-script renders as a text box with help text | `NightmareNestTask.__init__:59-61` |
| Is it just that a headless API cannot set it? | **No**: the config is plain text in `configs/*.json`, and AUTO-MAS copies the whole master config over on every round, so editing the master is enough | `AutoProxy.py:514-515` |

## That checkbox's label is misleading (settled 2026-08-29)

In the UI it is called 「**自动刷所有梦魇巢穴**」 ("auto farm all nightmare
nests"), but it **does not control what gets farmed**, only which method runs:

```
勾上  → run_task_by_class(NightmareNestTask) → run()   刷满模式（_capture_mode=False）
不勾  → run_capture_mode()                             抓一个声骸就停
```

Ticked: the clear-the-nest mode (`_capture_mode=False`). Unticked: stop after
grabbing one echo.

(`ok/task/task.py:1111 run_task_by_class` -> `task.run()`, verified.)

The scope is decided by **the nightmare-nest task's own two options**, which we
set long ago:

* `Which to Farm = ['Tacet Discord Nest']` - Tacet Discord Nests only,
  **nothing to do with Nightmare Eradication**
* `Only Farm These Nests = '落渊南丘'` - that one site only

So "clear only the Tacet Discord Nest at 落渊南丘" **needs no code at all**, just
the checkbox. Once it is cleared `find_nest` returns None, the log says
「指定点位都已打满，跳过」 and the task finishes - which satisfies the standing
order [[okww-only-nanqiu]].

**Changed** (both the master config and the live copy):
`"Additional Tasks to Run After Daily Task": ["Auto Farm all Nightmare Nest"]`

## ⚠️ Killing OK-WW means killing pythonw too

`ok-ww.exe` is only the pyappify launcher; what actually runs is
`data\apps\ok-ww\python\pythonw.exe ...\working\main.py`.

On 2026-08-29, after `taskkill /IM ok-ww.exe /F`, I reported "no leftover
processes" to the operator - **wrong**: the pythonw child was still alive and
still holding the named mutex `ok-script-<hash>` (its owner recorded in
`%TEMP%\ok-script-<hash>.pid`), so every subsequent start exited with
`RuntimeError: Another application instance is still running` and exit code 1.

When checking for leftovers you **must include `pythonw`**, and judge by the
command line rather than the process name:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' or Name='python.exe'" |
  ForEach-Object { $_.ProcessId.ToString() + ' :: ' + $_.CommandLine }
```

Two tooling traps while we are here:
* `wmic` no longer exists on this machine (removed in recent Windows); use
  `Get-CimInstance`.
* In pwsh, `\"` is not an escape. Inline PowerShell containing quotes must be
  written to a `.ps1` file and run with `-File`, otherwise the command
  **silently returns nothing** - which is how I concluded "there is no such
  process" three times running, all of it false.
