"""Game client updates on a version-update or maintenance day.

At boot (boot_check): cheap checks only - the Arknights version endpoint, the
Endfield and Wuthering Waves notices, and the three official maintenance
bulletins. A game that needs an update is registered (mark_pending), and during a
maintenance window its script is taken out of today's queues.
After the queue (run_deferred): each registered game's client is updated through
its launcher up to the login screen, the relay waits for the servers to return,
re-runs the script when today's last round failed for that reason, and puts the
removed scripts back in the queues.

Anything that could not be confirmed goes into `problems` for the caller to send.
The per-game update flows are in gameupdate_games.py and the MaaEnd task records
in gameupdate_maaend.py; their public names are re-exported here, so callers write
gameupdate.xxx.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core.config import SERVER_TZ
from ark_relay.core.ledger import manual_stop
from ark_relay.core.desktop import Desktop, kill

# Public names of gameupdate_games and gameupdate_maaend are re-exported; the
# private names imported here are used by this module (_store, _UA) or by callers
# (_OFF_RECORDS: machinechecks/system.py).
from ark_relay.features.gameupdate.gameupdate_games import AK_ACTIVITY, AK_APK_URL, AK_PACKAGE, AK_VERSION_URL, READY_WORDS, _UA, _store, adb_device, adb_of, ak_prewarm, ak_prewarm_owed, ak_recorded_day, download, emulator_boot, emulator_quit, emulator_shortcut, endfield_paths, installed_ak_version, ldconsole_of, record_ak_version, recorded_ak_version, remote_ak_version, update_arknights, update_endfield, update_wuwa, wait_ready, wuwa_launcher
from ark_relay.features.gameupdate.gameupdate_maaend import SPMED_NODE, SPMED_NODE_V232, SPMED_NODES, _OFF_RECORDS, _TASK_ZH, maaend_enable, maaend_reenable_records, spmed_check, spmed_shape  # noqa: F401

log = logging.getLogger("ark.gameupdate")

__all__ = [
    "AK_ACTIVITY",
    "AK_APK_URL",
    "AK_PACKAGE",
    "AK_VERSION_URL",
    "READY_WORDS",
    "SPMED_NODE",
    "SPMED_NODES",
    "SPMED_NODE_V232",
    "adb_device",
    "adb_of",
    "ak_prewarm",
    "boot_check",
    "clear_pending",
    "download",
    "emulator_boot",
    "emulator_quit",
    "emulator_shortcut",
    "endfield_paths",
    "in_maintenance",
    "installed_ak_version",
    "last_run_ok",
    "last_trace",
    "ldconsole_of",
    "log",
    "maaend_enable",
    "maaend_reenable_records",
    "mark_pending",
    "mark_run",
    "needs_rerun",
    "off",
    "pending",
    "record_ak_version",
    "recorded_ak_version",
    "remote_ak_version",
    "restore_skips",
    "run_deferred",
    "save_windows",
    "should_run",
    "skips",
    "spmed_check",
    "spmed_shape",
    "stopped_today",
    "update_arknights",
    "update_endfield",
    "update_wuwa",
    "wait_ready",
    "windows",
    "wuwa_launcher",
    "wuwa_update_day",
]


# ─────────────────────────── scheduling ───────────────────────────

def should_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> bool:
    """True unless the check already ran in this boot (a service restart within
    one boot does not count as a new boot)."""
    if not state_dir:
        return False
    d = _store(state_dir).get("updates", "gameupdate")
    return not isinstance(d, dict) or d.get("boot") != boot_id


def mark_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> None:
    if state_dir:
        _store(state_dir).set("updates", "gameupdate",
                              {"boot": boot_id, "at": now.isoformat()})


# ─────────────────── register which game needs updating ───────────────────
# The boot only registers; run_deferred updates after the queue has finished.

def pending(state_dir: Path) -> dict[str, str]:
    """{game: why}."""
    d = _store(state_dir).get("updates", "gameupdate_pending")
    return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}


def mark_pending(state_dir: Path, game: str, why: str) -> bool:
    """Register one entry; a game already registered is not registered twice.
    Returns whether this was a new registration."""
    d = pending(state_dir)
    if game in d:
        return False
    d[game] = why
    _store(state_dir).set("updates", "gameupdate_pending", d)
    log.info("游戏更新：已登记 %s 待更新（%s）", game, why)
    return True


def clear_pending(state_dir: Path, game: str) -> None:
    d = pending(state_dir)
    if game in d:
        d.pop(game)
        _store(state_dir).set("updates", "gameupdate_pending", d)


def _last_today(state_dir: Path, now: datetime, script: str) -> dict | None:
    """Today's last ledger line of this script, manual stops skipped."""
    last = None
    for e in _today(state_dir, now):
        if e.get("script") == script and not manual_stop(e):
            last = e
    return last


