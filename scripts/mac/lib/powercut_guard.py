#!/opt/homebrew/bin/python3
"""Mac 侧向游戏机发远程命令的分层北京时间断电硬锁（对齐 F-POWER-SCHEDULE）。

背景与设计原则：
  - 游戏机每天北京时间 08:40 智能插座硬断电，08:45 通电 BIOS 来电自启。
  - 第 1 层（全量 16 个直连游戏机入口）：严格拦截北京时间 08:40:00–08:45:59（返回码 78），
    绝不误伤 08:22–08:39 的短耗时只读探活（如 08:25 用 winps.sh 看一眼状态）。
  - 第 2 层（3 个长耗时写盘/部署/演练入口：deploy-relay.sh、lib/deploy-pkg.sh、
    relay_shift_rehearsal.py）：严格拦截北京时间 08:22:00–08:46:59（返回码 78），
    防止写盘/替换运行时或演练拖跨 08:40 硬断电损盘。
  - 环境变量 ARK_CLOCK_OVERRIDE 供单测与验收注入模拟时钟（如 '08:25'、'08:40:00'、
    '2026-11-28T08:45:59+08:00'、'2026-11-28T09:40:00+09:00'）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

BEIJING_TZ = dt.timezone(dt.timedelta(hours=8), "CST")
RC_POWERCUT_BLOCKED = 78

# 两层时间窗均用当天秒数闭区间 [start_s, end_s] 表示（北京时间 UTC+8）
TIER1_WINDOW_S = (8 * 3600 + 40 * 60, 8 * 3600 + 45 * 60 + 59)  # 08:40:00–08:45:59
TIER2_WINDOW_S = (8 * 3600 + 22 * 60, 8 * 3600 + 46 * 60 + 59)  # 08:22:00–08:46:59


def parse_beijing_clock(raw: str | None = None) -> dt.datetime:
    """解析给定时间字符串或读取 ARK_CLOCK_OVERRIDE；未设则返回当前北京时间。"""
    val = (raw if raw is not None else os.environ.get("ARK_CLOCK_OVERRIDE", "")).strip()
    if not val:
        return dt.datetime.now(tz=BEIJING_TZ)
    # 支持 HH:MM 或 HH:MM:SS 简写（默认按当天北京时间解释）
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", val)
    if m:
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        base = dt.datetime.now(tz=BEIJING_TZ)
        return base.replace(hour=hh, minute=mm, second=ss, microsecond=0)
    norm = re.sub(r"Z$", "+00:00", val.replace(" ", "T"))
    parsed = dt.datetime.fromisoformat(norm)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ)


def check_powercut(
    tier: int = 1,
    caller: str = "",
    now: dt.datetime | None = None,
) -> tuple[bool, str]:
    """核对给定时刻是否允许发远程命令。

    返回 (allowed, reason)：
      - allowed=True  表示当前不在该层断电保护窗内，可放行；
      - allowed=False 表示命中硬断电保护窗，调用方必须立刻停止并以 RC=78 退出。
    """
    if tier not in (1, 2):
        raise ValueError(f"不支持的断电锁层级 tier={tier!r}（仅支持 1 或 2）")
    cur = (now.astimezone(BEIJING_TZ) if now is not None else parse_beijing_clock())
    sec = cur.hour * 3600 + cur.minute * 60 + cur.second
    lo, hi = TIER1_WINDOW_S if tier == 1 else TIER2_WINDOW_S
    who = f"{caller}: " if caller else ""
    if lo <= sec <= hi:
        label = (
            "08:40:00–08:45:59 智能插座硬断电窗口"
            if tier == 1
            else "08:22:00–08:46:59 长耗时写盘/部署/演练断电保护窗口"
        )
        return (
            False,
            f"{who}拒绝操作——当前北京时间 {cur:%H:%M:%S} 处于第 {tier} 层 {label}（RC={RC_POWERCUT_BLOCKED}）",
        )
    return True, f"{who}北京时间 {cur:%H:%M:%S} 在第 {tier} 层断电保护窗外，放行"


def guard_or_exit(
    tier: int = 1,
    caller: str = "",
    now: dt.datetime | None = None,
) -> None:
    """入口一键硬闸：命中该层断电保护窗时打印中文原因到 stderr 并直接退出 RC=78。"""
    allowed, msg = check_powercut(tier=tier, caller=caller, now=now)
    if not allowed:
        print(msg, file=sys.stderr)
        raise SystemExit(RC_POWERCUT_BLOCKED)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="分层北京时间断电硬锁检查（第 1 层 08:40–08:45，第 2 层 08:22–08:46）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="检查当前或 ARK_CLOCK_OVERRIDE 时刻是否放行")
    chk.add_argument("--tier", type=int, choices=(1, 2), default=1)
    chk.add_argument("--caller", default="")
    chk.add_argument("--clock", default=None, help="显式覆写时钟（优先级高于 ARK_CLOCK_OVERRIDE）")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        now = parse_beijing_clock(args.clock) if args.clock else None
        allowed, msg = check_powercut(tier=args.tier, caller=args.caller, now=now)
        if not allowed:
            print(msg, file=sys.stderr)
            return RC_POWERCUT_BLOCKED
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
