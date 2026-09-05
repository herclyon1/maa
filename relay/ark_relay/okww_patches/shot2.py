"""OK-WW 补丁：shot2。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 周本退秘境前先留证据 -------------------------------------------------
# 来龙去脉见 docs/CODE-HISTORY.md「shot2.py:(模块级)」
_SHOT2_OLD = """                    if self._in_realm and not self.in_world():
                        self.send_key('esc', after_sleep=0.5)"""

_SHOT2_NEW = """                    if self._in_realm and not self.in_world():
                        # 本地补丁：退秘境之前先留一张图，看宝箱长什么样。
                        try:
                            self.screenshot('boss_dead_before_exit')
                        except Exception:
                            pass
                        self.send_key('esc', after_sleep=0.5)"""


def _shot2_present(text: str) -> bool:
    return "boss_dead_before_exit" in text


_SHOT2 = _Patch(
    name="退秘境前留证据截图",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_SHOT2_OLD,
    new=_SHOT2_NEW,
    present=_shot2_present,
    breaks="拿不到 Boss 刚死那一刻的画面，宝箱怎么领只能靠猜",
)
