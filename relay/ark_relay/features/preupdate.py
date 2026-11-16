"""Shared parts of the pre-update: log reading, closing a program, and starting a
GUI program on the interactive desktop from the relay's service session."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import uuid
import json
import time
import re
from pathlib import Path
from typing import Callable
from ark_relay.core.config import mas_base, atomic_write_text, SERVER_TZ
from datetime import datetime

log = logging.getLogger("ark.preupdate")

# Hang guards of the subprocess calls in the pre-update: the most one call may take,
# not what it takes (pwsh + Get-CimInstance measured 0.39-0.54 s on the game machine,
# 2026-10-13 11:08). preupdate.worst_case_seconds() sums them.
PWSH_GUARD_S = 60
TASKKILL_GUARD_S = 30


def going_down() -> bool:
    """The relay is stopping (SvcStop, or Windows going down). Every pre-update wait asks
    this at each poll, as boot_stages._stop_requested does: on 2026-10-16 02:35 a deploy
    rollback stopped the relay while the OK-WW wait could not hear it, and the 15 s hard
    exit killed the process before the auto-start switch was put back."""
    from ark_relay.features import errwatch  # noqa: PLC0415 - errwatch is heavy; only at call time
    return errwatch.going_down()


def _note(problems: list[str] | None, msg: str) -> None:
    """Append msg to problems (when given): something the caller alerts on.

    Used for "could not tell", which must not read as "nothing to do".
    """
    if problems is not None:
        problems.append(msg)


def _span(old: str, new: str) -> str:
    """「旧版 → 新版」, the shape every program's update notice uses.

    When the old version is empty or equal to the new one (the process that
    restarted after an update reports the new version as its current one), the
    old side reads 「（旧版本没读到）」.
    """
    if old and old != new:
        return f"{old} → {new}"
    return f"（旧版本没读到）→ {new}"


def _close(exe: Path) -> None:
    """Leave nothing running. AUTO-MAS kills it before every round anyway, but a pre-update
    that leaves a window on the desktop is a pre-update that changed the thing it
    was supposed to leave alone."""
    try:
        subprocess.run(
            ["taskkill", "/IM", exe.name, "/F"],
            capture_output=True, timeout=TASKKILL_GUARD_S, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("预更新：关闭 %s 失败", exe.name, exc_info=True)


# The direct route. The installed relay (app_main.py) runs in the logged-on user's session,
# elevated (\ArkRelay\main has highest privileges); the scheduled task below was for the
# old service in session 0. From there a program is started directly, with no PowerShell and
# no 3 s wait (audit 11-08 A-21). Two things the task route gave are kept:
# * the user's own environment (CreateEnvironmentBlock), not the relay's (PYTHONUTF8 and the
#   ARK_* variables would reach OK-WW's own Python);
# * a life of its own: the relay is the process of the \ArkRelay\main task, and ending that
#   task (schtasks /end, as estop.sh does) can end what runs in its job. Out of the job with
#   CREATE_BREAKAWAY_FROM_JOB, as pkg_layout.restart_soon does for its helper; where the job
#   does not allow that, the task route from then on.
# Win32 values (learn.microsoft.com "Process Creation Flags", "STARTUPINFOA"); subprocess
# names them on Windows only.
_CREATE_NEW_CONSOLE = 0x00000010
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESHOWWINDOW = 0x00000001
_SW_SHOWMINNOACTIVE = 7
_TOKEN_ELEVATION = 20           # TOKEN_INFORMATION_CLASS TokenElevation
_ERROR_ACCESS_DENIED = 5        # CreateProcess with CREATE_BREAKAWAY_FROM_JOB in a job that forbids it
# Set once breakaway was refused: every later start takes the task route.
_direct_refused = [False]
# Why the last start did not go direct, said once per reason in relay.log (INFO): after a
# deploy, 「直接启动了」 lines say the route runs; this says why it does not.
_not_here_said = [""]


def _not_here(why: str) -> bool:
    if _not_here_said[0] != why:
        _not_here_said[0] = why
        log.info("预更新：%s，程序走计划任务启动", why)
    return False


def _here_in_console() -> bool:
    """Whether this process runs elevated in the active console session (the installed
    relay). False when it cannot be told: the scheduled task is the route then."""
    try:
        import win32api  # noqa: PLC0415
        import win32security  # noqa: PLC0415
        import win32ts  # noqa: PLC0415
        session = win32ts.WTSGetActiveConsoleSessionId()
        own = win32ts.ProcessIdToSessionId(os.getpid())
        if session in (0, 0xFFFFFFFF) or own != session:
            return _not_here(f"中继在会话 {own}，桌面在会话 {session}")
        tok = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        if not win32security.GetTokenInformation(tok, getattr(win32security, "TokenElevation", _TOKEN_ELEVATION)):
            return _not_here("中继没有管理员权限")
        return True
    except Exception as exc:  # noqa: BLE001 - not Windows, no pywin32, a call refused: the task route
        return _not_here(f"看不出中继是不是在桌面会话里（{type(exc).__name__}: {exc}）")


def _logon_env() -> "dict | None":
    """The logged-on user's own environment (what a new logon gives a program), None when
    it cannot be built."""
    try:
        import win32api  # noqa: PLC0415
        import win32con  # noqa: PLC0415
        import win32profile  # noqa: PLC0415
        import win32security  # noqa: PLC0415
        tok = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY | win32con.TOKEN_DUPLICATE | win32con.TOKEN_IMPERSONATE)
        env = win32profile.CreateEnvironmentBlock(tok, False)
        return {str(k): str(v) for k, v in dict(env).items() if k and "=" not in str(k)[1:]}
    except Exception:  # the task route then
        log.debug("预更新：取不到登录用户的环境变量，走计划任务", exc_info=True)
        return None


def _spawn_here(exe: Path, cwd: Path, args: tuple[str, ...] = (), *, minimized: bool = False,
                hidden: bool = False, label: "str | None" = None) -> bool:
    """Start exe from this process when it already runs elevated on the desktop. True when
    started; False when not tried or refused - the caller takes the task route then."""
    if _direct_refused[0] or not _here_in_console():
        return False
    env = _logon_env()
    if env is None:
        return False
    flags = ((_CREATE_NO_WINDOW if hidden else _CREATE_NEW_CONSOLE)
             | _CREATE_NEW_PROCESS_GROUP | _CREATE_BREAKAWAY_FROM_JOB)
    startup = None
    if minimized:
        # A program may ignore this and show its window anyway (as _startup_info says).
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= _STARTF_USESHOWWINDOW
        startup.wShowWindow = _SW_SHOWMINNOACTIVE
    try:
        subprocess.Popen([str(exe), *args], cwd=str(cwd), env=env, creationflags=flags, startupinfo=startup)
    except OSError as exc:
        if getattr(exc, "winerror", None) == _ERROR_ACCESS_DENIED:
            _direct_refused[0] = True
            log.info("预更新：中继所在的计划任务不许它启动的程序脱离出去，%s 和之后的程序都走计划任务启动", exe.name)
        else:
            log.info("预更新：直接启动 %s 没成（%s: %s），改走计划任务", exe.name, type(exc).__name__, exc)
        return False
    log.info("预更新：中继就在桌面会话里，直接启动了 %s", label or exe.name)
    return True


# The scheduled-task route. The relay's service host cannot get the console
# user's token (WTSQueryUserToken fails with 1314, SE_TCB_NAME not enabled), so a
# GUI program is started by the Task Scheduler service with an Interactive
# logon instead; the caller then needs no SE_TCB_NAME.
def _task_name(stem: str) -> str:
    return "ark-preupdate-launch-" + "".join(c if c.isalnum() else "-" for c in stem)[:40]


def _ps_literal(text: str) -> str:
    """`text` as one single-quoted PowerShell string: nothing inside is expanded and
    a double quote is an ordinary character; a single quote is written twice.

    The arguments string holds double quotes whenever an argument has a space
    (list2cmdline quotes it), and in a double-quoted PowerShell string the first of
    them ends the string. The windowless route puts the program path among the
    arguments, so from 2026-10-11 (07d90b11) the OK-WW failure screenshot, whose
    program is C:\\Program Files\\PowerShell\\7\\pwsh.exe, could not build its task."""
    return "'" + str(text).replace("'", "''") + "'"


def _spawn_via_task(exe: Path, cwd: Path, args: tuple[str, ...] = (),
                    *, task: "str | None" = None, label: "str | None" = None) -> bool:
    """Start exe in the interactive desktop session via a one-shot scheduled task. True on success.

    `task` overrides the task name's stem, `label` the program name in the log line.
    """
    # One task name per launch: Register-ScheduledTask -Force stops a running instance, and
    # until 11-08 the name was one per program, so two launches of one program within the
    # 3 s before the unregister (two threads taking pictures) replaced or unregistered each
    # other's task (audit 11-08 A-21). A task left behind by a script killed inside those
    # 3 s keeps its name and never runs again (it has no trigger).
    task = f"{task or _task_name(exe.stem)}-{uuid.uuid4().hex[:8]}"
    quoted = subprocess.list2cmdline(list(args)) if args else ""
    ps = (
        f'$ErrorActionPreference="Stop";'
        f'Unregister-ScheduledTask -TaskName "{task}" -Confirm:$false '
        f'-ErrorAction SilentlyContinue;'
        f'$a=New-ScheduledTaskAction -Execute {_ps_literal(exe)} '
        + (f'-Argument {_ps_literal(quoted)} ' if quoted else "")
        + f'-WorkingDirectory {_ps_literal(cwd)};'
        f'$p=New-ScheduledTaskPrincipal -UserId "administrator" '
        f'-LogonType Interactive -RunLevel Highest;'
        f'Register-ScheduledTask -TaskName "{task}" -Action $a -Principal $p '
        f'-Force | Out-Null;'
        f'Start-ScheduledTask -TaskName "{task}";'
        # Unregister the task 3 s after starting it; the program keeps running.
        f'Start-Sleep -Seconds 3;'
        f'Unregister-ScheduledTask -TaskName "{task}" -Confirm:$false '
        f'-ErrorAction SilentlyContinue'
    )
    exe_ps = _pwsh()
    try:
        r = subprocess.run(
            [exe_ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, timeout=PWSH_GUARD_S, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("预更新：计划任务方式启动 %s 失败", exe.name, exc_info=True)
        return False
    if r.returncode != 0:
        log.warning("预更新：计划任务方式启动 %s 返回 %d：%s", exe.name,
                    r.returncode, r.stderr.decode("utf-8", "replace")[:200])
        return False
    log.info("预更新：已通过计划任务在交互会话启动 %s", label or exe.name)
    return True


# The windowless route. powershell.exe and pwsh.exe are console programs: started
# by the Interactive scheduled task they get a console window of their own, and
# that window takes the foreground for a moment even with -WindowStyle Hidden
# (the switch only hides it after PowerShell is up; on this Windows 11 machine,
# with no default-terminal choice under HKCU\Console\%%Startup, the console may
# also be handed to Windows Terminal). MaaEnd drives Endfield with its
# foreground controller (MXU log: 「需要游戏窗口保持在最前且不被遮挡」), so every
# picture taken mid-run knocked the game out of the foreground. On 2026-10-11 at
# 09:39:02 the game did not get it back for 25 s; the taskbar covered the
# 「ENDFIELD」 mark MaaEnd's InMenuList check reads (OCR got 「ENDI」 / 「ENDF」 next
# to 「搜索」 / 「晴朗」), __ScenePrivateMenuListLoadingEnterWorld timed out and
# 转交委托 failed (evidence 2026-10-11_endfield_MaaEnd-05-30-34, maafw.log:
# 159 x 「Failed to ensure foreground window before screencap」 09:39:02-09:39:27).
# pythonw.exe is a GUI program with no window, and it starts the console program
# with CREATE_NO_WINDOW, so nothing on the desktop is created or activated. It
# waits for the child, so the task's process lives as long as the program, as
# when the program itself was the task's process.
HIDDEN_LAUNCHER_NAME = "ark-hidden-launch.py"
HIDDEN_LAUNCHER = (
    "import subprocess, sys\n"
    "# 0x08000000 = CREATE_NO_WINDOW: the console program gets no window at all.\n"
    "sys.exit(subprocess.call(sys.argv[1:], creationflags=0x08000000))\n"
)


def _pythonw() -> "Path | None":
    """The relay's own pythonw.exe (runtime\\python\\ in the package); None when absent."""
    for p in (Path(sys.executable).with_name("pythonw.exe"), Path(sys.base_prefix) / "pythonw.exe"):
        if p.is_file():
            return p
    return None


