# Mac compatibility of the three games' helper programs

Verified 2026-08-29. Conclusion: **for "auto story mode" on a Mac, there is not one option.**

## Layer one: the games themselves have no official Mac client

| Game | Official macOS client |
|------|------------------|
| 原神 | None. Only via PlayCover running the iOS build (Apple Silicon only), or CrossOver / Whisky running the PC build |
| 鸣潮 | No official Mac client found |
| 终末地 | PC build is Windows; there are also Android / iOS builds |

Running an online game through unofficial routes carries a ban risk in itself — every one of
those guides says so themselves.

## Layer two: the helper programs

| Game | Tool | Auto story? | Mac build? | How it drives the game |
|------|------|--------------|-------------|-------------|
| 原神 | BetterGI (babalae/better-genshin-impact) | Yes (auto dialogue, auto skip) | **No.** The official quick-start page says verbatim: 「BetterGI 只支持 Windows 系统」, and requires Win10+ 64-bit | Captures the Windows window + injects input via Win32 |
| 鸣潮 | 更好的鸣潮 BetterWW (babalae/better-wuthering-waves) | **Yes, and it is the headline feature** — the repo's own title is 「后台自动剧情」 | **No.** The v0.12 release ships only `.exe` and `.7z` | Same as above |
| 鸣潮 | OK-WW (ok-oldking/ok-wuthering-waves) | Dialogue skipping inside the daily routine | **No.** Every asset in the v3.6.6 release is a `win32` package | Same as above |
| 终末地 | MaaEnd | No dedicated auto story; it is mainly dailies | **Yes.** v2.26.0 ships `macos-aarch64.dmg` and `macos-x86_64.dmg`, plus Linux packages | Win32 foreground (Windows only) **or ADB** (Android emulator / real device) |

## Why only MaaEnd has a Mac build

Every other tool from these three projects takes the same route: **capture the Windows game
window + inject keyboard and mouse through the Win32 API**. That API simply does not exist on
macOS, so porting is not "nobody bothered", it is not possible.

MaaEnd took a different route — **ADB to the Android build** — and that route is cross-platform
by nature, so macOS and Linux packages came almost for free. Its README only mentions
「PC 端 (Win32 前台) 与安卓端 (ADB)」 and never mentions macOS, but the release really does
contain dmgs.

## But MaaEnd's route is useless to us

1. On a Mac it can only go through ADB, which means it must run the **Android build of 终末地**,
   on either a real device or an emulator. Android emulator options on Apple Silicon are very limited.
2. **It has no auto story mode in the first place.** What it does is dailies.

## What BetterWW can actually do (confirmed by reading the source, not the blurb)

**It only does story, not dailies.** There are exactly three feature directories under `GameTask`
in the repo: `AutoSkip` (skip story), `AutoPick` (auto pickup), `GameLoading` (recognise the
loading bar). No stamina, weekly bosses, echoes, bounties or abyss — those are OK-WW's job.

**There is no auto pathfinding.** The entire repo contains no pathfinding, walking, or
route record/replay code at all.

### How the "background" part works

Two things combined:

1. **Capture goes by window handle, not by foreground.** `Fischless.GameCapture` implements
   three backends: `BitBlt`, `DwmSharedSurface`, `Graphics` (Windows Graphics Capture).
   All of them capture against the game window's HWND, so they still work when the window is
   covered or not in front.

2. **Input goes through `PostMessage`, not `SendInput`.**
   `AutoSkipTrigger.cs` calls `_simulator.KeyPressBackground(...)` and `skipRa.BackgroundClick()`,
   which sit on top of `PostMessageSimulator` — it posts messages straight into the game window's
   message queue, needs no window focus, and does not steal the mouse and keyboard you are using.

3. **Buttons are recognised by template matching** (image resources like `SkipButtonRo`,
   `NotPromptAgainButtonRo`), not OCR. That makes it very sensitive to resolution and filters:
   16:9 only, 1920x1080 windowed recommended, no HDR and no GPU filters, administrator rights
   required. Environment requirements are Windows 10 64-bit + .NET 8.

### How this differs from what our wingui.sh does

Our `wingui.sh` uses `keybd_event` / `mouse_event` — that is **global foreground input**:
the game has to be brought to the front, it steals the mouse, and it has to detour through a
scheduled task to reach session 1, so one round trip takes 30-40 seconds.

BetterWW is **local on that machine, posting messages to a window handle**, so latency is close
to zero and it never takes focus. The two are not in the same league.

## Conclusion

**Auto story mode on a Mac has zero options.** All three tools that have auto story (BetterGI,
BetterWW, OK-WW) are Windows-only; the one tool that ships a Mac build, MaaEnd, happens to be
the one without auto story.

**The right move is to turn the question around.** On 2026-08-29 we spent an afternoon proving
that when driving the game remotely from the Mac, the bottleneck is not platform compatibility
at all — it is the **30-40 second round trip per action** (see [PLAY-MANUAL.md](PLAY-MANUAL.md)).
Pathfinding is essentially zero.

And **BetterWW's 「后台自动剧情」 is exactly the thing we today cannot do, and it runs natively
with zero latency on that Windows machine in 乌鲁木齐.**

So the line is: the Windows machine is the execution end, the Mac is the control end — which is
exactly the current setup. If you want auto story, install BetterWW on that machine; do not try
to move it onto the Mac.

Ban risk is unchanged: these are all third-party tools, and both 库洛 and 米哈游 are within their
rights to ban accounts.

## Addendum: running Windows programs on a Mac without a VM — possible, but useless here

Verified 2026-08-29.

### The no-VM routes do exist

| Option | Status |
|------|------|
| **CrossOver 26** (released 2026-02) | Wine + Apple GPTK 4, supports both Intel and Apple Silicon, no Windows install and no Windows licence needed. Commercial software |
| **Whisky** | **No longer maintained**; the author tells people to move to CrossOver. Existing installs still work, but there are no updates and no support |
| Apple Game Porting Toolkit | Apple's own D3D→Metal translation layer, already bundled inside CrossOver 26 |
| VMs (Parallels / VMware / UTM) | Run Windows 11 ARM and rely on Windows' built-in x86 emulation for x86 programs |

### But the 鸣潮 chain breaks in two separate places

**Break one: the game itself will not even start under Wine.**
鸣潮 uses 库洛's anti-cheat (a modified ACE). Measured results are that both Whisky and Game
Porting Toolkit get blocked by the anti-cheat and the game does not launch. Linux/Proton hits
the same problem.

**Break two: even if the game ran, BetterWW could not attach to it.**
It relies on `DwmSharedSurface` / Windows Graphics Capture to capture the window, then
`PostMessage` to send messages to that HWND. Those APIs are essentially unimplemented in Wine,
and on top of that it would have to be in the **same Wine prefix** as the game to see the
window handle at all.

**The only way to play 鸣潮 on a Mac is PlayCover** — running the iOS build natively on Apple
Silicon. But that is an iOS app: it **has no Win32 window at all**, so BetterWW does not even
have an object to post messages to.

### Conclusion

On this particular question the Mac is not "a bit slower" or "a bit more awkward" — it is
**structurally impossible**. The Windows machine has to stay as the execution end.
