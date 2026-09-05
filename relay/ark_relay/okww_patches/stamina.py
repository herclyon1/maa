"""OK-WW 补丁：stamina。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations


from .core import _SRC, _Patch




# ── 补丁：附加任务提到体力刷取之前 ──────────────────────────────
# 周本（战歌重奏）在附加任务里，开一个宝箱要 60 体力。而日常刷取那步
# `must_use = 180 - used_stamina`，会先把体力吃到 180——排在后面的周本
# 就只剩 60，三个宝箱只开得到一个。
#
# 提前之后：周本先花掉 180，回主界面重读一次体力，日常那步自己就判定
# 不需要再刷了（`need_stamina = not daily_reward_ready and used_stamina < 180`）。
#
# **必须重读体力**：不重读的话 `used_stamina` 还是打 Boss 之前的值，
# 日常照样再刷 180，等于两头都花，一天要 360 体力。
# **必须先 ensure_main**：打完 Boss 人不在主界面，直接翻日常面板会失败。
_STAMINA_OLD = """        if need_stamina:
            target = self.config.get('Which to Farm', self.support_tasks[0])
            if target == self.support_tasks[0]:
                self.get_task_by_class(TacetTask).farm_tacet(daily=True, used_stamina=used_stamina,
                                                             config=self.config)
            elif target == self.support_tasks[1]:
                self.get_task_by_class(ForgeryTask).farm_forgery(daily=True, used_stamina=used_stamina,
                                                                 config=self.config)
            else:
                self.get_task_by_class(SimulationTask).farm_simulation(daily=True, used_stamina=used_stamina,
                                                                       config=self.config)
            self.sleep(4)

        self.claim_daily()

        self.claim_mail()
        self.sleep(1)
        self.claim_battle_pass()
        self.run_additional_tasks()
        self.log_info('Daily Task Completed', notify=True)"""

_STAMINA_NEW = """        # 本地补丁：附加任务提到体力刷取之前，而且体力要花完。
        # 周本在附加任务里，开一个宝箱 60 体力；日常刷取那步
        # must_use = 180 - used_stamina，排在前面就先把 180 吃光，
        # 轮到周本只剩 60，三个宝箱只开得到一个。
        # daily=False → must_use=0 → 刷到体力不够进本为止，
        # 所以周本花掉的那 180 之外，剩下的也不会闲置。
        self.run_additional_tasks()
        self.ensure_main(time_out=180)
        self.open_daily()

        target = self.config.get('Which to Farm', self.support_tasks[0])
        if target == self.support_tasks[0]:
            self.get_task_by_class(TacetTask).farm_tacet(config=self.config)
        elif target == self.support_tasks[1]:
            self.get_task_by_class(ForgeryTask).farm_forgery(config=self.config)
        else:
            self.get_task_by_class(SimulationTask).farm_simulation(config=self.config)
        self.sleep(4)

        self.claim_daily()

        self.claim_mail()
        self.sleep(1)
        self.claim_battle_pass()
        self.log_info('Daily Task Completed', notify=True)"""


def _stamina_present(text: str) -> bool:
    """附加任务是不是已经排在体力刷取前面了。

    判据不能用 `if need_stamina:`——新版把那个分支整个去掉了（体力要刷到光，
    不再按「够不够 180」来决定刷不刷）。2026-08-31 就因为这个判据没跟上，
    补丁贴上去之后被自己判成「没贴上」，当场还原。
    """
    # 判据用 claim_daily：`Which to Farm` 在更早的梦魇判定里也出现过，
    # 拿它当锚点会永远判成「没贴上」（2026-08-31 踩过）。
    a = text.find("self.run_additional_tasks()")
    b = text.find("self.claim_daily()")
    return a != -1 and b != -1 and a < b


_STAMINA = _Patch(
    name="附加任务先于体力刷取，且体力刷到光",
    parts=(*_SRC, "DailyTask.py"),
    old=_STAMINA_OLD,
    new=_STAMINA_NEW,
    present=_stamina_present,
    breaks="周本只能分到日常刷剩的 60 体力，三个宝箱只开得到一个；且剩余体力会闲置",
    upstream="ok-oldking/ok-wuthering-waves#1647",
)