def hidden_plan(exe: Path, cwd: Path, args: tuple[str, ...],
                pythonw: Path) -> "tuple[Path, tuple[str, ...], str]":
    """(program, arguments, task name) the scheduled task runs to start exe with no window."""
    launcher = Path(cwd) / HIDDEN_LAUNCHER_NAME
    return (pythonw, ("-I", str(launcher), str(exe), *args),
            _task_name(exe.stem) + "-hidden")


def _spawn_hidden_via_task(exe: Path, cwd: Path, args: tuple[str, ...] = ()) -> bool:
    """_spawn_via_task for a console program that must not show or activate any window.

    Started directly with CREATE_NO_WINDOW when this process already runs on the desktop
    (_spawn_here). Without pythonw.exe it falls back to the plain task route, with a warning.
    """
    if _spawn_here(exe, cwd, args, hidden=True, label=f"{exe.name}（无窗口）"):
        return True
    pyw = _pythonw()
    if pyw is None:
        log.warning("预更新：找不到 pythonw.exe，%s 只能带窗口启动", exe.name)
        return _spawn_via_task(exe, cwd, args)
    launcher = Path(cwd) / HIDDEN_LAUNCHER_NAME
    try:
        if not (launcher.is_file() and launcher.read_text(encoding="utf-8") == HIDDEN_LAUNCHER):
            Path(cwd).mkdir(parents=True, exist_ok=True)
            launcher.write_text(HIDDEN_LAUNCHER, encoding="utf-8")
    except OSError:
        log.warning("预更新：写不了无窗口启动器 %s，%s 只能带窗口启动", launcher, exe.name, exc_info=True)
        return _spawn_via_task(exe, cwd, args)
    prog, full_args, task = hidden_plan(exe, cwd, args, pyw)
    return _spawn_via_task(prog, cwd, full_args, task=task, label=f"{exe.name}（无窗口）")


_PWSH7 = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")


def _pwsh() -> str:
    """The PowerShell 7 path. There is no fallback to 5.1, which decodes
    Chinese paths through the ANSI code page.

    When it is missing this logs an ERROR and still returns the path, so the
    caller's subprocess call raises OSError.
    """
    if not _PWSH7.exists():
        log.error("找不到 %s：这台机器必须装 PowerShell 7", _PWSH7)
    return str(_PWSH7)


# TOKEN_INFORMATION_CLASS values. Looked up by name on win32security first
# (pywin32 versions differ in where they expose them), else these documented numbers.
_TOKEN_ELEVATION_TYPE = 18
_TOKEN_LINKED_TOKEN = 19
_ELEVATION_LIMITED = 3          # TokenElevationTypeLimited


def _console_primary_token(session: int):
    """The console user's primary token, unfiltered by UAC when possible.

    WTSQueryUserToken returns the restricted half of an administrator's split
    token; starting a requireAdministrator program (OK-WW) with it fails with
    740. The full token is the restricted one's TokenLinkedToken, duplicated
    here into a primary token. Any failure returns the restricted token.
    """
    import win32con  # noqa: PLC0415
    import win32security  # noqa: PLC0415
    import win32ts  # noqa: PLC0415

    token = win32ts.WTSQueryUserToken(session)
    linked = None
    try:
        cls_elev = getattr(win32security, "TokenElevationType", _TOKEN_ELEVATION_TYPE)
        if win32security.GetTokenInformation(token, cls_elev) != _ELEVATION_LIMITED:
            return token                     # not a split token: already the full one
        cls_link = getattr(win32security, "TokenLinkedToken", _TOKEN_LINKED_TOKEN)
        linked = win32security.GetTokenInformation(token, cls_link)
        primary = win32security.DuplicateTokenEx(
            linked, win32security.SecurityImpersonation,
            win32con.MAXIMUM_ALLOWED,
            getattr(win32security, "TokenPrimary", 1))
    except Exception:
        log.debug("预更新：取不到未过滤的控制台令牌，沿用受限令牌", exc_info=True)
        return token
    finally:
        for h in (linked,):
            try:
                if h is not None:
                    h.Close()
            except Exception:  # noqa: BLE001 - handle cleanup only
                pass
    try:
        token.Close()
    except Exception:  # noqa: BLE001 - handle cleanup only
        pass
    return primary


def _startup_info(minimized: bool):
    """STARTUPINFO for CreateProcessAsUser: desktop winsta0\\default, and when
    `minimized`, SW_SHOWMINNOACTIVE.

    Without lpDesktop the process has no window station and dies.
    """
    import win32con  # noqa: PLC0415
    import win32process  # noqa: PLC0415

    startup = win32process.STARTUPINFO()
    startup.lpDesktop = "winsta0\\default"
    if minimized:
        # A program may ignore this flag and show its window anyway.
        startup.dwFlags |= win32con.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_SHOWMINNOACTIVE
    return startup


def _close_handles(handles) -> None:
    """Close the handles CreateProcessAsUser returned. A failed Close is ignored:
    the process is already running."""
    for h in handles:
        try:
            h.Close()
        except Exception:  # noqa: BLE001 - handle cleanup only
            pass


def _spawn_fallback(exe: Path, cwd: Path, args: tuple[str, ...],
                    *, require_console: bool) -> bool:
    """After the token route failed: try the scheduled task; if that fails too,
    return False when `require_console`, else fall back to a plain launch
    (which lands in session 0, where GUI programs do not run).
    """
    if _spawn_via_task(exe, cwd, args):
        return True
    if require_console:
        log.warning("预更新：计划任务也没能把 %s 放进交互会话，本轮放弃",
                    exe.name)
        return False
    log.warning("预更新：计划任务也失败，退回普通启动")
    return _spawn_detached(exe, cwd, args)


