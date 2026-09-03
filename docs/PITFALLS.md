# Pitfalls

Everything here actually happened, with the cause that turned out to be true -
not the one that looked true at the time. Kept because each one cost hours and
none of them is guessable from the code.

## Judgement failures

**Treating a timezone difference as a broken clock.** The server is UTC+8, the
operator is UTC+9. That one hour got diagnosed as NTP drift and nearly led to
running `w32tm` against a problem that did not exist. **Every human-readable
timestamp must name its clock.**

**Building before searching.** About 1000 lines of Python runner got written
before discovering AUTO-MAS already did all of it - scheduling, log-based failure
detection, restarts, multi-account config - and did it better. All 1000 lines
were deleted. Search first.

**Concluding from one sample.** A "cannot reproduce" was posted on an upstream
issue after checking a single log; the reporter's diagnosis was correct and the
evidence was in a different day's logs. Two comments then had to be deleted.
One sample is not a refutation.

**Blaming the instrument.** MaaEnd's first-attempt failures were attributed to
the remote screenshots stealing focus. An experiment disproved it. The cause is
still open; `focus-watch.py` now runs at logon to catch the next occurrence.

## The relay starts before the machine has DNS

Measured 2026-08-21 at 21:20:19, one second after the service started on a cold
boot:

```
21:20:19 取不到 https://fastly.jsdelivr.net/...  [Errno 11001] getaddrinfo failed
21:20:19 取不到 https://cdn.jsdelivr.net/...     [Errno 11001] getaddrinfo failed
21:20:19 取不到 https://gcore.jsdelivr.net/...   [Errno 11001] getaddrinfo failed
21:20:19 取不到 https://raw.githubusercontent...  [Errno 11001] getaddrinfo failed
21:20:49 取不到待办文件（raw...）  _ssl.c:983: The handshake operation timed out
```

All four doors, plus the inbox, in the same second - and thirty seconds later
raw was still only getting as far as a TLS handshake. The relay is started by a
logon-triggered task and comes up within a second or two of the desktop, well
before Windows has finished bringing up DNS.

Nothing downstream retried its way out of it: `_best_manifest` asks each door
once and returns None when none answer, so the round was abandoned before the
doors were reachable at all. **The boot-window update - the entire reason that
window exists - had never once run against a working network.**

This had been misread for days as "the CDNs are flaky from this machine", which
is separately true and was not the reason. The tell is the error: `getaddrinfo
failed` is not a slow mirror, it is no resolver. A door that is merely slow
times out; a door whose name cannot be resolved fails instantly, and all four
failing in the same second is not four independent outages.

`service.py` now waits up to 90 seconds for DNS before touching either channel.
The boot-to-queue gap is about ten minutes, so the wait costs nothing that
matters and skipping it costs the whole update.

## Session-scoped state in a self-restarting process

The relay restarts itself every time it applies an update. Any judgement of the
form *"what has this process seen?"* is therefore a judgement about an interval
with no relation to the machine's day - and it was used in three separate
places, each one failing the same way:

| Asked | Should have asked |
|---|---|
| `_handled_any` - did this process handle a record? | does the ledger show today's due queues finished? |
| `_started_at > due` - was this process up when the queue was due? | was the **machine** up when the queue was due? |

The consequences were all silent. A restart after the last run left nobody to
trigger the shutdown, so the machine stayed on all night. A restart that
crossed a queue's scheduled time made the new process disqualify itself from
reporting a missed run - on precisely the boot where something had already gone
slowly enough to be worth knowing about.

The durable answers are the ledger (survives restarts, on disk) and machine
uptime via `GetTickCount64` (survives restarts, in the kernel). Neither has
anything to do with how long the current process has existed.

**The first fix for this was worse than the bug.** Replacing "did this process
handle anything" with "are all due queues finished" reads true on a machine
somebody powered on at 10:35 to work on: the 09:00 queue is still inside its
two-hour window and its records are already in the ledger from the morning. It
would have powered the machine off under them ten minutes after they booted it.
Uptime is what separates "this boot is the one the queue was scheduled for"
from "somebody turned this on afterwards" - and that distinction has to be part
of the test, not an afterthought.

## Silent degradation is the failure mode this system produces

Not crashes. Every serious incident here has been something that kept working
while quietly doing less:

- an `scp` that returned 0 without transferring, so the service restarted onto
  old code
- a self-update that gave up cleanly and logged it, leaving the machine on old
  code while everything upstream assumed the push had landed
- a directory watch whose re-arm failed, dropping the relay to alarm-clock-only
  wakeups - records still processed, just up to an hour late
- a torn interim marker reading as "already sent", suppressing every further
  interim report that day
- a wording model that was down, costing a 60-second timeout on every alert and
  every report, inside the path that must finish before the machine may sleep
- a drop total that was overwritten instead of summed across stages, so a
  number in the report simply got smaller

None of these announce themselves, and several look exactly like a quiet day.
The rule that follows: **when a component degrades, it must say so through a
channel that is still working.** Logging is not saying so - nobody reads the
log of a machine that is off 21 hours a day.

## A test in the wrong input format is not a test

The drop-parsing tests used timestamps without brackets. MAA writes
`[2026-08-15 09:06:29.091][INF][TaskQueueViewModel]     <2> TO-5 掉落统计:` and
the parser closes a drop block on the next *bracketed* line. With unbracketed
input the block never closed, so every test passed while exercising a path that
does not exist in production - including, for one commit, the per-stage fix
they were written to protect.

