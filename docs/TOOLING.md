# Tooling rules — the 21 traps stepped into on 826

The only reason this document exists: **never step into the same trap twice.**
On 2026-08-26, within a single day, there were 21 distinct classes of failure that produced
error text; the most frequent single one was hit **36 times**.
For details see memory `incident-826` and `fix-dont-work-around`.

---

## Remote execution

| Situation | Use this | Not this |
|---|---|---|
| Multi-line logic, parsing files | `scripts/mac/winrun.sh --py <local.py>` | Stringing an inline command together |
| Need the screen / enumerate windows / start a GUI program | `winrun.sh --py1` (goes through the interactive desktop session) | `--py` (runs in session 0, which has no desktop) |
| Fetch file contents | `winrun.sh --get '<remote path>'` | Remote `type`/`cat` and then reading stdout |
| One-off PowerShell | `winrun.sh --ps '<wrapped in single quotes>'` | Double quotes (`$_` gets expanded early by bash) |

**PowerShell is always `pwsh` (7.6.5), never `powershell` (5.1).**
5.1 does not default to UTF-8; `ConvertFrom-Json` on Chinese JSON will fail and the output will
be mojibake.

**Always send PowerShell over ssh as base64** — do not string quotes together. One inline command
has to pass through four layers, bash → ssh → cmd → PowerShell, and each layer takes a bite out
of it. `run_remote_ps()` in `winrun.sh` is the reference form; copy it:

```bash
b64=$(printf '%s' "$PS" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
ssh "$USER_AT" "pwsh -NoProfile -EncodedCommand $b64"
```

**Failure semantics of `winrun.sh --py`** (fixed 2026-08-26; before that it failed silently as
success):

| Exit code | Meaning |
|---:|---|
| 0 | Normal, produced output |
| 3 | Script could not be delivered (scp failed) |
| 4 | No `winrun.out` was produced on the remote end (script never ran / machine unreachable) |
| 5 | **It ran but produced 0 bytes** — that is not success, treat it as a failure |

**Never `rglob` the whole disk looking for a file.** On 826, searching for `relay.log` walked all
of `C:\` + `D:\`, got killed by a 10-minute timeout, and found nothing.
**Paths should be read out of the code instead**:

* Relay log: `C:\ProgramData\ark-relay\relay.log` (`REMOTE_DIR` in `deploy-relay.sh` +
  the `ARK_LOG_FILE` default in `relay/app_main.py:103`)
* Relay state: `C:\ProgramData\ark-relay\state`
* MAS config: `D:\ark\automas\config\`
* MaaEnd logs: `D:\ark\maaend\debug\<date>-<n>.log`, `maafw.log`
* MAA logs: `D:\ark\maa\debug\gui.log` (the UI), `asst.log` (the core, more detailed)

---

## AUTO-MAS API (`http://<host>:36163`)

* **Every endpoint accepts POST only**; GET always returns `Method Not Allowed`
* To read a script's config, first `POST /api/scripts/get {}` to get the uid, then
  `POST /api/scripts/user/get {"scriptId": "<uid>"}`
* Change config: `POST /api/scripts/user/update {"scriptId","userId","data"}`
* Queue: `POST /api/queue/update {"queueId","data"}`
* Start/stop: `POST /api/dispatch/start {"taskId","mode"}` / `/api/dispatch/stop {"taskId"}`
  — **manual dispatch always goes through `scripts/mac/run-one.sh MAA|MaaEnd|OK-WW`**, which has
  the busy/idle gate built in. Calling `/api/dispatch/start` bare fights with AUTO-MAS's own
  whole-queue retry — that is exactly how, on the morning of 2026-09-01, we ended up with
  「MAA 重复吃药、三个游戏同时在线」 and had to pull the power to recover.
* Field definitions are in `components.schemas` of `GET /openapi.json`

**`ValueError: 配置已锁定, 无法修改`**: config is read-only while a task is running.
**The correct move is to `dispatch/stop` the task first, wait for the AUTO-MAS process to go
idle, and then write** — not to retry harder; on 826 that was tried 18 times in a row and failed
every time. Verified: with no task running, the write succeeds immediately.

