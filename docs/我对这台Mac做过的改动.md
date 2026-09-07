# 我对这台 Mac 和 ins 做过的改动

> 由 Claude 维护。**每次改动系统级设置都要更新这份文件。**
> 最后更新：2026-09-08

---

## 一、开机自启的东西（唯一一个）

### 热点绕过 WARP　`local.hotspot-bypass`

| | |
|---|---|
| 加载脚本 | `/usr/local/libexec/hotspot-bypass.sh` |
| 启动项 | `/Library/LaunchDaemons/local.hotspot-bypass.plist` |
| 日志 | `/var/log/hotspot-bypass.log` |
| 触发 | **事件驱动，无轮询**：开机(`RunAtLoad`) + `WatchPaths` 监听三个文件 |

**WatchPaths 监听的文件**（覆盖全部会让规则失效的场景）：
- `/var/run/resolv.conf` —— 换网卡、切网络、新 DHCP 时被重写
- `/Library/Preferences/SystemConfiguration/com.apple.nat.plist` —— 互联网共享开关变化（它重载 pf 会冲掉锚点）
- `/Library/Preferences/SystemConfiguration/preferences.plist` —— 网络服务配置变化

**⚠ 不许改成 `StartInterval`**——用户早有禁令：不许默认轮询。

**解决什么**：开着 Cloudflare WARP 时，连 Mac 热点的手机完全没网。

**为什么会这样**：WARP 在 pf 里立了 `block drop in all` / `block return out all`，
只放行自己隧道的流量。手机经 Mac 转发的包不匹配任何放行规则 → 被丢弃并回 RST。

**三个叠加的问题（缺一不可，我前两次各只解决一个所以都失败）**：
1. WARP 的兜底拒绝 → 规则要装在 `com.apple/` 命名空间，
   因为 `/etc/pf.conf` 的 `anchor "com.apple/*"` 排在 WARP 动态插入的锚点**之前**
2. WARP 隧道 MTU 只有 1300，手机以为 1500 → `scrub max-mss 1240`
3. **包出网卡前已被 WARP 封装成 QUIC**（en6 上只看得到到 `162.159.198.2:443` 的加密流量）
   → 必须 `route-to` 在**入口**就钉死出口，写在「出网卡时放行」永远匹配不上

**装载的规则**（网卡和网关由脚本自动探测，换网卡不会失效）：
```
scrub in on <bridge> all max-mss 1240
pass in quick on <bridge> route-to (<uplink> <gw>) all tag HOTSPOT keep state
pass out quick on <uplink> tagged HOTSPOT keep state
```

**手动操作**：
```bash
sudo /usr/local/libexec/hotspot-bypass.sh status    # 看当前状态
sudo /usr/local/libexec/hotspot-bypass.sh unload    # 临时停用
sudo /usr/local/libexec/hotspot-bypass.sh load      # 重新启用
```

**彻底卸载**：
```bash
sudo launchctl bootout system/local.hotspot-bypass
sudo rm /Library/LaunchDaemons/local.hotspot-bypass.plist /usr/local/libexec/hotspot-bypass.sh
sudo pfctl -a 'com.apple/hotspot-bypass' -F all
```

---

## 二、改过的系统设置

| 项目 | 原值 | 现值 | 还原命令 |
|---|---|---|---|
| F 键行为 | 媒体键优先 | **标准功能键**（直接按 F5 就是 F5） | `defaults write -g com.apple.keyboard.fnState -bool false` |
| 右下角热区 | 快速备忘录(14) | **停用**(1) | `defaults write com.apple.dock wvous-br-corner -int 14 && killall Dock` |
| Dock 固定程序 | 21 个出厂默认 | **8 个**（按 knowledgeC 实际使用时长选） | 见下方备份 |
| Tailscale 接收子网路由 | 关 | **关**（中途开过，已关回） | — |

**Dock 备份**：`~/Claude/maa-automation/.dock-backup-20260905-025845.plist`
```bash
cp ~/Claude/maa-automation/.dock-backup-20260905-025845.plist ~/Library/Preferences/com.apple.dock.plist && killall Dock
```

**当前 Dock**：Claude / Chrome / 鸣潮 / WeChat / 明日方舟 / System Settings / Terminal / NeteaseMusic

---

## 三、桌面上的启动器（我改过内容）

`串流到ins.app`、`串流到ins-HEVC444.app`

