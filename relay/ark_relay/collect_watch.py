"""Narrow the master's gathering routes the moment a route fails - while the run
is still going, before AUTO-MAS starts its retry.

Why the record-time narrowing (handle.py, 2026-09-12) never once took effect:
AUTO-MAS writes every attempt's .json/.log of one script task only when the
whole task is over. On 2026-09-14 four MaaEnd attempts were all stamped
11:49:18; the relay narrowed the master at 11:54:56 and put it back the same
second, because the retry's own record was already sitting next to it. By the
time a record can be read, the retry has walked all 17 routes again.

What *is* live is MaaFW's own log, `<maaend_dir>/debug/maafw.log`:

    [msg=Tasker.Task.Starting]  {"entry":"AutoCollectSchedule", ...}   attempt begins
    [msg=Node.Action.Starting]  {"name":"AutoCollectRoute10Failed", ...} a route that did not make it
    [msg=Tasker.Task.Failed]    {"entry":"AutoCollectSchedule", ...}   attempt ends failed

On 09-14 the `Route10Failed` node was logged at 11:20:22 and AUTO-MAS launched
the retry at 11:21:43. AUTO-MAS copies the master into MaaEnd's config dir on
every attempt (`AutoProxy.set_maaend`, inside the retry loop), so a master
narrowed in that window makes the retry walk only the failed routes.

The lists go back at the retry's own `Tasker.Task.Starting` (its config was
copied before MaaEnd was launched, so the master is free again), and - as
before - when the MaaEnd record lands, at the shutdown decision and at boot.

No timer: the thread sleeps on a directory-change notification for the debug
dir (watch.py) and reads only the bytes appended since its last look. While
nothing runs, nothing writes there and the thread does not wake.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ark.collect_watch")

ENTRY = "AutoCollectSchedule"
_TASK = re.compile(r"\[msg=Tasker\.Task\.(Starting|Completed|Failed)\].*?\"entry\":\"" + ENTRY + r"\"")
_ROUTE_FAILED = re.compile(r"\[msg=Node\.Action\.Starting\].*?\"name\":\"AutoCollect((?:Common)?Route\d+)Failed\"")
_STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
# Only the dispatcher's own line; the agent client echoes every event once more.
_NOTIFY = "EventDispatcher::notify"
_PREFILTER = "AutoCollect"
COALESCE_SECONDS = 2.0


class Watcher:
    """Turns maafw.log lines into master narrowing / restoring. File-free for tests: `feed()`."""

    def __init__(self, cfg, notifier):
        self.cfg, self.notifier = cfg, notifier
        self.failed: list[str] = []      # caseNames of this attempt, e.g. Route10
        self.narrowed = False
        self._offset = 0
        self._tail = ""

    # ---------------------------------------------------------------- parsing

    def feed(self, text: str) -> list[str]:
        """Consume log text (any number of lines). Returns the notes it logged."""
        notes: list[str] = []
        for line in text.splitlines():
            if _NOTIFY not in line or _PREFILTER not in line:
                continue
            if m := _ROUTE_FAILED.search(line):
                rid = m.group(1)
                if rid not in self.failed:
                    self.failed.append(rid)
                    notes.extend(self._narrow(line))
            elif m := _TASK.search(line):
                notes.extend(self._task_event(m.group(1), line))
        return notes

    def _task_event(self, kind: str, line: str) -> list[str]:
        notes: list[str] = []
        if kind == "Starting":
            # A new attempt. If the last one left the master narrowed, this is the
            # retry that read it - put the original back now.
            if self.narrowed:
                notes.extend(self._restore())
            self.failed = []
        elif kind == "Failed":
            when = (_STAMP.match(line) or [None, "?"])[1]
            log.info("自动采集这一趟失败（%s），没走通：%s", when,
                     "、".join(self.failed) if self.failed else "日志里没有点名哪条路线")
        return notes

    # ---------------------------------------------------------------- effects

    def _narrow(self, line: str) -> list[str]:
        from . import collect_retry  # noqa: PLC0415
        from .config import SERVER_TZ  # noqa: PLC0415
        when = (_STAMP.match(line) or [None, ""])[1]
        try:
            note = collect_retry.narrow_master(self.cfg, list(self.failed), f"{when} 自动采集失败",
                                               datetime.now(tz=SERVER_TZ))
        except Exception:
            log.exception("母本路线收窄出错，重跑会走全部路线")
            return []
        if not note:
            return []
        self.narrowed = True
        zh = collect_retry._locale(Path(self.cfg.maaend_dir)) if self.cfg.maaend_dir else {}
        labels = [collect_retry.route_label(f"AutoCollect{r}", zh) for r in self.failed]
        # Log only. The daily report already names the routes that failed and
        # says the retry was narrowed; a separate push for it was noise (the
        # user asked why it was not simply part of the daily report, 2026-09-14).
        log.info("🔁 %s（%s）", note, "、".join(labels))
        return [note]

    def _restore(self) -> list[str]:
        from . import collect_retry  # noqa: PLC0415
        self.narrowed = False
        try:
            back = collect_retry.restore_master(self.cfg)
        except Exception:
            log.exception("母本路线改回出错")
            return []
        if back:
            log.info("🔁 重跑已经开始，%s", back)
            return [back]
        return []

    # ---------------------------------------------------------------- the file

    def log_path(self) -> Path | None:
        return Path(self.cfg.maaend_dir) / "debug" / "maafw.log" if self.cfg.maaend_dir else None

    def poll(self) -> list[str]:
        """Read whatever maafw.log gained since last time; follow a rotation."""
        p = self.log_path()
        if p is None:
            return []
        try:
            size = p.stat().st_size
        except OSError:
            return []
        notes: list[str] = []
        if size < self._offset:
            # MaaFW renamed the file to maafw.bak.<stamp>.log and started a new one;
            # the last lines of the old one (the Failed nodes come right before
            # MaaEnd exits) are still unread there.
            baks = sorted(p.parent.glob("maafw.bak.*.log"), key=lambda q: q.stat().st_mtime)
            if baks:
                notes.extend(self._read_from(baks[-1], self._offset))
            self._offset, self._tail = 0, ""
        notes.extend(self._read_from(p, self._offset, track=True))
        return notes

    def _read_from(self, p: Path, offset: int, *, track: bool = False) -> list[str]:
        try:
            with p.open("rb") as fh:
                fh.seek(offset)
                data = fh.read()
        except OSError:
            return []
        if not data:
            return []
        text = self._tail + data.decode("utf-8", "replace")
        text, _, rest = text.rpartition("\n")
        if track:
            self._offset = offset + len(data)
            self._tail = rest
        return self.feed(text)


def start(cfg, notifier) -> bool:
    """Arm the watcher thread. False (and a log line) when there is nothing to watch."""
    from . import watch  # noqa: PLC0415
    if not cfg.maaend_dir:
        log.info("没配 MaaEnd 目录，不盯采集日志")
        return False
    debug = Path(cfg.maaend_dir) / "debug"
    if not debug.is_dir():
        log.info("MaaEnd 的 debug 目录不存在（%s），不盯采集日志", debug)
        return False
    w = Watcher(cfg, notifier)
    try:
        w._offset = w.log_path().stat().st_size   # start from now, not from the last run
    except OSError:
        pass
    wake = threading.Event()
    if not watch.start(debug, wake):
        log.warning("挂不上 MaaEnd debug 目录的变更通知，采集路线收窄这一步不工作")
        return False

    def run() -> None:
        while True:
            wake.wait()
            wake.clear()
            time.sleep(COALESCE_SECONDS)     # MaaFW writes thousands of lines a second
            try:
                w.poll()
            except Exception:
                log.exception("盯采集日志出错，继续")

    threading.Thread(target=run, name="collect-watch", daemon=True).start()
    log.info("已挂上 MaaEnd 日志监听：采集路线一失败就收窄母本，重跑一开始就改回")
    return True
