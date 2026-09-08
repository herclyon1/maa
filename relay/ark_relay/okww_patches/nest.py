"""OK-WW patch: nest. Split out of okww_patch.py (2026-09-06, moved verbatim)."""
from __future__ import annotations

import logging
import hashlib
from pathlib import Path

from .core import _SRC, _atomic_write_bytes, _verify_or_revert

log = logging.getLogger("ark.okww_patch")




# ── Patch 3: nightmare nest task (whole-file replacement) ──────
# This patch changes three places and also adds a method and a config option;
# stitching that together with text replacements is far too brittle.
# So it is a **whole-file replacement guarded by a hash**: we only replace when
# the copy on the machine matches the upstream version we recorded byte for byte.
# The moment upstream changes, the hash no longer matches, we stop and say so —
# we never paste an old patch over new code.
#
# The three changes:
#   1. Allow resuming nests that are not yet cleared (the original only accepted
#      "defeated 0/N", so one kill made it give up on that nest forever)
#      -- upstream PR ok-oldking/ok-wuthering-waves#1629
#   2. Skip a nest that made no progress instead of re-entering forever (the game
#      pops up "challenge failed" when the team cannot win)
#   3. New "only farm these nests" config option (issue #1622; upstream has no
#      such capability yet)
_NEST_DIR = Path(__file__).resolve().parent.parent / "okww_files"   # one level deeper since the split into a subpackage
_NEST_UPSTREAM = _NEST_DIR / "NightmareNestTask.upstream.py"
_NEST_PATCHED = _NEST_DIR / "NightmareNestTask.patched.py"


def _sha(data: bytes) -> str:
    """Hash the **content**, not the line endings.

    On Windows `write_text` turns \n into \r\n, so the same content ends up with
    different bytes and a different hash on two machines. On 2026-08-26 that made
    us misjudge an already-applied patch as "does not match upstream". Normalising
    to \n first means we compare the content itself.
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# Hashes of every NightmareNestTask version we ourselves have shipped.
# Why this is needed: the guard originally recognised only "the upstream copy" and
# "the current copy", so as soon as we changed our own patch, the copy on the
# machine matched neither and was judged "hand-edited by someone" and refused --
# meaning our own fixes could never be pushed out. Past versions are recorded here;
# when we see one, we overwrite as usual.
# Our marker: a config constant we invented that can never appear in upstream source.
# Seeing it = the copy on site came from us and can safely be overwritten with the
# latest version.
_NEST_MARKER = b"Only Farm These Nests"

_NEST_KNOWN_OURS = {
    "6b27d6f03f7210f80cb5da823a55c5732f26935f16ab775196aee80376b2ff7e",   # 2026-08-27 12:05: the hit_wanted version (differs from the final one only in a docstring; its hash was never recorded)
    "788a8b633498b44f33dbd56d96b971cc95265e88719f6dc0a9f47fe2b4897916",   # 2026-08-27 11:35: a throwaway version that logged geometry
    "fc7207ff2047999241cd1ce44996b54b13f2a9d1d0169e344615490bf57e85d5",   # 2026-08-27 11:26: substring matching, but the row tolerance was only one line height
    "48ec36c8c117854dfdd86d160a89bc76ce6e26a9b1c445c7605935b69f044726",   # 2026-08-27 morning: the nest filter used exact matching and never matched 「落渊南丘残象聚落」
    "72cf1da2e840918fe62656acfb5b9434e84b1f320829ccf256d7f9aa9c9fcc34",   # before 2026-08-27: the nest filter ran OCR once and did not wait for the list to render
}


def _apply_nest(root: Path) -> list[str]:
    f = root.joinpath(*_SRC, "NightmareNestTask.py")
    label = "巢穴任务（续刷 / 不空转 / 可指定点位）"
    if not f.exists():
        return [f"OK-WW 补丁：找不到 NightmareNestTask.py，{label} 没能检查"]
    if not (_NEST_UPSTREAM.exists() and _NEST_PATCHED.exists()):
        log.warning("OK-WW 补丁：缺少 okww_files 里的参照文件")
        return [f"OK-WW 补丁：{label} 缺少参照文件，没能检查"]

    try:
        cur = f.read_bytes()
    except OSError:
        return ["OK-WW 补丁：读不了 NightmareNestTask.py"]

    patched = _NEST_PATCHED.read_bytes()
    if _sha(cur) == _sha(patched):
        return []                       # idempotent: already our copy
    # Upstream will never contain this config constant of ours, so seeing it means
    # the copy on site was pasted by some older version of ours and can safely be
    # overwritten; only when it is absent do we fall back to checking the hash.
    # 来龙去脉见 docs/CODE-HISTORY.md「nest.py:_apply_nest」
    ours_by_marker = _NEST_MARKER in cur
    if not ours_by_marker and _sha(cur) not in _NEST_KNOWN_OURS and \
            _sha(cur) != _sha(_NEST_UPSTREAM.read_bytes()):
        # Neither the upstream copy nor ours -- upstream changed it, or someone
        # hand-edited it. Overwriting now would wipe out their changes, so stop.
        log.warning("OK-WW 补丁：NightmareNestTask.py 和记录的上游版对不上，不动它")
        return [f"OK-WW 补丁：{label}**贴不上了**——文件和记录的上游版不一致，"
                "多半是上游更新了，需要人工重做这份补丁"]

    bak = _atomic_write_bytes(f, patched)
    if bak is None:
        return [f"OK-WW 补丁：{label} 写不进去"]
    if err := _verify_or_revert(f, bak, lambda s: _sha(s.encode("utf-8")) == _sha(patched), label):
        return [err]
    log.info("OK-WW 补丁：%s 已重新贴上", label)
    return [f"OK-WW 补丁：{label} 已重新贴上（上次更新把它覆盖了）"]
