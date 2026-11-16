"""Wake the game PC's display while AUTO-MAS brings Endfield up through its launcher.

Why: the power plan turns the display off after 300 s without input (powercfg AC
VIDEOIDLE 0x12c on the game PC), and the Hypergryph launcher keeps its main window
hidden while the display is off. Its own log, games.log, 2026-10-16 attempt 1:

    [10-16 13:21:31.615] ... bMainWndHide:true
    [10-16 13:21:31.616] ... [syspa] System display event: display off

and no 「display on」 / bMainWndHide:false before AUTO-MAS gave up at 13:23:36
(「游戏启动失败: 等待终末地游戏窗口超时」). Attempt 2 showed the window 0.8 s after
「display on」 (13:24:52.778 -> 13:24:53.567) and clicked 开始游戏 3 s later.
AUTO-MAS v5.7.0-beta.4 (launcher_start.py:479-514) only dismisses a running
screensaver, never a display the power plan has turned off. Until cdc1d5fb the
relay's own efstart drove the launcher, and its first desktop read woke the display
as a side effect (desktop.py WakeDisplay); handing the start back to AUTO-MAS
removed that. Any launcher start after 5 idle minutes is exposed, as the 13:21
make-up was.

What this does: a thread tails AUTO-MAS's `<automas>/debug/app.log` (woken by a
directory-change notification, POLL_SECONDS as a backstop) and, at each line where
AUTO-MAS hands Endfield to its launcher (「MaaEnd 自动代理 | 启动方式为「启动器启动」，
将由 MAS ...」, 13:21:28.423 that day; on v5.7.0-beta.5 「启动方式为「启动器启动」」 or, in
the 「MaaEnd 启动」 mode used since 10-17, 「启动方式为「MaaEnd 启动」」; one per attempt, so a
retry re-arms it), wakes the display at once through the
desktop agent (a zero-distance mouse move, the same WakeDisplay every screenshot
uses), then again every REWAKE_SECONDS until AUTO-MAS logs that the game is up
(「运行脚本任务: ...MaaEnd.exe」, 13:26:14 for attempt 2), the attempt failed
(「游戏启动失败」), or WINDOW_SECONDS have passed. One wake keeps the display on for
the 300 s idle time, longer than AUTO-MAS's 120 s launcher wait; the re-wakes only
cover a wake whose agent did not start. Nothing else changes: the power plan is not
touched and the display goes off again 5 minutes after the last wake.

Not this: 「业务调度 | 任务开始: <uid>」 also starts OK-WW and a MaaEnd that the config
check then refuses (09:34:04 / 09:34:05 that day), so it is not used. Not the
engine tick either: it reads app.log only every 60 s and only once it has seen a
script running, which a hand-started run idle until then never gets in time.
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ark.display_wake")

# Measured 2026-10-16 (app.log): AUTO-MAS gave up 128 s after the hand-off
# (13:21:28.423 -> 13:23:36.444), so a wake whose agent failed is retried once
# inside that wait. The game came up 158 s and 79 s after the hand-off in attempts
# 2 and 3 (13:26:14.036, 13:54:52.502); the window is the display's own idle time
# (powercfg AC VIDEOIDLE 0x12c = 300 s), after which the wake has long done its job.
REWAKE_SECONDS = 60
WINDOW_SECONDS = 300
# Measured: the launcher checks the display 3 s after the hand-off (games.log
# 13:21:31.616 「display off」); a missed notification costs at most this much.
POLL_SECONDS = 10.0
COALESCE_SECONDS = 0.5

_STAMP = r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^|]*\| MaaEnd 自动代理 \| "
# beta.4 logged 「启动方式为「启动器启动」，将由 MAS ...」; v5.7.0-beta.5 logs the bare mode
# (AutoProxy.py:496 「启动方式为「启动器启动」」, :503 「启动方式为「MaaEnd 启动」」, the mode
# efstart_setup sets since 10-17). In 「MaaEnd 启动」 MaaEnd's pretask starts Launcher.exe and
# finds it by its window just the same. 「MAS 启动」 starts Endfield.exe itself, no launcher window.
_HANDOFF = re.compile(_STAMP + r"启动方式为「(?:启动器启动|MaaEnd 启动)」")
_GAME_UP = re.compile(_STAMP + r"运行脚本任务")
_LAUNCH_FAILED = re.compile(_STAMP + r".*游戏启动失败")


def _when(s: str) -> datetime:
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    return datetime.fromisoformat(s).replace(tzinfo=SERVER_TZ)


class Waker:
    """Decides when to wake the display from app.log lines. File-free and clock-free for tests."""

    def __init__(self):
        self.until: datetime | None = None      # end of the current window; None when idle
        self.last_wake: datetime | None = None
        self.warned = False                     # a failed wake already went to the group this attempt

    def feed(self, lines) -> None:
        for line in lines:
            if "MaaEnd 自动代理" not in line:
                continue
            if m := _HANDOFF.match(line):
                self.until = _when(m.group(1)) + timedelta(seconds=WINDOW_SECONDS)
                self.last_wake = None           # a new attempt: wake at once
                self.warned = False
            elif self.until is not None and (_GAME_UP.match(line) or _LAUNCH_FAILED.match(line)):
                self.until = None

    def due(self, now: datetime) -> bool:
        """True when a wake should be issued now; the caller then calls woke(now)."""
        if self.until is None:
            return False
        if now >= self.until:
            self.until = None
            return False
        return self.last_wake is None or (now - self.last_wake).total_seconds() >= REWAKE_SECONDS

    def woke(self, now: datetime) -> None:
        self.last_wake = now


class Tail:
    """What app.log gained since the last read; follows AUTO-MAS's rotation at its start."""

    def __init__(self, path: Path, from_end: bool = True):
        self.path = path
        self._offset = 0
        self._tail = ""
        if from_end:
            try:
                self._offset = path.stat().st_size   # from now, not the lines of an earlier run
            except OSError:
                pass

    def read(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self._offset:
            self._offset, self._tail = 0, ""
        try:
            with self.path.open("rb") as fh:
                fh.seek(self._offset)
                data = fh.read()
        except OSError:
            return []
        if not data:
            return []
        self._offset += len(data)
        text, _, self._tail = (self._tail + data.decode("utf-8", "replace")).rpartition("\n")
        return text.splitlines()


def step(waker: Waker, tail: Tail, wake, now: datetime) -> bool:
    """One look: read app.log, wake when due. True when a wake was issued."""
    waker.feed(tail.read())
    if not waker.due(now):
        return False
    waker.woke(now)
    # Every WARNING goes to the group (errwatch): once per attempt, the retries
    # inside the same attempt only to the log.
    level = logging.INFO if waker.warned else logging.WARNING
    why = ("终末地经官方启动器开游戏：叫醒屏幕没成功，%d 秒后再试；屏幕关着时启动器不显示窗口，"
           "调度程序等不到就会算开游戏失败")
    try:
        ok = bool(wake())
    except Exception:
        waker.warned = True
        log.log(level, why, REWAKE_SECONDS, exc_info=True)
        return True
    if ok:
        log.info("终末地经官方启动器开游戏：已叫醒屏幕（屏幕关着时启动器不显示窗口）")
    else:
        waker.warned = True
        log.log(level, why, REWAKE_SECONDS)
    return True


def start(cfg) -> bool:
    """Arm the thread. False (and a log line) off Windows or without an AUTO-MAS log to read."""
    from ark_relay.core import config, watch  # noqa: PLC0415
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    if not config.IS_WINDOWS:
        return False
    if not cfg.automas_dir:
        log.info("没配调度程序目录，终末地开游戏时不叫醒屏幕")
        return False
    debug = Path(cfg.automas_dir) / "debug"
    if not debug.is_dir():
        log.info("调度程序的 debug 目录不存在（%s），终末地开游戏时不叫醒屏幕", debug)
        return False
    from ark_relay.core.desktop import Desktop  # noqa: PLC0415 - Windows-only helper
    desk = Desktop(Path(cfg.state_dir))
    waker, tail = Waker(), Tail(debug / "app.log")
    changed = threading.Event()
    watching = watch.start(debug, changed)

    def run() -> None:
        while True:
            if changed.wait(timeout=POLL_SECONDS):
                changed.clear()
                threading.Event().wait(COALESCE_SECONDS)
            try:
                step(waker, tail, desk.wake, datetime.now(tz=SERVER_TZ))
            except Exception:
                log.exception("盯调度程序日志（叫醒屏幕）出错，继续")

    threading.Thread(target=run, name="display-wake", daemon=True).start()
    log.info("已挂上调度程序日志监听：终末地经官方启动器开游戏时叫醒屏幕%s",
             "" if watching else f"（没有目录变更通知，每 {POLL_SECONDS:.0f} 秒看一次）")
    return True
