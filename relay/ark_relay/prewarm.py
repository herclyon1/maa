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

Failure here is deliberately cheap: if the warm-up cannot run, does not
finish, or the network is slow, the round proceeds exactly as it does today -
one wasted attempt, then the retry succeeds.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ

log = logging.getLogger("ark.prewarm")

# How long to let MaaEnd sort itself out. An update measured 17 seconds from
# launch to the restarted process, plus download time on a line that is slow to
# reach GitHub. The boot-to-queue gap is 13 minutes in the morning and 8 in the
# evening, so three minutes is affordable; overrunning it costs nothing but a
# round that behaves the way it does today.
BUDGET_SECONDS = 180
# The line MaaEnd writes once its update check has settled.
_DONE = re.compile(r"更新检查完成: 最新版本=(\S+?), 有更新=(true|false)")
_UPDATED = re.compile(r"检测到刚更新完成: (\S+)")


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


def run(maaend_dir: Path | None, budget_s: float = BUDGET_SECONDS) -> str:
    """Launch MaaEnd, wait for its update check, close it. Returns a note or "".

    The note is non-empty only when an update actually landed - that is the
    thing worth telling the operator about, and it is the operator's standing
    rule that an update which takes effect gets announced.
    """
    if not maaend_dir:
        return ""
    exe = Path(maaend_dir) / "MaaEnd.exe"
    if not exe.exists():
        log.warning("预热跳过：找不到 %s", exe)
        return ""

    before = _newest_log(Path(maaend_dir))
    before_name = before.name if before else ""
    deadline = time.monotonic() + budget_s
    try:
        # Detached: this must not become a child whose lifetime is tied to the
        # service, and it must not inherit the service's window station in a
        # way that keeps a handle open after we kill it.
        subprocess.Popen(  # noqa: S603
            [str(exe)], cwd=str(maaend_dir),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                           | subprocess.DETACHED_PROCESS))
    except OSError:
        log.warning("预热启动 MaaEnd 失败，本轮照旧", exc_info=True)
        return ""
    log.info("预热：已启动 MaaEnd，等它把更新做完（最多 %.0f 秒）", budget_s)

    updated_to = ""
    settled = False
    while time.monotonic() < deadline:
        time.sleep(3)
        current = _newest_log(Path(maaend_dir))
        if current is None or current.name == before_name:
            continue        # this launch has not opened its log yet
        text = _read(current)
        if m := _UPDATED.search(text):
            updated_to = m.group(1)
        if m := _DONE.search(text):
            version, has_update = m.group(1), m.group(2)
            # "有更新=true" means it is still downloading; keep waiting for the
            # restarted process to report false.
            if has_update == "false":
                settled = True
                log.info("预热：MaaEnd 已是 %s%s", version,
                         f"（本次更新自 → {updated_to}）" if updated_to else "（无需更新）")
                break
    if not settled:
        log.warning("预热：%.0f 秒内没等到更新检查结束，本轮照旧", budget_s)

    _close(exe)
    if updated_to and settled:
        return updated_to
    return ""


def _close(exe: Path) -> None:
    """Leave nothing running. AUTO-MAS kills it before每轮 anyway, but a warm-up
    that leaves a window on the desktop is a warm-up that changed the thing it
    was supposed to leave alone."""
    try:
        subprocess.run(  # noqa: S603
            ["taskkill", "/IM", exe.name, "/F"],
            capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("预热：关闭 MaaEnd 失败", exc_info=True)


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
