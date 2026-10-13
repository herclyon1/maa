#!/usr/bin/env python3
"""The scoreboard's 「自 … 起」 is on the machine clock, like the rest of relay.log.

relay.log:33229, written at 10-12 11:49:59 Beijing, said 「自 10-12 12:38 起」
for since 2026-10-12T11:38:15+08:00: the Tokyo clock inside a Beijing log.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core.ledger import State
from ark_relay.features.report import scoreboard
from _tmp import tmpdir

d = tmpdir()
st = State(Path(d))
st.store.set("versions", "scoreboard", {"20261012033118": {"runs": 1, "since": "2026-10-12T11:38:15+08:00"}})
got = scoreboard.line(st.store, "20261012033118")
ok = "（自 10-12 11:38 起）" in got
print(("  ✓ " if ok else "  ✗ ") + got)
print("\n" + ("all checks passed" if ok else "FAILED"))
sys.exit(0 if ok else 1)
