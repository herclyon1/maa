"""scripts/windows/okww-landed.py judges the OK-WW install the right way round.

Since 2026-09-09 the relay's OK-WW changes live in ok_tasks/ark_overrides.py and no
upstream file is edited (okww_overlay.py). The checker still expected 4 changed
spots in FarmEchoTask.py, so a clean install showed a red cross, and it passed
DailyTask.py / NightmareNestTask.py whatever their content (want=None). It also
never looked at the overlay itself. The script runs on import (it reads the
machine's .env), so its pure helpers are pulled out of the AST and run here.
"""
import ast
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "windows" / "okww-landed.py"
fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


src = SCRIPT.read_text(encoding="utf-8")
tree = ast.parse(src)
wanted = {"UPSTREAM_TASKS", "upstream_untouched", "overlay_problems"}
nodes = [n for n in tree.body
         if (isinstance(n, ast.FunctionDef) and n.name in wanted)
         or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in wanted for t in n.targets))]
ns: dict = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), "exec"), ns)
check("the helpers exist in the script", sorted(k for k in wanted if k in ns), sorted(wanted))
check("no 'None means pass' left in the script", "want is None" in src, False)
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)

print("[upstream files: 0 changed spots, every one of them]")
check("all three task files are checked",
      ns["UPSTREAM_TASKS"], ("FarmEchoTask.py", "DailyTask.py", "NightmareNestTask.py"))
check("a pristine file passes", ns["upstream_untouched"](0), True)
check("4 changed spots (the old patch count) fails", ns["upstream_untouched"](4), False)
check("1 changed spot fails", ns["upstream_untouched"](1), False)
loop = next(n for n in tree.body if isinstance(n, ast.For)
            and isinstance(n.iter, ast.Name) and n.iter.id == "UPSTREAM_TASKS")
check("the file loop judges with upstream_untouched",
      any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "upstream_untouched" for c in ast.walk(loop)), True)

print("[the overlay itself]")
good = {"applied": ["DailyTask.run"], "skipped": [], "error": None}
check("installed, same copy, bound: nothing to say", ns["overlay_problems"]("X", "X", good), [])
check("not installed", len(ns["overlay_problems"](None, "X", good)), 1)
check("an older copy", len(ns["overlay_problems"]("old", "X", good)), 1)
check("no report yet", len(ns["overlay_problems"]("X", "X", {})), 1)
check("report error", len(ns["overlay_problems"]("X", "X", dict(good, error="boom"))), 1)
check("an override skipped",
      len(ns["overlay_problems"]("X", "X", dict(good, skipped=[{"what": "NightmareNestTask.find_nest"}]))), 1)
check("nothing applied", len(ns["overlay_problems"]("X", "X", dict(good, applied=[]))), 1)
check("the script runs the overlay check at top level",
      any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "overlay_problems"
          for n in tree.body if not isinstance(n, ast.FunctionDef) for c in ast.walk(n)), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
