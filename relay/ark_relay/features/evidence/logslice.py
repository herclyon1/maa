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

# Two more stamps MaaEnd's debug/ logs use, read only when a caller asks for
# them (`more=True`, the MaaEnd bundle): mxu-tauri.log `[YYYY-MM-DD][HH:MM:SS]`
# and go-service.log's JSON lines `{..."time":"YYYY-MM-DDTHH:MM:SS+08:00"...}`.
# Local time like the others: the machine's clock is +08:00.
_MORE_TS = re.compile(r'^\[(\d{4})-(\d\d)-(\d\d)\]\[(\d\d):(\d\d):(\d\d)\]'
                      r'|^\{.*?"time":"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)')


def _line_ts(line: str, year: int, more: bool = False) -> "float | None":
    m = _CTX_TS.match(line)
    if not m and more and (mm := _MORE_TS.match(line)):
        g = mm.groups()
        try:
            return datetime(*(int(x) for x in (g[:6] if g[0] else g[6:]))).timestamp()
        except ValueError:
            return None
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


def slice_log(src: Path, window: "tuple[float, float]", dst: Path, tail_bytes: "int | None" = 50_000_000,
              *, more: bool = False) -> "Path | None":
    """Copy the lines of `src` stamped inside `window` into `dst`; continuation
    lines (tracebacks) follow their stamped line. The relay log stamps MM-DD
    without a year, AUTO-MAS's app.log stamps the full date. None when nothing
    fell in the window or the file cannot be read.

    `tail_bytes=None` reads the whole file line by line (a MaaEnd log of 60 MB
    is not held in memory) and does not reach into `<src>.1`; `more` also reads
    the MaaEnd stamps in _MORE_TS."""
    year = datetime.fromtimestamp(window[0]).year
    keep = False
    n = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if tail_bytes is None:
            lines = _file_lines(src)
        else:
            from ark_relay.core.logfile import tail_bytes as _tail  # noqa: PLC0415
            # Reaches into <src>.1 when a rotation moved part of the window there (logfile.py).
            lines = iter(_tail(src, tail_bytes)[0].decode("utf-8", errors="replace").splitlines())
        with dst.open("w", encoding="utf-8") as out:
            for line in lines:
                ts = _line_ts(line, year, more)
                if ts is not None:
                    keep = window[0] <= ts <= window[1]
                if keep:
                    out.write(line + "\n")
                    n += 1
    except OSError:
        dst.unlink(missing_ok=True)
        return None
    if not n:
        dst.unlink(missing_ok=True)
        return None
    return dst


def _file_lines(src: Path):
    with src.open("rb") as f:
        for raw in f:
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")


def first_ts(src: Path, more: bool = False, head_bytes: int = 65536) -> "float | None":
    """The stamp of the first stamped line in the first `head_bytes` of `src`
    (the year of a yearless stamp is taken from the file's mtime); None when
    none is readable there."""
    try:
        with src.open("rb") as f:
            head = f.read(head_bytes)
        year = datetime.fromtimestamp(src.stat().st_mtime).year
    except OSError:
        return None
    for line in head.decode("utf-8", errors="replace").splitlines():
        if (ts := _line_ts(line, year, more)) is not None:
            return ts
    return None


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
