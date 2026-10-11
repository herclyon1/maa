"""End MaaEnd.exe when it hangs, so AUTO-MAS judges and retries the run now.

When MaaEnd.exe exits, AUTO-MAS judges the run from MaaEnd's log at once:
unfinished tasks are retried, a finished run just closes. Without this, AUTO-MAS
ends MaaEnd only after 40 minutes without a log line.

Judged only while AUTO-MAS's runtime-snapshot says MaaEnd is exactly 「运行」
(no snapshot -> no judgment, no kill). Hung means one of:

  1. the plugin crashed: go-service.stderr.log gained `Exception 0x` /
     `panic:` / `fatal error`; or MaaEnd.exe has been seen for 3 minutes and
     go-service.exe is missing on two checks at least 60 s apart
  0. finished, did not exit: MaaEnd's own log says tasks-completed, no
     「自动执行任务完成，关闭自身」, and MaaEnd.exe still there NO_EXIT_SECONDS later.
     Before that kill MXU is asked once to stop (see below); the kill is only
     the fallback when that did not make it exit
  2. stalled: MaaEnd.exe alive and maafw.log without a new line for
     STALL_SECONDS (user-approved threshold, 2026-10-01 17:28)

Then only MaaEnd.exe is ended, plus its two plugins by their own PIDs - never
with `taskkill /T`: MaaEnd can launch Endfield.exe itself, so the game may sit
in MaaEnd's process tree, and the game is never killed here. One alarm per
MaaEnd PID, whether the kill worked or not.

No timer of its own: collect_watch's thread calls `tick` on every wake, at
least once a minute.

Finished but not exiting is upstream MistEO/MXU#371 (open, unanswered; the
installed MXU is v2.7.1, MaaEnd.exe FileVersion 2.7.1): with --quit-after-run
the frontend reads the backend 300 ms after 「tasks-completed」, the backend
still says running because stopping the two agents took longer
(mxu-tauri.log 2026-10-10 09:37:28 `maa_get_all_states called` while agent #0
only exited at 09:37:29), no later event comes, and the exit never fires.
Hangs: 10-06 09:51:51, 10-09 09:31:56, 10-10 09:37:28, each killed ~63 s later.
MXU's own way back: POST /api/maa/instances/<id>/tasks/stop on its local web
server (web_server.rs handle_stop_task -> stop_task_impl -> 「task-stopped」),
after which the frontend re-reads the state, sees not-running and exits. So at
the first check NUDGE_AFTER_SECONDS after tasks-completed the watchdog sends
that once (`_mxu_stop`). MaaEnd gone at a later check is a fault that fixed
itself: one WARNING marked errwatch.recovered() (daily report, not the group),
whose errwatch door writes one 「自愈待查」 red item to the technical log so a
session still looks at it (commit dae12439), plus machine check #31's PASS.
The same run's 「跑完没自己退出」 line from the outcome check follows suit (the
request's state is kept in StateStore marks, NUDGE_MARK, for
verdict._mark_no_self_exit), so one event is not half recovered, half pushed.
Still there, or the request failed, and it is killed as before, and that kill
is a fault for the group (its 「MaaEnd 卡死」 WARNING): the workaround did not
hold. That WARNING is the hang's one push: the kill is booked in NUDGE_MARK too
(failed / killed), and the outcome check's 🟠 line for the run then stays out
of the group (daily report and technical log still carry it).

Checked before relying on it (2026-10-10): the stop runs MaaFramework's
MaaTaskerPostStop, an EmptyTask whose run() always returns true (v5.14.2
Task/EmptyTask.h), so MXU prints 「任务开始: 停止任务」/「任务完成: 停止任务」
and never 「任务失败」 (real shape: tests/fixtures/maaend_stop_task_2026-10-08.log).
AUTO-MAS (task/MaaEnd/AutoProxy.py check_log) judges only once MaaEnd's stdout
ends and matches 「任务完成: X」 against its own task table, so the extra lines
change nothing there; 「任务失败: 停止任务」 would (a KeyError -> 「解析失败」 ->
retry), which is why it matters that the stop task cannot fail. stop_task_impl's
overall_status "Failed" only colours MXU's own dashboard. The relay's own
reading skips the marker (collector_maaend._maaend_round_closed).

The checks are only as frequent as the wakes (in practice up to a minute once
MaaEnd has gone quiet), so the real wait after the request is one wake, not
NUDGE_WAIT_SECONDS; the fallback kill never comes earlier than NO_EXIT_SECONDS
after tasks-completed. With two MaaEnd.exe up no request is sent (it reaches
an MXU by port, not by PID) and the kill comes as before.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from ark_relay.core import texts

log = logging.getLogger("ark.maaend_watchdog")

SCRIPT = "MaaEnd"                  # the script's name in AUTO-MAS's task_info
RUNNING = "运行"
MAAEND_EXE = "maaend.exe"
GO_SERVICE = "go-service.exe"
PLUGINS = (GO_SERVICE, "cpp-algo.exe")   # both live in <maaend>\agent\, started ~16 s after MaaEnd
STALL_SECONDS = 10 * 60
# Seconds after 「kind: tasks-completed」 before a MaaEnd that neither wrote
# 「自动执行任务完成，关闭自身」 nor exited is ended (normal runs exit within ~4 s).
NO_EXIT_SECONDS = 30
_MXU_LOG = re.compile(r"^\d{4}-\d\d-\d\d-\d+\.log$")
_MXU_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")
_MXU_COMPLETED = "kind: tasks-completed"
_MXU_CLOSING = "自动执行任务完成"
PLUGIN_GRACE_SECONDS = 3 * 60      # plugins are not up yet in MaaEnd's first seconds
GONE_CONFIRM_SECONDS = 60
CHECK_EVERY_SECONDS = 30           # MaaFW wakes the thread every ~2 s; tasklist need not follow
# After taskkill said 「成功」, how long MaaEnd's PID is given to leave the process
# list before the machine check of the kill (#31) calls it still there; 「成功」
# alone is not taken as MaaEnd gone. Looked at on the next checks
# (CHECK_EVERY_SECONDS), never waited for here.
GONE_WAIT_SECONDS = 10
# Ask MXU to stop (upstream #371, module docstring) at the first check this long
# after tasks-completed. Measured (relay2 status 10-01 20:35, 14 normal runs):
# MXU's closing line comes in the same second as tasks-completed and AUTO-MAS
# records the result 0.7-4.0 s later, so 10 s is past every normal exit.
NUDGE_AFTER_SECONDS = 10
# Then MaaEnd has this long to leave before a check calls the request a failure
# and kills it. Based on the same measured runs: a normal exit takes at most
# 4.0 s once MXU decides to quit, so 15 s leaves it room nearly four times over.
NUDGE_WAIT_SECONDS = 15
# An accepted request whose outcome was not seen within this long is dropped
# without a verdict (_verify_nudge): an exit much later is not its doing.
# Not measured: no request has run on the machine yet. Five of collect_watch's
# wakes (at least one a minute, module docstring) against an exit measured at
# 4.0 s at most (above); revisit once relay.log holds real requests.
NUDGE_FORGET_SECONDS = 5 * 60
# Where each stop request's fate is kept for the outcome check (StateStore marks,
# read by verdict._mark_no_self_exit): AUTO-MAS records the run 0.7-4.0 s after
# MaaEnd exits (measured above), well before the next check here sees the PID gone,
# so the outcome check must not wait for 「exited」. States: asked (accepted, no
# verdict yet), exited (_verify_nudge saw it go), failed (still there: killed in
# _end), killed (no accepted request, killed in _end), dropped
# (NUDGE_FORGET_SECONDS ran out). failed and killed both mean the watchdog's own
# 「MaaEnd 卡死」 WARNING has gone to the group. Only the newest NUDGE_KEEP are
# kept: one request per MaaEnd (_nudge_tried), and the outcome check reads a run's
# entry within minutes of that run, so the newest few always hold it.
NUDGE_MARK = "maaend_nudge"
NUDGE_KEEP = 8
# MXU's default port; it falls back to 12702 when that is held (mxu-tauri.log
# 2026-10-09 08:46:18 「Web server listening on http://127.0.0.1:12702 (fallback
# from default port 12701)」), so the port is read from its log (_mxu_port).
# The API and the hang: https://github.com/MistEO/MXU/issues/371
MXU_PORT = 12701
# Not measured: MXU's answer time has not been read on the machine yet. A local
# server; 5 s only bounds a hung one so the fallback kill still comes at the next
# wake (https://docs.python.org/3/library/urllib.request.html#urllib.request.urlopen).
MXU_HTTP_TIMEOUT = 5
_MXU_LISTEN = re.compile(r"Web server listening on http://127\.0\.0\.1:(\d+)")
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


def _mxu_port(debug_dir: Path) -> int:
    """The port MXU's web server bound, from its own log line; MXU_PORT when none is found.

    mxu-tauri.log rotates at 1 MB, and the line is written at start-up: on
    2026-10-10 the AUTO-MAS launch logged it at 09:14:21 and the file rotated at
    09:14:23, so the newest rotated file (mxu-tauri_<date>_<time>.log) is read
    when the live one has none.
    """
    debug_dir = Path(debug_dir)
    try:
        rotated = sorted(debug_dir.glob("mxu-tauri_*.log"), key=lambda p: p.stat().st_mtime)[-1:]
    except OSError:
        rotated = []
    for path in [debug_dir / "mxu-tauri.log", *rotated]:
        try:
            ports = _MXU_LISTEN.findall(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if ports:
            return int(ports[-1])
    return MXU_PORT


def _mxu_stop(debug_dir, opener=urllib.request.urlopen) -> "tuple[bool, str]":
    """POST tasks/stop to MXU's own web server once: (accepted, why not, in words for the alarm).

    The instance is the one MXU reports running, else its only one (the
    backend has usually stopped running by now - that is #371); several and
    none running is not guessed. MXU's own error text goes to the log.
    """
    base = f"http://127.0.0.1:{_mxu_port(debug_dir)}/api"
    try:
        with opener(urllib.request.Request(base + "/maa/state", method="GET"), timeout=MXU_HTTP_TIMEOUT) as r:
            state = json.loads(r.read().decode("utf-8", "replace") or "{}")
        insts = (state or {}).get("instances") or {}
        running = [k for k, v in insts.items() if isinstance(v, dict) and v.get("is_running")]
        ids = running or list(insts)
        if len(ids) != 1:
            log.info("MXU 报了 %d 套配置（在跑的 %d 套），不猜该停哪个：%s", len(insts), len(running), list(insts))
            return False, texts.MXU_STOP_WHICH
        req = urllib.request.Request(f"{base}/maa/instances/{urllib.parse.quote(ids[0], safe='')}/tasks/stop",
                                     data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with opener(req, timeout=MXU_HTTP_TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except OSError:
            detail = ""
        log.info("MXU 拒绝了停止请求：%s %s", e.code, detail)
        return False, texts.mxu_stop_refused(e.code)
    except (OSError, ValueError) as e:     # URLError, refused, timeout, a reply that is not JSON
        log.info("MXU 的本机网页服务没应答：%s", e)
        return False, texts.MXU_STOP_NO_ANSWER
    try:
        ok = json.loads(body or "{}").get("ok") is True
    except (ValueError, AttributeError):
        ok = False
    if not ok:
        log.info("MXU 回了停止请求但没说 ok：%s", body[:200])
        return False, texts.mxu_stop_refused(200)
    return True, ""


def _maaend_running(snap) -> bool:
    return any(str(i.get("name") or "") == SCRIPT and str(i.get("status") or "") == RUNNING
               for t in (snap or {}).get("tasks") or []
               for i in (t or {}).get("task_info") or [])


class Watchdog:
    """Pure state machine; everything outside (clock, snapshot, processes, kill) is injectable."""

    def __init__(self, notifier, debug_dir, *, clock=time.monotonic, snapshot=_snapshot,
                 processes=_tasklist, kill=_taskkill, plugin_paths=_plugin_paths,
                 wallclock=datetime.now, active: "bool | None" = None,
                 state_dir=None, nudge=None):
        self.notifier = notifier
        # The stop request of the no-exit rule; () -> (accepted, why not). None: MXU's own (_mxu_stop).
        self.nudge = nudge if nudge is not None else (lambda: _mxu_stop(self.debug_dir))
        self._nudged: "dict | None" = None      # the request that was accepted, until MaaEnd went or the wait ran out
        self._nudge_tried: set[int] = set()     # one request per MaaEnd, by PID
        self._nudge_why: "dict[int, str]" = {}  # PID -> why its request failed
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
        self._verify_nudge(now)

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
            self._nudge_tried.clear()
            self._nudge_why.clear()
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

        reason = self._no_exit(pid, procs, now)
        if reason == "":
            return None                 # asked MXU to stop: the next checks see whether it went
        no_exit = reason is not None
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
        return self._end(pid, procs, reason, now, no_exit)

    def _no_exit(self, pid: int, procs, now: float) -> "str | None":
        """The no-exit rule for this MaaEnd: a kill reason, "" while its stop request runs, None otherwise."""
        n = self._nudged
        if n is not None and n["pid"] == pid:
            # Asked to stop and still listed (_verify_nudge saw it): wait, then call it failed.
            # Judged on the request itself: MXU writes its closing line before exit(0),
            # so the log no longer says "completed without exit" once it is on its way.
            waited_n = int(now - n["at"])
            waited = int((self.wallclock() - n["done_wall"]).total_seconds())
            if waited_n < NUDGE_WAIT_SECONDS or waited < NO_EXIT_SECONDS:
                return ""
            self._nudged = None
            # Booked before the kill: MaaEnd leaving makes AUTO-MAS record the run within
            # seconds, and the outcome check must then read 「failed」, not 「asked」.
            self._nudge_book(n["done_wall"], pid, "failed")
            why = texts.maaend_nudge_no_exit(waited_n)
            self._machinecheck({"action": "nudge", "result": self._nudge_result(n, ok=True, gone=False,
                                                                                waited=waited_n, why=why)})
            return texts.maaend_no_exit_reason(n["done_at"], waited) + texts.maaend_nudge_failed(why)
        # Only a completion this MaaEnd logged: the newest log can still be the
        # previous attempt's - a hung one stops at tasks-completed with no closing
        # line (2026-10-01 16:58) - until the new MXU creates its own file.
        done_at = self._completed_without_exit()
        if done_at is None or done_at < self._pid_seen_wall:
            return None
        waited = int((self.wallclock() - done_at).total_seconds())
        hms = done_at.strftime("%H:%M:%S")
        if waited >= NUDGE_AFTER_SECONDS and pid not in self._nudge_tried:
            self._nudge_tried.add(pid)
            if sum(1 for name, _ in procs if name.lower() == MAAEND_EXE) > 1:
                # The request reaches an MXU by port, not by PID: with two MaaEnd.exe up
                # (10-09 / 10-10 08:46, the second bound 12702) it could stop the other
                # one's running tasks. The kill below is by PID and stays safe.
                log.info("开着 %d 个 MaaEnd，不发停止请求（分不清会停到哪一个）",
                         sum(1 for name, _ in procs if name.lower() == MAAEND_EXE))
                ok, why = False, texts.MXU_STOP_TWO
            else:
                try:
                    ok, why = self.nudge()
                except Exception:       # never let the workaround stop the kill behind it
                    log.exception("请 MaaEnd 停下的请求自己出错")
                    ok, why = False, texts.MXU_STOP_NO_ANSWER
            if ok:
                log.info("MaaEnd（PID %s）所有任务 %s 已完成，%d 秒仍没退出：已请它停一次（上游 MXU#371 的绕法）",
                         pid, hms, waited)
                self._nudged = {"pid": pid, "at": now, "after": waited, "done_at": hms, "done_wall": done_at}
                self._nudge_book(done_at, pid, "asked", after=waited)
                return ""
            self._nudge_why[pid] = why
            self._machinecheck({"action": "nudge", "result": {"pid": pid, "after": waited, "done_at": hms,
                                                               "ok": False, "gone": False, "waited": 0, "why": why}})
        if waited < NO_EXIT_SECONDS:
            return None
        reason = texts.maaend_no_exit_reason(hms, waited)
        if pid in self._nudge_why:
            reason += texts.maaend_nudge_failed(self._nudge_why[pid])
        # No accepted request, killed all the same: booked before the kill as above,
        # so the outcome check keeps its 🟠 line for this run out of the group (the
        # 「MaaEnd 卡死」 WARNING is the one push for this hang).
        self._nudge_book(done_at, pid, "killed", after=waited)
        return reason

    def _verify_nudge(self, now: float) -> None:
        """After an accepted stop request: is MaaEnd's PID gone? Then the workaround held -
        one recovered WARNING with the timings and machine check #31. Still listed is left
        to _no_exit (it kills once the wait is over); a list that cannot be read waits."""
        n = self._nudged
        if n is None:
            return
        if now - n["at"] > NUDGE_FORGET_SECONDS:
            # Nobody judged it in time (AUTO-MAS no longer 「运行」, or no snapshot):
            # whatever ends it later is not the request's doing, so it is not claimed.
            log.info("停止请求发出 %d 秒了，MaaEnd（PID %s）的去向没判出来，不再算在请求头上",
                     int(now - n["at"]), n["pid"])
            self._nudged = None
            self._nudge_book(n["done_wall"], n["pid"], "dropped")
            return
        procs = self.processes()
        if procs is None or any(p == n["pid"] and name.lower() == MAAEND_EXE for name, p in procs):
            return
        self._nudged = None
        gone_s = max(int(now - n["at"]), 0)
        # The fault (MaaEnd not exiting, upstream MXU#371) fixed itself on the request:
        # a WARNING marked recovered goes to the daily report as 自己好了, not to the
        # group, and errwatch's door for it writes one 「自愈待查」 red item to the
        # technical log so a session looks at it (techlog.self_heal, commit dae12439).
        # A request that failed or did not make it exit is killed in _no_exit / _end,
        # and that 「MaaEnd 卡死」 WARNING is pushed.
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        log.warning("%s（PID %s）", texts.maaend_nudged_exit(n["done_at"], n["after"], gone_s), n["pid"],
                    extra=errwatch.recovered())
        self._machinecheck({"action": "nudge", "result": self._nudge_result(n, ok=True, gone=True,
                                                                            waited=gone_s, why="")})
        self._nudge_book(n["done_wall"], n["pid"], "exited", gone=gone_s)

    def _nudge_book(self, done_wall: datetime, pid: int, state: str, **more) -> None:
        """Keep one stop request's state in StateStore marks (NUDGE_MARK), where the
        outcome check (verdict._mark_no_self_exit) matches it to the run by MXU's
        tasks-completed time. Never raises: the bookkeeping must not stop the kill."""
        if not self.state_dir:
            return
        try:
            from ark_relay.core.statestore import StateStore  # noqa: PLC0415
            store = StateStore(self.state_dir)
            done_at = done_wall.strftime("%Y-%m-%d %H:%M:%S")
            rows = [r for r in store.get("marks", NUDGE_MARK) or [] if isinstance(r, dict)]
            row = next((r for r in rows if r.get("done_at") == done_at and r.get("pid") == pid), None)
            if row is None:
                row = {"done_at": done_at, "pid": pid}
                rows.append(row)
            row.update(state=state, **more)
            store.set("marks", NUDGE_MARK, rows[-NUDGE_KEEP:])
        except Exception:
            log.exception("停止请求的结果没记下（结果核对会把这趟当没请过）")

    @staticmethod
    def _nudge_result(n: dict, **more) -> dict:
        """The #31 context of a stop request: plain values only (no datetime)."""
        return dict({k: v for k, v in n.items() if k != "done_wall"}, **more)


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
        # One MXU log per MaaEnd launch. MXU writes the closing line just before
        # tasks-completed, so any closing line in the file means it is exiting.
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

    def _end(self, pid: int, procs, reason: str, now: float, no_exit: bool = False) -> str:
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
        # One hang, one group push. A no-exit kill comes only after MXU was asked to
        # stop and did not leave (upstream MXU#371, _no_exit), so it means the
        # workaround did not hold; a successful one has its WARNING (pushed by
        # errwatch) as its only push. A crash / stall / plugin-gone, or a kill that did
        # not take, sends the ⚠️ group alarm, and the WARNING that follows repeats it:
        # errwatch.group_pushed keeps that WARNING out of the group only when the ⚠️
        # send really reached the group robot, so the fault still reaches the group once.
        warning_only = no_exit and ok
        pushed = {}
        if not warning_only:
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
                # INFO: the same tick (or the next, while a stop request runs) ends
                # MaaEnd in _end, whose one group push names the crash and its code.
                log.info("MaaEnd 的插件 go-service 崩溃，stderr 首行：%s", self._crash)
                return
