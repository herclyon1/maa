"""relay.log: rotated by size, and read across the rotation.

Until 2026-10-07 relay.log was a plain FileHandler that only ever grew: the
copy fetched on 2026-10-06 held every line since 08-15, 2.38 MB over 52 days.
That is slow (about 46 KB a day; the busiest day in it, 10-05, wrote 90 KB),
but it never stops, and one error loop that logs every second would fill the
disk at a rate nothing watches.

Sizes. MAX_BYTES = 16 MB is about a year of ordinary days at that rate and
still 180 of the busiest one, so a rotation is a rare event - the forensics in
this codebase read months of relay.log at a time (selfupdate.py quotes 521
rounds from 08-16 to 09-18). BACKUPS = 3 bounds the whole thing at 64 MB.

Readers. Five places read relay.log by seeking to its tail: the daily upload
(error_evidence._day_tail), the evidence slice (evidence.slice_log), the
machine checks (machinechecks/system.read_tail, runs._relay_today) and the
daily self-check (selfcheck.daily_section). Right after a rotation the tail
they want is partly in relay.log.1 - the boot checks' "previous session" would
be cut in two - so they all read through tail_bytes, which reaches into
relay.log.1 when the current file is shorter than what was asked for. One
older file is enough: each holds MAX_BYTES, far more than any reader's window.

Windows. A rotation renames relay.log, and Windows refuses to rename a file
another handle holds open without FILE_SHARE_DELETE - Python's own open(),
PowerShell's Get-Content, scp. RotatingFileHandler then drops the record that
triggered the rotation, and every record after it (each one retries the
rename and fails again) until the other handle closes. RelayLogHandler keeps
writing to the current file instead, says so in the file, and tries again
RETRY_SECONDS later. The service is the only writer: ARK_LOG_FILE is set inside
its own process (boot_stages._stage_bootstrap), and the command-line entry
(__main__.main) sets up logging before it reads .env, so a hand-run command
never opens relay.log for writing.
"""
from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
BACKUPS = 3
RETRY_SECONDS = 300.0


class RelayLogHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that never loses a record to a failed rotation (see the module docstring)."""

    def __init__(self, filename, max_bytes: int = MAX_BYTES, backups: int = BACKUPS) -> None:
        super().__init__(filename, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        self._retry_at = 0.0

    def shouldRollover(self, record) -> bool:  # noqa: N802 - logging's name
        if self._retry_at and time.monotonic() < self._retry_at:
            return False
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:  # noqa: N802 - logging's name
        try:
            super().doRollover()
        except OSError as exc:
            self._retry_at = time.monotonic() + RETRY_SECONDS
            if self.stream is None:
                self.stream = self._open()
            # Written straight into the file: this runs inside the handler, and
            # going through logging again would re-enter it. Same shape as a
            # formatted line (__main__._setup_logging), so the log readers see it.
            self.stream.write(f"{time.strftime('%m-%d %H:%M:%S')} WARNING ark.logfile  "
                              f"relay.log 轮转没成（{exc}），接着写在原文件里，"
                              f"{RETRY_SECONDS / 60:.0f} 分钟后再试\n")
            self.stream.flush()
        else:
            self._retry_at = 0.0


def tail_bytes(path, nbytes: int) -> "tuple[bytes, bool]":
    """The last `nbytes` of the log at `path`, reaching into `<path>.1` when the
    current file holds fewer (it was rotated recently).

    Returns (data, cut): `cut` is True when older bytes exist before `data`, so
    its first line may be partial. Raises OSError when the current file cannot
    be read, as open() would; a missing or unreadable `<path>.1` is no older part.
    """
    p = Path(path)
    with p.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        start = max(0, size - nbytes)
        fh.seek(start)
        data = fh.read()
    if start > 0:
        return data, True
    need = nbytes - len(data)
    try:
        with Path(f"{p}.1").open("rb") as fh:
            fh.seek(0, 2)
            osize = fh.tell()
            ostart = max(0, osize - need)
            fh.seek(ostart)
            older = fh.read()
    except OSError:
        return data, False
    if older and not older.endswith(b"\n"):
        older += b"\n"
    return older + data, ostart > 0
