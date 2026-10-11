"""ERROR lines in a game's own log for a round AUTO-MAS booked as a success.

Until 2026-10-11 the relay read the game logs only for the shapes it knew (the outcome
checks, collector_*): an ERROR line it did not know was ignored when the round ended
normally. On 2026-09-29 OK-WW logged 「can not battle pass, maybe ended」, the battle-pass
reward was not claimed, and the relay said nothing at all. The user, 2026-10-11 17:43
(Tokyo): 「你们有多少东西只进日报不去修的？如果不是自己好了禁止只进日报」.

So every ERROR line of a successful round's log (the AUTO-MAS history copy, rec.log_path)
is checked against gamelog_errors.txt next to this file: one line per known shape,

    <script> | <regex> | verdict: recovered - <why> | <source>
    <script> | <regex> | verdict: not-a-fault - <why> | <source>

`recovered` - the program got past it by itself in the same round (a retry, a re-read, a
window that came up a moment later); `not-a-fault` - not a failure at all, with what makes
it so. A line that matches no entry is pushed to the group, once per round (one fault, one
push: the round's record is handled once), and its raw lines go to the technical log as a
red item for us to look at. tests/test_gamelog_errors.py holds each entry to that shape and
to a real line it must match. Failed rounds are not read here: their failure is pushed (or
healed, with its own red item) on handle's failure path.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("ark.gamelog_errors")

REGISTRY = Path(__file__).with_name("gamelog_errors.txt")
VERDICT = re.compile(r"^verdict:\s+(recovered|not-a-fault)\s+-\s+(\S.*)$")

# The ERROR marker of each script's log, and how much of a line to quote.
_MARK = {
    "MAA": re.compile(r"\[ERR\]"),                  # MAA's gui.log copy
    "MaaEnd": re.compile(r"\[ERR\]"),               # MaaFramework's log copy
    "OK-WW": re.compile(r" ERROR "),                # OK-WW's ok-script log copy
}
_NUM = re.compile(r"\d+")
QUOTE = 300


class Entry:
    __slots__ = ("script", "pattern", "kind", "why", "source", "line_no")

    def __init__(self, script, pattern, kind, why, source, line_no):
        self.script, self.pattern, self.kind, self.why, self.source, self.line_no = \
            script, pattern, kind, why, source, line_no


def parse(text: str) -> "tuple[list[Entry], list[str]]":
    """(entries, problems) of a registry text; problems name the line."""
    entries, problems = [], []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) != 4:
            problems.append(f"line {i}: not `script | regex | verdict: ... | source`")
            continue
        script, rx, verdict, source = parts
        if script not in _MARK:
            problems.append(f"line {i}: unknown script {script!r}")
            continue
        try:
            pattern = re.compile(rx)
        except re.error as exc:
            problems.append(f"line {i}: bad regex ({exc})")
            continue
        m = VERDICT.match(verdict)
        if not m:
            problems.append(f"line {i}: verdict is not `verdict: recovered - why` / `verdict: not-a-fault - why`")
            continue
        entries.append(Entry(script, pattern, m.group(1), m.group(2), source, i))
    return entries, problems


_cache: dict = {}


def registry() -> "list[Entry]":
    """The shipped registry, read once per process. Unreadable: no entry (everything is pushed)."""
    if "entries" not in _cache:
        try:
            entries, problems = parse(REGISTRY.read_text(encoding="utf-8"))
        except OSError as exc:
            entries, problems = [], [f"{REGISTRY.name} unreadable: {type(exc).__name__}"]
        if problems:
            log.warning("游戏日志报错清单有 %d 行读不了，这些行不算登记：%s", len(problems), "；".join(problems[:3]))
        _cache["entries"] = entries
    return _cache["entries"]


def error_lines(script: str, text: str) -> "list[str]":
    """The ERROR lines of one script's log text."""
    mark = _MARK.get(script)
    if mark is None:
        return []
    return [ln.rstrip() for ln in text.splitlines() if mark.search(ln)]


def known(script: str, line: str, entries=None) -> "Entry | None":
    for e in registry() if entries is None else entries:
        if e.script == script and e.pattern.search(line):
            return e
    return None


def unregistered(script: str, text: str, entries=None) -> "list[tuple[str, int]]":
    """Distinct ERROR lines no entry matches: (first such line, how many lines of that
    shape - digits folded), in order of first appearance."""
    out: dict[str, list] = {}
    for line in error_lines(script, text):
        if known(script, line, entries) is not None:
            continue
        body = line[_MARK[script].search(line).start():]
        shape = _NUM.sub("#", body)[:160]
        if shape in out:
            out[shape][1] += 1
        else:
            out[shape] = [line[:QUOTE], 1]
    return [(first, n) for first, n in out.values()]


def check_round(eng, rec) -> "list[tuple[str, int]]":
    """Push the unregistered ERROR lines of a round AUTO-MAS booked as a success.

    One WARNING per round, titled and worded for him (texts.gamelog_unknown_errors),
    the raw lines to the technical log as one red item. Returns what was unregistered.
    Never raises: a log that cannot be read is said (a WARNING), never taken as clean."""
    from ark_relay.core import techlog, texts  # noqa: PLC0415
    from ark_relay.core.names import GAME_ZH  # noqa: PLC0415
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    script = getattr(rec, "script", "")
    if script not in _MARK or not getattr(rec, "log_path", None):
        return []
    try:
        text = Path(rec.log_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("%s %s 的日志读不了（%s），这一趟日志里的报错没查", script, rec.run_id, type(exc).__name__)
        return []
    found = unregistered(script, text)
    if not found:
        return []
    from datetime import datetime  # noqa: PLC0415
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    game = GAME_ZH.get(script, script)
    started = getattr(rec, "started", None)
    at = started.strftime("%H:%M") if started else ""
    day = (started or datetime.now(tz=SERVER_TZ)).strftime("%Y-%m-%d")
    shown = "；".join(f"{line}（{n} 行）" for line, n in found[:8])
    techlog.add_red(day, "游戏日志里没登记的报错",
                    [f"{script} {rec.run_id}：{len(found)} 种没登记的报错：{shown}"],
                    state_dir=getattr(eng.cfg, "state_dir", None))
    log.warning("%s %s 跑成功了，日志里有 %d 种没登记的报错：%s", script, rec.run_id, len(found), shown,
                extra=errwatch.alarm(texts.gamelog_unknown_errors(game),
                                     texts.gamelog_unknown_errors_body(game, at, len(found))))
    return found
