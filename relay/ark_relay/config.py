"""Configuration and data structures.

Everything the relay needs comes from environment variables (or a .env file),
so the same code runs unchanged on the Windows box and on a cloud server.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The monitored machine runs on Asia/Shanghai; the operator lives in Asia/Tokyo.
# Every human-facing timestamp must say which clock it is on, so keep both.
SERVER_TZ = timezone(timedelta(hours=8), "服务器")
USER_TZ = timezone(timedelta(hours=9), "东京")


def both_clocks(dt: datetime) -> str:
    """Render one instant on both clocks, always dated.

        08-15 09:00（东京 10:00）

    The two zones are an hour apart, so around midnight they fall on different
    days. When that happens the Tokyo date is spelled out too, otherwise a
    reader has no way to tell which day is meant:

        08-15 23:30（东京 08-16 00:30）
    """
    srv = dt.astimezone(SERVER_TZ)
    usr = dt.astimezone(USER_TZ)
    if srv.date() == usr.date():
        return f"{srv:%m-%d %H:%M}（东京 {usr:%H:%M}）"
    return f"{srv:%m-%d %H:%M}（东京 {usr:%m-%d %H:%M}）"


# Every env lookup below MUST be lazy (default_factory). Dataclass field
# defaults are evaluated at import time, which happens before .env is loaded -
# reading os.environ eagerly here silently yields empty config.
def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_path(name: str, default: str | None = None) -> Path | None:
    raw = os.environ.get(name, default)
    return Path(raw) if raw else None


@dataclass
class Config:
    mode: str = "local"  # "local" (on the game box) or "server" (cloud)

    # Where AUTO-MAS writes one JSON + one .log per run.
    history_dir: Path | None = field(
        default_factory=lambda: _env_path("ARK_HISTORY_DIR")
    )
    # AUTO-MAS install root; used to read tomorrow's plan out of its config.
    automas_dir: Path | None = field(
        default_factory=lambda: _env_path("ARK_AUTOMAS_DIR")
    )
    # Relay's own state: which runs have been handled, plus the daily ledger.
    state_dir: Path = field(
        default_factory=lambda: _env_path("ARK_STATE_DIR", "./ark-state")  # type: ignore[arg-type]
    )

    poll_seconds: int = field(default_factory=lambda: _env_int("ARK_POLL_SECONDS", 300))

    # Push channels. Empty string = channel disabled.
    serverchan_key: str = field(default_factory=lambda: _env("SERVERCHAN_KEY"))
    wecom_corpid: str = field(default_factory=lambda: _env("WECOM_CORPID"))
    wecom_secret: str = field(default_factory=lambda: _env("WECOM_SECRET"))
    wecom_agentid: str = field(default_factory=lambda: _env("WECOM_AGENTID"))
    wecom_touser: str = field(default_factory=lambda: _env("WECOM_TOUSER", "@all"))

    # Wording only - never judgment. See docs/04-中继设计.md §7.
    # "openai" covers DeepSeek and anything else speaking the OpenAI chat API;
    # "anthropic" is api.anthropic.com, which mainland China cannot reach.
    llm_provider: str = field(default_factory=lambda: _env("ARK_LLM_PROVIDER", "openai"))
    llm_base_url: str = field(
        default_factory=lambda: _env("ARK_LLM_BASE_URL", "https://api.deepseek.com")
    )
    llm_key: str = field(default_factory=lambda: _env("ARK_LLM_KEY"))
    llm_model: str = field(default_factory=lambda: _env("ARK_LLM_MODEL", "deepseek-chat"))

    # Take over shutdown from AUTO-MAS. Its own AfterAccomplish powers the box
    # off within seconds of a queue finishing, which the relay's poll can never
    # beat - so the daily report never got sent. With this on, set AUTO-MAS's
    # AfterAccomplish to NoAction and let the relay power down once it has
    # actually delivered everything.
    shutdown_after_run: bool = field(
        default_factory=lambda: _env("ARK_SHUTDOWN_AFTER_RUN", "0") == "1")
    # Never power off within this many seconds of the relay starting. Guards
    # against a boot -> immediate-shutdown loop if state is ever inconsistent.
    shutdown_min_uptime: int = field(
        default_factory=lambda: _env_int("ARK_SHUTDOWN_MIN_UPTIME", 600))

    # The last scheduled run of the day; the daily report goes out after it.
    # Server (Beijing) time, "HH:MM".
    last_run_after: str = field(default_factory=lambda: _env("ARK_LAST_RUN_AFTER", "21:30"))

    def validate(self) -> list[str]:
        """Return a list of problems, empty if the config is usable."""
        problems: list[str] = []
        if self.mode == "local":
            if not self.history_dir:
                problems.append("ARK_HISTORY_DIR 未设置（AUTO-MAS 的 history 目录）")
            elif not self.history_dir.is_dir():
                problems.append(f"ARK_HISTORY_DIR 不存在: {self.history_dir}")
        if not (self.serverchan_key or self.wecom_corpid):
            problems.append("没有配置任何推送渠道（SERVERCHAN_KEY 或 WECOM_*）")
        if self.wecom_corpid and not (self.wecom_secret and self.wecom_agentid):
            problems.append("企业微信缺少 WECOM_SECRET 或 WECOM_AGENTID")
        return problems


@dataclass
class RunRecord:
    """One AUTO-MAS run, parsed from history/<date>/<user>/<HH-MM-SS>.json."""

    run_id: str  # stable: "<date>/<user>/<HH-MM-SS>"
    script: str  # "MAA" | "MaaEnd" | "未知"
    user: str
    started: datetime
    finished: datetime
    ok: bool
    failed_tasks: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    log_path: Path | None = None
    # True only when start/finish came from the log's own timestamps. The
    # filename/mtime fallback is off by hours on this install, so a duration
    # derived from it must not be presented as fact.
    duration_known: bool = True

    @property
    def duration_min(self) -> int:
        return max(0, round((self.finished - self.started).total_seconds() / 60))

    @property
    def sanity(self) -> int | None:
        v = self.raw.get("sanity")
        return v if isinstance(v, int) else None

    @property
    def sanity_full_at(self) -> str:
        return str(self.raw.get("sanity_full_at") or "").strip()

    @property
    def drops(self) -> dict:
        d = self.raw.get("drop_statistics")
        return d if isinstance(d, dict) else {}

    @property
    def recruits(self) -> dict:
        r = self.raw.get("recruit_statistics")
        return r if isinstance(r, dict) else {}
