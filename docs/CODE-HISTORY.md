# The backstory lifted out of the code

Step three (2026-09-06): the code keeps only the single line saying "why it is written this way",
and the incident history moves here.
Each section's heading is `file:function`, and the body is the comment lifted verbatim from that
location.

## service.py:(模块级)

```
# How long a *live* Electron shell with no backend is left alone before the
# revival is allowed to force-kill it. The stuck state this guard exists for
# lasts hours; a first-run environment wizard - installing Python, pip and
# git, then cloning the backend - legitimately has no backend for several
# minutes and looks identical. On 2026-08-22 the revival killed that wizard
# twice mid-clone and the operator was told all six mirrors had failed.
```

## service.py:SvcStop

```
# Hard backstop: if it has not exited cleanly after 15 seconds, force the
# process to exit.
# The user, 2026-08-31: 「中继服务卡在 STOP_PENDING 这个不要再出现了，
# 直接浪费很长时间，杜绝。」 - it hung four times that one morning, ten
# minutes of waiting wasted on every deploy, and every time it had to be
# force-killed remotely.
# Why forcing the exit is right: hanging in STOP_PENDING is far worse than a
# forced exit - deployment is paralysed outright, the notification path stays
# broken, and a person has to come and rescue it. And every piece of this
# process's state is written to disk atomically (see config.atomic_write_text),
# so a forced exit cannot corrupt anything; the only real loss is "the few
# records this round had not finished processing", and the next startup picks
# them up again.
```

## service.py:main

```
# New code before anything else uses it. This block was silently lost
# in a refactor on 2026-08-17 - a range replace swallowed it - and for
# three commits the machine stopped receiving updates at all while the
# log still looked healthy. Keep it adjacent to its own marker.
# Before anything reaches for the network. Both the update and the
# inbox run in the seconds after boot, and on a cold boot there is no
# DNS yet - so both used to fail on every single boot and give up.
```

## service.py:_stage_patch_okww

```
# Re-apply the OK-WW patches on every startup - idempotent, and it writes not
# a single line when they are already in place.
#
# They used to be applied only inside the boot-time pre-update stage, so a
# patch edited during the day, deployed, with the service restarted,
# **would not take effect until the machine booted the next day**. That is
# exactly what happened on 2026-08-27: the 残像聚落 fix for
# 「只刷落渊南丘」 was pushed to the machine, the file on it was still the old
# one, and I thought it was already done.
# 「更新必须立即生效」 is a standing order - once the deploy is finished the
# state must be final, with no "wait for the next boot" tail left hanging.
```

## service.py:_stage_announce_update

```
# Plain language first. The user, 2026-08-26: 「更新内容用人话写」 -
# a string of file names tells someone who cannot read code nothing at all.
# RELEASE-NOTES.md is pushed along with the deploy and says "which problem
# that you actually ran into has been fixed".
# File names come second, listed only as a fallback when there is no notes file.
```

## service.py:_stage_inbox_and_phone

```
# Once, at startup. The machine boots for each queue, so a change
# pushed while it is off - which is nearly always - lands before that
# day's run. Re-checking on a timer was added and removed again: it
# bought nothing the boot check did not already cover.
# ---------- phone side ----------
# The shape the user set on 2026-08-31: on boot it must fetch commands once
# and report status once; it must report before shutdown; pressing refresh on
# the phone gets the status in real time (only while the machine is on);
# online/offline must not rely on polling. How it is done is in the module
# docstring of phone.py.
```

## service.py:_stage_preupdate

```
# MaaEnd updates itself at startup and restarts its own process when it
# finds a new build. AUTO-MAS kills and relaunches it before every
# round, so every round lands on that check, and the restart orphans
# the log monitor AUTO-MAS just attached - every task in the round is
# reported failed seconds later. Measured 2026-08-22; the channel is
# `beta`, which ships most days, so most days opened with a wasted
# attempt and a failure alert.
#
# Auto-update stays on - being current is the point of it. The update
# is moved instead: done here, in the gap between boot and the first
# queue, where a restart costs nothing. By the time the queue starts,
# the check answers "有更新=false" and the process AUTO-MAS launches is
# the one that stays.
```

```
# Anything that could not be *checked* lands here. A pre-update
# that cannot tell whether an update exists must say so: on
# 2026-08-25 OK-WW was launched into session 0, its updater
# never ran, and the unchanged version file was reported as
# 无需更新 while v3.6.5 had been out for fourteen hours.
```

```
# OK-WW's auto-update overwrites the whole of src and wipes the local patches
# out (measured 2026-08-26: after v3.6.5 → v3.6.6-beta.1 both patches were
# gone, backups included). So they are re-applied on every boot - idempotent,
# doing nothing when they are already in place.
# Placed after run_okww: let it finish updating first, then patch the new code.
```

