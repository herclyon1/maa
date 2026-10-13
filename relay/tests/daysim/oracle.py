#!/usr/bin/env python3
"""The day replay's oracle: what a simulated day must and must not produce.

`days/<D>/expected.json` holds the reviewed expectations for Beijing day D; the
simulator (run.py) writes `out/<D>/outputs.json` (design.md section 2, "Interfaces
fixed now"). This module

- loads expected.json and refuses an entry that is unreviewed or has no checkable
  source (`load_expected`, `validate`),
- matches outputs against the entries, strictly: a group / Server酱 push, a power
  command or a relay.log ERROR that no `must` or `may` entry accounts for fails
  the day (`check_day`),
- runs the five invariants every day must hold, whatever the entries say
  (`invariants`),
- and refuses a silent change between two versions of a day's file: an entry that
  disappears or changes its rule has to carry `was` (`drift`).

A failing day is printed expected beside actual. Nothing here ever writes an
expected.json: there is no "accept the actual output" path (design.md section 3,
"No drift").

Entry shape (one object in `items`):

    {"id": "1012-07", "kind": "push", "ch": "group", "at": "11:49", "tol_min": 10,
     "game": "鸣潮", "title_has": "没干完", "text_has": ["周本"], "rule": "must",
     "review": "reviewed", "why": "...", "src": "errors R32; f912c1f0"}

kinds: push, verdict, ledger, report, power, mas_write, log; rules: must,
must_not, may, dropped (a removed entry, kept with `was`). Time is `at` (+ tol_min)
or `window` [from, to], both Beijing "HH:MM[:SS]" on day D; neither means the
whole scope. `log` is a kind this file adds to the design's list: the R21 tail
(debug mode spending the power-off skip at boot) shows only as a shutdown-decision
line, which outputs.json carries in `log`.

CLI (python3.14 -I):
    oracle.py schema [expected.json ...]     every file (default: all days) loads
    oracle.py judge <outputs.json> <expected.json>
    oracle.py drift <old expected.json> <new expected.json>
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAYS = HERE / "days"
REPO = HERE.parents[2]
USER_SWITCHES = REPO / "relay" / "USER-SWITCHES.txt"

BEIJING = timezone(timedelta(hours=8))

KINDS = ("push", "verdict", "ledger", "report", "power", "mas_write", "log")
RULES = ("must", "must_not", "may", "dropped")
CHANNELS = ("group", "wecom_app", "serverchan", "ntfy", "mac")
# The channels whose every push must be accounted for by an entry (design.md
# section 3, "Strict"): what reaches a person's phone as a notification.
STRICT_CHANNELS = ("group", "serverchan")

# Default tolerance of `at`, minutes: design.md section 3's example entry.
DEFAULT_TOL_MIN = 10

# Invariant 3: ntfy.sh's free tier allows 250 messages per day per IP, counted per
# UTC day (errors-table R08; docs/ERROR-LEDGER-1010.md kinds 24 and 30; the quota
# day is the UTC day: https://docs.ntfy.sh/publish/#limitations).
NTFY_DAILY_LIMIT = 250

# Invariant 4: errwatch pushes each ERROR line to the group from its own queue,
# paced about 24 s apart (errwatch.py:556, design.md section 1); a burst of 20
# lines drains in 8 minutes. An ERROR logged while the machine goes down is
# pushed at the next boot (alerts/20261006.jsonl:5, the 06:21:36 line pushed
# 08:45:18), so a boot after the line opens a second window of the same length.
ERROR_PUSH_MIN = 10

# Invariant 1: a held failure is pushed once AUTO-MAS's retries are over, which
# can be its per-script time limit after the failed attempt (shutdown.py
# RETRY_LINK_H = 4 hours, from ScriptConfig.json read 2026-10-01).
FAILED_PUSH_H = 4

# The game names the pushes use (alertlog.py), by the script AUTO-MAS runs.
GAME_OF_SCRIPT = {"MAA": "明日方舟", "MaaEnd": "终末地", "OK-WW": "鸣潮"}

_COMMON = {"id", "kind", "rule", "review", "why", "src", "at", "tol_min", "window", "was",
           "run", "game", "note"}
_FIELDS = {
    "push": {"ch", "title_has", "text_has"},
    "verdict": {"status", "failed_has"},
    "ledger": set(),
    "report": {"title_has", "text_has"},
    "power": {"cmd_has"},
    "mas_write": {"has"},
    "log": {"level", "logger", "line_has"},
}
_REQUIRED = {
    "push": ("ch",),
    "verdict": ("run", "status"),
    "ledger": ("run",),
    "log": ("line_has",),
}
_TOP = {"day", "scope", "notes", "guards", "items"}

# Checkable source tokens. A source has to name at least one thing a reader can
# open and check; 「待核」 alone (an owner quote not found yet) is not one.
_ROW = re.compile(r"\b[REAC]\d{2}\b")                       # errors-table row
_KIND = re.compile(r"ERROR-LEDGER(?:-1010)?(?:\.md)? kinds? \d+")
_SHA = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![0-9A-Za-z])")
_SWITCH = re.compile(r"USER-SWITCHES\.txt:(\d+)")
_RECORD = re.compile(
    r"alerts/\d{8}\.jsonl:\d+"
    r"|ledger-\d{4}-\d\d-\d\d\.jsonl(?:\.bak[\w.-]*)?(?::\d+)?"
    r"|relay\.log \d\d-\d\d \d\d:\d\d(?::\d\d)?"
    r"|(?:报错台账|被指出)\.txt(?::\d+)? \d\d-\d\d \d\d:[\dx]{2}"
    r"|test-windows\.json"
    r"|history/\d{4}-\d\d-\d\d/\w+/[\w.-]+\.json"
    r"|docs/[\w./-]+\.md"
    r"|design\.md")
_CODE = re.compile(r"\b[\w/]+\.py:[A-Za-z_][\w.]*")
_HHMM = re.compile(r"^(\d\d):(\d\d)(?::(\d\d))?$")


class OracleError(ValueError):
    """An expected.json the loader refuses; `.problems` lists every reason."""

    def __init__(self, path, problems: list[str]):
        super().__init__(f"{path}: " + "; ".join(problems))
        self.problems = problems


# ---------------------------------------------------------------- loading

def _checkable(src: str) -> bool:
    return any(p.search(src) for p in (_ROW, _KIND, _SHA, _SWITCH, _RECORD, _CODE))


def _fix_or_normal(src: str) -> bool:
    """A must_not says why the thing must not happen: the error row, ledger kind or
    commit that fixed it, or the USER-SWITCHES.txt line that makes it a normal state."""
    return any(p.search(src) for p in (_ROW, _KIND, _SHA, _SWITCH))


def _hhmm_ok(v) -> bool:
    if not isinstance(v, str):
        return False
    if v == "24:00":
        return True
    m = _HHMM.match(v)
    return bool(m) and int(m[1]) < 24 and int(m[2]) < 60 and int(m[3] or 0) < 60


def _switch_lines() -> list[str]:
    try:
        return USER_SWITCHES.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _missing_commits(shas: set[str]) -> set[str]:
    """The cited shas this repository does not have (empty when git is not there)."""
    if not shas:
        return set()
    try:
        out = subprocess.run(["git", "-C", str(REPO), "cat-file", "--batch-check"],
                             input="\n".join(sorted(shas)) + "\n", capture_output=True,
                             text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.split()[0] for line in out.splitlines() if line.endswith(" missing")}


def _item_problems(it, seen: set[str], switches: list[str], shas: set[str]) -> list[str]:
    if not isinstance(it, dict):
        return [f"entry is not an object: {it!r}"[:120]]
    iid = it.get("id")
    who = f"entry {iid!r}"
    bad = []
    if not isinstance(iid, str) or not iid:
        bad.append(f"{who}: no id")
    elif iid in seen:
        bad.append(f"{who}: id used twice")
    seen.add(str(iid))
    kind, rule = it.get("kind"), it.get("rule")
    if kind not in KINDS:
        return bad + [f"{who}: kind {kind!r} is not one of {KINDS}"]
    if unknown := set(it) - _COMMON - _FIELDS[kind]:
        bad.append(f"{who}: unknown field(s) {sorted(unknown)} for kind {kind}")
    if it.get("review") != "reviewed":
        bad.append(f"{who}: review is {it.get('review')!r}, not 'reviewed' (draft entries are refused)")
    if rule not in RULES:
        bad.append(f"{who}: rule {rule!r} is not one of {RULES}")
    if not str(it.get("why") or "").strip():
        bad.append(f"{who}: no why")
    src = str(it.get("src") or "").strip()
    if not src:
        bad.append(f"{who}: no src")
    elif not _checkable(src):
        bad.append(f"{who}: src {src!r} names nothing checkable (error row, ledger kind, "
                   "commit, USER-SWITCHES.txt:<line>, record file:line, file.py:function)")
    elif rule == "must_not" and not _fix_or_normal(src):
        bad.append(f"{who}: a must_not cites the fix (error row / ERROR-LEDGER kind / commit) "
                   "or the USER-SWITCHES.txt line that makes it normal")
    for m in _SWITCH.finditer(src):
        # A line shifted by an insertion above it would point at another rule, or
        # at the header: the cited line must still be an entry (file | what | ...).
        n = int(m[1])
        if not 1 <= n <= len(switches):
            bad.append(f"{who}: USER-SWITCHES.txt has no line {n}")
        elif " | " not in switches[n - 1] or switches[n - 1].startswith("#"):
            bad.append(f"{who}: USER-SWITCHES.txt:{n} is not an entry line (did the file shift?)")
    shas.update(_SHA.findall(src))
    if "was" in it or rule == "dropped":
        was = it.get("was")
        if not (isinstance(was, dict) and was.get("rule") in RULES
                and str(was.get("reason") or "").strip()):
            bad.append(f"{who}: `was` must be {{rule, reason}} (needed for a dropped entry)")
    return bad + _shape_problems(it, who, kind)


def _shape_problems(it: dict, who: str, kind: str) -> list[str]:
    """The kind's required fields, channel, status, times and match lists."""
    bad = []
    for need in _REQUIRED.get(kind, ()):
        if it.get(need) in (None, "", []):
            bad.append(f"{who}: kind {kind} needs {need}")
    if kind == "push" and it.get("ch") not in CHANNELS:
        bad.append(f"{who}: ch {it.get('ch')!r} is not one of {CHANNELS}")
    if kind == "verdict" and it.get("status") not in ("ok", "failed"):
        bad.append(f"{who}: status must be ok or failed")
    if "at" in it and "window" in it:
        bad.append(f"{who}: give at or window, not both")
    if "at" in it and not _hhmm_ok(it["at"]):
        bad.append(f"{who}: at {it['at']!r} is not HH:MM[:SS]")
    if "window" in it:
        w = it["window"]
        if not (isinstance(w, list) and len(w) == 2 and all(_hhmm_ok(x) for x in w) and w[0] < w[1]):
            bad.append(f"{who}: window must be [from, to] HH:MM with from < to")
    if "tol_min" in it and not (isinstance(it["tol_min"], int) and it["tol_min"] >= 0):
        bad.append(f"{who}: tol_min must be a whole number of minutes")
    for k in ("text_has", "failed_has", "line_has"):
        v = it.get(k)
        if v is not None and not (isinstance(v, str) and v) and not (
                isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)):
            bad.append(f"{who}: {k} must be a non-empty string or list of strings")
    return bad


