"""Watch a queue while it runs: speak up at the first timeout and when a shift overruns.

Everything else in the relay learns about a run from AUTO-MAS's records, and
AUTO-MAS writes those only once a script's last attempt is over. On 2026-10-01
OK-WW timed out three times in a row, two hours each (09:18, 11:20, 13:21); the
three records landed together at 15:23, and until then the relay had nothing to
say. The morning shift that normally ends within an hour ran for over seven, and
not one alarm went out. The user, asked whether these two alarms were wanted,
answered 「要」 (2026-10-01 17:28).

Two checks, both run from the tick:

* **First timeout.** AUTO-MAS's own log, `<automas>/debug/app.log`, says so the
  moment an attempt is killed for running too long:

      2026-10-01 16:10:00.012 | INFO | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 进程超时, 日志锁已释放

  (OK-WW's line at 11:20 is the same shape, ending in 运行超时.)

  The first such line per script per day is pushed at once, while AUTO-MAS is
  still retrying. Lines older than FRESH_MINUTES are not news any more (a relay
  restarted mid-afternoon must not replay the morning).

* **Shift overrun.** A queue still unfinished in runtime-snapshot after its
  planned end + OVERRUN_SLACK_MIN. AUTO-MAS has no planned end or expected
  duration (QueueConfig.json holds only Name / Time / Days / Enabled / Mode /
  AfterAccomplish), so the planned end is the longest finish of the last
  HISTORY_DAYS days, recomputed from the ledger each time: on 2026-10-01 that was
  220 minutes for 早班 (09:00) and 19 for 晚班 (21:30).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import plan, texts
from .config import SERVER_TZ

log = logging.getLogger("ark.runwatch")

OVERRUN_SLACK_MIN = 30
HISTORY_DAYS = 7
# Records of one queue run follow each other within seconds; a make-up run hours
# later is a different run. The gap is generous because a hung attempt can leave
# a hole: 2026-09-28 had 41 minutes between two MaaEnd records of the same shift.
CHAIN_GAP_MIN = 60
# How long after its time a queue's first record may start and still be its own.
CHAIN_START_MIN = 60
# No history at all (new queue, wiped ledger): the overrun check still has to work.
FALLBACK_LIMIT_MIN = 180
FRESH_MINUTES = 30
# While anything runs, the loop comes back this often to read app.log.
RUNNING_RECHECK_S = 60

_STAMP = r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^|]*\| (\S+) 自动代理 \| "
_TIMEOUT = re.compile(_STAMP + r".*?任务结果: \S+ (\S{2}超时)")
_ATTEMPT = re.compile(_STAMP + r"用户 .*?尝试次数: (\d+)/(\d+)")


@dataclass
class Timeout:
    at: datetime
    script: str
    what: str                  # AUTO-MAS's own wording of the timeout, kept for the log
    attempt: int = 0           # 0 when no attempt line was seen before it
    of: int = 0
    began: datetime | None = None


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=SERVER_TZ)


class AppLog:
    """Reads what app.log gained since last time and turns it into Timeouts.

    Stateful across reads: the attempt line (「尝试次数: 2/3」) comes long before
    the result line of the same attempt, often in an earlier read.
    """

    def __init__(self, path: Path | None):
        self.path = path
        self._offset = 0
        self._tail = ""
        self._attempt: dict[str, tuple[int, int, datetime]] = {}

    def feed(self, lines) -> list[Timeout]:
        out: list[Timeout] = []
        for line in lines:
            if "自动代理" not in line:
                continue
            if m := _ATTEMPT.match(line):
                self._attempt[m.group(2)] = (int(m.group(3)), int(m.group(4)), _when(m.group(1)))
                continue
            if m := _TIMEOUT.match(line):
                script = m.group(2)
                n, of, began = self._attempt.get(script, (0, 0, None))
                out.append(Timeout(_when(m.group(1)), script, m.group(3), n, of, began))
        return out

    def poll(self) -> list[Timeout]:
        if self.path is None:
            return []
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self._offset:          # AUTO-MAS rotates app.log when it starts
            self._offset, self._tail = 0, ""
        try:
            with self.path.open("rb") as fh:
                fh.seek(self._offset)
                data = fh.read()
        except OSError:
            return []
        if not data:
            return []
        self._offset += len(data)
        text, _, self._tail = (self._tail + data.decode("utf-8", "replace")).rpartition("\n")
        return self.feed(text.splitlines())


def applog_path(automas_dir) -> Path | None:
    return Path(automas_dir) / "debug" / "app.log" if automas_dir else None


# ---------------------------------------------------------------- first timeout

def check_timeouts(eng, events: list[Timeout], now: datetime) -> list[Timeout]:
    """Push the first timeout per script per day. Returns the ones that could not be
    sent: app.log is read only once, so the caller has to hand them back next tick."""
    from . import handle  # noqa: PLC0415
    unsent: list[Timeout] = []
    for ev in events:
        if now - ev.at > timedelta(minutes=FRESH_MINUTES):
            continue
        day = ev.at.strftime("%Y-%m-%d")
        key = f"超时|{ev.script}"
        if handle._already_alerted(eng, day, key):
            continue
        title = texts.attempt_timeout(plan._GAME_OF.get(ev.script, ev.script), ev.script)
        body = texts.attempt_timeout_body(ev.attempt, ev.of, ev.began, ev.at)
        if eng.notifier.send(title, body, alert=True):
            log.error("超时告警没推出去，下一轮再试：%s", ev.script)
            unsent.append(ev)
            continue
        handle._mark_alerted(eng, day, key)
        log.warning("⏱️ %s 第 %s 次%s，已告警（AUTO-MAS 还在重试）", ev.script, ev.attempt or "?", ev.what)
    return unsent


# ---------------------------------------------------------------- shift overrun

def _parse(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return (t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)).astimezone(SERVER_TZ)


def run_minutes(entries: list[dict], due: datetime) -> int | None:
    """Minutes from `due` to the last record of the queue run that started at `due`."""
    runs = sorted(((s, f) for e in entries
                   if (s := _parse(e.get("started"))) and (f := _parse(e.get("finished")) or s)),
                  key=lambda x: x[0])
    end = None
    for s, f in runs:
        if end is None:
            if due - timedelta(minutes=5) <= s <= due + timedelta(minutes=CHAIN_START_MIN):
                end = f
            continue
        if s > end + timedelta(minutes=CHAIN_GAP_MIN):
            break
        end = max(end, f)
    if end is None:
        return None
    return max(0, int((end - due).total_seconds() // 60))


def planned_minutes(eng, hh: int, mm: int, today: datetime) -> tuple[int, int]:
    """(longest finish of the last HISTORY_DAYS days in minutes, days that had one)."""
    found = []
    for back in range(1, HISTORY_DAYS + 1):
        day = today - timedelta(days=back)
        due = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # An evening run can finish after midnight, in the next day's ledger.
        entries = (eng.state.read_ledger(day.strftime("%Y-%m-%d"))
                   + eng.state.read_ledger((day + timedelta(days=1)).strftime("%Y-%m-%d")))
        if (m := run_minutes(entries, due)) is not None:
            found.append(m)
    return (max(found), len(found)) if found else (FALLBACK_LIMIT_MIN, 0)


def overrun_moments(eng, now: datetime):
    """(queue, hhmm, uid, due, limit, deadline) for the latest due of every timed queue."""
    for q in plan.schedule(eng.cfg.automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due > now:
                due -= timedelta(days=1)
            limit, _ = planned_minutes(eng, hh, mm, due)
            yield (q, hhmm, q.get("uid"), due, limit,
                   due + timedelta(minutes=limit + OVERRUN_SLACK_MIN))


def _queue_task(snap, uid):
    for task in (snap or {}).get("tasks") or []:
        if uid and task.get("queueId") == uid:
            return task
    return None


def check_overrun(eng, now: datetime, snap) -> None:
    from . import engine as _engine, handle  # noqa: PLC0415
    if snap is None:
        return       # AUTO-MAS cannot be asked; the timeout check still works
    for q, hhmm, uid, due, limit, deadline in overrun_moments(eng, now):
        if now < deadline:
            continue
        day = due.strftime("%Y-%m-%d")
        key = f"队列超时|{q['name']}|{hhmm}"
        if handle._already_alerted(eng, day, key):
            continue
        task = _queue_task(snap, uid)
        if task is None or not _engine._task_unfinished(task):
            continue
        states = "、".join(f"{i.get('name')} {i.get('status')}"
                          for i in task.get("task_info") or [])
        body = texts.shift_overrun_body(q["name"], due, now, limit, OVERRUN_SLACK_MIN,
                                        states, str(task.get("log") or ""))
        if eng.notifier.send(texts.shift_overrun(q["name"]), body, alert=True):
            log.error("队列超时告警没推出去，下一轮再试：%s", q["name"])
            continue
        handle._mark_alerted(eng, day, key)
        log.warning("⏰ %s %s 开跑，%s 还没跑完（计划 %d 分钟 + %d），已告警",
                    q["name"], hhmm, now.strftime("%H:%M"), limit, OVERRUN_SLACK_MIN)


def next_moments(eng, now: datetime, running: bool) -> list[tuple[datetime, str]]:
    """While anything runs, come back every RUNNING_RECHECK_S seconds.

    That one moment covers both checks: a timeout line can only appear while a
    script runs, and a shift can only overrun while it is still running - so an
    idle machine adds no wake-ups at all.
    """
    if not running:
        return []
    return [(now + timedelta(seconds=RUNNING_RECHECK_S), "在跑巡查：读 AUTO-MAS 日志、核对有没有超时")]
