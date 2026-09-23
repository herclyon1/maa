"""web/sw.js SHELL holds every file the page needs to open offline (V1 独核 09-23 ④).

Static src / href in index.html (accept.js excepted: it loads only with ?accept), the
manifest's icons, and the tab bar lens family tab-lens.js fetches at run time together
with the map images its lens-filter.svg names.
"""
import json
import re
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
    return {r[2:] if r.startswith("./") else r for r in refs}


def test_shell_covers_page():
    missing = sorted(needed() - shell())
    assert not missing, missing


def test_shell_files_exist():
    absent = sorted(f for f in shell() if f != "./" and not (WEB / f).exists())
    assert not absent, absent
