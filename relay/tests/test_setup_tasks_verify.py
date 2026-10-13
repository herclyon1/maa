"""setup-tasks.ps1's verify list covers what the relay itself needs.

Its header and docs/OPERATIONS.md say it checks the scheduled tasks this system
needs, but until 2026-10-13 it checked only AUTO-MAS_AutoStart: a machine without
the installed relay's task (\\ArkRelay\\main) or its watchdog service
(ArkRelayWatchdog) printed OK. The names come from retire_legacy.py, which checks
exactly these before it retires the old service (new_relay_problems). No pwsh on
the Mac, so the script is read as text.
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = (ROOT / "scripts" / "windows" / "setup-tasks.ps1").read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location("retire_legacy", ROOT / "scripts" / "windows" / "retire_legacy.py")
rl = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT / "scripts" / "windows"))
sys.modules["retire_legacy"] = rl
spec.loader.exec_module(rl)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


verify = PS1[PS1.find('"--- verify ---"'):]
tasks = re.findall(r'foreach \(\$t in @\(([^)]*)\)\)', verify)
services = re.findall(r'foreach \(\$s in @\(([^)]*)\)\)', verify)
listed_tasks = re.findall(r'"([^"]+)"', tasks[0]) if tasks else []
listed_services = re.findall(r'"([^"]+)"', services[0]) if services else []
check("AUTO-MAS_AutoStart still checked", "AUTO-MAS_AutoStart" in listed_tasks, True)
check("the relay's task, as retire_legacy names it", f"{rl.NEW_TASK_FOLDER}\\{rl.NEW_TASK_NAME}" in listed_tasks, True)
check("the watchdog service, as retire_legacy names it", rl.NEW_WATCHDOG in listed_services, True)
check("a service that is there but not running is not OK", "-ne \"Running\"" in verify, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
