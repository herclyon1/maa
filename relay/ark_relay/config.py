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


def atomic_write_text(path: Path, text: str, newline: str | None = None) -> None:
    """Write via temp file + os.replace, so a power cut mid-write can never
    leave a truncated file behind.

    This machine powers itself off twice a day - including via the relay's own
    `shutdown /s /t 60`, which does not wait for in-flight work - and every
    config writer here edits files AUTO-MAS cannot run without. A truncated
    QueueConfig.json fails "safe" into a machine that schedules nothing, with
    only a .bak sitting next to the corpse.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline=newline) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


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

    # Fallback scan interval, used ONLY when no directory watcher could be
    # started (watch.py / pywin32 both unavailable). On every deployed path
    # records arrive as directory-change events and this number never ticks.
    poll_seconds: int = field(default_factory=lambda: _env_int("ARK_POLL_SECONDS", 300))

    # Push channels. Empty string = channel disabled.
    serverchan_key: str = field(default_factory=lambda: _env("SERVERCHAN_KEY"))
    wecom_corpid: str = field(default_factory=lambda: _env("WECOM_CORPID"))
    wecom_secret: str = field(default_factory=lambda: _env("WECOM_SECRET"))
    wecom_agentid: str = field(default_factory=lambda: _env("WECOM_AGENTID"))
    wecom_touser: str = field(default_factory=lambda: _env("WECOM_TOUSER", "@all"))
    # 企业微信群机器人: a webhook URL with no trusted-IP list, so it works from
    # any machine on rotating consumer broadband - unlike the self-built app
    # above, which answers errcode=60020 the day the IP changes.
    # The URL contains its own key: treat the whole thing as a secret.
    wecom_bot_url: str = field(default_factory=lambda: _env("WECOM_BOT_URL"))

    # Wording only - never judgment. See relay/README.md, "Where the model's
    # authority ends".
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
    # Send an interim report just before powering off, whenever the day's real
    # report has not gone out yet. Without it the morning queue finishes, the
    # machine goes dark, and nothing is heard until the evening - so a morning
    # that farmed nothing looks exactly like a morning that farmed fine.
    # On by default; set to 0 once the daily summary alone is trusted.
    report_before_shutdown: bool = field(
        default_factory=lambda: _env("ARK_REPORT_BEFORE_SHUTDOWN", "1") == "1")
    # The interim summary after each finished daytime round - kind 2 in
    # docs/NOTIFICATIONS.md, which calls it a test-phase feature that can be
    # turned off once the daily report alone is trusted, without affecting the
    # daily report. There was no switch for it: report_before_shutdown only
    # governs the pre-shutdown backstop, so the specified behaviour was not
    # actually available. On by default, which is the behaviour up to now.
    interim_report: bool = field(
        default_factory=lambda: _env("ARK_INTERIM_REPORT", "1") == "1")

    # How long after a queue's time to wait before declaring one of its scripts
    # missing. The morning queue runs MAA first (~20 min) and only then MaaEnd
    # (~25 min), so a healthy MaaEnd record can legitimately be 45+ minutes
    # late; alerting at the same mark as "nothing ran" would fire every morning.
    partial_grace: int = field(
        default_factory=lambda: _env_int("ARK_PARTIAL_GRACE_MIN", 75))
    # Stop looking this long after the queue's time. Past it the run is written
    # off - continuing to check would re-alert on yesterday's shape forever.
    partial_window: int = field(
        default_factory=lambda: _env_int("ARK_PARTIAL_WINDOW_MIN", 240))
    # Never power off within this many seconds of the relay starting. Guards
    # against a boot -> immediate-shutdown loop if state is ever inconsistent.
    shutdown_min_uptime: int = field(
        default_factory=lambda: _env_int("ARK_SHUTDOWN_MIN_UPTIME", 600))

    # Where queued config changes are fetched from, and the MaaEnd install they
    # may target. Empty URL falls back to the project's own repo path.
    inbox_url: str = field(default_factory=lambda: _env("ARK_INBOX_URL"))
    okww_dir: Path | None = field(
        default_factory=lambda: _env_path("ARK_OKWW_DIR")
    )
    maaend_dir: Path | None = field(
        default_factory=lambda: _env_path("ARK_MAAEND_DIR")
    )

    # The times the machine is woken for. At each one the relay asks what is
    # scheduled *for that time*; nothing scheduled means this boot has no
    # purpose and it powers off. Kept separate from the queue times on purpose:
    # a paused queue disappears from the schedule, but the wake that existed
    # for it does not, and that is exactly the case worth catching.
    check_times: str = field(
        default_factory=lambda: _env("ARK_CHECK_TIMES", "09:00,21:30"))

    # The last scheduled run of the day; the daily report goes out after it.
    # Server (Beijing) time, "HH:MM".
    last_run_after: str = field(default_factory=lambda: _env("ARK_LAST_RUN_AFTER", "21:30"))

    def validate(self) -> list[str]:
        """Return a list of problems, empty if the config is usable."""
        problems: list[str] = []
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
    # 这一轮不是"失败"，是"被下一轮取代了"。AUTO-MAS 把「游戏更新成功，
    # 即将重启任务」和真故障一起塞进 `_OKWW_BUILTIN_FATAL`（见
    # `task/Okww/AutoProxy.py:50-54`），于是客户端更新一次就报一次失败。
    # 那不是故障：它后面紧跟着一条真正的结果记录。
    transitional: bool = False

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

def master_config_dir(automas_dir: "str | Path | None", marker: str) -> "Path | None":
    """AUTO-MAS 母本目录里含 `marker` 的那一个。

    脚本跑之前 AUTO-MAS 会把 `<automas>/data/<脚本id>/Default/ConfigFile/`
    整个拷到脚本自己的配置目录，**无条件**（`AutoProxy.py:514-515`，
    和 `IfQuickConfig` 无关）。所以在脚本那边改的东西下一轮就没了，
    唯一长期生效的地方就是这里。

    脚本 id 不固定，按标志文件认：OK-WW 是 `DailyTask.json`，
    MaaEnd 是 `mxu-MaaEnd.json`。
    """
    if not automas_dir:
        return None
    root = Path(automas_dir) / "data"
    if not root.is_dir():
        return None
    for sid in sorted(root.iterdir()):
        d = sid / "Default" / "ConfigFile"
        if (d / marker).is_file():
            return d
    return None
