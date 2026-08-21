# ark-relay

The notification relay. Runs on the game machine as the Windows service
`ark-relay`; zero dependencies beyond the standard library (pywin32 for the
service wrapper, already installed there).

```
failure   push once, after the retries settle, with a one-line plain diagnosis
recovery  push "recovered this time, problem not solved" - self-healing != fine
success   silent, recorded
daytime   one interim summary per round, manual rounds included, no quota used
evening   the daily report after the last round; resent next day if it never went
countdown every summary carries the event's remaining time, from MAA's own cache
no boot   NOT this machine's job - GitHub Actions + Tailscale lastSeen
```

[docs/NOTIFICATIONS.md](../docs/NOTIFICATIONS.md) is the authority on all of the
above.

## Modules

| File | Responsibility |
|---|---|
| `service.py` | Windows service host: process watch, alarm clock, inbox deferral |
| `core.py` | judgement - what happened, was it a failure, what is pending |
| `engine.py` | the round: reports, shutdown, catch-up, manual-round detection |
| `collector.py` | parse AUTO-MAS history records and MAA/MaaEnd logs |
| `watch.py` | directory-change notification (Windows ctypes / macOS kqueue) |
| `plan.py` | read AUTO-MAS's schedule; there is no second copy of it |
| `notify.py` / `transport.py` | channels and HTTP with the right retry policy |
| `summary.py` | wording, including the optional LLM line |
| `inbox.py` | fetch and apply `queue/config.json` |
| `selfupdate.py` | fetch and apply `relay/manifest.json` |
| `commands.py` | the command whitelist and its gates |
| `queues.py` / `modes.py` / `annihilation.py` / `sanity_plan.py` / `maaend.py` | config writers |

## Running it

```bash
python -m ark_relay check      # self-test
python -m ark_relay test       # send one test message
python -m ark_relay local      # foreground; production uses service.py
```

Configuration is environment variables or `relay/.env`; the list is in
[docs/CONFIG.md](../docs/CONFIG.md).

## Why there is no server

Server mode was retired on 2026-08-20. Every capability a cloud server had now
has an implementation that needs no server *and* no upload code on the machine -
which matters, because the machine cannot reach github.com or api.github.com at
the TCP layer at all.

| Old server feature | Replacement |
|---|---|
| boot / shutdown supervision | GitHub Actions reads Tailscale `lastSeen`. tailscaled connecting at boot and dropping at shutdown is a signal the machine already sends |
| heartbeat timeout alarm | none - by the 2026-08-18 decision there is no periodic heartbeat, only those two events plus scheduled checks |
| command queue from the phone | the inbox: edit `queue/config.json` in this repo, the machine fetches it at boot |
| collect, judge, push | local mode already did this |
| status web page | reports and alarms go to WeChat; the rest is the GitHub web UI |

## The four gates on commands

A model may only emit an **action name from this table**. It may never emit a
JSON patch.

| Action | Reversible | Needs confirmation |
|---|---|---|
| `run_now` | - | **not implemented; refuses explicitly** (an older version wrote a marker nothing consumed and reported success) |
| `skip_today` | yes | no - disables that queue for the day and restores it afterwards. Takes `"day":"YYYY-MM-DD"`; the inbox is only read at boot, so a stale one is refused rather than skipping the wrong day |
| `debug_mode` | yes, self-expiring | no - `days:N` or `off:true`; while active: no shutdown, no missed-run alarms |
| `set_stage` | no, writes config | **yes** |
| `set_medicine` | no, writes config | **yes** |
| `set_wait_time` | no, writes config | **yes** - 60-600 only, see [CONFIG.md](../docs/CONFIG.md) |
| `toggle_task` | no, writes config | **yes** - not implemented; refuses explicitly |

`sanity_plan`, `maaend_option` and `queue` are handled in `inbox.py` before the
whitelist, as all-or-nothing batches, because their fields depend on each other.

The confirmation gate exists for the model path. Commands arriving through the
inbox are confirmed by the act of editing the repo file, so `inbox.py` supplies
`confirmed: True` itself.

Applying any of them: back up → write → `json.loads` → structural diff → **roll
back unless added=0, removed=0 and changed matches expectation**. That gate has
caught one real incident already; see [PITFALLS.md](../docs/PITFALLS.md).

## The timezone contract

Three clocks are in play: server UTC+8, operator UTC+9, and whatever host the
code runs on.

1. **All judgement uses the server clock.** `SERVER_TZ` is a hardcoded UTC+8
   fixed offset and deliberately does **not** read the host's local timezone.
   09:00 and 21:30 are aligned to the smart plug, the BIOS wake and AUTO-MAS's
   timers, all of which run on that clock. So where the relay is deployed cannot
   change a verdict.
2. **Everything persisted is ISO 8601 with an offset** - `2026-08-14T09:00:12+08:00`,
   never a bare `09:00:12`. An absolute instant reads the same on any machine.
3. **Everything shown to a human names both clocks.** `both_clocks()` prints
   `09:00（东京 10:00）`.
4. **No bare `datetime.now()` anywhere.** Every call carries `tz=SERVER_TZ`.

Rule 4 is not fastidiousness - see [PITFALLS.md](../docs/PITFALLS.md), "Timing
and time zones".

## Where the model's authority ends

The LLM call in `summary.py` **only chooses words**. Whether a run failed, which
task failed, the stage, the drops, the sanity numbers, whether something is
overdue - all of that is decided by ordinary Python in `core.py` before the model
is asked anything.

An unreachable model, a timeout, or no key at all costs one sentence of prose.
The structured content is sent regardless.

## Verified against real records

```
MAA     ok=True   45 min   龙门币 x28800 · 技巧概要·卷2 x4 · 家具零件 x6
MaaEnd  ok=False  43 min   failed: protocol space, daily reward collection
idempotence: a repeat scan yields 0 records
whitelist:   'rm -rf /' refused / unconfirmed set_stage refused / bad stage code refused
```
