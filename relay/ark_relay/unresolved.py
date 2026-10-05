"""A MAA / MaaEnd problem that outlived the relay's own handling goes to the group, every time.

From 13:07 to 15:38 on 2026-10-05 a MAA / MaaEnd failure went to the daily
report only, after one make-up run (makeup.py), and the group heard about a game
only once it had got nothing done all day (dayfail.py, removed). The user, 15:38,
asking why the group stays silent: 「为啥群里不响？你们不是没处理好吗？」, and that
this way the chance to fix it at once is lost. A problem the relay could not sort
out is one a person has to fix, and the sooner the better. So (D206 revised):

* a failure AUTO-MAS's own retries did not get past is held for its make-up;
  the moment the make-up is over and the game is still not done - the make-up
  failed, never produced a record, was given up or could not be dispatched - or
  there was no make-up for it (the day's one is spent, or midnight came first),
  the group hears of it (handle._flush_pending, `after_makeup`);
* a round that exited normally with work left undone (「没干完」) gets no make-up
  and goes to the group at once (handle._handle_success), whichever items they
  are - 自动采集 and 应急理智加强剂 included;
* every such failure and every such round rings. Until 2026-10-06 a shift rang
  at most once (key 「未解决|<script>|<shift>」) and a MaaEnd round short of only
  自动采集 / 应急理智加强剂 stayed in the daily report; the user's order that day,
  「不论多少次什么错误都要发」, ended both. The key is now the record itself
  (`alert_key`), so only a replay of the same record is not pushed twice. A push
  that did not go out is tried again on the next tick.

A make-up that went through is pushed through `send` as well, under its own
title (handle._push_unresolved; until 2026-10-06 the daily report only). What
handle.py settles before this module - AUTO-MAS's retry went through, could not
enter the game, MAA short of sanity, an attempt AUTO-MAS restarted at once,
MaaEnd restarting itself to install a new build after its shift's round was
already done (`done_in_shift`) - goes to the group too since 2026-10-06, each
with its own title. Only a run stopped by the user's own red button (停一切) is
not pushed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from .config import SERVER_TZ
from .names import EVENING, MORNING

log = logging.getLogger("ark.unresolved")

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
    from . import modes, names, plan  # noqa: PLC0415
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
    from . import makeup  # noqa: PLC0415
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
    except Exception:  # a broken config must not lose the alarm
        log.warning("读不到 %s 的班次，按中午前后分早晚班", day, exc_info=True)
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
    exited normally with nothing left undone; '' when there is none.

    10-04 09:51:26 and 10-05 11:30:44: MaaEnd's round had got everything done
    (静默记账), then the next attempt was MaaEnd installing its new build and
    restarting itself; with no success after it, that attempt was pushed as the
    final failure. A round already done makes such an attempt nothing at all.
    Rounds stopped by the red button or started by a person do not count.
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
            if other.started is not None and where(eng, other) == (day, shift):
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
    from . import makeup  # noqa: PLC0415
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

    The alarm is one `kind` (未解决 / 手动 / 更新日 / 补跑走通 / 重启 / 理智 / 装新版)
    about one record, `run_id`; its key is built here from the two, so the only
    push this holds back is the same alarm about the same record a second time
    (handle.py replays a record whose handling broke off midway,
    _append_ledger_once). Until 2026-10-06 callers passed the key ready-made,
    and nothing here could show it named a record."""
    from . import errwatch  # noqa: PLC0415
    key = _key(kind, run_id)
    if eng._already_alerted(day, key):  # one fault, one push: the record's run_id in `key`
        log.info("%s %s 这一条已经进过群（同一条记录又处理了一遍），不重推", day, key)
        return True
    if errs := eng.notifier.send(title, body, alert=True):
        # A failure of its own: errwatch pushes this line too (queued until the group takes it).
        log.warning("「%s」没推出去，下一轮再试：%s", title, "；".join(errs))
        return False
    eng._mark_alerted(day, key)
    log.warning("🚨 %s 已进群：%s", title, body.replace("\n", " ")[:300],
                extra=errwatch.group_pushed(title, errs, eng.notifier))
    return True


def retry_unsent(eng) -> None:
    """Push again what `send` could not deliver (the 「没干完」 path holds no record)."""
    left = []
    for day, kind, run_id, title, body in getattr(eng, "_unsent_unresolved", []):
        if not send(eng, day, kind, run_id, title, body):
            left.append((day, kind, run_id, title, body))
    eng._unsent_unresolved = left
