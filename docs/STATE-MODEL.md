# Relay state: one file, one field table (root fix #3, closed out 2026-09-08)

## Before the cleanup: 35 kinds of file scattered under `state/`, each module reading and writing its own

| Category | Files | Written by | Read by | After the cleanup |
|---|---|---|---|---|
| One-shot marks for the day | `report-{day}.sent`, `interim-{day}.sent`, `banner-{key}.sent`, `alerted-{day}.json`, `hb-{day}.txt`, `tacet-shots-{day}.sent` | report / handle / banners / phone | same, plus shutdown | `marks` section: `{"report:2026-09-07": "<timestamp>"}` |
| Switches and modes | `skip-next-shutdown.flag`, `shutdown-skipped.txt`, `debug-until.txt`, `skip-{day}.flag`, `skip-restore.json`, `queue-skips.json`, `gameupdate-off.flag`, `maintenance-today.json` | modes / commands / phone | shutdown / engine / phone | `modes` section |
| The three weekly gates | `annihilation.json`, `garden.json`, `weeklyboss.json` | the three gates | phone / service (a new week) | `weekly` section, all three the same shape |
| Version bookkeeping | `code-version.txt`, `okww-version.txt`, `maaend-version.txt`, `inbox-version.txt`, `announced-version.txt` | selfupdate / okww_patch / preupdate / inbox | same | `versions` section |
| Update flow | `preupdate.json`, `gameupdate.json`, `gameupdate-pending.json`, `arknights-client.json`, `maaend-collect-routes-off.json`, `maaend-disabled-for-1.5.3.json` | preupdate / gameupdate | same | `updates` section |
| Alert queues | `pending.json`, `resume-ids.json`, `seen.txt`, `phone-seen.json` | handle / inbox / phone | same | `queues` section |
| Ledgers and evidence (stay as files) | `ledger-{day}.jsonl`, `evidence/`, `apk/`, `desktop/`, `shot-*.png`, `req/res-*.json`, `relay.lock`, `agent.*` | - | - | untouched: append-only / binary / locks |

The problem was never the number of files, it was that **there was no field
table**: the phone page, the daily report and the shutdown decision each went
off to read their own handful of files, and one file written late produced one
false state (the 2026-09-07 "Weekly Boss already done this week" being false is
exactly how it happened).

## Design

* `ark_relay/statestore.py`: `StateStore(state_dir)`, one file on disk,
  `state/state.json`, written atomically (temp file + replace), the whole thing
  rewritten on every change; cached by mtime on read.
  Five sections: `marks / modes / weekly / versions / updates / queues`, with
  every key registered in the field table in this file (name, type, who writes
  it, who reads it, when it is cleared). **A key that is not registered cannot
  be written** (the same rule as the phone page's `set_config`, which only
  changes fields that already exist).
* The existing `State`, `modes.*`, the three gates, `preupdate.should_run/mark_run`,
  `gameupdate.pending` and similar interfaces **stay unchanged**; only the file
  reads and writes inside them become store calls - not one line changes at the
  call sites.
* Migration: on first start, if `state.json` does not exist, read the old files
  from the table above to build it, then rename the old files to `.migrated`;
  delete them after three clean days.
* The phone page's `state_payload` carries the `weekly / modes / versions`
  sections through as they are, so what the page shows is the same data the
  relay decides on.

## Order

1. `statestore.py` + the field table + tests (atomic write, unregistered key
   rejected, migration).
2. Move the three weekly gates onto the store (their shape is already uniform,
   so this is the easiest).
3. The day's marks and switches (report/interim/skip/debug).
4. Version bookkeeping and the update flow.
5. Alert queues.
After each step, deploy and check on the machine that `state.json` and the phone
page agree.

## Done (2026-09-08)

`ark_relay/statestore.py`: `state/state.json`, six sections, only keys
registered in the `FIELDS` field table can be written. Already moved in:

* `weekly`: Annihilation, Weekly Garden, Weekly Boss
* `marks`: daily report, interim report, banner announcements (per day / per
  banner, wildcard keys)
* `modes`: skip the next shutdown, the shutdown opportunity that was eaten,
  debug-mode expiry
* `versions`: OK-WW, MaaEnd, code version, and `scoreboard` — how many runs each
  code version has served and how many of them failed. The daily report ends with a
  line built from it, so a claim of "fixed" can be checked against the machine's own
  count rather than against what I wrote in the report (user's order, 2026-09-06).
* `updates`: pre-update bookkeeping, game-update bookkeeping, pending-update
  registration, the master switch, the Arknights client version, the queue
  entries removed for an update, today's maintenance window
* `queues`: alerts waiting to be pushed, phone-command deduplication, the
  to-do version, skip mode's restore marks and the day's skips

**Second batch, completed 2026-09-08**: the `updates` section gained three more
records of MaaEnd tasks temporarily switched off (`maaend_disabled_1_5_3` /
`maaend_reenable_next_boot` / `maaend_disabled_spmed`), and the `queues` section
gained `channels_down`. When moving these three, both the read side and the
write side must change together - the sweep renames the old file to `.migrated`,
so adding a migration without changing the read means the record can never be
read again and those daily items stay switched off with nobody knowing.

**Deliberately left as files**: `ledger-*.jsonl` (append-only), `seen.txt`
(append-only and grows large), `evidence/`, `apk/`, `desktop/`, `shot-*.png`,
`req/res-*.json` (binary or transfer artefacts), `relay.lock` (a lock),
`agent.*` (scripts other processes have to read), `hb-*.txt` (heartbeat, written
far too often), `asar-labels.json` (a pure cache - derived data, not state; it
rebuilds itself if lost).

Nothing bypasses StateStore any more.

Migration is automatic: when `state.json` does not exist the old files are read
in and then renamed `.migrated`, and kept. Tests are in
`tests/test_statestore.py`.
