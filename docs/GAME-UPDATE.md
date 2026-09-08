# Game client auto-update (major version update days)

What the operator asked for on 2026-09-02: on a major version update, the relay updates the
game client itself. Two constraints were fixed the same day: **do not probe every day** (major
versions are rare); **the boot window is too short to install a large package**, so once an
update is detected, let the other games finish first, then update and re-run that one game
on its own.

## Which route each of the three takes

| Game | How we learn an update is needed | How it updates | Who re-runs it |
|---|---|---|---|
| 明日方舟 | Read the official version endpoint once at boot and compare it with the installed version recorded in `state/arknights-client.json` | Download the APK (official direct link, resumable) → `ldconsole launch/installapp` → verify with dumpsys → quit the emulator | MAA is dispatched on its own only if it did not get a successful run that day |
| 终末地 | (1) the official bulletin that day carries a 「版本更新说明」; (2) MaaEnd cannot get into the game that day because the client is out of date (every task fails within 20 seconds, zero completions) | Screen-read the Hypergryph launcher (process `Games`): click 「更新游戏」 → wait for 「开始游戏」 → launch the game once to get past 「请重启游戏」 and the shader compilation → until 「点击任意位置继续」 appears | MaaEnd is dispatched on its own only if it did not get a successful run that day |
| 鸣潮 | Not tracked | OK-WW updates itself through the Kuro launcher (recorded 2026-09-02: update → restart → re-run succeeded) | Not needed |

## Timeline (finalized by the operator 2026-09-03)

1. **At boot**: read the official maintenance/downtime bulletins of all three games (明日方舟
   official site / 终末地 official site / 鸣潮 bulletin endpoint). A game under maintenance
   today: register it as pending an update; if today's queue time falls inside the maintenance
   window (counting another 45 minutes after service resumes), **remove it from the queue
   through the AUTO-MAS API** (item/delete, recorded in `state/queue-skips.json`), so today's
   queue does not run it.
2. **Once the queue has finished and the machine is idle**: a background thread updates the
   client **immediately** — download, install, launch the game through the shader compilation,
   and it counts as ready only when the 「点击任意位置继续」 login screen is reached. If the
   update package has not been released yet, retry every 10 minutes, up to 2 hours after
   service resumes.
3. **Once ready**: if service resumption is still more than 10 minutes away, close the game
   first; at the resumption time wait another 2 minutes, then run that one script as a make-up
   run; when it is done, put the removed script back at its original position in the queue
   (item/add → update → order), then shut down as usual.
4. Only scripts that "did not get a run because of maintenance / could not get into the game"
   or "were removed from today's queue" get a make-up run; ordinary task failures do not
   (the lesson of the evening of 09-02, when a make-up run kicked the operator off mid-session).

## Old timeline (obsolete)

1. **At boot** (after the pre-update): `gameupdate.boot_check` makes only two HTTP requests.
   If the 明日方舟 version differs and there are ≥10 minutes left before the queue, install on
   the spot; if not, register it. If the 终末地 bulletin says there is a version update today,
   register it. Registrations go in `state/gameupdate-pending.json`.
2. **While the queue runs**: nothing. The MaaEnd "cannot get into the game" kind of failure is
   recognized and registered (no alert; it shows as ⏸ in the daily report).
3. **Once the whole queue is done and no script is running**: the engine starts the background
   thread `gameupdate.run_deferred` and updates them one by one; during that time
   `_maybe_shutdown` does not power off.
4. **After the update**: if that script's last attempt of the day did not succeed →
   `commands.run_script` dispatches that one script (not the whole queue); when it finishes,
   accounting and shutdown proceed as usual.

Notifications: `🆕 游戏更新` (success), `🔁 更新后重跑`, `⚠️ 游戏更新没能确认` (which step could
not be confirmed — it never claims success it does not have).

## Desktop helper

`ark_relay/desktop.py`: dispatches a block of Windows PowerShell 5.1 into the desktop session
through an interactive scheduled task — screenshot + the built-in Windows Chinese OCR + click
on whatever text was read.
**This is the only place in the whole repository where 5.1 is allowed**: pwsh 7.6.5 was measured
to be unable to load the WinRT OCR types. Encoding traps: the script is written with a BOM, and
the request/result are explicitly UTF-8.

## 09-03 rehearsal record
- 明日方舟: start LDPlayer → launch the game → click START blind → read 「开始唤醒」; the whole
  sequence ran through on the deployed relay code, 89 seconds.
- Dry-ran the 09-04 boot decision against a real bulletin: 明日方舟 registered as pending an
  update, MAA removed from the morning queue — correct.
- Not yet exercised for real: downloading and installing a new APK (2.1 GB); the popups on the
  first login after an update.