**`Data.Stage` in `Config.json` is JSON nested inside a string**, so it needs `json.loads` twice:

```python
st = c["Data"]["Stage"]
if isinstance(st, str): st = json.loads(st)
```

**The `task` array in MaaEnd's `interface.json` is empty**; the 45 tasks are pulled in from
`tasks/*.json` via `import`. Looking only at the `task` field leads to the false conclusion that
it has no tasks.

---

## The relay (ark-relay)

**The relay brings AUTO-MAS back up on its own.** `_revive_automas()` (`relay/boot_stages.py`,
called by `_AutomasKeeper` in `relay/ark_relay/features/host/automas_keeper.py`, which
`mainloop._loop` builds; the installed relay's `app_main.py` runs that loop) is called **unconditionally**, with no debug gating (debug mode only governs "do not
shut down, do not report a missed run"). It also holds a process handle plus a WMI event
subscription watching AUTO-MAS.

**And on the installed relay something brings the relay back.** It is not a Windows service any
more (`packaging/switch.py install`): the logon task `\ArkRelay\main` runs `{app}\launch.py`
(`{app}` = `C:\Program Files\ArkRelay`), and the service `ArkRelayWatchdog` runs that task
again within 30 s whenever the relay is gone (`packaging/watchdog/ark_watchdog.py` `CHECK_S`).
The relay in turn starts a stopped watchdog again unless the marker
`C:\ProgramData\ark-relay\watchdog-stopped.txt` was written since the boot
(`relay/watchdog_guard.py`).

**So any "stop everything" operation stops the relay first, in this order** — otherwise the MAS
you killed is back within tens of seconds — the order of `packaging/switch.py` `stop()`:

1. `stop_watchdog()`: write the marker, `sc stop ArkRelayWatchdog`, and wait until it is really
   STOPPED (`sc stop` returns at once; stop it again if it shows RUNNING again).
2. `end_relaunch_helpers()`: end any update restart helper (`pythonw.exe … launch.py relaunch`),
   which would start the relay again once it has exited.
3. `{app}\runtime\python\python.exe {app}\launch.py stop`: asks the running relay to stop and
   waits.

On the machine `"C:\Program Files\ArkRelay\runtime\python\python.exe" "C:\Program
Files\ArkRelay\switch.py" stop` does all three. The red button `scripts/mac/estop.sh`
follows the whole order (its branch for the old `ark-relay` service, taken only when the machine
reports that layout, has had nothing to stop since that service was deleted on 2026-10-11; when
it cannot tell which relay the machine runs it stops the installed one): **relay (watchdog → restart helper → relay) → MAS →
scripts → games**, and ends the task (`schtasks /end /tn \ArkRelay\main`) when the relay is still
running after `launch.py stop`; `estop.sh --restore` removes the marker, starts the watchdog and
runs the task.

**The old relay is retired** (the pre-package `ark-relay` service, its logon task and its code in
`C:\ProgramData\ark-relay`): done 2026-10-11 22:33 with `scripts/windows/retire_legacy.py --go`,
which deleted the service and the task and moved the files into
`C:\ProgramData\ark-relay-retired-1011` (manifest.txt, saved `sc qc` / service and event-log
registry exports / task XML) instead of deleting them; that folder can be cleared after 30 days
(`KEEP_DAYS`). `packaging/switch.py revert` now exits 6 and points at `launch.py rollback`
(the previous version folder) as the way back.

**A recorded day for the day replay (daysim).** `scripts/mac/pull-day.sh <YYYY-MM-DD>` packs
the machine's record (`C:\ProgramData\ark-relay` without `.env`, and the `D:\ark` logs the
replay reads; nothing on the machine changes except its own archives in `%TEMP%`, which are
hashed and deleted), unpacks it under `~/Claude/daysim-corpus/_pull/<stamp>/` and runs
`relay/tests/daysim/slice.py`: the day's corpus (`~/Claude/daysim-corpus/<D>/`, redacted copies
with their true mtimes) plus `relay/tests/daysim/days/<D>/events.jsonl` and `seed.json` in the
repo, checked against the record by `relay/tests/test_daysim_slice.py` (`--full` reads every
byte). `--from <pull dir>` re-slices an earlier pull without touching the machine.

