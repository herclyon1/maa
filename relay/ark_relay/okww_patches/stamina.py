"""OK-WW patch: stamina. Split out of okww_patch.py (2026-09-06, moved verbatim)."""
from __future__ import annotations


from .core import _SRC, _Patch




# ── Patch: move the additional tasks ahead of stamina farming ──────────
# The weekly boss (战歌重奏) sits in the additional tasks, and opening one chest
# there costs 60 stamina. The daily farming step does
# `must_use = 180 - used_stamina`, so it eats stamina up to 180 first — the
# weekly boss runs after it with only 60 left and opens one of the three chests.
#
# After the move: the weekly boss spends the 180 first, we return to the main
# screen and re-read stamina, and the daily step then decides on its own that no
# farming is needed (`need_stamina = not daily_reward_ready and used_stamina < 180`).
#
# **Stamina must be re-read**: without the re-read `used_stamina` is still the
# value from before the boss fight, the daily step farms another 180, and we pay
# at both ends — 360 stamina a day.
# **ensure_main must come first**: after the boss fight we are not on the main
# screen, and opening the daily panel from there fails.
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
    """Are the additional tasks already ordered ahead of stamina farming?

    The test must not be `if need_stamina:` — the new version removes that branch
    entirely (stamina is farmed until it runs out, no longer gated on "is there at
    least 180"). On 2026-08-31 this test failed to follow that change: the patch
    was applied, our own check then judged it "not applied", and it was reverted
    on the spot.
    """
    # Anchor on claim_daily: `Which to Farm` also appears in the earlier
    # nightmare check, so anchoring on that would always report "not applied"
    # (hit on 2026-08-31).
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
