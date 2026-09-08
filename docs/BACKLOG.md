# Work owed to the user

**Why this file exists**: on 2026-08-27 the user asked 「角色练度推荐怎么又欠我了？你记不住事吗？」
Conversations get compacted, and a todo that lives only in my head is guaranteed to fall out.
**Write down what you promised the moment you promise it, and cross it off the moment it is done.**

**Todos live in exactly one place.** Before 2026-09-08, the WeCom 60020 problem and the three
watchdog secrets were written up both here and in `OPERATIONS.md`; edit one and the other became
wrong. `OPERATIONS.md` now keeps only "standing limits we do not plan to change", and
`NEXT-BOOT.md` keeps only "the first thing to do at the next boot".

## Todo
- [x] **Filed as [AUTO-MAS#573](https://github.com/AUTO-MAS-Project/AUTO-MAS/issues/573)** (using their
      "AI 提交的 Bug" template, and saying we will send a PR since they are short-handed). Background:
      MaaEnd v2.28.0-beta.1 changed SellProduct's display name to 「🛒据点交易」 (the task name itself did
      not change - `name` in `tasks/OutpostTrading.json` is still SellProduct, but the language-pack key
      became task.OutpostTrading.label). AUTO-MAS's `load_maaend_task_i18n` cannot find it and falls back
      to the English name SellProduct, so the log line 「任务完成: 🛒据点交易」 never matches. All 17 tasks
      of the run finished and it still recorded 「部分任务执行失败: SellProduct」, then burned two more
      retries per RunTimesLimit. The relay side now judges by MaaEnd's own log instead (every 「任务开始」
      has a 「任务完成」 and there is no 「任务失败」 = done). Follow `docs/UPSTREAM-ISSUE-RULES.md` before
      filing.
