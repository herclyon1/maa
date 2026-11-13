"""The farm scripts' own power-off stays out of the group (shutdown_signs.farm_poweroff_planned).

2026-11-13 08:22:20 the Arknights farm (the farm script is_run.py) powered the machine off at its
08:20 deadline; AUTO-MAS exited as Windows went down and the relay pushed it to the group as a relay
fault. The farm now leaves C:\\ProgramData\\ark-farm-poweroff.json right before `shutdown /s`. Gemini
2026-11-13 10:19: only when the mark names a farm script, its outcome is a normal end, the request came
from shutdown.exe and the mark is at most 30 minutes older than the request - anything else is pushed.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.host import shutdown_signs as S

fails = []


def check(label, got, want=True):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    if not ok:
        fails.append(label)


TMP = tmpdir()
REQ_AT = datetime(2026, 11, 13, 0, 20, 6, tzinfo=timezone.utc)      # 08:20:06 on the relay's clock
ASKED = {"clock": "08:20:06", "at": REQ_AT, "process": r"C:\WINDOWS\system32\shutdown.exe (INS)", "user": r"INS\Administrator"}


def mark(**kw):
    d = TMP / f"m{len(list(TMP.iterdir()))}"
    d.mkdir()
    body = {"at": REQ_AT.timestamp() - 1, "by": "is_run.py", "outcome": "deadline"}
    body.update(kw)
    (d / S.FARM_POWEROFF_MARK).write_text(json.dumps(body), encoding="utf-8")
    return d


print("[the farm's own deadline power-off is recognised]")
got = S.farm_poweroff_planned(ASKED, base=mark())
check("is_run.py deadline mark 1 s before the request", bool(got))
check("names the script", (got or {}).get("by"), "is_run.py")
check("the mark's time on the relay's clock", (got or {}).get("at"), "08:20:05")
check("spa_run.py counts too", bool(S.farm_poweroff_planned(ASKED, base=mark(by="spa_run.py", outcome="maxrounds"))))

print("[anything else is pushed as before]")
check("no mark", S.farm_poweroff_planned(ASKED, base=TMP / "nothing-here"), None)
check("no request standing", S.farm_poweroff_planned(None, base=mark()), None)
check("request not from shutdown.exe", S.farm_poweroff_planned(dict(ASKED, process=r"C:\Windows\explorer.exe"), base=mark()), None)
check("mark from another script", S.farm_poweroff_planned(ASKED, base=mark(by="someone.py")), None)
check("the farm failed", S.farm_poweroff_planned(ASKED, base=mark(outcome="failed")), None)
check("no outcome", S.farm_poweroff_planned(ASKED, base=mark(outcome="")), None)
check("mark 31 minutes before the request", S.farm_poweroff_planned(ASKED, base=mark(at=REQ_AT.timestamp() - 31 * 60)), None)
check("mark after the request (a later run)", S.farm_poweroff_planned(ASKED, base=mark(at=REQ_AT.timestamp() + 60)), None)
bad = TMP / "bad"
bad.mkdir()
(bad / S.FARM_POWEROFF_MARK).write_text("{not json", encoding="utf-8")
check("unreadable mark", S.farm_poweroff_planned(ASKED, base=bad), None)

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
