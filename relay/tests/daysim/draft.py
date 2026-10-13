#!/usr/bin/env python3
"""Draft a day's expected.json from the real record, for a person to review.

    python3.14 -I relay/tests/daysim/draft.py 2026-10-12 --record <record dir> > draft.json

<record dir> is the machine's C:\\ProgramData\\ark-relay as pulled (relay.log and
state/). Exactly three things are read, all written by the relay on the machine on
the day itself (design.md section 3, "Drafting"):

- state/alerts/<YYYYMMDD>.jsonl - every group alarm, as sent (alertlog.py),
- relay.log, the day's push, verdict and shutdown lines,
- state/ledger-<D>.jsonl - the day's booked runs.

The simulator's output is never read, and there is no --update: a draft goes to
stdout and never over an existing expected.json. Every entry comes out
`"review": "unreviewed"` with a suggested rule and the record line it came from as
`src`; oracle.load_expected refuses the file until a reviewer has relabelled each
entry with a rule, a why and a checkable source (the replay README's rule that a
draft must be looked at, applied to whole days).

Everything copied from the record goes through scripts/mac/redact.py, URL query
strings (COS signed links) are dropped and AKID key ids masked.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load_redact():
    spec = importlib.util.spec_from_file_location("ark_redact", REPO / "scripts" / "mac" / "redact.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.redact_text


_redact_text = _load_redact()
_URL = re.compile(r"(https?://[^\s?）)」\"']+)\?[^\s）)」\"']*")
_AKID = re.compile(r"AKID[0-9A-Za-z]+")
_WEBHOOK_KEY = re.compile(r"(?i)(key=)[0-9a-f-]{8,}")


def clean(s: str) -> str:
    """Record text made safe to commit: secrets masked, signed-URL queries dropped."""
    s = _redact_text(str(s))
    s = _URL.sub(r"\1", s)
    s = _AKID.sub("AKIDREDACTED", s)
    return _WEBHOOK_KEY.sub(r"\1REDACTED", s)


def first_clause(text: str, limit: int = 24) -> str:
    """The opening words of a push body: short enough to match on, long enough to mean it."""
    s = clean(text).strip().split("\n", 1)[0]
    s = re.split(r"[，。：；（(]", s, maxsplit=1)[0].strip(" ·")
    return s[:limit]


_LINE = re.compile(r"^(\d\d-\d\d) (\d\d:\d\d:\d\d) +([A-Z]+) +(\S+) +(.*)$")
_RUN = re.compile(r"\d{4}-\d\d-\d\d/\w+/[\w-]+-\d\d-\d\d-\d\d")
_REPORT_INTERIM = re.compile(r"已推送「(.+?)」")
_DEBUG_ON = re.compile(r"调试模式(?:已开启|生效)")
_DEBUG_OFF = re.compile(r"调试模式(?:已关闭|已结束)")
_DEBUG_UNTIL = re.compile(r"至 (?:\d{4}-)?(\d\d-\d\d) (\d\d:\d\d)")


def day_lines(relay_log: Path, d: date):
    """(line number, HH:MM:SS, level, logger, message) of day d (relay.log has no year)."""
    # Split on \n only: messages carry bare \r (34384 in the 10-13 pull), which text
    # mode would count as line ends, and the line numbers would stop matching `sed -n`.
    prefix = d.strftime("%m-%d ").encode()
    with relay_log.open("rb") as fh:
        for n, raw in enumerate(fh, 1):
            if raw.startswith(prefix):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if m := _LINE.match(line):
                    yield n, m[2], m[3], m[4], m[5]


def _item(kind: str, rule: str, src: str, **f) -> dict:
    it = {"id": "", "kind": kind, "rule": rule, "review": "unreviewed", "why": "", "src": src}
    it.update({k: v for k, v in f.items() if v not in (None, "", [])})
    return it


def draft(d: date, record: Path) -> dict:
    relay_log = record / "relay.log"
    alerts = record / "state" / "alerts" / f"{d:%Y%m%d}.jsonl"
    ledger = record / "state" / f"ledger-{d.isoformat()}.jsonl"
    items: list[tuple[str, dict]] = []
    guards: list[dict] = []
    md = d.strftime("%m-%d")

    if alerts.exists():
        for n, line in enumerate(alerts.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            hms = str(row.get("ts", ""))[11:19]
            items.append((hms, _item("push", "must", f"alerts/{d:%Y%m%d}.jsonl:{n}", ch="group",
                                     at=hms[:5], tol_min=10, game=row.get("game") or None,
                                     title_has=clean(row.get("title", "")),
                                     text_has=[first_clause(row.get("text", ""))] if row.get("text") else None)))

    booked: set[str] = set()
    if ledger.exists():
        for n, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            rid = row.get("run_id", "")
            booked.add(rid)
            raw = row.get("raw") or {}
            fails = [first_clause(x) for x in row.get("failed_tasks") or []][:2]
            fails += [first_clause(v) for k, v in raw.items() if str(k).endswith("_error")][:1]
            hms = str(row.get("finished") or row.get("started") or "")[11:19]
            src = f"ledger-{d.isoformat()}.jsonl:{n}"
            items.append((hms, _item("verdict", "must", src, run=rid,
                                     status="ok" if row.get("ok") else "failed", failed_has=fails)))
            if raw.get("hand_started"):
                guards.append({"from": str(row.get("started"))[11:19], "to": hms,
                               "what": f"hand-started run {rid}", "src": src})

    debug_from = None
    if relay_log.exists():
        for n, hms, level, logger, msg in day_lines(relay_log, d):
            src = f"relay.log {md} {hms} (line {n})"
            at = hms[:5]
            if level in ("ERROR", "CRITICAL"):
                items.append((hms, _item("log", "must", src, at=at, tol_min=5, level=level,
                                         logger=logger, line_has=first_clause(msg, 40))))
            if logger == "ark.report":
                if m := _REPORT_INTERIM.search(msg):
                    items.append((hms, _item("push", "must", src, ch="serverchan", at=at,
                                             tol_min=10, title_has=f"（{m[1]}）")))
                elif "日报已推送" in msg or "日报已补发" in msg:
                    items.append((hms, _item("report", "must", src, at=at, tol_min=15, title_has="📋")))
                elif "不推速览" in msg:
                    items.append((hms, _item("push", "must_not", src, ch="serverchan", at=at,
                                             tol_min=10, title_has="🔎")))
            elif logger == "ark.engine" and "60 秒后关机" in msg:
                items.append((hms, _item("power", "must", src, at=at, tol_min=10, cmd_has="/s")))
            elif logger == "ark.shutdown" and ("这一次关机已跳过" in msg or "用掉了" in msg):
                items.append((hms, _item("log", "must", src, at=at, tol_min=5, logger=logger,
                                         line_has=first_clause(msg, 30))))
            elif logger == "ark.handle" and (m := _RUN.search(msg)) and m[0] not in booked:
                booked.add(m[0])
                items.append((hms, _item("ledger", "must", src, run=m[0],
                                         note=clean(msg)[:120])))
            if _DEBUG_ON.search(msg) and "不推送" not in msg and debug_from is None:
                u = _DEBUG_UNTIL.search(msg)
                until = f"{u[2]}:00" if u and u[1] == md else "24:00"
                debug_from = (hms, src, until)
            elif _DEBUG_OFF.search(msg) and "不推送" not in msg and debug_from:
                guards.append({"from": debug_from[0], "to": min(hms, debug_from[2]),
                               "what": "debug mode", "src": f"{debug_from[1]}; {src}"})
                debug_from = None
    if debug_from:
        guards.append({"from": debug_from[0], "to": debug_from[2], "what": "debug mode (no end line)",
                       "src": debug_from[1]})

    items.sort(key=lambda x: x[0])
    out = []
    for i, (_, it) in enumerate(items, 1):
        it["id"] = f"{d:%m%d}-{i:02d}"
        out.append(it)
    return {"day": d.isoformat(), "scope": {"from": "00:00", "to": "24:00"},
            "notes": "DRAFT from the real record; review every entry (oracle.py refuses unreviewed ones).",
            "guards": guards, "items": out}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], allow_abbrev=False)
    ap.add_argument("day", help="Beijing day, YYYY-MM-DD")
    ap.add_argument("--record", required=True, type=Path,
                    help="the pulled C:\\ProgramData\\ark-relay (relay.log, state/)")
    args = ap.parse_args(argv)
    if not (args.record / "relay.log").exists():
        print(f"no relay.log under {args.record}", file=sys.stderr)
        return 2
    doc = draft(date.fromisoformat(args.day), args.record)
    sys.stdout.write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
