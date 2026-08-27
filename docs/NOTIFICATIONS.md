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

Kind 2 exists only while the system is under test: set `ARK_INTERIM_REPORT=0`
to stop it once the daily report alone is trusted. Turning it off must not
affect kind 1, which is why it is its own switch - `ARK_REPORT_BEFORE_SHUTDOWN`
governs a different thing, the backstop that fires from inside the shutdown path
when the interim never got delivered.

Kind 2 is not sent on a timer: the morning round powers off seconds after
finishing, so a timer would have to fire inside a moving window between
"finished" and "off". Reporting when the round completes is deterministic.

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
| **Relay code updated** | push the moment the new code is actually running - version before and after, and which files changed |
| **Relay code update failed** | push why, which files did not land, and that the machine is still on the old version |
| A notification channel is broken | alarm over whatever channel still works, **once per fault**. The record is on disk, so a relay restart does not re-announce it; it clears when the channel works again or the fault changes |
| MaaEnd updated itself | **not pushed** - the beta channel ships most days, so a notice per update is a daily message with nothing to act on. Log only |

## Updates must land at boot, and must announce themselves

Two rules, both given by the operator on 2026-08-21.

**At boot, never at the end of a queue.** The machine powers on at 21:20 and
the queue starts at 21:30; the relay is up a minute or two after boot, so
roughly eight of those ten minutes are usable and they exist for exactly this.
The morning gap is the same shape: power at 08:45, queue at 09:00. An update
applied after the run would sit unused until the next boot, and a command that
needs it could not be understood in the meantime. `service.py` runs selfupdate
at service start, before the inbox, and restarts itself immediately so the new
code is live before the queue fires.

**Announce the moment it takes effect** - code updates as well as config ones.
The process that applies a code update is still running the old code and is
about to replace itself, so it cannot be the one to report. It records what it
did, and the process that comes up on the new code sends the notice. That way
the message means "the new code is running", not "the files were written".

The first update after this shipped is a special case: the code that applies it
predates the feature and leaves no record. So the notice is also derivable from
the applied version alone, compared against the last version announced.

**A failed update is announced as loudly as a successful one.** An update that
was available and did not land leaves the machine running old code while
everything upstream assumes the push took effect - the same trap as an scp that
returns 0 without transferring, and the reason `deploy-relay.sh` verifies
hashes. The notice says why it failed, which files did not land, and that the
machine is still on the previous version. It repeats on every boot until an
update succeeds, because the machine boots twice a day and an unfixed channel
should keep saying so.

## Shutdown

- The relay powers the machine off after the queue has finished **and** the
  report has been delivered. This is the design and it stays.
- **Nothing else powers the machine down without an explicit instruction.**
  An unrequested manual shutdown on 2026-08-20 left the machine unreachable
  while a config still needed restoring. The relay's own post-run shutdown is
  the only automatic one.

## Only the relay pushes. Nothing else. Ever.

This is the design, stated by the operator and predating everything else on
this page: **MAA and AUTO-MAS never notify anyone directly.** They produce run
records; the relay reads those records, decides what is worth saying, and says
it. That is the whole reason the relay exists.

So every push switch in every profile of every downstream program is off, and
stays off. There is no "but this one goes to the other person" exception - the
other person is inside this system too, and a direct push from MAA bypasses all
of it: the retry logic that suppresses a first failure, the daily grouping, the
countdown, the one-channel-is-enough delivery rule.

Getting this wrong on 2026-08-22 cost three junk notices to the operator's
phone. Worse was the reasoning: MAA's second profile was left pushing because
its Server酱 key differed from the first, so its messages "went to someone
else". That was answering a question about configuration when the question was
about design. When a config looks like it might be someone else's business,
ask what the system was supposed to do - do not infer the intent from the
config, which is exactly the artefact that may be wrong.

## Channels

| Channel | State |
|---|---|
| Server酱 (`sctapi.ftqq.com`) | **carrying everything** |
| WeCom self-built app | **down**: `errcode=60020`, the home IP is not in the trusted list |
| WeCom group bot (`WECOM_BOT_URL`) | not configured; has no trusted-IP list, so it would survive a changing home IP |

MAA's and AUTO-MAS's own direct pushes are all off - both would reach the same
WeChat, so leaving them on delivers everything twice. When WeCom comes back,
expect duplicates until one channel is muted.

Server酱 has two product lines with different key prefixes - `SCT...` is Turbo,
`sctp...` is Server酱³ - and `notify.py` handles both, sending everything to
`sctapi.ftqq.com` (the per-uid `{uid}.push.ft07.com` host that Server酱³
documents returns 403 for this key and is not a usable fallback). Which line
this deployment's key belongs to is not recorded here; the key lives only in
`relay/.env` on the machine.

Delivery rule: **one channel delivering counts as delivered.** See
[PITFALLS.md](PITFALLS.md) for why that sentence exists.

### One channel by default, every channel for alerts

Dictated by the operator on 2026-08-24, after a report arrived twice:

> 中继也不要同时发两边通知，只允许在一侧不通的时候采用另一侧……除了报警之外
> （报警的时候用双通道全发），其他时候都默认走一个通知。

| Kind | Channels |
|---|---|
| **Alert** - 漏跑、缺项、脚本出错、自愈、中继自更新失败、目录监听掉线、AUTO-MAS 拉不起来、通道故障公告、`ark-do selftest` | **every** enabled channel |
| **Everything else** - 日报、临时查看、手动执行、预更新、剿灭、待办、跳过模式 | **one**, first that accepts |

Routine order is **Server酱 → WeCom group bot → WeCom app**, and a later channel
is attempted *only* when the one before it raises. Server酱 leads because it has
no trusted-IP list and the operator reports it has never once failed; WeCom sits
behind consumer broadband whose rotating IP triggers `60020` outright.

In code this is `Notifier.send(..., alert=True)`. The default is routine, so a
new call site is quiet by default and has to opt in to waking someone up.
`relay/tests/test_notify_routing.py` pins both paths.

Why not "send everywhere, it's safer": a daily report landing on the phone twice
is noise, not redundancy, and noise is what gets real alerts ignored. Redundancy
earns its cost on alerts, where a dead channel must not swallow the message -
that reasoning is in `Notifier`'s class docstring and stays true there.

`scripts/mac/push.py` on the Mac follows the same rule and the same order, with
`--all` to override.
