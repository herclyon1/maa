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

from . import collector
from .config import SERVER_TZ, Config, RunRecord


class Source(Protocol):
    """Where new run records come from."""

    def fetch(self, seen: set[str]) -> list[RunRecord]: ...


class LocalSource:
    """Read AUTO-MAS history straight off the local disk."""

    def __init__(self, cfg: Config):
        if not cfg.history_dir:
            raise ValueError("local 模式需要 ARK_HISTORY_DIR")
        self.root = cfg.history_dir

    def fetch(self, seen: set[str]) -> list[RunRecord]:
        return collector.scan(self.root, seen)


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
        # Must ride along. A record whose times came from the filename rather
        # than the log has an untrustworthy duration - the filename is on a
        # UTC+4 clock here, which is how a report once claimed a run at 05:17
        # on a machine that was powered off. Held failures are persisted to
        # pending.json and reloaded after a restart, and the relay restarts
        # itself for every selfupdate; dropping this flag let the reloaded copy
        # default back to True and present that duration as fact.
        "duration_known": rec.duration_known,
        "log_tail": collector.log_tail(rec) if not rec.ok else "",
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
        # Absent in payloads written before this was carried; True was the
        # effective behaviour then, so keep it as the default rather than
        # marking every pre-existing held record as untrustworthy.
        duration_known=bool(p.get("duration_known", True)),
    )
    return rec
