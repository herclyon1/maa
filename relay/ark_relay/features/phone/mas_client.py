"""The AUTO-MAS backend API client used by commands.py and redbutton.py.

commands.py re-exports `_mas` and `mas_post`; tests that fake the backend replace
`commands._mas` (for the command gates) or `redbutton._mas` (for the red button).
"""
from __future__ import annotations

import json
import urllib.request


# The address has exactly one source; see config.mas_base()
def _mas_api() -> str:
    from ark_relay.core.config import mas_base  # noqa: PLC0415 - avoids an import cycle
    return mas_base()


def mas_post(path: str, body: "dict | None" = None, timeout: int = 20) -> dict:
    """POST `body` as JSON to the AUTO-MAS backend and return the decoded JSON reply.

    Every AUTO-MAS endpoint is POST, the read-only ones included (GET answers
    Method Not Allowed). snapshot.py reads through this too.
    """
    req = urllib.request.Request(
        _mas_api() + path, data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _mas(path: str, body: "dict | None" = None, timeout: int = 20) -> dict:
    """The AUTO-MAS backend, for every command in commands.py and redbutton.py (see mas_post).

    Commands go through the API rather than editing files: while the backend is
    running it overwrites the file from its in-memory copy, so a value written
    straight into the file is lost. Each of those modules binds this name itself;
    tests replace `commands._mas` or `redbutton._mas` to fake the backend.
    """
    return mas_post(path, body, timeout)
