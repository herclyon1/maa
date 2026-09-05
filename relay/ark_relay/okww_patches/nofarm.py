"""OK-WW 补丁：nofarm。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 禁用刷体力，把波片留给周本 --------------------------------------------
# 来龙去脉见 docs/CODE-HISTORY.md「nofarm.py:(模块级)」
_NOFARM_OLD = """        target = self.config.get('Which to Farm', self.support_tasks[0])
        if target == self.support_tasks[0]:"""

_NOFARM_NEW = """        target = self.config.get('Which to Farm', self.support_tasks[0])
        # 本地补丁：存在这个标记文件就完全不刷体力，把波片留给周本。
        # 恢复：删掉 C:\\ProgramData\\ark-relay\\state\\no-stamina-farm.flag
        import os as _os
        if _os.path.exists(r'C:\\ProgramData\\ark-relay\\state\\no-stamina-farm.flag'):
            self.log_info('本地补丁：刷体力已禁用（标记文件在），这一趟不花波片')
        elif target == self.support_tasks[0]:"""


def _nofarm_present(text: str) -> bool:
    return "刷体力已禁用（标记文件在）" in text


_NOFARM = _Patch(
    name="禁用刷体力（标记文件控制）",
    parts=(*_SRC, "DailyTask.py"),
    old=_NOFARM_OLD,
    new=_NOFARM_NEW,
    present=_nofarm_present,
    breaks="日常刷取会把波片吃光，周本就没波片领奖了",
)
