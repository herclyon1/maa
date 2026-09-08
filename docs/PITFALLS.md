# Pitfalls

> The incident-by-incident accounts moved out of the code comments live in
> [CODE-HISTORY.md](CODE-HISTORY.md), indexed by "file:function".

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
| Fleet Monitor took tailscaled's `Online` to mean "the machine is up" | That is the control plane's opinion, not whether it can be reached. Losing power does not log the node out: on 09-03 it still reported Online=True four hours after shutdown. Now every machine that claims to be online must actually answer a disco ping before it is painted green |
| Changing the 终末地 / 鸣潮 settings from the phone page acknowledged the press, but the scripts ran unchanged | 「快速配置」 is off for both of those scripts, so AUTO-MAS returns immediately and never pushes the MAS user config down to them (`app/task/Okww/AutoProxy.py:320`, `MaaEnd/AutoProxy.py:537`). What actually takes effect is each one's own master config. **明日方舟 has no such switch**: its stage and medicine are written into gui.new.json on every dispatch, so going through MAS is the right route for it |
| Fleet Monitor raised two up/down notifications a day (several in a row at boot) | Scheduled power-on and post-run shutdown are this machine's normal day; nobody needs to be told. At the moment of boot, "reachable but not answering yet" makes the state flap, and the notifications flap with it. Removed entirely - the state is the Dock icon, and a real problem is reported through the relay's own channel |
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
| (made again on 2026-08-24) "all four switches in the MAA directory are false, so MAA is not the sender" | MAA was the sender. What had been checked was the copy that gets overwritten; the master lives under AUTO-MAS at `data/<uid>/Default/ConfigFile/`, and there it is `true`. Second time in the same hole - this time the check was extended to the master |
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


## MAA's base shift change fails once a day: not the resolution, the base view not being zoomed out far enough

On 2026-08-28 the user asked: 「中继通知我有四项失败……是不是我们这边设置没弄好」.
Going through them one at a time:

### 1. MAA 「基建换班」 - **not our settings**, chronic, intermittent, reproducible

The causal chain in `asst.log`:

```
13:18:04  InfrastInfoTask | zoom gesture sent
13:18:06  no facility matched, attempt 1
13:18:08  no facility matched, attempt 2
13:18:10  no facility matched, attempt 3
13:18:11  Save image D:\ark\maa\debug\infrast\facility_layout\...raw.png
13:18:11  ERR InfrastInfoTask | facility layout recognition failed after 3 attempts
```

**MAA saves a picture of the scene on every failure**, so that directory is the
complete case history:

    D:\ark\maa\debug\infrast\facility_layout\
      08-26 15:24:41 / 08-26 21:35:36 / 08-27 21:35:18 / 08-28 13:18:11   4 times over 3 days

The 08-27 and 08-28 images show **exactly the same symptom**: the base view is
not zoomed out far enough, so the right-hand column (加工站 / 办公室 / 训练室 /
会客室) sits outside the right edge of the frame and `InfrastInfoTask` cannot
recognise a complete layout.

**Resolution is ruled out**: the LDPlayer9 emulator has
`advancedSettings.resolution = 1600×900`, `resolutionDpi = 240`, 16:9 - above
MAA's 1280×720 floor; `asst.log` shows MAA handling everything normally with a
scale factor of `1.25` (1600÷1280), and **there is no resolution-related warning
anywhere**.

**Impact**: AUTO-MAS sees 「部分任务执行失败」 and runs the round again
(`RunTimesLimit=3`); the second round almost always succeeds. The cost is about
11 extra minutes per occurrence, with no task lost.

**Can it be fixed**: it is a recognition problem on MAA's side and there is no
corresponding switch here. 「基建换班」 has `CustomFileType=user_defined` but
`Filename=""` and `PlanSelect=-1`, i.e. a custom shift plan is not actually
enabled - **whether enabling it would bypass the layout recognition has not been
tested, so do not treat that as a conclusion.**

### 2 & 3. 终末地 「选剑演武」 ×2 - **this one is our settings**, fixed

