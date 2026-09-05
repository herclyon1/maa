"""OK-WW 补丁：count。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 进本之前拍一张 Boss 页面，看本周还剩几次 ----------------------------
#
# 2026-08-31 用户问：「你确定刷的两次周本奖励是 90 级的副本？」——问得对，
# 等级 90 是 16:20 才写进母本、16:41 才同步过去，之前几趟点的都是
# 「推荐等级80」。而「已用 2 次」这个数是我从体力消耗**推算**的，
# 不是读到的。推算已经错过好几回了，这次去读真的。
#
# 安全性：波片不足时进不去（会弹「结晶波片不足」，我们的补丁取消并跳过），
# **不消耗次数**。所以这张图可以在波片不够的时候放心拍。
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
    # 判据认本版独有的字串，不能只认那句没变过的截图名——
    # 否则改了内容也贴不上去（今天已栽过一次）。v2 加了 Boss 名的 OCR。
    return "周本名称原文" in text


_COUNT = _Patch(
    name="进本前拍一张看剩余次数",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_COUNT_OLD,
    new=_COUNT_NEW,
    present=_count_present,
    breaks="本周还剩几次只能靠体力推算，而推算已经错过好几回",
)