## service.py:_loop

```
# A pause order that failed to download is not a pause order. On
# 2026-08-17 the queue file was unreachable all evening and the
# operator's stop order silently never arrived - so a failed boot
# fetch is retried every five minutes until the file has actually
# been read once, instead of waiting a whole day for the next boot.
```

## okww_patch.py:ensure_patches

```
# Withdrawn 2026-08-31: the premise itself was wrong. The signature of
# ok.util.logger.Logger.error is error(self, message, exception=None) - the
# second parameter **is the exception already**, and internally it prints the
# stack through exception_to_str(exception). There is nothing wrong with the
# upstream code. The exc_info=True I added is something that wrapper does not
# understand at all: an instant TypeError, turning a recoverable retry into a
# hard crash (that is how the 16:00 round died).
```

```
Cut from four patches down to one on 2026-08-30. The only one left is the
whole-file replacement for 残象聚落, because "farm only the sites I name"
does not exist upstream at all and can only be obtained by swapping the entire
file.

The three that were withdrawn, all for the same reason - **there is no
evidence that they still do anything**:

* Main-DPS starvation backstop - it was caused by our own change to the game
keybinds (admitted upstream in #1632, and we closed the PR ourselves). Once
the keybinds were put back to default, the symptom never appeared again.
* Do not let a failed instance take the whole daily task down - it corresponds
to the 08-26 case of "walk to the chest, pick up nothing → wait times out →
the whole daily run collapses", most likely a full bag. But this patch was
only added on 08-28, and **the symptom had already stopped appearing on
08-27**; the illness was gone before the medicine arrived.
* Move reward claiming to the end - the upstream author closed PR #1631 on
2026-08-29 without leaving any explanation. And that ordering is deliberate on
the author's part; it is spelled out in `config_description`.
Turn it into an issue asking "could this be made configurable", and stop
changing it locally.

All three were actively reverted, not merely left un-reapplied.
```

## engine.py:Engine

```
# These particular failures inside MaaEnd are problems of upstream or of the
# game itself, not faults that need a person in the middle of the night:
#   应急理智加强剂: beta.5 is broken at the 「选择加强剂」 step (recorded 09-03, turned off pending upstream)
#   自动采集: out of 15 routes there are always two or three 「采集失败」, which makes the task as a whole report failure while everything else was collected
# The user, 2026-09-03: 「今天下午或者明天再报错你就滚」 - these go into the
# daily report only; they are not pushed as ⚠️.
```

## engine.py:_scripts_running

```
# Endfield.exe is on this list because MaaEnd has NO process of its
# own - AUTO-MAS's python drives it in-process (verified 2026-08-20:
# during a MaaEnd run tasklist shows only the game). Watching for
# "MaaEnd.exe" alone made this check blind through the entire 终末地
# phase; the game binary is the only visible sign that phase is live.
```

## handle.py:_maa_app_log

```
# A start marker with no end marker sweeps **the rounds that follow** in too.
# During the dry run on 2026-08-30, the 08-29 evening shift read 72810 lines
# (twice what this morning's round had) and the skill-failure count became
# 20+21=41 - which charges this morning's errors to last night. So there has
# to be an upper bound.
# When `until` is None no upper bound is set - the timestamps on a record with
# `duration_known=False` cannot be trusted, and in that case it is better to
# take too much than to cut a whole round away.
```

```
AUTO-MAS's history log only records "did the script finish or not"; **there is
no per-subtask success or failure**. So before 2026-08-30 a complete
infrastructure failure (`InfrastAbstractTask::on_run_fails`) was still recorded
as all green - that is where the "all green" the user saw two days running
came from.

Where it differs from MaaEnd: MaaEnd writes a new file per round, so rounds can
be picked by mtime; MAA has **one rolling asst.log**, which can only be cut by
the timestamps at the start of each line.
```

## handle.py:_handle

```
# Only a pass that actually reached the weekly cap counts. MAA
# reports Success! even when it stops early for want of sanity, and
# closing 剿灭 on that would skip the rest of the week with the cap
# unmet - the run on 2026-08-17 needed five sorties and 125 sanity
# to get from 0 to 1800.
```

```
# 2026-08-26: this used to read `notes.append(msg)`, but there is no notes in
# this scope at all - a NameError tore through the whole of _handle, and that
# OK-WW record turned into 「处理运行记录失败」 on the spot. Write it the way
# the 🗓️ 剿灭 branch does; the two weekly gates were always supposed to have
# the same shape.
```

