#!/usr/bin/env python3
"""Run the relay as a Windows service, so the OS keeps it alive.

Why a service and not a scheduled task: a task starts the relay once and then
forgets it. Nothing notices when the process dies - which is exactly what
happened on 2026-08-15, when the relay and AUTO-MAS both stopped mid-evening
and the 21:30 run was lost with no alert, because the thing that alerts was
the thing that died.

A service is different in kind, not degree. The Service Control Manager holds
the process handle, so the kernel tells it the instant the process exits -
there is no poll interval to wait out. Paired with failure actions
(`sc failure ... restart/5000/...`) the relay comes back within seconds of
being killed, by anything, including us.

This file adds nothing to the relay but the ability to answer the SCM. The
engine, the polling loop and every decision it makes are unchanged; see
__main__.cmd_local for the same loop without the service plumbing.

    install:  python service.py install
    start:    python service.py start
    remove:   python service.py stop && python service.py remove

AUTO-MAS cannot be a service at all: it drives the emulator and the game
window, and services run in session 0 where there is no desktop. ToDesk solves
the same problem by splitting itself in two - `ToDesk.exe --runservice` in
session 0 supervises, and it spawns `ToDesk.exe --show` into session 1 to do
the on-screen work. We follow that shape: this service supervises, and revives
AUTO-MAS through its scheduled task, which runs in the interactive session.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

import servicemanager  # noqa: E402
import win32api  # noqa: E402
import win32con  # noqa: E402
import win32event  # noqa: E402
import win32file  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

from ark_relay import texts  # noqa: E402
from ark_relay.config import SERVER_TZ, both_clocks  # noqa: E402

# Degraded path only: how often to re-check AUTO-MAS liveness when the WMI
# process-start subscription below could not be set up. On the healthy path
# a start is announced by the kernel and this number never ticks.
AUTOMAS_CHECK_SECONDS = 120
AUTOMAS_TASK = "AUTO-MAS_AutoStart"
# When AUTO-MAS is missing, how long to give it (or our own revival of it)
# before trying again. Doubles on each failed revival - this is failure
# backoff, not an interval; it resets the moment a backend handle is held.
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
# Processes whose presence vetoes any revival outright.
INSTALLER_HINTS = (b"auto-mas-setup", b"unins")


def _automas_shell_running() -> bool:
    """True if the Electron shell is up, whatever the backend is doing."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq AUTO-MAS.exe", "/NH"],
            capture_output=True, timeout=25,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True   # cannot tell -> assume it is there, i.e. do not kill
    return b"AUTO-MAS.exe" in out


def _installer_running() -> bool:
    """True while a setup or uninstaller is on screen. Never touch it."""
    try:
        out = subprocess.run(["tasklist", "/NH"], capture_output=True,
                             timeout=25).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return True   # cannot tell -> assume yes, i.e. keep hands off
    return any(h in out for h in INSTALLER_HINTS)


def _automas_running() -> bool:
    """True if AUTO-MAS's Python backend is up.

    Checks the backend rather than the Electron shell: the shell can sit there
    perfectly happily with a dead backend, which is precisely the state the
    machine was found in - the UI looked fine and nothing was scheduling runs.

    tasklist prints in the console's ANSI codepage (GBK here), so the output is
    never decoded; a UnicodeDecodeError in the watchdog would be the watchdog
    killing itself.
    """
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "commandline"],
            capture_output=True, timeout=25,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell -> assume alive rather than launch a duplicate
    return b"main.py" in out


def _automas_handle():
    """A waitable handle on the AUTO-MAS backend, or None if it is not up.

    Waiting on the process itself replaces asking every two minutes whether it
    is still there. Windows signals the handle the instant the process exits,
    so a backend that dies at 09:05 is revived at 09:05 rather than at 09:07 -
    and in between, the relay is not doing anything at all.
    """
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "processid,commandline"],
            capture_output=True, timeout=25,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for raw in out.splitlines():
        if b"main.py" not in raw:
            continue
        pid = raw.split()[-1]
        try:
            return win32api.OpenProcess(win32con.SYNCHRONIZE, False, int(pid))
        except (ValueError, Exception):  # noqa: BLE001
            return None
    return None


def _wait_for_network(log, timeout: float = 90.0) -> bool:
    """Block until DNS answers, or give up. True if the network came up.

    来龙去脉见 docs/CODE-HISTORY.md「service.py:_wait_for_network」。
    """
    import socket  # noqa: PLC0415 - only needed on this path

    deadline = time.monotonic() + timeout
    delay, waited = 2.0, False
    while True:
        try:
            socket.getaddrinfo("raw.githubusercontent.com", 443)
            if waited:
                log.info("网络已就绪（等了 %.0f 秒）", timeout - (deadline - time.monotonic()))
            return True
        except OSError as exc:
            left = deadline - time.monotonic()
            if left <= 0:
                log.warning("等了 %.0f 秒 DNS 仍不通（%s），本次跳过取件；"
                            "下次开机重试", timeout, exc)
                return False
            if not waited:
                log.info("刚开机，DNS 还没起来，最多等 %.0f 秒", timeout)
                waited = True
            time.sleep(min(delay, left))
            delay = min(delay * 2, 15.0)


