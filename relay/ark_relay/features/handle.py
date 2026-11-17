"""Per-day facts the engine asks handle.py for: whether a game has an update
window registered today, and which alarm keys were already marked sent today
(state.json marks.alerted:<day>).
"""
from __future__ import annotations

import sys as _sys
import json
import logging
import re
import dataclasses
import functools
import threading
import os
import shutil
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta
from ark_relay.core.config import SERVER_TZ, RunRecord, atomic_write_text, EVENING, MORNING
from ark_relay.core import texts, ledger as core, collector, summary, plan
from ark_relay.core.ledger import maaend_unbacked_why, maaend_unverified
from ark_relay.features import maintenance as efstatus, outcome, collector_maaend, stagegate
from types import SimpleNamespace

def _maintenance_today(eng, game: str) -> bool:
    try:
        from ark_relay.features import gameupdate  # noqa: PLC0415
        return game in gameupdate.windows(eng.state.dir)
    except Exception:  # noqa: BLE001
        return False


# Script + user + which steps failed. No push is held back on this key; only
# tests/test_alarm.py reads it (through Engine._alert_key).
# 来龙去脉见 docs/CODE-HISTORY.md「handle.py:(模块级)」
def _alert_key(eng, rec) -> str:
    return f"{rec.script}|{rec.user}|{','.join(sorted(rec.failed_tasks or ['?']))}"


def _alerted_file(eng, day: str) -> Path:
    """The path of the old per-day alerted file. Nothing calls it (Engine._alerted_file
    wraps it and is itself never called); the marks live in state.json under
    marks.alerted:<day>."""
    return Path(eng.state.dir) / f"alerted-{day}.json"


def _already_alerted(eng, day: str, key: str) -> bool:
    got = eng.state.store.get("marks", f"alerted:{day}")
    return key in got if isinstance(got, list) else False


def _mark_alerted(eng, day: str, key: str) -> None:
    """Add `key` to the day's marks in one read-modify-write of state.json (update):
    built from a get() outside the write lock, two marks racing wrote back the list
    each had read and one of them was lost."""
    def _add(got):
        cur = list(got) if isinstance(got, list) else []
        if key not in cur:
            cur.append(key)
        return cur
    eng.state.store.update("marks", f"alerted:{day}", _add)


# Same logger as handle.py: relay.log names these lines "ark.handle".
log = logging.getLogger("ark.handle")


def _okww_master_config(automas_dir: str | Path | None, name: str) -> dict:
    """Read the OK-WW config that is **actually in effect**.

    The copy in OK-WW's own directory is replaced wholesale by AUTO-MAS before a
    run and restored afterwards, so reading it after the fact reads a fake. The
    one actually in effect is under
    `<automas>/data/<script id>/Default/ConfigFile/`.
    The script id is not fixed, so just scan - on this machine only OK-WW has
    this directory structure.
    """
    if not automas_dir:
        return {}
    root = Path(automas_dir) / "data"
    if not root.is_dir():
        return {}
    for sid in root.iterdir():
        f = sid / "Default" / "ConfigFile" / f"{name}.json"
        if f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d:
                return d
    return {}


def _okww_nest_expected(automas_dir: str | Path | None) -> bool | None:
    """Whether this round was supposed to farm tacet nests. **Returns None, not False, when the config cannot be read.**

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_okww_nest_expected」。
    """
    daily = _okww_master_config(automas_dir, "DailyTask")
    if not daily:
        return None
    adds = daily.get("Additional Tasks to Run After Daily Task") or []
    if "Auto Farm all Nightmare Nest" in adds:
        return True
    return bool(daily.get("Farm Nightmare Nest for Daily Echo", True)
                and daily.get("Which to Farm", "Tacet Suppression") != "Tacet Suppression")


_MAA_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


# How much of the tail to take. One round is roughly 30,000 lines / 6-7 MB, so
# 16 MB is plenty to cover a whole round.
_MAA_LOG_TAIL = 16 * 1024 * 1024


MAAEND_NOTHING_TO_RUN_LOG = "MaaEnd 没有可执行任务，请检查任务配置, 无日志记录"


MAAEND_NOTHING_TO_RUN = "没有可执行任务"


