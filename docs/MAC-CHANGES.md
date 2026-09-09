# Changes I have made to this Mac and to ins

> Restore points live in `~/Claude/mac-backups/`, **not in the repository**.
> Moved out on 2026-09-08: this repository is public, and a personal machine's Dock
> configuration and launcher backups do not belong on it (they were swept in by a
> `git add -A` and committed alongside unrelated work).

> Maintained by Claude. **Update this file every time a system-level setting is changed.**
> Last updated: 2026-09-08

---

## 1. Things that start at boot (there is exactly one)

### Hotspot bypass for WARP  `local.hotspot-bypass`

| | |
|---|---|
| Loader script | `/usr/local/libexec/hotspot-bypass.sh` |
| Launch item | `/Library/LaunchDaemons/local.hotspot-bypass.plist` |
| Log | `/var/log/hotspot-bypass.log` |
| Trigger | **event-driven, no polling**: at boot (`RunAtLoad`) plus `WatchPaths` on three files |

**The files WatchPaths watches** (covering every case that would invalidate the rules):
- `/var/run/resolv.conf` - rewritten when the interface changes, the network changes, or a new DHCP lease arrives
- `/Library/Preferences/SystemConfiguration/com.apple.nat.plist` - internet sharing being toggled (its pf reload wipes the anchor)
- `/Library/Preferences/SystemConfiguration/preferences.plist` - network service configuration changes

**⚠ Must not be changed to `StartInterval`** - the user has a standing ban: no polling by default.

**What it solves**: while Cloudflare WARP is on, a phone connected to the Mac's hotspot has
no internet at all.

**Why that happens**: WARP installs `block drop in all` / `block return out all` in pf and
only lets its own tunnel's traffic through. Packets forwarded from the phone through the Mac
match no pass rule, so they are dropped and answered with RST.

**Three problems stacked on top of each other (all three must be solved; my first two
attempts each solved only one and both failed)**:
1. WARP's catch-all deny → the rules have to be installed in the `com.apple/` namespace,
   because `/etc/pf.conf`'s `anchor "com.apple/*"` comes **before** the anchor WARP inserts
   dynamically
2. WARP's tunnel MTU is only 1300 while the phone assumes 1500 → `scrub max-mss 1240`
3. **The packet is already wrapped in QUIC by WARP before it leaves the interface** (all that
   is visible on en6 is encrypted traffic to `162.159.198.2:443`) → the exit has to be pinned
   with `route-to` at **ingress**; a rule written as "pass on the way out of the interface"
   can never match

**The rules that get loaded** (the interface and gateway are auto-detected by the script, so
changing interfaces does not break it):
```
scrub in on <bridge> all max-mss 1240
pass in quick on <bridge> route-to (<uplink> <gw>) all tag HOTSPOT keep state
pass out quick on <uplink> tagged HOTSPOT keep state
```

**Manual operations**:
```bash
sudo /usr/local/libexec/hotspot-bypass.sh status    # show current state
sudo /usr/local/libexec/hotspot-bypass.sh unload    # disable temporarily
sudo /usr/local/libexec/hotspot-bypass.sh load      # enable again
```

**Full uninstall**:
```bash
sudo launchctl bootout system/local.hotspot-bypass
sudo rm /Library/LaunchDaemons/local.hotspot-bypass.plist /usr/local/libexec/hotspot-bypass.sh
sudo pfctl -a 'com.apple/hotspot-bypass' -F all
```

---

## 2. System settings that were changed

| Item | Was | Is now | Revert command |
|---|---|---|---|
| F-key behaviour | media keys take priority | **standard function keys** (pressing F5 sends F5) | `defaults write -g com.apple.keyboard.fnState -bool false` |
| Bottom-right hot corner | Quick Note (14) | **disabled** (1) | `defaults write com.apple.dock wvous-br-corner -int 14 && killall Dock` |
| Dock pinned apps | the 21 factory defaults | **8** (picked by actual usage time from knowledgeC) | see the backup below |
| Tailscale accept subnet routes | off | **off** (was turned on for a while, turned back off) | - |

**Dock backup**: `~/Claude/mac-backups/.dock-backup-20260905-025845.plist`
```bash
cp ~/Claude/mac-backups/.dock-backup-20260905-025845.plist ~/Library/Preferences/com.apple.dock.plist && killall Dock
```

