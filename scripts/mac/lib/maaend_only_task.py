"""Run ONE MaaEnd task through AUTO-MAS: switch every other task off in the master
for one manual run, then switch them back on.

    winrun.sh --py scripts/mac/lib/maaend_only_task.py disable [TaskName]   # default AutoCollect
    run-one.sh MaaEnd
    winrun.sh --py scripts/mac/lib/maaend_only_task.py enable

The list of what was turned off is kept in state/collect-watch-test/disabled.json,
so `enable` never guesses. A test run means that one task, never the daily list
(the user's order of 2026-09-14).
"""
import json
import sys
sys.path.insert(0, r"C:\ProgramData\ark-relay")
from pathlib import Path
from ark_relay.__main__ import _load_dotenv
_load_dotenv(Path(r"C:\ProgramData\ark-relay\.env"))
from ark_relay.config import Config, atomic_write_text  # noqa: E402
from ark_relay import mastercfg  # noqa: E402
mode = sys.argv[1]
keep = sys.argv[2] if len(sys.argv) > 2 else "AutoCollect"
cfg = Config()
f = mastercfg.maaend_master(cfg.automas_dir)
doc = json.loads(f.read_text(encoding="utf-8"))
tasks = doc["instances"][0]["tasks"]
store = Path(cfg.state_dir) / "collect-watch-test" / "disabled.json"
if mode == "disable":
    off = [t["taskName"] for t in tasks if t.get("enabled") and t.get("taskName") != keep]
    for t in tasks:
        if t["taskName"] in off:
            t["enabled"] = False
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(off, ensure_ascii=False), encoding="utf-8")
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    print("turned off:", off)
else:
    off = json.loads(store.read_text(encoding="utf-8"))
    for t in tasks:
        if t["taskName"] in off:
            t["enabled"] = True
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    store.unlink()
    print("turned back on:", off)
doc = json.loads(f.read_text(encoding="utf-8"))
print("enabled now:", [t["taskName"] for t in doc["instances"][0]["tasks"] if t.get("enabled")])
ac = next((t for t in doc["instances"][0]["tasks"] if t["taskName"] == "AutoCollect"), None)
if ac:
    ov = ac.get("optionValues") or {}
    print("routes:", {k: v.get("caseNames") for k, v in ov.items() if k.endswith("Routes") and v.get("caseNames")})