def last_run_ok(state_dir: Path, now: datetime, script: str) -> bool | None:
    """Whether this script's last round today succeeded; None when it has not run
    today. A round stopped by the red button (core.ledger.manual_stop) is
    skipped: the one before it decides."""
    last = _last_today(state_dir, now, script)
    return None if last is None else bool(last.get("ok"))


def _today(state_dir: Path, now: datetime) -> list[dict]:
    p = Path(state_dir) / f"ledger-{now:%Y-%m-%d}.jsonl"
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    # Parsed line by line, so one torn line (power-off mid-append) skips only that
    # line. core.State.read_ledger is the reader that reports torn lines.
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


# The ledger flag per script that says "could not get into the game". Nothing sets
# maa_unreachable at present (collector_maa does not write it), so an MAA run is
# re-run only when it was taken out of the queue or failed during maintenance.
_UNREACHABLE_FLAG = {"MaaEnd": "maaend_unreachable", "OK-WW": "okww_unreachable",
                     "MAA": "maa_unreachable"}


def stopped_today(state_dir: Path, now: datetime, script: str) -> str:
    """The red button's label (「HH:MM 停一切」) when a run of this script was cut
    short by it today, else ''.

    A script the operator stopped with the red button today is not re-run after
    a client update (_rerun_script; the daily report says 「已停，未补」).
    """
    for e in _today(state_dir, now):
        if e.get("script") == script and manual_stop(e):
            return str((e.get("raw") or {}).get("manual_stop"))
    return ""


def needs_rerun(state_dir: Path, now: datetime, script: str) -> bool:
    """Whether the script should be re-run after its client update.

    True when it was taken out of today's queue, or today's last round failed
    with the "could not get into the game" flag (_UNREACHABLE_FLAG) or during
    maintenance. An ordinary task failure is not re-run: a re-run would fail
    again and take the account from the user for nothing. False when the
    operator stopped it today (stopped_today).
    """
    if stopped_today(state_dir, now, script):
        return False
    if any(r.get("script") == script for r in skips(state_dir)):
        return True                     # taken out of today's queue
    last = _last_today(state_dir, now, script)   # manual stops are skipped
    if last is None or last.get("ok"):
        return False
    raw = last.get("raw") or {}
    return bool(raw.get(_UNREACHABLE_FLAG.get(script, "")) or raw.get("maintenance"))


def off(state_dir: Path) -> bool:
    """Master switch: when state.json's updates.gameupdate_off is true, none of this runs."""
    return bool(_store(state_dir).get("updates", "gameupdate_off"))


# ─────────── Wuthering Waves: the maintenance day named in the official notice ───────────
_WW_NOTICE_URL = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
                  "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
_WW_MAINT = re.compile(r"更新维护时间[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日")


