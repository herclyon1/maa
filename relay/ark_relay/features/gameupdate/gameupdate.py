"""On a major-version update day, update the three game clients ourselves.

The user, 2026-09-02: 「大版本鸣潮和终末地都有启动器去更新，明日方舟是通过模拟器
里面去更新安装包然后再手动点进去更新……希望你能帮我实现自动化。」

Every step logs its conclusion; anything that could not be confirmed goes into problems,
and the caller pushes 「⚠️ 没能确认」.

What is left in this file is the part that does not fork per game: the boot window's
two cheap HTTP checks (boot_check), the register-now / update-later bookkeeping, the
official maintenance windows, and the after-the-queue flow (run_deferred) that updates
a client and re-runs the script whose round failed. The three update flows themselves
were moved to gameupdate_games.py on 2026-09-08 (verbatim) - that module's docstring
describes how each launcher is driven, and every public name of it is re-exported here,
so callers and tests still write gameupdate.xxx.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from ark_relay.core.config import SERVER_TZ
from ark_relay.core.ledger import manual_stop
from ark_relay.core.desktop import Desktop, kill
from ark_relay.core.config import atomic_write_text

# Only public names are forwarded. The two private helpers this file needs
# (_store, _UA) are imported from the module they live in rather than re-exported,
# the same rule preupdate.py settled on: a facade that also re-exports privates
# announces "these are yours to use" and stops __all__ from describing the interface.
from ark_relay.features.gameupdate.gameupdate_games import AK_ACTIVITY, AK_APK_URL, AK_PACKAGE, AK_VERSION_URL, READY_WORDS, _UA, _store, adb_device, adb_of, ak_prewarm, ak_prewarm_owed, ak_recorded_day, download, emulator_boot, emulator_quit, emulator_shortcut, endfield_paths, installed_ak_version, ldconsole_of, record_ak_version, recorded_ak_version, remote_ak_version, update_arknights, update_endfield, update_wuwa, wait_ready, wuwa_launcher

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
    """Runs once per boot; never twice within one boot (a deploy restarting the
    service is not a new boot)."""
    if not state_dir:
        return False
    d = _store(state_dir).get("updates", "gameupdate")
    return not isinstance(d, dict) or d.get("boot") != boot_id


def mark_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> None:
    if state_dir:
        _store(state_dir).set("updates", "gameupdate",
                              {"boot": boot_id, "at": now.isoformat()})


# ─────────────────── register which game needs updating ───────────────────
# The user, 2026-09-02: 「预更新的窗口只有几分钟，更新游戏来不及。检测到有更新之后
# 直接先跳过这个游戏，等所有其他游戏跑完之后，再单独拉这个游戏进行更新，
# 然后再去重跑。」 So: the boot only registers, and the engine does the work once the
# queue has finished (run_deferred).

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


def _manual_stop(e: dict) -> bool:
    """A run the red button (停一切) cut short: neither a success nor a failure
    here either (core.manual_stop, the one definition every reader shares).

    2026-09-30: OK-WW failed 09:19 and 09:30 on the WuWa 3.7 maintenance day,
    the 09:46 press stopped the next run and AUTO-MAS logged it Success!; read as
    today's last round, that "success" kept the maintenance day from being
    registered, and WuWa was not played that day.
    """
    return manual_stop(e)


def _last_today(state_dir: Path, now: datetime, script: str) -> dict | None:
    """Today's last ledger line of this script, manual stops skipped."""
    last = None
    for e in _today(state_dir, now):
        if e.get("script") == script and not _manual_stop(e):
            last = e
    return last


def last_run_ok(state_dir: Path, now: datetime, script: str) -> bool | None:
    """Whether this script's last round today succeeded; None when it has not run
    today. A round the red button stopped is skipped (_manual_stop): the one
    before it decides."""
    last = _last_today(state_dir, now, script)
    return None if last is None else bool(last.get("ok"))


