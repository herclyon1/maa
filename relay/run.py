#!/usr/bin/env python3
"""Launcher for environments whose sys.path cannot be extended.

AUTO-MAS ships an embedded Python whose python312._pth pins sys.path; the "."
entry there means the interpreter's own directory, not the working directory,
so `python -m ark_relay` cannot find the package. Rather than modify someone
else's runtime, this launcher puts its own directory on the path.

    python.exe C:\\ProgramData\\ark-relay\\run.py check
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)  # so the default --env ./.env resolves next to this file

from ark_relay.__main__ import main  # noqa: E402  - must follow the path fix

if __name__ == "__main__":
    raise SystemExit(main())
