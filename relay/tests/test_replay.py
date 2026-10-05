"""Replay: every real record under tests/replay must be judged exactly as its expected.json says.

Item 2 of the fix the user approved on 2026-09-07: the judging functions may only
be changed against real samples, and a change that breaks one turns this red first.

Speed (2026-10-06, deploy speed gate: no test file over 10 s). Nearly all of the
time is collector_maa._STAGE_DROPS searching MAA's 9000-character
「Request body: {...}」 lines - seconds per MAA record. The records are parsed in
parallel worker processes, slowest first, and the results are compared and
printed in the same order as before, so the checks and their labels are the same.
Under a tracer (changed_covered.py collects what each test executes with
sys.settrace, and worker processes are not traced) it runs in this process, one
record after the other, as it always did.
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay import collector  # noqa: E402

REPLAY = ROOT / "tests" / "replay"
FLOOR = 40          # minimum corpus size, see main()
# Raised from 10 to 40 on 2026-09-08 when the corpus grew from 1 day (10 records)
# to 4 days (42): the 09-01 weekly boss stuck on its results page, the 09-04/09-05
# essence runs farming the wrong region, and 09-01 Endfield's 「赠送干员礼物」
# failure. The floor exists so the corpus cannot quietly disappear - `.gitignore`'s
# `*.log` once kept the whole corpus out of the repo, and this test printed
# "all checks passed" with not a single sample.
FIELDS = ("okww_steps", "okww_unreachable", "okww_error", "okww_farm", "okww_runs",
          "okww_stamina_spent", "okww_stamina_left", "maaend_name_mismatch", "tasks_failed",
          "tasks_done", "okww_exit_race", "maaend_unreachable", "maaend_unreachable_shape")


def snapshot(rec) -> dict:
    out = {"script": rec.script, "ok": rec.ok, "failed_tasks": rec.failed_tasks,
           "duration_known": rec.duration_known}
    for k in FIELDS:
        if k in rec.raw:
            out[k] = rec.raw[k]
    return out


def cases() -> list[tuple[str, Path, Path, object]]:
    """(label, record json, day root, expected) for every record, in the order they are checked."""
    out = []
    for exp_file in sorted(REPLAY.glob("*/*/expected.json")):
        expected = json.loads(exp_file.read_text(encoding="utf-8"))
        day_root = exp_file.parents[2]
        for stem, want in expected.items():
            out.append((f"{exp_file.parent.relative_to(REPLAY)}/{stem}", exp_file.parent / f"{stem}.json",
                        day_root, want))
    return out


def judge(js: Path, day_root: Path):
    """What the collector makes of one record, as compared with expected.json."""
    rec = collector.parse_record(js, day_root)
    return snapshot(rec) if rec else None


def _cost(js: Path) -> int:
    """Rough parse cost, for starting the slowest first: the size of the record's log."""
    log = js.with_suffix(".log")
    return log.stat().st_size if log.exists() else 0


def judge_all(todo: list[tuple[str, Path, Path, object]]) -> list:
    """judge() for every case, results in the cases' order."""
    workers = min(8, os.cpu_count() or 1, len(todo))
    if sys.gettrace() is not None or workers < 2:
        return [judge(js, day_root) for _, js, day_root, _ in todo]
    order = sorted(range(len(todo)), key=lambda i: -_cost(todo[i][1]))
    got: list = [None] * len(todo)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {i: pool.submit(judge, todo[i][1], todo[i][2]) for i in order}
        for i, fut in futures.items():
            got[i] = fut.result()
    return got


def main() -> int:
    fails = []
    todo = cases()
    n = len(todo)
    for (label, _, _, want), got in zip(todo, judge_all(todo)):
        if got != want:
            fails.append(label)
            print(f"  ✗ {label}")
            for k in sorted(set(want or {}) | set(got or {})):
                if (got or {}).get(k) != (want or {}).get(k):
                    print(f"      {k}: 期望 {(want or {}).get(k)!r} 实际 {(got or {}).get(k)!r}")
        else:
            print(f"  ✓ {label}")
    # The floor: finding no corpus at all must never pass. Both gates look only
    # for "passed" on the last line, so "replayed 0, all checks passed" would leave
    # every judging function in the collector unprotected without a word -
    # measured 2026-09-08, after .gitignore swallowed the corpus, that was the output.
    if n < FLOOR:
        fails.append(f"回放样本只找到 {n} 条（至少要有 {FLOOR} 条）"
                     "——语料库丢了、被 .gitignore 挡了，或者目录层级变了")
        print(f"  ✗ 语料库只找到 {n} 条，期望至少 {FLOOR} 条")
    print(f"\n回放 {n} 条，" + (f"FAILED: {len(fails)}" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
