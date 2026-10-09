# Relay error ledger, 2026-09-26 .. 2026-10-10

**Summary: 43 kinds. FIXED 28 · EXTERNAL 12 · ROUTING-ONLY 2 · UNKNOWN 0 · NORMAL-STATE 1 · UNFIXED 0.** Outside the 43 kinds, 4 relay power-offs did not take: 1 settled (aborted at the machine, 10-01), 3 cause unknown (10-02 ×2, 10-03; see the last section).
Of the 28 FIXED, the fix for part of kinds 7/8/19/20/43 is on main but not yet on the machine (cc71a980, 11e385a0), and kinds 9/10/11/21 are fixed in code but the fixed path has not run on the machine since.

## Conventions

- Input: `BOARD/任务证据/报错对账-1010/r0926.log` (relay.log 09-26 00:00 .. 10-10 04:28:47), its 233 WARNING/ERROR/CRITICAL lines grouped into kinds 1-40 (`kinds0926.txt`), plus kinds 41-42 (INFO 「不推送」 lines) and kind 43 (10-10 04:28:47, after the log file ends). "L<n>" is a line number in r0926.log.
- Clocks. Log times are the machine clock = Beijing. Commit times below were converted to Beijing (`TZ=Asia/Shanghai git log --date=format-local`). Deploy tag names `relay-YYYYMMDDhhmmss` are UTC. "Landed" means the machine's own `更新说明已记入当天日报（v<tag>）` line, i.e. when the code actually ran on the machine; for a tag the machine skipped, it is the landing of the first later tag that contains it. The user's rulings in relay/USER-SWITCHES.txt are in Tokyo time.
- "Deployed" means `git merge-base --is-ancestor <sha> relay-20261009021857` (= 7048162f, landed 10-09 10:19:22, L18303), the version the machine runs now. Every sha below is an ancestor of origin/main (fed9a445 at writing).
- Source lines are `file:line` on origin/main fed9a445. Where the wording no longer exists, the commit that changed it is named.
- Verdict rule: a commit counts as removing the root cause only if it changes the code path that produces the condition (or, for kinds 15-17, the machine itself). Lowering a level to INFO, `extra=errwatch.recovered()`, `replay._QUIET`, `known_fixed.KNOWN`, machine checks and push routing are routing, not fixes.
- "Recurred" checks the full log (INFO lines as well, since many wordings were lowered to INFO) after the fix landed.

## Open items: next steps

### ROUTING-ONLY

- **Kinds 5 and 14: the WMI process-start subscription drops (RPC failed 0x800706BE).** Happened 3 times: 10-05 22:45:46, 10-06 16:16:59, 10-06 18:08:22. Each time it was 37-51 s after a deploy restart: the update landed at 22:44:00 / 16:16:08 / 18:07:33 (L16167, L17011, L17183). Root cause unknown. Commit 6ca49eac only changed the line from a pushed ERROR to a recovered WARNING. Commits 372c24c1 and fed9a445 (not deployed) only add the System log's winmgmt events to the diag line. Nothing touches what drops the subscription.
  - Next step: deploy 372c24c1 and fed9a445, then read the System log for 10-05 22:43-22:47 and 10-06 16:12-16:17 and 18:03-18:09 (the last two are listed in docs/NEXT-BOOT.md). Event 7036/7031/7034 for winmgmt shows whether something stopped WMI or it crashed. If a relay boot stage or a deploy-time remote command restarts it (both drops came in the first minute after a restart; 8 other restarts that day did not drop), move or remove that call.
  - Covering tests: relay/tests/test_wmi_listener.py and relay/tests/test_mc_system_fixes.py, plus a new case built from the 7036 sample.

### Settled after the first draft: kind 12 (09-30) and kind 41

- **Kind 12, 09-30 occurrence, and kind 41.** Read from the three COS evidence bundles (2026-09-30_wuwa_OK-WW-05-18-57 / -05-30-24 / -05-40-56: OK-WW's own log, relay.log, a desktop shot) and the relay log:
  - The game was under maintenance. The official notice parsed by relay/ark_relay/maintenance.py:12 gives 「更新维护时间：2026年9月30日04:00 ~ 2026年9月30日11:00（UTC+8）」; the runs started 09:19:15, 09:30:37, 09:41:08 on the machine clock (Beijing = UTC+8).
  - OK-WW could not reach the overworld: run 2 ends in `ensure_main` → 「Exception: Please start in game world and in team!」 (OK-WW-05-30-24.log); run 3 logs 「DailyTask:info_set current task wait main」 at 09:41:15 and nothing more until it was closed at 09:46:41.
  - The morning queue should not have run at all. The user's skip_today at 08:46:37 (L12318) edited QueueConfig.json while AUTO-MAS was up; AUTO-MAS never re-read it and ran the queue at 09:00. Fixed by 3c2e49df (09-30 09:35, deployed): skips go through /api/queue/update and are read back. Not exercised since: the log has no skip_today after 09-30 08:46.
  - The boot check did not pull OK-WW out for the maintenance either: its log stops after the Arknights line (09-30 08:49:50). Root cause: at that version the only Wuthering Waves maintenance source was the in-game notice 「3.7版本内容说明」, which shows from 09-30 09:20, inside the window (commit message of 38462ba6), so the 08:49 boot check had nothing to read and, before 8a47bc39, said nothing. Fixed by 38462ba6 (10-07 01:55, deployed): the official site's 「《鸣潮》3.7版本更新维护预告」, posted 09-23, is read first (relay/tests/test_banners.py:580 holds the 3.7 notice). 8a47bc39 (09-30 15:55, deployed) only makes every branch log a line; that is observability, not part of the fix. 98f37ac7 (keep a window saved earlier the same day) does not apply to that morning: 08:45 was the first boot of 09-30. The maintenance-day path has not run since (no maintenance day for any of the three games' scripts after 09-30 in the log).
  - Run 3 was not a success. It was stopped by the red button at 09:46 and AUTO-MAS wrote 「Success!」 (OK-WW-05-40-56.json), which the relay read as 「重试后成功」 (L44, kind 41) while its own outcome check listed 4 items not done (kind 12). Fixed by 71dd666b (09-30 10:06, deployed: a run inside an estop window is booked as a manual stop, neither self-heal nor success) and 8a47bc39 (gameupdate/resources/report no longer count it as success). Proven on the machine: 09-30 15:11:46 「⏹ 补记：OK-WW 2026-09-30/wuwa/OK-WW-05-40-56（09:46 停一切）这趟是停一切停掉的，记手动停止」 (L12598).
  - Not exercised since: no Wuthering Waves maintenance day has come up after 09-30. Covering tests: relay/tests/test_gameupdate.py, relay/tests/test_outcome.py, relay/tests/test_maintenance.py.