def wuwa_update_day(now: datetime, fetch=None, problems: list | None = None) -> str:
    """Returns the evidence sentence when the newest 「版本内容说明」 notice names today
    as the maintenance day; otherwise an empty string.

    The notice goes up a few days ahead and always in the same form:
    「更新维护时间：2026年8月20日04:00 ~ …」 (checked 2026-09-02). One HTTP request; the
    launcher is not opened.

    An unreadable notice is not "today is not the maintenance day": it is said in
    `problems` (boot_check's list, pushed as 「游戏更新没能确认」).
    """
    try:
        data = fetch() if fetch else json.loads(
            urllib.request.urlopen(urllib.request.Request(
                _WW_NOTICE_URL, headers={"User-Agent": _UA}), timeout=20).read())
        items = [(str(n.get("tabTitle") or ""), str(n.get("content") or ""))
                 for n in (data.get("game") or []) if "版本内容说明" in str(n.get("tabTitle") or "")]
        from ark_relay.features.banners.banners import newest_version  # noqa: PLC0415
        body = newest_version(items)
        m = _WW_MAINT.search(re.sub(r"<[^>]+>", " ", body))
        if not m:
            # Say what was read: the 2026-09-30 boot check left no trace of why the
            # maintenance day was missed, so every "no" names its evidence.
            log.info("游戏更新：鸣潮公告——%d 条「版本内容说明」，最新那条里没找到「更新维护时间」",
                     len(items))
            return ""
        y, mo, d = (int(x) for x in m.groups())
        if (y, mo, d) == (now.year, now.month, now.day):
            ver = next((t for t, _ in items if body == dict(items).get(t)), "")
            return f"官方公告：今天更新维护（{ver.strip().splitlines()[-1] if ver else '新版本'}）"
        log.info("游戏更新：鸣潮公告——维护日写的是 %d-%02d-%02d，今天不是维护日", y, mo, d)
    except Exception:  # only a signal, but a silent one hid 2026-09-30: say why
        log.warning("游戏更新：鸣潮公告读不到或看不懂，今天是不是维护日不知道", exc_info=True)
        if problems is not None:
            problems.append("鸣潮：官方公告读不到，今天是不是维护日不知道")
        return ""
    return ""


# ─────────────────────── boot: only the cheap checks ───────────────────────

