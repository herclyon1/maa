"""relay.log: rotated by size, and read across the rotation.

Sizes. MAX_BYTES = 16 MB is about a year of ordinary days at that rate and
still 180 of the busiest one, so a rotation is a rare event - the forensics in
this codebase read months of relay.log at a time (selfupdate.py quotes 521
rounds from 08-16 to 09-18). BACKUPS = 3 bounds the whole thing at 64 MB.

Readers. Five places read relay.log by seeking to its tail: the daily upload
(error_evidence._day_tail), the evidence slice (evidence.slice_log), the
machine checks (machinechecks/system.read_tail, runs._relay_today) and the
daily self-check (selfcheck.daily_section). Right after a rotation the tail
they want is partly in relay.log.1 - the boot checks' "previous session" would
be cut in two - so they all read through tail_bytes, which reaches into
relay.log.1 when the current file is shorter than what was asked for. One
older file is enough: each holds MAX_BYTES, far more than any reader's window.

Windows. A rotation renames relay.log, and Windows refuses to rename a file
another handle holds open without FILE_SHARE_DELETE - Python's own open(),
PowerShell's Get-Content, scp. RotatingFileHandler then drops the record that
triggered the rotation, and every record after it (each one retries the
rename and fails again) until the other handle closes. RelayLogHandler keeps
writing to the current file instead and tries again RETRY_SECONDS later. It
says so through logging (ark.logfile), so errwatch sees it: a WARNING at the
first failure of a streak, INFO at each failed retry. That record is logged
after the handler's own handle() has returned and released its lock - logged
from inside, it would re-enter this handler. The service is the only writer: ARK_LOG_FILE is set inside
its own process (boot_stages._stage_bootstrap), and the command-line entry
(__main__.main) sets up logging before it reads .env, so a hand-run command
never opens relay.log for writing.
"""
from __future__ import annotations

import logging.handlers
import os
import threading
import time
import re
import copy
import fnmatch
import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from ark_relay.core.config import SERVER_TZ, atomic_write_text

_log_logfile = logging.getLogger("ark.logfile")

MAX_BYTES = 16 * 1024 * 1024
BACKUPS = 3
RETRY_SECONDS = 300.0


class RelayLogHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that never loses a record to a failed rotation (see the module docstring)."""

    def __init__(self, filename, max_bytes: int = MAX_BYTES, backups: int = BACKUPS) -> None:
        super().__init__(filename, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        self._retry_at = 0.0
        self._path = os.fspath(filename)
        self._failing = False                 # inside a streak of failed rotations
        self._pending: "tuple[int, str] | None" = None   # (level, message) to log after handle()
        self._reporting = False
        self._pending_lock = threading.Lock()

    def handle(self, record):
        rv = super().handle(record)
        if self._pending is not None and not self._reporting:
            with self._pending_lock:
                pending, self._pending = self._pending, None
            if pending is not None:
                self._reporting = True
                try:
                    _log_logfile.log(*pending)
                finally:
                    self._reporting = False
        return rv

    def shouldRollover(self, record) -> bool:  # noqa: N802 - logging's name
        if self._retry_at and time.monotonic() < self._retry_at:
            return False
        return bool(super().shouldRollover(record))

    def _roll(self) -> None:
        """RotatingFileHandler.doRollover with the steps reordered so a refused
        rename of relay.log moves nothing.
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.backupCount > 0:
            base = self.baseFilename
            hold = base + self.HOLD
            if os.path.exists(hold):
                # A rotation interrupted between its steps (the service killed):
                # finish it before starting this one, so the held lines are kept.
                self._shift_in(hold)
            # self.rotate is the stdlib's hook for the rename (a test makes it refuse).
            self.rotate(base, hold)
            if os.path.exists(hold):
                try:
                    self._shift_in(hold)
                except OSError:
                    os.replace(hold, base)
                    raise
        if not self.delay:
            self.stream = self._open()

    HOLD = ".rotating"

    def _shift_in(self, hold: str) -> None:
        """.N-1 -> .N down to .1 -> .2, then `hold` -> .1."""
        base = self.baseFilename
        for i in range(self.backupCount - 1, 0, -1):
            src, dst = f"{base}.{i}", f"{base}.{i + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(hold, f"{base}.1")

    def doRollover(self) -> None:  # noqa: N802 - logging's name
        try:
            self._roll()
        except OSError as exc:
            self._retry_at = time.monotonic() + RETRY_SECONDS
            if self.stream is None:
                self.stream = open(self._path, "a", encoding="utf-8")
            # Logged by handle() once this record is written (see the module
            # docstring): the group hears it once per streak, not every retry.
            if not self._failing:
                self._failing = True
                self._pending = (logging.WARNING,
                                 f"relay.log 轮转没成（{exc}），接着写在原文件里，"
                                 f"{RETRY_SECONDS / 60:.0f} 分钟后再试；一直不成的话它会一直变大")
            else:
                self._pending = (logging.INFO, f"relay.log 轮转还是没成（{exc}），"
                                               f"{RETRY_SECONDS / 60:.0f} 分钟后再试")
        else:
            self._retry_at = 0.0
            self._failing = False