- [x] **Filed as [AUTO-MAS#575](https://github.com/AUTO-MAS-Project/AUTO-MAS/issues/575)** (I first filed
      #574 from the command line without labels, closed it, and refiled through the form as #575): the
      success criterion only accepts OK-WW's last line 「Window closed」; the suggestion is to also accept
      Daily Task Completed. Nothing filed against OK-WW for now (a single one-off, not enough evidence).
      Background: (on the 09-06 09:36 run, the process disappeared during the handler stopping phase
      after writing Daily Task Completed). AUTO-MAS uses that line to judge success; without it, it
      records 「在完成任务前退出」 and retries. The relay now accepts OK-WW's own 「Daily Task Completed」.
      Whether to file with ok-ww depends on whether it happens every time (the second run wrote it
      normally).
- [ ] **The 09-04 Arknights major client update (06:00-12:00) is the first live run of the "maintenance
      day procedure"**: the 08:45 boot should drop MAA from the morning shift and record that; after the
      queue finishes, poll the official version number every 10 minutes, and when the new version lands,
      download the APK, install it into LDPlayer, and launch the game to warm it up; run MAA afterwards
      once it is past 12:00; add it back to the morning shift. **Watch the logs**, and fix anything that
      goes wrong that same day.
- [ ] Weekly boss name: the status page has 「千傀重楼」 typed in by hand (09-02 screenshot); patch v2 will
      OCR the name and update it automatically at the next weekly boss.

- [ ] **MaaEnd support for Endfield 1.5.3 「雪凇幽梦」** (rerun 2026-09-02 16:29: 赠送干员礼物 /
      装备制造 / 转交委托 / 环境监测 all four failed, AUTO-MAS retried twice with the same result;
      everything else including essence farming succeeded). Upstream had identical reports the same day:
      #5397 #5398 #5400 #5401 #5402 (转交委托, 赠送礼物, daily reward claiming, and so on), and the
      newest release is still v2.27.0-beta.4 (9/1, older than the game update).
      Not our problem; pre-update follows the beta channel, so a new upstream release installs itself.
      **On 2026-09-02 23:10 these four were turned off in the master config as the user instructed**
      (GiftOperator / GearAssembly / DeliveryJobs / EnvironmentMonitoring, backup as .bak-* next to the
      master config, recorded in state/maaend-disabled-for-1.5.3.json).
      **Remember to turn them back on once MaaEnd ships a version that supports 1.5.3.**

- [ ] **Run the launcher automatically to update the client on Endfield version-update days**
      (2026-09-02, observed: a version update downloads through the Hypergryph launcher, it is not a hot
      patch; MaaEnd launching Endfield.exe directly stops at 「客户端版本已过时」 and all three runs
      failed). Today the relay only gets as far as "recognize it, skip for the day, do not alarm";
      updating the client still needs a human to run the launcher once (process name Games, 「更新游戏」
      at the bottom right).
      Candidate approach: during the pre-update phase, if the official announcements for that day include
      a 「版本更新说明」, launch `Launcher.exe` in an interactive session, click update, and wait for the
      button to turn into 「开始游戏」 before releasing the morning shift.

- [ ] **Queue rename + notification styling, to be applied the moment the machine boots**:
      (1) `scripts/mac/rename-queues.py` (renames the queues inside AUTO-MAS, reads back to verify);
      (2) `scripts/mac/deploy-relay.sh`; (3) ~~verify interface.json's version~~ (verified 09-02 09:16:
      v2.27.0-beta.4);
      (4) `scripts/mac/deploy-web.sh` (the page's live online status has to point at the new relay);
      (5) turn off debug mode (turned on 09-02 09:16, runs until 21:10); (6) the next time any program
      really updates, check that the notification reads 「old → new」.

- [ ] **MaaEnd 「赠送干员礼物」 fails intermittently** (the 2026-09-01 11:06 run; the 11:31 retry healed
      itself). The evidence was not salvaged; when it recurs, `state/evidence/` will hold the material,
      and then handle it per `docs/UPSTREAM-ISSUE-RULES.md`.

- [ ] **Refile the MaaEnd issue (one failed auto-collect route drags down the whole run)**:
      the #5365 version was written in my own voice - section headings, parallel bullet lists, bold
      everywhere - and was judged AI-generated. **Copy how real humans in that repo write** (read a
      dozen or so real issues first), and **follow their template requirements strictly, attaching every
      log they ask for**.
      Several times before I refused to attach logs on the grounds that they "contain local paths"; that
      was wrong: either redact and attach, or submit the way they specify. Deciding on my own not to
      hand them over is not allowed.

- [ ] **Noise reduction (waiting on the user's decision)**:
      1. while debug mode is on, failures from **runs I dispatched by hand** do not go to the group, only
         to the log;
      2. repeated failures of the same problem within a short window are reported only once.
      Three of the five alerts in the group on 2026-09-01 were produced by my own test runs.

- [ ] **MaaEnd stuck on the 「获得」 popup during the morning shift**: investigation result (afternoon of
      2026-08-27) - the upstream medication flow **does** have a node that handles that popup,
      `AutoUseSpMedicationRewardsConfirm` (5-second timeout), so the claim in #5267 that it was "a
      missing template, same as #4589" was **wrong**, and the maintainer was right to close it.
      Why it timed out that day can no longer be established: MaaEnd wipes its debug artifacts on the
      next start, and that morning's three on_error screenshots are gone. Per the user's decision:
      **wait and see whether tomorrow's morning shift reproduces it**; the relay now salvages evidence
      into `state/evidence/<run_id>/` at the moment MaaEnd fails, so a recurrence will leave evidence
      behind.

- [ ] **The parameters for `team/index` (the full strategy list) are still not figured out**; it keeps
      answering 「参数错误」. Querying per character is already enough
      (`team/char-list?charId=`); the full list would only be a bonus.


- [ ] **Relay's WMI listener exits**: reported once on 08-27 08:17,
      `进程启动事件监听退出，改用 120 秒活性检查`. Needs the actual exception before it can be fixed.

- [ ] **The AUTO-MAS queue does not advance**: after MaaEnd exits on its own the queue stalls,
      `Run.RunTimeLimit=40` did not trigger a retry either, and `Game.CloseOnFinish=True` did not close
      the game either.

- [ ] **`ARK_LLM` (DeepSeek) reports that the model is unavailable**. The daily report falls back to the
      structured layout and loses its one-sentence plain-language summary; nothing else is affected.
      Restoring it needs a working key. (moved in from OPERATIONS.md)

- [ ] **Alert latency is bounded by when AUTO-MAS writes to disk.** It buffers every attempt of a whole
      round and writes them all out when the script ends, so a 09:17 login failure cannot be known before
      09:58 at the earliest; the relay itself needs only 34 seconds from seeing the file to pushing the
      alert. Getting ahead of that means reading MaaEnd's live log as a second source, and deciding who
      wins when the two disagree. **Do not touch this the night before a queue run**: one misread line in
      freshly written log parsing turns the whole night into false alarms. (moved in from OPERATIONS.md)

- [ ] **The git history of this public repo still contains a person's real name and how that machine is
      logged into** (needs your decision before anything moves; exactly which two strings is written in
      the regex of `lint-repo.sh` check 12, and is not repeated here - writing it here would trip that
      gate itself). The working tree was cleaned long ago and the gate keeps watching it; but that
      "redaction" in e9c2e75 only changed the current files, and the original text is still there in
      368d109 and earlier commits, visible by opening the history on GitHub.
      **Clearing it for real requires rewriting history**, at the cost of: every existing clone and fork
      breaks, every commit hash changes, and anyone who already fetched cannot fetch it back. The command
      is `git filter-repo --replace-text <replacement table>` followed by `git push --force`.
      This is irreversible and public-facing, so **I will not touch it without you explicitly saying to
      clear it**. Leaving it is also acceptable - that machine is only reachable inside the Tailscale
      network and has no entry point on the public internet.

## Done (kept around for a while so the same question is not asked twice)

- [x] All four OK-WW patches submitted upstream (2026-08-27):
      [#1625](https://github.com/ok-oldking/ok-wuthering-waves/pull/1625) a failed instance no longer
      drags down the dailies,
      [#1629](https://github.com/ok-oldking/ok-wuthering-waves/pull/1629) keep farming the nest + farm
      only the specified spot,
      [#1631](https://github.com/ok-oldking/ok-wuthering-waves/pull/1631) reward claim order,
      [#1632](https://github.com/ok-oldking/ok-wuthering-waves/pull/1632) fallback for starving the main
      DPS.
      Each comes with tests, and each was actually run on the game machine using OK-WW's bundled Python.
- [x] Limited vs standard: the official API **does not expose** that attribute (`labelType` is only the
      current banner's tag). The standard-pool six-star list comes from `STANDARD_CHARS` in
      cmyyx/cep's `src/data/banner.ts`: 艾尔黛拉、余烬、黎风、别礼、骏卫.

- [x] Results of pre-updating the four programs (08-27)
- [x] The complete Wuthering Waves daily flow from wake to finish → [WUWA-DAILY.md](WUWA-DAILY.md)
- [x] Endfield character investment levels → four Excel sheets + Server酱 push; reissued as "six-stars
      only" per request
- [x] Character investment plan: 11 of the six-stars are below 90, existing materials are **enough for
      all of them**, and after maxing them out there are still 16.37M EXP and 4M gold left over
      (ascension materials not included)
- [x] MaaEnd getting stuck on the popup filed upstream → MaaEnd/MaaEnd#5267
- [x] The official four investment templates and their numbers (basic 60/6/60, advanced 80/9/80,
      high 90/9/90, perfect 90/12/90) and the resource gap for each tier
- [x] Investment advice and team strategies: `char-pair/char-list?charId=`, `team/char-list?charId=`
      - all 16 six-stars captured, including recommended skill levels, recommended weapons, recommended
      partners and the reasoning
- [x] The full consumption rules for ascension/skills/talents: `calculate/rules?charIds=<single id>`
      (comma-joining several ids returns an empty table, so they have to be asked one at a time)
- [x] 残象聚落 farmed on 08-27 (0/41 → 24/41), all three bugs in the patch fixed
- [x] Outcome verification `outcome.py`: after a run, check against evidence and notify immediately when
      something did not actually happen, instead of silently booking it as done
- [x] MaaEnd really did start running at 12:00 (restarting AUTO-MAS cleared a stale task lock)
- [x] Gate self-check `scripts/mac/guardcheck.sh` (15 checks), wired into the deploy gate
- [x] Dead-code check `scripts/mac/lib/deadcode.py`, wired into the repo self-check and the deploy gate
- [x] A patch change takes effect immediately (the relay applies it as soon as it starts, instead of
      waiting for the next boot)
- [x] "Farm 落渊南丘 only" written into the master config that actually takes effect →
      [maa-config-master-copy memory]
- [x] All 森空岛 APIs working → [SKLAND-API.md](SKLAND-API.md)
- [x] `winrun.sh --put` (fixes hand-written scp using the wrong username)
- [x] MaaEnd update notification carries the old version number
- [x] OK-WW launch error 740

## WeCom push unavailable (moved in from README)

`errcode=60020`: the caller's IP is not in the enterprise's trusted-IP list. It can be added in the
WeCom admin console, or switched to a group bot with `WECOM_BOT_URL` configured - group bots have no
trusted-IP list. All pushes are currently carried by Server酱.

## Boot supervision not enabled (moved in from README)

The machine cannot detect on its own that it failed to boot, so that check lives in GitHub Actions
(`scripts/watchdog.py`). Enabling it requires configuring `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` and
`SERVERCHAN_KEY` in the repository secrets, and setting `enabled` in `queue/watchdog.json` to `true`.

### Upstream issue status (updated 2026-09-06)

* **OK-WW PR [#1657](https://github.com/ok-oldking/ok-wuthering-waves/pull/1657)**: the "farm only the
  specified spot" switch for 梦魇巢穴, filed using the PR template, with #954 as the prerequisite
  discussion. If the author asks something, **answer and then wait for him to decide; do not close it
  myself** (see memory okww-prs-i-closed-myself).
  Once merged, the local 「巢穴任务」 patch can keep only the two pieces about continuing to farm and not
  spinning idle, and the specified-spot part switches over to the upstream option.

* AUTO-MAS#573 (MaaEnd task rename judged as a failure): HarcoChen determined it is **a cache-refresh
  problem, and restarting MAS fixes it**.
  Verified on this machine: starting a fresh process with AUTO-MAS's own python and calling
  `load_maaend_task_i18n` maps SellProduct → 🛒据点交易 correctly;
  that run was using the stale resource table MAS preloaded at the 08:46 boot (`_loader_cache`), and
  MaaEnd was only upgraded by the pre-update after 08:47.
  Relay-side countermeasure: the pre-update restarts AUTO-MAS after upgrading MaaEnd (added 09-06).
  **HarcoChen also cautioned: do not post purely AI-generated replies in the MAS / MXU / MaaEnd issue
  trackers; MaaEnd and MXU have no AI template, and it increases the maintainers' workload.**
  From now on, anything sent to those three repos is one or two sentences of fact plus attachments, with
  no analysis paragraphs; whether to keep using my own phrasing is the user's call.
* AUTO-MAS#575 (OK-WW success criterion): maintainer 1w1w11w1 closed it: they cannot reproduce it locally
  over a long period, and putting the criterion on the last line is deliberate - judging success by Daily
  Task Completed would make MAS kill ok-ww early and leave the game not cleanly closed (which happened in
  the early days). They want the reproduction steps + full logs + a screen recording.
  Replied accepting that, with two full runs' logs attached; if it happens again I will add a recording.
  The relay's approach of judging by Completed is unaffected (we do not kill the process).

### Upstream issue status (updated 2026-09-01)

* [MaaEnd#5365](https://github.com/MaaEnd/MaaEnd/issues/5365) one failed auto-collect route drags down
  the whole run - **to be refiled per the "Todo" entry above**, since this version of the writing was
  judged to be AI.
* ~~ok-wuthering-waves#1649~~ **closed by me**: the premise was wrong to begin with
  (`ok.util.logger.Logger.error(message, exception=None)` prints the stack trace anyway, and I asserted
  otherwise from my impression of the standard library's logging), and the real cause was on our side.
* ~~ok-wuthering-waves#1626~~ **closed by me**: the real cause was that we had changed the game's
  keybinds.
* The three still open are all suggestions: #1621 missing docs, #1622 specified nest spot, #1647 make
  the order configurable.
* **The claim "OK-WW cannot claim the weekly boss chest" is void** -
  on 2026-09-01 07:27 it was made to work with a patch and verified live (3/3 → 2/3, 波片 down by 60).
  How it is done: `docs/OKWW-WEEKLY-BOSS.md`.

- [ ] **Upstream progress on MaaEnd's two broken tasks (checked 2026-09-03 21:50)**:
      * **应急理智加强剂** - the real cause is pinned down: inside the `all_of` of the node
        `AutoUseSpMedicationQuickUse`, the inline OCR criterion hangs `type`/`param` at the top level of
        the node, which the framework does not recognize, so it is as good as not written and the confirm
        button never gets clicked. The upstream fix is PR #5453 (it changes only one pipeline file:
        wraps it in `recognition`, widens the roi, and adds a wait for the screen to settle), which
        **had still not been merged by the night of 09-03**, so it will not be in beta.6. The relay now
        judges "turn it back on" by reading the shape of that criterion in the resource file, so it only
        turns on once the fix has really arrived. To take the fix early, the machine's
        `resource/pipeline/nodes.json` could be edited by hand following the PR (the release build merges
        all pipelines into that one file), but a MaaEnd update overwrites it, so it would have to become
        a patch that reapplies itself.
      * **Auto-collect Route3 (武陵城-至晶多齿叶) / Route13 (四号谷地-中黯石)** - the salvaged evidence
        shows the failure points clearly: Route3 dies at `AutoCollectRoute3Goto` (pathfinding cannot
        reach the spot), Route13 dies at `MapNavigatorObstacleDevice_InteractPost`.
        Both are in MapNavigator, which is compiled-in logic and cannot be changed locally. On 09-03
        02:03 upstream rewrote the whole NavMesh planner and merged it into the main branch (#5434, it
        had been reverted once before and then merged again); it is not in beta.5 and will only arrive in
        beta.6. On the community side, #5073 is the roll-up thread for the per-route bugs, and
        #5184 「红矛叶开场失败」 is still open.
      * **Next step**: once beta.6 is out, run these two routes once on their own in a gap that is **not**
        a maintenance day (auto-collect costs no sanity, only time), and once they pass, add them back to
        `AutoCollectRoutes`.

- [ ] **The two Endfield 「理智」 numbers do not agree (night of 2026-09-03, unresolved)**:
      * On the sinkhole start screen, MaaEnd OCR'd 「当前理智」 as **979/360** all three times
        (09:47, the 10:49 booster-popup screenshot, and 11:52); each claim steps it down by 80, so one
        run goes 979→579, and the next run starts at 979 again. Natural regeneration is 1 point per
        6 minutes, which cannot recover 400 in an hour.
      * 森空岛's `card/detail` `dungeon` reported **curStamina 103 / max 360** at 22:30 the same night,
        with `maxTs` corresponding to a full refill at 09-05 05:17; the slope matches 1 point per
        6 minutes - this is the server-side base sanity.
      * Both essence-farming runs really did claim their rewards (the second run got 15 无暇 + 10 高纯),
        and both booster tasks stopped at the 「快捷使用」 popup without clicking confirm (screenshots
        prove it), so **no potion was consumed at all**.
      * The conclusion waits on the user reporting the actual in-game numbers: the 979 on screen very
        likely includes a temporary/compensation sanity layer that does not decrease when rewards are
        claimed, while 森空岛 reports only the base layer. Until this is clear, the daily report's
        「剩余 659/360」 cannot be taken at face value - a reading above the cap has to be labelled as a
        screen reading, and paired with 森空岛's base sanity and its timestamp.
      * One accounting bug is already fixed: the reading is announced before each claim, and there is no
        reading after the last claim, so it used to be short by one (320 → 400).

- [ ] **The two Wuthering Waves "which one" numbers on the phone page have to become names a human can
      read (requested by the user on 2026-09-04)**:
      The user's words: 「给我标数字，我怎么知道 1234 是什么东西呢？」「无音区的名字没有必要，
      但是他刷的套装非常重要」. What he wants is the 无音区 at 玄幽东岳 (it drops one white set + one
      green set).
      * OK-WW stores only the index; it teleports by counting down the in-game **F2 teleport list**
        (`TacetTask.py:66` `index = config.get(...) - 1`), and knows neither the names nor the drops.
      * So **the only authoritative source is the in-game F2 list itself**; guide orderings found online
        cannot be used directly - the list order changes with the version and with which areas are
        unlocked. **Do not guess by aligning positions** (see memory idmap-no-guessing).
      * Approach: open Wuthering Waves → F2 → read "index → 无音区 name → echo set" off a screenshot,
        write it into a registry table in the repo, and change those two phone-page fields into dropdowns
        that show the set names.
