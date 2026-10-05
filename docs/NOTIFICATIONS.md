# Notification model (authoritative)

Dictated by the operator on 2026-08-20 and read back for confirmation on the
spot. **This page defines the required behaviour.** Where code or any other
document disagrees, this page wins and the code is a bug.

## Three kinds of summary

| # | Name | When | Title |
|---|---|---|---|
| 1 | **Daily report** | after the evening queue finishes, once a day | `📋 08-20 · 全绿 ✅` |
| 2 | **Interim look** | after a daytime queue finishes | `🔎 08-20 · …（临时查看）` |
| 3 | **Manual run** | after a hand-triggered queue finishes | `🔎 08-20 · …（手动执行）` |
| 3b | **Weekly gate** | when one of the three once-a-week items reaches its weekly cap (MAA 剿灭, OK-WW 周常乐园, OK-WW 周本) | `🗓️ 周常` — one line, same shape for all three: `明日方舟 · 剿灭：本周已打满，暂停到下周一（届时恢复为 Annihilation）` / `鸣潮 · 周常乐园：本周已完成，暂停检查到下周一` / `鸣潮 · 周本：本周三次已领满，暂停到下周一`. Monday boot sends ONE `🗓️ 新的一周` with all three status lines. Operator 2026-09-07: the three must share page logic, judgement and notifications. |
| 3a | **Tacet-field drops** | right after 1/2/3, when OK-WW farmed a Tacet Suppression that day | `🖼️ 无音区产出` — one text line (configured index, zone name, echo sets) then ONE image: the final results page (six drop slots). Group robot only (image messages); each screenshot sent once (`state/tacet-shots-<day>.sent`). Operator 2026-09-07: only the drops page, nothing else. |

They do not consume or cancel each other:

- An interim look or a manual run never uses up the day's daily report. The
  evening report still goes out (`send_daily_now(mark=False)`).
- However many daytime rounds run, that many interim messages go out - one per
  round, not one per day.
- A hand-triggered catch-up round sends its own message, explicitly labelled as
  manual.

Kind 2 exists only while the system is under test: set `ARK_INTERIM_REPORT=0`
to stop it once the daily report alone is trusted. Turning it off must not
affect kind 1, which is why it is its own switch - `ARK_REPORT_BEFORE_SHUTDOWN`
governs a different thing, the backstop that fires from inside the shutdown path
when the interim never got delivered.

Kind 2 is not sent on a timer: the morning round powers off seconds after
finishing, so a timer would have to fire inside a moving window between
"finished" and "off". Reporting when the round completes is deterministic.

## Every summary must carry

- Stage, drops, sanity, start and end times - **both clocks**, server and Tokyo.
- **Time remaining on the current event, with a countdown**, read from MAA's own
  `cache/gui/StageActivityV2.json`.
  - under 36 hours: prefix ⚠️
  - event already over while the stage is still the event stage: say plainly
    that the next round will fail and the stage must be changed now
- Tomorrow's plan: what will run, which stage, how sanity will be spent.

## Immediate notifications (not summaries, not bound by the rules above)

| Event | Behaviour |
|---|---|
| Task failed | push once, after all retries have finished, with a plain-language diagnosis |
| Recovered on retry | **daily report only**, not pushed: the failed run's row says the retry or the make-up got it, the make-up line says 「失败过，补跑后走通了」 (the table 「Recovered by itself」 below). The user, 2026-10-06 05:07: 「报错后自己好了的，只进日报、不进群。本来不就这样吗？本来不就是他自己弄好的，自己能修好的东西，不进报错里吗？」 From 2026-10-06 (「不论多少次什么错误都要发」) until 05:07 each was pushed to the group |
| Task succeeded | **silent**, recorded only |
| Should have run and did not / something missing | alarm immediately |
| Config command applied | push a receipt: inbox version, name, note, and what changed in plain language |
| **Relay code updated** | push the moment the new code is actually running - version before and after, and which files changed |
| **Relay code update failed** | push why, which files did not land, and that the machine is still on the old version |
| A notification channel is broken | alarm over whatever channel still works, **every send it refused** (the user, 2026-10-06: 「不论多少次什么错误都要发」). From 2026-08-22 until then it was once per fault, with the record on disk so that a relay restart did not re-announce it |
| MaaEnd updated itself | **not pushed** - the beta channel ships most days, so a notice per update is a daily message with nothing to act on. Log only |

