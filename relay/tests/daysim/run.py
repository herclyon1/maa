#!/usr/bin/env python3
"""daysim: replay recorded days through the relay and judge them (design.md section 5).

    python3.14 -I relay/tests/daysim/run.py --all [--jobs 8] [--chain]
    python3.14 -I relay/tests/daysim/run.py --day 2026-10-12 [--until 10:30] [--keep]

For each day: the machine at 00:00 is materialized from seed.json into a sim tree
(APFS clones of the corpus files), every recorded boot runs as its own
`boot.py` process over that tree, the inputs after the last boot are applied by
an offline pass, and the per-boot outputs are merged into out/<D>/outputs.json,
which oracle.check_day judges against the reviewed days/<D>/expected.json.
A failing day prints expected beside actual; nothing here writes expected.json.

Modes. Gate (default): every day starts from its own seed. Chain (--chain): the
days run in date order and each consecutive day starts from the previous day's
sim state folder (relay state, relay.log, step log) instead of the seeded one;
the inputs (game logs, history, AUTO-MAS config) still come from that day's seed.

Known red (knownred.py, known-red.json): failure lines a reported relay bug causes are
listed per day; a day whose every failure line is listed is KNOWN RED, not FAIL. The exit
code is 1 on any other failure line (new red) and on a listed entry that is stale, expired
or whose report is closed, so the list can only shrink. --strict ignores the list.

Budget: a day over DAY_CAP_S (design.md section 5; re-measured at DAY_CAP_S below) fails. The
cap is on the CPU seconds the day's boot processes spent, not on wall time: this Mac is
shared, and at a load average of 61-196 on its 10 cores (2026-10-13 18:42-18:48) the
10-12 morning took longer than the cap in wall time while doing the same work.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import knownred  # noqa: E402
import oracle  # noqa: E402
import world as W  # noqa: E402

PY = sys.executable
# Outside the repo (lint scans the worktree; a sim tree holds copies of machine files),
# next to the corpus the days are replayed from.
OUT = W.CORPUS_ROOT / "_out"
# design.md section 5's provisional cap was 60 s, set before a day did the machine's work
# (W5 ran with the programs' own files missing). Measured 2026-10-13 with install.py's
# copies planted: 10-12 (18 boots) 127.6 CPU-s, 10-06 (16) 100.2, 10-13 (8) 59.4; starting
# one boot process alone costs about 3 CPU-s (10-12 boot 0: 2.94). The cap is 1.4x the
# largest day.
DAY_CAP_S = 180
# An alerts/ row is written when the push is sent; errwatch paces its pushes 24 s
# apart (errwatch.py), so two minutes keeps a row with its own push.
ALERT_MATCH_S = 120


def day_corpus(day: str) -> Path:
    return W.CORPUS_ROOT / day


def merge(day: str, tree: Path, boot_docs: list[dict]) -> dict:
    """outputs.json (design.md section 2) from the boots' records and the sim state."""
    outs = [o for d in boot_docs for o in d.get("outputs") or []]
    by = {}
    for o in outs:
        by.setdefault(o["kind"], []).append(o)

    def strip(o):
        return {k: v for k, v in o.items() if k != "kind"}

    pushes = [strip(o) for o in by.get("push", [])]
    _games_from_alertlog(tree, pushes)
    reports = [p for p in pushes if p.get("ch") == "serverchan" and str(p.get("title") or "").startswith("📋")]
    ledger_f = tree / W.DATA_REL / "state" / f"ledger-{day}.jsonl"
    ledger = []
    if ledger_f.exists():
        for line in ledger_f.read_text(encoding="utf-8-sig").splitlines():
            try:
                ledger.append(json.loads(line))
            except ValueError:
                pass
    boots = []
    for d in boot_docs:
        b = d["boot"]
        if d.get("offline"):
            continue
        boots.append({"start": W.iso(b["start"]), "end": W.iso(b["end"]), "how": b["how"], "after": b["after"],
                      "version_recorded": b.get("version"), "src": b.get("src_start"), "exit": d.get("exit"),
                      "sim_end": d.get("sim_end"), "real_s": d.get("real_s"), "cpu_s": d.get("cpu_s")})
    return {
        "day": day,
        "boots": boots,
        "pushes": pushes,
        "power": [strip(o) for o in by.get("power", [])],
        "mas_writes": [strip(o) for o in by.get("mas_write", [])],
        "procs": [strip(o) for o in by.get("procs", [])],
        "ledger": ledger,
        "report": reports[-1] if reports else {},
        "log": [x for d in boot_docs for x in d.get("log") or []],
        "states": [strip(o) for o in by.get("phone_state", [])],
        "sim_errors": [strip(o) for o in by.get("sim_error", [])],
        "sim_notes": [strip(o) for o in by.get("sim_note", [])],
        "mas_backend": [strip(o) for o in by.get("mas_backend", [])],
    }


