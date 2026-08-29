"""Get MaaEnd's self-update out of the way before a queue needs it.

The problem this exists for, measured on 2026-08-22:

MaaEnd checks for updates only at startup, and AUTO-MAS kills and relaunches it
before every round - so every round lands on that check. When there is a new
build, MaaEnd downloads it and **restarts its own process**. AUTO-MAS's log
monitor is attached to the pid it launched, that pid is gone, and every task in
the round is reported failed about four seconds later:

    11:47:57  AUTO-MAS starts MaaEnd
    11:47:58  MaaEnd.exe pid=15772 takes focus
    11:48:14  MaaEnd.exe pid=20416 takes focus     <- restarted after updating
    11:48:18  all 14 tasks fail

The retry then succeeds, because by then the update is done - which is exactly
the "fails once or twice then heals itself" pattern that has been written off as
a window race for days. MaaEnd's own log says it plainly on the second attempt:
"检测到刚更新完成: v2.26.0-beta.1".

The update channel is `beta`, which ships most days, so most days start with a
wasted attempt and a failure alert.

Turning auto-update off is not an option - staying current is the point of it.
So the update is moved instead of removed: run MaaEnd once in the gap between
boot and the first queue, let it update and restart there where nothing is
watching, and close it. By the time the queue starts, the check returns
"有更新=false" and the process it launches is the one that stays.

Upstream declined to fix the underlying window-focus behaviour (MaaEnd#4820),
so this is handled from our side or not at all.

Measured side effects of launching MaaEnd on its own, 2026-08-22 12:37:

    12:37:12 WARN  [App] 自动执行：目标实例不存在，跳过自动执行
    12:37:12 INFO  [App] 检查更新: MaaEnd, 当前版本: v2.26.0-beta.1, 频道: beta
    12:37:13 INFO  [App] 更新检查完成: 最新版本=v2.26.0-beta.1, 有更新=false

It does not launch the game (verified over 64 seconds - only MaaEnd.exe ran),
it does not start its configured tasks, and the check itself takes one second.
So on the ordinary day, when there is nothing to update, this costs a few
seconds and touches nothing.

Why not check for the update from here and skip the launch entirely: doing that
means reimplementing MaaEnd's own version lookup - its MirrorChyan resource id,
its channel, its version format - and keeping that in step with a program that
ships most days. The launch already answers the question authoritatively in one
second, with no side effects worth avoiding. Downloading and applying the update
from here would be worse still: that is MaaEnd's updater, including whatever
file replacement and migration it does, and reimplementing it earns nothing but
a second thing to keep correct.

Failure here is deliberately cheap: if the pre-update cannot run, does not
finish, or the network is slow, the round proceeds exactly as it does today -
one wasted attempt, then the retry succeeds.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .config import atomic_write_text, SERVER_TZ

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
    """
    try:
        with path.open("rb") as fh:
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
        r = subprocess.run(  # noqa: S603
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


def _pwsh() -> str:
    """PowerShell 7 优先。5.1 默认不是 UTF-8，中文路径会被 ANSI 解码毁掉。"""
    seven = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")
    return str(seven) if seven.exists() else "powershell"


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
    except Exception:  # noqa: BLE001 - 拿不到就用受限的，不比以前差
        log.debug("预更新：取不到未过滤的控制台令牌，沿用受限令牌", exc_info=True)
        return token
    finally:
        for h in (linked,):
            try:
                if h is not None:
                    h.Close()
            except Exception:  # noqa: BLE001, S110 - handle cleanup only
                pass
    try:
        token.Close()
    except Exception:  # noqa: BLE001, S110 - handle cleanup only
        pass
    return primary


def _spawn_interactive(exe: Path, cwd: Path,
                       args: tuple[str, ...] = (),
                       *, require_console: bool = False) -> bool:
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
        # CreateProcessAsUser wants the exe repeated as argv[0].
        cmd = subprocess.list2cmdline([str(exe), *args])
        handles = win32process.CreateProcessAsUser(
            token, str(exe), cmd, None, None, False,
            win32con.CREATE_NEW_CONSOLE | win32process.CREATE_UNICODE_ENVIRONMENT,
            env, str(cwd), startup)
        for h in handles:
            try:
                h.Close()
            except Exception:  # noqa: BLE001, S110 - handle cleanup only
                pass
        log.info("预更新：已在会话 %s 启动 %s", session, exe.name)
        return True
    except Exception:  # noqa: BLE001 - any failure falls back, never raises
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
            except Exception:  # noqa: BLE001, S110
                pass


def _spawn_detached(exe: Path, cwd: Path,
                    args: tuple[str, ...] = ()) -> bool:
    """Plain detached launch - correct when the relay itself is interactive."""
    try:
        subprocess.Popen(  # noqa: S603
            [str(exe), *args], cwd=str(cwd),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                           | subprocess.DETACHED_PROCESS))
    except OSError:
        log.warning("预更新：启动 %s 失败，本轮照旧", exe.name, exc_info=True)
        return False
    return True