def tail_bytes(path, nbytes: int) -> "tuple[bytes, bool]":
    """The last `nbytes` of the log at `path`, reaching into `<path>.1` when the
    current file holds fewer (it was rotated recently).

    Returns (data, cut): `cut` is True when older bytes exist before `data`, so
    its first line may be partial. Raises OSError when the current file cannot
    be read, as open() would; a missing or unreadable `<path>.1` is no older part.
    """
    p = Path(path)
    with p.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        start = max(0, size - nbytes)
        fh.seek(start)
        data = fh.read()
    if start > 0:
        return data, True
    need = nbytes - len(data)
    try:
        with Path(f"{p}.1").open("rb") as fh:
            fh.seek(0, 2)
            osize = fh.tell()
            ostart = max(0, osize - need)
            fh.seek(ostart)
            older = fh.read()
    except OSError:
        return data, False
    if older and not older.endswith(b"\n"):
        older += b"\n"
    return older + data, ostart > 0


_log_techlog = logging.getLogger("ark.techlog")

RED = "🔴"
DONE = "✅"
RED_LINE = re.compile(r"^🔴 (R-\d{8}-\d{4}-\d+) (.*)$")
DONE_LINE = re.compile(r"^✅ (R-\d{8}-\d{4}-\d+) 已处理（(.+?)）")


def tech_dir(state_dir: "Path | str | None" = None) -> Path:
    """<state dir>/../tech - next to state/ and relay.log on the machine."""
    base = Path(state_dir or os.environ.get("ARK_STATE_DIR", "./ark-state"))
    return base.resolve().parent / "tech"


def path_for(day: str, state_dir=None) -> Path:
    return tech_dir(state_dir) / f"{day}.md"


def append(day: str, heading: str, text: str, *, state_dir=None, now: "datetime | None" = None) -> bool:
    """Append one section to the day's file. False (and a log line) when it cannot be written."""
    text = (text or "").strip()
    if not text:
        return True
    at = (now or datetime.now(tz=SERVER_TZ)).strftime("%H:%M")
    try:
        p = path_for(day, state_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"\n## {at} {heading}\n{text}\n")
        return True
    except OSError as exc:
        _log_techlog.warning("技术日志写不进 %s：%s", day, type(exc).__name__)
        return False


_ids = threading.Lock()


def add_red(day: str, heading: str, texts: "list[str]", *, state_dir=None,
            now: "datetime | None" = None) -> list[str]:
    """Append one section of red items, each with an id not used yet.

    Numbering from 1 on every call would write the same id twice for two calls in
    the same minute, and one `handled` would clear both; this continues after the
    highest number already written for that minute. Returns the ids written ([]
    when nothing was written)."""
    at = now or datetime.now(tz=SERVER_TZ)
    texts = [" ".join(str(t).split())[:400] for t in texts if str(t).strip()]
    if not texts:
        return []
    stamp = at.strftime("%Y%m%d-%H%M")
    with _ids:
        old = ""
        at_day = at.strftime("%Y-%m-%d")
        prev_day = (at - timedelta(days=1)).strftime("%Y-%m-%d")
        for d in dict.fromkeys((day, at_day, prev_day)):
            try:
                old += path_for(d, state_dir).read_text(encoding="utf-8", errors="replace") + "\n"
            except OSError:
                pass
        used = [int(m.group(1)) for m in re.finditer(rf"^{RED} R-{stamp}-(\d+) ", old, re.M)]
        start = max(used, default=0)
        lines = [f"{RED} R-{stamp}-{start + i} {t}" for i, t in enumerate(texts, 1)]
        if not append(day, heading, "\n".join(lines), state_dir=state_dir, now=at):
            return []
    return [ln.split(" ", 2)[1] for ln in lines]


SELF_HEAL = "自愈待查"


def self_heal(where: str, why: str, *, state_dir=None, now: "datetime | None" = None) -> list[str]:
    """One red item for a fault that fixed itself and so stayed out of the group."""
    at = now or datetime.now(tz=SERVER_TZ)
    return add_red(at.strftime("%Y-%m-%d"), SELF_HEAL, [f"{SELF_HEAL}：{where}：{why or '没记下原因'}"],
                   state_dir=state_dir, now=at)