Real log lines are in the session archives; use them. A parser test whose input
was written from memory is a test of the memory.

## Do not poll

**This is a standing order, not a preference.** Polling is the default move when
you cannot think of how to be notified, and every use of it here turned out to
be laziness.

| Was | Is |
|---|---|
| relay scanned `history/` every 30s | `FindFirstChangeNotification` - a record is handled the moment it lands |
| checked every 120s whether AUTO-MAS's backend was alive | WMI `Win32_ProcessStartTrace` + `OpenProcess` handle - woken the instant it exits |
| Fleet Monitor asked `tailscale status` every 30s | `watch-ipn-bus` long connection - the state change is pushed |
| Fleet Monitor 拿 tailscaled 的 `Online` 当「机器开着」 | 那是控制面的说法，不是能不能连上。断电不会登出，09-03 关机四小时后它还报 Online=True。现在每台声称在线的机器都要真回一个 disco ping 才画绿 |
| 手机页改终末地／鸣潮的设置，按下有回执但脚本照旧 | 这两个脚本的「快速配置」是关的，AUTO-MAS 直接 return，不把 MAS 用户配置下发给它们（`app/task/Okww/AutoProxy.py:320`、`MaaEnd/AutoProxy.py:537`）。真正生效的是各自的母本配置。**明日方舟没有这个开关**，它的关卡和理智药每次派发都会被写进 gui.new.json，走 MAS 是对的 |
| Fleet Monitor 每天弹两次上下线通知（还在开机时连弹） | 定时开机和跑完关机是这套机器的日常，没人需要被告知；开机瞬间「能连上但还没答话」会让状态来回跳，通知跟着刷。已整个去掉，状态看 Dock 图标；真出事由中继自己的渠道报 |
| Mac probed every 10 min for a chance to push code | deleted; the machine fetches from GitHub at boot |
| main loop woke every 300s to ask "is it time yet" | an alarm clock: compute the next exact instant and sleep to it |

The time-triggered events - "21:30 passed, send the report", "the queue produced
nothing by its deadline", "a checkpoint is due" - have no file or process to
signal them, but they still do not need polling: each has an exact next instant.
Enumerate those instants, sleep until the nearest. **Waking every N seconds to
look at a clock is still polling.** The difference is not just power: the
checkpoint window is 5 minutes wide and a 300s wake interval is the same width,
so an unlucky phase misses it entirely. The alarm clock removes that whole class
of bug. One hourly wake remains purely as a fuse against the alarm logic itself
being wrong; it has no detection duty.

Memory sampling every 600s is **not** polling - the point is the time series;
there is no event to wait for. The test is simply: *are you waiting for something
to happen, or periodically recording a state?*

## Encoding

**Chinese through heredoc → ssh → PowerShell turns to mojibake.** stdin is
decoded as GBK. A PowerShell here-string (`@'...'@`) through that pipe **fails
silently** - no error, nothing runs.

- Write scripts locally, `scp` them, execute with `-File`.
- **Never put Chinese in a `.ps1`**: PowerShell reads a BOM-less `.ps1` as GBK,
  quote pairing breaks, and it reports a missing string terminator.
- Use `findstr` (cmd) rather than `Select-String`.
- To return Chinese, base64 on the remote side and decode locally.

**A trailing backslash eats the quote.** `"D:\path\dir\"` - the `\"` is read as
an escape. Drop it or build the path from a variable.

**Chinese directory names are the root of all mojibake.** Perfectly legal on
Windows, GBK when they come back over SSH. The AUTO-MAS usernames were renamed
to `arknights` / `endfield` on 2026-08-21 for exactly this reason - and the
relay's `seen.txt` had to be rewritten in the same operation, because a record's
identity contains the username.

**A ✅ crashes a GBK console.** `print("\n✅ ...")` raises `UnicodeEncodeError`
under the GBK code page, so `check` and `test` both died *on the final success
line* - the work was done and the command reported failure. `logging` swallows
the same exception, so emoji log lines vanished from stderr while the file
handler (UTF-8) kept them. Fixed by `sys.stdout.reconfigure(encoding="utf-8",
errors="replace")` at the top of `main()`.

## Timing and time zones

**AUTO-MAS names history by a UTC+4 clock.**

```python
UTC4 = timezone(timedelta(hours=4))                       # constants.py
self.curdate = datetime.now(tz=UTC4).strftime("%Y-%m-%d") # AutoProxy.py
```

The machine runs UTC+8, so every filename reads four hours early. It stays
invisible as long as the log has timestamps - the relay prefers those. It only
surfaces when a run produced no timestamped log (a login failure that ended
before anything started), and then the report says "05:17 login failed" at an
hour when the machine was not even powered. Found on 2026-08-17 only because the
operator asked how anything could be running at 05:17.

**Never write a bare `datetime.now()`.** Every one must carry `tz=SERVER_TZ`.
`skip_today` originally used the host's local clock, which skips the wrong day
if the relay runs elsewhere or executes near midnight. The regression test runs
under `TZ=UTC`.

**Filename and mtime must come from the same clock.** Creating test data on the
Tokyo Mac with `touch -t 09:45` produced Tokyo 09:45 = server 08:45, *earlier*
than the 09:00 in the filename, and the duration came out negative. On the real
machine both are server local time, so they agree.

## Configuration

**AUTO-MAS overwrites external config edits from memory.** Proven twice in one
day: a `WaitTime=120` written by the inbox during the evening run was back to
`60`; the annihilation gate's `Annihilation=Close` was reopened, so every round
wasted another minute plus a full game launch on annihilation.

