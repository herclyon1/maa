# MAA 无人值守自动化

跨国远程运维一台游戏自动化机器的完整记录。

- **服务器**：Windows 11，在中国，朋友的机器，每天定时开机跑两次任务后自动关机
- **控制端**：macOS，在日本，通过 Tailscale + SSH 全程遥控
- **被自动化的**：[MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights)（明日方舟）、[MaaEnd](https://github.com/MaaEnd/MaaEnd)（终末地），由 [AUTO-MAS](https://github.com/AUTO-MAS-Project/AUTO-MAS) 统一调度

这个仓库是**存档 + 操作指南**，不是可直接运行的软件。

---

## 目录

| 文档 | 内容 |
|---|---|
| [00-总览.md](docs/00-总览.md) | **全组件总账**:什么在哪台机器、怎么触发;定时与轮询全量清单;铁律 |
| [01-架构.md](docs/01-架构.md) | 整体结构、网络、各组件职责 |
| [02-配置清单.md](docs/02-配置清单.md) | **所有改动过的配置项**：位置、原值、现值、原因 |
| [03-运维手册.md](docs/03-运维手册.md) | 日常操作、远程截图、故障排查 |
| [04-中继设计.md](docs/04-中继设计.md) | 通知中继的设计（**尚未实现**） |
| [05-踩过的坑.md](docs/05-踩过的坑.md) | 所有失败过的尝试和真正的原因 |
| [06-运行时间表.md](docs/06-运行时间表.md) | **一天的每一步**：从米家断电到晚上关机，含核对清单 |

## 脚本

| 脚本 | 用途 |
|---|---|
| [scripts/windows/ark-do.ps1](scripts/windows/ark-do.ps1) | GUI 动作解释器：点击 / 输入 / 截图 / 启动程序 / 关显示器 |
| [scripts/windows/ark-shot.ps1](scripts/windows/ark-shot.ps1) | 单次全屏截图 |
| [scripts/windows/push-wecom.ps1](scripts/windows/push-wecom.ps1) | 推送图片到企业微信 |
| [scripts/windows/setup-tasks.ps1](scripts/windows/setup-tasks.ps1) | 一键创建所需的计划任务 |
| [scripts/mac/edit-json.py](scripts/mac/edit-json.py) | 安全改远程 JSON：定位 → 替换 → 校验 → 结构化 diff |

## 中继

[relay/](relay/) —— 本机模式零依赖，服务器模式加 FastAPI。三种角色：

```bash
python -m ark_relay local     # 游戏机器上：读 history、判定、推送
python -m ark_relay agent     # 游戏机器上：上报事件 + 心跳 + 执行指令
python -m ark_relay server    # 云服务器上：7x24，含心跳超时告警与网页
```

详见 [relay/README.md](relay/README.md)。

---

## 核心结论

**1. Windows SSH 会话没有桌面（session 0 隔离）**
`CopyFromScreen` 直接失败。解法是把动作脚本挂成**计划任务**在交互式会话里跑，SSH 只负责触发：

```bash
scp cmd.txt ins:'C:/ProgramData/ark-cmd.txt'
ssh ins 'schtasks /run /tn "ark-do"'
```

计划任务必须带 `-WindowStyle Hidden`，否则弹出的 PowerShell 控制台会抢焦点并遮住半个屏幕——**自动化把自己要点的目标挡住了**。

**2. 中文经过 heredoc → ssh → PowerShell 会变成乱码**
stdin 被当 GBK 解码。可靠做法：
- 脚本在本地写好，`scp` 上去执行（`.ps1` 里**不要出现中文**，PowerShell 默认按 GBK 读 `.ps1`）
- 用 `findstr`（cmd）而不是 `Select-String`
- 需要返回中文时，在远端 base64 编码，在本地解码

**3. 改配置必须做结构化 diff**
正则替换会漏、会误伤。改完把改动前后的 JSON 都拍平成 `路径 → 值`，对比"新增 / 删除 / 改动"三个数字。本仓库里每次改动都这么核过，抓到过一次真实的漏改。

**4. MaaEnd 的前台控制器要求游戏窗口不被遮挡**
它自己在日志里写着：

```
已连接控制器 [电脑端-前台]
稳定性最好，需要游戏窗口保持在最前且不被遮挡，会完全抢占鼠标
```

所以只要有人用 ToDesk 连着，被控端的会话面板就会盖住右下角按钮，导致任务失败。这是**观察者效应**——无人值守时不会发生。ToDesk 没有关闭该面板的设置（7 个标签页全查过）。

**5. 监督者不能住在被监督者体内**
机器没开机时，跑在这台机器上的任何监控都不存在。
同理，控制链也不能挂在一台会睡觉的机器上——现在所有操作都依赖控制端的 Mac 开着，人一出门就断。详见 [中继设计](docs/04-中继设计.md)。

---

## 密钥

**本仓库不含任何密钥。** 需要的凭据见 [.env.example](.env.example)，实际值不要提交。

| 变量 | 用途 |
|---|---|
| `SERVERCHAN_KEY` | Server酱推送 |
| `WECOM_CORPID` / `WECOM_SECRET` / `WECOM_AGENTID` | 企业微信自建应用 |
| `ANTHROPIC_API_KEY` | 中继的措辞生成（Sonnet 5） |

> 企业微信自建应用需要把调用方 IP 加进「企业可信IP」，否则返回 `errcode=60020`。

---

## 关于占位符

文档里的 `$ARK_HOST`、`100.x.x.x`、`<服务器主机名>` 等是脱敏占位符。
本仓库公开，不写入具体机器地址、主机名和他人姓名。实际值放在本地 `.env`。

```bash
export ARK_HOST=<你的服务器 Tailscale IP>
```

## 状态

- [x] Tailscale + SSH 跨国远程访问
- [x] 远程截图 + 模拟点击（绕过 session 0 隔离）
- [x] AUTO-MAS 配置纠错（超时、模拟器、关卡、通知）
- [x] 通知噪音清理（5+ 条/轮 → 成功 1 条、失败 2 条）
- [x] 开机自启 + 完成后关机
- [x] 企业微信图片推送
- [ ] 无人值守全流程实测验证
- [x] 通知中继（本机模式 + 服务器模式，同一份代码）—— 已实现，待上机实测
- [x] 开机监督（心跳 + watchdog，服务器模式）
- [ ] 部署到云服务器并实测
- [x] 四端 PWA 客户端（看状态 + 发人话指令）—— 已实现，待上机实测
- [x] 人话 → 配置指令（白名单 + 人工确认 + 结构化 diff 校验）