def validate(doc) -> list[str]:
    """Every reason the loader refuses this expected.json document ([] = loads)."""
    if not isinstance(doc, dict):
        return ["the file is not a JSON object"]
    bad = [f"unknown top-level field {k!r}" for k in sorted(set(doc) - _TOP)]
    try:
        date.fromisoformat(str(doc.get("day")))
    except ValueError:
        bad.append(f"day {doc.get('day')!r} is not YYYY-MM-DD")
    scope = doc.get("scope", {"from": "00:00", "to": "24:00"})
    if not (isinstance(scope, dict) and _hhmm_ok(scope.get("from")) and _hhmm_ok(scope.get("to"))):
        bad.append("scope must be {from, to} HH:MM")
    switches, shas, seen = _switch_lines(), set(), set()
    for g in doc.get("guards", []):
        if not (isinstance(g, dict) and _hhmm_ok(g.get("from")) and _hhmm_ok(g.get("to"))
                and str(g.get("what") or "").strip() and _checkable(str(g.get("src") or ""))):
            bad.append(f"guard {g!r} needs from, to, what and a checkable src"[:200])
    items = doc.get("items")
    if not isinstance(items, list) or not items:
        bad.append("no items")
        items = []
    for it in items:
        bad += _item_problems(it, seen, switches, shas)
    bad += [f"commit {s} cited in a src is not in this repository" for s in sorted(_missing_commits(shas))]
    return bad