def _today(state_dir: Path, now: datetime) -> list[dict]:
    p = Path(state_dir) / f"ledger-{now:%Y-%m-%d}.jsonl"
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    # Line by line, as core.State.read_ledger does: one torn line (hard power-off
    # mid-append) used to empty the whole day here, so a red-button stop was
    # forgotten and an owed re-run skipped. read_ledger is the one that reports it.
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


# "MAA": the consumer side only. collector_maa does not set maa_unreachable yet
# (2026-10-06 audit), so until it does, an MAA run is re-run after an update only
# when it was pulled from the queue or failed during maintenance.
_UNREACHABLE_FLAG = {"MaaEnd": "maaend_unreachable", "OK-WW": "okww_unreachable",
                     "MAA": "maa_unreachable"}


def stopped_today(state_dir: Path, now: datetime, script: str) -> str:
    """The red button's label (「HH:MM 停一切」) when a run of this script was cut
    short by it today, else ''.

    Settled 2026-09-30 18:04: once the operator has stopped a script with the red
    button, the run it cut short and every later run of that script that day are
    not re-dispatched automatically after a client update - an automatic re-run
    would start again exactly what he stopped. The daily report says 「已停，未补」.
    """
    for e in _today(state_dir, now):
        if e.get("script") == script and _manual_stop(e):
            return str((e.get("raw") or {}).get("manual_stop"))
    return ""


