"""The evening health check judges annihilation by the post-hand-over model.

Review fix 3 of the 2026-10-11 hand-over (item 13): scripts/mac/lib/healthcheck.py
still required Info.Annihilation == "Close", the value the relay used to write
after the week's pass. AUTO-MAS now keeps the switch on the map and the week in
Data.AnnihilationCompletedWeek, so that check failed every night. The script runs
on the game machine against a live AUTO-MAS, so only its two pure functions are
loaded here (by AST, without running the script's top level).
"""
import ast
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.config import SERVER_TZ
from ark_relay.features.weekly.annihilation import week_key

SRC = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "lib" / "healthcheck.py"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        fails.append(label)


text = SRC.read_text(encoding="utf-8")
tree = ast.parse(text)
ns: dict = {}
wanted = {"game_week", "annihilation_check"}
found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
check("both functions are in healthcheck.py", sorted(n.name for n in found), sorted(wanted))
exec(compile(ast.Module(body=found, type_ignores=[]), str(SRC), "exec"), ns)

print("[the old rule is gone]")
check("no check that wants the switch Close", 'get("Annihilation") == "Close"' in text, False)

if "annihilation_check" in ns:
    ac, W = ns["annihilation_check"], "2026-W41"
    print("\n[the new rule]")
    check("on the map, week not done: fine (AUTO-MAS will fight it)",
          ac({"Annihilation": "Annihilation"}, {"AnnihilationCompletedWeek": "2026-W40"}, W)[0], True)
    check("on the map, week done: fine", ac({"Annihilation": "Annihilation"}, {"AnnihilationCompletedWeek": W}, W)[0],
          True)
    check("Close, week not done: wrong (nothing reopens it)",
          ac({"Annihilation": "Close"}, {"AnnihilationCompletedWeek": "2026-W40"}, W)[0], False)
    check("Close, no record at all: wrong", ac({"Annihilation": "Close"}, {}, W)[0], False)
    check("Close, week done: fine (same rule as the boot alarm)",
          ac({"Annihilation": "Close"}, {"AnnihilationCompletedWeek": W}, W)[0], True)
    check("the detail names the value", "'Close'" in ac({"Annihilation": "Close"}, {}, W)[1], True)

# time.tzset is POSIX only; the game machine itself runs on Beijing time, so on a
# Windows runner (UTC) this part cannot set the clock and is left to the Mac gate.
if "game_week" in ns and hasattr(time, "tzset"):
    print("\n[its week marker is the relay's (Monday 04:00 server time reset)]")
    import os
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Shanghai"          # the game machine's clock
    time.tzset()
    try:
        for t in (datetime(2026, 10, 5, 3, 59, tzinfo=SERVER_TZ), datetime(2026, 10, 5, 4, 1, tzinfo=SERVER_TZ),
                  datetime(2026, 1, 7, 12, 0, tzinfo=SERVER_TZ)):
            check(f"{t:%m-%d %H:%M}", ns["game_week"](t.timestamp()), week_key(t))
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
