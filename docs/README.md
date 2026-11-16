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

## Internal Windows / CI entry scripts

| Script | Role |
|---|---|
| `scripts/windows/deploy.py` | Unpacks and verifies legacy relay tar streams during `deploy-relay.sh` |
| `scripts/windows/deploy_watch.py` | Watches `relay.log` after restart to confirm boot self-check passes |
| `scripts/windows/dispatch_guard.py` | Busy/idle guard shared by `run-one.sh`, `okww-task.sh`, and `estop.sh` |
| `scripts/windows/machinecheck_wait.py` | Waits for machinecheck rows to settle after deploy |
| `scripts/windows/okww-landed.py` | Verifies OK-WW settings took effect (`okww-check.sh`) |
| `scripts/windows/pkg_deploy.py` | Stages version folders for installed relay (`deploy-pkg.sh`) |
| `scripts/windows/run-probe.py` | Live run probe on the game PC (`watch-run.sh`) |
| `scripts/windows/skip-shutdown.bat` | Desktop toggle writing `skip_next_shutdown` into `StateStore` |
| `scripts/windows/smoke.py` | Post-deploy import and boot-line smoke check on the game PC |
