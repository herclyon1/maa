# ark-relay

The notification relay. Runs on the game machine as the Windows service
`ark-relay`; zero dependencies beyond the standard library (pywin32 for the
service wrapper, already installed there).

```
failure   push once, after the retries settle, with a one-line plain diagnosis
recovery  push "recovered this time, problem not solved" - self-healing != fine
success   silent, recorded
daytime   one interim summary per round, manual rounds included, no quota used
evening   the daily report after the last round; resent next day if it never went
countdown every summary carries the event's remaining time, from MAA's own cache
no boot   NOT this machine's job - GitHub Actions + Tailscale lastSeen
```

[docs/NOTIFICATIONS.md](../docs/NOTIFICATIONS.md) is the authority on all of the
above.

## Modules

Shared parts live in `ark_relay/core/`, feature modules live flat in `ark_relay/features/`.

| File | Responsibility |
|---|---|
| `service.py` | 开机阶段编排（`ArkRelayService.main`）与停止收尾（`SvcStop` / `SvcShutdown`），供应用宿主复用 |
| `automas_keeper.py` | 主循环唤醒、历史目录监听、跨零点恢复与历史日志补传、AUTO-MAS 后端保活与补丁维护（`automas_files/`） |
| `procwatch.py` | WMI 进程启动监听、订阅异常诊断、系统关机事件（1074 / 1075）识别 |
| `config.py` | 环境变量与路径配置读取、原子落盘工具、队列名归一 |
| `statestore.py` | 唯一状态档案 `state/state.json`、`relay.log` 大小轮转与跨卷读取、每日技术日志 `tech/<day>.md` |
| `ledger.py` | 运行账本（`State`）、各游戏记录行转换、失败消息与日报正文拼装 |
| `summary.py` | 摘要文案整理（含可选补充行） |
| `collector.py` | 扫描 AUTO-MAS 的 `history` 目录、汇总各游戏日志解析器与 HTTP 读取辅助 |
| `engine.py` | 核心轮次推进：记账、阶段播报、日报时点、自动关机与延迟更新衔接 |
| `mastercfg.py` | AUTO-MAS 配置契约核对（含 v5.8 YAML 读取）与 MaaEnd / MAA / OK-WW 母本安全读写 |
| `plan.py` | 直接读取 AUTO-MAS 排班与队列定义 |
| `notify.py` | 企业微信机器人与 Server酱通知发送、路由分流及短时网络截断重试 |
| `desktop.py` | 桌面会话截图、窗口读屏助手与 WMI `python.exe` 进程表查询 |
| `skland.py` | 森空岛客户端与终末地角色练度读取 |
| `texts.py` | 全部群通知与日报固定文案、报错原因大白话翻译 |
| `watch.py` | 目录变更原生通知（Windows ctypes / macOS kqueue） |
| `wuwa_tables.py` | 鸣潮周本、凝素领域、无音区序号与名称掉落对照表 |
| `handle.py` | 运行结果记账、自愈核销、漏跑核对、未决故障告警与紧急停止补记 |
| `errwatch.py` | 中继自身 WARNING / ERROR 实时转群、已修故障复发标记、报警抄送落盘与上传 |
| `macpush.py` | 群报警同步直送 Mac 收件端与离线补发队列 |
| `banners.py` | 三游戏卡池抓取公共框架、连续性与官方兜底核对 |
| `arknights.py` | 明日方舟卡池与官方通讯解析 |
| `endfield.py` | 终末地特许寻访卡池与公告解析 |
| `wuwa.py` | 鸣潮卡池、版本资讯海报读图与历史台账核对 |
| `echofarm.py` | 鸣潮 4C 声骸定时刷取与配置自动还原 |
| `essence.py` | 终末地基质刷取目标集齐后自动切刷垫子模式 |
| `evidence.py` | 运行故障证据包打包上传与每日完整日志备份上传 |
| `task_shots.py` | 终末地每个子任务结束时的桌面截图留档 |
| `gameupdate.py` | 队列后游戏客户端更新调度与终末地母本开关核对 |
| `gameupdate_games.py` | 三游戏客户端启动器更新动作实现 |
| `efstart.py` | 终末地启动器辅助拉起与 AUTO-MAS 启动方式对齐 |
| `maaend_launch.py` | 终末地 1280×720 窗口启动与收工恢复全屏设置核对 |
| `trigger.py` | 识别脚本触发来源（排班队列、中继补跑、人工手动运行） |
| `maintenance.py` | 三游戏官方停服维护公告与终末地开服状态读取 |
| `makeup.py` | 明日方舟与终末地失败后的自动补跑及当天标记 |
| `activity.py` | 鸣潮每日活跃度不足 100 时的晚班补齐与告警 |
| `collect_retry.py` | 终末地自动采集失败路线单独补跑（最多两轮） |
| `modes.py` | 调试模式与「下次跑完不关机」开关读写 |
| `hardlock.py` | 硬锁（11-26 用户令）：锁着不派发、不补跑、不收信箱指令（调试模式除外）、不自更新；定时开机按设计关机；只有两步合格的解锁记录才解除 |
| `needtable.py` | App 库存页最新六星满练需求表重算与上传 |
| `okww_overlay.py` | 鸣潮 `ok_tasks/` 扩展补丁安装与上游源码锚点核对（`okww_files/`） |
| `phone.py` | 手机遥控状态组装、信箱长连接与命令队列、开机 `queue/config.json` 收件、COS 与 ntfy 同步、心跳与月卡提醒 |
| `resources.py` | 手机页森空岛会话与当日运行次数统计 |
| `commands.py` | 远端命令白名单、参数校验与结构化回滚保护 |
| `redbutton.py` | 紧急停止按钮（estop）执行与 AUTO-MAS 接口调用封装 |
| `snapshot.py` | 手机端展示用的全量脚本与队列配置快照 |
| `preupdate.py` | 开机窗口预更新总控、AUTO-MAS 自更新与鸣潮 OK-WW 脚本更新及依赖补齐 |
| `report.py` | 每日战报汇总发送与各代码版本战绩计分板 |
| `runwatch.py` | 在跑任务超时巡查与整条队列超时告警 |
| `collect_watch.py` | 实时盯 MaaEnd 框架日志记录采集路线成败并驱动截图与看门狗 |
| `display_wake.py` | 启动器拉起终末地期间定时唤醒显示器防止黑屏卡窗 |
| `maa_start_watchdog.py` | 明日方舟开游戏卡死 5 分钟看门狗 |
| `maaend_watchdog.py` | 终末地插件崩溃或框架日志停更 10 分钟看门狗 |
| `queues.py` | 队列开关改写与终末地失败重试次数固定守护 |
| `stagegate.py` | 明日方舟关卡导航可达性预检门 |
| `selfcheck.py` | 开机 12 项自检、早晚班收工体检、运行输入留档与发版前误报回放闸 |
| `machinecheck.py` | 部署后上机自动核对注册与触发框架（核对项见 machinechecks） |
| `selfupdate.py` | 按 `relay/manifest.json` 比对哈希自更新代码 |
| `shutdown.py` | 早晚班收工自动关机判定与关机被取消告警 |
| `collector_maa.py` | 明日方舟 MAA 运行日志与掉落解析 |
| `collector_maaend.py` | 终末地 MaaEnd 历史日志与框架日志任务轨迹解析 |
| `outcome.py` | 运行结果逐项核对、鸣潮中英文日志归一与游戏日志未知报错拦截 |
| `annihilation.py` | 明日方舟剿灭与鸣潮周常乐园每周一次开关门 |
| `weeklyboss.py` | 鸣潮周本每周一次计数与波片预留开关 |
| `sanity_plan.py` | 明日方舟理智刷取计划写入 |

