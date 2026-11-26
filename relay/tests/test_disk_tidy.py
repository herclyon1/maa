"""Regression tests for scripts/mac/disk-tidy.py (S-06 BOARD rule, ref_files, dry-run, idempotency)."""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir

_SHARED = (check, fails, require, tmpdir)


def _load_disk_tidy():
    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("disk_tidy_under_test", repo / "scripts/mac/disk-tidy.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_big_dir(path: Path, mb: int = 21) -> None:
    path.mkdir(parents=True, exist_ok=True)
    # Sparse-free real bytes so `du -sk` reports >= 20 MB on APFS.
    chunk = b"A" * (1024 * 1024)
    with (path / "blob.bin").open("wb") as fh:
        for _ in range(mb):
            fh.write(chunk)


def _part_board_stale_and_refs():
    dt = _load_disk_tidy()
    root = tmpdir().resolve()
    home = root / "home"
    tmp_root = root / "claude_tmp"
    td = root / "tdir"
    brew = root / "brew"
    for d in (home, tmp_root, td, brew):
        d.mkdir(parents=True, exist_ok=True)

    open_file = root / "open_paths.txt"
    procs_file = root / "procs.txt"
    open_file.write_text("", encoding="utf-8")
    procs_file.write_text("", encoding="utf-8")

    board = home / "Money/styl-work/BOARD"
    board.mkdir(parents=True, exist_ok=True)

    stale_unreferenced = board / "stale-unreferenced"
    ref_by_money = board / "ref-by-money"
    ref_by_memory = board / "ref-by-memory"
    protected_plan = board / "方案审批-keep"
    protected_arch = board / "归档-1122"
    small_dir = board / "small-stale"

    for d in (stale_unreferenced, ref_by_money, ref_by_memory, protected_plan, protected_arch):
        _make_big_dir(d, mb=21)
    small_dir.mkdir(parents=True, exist_ok=True)
    (small_dir / "tiny.txt").write_text("hi", encoding="utf-8")

    # 1) Active script under ~/Money/tools/ (outside remote-ref/tools) references ref-by-money
    tools_dir = home / "Money/tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "keep_helper.py").write_text(
        'DATA = "~/Money/styl-work/BOARD/ref-by-money/blob.bin"\n',
        encoding="utf-8",
    )

    # 2) Active Claude memory note references BOARD/ref-by-memory/sub/report.txt (relative form + CJK punct)
    mem_dir = home / ".claude/projects/-Users-test-Claude/memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "endfield-dx11.md").write_text(
        "证据 BOARD/ref-by-memory/sub/report-B.txt。\n",
        encoding="utf-8",
    )

    # Run clock 20 days in the future so mtime & ctime are >14 days old.
    future_now = time.time() + 20 * 86400
    saved_env = dict(os.environ)
    try:
        os.environ.update(
            HOME=str(home),
            DISK_TIDY_TMP_ROOT=str(tmp_root),
            DISK_TIDY_TMPDIR=str(td),
            DISK_TIDY_BREW_PREFIX=str(brew),
            DISK_TIDY_OPEN_PATHS=str(open_file),
            DISK_TIDY_PROCS=str(procs_file),
            DISK_TIDY_FREE_BYTES=str(100 * 1024**3),
            DISK_TIDY_NOW=str(future_now),
        )

        # Verify ref_files() covers both ~/Money active scripts and ~/.claude/projects/*/memory/*.md
        env = dt.Env.from_environ()
        rfiles = dt.ref_files(env, [])
        rfile_strs = {str(p) for p in rfiles}
        require("ref_files includes ~/Money/tools script", str(tools_dir / "keep_helper.py") in rfile_strs,
                str(rfile_strs))
        require("ref_files includes Claude memory note", str(mem_dir / "endfield-dx11.md") in rfile_strs,
                str(rfile_strs))

        # Verify exact keep reasons before apply (cannot pass due to an unrelated guard failure)
        ctx = dt.snapshot(env)
        by_name = {Path(it.path).name: it for it in dt.rule_board_stale_dirs(env, ctx)}
        require("stale-unreferenced marked for trash action",
                by_name["stale-unreferenced"].keep is None and by_name["stale-unreferenced"].action == "trash",
                str(by_name.get("stale-unreferenced")))
        require("ref-by-money kept specifically by reference check",
                "reused" in (by_name["ref-by-money"].keep or ""),
                str(by_name.get("ref-by-money")))
        require("ref-by-memory kept specifically by reference check",
                "memory note" in (by_name["ref-by-memory"].keep or ""),
                str(by_name.get("ref-by-memory")))

        # Dry-run: zero writes (nothing moved, no ~/.Trash entries, no log file)
        rc_dry = dt.main(["--dry-run"])
        check("dry-run exits 0", rc_dry, 0)
        require("dry-run leaves stale_unreferenced intact", stale_unreferenced.is_dir(), str(stale_unreferenced))
        trash_dir = home / ".Trash"
        trash_after_dry = list(trash_dir.iterdir()) if trash_dir.is_dir() else []
        check("dry-run leaves ~/.Trash untouched", trash_after_dry, [])
        require("dry-run writes no disk-tidy.log", not env.log.exists(), str(env.log))

        # Apply #1: only stale_unreferenced moves to ~/.Trash; referenced & protected stay
        rc_apply1 = dt.main(["--apply"])
        check("apply #1 exits 0", rc_apply1, 0)
        require("stale_unreferenced moved out of BOARD", not stale_unreferenced.exists(), str(stale_unreferenced))
        trashed = [p for p in trash_dir.iterdir() if p.name.endswith("_stale-unreferenced")]
        check("stale_unreferenced landed in ~/.Trash", len(trashed), 1)
        require("trashed payload intact", (trashed[0] / "blob.bin").is_file(), str(trashed[0]))

        require("~/Money script referenced dir kept", ref_by_money.is_dir(), str(ref_by_money))
        require("memory note referenced dir kept", ref_by_memory.is_dir(), str(ref_by_memory))
        require("protected 方案审批* dir kept", protected_plan.is_dir(), str(protected_plan))
        require("protected 归档-* dir kept", protected_arch.is_dir(), str(protected_arch))
        require("small <20MB dir kept", small_dir.is_dir(), str(small_dir))
        check("only 1 item moved to ~/.Trash", len(list(trash_dir.iterdir())), 1)

        log_lines_1 = env.log.read_text(encoding="utf-8").splitlines()
        check("apply #1 wrote 1 log line", len(log_lines_1), 1)

        # Apply #2: idempotent no-op
        rc_apply2 = dt.main(["--apply"])
        check("apply #2 exits 0", rc_apply2, 0)
        check("apply #2 leaves Trash count unchanged", len(list(trash_dir.iterdir())), 1)
        log_lines_2 = env.log.read_text(encoding="utf-8").splitlines()
        check("apply #2 writes no duplicate log lines", len(log_lines_2), 1)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)


