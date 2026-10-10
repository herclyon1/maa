"""app_main.AppHost has every self.<name> that the ArkRelayService methods it borrows use.

2026-10-11: 971a1a27 made service.main call self._stop_in_boot, which AppHost did not
borrow; the installed relay died at every start with "'AppHost' object has no attribute
'_stop_in_boot'" and every switch-over went back to the old relay (cloud run
38094295924). Read from the source (pywin32 is not on the Mac).
"""
import ast
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]


def cls(path: Path, name: str) -> ast.ClassDef:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise SystemExit(f"FAIL no class {name} in {path.name}")


host = cls(RELAY / "app_main.py", "AppHost")
has = {t.id for n in host.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
has |= {n.name for n in host.body if isinstance(n, ast.FunctionDef)}
has |= {n.attr for n in ast.walk(host) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name) and n.value.id == "self"}
borrowed = {t.id: n.value.attr for n in host.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)
            and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Attribute)
            and n.value.value.attr == "ArkRelayService"}

svc = cls(RELAY / "service.py", "ArkRelayService")
methods = {n.name: n for n in svc.body if isinstance(n, ast.FunctionDef)}
fails = []
for name, src in sorted(borrowed.items()):
    if src not in methods:
        continue                                   # a class attribute such as _svc_name_
    used = {n.attr for n in ast.walk(methods[src]) if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "self"}
    missing = sorted(used - has)
    print(f"{'ok' if not missing else 'FAIL'} {src}: uses self.{sorted(used)}; AppHost lacks {missing}")
    if missing:
        fails.append(f"{src}: {missing}")
if "main" not in borrowed:
    fails.append("AppHost does not borrow ArkRelayService.main (this test reads the wrong thing)")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
