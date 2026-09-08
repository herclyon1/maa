# Remote game operation manual

For whoever takes over driving the game machine. That machine sits in Urumqi and
runs on Beijing time, you are at the Mac end, and Tailscale is in between.
Every line below was written after actually hitting it, not imagined.

## 0. Accept one thing first: one action = 30~40 seconds

It is not a slow network. It is the link itself:

```
Mac ──ssh──> game machine ──creates an interactive scheduled task──> the desktop of session 1
                              └─> pwsh runs ark-gui.ps1 ─> sends keys/clicks ─> full-screen shot
Mac <──scp── pulls back the screenshot and the log
```

Why it goes the long way around: an ssh login lands in **session 0, which has no
desktop**, and a graphical program started from there dies outright
([relay-runs-in-session-0] already cost us once). To touch the real screen the
only route is a `/it` scheduled task that runs over in the already-logged-in
session 1.

**Conclusion: never split into three round trips what one round trip can do.**
See section 2.

## 1. Three tools

| Tool | What it does |
|------|--------|
| `scripts/mac/wingui.sh` | Send actions, take screenshots, pull them back |
| `scripts/mac/lib/shotcrop.py` | Crop and scale images + **convert image coordinates into click coordinates** |
| `ssh Administrator@$ARK_HOST` | Inspect files and processes. Do not use it to start graphical programs |

Environment variables:

```bash
export ARK_HOST=100.65.39.119
export ARK_GUI_PROC=Endfield                 # 终末地
export ARK_GUI_PROC=Client-Win64-Shipping    # 鸣潮 (default)
```

`ARK_GUI_PROC` decides which window the keys and clicks go to. **Wrong window =
every action is lost, and nothing reports an error.**

## 2. seq is what makes this workable at all

A single action:

```bash
./scripts/mac/wingui.sh key f7
./scripts/mac/wingui.sh click 960 540
./scripts/mac/wingui.sh shot
```

A run of actions (**one ssh round trip for all of them**):

```bash
./scripts/mac/wingui.sh seq 'key esc; wait 3000; key r; wait 3000; click 1642 866; wait 3000'
```

Measured: taking 3 photos as separate steps is 6 round trips ≈ 4 minutes;
strung into one seq it is 1 round trip ≈ 100 seconds.

### What can go inside a seq

| Action | Notes |
|------|------|
| `key <key>` / just `<key>` | `esc` `enter` `f1`~`f12` `a`~`z` `0`~`9`. The `key ` prefix is optional |
| `esc2` | Press ESC twice, 1.2 s apart |
| `click <x> <y>` | Left click at **real screen coordinates** |
| `look <dx> <dy>` | Turn the camera, relative mouse movement. Positive is right/down |
| `hold <key> <ms>` | Hold the key down. Walking, running and jumping all use this |
| `rdown` `rup` `ldown` `lup` | Mouse button down/up. For press-and-drag and for right-button camera turning |
| `scroll <notches> [x y]` | Scroll wheel, negative is down. **Without coordinates it scrolls at the centre of the screen**, which will not move a sidebar |
| `wait <ms>` | Wait |

Every action **carries its own** trailing wait (2.5 s for a key, 1.8 s for a
click); the `wait` you write is **on top of** that. Give 3000 for a screen
change, 30000 or more for a loading bar.

### Timeouts are not your problem

The script works out its own wait budget from the action list (it sums every
`wait`/`hold` in milliseconds, allows 5 seconds more per action, then adds 30
seconds of overhead). To set it by hand, use `ARK_GUI_WAIT=300`.

This used to be hard-coded to 40 seconds, so a long seq would report "no result
produced" while **the remote side had in fact finished**. That kind of false
failure is the worst kind, and it has been fixed.

## 3. Screenshots: crop before you look

What `wingui.sh` brings back is the whole virtual desktop, **3840x1243** (two
monitors stitched together), 7~10 MB per image.

