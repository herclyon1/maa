# 动手之前必读

这个文件每次会话自动加载。放这里的都是**已经犯过、代价真实**的错。
详细出处见 `docs/TOOLING.md` 和 memory `incident-826`。

## 硬规矩（违反过的次数写在后面）

1. **一律用绝对路径。**（826 当天违反 **36 次**，是当天最高频的问题）
   每个 heredoc 之后 shell 的 cwd 会被重置，相对路径必然失效。
   写命令时第一件事就是 `cd /Users/herclyon/Claude/maa-automation`，
   或者干脆全程绝对路径。**不许写 `../` 或裸文件名。**

2. **游戏机上的 PowerShell 一律 `pwsh`，不许 `powershell`。**（违反 6 次）
   5.1 默认不是 UTF-8，读中文 JSON 必失败、输出必乱码。

3. **ssh 送 PowerShell 一律 base64 `-EncodedCommand`。**（违反 5 次）
   内联命令要穿过 bash → ssh → cmd → PowerShell 四层，每层啃一遍引号。
   照抄 `scripts/mac/winrun.sh` 里的 `run_remote_ps()`。

4. **`gh api` 的 URL 含 `?` 必须加引号**，否则 zsh 当通配符。（违反 2 次）

5. **不许全盘 `rglob` 找文件。**（违反 1 次，超时 10 分钟且一无所获）
   路径从代码里读，常用路径见 `docs/TOOLING.md`。

6. **主动限制输出量。** 单次超过约 37KB 会被转存到文件而不是显示。
   用 `head`、只打印需要的字段。（违反 2 次）

7. **游戏机是北京时间，我是东京时间，差一小时。**（违反 4 次）
   跨零点还会差一整天。过滤日志一律用 `arklog.since()`，它用机器自己的钟。
   第 4 次（08-27）是**手打的时刻窗口**抄了手机上的东京时间，
   `since()` 老老实实返回 0 行，被我读成「什么都没发生」。现在：
   winrun 每次运行第一行打印 `[机器时间]`；`since()` 遇到未来起点、
   遇到「窗口之后一行都没有」、遇到解析不出任何时间戳，一律抛异常。
   **能用 `since_minutes(path, N)` 就别手打时刻。**

8. **远端脚本默认 120 秒上限。**（违反 1 次，卡十分钟期间用户无法打断）
   真需要更久要 `winrun.sh --timeout N`，并且先想清楚为什么这么久。

> 上面这些**已经做成工具**了，见下面的工具表。用户 2026-08-26 的原话：
> 「写进文档里跟放屁一样」——所以规矩以工具为准，这段只是索引。

## 三条不许（826 事故的直接教训）

* **不许把「我推断出的字段含义」当事实写进生产配置。**
  枚举、下标、布尔的含义必须由代码/日志/文档确认。
  找不到就问用户，**不要动手**。
* **不许在没读回配置文件的情况下说「已经设好了」。**
  2026-08-26 发现 OK-WW 的梦魇净化「三令五申检查通过」，
  实际配置文件从 08-24 起就没被写过——当时只是嘴上说了。
* **遇到报错必须当场告诉用户**，格式：
  「X 报了 Y，我改用 Z 继续；X 本身还是坏的 / 已顺手修好。」
  不许绕过去就不提。

## 常用工具（不要重复造）