def _start_process_watch(evt, alive: dict, log) -> bool:
    """Signal `evt` whenever a python.exe process starts anywhere on the box.

    Win32_ProcessStartTrace is a kernel-trace push event - WMI delivers it the
    instant the process is created, with no WITHIN-style polling underneath
    (unlike __InstanceCreationEvent, which would just move the timer into
    WMI). It needs admin rights; the service runs as LocalSystem, which has
    them. python.exe starts are rare on this machine (AUTO-MAS's backend and
    nothing else), so the wake-ups cost nothing.

    Returns False when the subscription cannot be created at all; if the
    listener thread dies later it flips alive["ok"] and fires `evt` once more,
    so the main loop notices and falls back to the liveness timer instead of
    trusting a watcher that no longer exists.
    """
    try:
        import pythoncom  # noqa: PLC0415 - optional capability probe
        import win32com.client  # noqa: PLC0415
    except ImportError:
        return False

    def run() -> None:
        """Subscribe, listen, and resubscribe when it drops - one dropped listener must not degrade us for good.

        来龙去脉见 docs/CODE-HISTORY.md「service.py:run」。
        """
        pythoncom.CoInitialize()
        delay = 5.0
        logged_detail = False
        try:
            while True:
                try:
                    wmi = win32com.client.GetObject(
                        "winmgmts:\\\\.\\root\\cimv2")
                    watcher = wmi.ExecNotificationQuery(
                        "SELECT * FROM Win32_ProcessStartTrace"
                        " WHERE ProcessName = 'python.exe'")
                    if not alive["ok"]:
                        alive["ok"] = True
                        log.info("进程启动事件订阅已恢复，不再走 %d 秒轮询",
                                 AUTOMAS_CHECK_SECONDS)
                    delay, logged_detail = 5.0, False
                    while True:
                        watcher.NextEvent()   # blocks until the kernel reports a process start
                        win32event.SetEvent(evt)
                except Exception:
                    # Full stack trace only the first time, one line after
                    # that: if WMI is properly broken, retrying every 60
                    # seconds would flood the log.
                    if not logged_detail:
                        log.exception(
                            "进程启动事件监听中断，改用 %d 秒活性检查，"
                            "%.0f 秒后重订阅",
                            AUTOMAS_CHECK_SECONDS, delay)
                        logged_detail = True
                    else:
                        log.warning("进程启动事件重订阅失败，%.0f 秒后再试", delay)
                    alive["ok"] = False
                    win32event.SetEvent(evt)   # wake the main loop so it sees the degradation
                    time.sleep(delay)
                    delay = min(delay * 2, 60.0)
        finally:
            pythoncom.CoUninitialize()

    # Verify the subscription can actually be created before promising it
    # works: do it here, synchronously, not inside the thread.
    try:
        pythoncom.CoInitialize()
        try:
            win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
        finally:
            pythoncom.CoUninitialize()
    except Exception:  # noqa: BLE001
        return False
    import threading  # noqa: PLC0415
    threading.Thread(target=run, name="proc-watch", daemon=True).start()
    return True


def _maaend_dir(cfg):
    """MaaEnd's install path, as AUTO-MAS records it."""
    from ark_relay import plan  # noqa: PLC0415
    return plan.script_dir(cfg.automas_dir, "MaaEnd")


