"""The relay loop, shared by local mode and server mode.

Given a Source of run records, this decides what to say and when to say it:

    failure       push immediately
    success       book it silently, no push
    end of day    push one daily report (日报)

Judgment happens here in plain Python. The model is asked for wording only,
after the verdict is already fixed.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import config, texts
from ark_relay.features import handle, handle as missed
from ark_relay.features import modes
from ark_relay.features import selfcheck as tape
from ark_relay.core import plan
from ark_relay.features import report
from ark_relay.features import shutdown
from ark_relay.core.config import SERVER_TZ, Config, RunRecord
from ark_relay.core.ledger import State
from ark_relay.features.handle import MISSED_GRACE_MIN
from ark_relay.core.notify import Notifier
from ark_relay.core.collector import Source

log = logging.getLogger("ark.engine")

# Engine steps not taken while hard-locked (features/hardlock.py): each starts a run or
# writes into AUTO-MAS, the games or COS.
LOCKED_STEPS = frozenset({
    "协议空间开关保护", "明日方舟活动提醒", "需求表", "关卡门", "重试上限", "补跑", "补活跃", "基质刷垫子", "队列后更新", "周常门",
})
# Short-lived cache for `_scripts_running`; see the comment on that method.
_SCRIPTS_CACHE: dict = {"at": -1e9, "val": False, "gen": 0}
_SCRIPTS_CACHE_LOCK = threading.Lock()
_SCRIPTS_TTL = 3.0
# An OK-WW process whose log is older than this is hung and no longer counts as running
# (_okww_up): eight times its longest quiet stretch at work, the 120 s wait_until.
OKWW_QUIET_MIN = 15


def forget_scripts_cache() -> None:
    """Drop the cached `_scripts_running` answer, so the next ask goes to AUTO-MAS.

    For whoever has just started something (a queued phone order applied, a
    make-up dispatched): within the same tick the shutdown decision or the
    make-up step would otherwise reuse the 「nothing runs」 read before it, and
    power off or dispatch on top of the run that has just been started.
    """
    with _SCRIPTS_CACHE_LOCK:
        _SCRIPTS_CACHE["at"] = -1e9
        _SCRIPTS_CACHE["val"] = False
        _SCRIPTS_CACHE["gen"] = _SCRIPTS_CACHE.get("gen", 0) + 1

_RUNTIME_PATH = "/api/dispatch/runtime-snapshot"   # the only confirmed GET endpoint
_SNAPSHOT_DONE = {"完成", "异常", "失败", "跳过", "中止", "取消"}
_TASK_DONE = {"success", "error", "cancelled"}
# Consecutive runtime-snapshot timeouts count as "busy" only up to this cap (covers
# transient event-loop blocks like MaaEnd's 10 s startup setup on 2026-11-23 without
# letting a permanently deadlocked AUTO-MAS hold missed-run checks and shutdown forever).
_SNAP_TIMEOUT_CAP_S = 180.0
_SNAP_TIMEOUT: dict = {"since": None, "capped_logged": False}
_SNAP_TIMEOUT_LOCK = threading.Lock()
_SNAP_STATE = threading.local()


def _is_timeout(exc: BaseException) -> bool:
    """True when talking to AUTO-MAS timed out (listener is up, event loop is busy)."""
    if isinstance(exc, TimeoutError):
        return True
    return isinstance(getattr(exc, "reason", None), TimeoutError)


def _task_items(task) -> list[dict]:
    """Per-script status dicts ({name, status, ...}) of one runtime-snapshot task.

    AUTO-MAS <= v5.8 kept them at task["task_info"]; v5.9+ moved them into the
    nested task tree at task["task"]["scripts"] (order + data[uid]["info"]).
    Returns [] when a task was just dispatched and has no script items yet.
    """
    if not isinstance(task, dict):
        return []
    if "task_info" in task:
        return [i for i in (task.get("task_info") or []) if isinstance(i, dict)]
    tree = task.get("task")
    scripts = tree.get("scripts") if isinstance(tree, dict) else None
    if not isinstance(scripts, dict):
        return []
    data = scripts.get("data")
    if not isinstance(data, dict):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for ref in scripts.get("order") or []:
        uid = ref.get("uid") if isinstance(ref, dict) else None
        if uid and uid in data and uid not in seen:
            seen.add(uid)
            info = data[uid].get("info") if isinstance(data[uid], dict) else None
            if isinstance(info, dict):
                out.append(info)
    for uid, entry in data.items():
        if uid not in seen and isinstance(entry, dict):
            info = entry.get("info")
            if isinstance(info, dict):
                out.append(info)
    return out


def _task_unfinished(task) -> bool:
    """Is this one runtime-snapshot task still unfinished?

    The one criterion shared by `_judge_snapshot` and the red button
    (redbutton._estop_live_tasks), so the two can never disagree about what
    "still running" means.
    """
    info = _task_items(task)
    if not info:
        top = ((task or {}).get("task") or {}).get("info") if isinstance(task, dict) else None
        status = str((top or {}).get("status") or "") if isinstance(top, dict) else ""
        return status not in _TASK_DONE   # just dispatched, no status of any kind yet
    return any(str(item.get("status") or "") not in _SNAPSHOT_DONE for item in info)


def _judge_snapshot(snap) -> bool:
    """Does runtime-snapshot still hold an unfinished task? (Sample shape in the tests.)"""
    return any(_task_unfinished(task) for task in (snap or {}).get("tasks") or [])


def _script_unfinished(snap, name: str) -> bool:
    """Is the script `name` (MAA / OK-WW / MaaEnd) still unfinished in this snapshot?

    Narrower than `_judge_snapshot` on purpose: a held failure of one script only
    has to wait for that script's own retries, not for the rest of the queue.
    """
    for task in (snap or {}).get("tasks") or []:
        info = _task_items(task)
        if not info:
            if _task_unfinished(task):
                return True      # just dispatched, cannot tell which script yet
            continue
        if any(str(item.get("name") or "") == name
               and str(item.get("status") or "") not in _SNAPSHOT_DONE for item in info):
            return True
    return False


def _automas_snapshot():
    """AUTO-MAS's runtime-snapshot, parsed; None when it cannot be asked."""
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    from ark_relay.core.config import mas_base  # noqa: PLC0415
    _SNAP_STATE.timed_out = False
    try:
        with urllib.request.urlopen(mas_base() + _RUNTIME_PATH, timeout=3) as r:
            raw = r.read()
    except Exception as exc:  # noqa: BLE001 - no endpoint -> fall back to the process check
        if _is_timeout(exc):
            log_capped = False
            with _SNAP_TIMEOUT_LOCK:
                now_m = time.monotonic()
                since = _SNAP_TIMEOUT["since"]
                if since is None:
                    since = now_m
                    _SNAP_TIMEOUT["since"] = since
                    _SNAP_TIMEOUT["capped_logged"] = False
                if now_m - since <= _SNAP_TIMEOUT_CAP_S:
                    _SNAP_STATE.timed_out = True
                elif not _SNAP_TIMEOUT["capped_logged"]:
                    _SNAP_TIMEOUT["capped_logged"] = True
                    log_capped = True
            if log_capped:
                log.info("AUTO-MAS 运行快照已连续超时超过 %d 秒，改回查进程表", int(_SNAP_TIMEOUT_CAP_S))
        else:
            with _SNAP_TIMEOUT_LOCK:
                _SNAP_TIMEOUT["since"] = None
                _SNAP_TIMEOUT["capped_logged"] = False
        tape.answer("mas", _RUNTIME_PATH, error=exc)
        return None
    with _SNAP_TIMEOUT_LOCK:
        _SNAP_TIMEOUT["since"] = None
        _SNAP_TIMEOUT["capped_logged"] = False
    tape.answer("mas", _RUNTIME_PATH, body=raw, resp=r)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable answer is no answer, as before
        return None