```
# AUTO-MAS saying "this script exited normally" does not mean it got the work
# done. 2026-08-27: OK-WW skipped 残象聚落 three rounds running, and MaaEnd
# got stuck on a popup and closed itself, treating a failure as completion -
# neither side reported a single ERROR, and this code still recorded ✅ and
# still stayed silent. The user's own words were 「他不报错，他直接把自己关掉了」.
# So check against the evidence before exiting; anything that did not get done
# has to speak up.
```

```
# MaaEnd does an "Auto-cleared log files and debug artifacts" at startup -
# the previous round's on_error screenshots and logs are deleted by MaaEnd
# itself **the instant it next starts**. That is how the three screenshots of
# the popup that blocked the morning of 2026-08-27 were lost: one retry at
# noon and the evidence was gone, leaving nothing afterwards but the file
# names I had copied down at the time. So the moment a failure is recorded,
# move the evidence out immediately.
```

## handle.py:(模块级)

```
# The same thing is reported only once a day. On 2026-09-01 the same OK-WW
# failure was pushed to the group three times in a row (17:00 / 08:29 /
# 11:54), and the user said: 「赶紧去修，报了三次了。」
# The key is script + which step failed: repeated failures at the same step
# are the same thing and must not be pushed again; a failure at a different
# step is a new thing and gets reported as usual. The day's ledger is
# state/alerted-<日期>.json; the daily report still totals up every failed
# round, and all that is silenced is the duplicate instant push.
```

## report.py:_maybe_daily_report

```
# Yesterday first. Everything below keys off "today", so a report that
# could not be delivered before midnight (channel outage - it has
# happened: 60020 all day on 2026-08-20) used to be abandoned the
# moment the date rolled: today's ledger is a different file, and no
# code path ever looked back. The runs are still in yesterday's
# ledger; send their report late rather than never.
```

## report.py:_compose_daily

```
# Event countdown rides on every report (operator order, 2026-08-20):
# a fixed-stage config plus an event ending overnight is a silent
# next-morning failure. Appended outside the model's text so a model
# outage can never drop it.
```

## claim.py:(模块级)