def needs_rerun(state_dir: Path, now: datetime, script: str) -> bool:
    """Only "today's last round failed because an outdated client could not get into
    the game" is worth re-running after an update.

    The incident on the evening of 2026-09-02: four MaaEnd tasks genuinely failed
    because upstream had not adapted to the new version; I dispatched it again on the
    rule "the last round did not succeed, so re-run", and it kicked the user off the
    account while he was playing. An ordinary task failure fails again on a re-run and
    only steals the account for nothing - that kind of failure is not the update's
    business.
    """
    if stopped_today(state_dir, now, script):
        return False                    # the operator stopped it today: see stopped_today
    if any(r.get("script") == script for r in skips(state_dir)):
        return True                     # pulled from today's queue: must be re-run
    last = _last_today(state_dir, now, script)   # a manual stop is skipped, see _manual_stop
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
    """What the boot window does: one HTTP read of the Arknights version, one HTTP read
    of the Endfield notice.

    Arknights version differs: install on the spot when the window is long enough
    (>= 10 minutes), otherwise register it.
    Endfield notice says there is a version update today: register it; the launcher is
    never opened once.
    Wuthering Waves: register when the notice names today as the maintenance day (OK-WW
    only clicks the in-game 「即将重启」, never 「更新」 on the launcher - pointed out by
    the user on 2026-09-02).
    """
    now = now or datetime.now(tz=SERVER_TZ)
    notes: list[str] = []
    problems: list[str] = []
    # A pull from an earlier day (or with no day: written before records carried
    # one) outlived its re-run - relay crash, power-off before the queue ended,
    # the switch turned off. Back in before anything else; if today needs it out
    # again, the maintenance step below pulls it again.
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
        # strict: update_hint on its own swallows every error and returns "", the
        # same answer as "no update today" - so this except never ran on the machine.
        h = hint(n0) if hint else efstatus.update_hint(n0, strict=True)
    except Exception:  # unknown, not "no update today" (a silent miss hid 2026-09-30)
        log.warning("游戏更新：终末地公告读不到，今天有没有版本更新不知道", exc_info=True)
        problems.append("终末地：官方公告读不到，今天有没有版本更新不知道")
        h = None
    # Do not register when it already succeeded today; an ordinary task failure is
    # not the update's business either (needs_rerun blocks that a second time).
    # Every branch logs one line: on 2026-09-30 the boot check went silent after
    # the Arknights line and nobody could tell which way WuWa had gone.
    if h:
        _register_if_due(cfg.state_dir, now, "终末地", "MaaEnd", h, "公告")
    elif h is not None:  # None = unreadable, already said above
        log.info("游戏更新：终末地公告——今天没有版本更新")
    # wuwa_update_day logs its own "not today" line with the date it read
    if w := wuwa_update_day(n0, fetch=None if wuwa_fetch is None else wuwa_fetch, problems=problems):
        _register_if_due(cfg.state_dir, now, "鸣潮", "OK-WW", w, "公告")
    # The three official maintenance notices (maintenance.py): for a game under
    # maintenance today, persist the window and register it. Settled by the user on
    # 2026-09-02: maintenance does not count as a failure; after the queue finishes, wait
    # for the servers to come back, update, re-run, and only then power off.
    # A bulletin that could not be read is not "no maintenance": the window saved
    # earlier today stays (handle._maintenance_today and in_maintenance read it, and
    # an emptied window turns a maintenance-hour failure into a real alarm).
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
        # The user, 2026-09-03: 「当天队列里不跑他」. Where today's queue time falls
        # inside the maintenance window (plus 45 minutes after the servers return, for
        # the client update), pull the script out of the queue through the API and add
        # it back after the re-run (restore_skips). Pull and restore were measured to be
        # reversible on the morning shift on 09-03.
        from datetime import timedelta as _td  # noqa: PLC0415
        for q in _queues_today(cfg.automas_dir, now):
            for due in q["dues"]:
                if start - _td(minutes=30) <= due <= end + _td(minutes=45):
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
    the script already succeeded today (a manual stop does not count, see
    _manual_stop). Logs one line whichever way it goes (mark_pending logs a new
    registration); returns whether the day is due (registered now or before)."""
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
    """Add back everything pulled (with `before_day`, only pulls from an earlier day
    or without a day); returns which ones. Every call retries, and only the ones
    that succeed are dropped from the record."""
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
    """Whether this script hits an official maintenance window at this moment (plus a
    45-minute grace after the servers return, for the client update). Returns the
    evidence sentence, or an empty string when it does not."""
    from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415
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
    """Update through to the login screen. Returns (ready, notification sentence). When
    it is not ready, the reason is in problems.

    Its own step because this is the only place in the whole flow that forks per game -
    launcher, time budget and the "counts as ready" test all differ between the three.
    With it pulled out, the main flow is a straight line: wait until ready -> wait for
    the servers -> re-run.
    """
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
    """Update over and over until the client is ready or the deadline passes. Returns
    (ready, notification sentence).

    Its own step because the retry here hides a rule that is easy to get wrong: on every
    failed round, **every** entry that round wrote into problems has to be taken back as
    a batch, cut at mark (the reason is in the comment at the end of the loop). That is a
    separate matter from the outer "what to do once it is ready", and mixing the two into
    one function makes the rule hard to see.
    """
    ready, note = False, ""
    outdated = False
    said: list[str] = []     # every round's sentence: round one's 「已更新」 must survive round two
    while True:
        mark = len(problems)
        ready, note = _prepare_client(cfg, desk, game, problems, sleep, clock=clock)
        if note and note not in said:
            said.append(note)
        if outdated and ready and not note:
            # An earlier round installed the update and the game still said its client
            # was outdated. The launcher now shows 「开始游戏」 and prepare says "no
            # update needed" - that is the same broken client, not a ready one.
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
        # The update package is most likely not out yet: take this round's problems
        # back as a batch and try again in 10 minutes.
        # Cut at mark rather than dropping only the last entry: one prepare can write two
        # (wrong version after install + login screen never read), and dropping one would
        # leave the other in the final report - reporting a failure even though it
        # succeeded later.
        log.info("游戏更新：%s 还没准备好（%s），10 分钟后再试", game, problems[-1] if problems else "")
        outdated = outdated or any("客户端已过时" in p for p in problems[mark:])
        del problems[mark:]
        sleep(600)
    return ready, "；".join(said)


def _rerun_script(cfg, now: datetime, dispatch, script: str,
                  reran: list[str], problems: list[str], notes: list[str] | None = None) -> None:
    """Once the client is updated, re-run the script whose round failed today.

    Its own step because "should it be re-run, and does the result count as success or
    as a problem" shares no state with the update wait above; it is a self-contained
    little job, and leaving it in the main loop only makes that loop longer.
    A script the red button stopped today is not re-run (stopped_today); that goes
    into `notes`, not `problems` - it is what the operator asked for.
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

    The order the user settled on 2026-09-03: **update the moment the queue finishes**
    (download, install, start the game to get through shader compilation - it only
    counts as ready at the 「点击任意位置继续」 login screen), without waiting for the
    servers to come back; once ready, if the servers are still more than 10 minutes
    away, close the game and re-run separately when the time comes. When the update
    package is not out yet (common during maintenance), retry every 10 minutes, up to
    2 hours past the servers returning.
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
        # Every way out - done, not ready, an exception - puts the pulled scripts back.
        if done := restore_skips(cfg.state_dir):
            log.info("游戏更新：已把摘掉的加回队列：%s", "、".join(done))
    return notes, problems, reran


