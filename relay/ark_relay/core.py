"""Judgment, bookkeeping, and message formatting.

Everything factual is decided here, in plain Python. The model is only ever
asked to phrase things (see summary.py). If it misbehaves the result is an
awkward sentence, never a wrong verdict.
"""
from __future__ import annotations

import json
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
    lines = [
        f"{both_clocks(rec.started)} → {both_clocks(rec.finished)}",
        f"用时 {rec.duration_min} 分钟 · 账号 {rec.user}",
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
    """'09:00→09:45　45m　东京 10:00' - compact but unambiguous."""
    if not known:
        return f"{_hm(started)}　时长未知　东京 {started.astimezone(USER_TZ):%H:%M}"
    mins = max(0, round((finished - started).total_seconds() / 60))
    dur = f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m"
    return (f"{_hm(started)}→{_hm(finished)}　{dur}"
            f"　东京 {started.astimezone(USER_TZ):%H:%M}")


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
        lines.append(("✅" if e["ok"] else "❌")
                     + f" {e['script']}　{_span(started, finished, e.get('duration_known', True))}")
        if not e["ok"]:
            lines.append("· " + _fmt_failed(e.get("failed_tasks") or []))
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
        if recruits := _fmt_items(e.get("recruits") or {}):
            lines.append("· 公招 " + recruits)
        if e.get("sanity") is not None:
            s = f"· 剩余理智 {e['sanity']}"
            full = str(e.get("sanity_full_at") or "")
            if "回满" in full:
                s += "，" + full.split("理智将在")[-1].split("回满")[0].strip() + " 回满"
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
