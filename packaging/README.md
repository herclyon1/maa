# Packaging the relay

The relay ships as a Windows installer built with Inno Setup (the tool AUTO-MAS uses
for its own installer). Everything the relay needs on the game machine is set up by
`ark-relay.iss`; reading that file tells you what is on the machine.

## Build

On Windows with Python 3.14.7 and Inno Setup 6:

    python packaging/build.py            # -> packaging/dist/ArkRelay-Setup-<version>.exe
    python packaging/build.py --stage-only

`relay/manifest.json` decides which relay files go in (the same set a deploy ships), so
regenerate it (`relay/make-manifest.py`) after adding or moving files.

## What gets installed

| Where | What | Changed by |
|---|---|---|
| `{app}\runtime\python` | embedded Python 3.14.7, Pillow, pywin32 (`relay/requirements.txt`) | installer only |
| `{app}\versions\<n>` | relay code, one folder per manifest version | installer, updater |
| `{app}\current.txt` | the version folder in use | installer, updater, rollback |
| `{app}\launch.py` | starts `versions\<current>\app_main.py` | installer only |
| `{app}\watchdog` | `ArkRelayWatchdog` service | installer only |
| task `\ArkRelay\main` | runs the relay at logon of the user at the console, highest privileges, no time limit, normal priority | installer |
| `C:\ProgramData\ark-relay` | `.env`, `state\` (update bookkeeping), `ark-state\` (the relay's own state unless `.env` sets `ARK_STATE_DIR`, as before), `relay.log`, `watchdog.log` | the relay; kept on uninstall unless the user says otherwise |

`{app}` is `C:\Program Files\ArkRelay`.

## Install and uninstall steps

The installer copies files and calls `switch.py`; the order of everything else is in
that one file:

- `switch.py install`:
  1. Stop and disable the old relay (`legacy.py takeover`).
  2. Hand AUTO-MAS the jobs it already does (`handover/automas_handover.py`: `plan`
     must pass, then `apply`).
  3. Register `\ArkRelay\main`.
  4. Register and start the watchdog.
  5. Start the relay.

  If step 2 fails, nothing new is registered and the old relay is switched back on.
  `/SKIPHANDOVER=1` on the setup command line skips step 2 (for the cloud test
  machine, which has no AUTO-MAS).
- `switch.py uninstall`:
  1. Stop the watchdog and the relay.
  2. Put back the AUTO-MAS settings the handover changed.
  3. Remove the version folders' `state` junctions.
  4. Unregister the service and the task.
  5. Remove the old relay's leftovers (`legacy.py remove`, from
     `handover/legacy-items.json`).

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

## Updates and rollback

At boot the relay copies its version folder, lets `selfupdate.check` bring the copy up
to the deployed manifest (only changed files are downloaded, as before), and switches
`current.txt` to it. The folder in use is never written to. The last 3 version folders
are kept. Each start sets selfupdate's recorded version to the running folder's, so a
failed switch, a rollback or an install over a newer old relay never leaves the record
ahead of the code. If `current.txt` names a missing folder, `launch.py` starts the
newest complete one.

    {app}\runtime\python\python.exe {app}\launch.py rollback   # back to the previous folder
    {app}\runtime\python\python.exe {app}\launch.py stop       # stop the relay
    {app}\runtime\python\python.exe {app}\switch.py stop       # stop the watchdog, then the relay

Python, Pillow and pywin32 change only with a new installer. Installing an older
installer over a newer updated version keeps the newer folder current.

## Uninstall

The uninstaller stops the watchdog and the relay, removes the service and the task,
removes what the relay left before it was packaged (`legacy.py remove`: the old
`ark-relay` service, its scheduled tasks, its files under `C:\ProgramData`, the file it
put into OK-WW), and deletes `{app}`. It asks before deleting `C:\ProgramData\ark-relay`.
A silent uninstall keeps that folder.
