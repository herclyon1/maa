"""OK-WW 补丁：teamshot。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 找不到「开启挑战」时留证据 -------------------------------------------
# 来龙去脉见 docs/CODE-HISTORY.md「teamshot.py:(模块级)」
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
