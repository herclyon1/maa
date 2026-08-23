"""Every `self.x` used in the relay must actually exist.

2026-08-23: `Engine._boot_time` was called from three places and never
defined. Python does not complain until the line runs, and the line only runs
on a boot where a queue's time has already passed - so it sat undetected from
2026-08-21 until the morning it swallowed the daily report and the power-off.

The service loop catches exceptions so one bad tick cannot kill the relay.
That is right, and it is also why this went unnoticed: the relay stayed up,
logged an AttributeError, and quietly did none of the work that follows.

A whole class of bug - typo'd attribute, method renamed at one call site,
method planned and never written - is a static fact about the source. This
checks it, so it can never again depend on a particular morning to surface.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Names that genuinely come from somewhere this file cannot see.
INHERITED = {
    "ArkRelayService": {
        # win32serviceutil.ServiceFramework
        "ReportServiceStatus", "SvcStop", "SvcDoRun", "stop_event",
    },
}


def defined_names(cls: ast.ClassDef) -> set[str]:
    out = set()
    for node in ast.walk(cls):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                    out.add(tgt.attr)
                elif isinstance(tgt, ast.Name):
                    out.add(tgt.id)          # class-level attribute
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if (isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                out.add(tgt.attr)
            elif isinstance(tgt, ast.Name):
                out.add(tgt.id)
        elif isinstance(node, ast.For):
            tgt = node.target
            if (isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                out.add(tgt.attr)
    return out


def used_names(cls: ast.ClassDef) -> dict[str, int]:
    out: dict[str, int] = {}
    for node in ast.walk(cls):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "self"
                and isinstance(node.ctx, ast.Load)):
            out.setdefault(node.attr, node.lineno)
    return out


def main() -> int:
    files = sorted(list((ROOT / "ark_relay").glob("*.py")) + [ROOT / "service.py"])
    problems = []
    checked = 0
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            checked += 1
            known = defined_names(cls) | INHERITED.get(cls.name, set())
            for attr, line in sorted(used_names(cls).items()):
                if attr.startswith("__") or attr in known:
                    continue
                problems.append(f"{f.relative_to(ROOT)}:{line} {cls.name}.{attr} 用了但没定义")
    print(f"  检查了 {len(files)} 个文件、{checked} 个类")
    for p in problems:
        print(f"  FAIL {p}")
    if problems:
        print("FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
