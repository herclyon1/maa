"""Whether a run should have farmed nests follows upstream's own condition.

OK-WW v3.7.4 DailyTask.py:84-93 runs the nests when 「Auto Farm all Nightmare
Nest」 is an additional task, or when 「Farm Nightmare Nest for Daily Echo」 (default
True, :37) is on, the farm target is not Tacet Suppression (the default) and the
daily reward is not ready. gamelogs._okww_nest_expected also said True for a
leftover 「Only Farm These Nests」 text or the echo flag alone, so unticking 「Auto
Farm all Nightmare Nest」 turned every daily red (audit 2026-10-13 item 9). The
daily-reward part is the log's (outcome.okww_checks), not the config's.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.features.alarm.gamelogs import _okww_nest_expected
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas(daily=None, nest=None):
    root = tmpdir()
    d = root / "data" / "okww-id" / "Default" / "ConfigFile"
    d.mkdir(parents=True)
    if daily is not None:
        (d / "DailyTask.json").write_text(json.dumps(daily), encoding="utf-8")
    if nest is not None:
        (d / "NightmareNestTask.json").write_text(json.dumps(nest), encoding="utf-8")
    return root


ADDS = "Additional Tasks to Run After Daily Task"
ECHO = "Farm Nightmare Nest for Daily Echo"
AUTO = "Auto Farm all Nightmare Nest"

print("[Auto Farm all Nightmare Nest: nests run]")
check("in the additional tasks", _okww_nest_expected(automas({ADDS: [AUTO], ECHO: False})), True)

print("\n[the daily-echo flag: only when the farm target is not Tacet Suppression]")
check("flag on, farming Tacet (upstream skips the nest)",
      _okww_nest_expected(automas({ECHO: True, "Which to Farm": "Tacet Suppression", ADDS: []})), False)
check("flag on, farming Forgery", _okww_nest_expected(automas({ECHO: True, "Which to Farm": "Forgery Challenge"})), True)
check("flag absent = default on; target absent = default Tacet", _okww_nest_expected(automas({ADDS: []})), False)
check("flag absent = default on, farming Simulation",
      _okww_nest_expected(automas({"Which to Farm": "Simulation Challenge"})), True)
check("flag off, farming Forgery", _okww_nest_expected(automas({ECHO: False, "Which to Farm": "Forgery Challenge"})), False)

print("\n[a leftover nest filter does not make nests run]")
check("filter text, Auto Farm unticked, farming Tacet",
      _okww_nest_expected(automas({ECHO: True, ADDS: []}, {"Only Farm These Nests": "落渊南丘"})), False)

print("\n[the config cannot be read: None, never a guess]")
check("no automas dir", _okww_nest_expected(None), None)
check("no DailyTask.json (only the nest config)",
      _okww_nest_expected(automas(None, {"Only Farm These Nests": "落渊南丘"})), None)

print("\n[the verdict's 「cannot read the config」 item names the file that decides (item 19)]")
import types  # noqa: E402

from ark_relay.features.alarm import verdict  # noqa: E402

seen = {}
real_judged = verdict._judged
verdict._judged = lambda rec, checks, *a, **k: seen.setdefault("checks", checks)
try:
    log = tmpdir() / "OK-WW.log"
    log.write_text("Daily Task Completed\n", encoding="utf-8")
    rec = types.SimpleNamespace(script="OK-WW", log_path=log)
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=automas(None, {"Only Farm These Nests": "x"})))
    verdict._verify_outcome(eng, rec)
finally:
    verdict._judged = real_judged
detail = next((c.detail for c in seen.get("checks", []) if c.label == "能读到 OK-WW 生效中的配置"), "")
check("names DailyTask.json", "DailyTask.json" in detail, True)
check("no longer names NightmareNestTask.json", "NightmareNestTask.json" in detail, False)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
