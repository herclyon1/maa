"""End MaaEnd.exe when it hangs, so AUTO-MAS judges and retries the run now.

When MaaEnd.exe exits, AUTO-MAS judges the run from MaaEnd's log at once:
unfinished tasks are retried, a finished run just closes. Without this, AUTO-MAS
ends MaaEnd only after 40 minutes without a log line.

Judged only while AUTO-MAS's runtime-snapshot says MaaEnd is exactly 「运行」
(no snapshot -> no judgment, no kill). Hung means one of:

Then only MaaEnd.exe is ended, plus its two plugins by their own PIDs - never
with `taskkill /T`: MaaEnd can launch Endfield.exe itself, so the game may sit
in MaaEnd's process tree, and the game is never killed here. One alarm per
MaaEnd PID, whether the kill worked or not.

No timer of its own: collect_watch's thread calls `tick` on every wake, at
least once a minute.
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

from ark_relay.core import config, texts
from ark_relay.core.config import SERVER_TZ

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
# The one-time 「协议更新」 dialog (2026-11-20, #187): MaaEnd has no node for it, and each task
# waited 5 min 33 s and failed, 83 minutes for the 早班, with maafw.log writing all along (so the
# stall check never fired). MaaFW's OCR read the dialog once at each task's start, 1-2 s in
# (09:34:28, 09:40:03, 09:45:35 … in the rotated logs). Held: read, and read again
# AGREEMENT_AGAIN_SECONDS or more later - on 11-20 at 09:40:03, the second task's start. One
# read, or two on the same screen, is not enough; once anyone clicks 同意 the line stops.
# A task failing is not used: after a click it fails for its own reasons.
AGREEMENT_AGAIN_SECONDS = 60
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
    """End one PID, but only if it still carries `image` (no /T, see the module docstring)."""
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
    from ark_relay.features.preupdate import _pwsh  # noqa: PLC0415 - the repo's one way to call PowerShell
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
    from ark_relay.core.engine import _task_items  # noqa: PLC0415
    return any(str(i.get("name") or "") == SCRIPT and str(i.get("status") or "") == RUNNING
               for t in (snap or {}).get("tasks") or []
               for i in _task_items(t))


class Watchdog:
    """Pure state machine; everything outside (clock, snapshot, processes, kill) is injectable."""

    def __init__(self, notifier, debug_dir, *, clock=time.monotonic, snapshot=_snapshot,
                 processes=_tasklist, kill=_taskkill, plugin_paths=_plugin_paths,
                 active: "bool | None" = None, state_dir=None, wall=None):
        self.notifier = notifier
        self.state_dir = state_dir      # where the machine check of a kill (#31) keeps its verdict
        # Wall clock for the 「超时|MaaEnd|…」 mark (`clock` is monotonic): the machine's time,
        # which runwatch.retry_clock reads on SERVER_TZ.
        self.wall = wall or (lambda: datetime.now(tz=SERVER_TZ))
        self._killed: "dict | None" = None   # the last kill, until it is known whether MaaEnd went
        self.stderr = Path(debug_dir) / "go-service.stderr.log"
        # Plugins are only ended when they run from MaaEnd's own agent folder: the
        # names alone could belong to anything else on the machine.
        # Trailing separator, or <maaend>\agent2\ would pass as agent too.
        self.agent_dir = str(Path(debug_dir).parent / "agent").lower() + os.sep
        self.clock, self.snapshot, self.processes, self.kill = clock, snapshot, processes, kill
        self.plugin_paths = plugin_paths
        self.active = config.IS_WINDOWS if active is None else active
        now = clock()
        self._lines: "int | None" = None
        self._progress_at = now         # last time maafw.log gained a line (or MaaEnd was not running)
        self._last_check = float("-inf")
        self._pid: "int | None" = None
        self._pid_seen_at = now
        self._gone_since: "float | None" = None
        self._crash = ""                # first crash line of the current MaaEnd's plugin
        self._handled: set[int] = set()
        self._pid_lines: "int | None" = None   # lines_seen baseline for the current MaaEnd PID
        # lines_seen at the immediately preceding 30 s check ONLY when that check cleanly
        # observed no running MaaEnd (WAITING/DONE or no MaaEnd.exe); None initially, while
        # a PID is running, or after snap/processes returned None so a new PID can never
        # inherit an old PID's or pre-outage lines and get killed blind.
        self._checked_lines: "int | None" = None
        self._blind: set[int] = set()           # PIDs already reported as unreadable
        # Blocking dialogs (_dialog_held: 「协议更新」 and 「登录认证已失效」): when each
        # dialog's line was read (recorded on every tick, not only the 30 s look), counted for
        # the MaaEnd running since _dialog_since. Like every other kill here, one group alarm
        # per MaaEnd ended (holding back retries' ones would be a mute, which only the user decides).
        self._dialog_counts = {"agreement": 0, "logout": 0}
        self._dialog_sightings: dict[str, list[float]] = {"agreement": [], "logout": []}
        self._dialog_since = now
        # Start from now, like collect_watch does for maafw.log: an old crash in the
        # file belongs to a MaaEnd that is already gone.
        self._err_offset, self._err_head = self._stderr_now()

    # ---------------------------------------------------------------- the loop

    def tick(self, lines_seen: int, last_stamp: str, agreement_seen: int = 0, logout_seen: int = 0) -> "str | None":
        """One look. `lines_seen` / `last_stamp` / `agreement_seen` / `logout_seen` come from
        collect_watch.Watcher. Returns the title sent."""
        if not self.active:
            return None
        now = self.clock()
        for kind, count in (("agreement", agreement_seen), ("logout", logout_seen)):
            if count > self._dialog_counts[kind]:
                self._dialog_sightings[kind].append(now)
            self._dialog_counts[kind] = count
        if lines_seen != self._lines:
            self._lines, self._progress_at = lines_seen, now
        if now - self._last_check < CHECK_EVERY_SECONDS:
            return None
        # What was read since the previous look belongs to whichever MaaEnd runs now when none
        # was running before; bounded to CHECK_EVERY_SECONDS (< AGREEMENT_AGAIN_SECONDS) so a
        # brand-new PID can never inherit an old sighting and die on its first check.
        since_last = self._last_check
        self._last_check = now
        self._verify_kill(now)

        snap = self.snapshot()
        if snap is None:
            self._checked_lines = None
            return None                 # cannot tell what AUTO-MAS is doing: never kill blind
        if not _maaend_running(snap):
            # Waiting or done: the 10 minutes start over once it is 「运行」 again.
            self._progress_at, self._gone_since = now, None
            self._checked_lines = lines_seen
            self._dialog_reset(now, drop_all=True)
            return None
        procs = self.processes()
        if procs is None:
            self._checked_lines = None
            return None
        pid = next((p for n, p in procs if n.lower() == MAAEND_EXE), None)
        if pid is None:
            # Forget it: Windows reuses PIDs, and a later MaaEnd that drew the same
            # number must get its own clocks and its own handled / blind marks.
            self._pid, self._gone_since = None, None
            self._checked_lines = lines_seen
            self._handled.clear()
            self._blind.clear()
            self._dialog_reset(now, drop_all=True)
            return None
        if pid != self._pid:
            # A new MaaEnd: its own clocks, and the stderr file still holds the previous
            # run's text until go-service relaunches and rewrites it. Never carry an old PID's
            # dialog sightings onto a new PID. Inherit the previous 30 s check's line count
            # only when that check cleanly observed no running MaaEnd and prev_pid is None;
            # after an in-window PID swap, startup, or snap/procs=None outage, start from
            # self._lines so lines from an earlier PID can never cause a blind kill.
            prev_pid = self._pid
            self._pid, self._pid_seen_at, self._gone_since, self._crash = pid, now, None, ""
            clean_idle = prev_pid is None and self._checked_lines is not None
            self._pid_lines = self._checked_lines if clean_idle else self._lines
            baseline = max(since_last, now - CHECK_EVERY_SECONDS) if (
                clean_idle and since_last != float("-inf")) else now
            self._dialog_reset(baseline)
            self._err_offset, self._err_head = self._stderr_now()
        self._checked_lines = None
        if self._starting(procs):
            # The relay's helper is starting Endfield through the official launcher
            # (gameupdate/efstart.py, for the relay's own retries): no task has started,
            # so no plugin and no log line yet, and that is not a hang. The clocks start
            # when the helper is done. AUTO-MAS's own launcher start (v5.7.0-beta.4) runs
            # before MaaEnd is started, so it never shows up here.
            self._pid_seen_at = self._progress_at = now
            self._gone_since = None
            return None
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
            if self._dialog_held("logout"):
                reason = texts.maaend_logged_out_reason()
            elif self._dialog_held("agreement"):
                reason = texts.maaend_agreement_reason()
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

    def _dialog_reset(self, since: float, *, drop_all: bool = False) -> None:
        """A new MaaEnd, or none running: keep only sightings from `since` on (or none at all)."""
        self._dialog_since = since
        for kind in self._dialog_sightings:
            self._dialog_sightings[kind] = [] if drop_all else [t for t in self._dialog_sightings[kind] if t >= since]

    def _dialog_held(self, kind: str) -> bool:
        """Is this MaaEnd held at dialog `kind`: read, and read again AGREEMENT_AGAIN_SECONDS or more later?"""
        seen = [t for t in self._dialog_sightings[kind] if t >= self._dialog_since]
        return bool(seen) and seen[-1] - seen[0] >= AGREEMENT_AGAIN_SECONDS

    def _starting(self, procs) -> bool:
        try:
            from ark_relay.features.efstart import helper_alive  # noqa: PLC0415 - pulls the desktop code
            return helper_alive(self.state_dir, procs)
        except Exception:  # never in the watchdog's way; without it the old behaviour holds
            log.debug("看门狗：读不了开游戏助手的状态", exc_info=True)
            return False

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
            from ark_relay.features import errwatch  # noqa: PLC0415
            pushed = errwatch.group_pushed(texts.MAAEND_WATCH_BLIND, errs, self.notifier)
        except Exception:
            log.exception("看门狗读不到日志的报警没发出去")
        log.warning("看门狗读不到 maafw.log：MaaEnd（PID %s）运行 %d 分钟，一行都没读到，不判卡死", pid, minutes,
                    extra=pushed)
        return texts.MAAEND_WATCH_BLIND

    def _end(self, pid: int, procs, reason: str, now: float) -> str:
        self._handled.add(pid)
        ok, why = self.kill(pid, "MaaEnd.exe")
        if ok:
            from ark_relay.features.maa_start_watchdog import mark_restart  # noqa: PLC0415
            mark_restart(self.state_dir, "MaaEnd", self.wall())
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
        self._dialog_reset(now, drop_all=True)
        title = texts.MAAEND_STUCK_KILLED if ok else texts.MAAEND_STUCK_KILL_FAILED
        body = texts.maaend_stuck_body(reason, ok, why, left=left)
        # One hang, one group push: the ⚠️ group alarm, and the WARNING that follows
        # repeats it. errwatch.group_pushed keeps that WARNING out of the group only
        # when the ⚠️ send really reached the group robot, so the fault still reaches
        # the group once.
        pushed = {}
        try:
            errs = self.notifier.send(title, body, alert=True)
            from ark_relay.features import errwatch  # noqa: PLC0415
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
            from ark_relay.features import machinecheck  # noqa: PLC0415
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
