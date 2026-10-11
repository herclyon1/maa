"""Replace a .bat on the gaming machine's desktop in place, keeping the old one as a backup.

Run on the machine through scripts/mac/place-skip-shutdown.py (which embeds the repo's
scripts/windows/skip-shutdown.bat and calls place()); nothing here is machine-specific,
so relay/tests/test_place_desktop_bat.py runs it against a temporary folder.

Rules:
  * the target must already exist: this replaces his file, it never adds one to his desktop;
  * the backup is <name>.<suffix> next to it, written once - a second run keeps the first
    backup (the original) instead of overwriting it with what the first run placed;
  * not while the switch's own window is open: cmd.exe reads a batch file line by line
    from byte offsets, so a window running the old file would carry on in the new one;
  * the new file goes in through a temp file + os.replace and is read back.
Prints one line per step (KEY=value) and returns 0 when the target holds the new bytes.
"""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

PWSH = r"C:\Program Files\PowerShell\7\pwsh.exe"


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def window_open(target: Path) -> "bool | None":
    """Whether a cmd.exe is running `target` (None: could not tell)."""
    ps = ("$n = @(Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" -EA SilentlyContinue | "
          "Where-Object { $_.CommandLine -like ('*' + $env:ARK_BAT_NAME + '*') }).Count; "
          "Write-Output ('OPEN=' + $n)")
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        r = subprocess.run([PWSH, "-NoProfile", "-EncodedCommand", enc], capture_output=True,
                           text=True, timeout=60, env={**os.environ, "ARK_BAT_NAME": target.name})
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        if line.startswith("OPEN="):
            return line[5:].strip() != "0"
    return None


def place(new: bytes, target: Path, suffix: str, check_only: bool = False,
          is_open=window_open) -> int:
    print(f"TARGET={target}")
    print(f"NEW_SHA1={_sha1(new)} ({len(new)} bytes)")
    if not target.is_file():
        print("RESULT=TARGET_MISSING (nothing placed: this only replaces an existing file)")
        return 2
    cur = target.read_bytes()
    print(f"CURRENT_SHA1={_sha1(cur)} ({len(cur)} bytes)")
    if cur == new:
        print("RESULT=ALREADY_CURRENT")
        return 0
    backup = target.with_name(target.name + suffix)
    if check_only:
        print(f"RESULT=WOULD_REPLACE (backup {'kept: ' if backup.exists() else 'to '}{backup.name})")
        return 0
    opened = is_open(target)
    if opened is not False:
        print("RESULT=WINDOW_OPEN (close the switch's window and run again)" if opened
              else "RESULT=UNKNOWN_WINDOW (could not tell whether the switch's window is open)")
        return 3
    if backup.exists():
        print(f"BACKUP=kept {backup.name} (sha1 {_sha1(backup.read_bytes())})")
    else:
        shutil.copy2(target, backup)
        if backup.read_bytes() != cur:
            print("RESULT=BACKUP_FAILED")
            return 4
        print(f"BACKUP=wrote {backup.name}")
    tmp = target.with_name(target.name + ".placing")
    try:
        tmp.write_bytes(new)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    got = target.read_bytes()
    if got != new:
        print(f"RESULT=READBACK_MISMATCH (sha1 {_sha1(got)})")
        return 5
    print("RESULT=PLACED")
    return 0