```
# ---- Actually claim the weekly boss reward --------------------------------
#
# Early on 2026-09-01, watching the screen, the user said:
# 「打完之后拿声骸直接一直重开去刷,这不是拿宝箱奖励」「这是声骸模式」.
# The log confirms it completely: all three rounds went
# Boss fight → farm echo on the face → dismiss the exit popup → restart,
# with the remaining weekly count sitting at 3/3 the whole time and 波片
# never moving off 91.
#
# **My entire premise was wrong.** `FarmEchoTask` + `Teleport to Boss =
# Weekly Challenge` is the mode for **farming 4C 声骸** - teleport to the
# weekly boss and grind it over and over; the reward-claiming step is not on
# this code path at all. That line 「结晶波片不足,无法获取奖励,
# 请确认是否继续进入」 is only **a warning shown before entering**, not
# "entering deducts 波片 and hands out the reward"; I read it backwards, and
# then wrote a document and three patches on top of that.
#
# The real claim: after killing the Boss, **walk up to the crystal, press F,
# and spend 60 波片**. `TacetTask` in the same repository already has this
# ready-made idiom (凝素领域 also spends stamina to claim):
#     walk_to_treasure() → pick_f(handle_claim=False)
#     → has_claim_stamina() → use_stamina(once=60)
#
# Inserted before 「退秘境」. Safety: `has_claim_stamina()` is the gate - if it
# does not recognize that screen, nothing is spent and the old path runs
# unchanged; the whole block is wrapped in try, so any exception merely falls
# back to the previous behaviour and cannot take the daily task down.
```

## core.py:_Patch

```
# The signature string of this patch that **does not change across versions**
# (the log line, for instance). Once applied it must appear exactly once;
# appearing more than once means an old version was not cleanly reverted and
# two layers are stacked.
# Why the first line of `new` cannot be the test: stacking means "old version
# + new version" coexist, and the new version still appears only once, so
# counting it can never catch the problem. That is exactly how it slipped
# through on 2026-09-01.
```

## core.py:_apply_one

```
# Note that the test in present() has to change together with `new`.
# Stepped on it 2026-08-31: I added a debug line to "skip the weekly boss when
# 波片 is short", but present() was still matching that log line, which had
# never changed, so _apply_one decided "already in place" and returned at once
# - the new version **was silently never deployed** - while I sat looking for
# that debug output in the log and wasted a whole round.
# The test must match something in `new` that is **unique to this version**;
# change the content and the test has to change with it.
```

## count.py:(模块级)

```
# ---- Before entering, take a shot of the Boss page to see how many attempts are left this week ----
#
# On 2026-08-31 the user asked: 「你确定刷的两次周本奖励是 90 级的副本？」 -
# a fair question. Level 90 was only written into the master copy at 16:20 and
# only synced across at 16:41; every earlier round had been clicking
# 「推荐等级80」. And the "2 attempts used" number was something I **inferred**
# from stamina consumption, not something I read. Inference has been wrong
# several times already, so this time go and read the real thing.
#
# Safety: when 波片 is short you cannot get in (the 「结晶波片不足」 popup comes
# up and our patch cancels and skips), and **no attempt is consumed**. So this
# screenshot can be taken safely even when 波片 is short.
```

## domain.py:(模块级)

```
# ── Patch 2: an instance that was not cleared should not take the whole daily task with it ──
# Measured 2026-08-26: 凝素领域 not cleared inside the time limit → no chest
# drops → walk_to_treasure raises WaitFailedException → it is not in the
# except → it propagates all the way to DailyTask.run.
# Four consecutive 「Daily Task exception stopped」 that day, with reward
# claiming / mail / additional tasks all skipped and total daily points 0.
# Meanwhile, right next to it in farm_domain_with_recovery_loop, the author
# wrote a recovery retry with max_recovery_retries=3 that can only be entered
# through `return False`, so for this failure mode it is entirely dead code.
```

## farmerr.py:(模块级)

```
# ---- Weekly boss livelock: print the exception that was being swallowed ----
#
# Measured 2026-08-31: between 12:35:53 and 12:47:44 it went round the loop
# 「传送 → found a claim reward → 传送」 21 times at 35 seconds a lap, burning
# 12 minutes before it actually got to fight the Boss. The upstream code is:
#
#     except Exception as e:
#         logger.error('farm 4c error, try handle monthly card', e)
#         if self.handle_claim_button() or self.handle_monthly_card():
#             self.run()
#
# logging treats the second positional argument as a printf argument for msg,
# and msg contains no %s, so **the exception content is thrown away entirely**
# - all the log keeps is one contentless 'farm 4c error' line, and the real
# cause cannot be found. This patch only changes it to exc_info=True and
# **touches no control flow at all**: the recursion, the retry count and the
# conditions are all left exactly as they are. The next time the weekly boss
# runs, the real cause will write itself into the log.
#
# The recursion having no bound is an upstream design problem; an issue has
# been filed, and we do not change control flow locally on our own initiative
# - doing that would mean touching a production script with no evidence.
```

## letpass.py:(模块级)

```
# ---- Let the "deliberate skip" signal pass through the catch-all ----------
#
# The catch-all in teleport_to_configured_boss_and_prepare wraps **every**
# exception into a RuntimeError:
#     except Exception as e:
#         raise RuntimeError('Teleport to boss failed') from e
# so the TaskDisabledException we raise deliberately gets wrapped as well, the
# `except TaskDisabledException: pass` in run() never sees it, and it falls
# into the generic catch-all further down, which logs one farm 4c error and
# then recurses to retry.
#
# Measured 2026-08-31: when 波片 was short it did skip, and not one Boss round
# was wasted, but the log still carried 3 farm 4c error lines and the skip was
# repeated 3 times - blocked by exactly that wrapping layer.
# Let TaskDisabledException through; everything else is still wrapped into
# RuntimeError as before.
```

## nest.py:_apply_nest

```
# Upstream will never contain this configuration constant we invented
# ourselves, so seeing it means the copy on the machine is some version we
# applied, and it gets overwritten as usual.
# Why not rely on _NEST_KNOWN_OURS alone: that table requires **a hash to be
# added by hand every time the patch changes**, and on 2026-08-29 I changed
# the patch and forgot to add one, so the fix could not be pushed while the
# deploy still reported success (it left exactly one warning line in the log).
# A step that depends on a person remembering will be missed sooner or later;
# a marker will not.
```

## nofarm.py:(模块级)

```
# ---- Disable stamina farming, keep 波片 for the weekly boss ----------------
#
# The user, 2026-09-01 03:25: 「把刷贝币刷体力的任务禁用，这样就不可能会出现
# 波片被消耗的情况。」 Claiming the weekly reward once costs 60 波片, three
# times 180; and daily farming (凝素/深渊/模拟领域) eats 波片 to nothing - the
# two compete for the same resource.
# That is exactly how it got eaten on 2026-08-31: at 18:23 贝币 farming spent
# 波片 down from 41 to 1.
#
# `Which to Farm` has only three options (凝素/深渊/模拟领域) and **no "do not
# farm"**, so the only way is a patch. It uses a **marker file** rather than a
# config option: to restore the behaviour just delete that file - no code
# change, no redeploy.
```

## nowave.py:(模块级)

```
# ---- Skip cleanly when 波片 is short: no spinning, no wasted fights --------
#
# On 2026-08-31 I captured the screen at the moment of failure; what the game
# put up was:
#     「结晶波片不足，无法获取奖励，请确认是否继续进入？」[取消][确认]
#
# Three things fell into place because of it:
#   * The weekly boss has no "kill it, then open a chest" step; the reward is
#     handed over directly by **deducting 60 结晶波片 on entry**;
#   * When 波片 is short, that popup **blocks 「开启挑战」**, wait_click_feature
#     times out and raises WaitFailedException, and run()'s catch-all recurses
#     and starts over → 21 empty laps from 12:35 to 12:47;
#   * Choosing 「确认」 means going in without taking the reward, which is why
#     stamina read 56→56 after three rounds - pure wasted effort.
#
# Going in without enough 波片 gets no reward either, so the right move is to
# click 「取消」 and quietly skip this weekly boss.
# TaskDisabledException is raised because run() handles it with `pass` -
# FarmEchoTask ends silently, the daily task carries on, and it does not take
# the whole daily run down the way an ordinary exception would (which is
# exactly how my 16:00 round crashed).
```

```
# The original text of the v1 version. Kept **only so that it can be
# reverted**: its replacement text carries the anchor
# `self.click_team_challenge()` at the end, so once I changed present() to
# match v3, _apply_one pasted another layer on top of it - two checks present
# at once, with v1 running first, and v1 is precisely the version that
# misjudges. Measured 2026-09-01: 波片 91 (>60) was still judged 「不足」 and
# skipped. A patch whose `new` carries its own `old` inside it is the root of
# this stacking.
```

```
# The original text of the previous version, v3, kept **only so that it can be
# reverted**. It swallowed the whole anchor line click_team_challenge(), so
# changing this patch again requires first restoring it to the upstream
# original; otherwise _apply_one cannot find `old` and reports 「贴不上了」 -
# which is what happened on 2026-09-01, and when I grepped the deploy output I
# filtered only for 「部署完成/❌」 and let that warning slip past, so the
# machine spun for 95 minutes while I believed the new patch was running.
```

## retrycap.py:(模块级)

```
# ---- Catch-all retry cap: quit after three failures in a row, never spin forever ----
#
# The catch-all in the upstream run() retries recursively with no bound at all
# as long as handle_claim_button() holds. Measured 2026-09-01: 81 laps, 50
# minutes. The user: 「一直卡循环了……你没有写退出机制。」 Add a cap: after 3
# consecutive farm 4c error the task ends, raising TaskDisabledException (run()
# swallows it quietly, so the dailies are not dragged down).
```

## shot.py:(模块级)

```
# ── Patch: take a screenshot at the moment the weekly reward is claimed ──
# 2026-08-31: three full weekly rounds and stamina had not moved at all, which
# means the reward was never claimed.
# The line in question is `wait_click_feature('claim_cancel_button…',
# relative_x=2)` - `relative_x` is "X relative to the box", so 2 means two
# button widths to the right of the cancel button's left edge, and **the
# intent is precisely to click the claim button on the right** (the user says
# the claim button is at the bottom right of the popup). The log clicked at
# (538, 675); whether that offset is enough or not cannot be settled without
# seeing the screen at that moment.
#
# This patch **changes no behaviour at all**; it only saves an image before
# the click. The next weekly run produces evidence, so there is no more
# guessing at button coordinates - guessing coordinates and then editing a
# production script is exactly the 826 class of mistake.
```

## shot2.py:(模块级)

```
# ---- Leave evidence before leaving the weekly instance --------------------
#
# Pinned down 2026-08-31: after the Boss is killed and the 声骸 collected,
# `do_run` goes:
#     if self._in_realm and not self.in_world():
#         self.send_key('esc', ...)                 ← leaves the instance directly
# The chest step does not exist at all. The previous version took its
# screenshot **after** the esc and caught only the 「确认离开」 popup - one
# wasted shot. This one moves it **before** the esc, capturing the screen at
# the moment the Boss dies, to establish what form the chest actually takes
# (an F prompt? an icon? or something you have to walk to?).
#
# Zero behaviour change: one extra screenshot, wrapped in try, and a failure
# does not affect the flow either.
```

## starve.py:(模块级)

```
# ── Patch 4: main-DPS starvation backstop ─────────────────────────────
# When 协奏 cannot be filled, has_buff() is permanently False and
# _unbuffed_non_main_target makes the two supports swap between each other
# forever, so the main DPS never gets on the field - and the main DPS is the
# only one with any chance of building 协奏 up.
# Measured 2026-08-26: across 56 swap decisions the main DPS was picked 0
# times, and the team was ground down with zero damage output the whole way.
# The root cause was that the game keybinds had been changed (see issue #1626)
# and is already fixed; this is kept as insurance and normally lies dormant
# (measured: in a healthy fight the swap sequence is identical to upstream).
# 2026-08-27: it was originally applied by hand and never entered this list,
# so a single OK-WW update washed it away.
```

## teamshot.py:(模块级)

```
# ---- Leave evidence when 「开启挑战」 cannot be found ----------------------
#
# The real cause, 2026-08-31 (the stack had been in the log since 12:35; I
# just had not read it):
#     teleport_to_configured_boss_and_prepare
#       → teleport_to_configured_boss
#         → click_team_challenge()
#           → wait_click_feature('team_start_challenge', raise_if_not_found=True)
#             → WaitFailedException
# After teleporting to the weekly boss the 「开启挑战」 button cannot be found,
# so it raises → retries → teleports again: 21 empty laps from 12:35 to 12:47.
# Upstream #1551 is about the same template match failing.
#
# On this weekly path there is one more click at hard-coded coordinates before
# the button, self.click(0.880, 0.911), and if that one lands wrong everything
# after it is wrong. Whether the template failed to match or the page never
# opened at all **cannot be settled without seeing the screen at that moment**,
# so save the image first and then raise; the `raise` guarantees the behaviour
# is unchanged.
```

## service.py:_wait_for_network

```
Measured 2026-08-21 21:20:19, one second after the service started on a
fresh boot: all four update doors failed with
`[Errno 11001] getaddrinfo failed`, and thirty seconds later raw was still
only getting as far as a TLS handshake timeout. The relay starts within a
second or two of logon, well before Windows has finished bringing up DNS,
so the boot-window update - the whole point of that window - was reaching
the network before there was one, every single boot.