## Updates must land at boot, and must announce themselves

Two rules, both given by the operator on 2026-08-21.

**At boot, never at the end of a queue.** The machine powers on at 21:20 and
the queue starts at 21:30; the relay is up a minute or two after boot, so
roughly eight of those ten minutes are usable and they exist for exactly this.
The morning gap is the same shape: power at 08:45, queue at 09:00. An update
applied after the run would sit unused until the next boot, and a command that
needs it could not be understood in the meantime. `service.py` runs selfupdate
at service start, before the inbox, and restarts itself immediately so the new
code is live before the queue fires.

**Announce the moment it takes effect** - code updates as well as config ones.
The process that applies a code update is still running the old code and is
about to replace itself, so it cannot be the one to report. It records what it
did, and the process that comes up on the new code sends the notice. That way
the message means "the new code is running", not "the files were written".

The first update after this shipped is a special case: the code that applies it
predates the feature and leaves no record. So the notice is also derivable from
the applied version alone, compared against the last version announced.

**A failed update is announced as loudly as a successful one.** An update that
was available and did not land leaves the machine running old code while
everything upstream assumes the push took effect - the same trap as an scp that
returns 0 without transferring, and the reason `deploy-relay.sh` verifies
hashes. The notice says why it failed, which files did not land, and that the
machine is still on the previous version. It repeats on every boot until an
update succeeds, because the machine boots twice a day and an unfixed channel
should keep saying so.

## Shutdown

- The relay powers the machine off after the queue has finished **and** the
  report has been delivered. This is the design and it stays.
- **Nothing else powers the machine down without an explicit instruction.**
  An unrequested manual shutdown on 2026-08-20 left the machine unreachable
  while a config still needed restoring. The relay's own post-run shutdown is
  the only automatic one.

## Only the relay pushes. Nothing else. Ever.

This is the design, stated by the operator and predating everything else on
this page: **MAA and AUTO-MAS never notify anyone directly.** They produce run
records; the relay reads those records, decides what is worth saying, and says
it. That is the whole reason the relay exists.

So every push switch in every profile of every downstream program is off, and
stays off. There is no "but this one goes to the other person" exception - the
other person is inside this system too, and a direct push from MAA bypasses all
of it: the retry logic that suppresses a first failure, the daily grouping, the
countdown, the one-channel-is-enough delivery rule.

Getting this wrong on 2026-08-22 cost three junk notices to the operator's
phone. Worse was the reasoning: MAA's second profile was left pushing because
its Server酱 key differed from the first, so its messages "went to someone
else". That was answering a question about configuration when the question was
about design. When a config looks like it might be someone else's business,
ask what the system was supposed to do - do not infer the intent from the
config, which is exactly the artefact that may be wrong.

## Channels

| Channel | State |
|---|---|
| Server酱 (`sctapi.ftqq.com`) | **carrying everything** |
| WeCom self-built app | **down**: `errcode=60020`, the home IP is not in the trusted list |
| WeCom group bot (`WECOM_BOT_URL`) | configured on the machine (since 2026-08-30) and, since 2026-09-23, in the Mac's push.env too; has no trusted-IP list, so it survives a changing home IP |

MAA's and AUTO-MAS's own direct pushes are all off - both would reach the same
WeChat, so leaving them on delivers everything twice. When WeCom comes back,
expect duplicates until one channel is muted.

Server酱 has two product lines with different key prefixes - `SCT...` is Turbo,
`sctp...` is Server酱³ - and `notify.py` handles both, sending everything to
`sctapi.ftqq.com` (the per-uid `{uid}.push.ft07.com` host that Server酱³
documents returns 403 for this key and is not a usable fallback). Which line
this deployment's key belongs to is not recorded here; the key lives in
`relay/.env` on the machine and in `~/.config/ark/push.env` on the Mac.

Delivery rule: **one channel delivering counts as delivered.** See
[PITFALLS.md](PITFALLS.md) for why that sentence exists.

