"""Debug mode must end just before the next scheduled power-on.

2026-08-22, 21:00 server: the operator asked for "no shutdown tonight". The
mode was set with days=1, which meant "through today" - and expired at
midnight, forty minutes later, while an AUTO-MAS update was still installing.
What was asked for was "until the next cycle is about to start", i.e. ten
minutes before the 08:40 power-on on the 23rd.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import modes                      # noqa: E402
from ark_relay.config import SERVER_TZ           # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(name)


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=SERVER_TZ)


def main(tmp: Path):
    # The exact case from the incident.
    ok, msg = modes.set_debug(tmp, 1, now=at("2026-08-22 21:00"))
    check("设置成功", ok, True)
    check("到期时刻 = 08:40 前 10 分钟",
          modes.debug_until(tmp), "2026-08-23 08:30")

    check("当晚 23:30 仍然生效",
          modes.debug_active(tmp, at("2026-08-22 23:30")), True)
    check("跨过午夜 00:10 仍然生效（旧实现在这里失效）",
          modes.debug_active(tmp, at("2026-08-23 00:10")), True)
    check("次日 08:29 仍然生效",
          modes.debug_active(tmp, at("2026-08-23 08:29")), True)
    check("次日 08:31 已经失效",
          modes.debug_active(tmp, at("2026-08-23 08:31")), False)

    # Set in the morning -> the evening power-on is the next boundary.
    modes.set_debug(tmp, 1, now=at("2026-08-23 10:00"))
    check("上午设置 -> 到 21:20 前 10 分钟",
          modes.debug_until(tmp), "2026-08-23 21:10")

    # Two cycles sits out one more power-on.
    modes.set_debug(tmp, 2, now=at("2026-08-22 21:00"))
    check("cycles=2 跨到晚班开机前",
          modes.debug_until(tmp), "2026-08-23 21:10")

    # Legacy bare-date files on disk must keep meaning end-of-day, not "off".
    (tmp / "debug-until.txt").write_text("2026-08-22", encoding="utf-8")
    check("旧格式当天 23:59 仍生效",
          modes.debug_active(tmp, at("2026-08-22 23:59")), True)
    check("旧格式次日 00:01 失效",
          modes.debug_active(tmp, at("2026-08-23 00:01")), False)

    # Garbage fails towards ON: the wrong failure powers off a box in use.
    (tmp / "debug-until.txt").write_text("???", encoding="utf-8")
    check("值损坏时保守取生效",
          modes.debug_active(tmp, at("2026-08-23 12:00")), True)

    # Off removes it outright.
    modes.set_debug(tmp, off=True)
    check("关闭后不再生效",
          modes.debug_active(tmp, at("2026-08-22 22:00")), False)

    print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        raise SystemExit(main(Path(d)))
