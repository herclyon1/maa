"""Debug mode (调试模式) and skip mode (跳过模式) - the operator's two levers
over what should NOT happen.

Debug mode  The machine is being worked on: boot it, farm nothing, and above
            all do not power it off. One file carries the whole state - the
            moment the mode stops holding - so it survives restarts, applies
            identically in local and service mode, and expires on its own
            instead of relying on anyone remembering to turn it off. While it
            holds, the engine will not power the machine off (the idle
            checkpoint included) and will not raise missed-run alarms.

            It ends ten minutes before the next scheduled power-on, not at
            midnight. "Leave it alone tonight" means leave it alone until the
            next cycle is about to start - and the calendar day ends in the
            middle of that, which on 2026-08-22 expired the mode forty minutes
            after it was asked for, while an update was still installing. The
            ten minutes are so the ordinary cycle resumes with the mode already
            out of the way.

Skip mode   One queue sits out one occasion. skip_today used to write a flag
            that nothing ever read; now the first tick that sees the flag
            disables that queue inside AUTO-MAS, and a restore marker
            re-enables it once the occasion is over - so a skip can never
            quietly become a permanent stop. The queue's own times are
            captured into the marker at disable time, because a disabled queue
            disappears from plan.schedule and can no longer answer "when was
            I due".
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import os

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.modes")

# How long past the skipped queue's last time of day the restore may happen.
# Generous on purpose: restoring while the occasion is arguably still in
# progress would defeat the skip.
RESTORE_GRACE_MIN = 30

# Scheduled power-on times, server clock. The relay cannot read these from
# anywhere: the morning one is a Mi Home plug cutting and restoring mains so
# the board's "restore on AC" boots it, the evening one is the board's own RTC
# alarm. Neither leaves a record on the machine. Override with ARK_BOOT_TIMES
# ("HH:MM,HH:MM") if the plug or the BIOS alarm is moved.
BOOT_TIMES = tuple(
    s.strip() for s in os.environ.get("ARK_BOOT_TIMES", "08:40,21:20").split(",")
    if s.strip())
# How far ahead of a power-on debug mode releases, so the ordinary cycle starts
# with the mode already gone rather than racing it.
DEBUG_LEAD_MIN = 10
# A power-on this close is the cycle already under way, not the next one. Asked
# at 21:00 for "leave it alone tonight", releasing at 21:10 - ten minutes
# before the 21:20 wake - would be an absurd reading of the request; the run it
# is meant to cover has not even started. Comfortably longer than a queue
# (~85 min) so the whole cycle is inside it.
CURRENT_CYCLE_MIN = 150


def next_boot(now: datetime, min_ahead_min: int = 0) -> datetime:
    """The next scheduled power-on more than `min_ahead_min` away."""
    now = now.astimezone(SERVER_TZ)
    floor = now + timedelta(minutes=min_ahead_min)
    cands = []
    for day in (0, 1, 2):
        for hhmm in BOOT_TIMES:
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            cands.append((now + timedelta(days=day)).replace(
                hour=hh, minute=mm, second=0, microsecond=0))
    future = sorted(c for c in cands if c > floor)
    # No parseable entry at all -> fall back to tomorrow, which keeps the mode
    # on rather than dropping it. Wrong in the safe direction.
    return future[0] if future else now + timedelta(days=1)


def _skip_flag(state_dir: Path) -> Path:
    return Path(state_dir) / "skip-next-shutdown.flag"


def skip_armed(state_dir: Path) -> bool:
    """人有没有按下「下一次别关机」。

    这是给**人**用的开关，桌面上那个 `中继关机开关.bat` 写的就是这个文件。
    和调试模式的区别：调试模式带到期时间，是我维护时用的；这个不带时间，
    就是把**下一次真正要执行的关机指令**吃掉一次，用完即失效。
    用户 2026-08-31：「你给一个人类好去调这个模式的方法，独立于你的。」
    """
    return _skip_flag(state_dir).exists()


def take_skip(state_dir: Path) -> bool:
    """有就用掉并返回 True。用完即失效，下一趟队列照常关机。"""
    f = _skip_flag(state_dir)
    if not f.exists():
        return False
    try:
        f.unlink()
    except OSError:
        log.warning("跳过关机的标记删不掉，可能会连着跳过两次", exc_info=True)
    return True


def _skipped_file(state_dir: Path) -> Path:
    return Path(state_dir) / "shutdown-skipped.txt"


def shutdown_skipped(state_dir: Path) -> str:
    """哪一次关机机会已经被调试模式吃掉了，''=没有。

    用户 2026-08-31：「我开了调试模式是指把一次队列的中继关机指令跳过，
    而不是中继一直尝试关机，要不然人类没办法使用这个电脑。」

    原来调试模式只是让每一次判定返回 False，而判定每 30 秒重来一次——
    到期后条件没变，机器立刻就关了，等于调试模式只是把关机推迟到到期时刻。
    现在它**吃掉这一次机会**：记下当时的机会标识，到期后只要标识没变
    （没有新队列跑完），就不再补关；新队列一跑完标识就变，恢复正常关机。
    """
    try:
        return _skipped_file(state_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def mark_shutdown_skipped(state_dir: Path, key: str) -> None:
    atomic_write_text(_skipped_file(state_dir), key)


def _debug_file(state_dir: Path) -> Path:
    return Path(state_dir) / "debug-until.txt"


def debug_until(state_dir: Path) -> str:
    """The moment debug mode holds through, '' when off.

    "YYYY-MM-DD HH:MM" since 2026-08-23. A bare "YYYY-MM-DD" is still accepted
    and still means end-of-that-day: files written by the older code are on
    disk right now, and reading one as a malformed value would turn the mode
    off under someone who had just switched it on.
    """
    try:
        return _debug_file(state_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def debug_active(state_dir: Path, now: datetime | None = None) -> bool:
    until = debug_until(state_dir)
    if not until:
        return False
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        end = datetime.strptime(until, "%Y-%m-%d %H:%M").replace(tzinfo=SERVER_TZ)
    except ValueError:
        try:                                   # legacy: a bare date
            end = (datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=SERVER_TZ)
                   + timedelta(days=1))
        except ValueError:
            # Anything unparseable fails towards "debug on": the operator
            # explicitly asked for the machine to be left alone, and the wrong
            # failure here powers off a box someone is working on.
            return True
    return now < end


def set_debug(state_dir: Path, cycles: int = 1, off: bool = False,
              now: datetime | None = None) -> tuple[bool, str]:
    """Hold until ten minutes before a scheduled power-on.

    `cycles=1` - the default and what "leave it alone tonight" means - releases
    at the next power-on. `cycles=2` skips one more, and so on. Counting cycles
    rather than days is the whole point: the boundary that matters is the start
    of the next run, and midnight falls in the middle of the night with the
    machine still being worked on.
    """
    path = _debug_file(state_dir)
    if off:
        path.unlink(missing_ok=True)
        return True, "调试模式已关闭，恢复正常运行（队列若被停用需另行恢复）"
    try:
        cycles = max(1, int(cycles))
    except (TypeError, ValueError):
        return False, f"轮数不是整数: {cycles!r}"
    at = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    # The first hop skips a power-on that is already imminent; later hops are
    # plain "the one after that".
    boot = next_boot(at, CURRENT_CYCLE_MIN)
    for _ in range(cycles - 1):
        boot = next_boot(boot)
    end = boot - timedelta(minutes=DEBUG_LEAD_MIN)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: a torn value fails towards "debug on" by design, which means the
    # machine then never powers itself off. Deliberate as a fallback, not as
    # something a power cut should be able to cause.
    atomic_write_text(path, end.strftime("%Y-%m-%d %H:%M"))
    return True, (f"🔧 调试模式已开启，至 {end:%m-%d %H:%M}"
                  f"（下次预定开机 {boot:%m-%d %H:%M} 前 {DEBUG_LEAD_MIN} 分钟）："
                  "不关机、不报漏跑。注意：要让机器什么都不刷，还需停用相应队列。")


# ---------- skip mode (跳过模式) ----------

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
    # Marker BEFORE disable. The old order (disable → marker → unlink) had a
    # crash window after the disable and before the marker: on the next tick
    # the queue had vanished from plan.schedule, this function declared "该队
    # 列本就没有启用的排期", deleted the flag - and the queue stayed disabled
    # forever with a message saying nothing needed doing. Marker-first fails
    # the other way: a crash before the disable leaves a marker whose restore
    # later re-enables an already-enabled queue, which is a no-op.
    # Atomic: the machine is hard power-cut twice a day, and a torn marker
    # makes _maybe_restore delete it and leave the queue disabled forever -
    # exactly the "a skip can never quietly become a permanent stop" promise
    # this module makes.
    atomic_write_text(_marker(state_dir), json.dumps(
        {"queue": queue, "day": day, "last_time": max(times)},
        ensure_ascii=False))
    ok, detail = queues.apply(Path(automas_dir), queue, enabled=False)
    if not ok:
        _marker(state_dir).unlink(missing_ok=True)
        return [*out, f"跳过「{queue}」失败：{detail}"]   # flag stays; retry next tick
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
