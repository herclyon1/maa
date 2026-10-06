#!/usr/bin/env python3
"""Judge every evidence-bucket run record with two relay versions and list where they differ.

    relay-judge-diff.py --old <relay dir> --new <relay dir> [--evidence DIR] [--stage DIR]

<relay dir> is the `relay/` folder of a checkout (a worktree at the old and at
the new commit). The records are the ones `scripts/mac/evidence.sh list` shows:
every run_id in the mirrored index `<evidence>/index.jsonl`, fetched beforehand
with `evidence.sh pull <run_id>` into `<evidence>/<run_id with / as _>/`.

Each record is staged once, in the layout the relay reads on the machine, and
the same staged tree is fed to both versions:

    <stage>/<run>/history/<date>/<account>/<stem>.json + .log   (history_root)
    <stage>/<run>/debug/app.log        AUTO-MAS app.log (collector._automas_result_time)
    <stage>/<run>/maaend/debug/...     MaaEnd's own logs from the bundle (maaend_dir)

Each version runs in its own process (cwd = its relay dir) and judges every
record with `collector.parse_record`, snapshotted by that version's own
`tests/test_replay.snapshot` (ok, failed_tasks, duration_known and the raw
fields test_replay compares), plus, for OK-WW, `replay.okww_pushes` - the
outcome check engine._verify_outcome runs over the same log.

Output: per date, how many runs the index lists, how many were fetched and
compared, how many judged the same; then every record judged differently, with
both judgements and the log lines that carry the differing text. Also which
ark_relay source files the judging loaded, and whether each is byte-identical
in the two versions.

Read-only towards the machine and the bucket: nothing is fetched or uploaded
here, and nothing under relay/tests/replay is written.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

# Runs inside each version's process. Reads jobs from stdin, prints one JSON
# object: {"results": {run: snapshot|None|{"error": ...}}, "modules": [files]}.
HELPER = r'''
import importlib.util, json, multiprocessing, os, sys, traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

RELAY = Path.cwd()
sys.path.insert(0, str(RELAY))
from ark_relay import collector, replay  # noqa: E402

spec = importlib.util.spec_from_file_location("tr", RELAY / "tests" / "test_replay.py")
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


def judge(job):
    try:
        js = Path(job["json"])
        rec = collector.parse_record(js, Path(job["history_root"]),
                                     Path(job["maaend_dir"]) if job.get("maaend_dir") else None)
        if rec is None:
            return None
        out = tr.snapshot(rec)
        if rec.script == "OK-WW" and js.with_suffix(".log").exists():
            text = js.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
            out["outcome_pushes"] = replay.okww_pushes(text)
        return out
    except Exception:
        return {"error": traceback.format_exc()}


def loaded():
    return sorted({os.path.relpath(m.__file__, RELAY) for m in list(sys.modules.values())
                   if m and getattr(m, "__file__", None) and "ark_relay" in m.__file__})


if __name__ == "__main__":
    jobs = json.load(sys.stdin)
    # Serial first job in this process so the module list covers what judging imports.
    results = {}
    if jobs:
        results[jobs[0]["run"]] = judge(jobs[0])
    mods = loaded()
    # fork: this helper is passed with -c, so a spawned worker could not re-import judge().
    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 1),
                             mp_context=multiprocessing.get_context("fork")) as pool:
        for job, got in zip(jobs[1:], pool.map(judge, jobs[1:])):
            results[job["run"]] = got
    # Modules a later job imported in a worker are not visible here; judge one of
    # each script serially too, so their imports show up.
    seen = set()
    for job in jobs:
        s = job["run"].split("/")[-1].rsplit("-", 3)[0]
        if s not in seen:
            seen.add(s)
            judge(job)
    mods = sorted(set(mods) | set(loaded()))
    print(json.dumps({"results": results, "modules": mods}, ensure_ascii=False))
'''


def index_runs(index: Path) -> "collections.OrderedDict[str, dict]":
    """run_id -> its newest index entry, in first-seen order."""
    runs: collections.OrderedDict = collections.OrderedDict()
    for ln in index.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        rid = str(e.get("run_id") or "")
        if rid:
            runs[rid] = e
    return runs


def _extract(zf: zipfile.ZipFile, member: zipfile.ZipInfo, dest: Path) -> Path:
    """Extract one member to `dest` (a file path), keeping the archive's timestamp."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as src, dest.open("wb") as out:
        shutil.copyfileobj(src, out)
    t = datetime(*member.date_time).timestamp()
    os.utime(dest, (t, t))
    return dest


