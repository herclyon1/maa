# Work owed to the user

Write down what was promised the moment it is promised, and cross it off the moment it is done
(the user, 2026-08-27: 「角色练度推荐怎么又欠我了？你记不住事吗？」).

**Todos live in exactly one place.** `OPERATIONS.md` keeps only standing limits we do not plan to
change; anything still owed is here. Finished items are deleted, not kept; `git log` has them.
Skipped tests are registered here too and may stay at most one week.

## Todo

- [ ] **Endfield version-briefing parser has only one sample (added 2026-10-08, due 2026-11-05 - overdue).**
      `banners.ef_briefing_banners` reads the official version briefing (bulletin cid 2183 ->
      endfield.hypergryph.com/version_briefing/latest -> content script, JSON.parse blocks). Only the
      v1d6 page is a sample in `relay/tests/test_banners.py`. When the next version's briefing goes
      live, save it as a second sample so the parser is checked against two issues, not one.
- [ ] **Debug mode swallows a shutdown chance and does not give it back when it expires (found
      2026-10-07).** 2026-10-06: debug mode was on until 21:10 Beijing; every shutdown point from
      17:38 to 19:26 met it and was consumed (`modes.py`). When debug mode expired nothing re-ran the
      shutdown decision, so at 21:30 the relay judged "skipped" and pushed 「🌙 今晚不关机」 to the
      group (`shutdown.py`), then shut down at 21:49 once the next MAA record arrived. Until fixed: do
      not leave debug mode on across a shutdown point and do not arm 「下次跑完不关机」 without a
      reason. Fix: when debug mode expires, release the consumed chance and re-run the shutdown
      decision; test with the 10-06 relay.log lines as the sample.
- [ ] **MaaEnd support for Endfield 1.5.3 「雪凇幽梦」.** On 2026-09-02 23:10 four tasks were turned
      off in the master config as the user instructed (GiftOperator / GearAssembly / DeliveryJobs /
      EnvironmentMonitoring; backup as `.bak-*` next to the master, recorded in state as
      `maaend-disabled-for-1.5.3.json`). Turn them back on once MaaEnd supports 1.5.3.
- [ ] **MaaEnd 「赠送干员礼物」 fails intermittently** (2026-09-01 11:06; the 11:31 retry healed
      itself). When it recurs the evidence bundle holds the material; report it upstream by the rules
      under 「Upstream issues」 below.
