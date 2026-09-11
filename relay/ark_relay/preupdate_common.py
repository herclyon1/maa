"""preupdate_common: split out of preupdate.py (2026-09-08, moved verbatim)."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path



log = logging.getLogger("ark.preupdate")

# How long to let MaaEnd sort itself out. An update measured 17 seconds from
# launch to the restarted process, plus download time on a line that is slow to
# reach GitHub. The boot-to-queue gap is 13 minutes in the morning and 8 in the
# evening, so three minutes is affordable; overrunning it costs nothing but a
# round that behaves the way it does today.
BUDGET_SECONDS = 180
# The line MaaEnd writes once its update check has settled.
_DONE = re.compile(r"更新检查完成: 最新版本=(\S+?), 有更新=(true|false)")
_UPDATED = re.compile(r"检测到刚更新完成: (\S+)")
# 「检查更新: MaaEnd, 当前版本: v2.26.0-beta.1, 频道: beta」 - the line written at
# startup. The update notification has to say which version we came up from;
# reporting only the new version number does not show what happened.
_CURRENT = re.compile(r"当前版本[:：]\s*(\S+?)[,，]")


def _note(problems: list[str] | None, msg: str) -> None:
    """Record a pre-update problem for the caller to alert on.

    Every `run_*` here used to return "" for both "nothing to do" and "I could
    not tell" - the two look identical to the caller, and on 2026-08-25 the
    second was reported to the operator as the first. A problem must be able
    to leave the function.
    """
    if problems is not None:
        problems.append(msg)


def _log_dir(maaend_dir: Path) -> Path:
    return Path(maaend_dir) / "debug"


def _newest_log(maaend_dir: Path) -> Path | None:
    """MaaEnd names its log <date>-<n>.log and starts a new one per launch."""
    try:
        logs = sorted(_log_dir(maaend_dir).glob("2*.log"),
                      key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return logs[-1] if logs else None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_from(path: Path, byte_offset: int) -> str:
    """Read from a **byte** offset, then decode.

    2026-08-26: this used to be `_read(path)[before_len:]`, where `before_len`
    was `stat().st_size` - a **byte** count, applied to slice the decoded
    **character** string. MAA's gui.log is full of Chinese, where one character
    is 3 bytes and 1 character, so the offset was always too large; the slice
    overshot and skipped the whole of the new content, the patterns never
    matched again, and every round waited out the full 180 seconds and then
    reported 「没给出更新结论」.

    The log is UTF-8 and only ever appended to, so seeking by byte and then
    decoding is safe.

    **But MAA itself breaks that "only ever appended to" premise**: on every
    launch it moves the previous `gui.log` aside as `gui.bak.log` and starts a
    fresh one at byte 0. The offset we recorded is the size of the file from
    **before** the launch (a few hundred KB); seeking that far into a new 12 KB
    file makes read return empty forever. That is exactly what happened on
    2026-09-04: MAA had already answered 「current version is latest」 at
    08:46:26, the patterns saw not one character of it, we waited out the full
    180 seconds, raised a false 「没能确认」 alarm, and held up everything else
    in that tick as well.
    So a file smaller than the offset means it was rotated or truncated: read
    from the start.
    """
    try:
        with path.open("rb") as fh:
            if byte_offset and path.stat().st_size < byte_offset:
                log.info("%s 比记下的偏移还小，判定被轮转过，从头读", path.name)
                byte_offset = 0
            fh.seek(byte_offset)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


# The scheduled-task route: used to drop a program into the interactive desktop
# session when the console token cannot be had.
#
# Measured 2026-08-26: **a real LocalSystem service cannot get the token either**:
#   08-26 08:51:30 预更新：拿控制台令牌失败，拒绝在 session 0 启动 ok-ww.exe
#   pywintypes.error: (1314, 'WTSQueryUserToken', '客户端没有所需的特权。')
# 1314 means SE_TCB_NAME is missing. LocalSystem nominally holds that privilege,
# but inside pywin32's service host it is not in the enabled state, so the call
# is refused all the same. All three pre-update errors share this one root
# cause; they are not three separate things.
#
# And **a route that works has been in this very repo all along**:
# `_revive_automas()` starts AUTO-MAS with `schtasks /run`, and
# `scripts/mac/winrun.sh --py1` runs scripts in the desktop session with
# `Register-ScheduledTask` + `LogonType Interactive`. The Task Scheduler service
# creates the process on our behalf, so the caller does not need SE_TCB_NAME.
def _spawn_via_task(exe: Path, cwd: Path, args: tuple[str, ...] = ()) -> bool:
    """Start exe in the interactive desktop session via a one-shot scheduled task. True on success."""
    # One task name per program: two launches seconds apart under a shared
    # name made Register-ScheduledTask -Force stop the first instance while
    # the second was starting (2026-09-12 01:27, MaaEnd then Endfield - the
    # first MaaEnd died holding port 12701 and the second fell back to 12702).
    task = "ark-preupdate-launch-" + "".join(c if c.isalnum() else "-" for c in exe.stem)[:40]
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
        # Unregister the task once it has started so no litter is left on the
        # system. The program itself is unaffected.
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
    log.info("预更新：已通过计划任务在交互会话启动 %s", exe.name)
    return True


_PWSH7 = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")


def _pwsh() -> str:
    """PowerShell 7 only. 5.1 does not default to UTF-8 and mangles Chinese paths through ANSI decoding.

    If it is missing we still do not fall back to 5.1: falling back makes the
    command "succeed" while producing mojibake, which is worse than failing.
    This only writes one ERROR line; the caller gets a path that does not exist
    and raises OSError on the spot.
    """
    if not _PWSH7.exists():
        log.error("找不到 %s：这台机器必须装 PowerShell 7", _PWSH7)
    return str(_PWSH7)


# Two values of TOKEN_INFORMATION_CLASS. pywin32 versions disagree about where
# these constants are exposed (both win32security and ntsecuritycon have been
# seen), so look them up by name and fall back to the documented numbers - one
# constant name must not be able to break the whole route.
_TOKEN_ELEVATION_TYPE = 18
_TOKEN_LINKED_TOKEN = 19
_ELEVATION_LIMITED = 3          # TokenElevationTypeLimited


def _console_primary_token(session: int):
    """The console user's token - **the one UAC has not filtered**.

    `WTSQueryUserToken` hands back the logged-in user's **restricted** token.
    Use it to start a program whose manifest says `requireAdministrator`
    (OK-WW does) and `CreateProcessAsUser` is bound to fail:

        pywintypes.error: (740, 'CreateProcessAsUser', '请求的操作需要提升。')

    Before 2026-08-27 every boot hit this and the whole route fell back to the
    scheduled task - which works, but sprayed a traceback into the log on every
    pre-update round, burying genuinely new errors, and left no interactive
    session at all if the scheduled-task route ever broke too.

    UAC splits an administrator account's token into a pair: the one in hand is
    the restricted half, and the full half hangs off it via `TokenLinkedToken`.
    Fetch that and duplicate it into a primary token.

    A failure at any step returns the restricted token unchanged - the worst
    case is exactly what it was before this change.
    """
    import win32con  # noqa: PLC0415
    import win32security  # noqa: PLC0415
    import win32ts  # noqa: PLC0415

    token = win32ts.WTSQueryUserToken(session)
    linked = None
    try:
        cls_elev = getattr(win32security, "TokenElevationType", _TOKEN_ELEVATION_TYPE)
        if win32security.GetTokenInformation(token, cls_elev) != _ELEVATION_LIMITED:
            return token                     # not split; it was already the full token
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
    """Build the STARTUPINFO for CreateProcessAsUser: name the desktop and, when asked, open the window minimized.

    A separate step because these few lines are the entirety of the settings for
    "open a window on somebody else's desktop", and both were learned the hard
    way: without lpDesktop the process dies anyway, and minimizing is something
    the user explicitly asked for. Sandwiched between fetching the token and
    assembling the command line it looks like boilerplate and is easy to delete
    in passing.
    """
    import win32con  # noqa: PLC0415
    import win32process  # noqa: PLC0415

    startup = win32process.STARTUPINFO()
    # Without this the process has no window station and dies the same way.
    startup.lpDesktop = "winsta0\\default"
    if minimized:
        # The user, 2026-09-02: 「检查更新的时候桌面我希望不要出现任何东西」.
        # Start it minimized; a program that ignores this flag will still pop up
        # a window (not yet verified in practice).
        startup.dwFlags |= win32con.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_SHOWMINNOACTIVE
    return startup


def _close_handles(handles) -> None:
    """Close the handles CreateProcessAsUser hands back, one by one.

    A separate step because "could not close" must never affect the verdict: the
    process is already running, and one failed Close is a handle leak, not
    something that should be caught by the except above and turned into "launch
    failed".
    """
    for h in handles:
        try:
            h.Close()
        except Exception:  # noqa: BLE001 - handle cleanup only
            pass


def _spawn_fallback(exe: Path, cwd: Path, args: tuple[str, ...],
                    *, require_console: bool) -> bool:
    """The way out when the token route fails: try the scheduled task first, then decide whether to fall back to a plain launch.

    A separate step because the order matters. The Task Scheduler creates the
    process on our behalf and does not require the caller to hold SE_TCB_NAME,
    so it goes first; when that fails too, require_console decides between
    **failing honestly** and falling back to session 0 - and that fallback is
    exactly the path that on 2026-08-25 turned 「没检查成」 into 「无需更新」.
    This branch has to be readable at a glance.
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

    The relay is a LocalSystem service, so it runs in session 0, which has no
    desktop. A GUI program started from there gets as far as touching its own
    log file and then dies. That is not a theory: the pre-update launched
    MaaEnd three times over two days, no run ever produced a MaaFW log, and
    every one of them timed out at the full budget while mxu-tauri.log was
    freshly stamped and empty. Hand the process the console user's token so it
    lands on a real desktop.

    Falls back to a plain launch when there is no console session or the token
    cannot be had - unless `require_console`, which refuses instead.

    That flag exists because "no worse than refusing to try" turned out to be
    wrong. On 2026-08-25 the console token was unavailable at 08:48 (40 seconds
    after boot), OK-WW was launched into session 0 anyway, its updater never
    ran, and the caller read the unchanged version file as **"无需更新"** and
    said so in the log. v3.6.5 had been out for fourteen hours. A false
    negative is worse than an honest failure: nobody goes looking for a problem
    that was reported as fine. Relaunching by hand in the console session
    applied the update in ten seconds.
    """
    try:
        import win32con  # noqa: PLC0415
        import win32process  # noqa: PLC0415
        import win32profile  # noqa: PLC0415
        import win32ts  # noqa: PLC0415
    except ImportError:
        return _spawn_detached(exe, cwd, args)

    token = None
    try:
        session = win32ts.WTSGetActiveConsoleSessionId()
        if session in (0, 0xFFFFFFFF):
            if require_console:
                log.warning("预更新：没有交互会话，拒绝在 session 0 启动 %s", exe.name)
                return False
            log.info("预更新：没有交互会话，退回普通启动")
            return _spawn_detached(exe, cwd, args)
        # The unfiltered token - a restricted token starting a
        # requireAdministrator program always fails with 740.
        token = _console_primary_token(session)
        env = win32profile.CreateEnvironmentBlock(token, False)
        startup = _startup_info(minimized)
        # CreateProcessAsUser wants the exe repeated as argv[0].
        cmd = subprocess.list2cmdline([str(exe), *args])
        # hidden: console programs such as the desktop helper must not open a
        # window - measured 09-03, its PowerShell window covered the game and
        # OCR was reading our own window. CREATE_NO_WINDOW leaves it without a
        # console.
        flags = (0x08000000 if hidden else win32con.CREATE_NEW_CONSOLE) | win32process.CREATE_UNICODE_ENVIRONMENT
        handles = win32process.CreateProcessAsUser(
            token, str(exe), cmd, None, None, False, flags,
            env, str(cwd), startup)
        _close_handles(handles)
        log.info("预更新：已在会话 %s 启动 %s", session, exe.name)
        return True
    except Exception:
        # Failing to get the token is not the end of it: switch to the
        # scheduled-task route, where Task Scheduler creates the process for us
        # and the caller needs no SE_TCB_NAME. **This is the normal path** -
        # measured 2026-08-26, the real service ends up here every time.
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
    """Plain detached launch - correct when the relay itself is interactive."""
    try:
        subprocess.Popen(
            [str(exe), *args], cwd=str(cwd),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                           | subprocess.DETACHED_PROCESS))
    except OSError:
        log.warning("预更新：启动 %s 失败，本轮照旧", exe.name, exc_info=True)
        return False
    return True
