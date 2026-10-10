"""Every pkg_layout name the packaged relay's callers use exists in pkg_layout.py.

2026-10-11: dd96d5a8 dropped link_state while app_main.py and pkg_deploy.py still
called it; the installed relay died at its first start with no log (cloud run
38091113646). The callers reach the module as `pkg_layout.x` or `pl.x`.
"""
import ast
import re
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
CALLERS = {
    RELAY / "app_main.py": "pkg_layout",
    ROOT / "scripts" / "windows" / "pkg_deploy.py": "pl",
}

tree = ast.parse((RELAY / "pkg_layout.py").read_text(encoding="utf-8"))
defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
defined |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
            if isinstance(t, ast.Name)}
defined |= {a.asname or a.name for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in n.names}

fails = []
for path, alias in CALLERS.items():
    used = set(re.findall(rf"\b{alias}\.([A-Za-z_]\w*)", path.read_text(encoding="utf-8")))
    missing = sorted(used - defined)
    print(f"{'ok' if not missing else 'FAIL'} {path.name}: uses {sorted(used)}; missing {missing}")
    if not used:
        fails.append(f"{path.name}: no {alias}.x use found (alias changed?)")
    if missing:
        fails.append(f"{path.name}: {missing}")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
