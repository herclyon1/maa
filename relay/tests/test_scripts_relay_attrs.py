"""Every name the helper scripts read off an ark_relay module still exists there.

The scripts under scripts/windows/ and scripts/mac/lib/ are shipped to the game
machine by winrun and import ark_relay at run time, so no relay test ever imports
them. On 2026-10-10 05:26 okww-check.sh died with

    AttributeError: module 'ark_relay.weeklyboss' has no attribute '_okww_file'

because 7425eff4 (2026-09-08) removed that helper and okww-landed.py still called
it. This walks each script's AST, resolves `from ark_relay import m as x`,
`import ark_relay.m as x` and `from ark_relay.m import a`, and requires every
`x.attr` / imported name to exist on the real module.
"""
import ast
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
DIRS = [ROOT / "scripts" / "windows", ROOT / "scripts" / "mac" / "lib"]

fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


def missing_names(src: str) -> list:
    tree = ast.parse(src)
    alias = {}
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "ark_relay":
            for a in node.names:
                alias[a.asname or a.name] = f"ark_relay.{a.name}"
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ark_relay."):
            mod = importlib.import_module(node.module)
            out += [f"{node.module}.{a.name}" for a in node.names if not hasattr(mod, a.name)]
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("ark_relay.") and a.asname:
                    alias[a.asname] = a.name
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in alias):
            mod = importlib.import_module(alias[node.value.id])
            if not hasattr(mod, node.attr):
                out.append(f"{alias[node.value.id]}.{node.attr}")
    return out


bad = {}
for d in DIRS:
    for f in sorted(d.glob("*.py")):
        miss = missing_names(f.read_text(encoding="utf-8"))
        if miss:
            bad[str(f.relative_to(ROOT))] = miss
check("every ark_relay name the scripts use exists", bad, {})

# The 05:26 crash, from the pre-fix okww-landed.py:7 and :14 verbatim.
old = ("from ark_relay import weeklyboss as W  # noqa: E402\n"
       'o = json.loads(W._okww_file(name).read_text(encoding="utf-8"))\n')
check("the 10-10 okww-check line is caught", missing_names(old), ["ark_relay.weeklyboss._okww_file"])
check("names that exist pass",
      missing_names("from ark_relay import weeklyboss as W\nW.DAILY\nW._file\nW.name_from_log\n"), [])
check("a missing from-import is caught",
      missing_names("from ark_relay.weeklyboss import nope\n"), ["ark_relay.weeklyboss.nope"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
