"""OK-WW 补丁：shot。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ── 补丁：周本领奖那一刻先截一张图 ────────────────────────────
# 2026-08-31：周本打满三轮，体力一点没动，说明奖励没领到。
# 那行代码是 `wait_click_feature('claim_cancel_button…', relative_x=2)`——
# `relative_x` 是「框内相对 X」，2 就是从取消按钮左边缘往右两个按钮宽度，
# **本意就是去点右边的领取按钮**（用户说领取在弹窗右下角）。日志里点在
# (538, 675)，偏够没偏够，不看那一刻的画面就说不清。
#
# 这个补丁**不改任何行为**，只是在点击之前存一张图。下次周本一跑就有证据，
# 不用再靠猜按钮坐标——猜坐标去改生产脚本正是 826 那类错。
_SHOT_OLD = """                        self.send_key('esc', after_sleep=0.5)
                        self.wait_click_feature('claim_cancel_button_hcenter_vcenter', relative_x=2,
                                                raise_if_not_found=True,
                                                post_action=lambda: self.send_key('esc', after_sleep=1),
                                                settle_time=1)"""

_SHOT_NEW = """                        self.send_key('esc', after_sleep=0.5)
                        # 本地补丁：先留一张证据，再点。行为不变。
                        try:
                            self.screenshot('weekly_claim_dialog')
                        except Exception:
                            pass
                        self.wait_click_feature('claim_cancel_button_hcenter_vcenter', relative_x=2,
                                                raise_if_not_found=True,
                                                post_action=lambda: self.send_key('esc', after_sleep=1),
                                                settle_time=1)"""


def _shot_present(text: str) -> bool:
    return "weekly_claim_dialog" in text


_SHOT = _Patch(
    name="周本领奖前留证据截图",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_SHOT_OLD,
    new=_SHOT_NEW,
    present=_shot_present,
    breaks="下次周本还是拿不到那一刻的画面，只能继续猜按钮位置",
)