**The day gate.** `relay/tests/daysim/gate.py` (deploy-relay.sh step 0.8) replays every
recorded day through the code under test (`run.py --all`) and stops on any failure line that
`relay/tests/daysim/known-red.json` does not list; each entry there names an open
`docs/BACKLOG.md` todo, expires within 7 days and must still match its exact line count, so a
fixed or changed bug fails the gate until its entry goes. Then each `badfix/*.patch` puts a
fixed bug back into a throwaway copy of the code (R36: 10-13's 11:13 power-off during a test
window) and its day must go red. `scripts/mac/deploy-relay.sh --dry-run` runs gates 0-0.8 only
(no network, no machine, no COS; gates 0.5 and 0.6 are reported instead of stopping) and is
the way to try a branch. lint-repo item 25 checks every `expected.json` and replays 10-13.
`relay/tests/daysim/pack.py` builds the light packs the Windows CI replays (`days/<D>/pack.tar.zst`).

**The game-layer gate.** `scripts/mac/lib/ci_green.py` (deploy-relay.sh step 0.9, the first
gate after the dry-run exit; it needs the network) requires a green run of
`.github/workflows/gamesim-windows.yml` - the OK-WW overlay inside the real OK-WW and
ok-script on windows-latest: frame truth, the scenarios, the install cycle and the relay's
verdicts on the overlay's own log lines (`relay/tests/gamesim/`). The workflow runs on every
push to `main`, `relay-*` and `gamesim-ci-*`. The deploy passes when the commit being deployed
has a green run (a rollback to an already-green commit passes the same way), or when a green
run's commit has the same game-layer files (`relay/` without `manifest.json`,
`RELEASE-NOTES.md` and `state/`, `packaging/`, the workflow file; `GAME_LAYER`). It stops,
with exit 16, when the commit's runs are all finished and none is green (each run's URL is
printed; a lane that crashed with 0xC000001D on some runners is a runner fault:
`gh run rerun <id> --failed`), when the commit is on no remote branch the workflow runs on
(push it first: `git push origin HEAD:refs/heads/main` or `:refs/heads/relay-<name>`), when
GitHub does not answer, and when the run is still not done after 15 minutes (the 58-job runs
on 10-13 took 7.3 and 9.6 min). Alone: `python3 scripts/mac/lib/ci_green.py [--sha REV]`.

---

## Local command line

* **Always use absolute paths.** After every heredoc the shell's cwd is reset to the default
  directory, so relative paths are guaranteed to break — on 826 this one was hit **36 times**,
  the most frequent problem of the day.
* A `gh api` URL containing `?` must be quoted, or zsh treats it as a glob and reports
  `no matches found`
* `gh search repos --json` has no `stargazerCount` (that is the GraphQL name); to search
  repositories use `gh search repos --topic=<topic>` — `gh api search/repositories` often comes
  back empty
* macOS has no `timeout` command. Use the Bash tool's own timeout parameter, or ssh's
  `-o ConnectTimeout=`
* Foreground `sleep` is disabled. To wait, poll on a condition; do not pad it out with `ping`
* Chrome headless sprays noise onto stderr (`Trying to load the allocator multiple times`,
  `task_policy_set`). **`--log-level=3` has no effect on those** — those lines are written before
  the logging system is initialised (measured 2026-08-26). You also **cannot `2>/dev/null`**:
  Chrome writes the "N bytes written to file" success message to stderr as well.
  **Always use `scripts/mac/html2png.sh`**, which filters out exactly the known-harmless lines
  and judges success by the output file itself (Chrome frequently returns 0 even when rendering
  failed)
* Any single output above roughly 37KB gets spilled to a file instead of being displayed.
  **Limit the output volume deliberately** (`head`, print only the fields you need); do not
  expect to dump everything to the screen

---

