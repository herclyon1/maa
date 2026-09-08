# Procedure for changing the game machine's configuration

**This document exists for a new session to follow step by step.** Not following it is how 826
happens again.

What happened on 826: I **invented the meaning of a field** and then changed production config
with it, which farmed the wrong stage and burned sanity potions — and not one of my abort
attempts took effect. The lesson is not "be careful", it is that not a single step below may be
skipped.

## Hard rules

1. **A field's meaning may only be confirmed from an authoritative source; it must not be
   inferred.** Lining fields up by position is guessing, and guessing right is more dangerous
   than guessing wrong.
2. **Before asserting anything about the configuration, run `scripts/mac/config-check.py` and
   paste its output, then draw the conclusion.** Not from memory, and not from "I just changed
   it myself".
3. **Change the JSON, not the UI.** The UI is only for what the JSON cannot do.
4. **After changing, read it back — and verify "is this value the thing I think it is"**, not
   merely "did the value get stored".
5. **Never change the configuration while a script is running.** While AUTO-MAS is running it
   overwrites the file from its own in-memory copy, and whatever was written is silently wiped.

## Before changing

```bash
export ARK_HOST=100.65.39.119
scripts/mac/config-check.py --save     # take a snapshot first, so --diff works afterwards
```

Confirm three things:

* **Whether you are changing the master or a copy.** AUTO-MAS rewrites MAA's and MaaEnd's own
  configuration before every run, so **changing their own config files changes nothing while
  looking like it did**. The authority lives under `AUTO-MAS/config/`: global `Config.json`,
  queues `QueueConfig.json`, per-user `ScriptConfig.json`.
* **Whether a script is running.** If one is, wait — or go through
  `scripts/mac/mas-api.py`, which writes through the running backend and therefore cannot be
  wiped by the in-memory copy.
* **What this field actually means.** See "Fields known to bite" below.

## While changing

Two routes, pick by situation:

* **Through the API (recommended, no need to stop the program)**

  ```bash
  scripts/mac/mas-api.py paths                 # see which endpoints exist first
  scripts/mac/mas-api.py get /api/scripts/get
  ```

  Note: **every endpoint is POST**. GET returns Method Not Allowed, including on read endpoints.

* **Editing the JSON directly (AUTO-MAS must be stopped first)**

  Pull it down → edit → use `scripts/mac/edit-json.py` for a **structured diff** proving that
  only the keys that should have changed did → atomic write-back → read back.
  Never run a regex replace over a whole file.

## After changing

```bash
scripts/mac/config-check.py --diff      # shows only what changed, against the before snapshot
```

Then **watch one real run**; do not stop at "the config was written".

## Fields known to bite

| Field | Where it bites |
|---|---|
| Stage index | **Counts from 1**, not from 0. This is exactly what 826 died on |
| Sanity potions | There are two of them: the regular one and the event-stage one (`活动关理智药`). Changing the wrong one is the same as changing nothing |
| Event stages such as AT-4 | The stage stops existing the moment the event ends, and a fixed-stage config pointing at it makes every later run fail. Either change it back before the event ends, or turn on 「优先刷取活动关」 |
| `Info.IfQuickConfig` | AUTO-MAS only rewrites downstream configuration when this is true. **On this machine: MaaEnd and OK-WW are both false (since 2026-08-28), so changing them on the MAS side has no effect — change the master instead; 明日方舟 has no such switch, so going through MAS is correct for it.** To see the effective value, run `scripts/mac/lib/effective_config.py` |
| MaaEnd sanity tasks | The authority is AUTO-MAS's `ScriptConfig`, not MaaEnd's own `mxu-MaaEnd.json` — the latter gets overwritten |
| 剿灭 `Close` | It means both "already done this week" and "somebody turned it off". Nobody turns the latter back on automatically, which costs one reward every week |

## If what you need to change is not listed above

**Go look it up; do not guess.** If you cannot find it, ask the operator; inferring a meaning by
"lining fields up by position" is not allowed. There is no exception to this rule — 826 is what
the exception costs.
