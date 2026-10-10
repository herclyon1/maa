"""The relay's relay.log and AUTO-MAS's debug/app.log, cut to an evidence
window, so a bundle carries what both programs wrote around the run.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


# A line stamp: `[YYYY-MM-DD HH:MM:SS` / `YYYY-MM-DDTHH:MM:SS` (AUTO-MAS) or
# `MM-DD HH:MM:SS` (relay.log, no year).
_CTX_TS = re.compile(r"^(?:\[)?(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)"
                     r"|^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)")


def _line_ts(line: str, year: int) -> "float | None":
    m = _CTX_TS.match(line)
    if not m:
        return None
    if m.group(1):
        y, mo, d, h, mi, sec = (int(x) for x in m.groups()[:6])
    else:
        y = year
        mo, d, h, mi, sec = (int(x) for x in m.groups()[6:])
    try:
        return datetime(y, mo, d, h, mi, sec).timestamp()
    except ValueError:
        return None


def slice_log(src: Path, window: "tuple[float, float]", dst: Path, tail_bytes: int = 50_000_000) -> "Path | None":
    """Copy the lines of `src` stamped inside `window` into `dst`; continuation
    lines (tracebacks) follow their stamped line. The relay log stamps MM-DD
    without a year, AUTO-MAS's app.log stamps the full date. None when nothing
    fell in the window or the file cannot be read."""
    from ark_relay.core.logfile import tail_bytes as _tail  # noqa: PLC0415
    try:
        # Reaches into <src>.1 when a rotation moved part of the window there (logfile.py).
        raw = _tail(src, tail_bytes)[0].decode("utf-8", errors="replace")
    except OSError:
        return None
    year = datetime.fromtimestamp(window[0]).year
    keep = False
    out: list[str] = []
    for line in raw.splitlines():
        ts = _line_ts(line, year)
        if ts is not None:
            keep = window[0] <= ts <= window[1]
        if keep:
            out.append(line)
    if not out:
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    return dst


def context_files(cfg, window: "tuple[float, float]", out_dir: Path, *,
                  relay_until: "float | None" = None) -> list[Path]:
    """The relay's relay.log and AUTO-MAS's debug/app.log, cut to the window.

    `relay_until` stretches the relay.log slice to that moment. The relay
    handles a run only once AUTO-MAS writes its record at the end of the whole
    script, so what the relay did about the run lies after the run's own
    window. The handler passes the moment it cuts; a hand-run export leaves it
    out.
    """
    import os  # noqa: PLC0415
    out: list[Path] = []
    relay_log = os.environ.get("ARK_LOG_FILE", "")
    if relay_log:
        rwin = (window[0], max(window[1], relay_until)) if relay_until else window
        if p := slice_log(Path(relay_log), rwin, out_dir / "relay.log"):
            out.append(p)
    automas = getattr(cfg, "automas_dir", None)
    if automas:
        if p := slice_log(Path(automas) / "debug" / "app.log", window, out_dir / "automas-app.log"):
            out.append(p)
    return out