def _part_fresh_and_docstring_honesty():
    dt = _load_disk_tidy()
    root = tmpdir().resolve()
    home = root / "home"
    tmp_root = root / "claude_tmp"
    td = root / "tdir"
    brew = root / "brew"
    for d in (home, tmp_root, td, brew):
        d.mkdir(parents=True, exist_ok=True)
    open_file = root / "open_paths.txt"
    procs_file = root / "procs.txt"
    open_file.write_text("", encoding="utf-8")
    procs_file.write_text("", encoding="utf-8")

    board = home / "Money/styl-work/BOARD"
    fresh_big = board / "fresh-big"
    _make_big_dir(fresh_big, mb=21)

    # Only 5 days later (< 14 days threshold) -> must be kept specifically for age.
    near_now = time.time() + 5 * 86400
    saved_env = dict(os.environ)
    try:
        os.environ.update(
            HOME=str(home),
            DISK_TIDY_TMP_ROOT=str(tmp_root),
            DISK_TIDY_TMPDIR=str(td),
            DISK_TIDY_BREW_PREFIX=str(brew),
            DISK_TIDY_OPEN_PATHS=str(open_file),
            DISK_TIDY_PROCS=str(procs_file),
            DISK_TIDY_FREE_BYTES=str(100 * 1024**3),
            DISK_TIDY_NOW=str(near_now),
        )
        env = dt.Env.from_environ()
        ctx = dt.snapshot(env)
        items = dt.rule_board_stale_dirs(env, ctx)
        check("fresh-big seen by board rule", len(items), 1)
        require("fresh-big kept specifically by 14d age check",
                "changed within 14 d" in (items[0].keep or ""),
                str(items[0]))

        rc = dt.main(["--apply"])
        check("fresh <14d apply exits 0", rc, 0)
        require("fresh <14d big dir kept", fresh_big.is_dir(), str(fresh_big))
        trash_dir = home / ".Trash"
        trashed = list(trash_dir.iterdir()) if trash_dir.is_dir() else []
        check("fresh <14d puts nothing in Trash", trashed, [])
    finally:
        os.environ.clear()
        os.environ.update(saved_env)

    # Docstring honesty: must NOT claim "never deleted" / "绝不永久删除" for Trash moves.
    doc = dt.rule_board_stale_dirs.__doc__ or ""
    require("rule docstring avoids false 'never deleted' claim", "never deleted" not in doc, doc)
    require("rule docstring mentions Trash auto-empty policy", "FXRemoveOldTrashItems" in doc, doc)


if __name__ == "__main__":
    sys.exit(run_parts([_part_board_stale_and_refs, _part_fresh_and_docstring_honesty]))
