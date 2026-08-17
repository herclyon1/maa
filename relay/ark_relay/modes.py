"""调试模式与跳过模式 - the operator's two levers over what should NOT happen.

调试模式  The machine is being worked on: boot it, farm nothing, and above
          all do not power it off. One file carries the whole state - a date
          up to which the mode holds - so it survives restarts, applies
          identically in local and service mode, and expires on its own
          instead of relying on anyone remembering to turn it off. While it
          holds, the engine will not power the machine off (the idle
          checkpoint included) and will not raise missed-run alarms.

跳过模式  One queue sits out one occasion. skip_today used to write a flag
          that nothing ever read; now the first tick that sees the flag
          disables that queue inside AUTO-MAS, and a restore marker re-enables
          it once the occasion is over - so a skip can never quietly become a
          permanent stop. The queue's own times are captured into the marker
          at disable time, because a disabled queue disappears from
          plan.schedule and can no longer answer "when was I due".
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ

log = logging.getLogger("ark.modes")

# How long past the skipped queue's last time of day the restore may happen.
# Generous on purpose: restoring while the occasion is arguably still in
# progress would defeat the skip.
RESTORE_GRACE_MIN = 30


def _debug_file(state_dir: Path) -> Path:
    return Path(state_dir) / "debug-until.txt"


def debug_until(state_dir: Path) -> str:
    """The date debug mode holds through, '' when off."""
    try:
        return _debug_file(state_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def debug_active(state_dir: Path, now: datetime | None = None) -> bool:
    until = debug_until(state_dir)
    if not until:
        return False
    today = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    # A malformed date must fail towards "debug on": the operator explicitly
    # asked for the machine to be left alone, and the wrong failure here powers
    # off a box someone is working on.
    return today <= until or len(until) != 10


def set_debug(state_dir: Path, days: int = 1, off: bool = False) -> tuple[bool, str]:
    """days=1 means today only; the mode expires by itself after the date."""
    path = _debug_file(state_dir)
    if off:
        path.unlink(missing_ok=True)
        return True, "调试模式已关闭，恢复正常运行（队列若被停用需另行恢复）"
    try:
        days = max(1, int(days))
    except (TypeError, ValueError):
        return False, f"天数不是整数: {days!r}"
    until = (datetime.now(tz=SERVER_TZ) + timedelta(days=days - 1)).strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(until, encoding="utf-8")
    return True, (f"🔧 调试模式已开启，至 {until}（含当天）：不关机、不报漏跑。"
                  "注意：要让机器什么都不刷，还需停用相应队列。")


# ---------- 跳过模式 ----------

def _marker(state_dir: Path) -> Path:
    return Path(state_dir) / "skip-restore.json"


def process_skip(state_dir: Path, automas_dir: Path | None,
                 now: datetime | None = None) -> list[str]:
    """Advance the skip state machine by one step. Returns operator messages.

    Cheap when idle - two existence checks - so the engine can call it every
    tick and the flag takes effect at the first tick after it is written,
    which on a boot means before the queue's scheduled time.
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    state_dir = Path(state_dir)
    out: list[str] = []
    out.extend(_maybe_restore(state_dir, automas_dir, now))
    out.extend(_maybe_engage(state_dir, automas_dir, now))
    return out


def _maybe_engage(state_dir: Path, automas_dir: Path | None,
                  now: datetime) -> list[str]:
    day = now.strftime("%Y-%m-%d")
    flag = state_dir / f"skip-{day}.flag"
    # Yesterday's flag with no marker means the skip never engaged (machine
    # was off all day). Say so rather than silently applying it to the wrong
    # day or leaving the file to confuse the next reader.
    stale = sorted(p for p in state_dir.glob("skip-*.flag") if p != flag)
    out = []
    for p in stale:
        p.unlink(missing_ok=True)
        out.append(f"过期的跳过标记 {p.stem} 未曾生效（当天机器没开机），已清除")
    if not flag.exists():
        return out
    if _marker(state_dir).exists():
        return out          # one skip at a time; the marker must resolve first
    queue = flag.read_text(encoding="utf-8").strip() or "新队列"
    if not automas_dir:
        return [*out, f"跳过「{queue}」失败：没有 AUTO-MAS 目录"]

    from . import plan, queues  # noqa: PLC0415 - avoids an import cycle
    times = next((q.get("times") or [] for q in plan.schedule(automas_dir)
                  if q["name"] == queue), [])
    if not times:
        flag.unlink(missing_ok=True)
        return [*out, f"跳过「{queue}」：该队列本就没有启用的排期，无需处理"]
    ok, detail = queues.apply(Path(automas_dir), queue, enabled=False)
    if not ok:
        return [*out, f"跳过「{queue}」失败：{detail}"]   # flag stays; retry next tick
    _marker(state_dir).write_text(json.dumps(
        {"queue": queue, "day": day, "last_time": max(times)},
        ensure_ascii=False), encoding="utf-8")
    flag.unlink(missing_ok=True)
    return [*out, f"今天（{day}）跳过队列「{queue}」：已临时停用，过后自动恢复"]


def _maybe_restore(state_dir: Path, automas_dir: Path | None,
                   now: datetime) -> list[str]:
    marker = _marker(state_dir)
    if not marker.exists():
        return []
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
        day, last_time = str(info["day"]), str(info.get("last_time") or "23:59")
        queue = str(info["queue"])
        hh, mm = (int(x) for x in last_time.split(":"))
        occasion_end = (datetime.strptime(day, "%Y-%m-%d")
                        .replace(hour=hh, minute=mm, tzinfo=SERVER_TZ)
                        + timedelta(minutes=RESTORE_GRACE_MIN))
    except (KeyError, ValueError, json.JSONDecodeError):
        # An unreadable marker must not strand the queue disabled forever.
        marker.unlink(missing_ok=True)
        return ["跳过模式的恢复标记损坏，已清除——请检查队列是否需要手动恢复"]
    if now < occasion_end:
        return []
    if not automas_dir:
        return []
    from . import queues  # noqa: PLC0415
    ok, detail = queues.apply(Path(automas_dir), queue, enabled=True)
    if not ok:
        return [f"跳过「{queue}」后恢复失败：{detail}——请手动检查"]
    marker.unlink(missing_ok=True)
    return [f"队列「{queue}」的跳过已结束，定时已恢复"]
