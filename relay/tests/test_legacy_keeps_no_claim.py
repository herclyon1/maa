"""The uninstall leaves his echo-farm no-claim file alone.

2026-10-13 (audit of the install / switch-over block, outside its scope, item 7 of the
fix list): relay/handover/legacy-items.json listed C:\\ProgramData\\ark-okww-farm.* for
deletion, which matched C:\\ProgramData\\ark-okww-farm.no-claim as well as the farm's .bat.
That file is his setting, not a leftover (coordinator's decision, 2026-10-13). Now the
.bat is listed on its own and the .no-claim file is `keep`. legacy.remove() is run
against a fake filesystem where both exist.
"""
import fnmatch
import json
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY.parent / "packaging"))

import legacy  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


NO_CLAIM = "C:\\ProgramData\\ark-okww-farm.no-claim"
BAT = "C:\\ProgramData\\ark-okww-farm.bat"
ON_DISK = [NO_CLAIM, BAT]

deleted = []
saved = (legacy.ITEMS, legacy.glob.glob, legacy._delete_path, legacy._run, legacy._task_names,
         legacy.service_exists, legacy.TAKEOVER_RECORD, legacy.os.path.expandvars)
legacy.ITEMS = RELAY / "handover" / "legacy-items.json"
legacy.glob.glob = lambda pat: [p for p in ON_DISK if fnmatch.fnmatch(p.lower(), pat.lower())]
legacy._delete_path = lambda p: deleted.append(str(p)) or []
legacy._run = lambda *cmd: 0
legacy._task_names = lambda: []
legacy.service_exists = lambda name: False
legacy.TAKEOVER_RECORD = RELAY / "tests" / "no-such-takeover-record.json"
legacy.os.path.expandvars = lambda s: s
try:
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        legacy.remove()
finally:
    (legacy.ITEMS, legacy.glob.glob, legacy._delete_path, legacy._run, legacy._task_names,
     legacy.service_exists, legacy.TAKEOVER_RECORD, legacy.os.path.expandvars) = saved

print("[legacy.remove with the farm's files on disk]")
check("the no-claim file is not deleted", [d for d in deleted if d.lower().endswith(".no-claim")], [])
check("the farm's .bat still is", BAT in deleted, True)

print("[legacy-items.json says so]")
items = json.loads((RELAY / "handover" / "legacy-items.json").read_text(encoding="utf-8"))["items"]
mine = [it for it in items if it.get("path", "").lower() == NO_CLAIM.lower()]
check("the no-claim file is listed as keep", [it["action"] for it in mine], ["keep"])
hits = [it["path"] for it in items if it.get("action") in ("remove", "takeover")
        and it.get("kind") in ("file", "glob", "dir")
        and fnmatch.fnmatch(NO_CLAIM.lower(), it["path"].lower())]
check("no remove / takeover path matches it", hits, [])

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