The rule is: **never edit AUTO-MAS's config while a script is running.**
`Engine.scripts_running()` exists for this; the inbox path did not call it and
now does, deferring commands until the scripts stop. The annihilation gate was
also made idempotent (`enforce()`) so it can re-close after being overwritten -
the old code returned as soon as `done_week` matched, so one overwrite lost the
whole week.

**Annihilation runs every single time because nothing remembers the week.**
The symptom is two MAA records per round, the first only ~1 minute: that minute
is MAA recognising the weekly cap and exiting. In `AutoProxy.py`:

```python
self.run_book = {"Annihilation": ... == "Close", "Routine": False}
```

`run_book` is rebuilt in memory on every run, so "annihilation is done this week"
is written nowhere. AUTO-MAS only offers the static `Info.Annihilation` switch
(`Close` / `Annihilation` / `Chernobog@Annihilation` / `LungmenOutskirts@Annihilation`)
- there is no "once a week" semantics to configure. The relay supplies it.

Related: the 1m23s annihilation pass is not worth cutting. The emulator stays up
and the daily pass starts 5 seconds later, so it costs 1.6% of the round and
skipping it forfeits the weekly reward.

**Regex JSON edits miss things and damage others.** Three webhooks to disable,
two disabled: the third had a `customName` between `taskName` and `enabled`, and
the regex instead hit history records under `recentlyClosed`. Structural diff -
flatten both sides to `path → value`, compare added/removed/changed - is what
caught it, and is now mandatory.

## Do not half-configure a feature you cannot finish

The Endfield account field was filled in and the password field was not,
because whoever filled it in could not supply a password. That combination is
not "partly configured" - it is a state that can only fail, and it failed
silently for two days behind a retry-three-times-then-move-on facade.

Worse, the failure it produced pointed at the wrong thing: "「明日方舟：终末地」
登录失败" reads as an account or network problem. The account was signed in the
entire time. It cost a full day of Endfield runs and a long detour through
crash logs, game bulletins and version files before the config turned out to be
the cause.

**If a feature needs something you cannot provide, do not start it.** Say what
it needs and leave it alone. A field that is filled in looks configured to
everyone who reads it later, including whoever wrote it.

## MaaEnd

**First attempt fails instantly, second succeeds.** All 14 items dead, five log
lines: window connected → foreground controller attached → "connecting to
window..." → nothing. The game rebuilds its window during first launch and
MaaEnd connects within a second of it appearing, so the handle goes stale. The
second attempt takes over an already-running game and is fine.

**Retry is the fix; do not treat it as a real fault.** The tunable is MaaEnd's
own post-launch wait.

**The cause, confirmed 2026-08-22: MaaEnd updates itself mid-round.**

MaaEnd checks for updates only at startup. AUTO-MAS kills and relaunches it
before every round, so every round lands on that check. When there is a new
build it downloads it and **restarts its own process** - and AUTO-MAS's log
monitor is attached to the pid it launched, which no longer exists:

```
11:47:57  AUTO-MAS starts MaaEnd
11:47:58  MaaEnd.exe pid=15772   <- the process AUTO-MAS is watching
11:48:14  MaaEnd.exe pid=20416   <- restarted after updating
11:48:18  all 14 tasks reported failed
```

MaaEnd says so itself on the next attempt: `检测到刚更新完成: v2.26.0-beta.1`,
followed by `更新检查完成: 最新版本=v2.26.0-beta.1, 有更新=false`. The retry
succeeds because by then the update is done. That is the whole of the
"fails once or twice, then heals itself" pattern.

The update channel is `beta`, which ships most days - v2.25.0-rc.1 on 08-21,
v2.26.0-beta.1 on 08-22 - so most days opened with a wasted attempt and a
failure alert.

Verified both directions on the same afternoon, one hour apart:

| | update pending | already current |
|---|---|---|
| monitor attached | 11:48:02 | 12:10:49 |
| outcome | **all 14 failed 16 s later** | **still running after 106 s** |

**An earlier reading of this page blamed MaaEnd's own window for stealing
focus.** The focus log does show a second MaaEnd window appearing seconds
before the failure, and that observation was correct - but it was the symptom.
That window is the restarted process. Reading a correlation off a focus log and
calling it a cause cost a day; the answer was in MaaEnd's own log the whole
time, in a line that says "just finished updating".

