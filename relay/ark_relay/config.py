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

    What gets written here is the config AUTO-MAS cannot start without. A
    corrupted QueueConfig.json makes the machine "safely" fail into scheduling
    nothing at all, leaving a lone .bak beside it. os.replace guarantees a
    reader sees either the old file or the new one, never a truncated one.
    """
    atomic_write_bytes(path, text.encode("utf-8") if newline is None
                       else text.replace("\n", newline).encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Same as above, for bytes. `.ps1` files need a BOM and `.py` files are
    code; both go through here.

    2026-09-08: five hand-copied "temp file + replace" snippets were folded into
    this one function. Each did its own thing - some skipped fsync, some left the
    temp file behind on failure, and they all reported errors differently. Five
    spellings of one operation, where fixing one fixes none of the others.

    This machine takes a hard power cut **exactly once a day**: the smart plug
    cuts power at 08:40 and restores it at 08:45, and at that moment the machine
    is already off (it shut itself down the previous night when the queue
    finished), so no file is being written. The relay's own `shutdown /s /f` is a
    clean shutdown and the OS flushes its caches.
    So "the power dies mid-write" essentially cannot happen on this machine - the
    operator corrected an overstatement of mine on 2026-09-08. fsync stays because
    it is the right thing to do and costs one syscall, not because there is a
    known trap here.
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
    below), which turns `ARK_MAS_PORT` into "set it and nothing happens" - harder
    to track down than today's partial effect.

    Before 2026-09-08 this address existed in four copies inside the relay:
    commands.py, snapshot.py and engine.py each hardcoded 36163, and only the
    pre-update path honoured `ARK_MAS_PORT` - so changing the port took effect in
    one place out of four.
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
    # Where MAA is installed. Needed to read MAA's **own** asst.log - AUTO-MAS's
    # history log has no subtask-level failures, so the whole base-management
    # task can collapse without it showing up there.
    maa_dir: Path | None = field(
        default_factory=lambda: _env_path("ARK_MAA_DIR")
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

    def __post_init__(self) -> None:
        """Fill `maaend_dir` from AUTO-MAS when the env var is unset.

        `plan.script_dir` already says it exists so the MaaEnd path never has
        to be configured twice — but only `service.py` ever called it, and
        `Engine` read `cfg.maaend_dir` raw. With `ARK_MAAEND_DIR` unset (it
        never was set on the machine), that stayed None, and
        `_archive_maaend_evidence` hit `if not src.is_dir(): return` on its
        very first line — silently, every single time, since the day it was
        written. That is how the on_error screenshots from the three failed
        sword-selection duels on the morning of 2026-08-28 were lost: MaaEnd
        wipes its debug directory on every restart, and the code meant to
        rescue those screenshots had never once run.

        Resolving here fixes every consumer at once instead of one call site.
        Import is deferred: `plan` imports this module.
        """
        if not self.automas_dir:
            return
        try:
            from . import plan  # noqa: PLC0415 - circular at module level
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
    # This run is not a "failure", it was "superseded by the next one".
    # AUTO-MAS lumps 「游戏更新成功，即将重启任务」 in with genuine faults inside
    # `_OKWW_BUILTIN_FATAL` (see `task/Okww/AutoProxy.py:50-54`), so every client
    # update reports one failure. That is not a fault: a real result record
    # follows immediately after it.
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


    **Does the script-side copy count? No - do not write it by hand.**
    (Settled on 2026-09-08 by reading the source; two contradictory claims
    existed before that.)
    AUTO-MAS's `app/task/Okww/AutoProxy.py:365-374`: as long as the user's
    configured `Mode` is not 「直控」 (this machine is on 「脚本」), it runs
    `copytree(master -> OK-WW's configs)` - **replacing the whole directory,
    outside the IfQuickConfig branch, unconditionally**.
    So writing the master alone is enough; writing the copy by hand is not only
    redundant, it masks a failed master write - when both sides agree you cannot
    tell whether the master took effect or the copy covered for it.
    (The 2026-08-31 case of "master 90, copy 80" was a late master write: it was
    written at 16:20, after that day's run, so at run time the master still held
    the old value and the copy naturally got the old value too. Nothing failed to
    copy.)
    To see the config actually in effect: `scripts/mac/lib/okww_effective.py`.
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
# One list of "what counts as the fleet running", instead of five. Five places
# each carried their own hard-coded set and no two agreed: estop.sh's regex,
# dispatch_guard's two tuples, snapshot's dict, the queue monitor's tuple,
# watch-run.sh's findstr. Three could not see Wuthering Waves' own process or the
# emulator, and one was still looking for MuMuPlayer, removed from this machine on
# 2026-08-24. A blind list does not report an error - it reports "nothing is
# running", and that is the answer that gets acted on: the phone page shows idle
# while the game is playing, and a script is dispatched on top of a running one.
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
# creates files: a new module reaches this machine only through a deploy, and
# until then every reader of it is silently degraded.

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
