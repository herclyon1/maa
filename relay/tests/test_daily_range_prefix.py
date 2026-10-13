#!/usr/bin/env python3
"""「日常 1-N 项完成」 only when the run's list is the footnote's first N names.

The fixture is the two real 2026-10-08 Endfield ledger records. The footnote key
comes from 05-29-15 (13 tasks, starting 赠送干员礼物、装备制造); the 10:35 run
06-34-21 did 12 others plus 自动采集. Before, its row said 「日常 1-13 项完成」,
naming tasks it never did.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import ledger as core

fails = []


def require(label, ok, detail=""):
    print(("  ✓ " if ok else "  ✗ ") + label + ("" if ok else f"  -- {detail}"))
    if not ok:
        fails.append(label)


es = [json.loads(x) for x in (Path(__file__).parent / "fixtures" / "ledger-1008-maaend-two-lists.jsonl").read_text(encoding="utf-8").splitlines()]
_t, body = core.format_daily("2026-10-08", es, "", "")
blocks = body.split("\n\n")
late = next(b for b in blocks if "10:35→11:12" in b)
early = next(b for b in blocks if "09:30→10:30" in b)
require("10:35 run names its own tasks", "日常 1-" not in late and "做了 拜访好友" in late, late)
require("10:35 run lists 自动采集 it did", "自动采集、日常奖励领取" in late, late)
require("the footnote's own run keeps 1-13", "日常 1-13 项完成" in early, early)
require("footnote starts with 05:29's list", core.daily_footnote(es).startswith("———————\n日常：1.赠送干员礼物 2.装备制造"))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
