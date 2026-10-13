#!/usr/bin/env python3
"""write_maaend reads back the very item it wrote and compares it with what it wrote.

The old read-back went through read_maaend, which covers only the items the phone
page shows: a valid write of 自动囤货's reserve said 「'240000' → None」, and a file
that came back different from what was written still answered success.
Fixture: tests/fixtures/maaend-v2.32-autostock (upstream excerpt, see SOURCE.txt).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import mastercfg

FX = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-autostock"
PATH = "AutoStockStaple/AutoStockReserveWuling"
FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def master() -> Path:
    automas = tmpdir() / "automas"
    cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
        {"taskName": "AutoStockStaple", "enabled": True, "optionValues": {
            "AutoStockReserveWuling": {"type": "input", "values": {"ReserveWuling": "240000"}}}},
    ]}]}), encoding="utf-8")
    return automas


# 1. A good write names the value it read back, not None.
ok, msg = mastercfg.write_maaend(master(), FX, PATH, "240001")
require("write 240001 succeeds", ok, msg)
require("the answer shows the value read back", msg.endswith("'240000' → '240001'"), msg)

# 2. The file comes back different from what was written: refused.
real = mastercfg.atomic_write_text
mastercfg.atomic_write_text = lambda path, text, **k: Path(path).write_text(
    text.replace('"240001"', '"240000"'), encoding="utf-8")
try:
    ok, msg = mastercfg.write_maaend(master(), FX, PATH, "240001")
finally:
    mastercfg.atomic_write_text = real
require("a read-back that differs from the write is not a success", not ok, msg)

# 3. The task switch still reads back too.
automas = master()
ok, msg = mastercfg.write_maaend(automas, FX, "AutoStockStaple/@enabled", False)
require("switching the task off succeeds and says so", ok and msg.endswith("True → False"), msg)
mastercfg.atomic_write_text = lambda path, text, **k: Path(path).write_text(
    text.replace('"enabled": false', '"enabled": true'), encoding="utf-8")
try:
    ok, msg = mastercfg.write_maaend(master(), FX, "AutoStockStaple/@enabled", False)
finally:
    mastercfg.atomic_write_text = real
require("a task switch that reads back unchanged is not a success", not ok, msg)

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
