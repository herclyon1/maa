# Packaging the relay

The relay ships as a Windows installer built with Inno Setup (the tool AUTO-MAS uses
for its own installer). Everything the relay needs on the game machine is set up by
`ark-relay.iss`; reading that file tells you what is on the machine.

## Build

On Windows with Python 3.14.8 and Inno Setup 6:

    python packaging/build.py            # -> packaging/dist/ArkRelay-Setup-<version>.exe
    python packaging/build.py --stage-only
    python packaging/build.py --runtime-only <dir>   # any OS: <dir>/runtime/python only

`relay/manifest.json` decides which relay files go in (the same set a deploy ships), so
regenerate it (`relay/make-manifest.py`) after adding or moving files.

## What gets installed

| Where | What | Changed by |
|---|---|---|
| `{app}\runtime\python` | embedded Python 3.14.8, Pillow, pywin32 (`relay/requirements.txt`) | installer; a relay deploy when it is not what `packaging/build.py` and `relay/requirements.txt` build (see "The runtime" below); the one before stays as `python.prev` |
| `{app}\versions\<n>` | relay code, one folder per manifest version | installer, updater |
| `{app}\current.txt` | the version folder in use | installer, updater, rollback |
| `{app}\launch.py` | starts `versions\<current>\app_main.py` | installer; a relay deploy when it changed (before the restart) |
| `{app}\switch.py`, `{app}\legacy.py`, `{app}\handover` | the install / uninstall / revert steps, the legacy list, the AUTO-MAS handover | installer; a relay deploy when they changed |
| `{app}\watchdog` | `ArkRelayWatchdog` service | installer; a relay deploy when `packaging/watchdog/ark_watchdog.py` changed (`scripts/windows/pkg_deploy.py watchdog`: copy, `install`, restart; not the self-update) |
| task `\ArkRelay\main` | runs the relay at logon of the user at the console, highest privileges, no time limit, normal priority | installer |
| `C:\ProgramData\ark-relay` | `.env`, `state\` (the relay's state and the update bookkeeping, one folder as on the old relay; `.env` can name another with `ARK_STATE_DIR`), `relay.log`, `watchdog.log`, `switch.log` (what install, revert and uninstall did) | the relay; kept on uninstall unless the user says otherwise |

`{app}` is `C:\Program Files\ArkRelay`.

## Install and uninstall steps

The installer copies files and calls `switch.py`; the order of everything else is in
that one file:

The rule: whichever step fails, the machine is left with a relay that runs - the new
one or the old one.

- `switch.py install`:
  1. Stop and disable the old relay (`legacy.py takeover`).
  2. Hand AUTO-MAS the jobs it already does (`handover/automas_handover.py`: `plan`
     must pass, then `apply`; skipped on an upgrade, when the handover's backup exists).
  3. Register `\ArkRelay\main`.
  4. Register (or update) and start the watchdog.
  5. Start the relay. With someone logged on at the console, it must be running (its
     mutex) within 60 s and still 15 s later, or this step fails. With nobody there the task cannot run
     yet; that is not a failure, and the watchdog starts it at logon.

  If any step fails, everything is reverted as `switch.py revert` does and the old relay
  runs again; the installer shows why (a silent one exits 1). `/SKIPHANDOVER=1` on the
  setup command line skips step 2 (for the cloud test machine, which has no AUTO-MAS).
- `switch.py revert` (by hand): back to the old relay without uninstalling. AUTO-MAS's
  settings are put back first; then the new relay is stopped and switched off (files
  stay) and the old relay is switched on. If the settings cannot be put back, nothing
  changes and the new relay keeps running (exit 4), so the two never do the same jobs
  at once; if the old relay does not start, the new one comes back (exit 5). Running
  the installer again switches over again. Once `scripts/windows/retire_legacy.py --go`
  has retired the old relay, revert changes nothing and exits 6: the way back is then
  the previous version folder (`launch.py rollback`), and a failed upgrade switches the
  new relay on again instead of the old one.
- `switch.py resume --current=<name>` (from the installer): an upgrade stops the
  installed relay before it copies files (`switch.py stop`). When Setup ends before the
  switch-over - Cancel, or a file it cannot replace - its `DeinitializeSetup` runs this:
  `current.txt` goes back to the folder it named before (Setup's rollback keeps files it
  already replaced), then the watchdog and the task start. A watchdog a revert disabled
  stays off. `switch.py` and `legacy.py` are the first files copied, so this is the new
  code whenever Setup got past them.
- `switch.py uninstall`:
  1. Stop the watchdog and the relay.
  2. Put back the AUTO-MAS settings the handover changed. If that fails (AUTO-MAS busy
     or not answering), stop here: the relay is started again, nothing is removed, the
     uninstaller says so and ends without deleting a file.
  3. Remove the version folders' `state` junctions.
  4. Unregister the service and the task.
  5. Remove the old relay and what it left (`legacy.py remove`, from
     `handover/legacy-items.json`). The uninstall removes everything except his data
     and his settings backups; the way back to the old relay is `revert`, not this.

## How it runs

- `\ArkRelay\main` starts `launch.py` at logon. The relay (`relay/app_main.py`) runs the
  same boot sequence and loop as the old service, in the user's session, so it can see
  the desktop. It holds the mutex `Global\ArkRelayMain` while it runs. Console programs
  it starts get no window (`CREATE_NO_WINDOW` by default), so nothing pops up over the
  games. A logoff stops it; only a Windows shutdown counts as a power-off.
- The relay runs only while someone is logged on; the machine needs automatic logon to
  run unattended after a power-on (the watchdog pushes once after 15 minutes with
  nobody logged on).
- `ArkRelayWatchdog` checks for that mutex every 30 s. When it is gone and someone is
  logged on, the watchdog runs the task again. After 3 failed starts in a row, it pushes
  one line to the WeCom group bot (`WECOM_BOT_URL` in `.env`). Windows restarts the
  watchdog 3 s after it fails (`sc failure`).
- The relay guards the watchdog in turn (`relay/watchdog_guard.py`): 60 s after it starts
  and every 3 minutes, a watchdog that is stopped, on automatic start, and not stopped on
  purpose is started again; 3 failed starts in a row log one ERROR, which errwatch pushes
  to the group. Stopped on purpose = disabled (revert) or `C:\ProgramData\ark-relay\watchdog-stopped.txt`
  written since the last boot (by `switch.py stop` / revert / uninstall and `estop.sh`,
  deleted by every start of the watchdog there).

## Updates and rollback

At boot the relay copies its version folder, lets `selfupdate.check` bring the copy up
to the deployed manifest (only changed files are downloaded, as before), and switches
`current.txt` to it. The folder in use is never written to. The last 3 version folders
are kept. Each start sets selfupdate's recorded version to the running folder's, so a
failed switch, a rollback or an install over a newer old relay never leaves the record
ahead of the code. After a rollback the record stays at the version rolled away from
(`state\rolled-back-from.txt`), so the next start does not update straight back into
it; the next higher deployed version clears that. If `current.txt` names a missing folder, `launch.py` starts the
newest complete one.

    {app}\runtime\python\python.exe {app}\launch.py rollback   # back to the previous folder
    {app}\runtime\python\python.exe {app}\launch.py stop       # stop the relay
    {app}\runtime\python\python.exe {app}\switch.py stop       # stop the watchdog, then the relay

Installing an older installer over a newer updated version keeps the newer folder
current.

## The runtime

A relay deploy (`scripts/mac/deploy-relay.sh`) reads the machine's runtime - its Python
version and installed packages (`pkg_deploy.py info`) - and compares it with
`packaging/build.py` `PY_VERSION` and the Windows pins in `relay/requirements.txt`
(`scripts/mac/lib/pkg_appfiles.py runtime-gap`). The same: nothing is built, sent or run.
Different (a Python patch release, a package pin raised):

1. Before any code is pushed, the Mac builds the runtime as the installer would
   (`build.py --runtime-only`, with `~/.local/bin/python3.14`), sends it with a sha1 per
   file into `{app}\runtime\.incoming`, and the machine checks every file and runs the
   new `python.exe` (it must load Pillow and pywin32 and be the wanted versions;
   `pkg_deploy.py runtime-check`). Not so: the deploy stops, nothing changed (exit 5).
2. After the code is committed, right before the restart, `pkg_deploy.py runtime` runs
   on the new runtime's own `python.exe` (the relay and the watchdog hold the old one's
   DLLs, and Windows renames no folder a running program was loaded from): the new one
   copied to `runtime\python.next` while everything still runs, watchdog stopped (stop
   marker first), relay stopped (`launch.py stop`), nothing left running from
   `runtime\python`, then two renames back to back (`python` -> `python.prev`,
   `python.next` -> `python`), the new one probed again, the watchdog started on it. A
   failed step puts `python.prev` back.
3. The usual restart and watch follow, on the new runtime. Not steady: the runtime goes
   back (`runtime-back`), then the code (exit 12). Steady: `.incoming` is dropped;
   `python.prev` stays until the next runtime change.

By hand, back to the previous runtime: `switch.py stop`, rename `runtime\python` to
`runtime\python.failed` and `runtime\python.prev` to `runtime\python`, `switch.py start`.

## Uninstall

The uninstaller stops the watchdog and the relay, removes the service and the task,
removes what the relay left before it was packaged (`legacy.py remove`: the old
`ark-relay` service, its scheduled tasks, its files under `C:\ProgramData`, the file it
put into OK-WW), and deletes `{app}`. It asks before deleting `C:\ProgramData\ark-relay`.
A silent uninstall keeps that folder.
