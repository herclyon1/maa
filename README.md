# 游戏机自动化

一台放在国内的 Windows 机器，每天自己开机两次，把三个游戏的日常刷完，
推个汇报到微信，然后自己关机。我这边是东京的 Mac，用 Tailscale + SSH 管它。
**我的 Mac 关着不影响它自己跑。**

三个游戏分别是 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights)（明日方舟）、
[MaaEnd](https://github.com/MaaEnd/MaaEnd)（终末地）、
[OK-WW](https://github.com/ok-oldking/ok-wuthering-waves)（鸣潮），
由 [AUTO-MAS](https://github.com/AUTO-MAS-Project/AUTO-MAS) 排队跑。
`relay/` 是我自己写的中继，跑在游戏机上，干这些活：

- 读每个脚本**自己的日志**核对到底干成了什么，而不是看进程退没退出
- 开机到队列开跑之间的空档里，把四个程序的更新做掉
- 推汇报和日报；队列跑完、汇报送到了，它负责关机
- 自更新；每次 OK-WW 更新完，把我们的补丁重新贴回去

**这不是给别人用的东西**，路径、账号、时刻表全是照这一台机器写死的。
放 GitHub 上是为了两件事：中继要从这儿自更新，以及我能在手机上改配置。

## 我想改东西，去哪

| 想干什么 | 去哪 |
|---|---|
| 改刷什么关卡、吃不吃药 | [`queue/config.json`](queue/config.json)，网页上直接改，提交后下次开机生效（**记得把 `version` 加一**） |
| 改中继的行为 | `relay/`，改完 `ARK_HOST=<IP> scripts/mac/deploy-relay.sh` |
| 出事了想立刻停 | `scripts/mac/estop.sh` |
| 看机器现在在不在 | Dock 上的 FleetMonitor |
| 远程操作游戏画面 | `scripts/mac/wingui.sh`，用法见 [docs/PLAY-MANUAL.md](docs/PLAY-MANUAL.md) |
| 查机器上的日志 | `scripts/mac/winrun.sh --py`，读日志一律用 `arklog` |

**维护前先开调试模式**，不然队列跑完它就自己关机了：
写 `C:\ProgramData\ark-relay\state\debug-until.txt`，内容是截止时刻；完事记得删掉。

## 踩过的坑

出事先翻 [docs/PITFALLS.md](docs/PITFALLS.md)，很多问题以前栽过一模一样的。
无界面操作（不靠看屏幕）的完整方法见 [docs/HEADLESS.md](docs/HEADLESS.md)。
AUTO-MAS 五个界面各管什么、母本副本的关系见 [docs/AUTOMAS.md](docs/AUTOMAS.md)。
家里网络那个 MTU 黑洞和百兆封顶的实测见 [docs/HOME-NETWORK.md](docs/HOME-NETWORK.md)。

---

## 每日流程

两列时间分别为服务器（北京，UTC+8）与东京（UTC+9），相差 1 小时。

```
服务器  东京    事件
08:40   09:40   米家插座断电
08:45   09:45   通电 → 主板「AC 上电自启」→ 开机 → 自动登录
09:00   10:00   队列「新队列」：明日方舟 → 终末地 → 鸣潮，约 85 分钟
~10:30  ~11:30  推送汇报 → 自动关机
                ── 白天约 11 小时完全关机，期间无任何本机监控 ──
21:20   22:20   BIOS RTC 定时开机（不依赖插座）
21:30   22:30   队列「Evening-MAA」：仅明日方舟，约 45 分钟
~22:20  ~23:20  推送当日日报 → 自动关机
```

带 `~` 的是估算：结束时刻取决于当轮实际耗时，队列结束即推送、推送送达即关机。

机器每天仅运行约 3 小时。明日方舟需一天两次分开运行，否则基建产能溢出。

当前配置：明日方舟关卡 `1-7`、理智药 `0`、剿灭 `Close`；鸣潮刷模拟领域（贝币），
残象聚落只刷落渊南丘。完整配置清单见 [docs/CONFIG.md](docs/CONFIG.md)。

## 推送内容

| 时机 | 内容 |
|---|---|
| 晚班结束 | 📋 当日日报：关卡、掉落、理智、起止时间（双时区）、活动倒计时、次日安排 |
| 白天每轮结束 | 🔎 临时查看（测试期功能，不占用日报名额） |
| 手动触发的轮次结束 | 🔎 标注「手动执行」 |
| 任务失败 | 重试全部结束后推送一条，附诊断 |
| 重试后自愈 | 推送「本次自愈，问题未解决」 |
| 该运行而未运行 | 立即告警 |
| 配置或中继代码更新生效 | 推送回执，说明改动内容与版本 |
| 任务成功 | 静默记账，不推送 |

完整定义见 [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md)，该文档对代码具有优先级。

## 运行约束

这些不是建议，是这套系统的既定行为，代码按此实现：

1. **关机权归中继**：队列结束且汇报送达后由中继关机；除此之外不关机。
2. **配置改动优先于按时开跑**：宁可推迟一轮，也不使用过期配置运行。
3. **更新在开机窗口落地并立即生效**：开机到队列启动之间的空档用于自更新，
   更新后立刻重启进程，不等到下一次开机；生效后立即推送通知。
4. **不使用轮询**：文件、进程、状态变化一律走事件通知，定时事件走精确闹钟。
   现存的唯一周期唤醒是一小时一次的保险丝，不承担任何发现职责。

## 待处理

需要在本仓库之外配置，目前未完成：

- **企业微信推送不可用**（`errcode=60020`）：调用方 IP 不在企业可信 IP 列表内。
  可在企业微信后台补录当前出口 IP（告警正文中会带上），或改用群机器人并配置
  `WECOM_BOT_URL`——群机器人没有可信 IP 名单，不受家宽拨号 IP 变动影响。
  当前全部推送由 Server酱 承担。
- **开机监督未启用**：机器未能开机这件事，机器自身无法发现，该检查放在 GitHub
  Actions（[scripts/watchdog.py](scripts/watchdog.py)）。启用需要在仓库 Secrets
  中配置 `TS_OAUTH_CLIENT_ID`、`TS_OAUTH_SECRET`、`SERVERCHAN_KEY`，并将
  [queue/watchdog.json](queue/watchdog.json) 的 `enabled` 改为 `true`。
  若需让机器整夜开启调试，先将其中的 `pause_until` 改到调试结束当日。

## 下发指令

改 [`queue/config.json`](queue/config.json) 并提交，机器下次开机会读、会应用、
会把结果推给我。**改完必须把 `version` 加一**，否则它当没变化。

能下发哪些指令、怎么写，见 [`queue/README.md`](queue/README.md)。
这个文件在 GitHub 网页上直接就能改，手机也行。

## 目录

| 目录 | 内容 |
|---|---|
| `relay/` | 通知中继源码，运行于游戏机 |
| `relay/tests/` | 关机判定、更新通知、掉落解析的回归测试 |
| `queue/` | 下发给机器的指令与开机监督配置 |
| `scripts/` | 控制端与游戏机两侧的工具脚本 |
| `docs/` | 运维参考、配置清单、故障记录、游戏知识（英文） |

`scripts/mac/check-docs.py` 核对文档与实际状态是否一致：链接是否有效、指令白
名单是否与代码相符、中继读取的环境变量是否都有记录，以及在机器可达时核对路径、
服务、计划任务与配置值。文档与事实不符即视为缺陷。

## 密钥

本仓库不含任何密钥。实际值位于游戏机上的 `relay/.env`，该文件不入库。所需变量
见 [docs/CONFIG.md](docs/CONFIG.md) 的 "Relay environment"。
