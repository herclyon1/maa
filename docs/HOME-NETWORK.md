# The home network in Tokyo: topology, diagnosis, options

Written from measurements taken in the early hours of 2026-08-25. **The point of this
document is that nobody has to diagnose this again.** Every number here was measured on
the real hardware that day or read out of a device log; none of it is guesswork.
Where something is a guess, it says so explicitly.

Related: [AUTOMAS.md](AUTOMAS.md), [PITFALLS.md](PITFALLS.md).

---

## Topology

```
Building fibre (terminates inside the building)
      │
      ▼  wall Ethernet port — plain Ethernet + DHCP, no PPPoE, no captive portal
┌───────────────────────────────────────────────────────────────┐
│ Building router 10.76.139.1                                   │
│   MAC 00:80:6D:8E:97:78 (Century Systems, a Japanese vendor)  │
│   management port closed to the LAN, no way in                │
│   upstream: transix DS-Lite (IPv4 over IPv6)                  │
│   public egress AS55392 Internet Multifeed (Osaka)            │
└───────────────────────────────────────────────────────────────┘
      │  white Ethernet cable
      ▼
┌───────────────────────────────────────────────────────────────┐
│ Foxconn "TV StickL" = Leopalace's Life Stick                  │
│   Amlogic S4 / Android 11 / 2GB RAM                           │
│   eth0  10.76.139.46   ← Realtek RTL8152, **100 Mbps only**   │
│   wlan1 SoftAP, SSID B0029F9B, MTU 1500                       │
└───────────────────────────────────────────────────────────────┘
      │  Wi-Fi
      ▼
   Mac + Android phone (the only two devices in the flat that go online)
```

**The hotspot subnet is re-randomized on every restart** (standard Android tethering
behaviour): 192.168.194.x and 192.168.158.x have both been seen, with the host part
unchanged (the Mac is always .83). **Do not mistake a changed subnet for a changed
device.**

---

## Two independent faults

### 1. MTU black hole — "Wi-Fi is connected but nothing loads"

| Item | Measured |
|---|---|
| Stick `wlan1` (the side the devices attach to) | **MTU 1500** |
| Stick `eth0` | **MTU 1500** |
| **Actual path MTU** (probed from the stick with `ping -M do`) | **1460** (1460 passes, 1468 does not) |
| Does the building router hand out an MTU over DHCP | **No** (`LinkProperties … MTU: 0`) |

**Why 1460**: DS-Lite wraps every IPv4 packet inside IPv6, and the IPv6 header is 40
bytes, so `1500 − 40 = 1460`. That is arithmetic, not coincidence.

Packets of 1461–1500 bytes are dropped silently, and the "fragmentation needed" ICMP
never makes it back → **PMTU black hole**. Small packets (ping / DNS / the start of a
TLS handshake) all get through, so the icon says "connected"; large packets (page
bodies, video, game data) are all lost. **Every device is hit at once, because they all
default to 1500.**

- **Why it used to be fine**: it started the day the building moved to DS-Lite (or
  swapped the router).
- **Why turning WARP on makes it work**: the WARP tunnel has an MTU of 1280, which
  shrinks the packets and so routes around the black hole — **it is not "acceleration"**.
- **Why it sometimes fixes itself for minutes or hours**: presumably the cached path MTU
  expires and the system re-probes, occasionally getting it right. **There is no direct
  evidence for this one; it is a guess.**

### 2. Capped at 100 Mbps

The NIC identifies itself in logcat:

```
USB device attached: vidpid 0bda:8152
mfg/product: Realtek / "USB 10/100 LAN"
```

`0bda:8152` is an **RTL8152, a 100 Mbps chip** (gigabit would be `0bda:8153`). Measured
download is 10.8 MB/s ≈ 86 Mbps, exactly line rate for 100 Mbps minus overhead.

**But that 100 Mbps port is not the bottleneck — the LEONET line itself tops out at
100Mbps.** Japanese sources agree: レオネット uses either **VDSL方式** or
**LAN配線方式**, and both are capped at 100Mbps. So 86–90 Mbps **is line rate for this
connection; it is already maxed out**.

**Conclusion: a gigabit dock or a gigabit router buys exactly zero extra speed. Do not
spend money on this to go faster.**

(From the 2026-08-25 record: at one point I had verified only "the stick is 100 Mbps" and
inferred from that "the line may well be gigabit and the user is getting a tenth of it".
That was wrong — I had not looked up LEONET's service specification. Lesson recorded in
[PITFALLS.md](PITFALLS.md) and `trust-the-log-over-plausible-theories`.)

---

## Already ruled out (do not try these a second time)

