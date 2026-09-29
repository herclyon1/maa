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
| Recovered on retry | push "recovered this time, problem not solved" - self-healing is not the same as fine |
| Task succeeded | **silent**, recorded only |
| Should have run and did not / something missing | alarm immediately |
| Config command applied | push a receipt: inbox version, name, note, and what changed in plain language |
| **Relay code updated** | push the moment the new code is actually running - version before and after, and which files changed |
| **Relay code update failed** | push why, which files did not land, and that the machine is still on the old version |
| A notification channel is broken | alarm over whatever channel still works, **once per fault**. The record is on disk, so a relay restart does not re-announce it; it clears when the channel works again or the fault changes |
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
   Server酱 refuses), and `route_of` demotes the maintenance titles that are
   not game alarms. The daily report itself goes to Server酱 (`daily=True`).
2. **Nothing already in the daily report or on the phone page is pushed.** Such
   titles are on the `log` list in `notify.py`; adding a push means adding a
   row to the table above with a reason, and the test fails otherwise.
3. **The private chat is never written to on my own initiative.** It is in no
   automatic order; `push.py --private` exists only for text he dictates.
4. **My tests never reach him.** Test dispatches are marked (`run-one.sh --test`)
   and collapse to one line in the daily report; the drill scripts that emit
   a push say so in their header and are run only when he asked for a test.
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
| ❌ <script> 失败 | group | a run failed and stayed failed |
| ⚠️ 这一轮没干完 | group | queue ended with items undone |
| <队列> 没有运行 / 机器没开机 | group | the machine or a queue did not run |
| 🔌 AUTO-MAS 启动不起来 | group | nothing can run until a person looks |
| ⚠️ 中继自更新没成功 | group | the relay is stuck on old code |
| ⚠️ 中继暂时不能在脚本跑完时马上处理结果 | group | results would be delayed |
| 🩺 中继自己报错了 | group | the relay's first ERROR of a boot; one per boot, the rest stay in relay.log (2026-09-17: one unread ERROR line, evening queue lost) |
| 🩺 开机自检没过 | group | a boot-time assumption (process table, AUTO-MAS API, its logon task, writable dirs, a channel) does not hold; the shift may not run |
| 🛑 没能停干净，需要你动手 | group | estop failed |
| ⚠️ 自动采集：补跑仍有路线没走通 | group | the day's gathering stayed incomplete |
| 🚩 自动采集：有路线连续两天补跑失败，是复发性问题 | group | needs a person (upstream issue) |
| 🆕 预更新 / 🆕 游戏更新 / 🔁 更新后重跑 | info | a game or script changed version (rare) |
| ⚠️ 预更新没能确认 / ⚠️ 游戏更新没能确认 | info | maintenance did not confirm; not a game failure |
| ⏸ <script> 进不了游戏，稍后补跑 | info | server maintenance day |
| 🥚 刷声骸收工 | info | the farm he ordered has ended |
| 🌙 今晚不关机 | info | the machine will stay on and why |
| 💳 月卡快到期 | info | a monthly card he registered ends within five days; one a day, all games in one message (user order 2026-09-26 02:47) |
| 📱 配置没改成 / ✗ … | info | his phone order failed |
| 🔓 终末地日常已开回 / 🧹 清掉了死条目 / 🧩 换写设置格式 | info | config maintenance (rare) |
| ⚠️ OK-WW 补丁有 N 条没贴上 | info | a patch no longer binds |
| 🗓️ 新的一周 | info | Monday summary of the three weekly gates |
| 🧷 上游改了导出日志的代码 | info | evidence bundling needs re-checking (rare) |
| 🔌 推送通道故障 | info | a channel is dead (once per fault) |
| 🔄 中继已更新 | log | the notes go into the daily report's 「今天中继改了什么」 |
| 🗓️ 周常 | log | the phone page shows the weekly state |
| ⏭️ 跳过模式 / 🛑 已停一切 / 📱 手机指令暂缓 / 📱 配置已修改 / ✅ … | log | the answer is on the phone page: per-row receipts for settings, 「机器最近的回执」 for actions |
| 🗂️ 证据包已送出机器 | log | the link is in the failure alarm and in the daily row (证据包) |
| 🔁 自动采集：只补跑失败的路线 / ✅ 补跑后全部走完 | log | the daily report has a 「自动采集补跑：走通 … / 仍失败 …」 line |
| ⚠️ <script> 中途失败过，重试后成功 | log | the daily report carries the retry |
| 🩹 OK-WW 补丁（N 条） | log | the healthy case |
| 🥚 开始刷声骸 | log | acknowledgement of his order |
| 🔁 自动采集：这一轮重跑只走没走通的路线 | (not sent) | log line only, in the daily report |

`scripts/mac/push.py` on the Mac follows the same rule and the same order, with
`--all` to override.
