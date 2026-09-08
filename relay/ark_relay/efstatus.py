"""Endfield official bulletins: is today a version-update day (= morning downtime)?

Only used to add one supporting line to the "cannot get into the game" verdict,
never as the primary evidence: measured 2026-09-02, the aggregate endpoint carries
no standalone maintenance notice, only the "version update notes" post that appears
after the servers are back up (startAt = the time service resumed). If nothing can
be fetched this returns an empty string and never affects the main flow.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime

from .config import SERVER_TZ

_URL = ("https://game-hub.hypergryph.com/bulletin/v2/aggregate"
        "?lang=zh-cn&platform=Windows&channel=1&type=0"
        "&code=endfield_5SD9TN&hideDetail=1")
_UA = "curl/8.7.1"


def _items(node, out: list) -> None:
    if isinstance(node, dict):
        if "title" in node:
            out.append(node)
        for v in node.values():
            _items(v, out)
    elif isinstance(node, list):
        for v in node:
            _items(v, out)


def update_hint(now: datetime | None = None, fetch=None) -> str:
    """Returns e.g. 「官方公告：今天 10:00「雪凇幽梦」版本更新」, or an empty string.

    fetch can be injected.
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        if fetch is None:
            req = urllib.request.Request(_URL, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
        else:
            data = fetch()
        items: list = []
        _items((data or {}).get("data") or {}, items)
        for it in items:
            head = str(it.get("header") or it.get("title") or "")
            if "版本更新说明" not in head:
                continue
            at = datetime.fromtimestamp(int(it.get("startAt") or 0), tz=SERVER_TZ)
            if at.date() != now.date():
                continue
            m = re.search(r"「([^」]+)」", head)
            name = f"「{m.group(1)}」" if m else ""
            return f"官方公告：今天 {at:%H:%M} {name}版本更新"
    except Exception:  # noqa: BLE001 - this is only supporting evidence
        return ""
    return ""