def _games_from_alertlog(tree: Path, pushes: list[dict]) -> None:
    """A group push's game, when its text names none: the relay files every group push in
    state/alerts/<YYYYMMDD>.jsonl with the game it was about (alertlog.py); the WeCom
    message itself does not carry it. Matched by title within ALERT_MATCH_S."""
    rows = []
    for f in sorted((tree / W.DATA_REL / "state" / "alerts").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            try:
                r = json.loads(line)
                ts = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=W.BJ).timestamp()
            except (ValueError, KeyError, TypeError):
                continue
            if r.get("game"):
                rows.append((ts, str(r.get("title") or ""), r["game"]))
    for p in pushes:
        if p.get("ch") != "group" or p.get("game"):
            continue
        t = W.epoch(p["t"])
        hit = [g for ts, title, g in rows if title == p.get("title") and abs(ts - t) <= ALERT_MATCH_S]
        if hit:
            p["game"] = hit[0]


def test_windows(day: str) -> list[tuple[str, str, str]]:
    """The day's test windows (inputs written from the Mac), for invariant 2."""
    events, _ = W.load_day(day)
    open_, got = {}, []
    for ev in events:
        if ev["kind"] == "file" and ev.get("op") == "test_window_open":
            open_[ev["entry"]["since"]] = ev["entry"]
        elif ev["kind"] == "file" and ev.get("op") == "test_window_close":
            e = ev["entry"]
            got.append((e["since"], e["until"], f"test window {e.get('what', '')}"))
            open_.pop(e["since"], None)
    return got


def run_boot(spec: dict, spec_path: Path, log_path: Path) -> dict:
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARK_", "WECOM_", "COS_", "SERVERCHAN"))}
    env.update(W.env_for(Path(spec["tree"])))
    with open(log_path, "wb") as lf:
        rc = subprocess.run([PY, "-I", "-X", "utf8", str(HERE / "boot.py"), str(spec_path)], stdout=lf, stderr=subprocess.STDOUT,
                            env=env, cwd=str(spec["tree"]), check=False).returncode
    out = Path(spec["out"])
    if not out.exists():
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
        return {"boot": spec["boot"], "exit": f"no output (rc {rc})", "offline": spec.get("offline"),
                "outputs": [{"kind": "sim_error", "t": W.iso(spec["boot"]["start"]), "what": "boot process died",
                             "detail": tail}], "log": []}
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc["offline"] = spec.get("offline")
    return doc


