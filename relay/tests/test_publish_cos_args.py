"""publish-cos.py: only a bare call publishes.

2026-10-10 18:04 `publish-cos.py --help` was run to read the usage; the script took
every argument but --check as "publish" and put a branch on COS as the machine's
next version.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("publish_cos", ROOT / "scripts/mac/publish-cos.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


reached = []


class _Stop(Exception):
    pass


def _client():
    reached.append(True)
    raise _Stop


pc._client = _client
for args, rc in ((["--help"], 0), (["-h"], 0), (["--dry-run"], 2), (["--check", "x"], 2)):
    reached.clear()
    check(f"{' '.join(args)}：不连 COS、退出码 {rc}", (pc.main(list(args)), reached), (rc, []))
for args in ([], ["--check"]):
    reached.clear()
    try:
        pc.main(list(args))
    except _Stop:
        pass
    check(f"{' '.join(args) or '不带参数'}：照常连 COS", reached, [True])

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
