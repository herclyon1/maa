"""preupdate_common：从 preupdate.py 拆出（2026-09-08，只搬不改）。"""
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
# 「检查更新: MaaEnd, 当前版本: v2.26.0-beta.1, 频道: beta」——启动时写的那行。
# 更新通知要带上「从哪个版本升上来的」，只报新版本号看不出发生了什么。
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
    """从**字节**偏移开始读，再解码。

    2026-08-26：原来是 `_read(path)[before_len:]`，而 `before_len` 是
    `stat().st_size`——**字节数**，切的却是解码后的**字符**串。
    MAA 的 gui.log 满是中文，一个汉字 3 字节 1 字符，于是偏移永远偏大，
    一刀切过头把新增内容整段跳掉，判据再也匹配不到，
    每次都白等满 180 秒然后报「没给出更新结论」。

    日志是 UTF-8 且只在末尾追加，所以按字节 seek 再解码是安全的。

    **但「只在末尾追加」这个前提，MAA 自己会打破**：它每次启动都把上一份
    `gui.log` 挪成 `gui.bak.log`，新开一份从 0 字节写起。我们记的偏移是
    启动**前**那份的大小（几百 KB），拿去 seek 一份 12 KB 的新文件，
    read 永远返回空——2026-09-04 就是这样：MAA 08:46:26 已经答了
    「current version is latest」，判据一个字也没看见，白等满 180 秒，
    再报一条「没能确认」的假警报，还把 tick 后面的事都耽误了。
    所以文件比偏移还小 = 它被轮转或截断过，从头读。
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


# 计划任务这条路：拿不到控制台令牌时，用它把程序丢进交互桌面会话。
#
# 2026-08-26 实测，**真实的 LocalSystem 服务也拿不到令牌**：
#   08-26 08:51:30 预更新：拿控制台令牌失败，拒绝在 session 0 启动 ok-ww.exe
#   pywintypes.error: (1314, 'WTSQueryUserToken', '客户端没有所需的特权。')
# 1314 是缺 SE_TCB_NAME。LocalSystem 名义上有这个特权，但 pywin32 的服务宿主
# 里它不是启用状态，所以调用照样被拒。三条预更新报错是同一个根因，不是三件事。
#
# 而**同一个仓库里早就有一条走得通的路**：`_revive_automas()` 用 `schtasks /run`
# 拉 AUTO-MAS，`scripts/mac/winrun.sh --py1` 用 `Register-ScheduledTask` +
# `LogonType Interactive` 在桌面会话里跑脚本。计划任务由 Task Scheduler 服务
# 代为创建进程，不需要调用方持有 SE_TCB_NAME。
def _spawn_via_task(exe: Path, cwd: Path, args: tuple[str, ...] = ()) -> bool:
    """用一次性计划任务把 exe 拉进交互桌面会话。成功返回 True。"""
    task = "ark-preupdate-launch"
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
        # 起来之后就把任务注销掉，别在系统里留垃圾。程序本身不受影响。
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
    """只认 PowerShell 7。5.1 默认不是 UTF-8，中文路径会被 ANSI 解码毁掉。

    不存在也不退回 5.1：退回去的话命令「跑成功了」但结果是乱码，比失败更坏。
    这里只写一条 ERROR，调用方拿到不存在的路径会当场报 OSError。
    """
    if not _PWSH7.exists():
        log.error("找不到 %s：这台机器必须装 PowerShell 7", _PWSH7)
    return str(_PWSH7)


# TOKEN_INFORMATION_CLASS 的两个取值。pywin32 各版本对这些常量的暴露位置
# 不一致（win32security / ntsecuritycon 都出现过），所以按名字取、取不到就用
# 文档里的数字，免得因为一个常量名让整条路走不通。
_TOKEN_ELEVATION_TYPE = 18
_TOKEN_LINKED_TOKEN = 19
_ELEVATION_LIMITED = 3          # TokenElevationTypeLimited


def _console_primary_token(session: int):
    """控制台用户的令牌，**要没被 UAC 过滤的那一个**。

    `WTSQueryUserToken` 交回来的是登录用户的**受限**令牌。用它去启动
    清单里写了 `requireAdministrator` 的程序（OK-WW 就是），
    `CreateProcessAsUser` 必然失败：

        pywintypes.error: (740, 'CreateProcessAsUser', '请求的操作需要提升。')

    2026-08-27 之前每次开机都撞这一下，然后整条路退到计划任务方式——
    能用，但每轮预更新都往日志里刷一段 traceback，把真正的新错埋掉，
    而且计划任务那条路一旦也坏了就彻底没有交互会话可用。

    UAC 把管理员账户的令牌拆成一对：手上这个是受限的一半，完整的那一半
    通过 `TokenLinkedToken` 挂在它上面。取过来复制成主令牌即可。

    任何一步失败都原样返回受限令牌——最坏情况和改动前完全一致。
    """
    import win32con  # noqa: PLC0415
    import win32security  # noqa: PLC0415
    import win32ts  # noqa: PLC0415

    token = win32ts.WTSQueryUserToken(session)
    linked = None
    try:
        cls_elev = getattr(win32security, "TokenElevationType", _TOKEN_ELEVATION_TYPE)
        if win32security.GetTokenInformation(token, cls_elev) != _ELEVATION_LIMITED:
            return token                     # 没被拆分，本来就是完整的
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
        # 未过滤的令牌——受限令牌启动 requireAdministrator 的程序必然报 740。
        token = _console_primary_token(session)
        env = win32profile.CreateEnvironmentBlock(token, False)
        startup = win32process.STARTUPINFO()
        # Without this the process has no window station and dies the same way.
        startup.lpDesktop = "winsta0\\default"
        if minimized:
            # 用户 2026-09-02：「检查更新的时候桌面我希望不要出现任何东西」。
            # 启动时就让它最小化；不认这个标志的程序会照常弹窗（待实测）。
            startup.dwFlags |= win32con.STARTF_USESHOWWINDOW
            startup.wShowWindow = win32con.SW_SHOWMINNOACTIVE
        # CreateProcessAsUser wants the exe repeated as argv[0].
        cmd = subprocess.list2cmdline([str(exe), *args])
        # hidden：桌面助手那种控制台程序不能开窗——09-03 实测它的 PowerShell 窗口
        # 把游戏盖住，OCR 读到的是自己的窗口。CREATE_NO_WINDOW 让它没有控制台。
        flags = (0x08000000 if hidden else win32con.CREATE_NEW_CONSOLE) | win32process.CREATE_UNICODE_ENVIRONMENT
        handles = win32process.CreateProcessAsUser(
            token, str(exe), cmd, None, None, False, flags,
            env, str(cwd), startup)
        for h in handles:
            try:
                h.Close()
            except Exception:  # noqa: BLE001 - handle cleanup only
                pass
        log.info("预更新：已在会话 %s 启动 %s", session, exe.name)
        return True
    except Exception:
        # 令牌拿不到不代表没救：换计划任务那条路，它由 Task Scheduler 代为
        # 建进程，不要求调用方持有 SE_TCB_NAME。**这才是常态路径**——
        # 2026-08-26 实测真实服务每次都走到这里。
        log.warning("预更新：拿控制台令牌失败，改用计划任务方式", exc_info=True)
        if _spawn_via_task(exe, cwd, args):
            return True
        if require_console:
            log.warning("预更新：计划任务也没能把 %s 放进交互会话，本轮放弃",
                        exe.name)
            return False
        log.warning("预更新：计划任务也失败，退回普通启动")
        return _spawn_detached(exe, cwd, args)
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
