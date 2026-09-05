"""OK-WW 补丁：reward。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ── 补丁一：领奖置底 ────────────────────────────────────────────
# 上游顺序是 claim_daily → claim_mail → claim_battle_pass → run_additional_tasks，
# 而周常乐园打完**还有奖励要领**，排在领奖之后就永远领不到。
_REWARD_OLD = """        self.claim_daily()

        self.claim_mail()
        self.sleep(1)
        self.claim_battle_pass()
        self.run_additional_tasks()
        self.log_info('Daily Task Completed', notify=True)"""

_REWARD_NEW = """        # 本地补丁：附加任务提到领奖之前。上游顺序把 run_additional_tasks
        # 排在 claim_daily 之后，可周常乐园打完还有奖励要领，就永远领不到。
        # 领奖必须置底，其他任务没有放在领奖之后的必要。
        self.run_additional_tasks()

        self.claim_daily()
        self.claim_mail()
        self.sleep(1)
        self.claim_battle_pass()
        self.log_info('Daily Task Completed', notify=True)"""


def _reward_present(text: str) -> bool:
    """附加任务是不是已经排在领奖前面了。"""
    a = text.find("self.run_additional_tasks()")
    c = text.find("self.claim_daily()")
    return a != -1 and c != -1 and a < c


PATCHES: tuple[_Patch, ...] = (
    _Patch(
        name="领奖顺序",
        parts=(*_SRC, "DailyTask.py"),
        old=_REWARD_OLD, new=_REWARD_NEW, present=_reward_present,
        breaks="周常乐园的奖励会领不到",
    ),
    # 这条是两段替换，用 old/new 表达不了，走 _apply_domain 特判。
)
