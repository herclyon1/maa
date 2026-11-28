"""Watch MaaFW's live log for MaaEnd: failed gathering routes, task pictures,
and the MaaEnd hang watchdog.

MaaFW's log, `<maaend_dir>/debug/maafw.log`, is written live (AUTO-MAS writes a
script's records only when all its attempts are over):

    [msg=Tasker.Task.Starting]  {"entry":"AutoCollectSchedule", ...}   attempt begins
    [msg=Node.Action.Starting]  {"name":"AutoCollectRoute10Failed", ...} a route that did not make it
    [msg=Tasker.Task.Failed]    {"entry":"AutoCollectSchedule", ...}   attempt ends failed

A failed attempt is logged with the routes it named; nothing is written to the
master config here. At each attempt's `Tasker.Task.Starting`, route lists an
older relay version left narrowed are restored (collect_retry.restore_master).

The thread sleeps on a directory-change notification for the debug dir
(watch.py) and reads only the bytes appended since its last look. It also wakes
at least every TICK_SECONDS for the MaaEnd watchdog (maaend_watchdog.py), since
a hung MaaEnd writes nothing. Task start / end lines also feed task_shots.py,
which takes a desktop picture at each task end on its own thread.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import threading
import time
import zlib
from pathlib import Path

log = logging.getLogger("ark.collect_watch")

# Blocking Endfield dialogs as MaaFW's OCR logs them (collector_maaend):
# only counted here when matched in an OCR `"text":"..."` value (never in param_.expected).
from ark_relay.features.collector_maaend import AGREEMENT_TEXT, LOGGED_OUT_TEXT, ocr_read_has  # noqa: E402 - after the logger, as above

_AGREE_FORMS = (AGREEMENT_TEXT, json.dumps(AGREEMENT_TEXT).strip('"'))
_LOGOUT_FORMS = (LOGGED_OUT_TEXT, json.dumps(LOGGED_OUT_TEXT).strip('"'))

ENTRY = "AutoCollectSchedule"
_TASK = re.compile(r"\[msg=Tasker\.Task\.(Starting|Completed|Failed)\].*?\"entry\":\"" + ENTRY + r"\"")
_ROUTE_FAILED = re.compile(
    r"\[msg=Node\.Action\.Starting\].*?\"name\":\"(?:__)?AutoCollect((?:Common)?Route\d+|[A-Za-z]+?\d+)Failed\""
    r"|\[msg=Node\.PipelineNode\.Failed\].*?\"name\":\"AutoCollect([A-Za-z]+?\d+)[A-Z][A-Za-z]*\"")
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
        self._last_mtime = 0.0           # mtime of maafw.log at last poll: guards against re-reading old .bak files on restart
        self._read_baks: set[str] = set()
        # For the MaaEnd watchdog: complete lines read so far (rotation included)
        # and the timestamp of the newest one.
        self.lines_seen = 0
        self.last_stamp = ""
        # For the watchdog's blocking-dialog check: chunks read with each dialog's line in them,
        # counted since the relay started.
        self.agreement_seen = 0
        self.logout_seen = 0
        self._shots_broken = False       # the picture queue failed once in this attempt (said once)

    # ---------------------------------------------------------------- parsing

    def feed(self, text: str) -> list[str]:
        """Consume log text (any number of lines). Returns the notes it logged."""
        notes: list[str] = []
        lines = text.splitlines()
        if any(x in text for x in _AGREE_FORMS) and any(ocr_read_has(ln, _AGREE_FORMS) for ln in lines):
            self.agreement_seen += 1
        if any(x in text for x in _LOGOUT_FORMS) and any(ocr_read_has(ln, _LOGOUT_FORMS) for ln in lines):
            self.logout_seen += 1
        for line in lines:
            if _NOTIFY not in line:
                continue
            if self.shots is not None and _TASK_EVENT in line:
                try:
                    self.shots.on_line(line)    # queues only; never waits on a picture
                except Exception:  # the watch goes on; the group hears it once per attempt
                    if not self._shots_broken:
                        self._shots_broken = True
                        log.warning("任务截图排队出错，这一趟后面的任务截图可能都没有", exc_info=True)
            if _PREFILTER not in line:
                continue
            if m := _ROUTE_FAILED.search(line):
                rid = m.group(1) or m.group(2)
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
        from ark_relay.features import collect_retry  # noqa: PLC0415
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
            st = p.stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            return []
        notes: list[str] = []
        if size < self._offset:
            # MaaFW renamed the file to maafw.bak.<stamp>.log and gzips it to .log.gz;
            # the last lines of the old one (the Failed nodes and dialog OCR lines) are
            # still unread there. Only pick a rotated file created since our last read of
            # maafw.log (never an older run's leftover .log.gz when MaaEnd restarts fresh).
            baks = []
            for q in [*p.parent.glob("maafw.bak.*.log"), *p.parent.glob("maafw.bak.*.log.gz")]:
                if q.name in self._read_baks:
                    continue
                try:
                    qm = q.stat().st_mtime
                except OSError:
                    continue
                if self._last_mtime and qm < self._last_mtime - 2.0:
                    continue
                baks.append((qm, q))
            if baks:
                chosen = max(baks)[1]
                self._read_baks.add(chosen.name)
                # final: the old file is closed, so its last line is whole even without a
                # newline - kept as the tail it was dropped by the reset below (audit B-06).
                notes.extend(self._read_from(chosen, self._offset, final=True))
            self._offset, self._tail = 0, ""
        self._last_mtime = mtime
        notes.extend(self._read_from(p, self._offset, track=True))
        return notes

    def _read_from(self, p: Path, offset: int, *, track: bool = False, final: bool = False) -> list[str]:
        try:
            opener = gzip.open(p, "rb") if p.suffix == ".gz" else p.open("rb")
            with opener as fh:
                fh.seek(offset)
                data = fh.read()
        except (OSError, EOFError, zlib.error):
            return []
        if not data:
            return []
        text = self._tail + data.decode("utf-8", "replace")
        if final:
            text, rest = text.rstrip("\r\n"), ""
        else:
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
    from ark_relay.features import task_shots  # noqa: PLC0415
    from ark_relay.core import watch  # noqa: PLC0415
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
        st = w.log_path().stat()
        w._offset = st.st_size   # start from now, not from the last run
        w._last_mtime = st.st_mtime
        w._read_baks = {q.name for q in [*debug.glob("maafw.bak.*.log"), *debug.glob("maafw.bak.*.log.gz")]}
    except OSError:
        pass
    from ark_relay.features import maaend_watchdog  # noqa: PLC0415
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
                dog.tick(w.lines_seen, w.last_stamp, w.agreement_seen, w.logout_seen)
            except Exception:
                log.exception("MaaEnd 卡死看门狗出错，继续")

    threading.Thread(target=run, name="collect-watch", daemon=True).start()
    log.info("已挂上 MaaEnd 日志监听：记下没走通的采集路线；MaaEnd 卡死就结束它%s",
             "；每个任务结束截一张桌面" if shots is not None else "")
    return True
