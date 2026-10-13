#!/usr/bin/env python3
"""MAA setting writes: the master copy is required, and a failure says what was written.

AUTO-MAS copies data/<script>/<user>/ConfigFile over MAA's config dir before each
run (AUTO-MAS v5.7 task/MAA/AutoProxy.py _copy_source_config). The old writer
skipped a missing master, wrote only MAA's own copy and reported success - the
change was gone at the next run. And when the second file failed, the first was
already written but the reply said the change was refused.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import mastercfg

FAILED: list[str] = []
DOC = {"Current": "Default", "Configurations": {"Default": {"TaskQueue": [
    {"Type": "StartUp"}, {"Type": "Infrast", "UsesOfDrones": "Money"}]}}}


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def drones(f: Path) -> str:
    return mastercfg._maa_infrast(json.loads(f.read_text(encoding="utf-8")))["UsesOfDrones"]


def tree(master_doc=DOC, own_doc=DOC):
    root = tmpdir()
    automas, maa = root / "AUTO-MAS", root / "MAA"
    mf = automas / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"
    mf.parent.mkdir(parents=True)
    if master_doc is not None:
        mf.write_text(json.dumps(master_doc), encoding="utf-8")
    own = maa / "config" / "gui.new.json"
    own.parent.mkdir(parents=True)
    own.write_text(own_doc if isinstance(own_doc, str) else json.dumps(own_doc), encoding="utf-8")
    return automas, maa, mf, own


def write(automas, maa):
    """write_maa's reply; an exception escaping it is a failure, kept as text."""
    try:
        return mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
    except Exception as exc:  # noqa: BLE001
        return None, f"raised {type(exc).__name__}: {exc}"


print("[no master copy, MAA's own copy present]")
automas, maa, mf, own = tree(master_doc=None)
ok, msg = write(automas, maa)
require("refused", ok is False, msg)
require("MAA's own copy untouched", drones(own) == "Money", drones(own))
require("says the master is missing", "母本" in msg, msg)

print("[MAA's own copy has no Infrast task]")
automas, maa, mf, own = tree(own_doc={"Current": "Default", "Configurations": {"Default": {"TaskQueue": []}}})
ok, msg = write(automas, maa)
require("refused", ok is False, msg)
require("the master was not written either", drones(mf) == "Money", drones(mf))

print("[MAA's own copy does not parse]")
automas, maa, mf, own = tree(own_doc="{broken")
ok, msg = write(automas, maa)
require("refused without an exception, master untouched", ok is False and drones(mf) == "Money", msg)

print("[MAA's own copy fails at write time, after the master]")
automas, maa, mf, own = tree()
real = mastercfg._write_maa_copies.__globals__["atomic_write_text"]


def fail_own(path, text):
    if Path(path) == own:
        raise PermissionError("locked")
    real(path, text)


mastercfg._write_maa_copies.__globals__["atomic_write_text"] = fail_own
try:
    ok, msg = write(automas, maa)
finally:
    mastercfg._write_maa_copies.__globals__["atomic_write_text"] = real
require("master is written", drones(mf) == "PureGold", drones(mf))
require("the reply says the master is already changed", "母本已经改好" in msg, msg)

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
