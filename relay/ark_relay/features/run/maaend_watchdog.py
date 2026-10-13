"""End MaaEnd.exe when it hangs, so AUTO-MAS judges and retries the run now.

When MaaEnd.exe exits, AUTO-MAS judges the run from MaaEnd's log at once:
unfinished tasks are retried, a finished run just closes. Without this, AUTO-MAS
ends MaaEnd only after 40 minutes without a log line.

Judged only while AUTO-MAS's runtime-snapshot says MaaEnd is exactly 「运行」
(no snapshot -> no judgment, no kill). Hung means one of:

  1. the plugin crashed: go-service.stderr.log gained `Exception 0x` /
     `panic:` / `fatal error`; or MaaEnd.exe has been seen for 3 minutes and
     go-service.exe is missing on two checks at least 60 s apart
  2. stalled: MaaEnd.exe alive and maafw.log without a new line for
     STALL_SECONDS (user-approved threshold, 2026-10-01 17:28)

Then only MaaEnd.exe is ended, plus its two plugins by their own PIDs - never
with `taskkill /T`: MaaEnd can launch Endfield.exe itself, so the game may sit
in MaaEnd's process tree, and the game is never killed here. One alarm per
MaaEnd PID, whether the kill worked or not.

No timer of its own: collect_watch's thread calls `tick` on every wake, at
least once a minute.

A MaaEnd that finished every task but does not exit (upstream MistEO/MXU#371)
is not judged here: AUTO-MAS v5.7.0-beta.2 ends it itself. Its _wait_maaend_stage
(app/task/MaaEnd/AutoProxy.py) watches MXU's log for 「kind: tasks-completed」,
records the result first (check_log), then terminates MaaEnd.exe, logging
「MaaEnd 队列已结束但进程未退出，正在中止脚本进程」. It ends MaaEnd.exe only, but
the two plugins are gone by then: MXU stops both agent processes as the queue
completes (mxu-tauri.log 2026-10-01 16:58:22 「Agent #0 child process exited」 /
「Agent #1 child process exited」, the hang of that day). The outcome check books
such a run (verdict._mark_no_self_exit).
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

from ark_relay.core import texts

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
# After taskkill said 「成功」, how long MaaEnd's PID is given to leave the process
# list before the machine check of the kill (#31) calls it still there; 「成功」
# alone is not taken as MaaEnd gone. Looked at on the next checks
# (CHECK_EVERY_SECONDS), never waited for here.
GONE_WAIT_SECONDS = 10
_CRASH_MARKS = ("Exception 0x", "panic:", "fatal error")
_CODE = re.compile(r"Exception (0x[0-9A-Fa-f]+)")
_HEAD_BYTES = 64


def _snapshot():
    from ark_relay.core.engine import _automas_snapshot  # noqa: PLC0415 - engine imports half the relay
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
    from ark_relay.features.preupdate.preupdate_common import _pwsh  # noqa: PLC0415 - the repo's one way to call PowerShell
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
                 active: "bool | None" = None, state_dir=None):
        self.notifier = notifier
        self.state_dir = state_dir      # where the machine check of a kill (#31) keeps its verdict
        self._killed: "dict | None" = None   # the last kill, until it is known whether MaaEnd went
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
            # number must get its own clocks and its own handled / blind marks.
            self._pid, self._gone_since = None, None
            self._handled.clear()
            self._blind.clear()
            return None
        if pid != self._pid:
            # A new MaaEnd: its own clocks, and the stderr file still holds the previous
            # run's text until go-service relaunches and rewrites it.
            self._pid, self._pid_seen_at, self._gone_since, self._crash = pid, now, None, ""
            self._pid_lines = self._lines
            self._err_offset, self._err_head = self._stderr_now()
        # one fault, one push: one hung MaaEnd, by its PID (forgotten once MaaEnd is gone)
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
        # one fault, one push: one MaaEnd whose log cannot be read, by its PID (forgotten once MaaEnd is gone)
        if pid in self._blind:
            return None
        self._blind.add(pid)
        # The group alarm first; the WARNING repeating it stays out of the group only
        # when that alarm really reached it (errwatch.group_pushed), as in _end.
        pushed = {}
        try:
            errs = self.notifier.send(texts.MAAEND_WATCH_BLIND, texts.maaend_watch_blind_body(minutes), alert=True)
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            pushed = errwatch.group_pushed(texts.MAAEND_WATCH_BLIND, errs, self.notifier)
        except Exception:
            log.exception("看门狗读不到日志的报警没发出去")
        log.warning("看门狗读不到 maafw.log：MaaEnd（PID %s）运行 %d 分钟，一行都没读到，不判卡死", pid, minutes,
                    extra=pushed)
        return texts.MAAEND_WATCH_BLIND

    def _end(self, pid: int, procs, reason: str, now: float) -> str:
        self._handled.add(pid)
        ok, why = self.kill(pid, "MaaEnd.exe")
        # Plugins left running (skipped or kill failed), in path form: the texts gate
        # refuses a bare English name or a PID.
        left = []
        if ok:
            paths = self.plugin_paths()
            for name, p in procs:
                if name.lower() not in PLUGINS:
                    continue
                if not str(paths.get(p, "")).lower().startswith(self.agent_dir):
                    log.warning("%s（%s）不在 MaaEnd 的 agent 目录下（%s），不结束", name, p, paths.get(p, "读不到路径"))
                    left.append(paths.get(p) or "agent\\" + name)
                    continue
                done, w = self.kill(p, name)
                if not done:
                    log.warning("MaaEnd 的插件 %s（%s）没结束掉：%s", name, p, w)
                    left.append("agent\\" + name)
        self._crash, self._gone_since, self._progress_at = "", None, now
        title = texts.MAAEND_STUCK_KILLED if ok else texts.MAAEND_STUCK_KILL_FAILED
        try:
            body = texts.maaend_stuck_body(reason, ok, why, left=left)
        except TypeError:
            # texts without the left= parameter (it arrives with 67e0873f): the alarm
            # still goes out, without the plugin names. Drop once that is on main.
            body = texts.maaend_stuck_body(reason, ok, why)
        # One hang, one group push: the ⚠️ group alarm, and the WARNING that follows
        # repeats it. errwatch.group_pushed keeps that WARNING out of the group only
        # when the ⚠️ send really reached the group robot, so the fault still reaches
        # the group once.
        pushed = {}
        try:
            errs = self.notifier.send(title, body, alert=True)
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            pushed = errwatch.group_pushed(title, errs, self.notifier)
        except Exception:
            log.exception("MaaEnd 卡死的报警没发出去")
        log.warning("MaaEnd 卡死（PID %s）：%s；%s", pid, reason, "已结束" if ok else f"没结束成：{why}",
                    extra=pushed)
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
            from ark_relay.features.selfcheck import machinecheck  # noqa: PLC0415
            from ark_relay.core.statestore import StateStore  # noqa: PLC0415
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
                # INFO: the same tick ends MaaEnd in _end, whose one group push names the crash and its code.
                log.info("MaaEnd 的插件 go-service 崩溃，stderr 首行：%s", self._crash)
                return