| What was tried | Result |
|---|---|
| Different DNS (Alibaba / DNSPod / 1.1.1.1) | The three CDN nodes already had 0% loss at 6–16ms; **only the game gateway is bad**, and the gateway IP comes from the server list, so DNS cannot change it |
| Routing over IPv6 (for the China-server games) | The Wuthering Waves domains have **no AAAA records at all**, and the client gets no v6 egress |
| Playing remotely on the machine in Ürümqi | Tokyo → Ürümqi averages 307ms, peaks at 1131ms, 5% loss; unplayable for an action game |
| WARP | Only shrinks the packets; the side effect is a longer path, and it has taken remote access down before |
| Changing the stick's MTU without root | `ip link set` / `ndc setmtu` / `cmd wifi` / `settings` all refuse or do not exist |

**The lag on China-server games is a separate matter**: `traceroute` shows all 6 hops
inside Japan under 22ms with zero loss, and 1500ms as soon as it enters China Telecom's
163 backbone (`202.97.x`). That is congestion on Telecom's international egress, and it
**has nothing to do with the MTU or this stick**; nothing changed at home can cure it.

---

## Options

Facts up front: **Leopalace lets residents attach their own router**, and that is the
normal thing residents do. Japanese guides consistently point out that **the speed
bottleneck on LEONET is the Life Stick**, and that moving the wall cable to your own
device fixes it; the letting agent said the same at the time.

> **To be clear first: bypassing the stick will not make it faster** — LEONET is 100 Mbps
> to begin with. What the two options below solve is **the phone's MTU** and **the
> stick's instability**, not speed. So **the cheapest 100 Mbps adapter is enough**.

### Option A: USB-C Ethernet adapter + Mac sharing (best when there are only two devices)

Adapter into the Mac, Mac straight into the wall port, then hand the network to the phone
with macOS "Internet Sharing".

- **The phone's MTU fixes itself**: today the "fragmentation needed" ICMP never comes back
  from upstream, so devices cannot learn 1460; with the Mac acting as the router **that
  ICMP is emitted by the Mac itself, one hop from the phone, and cannot be filtered**, so
  the phone learns the correct MTU automatically, **with nothing to change on the phone**.
- Cost: the Mac has to stay on.
- Apple Japan sells the Belkin USB-C to Gigabit / 2.5Gb Ethernet adapters (covered by
  Apple's return policy), but **the line is only 100 Mbps, so the 2.5G one is a waste**.

### Option B: buy a router

Consumer routers **do MSS clamping by default**, so every device in the flat is fixed
automatically and the Mac does not have to stay on. Every vendor (Buffalo / TP-Link /
Elecom / NEC Aterm / IODATA / ASUS) has a setup guide for use on LEONET.

**No need to buy gigabit**: LEONET is capped at 100Mbps (Japanese measurements after
swapping in a router report 82Mbps down, which agrees). A cheap one will do.

### Option C: fix the stick itself — not recommended

- **Root is a dead end**: `sys.oem_unlock_allowed=1` (so it can be unlocked), but after
  unlocking **there is no stock boot image to patch**; `boot_a` is `brw------- root root`
  with SELinux Enforcing, so adb (uid 2000) cannot read it; and searching the web turns up
  **no public firmware for ts401 / TVcore / LEONET**.
- **Flashing Linux is unrealistic**: the SoC is an Amlogic S4 (the S905Y4 family), and
  `ophub/amlogic-s9xxx-armbian`'s support list **does not include S905Y4**; mainline
  kernel support for S4 is still in development. ARM boxes are not like x86 — **every
  board needs its own device tree DTB**, and this ODM stick has no public DTB. Wi-Fi is
  Broadcom over SDIO (`bcmsdh_sdmmc`), and AP mode most likely will not come up on
  mainline → **wired would work, Wi-Fi would be gone**.
- **A backup is possible, but needs different gear**: Amlogic **maskrom mode** (hold the
  RESET button on the stick) + a USB male-to-male cable + a Windows PC, using
  `update mread store <partition> normal <offset> <size> <output file>` to read partitions
  out. **This is the only way back before flashing**, and adb cannot do it.

---

## How to connect to the stick (use this directly next time)

On the TV: Settings → System → About → tap "Android TV OS build" 7 times → Developer
options → turn on **USB debugging**. Then:

```bash
adb connect 10.76.139.46:5555     # note: the eth0 side; 5555 is not open on the hotspot side
```

Tick "always allow" on the TV. platform-tools can be downloaded directly, no brew needed:
`dl.google.com/android/repository/platform-tools-latest-darwin.zip`

Once connected you can read: `ifconfig -a` (MTU per interface), `dumpsys wifi` (SoftAP
state), `ip neigh` (who is attached), `logcat` (NIC model, tethering events),
`ping -M do -s N` (the real path MTU). **Nothing can be changed**: uid 2000 has no
CAP_NET_ADMIN.

---

## Current setting

Mac: `sudo networksetup -setMTU en0 1460`. Measured at 1460 with the DF flag, 20 packets,
0% loss, download 9.6–10.8 MB/s; at 1200 it is 9.0–10.2 MB/s, **a difference inside the
noise — both saturate the 100 Mbps port**. 1460 is the exact ceiling with no headroom; if
it ever plays up again, drop to 1400.
