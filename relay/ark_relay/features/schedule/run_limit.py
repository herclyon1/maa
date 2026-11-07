"""Keep Endfield's failure retry limit in AUTO-MAS at 1.

2026-11-05 morning: AUTO-MAS's Run.RunTimesLimit was 3, so one failed Endfield round was run
twice more by AUTO-MAS itself, all three stuck at the same gathering route, and the relay's
make-up made it five. The user then asked for a morning shift that just completes:
「我要你交的保证真的是，我正常早班能跑完，我不管别的，把中继给我根治了」 (11-05 13:0x Tokyo, his words in the chat with the session that root-fixed the relay that day).
The limit went to 1 that day (memory maaend-retry-policy-1105): what is missing after a round
is the relay's call (collect_retry, makeup), not three blind re-runs.

The limit is AUTO-MAS's own setting, written through its API. An AUTO-MAS update, or one click
in its window, puts it back to 3 with nobody noticing. So every engine tick reads it, and a
value other than 1 is written back and read back (commands._script_item_via_api). AUTO-MAS
refuses the write while that script runs (「正在运行，无法更新配置项」, 11-05 13:1x); the next tick
tries again, and a tick comes when the run's record lands. A write that worked is one Server-chan
line a day; ALARM_AFTER failures in a row for another reason are one group alarm.
"""
from __future__ import annotations

import logging
from datetime import datetime

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ

log = logging.getLogger(__name__)

WANT = {"MaaEnd": 1}
GAME = {"MaaEnd": "终末地"}
PATH = "Run.RunTimesLimit"
# The decision is of 2026-11-05 (module docstring); a replayed day before it ran under 3.
SINCE = "2026-11-05"
# AUTO-MAS's refusal while the script runs (11-05 13:1x); not a fault, the next tick retries.
BUSY = "正在运行"
ALARM_AFTER = 3


def _read(script: str) -> "tuple[dict | None, object]":
    """(the /api/scripts/get reply, the current limit), or (None, None) when the
    backend is down or the script / item is not there (nothing to guard then)."""
    from ark_relay.features.phone import commands  # noqa: PLC0415
    reply, _why = commands._backend_scripts()
    scripts = reply.get("data") if isinstance(reply, dict) else None
    if not isinstance(scripts, dict):
        return None, None
    for sc in scripts.values():
        if isinstance(sc, dict) and str((sc.get("Info") or {}).get("Name") or "").lower() == script.lower():
            try:
                return reply, commands._dig(sc, PATH)
            except KeyError:
                return None, None
    return None, None


def _fails(eng) -> dict:
    """{script: {"n": write-backs failed in a row, "alarmed": the group has it}}, on the engine."""
    got = getattr(eng, "_run_limit_fails", None)
    if not isinstance(got, dict):
        got = {}
        eng._run_limit_fails = got
    return got


def step(eng, now: "datetime | None" = None) -> None:
    """One look per engine tick; a limit other than WANT is written back."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    if day < SINCE:
        return
    from ark_relay.features.phone import commands  # noqa: PLC0415
    for script, want in WANT.items():
        reply, cur = _read(script)
        if reply is None:
            continue
        fails = _fails(eng)
        if cur == want:
            fails.pop(script, None)
            continue
        ok, msg = commands._script_item_via_api(reply, script, PATH, want)
        game = GAME.get(script, script)
        if ok:
            log.info("%s 的失败重试上限被改成了 %s，已改回 %s：%s", script, cur, want, msg)
            fails.pop(script, None)
            if getattr(eng, "_run_limit_noted", "") != day and \
                    not eng.notifier.send(texts.RUN_LIMIT_RESET, texts.run_limit_reset_body(game, cur, want)):
                eng._run_limit_noted = day
            continue
        if BUSY in msg:
            log.info("%s 正在跑，失败重试上限 %s 先不改回 %s，下一轮再改", script, cur, want)
            continue
        st = fails.setdefault(script, {"n": 0, "alarmed": False})
        st["n"] += 1
        n = st["n"]
        log.info("%s 的失败重试上限是 %s，改回 %s 没成（第 %d 次）：%s", script, cur, want, n, msg)
        # From ALARM_AFTER on until the group has it: an alarm whose send failed was never
        # tried again while the count ran past it (audit 2026-11-08 B-07).
        if n >= ALARM_AFTER and not st["alarmed"]:
            errs = eng.notifier.send(texts.RUN_LIMIT_STUCK, texts.run_limit_stuck_body(game, cur, want, msg), alert=True)
            st["alarmed"] = not errs
