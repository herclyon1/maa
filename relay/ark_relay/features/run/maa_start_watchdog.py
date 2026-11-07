"""End MAA.exe when Arknights' game start hangs, so AUTO-MAS restarts it now (ledger #137).

2026-11-05 早班: MAA began starting the game at 09:03:23 (asst.log, TaskChainStart StartUp) and
pressed the title screen's 「开始唤醒」 609 times (SubTaskStart GameStart, exec_times 1..609, one
press every 4.4 s) while the game stayed at 「正在提交反馈至神经」. Nothing ended it until
AUTO-MAS's own limit for MAA at 09:48:24 (app.log 「MAA 任务结果: MAA 进程超时」); the retry was in
the game 101 s after its start (09:49:43 -> 09:51:24), and the whole morning shift slid by 46
minutes.

What AUTO-MAS does once MAA.exe is gone (app/task/MAA/AutoProxy.py on the machine): its log
monitor calls check_log at least once a minute even while MAA's gui.log does not change
(app/utils/LogMonitor.py, 「日志无变化超时调用回调」), and check_log turns a MAA that is no longer
running into 「MAA 在完成任务前退出」. That is a failed attempt, handled like the 09:48 one in
app.log: the failure screenshot, the emulator closed, MAA.exe ended, then 「尝试次数: 2/3」 and a
fresh emulator and MAA. So ending MAA.exe is all it takes: the emulator and the game are
AUTO-MAS's to close, and when the attempts run out MAA's turn fails as any failure does.

Hung means, all at once:
  * AUTO-MAS's runtime snapshot says MAA is exactly 「运行」 (no snapshot -> never kill blind);
  * the newest StartUp task chain in <maa>/debug/asst.log is open - a TaskChainStart with no
    TaskChainCompleted / TaskChainError / TaskChainStopped after it and no 「MaaCore Process
    Start」 banner of a newer MAA - and the MAA.exe that wrote it is still running. The log's
    [Px<pid>] is MAA.exe's PID: app.log 09:02:59 「MAA 进程已创建: D:\\ark\\maa\\MAA.exe - PID:
    16328」, asst.log [Px16328];
  * for STARTUP_LIMIT_SECONDS no sign of a download or a resource check. MAA's StartUp repeats
    GameStartUpdateOCR (「正在释放神经递质」 / 「MB」, the game downloading an update) and
    GameStartCheckResourceOCR (「资源完整性」 / 「不消耗流量」, its integrity check) every few seconds
    while either screen is up (resource/tasks/tasks.json: next 「#self」, postDelay 5 s), and each
    one restarts the clock. A hot update is progress, never a hang.

Only MAA.exe is ended, by its PID and image name (maaend_watchdog._taskkill: no /T). One alarm
per hung start (its PID and start time), whether the kill worked or not. After a kill the
watchdog leaves the mark AUTO-MAS's own timeout leaves (「超时|MAA|<HH:MM:SS>」, runwatch.
check_timeouts), so the shift's overrun and no-result clocks restart from it the same way
(runwatch.retry_clock, ledger #138). No other alarm follows the kill: AUTO-MAS logs
「MAA 任务结果: MAA 在完成任务前退出」, which runwatch does not read as a timeout.

Not this: a download whose screen MAA no longer recognises. The only signs of progress are the
two OCR tasks above; should an update change that screen so GameStartUpdateOCR stops firing,
a long download would be ended as a hang on every attempt. AUTO-MAS's app.log line
「检测到待下载的游戏资源热更新」 (AutoProxy._check_game_update, logged when the resource version
differs from the last good run) would be the second sign to read then.

Its own thread (start), one look every CHECK_EVERY_SECONDS; the snapshot and the process list
are only read once a start has gone quiet for the limit.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from ark_relay.core import config, texts
from ark_relay.features.run import maaend_watchdog

log = logging.getLogger("ark.maa_start_watchdog")

SCRIPT = "MAA"                     # the script's name in AUTO-MAS's task_info
RUNNING = "运行"
MAA_EXE = "maa.exe"
# Measured: every StartUp in MAA's asst.bak.log and asst.log (11-01 23:10 .. 11-05) took
# 58-66 s, nine runs, and the 11-05 retry 101 s. The user agreed to restart a hung start with
# the limit taken from the longest normal one (11-05, 「我建议加」); this is three times that.
STARTUP_LIMIT_SECONDS = 5 * 60
CHECK_EVERY_SECONDS = maaend_watchdog.CHECK_EVERY_SECONDS
# Read back on the first look, so a relay that starts in the middle of a hang still finds its
# TaskChainStart. Measured: the 11-05 hang wrote 2.28 MB in 46 minutes (9305 lines).
BACKLOG_BYTES = 4 * 1024 * 1024
PROGRESS_TASKS = (b"GameStartUpdateOCR", b"GameStartCheckResourceOCR")
PRESS_TASK = b"GameStart"          # 「开始唤醒」 on the title screen
_HEAD_BYTES = 64

# 「[2026-11-05 09:03:23.760][INF][Px16328][Tx43461] Assistant::append_callback | TaskChainStart {...}」
_LINE = re.compile(rb"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+\]\[[A-Z]+\]\[Px(\d+)\]\[Tx\d+\] (.*)$")
_CALLBACK = re.compile(rb"Assistant::append_callback \| "
                       rb"(TaskChainStart|TaskChainCompleted|TaskChainError|TaskChainStopped|SubTaskStart) ")
_TASK = re.compile(rb'"task":"([^"]+)"')        # details.task, the first such key in a SubTaskStart
_STARTUP = b'"taskchain":"StartUp"'
_BANNER = b"MaaCore Process Start"


class Start:
    """One open game start: the MAA.exe that began it, when, the last download / resource-check
    screen seen in it, and how often 「开始唤醒」 was pressed."""

    __slots__ = ("pid", "at", "progress", "presses")

    def __init__(self, pid: int, at: datetime):
        self.pid, self.at, self.progress, self.presses = pid, at, at, 0


def _maa_running(snap) -> bool:
    return any(str(i.get("name") or "") == SCRIPT and str(i.get("status") or "") == RUNNING
               for t in (snap or {}).get("tasks") or []
               for i in (t or {}).get("task_info") or [])


class Watchdog:
    """State machine over asst.log; clock, snapshot, process list and kill are injectable."""

    def __init__(self, notifier, maa_dir, *, now=datetime.now, snapshot=maaend_watchdog._snapshot,
                 processes=maaend_watchdog._tasklist, kill=maaend_watchdog._taskkill,
                 active: "bool | None" = None, state_dir=None):
        self.notifier = notifier
        self.state_dir = state_dir      # where the restart mark goes (runwatch.retry_clock)
        self.path = Path(maa_dir) / "debug" / "asst.log"
        self.now, self.snapshot, self.processes, self.kill = now, snapshot, processes, kill
        self.active = config.IS_WINDOWS if active is None else active
        self.start: "Start | None" = None
        self._offset: "int | None" = None     # None: the first look reads back BACKLOG_BYTES
        self._head = b""
        self._rest = b""
        self._handled: set = set()

    def tick(self) -> "str | None":
        """One look. Returns the alarm title sent, None when nothing was done."""
        if not self.active:
            return None
        self._read()
        s = self.start
        # one fault, one push: one hung start, by the PID of the MAA that began it and its start time
        if s is None or (s.pid, s.at) in self._handled:
            return None
        now = self.now()
        quiet = (now - s.progress).total_seconds()
        if quiet < STARTUP_LIMIT_SECONDS:
            return None
        snap = self.snapshot()
        if snap is None or not _maa_running(snap):
            return None                 # cannot tell, or AUTO-MAS is not running MAA: never kill blind
        procs = self.processes()
        if procs is None:
            return None
        if not any(p == s.pid and n.lower() == MAA_EXE for n, p in procs):
            # The MAA that began this start is gone (AUTO-MAS ended it, or it exited).
            self.start = None
            return None
        return self._end(s, now, quiet)

    # ---------------------------------------------------------------- asst.log

    def _read(self) -> None:
        """Feed what asst.log gained; start over when MAA rotated it (asst.bak.log)."""
        try:
            size = self.path.stat().st_size
            with self.path.open("rb") as fh:
                head = fh.read(_HEAD_BYTES)
                first = self._offset is None
                if first:
                    self._offset = max(0, size - BACKLOG_BYTES)
                elif size < self._offset or (self._head and head[:len(self._head)] != self._head):
                    # Rotated: what the old file gained after the last read is now in
                    # asst.bak.log - StartUp's completion line can be there (audit B-05).
                    self._feed_rotated_tail(self._offset)
                    self._offset, self._rest = 0, b""
                fh.seek(self._offset)
                data = fh.read()
        except OSError:
            return
        self._head = head
        if not data:
            return
        skip_partial = first and self._offset > 0
        self._offset += len(data)
        lines = (self._rest + data).split(b"\n")
        self._rest = lines.pop()
        if skip_partial and lines:
            lines = lines[1:]           # the read began inside a line
        for line in lines:
            self._feed(line.rstrip(b"\r"))

    def _feed_rotated_tail(self, offset: int) -> None:
        """Feed asst.bak.log from `offset` (where the read of asst.log stopped) to its end."""
        bak = self.path.with_name("asst.bak.log")
        try:
            with bak.open("rb") as fh:
                if bak.stat().st_size < offset:
                    return              # not the file read up to offset: nothing to resume
                fh.seek(offset)
                data = fh.read(BACKLOG_BYTES)
        except OSError:
            return
        lines = (self._rest + data).split(b"\n")
        for line in lines:
            self._feed(line.rstrip(b"\r"))

    def _feed(self, line: bytes) -> None:
        m = _LINE.match(line)
        if not m:
            return
        rest = m.group(3)
        if rest.startswith(_BANNER):
            self.start = None           # a new MAA: an open start belonged to the one before
            return
        cb = _CALLBACK.match(rest)
        if not cb:
            return
        if _STARTUP not in rest:
            # Another task chain of the same MAA began (Fight, Infrast ...): its StartUp is
            # over, even if the completion line was lost (asst.log rotated between reads) -
            # left open, the start ran out its limit during the fight and MAA was killed
            # mid-stage (audit 2026-11-08 B-05).
            s = self.start
            if s is not None and cb.group(1) == b"TaskChainStart" and int(m.group(2)) == s.pid:
                self.start = None
            return
        try:
            at = datetime.strptime(m.group(1).decode("ascii"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return
        pid, kind = int(m.group(2)), cb.group(1)
        if kind == b"TaskChainStart":
            self.start = Start(pid, at)
            return
        s = self.start
        if s is None or s.pid != pid:
            return
        if kind == b"SubTaskStart":
            t = _TASK.search(rest)
            task = t.group(1) if t else b""
            if task in PROGRESS_TASKS:
                s.progress = at
            elif task == PRESS_TASK:
                s.presses += 1
            return
        self.start = None               # TaskChainCompleted / TaskChainError / TaskChainStopped

    # ---------------------------------------------------------------- effects

    def _end(self, s: Start, now: datetime, quiet: float) -> str:
        self._handled.add((s.pid, s.at))
        ok, why = self.kill(s.pid, "MAA.exe")
        if ok:
            self._mark_restart(now)
        title = texts.MAA_START_STUCK_KILLED if ok else texts.MAA_START_STUCK_KILL_FAILED
        body = texts.maa_start_stuck_body(s.at.strftime("%H:%M"), int((now - s.at).total_seconds() // 60),
                                          s.presses, ok, why, int(quiet // 60))
        # One hang, one group push: the ⚠️ alarm, and the WARNING after it repeats it only in
        # relay.log when that alarm really reached the group (errwatch.group_pushed).
        pushed = {}
        try:
            errs = self.notifier.send(title, body, alert=True)
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            pushed = errwatch.group_pushed(title, errs, self.notifier)
        except Exception:
            log.exception("明日方舟开游戏卡住的报警没发出去")
        log.warning("明日方舟开游戏卡住：MAA（PID %s）%s 开始开游戏，%d 秒没进展，「开始唤醒」点了 %d 次；%s",
                    s.pid, s.at.strftime("%H:%M:%S"), int(quiet), s.presses,
                    "已结束 MAA" if ok else f"没结束成：{why}", extra=pushed)
        return title


    def _mark_restart(self, now: datetime) -> None:
        """The 「超时|MAA|<HH:MM:SS>」 day mark runwatch.retry_clock restarts the shift's clocks
        from. Never raises: a mark that cannot be written leaves the clocks at the shift's time."""
        if not self.state_dir:
            return
        key = f"超时|{SCRIPT}|{now:%H:%M:%S}"

        def add(got):
            cur = list(got) if isinstance(got, list) else []
            return cur if key in cur else [*cur, key]
        try:
            from ark_relay.core.statestore import StateStore  # noqa: PLC0415
            StateStore(self.state_dir).update("marks", f"alerted:{now:%Y-%m-%d}", add)
        except Exception:
            log.warning("记不下这次重开的时刻：这一班的超时计时还从排定的开跑时间算", exc_info=True)


def start(cfg, notifier) -> bool:
    """Arm the thread. False (and a log line) off Windows or without MAA's install folder."""
    if not config.IS_WINDOWS:
        return False
    if not cfg.maa_dir:
        log.info("没配 MAA 目录，明日方舟开游戏卡住时不会自动重开")
        return False
    dog = Watchdog(notifier, cfg.maa_dir, state_dir=cfg.state_dir)

    def run() -> None:
        while True:
            time.sleep(CHECK_EVERY_SECONDS)
            try:
                dog.tick()
            except Exception:
                log.exception("明日方舟开游戏看门狗出错，继续")

    threading.Thread(target=run, name="maa-start-watch", daemon=True).start()
    log.info("已挂上明日方舟开游戏看门狗：MAA 开游戏 %d 分钟没进展（不在下载更新、不在校验资源）就结束 MAA，"
             "让 AUTO-MAS 重开", STARTUP_LIMIT_SECONDS // 60)
    return True
