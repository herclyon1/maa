"""OK-WW 补丁：starve。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations

import logging
from pathlib import Path

from .core import _SRC, _atomic_write, _verify_or_revert

log = logging.getLogger("ark.okww_patch")



# ── 补丁四：主C饿死兜底 ────────────────────────────────────────
# 来龙去脉见 docs/CODE-HISTORY.md「starve.py:(模块级)」
_STARVE_OLD = """    def _choose_switch_target_by_buff_time(self, current_char, candidates):
        if not candidates:
            return current_char
"""

_STARVE_NEW = """    # 本地补丁：主C饿死兜底。协奏攒不满时 has_buff() 恒为 False，
    # _unbuffed_non_main_target 会让两个辅助无限互切，主C永远上不了场——
    # 而主C正是唯一有机会把协奏打起来的人，于是死锁自我维持。
    # 上游 issue: ok-oldking/ok-wuthering-waves#1626
    MAIN_DPS_STARVE_SECONDS = 25.0

    def _starved_main_dps_target(self, candidates):
        now = time.time()
        starved = [char for char in candidates
                   if char.is_main_dps
                   and (char.last_switch_in_time < 0
                        or now - char.last_switch_in_time > self.MAIN_DPS_STARVE_SECONDS)]
        return self._oldest_switch_target(starved)

    def _choose_switch_target_by_buff_time(self, current_char, candidates):
        if not candidates:
            return current_char

        if not current_char.is_main_dps:
            if starved := self._starved_main_dps_target(candidates):
                return starved
"""


def _starve_present(text: str) -> bool:
    return "_starved_main_dps_target" in text


def _apply_starve(root: Path) -> list[str]:
    f = root.joinpath(*_SRC, "BaseCombatTask.py")
    label = "主C饿死兜底"
    if not f.exists():
        return [f"OK-WW 补丁：找不到 BaseCombatTask.py，{label} 没能检查"]
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return ["OK-WW 补丁：读不了 BaseCombatTask.py"]
    if _starve_present(text):
        return []
    if _STARVE_OLD not in text:
        log.warning("OK-WW 补丁：认不出上游 _choose_switch_target_by_buff_time，不动它")
        return [f"OK-WW 补丁：{label}**贴不上了**（上游结构变了），需要人工看一眼"]
    bak = _atomic_write(f, text.replace(_STARVE_OLD, _STARVE_NEW, 1))
    if bak is None:
        return [f"OK-WW 补丁：{label} 写不进去"]
    if err := _verify_or_revert(f, bak, _starve_present, label):
        return [err]
    log.info("OK-WW 补丁：%s 已重新贴上", label)
    return [f"OK-WW 补丁：{label} 已重新贴上（上次更新把它覆盖了）"]
