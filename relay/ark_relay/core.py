"""Judgment, bookkeeping, and message formatting.

Everything factual is decided here, in plain Python. The model is only ever
asked to phrase things (see summary.py). If it misbehaves the result is an
awkward sentence, never a wrong verdict.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, USER_TZ, Config, RunRecord, both_clocks


class State:
    """Which runs have been handled, and today's ledger.

    Kept as line-delimited JSON so a half-written file costs at most one
    record, and so it stays readable when something goes wrong at 3am.
    """

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen.txt"
        self._seen: set[str] | None = None

    @property
    def seen(self) -> set[str]:
        if self._seen is None:
            if self.seen_path.exists():
                self._seen = {
                    ln.strip()
                    for ln in self.seen_path.read_text(encoding="utf-8").splitlines()
                    if ln.strip()
                }
            else:
                self._seen = set()
        return self._seen

    def mark_seen(self, run_id: str) -> None:
        self.seen.add(run_id)
        with self.seen_path.open("a", encoding="utf-8") as f:
            f.write(run_id + "\n")

    def ledger_path(self, day: str) -> Path:
        return self.dir / f"ledger-{day}.jsonl"

    def append_ledger(self, rec: RunRecord) -> None:
        entry = {
            "run_id": rec.run_id,
            "script": rec.script,
            "user": rec.user,
            "started": rec.started.isoformat(),
            "finished": rec.finished.isoformat(),
            "ok": rec.ok,
            "failed_tasks": rec.failed_tasks,
            "duration_known": rec.duration_known,
            # The model reads this verbatim. Keeping AUTO-MAS's own output
            # means the report can never disagree with what actually happened.
            "raw": rec.raw,
            "sanity": rec.sanity,
            "sanity_full_at": rec.sanity_full_at,
            "drops": rec.drops,
            "recruits": rec.recruits,
        }
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        with self.ledger_path(day).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_ledger(self, day: str) -> list[dict]:
        p = self.ledger_path(day)
        if not p.exists():
            return []
        out = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue  # tolerate one torn line rather than lose the day
        return out

    # ---------- undelivered alerts survive a restart ----------
    #
    # An alert held in memory is an alert lost the moment the relay restarts -
    # and this machine reboots twice a day. Anything not yet delivered goes to
    # disk and is only removed once a channel has actually accepted it.

    @property
    def pending_path(self) -> Path:
        return self.dir / "pending.json"

    def save_pending(self, payload: dict) -> None:
        tmp = self.pending_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.pending_path)  # atomic: never leave a half-written file

    def load_pending(self) -> dict:
        if not self.pending_path.exists():
            return {}
        try:
            data = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def report_sent(self, day: str) -> bool:
        return (self.dir / f"report-{day}.sent").exists()

    def interim_sent(self, day: str) -> bool:
        return (self.dir / f"interim-{day}.sent").exists()

    def interim_covered(self, day: str) -> int:
        """How many ledger entries the day's interim reports already cover.

        Stored as a count so a make-up run later the same day (new entries
        past the covered mark) triggers a fresh interim instead of being
        swallowed by a boolean "already sent today" - the operator's design
        is one interim per finished daytime round, not one per day.
        """
        try:
            raw = (self.dir / f"interim-{day}.sent").read_text(
                encoding="utf-8").strip()
        except OSError:
            return 0
        if not raw:
            # Legacy empty marker (pre-2026-08-20): sent, count unknown -
            # never re-announce the day's already-reported rounds.
            return 10**6
        try:
            return int(raw)
        except ValueError:
            return 10**6

    def mark_interim_sent(self, day: str, covered: int = 1) -> None:
        (self.dir / f"interim-{day}.sent").write_text(
            str(covered), encoding="utf-8")

    def mark_report_sent(self, day: str) -> None:
        (self.dir / f"report-{day}.sent").touch()


def is_last_run_of_day(rec: RunRecord, cfg: Config) -> bool:
    """True once the day's final scheduled queue has finished.

    Configured as ARK_LAST_RUN_AFTER (server time). Anything finishing at or
    after that hour is treated as the day's closer.
    """
    try:
        hh, mm = (int(x) for x in cfg.last_run_after.split(":"))
    except ValueError:
        hh, mm = 21, 30
    finished = rec.finished.astimezone(SERVER_TZ)
    cutoff = finished.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return finished >= cutoff


def format_failure(rec: RunRecord, diagnosis: str = "") -> tuple[str, str]:
    """Immediate alert for a failed run. Title, body."""
    title = f"❌ {rec.script} 失败"
    # duration_known=False means start/finish came from filename/mtime, which
    # is hours wrong on this install ("未捕获到日志" runs - exactly the class
    # most likely to be a failure alert). Never present those as fact.
    if rec.duration_known:
        lines = [
            f"{both_clocks(rec.started)} → {both_clocks(rec.finished)}",
            f"用时 {rec.duration_min} 分钟 · 账号 {rec.user}",
            "",
        ]
    else:
        lines = [
            f"{both_clocks(rec.started)}（文件名时间，可能有偏差）",
            f"时长未知 · 账号 {rec.user}",
            "",
        ]
    lines.append("· " + _fmt_failed(rec.failed_tasks))
    if rec.sanity is not None:
        lines += ["", f"剩余理智 {rec.sanity}"]
        if rec.sanity_full_at:
            lines.append(rec.sanity_full_at)
    if diagnosis:
        lines += ["", "─" * 12, diagnosis]
    return title, "\n".join(lines)


def _fmt_items(d: dict, limit: int | None = None) -> str:
    """Render a {name: count} map, biggest first, as one line.

    `limit=None` means never fold. Output is the whole point of the report -
    an elided "…另1项" hides exactly the number the reader opened the message
    to see, and there is no way to go look it up afterwards.
    """
    if not d:
        return ""
    try:
        pairs = sorted(d.items(), key=lambda kv: -int(kv[1]))
    except (TypeError, ValueError):
        pairs = list(d.items())
    if limit is None or len(pairs) <= limit:
        return " ".join(f"{k}×{v}" for k, v in pairs)
    out = [f"{k}×{v}" for k, v in pairs[:limit]]
    out.append(f"…另{len(pairs) - limit}项")
    return " ".join(out)


def _fmt_failed(names: list[str], limit: int = 3) -> str:
    """Fold long failure lists.

    A run where everything failed means the script never got going - listing
    fourteen separate lines implies fourteen separate faults, which is both
    wrong and unreadable on a phone.
    """
    names = names or ["未知"]
    if len(names) <= limit:
        return "、".join(names)
    return f"{len(names)} 项失败：" + "、".join(names[:limit]) + "…"


def _hm(dt: datetime) -> str:
    return f"{dt.astimezone(SERVER_TZ):%H:%M}"


def _span(started: datetime, finished: datetime, known: bool = True) -> str:
    """'09:00→09:18　17m　东京 10:00→10:18'.

    Both ends on both clocks. Showing only the Tokyo start meant the reader
    could see when a run began in their own time but had to do the arithmetic
    to know when it ended - on the one line where the whole point is the span.
    """
    tk = lambda d: f"{d.astimezone(USER_TZ):%H:%M}"  # noqa: E731
    if not known:
        return f"{_hm(started)}　时长未知　东京 {tk(started)}"
    mins = max(0, round((finished - started).total_seconds() / 60))
    dur = f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m"
    return (f"{_hm(started)}→{_hm(finished)}　{dur}"
            f"　东京 {tk(started)}→{tk(finished)}")


# "理智将在 2026-08-17 05:33 回满。(20h 14m 后)"
_FULL_AT = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")


def _sanity_full(raw: str, ref: datetime) -> str:
    """'次日 05:33 回满（东京 06:33）'. '' when the source says nothing.

    A bare "2026-08-17 05:33" makes the reader work out whether that is tonight
    or tomorrow, which is the only thing they actually wanted to know.
    """
    m = _FULL_AT.search(str(raw or ""))
    if not m:
        return ""
    try:
        when = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    when = when.replace(tzinfo=SERVER_TZ)
    delta = (when.date() - ref.astimezone(SERVER_TZ).date()).days
    day = {0: "本日", 1: "次日"}.get(delta) or f"{delta} 天后"
    return f"{day} {when:%H:%M} 回满（东京 {when.astimezone(USER_TZ):%H:%M}）"


def format_daily(day: str, entries: list[dict], prose: str = "",
                 plan: str = "") -> tuple[str, str]:
    """The one message of the day. Numbers here are copied, never generated.

    Laid out for a narrow phone screen: no nested indentation (full-width
    spaces do not line up across fonts), one fact per short line.
    """
    if not entries:
        return f"📋 {day} 日报", "今天没有任何运行记录。"

    failed = [e for e in entries if not e["ok"]]
    head = "全绿 ✅" if not failed else f"{len(failed)} 项失败 ⚠️"
    title = f"📋 {day[5:]} · {head}"

    lines: list[str] = []
    for e in entries:
        started = datetime.fromisoformat(e["started"])
        finished = datetime.fromisoformat(e["finished"])
        raw_early = e.get("raw") or {}
        # AUTO-MAS always runs 剿灭 as its own pass before the day's farming, so
        # every queue produces two records. The first is a one-minute check that
        # farms nothing, and unlabelled it looked like a run that mysteriously
        # did nothing and ended on 0 sanity.
        tag = "（剿灭检查）" if raw_early.get("annihilation") else ""
        lines.append(("✅" if e["ok"] else "❌")
                     + f" {e['script']}{tag}　"
                     + _span(started, finished, e.get('duration_known', True)))
        if not e["ok"]:
            lines.append("· " + _fmt_failed(e.get("failed_tasks") or []))
        if raw_early.get("annihilation"):
            prog = raw_early.get("annihilation_progress")
            if prog and prog[0] >= prog[1]:
                note = f"本周剿灭已打满（{prog[0]}/{prog[1]}）"
            elif prog:
                note = f"⚠️ 剿灭只打到 {prog[0]}/{prog[1]}，本周还没满"
            elif raw_early.get("annihilation_done"):
                note = "本周剿灭此前已完成，跳过"
            else:
                note = "已打剿灭"
            lines.append("· " + note)
            lines.append("")
            continue
        # What the sanity actually bought. AUTO-MAS leaves these empty, so they
        # come from the collector's parse of MAA's own log - see collector.py.
        raw = e.get("raw") or {}
        if stages := raw.get("stages"):
            farmed = "、".join(stages)
            if times := raw.get("run_times"):
                farmed += f" ×{times}"
            lines.append("· 刷了 " + farmed)
        if spent := raw.get("sanity_spent"):
            cost = f"· 消耗理智 {spent}"
            if med := raw.get("medicine_used"):
                cost += f"，吃药 {med}"
            lines.append(cost)
        if drops := _fmt_items(e.get("drops") or {}):
            lines.append("· 产出 " + drops)
        # MaaEnd works through a list of chores rather than farming a stage, so
        # "how many got done" is its equivalent of a stage count.
        if done := raw.get("tasks_done"):
            lines.append(f"· 完成 {len(done)} 项日常")
        # MaaEnd publishes no sanity number and no refill time, so say the one
        # thing it does report rather than leaving the line blank and letting
        # the reader wonder whether it simply stopped early.
        if runs := raw.get("protocol_runs"):
            note = f"· 协议空间 {runs} 次"
            if raw.get("sanity_exhausted"):
                note += "，理智已耗尽"
            lines.append(note)
        elif raw.get("sanity_exhausted"):
            lines.append("· 理智不足，未进入协议空间")
        if recruits := _fmt_items(e.get("recruits") or {}):
            lines.append("· 公招 " + recruits)
        if e.get("sanity") is not None:
            s = f"· 剩余理智 {e['sanity']}"
            # 终末地 reports "current/cap", and the current value really does
            # go over the cap - being over means sanity (理智) is overflowing
            # and going to waste, which is a signal to act on, so a bare
            # number on its own is not enough.
            if cap := raw.get("sanity_cap"):
                s += f"/{cap}"
                if e["sanity"] > cap:
                    s += "　⚠️ 已超上限，理智在溢出"
            if full := _sanity_full(e.get("sanity_full_at"), finished):
                s += "，" + full
            lines.append(s)
        lines.append("")

    if prose:
        lines += ["———————", prose, ""]
    # Knowing last night was fine is only half of it - the operator also needs
    # to know what tomorrow will farm, while there is still time to change it.
    if plan:
        lines += ["———————", plan]
    return title, "\n".join(lines).rstrip()


def format_missing(what: str, expected_at: datetime, detail: str = "") -> tuple[str, str]:
    """Alert for something that should have happened and did not.

    This is the alert only a relay outside the monitored machine can produce.
    """
    title = f"🔌 {what}"
    body = [f"预计 {both_clocks(expected_at)} 应发生，至今没有。"]
    if detail:
        body += ["", detail]
    return title, "\n".join(body)


def stale_seconds(last: datetime | None, now: datetime | None = None) -> float:
    now = now or datetime.now(tz=SERVER_TZ)
    if last is None:
        return float("inf")
    return (now - last).total_seconds()


def next_occurrence(hhmm: str, now: datetime | None = None) -> datetime:
    """Next time-of-day on the server clock, today or tomorrow."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    hh, mm = (int(x) for x in hhmm.split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)
