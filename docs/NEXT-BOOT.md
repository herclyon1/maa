# Check these when the machine is next up

## 2026-09-09 — the 4-cost echo farm now loops; two rough edges left

It runs from the phone page, farms 天傀劫煞 (讨伐强敌 position 1) about one lap a
minute, picks up an echo nearly every lap, spends no waveplates, and stops itself at
the configured clock time. Verified live from 06:02 to 06:10 machine time.

The character dies every ten laps or so. OK-WW used to stop the whole task on a
death - inside a realm its `revive_action` gives up, because there is no teleport
tower to run back to. It now clicks the revive button by its own text and the loop
takes the next lap (`okww_patches/revive.py`). **That patch has not yet been seen to
fire**: it was deployed at 07:21 and no death happened before 07:32. If the log ever
carries 「死亡弹窗上没找到复活按钮」 it also prints everything it read off the screen,
which is what to look at.

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