Nothing downstream retried its way out of that: _best_manifest asks each
door once and returns None if none answer, so the round was abandoned
before the doors were reachable.

The boot-to-queue gap is about ten minutes, so waiting up to ninety
seconds here is cheap. Failing to wait costs the entire update.
```

## service.py:run

```
Before 2026-08-30 this was one-shot: one hiccup in RPC (in relay.log,
`SWbemEventSource 远程过程调用失败`, 24 times between 08-24 and 08-29) and the
thread simply exited, leaving **the whole rest of that boot cycle** stuck on
120-second polling. The machine boots only twice a day, so the relay spent
most of its running time in degraded mode.
There is a fallback, but a fallback should not be where it ends.
```

## service.py:collect

```
Configuration changes must stay clear of the window in which a script is
running. While AUTO-MAS is running, it overwrites ScriptConfig.json from the
copy in its memory, so values written during that window are wiped silently -
measured twice on 2026-08-20: set_wait_time 120 was pushed back to 60 and the
剿灭 switch was pushed back to on, so every round wasted another 剿灭 run.
engine.scripts_running() exists precisely for this; this adds the call that
was missing.
```

## handle.py:_okww_nest_expected

```
It used to return False when it could not read the config, so "the config says
it does not need doing" and "I never managed to read the config at all" looked
exactly alike - and the latter makes the 残象聚落 item **disappear entirely**
while OK-WW still reports all green.
`_okww_master_config` returns `{}` in three cases - no automas_dir, no data
directory, and a broken JSON read - and any one of them ends up here.
This is the class of bug diagnosed on 2026-08-30: a precondition is not met →
it silently does nothing → it looks like success.
```

## handle.py:_maaend_app_log

```
The completion marker 「INFO [App] 自动执行任务完成，关闭自身」 appears only in
`<maaend>/debug/YYYY-MM-DD-N.log`, **not in AUTO-MAS's history log**.
The 2026-08-29 morning shift checked only the latter, so "MaaEnd finished" was
permanently false and a false alert saying "this round did not finish" was
pushed - while MaaEnd had plainly printed that line at 09:54:38.
The test was not wrong; what was wrong was not giving it the file it was
supposed to read.
```

## handle.py:_warn_if_evidence_stale

```
The relay only learns about a failure by watching AUTO-MAS's history, and
AUTO-MAS writes the record only once the whole round is over. By the time the
message arrives, MaaEnd has usually already retried successfully and cleared
debug on startup, so what gets saved is the log of **the retry that
succeeded**.

