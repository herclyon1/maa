"""An unreadable annihilation week record is "unknown", not "not done".

Audit 2026-10-13 (weekly block, finding 5): WeeklyGate.settings() returned
bool(done), so when AUTO-MAS's record could not be read (_status gives done None)
the phone payload said 本周已完成 False and tomorrow's plan
(plan._annihilation_done_tomorrow) wrote 「剿灭 Annihilation」 - "it will run" -
instead of saying it could not tell. week_line already said 读不到 for the same
state. settings() now carries None, and the plan says 「剿灭 本周打没打满读不到」,
the wording the weekly boss uses (plan.py, _weekly_boss_state).

plan._annihilation_done_tomorrow's except stays: settings() does raise on a
ScriptConfig.json of the wrong shape (a top-level list -> AttributeError in
_maa_users), checked below; it now also answers None.

Plan text through next_plan with the machine's AUTO-MAS config
(fixtures/automas-config-2026-10-11), its MAA switch set to "Annihilation".
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import plan
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.weekly import annihilation as A

AUTOMAS_FX = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11" / "config"
# next_plan's maintenance notices come from the official sites; nothing here is about
# them, and no relay test may reach the internet (run 38363145659 sat in those
# fetches on Windows until the 180 s limit).
plan.maintenance_lines = lambda day: []

FAILED: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
    if not ok:
        FAILED.append(name)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


MON = datetime(2026, 10, 12, 8, 46, tzinfo=SERVER_TZ)
TUE_NOON = datetime(2026, 10, 13, 12, tzinfo=SERVER_TZ)

print("[settings(): unreadable is None, not False]")
with mock.patch.object(A, "_maa_user", lambda d: {}):
    check("AUTO-MAS unreadable", A.WeeklyGate(None, Path("automas")).settings(MON),
          {"本周已完成": None, "当前": ""})
check("no AUTO-MAS dir", A.WeeklyGate(None, None).settings(MON), {"本周已完成": None, "当前": ""})
done = {"Info": {"Annihilation": "Annihilation"}, "Data": {"AnnihilationCompletedWeek": A.week_key(MON)}}
with mock.patch.object(A, "_maa_user", lambda d: done):
    check("readable and done", A.WeeklyGate(None, Path("automas")).settings(MON)["本周已完成"], True)
not_done = {"Info": {"Annihilation": "Annihilation"}, "Data": {}}
with mock.patch.object(A, "_maa_user", lambda d: not_done):
    check("readable, never recorded: False", A.WeeklyGate(None, Path("automas")).settings(MON)["本周已完成"], False)

print("\n[week_key: the plain strftime]")
check("Monday 04:00 is the new week", A.week_key(datetime(2026, 10, 12, 4, 0, tzinfo=SERVER_TZ)), "2026-W42")
check("Monday 03:59 is the old one", A.week_key(datetime(2026, 10, 12, 3, 59, tzinfo=SERVER_TZ)), "2026-W41")

print("\n[tomorrow's plan says it cannot tell]")
automas = tmpdir() / "automas"
shutil.copytree(AUTOMAS_FX, automas / "config")
sc = automas / "config" / "ScriptConfig.json"
cfg = json.loads(sc.read_text(encoding="utf-8"))
for inst in cfg["instances"]:
    node = cfg[inst["uid"]]
    if node.get("Info", {}).get("Path", "").lower().endswith("maa"):
        for uid, user in node["SubConfigsInfo"]["UserData"].items():
            if isinstance(user, dict):
                user["Info"]["Annihilation"] = "Annihilation"
sc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
plan._tomorrow = lambda: TUE_NOON
with mock.patch.object(A, "_maa_user", lambda d: {}):
    check("_annihilation_done_tomorrow -> None", plan._annihilation_done_tomorrow(automas), None)
    lines = [ln.strip() for ln in plan.next_plan(automas).splitlines() if "剿灭" in ln]
check("the plan line", sorted(set(lines)), ["剿灭 本周打没打满读不到"])
with mock.patch.object(A, "_maa_user", lambda d: not_done):
    lines = [ln.strip() for ln in plan.next_plan(automas).splitlines() if "剿灭" in ln]
check("readable, not done: the map, as before", sorted(set(lines)) != ["剿灭 本周打没打满读不到"] and bool(lines), True)

print("\n[a ScriptConfig.json of the wrong shape: settings() raises, the plan still says 读不到]")
bad = tmpdir() / "bad"
(bad / "config").mkdir(parents=True)
(bad / "config" / "ScriptConfig.json").write_text("[]", encoding="utf-8")
grab = Grab()
logging.getLogger().addHandler(grab)
with mock.patch.object(A, "_going_down", lambda: True):      # read the file, skip the backend
    try:
        A.WeeklyGate(None, bad).settings(MON)
        raised = False
    except AttributeError:
        raised = True
    check("settings() raises", raised, True)
    check("plan answers None", plan._annihilation_done_tomorrow(bad), None)
logging.getLogger().removeHandler(grab)
check("one WARNING", len([r for r in grab.records if "剿灭" in r.getMessage()]), 1)

print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
sys.exit(1 if FAILED else 0)
