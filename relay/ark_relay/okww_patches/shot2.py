"""OK-WW 补丁：shot2。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 周本退秘境前先留证据 -------------------------------------------------
#
# 2026-08-31 定位到：打完 Boss、捡完声骸之后，`do_run` 走的是
#     if self._in_realm and not self.in_world():
#         self.send_key('esc', ...)                 ← 直接退秘境
# 宝箱那一步整个不存在。上一版截图拍在 esc **之后**，只拍到「确认离开」
# 弹窗，白拍一次。这次挪到 esc **之前**，拍的是 Boss 刚死那一刻的画面，
# 用来确认宝箱到底以什么形式出现（F 提示？图标？还是要走过去？）。
#
# 零行为改动：只加一次截图，try 包住，失败也不影响流程。
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