That is the circle it went round on 2026-09-05: the evidence directory was
named after the failing run (MaaEnd-05-27-42), but the maafw.log inside it
covered only 09:57-09:59, which belongs to the successful run
(MaaEnd-05-56-35). What actually located the problem was the AUTO-MAS .json
saved alongside it.

run_id has the form `<日期>/<用户>/MaaEnd-HH-MM-SS`, and the last segment is
the start time of that round.
```

## report.py:_fill_single_run_sanity

```
「当前理智」 is announced **before** each claim, so one round has a single
reading and zero steps, and this record cannot compute the consumption on its
own. The daily report of 2026-09-04 printed a dash for it: that round actually
went from 116 down to 37, spending 79, except that the two numbers landed in
two separate records, one before and one after.

Fill it in only when both readings come from the same day and the same script
and both have a remaining-sanity value; when it cannot be filled, leave it
empty - better empty than a number that was made up.
```

## report.py:_announce_banners

```
Set by the user on 2026-08-31: send to the group only on 「任意游戏的新卡池开放的前一天」
(the day before any game opens a new banner), and the rest of the time he reads Server酱 himself. So it goes through
send_group and not send - the latter prefers Server酱 and stops at the first
success, so it would never reach the group.

Marked by "game + start time": two games rotating banners on the same day each
get their own announcement, while the same banner must not be announced a
second time just because the daily report was resent.
```

## shutdown.py:_boot_time

```
Uptime, not the relay's own start time. The relay restarts itself for
every selfupdate, so `eng._started_at` moves - and an update that ran
past a queue's time made the new process disqualify itself from
reporting the missed run, on precisely the boot where something had
already gone slowly enough to be worth knowing about.

