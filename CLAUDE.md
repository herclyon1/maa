# 动手之前必读

每次会话自动加载，只放现行做法与在用工具。

## 硬规矩
1. 一律绝对路径；heredoc 之后 cwd 会重置，不写 `../` 和裸文件名。
2. 游戏机上 PowerShell 用 `pwsh`，不用 `powershell`（5.1 不是 UTF-8，中文必乱）。
3. ssh 送 PowerShell 一律 base64 `-EncodedCommand`，走 `scripts/mac/winps.sh`。
4. `gh api` 的 URL 含 `?` 要加引号。
5. 不许全盘 `rglob`；路径从代码读，配置清单见 `docs/CONFIG.md` 与 `docs/OPERATIONS.md`。
6. 主动限制输出：`head`、只打印要的字段。
7. 游戏机北京时间、Mac 东京时间。过滤日志只用 `arklog.since()` / `since_minutes(path, N)`，不手打时刻；`winrun.sh` 第一行打印 `[机器时间]`。
8. 远端脚本默认 120 秒上限，要更久用 `winrun.sh --timeout N`。

## 测试资源与验证
* 波片 / 理智 / 备用体力 / 周本次数是给脚本的，手动一片不许花。
* 手动点一遍不算验证，补丁自己无人值守跑过才算。

## 通知与开关
* 群机器人只发真报警；日报走 Server酱；企业微信私聊不自动发；测试不进他眼。每个标题走哪一路见 `docs/NOTIFICATIONS.md`。
* 不进群的报错都要在 `relay/USER-SWITCHES.txt` 登记判定（已修 / 正常状态 / 任务开关），原因不明的不许压下。
* 遥控端已迁至原生 App `~/Claude/ark-remote`；中继每个服务器日在游戏机上重算需求表并发到 COS（`relay/ark_relay/features/needtable/`）。

## 三条不许
* 推断出来的字段含义不许写进生产配置：枚举、下标、布尔的含义由代码 / 日志 / 文档确认，找不到就不动。
* 没读回配置文件，不许说「已经设好了」。
* 遇到报错当场查清根因并说实话。

## 常用工具（不要重复造）

| 要做什么 | 用什么 |
|---|---|
| 部署中继 | `scripts/mac/deploy-relay.sh`（先写 `relay/RELEASE-NOTES.md`；末尾调 `scripts/mac/publish-cos.py` 与 `scripts/mac/purge-cdn.py`） |
| 仓库自检 | `scripts/mac/lint-repo.sh` |
| 给机器下指令 | 开着：`scripts/mac/order-now.sh '{"action":...}'`；关着：`scripts/mac/order.sh '{...}'`（`--clear` 清空） |
| 在游戏机上跑脚本 / PowerShell | `scripts/mac/winrun.sh --py <本地.py>`（脱敏依赖 `scripts/mac/redact.py`）；`scripts/mac/winps.sh '<脚本>'` |
| 看游戏机屏幕 / 驱动模拟器 | `scripts/mac/wingui.sh shot\|key\|click\|scroll\|focus\|launch`；`scripts/mac/adbdo.sh tap\|swipe\|shot\|seq` |
| 手动跑单个脚本 / 停干净 | `scripts/mac/run-one.sh MAA\|MaaEnd\|OK-WW`（`status` / `stop` / `--test` / `test-off`）；盯进度：`scripts/mac/watch-run.sh` |
| 单跑终末地或鸣潮子任务 | 终末地：`winrun.sh --py scripts/mac/lib/maaend_only_task.py disable [任务名]`；鸣潮：`scripts/mac/okww-task.sh --list` / `<下标>` |
| 核实鸣潮配置落地 | `scripts/mac/okww-check.sh`（远端 `scripts/windows/okww-landed.py` 与 `scripts/mac/lib/okww_effective.py`） |
| 紧急停止一切 | `scripts/mac/estop.sh`（恢复 `--restore`） |
| 收工前体检 / 关机前核对 | `winrun.sh --py scripts/mac/lib/healthcheck.py`；`scripts/mac/lib/poweroff_ok.py` |
| 取证据包 / 诊断日志 / 技术日志 | `scripts/mac/evidence.sh`；`scripts/mac/diag-pull.py`；`scripts/mac/techlog.py red` |
| 调 AUTO-MAS 接口 / 契约核对 | `scripts/mac/mas-api.py`；`scripts/mac/lib/automas_contract_watch.py` |
| 串流到 ins / 发通知 / 磁盘清理 | `scripts/mac/stream-ins.sh`；`scripts/mac/push.py`；`scripts/mac/disk-tidy.py` |

## 中英文与提交流程
* 英文：`docs/**`、代码注释与 docstring、脚本输出、commit message、文件名。
* 中文：根 `README.md`、推送通知（`ark_relay/core/texts.py`）、`relay/RELEASE-NOTES.md`；引他原话保留中文原文。
* 中继改完合进 `main` 并部署，部署前写好 `relay/RELEASE-NOTES.md`。