### Still recurring, cause outside our code

- **Kinds 2 and 3 (MaaEnd finished every task but did not exit).** Last seen 10-09 09:33:00. The cause is upstream, in the MXU v2.7.1 callback race (status-中继二 10-10 06:14 and 06:17; issue MistEO/MXU#371, no reply).
  - Our side: the watchdog ends it after 63 s (6ebbd668), and 3e715160 (not deployed) ships the evidence bundle for every such run.
  - A real fix needs an upstream change. Proposing one to upstream means asking the user first, since it would be public posting.

### Fixed on main but not deployed

- cc71a980 (kinds 7, 8, 43 on any shutdown) and 11e385a0 / 87864949 (kinds 19 and 20 on a shutdown the relay did not issue). They go out with the next deploy.
- After that deploy, check the first manual or Windows shutdown: there must be no 「快照的…读不到」 line, and no AUTO-MAS revive before the stop notice.

### Fixed in code, not yet exercised on the machine

- **Kinds 9, 10, 11 (b799746e OCR tolerance).** Since 10-06 21:48:21 (L17442) every #2 machine check says 「没读图：另一来源已给出开启时刻」, so the calendar image has not been read since the fix.
- **Kind 21 (be8582aa Bilibili retries).** There are 0 Bilibili lines after 10-06 06:10.
- **Kind 12, 10-05 part (9ef10d84 / f087e2b6 / dc9a8f46 weekly claim).** No claim read-back on the machine since.
- How to confirm: watch the next version's calendar read (relay/tests/test_banners.py holds the incident lines).

## Entries

### 1. ark.gameupdate 「游戏更新：明日方舟 N 分钟内没读到「开始唤醒」」
- Occurrences: 1, at 10-09 09:54:57.
- What it is: after installing a new Arknights client, the relay starts the game to prewarm it and watches the screen for the login button 「开始唤醒」. It logs this when the button never appears.
  - Source: relay/ark_relay/gameupdate_games.py:635 (now `log.info`).
- Root cause: the install ran inside the 06:00-12:00 maintenance window, so the screen showed the maintenance notice and a 「下载」 popup (L18221-18286, through 09:54:37). The next round, at 10:05:03, then said 「官方版本号还没变（还是 2.7.71），维护中包体还没放出来」.
- Fix: bb58e515 (10-09 10:17), "Arknights prewarm waits out the maintenance window". The prewarm is now owed until the window ends and retried by the 10-minute loop (gameupdate_games.py hunk), and the WARNING became INFO.
  - Deployed: yes (relay-20261009021857, landed 10-09 10:19:22).
  - Proven on the machine: 10:21:18 「维护到 12:00，预热等维护结束」 (L18333), then 12:03:17 「明日方舟预热完成（读到「开始唤醒」）」 (L18370).
- **Verdict: FIXED** (bb58e515; deployed yes; recurred: no).

### 2. ark.handle 「🟠 MaaEnd … 任务全部完成，但跑完没自己退出」
- Occurrences: 2 (10-06 09:53:25, 10-09 09:33:02).
- What it is: the bookkeeping line for a MaaEnd run that finished every task but did not exit. Source: relay/ark_relay/handle.py:479.
- Root cause: upstream MXU v2.7.1 (bundled with MaaEnd v2.31.0-beta.4 .. v2.32.0-beta.5).
  - In the last task's callback, MXU emits "tasks-completed" and then disconnects its agents synchronously (utils.rs:143/146).
  - The framework's running flag is still true at that point (MaaFramework AsyncRunner.hpp:134/147/128), so the UI's single 300 ms re-read sees "running" and its exit condition (App.tsx:925-929) never fires.
  - Sources: BOARD/中继-报错清单-1010.md item 4 and status-中继二 10-10 06:14. The local 10-01 16:58 sample matches.
- Our side:
  - 6ebbd668 (10-01 19:46; relay-20261001120806, landed 10-01 20:08:31) ends such a MaaEnd after 30 s idle.
  - ba6ff907 (10-06 13:49) made the line daily-report-only. That is routing.
  - 3e715160 (10-10, not deployed) uploads the evidence bundle.
- **Verdict: EXTERNAL** (upstream MXU race, MistEO/MXU#371 open and not fixed). The watchdog keeps the queue moving. Still recurring: 10-09 09:33.

### 3. ark.maaend_watchdog 「MaaEnd 卡死（PID N）：判定原因：MaaEnd 所有任务 … 已完成，N 秒后仍没有自己退出」
- Occurrences: 2 (10-06 09:52:54, 10-09 09:33:00).
- What it is: the watchdog's kill line for the same condition as kind 2. Source: relay/ark_relay/maaend_watchdog.py:336, with the text from texts.py:155.
- Root cause and fix: as kind 2. The watchdog itself is 6ebbd668.
- **Verdict: EXTERNAL** (as kind 2).

### 4. ark.phone 「发到手机信箱第一次没成，N 秒后再发一次，发出去了」
- Occurrences: 1, at 10-08 21:49:08.
- What it is: a post to ntfy that timed out and then went through on the retry. Source: relay/ark_relay/phone.py:1123.
- Root cause: a single connection to ntfy.sh (overseas) stalled.
  - The post at 21:48:42 waited out its full 20 s timeout (phone.py:1116), and the retry 3 s later succeeded within 1 s.
  - COS (Shanghai) was reached at the same moment. Source: status-中继二 / 中继-报错清单-1010.md item 6.
- Our side: 2a0c1409 (10-06 02:46; landed 10-06 06:10:04) added the one retry after a pause, and 9e1f2b60 logs the recovery. Nothing was lost.
- **Verdict: EXTERNAL** (network to ntfy.sh). Retry: 2a0c1409. It still pushes when every attempt fails (boot_stages.py:922/938).

### 5. ark.service 「系统的程序启动通知断过 N 秒（远程过程调用失败，0x800706BE），已经自己重新订上」
- Occurrences: 2 (10-06 16:16:59, 10-06 18:08:22).
- What it is: the WMI process-start subscription dropped and the relay resubscribed on its own. Source: relay/service.py:576.
- Root cause unknown.
  - Each drop came about 50 s after a deploy restart: the update landed at 16:16:08 (L17011) and 18:07:33 (L17183). The subscription had been up for about 18 s with 0 events.
  - The diag shows the winmgmt pid changed (3560→2596, 2596→2580), meaning the WMI service itself restarted (中继-报错清单-1010.md item 5).
  - No code in the repo restarts winmgmt. 8 other deploy restarts that day did not drop.
- Commits:
  - 6ca49eac (10-06 04:46, landed 10-06 06:10:04) turned the drop into an INFO line plus one recovered WARNING (daily report only). That is routing. Read in the service.py hunk: it adds the `fault` bookkeeping, the recovered WARNING, `stopping()`'s ERROR for an outage still open at stop, and the 600 s ERROR. The subscribe and resubscribe calls are unchanged.
  - 7253799e also adds a settle wait before a drop is ruled a fault. That explains why the 10-05 drop reads 5 s and the 10-06 drops read 15 s. It still does not touch the cause.
  - 372c24c1 and fed9a445 (10-10, not deployed) add the System log's winmgmt events to the diag. That is diagnosis only.
- Same phenomenon as kind 14.
- **Verdict: ROUTING-ONLY.** The root cause is still there, and the only commits are routing and diagnosis. Next step in the Open items section.

### 6. ark.phone 「开机时没读到手机信箱，手机通道连上后补读到了 N 条指令」
- Occurrences: 1, at 10-06 17:38:10.
- What it is: the boot-time mailbox read timed out, and the relay read the backlog again once the stream connected. Source: relay/ark_relay/phone.py:1305.
- Root cause: the one-shot read to ntfy.sh waited out its full 25 s timeout (phone.py:1184) at 17:37:44-17:38:09, then the re-read 1 s later worked (0 orders) (status-中继二, item 6).
- Our side: 2a0c1409 added the late backlog re-read (before it, those presses were lost; see kind 13), and 9e1f2b60 logs the recovery.
- **Verdict: EXTERNAL** (network to ntfy.sh). Re-read: 2a0c1409.

### 7. ark.snapshot 「快照的 _队列错误 这一段读不到」 / 8. 「快照的 _MAS错误 这一段读不到」
- Occurrences: kind 7: 5 (09-26 08:45:33, 09-29 08:45:30 and 08:45:32, 10-06 06:21:36, 10-06 09:55:06). Kind 8: 5 (09-26 08:45:31, 09-29 08:45:28 and 08:45:30, 10-06 06:21:34, 10-06 09:55:04).
- What it is: the state snapshot taken for the "before stop" push could not read the AUTO-MAS sections. Source: relay/ark_relay/snapshot.py:252.
- Root cause: AUTO-MAS's API was not there while the relay was stopping. The cause differs by date:
  - **09-26 and 09-29, 08:45 (self-update restart).** The dying process kept running the boot stages, because `_stage_selfupdate` returned None after 25b76dd4. AUTO-MAS was not up yet: 「AUTO-MAS 窗口已在、接口还没开」, then 「服务正在停止」 08:45:28, then ConnectionRefusedError [WinError 10061] at L11062-11093. Fixed by c2d14428 (09-29 09:00), which makes `_stage_selfupdate` return True so service.py exits. Landed 09-29 09:02:08 (L12103). No snapshot failure on any self-update restart after (e.g. 10-01 08:45:22, L12717-12723).
  - **10-06 06:21 and 09:55 (the relay's own power-off).** Fixed by b799746e part B (10-06 09:55; landed 10-06 15:48:14): the two sections are skipped once the relay has issued its shutdown.
  - **10-10 04:28:47, a manual Windows shutdown (= kind 43).** Fixed by cc71a980 (10-10 05:36, not deployed): skip on any shutdown (`errwatch.going_down()`).
- Recurred after a deployed fix: yes, 10-10 04:28:47, on the manual-shutdown path that only cc71a980 covers.
- **Verdict: FIXED** (c2d14428 and b799746e deployed; cc71a980 not deployed; recurred: yes, on the undeployed path).

### 9. ark.banners 「鸣潮 N.N 版本活动日历读了 N 行，没找到「余心所向九死未悔」的日期」
- Occurrences: 13 (10-01 17:28:43 .. 10-06 09:53:46).
- What it is: OCR of the Wuthering Waves version activity calendar image found no date for the second-half banner. Source: relay/ark_relay/banners.py:1920 and :1923.
- Root cause: Windows OCR misreads.
  - It dropped characters from the banner name, giving 「余心所向九悔」 for 「余心所向九死未悔」 (visible in the 10-03 21:48:16 line and later).
  - It mangled the date label: 「]0．22」, 「]1月」, 「10．22一]I.11」.
