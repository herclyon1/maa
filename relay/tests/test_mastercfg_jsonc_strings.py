#!/usr/bin/env python3
"""MaaEnd definitions are JSONC: comments and trailing commas go, string contents stay.

The old trailing-comma regex also ran inside strings and turned the `\\d{6,}` of
AutoStockStaple.json's verify rule into `\\d{6}`, so writing 12000000 (a value
MaaEnd's own rule accepts) to 自动囤货's reserve was refused as 「不合格式」.
Fixture: tests/fixtures/maaend-v2.32-autostock (upstream excerpt, see SOURCE.txt).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import mastercfg

FX = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-autostock"
FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def master_with_reserve(value: str) -> Path:
    automas = tmpdir() / "automas"
    cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
        {"taskName": "AutoStockStaple", "enabled": True, "optionValues": {
            "AutoStockReserveWuling": {"type": "input", "values": {"ReserveWuling": value}}}},
    ]}]}), encoding="utf-8")
    return automas


# 1. The walker itself: string contents survive, commas outside strings go.
src = '{"a": "x,}", "b": "\\\\d{6,}", "c": [1, 2, ], // note\n "d": {"e": 1, },}'
got = json.loads(mastercfg._strip_jsonc(src))
require("「,}」 inside a string is kept", got["a"] == "x,}", repr(got["a"]))
require("a regex quantifier {6,} inside a string is kept", got["b"] == "\\d{6,}", repr(got["b"]))
require("trailing commas outside strings are dropped", got["c"] == [1, 2] and got["d"] == {"e": 1})

# 2. The real definition reads back with MaaEnd's own rule intact.
rule = mastercfg._maaend_defs(FX)[0]["AutoStockReserveWuling"]["inputs"][0]["verify"]
require("AutoStockReserveWuling's verify rule is upstream's", rule.endswith("\\d{6,})$"), rule)
require("MaaEnd's own rule accepts 12000000", bool(re.fullmatch(rule, "12000000")))

# 3. Writing that value is accepted and lands in the master copy.
automas = master_with_reserve("240000")
ok, msg = mastercfg.write_maaend(automas, FX, "AutoStockStaple/AutoStockReserveWuling", "12000000")
require("write 12000000 is accepted", ok, msg)
doc = json.loads(mastercfg.maaend_master(automas).read_text(encoding="utf-8"))
landed = doc["instances"][0]["tasks"][0]["optionValues"]["AutoStockReserveWuling"]["values"]["ReserveWuling"]
require("12000000 is in the master copy", landed == "12000000", landed)

# 4. A value the rule really rejects is still refused.
ok, msg = mastercfg.write_maaend(automas, FX, "AutoStockStaple/AutoStockReserveWuling", "1000")
require("write 1000 (below the rule) is refused", not ok, msg)

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
