"""Which ark_relay a tool on the gaming machine imports: the one the relay runs.

The installed relay (packaging/ark-relay.iss) runs {app}\\versions\\<current.txt>\\
(relay/pkg_layout.py); C:\\ProgramData\\ark-relay holds only its data (.env, state\\,
relay.log). The old relay's ark_relay folder that lay there (a tool importing it judged
the machine by old code, and one applying OK-WW patches with it wrote old patches over
newer fixes) went to C:\\ProgramData\\ark-relay-retired-1011 on 2026-10-11 22:33
(scripts/windows/retire_legacy.py, docs/TOOLING.md). Every tool that imports ark_relay
on the machine takes the folder from here.

    from relay_code import use_relay_code   # its own line at column 0: winrun.sh --py
    CODE = use_relay_code()                 # ships the scripts/mac/lib modules it sees
                                            # imported that way next to the script

A machine without the installed relay: the old folder is still put on sys.path, with one
line on stderr saying so; since the old code was moved out, the import then fails (the
tool stops with an import error rather than running old code).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The installer's default folder; ARK_APP for an install put elsewhere (scripts/mac/estop.sh
# reads the folder off the logon task for the same reason).
APP = Path(os.environ.get("ARK_APP") or r"C:\Program Files\ArkRelay")
# Data (.env, state, relay.log) stays here for every version (relay/pkg_layout.py data_root).
DATA = Path(os.environ.get("ARK_HOME") or r"C:\ProgramData\ark-relay")
# The old relay kept its code next to its data (moved out 2026-10-11, see the docstring).
LEGACY_CODE = Path(r"C:\ProgramData\ark-relay")


def code_root(app: Path = APP, legacy: Path = LEGACY_CODE) -> "tuple[Path, bool]":
    """(the folder holding ark_relay, True when it is the installed relay's version folder)."""
    try:
        name = (app / "current.txt").read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        name = ""
    if name:
        folder = app / "versions" / name
        if (folder / "ark_relay" / "__init__.py").is_file():
            return folder, True
    return legacy, False


def use_relay_code(app: Path = APP, legacy: Path = LEGACY_CODE) -> Path:
    """Put the relay's code folder first on sys.path and return it."""
    folder, installed = code_root(app, legacy)
    if not installed:
        print(f"[relay_code] no installed relay at {app} (current.txt); "
              f"importing the old code in {folder}", file=sys.stderr, flush=True)
    sys.path.insert(0, str(folder))
    return folder