_MAAEND_TS = re.compile(r"^\[?(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def _in_window(text: str, started: datetime, until: datetime) -> str:
    """The lines of `text` stamped inside [started - WINDOW_SLACK, until] (Beijing,
    the machine's clock), unstamped lines following the line before them; `text` as
    it is when no line carries a stamp (a format this does not know is not cut away).
    """
    from ark_relay.features.evidence import WINDOW_SLACK  # noqa: PLC0415
    cut = (started - timedelta(seconds=WINDOW_SLACK)).astimezone(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
    top = until.astimezone(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
    out: list[str] = []
    keep, stamped = False, False
    for line in text.splitlines():
        if m := _MAAEND_TS.match(line):
            stamped = True
            keep = cut <= m.group(1) <= top     # fixed width: lexical order is time order
        if keep:
            out.append(line)
    return "\n".join(out) if stamped else text


def _maaend_app_log(maaend_dir: "str | Path | None",
                    started: datetime, until: "datetime | None" = None) -> str:
    """The app log MaaEnd wrote **itself** for this round.

来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maaend_app_log」。
    """
    if not maaend_dir:
        return ""
    d = Path(maaend_dir) / "debug"
    if not d.is_dir():
        return ""
    cut = started.timestamp()
    out: list[str] = []
    for f in sorted(d.glob("20??-??-??-*.log")):
        try:
            if f.stat().st_mtime < cut:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")[-200_000:]
        except OSError:
            continue
        if until is not None:
            text = _in_window(text, started, until)
        if text:
            out.append(text)
    return "\n".join(out)


def _maa_app_log(maa_dir: "str | Path | None", started: datetime,
                 until: "datetime | None" = None) -> "str | None":
    """The asst.log MAA wrote **itself** for this round, keeping only the lines inside this round's time window.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maa_app_log」。
    """
    if not maa_dir:
        return None
    f = Path(maa_dir) / "debug" / "asst.log"
    if not f.is_file():
        return None
    try:
        # One round alone is over 30,000 lines, so reading the whole file is
        # unnecessary; take the tail and then cut by time.
        size = f.stat().st_size
        with f.open("rb") as fh:
            if size > _MAA_LOG_TAIL:
                fh.seek(size - _MAA_LOG_TAIL)
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    # An upper bound is mandatory: a start with no end sweeps in lines from the
    # **later rounds** as well, which is charging this morning's error to last
    # night. The exception is `until` being None, where no upper bound is set -
    # the times on such a record are untrustworthy to begin with, and taking too
    # much beats cutting the whole round away.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maa_app_log」
    cut = started.strftime("%Y-%m-%d %H:%M:%S")
    top = until.strftime("%Y-%m-%d %H:%M:%S") if until else None
    out: list[str] = []
    keep = False
    for line in raw.splitlines():
        m = _MAA_TS.match(line)
        if m:
            # The timestamp is fixed-width, so lexical order is chronological
            # order and it can be compared directly here.
            ts = m.group(1)
            keep = ts >= cut and (top is None or ts <= top)
        # A line with no timestamp is a continuation of the previous one and
        # follows it - do not judge it on its own, or traceback lines get pulled
        # in unconditionally (this trap is recorded in arklog.py).
        if keep:
            out.append(line)
    # Not a single line inside the window = this round's log was not found,
    # which is just as uncheckable as "cannot read the file". Returning "" would
    # be read by the checks as "no errors at all", which is another false green.
    return "\n".join(out) if out else None


def _maaend_new_shots(maaend_dir: str | Path | None,
                      started: datetime, until: "datetime | None" = None) -> list[str]:
    """The on_error screenshot filenames that appeared during this round."""
    from ark_relay.features import collector_maaend  # noqa: PLC0415
    return collector_maaend.round_shots(maaend_dir, started, until)


def _okww_log_file(okww_dir: "str | Path | None") -> "Path | None":
    """OK-WW's newest log. Say something when it is not found; never return None silently."""
    if not okww_dir:
        log.warning("okww_dir 没解析出来，OK-WW 的日志切片存不了")
        return None
    logs = Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "logs"
    try:
        return max(logs.glob("*.log*"), key=lambda q: q.stat().st_mtime)
    except (OSError, ValueError):
        log.warning("OK-WW 的日志目录 %s 里没有日志", logs)
        return None


# Same logger as handle.py: relay.log names these lines "ark.handle".


def backfill_manual_stops(eng, now: datetime | None = None) -> int:
    """Book as manual stops the runs of today and yesterday that a recorded press
    overlaps but whose ledger line lacks raw.manual_stop. Returns how many.

    Run once per boot, after the self-update, so the new code does it. Covers a
    press recorded after its run was booked. Each ledger file is rewritten once,
    atomically, with every other line - torn ones included - kept byte for byte.
    Idempotent: a patched line is skipped the next time.

    Also drops the alarms _handle would have dropped at record time: a held
    failure of the same script and user that started no later than the stopped
    run (its final alarm), and a self-heal notice the stopped run produced by
    reading as a success. The engine has already loaded both from disk in its
    constructor, so they are removed in memory and persisted.
    """
    from ark_relay.features import commands  # noqa: PLC0415
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    state_dir = eng.cfg.state_dir
    windows = commands.estop_windows(state_dir)
    if not windows:
        return 0
    patched: list[dict] = []
    entries: list[dict] = []
    for day in sorted({(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in (1, 0)}):
        path = eng.state.ledger_path(day)
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        hit = False
        for i, ln in enumerate(lines):
            try:
                e = json.loads(ln)
                started = datetime.fromisoformat(str(e["started"]))
                finished = datetime.fromisoformat(str(e["finished"]))
            except (ValueError, TypeError, KeyError):
                continue          # a torn or foreign line stays exactly as it is
            entries.append(e)
            raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
            if raw.get("manual_stop"):
                continue
            if not (label := commands.estop_label(windows, started, finished)):
                continue
            raw["manual_stop"] = label
            e["raw"] = raw
            lines[i] = json.dumps(e, ensure_ascii=False)
            patched.append(e)
            hit = True
            log.info("⏹ 补记：%s %s（%s）这趟是停一切停掉的，记手动停止",
                     e.get("script"), e.get("run_id"), label)
        if hit:
            atomic_write_text(path, "\n".join(lines) + "\n")
    if patched:
        _drop_alarms_for_manual(eng, patched, entries)
    return len(patched)


def _push_before_stop(eng, failed: RunRecord, stop: str) -> list:
    """A failure that a 停一切 cut off from its retries / make-up: pushed now, saying so."""
    # Imported at call time: handle imports this module, and _failure_alarm stays in
    # handle with the evidence helpers tests rebind there.
    pass
    day = run_day(failed)
    # held=True: its evidence was captured when it was held; what is on the screen
    # and in the logs now is the stopped run's.
    title, body = _failure_alarm(eng, failed, f"后面那趟是停一切停掉的（{stop}），这次失败没再重试、也没补跑，照报。",
                                 held=True)
    return _push_now(eng, day, "停一切前", failed.run_id, title, body)


def _drop_alarms_for_manual(eng, patched: list[dict], entries: list[dict]) -> None:
    """Settle held alarms tied to runs just booked as manual stops (see backfill_manual_stops):
    the failure is pushed now instead of waiting for retries a 停一切 ended."""
    def _at(v) -> datetime:
        t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
        return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)

    changed = False
    for e in patched:
        key = (e.get("script"), e.get("user"))
        stop_at = _at(e["started"])
        held = eng._pending.get(key)
        stop = (e.get("raw") or {}).get("manual_stop") or "停一切"
        if held is not None and _at(held.started) <= stop_at:
            eng._pending.pop(key, None)
            changed = True
            _push_before_stop(eng, held, stop)
            log.info("⏹ 补记：%s %s 的失败已报群（后面那趟是停一切停掉的）", key[0], held.run_id)
        healed = eng._recovered.get(key)
        if healed is None or _at(healed.started) > stop_at:
            continue
        # A genuine success between the held failure and the stopped run is what
        # healed it; that notice stands.
        cured = any(x is not e and x.get("ok") and not (x.get("raw") or {}).get("manual_stop")
                    and (x.get("script"), x.get("user")) == key
                    and _at(healed.started) < _at(x["started"]) < stop_at
                    for x in entries)
        if not cured:
            # The 「success」 that healed it was the stopped run: it was not healed.
            eng._recovered.pop(key, None)
            changed = True
            _push_before_stop(eng, healed, stop)
            log.info("⏹ 补记：%s %s 不算重试后成功（那次成功是停一切停掉的），失败已报群",
                     key[0], healed.run_id)
    if changed:
        eng._persist_pending()


# Same logger as handle.py: relay.log names these lines "ark.handle".


def _errwatch():
    from ark_relay.features import errwatch  # noqa: PLC0415
    return errwatch


def _push_undone(eng, rec: RunRecord, msg: str, page: str) -> tuple[str, list]:
    """A MAA / MaaEnd round that exited normally with work left undone: no make-up
    is run for it, so the group hears of it now (unresolved.py), whichever items
    they are - 自动采集 and 应急理智加强剂 included. Returns (title, errors) of the
    push."""
    unresolved = _sys.modules[__name__]
    day, shift = unresolved.where(eng, rec)
    game = unresolved.GAME[rec.script]
    # The caller has just tried the bundle (_ship_evidence); no second upload here.
    note = "" if page else texts.EVIDENCE_NOT_SHIPPED + "\n"
    # Settings reset to defaults is said as such, not as 「没干完」 (outcome.summarize).
    if texts.outcome_settings_only(msg):
        title = texts.unresolved_settings(game, shift)
        first = texts.unresolved_settings_head(game, shift, unresolved.undone_label(msg), page)
    else:
        title = texts.unresolved_undone(game, shift)
        first = texts.unresolved_undone_head(game, shift, unresolved.undone_label(msg), page,
                                             _gathering_retry_note(eng, rec, msg))
    body = first + note + "\n" + msg
    return title, _push_now(eng, day, unresolved.UNRESOLVED_KIND, rec.run_id, title, body)


def _gathering_retry_note(eng, rec: RunRecord, msg: str) -> str:
    """What the 「没干完」 head says in place of 「这一类不补跑」 for a MaaEnd round with
    gathering among what is undone: no whole make-up, and what becomes of the routes that
    did not walk (collect_retry.retry_ahead). '' - the usual words - for anything else, when
    the round's log names no such route, and when that cannot be read: the alarm goes out
    at once either way, this only keeps its first line true."""
    unresolved = _sys.modules[__name__]
    from ark_relay.features import collect_retry, makeup  # noqa: PLC0415
    if rec.script != "MaaEnd" or makeup.GATHERING not in unresolved._undone_items(msg):
        return ""
    try:
        names, state = collect_retry.retry_ahead(eng, rec)
    except Exception:  # the alarm must go out; the usual words then
        log.info("没读出 %s 哪几条采集路线会单独补，报警照旧用原来那句", rec.run_id, exc_info=True)
        return ""
    return texts.NO_WHOLE_MAKEUP + "，" + texts.collect_retry_ahead(names, state) if names else ""


# Why an item does not count, by game (core.day_unverified_items says how each is found).
# MaaEnd's depends on the items: those judged from its own record say so
# (_unverified_why, texts.maaend_unverified_why); this one is for the rest.
_UNVERIFIED_WHY = {
    "MaaEnd": "日志里没有游戏回显",
    "MAA": "日志里没有「剿灭模式 x/y」这行进度",
    "OK-WW": "日志里没读到做完",
}
UNVERIFIED_KIND = "没证据"
# The mark naming the record whose booking sent (or queued) a 「没证据」 alarm.
UNVERIFIED_BY = "没证据-发自"


def _unverified_why(script: str, items: list, entries: list) -> str:
    """_UNVERIFIED_WHY for `items`, one day's ledger `entries`. For MaaEnd, an item some
    run of the day judged from MaaEnd's own record (raw['tasks_trail'], the four of
    maaend_fwlog.TRAIL_TASKS) is said that way; the rest by their log line."""
    if script != "MaaEnd":
        return _UNVERIFIED_WHY.get(script, "没有游戏里的证据")
    judged = {t for e in entries if e.get("script") == "MaaEnd"
              for t, v in ((e.get("raw") or {}).get("tasks_trail") or {}).items() if isinstance(v, dict)}
    return texts.maaend_unverified_why([t for t in items if t in judged], [t for t in items if t not in judged])


def _trail_whys(rec: RunRecord, items: list, entries: list) -> list:
    """[(task, what MaaEnd's own record shows)] for the items of the 「没证据」 alarm judged
    from it (raw['tasks_trail']: MaaEnd stopped itself inside the task and why, no step
    that did the job, ...), from this run's record first, else the day's latest run that
    left it unbacked; the same verdict machine check #28 reads, so the alarm carries it."""
    out = []
    rows = [rec.raw or {}, *((e.get("raw") or {}) for e in reversed(entries) if e.get("script") == rec.script)]
    for t in items:
        for raw in rows:
            if t in maaend_unverified(raw) and (why := maaend_unbacked_why(raw, t)):
                out.append((t, why))
                break
    return out


def _push_unverified(eng, rec: RunRecord) -> None:
    """Once a round has exited normally, push the day's items of its game that the
    program called done with no game evidence (core.day_unverified_items: the very
    items the report title counts as 「N 项没证据」), each set once a day.

    Not a normal state: the program says the work is done and nothing from the game
    backs it, so whether the stamina went where it should is unknown - a person has
    to look (every error goes to the group: docs/NOTIFICATIONS.md). It runs at the
    round's end, after AUTO-MAS's own retries: an item another run of the day backs up is not on the list, so what is
    pushed is what nothing recovered. Never raises: bookkeeping goes on."""
    try:
        unresolved = _sys.modules[__name__]
        # Read from handle at call time: tests rebind handle._ship_evidence.
        pass
        day = run_day(rec)
        entries = eng.state.read_ledger(day)
        items = dict(core.day_unverified_items(entries)).get(rec.script)
        if not items:
            return
        _, shift = unresolved.where(eng, rec)
        game = core._game(rec.script)
        page = _ship_evidence(eng, rec)
        head = texts.unverified_alarm_head(game, shift, "、".join(items),
                                           _unverified_why(rec.script, items, entries), page)
        body = (head + texts.unverified_trail_lines(_trail_whys(rec, items, entries))
                + ("" if page else texts.EVIDENCE_NOT_SHIPPED + "\n"))
        key = f"{rec.script}:{rec.run_id}:{'、'.join(items)}"
        # Which record's booking sent it: a record replayed after its handling broke
        # off (_append_ledger_once) finds its own alarm, not an earlier run's.
        mine = unresolved._key(UNVERIFIED_BY, rec.run_id)
        sent_now = not eng._already_alerted(day, unresolved._key(UNVERIFIED_KIND, key))
        queued = False
        if sent_now:
            queued = bool(_push_now(eng, day, UNVERIFIED_KIND, key, texts.unverified_alarm(game, shift, len(items)), body))
        if sent_now or eng._already_alerted(day, mine):
            runchecks = _sys.modules[__name__]
            from ark_relay.features import machinechecks as runs  # noqa: PLC0415
            runchecks._UNVERIFIED[rec.run_id] = list(items)
            runs.covered_28(eng.cfg.state_dir, rec.script, day, list(items))
            if sent_now and not queued and not eng._already_alerted(day, unresolved._key(UNVERIFIED_KIND, key)):
                # Went out, but its own day mark did not land (unresolved.send said so in
                # one ERROR, replay included): the mark of this record would fail on the
                # same lock and say the same cause again.
                log.info("「没证据」已发出、当天记号没记上（已报），不再记「是 %s 这一趟发的」", rec.run_id)
            elif sent_now:
                try:
                    eng._mark_alerted(day, mine)
                except Exception:  # sent (or queued); only which record sent it is not on file
                    log.error("「没证据」已经发出（或排着下一轮发），但「是 %s 这一趟发的」没记下："
                              "这一趟的记账若重放，上机核对第 28 条会单独再报一次", rec.run_id, exc_info=True)
        else:
            # Only a replay of this record whose own mark did not land gets here: its alarm
            # went out under the same key the first time.
            log.info("「%s」这一趟已经发过（%s 重放），不再发", texts.unverified_alarm(game, shift, len(items)), rec.run_id)
    except Exception:
        log.exception("「没证据」这一项没能推到群里（%s）", rec.run_id)


def _push_now(eng, day: str, kind: str, run_id: str, title: str, body: str) -> list:
    """Push one alarm of `kind` about the record `run_id` to the group now; one that
    did not go out is kept and tried again on the next tick (unresolved.retry_unsent).
    -> errors."""
    unresolved = _sys.modules[__name__]
    if unresolved.send(eng, day, kind, run_id, title, body):
        return []
    eng._unsent_unresolved.append((day, kind, run_id, title, body))
    eng._persist_pending()
    return ["没推出去，下一轮再推"]


def _evidence_note(eng, rec: RunRecord) -> str:
    """Right before a group alarm about `rec`: make sure it carries a bundle.

    No link on the record yet -> ship one now, once per record (a push that fails
    is retried every tick; the upload is not). '' when the record has its link,
    else the one line for the alarm's body. Never raises: the alarm goes out
    either way. An alarm without its evidence cannot be checked.
    """
    try:
        # Read from handle at call time: tests rebind handle._ship_evidence.
        pass
        raw = rec.raw
        if raw.get("evidence_page"):
            return ""
        if not raw.get("evidence_retried"):
            raw["evidence_retried"] = True
            page = _ship_evidence(eng, rec)
            eng._persist_pending()
            if page:
                return ""
    except Exception:
        log.exception("报警前补传证据包出错（报警照发）")
    return texts.EVIDENCE_NOT_SHIPPED


def _push_unresolved(eng, rec: RunRecord, makeup_phrase: str, attempts: int) -> bool:
    """A MAA / MaaEnd failure its make-up did not fix (or that got none): an alarm
    for every such failure (unresolved.py).
    A make-up that went through is not pushed (_flush_pending; the daily report
    says it). False when the push failed (keep it held)."""
    unresolved = _sys.modules[__name__]
    day, shift = unresolved.where(eng, rec)
    game = unresolved.GAME[rec.script]
    note = _evidence_note(eng, rec)
    raw = rec.raw or {}
    names = core._with_causes(list(rec.failed_tasks or []), raw.get("maaend_fail_causes"))
    if makeup_phrase == texts.MAKEUP_STOPPED_PHRASE:
        names = [n for n in names if texts.AUTOMAS_MANUAL_STOP not in n]
    stuck = "、".join(names[:3]) + ("…" if len(names) > 3 else "")
    page = raw.get("evidence_page") or ""
    # The link goes in the head; the rest of the body is the usual failure text without it.
    _, rest = core.format_failure(dataclasses.replace(rec, raw={k: v for k, v in raw.items() if k != "evidence_page"}),
                                  _diagnosis(eng, rec))
    title, head = _unresolved_title_head(game, shift, makeup_phrase, stuck, page)
    body = head + (note + "\n" if note else "") + "\n" + texts.failed_body_head(attempts) + _restart_note(rec) + rest
    if raw.get("maaend_unreachable_shape") and not raw.get("maaend_unreachable"):
        # maaend_unreachable_unread: the official notices could not be read, so
        # "no notice today" would be a guess (records._confirm_unreachable).
        unread_note = getattr(texts, "UNREACHABLE_UNREAD_NOTE", None)
        body += "\n" + (unread_note if raw.get("maaend_unreachable_unread") and unread_note
                         else texts.UNREACHABLE_SHAPE_NOTE)
    return unresolved.send(eng, day, unresolved.UNRESOLVED_KIND, rec.run_id, title, body)


def _unresolved_title_head(game: str, shift: str, makeup_phrase: str, stuck: str, page: str) -> tuple[str, str]:
    """(title, first line) of a held failure's alarm. A MaaEnd round whose only unfinished task
    was gathering got no whole make-up (makeup.maaend_round_only_gathering): every other task was
    done, so it is said as 「没干完」 like any round left with gathering undone, with why there was
    no whole make-up under it - not as 「没跑成」."""
    if texts.MAKEUP_ONLY_GATHERING_MARK in makeup_phrase:
        from ark_relay.features import makeup  # noqa: PLC0415
        # Its second line already says the routes are walked again before the power-off
        # (texts.makeup_only_gathering); the first no longer says nothing is re-run.
        return (texts.unresolved_undone(game, shift),
                texts.unresolved_undone_head(game, shift, makeup.GATHERING, page, texts.NO_WHOLE_MAKEUP)
                + makeup_phrase + "\n")
    return texts.unresolved(game, shift), texts.unresolved_head(game, shift, makeup_phrase, stuck, page)


# Same logger as handle.py: relay.log names these lines "ark.handle".


def run_day(rec: RunRecord) -> str:
    """The server-time day (YYYY-MM-DD) the run started on: its ledger file."""
    return rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")


def _append_ledger_once(eng, rec: RunRecord) -> None:
    """Append this run to the day's ledger, without double-counting a replayed record.

    Its own step because bookkeeping has to be idempotent, while the judging and
    pushing below it can fail midway and send the whole record through from the
    start again - fenced off as one step, a replay simply skips it.
    """
    # mark_seen only happens after _handle returns, so a crash later in
    # handling replays the record on every retry tick; appending it again
    # would inflate the daily report and the "重试 N 次" counts.
    day = run_day(rec)
    if any(e.get("run_id") == rec.run_id for e in eng.state.read_ledger(day)):
        log.info("记录 %s 已在账上（上次处理中途出错的重试），跳过重记", rec.run_id)
    else:
        eng.state.append_ledger(rec)


def _same_shift(eng, a: RunRecord, b: RunRecord) -> bool:
    unresolved = _sys.modules[__name__]
    try:
        return unresolved.where(eng, a) == unresolved.where(eng, b)
    except Exception:  # not knowing keeps the held record on its usual path
        log.warning("分不清 %s 和 %s 是不是同一班，按原样处理", a.run_id, b.run_id, exc_info=True)
        return False


def _estop_overlap(eng, rec: RunRecord) -> str:
    """「HH:MM 停一切」 when this run overlaps a press of the red button, else ''.

    AUTO-MAS can record a run the button stopped as Success!; without this mark
    it would read as the retry that healed an earlier failure.
    """
    try:
        from ark_relay.features import commands  # noqa: PLC0415
        return commands.estop_label(commands.estop_windows(eng.cfg.state_dir),
                                    rec.started, rec.finished)
    except Exception:
        log.exception("红按钮时间对不上（按正常记录处理）")
    return ""


def _mark_update_restart(eng, rec: RunRecord) -> None:
    """A MaaEnd attempt spent on installing its own update is not a game failure.

    Marked before the ledger line is written, so the daily report reads it as an
    update episode. It is still held like a failure: if no later attempt gets
    through, the final alarm says the last retry went on the update.
    """
    # Only a run attempt: AUTO-MAS's own failed update step (collector,
    # raw['automas_update_step']) sits in the same MXU install window but is no run.
    if rec.script != "MaaEnd" or rec.ok or rec.transitional or (rec.raw or {}).get("automas_update_step"):
        return
    try:
        from ark_relay.features.collector_maaend import update_restart_version  # noqa: PLC0415
        version = update_restart_version(eng.cfg.maaend_dir, rec.started)
    except Exception:
        log.exception("核对 MaaEnd 是否在装更新时出错，按原样处理")
        return
    if not version:
        return
    rec.raw["maaend_update_restart"] = version
    rec.raw["automas_failed_tasks"] = list(rec.failed_tasks)
    rec.failed_tasks = [f"MaaEnd 装新版 {version} 后自己重启，这一次重试被用掉"]
    rec.transitional = True


# A task-end picture belongs to a task when it was taken this close after the
# task's 「任务完成」 (the picture lands a few seconds after the maafw event,
# task_shots.py); the launch's first-start picture of a longer task is earlier.
SHOT_BEFORE_S, SHOT_AFTER_S = 5, 120


def _mark_task_shots(eng, rec: RunRecord) -> None:
    """raw['tasks_shot']: the MaaEnd tasks of this run with a task-end picture
    (task_shots.py). Game evidence for core.maaend_unverified only on records booked
    before raw['tasks_trail'] (_mark_task_trails): the picture shows the next task. A
    key of its own, so collector.refresh_raw (which re-parses only the log) never drops it.
    raw['tasks_shot_files']: {task: that picture, relative to the state folder},
    the evidence a machine check names (machinechecks/runs.py)."""
    try:
        from ark_relay.features import collector_maaend  # noqa: PLC0415
        from ark_relay.features import task_shots  # noqa: PLC0415
        log_path = rec.log_path
        if not log_path or not Path(log_path).is_file():
            return
        times = collector_maaend.task_times(Path(log_path).read_text(encoding="utf-8", errors="replace"))
        shots: list[tuple[str, datetime, Path]] = []
        end = rec.finished if rec.finished else datetime.now().astimezone()
        for p in task_shots.in_window(eng.cfg.state_dir, (rec.started.timestamp(),
                                                          end.timestamp() + SHOT_AFTER_S)):
            stamp, _, label = p.stem.partition("-")
            try:
                at = datetime.strptime(f"{p.parent.parent.name} {stamp}", "%Y-%m-%d %H%M%S")
            except ValueError:
                continue
            shots.append((label, at, p))
        files: dict[str, str] = {}
        for t, (_, fin) in times.items():
            for label, at, p in shots:
                if (label == task_shots.plain_name(t)
                        and -SHOT_BEFORE_S <= (at - fin).total_seconds() <= SHOT_AFTER_S):
                    files[t] = _state_relative(eng.cfg.state_dir, p)
                    break
        if files:
            rec.raw["tasks_shot"] = list(files)
            rec.raw["tasks_shot_files"] = files
    except Exception:
        log.warning("核对任务截图出错（这一趟的任务按日志里的证据算）", exc_info=True)


def _mark_task_trails(eng, rec: RunRecord) -> None:
    """raw['tasks_trail']: {task: maaend_fwlog.trail_entry} for each of
    maaend_fwlog.TRAIL_TASKS this run finished (its 「任务完成」, not a weekday skip):
    whether MaaFW's log holds its run, and whether its steps show the job done or
    nothing to do (maaend_fwlog.task_verdict). It is the game evidence of those tasks
    for core.maaend_unverified, and machine check #28 reads its verdict from here
    (machinechecks/runs.py) instead of reading MaaFW's log again; the desktop picture
    (_mark_task_shots) is no evidence, since it is taken 5-8 s after the task ended and
    shows the next one (task_shots.py).

    raw['tasks_trail_miss']: when one of those tasks is unread (maaend_fwlog.trail_table:
    none of them is in MaaFW's log - the folder is not configured, MaaEnd cleared it at
    a restart, a file could not be read - or the log, rotated or cleared inside the run,
    does not reach back to that task's start), how many MaaEnd runs in a row that is,
    this one included (_trail_miss_streak); 0 otherwise. Below
    maaend_fwlog.TRAIL_MISS_FAIL the unread tasks are left unjudged - said at INFO and
    in the daily report (core.maaend_unjudged), not pushed - as #28 does; the tasks the
    log does hold are judged as usual.

    Booked here, while MaaFW's log still holds the run: MaaEnd clears its debug folder
    when it restarts. Keys of their own, so collector.refresh_raw keeps them. Always
    set on a MaaEnd record ({} when the run did none of the four), which tells
    maaend_unverified the record was booked under this rule."""
    trails: dict = {}
    rec.raw["tasks_trail"] = trails
    rec.raw["tasks_trail_miss"] = 0
    try:
        from ark_relay.features import collector_maaend, collector_maaend as maaend_fwlog  # noqa: PLC0415
        log_path = rec.log_path
        if not log_path or not Path(log_path).is_file():
            return
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        times = collector_maaend.task_times(text)
        done = set(rec.raw.get("tasks_done") or [])
        skipped = rec.raw.get("maaend_tasks_skipped") or {}
        times = {t: v for t, v in times.items() if t in done and t not in skipped}
        table, why = maaend_fwlog.trail_table(getattr(eng.cfg, "maaend_dir", None), times, text)
        trails.update(table)
        if not why:
            return
        miss = _trail_miss_streak(eng, rec)
        rec.raw["tasks_trail_miss"] = miss
        unread = [t for t, e in table.items() if e.get("unread")]
        log.info("%s：%s 在终末地自己的记录里读不到（%s），连续第 %d 趟；%s", rec.run_id, "、".join(unread), why,
                 miss, "到了次数，按没证据算" if miss >= maaend_fwlog.TRAIL_MISS_FAIL else "这一趟先不判，写进日报")
        if unread and miss < maaend_fwlog.TRAIL_MISS_FAIL:
            try:
                from ark_relay.core import statestore as techlog  # noqa: PLC0415
                techlog.self_heal(f"MaaEnd {rec.run_id} 自己的记录没读到",
                                  f"{'、'.join(unread)} 这一趟先不判（{why}），连续第 {miss} 趟",
                                  state_dir=getattr(eng.cfg, "state_dir", None))
            except Exception:  # the booking stands; only the red item is missing
                log.info("「自己的记录没读到」的红项没写进技术日志（%s）", rec.run_id, exc_info=True)
    except Exception:
        log.warning("没读成终末地自己的任务记录（这一趟的四个任务只按日志里的行算）", exc_info=True)


def _trail_miss_streak(eng, rec: RunRecord) -> int:
    """1 + the tasks_trail_miss of the MaaEnd run booked last before this one (today's
    and yesterday's ledger) among those that asked MaaFW's log about any of the four
    tasks; 1 when that run found them or there is none. Read from the ledger, so a
    record handled again (handle._append_ledger_once) does not count twice."""
    try:
        day = datetime.strptime(run_day(rec), "%Y-%m-%d")
        rows = [*eng.state.read_ledger((day - timedelta(days=1)).strftime("%Y-%m-%d")),
                *eng.state.read_ledger(run_day(rec))]
        before = sorted((e for e in rows if e.get("script") == "MaaEnd" and e.get("run_id") != rec.run_id
                         and (e.get("started") or "") < rec.started.isoformat()
                         and (e.get("raw") or {}).get("tasks_trail")),
                        key=lambda e: e.get("started") or "")
    except Exception:  # no history: this run counts as the first in a row
        log.info("读不到前几趟的账，这一趟按连续第 1 趟算", exc_info=True)
        return 1
    if not before:
        return 1
    return int((before[-1].get("raw") or {}).get("tasks_trail_miss") or 0) + 1


def _state_relative(state_dir, p: Path) -> str:
    """`p` as written under the state folder (shots/<day>/...), or the whole path when it is elsewhere."""
    try:
        return Path(p).relative_to(Path(state_dir)).as_posix()
    except ValueError:
        return str(p)


def _restore_after_maaend(eng) -> None:
    """A MaaEnd record has landed: put back what a retry or a make-up narrowed."""
    # A MaaEnd record ending means AUTO-MAS's retry round (if any) is over:
    # whatever narrowing was done for it must go back before anything else.
    try:
        from ark_relay.features import collect_retry  # noqa: PLC0415
        if back := collect_retry.restore_master(eng.cfg):
            log.info("🔁 %s", back)
    except Exception:
        log.exception("母本路线改回出错")
    # Same for the make-up's narrowing (makeup.py): AUTO-MAS writes a
    # script's records once all its attempts are over, so the make-up run
    # and its own retries are done by now.
    try:
        from ark_relay.features import makeup  # noqa: PLC0415
        back, err = makeup.try_restore(eng.cfg, eng.notifier)
        if back:
            log.info("🔁 %s", back)
        elif err:
            # A failure, so it reaches the group (errwatch pushes every
            # WARNING). makeup's own alarm (both files unreadable) may say
            # the same; try_restore does not tell whether it sent one, so this
            # line is not held back on a guess.
            log.warning("补跑的母本没能改回（%s）", err)
    except Exception:
        log.exception("补跑的母本改回出错")


def _confirm_unreachable(eng, rec: RunRecord) -> None:
    """A MaaEnd failure shaped like "never got into the game" is that only when
    there is evidence the game itself was unavailable.

    `maaend_unreachable` skips the alarm (_flush_pending), the make-up
    (makeup.eligible), and registers a client update plus a re-run after the
    queue (gameupdate.mark_pending -> run_deferred kills the game, opens the
    launcher and re-dispatches MaaEnd via needs_rerun). The log's shape alone
    (collector_maaend.maaend_unreachable) is also what a lost game window or a
    crash at the title screen looks like, so it is set only on an official
    maintenance window (gameupdate.in_maintenance) or an official update notice
    for today (efstatus.update_hint). Without either the run is an ordinary
    failure: held, made up, and alarmed on like any other; the shape stays in
    `maaend_unreachable_shape` for the alarm text. Runs before the ledger line
    is written so the daily report reads the same verdict.
    """
    raw = rec.raw   # RunRecord.raw defaults to a dict
    shape = raw.pop("maaend_unreachable", None) or raw.get("maaend_unreachable_shape")
    if rec.script != "MaaEnd" or rec.ok or not shape:
        return
    if raw.get("maaend_update_restart"):
        # Every task failing at once is what MaaEnd restarting into its new build
        # looks like (MXU's own log proves the install, _mark_update_restart). Not a
        # fault to warn about - the WARNING below reaches the group (errwatch) and
        # said 「报警、补跑」 about an attempt that is let go when its shift is done -
        # and not the alarm note 「看着像没进游戏」 either.
        raw.pop("maaend_unreachable_shape", None)
        log.info("MaaEnd %s 每个任务秒败，是装新版 %s 后自己重启造成的，不按没进游戏算",
                 rec.run_id, raw["maaend_update_restart"])
        return
    raw["maaend_unreachable_shape"] = True
    why = ""
    unread = False
    try:
        from ark_relay.features import gameupdate  # noqa: PLC0415
        why = gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started)
    except Exception:  # logged with the traceback
        log.warning("查不了维护窗口，%s 按普通失败处理", rec.run_id, exc_info=True)
        unread = True
    if not why:
        try:
            why = efstatus.update_hint(rec.started, strict=True)
        except Exception:  # the alarm says the notice was not read
            log.info("终末地更新公告没读到，%s 按普通失败处理", rec.run_id, exc_info=True)
            unread = True
    if unread and not why:
        raw["maaend_unreachable_unread"] = True
    if why:
        raw["maaend_unreachable"] = True
        raw["maaend_unreachable_why"] = why
        log.info("⏸ MaaEnd %s 每个任务秒败、零完成，且有官方依据（%s）：按进不了游戏处理", rec.run_id, why)
    else:
        log.info("❌ MaaEnd %s 每个任务秒败、零完成，像没进游戏，但没有官方维护或更新公告："
                 "按普通失败处理（报警、补跑）", rec.run_id)


def _mark_raw_on_ledger(eng, rec: RunRecord, key: str, value) -> None:
    """A raw field learned after the run's ledger line was written goes onto that line."""
    day = run_day(rec)
    if not eng.state.mark_raw(day, rec.run_id, key, value):
        log.warning("没能把 %s 写回 %s 的账本", key, rec.run_id)


def _attempts(eng, rec: RunRecord, day: str) -> int:
    """How many tries the failed streak `rec` belongs to took: the failed rows of the
    same script and user in `rec`'s shift since the last row that exited normally,
    plus the success that healed it when there is one (「跑了 N 次」).
    """
    unresolved = _sys.modules[__name__]
    try:
        shift = unresolved.where(eng, rec)
    except Exception:  # noqa: BLE001 - no shift known: the streak alone bounds the count
        shift = None
    rows = []
    for d in dict.fromkeys((day, shift[0] if shift else day)):
        rows += [e for e in eng.state.read_ledger(d)
                 if e.get("script") == rec.script and e.get("user") == rec.user
                 and core.maa_mode(e) == core.maa_mode({"script": rec.script, "raw": rec.raw})
                 and _row_started(e) is not None]
    rows.sort(key=_row_started)
    n = 0
    for e in rows:
        raw = e.get("raw") or {}
        if raw.get("hand_started") or core.manual_stop(e):
            continue
        if shift is not None and e.get("run_id") != rec.run_id:
            try:
                if unresolved.where(eng, unresolved._row_rec(e)) != shift:
                    continue
            except Exception:  # noqa: BLE001 - unknown shift: judged by the streak alone
                pass
        if e.get("ok"):
            if _row_started(e) >= rec.started:
                return n + 1   # the success that healed it is the streak's last try
            n = 0              # a success before it ends the streak before it
        elif not e.get("transitional") or raw.get("maaend_update_restart"):
            n += 1
    return n


def _row_started(e: dict) -> datetime | None:
    """A ledger row's start as an aware time; None when unreadable or naive."""
    try:
        t = datetime.fromisoformat(str(e.get("started")))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else None


def _diagnosis(eng, rec: RunRecord) -> str:
    """What is known about why `rec` failed: a known cause as it is, the model asked
    only about the rest."""
    tail = eng.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
    causes = (rec.raw or {}).get("maaend_fail_causes") or {}
    # An unconfirmed cause states what was seen, not why: still ask about it.
    from ark_relay.features.collector_maaend import CLAIM_UNCONFIRMED  # noqa: PLC0415
    known = {k: v for k, v in causes.items() if v != CLAIM_UNCONFIRMED}
    rest = [t for t in rec.failed_tasks if t not in known]
    return "\n".join(x for x in (
        texts.ANNIHILATION_NO_PROXY if (rec.raw or {}).get("annihilation_no_proxy") else "",
        texts.known_cause(causes),
        summary.diagnose(eng.cfg, rec.script, rest, tail) if rest or not known else "",
    ) if x)


def _later_success(eng, rec: RunRecord) -> str:
    """run_id of a ledger row of the same script and user (and MAA job, core.maa_mode),
    started after `rec`, that exited normally with nothing left undone and was not
    cut short by the red button; '' when there is none."""
    day = run_day(rec)
    for e in eng.state.read_ledger(day):
        if ((e.get("script"), e.get("user")) != (rec.script, rec.user) or not e.get("ok")
                or e.get("incomplete") or core.manual_stop(e)
                or core.maa_mode(e) != core.maa_mode({"script": rec.script, "raw": rec.raw})):
            continue
        try:
            after = datetime.fromisoformat(str(e.get("started"))) > rec.started
        except (TypeError, ValueError):   # unreadable, or naive against aware: not known to be later
            continue
        if after:
            return str(e.get("run_id") or "")
    return ""


def _restart_result(rec: RunRecord) -> str:
    """What AUTO-MAS recorded as the result of an attempt ('' when it wrote none)."""
    raw = rec.raw or {}
    return str(raw.get("general_result") or raw.get("maa_result") or raw.get("maaend_result") or "").strip()


def _restart_note(rec: RunRecord) -> str:
    """The line a final alarm carries when its held record is an attempt AUTO-MAS
    recorded as a restart (collector._TRANSITIONAL; held by _handle) and no record
    of the script came after it; '' for any other record."""
    if not rec.transitional or (rec.raw or {}).get("maaend_update_restart"):
        return ""
    return texts.restart_was_last(_restart_result(rec), rec.started.astimezone(SERVER_TZ).strftime("%H:%M"))


def _healed_title(eng, rec: RunRecord, day: str) -> str:
    """What a held failure that recovered is called in relay.log (_flush_pending):
    its make-up went through (MAA / MaaEnd), it sat in an update's streak
    (core.episode_kinds 「update」), or AUTO-MAS's own retry got past it."""
    if rec.script in ("MAA", "MaaEnd"):
        unresolved = _sys.modules[__name__]
        if unresolved.after_makeup(eng, rec)[0] == unresolved.PASSED:
            return texts.makeup_passed(unresolved.GAME[rec.script], unresolved.where(eng, rec)[1])
    if core.episode_kinds(eng.state.read_ledger(day)).get(rec.run_id) == "update":
        return texts.healed_after_update(rec.script)
    return texts.self_healed(rec.script)


# Same logger as handle.py: relay.log names these lines "ark.handle".


# What _verify_outcome found for each record it checked, until the record's machine
# checks have read it (_judge_run pops it): the outcome checks, the summary and, for
# OK-WW, the nest settings they were judged with.
_OUTCOME: dict[str, dict] = {}
# The items of the 「没证据」 alarm pushes._push_unverified sent (or kept for the next
# tick) while each record was booked, until its machine checks have read them
# (_judge_run pops it): #28 does not push a FAIL that alarm already carries.
_UNVERIFIED: dict[str, list] = {}


def _judged(rec: RunRecord, checks: list, who: str, **extra) -> str | None:
    """outcome.summarize(checks, who), keeping the checks for the machine checks."""
    msg = outcome.summarize(checks, who)
    _OUTCOME[rec.run_id] = dict(extra, checks=list(checks), msg=msg)
    return msg


def _alert_days() -> list[str]:
    """Yesterday and today in Beijing time, as the alarm copies name their day files."""
    from ark_relay.features import errwatch as alertlog  # noqa: PLC0415
    now = alertlog.beijing()
    return [(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")]


def _alert_file(state_dir, day: str) -> Path:
    return Path(state_dir) / "alerts" / f"{day}.jsonl"


def _alert_sizes(state_dir) -> dict[str, int]:
    """{day: bytes} of the alarm copies (alertlog.py) as they are now; 0 for a day with none."""
    out: dict[str, int] = {}
    for day in _alert_days():
        try:
            out[day] = _alert_file(state_dir, day).stat().st_size
        except OSError:
            out[day] = 0
    return out


def _alerts_since(state_dir, marks: dict[str, int]) -> list[dict]:
    """The alarm copies written after `marks` (_alert_sizes): what went to the group since."""
    rows: list[dict] = []
    for day in dict.fromkeys([*marks, *_alert_days()]):
        try:
            data = _alert_file(state_dir, day).read_bytes()
        except OSError:
            continue
        for line in data[marks.get(day, 0):].decode("utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


class _RunWatch(logging.Handler):
    """What happened while one record was handled, for its machine checks: which
    records were held before, the relay's own WARNING / ERROR lines on this thread
    (each reaches the group through errwatch unless it says it was delivered
    already or recovered), and the alarms whose copies landed in state/alerts.

    Never raises: not knowing leaves the checks less to read, never the record unbooked."""

    def __init__(self, eng):
        super().__init__(level=logging.WARNING)
        self.eng = eng
        self.thread = threading.get_ident()
        self.errors: list[dict] = []
        self.held_before: dict[str, RunRecord] = {}
        self.marks: dict[str, int] = {}
        self._logger = None

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread:
            return
        try:
            from ark_relay.features import errwatch  # noqa: PLC0415
            self.errors.append({"level": record.levelname, "logger": record.name,
                                "msg": record.getMessage()[:500],
                                "pushed": bool(getattr(record, errwatch.PUSHED, False)),
                                "recovered": bool(getattr(record, errwatch.RECOVERED, False))})
        except Exception:  # noqa: BLE001 - a log line must never fail because of this
            pass

    def __enter__(self):
        try:
            self.held_before = {r.run_id: r for r in list(getattr(self.eng, "_pending", {}).values())}
            self.marks = _alert_sizes(self.eng.cfg.state_dir)
            from ark_relay.features import errwatch  # noqa: PLC0415
            self._logger = logging.getLogger(errwatch.ARK)
            self._logger.addHandler(self)
        except Exception:
            log.debug("上机核对的记录器没装上", exc_info=True)
        return self

    def __exit__(self, *exc) -> bool:
        if self._logger is not None:
            self._logger.removeHandler(self)
        return False

    def alerts(self) -> list[dict]:
        try:
            return _alerts_since(self.eng.cfg.state_dir, self.marks)
        except Exception:
            log.warning("读报警抄送出错，上机核对按没看到报警处理", exc_info=True)
            return []


def _test_run(eng, rec: RunRecord) -> bool:
    """Inside a test window run-one.sh marked (core.split_test): not an unattended run."""
    from ark_relay.features import report  # noqa: PLC0415
    windows = report.test_windows(eng.cfg.state_dir)
    return bool(core.split_test([{"started": rec.started.isoformat()}], windows)[1])


def _update_restarts(eng, rec: RunRecord) -> dict:
    """{run_id: {version, started, done, held}} for every MaaEnd update restart on the
    ledger of the record's day and the day before (this record included): `done` is
    the round of the same shift that got everything done (unresolved.done_in_shift),
    '' when there is none; `held` whether it is still held for a later push."""
    unresolved = _sys.modules[__name__]
    day = rec.started.astimezone(SERVER_TZ)
    rows: dict[str, dict] = {}
    for d in ((day - timedelta(days=1)).strftime("%Y-%m-%d"), day.strftime("%Y-%m-%d")):
        for e in eng.state.read_ledger(d):
            if e.get("script") == "MaaEnd" and (e.get("raw") or {}).get("maaend_update_restart"):
                rows[str(e.get("run_id"))] = e
    held = {r.run_id for r in eng._pending.values()}
    out: dict = {}
    for rid, e in rows.items():
        r = unresolved._row_rec(e)
        if r.started is None:
            continue
        try:
            done = unresolved.done_in_shift(eng, r)
        except Exception:  # the check then has nothing to judge about it
            log.warning("查不了 %s 那一班有没有做完的那趟，上机核对跳过它", rid, exc_info=True)
            continue
        out[rid] = {"version": str(e["raw"]["maaend_update_restart"]), "started": r.started.isoformat(),
                    "done": done, "held": rid in held}
    return out


def _run_ctx(eng, rec: RunRecord, watch: _RunWatch) -> dict:
    """The context of the 「run」 event (machinecheck.EVENTS): the record, its raw
    dict, its run log, and what the relay did about it."""
    text = ""
    unreadable = False
    if rec.log_path:
        try:
            text = Path(rec.log_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # The log-based checks return "not applicable" on empty text, which
            # would read as "nothing to check" rather than "could not check".
            log.warning("%s 的运行日志读不到（%s: %s），按日志判的上机核对这一趟都没判",
                        rec.run_id, type(exc).__name__, exc)
            text, unreadable = "", True
    day = run_day(rec)
    ctx = {
        "rec": rec, "raw": rec.raw, "log_text": text, "day": day,
        "outcome": _OUTCOME.get(rec.run_id),
        "unverified_alarm": list(_UNVERIFIED.get(rec.run_id) or []),
        "held_before": list(watch.held_before),
        "held": [r.run_id for r in eng._pending.values()],
        "unsent": [x[2] for x in getattr(eng, "_unsent_unresolved", []) or []],
        "alerts": watch.alerts(),
        "relay_errors": list(watch.errors),
        "ledger": eng.state.read_ledger(day),
        "test_run": _test_run(eng, rec),
        "maaend_dir": eng.cfg.maaend_dir,
    }
    if hasattr(eng, "_already_alerted"):
        # The day marks a #28 FAIL pushed at once is marked in once its push went out
        # (runs._hold_28, Result.after_push), as settle_28 checks.
        ctx["alerted"] = (eng._already_alerted, eng._mark_alerted)
    if unreadable:
        ctx["log_unreadable"] = True
    if rec.script == "MaaEnd":
        ctx["update_restarts"] = _update_restarts(eng, rec)
    if rec.script == "OK-WW":
        from ark_relay.features import okww_overlay  # noqa: PLC0415
        ctx["overlay"] = okww_overlay.report_snapshot()
    return ctx


def _one_pass(fn):
    """`fn` (handle._handle: one booking; handle._flush_pending: one tick's) as one
    pass of machinecheck-runs.json reads (machinechecks/runs.py one_pass): a lock on
    the file is waited out once in it, not on every read."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        from ark_relay.features import machinechecks as runs  # noqa: PLC0415
        with runs.one_pass():
            return fn(*args, **kwargs)
    return run


def _settle_held(eng) -> None:
    """Settle the machine-check FAILs kept while their run was held for its retry
    (machinechecks/runs.py settle_28) whose hold is over: no record of that script and
    user held any more, the script not running. After every booking and every
    _flush_pending; never raises (a broken settle is an ERROR, which reaches the group,
    and the FAILs stay kept for the next one). A machinecheck-runs.json that cannot be
    read is one ERROR naming the holds stuck behind it until it reads again
    (runs.held_stuck), not a settle skipped without a word."""
    state_dir = getattr(getattr(eng, "cfg", None), "state_dir", None)
    if not state_dir:
        return
    try:
        from ark_relay.features import machinechecks as runs  # noqa: PLC0415
        if not runs.held_stuck(state_dir):
            return
        held = {(r.script, r.user) for r in eng._pending.values()}
        runs.settle_28(state_dir,
                       lambda script, user: (script, user) not in held and not eng._script_running(script),
                       eng.state.read_ledger, eng.notifier,
                       alerted=(eng._already_alerted, eng._mark_alerted))
    except Exception:
        log.exception("上机核对等重试的那几条没结成（下一轮再结）")


# Same logger as handle.py: relay.log names these lines "ark.handle".


def _activity_topup(eng, rec: RunRecord, text: str, checks: list) -> None:
    """Daily activity short of 100 with the waveplates spent: 「晚班补」, not undone (activity.py)."""
    try:
        from ark_relay.features import activity  # noqa: PLC0415
        activity.morning(eng, rec, text, checks)
    except Exception:  # the round is still judged; the item stays undone
        log.warning("鸣潮活跃晚班补没记上", exc_info=True)


def _verify_outcome(eng, rec: RunRecord) -> str | None:
    """Check against the evidence what this round actually accomplished; returns None when everything was done.

    The criteria live in `outcome.py`, with samples taken from real logs. This
    function only assembles the log text and what was supposed to happen -
    **a failed check must never block bookkeeping**, so the whole body is wrapped
    in try: an error in the check itself only writes a log line and does not
    change existing behaviour.
    """
    try:
        text = ""
        if rec.log_path and rec.log_path.exists():
            text = rec.log_path.read_text(encoding="utf-8", errors="replace")
        if not text and rec.script in ("OK-WW", "MaaEnd"):
            return _judged(rec, [outcome.Check(
                "能读到 AUTO-MAS 这一轮的运行日志", False,
                f"{rec.log_path or '没有 .log 文件'}：AUTO-MAS 只留下了「正常退出」的记录，"
                "没有这一轮的日志，做没做成核对不了")], rec.script)
        if rec.script == "OK-WW":
            expect_nest = _okww_nest_expected(eng.cfg.automas_dir)
            if expect_nest is None:
                # If the config cannot be read, say so; never quietly drop the
                # tacet-nest check.
                checks = outcome.okww_checks(text, expect_nest=False)
                checks.append(outcome.Check(
                    "能读到 OK-WW 生效中的配置", False,
                    f"{eng.cfg.automas_dir}/data/*/Default/ConfigFile/ "
                    "下没读到 DailyTask.json（该不该打残象聚落只看它），"
                    "所以这一轮该不该打残象聚落无从判断"))
            else:
                only = (_okww_master_config(eng.cfg.automas_dir, "NightmareNestTask")
                        .get("Only Farm These Nests") or "").strip()
                checks = outcome.okww_checks(text, expect_nest=expect_nest, only_nest=only)
                _activity_topup(eng, rec, text, checks)
                return _judged(rec, checks, "OK-WW", expect_nest=expect_nest, only_nest=only)
            _activity_topup(eng, rec, text, checks)
            return _judged(rec, checks, "OK-WW", expect_nest=None, only_nest="")
        if rec.script == "MAA":
            # Only MAA's own log is read: AUTO-MAS's history carries no per-
            # subtask success or failure.
            # The finish time is used as the upper bound only when it is
            # trustworthy (see RunRecord.duration_known).
            # Leave 5 minutes of slack: MAA's wrap-up lines can land after
            # AUTO-MAS has already recorded the run.
            until = (rec.finished + timedelta(minutes=5)
                     if rec.duration_known else None)
            maa_log = _maa_app_log(eng.cfg.maa_dir, rec.started, until)
            if maa_log is None:
                # Feeding empty text to maa_checks passes every check = another
                # false green.
                return _judged(rec, [outcome.Check(
                    "能读到 MAA 自己的日志", False,
                    f"maa_dir={eng.cfg.maa_dir}，"
                    "MAA 自己的日志里没有这一轮的记录，基建做没做成核对不了")],
                    "MAA")
            return _judged(rec, outcome.maa_checks(maa_log), "MAA")
        if rec.script == "MaaEnd":
            # AUTO-MAS closes a retry round with one more record whose whole log
            # is MAAEND_NOTHING_TO_RUN_LOG - bookkeeping, not a run: no MaaEnd
            # process, no app log. Judged as a run it would fail the
            # completion-marker check: the record starts after the real run's log
            # was last written, so the mtime cut in _maaend_app_log excludes it.
            if MAAEND_NOTHING_TO_RUN in text:
                log.info("%s 是 AUTO-MAS 的收尾记录（没有可执行任务），不是一趟运行，不核对", rec.run_id)
                return None
            # Bounded above like MAA's log: a round judged late must not take the
            # later rounds' pictures and lines as its own.
            until = collector_maaend.round_until(rec)
            shots = _maaend_new_shots(eng.cfg.maaend_dir, rec.started, until)
            # Read AUTO-MAS's history log together with MaaEnd's own app log:
            # the wrap-up marker only exists in the latter and task start/finish
            # only in the former, so missing either one misjudges the round.
            app = _maaend_app_log(eng.cfg.maaend_dir, rec.started, until)
            both = text + "\n" + app
            # Only with MaaEnd's own log in hand: the wrap-up line lives there, and
            # without it every run would look like one that did not exit.
            own = bool(app.strip())
            if outcome.maaend_no_self_exit(both, own_log=own):
                _mark_no_self_exit(eng, rec)
            # The pictures go with the checks: machine check #29 judges this booking
            # on the very same set (runs._c29).
            return _judged(rec, outcome.maaend_checks(both, shots, own_log=own), "MaaEnd", shots=shots)
    except Exception as exc:
        log.exception("结果核对本身出错")
        # None would mean "everything was done"; a check that crashed has
        # verified nothing, so it says so. Bookkeeping is unaffected either way
        # (this function only decides whether to say one extra thing).
        return (f"{rec.script} 这一轮的结果核对没跑成（{type(exc).__name__}: "
                f"{exc}），所以「干成了没有」这次没人验过。")
    return None


def _mark_no_self_exit(eng, rec: RunRecord) -> None:
    """Book 「all tasks done, MaaEnd did not exit」 with how long it then sat idle.

    The idle span runs from the log's last line to AUTO-MAS's own result line in
    app.log, in minutes; 0 when that line is not there to read.

    The hang is upstream MistEO/MXU#371. AUTO-MAS v5.7.0-beta.2 ends such a MaaEnd
    itself right after recording the result (collector._automas_ended_maaend reads
    its line): the run is done and AUTO-MAS handles it by design, so that case is an
    INFO line only. No such AUTO-MAS line and the WARNING is pushed (errwatch).
    """
    from ark_relay.core.collector import _automas_ended_maaend, _automas_result_time  # noqa: PLC0415
    # Read from handle at call time: tests rebind handle._ship_evidence.
    pass
    idle, ended_by_mas = 0, None
    if eng.cfg.history_dir and (ended := _automas_result_time(eng.cfg.history_dir, rec.script, rec.started)):
        idle = max(0, int((ended - rec.finished).total_seconds() // 60))
        ended_by_mas = _automas_ended_maaend(eng.cfg.history_dir, ended)
    rec.raw["maaend_no_self_exit"] = idle
    day = run_day(rec)
    eng.state.mark_raw(day, rec.run_id, "maaend_no_self_exit", idle)
    if ended_by_mas is not None:
        # Handled: AUTO-MAS ends it on its own path every time, the run's work is
        # done and the cause is known (MXU#371), so there is nothing to look into.
        # Kept in the relay log and the technical section of the daily report.
        log.info("MaaEnd %s 任务全部完成，跑完没自己退出（空等 %d 分钟）；AUTO-MAS %s 记下结果后按设计结束了它"
                 "（上游 MXU#371）", rec.run_id, idle, ended_by_mas.strftime("%H:%M:%S"))
    else:
        # Every task was done; only the exit was missing, and AUTO-MAS did not end
        # it on its own path: pushed (errwatch).
        log.warning("🟠 MaaEnd %s 任务全部完成，但跑完没自己退出（空等 %d 分钟）", rec.run_id, idle)
    # The run is ok, so the failure path never ships its bundle, and MXU's own log
    # of the hang (why the quit-after-run exit never fired) would stay on the
    # machine. Ship it here, once per record: a replay of the record finds the
    # link already on it.
    if not rec.raw.get("evidence_page"):
        _ship_evidence(eng, rec)


_log_missed = logging.getLogger("ark.missed")

# How long past a queue's time before "it produced nothing" becomes a fault.
MISSED_GRACE_MIN = 25


# ---------- a run that should have happened and did not ----------


def _queue_run(e: dict, q: dict) -> bool:
    """A ledger line that can be queue `q`'s run: one of its scripts, not started by hand."""
    kinds = q.get("kinds") or ()
    return (not kinds or e.get("script") in kinds) and not (e.get("raw") or {}).get("hand_started")


def _check_missed_runs(eng, now: datetime | None = None,
                       grace_min: int = MISSED_GRACE_MIN) -> None:
    """Alert when a scheduled queue produced nothing.

    "Did not run" is as much a fault as "ran and failed", and it is the
    one the operator is least likely to notice on their own - silence
    looks exactly like everything being fine.

    Only covers windows while the relay itself is up. A machine that never
    powered on cannot be caught from inside it; that is the GitHub Actions
    watchdog's job (scripts/watchdog.py, reading Tailscale lastSeen).
    """
    from ark_relay.features import errwatch  # noqa: PLC0415
    # Checked and pushed in debug mode too: a queue that did not run is an error.
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    entries = eng._recent_entries(now)
    for q in plan.schedule(eng.cfg.automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not plan.runs_at(q, hhmm, due):
                continue  # not a run day for this time, or every item sits today out
            if now < due + timedelta(minutes=grace_min):
                continue  # not late yet
            key = f"{day}/{q['name']}/{hhmm}"
            # one fault, one push: one queue that did not run at its time (queue + due time today), checked every tick
            if _settled(eng, day, key):
                continue
            # The stage gate took MAA out of this run and nothing else was in it
            # (stagegate.py): nothing was meant to run; its alarm already went out.
            if stagegate.settled_alone(eng.cfg.state_dir, q["name"], due):
                _settle(eng, day, key)
                continue
            # Skipped today on purpose (phone switch / order-now skip_today): its restore after
            # the slot re-enables the queue, and this check must not read that as a missed run.
            if _sat_out(eng, day, q["name"]):
                _settle(eng, day, key)
                continue
            ran = any(datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ) >= due - timedelta(minutes=5)
                      and _queue_run(e, q) for e in entries)
            if ran:
                _settle(eng, day, key)   # settled, stop checking
                continue
            # Was this machine even awake when the queue was due? If it
            # was off, "nothing ran" is not something this relay can
            # observe from the inside, and claiming it would be a false
            # alarm every single morning - that is the GitHub Actions
            # watchdog's job instead.
            #
            # Uptime, not the relay's own start time. Those differ every
            # time the relay restarts itself for a selfupdate, and an
            # update that runs long enough to cross the queue's time used
            # to make the new process disqualify itself - swallowing a
            # genuine missed run on precisely the boot where something had
            # already gone slowly enough to be worth knowing about.
            watching_since = eng._boot_time(now) or eng._started_at
            if watching_since > due:
                _settle(eng, day, key)
                continue
            if eng._scripts_running():
                # No record yet while a script process is alive (AUTO-MAS
                # retrying, say) is not "did not run". Running far too long is a
                # fault of its own, reported by runwatch.check_overrun.
                _log_missed.info("🔌 %s 还没有记录，但脚本进程在跑，先不喊（跑太久由在跑巡查报）", q["name"])
                continue
            late = int((now - due).total_seconds() // 60)
            title, body = core.format_missing(texts.not_run(q['name']), due,
                                              texts.missed_queue_body(late))
            if not (errs := eng.notifier.send(title, body, alert=True)):
                _settle(eng, day, key)
                _log_missed.warning("🔌 %s 该跑没跑，已告警", q["name"],
                            extra=errwatch.group_pushed(title, errs, eng.notifier))
    eng._check_partial_queues(now, day, entries)


def _sat_out(eng, day: str, queue: str) -> bool:
    """Whether `queue` was skipped on purpose on `day` (modes.sat_out); unreadable counts as no."""
    from ark_relay.core import config as names  # noqa: PLC0415
    from ark_relay.features import modes  # noqa: PLC0415
    try:
        return names.canonical(queue) in modes.sat_out(eng.cfg.state_dir, day)
    except Exception:  # noqa: BLE001 - a broken skip record must not silence a real missed run
        return False


def _check_partial_queues(eng, now: datetime, day: str,
                          entries: list[dict]) -> None:
    """Alert when a queue ran but one of its scripts never did.

    The check above only asks "did this queue produce anything": a queue whose
    MAA ran but whose Endfield never started counts as having run there. A
    queue that delivers half of what it promised is a fault, and it is
    invisible from the outside - the day looks green.

    Two things make this safe to alert on:

    Grace is generous. The morning queue runs MAA (~20 min) and only then
    MaaEnd (~25 min), so MaaEnd's record can legitimately be 45+ minutes
    late. Alerting at the same 25-minute mark as "nothing ran" would fire
    on every single healthy morning.

    Records are matched to their own queue by start time, so the morning's
    MaaEnd can never be mistaken for the evening's.
    """
    from ark_relay.features import errwatch  # noqa: PLC0415
    for q in plan.recent_due_queues(eng.cfg.automas_dir, now,
                                    window_minutes=eng.cfg.partial_window):
        due = q["due"]
        if now < due + timedelta(minutes=eng.cfg.partial_grace):
            continue  # still legitimately in progress
        ran = {e["script"] for e in entries
               if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
               >= due - timedelta(minutes=5) and _queue_run(e, q)}
        if not ran:
            continue  # nothing at all - already covered by the check above
        for kind in q["kinds"]:
            if kind in ran:
                continue
            # Pulled from this run by the stage gate (and put back afterwards).
            if kind == "MAA" and stagegate.excused(eng.cfg.state_dir, q["name"], due):
                continue
            # Still running or waiting its turn: its record has not landed yet. Only
            # that script holds this back - another script running elsewhere in the
            # queue says nothing about whether this one ever ran.
            if eng._script_running(kind):
                continue
            key = f"{day}/{q['name']}/{due:%H:%M}/{kind}"
            # one fault, one push: one script missing from one queue run (its due time), checked every tick
            if _settled(eng, day, key):
                continue
            # Was the machine awake when this queue was due? Same test,
            # and the same reason, as in _check_missed_runs: uptime rather
            # than the relay's start time, so a selfupdate restart cannot
            # make the relay disqualify itself from reporting a script that
            # never started.
            watching_since = eng._boot_time(now) or eng._started_at
            if watching_since > due:
                _settle(eng, day, key)
                continue
            late = int((now - due).total_seconds() // 60)
            title, body = core.format_missing(texts.not_run_in(kind, q['name']), due,
                                              texts.missed_item_body(list(ran), kind, late))
            if not (errs := eng.notifier.send(title, body, alert=True)):
                _settle(eng, day, key)
                _log_missed.warning("🔌 %s 缺项：%s 没跑，已告警", q["name"], kind,
                            extra=errwatch.group_pushed(title, errs, eng.notifier))


_MARK = "漏跑|"


def _settled(eng, day: str, key: str) -> bool:
    if key in eng._missed_alerted:
        return True
    if eng._already_alerted(day, _MARK + key):
        eng._missed_alerted.add(key)
        return True
    return False


def _settle(eng, day: str, key: str) -> None:
    eng._missed_alerted.add(key)
    eng._mark_alerted(day, _MARK + key)


_log_unresolved = logging.getLogger("ark.unresolved")

GAME = {"MAA": "明日方舟", "MaaEnd": "终末地"}
# A run started this long before its queue's time still belongs to it (the same
# allowance shutdown._unfinished_queues gives).
QUEUE_SLACK = timedelta(minutes=5)
# Without a readable queue config, a run before this hour is the morning shift.
NOON = 12

WAIT, PASSED, UNRESOLVED = "wait", "passed", "unresolved"


# The kind of the alarm `send` pushes for a failure its make-up did not fix.
UNRESOLVED_KIND = "未解决"


def alert_key(rec) -> str:
    """The alarm's identity: the record it is about, so the same record replayed is not pushed twice."""
    return _key(UNRESOLVED_KIND, rec.run_id)


def _key(kind: str, run_id: str) -> str:
    """「<kind>|<run_id>」: one alarm of one kind about one record (the marks in state.json)."""
    return f"{kind}|{run_id}"


def _day(t: datetime) -> str:
    return t.astimezone(SERVER_TZ).strftime("%Y-%m-%d")


def _at(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)


# ------------------------------------------------------------------ shifts

def shifts(automas_dir, state_dir, script: str, day: str) -> list[tuple[datetime, str]]:
    """(due, queue name) of every scheduled time on `day` whose queue runs `script`,
    earliest first; queues skipped that day are left out. [] when the queue config
    cannot be read."""
    from ark_relay.features import modes  # noqa: PLC0415
    from ark_relay.core import config as names, plan  # noqa: PLC0415
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return []
    base = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=SERVER_TZ)
    try:
        skipped = {names.canonical(q) for q in modes.skipped_today_all(Path(state_dir), base + timedelta(hours=12))}
    except Exception:  # noqa: BLE001 - an unreadable skip flag counts as no skip
        skipped = set()
    kinds = {uid: s.get("kind") for uid, s in plan._scripts(cfg_dir).items()}
    out: list[tuple[datetime, str]] = []
    for q in plan._queues(cfg_dir):
        name = names.canonical(q.get("name") or "")
        if name in skipped or script not in {kinds.get(uid) for uid in q.get("items") or []}:
            continue
        for hhmm in q.get("times") or []:
            try:
                hh, mm = (int(x) for x in str(hhmm).split(":"))
            except ValueError:
                continue
            out.append((base.replace(hour=hh, minute=mm), name))
    return sorted(out)


def _origin_started(eng, rec) -> datetime:
    """When the round `rec` belongs to started: the make-up's own record counts from
    the failure it made up for (a 14:00 make-up of the morning shift is still the
    morning shift's)."""
    from ark_relay.features import makeup  # noqa: PLC0415
    for day in (_day(rec.started), _day(rec.started - timedelta(days=1))):
        ent = makeup.read_marker(eng.cfg.state_dir, day).get(rec.script)
        if not isinstance(ent, dict) or ent.get("record") != rec.run_id or not ent.get("run_id"):
            continue
        try:
            rows = eng.state.read_ledger(day)
        except Exception:  # noqa: BLE001 - an unreadable ledger leaves the record's own time
            rows = []
        for e in rows:
            if e.get("run_id") == ent["run_id"] and (t := _at(e.get("started"))) is not None:
                return t
    return rec.started


def where(eng, rec) -> tuple[str, str]:
    """(day, shift) the record's round belongs to. The shift is the queue whose
    scheduled time came last before the round started (AUTO-MAS's QueueConfig);
    without a readable config, before NOON is 早班 and after it 晚班."""
    at = _origin_started(eng, rec).astimezone(SERVER_TZ)
    day = _day(at)
    try:
        due = shifts(eng.cfg.automas_dir, eng.cfg.state_dir, rec.script, day)
    except Exception:  # noqa: BLE001 - a broken config must not lose the alarm
        _log_unresolved.warning("读不到 %s 的班次，按中午前后分早晚班", day, exc_info=True)
        due = []
    names = [n for t, n in due if t - QUEUE_SLACK <= at]
    if names:
        return day, names[-1]
    return day, MORNING if at.hour < NOON else EVENING


def _row_rec(e: dict):
    """A ledger row in the shape `where` reads (script, user, run_id, started)."""
    return SimpleNamespace(script=e.get("script"), user=e.get("user"), run_id=e.get("run_id"),
                           started=_at(e.get("started")))


def done_in_shift(eng, rec) -> str:
    """run_id of another round of the same script and user in `rec`'s shift that
    started before `rec` and exited normally with nothing left undone; '' when
    there is none.
    """
    day, shift = where(eng, rec)
    for d in dict.fromkeys((day, _day(rec.started))):
        try:
            rows = eng.state.read_ledger(d)
        except Exception:  # noqa: BLE001 - an unreadable ledger finds nothing (keeps today's path)
            rows = []
        for e in rows:
            raw = e.get("raw") or {}
            if (e.get("run_id") == rec.run_id or e.get("script") != rec.script or e.get("user") != rec.user
                    or not e.get("ok") or e.get("incomplete") or e.get("transitional")
                    or raw.get("manual_stop") or raw.get("hand_started")):
                continue
            other = _row_rec(e)
            try:
                before = other.started is not None and other.started < rec.started
            except TypeError:   # naive against aware: not known to be earlier
                before = False
            if before and where(eng, other) == (day, shift):
                return e["run_id"]
    return ""


# ------------------------------------------------------- after the make-up

def _gave_up_phrase(note: str) -> str:
    if note.startswith("不补跑"):
        return "没补跑：" + note[len("不补跑"):].lstrip("：: ")
    return "补跑没能开跑" + (f"（{note}）" if note else "")


def after_makeup(eng, rec, now: datetime | None = None) -> tuple[str, str]:
    """(verdict, what to say about the make-up) for a held MAA / MaaEnd failure.

    WAIT while its make-up is still to come or running; PASSED when the make-up
    went through; UNRESOLVED otherwise, with the phrase for the alarm's head."""
    from ark_relay.features import makeup  # noqa: PLC0415
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if makeup.holding(eng, rec, now):
        return WAIT, ""
    day = _day(rec.started)
    ent = makeup.read_marker(eng.cfg.state_dir, day).get(rec.script)
    if not isinstance(ent, dict):
        if day != _day(now):
            return UNRESOLVED, "没补跑：没等到补跑就过了零点，补跑只补当天的"
        return UNRESOLVED, "没补跑"
    since = _at(ent.get("dispatched_at"))
    ours = (rec.run_id in (ent.get("run_id"), ent.get("record"))
            or (since is not None and rec.started < since - makeup.SLACK)
            or (since is None and not ent.get("run_id")))
    if not ours:
        # A later round of the same day (the evening shift after the morning's
        # make-up): the day's one make-up is spent.
        return UNRESOLVED, "没补跑：补跑一天只有一次，今天的已经用过了"
    res = ent.get("result")
    note = str(ent.get("note") or "").strip()
    if res == makeup.DISPATCHED:
        # makeup._settle_stale closes a stale one (today's and yesterday's); one
        # older than that nobody will close.
        if since is not None and now - since > timedelta(days=1):
            return UNRESOLVED, "补跑派下去了，没跑出记录"
        return WAIT, ""
    if res == makeup.OK:
        return PASSED, ""
    if res == makeup.FAILED:
        if note == makeup.STOPPED_NOTE:
            return UNRESOLVED, texts.MAKEUP_STOPPED_PHRASE
        return UNRESOLVED, "补跑也没成"
    if res == makeup.NO_RECORD:
        return UNRESOLVED, f"补跑派下去了，{makeup.STALE_MIN} 分钟没跑出记录"
    return UNRESOLVED, _gave_up_phrase(note)


# ------------------------------------------- rounds left undone (「没干完」)

_DANGLING = "开了没收尾："


def _undone_items(msg: str) -> list[str]:
    """The items an outcome summary (outcome.summarize) lists as not done."""
    out: list[str] = []
    for line in (msg or "").splitlines():
        if out and line.endswith(texts.OUTCOME_SETTINGS_HEAD):
            break
        if not line.startswith("· "):
            continue
        label, _, detail = line[2:].partition("：")
        if detail.startswith(_DANGLING):
            out += [x for x in detail[len(_DANGLING):].split("、") if x.strip()]
        else:
            out.append(label.split(" 真的", 1)[0].strip())
    return out


def undone_label(msg: str) -> str:
    """「基建换班、自动采集」 for the alarm's head; '' when the summary lists none."""
    items = list(dict.fromkeys(_undone_items(msg)))
    return "、".join(items[:3]) + ("…" if len(items) > 3 else "")


# ------------------------------------------------------------------- send

def send(eng, day: str, kind: str, run_id: str, title: str, body: str) -> bool:
    """Push one alarm to the group. True when it went out (or this very alarm went
    out before: the same record replayed); False when the push failed and the
    caller keeps it for the next tick.

    The alarm is one `kind` (未解决 / 手动 / 更新日 / 理智 / 停一切 / 停一切前)
    about one record, `run_id`; its key is built here from the two, so the only
    push this holds back is the same alarm about the same record a second time
    (handle.py replays a record whose handling broke off midway,
    _append_ledger_once)."""
    from ark_relay.features import errwatch  # noqa: PLC0415
    key = _key(kind, run_id)
    if eng._already_alerted(day, key):  # one fault, one push: the record's run_id in `key`
        _log_unresolved.info("%s %s 这一条已经进过群（同一条记录又处理了一遍），不重推", day, key)
        return True
    if errs := eng.notifier.send(title, body, alert=True):
        # A failure of its own: errwatch pushes this line too (queued until the group takes it).
        _log_unresolved.warning("「%s」没推出去，下一轮再试：%s", title, "；".join(errs))
        return False
    try:
        eng._mark_alerted(day, key)
    except Exception:  # noqa: BLE001 - it went out; only the record of that failed
        # Not raised: the caller would keep an alarm that went out for the next tick
        # and skip what follows a push (pushes._push_unverified: the cover of #28).
        _log_unresolved.error("「%s」已进群，但「已进群」没记进 state.json：这条记录若重新处理一遍，会再推一次",
                  title, exc_info=True)
    _log_unresolved.warning("🚨 %s 已进群：%s", title, body.replace("\n", " ")[:300],
                extra=errwatch.group_pushed(title, errs, eng.notifier))
    # Judged once it went out: one that did not is said above and tried again.
    machinecheck(eng, {"kind": kind, "run_id": run_id, "day": day, "title": title, "body": body,
                       "sent": True})
    return True


def machinecheck(eng, ctx: dict) -> None:
    """Hand one alarm decision to the machine checks (ark_relay/features/selfcheck/machinecheck.py, event
    「unresolved」; #21 / #34 / #55 in machinechecks/system.py). `copies` says whether
    the sender keeps the alarm copy those checks look in (notify.Notifier.alert_log).
    Never raises: a broken check must not break an alarm (judge logs it as ERROR)."""
    state_dir = getattr(getattr(eng, "cfg", None), "state_dir", None)
    if not state_dir:
        return
    try:
        from ark_relay.features import machinecheck as mc  # noqa: PLC0415
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        notifier = getattr(eng, "notifier", None)
        mc.judge(state_dir, "unresolved", dict(ctx, copies=hasattr(notifier, "alert_log")),
                 notifier=notifier, version=str(StateStore(state_dir).get("versions", "code") or ""))
    except Exception:  # noqa: BLE001
        _log_unresolved.exception("上机核对（报警那一步）自己出错，报警照常")


def retry_unsent(eng) -> None:
    """Push again what `send` could not deliver (the 「没干完」 path holds no record)."""
    left = []
    for day, kind, run_id, title, body in getattr(eng, "_unsent_unresolved", []):
        if not send(eng, day, kind, run_id, title, body):
            left.append((day, kind, run_id, title, body))
    eng._unsent_unresolved = left


# This module's public names plus every name re-exported from the modules above
# (callers and tests say handle.<name>); pyflakes and ruff count a listed name as used.


def _self_heal_red(eng, where: str, why: str) -> None:
    """A held failure that healed itself stays out of the group; one red item in the
    technical log says a session has to look at why it failed (techlog.self_heal)."""
    from ark_relay.core import statestore as techlog  # noqa: PLC0415
    try:
        techlog.self_heal(where, why, state_dir=getattr(eng.cfg, "state_dir", None))
    except Exception:  # the booking goes on; the group hears the failure to write
        log.warning("自愈待查的红项没写进技术日志：%s", where, exc_info=True)


# ---------- per record ----------

def _warn_if_evidence_stale(eng, rec: RunRecord, dst: Path) -> None:
    """The archived debug log is not necessarily from the failing run - say so plainly when it does not line up, rather than misleading the reader.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_warn_if_evidence_stale」。
    """
    try:
        cut = rec.started.timestamp()
        began = rec.started.astimezone(SERVER_TZ)
        for f in dst.glob("*.log"):
            if f.name.startswith("automas-"):
                continue          # this one was taken by run_id, so it always lines up
            mtime = f.stat().st_mtime
            if mtime < cut:
                mt = datetime.fromtimestamp(mtime, tz=SERVER_TZ)
                log.info("⚠️ 证据里的 %s 最后写于 %s，早于这一轮开始的 %s，"
                         "是**别的轮次**的日志，别拿它当这次失败的依据",
                         f.name, mt.strftime("%m-%d %H:%M:%S"), began.strftime("%m-%d %H:%M:%S"))
    except Exception:  # the booking goes on; the group hears the check broke
        log.warning("证据时间范围检查失败（这一份证据没核是不是这一轮的）", exc_info=True)


# Take a full-screen shot. **Must run in an interactive session** - the relay is
# a service running in session 0, which has no desktop at all, so shooting from
# here only ever yields a black image.
_SHOT_PS1 = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object Drawing.Bitmap $b.Width, $b.Height
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save('%OUT%', [Drawing.Imaging.ImageFormat]::Png)
"""


def _screenshot_to(out: Path) -> bool:
    """Take a screenshot in an interactive session and save it to `out`. True on success."""
    from ark_relay.features.preupdate import _PWSH7, _spawn_hidden_via_task  # noqa: PLC0415 - avoids an import cycle
    ps1 = Path(tempfile.gettempdir()) / f"ark-shot-{os.getpid()}.ps1"
    try:
        ps1.write_text(_SHOT_PS1.replace("%OUT%", str(out)), encoding="utf-8")
        _spawn_hidden_via_task(_PWSH7, ps1.parent,
                               ("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)))
        # The scheduled task starts asynchronously, so wait for the image to
        # land. Nothing after 10 seconds means the shot did not happen.
        for _ in range(20):
            if out.is_file() and out.stat().st_size > 10_000:
                return True
            time.sleep(0.5)
        return False
    except Exception:   # a failed screenshot must never take bookkeeping down
        log.warning("截图失败", exc_info=True)
        return False
    finally:
        ps1.unlink(missing_ok=True)


def _history_files(eng, rec: RunRecord) -> list:
    """This run's AUTO-MAS history files: <run_id>.log/.json (before v5.8), else the record's
    own log (v5.8's <date>/<record id>/0.log, rec.log_path) - the old path alone found
    nothing since 2026-10-28 (audit 2026-11-08 C-08, as B-01)."""
    out = []
    if eng.cfg.history_dir:
        for suffix in (".log", ".json"):
            f = Path(eng.cfg.history_dir) / (rec.run_id + suffix)
            if f.is_file():
                out.append(f)
    if not out and rec.log_path and Path(rec.log_path).is_file():
        out.append(Path(rec.log_path))
    return out


def _archive_okww_evidence(eng, rec: RunRecord) -> None:
    """When OK-WW fails, rescue a log slice and **a screenshot taken right then**.

    When upstream `ensure_main` cannot reach 「大世界 + 队伍」 (`Please start in game
    world and in team!`), the log cannot say what was in the way; only the screen
    at that moment can (a dialog, for one: docs/OKWW-STUCK-DIALOG.md), and OK-WW's
    own debug screenshots are switched off.

    The whole body is wrapped in try: rescuing evidence must never block
    bookkeeping.
    """
    dst = Path(eng.cfg.state_dir) / "evidence" / rec.run_id.replace("/", "_")
    try:
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        if log_path := _okww_log_file(eng.cfg.okww_dir):
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-800:]
                (dst / "ok-script.tail.log").write_text("\n".join(tail), encoding="utf-8")
                n += 1
            except OSError:
                log.warning("OK-WW 日志读不出来：%s", log_path, exc_info=True)
        for src_f in _history_files(eng, rec):
            shutil.copy2(src_f, dst / ("automas-" + src_f.name))
            n += 1
        # The screen. This is the reason this function exists.
        if _screenshot_to(dst / "screen.png"):
            n += 1
        else:
            log.error("❌ OK-WW 失败截图没拍成——下次还是只能猜屏幕上是什么")
        log.info("📦 OK-WW 失败证据已存档 %d 个文件 → %s", n, dst)
    except Exception:
        log.warning("存 OK-WW 失败证据时出错，跳过", exc_info=True)


def _archive_maaend_evidence(eng, rec: RunRecord) -> None:
    """Rescue this round's on_error screenshots and debug logs into the relay's own directory.

    Saved to state/evidence/<run_id>/. It must never block bookkeeping, so the
    whole body is wrapped in try.
    """
    try:
        if not eng.cfg.maaend_dir:
            log.error("❌ 存不了 MaaEnd 失败证据：maaend_dir 没解析出来"
                      "（ARK_MAAEND_DIR 未设，且 AUTO-MAS 里也没查到）。"
                      "MaaEnd 下次启动就会清空 debug 目录，证据即将丢失")
            return
        src = Path(eng.cfg.maaend_dir) / "debug"
        if not src.is_dir():
            log.error("❌ 存不了 MaaEnd 失败证据：%s 不是目录", src)
            return
        dst = Path(eng.cfg.state_dir) / "evidence" / rec.run_id.replace("/", "_")
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        oe = src / "on_error"
        if oe.is_dir():
            for png in sorted(oe.glob("*.png"))[:20]:
                shutil.copy2(png, dst / png.name)
                n += 1
        logs = sorted(src.glob("*.log"), key=lambda f: f.stat().st_mtime)
        for f in logs[-2:]:
            shutil.copy2(f, dst / f.name)
            n += 1
        # AUTO-MAS's own .log/.json for that round **always lines up with this
        # failure**, whereas MaaEnd's debug log may not - see the time-range check
        # below. The .json names the failing task.
        for src_f in _history_files(eng, rec):
            shutil.copy2(src_f, dst / ("automas-" + src_f.name))
            n += 1
        log.info("📦 MaaEnd 失败证据已存档 %d 个文件 → %s", n, dst)
        eng._warn_if_evidence_stale(rec, dst)
    except Exception:
        log.exception("MaaEnd 证据存档失败（不影响记账）")


def _mark_downtime(eng, rec: RunRecord) -> None:
    """A failure that could not get into the game: register the game for the update
    and re-run after the queue (gameupdate.mark_pending -> run_deferred), and mark a
    failure inside an official maintenance window on the record and its ledger line.
    """
    try:
        from ark_relay.features import gameupdate  # noqa: PLC0415
        from ark_relay.features import maintenance  # noqa: PLC0415
        raw = rec.raw
        # Never entering the game at all is the signal that the client needs an update.
        if rec.script == "MaaEnd" and raw.get("maaend_unreachable"):
            gameupdate.mark_pending(eng.cfg.state_dir, "终末地", "今天 MaaEnd 进不了游戏（客户端待更新）")
        if rec.script == "OK-WW" and raw.get("okww_unreachable"):
            gameupdate.mark_pending(eng.cfg.state_dir, "鸣潮", "今天 OK-WW 等不到游戏窗口（客户端待更新）")
        # A failure that ran into official downtime: ⏸ in the daily report, the
        # 「进不了游戏」 alarm instead of a failure, no make-up, and a re-run once
        # the servers are back.
        if why := gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started):
            raw["maintenance"] = why
            _mark_raw_on_ledger(eng, rec, "maintenance", why)
            game = next((g for g, s in maintenance.SCRIPT_OF.items() if s == rec.script), "")
            if game:
                gameupdate.mark_pending(eng.cfg.state_dir, game, f"今天 {rec.script} 撞上官方维护（{why}）")
    except Exception:  # not knowing leaves it an ordinary failure
        log.warning("没查成 %s 是不是撞上维护 / 进不了游戏，按普通失败处理", rec.run_id, exc_info=True)


def _weekly_gates(eng, rec: RunRecord) -> None:
    """The weekly gates (weekly boss, weekly garden): which one this run finished, and one line about it when it did.
    """
    # Only a run that genuinely fills the weekly quota counts.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
    steps = rec.raw.get("okww_steps") or []
    # Weekly boss: the task name is translated as 「传送并刷取4C声骸」 while the task
    # itself displays 「刷4C(大世界/副本)」; both are accepted. The criterion matches
    # the weekly garden - only actually finishing that step counts.
    if any(s.startswith("周本") and "已完成" in s for s in steps):
        if msg := eng._weeklyboss.on_success(rec.finished, since=rec.started):
            eng.notifier.send(texts.WEEKLY, msg)
    if any("周常乐园" in s and "已完成" in s for s in steps) and eng._garden:
        if msg := eng._garden.on_success(rec.finished):
            # The weekly gates have the same shape.
            # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
            eng.notifier.send(texts.WEEKLY, msg)


def _annihilation_checked_full(eng, rec: RunRecord) -> "dict | None":
    """{'current', 'total', 'store_ts', 'read_at'} when an Annihilation pass that MAA skipped
    because the terminal listed no annihilation (collector_maa annihilation_no_entry) is
    backed by the game server's own figure: Skland's campaign reward full, stored in the
    pass's own game-week (Monday 04:00 reset). None otherwise - Skland unreachable, token
    missing or expired, a reading from before the reset, or not full - and the day's
    unverified-annihilation alarm goes out as before. One read, no retry. Reads only; the
    caller marks.
    """
    if not _unbacked_skip(rec):
        return None
    got = _read_skland_annihilation(eng)
    return _skland_backs(got, rec) if got else None


def _unbacked_skip(rec: RunRecord) -> bool:
    """An Annihilation pass MAA skipped because the terminal listed no annihilation
    (collector_maa annihilation_no_entry), with no progress line and no Skland reading on it yet."""
    raw = rec.raw
    return bool(rec.script == "MAA" and raw.get("annihilation") and raw.get("annihilation_no_entry")
                and not raw.get("annihilation_progress") and not raw.get("annihilation_official"))


def _read_skland_annihilation(eng) -> "dict | None":
    """Skland's {'current', 'total', 'store_ts', 'read_at'} for the account, or None when there
    is no token or the read fails. One read, no retry; never raises."""
    token = getattr(eng.cfg, "skland_token", "")
    if not token:
        log.info("剿灭：MAA 说终端里没有剿灭入口、跳过了；没有森空岛凭证，核对不了，照旧按没证据算")
        return None
    from ark_relay.core import skland  # noqa: PLC0415
    now = datetime.now(tz=SERVER_TZ)
    try:
        got = skland.arknights_annihilation(skland.login(token))
    except Exception as exc:  # noqa: BLE001 - any doubt keeps the alarm; never raises
        log.warning("剿灭：MAA 说终端里没有剿灭入口、跳过了；去森空岛核对没核成（%s），照旧按没证据算",
                    type(exc).__name__)
        return None
    return {**got, "read_at": now.strftime("%Y-%m-%d %H:%M:%S")}


def _skland_backs(got: dict, rec: RunRecord) -> "dict | None":
    """`got` when that Skland reading is full and was stored in `rec`'s own game-week
    (Monday 04:00 reset); None otherwise."""
    from ark_relay.features.annihilation import week_key  # noqa: PLC0415
    stored = datetime.fromtimestamp(got["store_ts"], tz=SERVER_TZ) if got["store_ts"] else None
    # A reading stored in an earlier game-week is last week's figure, 1800/1800 or not.
    if stored is None or week_key(stored) != week_key(rec.started):
        log.info("剿灭：森空岛读到 %s/%s，但那是 %s 存的、不是这一周的数，不算；照旧按没证据算",
                 got["current"], got["total"], stored.strftime("%m-%d %H:%M") if stored else "不知道什么时候")
        return None
    if got["total"] <= 0 or got["current"] < got["total"]:
        log.info("剿灭：MAA 跳过了，可森空岛读到本周只有 %s/%s，没打满；照旧按没证据算",
                 got["current"], got["total"])
        return None
    return got


def _day_unbacked_skips(eng, rec: RunRecord) -> list:
    """`rec` and the other records of its day (the ledger) that are a skipped Annihilation pass
    nothing backs yet - the rows core.day_unverified_items lists as annihilation. Runs that failed, were
    stopped by hand or were short of sanity are left out, as that list leaves them out."""
    out = [rec] if rec.ok and _unbacked_skip(rec) else []
    try:
        rows = eng.state.read_ledger(run_day(rec))
    except Exception:  # noqa: BLE001 - an unreadable ledger only means nothing more to check
        rows = []
    for e in rows:
        raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
        if (e.get("run_id") == rec.run_id or not e.get("ok") or core.manual_stop(e)
                or raw.get("maa_sanity_short")):
            continue
        try:
            started = datetime.fromisoformat(e["started"])
            row = RunRecord(run_id=e["run_id"], script=e.get("script", ""), user=e.get("user", ""),
                            started=started, finished=started, ok=True, raw=dict(raw))
        except (KeyError, TypeError, ValueError):
            continue
        if _unbacked_skip(row):
            out.append(row)
    return out


def _annihilation_checked_day(eng, rec: RunRecord) -> None:
    """When an MAA record lands, back with Skland every skipped Annihilation pass of its day
    that nothing backs yet - its own, and an earlier one whose read at its own landing missed
    (Skland down, or the figure not stored yet). One read for all of them, and only when there
    is one; each is judged against its own game-week and marked on its own ledger line.
    """
    if rec.script != "MAA":
        return
    todo = _day_unbacked_skips(eng, rec)
    if not todo:
        return
    got = _read_skland_annihilation(eng)
    if not got:
        return
    for row in todo:
        if backed := _skland_backs(got, row):
            _say_annihilation_checked(eng, row, backed)


def _annihilation_verdicts(eng, rec: RunRecord) -> None:
    """The two annihilation checks a normally-exited record gets before its day's unverified
    items are pushed, on the scheduled and the hand-started path alike: Skland backing a
    skipped pass, and a pass that fought nothing for lack of sanity."""
    _annihilation_checked_day(eng, rec)
    if short := _annihilation_sanity_short(eng, rec):
        _say_annihilation_short(eng, rec, short)


def _say_annihilation_checked(eng, rec: RunRecord, got: dict) -> None:
    """Put the Skland reading on the record and on its ledger line, so the day's unverified
    items (core.day_unverified_items) count annihilation as backed for every record of the
    day - the second 11-16 alarm came from the routine run re-reading the ledger - and the
    daily report says where the figure came from."""
    rec.raw["annihilation_official"] = got
    _mark_raw_on_ledger(eng, rec, "annihilation_official", got)
    log.info("🟢 剿灭：MAA 在终端待办里没找到剿灭入口、跳过了；森空岛官方数据 %s 读到本周 %s/%s"
             "（游戏服务器 %s 存的），算本周已打满",
             got["read_at"][11:], got["current"], got["total"],
             datetime.fromtimestamp(got["store_ts"], tz=SERVER_TZ).strftime("%m-%d %H:%M:%S"))


def _annihilation_sanity_short(eng, rec: RunRecord) -> "dict | None":
    """{'have', 'cost'} when an Annihilation pass AUTO-MAS booked as done fought nothing for
    lack of sanity; None otherwise. Reads only; _say_annihilation_short marks and pushes.
    """
    raw = rec.raw
    if (rec.script == "MAA" and raw.get("annihilation") and not raw.get("annihilation_progress")
            and not raw.get("maa_sanity_short") and not raw.get("annihilation_official")):
        until = rec.finished + timedelta(minutes=5) if rec.duration_known else None
        return outcome.maa_sanity_short(_maa_app_log(eng.cfg.maa_dir, rec.started, until) or "")
    return None


def _say_annihilation_short(eng, rec: RunRecord, short: dict) -> None:
    """Mark the pass the way the failure path marks a run short of sanity (raw maa_sanity_short,
    the ledger line too), so the day's unverified items leave it out (core.day_unverified_items)
    and the daily report says why; and say it in the group the way the failure path does, every
    such run, with the two numbers and that AUTO-MAS booked it done."""
    rec.raw["maa_sanity_short"] = short
    _mark_raw_on_ledger(eng, rec, "maa_sanity_short", short)
    errs = _push_now(eng, run_day(rec), "理智", rec.run_id, texts.MAA_SANITY_SHORT,
                     texts.maa_sanity_short_body(short["have"], short["cost"],
                                                 rec.started.astimezone(SERVER_TZ).strftime("%H:%M"), booked_ok=True))
    log.info("🟡 MAA 剿灭理智不够（%s/%s），没打，AUTO-MAS 记成成功，%s", short["have"], short["cost"],
             "没推出去，下一轮再推" if errs else "已报群")


def _handle_success(eng, rec: RunRecord, key: tuple) -> None:
    """Everything to do after AUTO-MAS reports that this round exited normally.

    Its own step because the success and failure paths share not one line: this
    one handles the self-heal notice, the weekly gates and the outcome check,
    while the failure one handles mid-round restarts, update days and holding.
    """
    # A held MaaEnd update restart that started after this round of the same
    # shift (records can land in either order). If this round turns out to have got the
    # work done (the outcome check below), the restart is let go; until then it
    # stays held, and an undone round sends it down the usual path.
    held = eng._pending.get(key)
    after_done = (held is not None and bool((held.raw or {}).get("maaend_update_restart"))
                  and rec.started < held.started and _same_shift(eng, held, rec))
    if not after_done and _same_job(held, rec):
        _retry_healed(eng, rec, key)
    elif held is not None and not after_done:
        log.info("↪️ %s %s（%s）跑成了，但压着的 %s 是%s失败，不算它自己好了，照旧等着报",
                 rec.script, rec.run_id, core.maa_mode(_job(rec)), held.run_id, core.maa_mode(_job(held)))
    _weekly_gates(eng, rec)
    _annihilation_verdicts(eng, rec)
    # AUTO-MAS saying 「这个脚本正常退出了」 does not mean it got the work done.
    # So check against the evidence before returning, and anything not done has
    # to be said out loud.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
    _push_unverified(eng, rec)
    msg = eng._verify_outcome(rec)
    if rec.script in ("MAA", "MaaEnd"):
        # A make-up booked OK (makeup.on_record) is tied to the failures it made up for
        # only now, on this check's word.
        try:
            from ark_relay.features import makeup  # noqa: PLC0415
            makeup.after_outcome(eng, rec, msg)
        except Exception:
            log.exception("补跑结果记账出错")
    if msg:
        if after_done:
            _retry_healed(eng, rec, key)
        # Onto the ledger too, or the daily report would open with 全绿 while this
        # very message says otherwise.
        day = run_day(rec)
        if not eng.state.mark_incomplete(day, rec.run_id, msg):
            log.warning("没能把「没干完」写回 %s 的账本，日报会少这一条", rec.run_id)
        # Bundle first, so the alarm carries the link (the round is over: this
        # alarm is the final word on it, and the daily row gets the link too).
        page = _ship_evidence(eng, rec)
        full = msg + (f"\n\n证据包：{page}" if page else "")
        if rec.script in ("MAA", "MaaEnd"):
            title, errs = _push_undone(eng, rec, msg, page)
        else:
            title = texts.ROUND_INCOMPLETE
            errs = eng.notifier.send(title, full, alert=True)
        ew = _errwatch()
        log.warning("⚠️ %s %s 有项目没干成：\n%s", rec.script, rec.run_id, msg,
                    extra=ew.alarm(title, full) if errs else ew.group_pushed(title, errs, eng.notifier))
        return
    if after_done:
        eng._pending.pop(key, None)
        eng._persist_pending()
        _drop_update_after_done(eng, held, rec.run_id)
    # Booked a success and every outcome check passed: an ERROR line in the game's own
    # log that nobody has looked at still goes to the group (gamelog_errors.py).
    from ark_relay.features import outcome as gamelog_errors  # noqa: PLC0415
    try:
        gamelog_errors.check_round(eng, rec)
    except Exception:  # the booking goes on; the group hears the check broke
        log.warning("%s %s 日志里的报错没查成", rec.script, rec.run_id, exc_info=True)
    log.info("✅ %s %s（%d 分钟）静默记账",
             rec.script, rec.run_id, rec.duration_min)
    return


def _retry_healed(eng, rec: RunRecord, key: tuple) -> None:
    """A later success means AUTO-MAS got past the held failure on its own. Report
    it anyway - once for the whole event, not once per failed attempt."""
    if (bad := eng._pending.pop(key, None)) is not None:
        eng._recovered[key] = bad
        eng._persist_pending()
        log.info("↩️ %s 重试后成功，改为自愈通知", rec.script)


def _drop_update_after_done(eng, rec: RunRecord, done: str) -> None:
    """An update restart whose shift's round (`done`) was already done: no make-up
    and no push - that round got its work done, so nothing is left broken. The
    daily report carries it.

    The ledger line stays; the mark on it is what makes the daily report book it
    as the update (core.episode_kinds: a ↪️ row naming the new build) instead of a
    failure, since no success follows it there. Not pushed: the user's words for
    this are in relay/USER-SWITCHES.txt (this function's entry).
    """
    _mark_raw_on_ledger(eng, rec, "maaend_update_after_done", done)
    log.info("↪️ MaaEnd %s 前面那趟已经做完（%s），这趟是装新版 %s 重启，只进日报（%s）",
             rec.run_id, done, rec.raw.get("maaend_update_restart"), texts.MAAEND_UPDATE_AFTER_DONE)


def _update_restart_done(eng, rec: RunRecord) -> bool:
    """At the push: a held MaaEnd update restart whose shift's round is done by now
    is let go (_drop_update_after_done) instead of alarmed on. True when let go.

    _handle lets it go when that round is already booked, and _handle_success when
    the round lands after it; this is the last door before any alarm, so a done
    shift can never end in an alarm about the restart, whichever order and tick the
    two records came in."""
    if rec.script != "MaaEnd" or not (rec.raw or {}).get("maaend_update_restart"):
        return False
    unresolved = _sys.modules[__name__]
    try:
        done = unresolved.done_in_shift(eng, rec)
    except Exception:  # not knowing keeps it on its usual path
        log.warning("查不了这一班有没有做完的那趟，%s 照旧处理", rec.run_id, exc_info=True)
        return False
    if not done:
        return False
    eng._pending.pop((rec.script, rec.user), None)
    eng._persist_pending()
    eng.log_tails.pop(rec.run_id, None)
    _drop_update_after_done(eng, rec, done)
    return True


# Attempts of one AUTO-MAS round start minutes apart at most (its retries follow at
# once); a held record further away than this belongs to another round.
SAME_ROUND = timedelta(minutes=30)


def _keeps_rejected(held, rec: RunRecord) -> bool:
    """Whether the held record of the same key stays held instead of `rec`: it says
    MAA refused the config (collector_maa) and `rec`, an attempt of the same round,
    does not. AUTO-MAS lands a round's records together in no fixed order, and one
    without its log (json only) carries no reason; held last, the alarm would lose the refusal and wait for a make-up tick."""
    return (held is not None and held is not rec
            and bool((held.raw or {}).get("maa_config_rejected"))
            and not (rec.raw or {}).get("maa_config_rejected")
            and abs(rec.started - held.started) <= SAME_ROUND)


def _hold_for_retry(eng, rec: RunRecord, key: tuple) -> None:
    """Wrapping up a genuine failure: queue it for pushing, persist it, rescue the evidence.

    Its own step because it is the only section of the failure path that stops
    judging and just cleans up, and because every step of it has to be finished
    before the next thing can go wrong - the order must not be changed.
    """
    _mark_downtime(eng, rec)   # before the hold is persisted: the mark survives a restart
    # Hold it. Only alert once the script has stopped retrying entirely.
    if not _keeps_rejected(eng._pending.get(key), rec):
        eng._pending[key] = rec   # else the held refusal stays: the alarm is about it
    eng._persist_pending()   # queued to disk before anything else can go wrong
    # Move the evidence away the moment a failure is recorded: the instant
    # MaaEnd next starts it clears the previous round's screenshots and logs
    # itself, and by the time a person looks there is nothing left.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
    if rec.script == "MaaEnd":
        eng._archive_maaend_evidence(rec)
    elif rec.script == "OK-WW":
        _archive_okww_evidence(eng, rec)
    if _ship_evidence(eng, rec):
        eng._persist_pending()   # again, now with the link the final alarm carries
    if rejected := (eng._pending[key].raw or {}).get("maa_config_rejected"):
        # Collapsed with the round's other attempts under one key and pushed by this
        # tick's _flush_pending (makeup.refuse_rejected): nothing to wait for.
        log.info("🚫 MAA 不接受这份配置（%s），不等重试、不补跑，这一轮就进群", rejected)
        return
    log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)


def _ship_evidence(eng, rec: RunRecord) -> str:
    """Build the upstream-format bundle and push it off the machine; log the link.

    Returns the link ("" when nothing went up) and leaves it on rec.raw and on
    the day's ledger line: the final alarm and the daily report carry it.

    The bundle is the same files the project's own export button would produce
    (evidence.py), plus this round's AUTO-MAS log and record, readable with the
    machine off. Wrapped in try: shipping
    evidence must never block bookkeeping.
    """
    try:
        from ark_relay.features import evidence  # noqa: PLC0415
        extra = list(_history_files(eng, rec))
        shot = None
        if rec.script == "OK-WW":
            first = Path(eng.cfg.state_dir) / "evidence" / rec.run_id.replace("/", "_") / "screen.png"
            if first.is_file():
                extra.append(first)
                shot = lambda: None  # noqa: E731
        # One run's window, widened a little on both ends (evidence.WINDOW_SLACK):
        # a bundle is always cut by time, never the whole debug folder.
        window = evidence.run_window(rec.started, rec.finished if rec.duration_known else None)
        if rec.script == "MaaEnd":
            # The desktop at each task's end (task_shots.py), next to MaaEnd's own
            # on_error / vision pictures that bundle_maaend takes.
            from ark_relay.features import task_shots  # noqa: PLC0415
            extra += task_shots.in_window(eng.cfg.state_dir, window)
        # relay.log up to now: what the relay did about the run comes after it.
        res = evidence.save_and_upload(eng.cfg, rec.script, rec.run_id, extra, window=window,
                                       relay_until=time.time(), screenshot=shot)
        if res.get("page"):
            # One archive goes up (evidence.pack_one), so "uploaded" holds one link;
            # the count that means something is the files inside it.
            n = len(res.get("files") or [])
            log.info("🗂️ %s 证据包已上传（%d 个文件）→ %s", rec.run_id, n, res["page"])
            rec.raw["evidence_page"] = res["page"]     # the failure alarm and the daily row carry it
            day = run_day(rec)
            if not eng.state.mark_evidence(day, rec.run_id, res["page"]):
                log.warning("没能把证据链接写回 %s 的账本，日报那一行会没有链接", rec.run_id)
            eng.notifier.send(texts.EVIDENCE_SAVED,
                              texts.evidence_saved_body(rec.script, rec.started.astimezone(SERVER_TZ).strftime("%m-%d %H:%M"),
                                                        n, res["page"]))
        else:
            log.warning("🗂️ %s 证据包没传上去：%s", rec.run_id, "；".join(res.get("errors") or ["没有文件"]))
        return res.get("page") or ""
    except Exception:
        log.exception("证据外送出错（不影响记账）")
        return ""


def _hand_started(eng, rec: RunRecord) -> str:
    """The AUTO-MAS task id when a person started this run at AUTO-MAS itself, else ''.

    Never raises: not knowing keeps the run on the normal path (trigger.py).
    """
    try:
        from ark_relay.features import trigger  # noqa: PLC0415
        task = trigger.hand_started(eng.cfg.automas_dir, eng.cfg.state_dir, rec.started)
    except Exception:
        log.exception("判断是不是有人手动开的出错，按定时的处理")
        return ""
    return task.id if task else ""


def _hand_started_alarm(eng, rec: RunRecord, key: tuple) -> "tuple[str, str, str, str] | None":
    """(day, alarm kind, title, body) of the alarm _handle pushes now about a run a
    person started from AUTO-MAS's own screen (trigger.py), or None when nothing is
    to be pushed now. Alarmed like any other run, with a line saying whose run it
    was; no make-up is run for it (makeup.marker.eligible).
    """
    day = run_day(rec)
    kind = "手动"          # unresolved.send keys it with rec.run_id
    if rec.ok:
        held = eng._pending.get(key)
        if held is not None and (held.raw or {}).get("hand_started") == rec.raw.get("hand_started"):
            # An earlier attempt of this same task: AUTO-MAS's own retry got past it.
            _retry_healed(eng, rec, key)
        elif held is not None and held.started < rec.started:
            eng._pending.pop(key, None)
            eng._persist_pending()
            hhmm = rec.started.astimezone(SERVER_TZ).strftime("%H:%M")
            title, body = _failure_alarm(eng, held, texts.hand_fixed_note(hhmm), held=True)
            errs = _push_now(eng, run_day(held), "手动跑成前", held.run_id, title, body)
            log.info("🖐 %s 之前压着的失败 %s，后来有人手动跑成了，%s", rec.script, held.run_id,
                     "没推出去，下一轮再推" if errs else "照报进群")
        _weekly_gates(eng, rec)
        _annihilation_verdicts(eng, rec)
        _push_unverified(eng, rec)
        if msg := eng._verify_outcome(rec):
            eng.state.mark_incomplete(day, rec.run_id, msg)
            page = _ship_evidence(eng, rec)
            return day, kind, texts.ROUND_INCOMPLETE, (texts.HAND_STARTED_NOTE + "\n" + msg
                                                       + (f"\n\n证据包：{page}" if page else ""))
        log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的，跑完了，静默记账", rec.script, rec.run_id)
        return None
    if _hold_hand_started(eng, rec, key):
        return None
    title, body = _failure_alarm(eng, rec, texts.HAND_STARTED_NOTE)
    return day, kind, title, body


def _hold_hand_started(eng, rec: RunRecord, key: tuple) -> bool:
    """Hold a failed attempt of a hand-started task until the task's later attempts
    decide (_hand_started_alarm). False when a failure from somewhere else is held
    for the same script (a shift's, or another task's): this one is then pushed at
    once as before, and that one stays on its own path.

    Replacing follows _hold_restart and _hold_for_retry: a later failure of the same
    task replaces the held one, said in one INFO line, while a restart AUTO-MAS
    recorded (transitional) or an earlier attempt landing late does not. Evidence is
    archived and shipped for the record kept, as _hold_for_retry does; no
    _mark_downtime, which is for a scheduled run (_failure_alarm)."""
    held = eng._pending.get(key)
    task = rec.raw.get("hand_started")
    if held is not None and (held.raw or {}).get("hand_started") != task:
        return False
    keep_held = held is not None and (
        (rec.transitional and not held.transitional)
        or rec.started < held.started
        or _keeps_rejected(held, rec))
    if keep_held:
        log.info("🖐 %s %s 是同一个手动任务里的另一次尝试，留着压着的 %s", rec.script, rec.run_id, held.run_id)
        return True
    eng._pending[key] = rec
    eng._persist_pending()   # queued to disk before anything else can go wrong
    if held is not None:
        log.info("🖐 %s 压着的 %s 换成同一个手动任务后面那次失败 %s", rec.script, held.run_id, rec.run_id)
    if rec.script == "MaaEnd":
        eng._archive_maaend_evidence(rec)
    elif rec.script == "OK-WW":
        _archive_okww_evidence(eng, rec)
    if _ship_evidence(eng, rec):
        eng._persist_pending()   # again, now with the link the final alarm carries
    log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的（任务 %s），AUTO-MAS 接着重试；先压着，看同一任务后面那次",
             rec.script, rec.run_id, task)
    return True


def _release_hand_started(eng, rec: RunRecord, key: tuple) -> None:
    """Before a record that is not a person's run is booked at `key`: a hand-started
    task's last failure still held there (_hold_hand_started; its flush waited while
    the script was running or queued, or while the robot was down) is pushed now.

    That task is over - AUTO-MAS lands all of a task's records together - and the
    paths below would otherwise replace it (_hold_for_retry, the update-restart
    hold) or move it to the self-heal path (_handle_success -> _retry_healed) on the
    strength of a run that is not its task: its alarm would never go out. The other
    way round, a person's record landing on a held shift failure, is
    _hold_hand_started's False."""
    held = eng._pending.get(key)
    if held is not None and held is not rec and (held.raw or {}).get("hand_started"):
        title, body = _failure_alarm(eng, held, texts.HAND_STARTED_NOTE, held=True)
        # Pushed (or queued to disk by _push_now when the robot is down) before it
        # leaves the queue: a crash in between must not lose it.
        errs = _push_now(eng, run_day(held), "手动", held.run_id, title, body)
        eng._pending.pop(key, None)
        eng._persist_pending()
        eng.log_tails.pop(held.run_id, None)
        log.info("🖐 %s 压着的 %s 是有人在 AUTO-MAS 上手动开的（任务 %s），%s 这趟不是它的，先把它报了：%s",
                 rec.script, held.run_id, held.raw.get("hand_started"), rec.run_id,
                 "没推出去，下一轮再推" if errs else "已报群")


def _failure_alarm(eng, rec: RunRecord, note: str, held: bool = False) -> tuple[str, str]:
    """(title, body) of the final-failure alarm about `rec` when it is pushed now
    rather than held (no make-up is run for it): the usual failure text with `note`
    on top and the evidence link. Rescues and ships the evidence first.

No _mark_downtime here: the mark (⏸, mark_pending, the relay's re-run) is for
    a scheduled run being held. A hand-started failure is a person's run, and an
    update-day MAA failure is pushed saying the evening shift runs it again; a held
    `rec` got its mark when it was held.
    """
    if not held and rec.script == "MaaEnd":
        eng._archive_maaend_evidence(rec)
    elif not held and rec.script == "OK-WW":
        _archive_okww_evidence(eng, rec)
    ev = _evidence_note(eng, rec)      # ships the bundle first when the record has none
    title, body = core.format_failure(rec, _diagnosis(eng, rec))
    body = note + "\n" + body + (f"\n{ev}" if ev else "")
    # The 「像没进游戏」 shape with no official notice behind it: said here as
    # pushes._push_unresolved says it on the held final alarm, since
    # _confirm_unreachable logs it at INFO only (review of s7 #5).
    raw = rec.raw or {}
    if raw.get("maaend_unreachable_shape") and not raw.get("maaend_unreachable"):
        body += "\n" + (texts.UNREACHABLE_UNREAD_NOTE if raw.get("maaend_unreachable_unread")
                        else texts.UNREACHABLE_SHAPE_NOTE)
    return title, body


@_one_pass
def _handle(eng, rec: RunRecord) -> None:
    """Book one run record, then let the machine checks read what happened
    (machinecheck.py, event 「run」).

    The checks run only after the record was handled to the end: one whose
    handling broke off is replayed on the next tick and judged then."""
    watch = _RunWatch(eng)
    with watch:
        _book(eng, rec)
    _judge_run(eng, rec, watch)
    # A check's FAIL kept while a run was held for its retry: this booking may have
    # ended the hold (the retry got through) or sent the alarm that carries it.
    _settle_held(eng)


def _book_own_run(eng, rec: RunRecord) -> None:
    """A make-up (makeup.py) or an activity top-up (activity.py) record: into its marker."""
    if rec.script in ("MAA", "MaaEnd"):
        try:
            from ark_relay.features import makeup  # noqa: PLC0415
            makeup.on_record(eng, rec)
        except Exception:
            log.exception("补跑结果记账出错")
    elif rec.script == "OK-WW":
        try:
            from ark_relay.features import activity  # noqa: PLC0415
            activity.on_record(eng, rec)
        except Exception:
            log.exception("鸣潮活跃晚班补记账出错")


def _book(eng, rec: RunRecord) -> None:
    day = run_day(rec)
    if stop := _estop_overlap(eng, rec):
        rec.raw["manual_stop"] = stop
    elif hand := _hand_started(eng, rec):
        rec.raw["hand_started"] = hand
    _mark_update_restart(eng, rec)
    _confirm_unreachable(eng, rec)
    if rec.script == "MaaEnd":
        _mark_task_shots(eng, rec)
        _mark_task_trails(eng, rec)
    _append_ledger_once(eng, rec)
    key = (rec.script, rec.user)
    if rec.script == "MaaEnd":
        _restore_after_maaend(eng)
    # Is this a run the relay dispatched itself (the day's make-up, the evening activity
    # top-up)? Booked before anything below can return early (a red-button stop returns
    # right away).
    _book_own_run(eng, rec)
    if rec.script == "MaaEnd":
        # Target mode found every ticked weapon's essence owned: switch to filler mode
        # at the next safe moment (essence.step, an engine tick step).
        try:
            from ark_relay.features import essence  # noqa: PLC0415
            essence.on_record(eng, rec, day)
        except Exception:
            log.exception("基质刷取切刷垫子记账出错")

    if rec.raw.get("manual_stop"):
        # Cut short by the red button: not a self-heal, not a success (no weekly
        # gates, no outcome check), not a new failure to hold. A failure held from
        # before the stop, and a failure AUTO-MAS wrote for the stopped run itself,
        # both go to the group, saying the run was stopped by 停一切.
        stop = rec.raw["manual_stop"]
        if (held := eng._pending.pop(key, None)) is not None:
            eng._persist_pending()
            _push_before_stop(eng, held, stop)
        if not rec.ok:
            title, body = _failure_alarm(eng, rec, f"这一趟是停一切停掉的（{stop}），AUTO-MAS 把它记成了失败，照报。")
            _push_now(eng, day, "停一切", rec.run_id, title, body)
        log.info("⏹ %s %s 这趟是停一切停掉的（%s），记手动停止，不算自愈也不算成功；之前的失败已报群",
                 rec.script, rec.run_id, stop)
        return
    if rec.raw.get("hand_started"):
        # A run a person started at AUTO-MAS itself (trigger.py): no make-up for a
        # person's own run. An undone round, or a failure while another failure is
        # held, is pushed right here; a failed attempt is held until its task's later
        # attempts decide (_hold_hand_started, pushed by _flush_pending).
        if alarm := _hand_started_alarm(eng, rec, key):
            _, kind, title, body = alarm
            errs = _push_now(eng, day, kind, rec.run_id, title, body)
            log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的（任务 %s）：%s，%s", rec.script, rec.run_id,
                     rec.raw.get("hand_started"), title, "没推出去，下一轮再推" if errs else "已报群")
        return
    _release_hand_started(eng, rec, key)

    if rec.ok:
        _handle_success(eng, rec, key)
        return

    # AUTO-MAS records a restart (「游戏更新成功，即将重启任务」 sits in
    # _OKWW_BUILTIN_FATAL alongside real faults) as a failed attempt; the next two
    # branches handle MaaEnd's update restarts and every other restart.
    if rec.raw.get("maaend_update_restart"):
        # The shift's round already got everything done: this attempt is MaaEnd
        # restarting into its new build - not held, no make-up, not pushed; its
        # ledger line stays and the daily report says it (_drop_update_after_done).
        unresolved = _sys.modules[__name__]
        try:
            done = unresolved.done_in_shift(eng, rec)
        except Exception:  # not knowing keeps it held, as before
            log.warning("查不了这一班有没有做完的那趟，%s 照旧压着", rec.run_id, exc_info=True)
            done = ""
        if done:
            _drop_update_after_done(eng, rec, done)
            return
        if later := _later_success(eng, rec):
            # Its retry's record landed first: healed already, as _hold_restart does.
            # The daily report books the pair as the update (core.episode_kinds).
            log.info("↪️ MaaEnd %s 是装新版 %s 后的自重启，后面那次 %s 已经成功：自己好了", rec.run_id,
                     rec.raw["maaend_update_restart"], later)
            _self_heal_red(eng, f"{rec.script} {rec.run_id} 装新版 {rec.raw['maaend_update_restart']} 后自重启",
                           f"后面 {later} 成功")
            return
        _mark_downtime(eng, rec)   # held like _hold_for_retry: marked before it is persisted
        if key not in eng._pending or (eng._pending[key].raw or {}).get("maaend_update_restart"):
            eng._pending[key] = rec
        eng._persist_pending()
        # Rescue and ship the evidence now, as _hold_for_retry does: MaaEnd clears
        # its own debug folder on its next start, and this record can still end
        # in the final alarm.
        eng._archive_maaend_evidence(rec)
        if _ship_evidence(eng, rec):
            eng._persist_pending()
        log.info("↪️ MaaEnd %s 是装新版 %s 后的自重启，先压着看后面的重试",
                 rec.run_id, rec.raw["maaend_update_restart"])
        return
    if rec.transitional:
        # An attempt AUTO-MAS recorded as a restart (collector._TRANSITIONAL: a game
        # update, an emulator that did not start, a stub with no log) and retried at
        # once. Nothing is pushed at this moment: the attempts after it decide. It is
        # held like a failure - unless an earlier failure of the same script is held
        # already, which stays (it is the one a later success heals or the final
        # alarm names). A later success moves the held record to the self-heal path
        # (_retry_healed): daily report only (what recovered by itself). A later
        # failure replaces it and is alarmed on as usual; no later attempt at all,
        # and the final alarm names this one (_flush_pending).
        _hold_restart(eng, rec, key)
        return

    if rec.script == "MAA" and not rec.ok:
        # MAA stopping at once for lack of sanity (「理智 17，需要 25」) fought
        # nothing and spent nothing; say that and stop there.
        until = rec.finished + timedelta(minutes=5) if rec.duration_known else None
        app_log = _maa_app_log(eng.cfg.maa_dir, rec.started, until) or ""
        short = outcome.maa_sanity_short(app_log)
        if short:
            rec.raw["maa_sanity_short"] = short
            # The ledger line was written above, before this was known: put it
            # there too, or the daily report (core.episode_kinds 「nosanity」) reads
            # the run as a plain failure.
            _mark_raw_on_ledger(eng, rec, "maa_sanity_short", short)
            # AUTO-MAS booked it as failed: the group hears of it, every such run, with
            # the two numbers. Not held and no make-up: a second run would meet the
            # same sanity.
            errs = _push_now(eng, day, "理智", rec.run_id, texts.MAA_SANITY_SHORT,
                             texts.maa_sanity_short_body(short["have"], short["cost"],
                                                         rec.started.astimezone(SERVER_TZ).strftime("%H:%M")))
            log.info("🟡 MAA 理智不够（%s/%s），没打，%s", short["have"], short["cost"],
                     "没推出去，下一轮再推" if errs else "已报群")
            return
        if outcome.maa_annihilation_no_proxy(app_log):
            # The annihilation map's auto-deploy is locked: no retry or make-up can run
            # it. Held and alarmed on as usual (only another Annihilation success heals
            # it, _same_job); the alarm and the daily row say why (texts.ANNIHILATION_NO_PROXY).
            rec.raw["annihilation_no_proxy"] = True
            _mark_raw_on_ledger(eng, rec, "annihilation_no_proxy", True)
    if rec.script == "MAA" and not rec.ok and eng._maintenance_today("明日方舟"):
        # A MAA failure on a day with a registered version update is still a
        # failure: pushed now, saying it is the update day, and not held for a
        # make-up (the evening shift runs it again anyway).
        rec.raw["maintenance_day"] = True
        _mark_raw_on_ledger(eng, rec, "maintenance_day", True)
        title, body = _failure_alarm(eng, rec, texts.UPDATE_DAY_NOTE)
        errs = _push_now(eng, day, "更新日", rec.run_id, title, body)
        log.info("❌ 更新日 MAA %s 没跑成，%s", rec.run_id, "没推出去，下一轮再推" if errs else "已报群")
        return
    # Every other failure - a MaaEnd round that failed on 自动采集 / 应急理智加强剂
    # alone included - is held, made up and alarmed on.
    _hold_for_retry(eng, rec, key)


def _job(rec: RunRecord) -> dict:
    return {"script": rec.script, "raw": rec.raw}


def _same_job(held: "RunRecord | None", rec: RunRecord) -> bool:
    """Whether `rec` succeeding can heal `held`: the same MAA job (core.maa_mode) -
    AUTO-MAS runs Annihilation and Routine as one script, one after the other
    (2026-10-26: a Routine success had healed three Annihilation failures)."""
    return held is None or core.maa_mode(_job(held)) == core.maa_mode(_job(rec))


def _hold_restart(eng, rec: RunRecord, key: tuple) -> None:
    """Hold an attempt AUTO-MAS recorded as a restart (see _handle) unless a failure
    of the same script is held already; nothing is pushed for it now.

    Its record can land after the record of the attempt that followed it (records
    become readable once their file stops changing): when the ledger already holds
    a success of the same script and user that started after it, it is healed
    already - not held, or the next flush would push a final alarm about a script
    that got through."""
    if later := _later_success(eng, rec):
        log.info("↪️ %s %s 是中途重启（%s），后面那次 %s 已经成功：自己好了，只进日报", rec.script, rec.run_id,
                 _restart_result(rec), later)
        _self_heal_red(eng, f"{rec.script} {rec.run_id} 中途重启", f"{_restart_result(rec)}；后面 {later} 成功")
        return
    if key not in eng._pending:
        eng._pending[key] = rec
        eng._persist_pending()
    log.info("↪️ %s %s 是中途重启（%s），AUTO-MAS 接着重试；先压着，看后面那次", rec.script, rec.run_id,
             _restart_result(rec))


@_one_pass
def _flush_pending(eng) -> None:
    """Push what is held once its script is done retrying, then settle the
    machine-check FAILs kept while their run was held (runchecks._settle_held)."""
    try:
        if getattr(eng, "_unsent_unresolved", None):
            unresolved = _sys.modules[__name__]
            unresolved.retry_unsent(eng)
        if not (eng._pending or eng._recovered):
            return

        # Wait only on the failed script's own retries, never on the rest of the queue.
        # AUTO-MAS writes a script's records once all its attempts are over, so by the
        # time one is held here its retries are normally spent; waiting for the whole
        # queue would hold an alarm behind every script after it.
        for rec in list(eng._recovered.values()):
            if eng._script_running(rec.script):
                continue
            day = run_day(rec)
            # Recovered by itself: AUTO-MAS's own retry, the rerun after an update
            # restart, or the relay's make-up (makeup.py: its success moved the held
            # failure here) got past it. Not pushed; the daily report says it - the
            # failed run's row (↻ 「后来在 HH:MM 那趟重试/补跑里做成了」 with its evidence
            # link, or ↪️ for an update's streak, core.episode_kinds), the run that got
            # through, and the make-up line (report.makeup_line). The user's words for
            # this are in relay/USER-SWITCHES.txt (this function's entry). The title
            # (texts.self_healed / healed_after_update / makeup_passed) only names the
            # log line.
            title = _healed_title(eng, rec, day)
            eng._recovered.pop((rec.script, rec.user), None)
            eng._persist_pending()   # only now is it safe to forget
            why = "、".join(rec.failed_tasks or []) or "没写失败项"
            log.info("%s（%s，跑了 %d 次）：自己好了，只进日报", title, why, _attempts(eng, rec, day))
            _self_heal_red(eng, f"{rec.script} {rec.run_id} {title}", why)

        for rec in list(eng._pending.values()):
            if eng._script_running(rec.script):
                continue
            if (rec.raw or {}).get("hand_started"):
                # The last failed attempt of a task a person started (_hold_hand_started):
                # its retries are over, so its alarm goes out now, saying whose run it was.
                # Not a shift's: no update-restart, make-up or maintenance branch below.
                title, body = _failure_alarm(eng, rec, texts.HAND_STARTED_NOTE, held=True)
                unresolved = _sys.modules[__name__]
                if not unresolved.send(eng, run_day(rec), "手动", rec.run_id, title, body):
                    continue
                eng._pending.pop((rec.script, rec.user), None)
                eng._persist_pending()
                eng.log_tails.pop(rec.run_id, None)
                log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的（任务 %s），同一任务里没有后来跑成的，已报群",
                         rec.script, rec.run_id, rec.raw.get("hand_started"))
                continue
            if _update_restart_done(eng, rec):
                continue
            day = run_day(rec)
            attempts = _attempts(eng, rec, day)
            # Could not get into the game, with an official maintenance window or update
            # notice behind it (handle._mark_downtime, _confirm_unreachable):
            # every such record goes to the group, with that notice in the text; no
            # make-up (gameupdate re-runs it after the queue).
            raw = rec.raw or {}
            maint = raw.get("maintenance")
            if maint or (rec.script == "MaaEnd" and raw.get("maaend_unreachable")):
                hint = maint or raw.get("maaend_unreachable_why") or efstatus.update_hint()
                note = _evidence_note(eng, rec)      # ships the bundle first when the record has none
                page = raw.get("evidence_page") or ""
                from ark_relay.features.collector_maaend import _UNREACHABLE_QUICK_SEC  # noqa: PLC0415
                body = (texts.cant_enter_body(rec.script, attempts, bool(maint), str(hint or ""),
                                              _UNREACHABLE_QUICK_SEC)
                        + (f"\n证据包：{page}" if page else f"\n{note}" if note else ""))
                if errs := eng.notifier.send(texts.cant_enter(rec.script), body, alert=True):
                    log.error("进不了游戏的告警推送出错，保留待重发：%s", "；".join(errs))
                    continue  # if it cannot be sent, come back next tick
                eng._pending.pop((rec.script, rec.user), None)
                eng._persist_pending()
                eng.log_tails.pop(rec.run_id, None)
                log.info("⏸ %s 进不了游戏（尝试 %d 次），已报群", rec.script, attempts)
                continue
            if rec.script in ("MAA", "MaaEnd"):
                # A person would restart the game and run just the failed part once
                # more before calling it a fault (makeup.py). Held until the make-up is
                # over. Still failed, or no make-up for it -> the group hears of it now,
                # every time (unresolved.py). Went through -> recovered: the daily report
                # only, its make-up line and the failed run's row say it.
                from ark_relay.features import makeup  # noqa: PLC0415
                unresolved = _sys.modules[__name__]
                # MAA refused the config itself: no make-up can help, so it is refused
                # here and the alarm goes out on this tick, not after maybe_run's.
                makeup.refuse_rejected(eng, rec)
                verdict, phrase = unresolved.after_makeup(eng, rec)
                if verdict == unresolved.WAIT:
                    continue
                if verdict == unresolved.PASSED:
                    eng._pending.pop((rec.script, rec.user), None)
                    eng._persist_pending()
                    eng.log_tails.pop(rec.run_id, None)
                    passed = texts.makeup_passed(unresolved.GAME[rec.script], unresolved.where(eng, rec)[1])
                    log.info("%s（尝试 %d 次）：补跑走通了，只进日报", passed, attempts)
                    _self_heal_red(eng, f"{rec.script} {rec.run_id} {passed}",
                                   "、".join(rec.failed_tasks or []) or "没写失败项")
                    continue
                if not _push_unresolved(eng, rec, phrase, attempts):
                    continue  # still on disk, retry next tick
                eng._pending.pop((rec.script, rec.user), None)
                eng._persist_pending()
                eng.log_tails.pop(rec.run_id, None)
                log.info("❌ %s 没处理好，已进群（%s；尝试 %d 次）", rec.script, phrase, attempts)
                continue
            # Every final failure is pushed, the same step failing again the same day
            # included.
            note = _evidence_note(eng, rec)
            title, body = core.format_failure(rec, _diagnosis(eng, rec))
            body = texts.failed_body_head(attempts) + _restart_note(rec) + body + (f"\n{note}" if note else "")
            errors = eng.notifier.send(title, body, alert=True)
            if errors:
                log.error("告警推送出错，保留待重发: %s", "；".join(errors))
                continue  # still on disk, retry next tick
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()   # only now is it safe to forget
            log.info("❌ %s 最终失败，告警已推送（尝试 %d 次）", rec.script, attempts)
    finally:
        _settle_held(eng)


# ---------- machine checks (machinecheck.py, event 「run」) ----------


def _judge_run(eng, rec: RunRecord, watch: _RunWatch) -> None:
    """machinecheck.judge(event 「run」) for a record just handled. A broken check or
    context is an ERROR of its own (it reaches the group), never a broken booking."""
    try:
        from ark_relay.features import machinecheck  # noqa: PLC0415
        try:
            version = str(eng.state.store.get("versions", "code") or "")
        except Exception:  # noqa: BLE001 - a version missing from the verdict is no reason to skip it
            version = ""
        machinecheck.judge(eng.cfg.state_dir, "run", _run_ctx(eng, rec, watch),
                           version=version, notifier=eng.notifier)
    except Exception:
        log.exception("上机核对没跑成（%s；记账照常）", rec.run_id)
    finally:
        _OUTCOME.pop(rec.run_id, None)
        _UNVERIFIED.pop(rec.run_id, None)

__all__ = ['MAAEND_NOTHING_TO_RUN', 'MAAEND_NOTHING_TO_RUN_LOG', 'SAME_ROUND', 'SHOT_AFTER_S', 'SHOT_BEFORE_S', 'UNVERIFIED_KIND', '_MAA_LOG_TAIL', '_MAA_TS', '_UNVERIFIED_WHY', '_alert_days', '_alert_file', '_alert_key', '_alert_sizes', '_alerted_file', '_alerts_since', '_already_alerted', '_drop_alarms_for_manual', '_judged', '_maaend_app_log', '_maaend_new_shots', '_maintenance_today', '_mark_alerted', '_mark_no_self_exit', '_okww_master_config', '_okww_nest_expected', '_state_relative', '_test_run', '_update_restarts', '_verify_outcome', 'backfill_manual_stops', 'log']
