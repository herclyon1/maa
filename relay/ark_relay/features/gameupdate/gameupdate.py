"""Game client updates on a version-update or maintenance day.

At boot (boot_check): cheap checks only - the Endfield notice and the three
official maintenance bulletins. A game that needs an
update is registered (mark_pending), and during a maintenance window its script
is skipped in today's queues (its queue items lose today's weekday).
After the queue (run_deferred): each registered game's client is updated through
its launcher up to the login screen, the relay waits for the servers to return,
re-runs the script when today's last round failed for that reason, and gives the
skipped queue items their weekday back.

The Arknights client is not updated here: since the 2026-10-11 switch-over
AUTO-MAS checks the version and installs the APK before an MAA run
(Run.IfCheckGameUpdate / IfAutoInstallGameApk, item 10a of the hand-over list).
The Wuthering Waves client is not updated here either: since 2026-10-12 AUTO-MAS
checks the official version and patches the client before an OK-WW run
(OK-WW script Game.Enabled / Game.Path / Game.IfAutoUpdate, item 10b).
A maintenance day still registers 明日方舟 and 鸣潮, so MAA / OK-WW is skipped in
the queues in the window and re-run once the servers are back; that re-run is
when AUTO-MAS updates the client.

Anything that could not be confirmed goes into `problems` for the caller to send.
The per-game update flows are in gameupdate_games.py and the MaaEnd task records
in gameupdate_maaend.py; their public names are re-exported here, so callers write
gameupdate.xxx.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.core.ledger import manual_stop
from ark_relay.core.desktop import Desktop, kill

# Public names of gameupdate_games and gameupdate_maaend are re-exported; the
# private names imported here are used by this module (_store) or by callers
# (_OFF_RECORDS: machinechecks/system.py).
from ark_relay.features.gameupdate.gameupdate_games import READY_WORDS, _store, endfield_paths, update_endfield
from ark_relay.features.gameupdate.gameupdate_maaend import SPMED_NODE, SPMED_NODE_V232, SPMED_NODES, _OFF_RECORDS, spmed_check, spmed_shape

log = logging.getLogger("ark.gameupdate")

__all__ = [
    "READY_WORDS",
    "_OFF_RECORDS",
    "SPMED_NODE",
    "SPMED_NODES",
    "SPMED_NODE_V232",
    "boot_check",
    "clear_pending",
    "endfield_paths",
    "in_maintenance",
    "last_run_ok",
    "last_trace",
    "log",
    "mark_pending",
    "mark_run",
    "needs_rerun",
    "off",
    "pending",
    "rerun_verdict",
    "restore_queue_skips_new_day",
    "restore_skips",
    "run_deferred",
    "save_windows",
    "should_run",
    "skips",
    "spmed_check",
    "spmed_shape",
    "stopped_today",
    "update_endfield",
    "windows",
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


# The ledger flag per script that says "could not get into the game". The
# collector writes maa_unreachable when every failure of an MAA record reads as
# not started and nothing shows work (collector_maa.never_started).
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

    True when the update skipped it in today's queue, or today's last round failed
    with the "could not get into the game" flag (_UNREACHABLE_FLAG) or during
    maintenance. An ordinary task failure is not re-run: a re-run would fail
    again and take the account from the user for nothing. False when the
    operator stopped it today (stopped_today).

    MAA is re-run only when the whole round never got going, by the make-up's
    rule (makeup.maa_round_work_done): an earlier attempt of the same round may
    have fought and used sanity potions before the last one failed to log in or
    ran into the maintenance, and a second whole run would use them again.
    """
    return rerun_verdict(state_dir, now, script)[0]


