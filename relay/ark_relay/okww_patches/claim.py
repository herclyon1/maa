"""OK-WW 补丁：claim。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 真正领周本奖励 --------------------------------------------------------
# 来龙去脉见 docs/CODE-HISTORY.md「claim.py:(模块级)」
_CLAIM_OLD = """                    if self._in_realm and not self.in_world():
                        self.send_key('esc', after_sleep=0.5)"""

_CLAIM_NEW = """                    if self._in_realm and not self.in_world():
                        # 本地补丁：退秘境之前把周本奖励领了。
                        # 弹窗原文（整屏 OCR 读到的）：
                        #   「领取奖励需消耗60点结晶波片，请确认是否领取？」[取消][确认]
                        # has_claim_stamina() 认不出它（已证伪），所以用 OCR 认。
                        # **波片不够时用备用体力**：游戏会再弹一次问要不要用，
                        # 点掉它就行——照抄 BaseWWTask.use_stamina 里那段。
                        # 用户 2026-09-01：「体力还能用，有备用体力，去点击
                        # 使用备用体力的那个。」
                        try:
                            self.walk_to_treasure()
                            self.pick_f(handle_claim=False)
                            self.sleep(2)
                            _o = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0))
                            _txt = ' '.join(str(_b) for _b in (_o or []))
                            if '领取奖励需消耗' in _txt and '结晶波片' in _txt:
                                self.log_info(f'周本领奖：认出弹窗，点确认。读到 {_txt[:70]}')
                                _btn = self.click_dialog_right_button()
                                if self.wait_feature('gem_add_stamina',
                                                     horizontal_variance=0.4,
                                                     vertical_variance=0.05,
                                                     time_out=3, settle_time=0.5):
                                    self.log_info('周本领奖：波片不够，动用备用体力')
                                    self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
                                    self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
                                    self.back(after_sleep=1)
                                    self.click(_btn, after_sleep=1)
                                self.sleep(3)
                                self.log_info('周本领奖：已点确认')
                            else:
                                try:
                                    self.screenshot('no_claim_ui')
                                except Exception:
                                    pass
                                self.log_info(f'周本领奖：没认出领奖弹窗，整屏读到 {_o}')
                        except Exception as _e:
                            self.log_info(f'周本领奖：这一步没做成，按原样退出 {_e!r}')
                        self.send_key('esc', after_sleep=0.5)"""


# 领奖补丁的上一版，留着**只为了还原**。改这条补丁之前必须先把它还原，
# 否则 _apply_one 找不到 old、报「贴不上了」。今晚在这上面栽过三次。
_CLAIM_V1 = """                    if self._in_realm and not self.in_world():
                        # 本地补丁：退秘境之前先把周本奖励领了。
                        # 领奖＝走到结晶前按 F、花 60 波片，不是进本时扣。
                        # has_claim_stamina() 是门：认不出就什么都不花。
                        try:
                            self.walk_to_treasure()
                            self.pick_f(handle_claim=False)
                            self.sleep(2)
                            if self.has_claim_stamina():
                                self.log_info('周本领奖：认出「花体力领取」界面，开始领')
                                _ok, _used = self.use_stamina(once=60, must_use=0)
                                self.log_info(f'周本领奖：已领取，花了 {_used}')
                            else:
                                self.log_info('周本领奖：没认出花体力界面，不领，按原样退出')
                        except Exception as _e:
                            self.log_info(f'周本领奖：这一步没做成，按原样退出 {_e!r}')
                        self.send_key('esc', after_sleep=0.5)"""


# 领奖补丁 v2（加了取证截图那版）的原文，留着**只为了还原**。
_CLAIM_V2 = """                    if self._in_realm and not self.in_world():
                        # 本地补丁：退秘境之前先把周本奖励领了。
                        # 领奖＝走到结晶前按 F、花 60 波片，不是进本时扣。
                        # has_claim_stamina() 是门：认不出就什么都不花。
                        try:
                            self.walk_to_treasure()
                            self.pick_f(handle_claim=False)
                            self.sleep(2)
                            if self.has_claim_stamina():
                                self.log_info('周本领奖：认出「花体力领取」界面，开始领')
                                _ok, _used = self.use_stamina(once=60, must_use=0)
                                self.log_info(f'周本领奖：已领取，花了 {_used}')
                            else:
                                # 认不出就取证：是 F 没按出弹窗，还是弹窗在
                                # 但 claim_stamina_sign 模板不匹配？
                                try:
                                    self.screenshot('no_claim_ui')
                                    _o = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0))
                                    self.log_info(f'周本领奖：没认出，整屏读到 {_o}')
                                except Exception:
                                    pass
                                self.log_info('周本领奖：没认出花体力界面，不领，按原样退出')
                        except Exception as _e:
                            self.log_info(f'周本领奖：这一步没做成，按原样退出 {_e!r}')
                        self.send_key('esc', after_sleep=0.5)"""


# 领奖补丁 v3（带 >=60 门槛那版）的原文，留着**只为了还原**。
_CLAIM_V3 = """                    if self._in_realm and not self.in_world():
                        # 本地补丁：退秘境之前把周本奖励领了。
                        # 领奖弹窗长这样（2026-09-01 整屏 OCR 一字不差读到的）：
                        #   「领取奖励需消耗60点结晶波片，请确认是否领取？」[取消][确认]
                        # has_claim_stamina() 那个模板认不出它——弹窗明明在屏幕上，
                        # 模板仍返回假。所以改用 OCR 认，OCR 是实测可靠的那条路。
                        # 只有波片够 60 才点确认；不够就取消，不白费一次周本次数。
                        try:
                            self.walk_to_treasure()
                            self.pick_f(handle_claim=False)
                            self.sleep(2)
                            _o = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0))
                            _txt = ' '.join(str(_b) for _b in (_o or []))
                            if '领取奖励需消耗' in _txt and '结晶波片' in _txt:
                                _m = re.search(r'(\\d+)\\s*/\\s*240', _txt)
                                _have = int(_m.group(1)) if _m else 0
                                if _have >= 60:
                                    self.log_info(f'周本领奖：确认领取，波片 {_have}')
                                    self.click_dialog_right_button()
                                    self.sleep(3)
                                    self.log_info('周本领奖：已点确认')
                                else:
                                    self.log_info(f'周本领奖：波片只有 {_have}，不够 60，取消')
                                    self.click_dialog_left_button()
                                    self.sleep(1)
                            else:
                                try:
                                    self.screenshot('no_claim_ui')
                                except Exception:
                                    pass
                                self.log_info(f'周本领奖：没认出领奖弹窗，整屏读到 {_o}')
                        except Exception as _e:
                            self.log_info(f'周本领奖：这一步没做成，按原样退出 {_e!r}')
                        self.send_key('esc', after_sleep=0.5)"""


def _claim_present(text: str) -> bool:
    return "周本领奖：认出弹窗，点确认" in text


_CLAIM = _Patch(
    name="打完 Boss 真正领周本奖励",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_CLAIM_OLD,
    new=_CLAIM_NEW,
    present=_claim_present,
    breaks="周本永远只是刷声骸，奖励一次都领不到（本周 3/3 就是这么来的）",
)
