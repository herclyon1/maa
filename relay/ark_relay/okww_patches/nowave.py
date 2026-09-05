"""OK-WW 补丁：nowave。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ---- 波片不足时干净跳过，不空转不白打 --------------------------------------
#
# 2026-08-31 拍到了失败那一刻的画面，游戏弹的是：
#     「结晶波片不足，无法获取奖励，请确认是否继续进入？」[取消][确认]
#
# 三件事因此对上了：
#   * 周本没有「打完开宝箱」这一步，奖励是**进本时扣 60 结晶波片**直接给的；
#   * 波片不够时这个弹窗**挡住了「开启挑战」**，wait_click_feature 超时抛
#     WaitFailedException，run() 兜底又递归重来 → 12:35→12:47 空转 21 圈；
#   * 选「确认」是不拿奖励地进去，所以三轮打完体力 56→56 一动没动，纯白打。
#
# 波片不够进去也拿不到奖励，正确做法是点「取消」并把这次周本安静跳过。
# 抛 TaskDisabledException 是因为 run() 对它的处理就是 `pass`——
# FarmEchoTask 静默结束，日常任务继续往下跑，不会像抛普通异常那样
# 把整个日常带崩（我 16:00 那次就是这么崩的）。
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


# v1 那一版的原文。留着**只为了还原**：它的替换文本末尾自带锚点
# `self.click_team_challenge()`，所以我把 present() 改成认 v3 之后，
# _apply_one 又在它上面贴了一层——两段检查同时存在，v1 在前面先跑，
# 而 v1 正是会误判的那版。2026-09-01 实测：波片 91（>60）也被判成
# 「不足」跳过了。补丁的 new 里带着自己的 old，是这次叠加的根源。
_NOWAVE_V1 = """            # 本地补丁：波片不足时游戏会弹「无法获取奖励，是否继续进入」，
            # 它挡住「开启挑战」，上游只会超时→重试→再传送，空转。
            # 进去也拿不到奖励，所以点「取消」并安静跳过这次周本。
            if self.ocr(box=self.box_of_screen(0.25, 0.40, 0.75, 0.56),
                        match=re.compile('结晶波片不足|无法获取奖励')):
                self.log_info('结晶波片不足，取消并跳过本次周本')
                self.click_dialog_left_button()
                self.sleep(1)
                raise TaskDisabledException()"""


# 上一版 v3 的原文，留着**只为了还原**。它把锚点 click_team_challenge()
# 整句吃掉了，所以再想改这条补丁，必须先把它还原成上游原样，
# 否则 _apply_one 找不到 old、报「贴不上了」——2026-09-01 就是这样，
# 而我 grep 部署输出时只筛了「部署完成/❌」，把那条告警漏了过去，
# 机器上跑了 95 分钟的空转我却以为新补丁在跑。
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


# 上一版（取证只拍图不处理那版），留着只为了还原。
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
    # 认 **这一版独有** 的字串。只认那句没变过的日志会让改动静默不部署——
    # 2026-08-31 已经栽过一次：v2 加了调试输出，判据没跟着改，
    # _apply_one 判成「已在位」直接返回，我却在日志里找那行输出。
    return "波片不足挡住开启挑战" in text


_NOWAVE = _Patch(
    name="波片不足时跳过周本",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_NOWAVE_OLD,
    new=_NOWAVE_NEW,
    present=_nowave_present,
    breaks="波片不够时周本会空转十几分钟，而且是不拿奖励地白打",
    # v1 和 v3 都会打这句日志，所以它出现两次＝两段检查并存。
    unique="结晶波片不足，取消并跳过本次周本",
)