- **Do not Read the raw image.** It blows up the context and the window goes
  white ([claude-desktop-white-screen-huge-transcript]).
- The game window is in the **top-left corner, 0,0 - 1920,1080**.

```bash
python3 scripts/mac/lib/shotcrop.py <source> <out.png>                    # default: crop the game area, scale to 1400 wide
python3 scripts/mac/lib/shotcrop.py <source> <out.png> 1130,280,1900,930 1350   # only the list on the right half
```

To read small text (progress numbers, star counts, key labels), crop tighter and
ask for a bigger width - that is your magnifying glass.

## 4. Coordinates: what you measured on the image ≠ what you can click

**This is the easiest mistake to make.** You measure (1197, 632) on an image
that was cropped and then scaled, and `click 1197 632` lands somewhere entirely
unrelated.

```bash
python3 scripts/mac/lib/shotcrop.py --map 0,0,1920,1080 1400 1197 632
# -> 1642 867      ← this is what click wants
```

The arguments are the same two you used when cropping (region + width).
`shotcrop.py` prints this command after cropping; copy it and change the numbers.

## 5. "Did it work" is answered only by numbers inside the game

I clicked the button ≠ it took effect. This actually happened: I clicked "保存",
the screen did not react, I assumed it had failed, then a `dir` on the machine
showed the file had been written.

Judge it either by an **in-game counter** (`6/10` → `7/10`) or by **evidence on
disk** (a file, a log). Never close a case with "I clicked it so it must have
worked."

## 6. Known key bindings

### 终末地 (`ARK_GUI_PROC=Endfield`)

| Key | Screen |
|----|------|
| **J** | 任务日志 - main and side quests are here, not under F8 |
| **F7** | 活动中心 |
| F8 | 行动手册 (**sanity is in the top bar of this screen**) |
| F9 | 武库 |
| F5 | 采购中心 (**the shop, it has real-money purchase buttons, do not click around**) |
| B / C | 背包 / 干员 |
| TAB | 探索大地图 |
| ESC | 系统菜单 |
| **R** | 拍照模式 (when the quick tool is already switched to the camera) |

Inside 拍照模式: `Z` resets the view, `X` hides the UI, right button rotates,
the wheel zooms, `TAB` switches between operator and camera, `WASD` moves the
operator, `ESC` exits. The shutter is at `1642 866`; a preview pops up after the
shot, save is at `1752 976`, then two ESC presses return you to the world.

**Do not read sanity off the top-right of the world screen.** That
`2400/2400` with the lightning ring is a scene facility's energy bar, not
sanity. Sanity is in the F8 top bar.

**The small orange square in the sidebar means "unread", not "not done"** - it
disappears as soon as you open the entry. Whether something is finished is told
only by the green 「已全部领取」 on the detail page.

You never have to guess or ask about key bindings: once in the game, every icon
in the top-right corner has its own key printed above it. Crop
`1330,0,1920,100` and enlarge it to read them. **When you meet a screen you do
not recognise, read this first instead of experimenting.**

### The trap in batched clicks (a real crash on 2026-08-29)

Dialogue screens have a 「待发送」 button; one click advances one line. To save
effort I repeated `click 1136 845; wait 4000` six times in a single seq.

The dialogue ended on the fourth click, so **the last two landed on the world
screen**, opened the map and popped up the 「自定义标记」 dialog - it came
within one click of adding a marker.

**Rule: when clicking the same coordinate repeatedly, count by "the fewest
clicks still needed" - too few beats too many.** The moment the target is gone,
the extra clicks fall through to whatever screen is underneath, and you do not
know what that screen is. Take a screenshot to confirm once you are done; do not
keep clicking until "that's probably enough."

### 鸣潮 (`ARK_GUI_PROC=Client-Win64-Shipping`)

