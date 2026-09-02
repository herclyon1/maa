"""终末地官方公告：今天是不是版本更新日（= 早上停服维护）。

只用来给「进不了游戏」的判定加一句依据，不做主判据：2026-09-02 实测，
聚合口里没有单独的维护公告，只有开服后才出现的「版本更新说明」
（startAt = 开服时刻）。取不到就返回空串，绝不影响主流程。
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
    """「官方公告：今天 10:00「雪凇幽梦」版本更新」或空串。fetch 可注入。"""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        if fetch is None:
            req = urllib.request.Request(_URL, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=8) as r:   # noqa: S310
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
    except Exception:  # noqa: BLE001 - 只是加一句依据
        return ""
    return ""