- Fix: b799746e part A (10-06 09:55; relay-20261006020610, landed 10-06 15:48:14).
  - Name matching now tolerates dropped characters (desktop._subseq_miss).
  - The date label is normalised first (banners.py:1816 `_WW_CAL_FIX`, `_WW_CAL_BARE`), with a regression test from the incident lines.
  - 12edfb0b (10-06 13:08, landed 15:58:10) tightened the date range.
  - The cross-check mute (a4db06c1, replay `_QUIET`) is routing and is not counted.
- Not exercised since: every later #2 check reads 「没读图：另一来源已给出开启时刻」 (10-06 21:48:21 .. 10-09 21:40:59).
- **Verdict: FIXED** (b799746e; deployed yes; recurred: no; not yet proven on a real calendar read).

### 10. ark.banners 「这条公告只有图，没读到字」
- Occurrences: 13, at the same instants as kind 9.
- What it is: the calendar notice is image-only and the image read gave nothing usable. Source: relay/ark_relay/banners.py:1940 and :1943.
- Root cause and fix: as kind 9 (same read).
- **Verdict: FIXED** (as kind 9).

### 11. ark.phone_banners 「🔬 上机核对没过：#2 鸣潮版本活动日历图读出第二期卡池的开始日期」
- Occurrences: 2 (10-06 06:20:17, 10-06 09:53:46).
- What it is: on-machine check #2 confirming that the deployed calendar read works. Its failure text is texts.py:763 (`MACHINECHECK_FAIL`).
- Root cause: the kind 9 misread. Fix: as kind 9. After 10-06 15:48 the check passes, but only via the other source.
- **Verdict: FIXED** (as kind 9).

