"""What handle.py gives the machine checks (machinecheck.py, event 「run」) about
one handled record: the outcome checks, the WARNING / ERROR lines and alarms
written while it was handled, whether it was a test run, and the MaaEnd update
restarts around it.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import timedelta
from pathlib import Path

from ark_relay.core import ledger as core
from ark_relay.core.config import SERVER_TZ, RunRecord
from ark_relay.features.verify import outcome

# Same logger as handle.py: relay.log names these lines "ark.handle".
log = logging.getLogger("ark.handle")


# What _verify_outcome found for each record it checked, until the record's machine
# checks have read it (_judge_run pops it): the outcome checks, the summary and, for
# OK-WW, the nest settings they were judged with.
_OUTCOME: dict[str, dict] = {}


def _judged(rec: RunRecord, checks: list, who: str, **extra) -> str | None:
    """outcome.summarize(checks, who), keeping the checks for the machine checks."""
    msg = outcome.summarize(checks, who)
    _OUTCOME[rec.run_id] = dict(extra, checks=list(checks), msg=msg)
    return msg


def _alert_days() -> list[str]:
    """Yesterday and today in Beijing time, as the alarm copies name their day files."""
    from ark_relay.features.alarm import alertlog  # noqa: PLC0415
    now = alertlog.beijing()
    return [(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")]


def _alert_file(state_dir, day: str) -> Path:
    return Path(state_dir) / "alerts" / f"{day}.jsonl"


def _alert_sizes(state_dir) -> dict[str, int]:
    """{day: bytes} of the alarm copies (alertlog.py) as they are now; 0 for a day with none."""
    out: dict[str, int] = {}
    for day in _alert_days():
        try:
            out[day] = _alert_file(state_dir, day).stat().st_size
        except OSError:
            out[day] = 0
    return out


def _alerts_since(state_dir, marks: dict[str, int]) -> list[dict]:
    """The alarm copies written after `marks` (_alert_sizes): what went to the group since."""
    rows: list[dict] = []
    for day in dict.fromkeys([*marks, *_alert_days()]):
        try:
            data = _alert_file(state_dir, day).read_bytes()
        except OSError:
            continue
        for line in data[marks.get(day, 0):].decode("utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


class _RunWatch(logging.Handler):
    """What happened while one record was handled, for its machine checks: which
    records were held before, the relay's own WARNING / ERROR lines on this thread
    (each reaches the group through errwatch unless it says it was delivered
    already or recovered), and the alarms whose copies landed in state/alerts.

    Never raises: not knowing leaves the checks less to read, never the record unbooked."""

    def __init__(self, eng):
        super().__init__(level=logging.WARNING)
        self.eng = eng
        self.thread = threading.get_ident()
        self.errors: list[dict] = []
        self.held_before: dict[str, RunRecord] = {}
        self.marks: dict[str, int] = {}
        self._logger = None

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread:
            return
        try:
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            self.errors.append({"level": record.levelname, "logger": record.name,
                                "msg": record.getMessage()[:500],
                                "pushed": bool(getattr(record, errwatch.PUSHED, False)),
                                "recovered": bool(getattr(record, errwatch.RECOVERED, False))})
        except Exception:  # noqa: BLE001 - a log line must never fail because of this
            pass

    def __enter__(self):
        try:
            self.held_before = {r.run_id: r for r in list(getattr(self.eng, "_pending", {}).values())}
            self.marks = _alert_sizes(self.eng.cfg.state_dir)
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            self._logger = logging.getLogger(errwatch.ARK)
            self._logger.addHandler(self)
        except Exception:
            log.debug("上机核对的记录器没装上", exc_info=True)
        return self

    def __exit__(self, *exc) -> bool:
        if self._logger is not None:
            self._logger.removeHandler(self)
        return False

    def alerts(self) -> list[dict]:
        try:
            return _alerts_since(self.eng.cfg.state_dir, self.marks)
        except Exception:
            log.warning("读报警抄送出错，上机核对按没看到报警处理", exc_info=True)
            return []


def _test_run(eng, rec: RunRecord) -> bool:
    """Inside a test window run-one.sh marked (core.split_test): not an unattended run."""
    from ark_relay.features.report import report  # noqa: PLC0415
    windows = report.test_windows(eng.cfg.state_dir)
    return bool(core.split_test([{"started": rec.started.isoformat()}], windows)[1])


def _update_restarts(eng, rec: RunRecord) -> dict:
    """{run_id: {version, started, done, held}} for every MaaEnd update restart on the
    ledger of the record's day and the day before (this record included): `done` is
    the round of the same shift that got everything done (unresolved.done_in_shift),
    '' when there is none; `held` whether it is still held for a later push."""
    from ark_relay.features.alarm import unresolved  # noqa: PLC0415
    day = rec.started.astimezone(SERVER_TZ)
    rows: dict[str, dict] = {}
    for d in ((day - timedelta(days=1)).strftime("%Y-%m-%d"), day.strftime("%Y-%m-%d")):
        for e in eng.state.read_ledger(d):
            if e.get("script") == "MaaEnd" and (e.get("raw") or {}).get("maaend_update_restart"):
                rows[str(e.get("run_id"))] = e
    held = {r.run_id for r in eng._pending.values()}
    out: dict = {}
    for rid, e in rows.items():
        r = unresolved._row_rec(e)
        if r.started is None:
            continue
        try:
            done = unresolved.done_in_shift(eng, r)
        except Exception:  # the check then has nothing to judge about it
            log.warning("查不了 %s 那一班有没有做完的那趟，上机核对跳过它", rid, exc_info=True)
            continue
        out[rid] = {"version": str(e["raw"]["maaend_update_restart"]), "started": r.started.isoformat(),
                    "done": done, "held": rid in held}
    return out