def _revive_automas() -> None:
    """Restart AUTO-MAS through its scheduled task, which owns session 1.

    Three steps, and skipping any of them makes this silently do nothing:

    The Electron shell outlives its own Python backend - the window sits there
    looking healthy while nothing is scheduling runs, which is the exact state
    the machine was found in. So the shell has to go first.

    The task also still counts as running while that shell is alive, and
    `schtasks /run` on an already-running task returns 0x41301 and starts
    nothing. `/end` clears that before `/run` can take.
    """
    for cmd in (
        ["taskkill", "/IM", "AUTO-MAS.exe", "/F"],
        ["schtasks", "/end", "/tn", AUTOMAS_TASK],
    ):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    time.sleep(4)  # let the shell actually exit before the task is re-run
    try:
        subprocess.run(["schtasks", "/run", "/tn", AUTOMAS_TASK],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass  # next check will try again



def ensure_automas(timeout: float = 45) -> bool:
    """Start AUTO-MAS if its API is not answering, then wait for it to come up.

    The user, 2026-09-03: 「MAS 不在的时候你要拉起他，
    不希望见到任何理由开机时检测不到配置，而且要快。」
    """
    import logging  # noqa: PLC0415
    from ark_relay import commands  # noqa: PLC0415
    log = logging.getLogger("ark.service")
    if commands.mas_up():
        return True
    log.warning("AUTO-MAS 接口不在，拉起它")
    _revive_automas()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(3)
        if commands.mas_up():
            log.info("AUTO-MAS 已拉起（%.0f 秒）", timeout - (deadline - time.monotonic()))
            return True
    log.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", timeout)
    return False


def _boot_stamp(now: datetime) -> str:
    """Identifier for this boot: the power-on moment to the minute. Restarting the service for a deploy does not change it."""
    try:
        import ctypes  # noqa: PLC0415
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong  # 64-bit; do not truncate
        up_ms = ctypes.windll.kernel32.GetTickCount64()
        return (now - timedelta(milliseconds=int(up_ms))).strftime("%Y%m%d%H%M")
    except Exception:  # noqa: BLE001
        return now.strftime("%Y%m%d%H")


def _seconds_to_next_queue(automas_dir, now: datetime) -> float:
    """Seconds until today's next queue; when today has none left, hand back the large evening budget."""
    from ark_relay import plan  # noqa: PLC0415
    best = None
    for q in plan.schedule(automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due > now and (best is None or due < best):
                best = due
    if best is None:
        return 3600.0
    return max(120.0, (best - now).total_seconds() - 90)

class ArkRelayService(win32serviceutil.ServiceFramework):
    _svc_name_ = "ark-relay"
    _svc_display_name_ = "Ark Relay (MAA notification relay)"
    _svc_description_ = (
        "Watches AUTO-MAS run history, silences successful runs, alerts on "
        "failures immediately, and sends one daily summary. Also revives "
        "AUTO-MAS if its backend stops."
    )

    def __init__(self, args):
        super().__init__(args)
        # The second argument, 1, means manual reset. Three threads watch this
        # event (the main loop, the phone channel, the heartbeat); with auto
        # reset whichever sees it first eats the signal and the other two wait
        # forever.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:stop_event」
        self.stop_event = win32event.CreateEvent(None, 1, 0, None)

    def SvcStop(self):  # noqa: N802 - name required by the framework
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        # The phone channel's long-lived connection has to be cut deliberately,
        # otherwise it stays blocked on a socket read and the service cannot
        # stop - on 2026-08-31 it hung in STOP_PENDING several times running.
        box = getattr(self, "_mailbox", None)
        if box is not None:
            box.close()
        # Hard backstop: force the process to exit if it has not shut down
        # cleanly within 15 seconds. Hanging in STOP_PENDING is far worse than a
        # forced exit, and every piece of this process's state is written to
        # disk atomically, so a forced exit cannot corrupt anything.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:SvcStop」
        def _force_exit() -> None:
            # Getting here means the main loop did not come out of tick()
            # within 15 seconds (it happened once at 2026-09-07 10:29, with no
            # clue at all in the log). Print the line each thread is stuck on,
            # so next time there is nothing to guess.
            import sys  # noqa: PLC0415
            import traceback  # noqa: PLC0415
            names = {t.ident: t.name for t in threading.enumerate()}
            dump = []
            for ident, frame in sys._current_frames().items():
                if ident == threading.get_ident():
                    continue
                stack = traceback.format_stack(frame)[-4:]
                dump.append(f"[{names.get(ident, ident)}]\n" + "".join(stack))
            logging.getLogger("ark.service").warning(
                "停止 15 秒后进程仍未退出，硬保险强制退出。各线程卡在：\n%s", "\n".join(dump))
            logging.shutdown()
            os._exit(0)
        killer = threading.Timer(15, _force_exit)
        killer.daemon = True     # it must not itself hold up the exit
        killer.start()

    def SvcDoRun(self):  # noqa: N802 - name required by the framework
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            self.main()
        except Exception:
            import traceback  # noqa: PLC0415
            servicemanager.LogErrorMsg(traceback.format_exc())
            raise
        # The gap between this line and 「收到停止信号」, and between it and the
        # stop time the SCM records, is the evidence for where stopping the
        # service actually goes (measured 2026-09-07: sc stop -> STOPPED took
        # about 20 seconds).
        logging.getLogger("ark.service").info(
            "主流程已返回，向 SCM 报告已停止；还活着的线程：%s",
            "、".join(t.name for t in threading.enumerate() if t is not threading.current_thread()))
        # Do the last step ourselves rather than leaving it to the interpreter's
        # shutdown. The remaining threads are all daemons, but they are stuck
        # inside C calls (SSL reads, WMI waits) and Py_Finalize waits for them;
        # the 15-second backstop Timer cannot get the GIL during finalization
        # and never fires. Measured 2026-09-07: sc stop -> STOPPED took 20-27
        # seconds.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:stop_event」
        for t in threading.enumerate():
            if t.name == "phone-heartbeat":
                t.join(3)          # time for it to send the offline heartbeat (bye)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)
        logging.shutdown()
        os._exit(0)

    def main(self) -> None:
        """The boot sequence. One function per step, in exactly the order written here."""
        booted = _stage_bootstrap()
        if booted is None:
            return
        log, cfg, notifier, engine = booted
        _stage_patch_okww(cfg, notifier, log)
        # The self-update has to come before anything uses the new code, and
        # the network wait has to come before the self-update (a cold boot has
        # no DNS yet). The order of these two lines is itself the rule: do not
        # move them.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:main」
        _wait_for_network(log)
        if _stage_selfupdate(log):
            return
        _stage_announce_update(notifier, log)
        inbox, collect, deferred = _stage_inbox_and_phone(self, cfg, engine, notifier, log)
        _stage_preupdate(cfg, notifier, log)
        _stage_reenable_maaend(cfg, notifier, log)
        _stage_gameupdate(cfg, notifier, log)
        _stage_annihilation(engine, notifier, log)
        _loop(self, cfg, engine, notifier, inbox, collect, deferred, log)

def _stage_bootstrap():
    """First boot step: environment variables, logging, config, engine. Returns None when the config is unusable."""
    import logging  # noqa: PLC0415

    # The scheduled-task launcher used to set these before starting Python,
    # and .env never carried them - so a service, which does not go through
    # that launcher, ran fine but wrote its log nowhere. A service with no
    # log is a service you cannot debug, which defeats the point of making
    # the relay unkillable. Set them here, but let .env win if it says
    # otherwise.
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("ARK_LOG_FILE", str(HERE / "relay.log"))

    from ark_relay.__main__ import _force_utf8_console, _load_dotenv, _setup_logging  # noqa: PLC0415
    _force_utf8_console()
    # Absolute path: a service starts with an unrelated working directory,
    # and a silently empty config would disable every push channel.
    _load_dotenv(HERE / ".env")
    _setup_logging(verbose=False)

    from ark_relay.config import Config  # noqa: PLC0415
    from ark_relay.core import State  # noqa: PLC0415
    from ark_relay.engine import Engine  # noqa: PLC0415
    from ark_relay.notify import Notifier  # noqa: PLC0415
    from ark_relay.transport import LocalSource  # noqa: PLC0415

    log = logging.getLogger("ark.service")
    cfg = Config()
    if problems := cfg.validate():
        for p in problems:
            log.error("配置有问题: %s", p)
        return

    notifier = Notifier(cfg)
    engine = Engine(cfg, LocalSource(cfg), State(cfg.state_dir), notifier)
    engine.bootstrap()
    log.info("服务模式启动，监视 %s（变更即处理，兜底 %d 秒）",
             cfg.history_dir, cfg.poll_seconds)
    return log, cfg, notifier, engine


def _stage_patch_okww(cfg, notifier, log) -> None:
    """Apply the OK-WW patches once per startup (idempotent)."""
    # Idempotent: it writes nothing at all when they are already in place.
    # Here, not only in the boot pre-update block: after a deploy the machine
    # should already be in its final state, with no "takes effect next boot"
    # loose end.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_patch_okww」
    try:
        # Local import: a module-level one would be evaluated during service
        # installation, when ark_relay may not be on sys.path yet.
        from ark_relay import okww_patch as _okww_patch  # noqa: PLC0415

        okww_at_boot = cfg.okww_dir or (
            Path(cfg.automas_dir).parent / "okww" if cfg.automas_dir else None)
        notes = _okww_patch.ensure_patches(okww_at_boot)
        for note in notes:
            log.info("启动：%s", note)
        # One push per startup. It used to push one message per patch, so a
        # single OK-WW update dumped eight of them on the phone at once
        # (the user, 2026-09-06: 「你这个通知一直在轰炸我」).
        if notes:
            notifier.send(texts.patches(len(notes)), "\n".join(f"· {n}" for n in notes))
    except Exception:
        log.exception("启动时贴 OK-WW 补丁失败，服务照常继续")


def _stage_selfupdate(log) -> bool:
    """Pull new code; when something really updated, trigger a restart and return True so the caller exits at once."""
    try:
        from ark_relay import selfupdate  # noqa: PLC0415

        if changed := selfupdate.check(HERE):
            # Take effect now, not next boot. The files are on disk but this
            # process imported the old ones, so the only honest way to run
            # the new code is to be a new process. Waiting for the next boot
            # meant a fix pushed in the morning sat unused all day - and a
            # queued command that needs that fix could not be understood.
            #
            # A detached restarter rather than exiting and trusting the SCM's
            # failure actions: if those are ever unset, exiting would leave
            # the relay down until tomorrow, which is worse than the problem
            # being fixed.
            log.info("代码已更新，重启以立即生效: %s", "、".join(changed))
            subprocess.Popen(
                ["cmd", "/c", "timeout /t 3 /nobreak >nul & "
                              "net stop ark-relay & net start ark-relay"],
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.DETACHED_PROCESS))
            return
    except Exception:
        log.exception("自更新出错，跳过")
    return False


def _stage_announce_update(notifier, log) -> None:
    """First thing once the new code is up: announce either the failed update or the applied one."""
    # We only reach here on a process that did NOT just apply an update -
    # which, after a self-restart, is the process running the new code. So
    # this is the first honest moment to say the update took effect, and
    # the operator asked to be told the moment it does.
    try:
        from ark_relay import selfupdate  # noqa: PLC0415 - see the block above

        # An update that was available and did not land must be as loud
        # as one that did. Otherwise the machine quietly runs old code
        # while everything upstream assumes the push took effect - the
        # same trap as an scp that returns 0 without transferring.
        if fail := selfupdate.take_failure(HERE):
            files = fail.get("files") or []
            more = max(0, int(fail.get("count") or 0) - len(files))
            body = "\n".join([
                f"原因：{fail.get('reason') or '未知'}",
                f"仓库 v{fail.get('remote') or '?'}，本机仍是 v{fail.get('local') or '?'}",
                "没更新的文件：" + "、".join(files) + (f" 等 {more} 个" if more else ""),
                "",
                "本机现在跑的是旧代码。下次开机会自动重试；",
                "要立刻生效请在控制端执行 scripts/mac/deploy-relay.sh。",
            ])
            if errors := notifier.send(texts.SELFUPDATE_FAILED, body, alert=True):
                log.error("更新失败通知没发出去: %s", "；".join(errors))
            else:
                log.info("已推送更新失败通知")

        if note := selfupdate.pending_announcement(HERE):
            files = note.get("files") or []
            title = (f"🔄 中继已更新（{len(files)} 个文件）" if files
                     else "🔄 中继已更新")
            applied = note.get("at") or ""
            try:
                when = both_clocks(datetime.fromisoformat(applied))
            except ValueError:
                when = applied
            lines = [f"{when} 生效" if when else "刚刚生效"]
            prev = note.get("previous")
            lines.append(f"版本 v{prev} → v{note.get('version') or '?'}"
                         if prev else f"版本 v{note.get('version') or '?'}")
            # Plain language first: take "which problem you hit did this fix"
            # from RELEASE-NOTES.md, and only fall back to listing file names
            # when there is no notes file.
            # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_announce_update」
            notes = ""
            try:
                nf = HERE / "RELEASE-NOTES.md"
                if nf.exists():
                    notes = nf.read_text(encoding="utf-8").strip()
            except OSError:
                notes = ""
            if notes:
                lines += ["", notes]
            else:
                # The file list only exists when the process that applied the
                # update was already running this code; the first update after
                # this shipped has no list, and saying so beats an empty line.
                lines.append("改动文件：" + "、".join(files) if files
                             else "（改动清单由上一版代码写入，本次没有）")
            lines += ["", "更新在开机后、队列开跑前落地，本轮直接使用新代码。"]
            body = "\n".join(lines)
            if errors := notifier.send(title, body):
                log.error("更新通知没发出去: %s", "；".join(errors))
            else:
                log.info("已推送更新通知：%d 个文件", len(files))
    except Exception:
        log.exception("推送更新通知出错，跳过")


def _make_collect(inbox, engine, notifier, log, deferred_inbox):
    """Build the action that checks the todo mailbox once and pushes a message if anything new landed.

    A separate step because it is called at three moments - at boot, on every
    round of the loop, and before shutdown - and all three have to make the
    same decision. The most important part of that decision: nothing may land
    while a script is running, because config written then is clobbered by
    AUTO-MAS's in-memory copy. So it defers on the spot and records the
    outstanding check in deferred_inbox for the main loop to see.
    """

    def collect(reason: str) -> None:
        """Check for queued changes and push whatever landed.

        来龙去脉见 docs/CODE-HISTORY.md「service.py:collect」。
        """
        if engine.scripts_running():
            if not deferred_inbox[0]:
                log.info("待办检查（%s）推迟：脚本正在运行，"
                         "此时改配置会被 AUTO-MAS 冲掉", reason)
            deferred_inbox[0] = True
            return
        deferred_inbox[0] = False
        try:
            version, messages = inbox.poll()
        except Exception:
            log.exception("待办检查出错，跳过")
            return
        if messages:
            for m in messages:
                log.info("待办: %s", m)
            notifier.send(messages[0], "\n".join(messages[1:]).strip())
        else:
            log.debug("待办检查（%s）：无新配置（当前 v%s）", reason, version)

    return collect


def _make_phone_cmd(engine, notifier, log, hb, push_state):
    """Build the callback for what happens after a button is pressed on the phone.

    A separate step because it has two entry points: at boot the commands that
    piled up are worked through one by one, and after that the long-lived
    connection calls it again for every command it hears - both have to be the
    same logic.
    """
    from ark_relay.commands import apply_command  # noqa: PLC0415

    def run_phone_cmd(body: dict) -> None:
        """One press from the phone. Refresh only answers with state; everything else really changes config, and notifies the moment it is done."""
        action = str((body or {}).get("action") or "")
        if action == "refresh":
            ensure_automas()          # make sure it is alive before reading config
            push_state("手机请求")
            return
        if action == "watch":
            hb.watch()          # the page is open: beat every 30s for the next 10 minutes
            return
        if action == "estop":
            # Red button: it gets pressed precisely while scripts are running,
            # so it must not be blocked by the gate below.
            from ark_relay import commands as _cmd  # noqa: PLC0415
            ok, msg = _cmd.estop()
            log.warning("🛑 红按钮：%s", msg)
            notifier.send(texts.ESTOP, msg)
            push_state("红按钮")
            return
        if engine.scripts_running():
            # Config changed while a script is running gets clobbered by
            # AUTO-MAS's in-memory copy.
            notifier.send(texts.PHONE_DEFERRED, texts.phone_deferred_body(action))
            return
        ok, msg = apply_command(body)
        log.info("📱 手机指令 %s：%s", action, msg)
        # Asked for by the user on 2026-08-31: pressing save has to be followed
        # by a notification saying the change succeeded.
        notifier.send(texts.CONFIG_CHANGED if ok else texts.CONFIG_FAILED, msg)
        push_state("改完配置")

    return run_phone_cmd


def _start_phone_channel(svc, cfg, engine, notifier, log):
    """Bring up the whole phone channel: mailbox, heartbeat, two background threads.

    A separate step because this section does exactly one thing - let the phone
    both see the state and change the config - and it exposes only one thing to
    the outside: push_state, which reports state and is needed once more before
    shutdown.
    """
    # Fetching once at boot is enough: the machine restarts for every queue run,
    # and the config is almost always changed while it is off, so the next boot
    # is bound to pick it up. Online/offline must not be done by polling; how it
    # is done instead is in phone.py's module docstring.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_inbox_and_phone」
    from ark_relay.phone import Mailbox  # noqa: PLC0415

    box = Mailbox(cfg.phone_topic, cfg.phone_pin, cfg.state_dir)
    svc._mailbox = box          # SvcStop uses this to cut the long-lived connection

    def push_state(why: str) -> None:
        if not box.enabled:
            return
        try:
            from ark_relay.phone import state_payload  # noqa: PLC0415
            box.publish(state_payload(cfg, cfg.state_dir))
            log.info("📱 已上报状态到手机（%s）", why)
        except Exception:
            log.warning("状态没能上报到手机（%s）", why, exc_info=True)

    from ark_relay.phone import Heartbeat  # noqa: PLC0415
    hb = Heartbeat(box.topic, cfg.state_dir)
    run_phone_cmd = _make_phone_cmd(engine, notifier, log, hb, push_state)

    ensure_automas()
    push_state("开机")
    if box.enabled:
        for body in box.fetch():
            run_phone_cmd(body)
        threading.Thread(
            target=lambda: box.listen(
                run_phone_cmd,
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0),
            name="phone-mailbox", daemon=True).start()
        # ToDesk-style presence: it only beats while the page says it is
        # watching, and sends bye when the service stops. The page uses it to
        # flip between powered on and off by itself, with no manual refresh
        # (asked for by the user on 2026-09-02).
        threading.Thread(
            target=lambda: hb.loop(
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0),
            name="phone-heartbeat", daemon=True).start()

    return push_state


def _stage_inbox_and_phone(svc, cfg, engine, notifier, log):
    """Todo mailbox plus phone channel. Returns (inbox, collect, deferred_inbox), which the main loop needs."""
    from ark_relay.inbox import Inbox  # noqa: PLC0415

    inbox = Inbox(cfg.state_dir, cfg.inbox_url,
                  cfg.maaend_dir or _maaend_dir(cfg), cfg.automas_dir)

    # A config command that arrives while a queue is running waits here
    # until every script has stopped, then lands.
    deferred_inbox = [False]
    collect = _make_collect(inbox, engine, notifier, log, deferred_inbox)
    push_state = _start_phone_channel(svc, cfg, engine, notifier, log)

    # One last todo fetch and state report before shutdown: someone may have
    # just pressed 「今晚别关机」 on their phone, and the state shown there has
    # to come to rest looking the way it did the moment the machine powered off.
    def before_shutdown() -> None:
        collect("关机前")
        push_state("关机前")

    engine._before_shutdown = before_shutdown
    collect("启动")
    return inbox, collect, deferred_inbox


def _note(problems, msg: str) -> None:
    problems.append(msg)


def _preupdate_maaend(maaend, cfg, notifier, log, problems) -> None:
    """The MaaEnd slot of the pre-update: upgrade it, then clear the two loose ends it leaves behind.

    A separate step because it runs one stretch longer than the other three: a
    new version means AUTO-MAS has to re-read the task table, and the tasks that
    were temporarily switched off while waiting for that version have to be
    switched back on.
    """
    from ark_relay import preupdate  # noqa: PLC0415

    if updated := preupdate.run(maaend, problems=problems,
                                state_dir=cfg.state_dir):
        log.info("预更新：MaaEnd 已更新：%s", updated)
        notifier.send(texts.PREUPDATE,
                      f"MaaEnd 已更新：{updated}")
        # AUTO-MAS preloads MaaEnd's task table into an in-memory cache at
        # boot, and when MaaEnd is upgraded afterwards that cache is not
        # refreshed: on 2026-09-06 upstream renamed SellProduct's definition
        # file, MAS was holding the old table and could not match
        # 「任务完成: 🛒据点交易」, so the whole run was judged a failure and
        # retried twice.
        # The maintainer (AUTO-MAS#573): 「缓存更新逻辑的问题，重启 MAS 就好」.
        # Verified true on this machine, so restart MAS after the upgrade and
        # make it read MaaEnd again.
        log.info("预更新：MaaEnd 换了版本，重启 AUTO-MAS 刷新它的任务表缓存")
        _revive_automas()
        if not ensure_automas(timeout=120):
            _note(problems, "MaaEnd 更新后重启 AUTO-MAS，120 秒内接口没起来")
    try:
        from ark_relay import gameupdate as _gu  # noqa: PLC0415
        if back := _gu.maaend_reenable_if_updated(cfg):
            log.info("预更新：%s", back)
            notifier.send(texts.MAAEND_REENABLED, back)
    except Exception:
        log.exception("开回 MaaEnd 任务出错")


def _preupdate_okww(cfg, notifier, log, problems) -> None:
    """The OK-WW slot of the pre-update: update first, then re-apply the local patches.

    A separate step because it differs from the other three - its update
    overwrites the whole of src, so "update" and "re-apply the patches" are a
    bound pair, and doing half of it is the same as doing none of it.
    """
    # Until 2026-08-26 okww_patch was missing from this line: line 549 below
    # uses it and raised NameError the moment it was reached, which means
    # **re-applying the patches had never once actually run**.
    # tests/test_undefined_names.py was added for exactly this class of error.
    from ark_relay import okww_patch, preupdate  # noqa: PLC0415

    # OK-WW last: it is the newest of the four and the only one whose
    # update comes from a CNB git mirror rather than MirrorChyan.
    okww = cfg.okww_dir or (Path(cfg.automas_dir).parent / "okww"
                            if cfg.automas_dir else None)
    # OK-WW's auto-update overwrites the whole of src and wipes out the local
    # patches, so they have to be re-applied after every update.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
    if note := preupdate.run_okww(okww, problems=problems):
        log.info("预更新：%s", note)
        notifier.send(texts.PREUPDATE, note)
    patch_notes = okww_patch.ensure_patches(okww)
    for note in patch_notes:
        log.info("预更新：%s", note)
    if patch_notes:      # one combined push, not one per patch
        notifier.send(texts.patches(len(patch_notes)),
                      "\n".join(f"· {n}" for n in patch_notes))


def _stage_preupdate(cfg, notifier, log) -> None:
    """Do the updates for all four programs inside the boot window (once a day)."""
    # MaaEnd only checks for updates at startup, and when it finds one it
    # downloads it and **restarts its own process** - while AUTO-MAS is watching
    # the pid it launched, so on any day with a new version the first queue run
    # is bound to fail. Hence moving this step into the boot window, so it
    # finishes updating while nobody is waiting on it.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
    try:
        from ark_relay import plan, preupdate  # noqa: PLC0415

        # Once a day is enough: re-running on every service restart would
        # launch MAA, MaaEnd and OK-WW one by one to check for updates all over
        # again. On 2026-08-31 I deployed three times in one morning, it ran
        # three times, and on the third MAA did not answer within 180 seconds
        # and we reported 「没能确认」.
        _pre_now = datetime.now(tz=SERVER_TZ)
        if (preupdate.wanted_today(cfg.automas_dir)
                and preupdate.should_run(cfg.state_dir, _pre_now)):
            ensure_automas()          # 09-03 01:08: AUTO-MAS was shut down and the pre-update asked for 180s
            maaend = cfg.maaend_dir or _maaend_dir(cfg)
            # Both are pushed, per the standing order: when an auto-update
            # takes effect, say so at once. An earlier version of this block
            # suppressed the MaaEnd notice on the grounds that its beta
            # channel "ships most days" - that was never measured, and the
            # log shows the MaaEnd pre-update had in fact never once run to
            # a verdict. Measured cadence on MAA is one update per ~6 days,
            # which is not a channel anyone learns to tune out. If either
            # ever does become daily noise, coalesce the two into one
            # message rather than going silent.
            maa = plan.script_dir(cfg.automas_dir, "MAA")
            # Everything that could not be confirmed goes into this basket and
            # is then sent as an **alert**. A false "all fine" is worse than an
            # honest failure: nobody goes looking into something that was
            # reported as normal.
            # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
            problems: list[str] = []
            # MAA first: its update is applied by a delegated process at
            # startup, so getting it out of the way is quick and the
            # launch of MaaEnd afterwards is unaffected either way.
            if note := preupdate.run_maa(maa, problems=problems):
                log.info("预更新：%s", note)
                notifier.send(texts.PREUPDATE, note)
            _preupdate_maaend(maaend, cfg, notifier, log, problems)
            # AUTO-MAS is asked, not launched - it is already running.
            if note := preupdate.run_automas(cfg.automas_dir,
                                             problems=problems):
                notifier.send(texts.PREUPDATE, note)
            _preupdate_okww(cfg, notifier, log, problems)
            preupdate.mark_run(cfg.state_dir, _pre_now,
                               clean=not problems)
            if problems:
                # An alert, not a routine note: a silent pre-update leaves
                # the machine running a version nobody chose.
                body = "\n".join(f"· {p}" for p in problems)
                log.error("预更新有 %d 项没能确认：\n%s", len(problems), body)
                notifier.send(texts.unconfirmed("预更新", len(problems)),
                              body + texts.preupdate_unconfirmed_tail(), alert=True)
    except Exception:
        log.exception("预更新出错，跳过（本轮照旧）")


def _stage_reenable_maaend(cfg, notifier, log) -> None:
    """Switch the temporarily disabled tasks back on once MaaEnd has changed version."""
    # Once MaaEnd changes version, switch the four items disabled on 09-02 back
    # on. Outside the pre-update block, because on the morning of 09-03 the
    # pre-update was skipped (it had already run overnight), this step was
    # skipped along with it, and the four stayed off.
    try:
        from ark_relay import gameupdate as _gu2  # noqa: PLC0415
        for back in (_gu2.maaend_reenable_if_updated(cfg), _gu2.maaend_reenable_next_boot(cfg),
                     _gu2.maaend_reenable_spmed_if_updated(cfg)):
            if back:
                log.info("开机：%s", back)
                notifier.send(texts.MAAEND_REENABLED, back)
    except Exception:
        log.exception("开回 MaaEnd 任务出错")


def _stage_gameupdate(cfg, notifier, log) -> None:
    """Major version update days: register the game clients that need updating."""
    # On major update days, update the game clients too (asked for by the user
    # on 2026-09-02). Once per boot: the morning window is short, only enough
    # for Arknights to install its package or for a launcher to be clicked; the
    # evening run is MAA only, so the large Endfield and Wuthering Waves
    # downloads go here. The budget is however long there is until the next
    # queue.
    try:
        from ark_relay import gameupdate  # noqa: PLC0415
        _gu_now = datetime.now(tz=SERVER_TZ)
        _boot_id = _boot_stamp(_gu_now)
        if gameupdate.should_run(cfg.state_dir, _gu_now, boot_id=_boot_id):
            budget = _seconds_to_next_queue(cfg.automas_dir, _gu_now)
            log.info("游戏更新：开始检查三家客户端（预算 %.0f 秒）", budget)
            notes, gproblems = gameupdate.boot_check(cfg, budget_s=budget, now=_gu_now)
            for n in notes:
                log.info("游戏更新：%s", n)
                notifier.send(texts.GAME_UPDATE, n)
            if gproblems:
                body = "\n".join(f"· {x}" for x in gproblems)
                log.warning("游戏更新有 %d 项没能确认：\n%s", len(gproblems), body)
                notifier.send(texts.unconfirmed("游戏更新", len(gproblems)), body)
            gameupdate.mark_run(cfg.state_dir, _gu_now, boot_id=_boot_id)
    except Exception:
        log.exception("游戏更新出错，跳过（本轮照旧）")


def _stage_annihilation(engine, notifier, log) -> None:
    """Restore the three once-a-week switches for a new week, and assert them once at boot.

    Annihilation, the weekly garden and the weekly boss share one piece of logic
    and one notification (the user, 2026-09-07: 「逻辑上一致的
    东西就应该强统一」). When any one of them rolls over into a new week, this
    week's state for all three is sent together.
    """
    gates = [("剿灭", engine._annihilation), ("周常乐园", engine._garden),
             ("周本", engine._weeklyboss)]
    rolled: dict[str, str] = {}
    for name, gate in gates:
        if gate is None:
            continue
        try:
            if line := gate.maybe_reopen():
                if hasattr(gate, "enforce") and name != "剿灭":
                    gate.enforce()      # really put it back first, then say it is restored
                rolled[name] = line
        except Exception:
            log.exception("%s 周期检查出错，跳过", name)
    if rolled:
        lines = []
        for name, gate in gates:
            if gate is None:
                continue
            try:
                lines.append(rolled.get(name) or gate.week_line())
            except Exception:
                log.exception("%s 状态读不出来", name)
        notifier.send(texts.NEW_WEEK, "\n".join(lines))

    # Assert the annihilation switch once at startup rather than leaving it
    # to tick(): ticks are driven by file events and alarms, and neither has
    # fired yet on a machine that just booted. By the time the first tick
    # arrives it is usually the queue's own start time, so that round would
    # still pay for the pointless annihilation pass.
    engine._enforce_annihilation()


class _DirWatch:
    """Change notifications for AUTO-MAS's history directory: arming, rebuilding and re-arming all live here.

    Split out of `_loop` (2026-09-08). Not a word of behaviour changed; the
    three pieces - arm, rebuild, re-arm - were simply moved out of the middle of
    the main loop into somewhere with a name. They used to be interleaved with
    keeping AUTO-MAS alive in a single 241-line function, where changing any one
    piece meant reading the other two first.

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
        try:
            if cfg.history_dir:
                self.handle = win32file.FindFirstChangeNotification(
                    str(cfg.history_dir), True,   # True = include subdirectories
                    win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                    | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
                log.info("已挂上目录变更通知，记录一落盘立即处理")
        except Exception:
            log.exception("目录变更通知挂载失败，先退回定时检查，稍后自动重试")
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
            self.log.info("目录变更通知已重建，恢复「记录一落盘立即处理」")
            self.retry_delay = 5.0
        except Exception:  # noqa: BLE001 - a failed rebuild just waits longer; do not flood the log
            self.handle = None
            self.retry_delay = min(self.retry_delay * 2, 60.0)
            self.log.warning("目录变更通知重建失败，%.0f 秒后再试",
                             self.retry_delay)
        self.retry_at = time.monotonic() + self.retry_delay

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
        been bitten by most, so say it out loud.
        """
        try:
            win32file.FindNextChangeNotification(self.handle)
        except Exception:
            self.log.exception("目录变更通知重新武装失败，改用闹钟兜底")
            self.close()
            self.retry_at = time.monotonic() + 5.0
            self.retry_delay = 5.0
            self.notifier.send(texts.WATCH_LOST, texts.watch_lost_body(), alert=True)
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


class _AutomasKeeper:
    """Keeping the AUTO-MAS backend alive: hold the handle, detect absence, revive with backoff, alert after repeated failures.

    Split out of `_loop` (2026-09-08); not a word of behaviour changed.

    Two of the four things that can wake the loop live here: the backend dying,
    and a python.exe starting (so a freshly launched backend gets its handle
    immediately instead of at the next liveness check).
    """

    def __init__(self, log, notifier):
        self.log, self.notifier = log, notifier
        self.handle = _automas_handle()
        if self.handle:
            log.info("已挂上 AUTO-MAS 进程句柄，它一退出立即拉起")
        self.proc_evt = win32event.CreateEvent(None, 0, 0, None)
        self.wmi_alive = {"ok": False}
        self.wmi_alive["ok"] = _start_process_watch(self.proc_evt, self.wmi_alive, log)
        if self.wmi_alive["ok"]:
            log.info("已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄")
        else:
            log.warning("进程启动事件订阅不可用，AUTO-MAS 缺席时退回 %d 秒活性检查",
                        AUTOMAS_CHECK_SECONDS)
        # One-shot deadline for "AUTO-MAS should have appeared by now" - armed
        # only while no handle is held. Doubles on every failed revival so a
        # broken backend is retried with backoff, never on a beat.
        self.revive_wait = float(REVIVE_FIRST_WAIT)
        self.revive_deadline = (time.monotonic() + self.revive_wait) if not self.handle else None
        self.revive_failures = 0
        self.revive_alerted = False
        # When the shell was first seen alive with no backend behind it.
        self.shell_only_since = None
        self.shell_grace_noted = False
        self.next_check = 0.0

    def cap_wait(self, wait_s: float) -> float:
        """With no handle held, do not sleep past the moment it should have appeared."""
        if self.handle:
            return wait_s
        if self.wmi_alive["ok"] and self.revive_deadline is not None:
            return min(wait_s, max(1.0, self.revive_deadline - time.monotonic()))
        if not self.wmi_alive["ok"]:
            return min(wait_s, AUTOMAS_CHECK_SECONDS)
        return wait_s

    def _adopted(self) -> None:
        self.shell_only_since = None
        self.shell_grace_noted = False
        self.revive_deadline = None
        self.revive_wait = float(REVIVE_FIRST_WAIT)
        self.revive_failures = 0
        self.revive_alerted = False

    def on_process_started(self) -> None:
        """A python.exe has started: if it is the backend, take the handle at once instead of waiting for the next liveness check."""
        if self.handle:
            return
        self.handle = _automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 已启动，进程句柄已挂上")
            self._adopted()

    def check(self, died: bool, now: float) -> None:
        """The backend died, or the moment it should have appeared has arrived: check once, and revive if needed."""
        if died:
            self.log.warning("AUTO-MAS 后端退出了")
            win32api.CloseHandle(self.handle)
            self.handle = None
        due_check = (
            self.handle is None
            and ((self.wmi_alive["ok"] and self.revive_deadline is not None
                  and now >= self.revive_deadline)
                 or (not self.wmi_alive["ok"] and now >= self.next_check)))
        if not (died or due_check):
            return
        self.next_check = now + AUTOMAS_CHECK_SECONDS
        if not _automas_running():
            self._revive(now)
        # Adopt whichever backend now exists - our revival, or one that
        # was there all along. A revived backend is a new process, so
        # the old handle (already closed above) never signals again.
        self.handle = _automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 进程句柄已挂上")
            self._adopted()
        else:
            # Arm with the CURRENT wait, then double for the next
            # failure - doubling first made the very first retry gap
            # 360s instead of the documented 180s.
            self.revive_deadline = now + self.revive_wait
            self.revive_wait = min(self.revive_wait * 2, float(REVIVE_MAX_WAIT))

    def _revive(self, now: float) -> None:
        # Two gates before the force-kill, because reviving is not
        # free: it kills a window somebody may be looking at.
        if _installer_running():
            self.log.warning("AUTO-MAS 后端不在，但安装程序正在运行——不动它")
            self.shell_only_since = None
            self.shell_grace_noted = False
        elif _automas_shell_running():
            # Shell up, backend down: it may be doing first-run setup or a
            # self-update, so give it a grace period first.
            if self.shell_only_since is None:
                self.shell_only_since = now
            waited = now - self.shell_only_since
            if waited < SHELL_GRACE_SECONDS:
                if not self.shell_grace_noted:
                    self.shell_grace_noted = True
                    self.log.warning(
                        "AUTO-MAS 窗口在、后端不在，先等 %d 分钟再动"
                        "（可能正在首次配置或更新）",
                        SHELL_GRACE_SECONDS // 60)
            else:
                self.log.warning("AUTO-MAS 窗口在、后端已缺席 %d 分钟，"
                                 "正在拉起（第 %d 次）",
                                 int(waited // 60), self.revive_failures + 1)
                _revive_automas()
                self.revive_failures += 1
        else:
            # No shell at all: nothing to kill, so revive at once.
            self.log.warning("AUTO-MAS 后端不在，正在拉起（第 %d 次）",
                             self.revive_failures + 1)
            _revive_automas()
            self.revive_failures += 1
        if self.revive_failures >= REVIVE_ALERT_AFTER and not self.revive_alerted:
            self.revive_alerted = True
            self.notifier.send(texts.AUTOMAS_DOWN,
                               texts.automas_down_body(self.revive_failures), alert=True)


def _loop(svc, cfg, engine, notifier, inbox, collect, deferred_inbox, log) -> None:
    """The main loop: wait for an event or an alarm, run tick, revive AUTO-MAS.

    Four things can wake it, and none of them is a timer: the service being
    stopped, a run record landing on disk, the AUTO-MAS backend exiting, and a
    python.exe starting. The timeout is not an "interval" either, it is an alarm
    clock - the engine knows the moment at which the next purely time-based
    decision changes (a missed-run alert falling due, the daily report cutoff,
    the boot checkpoint), and the loop sleeps until exactly that moment.
    """
    watch = _DirWatch(cfg, notifier, log)
    keeper = _AutomasKeeper(log, notifier)
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
        if not inbox.last_fetch_ok:
            wait_s = min(wait_s, 300)   # wake in time for the fetch retry

        rc = win32event.WaitForMultipleObjects(
            handles, False, int(wait_s * 1000))
        if rc == win32event.WAIT_OBJECT_0:
            log.info("收到停止信号，退出")
            watch.close()
            return
        if rc == win32event.WAIT_OBJECT_0 + proc_idx:
            keeper.on_process_started()
        if watch.handle and rc == win32event.WAIT_OBJECT_0 + watch_idx:
            watch.rearm()

        try:
            engine.tick()
        except Exception:
            log.exception("本轮处理出错，继续")

        # A 「暂停」 command that never got downloaded is the same as no command
        # at all - so a failed fetch has to be retried, every 5 minutes. One
        # failure must not be read as "nobody issued a command today".
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_loop」
        if not inbox.last_fetch_ok and time.monotonic() >= next_inbox_retry:
            next_inbox_retry = time.monotonic() + 300
            collect("重试")

        # Scripts have just stopped: apply the config commands that were
        # deferred, now that a write will not be clobbered.
        if deferred_inbox[0] and not engine.scripts_running():
            log.info("脚本已停，补做之前推迟的待办检查")
            collect("推迟补做")

        keeper.check(bool(keeper.handle) and rc == win32event.WAIT_OBJECT_0 + automas_idx,
                     time.monotonic())


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Launched by the SCM rather than from a shell.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ArkRelayService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ArkRelayService)
