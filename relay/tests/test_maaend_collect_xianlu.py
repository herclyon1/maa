#!/usr/bin/env python3
"""自动采集 walking only routes 1-3 is work done, not a false green.

MaaEnd spells its first routes 「线路N：」 (fixtures/maaend-collect-xianlu-1012.log:
the start, 线路1-3 and finish lines of 2026-10-12 MaaEnd-06-04-00.log). The work
check accepted only 「路线N：」, so a day with routes 1-3 alone would be red.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify.outcome import maaend_checks  # noqa: E402

text = (Path(__file__).parent / "fixtures" / "maaend-collect-xianlu-1012.log").read_text(encoding="utf-8")
got = {c.label: c.ok for c in maaend_checks(text, []) if "自动采集" in c.label}
ok = got.get("自动采集 真的走了路线") is True
print(("  ✓ " if ok else "  ✗ ") + f"线路1-3 count as walked routes: {got}")
sys.exit(0 if ok else 1)