`GetTickCount64` is milliseconds since boot and never needs a clock
that agrees with anything. It is Windows-only; anywhere else this
returns None and the callers fall back to their own start time, which
is the conservative direction - a missed-run alarm that is skipped
beats one invented out of a wrong boot time.

This method was referenced from three places since 2026-08-21 and never
actually written. It raised AttributeError inside `_check_missed_runs`,
which the service loop caught and logged, so the relay stayed up while
silently doing none of the work that follows: no missed-run alarms, no
daily report, no power-off. See PITFALLS.
```

## shutdown.py:_unfinished_queues

```
"No game process" is not the same as "the queue is finished". Between
two scripts in one queue there is a window - MAA has exited, MaaEnd's
game is still launching - where neither process exists, and the same
window exists at the very start before the first game comes up. Acting
in it costs a run: it cost 终末地 the morning of 2026-08-16.
```

## shutdown.py:_work_is_done

```
The durable version of `_handled_any`, which only knows what *this
process* watched land. A relay restart after the last run - a
selfupdate is exactly that - cleared the flag, so nothing was left to
trigger the shutdown and the machine stayed awake all night. It cost
2026-08-20 a manual power-off.

Two requirements, and dropping either one costs a run:

A queue must actually have come due. "Nothing is unfinished" is
vacuously true at 08:50 with the 09:00 queue still ahead, and acting on
it would power the machine off minutes before its own run.

And the machine must have booted *before* that queue was due - this
boot has to be the one the queue was scheduled for. Without that test
the rule reaches a machine somebody powered on at 10:35 to work on: the
09:00 queue is still inside its two-hour window and its records are
already in the ledger from the morning, so "everything is finished"
reads true and the machine switches off under them ten minutes later.
Uptime is what distinguishes the two, not the relay's start time, which
every selfupdate resets.

Residual, deliberately not widened: `recent_due_queues` forgets a queue
two hours after it was due, so a restart later than that still leaves
no one to shut down. Widening the window here would also widen the
"wait for a script that never ran" hold that shares it.
```

## shutdown.py:_round_is_manual

```
Manual rounds have to be labelled separately (operator order,
2026-08-20): a scheduled round and a hand-triggered make-up run must
be distinguishable at a glance, or the operator cannot judge whether
a given message was supposed to appear at all.

The test looks only at how far this round's earliest record sits from
a scheduled time - and the scheduled times are read straight from
AUTO-MAS's queue config, so changing the schedule needs no matching
change here. If no schedule can be read it returns False: better to
leave a round unlabelled than to mislabel a scheduled one as manual.
```

## shutdown.py:_last_round_manual

```
A manual round must not count as "the day's work is done". On
2026-08-21 a hand-triggered MaaEnd test finished at 12:29 and the
relay promptly powered the machine off - while the operator was in
the middle of working on it, and hours before the evening queue.

