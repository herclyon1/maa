"""OK-WW patch: nowave. Split out of okww_patch.py (2026-09-06, moved verbatim)."""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- Skip cleanly when waveplates are short: no spinning, no unrewarded runs ----
# 来龙去脉见 docs/CODE-HISTORY.md「nowave.py:(模块级)」
_NOWAVE_OLD = """            self.click_team_challenge()"""

_NOWAVE_V2 = """            # 本地补丁：波片不足时游戏会弹「无法获取奖励，是否继续进入」，
            # 它挡住「开启挑战」，上游只会超时→重试→再传送，空转。
            # 进去也拿不到奖励，所以点「取消」并安静跳过这次周本。
            # v2：先无条件读一次并打进日志。v1 用 ocr(match=正则) 判，
            # 实测一次都没命中（36 点波片照样进本白打），先看清读到的是什么。
            _seen = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60))
            self.log_info(f'v2 开启挑战前读到: {_seen}')
            try:
                self.screenshot('before_start_challenge')
            except Exception:
                pass
            if any('结晶波片' in str(b) or '无法获取奖励' in str(b) for b in (_seen or [])):
                self.log_info('结晶波片不足，取消并跳过本次周本')
                self.click_dialog_left_button()
                self.sleep(1)
                raise TaskDisabledException()
            self.click_team_challenge()"""


_NOWAVE_NEW = """            # 本地补丁 v3：波片不足的弹窗是**点了「开启挑战」之后**才弹的。
            # v1/v2 把检查放在点之前，那时画面还是配队页，OCR 读到空表，
            # 一次都没命中（2026-08-31 实测：本周 3/3 一次奖励都没领到，
            # 三轮 Boss 全是不拿奖励地白打）。
            # 上游 click_team_challenge() 里紧跟着 wait_click_skip_dialog_confirm()，
            # 会把弹窗上的「确认」点掉——「确认」的意思正是「不拿奖励继续进入」。
            # 所以把那两步拆开：先点开启挑战，再看弹窗，有就点「取消」并跳过。
            try:
                self.wait_click_feature('team_start_challenge', raise_if_not_found=True,
                                        click_after_delay=0.5, after_sleep=1)
            except Exception:
                # 「开启挑战」等不到，几乎都是弹窗挡住了。2026-09-01 实测：
                # 点「单人挑战」后弹「结晶波片不足，无法获取奖励，请确认是否
                # 继续进入？」，把按钮整个挡住——上一版在这里只拍图就 raise，
                # 81 轮取证图每一轮都读到了弹窗原文，却没人处理，run() 兜底
                # 无上限重试转了 50 分钟。认出弹窗就点取消、干净跳过。
                _s = []
                try:
                    _s = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
                except Exception:
                    pass
                _t = ' '.join(str(_b) for _b in _s)
                if '结晶波片不足' in _t or '无法获取奖励' in _t:
                    self.log_info('波片不足挡住开启挑战，点取消跳过本次周本')
                    try:
                        self.click_dialog_left_button()
                        self.sleep(1)
                    except Exception:
                        pass
                    raise TaskDisabledException()
                try:
                    self.screenshot('no_start_btn')
                    self.log_info(f'找不到开启挑战，整屏读到: {_s}')
                except Exception:
                    pass
                raise
            _seen = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60))
            self.log_info(f'v3 开启挑战后读到: {_seen}')
            if any('结晶波片' in str(_b) or '无法获取奖励' in str(_b) for _b in (_seen or [])):
                self.log_info('结晶波片不足，取消并跳过本次周本')
                try:
                    self.screenshot('nowave_dialog')
                except Exception:
                    pass
                self.click_dialog_left_button()
                self.sleep(1)
                raise TaskDisabledException()
            self.wait_click_skip_dialog_confirm()"""


# The v1 text. Kept **only so it can be reverted**: its replacement text carries
# the anchor at its own tail, so unless the file is restored to upstream's original
# first, the new patch will not apply — and failing to apply is silent.
# 来龙去脉见 docs/CODE-HISTORY.md「nowave.py:(模块级)」
_NOWAVE_V1 = """            # 本地补丁：波片不足时游戏会弹「无法获取奖励，是否继续进入」，
            # 它挡住「开启挑战」，上游只会超时→重试→再传送，空转。
            # 进去也拿不到奖励，所以点「取消」并安静跳过这次周本。
            if self.ocr(box=self.box_of_screen(0.25, 0.40, 0.75, 0.56),
                        match=re.compile('结晶波片不足|无法获取奖励')):
                self.log_info('结晶波片不足，取消并跳过本次周本')
                self.click_dialog_left_button()
                self.sleep(1)
                raise TaskDisabledException()"""