def load_expected(path) -> dict:
    """The reviewed expectations of one day; OracleError when any entry is refused."""
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OracleError(path, [f"unreadable: {exc}"]) from exc
    if problems := validate(doc):
        raise OracleError(path, problems)
    return doc


def drift(old: dict, new: dict) -> list[str]:
    """Entries that changed rule or disappeared between two versions without `was`.

    design.md section 3: turning a must into must_not, or deleting an entry, keeps a
    `was` with the old rule and the reason, so the change is reviewed in the diff."""
    olds = {it.get("id"): it for it in old.get("items", []) if isinstance(it, dict)}
    news = {it.get("id"): it for it in new.get("items", []) if isinstance(it, dict)}
    bad = []
    for iid, o in olds.items():
        n = news.get(iid)
        if n is None:
            bad.append(f"entry {iid!r} was deleted; keep it with rule 'dropped' and `was`")
        elif n.get("rule") != o.get("rule"):
            was = n.get("was")
            if not (isinstance(was, dict) and was.get("rule") == o.get("rule")
                    and str(was.get("reason") or "").strip()):
                bad.append(f"entry {iid!r} changed rule {o.get('rule')} -> {n.get('rule')} "
                           f"without was={{rule: {o.get('rule')!r}, reason}}")
    return bad


