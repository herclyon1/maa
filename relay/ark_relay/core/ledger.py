"""The ledger: one JSON line per finished run, per day, plus the marks kept beside it.

`State` appends, reads and rewrites ledger entries and keeps the seen-run set,
pending payload and sent-report / banner marks. Report text built from the
entries is in ledger_rows.py and ledger_report.py. Every verdict is plain
Python; the model only phrases text (summary.py).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ark_relay.features.report import scoreboard
from ark_relay.core.statestore import StateStore
from ark_relay.core.config import atomic_write_text, RunRecord, SERVER_TZ

# Report text lives in ledger_rows / ledger_report; callers and tests still say
# ledger.<name>, so every name defined there is importable from here too.
from ark_relay.core.ledger_rows import (  # noqa: F401
    UNVERIFIED, UNVERIFIED_STEP, _END_FARM_NOTE_SKIP, _FULL_AT, _LABELS, _block, _block_maa,
    _block_maaend, _block_okww, _fmt_items, _maaend_listed, _row, _rows_for, _sanity_full,
    _with_causes, maaend_unverified,
)
from ark_relay.core.ledger_report import (  # noqa: F401
    _KIND_ICON, _KIND_NOTE, _claim_block, _collapse_retries, _count_by_script, _daily_head,
    _fmt_failed, _game, _hm, _launch_miss, _maaend_restart, _no_exit_note, _ran_later,
    _skipped_gathering_only, _span, daily_footnote, day_unverified, day_unverified_items,
    episode_kinds, format_daily, format_failure, format_missing, manual_stop, retried_notes,
    split_test,
)

log = logging.getLogger("ark.core")


def _is_iso(v) -> bool:
    try:
        datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return False
    return True


# The last unreadable-line condition said per ledger file (path -> torn lines),
# the WeeklyBossGate._last_error pattern: read_ledger runs every tick and on every
# phone-state publish, so a torn line is said once, not on every read. Reset when
# the file no longer has it.
_LEDGER_TORN_SAID: dict[str, frozenset] = {}
# The last non-numeric interim marker said, {day: raw} with at most one entry:
# interim_covered is asked every tick once the interim check gets that far. Same
# pattern, cleared once that day's marker reads as a count again.
_INTERIM_SAID: dict[str, str] = {}


class State:
    """Which runs have been handled, and today's ledger.

    Kept as line-delimited JSON so a half-written file costs at most one
    record, and so it stays readable when something goes wrong at 3am.
    """

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen.txt"      # append-only and grows large; stays its own file
        self._seen: set[str] | None = None
        # The day's markers and the alert queue all live in state.json
        # (docs/STATE-MODEL.md): they used to be a dozen scattered .sent / .json
        # files where who wrote and who read what was carried in someone's head,
        # and one late write produced a false state.
        self.store = StateStore(state_dir)

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
            # Tells the model writing the report that this is not a failure but
            # a record superseded by the next round
            "transitional": rec.transitional,
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
        # Score the current code version while we are here. It sits here because
        # **every finished run has to pass through this line**, so nothing I write
        # into the daily report can touch it - which is exactly what the user
        # asked for on 2026-09-06:
        # 「我说『修好了』而它写『失败 1 趟』，谎话当场现形。」
        try:
            # A run the red button cut short says nothing about the code version.
            if not (rec.raw or {}).get("manual_stop"):
                scoreboard.record(self.store, str(self.store.get("versions", "code") or ""),
                                  rec.ok, rec.transitional)
        except Exception:
            # The scoreboard must never take the bookkeeping down with it: the
            # ledger is the main line, this entry is incidental.
            log.warning("记分牌没记上", exc_info=True)

    def mark_incomplete(self, day: str, run_id: str, why: str) -> bool:
        """Write a failed outcome check back onto the day's ledger line.

        Until 2026-09-10 the check only produced a push notification; the
        ledger kept `ok: true` and the evening report still opened with 全绿.
        The record stays `ok` (AUTO-MAS did see the process exit normally, and
        the retry logic keys off that) - `incomplete` is a second, independent
        fact about the same run: it finished, and it did not do the work.
        """
        return self._rewrite_entry(day, run_id, lambda e: e.__setitem__("incomplete", why))

    def mark_raw(self, day: str, run_id: str, key: str, value) -> bool:
        """Set one raw field on the day's ledger line (the line is written first)."""
        def put(e: dict) -> None:
            raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
            raw[key] = value
            e["raw"] = raw
        return self._rewrite_entry(day, run_id, put)

    def mark_evidence(self, day: str, run_id: str, page: str) -> bool:
        """Write the evidence link back onto the day's ledger line.

        The run is on the ledger before its bundle is shipped (handle.py appends
        first, so a crash later cannot lose it), so the link set on rec.raw
        afterwards never reached the file, and the daily report's 证据包 row read
        an empty field on every failure until 2026-09-24.
        """
        def put(e: dict) -> None:
            raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
            raw["evidence_page"] = page
            e["raw"] = raw
        return self._rewrite_entry(day, run_id, put)

    def _rewrite_entry(self, day: str, run_id: str, edit) -> bool:
        p = self.ledger_path(day)
        if not p.exists():
            return False
        lines = p.read_text(encoding="utf-8").splitlines()
        hit = False
        for i, ln in enumerate(lines):
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("run_id") == run_id:
                edit(entry)
                lines[i] = json.dumps(entry, ensure_ascii=False)
                hit = True
        if hit:
            atomic_write_text(p, "\n".join(lines) + "\n")
        return hit

    # What every consumer of a ledger entry assumes is present. Checked once,
    # here, rather than defended against at each of the dozen places that read
    # these fields - and one of those places is the deterministic report
    # layout, the last fallback when the wording model is unavailable. A
    # KeyError there means the daily report is never sent, and since the
    # shutdown path waits for a sent report, the machine stays powered on all
    # night. A missing dictionary key should not be able to do that.
    _LEDGER_REQUIRED = ("run_id", "script", "started", "finished", "ok")

    def read_ledger(self, day: str) -> list[dict]:
        p = self.ledger_path(day)
        if not p.exists():
            return []
        out = []
        torn = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                torn.append(ln)
                continue  # tolerate one torn line rather than lose the day
            if not isinstance(entry, dict):
                continue
            if missing := [k for k in self._LEDGER_REQUIRED if k not in entry]:
                # Reachable: the ledger is line-delimited JSON on a machine
                # that is hard power-cut twice a day, so a line can end up
                # valid JSON yet incomplete.
                log.warning("账目里有一条残缺记录（缺 %s），已跳过: %.120s",
                            "、".join(missing), ln)
                continue
            # A key being present does not mean its value is right. Both the
            # daily report and the shutdown decision run started/finished through
            # fromisoformat, and one unparseable record stops the whole day's
            # report from going out; shutdown waits for that report, so the
            # machine stays on all night. Same class of problem as the missing
            # keys above, and skipped the same way.
            bad = [k for k in ("started", "finished")
                   if not _is_iso(entry.get(k))]
            if bad:
                log.warning("账目里有一条时间不合法的记录（%s），已跳过: %.120s",
                            "、".join(bad), ln)
                continue
            out.append(entry)
        said = _LEDGER_TORN_SAID.get(str(p), frozenset())
        for ln in torn:
            if ln not in said:
                # A run lost to a torn write would otherwise vanish from the
                # daily report and today's counts with no word.
                log.warning("账目里有一行不是完整的 JSON（多半是断电写了一半），已跳过: %.120s", ln)
        if torn:
            _LEDGER_TORN_SAID[str(p)] = frozenset(torn)
        else:
            _LEDGER_TORN_SAID.pop(str(p), None)
        return out

    # ---------- undelivered alerts survive a restart ----------
    #
    # An alert held in memory is an alert lost the moment the relay restarts -
    # and this machine reboots twice a day. Anything not yet delivered goes to
    # disk and is only removed once a channel has actually accepted it.

    def save_pending(self, payload: dict) -> None:
        self.store.set("queues", "pending", dict(payload))

    def load_pending(self) -> dict:
        data = self.store.get("queues", "pending")
        return dict(data) if isinstance(data, dict) else {}

    def report_sent(self, day: str) -> bool:
        return self.store.get("marks", f"report:{day}") is not None

    def interim_sent(self, day: str) -> bool:
        return self.store.get("marks", f"interim:{day}") is not None

    def interim_covered(self, day: str) -> int:
        """How many ledger entries the day's interim reports already cover.

        Stored as a count so a make-up run later the same day (new entries
        past the covered mark) triggers a fresh interim instead of being
        swallowed by a boolean "already sent today" - the operator's design
        is one interim per finished daytime round, not one per day.
        """
        raw = self.store.get("marks", f"interim:{day}")
        try:
            got = 0 if raw is None else int(str(raw).strip())
        except (TypeError, ValueError):
            # An old empty marker (before 2026-08-20): sent, count unknown -
            # never replay rounds that were already reported. Writes are atomic
            # now, so for a day still being judged only a bug gets here, and it
            # suppresses every further interim that day: say so, once.
            if _INTERIM_SAID.get(day) != str(raw):
                log.warning("临时日报标记 interim:%s 不是条数（%.40r），按已发处理，今天不再推临时日报",
                            day, raw)
                _INTERIM_SAID.clear()
                _INTERIM_SAID[day] = str(raw)
            return 10**6
        _INTERIM_SAID.pop(day, None)
        return got

    def mark_interim_sent(self, day: str, covered: int = 1) -> None:
        # Atomic: the machine is hard power-cut twice a day, and a torn write
        # leaves an empty marker. interim_covered reads empty as "sent, count
        # unknown" and returns 10**6, which silently suppresses every further
        # interim report that day - a failure that looks exactly like a quiet
        # afternoon.
        self.store.set("marks", f"interim:{day}", str(covered))

    def mark_report_sent(self, day: str) -> None:
        self.store.set("marks", f"report:{day}",
                       datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))

    # The day before a banner goes live, say something in the group. Recorded by
    # "game + start time", not by day - keyed by day, two games rotating banners
    # on the same day would only ever get one announcement out.
    def banner_announced(self, key: str) -> bool:
        return self.store.get("marks", f"banner:{key}") is not None

    def mark_banner_announced(self, key: str) -> None:
        self.store.set("marks", f"banner:{key}",
                       datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))


