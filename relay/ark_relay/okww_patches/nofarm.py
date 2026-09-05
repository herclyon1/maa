"""OK-WW 补丁：nofarm。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 禁用刷体力，把波片留给周本 --------------------------------------------
#
# 用户 2026-09-01 03:25：「把刷贝币刷体力的任务禁用，这样就不可能会出现
# 波片被消耗的情况。」周本领一次奖要 60 波片，三次 180；而日常刷取
# （凝素/深渊/模拟领域）会把波片吃光——两者抢同一份资源。
# 2026-08-31 就是这么被吃掉的：18:23 贝币刷取把波片从 41 花到 1。
#
# `Which to Farm` 只有三个选项（凝素/深渊/模拟领域），**没有「不刷」**，
# 所以只能打补丁。用**标记文件**而不是配置项：想恢复只要删掉那个文件，
# 不用改代码、不用重新部署。
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