def _tcb_enabled() -> bool:
    """True when this process may call WTSQueryUserToken (SE_TCB_NAME enabled), enabling it if held.

    On the game machine the relay's service host has never held it: every pre-update since
    08-26 took the token route first, failed with winerror 1314 and then used the scheduled
    task - and 2026-10-12 08:46 that expected failure went to the group as 「中继自己报错了」.
    A route that cannot work here is not tried; the scheduled task is the route.
    """
    try:
        import win32api  # noqa: PLC0415
        import win32security  # noqa: PLC0415
        tok = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_QUERY | win32security.TOKEN_ADJUST_PRIVILEGES)
        luid = win32security.LookupPrivilegeValue(None, win32security.SE_TCB_NAME)
        held = [a for lu, a in win32security.GetTokenInformation(tok, win32security.TokenPrivileges) if lu == luid]
        if not held:
            return False
        if not held[0] & win32security.SE_PRIVILEGE_ENABLED:
            win32security.AdjustTokenPrivileges(tok, False, [(luid, win32security.SE_PRIVILEGE_ENABLED)])
            held = [a for lu, a in win32security.GetTokenInformation(tok, win32security.TokenPrivileges) if lu == luid]
        return bool(held and held[0] & win32security.SE_PRIVILEGE_ENABLED)
    except Exception:
        log.debug("预更新：查不了 SE_TCB_NAME，当作没有", exc_info=True)
        return False


def _spawn_interactive(exe: Path, cwd: Path,
                       args: tuple[str, ...] = (),
                       *, require_console: bool = False,
                       minimized: bool = False, hidden: bool = False) -> bool:
    """Start a GUI program in the console session. True if it was launched.

    The relay runs as a LocalSystem service in session 0, which has no desktop;
    a GUI program started there dies (MaaEnd, MAA and OK-WW updaters do not run).
    So the process is created with the console user's token
    (CreateProcessAsUser), else through a one-shot scheduled task
    (_spawn_fallback).

    With no console session, no token or no pywin32, it falls back to a plain
    launch - unless `require_console`, which returns False instead, because a
    program started in session 0 leaves its version file unchanged and the
    caller would read that as "no update".
    `hidden` starts a console program with CREATE_NO_WINDOW; `minimized` see
    _startup_info.

    The installed relay already runs elevated on the desktop: it starts the program itself
    (_spawn_here) and none of the above is needed.
    """
    if _spawn_here(exe, cwd, args, minimized=minimized, hidden=hidden):
        return True
    try:
        import win32con  # noqa: PLC0415
        import win32process  # noqa: PLC0415
        import win32profile  # noqa: PLC0415
        import win32ts  # noqa: PLC0415
    except ImportError:
        # The scheduled-task route needs only pwsh, not pywin32.
        log.warning("预更新：导入 pywin32 失败，改用计划任务方式启动 %s",
                    exe.name, exc_info=True)
        return _spawn_fallback(exe, cwd, args, require_console=require_console)

    token = None
    try:
        session = win32ts.WTSGetActiveConsoleSessionId()
        if session in (0, 0xFFFFFFFF):
            if require_console:
                log.warning("预更新：没有交互会话，拒绝在 session 0 启动 %s", exe.name)
                return False
            log.info("预更新：没有交互会话，退回普通启动")
            return _spawn_detached(exe, cwd, args)
        if not _tcb_enabled():
            log.info("预更新：中继服务没有拿控制台令牌的权限（这台机器上一直如此），直接用计划任务启动 %s", exe.name)
            return _spawn_fallback(exe, cwd, args, require_console=require_console)
        token = _console_primary_token(session)
        env = win32profile.CreateEnvironmentBlock(token, False)
        startup = _startup_info(minimized)
        # CreateProcessAsUser wants the exe repeated as argv[0].
        cmd = subprocess.list2cmdline([str(exe), *args])
        # 0x08000000 = CREATE_NO_WINDOW.
        flags = (0x08000000 if hidden else win32con.CREATE_NEW_CONSOLE) | win32process.CREATE_UNICODE_ENVIRONMENT
        handles = win32process.CreateProcessAsUser(
            token, str(exe), cmd, None, None, False, flags,
            env, str(cwd), startup)
        _close_handles(handles)
        log.info("预更新：已在会话 %s 启动 %s", session, exe.name)
        return True
    except Exception as e:
        # The relay's service host normally ends up here: WTSQueryUserToken needs
        # SE_TCB_NAME, which the service does not hold (winerror 1314). That is the
        # route the scheduled task exists for, not a fault - 2026-10-12 08:46 it was
        # logged as a WARNING with a traceback and went to the group as 「中继自己报错了」.
        # Any other failure is still a WARNING; a failed fallback warns in _spawn_fallback.
        if getattr(e, "winerror", None) == 1314:
            log.info("预更新：中继服务没有拿控制台令牌的权限（平常如此），走计划任务方式启动 %s", exe.name)
        else:
            log.warning("预更新：拿控制台令牌失败，改用计划任务方式", exc_info=True)
        return _spawn_fallback(exe, cwd, args, require_console=require_console)
    finally:
        if token is not None:
            try:
                token.Close()
            except Exception:  # noqa: BLE001
                pass


def _spawn_detached(exe: Path, cwd: Path,
                    args: tuple[str, ...] = ()) -> bool:
    """Plain detached launch from the relay's own session."""
    try:
        subprocess.Popen(
            [str(exe), *args], cwd=str(cwd),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                           | subprocess.DETACHED_PROCESS))
    except OSError:
        log.warning("预更新：启动 %s 失败，本轮照旧", exe.name, exc_info=True)
        return False
    return True


# AUTO-MAS is already running and its FastAPI backend answers on localhost, so it
# is asked over HTTP instead of being launched.
# Installing runs AUTO-MAS-Setup.exe and the AUTO-MAS process exits; service.py
# does not relaunch AUTO-MAS while "auto-mas-setup" is in the task list
# (service.INSTALLER_HINTS).
# The backend address comes from config.mas_base() at call time.
_MAS_HTTP_TIMEOUT = 20
# Seconds for the download. A package not complete by then is left for the next
# boot instead of starting an install that may not finish before the queue.
MAS_BUDGET_SECONDS = 600
# How long to wait for AUTO-MAS's backend to start listening.
MAS_WAIT_SECONDS = 180
# Seconds to wait after install for the restarted backend to report the new
# version (measured: 16 s).
MAS_INSTALL_WAIT_SECONDS = 150


