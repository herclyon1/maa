# Documentation index

Rule: **a newly added document must be registered here**; gate 12 of `scripts/mac/lint-repo.sh` checks it.

## Documents

| Document | Question it answers |
|---|---|
| [../CLAUDE.md](../CLAUDE.md) | Standing orders and the active tool table |
| [OPERATIONS.md](OPERATIONS.md) | Schedule, power on/off, and diagnostic paths |
| [NOTIFICATIONS.md](NOTIFICATIONS.md) | Notification titles, channels, and triggers |
| [CONFIG.md](CONFIG.md) | Environment variables and effective config locations |
| [AUTOMAS.md](AUTOMAS.md) | AUTO-MAS configuration and API reference |
| [BACKLOG.md](BACKLOG.md) | Tracked follow-ups |

`UNMERGED-REVIEWED.txt` lists branch commits reviewed for `scripts/mac/deploy-relay.sh` step 0.6 (`scripts/mac/lib/unmerged_fixes.py`).

## Machine-side entry scripts (`scripts/windows/`)

| Script | Role |
|---|---|
| `scripts/windows/deploy.py` | Places an Arknights operator through MaaTouch (press, drag, release, flick), which `adb shell input` cannot do: `deploy.py <card x> <card y> <tile x> <tile y> <up\|down\|left\|right>`, `--probe` to only hold; run with `winrun.sh --py` |
| `scripts/windows/deploy_watch.py` | Watches `relay.log` after restart to confirm boot self-check passes |
| `scripts/windows/dispatch_guard.py` | The gate behind `run-one.sh`: dispatches one script only when nothing is running, and stops in order (API, wait, kill leftovers, re-check) |
| `scripts/windows/machinecheck_wait.py` | Waits for machinecheck rows to settle after deploy |
| `scripts/windows/okww-landed.py` | Verifies OK-WW settings took effect (`okww-check.sh`) |
| `scripts/windows/pkg_deploy.py` | Stages version folders for installed relay (`scripts/mac/lib/deploy-pkg.sh`) |
| `scripts/windows/run-probe.py` | Live run probe on the game PC (`watch-run.sh`) |
| `scripts/windows/set_maa_os4_medicine999.py` | Hardlock-gated AUTO-MAS MAA config switcher for `OS-4` + `MedicineNumb=999` (`--check` read-only default `0/2`, `--apply` refuses under `HARDLOCK.json` with `RC=4`, otherwise backs up, writes via API and verifies all 8 fields) |
| `scripts/windows/skip-shutdown.bat` | Desktop toggle writing `skip_next_shutdown` into `StateStore` |
| `scripts/windows/smoke.py` | Post-deploy import and boot-line smoke check on the game PC |