def boot_check(cfg, *, budget_s: float, now: datetime | None = None,
               hint=None, fetch=None, wuwa_fetch=None, maint_sources=None,
               skipper=None) -> tuple[list[str], list[str]]:
    """The boot window's checks. Returns (notes, problems).

    Arknights: the official version differs from the recorded one -> register;
    no version recorded yet -> start the emulator once to record it
    (update_arknights).
    Endfield: the notice says there is a version update today -> register; the
    launcher is not opened.
    Wuthering Waves: the notice names today as the maintenance day -> register
    (OK-WW does not press the launcher's update button).
    Maintenance bulletins: save today's windows, register the game, and take its
    script out of queues that fall inside the window.
    """
    now = now or datetime.now(tz=SERVER_TZ)
    notes: list[str] = []
    problems: list[str] = []
    # Scripts taken out of a queue on an earlier day (or with no day recorded) go
    # back first; the maintenance step below takes them out again if today needs it.
    if done := restore_skips(cfg.state_dir, before_day=now.strftime("%Y-%m-%d")):
        log.warning("游戏更新：之前为更新从队列里摘掉、一直没加回的，开机加回了：%s", "、".join(done))
    if off(cfg.state_dir):
        log.info("游戏更新：总开关关着（state.json 的 updates.gameupdate_off），不检查")
        return notes, problems
    ld, idx = ldconsole_of(cfg.maa_dir)
    if ld:
        try:
            remote = remote_ak_version(fetch)
            local = recorded_ak_version(cfg.state_dir)
            if remote and local and remote != local:
                # The user, 2026-09-02: 「你能保证 10 分钟之内更新完吗？」 No. Always defer.
                mark_pending(cfg.state_dir, "明日方舟", f"官方版本 {remote}，已装 {local}")
            elif remote and not local:
                # First time: start the emulator to record the installed version (~1 min)
                if n := update_arknights(cfg.state_dir, ld, idx, budget_s=min(budget_s, 300),
                                         problems=problems, fetch=fetch):
                    notes.append(n)
            elif not remote:
                # An empty clientVersion is "unknown", not "up to date": update_arknights
                # says the same thing in the same words (gameupdate_games.py).
                log.warning("游戏更新：明日方舟官方版本信息里没有客户端版本号，查不了要不要更新")
                problems.append("明日方舟：官方的版本信息里没有客户端版本号")
            else:
                log.info("游戏更新：明日方舟已是 %s，无需更新", remote)
        except Exception:
            log.exception("游戏更新：明日方舟开机检查出错")
            problems.append("明日方舟：开机检查出错（见日志）")
    from ark_relay.features.maintenance import efstatus  # noqa: PLC0415
    n0 = now.replace(tzinfo=None) if now.tzinfo else now
    try:
        # strict: without it update_hint returns "" on any error, the same answer
        # as "no update today".
        h = hint(n0) if hint else efstatus.update_hint(n0, strict=True)
    except Exception:  # unknown, not "no update today"
        log.warning("游戏更新：终末地公告读不到，今天有没有版本更新不知道", exc_info=True)
        problems.append("终末地：官方公告读不到，今天有没有版本更新不知道")
        h = None
    # _register_if_due does not register a script that already succeeded today.
    # Every branch logs one line.
    if h:
        _register_if_due(cfg.state_dir, now, "终末地", "MaaEnd", h, "公告")
    elif h is not None:  # None = unreadable, already said above
        log.info("游戏更新：终末地公告——今天没有版本更新")
    # wuwa_update_day logs its own "not today" line with the date it read
    if w := wuwa_update_day(n0, fetch=None if wuwa_fetch is None else wuwa_fetch, problems=problems):
        _register_if_due(cfg.state_dir, now, "鸣潮", "OK-WW", w, "公告")
    # The official maintenance bulletins (maintenance.py): for a game under
    # maintenance today, save the window and register the game; run_deferred waits
    # for the servers, updates and re-runs.
    # For a bulletin that could not be read, the window saved earlier today stays
    # (handle._maintenance_today and in_maintenance read it).
    failed: list[str] | None = []
    try:
        from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
        wins = maintenance.today(now, sources=maint_sources, failed=failed)
    except Exception:  # logged below
        log.warning("游戏更新：维护公告整体读不到", exc_info=True)
        wins, failed = {}, None            # None: every game unread
    wins = {**_kept_windows(cfg.state_dir, now, wins, failed), **wins} if failed != [] else wins
    save_windows(cfg.state_dir, wins)
    fresh = {g: w for g, w in wins.items() if failed is not None and g not in failed}
    _log_windows(wins, fresh, failed)
    for game, (start, end, why) in fresh.items():
        script = maintenance.SCRIPT_OF[game]
        if not _register_if_due(cfg.state_dir, now, game, script, why, "维护"):
            continue
        # A queue time from 30 minutes before the window to 45 minutes after it
        # (time for the client update): take the script out of that queue through
        # the AUTO-MAS API; restore_skips puts it back after the re-run.
        for q in _queues_today(cfg.automas_dir, now):
            for due in q["dues"]:
                if start - timedelta(minutes=30) <= due <= end + timedelta(minutes=45):
                    try:
                        rec = skipper(q["name"], script) if skipper else _skip_default(q["name"], script)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"{game}：从队列「{q['name']}」摘掉 {script} 失败（{exc}）")
                        continue
                    if rec:
                        rec["why"] = why
                        _add_skip(cfg.state_dir, rec)
                        log.info("游戏更新：%s 维护（%s），今天从队列「%s」摘掉 %s", game, why, q["name"], script)
                    break
    return notes, problems


def _kept_windows(state_dir: Path, now: datetime, wins: dict,
                  failed: list[str] | None) -> dict:
    """Saved windows still covering today for the games whose bulletin could not be
    read this time (failed=None: none could)."""
    day = now.date()
    return {g: w for g, w in windows(state_dir).items()
            if g not in wins and (failed is None or g in failed)
            and w[0].date() <= day <= w[1].date()}


def _log_windows(wins: dict, fresh: dict, failed: list[str] | None) -> None:
    """One line on what the maintenance bulletins said, never 「没有维护」 for one
    that could not be read."""
    def _span(ws: dict) -> str:
        return "、".join(f"{g} {s:%H:%M}–{e:%H:%M}" for g, (s, e, _w) in ws.items())
    if failed == []:
        log.info("游戏更新：维护公告——%s", _span(wins) or "今天没有游戏停服维护")
        return
    kept = {g: w for g, w in wins.items() if g not in fresh}
    who = "全部" if failed is None else "、".join(failed)
    log.warning("游戏更新：维护公告读不到（%s），沿用已存窗口：%s；读到的：%s", who,
                _span(kept) or "今天没存过", _span(fresh) or ("—" if failed is None else "今天没有停服维护"))