模块表和实际文件由 `tests/test_evidence.py` 盯着，加文件不登记会红。

## Running it

```bash
python -m ark_relay check      # self-test
python -m ark_relay test       # send one test message
python -m ark_relay local      # foreground; production runs app_main.py (scheduled task \ArkRelay\main)
```

Configuration is environment variables or `relay/.env`; the list is in
[docs/CONFIG.md](../docs/CONFIG.md).

## Why there is no server

Server mode was retired on 2026-08-20. Every capability a cloud server had now
has an implementation that needs no server *and* no upload code on the machine -
which matters, because the machine cannot reach github.com or api.github.com at
the TCP layer at all.

| Old server feature | Replacement |
|---|---|
| boot / shutdown supervision | GitHub Actions reads Tailscale `lastSeen`. tailscaled connecting at boot and dropping at shutdown is a signal the machine already sends |
| heartbeat timeout alarm | none - by the 2026-08-18 decision there is no periodic heartbeat, only those two events plus scheduled checks |
| command queue from the phone | the inbox: edit `queue/config.json` in this repo, the machine fetches it at boot |
| collect, judge, push | local mode already did this |
| status web page | reports and alarms go to WeChat; the rest is the GitHub web UI |

## The four gates on commands

A model may only emit an **action name from this table**. It may never emit a
JSON patch.

