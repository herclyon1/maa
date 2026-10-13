#!/usr/bin/env python3
"""refresh_raw applies the "MAA sanity never read" rule, like bookkeeping does.

Real 2026-10-09 MAA-08-03-19 (fixtures/refresh-unread-1009): Success!, combat off,
AUTO-MAS wrote sanity 0 with no refill sentence. It was booked before the rule
(cf246b6f) as sanity 0; re-reported, it has to read as unread, not 0. The log is
the original's first 8 and last 5 lines.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import collector  # noqa: E402

D = Path(__file__).parent / "fixtures" / "refresh-unread-1009"
e = json.loads((D / "ledger.jsonl").read_text(encoding="utf-8"))
out = collector.refresh_raw(e, D)
got = (out.get("sanity"), out["raw"].get("sanity"), out["raw"].get("sanity_unread"))
ok = got == (None, None, True)
print(("  ✓ " if ok else "  ✗ ") + f"unread after refresh: {got}")
print("\n" + ("all checks passed" if ok else "FAILED"))
sys.exit(0 if ok else 1)
