# 动手之前必读

每次会话自动加载，只放做法；事故经过见 `docs/TOOLING.md`、记忆 `incident-826` / `incident-0914-spent-the-test-resource`，2026-10-10 前的完整版见 `git show 453c0249:CLAUDE.md`。规矩以工具为准（用户 08-26：「写进文档里跟放屁一样」）。

## 硬规矩
1. 一律绝对路径；heredoc 之后 cwd 会重置，不写 `../` 和裸文件名。
2. 游戏机上 PowerShell 用 `pwsh`，不用 `powershell`（5.1 不是 UTF-8，中文必乱）。
3. ssh 送 PowerShell 一律 base64 `-EncodedCommand`，走 `scripts/mac/winps.sh`。
4. `gh api` 的 URL 含 `?` 要加引号。
5. 不许全盘 `rglob`；路径从代码读，常用路径见 `docs/TOOLING.md`。
6. 主动限制输出（超约 37KB 会转存文件）：`head`、只打印要的字段。
7. 游戏机北京时间、Mac 东京时间。过滤日志只用 `arklog.since()` / `since_minutes(path, N)`，不手打时刻；winrun 第一行打印 `[机器时间]`。
8. 远端脚本默认 120 秒上限，要更久用 `winrun.sh --timeout N`，先想清楚为什么。

## 测试资源与验证（0914）
* 波片 / 理智 / 备用体力 / 周本次数是给脚本的，手动一片不许花。
* 手动点一遍不算验证，补丁自己无人值守跑过才算；「确认跑成功再关机」= 跑到成功为止，资源不够就等到回满那一刻。

## 通知与手机页
* 群机器人只发真报警；日报走 Server酱；企业微信私聊不自动发；测试不进他眼。每个标题走哪一路见 `docs/NOTIFICATIONS.md`，加一个 `notifier.send` 先加一行表。
* 不进群的报错都要在 `relay/USER-SWITCHES.txt` 登记判定（已修 / 正常状态 / 任务开关），原因不明的不许压下（`relay/tests/test_mute_verdicts.py`）。
* 手机页：按游戏分页，一行一个形状（名字左、控件右），设置用开关 / 下拉 / 数字，点了立刻回执；规则见 `docs/PHONE-COPY-RULES.md`。

## 三条不许（826）
* 推断出来的字段含义不许写进生产配置：枚举、下标、布尔的含义由代码 / 日志 / 文档确认，找不到就不动。
* 没读回配置文件，不许说「已经设好了」。
* 遇到报错当场说：「X 报了 Y，我改用 Z 继续；X 本身还是坏的 / 已顺手修好。」

## 常用工具（不要重复造）

