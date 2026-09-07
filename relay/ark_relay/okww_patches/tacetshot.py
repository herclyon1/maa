"""OK-WW 补丁：无音区留两张图给日报。

用户 2026-09-07：「我想确认一下是不是刷的是我想要的无音区种类，因为我不放心。
刷完之后能不能贴一张截图在日报通知里面？」
拍两张：F2 图鉴的无音区列表页（传送前）、到达后站在场里（第一轮打之前）。
每趟只拍一次。图落在 OK-WW 自己的 screenshots 目录，中继发日报时顺手带上
（report.py:_attach_tacet_shots）。
"""
from __future__ import annotations

from .core import _SRC, _Patch

_TACETSHOT_OLD = """            self.open_boss_book('wuyin')
            index = config.get('Which Tacet Suppression to Farm', 1) - 1
            self.teleport_to_tacet(index)
            self.click_team_challenge()
            while True:
                self.wait_in_team_and_world(time_out=120)"""

_TACETSHOT_NEW = """            self.open_boss_book('wuyin')
            index = config.get('Which Tacet Suppression to Farm', 1) - 1
            # 本地补丁：留两张图给日报，让人核对刷的是不是想要的那个无音区。
            # 每趟只拍一次（这个 while 每轮体力都会回来）。
            if not getattr(self, '_ark_tacet_shot', False):
                try:
                    self.screenshot('tacet_list')
                except Exception:
                    pass
            self.teleport_to_tacet(index)
            self.click_team_challenge()
            while True:
                self.wait_in_team_and_world(time_out=120)
                if not getattr(self, '_ark_tacet_shot', False):
                    self._ark_tacet_shot = True
                    try:
                        self.screenshot('tacet_arrived')
                    except Exception:
                        pass"""


def _tacetshot_present(text: str) -> bool:
    return "self.screenshot('tacet_list')" in text


_TACETSHOT = _Patch(
    name="无音区留两张图给日报",
    parts=(*_SRC, "TacetTask.py"),
    old=_TACETSHOT_OLD,
    new=_TACETSHOT_NEW,
    present=_tacetshot_present,
    breaks="日报里没有无音区截图，人没法核对刷的是哪一个",
)
