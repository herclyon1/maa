#!/usr/bin/env python3
"""Put the repo's desktop switch (scripts/windows/skip-shutdown.bat) on the gaming machine.

    scripts/mac/place-skip-shutdown.py            # back up his 中继关机开关.bat, replace it
    scripts/mac/place-skip-shutdown.py --check    # only say what it would do

His desktop's 中继关机开关.bat is replaced in place (same name, same folder); the file it
replaces is kept once as 中继关机开关.bat.bak-1011 next to it. Decided by the acceptance
session (BOARD/DECISIONS.md D-1011-工具最新): the 08-31 copy on his desktop writes
state\\skip-next-shutdown.flag, which the relay only takes in at its next start, so a press
while it runs does nothing until then. The logic is scripts/mac/lib/place_desktop_bat.py;
this embeds the .bat and sends both through winrun.sh --py.
"""
from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BAT = HERE.parent / "windows" / "skip-shutdown.bat"
TARGET = r"C:\Users\Administrator\Desktop\中继关机开关.bat"
SUFFIX = ".bak-1011"

STUB = '''import base64
from pathlib import Path
from place_desktop_bat import place
raise SystemExit(place(base64.b64decode({b64!r}), Path({target!r}), {suffix!r}, check_only={check!r}))
'''


def main(argv: list[str]) -> int:
    check = "--check" in argv
    new = BAT.read_bytes()
    stub = STUB.format(b64=base64.b64encode(new).decode(), target=TARGET, suffix=SUFFIX, check=check)
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "place_skip_shutdown_remote.py"
        script.write_text(stub, encoding="utf-8")
        return subprocess.run([str(HERE / "winrun.sh"), "--py", str(script)]).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
