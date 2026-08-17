"""The only layer that differs between local mode and server mode.

    local   the relay sits on the game box and reads history/ directly
    server  the game box POSTs events here; the relay never touches its disk

Everything above this layer (judgment, ledger, wording, push) is identical,
so moving from local to server means changing a flag, not rewriting logic.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Protocol

from . import collector
from .config import SERVER_TZ, Config, RunRecord

log = logging.getLogger("ark.transport")


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


class QueueSource:
    """Records handed in by the HTTP receiver (server mode).

    The web layer appends; the relay loop drains. Deliberately in-memory:
    anything already drained is recorded in `seen`, and anything not yet
    drained will be re-sent by the agent, which retries until acknowledged.
    """

    def __init__(self) -> None:
        self._pending: list[RunRecord] = []

    def offer(self, rec: RunRecord) -> None:
        self._pending.append(rec)

    def fetch(self, seen: set[str]) -> list[RunRecord]:
        out = [r for r in self._pending if r.run_id not in seen]
        self._pending.clear()
        out.sort(key=lambda r: r.started)
        return out


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
    )
    return rec


class Uploader:
    """Runs on the Windows box in server mode: ships events and heartbeats.

    Retries matter here. The machine is only awake ~3 hours a day; an event
    that fails to upload before shutdown must be re-sent on the next boot,
    which is why the agent keeps its own `seen` file and only marks a record
    once the relay has acknowledged it.
    """

    def __init__(self, base_url: str, token: str = "", timeout: int = 20):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Ark-Token"] = self.token
        req = urllib.request.Request(self.base + path, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    def send_event(self, rec: RunRecord) -> bool:
        try:
            r = self._post("/api/event", record_to_payload(rec))
            return bool(r.get("ok"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("上报事件失败 %s: %s", rec.run_id, exc)
            return False

    def heartbeat(self, note: str = "") -> bool:
        try:
            r = self._post("/api/heartbeat", {
                "at": datetime.now(tz=SERVER_TZ).isoformat(),
                "note": note,
            })
            return bool(r.get("ok"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("心跳失败: %s", exc)
            return False

    def pull_commands(self, wait: float = 0) -> list[dict]:
        """Fetch queued commands to apply on this machine.

        With `wait`, the server holds the request open until a command is
        queued or the wait expires - the agent's doorbell, in place of asking
        on a beat. Returns raw dicts; the applier does whitelist validation.
        Never trust this list - it arrives over the network.
        """
        try:
            url = self.base + "/api/commands"
            if wait:
                url += f"?wait={int(wait)}"
            req = urllib.request.Request(url)
            if self.token:
                req.add_header("X-Ark-Token", self.token)
            with urllib.request.urlopen(req, timeout=self.timeout + wait) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
            cmds = data.get("commands")
            return list(cmds) if isinstance(cmds, list) else []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("拉取指令失败: %s", exc)
            return []

    def report_command(self, cmd_id: str, ok: bool, detail: str) -> None:
        try:
            self._post("/api/command-result",
                       {"id": cmd_id, "ok": ok, "detail": detail})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("回报指令结果失败: %s", exc)


def local_state_dir(cfg: Config) -> Path:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg.state_dir
