"""The relay's technical log: what we read, not the user.

Decision D-1010 (the user, 2026-10-10 22:47 Osaka; quoted in
~/Money/styl-work/BOARD/DECISIONS.md): the daily report is for a person to read;
everything technical goes somewhere of our own and we read it every day.

So everything technical that used to ride on the daily report (deploys of the day,
the relay's own WARNING / ERROR lines, machine checks, the boot self-check, the
test-window count, evidence links, version numbers and file names) goes here
instead (features/report/report.write_daily_techlog). Other writers (the post-shift
health check, the shutdown path) append to the same file the same way.

One Markdown file per day, appended to, never rewritten:

    <ARK_STATE_DIR>/../tech/YYYY-MM-DD.md      (C:\\ProgramData\\ark-relay\\tech\\ on the machine)

A section is `## HH:MM <heading>` followed by its text. A red item is one line

    🔴 <id> <text>              id = R-YYYYMMDD-HHMM-<n>

and it is handled once a later line (in any day's file) matches DONE_LINE, the
line handled_line(<id>, <commit>) writes.

Writing never raises: the daily report must go out whether or not this file can be
written.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.techlog")

RED = "🔴"
DONE = "✅"
RED_LINE = re.compile(r"^🔴 (R-\d{8}-\d{4}-\d+) (.*)$")
DONE_LINE = re.compile(r"^✅ (R-\d{8}-\d{4}-\d+) 已处理（(.+?)）")


def tech_dir(state_dir: "Path | str | None" = None) -> Path:
    """<state dir>/../tech - next to state/ and relay.log on the machine."""
    base = Path(state_dir or os.environ.get("ARK_STATE_DIR", "./ark-state"))
    return base.resolve().parent / "tech"


def path_for(day: str, state_dir=None) -> Path:
    return tech_dir(state_dir) / f"{day}.md"


def append(day: str, heading: str, text: str, *, state_dir=None, now: "datetime | None" = None) -> bool:
    """Append one section to the day's file. False (and a log line) when it cannot be written."""
    text = (text or "").strip()
    if not text:
        return True
    at = (now or datetime.now(tz=SERVER_TZ)).strftime("%H:%M")
    try:
        p = path_for(day, state_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"\n## {at} {heading}\n{text}\n")
        return True
    except OSError as exc:
        # A WARNING, so the group hears it (the user, 2026-10-11 17:43: nothing that
        # did not fix itself stays out of the group): a red item that cannot be
        # written is a fault nobody would otherwise look at. The report still goes out.
        log.warning("技术日志写不进 %s：%s", day, type(exc).__name__)
        return False


def red_items(day: str, texts: "list[str]", *, now: "datetime | None" = None) -> list[str]:
    """Lines for the red items of one check run, each with its own id."""
    at = now or datetime.now(tz=SERVER_TZ)
    stamp = at.strftime("%Y%m%d-%H%M")
    return [f"{RED} R-{stamp}-{i} {t}" for i, t in enumerate(texts, 1)]


_ids = threading.Lock()


def add_red(day: str, heading: str, texts: "list[str]", *, state_dir=None,
            now: "datetime | None" = None) -> list[str]:
    """Append one section of red items whose ids are not used yet in the day's file.

    red_items() numbers from 1 for every call, so two calls in the same minute
    would write the same id twice and one `handled` would clear both; this one
    continues after the highest number already written for that minute. Returns
    the ids written ([] when nothing was written)."""
    at = now or datetime.now(tz=SERVER_TZ)
    texts = [" ".join(str(t).split())[:400] for t in texts if str(t).strip()]
    if not texts:
        return []
    stamp = at.strftime("%Y%m%d-%H%M")
    with _ids:
        try:
            old = path_for(day, state_dir).read_text(encoding="utf-8")
        except OSError:
            old = ""
        used = [int(m.group(1)) for m in re.finditer(rf"^{RED} R-{stamp}-(\d+) ", old, re.M)]
        start = max(used, default=0)
        lines = [f"{RED} R-{stamp}-{start + i} {t}" for i, t in enumerate(texts, 1)]
        if not append(day, heading, "\n".join(lines), state_dir=state_dir, now=at):
            return []
    return [ln.split(" ", 2)[1] for ln in lines]


SELF_HEAL = "自愈待查"


def self_heal(where: str, why: str, *, state_dir=None, now: "datetime | None" = None) -> list[str]:
    """One red item for a fault that fixed itself and so stayed out of the group.

    The user, 2026-10-11 17:44 (Tokyo): 「只进日报的东西只允许是他自己好了，可以不报警，
    但你们必须有人要去查，去看是什么情况。」 Every way a fault leaves the group because it
    recovered (errwatch.recovered(), handle's heals, the gathering retry that walked)
    writes one of these, with where it happened and the first reason, and it counts
    as unhandled until scripts/mac/techlog.py handled marks it."""
    at = now or datetime.now(tz=SERVER_TZ)
    return add_red(at.strftime("%Y-%m-%d"), SELF_HEAL, [f"{SELF_HEAL}：{where}：{why or '没记下原因'}"],
                   state_dir=state_dir, now=at)


def unhandled(text: str) -> list[tuple[str, str]]:
    """(id, text) of every red item in `text` without a handled line for it."""
    reds: dict[str, str] = {}
    done: set[str] = set()
    for line in text.splitlines():
        if m := RED_LINE.match(line.strip()):
            reds.setdefault(m.group(1), m.group(2))
        elif m := DONE_LINE.match(line.strip()):
            done.add(m.group(1))
    return [(i, t) for i, t in reds.items() if i not in done]


def handled_line(item_id: str, commit: str) -> str:
    return f"{DONE} {item_id} 已处理（{commit}）"