def unhandled(text: str) -> list[tuple[str, str]]:
    """(id, text) of every red item in `text` without a handled line for it."""
    reds: dict[str, str] = {}
    done: set[str] = set()
    for line in text.splitlines():
        if m := RED_LINE.match(line.strip()):
            reds.setdefault(m.group(1), m.group(2))
        elif m := DONE_LINE.match(line.strip()):
            done.add(m.group(1))
    return [(i, t) for i, t in reds.items() if i not in done]


def handled_line(item_id: str, commit: str) -> str:
    return f"{DONE} {item_id} 已处理（{commit}）"


log = logging.getLogger("ark.statestore")

FILE = "state.json"
STRAY_TMP_AGE_S = 24 * 3600
SECTIONS = ("marks", "modes", "weekly", "versions", "updates", "queues")

# The field table: section -> {key (may contain a * wildcard): description}.
# Changing this changes the contract - change docs/STATE-MODEL.md along with it.
FIELDS: dict[str, dict[str, str]] = {
    "weekly": {
        "annihilation": "剿灭：{done_week, restore_to}",
        "garden": "周常乐园：{done_week}",
        "boss": "周本：{index, name, done_week}",
    },
    "marks": {
        "report:*": "某天日报已发（值=时刻）",
        "interim:*": "某天临时日报覆盖到第几条记录",
        "techlog:*": "某天日报的技术部分哪几段已写进技术日志（值=标题列表；report.write_daily_techlog）",
        "banner:*": "某个卡池的开服播报已发（键=游戏+开始时刻）",
        "alerted:*": "某天已经告警过的事（键=日期，值=告警标识列表）",
        "noted:*": "某天已经记进日报的不关机原因（10-10 23:22 起不再写，旧的留着无害）",
        "handled_boot": "这次开机里中继看到运行记录落账：{boot, at}（重启后同一次开机接着判关机；shutdown.note_handled）",
        "relay_poweroff": "中继自己发出关机命令的时刻（看门服务代发停止前状态时据此认出是中继自己关的机；取消倒计时清掉；shutdown.relay_poweroff_recorded）",
        "relay_poweroff_why": "中继自己关机的原因：{why, shift, due, finished, at}（哪一班、几点跑完；最后一跳心跳带给 App；取消倒计时清掉；shutdown.poweroff_note）",
        "shutdown_forfeit": "哪一班的关机机会已过：{shift, why, at}（班跑完后补跑或游戏更新把关机拖住了，这一班不再关机，下一班照常；shutdown._note_forfeit）",
        "shiftcheck_shift": "收工体检查过的最后一班的排期时刻（每班只查一次，中继重启后不重查；shiftcheck.maybe_run）",
    },
    "modes": {
        "skip_next_shutdown": "「下次跑完不关机」标记还没用上（一次性，人按的；下一趟早班/晚班跑完时用掉）",
        "shutdown_skipped": "哪一次关机机会已经跳过（机会标识；调试模式、倒计时里按的、用掉的「下次跑完不关机」或故障留机锁写的；手动关调试模式只清调试模式自己写的那条，其余的留着）",
        "debug_until": "调试模式到什么时候（YYYY-MM-DD HH:MM）",
        "alarm_hold": "故障留机锁：{until, boot, reason, created_at, at, boot_at}（本班有未修完群报警时挂起，防机器自动/提前关机）",
        "alarm_hold_cleared_at": "最近一次解锁故障留机锁的北京时间高水位（ISO +08:00，防迟到外部留机指令僵尸复锁）",
    },
    "versions": {
        "announced_notes": "上一条「已更新」推送的说明原文（一模一样就不再推）",
        "okww": "上次贴补丁时 OK-WW 的版本",
        "maaend": "上次预更新确认过的 MaaEnd 版本",
        "code": "本机中继代码版本",
        "announced": "已经播报过更新的那个版本，避免重复推送",
        "scoreboard": "每个代码版本跑过几趟、失败几趟（日报末尾那一行的来源）",
    },
    "updates": {
        "preupdate": "预更新今天跑过没有：{day, at, clean}",
        "gameupdate": "游戏客户端更新这次开机跑过没有：{boot, at}",
        "gameupdate_pending": "待更新登记：{游戏: 为什么}",
        "gameupdate_off": "游戏更新总开关（真=整套不动）",
        "arknights_client": "记下的明日方舟客户端版本：{version, at}",
        "arknights_prewarmed": "装完后进游戏到过登录界面的明日方舟版本：{version, at}",
        "queue_skips": "今天在队列里跳过的队列项（为更新、按队列指令，sources 记着谁要跳），记着原运行日，一项一条",
        "maintenance_windows": "今天各游戏的停服维护时段：{游戏: {start,end,why}}",
        "stagegate_skips": "关卡门为 MAA 走不到的关卡从队列里拿掉、还没放回的记录，列表（stagegate.py）",
        "stagegate_dues": "关卡门最近几天每一班查过的结论：{日期: {队列/HH:MM: {verdict, stage, why, pulled, others}}}",
        "essence_filler_pending": "基质刷取目标都齐了、等没有任务在跑时切成刷垫子的那趟记录：{run_id, day, at}（essence.on_record 写，essence.step 切完或切不成清掉）",
        "essence_filler_done_for": "上一趟已经处理过切刷垫子的运行标识（同一趟记录重新记账时不再切；essence.step）",
        "protocol_space_guard": "MaaEnd 母本当前启用的理智任务开关记录：{active: [...]}（用于发现「设置脚本」意外取消协议空间勾选并自动恢复）",
        # Leftovers only: nothing writes these any more, and since 840c3f4c nothing
        # switches their tasks back on or drops them either (machine check #63 reads them).
        "maaend_disabled_1_5_3": "旧记录：9 月初为 1.5.3 关掉的 MaaEnd 任务 {disabled 或 tasks, since}；开机开回那一步 10-13 已删，留下的不动",
        "maaend_reenable_next_boot": "旧记录：补跑时关掉的 MaaEnd 任务 {tasks}；开机开回那一步 10-13 已删，留下的不动",
        "maaend_disabled_spmed": "旧记录：9 月初关掉的应急理智加强剂 {tasks, since}；开机开回那一步 10-13 已删，留下的不动",
    },
    "queues": {
        "echo_farm": "正在刷的声骸 boss：{boss, name, weekly, until, started, started_s（到秒）, saved, restarts, restarted；按主词条刷时还有 target_stat, target_set, target_count 和 tick 写的 已出, 总捡, 未读出, 参考剩余分钟}",
        "pending": "还没推出去的失败告警：{脚本|账号: 记录}",
        "phone_seen": "手机指令去重用的消息 id 列表",
        "phone_mark": "手机信箱读到的最新 ntfy 时间（unix 秒），下次开机据此算读不到的时段",
        "phone_blind": "手机信箱读不到的时段（关机超过 ntfy 12 小时缓存）：[{from, to, boot}]，最多留 10 段",
        "inbox_version": "待办清单处理到哪一版",
        "skip_restore": "跳过模式停用了哪个队列，用于过后恢复（一个队列存一条，两个以上存列表）",
        "skip_day:*": "某天要跳过哪个队列（值=队列名；两个以上是队列名列表）",
        "skip_done:*": "某天跳过后已恢复的队列（队列名列表），漏跑和超时检查据此不把那天那趟算漏跑",
        "channels_down": "哪些推送渠道正挂着，避免每次重启都重报一遍",
        "given_up": "连续处理失败、先不记账的运行记录：{运行标识: {code, at}}，代码版本变了（部署）再试一轮（engine.tick）",
    },
}