| 要做什么 | 用什么 |
|---|---|
| 核实鸣潮配置真的落地 | `scripts/mac/okww-check.sh`（底下是 `scripts/windows/okww-landed.py`） |
| 给机器下指令 | 开着：`scripts/mac/order-now.sh '{"action":...}'`（几秒到）；关着：`scripts/mac/order.sh '{...}'`（开机 / 关机前才读，`--clear` 清空）。别手改 `queue/config.json` |
| 发布手机页 | `scripts/mac/deploy-web.sh`（改了 `web/` 必跑） |
| 重算「最新六星满练要多少」表 | `scripts/mac/build-need-tables.py`（新六星出现就跑，写 `web/data/need.json` 后 `deploy-web.sh`；`--rarity 5`、`--char/--weapon`；坑见 `docs/SKLAND-API.md` §8） |
| 手机页验收（发布后跑） | `scripts/mac/phone-accept.py`（模拟器 Safari 量 DOM 对 `docs/HIG-CHECKLIST.md`，浅深各一遍） |
| 一键截图（刷声骸评分） | 按 `¥` 存到 `~/Pictures/EchoShots`；配置 `~/.hammerspoon/init.lua`，仓库存档 `scripts/mac/hammerspoon/init.lua` |
| 查哪个共鸣者用哪套声骸 | `scripts/mac/kuro-echoes.py`（`--dump 文件`）：读 `~/.config/ark/.env` 的 `KUROBBS_TOKEN` + `KUROBBS_DID`，必须是手机 App 抓包那一对；只看得到已装备的 |
| 重编 Fleet Monitor | `scripts/mac/build-fleetmonitor.sh`（改了 `scripts/mac/FleetMonitor/main.swift` 后跑） |
| 串流到 ins 打游戏 | `scripts/mac/stream-ins.sh`（`--relative` 游戏内转视角） |
| 测试只跑终末地某一个任务 | `winrun.sh --py scripts/mac/lib/maaend_only_task.py disable [任务名]` → `run-one.sh MaaEnd` → `... enable`。测试只派那一个任务 |
| 手动跑单个脚本 / 停干净 | `scripts/mac/run-one.sh MAA\|MaaEnd\|OK-WW`（`status` / `stop`），唯一正门，含忙闲闸门；禁裸调 `/api/dispatch/start`、禁 `taskkill`。我的测试跑加 `--test`，测完 `run-one.sh test-off` |
| 在游戏机上跑脚本 | `scripts/mac/winrun.sh --py <本地.py>`（看屏幕用 `--py1`；取文件 `--get '<远端路径>'`） |
| 拉起方舟那个雷电实例 | `scripts/windows/emu-start.py`（方舟在 1000 号实例，adb 7555；双击 `dnplayer.exe` 起的是 0 号） |
| 打月行水 SR-4 | `scripts/windows/sr4-run.py`（游戏机本地跑） |
| 读远端日志 | `from arklog import since, summarise, mtime, OKWW_LOG`；自己拼时间比较会被拒发，相对窗口用 `since_minutes(path, 90)` |
| 在游戏机上跑 PowerShell | `scripts/mac/winps.sh '<脚本>'`（唯一正门，整段 base64） |
| 看游戏机屏幕 / 发按键 | `scripts/mac/wingui.sh shot\|key\|click\|scroll\|focus\|launch` |
| 单跑 OK-WW 某个任务 | `scripts/mac/okww-task.sh --list` 核对下标，再 `okww-task.sh <下标>` |
| 紧急停止一切 | `scripts/mac/estop.sh`（恢复 `--restore`） |
| 部署中继 | `scripts/mac/deploy-relay.sh`（先写 `relay/RELEASE-NOTES.md`；本地闸门跑改动映射到的测试，末尾 `publish-cos.py` 推 COS） |
| 看 COS 上机器会拿到哪一版 | `scripts/mac/publish-cos.py --check` |
| HTML 转图 | `scripts/mac/html2png.sh` |
| 调 AUTO-MAS 接口 | `scripts/mac/mas-api.py`（全部 POST） |
| 看 OK-WW 真正生效的配置 | `winrun.sh --py scripts/mac/lib/okww_effective.py`（OK-WW 自己目录那份不作数） |
| 收工前体检 | `winrun.sh --py scripts/mac/lib/healthcheck.py` |
| 验证闸门自己还活着 | `scripts/mac/guardcheck.sh`（拿已知坏样本喂每道闸门） |
| 翻译任何 id / 枚举 / 下标 | `scripts/mac/lib/idmap.py get <id>`，查不到就停，不按位置猜；登记要 `--source` |
| 读森空岛快照 | `from snapshot import load, is_stale`；刷新只在用户说「刷新」时跑 `refresh_snapshot.refresh()` |
| 核对武器基质 | `scripts/mac/gem-check.py`（按 id 比，不按中文比） |
| 单跑 MaaEnd 基质筛选 | `winrun.sh --py scripts/mac/lib/maaend_essence.py`（`--go` 才真跑；不废弃） |
| 查三个脚本实际会跑什么 | `winrun.sh --py scripts/mac/lib/effective_config.py`（`config-check.py` 只读 MAS 侧，会误导） |
| 盯队列进度 | `winrun.sh --py scripts/mac/lib/queue_events.py`（只能用 winrun，winps 中文会乱） |
| 改手机页任何一条说明 | 先读 `docs/PHONE-COPY-RULES.md`；`lint-repo.sh` 第 8 项会拒 |
| **打活动关 / 打保全派驻** | 先读 `docs/MAA-EVENTS-AND-SSS.md`（矢量突破看 §1.3：驻防锁人、补给、关卡编号对照、收尾领奖）——**动手前读完对应那节**。2026-08-23 指挥打活动关卡了整整一天，全部时间花在摸索上，那天的坑都在里面 |
| 驱动模拟器里的游戏 | `scripts/mac/adbdo.sh tap\|swipe\|shot\|seq`（一步约 1 秒；别用 winrun） |
| 往上游提 issue / 讨论 / PR | `scripts/mac/upstream-post.py rules <repo>` → `dup` → `lint`，只走网页表单；规矩见 `docs/UPSTREAM-ISSUE-RULES.md` |
| 仓库自检 | `scripts/mac/lint-repo.sh` |
| shell 脚本静态检查 | `~/.local/bin/shellcheck -S warning` |

## 中英文（判据是谁读；用户 09-08：「除了 readme 之外的部分都用英文，因为是你看的不是人看的。」）
* 英文：`docs/**`、代码注释与 docstring、脚本打印给我看的话、闸门报错、commit message、文件名。
* 中文：根 `README.md`、推送通知（`ark_relay/texts.py`）、手机页文案（`web/`）、`relay/RELEASE-NOTES.md`；引他原话保留中文原文。
* 注释里的中文只准变少：`scripts/mac/lib/zh_ratchet.py`（登记 `relay/tests/zh-baseline.txt`，lint 第 20 项挡）；碰到哪个文件顺手换英文，用 `scripts/mac/lib/comments_only.py <改前快照> <文件…>` 证明只动了注释。

## 开机后、改中继
* 开机后先看 `docs/NEXT-BOOT.md`，处理完从那里删掉。
* 中继改完立即部署，不要问（`deploy-relay.sh` 自带测试闸门、哈希核对、启动确认）；部署前写 `relay/RELEASE-NOTES.md`，人话、只写这次新增的。