**The fix keeps auto-update on and moves it earlier.** `relay/ark_relay/preupdate.py`
runs MaaEnd once in the boot-to-queue gap, waits for its update check to
settle, and closes it, so the queue's launch finds nothing to update. Upstream
declined to address the focus behaviour (MaaEnd#4820: "always on top 友商都没做,
说明不是一个很好的方案"), so this is handled here or not at all.

**Do not leave the Endfield launcher window on the desktop.** The foreground
controller needs the game window unobstructed.

**MaaEnd's webhooks cannot carry content.** Structural, not a misconfiguration -
see [CONFIG.md](CONFIG.md).

## Copying the answer instead of the method

Spent most of an afternoon on 2026-08-22 failing at a task MAA does in seconds:
read two numbers out of the depot. The failures were all the same shape.

**Copied its coordinates, not its approach.** MAA's task files are full of
numbers, and taking them felt like learning. But its numbers only work inside
its method - screenshot, recognise what is actually on screen, then act. What
got written instead was click-sleep-click-sleep, which assumes each step landed.
One slow load desynchronised the rest and the run dragged the emulator's
launcher screen around until the game icon was gone.

**Rebuilt its eyes instead of using my own.** Time went into a template-matching
engine with OpenCV, to recognise game screens. MAA needs that because it is an
offline program that cannot see. I can look at a screenshot directly. The thing
worth taking from MAA was never its recogniser - it was its **decision table**:
what to do about each screen that might appear, and the fact that it lists all
of them rather than predicting a sequence.

**Fought the wrong layer.** Screen coordinates, window rects, a drag that would
not scroll, an overlay covering the button. Every one of those problems exists
only for something clicking at the desktop. MAA has never done that: it talks
ADB to the device, where there is no desktop, no window position and no overlay.
The fix was not a better mouse - it was to stop using the mouse.

The general form: **when a working tool does something easily, the transferable
part is how it decided, not what it typed.** Its constants encode its
constraints, and its constraints may not be mine - in this case it needs
resolution-independent coordinates and template matching, and I need neither.

## Inherited claims are the main source of wrong documentation here

A full audit of the nine retired Chinese documents was run on 2026-08-22
against the live machine: 1,848 lines, 341 candidate factual claims extracted
mechanically (paths, service and task names, config keys with values, version
numbers, booleans, timings), then checked one class at a time.

**What held up.** 14 of 16 Windows paths; all five scheduled tasks; both
services and their exact recovery policies (`sshd` reset=86400/5000 ms,
`ark-relay` reset=60/3000 ms); AUTO-MAS v5.3.1; the UTC+4 history clock in
`constants.py`; `WaitTime`'s `ge=60`; the emulator triple (ldplayer /
ldconsole.exe / Index 1000); the timeouts; the power settings. The
machine-facing core of those documents was sound.

**What did not.** Every failure was of one kind - a claim that was true once,
or guessed once, and then copied forward:

| Claim | Reality |
|---|---|
| "the Mi Home timers are not set" | they were, and had been for days |
| folder `MAA-v5.1.0-win-x64` = version 5.1.0 | v6.17.0-beta.5 |
| folder `MaaEnd-…-v1.6.5` = version 1.6.5 | v2.25.0-rc.1 |
| MAA's push switches "false on both profiles" | both true - it had been pushing all along |
| （2026-08-24 又犯了一次）"MAA 目录里四个开关都是 false，所以不是 MAA 发的" | 是 MAA 发的。查的是会被覆盖的副本，母本在 AUTO-MAS 的 `data/<uid>/Default/ConfigFile/` 下，那里是 `true`。同一个坑第二次，这次把校验补到了母本上 |
| the second MAA profile is "the owner's manual config" | an automation profile with `RunDirectly` + `PostActions: Shutdown` |
| `Notify.IfServerChan = true` | false |
| "everything touched was backed up first" | MaaEnd's config backup does not exist |

Two more were false alarms worth recording, because both nearly became
corrections *away* from the truth: `findstr "WaitTime"` appeared to show no
`ge=60` until it turned out there are two same-named fields and the first match
was the wrong one; and several Stage/Medicine/AfterAccomplish mismatches were
not errors at all but deliberate later changes. **Check the whole picture
before "fixing" a document - a single grep is a sample, not an answer.**

**The lesson that generalises.** None of these were caught by reading the
documents; all were caught by touching the machine for an unrelated reason.
Reading cannot find them, because a confident sentence reads the same whether
it is true or not. So: write claims in a form `check-docs.py` can verify, and
when that is impossible, date them. This audit converted the surviving
config claims into directives - the checker now verifies 81 facts against the
machine, up from 42.

## A directory name is not a version number

Both bots update themselves in place and keep the folder name they were
unpacked with. On 2026-08-22:

| Folder | Actually running |
|---|---|
| `MAA-v5.1.0-win-x64` | v6.17.0-beta.4 |
| `MaaEnd-win-x86_64-v1.6.5` | v2.25.0-rc.1 |

Both were quoted as versions in this documentation, one of them off by a whole
major release, and a version claimed from a path was already the reason an
upstream report went out wrong once. The window title in `focus-watch.log`
carries the real one for both; `resource/version.json` under MAA is the
*resource* date, not the program version.

## MAA

**Drop statistics are running totals - never sum them.** One round farms in
batches and MAA prints a block per batch:

```
TO-5 掉落统计:
龙门币 : 1440 (+1440)      <- total after batch 1
当前次数 : 10
TO-5 掉落统计:
龙门币 : 2448 (+1008)      <- total after batch 2, not this batch's gain
当前次数 : 7
```

The parser summed both blocks and reported **3888** against a true **2448**.
The last block *is* the answer; the `(+N)` is the delta. AUTO-MAS reads the last
block, so the two disagreed and exposed it.

**`当前次数` is the opposite** - `10` and `7` are per-batch counts and 17 is
correct (the log says "行动 1~10 次" then "行动 11~17 次"). Two different
semantics inside one block, easy to get wrong together.

Checked against a real run on 2026-08-21 (09:22, stage 1-7, two batches:
龙门币 720 then 1440). The parser's six drop figures match AUTO-MAS's own
`drop_statistics` exactly, and the run count comes out 20 for 10+10. AUTO-MAS
writing its own figure into the record is what makes this verifiable at all -
when the two disagree, the parser is wrong.

## GUI automation

**An SSH session cannot take a screenshot.** Session 0 isolation; there is no
desktop. Run the action script as a scheduled task in the interactive session
and use SSH only for `schtasks /run`.

