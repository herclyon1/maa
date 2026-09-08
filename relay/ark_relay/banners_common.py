"""banners_common: the plumbing the three per-game banner modules share.

Split out of banners.py on 2026-09-08, moved verbatim. It exists for the same
reason preupdate_common.py does: banners.py is now the facade that imports the
three game modules, so anything those modules need has to live below them or the
import runs in a circle. What lands here is only what more than one game uses --
the logger, the two user agents, the Banner record, the three fetch helpers, and
the three cross-game judgements (newest_version / upcoming / debut_only). Every
public name here is re-exported from banners.py, so callers and tests still write
banners.xxx.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime


log = logging.getLogger("ark.banners")


# PRTS checks the User-Agent: curl's default UA gets through, a browser UA gets a
# 403 instead. Do not "optimise" this into a Chrome UA; everything 403s (measured
# twice, 2026-08-30).
_UA_PLAIN = "curl/8.7.1"
_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


@dataclass(frozen=True)
class Banner:
    """One banner. `chars` are the new characters debuting on it; there can be
    more than one.
    """

    game: str
    name: str
    chars: tuple[str, ...]
    start: datetime
    end: datetime



_VER = re.compile(r"(\d+)\.(\d+)")


def newest_version(entries: "list[tuple[str, str]]") -> str:
    """From [(title, body)], pick the body with the highest version number.

    As 3.6 nears its end the 3.7 version notes are posted first and both exist at
    once. This used to concatenate every 「版本内容说明」, so as soon as 3.7 came before
    3.6 the "whoever comes after the one currently running" criterion pointed at the
    wrong character. Only the highest version number is accepted, so 3.7 gets reported
    automatically the moment it is published, with no code change.
    """
    best, best_key = "", (-1, -1)
    for title, body in entries:
        m = _VER.search(title or "")
        key = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        if key >= best_key:
            best, best_key = body, key
    return best


def upcoming(debut: "list[tuple[str, str]]", live: "set[str]"
             ) -> "list[tuple[str, str]]":
    """The bulletin lists the version's banners in order; only the ones after the
    banner currently running have yet to open.

    "Not in live" alone will not do -- the first half of this version has already
    finished, so that character is not in live either, and by that criterion the
    **previous** banner would get reported as the next one.
    """
    idx = max((i for i, (w, _) in enumerate(debut) if w in live), default=None)
    return debut[idx + 1:] if idx is not None else []


# ── Deciding what counts as a debut ────────────────────────────
_RERUN = ("复刻", "Rerun", "rerun")
# Banners that by definition cannot debut a character, excluded by name.
# The first version on 2026-08-30 did not exclude them and judged 「联合行动23」 a debut
# (诺威尔 and 杏仁 are both old operators).
_NOT_DEBUT = ("联合行动", "中坚寻访", "中坚甄选", "概率提升")


def debut_only(banners: list[Banner]) -> list[Banner]:
    """Keep debuts only.

    What is passed in must be the **complete history, sorted by start time**.
    """
    seen: set[str] = set()
    out: list[Banner] = []
    for b in banners:
        skip = any(k in b.name for k in _RERUN + _NOT_DEBUT)
        fresh = tuple(c for c in b.chars if c not in seen)
        seen.update(b.chars)          # record rotating-banner characters too; they are not new
        if skip or not fresh:
            continue
        out.append(Banner(b.game, b.name, fresh, b.start, b.end))
    return out


# Measured on the game machine 2026-08-31: raw.githubusercontent.com is reachable,
# but takes **33 seconds** -- past the timeout it simply fails, which is why the
# Arknights and Endfield previews came and went. The same file over jsDelivr takes
# only 2.8-4.6 seconds. So the mirrors are ordered by measured speed, with raw last as
# a fallback. gitmirror and ghfast.top were completely unreachable at the time; do not
# add them back.
def gh_raw(owner: str, repo: str, branch: str, path: str) -> list[str]:
    """Several routes to the same GitHub file, ordered by speed measured on the
    game machine.
    """
    return [
        f"https://fastly.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}",
        f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}",
        f"https://gh-proxy.com/https://raw.githubusercontent.com/"
        f"{owner}/{repo}/{branch}/{path}",
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}",
    ]


def _json(url: str, ua: str, data: "bytes | None" = None,
          headers: "dict | None" = None, timeout: int = 20) -> dict:
    h = {"User-Agent": ua}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _text(url: str, ua: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _first(urls: list[str], ua: str, timeout: int = 12) -> str:
    """Try each in turn and return the first that works.

    Only when all of them fail is the last exception raised.
    """
    err: Exception = RuntimeError("没有可用地址")
    for u in urls:
        try:
            return _text(u, ua, timeout)
        except Exception as e:  # noqa: BLE001
            log.debug("镜像取不到 %s：%s", u, e)
            err = e
    raise err