def _open_other_mode_tasks(automas_dir, snap, now: datetime) -> list:
    """Open non-AutoProxy tasks (e.g. ScriptConfig 「设置脚本」) seen in AUTO-MAS app.log
    that are not already listed in `snap`."""
    if not automas_dir:
        return []
    from ark_relay.features import trigger  # noqa: PLC0415
    listed = {str((task or {}).get("taskId") or "") for task in ((snap or {}).get("tasks") or [])}
    f = Path(automas_dir) / "debug" / "app.log"
    try:
        with f.open("rb") as fh:
            fh.seek(max(0, f.stat().st_size - _APPLOG_TAIL))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    return [
        t for t in trigger.parse(lines)
        if (t.mode != "AutoProxy" and t.ended is None
            and timedelta(0) <= now - t.created <= timedelta(minutes=OTHER_MODE_OPEN_MIN)
            and not any(tid and (t.id == tid or t.id.startswith(tid)) for tid in listed))
    ]


def script_config_open(automas_dir=None, now: "datetime | None" = None) -> bool:
    """True while AUTO-MAS has an open 「设置脚本」 (ScriptConfig) session.

    Checks runtime-snapshot on Windows first (unfinished task with mode == ScriptConfig),
    then falls back to AUTO-MAS debug/app.log so master-config writers refuse to race
    AUTO-MAS's close-session copy-back even when runtime-snapshot omits ScriptConfig.
    """
    cur = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    snap = None
    if config.IS_WINDOWS:
        snap = _automas_snapshot()
        if isinstance(snap, dict):
            for task in snap.get("tasks") or []:
                if str((task or {}).get("mode") or "") == "ScriptConfig" and _task_unfinished(task):
                    return True
    amas = automas_dir or _BUSY_SEEN["automas_dir"] or os.environ.get("ARK_AUTOMAS_DIR")
    return any(t.mode == "ScriptConfig" for t in _open_other_mode_tasks(amas, snap, cur))


def _automas_busy(automas_dir=None, now: "datetime | None" = None):
    """Ask AUTO-MAS whether a task is running. True/False; None when it cannot be asked.

    A timeout means AUTO-MAS's listener is up while its event loop is blocked
    (e.g. MaaEnd's 10 s launch setup on 2026-11-23 10:24:53-10:25:03): treat as
    busy rather than falling through to tasklist before the game process exists.
    Also checks AUTO-MAS debug/app.log for open non-AutoProxy tasks (such as
    ScriptConfig 「设置脚本」) that runtime-snapshot omits, preventing master-config
    overwrite races (R-09).
    """
    _SNAP_STATE.timed_out = False
    snap = _automas_snapshot()
    cur = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    amas = automas_dir or _BUSY_SEEN["automas_dir"] or os.environ.get("ARK_AUTOMAS_DIR")
    if snap is None:
        if getattr(_SNAP_STATE, "timed_out", False):
            log.info("AUTO-MAS 运行快照超时，暂按有脚本在跑处理")
            return True
        if amas and (app_open := _open_other_mode_tasks(amas, None, cur)):
            log.info("AUTO-MAS 日志里有未结束的 %s 任务（%s），按在忙处理",
                     app_open[0].mode, app_open[0].id[:8])
            _note_other_modes(None, True, now=cur, app_tasks=app_open)
            return True
        return None
    busy = _judge_snapshot(snap)
    app_open = []
    if not busy and amas:
        app_open = _open_other_mode_tasks(amas, snap, cur)
        if app_open:
            busy = True
            log.info("AUTO-MAS 运行快照未列，但日志里有未结束的 %s 任务（%s），按在忙处理",
                     app_open[0].mode, app_open[0].id[:8])
    _note_other_modes(snap, busy, now=cur, app_tasks=app_open)
    return busy


def _okww_up() -> bool:
    """Is an OK-WW process up, however it was started (okww_overlay.okww_running is True)?

    AUTO-MAS answers busy only for its own dispatches, and the process fallback knew
    MAA, MaaEnd and Endfield only, so OK-WW started outside AUTO-MAS (okww-task.sh, the
    echo farm's scheduled task) was 「nothing running」: 10-27 a make-up nest run had to
    be held with debug mode or the morning shift's shutdown would have landed mid-run.
    OK-WW exits when its task ends (main.py -e), so its process is the sign; the game
    client can outlive it. An unreadable process list (None) adds nothing.

    A process whose log has been quiet for OKWW_QUIET_MIN is hung, not working: it must
    not keep the machine on all day. The longest quiet stretch of a working run is a
    wait_until of 120 s (10-27 09:23:04-09:25:04, the nest travel); combat logs every
    few seconds. A log that cannot be read leaves the process counted.
    """
    from ark_relay.features.okww_overlay import okww_running  # noqa: PLC0415 - import cycle
    if okww_running() is not True:
        return False
    logs = config.okww_root() / "data" / "apps" / "ok-ww" / "working" / "logs"
    try:
        newest = max(f.stat().st_mtime for f in logs.glob("*.log"))
    except (OSError, ValueError):
        return True
    return time.time() - newest < OKWW_QUIET_MIN * 60


# Where _note_other_modes keeps what it saw and finds AUTO-MAS's app.log; set by
# Engine.__init__ (a process that built no engine notes nothing).
_BUSY_SEEN: dict = {"state_dir": None, "automas_dir": None}
BUSY_FILE = "machinecheck-busy.json"      # read by machinechecks/system.py (#18)
# An app.log task with no end line counts as open for this long after its start.
OTHER_MODE_OPEN_MIN = 30
HANDLE_TRIES = 3
# A given-up record (queues.given_up) is dropped from that list after this many days.
GIVEN_UP_KEEP_DAYS = 30
_APPLOG_TAIL = 512 * 1024


def _note_other_modes(snap, busy: bool, now: "datetime | None" = None,
                      app_tasks: "list | None" = None) -> None:
    """Keep, for machine check #18, what AUTO-MAS's runtime-snapshot said while a
    task of a mode other than AutoProxy (a 设置脚本 session, say) was open: whether it
    was counted as running. A master edit made during such a session is copied over
    when it ends (docs/BACKLOG.md), so it has to count.

    Listed in the snapshot and unfinished, or caught via app.log (`app_tasks`): counted.
    Not listed at all while app.log has its 「创建任务」 line (OTHER_MODE_OPEN_MIN old at
    most) and no end line, with the caller reporting `busy=False`: not counted. One entry
    per task and answer. Never raises."""
    state_dir = _BUSY_SEEN["state_dir"]
    if not state_dir:
        return
    try:
        _note_other_modes_in(Path(state_dir), _BUSY_SEEN["automas_dir"], snap, busy,
                             (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ),
                             app_tasks=app_tasks)
    except Exception:  # evidence for a check; never in the way of the answer
        log.debug("没记下调度程序非代理任务的忙闲", exc_info=True)


