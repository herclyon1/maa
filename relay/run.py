#!/usr/bin/env python3
"""Launcher for environments whose sys.path cannot be extended.

AUTO-MAS ships an embedded Python whose python312._pth pins sys.path; the "."
entry there means the interpreter's own directory, not the working directory,
so `python -m ark_relay` cannot find the package. Rather than modify someone
else's runtime, this launcher puts its own directory on the path.

    python.exe "C:\\Program Files\\ArkRelay\\versions\\<current.txt>\\run.py" check

On the installed relay this file sits in a version folder and the data (.env, state,
relay.log) in C:\\ProgramData\\ark-relay (relay/pkg_layout.py), so it changes into the
data folder; elsewhere (the old relay, a checkout) code and data share this folder.
"""
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pkg_layout  # noqa: E402  - next to this file

# so the default --env ./.env (and a relative state dir) resolves in the data folder
os.chdir(pkg_layout.data_root() if pkg_layout.app_root(Path(HERE)) else HERE)

from ark_relay.__main__ import main  # noqa: E402  - must follow the path fix

if __name__ == "__main__":
    raise SystemExit(main())
