#!/usr/bin/env python3
"""MaaEnd v2.34's 「体力不足，任务结束」 is the out-of-sanity ending of 基质刷取.

Real record, 2026-10-19 (fixtures/maaend-2026-10-19/MaaEnd-07-14-29.log, the
AUTO-MAS history log of the morning run's second attempt, unchanged). MaaEnd had
updated itself to v2.34.0-rc.1 at 11:14:04 between the two attempts. The first
attempt had farmed sanity 242 -> 2 already; in the retry 基质刷取 read 「当前理智
9/360」 and stopped after 76 s with 「😴**体力不足，任务结束**」. The relay knew only
「已完成一次基质刷取|理智不足」 as the trace of farming, so at 11:57:16 it pushed
「⚠️ 终末地早班没干完」 to the group (ledger #106): a normal state (out of sanity)
reported as work left undone.

The negative case keeps the same segment without the stop line: a quick
「任务完成」 with no trace must still alert.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify.collector_maaend import parse_maaend_log
from ark_relay.features.verify.outcome import maaend_checks

LOG_PATH = Path(__file__).parent / "fixtures" / "maaend-2026-10-19" / "MaaEnd-07-14-29.log"
LOG = LOG_PATH.read_text(encoding="utf-8")
STOP = "😴**体力不足，任务结束**"
fails = []


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)


def bad(checks):
    return {c.label: c.detail for c in checks if not c.ok}


require("the real record holds the stop line", STOP in LOG)
got = bad(maaend_checks(LOG, []))
require("「体力不足，任务结束」 counts as 基质刷取's ending, no 「真的刷了」 failure",
      "基质刷取 真的刷了" not in got)

stripped = "\n".join(l for l in LOG.splitlines() if "体力不足" not in l and "如需继续刷取" not in l)
got2 = bad(maaend_checks(stripped, []))
require("without the stop line a 76 s 基质刷取 still alerts",
      "76 秒" in got2.get("基质刷取 真的刷了", ""))

require("the sanity collector reads the new stop line as sanity exhausted",
      parse_maaend_log(LOG_PATH).get("sanity_exhausted") is True)

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall checks passed")
