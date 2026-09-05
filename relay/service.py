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
import threading
import time
from datetime import datetime, timedelta
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
# How long a *live* Electron shell with no backend is left alone before the
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
        except (ValueError, Exception):  # noqa: B014 - pywin32 raises its own
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
        """订阅、监听、断了就重订阅——不要监听一断就永久退化。

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
                        watcher.NextEvent()   # 阻塞到内核报告一次进程启动
                        win32event.SetEvent(evt)
                except Exception:  # noqa: BLE001 - 降级但绝不放弃
                    # 完整堆栈只写第一次，之后写一行：WMI 要是彻底坏了，
                    # 60 秒重试一次会把日志刷爆。
                    if not logged_detail:
                        log.exception(
                            "进程启动事件监听中断，改用 %d 秒活性检查，"
                            "%.0f 秒后重订阅",
                            AUTOMAS_CHECK_SECONDS, delay)
                        logged_detail = True
                    else:
                        log.warning("进程启动事件重订阅失败，%.0f 秒后再试", delay)
                    alive["ok"] = False
                    win32event.SetEvent(evt)   # 唤醒主循环，让它看到降级
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



def ensure_automas(timeout: float = 45) -> bool:
    """AUTO-MAS 接口不在就拉起来等它上线。用户 2026-09-03：「MAS 不在的时候你要拉起他，
    不希望见到任何理由开机时检测不到配置，而且要快。」"""
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
    """这次开机的标识：开机时刻到分钟。部署重启服务不改变它。"""
    try:
        import ctypes  # noqa: PLC0415
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong  # 64 位，别截断
        up_ms = ctypes.windll.kernel32.GetTickCount64()
        return (now - timedelta(milliseconds=int(up_ms))).strftime("%Y%m%d%H%M")
    except Exception:  # noqa: BLE001
        return now.strftime("%Y%m%d%H")


def _seconds_to_next_queue(automas_dir, now: datetime) -> float:
    """离今天下一趟队列还有多少秒；今天没有了就给晚上的大预算。"""
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
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):  # noqa: N802 - name required by the framework
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        # 手机通道那条长连接必须主动掐断，否则它在 socket 读上阻塞着，
        # 服务停不下来——2026-08-31 连着几次卡在 STOP_PENDING。
        box = getattr(self, "_mailbox", None)
        if box is not None:
            box.close()
        # 硬保险：15 秒还没退干净就强制退出进程。
        # 用户 2026-08-31：「中继服务卡在 STOP_PENDING 这个不要再出现了，
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:SvcStop」
        killer = threading.Timer(15, lambda: os._exit(0))
        killer.daemon = True     # 它自己不能反过来拖住退出
        killer.start()

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
        """开机流程。每一步一个函数，顺序就是这里写的顺序。"""
        booted = _stage_bootstrap()
        if booted is None:
            return
        log, cfg, notifier, engine = booted
        _stage_patch_okww(cfg, notifier, log)
        # New code before anything else uses it. This block was silently lost
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
    """开机第一步：环境变量、日志、配置、引擎。配置不可用返回 None。"""
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

    from ark_relay.config import Config
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
    return log, cfg, notifier, engine


def _stage_patch_okww(cfg, notifier, log) -> None:
    """每次启动贴一次 OK-WW 补丁（幂等）。"""
    # 每次启动都贴一次 OK-WW 补丁——幂等，在位就一句话都不写。
    # 「更新必须立即生效」是死命令，部署完就该是最终状态，不能留一个
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_patch_okww」
    try:
        # 就地 import：模块级 import 会在服务安装阶段就被求值，
        # 而 ark_relay 那时还不一定在 sys.path 上。
        from ark_relay import okww_patch as _okww_patch  # noqa: PLC0415

        okww_at_boot = cfg.okww_dir or (
            Path(cfg.automas_dir).parent / "okww" if cfg.automas_dir else None)
        for note in _okww_patch.ensure_patches(okww_at_boot):
            log.info("启动：%s", note)
            notifier.send("🩹 OK-WW 补丁", note)
    except Exception:  # noqa: BLE001 - 贴不上也不能挡住服务启动
        log.exception("启动时贴 OK-WW 补丁失败，服务照常继续")


def _stage_selfupdate(log) -> bool:
    """拉新代码；真更新了就发起重启并返回 True，调用方立刻退出。"""
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
    return False


def _stage_announce_update(notifier, log) -> None:
    """新代码起来之后的第一件事：把「更新失败 / 已更新」播出去。"""
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
            if errors := notifier.send("⚠️ 中继自更新没成功", body, alert=True):
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
            # 人话优先。用户 2026-08-26：「更新内容用人话写」——
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
    except Exception:  # noqa: BLE001 - a receipt must never break the relay
        log.exception("推送更新通知出错，跳过")


def _stage_inbox_and_phone(svc, cfg, engine, notifier, log):
    """待办信箱 + 手机通道。返回 (inbox, collect, deferred_inbox)，主循环要用。"""
    from ark_relay.inbox import Inbox

    inbox = Inbox(cfg.state_dir, cfg.inbox_url,
                  cfg.maaend_dir or _maaend_dir(cfg), cfg.automas_dir)

    # A config command that arrives while a queue is running waits here
    # until every script has stopped, then lands.
    deferred_inbox = [False]

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
    # 在线/离线不许靠轮询。做法见 phone.py 的模块说明。
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_inbox_and_phone」
    from ark_relay.commands import apply_command
    from ark_relay.phone import Mailbox

    box = Mailbox(cfg.phone_topic, cfg.phone_pin, cfg.state_dir)
    svc._mailbox = box          # SvcStop 要用它掐断长连接

    def push_state(why: str) -> None:
        if not box.enabled:
            return
        try:
            from ark_relay.phone import state_payload
            box.publish(state_payload(cfg, cfg.state_dir))
            log.info("📱 已上报状态到手机（%s）", why)
        except Exception:  # noqa: BLE001 - 上报失败不许拖垮中继
            log.warning("状态没能上报到手机（%s）", why, exc_info=True)

    from ark_relay.phone import Heartbeat  # noqa: PLC0415
    hb = Heartbeat(box.topic, cfg.state_dir)

    def run_phone_cmd(body: dict) -> None:
        """手机上按的一条。刷新只回状态；其余是真改配置，改完立刻通知。"""
        action = str((body or {}).get("action") or "")
        if action == "refresh":
            ensure_automas()          # 读配置前先保证它活着
            push_state("手机请求")
            return
        if action == "watch":
            hb.watch()          # 页面打开了：这 10 分钟每 30 秒跳一次
            return
        if action == "estop":
            # 红按钮：恰恰是脚本在跑的时候才按，不能被下面那道门拦住
            from ark_relay import commands as _cmd  # noqa: PLC0415
            ok, msg = _cmd.estop()
            log.warning("🛑 红按钮：%s", msg)
            notifier.send("🛑 已停一切", msg)
            push_state("红按钮")
            return
        if engine.scripts_running():
            # 脚本在跑的时候改配置会被 AUTO-MAS 用内存里那份冲掉。
            notifier.send("📱 手机指令暂缓",
                          f"「{action}」现在不能执行：脚本正在运行，"
                          "此时改配置会被冲掉。等这一趟跑完再按一次。")
            return
        ok, msg = apply_command(body)
        log.info("📱 手机指令 %s：%s", action, msg)
        # 用户 2026-08-31 要的：按下保存之后要有通知说改动成功。
        notifier.send("📱 配置已修改" if ok else "📱 配置没改成", msg)
        push_state("改完配置")

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
        # ToDesk 式在线状态：页面说「我在看」才跳，停服务时发 bye。
        # 页面靠它自动翻开机/关机，不用人手动刷新（用户 2026-09-02 要的）。
        threading.Thread(
            target=lambda: hb.loop(
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0),
            name="phone-heartbeat", daemon=True).start()

    # 关机前最后拉一次待办 + 上报一次状态：人可能刚在手机上按了
    # 「今晚别关机」，而且手机上那份状态得停在机器关机那一刻的样子。
    def before_shutdown() -> None:
        collect("关机前")
        push_state("关机前")

    engine._before_shutdown = before_shutdown  # noqa: SLF001
    collect("启动")
    return inbox, collect, deferred_inbox


def _stage_preupdate(cfg, notifier, log) -> None:
    """开机窗口里把四个程序的更新做掉（一天一次）。"""
    # MaaEnd updates itself at startup and restarts its own process when it
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
    try:
        # okww_patch 2026-08-26 之前一直漏在这行外面：下面 549 行用它，
        # 一跑到就 NameError，也就是说**补丁重贴从来没有真正执行过**。
        # tests/test_undefined_names.py 就是为了这类错加的。
        from ark_relay import okww_patch, plan, preupdate  # noqa: PLC0415

        # 一天跑一遍就够：每次服务重启都重跑，会把 MAA/MaaEnd/OK-WW
        # 挨个再拉起来查一遍更新。2026-08-31 我一上午部署三次，
        # 它跑了三次，第三次 MAA 没在 180 秒内答话，报了「没能确认」。
        _pre_now = datetime.now(tz=SERVER_TZ)
        if (preupdate.wanted_today(cfg.automas_dir)
                and preupdate.should_run(cfg.state_dir, _pre_now)):
            ensure_automas()          # 09-03 01:08：AUTO-MAS 被关着，预更新问了 180 秒
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
            # Anything that could not be *checked* lands here. A pre-update
            # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
            problems: list[str] = []
            # MAA first: its update is applied by a delegated process at
            # startup, so getting it out of the way is quick and the
            # launch of MaaEnd afterwards is unaffected either way.
            if note := preupdate.run_maa(maa, problems=problems):
                log.info("预更新：%s", note)
                notifier.send("🆕 预更新", note)
            if updated := preupdate.run(maaend, problems=problems):
                log.info("预更新：MaaEnd 已更新：%s", updated)
                notifier.send("🆕 预更新",
                              f"MaaEnd 已更新：{updated}")
            try:
                from ark_relay import gameupdate as _gu  # noqa: PLC0415
                if back := _gu.maaend_reenable_if_updated(cfg):
                    log.info("预更新：%s", back)
                    notifier.send("🔓 终末地日常已开回", back)
            except Exception:  # noqa: BLE001
                log.exception("开回 MaaEnd 任务出错")
            # AUTO-MAS is asked, not launched - it is already running.
            if note := preupdate.run_automas(cfg.automas_dir,
                                             problems=problems):
                notifier.send("🆕 预更新", note)
            # OK-WW last: it is the newest of the four and the only one whose
            # update comes from a CNB git mirror rather than MirrorChyan.
            okww = cfg.okww_dir or (Path(cfg.automas_dir).parent / "okww"
                                    if cfg.automas_dir else None)
            # OK-WW 的自动更新会整段覆盖 src，把本地补丁抹掉
            # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
            if note := preupdate.run_okww(okww, problems=problems):
                log.info("预更新：%s", note)
                notifier.send("🆕 预更新", note)
            for note in okww_patch.ensure_patches(okww):
                log.info("预更新：%s", note)
                notifier.send("🩹 OK-WW 补丁", note)
            preupdate.mark_run(cfg.state_dir, _pre_now,
                               clean=not problems)
            if problems:
                # An alert, not a routine note: a silent pre-update leaves
                # the machine running a version nobody chose.
                body = "\n".join(f"· {p}" for p in problems)
                log.error("预更新有 %d 项没能确认：\n%s", len(problems), body)
                notifier.send(
                    f"⚠️ 预更新没能确认（{len(problems)} 项）",
                    body + "\n\n这不是「无需更新」——是这一轮没能确认有没有更新。"
                           "机器可能仍在跑旧版本。",
                    alert=True)
    except Exception:  # noqa: BLE001 - a pre-update must never stop the relay
        log.exception("预更新出错，跳过（本轮照旧）")


def _stage_reenable_maaend(cfg, notifier, log) -> None:
    """MaaEnd 换版本后把临时关掉的任务开回来。"""
    # MaaEnd 换了版本就把 09-02 关掉的四项开回来。放在预更新块外面：09-03 早上
    # 预更新因为凌晨已经跑过而跳过，这一步跟着没跑，四项一直关着。
    try:
        from ark_relay import gameupdate as _gu2  # noqa: PLC0415
        for back in (_gu2.maaend_reenable_if_updated(cfg), _gu2.maaend_reenable_next_boot(cfg),
                     _gu2.maaend_reenable_spmed_if_updated(cfg)):
            if back:
                log.info("开机：%s", back)
                notifier.send("🔓 终末地日常已开回", back)
    except Exception:  # noqa: BLE001
        log.exception("开回 MaaEnd 任务出错")


def _stage_gameupdate(cfg, notifier, log) -> None:
    """大版本更新日：登记要更新的游戏客户端。"""
    # 大版本更新日把游戏客户端也更新掉（用户 2026-09-02 要的）。
    # 每次开机一遍：早班窗口短，只够方舟装包 / 给启动器点一下更新；
    # 晚班只跑 MAA，终末地和鸣潮的大包放这里下。预算 = 离下一趟队列还有多久。
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
                notifier.send("🆕 游戏更新", n)
            if gproblems:
                body = "\n".join(f"· {x}" for x in gproblems)
                log.warning("游戏更新有 %d 项没能确认：\n%s", len(gproblems), body)
                notifier.send(f"⚠️ 游戏更新没能确认（{len(gproblems)} 项）", body)
            gameupdate.mark_run(cfg.state_dir, _gu_now, boot_id=_boot_id)
    except Exception:  # noqa: BLE001 - 更新客户端出错不能拖垮中继
        log.exception("游戏更新出错，跳过（本轮照旧）")


def _stage_annihilation(engine, notifier, log) -> None:
    """新的一周恢复剿灭，并在开机时校正一次开关。"""
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


def _loop(svc, cfg, engine, notifier, inbox, collect, deferred_inbox, log) -> None:
    """主循环：等事件或闹钟，跑 tick，拉起 AUTO-MAS。"""
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
        log.exception("目录变更通知挂载失败，先退回定时检查，稍后自动重试")
        watch = None
    # 重建节奏。开机时挂载失败（比如目录还没就绪）同样要进重试，
    # 不能只有「重新武装失败」那条路才有。
    watch_retry_at = time.monotonic() + 5.0
    watch_retry_delay = 5.0

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
    # When the shell was first seen alive with no backend behind it.
    shell_only_since = None
    shell_grace_noted = False
    next_automas_check = 0.0
    next_inbox_retry = 0.0
    while True:
        # 监听掉了就退避重建。重建成功后运行记录重新变成「一落盘就处理」。
        if watch is None and cfg.history_dir \
                and time.monotonic() >= watch_retry_at:
            try:
                watch = win32file.FindFirstChangeNotification(
                    str(cfg.history_dir), True,
                    win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                    | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
                log.info("目录变更通知已重建，恢复「记录一落盘立即处理」")
                watch_retry_delay = 5.0
            except Exception:  # noqa: BLE001 - 重建失败就再等等，别刷屏
                watch = None
                watch_retry_delay = min(watch_retry_delay * 2, 60.0)
                log.warning("目录变更通知重建失败，%.0f 秒后再试",
                            watch_retry_delay)
            watch_retry_at = time.monotonic() + watch_retry_delay

        handles = [svc.stop_event, proc_evt]
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
                # 重建时刻：掉了不是终点。原来这里只发一条「去重启中继」
                # 就完事，剩下整个开机周期都靠闹钟兜底——和 WMI 订阅那个
                # 一次性 bug 是同一族（2026-08-30 全量审查一起修的）。
                watch_retry_at = time.monotonic() + 5.0
                watch_retry_delay = 5.0
                notifier.send(
                    "⚠️ 中继的目录监听掉了",
                    "运行记录暂时不再是一落盘就处理，要等下一个定时判定点"
                    "（最长一小时）。中继会自己反复重建监听，恢复了就不用管；\n"
                    "如果这条之后一直没恢复，重启中继：\n"
                    "net stop ark-relay & net start ark-relay",
                    alert=True)
            # AUTO-MAS writes the .json and .log separately; give it a
            # moment so the first notification does not read a half-file.
            time.sleep(2)

        try:
            engine.tick()
        except Exception:  # noqa: BLE001 - the loop must survive anything
            log.exception("本轮处理出错，继续")

        # A pause order that failed to download is not a pause order. On
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_loop」
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
                # Two gates before the force-kill, because reviving is not
                # free: it kills a window somebody may be looking at.
                if _installer_running():
                    log.warning("AUTO-MAS 后端不在，但安装程序正在运行——不动它")
                    shell_only_since = None
                    shell_grace_noted = False
                elif _automas_shell_running():
                    # Shell up, backend down. Either the stuck state this
                    # guard exists for, or a first run still setting itself
                    # up. Only the clock tells them apart, so wait.
                    if shell_only_since is None:
                        shell_only_since = now
                    waited = now - shell_only_since
                    if waited < SHELL_GRACE_SECONDS:
                        if not shell_grace_noted:
                            shell_grace_noted = True
                            log.warning(
                                "AUTO-MAS 窗口在、后端不在，先等 %d 分钟再动"
                                "（可能正在首次配置或更新）",
                                SHELL_GRACE_SECONDS // 60)
                    else:
                        log.warning("AUTO-MAS 窗口在、后端已缺席 %d 分钟，"
                                    "正在拉起（第 %d 次）",
                                    int(waited // 60), revive_failures + 1)
                        _revive_automas()
                        revive_failures += 1
                else:
                    # No shell at all: nothing to kill, so revive at once.
                    log.warning("AUTO-MAS 后端不在，正在拉起（第 %d 次）",
                                revive_failures + 1)
                    _revive_automas()
                    revive_failures += 1
                if revive_failures >= REVIVE_ALERT_AFTER and not revive_alerted:
                    revive_alerted = True
                    notifier.send(
                        "🔌 AUTO-MAS 拉不起来",
                        f"已连续尝试拉起 {revive_failures} 次仍不见后端进程，"
                        "需要人工看一眼。服务会按翻倍退避继续重试。",
                        alert=True)
            # Adopt whichever backend now exists - our revival, or one that
            # was there all along. A revived backend is a new process, so
            # the old handle (already closed above) never signals again.
            if automas := _automas_handle():
                log.info("AUTO-MAS 进程句柄已挂上")
                shell_only_since = None
                shell_grace_noted = False
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