**Red line: never change 鸣潮's key bindings.** Changed key bindings = OK-WW
automation silently produces nothing; if a fight is being lost, check the key
bindings before the team composition ([wuwa-keybinds-must-be-default]). Reading
the settings screen is fine, touching anything in it is not.

Launch: `./scripts/mac/wingui.sh launch wuwa`; once it is up, click 「点击连接」
at `979 1008`; entering the world takes over 50 seconds.

| Where | Notes |
|------|------|
| Quest bar, top left | The tracked quest name + next objective + distance. **This is your only navigation source** |
| The key hint inside the quest bar | For example 「`V` 查看飞讯」 - the game tells you outright which key to press, so press it |
| 飞讯 「待发送」 button | `1136 845`, one click advances one line of dialogue |
| ESC | Closes panels one layer at a time; pressed in the world it opens the system menu |

However many metres the quest bar says, that is how far you have to walk.

**鸣潮 has no auto-pathing.** Clicking the quest text or the quest icon only
re-tracks it; the character does not walk (tested three times on 2026-08-29, the
character did not take a step). For any distance there is exactly one route:
open the map (`M`) → find the **beacon** nearest the target (one you have
unlocked) → click it → click 「传送」 in the popup → run the remaining distance
by hand.

Reading markers on the world map:

- **The yellow arrow is you**, and its direction is which way the character
  faces. Do not mistake it for the destination.
- A golden circle with a crosshair = the quest objective being tracked.
- Clicking **empty map** pops the 「自定义标记」 dialog - ESC out of it, do not
  click 「添加」.
- Clicking **a marker itself** only opens an info box, it does not teleport;
  only beacons offer a 「传送」 button.

### Cutscenes can be skipped

Cutscenes and dialogue **have a skip button in the top-left corner**. Look
there first when a story sequence starts instead of clicking through it line by
line.

### Walking navigation: follow the waypoint icon, not the metre count

**The metre count is a 3D straight-line distance, and it tells you nothing about
direction.** Going around a pillar, ending up on the wrong floor, walking past
the target - the number goes up in all of those, and you cannot tell being
turned around from being blocked.

Real failure on 2026-08-29: the distance went 6→12→15→26→26→30→29 - already
down to 6 metres and back out to 29, seven attempts in a row without one steady
decrease.

**There is a waypoint on screen.** The tracked quest objective is drawn in the
world as a **golden circle with a cross** (it only appears at close range), with
a `>` or `<` arrow beside it meaning the target is further off in that
direction.

The way that works:

```
1. Take a screenshot and find that golden waypoint icon
2. Use look <dx> 0 to turn until the waypoint is horizontally centred (x ≈ 960)
   Screenshot after each turn to confirm; the icon should be moving inward
3. Only once it is centred, hold w, 2000~3000ms at a time
4. Only now should the metre count fall steadily. If it does not, there is a
   wall or a height difference in the way
```

**Height difference**: the waypoint icon clearly above centre = the target is
upstairs, find stairs or climb; clearly below = the target is downstairs, drop
down. Jump is space by default.

**Do not operate while standing on a railing or the edge of a platform.** When
the character is stuck on a narrow edge, movement is constrained by the terrain
and the path taken has nothing to do with what you intended. Get down to flat
ground before navigating.

### That golden icon sticks to the screen edge - do not expect to centre it

When the icon has a `>`, `<` or `⌄` beside it, the **target is off screen** and
the icon is pinned to a fixed position at the edge; the only useful information
is that little arrow (which direction the target is in). Turning the camera
barely moves it.

Only when the target **comes on screen** does the icon settle onto its real
position, with "N metres" shown beside it. **Seeing "N metres" is what tells you
that you actually have the target in view.**

### The coordinate readout in the bottom-left corner is in metres, so solve for the target

The bottom-left corner shows something like `-24,6,1`: that is **(x, height, z),
in metres**. The distance in the quest bar is the 3D straight-line distance to
the target.

Put the two together and the target position is solvable: stand in several
different places and read "coordinates + distance" at each; three points or more
are enough to solve for the target coordinates.

