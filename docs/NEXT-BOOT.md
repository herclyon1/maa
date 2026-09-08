# Open items

**Read this first thing after the machine boots**, and delete each item once it is handled.
Long-running work lives in [BACKLOG.md](BACKLOG.md); settled limits nobody intends to change
live in [OPERATIONS.md](OPERATIONS.md).

## Deploy the banners split (2026-09-08)

`banners.py` was split into a facade plus four per-game modules, verified byte-identical
function by function, and then **reverted from main** the same evening: self-update never
creates files, so pushing it would have written the edited importer without the modules it
imports and left the relay dead on ModuleNotFoundError with the version stamped as current.
(The abort-on-missing-file guard that stops that class of accident is now on the machine, so
a repeat would be loud instead of fatal.)

The split itself is finished and green - it was not deployed on the night of 09-08 only
because the machine boots at 21:20 and powers off after the evening queue, and a refactor
with no user-visible effect is not worth keeping it running for.

To land it: restore commit `1cf0e67`'s versions of `relay/ark_relay/banners*.py`,
`relay/tests/test_banners.py`, `scripts/mac/lib/loggernames.py` and `relay/README.md`
(the four modules are also parked in this session's scratchpad), regenerate the manifest,
then `ARK_HOST=... scripts/mac/deploy-relay.sh` - **deploy, not self-update**, because only
deploy can create files. Do it early in a boot window, not minutes before a queue.

## ~~Evening run finished but the machine never shut down (2026-09-04)~~ explained

**Cause: I set "skip the shutdown this once" and forgot to cancel it when the work was done.**
Relay log:

```
09-03 21:46:32  ⏸ 有人按了「这次别关机」，本次关机已跳过
09-04 21:55:35  ⏸ 有人按了「这次别关机」，本次关机已跳过
```

That switch eats the **next** shutdown opportunity and **never expires**. It was set in the
afternoon to run an event stage, and only got consumed at 21:55 when the evening run finished,
so the machine stayed up all night for nothing. Two days in a row, same cause.

Two other explanations ruled out:
* Not `_last_round_manual` ("the last round was triggered manually") — that only fired at 12:56 that day.
* Nothing pressed the switch automatically — the desktop `中继关机开关.bat` is a purely
  interactive menu, and no scheduled task or startup item calls it. It **writes the file
  directly without going through the relay, so it leaves no log entry**; finding no "who set it"
  record in the log is expected, not evidence.

The rule is recorded in memory `skip-shutdown-must-be-cancelled`: before signing off, check the
`modes` section of `state/state.json` — it is only clean when neither `skip_next_shutdown` nor
`debug_until` is present.
(Before the 2026-09-08 state consolidation these two were separate files,
`skip-next-shutdown.flag` and `debug-until.txt`. Those files no longer exist, so checking the
old ones reads as "everything is clear" when it is not.)

## After the 2026-09-07 boot

- [x] **Deploy the relay by hand** (deployed several times since 09-07, each time reading the
      hash back to verify; the okww_patches patches are all in place in the log's "启动：" lines)
      ~~original~~: **Deploy the relay by hand** (`ARK_HOST=100.65.39.119 scripts/mac/deploy-relay.sh`):
      the 09-06 night split added handle/missed/report/shutdown and okww_patches/, and self-update
      does not pick up new files. Do it after the 09:00 queue starts, not during the 08:45–09:00
      pre-update window. After deploying, check relay.log for "这一段出错" and confirm the
      `okww_patches` patches were applied (the "启动：" lines in the log).
- [x] 09:00 morning run: essence farming at 清波寨 280→40, three runs in a row, one success.
      This morning's pre-update raised MaaEnd to v2.28.0-beta.1 and OK-WW to v3.6.7-beta.2,
      with no false alarms.