# ---------------------------------------------------------------- matching

def _day(expected: dict) -> date:
    return date.fromisoformat(expected["day"])


def _clock(d: date, hhmm: str) -> datetime:
    if hhmm == "24:00":
        return datetime.combine(d + timedelta(days=1), time(0), BEIJING)
    m = _HHMM.match(hhmm)
    return datetime.combine(d, time(int(m[1]), int(m[2]), int(m[3] or 0)), BEIJING)


def when(v, d: date) -> datetime | None:
    """An output's time as a Beijing datetime: ISO (naive = Beijing), "HH:MM[:SS]" on
    day d, "MM-DD HH:MM:SS" (relay.log), or epoch seconds."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, BEIJING)
    s = str(v).strip()
    if _HHMM.match(s):
        return _clock(d, s)
    m = re.match(r"^(\d\d)-(\d\d)[ T](\d\d:\d\d:\d\d)", s)
    if m:
        return _clock(date(d.year, int(m[1]), int(m[2])), m[3])
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=BEIJING)).astimezone(BEIJING)


def _span(it: dict, expected: dict) -> tuple[datetime, datetime]:
    d = _day(expected)
    if "at" in it:
        at = _clock(d, it["at"])
        tol = timedelta(minutes=it.get("tol_min", DEFAULT_TOL_MIN))
        return at - tol, at + tol
    if "window" in it:
        return _clock(d, it["window"][0]), _clock(d, it["window"][1])
    scope = expected.get("scope", {"from": "00:00", "to": "24:00"})
    return _clock(d, scope["from"]), _clock(d, scope["to"])


def _as_list(v) -> list[str]:
    return [] if v is None else [v] if isinstance(v, str) else list(v)


_LOG_LINE = re.compile(r"^(?:\d{4}-)?(\d\d-\d\d) (\d\d:\d\d:\d\d)(?:[.,]\d+)?\s+([A-Z]+)\s+(\S+)\s+(.*)$", re.S)


def log_record(entry, d: date) -> dict:
    """One outputs.log entry as {t, level, logger, msg}: a relay.log line or a dict."""
    if isinstance(entry, dict):
        msg = entry.get("msg") or entry.get("text") or entry.get("line") or ""
        return {"t": when(entry.get("t"), d), "level": str(entry.get("level") or ""),
                "logger": str(entry.get("logger") or ""), "msg": str(msg)}
    s = str(entry)
    m = _LOG_LINE.match(s)
    if not m:
        return {"t": None, "level": "", "logger": "", "msg": s}
    return {"t": when(f"{m[1]} {m[2]}", d), "level": m[3], "logger": m[4], "msg": m[5]}


def _run_matches(want: str, run_id: str) -> bool:
    return bool(run_id) and (run_id == want or run_id.endswith("/" + want))


def _failed_text(row: dict) -> str:
    raw = row.get("raw") or {}
    parts = [str(x) for x in row.get("failed_tasks") or []]
    parts += [str(v) for k, v in raw.items() if str(k).endswith("_error")]
    return "\n".join(parts)


@dataclass
class Out:
    """One output the matcher looks at."""
    kind: str
    t: datetime | None
    data: dict
    label: str
    strict: bool = False
    claimed: list[str] = field(default_factory=list)


def collect(outputs: dict, d: date) -> list[Out]:
    """Every output of the day, flattened and labelled for the report."""
    outs: list[Out] = []
    for p in outputs.get("pushes") or []:
        ch = p.get("ch")
        outs.append(Out("push", when(p.get("t"), d), p,
                        f"push {ch} {p.get('t')} {p.get('title')!r}", strict=ch in STRICT_CHANNELS))
    rep = outputs.get("report")
    if isinstance(rep, dict) and rep:
        outs.append(Out("report", when(rep.get("t"), d), rep, f"report {rep.get('t')} {rep.get('title')!r}"))
    for p in outputs.get("power") or []:
        outs.append(Out("power", when(p.get("t"), d), p, f"power {p.get('t')} {p.get('cmd')!r}", strict=True))
    for r in outputs.get("ledger") or []:
        outs.append(Out("ledger", when(r.get("finished") or r.get("started"), d), r,
                        f"ledger {r.get('run_id')} ok={r.get('ok')}"))
    for w in outputs.get("mas_writes") or []:
        w = w if isinstance(w, dict) else {"what": w}
        outs.append(Out("mas_write", when(w.get("t"), d), w, f"mas_write {json.dumps(w, ensure_ascii=False)[:120]}"))
    for line in outputs.get("log") or []:
        rec = log_record(line, d)
        outs.append(Out("log", rec["t"], rec, f"log {rec['t']:%H:%M:%S} {rec['level']} {rec['logger']} {rec['msg'][:100]!r}"
                        if rec["t"] else f"log {rec['msg'][:100]!r}", strict=rec["level"] in ("ERROR", "CRITICAL")))
    return outs


def _game_ok(it: dict, data: dict) -> bool:
    g = it.get("game")
    if not g:
        return True
    if data.get("game"):
        return data["game"] == g
    return g in f"{data.get('title') or ''}\n{data.get('text') or ''}"


def _matches(it: dict, o: Out, expected: dict) -> bool:
    kind = it["kind"]
    if kind == "report":
        is_report = o.kind == "report" or (
            o.kind == "push" and o.data.get("ch") == "serverchan"
            and str(o.data.get("title") or "").startswith("📋"))
        if not is_report:
            return False
    elif kind in ("verdict", "ledger"):
        if o.kind != "ledger":
            return False
    elif o.kind != kind:
        return False
    if kind not in ("verdict", "ledger"):
        lo, hi = _span(it, expected)
        if o.t is None or not lo <= o.t <= hi:
            return False
    data = o.data
    if kind in ("push", "report"):
        if kind == "push" and data.get("ch") != it["ch"]:
            return False
        if not _game_ok(it, data):
            return False
        if it.get("title_has") and it["title_has"] not in str(data.get("title") or ""):
            return False
        return all(x in str(data.get("text") or "") for x in _as_list(it.get("text_has")))
    if kind in ("verdict", "ledger"):
        if not _run_matches(it["run"], str(data.get("run_id") or "")):
            return False
        if kind == "ledger":
            return True
        if (it["status"] == "ok") != bool(data.get("ok")):
            return False
        return all(x in _failed_text(data) for x in _as_list(it.get("failed_has")))
    if kind == "power":
        return all(x in str(data.get("cmd") or "") for x in _as_list(it.get("cmd_has") or "/s"))
    if kind == "mas_write":
        blob = json.dumps(data, ensure_ascii=False)
        return all(x in blob for x in _as_list(it.get("has")))
    if kind == "log":
        if it.get("level") and data["level"] != it["level"]:
            return False
        if it.get("logger") and data["logger"] != it["logger"]:
            return False
        return all(x in data["msg"] for x in _as_list(it.get("line_has")))
    return False


def _describe(it: dict) -> str:
    keys = ("kind", "ch", "run", "status", "at", "tol_min", "window", "game", "title_has",
            "text_has", "failed_has", "cmd_has", "line_has", "has")
    return " ".join(f"{k}={it[k]!r}" for k in keys if k in it)


def _near(it: dict, outs: list[Out], expected: dict) -> list[str]:
    """Outputs of the entry's kind near its time, to print beside a missed must."""
    want = {"verdict": "ledger", "report": "push"}.get(it["kind"], it["kind"])
    lo, hi = _span(it, expected)
    lo, hi = lo - timedelta(hours=1), hi + timedelta(hours=1)
    near = [o.label for o in outs if o.kind in (want, it["kind"])
            and (o.t is None or lo <= o.t <= hi or it["kind"] in ("verdict", "ledger"))]
    return near[:8] or ["(nothing of this kind near that time)"]