**The current Dock**: Claude / Chrome / 鸣潮 / WeChat / 明日方舟 / System Settings / Terminal / NeteaseMusic

---

## 3. The launchers on the desktop (whose contents I changed)

`串流到ins.app`, `串流到ins-HEVC444.app`

**Two changes** (not one character of the image-quality parameters was touched):
- `--performance-overlay` → **`--no-performance-overlay`** (turns off the top-left overlay)
- added **`--capture-system-keys always`** (maps ⌘ to the Win key and passes it through)

**⚠ The main executable has to be a compiled Mach-O, not a shell script** - as a script,
double-clicking pops up a "Rosetta needs to be installed" dialog, because LaunchServices
cannot determine the architecture.

**To change the parameters, change them in this one place and re-run the build script**:
```bash
# the parameters live in scripts/mac/lib/moonlight-params.sh; run this after editing
~/Claude/maa-automation/scripts/mac/make-stream-apps.sh
```
Since 2026-09-08 the desktop launchers and the command-line `scripts/mac/stream-ins.sh` share
one copy of the parameters in `scripts/mac/lib/moonlight-params.sh`. Before that each side
had its own copy, so changing the bitrate in one left the other as it was - and both still
launched fine with no error, only with mismatched image quality.

Backup of the original binaries: `~/Claude/mac-backups/.launcher-backup-20260830-232059/`

**There is a third one on the desktop: `强制关闭串流.app`, whose source is not in this
repository.** It was not generated by `make-stream-apps.sh` (the bundle identifier's
algorithm does not match); it is compiled from Swift, and all that can be seen inside is one
"Moonlight" string literal and a few Process methods.
It has not been touched, and rebuilding it from guesswork is not advisable - if it really has
to be rebuilt, first ask the user how it was originally made.

---

## 4. Scripts I created

| Path | Purpose |
|---|---|
| `scripts/mac/make-stream-apps.sh` | build/update the desktop streaming launchers |
| `scripts/mac/cn-route-pf.sh` | route Cloud Genshin through ins (**off by default, turned on/off by hand**) |
| `scripts/mac/proxy-monitor.sh` | see whether traffic is going through the tunnel |

---

## 5. Things the user did themselves (on my suggestion)

- `~/.claude/settings.json` → `"allow": ["Bash", ...]`, allowing everything
- `/etc/sudoers.d/claude-nopasswd` → **passwordless sudo globally**
  To revoke: `sudo rm /etc/sudoers.d/claude-nopasswd`

---

## 6. Changes on ins (Windows)

| Item | Change | Note |
|---|---|---|
| Sunshine `fec_percentage` | not set (default 20) → **100** | dropped frames in the stream went from 45 to 2, **recommended to keep** |
| Tailscale advertised subnets | none → `101/106/112/117/120/223`, each a /8 | for the Cloud Genshin relay; **already approved in the admin console** |
| IP forwarding | off → **on** (Ethernet + Tailscale adapters) plus registry `IPEnableRouter=1` | **the per-adapter setting resets after a reboot and has to be set again** |
| Windows NAT | none → `New-NetNat TSSubnetNat 100.64.0.0/10` | **NetNat is a Hyper-V component, so it is only available after a reboot** |

Configuration backup: `C:\Program Files\Sunshine\config\sunshine.conf.bak-20260830-215537`

---

## 7. Touched but already reverted (no traces left)

- `AX88179B`'s DNS - was set to `10.76.139.1 1.1.1.1`, **restored to following DHCP**
  (I had misdiagnosed it as "sharing handing out IPv6 DNS"; DNS had been fine all along)
- Internet sharing configuration `AirPort.Enabled` 0→1→**0** (reverted)
- The mistakenly created `/Library/Preferences/SystemConfiguration/com.apple.nat` (no
  extension) - **deleted**
- `/etc/pf.anchors/cnvideo` - deleted, and the `cnvideo` anchor is now empty

**⚠ A mistake I made**: `sudo killall InternetSharing`. I had misdiagnosed it as "sharing's
NAT got wiped" (it was there the whole time; I was looking at the wrong anchor path - the
right one is `com.apple.internet-sharing/shared_v4`), and after killing it **launchd does not
restart it, so the Wi-Fi AP went offline**, and the only fix was to have the user turn
sharing off and on by hand in System Settings → General → Sharing.
**Do not touch system services that have nothing to do with the task at hand again.**

---

## 8. Diagnostic conclusions (not changes, but important)

