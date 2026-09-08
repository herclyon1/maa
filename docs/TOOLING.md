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
  `ARK_LOG_FILE` in `service.py`)
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

**`ark-relay` brings AUTO-MAS back up on its own.** `_revive_automas()` in `service.py` is called
**unconditionally**, with no debug gating (debug mode only governs "do not shut down, do not
report a missed run"). It also holds a process handle plus a WMI event subscription watching
AUTO-MAS.

**So any "stop everything" operation must stop the `ark-relay` service first**, otherwise the MAS
you killed is back within tens of seconds. The red button `scripts/mac/estop.sh` already follows
that order: **relay → MAS → scripts → games**.

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

This Mac **has no Homebrew**. A single static binary can just come from the official release
(`gh release download --repo <owner/repo> --pattern '<name>'`).
`coreutils` / `pytest` were evaluated and judged not worth installing.
