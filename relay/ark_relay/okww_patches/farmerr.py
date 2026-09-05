"""OK-WW 补丁：farmerr。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 周本活锁：把被吞掉的异常打出来 ----------------------------------------
# 来龙去脉见 docs/CODE-HISTORY.md「farmerr.py:(模块级)」
_FARMERR_OLD = """            logger.error('farm 4c error, try handle monthly card', e)"""

_FARMERR_NEW = """            # 本地补丁：上游把异常当成 printf 参数传进去了，内容会被丢掉。
            logger.error(f'farm 4c error, try handle monthly card: {e!r}',
                         exc_info=True)"""


def _farmerr_present(text: str) -> bool:
    return "farm 4c error, try handle monthly card: {e!r}" in text


_FARMERR = _Patch(
    name="周本活锁：打出被吞掉的异常",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_FARMERR_OLD,
    new=_FARMERR_NEW,
    present=_farmerr_present,
    breaks="周本活锁的真因继续查不到，日志里只有一句没信息量的 farm 4c error",
)
