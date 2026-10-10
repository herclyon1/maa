#!/usr/bin/env python3
"""List relay.log ERROR lines that the error ledger (BOARD/报错台账.txt) has no entry for.

    scripts/mac/ledger-gap.py [--days N]      # default 2; exit 1 when something is missing

The house rule is that every error met goes into the ledger (报错 / 根因 / 已解决).
On 2026-10-10 the 04:28:51 ERROR was root-caused and fixed (30cc1e94) but never
written down, and 验收 found the gap at 22:4x. Memory is not a check, so this is.

An ERROR counts as recorded when one ledger line holds both its date (MM-DD) and its
time to the second (HH:MM:SS), as written in relay.log (the machine's clock). The
minute alone is not enough: the ledger's 「10-10 04:28 验收 报错：own_mess_guard_test…」
is another error that happened in the same minute. The log is read on the
machine with arklog.since_minutes, never with a hand-typed window.
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = Path.home() / "Money" / "styl-work" / "BOARD" / "报错台账.txt"
REMOTE = '''
from arklog import since_minutes, RELAY_LOG
for l in since_minutes(RELAY_LOG, {minutes}):
    if " ERROR " in l[:40]:
        print("ERR|" + l[:200])
'''
LINE = re.compile(r"^ERR\|(\d\d-\d\d) (\d\d:\d\d:\d\d)")


def gaps(errors: list[str], ledger: str) -> list[str]:
    """The ERROR lines no ledger line covers (date and second on one line)."""
    rows = ledger.splitlines()
    out = []
    for e in errors:
        m = LINE.match(e)
        if m and not any(m[1] in r and m[2] in r for r in rows):
            out.append(e[4:])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    a = ap.parse_args()
    if not LEDGER.exists():
        print(f"ledger-gap: no ledger at {LEDGER}, nothing to check")
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(REMOTE.format(minutes=a.days * 1440))
    p = subprocess.run([str(ROOT / "scripts" / "mac" / "winrun.sh"), "--py", f.name],
                       capture_output=True, text=True, timeout=180)
    Path(f.name).unlink(missing_ok=True)
    errors = [l for l in p.stdout.splitlines() if l.startswith("ERR|")]
    if p.returncode != 0 and not errors:
        print(f"ledger-gap: could not read relay.log on the machine (rc {p.returncode})\n{p.stdout[-800:]}")
        return 2
    missing = gaps(errors, LEDGER.read_text(encoding="utf-8"))
    if not missing:
        print(f"ledger-gap: all {len(errors)} relay.log ERROR lines of the last {a.days} days are in the ledger")
        return 0
    print(f"ledger-gap: {len(missing)} relay.log ERROR line(s) with no ledger entry ({LEDGER}):")
    for m in missing:
        print("  " + m)
    return 1


if __name__ == "__main__":
    sys.exit(main())
