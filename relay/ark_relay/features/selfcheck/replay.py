"""Offline replay of the outcome / errwatch judgements - the deploy gate E1.

Before a deploy, the recent relay.log and the evidence-package logs are run
through *this* version's outcome and errwatch offline, and every group push the
current code would have sent is counted. Any push refuses the deploy. The point
is the 2026-10-06 false alarms: the OK-WW weekly waveplate shortage (an update
note matched 「结晶波片不足」), the banner calendar #2 machine check, and the
shutdown snapshot read. Replaying those logs with the old code pushes; with
this code it does not.

Two judgements, two replayers:

* ``okww_pushes(text)`` replays outcome over one OK-WW run log - the real code
  (``outcome.okww_checks`` + ``outcome.summarize``), exactly what
  ``engine._verify_outcome`` runs. Faithful by construction.
* ``errwatch_pushes(text, quiet=...)`` replays the errwatch handler over a
  relay.log: every WARNING / ERROR line of an ``ark.*`` logger is a push,
  except the lines this version no longer pushes. Those live in ``_QUIET``,
  each with the fix that made it quiet. It is a hand registry, not the code,
  because the recovered flag of a line is not in the log text (a recovered
  line and a plain one share the same words) - the registry is the replay's
  knowledge of the current code's recovered / removed wordings, the same way
  the machine checks keep ``old=`` / ``recovered=`` patterns
  (``machinechecks/phone_banners.py`` ``_lines``).

The deploy script (``scripts/mac/deploy-relay.sh``) runs the module's ``main``
over the checked-in false-alarm fixtures (and any ``$REPLAY_LOGS`` the deployer
adds) before it pushes; any push stops the deploy.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# A relay.log line: 「MM-DD HH:MM:SS LEVEL  ark.name  message」. LEVEL is padded
# with spaces to the width of WARNING; the name is always an ark.* logger. The
# bare 「diag:」 and traceback lines have no leading timestamp and are skipped.
_LINE = re.compile(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+(WARNING|ERROR)\s+(ark\.[\w.]+)\s+(.*)$")

# The WARNING / ERROR wordings this version no longer pushes, by logger and
# message. Each is one of the 2026-10-06 false alarms and its fix:
#
# * ark.banners calendar 「没找到…的日期」 / 「只有图，没读到字」 / 「读图失败」 - the
#   cross-check mute of a4db06c1: when another source gave the time, these are
#   logged ``extra=errwatch.recovered()`` (daily report only, not the group).
#   The plain (no-other-source) wording is the same text and would still push;
#   it cannot be told apart from the log line alone, so the registry keeps the
#   fixed case quiet - the replay's job is the false alarm, not a second errwatch.
# * ark.phone_banners 「🔬 上机核对没过：#2」 - the calendar #2 check now passes
#   (the cross-check found the time), so this ERROR is no longer logged.
# * ark.snapshot 「快照的 _MAS错误/_队列错误 这一段读不到」 - the shutdown snapshot
#   skip of b799746e: after the relay issued the power-off those two sections are
#   no longer read (they only fail during the AUTO-MAS teardown).
_QUIET = (
    ("ark.banners", re.compile(r"版本活动日历读了 \d+ 行，没找到「")),
    ("ark.banners", re.compile(r"^这条公告只有图，没读到字：")),
    ("ark.banners", re.compile(r"^鸣潮版本活动日历读图失败")),
    ("ark.phone_banners", re.compile(r"^🔬 上机核对没过：#2\b")),
    ("ark.snapshot", re.compile(r"^快照的 _(MAS错误|队列错误) 这一段读不到")),
)


def okww_pushes(text: str, *, expect_nest: bool = False, expect_daily: bool = True,
                expect_stamina: bool = True, only_nest: str = "") -> list[str]:
    """The group pushes ``outcome.okww_checks`` would send for one OK-WW run log.

    Defaults match ``okww_checks``: daily and stamina are expected, no nest
    filter. Each entry is the paragraph ``outcome.summarize`` would push (which
    starts 「OK-WW 这一轮有 … 项没干成」); an empty list means the run is green."""
    from ark_relay.features.verify.outcome import okww_checks, summarize  # noqa: PLC0415

    msg = summarize(okww_checks(text, expect_nest=expect_nest, expect_daily=expect_daily,
                                expect_stamina=expect_stamina, only_nest=only_nest), "OK-WW")
    return [msg] if msg else []


def errwatch_pushes(text: str, quiet: tuple = _QUIET) -> list[dict]:
    """The group pushes errwatch would send for the WARNING / ERROR lines of a relay.log.

    Each entry is ``{where, line, lineno}`` - the logger, the message, and the
    source line number. ``quiet`` is the registry of wordings this version no
    longer pushes; pass ``()`` to replay the old code (everything pushes)."""
    out: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        m = _LINE.match(line)
        if m is None:
            continue
        name, msg = m.group(2), m.group(3)
        if any(n == name and rx.search(msg) for n, rx in quiet):
            continue
        out.append({"where": name, "line": msg, "lineno": i})
    return out


def _is_okww(path: str) -> bool:
    # The checked-in fixture is 「okww-1006-run.log」 and the evidence package's own
    # name is 「OK-WW-…」: both are OK-WW run logs (an exact 「OK-WW」 test missed the
    # fixture, so the deploy gate replayed it as a relay.log and found nothing).
    return re.search(r"ok-?ww", Path(path).name, re.I) is not None


def _pushed(path: str) -> list[str]:
    """The pushes replaying one file would send, as printable lines with their source."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{path}: 读不了：{exc}"]
    if _is_okww(path):
        return [f"{path} → {push.splitlines()[0]}" for push in okww_pushes(text)]
    return [f"{path}:{p['lineno']} {p['where']}: {p['line'][:160]}" for p in errwatch_pushes(text)]


def main(argv: list[str]) -> int:
    """Replay the given log files; print every push with its source; 1 when any push."""
    pushed: list[str] = []
    for path in argv:
        pushed += _pushed(path)
    if pushed:
        for line in pushed:
            print(line)
        print(f"{len(pushed)} 条会推进群", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
