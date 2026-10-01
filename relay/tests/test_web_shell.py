"""web/sw.js SHELL holds every file the page needs to open offline (V1 独核 09-23 ④).

Static src / href in index.html (accept.js excepted: it loads only with ?accept), the
manifest's icons, and the tab bar lens family tab-lens.js fetches at run time together
with the map images its lens-filter.svg names and the worker it starts (lens-worker.js).
"""
import json
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
LOCAL = re.compile(r'(?:src|href)\s*=\s*"(?!https?:|//|data:|mailto:|#)([^"?#]+)')


def shell() -> set[str]:
    js = (WEB / "sw.js").read_text(encoding="utf-8")
    body = re.search(r"const SHELL = \[(.*?)\];", js, re.S).group(1)
    return set(re.findall(r'"([^"]+)"', body))


def needed() -> set[str]:
    refs = set(LOCAL.findall((WEB / "index.html").read_text(encoding="utf-8")))
    refs.discard("accept.js")
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    refs |= {i["src"].split("?")[0] for i in manifest["icons"]}
    tab = "assets/lens/tab5/"
    refs |= {tab + "lens-filter.svg", tab + "lens-field.json"}
    refs |= set(LOCAL.findall((WEB / tab / "lens-filter.svg").read_text(encoding="utf-8")))
    # the workers tab-lens.js starts (new Worker(new URL("lens-worker.js" + …, its own src))): a sibling of the script
    lens = (WEB / "assets/lens/tab-lens.js").read_text(encoding="utf-8")
    refs |= {"assets/lens/" + w for w in re.findall(r'new Worker\(new URL\("([^"?]+)"', lens)}
    return {r[2:] if r.startswith("./") else r for r in refs}


fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


check("SHELL covers every file the page opens with", sorted(needed() - shell()), [])
check("every SHELL entry exists under web/", sorted(f for f in shell() if f != "./" and not (WEB / f).exists()), [])

print()
if fails:
    print(f"✗ {len(fails)} failed: {fails}")
    sys.exit(1)
print(f"all checks passed ({len(shell())} SHELL entries)")