| 要做什么 | 用什么 |
|---|---|
| 在游戏机上跑脚本 | `scripts/mac/winrun.sh --py <本地.py>`（要看屏幕用 `--py1`） |
| **读远端日志** | `from arklog import since, summarise, mtime, OKWW_LOG`（winrun 自动送上机器）。**自己拼 `l[:19] > "..."` 或 `datetime.now()` 会被拒绝发送**；相对窗口用 `since_minutes(path, 90)` |
| **在游戏机上跑 PowerShell** | `scripts/mac/winps.sh '<脚本>'` —— 唯一正门，整段 base64。**不许再手拼 ssh + 引号** |
| 看游戏机真实屏幕 / 发按键 | `scripts/mac/wingui.sh shot\|key\|click\|scroll\|focus\|launch` |
| 单跑 OK-WW 的某个任务 | `scripts/mac/okww-task.sh --list` 核对下标，再 `okww-task.sh <下标>` |
| 取游戏机上的文件 | `scripts/mac/winrun.sh --get '<远端路径>'` |
| 紧急停止一切 | `scripts/mac/estop.sh`（恢复 `--restore`） |
| 部署中继 | `scripts/mac/deploy-relay.sh`（先写 `relay/RELEASE-NOTES.md`） |
| HTML 转图 | `scripts/mac/html2png.sh` |
| 调 AUTO-MAS 接口 | `scripts/mac/mas-api.py`（全部 POST） |
| **看 OK-WW 真正生效的配置** | `scripts/mac/winrun.sh --py scripts/mac/lib/okww_effective.py` —— OK-WW 自己目录那份跑前会被 AUTO-MAS 整个换掉，**不作数** |
| **收工前体检** | `scripts/mac/winrun.sh --py scripts/mac/lib/healthcheck.py` —— 补丁在不在、临时配置有没有改回来、明早能不能跑 |
| **验证闸门自己还活着** | `scripts/mac/guardcheck.sh` —— 拿已知坏样本喂每道闸门，断言它必须拒绝。**闸门坏了不会吭声**，2026-08-27 就发现「全盘扫描」那道闸只认反斜杠，`Path("C:/")` 直接穿过去 |
| **翻译任何 id / 枚举 / 下标** | `scripts/mac/lib/idmap.py get <id>` —— 查不到就停下，**不许按位置对齐去猜**。登记要 `--source` |
| **读森空岛快照** | `from snapshot import load, is_stale` —— `load` 自己会把数据年龄打出来。**刷新只在用户说「刷新」时跑** `refresh_snapshot.refresh()`，不许挂在读取路径上自动拉（那是轮询） |
| **核对武器基质** | `scripts/mac/gem-check.py` —— 武器自己在 `skillInfos[].gemTagId` 里声明要哪三条。**按 id 比不按中文比**：森空岛自己两处命名不一致（attr_magicdam 在武器栏叫「法术提升」、在基质栏叫「法术伤害提升」），按中文比会把装对的判成错的 |
| **单跑 MaaEnd 基质筛选** | `winrun.sh --py scripts/mac/lib/maaend_essence.py`（`--go` 才真跑）—— 自导航到基质页，锁毕业词条；**不废弃**，废弃没给开关 |
| **查三个脚本实际会跑什么** | `winrun.sh --py scripts/mac/lib/effective_config.py` —— 按 `IfQuickConfig` 和 `StageMode` 分支取**真正生效**的那一份。`config-check.py` 只读 MAS 侧，快速配置关掉之后它会误导人 |
| **盯队列进度** | `winrun.sh --py scripts/mac/lib/queue_events.py` —— 只吐增量事件，配 Monitor 挂后台。**必须用 winrun 不能用 winps**：winps 走 936 控制台，中文会变「杩涚▼」 |
| **改手机页任何一条说明** | 先读 `docs/手机页文案的规矩.md`——只写「这个开关干什么、改了会怎样」，不写上游/版本号/日期/我的口吻。`lint-repo.sh` 第 8 项会拒 |
| **打活动关 / 打保全派驻** | 先读 `docs/MAA-打活动关与保全派驻.md`——**动手前读完对应那节**。2026-08-23 指挥打活动关卡了整整一天，全部时间花在摸索上，那天的坑都在里面 |
| **驱动模拟器里的游戏（点/滑/截图）** | `scripts/mac/adbdo.sh tap\|swipe\|shot\|seq` —— 走复用 ssh，一步约 1 秒；**别用 winrun 干这个**，它走计划任务一步 10 秒 |
| 仓库自检 | `scripts/mac/lint-repo.sh` |
| shell 脚本静态检查 | `~/.local/bin/shellcheck -S warning` |

## 开机后先看 docs/待查.md

里面是上次收工时没查完、要在有机器的时候查的事。处理完就从那里删掉。

## 改中继的流程

改完 → **立即部署，不要问**（`deploy-relay.sh` 自带测试闸门 + 哈希核对 + 启动确认）。
部署前必须写 `relay/RELEASE-NOTES.md`：**用人话、只写这次新增的**，
部署成功后它会被自动清空，逼下次重写。
