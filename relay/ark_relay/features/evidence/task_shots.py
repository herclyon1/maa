"""A desktop picture at the end of every MaaEnd task, kept as evidence.

Why: some MaaEnd tasks (赠送干员礼物, 装备制造, 转交委托, 环境监测) leave nothing in
any log but 「任务开始」 / 「任务完成」 (sample: AUTO-MAS history
2026-10-05/endfield/MaaEnd-06-39-48.log). Whether they did anything cannot be
checked afterwards; a picture of the screen at the moment each one finished can.

Where the moment comes from: not the AUTO-MAS history log - AUTO-MAS writes
it only once the whole script run is over (collect_watch.py's docstring,
docs/CODE-HISTORY.md「engine.py:_scripts_running」). MaaFW's own
`<maaend>/debug/maafw.log` is live and is already tailed by collect_watch; every
task MXU posts shows up there as

    [msg=Tasker.Task.Starting]  [details={"entry":"GiftOperatorMain","task_id":200000001,...}]
    [msg=Tasker.Task.Succeeded] [details={"entry":"GiftOperatorMain","task_id":200000001,...}]

and MXU's own log of 2026-10-05 (debug/2026-10-05-2.log, 10:41:05) lists the
16 entries it posted. The entry is turned back into the name AUTO-MAS prints
(「🎁赠送干员礼物」) through the task declarations interface.json imports and
locales/interface/zh_cn.json - all 16 of that round map to exactly the names in
the AUTO-MAS log.

One picture per Succeeded / Failed, and one at the first Starting of each
MaaEnd launch (the 'before' picture), saved as
`state/shots/<day>/MaaEnd-<HH-MM-SS of that first start>/<HHMMSS>-<name>.png`.
The folder cannot carry AUTO-MAS's own run name (MaaEnd-06-39-48): that is
only known when the record lands. Bundles pick shots by time instead
(`in_window`).

The collect-watch thread only queues; a thread of its own takes the pictures.
A picture goes through the desktop agent (desktop.py: an interactive scheduled
task, polled up to 45 s), and that thread also narrows the gathering routes and
ticks the MaaEnd watchdog, both of which must not wait on it. So a picture
lands a few seconds after its log line (the watcher's 2 s coalescing plus the
agent's start-up) and may already show the next task beginning; the file name
carries the log line's time, the file time when it was really taken. The
entry -> name table is read once at service start: an entry added by a MaaEnd
update mid-day is named by its entry until the next start.

PNG, ~1.5 MB per 1280x720 picture: the desktop agent can only save PNG today
and changing its PowerShell cannot be checked off the machine. Three days are
kept (`prune`, at service start).
"""
from __future__ import annotations

import json
import logging
import queue
import re
import shutil
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("ark.task_shots")

KEEP_DAYS = 3
# A new MaaEnd launch is told by MaaFW numbering its tasks from 200000001 again
# (MXU's log, 2026-10-05 10:41:07: task_ids 200000001..200000016). Not by a quiet
# spell: 自动采集 alone ran 26 minutes without a task event (10:01:54-11:28:22).
# The agent echoes every event from a second process within milliseconds
# (fixtures/collect-watch-2026-09-14, Px7172 / Px18500); a repeat this close is that echo.
ECHO_SECONDS = 5

# MaaFW names a finished task Tasker.Task.Succeeded (MaaEnd's own log-analysis
# notes, .agents/skills/maaend-issue-log-analysis/SKILL.md: 「Starting / Succeeded /
# Failed」); Completed is accepted too in case a build spells it that way.
_EVENT = re.compile(r"\[msg=Tasker\.Task\.(Starting|Succeeded|Completed|Failed)\]\s*\[details=(\{.*?\})\]")
_STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d) (\d\d):(\d\d):(\d\d)")
_DAY = re.compile(r"^\d{4}-\d\d-\d\d$")
# Leading emoji / symbols of a MaaEnd label (「🎁赠送干员礼物」, 「❌关闭游戏（PC）」).
_LEAD = re.compile(r"^[^\w（(]+")
_UNSAFE = re.compile(r'[\\/:*?"<>|\s]+')


def root(state_dir) -> Path:
    return Path(state_dir) / "shots"


def plain_name(label: str) -> str:
    """「🎁赠送干员礼物」 -> 「赠送干员礼物」, safe as a Windows file name."""
    s = _LEAD.sub("", str(label or "")).strip()
    s = _UNSAFE.sub("_", s).strip("._")
    return s or "task"


def entry_labels(maaend_dir) -> dict:
    """entry -> the label AUTO-MAS prints (「🎁赠送干员礼物」); {} when unreadable."""
    if not maaend_dir:
        return {}
    from ark_relay.features.makeup import collect_retry
    from ark_relay.core import mastercfg  # noqa: PLC0415
    try:
        _, tasks = mastercfg._maaend_defs(maaend_dir)
        zh = collect_retry._locale(Path(maaend_dir))
    except Exception:
        log.warning("读不到 MaaEnd 的任务名，截图用入口名命名", exc_info=True)
        return {}
    out: dict = {}
    for t in tasks.values():
        entry, label = t.get("entry"), str(t.get("label") or "")
        if not entry or entry in out:
            continue
        if label.startswith("$"):
            label = str(zh.get(label[1:]) or "")
        out[entry] = label or t.get("name") or entry
    return out


