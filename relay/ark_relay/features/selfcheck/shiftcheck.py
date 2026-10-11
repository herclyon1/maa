"""After-shift check: the sign-off items the relay had no check of its own for.

scripts/mac/lib/healthcheck.py is the hand-run sign-off check. Everything else in it
is already judged by the relay itself (boot self-check, the daily report's relay
lines, the machine checks). These four were not, so they run here once after every
finished morning / evening shift. The 游戏-中继二 session's scope cut of 10-10 23:3x
listed six; 验收 dropped MAA's IfActivityFirst and IfFight on 10-11 (his own phone
settings - his 09-11 「管我刷什么干嘛」 - and the daily report is for him to read):

1. MAA's annihilation switch is not "Close" with this game-week not done
   (annihilation.WeeklyGate.switch_off_line - the same rule as the boot alarm);
2. the one-shot 「下次跑完不关机」 mark is not armed when the shift ends (modes.skip_armed;
   armed, it skips this shift's power-off and the machine stays on until the next shift);
3. debug mode is not on (modes.debug_active);
4. no test window run-one.sh opened is still open (report.test_windows).

When: the first tick after a scheduled shift on this boot has every script
recorded and its records seen landing (shutdown._not_shift returns None - which
already leaves out a run started by hand and a relay restarted after the shift).
Once per shift: the shift's due time is kept in state.json marks. It runs before
the daily report and the shutdown decision of that tick: the report then carries
the line, and the 「下次跑完不关机」 mark is read before the shutdown step spends it.

Route: one relay.log INFO line per shift (texts.shiftcheck_summary), which
selfcheck.daily_lines quotes in the daily report's relay section. Nothing is
pushed. Items 2 and 3 are recorded normal states (USER-SWITCHES.txt,
shutdown.py:_say_if_moment_passed), 4 is ours; the annihilation switch already rings the group once per boot
(boot_stages._annihilation_switch_off). A crash inside the check is a relay fault of
its own: logged at ERROR (errwatch pushes it, as every other broken relay step in
engine.tick), and that line - which says the shift was not checked - is what the
daily report quotes for the shift.
"""
from __future__ import annotations

import logging
from datetime import datetime

from ark_relay.core import names, texts
from ark_relay.features.selfcheck.selfcheck import Check

log = logging.getLogger("ark.shiftcheck")

MARK = "shiftcheck_shift"     # state.json marks: the due time of the last shift checked
_last_failure = [""]          # the last reason maybe_run could not tell whether a shift finished


def judge(annihilation_line: "str | None", skip_armed: bool, debug_on: bool, debug_until: str,
          windows: list) -> list[Check]:
    """The four items from what was read. `annihilation_line` is switch_off_line's text
    ('' when the switch is fine, None when it could not be read)."""
    out: list[Check] = []
    out.append(Check(texts.SHIFTCHECK_ANNIHILATION, None if annihilation_line is None else not annihilation_line,
                     texts.SHIFTCHECK_ANNIHILATION_UNREAD if annihilation_line is None else annihilation_line))
    out.append(Check(texts.SHIFTCHECK_SKIP, not skip_armed, texts.SHIFTCHECK_SKIP_ON))
    out.append(Check(texts.SHIFTCHECK_DEBUG, not debug_on, texts.shiftcheck_debug_on(debug_until)))
    still = [w for w in windows if isinstance(w, dict) and w.get("until") is None]
    out.append(Check(texts.SHIFTCHECK_TEST_WINDOW, not still,
                     texts.shiftcheck_test_window_on(str(still[0].get("since") or "")) if still else ""))
    return out


def summary(shift: str, checks: list[Check]) -> str:
    bad = [(c.name, c.detail) for c in checks if c.ok is False]
    unread = [(c.name, c.detail) for c in checks if c.ok is None]
    return texts.shiftcheck_summary(shift, len(checks), bad, unread)


def read(eng, now: datetime) -> list[Check]:
    """Read the four items on the machine and judge them."""
    from ark_relay.features.modes import modes  # noqa: PLC0415
    from ark_relay.features.report import report  # noqa: PLC0415
    state_dir = eng.cfg.state_dir
    gate = getattr(eng, "_annihilation", None)
    try:
        ann = gate.switch_off_line(now) if gate is not None else None
    except Exception as exc:  # noqa: BLE001 - an unreadable switch is a 「判不了」, not a crash
        log.warning("收工体检：剿灭开关读不到（%s: %s）", type(exc).__name__, exc)
        ann = None
    return judge(ann, modes.skip_armed(state_dir), modes.debug_active(state_dir, now),
                 modes.debug_until(state_dir), report.test_windows(state_dir))


def finished_shift(eng, now: datetime) -> "dict | None":
    """The scheduled shift on this boot that has just finished (the latest-due queue of
    it), or None when none has (the same test the shutdown decision uses)."""
    from ark_relay.features.shutdown import shutdown  # noqa: PLC0415
    booted = eng._boot_time(now)
    if booted is None:
        return None
    shift = shutdown._shift_queues(eng, now, booted)
    if not shift:
        return None
    if shutdown._not_shift(eng, now, eng._recent_entries(now), booted, shift) is not None:
        return None
    return max(shift, key=lambda q: q["due"])


def maybe_run(eng, now: datetime) -> "list[Check] | None":
    """Run the check once for a shift that just finished. Returns the checks, or None
    when there was nothing to do now. Never raises."""
    try:
        last = finished_shift(eng, now)
        if last is None:
            return None
        key = last["due"].isoformat()
        store = eng.state.store
        if store.get("marks", MARK) == key:
            return None
        # Marked before judging: a check that crashes must not run again on every tick.
        store.set("marks", MARK, key)
        shift = names.canonical(str(last.get("name") or "")).strip("?") or (
            names.MORNING if last["due"].hour < 12 else names.EVENING)   # plan gives "?" for no name
    except Exception as exc:
        # Asked again on every tick: logged once per distinct failure, not once a tick.
        why = f"{type(exc).__name__}: {exc}"
        if _last_failure[0] != why:
            _last_failure[0] = why
            log.exception("收工体检：判不了这班跑完没有，这一轮不查")
        return None
    _last_failure[0] = ""
    try:
        checks = read(eng, now)
    except Exception:
        log.exception(texts.shiftcheck_broken(shift))
        return []
    log.info(summary(shift, checks))
    return checks
