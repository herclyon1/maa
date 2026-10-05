"""Watch MaaFW's live log for MaaEnd: which gathering routes failed, the task
pictures, and the MaaEnd hang watchdog.

MaaFW's own log, `<maaend_dir>/debug/maafw.log`, is live (AUTO-MAS writes a
script's .json/.log records only when all its attempts are over):

    [msg=Tasker.Task.Starting]  {"entry":"AutoCollectSchedule", ...}   attempt begins
    [msg=Node.Action.Starting]  {"name":"AutoCollectRoute10Failed", ...} a route that did not make it
    [msg=Tasker.Task.Failed]    {"entry":"AutoCollectSchedule", ...}   attempt ends failed

Until 2026-10-06 this watcher narrowed the master's 自动采集 route lists to the
failed routes the moment one failed, so AUTO-MAS's retry walked only those
(2026-09-14). That switched off routes the user had selected; he forbade it on
2026-10-06 (02:46-03:12 Tokyo): 「我开的任务是谁说要关的」. The master is no
longer written here. A failing attempt is logged with the routes it named; the
failure itself reaches the group from the run's record (unresolved.py) and the
after-queue per-route retry (collect_retry.maybe_run). Lists an older version
left narrowed still go back at the next attempt's `Tasker.Task.Starting` (its
config was copied before MaaEnd was launched, so the master is free), and - as
before - when the MaaEnd record lands, at the shutdown decision and at boot.

The thread sleeps on a directory-change notification for the debug dir
(watch.py) and reads only the bytes appended since its last look. It also wakes
once a minute without one, for the MaaEnd watchdog (maaend_watchdog.py): on
2026-10-01 MaaEnd hung for 40 minutes after its plugin crashed, and a hung
MaaEnd is exactly the case where nothing writes there - a thread that only
wakes on writes would never notice. An idle wake costs one stat().

Every task's start / end in the same lines also feeds task_shots.py, which
takes a desktop picture at each task end on a thread of its own.
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
_TASK_EVENT = "Tasker.Task."
COALESCE_SECONDS = 2.0
TICK_SECONDS = 60.0     # longest sleep without a write; the watchdog's clock


class Watcher:
    """Turns maafw.log lines into route-failure log lines and restores of an old narrowing. File-free for tests: `feed()`."""

    def __init__(self, cfg, notifier, shots=None):
        self.cfg, self.notifier = cfg, notifier
        self.shots = shots               # task_shots.Shooter: a picture at every task end
        self.failed: list[str] = []      # caseNames of this attempt, e.g. Route10
        self._offset = 0
        self._tail = ""
        # For the MaaEnd watchdog: complete lines read so far (rotation included)
        # and the timestamp of the newest one.
        self.lines_seen = 0
        self.last_stamp = ""

    # ---------------------------------------------------------------- parsing

    def feed(self, text: str) -> list[str]:
        """Consume log text (any number of lines). Returns the notes it logged."""
        notes: list[str] = []
        for line in text.splitlines():
            if _NOTIFY not in line:
                continue
            if self.shots is not None and _TASK_EVENT in line:
                try:
                    self.shots.on_line(line)    # queues only; never waits on a picture
                except Exception:
                    log.debug("任务截图排队出错", exc_info=True)
            if _PREFILTER not in line:
                continue
            if m := _ROUTE_FAILED.search(line):
                rid = m.group(1)
                if rid not in self.failed:
                    self.failed.append(rid)
            elif m := _TASK.search(line):
                notes.extend(self._task_event(m.group(1), line))
        return notes

    def _task_event(self, kind: str, line: str) -> list[str]:
        notes: list[str] = []
        if kind == "Starting":
            # A new attempt: its config was copied before MaaEnd was launched, so
            # route lists an older relay version left narrowed can go back now.
            notes.extend(self._restore())
            self.failed = []
        elif kind == "Failed":
            when = (_STAMP.match(line) or [None, "?"])[1]
            log.info("自动采集这一趟失败（%s），没走通：%s", when,
                     "、".join(self.failed) if self.failed else "日志里没有点名哪条路线")
        return notes

    # ---------------------------------------------------------------- effects

    def _restore(self) -> list[str]:
        from . import collect_retry  # noqa: PLC0415
        try:
            back = collect_retry.restore_master(self.cfg)
        except Exception:
            log.exception("母本路线改回出错")
            return []
        if back:
            log.info("🔁 新一趟开始，%s", back)
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
        if text:
            self.lines_seen += text.count("\n") + 1
            for line in reversed(text.splitlines()):
                if m := _STAMP.match(line):
                    self.last_stamp = m.group(1)
                    break
        if track:
            self._offset = offset + len(data)
            self._tail = rest
        return self.feed(text)


def start(cfg, notifier) -> bool:
    """Arm the watcher thread. False (and a log line) when there is nothing to watch."""
    from . import task_shots, watch  # noqa: PLC0415
    try:
        task_shots.prune(cfg.state_dir)
    except Exception:
        log.warning("清旧的任务截图出错", exc_info=True)
    if not cfg.maaend_dir:
        log.info("没配 MaaEnd 目录，不盯采集日志")
        return False
    debug = Path(cfg.maaend_dir) / "debug"
    if not debug.is_dir():
        log.info("MaaEnd 的 debug 目录不存在（%s），不盯采集日志", debug)
        return False
    shots = None
    try:
        shots = task_shots.start(cfg)
    except Exception:
        log.warning("任务截图线程起不来，不截图", exc_info=True)
    w = Watcher(cfg, notifier, shots)
    try:
        w._offset = w.log_path().stat().st_size   # start from now, not from the last run
    except OSError:
        pass
    from . import maaend_watchdog  # noqa: PLC0415
    dog = maaend_watchdog.Watchdog(notifier, debug, state_dir=cfg.state_dir)
    wake = threading.Event()
    if not watch.start(debug, wake):
        log.warning("挂不上 MaaEnd debug 目录的变更通知，MaaEnd 卡死看门狗和任务截图不工作")
        return False

    def run() -> None:
        while True:
            if wake.wait(timeout=TICK_SECONDS):
                wake.clear()
                time.sleep(COALESCE_SECONDS)     # MaaFW writes thousands of lines a second
            try:
                w.poll()
            except Exception:
                log.exception("盯采集日志出错，继续")
            # Separate guard: a watchdog fault must not stop the log reading.
            try:
                dog.tick(w.lines_seen, w.last_stamp)
            except Exception:
                log.exception("MaaEnd 卡死看门狗出错，继续")

    threading.Thread(target=run, name="collect-watch", daemon=True).start()
    log.info("已挂上 MaaEnd 日志监听：记下没走通的采集路线；MaaEnd 卡死就结束它%s",
             "；每个任务结束截一张桌面" if shots is not None else "")
    return True
