"""Alarms that go to the group at once instead of being held for retries:
an undone round, items done without game evidence, a failure its make-up did
not fix; plus the one push-and-keep-if-unsent helper they share and the
evidence line every final alarm carries.
"""
from __future__ import annotations

import dataclasses
import logging

from ark_relay.core import texts
from ark_relay.core import ledger as core
from ark_relay.core.config import RunRecord
from ark_relay.features.alarm.records import _diagnosis, _restart_note, run_day

# Same logger as handle.py: relay.log names these lines "ark.handle".
log = logging.getLogger("ark.handle")


def _errwatch():
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    return errwatch


def _push_undone(eng, rec: RunRecord, msg: str, page: str) -> tuple[str, list]:
    """A MAA / MaaEnd round that exited normally with work left undone: no make-up
    is run for it, so the group hears of it now (unresolved.py), whichever items
    they are - 自动采集 and 应急理智加强剂 included. Returns (title, errors) of the
    push."""
    from ark_relay.features.alarm import unresolved  # noqa: PLC0415
    day, shift = unresolved.where(eng, rec)
    game = unresolved.GAME[rec.script]
    # The caller has just tried the bundle (_ship_evidence); no second upload here.
    note = "" if page else texts.EVIDENCE_NOT_SHIPPED + "\n"
    body = texts.unresolved_undone_head(game, shift, unresolved.undone_label(msg), page) + note + "\n" + msg
    title = texts.unresolved_undone(game, shift)
    return title, _push_now(eng, day, unresolved.UNRESOLVED_KIND, rec.run_id, title, body)


# Why an item does not count, by game (core.day_unverified_items says how each is found).
_UNVERIFIED_WHY = {
    "MaaEnd": "日志里没有游戏回显，也没有任务结束的截图",
    "MAA": "日志里没有「剿灭模式 x/y」这行进度",
    "OK-WW": "日志里没读到做完",
}
UNVERIFIED_KIND = "没证据"


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
        from ark_relay.features.alarm import unresolved  # noqa: PLC0415
        # Read from handle at call time: tests rebind handle._ship_evidence.
        from ark_relay.features.alarm.handle import _ship_evidence  # noqa: PLC0415
        day = run_day(rec)
        items = dict(core.day_unverified_items(eng.state.read_ledger(day))).get(rec.script)
        if not items:
            return
        _, shift = unresolved.where(eng, rec)
        game = core._game(rec.script)
        page = _ship_evidence(eng, rec)
        head = texts.unverified_alarm_head(game, shift, "、".join(items),
                                           _UNVERIFIED_WHY.get(rec.script, "没有游戏里的证据"), page)
        body = head + ("" if page else texts.EVIDENCE_NOT_SHIPPED + "\n")
        # Keyed by the items, not the record: a later run of the same game the same
        # day with the same items left unbacked is the same alarm, not a new one.
        _push_now(eng, day, UNVERIFIED_KIND, f"{rec.script}:{'、'.join(items)}",
                  texts.unverified_alarm(game, shift, len(items)), body)
    except Exception:
        log.exception("「没证据」这一项没能推到群里（%s）", rec.run_id)


def _push_now(eng, day: str, kind: str, run_id: str, title: str, body: str) -> list:
    """Push one alarm of `kind` about the record `run_id` to the group now; one that
    did not go out is kept and tried again on the next tick (unresolved.retry_unsent).
    -> errors."""
    from ark_relay.features.alarm import unresolved  # noqa: PLC0415
    if unresolved.send(eng, day, kind, run_id, title, body):
        return []
    eng._unsent_unresolved.append((day, kind, run_id, title, body))
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
        from ark_relay.features.alarm.handle import _ship_evidence  # noqa: PLC0415
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
    from ark_relay.features.alarm import unresolved  # noqa: PLC0415
    day, shift = unresolved.where(eng, rec)
    game = unresolved.GAME[rec.script]
    note = _evidence_note(eng, rec)
    raw = rec.raw or {}
    names = core._with_causes(list(rec.failed_tasks or []), raw.get("maaend_fail_causes"))
    stuck = "、".join(names[:3]) + ("…" if len(names) > 3 else "")
    page = raw.get("evidence_page") or ""
    # The link goes in the head; the rest of the body is the usual failure text without it.
    _, rest = core.format_failure(dataclasses.replace(rec, raw={k: v for k, v in raw.items() if k != "evidence_page"}),
                                  _diagnosis(eng, rec))
    body = (texts.unresolved_head(game, shift, makeup_phrase, stuck, page) + (note + "\n" if note else "") + "\n"
            + texts.failed_body_head(attempts) + _restart_note(rec) + rest)
    if raw.get("maaend_unreachable_shape") and not raw.get("maaend_unreachable"):
        body += "\n" + texts.UNREACHABLE_SHAPE_NOTE
    return unresolved.send(eng, day, unresolved.UNRESOLVED_KIND, rec.run_id, texts.unresolved(game, shift), body)
