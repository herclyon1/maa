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
| task `\ArkRelay\main` | runs the relay at logon, highest privileges, no time limit | installer |
| `C:\ProgramData\ark-relay` | `.env`, `state\`, `relay.log`, `watchdog.log` | the relay; kept on uninstall unless the user says otherwise |

`{app}` is `C:\Program Files\ArkRelay`.

## How it runs

- `\ArkRelay\main` starts `launch.py` at logon. The relay (`relay/app_main.py`) runs the
  same boot sequence and loop as the old service, in the user's session, so it can see
  the desktop. It holds the mutex `Global\ArkRelayMain` while it runs.
- `ArkRelayWatchdog` checks for that mutex every 30 s. When it is gone and someone is
  logged on, the watchdog runs the task again. After 3 failed starts in a row, it pushes
  one line to the WeCom group bot (`WECOM_BOT_URL` in `.env`). Windows restarts the
  watchdog 3 s after it fails (`sc failure`).

## Updates and rollback

At boot the relay copies its version folder, lets `selfupdate.check` bring the copy up
to the deployed manifest (only changed files are downloaded, as before), and switches
`current.txt` to it. The folder in use is never written to. The last 3 version folders
are kept.

    {app}\runtime\python\python.exe {app}\launch.py rollback   # back to the previous folder
    {app}\runtime\python\python.exe {app}\launch.py stop       # stop the relay

Python, Pillow and pywin32 change only with a new installer. Installing an older
installer over a newer updated version keeps the newer folder current.

## Uninstall

The uninstaller stops the watchdog and the relay, removes the service and the task,
removes what the relay left before it was packaged (`legacy.py remove`: the old
`ark-relay` service, its scheduled tasks, its files under `C:\ProgramData`, the file it
put into OK-WW), and deletes `{app}`. It asks before deleting `C:\ProgramData\ark-relay`.
A silent uninstall keeps that folder.
