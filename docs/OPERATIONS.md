# Operations

> **When something here is unclear, or an attempt fails: read MAA's own
> documentation first. Do not start experimenting.**
>
> MAA has solved every problem this system has, and written it down.
> [Its manual](https://github.com/MaaAssistantArknights/MaaAssistantArknights/tree/dev-v2/docs/zh-cn/manual)
> covers connection, emulators, the depot tool and the rest;
> `resource/tasks/tasks.json` and `src/MaaCore/` hold the behaviour itself.
> On 2026-08-22 an evening went into discovering by trial that LDPlayer's
> instance 1000 answers at `emulator-7554`. Its connection guide links the
> vendor page that states the rule outright: device port = 5554 + index * 2.
> Two page loads against several hours.


How to do things to the running system. Facts only; if a line cannot be checked
against the machine or the code, it does not belong here.

`scripts/mac/check-docs.py` verifies the checkable claims on this page and its
siblings - paths, the service, the scheduled tasks, config values - against the
live machine. Run it after any change to the system or to these docs, and
believe it over this page.

Reviewed 2026-08-21. Claims carried over from older documents have been wrong
before: "the Mi Home timers are not set" survived here for six days while the
morning round ran every one of them. Anything inherited rather than checked is
a candidate for the same failure.

## Map

```
Japan (UTC+9)                          China (UTC+8, "server time")
  control Mac  ── Tailscale + SSH ──▶  Windows 11 game machine, host "INS"
  control only                          awake ~3h/day, off the rest
       │                                     ▲
       └── push to GitHub ──▶ repo ──────────┘  machine pulls at every boot
```

The Mac is on **no** automated path. Everything that must happen while the Mac
is closed happens either on the game machine or in GitHub Actions.

| Host | Address | Role |
|---|---|---|
| Game machine | Tailscale `$ARK_HOST`, hostname `INS` | runs AUTO-MAS + MAA + MaaEnd + the relay |
| Mac | Tailscale, Tokyo | control; not depended on |
| HP server | Osaka; cloudflared tunnel + sshd on :2222 + RustDesk | **unused by this system** since the relay's server mode was retired. Its credentials are kept outside this repository |

`ssh Administrator@$ARK_HOST` over Tailscale. No port forwarding. Public key
must live in `C:\ProgramData\ssh\administrators_authorized_keys` - for accounts
in the Administrators group, sshd does not read the user's own directory.

## Runtimes: independent, not borrowed

Both machines run their own Python now, and the game machine has PowerShell 7.

| | Was | Is | Why |
|---|---|---|---|
| Game machine, relay | AUTO-MAS's embedded `environment\python\python.exe` | `C:\Program Files\Python314\python.exe` | **A watchdog must not depend on the runtime of the program it watches.** AUTO-MAS moving, replacing or breaking its bundled interpreter would take the relay down with it - and the relay exists precisely for when AUTO-MAS is in trouble |
| Game machine, shell | Windows PowerShell 5.1 only | + `pwsh` 7.6.5 | 5.1 reads files as ANSI and cannot be changed; 7 is UTF-8 by default |
| This Mac | Apple's Python 3.9 (frozen, deprecated) | `~/.local/bin/python3.14` via `uv` | 3.9 cannot run modern syntax; Apple's copy is an OS component and must not be replaced |

Bundling a runtime inside an application is for making *that application* easy
to deploy. Borrowing it for something else inherits every one of its upgrades
as a risk.

### Re-registering the relay service on a new interpreter

```bash
scripts/mac/winrun.sh 'net stop ark-relay'
scripts/mac/winrun.sh --ps 'Set-Location C:\ProgramData\ark-relay; & "C:\Program Files\Python314\python.exe" service.py --startup auto update'
scripts/mac/winrun.sh 'net start ark-relay'
```

`update` re-points the service at whichever interpreter runs it, and is
reversible by running the same command with the other one. Install `pywin32`
first (`pip install pywin32 -i https://pypi.tuna.tsinghua.edu.cn/simple` - the
Tsinghua mirror, PyPI direct is slow from that machine) and confirm every relay
module imports under the new interpreter **before** touching the service.

### Downloading anything onto that machine

- **Use `curl.exe`, not `Invoke-WebRequest`.** Measured 2026-08-23 on the same
  file and mirror: PowerShell managed 19 MB in 24 minutes, curl did 108 MB in
  85 seconds. Its progress rendering is the difference, not the network.
- **GitHub release assets need a mirror.** `github.com` times out; `ghfast.top`
  served at 1.26 MB/s. `gh-proxy.com` answers HEAD but stalls on the body.
  python.org and the Tsinghua PyPI mirror are both reachable directly.
- **A stalled download holds its output file open.** curl then fails with
  `(23) Failed writing received data to disk` and `del` silently does nothing.
  Kill the old process before retrying, or the retry cannot succeed.

## Paths on the game machine

The three programs live under `D:\ark\` with names that carry no version:

```
D:\ark\automas\   D:\ark\maa\   D:\ark\maaend\
```

**Renamed 2026-08-24, because the old names lied.** `MAA-v5.1.0-win-x64` held
v6.17.0; `MaaEnd-win-x86_64-v1.6.5` held v2.26.0-beta.3. Both self-update in
place and neither renames its folder, so the name freezes at whatever was first
downloaded - and it misled three separate investigations in one day, twice
badly enough to reach a wrong conclusion. A directory name is not a version;
`MAA.exe`'s `FileVersion` and MaaEnd's `interface.json` are.

```
D:\ark\automas\            scheduler (Electron + embedded Python)
  config\Config.json                                global settings incl. notifications
  config\QueueConfig.json                           queues and their times
  config\ScriptConfig.json                          per-user script settings (stage, medicine, ...)
  history\<YYYY-MM-DD>\<user>\<HH-MM-SS>.json+.log  one run record per script per attempt
D:\ark\maa\  Arknights bot
  config\gui.new.json                               the live config; gui.json is a dead older format
  cache\gui\StageActivityV2.json                    event end times, source of the report countdown
D:\ark\maaend\                 Endfield bot
C:\ProgramData\ark-relay\                           the relay; Windows service "ark-relay"
  relay.log                                         its log
  state\                                            ledger-<date>.jsonl, seen.txt, pending.json,
                                                    code-version.txt, announced-version.txt,
                                                    ark-do-last.txt, report-/interim-<date>.sent
C:\ProgramData\ark-do.ps1 / ark-cmd.txt / ark-do.log   remote input
C:\ProgramData\ark-shot.ps1 / ark-shot.png             one-shot screenshot
C:\ProgramData\focus-watch.log                         foreground-window log
```

<!-- check: win D:\ark\automas -->
<!-- check: win D:\ark\automas\config\ScriptConfig.json -->
<!-- check: win D:\ark\automas\config\QueueConfig.json -->
<!-- check: win D:\ark\automas\config\Config.json -->
<!-- check: win D:\ark\maa\config\gui.new.json -->
<!-- check: win D:\ark\maa\cache\gui\StageActivityV2.json -->
<!-- check: win D:\ark\maaend -->
<!-- check: win C:\ProgramData\ark-relay -->
<!-- check: win C:\ProgramData\ark-do.ps1 -->
<!-- check: win C:\ProgramData\ark-shot.ps1 -->

AUTO-MAS users are `arknights` (MAA) and `endfield` (MaaEnd) - ASCII since
2026-08-21. **Renaming a user means rewriting the relay's `state\seen.txt` too**:
a record's identity is `<date>/<user>/<time>`, so old records would look new and
replay every alert they ever raised.

The history filename is the run's START time on a **UTC+4** clock - AUTO-MAS
names directories by the game's day-rollover timezone, so every filename reads
four hours early. The file mtime is when the whole queue finished, not this
script. For real times, use the timestamps inside the `.log`; the relay does
(`collector._log_span`) and only falls back to the filename when a run produced
no timestamped log at all.

## Schedule (server time; Tokyo is +1h)

| Time | What | Trigger |
|---|---|---|
| 08:40 / 08:45 | smart plug cuts then restores power | Mi Home timer |
| 08:46-08:47 | boot, auto-login, AUTO-MAS + relay start | BIOS "restore on AC", logon tasks |
| 09:00 | queue `新队列`: MAA then MaaEnd, ~85 min | AUTO-MAS timer |
| 21:20 | the machine powers on | BIOS RTC (`08-10 21:20:16 BOOT` in the event log) |
| 21:30 | queue `Evening-MAA`: MAA only, ~45 min | AUTO-MAS timer |
| after the last queue | relay sends the report, then powers off | relay |

The morning wake and the evening wake use different mechanisms: the plug cuts
mains power so the board's "restore on AC" setting boots it, while the evening
one is the board's own RTC alarm and needs no plug at all.

Arknights must farm twice a day at roughly even spacing or the base overflows.

The relay reads these times from AUTO-MAS's own `QueueConfig.json`, so moving a
queue there moves the missed-run alarms and the report cutoff with it - there is
no second copy of the schedule to keep in sync.

Between roughly 10:30 and 21:20 the machine is fully off and nothing on it can observe
anything. That blind spot is what GitHub Actions covers (see below).

## Remote input: the ark-do task

An SSH session has no desktop (session 0 isolation), so `CopyFromScreen` and any
synthetic mouse input fail outright. Everything that touches the screen goes
through a scheduled task running in the interactive session.

```bash
cat > cmd.txt <<'EOF'
run D:\ark\automas\AUTO-MAS.exe
sleep 20000
click 264 345
shot C:\ProgramData\s1.png
monitoroff
EOF
scp cmd.txt Administrator@$ARK_HOST:'C:/ProgramData/ark-cmd.txt'
ssh Administrator@$ARK_HOST 'schtasks /run /tn "ark-do"'
scp Administrator@$ARK_HOST:'C:/ProgramData/s1.png' .
```

| Action | Meaning |
|---|---|
| `move x y` | move the cursor |
| `click x y` / `rclick x y` / `dclick x y` | left / right / double click |
| `scroll x y n` | wheel n notches at (x,y), positive is up. Electron ignores PgUp/PgDn, so this is the only way to page AUTO-MAS's UI |
| `type <SendKeys>` | keystrokes, e.g. `type {ESC}` |
| `sleep <ms>` | wait |
| `run <path>` | start a program (path only, no arguments) |
| `shot <path>` | full-screen capture |
| `uiclick x y` | click for Electron / WebView UIs - hover, settle, click twice |
| `vclick x y` | **verified click** - photographs a patch, clicks, photographs again, and says in the log whether anything reacted |
| `vclick x y cx cy w h` | same, but check a rectangle centred on `(cx,cy)` instead of on the cursor - use whenever the effect appears somewhere else |
| `focus <window title substring>` | raise a window and wait for it to settle before clicking into it |
| `monitoroff` | blank the display. Put it last - any later mouse action wakes it |

A plain screenshot is also available as `schtasks /run /tn "ark-shot"` writing
`C:\ProgramData\ark-shot.png`.

<!-- check: task ark-do -->
<!-- check: task ark-shot -->
<!-- check: task ark-focus-watch -->

### Prefer `vclick`, and read the log

`click` is fire-and-forget: it moves the cursor, presses, releases, and never
looks. `vclick` checks each step - that the cursor arrived, that SendInput was
accepted, and that the screen actually reacted - and writes the verdict to
`ark-do.log`:

```
vclick OK at 1072,830 (8.02% of the checked patch changed)
!! VCLICK NO REACTION at 716,1056 (0% changed) - do NOT blind-retry a toggle
```

**It never retries by itself.** An automatic retry is only safe on a control
that ignores a second press; on a checkbox it undoes the first click and then
reports failure for a setting it changed twice. That happened here on
2026-08-22. If a click needs repeating, repeat it in the batch after looking at
a screenshot.

Three things were wrong with the first version of this, all of them the same
mistake in different clothes - **the check was easier to fool than the thing it
was checking**:

1. It verified the patch *under the cursor*. AUTO-MAS highlights a menu item on
   hover, so a click that never navigated scored 0.84% and passed.
2. It compared one byte in three, which in BGR is blue. White (255,255,255) and
   the theme blue (255,119,22) share a blue channel of 255, so toggling a
   checkbox scored **0%** and was reported as no reaction.
3. It rebuilt the input packet through `$i.mi.dx = ...`, which mutates a copy of
   a value-type field in PowerShell. Every event went out with all-zero flags.
   `SendInput` still returned 1, the cursor still moved because `MoveTo` falls
   back to `SetCursorPos`, and hover highlights still lit up - so for half an
   hour it looked exactly like "this app ignores synthetic clicks". It ignored
   nothing; nothing was ever sent.

**`click` misses on AUTO-MAS's UI, twice over, and both failures are silent** -
the cursor lands correctly and nothing happens. Measured 2026-08-22:

1. Electron/WebView controls arm on hover. A bare `click` sends press and
   release without the control ever having seen a `mouseover`, and is ignored.
   Moving there first and waiting fixes it.
2. When the window is not in the foreground, the first click is spent
   activating it. `run <exe>` raises the window but does not make that first
   click count - a stop button was pressed twice this way while the task kept
   running.

`uiclick` does both (hover, settle, click, click) and `focus` raises a window
properly first. Use them for anything drawn by AUTO-MAS or MaaEnd. Plain
`click` is still right for the game itself, which is a normal window inside the
emulator.

The task must run `-WindowStyle Hidden`. Without it the PowerShell console it
opens takes focus and covers the left half of the screen - the automation hides
its own click target. If that console ever gets clicked it enters mark mode and
freezes its own output; one `{ESC}` releases it.

**Screenshots do not steal focus** - tested and disproved as a cause of MaaEnd
failures. `run` and `click` do.

**ark-do does not hold off the shutdown.** An earlier version stamped
`state\ark-do-last.txt` and the relay treated a recent stamp as "somebody is
working on this desktop"; the operator removed that on 2026-08-22 - a countdown
that moves whenever a screenshot is taken makes the power-off time
unpredictable. To keep the machine up while working on it, use debug mode
(below), which is explicit and self-expiring.

Note this file is **not** in the relay manifest, so `deploy-relay.sh` and
selfupdate do not touch it - `scripts/windows/*.ps1` has to be scp'd by hand:

```bash
scp scripts/windows/ark-do.ps1 Administrator@$ARK_HOST:'C:/ProgramData/ark-do.ps1'
```

## Driving the game over ADB - use this, not the mouse

### The emulator has two instances. Only one has the game.

This cost an entire evening on 2026-08-22, so it goes first.

```
ldconsole list2
0,    雷电模拟器,       ...   <- factory instance, empty, ~570 MB
1000, 雷电模拟器-1000,  ...   <- the one with Arknights, ~40 GB
```

Both were created the same day the emulator was installed, two minutes apart -
instance 0 is not something anyone added, it ships that way. AUTO-MAS's
`EmulatorConfig.json` says `Index: 1000`, which is the only reason the right
one was ever being used: MAA had already started it.

**Instance index maps to ADB device by a fixed rule** ([LDPlayer's own
docs](https://help.ldmnq.com/docs/LD9adbserver)): "模拟器编号每+1，设备号+2",
i.e.

```
device port = 5554 + index * 2
  index 0     -> emulator-5554
  index 1000  -> emulator-7554     <- verified on this machine
```

So the address is computable, not something to discover by trial. MAA's own
[connection guide](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/manual/connection.md)
also notes its auto-detection only handles **a single running emulator** - with
multiple instances you must supply the address yourself.

### Starting the right instance

Three conditions, and all three are required. Each was violated at least once:

```bash
# via ark-do, NOT over ssh
runargs D:\LD-MRFZ\LDPlayer9\ldconsole.exe launch --index 1000
```

| Requirement | What happens otherwise |
|---|---|
| Use `ldconsole`, not `dnplayer.exe` | `dnplayer.exe --index 1000` ignores the argument and starts instance 0 |
| Run it through `ark-do` | over SSH it is session 0 with no desktop, and **no process appears at all** |
| Use `runargs`, not `run` | `run` takes a bare path; the whole string becomes the path and it reports `RUN FAIL` |

Note `ldconsole runninglist` and `list2` reported "nothing running" even while
the instance was up and serving ADB. **Do not use them as the readiness test.**

**Shutting the instance down has the same session constraint as starting it:**

```bash
# via ark-do
runargs D:\LD-MRFZ\LDPlayer9\ldconsole.exe quit --index 1000
```

Over SSH this command exits 0 and does nothing - `dnplayer.exe` and
`Ld9BoxHeadless.exe` stay in the task list. Verified 2026-08-22: two SSH
attempts left the emulator running, the same command through ark-do closed it.
Check with `tasklist | findstr /I "dnplayer Ld9BoxHeadless"`, not with the exit
code.

### Knowing when it is ready

In order, each check better than a timer:

```bash
adb devices                                    # the device appears
adb -s emulator-7554 shell getprop sys.boot_completed   # -> 1
adb -s emulator-7554 shell pm list packages | findstr hypergryph   # the game is there
```

The last one is the real test: an emulator can be up, booted and serving ADB
while being the wrong instance. Waiting on "a device exists" spent four minutes
watching the empty instance on 2026-08-22.

MAA's own order is worth copying: **connect first, launch only if that fails**,
then wait and reconnect - not "launch and sleep".

### From booted to the home screen

```bash
adb -s $DEV shell monkey -p com.hypergryph.arknights -c android.intent.category.LAUNCHER 1
# screenshot, look, tap START
adb -s $DEV shell input tap 800 852
# screenshot, look, tap 开始唤醒
adb -s $DEV shell input tap 800 641
```

Coordinates are read off `exec-out screencap -p`, which returns the device
frame (1600x900 here) with no desktop, no window border and no overlays.
**Measure on that image and send the numbers unchanged** - there is nothing to
convert, and MAA's own 1280x720 task coordinates only need converting because
it must run on every device.

Screenshot between every step. Do not chain taps with sleeps.



The emulator exposes an ADB endpoint. Everything the game needs can go through
it, and that is strictly better than screen coordinates and synthetic clicks:

```bash
ADB='D:\LD-MRFZ\LDPlayer9\adb.exe'
ssh $H "\"$ADB\" connect 127.0.0.1:7555"                    # returns "connected"
ssh $H "\"$ADB\" -s 127.0.0.1:7555 shell input tap 1496 779"
ssh $H "\"$ADB\" -s 127.0.0.1:7555 shell input swipe 1200 425 600 425 400"
ssh $H "\"$ADB\" -s 127.0.0.1:7555 exec-out screencap -p > C:\\ProgramData\\dev.png"
```

The device is **1600x900**. `screencap` returns exactly that, containing only
the game - no desktop, no window frame, no overlays. **Measure coordinates off
that screenshot and send them unchanged.** There is nothing to convert.

Three things this fixes at once, each of which cost time on 2026-08-22:

- **Overlays stop mattering.** A ToDesk panel was covering a 218x190 patch of
  the game's bottom-right corner, exactly where the depot button is. Over ADB
  it is irrelevant - the panel is a Windows window, the tap goes into the
  device. (This is also why the old warning about ToDesk breaking runs applies
  to MaaEnd's foreground controller and to screen-clicking, and **not** to MAA,
  which has always used ADB.)
- **Window position stops mattering.** No client-rect measurement to go stale
  when someone moves or resizes the emulator.
- **The launcher desktop stops mattering.** `adb shell monkey -p
  com.hypergryph.arknights -c android.intent.category.LAUNCHER 1` starts the
  game directly. No hunting for an icon - and no chance of dragging the icon
  off the launcher's home screen, which is how one earlier attempt ended.

Package name: `com.hypergryph.arknights` (official server). Find it with
`adb shell pm list packages | findstr hypergryph`.

### Getting from nothing to the home screen

MAA's own sequence, from its logs, and it is worth copying exactly:

```
正在连接模拟器......
连接失败
正在尝试启动模拟器
等待模拟器启动时间（秒）：10s
等待结束
正在运行中......
```

**Connect first; only launch the emulator if that fails.** Then wait a fixed
interval and reconnect. The success test is "ADB answers", not "some seconds
have passed" - the difference between those two is the difference between a
procedure and a guess.

After the game starts, it is a state machine, never a fixed script. Every round:
screenshot, see what is actually on screen, act on that. What can show up:

| On screen | Do |
|---|---|
| Title page with START | tap it |
| 「开始唤醒」 | tap it |
| Loading triangle, centre | **nothing - wait and look again** |
| Announcement popup | close it |
| 今日配给 | dismiss it |
| Disconnect confirmation | confirm |
| Resource integrity check | let it finish |

Reaching the home screen is not the end: MAA checks it **three consecutive
times** before believing it, because "sometimes it is already at home, then a
window pops up a moment later" (its own comment). Do the same.

**Do not write click-sleep-click-sleep.** That was tried here and one slow load
desynchronised everything after it; the run ended up dragging the launcher's
home screen around and losing the game icon. A sequence assumes; a state
machine looks.

### Depot specifics

The depot shelf scrolls **horizontally**, which is not obvious - a vertical
drag does nothing at all, silently. MAA's own swipe is right-to-left across the
middle of the shelf; over ADB on this device, something like
`input swipe 1200 425 600 425 400` moves about one screen. Tabs across the top:
全部 / 消耗物品 / 基础物品 / 养成材料. Materials live under 养成材料;
基础物品 is currencies.

MAA knows it has reached the end when the recognised starting position stops
changing, not by counting pages - the swipe is less than a full screen, so
consecutive views overlap and items must be de-duplicated by id.

## Telling the machine NOT to do something

Two levers, both in `C:\ProgramData\ark-relay\state\`, both self-expiring by
design so that "just this once" cannot silently become permanent.

<!-- check: dir C:\ProgramData\ark-relay\state -->

### Debug mode - do not power off, do not alarm

The file holds a **moment**, `YYYY-MM-DD HH:MM` on the server clock, and the
mode releases **ten minutes before the next scheduled power-on** - not at
midnight.

```bash
# what "leave it alone tonight" means: through to just before the next cycle
ssh $ARK_HOST 'powershell -NoProfile -Command "Set-Content C:\ProgramData\ark-relay\state\debug-until.txt -Value \"2026-08-23 08:30\" -NoNewline"'
# release early
ssh $ARK_HOST 'del C:\ProgramData\ark-relay\state\debug-until.txt'
```

`modes.set_debug(state_dir, cycles=1)` computes that moment. A power-on less
than 150 minutes away counts as the cycle already under way and is skipped -
asked at 21:00 to leave the machine alone, releasing at 21:10 (ten minutes
before the 21:20 wake) would cover none of the run it was meant to cover.

Power-on times are not discoverable on the machine: the morning one is a Mi
Home plug cutting and restoring mains so the board's "restore on AC" boots it,
the evening one is the board's own RTC alarm. `modes.BOOT_TIMES` carries them,
default `08:40,21:20`, override with `ARK_BOOT_TIMES`. **Moving the plug timer
or the BIOS alarm means changing that too** - nothing else will notice.

While it holds, the engine will not power the machine off (the idle checkpoint
included) and will not raise missed-run alarms. It does **not** stop the queues
- to have the machine boot and farm nothing, disable the queue as well.

A bare `YYYY-MM-DD` is still read as end-of-that-day, and anything unparseable
reads as "debug on" on purpose: the wrong failure here powers off a box
somebody is working on.

**Why it is not days.** Until 2026-08-23 this took a day count and expired at
midnight. Asked at 21:00 on the 22nd for "no shutdown tonight", it expired
forty minutes later, in the middle of an AUTO-MAS update.

### Skip mode - one queue sits out one occasion

```bash
# server-time date in the filename, queue name in the body
echo -n Evening-MAA > flag && scp flag $ARK_HOST:'C:/ProgramData/ark-relay/state/skip-2026-08-22.flag'
```

The first relay tick that sees the flag disables that queue in AUTO-MAS and
writes `skip-restore.json` capturing the queue's times; 30 minutes past the last
of those times, a later tick re-enables it and deletes the marker. The marker is
written **before** the disable, so a crash in between leaves a marker that
restores an already-enabled queue - a no-op - rather than a queue disabled
forever.

**Do not disable a queue by hand instead.** Editing `TimeEnabled` over SSH works
for tonight and then leaves it off for every night after. If it has already been
done, drop a `skip-restore.json` in by hand to hand it back to the machinery:

```json
{"queue": "Evening-MAA", "day": "2026-08-22", "last_time": "21:30"}
```

**Known gap:** `queues.apply` writes `QueueConfig.json` without stopping
AUTO-MAS, so a skip engaged or restored while AUTO-MAS is running can be undone
when AUTO-MAS next writes its in-memory copy out - the same trap CONFIG.md
documents for hand edits. Verify with a read-back after the restore fires.

## Driving all three without a window

**The full method now lives in [HEADLESS.md](HEADLESS.md)** - the API client,
the request-shape traps, MAA's binding, MaaEnd's inventory file, and an audit of
what the relay can and cannot hand over. What follows is the summary.

The desktop is only composited while something consumes frames, so with nobody
watching, screen grabs return a stale frame and MAA's window comes back blank.
Every one of these three programs can be driven without its UI, and that is the
direction this system is moving.

### AUTO-MAS - a FastAPI backend, 126 endpoints

The Electron window is a shell over a Python backend that serves a REST API.
Because it is FastAPI, the machine itself publishes the contract:

```bash
# the backend is the python.exe running main.py; find the port it listens on
netstat -ano | findstr LISTENING | findstr <pid>
curl http://127.0.0.1:<port>/openapi.json      # measured 2026-08-23: port 36163
```

**The port looked dynamic** - do not hard-code 36163 without checking. Verified
by fetching the spec live: 126 paths, almost all `POST` with a JSON body.

The ones that matter here:

| Endpoint | What it replaces |
|---|---|
| `/api/dispatch/start` `{taskId, mode}` | triggering a queue by hand |
| `/api/dispatch/stop` | stopping a run |
| `/api/dispatch/set/power` `{signal}` · `get/power` · `cancel/power` | the power-off decision |
| `/api/queue/*` (add / update / item / time / order / delete) | the stop-edit-restart JSON dance on `QueueConfig.json` |
| `/api/scripts/user/update` · `/api/scripts/get` | editing `ScriptConfig.json` by hand |
| `/api/setting/get` · `/api/setting/update` | editing `Config.json` by hand |
| `/api/info/get/overview` | reading the home page off a screenshot - it returns the live activity stages, their drops and expiry |
| `/api/ocr/screenshot` · `/api/ocr/screenshot/adb` · `/api/ocr/click/text` · `/api/ocr/click/image` | ark-do clicking, and blind coordinate taps |
| `/api/history/search` · `/api/history/data` | scraping the history directory |
| `/api/emulator/operate` · `/api/emulator/status` | `ldconsole` through ark-do |
| `/api/scripts/maa/depot/items` `{scriptId}` | the 库存保持 item list |
| `/api/scripts/maaend/options` `{scriptId}` | MaaEnd's task list |

**This removes the reason config edits needed the program stopped.** The API
writes through the running backend, so there is no in-memory copy to be
clobbered - which was the whole basis of the stop-edit-restart procedure.
Verified end to end on 2026-08-23: read a setting, write the opposite, read it
back changed, restore it - all over HTTP from the Mac, with AUTO-MAS running.

**Reachable from here, and unauthenticated.** `http://<tailscale-ip>:36163`
answers directly; the port survived a reboot. It binds `0.0.0.0`, so anything
that can route to the machine can drive it. Fine on Tailscale, not fine on an
untrusted network - if this box ever leaves that private network, this is the
first thing to close.

**Mutating endpoints wrap their payload in `data`.** This is the one trap:

```jsonc
// /api/setting/update
{"data": {"Function": {"IfBlockAd": true}}}
// /api/queue/update
{"queueId": "<uid>", "data": {"Info": {"TimeEnabled": false}}}
// /api/scripts/user/update
{"scriptId": "<uid>", "userId": "<uid>", "data": {...}}
```

Sending the inner object alone returns something that is not the usual
envelope and changes nothing - a silent no-op. Read the schema out of
`/openapi.json` rather than guessing the shape:
`scripts/mac/mas-api.py paths` prints every endpoint with its required fields.

The client lives at `scripts/mac/mas-api.py`.

### MAA - MaaCore, already in use

`scripts/windows/copilot-drive.py` drives it through the binding MAA ships at
`Python/asst/`. See the copilot section below.

### MaaEnd - MaaFramework

MaaEnd is built on MaaFramework, whose Go/Python bindings and CLI are the same
shape as MaaCore's. Its own agent is a Go service plus C++ algorithms, so the
headless surface exists; it has not been exercised here yet.

**MaaEnd does have an inventory readout - IMS.** An earlier reading of its
feature list said otherwise; that was wrong. The feature is not advertised as
"check my depot" because it exists to answer "do I have enough", so it is easy
to miss from the outside.

IMS (Item Management System) lives in MaaEnd's go-service and is documented at
`docs/zh_cn/developers/components/ims.md`. Two recognisers and three actions:

| Node | Does |
|---|---|
| `SyncItemData` | scan the current screen and write **the whole table** into cache |
| `SyncShopItemData` / `SyncValuablesItemData` | the same for 采购中心 and 珍贵物品页 |
| `AddItemData` | scan and *add* to the cache |
| `UpdateItemQuantity` | adjust one item |
| `ItemQuantitySatisfied` / `ItemDataReady` | test the cache against a condition |

**The result is a file:** `<MaaEnd>/debug/record/IMS.json`, `{updated_at,
items: {<id>: <count>}}`. Reading it needs no automation at all.

**It is already being filled every day.** Of MaaEnd's task entries only
`ProtocolSpace.json` (协议空间) reaches `SyncItemData`, and 协议空间 is in the
nightly run - which is why the file exists. The chain is
`SyncItemData -> SyncItemDataBegin -> SyncItemDataInProgressionTab ->
SyncItemDataRunFull`, so that pass is **already the full scan**, not a partial
one. To refresh it, run the MaaEnd script and re-read the file.

Item ids map through `assets/data/IconRecognition/recognition_items.json` (782
entries) for **category, rarity, storageKind and icon id** - but its `name`
field is a hash, so readable Chinese names are not in MaaEnd's own data. 29 of
the 43 ids seen on 2026-08-23 were in that catalog; the rest are the
fixed-point currency nodes (`T_CREDS`, `OROBERYL`, `VALLEY_STOCK_BILL`, ...)
declared per-task rather than in the catalog.

## MAA's auto-battle (自动战斗 / Copilot) - run, 2026-08-23

Read before touching it. Everything below is either from
[MAA's own manual](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/manual/introduction/copilot.md)
and [integration protocol](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/protocol/integration.md),
or measured on this machine on 2026-08-22.

Note MAA's default branch is **`dev-v2`**, not `dev` - a `dev` URL 404s.

### Raid mode (突袭), and what a 1-star clear means

An EX stage has two difficulties and they are separate clears with separate
rewards. From the stage's detail panel, **突袭模式** at the bottom switches it;
the title turns red, an 附加条件 appears (AT-EX-8's is "「斩」所需费用提升") and
the button becomes **开始突袭**.

**A raid clear settles at ONE star and that is correct.** Three stars is not
available in raid. So a success detector keyed on `StageDrops-Stars-3` will
report a perfectly good raid as a failure - which is what happened here on
2026-08-23. What is *wrong* is a one-star settlement on a stage that does have
three stars.

In `copilot_list` an entry carries `is_raid`; in single-copilot mode there is
no such field, because the game is already in raid mode when you started from
that screen.

Jobs declare which difficulties they support in `difficulty`: `1` normal, `2`
raid, `3` both, `0` unset. Filter on it - and note that the copilot site indexes
the raid variant under its own level id, `act44side_ex08#f#` beside
`act44side_ex08`.

### When auto-formation rejects an operator - read `reason`, not `why`

Two different failures wear the same wrapper. The outer error always says
`"why": "OperatorMissing"`; the useful field is `reason` inside `details.opers`.

| `reason` | What it means | Fix |
|---|---|---|
| `Unavailable` | The operator **is owned and was found**. The job declares a 练度要求 - usually `skill_level`, i.e. a specialised skill - that this account has not reached, and MAA enforces it | set **`ignore_requirements: true`** |
| `Missing` | MAA did not find the operator in the list at all | check 特别关注 per the FAQ |

Measured 2026-08-23 on AT-EX-8's most-popular job: 丰川祥子, 八幡海铃 and 酒神
were all rejected with `requirement_type: "skill_level"`. All three are owned.
With `ignore_requirements: true` the identical job formed the full six-operator
squad and reached `BattleStartAll` - the requirement is the job author's
preference, not a constraint the game imposes.

**So `ignore_requirements: true` is the default here**, and a job should only
be swapped out after that has been tried.

Two mistakes made this take hours instead of minutes:

1. **The logger truncated the callback to 260 characters** - and the field that
   distinguishes the two cases sits past that cut. Never truncate diagnostic
   output for readability; log it whole and read the whole thing.
2. `reason: "Missing"` was read as "the account does not own this operator",
   and two perfectly usable jobs were discarded on that basis.

### When auto-formation says an operator is "Missing"

It does **not** mean the account lacks the operator. It means MAA did not find
it in the formation list. The official FAQ names the cause in one line:

> 若自动编队无法正常识别干员，请取消对应干员的特别关注。
> — [MAA FAQ](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/dev-v2/docs/zh-cn/manual/faq.md)

On 2026-08-23 this was read as "the operator is not owned" and two jobs were
swapped away on that basis; the operator owned both of them. **Check the
special-focus marks before the first run, not after the third failure.** The
filter is the rook icon in the sort bar, present on every operator list.

The headless path loses nothing here: the callback carries
`{"opers": {"<name>": [{"reason": "Missing"}]}}`, which is the same fact the
GUI turns into its message box. What was missing was the translation, not the
data.

### Run it through MaaCore, not the window

`scripts/windows/copilot-drive.py` clears a list of stages unattended. It talks
to `MaaCore.dll` through the binding MAA ships at `Python/asst/`, so there is no
window to see and nothing to click - which matters here because MAA's window
cannot be screenshotted at all when nobody is watching the machine (see
PITFALLS).

Six stages of 墟 were cleared this way on 2026-08-23, and every failure along
the way came from the same mistake in different clothes: **assuming a starting
screen instead of establishing one.**

| What was assumed | What happened |
|---|---|
| `filename` mode navigates | It does not. It expects the formation screen and errors on `BattleStartAll` from anywhere else. `copilot_list` navigates; single mode fights |
| Copilot navigation works from the main screen | For an event stage it does not - it hunts the main-story chapters. 224 swipes and 100 chapter turns looking for AT-5 |
| BACK a few times reaches a neutral screen | BACK on the main screen raises 是否确认退出游戏, and the tap meant to dismiss it opened the event shop twice |
| Hand-timed taps reach the game | 70 s to the splash is enough until it is not. MAA's `StartUp` task waits on what it sees; use it |
| MAA can navigate any stage | It could not find this event's **EX** map. Tapping there by hand and running `filename` mode worked first try |

The working recipe, in order:

1. `StartUp` task - MAA opens the game and reaches the main screen.
2. Tap into the event map (banner, then section). Only safe *because* step 1
   guarantees the screen it starts from.
3. `copilot_list` with one entry - it navigates within the event map and fights.
4. On `BattleFormationTask` + `reason: Missing`, move to the next job for that
   stage. `support_unit_usage: 1` borrows when exactly one operator is missing,
   which the operator reckons covers 90% of the cases.

**Detect a stall by repetition, not by silence.** A navigation that cannot find
its stage emits callbacks forever, so a quiet-timer never fires. The driver
counts consecutive identical subtasks and gives up at 30.

### What it is

A copilot ("作业") is a JSON timeline for one stage: which operators, which
skills, and an ordered `actions` list of deploy / skill / retreat steps, each
gated on kills, cost, cost change, cooling count or elapsed time. MAA replays
it. It is not a solver - it does exactly what the file says, so a file written
for a different roster or a different stage fails rather than adapts.

### Prerequisites - both are hard requirements

| Requirement | Status here |
|---|---|
| **60+ stable FPS** in the emulator | **unverified** - LDPlayer stores no fps key in `leidian1000.config` or the global `leidians.config`, so it is on the default and can only be confirmed in the emulator's own settings UI |
| Touch mode **MiniTouch or MaaTouch** | **OK** - the `Default` profile (the one the queue runs, `emulator-7554`) is `MiniTouch`; the second profile is `MaaTouch` |

`ConnectSettings/TouchMode` in `config\gui.new.json` holds this. **Plain ADB
`input tap` - what this system uses for manual poking - is not one of the
accepted modes.** Deployment is a press-drag-release with a direction flick and
frame-accurate timing; the tap-based approach used to read the depot cannot do
it, which is why this is MAA's job and not something to reimplement.

### Where a copilot comes from

- **prts.plus 神秘代码**, pasted into MAA's 自动战斗 box, or
- **a local JSON file**.

Both routes are open from the game machine - measured 2026-08-22: `prts.plus`
returned HTTP 200 three times out of three and the API MAA actually calls,
`prts.maa.plus/copilot/get/<id>`, returned 200. **This is not the same as
`prts.wiki`, which 403s from that address.** Do not generalise either result to
the other host.

There is already a local library: 39 files in
`D:\ark\maa\config\copilot\` (`ME-*`, `AD-EX-*`, `15-3`, `15-4`, ...)
plus MAA's bundled `resource\copilot\`.

### Which screen it has to start from - this is the usual failure

| Mode | Start MAA here |
|---|---|
| single copilot | the formation screen, the one with **开始行动** |
| 战斗列表 (battle list) | the **map screen** holding those stages, not the formation screen |
| 保全派驻 | after doing the initial setup by hand, at **开始部署** |
| 悖论模拟 | **自动编队 off**, skills chosen by hand, at **开始模拟** |

For a battle list, every stage must be in one area - reachable by swiping the
map left and right only. The list stops itself on insufficient sanity, a lost
battle, or a non-3-star clear.

### Auto-formation wipes the current formation

`自动编队` **clears whatever is in the formation** and rebuilds it from the
copilot's operator list. Two consequences worth knowing before the first run:

- 特别关注 (special-focus) marks on those operators must be cleared, or the
  pick fails.
- MAA does **not** borrow a support unit unless `support_unit_usage` says so,
  and loop counts are meaningless when borrowing.

`LoopTimes` applies to single-copilot mode only, never to a battle list.
Current settings: `Default` profile has `SelectFormation=1`, `LoopTimes=3`,
`SupportMode=WhenNeeded`, and an empty `TaskList`.

### AUTO-MAS cannot start it - this is the blocker

AUTO-MAS's MAA integration exposes only `IfFight`, `IfSeizeEntrustTask`,
`SanityTaskType` and `TaskTransitionMethod`. There is **no copilot field**, so a
copilot cannot be put in the nightly queue the way farming is. Two routes exist:

1. **Drive MAA's GUI** through `ark-do` - `focus`, then `uiclick`, since MAA's
   window is the Electron-style UI that swallows plain clicks.
2. **Call MaaCore's `Copilot` task** directly, which is what the GUI does
   underneath:

```json
{
  "enable": true,
  "filename": "copilot/1-7.json",
  "loop_times": 2,
  "formation": true,
  "formation_index": 0,
  "use_sanity_potion": false,
  "support_unit_usage": 0
}
```

`copilot_list` replaces `filename` for a battle list, each entry being
`{filename, nav_name_override, is_raid}`; with a list, `loop_times` is ignored
and `set_params` may be called only once.

### Before the first real run

1. Confirm the emulator's frame rate in its settings UI (the config file cannot
   answer it).
2. Pick a stage that costs little to fail.
3. Expect the formation to be rebuilt - do not run it on a formation that
   matters.
4. Watch the first attempt with a screenshot, not by trusting the exit code.

### Emulator frame rate

60 FPS, stated by the operator. It is not in any LDPlayer config file - do not
go looking for it again.

## Changing game configuration

**Never launch MAA.exe or the MaaEnd executable directly.** They are launchers:
starting one also brings up the emulator or the game itself. Go in through
AUTO-MAS's UI - `run AUTO-MAS.exe` focuses the already-running instance.

**AUTO-MAS is the authority for everything downstream.** Before each run it
rewrites MAA's task table and stage config, and rewrites MaaEnd's `optionValues`
from its own `ScriptConfig.json` (when that user has `Info.IfQuickConfig` true,
which this machine does). Editing MAA's or MaaEnd's own config is a no-op that
looks like it worked. Anything automated must write AUTO-MAS's config; see
`relay/ark_relay/sanity_plan.py`.

**AUTO-MAS holds its config in memory and writes the whole thing back.** A JSON
edit made while it runs succeeds, reads back correctly, and is gone at the next
UI save or launch. Its UI is not reliably better: text fields appear to persist
on 返回, toggles did not persist even after closing the window.

The reliable procedure - stop everything, edit, restart, re-read:

```
net stop ark-relay                                   # else the relay revives AUTO-MAS mid-edit
schtasks /change /tn "AUTO-MAS_AutoStart" /disable
taskkill /IM AUTO-MAS.exe /F                         # the Python backend exits with the shell
  ...  download, edit locally, json.loads, structural diff, back up, upload  ...
schtasks /change /tn "AUTO-MAS_AutoStart" /enable
schtasks /run  /tn "AUTO-MAS_AutoStart"
net start ark-relay
```

Then read the value back **after AUTO-MAS has restarted**, not before.

Three write paths, and the differences between them are deliberate.

`commands.py` edits the JSON **as text**, so it carries the full structural diff
described below: added=0, removed=0, changed exactly as expected, or roll back.

`maaend.py` parses to a dict but still diffs, with the check scoped to the
options it meant to touch - a checkbox going from seven days to two genuinely
adds and removes leaves, so a blanket added=0/removed=0 would reject real edits
while a stray change anywhere else is still caught.

`sanity_plan.py` and `queues.py` parse to a dict and do not diff. Structure
cannot be broken that way, so they rely on a different set of guards: refuse to
create a key that does not already exist, validate types, back up, write
atomically, roll back on failure, and (sanity_plan) read back. Do not "add the
diff for consistency" there; it guards against a failure mode those two do not
have.

Never regex-edit JSON on the remote host. The procedure that has never failed:
fetch base64 → edit locally within the located block → `json.loads` → flatten
both sides to `path → value` and require added=0 / removed=0 / changed=N →
back up remotely → upload → re-read and re-parse. `scripts/mac/edit-json.py`
does this. Step 4 is not optional: it is what caught a regex that disabled 2 of
3 webhooks and damaged an unrelated section.

Some numeric fields have hidden floors. `Game/WaitTime` is `Field(ge=60)` in
AUTO-MAS's `app/models/schema.py`: writing 30 succeeds, reads back as 30, and is
silently 60 again after the next launch. When a change "reverts itself", read
that schema before suspecting the write.

## Deploying relay code

```bash
ARK_HOST=<tailscale ip> scripts/mac/deploy-relay.sh
```

Rebuild manifest → syntax check → scp → **verify every file's hash** → stamp
`state\code-version.txt` → clear `__pycache__` → restart the service → print the
startup log. Any step failing exits non-zero.

Never plain `scp`. On 2026-08-20 an scp returned 0 without transferring; the
service restarted onto old code and only a hash comparison found it. *Believing
you deployed is worse than not deploying.*

## The relay is a Windows service

```bash
sc query    ark-relay
sc stop     ark-relay        # maintenance
sc start    ark-relay
sc qfailure ark-relay        # restart after 3s, reset window 60s
```

<!-- check: svc ark-relay -->

The SCM holds a handle on the process, so a crash is noticed by the kernel with
no polling interval. Recovery actions deliberately do **not** apply to a manual
`sc stop` - that is Windows behaviour and it is what makes maintenance possible.
`sc config ark-relay start= disabled` and `sc delete ark-relay` are the other
two intentional escape hatches; do not close them.

Rollback path: `sc delete ark-relay` then re-enable the disabled scheduled task
`ark-relay`, which was deliberately left in place as a way back.

<!-- check: task ark-relay -->

Services do not run `ark-relay.ps1`, so the environment that script used to set
is absent. `service.py` sets `PYTHONUTF8`, `PYTHONIOENCODING` and `ARK_LOG_FILE`
itself - without that the service ran fine and logged into nothing. Installing
the service makes pywin32 move `pythonservice.exe` and `pywintypes312.dll` into
AUTO-MAS's embedded Python directory; that is pywin32's own mechanism.

### Watchdogs

A watchdog watches something that should be alive and restarts it when it dies.
There are two layers, and each exists because the layer below it once died
silently:

| Watcher | How it notices | What it does |
|---|---|---|
| Windows SCM → relay | kernel process handle | restarts the relay after 3s |
| relay → AUTO-MAS | WMI `Win32_ProcessStartTrace` + a handle on the backend | restarts it immediately |

On 2026-08-15 the relay and AUTO-MAS stopped together, the 21:30 round was lost,
and **no alarm fired - the thing that raises alarms was the thing that died.**

A watchdog only answers "is the process there". Whether the run was correct is
the relay's judgement and has nothing to do with it.

<!-- check: task AUTO-MAS_AutoStart -->

Reviving AUTO-MAS takes three steps and skipping one fails silently:

```
taskkill /IM AUTO-MAS.exe /F            the Electron shell outlives the dead backend;
                                        the window looks fine and nothing is scheduled
schtasks /end /tn "AUTO-MAS_AutoStart"  while the shell lives the task counts as running,
                                        so /run returns 0x41301 and does nothing
schtasks /run /tn "AUTO-MAS_AutoStart"
```

Revive failures back off (180s, doubling, capped at 30 min) and alarm after 3
consecutive failures. Only if the WMI subscription cannot be created does it
fall back to a 120s liveness check, and that degradation is logged at startup.

AUTO-MAS itself cannot be a service: it drives an emulator and game windows, and
services live in session 0 with no desktop.

## Checking whether the machine ran

```bash
scripts/mac/watch-run.sh          # follow a run live: OK/FAIL per record, OFFLINE, DONE
```

**The window between a run finishing and the machine powering off is about a
minute**, and it is not a good time to be collecting anything. The report goes
out as soon as the last record lands, the shutdown countdown is 60 s, and a
watcher polling every three minutes will simply miss it - which is how the
2026-08-22 morning's MaaEnd logs went uncollected despite a watcher being armed
for exactly that.

Collect while the run is still going, or wait for the next boot. Nothing is
lost by waiting: `history/` and `focus-watch.log` are on disk and survive the
power cycle. If something really must be caught before shutdown, watch for the
script **starting** rather than for its record appearing - that gives half an
hour of margin instead of one minute.

```powershell
(Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
(Get-CimInstance Win32_OperatingSystem).LastBootUpTime
Get-Process AUTO-MAS | Select-Object StartTime
Get-WinEvent -FilterHashtable @{LogName='System'; Id=6005,6006,1074} -MaxEvents 40 |
  ForEach-Object { $_.TimeCreated.ToString("MM-dd HH:mm:ss") + "  " + $_.Id }
```

`6005` boot, `6006` clean shutdown, `1074` shutdown requested - this is how BIOS
wake and auto-shutdown get confirmed.

Power settings that must hold:

```powershell
powercfg /change monitor-timeout-ac 5     # display may sleep - harmless
powercfg /change standby-timeout-ac 0     # the machine must NEVER sleep
powercfg /change hibernate-timeout-ac 0
powercfg /requests                        # who is blocking sleep
powercfg /lastwake                        # what woke it
```

Display sleep does not affect tasks: the desktop still renders and ADB still
works. System sleep interrupts everything. MAA drives the emulator over ADB and
produces no system-level mouse input, so the screen goes dark during its 45
minutes; MaaEnd's foreground controller seizes the mouse, so the screen stays
lit for its whole run and that cannot be avoided.

## MaaEnd's pre-update

`relay/ark_relay/preupdate.py`, run once per boot when a queue still to come that
day includes MaaEnd. It launches MaaEnd, waits up to 180 s for its update check
to settle (`更新检查完成: ... 有更新=false` in `MaaEnd/debug/<date>-<n>.log`),
then closes it. If an update landed, the operator is told.

It exists because MaaEnd restarts its own process after updating, which kills
whatever round AUTO-MAS had just started - see [PITFALLS.md](PITFALLS.md).
Auto-update is deliberately left on; only its timing moved.

Skipped when the day's remaining queues are MAA-only, so the evening boot does
not start a program nothing will use. Failure is cheap by design: if it cannot
run or does not finish, the round behaves exactly as it did before - one wasted
attempt, then the retry succeeds.

## What the new runtimes actually buy us

Both machines run Python 3.14 and PowerShell 7. Most of what those releases
changed is irrelevant to this project; this is the short list of things that
are, so the next person does not have to read seven changelogs to find out.

### Python (we came from 3.9 on the Mac, and from AUTO-MAS's bundled copy on the game machine)

- **`zoneinfo`** (3.9+) is the one that matters here. This project lives in two
  clocks - the machine is UTC+8, the operator is UTC+9 - and every hand-rolled
  offset is a DST bug waiting for a country to change its mind.
  `ZoneInfo("Asia/Shanghai")` and `ZoneInfo("Asia/Tokyo")` are in the standard
  library, no `pytz`, no vendored table.
- **Deferred annotation evaluation** (PEP 649/749, 3.14) means
  `from __future__ import annotations` is no longer needed for `X | None` in
  signatures. Harmless to keep - the relay still has it - but new modules do
  not need the line.
- **`tomllib`** (3.11) reads TOML with no dependency. Worth remembering if a
  config ever wants comments, which JSON cannot carry.
- **Much better tracebacks** (3.11 onward): the failing sub-expression is
  underlined, and `ExceptionGroup` renders readably. This is not a feature we
  call, it is one we benefit from every time a remote script dies.
- **`match`** (3.10) suits dispatch on record shape. Not a reason to rewrite
  anything working.

Deliberately not used: free-threading (PEP 703), sub-interpreters (PEP 734),
t-strings (PEP 750). Nothing here is CPU-bound or templating-heavy.

### PowerShell (we came from Windows PowerShell 5.1)

- **UTF-8 by default.** This is the whole reason the mojibake chapter in
  PITFALLS.md ends where it does. 5.1 reads files as ANSI (CP936 here) unless a
  BOM says otherwise; 7 reads and writes UTF-8. `scripts/mac/winrun.sh` still
  writes a BOM, because it must survive whichever host picks the script up.
- **`ForEach-Object -Parallel`** (7.0) for bulk remote checks. `check-docs.py`
  does its own fan-out, so this is for ad-hoc work.
- **`&&` / `||` pipeline chain operators, `?:`, `??`, `??=`** (7.0). These make
  one-liners over SSH shorter, which matters when every character has to
  survive bash quoting on the way in.
- **`Test-Json`** (6.1) validates before writing. Our policy is JSON-first for
  config changes - stop the program, diff, write atomically, read back - and
  this is a cheap extra gate in that sequence.
- **`Get-Error`** renders the full error record including inner exceptions,
  which the default one-line view hides.

Deliberately not used: `Invoke-WebRequest` for anything large. It moved 19 MB
in 24 minutes on this machine where `curl.exe` moved 108 MB in 85 seconds. Use
`curl.exe`; Windows has shipped it since 1803.


## Four programs, four update mechanisms

All three update through MirrorChyan on the beta channel, and that is where the
similarity ends. Each needed a different answer in the relay's pre-update, so
the differences are written down rather than rediscovered.

| | 何时发现更新 | 如何应用 | 中途会不会打断队列 | 中继怎么处理 |
|---|---|---|---|---|
| **MAA** | 运行期间自己查（日志见 21:30 那次） | 下载后放进 `<MAA>\NewVersion`，**下次启动**由 Bootstrapper 应用 | 不会——应用被推迟到下次启动 | 看 `NewVersion` 目录在不在；在才用 `MAA.exe --skip-startup-auto-run` 启动一次让它装完 |
| **MaaEnd (MXU)** | 每次启动时查 | 当场下载并**重启自己** | 会——如果在跑任务时启动 | 开机时用 `--autostart` 先启动一次（这是唯一能跳过「更新完成」弹窗的分支），并临时清空 `autoStartInstanceId` 保证不开跑 |
| **AUTO-MAS** | 后端每 4 小时查一次 | 需要显式 download + install；install 解压 `UpdatePack_*.zip` 后启动 `AUTO-MAS-Setup.exe` | 不会——`Run/IfAutoUpdateAfterQueue` 默认 false 且本机未设 | 直接调它自己的 HTTP 接口：check → download → 等包落地 → install |
| **OK-WW（鸣潮）** | 启动时由 pyappify 检查 | 从 **CNB git 镜像** `cnb.cool/ok-oldking/ok-ww-update2.git` 拉取；`app.json` 里 `"update_method": "AUTO_UPDATE"` | 会——它 `Auto Start Game When App Starts` 开着，一启动就连游戏一起开 | 开机时临时关掉那个开关，用 `ok-ww.exe` 启动（**必须走这个外壳**，直接跑内置 python 会让 pyappify 上下文缺失、`/api/updates` 报 `pyappify_version: None`），等 `app.json` 的 `update_state` 落回 idle，关掉并还原 |

四条容易踩的：

- **MAA 的待装更新可以脱离网络判断**：`NewVersion` 目录就是全部信号。MirrorChyan 的匿名查询帮不上忙——`MaaResource` 查得到，`MAA` 和 `MaaEnd` 返回 `{"code":8001,"resource not found"}`，要 CDK。两台机器都验过。
- **MaaEnd 不带 `--autostart` 就查不完**：刚更新过的那次开机，`App.tsx` 弹出「更新完成」框之后直接 `return`，后面的更新检查根本不执行。症状是中继空等满 180 秒。
- **AUTO-MAS 装更新时进程会退出**，而中继本来会立刻把它拉起来。之所以不打架，是因为 `INSTALLER_HINTS` 里的 `auto-mas-setup` 正好就是它启动的安装器名字。改动那份名单前先想想这条。


- **OK-WW 是四个里唯一不走 MirrorChyan 的。** MirrorChyan 确实收录了 `okww`（匿名查询就能拿到版本），但那只是初装下载渠道；它自带的更新器是 git 型的，国服 profile 指向 CNB。实测这台机器上 `cnb.cool` 是 200/0.32 秒，而 `github.com` 完全连不上，所以 CNB 这条路是对的，不要改。
- **改 OK-WW 的配置前必须先停掉它。** 2026-08-24 踩过：我留着一个 `ok web` 实例，它把设置持在内存里又写回磁盘，于是「关掉自动开游戏」白改，`ok-ww.exe` 读到 True 就把鸣潮拉起来了。和 MAA 的母本/副本是同一类错误——**改一个正在运行的进程拥有的文件，等于改副本**。`preupdate._okww_quiesce()` 就是为此存在的。

## Update channels

Both code and config reach the machine through this GitHub repo, because the
machine **cannot reach github.com or api.github.com at all** - TCP is blocked
(0/6 on 2026-08-20). Only plain HTTPS file fetches work, which also means
nothing can ever be uploaded from the machine.

- **Code**: `relay/manifest.json` carries a SHA-1 per file. At every service
  start the relay **waits up to 90 s for DNS** and then fetches whatever
  changed, all-or-nothing, inside a 240s budget, then restarts itself. The wait
  is not optional: the relay is logon-triggered and comes up before Windows has
  a resolver, so without it every boot-window update failed with
  `getaddrinfo failed` before reaching any door - see [PITFALLS.md](PITFALLS.md). **At service start specifically, never at the end of a
  queue** - the machine boots at 21:20 for a 21:30 queue, and that gap is the
  window this is meant to use. Once the new code is running it pushes a notice
  saying so; see [NOTIFICATIONS.md](NOTIFICATIONS.md).
  Note the manifest only covers `relay/ark_relay/*.py`, `run.py` and
  `service.py`. Anything else - `scripts/windows/ark-do.ps1`, for instance -
  has to be scp'd by hand, and so does any brand-new relay file, because
  selfupdate deliberately refuses to create files that do not already exist.
- **Config**: `queue/config.json`, applied once per strictly-newer integer
  `version`. See `queue/README.md` for the command format.

Doors, in the order the code tries them (measured from the machine 2026-08-21,
8 attempts each):

| Door | Success | Median |
|---|---|---|
| `fastly.jsdelivr.net` | 8/8 | 426 ms |
| `cdn.jsdelivr.net` | 7/8 | 1956 ms |
| `gcore.jsdelivr.net` | 7/8 | 2398 ms |
| `raw.githubusercontent.com` | 2/8 | 38179 ms |

raw is last because it is by far the slowest, but it is the only door that can
never serve a stale copy, so it stays as the final fallback. Both fetchers query
**every** door and take the highest `version` - a lagging mirror used to make a
config change silently do nothing.

After pushing, run `scripts/mac/purge-cdn.py`: it purges jsDelivr and then waits
until the machine could actually fetch the new version. Its success test mirrors
what selfupdate really does - the newest manifest across **all** doors equals
the local one, and every file is served correctly by **at least one** door -
because an earlier version only watched fastly and reported failure during the
minutes fastly lagged, while the machine was already able to update fine. A test
stricter than reality is a false alarm generator.

It also reports how many files only `raw` can serve. That number matters: raw's
measured median is 38 s, the whole round has a 240 s budget, so once more than
about five files fall through to raw alone the update will not finish in time
and will be abandoned cleanly. When that is the situation and a boot is close,
use `deploy-relay.sh` instead - it is certain.

**Fetch speed and cache-refresh speed are different things**, measured
2026-08-21. The table above ranks fetches. On refresh the order inverted: after
a purge that the API reported as `"status": "finished"` with both providers
acknowledging, `cdn.jsdelivr.net` served the new manifest within seconds while
`fastly.jsdelivr.net` - the fastest door for fetching - was still serving the
previous version minutes later. A second purge in quick succession is also
slower than the first.

That is survivable by design rather than by luck: `raw.githubusercontent.com`
carries the new manifest immediately, `_best_manifest` takes the highest version
across all doors, and `_get_with_retry(expect_sha=...)` treats a hash mismatch
as "this door is stale, try the next". So a machine booting mid-refresh still
gets the right code - just slowly, since more files fall through to raw. When
the purge script times out and the boot window is close, prefer the certain
path: `deploy-relay.sh` pushes over SSH with hash verification.

A stale manifest could also downgrade the relay. `deploy-relay.sh` stamps
`state\code-version.txt` and selfupdate refuses any manifest not strictly newer,
including one carrying no version field at all.

## Off-machine supervision

Nothing running on the machine can report that the machine failed to boot. That
check is a GitHub Actions schedule that reads the device's `lastSeen` from the
Tailscale API and pushes over Server酱: `scripts/watchdog.py`,
`.github/workflows/watchdog.yml`, config `queue/watchdog.json`.

The machine sends no heartbeat and needs no code for this: tailscaled connecting
at boot and dropping at shutdown *is* the check-in signal.

**Not enabled.** It needs three repository secrets - `TS_OAUTH_CLIENT_ID`,
`TS_OAUTH_SECRET`, `SERVERCHAN_KEY` - and `enabled: true` in `watchdog.json`.
Set `pause_until` before deliberately leaving the machine up overnight, or it
will alarm at 23:10 about a machine that should have shut down.

Once it is on, remember that remote GUI work interacts with it: every `ark-do`
batch holds the shutdown for 20 minutes, and the morning check expects the
machine off by 10:45. A screenshot taken at 10:30 will therefore trip the
"should have shut down" alarm. `pause_until` is the intended answer, and
`workflow_dispatch` runs every check in print-only mode for testing.

`git log` decides whether it runs at all: GitHub disables scheduled workflows on
a public repo after 60 days with no commits. Inbox edits normally keep this one
alive, but a quiet stretch would switch off the only sentinel that lives
outside the machine - silently, which is the whole hazard this file is about.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/mac/deploy-relay.sh` | push relay code with hash verification (see above) |
| `scripts/mac/watch-run.sh` | follow a run from the Mac until DONE or OFFLINE |
| `scripts/mac/purge-cdn.py` | purge jsDelivr and wait for the new version to be served |
| `scripts/mac/edit-json.py` | safe remote JSON edit: locate → replace → validate → structural diff |
| `scripts/mac/check-docs.py` | verify the facts in these docs against repo and machine |
| `scripts/mac/mem-sample.sh` | LaunchAgent, samples Mac memory every 600s (a time series, not polling) |
| `scripts/mac/push.py` | manual push to the notification channels |
| `scripts/mac/make-app.sh` | wrap a script as a double-clickable .app |
| `scripts/mac/strip-transcript-images.py` | shrink a session transcript that has grown huge with screenshots |
| `scripts/windows/ark-do.ps1` | the GUI action interpreter behind the `ark-do` task |
| `scripts/windows/ark-shot.ps1` | single screenshot |
| `scripts/windows/setup-tasks.ps1` | create the scheduled tasks this system needs |
| `scripts/windows/run-probe.py` | emit run records as pure ASCII so nothing must survive the GBK console |
| `scripts/windows/focus-watch.py` | log every foreground-window change; task `ark-focus-watch` starts it at logon |
| `scripts/windows/probe-mirrors.py` | measure which mirrors work from the machine, including content freshness |
| `scripts/windows/push-wecom.ps1` | push an image to WeCom |
| `scripts/windows/hp-fix.ps1` | one-off repair of the HP server's sshd. Nothing references it and the HP server is not part of this system; kept because that machine still runs the daemon it fixed |
| `scripts/watchdog.py` | the GitHub Actions boot supervisor |

<!-- check: repo scripts/mac/deploy-relay.sh -->
<!-- check: repo scripts/mac/watch-run.sh -->
<!-- check: repo scripts/mac/purge-cdn.py -->
<!-- check: repo scripts/mac/edit-json.py -->
<!-- check: repo scripts/mac/check-docs.py -->
<!-- check: repo scripts/mac/mem-sample.sh -->
<!-- check: repo scripts/mac/push.py -->
<!-- check: repo scripts/mac/make-app.sh -->
<!-- check: repo scripts/mac/strip-transcript-images.py -->
<!-- check: repo scripts/windows/ark-do.ps1 -->
<!-- check: repo scripts/windows/ark-shot.ps1 -->
<!-- check: repo scripts/windows/setup-tasks.ps1 -->
<!-- check: repo scripts/windows/run-probe.py -->
<!-- check: repo scripts/windows/focus-watch.py -->
<!-- check: repo scripts/windows/probe-mirrors.py -->
<!-- check: repo scripts/windows/push-wecom.ps1 -->
<!-- check: repo scripts/watchdog.py -->
<!-- check: repo .github/workflows/watchdog.yml -->
<!-- check: repo relay/manifest.json -->
<!-- check: repo queue/config.json -->
<!-- check: repo queue/watchdog.json -->

## Symptom → first thing to check

| Symptom | Look at |
|---|---|
| SSH connects, no banner, drops instantly | antivirus quarantined `sshd-session.exe`. **Needs a person at the machine** |
| Nothing ran at the scheduled time | is AUTO-MAS running; does `AUTO-MAS_AutoStart` still exist; did the machine reach the desktop |
| Protocol space failed | was someone connected over ToDesk - its session panel covers the button |
| MaaEnd failed on attempt 1, fine on attempt 2 | expected; window race on first launch. Not a fault |
| No notifications at all | AUTO-MAS's switches are layered - see [CONFIG.md](CONFIG.md) |
| WeCom `errcode=60020` | the caller IP is not in the trusted list |
| The emulator started but it was the wrong instance | emulator type must be `ldplayer` + `ldconsole.exe` |
| A config change reverted itself | AUTO-MAS was running and overwrote it from memory, or the field has a `ge` floor in its schema |
| A deploy "succeeded" but behaviour is unchanged | compare hashes; use `deploy-relay.sh`, never bare scp |
| Self-update failed right after boot with `getaddrinfo failed` | no resolver yet, not a flaky mirror. All four doors failing in the same second is the tell |
| Report says something happened at an impossible hour | the history filename is on a UTC+4 clock |

## Open items

Split by what is needed to close them, so the list is not read as work handed
to the operator when most of it is not.

### Requires access outside this repository

- **WeCom `errcode=60020`.** Either add the current egress IP in the admin
  console (the alarm carries it), or create a group bot and set `WECOM_BOT_URL`,
  which has no trusted-IP list and survives a changing home IP. Server酱 is
  carrying everything meanwhile.
- **The watchdog needs three repository secrets** - `TS_OAUTH_CLIENT_ID`,
  `TS_OAUTH_SECRET`, `SERVERCHAN_KEY` - and `enabled: true` in
  `queue/watchdog.json`.
- **`ARK_LLM` (DeepSeek) reports the model unavailable.** Reports fall back to
  structured formatting with no prose line, which costs one sentence and
  nothing else. Needs a working key.

### Accepted limits - understood, not going to be fixed

- **SSH is a single point of failure.** Everything remote sits on it and it
  cannot repair itself: when antivirus quarantined `sshd-session.exe` the only
  fix was a person at the machine. A second channel would need a service the
  machine can reach outward, and it cannot reach GitHub at all.
- **The 21:30 checkpoint cannot tell maintenance from an idle machine.** Boot
  the machine in the afternoon, still be working at 21:30, and it powers off
  underneath you. `debug_mode` is the workaround.

  A 20-minute hold keyed off remote GUI activity was built for this on
  2026-08-21 and removed on 2026-08-22 at the operator's request: it made the
  shutdown time unpredictable, and an unpredictable shutdown is worse than the
  problem it solved. Shutdown timing should stay boring.
- **A relay restart more than two hours after a run still leaves nobody to
  shut down.** `recent_due_queues` forgets a queue after that, and widening the
  window would also widen the "wait for a script that never ran" hold that
  shares it. The realistic case - a selfupdate restart minutes after the run -
  is fixed.

### Outstanding work - not blocked on anything external

- **Alarms are only as timely as AUTO-MAS's writes.** It flushes every attempt
  at once when the script ends, so a 09:17 login failure cannot be known before
  ~09:58; the relay's own file-to-push latency is 34 s. Fixing it means tailing
  MaaEnd's live log as a second source and deciding which one wins when they
  disagree. Deliberately not done the evening before a run: a new log parser
  that misreads a line turns a working night into false alarms.
- ~~**MaaEnd's first-attempt failure has no confirmed cause.**~~ Solved
  2026-08-22: MaaEnd updates itself at startup and restarts its own process,
  orphaning the log monitor AUTO-MAS just attached. `preupdate.py` now does that
  update in the boot-to-queue gap. See [PITFALLS.md](PITFALLS.md).

## Appendix: driving PlayCover games on the Mac

Unrelated to the game machine; this is computer-use against iOS games running
under PlayCover locally.

1. **Slow presses only.** PlayCover translates mouse events into touches and a
   one-shot `left_click` is often ignored. Use move → down → wait 1s → up, for
   every click including the small X that closes a dialog.
2. **Drag, don't scroll**, and decompose it: down → 2-3 moves → up. Dragging
   right-to-left reveals content *later* in the list; left-to-right reveals
   *earlier*.
3. **Page a horizontal list one screen at a time.** Three large swipes jump to
   the far end and skip two full screens in between - which is how half a shop
   inventory got missed and reported as "cleared out".
4. **Read the whole shop before buying anything.** Tokens are finite and what
   you buy first decides what you can no longer afford.