def rerun_verdict(state_dir: Path, now: datetime, script: str) -> tuple[bool, str]:
    """(needs_rerun, why not): the second part is the round rule's reason when it
    alone refused an MAA re-run that the last record asked for, '' otherwise.
    _rerun_script sends that reason as a plain GAME_UPDATE note, which routes to
    the info channels (notify.route_of 'info'), not the group: it is not an alarm, and no
    group message promised MAA a re-run."""
    if stopped_today(state_dir, now, script):
        return False, ""
    # A skip the user ordered through a queue command (source "queue") is his
    # choice for the day, not the update's, so it does not ask for a re-run - also
    # when the update holds the same item (both sources on one record).
    if any(r.get("script") == script and _sources(r) == {"update"} for r in skips(state_dir)):
        return True, ""                 # skipped in today's queue for the update
    last = _last_today(state_dir, now, script)   # manual stops are skipped
    if last is None or last.get("ok"):
        return False, ""
    raw = last.get("raw") or {}
    if not (raw.get(_UNREACHABLE_FLAG.get(script, "")) or raw.get("maintenance")):
        return False, ""
    if script == "MAA":
        from ark_relay.core.ledger import State  # noqa: PLC0415
        from ark_relay.features.makeup import makeup  # noqa: PLC0415
        try:
            why = makeup.maa_round_work_done(State(Path(state_dir)).read_ledger, last,
                                             downtime=bool(raw.get("maintenance")))
        except Exception:
            # Unsure: a second run may use sanity potions again.
            log.warning("游戏更新：没查成明日方舟这一轮有没有打过仗，不补跑", exc_info=True)
            why = "没查成这一轮前面有没有打过仗"
        if why:
            log.info("游戏更新：明日方舟不补跑：%s", why)
            return False, why
    return True, ""


def off(state_dir: Path) -> bool:
    """Master switch: when state.json's updates.gameupdate_off is true, none of this runs."""
    return bool(_store(state_dir).get("updates", "gameupdate_off"))


# ─────────────────────── boot: only the cheap checks ───────────────────────

def boot_check(cfg, *, budget_s: float, now: datetime | None = None,
               hint=None, maint_sources=None,
               skipper=None) -> tuple[list[str], list[str]]:
    """The boot window's checks. Returns (notes, problems).

    Endfield: the notice says there is a version update today -> register; the
    launcher is not opened.
    Maintenance bulletins: save today's windows, register the game, and take its
    script out of queues that fall inside the window.
    Arknights and Wuthering Waves have no version check here: AUTO-MAS does it
    before an MAA / OK-WW run.
    `budget_s` (the boot window left) is accepted for the caller; no check here
    needs it since the Arknights emulator start went.
    """
    now = now or datetime.now(tz=SERVER_TZ)
    notes: list[str] = []
    problems: list[str] = []
    # Skips made on an earlier day (or with no day recorded) are undone first; the
    # maintenance step below skips again if today needs it. An update's skip still
    # open is a missed put-back (WARNING); a queue command's is meant to end today.
    day = now.strftime("%Y-%m-%d")
    if done := restore_skips(cfg.state_dir, before_day=day, manual_too=False):
        log.warning("游戏更新：之前为更新在队列里跳过、一直没改回的，开机改回了：%s", "、".join(done))
    if done := restore_skips(cfg.state_dir, before_day=day):
        log.info("游戏更新：前一天按指令在队列里跳过的，开机改回了：%s", "、".join(done))
    if off(cfg.state_dir):
        log.info("游戏更新：总开关关着（state.json 的 updates.gameupdate_off），不检查")
        return notes, problems
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
        # (time for the client update): skip the script in that queue for today
        # through the AUTO-MAS API; restore_skips undoes it after the re-run.
        for q in _queues_today(cfg.automas_dir, now):
            for due in q["dues"]:
                if start - timedelta(minutes=30) <= due <= end + timedelta(minutes=45):
                    try:
                        got = skipper(q["name"], script) if skipper else _skip_default(q["name"], script)
                    except Exception as exc:  # noqa: BLE001
                        # Items whose run days may already be trimmed: keep their
                        # undo records, or the weekday stays removed for good.
                        for rec in getattr(exc, "recs", []):
                            rec["why"] = why
                            _add_skip(cfg.state_dir, rec)
                        problems.append(f"{game}：在队列「{q['name']}」里今天跳过 {script} 失败（{exc}）")
                        continue
                    # One record per queue item: a script may sit in the queue twice.
                    for rec in (got if isinstance(got, list) else [got] if got else []):
                        rec["why"] = why
                        _add_skip(cfg.state_dir, rec)
                    if got:
                        log.info("游戏更新：%s 维护（%s），队列「%s」今天跳过 %s", game, why, q["name"], script)
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


