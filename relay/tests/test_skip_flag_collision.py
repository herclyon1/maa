"""两个功能共用 skip-*.flag 这个名字，清理陈旧标记时把对方扫掉了。

「某天跳过队列」写 skip-<YYYY-MM-DD>.flag，「下一次跑完不关机」写
skip-next-shutdown.flag，两者住同一个 state 目录。process_skip 每一拍
（30 秒）都会清理「不是今天的」skip-*.flag，glob 把后者也匹配上，于是
人在手机上按下开关，半分钟内就被删掉，日志还写「未曾生效（当天机器
没开机）」——而机器正开着。发现于 2026-08-31：按下后回读 True，40 秒后
再读已经没了。
"""
import sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import modes
from ark_relay.config import SERVER_TZ

STATE = Path(tempfile.mkdtemp()) / "state"; STATE.mkdir(parents=True)
NOW = datetime(2026, 8, 31, 12, 44, tzinfo=SERVER_TZ)

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        fails.append(label)

print("\n[the bug] 清理陈旧队列标记不许碰「下一次别关机」")
modes.set_skip_shutdown(STATE, True)
check("按下之后确实开着", modes.skip_armed(STATE), True)
modes.process_skip(STATE, None, NOW)
check("扫过一拍还在", modes.skip_armed(STATE), True)
for _ in range(5):                      # 引擎每 30 秒一拍，多扫几次
    modes.process_skip(STATE, None, NOW)
check("扫过六拍还在", modes.skip_armed(STATE), True)
check("用掉之后才消失", modes.take_skip(STATE), True)
check("用完就没了", modes.skip_armed(STATE), False)

print("\n[没有回归] 真正过期的队列标记照旧清掉")
(STATE / "skip-2026-08-20.flag").write_text("Evening-MAA", encoding="utf-8")
modes.set_skip_shutdown(STATE, True)
msgs = modes.process_skip(STATE, None, NOW)
check("过期的队列标记被清除", (STATE / "skip-2026-08-20.flag").exists(), False)
check("而且说了这件事", any("过期的跳过标记" in m for m in msgs), True)
check("关机标记没受牵连", modes.skip_armed(STATE), True)

print("\n[边界] 名字长得像日期但不是日期的，不当队列标记处理")
for bogus in ("skip-next-shutdown.flag", "skip-2026-13-40.flag", "skip-.flag"):
    check(f"{bogus} 不是队列标记", modes._flag_day(STATE / bogus), None)
check("skip-2026-08-20.flag 是队列标记",
      modes._flag_day(STATE / "skip-2026-08-20.flag"), "2026-08-20")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
