"""Shared parts of the pre-update: log reading, closing a program, and starting a
GUI program on the interactive desktop from the relay's service session."""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path


log = logging.getLogger("ark.preupdate")



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
            capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("预更新：关闭 %s 失败", exe.name, exc_info=True)


# The scheduled-task route. The relay's service host cannot get the console
# user's token (WTSQueryUserToken fails with 1314, SE_TCB_NAME not enabled), so a
# GUI program is started by the Task Scheduler service with an Interactive
# logon instead; the caller then needs no SE_TCB_NAME.
def _task_name(stem: str) -> str:
    return "ark-preupdate-launch-" + "".join(c if c.isalnum() else "-" for c in stem)[:40]


def _spawn_via_task(exe: Path, cwd: Path, args: tuple[str, ...] = (),
                    *, task: "str | None" = None, label: "str | None" = None) -> bool:
    """Start exe in the interactive desktop session via a one-shot scheduled task. True on success.

    `task` overrides the task name, `label` the program name in the log line.
    """
    # One task name per program, so two launches seconds apart do not replace
    # each other's task (Register-ScheduledTask -Force stops a running instance).
    task = task or _task_name(exe.stem)
    quoted = subprocess.list2cmdline(list(args)) if args else ""
    ps = (
        f'$ErrorActionPreference="Stop";'
        f'Unregister-ScheduledTask -TaskName "{task}" -Confirm:$false '
        f'-ErrorAction SilentlyContinue;'
        f'$a=New-ScheduledTaskAction -Execute "{exe}" '
        + (f'-Argument "{quoted}" ' if quoted else "")
        + f'-WorkingDirectory "{cwd}";'
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
            capture_output=True, timeout=60, check=False)
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

    Without pythonw.exe it falls back to the plain task route, with a warning.
    """
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
    """
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
    except Exception:
        # The relay's service host normally ends up here (no SE_TCB_NAME).
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
