"""The AUTO-MAS processes as tasklist and OpenProcess see them: the Electron shell, the Python backend and its handle, an installer running.
"""
from __future__ import annotations

import sys as _sys
import subprocess
import boot_stages
import logging
import time
try:
    import win32api
    import win32con
    import win32file
    import win32event
except ImportError:
    win32api = win32con = win32file = win32event = None  # type: ignore[assignment]
from pathlib import Path
from ark_relay.core.config import atomic_write_bytes, SERVER_TZ
from datetime import datetime, timedelta
from ark_relay.features import procwatch, procwatch as wmi_diag, procwatch as shutdown_signs
from ark_relay.core import texts
automas_keeper = _sys.modules[__name__]
day_roll = _sys.modules[__name__]
dirwatch = _sys.modules[__name__]

# Processes whose presence vetoes any revival outright.
INSTALLER_HINTS = (b"auto-mas-setup", b"unins")


# OpenProcess right that lets GetExitCodeProcess read the backend's exit code
# (PROCESS_QUERY_LIMITED_INFORMATION; not every win32con build names it).
_QUERY_LIMITED = 0x1000


def _automas_shell_running() -> bool:
    """True if the Electron shell is up, whatever the backend is doing."""
    return boot_stages.shell_running()


def _installer_running() -> "bool | None":
    """True while a setup or uninstaller is on screen (never touch it); None when
    the process list cannot be read.

    None used to be True, and _revive then logged 「安装程序正在运行」 for a list
    it had not read - the "cannot tell" read as a definite answer that procs.py
    records (three weeks blind). The caller still keeps its hands off on None,
    but says why."""
    out = _tasklist()
    if out is None:
        return None
    return any(h in out for h in INSTALLER_HINTS)


def is_backend(cmd: str) -> bool:
    """True if a python.exe command line is AUTO-MAS's backend: main.py run from under the
    install root's \\automas\\ directory.
    """
    low = (cmd or "").lower().replace("/", "\\")
    return "main.py" in low and "\\automas\\" in low


def _python_processes() -> "list[tuple[int, str]] | None":
    """(pid, command line) of every python.exe, or None when the query itself failed. See procs.py."""
    from ark_relay.core import desktop as procs  # noqa: PLC0415
    return procs.python_processes()


def _automas_running() -> bool:
    """True if AUTO-MAS's Python backend is up.

    Checks the backend rather than the Electron shell: the shell can sit there
    perfectly happily with a dead backend, which is precisely the state the
    machine was found in - the UI looked fine and nothing was scheduling runs.

    When the process list cannot be read at all, the API answers instead: an
    answering API is a live backend by definition, and a silent one is not
    assumed alive any more (that assumption is what blinded the keeper, see
    _python_processes).
    """
    procs = _python_processes()
    if procs is None:
        from ark_relay.features import commands  # noqa: PLC0415
        return commands.mas_up()
    return any(is_backend(cmd) for _, cmd in procs)


def _automas_handle():
    """A waitable handle on the AUTO-MAS backend, or None if it is not up.

    Waiting on the process itself replaces asking every two minutes whether it
    is still there. Windows signals the handle the instant the process exits,
    so a backend that dies at 09:05 is revived at 09:05 rather than at 09:07 -
    and in between, the relay is not doing anything at all.
    """
    for pid, cmd in (_python_processes() or []):
        if not is_backend(cmd):
            continue
        # With the query right as well, its exit code can be read when it goes
        # (_exit_code); without it only the exit itself is visible.
        for access in (lambda: win32con.SYNCHRONIZE | _QUERY_LIMITED, lambda: win32con.SYNCHRONIZE):
            try:
                return win32api.OpenProcess(access(), False, pid)
            except Exception:  # noqa: BLE001
                continue
        # This pid could not be opened (gone since the query, or refused): the
        # next match may be the live backend, so it is tried too.
    return None


def _exit_code(handle) -> "int | None":
    """The exited backend's exit code, None where it cannot be read."""
    try:
        import win32process  # noqa: PLC0415
        return int(win32process.GetExitCodeProcess(handle))
    except Exception:  # noqa: BLE001 - evidence only; never stops the revival
        return None


def _tasklist() -> "bytes | None":
    """`tasklist /NH`, lowercased; None when it could not be run."""
    try:
        return subprocess.run(["tasklist", "/NH"], capture_output=True,
                              timeout=25).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return None


# AUTO-MAS's own interpreter, under its install folder (cfg.automas_dir, D:\ark\automas).
SITE_PACKAGES = ("runtime", "environment", "venv", "Lib", "site-packages")
FILES = ("zz_automas_job_fix.py", "zz_automas_job_fix.pth", "zz_automas_ld_adb.py", "zz_automas_ld_adb.pth")
_PAYLOAD = Path(__file__).with_name("automas_files")


def payload(name: str) -> bytes:
    """The bytes the relay keeps for one of FILES."""
    return (_PAYLOAD / f"{name}.txt").read_bytes()


def site_dir(automas_dir) -> Path | None:
    """AUTO-MAS's venv site-packages; None with no AUTO-MAS folder or no such directory."""
    if not automas_dir:
        return None
    p = Path(automas_dir).joinpath(*SITE_PACKAGES)
    return p if p.is_dir() else None


