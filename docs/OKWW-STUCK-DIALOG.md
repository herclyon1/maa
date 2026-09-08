# OK-WW hang: a modal dialog → `target_enemy failed` across the board

On 2026-08-26, during a catch-up run, OK-WW hit `📅 Daily Task exception stopped`
four times in a row (16:04, 16:27, 16:29, 16:32), after which the process was simply
gone. This note records **what the real cause was**, **which steps I misdiagnosed**,
and **how to go straight to the answer next time**.

## Symptoms

```
ERROR CombatCheck: target lost try retarget 10
ERROR CombatCheck: target_enemy failed, try recheck break out of combat
Exception: can't find gray_book_boss, make sure f2 is the hotkey for book
```

Counts: echo book opened 16 times / combat entered 9 times / **combat finished
successfully 0 times** / the counter stayed at 0/41 throughout. Stamina farming
(`ForgeryTask`) was blocked completely: 0 lines for claiming daily rewards, 0 lines
for daily completion.

## Real cause

The game was blocked by a **「选择复苏物品」 modal dialog**, and it had been blocked
for at least 20 minutes.

OK-WW does not recognize this dialog; its `click_skip_dialog_confirm` tried and timed
out. The dialog stayed up, so every feature-recognition pass landed on the same
obscured frame: no enemy could be locked → `target_enemy failed` → upstream
`CombatCheck` went straight to `break out of combat` → `DomainTask.farm_in_domain`
carried on down to `walk_to_treasure()` to pick up the chest → not a single enemy had
been killed in the domain, so of course there was no chest → `WaitFailedException` →
the whole Daily Task exited on an exception.

The full call chain (`ok-script.log`, 16:32:15):

```
DailyTask.run → ForgeryTask.farm_forgery → DomainTask.farm_domain_with_recovery_loop
  → DomainTask.farm_in_domain → BaseWWTask.walk_to_treasure
  → walk_to_box → do_walk_to_box → wait_until → WaitFailedException
```

**The fix on the spot**: send `{ESC}` to the game window to dismiss the dialog. Do not
click 「确认」 — that would consume one revival item (stock at the time was 9 + 4).
Right after ESC the screen was normal again: character at full HP 17267/17267, Lv.90,
standing inside the Forgery Challenge domain, countdown running, timed enemy kills at
0/5. After re-triggering OK-WW, `target_enemy failed` **dropped to zero** and the
`switch_next_char Chisa(Healer) ↔ Lucilla(SubDps)` rotation ran normally.

## The three things I got wrong (skip them next time)

### 1. "The game crashed, the process is a 3MB empty shell" — wrong

`Wuthering Waves.exe` is only the launcher shell; **the actual game process is
`Client-Win64-Shipping.exe`** (331 threads at the time, perfectly alive). To check
whether the game is alive or dead, always check the latter.

### 2. "The game machine's screen is locked" — wrong, and my own tool lied to me

I called `GetCursorPos` from an ssh session and got `err=1459`
(`ERROR_REQUIRES_INTERACTIVE_WINDOWSTATION`), and concluded from that the desktop had
been switched away.

In reality **an ssh session simply has no interactive window station**; that error has
nothing to do with the state of the game machine. Likewise, reading
`MainWindowHandle` and `WorkingSetSize` across sessions is not trustworthy either —
that day the real game process reported a `MainWindowHandle` of 0.

**Whenever you need to know "what is actually on the screen right now", use
`scripts/mac/wingui.sh shot`**, which registers an `/it` (interactive) scheduled task
and takes a real screenshot inside session 1.

### 3. "OK-WW's own saved screenshots show the current state" — wrong

OK-WW saves screenshots **only on errors**, and the two from that day, 16:27:11 and
16:32:15, were **identical**. That looks like "the game is frozen", but really it was
OK-WW failing recognition over and over against the same frame obscured by the dialog.
What it saves is what it saw, not what is there now.

## Tools

`scripts/mac/wingui.sh` (written 2026-08-26 because of this incident):

```bash
ARK_HOST=100.65.39.119 scripts/mac/wingui.sh shot now.png    # the real screen
ARK_HOST=100.65.39.119 scripts/mac/wingui.sh key esc         # close the dialog
ARK_HOST=100.65.39.119 scripts/mac/wingui.sh key f2          # open the teleport list
```

`key` always calls `SetForegroundWindow` first: **Wuthering Waves keeps rendering while
unfocused but accepts no input**. Without bringing it to the foreground every keystroke
is dropped, and nothing reports an error.

## Still unresolved

* **Upstream does not know this dialog.** `click_skip_dialog_confirm` does not cover
  「选择复苏物品」. Worth filing an issue with ok-oldking/ok-wuthering-waves: fall back
  to ESC for any modal dialog, instead of only recognizing the few known ones.
* **How the dialog appeared in the first place** is undetermined. The character was at
  full HP, so it does not look like a death trigger; more likely the item bar was hit by
  accident during auto-combat. There is no corresponding record in the log.
* **Which domain "number 1" in the Forgery Challenge list actually is** cannot be found
  in the code. Upstream hardcodes
  `'The Forgery Challenge number in the F2 list.'`, i.e. `serial_number - 1` picks that
  row of the in-game F2 list, and the order is decided by the game. It can only be
  pinned down by photographing the F2 list once, **and the order may change after a game
  update** — this is not settled once and for all.