def stage_run(rid: str, entry: dict, evidence: Path, stage: Path) -> "tuple[dict | None, str]":
    """Stage one run. Returns (job, "") or (None, why it could not be compared)."""
    parts = rid.split("/")
    if len(parts) != 3:
        return None, "not a run record (run_id is not date/account/stem)"
    date, user, stem = parts
    src = evidence / rid.replace("/", "_")
    outer = sorted(src.glob(f"*{rid.replace('/', '_')}.zip")) if src.is_dir() else []
    store = entry.get("store") or "gofile"
    if not outer:
        if store == "gofile":
            return None, f"not fetched: stored on gofile ({entry.get('page') or 'no page - nothing was uploaded'}), web download only"
        if store == "wecom":
            return None, f"not fetched: stored on WeCom, media kept 3 days (expired {(entry.get('uploaded') or [{}])[0].get('expires')})"
        return None, f"not fetched: no archive for this run from {store}"
    try:
        zf = zipfile.ZipFile(outer[0])
        bad = zf.testzip()
    except (OSError, zipfile.BadZipFile) as exc:
        return None, f"archive broken: {outer[0].name} ({exc})"
    if bad:
        return None, f"archive broken: {bad} in {outer[0].name} fails its CRC"
    run_dir = stage / rid.replace("/", "_")
    if run_dir.exists():
        shutil.rmtree(run_dir)
    hist = run_dir / "history"
    names = {m.filename: m for m in zf.infolist()}
    if f"{stem}.json" not in names:
        return None, f"archive has no {stem}.json"
    js = _extract(zf, names[f"{stem}.json"], hist / date / user / f"{stem}.json")
    if f"{stem}.log" in names:
        _extract(zf, names[f"{stem}.log"], hist / date / user / f"{stem}.log")
    if "automas-app.log" in names:
        _extract(zf, names["automas-app.log"], run_dir / "debug" / "app.log")
    maaend_dir = None
    inner = [n for n in names if n.startswith("MaaEnd-logs-") and n.endswith(".zip")]
    if inner:
        maaend_dir = run_dir / "maaend"
        tmp = run_dir / "_inner"
        for n in sorted(inner):
            p = _extract(zf, names[n], tmp / n)
            try:
                with zipfile.ZipFile(p) as iz:
                    for m in iz.infolist():
                        if not m.is_dir() and m.filename.endswith(".log"):
                            _extract(iz, m, maaend_dir / "debug" / m.filename)
            except zipfile.BadZipFile:
                pass  # a split part that is not a zip on its own; its logs are simply absent
        shutil.rmtree(tmp, ignore_errors=True)
    return {"run": rid, "json": str(js), "history_root": str(hist),
            "maaend_dir": str(maaend_dir) if maaend_dir else ""}, ""


