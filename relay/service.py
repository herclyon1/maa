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
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

import servicemanager  # noqa: E402
import win32event  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

# How often to check that AUTO-MAS is still alive. It is only checked, never
# polled for liveness the way a task would poll the relay - a missing AUTO-MAS
# is not urgent to the second, and relaunching it costs a desktop window.
AUTOMAS_CHECK_SECONDS = 120
# How often to re-check for queued config changes while already running.
INBOX_CHECK_SECONDS = 300
AUTOMAS_TASK = "AUTO-MAS_AutoStart"


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
        log.info("服务模式启动，监视 %s（每 %d 秒）", cfg.history_dir, cfg.poll_seconds)

        from ark_relay.inbox import Inbox

        inbox = Inbox(cfg.state_dir, cfg.inbox_url,
                      cfg.maaend_dir or _maaend_dir(cfg), cfg.automas_dir)

        def collect(reason: str) -> None:
            """Check for queued changes and push whatever landed."""
            try:
                version, messages = inbox.poll()
            except Exception:  # noqa: BLE001 - never let this stop the relay
                log.exception("待办检查出错，跳过")
                return
            if messages:
                for m in messages:
                    log.info("待办: %s", m)
                notifier.send(f"⚙️ 配置已更新 v{version}", "\n".join(messages[1:]))
            else:
                log.debug("待办检查（%s）：无新配置（当前 v%s）", reason, version)

        collect("启动")

        next_automas_check = 0.0
        next_inbox_check = time.monotonic() + INBOX_CHECK_SECONDS
        while True:
            # Wait for either the stop signal or the next poll. Sleeping on the
            # event rather than time.sleep is what makes "stop" immediate
            # instead of up to one poll interval late.
            if win32event.WaitForSingleObject(
                self.stop_event, cfg.poll_seconds * 1000
            ) == win32event.WAIT_OBJECT_0:
                log.info("收到停止信号，退出")
                return

            try:
                engine.tick()
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("本轮处理出错，继续")

            now = time.monotonic()
            # A change pushed while the machine is already awake must not have
            # to wait for the next boot - the operator pushes it precisely
            # because they want it to apply. Only when nothing is running,
            # though: AUTO-MAS reads its config as it launches each script.
            if now >= next_inbox_check and not engine.scripts_running():
                next_inbox_check = now + INBOX_CHECK_SECONDS
                collect("轮次")

            if now >= next_automas_check:
                next_automas_check = now + AUTOMAS_CHECK_SECONDS
                if not _automas_running():
                    log.warning("AUTO-MAS 后端不在，正在拉起")
                    _revive_automas()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Launched by the SCM rather than from a shell.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ArkRelayService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ArkRelayService)