def run_day(day: str, *, code: Path, chain_from: "Path | None" = None, until: "str | None" = None,
            keep: bool = False, out_root: Path = OUT) -> dict:
    t_real = time.perf_counter()
    od = out_root / day
    if od.exists():
        shutil.rmtree(od)
    od.mkdir(parents=True)
    tree = od / "tree"
    corpus = day_corpus(day)
    seed = W.materialize(day, tree, corpus, code)
    if chain_from is not None:
        carry(chain_from, tree)
    events, _ = W.load_day(day)
    cut = None
    if until:
        h, m = map(int, until.split(":"))
        cut = (datetime.fromisoformat(seed["t0"]) + timedelta(hours=h, minutes=m)).timestamp()
    boots = W.plan_boots(events, seed, cut)
    docs = []
    for b in boots:
        spec = {"day": day, "tree": str(tree), "corpus": str(corpus), "boot": b, "out": str(od / f"boot-{b['i']:02d}.json")}
        docs.append(run_boot(spec, od / f"boot-{b['i']:02d}.spec.json", od / f"boot-{b['i']:02d}.log"))
    end = cut or W.epoch(seed["t1"])
    off = {"i": len(boots), "start": end, "end": end, "how": "offline", "power_on": end, "after": "", "version": "",
           "relay_poweroff": False}
    spec = {"day": day, "tree": str(tree), "corpus": str(corpus), "boot": off, "offline": True,
            "out": str(od / "offline.json")}
    docs.append(run_boot(spec, od / "offline.spec.json", od / "offline.log"))
    outputs = merge(day, tree, docs)
    real = time.perf_counter() - t_real
    outputs["real_s"] = round(real, 1)
    cpu = sum(float(d.get("cpu_s") or 0) for d in docs)
    outputs["cpu_s"] = round(cpu, 1)
    (od / "outputs.json").write_text(json.dumps(outputs, ensure_ascii=False, indent=1), encoding="utf-8")
    expected = oracle.load_expected(W.DAYS / day / "expected.json")
    if until:
        expected = clip(expected, until)
    res = oracle.check_day(outputs, expected, test_windows=test_windows(day))
    if cpu > DAY_CAP_S and not until:
        res.failures.append(f"budget: {cpu:.1f} s CPU, cap {DAY_CAP_S} s")
        res.lines.append(f"  FAIL budget: {cpu:.1f} s CPU ({real:.1f} s real), cap {DAY_CAP_S} s")
    (od / "judgement.txt").write_text(res.report() + "\n", encoding="utf-8")
    if not keep:
        state = tree / W.DATA_REL / "state"
        keep_dir = od / "final"
        keep_dir.mkdir(exist_ok=True)
        if state.exists():
            shutil.copytree(state, keep_dir / "state", symlinks=True)
        for f in (tree / W.DATA_REL / "relay.log", tree / "_sim" / "steplog.txt", tree / "_sim" / "world.json"):
            if f.exists():
                shutil.copy2(f, keep_dir / f.name)
        shutil.rmtree(tree)
    return {"day": day, "ok": res.ok, "report": res.report(), "failures": list(res.failures), "real_s": real,
            "cpu_s": cpu, "boots": len(boots), "final": (tree if keep else od / "final")}


def clip(expected: dict, until: str) -> dict:
    """A partial day (--until): entries whose time lies after the cut are not judged."""
    d = oracle._day(expected)
    cut = oracle._clock(d, until)
    events, _ = W.load_day(expected["day"])
    ends = {f"{e['dir']}/{e['user']}/{e['stem']}": W.epoch(e["end"]) for e in events if e["kind"] == "run"}
    items = []
    for it in expected["items"]:
        lo, _hi = oracle._span(it, expected)
        if it["kind"] in ("verdict", "ledger"):
            if ends.get(it.get("run", ""), 0) > cut.timestamp():
                continue
        elif lo > cut:
            continue
        items.append(it)
    return {**expected, "items": items}


