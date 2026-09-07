# 游戏机自动化

一台在乌鲁木齐的 Windows 机器每天自动开机两次，跑三款游戏的日常任务，把结果推到
手机上，然后自动关机。控制端是东京的一台 Mac，经 Tailscale + SSH 远程管理。
两地有一小时时差，文档里凡是写时刻的地方都会注明是哪边的钟。

被自动化的是 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights)（明日方舟）、
[MaaEnd](https://github.com/MaaEnd/MaaEnd)（终末地）与
[OK-WW](https://github.com/ok-oldking/ok-wuthering-waves)（鸣潮），
由 [AUTO-MAS](https://github.com/AUTO-MAS-Project/AUTO-MAS) 统一调度。

`relay/` 是自建的通知中继，作为 Windows 服务跑在游戏机上：读各脚本自己的日志核对
运行结果、在开机到队列启动之间把各程序更新完、推汇报和日报、队列跑完关机。

这是个人项目，一个人维护。它不追求通用——很多判断依赖那台机器的具体环境。

## 目录

| 目录 | 内容 |
|---|---|
| `relay/` | 中继源码与 83 个测试 |
| `queue/` | 下发给机器的指令（版本号一变大就整批应用） |
| `scripts/mac/` | 控制端工具：部署、远程执行、看屏幕、拉日志 |
| `scripts/win/` | 跑在游戏机上的工具：派发闸门、桌面开关 |
| `web/` | 手机遥控页面，发布在 GitHub Pages |
| `docs/` | 全部文档，索引见 [docs/README.md](docs/README.md) |

## 从哪读起

* 要动手改东西：先读 [CLAUDE.md](CLAUDE.md)（死命令和工具表），再读
  [docs/TOOLING.md](docs/TOOLING.md)（用工具的规矩）。
* 想知道它怎么运转：[docs/OPERATIONS.md](docs/OPERATIONS.md)。
* 出了问题：先搜 [docs/PITFALLS.md](docs/PITFALLS.md)，多半栽过。

## 部署

中继部署到游戏机（改完代码就跑这个，它自己会跑测试、核对哈希、重启服务并确认起来了）：

```bash
export ARK_HOST=<游戏机的 Tailscale IP>
scripts/mac/deploy-relay.sh
```

跑之前必须先写 `relay/RELEASE-NOTES.md`——那段文字就是推到手机上的更新说明，
不写会被拒绝部署。部署成功后它会自动清空。

手机页发布到 GitHub Pages：

```bash
scripts/mac/deploy-web.sh
```

## 改配置

**不要直接编辑机器上的配置文件。** 三个游戏的配置有母本和副本之分，改错那份等于没改；
终末地和鸣潮的「快速配置」是关的，从 AUTO-MAS 侧改它们不生效。规程见
[docs/CHANGE-CONFIG.md](docs/CHANGE-CONFIG.md)，配置清单见
[docs/CONFIG.md](docs/CONFIG.md)，查真正生效的值跑
`scripts/mac/winrun.sh --py scripts/mac/lib/effective_config.py`。

日常改设置走手机页；命令行改走 `queue/config.json`（抬版本号，中继下次开机整批应用）。

## 自检

提交前跑这两个，它们是硬闸门：

```bash
scripts/mac/lint-repo.sh
```

```bash
scripts/mac/guardcheck.sh
```

前者 13 项（测试全绿、无死代码、静态检查、文案规矩、文档和脚本都有入口……），
后者验证那些闸门本身还活着——闸门坏了不出声比没有闸门更糟。

## 许可

本仓库 MIT，见 [LICENSE](LICENSE)。`relay/ark_relay/okww_files/` 下是上游 OK-WW 的
源码，AGPL-3.0，版权归上游作者。
