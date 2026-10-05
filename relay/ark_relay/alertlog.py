"""A copy of every group alarm, one JSON line each, in the COS object alerts/<Beijing YYYYMMDD>.jsonl.

The user, 2026-10-06 00:23: 「中继每往群里发一条报警，就同时抄一份给 Mac，Mac 收到
后记到一个地方…就是他发给群里的时候再发给我的电脑不就完了。」 The Mac reads the
bucket; the machine appends. Private object (no public-read ACL): only key holders
read it.

Runs on its own thread after the push, so a slow or dead COS never delays the
alarm. A failure is one WARNING on this module's logger, which errwatch ignores
(QUIET_LOGGERS) - a COS outage must not ring the group about itself.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

log = logging.getLogger("ark.alertlog")
BEIJING = timezone(timedelta(hours=8))
THREAD = "alarm-copy"
_lock = threading.Lock()     # one read-append-write at a time, or two alarms lose one line
_RUN = re.compile(r"\d{4}-\d{2}-\d{2}[/_][A-Za-z]+[/_][\w-]+")


def key_for(now: datetime) -> str:
    return f"alerts/{now.astimezone(BEIJING).strftime('%Y%m%d')}.jsonl"


def entry(title: str, text: str, version: str, game: str = "", evidence_run: str = "",
          now: "datetime | None" = None) -> dict:
    now = now or datetime.now(BEIJING)
    if not game:
        from .errwatch import game_of  # noqa: PLC0415
        game = game_of(title, text)
    if not evidence_run:
        m = _RUN.search(f"{title}\n{text}")
        evidence_run = m.group(0) if m else ""
    return {"ts": now.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S"), "game": game, "title": title,
            "text": text, "version": str(version or ""), "evidence_run": evidence_run}


def cos_get(cos, key: str, timeout: float = 20) -> bytes:
    """The object's bytes; b"" when it does not exist yet (404)."""
    req = urllib.request.Request(f"https://{cos.host}/" + urllib.parse.quote(key, safe="/"),
                                 headers={"Authorization": cos.authorization("GET", key)})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return b""
        raise


def cos_put(cos, key: str, data: bytes, timeout: float = 20) -> None:
    req = urllib.request.Request(f"https://{cos.host}/" + urllib.parse.quote(key, safe="/"),
                                 data=data, method="PUT",
                                 headers={"Authorization": cos.authorization("PUT", key),
                                          "Content-Type": "application/x-ndjson; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def append(cos, row: dict, get=None, put=None) -> None:
    """Read the day's object, add one line, write it back. Raises on a COS failure."""
    get, put = get or cos_get, put or cos_put
    key = key_for(datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING))
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        old = get(cos, key)
        if old and not old.endswith(b"\n"):
            old += b"\n"
        put(cos, key, old + line.encode("utf-8"))


def copy(cos, title: str, text: str, version: str, get=None, put=None) -> "threading.Thread | None":
    """Start the copy on its own thread; None when this machine has no COS."""
    if cos is None:
        return None
    row = entry(title, text, version)

    def run() -> None:
        t0 = time.monotonic()
        try:
            append(cos, row, get, put)
        except Exception as exc:  # noqa: BLE001 - a copy that failed is said once, never raised
            log.warning("群报警抄送 COS 没成（%.0f 秒）：%s ｜ 标题：%s", time.monotonic() - t0,
                        exc, title)

    t = threading.Thread(target=run, name=f"{THREAD}-{int(time.time())}", daemon=True)
    t.start()
    return t
