# ark-relay

MAA / AUTO-MAS 通知中继，跑在游戏机上。

```
失败  → 立刻推（附模型写的一句人话诊断）
成功  → 静默记账
收尾  → 当天一条日报（关卡 / 掉落 / 理智 / 起止时间，双时区）
没开机 → 告警  ★ 由 GitHub Actions + Tailscale 负责，不在这台机器上
```

**服务器模式已裁撤（2026-08-20）。** 云服务器的每一项独有功能都有了不需要
服务器的实现，而且机器侧一行上传代码都不用写：

| 原服务器功能 | 现在的实现 |
|---|---|
| 开机 / 收工监督 | GitHub Actions 定时查 Tailscale `lastSeen`（[watchdog](../.github/workflows/watchdog.yml)，配置在 [queue/watchdog.json](../queue/watchdog.json)）。机器开机 tailscaled 即连、关机即断，「报到」是它本来就在发的信号 |
| 心跳超时告警 | 同上——按 2026-08-18 裁决，没有周期心跳，只有开机/收工两个事件加到点核查 |
| 指令队列（手机发指令） | 收件箱：手机改仓库里的 [queue/config.json](../queue/config.json)，机器开机自取（inbox.py） |
| 收事件、判定、推送 | 本机模式本来就有 |
| 网页看状态 | 不再单做：日报/告警已推到微信，剩余需求由 GitHub 网页（仓库文件 + Actions 运行记录）覆盖 |

之所以必须这样绕：游戏机对 github.com / api.github.com **TCP 层直接不通**
（2026-08-20 实测），永远写不了 GitHub；而 raw.githubusercontent 会整晚变黑
（8/17、8/20 两次实测），只读也得靠 jsDelivr 双门 + 粘性门顺序 + 推送后
清 CDN 缓存（[purge-cdn.py](../scripts/mac/purge-cdn.py)）才稳。

## 装

**零依赖**，标准库就够（Windows 服务形态另需 pywin32，游戏机已装）：

```bash
python -m ark_relay check      # 自检
python -m ark_relay test       # 发一条测试消息
python -m ark_relay local      # 常驻（生产用 service.py 的 Windows 服务形态）
```

## 配置

复制仓库根目录的 `.env.example` 到 `relay/.env` 填好，或者直接用环境变量：

| 变量 | 说明 |
|---|---|
| `ARK_HISTORY_DIR` | AUTO-MAS 的 `history` 目录（必填） |
| `ARK_STATE_DIR` | 中继自己的状态目录，默认 `./ark-state` |
| `ARK_POLL_SECONDS` | 兜底扫描间隔，默认 300——**仅当目录监听挂不上时才用**，生产路径事件驱动，此数从不走表 |
| `ARK_LAST_RUN_AFTER` | 当天最后一轮的时刻（服务器时间），默认 `21:30` |
| `SERVERCHAN_KEY` | Server酱 |
| `WECOM_CORPID` / `WECOM_SECRET` / `WECOM_AGENTID` | 企业微信自建应用（家宽 IP 一变就 60020，别当唯一渠道） |
| `WECOM_BOT_URL` | 企业微信群机器人 webhook——没有可信 IP 名单，适合拨号家宽 |
| `ARK_LLM_KEY` 等 | 措辞生成，不配也能跑 |
| `ARK_AUTOMAS_DIR` | 读排期、收件箱改配置用 |

## 指令的四道闸

见 [docs/04-中继设计.md §15](../docs/04-中继设计.md)。代码在 `commands.py`。

| 动作 | 可逆 | 要确认 |
|---|---|---|
| `run_now` 立刻跑一轮 | — | **尚未实现，会明确拒绝**（旧版写过一个没人消费的标记还报成功） |
| `skip_today` 今天跳过 | ✅ | 否（跳过模式：当天临时停用该队列，过后自动恢复。可带 `"day":"YYYY-MM-DD"` 声明意图日期——收件箱是开机才收的，过期即拒绝，防止跳错天） |
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