def _note_other_modes_in(state_dir: Path, automas_dir, snap, busy: bool, now: datetime,
                         app_tasks: "list | None" = None) -> None:
    import json  # noqa: PLC0415
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    at = now.strftime("%m-%d %H:%M:%S")
    found: list[dict] = []
    for task in (snap or {}).get("tasks") or []:
        tid = str((task or {}).get("taskId") or "")
        mode = str((task or {}).get("mode") or "")
        if mode and mode != "AutoProxy" and _task_unfinished(task):
            states = "、".join(f"{i.get('name')} {i.get('status')}" for i in _task_items(task))
            found.append({"at": at, "task": tid, "mode": mode, "busy": True,
                          "line": f"快照里列着、没完成：{states or '还没有状态'}"})
    if app_tasks:
        for t in app_tasks:
            found.append({"at": at, "task": t.id, "mode": t.mode, "busy": True,
                          "line": f"调度程序日志 {t.created:%H:%M:%S} 创建任务 {t.id[:8]}，"
                                  f"模式 {t.mode}，快照未列但按日志判为在忙"})
    if not busy and automas_dir:
        for t in _open_other_mode_tasks(automas_dir, snap, now):
            found.append({"at": at, "task": t.id, "mode": t.mode, "busy": False,
                          "line": f"调度程序日志 {t.created:%H:%M:%S} 创建任务 {t.id[:8]}，"
                                  f"模式 {t.mode}，触发来源 {t.source}，还没有结束那一行；快照里没有它"})
    if not found:
        return
    path = state_dir / BUSY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    seen = data.get("seen") if isinstance(data, dict) and isinstance(data.get("seen"), list) else []
    known = {(o.get("task"), o.get("busy")) for o in seen if isinstance(o, dict)}
    new = [o for o in found if (o["task"], o["busy"]) not in known]
    if new:
        state_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps({"seen": (seen + new)[-50:]}, ensure_ascii=False, indent=1))


# A skip of a queue (跳过模式, skip_today) that did not take effect, or whose restore
# failed: a failure, so it goes to the group every time it is said. texts.SKIP_MODE,
# which notify routes to the log only, is for the acknowledgements.
SKIP_FAILED = texts.SKIP_FAILED


def skip_failed(state_dir, msg: str) -> bool:
    """Whether a message of modes.process_skip is a failure: modes writes every failed
    engage or restore as a red receipt (ok false) with the same words, for the phone
    page; an acknowledgement is a green receipt or none."""
    text = str(msg)[:200]
    return any(r.get("ok") is False and r.get("text") == text for r in modes.receipts(state_dir))