# ---------------------------------------------------------------- invariants

def _windows(spans, d: date) -> list[tuple[datetime, datetime, str]]:
    got = []
    for s in spans or ():
        if isinstance(s, dict):
            a, b, what = s.get("from") or s.get("since"), s.get("to") or s.get("until"), s.get("what", "")
        else:
            a, b, what = s[0], s[1], (s[2] if len(s) > 2 else "")
        ta, tb = when(a, d), when(b, d)
        if ta and tb:
            got.append((ta, tb, str(what)))
    return got


def _boot_starts(outputs: dict, d: date) -> list[datetime]:
    got = []
    for b in outputs.get("boots") or []:
        v = b if not isinstance(b, dict) else (b.get("start") or b.get("t") or b.get("relay_start") or b.get("at"))
        if (t := when(v, d)) is not None:
            got.append(t)
    return sorted(got)


def invariants(outputs: dict, expected: dict, *, test_windows=(), debug_windows=()) -> list[str]:
    """The five checks every day holds (design.md section 3, "Invariants").

    test_windows / debug_windows: extra guard spans [(from, to, what)] the caller has
    from the day's inputs; expected.json's reviewed `guards` always apply."""
    d = _day(expected)
    bad = []
    outs = collect(outputs, d)
    pushes = [o for o in outs if o.kind == "push"]
    group = [o for o in pushes if o.data.get("ch") == "group" and o.t is not None]
    covers = {str(it.get("run")) for it in expected.get("items", [])
              if it.get("rule") == "must_not" and it.get("run")}

    # (1) every ledger row judged failed has a group push, unless a sourced
    # must_not on that run says why not.
    for r in outputs.get("ledger") or []:
        if r.get("ok") is not False:
            continue
        rid = str(r.get("run_id") or "")
        if any(_run_matches(c, rid) for c in covers):
            continue
        stem = rid.rsplit("/", 1)[-1]
        game = GAME_OF_SCRIPT.get(str(r.get("script") or stem.rsplit("-", 3)[0]), "")
        end = when(r.get("finished") or r.get("started"), d)
        pushed = any(stem and stem in f"{o.data.get('title')}\n{o.data.get('text')}" for o in group) or any(
            end and end <= o.t <= end + timedelta(hours=FAILED_PUSH_H) and _game_ok({"game": game}, o.data)
            for o in group if game)
        if not pushed:
            bad.append(f"invariant 1: ledger row {rid} is failed ({r.get('failed_tasks')}) "
                       "and no group push names it; no must_not entry covers that run")

    # (2) no `shutdown /s` while a test window, a hand-started run or debug mode is open.
    guards = _windows(expected.get("guards"), d) + _windows(test_windows, d) + _windows(debug_windows, d)
    for r in outputs.get("ledger") or []:
        if (r.get("raw") or {}).get("hand_started"):
            a, b = when(r.get("started"), d), when(r.get("finished"), d)
            if a and b:
                guards.append((a, b, f"hand-started run {r.get('run_id')}"))
    for o in outs:
        if o.kind == "power" and "/s" in str(o.data.get("cmd") or "") and o.t is not None:
            for a, b, what in guards:
                if a <= o.t <= b:
                    bad.append(f"invariant 2: {o.label} while {what} was open ({a:%H:%M:%S}-{b:%H:%M:%S})")

    # (3) at most NTFY_DAILY_LIMIT ntfy publishes per UTC day.
    per_day: dict[str, int] = {}
    for o in pushes:
        if o.data.get("ch") == "ntfy" and o.t is not None:
            k = o.t.astimezone(timezone.utc).strftime("%Y-%m-%d")
            per_day[k] = per_day.get(k, 0) + 1
    for k, n in sorted(per_day.items()):
        if n > NTFY_DAILY_LIMIT:
            bad.append(f"invariant 3: {n} ntfy publishes on UTC day {k} (limit {NTFY_DAILY_LIMIT})")

    # (4) no relay.log ERROR without a group push after it.
    boots = _boot_starts(outputs, d)
    win = timedelta(minutes=ERROR_PUSH_MIN)
    for o in outs:
        if o.kind != "log" or o.data["level"] not in ("ERROR", "CRITICAL"):
            continue
        if o.t is None:
            bad.append(f"invariant 4: ERROR line without a time: {o.label}")
            continue
        starts = [o.t] + [b for b in boots if b > o.t][:1]
        if not any(s <= p.t <= s + win for s in starts for p in group):
            bad.append(f"invariant 4: {o.label} has no group push within {ERROR_PUSH_MIN} min "
                       "(nor within that long of the next boot)")

    # (5) no sim error.
    for e in outputs.get("sim_errors") or []:
        bad.append(f"invariant 5: sim error: {e}")
    return bad