def _skip_default(queue: str, script: str) -> list[dict]:
    from ark_relay.features.phone import commands  # noqa: PLC0415
    return commands.skip_script_all_items(queue, script)


def _queues_today(automas_dir, now: datetime) -> list[dict]:
    """Today's queue times that have not come yet and run something today
    (plan.runs_at): [{name, dues:[datetime]}]."""
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
            if due >= now and plan.runs_at(q, hhmm, due):
                dues.append(due)
        out.append({"name": q["name"], "dues": dues})
    return out


def skips(state_dir: Path) -> list[dict]:
    d = _store(state_dir).get("updates", "queue_skips")
    return list(d) if isinstance(d, list) else []


# Who holds a skip record: "queue" (a queue command, queues.apply(scripts=...))
# and/or "update" (a game update or maintenance, boot_check). One record per queue
# item holds both when both want the item out today, so neither undoes the
# other's skip: the item gets its days back only when no holder is left.
# Records written before 2026-10-11 carry only "source" ("queue" or none).
def _sources(rec: dict) -> set[str]:
    got = rec.get("sources")
    if isinstance(got, list) and got:
        return {str(x) for x in got}
    return {"queue"} if rec.get("source") == "queue" else {"update"}


def _with_sources(rec: dict, srcs: set[str]) -> dict:
    out = dict(rec, sources=sorted(srcs))
    if "queue" in srcs:
        out["source"] = "queue"
    else:
        out.pop("source", None)
    return out


def _key(rec: dict) -> tuple:
    """A record's queue item: by item id; a record without one, by script id."""
    item = rec.get("queueItemId")
    return (rec.get("queueId"), "item", item) if item else (rec.get("queueId"), "script", rec.get("scriptId"))


def _add_skip(state_dir: Path, rec: dict) -> None:
    """Record a skip. A record of the same queue item already kept is merged into:

    * its `days` stay - they were read before any skip trimmed the item, so they
      are the true original. A skip made on a later day while an earlier day's
      record is still open (a queue command replayed at the next boot) reads
      days that still lack the earlier weekday; saving those would lose it.
    * the same day: the holders add up ("queue" and "update").
    * an earlier day: that record is stale (its put-back was missed); the new
      skip's day and holder replace it, so the boot restore of earlier-day
      records (before_day) does not undo today's skip.
    """
    lst, new = skips(state_dir), _with_sources(rec, _sources(rec))
    for i, old in enumerate(lst):
        if _key(old) != _key(rec):
            continue
        if str(old.get("day") or "") == str(rec.get("day") or ""):
            merged = _with_sources({**old, **rec}, _sources(old) | _sources(rec))
        else:
            merged = new
        if isinstance(old.get("days"), list):
            merged["days"] = list(old["days"])
        lst[i] = merged
        break
    else:
        lst.append(new)
    _store(state_dir).set("updates", "queue_skips", lst)


def _drop_skip(state_dir: Path, rec: dict) -> None:
    _store(state_dir).set("updates", "queue_skips",
                          [r for r in skips(state_dir) if _key(r) != _key(rec)])


def _release(state_dir: Path, rec: dict, source: str) -> None:
    """Take `source` off the record of rec's item, keeping the skip for the other holder."""
    _store(state_dir).set("updates", "queue_skips",
                          [_with_sources(r, _sources(r) - {source}) if _key(r) == _key(rec) else r
                           for r in skips(state_dir)])