**Clicks landing on the wrong window.** Two consecutive screenshots showed a
30-pixel cascade offset - meaning a new window had appeared in between. The
culprit was `schtasks /run` opening a **visible** PowerShell console that took
focus and covered the left half of the screen. **The automation hid its own
target.** Fix: `-WindowStyle Hidden` on the task.

**Protocol space only failed while someone was connected over ToDesk.** The
`on_error` screenshot shows ToDesk's controlled-side session panel covering the
bottom-right from x≈1024, exactly over the button. MaaEnd's own log says it:
foreground controller, game window must stay frontmost and unobstructed. ToDesk
has no setting to hide that panel (all 7 tabs checked). **Do not watch over
ToDesk while tasks run** - SSH screenshots create no overlay at all. TeamViewer's
main window sits on the desktop permanently without anyone connecting, which is
the larger risk of the two.

## Notifications

**One broken channel alarmed all night and kept the machine on.** `Notifier.send()`
returned a non-empty error list if *any* channel raised, and the engine read
non-empty as "not delivered":

```python
errors = self.notifier.send(title, body)
if errors:
    return              # keep it on disk, resend next round
```

With WeCom broken and Server酱 fine, the message **had** been delivered, but
nothing was ever settled: the same alarm resent every 30s, `mark_report_sent` was
never called so the daily report resent all night, and `_maybe_shutdown` requires
an empty pending list plus a sent report - so **the machine never powered off
again**. Both machines sit behind dial-up home lines with changing public IPs,
and a WeCom self-built app only accepts calls from its trusted-IP list
(`errcode=60020`), so the day the IP changed, all three happened at once.

**Fix: one channel delivering means delivered.** `send()` reports an error only
when *every* channel failed. A dead channel is raised as its own separate
incident over whatever still works, once per process per channel - the machine
cycles twice a day, so an unfixed channel keeps reminding.

**One TLS handshake timeout dropped an alarm permanently.** Japan → `sctapi.ftqq.com`
occasionally times out during the handshake while the retry answers in a second.
Alarms are one-shot and nothing resends them. Transport-level retry added: 3
attempts, backoff from 1.5s, **for transport failures only**. An HTTP status is
the server answering - a 403 stays 403 however often you ask, and `errcode=60020`
likewise; those raise immediately so the caller can switch endpoint or channel
instead of waiting out a backoff.

Also established: Server酱³'s uid-derived `{uid}.push.ft07.com` endpoint returns
403 for this key permanently - it was never a valid fallback. Only
`sctapi.ftqq.com` works.

**`sctp...` and `SCT...` are different products.** `sctp` is Server酱³ (app
first); `SCT` is Turbo, which reaches the WeChat service account.

**Server酱 returning `code:0` does not mean it arrived.** The channel was
configured as PushDeer rather than the WeChat service account. A return code only
says the API call succeeded.

**WeCom `errcode=44004 empty content`** - the Chinese test payload was destroyed
by the GBK pipe. Verify a channel with pure ASCII first.

**WeCom `errcode=60020`** - caller IP not in the trusted list. Once, this cost
hours because one digit of the IP had been typed wrong. Check it digit by digit.

**The daily report's trigger condition was wrong and could never fire.** The old
test was "the *last run's finish time* ≥ ARK_LAST_RUN_AFTER":

```python
last_finished = max(finish for e in entries)
cutoff = last_finished.replace(hour=21, minute=30)
if last_finished < cutoff:
    return          # always true
```

Queues finishing at 21:52 were fine, but a queue moved to 21:25 and finishing at
21:28 makes the return **always** hit: the report can never be sent, and since
`_maybe_shutdown` requires a sent report, the machine never powers off. Worse,
`_maybe_daily_report` and `_maybe_shutdown` each computed their own cutoff from
different starting points.

**Fix:** one `_report_cutoff()` taken from the last queue time in AUTO-MAS's own
config (falling back to `ARK_LAST_RUN_AFTER` only if unreadable), and the test
became "the clock is past the cutoff and no script is running". Now moving a
queue in AUTO-MAS moves the report and the shutdown with it.

## Environment

**`Add-WindowsCapability` could not install OpenSSH** - corrupt component store.
The standalone MSI worked first try.

**Public key login kept being refused.** Accounts in the Administrators group do
not read the user's own directory; the key must be in
`C:\ProgramData\ssh\administrators_authorized_keys`. Note also that SSH key login
does not require knowing or changing anyone's password.

**Antivirus deleted sshd.** Huorong quarantined `sshd-session.exe` as
`Worm/DTStealer.B`. The symptom is confusing: the TCP port connects, no banner
appears, the connection drops, and `Restart-Service sshd` hangs in StartPending.
**This cannot be repaired remotely** - fixing SSH requires SSH. Someone has to be
at the machine.

## Dead ends - do not retry

**Tailscale on a Windows box without administrator rights is impossible.**
`--tun=userspace-networking` gets past the network driver, but tailscaled forces
the control pipe's owner to the Administrators group SID, which a standard user
cannot assign:

```
namedpipe.Listen: open \\.\pipe\ts-human:
  This security ID may not be assigned as the owner of this object.
```

Moving `--socket` to an unprotected path is refused the same way. `cloudflared`
does run as a standard user (verified, version 2026.8.2), but it is only a
tunnel - it needs a local service to forward to, and installing sshd needs
administrator again. So "reach that machine" remains unsolved.

**The relay's server mode.** Retired 2026-08-20. Every capability a cloud server
had now has a serverless implementation, and the machine cannot upload to GitHub
anyway. Do not rebuild it: the reasoning and the replacements are in
[OPERATIONS.md](OPERATIONS.md) under "Update channels" and "Off-machine
supervision".