# The desk of the latest run_deferred: its trace is every screen that update read
# (Desktop.trace), which the machine checks #60-#62 judge (engine._maybe_deferred_update).
_LAST_DESK: list = [None]


def last_trace() -> list[dict]:
    """Every screen the latest run_deferred read and what its flows made of them; [] when none."""
    return list(getattr(_LAST_DESK[0], "trace", None) or [])


def _work_deferred(cfg, now, todo, desk, dispatch, sleep, clock, notes, problems, reran) -> None:
    desk = desk or Desktop(cfg.state_dir)
    _LAST_DESK[0] = desk
    wins = windows(cfg.state_dir)
    from datetime import timedelta as _td  # noqa: PLC0415

    from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
    for game, why in list(todo.items()):
        script = maintenance.SCRIPT_OF.get(game, "")
        start, end = (wins.get(game) or (None, None, ""))[:2]
        deadline = (end + _td(hours=2)) if end else clock() + _td(hours=1)
        expect_new = bool(end)              # maintenance window = a new version today;
                                            # without one it does not count as ready
        local0 = recorded_ak_version(cfg.state_dir) if game == "明日方舟" else ""
        ready, note = _prepare_until_ready(cfg, desk, game, deadline=deadline, clock=clock,
                                           sleep=sleep, problems=problems,
                                           expect_new=expect_new, local0=local0)
        if note:
            notes.append(note + f"（依据：{why}）")
        if not ready:
            problems.append(f"{game}：到 {deadline:%m-%d %H:%M} 仍没准备好客户端，今天不补跑")
            continue
        # Ready. If the servers are still far off, close the game and wait; re-run
        # when the time comes
        if end and clock() < end:
            if end - clock() > _td(minutes=10):
                kill("Endfield.exe", "Client-Win64-Shipping.exe")
            log.info("游戏更新：%s 客户端已就绪，等 %s 开服再补跑", game, end.strftime("%H:%M"))
            while clock() < end:
                sleep(60)
            sleep(120)
        _rerun_script(cfg, now, dispatch, script, reran, problems, notes)
        clear_pending(cfg.state_dir, game)


# ───────── MaaEnd tasks the relay once switched off: back on, and never off again ─────────
# The user, 2026-10-06, on 应急理智加强剂 (switched off by hand on 2026-09-03 and kept
# off by this file until 「upstream fixed it」): 「那个要一直开着，如果上游maaend改了导致
# 没生效就要报警 ... 我开的任务是谁说要关的」. So nothing here decides to keep a task off
# any more. Three records may still sit in state.json from the time tasks were switched
# off (by hand on 2026-09-02 / 09-03, or for a make-up); at boot every task they name is
# switched back on at once, whatever the MaaEnd version, and the record goes.
# The booster step itself is only watched (spmed_check): when MaaEnd ships it in a form
# this file does not know, the group is told at every boot - the task stays on.