def _automas_version(automas_dir: Path) -> str:
    """The version in AUTO-MAS's res/version.json; "" when unreadable."""
    try:
        data = json.loads(
            (Path(automas_dir) / "res" / "version.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _live_version() -> str:
    """The version the running backend reports (GET /api/core/health); '' when
    it cannot be asked.

    Electron builds no longer rewrite res/version.json, so the backend's answer
    takes precedence over the file.
    """
    import urllib.request  # noqa: PLC0415
    try:
        with urllib.request.urlopen(mas_base() + "/api/core/health",
                                    timeout=_MAS_HTTP_TIMEOUT) as resp:
            return str(json.loads(resp.read().decode("utf-8", "replace")).get("version") or "")
    except Exception:  # noqa: BLE001 - not up yet; the caller keeps waiting
        return ""


def _wait_for_version(want: str, deadline: float, stopping=going_down) -> str:
    """Poll the backend until it reports `want`, the deadline passes or `stopping()`;
    returns what it last said."""
    got = ""
    while time.monotonic() < deadline and not stopping():
        got = _live_version()
        if got == want:
            return got
        time.sleep(5)
    return got


def _mas_post(path: str, body: dict | None = None) -> dict:
    import urllib.request  # noqa: PLC0415 - only this path needs it
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        mas_base() + path, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_MAS_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _mas_error(answer) -> str | None:
    """None when an AUTO-MAS answer says success; otherwise what it said instead.

    AUTO-MAS reports failure inside an HTTP 200 body: the routes in
    app/api/update.py return code=500 / status="error" (the update check also
    fills in if_need_update=False). Missing code/status take AUTO-MAS's OutBase
    defaults (200 / "success"); a body that is not a dict is a failure.
    """
    if not isinstance(answer, dict):
        return f"回答不是 JSON 对象：{answer!r}"[:200]
    code, status = answer.get("code", 200), answer.get("status", "success")
    if code == 200 and status == "success":
        return None
    return f"code={code} status={status} {answer.get('message') or ''}".strip()[:200]


def _wait_for_package(automas_dir: Path, deadline: float, stopping=going_down) -> Path | None:
    """Wait for UpdatePack_*.zip to appear and keep the same size for 9 s; None when
    the deadline passes or `stopping()` first.

    install_update() refuses when the package is not there yet.
    """
    stable_at = None
    last_size = -1
    while time.monotonic() < deadline:
        time.sleep(3)
        if stopping():
            return None
        packs = sorted(Path(automas_dir).glob("UpdatePack_*.zip"),
                       key=lambda f: f.stat().st_mtime)
        if not packs:
            continue
        pack = packs[-1]
        try:
            size = pack.stat().st_size
        except OSError:
            continue
        if size == last_size and size > 0:
            if stable_at is None:
                stable_at = time.monotonic()
            elif time.monotonic() - stable_at >= 9:
                return pack
        else:
            stable_at = None
            last_size = size
    return None


def run_automas(automas_dir: Path | None,
                budget_s: float = MAS_BUDGET_SECONDS,
                problems: list[str] | None = None,
                after_update: "Callable[[str], object] | None" = None,
                stopping=None, carry: "dict | None" = None) -> str:
    """Check, download and apply an AUTO-MAS update now. Returns a note or "".

    after_update(new_version) is called once the restarted backend reports the new version,
    and only then: boot_stages passes selfcheck.report_contract, which checks again that every
    setting the relay reads is where it looks (10-14: v5.7.0-beta.3, installed here at 08:46,
    moved the stage items, and the boot self-check had run at 08:45 on the old version).

    `stopping()` (default preupdate_common.going_down) is asked at every poll of the three
    waits; a stop ends the item at once with "" and no note, since nothing was judged and
    the next boot runs the pre-update again.

    `carry` is one dict the caller hands to both tries of boot_stages._once_more: a try that
    started an install it could not see land leaves {"from", "to"} there, and the next try,
    finding the backend on "to", calls after_update and says 「已更新」. Until 11-08 that
    try found nothing to do and said nothing, the first try's 「还没确认装成」 went out and
    the settings check after an update never ran (audit 11-08 A-20)."""
    stopping = stopping or going_down
    if not automas_dir:
        return ""
    root = Path(automas_dir)
    version = _automas_version(root)
    if not version:
        log.info("预更新：读不到 AUTO-MAS 版本号，跳过")
        _note(problems, "AUTO-MAS 预更新：读不到版本号，**没有检查更新**")
        return ""
    # The backend may not be listening yet at boot: retry for MAS_WAIT_SECONDS.
    answer = None
    wait_until = time.monotonic() + MAS_WAIT_SECONDS
    while True:
        try:
            # if_force bypasses AUTO-MAS's 4-hour cache of the check result. The
            # MirrorChyan download URL in that result is single-use, so a cached
            # one returns 404 on download.
            live = _live_version()
            if live and live != version:
                log.info("预更新：AUTO-MAS 后端自报 %s（res/version.json 还写着 %s，新版不再改那个文件）",
                         live, version)
                version = live
            answer = _mas_post("/api/update/check",
                               {"current_version": version, "if_force": True})
            break
        except Exception:  # noqa: BLE001 - not up yet, or genuinely unreachable
            if stopping():
                log.info("预更新：中继正在停止，AUTO-MAS 的更新这次不查了")
                return ""
            if time.monotonic() >= wait_until:
                log.warning("预更新：等了 %.0f 秒仍问不到 AUTO-MAS 更新状态，跳过",
                            MAS_WAIT_SECONDS)
                _note(problems,
                      f"AUTO-MAS 预更新：等了 {MAS_WAIT_SECONDS:.0f} 秒仍问不到"
                      "更新状态，**没有检查更新**")
                return ""
            time.sleep(5)
    landed = _landed(carry, version, after_update)
    failed = _mas_error(answer)
    if failed is None and not isinstance(answer.get("if_need_update"), bool):
        failed = "回答里没有 if_need_update"
    if failed is not None:
        log.warning("预更新：AUTO-MAS 查更新没有结论（%s），本轮没有检查更新", failed)
        _note(problems, f"AUTO-MAS 预更新：查更新没有结论（{failed}），**没有检查更新**"
                        "（不是「无需更新」）")
        return landed
    if not answer["if_need_update"]:
        log.info("预更新：AUTO-MAS 已是 %s（无需更新）", version)
        return landed

    latest = answer.get("latest_version") or "新版本"
    log.info("预更新：AUTO-MAS 有更新 %s → %s，开始下载", version, latest)
    deadline = time.monotonic() + budget_s
    try:
        failed = _mas_error(_mas_post("/api/update/download"))
    except Exception as e:
        failed = f"{type(e).__name__}: {e}"
        log.warning("预更新：AUTO-MAS 下载没能启动，本轮照旧", exc_info=True)
    if failed is not None:
        log.warning("预更新：AUTO-MAS 下载没能启动（%s）", failed)
        _note(problems, f"AUTO-MAS 预更新：查到有 {latest}，但下载没能启动（{failed}）")
        return landed

    pack = _wait_for_package(root, deadline, stopping)
    if pack is None and stopping():
        # The partial package stays; the next boot continues from it.
        log.info("预更新：中继正在停止，AUTO-MAS 的更新包留到下次开机再装")
        return landed
    if pack is None:
        # The partial package stays; the next boot continues from it.
        log.warning("预更新：AUTO-MAS 更新包 %.0f 秒内没下完，留到下次开机再装", budget_s)
        _note(problems,
              f"AUTO-MAS 预更新：{latest} 的更新包 {budget_s:.0f} 秒内没下完，"
              "留到下次开机再装")
        return landed

    log.info("预更新：更新包就绪（%s），开始安装", pack.name)
    try:
        failed = _mas_error(_mas_post("/api/update/install"))
    except Exception as e:
        failed = f"{type(e).__name__}: {e}"
        log.warning("预更新：AUTO-MAS 安装没能启动，本轮照旧", exc_info=True)
    if failed is not None:
        log.warning("预更新：AUTO-MAS 安装没能启动（%s）", failed)
        _note(problems, f"AUTO-MAS 预更新：{latest} 的更新包已下好，但安装没能启动"
                        f"（{failed}），留到下次开机再装")
        return landed
    # The backend restarts itself after install; wait for it to report the new version.
    got = _wait_for_version(latest, time.monotonic() + MAS_INSTALL_WAIT_SECONDS, stopping)
    if got != latest and stopping():
        log.info("预更新：中继正在停止，AUTO-MAS 的安装已启动，装没装上留到下次开机再看")
        return landed
    if got == latest:
        log.info("预更新：AUTO-MAS 已更新到 %s（后端重启后自报）", latest)
        _after(after_update, latest)
        return f"AUTO-MAS 已更新：{_span(version, latest)}"
    log.warning("预更新：AUTO-MAS 装完 %.0f 秒内后端没有自报 %s（最后一次说的是 %s），留到下次开机再看",
                MAS_INSTALL_WAIT_SECONDS, latest, got or "问不到")
    _note(problems, f"AUTO-MAS 预更新：{latest} 的安装已启动，但后端没有自报新版本"
                    f"（最后说的是 {got or '问不到'}），留到下次开机再看")
    if carry is not None:
        carry.update({"from": (carry.get("from") or version), "to": latest})
    return f"AUTO-MAS 有更新：{_span(version, latest)}（安装已启动，还没确认装成）"


def _after(after_update, version: str) -> None:
    """after_update(version), its failure logged: the update itself landed."""
    if after_update is None:
        return
    try:
        after_update(version)
    except Exception:
        log.exception("预更新：AUTO-MAS 更新后核对中继要读的设置时出错")


def _landed(carry: "dict | None", live: str, after_update) -> str:
    """「AUTO-MAS 已更新：…」 when an earlier try's install (carry) is what the backend runs
    now, after_update called for it; '' otherwise. The record is used once."""
    if not carry or not carry.get("to") or live != carry["to"]:
        return ""
    old = str(carry.get("from") or "")
    carry.clear()
    log.info("预更新：上一次装的 AUTO-MAS %s 已经装上了（后端现在自报 %s）", live, live)
    _after(after_update, live)
    return f"AUTO-MAS 已更新：{_span(old, live)}"


# OK-WW updates itself through pyappify from a CNB git mirror when ok-ww.exe (the
# pyappify shell) is launched; app.json carries "update_method": "AUTO_UPDATE".
# Running the bundled python directly does not update. ok-ww.exe also honours
# "Auto Start Game When App Starts", so that switch is turned off for the
# relay's launch and restored afterwards.
_OKWW_BASIC = ("data", "apps", "ok-ww", "working", "configs", "Basic Options.json")
_OKWW_APPJSON = ("data", "apps", "ok-ww", "app.json")
_OKWW_AUTOSTART_KEY = "Auto Start Game When App Starts"
OKWW_BUDGET_SECONDS = 240
# OK-WW schedules its update check 30 s after its window shows up ("schedule
# pyappify update check in 30000ms"), while app.json is rewritten within seconds
# of launch. A verdict of "checked, no update" waits at least this long.
OKWW_MIN_WAIT_SECONDS = 45
# Where run_okww keeps the switch's value from before it turned it off, until it has put
# it back. 2026-10-16 02:35 the 15 s hard exit killed the relay inside run_okww, the
# `finally` that restores the switch never ran, and the next run read the switch as off
# and "restored" it to off. The next run and every boot restore from this file instead.
AUTOSTART_MEMO = "okww-autostart-was.json"


# OK-WW's own python processes: python.exe or pythonw.exe (the echo farm launches
# pythonw so no console covers the game) whose command line holds OK-WW's install
# folder. One filter for stopping them and for looking for them.
# The folder, not a bare "ok-ww" or `-m ok`: -like ignores case, so any python with
# "OK-WW" among its arguments matched - `dispatch_guard.py start OK-WW` saw itself
# (scripts/windows/dispatch_guard.py). A path fragment carries separators no
# argument has. OK-WW's real line (ok-script.2026-10-12.log, 15:23:30):
# D:\ark\okww\data\apps\ok-ww\working\main.py -t 2 -e, run by the pythonw.exe under
# data\apps\ok-ww\python (echofarm._launch).
_OKWW_PY = ("Get-CimInstance Win32_Process -Filter "
            "\"Name='python.exe' OR Name='pythonw.exe'\" | "
            r"Where-Object { $_.CommandLine -like '*\ok-ww\*' }")


def _okww_py(tail: str, timeout: "float | None" = None):
    """Run `_OKWW_PY | tail` in PowerShell 7; the CompletedProcess, or None when it
    could not run (or ran past `timeout` seconds)."""
    ps = _OKWW_PY + " | " + tail
    # 60 s is a hang guard, not an expected duration (kept from _okww_quiesce,
    # bc3b709d). Measured on the game machine 2026-10-13 11:08 Beijing: this call
    # (okww_python_pids) took 0.54, 0.39, 0.39, 0.41, 0.41 s over 5 runs, so the
    # guard fires only when pwsh or WMI hangs.
    try:
        return subprocess.run([_pwsh(), "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=PWSH_GUARD_S if timeout is None else timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _stop_okww_python(timeout: "float | None" = None) -> None:
    """Stop OK-WW's python processes (only those, see _OKWW_PY); the game is left alone.
    The result is not checked: a caller that must know uses okww_python_pids."""
    _okww_py("ForEach-Object { Stop-Process -Id $_.ProcessId -Force }", timeout)


def okww_python_pids(timeout: "float | None" = None) -> "list[int] | None":
    """PIDs of OK-WW's running python processes (_OKWW_PY); None when the process
    list could not be read.

    No process gives empty output with exit 0 and nothing on stderr. A query that
    failed inside pwsh also prints nothing on stdout, so a nonzero exit, or empty
    output with an error on stderr, is "could not read", never "none left"."""
    r = _okww_py("Select-Object ProcessId | ConvertTo-Json -Compress", timeout)
    if r is None or r.returncode != 0:
        return None
    text = (r.stdout or b"").decode("utf-8", "replace").strip()
    if not text and (r.stderr or b"").strip():
        return None
    try:
        data = json.loads(text or "null")
    except ValueError:
        return None
    out = []
    for proc in [data] if isinstance(data, dict) else (data or []):
        try:
            out.append(int(proc.get("ProcessId")))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def _okww_quiesce(sleep=time.sleep, launcher_root: Path | None = None, left=None) -> None:
    """Stop OK-WW, the game and the Kuro launcher, so nothing rewrites OK-WW's
    config from memory.

    A running OK-WW (ok-ww.exe or an `ok` python process) writes its settings
    back from memory, so an edit to its JSON made while it runs is lost.
    The OK-WW python processes (python.exe and pythonw.exe) are stopped before
    the game, because OK-WW restarts the game when it is killed first.
    `launcher_root` is the Kuro launcher's folder (see _stop_wuwa_launcher).
    taskkill runs from the service's session and its result is not checked; a
    caller that must know the machine is clean uses _okww_close.
    `left`, when given, returns the seconds a caller's time budget has left; each
    PowerShell call here gets only that (echofarm.stop_okww).
    """
    _stop_okww_python(timeout=left() if left else None)
    for name in _QUIESCE_EXES:
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],
                           capture_output=True, timeout=TASKKILL_GUARD_S)
        except (OSError, subprocess.SubprocessError):
            pass
    _stop_wuwa_launcher(launcher_root, timeout=left() if left else None)
    # Two seconds for the processes to exit. `sleep` is injectable for tests.
    sleep(_QUIESCE_SETTLE_S)


def _okww_close(sleep=time.sleep, launcher_root: Path | None = None, clock=time.monotonic) -> list[str]:
    """_okww_quiesce, then look again: what is still up afterwards ([] = clean).

    taskkill from session 0 does not reach the game under its anti-cheat, so
    whatever survives is killed again from the desktop session
    (echofarm._kill_on_desktop) and checked for up to 10 s.

    Bounded as echofarm.stop_okww is, by its STOP_OKWW_SECONDS: each PowerShell call gets
    only the time left (at least one second) and the looks stop when it runs out; the
    taskkill / tasklist / schtasks calls keep their own guards (OKWW_CLOSE_MAX_SECONDS).
    """
    from ark_relay.features.echofarm import STOP_OKWW_SECONDS, _kill_on_desktop  # noqa: PLC0415 - echofarm imports this module
    end = clock() + STOP_OKWW_SECONDS

    def left_s() -> float:
        return max(1.0, end - clock())

    _okww_quiesce(sleep=sleep, launcher_root=launcher_root, left=left_s)
    left, pids = _okww_left(launcher_root, left_s())
    if not left:
        return []
    log.warning("鸣潮：关完还在 %s，从桌面会话再关一次", "、".join(left))
    _kill_on_desktop(pids=pids)
    for _ in range(10):
        if clock() >= end:
            break
        sleep(1)
        left, _pids = _okww_left(launcher_root, left_s())
        if not left:
            return []
    return left


def _okww_left(launcher_root: Path | None = None,
               timeout: "float | None" = None) -> tuple[list[str], list[int]]:
    """(names still up, PIDs to kill by number): the game's processes, OK-WW's own
    python (game_alive) and the Kuro launcher at its path; the PIDs are the
    launcher's and OK-WW's python's, whose names are too common to kill by name.
    An unreadable launcher list is named, not taken as gone. `timeout` bounds each
    PowerShell query (None: their guards)."""
    from ark_relay.features.echofarm import game_alive  # noqa: PLC0415 - echofarm imports this module
    left = list(game_alive(timeout))
    py = (okww_python_pids(timeout) or []) if left else []
    procs = _wuwa_launcher_procs(launcher_root, timeout)
    if procs is None:
        left.append("鸣潮启动器（查不到它还开没开着）")
        return left, py
    left += [Path(path.replace("\\", "/")).name for _pid, path in procs]
    return left, [pid for pid, _path in procs] + py


# The Kuro launcher: launcher.exe is the entry shell; while it runs the process is
# <launcher dir>\<version>\launcher_main.exe. Both names are common, so only
# processes under the launcher's folder (`root`, when a caller knows it) or under
# a folder named Wuthering Waves (the machine: D:\Wuthering Waves\launcher.exe)
# are stopped.
_WW_LAUNCHER_EXES = ("launcher.exe", "launcher_main.exe")
# Used when the launcher's folder cannot be worked out. A path segment, so the game
# body's folder (…\Wuthering Waves Game\…) does not match.
_WW_LAUNCHER_SEGMENT = "\\wuthering waves\\"
_QUIESCE_EXES = ("ok-ww.exe", "Wuthering Waves.exe", "Client-Win64-Shipping.exe", "KRSDKExternal.exe")
_QUIESCE_SETTLE_S = 2
# The longest one _okww_quiesce can take, from its hang guards: the OK-WW python query
# (_stop_okww_python), one taskkill per name, the launcher query and one taskkill per
# launcher process, then the settle sleep.
OKWW_QUIESCE_MAX_SECONDS = (2 * PWSH_GUARD_S
                            + (len(_QUIESCE_EXES) + len(_WW_LAUNCHER_EXES)) * TASKKILL_GUARD_S
                            + _QUIESCE_SETTLE_S)


def okww_close_max_seconds() -> float:
    """The longest _okww_close can take: its budget (echofarm.STOP_OKWW_SECONDS, which also
    bounds the quiesce's PowerShell calls), the quiesce's taskkills and settle, and past the
    budget one look's tasklist (game_alive guards it at TASKKILL_GUARD_S's 30 s) with its three
    PowerShell queries at their one-second floor. The desktop kill's schtasks calls have no
    guard of their own and are not counted (as in echofarm.stop_okww)."""
    from ark_relay.features.echofarm import STOP_OKWW_SECONDS  # noqa: PLC0415 - echofarm imports this module
    return float(STOP_OKWW_SECONDS + OKWW_QUIESCE_MAX_SECONDS - 2 * PWSH_GUARD_S + TASKKILL_GUARD_S + 3)


def _norm(path) -> str:
    return str(path or "").replace("/", "\\").lower()


def _is_wuwa_launcher(path, root: Path | None = None) -> bool:
    """Whether an executable path is the Kuro launcher: launcher.exe or
    launcher_main.exe under `root` (subfolders included), or, without a root,
    under a folder named Wuthering Waves."""
    p = _norm(path)
    if p.rsplit("\\", 1)[-1] not in _WW_LAUNCHER_EXES:
        return False
    if root:
        return p.startswith(_norm(root).rstrip("\\") + "\\")
    return _WW_LAUNCHER_SEGMENT in p


def _wuwa_launcher_procs(root: Path | None = None,
                         timeout: "float | None" = None) -> list[tuple[int, str]] | None:
    """(PID, path) of the running Kuro launcher processes; None when the process
    list could not be read."""
    ps = ("Get-CimInstance Win32_Process -Filter "
          "\"Name='launcher.exe' OR Name='launcher_main.exe'\" | "
          "Select-Object ProcessId, ExecutablePath | ConvertTo-Json -Compress")
    # 60 s is a hang guard. Not timed itself; the same pwsh + Get-CimInstance call
    # for OK-WW's python was measured on the game machine 2026-10-13 11:08 Beijing
    # at 0.39-0.54 s over 5 runs.
    # As okww_python_pids: a query that failed inside pwsh prints nothing on stdout too, so
    # a nonzero exit, or empty output with an error on stderr, is "could not read", never
    # "no launcher" (audit 11-08 A-22).
    try:
        r = subprocess.run([_pwsh(), "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=PWSH_GUARD_S if timeout is None else timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (r.stdout or b"").decode("utf-8", "replace").strip()
    if r.returncode != 0 or (not text and (r.stderr or b"").strip()):
        return None
    try:
        data = json.loads(text or "null")
    except ValueError:
        return None
    out = []
    for proc in [data] if isinstance(data, dict) else (data or []):
        if not (isinstance(proc, dict) and _is_wuwa_launcher(proc.get("ExecutablePath"), root)):
            continue
        try:
            out.append((int(proc.get("ProcessId")), str(proc.get("ExecutablePath"))))
        except (TypeError, ValueError):
            continue
    return out


def _stop_wuwa_launcher(root: Path | None = None, timeout: "float | None" = None) -> list[int]:
    """Stop the Kuro launcher processes, matched on their full executable path.

    Returns the PIDs taskkill confirmed (return code 0); one it could not stop
    is logged and left out (_okww_close tries again from the desktop).
    """
    stopped = []
    for pid, path in _wuwa_launcher_procs(root, timeout) or []:
        try:
            r = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                               timeout=TASKKILL_GUARD_S)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("鸣潮启动器没关掉（PID %d，%s）：%s", pid, path, exc)
            continue
        if r.returncode != 0:
            log.warning("鸣潮启动器没关掉（PID %d，%s）：taskkill 返回 %s %s", pid, path, r.returncode,
                        (r.stderr or b"").decode("utf-8", "replace").strip()[:120])
            continue
        stopped.append(pid)
        log.info("鸣潮启动器已关掉（PID %d，%s）", pid, path)
    return stopped


def _okww_autostart(okww_dir: Path, value: bool) -> bool | None:
    """Set OK-WW's auto-start-game flag, returning what it was. None if it could not."""
    cfg = Path(okww_dir).joinpath(*_OKWW_BASIC)
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        was = bool(data.get(_OKWW_AUTOSTART_KEY, False))
    except (OSError, ValueError, TypeError):
        log.warning("预更新：读不到 OK-WW 的 Basic Options，跳过 OK-WW")
        return None
    if was == value:
        return was
    data[_OKWW_AUTOSTART_KEY] = value
    try:
        atomic_write_text(cfg, json.dumps(data, ensure_ascii=False, indent=4))
    except OSError:
        log.warning("预更新：写不回 OK-WW 的 Basic Options，跳过 OK-WW", exc_info=True)
        return None
    return was


def _okww_state(okww_dir: Path) -> tuple[str, str, str, tuple[str, ...]]:
    """(current_version, update_state, update_error, available_versions) from app.json.

    A refreshed available_versions shows that OK-WW asked upstream.
    """
    try:
        d = json.loads(Path(okww_dir).joinpath(*_OKWW_APPJSON).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "", "", "", ()
    avail = d.get("available_versions")
    return (str(d.get("current_version") or ""), str(d.get("update_state") or ""),
            str(d.get("update_error") or ""),
            tuple(str(x) for x in avail) if isinstance(avail, list) else ())


def _okww_stamp(okww_dir: Path) -> float:
    """Modification time of app.json; 0 when it cannot be read.

    OK-WW rewrites app.json when it checks, even when the version list stays
    the same, so a newer mtime shows that a check ran.
    """
    try:
        return Path(okww_dir).joinpath(*_OKWW_APPJSON).stat().st_mtime
    except OSError:
        return 0.0


def _okww_await_update(root: Path, budget_s: float, before_version: str,
                       before_avail: tuple[str, ...],
                       before_stamp: float, sleep=time.sleep,
                       clock=time.monotonic,
                       stopping=None) -> tuple[str, bool, str, str, tuple[str, ...]]:
    """Watch app.json until OK-WW is done: returns (new version, did it check, error,
    the state it was still in when the budget ran out - "" unless it timed out busy,
    the last non-empty available_versions read - `before_avail` if none was read).

    "Did it check" is true when the version list changed, app.json was
    rewritten, the update state left idle, or the version changed. A
    "checked, settled" verdict also needs OKWW_MIN_WAIT_SECONDS since launch.
    `stopping()` true at a poll ends the wait at once (default: the relay is stopping,
    preupdate_common.going_down); the caller asks it again and gives no verdict.
    """
    stopping = stopping or going_down
    deadline = clock() + budget_s
    launched = clock()
    settled = ""
    checked = False           # saw it actually move: state / version list / version
    failed = ""
    state = ""
    version, avail = before_version, before_avail
    latest = before_avail     # the list the verdict reads: the newest one seen
    while clock() < deadline:
        sleep(3)
        if stopping():
            break
        version, state, err, avail = _okww_state(root)
        if avail:
            latest = avail
        if err:
            log.warning("预更新：OK-WW 更新报错 %s", err[:200])
            failed = err[:200]
            break
        if avail and avail != before_avail:
            checked = True    # list refreshed: it asked upstream
        if before_stamp and _okww_stamp(root) > before_stamp:
            # app.json rewritten: it ran its check.
            checked = True
        if state and state not in ("idle", ""):
            checked = True
            continue          # downloading or installing, keep waiting
        # Without a baseline version (app.json unreadable before launch) a version
        # read now is not counted as a change.
        if version and before_version and version != before_version:
            settled, checked = version, True
            break
        if (checked and state == "idle"
                and clock() - launched >= OKWW_MIN_WAIT_SECONDS):
            break             # checked, past the minimum wait, and idle
    else:
        if state not in ("idle", ""):
            # Out of time while app.json still says it is downloading or installing.
            log.warning("预更新：OK-WW %.0f 秒到了还在「%s」，没更新完；app.json 最后读到 "
                        "版本 %s，可用版本 %s", budget_s, state, version or "未知", list(avail[:3]))
            return settled, checked, failed, state, latest
    return settled, checked, failed, "", latest


def _okww_report(problems: list[str] | None, budget_s: float,
                 before_version: str, latest_avail: tuple[str, ...],
                 settled: str, checked: bool, failed: str, stuck: str = "",
                 shot: "Path | None" = None) -> None:
    """Log the result of _okww_await_update and note a problem where one is due.

    Branches: update error; updated; out of time while busy; no sign of a check
    (not the same as "no update"); checked with nothing newer installed - a
    problem when `latest_avail` (the version list as last read during the wait,
    newest first) lists a newer one, otherwise 「无需更新」.
    """
    if failed:
        _note(problems, f"OK-WW 预更新：更新报错 {failed}")
    elif settled:
        log.info("预更新：OK-WW 已更新 %s → %s", before_version, settled)
    elif stuck:
        _note(problems,
              f"OK-WW 预更新：{budget_s:.0f} 秒到了还在「{stuck}」，**没更新完**（不是「无需更新」，"
              f"当前 {before_version or '版本未知'}）" + (f"，截图 {shot}" if shot else "，截图没拿到"))
    elif not checked:
        log.warning("预更新：OK-WW %.0f 秒内没有任何检查迹象（版本列表没刷新）",
                    budget_s)
        _note(problems,
              f"OK-WW 预更新：{budget_s:.0f} 秒内没有任何检查迹象，"
              f"**无法确认是否检查过更新**（当前 {before_version or '版本未知'}）")
    else:
        newest = latest_avail[0] if latest_avail else ""
        if not newest or newest == before_version:
            log.info("预更新：OK-WW 无需更新（%s）", before_version or "版本未知")
        else:
            _note(problems,
                  f"OK-WW 预更新：查到有 {newest}，但没装上"
                  f"（仍是 {before_version or '版本未知'}）")


def _okww_timeout_shot(take=None) -> "Path | None":
    """A picture of the desktop when the update ran out of time mid-download, saved
    under the relay's state folder. None when it could not be taken (a Mac, a test,
    no interactive session). `take(out) -> bool` is for tests."""
    from ark_relay.core.config import _env_path  # noqa: PLC0415
    if take is None:
        from ark_relay.features.handle import _screenshot_to as take  # noqa: PLC0415 - Windows-only, heavy import
    try:
        out = _env_path("ARK_STATE_DIR", "./ark-state") / "preupdate" / \
            f"okww-timeout-{time.strftime('%Y%m%d-%H%M%S')}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        return out if take(out) else None
    except Exception:
        log.warning("预更新：OK-WW 超时截图没拿到", exc_info=True)
        return None


def _okww_autostart_now(okww_dir: Path) -> bool | None:
    """The auto-start switch as it is now, read only; None when unreadable."""
    try:
        data = json.loads(Path(okww_dir).joinpath(*_OKWW_BASIC).read_text(encoding="utf-8"))
        return bool(data.get(_OKWW_AUTOSTART_KEY, False))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _memo_path(state_dir: "Path | None") -> "Path | None":
    return Path(state_dir) / AUTOSTART_MEMO if state_dir else None


def _memo_read(memo: "Path | None") -> bool | None:
    """The switch's value from before a run turned it off, when that run never put it
    back; None when there is no such record (or it cannot be read)."""
    if memo is None:
        return None
    try:
        value = json.loads(memo.read_text(encoding="utf-8")).get("was")
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return value if isinstance(value, bool) else None


def _memo_write(memo: "Path | None", value: bool) -> None:
    if memo is None:
        return
    try:
        memo.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(memo, json.dumps({"was": value, "at": time.strftime("%Y-%m-%d %H:%M:%S")}))
    except OSError:
        # Without the record a hard exit loses the value again, as before 10-16; the run goes on.
        log.warning("预更新：记不下 OK-WW 自动开游戏开关的原值（%s）", memo, exc_info=True)


def _memo_drop(memo: "Path | None") -> None:
    if memo is None:
        return
    try:
        memo.unlink(missing_ok=True)
    except OSError:
        log.warning("预更新：删不掉 %s，下次还会按它放回开关", memo, exc_info=True)


def restore_autostart_leftover(okww_dir: "Path | None", state_dir: "Path | None",
                               pids=None) -> str:
    """At boot: put the auto-start switch back from the record a killed run left
    (AUTOSTART_MEMO). Returns a log line when it did, else "".

    Every boot, not only a pre-update boot: a day with no OK-WW queue left, or a clean
    pre-update already done, runs no pre-update and would leave the switch wrong. Only
    while no OK-WW python runs (`pids`, default okww_python_pids; [] = none): a running
    OK-WW writes its settings back from memory. Unknown (None) is left for the next boot.
    """
    memo = _memo_path(state_dir)
    was = _memo_read(memo)
    if was is None or not okww_dir:
        return ""
    running = (pids or okww_python_pids)()
    if running is None or running:
        log.info("启动：OK-WW 的自动开游戏开关上次没放回，但 OK-WW %s，留到下次开机再放",
                 "在跑" if running else "在不在跑查不到")
        return ""
    if _okww_autostart_now(Path(okww_dir)) == was:
        # Put back and kept (a run that could not see OK-WW close keeps the record, run_okww).
        _memo_drop(memo)
        return ""
    if _okww_autostart(Path(okww_dir), was) is None:
        return ""
    _memo_drop(memo)
    return f"OK-WW 的自动开游戏开关上次没放回，已放回原来的「{'开' if was else '关'}」"


# ── after the pre-update: are OK-WW's own Python packages all there? (ledger #115) ──
# 10-24 OK-WW updated itself to v3.7.11-beta.1, whose ok/core/plugins.py imports
# `packaging`; its bundled Python had none, and the morning run crashed at start three
# times. It was fixed by a pip install by hand, and the ledger said an update that
# rebuilds the environment would crash again (dispatch relay-opt-round3-1108 O-01).
# So, with OK-WW closed, its own python imports what main.py imports (config, ok) and
# `packaging`, and names each module it cannot find.
_OKWW_PYTHON = ("data", "apps", "ok-ww", "python", "python.exe")
_OKWW_WORKING = ("data", "apps", "ok-ww", "working")
# The probe, run by OK-WW's own python in its working folder. Two looks, one line each:
# * every dist OK-WW's own requirements.txt lists is installed (importlib.metadata, by the
#   dist's name: a module's name is not its dist's - cv2 / opencv-python, PIL / pillow,
#   win32api / pywin32), else `DIST <name>`;
# * what main.py imports (config, ok), ok.core.plugins (#115's file: ok lazy-imports, so
#   `import ok` alone never reaches it) and `packaging` import, else `MODULE <root>` for
#   the module that was not found. A probed submodule this ok-script version does not have
#   is not a missing package and says nothing.
# A requirement with an environment marker is checked only when the marker applies here;
# without `packaging` to read the marker, it is checked anyway (the machine is the Windows
# the markers are written for).
_DEPS_PROBE = r"""
import importlib, importlib.metadata, re, sys
sys.path.insert(0, '.')
try:
    from packaging.markers import Marker
except Exception:
    Marker = None
try:
    lines = open('requirements.txt', encoding='utf-8', errors='replace').read().splitlines()
except OSError:
    lines = []
for line in lines:
    spec = line.split('#', 1)[0].strip()
    if not spec or spec.startswith('-'):
        continue
    req, _, marker = spec.partition(';')
    if marker.strip() and Marker is not None:
        try:
            if not Marker(marker.strip()).evaluate():
                continue
        except Exception:
            pass
    name = re.split(r'[=<>!~\[;\s]', req.strip(), maxsplit=1)[0]
    try:
        importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        print('DIST', name)
for n in ('packaging', 'config', 'ok', 'ok.core.plugins'):
    try:
        importlib.import_module(n)
    except ModuleNotFoundError as e:
        miss = e.name or ''
        if '.' in n and (n == miss or n.startswith(miss + '.')):
            continue
        print('MODULE', miss.split('.')[0])
    except Exception as e:
        print('OTHER', n, type(e).__name__)
"""
# Installed only when OK-WW itself asks for it: a dist its own requirements.txt lists (as
# written there, pin included), or `packaging` (#115: imported by ok-script, not in OK-WW's
# list). A missing module is matched to a listed dist by name only; any other is said,
# not installed: pip would fetch whatever PyPI holds under a guessed name.
_DEPS_ALWAYS = {"packaging": "packaging"}
# A requirement's name ends at its version, extras, marker or whitespace
# (`onnxocr-ppocrv5>=0.0.20`, `ok-script[ocr,qt]==3.0.3`).
_REQ_NAME_END = re.compile(r"[=<>!~\[;\s]")


def _dist_key(name: str) -> str:
    """A dist or module name as pip compares them (PEP 503: case, '-', '_' and '.' alike)."""
    return "".join("-" if c in "-_." else c for c in name.strip().lower())


def _okww_pins(working: Path) -> "dict[str, str]":
    """{normalised dist name: requirement as written (`name==version`, `name>=version`, ...,
    marker dropped)} from OK-WW's own requirements.txt; {} unreadable."""
    try:
        text = (working / "requirements.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        spec = line.split("#", 1)[0].split(";", 1)[0].strip()
        if spec and not spec.startswith("-"):
            out[_dist_key(_REQ_NAME_END.split(spec, maxsplit=1)[0])] = spec
    return out


def _deps_probe(py: Path, working: Path, run) -> "tuple[list[str], list[str], str]":
    """(dists OK-WW lists that are not installed, module roots its python cannot find, why
    the probe could not tell or '')."""
    try:
        r = run([str(py), "-c", _DEPS_PROBE], cwd=str(working), capture_output=True,
                timeout=PWSH_GUARD_S, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return [], [], f"{type(exc).__name__}: {exc}"
    out = r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, bytes) else str(r.stdout or "")
    dists, modules, other = [], [], []
    for line in out.splitlines():
        word, _, rest = line.strip().partition(" ")
        if word == "DIST" and rest and rest not in dists:
            dists.append(rest)
        elif word == "MODULE" and rest and rest not in modules:
            modules.append(rest)
        elif word == "OTHER":
            other.append(rest)
    if other:
        # Not a missing package: an import that failed for another reason, which the run itself shows.
        log.info("OK-WW 自带的 Python 试导入时别的地方出错（不是缺包）：%s", "；".join(other))
    if r.returncode != 0 and not dists and not modules:
        return [], [], f"试导入退出码 {r.returncode}"
    return dists, modules, ""


def _deps_specs(working: Path, dists: list[str], modules: list[str]) -> "tuple[list[str], list[str]]":
    """(what to hand pip, missing modules OK-WW does not ask for)."""
    pins = _okww_pins(working)
    specs = [pins.get(_dist_key(d)) or d for d in dists]
    unknown = []
    for m in modules:
        spec = pins.get(_dist_key(m)) or _DEPS_ALWAYS.get(m)
        if spec and spec not in specs:
            specs.append(spec)
        elif not spec:
            unknown.append(m)
    return specs, unknown


def ensure_okww_deps(okww_dir: Path, problems: "list[str] | None" = None, *, run=None) -> str:
    """With OK-WW closed: find the packages its bundled python lacks (the probe above), pip
    install the ones OK-WW asks for and probe again. Returns 「OK-WW 缺的 Python 包已补装：…」
    when that fixed something, '' otherwise; what it could not fix or could not tell goes in
    `problems`. No OK-WW python here (a test tree, another layout): nothing, silently. `run`
    replaces subprocess.run (the tests' door)."""
    root = Path(okww_dir)
    py, working = root.joinpath(*_OKWW_PYTHON), root.joinpath(*_OKWW_WORKING)
    if not py.is_file() or not working.is_dir():
        return ""
    run = run or subprocess.run
    dists, modules, why = _deps_probe(py, working, run)
    if why:
        _note(problems, f"OK-WW 预更新：没能核对 OK-WW 自带的 Python 包齐不齐（{why}）")
        return ""
    if not dists and not modules:
        log.info("OK-WW 自带的 Python 包齐全")
        return ""
    specs, unknown = _deps_specs(working, dists, modules)
    pip_rc = "没装"
    if specs:
        try:
            r = run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *specs],
                    cwd=str(working), capture_output=True, timeout=PWSH_GUARD_S,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            pip_rc = r.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            pip_rc = f"{type(exc).__name__}: {exc}"
        # A missing dist may be what provides a missing module: look again before judging.
        still_d, still_m, why = _deps_probe(py, working, run)
        if why:
            _note(problems, f"OK-WW 自带的 Python 缺包 {'、'.join(specs)}，补装过（pip 结果 {pip_rc}），"
                            f"装完没能再核对（{why}）")
            return ""
    else:
        still_d, still_m = dists, modules
    fixed = [x for x in dists + modules if x not in still_d + still_m]
    unknown = [m for m in still_m if m in unknown]
    left = [x for x in still_d + still_m if x not in unknown]
    if unknown:
        _note(problems, f"OK-WW 自带的 Python 缺包 {'、'.join(unknown)}：OK-WW 自己的依赖清单里没有，"
                        "没有自动装，OK-WW 一启动就会崩")
    if left:
        _note(problems, f"OK-WW 自带的 Python 缺包 {'、'.join(left)}，自动补装没成（pip 结果 {pip_rc}），"
                        "OK-WW 一启动就会崩")
    if not fixed:
        return ""
    from ark_relay.features import errwatch  # noqa: PLC0415
    log.warning("OK-WW 更新后自带的 Python 缺包 %s，已自动补装、再导入核对过", "、".join(fixed),
                extra=errwatch.recovered())
    return f"OK-WW 缺的 Python 包已补装：{'、'.join(fixed)}"


def run_okww(okww_dir: Path | None,
             budget_s: float = OKWW_BUDGET_SECONDS,
             problems: list[str] | None = None,
             state_dir: "Path | None" = None,
             stopping=None) -> str:
    """Let OK-WW apply any pending update now, without starting the game.

    Appends to `problems` whenever the check could not be shown to have
    happened. Returns 「OK-WW 已更新：旧 → 新」 or "".
    `state_dir` holds AUTOSTART_MEMO (none given: no record kept). `stopping()` (default
    preupdate_common.going_down): a stopping relay launches nothing, and a stop during
    the wait closes OK-WW and puts the switch back at once, with no verdict and no note.
    """
    stopping = stopping or going_down
    if not okww_dir:
        return ""
    if stopping():
        log.info("预更新：中继正在停止，不启动 OK-WW")
        return ""
    root = Path(okww_dir)
    exe = root / "ok-ww.exe"
    if not exe.exists():
        log.warning("预更新跳过：找不到 %s", exe)
        _note(problems, f"OK-WW 预更新跳过：找不到 {exe}")
        return ""

    before_version, _, _, before_avail = _okww_state(root)
    before_stamp = _okww_stamp(root)
    # Nothing may be holding the config in memory while we edit it.
    _okww_quiesce()
    if stopping():
        # The stop came during the quiesce: no switch flip, no launch.
        log.info("预更新：中继正在停止，不启动 OK-WW")
        return ""
    # ok-ww.exe has no launch argument that keeps it from starting the game, so
    # the auto-start switch is turned off for this launch and restored in the
    # `finally` below. Its value is kept in state first, so a process killed before
    # the `finally` (10-16 02:35) does not lose it.
    memo = _memo_path(state_dir)
    kept = _memo_read(memo)
    if kept is None and (now := _okww_autostart_now(root)) is not None:
        _memo_write(memo, now)
    was = _okww_autostart(root, False)
    if was is None:
        _note(problems, "OK-WW 预更新：改不动 Basic Options.json 里的自动开游戏开关，没有检查更新")
        return ""
    if kept is not None:
        # An earlier run turned it off and never put it back: the record has the real value.
        was = kept
    launched = False
    try:
        # require_console: in session 0 OK-WW's updater does not run.
        if not _spawn_interactive(exe, root, require_console=True, minimized=True):
            log.warning("预更新：OK-WW 没能在控制台会话启动，本轮没有检查更新")
            _note(problems, "OK-WW 预更新：拿不到控制台会话，**没有检查更新**"
                            "（不是「无需更新」）")
            return ""
        launched = True
        log.info("预更新：已启动 OK-WW（已临时关掉自动开游戏），最多 %.0f 秒", budget_s)
        settled, checked, failed, stuck, latest_avail = _okww_await_update(
            root, budget_s, before_version, before_avail, before_stamp, stopping=stopping)
        if stopping():
            # No verdict, no note, no screenshot: the next boot runs the pre-update again.
            log.info("预更新：中继正在停止，不等 OK-WW 了，关掉它、放回开关")
            return ""
        _okww_report(problems, budget_s, before_version, latest_avail,
                     settled, checked, failed, stuck, _okww_timeout_shot() if stuck else None)
        if not before_version:
            _note(problems, "OK-WW 预更新：启动前读不到 app.json 里的版本号，这次装没装上新版没法比对"
                            f"（现在是 {_okww_state(root)[0] or '版本未知'}）")
        return f"OK-WW 已更新：{_span(before_version, settled)}" if settled else ""
    finally:
        # Close OK-WW and anything it started, also when something above raised,
        # and before the switch is restored (a running OK-WW writes its settings
        # back). The ok-ww.exe killed here is the one started above: _okww_quiesce
        # ran before the spawn. It is also closed when the update is still running
        # (stuck); the problem note lets the relay retry later.
        # Closed for real before the switch is put back (audit 11-08 A-22): a quiesce alone
        # does not wait for ok-ww.exe to be gone, and one that exits slowly writes its
        # in-memory settings - the switch off - over the restored file. A stopping relay
        # has its 15 s hard exit: the quiesce only, as before.
        clean = not launched
        try:
            if launched:
                _close(exe)
                if stopping():
                    _okww_quiesce()
                    clean = True
                else:
                    try:
                        still = _okww_close()
                    except Exception:
                        log.warning("预更新：核实 OK-WW 关没关干净时出错", exc_info=True)
                        still = ["（没能核实）"]
                    clean = not still
                    if still:
                        log.warning("预更新：OK-WW 关完还在（%s），自动开游戏开关照样放回，"
                                    "下次开机没有 OK-WW 在跑时再放一次", "、".join(still))
                    else:
                        # OK-WW closed: its own python may be run (ledger #115).
                        try:
                            if fixed := ensure_okww_deps(root, problems):
                                log.info("预更新：%s", fixed)
                        except Exception:
                            log.warning("预更新：核对 OK-WW 自带的 Python 包时出错", exc_info=True)
        finally:
            back = _okww_autostart(root, was)   # put it back as we found it
            if back is None:
                from ark_relay.core import texts  # noqa: PLC0415
                log.warning("%s", texts.okww_autostart_not_restored(bool(was)))
            elif clean:
                _memo_drop(memo)


# Only public names are re-exported. Callers that need a private name import it
# from the module that defines it.


# Runs at most once per day: a service restart after a clean run does not run it
# again, and a run that left something unconfirmed may be retried after RETRY_MIN.
RETRY_MIN = 20          # minutes before a run that left something unconfirmed may be retried


def should_run(state_dir: "Path | None", now: datetime,
               *, had_problems: bool = False) -> bool:
    """Whether the pre-update should run today.

    * Finished cleanly today -> False.
    * Ran today but left something unconfirmed -> True once RETRY_MIN minutes
      have passed since that run.
    * Not run today, or no state directory -> True.
    """
    if not state_dir:
        return True
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    st = StateStore(state_dir).get("updates", "preupdate")
    if not isinstance(st, dict):
        return True
    if st.get("day") != now.strftime("%Y-%m-%d"):
        return True
    if st.get("clean"):
        return False
    try:
        last = datetime.fromisoformat(str(st.get("at")))
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= RETRY_MIN * 60


def mark_run(state_dir: "Path | None", now: datetime, *, clean: bool) -> None:
    if not state_dir:
        return
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(state_dir).set("updates", "preupdate",
                                  {"day": now.strftime("%Y-%m-%d"), "at": now.isoformat(),
                                   "clean": bool(clean)})
    except OSError:
        log.warning("预更新的记账写不下来，下次重启可能会重跑一遍", exc_info=True)


def wanted_today(automas_dir: Path | None, now: datetime | None = None,
                 kind: str = "OK-WW") -> bool:
    """True when a queue still to come today runs `kind`.

    OK-WW by default: it is the one program the pre-update still launches (its
    update overwrites the local patches, which are re-applied right after), so
    the pre-update is wanted only before a queue that runs it. Read from
    AUTO-MAS's own schedule (plan.schedule); queue times already past are ignored.
    """
    from ark_relay.core import plan  # noqa: PLC0415 - avoids an import cycle

    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    cfg_dir = Path(automas_dir) / "config" if automas_dir else None
    if not cfg_dir or not cfg_dir.is_dir():
        return False
    scripts = plan._scripts(cfg_dir)
    for q in plan.schedule(automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due < now:
                continue
            # Only the items that run at that time on that day (plan.runs_at: the
            # weekday rules and the relay's own one-day skip).
            if any((scripts.get(uid) or {}).get("kind") == kind
                   for uid in plan.runs_at(q, hhmm, due)):
                return True
    return False


def worst_case_seconds() -> float:
    """The longest the boot pre-update can run, summed from its own budgets and hang guards.

    scripts/windows/deploy_watch.py waits up to this much longer for the main loop's
    「已挂上 AUTO-MAS 进程句柄」 while the pre-update runs: on 2026-10-16 02:33 a deploy
    restart was the day's first boot, AUTO-MAS really updated (72 s) and OK-WW took its
    45 s minimum, the 120 s watch failed, and the rollback's stop hard-exited the relay.

    AUTO-MAS: the wait for its backend, plus one more HTTP try that began just before that
    wait ran out (a check and a version read), the download, the install. OK-WW: a quiesce
    before, the close after (okww_close_max_seconds: until 11-08 a quiesce that did not look
    again), the scheduled-task launch, closing ok-ww.exe, its budget, and the
    package check after it (preupdate_okww.ensure_okww_deps: an import, a pip install, the
    import again, each under PWSH_GUARD_S).
    boot_stages._once_more may run each item twice.
    """
    automas = (MAS_WAIT_SECONDS + 2 * _MAS_HTTP_TIMEOUT
               + MAS_BUDGET_SECONDS + MAS_INSTALL_WAIT_SECONDS)
    okww = (OKWW_QUIESCE_MAX_SECONDS + okww_close_max_seconds() + PWSH_GUARD_S + TASKKILL_GUARD_S
            + OKWW_BUDGET_SECONDS + 3 * PWSH_GUARD_S)
    return float(2 * (automas + okww))

__all__ = ['MAS_BUDGET_SECONDS', 'MAS_WAIT_SECONDS', 'OKWW_BUDGET_SECONDS', 'OKWW_MIN_WAIT_SECONDS', 'RETRY_MIN', 'log', 'mark_run', 'restore_autostart_leftover', 'run_automas', 'run_okww', 'should_run', 'wanted_today', 'worst_case_seconds']
