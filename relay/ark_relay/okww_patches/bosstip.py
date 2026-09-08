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

# v3 replaces the return line too, so its anchor includes it. v1 and v2 stopped at
# the wait, which is why they revert to _BOSSTIP_OLD and v3 reverts to this.
_BOSSTIP_OLD_FULL = _BOSSTIP_OLD + "\n        return feature.name == 'team_close'"


_BOSSTIP_NEW = """        self.click(target, after_sleep=1)
        # 本地补丁：限时提前开放的 boss（2026-09-09 的天傀劫煞是列表第一个）点
        # 「直接挑战」之后，会先弹一个「提前到达目标位置可能影响剧情体验，是否确认
        # 前往？」。上游不认这个框，下面那个 wait 必然超时 → Teleport to boss failed，
        # 一次都进不去。这个框不花任何资源，只是剧透提醒。
        # **先按文字认框再点**：只看「屏幕上有确认按钮」会把波片不足那类花钱的框
        # 也一起确认掉，那是这个文件绝不能犯的错。
        _tipped = False
        try:
            _tip = self.ocr(box=self.box_of_screen(0.25, 0.40, 0.78, 0.56)) or []
            _tip_t = ' '.join(str(_b) for _b in _tip)
            _tipped = '确认前往' in _tip_t or '剧情体验' in _tip_t
            if _tipped:
                self.log_info('限时提前开放的剧情提示框，点确认前往')
                self.click_dialog_right_button()
            else:
                # 认不出来时把读到的原文留下。2026-09-09 三趟全挂在下面那个 wait 上，
                # 日志里一个字都没有，查不出是没弹框、弹了没认出、还是被别的窗口挡着。
                self.log_info(f'传送前没认出提示框，这块屏幕读到：{_tip_t[:120]!r}')
        except Exception as _e:
            self.log_info(f'剧情提示框那一步跳过: {_e}')
        try:
            feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'],
                                        time_out=10, settle_time=0.5, raise_if_not_found=True)
        except Exception:
            if not _tipped:
                raise
            # 点完「确认前往」是直接落到战斗场地，既没有传送界面也没有队伍界面，
            # 上游这个 wait 永远等不到 → 每一趟都 Teleport to boss failed。
            # 按「秘境」返回（True）：这个 4C 是副本型的，和周本声骸同一类，
            # 上游给这类写的重复挑战是 enter_configured_boss_realm_from_f——
            # 打完走到结晶按 F、重选等级再进一次。大世界那条对它不适用。
            self.log_info('限时提前开放：确认后直接进场，没有传送界面，按副本 boss 走')
            # 告诉 teleport_to_configured_boss 别再走队伍界面那一套：人已经在场地里，
            # 那边等「开启挑战」等不到，照样报 Teleport to boss failed。
            self._early_open_direct = True
            return True
        return feature.name == 'team_close'"""