class Shooter:
    """maafw.log task events in, pictures out. `on_line` never blocks; `drain` takes the pictures.

    `shot(out_dir, name) -> Path | None` takes one picture (evidence.desktop_shot by
    default); `labels` maps MaaFW entries to task names.
    """

    def __init__(self, state_dir, labels: "dict | None" = None, shot=None):
        self.root = root(state_dir)
        self.labels = labels or {}
        self._shot = shot
        self.queue: "queue.Queue[tuple[Path, str]]" = queue.Queue()
        self.run_dir: "Path | None" = None
        self._seen: set = set()          # (kind, task_id) this run: the agent echoes each event once more
        self._last_id = 0
        self._last_at: "datetime | None" = None
        self._warned: "Path | None" = None   # the run a failed picture was already logged for

    # ---------------------------------------------------------------- parsing

    def on_line(self, line: str) -> "Path | None":
        """One maafw.log line. Queues a picture when it is a task end (or a run's first start)."""
        m = _EVENT.search(line)
        st = _STAMP.match(line)
        if not m or not st:
            return None
        kind = m.group(1)
        try:
            details = json.loads(m.group(2))
        except ValueError:
            return None
        entry = str(details.get("entry") or "")
        try:
            task_id = int(details.get("task_id") or 0)
        except (TypeError, ValueError):
            task_id = 0
        day, hh, mm, ss = st.groups()
        at = datetime.strptime(f"{day} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")
        key = (kind, task_id)
        new_run = self.run_dir is None
        if key in self._seen:
            if self._last_at is not None and (at - self._last_at).total_seconds() <= ECHO_SECONDS:
                return None      # the agent's echo of the event just handled
            if kind != "Starting":
                return None
            new_run = True       # the same task number started again: MaaEnd was launched anew
        elif kind == "Starting" and task_id and task_id < self._last_id:
            new_run = True
        if new_run:
            self.run_dir = self.root / day / f"MaaEnd-{hh}-{mm}-{ss}"
            self._seen = set()
            self._last_id = 0
        run_dir = self.run_dir
        self._seen.add(key)
        self._last_id = max(self._last_id, task_id)
        self._last_at = at
        if kind == "Starting" and not new_run:
            return None
        name = f"{hh}{mm}{ss}-{plain_name(self.labels.get(entry) or entry)}"
        self.queue.put((run_dir, name))
        return run_dir / f"{name}.png"

    # ---------------------------------------------------------------- pictures

    def drain(self) -> int:
        """Take every queued picture now. Returns how many were saved."""
        n = 0
        while True:
            try:
                out_dir, name = self.queue.get_nowait()
            except queue.Empty:
                return n
            n += self._take(out_dir, name)

    def _take(self, out_dir: Path, name: str) -> int:
        try:
            got = self._shoot(out_dir, name)
        except Exception:  # a missing picture must never stop the next one
            got = None
            log.debug("任务截图出错 %s", name, exc_info=True)
        if got:
            return 1
        if self._warned != out_dir:
            self._warned = out_dir
            log.warning("MaaEnd 任务截图没拿到（%s，这一趟后面的失败不再逐张记）", name)
        return 0

    def _shoot(self, out_dir: Path, name: str):
        if self._shot is not None:
            return self._shot(out_dir, name)
        raise RuntimeError("no screenshot function")

    def _run_forever(self) -> None:
        while True:
            out_dir, name = self.queue.get()
            self._take(out_dir, name)


def start(cfg) -> "Shooter | None":
    """The picture thread, fed by collect_watch. None off Windows (no desktop to take)."""
    import os  # noqa: PLC0415
    if os.name != "nt":
        return None
    from ark_relay.features.evidence import evidence  # noqa: PLC0415

    def shot(out_dir: Path, name: str):
        return evidence.desktop_shot(cfg, out_dir, name=name, move=True, quiet=True)

    s = Shooter(cfg.state_dir, entry_labels(cfg.maaend_dir), shot)
    threading.Thread(target=s._run_forever, name="task-shots", daemon=True).start()
    return s


# ---------------------------------------------------------------- bundles, retention

def in_window(state_dir, window: "tuple[float, float]") -> list[Path]:
    """Every saved picture whose file time is inside `window` (epoch seconds), oldest first."""
    r = root(state_dir)
    if not r.is_dir():
        return []
    out = []
    for p in r.glob("*/*/*.png"):
        try:
            t = p.stat().st_mtime
        except OSError:
            continue
        if window[0] <= t <= window[1]:
            out.append((t, p))
    return [p for _, p in sorted(out)]


def prune(state_dir, today: "date | None" = None, keep_days: int = KEEP_DAYS) -> list[str]:
    """Delete day folders under state/shots/ older than `keep_days` (today counts as one). Returns their names."""
    r = root(state_dir)
    if not r.is_dir():
        return []
    today = today or date.today()
    oldest = today - timedelta(days=keep_days - 1)
    gone = []
    for d in sorted(r.iterdir()):
        if not (d.is_dir() and _DAY.match(d.name)):
            continue
        try:
            day = date.fromisoformat(d.name)
        except ValueError:
            continue
        if day < oldest:
            shutil.rmtree(r / d.name, ignore_errors=True)
            gone.append(d.name)
    if gone:
        log.info("任务截图只留 %d 天，删了 %s", keep_days, "、".join(gone))
    return gone