# Records that name MaaEnd tasks switched off at some point. The key the task names
# sit under: "disabled" is what the hand-written 1.5.3 record used, "tasks" is the
# shape statestore.py documents.
_OFF_RECORDS = ("maaend_disabled_1_5_3", "maaend_reenable_next_boot", "maaend_disabled_spmed")
_TASK_ZH = {"GiftOperator": "赠送干员礼物", "GearAssembly": "装备制造", "DeliveryJobs": "转交委托",
            "EnvironmentMonitoring": "环境监测", "AutoCollect": "自动采集",
            "AutoUseSpMedication": "应急理智加强剂"}


def maaend_enable(cfg, names: set) -> tuple[list[str], list[str], str]:
    """Switch the named tasks ON in the master mxu-MaaEnd.json - `enabled` and every
    per-controller copy of it (makeup._set_flag / maaend.py do the same). There is no
    way to switch a task off here.

    Returns (switched on now, named but not in the master at all, why it could not
    be done - '' when it was). "Already on" is in neither list."""
    root = Path(cfg.automas_dir) / "data" if cfg.automas_dir else None
    target = next((f for f in (root.glob("*/Default/ConfigFile/mxu-MaaEnd.json") if root else [])), None)
    if not target:
        return [], [], "找不到终末地的母本"
    try:
        j = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], [], f"终末地的母本读不出来（{type(exc).__name__}）"
    changed: list[str] = []
    seen: set[str] = set()
    for inst in j.get("instances") or []:
        for t in inst.get("tasks") or []:
            name = t.get("taskName")
            if name not in names:
                continue
            seen.add(name)
            ctl = t.get("enabledByController")
            ctl_off = (isinstance(ctl, dict) and not all(ctl.values())) or ctl is False
            if not t.get("enabled") or ctl_off:
                t["enabled"] = True
                if isinstance(ctl, dict):
                    for k in ctl:
                        ctl[k] = True
                elif isinstance(ctl, bool):
                    t["enabledByController"] = True
                if name not in changed:
                    changed.append(name)
    gone = sorted(set(names) - seen)
    if not changed:
        return [], gone, ""
    try:
        atomic_write_text(target, json.dumps(j, ensure_ascii=False, indent=2))
        back = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], gone, f"终末地的母本写不进去（{type(exc).__name__}）"
    off = sorted({str(t.get("taskName")) for inst in back.get("instances") or []
                  for t in inst.get("tasks") or [] if t.get("taskName") in changed and not t.get("enabled")})
    if off:
        return [], gone, "写进终末地的母本之后再读，这几项还是关着：" + "、".join(off)
    return changed, gone, ""


def maaend_reenable_records(cfg) -> list[str]:
    """Boot: switch every task a leftover switch-off record names back on, once, and
    drop the record. Returns the log lines (already logged).

    Switched on (or already on): INFO, record dropped. The master cannot be found or
    read: WARNING (a relay WARNING reaches the group), record kept for the next boot.
    A record naming no task, or tasks the master no longer has: WARNING with the
    record, record dropped (nothing is left to switch on)."""
    store = _store(cfg.state_dir)
    said: list[str] = []
    for key in _OFF_RECORDS:
        rec = store.get("updates", key)
        if rec is None:
            continue
        rec_d = rec if isinstance(rec, dict) else {}
        names = {str(n) for n in (rec_d.get("disabled") or rec_d.get("tasks") or []) if n}
        if not names:
            line = f"开机：中继以前关掉终末地任务的记录 {key} 里没有任务名（{rec!r}），没法开回，记录已删"
            log.warning(line)
            store.pop("updates", key)
            said.append(line)
            continue
        zh = "、".join(_TASK_ZH.get(n, n) for n in sorted(names))
        on, gone, err = maaend_enable(cfg, names)
        if err:
            line = f"开机：中继以前关掉的终末地任务 {zh} 没能开回（{err}），记录留着，下次开机再试"
            log.warning(line)
            said.append(line)
            continue
        store.pop("updates", key)
        if gone:
            line = (f"开机：中继以前关掉的终末地任务里，{'、'.join(_TASK_ZH.get(n, n) for n in gone)}"
                    f" 母本里已经没有了，没法开回（记录 {key} 已删）")
            log.warning(line)
            said.append(line)
        if on:
            line = (f"开机：中继以前关掉的终末地任务已开回：{'、'.join(_TASK_ZH.get(n, n) for n in on)}"
                    f"（记录 {key} 已删）")
        elif len(gone) < len(names):
            line = (f"开机：中继以前关掉的终末地任务 {'、'.join(_TASK_ZH.get(n, n) for n in sorted(names - set(gone)))}"
                    f" 已经开着（记录 {key} 已删）")
        else:
            continue
        log.info(line)
        said.append(line)
    return said