**This broadband line has no usable route to China.**

The ISP is `AS55392 Internet Multifeed` (transix, an IPv4-over-IPv6 tunnel).

| Target | Path | Result |
|---|---|---|
| Google | home → transix → Google (3 hops) | **6.4 ms, perfect** |
| Wuthering Waves servers | home → transix → IIJ → **everything after IIJ Tokyo is a black hole** | **35-100% packet loss, 2-5 s latency** |

**So WARP has to be on to play Wuthering Waves**; nothing done on this machine can reach that
segment. The user can play on other Wi-Fi networks because those carriers have a working
transit to China.

**A false lead (it fooled me twice, do not fall for it again)**: `www.qq.com` over IPv6 shows
only 10 ms and 0% loss, which looks like "IPv6 goes straight to China" - **in reality those
are CDN nodes in Singapore (240d:c010, Tencent Singapore) and Japan (2404:2280, Alibaba)**,
and the traffic never leaves Southeast Asia. A round trip from Tokyo to Shanghai takes at
least 25 ms at the speed of light, so 10 ms is physically impossible. On top of that,
Wuthering Waves' servers are IPv4-only, so there is no IPv6 path to take.

### 云原神.app(2026-09-09 新增)

桌面上的第四个启动器。作用:WARP 没连就 `warp-cli connect`,然后用 Chrome 打开 `https://ys.mihoyo.com/cloud/`。
主程序是 clang 编译的 arm64 二进制,壳脚本在 `Contents/Resources/run.sh`。
重建:`scripts/mac/make-cloud-genshin-app.sh`。删掉即撤销,不改任何系统设置。
配套的 Chrome 插件见 `docs/CLOUD-GENSHIN-WARP.md`。

### 桌面启动器图标(2026-09-09)

五个桌面 app 都有图标了：串流到ins / 串流到ins-HEVC444 用 Moonlight 图标（444 版带红色角标），云原神用官网图标，强制关闭串流用系统红色停止牌，优盘体检原本就有。
图标源图在 `scripts/mac/icons/`，生成逻辑在 `scripts/mac/lib/app-icon.sh`，两个构建脚本重跑会自动带上。
`强制关闭串流.app` 没有构建脚本，图标是直接写进桌面那份的；重做它时记得也调一下 `set_app_icon`。

### EchoShot: one key, one screenshot (2026-09-09)

The user scores Wuthering Waves echoes one screenshot at a time, dozens in a row, while a
Moonlight stream is fullscreen. He asked for **one** key. Cmd+Shift+3 is three, and he said
so in exactly those terms.

`~/Applications/EchoShot.app` registers a Carbon global hotkey with no modifiers and shells
out to `screencapture -x -t jpg` into `~/Pictures/EchoShots`. The key depends on the physical
layout, checked at launch with `KBGetLayoutType`: **¥** (keycode 93) on this machine's JIS
keyboard, ` (keycode 50) on ANSI. JIS has no key left of 1, so the ANSI default was
unreachable here - it fired for a synthetic keycode 50 and for nothing the user could press.
Built by
`scripts/mac/build-echoshot.sh` from `scripts/mac/EchoShot/main.swift`; the binary is not
committed. A LaunchAgent (`local.ark.echoshot`) starts it at login.

- Carbon's `RegisterEventHotKey` needs no Accessibility or Input Monitoring grant and fires
  over a fullscreen game. Hammerspoon and skhd would both have worked; they cost an install,
  a menu-bar app and an Accessibility grant, which is more than the sixty lines here.
- **Screen Recording must be granted to EchoShot** or every capture writes a zero-byte file.
  The app deletes those, thuds instead of clicking, and writes the reason to
  `~/Pictures/EchoShots/echoshot.log`.
- JPEG, not PNG: the scorer caps uploads at 1 MB and a PNG of this 2772x1280 screen is ~5 MB.
- The chosen key is grabbed system-wide, so it stops typing everywhere else while the app runs.
  `scripts/mac/build-echoshot.sh --off` stops it, `--on` starts it again. The key is
  configurable: `defaults write local.ark.echoshot keyCode -int <keycode>`. Other spare JIS
  keys: 94 = `_`, 102 = 英数, 104 = かな (the last two switch input method).

Nothing else on the Mac changed. `com.apple.screencapture` was briefly repointed at the same
folder and then restored - the defaults are back to stock, and Cmd+Shift+3 still lands on the
Desktop as PNG.