def carry(prev_final: Path, tree: Path) -> None:
    """Chain mode: the relay's own state, relay.log and the step log from the previous day's run."""
    state = tree / W.DATA_REL / "state"
    src_state = prev_final / "state" if (prev_final / "state").exists() else prev_final / W.DATA_REL / "state"
    if state.exists():
        shutil.rmtree(state)
    shutil.copytree(src_state, state, symlinks=True)
    for name, dst in (("relay.log", tree / W.DATA_REL / "relay.log"), ("steplog.txt", tree / "_sim" / "steplog.txt")):
        src = prev_final / name
        if not src.exists():
            src = prev_final / ("_sim" if name == "steplog.txt" else W.DATA_REL) / name
        if src.exists():
            shutil.copy2(src, dst)
    # ntfy counts per UTC day, and a Beijing night is the end of a UTC day: keep the counts.
    for src in (prev_final / "world.json", prev_final / "_sim" / "world.json"):
        if src.exists():
            counts = json.loads(src.read_text(encoding="utf-8")).get("ntfy_count") or {}
            (tree / "_sim" / "world.json").write_text(json.dumps({"applied": [], "ntfy_count": counts}),
                                                      encoding="utf-8")
            break


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--day", action="append", default=[])
    ap.add_argument("--chain", action="store_true")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--until", help="stop the day at HH:MM (bring-up)")
    ap.add_argument("--keep", action="store_true", help="keep the sim tree")
    ap.add_argument("--code", default=str(W.RELAY), help="the relay code under test (default: this repo's relay/)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--strict", action="store_true", help="ignore known-red.json: every failure line counts")
    ap.add_argument("--known-red", default=str(knownred.KNOWN_RED), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    days = sorted(p.name for p in W.DAYS.iterdir() if (p / "events.jsonl").exists()) if a.all else sorted(a.day)
    if not days:
        ap.error("give --all or --day")
    entries = []
    if not a.strict:
        try:
            entries = knownred.load(Path(a.known_red))
        except knownred.KnownRedError as exc:
            print("known-red.json refused (fix the list before any day runs):")
            for x in exc.args[0]:
                print(f"  - {x}")
            return 1
        if a.all:
            gone = sorted({e["day"] for e in entries} - set(days))
            if gone:
                print(f"known-red.json lists days that have no replay: {', '.join(gone)}")
                return 1
    missing = [d for d in days if not day_corpus(d).is_dir()]
    if missing:
        print(f"no corpus for {', '.join(missing)} under {W.CORPUS_ROOT} (scripts/mac/pull-day.sh)")
        return 2
    code, out_root = Path(a.code), Path(a.out)
    results = []
    if a.chain:
        prev, prev_day = None, None
        for d in days:
            follows = prev_day is not None and \
                (datetime.fromisoformat(d) - datetime.fromisoformat(prev_day)).days == 1
            r = run_day(d, code=code, chain_from=prev if follows else None, until=a.until, keep=a.keep,
                        out_root=out_root / "chain")
            r["chained"] = follows
            results.append(r)
            prev, prev_day = r["final"], d
    else:
        with ThreadPoolExecutor(max(1, a.jobs)) as ex:
            results = list(ex.map(lambda d: run_day(d, code=code, until=a.until, keep=a.keep, out_root=out_root),
                                  days))
    bad = 0
    for r in results:
        print(r["report"])
        print(f"  ({r['boots']} boots, {r['cpu_s']:.1f} s CPU, {r['real_s']:.1f} s real"
              f"{', chained' if r.get('chained') else ''})")
        sp = knownred.split(r["day"], r["failures"], entries, check_stale=not a.until)
        print(f"  verdict {r['day']}: {verdict(sp)}")
        for x in sp.new:
            print(f"    NEW RED: {x}")
        for x in sp.stale:
            print(f"    STALE: {x}")
        bad += not sp.ok
    return 1 if bad else 0


def verdict(sp: "knownred.Split") -> str:
    if sp.new or sp.stale:
        return f"FAIL ({len(sp.new)} new red, {len(sp.stale)} stale known-red)"
    if sp.known:
        bugs = sorted({x.rsplit("[known red: ", 1)[1].split(",", 1)[0] for x in sp.known})
        return f"KNOWN RED only ({len(sp.known)} line(s): {', '.join(bugs)})"
    return "PASS"


if __name__ == "__main__":
    sys.exit(main())
