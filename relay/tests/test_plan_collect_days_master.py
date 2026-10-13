#!/usr/bin/env python3
"""The plan's gathering-day line reads the master copy, not MaaEnd's own file.

Phone edits go to the master copy only (mastercfg.write_maaend); AUTO-MAS copies
it over MaaEnd's config/mxu-MaaEnd.json before each run. Reading MaaEnd's file
showed a phone change in 「明日安排」 only after the next run. With no
AutoCollectSchedule saved, MaaEnd runs on the option's default_case (all seven
days in tasks/AutoCollect.json), so the plan must not drop the line.
Days below are the real master copy's (10-11: Monday, Thursday).
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import plan

FAILED: list[str] = []
FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-09-10" / "tasks" / "AutoCollect.json"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def doc(schedule):
    opts = {} if schedule is None else {"AutoCollectSchedule": {"type": "checkbox", "caseNames": schedule}}
    return {"instances": [{"id": "automas", "tasks": [
        {"taskName": "AutoCollect", "enabled": True, "optionValues": opts}]}]}


def setup(master_days, own_days):
    root = tmpdir()
    automas = root / "automas"
    cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    (cfg / "mxu-MaaEnd.json").write_text(json.dumps(doc(master_days)), encoding="utf-8")
    maaend = root / "maaend"
    (maaend / "config").mkdir(parents=True)
    (maaend / "tasks").mkdir()
    (maaend / "config" / "mxu-MaaEnd.json").write_text(json.dumps(doc(own_days)), encoding="utf-8")
    (maaend / "interface.json").write_text('{"import": ["tasks/AutoCollect.json"]}', encoding="utf-8")
    shutil.copy(FIX, maaend / "tasks" / "AutoCollect.json")
    return automas, maaend


MON_THU = ["AutoCollectScheduleMonday", "AutoCollectScheduleThursday"]
TUESDAY, THURSDAY = date(2026, 10, 13), date(2026, 10, 15)

print("[phone moved the days to Mon/Thu; MaaEnd's own file still says Tuesday only]")
automas, maaend = setup(MON_THU, ["AutoCollectScheduleTuesday"])
got = plan._maaend_extra_bits(automas, maaend, TUESDAY)
require("Tuesday is not a gathering day", got == ["自动采集仅 周一、四 跑"], repr(got))
got = plan._maaend_extra_bits(automas, maaend, THURSDAY)
require("Thursday is", len(got) == 1 and got[0].startswith("⏳ 先跑自动采集"), repr(got))

print("[no AutoCollectSchedule saved: MaaEnd's default_case, every day]")
automas, maaend = setup(None, None)
got = plan._maaend_extra_bits(automas, maaend, TUESDAY)
require("the line is still there and says it runs", len(got) == 1 and got[0].startswith("⏳ 先跑自动采集"), repr(got))

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
