#!/usr/bin/env python3
"""Endfield sanity spent and left come from one rule, checked on real logs.

Fixtures (fixtures/maaend-sanity-1013/) are the 协议空间 task of real machine
logs, movement and template-matcher lines dropped. Each expected 「left」 is
checked against the next run's first reading at ~1 sanity per 7.2 minutes:
  10-13 05:36  198, one double claim            -> 160 spent, 38 left
  10-07 05:29  277, double + half claim         -> 240 spent, 37 left (10-08 reads 237)
  10-08 05:29  237, 4 double + 1 half, 14 potions (「补充理智」, 40 each)
                                                -> 720 spent, 78 left (06:34 reads 85)
  10-08 06:34  85, one half claim               -> 80 spent, 5 left (10-09 reads 194)
Before: spent 0 for one run (two equal readings), 0 left after a half claim,
and the report row said 「理智不足，一次没开成」 on a run that claimed its reward.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import ledger_rows  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.verify.collector_maaend import parse_maaend_log  # noqa: E402

D = Path(__file__).resolve().parent / "fixtures" / "maaend-sanity-1013"
fails: list[str] = []


def check(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  got {got!r}, want {want!r}"))
    if not ok:
        fails.append(name)


CASES = [
    ("2026-10-13_MaaEnd-05-36-57.log", 1, 160, 38, None),
    ("2026-10-07_MaaEnd-05-29-05.log", 2, 240, 37, None),
    ("2026-10-08_MaaEnd-05-29-15.log", 5, 720, 78, 14),
    ("2026-10-08_MaaEnd-06-34-21.log", 1, 80, 5, None),
]
for name, runs, spent, left, potions in CASES:
    o = parse_maaend_log(D / name)
    check(f"{name} runs", o.get("maaend_farm_runs"), runs)
    check(f"{name} spent", o.get("maaend_sanity_spent"), spent)
    check(f"{name} left", o.get("sanity"), left)
    check(f"{name} potions", o.get("maaend_medicine"), potions)

# The report row: a run that claimed is never 「一次没开成」, even with no figure.
fin = datetime(2026, 10, 13, 9, 54, tzinfo=SERVER_TZ)
raw = {"maaend_farm": "协议空间", "maaend_farm_runs": 1, "sanity_exhausted": True,
       "maaend_farm_drops": {"折金票": 68000}}
_did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": raw}, raw, fin)
check("ran, no figure: not 一次没开成", cost, ["理智消耗没读到"])
raw = {"maaend_farm": "协议空间", "sanity_exhausted": True}
_did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": raw}, raw, fin)
check("no run, exhausted: 一次没开成", cost, ["理智不足，一次没开成"])
o = parse_maaend_log(D / "2026-10-13_MaaEnd-05-36-57.log")
_did, cost, *_ = ledger_rows._block_maaend({"ok": True, "raw": o, "sanity": o["sanity"]}, o, fin)
check("10-13 cost row", cost, ["理智 160，加强剂 0"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
