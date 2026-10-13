"""daysim: days that are red only because of relay bugs already reported (known-red.json).

The day gate (gate.py, deploy-relay.sh step 0.8) must stop on any NEW red, but a bug
that is reported and not fixed yet would otherwise block every deploy, including
unrelated ones. known-red.json lists, per day, the exact failure lines such a bug
causes; run.py then judges a day by what is left once those lines are taken out.

Each entry:

    {"day": "2026-10-13", "bug": "daysim-R2", "report": "docs/BACKLOG.md",
     "added": "2026-10-13", "expires": "2026-10-20", "count": 2,
     "excuses": ["^strict: no entry expects push serverchan \\\\S+ '⚙️ 配置已更新："],
     "why": "..."}

How the list is kept shrinking to empty (every rule below fails the gate):

* the report must exist and hold the bug id on an open todo line (`- [ ] **<bug>:`);
  a closed or deleted report means the bug is fixed, so its entries must go;
* an entry expires at most EXPIRY_MAX_DAYS after it was added (docs/BACKLOG.md:
  a skipped test stays registered a week at most);
* stale: when a day runs, every excuse must match exactly `count` failure lines in
  total; a fixed bug (fewer or no matches) and a changed one (more) both fail the
  gate until the entry is edited or removed;
* never excusable: the budget line and invariant 5 (sim errors): those are the
  simulator's own health, not a relay bug.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
KNOWN_RED = HERE / "known-red.json"
# docs/BACKLOG.md / ~/Claude/CLAUDE.md: a skipped test is registered for one week at most.
EXPIRY_MAX_DAYS = 7
NEVER_EXCUSED = re.compile(r"^(budget:|invariant 5:)")
FIELDS = {"day", "bug", "report", "added", "expires", "count", "excuses", "why"}


class KnownRedError(ValueError):
    pass


def load(path: Path = KNOWN_RED, *, today: "date | None" = None, repo: Path = REPO) -> list[dict]:
    """The entries, or KnownRedError listing every problem (expired, no open report, ...)."""
    today = today or date.today()
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise KnownRedError([f"{path.name}: no 'entries' list"])
    problems = []
    for i, e in enumerate(entries):
        where = f"{path.name} entry {i} ({e.get('day')} {e.get('bug')})"
        if set(e) != FIELDS:
            problems.append(f"{where}: fields must be exactly {sorted(FIELDS)}, got {sorted(e)}")
            continue
        try:
            added, expires = date.fromisoformat(e["added"]), date.fromisoformat(e["expires"])
            date.fromisoformat(e["day"])
        except (TypeError, ValueError):
            problems.append(f"{where}: day / added / expires must be YYYY-MM-DD")
            continue
        if (expires - added).days > EXPIRY_MAX_DAYS or expires < added:
            problems.append(f"{where}: expires {expires} is more than {EXPIRY_MAX_DAYS} days after added {added}")
        if today > expires:
            problems.append(f"{where}: expired on {expires}; fix {e['bug']} or re-review it (and move "
                            "'expires' with a reason in its report)")
        if not (isinstance(e["count"], int) and e["count"] >= 1):
            problems.append(f"{where}: count must be a positive integer")
        if not (isinstance(e["excuses"], list) and e["excuses"]):
            problems.append(f"{where}: excuses must be a non-empty list of regexes")
        else:
            for x in e["excuses"]:
                try:
                    re.compile(x)
                except (re.error, TypeError) as exc:
                    problems.append(f"{where}: bad regex {x!r}: {exc}")
        if not str(e["why"]).strip():
            problems.append(f"{where}: why is empty")
        rep = repo / str(e["report"])
        try:
            text = rep.read_text(encoding="utf-8")
        except OSError:
            problems.append(f"{where}: report {e['report']} does not exist")
        else:
            if not re.search(rf"^- \[ \] \*\*{re.escape(str(e['bug']))}:", text, re.M):
                problems.append(f"{where}: {e['report']} has no open todo '- [ ] **{e['bug']}:' "
                                "(fixed? then remove this entry)")
    if problems:
        raise KnownRedError(problems)
    return entries


@dataclass
class Split:
    new: list[str] = field(default_factory=list)       # red nobody has reported: stops the gate
    known: list[str] = field(default_factory=list)     # "<line>  [known red: <bug>, <report>]"
    stale: list[str] = field(default_factory=list)     # entries that no longer match: stop the gate

    @property
    def ok(self) -> bool:
        return not self.new and not self.stale


def split(day: str, failures: list[str], entries: list[dict], *, check_stale: bool = True) -> Split:
    """Sort one day's failure lines into new and known red; find stale entries."""
    mine = [e for e in entries if e["day"] == day]
    out = Split()
    hits = {id(e): 0 for e in mine}
    for line in failures:
        owner = None
        if not NEVER_EXCUSED.match(line):
            owner = next((e for e in mine if any(re.search(x, line) for x in e["excuses"])), None)
        if owner is None:
            out.new.append(line)
        else:
            hits[id(owner)] += 1
            out.known.append(f"{line}  [known red: {owner['bug']}, {owner['report']}]")
    if check_stale:
        for e in mine:
            if hits[id(e)] != e["count"]:
                out.stale.append(f"known-red {day} {e['bug']}: expected {e['count']} failure line(s), "
                                 f"matched {hits[id(e)]} - fixed or changed; edit or remove the entry "
                                 f"(relay/tests/daysim/known-red.json) and close {e['report']}")
    return out
