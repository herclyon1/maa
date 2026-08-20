#!/usr/bin/env python3
"""开机监督：跑在 GitHub Actions 上，问 Tailscale「机器报到了吗」。

这是整套系统里唯一必须住在游戏机之外的判断——「机器根本没开机」在机器
内部是不可能被发现的。云服务器方案（docs/04-中继设计.md）被这个文件取代：
机器什么都不用上传（api.github.com 从那台机器 TCP 层就不通，2026-08-20 实
测），tailscaled 开机即连、关机即断，Tailscale 的协调服务器本来就记着每台
设备的 lastSeen。GitHub Actions 按日程（cron 是日程，不是轮询）来读一眼，
该报到没报到就推 Server酱。

对应 2026-08-18 的用户裁决（docs/00-总览.md #12）：不要周期心跳，要的是
「开机报到 + 收工报到 + 到点没收工的一次性闹钟」。lastSeen 就是前两者，
本脚本的每次运行就是那只闹钟。

配置在 queue/watchdog.json，手机上改仓库文件即可生效（和收件箱同一习惯）：

    enabled       false 时整个监督静默跳过（缺 secrets 时的出厂状态）
    pause_until   到这天为止不告警（含当天）——调试模式时用，等价于机上的
                  debug_mode
    device        Tailscale 里的主机名
    checks        以触发它的 cron 表达式为键；kind=boot 查「该开机了没上线」，
                  kind=shutdown 查「该关机了还在线 / 中途就消失了」

时刻全部是服务器（北京）时间字符串；本脚本自换算 UTC 与东京。
Secrets（仓库 Settings → Secrets → Actions）：
    TS_OAUTH_CLIENT_ID / TS_OAUTH_SECRET   Tailscale OAuth client（devices 只读）
    SERVERCHAN_KEY                          告警出口
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVER_TZ = timezone(timedelta(hours=8), "服务器")
USER_TZ = timezone(timedelta(hours=9), "东京")
# lastSeen 在设备在线时会持续刷新；落后不超过这个数就视为「现在在线」。
ONLINE_SLACK_MIN = 10

CONFIG = Path(__file__).resolve().parents[1] / "queue" / "watchdog.json"


def both_clocks(dt: datetime) -> str:
    srv, usr = dt.astimezone(SERVER_TZ), dt.astimezone(USER_TZ)
    if srv.date() == usr.date():
        return f"{srv:%m-%d %H:%M}（东京 {usr:%H:%M}）"
    return f"{srv:%m-%d %H:%M}（东京 {usr:%m-%d %H:%M}）"


def today_at(hhmm: str, now: datetime) -> datetime:
    """The server-time occurrence of hh:mm this run is judging.

    Normally today's. But GitHub cron can run tens of minutes late, and the
    23:10 check delayed past server midnight would compute *tomorrow's*
    reference times, decide "not due yet", and silently skip the night's
    check. A reference more than 6h in the future can only mean the date
    rolled under us - the intended occurrence was yesterday's. 6h is far
    beyond any real cron delay and far short of a day.
    """
    hh, mm = (int(x) for x in hhmm.split(":"))
    ref = now.astimezone(SERVER_TZ).replace(
        hour=hh, minute=mm, second=0, microsecond=0)
    if ref - now > timedelta(hours=6):
        ref -= timedelta(days=1)
    return ref


def _post_form(url: str, fields: dict, timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    with urllib.request.urlopen(
            urllib.request.Request(url, data=body), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def alert(title: str, body: str) -> bool:
    key = os.environ.get("SERVERCHAN_KEY", "")
    if not key:
        print(f"!! 无 SERVERCHAN_KEY，告警发不出去：{title}\n{body}")
        return False
    r = _post_form(f"https://sctapi.ftqq.com/{key}.send",
                   {"title": title[:100], "desp": body.replace("\n", "\n\n")})
    ok = r.get("code", r.get("errno")) in (0, None)
    print(("已告警：" if ok else f"告警失败 {r}：") + title)
    return ok


def tailscale_last_seen(device: str) -> datetime:
    """The device's lastSeen, UTC. Raises on any API trouble - a watchdog
    that cannot see must say so loudly, never report "all quiet"."""
    cid = os.environ.get("TS_OAUTH_CLIENT_ID", "")
    sec = os.environ.get("TS_OAUTH_SECRET", "")
    if not (cid and sec):
        raise RuntimeError("缺 TS_OAUTH_CLIENT_ID / TS_OAUTH_SECRET secrets")
    token = _post_form("https://api.tailscale.com/api/v2/oauth/token",
                       {"client_id": cid, "client_secret": sec})["access_token"]
    req = urllib.request.Request(
        "https://api.tailscale.com/api/v2/tailnet/-/devices",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        devices = json.loads(resp.read().decode("utf-8")).get("devices", [])
    want = device.lower()
    for d in devices:
        names = {str(d.get("hostname", "")).lower(),
                 str(d.get("name", "")).split(".")[0].lower()}
        if want in names:
            raw = str(d.get("lastSeen", ""))
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    raise RuntimeError(f"tailnet 里找不到设备 {device!r}"
                       f"（有：{[d.get('hostname') for d in devices]}）")


def run_check(kind: str, check: dict, last: datetime, now: datetime) -> str | None:
    """Returns an alert body, or None when this check is satisfied/not due."""
    online = (now - last) < timedelta(minutes=ONLINE_SLACK_MIN)
    state = f"最后报到 {both_clocks(last)}" + ("，现在在线" if online else "，现在离线")

    if kind == "boot":
        since = today_at(check["since"], now)
        if now < since:
            return None      # 手动触发时这项还没到点，不评判
        if online or last >= since:
            print(f"✓ {check['label']}：{state}")
            return None
        return (f"预计 {both_clocks(since)} 之后就该开机上线，至今没有。\n{state}\n"
                "可能：米家/BIOS 定时没生效、断电、网络没起来。")

    # kind == "shutdown"
    off_by = today_at(check["off_by"], now)
    if now < off_by:
        return None
    boot_since = today_at(check["boot_since"], now)
    min_off = today_at(check["min_off"], now)
    if online:
        return (f"预计 {both_clocks(off_by)} 之前就该收工关机，现在还在线。\n{state}\n"
                "可能：任务卡死、关机被挡住、有人在用（在用请设 pause_until）。")
    if last < boot_since:
        print(f"– {check['label']}：这一轮根本没开机（由开机检查负责告警），略过")
        return None
    if last < min_off:
        return (f"开机了，但 {both_clocks(last)} 就下线了——早于最早合理收工时刻 "
                f"{both_clocks(min_off)}。\n可能：中途断电、死机、任务没跑完就关了。")
    print(f"✓ {check['label']}：{state}")
    return None


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not cfg.get("enabled"):
        print("watchdog.json 里 enabled=false，静默跳过。"
              "配好 secrets 后把它改成 true 即启用。")
        return 0
    now = datetime.now(timezone.utc)
    # -6h：迟到跨过午夜的检查仍属于它出发的那一天，pause_until 写到哪天就
    # 该连同那晚零点后的迟到检查一起罩住（与 today_at 的口径一致）。
    today = (now.astimezone(SERVER_TZ) - timedelta(hours=6)).strftime("%Y-%m-%d")
    if str(cfg.get("pause_until", "")) >= today:
        print(f"pause_until={cfg['pause_until']}，今天暂停监督。")
        return 0

    cron = os.environ.get("CHECK_CRON", "")   # 空 = 手动触发，全部检查但只打印
    manual = not cron
    checks = cfg.get("checks", {})
    todo = checks if manual else {k: v for k, v in checks.items() if k == cron}
    if not todo:
        print(f"没有配置对应这个 cron（{cron!r}）的检查项，watchdog.json 和 "
              "workflow 的 schedule 失配了。")
        return 1

    last = tailscale_last_seen(str(cfg.get("device", "ins")))
    failures = 0
    for key, check in todo.items():
        body = run_check(str(check.get("kind", "boot")), check, last, now)
        if body is None:
            continue
        title = f"🔌 {check.get('label', key)}异常"
        if manual:
            print(f"[手动触发，只打印不推送] {title}\n{body}")
        elif not alert(title, body):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
