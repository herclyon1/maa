"""End MaaEnd.exe when it hangs, so AUTO-MAS retries now instead of 45 minutes later.

2026-10-01 15:30:03, MaaEnd on 「信用点购物」: its plugin
D:\\ark\\maaend\\agent\\go-service.exe crashed - go-service.stderr.log line 1
`Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456`, then a Go
goroutine dump. maafw.log never gained another line; MaaEnd.exe stayed alive,
waiting on a plugin that was gone, until AUTO-MAS's per-script limit
killed it at 16:10:00 - AUTO-MAS ends MaaEnd after 40 minutes without a log
line (15:30:03 -> 16:10:00). The same day at 16:58:22 MaaEnd logged
「tasks-completed」 and closed the game, but MaaEnd.exe never exited and AUTO-MAS
kept it 「运行」; 2026-09-28 11:22:10 -> 12:02:11 was that same case. On
MaaEnd.exe exiting AUTO-MAS judges the run from MaaEnd's log at once (measured
10-01 16:11:08): unfinished tasks are retried, a finished run just closes. So
ending MaaEnd.exe early is all it takes, in both cases.

Judged only while AUTO-MAS's runtime-snapshot says MaaEnd is exactly 「运行」
(no snapshot -> no judgment, no kill). Hung means one of:

  1. the plugin crashed: go-service.stderr.log gained `Exception 0x` /
     `panic:` / `fatal error`; or MaaEnd.exe has been seen for 3 minutes and
     go-service.exe is missing on two checks at least 60 s apart
  2. stalled: MaaEnd.exe alive and maafw.log without a new line for 10 minutes
     (normal runs, measured 09-25 .. 10-01: never more than 65 s between lines;
     10 minutes is the threshold the user approved, 10-01 17:28)

Then only MaaEnd.exe is ended, plus its two plugins by their own PIDs - never
with `taskkill /T`: MaaEnd can launch Endfield.exe itself (docs/BACKLOG.md,
`collect_retry._game_exe` reads the game path MXU saved), so the game may sit
in MaaEnd's process tree, and the game is never to be killed here. One alarm
per MaaEnd PID, whether the kill worked or not.

No timer of its own: collect_watch's thread calls `tick` on every wake, and
wakes at least once a minute even when the debug dir is silent - a hung
MaaEnd is exactly the case where nothing writes there.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from . import texts

log = logging.getLogger("ark.maaend_watchdog")

SCRIPT = "MaaEnd"                  # the script's name in AUTO-MAS's task_info
RUNNING = "运行"
MAAEND_EXE = "maaend.exe"
GO_SERVICE = "go-service.exe"
PLUGINS = (GO_SERVICE, "cpp-algo.exe")   # both live in <maaend>\agent\, started ~16 s after MaaEnd
STALL_SECONDS = 10 * 60
PLUGIN_GRACE_SECONDS = 3 * 60      # plugins are not up yet in MaaEnd's first seconds
GONE_CONFIRM_SECONDS = 60
CHECK_EVERY_SECONDS = 30           # MaaFW wakes the thread every ~2 s; tasklist need not follow
_CRASH_MARKS = ("Exception 0x", "panic:", "fatal error")
_CODE = re.compile(r"Exception (0x[0-9A-Fa-f]+)")
_HEAD_BYTES = 64


def _snapshot():
    from .engine import _automas_snapshot  # noqa: PLC0415 - engine imports half the relay
    return _automas_snapshot()


def _tasklist() -> "list[tuple[str, int]] | None":
    """(image name, PID) of every process; None when tasklist itself failed."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    # Image names are ASCII; the session column may be GBK, which is never read.
    rows = []
    for rec in csv.reader(io.StringIO(out.decode("utf-8", "replace"))):
        if len(rec) >= 2 and rec[1].isdigit():
            rows.append((rec[0], int(rec[1])))
    return rows