**改了两处**（画质参数一字未动）：
- `--performance-overlay` → **`--no-performance-overlay`**（关掉左上角浮层）
- 新增 **`--capture-system-keys always`**（⌘ 映射成 Win 键并透传）

**⚠ 主可执行文件必须是编译的 Mach-O，不能是 shell 脚本**——写成脚本双击会弹
「需要安装 Rosetta」，因为 LaunchServices 判不出架构。

**要改参数改构建脚本再重跑，别直接改 app**：
```bash
~/Claude/maa-automation/scripts/mac/make-stream-apps.sh
```
原二进制备份：`~/Claude/maa-automation/.launcher-backup-20260830-232059/`

---

## 四、我建的脚本

| 路径 | 用途 |
|---|---|
| `scripts/mac/make-stream-apps.sh` | 生成/更新桌面串流启动器 |
| `scripts/mac/cn-route-pf.sh` | 云原神走 ins 中转（**默认不开，手动 on/off**） |
| `scripts/mac/proxy-monitor.sh` | 看流量走没走隧道 |

---

## 五、用户自己做的（我提的建议）

- `~/.claude/settings.json` → `"allow": ["Bash", ...]` 全量放行
- `/etc/sudoers.d/claude-nopasswd` → **全局免密 sudo**
  撤销：`sudo rm /etc/sudoers.d/claude-nopasswd`

---

## 六、ins（Windows）上的改动

| 项目 | 改动 | 说明 |
|---|---|---|
| Sunshine `fec_percentage` | 未设置(默认20) → **100** | 串流废帧从 45 次降到 2 次，**建议保留** |
| Tailscale 宣告子网 | 无 → `101/106/112/117/120/223` 各 /8 | 给云原神中转用；**后台已批准** |
| IP 转发 | 关 → **开**（以太网+Tailscale 网卡）+ 注册表 `IPEnableRouter=1` | **重启后网卡那项会重置，要重设** |
| Windows NAT | 无 → `New-NetNat TSSubnetNat 100.64.0.0/10` | **NetNat 属 Hyper-V 组件，重启后才可用** |

配置备份：`C:\Program Files\Sunshine\config\sunshine.conf.bak-20260830-215537`

---

## 七、动过但已还原的（不留痕）

- `AX88179B` 的 DNS —— 曾设为 `10.76.139.1 1.1.1.1`，**已还原为跟随 DHCP**
  （当时误判成「共享下发 IPv6 DNS」，其实 DNS 一直是好的）
- 互联网共享配置 `AirPort.Enabled` 0→1→**0**（已还原）
- 误建的 `/Library/Preferences/SystemConfiguration/com.apple.nat`（无扩展名）—— **已删除**
- `/etc/pf.anchors/cnvideo` —— 已删除，`cnvideo` 锚点已清空

**⚠ 我犯过的错**：`sudo killall InternetSharing`。当时误判「共享的 NAT 被冲掉了」
（其实一直在，是我查错了锚点路径——正确的是 `com.apple.internet-sharing/shared_v4`），
杀掉后 **launchd 不会自动拉起，Wi-Fi AP 就此下线**，只能让用户在
系统设置 → 通用 → 共享 里手动关再开。**别再动跟当前任务无关的系统服务。**

---

## 八、诊断结论（不是改动，但很重要）

**这条宽带没有能用的对华线路。**

ISP 是 `AS55392 Internet Multifeed`（transix，IPv4-over-IPv6 隧道）。

| 目标 | 路径 | 结果 |
|---|---|---|
| Google | 家 → transix → Google（3跳） | **6.4ms 完美** |
| 鸣潮服务器 | 家 → transix → IIJ → **IIJ东京之后全黑** | **35~100% 丢包，2~5 秒延迟** |

**所以必须开 WARP 才能玩鸣潮**，本机做任何事都够不着那段路。
用户在别处 Wi-Fi 能玩，是因为那些运营商有正常的对华转接。

**假线索（栽过两次，别再上当）**：`www.qq.com` 的 IPv6 只有 10ms、0% 丢包，
看着像「IPv6 直达中国」——**实际是新加坡（240d:c010，腾讯新加坡）和日本（2404:2280，阿里）
的 CDN 节点**，根本没出东南亚。东京到上海光速往返最少 25ms，10ms 物理上不可能。
而且鸣潮的服务器是纯 IPv4，没有 IPv6 可走。