# ───────── the booster step: watched, never a reason to switch anything off ─────────
# The confirm node this file knows (beta.5, read verbatim off the machine 2026-09-03):
#   "all_of": ["YellowConfirmButtonType2", {"param": {...}, "type": "OCR"}]
# The elements of all_of are nodes, and an inline recognition has to sit inside its own
# recognition block; type/param straight on the element is something the framework does
# not understand, which left the confirm button unclickable. Upstream PR #5453 wrapped it
# (the "fixed" shape). v2.28.0-beta.4 (read off the machine 2026-09-09) had the node with
# no recognition block at all; v2.30.0-beta.4 (tests/fixtures/maaend-v2.30.0-beta.4-spmed)
# no longer has the node - the quick-use step is __AutoUseSpMedicationInQuickUse there.
SPMED_NODE = "AutoUseSpMedicationQuickUse"
# Its name from v2.32 on (the machine's live nodes.json, read by the operator 2026-10-06,
# tests/fixtures/maaend-v2.32-spmed): the click on the detail page's use button, whose
# all_of holds only node names - the 09-03 inline-OCR bug cannot occur in that shape.
SPMED_NODE_V232 = "__AutoUseSpMedicationUseEmergencySpBooster"
SPMED_NODES = (SPMED_NODE, SPMED_NODE_V232)


def spmed_shape(maaend_dir) -> str:
    """How the booster's confirm node reads in this MaaEnd install:
    "fixed" (the shape upstream PR #5453 produced), "broken" (the 09-03 shape),
    "unknown" (the node is there in a shape this file does not know), "missing"
    (no node of that name: renamed or removed upstream), "unreadable" (nodes.json
    cannot be read), "" (no MaaEnd directory configured)."""
    if not maaend_dir:
        return ""
    f = Path(maaend_dir) / "resource" / "pipeline" / "nodes.json"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(doc, dict):
        return "unreadable"
    name = next((n for n in SPMED_NODES if n in doc), None)
    if name is None:
        return "missing"
    node = doc[name]
    if not isinstance(node, dict) or not isinstance(node.get("recognition"), dict):
        return "unknown"
    all_of = (node["recognition"].get("param") or {}).get("all_of")
    if not isinstance(all_of, list) or not all_of:
        return "unknown"
    # Fixed: every element is a node name, or an inline recognition inside its own
    # recognition block. Broken (09-03): an inline element without that block.
    if any(not isinstance(x, (str, dict)) for x in all_of):
        return "unknown"
    return "fixed" if all(isinstance(x, str) or "recognition" in x for x in all_of) else "broken"


def spmed_check(cfg) -> str:
    """The booster step's shape when it calls for the boot alarm (texts.SPMED_UNRECOGNISED,
    body texts.spmed_unrecognised_body), '' when it is the fixed shape or there is no
    MaaEnd directory.

    Every boot that sees it says it again (the user, 2026-10-06: 「如果上游maaend改了导致
    没生效就要报警」). The task itself is never touched here."""
    shape = spmed_shape(getattr(cfg, "maaend_dir", None))
    if not shape:
        return ""
    if shape == "fixed":
        log.info("开机：应急理智加强剂那段是认得的修好写法")
        return ""
    # INFO, not WARNING: the caller pushes the alarm itself, and a relay WARNING
    # would reach the group a second time (errwatch).
    log.info("开机：应急理智加强剂那段认不出（%s），报群", shape)
    return shape
