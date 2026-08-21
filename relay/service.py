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

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

import servicemanager  # noqa: E402
import win32api
import win32con
import win32event
import win32file  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

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
        except (ValueError, Exception):  # noqa: B014 - pywin32 raises its own
            return None
    return None


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
        pythoncom.CoInitialize()
        try:
            wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
            watcher = wmi.ExecNotificationQuery(
                "SELECT * FROM Win32_ProcessStartTrace"
                " WHERE ProcessName = 'python.exe'")
            while True:
                watcher.NextEvent()  # blocks until the kernel reports a start
                win32event.SetEvent(evt)
        except Exception:  # noqa: BLE001 - degrade to the timer, never crash
            log.exception("进程启动事件监听退出，改用 %d 秒活性检查",
                          AUTOMAS_CHECK_SECONDS)
            alive["ok"] = False
            win32event.SetEvent(evt)   # wake the loop so it sees the change
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
    from ark_relay import plan
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
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):  # noqa: N802 - name required by the framework
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):  # noqa: N802 - name required by the framework
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            self.main()
        except Exception:  # noqa: BLE001 - a crash here must reach the event log
            import traceback
            servicemanager.LogErrorMsg(traceback.format_exc())
            raise

    def main(self) -> None:
        import logging

        # The scheduled-task launcher used to set these before starting Python,
        # and .env never carried them - so a service, which does not go through
        # that launcher, ran fine but wrote its log nowhere. A service with no
        # log is a service you cannot debug, which defeats the point of making
        # the relay unkillable. Set them here, but let .env win if it says
        # otherwise.
        os.environ.setdefault("PYTHONUTF8", "1")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        os.environ.setdefault("ARK_LOG_FILE", str(HERE / "relay.log"))

        from ark_relay.__main__ import _force_utf8_console, _load_dotenv, _setup_logging
        _force_utf8_console()
        # Absolute path: a service starts with an unrelated working directory,
        # and a silently empty config would disable every push channel.
        _load_dotenv(HERE / ".env")
        _setup_logging(verbose=False)

        from ark_relay.config import SERVER_TZ, Config, both_clocks
        from ark_relay.core import State
        from ark_relay.engine import Engine
        from ark_relay.notify import Notifier
        from ark_relay.transport import LocalSource

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

        # New code before anything else uses it. This block was silently lost
        # in a refactor on 2026-08-17 - a range replace swallowed it - and for
        # three commits the machine stopped receiving updates at all while the
        # log still looked healthy. Keep it adjacent to its own marker.
        try:
            from ark_relay import selfupdate

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
                subprocess.Popen(  # noqa: S603
                    ["cmd", "/c", "timeout /t 3 /nobreak >nul & "
                                  "net stop ark-relay & net start ark-relay"],
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.DETACHED_PROCESS))
                return
        except Exception:  # noqa: BLE001 - never let this stop the relay
            log.exception("自更新出错，跳过")

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
                if errors := notifier.send("⚠️ 中继自更新没成功", body):
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
        except Exception:  # noqa: BLE001 - a receipt must never break the relay
            log.exception("推送更新通知出错，跳过")

        from ark_relay.inbox import Inbox

        inbox = Inbox(cfg.state_dir, cfg.inbox_url,
                      cfg.maaend_dir or _maaend_dir(cfg), cfg.automas_dir)

        # A config command that arrives while a queue is running waits here
        # until every script has stopped, then lands.
        deferred_inbox = [False]

        def collect(reason: str) -> None:
            """Check for queued changes and push whatever landed.

            改配置必须避开脚本运行期。AUTO-MAS 在跑的时候会用它内存里的那份
            覆写 ScriptConfig.json，此时写进去的值会被静静冲掉——2026-08-20
            实测两次：set_wait_time 120 被冲回 60，剿灭开关被冲回打开，于是
            每轮又白跑一次剿灭。engine.scripts_running() 本来就是为这件事
            准备的守卫，这里补上调用。
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
            except Exception:  # noqa: BLE001 - never let this stop the relay
                log.exception("待办检查出错，跳过")
                return
            if messages:
                for m in messages:
                    log.info("待办: %s", m)
                notifier.send(messages[0], "\n".join(messages[1:]).strip())
            else:
                log.debug("待办检查（%s）：无新配置（当前 v%s）", reason, version)

        # Once, at startup. The machine boots for each queue, so a change
        # pushed while it is off - which is nearly always - lands before that
        # day's run. Re-checking on a timer was added and removed again: it
        # bought nothing the boot check did not already cover.
        collect("启动")

        # A new game-week means last week's 剿灭 no longer counts.
        try:
            if msg := engine._annihilation.maybe_reopen():  # noqa: SLF001
                notifier.send("🗓️ 剿灭", msg)
        except Exception:  # noqa: BLE001
            log.exception("剿灭周期检查出错，跳过")

        # Assert the annihilation switch once at startup rather than leaving it
        # to tick(): ticks are driven by file events and alarms, and neither has
        # fired yet on a machine that just booted. By the time the first tick
        # arrives it is usually the queue's own start time, so that round would
        # still pay for the pointless annihilation pass.
        engine._enforce_annihilation()  # noqa: SLF001

        # Wake on the directory changing, not on a timer. AUTO-MAS writes a
        # run record the moment a script finishes, and Windows will say so;
        # asking every thirty seconds instead was just the lazy way to find out.
        #
        # The timeout stays, because some of what tick() does is genuinely
        # time-based - the report cutoff, "a queue was due and produced
        # nothing", the shutdown window - and none of those are announced by a
        # file appearing. So: whichever comes first, a change or the interval.
        watch = None
        try:
            if cfg.history_dir:
                watch = win32file.FindFirstChangeNotification(
                    str(cfg.history_dir), True,   # True = include subdirectories
                    win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                    | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
                log.info("已挂上目录变更通知，记录一落盘立即处理")
        except Exception:  # noqa: BLE001 - a missing notifier must not stop the relay
            log.exception("目录变更通知挂载失败，退回定时检查")
            watch = None

        # Four things can wake this loop, none of them a timer: the service
        # being stopped, a run record landing on disk, the AUTO-MAS backend
        # dying, and a python.exe starting (so a freshly launched backend gets
        # its handle immediately instead of at the next liveness check). The
        # timeout is not an interval either - it is an alarm clock. The engine
        # knows the exact next moment any clock-based decision can change
        # (a missed-run alert coming due, the report cutoff, a wake-up
        # checkpoint), so the loop sleeps until precisely then.
        automas = _automas_handle()
        if automas:
            log.info("已挂上 AUTO-MAS 进程句柄，它一退出立即拉起")
        proc_evt = win32event.CreateEvent(None, 0, 0, None)
        wmi_alive = {"ok": False}
        wmi_alive["ok"] = _start_process_watch(proc_evt, wmi_alive, log)
        if wmi_alive["ok"]:
            log.info("已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄")
        else:
            log.warning("进程启动事件订阅不可用，AUTO-MAS 缺席时退回 %d 秒活性检查",
                        AUTOMAS_CHECK_SECONDS)

        # If every alarm is far away (or there are none), still wake
        # occasionally: an alarm-clock with a bug in it must degrade into
        # lateness, not into a relay that sleeps forever.
        backstop = 3600.0
        last_alarm_note = ""
        # One-shot deadline for "AUTO-MAS should have appeared by now" - armed
        # only while no handle is held. Doubles on every failed revival so a
        # broken backend is retried with backoff, never on a beat.
        revive_wait = float(REVIVE_FIRST_WAIT)
        revive_deadline = (time.monotonic() + revive_wait) if not automas else None
        revive_failures = 0
        revive_alerted = False
        next_automas_check = 0.0
        next_inbox_retry = 0.0
        while True:
            handles = [self.stop_event, proc_evt]
            proc_idx = 1
            watch_idx = automas_idx = -1
            if watch:
                handles.append(watch); watch_idx = len(handles) - 1
            if automas:
                handles.append(automas); automas_idx = len(handles) - 1
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
            except Exception:  # noqa: BLE001 - a broken alarm must not stop the loop
                log.exception("计算下一个时刻出错，退回备用间隔")
            if not automas:
                if wmi_alive["ok"] and revive_deadline is not None:
                    # Event-driven path: sleep exactly until the revival
                    # deadline; a start event will wake us sooner.
                    wait_s = min(wait_s, max(1.0, revive_deadline - time.monotonic()))
                elif not wmi_alive["ok"]:
                    # Degraded path: no start events, so liveness has to be
                    # re-checked on a timer until a handle can be re-acquired.
                    wait_s = min(wait_s, AUTOMAS_CHECK_SECONDS)
            if not inbox.last_fetch_ok:
                wait_s = min(wait_s, 300)   # wake in time for the fetch retry
            rc = win32event.WaitForMultipleObjects(
                handles, False, int(wait_s * 1000))
            if rc == win32event.WAIT_OBJECT_0:
                log.info("收到停止信号，退出")
                if watch:
                    win32file.FindCloseChangeNotification(watch)
                return
            if rc == win32event.WAIT_OBJECT_0 + proc_idx and not automas:
                # Some python.exe just started; adopt it if it is the backend.
                if automas := _automas_handle():
                    log.info("AUTO-MAS 已启动，进程句柄已挂上")
                    revive_deadline = None
                    revive_wait = float(REVIVE_FIRST_WAIT)
                    revive_failures = 0
                    revive_alerted = False
            if watch and rc == win32event.WAIT_OBJECT_0 + watch_idx:
                # Re-arm before handling, so a write that lands while we work is
                # not lost. A record that appears during tick() would otherwise
                # wait for the timeout - the exact latency this removes.
                #
                # Re-arming can fail, and it used to fail silently: the handle
                # then never signals again, the loop falls back to waking only
                # on the alarm clock, and run records sit unprocessed until the
                # next clock-based deadline - up to the hour-long backstop.
                # Everything still happens, just late and with no indication
                # why. Degrading quietly is the failure mode this system has
                # been bitten by most, so say it out loud.
                try:
                    win32file.FindNextChangeNotification(watch)
                except Exception:  # noqa: BLE001 - report and degrade knowingly
                    log.exception("目录变更通知重新武装失败，改用闹钟兜底")
                    try:
                        win32file.FindCloseChangeNotification(watch)
                    except Exception:  # noqa: BLE001
                        pass
                    watch = None
                    notifier.send(
                        "⚠️ 中继的目录监听掉了",
                        "运行记录不再是一落盘就处理，要等下一个定时判定点才会被读到"
                        "（最长一小时）。功能还在，只是变慢。\n"
                        "重启中继即可恢复：net stop ark-relay & net start ark-relay")
                # AUTO-MAS writes the .json and .log separately; give it a
                # moment so the first notification does not read a half-file.
                time.sleep(2)

            try:
                engine.tick()
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("本轮处理出错，继续")

            # A pause order that failed to download is not a pause order. On
            # 2026-08-17 the queue file was unreachable all evening and the
            # operator's stop order silently never arrived - so a failed boot
            # fetch is retried every five minutes until the file has actually
            # been read once, instead of waiting a whole day for the next boot.
            if not inbox.last_fetch_ok and time.monotonic() >= next_inbox_retry:
                next_inbox_retry = time.monotonic() + 300
                collect("重试")

            # Scripts have just stopped: apply the config commands that were
            # deferred, now that a write will not be clobbered.
            if deferred_inbox[0] and not engine.scripts_running():
                log.info("脚本已停，补做之前推迟的待办检查")
                collect("推迟补做")

            now = time.monotonic()
            died = bool(automas) and rc == win32event.WAIT_OBJECT_0 + automas_idx
            if died:
                log.warning("AUTO-MAS 后端退出了")
                win32api.CloseHandle(automas)
                automas = None
            due_check = (
                automas is None
                and ((wmi_alive["ok"] and revive_deadline is not None
                      and now >= revive_deadline)
                     or (not wmi_alive["ok"] and now >= next_automas_check)))
            if died or due_check:
                next_automas_check = now + AUTOMAS_CHECK_SECONDS
                if not _automas_running():
                    log.warning("AUTO-MAS 后端不在，正在拉起（第 %d 次）",
                                revive_failures + 1)
                    _revive_automas()
                    revive_failures += 1
                    if revive_failures >= REVIVE_ALERT_AFTER and not revive_alerted:
                        revive_alerted = True
                        notifier.send(
                            "🔌 AUTO-MAS 拉不起来",
                            f"已连续尝试拉起 {revive_failures} 次仍不见后端进程，"
                            "需要人工看一眼。服务会按翻倍退避继续重试。")
                # Adopt whichever backend now exists - our revival, or one that
                # was there all along. A revived backend is a new process, so
                # the old handle (already closed above) never signals again.
                if automas := _automas_handle():
                    log.info("AUTO-MAS 进程句柄已挂上")
                    revive_deadline = None
                    revive_wait = float(REVIVE_FIRST_WAIT)
                    revive_failures = 0
                    revive_alerted = False
                else:
                    # Arm with the CURRENT wait, then double for the next
                    # failure - doubling first made the very first retry gap
                    # 360s instead of the documented 180s.
                    revive_deadline = now + revive_wait
                    revive_wait = min(revive_wait * 2, float(REVIVE_MAX_WAIT))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Launched by the SCM rather than from a shell.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ArkRelayService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ArkRelayService)
