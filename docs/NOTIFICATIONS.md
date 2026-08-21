# Notification model (authoritative)

Dictated by the operator on 2026-08-20 and read back for confirmation on the
spot. **This page defines the required behaviour.** Where code or any other
document disagrees, this page wins and the code is a bug.

## Three kinds of summary

| # | Name | When | Title |
|---|---|---|---|
| 1 | **Daily report** | after the evening queue finishes, once a day | `📋 08-20 · 全绿 ✅` |
| 2 | **Interim look** | after a daytime queue finishes | `🔎 08-20 · …（临时查看）` |
| 3 | **Manual run** | after a hand-triggered queue finishes | `🔎 08-20 · …（手动执行）` |

They do not consume or cancel each other:

- An interim look or a manual run never uses up the day's daily report. The
  evening report still goes out (`send_daily_now(mark=False)`).
- However many daytime rounds run, that many interim messages go out - one per
  round, not one per day.
- A hand-triggered catch-up round sends its own message, explicitly labelled as
  manual.

Kind 2 exists only while the system is under test (`ARK_REPORT_BEFORE_SHUTDOWN=1`).
Turning it off must not affect kind 1. It is not sent on a timer: the morning
round powers off seconds after finishing, so a timer would have to fire inside a
moving window between "finished" and "off". Sending immediately before shutdown
is deterministic.

## Every summary must carry

- Stage, drops, sanity, start and end times - **both clocks**, server and Tokyo.
- **Time remaining on the current event, with a countdown**, read from MAA's own
  `cache/gui/StageActivityV2.json`.
  - under 36 hours: prefix ⚠️
  - event already over while the stage is still the event stage: say plainly
    that the next round will fail and the stage must be changed now
- Tomorrow's plan: what will run, which stage, how sanity will be spent.

## Immediate notifications (not summaries, not bound by the rules above)

| Event | Behaviour |
|---|---|
| Task failed | push once, after all retries have finished, with a plain-language diagnosis |
| Recovered on retry | push "recovered this time, problem not solved" - self-healing is not the same as fine |
| Task succeeded | **silent**, recorded only |
| Should have run and did not / something missing | alarm immediately |
| Config command applied | push a receipt: inbox version, name, note, and what changed in plain language |
| A notification channel is broken | alarm over whatever channel still works (e.g. WeCom `60020` with the current egress IP) |

## Shutdown

- The relay powers the machine off after the queue has finished **and** the
  report has been delivered. This is the design and it stays.
- **I must never shut the machine down without an explicit order from the
  operator.** On 2026-08-20 I did, and then could not reach the machine to
  restore a config. The relay's own post-run shutdown is the only exception.

## Channels

| Channel | State |
|---|---|
| Server酱 (`sctapi.ftqq.com`, `SCT...` Turbo key) | **carrying everything** |
| WeCom self-built app | **down**: `errcode=60020`, the home IP is not in the trusted list |
| WeCom group bot (`WECOM_BOT_URL`) | not configured; has no trusted-IP list, so it would survive a changing home IP |

MAA's and AUTO-MAS's own direct pushes are all off - both would reach the same
WeChat, so leaving them on delivers everything twice. When WeCom comes back,
expect duplicates until one channel is muted.

Delivery rule: **one channel delivering counts as delivered.** See
[PITFALLS.md](PITFALLS.md) for why that sentence exists.