class Engine:
    def __init__(self, cfg: Config, source: Source, state: State, notifier: Notifier):
        self.cfg = cfg
        self.source = source
        self.state = state
        self.notifier = notifier
        _BUSY_SEEN.update(state_dir=cfg.state_dir, automas_dir=cfg.automas_dir)
        # Hook for the last pull of pending orders before powering off, wired up by
        # service (see _maybe_shutdown). None when running tests standalone, and then
        # nothing is pulled.
        self._before_shutdown = None
        # Hook for sending the phone page a fresh state snapshot, wired up by
        # boot_stages._start_phone_channel. Called after a skip step says
        # something, so its receipt shows without waiting for the next refresh.
        self._push_state = None
        # Hook that applies the phone orders queued while a script ran
        # (boot_stages._make_phone_cmd drain). None in standalone tests.
        self._phone_drain = None
        # runwatch: AUTO-MAS's app.log, read incrementally, and the first-timeout
        # alarms that could not be sent yet (the log line is read only once).
        self._applog = None
        self._unsent_timeouts: list = []
        self._unsent_skips: list = []
        # 「没干完」 alarms (unresolved.py) whose push failed: (day, kind, run_id, title,
        # body), tried again at the top of every _flush_pending; kept on disk with
        # _pending (_persist_pending).
        self._unsent_unresolved: list = []
        # Populated by the HTTP layer in server mode, where the log tail
        # arrives with the payload instead of being read off local disk.
        self.log_tails: dict[str, str] = {}
        # Failures held back until we know whether a retry rescued them.
        # AUTO-MAS retries a failed script up to RunTimesLimit times; alerting
        # on the first attempt turns a self-healing hiccup into a false alarm.
        self._pending: dict[tuple[str, str], RunRecord] = {}
        # Failures that a later retry got past. Still reported, and reported as
        # an unresolved fault - the run survived, the bug did not go away.
        self._recovered: dict[tuple[str, str], RunRecord] = {}
        self._pending_restored = False
        self._fetch_owed = False
        self._restore_pending()
        self._missed_alerted: set[str] = set()
        # run_id -> how many ticks _handle raised on it (tick, HANDLE_TRIES).
        self._handle_fails: dict[str, int] = {}
        self._started_at = datetime.now(tz=SERVER_TZ)
        self._handled_any = False   # nothing ran this session -> nothing to shut down for
        self._shutdown_issued = False  # a countdown is already running; never twice
        self._last_wait_note = ""  # so the guard does not repeat itself every poll
        self._mode_notified: set[str] = set()  # skip-mode messages already pushed
        self._debug_last: bool | None = None  # log mode transitions, not every tick
        from ark_relay.features.annihilation import WeeklyGate  # noqa: PLC0415 - optional feature
        self._annihilation = WeeklyGate(state.dir, cfg.automas_dir)
        # The weekly garden and annihilation are the same shape of problem: something
        # that only needs doing once a week should not be visited every day. The only
        # difference is which switch gets turned off - annihilation's is MAA's, this
        # one's is OK-WW's "Check Weekly Garden" additional task.
        from ark_relay.features.annihilation import GardenGate  # noqa: PLC0415 - optional feature
        # Writes the OK-WW master copy directly, not through the MAS API (that path
        # needs quick-config on, and quick-config is off).
        self._garden = GardenGate(state.dir, cfg.automas_dir)
        from ark_relay.features.weeklyboss import WeeklyBossGate  # noqa: PLC0415 - avoid import cycle
        self._weeklyboss = WeeklyBossGate(state.dir, cfg.automas_dir)

    # ---------- operator modes ----------

    def _observe_modes(self) -> None:
        """Advance skip-mode and make debug-mode transitions visible.

        Runs at the top of every tick: the skip flag must engage before the
        queue it targets comes due, and a mode change should announce itself
        once in the log rather than being discovered from what did not happen.
        """
        # Skip mode edits AUTO-MAS's queue config. While a script runs AUTO-MAS's
        # in-memory copy overwrites such an edit, so it waits for the next tick
        # with nothing running. (Even then AUTO-MAS can ignore a file edit, which
        # is why queues.apply goes through the backend API whenever it answers.)
        if self._scripts_running():
            return
        fresh = False
        try:
            for msg in modes.process_skip(self.state.dir, self.cfg.automas_dir):
                log.info("⏭️ %s", msg)
                # A persistent failure (queue renamed while a restore marker is
                # pending) returns the identical message on every tick: one push
                # per message per process.
                if msg not in self._mode_notified:
                    self._mode_notified.add(msg)
                    fresh = True
                    if not skip_failed(self.state.dir, msg):
                        self.notifier.send(texts.SKIP_MODE, msg)     # an acknowledgement: log route
                    elif errs := self.notifier.send(SKIP_FAILED, msg, alert=True):
                        # Not out: errwatch pushes this line (kept on disk until the
                        # group takes it), and a failure said again next tick is pushed again.
                        self._mode_notified.discard(msg)
                        log.warning("%s：%s（报警没推出去：%s）", SKIP_FAILED, msg, "；".join(errs))
        except Exception:
            log.exception("跳过模式处理出错")
        if fresh and self._push_state is not None:
            try:
                self._push_state("跳过队列")
            except Exception:
                log.exception("跳过队列后状态没能上报到手机")
        if expired_until := modes.expire_debug_if_due(self.state.dir):
            log.info("🔧 调试模式（至 %s）已到期，释放被吞的关机机会，本轮重新判关机", expired_until)
        active = modes.debug_active(self.state.dir)
        if active != self._debug_last:
            if active:
                log.info("🔧 调试模式生效（至 %s）：这一轮跑完不关机",
                         modes.debug_until(self.state.dir))
            elif self._debug_last is not None:
                log.info("🔧 调试模式已结束，恢复正常判定")
            self._debug_last = active

    # ---------- survive restarts ----------

    # Steps skipped while state.json has never been read since boot (D-1017 boot
    # read-lock): running them on an unread empty state would misread marks/holds.
    _UNREAD_SKIP_STEPS = frozenset({
        "推送积压告警", "周常门", "月卡提醒", "明日方舟活动提醒", "需求表", "漏跑检查", "补跑",
        "补活跃", "基质刷垫子", "临时查看", "队列后更新", "收工体检", "日报", "关机",
    })

    def _restore_pending(self) -> bool:
        """Reload alerts that were queued but never delivered.

        Returns False when state.json could not be read on boot (e.g. Windows lock):
        the in-memory buckets stay unread and _persist_pending refuses to overwrite
        state.json until a later tick reads it back."""
        if getattr(self, "_pending_restored", False):
            return True
        from ark_relay.core.collector import payload_to_record  # noqa: PLC0415 - avoid cycle
        try:
            data = self.state.load_pending(fresh=True)
        except OSError as exc:
            log.info("开机读不到 state.json（%s），未送达的告警暂不恢复，读回来之前跳过依赖它的步骤",
                     type(exc).__name__)
            return False
        dropped = []
        for bucket, target in (("pending", self._pending), ("recovered", self._recovered)):
            for item in data.get(bucket, []):
                try:
                    rec = payload_to_record(item)
                except (KeyError, ValueError, TypeError):
                    # Boot-only path: say it directly, or an alarm held across the
                    # restart vanishes with no trace.
                    got = item if isinstance(item, dict) else {}
                    dropped.append(" ".join(str(got.get(k) or "") for k in ("script", "run_id")).strip()
                                   or "（认不出是哪条）")
                    continue
                target[(rec.script, rec.user)] = rec
                if tail := item.get("log_tail"):
                    self.log_tails[rec.run_id] = str(tail)
        for item in data.get("unsent", []):
            if isinstance(item, list) and len(item) == 5 and all(isinstance(x, str) for x in item):
                self._unsent_unresolved.append(tuple(item))
            else:
                dropped.append(str(item)[:80])
        if dropped:
            log.warning("磁盘上有 %d 条未送达的告警恢复不出来，已丢弃：%s",
                        len(dropped), "；".join(dropped))
        if self._pending or self._recovered or self._unsent_unresolved:
            log.info("从磁盘恢复了 %d 条未送达的告警",
                     len(self._pending) + len(self._recovered) + len(self._unsent_unresolved))
        self._pending_restored = True
        return True

    def _persist_pending(self) -> None:
        if not getattr(self, "_pending_restored", True) and not self._restore_pending():
            raise PermissionError("state.json 开机还没读回来，拒绝把未送达告警覆盖成空的")
        from ark_relay.core.collector import record_to_payload  # noqa: PLC0415 - avoid cycle
        def payload(r: RunRecord) -> dict:
            p = record_to_payload(r)
            # A record restored from disk has no log file to read: keep the tail it came with.
            if not p.get("log_tail") and self.log_tails.get(r.run_id):
                p["log_tail"] = self.log_tails[r.run_id]
            return p
        self.state.save_pending({
            "pending": [payload(r) for r in self._pending.values()],
            "recovered": [payload(r) for r in self._recovered.values()],
            "unsent": [list(x) for x in self._unsent_unresolved],
        })

    # ---------- first ever start ----------

    def bootstrap(self) -> int:
        """Adopt whatever history already exists as already-handled.

        A fresh install must not replay past runs as new alerts. Those records
        describe problems that were either already dealt with or are simply
        old news; pushing them looks like a flood of failures that just
        happened. Only runs produced after the relay starts are news.
        """
        if self.state.seen_path.exists():
            return 0
        adopted = 0
        for rec in self.source.fetch(set()):
            self.state.mark_seen(rec.run_id)
            adopted += 1
        # Touch the file even when there is nothing, so the next start is not
        # treated as a first start.
        self.state.seen_path.touch(exist_ok=True)
        if adopted:
            log.info("首次启动：已把 %d 条历史记录标记为已处理，不会重复告警", adopted)
        return adopted

    # ---------- one pass ----------

    def tick(self) -> int:
        """Process whatever is new. Returns how many records were handled."""
        # Every step is caught on its own, so one broken step cannot take the
        # rest of the tick (and the daily report and shutdown at its end) with it.
        # Phone orders that waited for the run to end go first: a queued skip is
        # then engaged by _observe_modes below, and a queued 「现在跑」 or setting
        # is in place before this tick's shutdown decision.
        if self._phone_drain is not None:
            try:
                self._phone_drain()
            except Exception:
                log.exception("排队的手机指令没执行完，下一轮再试")
        try:
            self._observe_modes()
        except Exception:
            log.exception("读模式开关出错，本轮按「没开任何模式」继续")
        if not getattr(self, "_pending_restored", True) and not self._restore_pending():
            self._fetch_owed = True
            records = []
            landed = False
        else:
            self._fetch_owed = False
            given_up = self._given_up()
            code = self._code_version()
            try:
                # A given-up record stays out until the code changes: a deploy (the fix
                # for the alarm below) gets one more round of HANDLE_TRIES at it.
                records = self.source.fetch(
                    self.state.seen | {k for k, v in given_up.items() if v.get("code") == code})
            except Exception:
                log.exception("读取运行记录失败，本轮按没有新记录处理")
                records = []
            landed = False
            for rec in records:
                try:
                    self._handle(rec)
                except Exception:
                    n = self._handle_fails[rec.run_id] = self._handle_fails.get(rec.run_id, 0) + 1
                    if n < HANDLE_TRIES:
                        log.info("处理运行记录失败（第 %d 次，下一轮再试）: %s", n, rec.run_id, exc_info=True)
                        continue
                    log.exception("运行记录连续 %d 次处理失败，不再重试，这一趟先不记进账，"
                                  "等修好部署后再补记一次: %s", n, rec.run_id)
                    self._handle_fails.pop(rec.run_id, None)
                    given_up[rec.run_id] = {"code": code, "at": datetime.now(tz=SERVER_TZ).isoformat()}
                    self._set_given_up(given_up)
                    self._handled_any = landed = True
                    continue
                self._handle_fails.pop(rec.run_id, None)
                self.state.mark_seen(rec.run_id)
                if given_up.pop(rec.run_id, None) is not None:
                    log.info("之前放弃的运行记录这次记进账了: %s", rec.run_id)
                    self._set_given_up(given_up)
                self._handled_any = landed = True
        if landed:
            # On disk too: a restart on the same boot (a deploy) still knows it saw them land.
            shutdown.note_handled(self, datetime.now(tz=SERVER_TZ))
        # Every step is caught on its own; a broken one must not take the rest with
        # it. Shutdown and the daily report are last.
        # Hard-locked (features/hardlock.py): the steps that start a run or write into
        # AUTO-MAS / the games / COS are not taken; watching, alarms, reports and the
        # power-off still are.
        from ark_relay.features import hardlock  # noqa: PLC0415
        locked = hardlock.active(self.cfg.state_dir)
        if locked:
            try:
                from ark_relay.features import commands  # noqa: PLC0415
                hardlock.timers_off(commands._mas)
            except Exception:  # AUTO-MAS down or busy: the next tick tries again
                log.info("硬锁中：这一轮没能核对调度程序定时（下一轮再核）", exc_info=True)
        skip_unread = not getattr(self, "_pending_restored", True)
        for what, step in (
            ("刷声骸到点收工", self._echo_farm_deadline),
            ("协议空间开关保护", self._guard_maaend_switches),
            ("在跑巡查", self._run_watch),
            ("推送积压告警", self._flush_pending),
            ("周常门", self._weekly_gates),
            ("月卡提醒", self._monthcard_notice),
            ("明日方舟活动提醒", self._ak_activity_notice),
            ("需求表", self._need_table),
            # Before the missed-run check and the shutdown decision: both read what
            # the stage gate pulled (stagegate.excused / recent_pulled).
            ("关卡门", self._stage_gate),
            ("漏跑检查", self._check_missed_runs),
            # Before both reports and the shutdown decision: a held MAA / MaaEnd
            # failure gets its one make-up run first (makeup.py), and the reports
            # wait for it instead of describing the day without it.
            # Before the make-up: it must not be dispatched under a retry limit someone
            # put back to 3 (run_limit.py).
            ("重试上限", self._run_limit_guard),
            ("补跑", self._maybe_makeup),
            # The evening top-up of a waveplate-short daily activity (activity.py), after
            # the queue and before the reports and the shutdown decision, which wait for it.
            ("补活跃", self._maybe_activity_topup),
            # After the make-up (it may hold a temporary change in the master) and
            # before the reports (the switch is one line in the daily report).
            ("基质刷垫子", self._essence_filler),
            ("临时查看", self._maybe_interim_report),
            ("队列后更新", self._maybe_deferred_update),
            # Before the report (it quotes the line) and the shutdown step (which
            # spends the 「下次跑完不关机」 mark the check reads).
            ("收工体检", self._shift_check),
            ("日报", self._maybe_daily_report),
            ("留机锁到期", self._check_alarm_hold_expiry),
            ("关机", self._maybe_shutdown),
        ):
            if (locked and what in LOCKED_STEPS) or (skip_unread and what in self._UNREAD_SKIP_STEPS):
                continue
            try:
                step()
            except Exception:
                log.exception("本轮「%s」这一段出错，跳过它继续", what)
        return len(records)

    def _guard_maaend_switches(self) -> None:
        """Keep MaaEnd's ProtocolSpace switch & per-controller state intact after idle/ScriptConfig."""
        if not self.cfg.automas_dir or self._scripts_running() or script_config_open(self.cfg.automas_dir):
            return
        from ark_relay.core import mastercfg  # noqa: PLC0415
        f = mastercfg.maaend_master(self.cfg.automas_dir)
        if f is None or not f.is_file():
            return
        try:
            sig = (str(f), f.stat().st_mtime_ns, f.stat().st_size)
        except OSError:
            return
        if sig == getattr(self, "_maaend_guard_sig", None):
            return
        mastercfg.guard_maaend_protocol_space(self.cfg.automas_dir, self.state.dir)
        try:
            self._maaend_guard_sig = (str(f), f.stat().st_mtime_ns, f.stat().st_size)
        except OSError:
            self._maaend_guard_sig = None

    def _echo_farm_deadline(self) -> None:
        """End a 「farm until HH:MM」 run when its moment arrives."""
        from ark_relay.features import echofarm  # noqa: PLC0415
        note, failed = echofarm.tick_result(self.cfg)
        if not note:
            return
        log.info("刷声骸：%s", note)
        echofarm.push_wrapup(self.notifier, note, failed)

    def _run_limit_guard(self) -> None:
        """Endfield's failure retry limit in AUTO-MAS kept at 1 (run_limit.py)."""
        from ark_relay.features import queues as run_limit  # noqa: PLC0415
        run_limit.step(self)

    def _monthcard_notice(self) -> None:
        """From five days before a monthly card's last claim day, one Server酱 line a day."""
        from ark_relay.features import friend_events, hardlock, phone as monthcard  # noqa: PLC0415
        if hardlock.active(self.state.dir, "wechat"):
            return
        items = monthcard.due_items(self.state.dir)
        due = monthcard.due_notice(self.state.dir)
        if due and not self.notifier.send(*due):
            monthcard.mark_sent(self.state.dir)
            try:
                for it in items:
                    friend_events.emit_monthcard_expiring(
                        self.cfg,
                        game=it["game"],
                        days_left=it["days_left"],
                        last_date=it["last"],
                        text=it["line"],
                    )
            except Exception:
                log.warning("月卡到期好友提醒入队失败", exc_info=True)

    def _ak_activity_notice(self) -> None:
        """Notify once when a new or rerun Arknights activity opens (ak_activity.py)."""
        from ark_relay.features import ak_activity  # noqa: PLC0415
        ak_activity.step(self)

    def _need_table(self) -> None:
        """Once a server day, on a thread of its own: the App's need table rebuilt and put on COS (needtable.py)."""
        from ark_relay.features import needtable  # noqa: PLC0415
        needtable.step(self.cfg)

    def _stage_gate(self, now: datetime | None = None, lead_min: int | None = None) -> None:
        """Before each MAA due: pull MAA from that queue run when its stage cannot be
        navigated to; put it back afterwards (stagegate.py). Local files only.
        lead_min: the boot pass looks further ahead (stagegate.BOOT_LEAD_MIN)."""
        from ark_relay.features import stagegate  # noqa: PLC0415
        stagegate.step(self.cfg, self.notifier, now, busy=self._scripts_running,
                       lead_min=lead_min or stagegate.LEAD_MIN)

    def _weekly_gates(self) -> None:
        try:
            self._garden.enforce()
            self._weeklyboss.enforce()
        except Exception:
            log.warning("周常乐园开关没能落盘，下轮再试", exc_info=True)

    # ---------- update the game clients only after the queue is done ----------

    def _deferred_update_busy(self) -> bool:
        t = getattr(self, "_gu_thread", None)
        return bool(t is not None and t.is_alive())

    def _maybe_deferred_update(self) -> None:
        """Registered + queues finished + nothing running -> update in a background
        thread, then re-run.

        Other games finish first; then the game updates on its own and re-runs on
        its own. _maybe_shutdown will not power off while the thread is alive; the
        re-run is a script dispatched by AUTO-MAS, so once it starts
        _scripts_running blocks shutdown as usual. At most once a day.
        """
        from ark_relay.features import gameupdate  # noqa: PLC0415
        from ark_relay.features import makeup as makeup_marker  # noqa: PLC0415
        if self._deferred_update_busy() or not gameupdate.pending(self.state.dir):
            return
        now = datetime.now(tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        why = ""
        if getattr(self, "_gu_day", "") == day:
            why = "今天已经起过一次"
        elif self._scripts_running():
            why = "有脚本在跑"
        elif inflight := makeup_marker.in_flight(self.cfg.state_dir, now):
            # The make-up step runs just before this one in the same tick, and
            # _scripts_running's answer is cached for _SCRIPTS_TTL, so a make-up
            # dispatched a moment ago does not show as running yet. Started now,
            # the re-run (needs_rerun) would read the failure the make-up is for
            # (e.g. a never-started MAA, maa_unreachable) and dispatch the same
            # script a second time; the make-up's record decides instead.
            why = "补跑还没跑完：" + "、".join(inflight)
        elif not self.state.read_ledger(day):
            why = "今天还没有任何运行记录"
        elif unfinished := self._unfinished_queues(now, self._recent_entries(now)):
            why = "队列没跑完：" + "；".join(unfinished)
        if why:
            # One line only when the reason changes, not every 30 s.
            if why != getattr(self, "_gu_wait_note", ""):
                self._gu_wait_note = why
                log.info("游戏更新：有登记但先不动（%s）", why)
            return
        self._gu_wait_note = ""
        import threading  # noqa: PLC0415
        self._gu_day = day

        games = "、".join(gameupdate.pending(self.state.dir))

        def work() -> None:
            from ark_relay.features import commands  # noqa: PLC0415
            try:
                def _dispatch(name: str):
                    self._gu_rerun_at = datetime.now(tz=SERVER_TZ)
                    # Which scripts the catch-up re-ran: shutdown._shift_overdue times them from here
                    self._gu_reran = {*getattr(self, "_gu_reran", ()), name}
                    try:
                        return commands.run_script(name)
                    finally:
                        # The thread ends right after this; the shutdown decision of
                        # the next tick must ask AUTO-MAS, not reuse a 「nothing runs」
                        # read cached before the re-run was dispatched (清单-1108 A-14).
                        forget_scripts_cache()
                try:
                    notes, problems, reran = gameupdate.run_deferred(
                        self.cfg, now=now, dispatch=_dispatch)
                finally:
                    # Every screen the update read (gameupdate.last_trace): the
                    # machine checks #60-#62 judge from it.
                    self._machinecheck("gameupdate", {"game": games, "screens": gameupdate.last_trace()})
                for n in notes:
                    self.notifier.send(texts.GAME_UPDATE, n)
                if reran:
                    self.notifier.send(texts.RERUN_AFTER_UPDATE, texts.rerun_body(reran))
                if problems:
                    # A group alarm, each time.
                    self.notifier.send(texts.unconfirmed("游戏更新", len(problems)),
                                       "\n".join(f"· {x}" for x in problems), alert=True)
            except Exception:
                log.exception("游戏更新（队列后）出错")

        self._gu_thread = threading.Thread(target=work, name="game-update", daemon=True)
        self._gu_thread.start()
        log.info("游戏更新：队列已跑完，后台开始更新 %s", "、".join(gameupdate.pending(self.state.dir)))

    def _machinecheck(self, event: str, ctx: dict) -> None:
        """Hand one event to the machine checks (machinecheck.py). Never raises: a
        broken check must not break the relay's own path (judge logs it as ERROR)."""
        if not getattr(self.cfg, "state_dir", None):
            return
        try:
            from ark_relay.features import machinecheck  # noqa: PLC0415
            from ark_relay.core.statestore import StateStore  # noqa: PLC0415
            machinecheck.judge(self.cfg.state_dir, event, ctx, notifier=self.notifier,
                               version=str(StateStore(self.cfg.state_dir).get("versions", "code") or ""))
        except Exception:
            log.exception("上机核对（%s）自己出错，这一步照常", event)

    # ---------- decide held-back failures ----------

    def scripts_running(self) -> bool:
        """Public view of the same check the shutdown path uses.

        The service needs it to decide when a config edit is safe: AUTO-MAS
        reads its config as it launches each script, so writing during a run
        would land somewhere between two scripts and take effect for only half
        the queue.
        """
        return self._scripts_running()

    def _script_running(self, name: str) -> bool:
        """Is this one script still running or waiting its turn in AUTO-MAS?

        Asks runtime-snapshot for that script alone. When AUTO-MAS timed out
        (alive and busy), waits at once without paying a second timeout; when
        AUTO-MAS cannot be reached at all, falls back to `_scripts_running`.
        """
        if not config.IS_WINDOWS:
            return False
        with _SCRIPTS_CACHE_LOCK:
            gen = _SCRIPTS_CACHE.get("gen", 0)
        _SNAP_STATE.timed_out = False
        snap = _automas_snapshot()
        if snap is None:
            if getattr(_SNAP_STATE, "timed_out", False):
                log.info("AUTO-MAS 运行快照超时，暂按 %s 还在跑处理", name)
                with _SCRIPTS_CACHE_LOCK:
                    if _SCRIPTS_CACHE.get("gen", 0) == gen:
                        _SCRIPTS_CACHE["at"] = time.monotonic()
                        _SCRIPTS_CACHE["val"] = True
                        _SCRIPTS_CACHE["gen"] = gen + 1
                return True
            return self._scripts_running()
        return _script_unfinished(snap, name)

    @staticmethod
    def _scripts_running() -> bool:
        """True while AUTO-MAS says a task is in progress, or a game process is alive.

        Asks AUTO-MAS first (/api/dispatch/runtime-snapshot: the state of every script
        in the queue) and falls back to the process list only when it cannot be
        reached. Processes alone miss a script between rounds of its retries, and
        AUTO-MAS writes a record only once the whole script ends. A failure is
        reported only once nothing is still trying.
        """
        if not config.IS_WINDOWS:
            return False
        # One tick asks this many times (skip mode, held-back alerts, missed runs,
        # reports, shutdown); an answer less than _SCRIPTS_TTL seconds old is reused.
        with _SCRIPTS_CACHE_LOCK:
            now = time.monotonic()
            if now - _SCRIPTS_CACHE["at"] < _SCRIPTS_TTL:
                return _SCRIPTS_CACHE["val"]
            gen = _SCRIPTS_CACHE.get("gen", 0)
        busy = _automas_busy()
        if busy:
            val = True
        else:
            try:
                out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                                     capture_output=True, timeout=20).stdout
            except (OSError, subprocess.SubprocessError):
                val = True  # cannot tell -> wait rather than cry wolf
            else:
                # Endfield.exe has to be counted too: MaaEnd **has no process of
                # its own**, AUTO-MAS's python drives it in-process, so watching only
                # MaaEnd.exe goes blind for the entire Endfield stretch.
                # 来龙去脉见 docs/CODE-HISTORY.md「engine.py:_scripts_running」
                val = any(n in out for n in (b"MAA.exe", b"MaaEnd.exe", b"Endfield.exe")) or _okww_up()
        with _SCRIPTS_CACHE_LOCK:
            if _SCRIPTS_CACHE.get("gen", 0) == gen:
                _SCRIPTS_CACHE["at"] = now
                _SCRIPTS_CACHE["val"] = val
                _SCRIPTS_CACHE["gen"] = gen + 1
        return val

    # ---------- daily wrap-up ----------

    def _reread_moments(self, now: datetime) -> list[tuple[datetime, str]]:
        """Reads the last tick put off that no file event will bring back: state.json
        refusing reads (statestore.refused_since), a record waiting for its log or a
        history.db read that failed (collector.next_moment), the need table's same-day
        second try (needtable.next_moment). Each waited for the hour backstop before
        (dispatch relay-audit-round2-1108 N-02 / N-05)."""
        from ark_relay.core import collector, statestore  # noqa: PLC0415
        from ark_relay.features import needtable  # noqa: PLC0415
        out = []
        state_file = getattr(getattr(self.state, "store", None), "path", None)
        if state_file is not None and (
                statestore.refused_since(state_file) is not None
                or not getattr(self, "_pending_restored", True)
                or getattr(self, "_fetch_owed", False)):
            out.append((now + timedelta(seconds=statestore.UNREAD_RETRY_S), "重读 state.json"))
        for moment in (collector.next_moment(now), needtable.next_moment(self.cfg.state_dir, now)):
            if moment is not None:
                out.append(moment)
        return out

    def _missed_moments(self, now: datetime) -> list[tuple[datetime, str]]:
        """Missed-run check moments for scheduled queues (today & tomorrow)."""
        out: list[tuple[datetime, str]] = []
        for q in plan.schedule(self.cfg.automas_dir):
            for hhmm in q.get("times", []):
                try:
                    hh, mm = (int(x) for x in hhmm.split(":"))
                except ValueError:
                    continue
                due0 = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                for due in (due0, due0 + timedelta(days=1)):
                    if not plan.runs_at(q, hhmm, due):
                        continue        # that time runs nothing that day: nothing to miss
                    key = f"{due:%Y-%m-%d}/{q['name']}/{hhmm}"
                    moment = due + timedelta(minutes=MISSED_GRACE_MIN)
                    if moment > now and key not in self._missed_alerted:
                        out.append((moment, f"核对队列「{q['name']}」{hhmm} 是否漏跑"))
        return out

    def next_deadline(self, now: datetime | None = None) -> tuple[datetime, str] | None:
        """The next moment any purely time-based decision can change.

        Event-driven work wakes the loop by itself (a record landing on disk, the
        backend dying, the service being stopped). The clock work left has exact
        next moments, and the loop sleeps until the earliest:

          - a queue that produced nothing becomes reportable at due+grace
          - the daily report becomes due at the cutoff
          - a wake-up checkpoint is asked once, shortly past its time
          - the echo farm's deadline, and a look at whether its task is alive
          - runwatch's moments, the shutdown uptime floor, make-up retries
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if self._shutdown_issued:
            from ark_relay.features.shutdown import ISSUED_STUCK_MIN  # noqa: PLC0415
            at = getattr(self, "_shutdown_issued_at", None)
            if at is not None and (check := at + timedelta(minutes=ISSUED_STUCK_MIN)) > now:
                return (check, "核对关机有没有关下去")
            return None
        cands: list[tuple[datetime, str]] = []
        # Hard-locked (features/hardlock.py): wake every minute to put AUTO-MAS's timers back to
        # off and to judge the power-off again (debug mode's end and the 08:25 pre-cut window
        # have no deadline of their own).
        from ark_relay.features import hardlock  # noqa: PLC0415
        if hardlock.active(self.cfg.state_dir):
            cands.append((now + timedelta(seconds=hardlock.TIMERS_EVERY_S), "硬锁：核一次调度程序定时，再判一次关机"))

        try:
            cands.extend(self._reread_moments(now))
        except Exception:
            log.exception("算重读的时刻出错，跳过")

        # An echo farm: its deadline, and a look every RESTART_QUIET_MINUTES while
        # it runs to notice the task has died.
        from ark_relay.features import echofarm  # noqa: PLC0415
        if rec := echofarm.current(self.cfg.state_dir):
            if until := echofarm.deadline_of(rec):
                cands.append((until, "刷声骸到点收工"))
            cands.append((now + timedelta(minutes=echofarm.RESTART_QUIET_MINUTES),
                          "看一眼刷声骸还活着没"))

        cands.extend(self._missed_moments(now))

        try:
            entries = self._recent_entries(now)
            for q in plan.recent_due_queues(self.cfg.automas_dir, now, window_minutes=self.cfg.partial_window):
                matched = missed._matched_runs(entries, q, q["due"])
                moment = missed._partial_deadline(q["due"], self.cfg.partial_grace, matched)
                day, hhmm = q["due"].strftime("%Y-%m-%d"), q["due"].strftime("%H:%M")
                if moment > now and any(not missed._settled(self, day, f"{day}/{q['name']}/{hhmm}/{k}")
                                        for k in shutdown._missing_kinds(self, q, entries)):
                    cands.append((moment, f"核对队列「{q['name']}」{hhmm} 有没有缺项"))
        except Exception:
            log.exception("算缺项核对的时刻出错，跳过")

        # A running queue is only visible through AUTO-MAS's own log and snapshot,
        # neither of which wakes the loop (runwatch.next_moments).
        try:
            from ark_relay.features import runwatch  # noqa: PLC0415
            cands.extend(runwatch.next_moments(self, now, self._scripts_running()))
        except Exception:
            log.exception("算在跑巡查的时刻出错，跳过")

        # A shift still lacking a record becomes overdue (shutdown._alarm_shift_overdue):
        # with no script running and AUTO-MAS silent, nothing else wakes the loop then.
        try:
            cands.extend(shutdown.overdue_moments(self, now))
        except Exception:
            log.exception("算班次超时的时刻出错，跳过")

        # The shutdown floor (shutdown.py: 「开机不够久」 until _started_at +
        # shutdown_min_uptime): re-judge shutdown when it passes.
        if self.cfg.shutdown_after_run:
            floor = self._started_at + timedelta(seconds=self.cfg.shutdown_min_uptime)
            if floor > now:
                cands.append((floor, "开机满下限，重新判一次关机"))

        # A make-up dispatch that did not take is tried again after a gap, and one
        # that never produced a record is closed out after a while; both are
        # moments nothing else wakes the loop for.
        try:
            from ark_relay.features import makeup  # noqa: PLC0415
            if moment := makeup.next_moment(self.cfg.state_dir, now):
                cands.append(moment)
            from ark_relay.features import activity  # noqa: PLC0415
            if moment := activity.next_moment(self.cfg.state_dir, now):
                cands.append(moment)
        except Exception:
            log.exception("算补跑的时刻出错，跳过")

        if not self.state.report_sent(now.strftime("%Y-%m-%d")):
            cutoff = self._report_cutoff(now)
            if cutoff > now:
                cands.append((cutoff, "日报截止"))

        cands.extend(self._debug_deadline(now))
        cands.extend(self._alarm_hold_deadline(now))

        return min(cands) if cands else None

    def _debug_deadline(self, now: datetime) -> list[tuple[datetime, str]]:
        try:
            end_dt = modes.debug_end(self.cfg.state_dir)
            if end_dt is not None and end_dt > now:
                return [(end_dt, "调试模式到期，重新判一次关机")]
        except (OSError, ValueError, TypeError):
            return []
        return []

    def _alarm_hold_deadline(self, now: datetime) -> list[tuple[datetime, str]]:
        try:
            hold = modes.alarm_hold_raw(self.cfg.state_dir)
            if isinstance(hold, dict) and hold.get("until"):
                until_dt = modes._parse_bj(hold["until"])
                if until_dt > now:
                    return [(until_dt, "故障留机锁到期释放")]
        except (OSError, ValueError, TypeError):
            return []
        return []

    def _check_alarm_hold_expiry(self, now: datetime | None = None) -> None:
        """Expire an alarm_hold whose `until` has arrived and notify the group honestly."""
        cur = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        old, in_window = modes.expire_alarm_hold_if_due(self.cfg.state_dir, cur)
        if not old:
            return
        reason = str(old.get("reason") or "")
        boot = str(old.get("boot") or old.get("until") or "")
        body = texts.alarm_hold_expired_body(reason, boot, in_window)
        log.info("⏰ 故障留机锁到期释放（预定开机 %s，窗内=%s，原原因：%s）", boot, in_window, reason)
        self.notifier.send(texts.ALARM_HOLD_EXPIRED, body, alert=True)

    # ---------- bookkeeping and alerts (handle.py) ----------
    def _code_version(self) -> str:
        try:
            return str(self.state.store.get("versions", "code") or "")
        except Exception:  # noqa: BLE001 - no version only means no retry after a deploy
            return ""

    def _given_up(self) -> dict:
        """queues.given_up: run_id -> {code, at} for records tick gave up on, minus
        the ones older than GIVEN_UP_KEEP_DAYS."""
        try:
            raw = self.state.store.get("queues", "given_up") or {}
        except Exception:
            log.warning("读不出放弃过的运行记录，本轮按没有处理", exc_info=True)
            return {}
        cut = datetime.now(tz=SERVER_TZ) - timedelta(days=GIVEN_UP_KEEP_DAYS)
        out = {}
        for rid, v in raw.items() if isinstance(raw, dict) else ():
            try:
                if isinstance(v, dict) and datetime.fromisoformat(str(v.get("at"))) >= cut:
                    out[str(rid)] = v
            except ValueError:
                continue
        return out

    def _set_given_up(self, given_up: dict) -> None:
        try:
            if given_up:
                self.state.store.set("queues", "given_up", dict(given_up))
            else:
                self.state.store.pop("queues", "given_up")
        except Exception:
            log.warning("放弃过的运行记录没能存盘", exc_info=True)

    def _handle(self, rec: RunRecord) -> None:
        return handle._handle(self, rec)

    def _verify_outcome(self, rec: RunRecord) -> str | None:
        return handle._verify_outcome(self, rec)

    def _archive_maaend_evidence(self, rec: RunRecord) -> None:
        return handle._archive_maaend_evidence(self, rec)

    def _warn_if_evidence_stale(self, rec: RunRecord, dst: Path) -> None:
        return handle._warn_if_evidence_stale(self, rec, dst)

    def _maintenance_today(self, game: str) -> bool:
        return handle._maintenance_today(self, game)

    def _alert_key(self, rec) -> str:
        return handle._alert_key(self, rec)

    def _alerted_file(self, day: str) -> Path:
        return handle._alerted_file(self, day)

    def _already_alerted(self, day: str, key: str) -> bool:
        return handle._already_alerted(self, day, key)

    def _mark_alerted(self, day: str, key: str) -> None:
        return handle._mark_alerted(self, day, key)

    def _flush_pending(self) -> None:
        unsent = len(self._unsent_unresolved)
        try:
            return handle._flush_pending(self)
        finally:
            # A retried 「没干完」 alarm that went out leaves the copy on disk too.
            if len(self._unsent_unresolved) != unsent:
                self._persist_pending()
            try:
                from ark_relay.features import friend_events  # noqa: PLC0415
                friend_events.flush_pending(self.cfg, async_flush=True)
            except Exception:
                log.warning("排空好友微信待发队列失败", exc_info=True)

    def _essence_filler(self, now: datetime | None = None) -> None:
        """A target-met essence run switches 基质刷取 to filler mode (features/essence)."""
        from ark_relay.features import essence  # noqa: PLC0415
        essence.step(self, now)

    def _maybe_activity_topup(self, now: datetime | None = None) -> bool:
        from ark_relay.features import activity  # noqa: PLC0415
        return activity.maybe_run(self, now)

    def _maybe_makeup(self, now: datetime | None = None) -> bool:
        from ark_relay.features import makeup  # noqa: PLC0415
        return makeup.maybe_run(self, now)

    def _run_watch(self, now: datetime | None = None) -> None:
        """Every timeout of each script, a script AUTO-MAS refused at its config check, and a
        shift running past its planned end (runwatch)."""
        from ark_relay.features import runwatch  # noqa: PLC0415
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if self._applog is None:
            self._applog = runwatch.AppLog(runwatch.applog_path(self.cfg.automas_dir))
        events = self._unsent_timeouts + self._applog.poll()
        self._unsent_timeouts = runwatch.check_timeouts(self, events, now)
        self._unsent_skips = runwatch.check_config_skips(self, self._unsent_skips + self._applog.take_skips(), now)
        if config.IS_WINDOWS:
            runwatch.check_overrun(self, now, _automas_snapshot())

    # ---------- missed runs and missing items (missed.py) ----------
    def _check_missed_runs(self, now: datetime | None = None,
                           grace_min: int = MISSED_GRACE_MIN) -> None:
        return missed._check_missed_runs(self, now, grace_min)

    def _check_partial_queues(self, now: datetime, day: str,
                              entries: list[dict]) -> None:
        return missed._check_partial_queues(self, now, day, entries)

    # ---------- daily report and interim view (report.py) ----------
    def _report_cutoff(self, now: datetime) -> datetime:
        return report._report_cutoff(self, now)

    def _maybe_interim_report(self, now: datetime | None = None) -> None:
        return report._maybe_interim_report(self, now)

    def _maybe_daily_report(self, now: datetime | None = None) -> None:
        return report._maybe_daily_report(self, now)

    def _shift_check(self, now: datetime | None = None) -> None:
        """The after-shift check, once per finished morning / evening shift (selfcheck/shiftcheck.py)."""
        from ark_relay.features import selfcheck as shiftcheck  # noqa: PLC0415
        shiftcheck.maybe_run(self, (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ))

    def _compose_daily(self, day: str, entries: list[dict]) -> tuple[str, str]:
        return report._compose_daily(self, day, entries)

    def _announce_banners(self, now: datetime, nxt) -> None:
        return report._announce_banners(self, now, nxt)

    def send_daily_now(self, mark: bool = True, label: str = "临时查看") -> bool:
        return report.send_daily_now(self, mark, label)

    # ---------- shutdown decision (shutdown.py) ----------
    def _boot_time(self, now: datetime | None = None) -> datetime | None:
        return shutdown._boot_time(self, now)

    def _recent_entries(self, now: datetime) -> list[dict]:
        return shutdown._recent_entries(self, now)

    def _unfinished_queues(self, now: datetime, entries: list[dict]) -> list[str]:
        return shutdown._unfinished_queues(self, now, entries)

    def _round_is_manual(self, new_entries: list[dict]) -> bool:
        return shutdown._round_is_manual(self, new_entries)

    def _last_round_manual(self, now: datetime, entries: list[dict]) -> bool:
        return shutdown._last_round_manual(self, now, entries)

    def _shutdown_key(self, now: datetime) -> str:
        return shutdown._shutdown_key(self, now)

    def _maybe_shutdown(self, now: datetime | None = None) -> bool:
        return shutdown._maybe_shutdown(self, now)

    def _power_off(self) -> bool:
        """Issue the actual shutdown command. It lives here so tests can swap out subprocess.

        True only when Windows accepted the command (exit code 0). A refusal (1190
        "a shutdown is already scheduled", no privilege) returns False, which sends
        the caller (shutdown._maybe_shutdown) back to deciding on the next tick; the
        ERROR line is the alarm (errwatch). The 「60 秒后关机」 line is written only
        after the command was accepted: machine checks #37/#38
        (machinechecks/system.py POWER_OFF) read it as proof the relay powered the
        machine off.
        """
        # /d p:4:1 records the power-off as planned ("Application: Maintenance
        # (Planned)"); without /d, "If p or u aren't specified, the restart or
        # shutdown is unplanned."
        # https://learn.microsoft.com/windows-server/administration/windows-commands/shutdown
        try:
            r = subprocess.run(["shutdown", "/s", "/t", "60", "/d", "p:4:1",
                                "/c", "ark-relay: run complete"],
                               capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("关机命令执行失败")
            return False
        if r.returncode != 0:
            # shutdown.exe prints in the console codepage (GBK on the machine).
            said = b" ".join(x for x in (r.stderr or b"", r.stdout or b"") if x.strip())
            log.error("关机命令被 Windows 拒绝（退出码 %s）：%s，这次没关机，下一轮再判",
                      r.returncode, said.decode("gbk", errors="replace").strip() or "没有输出")
            return False
        log.info("本轮已处理完毕，60 秒后关机")
        return True

    def _abort_power_off(self) -> int:
        """Run `shutdown /a` and return its exit code (-1 when it could not run).

        0 = the countdown _power_off started was cancelled; 1116
        (ERROR_NO_SHUTDOWN_IN_PROGRESS) = there was no countdown to cancel.
        """
        try:
            r = subprocess.run(["shutdown", "/a"], capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("取消关机命令执行失败")
            return -1
        return r.returncode