| Action | Reversible | Needs confirmation |
|---|---|---|
| `run_now` | - | **会真的开跑一趟**：调 `/api/dispatch/start` 派发那条队列。手动派发的唯一正门是 `scripts/mac/run-one.sh`（内含忙闲闸门），不要裸调 dispatch |
| `skip_today` | yes | no - disables that queue for the day and restores it afterwards. Takes `"day":"YYYY-MM-DD"`; the inbox is only read at boot, so a stale one is refused rather than skipping the wrong day |
| `unskip_today` | yes | no - cancels today's `skip_today` for that queue: drops the flag, or re-enables the queue at once if the skip already engaged (the phone's queue switch turned back on, 2026-09-15) |
| `debug_mode` | yes, self-expiring | no - `days:N` or `off:true`; while active: no shutdown, no missed-run alarms |
| `alarm_hold` | yes, self-expiring | no - `on:true` (`reason`, optional `alert_ts`, `internal:true`) or `off:true` (optional `expected_at`, `expected_created_at`); holds shutdown until 10 minutes before the next scheduled power-on while an unfixed fault alarm is open |
| `set_stage` | no, writes config | **yes** |
| `set_medicine` | no, writes config | **yes** |
| `set_wait_time` | no, writes config | **yes** - 60-600 only, see [CONFIG.md](../docs/CONFIG.md) |
| `toggle_task` | no, writes config | **yes** - not implemented; refuses explicitly |
| `tacet_shots` | yes | no - 日报后面要不要带无音区结算截图（`on:true/false`，默认不带；手机页那个按钮） |
| `monthcard` | yes | no - 登记月卡（`game` 为 明日方舟 / 终末地 / 鸣潮，再填 `add:N` 充值了几次或 `left:X` 游戏里还剩几天，二选一；手机带来的 `last` 最后领取日与 `at` 登记时间照用，比已存登记旧的不改）；最后领取日前 5 天起每天一条 Server酱 |
| `skip_shutdown` | yes | no - arms the one-shot 「下次跑完不关机」 mark (no expiry; `off:true` pulls back a mark not yet spent). It is spent when the next 早班/晚班 run finishes: that shutdown occasion is skipped, the re-checks after it do not power off, and the machine stays on until the run after that, which shuts down as usual. Once spent there is nothing to cancel. Pressed inside the relay's own 60-second countdown it cancels that countdown instead. The desktop `中继关机开关.bat` and the phone switch both send it (see `modes.skip_armed`) |
| `weekly_boss` | yes | no - 鸣潮周本「打第几个」。次数（3）和难度（90 级）是游戏规则，钉死在中继里不给改 |
| `echo_farm` | yes | yes - 鸣潮：盯着 F2「讨伐强敌」里的第几个 boss 刷 4C 声骸，**刷到指定时刻为止**（`until` 写 `08:30` 这种，按机器的钟）。开跑前把 FarmEchoTask 的原配置整份存下来，收工时还原——那份配置和每日的周本共用 |
| `echo_farm_stop` | yes | no - 提前收工：停掉刷取并把配置还原 |
| `echo_farm_until` | yes | no - 改正在刷的那趟的收工时刻，提前或延后都行（`until` 写 `21:00` 这种）。只动收工时刻，存下来的原配置、开跑时刻和重开次数都不动 |
| `set_config` | no, writes config | **yes** - 改 MAS 侧用户配置，**只改已存在的字段**，凭空造的会被拒 |
| `set_master` | no, writes config | **yes** - 改脚本自己的母本配置（MaaEnd / OK-WW / MAA）。这两个脚本的快速配置是关的，MAS 侧改了不生效，所以手机页那两段走的是这条 |

`sanity_plan` and `queue` are handled in `phone.py` before the
whitelist, as all-or-nothing batches, because their fields depend on each other.

The confirmation gate exists for the model path. Commands arriving through the
inbox are confirmed by the act of editing the repo file, so `phone.py` supplies
`confirmed: True` itself.

Applying any of them: back up → write → `json.loads` → structural diff → **roll
back unless added=0, removed=0 and changed matches expectation**. That gate has
caught one real incident already; see [OPERATIONS.md](../docs/OPERATIONS.md), "Changing game configuration".

## The timezone contract

Three clocks are in play: server UTC+8, operator UTC+9, and whatever host the
code runs on.

1. **All judgement uses the server clock.** `SERVER_TZ` is a hardcoded UTC+8
   fixed offset and deliberately does **not** read the host's local timezone.
   09:00 and 21:30 are aligned to the smart plug, the BIOS wake and AUTO-MAS's
   timers, all of which run on that clock. So where the relay is deployed cannot
   change a verdict.
2. **Everything persisted is ISO 8601 with an offset** - `2026-08-14T09:00:12+08:00`,
   never a bare `09:00:12`. An absolute instant reads the same on any machine.
3. **Everything shown to a human names both clocks.** `both_clocks()` prints
   `09:00（东京 10:00）`.
4. **No bare `datetime.now()` anywhere.** Every call carries `tz=SERVER_TZ`.

Rule 4 is not fastidiousness - see [OPERATIONS.md](../docs/OPERATIONS.md), "Schedule".

## Where the model's authority ends

The LLM call in `summary.py` **only chooses words**. Whether a run failed, which
task failed, the stage, the drops, the sanity numbers, whether something is
overdue - all of that is decided by ordinary Python in `ledger.py` before the model
is asked anything.

An unreachable model, a timeout, or no key at all costs one sentence of prose.
The structured content is sent regardless.

## Verified against real records

```
MAA     ok=True   45 min   龙门币 x28800 · 技巧概要·卷2 x4 · 家具零件 x6
MaaEnd  ok=False  43 min   failed: protocol space, daily reward collection
idempotence: a repeat scan yields 0 records
whitelist:   'rm -rf /' refused / unconfirmed set_stage refused / bad stage code refused
```
