"""OK-WW patch: keep one shot of the tacet-field result screen for the daily report.

The user, 2026-09-07: 「我想确认一下是不是刷的是我想要的无音区种类，因为我不放心。
刷完之后能不能贴一张截图在日报通知里面？」and then: 「不要发没有用的截图，
我只需要刷完之后产出的那一张就行。」
Four seconds after the stamina is spent the screen is the result page (six drop
slots + exit dungeon / retry); OK-WW takes the shot on the last round, at the
moment just before it clicks 退出副本. The image lands in OK-WW's own screenshots
directory, and the relay attaches it to the daily report
(report.py:_attach_tacet_shots).
"""
from __future__ import annotations

from .core import _SRC, _Patch

_TACETSHOT_OLD = """                can_continue, used = self.use_stamina(once=self.stamina_once, must_use=must_use)
                self.info_incr('used stamina', used)
                self.sleep(4)
                if not can_continue:
                    self.click_relative(0.365, 0.853, hcenter=True)"""

_TACETSHOT_NEW = """                can_continue, used = self.use_stamina(once=self.stamina_once, must_use=must_use)
                self.info_incr('used stamina', used)
                self.sleep(4)
                if not can_continue:
                    # 本地补丁：最后一轮的结算页（产出六格）留一张给日报。
                    try:
                        self.screenshot('tacet_drops')
                    except Exception:
                        pass
                    self.click_relative(0.365, 0.853, hcenter=True)"""

# The v1 text (one shot of the list page before teleporting, one after arriving),
# kept **only so it can be reverted**. The user said those two shots were useless.
_TACETSHOT_V1_OLD = """            self.open_boss_book('wuyin')
            index = config.get('Which Tacet Suppression to Farm', 1) - 1
            self.teleport_to_tacet(index)
            self.click_team_challenge()
            while True:
                self.wait_in_team_and_world(time_out=120)"""
_TACETSHOT_V1 = """            self.open_boss_book('wuyin')
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
    return "self.screenshot('tacet_drops')" in text


_TACETSHOT = _Patch(
    name="无音区结算页留一张给日报",
    parts=(*_SRC, "TacetTask.py"),
    old=_TACETSHOT_OLD,
    new=_TACETSHOT_NEW,
    present=_tacetshot_present,
    breaks="日报里没有无音区产出截图，人没法核对刷的是哪一个",
)
