#!/usr/bin/env python3
"""migrate_maaend_options does not drop a live value because a definition file was unreadable.

MaaEnd v2.32: 9 of its 46 tasks take options from another file (AutoCollect and
four others from StashBackpack.json, AutoEssence from Location/*.json). When such
a file did not parse, its options looked dead and the migration deleted their
values from the master copy - MaaEnd then runs on defaults. prune_maaend_orphans
already refused on the same blind spots (8dbd1d3b); now the migration does too.
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


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def setup(stash_text: str, interface: "str | None" = '{"import": ["tasks/AutoCollect.json", "tasks/StashBackpack.json"]}'):
    root = tmpdir()
    automas = root / "automas"
    cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
        {"taskName": "AutoCollect", "enabled": True, "optionValues": {
            "AutoCollectMode": {"type": "select", "caseName": "Always"},
            "StashBackpackMode": {"type": "select", "caseName": "Deposit"},
            "OldDeadKey": {"type": "switch", "value": True}}}]}]}), encoding="utf-8")
    maaend = root / "maaend"
    (maaend / "tasks").mkdir(parents=True)
    if interface is not None:
        (maaend / "interface.json").write_text(interface, encoding="utf-8")
    (maaend / "tasks" / "AutoCollect.json").write_text(json.dumps({
        "task": [{"name": "AutoCollect", "option": ["AutoCollectMode", "StashBackpackMode"]}],
        "option": {"AutoCollectMode": {"type": "select", "cases": [{"name": "Always"}]}}}), encoding="utf-8")
    (maaend / "tasks" / "StashBackpack.json").write_text(stash_text, encoding="utf-8")
    return automas, maaend, cfg / "mxu-MaaEnd.json"


def values(master: Path) -> dict:
    return json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]


GOOD = json.dumps({"option": {"StashBackpackMode": {"type": "select", "cases": [{"name": "Deposit"}]}}})
BROKEN = GOOD[:-1] + " oops"           # StashBackpack.json does not parse but names its option

print("[every definition read: a dead key goes, the live ones stay]")
automas, maaend, master = setup(GOOD)
changes, note = mastercfg.migrate_maaend_options(automas, maaend)
require("OldDeadKey is removed", "OldDeadKey" not in values(master), note)
require("StashBackpackMode is kept", "StashBackpackMode" in values(master), note)

print("[StashBackpack.json does not parse]")
automas, maaend, master = setup(BROKEN)
changes, note = mastercfg.migrate_maaend_options(automas, maaend)
require("StashBackpackMode is not deleted", "StashBackpackMode" in values(master), repr(values(master)))
require("the migration refuses and names the file", not changes and "StashBackpack.json" in note, note)
require("nothing else is rewritten either", "OldDeadKey" in values(master), repr(values(master)))

print("[interface.json unreadable: the file list is a guess]")
automas, maaend, master = setup(GOOD, interface="{broken")
changes, note = mastercfg.migrate_maaend_options(automas, maaend)
require("refuses when MaaEnd's own file list cannot be read",
        not changes and "interface.json" in note and "OldDeadKey" in values(master), note)

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
