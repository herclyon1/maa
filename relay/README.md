# ark-relay

MAA / AUTO-MAS 通知中继。**本机模式与服务器模式共用全部业务逻辑，只有 `transport.py` 一层不同。**

```
失败  → 立刻推（附 Sonnet 写的一句人话诊断）
成功  → 静默记账
收尾  → 当天一条日报（关卡 / 掉落 / 理智 / 起止时间，双时区）
没开机 → 告警  ★ 只有服务器模式做得到
```

## 装

本机模式**零依赖**，标准库就够：

```bash
python -m ark_relay check      # 自检
python -m ark_relay test       # 发一条测试消息
python -m ark_relay local      # 常驻
```

服务器模式额外需要：

```bash
pip install fastapi "uvicorn[standard]"
python -m ark_relay server --port 8787
```

## 配置

复制仓库根目录的 `.env.example` 到 `relay/.env` 填好，或者直接用环境变量：

| 变量 | 说明 |
|---|---|
| `ARK_HISTORY_DIR` | AUTO-MAS 的 `history` 目录（本机模式 / 采集端必填） |
| `ARK_STATE_DIR` | 中继自己的状态目录，默认 `./ark-state` |
| `ARK_POLL_SECONDS` | 轮询间隔，默认 300 |
| `ARK_LAST_RUN_AFTER` | 当天最后一轮的时刻（服务器时间），默认 `21:30` |
| `SERVERCHAN_KEY` | Server酱 |
| `WECOM_CORPID` / `WECOM_SECRET` / `WECOM_AGENTID` | 企业微信自建应用 |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | 措辞生成，不配也能跑 |
| `ARK_AUTOMAS_DIR` | 采集端要改配置时才需要 |

## 三种角色

```
本机模式    python -m ark_relay local
            跑在游戏机器上，直接读 history，自己判定自己推送
            ✅ 失败告警、日报    ❌ 开机监督（它自己也在这台机器上）

采集端      python -m ark_relay agent --url http://<中继>:8787
            跑在游戏机器上（服务器模式下）：上报事件 + 发心跳 + 执行指令
            上报成功才记 seen，所以关机丢的事件下次开机会补上

服务器      python -m ark_relay server
            跑在云服务器上：收事件、判定、推送、心跳超时告警、指令队列、网页
```

## 网页

服务器模式自带一个页面，手机浏览器打开、「添加到主屏幕」就是一个 App 图标——
安卓 / iOS / Windows / macOS 一份代码全覆盖，不用上架、不用装包。

能看机器在线状态、今天的运行记录；能用人话发指令。

## 指令的四道闸

见 [docs/04-中继设计.md §15](../docs/04-中继设计.md)。代码在 `commands.py`。

| 动作 | 可逆 | 要确认 |
|---|---|---|
| `run_now` 立刻跑一轮 | ✅ | 否 |
| `skip_today` 今天跳过 | ✅ | 否（跳过模式：当天临时停用该队列，过后自动恢复） |
| `debug_mode` 调试模式 | ✅ 自动过期 | 否（`days`:N 或 `off`:true；生效期内不关机、不报漏跑） |
| `set_stage` 换关卡 | ❌ 改配置 | **是** |
| `set_medicine` 理智药 | ❌ 改配置 | **是** |
| `toggle_task` 开关任务 | ❌ 改配置 | **是**（尚未实现，会明确拒绝） |

模型**只能产出这张表里的动作名，不能输出 JSON 补丁**。落地时一律：备份 → 改 → `json.loads` → 结构化 diff，**新增/删除不为 0 或改动数不符预期就回滚**。

这道闸不是摆设：它已经抓到过一次真实事故——一个本该关掉 3 个 webhook 的正则只关了 2 个，还damage了无关段落。

## 时区

两台机器差 1 小时（服务器 Asia/Shanghai UTC+8，人在 Asia/Tokyo UTC+9），中继本身还可能跑在时区是 UTC 的云服务器上。三个时钟，四条规矩：

**① 一切判定用服务器时钟。** `SERVER_TZ` 是写死的 UTC+8 固定偏移，**不读运行主机的本地时区**。09:00 / 21:30 这些时刻对齐的是米家插座、BIOS 唤醒和 AUTO-MAS 的定时——它们全都按服务器钟走。所以中继部署在哪都不影响判定。

**② 落盘一律存带偏移的 ISO 8601。** ledger 里是 `2026-08-14T09:00:12+08:00`，不是 `09:00:12`。绝对时刻没有歧义，换机器读也不会错。

**③ 给人看的地方一律双时区。** `both_clocks()` 输出 `09:00（东京 10:00）`，永远不出现没标注是哪个钟的时间。

**④ 代码里不允许出现裸的 `datetime.now()`。** 每一处都必须带 `tz=SERVER_TZ`。

> 第 ④ 条不是洁癖。`commands.py` 里「今天跳过」的日期原本用的是主机本地时钟，一旦采集端换台机器跑、或者恰好在午夜前后执行，就会跳错天。回归测试用 `TZ=UTC` 跑了一遍确认修好。
>
> 开发时也踩过：在东京的 Mac 上 `touch -t 09:45` 造测试数据，那是东京 09:45 = 服务器 08:45，比文件名里的 09:00 还早，算出「结束早于开始」。**文件名和 mtime 必须来自同一个钟**——在真机上它们都是服务器本地时间，所以一致。

## 模型的边界

`summary.py` 里的模型调用**只负责措辞**。是否失败、哪个任务失败、关卡掉落理智的数字、心跳有没有超时，全部在 `core.py` 里用普通 Python 判定完毕之后才轮到模型说话。

模型调不通、超时、没配 key，都只是少一句人话——结构化内容照发。

## 已验证

用真实的 AUTO-MAS 记录格式跑通：

```
MAA     ok=True   45 分钟   龙门币 ×28800 · 技巧概要·卷2 ×4 · 家具零件 ×6
MaaEnd  ok=False  43 分钟   失败：协议空间、日常奖励领取
幂等性：重复扫描 0 条
白名单：'rm -rf /' 拒绝 / 未确认的 set_stage 拒绝 / 'DROP TABLE' 关卡格式拒绝
```
