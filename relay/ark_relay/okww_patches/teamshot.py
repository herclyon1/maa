"""OK-WW 补丁：teamshot。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 找不到「开启挑战」时留证据 -------------------------------------------
#
# 2026-08-31 真因（堆栈从 12:35 起就在日志里，是我没去读）：
#     teleport_to_configured_boss_and_prepare
#       → teleport_to_configured_boss
#         → click_team_challenge()
#           → wait_click_feature('team_start_challenge', raise_if_not_found=True)
#             → WaitFailedException
# 传送到周本之后找不到「开启挑战」按钮，于是抛异常 → 重试 → 再传送，
# 12:35→12:47 空转 21 圈。上游 #1551 讲的是同一个模板匹配失败。
#
# 周本这条路在点按钮之前还有一次写死坐标的点击 self.click(0.880, 0.911)，
# 那一下歪了后面就全错。到底是模板没匹配上还是页面根本没打开，
# **不看那一刻的画面说不清**，所以先留图再抛，`raise` 保证行为不变。
_TEAMSHOT_OLD = """            self.click_team_challenge()"""

_TEAMSHOT_NEW = """            # 本地补丁：找不到「开启挑战」时先留一张图再抛，行为不变。
            try:
                self.click_team_challenge()
            except Exception:
                try:
                    self.screenshot('no_start_challenge')
                except Exception:
                    pass
                raise"""


def _teamshot_present(text: str) -> bool:
    return "no_start_challenge" in text


_TEAMSHOT = _Patch(
    name="开启挑战找不到时留证据截图",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_TEAMSHOT_OLD,
    new=_TEAMSHOT_NEW,
    present=_teamshot_present,
    breaks="周本空转的那一刻画面拿不到，只能继续猜是模板问题还是坐标问题",
)
