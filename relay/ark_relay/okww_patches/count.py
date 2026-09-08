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

_COUNT_V2 = """                # 本地补丁：选等级之前把「本周剩余可收取次数」读出来。
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

_COUNT_NEW = """                # 本地补丁：选等级之前把「本周剩余可收取次数」读出来。
                # 中继靠这个数判断本周打完没有——「任务跑完」不等于「三次领满」，
                # 波片不够时一趟只领得到一两次，按前者记账会把剩下的次数丢掉。
                try:
                    self.screenshot('weekly_remaining')
                except Exception:
                    pass
                _left = None
                try:
                    _left = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
                    self.log_info(f'周本本周剩余次数原文: {_left}')
                except Exception:
                    pass
                # 本地补丁 v3：读到「本周剩余可收取次数：0/3」就不进本。
                # 09-07 实测：读到 0/3 之后照样进去打了两轮，整屏都是
                # 「收取物资次数已达到上限」，五分多钟一无所获，还把日常往后推。
                # 次数就在这一行读到了，认出来就按「本周已领满」干净跳过，
                # 走法和波片不足那条一样（TaskDisabledException = 跳过本次）。
                import re as _re
                _lt = ' '.join(str(_b) for _b in (_left or []))
                if _re.search(r'次数[^0-9]{0,6}0\s*[/／]\s*3', _lt):
                    self.log_info('本周周本次数已领满（0/3），不进本，跳过')
                    try:
                        self.ensure_main(time_out=30)
                    except Exception:
                        pass
                    raise TaskDisabledException()
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
    # (that bit us once today). v2 added the OCR of the boss name; v3 skips the
    # boss when the count already reads 0/3.
    return "本周周本次数已领满" in text


_COUNT = _Patch(
    name="进本前拍一张看剩余次数",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_COUNT_OLD,
    new=_COUNT_NEW,
    present=_count_present,
    breaks="本周还剩几次只能靠体力推算，而推算已经错过好几回",
)