def heal(automas_dir) -> list[str]:
    """Put back each of FILES that is missing or differs; the names put back, [] when all
    were right or there is no site-packages to put them in.

    A file already right is not written (not even its mtime touched). Raises OSError when a
    write fails or the file read back differs from the payload: the fallback is then not in
    place and the caller says so."""
    site = site_dir(automas_dir)
    if site is None:
        return []
    put: list[str] = []
    for name in FILES:
        want, dest = payload(name), site / name
        try:
            if dest.read_bytes() == want:
                continue
        except OSError:
            pass          # missing (or unreadable): written below
        atomic_write_bytes(dest, want)
        if dest.read_bytes() != want:
            raise OSError(f"{dest} 写进去读回来不一样")
        put.append(name)
    return put


# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.
log = logging.getLogger("ark.service")


class _DayRoll:
    """Local midnight in the main loop: put back the queue-command skips of the day before.

    The boot restore (gameupdate.boot_check) only runs at boot, so on a machine
    left on for days a skip a phone queue command made would keep that weekday
    off the queue item. cap_wait makes the loop wake just past midnight; check
    runs the put-back on the first wake of a new day, and again on later wakes
    while one is still open (AUTO-MAS not answering at midnight).
    """

    def __init__(self, cfg, log, now: datetime | None = None):
        self.cfg, self.log = cfg, log
        self.day = (now or datetime.now(tz=SERVER_TZ)).date()
        # True: the first check also puts back earlier days' holds. A relay restart
        # (not a reboot) skips boot_check's restore - gameupdate.should_run is once
        # per machine boot - and the put-back only touches earlier days' records.
        self.pending = True

    # While a put-back is still open (AUTO-MAS did not answer), the loop wakes at
    # least this often to try again: 「下次醒来再试」 meant the next alarm, up to
    # the hour-long backstop (清单-1108 A-04). The keeper's own beat for a silent
    # AUTO-MAS (procwatch.AUTOMAS_CHECK_SECONDS), not a new number.
    RETRY_S = float(procwatch.AUTOMAS_CHECK_SECONDS)

    def cap_wait(self, wait_s: float, now: datetime | None = None) -> float:
        now = now or datetime.now(tz=SERVER_TZ)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        wait_s = min(wait_s, max((midnight - now).total_seconds() + 1, 1.0))
        if self.pending and getattr(self.cfg, "state_dir", None):
            wait_s = min(wait_s, self.RETRY_S)
        return wait_s

    def _backfill_logs(self, now: datetime) -> None:
        """The first round after the relay starts and the first one of each new day: past
        days' logs COS lacks go up on a thread of their own (error_evidence.backfill_step)."""
        if not getattr(self.cfg, "state_dir", None):
            return
        try:
            from ark_relay.features import evidence as error_evidence  # noqa: PLC0415
            error_evidence.backfill_step(self.cfg, now)
        except Exception:
            self.log.exception("补传前几天日志这一步没起来，下次醒来再试")

    def check(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(tz=SERVER_TZ)
        self._backfill_logs(now)
        if now.date() != self.day:
            self.day, self.pending = now.date(), True
        if not self.pending or not getattr(self.cfg, "state_dir", None):
            return []
        try:
            from ark_relay.features import gameupdate  # noqa: PLC0415
            done, self.pending = gameupdate.restore_queue_skips_new_day(self.cfg.state_dir, now)
        except Exception:
            self.log.exception("过了零点改回队列跳过时出错，下次醒来再试")
            return []
        if done:
            self.log.info("游戏更新：过了零点，前一天按指令在队列里跳过的改回了：%s", "、".join(done))
        return done


# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.


class _DirWatch:
    """Change notifications for AUTO-MAS's history directory: arming, rebuilding and re-arming all live here.

Wake on the directory changing, not on a timer. AUTO-MAS writes a run record
    the moment a script finishes, and Windows will say so; asking every thirty
    seconds instead was just the lazy way to find out.

The loop's timeout stays, because some of what tick() does is genuinely
    time-based - the report cutoff, "a queue was due and produced nothing", the
    shutdown window - and none of those are announced by a file appearing.
    So: whichever comes first, a change or the interval.
    """

    def __init__(self, cfg, notifier, log):
        self.cfg, self.notifier, self.log = cfg, notifier, log
        self.handle = None
        self.lost_since = None     # monotonic time the watch was lost; None while armed
        self.lost_why = ""
        self.lost_told = False     # this loss reached OUTAGE_ALARM_SECONDS and was pushed
        try:
            if cfg.history_dir:
                self.handle = win32file.FindFirstChangeNotification(
                    str(cfg.history_dir), True,   # True = include subdirectories
                    win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                    | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
                log.info("已挂上目录变更通知，记录一落盘立即处理")
        except Exception as exc:  # decided by maybe_rebuild
            self._lost(exc)
            log.info("目录变更通知挂载失败，先退回定时检查，稍后自动重试", exc_info=True)
            self.handle = None
        # The rebuild cadence. Failing to arm at boot (because the directory is
        # not ready yet, say) has to enter the retry path as well - not only the
        # "re-arming failed" path.
        self.retry_at = time.monotonic() + 5.0
        self.retry_delay = 5.0

    def maybe_rebuild(self) -> None:
        """Rebuild with backoff once the watch has dropped. After a successful rebuild, run records are processed the moment they land again."""
        if self.handle is not None or not self.cfg.history_dir:
            return
        if time.monotonic() < self.retry_at:
            return
        try:
            self.handle = win32file.FindFirstChangeNotification(
                str(self.cfg.history_dir), True,
                win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
            self.retry_delay = 5.0
        except Exception as exc:  # noqa: BLE001 - a failed rebuild just waits longer
            self.handle = None
            self.retry_delay = min(self.retry_delay * 2, 60.0)
            self._lost(exc)
            self._still_lost()
        else:
            self._rebuilt()
        self.retry_at = time.monotonic() + self.retry_delay

    def cap_wait(self, wait_s: float) -> float:
        """While the watch is lost, the loop wakes for the next rebuild (retry_at) and,
        with no change notification to wake it, at least every poll_seconds to look
        for run records - what 「退回定时检查」 and 「5 秒后重建」 promise. Without
        it the loop slept to the next alarm or the hour-long backstop (清单-1108 A-04)."""
        if self.handle is not None or not self.cfg.history_dir:
            return wait_s
        poll = float(getattr(self.cfg, "poll_seconds", 300) or 300)
        return min(wait_s, poll, max(self.retry_at - time.monotonic(), 1.0))

    def _lost(self, exc: BaseException) -> None:
        """Note the start of a loss (a later failure keeps the first one's time and reason)."""
        if self.lost_since is None:
            self.lost_since = time.monotonic()
            self.lost_why = f"{type(exc).__name__}: {exc}"

    def _rebuilt(self) -> None:
        """Armed again: a loss the relay got over by itself goes to the daily report only."""
        since, self.lost_since = self.lost_since, None
        told, self.lost_told = self.lost_told, False
        if since is None:
            self.log.info("目录变更通知已重建，恢复「记录一落盘立即处理」")
            return
        # Already pushed meanwhile (told): one fault, one push - this end is daily only.
        from ark_relay.features import errwatch  # noqa: PLC0415
        self.log.warning("目录变更通知断过 %s，已经自己重建，跑完的结果又能马上处理了%s\n原因：%s",
                         wmi_diag._span(time.monotonic() - since), "（期间报过群）" if told else "",
                         self.lost_why, extra=errwatch.recovered() if told else None)

    def _still_lost(self) -> None:
        """A rebuild failed: INFO until the loss reaches OUTAGE_ALARM_SECONDS, then the
        group alarm once, and INFO for every failed rebuild after it - one fault, one
        push. Until 2026-10-13 those were WARNINGs, which errwatch pushes: about 50 an
        hour after the one alarm, each with different numbers so none merged (audit
        s15 #2). The end of the loss is still said (_rebuilt, stopping)."""
        down = time.monotonic() - (self.lost_since or time.monotonic())
        if self.lost_told:
            self.log.info("目录变更通知重建失败，%.0f 秒后再试（已经断了 %s）",
                             self.retry_delay, wmi_diag._span(down))
        elif down >= procwatch.OUTAGE_ALARM_SECONDS:
            self.lost_told = True
            self.log.info("目录变更通知断了 %s 还没重建（%s），报到群里", wmi_diag._span(down), self.lost_why)
            self.notifier.send(texts.WATCH_LOST, texts.watch_lost_body(), alert=True)
        else:
            self.log.info("目录变更通知重建失败（%s），%.0f 秒后再试；重建好了报到群里（断开的原因还没查清），"
                          "%d 分钟还没重建报到群里", self.lost_why, self.retry_delay,
                          procwatch.OUTAGE_ALARM_SECONDS // 60)

    def stopping(self) -> None:
        """The service is stopping with the watch still lost and not yet pushed: not recovered, a WARNING."""
        if self.lost_since is not None and not self.lost_told:
            self.lost_told = True
            self.log.warning("目录变更通知断了 %s，到中继停下时还没重建（%s）",
                             wmi_diag._span(time.monotonic() - self.lost_since), self.lost_why)

    def rearm(self) -> None:
        """Re-arm immediately after a notification, then give the writer a moment.

        Re-arm before handling, so a write that lands while we work is not lost.
        A record that appears during tick() would otherwise wait for the timeout
        - the exact latency this removes.

        Re-arming can fail, and it used to fail silently: the handle then never
        signals again, the loop falls back to waking only on the alarm clock,
        and run records sit unprocessed until the next clock-based deadline - up
        to the hour-long backstop. Everything still happens, just late and with
        no indication why. Degrading quietly is the failure mode this system has
        been bitten by most, so it is said out loud - once it is known whether
        the rebuild 5 seconds later fixed it (maybe_rebuild): the daily report
        when it did, the group when it is still lost after OUTAGE_ALARM_SECONDS.
        """
        try:
            win32file.FindNextChangeNotification(self.handle)
        except Exception as exc:  # decided by maybe_rebuild
            self._lost(exc)
            self.log.info("目录变更通知重新武装失败，改用闹钟兜底，5 秒后重建；重建好了报到群里（断开的原因还没查清），"
                          "%d 分钟还没重建报到群里", procwatch.OUTAGE_ALARM_SECONDS // 60, exc_info=True)
            self.close()
            self.retry_at = time.monotonic() + 5.0
            self.retry_delay = 5.0
        # AUTO-MAS writes the .json and .log separately; give it a
        # moment so the first notification does not read a half-file.
        time.sleep(2)

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            win32file.FindCloseChangeNotification(self.handle)
        except Exception:  # noqa: BLE001
            pass
        self.handle = None


# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.


def _loop(svc, cfg, engine, notifier, inbox, collect, deferred_inbox, log) -> None:
    """The main loop: wait for an event or an alarm, run tick, revive AUTO-MAS.

    Four things can wake it, and none of them is a timer: the service being
    stopped, a run record landing on disk, the AUTO-MAS backend exiting, and a
    python.exe starting. The timeout is not an "interval" either, it is an alarm
    clock - the engine knows the moment at which the next purely time-based
    decision changes (a missed-run alert falling due, the daily report cutoff,
    the boot checkpoint), and the loop sleeps until exactly that moment. Local
    midnight is one such moment too (_DayRoll: the queue-command skips end).
    """
    watch = dirwatch._DirWatch(cfg, notifier, log)
    keeper = automas_keeper._AutomasKeeper(log, notifier)
    dayroll = day_roll._DayRoll(cfg, log)
    # If every alarm is far away (or there are none), still wake
    # occasionally: an alarm-clock with a bug in it must degrade into
    # lateness, not into a relay that sleeps forever.
    backstop = 3600.0
    last_alarm_note = ""
    next_inbox_retry = 0.0
    while True:
        watch.maybe_rebuild()

        handles = [svc.stop_event, keeper.proc_evt]
        proc_idx = 1
        watch_idx = automas_idx = -1
        if watch.handle:
            handles.append(watch.handle); watch_idx = len(handles) - 1
        if keeper.handle:
            handles.append(keeper.handle); automas_idx = len(handles) - 1

        wait_s = backstop
        try:
            if alarm := engine.next_deadline():
                due, why = alarm
                # +1s so the wake lands just past the moment, not just short.
                remain = (due - datetime.now(tz=SERVER_TZ)).total_seconds() + 1
                wait_s = min(max(remain, 1.0), backstop)
                note = f"{due:%H:%M} {why}"
                if note != last_alarm_note:
                    last_alarm_note = note
                    log.info("下一个闹钟 %s", note)
        except Exception:
            log.exception("计算下一个时刻出错，退回备用间隔")
        wait_s = keeper.cap_wait(wait_s)
        wait_s = dayroll.cap_wait(wait_s)
        wait_s = watch.cap_wait(wait_s)
        if not inbox.last_fetch_ok:
            wait_s = min(wait_s, 300)   # wake in time for the fetch retry

        rc = win32event.WaitForMultipleObjects(
            handles, False, int(wait_s * 1000))
        fired = _fired(handles, rc)
        if 0 in fired:
            log.info("收到停止信号，退出")
            keeper.stopping()     # what has not recovered by now is pushed
            watch.stopping()
            watch.close()
            return
        if proc_idx in fired:
            keeper.on_process_started()
        if watch.handle and watch_idx in fired:
            watch.rearm()

        # Scripts have just stopped: apply the config commands that were deferred,
        # now that a write will not be clobbered - before tick, whose decisions
        # (the shift's power-off above all) must see them: a 「下次跑完不关机」 or
        # debug order sent during the shift landed only after tick had powered
        # the machine off (清单-1108 A-05).
        if deferred_inbox[0] and not engine.scripts_running():
            log.info("脚本已停，补做之前推迟的待办检查")
            collect("推迟补做")

        try:
            engine.tick()
        except Exception:
            log.exception("本轮处理出错，继续")
        dayroll.check()

        # A 「暂停」 command that never got downloaded is the same as no command
        # at all - so a failed fetch has to be retried, every 5 minutes. One
        # failure must not be read as "nobody issued a command today".
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_loop」
        if not inbox.last_fetch_ok and time.monotonic() >= next_inbox_retry:
            next_inbox_retry = time.monotonic() + 300
            collect("重试")

        keeper.check(bool(keeper.handle) and automas_idx in fired, time.monotonic())


def _fired(handles: list, rc: int) -> "set[int]":
    """Every handle that is signaled now, by index. WaitForMultipleObjects names only
    the lowest one; a run record landing in the same moment as a python.exe start
    left the change notification signaled and not re-armed, and an AUTO-MAS exit
    behind either went unseen until a later wake (清单-1108 A-04). An auto-reset
    event looked at here is consumed, which is right: it is handled now."""
    first = rc - win32event.WAIT_OBJECT_0
    out = {first} if 0 <= first < len(handles) else set()
    for i, h in enumerate(handles):
        if i in out:
            continue
        try:
            if win32event.WaitForSingleObject(h, 0) == win32event.WAIT_OBJECT_0:
                out.add(i)
        except Exception:  # noqa: BLE001 - a handle closed meanwhile is not signaled
            continue
    return out


# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.


REVIVE_FIRST_WAIT = 180


REVIVE_MAX_WAIT = 1800


# After this many failed revivals in a row, tell the operator. Before this
# alert existed, a backend that refused to come back was discovered only by
# the runs it failed to schedule.
REVIVE_ALERT_AFTER = 3


# How long a live Electron shell with no backend behind it may sit before we are
# allowed to force-kill it. 15 minutes, because the first-run environment wizard
# (installing Python, pip and git, then cloning the backend) legitimately spends
# several minutes with no backend and looks exactly like being stuck.
# 来龙去脉见 docs/CODE-HISTORY.md「service.py:(模块级)」
SHELL_GRACE_SECONDS = 900


EXIT_BEFORE_SHUTDOWN_SECONDS = 60.0


# After such an exit the backend is not revived while the shutdown runs; if the machine
# is still up this long after the exit (the shutdown did not happen), the exit is
# handled as an unexpected one from then on.
SHUTDOWN_NO_SHOW_SECONDS = 180.0
# A backend process is held only when its API answers (_confirm): until then the
# revival state is not reset, so a backend that starts and never serves (its port
# still held by a leftover process) keeps counting towards REVIVE_ALERT_AFTER
# instead of starting from zero at every attempt (清单-1108 A-06). The loop asks
# again on the keeper's own liveness beat (procwatch.AUTOMAS_CHECK_SECONDS); one that
# has not answered after the first revival wait (REVIVE_FIRST_WAIT) since its process
# appeared is a WARNING (pushed) once. No new numbers: both are the keeper's own.
API_RECHECK_SECONDS = float(procwatch.AUTOMAS_CHECK_SECONDS)
API_GRACE_SECONDS = float(REVIVE_FIRST_WAIT)


def _api_up() -> bool:
    """Whether the AUTO-MAS backend API answers (commands.mas_up)."""
    from ark_relay.features import commands  # noqa: PLC0415
    return commands.mas_up()


class _AutomasKeeper:
    """Keeping the AUTO-MAS backend alive: hold the handle, detect absence, revive with backoff, alert after repeated failures.

Two of the four things that can wake the loop live here: the backend dying,
    and a python.exe starting (so a freshly launched backend gets its handle
    immediately instead of at the next liveness check).
    """

    # Class defaults as well as set in __init__: tests build a keeper with __new__.
    hold_said = None
    api_since = None     # monotonic time a held backend's API was first found silent
    api_warned = False

    def __init__(self, log, notifier):
        self.log, self.notifier = log, notifier
        self.handle = _automas_handle()
        if self.handle:
            log.info("已挂上 AUTO-MAS 进程句柄，它一退出立即拉起")
        self.proc_evt = win32event.CreateEvent(None, 0, 0, None)
        # True before the listener starts, not after: its thread can find the
        # subscription broken (and set False) before _start_process_watch
        # returns, and assigning the return value afterwards overwrote that
        # with True - the loop then trusted a listener that was down.
        self.wmi_alive = {"ok": True}
        if procwatch._start_process_watch(self.proc_evt, self.wmi_alive, log):
            log.info("已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄")
        else:
            self.wmi_alive["ok"] = False
            log.warning("系统的程序启动通知用不了，AUTO-MAS 在不在改为每 %d 秒查一次",
                        procwatch.AUTOMAS_CHECK_SECONDS)
        # One-shot deadline for "AUTO-MAS should have appeared by now" - armed
        # only while no handle is held. Doubles on every failed revival so a
        # broken backend is retried with backoff, never on a beat.
        self.revive_wait = float(REVIVE_FIRST_WAIT)
        self.revive_deadline = (time.monotonic() + self.revive_wait) if not self.handle else None
        self.revive_failures = 0
        self.revive_alerted = False
        # The backend was seen up but its handle could not be taken: said once
        # (INFO), until a handle is held again (_adopted).
        self.unattached_noted = False
        # The hold (installer / unreadable process list) last said, so a hold that
        # outlasts many checks is said at WARNING once and at INFO after that.
        self.hold_said = None
        # When the shell was first seen alive with no backend behind it.
        self.shell_only_since = None
        self.shell_grace_noted = False
        self.next_check = 0.0
        # An exit nothing explained (_exited), until it is decided: the backend
        # back (_adopted: daily report only), still not back at the
        # REVIVE_ALERT_AFTER-th check (_revive: group) or at the stop (stopping:
        # group). {"at", "clock", "said", "how", "installer", "checks", "decided"}.
        self.gone = None

    def cap_wait(self, wait_s: float) -> float:
        """With no handle held, do not sleep past the moment it should have appeared;
        with one held whose API has not answered yet, wake to ask again."""
        if self.handle:
            return min(wait_s, API_RECHECK_SECONDS) if self.api_since is not None else wait_s
        if self.wmi_alive["ok"] and self.revive_deadline is not None:
            return min(wait_s, max(1.0, self.revive_deadline - time.monotonic()))
        if not self.wmi_alive["ok"]:
            return min(wait_s, procwatch.AUTOMAS_CHECK_SECONDS)
        return wait_s

    def _adopted(self) -> None:
        gone, self.gone = self.gone, None
        if gone is not None:
            # meanwhile (decided) - one fault, one push.
            from ark_relay.features import errwatch  # noqa: PLC0415
            down = wmi_diag._span(time.monotonic() - gone["at"])
            if self.revive_failures:
                self.log.warning("AUTO-MAS 后台意外退出过（%s 退出，退出码 %s），中继已重新打开（断了 %s，"
                                 "第 %d 次打开后起来的）\n%s", gone["clock"], gone["said"], down,
                                 self.revive_failures, gone["how"],
                                 extra=errwatch.recovered() if gone["decided"] else None)
            else:
                self.log.warning("AUTO-MAS 后台%s退出过（%s 退出，退出码 %s），现在又在运行了（断了 %s，"
                                 "不是中继打开的）\n%s", "" if gone["installer"] else "意外", gone["clock"],
                                 gone["said"], down, gone["how"],
                                 extra=errwatch.recovered() if gone["installer"] or gone["decided"] else None)
        self.shell_only_since = None
        self.shell_grace_noted = False
        self.revive_deadline = None
        self.revive_wait = float(REVIVE_FIRST_WAIT)
        self.revive_failures = 0
        self.revive_alerted = False
        self.unattached_noted = False
        self.hold_said = None

    def _confirm(self) -> None:
        """A backend handle is held: its revival state is reset (_adopted) only once its
        API answers. Until then the loop asks every API_RECHECK_SECONDS (check), and a
        backend still silent API_GRACE_SECONDS after its process appeared is pushed once."""
        if _api_up():
            if self.api_since is not None:
                self.log.info("AUTO-MAS 后台接口响应了（进程起来后 %s）",
                              wmi_diag._span(time.monotonic() - self.api_since))
            self.api_since, self.api_warned = None, False
            self._adopted()
            return
        if self.api_since is None:
            self.api_since = time.monotonic()
            self.log.info("AUTO-MAS 后台进程起来了，接口还没响应，每 %.0f 秒再问一次", API_RECHECK_SECONDS)
        elif not self.api_warned and time.monotonic() - self.api_since >= API_GRACE_SECONDS:
            self.api_warned = True
            self.log.warning("AUTO-MAS 后台进程起来 %s 了，接口一直没响应（端口可能被残留进程占着），"
                             "中继每 %.0f 秒再问一次，打开的次数照旧累计",
                             wmi_diag._span(time.monotonic() - self.api_since), API_RECHECK_SECONDS)

    def on_process_started(self) -> None:
        """A python.exe has started: if it is the backend, take the handle at once instead of waiting for the next liveness check."""
        if self.handle:
            return
        self.handle = _automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 已启动，进程句柄已挂上")
            self._confirm()

    def check(self, died: bool, now: float) -> None:
        """The backend died, or the moment it should have appeared has arrived: check once, and revive if needed."""
        from ark_relay.features import errwatch  # noqa: PLC0415
        if died:
            self.api_since, self.api_warned = None, False
            self._exited()
        elif self.handle and self.api_since is not None:
            self._confirm()
            return
        gone = self.gone
        if self.handle is None and gone is not None and gone.get("shutdown") and not gone["decided"]:
            if time.monotonic() - gone["at"] < SHUTDOWN_NO_SHOW_SECONDS:
                self.revive_deadline = now + procwatch.AUTOMAS_CHECK_SECONDS
                self.next_check = now + procwatch.AUTOMAS_CHECK_SECONDS
                return
            # The machine is still up: the shutdown did not happen (cancelled without a
            # 1075, or refused). From here it is an exit nothing explained.
            gone["shutdown"] = None
            gone["how"] = (f"{wmi_diag._span(time.monotonic() - gone['at'])}前系统日志说要关机，但机器到现在没关，"
                           "也没在装更新")
            self.log.info("AUTO-MAS 后台退出 %s 后机器还没关机，按没在关机处理，重新打开它",
                          wmi_diag._span(time.monotonic() - gone["at"]))
            died = True
        if self.handle is None and errwatch.relay_shutdown_issued():
            # The relay's own power-off is under way: there is nothing to
            # revive into (the exit itself was logged by _exited). Reviving here ran taskkill and
            # `schtasks /run` against a session Windows was closing, and logged
            # both steps as faults at every power-off. A deadline that has
            # passed is pushed on, or cap_wait would wake the loop every second;
            # none at all (an exit _exited put down to this power-off) is armed, so
            # a power-off that does not go ahead (cancelled) leads to a check that
            # revives the backend and says it was gone.
            if self.revive_deadline is None or now >= self.revive_deadline:
                self.revive_deadline = now + procwatch.AUTOMAS_CHECK_SECONDS
            return
        due_check = (
            self.handle is None
            and ((self.wmi_alive["ok"] and self.revive_deadline is not None
                  and now >= self.revive_deadline)
                 or (not self.wmi_alive["ok"] and now >= self.next_check)))
        if not (died or due_check):
            return
        self.next_check = now + procwatch.AUTOMAS_CHECK_SECONDS
        running = _automas_running()
        revived_before = self.revive_failures
        if not running:
            self._revive(now, after_exit=died)
        revived = self.revive_failures > revived_before
        # Adopt whichever backend now exists - our revival, or one that
        # was there all along. A revived backend is a new process, so
        # the old handle (already closed above) never signals again.
        self.handle = _automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 进程句柄已挂上")
            self._confirm()
        elif revived:
            # Arm with the CURRENT wait, then double for the next
            # failure - doubling first made the very first retry gap
            # 360s instead of the documented 180s.
            self.revive_deadline = now + self.revive_wait
            self.revive_wait = min(self.revive_wait * 2, float(REVIVE_MAX_WAIT))
        elif running:
            # Up (by the process list or, when that cannot be read, by its API)
            # but not attachable: nothing failed to revive, so no backoff - the
            # liveness check keeps its own beat until the handle can be taken.
            if not self.unattached_noted:
                self.unattached_noted = True
                self.log.info("AUTO-MAS 后台在运行，但挂不上它的进程句柄（进程列表读不到或打不开进程），"
                              "改为每 %d 秒查一次它在不在", procwatch.AUTOMAS_CHECK_SECONDS)
            self.revive_deadline = now + procwatch.AUTOMAS_CHECK_SECONDS
        else:
            # Held off (an installer on screen, the window's grace, an unreadable
            # process list): no revival ran, so the wait is not doubled. The hold
            # is said at WARNING once (_revive, hold_said), not at every check.
            self.revive_deadline = now + self.revive_wait

    def _exited(self) -> None:
        """The backend's handle signalled: say why it went, as far as the relay can know, and let go of the handle.
        """
        code = _exit_code(self.handle)
        win32api.CloseHandle(self.handle)
        self.handle = None
        said = f"0x{code & 0xFFFFFFFF:X}" if code is not None else "读不到"
        # No settle wait (0): the power-off the relay issues comes from this same loop
        # thread (engine.tick), so waiting here for it only held the loop 15 s at
        # every exit that was not one (清单-1108 A-06).
        if shutdown_signs._going_down_soon(0):
            self.log.info("%s，AUTO-MAS 后台此时退出（退出码 %s），按关机处理，不算故障，不再重新打开它",
                          shutdown_signs._down_reason(), said)
            return
        xmls = shutdown_signs._shutdown_event_xml()
        asked = shutdown_signs.shutdown_requested(xmls) if xmls else None
        if asked is not None:
            # A Windows shutdown is under way and the exit came before the stop
            # notice (it may also come after: EXIT_BEFORE_SHUTDOWN_SECONDS). Not
            # revived into the closing session; the stop says who shut the machine down.
            self.gone = {"at": time.monotonic(), "clock": datetime.now(tz=SERVER_TZ).strftime("%H:%M:%S"),
                         "said": said, "how": "Windows 正在关机", "installer": False, "checks": 0,
                         "decided": False, "shutdown": asked}
            self.log.info("AUTO-MAS 后台退出（退出码 %s）：%s 于 %s 发起了 Windows 关机（账户 %s），"
                          "关机中不重新打开它", said, asked["process"] or "读不到", asked["clock"] or "读不到",
                          asked["user"] or "读不到")
            return
        if xmls is None:
            self.log.info("AUTO-MAS 后台退出：系统日志读不到，判断不了是不是 Windows 在关机，按没在关机处理")
        out = _tasklist()
        installer = out is not None and any(h in out for h in INSTALLER_HINTS)
        if installer:
            # AUTO-MAS installs an update by starting AUTO-MAS-Setup.exe and
            # exiting (preupdate_automas.py); _revive leaves it alone meanwhile.
            how = "当时有安装或卸载程序开着，装完之前中继不去重新打开它"
        elif out is None:
            how = "窗口在不在读不到，当时机器没在关机"
        else:
            how = f"窗口{'还在' if b'auto-mas.exe' in out else '也没了'}，当时机器没在关机，也没在装更新"
        self.gone = {"at": time.monotonic(), "clock": datetime.now(tz=SERVER_TZ).strftime("%H:%M:%S"),
                     "said": said, "how": how, "installer": installer, "checks": 0, "decided": False}
        self.log.info("AUTO-MAS 后台%s退出了（退出码 %s，%s）；%s，查 %d 次还没起来报到群里",
                      "" if installer else "意外", said, how,
                      "装完更新重新起来了写进日报" if installer else "重新起来了也报到群里（退出的原因还没查清）",
                      REVIVE_ALERT_AFTER)

    def _gone_line(self) -> str:
        """The pending exit in words, for a push that says it did not recover."""
        g = self.gone or {}
        return (f"AUTO-MAS 后台{'' if g.get('installer') else '意外'}退出（{g.get('clock', '')} 退出，"
                f"退出码 {g.get('said', '')}，{g.get('how', '')}），到现在 {wmi_diag._span(time.monotonic() - g.get('at', 0))}")

    def stopping(self) -> None:
        """The service is stopping: what is still undecided did not recover, so it is pushed.

        The WMI listener's open drop (_ProcessWatch.stopping), and an exit
        nothing explained whose backend is not back yet: one WARNING (pushed),
        whatever stops the service - the exit itself was already ruled not to be
        the relay's own power-off when it happened (_exited)."""
        watch = self.wmi_alive.get("watch")
        if watch is not None:
            watch.stopping()
        if self.gone is not None and not self.gone["decided"]:
            self.gone["decided"] = True
            from ark_relay.features import errwatch  # noqa: PLC0415
            before = time.monotonic() - self.gone["at"]
            asked = self.gone.get("shutdown")
            planned = shutdown_signs.farm_poweroff_planned(asked)
            if planned is not None:
                self.log.info("Windows 关机是 %s 按计划发起的（收工 %s，%s 留的记号）：AUTO-MAS 后台跟着关机退出"
                              "（%s 退出，退出码 %s），不算故障", planned["by"], planned["outcome"], planned["at"],
                              self.gone["clock"], self.gone["said"])
                return
            if asked is not None:
                self.log.warning("Windows 关机（%s，账户 %s，于 %s 发起）：AUTO-MAS 后台在关机通知前 %s 被关掉"
                                 "（%s 退出，退出码 %s）", asked["process"] or "发起程序读不到",
                                 asked["user"] or "读不到", asked["clock"] or "时刻读不到", wmi_diag._span(before),
                                 self.gone["clock"], self.gone["said"])
                return
            if errwatch.os_shutdown() and before <= EXIT_BEFORE_SHUTDOWN_SECONDS:
                self.log.warning("Windows 关机（不是中继下的关机令）：AUTO-MAS 后台在关机通知前 %s 被关掉"
                                 "（%s 退出，退出码 %s），中继停下时它没再起来",
                                 wmi_diag._span(before), self.gone["clock"], self.gone["said"])
                return
            self.log.warning("%s，中继停下时还没重新起来", self._gone_line())

    def _revive(self, now: float, after_exit: bool = False) -> None:
        # While an exit nothing explained is undecided (self.gone), every step
        # here is INFO: whether the backend comes back decides (_adopted: daily
        # report; the REVIVE_ALERT_AFTER-th check below: group). Reached from
        # the deadline with no such exit - or after it was pushed - AUTO-MAS did
        # not come back: a fault of its own, WARNING.
        pending = self.gone is not None and not self.gone["decided"]
        say = self.log.info if (after_exit or pending) else self.log.warning
        holding = ""     # why the relay does not revive it on this check, in words

        def say_hold(reason: str, *args) -> None:
            # The same hold at every REVIVE_FIRST_WAIT check went to the group
            # through errwatch every 3 minutes (40 WARNINGs in 2 hours, review
            # of bd80586d): said by `say` the first time, at INFO while it lasts.
            (say if self.hold_said != reason else self.log.info)(*args)
            self.hold_said = reason
        # Two gates before the force-kill, because reviving is not
        # free: it kills a window somebody may be looking at.
        installer = _installer_running()
        if installer is None:
            # Unknown is not "no installer": killing a window mid-install is the
            # worse mistake (test_verify.py), so hands off - but said as
            # what it is. Same level rule as every step here (say); a hold that
            # outlasts REVIVE_ALERT_AFTER checks reaches the group below with
            # this `holding` as the reason.
            say_hold("unreadable", "AUTO-MAS 后端不在，但读不到正在运行的程序列表，"
                     "判断不了有没有安装程序开着——这次不动它，下次再查")
            self.shell_only_since = None
            self.shell_grace_noted = False
            holding = "读不到正在运行的程序列表，判断不了有没有安装程序开着，中继不去动它"
        elif installer:
            say_hold("installer", "AUTO-MAS 后端不在，但安装程序正在运行——不动它")
            self.shell_only_since = None
            self.shell_grace_noted = False
            holding = "安装或卸载程序还开着，中继不去动它"
        elif _automas_shell_running():
            # Shell up, backend down: it may be doing first-run setup or a
            # self-update, so give it a grace period first.
            if self.shell_only_since is None:
                self.shell_only_since = now
            waited = now - self.shell_only_since
            if waited < SHELL_GRACE_SECONDS:
                if not self.shell_grace_noted:
                    self.shell_grace_noted = True
                    say(
                        "AUTO-MAS 窗口在、后端不在，先等 %d 分钟再动"
                        "（AUTO-MAS 首次配置或自己更新时会这样）",
                        SHELL_GRACE_SECONDS // 60)
                holding = f"窗口开着、后台不在，中继等满 {SHELL_GRACE_SECONDS // 60} 分钟再关掉它重新打开"
            else:
                (self.log.info if pending else self.log.warning)(
                    "AUTO-MAS 窗口开着、后台已经 %d 分钟没在运行，中继正在关掉它重新打开（第 %d 次）",
                    int(waited // 60), self.revive_failures + 1)
                self.hold_said = None
                boot_stages._revive_automas()
                self.revive_failures += 1
        else:
            # No shell at all: nothing to kill, so revive at once.
            self.hold_said = None
            say("AUTO-MAS 没在运行，中继正在重新打开它（第 %d 次%s）", self.revive_failures + 1,
                "，上一次打开后没起来" if self.revive_failures else "")
            boot_stages._revive_automas()
            self.revive_failures += 1
        if pending:
            self.gone["checks"] += 1
        if self.revive_failures >= REVIVE_ALERT_AFTER and not self.revive_alerted:
            # The give-up: REVIVE_ALERT_AFTER revivals and no backend. Not
            # recovered, so the group, with the exit that started it when there was one.
            self.revive_alerted = True
            body = texts.automas_down_body(self.revive_failures)
            if self.gone is not None:
                body += "\n起因：" + self._gone_line()
                self.gone["decided"] = True
            self.notifier.send(texts.AUTOMAS_DOWN, body, alert=True)
        elif pending and self.gone["checks"] >= REVIVE_ALERT_AFTER:
            # The same number of checks while the relay holds off (an installer
            # on screen, the window's grace) or its revivals have not all run:
            # still not back, so the group.
            self.gone["decided"] = True
            self.log.warning("%s，还没回来：%s", self._gone_line(),
                             holding or f"中继已经打开了 {self.revive_failures} 次，还没起来，接着试")
