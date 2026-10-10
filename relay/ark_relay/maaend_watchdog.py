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
  0. finished, did not exit: MaaEnd's own log says tasks-completed, no
     「自动执行任务完成，关闭自身」, and MaaEnd.exe still there NO_EXIT_SECONDS later
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
from datetime import datetime
from pathlib import Path

from . import texts

log = logging.getLogger("ark.maaend_watchdog")

SCRIPT = "MaaEnd"                  # the script's name in AUTO-MAS's task_info
RUNNING = "运行"
MAAEND_EXE = "maaend.exe"
GO_SERVICE = "go-service.exe"
PLUGINS = (GO_SERVICE, "cpp-algo.exe")   # both live in <maaend>\agent\, started ~16 s after MaaEnd
STALL_SECONDS = 10 * 60
# Tasks all done but MaaEnd neither wrote 「自动执行任务完成，关闭自身」 nor exited
# (user 2026-10-01 20:35, D129). Normal runs go from 「kind: tasks-completed」 to
# the process gone in 0.7-4.0 s (14 runs 09-25..10-01, median 2.2 s, max 4.0 s
# on 09-25 13:53:59 -> 13:54:03.036); 3 x the max is 12 s, raised to the agreed
# floor of 30 s. The three that hung sat 29-40 minutes.
NO_EXIT_SECONDS = 30
_MXU_LOG = re.compile(r"^\d{4}-\d\d-\d\d-\d+\.log$")
_MXU_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")
_MXU_COMPLETED = "kind: tasks-completed"
_MXU_CLOSING = "自动执行任务完成"
PLUGIN_GRACE_SECONDS = 3 * 60      # plugins are not up yet in MaaEnd's first seconds
GONE_CONFIRM_SECONDS = 60
CHECK_EVERY_SECONDS = 30           # MaaFW wakes the thread every ~2 s; tasklist need not follow
# After taskkill said 「成功」, how long MaaEnd's PID is given to leave the process
# list before the machine check of the kill (#31) calls it still there. taskkill
# from this service (session 0) has been shown not to reach the game itself
# (echofarm._kill_on_desktop, 2026-09-09), so 「成功」 alone is not taken as MaaEnd
# gone. Looked at on the next checks (CHECK_EVERY_SECONDS), never waited for here.
GONE_WAIT_SECONDS = 10
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
                 wallclock=datetime.now, active: "bool | None" = None,
                 state_dir=None):
        self.notifier = notifier
        self.state_dir = state_dir      # where the machine check of a kill (#31) keeps its verdict
        self._killed: "dict | None" = None   # the last kill, until it is known whether MaaEnd went
        self.debug_dir = Path(debug_dir)
        self.wallclock = wallclock      # machine-local, the same clock MXU stamps its log with
        self.stderr = Path(debug_dir) / "go-service.stderr.log"
        # Plugins are only ended when they run from MaaEnd's own agent folder: the
        # names alone could belong to anything else on the machine.
        # Trailing separator, or <maaend>\agent2\ would pass as agent too.
        self.agent_dir = str(Path(debug_dir).parent / "agent").lower() + os.sep
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
        self._pid_seen_wall = datetime.max     # wall-clock moment this MaaEnd was first seen
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
        self._verify_kill(now)

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
            # number must get its own clocks, not this one's (or its handled or
            # blind mark: until 2026-10-06 the blind mark was kept, so a later
            # MaaEnd that drew the same PID and could not be read either was silent).
            self._pid, self._gone_since = None, None
            self._handled.clear()
            self._blind.clear()
            return None
        if pid != self._pid:
            # A new MaaEnd: its own clocks, and the stderr file still holds the previous
            # run's text until go-service relaunches and rewrites it.
            self._pid, self._pid_seen_at, self._gone_since, self._crash = pid, now, None, ""
            self._pid_lines = self._lines
            self._pid_seen_wall = self.wallclock()
            self._err_offset, self._err_head = self._stderr_now()
        # one fault, one push: one hung MaaEnd, by its PID (forgotten once MaaEnd is gone)
        if pid in self._handled:
            return None
        self._read_stderr()

        reason = None
        self_heal = False
        # Only a completion this MaaEnd logged: the newest log can still be the
        # previous attempt's - a hung one stops at tasks-completed with no closing
        # line (2026-10-01 16:58) - until the new MXU creates its own file.
        done_at = self._completed_without_exit()
        if done_at is not None and done_at >= self._pid_seen_wall:
            waited = int((self.wallclock() - done_at).total_seconds())
            if waited >= NO_EXIT_SECONDS:
                reason = texts.maaend_no_exit_reason(done_at.strftime("%H:%M:%S"), waited)
                self_heal = True
        if reason is not None:
            self._gone_since = None
        elif self._crash:
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
        return self._end(pid, procs, reason, now, self_heal)

    def _completed_without_exit(self) -> "datetime | None":
        """When the newest MXU log said tasks-completed with no closing line after it."""
        try:
            logs = [p for p in self.debug_dir.iterdir() if _MXU_LOG.match(p.name)]
            if not logs:
                return None
            newest = max(logs, key=lambda p: p.stat().st_mtime)
            text = newest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        # One MXU log per MaaEnd launch. MXU writes the closing line in the same
        # second as, and just before, tasks-completed (09-30 18:18:35), so any
        # closing line in the file means it is on its way out.
        if _MXU_CLOSING in text:
            return None
        done_at = None
        for line in text.splitlines():
            if _MXU_COMPLETED in line and (m := _MXU_STAMP.match(line)):
                try:
                    done_at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
        return done_at

    # ---------------------------------------------------------------- effects

    def _blind_alarm(self, pid: int, minutes: int) -> "str | None":
        # one fault, one push: one MaaEnd whose log cannot be read, by its PID (forgotten once MaaEnd is gone)
        if pid in self._blind:
            return None
        self._blind.add(pid)
        log.warning("看门狗读不到 maafw.log：MaaEnd（PID %s）运行 %d 分钟，一行都没读到，不判卡死", pid, minutes)
        try:
            self.notifier.send(texts.MAAEND_WATCH_BLIND, texts.maaend_watch_blind_body(minutes), alert=True)
        except Exception:
            log.exception("看门狗读不到日志的报警没发出去")
        return texts.MAAEND_WATCH_BLIND

    def _end(self, pid: int, procs, reason: str, now: float, self_heal: bool = False) -> str:
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
        # Every case is a plain WARNING (pushed). A kill for the no-exit reason (every
        # task done, just did not exit) that then took was daily-report-only until
        # 2026-10-10 as "healed itself"; why MaaEnd does not exit is not known and it
        # keeps happening, so it is pushed until that is fixed. That case sends no ⚠️
        # on top: the WARNING is its one push. A crash / stall / plugin-gone, or a kill
        # that did not take, also sends the ⚠️ group alarm.
        healed = self_heal and ok
        log.warning("MaaEnd 卡死（PID %s）：%s；%s", pid, reason, "已结束" if ok else f"没结束成：{why}")
        if not healed:
            try:
                self.notifier.send(title, body, alert=True)
            except Exception:
                log.exception("MaaEnd 卡死的报警没发出去")
        result = {"pid": pid, "reason": reason, "ok": ok, "why": why, "at": now}
        if ok:
            self._killed = result       # gone or not: the next checks look (_verify_kill)
        else:
            self._machinecheck({"action": "kill", "result": dict(result, gone=False, waited=0)})
        return title

    def _verify_kill(self, now: float) -> None:
        """After a kill taskkill called a success: is MaaEnd's PID really gone from the
        process list? Gone, or still there GONE_WAIT_SECONDS after the kill, goes to the
        machine check #31 with what was seen; a list that cannot be read is said as such."""
        k = self._killed
        if k is None:
            return
        procs = self.processes()
        waited = int(now - k["at"])
        if procs is not None and not any(p == k["pid"] and n.lower() == MAAEND_EXE for n, p in procs):
            gone = True
        elif waited >= GONE_WAIT_SECONDS:
            gone = None if procs is None else False
            if gone is False:
                log.warning("结束 MaaEnd（PID %s）的命令说成功了，过了 %d 秒它还在跑", k["pid"], waited)
        else:
            return
        self._killed = None
        self._machinecheck({"action": "kill", "result": dict(k, gone=gone, waited=waited)})

    def _machinecheck(self, ctx: dict) -> None:
        """Hand what the watchdog did to the machine checks (machinecheck.py, event
        「watchdog」). Never raises (judge logs a broken check as ERROR)."""
        if not self.state_dir:
            return
        try:
            from . import machinecheck  # noqa: PLC0415
            from .statestore import StateStore  # noqa: PLC0415
            machinecheck.judge(self.state_dir, "watchdog", ctx, notifier=self.notifier,
                               version=str(StateStore(self.state_dir).get("versions", "code") or ""))
        except Exception:
            log.exception("上机核对（看门狗那一步）自己出错，看门狗照常")

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
