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

Shared parts are in `ark_relay/core/`, each feature in `ark_relay/features/<name>/`
(one folder per cell of the relay map); `ark_relay/_aliases.py` keeps the old flat
paths importable (`ark_relay.notify` is `ark_relay.core.notify`).

| File | Responsibility |
|---|---|
| `service.py` | Windows service host: process watch, alarm clock, inbox deferral |
| `ledger.py` | judgement - what happened, was it a failure, what is pending |
| `engine.py` | the round: reports, shutdown, catch-up, manual-round detection |
| `collector.py`（聚合）+ `collector_maa.py` / `collector_maaend.py` / `collector_okww.py` | 扫 AUTO-MAS 的 history 记录、判成败；三个游戏的日志解析按游戏分文件 |
| `watch.py` | directory-change notification (Windows ctypes / macOS kqueue) |
| `plan.py` | read AUTO-MAS's schedule; there is no second copy of it |
| `notify.py` / `transport.py` | channels and HTTP with the right retry policy |
| `summary.py` | wording, including the optional LLM line |
| `inbox.py` | fetch and apply `queue/config.json` |
| `logfile.py` | relay.log size rotation (16 MB × 3 backups) that never stops the relay when Windows refuses the rename; `tail_bytes` reads across the rotated files |
| `selfupdate.py` | fetch and apply `relay/manifest.json` |
| `commands.py` | the command whitelist and its gates |
| `queues.py` / `modes.py` / `sanity_plan.py` / `maaend.py` / `mastercfg.py` | config writers |
| `statestore.py` | 唯一的状态档案 `state/state.json`：六段、字段表登记过才能写、旧文件自动迁入 |
| `texts.py` | 所有通知文案。标题不许写死在别处，闸门盯着 |
| `handle.py` / `missed.py` / `report.py` / `shutdown.py` | 从 engine 拆出来的四块：记账告警 / 漏跑缺项 / 日报 / 关机决策 |
| `gamelogs.py` / `records.py` / `runchecks.py` | handle.py's helpers: the games' own logs for one run / facts and marks on one record / what the machine checks get about a handled record |
| `runwatch.py` | 在跑巡查：读 AUTO-MAS 的 app.log，脚本每次超时都立刻报（手动开的那趟也报，并写明是手动开的）；队列超过近 7 天最长收尾 + 30 分钟还没跑完报一次（有人在 AUTO-MAS 上手动开的那个任务不算这一班） |
| `trigger.py` | 谁开的这趟：读 AUTO-MAS app.log 的「触发来源」，加上中继自己发起的记账；有人在 AUTO-MAS 上手动开的照样报警（写明是手动开的），只是不补跑、不算这一班 |
| `scoreboard.py` | 每个代码版本跑过几趟、失败几趟。数在 `append_ledger` 里记，日报末尾贴一行——我写的字动不了它 |
| `annihilation.py` / `garden.py` / `weeklyboss.py` | 三个「一周一次」的门，同一套接口 |
| `preupdate.py`（聚合）+ `preupdate_common.py` / `preupdate_maa.py` / `preupdate_maaend.py` / `preupdate_automas.py` / `preupdate_okww.py` | 开机窗口里把四个程序更新掉，按程序分文件 |
| `gameupdate.py`（聚合）+ `gameupdate_games.py` | 队列跑完后更新游戏客户端，再单独补跑；三家游戏各自的更新流程单独一个文件 |
| `okww_patch.py` + `okww_patches/` | 贴在 OK-WW 源码上的本地补丁，一个补丁一个文件 |
| `okww_overlay.py` | 装进 OK-WW 自己的 `ok_tasks/` 扩展目录，不改它的源文件；装完读回报告，有没贴上的就报出来；开机和预更新后按盘上源码核钉住的几处，对不上开跑前就说 |
| `wuwa_tacet.py` / `wuwa_forgery.py` | 鸣潮副本序号 → 名字 → 掉落，手机页与此同源 |
| `echofarm.py` | 刷 4C 声骸：改配置、在 session 1 起 OK-WW、到点收工并还原配置 |
| `monthcard.py` | 月卡到期提示：存手机登记的充值次数 / 剩余天数，算最后一次领取日，前 5 天起每天一条 Server酱 |
| `wuwa_boss.py` | 鸣潮「讨伐强敌」列表序号 → boss 名字，手机页的下拉与此同源 |
| `banners.py` / `efstatus.py` / `snapshot.py` / `desktop.py` / `phone.py` | 卡池播报 / 终末地开服状态 / 配置快照 / 桌面助手 / 手机通道 |
| `outcome.py` | 跑完核对「到底干成了什么」，没干成必须出声 |
| `collect_retry.py` | 自动采集只补跑失败的路线（上游 #5660 不做）；连续两天仍败＝复发，请人工提 issue |
| `collect_watch.py` | 盯 MaaEnd 的 maafw.log：记下哪条采集路线没走通（不改母本，2026-10-06 起不再收窄路线）；旧版本收窄过的母本在下一趟开始时改回；喂任务截图和卡死看门狗 |
| `stagegate.py` | Stage gate: replicates MAA's own check (FightTask.cpp / StageNavigationTask.cpp) on resource/tasks + cache/resource/tasks for the stage AUTO-MAS will send; refuses setting a stage MAA cannot navigate to (「MAA 走不到，修改失败」, nothing saved), and before each MAA queue time sends one group alarm (`PULL_FROM_QUEUE` off as shipped; on, it pulls MAA from that queue run and puts it back afterwards). Unreadable files never block |
| `makeup.py` | 明日方舟 / 终末地失败后，队列空了补跑一次（终末地按你自己的设置整轮再跑、先关游戏，不关你开着的任何一项；背包满了先开「存放背包」排到最前，跑完改回）；补跑走通只进日报 |
| `unresolved.py` | 明日方舟 / 终末地没处理好就进群：补跑后仍没成、没补跑、或跑完了但没干完（自动采集、应急理智加强剂也一样），每一次都响；同一条记录不重复推 |
| `maaend_watchdog.py` | MaaEnd hang watchdog, ticked by collect_watch's thread at least once a minute: while AUTO-MAS says MaaEnd is 「运行」, a go-service plugin crash or 10 minutes without a maafw.log line ends MaaEnd.exe (never the game) so AUTO-MAS retries at once, and alarms the group |
| `task_shots.py` | A desktop picture at every MaaEnd task end (and before a launch's first task), driven by collect_watch's maafw.log events and taken on its own thread; state/shots/<day>/, kept 3 days; MaaEnd evidence bundles carry the pictures inside the run's window |
| `errwatch.py` | 中继自己记下的每一条 WARNING / ERROR 都立刻报群，每次都报；修过的（`known_fixed.py`）又出现标「复发」；群里没收下的存盘排队、过后再发，一条不丢（积压时合成一条发）；推送途中自己记的不再回来报 |
| `known_fixed.py` | 修好过的报错种类和修好的版本，errwatch 拿它给复发打标记；只登记有部署标签能查到的修复 |
| `alertlog.py` | 每条送到群的报警抄一份：先记 state/alerts/<北京日期>.jsonl，再把这一天整份私有地传到 COS 的 alerts/<北京日期>.jsonl（北京时间、游戏、标题、正文、版本、运行编号）；传不上下条报警或开机再补 |
| `machinecheck.py` + `machinechecks/` | 上机核对：部署后没在机器上确认过的改动，机器自己核——正常跑完一趟（A 类）或某个触发自然发生时（B 类）判一次，过了只进日报「上机核对」一段，没过每次都报群（🔬）；核不了的写明原因 |
| `selfcheck.py` | 开机自检：进程表、系统 WMI、调度程序接口/后端/任务计划、排期、目录可写、通知通道逐项验，不成立当场群报；同时给日报「中继体检」两行 |
| `procs.py` | 用系统 WMI 读 python.exe 的进程号和命令行（wmic 在 25H2 已删） |
| `error_evidence.py` | 每次中继自己的报错推送前、以及关机令之前，把当天整份 relay.log 和 AUTO-MAS app.log 各传一个带日期的 COS 对象（同一天覆盖同一份，一次上传最多等 60 秒）；报错推送末尾带「日志：<链接>」，机器关着也能取（scripts/mac/evidence.sh daily） |
| `replay.py` | 发版前回放闸（deploy-relay.sh 的 0.75 步）：把检入的真日志片段用这一版代码离线跑一遍，会往群里推一条就拒绝部署 |
| `evidence.py` + `bundles.py` / `sources.py` / `stores.py` / `logslice.py` | 按三家上游导出按钮的规则打证据包（永远按时间窗取，截图去重封顶）、钉住其源码、只传腾讯云 COS |
| `maintenance.py` | 三个游戏官方停服维护公告的机器可读来源 |
| `skland.py` | 森空岛客户端，拿终末地的角色练度 |
| `resources.py` | 手机页数字磁贴要的两样：森空岛会话（cred/签名 token/设备号/账号 id，一个进程登一次，网页拿去自己签名去读理智）和今天跑了几趟；波片、理智的数字是网页自己问游戏的 |
| `config.py` / `names.py` / `__main__.py` | 配置读取与地址出处 / 队列名归一 / 命令行入口 |

模块表和实际文件由 `tests/test_module_table.py` 盯着，加文件不登记会红。

## Running it

```bash
python -m ark_relay check      # self-test
python -m ark_relay test       # send one test message
python -m ark_relay local      # foreground; production uses service.py
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
| `set_stage` | no, writes config | **yes** |
| `set_medicine` | no, writes config | **yes** |
| `set_wait_time` | no, writes config | **yes** - 60-600 only, see [CONFIG.md](../docs/CONFIG.md) |
| `toggle_task` | no, writes config | **yes** - not implemented; refuses explicitly |
| `tacet_shots` | yes | no - 日报后面要不要带无音区结算截图（`on:true/false`，默认不带；手机页那个按钮） |
| `monthcard` | yes | no - 登记月卡（`game` 为 明日方舟 / 终末地 / 鸣潮，再填 `add:N` 充值了几次或 `left:X` 游戏里还剩几天，二选一；手机带来的 `last` 最后领取日与 `at` 登记时间照用，比已存登记旧的不改）；最后领取日前 5 天起每天一条 Server酱 |
| `skip_shutdown` | yes | no - **一次性、不带时效**：吃掉下一次真正要执行的关机，用完即失效。开了不取消会一直等到下一趟队列跑完才关，机器可能白开一夜。桌面 `中继关机开关.bat` 和手机页按的都是它 |
| `weekly_boss` | yes | no - 鸣潮周本「打第几个」。次数（3）和难度（90 级）是游戏规则，钉死在中继里不给改 |
| `echo_farm` | yes | yes - 鸣潮：盯着 F2「讨伐强敌」里的第几个 boss 刷 4C 声骸，**刷到指定时刻为止**（`until` 写 `08:30` 这种，按机器的钟）。开跑前把 FarmEchoTask 的原配置整份存下来，收工时还原——那份配置和每日的周本共用 |
| `echo_farm_stop` | yes | no - 提前收工：停掉刷取并把配置还原 |
| `echo_farm_until` | yes | no - 改正在刷的那趟的收工时刻，提前或延后都行（`until` 写 `21:00` 这种）。只动收工时刻，存下来的原配置、开跑时刻和重开次数都不动 |
| `set_config` | no, writes config | **yes** - 改 MAS 侧用户配置，**只改已存在的字段**，凭空造的会被拒 |
| `set_master` | no, writes config | **yes** - 改脚本自己的母本配置（MaaEnd / OK-WW / MAA）。这两个脚本的快速配置是关的，MAS 侧改了不生效，所以手机页那两段走的是这条 |

`sanity_plan`, `maaend_option` and `queue` are handled in `inbox.py` before the
whitelist, as all-or-nothing batches, because their fields depend on each other.

The confirmation gate exists for the model path. Commands arriving through the
inbox are confirmed by the act of editing the repo file, so `inbox.py` supplies
`confirmed: True` itself.

Applying any of them: back up → write → `json.loads` → structural diff → **roll
back unless added=0, removed=0 and changed matches expectation**. That gate has
caught one real incident already; see [PITFALLS.md](../docs/PITFALLS.md).

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

Rule 4 is not fastidiousness - see [PITFALLS.md](../docs/PITFALLS.md), "Timing
and time zones".

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
