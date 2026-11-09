"""Watch a queue while it runs: alarm on every attempt timeout and on a shift overrun.

AUTO-MAS writes a script's record only after its last attempt, so these two
checks read live sources instead. Both run from the tick:

* **Attempt timeout.** AUTO-MAS's own log, `<automas>/debug/app.log`, logs a line
  the moment an attempt is killed for running too long:

      2026-10-01 16:10:00.012 | INFO | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 进程超时, 日志锁已释放

  (OK-WW's line ends in 运行超时.) Every such line is pushed, hand-started runs
  included (user 2026-10-06: 「不论多少次什么错误都要发」). Lines older than
  FRESH_MINUTES are skipped, and a line already pushed is not pushed again
  (app.log is read from its start after a restart).

* **Config-check skip.** AUTO-MAS checks a script's settings before it starts it;
  a refusal is one app.log line and no history record, and the queue moves on:

      2026-10-16 09:34:04.988 | INFO     | 业务调度 | 任务开始: 59da8762-8fa7-4260-8aee-10f9ca00097a
      2026-10-16 09:34:05.023 | WARNING  | MaaEnd 调度器 | 未通过配置检查: <AUTO-MAS's reason>

  The 任务开始 line names the script by its uid (the queue item), so the skip is
  matched to its scheduled run by uid. It is pushed at once with AUTO-MAS's reason,
  and booked as that script's failed run of the shift (check_config_skips).

* **Shift overrun.** A queue still unfinished in runtime-snapshot after its
  planned end + OVERRUN_SLACK_MIN. AUTO-MAS's QueueConfig.json has no planned end
  or duration, so the planned end is the longest finish of the last HISTORY_DAYS
  days and of the same weekday SAME_WEEKDAY_BACK days back, recomputed from the ledger
  each time (planned_minutes).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import plan, texts
from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.runwatch")

OVERRUN_SLACK_MIN = 30
HISTORY_DAYS = 7
# The same weekday this many days back counts too, when it was clean (Gemini's #155 ruling,
# 2026-11-09). Measured (ledgers 10-26..11-08 through _chain): the Monday 早班 is long after the
# 04:00 weekly reset - 10-26 142 min clean, 11-02 151 min not clean (an OK-WW attempt failed),
# every other day 56-87 min - so on 11-09 the HISTORY_DAYS window held no clean Monday, the limit
# was 11-04's 81 min, and 「⏰ 早班超时还没跑完」 went out at 10:51 with MaaEnd gathering on
# normally (OK-WW 51 min against 11-12, the weekly boss and garden). 14 reaches 10-26.
SAME_WEEKDAY_BACK = (7, 14)
# Records of one queue run follow each other closely; a record more than this
# after the previous one starts a different run. A hung attempt can leave a gap of
# tens of minutes inside one run.
CHAIN_GAP_MIN = 60
# How long after its time a queue's first record may start and still be its own.
CHAIN_START_MIN = 60
# No history at all (new queue, wiped ledger): the overrun check still has to work.
FALLBACK_LIMIT_MIN = 180
# Fewer clean days than this and the limit comes from every day that did not time out.
MIN_CLEAN_DAYS = 3
FRESH_MINUTES = 30
# While anything runs, the loop comes back this often to read app.log.
RUNNING_RECHECK_S = 60
# After running goes false, one more read this soon. Measured: AUTO-MAS wrote the refusal line
# 117 ms after the record before it (app.log 10-16 09:34:04.906 / 09:34:05.023), and an answer of
# "running" may be up to engine._SCRIPTS_TTL (3 s) old; 10 s covers both, well inside the minute.
STOPPED_RECHECK_S = 10

_STAMP = r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^|]*\| (\S+) 自动代理 \| "
_TIMEOUT = re.compile(_STAMP + r".*?任务结果: \S+ (\S{2}超时)")
_ATTEMPT = re.compile(_STAMP + r"用户 .*?尝试次数: (\d+)/(\d+)")
_SCRIPT_START = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^|]*\| 业务调度 \| 任务开始: ([0-9a-fA-F-]{36})\s*$")
_CONFIG_SKIP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^|]*\| (\S+) 调度器 \| 未通过配置检查: (.+?)\s*$")


@dataclass
class Timeout:
    at: datetime
    script: str
    what: str                  # AUTO-MAS's own wording of the timeout, kept for the log
    attempt: int = 0           # 0 when no attempt line was seen before it
    of: int = 0
    began: datetime | None = None
    unsent: bool = False       # check_timeouts failed to push it and handed it back


@dataclass
class ConfigSkip:
    at: datetime
    script: str                # AUTO-MAS's type name in the line ("MaaEnd"), for the log
    reason: str                # AUTO-MAS's own words, kept for the log
    uid: str = ""              # the script uid of the script-start line before it; "" when none was seen
    unsent: bool = False


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
        self._started_uid = ""
        # Config-check skips read so far and not yet taken (take_skips).
        self.skips: list[ConfigSkip] = []

    def feed(self, lines) -> list[Timeout]:
        out: list[Timeout] = []
        for line in lines:
            if "业务调度" in line and (m := _SCRIPT_START.match(line)):
                self._started_uid = m.group(2).lower()
                continue
            if "未通过配置检查" in line and (m := _CONFIG_SKIP.match(line)):
                self.skips.append(ConfigSkip(_when(m.group(1)), m.group(2), m.group(3), self._started_uid))
                continue
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


    def take_skips(self) -> list[ConfigSkip]:
        got, self.skips = self.skips, []
        return got


def applog_path(automas_dir) -> Path | None:
    return Path(automas_dir) / "debug" / "app.log" if automas_dir else None


# ---------------------------------------------------------------- first timeout

def check_timeouts(eng, events: list[Timeout], now: datetime) -> list[Timeout]:
    """Push every timeout. Returns the ones that could not be sent: app.log is read
    only once, so the caller has to hand them back next tick."""
    from ark_relay.features.alarm import errwatch, handle  # noqa: PLC0415
    from ark_relay.features.guard import trigger  # noqa: PLC0415
    unsent: list[Timeout] = []
    tasks = None
    for ev in events:
        if now - ev.at > timedelta(minutes=FRESH_MINUTES):
            if ev.unsent:
                # Handed back after failed sends until it went stale: said once, not dropped silently.
                log.warning("⏱️ %s %s 的超时告警 %d 分钟都没推出去，不再重试（第 %s 次%s）", ev.script,
                            ev.at.strftime("%H:%M"), FRESH_MINUTES, ev.attempt or "?", ev.what)
            continue
        day = ev.at.strftime("%Y-%m-%d")
        key = f"超时|{ev.script}|{ev.at:%H:%M:%S}"      # this one line, not the script
        # one fault, one push: one timeout line of app.log (its own time stamp), seen again when app.log is re-read
        if handle._already_alerted(eng, day, key):
            continue
        if tasks is None:
            tasks = trigger.read(eng.cfg.automas_dir)
        title = texts.attempt_timeout(plan._GAME_OF.get(ev.script, ev.script), ev.script)
        body = texts.attempt_timeout_body(ev.attempt, ev.of, ev.began, ev.at)
        if trigger.hand_started_at(tasks, ev.began or ev.at, eng.cfg.state_dir):
            body = texts.HAND_STARTED_NOTE + "\n" + body
        if errs := eng.notifier.send(title, body, alert=True):
            log.error("超时告警没推出去，下一轮再试：%s", ev.script)
            ev.unsent = True
            unsent.append(ev)
            continue
        handle._mark_alerted(eng, day, key)
        log.warning("⏱️ %s 第 %s 次%s，已告警（AUTO-MAS 还在重试）", ev.script, ev.attempt or "?", ev.what,
                    extra=errwatch.group_pushed(title, errs, eng.notifier))
    return unsent


# ---------------------------------------------------------------- config-check skip

def _script_of(automas_dir, uid: str) -> tuple[str, str]:
    """(kind, first user's name) of script `uid` in AUTO-MAS's ScriptConfig.json; "" where unknown."""
    if not automas_dir or not uid:
        return "", ""
    cfg_dir = Path(automas_dir) / "config"
    kind = (plan._scripts(cfg_dir).get(uid) or {}).get("kind") or ""
    node = plan._load(cfg_dir / "ScriptConfig.json").get(uid) or {}
    users = ((node.get("SubConfigsInfo") or {}).get("UserData") or {}).values()
    names = [str((u.get("Info") or {}).get("Name") or "") for u in users if isinstance(u, dict)]
    return kind, next((n for n in names if n), "")


def _shift_of_skip(eng, uid: str, kind: str, at: datetime):
    """(queue, "HH:MM", due) of the scheduled run a skip at `at` belongs to: the latest due
    time whose items include the script (by uid; by kind when no uid was seen) and that came
    up at most cfg.partial_window minutes before. None for a run nobody scheduled."""
    scripts = plan._scripts(Path(eng.cfg.automas_dir) / "config") if not uid and eng.cfg.automas_dir else {}
    best = None
    for q in plan.schedule(eng.cfg.automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":")[:2])
            except ValueError:
                continue
            for back in (0, 1):
                due = (at - timedelta(days=back)).replace(hour=hh, minute=mm, second=0, microsecond=0)
                if not due - timedelta(minutes=5) <= at < due + timedelta(minutes=eng.cfg.partial_window):
                    continue
                items = [str(i).lower() for i in plan.runs_at(q, hhmm, due)]
                hit = uid in items if uid else any((scripts.get(i) or {}).get("kind") == kind for i in items)
                if hit and (best is None or due > best[2]):
                    best = (q, hhmm, due)
    return best


def _book_skip(eng, ref: ConfigSkip, kind: str, user: str, queue: str, now: datetime) -> None:
    """The skip on the day's ledger as the script's failed run of the shift, the way a failed
    record is: the shutdown gate (shutdown._missing_kinds), the missing-item check and the
    reports (ledger_report._bare_reason) all read the ledger. Not held in eng._pending: a
    make-up would be refused by the same check. It scores against the code version like any
    failed run (append_ledger): the relay's own efstart_setup set the path AUTO-MAS refused."""
    from ark_relay.core.config import RunRecord  # noqa: PLC0415
    from ark_relay.features.shutdown import shutdown  # noqa: PLC0415
    who = user or kind
    rec = RunRecord(run_id=f"{ref.at:%Y-%m-%d}/{who}/{kind}-skip-{ref.at:%H-%M-%S}", script=kind, user=who,
                    started=ref.at, finished=ref.at, ok=False, failed_tasks=[],
                    raw={"automas_config_skip": ref.reason, "queue": queue})
    if any(e.get("run_id") == rec.run_id for e in eng.state.read_ledger(f"{ref.at:%Y-%m-%d}")):
        return
    eng.state.append_ledger(rec)
    # The shift's last result, seen by this process (a line read again after a restart is not:
    # shutdown._seen_landing keeps a relay restarted after the shift from powering off).
    if ref.at >= eng._started_at:
        eng._handled_any = True
        shutdown.note_handled(eng, now)


def check_config_skips(eng, refusals: list[ConfigSkip], now: datetime) -> list[ConfigSkip]:
    """Push every config-check skip once, with AUTO-MAS's reason in plain words, and book a
    scheduled one onto the ledger. Its key is missed's own (漏跑|<day>/<queue>/<HH:MM>/<kind>),
    so the timed missing-item check (missed._check_partial_queues) does not say it again.
    Returns the skips whose push failed, for the next tick (app.log is read once); while any
    is left, shutdown.decide holds the machine on ("pending"), as for a held failure."""
    from ark_relay.core.config import both_clocks  # noqa: PLC0415
    from ark_relay.features.alarm import errwatch, handle, missed  # noqa: PLC0415
    from ark_relay.features.guard import trigger  # noqa: PLC0415
    unsent: list[ConfigSkip] = []
    tasks = None
    for ref in refusals:
        kind, user = _script_of(eng.cfg.automas_dir, ref.uid)
        kind = kind or ref.script
        if tasks is None:
            tasks = trigger.read(eng.cfg.automas_dir)
        hand = trigger.hand_started_at(tasks, ref.at, eng.cfg.state_dir)
        shift = None if hand else _shift_of_skip(eng, ref.uid, kind, ref.at)
        if shift is not None:
            q, hhmm, due = shift
            # Past the missing-item window the missed check no longer looks either (app.log
            # keeps earlier days until AUTO-MAS restarts).
            if now - ref.at > timedelta(minutes=eng.cfg.partial_window):
                if ref.unsent:
                    log.warning("🔌 %s %s 开跑前没过检查的告警到缺项核对的时限都没推出去，不再重试（%s）", kind,
                                ref.at.strftime("%H:%M"), ref.reason)
                continue
            queue, day = q["name"], due.strftime("%Y-%m-%d")
            key = f"{day}/{queue}/{hhmm}/{kind}"
            _book_skip(eng, ref, kind, user, queue, now)
            # one fault, one push: one script refused at one queue run (missed's own key), re-read after a restart
            if missed._settled(eng, day, key):
                continue
        else:
            if now - ref.at > timedelta(minutes=FRESH_MINUTES):
                if ref.unsent:
                    log.warning("🔌 %s %s 开跑前没过检查的告警 %d 分钟都没推出去，不再重试（%s）", kind,
                                ref.at.strftime("%H:%M"), FRESH_MINUTES, ref.reason)
                continue
            queue, day = "", ref.at.strftime("%Y-%m-%d")
            key = f"配置检查|{kind}|{ref.at:%H:%M:%S}"
            # one fault, one push: one refusal line of app.log (its own time stamp), seen again when app.log is re-read
            if handle._already_alerted(eng, day, key):
                continue
        game = plan._GAME_OF.get(kind, kind)
        title = texts.missing(texts.not_run_in(kind, queue or "手动开的一趟"))
        body = texts.config_skip_body(game, texts.config_skip_why(ref.reason), both_clocks(ref.at), queue)
        if hand:
            body = texts.HAND_STARTED_NOTE + "\n" + body
        if errs := eng.notifier.send(title, body, alert=True):
            log.error("开跑前没过检查的告警没推出去，下一轮再试：%s", kind)
            ref.unsent = True
            unsent.append(ref)
            continue
        if shift is not None:
            missed._settle(eng, day, key)
        else:
            handle._mark_alerted(eng, day, key)
        log.warning("🔌 %s %s 开跑前没过 AUTO-MAS 的配置检查，没开跑：%s，已告警", queue or "手动开的一趟", kind,
                    ref.reason, extra=errwatch.group_pushed(title, errs, eng.notifier))
    return unsent


# ---------------------------------------------------------------- shift overrun

def _parse(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return (t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)).astimezone(SERVER_TZ)


def _timed_out(e: dict) -> bool:
    """A record AUTO-MAS ended on its time limit. MAA's and MaaEnd's own result keys count
    too: a MaaEnd that did every task and then hung is booked ok with no failed task
    (collector._judge_result, maaend_done_then_hung) and kept its 「超时」 only in
    raw["maaend_result"], so until 11-08 its hung minutes went into planned_minutes'
    clean days (audit 11-08 B-D17)."""
    raw = e.get("raw") or {}
    words = list(e.get("failed_tasks") or []) + [str(raw.get(k) or "")
                                                  for k in ("general_result", "maa_result", "maaend_result")]
    return any("超时" in str(w) for w in words)


def _chain(entries: list[dict], due: datetime) -> tuple[int | None, bool, bool]:
    """For the run that started at `due`: (minutes from `due` to its end,
    every script's last record ok, any record a timeout).

    Clean is judged per script by its last record in the chain: AUTO-MAS retries a
    failed script, and a retry that succeeds is a clean run (10-01..10-13 the 09:00
    run was clean on 2 of 13 days when any failed attempt counted - one MaaEnd attempt
    failing and its retry succeeding - so the limit fell back to the longest day)."""
    # A run a person started at AUTO-MAS (raw.hand_started, handle._book) is not the
    # shift's, so it neither lengthens nor dirties the chain (10-12: OK-WW 11:41-11:49).
    runs = sorted(((s, f, e.get("ok") is not False, _timed_out(e), str(e.get("script") or "")) for e in entries
                   if not (e.get("raw") or {}).get("hand_started")
                   and (s := _parse(e.get("started"))) and (f := _parse(e.get("finished")) or s)),
                  key=lambda x: x[0])
    end, timeout, last_ok = None, False, {}
    for s, f, ok, to, script in runs:
        if end is None:
            if due - timedelta(minutes=5) <= s <= due + timedelta(minutes=CHAIN_START_MIN):
                end, timeout, last_ok = f, to, {script: ok}
            continue
        if s > end + timedelta(minutes=CHAIN_GAP_MIN):
            break
        end, timeout = max(end, f), timeout or to
        last_ok[script] = ok
    if end is None:
        return None, True, False
    return max(0, int((end - due).total_seconds() // 60)), all(last_ok.values()), timeout


def run_minutes(entries: list[dict], due: datetime) -> int | None:
    """Minutes from `due` to the last record of the queue run that started at `due`."""
    return _chain(entries, due)[0]


def _past_run(eng, today: datetime, back: int, hh: int, mm: int, names: list[str]) -> "tuple[int, bool] | None":
    """(minutes, clean) of the queue run at hh:mm `back` days before `today` (_chain); None when
    there was none, it timed out, or it raised an overrun alarm."""
    from ark_relay.features.alarm import handle  # noqa: PLC0415
    hhmm = f"{hh:02d}:{mm:02d}"
    day = today - timedelta(days=back)
    due = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
    # An evening run can finish after midnight, in the next day's ledger.
    entries = (eng.state.read_ledger(day.strftime("%Y-%m-%d"))
               + eng.state.read_ledger((day + timedelta(days=1)).strftime("%Y-%m-%d")))
    m, ok, timed_out = _chain(entries, due)
    if m is None or timed_out:
        return None
    if any(handle._already_alerted(eng, day.strftime("%Y-%m-%d"), f"队列超时|{n}|{hhmm}") for n in names):
        return None
    return m, ok


def planned_minutes(eng, hh: int, mm: int, today: datetime) -> tuple[int, int]:
    """(planned minutes for the queue at hh:mm, days it was taken from).

    The longest finish among the last HISTORY_DAYS days that were clean (each
    script's last record ok, _chain), and among the same weekday SAME_WEEKDAY_BACK days
    back when that day was clean (the Monday shift after the weekly reset). A day that
    timed out or raised an overrun alarm never counts, so one overlong day does not raise
    the limit for a week. With fewer than MIN_CLEAN_DAYS clean days, the longest of every
    day that did not time out is used instead. FALLBACK_LIMIT_MIN only when there is no
    usable day at all. The day count is the HISTORY_DAYS window's.
    """
    names = [q["name"] for q in plan.schedule(eng.cfg.automas_dir)]
    runs = [r for back in range(1, HISTORY_DAYS + 1) if (r := _past_run(eng, today, back, hh, mm, names))]
    weekday = [r[0] for back in SAME_WEEKDAY_BACK if (r := _past_run(eng, today, back, hh, mm, names)) and r[1]]
    clean = [m for m, ok in runs if ok]
    if len(clean) >= MIN_CLEAN_DAYS:
        return max(clean + weekday), len(clean)
    if runs:
        return max([m for m, _ in runs] + weekday), len(runs)
    if weekday:
        return max(weekday), len(weekday)
    return FALLBACK_LIMIT_MIN, 0


def retry_clock(eng, due: datetime, limit: int) -> datetime | None:
    """The latest moment a script of the shift that started at `due` timed out and AUTO-MAS
    retried it: the 「超时|<script>|<HH:MM:SS>」 marks check_timeouts leaves once the timeout
    alarm is out, between `due` and the shift's planned end (due + limit + OVERRUN_SLACK_MIN).
    None when there is none (or no state to read).

    2026-11-05: in the 09:00 早班 MAA's first attempt hung at StartUp for 46 minutes until
    AUTO-MAS's timeout at 09:48 and a retry; MaaEnd started only at 10:22, and at 10:57 both the
    overrun alarm and the no-result alarm counted 87 + 30 minutes from 09:00 (ledger #138) - on
    top of the timeout alarm already pushed for MAA. A retried timeout restarts the shift's
    clock: the rest of the shift is timed from it with the same planned minutes, so a script
    that hangs after the retry is still caught. A timeout after the planned end moves nothing:
    the overrun was due by then.
    """
    end = due + timedelta(minutes=limit + OVERRUN_SLACK_MIN)
    try:
        store = eng.state.store
    except AttributeError:
        return None
    latest = None
    for day in sorted({due.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")}):
        try:
            got = store.get("marks", f"alerted:{day}")
        except Exception:  # noqa: BLE001 - a state read error must not stop the overrun check
            continue
        for key in got if isinstance(got, list) else []:
            parts = str(key).split("|")
            if len(parts) != 3 or parts[0] != "超时":
                continue
            try:
                at = datetime.strptime(f"{day} {parts[2]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=due.tzinfo)
            except ValueError:
                continue
            if due <= at <= end and (latest is None or at > latest):
                latest = at
    return latest


def overrun_moments(eng, now: datetime):
    """(queue, hhmm, uid, due, limit, deadline, days) for the latest due of every timed
    queue; `days` is planned_minutes' day count (0: the fallback, no history). The
    deadline runs from retry_clock when a script of that run timed out and was retried."""
    for q in plan.schedule(eng.cfg.automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":")[:2])
            except ValueError:
                continue        # plan._queues already said so (it normalises to HH:MM)
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due > now:
                due -= timedelta(days=1)
            if not plan.runs_at(q, hhmm, due):
                continue        # off that weekday, or every item skipped: no run to overrun
            limit, days = planned_minutes(eng, hh, mm, due)
            start = retry_clock(eng, due, limit) or due
            yield (q, hhmm, q.get("uid"), due, limit,
                   start + timedelta(minutes=limit + OVERRUN_SLACK_MIN), days)


def last_log_line(log_text, limit: int = 200) -> str:
    """The last non-empty line of AUTO-MAS's task log, at most `limit` characters.

    runtime-snapshot's task `log` is the task's whole log, not its last line: 2026-11-05 the
    早班 MaaEnd task's was 38151 characters in 343 lines, and the overrun alarm put all of it
    into the group text as 「AUTO-MAS 最后一句」 (44 robot messages, see notify.WeComBot.MAX_PARTS).
    """
    for line in reversed(str(log_text or "").splitlines()):
        line = line.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def _queue_task(snap, uid):
    for task in (snap or {}).get("tasks") or []:
        if uid and task.get("queueId") == uid:
            return task
    return None


def _not_the_shift(eng, task, app=False) -> bool:
    """True when this task is one a person started at AUTO-MAS (trigger.py).

    Such a task is not the shift, so the overrun alarm (which says the shift
    started at its due time is still running) does not apply; its failures and
    timeouts still alarm (handle, check_timeouts). A task app.log does not mention
    is treated as the shift. `app`: the task's app.log entry when the caller has
    read it already (_app_task), so app.log is read once.
    """
    from ark_relay.features.guard import trigger  # noqa: PLC0415
    t = _app_task(eng, task) if app is False else app
    return t is not None and trigger.hand_started_task(t, eng.cfg.state_dir)


def _app_task(eng, task):
    """The task app.log created for this runtime-snapshot task (trigger.Task), None when
    app.log does not mention it."""
    from ark_relay.features.guard import trigger  # noqa: PLC0415
    tid = str(task.get("taskId") or "")
    if not tid:
        return None
    for t in trigger.read(eng.cfg.automas_dir):
        if t.id == tid or (len(tid) >= 8 and t.id.startswith(tid)):
            return t
    return None


def _created(t) -> str:
    """app.log's 「创建任务」 line of a task, by its fields."""
    return f"{t.created:%m-%d %H:%M:%S} 创建任务 {t.id[:8]}，模式 {t.mode}，触发来源 {t.source}" if t else ""


def _late_start(app, due: datetime) -> datetime | None:
    """When the running task was created after its due minute: its creation time, else None.

    2026-11-09 00:52:21 session 2499 re-ran the evening shift through the phone's run_now; at 00:52:28
    the overrun alarm (ledger #151) said the 21:30 run had been going for 202 minutes and was
    due to end by 22:21. The relay's own late start of the whole queue (the phone's run_now:
    phone/commands.py notes it, so _not_the_shift keeps it in the shift) is timed from its own
    start. A make-up or a re-run after an update dispatches one script, not the queue, so its
    task is not the queue's and this check never sees it. AUTO-MAS's timer creates the shift's
    task inside its due minute (21:30:00.780 in app.log), so that one keeps the due time.
    """
    if app is None or app.created.replace(second=0, microsecond=0) <= due:
        return None
    return app.created


def check_overrun(eng, now: datetime, snap) -> None:
    """A queue still running past its planned end: one alarm for that run (key: the
    queue and its due time - the same overrun is one event, re-checked every minute)."""
    from ark_relay.core import engine as _engine  # noqa: PLC0415
    from ark_relay.features.alarm import errwatch, handle, unresolved  # noqa: PLC0415
    from ark_relay.features.shutdown import shutdown  # noqa: PLC0415
    if snap is None:
        return       # AUTO-MAS cannot be asked; the timeout check still works
    for q, hhmm, uid, due, limit, deadline, days in overrun_moments(eng, now):
        if now < deadline:
            continue
        day = due.strftime("%Y-%m-%d")
        key = f"队列超时|{q['name']}|{hhmm}"
        # shutdown._alarm_shift_overdue may have pushed this same run while AUTO-MAS could not be asked.
        # one fault, one push: one shift run (queue + its due time) running long, re-checked every minute
        if (handle._already_alerted(eng, day, key)
                or handle._already_alerted(eng, day, f"{shutdown.OVERDUE_KEY}|{q['name']}|{hhmm}")):
            continue
        task = _queue_task(snap, uid)
        if task is None or not _engine._task_unfinished(task):
            continue
        app = _app_task(eng, task)
        seen = {"kind": "队列超时", "queue": q["name"], "hhmm": hhmm, "create": _created(app),
                "task_id": str(task.get("taskId") or ""), "run_id": f"{q['name']} {hhmm}"}
        if _not_the_shift(eng, task, app):
            # Machine check #55: the task left out was a person's (its app.log line).
            unresolved.machinecheck(eng, dict(seen, alarmed=False))
            continue
        start = deadline - timedelta(minutes=limit + OVERRUN_SLACK_MIN)
        restarted = start if start != due else None
        if (started := _late_start(app, due)) is not None:
            # Its own clock: from its creation, or from a timeout AUTO-MAS retried inside it.
            restarted = retry_clock(eng, started, limit)
            if now < (restarted or started) + timedelta(minutes=limit + OVERRUN_SLACK_MIN):
                continue
        states = "、".join(f"{i.get('name')} {i.get('status')}"
                          for i in task.get("task_info") or [])
        body = texts.shift_overrun_body(q["name"], due, now, limit, OVERRUN_SLACK_MIN,
                                        states, last_log_line(task.get("log")), days,
                                        restarted=restarted, started=started)
        if errs := eng.notifier.send(texts.shift_overrun(q["name"]), body, alert=True):
            log.error("队列超时告警没推出去，下一轮再试：%s", q["name"])
            continue
        handle._mark_alerted(eng, day, key)
        log.warning("⏰ %s %s 开跑，%s 还没跑完（计划 %d 分钟 + %d），已告警",
                    q["name"], f"{hhmm}（这趟 {started:%H:%M}）" if started else hhmm,
                    now.strftime("%H:%M"), limit, OVERRUN_SLACK_MIN,
                    extra=errwatch.group_pushed(texts.shift_overrun(q["name"]), errs, eng.notifier))
        # Machine check #55: the task alarmed on was the shift's own (its app.log line).
        unresolved.machinecheck(eng, dict(seen, alarmed=True, sent=True, title=texts.shift_overrun(q["name"]),
                                          body=body))


def next_moments(eng, now: datetime, running: bool) -> list[tuple[datetime, str]]:
    """While anything runs, come back every RUNNING_RECHECK_S seconds.

    That one moment covers both checks: a timeout line can only appear while a
    script runs, and a shift can only overrun while it is still running - so an
    idle machine adds no wake-ups at all.

    One more wake STOPPED_RECHECK_S after running is first seen false: a config-check
    skip of the queue's last item lands in app.log after the record that woke the loop,
    when nothing runs any more (10-16: OK-WW's record 09:34:04.906, MaaEnd's skip line
    09:34:05.023). Kept until it passes, so a second ask in the meantime gets it too.
    """
    if running:
        eng._watch_running, eng._watch_stopped = True, None
        return [(now + timedelta(seconds=RUNNING_RECHECK_S), "在跑巡查：读 AUTO-MAS 日志、核对有没有超时")]
    if getattr(eng, "_watch_running", False):
        eng._watch_running, eng._watch_stopped = False, now + timedelta(seconds=STOPPED_RECHECK_S)
    stop = getattr(eng, "_watch_stopped", None)
    if stop is not None and stop > now:
        return [(stop, "队列刚停：再读一次 AUTO-MAS 日志，看有没有开跑前被跳过的项")]
    eng._watch_stopped = None
    return []
