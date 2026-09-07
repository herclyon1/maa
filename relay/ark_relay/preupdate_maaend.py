"""preupdate_maaend：从 preupdate.py 拆出（2026-09-08，只搬不改）。"""
from __future__ import annotations

import json
from .config import atomic_write_text
import subprocess
import time
from pathlib import Path


from .preupdate_common import BUDGET_SECONDS, _CURRENT, _DONE, _UPDATED, _newest_log, _note, _read, _spawn_interactive, log



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
        atomic_write_text(cfg, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        log.warning("预更新：写不回 MaaEnd 的 settings，跳过 MaaEnd", exc_info=True)
        return None
    return was


def run(maaend_dir: Path | None, budget_s: float = BUDGET_SECONDS,
        problems: list[str] | None = None, state_dir: Path | None = None) -> str:
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
        return _run_maaend(Path(maaend_dir), exe, budget_s, problems, state_dir)
    finally:
        _maaend_autostart_instance(Path(maaend_dir), was_instance)


def _maaend_version_in(log_file: Path | None) -> str:
    """某个 MaaEnd 日志里最后一次自报的版本号；读不到返回空串。"""
    if not log_file:
        return ""
    hits = _CURRENT.findall(_read(log_file))
    return hits[-1] if hits else ""


def _span(old: str, new: str) -> str:
    """「旧版 → 新版」——四个程序的更新通知统一用这一种写法。

    旧版号没拿到就明说「旧版本没读到」，不编也不省：2026-08-30 MaaEnd
    的通知只有「已更新：v2.27.0-beta.1」，看不出从哪升上来的，用户
    2026-09-01 要求四个程序样式统一、都带「老版本号 → 新版本号」。
    """
    if old and old != new:
        return f"{old} → {new}"
    # 旧版等于新版不是「没更新」，是旧版号读错了——更新后的进程自报的
    # 「当前版本」就是新版号。2026-09-06、09-07 两天的 MaaEnd 通知都只有
    # 一个版本号，就是这条分支把它当成「同版只报一次」吞掉的。
    return f"（旧版本没读到）→ {new}"


_maaend_span = _span      # 旧名字，测试和别处还在用

_VERSION_FILE = "maaend-version.txt"   # 中继自己记的、上一次确认过的 MaaEnd 版本


def _pick_old(candidates, new: str) -> str:
    """旧版本号：按可信度顺序取第一个非空、且**不等于新版本**的。

    等于新版本的一律不算——那是更新之后读到的。四个来源见 _run_maaend。
    """
    for c in candidates:
        if c and c != new:
            return c
    return ""


def _remembered_version(state_dir) -> str:
    """中继上一次预更新确认过的 MaaEnd 版本。没有就空串。

    MaaEnd 装更新会把自己的 debug 目录连旧日志一起换掉（2026-09-07 实测：
    更新后目录里只剩新进程那一份日志），interface.json 也已经是新的。
    那时只有中继自己记的这一份还知道昨天是什么版本。记在 state.json 的 versions 段。
    """
    if not state_dir:
        return ""
    from .statestore import StateStore  # noqa: PLC0415
    return str(StateStore(state_dir).get("versions", "maaend") or "")


def _remember_version(state_dir, ver: str) -> None:
    if not state_dir or not ver:
        return
    from .statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(state_dir).set("versions", "maaend", ver)
    except OSError:
        log.warning("预更新：MaaEnd 版本号记不下来，下次更新通知可能缺旧版号", exc_info=True)


def _maaend_file_version(maaend_dir: Path) -> str:
    """MaaEnd 自己的 interface.json 里的 version——不依赖日志时机。

    2026-08-30 08:46:23 启动、08:46:33 就「刚更新完成」：更新包是前一天
    跑队列时下载好的，启动即装、装完重启，旧版本那行日志根本没机会被
    读到。文件里的版本号在启动**之前**读，就没有这个时机问题。
    """
    try:
        data = json.loads((Path(maaend_dir) / "interface.json")
                          .read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def _run_maaend(maaend_dir: Path, exe: Path, budget_s: float,
                problems: list[str] | None = None,
                state_dir: Path | None = None) -> str:
    """The body of run(), with auto-run already disarmed by the caller."""
    before = _newest_log(maaend_dir)
    before_name = before.name if before else ""
    deadline = time.monotonic() + budget_s
    # In the console session, not session 0 - see _spawn_interactive.
    if not _spawn_interactive(exe, maaend_dir, _MAAEND_AUTOSTART, minimized=True):
        return ""
    log.info("预更新：已启动 MaaEnd（--autostart，已清空自动执行实例），最多 %.0f 秒",
             budget_s)

    updated_to = ""
    # 升级前的版本号，四个来源，按可信度排：
    #   launch_ver  本次启动、装更新**之前**那个进程自报的「当前版本」
    #   file_ver    启动前读的 interface.json
    #   prev_ver    上一次启动的日志
    #   kept_ver    中继上次预更新记下的版本（MaaEnd 更新会把旧日志清掉）
    # 最后由 _pick_old 取第一个不等于新版本的。**更新后的进程也会写一行
    # 「当前版本」，写的是新版号**——2026-09-06/07 两天就是被它覆盖了旧版号。
    launch_ver = ""
    file_ver = _maaend_file_version(maaend_dir)
    prev_ver = _maaend_version_in(before)
    kept_ver = _remembered_version(state_dir)

    def old_for(new: str) -> str:
        return _pick_old((launch_ver, file_ver, prev_ver, kept_ver), new)

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
        if (m2 := _CURRENT.search(text)) and not _UPDATED.search(text):
            # 装完更新重启后的进程也写「当前版本」，但那已经是新版号，
            # 只有同一份日志里没有「刚更新完成」时它才是旧版号。
            launch_ver = m2.group(1)
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
                     _maaend_span(old_for(updated_to), updated_to))
            break
        if m := _DONE.search(text):
            version, has_update = m.group(1), m.group(2)
            # "有更新=true" means it is still downloading; keep waiting for the
            # restarted process to report false.
            if has_update == "false":
                settled = True
                _remember_version(state_dir, version)
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
        _remember_version(state_dir, updated_to)
        return _maaend_span(old_for(updated_to), updated_to)
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