The round is the group of records that finished close together; two
hours is comfortably wider than a full queue (MAA then MaaEnd) and
far narrower than the gap between the morning and evening queues.
```

## shutdown.py:decide

```
- the feature is off -> never
- debug mode / this one opportunity already consumed -> never (judgement changed 2026-08-31, see below)
- a shutdown order has already gone out -> never (2026-08-16 it reported three times within one minute and shut down twice)
- this boot has not finished its queue yet -> never
- not up long enough -> never (guards against the boot-then-shut-down-again loop)
- a script is running / an alert has not been pushed / a client is updating -> never
- the most recent round was run by hand -> never (2026-08-21 it powered off a machine that was being worked on)
- the queue is still missing a script -> never (2026-08-16 it shut 终末地 down in the gap between two scripts)
- the time has come but the daily report has not gone out -> never (hold the shutdown for the report; the report is never silent)
```

## core.py:_stacked

```
The trap stepped on 2026-09-01: the replacement text of v1 **carries the
anchor at its very end**, `self.click_team_challenge()`, so once I changed
present() to match the new version, _apply_one pasted another layer on top of
v1 - two checks present at once, with the old one running first, and that one
is precisely the version that misjudges. 波片 91 (>60) was judged 「不足」 and
skipped as well.
Without this self-check, stacking is **invisible**: the file's syntax is fine
and present() is true as well.

The test uses the first line of `new` (the comment or code line unique to each
version); appearing more than once means it is stacked.
```

## service.py:stop_event

The second argument `0` in `CreateEvent(None, 0, 0, None)` means **auto-reset**:
whichever `WaitForSingleObject` sees the signal clears it on its way past. But
this event has three consumers - the main loop's `WaitForMultipleObjects`, the
phone channel's `listen()` through `stop()`, and the heartbeat's `loop()`
through `stop()`. When the service is stopped, whoever gets there first takes
the signal away and the rest go on believing that nothing has stopped.

The consequences, by date:
* 2026-08-31: several hangs in STOP_PENDING (the main loop did not win the signal
  and had to leave through the 15-second `os._exit` backstop).
* 2026-09-07 09:02: a deploy stopped the service, the phone channel treated the
  connection that `close()` had cut as an unexpected disconnect, and printed a
  whole `AttributeError: 'NoneType' object has no attribute 'peek'` into the log.

Changed to manual reset (second argument 1) on 2026-09-07: the signal stays lit,
so all three threads can each see it. The regression test
`tests/test_stop_event_manual_reset.py` watches this argument.

Addendum (same day): after the event was switched to manual reset, the gap
between "stop signal received" and "the main flow has returned" is 0 seconds,
yet `sc stop` still takes 20-27 seconds before the SCM reports STOPPED, and the
15-second backstop never fired once. The reason is that once `SvcDoRun` returns,
the process is handed over to the interpreter's shutdown: the remaining daemon
threads are stuck inside C calls (the phone channel's SSL read, the WMI process
monitor's COM wait) and `Py_Finalize` waits for them; the backstop's
`threading.Timer` is a Python thread, cannot get the GIL during that shutdown,
and so never reaches `os._exit`.
The fix: at the end of `SvcDoRun`, call `ReportServiceStatus(SERVICE_STOPPED)`
+ `logging.shutdown()` + `os._exit(0)` itself, giving the heartbeat thread only
3 seconds to send its goodbye (bye).

## engine.py:_scripts_running（2026-09-07 补）

Looking only at the process list (MAA.exe / MaaEnd.exe / Endfield.exe) failed:
OK-WW is not on that list.
On the 2026-09-07 morning shift OK-WW started at 09:19 and ran three rounds, but
AUTO-MAS writes the run record only when the whole script section ends (10:16).
At 10:15 the missing-item check saw "no process running, no OK-WW record, no
MaaEnd record" and sent two false 「没有运行」 alarms. Changed to ask AUTO-MAS's
`GET /api/dispatch/runtime-snapshot` first (完成/异常/运行/等待 per script), and
fall back to the process check only when that cannot be reached.

## claim.py:(模块级)（2026-09-07 补，v5）

Once the reward is claimed, the game goes straight into a full-screen
「挑战成功」 results page (the screenshot is in the session record: six reward
cells, 「退出副本」 and 「重新挑战 剩余62」, 「281秒后自动退出」). ESC does not
dismiss it, so the upstream call that follows immediately,
`wait_click_feature('claim_cancel_button…', raise_if_not_found=True)`, times out
after 10 seconds and raises WaitFailedException; AUTO-MAS judges that a failure
and retries. Each of the three rounds claimed once (3/3→0), but daily stamina
farming never got its turn at all. 09-02 followed the same pattern, except that
on the fourth round it happened to hit a 「次数已达上限」 popup and got out that
way.
v5 pulls those four upstream lines into the anchor (`_CLAIM_OLD_FULL`): after
claiming, it OCRs for 「退出副本」 and clicks it, and if the click lands it skips
the ESC-and-popup stretch.
