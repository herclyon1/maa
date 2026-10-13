#!/usr/bin/env python3
"""Endfield's full-again time counts from the reading, and a floor 0 gets none.

fixtures/maaend-sanity-1013/2026-10-12_MaaEnd-06-04-00.log is that run's 协议空间
task: last reading 242 at 10:23:32, one double claim, 82 left. Skland at
10:24:03 read curStamina=82 with maxTs 1791891939 = 10-13 19:45:39 (relay.log
上机核对 #10). Anchored on the record's finish (10:58) the sentence said 20:19.
A 0 after 「理智不足，结束任务」 is max(0, …) of a subtraction, not a reading; a
time from it was 1.4-4.5 h late on 10-11 and 10-12.
An exact 0 from the per-claim rule is a reading and keeps its time: the 10-13
05:36 log with 198 changed to 160 (one double claim, 160 -> 0, then 「理智不足，
结束任务」) is full 360 x 7m12s after 09:53:22. With 198 changed to 60 the half
claim gives -20, floored to 0: no time. Before, both lost the time.
"""
import sys
import tempfile
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

src = (Path(__file__).parent / "fixtures" / "maaend-sanity-1013" / "2026-10-13_MaaEnd-05-36-57.log").read_text(encoding="utf-8")
fin = datetime(2026, 10, 13, 9, 54, tzinfo=SERVER_TZ)
for first, want_left, want in ((160, 0, "理智将在 2026-10-15 05:05 回满。"), (60, 0, "")):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "MaaEnd.log"
        p.write_text(src.replace("当前理智 198/360", f"当前理智 {first}/360"), encoding="utf-8")
        raw = {}
        collector._enrich_record(raw, "MaaEnd", p, True, [], fin)
    check(f"read {first}, exhausted: left", raw.get("sanity"), want_left)
    check(f"read {first}, exhausted: full-at", raw.get("sanity_full_at") or "", want)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