# MaaEnd's UI is MXU (MistEO/MXU) - MaaEnd.exe reports ProductName "mxu".
# Two facts from its source decide how the pre-update has to launch it:
#
#   1. On the boot right after an update, App.tsx shows a "更新完成" modal and
#      then *returns* - the update check that follows never runs. The only
#      branch that skips that modal is `isAutoStartMode`, set by --autostart.
#      Without it the pre-update waits out its whole budget for a line that
#      will never be written, which is exactly what it did on 08-24 01:38.
#
#   2. --autostart also arms auto-run: `shouldAutoRun = isAutoStart ||
#      autoRunOnLaunch`, and the instance picked is `cliInstanceId ||
#      autoStartInstanceId`. Today nothing runs only because this machine's
#      autoStartInstanceId names an instance that no longer exists. The day
#      someone sets a real one in the UI, the 08:40 pre-update would start a
#      farming round. Clearing the field for the duration removes the whole
#      branch: `shouldAutoRun && targetInstanceId` cannot be true with no id.
_MAAEND_AUTOSTART = ("--autostart",)


def _maaend_autostart_instance(maaend_dir: Path, value: str) -> str | None:
    """Set settings/autoStartInstanceId, returning what it was. None if it could not."""
    cfg = Path(maaend_dir) / "config" / "mxu-MaaEnd.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        settings = data["settings"]
        was = settings.get("autoStartInstanceId", "")
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("预更新：读不到 MaaEnd 的 settings，跳过 MaaEnd")
        return None
    if was == value:
        return was
    settings["autoStartInstanceId"] = value
    try:
        tmp = cfg.with_suffix(cfg.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(cfg)
    except OSError:
        log.warning("预更新：写不回 MaaEnd 的 settings，跳过 MaaEnd", exc_info=True)
        return None
    return was


def run(maaend_dir: Path | None, budget_s: float = BUDGET_SECONDS,
        problems: list[str] | None = None) -> str:
    """Launch MaaEnd, wait for its update check, close it. Returns a note or "".

    The note is non-empty only when an update actually landed - that is the
    thing worth telling the operator about, and it is the operator's standing
    rule that an update which takes effect gets announced.
    """
    if not maaend_dir:
        return ""
    exe = Path(maaend_dir) / "MaaEnd.exe"
    if not exe.exists():
        log.warning("预更新跳过：找不到 %s", exe)
        return ""

    # Disarm auto-run before --autostart can act on it. Restored in the finally
    # below, after MaaEnd has exited - restoring while it still runs would just
    # be overwritten by its own config save.
    was_instance = _maaend_autostart_instance(Path(maaend_dir), "")
    if was_instance is None:
        return ""

    try:
        return _run_maaend(Path(maaend_dir), exe, budget_s, problems)
    finally:
        _maaend_autostart_instance(Path(maaend_dir), was_instance)


def _maaend_version_in(log_file: Path | None) -> str:
    """某个 MaaEnd 日志里最后一次自报的版本号；读不到返回空串。"""
    if not log_file:
        return ""
    hits = _CURRENT.findall(_read(log_file))
    return hits[-1] if hits else ""


def _maaend_span(old: str, new: str) -> str:
    """「旧版 → 新版」。旧版号没拿到就只报新版，不编。"""
    return f"{old} → {new}" if old and old != new else new


def _run_maaend(maaend_dir: Path, exe: Path, budget_s: float,
                problems: list[str] | None = None) -> str:
    """The body of run(), with auto-run already disarmed by the caller."""
    before = _newest_log(maaend_dir)
    before_name = before.name if before else ""
    deadline = time.monotonic() + budget_s
    # In the console session, not session 0 - see _spawn_interactive.
    if not _spawn_interactive(exe, maaend_dir, _MAAEND_AUTOSTART):
        return ""
    log.info("预更新：已启动 MaaEnd（--autostart，已清空自动执行实例），最多 %.0f 秒",
             budget_s)

    updated_to = ""
    # 升级前的版本号。先从上一次启动的日志里兜个底，本次启动自己写的
    # 「当前版本: vX」一出现就覆盖掉它——那个才是准的。
    old_ver = _maaend_version_in(before)
    settled = False
    # Poll quickly at first: measured on the machine, MaaEnd answers its own
    # update check about one second after launch when there is nothing to do
    # (12:37:12 launch, 12:37:13 "有更新=false"). The common case - no update -
    # should cost seconds, not a fixed wait.
    while time.monotonic() < deadline:
        time.sleep(1)
        current = _newest_log(Path(maaend_dir))
        if current is None or current.name == before_name:
            continue        # this launch has not opened its log yet
        text = _read(current)
        if m2 := _CURRENT.search(text):
            # MaaEnd 装完更新会重启自己、另起一个日志文件，那个进程不再写
            # 「当前版本」。所以要在重启之前就把它记下来。
            old_ver = m2.group(1)
        if m := _UPDATED.search(text):
            updated_to = m.group(1)
            # This *is* a conclusion. When MaaEnd starts up straight after
            # applying an update it logs "检测到刚更新完成: vX" and then skips
            # the check entirely - there is no point asking again one second
            # after installing. So no "更新检查完成" line ever arrives, and
            # waiting for one burns the whole budget and reports a failure for
            # a launch that actually updated. Measured 2026-08-26: installed
            # v2.26.0-beta.6 at 08:48:37, then nothing but scheduler polls
            # until we killed it at 08:51:07.
            settled = True
            log.info("预更新：MaaEnd 刚更新完成 → %s（本次启动不再检查）",
                     _maaend_span(old_ver, updated_to))
            break
        if m := _DONE.search(text):
            version, has_update = m.group(1), m.group(2)
            # "有更新=true" means it is still downloading; keep waiting for the
            # restarted process to report false.
            if has_update == "false":
                settled = True
                log.info("预更新：MaaEnd 已是 %s%s", version,
                         f"（本次更新自 → {updated_to}）" if updated_to else "（无需更新）")
                break
    if not settled:
        log.warning("预更新：%.0f 秒内没等到更新检查结束，本轮照旧", budget_s)
        _note(problems,
              f"MaaEnd 预更新：{budget_s:.0f} 秒内没等到更新检查结束，"
              "**本轮没有确认过是否有更新**")

    _close(exe)
    if updated_to and settled:
        return _maaend_span(old_ver, updated_to)
    return ""


def _close(exe: Path) -> None:
    """Leave nothing running. AUTO-MAS kills it before每轮 anyway, but a pre-update
    that leaves a window on the desktop is a pre-update that changed the thing it
    was supposed to leave alone."""
    try:
        subprocess.run(  # noqa: S603
            ["taskkill", "/IM", exe.name, "/F"],
            capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("预更新：关闭 MaaEnd 失败", exc_info=True)


# MAA applies a pending update at startup, in its Bootstrapper, before the app
# is usable - "Delegated pending update completed successfully" in gui.log. That
# is a gentler mechanism than MaaEnd's (which restarts its own process mid-run),
# and it has not been caught breaking a queue here. Moving it into the boot
# window anyway costs a few seconds and removes the possibility.
_MAA_LATEST = re.compile(r'"msg"\s*:\s*"current version is latest"')
_MAA_APPLIED = re.compile(r"Delegated pending update completed successfully")
_MAA_READY = re.compile(r"LoadResource Exit")

# MAA's own flag for "start, but do not begin a run or boot the emulator".
# MAA writes it into its own relaunch chain after applying an update
# (Bootstrapper.SkipStartupAutoRunArg), so this is the vendor's intended way to
# open MAA without setting it to work - not a setting we have to reach in and
# flip. The config flip below stays as a second lock: if a future MAA drops the
# argument, an unknown flag is ignored and 启动后直接运行 would send it straight
# into a farming round at 08:40, which is the one outcome this must never have.
_MAA_NO_AUTORUN = ("--skip-startup-auto-run",)


def _maa_run_directly(maa_dir: Path, value: bool) -> bool | None:
    """Set Default/RunDirectly, returning what it was. None if it could not.

    Launching MAA with 启动后直接运行 on starts a farming round immediately -
    which is the opposite of what a pre-update pass wants. AUTO-MAS itself does
    exactly this dance: AutoProxy sets it True before a run, ScriptConfig sets
    it False when opening MAA to be configured.
    """
    cfg = Path(maa_dir) / "config" / "gui.new.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        node = data["Configurations"]["Default"]["Gui"]["StartUpSettings"]
    except (OSError, ValueError, KeyError):
        log.warning("预更新：读不到 MAA 的 StartUpSettings，跳过 MAA")
        return None
    was = bool(node.get("RunDirectly"))
    if was == value:
        return was
    node["RunDirectly"] = value
    try:
        atomic_write_text(cfg, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        log.warning("预更新：写不了 MAA 配置，跳过 MAA", exc_info=True)
        return None
    return was


# MAA extracts a downloaded update into <MAA>/NewVersion and applies it at the
# next startup ("Pending update package detected, applying before full
# startup"). That directory is the entire signal, and reading it costs nothing:
# no network call, no window, no key. The alternative - asking MirrorChyan - is
# not available to us anonymously: rid "MAA" answers {"code":8001,"resource not
# found"} from both machines, while the public rid "MaaResource" answers fine,
# so the private ones want the CDK. Lifting that key into the relay to save one
# launch a day would buy a secret we otherwise do not hold.
_MAA_PENDING_DIR = "NewVersion"
# ...but that is only the GitHub path. On the MirrorChyan channel MAA downloads
# the update as a **zip in the MAA root** and never creates NewVersion:
#
#   08:45:33 MirrorChyan response: {"version_name":"v6.17.0-beta.6", ...}
#   08:45:33 New version found: v6.17.0-beta.6
#   08:45:34 Remove download temp file D:\ark\maa\MirrorChyanAppv6.17.0-beta.6.zip.temp
#
# 2026-08-26: the update was on disk at 08:45:34, and the pre-update still
# reported "180 秒内没给出更新结论" because it was watching only NewVersion.
# Watch both, or the MirrorChyan channel is invisible to us.
_MAA_PENDING_GLOB = "MirrorChyanApp*.zip"


def maa_update_pending(maa_dir: Path | None) -> bool:
    """True when MAA has an update downloaded and waiting for a restart.

    Two shapes, because MAA has two update channels - see above. A `.temp` file
    is a download still in flight and must not count.
    """
    if not maa_dir:
        return False
    root = Path(maa_dir)
    if (root / _MAA_PENDING_DIR).is_dir():
        return True
    try:
        return any(p.suffix.lower() == ".zip"
                   for p in root.glob(_MAA_PENDING_GLOB))
    except OSError:
        return False


_MAA_VERSION = re.compile(r"Version (v[\w.\-+]+)")


def _maa_version(log_path: Path) -> str:
    """MAA 自己在 gui.log 里报的版本号（`Bootstrapper ... Version v6.17.0-beta.6`）。

    读不到就返回空串——它只用来把日志写得具体一点，不值得让预更新失败。
    """
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-200_000:]
    except OSError:
        return ""
    hits = _MAA_VERSION.findall(tail)
    return hits[-1] if hits else ""


def run_maa(maa_dir: Path | None, budget_s: float = BUDGET_SECONDS,
            problems: list[str] | None = None) -> str:
    """Apply any pending MAA update, and let it look for the next one.

    MAA is the one of the four that updates itself *while running*: it
    downloads into `NewVersion` and a delegated process applies that at the
    following startup. Left alone, that costs a whole queue. An update
    published at 23:00 is only downloaded during the 09:00 run, only applied at
    the 21:20 boot, and only used by the 21:30 queue - a full day behind the
    other three, which update in the boot window.

    So this launches MAA even when nothing is staged, and waits for the
    download to land in `NewVersion` rather than closing the moment the check
    answers - closing mid-download would throw the download away. Whatever is
    staged here is applied by the 09:00 queue's own startup, which is what
    removes the lag.

    The cost is a MAA window during every boot window instead of only on
    update days. It is closed before the queue starts, and being a day late on
    every release was the worse of the two.
    """
    if not maa_dir:
        return ""
    exe = Path(maa_dir) / "MAA.exe"
    log_path = Path(maa_dir) / "debug" / "gui.log"
    if not exe.exists():
        log.warning("预更新跳过：找不到 %s", exe)
        _note(problems, f"MAA 预更新跳过：找不到 {exe}")
        return ""

    staged_before = maa_update_pending(maa_dir)
    was = _maa_run_directly(Path(maa_dir), False)
    if was is None:
        _note(problems, "MAA 预更新：改不动配置，没有检查更新")
        return ""
    before_len = log_path.stat().st_size if log_path.exists() else 0
    applied = ""
    answered = False
    try:
        # session 0 has no desktop; MAA's updater does not run there.
        if not _spawn_interactive(exe, maa_dir, require_console=True):
            log.warning("预更新：MAA 没能在控制台会话启动，本轮没有检查更新")
            _note(problems, "MAA 预更新：拿不到控制台会话，**没有检查更新**")
            return ""
        log.info("预更新：已启动 MAA（已临时关闭「启动后直接运行」），最多 %.0f 秒", budget_s)
        deadline = time.monotonic() + budget_s
        while time.monotonic() < deadline:
            time.sleep(1)
            text = _read_from(log_path, before_len)
            if _MAA_APPLIED.search(text):
                applied = "已应用挂起的更新"
            if _MAA_LATEST.search(text):
                answered = True
                # 别把这行省掉：另外三个程序在「已是最新」时都写一句，
                # 只有 MAA 曾经是哑的，于是日志里看不出它到底查没查过。
                log.info("预更新：MAA 已是 %s（无需更新）", _maa_version(log_path) or "最新版")
                break             # 明说了已是最新，没有下载要等
            if not staged_before and maa_update_pending(maa_dir):
                answered = True
                log.info("预更新：MAA 已把新版下载到 %s，下轮启动时装上",
                         _MAA_PENDING_DIR)
                break             # 下载落地了，剩下的交给 09:00 那次启动
            if _MAA_READY.search(text) and staged_before:
                answered = True
                log.info("预更新：MAA 的挂起更新已就绪，下轮启动时装上")
                break             # 本来就有暂存，装完即可，不必等新的
        else:
            log.warning("预更新：MAA 在 %.0f 秒内没给出更新结论，照常继续", budget_s)
            _note(problems,
                  f"MAA 预更新：{budget_s:.0f} 秒内没给出更新结论，"
                  "**本轮没有确认过是否有更新**")
    finally:
        _close(exe)
        if was:
            _maa_run_directly(Path(maa_dir), True)   # put it back as we found it
    if applied:
        return f"MAA {applied}"
    if answered and not staged_before and maa_update_pending(maa_dir):
        return "MAA 已下载新版，下轮启动时装上"
    return ""


# AUTO-MAS is the odd one of the three. It does not need to be launched to be
# asked - it is already running, and its FastAPI backend answers on localhost.
#
# It also cannot land an update mid-queue: its Run/IfAutoUpdateAfterQueue
# defaults to false and is not set on this machine, so the 4-hourly checker
# (frontend.log: "版本更新检查服务已启动（每4小时检查一次）") only ever reports.
# Unattended, it reports to a window nobody is looking at and the version never
# moves - which is the whole reason this exists.
#
# Applying it here is safe against the one interference that could plausibly
# break it: AUTO-MAS installs by launching AUTO-MAS-Setup.exe
# (app/services/update.py), which means the process exits - and service.py's
# _revive_automas would normally relaunch it. It does not, because
# INSTALLER_HINTS already vetoes revival while "auto-mas-setup" is in the
# task list. That gate was built for the manual installer; it covers this too.
_MAS_PORT = os.environ.get("ARK_MAS_PORT", "36163")
_MAS_HTTP_TIMEOUT = 20
# Boot is 08:40 and the queue checks in at 09:00. Downloading is harmless at any
# point - the package just sits there - but starting an install we cannot finish
# before the queue is not. If the download runs past this, leave the package for
# the next boot rather than opening a setup window in front of the run.
MAS_BUDGET_SECONDS = 600
# How long to wait for AUTO-MAS's backend to start listening.
MAS_WAIT_SECONDS = 180


def _automas_version(automas_dir: Path) -> str:
    """AUTO-MAS keeps its version in res/version.json - the same string its
    update check expects back."""
    try:
        data = json.loads(
            (Path(automas_dir) / "res" / "version.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _mas_post(path: str, body: dict | None = None) -> dict:
    import urllib.request  # noqa: PLC0415 - only this path needs it
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(  # noqa: S310 - fixed localhost URL
        f"http://127.0.0.1:{_MAS_PORT}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_MAS_HTTP_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", "replace"))


def _wait_for_package(automas_dir: Path, deadline: float) -> Path | None:
    """Wait for UpdatePack_*.zip to appear and stop growing.

    install_update() refuses with "未检测到更新包, 请先下载更新" if the package is
    not there, so calling install the moment download returns would simply fail.
    """
    stable_at = None
    last_size = -1
    while time.monotonic() < deadline:
        time.sleep(3)
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
                problems: list[str] | None = None) -> str:
    """Check, download and apply an AUTO-MAS update now. Returns a note or ""."""
    if not automas_dir:
        return ""
    root = Path(automas_dir)
    version = _automas_version(root)
    if not version:
        log.info("预更新：读不到 AUTO-MAS 版本号，跳过")
        _note(problems, "AUTO-MAS 预更新：读不到版本号，**没有检查更新**")
        return ""
    # AUTO-MAS starts at logon, and its backend is not listening the instant the
    # relay wakes: on 2026-08-24 the relay asked at 08:45:33 and AUTO-MAS's own
    # log shows its backend only came up at 08:46:09. Asking once at boot is
    # therefore guaranteed to miss it. Wait for the port instead - the boot
    # window runs to 09:00, so a couple of minutes costs nothing.
    answer = None
    wait_until = time.monotonic() + MAS_WAIT_SECONDS
    while True:
        try:
            # if_force 是必须的，不是保险起见。AUTO-MAS 的检查结果缓存四小时
            # （`app/services/update.py:178-184`），而 MirrorChyan 的下载地址是
            # **一次性令牌**，随检查响应带回来、存进 `mirror_chyan_download_url`。
            # 走缓存 = 拿一个早就过期的令牌去下载，三次重试全 404，更新包一个字节
            # 都不落地，然后我们在这儿干等 600 秒超时。
            # 2026-08-29 实测：不强制 → 404；强制 → 换到新令牌，状态码 200。
            # 这就是 AUTO-MAS 从 08-27 起反复「开始下载」却始终装不上的原因。
            answer = _mas_post("/api/update/check",
                               {"current_version": version, "if_force": True})
            break
        except Exception:  # noqa: BLE001 - not up yet, or genuinely unreachable
            if time.monotonic() >= wait_until:
                log.warning("预更新：等了 %.0f 秒仍问不到 AUTO-MAS 更新状态，跳过",
                            MAS_WAIT_SECONDS)
                _note(problems,
                      f"AUTO-MAS 预更新：等了 {MAS_WAIT_SECONDS:.0f} 秒仍问不到"
                      "更新状态，**没有检查更新**")
                return ""
            time.sleep(5)
    if not answer.get("if_need_update"):
        log.info("预更新：AUTO-MAS 已是 %s（无需更新）", version)
        return ""

    latest = answer.get("latest_version") or "新版本"
    log.info("预更新：AUTO-MAS 有更新 %s → %s，开始下载", version, latest)
    deadline = time.monotonic() + budget_s
    try:
        _mas_post("/api/update/download")
    except Exception:  # noqa: BLE001
        log.warning("预更新：AUTO-MAS 下载没能启动，本轮照旧", exc_info=True)
        _note(problems, f"AUTO-MAS 预更新：查到有 {latest}，但下载没能启动")
        return ""

    pack = _wait_for_package(root, deadline)
    if pack is None:
        # The package keeps whatever it downloaded; next boot picks it up.
        log.warning("预更新：AUTO-MAS 更新包 %.0f 秒内没下完，留到下次开机再装", budget_s)
        _note(problems,
              f"AUTO-MAS 预更新：{latest} 的更新包 {budget_s:.0f} 秒内没下完，"
              "留到下次开机再装")
        return ""

    log.info("预更新：更新包就绪（%s），开始安装", pack.name)
    try:
        _mas_post("/api/update/install")
    except Exception:  # noqa: BLE001
        log.warning("预更新：AUTO-MAS 安装没能启动，本轮照旧", exc_info=True)
        return ""
    return f"AUTO-MAS 已开始安装更新：{version} → {latest}"


# OK-WW (鸣潮) is the fourth program and updates unlike any of the other three:
# not MirrorChyan, not a delegated updater, but pyappify pulling from a CNB git
# mirror (`https://cnb.cool/ok-oldking/ok-ww-update2.git`, reachable from this
# machine in 0.3s where GitHub is not reachable at all). app.json carries
# "update_method": "AUTO_UPDATE", so it updates itself when launched.
#
# Two things make the launch delicate:
#   1. The update only happens through ok-ww.exe, the pyappify shell. Running
#      the bundled python directly - which is how tasks run headlessly - leaves
#      pyappify uninitialised and /api/updates answers
#      "pyappify_version: None".
#   2. ok-ww.exe honours "Auto Start Game When App Starts", which is on here.
#      Launching it at 08:45 would start 鸣潮 itself. Same shape of hazard as
#      MAA's RunDirectly and MaaEnd's autostart, and handled the same way.
_OKWW_BASIC = ("data", "apps", "ok-ww", "working", "configs", "Basic Options.json")
_OKWW_APPJSON = ("data", "apps", "ok-ww", "app.json")
_OKWW_AUTOSTART_KEY = "Auto Start Game When App Starts"
OKWW_BUDGET_SECONDS = 240


def _okww_quiesce() -> None:
    """Stop anything that would rewrite OK-WW's config from memory.

    Learned the hard way on 2026-08-24: a leftover `ok web` instance held the
    settings in memory and wrote them back, so flipping
    "Auto Start Game When App Starts" in the JSON had no effect - ok-ww.exe read
    the restored True and launched 鸣潮 during what was supposed to be a
    windowless update check. Same shape as MAA's master-copy problem: editing a
    file that a running process owns is editing a copy.
    """
    for name in ("ok-ww.exe", "Wuthering Waves.exe",
                 "Client-Win64-Shipping.exe", "KRSDKExternal.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],  # noqa: S603, S607
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    # The headless task/web runners are plain python; match them by command line.
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*ok-ww*' -or "
          "$_.CommandLine -like '*-m ok *' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],  # noqa: S603, S607
                       capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
    time.sleep(2)


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
        tmp = cfg.with_suffix(cfg.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
        tmp.replace(cfg)
    except OSError:
        log.warning("预更新：写不回 OK-WW 的 Basic Options，跳过 OK-WW", exc_info=True)
        return None
    return was


def _okww_state(okww_dir: Path) -> tuple[str, str, str, tuple[str, ...]]:
    """(current_version, update_state, update_error, available_versions).

    `available_versions` is the point of the fourth field: it is how we tell
    "checked, nothing newer" apart from "never checked at all". On 2026-08-25
    the pre-update reported 无需更新 while that list still topped out at the
    installed version and the CNB mirror already carried the next one - the
    list had simply never been refreshed.
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
    """app.json 的修改时间。0 表示读不到。

    2026-08-26：判据原本只看 `available_versions` 有没有变。可 OK-WW 本来就是
    最新版时，它**查过之后列表内容一模一样**——于是「查过了」和「压根没查」
    在中继眼里长得一样，只能报「没有任何检查迹象」。
    实测那次 app.json 的 mtime 明明前进了（12:36:53，正是启动它的那几分钟），
    **文件被写过就是它跑过的直接证据**，比比对内容可靠。
    """
    try:
        return Path(okww_dir).joinpath(*_OKWW_APPJSON).stat().st_mtime
    except OSError:
        return 0.0


def run_okww(okww_dir: Path | None,
             budget_s: float = OKWW_BUDGET_SECONDS,
             problems: list[str] | None = None) -> str:
    """Let OK-WW apply any pending update now, without starting the game.

    Appends to `problems` whenever the check could not be *proven* to have
    happened. Silence used to be reported as success; see `_spawn_interactive`
    for the morning that cost us a release.
    """
    if not okww_dir:
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
    was = _okww_autostart(root, False)
    if was is None:
        _note(problems, "OK-WW 预更新：改不动 app.json，没有检查更新")
        return ""
    try:
        # session 0 has no desktop, and OK-WW's updater simply does not run
        # there - it returns a stale version file that reads as "no update".
        if not _spawn_interactive(exe, root, require_console=True):
            log.warning("预更新：OK-WW 没能在控制台会话启动，本轮没有检查更新")
            _note(problems, "OK-WW 预更新：拿不到控制台会话，**没有检查更新**"
                            "（不是「无需更新」）")
            return ""
        log.info("预更新：已启动 OK-WW（已临时关掉自动开游戏），最多 %.0f 秒", budget_s)
        deadline = time.monotonic() + budget_s
        settled = ""
        checked = False           # 见到过它真的动了：状态变化 / 版本列表刷新 / 版本变化
        failed = ""
        while time.monotonic() < deadline:
            time.sleep(3)
            version, state, err, avail = _okww_state(root)
            if err:
                log.warning("预更新：OK-WW 更新报错 %s", err[:200])
                failed = err[:200]
                break
            if avail and avail != before_avail:
                checked = True    # 版本列表刷新过 = 确实向上游问过
            if before_stamp and _okww_stamp(root) > before_stamp:
                # 本来就是最新版时列表内容不会变，但文件照样会被重写。
                # 这一条才是「它确实跑起来查过了」的直接证据。
                checked = True
            if state and state not in ("idle", ""):
                checked = True
                continue          # 正在下载/安装，继续等
            if version and version != before_version:
                settled, checked = version, True
                break
            if checked and state == "idle":
                break             # 问过了，而且已经安顿下来
        if failed:
            _note(problems, f"OK-WW 预更新：更新报错 {failed}")
        elif settled:
            log.info("预更新：OK-WW 已更新 %s → %s", before_version, settled)
        elif not checked:
            # 这正是 2026-08-25 的漏网：安静 ≠ 没有更新。
            log.warning("预更新：OK-WW %.0f 秒内没有任何检查迹象（版本列表没刷新）",
                        budget_s)
            _note(problems,
                  f"OK-WW 预更新：{budget_s:.0f} 秒内没有任何检查迹象，"
                  f"**无法确认是否检查过更新**（当前 {before_version or '版本未知'}）")
        else:
            newest = before_avail[0] if before_avail else ""
            log.info("预更新：OK-WW 无需更新（%s）", before_version or "版本未知")
            if newest and newest != before_version:
                _note(problems,
                      f"OK-WW 预更新：查到有 {newest}，但没装上"
                      f"（仍是 {before_version or '版本未知'}）")
        # Close OK-WW *and* anything it may have pulled up with it. A
        # pre-update that leaves 鸣潮 running has not left the machine alone.
        _close(exe)
        _okww_quiesce()
        return f"OK-WW 已更新：{before_version} → {settled}" if settled else ""
    finally:
        _okww_autostart(root, was)


def wanted_today(automas_dir: Path | None, now: datetime | None = None) -> bool:
    """True when a queue still to come today runs MaaEnd.

    The evening queue is MAA only, so warming up before it would start a
    program nothing is going to use. Read from AUTO-MAS's own schedule, so a
    queue changed there changes this too.
    """
    from . import plan  # noqa: PLC0415 - avoids an import cycle

    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    cfg_dir = Path(automas_dir) / "config" if automas_dir else None
    if not cfg_dir or not cfg_dir.is_dir():
        return False
    scripts = plan._scripts(cfg_dir)  # noqa: SLF001 - same package
    for q in plan.schedule(automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due < now:
                continue        # already past; warming up helps nothing
            if any((scripts.get(uid) or {}).get("kind") == "MaaEnd"
                   for uid in q.get("items", [])):
                return True
    return False
