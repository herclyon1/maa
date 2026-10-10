"""Who started a run: AUTO-MAS's timer, the relay, or a person at AUTO-MAS itself.

AUTO-MAS writes one line per task it creates, in its own debug/app.log:

    2026-10-03 00:19:50.991 | INFO     | 业务调度 | 创建任务: 68b6e221-…, 模式: AutoProxy, 触发来源: manual_task
    2026-09-25 21:30:00.780 | INFO     | 业务调度 | 创建任务: e715210d-…, 模式: AutoProxy, 触发来源: scheduled_task

and later 「任务结束: <id>」, 「任务 <id> 已结束」 or 「中止任务: <id>」. The id is the
taskId that runtime-snapshot reports.

「manual_task」 is every start that is not AUTO-MAS's own timer, including the relay's
/api/dispatch/start (a rerun after a game update, the phone's 「run now」). The relay
records each start it makes (`note_dispatch`); a task is **hand-started** when it is
manual_task and no relay start matches it.

Callers use this to keep a hand-started run out of the shift: it gets no shift overrun
alarm (runwatch._not_the_shift) and no make-up, stays in the daily report, and its
failures are pushed like any other run's, labelled as started by hand (the user's
order of 2026-10-06 for that last part: 「不论多少次什么错误都要发」).

When app.log cannot be read or has no line for the run, nothing is hand-started.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.trigger")

MANUAL = "manual_task"

_STAMP = r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.\d+)? \|[^|]*\| 业务调度 \| "
_CREATE = re.compile(_STAMP + r"创建任务: ([0-9a-fA-F-]+), 模式: (\S+), 触发来源: (\S+)")
_END = re.compile(_STAMP + r"(?:任务结束: ([0-9a-fA-F-]+)|任务 ([0-9a-fA-F-]+) 已结束|中止任务: ([0-9a-fA-F-]+))")

# The relay's own starts, so that 「manual_task」 can be told apart from a person.
DISPATCH_FILE = "relay-dispatches.json"
KEEP_DAYS = 3
# A dispatch call returns once AUTO-MAS has created the task; allow for a slow API.
MATCH_BEFORE_S = 5
MATCH_AFTER_S = 60


@dataclass
class Task:
    id: str
    mode: str
    source: str
    created: datetime
    ended: datetime | None = None


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=SERVER_TZ)


def parse(lines) -> list[Task]:
    """Every task AUTO-MAS created in these app.log lines, with its end when logged."""
    tasks: dict[str, Task] = {}
    for line in lines:
        if "业务调度" not in line:
            continue
        if m := _CREATE.match(line):
            tasks[m.group(2)] = Task(m.group(2), m.group(3), m.group(4), _when(m.group(1)))
        elif m := _END.match(line):
            t = tasks.get(m.group(2) or m.group(3) or m.group(4))
            if t is not None and t.ended is None:
                t.ended = _when(m.group(1))
    return sorted(tasks.values(), key=lambda t: t.created)


def read(automas_dir) -> list[Task]:
    """The tasks in AUTO-MAS's current app.log; [] when it cannot be read."""
    if not automas_dir:
        return []
    path = Path(automas_dir) / "debug" / "app.log"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return parse(text.splitlines())


# A task with no end line (AUTO-MAS restarted mid-run) stops counting as open after this.
OPEN_CAP = timedelta(hours=24)


def tasks_at(tasks: list[Task], when: datetime) -> list[Task]:
    """Every task open when a script attempt started at `when` (two seconds of slack for
    the clocks' rounding).

    More than one task can be open at once, and app.log does not say which one an
    attempt belongs to, so hand_started_at requires every open task to be hand-started.
    """
    return [t for t in tasks
            if t.created <= when + timedelta(seconds=2)
            and (t.ended >= when if t.ended else when - t.created <= OPEN_CAP)]


# ── the relay's own starts ─────────────────────────────────────────

def _dispatch_path(state_dir) -> Path | None:
    return Path(state_dir) / DISPATCH_FILE if state_dir else None


# The unreadable-file condition last logged. The file is read every tick (shutdown
# decision, runwatch), so each condition is logged once and forgotten once the file
# reads again. Holds at most one key; mutated in place.
_DISPATCH_SAID: set[str] = set()


def _read_dispatches(state_dir) -> list[dict]:
    p = _dispatch_path(state_dir)
    try:
        got = json.loads(p.read_text(encoding="utf-8")) if p else []
    except FileNotFoundError:
        got = []                        # nothing dispatched yet: the normal case
    except (OSError, ValueError) as exc:
        key = f"{p}:{type(exc).__name__}"
        if key not in _DISPATCH_SAID:
            log.warning("读不出中继自己发起的运行记录（%s：%s），中继自己开的运行会被当成有人手动开的",
                        p.name, type(exc).__name__)
            _DISPATCH_SAID.clear()
            _DISPATCH_SAID.add(key)
        return []
    _DISPATCH_SAID.clear()
    return got if isinstance(got, list) else []


def note_dispatch(state_dir, what: str, now: datetime | None = None) -> None:
    """Remember that the relay itself just asked AUTO-MAS to start `what`. Never raises."""
    p = _dispatch_path(state_dir)
    if p is None:
        return
    now = now or datetime.now(tz=SERVER_TZ)
    keep = [d for d in _read_dispatches(state_dir)
            if str(d.get("at") or "") >= (now - timedelta(days=KEEP_DAYS)).isoformat()]
    keep.append({"at": now.isoformat(), "what": what})
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(p, json.dumps(keep, ensure_ascii=False))
    except OSError:
        log.warning("没能记下中继自己发起的运行（%s），这一趟会被当成有人手动开的", what)


def _relay_started(task: Task, dispatches: list[dict]) -> bool:
    for d in dispatches:
        try:
            at = datetime.fromisoformat(str(d.get("at")))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=SERVER_TZ)
        if at - timedelta(seconds=MATCH_BEFORE_S) <= task.created <= at + timedelta(seconds=MATCH_AFTER_S):
            return True
    return False


def hand_started_task(task: Task | None, state_dir) -> bool:
    """A task a person started at AUTO-MAS: manual_task and not one of the relay's own."""
    if task is None or task.source != MANUAL:
        return False
    return not _relay_started(task, _read_dispatches(state_dir))


def hand_started_at(tasks: list[Task], when: datetime, state_dir) -> Task | None:
    """The hand-started task an attempt at `when` belongs to - only when every task open
    then is hand-started. Any doubt (none open, or a scheduled or relay one among them)
    is None: the run keeps today's alarms."""
    open_ = tasks_at(tasks, when)
    if not open_ or not all(hand_started_task(t, state_dir) for t in open_):
        return None
    return open_[-1]


def hand_started(automas_dir, state_dir, when: datetime) -> Task | None:
    """The hand-started task a run starting at `when` belongs to, or None (scheduled,
    the relay's own, or not known - all of which keep today's behaviour)."""
    return hand_started_at(read(automas_dir), when, state_dir)
