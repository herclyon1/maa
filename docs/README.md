# Documentation index

40 documents, grouped by "what are you trying to do right now". One line each,
saying which question that document answers.

Rule: **a newly added document must be registered here**; gate 13 of
`scripts/mac/lint-repo.sh` checks it. A document with no entry point does not
exist - the next session will never read it, so writing it was wasted.

## Read before starting work

| Document | Question it answers |
|---|---|
| [../CLAUDE.md](../CLAUDE.md) | Standing orders, the tool table; read this before every session |
| [MAINTENANCE.md](MAINTENANCE.md) | How to deploy, how to change config, what to run before committing |
| [TOOLING.md](TOOLING.md) | The rules for using the tools; the 21 pitfalls dug up on 826 |
| [PITFALLS.md](PITFALLS.md) | Pitfalls already fallen into and the shape they have now (the longest one; search it first when something breaks) |
| [RETROSPECTIVE.md](RETROSPECTIVE.md) | The mistakes made, and the gates that now stop them |
| [UPSTREAM-ISSUE-RULES.md](UPSTREAM-ISSUE-RULES.md) | Read before filing an issue / PR upstream |

## Daily operations

| Document | Question it answers |
|---|---|
| [OPERATIONS.md](OPERATIONS.md) | The operations master document: the schedule, power on/off, diagnostic paths (the most complete, and the longest) |
| [ESTOP.md](ESTOP.md) | The red button: stop everything on the game machine in one command |
| [CHANGE-CONFIG.md](CHANGE-CONFIG.md) | The procedure for changing the game machine's config (which copy to edit, how to verify) |
| [STATE-MODEL.md](STATE-MODEL.md) | Where the relay keeps its state, and what each key means |
| [NOTIFICATIONS.md](NOTIFICATIONS.md) | Which notifications exist, when they are sent, what they look like |
| [GAME-UPDATE.md](GAME-UPDATE.md) | What happens on a day a game client takes a major version update |
| [NEXT-BOOT.md](NEXT-BOOT.md) | Things not yet figured out |
| [BACKLOG.md](BACKLOG.md) | Things promised and not yet done |

## Configuration and interfaces

| Document | Question it answers |
|---|---|
| [CONFIG.md](CONFIG.md) | The config inventory: environment variables, each program's settings, and which copy actually takes effect |
| [AUTOMAS.md](AUTOMAS.md) | AUTO-MAS: its screens, its configuration, and driving it without a UI |
| [HEADLESS.md](HEADLESS.md) | How all three programs run with no UI at all |
| [SKLAND-API.md](SKLAND-API.md) | The 森空岛 API (终末地) |
| [BANNER-SOURCES.md](BANNER-SOURCES.md) | Where the banner data comes from |

## Knowledge specific to each of the three games

| Document | Question it answers |
|---|---|
| [GAME.md](GAME.md) | Knowledge common to all three games |
| [MAA-EVENTS-AND-SSS.md](MAA-EVENTS-AND-SSS.md) | 明日方舟: how to configure event stages and 保全派驻 |
| [MAA-INFRAST-ZOOM.md](MAA-INFRAST-ZOOM.md) | 明日方舟: why the infrastructure 「双指滑动到总览」 gesture fails |
| [ENDFIELD-GUIDES.md](ENDFIELD-GUIDES.md) | 终末地: external reference sources (look here first when you do not know something) |
| [ENDFIELD-ITEMS.md](ENDFIELD-ITEMS.md) | 终末地: item ids, Chinese names, what they are for |
| [ENDFIELD-STOCKPILE.md](ENDFIELD-STOCKPILE.md) | 终末地: how much a full set of upgrade materials costs, and how much to stockpile |
| [ENDFIELD-ACTIVITIES.md](ENDFIELD-ACTIVITIES.md) | 终末地: the activity centre |
| [MAAEND-TRIAL-SWORDMANCY.md](MAAEND-TRIAL-SWORDMANCY.md) | 终末地: why 选剑演武 fails |
| [WUWA-DAILY.md](WUWA-DAILY.md) | 鸣潮: every step of the daily run, from power-on to finish |
| [OKWW-WEEKLY-BOSS.md](OKWW-WEEKLY-BOSS.md) | 鸣潮: how the weekly boss is fought and how its reward is claimed |
| [OKWW-NEST-MODES.md](OKWW-NEST-MODES.md) | 鸣潮: the difference between the two 残象聚落 modes |
| [OKWW-PATCHES.md](OKWW-PATCHES.md) | 鸣潮: what the local patches change, and what counts as success |
| [OKWW-STUCK-DIALOG.md](OKWW-STUCK-DIALOG.md) | 鸣潮: diagnosing a hang (the modal-dialog class of them) |
| [WUWA-TACET-INDEX.md](WUWA-TACET-INDEX.md) | 鸣潮: 无音区 index mapping (unfinished) |
| [AUTO-STORY.md](AUTO-STORY.md) | Findings on automating story playback / event stages |

## This Mac and the network

| Document | Question it answers |
|---|---|
| [HOME-NETWORK.md](HOME-NETWORK.md) | The home network in Tokyo: topology, cause and options |
| [PLAY-MANUAL.md](PLAY-MANUAL.md) | Manual for playing remotely (streaming) |
| [MAC-COMPAT.md](MAC-COMPAT.md) | How compatible the three helper programs are with the Mac |
| [MAC-CHANGES.md](MAC-CHANGES.md) | What has been changed on this Mac and on ins |

## Rules for writing

| Document | Question it answers |
|---|---|
| [PHONE-COPY-RULES.md](PHONE-COPY-RULES.md) | How to write the copy on the phone remote page |

## Archive (mind the dates when reading)

| Document | What it is |
|---|---|
| [CODE-HISTORY.md](CODE-HISTORY.md) | The backstory lifted out of code comments; pointers in the code lead here |
| [IMPROVEMENT-PLAN.md](IMPROVEMENT-PLAN.md) | The optimisation plan proposed on 2026-09-06 and the record of carrying it out |
| [SWEEP-0830.md](SWEEP-0830.md) | One systematic sweep of the 08-29 evening run / 08-30 morning run |
| [SURVEY-2026-09-08.md](SURVEY-2026-09-08.md) | 46 verified findings from a read-only survey of every piece of software here, ranked by what a silent failure costs |
