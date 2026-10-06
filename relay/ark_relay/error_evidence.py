"""Today's whole relay.log and AUTO-MAS app.log to COS, one object per day.

The 2026-10-06 fix bill (item L): 「报错保存证据包」 - when the relay pushes one
of its own errors, and again right before it powers the machine off, today's
full relay.log goes to COS as one object whose name carries the date, overwritten
the same day, so the log is readable with the machine off. A relay-error push
then ends with 「日志：<链接>，出事时刻 HH:MM」.

Nothing here re-invents the per-run bundle: that stays in evidence.py
(bundle_maaend / bundle_maa / bundle_okww). This is only the day object for the
relay's own faults, built from the same COS uploader and the same line-stamp
parser.

Rules:
* one object per day per log, the same key overwritten all day (PUT is replace);
* at most one upload a minute from the error path (THROTTLE_S) - the shutdown
  moment forces one last upload regardless;
* the whole-day log is capped at DAY_MAX_BYTES: a bigger day uploads its last
  DAY_MAX_BYTES and says so.
* an upload that fails never blocks the push or the shutdown: the caller gets
  `errors` and decides how to say it (errwatch notes it in the daily report,
  shutdown.py logs it as recovered).

Everything here reuses evidence.py: Cos (the XML-API PUT), _line_ts (the log
line stamp), PermanentUploadError.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ
from .evidence import Cos, PermanentUploadError, _line_ts

log = logging.getLogger("ark.evidence")

# The COS object folder: daily/relay-YYYY-MM-DD.log, daily/automas-app-YYYY-MM-DD.log.
DAILY_PREFIX = "daily"
# The whole-day log's cap. A day bigger than this uploads only its last part.
DAY_MAX_BYTES = 50 * 1024 * 1024
# At most one upload a minute from the error path (the object overwrites anyway).
THROTTLE_S = 60.0

# The last error-path upload attempt (epoch seconds, the caller's clock). Module
# state so errwatch and shutdown share one throttle; tests pass a fake clock.
_last_attempt = [0.0]


def _daily_uploader(cfg):
    """The COS store for the day objects, or None when COS is not configured."""
    if all(getattr(cfg, k, "") for k in ("cos_secret_id", "cos_secret_key", "cos_bucket", "cos_region")):
        return Cos(cfg.cos_secret_id, cfg.cos_secret_key, cfg.cos_bucket, cfg.cos_region,
                   prefix=DAILY_PREFIX)
    return None


def _day_tail(src: Path, day_start: datetime, day_end: datetime, max_bytes: int) -> tuple[bytes, bool]:
    """The lines of `src` stamped inside the day, capped to the last `max_bytes`.

    Returns (bytes, truncated). b"" when the file cannot be read or has no line
    in the day. The relay log stamps MM-DD without a year (the day's year is
    passed to _line_ts); AUTO-MAS's app.log stamps the full date.
    """
    try:
        size = src.stat().st_size
        with src.open("rb") as fh:
            # A day's lines live at the tail; reading twice the cap is enough to
            # catch a day boundary that lands inside the cap.
            if size > max_bytes * 2:
                fh.seek(size - max_bytes * 2)
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return b"", False
    year = day_start.year
    keep = False
    out: list[str] = []
    for line in raw.splitlines(keepends=True):
        ts = _line_ts(line, year)
        if ts is not None:
            keep = day_start.timestamp() <= ts <= day_end.timestamp()
        if keep:
            out.append(line)
    data = "".join(out).encode("utf-8")
    truncated = len(data) > max_bytes
    if truncated:
        data = data[-max_bytes:]
        nl = data.find(b"\n")
        if nl > 0:
            data = data[nl + 1:]   # drop the partial first line of the cut
    return data, truncated


def upload_daily_logs(cfg, *, force: bool = False, now: "datetime | None" = None,
                      clock=time.time, uploader=None) -> dict:
    """Upload today's relay.log and AUTO-MAS app.log to COS; the same keys are
    overwritten all day.

    Returns {"url", "at", "truncated", "errors", "skipped"}: `url` is the
    relay.log object's URL ("" when there is no relay log), `at` is the moment
    as HH:MM (server clock), `skipped` marks a throttle hit, `errors` the
    reasons an upload did not land. Never raises - an upload problem is reported
    in the result, not thrown at the caller.
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if not force and clock() - _last_attempt[0] < THROTTLE_S:
        return {"url": "", "at": now.strftime("%H:%M"), "truncated": False,
                "errors": [], "skipped": True}
    up = uploader if uploader is not None else _daily_uploader(cfg)
    result = {"url": "", "at": now.strftime("%H:%M"), "truncated": False,
              "errors": [], "skipped": False}
    if up is None:
        result["errors"].append("没有配置 COS（.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION）")
        _last_attempt[0] = clock()
        return result
    day = now.strftime("%Y-%m-%d")
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    srcs: list[tuple[str, Path]] = []
    if relay_log := os.environ.get("ARK_LOG_FILE", ""):
        srcs.append(("relay", Path(relay_log)))
    if automas := getattr(cfg, "automas_dir", None):
        srcs.append(("automas-app", Path(automas) / "debug" / "app.log"))
    tmp_dir = Path(cfg.state_dir) / "evidence" / "daily"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for kind, src in srcs:
        data, truncated = _day_tail(src, day_start, now, DAY_MAX_BYTES)
        if not data:
            continue
        tmp = tmp_dir / f"{kind}-{day}.log"
        try:
            tmp.write_bytes(data)
            got = up.upload(tmp)
        except PermanentUploadError as exc:
            result["errors"].append(f"{kind}: {exc}")
            break                      # the key/bucket refuses: the app.log would too
        except Exception as exc:       # noqa: BLE001 - a failed upload must not raise
            result["errors"].append(f"{kind}: {type(exc).__name__}: {exc}")
            continue
        if kind == "relay":
            result["url"] = got.get("url", "")
            result["truncated"] = truncated
    _last_attempt[0] = clock()
    return result