## Reading a nested field at the wrong depth looks exactly like stale data

On 2026-08-22 the event cache `cache/gui/StageActivityV2.json` was declared
stale and its countdown declared untrustworthy. It was neither. The probe read
`node["UtcExpireTime"]`, but the field lives at `node["Activity"]["UtcExpireTime"]`
- which is where `plan.activity_countdown` had been reading it all along. Every
event came back `None`, and `None` was reported as "the cache never updated".

Two checks would have caught it, and both are cheap:

1. **The file's mtime.** It was written that same day at 15:12. A cache with a
   fresh mtime and empty fields is a parser bug, not a stale cache.
2. **Read it the way the consumer reads it.** `plan.py` already had the correct
   path. Writing a second, shallower reader invented a disagreement that did
   not exist.

The general form: when a probe says "everything is empty", suspect the probe
before the data. Absent values are the most common shape of a path mistake.

## A watchdog cannot tell "installing" from "hung" - so give it a clock

The relay revives AUTO-MAS when its Python backend is missing, and to do that
it must first `taskkill /F` the Electron shell: the shell outlives its own
backend (the exact state the machine was once found in), and the scheduled task
counts as running while that shell is alive, so `schtasks /run` would start
nothing.

On 2026-08-22 an AUTO-MAS update ran its first-time environment wizard -
Python, pip, git, then cloning the backend. Throughout all of that there is
legitimately no backend. The revival killed the wizard twice, mid-clone, at
23:12 and 23:16. The wizard then reported **"所有镜像源都尝试失败"**.

Every part of that message was misleading, and chasing it wasted the next
half hour:

- All six mirrors were **reachable** from that machine - CNB 417 ms, gitee
  339 ms, both HTTP 200. Only GitHub direct and ghfast timed out.
- Both working mirrors **carried the branch** it wanted, `release/v5.4.0-beta.7`.
- The clone had in fact **already succeeded**: HEAD sat on `5e2c2ba`, the exact
  commit of that branch, tracking origin.

The update completed by itself the moment the relay was stopped. Nothing else
changed.

Two lessons, and the second is the general one:

1. **Never force-kill a window on a single instantaneous signal.** "Backend
   missing" is true both when something is broken and when something is being
   set up. Only elapsed time separates them, so the guard now waits 15 minutes
   while a shell is alive, vetoes outright while an installer process exists,
   and still revives instantly when there is no shell to kill.
2. **An error message names the symptom, not the cause.** "All mirrors failed"
   was the wizard's honest report of its own experience; it had no way to know
   it was being shot. Test the thing it blames - the mirrors, from that machine
   - before believing it.

While chasing this I also asserted that the revival had no backoff, from
reading `AUTOMAS_CHECK_SECONDS = 120`. That constant is the degraded path used
only when the WMI subscription fails. The real path doubles `revive_wait` from
180 s to a 1800 s cap, exactly as its alert message claims. Reading one
constant is not reading the code path.

## Fixing a crash re-arms everything the crash was suppressing

2026-08-23. Two bugs had been silently disabling the relay: `Engine._boot_time`
was called from three places and never defined, and AUTO-MAS v5.4.0-beta.7
renamed its history records from `05-00-01.json` to `MAA-05-00-00.json`, which
the filename parser rejected. Between them: no records ingested, no ledger, no
report, no power-off, and a missed-run alarm for a queue that had succeeded.

Both were fixed and deployed. The relay then did exactly what it is supposed to
do - ingested the day's runs, sent the report, found the day's work complete,
and **powered the machine off**, twenty minutes after the operator had said to
keep it up. Debug mode had expired at 08:30 and nothing else was holding it.

The mistake was not the fix. It was not seeing that **a suppressed behaviour is
still configured**: the shutdown had not been turned off, only broken. Restoring
the code restored it. Before repairing anything that has been failing quietly,
ask what it will start doing again the moment it works, and gate that first.

Two smaller lessons from the same morning:

- **A service that catches per-tick exceptions hides this class of bug.** The
  relay stayed up, logged an AttributeError every tick, and did none of the
  work that followed. `relay/tests/test_self_attrs.py` now checks statically
  that every `self.x` in the package exists, which fails on exactly this.
- **Upstream renames arrive as silence.** Nothing errored when the record
  filenames changed - `parse_record` returned None and the records simply
  vanished. A parser that can reject input needs a test for the shape it
  rejects, not only the shape it accepts.

## Mojibake is not a display problem - it is where hallucinations come from

2026-08-23. A run record was read with a remote command and the drop names came
back as broken bytes. Rather than stopping, they were reported as 家具零件 and
沿途的点滴 - names that look plausible and were invented. The real drops, from
the same file read correctly, are 艺人见面抽选券 and 闲言碎语.

**Reading damaged text and reporting a guess is worse than reporting nothing.**
If the bytes are broken, the only correct next action is to fix how they are
being read.

Three separate causes, each of which alone produces mojibake:

1. **Windows PowerShell 5.1 reads files as ANSI.** `Get-Content some.json` on a
   UTF-8 file destroys it **on the machine**, before anything is transmitted.
   Use `-Encoding UTF8`, or better, do not print files at all.
2. **The console is codepage 936.** `cmd /c` interprets a UTF-8 command line as
   GBK. `chcp 65001` first fixes it.
3. **PowerShell 5.1 reads a `.ps1` as ANSI unless it opens with a UTF-8 BOM.**
   A script written without those three bytes has its own Chinese destroyed
   before it runs.

