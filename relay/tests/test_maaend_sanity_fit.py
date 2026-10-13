#!/usr/bin/env python3
"""Endfield sanity is reported as a figure only when the log's readings fit the
per-claim rule (40 per 「补充理智」 booster, collector_maaend._claims_fit).

The real 10-08 MaaEnd-05-29-15.log fits: 237 - 160 + 1 booster = 117 read next.
With that one 「补充理智」 line taken out the same readings no longer fit
(237 - 160 = 77, yet 117 is read 79 s later): the report must say
「理智消耗没读到」, not a number. Before: 「理智 720，加强剂 13」.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import ledger_rows
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.verify.collector_maaend import parse_maaend_log

LOG = Path(__file__).resolve().parent / "fixtures" / "maaend-sanity-1013" / "2026-10-08_MaaEnd-05-29-15.log"
fails: list[str] = []


def require(name, ok, detail=""):
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


fin = datetime(2026, 10, 8, 9, 57, tzinfo=SERVER_TZ)


def cost_row(o):
    return ledger_rows._block_maaend({"ok": True, "raw": o, "sanity": o.get("sanity")}, o, fin)[1]


real = parse_maaend_log(LOG)
require("real log fits: 720 spent", real.get("maaend_sanity_spent") == 720 and not real.get("maaend_sanity_unfit"),
        f"got {real.get('maaend_sanity_spent')!r}, unfit {real.get('maaend_sanity_unfit')!r}")
require("real log cost row", cost_row(real) == ["理智 720，加强剂 14"], f"got {cost_row(real)!r}")

lines = LOG.read_text(encoding="utf-8").splitlines(keepends=True)
first = next(i for i, x in enumerate(lines) if "补充理智" in x)
with tempfile.TemporaryDirectory() as d:
    bad = Path(d) / LOG.name
    bad.write_text("".join(lines[:first] + lines[first + 1:]), encoding="utf-8")
    o = parse_maaend_log(bad)
require("misfit: no spent figure", o.get("maaend_sanity_spent") is None, f"got {o.get('maaend_sanity_spent')!r}")
require("misfit: not filled in later", o.get("maaend_sanity_runs_only") is None, f"got {o.get('maaend_sanity_runs_only')!r}")
require("misfit: cost row says 没读到", cost_row(o) == ["理智消耗没读到，加强剂 13"], f"got {cost_row(o)!r}")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