# v3 of this patch, kept **only so it can be reverted**.
_BOSSTIP_V3 = """        self.click(target, after_sleep=1)
        # 本地补丁：限时提前开放的 boss（2026-09-09 的天傀劫煞是列表第一个）点
        # 「直接挑战」之后，会先弹一个「提前到达目标位置可能影响剧情体验，是否确认
        # 前往？」。上游不认这个框，下面那个 wait 必然超时 → Teleport to boss failed，
        # 一次都进不去。这个框不花任何资源，只是剧透提醒。
        # **先按文字认框再点**：只看「屏幕上有确认按钮」会把波片不足那类花钱的框
        # 也一起确认掉，那是这个文件绝不能犯的错。
        _tipped = False
        try:
            _tip = self.ocr(box=self.box_of_screen(0.25, 0.40, 0.78, 0.56)) or []
            _tip_t = ' '.join(str(_b) for _b in _tip)
            _tipped = '确认前往' in _tip_t or '剧情体验' in _tip_t
            if _tipped:
                self.log_info('限时提前开放的剧情提示框，点确认前往')
                self.click_dialog_right_button()
            else:
                # 认不出来时把读到的原文留下。2026-09-09 三趟全挂在下面那个 wait 上，
                # 日志里一个字都没有，查不出是没弹框、弹了没认出、还是被别的窗口挡着。
                self.log_info(f'传送前没认出提示框，这块屏幕读到：{_tip_t[:120]!r}')
        except Exception as _e:
            self.log_info(f'剧情提示框那一步跳过: {_e}')
        try:
            feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'],
                                        time_out=10, settle_time=0.5, raise_if_not_found=True)
        except Exception:
            if not _tipped:
                raise
            # 点完「确认前往」是直接落到战斗场地，既没有传送界面也没有队伍界面，
            # 上游这个 wait 永远等不到 → 每一趟都 Teleport to boss failed。
            # 按「秘境」返回（True）：这个 4C 是副本型的，和周本声骸同一类，
            # 上游给这类写的重复挑战是 enter_configured_boss_realm_from_f——
            # 打完走到结晶按 F、重选等级再进一次。大世界那条对它不适用。
            self.log_info('限时提前开放：确认后直接进场，没有传送界面，按副本 boss 走')
            return True
        return feature.name == 'team_close'"""


# v2 of this patch, kept **only so it can be reverted**.
_BOSSTIP_V2 = """        self.click(target, after_sleep=1)
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
            else:
                # 认不出来时把读到的原文留下。2026-09-09 三趟全挂在下面那个 wait 上，
                # 日志里一个字都没有，查不出是没弹框、弹了没认出、还是被别的窗口挡着。
                self.log_info(f'传送前没认出提示框，这块屏幕读到：{_tip_t[:120]!r}')
        except Exception as _e:
            self.log_info(f'剧情提示框那一步跳过: {_e}')
        feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'], time_out=10,
                                    settle_time=0.5, raise_if_not_found=True)"""


# v1 of this patch, kept **only so it can be reverted**: a new version cannot be
# applied over it, and a half-applied patch fails silently.
_BOSSTIP_V1 = """        self.click(target, after_sleep=1)
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
    return "self._early_open_direct = True" in text


_BOSSTIP = _Patch(
    name="限时提前开放的 boss：认出剧情提示框",
    parts=(*_SRC, "BaseWWTask.py"),
    old=_BOSSTIP_OLD_FULL,
    new=_BOSSTIP_NEW,
    present=_bosstip_present,
    breaks="刷天傀劫煞这类限时提前开放的 boss 时一次都传送不进去，整个任务失败",
    unique="限时提前开放的剧情提示框",
)


# The other half of the same fix, on FarmEchoTask. Confirming the spoiler dialog drops
# the player straight into the arena: there is no fast-travel UI and no team screen, so
# both of upstream's branches raise. This one returns as soon as it sees the flag.
_EARLY_OLD = """        is_team = self.click_on_book_target(serial_number, total_number)
        if is_team:"""

_EARLY_NEW = """        is_team = self.click_on_book_target(serial_number, total_number)
        if getattr(self, '_early_open_direct', False):
            # 限时提前开放的 boss：点完「确认前往」人已经在场地里了，既没有队伍
            # 界面也没有传送界面。下面两条分支等的都是那两个界面，等不到就报
            # Teleport to boss failed——2026-09-09 一晚上四趟全挂在这里。
            # 直接按「已经在秘境里」返回，后面的重复挑战照常走 F 重进那条。
            self._early_open_direct = False
            self.log_info('限时提前开放：已经在场地里，跳过队伍和传送这两步')
            return True
        if is_team:"""


def _early_present(text: str) -> bool:
    return "限时提前开放：已经在场地里" in text


_EARLYOPEN = _Patch(
    name="限时提前开放的 boss：进场后跳过队伍和传送界面",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_EARLY_OLD,
    new=_EARLY_NEW,
    present=_early_present,
    breaks="点完确认已经在场地里，却还去等队伍界面，每一趟都报传送失败",
    unique="限时提前开放：已经在场地里",
)
