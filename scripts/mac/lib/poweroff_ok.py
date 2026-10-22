"""Can a person power the gaming machine off right now without cutting the relay's own work?

    scripts/mac/winrun.sh --py scripts/mac/lib/poweroff_ok.py

Prints 「可以关」 and exits 0, or 「先别关」 with each reason and exits 1.

Why (2026-10-22, ledger #110): after a manual job we turned 调试模式 off and powered off by
hand half a minute later. Debug mode had been holding the shutdown decision all day, and that
decision starts the day's gathering retry before it powers off (shutdown._maybe_shutdown ->
collect_retry.maybe_run). The retry started 2 s after debug mode went off and the hand
power-off cut it; the relay found the cut-off retry at the evening boot, ran it again and the
group got 「中继自己报错了」. With debug mode off the relay powers off by itself once its own
work is done; a hand power-off is for when it does not, and only after this says 可以关.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

from arklog import RELAY_LOG, since_minutes
from relay_code import DATA, use_relay_code
use_relay_code()

from ark_relay.core.config import SERVER_TZ                      # noqa: E402
from ark_relay.core.engine import Engine                          # noqa: E402
from ark_relay.features.echofarm import echofarm                  # noqa: E402
from ark_relay.features.makeup import collect_retry, makeup       # noqa: E402

# The relay's tick is about a minute ("下一个闹钟"); two give the shutdown decision that
# debug mode was holding back a turn to start what it was waiting to do.
DEBUG_OFF_GRACE_MINUTES = 2


def reasons(now: datetime, state_dir, scripts_running, log_lines) -> list[str]:
    """Why a person must not power off now; [] when nothing of the relay's is under way."""
    why = []
    if scripts_running():
        why.append("调度程序有任务在跑，或者游戏 / 模拟器开着")
    stamp = state_dir / "collect-retry" / f"{now:%Y-%m-%d}.json"
    try:
        rec = json.loads(stamp.read_text(encoding="utf-8"))
        begun = datetime.fromisoformat(rec["started"])
    except (OSError, ValueError, KeyError, TypeError):
        rec, begun = {}, None
    if rec and "finished" not in rec and begun and now - begun < collect_retry.STAMP_STALE:
        why.append(f"采集补跑在跑（{begun.astimezone(SERVER_TZ):%H:%M} 开始），中继跑完会自己关机")
    if farm := echofarm.current(state_dir):
        why.append(f"刷声骸在跑（{farm.get('name') or '?'}，到 {farm.get('until')}）")
    if going := makeup.in_flight(state_dir, now):
        why.append(f"补跑在跑（{'、'.join(going)}）")
    if any("调试模式已关闭" in line for line in log_lines):
        why.append(f"调试模式 {DEBUG_OFF_GRACE_MINUTES} 分钟内刚关，先等中继判一次关机（它会先做该补的再自己关）")
    return why


def main() -> int:
    now = datetime.now(tz=SERVER_TZ)
    why = reasons(now, DATA / "state", Engine._scripts_running,
                  since_minutes(RELAY_LOG, DEBUG_OFF_GRACE_MINUTES, allow_empty=True))
    if why:
        print("先别关：")
        for w in why:
            print(f"  - {w}")
        return 1
    print("可以关：中继没有在做的事")
    return 0


if __name__ == "__main__":
    sys.exit(main())