# Old file -> (section, key, how to read). How: json = the whole file is JSON;
# text = plain text, stripped.
# Wildcard migration: filename pattern -> (section, key template, how to read).
# Whatever `*` captures is filled into the {} of the key template.
LEGACY_GLOB = {
    "report-*.sent": ("marks", "report:{}", "flag"),
    "interim-*.sent": ("marks", "interim:{}", "text"),
    "banner-*.sent": ("marks", "banner:{}", "flag"),
    "alerted-*.json": ("marks", "alerted:{}", "json"),
    "skip-*.flag": ("queues", "skip_day:{}", "text"),
}

LEGACY = {
    "annihilation.json": ("weekly", "annihilation", "json"),
    "pending.json": ("queues", "pending", "json"),
    "skip-next-shutdown.flag": ("modes", "skip_next_shutdown", "flag"),
    "preupdate.json": ("updates", "preupdate", "json"),
    "gameupdate.json": ("updates", "gameupdate", "json"),
    "gameupdate-pending.json": ("updates", "gameupdate_pending", "json"),
    "gameupdate-off.flag": ("updates", "gameupdate_off", "flag"),
    "arknights-client.json": ("updates", "arknights_client", "json"),
    "queue-skips.json": ("updates", "queue_skips", "json"),
    "maaend-disabled-for-1.5.3.json": ("updates", "maaend_disabled_1_5_3", "json"),
    "maaend-reenable-next-boot.json": ("updates", "maaend_reenable_next_boot", "json"),
    "maaend-disabled-spmed.json": ("updates", "maaend_disabled_spmed", "json"),
    "channels-down.json": ("queues", "channels_down", "json"),
    "phone-seen.json": ("queues", "phone_seen", "json"),
    "inbox-version.txt": ("queues", "inbox_version", "text"),
    "skip-restore.json": ("queues", "skip_restore", "json"),
    "maintenance-today.json": ("updates", "maintenance_windows", "json"),
    "shutdown-skipped.txt": ("modes", "shutdown_skipped", "text"),
    "garden.json": ("weekly", "garden", "json"),
    "weeklyboss.json": ("weekly", "boss", "json"),
    "okww-version.txt": ("versions", "okww", "text"),
    "code-version.txt": ("versions", "code", "text"),
    "announced-version.txt": ("versions", "announced", "text"),
    "maaend-version.txt": ("versions", "maaend", "text"),
    "debug-until.txt": ("modes", "debug_until", "text"),
}


