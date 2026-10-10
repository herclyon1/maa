"""OK-WW (Wuthering Waves) pre-update, and closing OK-WW, the game and the Kuro
launcher."""
from __future__ import annotations

import json
from ark_relay.core.config import atomic_write_text
import subprocess
import time
from pathlib import Path


from ark_relay.features.preupdate.preupdate_common import _note, _pwsh, _span, _spawn_interactive, log
from ark_relay.features.preupdate.preupdate_maaend import _close


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


def _okww_quiesce(sleep=time.sleep, launcher_root: Path | None = None) -> None:
    """Stop OK-WW, the game and the Kuro launcher, so nothing rewrites OK-WW's
    config from memory.

    A running OK-WW (ok-ww.exe or an `ok` python process) writes its settings
    back from memory, so an edit to its JSON made while it runs is lost.
    The OK-WW python processes (python.exe and pythonw.exe) are stopped before
    the game, because OK-WW restarts the game when it is killed first.
    `launcher_root` is the Kuro launcher's folder (see _stop_wuwa_launcher).
    taskkill runs from the service's session and its result is not checked; a
    caller that must know the machine is clean uses _okww_close.
    """
    ps = ("Get-CimInstance Win32_Process -Filter "
          "\"Name='python.exe' OR Name='pythonw.exe'\" | "
          "Where-Object { $_.CommandLine -like '*ok-ww*' -or "
          "$_.CommandLine -like '*-m ok *' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run([_pwsh(), "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ("ok-ww.exe", "Wuthering Waves.exe",
                 "Client-Win64-Shipping.exe", "KRSDKExternal.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    _stop_wuwa_launcher(launcher_root)
    # Two seconds for the processes to exit. `sleep` is injectable for tests.
    sleep(2)


def _okww_close(sleep=time.sleep, launcher_root: Path | None = None) -> list[str]:
    """_okww_quiesce, then look again: what is still up afterwards ([] = clean).

    taskkill from session 0 does not reach the game under its anti-cheat, so
    whatever survives is killed again from the desktop session
    (echofarm._kill_on_desktop) and checked for up to 10 s.
    """
    from ark_relay.features.echofarm.echofarm import _kill_on_desktop  # noqa: PLC0415 - echofarm imports this module
    _okww_quiesce(sleep=sleep, launcher_root=launcher_root)
    left, pids = _okww_left(launcher_root)
    if not left:
        return []
    log.warning("鸣潮：关完还在 %s，从桌面会话再关一次", "、".join(left))
    _kill_on_desktop(pids=pids)
    for _ in range(10):
        sleep(1)
        left, _pids = _okww_left(launcher_root)
        if not left:
            return []
    return left


def _okww_left(launcher_root: Path | None = None) -> tuple[list[str], list[int]]:
    """(names still up, launcher PIDs still up): the game's processes plus the Kuro
    launcher at its path. An unreadable launcher list is named, not taken as gone."""
    from ark_relay.features.echofarm.echofarm import game_alive  # noqa: PLC0415 - echofarm imports this module
    left = list(game_alive())
    procs = _wuwa_launcher_procs(launcher_root)
    if procs is None:
        left.append("鸣潮启动器（查不到它还开没开着）")
        return left, []
    left += [Path(path.replace("\\", "/")).name for _pid, path in procs]
    return left, [pid for pid, _path in procs]


# The Kuro launcher (gameupdate_games.wuwa_launcher): launcher.exe is the entry
# shell; while it runs the process is <launcher dir>\<version>\launcher_main.exe.
# Both names are common, so only processes under the launcher's own folder are
# stopped.
_WW_LAUNCHER_EXES = ("launcher.exe", "launcher_main.exe")
# Used when the launcher's folder cannot be worked out. A path segment, so the game
# body's folder (…\Wuthering Waves Game\…) does not match.
_WW_LAUNCHER_SEGMENT = "\\wuthering waves\\"


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


def _launcher_root(root: Path | None) -> Path | None:
    """The launcher's folder: the one given, else the one
    gameupdate_games.wuwa_launcher finds from OK-WW's config (the same lookup
    update_wuwa starts the launcher from). None when that is not a launcher.exe."""
    if root:
        return root
    from ark_relay.core.config import _env_path  # noqa: PLC0415
    from ark_relay.features.gameupdate.gameupdate_games import wuwa_launcher  # noqa: PLC0415 - it imports this module
    try:
        exe = wuwa_launcher(_env_path("ARK_OKWW_DIR"))
    except OSError:
        return None
    return exe.parent if exe and exe.name.lower() == "launcher.exe" else None


def _wuwa_launcher_procs(root: Path | None = None) -> list[tuple[int, str]] | None:
    """(PID, path) of the running Kuro launcher processes; None when the process
    list could not be read."""
    root = _launcher_root(root)
    ps = ("Get-CimInstance Win32_Process -Filter "
          "\"Name='launcher.exe' OR Name='launcher_main.exe'\" | "
          "Select-Object ProcessId, ExecutablePath | ConvertTo-Json -Compress")
    try:
        r = subprocess.run([_pwsh(), "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=60)
        data = json.loads((r.stdout or b"").decode("utf-8", "replace").strip() or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
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


def _stop_wuwa_launcher(root: Path | None = None) -> list[int]:
    """Stop the Kuro launcher processes, matched on their full executable path.

    Returns the PIDs taskkill confirmed (return code 0); one it could not stop
    is logged and left out (_okww_close tries again from the desktop).
    """
    stopped = []
    for pid, path in _wuwa_launcher_procs(root) or []:
        try:
            r = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
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
                       clock=time.monotonic) -> tuple[str, bool, str, str]:
    """Watch app.json until OK-WW is done: returns (new version, did it check, error,
    the state it was still in when the budget ran out - "" unless it timed out busy).

    "Did it check" is true when the version list changed, app.json was
    rewritten, the update state left idle, or the version changed. A
    "checked, settled" verdict also needs OKWW_MIN_WAIT_SECONDS since launch.
    """
    deadline = clock() + budget_s
    launched = clock()
    settled = ""
    checked = False           # saw it actually move: state / version list / version
    failed = ""
    state = ""
    while clock() < deadline:
        sleep(3)
        version, state, err, avail = _okww_state(root)
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
            return settled, checked, failed, state
    return settled, checked, failed, ""


def _okww_report(problems: list[str] | None, budget_s: float,
                 before_version: str, before_avail: tuple[str, ...],
                 settled: str, checked: bool, failed: str, stuck: str = "",
                 shot: "Path | None" = None) -> None:
    """Log the result of _okww_await_update and note a problem where one is due.

    Branches: update error; updated; out of time while busy; no sign of a check
    (not the same as "no update"); checked with nothing newer installed (noted
    when available_versions lists a newer one).
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
        newest = before_avail[0] if before_avail else ""
        log.info("预更新：OK-WW 无需更新（%s）", before_version or "版本未知")
        if newest and newest != before_version:
            _note(problems,
                  f"OK-WW 预更新：查到有 {newest}，但没装上"
                  f"（仍是 {before_version or '版本未知'}）")


def _okww_timeout_shot(take=None) -> "Path | None":
    """A picture of the desktop when the update ran out of time mid-download, saved
    under the relay's state folder. None when it could not be taken (a Mac, a test,
    no interactive session). `take(out) -> bool` is for tests."""
    from ark_relay.core.config import _env_path  # noqa: PLC0415
    if take is None:
        from ark_relay.features.alarm.handle import _screenshot_to as take  # noqa: PLC0415 - Windows-only, heavy import
    try:
        out = _env_path("ARK_STATE_DIR", "./ark-state") / "preupdate" / \
            f"okww-timeout-{time.strftime('%Y%m%d-%H%M%S')}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        return out if take(out) else None
    except Exception:  # noqa: BLE001 - a missing picture must not cost the verdict
        log.warning("预更新：OK-WW 超时截图没拿到", exc_info=True)
        return None


def run_okww(okww_dir: Path | None,
             budget_s: float = OKWW_BUDGET_SECONDS,
             problems: list[str] | None = None) -> str:
    """Let OK-WW apply any pending update now, without starting the game.

    Appends to `problems` whenever the check could not be shown to have
    happened. Returns 「OK-WW 已更新：旧 → 新」 or "".
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
    # ok-ww.exe has no launch argument that keeps it from starting the game, so
    # the auto-start switch is turned off for this launch and restored in the
    # `finally` below.
    was = _okww_autostart(root, False)
    if was is None:
        _note(problems, "OK-WW 预更新：改不动 app.json，没有检查更新")
        return ""
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
        settled, checked, failed, stuck = _okww_await_update(
            root, budget_s, before_version, before_avail, before_stamp)
        _okww_report(problems, budget_s, before_version, before_avail,
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
        try:
            if launched:
                _close(exe)
                _okww_quiesce()
        finally:
            back = _okww_autostart(root, was)   # put it back as we found it
            if back is None:
                log.warning("预更新：OK-WW 的「启动时自动开游戏」没能改回原来的（%s），"
                            "需要人工看一眼 OK-WW 的基本设置", "开" if was else "关")
