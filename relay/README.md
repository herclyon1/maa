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

| File | Responsibility |
|---|---|
| `service.py` | Windows service host: process watch, alarm clock, inbox deferral |
| `core.py` | judgement - what happened, was it a failure, what is pending |
| `engine.py` | the round: reports, shutdown, catch-up, manual-round detection |
| `collector.py`（聚合）+ `collector_maa.py` / `collector_maaend.py` / `collector_okww.py` | 扫 AUTO-MAS 的 history 记录、判成败；三个游戏的日志解析按游戏分文件 |
| `watch.py` | directory-change notification (Windows ctypes / macOS kqueue) |
| `plan.py` | read AUTO-MAS's schedule; there is no second copy of it |
| `notify.py` / `transport.py` | channels and HTTP with the right retry policy |
| `summary.py` | wording, including the optional LLM line |
| `inbox.py` | fetch and apply `queue/config.json` |
| `selfupdate.py` | fetch and apply `relay/manifest.json` |
| `commands.py` | the command whitelist and its gates |
| `queues.py` / `modes.py` / `sanity_plan.py` / `maaend.py` / `mastercfg.py` | config writers |
| `statestore.py` | 唯一的状态档案 `state/state.json`：六段、字段表登记过才能写、旧文件自动迁入 |
| `texts.py` | 所有通知文案。标题不许写死在别处，闸门盯着 |
| `handle.py` / `missed.py` / `report.py` / `shutdown.py` | 从 engine 拆出来的四块：记账告警 / 漏跑缺项 / 日报 / 关机决策 |
| `scoreboard.py` | 每个代码版本跑过几趟、失败几趟。数在 `append_ledger` 里记，日报末尾贴一行——我写的字动不了它 |
| `annihilation.py` / `garden.py` / `weeklyboss.py` | 三个「一周一次」的门，同一套接口 |
| `preupdate.py`（聚合）+ `preupdate_common.py` / `preupdate_maa.py` / `preupdate_maaend.py` / `preupdate_automas.py` / `preupdate_okww.py` | 开机窗口里把四个程序更新掉，按程序分文件 |
| `gameupdate.py`（聚合）+ `gameupdate_games.py` | 队列跑完后更新游戏客户端，再单独补跑；三家游戏各自的更新流程单独一个文件 |
| `okww_patch.py` + `okww_patches/` | 贴在 OK-WW 源码上的本地补丁，一个补丁一个文件 |
| `okww_overlay.py` | 装进 OK-WW 自己的 `ok_tasks/` 扩展目录，不改它的源文件；装完读回报告，有没贴上的就报出来 |
| `wuwa_tacet.py` / `wuwa_forgery.py` | 鸣潮副本序号 → 名字 → 掉落，手机页与此同源 |
| `echofarm.py` | 刷 4C 声骸：改配置、在 session 1 起 OK-WW、到点收工并还原配置 |
| `wuwa_boss.py` | 鸣潮「讨伐强敌」列表序号 → boss 名字，手机页的下拉与此同源 |
| `banners.py` / `efstatus.py` / `snapshot.py` / `desktop.py` / `phone.py` | 卡池播报 / 终末地开服状态 / 配置快照 / 桌面助手 / 手机通道 |
| `outcome.py` | 跑完核对「到底干成了什么」，没干成必须出声 |
| `maintenance.py` | 三个游戏官方停服维护公告的机器可读来源 |
| `skland.py` | 森空岛客户端，拿终末地的角色练度 |
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
| `debug_mode` | yes, self-expiring | no - `days:N` or `off:true`; while active: no shutdown, no missed-run alarms |
| `set_stage` | no, writes config | **yes** |
| `set_medicine` | no, writes config | **yes** |
| `set_wait_time` | no, writes config | **yes** - 60-600 only, see [CONFIG.md](../docs/CONFIG.md) |
| `toggle_task` | no, writes config | **yes** - not implemented; refuses explicitly |
| `skip_shutdown` | yes | no - **一次性、不带时效**：吃掉下一次真正要执行的关机，用完即失效。开了不取消会一直等到下一趟队列跑完才关，机器可能白开一夜。桌面 `中继关机开关.bat` 和手机页按的都是它 |
| `weekly_boss` | yes | no - 鸣潮周本「打第几个」。次数（3）和难度（90 级）是游戏规则，钉死在中继里不给改 |
| `echo_farm` | yes | yes - 鸣潮：盯着 F2「讨伐强敌」里的第几个 boss 刷 4C 声骸，**刷到指定时刻为止**（`until` 写 `08:30` 这种，按机器的钟）。开跑前把 FarmEchoTask 的原配置整份存下来，收工时还原——那份配置和每日的周本共用 |
| `echo_farm_stop` | yes | no - 提前收工：停掉刷取并把配置还原 |
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
overdue - all of that is decided by ordinary Python in `core.py` before the model
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
