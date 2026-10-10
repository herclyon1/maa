"""Where run records come from, and how they serialise for disk.

Only the local source exists now: the relay sits on the game box and reads
history/ directly. The HTTP transport (agent/server split) was removed on
2026-08-20 together with server mode itself - the off-box half of the system
is GitHub Actions reading Tailscale's lastSeen, which needs no transport code
on this machine at all. The payload converters stay: engine uses them to
persist undelivered alerts across restarts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ark_relay.core import collector
from ark_relay.core.config import SERVER_TZ, Config, RunRecord


class Source(Protocol):
    """Where new run records come from."""

    def fetch(self, seen: set[str]) -> list[RunRecord]: ...


class LocalSource:
    """Read AUTO-MAS history straight off the local disk."""

    def __init__(self, cfg: Config):
        if not cfg.history_dir:
            raise ValueError("local 模式需要 ARK_HISTORY_DIR")
        self.root = cfg.history_dir
        # MaaEnd's install: its framework log proves a full bag
        # (collector_maaend._maaend_fail_causes). Config resolves it from
        # AUTO-MAS when ARK_MAAEND_DIR is unset.
        self.maaend_dir = cfg.maaend_dir

    def fetch(self, seen: set[str]) -> list[RunRecord]:
        return collector.scan(self.root, seen, self.maaend_dir)


def record_to_payload(rec: RunRecord) -> dict:
    """Serialise a record for the wire."""
    return {
        "run_id": rec.run_id,
        "script": rec.script,
        "user": rec.user,
        "started": rec.started.isoformat(),
        "finished": rec.finished.isoformat(),
        "ok": rec.ok,
        "failed_tasks": rec.failed_tasks,
        "raw": rec.raw,
        # Carried so a held failure reloaded after a restart (pending is kept on
        # disk) still knows its times came from the filename (UTC+4 clock, hours
        # off), not from the log.
        "duration_known": rec.duration_known,
        # Carried so a record superseded by the next attempt stays one (not a
        # failure) in replays and in the daily report.
        "transitional": rec.transitional,
        "log_tail": "" if (rec.ok or rec.transitional)
                    else collector.log_tail(rec),
    }


def payload_to_record(p: dict) -> RunRecord:
    """Rebuild a record on the receiving side. Log tail rides along separately."""
    rec = RunRecord(
        run_id=str(p["run_id"]),
        script=str(p.get("script") or "未知"),
        user=str(p.get("user") or ""),
        started=datetime.fromisoformat(p["started"]).astimezone(SERVER_TZ),
        finished=datetime.fromisoformat(p["finished"]).astimezone(SERVER_TZ),
        ok=bool(p.get("ok")),
        failed_tasks=list(p.get("failed_tasks") or []),
        raw=dict(p.get("raw") or {}),
        log_path=None,
        # Absent in older payloads: default True.
        duration_known=bool(p.get("duration_known", True)),
        # Absent in older payloads: default False.
        transitional=bool(p.get("transitional", False)),
    )
    return rec