- [ ] **Noise reduction (waiting on the user's decision):** (1) while debug mode is on, failures from
      runs dispatched by hand go to the log only; (2) repeated failures of the same problem within a
      short window are reported once.
- [ ] **MaaEnd stuck on the 「获得」 popup during the morning shift** (2026-08-27). Upstream's
      medication flow does have a node for that popup, `AutoUseSpMedicationRewardsConfirm` (5-second
      timeout), so #5267's "missing template" claim was wrong. Why it timed out that day cannot be
      established any more. The user's decision: wait for a recurrence; the evidence bundle taken at
      the failure will hold it.
- [ ] **The parameters for Skland's `team/index` (the full strategy list) are not figured out**; it
      answers 「参数错误」. Per-character queries (`team/char-list?charId=`) are enough; the full list
      would be a bonus.
- [ ] **The AUTO-MAS queue does not advance:** after MaaEnd exits on its own the queue stalls,
      `Run.RunTimeLimit=40` did not trigger a retry, and `Game.CloseOnFinish=True` did not close the
      game.
- [ ] **`ARK_LLM_*` (DeepSeek) reports that the model is unavailable.** The daily report falls back to
      the structured layout and loses its one-sentence summary; nothing else is affected. Restoring it
      needs a working key.
- [ ] **Alert latency is bounded by when AUTO-MAS writes to disk.** It buffers every attempt of a
      round and writes them when the script ends, so a 09:17 login failure cannot be known before
      09:58; the relay needs only 34 seconds from seeing the file to pushing. Getting ahead of that
      means reading MaaEnd's live log as a second source and deciding who wins when the two disagree.
      **Do not touch this the night before a queue run.**
- [ ] **Upstream progress on MaaEnd's two broken tasks (checked 2026-09-03):**
      * 应急理智加强剂: inside the `all_of` of the node `AutoUseSpMedicationQuickUse`, the inline OCR
        criterion hangs `type` / `param` at the top level of the node, which the framework does not
        recognise, so the confirm button is never clicked. Upstream fix: PR #5453. The relay checks
        the shape of that criterion in the resource file at every boot (`gameupdate.spmed_check`).
      * Auto-collect Route3 (武陵城-至晶多齿叶) dies at `AutoCollectRoute3Goto`, Route13
        (四号谷地-中黯石) at `MapNavigatorObstacleDevice_InteractPost`. Both are in MapNavigator,
        compiled-in logic that cannot be changed locally; upstream rewrote the NavMesh planner
        (#5434). Next step: run the two routes on their own in a gap that is not a maintenance day,
        and once they pass add them back to `AutoCollectRoutes`.
- [ ] **The two Endfield 「理智」 numbers do not agree (2026-09-03, unresolved).** On the sinkhole
      start screen MaaEnd OCR'd 「当前理智」 as 979/360 three times that day; Skland's `card/detail`
      `dungeon` reported curStamina 103 / max 360 the same night with a slope of 1 point per 6
      minutes - the server-side base sanity. The 979 very likely includes a temporary layer that does
      not decrease when rewards are claimed. Waiting on the user's in-game numbers; until then a
      reading above the cap is a screen reading and is paired with Skland's base sanity and its time.

## Decided, do not re-open

- **The git history of this public repo still contains a person's real name and how that machine is
  logged into.** Closed 2026-09-08 by the user: 「git 历史里那个真名和登录方式不管」. The working tree
  stays clean and `lint-repo.sh` keeps watching it; do not propose rewriting history again.
- **Osaka HP ProOne 600 G3 as a cloud server: shelved 2026-09-01.** Plans treat it as non-existent.
  If it is ever revived: it reached the net through the Cloudflare tunnel `osaka` plus the Mac's WARP
  team, SSH on port 2222; its LAN address is re-issued by DHCP on every reboot, which kills the /32
  route. Recovery: Cloudflare dashboard -> Networks -> Tunnels -> `osaka` -> the connector
  diagnostics page shows the current **Private IP**; put it into the tunnel's CIDR route and the WARP
  split-tunnel include list. Longer write-up: `~/Claude/HANDOFF-hp-cloud-server.md`.

## Standing limits with a way out

- **WeCom self-built app push is unavailable:** `errcode=60020`, the caller's IP is not in the
  enterprise's trusted-IP list. The group bot (`WECOM_BOT_URL`, no trusted-IP list) carries the
  alarms and Server酱 the daily report ([NOTIFICATIONS.md](NOTIFICATIONS.md)).
- **Boot supervision from outside is not enabled:** the machine cannot detect on its own that it
  failed to boot, so that check is `scripts/watchdog.py` under GitHub Actions. Enabling it needs
  `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` and `SERVERCHAN_KEY` in the repository secrets and
  `enabled` set to `true` in `queue/watchdog.json`.

## Upstream issues

Rules: one or two sentences of fact plus the attachments their template asks for (logs redacted,
never withheld); no analysis paragraphs and no AI-styled writing (AUTO-MAS maintainer HarcoChen,
2026-09-06: MaaEnd and MXU have no AI template, and such replies add to the maintainers' work). When
the author asks something, answer and wait for their decision; do not close our own issue or PR
ourselves. Read replies when asked; no self-scheduled polling.

| Issue | State |
|---|---|
| OK-WW PR [#1657](https://github.com/ok-oldking/ok-wuthering-waves/pull/1657) | 梦魇巢穴 "farm only the specified spot" switch; open. Once merged, the local nest override keeps only "continue farming" and "no idle spinning" |
| OK-WW #1621 / #1622 / #1647 | suggestions (missing docs, specified nest spot, configurable order); open |
| OK-WW #1649 / #1626 | closed by us: the premises were wrong (`Logger.error` does print the stack trace; we had changed the game's keybinds) |
| AUTO-MAS #573 | MaaEnd task rename judged as a failure: a cache-refresh problem, restarting AUTO-MAS fixes it. The pre-update restarts AUTO-MAS after upgrading MaaEnd |
| AUTO-MAS #575 | OK-WW success criterion: closed by the maintainer (judging by the last line is deliberate); they want reproduction steps, full logs and a recording if it recurs. The relay's own judgement by 「Daily Task Completed」 is unaffected |
| [MaaEnd#5608](https://github.com/MaaEnd/MaaEnd/issues/5608) | theirs: navigation fails after the second fight, 「YOLO is confident but zone validation failed」. Our comment 2026-09-18 with the mirror case at 藏剑谷. Same family: #5833 |
| [MaaEnd#5851](https://github.com/MaaEnd/MaaEnd/issues/5851) | ours, 2026-09-18: 基质刷取 at 清波寨, `AutoEssenceConfirmObtain` hit its 20 s timeout after 「点击确认领取」. Once only |
| [MaaEnd#5660](https://github.com/MaaEnd/MaaEnd/issues/5660) | ours, 2026-09-11: retry failed gathering routes once at the end of a run instead of failing the whole task (the re-filing of #5365 by their rules) |
| MaaEnd #5073 / #5184 | community roll-up of per-route bugs / 「红矛叶开场失败」; open |

Drafts and evidence of the 09-18 filings: `~/Money/styl-work/issue-drafts-0918/`.
