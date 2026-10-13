#!/usr/bin/env python3
"""Endfield's full-again time counts from the reading, and a floor 0 gets none.

fixtures/maaend-sanity-1013/2026-10-12_MaaEnd-06-04-00.log is that run's 协议空间
task: last reading 242 at 10:23:32, one double claim, 82 left. Skland at
10:24:03 read curStamina=82 with maxTs 1791891939 = 10-13 19:45:39 (relay.log
上机核对 #10). Anchored on the record's finish (10:58) the sentence said 20:19.
A 0 after 「理智不足，结束任务」 is max(0, …) of a subtraction, not a reading; a
time from it was 1.4-4.5 h late on 10-11 and 10-12.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import collector
from ark_relay.core.config import SERVER_TZ

fails = []


def check(label, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + label + ("" if ok else f"  got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


fin = datetime(2026, 10, 12, 10, 58, 40, tzinfo=SERVER_TZ)
log = Path(__file__).parent / "fixtures" / "maaend-sanity-1013" / "2026-10-12_MaaEnd-06-04-00.log"
raw: dict = {}
collector._enrich_record(raw, "MaaEnd", log, True, [], fin)
check("full at from the reading's time", raw.get("sanity_full_at"), "理智将在 2026-10-13 19:45 回满。")

raw = {"sanity": 0, "sanity_exhausted": True, "sanity_cap": 360}
collector._enrich_record(raw, "MaaEnd", Path("/nonexistent/MaaEnd.log"), True, [], fin)
check("exhausted and 0: no sentence", raw.get("sanity_full_at") or "", "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
