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
    """Write via temp file + os.replace: a reader sees either the old file or
    the new one, never a truncated one. Configs AUTO-MAS cannot start without
    are written through here.
    """
    atomic_write_bytes(path, text.encode("utf-8") if newline is None
                       else text.replace("\n", newline).encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Same as above, for bytes (`.ps1` files need a BOM; `.py` files are code).

    The one implementation of "temp file + fsync + replace" in the relay
    (test_atomic_write.py checks no other copy exists). The temp file is
    removed when the write fails.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def mas_base() -> str:
    """Base URL of the AUTO-MAS backend. **Must be a function, never a
    module-level constant.**

    A module-level constant is evaluated before .env is loaded (see the comment
    below), so `ARK_MAS_PORT` would be ignored. Every caller in the relay gets the
    address from here.
    """
    return f"http://127.0.0.1:{os.environ.get('ARK_MAS_PORT', '36163')}"


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

    # The pipe to the phone. Both empty = the whole feature is off.
    phone_topic: str = field(default_factory=lambda: _env("ARK_PHONE_TOPIC"))
    phone_pin: str = field(default_factory=lambda: _env("ARK_PHONE_PIN"))

    # Skland pass token, needed for the Endfield banner line at the end of the
    # daily report. Empty = that line is omitted.
    # The Wuthering Waves and Arknights banners need no token at all, see
    # banners.py.
    skland_token: str = field(default_factory=lambda: _env("SKLAND_TOKEN"))

    # Push channels. Empty string = channel disabled.
    serverchan_key: str = field(default_factory=lambda: _env("SERVERCHAN_KEY"))
    wecom_corpid: str = field(default_factory=lambda: _env("WECOM_CORPID"))
    wecom_secret: str = field(default_factory=lambda: _env("WECOM_SECRET"))
    wecom_agentid: str = field(default_factory=lambda: _env("WECOM_AGENTID"))
    wecom_touser: str = field(default_factory=lambda: _env("WECOM_TOUSER", "@all"))
    # WeCom group bot: a webhook URL with no trusted-IP list, so it works from
    # any machine on rotating consumer broadband - unlike the self-built app
    # above, which answers errcode=60020 the day the IP changes.
    # The URL contains its own key: treat the whole thing as a secret.
    wecom_bot_url: str = field(default_factory=lambda: _env("WECOM_BOT_URL"))
    # Tencent Cloud COS for evidence bundles (evidence.py). All four or nothing:
    # bucket in the 「name-appid」 form (ark-evidence-1250000000), region such as
    # ap-shanghai. Without them evidence goes out through the WeCom app as file
    # messages (20 MB parts, media kept 3 days), and gofile only as a last resort.
    cos_secret_id: str = field(default_factory=lambda: _env("COS_SECRET_ID"))
    cos_secret_key: str = field(default_factory=lambda: _env("COS_SECRET_KEY"))
    cos_bucket: str = field(default_factory=lambda: _env("COS_BUCKET"))
    cos_region: str = field(default_factory=lambda: _env("COS_REGION"))

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

    # Take over shutdown from AUTO-MAS: AUTO-MAS's own AfterAccomplish powers the
    # box off within seconds of a queue finishing, before the daily report is
    # sent. With this on, AUTO-MAS's AfterAccomplish is set to NoAction and the
    # relay powers down once it has delivered everything.
    shutdown_after_run: bool = field(
        default_factory=lambda: _env("ARK_SHUTDOWN_AFTER_RUN", "0") == "1")
    # Send an interim report just before powering off whenever the day's real
    # report has not gone out yet, so a morning round is heard about before the
    # evening. On by default.
    report_before_shutdown: bool = field(
        default_factory=lambda: _env("ARK_REPORT_BEFORE_SHUTDOWN", "1") == "1")
    # The interim summary after each finished daytime round (kind 2 in
    # docs/NOTIFICATIONS.md), separate from report_before_shutdown. On by default.
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
    # Where MAA is installed. Needed to read MAA's **own** asst.log - AUTO-MAS's
    # history log has no subtask-level failures, so the whole base-management
    # task can collapse without it showing up there.
    maa_dir: Path | None = field(
        default_factory=lambda: _env_path("ARK_MAA_DIR")
    )

    # The last scheduled run of the day; the daily report goes out after it.
    # Server (Beijing) time, "HH:MM".
    last_run_after: str = field(default_factory=lambda: _env("ARK_LAST_RUN_AFTER", "21:30"))

    def __post_init__(self) -> None:
        """Fill `maaend_dir` from AUTO-MAS when the env var is unset.

        Also `maa_dir`. AUTO-MAS knows both install paths (plan.script_dir), so
        neither has to be configured; resolving here gives every consumer of
        Config the same paths. Import is deferred: `plan` imports this module.
        """
        if not self.automas_dir:
            return
        try:
            from ark_relay.core import plan  # noqa: PLC0415 - circular at module level
            if not self.maaend_dir:
                self.maaend_dir = plan.script_dir(self.automas_dir, "MaaEnd")
            if not self.maa_dir:
                self.maa_dir = plan.script_dir(self.automas_dir, "MAA")
        except Exception:  # noqa: BLE001 - resolution must never break startup
            self.maaend_dir = self.maaend_dir or None
            self.maa_dir = self.maa_dir or None

    def validate(self) -> list[str]:
        """Return a list of problems, empty if the config is usable."""
        problems: list[str] = []
        if not self.history_dir:
            problems.append("ARK_HISTORY_DIR 未设置（AUTO-MAS 的 history 目录）")
        elif not self.history_dir.is_dir():
            problems.append(f"ARK_HISTORY_DIR 不存在: {self.history_dir}")
        if not (self.serverchan_key or self.wecom_corpid or self.wecom_bot_url):
            problems.append("没有配置任何推送渠道（WECOM_BOT_URL、SERVERCHAN_KEY 或 WECOM_*）")
        elif not self.wecom_bot_url:
            # Alarms are routed to the group robot first (notify._GROUP_ORDER);
            # a missing robot is reported as a config problem.
            problems.append("没有配置群机器人（WECOM_BOT_URL）——通知只发群机器人，没有它一条都送不到")
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
    # Superseded by the next attempt, not a failure: AUTO-MAS lists
    # 「游戏更新成功，即将重启任务」 among genuine faults in `_OKWW_BUILTIN_FATAL`
    # (`task/Okww/AutoProxy.py:50-54`), and a real result record follows it.
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
    """The AUTO-MAS master config directory that contains `marker`.

    Before a script runs, AUTO-MAS copies
    `<automas>/data/<script id>/Default/ConfigFile/` wholesale into that
    script's own config directory, **unconditionally** (`AutoProxy.py:514-515`,
    unrelated to `IfQuickConfig`). So anything edited on the script's side is
    gone by the next run, and this is the only place a change survives.

    Script ids are not fixed, so the directory is identified by a marker file:
    `DailyTask.json` for OK-WW, `mxu-MaaEnd.json` for MaaEnd.


    **The script-side copy is not written.** AUTO-MAS's
    `app/task/Okww/AutoProxy.py:365-374`: while the configured `Mode` is not
    「直控」 (this machine is on 「脚本」), it runs `copytree(master -> OK-WW's
    configs)`, replacing the whole directory, outside the IfQuickConfig branch.
    Writing the master alone is enough, and a hand-written copy would hide a
    failed master write. To see the config actually in effect:
    `scripts/mac/lib/okww_effective.py`.
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


# ---------------------------------------------------------------- process names
# The one list of "what counts as the fleet running"; every check reads it. A
# list blind to a process reports "nothing is running", and that answer is acted
# on (the phone page shows idle, a script is dispatched on top of a running one).
#
# Two facts every one of these lists has to know:
#   * MaaEnd has no process of its own - AUTO-MAS's python drives it in-process,
#     so Endfield.exe stands in for a MaaEnd run.
#   * OK-WW does not run as ok-ww.exe. That is only the pyappify launcher and it
#     does not exist at all on an automated run; what runs is pythonw.exe with
#     working/main.py on its command line, so a name-only check is blind to it and
#     the game (Client-Win64-Shipping.exe) is the visible evidence.
#
# It lives in config.py rather than a module of its own because self-update never
# creates files: a new module reaches the machine only through a deploy.

# Games and emulators. Seeing any of these means something is being played.
GAME_PROCS: tuple[str, ...] = (
    "Endfield.exe",                 # Endfield itself; also the evidence that MaaEnd is running
    "Client-Win64-Shipping.exe",    # Wuthering Waves itself
    "Wuthering Waves.exe",          # its launcher
    "dnplayer.exe",                 # LDPlayer; Arknights lives inside it
)

# The scripts themselves.
SCRIPT_PROCS: tuple[str, ...] = (
    "MAA.exe",
    "MaaEnd.exe",
    "ok-ww.exe",                    # launcher only; absent on an automated run, see above
)

ORCHESTRATOR_PROC = "AUTO-MAS.exe"

# What a "is anything running" check must be able to see.
BUSY_PROCS: tuple[str, ...] = SCRIPT_PROCS + GAME_PROCS

# A python process with this on its command line is OK-WW itself.
OKWW_CMDLINE = "ok-ww"
PYTHON_HOSTS: tuple[str, ...] = ("pythonw.exe", "python.exe")


# ---------------------------------------------------------------- one-shot flags
# The patched OK-WW checks for this file and skips stamina farming entirely while
# it is there. It is set by hand (weekly boss tests) and must be deleted afterwards;
# while it exists, tomorrow's plan says stamina is not farmed (plan._okww_farm_bit).
NO_STAMINA_FARM_FLAG = r"C:\ProgramData\ark-relay\state\no-stamina-farm.flag"


def no_stamina_farm() -> bool:
    """Is the hand-set "do not spend any stamina" flag in place?"""
    from pathlib import Path as _P  # noqa: PLC0415
    import os as _os  # noqa: PLC0415
    root = _os.environ.get("ARK_STATE_DIR")
    if root:
        return (_P(root) / "no-stamina-farm.flag").exists()
    return _P(NO_STAMINA_FARM_FLAG).exists()