# The previous v3 text, kept **only so it can be reverted**. It swallowed the whole
# anchor line click_team_challenge(), so before this patch can be changed again the
# file must be restored to upstream's original, or the new one will not apply.
# 来龙去脉见 docs/CODE-HISTORY.md「nowave.py:(模块级)」
_NOWAVE_V3A = """            # 本地补丁 v3：波片不足的弹窗是**点了「开启挑战」之后**才弹的。
            # v1/v2 把检查放在点之前，那时画面还是配队页，OCR 读到空表，
            # 一次都没命中（2026-08-31 实测：本周 3/3 一次奖励都没领到，
            # 三轮 Boss 全是不拿奖励地白打）。
            # 上游 click_team_challenge() 里紧跟着 wait_click_skip_dialog_confirm()，
            # 会把弹窗上的「确认」点掉——「确认」的意思正是「不拿奖励继续进入」。
            # 所以把那两步拆开：先点开启挑战，再看弹窗，有就点「取消」并跳过。
            self.wait_click_feature('team_start_challenge', raise_if_not_found=True,
                                    click_after_delay=0.5, after_sleep=1)
            _seen = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60))
            self.log_info(f'v3 开启挑战后读到: {_seen}')
            if any('结晶波片' in str(_b) or '无法获取奖励' in str(_b) for _b in (_seen or [])):
                self.log_info('结晶波片不足，取消并跳过本次周本')
                try:
                    self.screenshot('nowave_dialog')
                except Exception:
                    pass
                self.click_dialog_left_button()
                self.sleep(1)
                raise TaskDisabledException()
            self.wait_click_skip_dialog_confirm()"""


# The version before that (evidence only: screenshot, no handling), kept only so it
# can be reverted.
_NOWAVE_V3B = """            # 本地补丁 v3：波片不足的弹窗是**点了「开启挑战」之后**才弹的。
            # v1/v2 把检查放在点之前，那时画面还是配队页，OCR 读到空表，
            # 一次都没命中（2026-08-31 实测：本周 3/3 一次奖励都没领到，
            # 三轮 Boss 全是不拿奖励地白打）。
            # 上游 click_team_challenge() 里紧跟着 wait_click_skip_dialog_confirm()，
            # 会把弹窗上的「确认」点掉——「确认」的意思正是「不拿奖励继续进入」。
            # 所以把那两步拆开：先点开启挑战，再看弹窗，有就点「取消」并跳过。
            try:
                self.wait_click_feature('team_start_challenge', raise_if_not_found=True,
                                        click_after_delay=0.5, after_sleep=1)
            except Exception:
                # 找不到「开启挑战」时留一张图再抛。2026-09-01 波片 91（够）
                # 却仍然找不到，且之前几趟这一步是成功的——不是必然失败，
                # 光看日志说不清那一刻画面是什么，只能拍下来。
                try:
                    self.screenshot('no_start_btn')
                    _s = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0))
                    self.log_info(f'找不到开启挑战，整屏读到: {_s}')
                except Exception:
                    pass
                raise
            _seen = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60))
            self.log_info(f'v3 开启挑战后读到: {_seen}')
            if any('结晶波片' in str(_b) or '无法获取奖励' in str(_b) for _b in (_seen or [])):
                self.log_info('结晶波片不足，取消并跳过本次周本')
                try:
                    self.screenshot('nowave_dialog')
                except Exception:
                    pass
                self.click_dialog_left_button()
                self.sleep(1)
                raise TaskDisabledException()
            self.wait_click_skip_dialog_confirm()"""


def _nowave_present(text: str) -> bool:
    # Match a string that is **unique to this version**. Matching only the log line
    # that never changes lets a change go undeployed silently — this bit us on
    # 2026-08-31: v2 added debug output, the test was not updated along with it,
    # _apply_one judged the patch "already in place" and returned, while I was
    # looking for that output in the log.
    return "波片不足挡住开启挑战" in text


_NOWAVE = _Patch(
    name="波片不足时跳过周本",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_NOWAVE_OLD,
    new=_NOWAVE_NEW,
    present=_nowave_present,
    breaks="波片不够时周本会空转十几分钟，而且是不拿奖励地白打",
    # v1 and v3 both emit this log line, so two occurrences means two checks coexist.
    unique="结晶波片不足，取消并跳过本次周本",
)
