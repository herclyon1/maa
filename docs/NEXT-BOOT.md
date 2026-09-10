# Check these when the machine is next up

## 2026-09-11 — two things landed while the machine was off; one rerun ordered

1. **Relay pushes the phone state in SvcStop** (`relay/service.py`, `boot_stages._start_phone_channel`)
   so a shutdown by hand leaves the page current. Pushed to the repo only (machine was off);
   check the boot self-update took it (code version on the machine vs the pushed manifest),
   otherwise `deploy-relay.sh`. Health check no longer judges medicine count or farm target
   (`scripts/mac/lib/healthcheck.py`) - those are his choices, not health items.
2. **Order: run the full 自动采集 once on 09-11** (Friday - not in the schedule, so it needs
   the day attached). First check whether a MaaEnd release carries #5634
   (`gh release list -R MaaEnd/MaaEnd`); if yes, update, then run through the UI with all 17
   rare routes and Friday added; if not, the API path with the dispatch override
   (`scratchpad collect_api.py` pattern, Friday attached). Route 15/16 ziplines are gone,
   so all 17 should pass; anything that fails now is worth a report - through the 🗄️ export.
3. **MAA MedicineNumb is 999 and ate one potion on 09-10 09:00** - his setting; he was asked
   whether that is intended. Do not touch it.


## 2026-09-10 — MaaEnd v2.28.0-beta.5 cannot gather; wait for the release that carries #5634

Every `AutoCollectRouteNDispatch` node ships disabled and the route options only enable
`RouteNStart`, so `AutoCollectLoop` finds nothing and the task "completes" in ~36 s
(upstream MaaEnd/MaaEnd#5628, fixed on main by #5634 on 2026-09-10, not in any release
yet). The relay now reports it as 「自动采集 真的走了路线」 not done, so it is no longer
green. The 09-10 afternoon rerun went through MXU's API with the Dispatch nodes added
to the override (`scratchpad collect_api.py`, not in the repo); the installed
definition was **not** patched (the sandbox refused the write).

- When MaaEnd updates past beta.5, confirm `D:\ark\maaend\tasks\AutoCollect.json` has
  `AutoCollectRoute4Dispatch` in the Route4 case, then drop this note.
- Until then every morning's 自动采集 will be flagged; that is correct, not noise.

### The three routes that failed in the 09-10 16:56 rerun (evidence on the Mac)

Evidence: `~/Claude/ark-evidence/2026-09-10-collect/` - the whole `debug/` folder of that run
(maafw.log 86 MB, go-service.log, on_error/*.png) plus `nodes.json`. Copied with plain
`scp`; `winrun.sh --get` mangles binaries (a 12.8 MB zip came back as 23 MB).
MaaEnd does **not** re-run a failed route at the end: the `AutoCollectRouteNFailed` nodes at
17:24:19 only report; nothing was retried (I told the user otherwise on 09-10 - wrong).

* **Route1 受蚀玉化叶** (first route right after login, 16:57:13-16:57:42): opened the map,
  landed on the 武陵 region overview, and `__ScenePrivateMapOverviewEnterMapWulingWulingCity`
  never matched its tab templates (`MapOverviewWulingChoose/NotChoose`, ROI bottom-right,
  scores 0.15-0.67 vs threshold 0.9); `__ScenePrivateMapAnyEnterMapOverview` then looped on
  `OtherAreaEnterMapOverview` (0.44/0.51) until the 20 s timeout. Route2 passed the same
  screens one second later, and Route17 at 17:22:50 matched the same templates. On-screen:
  the overview with 「其他地图追踪中…」 in the top-left. No upstream report found for this.
* **Route15 红矛叶** (17:19:38-17:20:41): teleport to 北部禁区-前哨基地 (anchor at map
  [1122, 597.7]) succeeded at 17:20:19; `AutoCollectRoute15AssertLocation`
  (`MapLocateAssertLocation`, target [1117.57, 594.24], zone `Wuling_Base`) failed for 20 s.
  On-screen: standing at the 长距滑索架 with the 「登上滑索架」 prompt. Upstream #5345 (same
  anchor, closed 09-01 by the WorldMap fix #5372) covered the earlier phase (anchor icon not
  found); #5184 (open) is a different symptom. #5559 changed zipline landing localisation
  on 09-06 - possibly related.
* **Route16 协议纹石** (17:20:41-17:22:45): teleport to 天师桩研发中心 (anchor [1455.2, 529.6])
  and the location assert passed; `GotoInteract` (navmesh to [1502, 538.13]) and
  `FindButtonUsing` (OCR 使用) passed; `AutoCollectRoute16Goto` (RUN to [189.72, 282.57] on
  tier `Wuling_L8_382`, then DIG points) failed after 68 s. On-screen: facing a wall next to
  a device with the 「使用」 prompt still up. Route added 09-04 (#5420); no report yet.

Reporting plan (strictly by `docs/UPSTREAM-ISSUE-RULES.md`): wait for the release that
carries #5634, update, tick only Route1/15/16, run through the MaaEnd UI
(`MaaEnd.exe --autostart`, stays open), screenshot the software with the log panel, export
the log bundle with the 🗄️ button (`debug_exports/`), fetch it with scp, then draft
one issue per route, `upstream-post.py lint`, and post only after the user says so.
`autoClearLogsOnLaunch` was switched off on 09-11 so the debug folder survives a relaunch.


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


## 2026-09-09 14:00 — nothing edits OK-WW's source any more

All thirteen changes live in `ok_tasks/ark_overrides.py`. Eighteen bindings, of which
fifteen are wrappers that run upstream's own body inside them; three replace it and
are pinned to its hash (`revive_action`, `click_team_challenge`, `find_nest`). The
nest file replacement was retired and upstream's own file restored.

**Check `C:\ProgramData\ark-okww-overlay.json` after an OK-WW update.** A pinned
replacement that no longer matches refuses to bind, and the relay pushes which one and
why. That is the designed behaviour, not a fault - go and read what upstream changed,
then update the pin deliberately.

### A four-hour 天傀劫煞 farm is running until 17:52
Safeguards, all verified live at 14:00:
- three minutes of log silence relaunches OK-WW, up to 40 times, and the engine now
  carries an alarm for that check so the loop actually wakes for it
- the character revives in place on death, so a death no longer ends the run
- the automatic shutdown is held off while a farm is recorded
- no reward is ever claimed while farming, so no waveplates are spent
- at 17:52 it stops, restores Boss Level 90 and Repeat Farm Count 30, drops the marker
  and pushes a summary including how many times it had to be relaunched
