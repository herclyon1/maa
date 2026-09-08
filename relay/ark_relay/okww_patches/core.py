"""OK-WW patch: core. Split out of okww_patch.py (2026-09-06, moved verbatim)."""
from __future__ import annotations

import logging
import os
import py_compile
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("ark.okww_patch")



_SRC = ("data", "apps", "ok-ww", "working", "src", "task")


@dataclass(frozen=True)
class _Patch:
    name: str               # Plain-language name; goes into notifications
    parts: tuple            # Path relative to okww_dir
    old: str                # The upstream snippet, verbatim
    new: str                # The snippet we want instead
    present: Callable[[str], bool]      # Is it already in place?
    breaks: str             # What breaks if it cannot be applied; written for a human
    upstream: str = ""      # PR link once filed upstream; delete this patch once merged
    # A marker string of this patch that **stays the same across versions**
    # (a log line, say). After applying, it must appear exactly once in the
    # file; twice means patches got stacked.
    # The first line of `new` must not be used as the marker: stacking means
    # "old version + new version" side by side, and the two versions' first
    # lines usually differ, so counting on it finds exactly one -- letting the
    # stack through.
    # 来龙去脉见 docs/CODE-HISTORY.md「core.py:_Patch」
    unique: str = ""


def _atomic_write(f: Path, text: str) -> Path | None:
    """Back up, then replace atomically. Returns the backup path, or None if the write failed."""
    bak = f.with_name(f"{f.stem}.py.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(f, bak)
        tmp = f.with_suffix(".py.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, f)      # Atomic swap -- never let OK-WW read a half-written file
    except OSError:
        log.warning("OK-WW 补丁：写不进去 %s", f.name, exc_info=True)
        return None
    return bak


def _atomic_write_bytes(f: Path, data: bytes) -> Path | None:
    """Write bytes verbatim. A whole-file replacement must not go through
    write_text -- that rewrites line endings per platform.
    """
    bak = f.with_name(f"{f.stem}.py.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(f, bak)
        tmp = f.with_suffix(".py.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, f)
    except OSError:
        log.warning("OK-WW 补丁：写不进去 %s", f.name, exc_info=True)
        return None
    return bak


def _verify_or_revert(f: Path, bak: Path, present: Callable[[str], bool],
                      label: str) -> str:
    """Read back, then compile. Written is not the same as correct: broken
    syntax takes down the whole daily task.
    """
    back = f.read_text(encoding="utf-8", errors="replace")
    if not present(back):
        shutil.copy2(bak, f)
        log.error("OK-WW 补丁：%s 回读不对，已还原", label)
        return f"OK-WW 补丁：{label} 回读不对，已还原成上游版"
    try:
        py_compile.compile(str(f), doraise=True)
    except (py_compile.PyCompileError, OSError):
        shutil.copy2(bak, f)
        log.error("OK-WW 补丁：%s 语法检查没过，已还原", label, exc_info=True)
        return f"OK-WW 补丁：{label} 改完语法不对，已还原成上游版"
    return ""


def _stacked(f: Path, p: _Patch) -> "str | None":
    """After applying, check for stacking. Returns warning text, or None when fine.

    来龙去脉见 docs/CODE-HISTORY.md「core.py:_stacked」。
    """
    head = p.unique or next((ln for ln in p.new.splitlines() if ln.strip()), "")
    if not head:
        return None
    try:
        n = f.read_text(encoding="utf-8").count(head)
    except OSError:
        return None
    if n <= 1:
        return None
    log.error("OK-WW 补丁：%s 叠了 %d 层，需要人工看一眼", p.name, n)
    return (f"OK-WW 补丁：{p.name}**叠了 {n} 层**——旧版本没还原干净，"
            f"旧那段会先跑。{p.breaks}")


def _apply_one(root: Path, p: _Patch) -> list[str]:
    # Whenever `new` changes, present() must change with it: if the probe still
    # matches the old text, the patch is judged "not in place" and re-applied
    # over and over, or judged "already in place" and never applied at all.
    # Both fail silently.
    # 来龙去脉见 docs/CODE-HISTORY.md「core.py:_apply_one」
    f = root.joinpath(*p.parts)
    if not f.exists():
        log.warning("OK-WW 补丁：找不到 %s，跳过", f)
        return [f"OK-WW 补丁：找不到 {f.name}，{p.name} 没能检查"]
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        log.warning("OK-WW 补丁：读不了 %s", f, exc_info=True)
        return [f"OK-WW 补丁：读不了 {f.name}"]

    if p.present(text):
        return []                      # Idempotent: already in place, so leave no trace and make no noise
    if p.old not in text:
        # Upstream changed the structure. A forced replacement would only
        # corrupt the file, so stop and say so.
        log.warning("OK-WW 补丁：认不出上游 %s 那段，结构可能变了，不动它", p.name)
        return [f"OK-WW 补丁：{p.name}**贴不上了**（上游结构变了），"
                f"{p.breaks}，需要人工看一眼"]

    bak = _atomic_write(f, text.replace(p.old, p.new, 1))
    if bak is None:
        return [f"OK-WW 补丁：{p.name} 写不进去，{p.breaks}"]
    if err := _verify_or_revert(f, bak, p.present, p.name):
        return [err]
    if (dup := _stacked(f, p)) is not None:
        return [dup]
    log.info("OK-WW 补丁：%s 已重新贴上", p.name)
    return [f"OK-WW 补丁：{p.name} 已贴上"]

def _revert_text(root: Path, parts: tuple, new: str, old: str,
                 label: str) -> list[str]:
    """Revert one local change back to the upstream original. If it is not found,
    treat it as already reverted and say nothing.

    **Merely stopping to re-apply is not enough**: `ensure_patches` only applies,
    never reverts. Dropping a patch from the list leaves the copy already on the
    machine in place, and it only disappears when OK-WW's next update overwrites
    the file. So revert it deliberately.
    """
    f = root.joinpath(*parts)
    if not f.exists():
        return []
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return [f"OK-WW 补丁：读不了 {f.name}，{label} 没能撤销"]
    if new not in text:
        return []                       # Idempotent: already the upstream original
    bak = _atomic_write(f, text.replace(new, old, 1))
    if bak is None:
        return [f"OK-WW 补丁：{label} 撤销失败，写不进去"]
    log.info("OK-WW 补丁：%s 已撤销，还原成上游原样", label)
    return [f"OK-WW 补丁：{label} 已还原成上游原样"]
