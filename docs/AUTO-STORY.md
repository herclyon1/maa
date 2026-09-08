# Auto-story / event clearing — research conclusion (2026-08-26)

**Conclusion: the "fully automatic" thing the user asked for (auto-pathing → open the map and
teleport → trigger the NPC dialogue → skip it) does not exist. Every project for 鸣潮 and 终末地 is
"you trigger the story, it does the clicking". Do not research this again.**

| Project | Game | Background | Picks dialogue branches | Pathing / teleport |
|---|---|---|---|---|
| **MaaEnd** `RealTimeTask` | 终末地 | real-time assist by design | ✅ `AutoSkipChoose` | ❌ `QuickTeleport` is **the user picking a destination from a list** |
| [WWA](https://github.com/wakening/WutheringWavesAssistant) `AutoStoryService` | 鸣潮 | ❌ **must be foreground** | ✅ | ❌ |
| [better-wuthering-waves](https://github.com/babalae/better-wuthering-waves) | 鸣潮 | ✅ background | ⚠️ only ever picks the last option | ❌ |
| **OK-WW** `SkipDialogTask` | 鸣潮 | ✅ background | ❌ | ❌ |

## Source evidence (do not believe the READMEs' sales copy)

- **WWA** `src/service/auto_story_service.py`: `npc_interact_action` is three lines end to end —
  `sleep(0.5)` → `pick_up()` → return, and it fires only once the `NpcInteract.png` interaction box
  is **already on screen**. The first line of `execute()` is `if not is_foreground_window(): ... return`,
  so **it does nothing unless the game is in the foreground**.
  `explore_workflow.py` is the same shape: only `_skip`/`_play`/`_dialogue`/`_pickup`, no routes,
  no pathing, no map nodes.
- **better-wuthering-waves** (★155, C#, the babalae team): the README's feature list is a single line —
  「快速点击F过剧情，可以后台过。可以自动点击跳过按钮。默认选择最后一项选项」
  (mash F through the story, works in the background, auto-clicks the skip button, defaults to the
  last option). The author says of it 「项目随时会弃坑」 — the project may be dropped at any time.
- **MaaEnd `RealTimeTask`** nodes: `AutoFight` / `AutoPick` / `AutoZipline` / `AutoPuzzleSolving` /
  `SklandMap` (森空岛 map overlay) / `QuickTeleport` — the classic "you play, it clicks for you".

## MaaEnd's auto-story switches (installed, not in use)

They hang off **`RealTimeTask`** (`RealtimeAssist` is a trimmed-down preset):

| Switch | What it does |
|---|---|
| `AutoSkip` | Auto-story (master switch) |
| `AutoSkipAll` | Skip every cutscene, auto-click the skip button |
| `AutoSkipChoose` | **Auto-select the dialogue branch** |
| `AutoSkipNext` | Speed the story up (keeps tapping the screen) |
| `EnableCloseSpecialPanel` | Auto-close the story-document / voice-log screens |

**`RealTimeTask` is one of the 27 tasks AUTO-MAS does not expose**, so it is invisible in the MAS UI.
Reach it through MaaEnd's own UI (MXU `127.0.0.1:12701`) or its API. See [HEADLESS.md](HEADLESS.md).

## Why nobody has built the fully automatic version

Pathing requires the machine to understand quest state + the map + navigation, which is an order of
magnitude harder than "see a button, click it". The deepest work of this kind, the Genshin one
([BetterGI](https://github.com/babalae/better-genshin-impact)), still only **replays routes the user
recorded themselves** — it does not find quest markers on its own.

## Related projects noted along the way

- [`zzc-tongji/ok-ww-enhanced`](https://github.com/zzc-tongji/ok-ww-enhanced) ★24 —
  an enhanced OK-WW that adds `-t/--task` and `-e/--exit` command-line flags (exits by itself when done),
  which is **useful for unattended scheduling**. No story, no events.
- [`ok-oldking/ok-end-field`](https://github.com/ok-oldking/ok-end-field) ★7 —
  the 终末地 build by OK-WW's author, has "auto-skip story", but MaaEnd (★3708) is far more mature;
  no reason to switch.
- WWA has an event framework in `src/core/activity.py` (version detection / time windows / availability)
  plus `SoarToTheBeatMacroReplayTask` (macro record-and-replay for rhythm-style minigames like 律动九霄) —
  **it is the only one that covers events at all**.

## Two things to confirm before installing any of this

1. WWA holds the foreground, so it and background OK-WW **cannot** drive 鸣潮 at the same time —
   they fight over the screen.
2. Two scripts driving the same game must be staggered in the schedule.