## Disk tidy (what sessions leave on this Mac's disk)

The disk filled to 100 % twice on 2026-10-13: worktrees, session scratch dirs, DerivedData, old
Gradle / Swift versions and caches that no session ever removed. The owner (10-13 22:3x): we never
clean what we create and he cannot watch us. `scripts/mac/disk-tidy.py` is the cleaner; its rules
are the "safe" column of that evening's inventory (`/private/tmp/claude-501/disk-tidy/inventory.md`),
re-checked live on every run.

```
~/.local/bin/python3.14 scripts/mac/disk-tidy.py            # dry run (default): what would go, sizes, why the rest stays
~/.local/bin/python3.14 scripts/mac/disk-tidy.py --apply    # remove; one line per removal in ~/Library/Logs/disk-tidy.log
```

* **Normal rules** (always): merged + clean worktrees idle 24 h (`git worktree remove`, branch
  kept), stale worktree registrations (`git worktree prune`), DerivedData project folders idle
  24 h, `~/.gradle/{caches,daemon}/<version>` no Homebrew gradle or wrapper uses, swiftly
  toolchains other than `inUse` (`swiftly uninstall`), `/private/tmp/claude-501/<project>/<session>`
  of finished sessions, the one-off outputs `$TMPDIR/precheck-*`, `~/Claude/transit-app/build`,
  `remote-ref/tools/bugexam/xcr-dd`, and the caches (`uv cache prune`, `brew cleanup --prune=all`,
  `go clean -cache`, `~/.cache/pyright-python`), plus `xcrun simctl delete unavailable`.
* **Floor rules** (free space under `--floor-gb`, default 30, or `--aggressive`): the same
  worktree / DerivedData rules with a 2 h idle window, Xcode's shared caches while no build runs,
  and git-ignored `.build` / `.swiftpm` / `.ruff_cache` inside idle unmerged or dirty worktrees
  (the checkout and its changes stay).
* **In use** means any of: a process has it open or as cwd (`lsof`; if lsof fails nothing is
  removed), a file in it changed inside the idle window, a running session
  (`~/.claude/sessions/*.json`) or the session it continues owns it, a workflow journal written in
  the last 2 h names the worktree, or code in `~/.claude/hooks`, `remote-ref/tools` or a repo names
  the path or session tmp dir (reused, e.g. the precheck tests read 5f3e1301's files).
* **Never**: anything under `~/Money` or `~/Claude` that is not a session worktree or a listed
  build output, the standing trees (`maa-automation-data/ui/ui2`, `transit-data/ui`,
  `ds-relay-tree`), a worktree with uncommitted changes, `~/.claude`, CoreDevice, simulators,
  app containers, anything no rule matches. `git worktree remove` never gets `--force`.
* Scheduling: `scripts/mac/launchd/com.ark.disk-tidy.plist` (hourly `--apply`, nice 10, low-priority
  I/O, output in `~/Library/Logs/disk-tidy.out`) is in the repo but **not installed**; installing
  it is a separate decision. Tests: `relay/tests/test_disk_tidy.py`.

---

## Fetching web pages

* `WebFetch` **does not follow** cross-origin redirects; get the new URL and issue a second request
* Some sites return 403 outright (`endfieldtools.dev`, `mobalytics.gg`, `icy-veins.com`, 萌娘百科).
  **The correct substitute is to actually open them with the browser tools**
  (`mcp__Claude_Browser__*`). That is not a workaround, it is switching to the right tool —
  WebFetch is a simple fetcher, not a browser

---

## Extra tools installed on this machine

| Tool | Location | Why it was installed |
|---|---|---|
| `shellcheck` 0.11.0 | `~/.local/bin/shellcheck` | `estop.sh` is a safety-critical script, and `bash -n` checks syntax only, not logic |

Homebrew is installed (`/opt/homebrew`, checked 2026-10-13; `disk-tidy.py` runs `brew cleanup`).
A single static binary can still just come from the official release
(`gh release download --repo <owner/repo> --pattern '<name>'`).
`coreutils` / `pytest` were evaluated and judged not worth installing.