### Three channels, three jobs (2026-09-14 evening)

| Channel | Carries | Code |
|---|---|---|
| WeCom group robot | real alarms someone has to act on | `send(..., alert=True)` |
| Server酱 | the daily report (and its 补发 / 临时查看) and every other notification that means something | `send(..., daily=True)` / `send(...)` |
| WeCom self-built app (private chat) | nothing on its own - only text the operator dictated (`push.py --private`) | never in an automatic order |
| WeCom group robot, **总统令** (the one exception, BOARD A45 (3), 2026-09-23) | 「总统令第 N 条：…」 - the operator's ruling on a question the sessions still disagree on after a meeting. Sent by hand from the Mac, group robot only, no fallback; N is checked against `~/.config/ark/decrees.jsonl` so none is skipped or repeated | `scripts/mac/push.py --decree N "…"`; `--decree --check` probes the key without posting |

The operator, 2026-09-14: 「群里面的机器人通知，只允许出现正常的日报、以及日报中的
真实报错报警通知」「server酱里允许一切有意义的通知」「私聊的通道只允许是我本人亲自口述
允许让你去发某些内容」「三个不同的通知各司其职，不要混在一起，而且根本目的是不要去
打扰我」. The group falls back to Server酱 when the robot refuses (an alarm must
arrive); the daily report falls back to the group (in 2048-byte pieces) when
Server酱 refuses; other information Server酱 refuses is returned as undelivered
and never escalated into the group or the private chat.

The daily report moved from the group robot to Server酱 the same night (the
operator: 「企业群机器人的文字上限有，日报改成server酱推送」): a group text
message is capped at 2048 bytes, so the report arrived as three or four
「(1/4)」 pieces; Server酱 renders it as one Markdown message.

### Guarantee (2026-09-14)

The user, after being pushed to more than ten times in one day: 「根本目的是不要去打扰我」
「在你整顿好之前，我是不会开的」. What is promised, and what enforces it:

1. **The group robot carries real alarms, nothing else.** A title reaches the
   group only through `alert=True` (or as the daily report's fallback when
   Server酱 refuses); since 2026-10-06 every failure is one of them, and
   `route_of` demotes no failure-shaped title (until then it demoted the
   pre-update / game-update 「没能确认」 notices and kept the self-heal notice in
   the daily report). What the relay or AUTO-MAS recovered from by itself is
   not sent at all; the daily report says it (the user, 2026-10-06 05:07; the
   table 「Recovered by itself」 below). The daily report itself goes to Server酱 (`daily=True`).
2. **Nothing already in the daily report or on the phone page is pushed.** Such
   titles are on the `log` list in `notify.py`; adding a push means adding a
   row to the table above with a reason, and the test fails otherwise.
3. **The private chat is never written to on my own initiative.** It is in no
   automatic order; `push.py --private` exists only for text he dictates.
4. **My tests never reach him.** Test dispatches are marked (`run-one.sh --test`)
   and collapse to one line in the daily report; the drill scripts that emit
   a push say so in their header and are run only when he asked for a test.
   A failure or a relay error during a test run still goes to the group like
   any other (2026-10-06: every error, every time); only the daily rows collapse.
5. **A new notification is a change to this file first.** No `notifier.send`
   call site is added without a row in the table and a test line.

If a push reaches him that breaks one of these, the fix is a route change here
and a test, not an explanation.

### Every title and where it goes (`notify.route_of`; `test_notify_routing.py` checks this table against the code)

What the daily report or the phone page already says is **not pushed at all**
(route `log`): it is written to relay.log and counts as delivered. Expected
volume on a normal day: one daily report and zero to two other messages on
Server酱, zero alarms in the group.

