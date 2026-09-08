"""OK-WW patch: the story-spoiler dialog on a limited-time-early boss.

2026-09-09, farming the first row of 讨伐强敌, which carries the 限时提前开放 tag:
clicking its challenge button pops a spoiler dialog reading 「提前到达目标位置可能影响
剧情体验，是否确认前往？」 over two buttons, cancel on the left and confirm on the right.
Upstream's click_on_book_target does not know that dialog, so the wait that follows
it times out every time and the whole run dies with 「Teleport to boss failed」 -
three attempts, then our retry cap stops the task. The user had to click 确认 by
hand to get in at all.

The dialog costs nothing: it is a spoiler warning, not a resource prompt. It is
identified by its own text before anything is clicked - a bare 「there is a confirm
button on screen」 test would happily confirm a waveplate prompt too, and that is
the one mistake this file must not make.
"""
from __future__ import annotations

from .core import _SRC, _Patch

_BOSSTIP_OLD = """        self.click(target, after_sleep=1)
        feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'], time_out=10,
                                    settle_time=0.5, raise_if_not_found=True)"""

_BOSSTIP_NEW = """        self.click(target, after_sleep=1)
        # 本地补丁：限时提前开放的 boss（2026-09-09 的天傀劫煞是列表第一个）点
        # 「直接挑战」之后，会先弹一个「提前到达目标位置可能影响剧情体验，是否确认
        # 前往？」。上游不认这个框，下面那个 wait 必然超时 → Teleport to boss failed，
        # 一次都进不去。这个框不花任何资源，只是剧透提醒。
        # **先按文字认框再点**：只看「屏幕上有确认按钮」会把波片不足那类花钱的框
        # 也一起确认掉，那是这个文件绝不能犯的错。
        try:
            _tip = self.ocr(box=self.box_of_screen(0.25, 0.40, 0.78, 0.56)) or []
            _tip_t = ' '.join(str(_b) for _b in _tip)
            if '确认前往' in _tip_t or '剧情体验' in _tip_t:
                self.log_info('限时提前开放的剧情提示框，点确认前往')
                self.click_dialog_right_button()
        except Exception as _e:
            self.log_info(f'剧情提示框那一步跳过: {_e}')
        feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'], time_out=10,
                                    settle_time=0.5, raise_if_not_found=True)"""


def _bosstip_present(text: str) -> bool:
    return "限时提前开放的剧情提示框" in text


_BOSSTIP = _Patch(
    name="限时提前开放的 boss：认出剧情提示框",
    parts=(*_SRC, "BaseWWTask.py"),
    old=_BOSSTIP_OLD,
    new=_BOSSTIP_NEW,
    present=_bosstip_present,
    breaks="刷天傀劫煞这类限时提前开放的 boss 时一次都传送不进去，整个任务失败",
    unique="限时提前开放的剧情提示框",
)