See [AUTOMAS.md](AUTOMAS.md#选剑演武游戏里成功maaend报失败已关掉).
I had added the task the same day; its recognition is unreliable, and on failure
it also left the character stuck in the challenge, which dragged down essence
farming. Now disabled.

### 4. 鸣潮 「游戏更新成功，即将重启任务」 - a false alarm

Not a fault: it is OK-WW's normal task-restart flow after the 鸣潮 client
updates, and DONE follows immediately after.

### Incidentally: how to look this history up

```
mas-api.py get /api/history/search '{"mode":"DAILY","start_date":"...","end_date":"..."}'
```
returns `status` and `error_info` for every round of every script. **But it only
records 「部分任务执行失败」, not which task it was** - the task name has to come
from MXU's run log or MAA's `gui.log`, and the reason for the failure from
MaaCore's `asst.log` (`gui.log` only says 「任务出错」, never why).

## Check whether the pre-update is running before deploying the relay (2026-08-29)

`deploy-relay.sh` hung at `STOP_PENDING` while stopping the service, declared
failure and asked for a manual `sc start`. The real cause was not in the deploy
script: at 00:35:37 the relay was downloading AUTO-MAS v5.4.0 → v5.5.0-beta.1,
and with the download thread still alive the service could not stop cleanly. I
force-killed the service process (`taskkill /PID <pid> /T /F`), the service
recovery policy brought it straight back, and the subsequent `sc start` reported
1056 「已在运行」 - which is normal.

**The cost**: that AUTO-MAS download was interrupted. Checking afterwards,
`main.py`, `QueueConfig.json` and `ScriptConfig.json` were all present, there was
no half-written download directory, and all 4 AUTO-MAS processes were healthy -
nothing broke this time, but purely by luck.

**Rule**: before deploying, look at the end of `relay.log` for a
「预更新：…开始下载」 with no matching completion line; if there is one, wait for
it to finish before deploying.

## The patch mechanism could not update a patch it had applied itself (2026-08-29, fixed)

`okww_patch._apply_nest` originally recognised only two hashes, "upstream
original" and "current latest". On the machine sat **our previous** patch, which
matched neither, so it was judged "somebody edited this by hand" and the
overwrite was refused. The `_NEST_KNOWN_OURS` table can rescue that case, but it
requires **manually adding a hash every time the patch changes** - and I forgot.

**The deploy script reported success as usual**, leaving nothing but one warning
line in the service startup log.

It now recognises a marker of our own, `Only Farm These Nests` (a config constant
we invented, which will never appear in upstream source): when it is there, the
overwrite proceeds as normal. Tests in
`relay/tests/test_okww_patch_refresh.py`. **A step that relies on someone
remembering will eventually be skipped; a marker will not.**

## AUTO-MAS failing to update was not a CDK problem (2026-08-29, fixed)

From 08-27 on, every boot logged 「预更新：AUTO-MAS 有更新，开始下载」 and then
nothing further, with the version stuck at v5.4.0. There was no failure line in
the log at all; it looked like a slow network.

The real cause was two things together:

* `app/services/update.py:178-184` **caches the update-check result for four
  hours**;
* MirrorChyan's download address is a **single-use token**, returned with the
  check response, stored in `mirror_chyan_download_url` and used directly at
  download time.

Hitting the cache = downloading with a token that expired long ago → all three
retries 404 → not a single byte of `UpdatePack_*.zip` lands → the relay waits out
its 600-second timeout in `_wait_for_package`.

**The CDK was fine all along**: the version check succeeded from start to finish
(it could see v5.5.0-beta.1).

The fix: send `/api/update/check` with `if_force: True` (`UpdateCheckIn` already
has the field). Measured on the machine: without forcing → 404; with forcing → a
fresh token, status 200, **102.8MB downloaded in 9.93 seconds**. So the
600-second budget was never the bottleneck. Tests in
`relay/tests/test_preupdate_mas_force.py`.

**The lesson**: when "X started" is followed by neither a success nor a failure
line, do not read it as "still in progress". Go to the callee's log and see what
it actually did.

## A dead WMI process subscription does not come back on its own (found 2026-08-29, fixed 2026-08-30)

`relay/service.py` subscribes to python.exe starts with
`Win32_ProcessStartTrace` so that a handle can be attached the moment AUTO-MAS
comes up. That subscription is periodically broken by RPC:

```
pywintypes.com_error: (-2147352567, '发生意外。',
  (0, 'SWbemEventSource', '远程过程调用失败。 ', None, 0, -2147023170), None)
```

**There was a fallback**: run() in `_start_process_watch` catches the exception,
logs it, flips `alive["ok"]` to False and wakes the main loop onto the timed
liveness check at `AUTOMAS_CHECK_SECONDS = 120`. So it was not a silent failure.

**What was missing was re-subscribing**: `_start_process_watch` was called only
once, so once the thread died it never came back and the rest of that entire
power-on cycle stayed on the 120-second poll. The cost is that the relay attaches
its handle up to 120 seconds after AUTO-MAS starts, instead of the "immediately"
of a kernel event.

**Scale**: 24 occurrences in `relay.log` between 08-24 and 08-29, about 4 a day.
The machine only powers on twice a day (08:45 / 21:20), so the relay spent **most
of its running time in degraded mode**.

**Fixed (2026-08-30)**: run() in `service._start_process_watch` re-subscribes
with backoff when it breaks (starting at 5 seconds, doubling, capped at 60), and
on recovery flips `alive["ok"]` back to True and logs a line. The full story is
under "service.py:run" in `docs/CODE-HISTORY.md`.
(No line number here - during the 2026-09-08 review that line number had drifted
by 355 lines and pointed at a different function. Code references in the docs use
function names.)

### Incidentally: the todo-delivery path failed again that night

```
08-29 21:21:38 WARNING ark.inbox  取不到待办文件
  (https://raw.githubusercontent.com/herclyon1/maa/main/queue/config.json):
  <urlopen error _ssl.c:1064: The handshake operation timed out>
```

In the same power-on, `ark.selfupdate` (then called `ark.update`) also failed
once fetching the manifest (WinError 10054), but it **retried against a different
mirror and succeeded** (the manifest it got was merely older than the local one,
so nothing was updated). No retry is visible for `ark.inbox`. This is exactly the
previously recorded "self-update and todo delivery are unreliable".

## A local variable with a module's name breaks the whole function, and 61 green tests never noticed (2026-09-06)

`queues.apply` and `commands._run_now` both imported the `names` module and
then, further down, did `names = []`. Python treats a name assigned anywhere in
a function as local for the *entire* function, so the first line -
`names.canonical(name)` - raised `UnboundLocalError` on every call from
2026-09-02 (when `names.py` was added) to 09-06. Skip-queue, the inbox's queue
switch and the phone's "run now" were all dead for four days.

Why nothing caught it: no test called either function, and the home-grown
`test_undefined_names.py` only asks "was this name ever bound in scope?" -
which it was. The static fact that matters is *bound after being read*, which
is pyflakes' F823 and takes one line to report.

Now enforced: `lint-repo.sh` item 9 runs pyflakes over `relay/` and `scripts/`
(zero reports allowed) and compiles everything with the machine's Python 3.14
with `SyntaxWarning` as an error - that caught an invalid `\d` escape the local
3.9 never mentioned. `guardcheck.sh` feeds both gates a known-bad sample.

## One stage of `tick()` raising took the report and the shutdown with it (2026-09-04, fixed 09-06)

`tick()` called its clock-driven stages in sequence with no per-stage guard.
An `ImportError` in the "tomorrow's plan" stage aborted the tick before the
daily report and `_maybe_shutdown` ran, every tick, all morning. Each stage
now runs inside its own `try` and a failure is logged with its name; the
source fetch is guarded the same way. `test_tick_isolation.py` raises in one
stage and asserts the later ones still run.
