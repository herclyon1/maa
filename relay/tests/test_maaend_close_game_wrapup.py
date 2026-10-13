#!/usr/bin/env python3
"""关闭游戏（PC） is the round's wrap-up step, not a daily task.

The fixture is the real 2026-10-12 MaaEnd-14-25-41 ledger record: tasks_done
['日常奖励领取', '关闭游戏（PC）'], 关闭游戏 with no log evidence and no task picture.
Before, the report counted it as a daily task and called it 「没证据，不算完成」
(and pushes.py sends that list to the group); a gathering-only record holding it
was not recognised as gathering-only either.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import ledger_report, ledger_rows
from ark_relay.core.config import SERVER_TZ

fails = []


def check(label, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + label + ("" if ok else f"  got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


e = json.loads((Path(__file__).parent / "fixtures" / "ledger-1012-maaend-close-game.jsonl").read_text(encoding="utf-8"))
raw = e["raw"]
check("not unverified", ledger_rows.maaend_unverified(raw), [])
check("not listed", ledger_rows._maaend_listed(raw), ["日常奖励领取"])
notes = ledger_rows._block_maaend(e, raw, datetime(2026, 10, 12, 18, 28, tzinfo=SERVER_TZ))[4]
check("notes name the daily task only", notes, ["做了 日常奖励领取"])

gather = {"ok": True}
graw = {"maaend_collect_skipped": "周日", "tasks_done": ["自动采集", "关闭游戏（PC）"]}
check("gathering-only with 关闭游戏", ledger_report._skipped_gathering_only(gather, graw), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
