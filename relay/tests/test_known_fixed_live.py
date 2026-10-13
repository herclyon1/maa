"""Every known_fixed entry can still match: its message is logged at WARNING or above.

errwatch only sees WARNING and above, so a known_fixed key whose message is now
logged at INFO is dead weight - a recurrence of that kind could never be tagged.
The two 「库街区官方资讯里没找到 … 版本资讯帖」 keys were such entries after that
message became log.info (banners/wuwa_posters.py), audit s8 #5.

For each key: the fixed text before its first blanked part (# / <path> / ...) must
appear inside a .warning( / .error( / .exception( / .critical( call somewhere under
ark_relay/.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ark_relay.features.alarm import known_fixed  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


CALL = re.compile(r"\.(warning|error|exception|critical|info|debug)\(\s*(f?\"[^\"]*\"|f?'[^']*')", re.S)
levels: dict[str, set[str]] = {}
for f in (ROOT / "ark_relay").rglob("*.py"):
    if f.name == "known_fixed.py":
        continue
    for m in CALL.finditer(f.read_text(encoding="utf-8")):
        levels.setdefault(m.group(2), set()).add(m.group(1))

LOUD = {"warning", "error", "exception", "critical"}
for key in known_fixed.KNOWN:
    msg = key.split("|")[1]
    head = re.split(r"#|<path>|<url>|<id>", msg)[0].strip()
    found = {lv for lit, lvs in levels.items() if head in lit for lv in lvs}
    check(f"{key!r}: logged at WARNING or above", bool(found & LOUD), True)

print("\n" + (f"✗ {len(fails)} failed" if fails else "all checks passed"))
sys.exit(1 if fails else 0)
