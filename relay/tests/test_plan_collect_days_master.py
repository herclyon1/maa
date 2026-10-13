#!/usr/bin/env python3
"""The plan's gathering-day line reads the master copy, not MaaEnd's own file.

Phone edits go to the master copy only (mastercfg.write_maaend); AUTO-MAS copies
it over MaaEnd's config/mxu-MaaEnd.json before each run. Reading MaaEnd's file
showed a phone change in 「明日安排」 only after the next run. With no
AutoCollectSchedule saved, MaaEnd runs on the option's default_case (all seven
days in tasks/AutoCollect.json), so the plan must not drop the line.
Days below are the real master copy's (10-11: Monday, Thursday).
Checked through next_plan (the 「明日安排」 text), with the machine's own AUTO-MAS
config (tests/fixtures/automas-config-2026-10-11) pointing MaaEnd at a temp dir.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import plan
from ark_relay.core.config import SERVER_TZ

FAILED: list[str] = []
FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-09-10" / "tasks" / "AutoCollect.json"
AUTOMAS_FX = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11" / "config"


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
    shutil.copytree(AUTOMAS_FX, automas / "config")
    sc = automas / "config" / "ScriptConfig.json"
    d = json.loads(sc.read_text(encoding="utf-8"))
    for inst in d["instances"]:
        info = d[inst["uid"]]["Info"]
        if "maaend" in str(info.get("Path", "")).lower():
            info["Path"] = str(maaend)
    sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return automas


def maaend_lines(automas, tomorrow):
    """The MaaEnd block's gathering line(s) in next_plan, for that tomorrow."""
    plan._tomorrow = lambda: tomorrow
    text = plan.next_plan(automas)
    return [ln.strip() for ln in text.splitlines() if "自动采集" in ln]


MON_THU = ["AutoCollectScheduleMonday", "AutoCollectScheduleThursday"]
TUESDAY = datetime(2026, 10, 13, 12, tzinfo=SERVER_TZ)
THURSDAY = datetime(2026, 10, 15, 12, tzinfo=SERVER_TZ)

print("[phone moved the days to Mon/Thu; MaaEnd's own file still says Tuesday only]")
automas = setup(MON_THU, ["AutoCollectScheduleTuesday"])
got = maaend_lines(automas, TUESDAY)
require("Tuesday is not a gathering day", got == ["自动采集仅 周一、四 跑"], repr(got))
got = maaend_lines(automas, THURSDAY)
require("Thursday is", len(got) == 1 and got[0].startswith("⏳ 先跑自动采集"), repr(got))

print("[no AutoCollectSchedule saved: MaaEnd's default_case, every day]")
automas = setup(None, None)
got = maaend_lines(automas, TUESDAY)
require("the line is still there and says it runs", len(got) == 1 and got[0].startswith("⏳ 先跑自动采集"), repr(got))

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