def _read_legacy(f: Path, how: str):
    """Read an old file into a value per `how`. Returns None if unreadable (the caller skips it)."""
    try:
        raw = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        log.warning("旧状态文件 %s 读不出来，跳过", f.name)
        return None
    if how == "json":
        try:
            return json.loads(raw)
        except ValueError:
            log.warning("旧状态文件 %s 不是 JSON，跳过", f.name)
            return None
    if how == "flag":
        return True         # the file existing is itself the value
    return raw.strip()


def _registered(section: str, key: str) -> bool:
    return any(fnmatch.fnmatchcase(key, pat) for pat in FIELDS.get(section, {}))


# Directories whose old files this process has already swept. The sweep runs
# once per process, not only when state.json is missing: old files can sit next
# to an existing state.json, and an unmigrated `report-*.sent` would make
# yesterday's daily report count as unsent and go out again.
_SWEPT: set = set()

# Unreadable state.json files already said and copied aside: path -> the mtime
# that was. A StateStore is built fresh at most call sites (phone state, notify,
# inbox ...), so an instance cache alone would say it on every read; module-level,
# like _SWEPT. Dropped once the file reads again.
_CORRUPT_SAID: dict[str, float] = {}

# The last state.json content this process read or wrote, per path: what a plain read
# answers with while the file refuses to be read (a Windows lock), for the StateStore
# built fresh at most call sites as for the long-lived ones. Never written to disk
# from here: a write reads the file itself (_load fresh).
_LAST_GOOD: dict[str, dict] = {}
# Every write this process made, per file: a cached copy read before another
# instance's write is stale even when the file's mtime reads the same (two writes
# inside the clock's resolution, or a clock step back). _load serves its cache only
# when no write came in between (清单-1108 A-07).
_WRITE_SEQ: dict[str, int] = {}

UNREAD_RETRY_S = 45
UNREAD_WARN_S = 600
# path -> [time.monotonic() of the first refusal of the current run, its WARNING sent].
_UNREAD: dict[str, list] = {}