### 12. ark.handle 「⚠️ OK-WW … 有项目没干成」
- Occurrences: 4 (09-30 09:47:10, 10-04 09:26:43, 10-05 10:39:49, 10-06 09:28:13).
- What it is: the outcome check of an OK-WW run found items its log does not prove done. Source: relay/ark_relay/handle.py:583. Each occurrence has its own cause:
  - **09-30 (4 items: nest filter, daily task, nest opened then quit, stamina farm).** The game was in its 3.7 maintenance (04:00-11:00) and the skipped morning queue ran anyway; see the Open items section. The relay log only shows OK-WW refused to start because the game was not in the overworld (kind 41 line, L12541), on the 3.7 maintenance day.
  - **10-04 and 10-05, nest filter not applied (「过滤没拿到点位名，按上游行为刷了全部」).** OK-WW v3.7.x changed its nest code. Fixed by f6b5f432 (10-05 12:24; relay-20261005043358, landed 10-05 21:20:27), "the nest filter follows OK-WW v3.7.3". Proven: 10-06 09:22:16 「nightmare nest: 只刷 ['落渊南丘']（设置来自母本）」 (machine check #5 at 09:28:13).
  - **10-05, weekly boss fought but no claim step.** Fixed by 9ef10d84 (10-05 14:26; landed 21:20:27), with f087e2b6 and dc9a8f46 (landed 10-05 22:10 / 23:28). After 「确认前往」 on an early-open boss it looks where it landed, and the claim is counted only from the read-back. Not exercised on the machine since: the only later weekly run, 10-06, stopped at the waveplate shortage, and the log has no claim read-back line after 10-05 21:20.
  - **10-06, 「结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）」.** A game resource shortage. 3f6b2fbe and 4c1b58aa (10-07 05:30/05:36; landed 10-07 08:45:28) end the run as skipped; USER-SWITCHES.txt:50 cites the user's 2026-10-06 10:34 (Tokyo) 「正常状态报什么？」 → NORMAL-STATE.
- Recurred: no OK-WW 「有项目没干成」 after 10-06.
- **Verdict: FIXED** (09-30: maintenance window plus a skip that did not stick, fixed by 3c2e49df, 71dd666b and 38462ba6, see the Open items section; 10-04 and 10-05 FIXED; 10-06 NORMAL-STATE).

### 13. ark.phone 「取不到信箱里的指令」
- Occurrences: 4 (09-26 21:21:31, 09-26 22:13:55, 10-02 22:48:30, 10-05 23:11:33).
- What it is: the boot-time mailbox read failed. This wording was replaced by 2a0c1409; the INFO line 「开机读手机信箱没成」 and the recovered kind 6 replace it.
- Root cause: `TimeoutError: The read operation timed out` from ntfy.sh, each time in the first minute after a restart, which is the only time this one-shot read runs (L11326, L11484, L14683, L16211). The stream connected 1-3 s later each time.
- Our side: before 2a0c1409 (10-06 02:46, landed 10-06 06:10:04), presses sent during that window were lost. 2a0c1409 re-reads the backlog once the stream answers.
- Recurred: once more, 10-06 17:38 (= kind 6), recovered.
- **Verdict: EXTERNAL** (ntfy.sh read timeout). Re-read: 2a0c1409.

### 14. ark.service ERROR 「进程启动事件监听中断，改用 N 秒活性检查，N 秒后重订阅」
- Occurrences: 1, at 10-05 22:45:46.
- What it is: the old wording of kind 5. It was removed by 7253799e and 6ca49eac; the current lines are service.py:576/605/661.
- Root cause: as kind 5.
  - `pywintypes.com_error … SWbemEventSource 远程过程调用失败 … -2147023170` (= 0x800706BE).
  - The relay started after the update that landed at 22:44:00 and subscribed at 22:45:09; the drop came 37 s later. There was no shutdown (L16179-16205; ERROR at L16191).
- Commits: 6ca49eac only turned it into a recovered WARNING. 7253799e covers only drops during the relay's own power-off, and this was not one.
- **Verdict: ROUTING-ONLY** (as kind 5; it recurred as kind 5 twice on 10-06).

### 15. ark.desktop 「桌面助手读图失败：ERR 使用“1”个参数调用“RecognizeAsync”时发生异常:“参数错误。」
- Occurrences: 3 (10-02 21:48:46, 10-04 21:48:40, 10-05 21:47:47).
- What it is: the Windows OCR helper rejected the image. Source: relay/ark_relay/desktop.py:545.
- Root cause: each of the 3 came seconds after a kind 17 at 21:48:41, 21:48:34 and 21:47:41. With Pillow missing, the poster was handed to Windows OCR unconverted and RecognizeAsync refused it.
- Fix: as kind 17.
- Recurred: 0 RecognizeAsync lines after 10-05 23:11:37.
- **Verdict: FIXED** (as kind 17).

### 16. ark.banners 「B 站版本资讯第 N 张图没读出来，这次不再读后面的图」
- Occurrences: 3, at the same instants as kind 15.
- What it is: the poster reader stops after an OCR-agent failure (22974aad). Source: relay/ark_relay/banners.py:2335.
- Root cause and fix: as kind 15 and kind 17.
- **Verdict: FIXED** (as kind 17).

### 17. ark.banners 「官方图转 PNG 失败，原样交给系统 OCR」
- Occurrences: 9 (10-01 17:28:11 .. 10-05 21:47:41).
- What it is: converting an official image to PNG failed. Source: relay/ark_relay/banners.py:2451.
- Root cause: `ModuleNotFoundError: No module named 'PIL'` on all 9 (e.g. L12882, L16009). Pillow was not installed on the machine.
- Fix: Pillow 12.3.0 was installed on the machine (status-中继二 entry 10-06 00:34 Tokyo).
  - The boot self-check reports 「中继装了读图组件」 from 10-05 23:11:37 (L16248).
  - 9960c184 (10-05 22:57; landed 10-05 23:10:53) adds the self-check that alarms if Pillow goes missing (selfcheck.NEEDED_MODULES) and a known_fixed entry.
  - Machine run 10-05 23:30:40 read 「10-22 10:00 开」 from the 库街区 4th image (status-中继二).
- Recurred: no.
- **Verdict: FIXED** (machine-side Pillow install, guarded by 9960c184; deployed yes; recurred: no).

### 18. ark.banners 「库街区官方资讯里没找到 3.7 版本资讯帖」
- Occurrences: 1, at 10-05 21:47:23.
- What it is: the 库街区 news list had no version-news post. Source: relay/ark_relay/banners.py:2231 (now INFO).
- Root cause: the list was read with pageSize 50; the post sat at about 100 (9960c184 message).
- Fix: 9960c184 sets pageSize to 200 (deployed; landed 10-05 23:10:53).
- Recurred: no (0 lines after, INFO included). Afterwards #58 found the post: 10-06 21:48:21 「库街区官方资讯里找到了这一帖」.
- **Verdict: FIXED** (9960c184; deployed yes; recurred: no).

### 19. ark.service 「AUTO-MAS 后端退出了」 / 20. 「AUTO-MAS 后端不在，正在拉起（第 N 次）」
- Occurrences: 20 each (09-26 01:55:10 .. 10-05 11:32:26).
- What it is: the AUTO-MAS keeper saw the backend exit and relaunched it. The old wording was changed by 7253799e and 9bcf2f69. Current lines: service.py:1228 (power-off, INFO), :1126 (recovered), :1348 (revive).
- Root cause: every one of the 20 happened inside a Windows shutdown. For 19, 「关机途中，进程启动事件监听随系统断开」 follows within 1-19 s; for 10-02 09:55:14 it came 2 s before (09:55:12).
  - 17 followed the relay's own power-off command (「本轮已处理完毕，60 秒后关机」). 15 of them exited 63-72 s after the command; 2 exited hours later (10-01 21:48:52 → 10-02 04:42:36, and 10-03 01:36:06 → 03:50:41).
  - 3 were shutdowns the relay did not issue: 09-26 01:55:10, 09-26 22:26:12 (after 「这一次关机机会已被调试模式吃掉」), and 10-03 21:06:29 (rebooted by 21:20).
  - The keeper treated AUTO-MAS's teardown during shutdown as a crash and relaunched it into the shutdown.
- Fix:
  - 7253799e (10-06 02:52; relay-20261005220948, landed 10-06 06:10:04) handles the relay's own power-off: no revive, logged 「…按关机处理，不算故障，不再重新打开它」. Proven at 10-06 06:21:27, 09:54:59, 10-07 09:55:32, 10-08 11:15:52 and others (machine check #37).
  - 11e385a0 (10-10 05:59, not deployed) handles other shutdowns by reading event 1074 from the System log. 87864949 (not deployed) fixes the wording.
- Recurred: yes, 10-10 04:28:44-45 (manual shutdown). INFO 「AUTO-MAS 后台意外退出了…当时机器没在关机」, then 「中继正在重新打开它」, then 「收到停止通知（Windows 关机）」 one second later (L18459-18461). This is the path only 11e385a0 covers.
- **Verdict: FIXED** (7253799e deployed; 11e385a0 not deployed; recurred: yes, on the undeployed path).

### 21. ark.banners 「B 站鸣潮官号动态第 N 页：code=0，0 条，没找到版本资讯」
- Occurrences: 8 (10-01 17:28:38 .. 10-05 11:31:06).
- What it is: Bilibili's feed returned an empty page. The wording was removed by be8582aa; now `BiliFeedProblem` and banners.py:2198-2205 (INFO).
- Root cause: Bilibili's silent risk control. The same signed request alternates between a full page and `{"code":0,…,"items":[]}` (be8582aa message, from responses recorded on 10-05).
- Our side: be8582aa (10-06 00:54; landed 10-06 06:10:04) retries up to 5 times with a new buvid, pages up to 12 (the 3.7 post was already on page 3), and reads 库街区 first.
- Not exercised since: 0 Bilibili lines after 10-06 06:10, because the notice text answers first (9960c184).
- **Verdict: EXTERNAL** (Bilibili risk control). Retry: be8582aa. A page that stays empty raises `BiliFeedProblem`.

### 22. ark.banners 「库街区 <post> 的长图里没读到「余心所向九死未悔」的唤取时间」
- Occurrences: 10 (10-01 17:28:34 .. 10-05 11:31:02).
- What it is: the 库街区 version-news long image gave no time for the banner. Source: relay/ark_relay/banners.py:2346 (now INFO).
- Root cause:
  - Pillow was missing, so the long image could not be cut and read (kind 17).
  - Windows OCR reads 「～」 as 「、」 (1ffbcd76 message; the fixture ww-3.7-news-4-winocr.json is a real machine read).
  - The empty result was cached between runs (22974aad), which explains the occurrences without a kind 17 next to them.
- Fix: the Pillow install (kind 17) plus 1ffbcd76 (10-05 23:27; relay-20261005152914, landed 10-05 23:29:42). Proven on 10-05 23:30:40, when the machine read the 10-22 10:00 start from the 4th image (status-中继二).
- Recurred: no (0 lines after, INFO included).
- **Verdict: FIXED** (Pillow plus 1ffbcd76; deployed yes; recurred: no).

### 23. ark.phone 「手机通道断了，N 秒后重连」
- Occurrences: 4 (10-01 11:42:34, 10-01 12:23:17, 10-05 11:17:10, 10-05 11:17:21).
- What it is: the ntfy long-poll stream dropped. Source: relay/ark_relay/phone.py:1434 (now INFO).
- Root cause: ntfy.sh's side.
  - The 10-01 drops were `TimeoutError: The read operation timed out` on the open stream (L12785, L12813).
  - The 10-05 drops were `HTTP Error 502: Bad Gateway` and `ConnectionResetError [WinError 10054]` (WARNING at L15815 and L15835; exceptions at L15834 and L15876).
- Our side: 2a0c1409 reconnects with since=<last line read>, so nothing is lost; the earlier fixed 10 m replay could lose lines. An outage of 10 min or more stays one pushed WARNING.
- Recurred: once, 10-09 13:15:03 INFO, reconnected 6 s later.
- **Verdict: EXTERNAL** (ntfy.sh). Reconnect: 2a0c1409.

### 24. ark.phone 「状态没能发到信箱：ntfy 回 429 42908 limit reached: daily message quota reached…（本机今天记了 0 条…）」
- Occurrences: 14 (10-02 21:16:27 .. 10-03 01:36:06).
- What it is: a state post was refused because ntfy's daily quota was used up. The wording was removed by 2a0c1409; the current fallback is phone.py:1048 (recovered: 「状态已存到腾讯云」).
- Root cause: the relay exceeded ntfy.sh's 250 messages/day per IP. Each state was 4 message pieces (「切成 4 条普通消息发」), every phone refresh sent a full state, and heartbeats went over ntfy too.
  - The quota ran out by 10-02 19:19 (kind 34).
  - The new local ledger started at 0 that day ("本机今天记了 0 条") while ntfy already counted 250.
- Fix:
  - 1ad63911 (10-02 21:11; landed 10-02 21:16:10): one ledger, coalesced refreshes, no 429 retry.
  - 3bba2d90 (10-02 21:30; landed 10-02 22:47:37): the state goes to COS whole, and ntfy gets a one-line notice.
  - 06dede1d (10-02 23:24; landed 10-02 23:29:38): the heartbeat is also on COS.
  - 2a0c1409 (landed 10-06 06:10:04): ntfy's own count is read from GET /v1/account, ntfy beats stop at 200 and notices at 230.
- Recurred: 0 lines with 429 or 42908 after 10-03 01:36:06. Daily ntfy peak since then: 117 (10-09).
- **Verdict: FIXED** (1ad63911 + 3bba2d90 + 06dede1d + 2a0c1409; deployed yes; recurred: no).

### 25. ark.service 「状态没能上报到手机（关机前；今天 ntfy 已发 N 条）」
- Occurrences: 3 (10-02 21:49:01 .. 10-03 01:36:06).
- What it is: boot_stages.publish_state's line when the state reached neither route. Source: relay/boot_stages.py:922 and :938.
- Root cause: the quota day of kind 24 (each line sits next to a 429). Fix: as kind 24.
- **Verdict: FIXED** (as kind 24).

### 26. ark.phone 「心跳没能写到腾讯云 COS（<urlopen error timed out>），ntfy 心跳照旧」
- Occurrences: 1, at 10-03 00:16:44.
- What it is: one COS heartbeat write timed out. Source: relay/ark_relay/phone.py:588 (now INFO).
- Root cause: a network timeout to COS. The next beats worked: 「心跳又写得进腾讯云 COS 了」 at 00:18:47.
- Our side: 9e1f2b60 (landed 10-06 06:10:04) logs a recovered WARNING and pushes once if COS stays down 600 s.
- Recurred: no.
- **Verdict: EXTERNAL** (network). Retry: the 30 s beat loop. Outage push: 9e1f2b60.

### 27. ark.service 「状态没能上报到手机（手机请求；…）」
- Occurrences: 7 (10-02 22:56:22 .. 10-03 00:13:23).
- Same line as kind 25 (boot_stages.py:922/938), reason 「手机请求」. Root cause and fix: as kind 24.
- **Verdict: FIXED** (as kind 24).

### 28. ark.runwatch 「⏰ 晚班 21:30 开跑，23:43 还没跑完（计划 19 分钟 + 30），已告警」
- Occurrences: 1, at 10-02 23:43:30.
- What it is: the shift-overrun alarm. Source: relay/ark_relay/runwatch.py:332.
- Root cause: a false attribution in our code.
  - The 21:30 shift had finished: 「✅ MAA 2026-10-02/arknights/MAA-17-30-03（17 分钟）」 at 21:48:10.
  - The runs from 23:40 were a person's own 自动肉鸽 runs started from AUTO-MAS's screen: 10 runs, 10 failures, and 「🔎 2026-10-03 已推送「手动执行」」 at 01:35:58.
  - runwatch counted them as the evening shift.
- Fix: 4b08a8af (10-05 12:28) reads 触发来源 from AUTO-MAS's app.log, so a hand-started run is reported but never alarmed, and the overrun counts only the timer-started task. 485d0cc4 (10-05 12:34) makes a run hand-started only when every open task is. Both are in relay-20261005043358, landed 10-05 21:20:27.
- Recurred: no.
- **Verdict: FIXED** (4b08a8af + 485d0cc4; deployed yes; recurred: no).

### 29. ark.service 「状态没能上报到手机（开机；…）」
- Occurrences: 4 (10-02 21:16:27 .. 23:29:51).
- Same line as kind 25, reason 「开机」. Root cause and fix: as kind 24.
- **Verdict: FIXED** (as kind 24).

### 30. ark.phone 「ntfy 今天的 250 条额度用完了（…本机今天记了 0 条），心跳停到北京时间 8 点额度恢复」
- Occurrences: 3 (10-02 22:47:35 .. 23:29:36).
- What it is: the quota-exhausted notice. Its current form, once per UTC day, is phone.py:391.
- Root cause and fix: as kind 24. The "记了 0 条" mismatch was removed by 2a0c1409's Quota.sync.
- **Verdict: FIXED** (as kind 24).

### 31. ark.maintenance 「维护公告：终末地 取不到」 / 32. 「维护公告：明日方舟 取不到」
- Occurrences: 1 each (10-02 23:05:54, 10-02 23:05:34).
- What it is: an official maintenance-bulletin site did not answer. The current lines are maintenance.py:67 (retry, INFO) and :269 (both tries failed, WARNING).
- Root cause: `TimeoutError: timed out` from the official site (L14739, L14800; maintenance.py:57 `arknights_window`). ntfy.sh answered in the same minute (429 at 23:06:15), so the machine had network.
- Our side: 2a0c1409 (landed 10-06 06:10:04) adds one retry and caches results (1 h; failures 5 min), so not every state push fetches all three sites. 9e1f2b60 logs a retry success as recovered.
- Recurred: no.
- **Verdict: EXTERNAL** (official site timeout). Retry and cache: 2a0c1409. Both tries failing still pushes (maintenance.py:269).

### 33. ark.phone 「第 N/N 片没发出去，这一份状态剩下的 N 片不发了」
- Occurrences: 2 (10-02 21:16:27, 21:49:01).
- What it is: a multi-piece state was abandoned after a piece failed. Source: phone.py:1019 (now INFO).
- Root cause: the quota day (each sits next to a 429). Fix: as kind 24; since 3bba2d90 the state is not split over ntfy at all.
- **Verdict: FIXED** (as kind 24).

### 34. ark.phone 「状态没能发到信箱（试了 N 次）」
- Occurrences: 52 (10-02 19:19:08 .. 20:54:06).
- What it is: the pre-1ad63911 wording of a failed state post, removed by 2a0c1409.
- Root cause: `urllib.error.HTTPError: HTTP Error 429: Too Many Requests` (from L13326 onward). ntfy's daily quota was spent by 19:19 on 10-02, and the old code retried every 429.
- Fix: as kind 24. 1ad63911 removed the 429 retry.
- **Verdict: FIXED** (as kind 24).

### 35. ark.handle 「⚠️ MaaEnd … 有项目没干成」
- Occurrences: 3 (09-30 15:48:39, 10-01 17:27:45, 10-01 17:27:48).
- What it is: the outcome check of a MaaEnd run. Source: relay/ark_relay/handle.py:583.
- Root cause per occurrence:
  - **「MaaEnd 跑完：日志里没有「自动执行任务完成」」 (all three).** This is the kind 2 no-exit condition before 56a9fc00 (10-01 19:30) split 「全部完成但没自己退出」 off from 「没干完」. The 10-01 16:58 MaaEnd-12-11-12 MXU log ends with tasks-completed and no 「关闭自身」, and 09-30 15:46:38 has the same shape (中继-报错清单-1010.md item 4).
  - **10-01 MaaEnd-11-23-07, 「开了没收尾：🛍️信用点购物」 with error screenshot MapNavigatorObstacleDevice_InteractPost.** MaaEnd's own map navigation failed. AUTO-MAS retried, and the third attempt passed (kind 42).
- **Verdict: EXTERNAL** (upstream MXU race, as kind 2, and MaaEnd's own navigation failure). Our side: 56a9fc00 and 6ebbd668; retries by AUTO-MAS.

### 36. ark.service ERROR 「预更新有 1 项没能确认：· MAA 预更新：180 秒内没给出更新结论」
- Occurrences: 1, at 09-29 08:50:34.
- What it is: the pre-update summary. Source: relay/boot_stages.py:1207.
- Root cause: kind 37.
- **Verdict: FIXED** (as kind 37).

### 37. ark.preupdate 「预更新：MAA 在 180 秒内没给出更新结论，照常继续」
- Occurrences: 1, at 09-29 08:49:14.
- What it is: MAA, started for the pre-update, wrote no update verdict within 180 s. Source: relay/ark_relay/preupdate_maa.py:196.
- Root cause: our self-update restart.
  - The dying process (`_stage_selfupdate` returned None after 25b76dd4) launched MAA at 08:45:51 (L12038) and was then force-exited (kind 38) with MAA still open.
  - The new process's launch at 08:46:14 became a silent "secondary launch" (c2d14428 message).
- Fix: c2d14428 (09-29 09:00; landed 09-29 09:02:08).
  - `_stage_selfupdate` returns True so the old process exits.
  - `_stage_preupdate` does nothing while stopping.
  - `run_maa` closes a leftover MAA first.
  - Test: relay/tests/test_selfupdate_exit.py.
- Recurred: no.
- **Verdict: FIXED** (c2d14428; deployed yes; recurred: no).

### 38. ark.service 「停止 15 秒后进程仍未退出，硬保险强制退出。各线程卡在：」
- Occurrences: 3 (09-26 08:45:39, 09-26 21:20:41, 09-29 08:45:57). All three were self-update restarts.
- What it is: the 15 s hard exit on stop. Source: relay/service.py:805.
- Root cause: the same as kind 37. The main thread [Dummy-1] of the dying process was still inside boot stages:
  - 09-26 08:45: a TLS handshake (L11178-11187).
  - 09-26 21:20: an HTTPS read.
  - 09-29 08:45: `boot_stages._stage_preupdate`, then `preupdate_maa._maa_await_verdict` (L12040+).
  - The restart had already been requested (「代码已更新，重启以立即生效」 at 08:45:21, 21:20:23 and 08:45:23).
- Fix: c2d14428. b799746e part F also drains the push thread before `os._exit`.
- Recurred: no. Not one hard exit in about 40 restarts after 09-29 09:02.
- **Verdict: FIXED** (c2d14428; deployed yes; recurred: no).

### 39. ark.banners ERROR 「卡池预告没通过来源核对，扣下：… 官网已发「心」的战斗演示（09-26） ← 日期 09-26 没有来源把它当作开始时刻」
- Occurrences: 1, at 09-26 21:46:53.
- What it is: the banner section's source gate held a line. The current form is banners.py:641; the wording was changed by 28aafe8c.
- Root cause: a false positive in our gate. 09-26 was the publication date of the cited combat-demo article, not a start time.
- Fix: c65a72ad (09-26 21:50; landed 09-26 21:51:39), "banners gate accepts a cited article's publication date".
- Recurred: no.
- **Verdict: FIXED** (c65a72ad; deployed yes; recurred: no).

### 40. ark.banners 「PRTS 取不到 卡池一览/限时寻访」
- Occurrences: 1, at 09-26 21:46:44.
- What it is: the PRTS (MediaWiki) API call for the Arknights banner table failed. The current lines are banners.py:1223 (INFO) and :1227 (both failed, WARNING).
- Root cause: `HTTP Error 503: Service Temporarily Unavailable` from PRTS (L11375-11397).
- Our side: a7eb4953 (09-26 22:11; landed 09-26 22:12:58) reads PRTS's rendered page when the API fails. b73c82fc (10-06 18:19) reads every official post.
- Recurred: no.
- **Verdict: EXTERNAL** (PRTS 503). Fallback: a7eb4953. API and page both failing still pushes.

### 41. ark.notify INFO 「不推送（日报或手机页已有）：⚠️ OK-WW 中途失败过，重试后成功」
- Occurrences: 1, at 09-30 09:47:17.
- What it is: a held OK-WW failure whose retry went through, which goes to the daily report only. Source: texts.py:277 and handle.py:_flush_pending.
- Underlying failure: attempts 1-2 failed with 「开跑时游戏不在大世界、或者没有出战队伍」 (kind 12, 09-30 part: the game was under maintenance).
- **Verdict: FIXED.** The "retry" that passed was run 3, which the red button stopped at 09:46 and AUTO-MAS logged as Success!. 71dd666b (deployed) books such a run as a manual stop, and the relay back-booked this very run so at 09-30 15:11:46 (L12598). The routing rule itself (a real self-heal goes to the daily report only) stays: relay/USER-SWITCHES.txt:24.

### 42. ark.notify INFO 「⚠️ MaaEnd 中途失败过，重试后成功」
- Occurrences: 1, at 10-01 17:27:54.
- What it is: as kind 41, for MaaEnd. The first attempt failed at 16:11 with 15 items; the third passed.
- Underlying failure: see kind 35.
- **Verdict: NORMAL-STATE** (as kind 41).

### 43. ark.snapshot 「快照的 _MAS错误 这一段读不到」 (10-10 04:28:47)
- Occurrences: 1, at 10-10 04:28:47. Not in r0926.log: the uploaded log ends at the 04:28:47 bye.
- What it is: kind 8 on a manual Windows shutdown. Source: snapshot.py:252.
- Root cause: AUTO-MAS had already exited.
  - 04:28:44 「AUTO-MAS 后台意外退出了」, 04:28:45 「收到停止通知（Windows 关机）」 (L18459-18461).
  - The deployed skip (b799746e) only covers the relay's own shutdown.
- Fix: cc71a980 (10-10 05:36) skips on any shutdown via `errwatch.going_down()`; the test in relay/tests/test_snapshot.py adds "manual shutdown" and "shutdown starts mid-read". Not deployed.
- **Verdict: FIXED** (cc71a980; deployed no; recurred: n/a, not deployed yet).

## Seen in passing (not one of the 43 kinds): relay power-offs that did not take

Four of the relay's own power-offs (「本轮已处理完毕，60 秒后关机」) did not take; every other one since 09-26 completed in 63-72 s (every one from 10-04 to the end of this log among them).
- **10-01 21:48:52 → down 10-02 04:42:36. Cause: aborted at the machine.** From the System log read that night (BOARD/status-中继一.md, 10-01 22:52 line): 1074 at 21:48:52 (the relay's command), Kernel-Power 566 「Reason InputHid」 at 21:49:36 (keyboard/mouse input at the machine), 1075 「关机请求被 INS\Administrator 取消」 at 21:49:52, then Games at 21:49:59 and Endfield at 21:50:07. The 566 is what shows a person; the account alone would not, since a remote `shutdown /a` runs as the same account. Who powered it off at 04:42 is unread (docs/NEXT-BOOT.md).
- **10-02 21:49:01 (up at 22:47:33, when a deploy restarted the service), 10-02 22:58:05 (relay still logging at 23:05:34), 10-03 01:36:06 → down 03:50:41. Cause unknown.** No System log read exists for these. Not the Mac-side `shutdown /a` in scripts/mac/order-now.sh: that came with 30c1ce95 on 10-09. Before 8d742d3b (10-07, deployed) a command Windows refused still logged 「60 秒后关机」, so a refusal is not ruled out either. docs/NEXT-BOOT.md 「2026-10-11 boot - relay power-offs that took hours」 lists the events to read (1074/1075, Kernel-Power 566, the final 1074s). If the log no longer reaches back that far, these stay unknown.
- What the relay does now. Since 0b67d6dd (10-06, deployed) a power-off still not down 10 minutes after the command is pushed (「…没有关下去」); since 8d742d3b a refused command is an ERROR, not a 「60 秒后关机」 line. Neither has fired since (0 lines). relay1-shutdown-cancel (this change, not deployed) reads 1074/1075 at that 10-minute point: a 1075 after the command gives 「关机命令 HH:MM 发出后，HH:MM:SS 被取消了（系统事件 1075），中继不会再自己关机」, still pushed (every code but 「issued」 is, since 10-06), so an abort is no longer reported as a power-off that failed; with no 1075 or an unreadable log the 「没有关下去」 push stands. Covered by relay/tests/test_shutdown_notice.py (the 10-01 sample).
- **Open, for the user:** after an abort the relay never powers the machine off again (`_shutdown_issued` stays set), so the machine stays on until someone shuts it down. Whether it should power off again once he is done is his call; not changed here.