| Title | Route | Why |
|---|---|---|
| 📋 日报 / 🔎 临时查看 / （补发） | daily | the one message of the day; Server酱, the group robot only when Server酱 refuses |
| ❌ <script> 失败 | group | an OK-WW run failed and stayed failed (MAA / MaaEnd: see the next row), every time - the same step again included (until 2026-10-06 a step rang once a day). Also, pushed at once with no make-up: a run a person started at AUTO-MAS itself (`trigger.py`; first line 「这一趟是有人在 AUTO-MAS 上手动开的，不是定时开的。」) and a MAA failure on a day with a registered Arknights update (first line 「今天登记了明日方舟的版本更新。」); until 2026-10-06 both went to the daily report only |
| ❌ <游戏><班>没跑成 | group | a MAA / MaaEnd failure AUTO-MAS's retries did not get past, once its one make-up run (`makeup.py`) is over and did not go through - or it got none (the day's one is spent, MAA had already fought, past midnight). Pushed at once (user 2026-10-05 15:38: 「为啥群里不响？你们不是没处理好吗？」), with the make-up's outcome, where it failed and the evidence link. Every such failure (until 2026-10-06 once per game per shift; the user, 2026-10-06: 「不论多少次什么错误都要发」); the key is the record (`unresolved.py`, 「未解决|<run_id>」), so only the same record handled twice is not pushed twice. Shift (in the text) from AUTO-MAS QueueConfig, else before 12:00 = 早班. Could not enter the game and MAA short of sanity have rows of their own (group since 2026-10-06); a make-up that went through is not pushed (「Recovered by itself」 below); a failure cut short by his own red button (停一切) is pushed at once, saying so (`handle._handle`, since 2026-10-06) |
| ⚠️ 明日方舟理智不够，这一趟没打 | group | MAA read less sanity than the stage costs and fought nothing (`outcome.maa_sanity_short`), and AUTO-MAS booked the run as failed; both numbers in the text, key 「理智|<run_id>」. Not held, no make-up. Until 2026-10-06 a log line 「不算失败」 only |
| ⚠️ <游戏><班>没干完 | group | a MAA / MaaEnd round exited normally with items undone (no make-up is run for it), every such round, whichever items - 自动采集 / 应急理智加强剂 alone included (until 2026-10-06 `engine.SOFT_FAILS` kept MaaEnd's in the daily report, and a shift rang once) |
| ⚠️ 这一轮没干完 | group | an OK-WW round ended with items undone; also a run a person started at AUTO-MAS itself that ended with items undone (first line 「这一趟是有人在 AUTO-MAS 上手动开的…」) |
| ⚠️ 终末地设置没能自动改回 | group | the make-up (`makeup.py`) switched 存放背包 on and moved it in front for a full bag (or a make-up before 2026-10-06 narrowed the MaaEnd master), and neither its saved flags nor its full backup can be read back; pushed once, and no make-up touches the master again until a person deletes `state/makeup/narrow.json` |
| ⚠️ 终末地应急理智加强剂：中继确认不了还能不能用上 | group | at every boot (`boot_stages._stage_reenable_maaend`, `gameupdate.spmed_check`): MaaEnd's booster confirm step (`AutoUseSpMedicationQuickUse` in resource/pipeline/nodes.json) is not in the shape known to work - the 09-03 broken shape, a shape the relay does not know, renamed or removed (v2.30.0-beta.4 has no node of that name), or nodes.json unreadable. Not deduplicated: every boot that sees it rings again. The task stays on; the relay never switches it off (user 2026-10-06: 「那个要一直开着，如果上游maaend改了导致没生效就要报警 ... 我开的任务是谁说要关的」) |
| <队列> 没有运行 / 机器没开机 | group | the machine or a queue did not run |
| 🔌 AUTO-MAS 启动不起来 | group | nothing can run until a person looks |
| ⚠️ 中继自更新没成功 | group | the relay is stuck on old code |
| ⚠️ 中继暂时不能在脚本跑完时马上处理结果 | group | results would be delayed |
| 🩺 中继自己报错了 / 🩺 中继自己报错了（v<N> 修过的又出现了） | group | every WARNING and ERROR line the relay logs, each time, at once (`errwatch.py`). The user, 2026-10-06: 「只要是报错，就说这个中继程序它出现问题了，立马就向群内机器人报告错误。不论多少次什么错误都要发 ... 你正常情况应该一条都不发的。」 A kind `known_fixed.py` records as fixed in v<N> goes under the second title. Sent to the group robot alone (`send_group`) and never dropped: what it refuses stays queued on disk (state/errwatch-queue.json) and is sent again (30 s, then up to every 10 minutes); a line the robot has refused for 10 minutes goes the usual alarm way (robot, then Server酱) and stays queued if that fails too; once the queue has backed up, waiting lines go out merged as 「…（N 条）」, identical ones as one line with their count. At most one push every 3 seconds from here (the robot takes 20 a minute). A line that only repeats an alarm already delivered to the group (e.g. 「已告警」, 「已进群」) is not pushed again; a line logged while pushing is not pushed (no loop). Not suppressed while the machine goes down. The daily section 「中继自己记下的报错」 lists the day's lines with 已报群 / 还在排队. Until 2026-10-06: once per kind, at most 3 an hour, WARNINGs daily-only, silent while going down |
| ⚠️ 剿灭开关没能关上 / ⚠️ 剿灭开关没能恢复 | group | the annihilation weekly switch (`annihilation.WeeklyGate`) could not be set to Close after the week's pass (`enforce`, every tick it is tried), or put back on a new week (`maybe_reopen`, at boot: the write was refused, or it reads back changed). Pushed through errwatch with its own text, every time. The switch itself stays (the user, 2026-10-06 02:53: 「我当时已经就专门设计的这个功能，就是说如果打满之后，本周不再进行检查」) |
| ⚠️ 森空岛给了不止一个终末地角色，没有读 | group | Skland listed more than one Endfield role for the account (`skland.SklandMultiRole`), so the phone page's Endfield numbers were not read rather than guessed; pushed through errwatch, once per Skland session the relay makes (`resources.skland_session`) |
| 🩺 开机自检没过 | group | a boot-time assumption (process table, AUTO-MAS API, its logon task, writable dirs, a channel) does not hold; the shift may not run |
| 🛑 没能停干净，需要你动手 | group | estop failed |
| ⚠️ 终末地 MaaEnd 卡住，已结束它让 AUTO-MAS 接着走 | group | MaaEnd's plugin crashed or maafw.log stood still 10 minutes while 「运行」; the relay ended MaaEnd.exe and AUTO-MAS judges the run from MaaEnd's log (`maaend_watchdog.py`; 2026-10-01: 40 minutes lost on a dead plugin, and again after all tasks completed but MaaEnd.exe never exited - the 09-28 41-minute gap was the latter) |
| ⚠️ 终末地 MaaEnd 卡死，没能结束，需要人工看一眼 | group | same, but ending MaaEnd.exe failed; it stays hung until AUTO-MAS's own limit |
| ⏱️ <game>（<script>）跑超时，AUTO-MAS 正在重试 | group | every 运行超时/进程超时 line in AUTO-MAS's app.log, pushed while AUTO-MAS still retries (`runwatch.py`, 2026-10-01: three two-hour OK-WW timeouts, no alarm for six hours); a run a person started from AUTO-MAS itself too, saying so. Until 2026-10-06 only the first per script per day, and none for a hand-started run |
| ⏰ <queue>超时还没跑完 | group | a queue still unfinished past the longest finish of the last 7 days + 30 minutes (`runwatch.py`), once for that queue run (re-checked every minute). Not when the task running is one a person started from AUTO-MAS itself (`trigger.py`, 10-03 00:43): it is not the shift, and the text would say the shift is still running |
| 🆕 预更新 / 🆕 游戏更新 / 🔁 更新后重跑 | info | a game or script changed version (rare) |
| ⚠️ 预更新没能确认 / ⚠️ 游戏更新没能确认 | group | the pre-update (`boot_stages._stage_preupdate`) or the game update (`_stage_gameupdate`, `engine._maybe_deferred_update`) could not confirm an item, each time. Until 2026-10-06 demoted to Server酱 by `route_of` (the user, 2026-10-05 13:07: 「几乎就是遇到一点小毛病就停下来报错」); his order of 10-06 (「不论多少次什么错误都要发」) reverses that |
| ⏸ <script> 进不了游戏，稍后补跑 | group | a MaaEnd run that never got into the game on an official maintenance window or update notice, or any run inside an official maintenance window: every such record, with the official notice it was matched to (「官方依据：…」). Until 2026-10-06 one notice per script per day to Server酱 and no alarm (the user, 2026-09-02: 「检测到服务器在维护时候就跳过，不报警」); his order of 10-06 reverses that |
| 🥚 刷声骸收工 | info | the farm he ordered has ended |
| 🌙 今晚不关机 | group | the machine will stay on and why, past the day's last queue time (`shutdown._say_if_moment_passed`, alert=True): every reason - debug mode, 「下次跑完不关机」, a make-up running, the relay switched off shutdowns, uptime, nothing done yet, the report not sent - except the relay's own power-off in progress (`shutdown.RELAY_POWER_OFF`, the only code not pushed; the user 2026-10-06: only the planned power-off the relay itself started may skip the group). Once for each reason text a day (the same reason re-checked every tick is one push). Also, at once, when the power-off command went out 10 minutes ago and the machine is still up (「not-down」) |
| 💳 月卡快到期 | info | a monthly card he registered ends within five days; one a day, all games in one message (user order 2026-09-26 02:47) |
| 📱 配置没改成 / ✗ … | group | his phone order failed - an error, so the group (2026-10-06: every error, every time; `boot_stages._phone_execute`, alert=True) |
| 🧹 终末地配置清掉了死条目 / ⚠️ 终末地配置里的死条目没能清 | group | `mastercfg.prune_maaend_orphans` deleted master entries MaaEnd no longer defines (each named, 开着/关着) or refused to (why); every time, pushed through errwatch under its own title. Deleting them is on relay/USER-SWITCHES.txt (user 2026-09-09 03:49: 「另外手机遥控里还有黄色警告，你光报警不去修吗？」) |
| 🧩 换写设置格式 | info | config maintenance (rare). Tasks the relay once switched off (leftover records in state.json) are switched back on at boot with an INFO log line, not pushed; failing to is a WARNING (`gameupdate.maaend_reenable_records`) |
| ⚠️ OK-WW 补丁有 N 条没贴上 | group | a patch no longer binds (`boot_stages._stage_patch_okww`, `_preupdate_okww`, `engine._patch_okww_if_updated`), each time; until 2026-10-06 Server酱 only |
| 🗓️ 新的一周 | info | Monday summary of the three weekly gates |
| 🧷 上游改了导出日志的代码 | info | evidence bundling needs re-checking (rare) |
| 🔌 推送通道故障 | group | a channel refused a send that another one took: announced on the group order (robot, then Server酱), every such send; until 2026-10-06 once per fault |
| 🔄 中继已更新 | log | the notes go into the daily report's 「今天中继改了什么」 |
| 🗓️ 周常 | log | the phone page shows the weekly state |
| ⏭️ 跳过模式 / 🛑 已停一切 / 📱 配置已修改 / ✅ … | log | the answer is on the phone page: per-row receipts for settings, 「机器最近的回执」 for actions |
| 🗂️ 证据包已送出机器 | log | the link is in the failure alarm and in the daily row (证据包) |
| ✅ 自动采集：补跑后全部走完 | log | the daily report has a 「自动采集补跑：走通 … / 仍失败 …」 line |
| ⚠️ 自动采集：补跑仍有路线没走通 / 🚩 自动采集：有路线连续两天补跑失败，是复发性问题 | group | a route failing its retry is a failure (`collect_retry.py`); the daily line says it too. From 2026-10-05 13:07 (「他不要再报错了」) until 2026-10-06 it was daily-only |
| 🩹 OK-WW 补丁（N 条） | log | the healthy case |
| 🥚 开始刷声骸 | log | acknowledgement of his order |

### Recovered by itself: not sent, the daily report carries it (2026-10-06 05:07)

The user, 2026-10-06 05:07: 「报错后自己好了的，只进日报、不进群。本来不就这样吗？本来不就是
他自己弄好的，自己能修好的东西，不进报错里吗？」 So nothing below is sent through `notify` at
all - not to the group, not to Server酱: the caller writes one INFO line to relay.log
(「…只进日报」), and the daily report shows the event. What did **not** recover keeps
its group row above, every time. From 2026-10-06 (「不论多少次什么错误都要发」) until
05:07 every row here was pushed to the group. Each place is on relay/USER-SWITCHES.txt
(tests/test_user_switches.py); `test_notify_routing.py` checks that none of these
titles is sent, `test_recovered_daily_only.py` the behaviour.

| Title (relay.log only) | The daily report shows it as | Not recovered: what goes to the group |
|---|---|---|
| ⚠️ <script> 中途失败过，重试后成功 | the failed run's row (↻ 「后来在 HH:MM 那趟重试里做成了」, or ❌ with what failed) with its evidence link, and the run that got through (`handle._flush_pending`) | no later success: 「❌ <script> 失败」 / 「❌ <游戏><班>没跑成」 |
| ⚠️ <script> 更新时失败过，重跑后成功 | the streak as ↪️ rows (「游戏更新后重跑」 / 「MaaEnd 装新版 … 后自己重启」, `core.episode_kinds` 「update」); a failure in the streak not caused by the update keeps its own row | the same final alarms |
| ⚠️ <游戏><班>失败过，补跑后走通了 | the make-up line 「补跑：<游戏> … → 失败过，补跑后走通了（原来失败于：…）」 (`report.makeup_line`) and the failed run's row (「后来在 HH:MM 那趟补跑里做成了」) | the make-up did not go through, or there was none: 「❌ <游戏><班>没跑成」 |
| (an attempt AUTO-MAS recorded as a restart: 「游戏更新成功，即将重启任务」, 「模拟器启动失败」, 「未捕获到日志」) | not pushed when it lands: held like a failure, the attempts after it decide (`handle._handle`, `_hold_restart`). A later success heals it - also one whose record landed first (the rows above; ↪️ for a game update, 「ℹ️ MaaEnd 发版自更新重启 N 次」 for MaaEnd's stub; an emulator launch miss has no row, the user's 2026-09-14 choice) | a later failure is alarmed as usual; no record after it: the final alarm about it, with the line 「HH:MM 开始的这一次，AUTO-MAS 记的结果是「…」…这次之后没有再跑出一次记录。」 |
| ⚠️ 终末地装新版重启了这一趟（前面那趟已做完） | ↪️ 「MaaEnd 装新版 … 后自己重启，用掉一次重试」 (`handle._drop_update_after_done`); the shift's round was already done | - (the round is done; when it is not, the restart is held and the final alarm names the update) |
| 🔁 自动采集：只补跑失败的路线 | 「自动采集补跑：走通 … / 仍失败 … / 没结论 …」 (`report.retry_line`; `collect_retry.maybe_run` logs the start) | 「⚠️ 自动采集：补跑仍有路线没走通」 / 「🚩 …复发性问题」 (rows above) |
| relay.log 「推送传输失败 N 次，第 M 次送到了」 / 「Server酱 前面的地址没送到…，换 … 送到了」 | 「中继自己记下的报错」, tagged 自己好了 (`notify._post`, `ServerChan.send_text`, `errwatch.recovered()`); each failed attempt before it is an INFO line | every attempt failed: the caller's WARNING / ERROR (「…推送失败」, 「通知一条渠道都没送到」) and 🔌 推送通道故障 |

`scripts/mac/push.py` on the Mac follows the same rule and the same order, with
`--all` to override.

### A copy of every group alarm on COS (2026-10-06)

The user, 2026-10-06 00:23: 「中继每往群里发一条报警，就同时抄一份给 Mac」. Every
message that went to the group route and was delivered (`send(..., alert=True)`
routed `group`, `send_group`, and the 🔌 channel-outage notice, which goes out
on the group order) is appended to `state/alerts/<Beijing YYYYMMDD>.jsonl` and the
whole day file is PUT, privately, to the evidence bucket as
`alerts/<Beijing YYYYMMDD>.jsonl` (`alertlog.py`). One JSON object per line with
exactly `ts` (Beijing time, `YYYY-MM-DD HH:MM:SS`, computed from UTC), `game`,
`title`, `text`, `version`, `evidence_run`; empty string when unknown. This is
not a notification: nothing is pushed for it, and a COS failure is one WARNING
in relay.log; the next alarm or the next boot sends the day again.