def _refused(path: Path, exc: OSError) -> None:
    """A read of `path` was refused for good this time: start or go on with its run of
    refusals; one INFO line when the run starts, one WARNING once it lasts UNREAD_WARN_S."""
    now = time.monotonic()
    run = _UNREAD.get(str(path))
    if run is None:
        run = _UNREAD[str(path)] = [now, False]
        log.info("%s 这次读不出来（%s），先用上次读到的；读回来之前写不进去，每 %d 秒再读一次",
                 path.name, type(exc).__name__, UNREAD_RETRY_S)
    if not run[1] and now - run[0] >= UNREAD_WARN_S:
        run[1] = True
        log.warning("中继自己的状态文件 %s 已经 %d 分钟读不出来（%s: %s）。这期间只能用上次读到的内容，"
                    "要写进去的报警记号、运行记录和手机指令都写不进去；读回来后自动接着用",
                    path.name, int((now - run[0]) // 60), type(exc).__name__, exc)


def _read_back(path: Path) -> None:
    """A read of `path` got through: its run of refusals, if any, is over (one INFO line)."""
    run = _UNREAD.pop(str(path), None)
    if run is not None:
        log.info("%s 读回来了（读不出来持续了约 %d 分钟%s）", path.name,
                 int((time.monotonic() - run[0]) // 60), "，之前已报过一条「读不出来」" if run[1] else "")


def refused_since(path: Path) -> "float | None":
    """time.monotonic() of the first refused read of `path` in the current run of
    refusals, None while it reads (engine.next_deadline)."""
    run = _UNREAD.get(str(path))
    return run[0] if run else None


def set_aside(path: Path, mtime: float, said: "dict[str, float] | None" = None) -> "str | None":
    """Copy an unreadable state file aside as <name>.corrupt-<mtime> before anything
    overwrites it; the one line saying where it went (for the caller's log line), or
    None when this mtime of it was set aside already (`said`, default _CORRUPT_SAID:
    path -> mtime; the caller drops the path once the file reads again)."""
    said = _CORRUPT_SAID if said is None else said
    if said.get(str(path)) == mtime:
        return None
    said[str(path)] = mtime
    copy = path.with_name(f"{path.name}.corrupt-{datetime.fromtimestamp(mtime):%Y%m%d-%H%M%S}")
    try:
        shutil.copy2(path, copy)
        return f"旧内容已另存为 {copy.name}"
    except OSError as exc:
        return f"旧内容没能另存（{type(exc).__name__}），下一次写入会把它盖掉"


# A Windows lock on a state file is waited out this long before a read or write of it
# is given up (seconds between tries): an antivirus scan or backup tool holding the
# file open makes os.replace fail with ERROR_ACCESS_DENIED (5) or
# ERROR_SHARING_VIOLATION (32), which Python raises as PermissionError, for a moment.
LOCK_WAITS = (0.05, 0.15, 0.3)
_LOCK_WINERRORS = (5, 32, 33)


def locked(exc: OSError) -> bool:
    """`exc` is how Windows refuses a file another handle holds open."""
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in _LOCK_WINERRORS


def write_waiting(path: Path, text: str, write=None, waits=None) -> None:
    """write(path, text) (default: this module's atomic_write_text, looked up at call
    time, as tests replace it), tried again after each of `waits` (default LOCK_WAITS)
    while the file is locked (locked()); raises the last OSError when it never gets
    through, or at once for any other OSError."""
    write = write or atomic_write_text
    for wait in (*(LOCK_WAITS if waits is None else waits), None):
        try:
            write(path, text)
            return
        except OSError as exc:
            if wait is None or not locked(exc):
                raise
            time.sleep(wait)

# Held around every load-modify-write of state.json. The phone listen thread
# (queues.phone_seen, modes.* from live commands) and the engine thread write the
# same file through StateStore instances of their own; without one lock for the
# process, the slower writer overwrote the other's key with the copy it had read.
# Re-entrant: _sweep_legacy runs inside __init__, which a caller may reach while
# holding it.
_WRITE_LOCK = threading.RLock()
_WRITE_DEPTH = threading.local()


def in_store_write() -> bool:
    """Whether the current thread is inside a StateStore write lock."""
    return getattr(_WRITE_DEPTH, "n", 0) > 0


class StateStore:
    _seq = -1           # the _WRITE_SEQ value the cached copy was read at

    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.path = self.dir / FILE
        self._data: dict | None = None
        self._mtime = -1.0
        if str(self.dir) not in _SWEPT:
            _SWEPT.add(str(self.dir))
            try:
                with _WRITE_LOCK:
                    _WRITE_DEPTH.n = getattr(_WRITE_DEPTH, "n", 0) + 1
                    try:
                        self._sweep_legacy()
                    finally:
                        _WRITE_DEPTH.n -= 1
            except OSError:
                # Swept again by the next StateStore: an unmigrated report-*.sent makes
                # that day's report count as unsent. Only state.json's own read or write
                # raises here (a lock outlasting LOCK_WAITS): a legacy file that cannot
                # be read or moved is skipped inside.
                _SWEPT.discard(str(self.dir))
                log.warning("清扫旧状态文件时出错，下一次再试", exc_info=True)
            self._sweep_stray_tmp()

    def _sweep_stray_tmp(self) -> None:
        """Remove state.json.<random>.tmp (and the old fixed state.json.tmp) older
        than STRAY_TMP_AGE_S. A write cut off between mkstemp and the replace leaves
        one, and nothing else ever removes it. A live write's temp file is seconds
        old, so the age keeps this off it."""
        cut = time.time() - STRAY_TMP_AGE_S
        for f in self.dir.glob(FILE + ".*tmp"):
            try:
                if f.is_file() and f.stat().st_mtime < cut:
                    f.unlink()
                    log.info("删掉了没写完的状态临时文件: %s", f.name)
            except OSError:
                log.warning("删不掉没写完的状态临时文件 %s，下次进程启动再试", f.name, exc_info=True)

    # ---------- read ----------
    def _stat_mtime(self, waits: tuple[float, ...]) -> tuple[float, OSError | None]:
        """Return (st_mtime, None), (-1.0, None) when missing, or (-1.0, exc) when refused."""
        for wait in (*waits, None):
            try:
                return self.path.stat().st_mtime, None
            except FileNotFoundError:
                return -1.0, None
            except OSError as exc:
                if wait is not None and locked(exc):
                    time.sleep(wait)
                    continue
                return -1.0, exc
        return -1.0, None

    def _load(self, fresh: bool = False) -> dict:
        """state.json as a dict. `fresh` rereads the file even when its mtime
        matches the cached copy: a write must start from what is on disk, and
        another instance may have written within the clock's resolution."""
        seq = _WRITE_SEQ.get(str(self.path), 0)
        last = self._data if self._data is not None else _LAST_GOOD.get(str(self.path))
        waits = LOCK_WAITS if fresh or last is None else ()
        m, stat_err = self._stat_mtime(waits)
        if stat_err is not None:
            _refused(self.path, stat_err)
            if fresh:
                raise stat_err
            # Not cached, _mtime kept: the next read tries the file again.
            return last if last is not None else {sec: {} for sec in SECTIONS}
        # While its reads are refused the cached copy is not served: each read tries the
        # file once more, so the run of refusals ends (or reaches its WARNING) on a read.
        if (self._data is not None and m == self._mtime and not fresh and self._seq == seq
                and str(self.path) not in _UNREAD):
            return self._data
        data: dict = {}
        if m >= 0:
            for wait in (*waits, None):
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                except OSError as exc:
                    # Gone since the stat (FileNotFoundError) is no different: the
                    # next call's stat tells a file removed for good from a replace
                    # caught midway.
                    if wait is not None and locked(exc):
                        time.sleep(wait)
                        continue
                    _refused(self.path, exc)
                    if fresh:
                        raise
                    # Not cached, _mtime kept: the next read tries the file again.
                    return last if last is not None else {sec: {} for sec in SECTIONS}
                except ValueError:
                    self._set_aside(m)
                    data = {}
                else:
                    if not isinstance(data, dict):
                        self._set_aside(m)
                        data = {}
                    else:
                        _CORRUPT_SAID.pop(str(self.path), None)
                _read_back(self.path)
                break
        else:
            _read_back(self.path)
        for s in SECTIONS:
            data.setdefault(s, {})
        self._data, self._mtime, self._seq = data, m, seq
        _LAST_GOOD[str(self.path)] = data
        return data

    def _set_aside(self, mtime: float) -> None:
        """Copy an unreadable state.json aside before anything overwrites it.

        The next set()/pop() writes the near-empty fallback over state.json, so
        without a copy pending holds, weekly gates and debug mode are gone for
        good. Once per unreadable mtime: this is read on every tick."""
        where = set_aside(self.path, mtime)
        if where:
            log.warning("state.json 读不出来，按空处理；%s", where, exc_info=True)

    def section(self, name: str) -> dict:
        if name not in SECTIONS:
            raise KeyError(f"没有 {name!r} 这一段")
        return dict(self._load()[name])

    def get(self, section: str, key: str, default=None, *, fresh: bool = False):
        return self._load(fresh=fresh).get(section, {}).get(key, default)

    # ---------- write ----------
    def set(self, section: str, key: str, value) -> None:
        if not _registered(section, key):
            raise KeyError(f"state.{section}.{key} 没在字段表里登记，拒绝写入（见 docs/STATE-MODEL.md）")
        with _WRITE_LOCK:
            _WRITE_DEPTH.n = getattr(_WRITE_DEPTH, "n", 0) + 1
            try:
                data = self._writable()
                data[section][key] = value
                self._flush(data)
            finally:
                _WRITE_DEPTH.n -= 1

    def update(self, section: str, key: str, change) -> None:
        """state[section][key] = change(its value on disk, None when unset), the read
        and the write under one hold of _WRITE_LOCK. A caller that get()s, changes and
        set()s builds the value from a read outside the lock (and from the cached copy):
        two such writers racing put back the copy each had read, and the second
        dropped the first's change - one alarm's day mark lost that way (10-17)."""
        if not _registered(section, key):
            raise KeyError(f"state.{section}.{key} 没在字段表里登记，拒绝写入（见 docs/STATE-MODEL.md）")
        with _WRITE_LOCK:
            _WRITE_DEPTH.n = getattr(_WRITE_DEPTH, "n", 0) + 1
            try:
                data = self._writable()
                data[section][key] = change(data[section].get(key))
                self._flush(data)
            finally:
                _WRITE_DEPTH.n -= 1

    def pop(self, section: str, key: str) -> None:
        with _WRITE_LOCK:
            _WRITE_DEPTH.n = getattr(_WRITE_DEPTH, "n", 0) + 1
            try:
                data = self._writable()
                if key in data.get(section, {}):
                    del data[section][key]
                    self._flush(data)
            finally:
                _WRITE_DEPTH.n -= 1

    def atomic(self, section: str, fn):
        """Read-modify-write a whole `section` dict under one hold of _WRITE_LOCK.
        Validates every added/modified key against FIELDS and flushes once iff changed."""
        if section not in SECTIONS:
            raise KeyError(f"没有 {section!r} 这一段")
        with _WRITE_LOCK:
            _WRITE_DEPTH.n = getattr(_WRITE_DEPTH, "n", 0) + 1
            try:
                data = self._writable()
                sec = data[section]
                before = copy.deepcopy(sec)
                res = fn(sec)
                if sec != before:
                    for k, v in sec.items():
                        if k not in before or before[k] != v:
                            if not _registered(section, k):
                                raise KeyError(f"state.{section}.{k} 没在字段表里登记，拒绝写入（见 docs/STATE-MODEL.md）")
                    self._flush(data)
                return res
            finally:
                _WRITE_DEPTH.n -= 1

    def _writable(self) -> dict:
        """state.json as on disk (_load fresh), its sections copied: a change is made
        to the copy, which becomes the cached one only once _flush wrote it. Changed
        in place, a write that failed left the cache answering with what never reached
        the file - an alarm's day mark that a lock refused read as set (10-17)."""
        # A deep copy: with each section copied only one level down, a list or table
        # inside a key was shared with the cache, and changing it in place changed
        # the cache before the write went through (清单-1108 A-07).
        return copy.deepcopy(self._load(fresh=True))

    def _flush(self, data: dict) -> None:
        """Write `data` as state.json; a Windows lock on it is waited out first
        (write_waiting), so a scan holding it a moment does not make set() / pop()
        raise - a day mark of an alarm that went out was lost that way (10-17)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        write_waiting(self.path, json.dumps(data, ensure_ascii=False, indent=1))
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = -1.0
        self._data = data
        _WRITE_SEQ[str(self.path)] = self._seq = _WRITE_SEQ.get(str(self.path), 0) + 1
        _LAST_GOOD[str(self.path)] = data

    # ---------- migration ----------

    def _sweep_legacy(self) -> None:
        """Migrate in whatever old state files are still on disk. Once per process, per directory.

        A key that already has a value is not overwritten: state.json is
        authoritative, the old file is just leftovers nobody cleaned up.
        After migrating, the old file is renamed `.migrated` and kept, to be
        deleted after a few stable days.
        """
        if not self.dir.is_dir():
            return
        data = None
        moved = []

        def take(section: str, key: str, value) -> bool:
            nonlocal data
            if value in ("", {}, None) and value is not False:
                return False
            if data is None:
                data = self._writable()
            if key in data.get(section, {}):
                return False        # already has a value: state.json wins
            data.setdefault(section, {})[key] = value
            return True

        for name, (section, key, how) in LEGACY.items():
            f = self.dir / name
            if not f.is_file():
                continue
            value = _read_legacy(f, how)
            if value is None:
                continue
            take(section, key, value)
            moved.append(name)
        for pattern, (section, tmpl, how) in LEGACY_GLOB.items():
            head, _, tail = pattern.partition("*")
            for f in sorted(self.dir.glob(pattern)):
                if f.name in LEGACY:
                    continue        # migrated by full name above (skip-next-shutdown.flag collides with skip-*.flag)
                stem = f.name[len(head):-len(tail)] if tail else f.name[len(head):]
                value = _read_legacy(f, how)
                if value is None:
                    continue
                # Empty content is kept as an empty string: an empty
                # `interim-*.sent` marker means "sent, count unknown". Turning it
                # into "1" would read as "only covered 1 record", and rounds
                # already reported that day would be replayed.
                if value == "" and how == "text":
                    if data is None:
                        data = self._writable()
                    data.setdefault(section, {}).setdefault(tmpl.format(stem), "")
                    moved.append(f.name)
                    continue
                take(section, tmpl.format(stem), value)
                moved.append(f.name)
        if not moved:
            return
        if data is not None:
            self._flush(data)
        for name in moved:
            try:
                # replace, not rename: a .migrated of the same name may already be
                # there, and on Windows rename fails when the target exists.
                (self.dir / name).replace(self.dir / f"{name}.migrated")
            except OSError:
                log.warning("旧状态文件 %s 收不走，下次启动再试（不影响读写）", name)
        log.info("状态已迁入 state.json：%s", "、".join(sorted(moved)))
