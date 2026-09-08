"""preupdate_maaend: split out of preupdate.py (2026-09-08, moved verbatim)."""
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
        problems: list[str] | None = None, state_dir: Path | None = None,
        sleep=time.sleep) -> str:
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
        return _run_maaend(Path(maaend_dir), exe, budget_s, problems, state_dir,
                           sleep=sleep)
    finally:
        _maaend_autostart_instance(Path(maaend_dir), was_instance)


def _maaend_version_in(log_file: Path | None) -> str:
    """The last version MaaEnd reported about itself in a given log; "" if unreadable."""
    if not log_file:
        return ""
    hits = _CURRENT.findall(_read(log_file))
    return hits[-1] if hits else ""


def _span(old: str, new: str) -> str:
    """「旧版 → 新版」 - the one shape all four programs' update notices use.

    When the old version could not be read, say so outright with 「旧版本没读到」:
    do not invent it and do not drop it. On 2026-08-30 the MaaEnd notice read only
    「已更新：v2.27.0-beta.1」, with no way to tell what it came from; the user, on
    2026-09-01, asked for one consistent shape across all four programs, each
    carrying 「老版本号 → 新版本号」.
    """
    if old and old != new:
        return f"{old} → {new}"
    # Old == new does not mean "no update", it means the old version was read
    # wrong - the post-update process reports the new version as its
    # 「当前版本」. On 2026-09-06 and 09-07 the MaaEnd notices carried only one
    # version number, because this branch swallowed it as "same version, report
    # once".
    return f"（旧版本没读到）→ {new}"


_maaend_span = _span      # old name, still used by the tests and elsewhere

_VERSION_FILE = "maaend-version.txt"   # the last MaaEnd version the relay itself confirmed


def _pick_old(candidates, new: str) -> str:
    """Old version: the first candidate, in order of trustworthiness, that is
    non-empty and **not equal to the new version**.

    Anything equal to the new version is discarded - that reading was taken after
    the update. The four sources are listed in _run_maaend.
    """
    for c in candidates:
        if c and c != new:
            return c
    return ""


def _remembered_version(state_dir) -> str:
    """The MaaEnd version the relay confirmed during its previous pre-update. "" if none.

    Installing a MaaEnd update replaces its debug directory, old logs included
    (measured 2026-09-07: after the update the directory held only the new
    process's log), and interface.json is already the new one by then. At that
    point this record the relay keeps for itself is the only thing that still
    knows yesterday's version. Stored in the `versions` section of state.json.
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
    """The `version` in MaaEnd's own interface.json - independent of log timing.

    2026-08-30: launched 08:46:23 and already 「刚更新完成」 by 08:46:33. The update
    package had been downloaded during the previous day's queue run, so it
    installed on launch and restarted immediately, and the old-version log line
    never had a chance to be read. Reading the version out of the file **before**
    launch has no such timing problem.
    """
    try:
        data = json.loads((Path(maaend_dir) / "interface.json")
                          .read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def _run_maaend(maaend_dir: Path, exe: Path, budget_s: float,
                problems: list[str] | None = None,
                state_dir: Path | None = None, sleep=time.sleep) -> str:
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
    # The pre-upgrade version, four sources, ordered by trustworthiness:
    #   launch_ver  the 「当前版本」 self-reported by this launch's process
    #               **before** the update was installed
    #   file_ver    interface.json, read before launch
    #   prev_ver    the previous launch's log
    #   kept_ver    the version the relay recorded during its last pre-update
    #               (a MaaEnd update wipes the old logs)
    # _pick_old then takes the first one that differs from the new version.
    # **The post-update process also writes a 「当前版本」 line, carrying the new
    # version** - that is what overwrote the old version on 2026-09-06/07.
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
        # `sleep` 可注入是为了测试。2026-09-08 量到 test_preupdate_maaend_oldver
        # 有 6 秒是**纯等**（CPU 1%）——部署每次都跑这套测试，空等就是部署时间。
        sleep(1)
        current = _newest_log(Path(maaend_dir))
        if current is None or current.name == before_name:
            continue        # this launch has not opened its log yet
        text = _read(current)
        if (m2 := _CURRENT.search(text)) and not _UPDATED.search(text):
            # The process restarted after installing an update writes
            # 「当前版本」 too, but by then it is the new version; it is the old
            # version only when the same log has no 「刚更新完成」 in it.
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
    """Leave nothing running. AUTO-MAS kills it before every round anyway, but a pre-update
    that leaves a window on the desktop is a pre-update that changed the thing it
    was supposed to leave alone."""
    try:
        subprocess.run(
            ["taskkill", "/IM", exe.name, "/F"],
            capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("预更新：关闭 MaaEnd 失败", exc_info=True)