def _register_if_due(state_dir: Path, now: datetime, game: str, script: str,
                     why: str, source: str) -> bool:
    """`why` says today is the game's update/maintenance day: register it unless
    the script already succeeded today (a manual stop does not count). Logs one
    line whichever way it goes (mark_pending logs a new registration); returns
    whether the day is due (registered now or before)."""
    if last_run_ok(state_dir, now, script) is True:
        log.info("游戏更新：%s%s——%s，但 %s 今天已成功过，不登记", game, source, why, script)
        return False
    if not mark_pending(state_dir, game, why):
        log.info("游戏更新：%s%s——%s，之前已登记", game, source, why)
    return True


def _skip_default(queue: str, script: str):
    from ark_relay.features.phone import commands  # noqa: PLC0415
    return commands.skip_script_in_queue(queue, script)


def _queues_today(automas_dir, now: datetime) -> list[dict]:
    """Today's queue times that have not come yet: [{name, dues:[datetime]}]."""
    from ark_relay.core import plan  # noqa: PLC0415
    out = []
    for q in plan.schedule(automas_dir) if automas_dir else []:
        dues = []
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due >= now:
                dues.append(due)
        out.append({"name": q["name"], "dues": dues})
    return out


def skips(state_dir: Path) -> list[dict]:
    d = _store(state_dir).get("updates", "queue_skips")
    return list(d) if isinstance(d, list) else []


def _add_skip(state_dir: Path, rec: dict) -> None:
    lst = skips(state_dir)
    if not any(r.get("queueId") == rec.get("queueId") and r.get("scriptId") == rec.get("scriptId") for r in lst):
        lst.append(rec)
    _store(state_dir).set("updates", "queue_skips", lst)


def restore_skips(state_dir: Path, restorer=None, before_day: str = "") -> list[str]:
    """Put back every script taken out of a queue (with `before_day`, only those
    taken out on an earlier day or with no day); returns which ones. Only the
    ones put back are dropped from the record, so a failure is retried next call."""
    from ark_relay.features.phone import commands  # noqa: PLC0415
    restorer = restorer or commands.restore_script_in_queue
    left, done = [], []
    for rec in skips(state_dir):
        if before_day and str(rec.get("day") or "") >= before_day:
            left.append(rec)
            continue
        try:
            if restorer(rec):
                done.append(f"{rec['script']}→「{rec['queue']}」")
                continue
        except Exception:
            log.exception("加回队列失败：%s", rec)
        left.append(rec)
    _store(state_dir).set("updates", "queue_skips", left)
    return done


def save_windows(state_dir: Path, wins: dict) -> None:
    _store(state_dir).set("updates", "maintenance_windows",
        {g: {"start": w[0].isoformat(), "end": w[1].isoformat(), "why": w[2]} for g, w in wins.items()})


def windows(state_dir: Path) -> dict[str, tuple[datetime, datetime, str]]:
    d = _store(state_dir).get("updates", "maintenance_windows")
    if not isinstance(d, dict):
        return {}
    try:
        return {g: (datetime.fromisoformat(v["start"]), datetime.fromisoformat(v["end"]), str(v.get("why") or ""))
                for g, v in d.items()}
    except (ValueError, KeyError, TypeError):
        return {}


def in_maintenance(state_dir: Path, script: str, at: datetime) -> str:
    """Whether `at` falls in this script's saved maintenance window, from 30 minutes
    before it to 45 minutes after it. Returns the evidence sentence, or ''."""
    from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
    game = next((g for g, s in maintenance.SCRIPT_OF.items() if s == script), "")
    w = windows(state_dir).get(game)
    if not w:
        return ""
    start, end, why = w
    if start - timedelta(minutes=30) <= at.astimezone(start.tzinfo) <= end + timedelta(minutes=45):
        return why
    return ""


# ─────────────── after the queue finishes: update + re-run ───────────────