Measured on 2026-08-29: a grid search over 8 samples solved the target as
`(-7,-2,5)`, with an **average error of 0.27 metres**. This turns "wander about
and hope" into "compute how far is left."

```python
best, bestErr = None, 1e18
for a in range(-60, 41):
  for b in range(-40, 41):
    for c in range(-40, 41):
      e = sum((math.dist(p, (a,b,c)) - d)**2 for p, d in obs)
      if e < bestErr: bestErr, best = e, (a,b,c)
```

With the target coordinates in hand, read the coordinates after every step and
you can tell whether that step closed the gap or opened it, instead of guessing
direction from the metre count. **Calibrate the world direction of the movement
keys the same way**: walk a short distance, look at the coordinate delta, and
you know which world direction each of `w/a/s/d` maps to.

### But: in tight indoor terrain this whole method still loses

Also measured on 2026-08-29, inside the 「心的密室」 instance: the character was
wedged in the corner between a rock and a wall, `a` moved +x but **automatically
climbed the wall** at the same time (height +7), `d` lowered the height but
moved x the wrong way, and `w` walked straight into the wall and stayed put. No
matter how precise the solved coordinates are, there is no route that both
lowers height and moves forward.

**Conclusion: dialogue, menus, skipping cutscenes, teleporting, running across
open ground - this method handles all of that. Three-dimensional movement in
tight indoor spaces - it cannot, at 40 seconds per frame, so do not grind at
it.** In terrain like that, hand over the coordinates and the target position
and let a person take over for half a minute; it beats burning an hour.

### Tick 「不再提醒」 only where it is about skipping cutscenes

鸣潮 puts a second confirmation dialog in front of many actions. On a link with a
40-second round trip, every confirmation dialog is one more real round trip, and
skipping one story sequence costs the best part of an extra minute.

Those dialogs usually carry a **「不再提醒」** checkbox; tick it and the same
class of action stops asking, which saves a great many round trips.

**But tick it only in these two places:**

- Confirmations for skipping story / skipping cutscenes
- Confirmations for pure UI actions (closing a panel, leaving a screen)

**Never tick it, and never click confirm, in these places - ask first:**

- Anything that spends something on the account (stamina, materials, currency,
  gacha pulls)
- Anything with the words 「购买 / 充值 / 兑换 / 删除 / 分解 / 放弃」 on it
- Anything where you cannot say what clicking it will do

The difference: getting a skip-cutscene click wrong costs you a story sequence
at worst, and you can watch it again; once the reminder is turned off on a
resource-spending dialog, every later misclick takes something directly, with no
way back.

## 7. Red lines

1. **Do not click any purchase / top-up / exchange button.** Hit ESC out of a
   shop screen immediately.
2. **Do not click account logout, account switching, or delete save.**
3. **Do not change 鸣潮 key bindings.** See above.
4. **Do not shut the machine down.** Shutting it down = cutting off your own hands.
5. **Report an error the moment it happens.** Do not work around it silently, and
   do not fob it off as "known issue / does not affect the result". A silent
   failure is the highest-priority bug there is.
6. **Do not present an inference as a fact.** If it has not been tested, say
   "not tested".
7. Take a screenshot before acting, to confirm which screen you are on. Blindly
   clicking into a screen you cannot identify is the one use of these tools that
   causes real loss.

## 8. If you are stuck, ask

```
SendMessage({to: "main", message: "..."})
```

This link is confirmed to work in both directions. `ListAgents` is disabled in a
subprocess, but the address `"main"` is written into SendMessage's own
documentation, so just use it.

**When to ask:** an unfamiliar screen, a key binding you cannot look up, two
attempts in a row with no progress, anything that might spend a resource on the
account, and any moment where clicking feels like it might not end well.

When you ask, send these three things together: which screen you are on, what
you are trying to do, and which step you are stuck on. Do not just send "stuck".