def judge_with(relay: Path, jobs: list) -> dict:
    env = dict(os.environ)
    # wuwa_game_root reads OK-WW's devices.json under ARK_OKWW_DIR; point both
    # versions at the same absent folder so neither reads anything of this Mac.
    env["ARK_OKWW_DIR"] = str(Path(tempfile.gettempdir()) / "relay-judge-diff-no-okww")
    env.pop("ARK_LOG_FILE", None)
    r = subprocess.run([sys.executable, "-c", HELPER], cwd=relay, input=json.dumps(jobs),
                       capture_output=True, text=True, env=env, check=False)
    if r.returncode != 0:
        raise SystemExit(f"judging with {relay} failed (exit {r.returncode}):\n{r.stderr[-4000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _strings(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in _strings(x)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    return []


def log_lines(log: Path, old: dict, new: dict, keys: list[str], limit: int = 12) -> list[str]:
    """Log lines carrying the text of the differing values; the log's tail when none do."""
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ["(no log file)"]
    needles = set()
    for k in keys:
        a, b = set(_strings(old.get(k))), set(_strings(new.get(k)))
        for s in a ^ b:
            # The judgement strings are the relay's own wording; the log carries
            # the script's. Search by the whole string, the part before the first
            # full-width parenthesis (the task name), and every full-width-quoted
            # piece (log words the relay copies through).
            for piece in [s, s.split("\uff08")[0],
                          *[p.split("\u300d")[0] for p in s.split("\u300c")[1:]]]:
                piece = piece.strip("\uff1a: ")
                if len(piece) >= 2:
                    needles.add(piece)
    hits = [f"{i}: {ln}" for i, ln in enumerate(lines, 1) if any(n in ln for n in needles)]
    if len(hits) > limit:
        # The verdict line (a task's failure, the run's last word) is usually
        # near the end; keep the first few for context and the rest from the end.
        return hits[:4] + [f"... ({len(hits) - limit} lines skipped)"] + hits[-(limit - 4):]
    if hits:
        return hits
    return ["(the differing text is not in the log verbatim; the log's last lines:)"] + \
        [f"{i}: {ln}" for i, ln in list(enumerate(lines, 1))[-6:]]


def sha(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return "(missing)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", required=True, type=Path, help="old version's relay/ folder")
    ap.add_argument("--new", required=True, type=Path, help="new version's relay/ folder")
    ap.add_argument("--evidence", type=Path, default=Path.home() / "Claude" / "ark-evidence")
    ap.add_argument("--stage", type=Path, help="where to stage the records (default: a temp folder)")
    ap.add_argument("--json", type=Path, help="also write both judgements of every record here")
    a = ap.parse_args()

    runs = index_runs(a.evidence / "index.jsonl")
    stage = a.stage or Path(tempfile.mkdtemp(prefix="relay-judge-diff-"))
    stage.mkdir(parents=True, exist_ok=True)
    jobs, skipped = [], {}
    for rid, entry in runs.items():
        job, why = stage_run(rid, entry, a.evidence, stage)
        if job:
            jobs.append(job)
        else:
            skipped[rid] = why

    old = judge_with(a.old.resolve(), jobs)
    new = judge_with(a.new.resolve(), jobs)

    by_date: dict = collections.OrderedDict()
    diffs, not_records = [], []
    for rid in runs:
        d = by_date.setdefault(rid.split("/")[0] if rid.count("/") == 2 else rid.split("/")[0],
                               {"listed": 0, "fetched": 0, "same": 0, "diff": 0, "not_record": 0})
        d["listed"] += 1
        if rid in skipped:
            continue
        d["fetched"] += 1
        o, n = old["results"].get(rid), new["results"].get(rid)
        if o is None and n is None:
            d["not_record"] += 1
            not_records.append(rid)
        elif o == n:
            d["same"] += 1
        else:
            d["diff"] += 1
            diffs.append((rid, o, n))

    print(f"old   {a.old}\nnew   {a.new}\nstage {stage}\n")
    print("date        listed fetched not_record  same  differ")
    tot = collections.Counter()
    for day, c in by_date.items():
        tot.update(c)
        print(f"{day:<11} {c['listed']:>6} {c['fetched']:>7} {c['not_record']:>10} {c['same']:>5} {c['diff']:>7}")
    print(f"{'total':<11} {tot['listed']:>6} {tot['fetched']:>7} {tot['not_record']:>10} {tot['same']:>5} {tot['diff']:>7}")

    if skipped:
        print("\nnot fetched / not compared:")
        for rid, why in skipped.items():
            print(f"  {rid}: {why}")
    if not_records:
        print("\nnot a run record for either version (parse_record returned None):")
        for rid in not_records:
            print(f"  {rid}")
    errors = [(rid, side) for rid in runs for side, res in (("old", old), ("new", new))
              if isinstance(res["results"].get(rid), dict) and "error" in res["results"][rid]]
    if errors:
        print("\nraised while judging (still compared above):")
        for rid, side in errors:
            res = (old if side == "old" else new)["results"][rid]["error"].strip().splitlines()[-1]
            print(f"  {rid} {side}: {res}")

    print(f"\njudged differently: {len(diffs)}" + (" (none)" if not diffs else ""))
    for rid, o, n in diffs:
        keys = sorted(set(o or {}) | set(n or {}))
        keys = [k for k in keys if (o or {}).get(k) != (n or {}).get(k)]
        print(f"\n● {rid}")
        for k in keys:
            print(f"    {k}:\n      old {(o or {}).get(k)!r}\n      new {(n or {}).get(k)!r}")
        job = next(j for j in jobs if j["run"] == rid)
        print("    log lines:")
        for ln in log_lines(Path(job["json"]).with_suffix(".log"), o or {}, n or {}, keys):
            print(f"      {ln}")

    mods = sorted(set(old["modules"]) | set(new["modules"]))
    changed = [m for m in mods if sha(a.old / m) != sha(a.new / m)]
    print(f"\nark_relay source files the judging loaded: {len(mods)}, differing between the versions: {len(changed)}"
          + (" - " + ", ".join(changed) if changed else ""))
    print("  " + " ".join(mods))

    if a.json:
        a.json.write_text(json.dumps({"old": old["results"], "new": new["results"],
                                      "skipped": skipped}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
