"""preupdate_maa: split out of preupdate.py (2026-09-08, moved verbatim)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .config import atomic_write_text

from .preupdate_common import BUDGET_SECONDS, _note, _read_from, _spawn_interactive, log
from .preupdate_maaend import _close, _span



# MAA applies a pending update at startup, in its Bootstrapper, before the app
# is usable - "Delegated pending update completed successfully" in gui.log. That
# is a gentler mechanism than MaaEnd's (which restarts its own process mid-run),
# and it has not been caught breaking a queue here. Moving it into the boot
# window anyway costs a few seconds and removes the possibility.
_MAA_LATEST = re.compile(r'"msg"\s*:\s*"current version is latest"')
# **The first startup right after MAA updated skips the update check**, so the
# "latest" line never arrives. Measured 2026-09-05: 08:46:07 started v6.17.1
# (upgraded from 6.17.0 the day before) and the log had
# `IsFirstBoot has been set: \`true\` -> \`false\`` with **not a single
# mirrorchyan request** in the whole span; the relay waited out all 180 seconds
# and then raised a false "could not confirm" alert. On the same day, the
# 09:00:50 startup already had IsFirstBoot false and asked normally at 09:00:56.
# Recognising this line means we stop waiting -- **this is not a fault**, and no
# update is missed either: the 09:00 queue's own startup performs the check.
_MAA_FIRST_BOOT = re.compile(r"IsFirstBoot has been set: `true` -> `false`")
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


_MAA_PENDING_VER = re.compile(r"MirrorChyanApp(v[\w.\-+]+)\.zip$", re.IGNORECASE)


def _maa_pending_version(maa_dir: Path | None) -> str:
    """Which version the downloaded, not-yet-installed package is -- read from
    the MirrorChyan file name. Empty string when it cannot be read.
    """
    if not maa_dir:
        return ""
    try:
        for p in Path(maa_dir).glob(_MAA_PENDING_GLOB):
            if m := _MAA_PENDING_VER.search(p.name):
                return m.group(1)
    except OSError:
        pass
    return ""


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
    """The version MAA reports for itself in gui.log
    (`Bootstrapper ... Version v6.17.0-beta.6`).

    Returns an empty string when it cannot be read -- this only makes the log
    more specific, and is not worth failing the pre-update over.
    """
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-200_000:]
    except OSError:
        return ""
    hits = _MAA_VERSION.findall(tail)
    return hits[-1] if hits else ""


def _maa_await_verdict(log_path: Path, before_len: int, maa_dir: Path | None,
                       staged_before: bool, budget_s: float,
                       problems: list[str] | None) -> tuple[str, bool]:
    """Watch gui.log until MAA has settled the update question. Returns
    (description of what was applied, whether there was a verdict at all).

    This is its own step because MAA settles the question in four different
    ways -- it just updated so it skipped the check itself; it says outright it
    is up to date; it landed the download of a new build; something was already
    staged and is now ready -- and each one needs its own written reason for
    why we may stop here. With all four sets of criteria wedged between the
    launch and the cleanup, run_maa's spine (open -> wait -> close) becomes
    unreadable. The "no verdict" problem is also recorded for the caller here.
    """
    applied = ""
    answered = False
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        time.sleep(1)
        text = _read_from(log_path, before_len)
        if _MAA_APPLIED.search(text):
            applied = "已应用挂起的更新"
        if _MAA_FIRST_BOOT.search(text):
            answered = True
            log.info("预更新：MAA 刚更新过，这次是首次启动，它自己跳过了更新检查；"
                     "09:00 队列启动时会补上")
            break             # "latest" will never come; waiting only burns the full 180 seconds
        if _MAA_LATEST.search(text):
            answered = True
            # Do not drop this line: the other three programs each log a line
            # when they are already up to date. Only MAA used to be silent, so
            # the log did not show whether it had checked at all.
            log.info("预更新：MAA 已是 %s（无需更新）", _maa_version(log_path) or "最新版")
            break             # It said outright it is up to date; no download to wait for
        if not staged_before and maa_update_pending(maa_dir):
            answered = True
            log.info("预更新：MAA 已把新版下载到 %s，下轮启动时装上",
                     _MAA_PENDING_DIR)
            break             # The download landed; the 09:00 startup handles the rest
        if _MAA_READY.search(text) and staged_before:
            answered = True
            log.info("预更新：MAA 的挂起更新已就绪，下轮启动时装上")
            break             # Something was already staged; installing it is enough, no need to wait for more
    else:
        log.warning("预更新：MAA 在 %.0f 秒内没给出更新结论，照常继续", budget_s)
        _note(problems,
              f"MAA 预更新：{budget_s:.0f} 秒内没给出更新结论，"
              "**本轮没有确认过是否有更新**")
    return applied, answered


def _maa_summary(maa_dir: Path | None, log_path: Path, before_ver: str,
                 applied: str, answered: bool, staged_before: bool) -> str:
    """Turn the verdict into one human-readable line; empty string when there
    is nothing to report.

    This is its own step because it runs **after** the finally block has closed
    MAA: only the restart that follows the install writes the new version at
    the end of gui.log, and reading a step earlier still gets the old one.
    Pulled out here, nobody casually moves it back inside the try.
    """
    if applied:
        # MAA restarts after installing, so the last Version line in gui.log is the new one
        return f"MAA 已更新：{_span(before_ver, _maa_version(log_path) or '新版本')}"
    if answered and not staged_before and maa_update_pending(maa_dir):
        target = _maa_pending_version(maa_dir) or "新版本"
        return f"MAA 有更新：{_span(before_ver, target)}（已下载，下轮启动时装上）"
    return ""


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
    before_ver = _maa_version(log_path)
    was = _maa_run_directly(Path(maa_dir), False)
    if was is None:
        _note(problems, "MAA 预更新：改不动配置，没有检查更新")
        return ""
    before_len = log_path.stat().st_size if log_path.exists() else 0
    try:
        # session 0 has no desktop; MAA's updater does not run there.
        if not _spawn_interactive(exe, maa_dir, require_console=True, minimized=True):
            log.warning("预更新：MAA 没能在控制台会话启动，本轮没有检查更新")
            _note(problems, "MAA 预更新：拿不到控制台会话，**没有检查更新**")
            return ""
        log.info("预更新：已启动 MAA（已临时关闭「启动后直接运行」），最多 %.0f 秒", budget_s)
        applied, answered = _maa_await_verdict(
            log_path, before_len, maa_dir, staged_before, budget_s, problems)
    finally:
        _close(exe)
        if was:
            _maa_run_directly(Path(maa_dir), True)   # put it back as we found it
    return _maa_summary(maa_dir, log_path, before_ver, applied, answered,
                        staged_before)
