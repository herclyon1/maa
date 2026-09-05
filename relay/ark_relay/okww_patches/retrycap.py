"""OK-WW 补丁：retrycap。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 兜底重试上限：连败三次就退出，不许无限转 ----------------------------
# 来龙去脉见 docs/CODE-HISTORY.md「retrycap.py:(模块级)」
_RETRYCAP_OLD = """            logger.error('farm 4c error, try handle monthly card', e)
            if self.handle_claim_button() or self.handle_monthly_card():"""

_RETRYCAP_NEW = """            logger.error('farm 4c error, try handle monthly card', e)
            # 本地补丁：退出机制。连败 3 次就停，不许无限重试。
            self._farm_fail_count = getattr(self, '_farm_fail_count', 0) + 1
            if self._farm_fail_count >= 3:
                self.log_info('连续 3 次失败，退出本次周本任务，不再重试')
                raise TaskDisabledException()
            if self.handle_claim_button() or self.handle_monthly_card():"""


def _retrycap_present(text: str) -> bool:
    return "连续 3 次失败，退出本次周本任务" in text


_RETRYCAP = _Patch(
    name="兜底重试上限",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_RETRYCAP_OLD,
    new=_RETRYCAP_NEW,
    present=_retrycap_present,
    breaks="出错时无限重试，2026-09-01 转了 81 轮 50 分钟",
    unique="连续 3 次失败，退出本次周本任务",
)
