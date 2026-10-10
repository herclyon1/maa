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
                # 一行赋多个属性也算定义：`self.a, self.b = x, y`。
                # 2026-09-08 漏过这种写法，把 _DirWatch 正常的三个属性报成「没定义」。
                for t in (tgt.elts if isinstance(tgt, (ast.Tuple, ast.List)) else [tgt]):
                    if (isinstance(t, ast.Attribute)
                            and isinstance(t.value, ast.Name) and t.value.id == "self"):
                        out.add(t.attr)
                    elif isinstance(t, ast.Name):
                        out.add(t.id)        # class-level attribute
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


def module_name(f: Path) -> str:
    """Dotted import name of a scanned file: ark_relay/core/config.py -> ark_relay.core.config."""
    parts = list(f.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class Index:
    """Top-level classes and `from ... import` bindings of every scanned module.

    A subclass may use `self.x` defined only on its base class (GardenGate and
    WeeklyBossGate inherit `_load`, `_save`, `automas_dir` from weekgate.WeekGate).
    The base is looked up in the scanned source - same module, or followed through
    `from <module> import <name>` (relative imports and re-exports included). A base
    that cannot be found in the scanned files (stdlib, third-party, `import x` then
    `x.Base`) adds nothing, so those classes are checked exactly as before.
    """

    def __init__(self, trees: dict[str, tuple[ast.Module, bool]]):
        self.classes: dict[str, dict[str, ast.ClassDef]] = {}
        self.imports: dict[str, dict[str, tuple[str, str]]] = {}
        for mod, (tree, is_pkg) in trees.items():
            self.classes[mod] = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
            imps: dict[str, tuple[str, str]] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    src = node.module or ""
                    if node.level:
                        pkg = mod.split(".") if is_pkg else mod.split(".")[:-1]
                        pkg = pkg[:len(pkg) - (node.level - 1)]
                        src = ".".join(pkg + ([src] if src else []))
                    for a in node.names:
                        imps[a.asname or a.name] = (src, a.name)
            self.imports[mod] = imps

    def lookup(self, mod: str, name: str, depth: int = 0) -> "tuple[str, ast.ClassDef] | None":
        if depth > 10:
            return None
        if name in self.classes.get(mod, {}):
            return mod, self.classes[mod][name]
        src = self.imports.get(mod, {}).get(name)
        if src is None:
            return None
        return self.lookup(src[0], src[1], depth + 1)

    def inherited(self, mod: str, cls: ast.ClassDef, seen=None) -> set[str]:
        """Names defined on every base class reachable in the scanned source."""
        seen = set() if seen is None else seen
        out: set[str] = set()
        for b in cls.bases:
            if not isinstance(b, ast.Name):
                continue
            hit = self.lookup(mod, b.id)
            if hit is None or id(hit[1]) in seen:
                continue
            seen.add(id(hit[1]))
            out |= defined_names(hit[1]) | INHERITED.get(hit[1].name, set())
            out |= self.inherited(hit[0], hit[1], seen)
        return out


def main() -> int:
    files = sorted(list([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "okww_patches", "machinechecks"} & set(p.parts)])
                   + [ROOT / "service.py", ROOT / "boot_stages.py"])
    # 地板：glob 扫到 0 个文件也会打印「通过」，闸门就成了摆设——
    # 目录改名、路径写错都会静默失效。2026-09-08 回放测试栽过一次。
    if len(files) < 20:
        print(f"  ✗ 只扫到 {len(files)} 个文件，至少该有 20 个——路径不对或目录改名了")
        return 1
    problems = []
    checked = 0
    trees = {module_name(f): (ast.parse(f.read_text(encoding="utf-8"), filename=str(f)),
                              f.name == "__init__.py")
             for f in files}
    index = Index(trees)
    for f in files:
        mod = module_name(f)
        tree = trees[mod][0]
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            checked += 1
            known = (defined_names(cls) | INHERITED.get(cls.name, set())
                     | index.inherited(mod, cls))
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
