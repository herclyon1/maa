"""deploy-pkg.sh under macOS /bin/bash 3.2, a UTF-8 locale and set -u.

bash 3.2 reads the bytes of a full-width character right after `$NAME` (for example
`$PREV（`) as part of the variable name, so under set -u the line dies with
"PREV\xef: unbound variable" (exit 127). Until 2026-10-13 seven lines of
scripts/mac/lib/deploy-pkg.sh were written that way, one of them on the way back
after a failed deploy. Every variable touching a non-ASCII character is ${NAME} now.

No deploy runs here: the way-back block is run in /bin/bash with ssh, scp and the
script's helpers (pkg_py, pkg_py_at, pkg_restart) stood in, and every other echo line
that names a variable next to a non-ASCII character is run on its own.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SH = (ROOT / "scripts" / "mac" / "lib" / "deploy-pkg.sh").read_text(encoding="utf-8")
BASH = "/bin/bash"
ENV = {**os.environ, "LC_ALL": "en_US.UTF-8"}

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def bash(script: str):
    r = subprocess.run([BASH, "-c", script], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV)
    return r.returncode, r.stdout + r.stderr


if not Path(BASH).exists():
    print("  - no /bin/bash here, nothing to check")
    sys.exit(0)

print("[this bash is the one that trips]")
rc, out = bash('set -u; PREV=41; echo "a $PREV（b"')
print(f"    {Path(BASH)} on $PREV（: exit {rc}")

print("[no $NAME right before a non-ASCII character]")
bare = [ln.strip() for ln in SH.splitlines() if re.search(r"\$[A-Za-z_][A-Za-z_0-9]*[^\x00-\x7F]", ln)]
check("lines with a bare $NAME before a non-ASCII character", bare, [])

STUBS = r"""
set -euo pipefail
SSH_OPTS=(-o ConnectTimeout=15); USER_AT=Administrator@host
APP_WIN='C:\Program Files\ArkRelay'; PKG_DEPLOY='C:\x\ark-pkg-deploy.py'; WATCH_PY='C:\x\w.py'
PREV=41; NEW=42; VER=20261013000000; T0='2026-10-13 11:00:00'; INC='C:\x\.incoming'
APPFILES_WHY=boom; RUNTIME_WHY=boom; MC_STATE='C:\Program Data\ark'; RUNTIME_PY_EXE='C:\x\python.exe'
FAILED_WHY="上线后没稳住：test"; RUNTIME_TOUCHED=0; APPFILES_SWAPPED=0
STATE=Stopped; CURRENT=42; WATCH_OUT=$(mktemp)
ssh() { :; }
scp() { :; }
pkg_py() { case "$*" in *" watch "*) echo "WATCH_OK" ;; *" back "*) echo "BACK to 41" ;; esac; }
pkg_py_at() { :; }
pkg_restart() { STATE=Running; CURRENT=$PREV; }
"""

print("[the way back runs to its end]")
start = SH.find('if [ -n "$FAILED_WHY" ]; then\n  echo "❌❌ $FAILED_WHY"')
end = SH.find("  exit 13\nfi\n", start)
check("way-back block found", start >= 0 and end > start, True)
block = SH[start:end + len("  exit 13\nfi\n")]
rc, out = bash(STUBS + block)
check("way back exits 12 (previous version holds)", rc, 12)
check("way back names the previous version", "自动退回上一版 41（" in out, True)
check("way back reports it held", "已自动退回上一版 41，" in out, True)

print("[every other echo naming a variable next to a non-ASCII character]")
lines = [ln.strip() for ln in SH.splitlines()
         if ln.strip().startswith("echo ") and re.search(r"\$\{?[A-Za-z_][A-Za-z_0-9]*\}?[^\x00-\x7F]", ln)]
check("found the echo lines", len(lines) >= 7, True)
for ln in lines:
    rc, out = bash(STUBS + ln + "\n")
    check(f"exit 0: {ln[:60]}", rc, 0)

print("FAIL" if fails else "OK")
sys.exit(1 if fails else 0)
