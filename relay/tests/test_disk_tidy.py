"""Regression tests for scripts/mac/disk-tidy.py (S-06 BOARD rule, ref_files, dry-run, idempotency)."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
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


def _part_out_log_rotation_and_no_hardlock():
    dt = _load_disk_tidy()
    src = Path(dt.__file__).read_text(encoding="utf-8")
    require("disk-tidy.py stripped Mac hardlock.py", "hardlock" not in src.lower(), "hardlock ref remains")
    root = tmpdir().resolve()
    out_log = root / "disk-tidy.out"
    # Below 2 MB threshold -> no rotation
    small = b"small log line\n" * 10
    out_log.write_bytes(small)
    check("under 2 MB does not rotate", dt.rotate_out_log(out_log), False)
    check("small log unchanged", out_log.read_bytes(), small)
    # Above 2 MB threshold -> rotates tail <= 2 MB to .1 and truncates .out in-place (preserving inode)
    ino_before = out_log.stat().st_ino
    chunk = (b"disk-tidy 2026-11-27 12:00 line " + b"x" * 96 + b"\n") * 25000
    out_log.write_bytes(chunk + b"LAST_MARKER_LINE\n")
    require("test log exceeds 2 MB", out_log.stat().st_size > dt.OUT_LOG_MAX_BYTES, str(out_log.stat().st_size))
    check("over 2 MB rotates", dt.rotate_out_log(out_log), True)
    check("inode preserved for launchd O_APPEND", out_log.stat().st_ino, ino_before)
    check("active disk-tidy.out truncated to 0", out_log.stat().st_size, 0)
    bak = root / "disk-tidy.out.1"
    require("backup .1 exists and <= 2 MB", bak.is_file() and 0 < bak.stat().st_size <= dt.OUT_LOG_MAX_BYTES,
            str(bak.stat().st_size if bak.is_file() else -1))
    require("backup .1 keeps newest tail", b"LAST_MARKER_LINE\n" in bak.read_bytes(), "missing tail marker")


def _make_gemini_db(db_path: Path, rows: list[tuple]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE conversation_summaries ("
            "conversation_id TEXT PRIMARY KEY, parent_conversation_id TEXT NOT NULL DEFAULT '', "
            "nesting_depth INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT '', "
            "not_fully_idle INTEGER NOT NULL DEFAULT 0, last_modified_time TEXT NOT NULL DEFAULT '')"
        )
        con.executemany(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()
    finally:
        con.close()


def _part_trash_ai_batches_and_gemini_subagents():
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
    procs_file.write_text("", encoding="utf-8")

    # --- Setup ~/.Trash fixtures ---
    trash = home / ".Trash"
    trash.mkdir(parents=True, exist_ok=True)
    ai_old_1 = trash / "Claude侧垃圾_1125"
    ai_old_2 = trash / "agy_tidy_1125"
    ai_old_3 = trash / "__retired_1125"
    user_trash = trash / "user_personal_photos"
    for d in (ai_old_1, ai_old_2, ai_old_3, user_trash):
        d.mkdir()
        (d / "f.txt").write_text("x", encoding="utf-8")

    # --- Setup ~/.gemini/antigravity/brain fixtures ---
    ag = home / ".gemini/antigravity"
    brain = ag / "brain"
    conv_dir = ag / "conversations"
    brain.mkdir(parents=True, exist_ok=True)
    conv_dir.mkdir(parents=True, exist_ok=True)

    main_a = "084474b4-ab78-4f5c-a7e0-07e9be8f50a2"
    main_b = "fe823e8f-f757-4676-b048-8569a38a3e20"
    main_c = "44e73229-c82c-449e-8bd0-76aed2437963"
    top_novel = "fe16624f-2668-4326-94fa-e32b7be2f56f"
    sub_stale = "11111111-1111-4111-8111-111111111111"
    sub_running = "22222222-2222-4222-8222-222222222222"
    sub_not_idle = "33333333-3333-4333-8333-333333333333"
    sub_recent_db = "44444444-4444-4444-8444-444444444444"
    sub_referenced = "55555555-5555-4555-8555-555555555555"
    sub_open = "66666666-6666-4666-8666-666666666666"
    sub_unlisted = "77777777-7777-4777-8777-777777777777"
    all_cids = (main_a, main_b, main_c, top_novel, sub_stale, sub_running,
                sub_not_idle, sub_recent_db, sub_referenced, sub_open, sub_unlisted)
    for cid in all_cids:
        d = brain / cid
        d.mkdir()
        (d / "note.txt").write_text("hi", encoding="utf-8")

    # Mark sub_open as open in lsof mock
    open_file.write_text(str(brain / sub_open / "note.txt") + "\n", encoding="utf-8")

    # Reference sub_referenced from an active tool under ~/Money/tools
    tools_dir = home / "Money/tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "ref_brain.py").write_text(
        f'P = "~/.gemini/antigravity/brain/{sub_referenced}/note.txt"\n',
        encoding="utf-8",
    )

    # Simulate running 48h in the future so created files have mtime/ctime >24h old
    now_t = time.time() + 48 * 3600
    old_iso = datetime.fromtimestamp(now_t - 72 * 3600, tz=timezone.utc).isoformat()
    recent_iso = datetime.fromtimestamp(now_t - 2 * 3600, tz=timezone.utc).isoformat()
    _make_gemini_db(ag / "conversation_summaries.db", [
        # Even if main_a/b/c were ever tagged as subagents, prefix hard-protection MUST keep them
        (main_a, "", 0, "CASCADE_RUN_STATUS_IDLE", 0, old_iso),
        (main_b, "", 0, "CASCADE_RUN_STATUS_IDLE", 0, old_iso),
        (main_c, main_a, 1, "CASCADE_RUN_STATUS_IDLE", 0, old_iso),
        (top_novel, "", 0, "CASCADE_RUN_STATUS_IDLE", 0, old_iso),
        (sub_stale, main_a, 1, "CASCADE_RUN_STATUS_IDLE", 0, old_iso),
        (sub_running, main_a, 1, "CASCADE_RUN_STATUS_RUNNING", 0, old_iso),
        (sub_not_idle, main_a, 1, "CASCADE_RUN_STATUS_IDLE", 1, old_iso),
        (sub_recent_db, main_a, 1, "CASCADE_RUN_STATUS_IDLE", 0, recent_iso),
        (sub_referenced, main_a, 1, "CASCADE_RUN_STATUS_IDLE", 0, old_iso),
        (sub_open, main_a, 1, "CASCADE_RUN_STATUS_IDLE", 0, old_iso),
    ])

    saved_env = dict(os.environ)
    try:
        # 1) Above floor (100 GiB free): Trash AI batches must NOT be touched; only sub_stale brain dir removed.
        os.environ.update(
            HOME=str(home),
            DISK_TIDY_TMP_ROOT=str(tmp_root),
            DISK_TIDY_TMPDIR=str(td),
            DISK_TIDY_BREW_PREFIX=str(brew),
            DISK_TIDY_OPEN_PATHS=str(open_file),
            DISK_TIDY_PROCS=str(procs_file),
            DISK_TIDY_FREE_BYTES=str(100 * 1024**3),
            DISK_TIDY_NOW=str(now_t),
        )
        rc1 = dt.main(["--apply"])
        check("above-floor apply exits 0", rc1, 0)
        require("above floor keeps AI trash batch 1", ai_old_1.is_dir(), str(ai_old_1))
        require("above floor keeps AI trash batch 2", ai_old_2.is_dir(), str(ai_old_2))
        require("above floor keeps AI trash batch 3", ai_old_3.is_dir(), str(ai_old_3))
        require("stale unreferenced subagent removed", not (brain / sub_stale).exists(), sub_stale)
        for keep_cid in (main_a, main_b, main_c, top_novel, sub_running,
                         sub_not_idle, sub_recent_db, sub_referenced, sub_open, sub_unlisted):
            require(f"protected/active Gemini dir kept: {keep_cid[:8]}", (brain / keep_cid).is_dir(), keep_cid)

        # 2) Below 30 GB floor (10 GiB free) + add a fresh (<24h) AI Trash batch:
        #    old AI batches go, fresh AI batch and user personal Trash stay!
        ai_fresh = trash / "Claude侧垃圾_fresh"
        ai_fresh.mkdir()
        (ai_fresh / "new.txt").write_text("fresh", encoding="utf-8")
        # Set fresh batch mtime to now_t - 1h so it is inside 24h window relative to now_t
        fresh_ts = now_t - 3600
        os.utime(ai_fresh / "new.txt", (fresh_ts, fresh_ts))
        os.utime(ai_fresh, (fresh_ts, fresh_ts))
        # Recreate a fresh subagent dir inside 24h window relative to now_t
        sub_fresh_fs = "88888888-8888-4888-8888-888888888888"
        (brain / sub_fresh_fs).mkdir()
        (brain / sub_fresh_fs / "t.txt").write_text("recent", encoding="utf-8")
        os.utime(brain / sub_fresh_fs / "t.txt", (fresh_ts, fresh_ts))
        os.utime(brain / sub_fresh_fs, (fresh_ts, fresh_ts))
        con = sqlite3.connect(str(ag / "conversation_summaries.db"))
        con.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?)",
                    (sub_fresh_fs, main_a, 1, "CASCADE_RUN_STATUS_IDLE", 0, old_iso))
        con.commit()
        con.close()

        os.environ["DISK_TIDY_FREE_BYTES"] = str(10 * 1024**3)
        rc2 = dt.main(["--apply"])
        check("below-floor apply exits 0", rc2, 0)
        require("below floor removes Claude侧垃圾_* >24h", not ai_old_1.exists(), str(ai_old_1))
        require("below floor removes agy_tidy_* >24h", not ai_old_2.exists(), str(ai_old_2))
        require("below floor removes __retired_* >24h", not ai_old_3.exists(), str(ai_old_3))
        require("below floor keeps <24h fresh AI trash batch", ai_fresh.is_dir(), str(ai_fresh))
        require("below floor NEVER touches user personal Trash", user_trash.is_dir(), str(user_trash))
        require("fresh-mtime subagent brain dir kept", (brain / sub_fresh_fs).is_dir(), sub_fresh_fs)

        # 3) Missing/unreadable DB -> fail-closed (keeps every subagent dir)
        sub_failclosed = "99999999-9999-4999-8999-999999999999"
        (brain / sub_failclosed).mkdir()
        (brain / sub_failclosed / "x.txt").write_text("x", encoding="utf-8")
        (ag / "conversation_summaries.db").unlink()
        rc3 = dt.main(["--apply"])
        check("missing-db apply exits 0", rc3, 0)
        require("missing DB fails closed and keeps brain dir", (brain / sub_failclosed).is_dir(), sub_failclosed)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)


if __name__ == "__main__":
    sys.exit(run_parts([
        _part_board_stale_and_refs,
        _part_fresh_and_docstring_honesty,
        _part_out_log_rotation_and_no_hardlock,
        _part_trash_ai_batches_and_gemini_subagents,
    ]))
