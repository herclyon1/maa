# Operations

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

## Paths on the game machine

```
D:\Users\Administrator\Desktop\AUTO-MAS\            scheduler (Electron + embedded Python)
  config\Config.json                                global settings incl. notifications
  config\QueueConfig.json                           queues and their times
  config\ScriptConfig.json                          per-user script settings (stage, medicine, ...)
  history\<YYYY-MM-DD>\<user>\<HH-MM-SS>.json+.log  one run record per script per attempt
D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64\  Arknights bot
  config\gui.new.json                               the live config; gui.json is a dead older format
  cache\gui\StageActivityV2.json                    event end times, source of the report countdown
D:\maaend\MaaEnd-win-x86_64-v1.6.5\                 Endfield bot
C:\ProgramData\ark-relay\                           the relay; Windows service "ark-relay"
  relay.log                                         its log
  state\                                            ledger-<date>.jsonl, seen.txt, pending.json,
                                                    code-version.txt, announced-version.txt,
                                                    ark-do-last.txt, report-/interim-<date>.sent
C:\ProgramData\ark-do.ps1 / ark-cmd.txt / ark-do.log   remote input
C:\ProgramData\ark-shot.ps1 / ark-shot.png             one-shot screenshot
C:\ProgramData\focus-watch.log                         foreground-window log
```

<!-- check: win D:\Users\Administrator\Desktop\AUTO-MAS -->
<!-- check: win D:\Users\Administrator\Desktop\AUTO-MAS\config\ScriptConfig.json -->
<!-- check: win D:\Users\Administrator\Desktop\AUTO-MAS\config\QueueConfig.json -->
<!-- check: win D:\Users\Administrator\Desktop\AUTO-MAS\config\Config.json -->
<!-- check: win D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64\config\gui.new.json -->
<!-- check: win D:\Users\Administrator\Desktop\MAA-v5.1.0-win-x64\cache\gui\StageActivityV2.json -->
<!-- check: win D:\maaend\MaaEnd-win-x86_64-v1.6.5 -->
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
run D:\Users\Administrator\Desktop\AUTO-MAS\AUTO-MAS.exe
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
| `monitoroff` | blank the display. Put it last - any later mouse action wakes it |

A plain screenshot is also available as `schtasks /run /tn "ark-shot"` writing
`C:\ProgramData\ark-shot.png`.

<!-- check: task ark-do -->
<!-- check: task ark-shot -->
<!-- check: task ark-focus-watch -->

The task must run `-WindowStyle Hidden`. Without it the PowerShell console it
opens takes focus and covers the left half of the screen - the automation hides
its own click target. If that console ever gets clicked it enters mark mode and
freezes its own output; one `{ESC}` releases it.

**Screenshots do not steal focus** - tested and disproved as a cause of MaaEnd
failures. `run` and `click` do.

**Every ark-do batch delays the automatic shutdown by 20 minutes.** The script
stamps `state\ark-do-last.txt` and the relay treats a recent stamp as "somebody
is working on this desktop", which is the point - but it means a screenshot
taken while waiting for a run to finish pushes the power-off back. Take the
screenshots before the round ends, or expect to wait. The hold is bounded by
the last action, so it cannot keep the machine up indefinitely.

Note this file is **not** in the relay manifest, so `deploy-relay.sh` and
selfupdate do not touch it - `scripts/windows/*.ps1` has to be scp'd by hand:

```bash
scp scripts/windows/ark-do.ps1 Administrator@$ARK_HOST:'C:/ProgramData/ark-do.ps1'
```

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