And one trap that looks like a fix: **piping everything through
`iconv -f GBK`**. Output that was already UTF-8 is then decoded twice and
shredded, so it works sometimes and silently corrupts the rest - which is worse
than a consistent failure.

The root fix for the first cause is **PowerShell 7**, which is UTF-8 by
default: `Get-Content file.json -Raw` on a UTF-8 file is simply correct there,
with no `-Encoding` and nothing to remember. Windows PowerShell 5.1 cannot be
changed - like `cmd.exe`, it is a frozen OS component kept bug-compatible on
purpose - so the answer is to stop using it, not to work around it.

`scripts/mac/winrun.sh` encodes all of this:

- `--get <path>` copies a file as bytes and decodes it here. **File contents
  always go through this**, never through a remote command.
- command output is written to a UTF-8 file on the machine and copied back, so
  no console sits in the path.
- the generated `.ps1` carries a BOM and `cmd` invocations are prefixed with
  `chcp 65001`, so Chinese works on the command line too.
- it runs under `pwsh` 7 when present, falling back to 5.1 only if it is not.
- it pins `[Console]::OutputEncoding` and `PYTHONUTF8` so a child process that
  writes UTF-8 - python, curl, git - survives being captured.
- **it deletes the previous output file before every run.** Without that, a
  command that fails to produce output leaves the last run's file behind, and
  reading that as the current result is the same failure mode in a new costume:
  stale data reported as fresh.



## Five layers of quoting, and none of them are on your side

A command typed inline for the game machine passes through bash, ssh,
PowerShell, sometimes cmd, and finally Python. Every one of them gets a turn at
the quotes.

The failure that keeps recurring: PowerShell escapes a single quote by doubling
it (`''`), but writing that inside a bash single-quoted string ends the bash
string at the first quote. The result is not an error - it is a mangled command
that runs and produces something plausible. On 2026-08-24 this burned three
round trips in one session, twice producing `scp: winrun.out: No such file`
because the remote command never ran at all.

`set FOO=1 && cmd` has the same flavour of trap: cmd takes the trailing space
into the value, so `PYTHONUTF8` becomes `"1 "` and Python refuses to start with
`invalid PYTHONUTF8 environment variable value`. Write `set FOO=1&& cmd`.

**The fix is not more careful quoting.** Put the script in a file and ship it:

```bash
scripts/mac/winrun.sh --py scripts/whatever.py arg1 arg2
```

`--py` copies the file, runs it with the machine's own Python 3.14 under
`PYTHONUTF8=1`, and brings the output back as bytes through the same UTF-8-safe
path as the other modes. No layer parses the script, so no layer can corrupt
it. Verified with a line containing a single quote, a double quote and a
backtick, plus Chinese, all of which arrived intact.

Use `--ps` for genuine one-liners. Anything with a quote in it, or longer than
one line, goes in a file.


## MAA 基建换班每天挂一次：不是分辨率，是基建视图没缩放到位

2026-08-28 用户问「中继通知我有四项失败……是不是我们这边设置没弄好」。
逐项查完的结论：

### 1. MAA「基建换班」——**不是我们的设置**，慢性偶发，会复现

`asst.log` 的因果链：

```
13:18:04  InfrastInfoTask | zoom gesture sent
13:18:06  no facility matched, attempt 1
13:18:08  no facility matched, attempt 2
13:18:10  no facility matched, attempt 3
13:18:11  Save image D:\ark\maa\debug\infrast\facility_layout\...raw.png
13:18:11  ERR InfrastInfoTask | facility layout recognition failed after 3 attempts
```

**MAA 每次失败都会存一张现场图**，那个目录就是完整病历：

    D:\ark\maa\debug\infrast\facility_layout\
      08-26 15:24:41 / 08-26 21:35:36 / 08-27 21:35:18 / 08-28 13:18:11   共 4 次 / 3 天

08-27 与 08-28 两张图**症状完全相同**：基建视图没缩放到位，
右边一列（加工站 / 办公室 / 训练室 / 会客室）卡在画面右缘外，
`InfrastInfoTask` 认不出完整布局。

**排除了分辨率**：模拟器 LDPlayer9 `advancedSettings.resolution = 1600×900`、
`resolutionDpi = 240`、16:9，高于 MAA 要求的 1280×720 下限；
`asst.log` 里 MAA 全程用 `1.25` 的缩放因子（1600÷1280）正常处理，
**没有任何分辨率相关告警**。

**影响**：AUTO-MAS 看到「部分任务执行失败」就重跑一轮（`RunTimesLimit=3`），
第二轮基本都成功。代价是每次多跑约 11 分钟，不丢任务。

**能不能修**：MAA 侧的识别问题，我们这边没有对应开关。
`基建换班` 的 `CustomFileType=user_defined` 但 `Filename=""`、`PlanSelect=-1`，
等于没启用自定义排班——**没有验证过启用它能否绕过布局识别，别当成结论。**

### 2 & 3. 终末地「选剑演武」×2 ——**是我们的设置**，已修

