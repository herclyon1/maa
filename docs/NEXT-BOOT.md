# Check these when the machine is next up

## 2026-09-09 — the 4-cost echo farm now loops; two rough edges left

It runs from the phone page, farms 天傀劫煞 (讨伐强敌 position 1) about one lap a
minute, picks up an echo nearly every lap, spends no waveplates, and stops itself at
the configured clock time. Verified live from 06:02 to 06:10 machine time.

The character dies every ten laps or so. OK-WW used to stop the whole task on a
death - inside a realm its `revive_action` gives up, because there is no teleport
tower to run back to. It now clicks the revive button by its own text and the loop
takes the next lap (`okww_patches/revive.py`). **Verified live at 08:08**: the character died, the dialog was confirmed, and the loop
took the next lap. Each revive spends one 复苏物品. v1 clicked the dialog's own title
(「选择复苏物品」 contains 复苏) and did nothing; v2 clicks a short 确认 instead, and
only when the dialog is actually on screen. If the log ever carries
「死亡弹窗上没找到「确认」」 it also prints everything it read off the screen.

The relay still relaunches the farm as a backstop after three minutes of log silence,
and the count of relaunches is in the message it pushes when the farm ends. The farm's
two moments (its deadline, and the three-minute liveness check) are now registered as
alarms; before that the loop slept until the next queue alarm and the measured gap was
21 minutes.

### Rough edges, neither blocking
- **`enter_configured_boss_realm_from_f` raises every lap**
  (`Teleport to boss failed: can not find F before entering realm`). The claim
  patch catches it, falls through to the ESC/cancel path, and the next lap starts
  anyway — the loop is not harmed, but the log says 「按 F 重新进一趟」 and then
  fails, which reads worse than it is. Fix by pressing F only when
  `find_f_with_text()` already holds, or by dropping the re-entry call now that the
  fallback is doing the work. Do not touch this while a farm is running.
- **The boss level is forced to 50 while farming.** A boss's level does not change
  whether it drops an echo or the echo's class (the data bank level sets that), so
  the lowest tier is correct for farming. The saved value (90) is restored when the
  farm ends. If a future farm target genuinely needs a higher level, make the level
  a field on the phone page instead of a constant.

### Settled tonight, no action needed
- 天傀劫煞 is reachable only through the 限时提前开放 entry, so confirming its
  spoiler dialog drops the player straight into the arena. Neither of upstream's
  branches fits: there is no fast-travel UI and no team screen, so both raised
  「Teleport to boss failed」. Two patches in `okww_patches/bosstip.py` handle it.
- The character was not stalling after the kill; at level 90 it was being killed,
  with the boss still above half health.
- The launcher no longer leaves a cmd.exe console on top of the game.
- `echofarm.tick` ends the run and pushes a line if OK-WW's log goes quiet for 12
  minutes.


## 2026-09-09 08:25 — 「收工」 lied twice

Pressing 收工 reported 「已收工、配置已还原」 while 鸣潮 was still on screen, twice.
The relay is a service in session 0; `taskkill /F /IM` fired from there does not reach
the game, which runs in the logged-in session under its anti-cheat. Nobody noticed
because the return code was never read.

The kill now goes out the same door the launch does - a .bat run by a scheduled task
in the interactive session - and `stop_okww` counts the processes afterwards and names
whatever is still up instead of claiming success. **The service-side path has not been
exercised yet**: it was deployed at 08:24 and the desktop was already clean. First
chance to see it is the next 收工 pressed from the phone while the game is running.


## 2026-09-09 12:00 — four OK-WW changes moved out of upstream's source files

`okww_overlay.py` installs `ark_overrides.py` into OK-WW's own `ok_tasks/` folder,
which ok-script executes at startup. Four changes now live there and their anchors in
OK-WW's source have been reverted to upstream:

- `FarmEchoTask.revive_action` (revive in place while farming echoes)
- `BaseWWTask.click_on_book_target` (the 限时提前开放 spoiler dialog)
- `FarmEchoTask.teleport_to_configured_boss` (dropped straight into the arena)
- `FarmEchoTask.teleport_to_configured_boss_and_prepare` (let a deliberate skip pass)

Verified on the machine: all four report as applied with nothing skipped, and the
source files match `repo/` byte for byte at those points.

### To check on the next real run
The last three are exercised by the **weekly boss step of the morning daily**, and
they have only been verified to bind, not to behave. If tomorrow's Endfield-free
OK-WW run reports 「Teleport to boss failed」 or a task that should have been skipped
is retried as an error, look here first. `C:\ProgramData\ark-okww-overlay.json` says
what bound; the log lines to grep for are 「限时提前开放」 and 「刷声骸模式」.

### Done: ten of thirteen moved (2026-09-09 12:45)
Only the nest whole-file replacement and the two DailyTask stamina changes still edit
OK-WW's source. Everything else is in `ark_overrides.py`: three wrappers and four
whole-method copies, each copy pinned to upstream's pristine hash. Verified on the
machine - eight bindings applied, nothing skipped.

### 2026-09-09 — do not file the MaaEnd 「silent failure」 issue as first framed
80% of MaaEnd task failures print no reason in the log AUTO-MAS captures. That looked
like an upstream logging bug until the framework log turned up: MaaEnd writes its own
`debug/maafw.log`, 17 MB for a single run, and that is the log upstream's issue
template asks for. The reason is very likely in there; the user-facing log simply does
not repeat it. The framework log for the failing run had already rotated, so this is
not proven either way - prove it before writing anything upstream.

Worth building on our side regardless: when a task fails, keep the matching slice of
`maafw.log` as evidence so the daily report can say why instead of just naming the
step.