def _taskkill(pid: int, image: str) -> "tuple[bool, str]":
    """End one PID, but only if it still carries `image` (no /T, see the module docstring).

    The name filter closes the gap between tasklist and taskkill: a PID freed and
    reused in between belongs to some other program, and the filter makes taskkill
    match nothing instead of ending it. A filter that matches nothing still exits 0
    (「信息: 没有运行的带有指定标准的任务。」, read on the machine 2026-10-01), so
    success is read from the 「成功」 / SUCCESS line, not from the exit code.
    """
    try:
        r = subprocess.run(["taskkill", "/F", "/FI", f"PID eq {pid}", "/FI", f"IMAGENAME eq {image}"],
                           capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False, "结束命令 30 秒没返回"
    except OSError:
        log.exception("taskkill 起不来")
        return False, "结束命令没能运行"
    out = (r.stdout or b"").decode("gbk", "replace") + (r.stderr or b"").decode("gbk", "replace")
    if r.returncode == 0 and ("成功" in out or "SUCCESS" in out):
        return True, ""
    log.warning("taskkill PID %s（%s）退出码 %s：%s", pid, image, r.returncode, out.strip())
    if r.returncode == 0:
        return False, "要结束的那个已经不在了"
    return False, f"退出码 {r.returncode}"


def _plugin_paths() -> "dict[int, str]":
    """PID -> executable path of every go-service.exe / cpp-algo.exe; {} when it cannot be read."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='go-service.exe' or Name='cpp-algo.exe'\" | "
          "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.ExecutablePath }")
    from .preupdate_common import _pwsh  # noqa: PLC0415 - the repo's one way to call PowerShell
    try:
        out = subprocess.run([_pwsh(), "-NoProfile", "-Command", ps],
                             capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    paths = {}
    for line in out.decode("utf-8", "replace").splitlines():
        pid, _, path = line.strip().partition("|")
        if pid.isdigit():
            paths[int(pid)] = path
    return paths


def _maaend_running(snap) -> bool:
    return any(str(i.get("name") or "") == SCRIPT and str(i.get("status") or "") == RUNNING
               for t in (snap or {}).get("tasks") or []
               for i in (t or {}).get("task_info") or [])


class Watchdog:
    """Pure state machine; everything outside (clock, snapshot, processes, kill) is injectable."""

    def __init__(self, notifier, debug_dir, *, clock=time.monotonic, snapshot=_snapshot,
                 processes=_tasklist, kill=_taskkill, plugin_paths=_plugin_paths,
                 active: "bool | None" = None):
        self.notifier = notifier
        self.stderr = Path(debug_dir) / "go-service.stderr.log"
        # Plugins are only ended when they run from MaaEnd's own agent folder: the
        # names alone could belong to anything else on the machine.
        self.agent_dir = str(Path(debug_dir).parent / "agent").lower()
        self.clock, self.snapshot, self.processes, self.kill = clock, snapshot, processes, kill
        self.plugin_paths = plugin_paths
        self.active = (os.name == "nt") if active is None else active
        now = clock()
        self._lines: "int | None" = None
        self._progress_at = now         # last time maafw.log gained a line (or MaaEnd was not running)
        self._last_check = float("-inf")
        self._pid: "int | None" = None
        self._pid_seen_at = now
        self._gone_since: "float | None" = None
        self._crash = ""                # first crash line of the current MaaEnd's plugin
        self._handled: set[int] = set()
        self._pid_lines: "int | None" = None   # lines_seen when this MaaEnd was first seen
        self._blind: set[int] = set()           # PIDs already reported as unreadable
        # Start from now, like collect_watch does for maafw.log: an old crash in the
        # file belongs to a MaaEnd that is already gone.
        self._err_offset, self._err_head = self._stderr_now()

    # ---------------------------------------------------------------- the loop

    def tick(self, lines_seen: int, last_stamp: str) -> "str | None":
        """One look. `lines_seen` / `last_stamp` come from collect_watch.Watcher. Returns the title sent."""
        if not self.active:
            return None
        now = self.clock()
        if lines_seen != self._lines:
            self._lines, self._progress_at = lines_seen, now
        if now - self._last_check < CHECK_EVERY_SECONDS:
            return None
        self._last_check = now

        snap = self.snapshot()
        if snap is None:
            return None                 # cannot tell what AUTO-MAS is doing: never kill blind
        if not _maaend_running(snap):
            # Waiting or done: the 10 minutes start over once it is 「运行」 again.
            self._progress_at, self._gone_since = now, None
            return None
        procs = self.processes()
        if procs is None:
            return None
        pid = next((p for n, p in procs if n.lower() == MAAEND_EXE), None)
        if pid is None:
            # Forget it: Windows reuses PIDs, and a later MaaEnd that drew the same
            # number must get its own clocks, not this one's (or its handled mark).
            self._pid, self._gone_since = None, None
            self._handled.clear()
            return None
        if pid != self._pid:
            # A new MaaEnd: its own clocks, and the stderr file still holds the previous
            # run's text until go-service relaunches and rewrites it.
            self._pid, self._pid_seen_at, self._gone_since, self._crash = pid, now, None, ""
            self._pid_lines = self._lines
            self._err_offset, self._err_head = self._stderr_now()
        if pid in self._handled:
            return None
        self._read_stderr()

        reason = None
        if self._crash:
            m = _CODE.search(self._crash)
            reason = texts.maaend_crash_reason(m.group(1) if m else "")
        elif (now - self._pid_seen_at >= PLUGIN_GRACE_SECONDS
              and not any(n.lower() == GO_SERVICE for n, _ in procs)):
            if self._gone_since is None:
                self._gone_since = now
            elif now - self._gone_since >= GONE_CONFIRM_SECONDS:
                reason = texts.maaend_plugin_gone_reason(int(now - self._gone_since))
        else:
            self._gone_since = None
        if reason is None:
            idle = now - max(self._progress_at, self._pid_seen_at)
            if idle >= STALL_SECONDS:
                if self._lines == self._pid_lines:
                    # Not one line read for this MaaEnd: the log is missing, moved or
                    # unreadable, which says nothing about MaaEnd. Never kill on that.
                    return self._blind_alarm(pid, int(idle // 60))
                reason = texts.maaend_stall_reason(int(idle // 60), last_stamp[11:19] if last_stamp else "")
        if reason is None:
            return None
        return self._end(pid, procs, reason, now)

    # ---------------------------------------------------------------- effects

    def _blind_alarm(self, pid: int, minutes: int) -> "str | None":
        if pid in self._blind:
            return None
        self._blind.add(pid)
        log.warning("看门狗读不到 maafw.log：MaaEnd（PID %s）运行 %d 分钟，一行都没读到，不判卡死", pid, minutes)
        try:
            self.notifier.send(texts.MAAEND_WATCH_BLIND, texts.maaend_watch_blind_body(minutes), alert=True)
        except Exception:
            log.exception("看门狗读不到日志的报警没发出去")
        return texts.MAAEND_WATCH_BLIND

    def _end(self, pid: int, procs, reason: str, now: float) -> str:
        self._handled.add(pid)
        ok, why = self.kill(pid, "MaaEnd.exe")
        if ok:
            paths = self.plugin_paths()
            for name, p in procs:
                if name.lower() not in PLUGINS:
                    continue
                if not str(paths.get(p, "")).lower().startswith(self.agent_dir):
                    log.warning("%s（%s）不在 MaaEnd 的 agent 目录下（%s），不结束", name, p, paths.get(p, "读不到路径"))
                    continue
                done, w = self.kill(p, name)
                if not done:
                    log.warning("MaaEnd 的插件 %s（%s）没结束掉：%s", name, p, w)
        self._crash, self._gone_since, self._progress_at = "", None, now
        title = texts.MAAEND_STUCK_KILLED if ok else texts.MAAEND_STUCK_KILL_FAILED
        body = texts.maaend_stuck_body(reason, ok, why)
        log.warning("MaaEnd 卡死（PID %s）：%s；%s", pid, reason, "已结束" if ok else f"没结束成：{why}")
        try:
            self.notifier.send(title, body, alert=True)
        except Exception:
            log.exception("MaaEnd 卡死的报警没发出去")
        return title

    # ---------------------------------------------------------------- stderr

    def _stderr_now(self) -> "tuple[int, bytes]":
        try:
            with self.stderr.open("rb") as fh:
                head = fh.read(_HEAD_BYTES)
            return self.stderr.stat().st_size, head
        except OSError:
            return 0, b""

    def _read_stderr(self) -> None:
        """Read what go-service.stderr.log gained; start over when MaaEnd rewrote it."""
        try:
            size = self.stderr.stat().st_size
            with self.stderr.open("rb") as fh:
                head = fh.read(_HEAD_BYTES)
                if size < self._err_offset or not head.startswith(self._err_head):
                    self._err_offset = 0          # rewritten by a relaunched go-service
                fh.seek(self._err_offset)
                data = fh.read()
        except OSError:
            return
        self._err_offset += len(data)
        self._err_head = head
        if self._crash or not data:
            return
        for line in data.decode("utf-8", "replace").splitlines():
            if any(mark in line for mark in _CRASH_MARKS):
                self._crash = line.strip()
                log.warning("MaaEnd 的插件 go-service 崩溃，stderr 首行：%s", self._crash)
                return
