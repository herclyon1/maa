"""OK-WW patch: count. Split out of okww_patch.py (2026-09-06, moved verbatim)."""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- Shoot the boss page before entering, to read this week's runs left ---
# 来龙去脉见 docs/CODE-HISTORY.md「count.py:(模块级)」
_COUNT_OLD = """                self.click_configured_boss_level()"""

_COUNT_V1 = """                # 本地补丁：选等级之前把「本周剩余可收取次数」读出来。
                # 中继靠这个数判断本周打完没有——「任务跑完」不等于「三次领满」，
                # 波片不够时一趟只领得到一两次，按前者记账会把剩下的次数丢掉。
                try:
                    self.screenshot('weekly_remaining')
                except Exception:
                    pass
                try:
                    _left = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
                    self.log_info(f'周本本周剩余次数原文: {_left}')
                except Exception:
                    pass
                self.click_configured_boss_level()"""

_COUNT_NEW = """                # 本地补丁：选等级之前把「本周剩余可收取次数」读出来。
                # 中继靠这个数判断本周打完没有——「任务跑完」不等于「三次领满」，
                # 波片不够时一趟只领得到一两次，按前者记账会把剩下的次数丢掉。
                try:
                    self.screenshot('weekly_remaining')
                except Exception:
                    pass
                try:
                    _left = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
                    self.log_info(f'周本本周剩余次数原文: {_left}')
                except Exception:
                    pass
                try:
                    # 右上角标题就是 Boss 名（2026-09-02 截图：千傀重楼）——日报要写名字，不写序号
                    _name = self.ocr(box=self.box_of_screen(0.62, 0.13, 0.86, 0.20))
                    self.log_info(f'周本名称原文: {_name}')
                except Exception:
                    pass
                self.click_configured_boss_level()"""


def _count_present(text: str) -> bool:
    # The probe must match a string unique to THIS version, not the screenshot
    # name that never changes -- otherwise a changed body never gets applied
    # (that bit us once today). v2 added the OCR of the boss name.
    return "周本名称原文" in text


_COUNT = _Patch(
    name="进本前拍一张看剩余次数",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_COUNT_OLD,
    new=_COUNT_NEW,
    present=_count_present,
    breaks="本周还剩几次只能靠体力推算，而推算已经错过好几回",
)