# ---------------------------------------------------------------- the day

@dataclass
class Result:
    day: str
    failures: list[str]
    lines: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures

    def report(self) -> str:
        head = f"{'PASS' if self.ok else 'FAIL'} {self.day}"
        return "\n".join([head, *self.lines])


def check_day(outputs: dict, expected: dict, *, test_windows=(), debug_windows=()) -> Result:
    """Judge one simulated day against its reviewed expected.json (already loaded)."""
    d = _day(expected)
    outs = collect(outputs, d)
    failures, lines = [], []
    for it in expected.get("items", []):
        rule = it.get("rule")
        if rule == "dropped":
            continue
        hits = [o for o in outs if _matches(it, o, expected)]
        for o in hits:
            o.claimed.append(f"{it['id']}:{rule}")
        if rule == "must" and not hits:
            msg = f"{it['id']} must, missing: {_describe(it)}"
            failures.append(msg)
            lines += [f"  FAIL {msg}", f"       why: {it.get('why')} [{it.get('src')}]",
                      *(f"       actual near it: {x}" for x in _near(it, outs, expected))]
        elif rule == "must_not" and hits:
            msg = f"{it['id']} must_not, happened: {_describe(it)}"
            failures.append(msg)
            lines += [f"  FAIL {msg}", f"       why: {it.get('why')} [{it.get('src')}]",
                      *(f"       actual: {o.label}" for o in hits)]
        else:
            lines.append(f"  ok   {it['id']} {rule} ({len(hits)} matched)")
    for o in outs:
        if o.strict and not any(c.endswith((":must", ":may")) for c in o.claimed):
            if any(c.endswith(":must_not") for c in o.claimed):
                continue        # already a failure of that must_not
            msg = f"strict: no entry expects {o.label}"
            failures.append(msg)
            lines.append(f"  FAIL {msg}")
    for msg in invariants(outputs, expected, test_windows=test_windows, debug_windows=debug_windows):
        failures.append(msg)
        lines.append(f"  FAIL {msg}")
    return Result(expected["day"], failures, lines)


def all_days() -> list[Path]:
    return sorted(DAYS.glob("*/expected.json"))


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("schema", "judge", "drift"):
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "schema":
        paths = [Path(a) for a in args] or all_days()
        bad = 0
        for p in paths:
            try:
                doc = load_expected(p)
            except OracleError as exc:
                bad += 1
                print(f"REFUSED {p}")
                for x in exc.problems:
                    print(f"  - {x}")
            else:
                print(f"ok {p} ({len(doc['items'])} entries)")
        return 1 if bad else 0
    if cmd == "judge" and len(args) == 2:
        outputs = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        res = check_day(outputs, load_expected(args[1]))
        print(res.report())
        return 0 if res.ok else 1
    if cmd == "drift" and len(args) == 2:
        old, new = (json.loads(Path(a).read_text(encoding="utf-8")) for a in args)
        problems = drift(old, new)
        for x in problems:
            print(f"  - {x}")
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
