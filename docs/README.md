# Documentation index

Six documents and one list. One line each, saying which question that document answers.

Rule: **a newly added document must be registered here**; gate 12 of
`scripts/mac/lint-repo.sh` checks it. A document with no entry point does not
exist - the next session will never read it, so writing it was wasted.

On 2026-11-17 the other 48 documents (dated surveys, plans, per-game notes, the phone
page's writing rules) were removed together with the phone page `web/`. They are in git
history: `git show 1c8b5828:docs/<NAME>.md`, and `git show 1c8b5828:docs/README.md` for the
index as it was. Comments in the code and the tests still point at some of them by name
(PITFALLS.md, CODE-HISTORY.md, STATE-MODEL.md, SKLAND-API.md, ...); read those from history.

## The documents

| Document | Question it answers |
|---|---|
| [../CLAUDE.md](../CLAUDE.md) | Standing orders, the tool table; read this before every session |
| [OPERATIONS.md](OPERATIONS.md) | The operations master document: the schedule, power on/off, diagnostic paths |
| [NOTIFICATIONS.md](NOTIFICATIONS.md) | Which notifications exist, when they are sent, what they look like |
| [CONFIG.md](CONFIG.md) | The config inventory: environment variables, each program's settings, and which copy actually takes effect |
| [AUTOMAS.md](AUTOMAS.md) | AUTO-MAS: its screens, its configuration, and driving it without a UI |
| [BACKLOG.md](BACKLOG.md) | Things promised and not yet done |

`UNMERGED-REVIEWED.txt` is the list `scripts/mac/deploy-relay.sh` step 0.6 reads
(`scripts/mac/lib/unmerged_fixes.py`): relay fixes on a branch that were looked at and are
not going into main.

## Scripts with no other entry point

Gate 12 also wants every `scripts/mac/*.sh`, `scripts/windows/*.py` and `scripts/windows/*.bat`
named in `CLAUDE.md` or here. These were named only in documents that are gone:

| Script | What it does |
|---|---|
| `scripts/mac/confirm-off.sh` | Is the game machine powered off right now: prints measured evidence, not Tailscale's opinion |
| `scripts/mac/pull-day.sh` | Pulls the game machine's record of one Beijing day and cuts it into the day-replay corpus (`relay/tests/daysim`) |
| `scripts/mac/pull-replay.sh` | Pulls one day's AUTO-MAS run records back as a replay sample (redacted, with a draft `expected.json`) |
| `scripts/windows/smoke.py` | The deploy's smoke test on the machine: imports every relay module with the machine's Python and reads back the log the service wrote after its restart, before "deployed" is printed |
| `scripts/windows/copilot-run.py` | Runs a MAA copilot (auto-battle) file through MaaCore without the GUI |
| `scripts/mac/make-stream-apps.sh` | Builds the desktop streaming launchers from `lib/moonlight-params.sh` (lint gate 17 checks they are current) |
| `scripts/mac/make-cloud-genshin-app.sh` | Builds `~/Desktop/云原神.app` (turns WARP on, opens the cloud-game page) |
| `scripts/mac/cn-route-pf.sh` | `sudo ... on / off / status`: rewrites the source address of UDP to Chinese ranges so it goes through the Tailscale tunnel |
| `scripts/mac/proxy-monitor.sh` | Shows whether cloud Genshin's traffic goes through the ins tunnel while the game is running |
| `scripts/mac/check-shell.sh` | Checked the phone page's shell stamp (`index.html` / `sw.js`); the page is gone, the script is left for whoever decides its fate |