def _prepare_client(cfg, desk: Desktop, game: str, problems: list[str], sleep,
                    clock=None) -> tuple[bool, str]:
    """Update one game's client through to the login screen. Returns (ready,
    notification sentence); when not ready, the reason is in problems."""
    before = len(problems)
    if game == "终末地":
        g, l = endfield_paths(cfg.maaend_dir)
        if not (g and l):
            problems.append("终末地：找不到启动器"); return False, ""
        n = update_endfield(desk, g, l, budget_s=2400, problems=problems, sleep=sleep)
    elif game == "鸣潮":
        l = wuwa_launcher(cfg.okww_dir)
        if not l:
            problems.append("鸣潮：找不到启动器"); return False, ""
        n = update_wuwa(desk, l, budget_s=2400, problems=problems, sleep=sleep)
    else:
        ld, idx = ldconsole_of(cfg.maa_dir)
        if not ld:
            problems.append("明日方舟：找不到雷电 ldconsole"); return False, ""
        end = (windows(cfg.state_dir).get("明日方舟") or (None, None, ""))[1]
        n = update_arknights(cfg.state_dir, ld, idx, budget_s=1800, problems=problems, sleep=sleep, desk=desk,
                             maa_dir=cfg.maa_dir, maint_end=end, clock=clock)
    return len(problems) == before, n


def _prepare_until_ready(cfg, desk: Desktop, game: str, *, deadline: datetime, clock, sleep,
                         problems: list[str], expect_new: bool,
                         local0: str) -> tuple[bool, str]:
    """Update every 10 minutes until the client is ready or the deadline passes.
    Returns (ready, every round's notification sentence joined).

    A round that is not ready has all the problems it wrote removed before the
    next round, so only the last round's problems reach the report.
    """
    ready, note = False, ""
    outdated = False
    said: list[str] = []     # every round's sentence, so an earlier round's 「已更新」 is kept
    while True:
        mark = len(problems)
        ready, note = _prepare_client(cfg, desk, game, problems, sleep, clock=clock)
        if note and note not in said:
            said.append(note)
        if outdated and ready and not note:
            # An earlier round's game said its client was outdated; a later "no update
            # needed" from the launcher is the same client, not a ready one.
            ready = False
            problems.append(f"{game}：更新后游戏说客户端已过时，启动器却显示无需更新，客户端没准备好")
        owed = ak_prewarm_owed(cfg.state_dir) if game == "明日方舟" else ""
        if owed and ready:
            # Installed, but not yet started to the login screen: during maintenance the
            # notice covers it (2026-10-09). A wait, not a problem.
            ready = False
            log.info("游戏更新：明日方舟 %s 已装，还没进游戏预热，10 分钟后再看", owed)
        elif (game == "明日方舟" and expect_new and ready and not note
              and ak_recorded_day(cfg.state_dir) != clock().strftime("%Y-%m-%d")):
            # prepare saying "no update needed" = the official version number has not
            # changed yet (during maintenance the package is not out), so keep waiting.
            # Not when the new version went in today: on 2026-10-09 the round after the
            # install (10:05:03) read as 「还是 2.7.71」 and would have waited to 14:00.
            ready = False
            if not problems or "版本号还没变" not in problems[-1]:
                problems.append(f"明日方舟：官方版本号还没变（还是 {local0}），维护中包体还没放出来")
        if ready or clock() >= deadline:
            break
        # Not ready (often the update package is not out yet): drop every problem
        # this round wrote - one round can write several - and retry in 10 minutes.
        log.info("游戏更新：%s 还没准备好（%s），10 分钟后再试", game, problems[-1] if problems else "")
        outdated = outdated or any("客户端已过时" in p for p in problems[mark:])
        del problems[mark:]
        sleep(600)
    return ready, "；".join(said)