def restore_skips(state_dir: Path, restorer=None, before_day: str = "", manual_too: bool = True,
                  updates_too: bool = True) -> list[str]:
    """Undo today-only queue skips; returns which items got their days back.

    With `before_day`, only records made on an earlier day or with no day. With
    manual_too False the queue-command holder ("queue", which lasts the whole
    day) is left alone; with updates_too False the update holder is. A record
    whose other holder is left keeps the skip and only loses the released
    holder. Only the records undone are dropped, so a failure is retried next call.
    """
    from ark_relay.features.phone import commands  # noqa: PLC0415
    restorer = restorer or commands.restore_script_in_queue
    release = ({"queue"} if manual_too else set()) | ({"update"} if updates_too else set())
    left, done = [], []
    for rec in skips(state_dir):
        srcs = _sources(rec)
        if (before_day and str(rec.get("day") or "") >= before_day) or not srcs & release:
            left.append(rec)
            continue
        if srcs - release:
            left.append(_with_sources(rec, srcs - release))
            continue
        try:
            if restorer(rec):
                done.append(f"{rec['script']}→「{rec['queue']}」")
                continue
        except Exception:
            log.exception("队列运行日改回失败：%s", rec)
        left.append(rec)
    _store(state_dir).set("updates", "queue_skips", left)
    return done


def restore_queue_skips_new_day(state_dir: Path, now: datetime, restorer=None) -> tuple[list[str], bool]:
    """Put back the queue-command skips of earlier days once the day has turned.

    A queue command's skip lasts the day it was made on. The boot restore ends it
    on a machine that is switched off overnight; on one left running this is
    called when the main loop passes local midnight (machine time is server
    time), so the item does not keep the weekday off. The update's holder is left
    to run_deferred. Returns (items put back, whether an earlier day's
    queue-command hold is still open - a failed put-back, to try again).
    """
    today = now.strftime("%Y-%m-%d")
    done = restore_skips(state_dir, restorer=restorer, before_day=today, updates_too=False)
    open_ = any(str(r.get("day") or "") < today and "queue" in _sources(r) for r in skips(state_dir))
    return done, open_


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
                    budget_s: float = 2400) -> tuple[bool, str]:
    """Update one game's client through to the login screen. Returns (ready,
    notification sentence); when not ready, the reason is in problems. `budget_s`
    caps the wait for the launcher's download."""
    before = len(problems)
    if game == "终末地":
        g, launcher = endfield_paths(cfg.maaend_dir)
        if not (g and launcher):
            problems.append("终末地：找不到启动器"); return False, ""
        n = update_endfield(desk, g, launcher, budget_s=budget_s, problems=problems, sleep=sleep)
    else:
        # 明日方舟 and 鸣潮: nothing to prepare. AUTO-MAS checks and installs the
        # client before the MAA / OK-WW re-run (MAA Run.IfCheckGameUpdate /
        # IfAutoInstallGameApk, item 10a; OK-WW Game.Enabled / Game.Path /
        # Game.IfAutoUpdate, item 10b).
        return True, ""
    return len(problems) == before, n


# What the game says when the update package it needs is not out yet: the wait
# _prepare_until_ready retries for, not a fault (gameupdate_games.update_endfield).
NOT_OUT_YET = "客户端已过时"


def _prepare_until_ready(cfg, desk: Desktop, game: str, *, deadline: datetime, clock, sleep,
                         problems: list[str]) -> tuple[bool, str]:
    """Update every 10 minutes until the client is ready or the deadline passes.
    Returns (ready, every round's notification sentence joined).

    A round that is not ready has the problems it wrote taken out before the next
    round. 「The update package is not out yet」 (NOT_OUT_YET: the game says its
    client is outdated) is the wait this loop is for and is dropped. Any other
    problem is kept aside: a later ready round makes it a fault that fixed itself,
    one WARNING marked errwatch.recovered() naming each (until 2026-10-12 it was
    dropped with no trace); not ready by the deadline, it is reported with the last
    round's problems.
    """
    ready, note = False, ""
    outdated = False
    said: list[str] = []     # every round's sentence, so an earlier round's 「已更新」 is kept
    earlier: list[str] = []  # problems of rounds that were not ready, other than NOT_OUT_YET
    start = clock()          # when the next round starts
    while True:
        mark = len(problems)
        # One round's download wait ends by the deadline, not 40 minutes past it
        # (s18 F6): the deadline is otherwise checked only between rounds.
        left = max(0.0, (deadline - start).total_seconds())
        ready, note = _prepare_client(cfg, desk, game, problems, sleep, budget_s=min(2400.0, left))
        if note and note not in said:
            said.append(note)
        if outdated and ready and not note:
            # An earlier round's game said its client was outdated; a later "no update
            # needed" from the launcher is the same client, not a ready one.
            ready = False
            problems.append(f"{game}：更新后游戏说客户端已过时，启动器却显示无需更新，客户端没准备好")
        at = clock()
        # No round after the 10-minute wait when it would start at or past the
        # deadline: it would run with no budget and report a bogus 「0 分钟内没等到」.
        if ready or at + timedelta(seconds=600) >= deadline:
            break
        # Not ready (often the update package is not out yet): take out every problem
        # this round wrote - one round can write several - and retry in 10 minutes.
        log.info("游戏更新：%s 还没准备好（%s），10 分钟后再试", game, problems[-1] if problems else "")
        outdated = outdated or any(NOT_OUT_YET in p for p in problems[mark:])
        earlier += [p for p in problems[mark:] if NOT_OUT_YET not in p and p not in earlier]
        del problems[mark:]
        sleep(600)
        start = at + timedelta(seconds=600)
    if ready and earlier:
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        log.warning("游戏更新：%s 前面几轮没准备好，后来一轮准备好了\n%s", game, "；".join(earlier),
                    extra=errwatch.recovered())
    elif not ready:
        problems.extend(f"{p}（之前一轮）" for p in earlier if p not in problems[mark:])
    return ready, "；".join(said)


