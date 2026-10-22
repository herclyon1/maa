"""A hand power-off waits for the relay's own work (scripts/mac/lib/poweroff_ok.py).

Ledger #110 (2026-10-22): 调试模式 off at 16:44:18 Beijing, the gathering retry started by
the shutdown decision at 16:44:20, a hand `shutdown /s /t 60` at 16:44:5x cut it, and the
evening boot re-ran it with 「中继自己报错了」 in the group. Each case below is one thing a
person's power-off must not cut, the first two being that afternoon's.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
sys.path.insert(0, str(ROOT / "relay" / "tests"))
sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
import poweroff_ok  # noqa: E402
from _tmp import tmpdir  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.echofarm import echofarm  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


NOW = datetime(2026, 10, 22, 16, 44, 50, tzinfo=SERVER_TZ)
idle = lambda: False   # noqa: E731


def why(sd, running=idle, lines=()):
    return poweroff_ok.reasons(NOW, sd, running, list(lines))


def stamp(sd, **rec):
    f = sd / "collect-retry" / f"{NOW:%Y-%m-%d}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec), encoding="utf-8")


print("[10-22 那天下午的两件事]")
sd = tmpdir()
stamp(sd, run_id="r1", routes=["AutoCollectRoute2"], started=(NOW - timedelta(seconds=30)).isoformat())
got = why(sd)
check("采集补跑开了还没写结束 → 先别关", any("采集补跑在跑" in w for w in got), True)
check("说了几点开始的", any("16:44" in w for w in got), True)
got = why(tmpdir(), lines=["10-22 16:44:18 INFO    ark.service  📱 手机指令 debug_mode：调试模式已关闭"])
check("调试模式刚关 → 先等中继判一次关机", any("调试模式" in w for w in got), True)

print("\n[别的在跑的]")
check("调度程序或游戏在跑 → 先别关", bool(why(tmpdir(), running=lambda: True)), True)
sd = tmpdir()
echofarm._store(sd).set("queues", "echo_farm", {"name": "周本第 1 个", "until": "2026-10-22 16:41"})
check("刷声骸在跑 → 先别关", any("刷声骸在跑" in w for w in why(sd)), True)

print("\n[可以关的]")
check("什么都没在跑 → 可以关", why(tmpdir()), [])
sd = tmpdir()
stamp(sd, run_id="r1", started=(NOW - timedelta(minutes=30)).isoformat(), finished=NOW.isoformat())
check("补跑已经跑完 → 不拦", why(sd), [])
sd = tmpdir()
stamp(sd, run_id="r1", started=(NOW - timedelta(days=1)).isoformat())
check("开始太久的印记（中继停过，下次开机它自己补）→ 不拦", why(sd), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