def _rerun_script(cfg, now: datetime, dispatch, script: str,
                  reran: list[str], problems: list[str], notes: list[str] | None = None) -> None:
    """Once the client is updated, re-run the script when needs_rerun says so.

    A script the red button stopped today is not re-run (stopped_today); that is
    said in `notes`, not `problems`.
    """
    if stop := stopped_today(cfg.state_dir, now, script):
        log.info("游戏更新：%s 今天被停一切停过（%s），不自动补跑", script, stop)
        if notes is not None:
            notes.append(f"{script}：今天 {stop}停过，已停，未补")
        return
    if needs_rerun(cfg.state_dir, now, script) and dispatch is not None:
        ok, msg = dispatch(script)
        log.info("游戏更新：补跑 %s → %s", script, msg)
        if ok:
            reran.append(script)
        else:
            problems.append(f"{script}：更新后没能补跑（{msg}）")


def run_deferred(cfg, *, now: datetime | None = None, desk: Desktop | None = None,
                 dispatch=None, sleep=time.sleep, clock=None) -> tuple[list[str], list[str], list[str]]:
    """Work through everything registered. Returns (update notices, problems, scripts
    that were re-run).

    Runs after the queue: update each registered game's client up to its login
    screen (READY_WORDS) without waiting for the servers; once ready, if the
    servers return more than 10 minutes later, close the game; wait for the
    servers, then re-run. A client that is not ready is retried every 10 minutes,
    up to 2 hours after the maintenance window ends (1 hour from now without a
    window). Scripts taken out of queues are put back on every way out.
    """
    now = now or datetime.now(tz=SERVER_TZ)
    clock = clock or (lambda: datetime.now(tz=SERVER_TZ))
    notes: list[str] = []
    problems: list[str] = []
    reran: list[str] = []
    _LAST_DESK[0] = desk
    todo = pending(cfg.state_dir)
    if not todo or off(cfg.state_dir):
        if done := restore_skips(cfg.state_dir):
            log.info("游戏更新：已把摘掉的加回队列：%s", "、".join(done))
        return notes, problems, reran
    try:
        _work_deferred(cfg, now, todo, desk, dispatch, sleep, clock, notes, problems, reran)
    finally:
        if done := restore_skips(cfg.state_dir):
            log.info("游戏更新：已把摘掉的加回队列：%s", "、".join(done))
    return notes, problems, reran


# The Desktop of the latest run_deferred. Its trace (Desktop.trace) is every screen
# that run read; engine._maybe_deferred_update hands it to the machine checks.
_LAST_DESK: list = [None]


def last_trace() -> list[dict]:
    """Every screen the latest run_deferred read and what its flows made of them; [] when none."""
    return list(getattr(_LAST_DESK[0], "trace", None) or [])


def _work_deferred(cfg, now, todo, desk, dispatch, sleep, clock, notes, problems, reran) -> None:
    desk = desk or Desktop(cfg.state_dir)
    _LAST_DESK[0] = desk
    wins = windows(cfg.state_dir)
    from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
    for game, why in list(todo.items()):
        script = maintenance.SCRIPT_OF.get(game, "")
        start, end = (wins.get(game) or (None, None, ""))[:2]
        deadline = (end + timedelta(hours=2)) if end else clock() + timedelta(hours=1)
        expect_new = bool(end)              # a maintenance window today means a new version
        local0 = recorded_ak_version(cfg.state_dir) if game == "明日方舟" else ""
        ready, note = _prepare_until_ready(cfg, desk, game, deadline=deadline, clock=clock,
                                           sleep=sleep, problems=problems,
                                           expect_new=expect_new, local0=local0)
        if note:
            notes.append(note + f"（依据：{why}）")
        if not ready:
            problems.append(f"{game}：到 {deadline:%m-%d %H:%M} 仍没准备好客户端，今天不补跑")
            continue
        # Ready. Servers still down: close the game when they are more than 10
        # minutes away, wait for them, then re-run.
        if end and clock() < end:
            if end - clock() > timedelta(minutes=10):
                kill("Endfield.exe", "Client-Win64-Shipping.exe")
            log.info("游戏更新：%s 客户端已就绪，等 %s 开服再补跑", game, end.strftime("%H:%M"))
            while clock() < end:
                sleep(60)
            sleep(120)
        _rerun_script(cfg, now, dispatch, script, reran, problems, notes)
        clear_pending(cfg.state_dir, game)