def _rerun_script(cfg, now: datetime, dispatch, script: str,
                  reran: list[str], problems: list[str], notes: list[str] | None = None) -> None:
    """Once the client is updated, re-run the script when needs_rerun says so.

    A script the red button stopped today is not re-run (stopped_today); that is
    said in `notes`, not `problems`. So is an MAA round that already fought
    (rerun_verdict's reason): not an alarm, so it goes to the info channels only, telling
    the user why the round he may expect to run again after the update did not.
    """
    if stop := stopped_today(cfg.state_dir, now, script):
        log.info("游戏更新：%s 今天被停一切停过（%s），不自动补跑", script, stop)
        if notes is not None:
            notes.append(f"{script}：今天 {stop}停过，已停，未补")
        return
    rerun, why = rerun_verdict(cfg.state_dir, now, script)
    if why and notes is not None:
        notes.append(texts.update_rerun_refused(script, why))
    if rerun and dispatch is not None:
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
    window). The update's queue skips are undone on every way out.
    """
    now = now or datetime.now(tz=SERVER_TZ)
    clock = clock or (lambda: datetime.now(tz=SERVER_TZ))
    notes: list[str] = []
    problems: list[str] = []
    reran: list[str] = []
    _LAST_DESK[0] = desk
    todo = pending(cfg.state_dir)
    if not todo or off(cfg.state_dir):
        if done := restore_skips(cfg.state_dir, manual_too=False):
            log.info("游戏更新：已把跳过的改回队列：%s", "、".join(done))
        return notes, problems, reran
    try:
        _work_deferred(cfg, now, todo, desk, dispatch, sleep, clock, notes, problems, reran)
    finally:
        if done := restore_skips(cfg.state_dir, manual_too=False):
            log.info("游戏更新：已把跳过的改回队列：%s", "、".join(done))
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
        ready, note = _prepare_until_ready(cfg, desk, game, deadline=deadline, clock=clock,
                                           sleep=sleep, problems=problems)
        if note:
            notes.append(note + f"（依据：{why}）")
        if not ready:
            problems.append(f"{game}：到 {deadline:%m-%d %H:%M} 仍没准备好客户端，今天不补跑")
            continue
        # Ready. Servers still down: close the game when they are more than 10
        # minutes away, wait for them, then re-run.
        if end and clock() < end:
            # Only Endfield is opened here (_prepare_client): 明日方舟 and 鸣潮 open
            # nothing, so any client of theirs is one the owner opened (s18 F2).
            if game == "终末地" and end - clock() > timedelta(minutes=10):
                kill("Endfield.exe")
            log.info("游戏更新：%s 客户端已就绪，等 %s 开服再补跑", game, end.strftime("%H:%M"))
            while clock() < end:
                sleep(60)
            sleep(120)
        _rerun_script(cfg, now, dispatch, script, reran, problems, notes)
        clear_pending(cfg.state_dir, game)