见 [AUTOMAS.md](AUTOMAS.md#选剑演武游戏里成功maaend报失败已关掉)。
我当天才加的任务，识别不可靠，失败时还把角色卡在挑战里连累基质刷取。已关闭。

### 4. 鸣潮「游戏更新成功，即将重启任务」——误报

不是故障，是鸣潮客户端更新后 OK-WW 正常重启任务的流程，紧接着就 DONE。

### 顺带：这些历史怎么查

```
mas-api.py get /api/history/search '{"mode":"DAILY","start_date":"...","end_date":"..."}'
```
返回每个脚本每轮的 `status` 和 `error_info`。**但它只记「部分任务执行失败」，
不记是哪个任务**——具体任务名要去 MXU 的运行日志或 MAA 的 `gui.log` 找，
失败原因要去 MaaCore 的 `asst.log`（`gui.log` 只说「任务出错」不说为什么）。

## 部署中继前先看预更新在不在跑（2026-08-29）

`deploy-relay.sh` 停服务时卡在 `STOP_PENDING`，脚本判失败并提示手动 `sc start`。
真因不在部署脚本：中继 00:35:37 正在下载 AUTO-MAS v5.4.0 → v5.5.0-beta.1，
下载线程没结束，服务就停不干净。我把服务进程强杀了（`taskkill /PID <pid> /T /F`），
服务恢复策略自动把它拉了回来，`sc start` 随后报 1056「已在运行」——那是正常的。

**代价**：那次 AUTO-MAS 下载被打断。事后核对 `main.py`、`QueueConfig.json`、
`ScriptConfig.json` 都在，没有半截下载目录，4 个 AUTO-MAS 进程正常——这次没坏，
但纯属运气。

**规矩**：部署前先看 `relay.log` 末尾有没有「预更新：…开始下载」而没有对应的完成行；
有就等它结束再部署。

## 补丁机制没法更新自己贴过的补丁（2026-08-29，已修）

`okww_patch._apply_nest` 原本只认「上游原版」和「当前最新版」两个哈希，
机器上是我们**上一版**补丁时两边都不像，被判成「有人手改过」而拒绝覆盖。
`_NEST_KNOWN_OURS` 那张表能救，但要求**每次改补丁都手动补一条哈希**——我忘了。

**部署脚本照常显示成功**，只在服务启动日志里留了一行 warning。

已改成认「我方标记」`Only Farm These Nests`（我们自己造的配置常量，
上游源码里绝不会出现），见到就照常覆盖。测试见
`relay/tests/test_okww_patch_refresh.py`。**靠人记的步骤迟早会漏，标记不会。**

## AUTO-MAS 更新不上不是 CDK 的问题（2026-08-29，已修）

从 08-27 起每次开机都打「预更新：AUTO-MAS 有更新，开始下载」，然后没有下文，
版本卡在 v5.4.0。日志里没有任何失败行，看着像网慢。

真因是两件事凑一起：

* `app/services/update.py:178-184` 把更新检查结果**缓存四小时**；
* MirrorChyan 的下载地址是**一次性令牌**，随检查响应带回来存进
  `mirror_chyan_download_url`，下载时直接拿它用。

走缓存 = 拿早就作废的令牌去下 → 三次重试全 404 → `UpdatePack_*.zip` 一个字节
都不落地 → 中继在 `_wait_for_package` 干等 600 秒超时。

**CDK 一直是好的**：版本检查从头到尾都成功（能查到 v5.5.0-beta.1）。

修法：`/api/update/check` 带 `if_force: True`（`UpdateCheckIn` 本来就有这个字段）。
机器上实测：不强制 → 404；强制 → 换到新令牌、状态码 200、**9.93 秒下完 102.8MB**。
所以 600 秒预算从来不是瓶颈。测试见 `relay/tests/test_preupdate_mas_force.py`。

**教训**：「开始 X」之后既没有成功也没有失败行，别当成「还在进行中」。
去被调用方的日志里看它到底做了什么。

## WMI 进程订阅死了不会自己回来（2026-08-29 发现，未修）

`relay/service.py` 用 `Win32_ProcessStartTrace` 订阅 python.exe 启动，
好让 AUTO-MAS 一起来就立刻挂上句柄。这个订阅会周期性地被 RPC 打断：

```
pywintypes.com_error: (-2147352567, '发生意外。',
  (0, 'SWbemEventSource', '远程过程调用失败。 ', None, 0, -2147023170), None)
```

**兜底是有的**：`_start_process_watch` 的 run() 捕获异常、记日志、
把 `alive["ok"]` 翻成 False、唤醒主循环改用 `AUTOMAS_CHECK_SECONDS = 120`
的定时活性检查。所以不是静默失败。

**但缺的是重订阅。** `_start_process_watch` 只在第 635 行被调一次，
线程一死就**再也不会重来**，剩下整个开机周期都停在 120 秒轮询上。

代价：AUTO-MAS 启动后，中继最晚要 120 秒才挂上句柄，而不是内核事件的「立刻」。

**规模**：`relay.log` 里 08-24 到 08-29 共 24 次，约每天 4 次。
机器一天只开两次机（08:45 / 21:20），所以中继**大部分运行时间都在降级模式**。

**该怎么修**：run() 的 except 分支不要直接退出线程，改成退避重试
（比如 5s → 10s → …封顶 60s）重新建订阅，成功后把 `alive["ok"]` 翻回 True
并记一行日志。注意别在队列运行期间部署——部署会重启服务。

### 顺带：待办下发那条路今晚又失败了

```
08-29 21:21:38 WARNING ark.inbox  取不到待办文件
  (https://raw.githubusercontent.com/herclyon1/maa/main/queue/config.json):
  <urlopen error _ssl.c:1064: The handshake operation timed out>
```

同一次开机里 `ark.update` 取 manifest 也失败了一次（WinError 10054），
但它**换了镜像重试成功**（拿到清单只是比本机旧，所以没更新）。
`ark.inbox` 这条没有看到重试。这就是之前记下的「自更新和待办下发不可靠」。
