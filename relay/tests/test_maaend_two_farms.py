#!/usr/bin/env python3
"""Both sanity tasks in one round are both read.

ProtocolSpace sits before AutoEssence and the phone page can switch each on
(mastercfg `@enabled`). No real round has run both yet, so the round here is
two real segments back to back: the 协议空间 task of
fixtures/maaend-farm-drops/2026-09-27.log and the 基质刷取 task of
2026-09-24_MaaEnd-06-07-50.log, each from its 「任务开始」 to its own end line.
Before 2026-10-06 only the first was read: the essence runs and drops vanished.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collector_maaend as cm

FAILED: list[str] = []
D = Path(__file__).resolve().parent / "fixtures" / "maaend-farm-drops"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def _task(path: Path, key: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    a = next(i for i, x in enumerate(lines) if "任务开始" in x and key in x)
    b = next(i for i, x in enumerate(lines) if i > a and ("任务完成" in x or "任务失败" in x) and key in x)
    return "\n".join(lines[a:b + 1]) + "\n"


def main() -> int:
    ps = _task(D / "2026-09-27.log", "协议空间")
    ess = _task(D / "2026-09-24_MaaEnd-06-07-50.log", "基质刷取")
    one_ps, one_ess = cm._maaend_farm(ps), cm._maaend_farm(ess)
    both = cm._maaend_farm(ps + ess)
    require("each part alone farmed something", one_ps.get("maaend_farm_runs") and one_ess.get("maaend_farm_runs"),
            repr((one_ps, one_ess)))
    require("both tasks are named", both.get("maaend_farm") == "协议空间、基质刷取", repr(both.get("maaend_farm")))
    require("runs add up", both.get("maaend_farm_runs") ==
            one_ps["maaend_farm_runs"] + one_ess["maaend_farm_runs"], repr(both.get("maaend_farm_runs")))
    want = dict(one_ps.get("maaend_farm_drops") or {})
    for k, n in (one_ess.get("maaend_farm_drops") or {}).items():
        want[k] = want.get(k, 0) + n
    require("drops of both are kept", both.get("maaend_farm_drops") == want, repr(both.get("maaend_farm_drops")))
    require("a single task reads as before", cm._maaend_farm(ps) == one_ps)
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
