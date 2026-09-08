"""OK-WW patch: revive inside a boss realm while farming echoes.

Upstream's FarmEchoTask gives up on reviving as soon as it is in a realm - there is
no teleport tower to run back to, so `revive_action` returns False, the death becomes
a CharDeadException and OK-WW stops the whole task. That is right for a weekly boss,
which is meant to run once. It is wrong for an overnight echo farm: on 2026-09-09 the
character died three times and each death left the machine standing still until
someone noticed, the last one for 25 minutes.

The death popup itself is on screen and OK-WW already recognises it - that is how it
decides the character is dead. So while the farm marker file is present, find the
revive button by its own text, click it, and let the loop take the next lap. Reading
the button rather than clicking a fixed spot keeps this from confirming some other
dialog, the mistake this whole patch set exists to avoid.
"""
from __future__ import annotations

from .core import _SRC, _Patch

_FE_PARTS = (*_SRC, "FarmEchoTask.py")


_REVIVE_OLD = """    def revive_action(self):
        if self._in_realm:
            return False"""

_REVIVE_NEW = """    def revive_action(self):
        if self._in_realm:
            # 本地补丁：秘境里没有传送点可回，上游到这里就放弃复活，于是角色一死
            # 整个任务就停掉。刷声骸是通宵跑的，停一次就白站一整晚——2026-09-09
            # 死了三次，最后一次站了 25 分钟。死亡弹窗本身就在屏幕上（OK-WW 正是
            # 靠认出它才判定角色死了），按文字找到「复活」点掉，接着刷下一趟。
            # **按文字找按钮**，不按固定坐标：固定坐标会把别的弹窗一起点掉。
            import os as _os
            if not _os.path.exists('C:/ProgramData/ark-okww-farm.no-claim'):
                return False
            try:
                _o = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
                _btn = next((_b for _b in _o
                             if any(_k in str(_b) for _k in ('复活', '复苏', '原地'))), None)
                if _btn is None:
                    self.log_info(f'刷声骸模式：死亡弹窗上没找到复活按钮，整屏读到 {_o}')
                    return False
                self.log_info(f'刷声骸模式：角色阵亡，点「{_btn}」复活，接着刷')
                self.click(_btn, after_sleep=3)
                self.wait_in_team_and_world(time_out=120)
                self.is_revived = True
                return True
            except Exception as _e:
                self.log_info(f'刷声骸模式：复活这一步没做成 {_e!r}')
                return False"""


def _revive_present(text: str) -> bool:
    return "刷声骸模式：角色阵亡，点" in text


_REVIVE = _Patch(
    name="刷声骸时角色阵亡就原地复活",
    parts=_FE_PARTS,
    old=_REVIVE_OLD,
    new=_REVIVE_NEW,
    present=_revive_present,
    breaks="角色一死整趟就停，剩下的时间全站着不动",
    unique="刷声骸模式：角色阵亡，点",
)


# Reviving is only half of it: the revived death still travels up as an exception and
# upstream's loop only knows how to recover the overworld case, so the task would stop
# anyway. These two make the loop take the next lap instead.
_REVIVEIMP_OLD = "from src.task.BaseCombatTask import BaseCombatTask, white_color"

_REVIVEIMP_NEW = ("from src.task.BaseCombatTask import (BaseCombatTask, white_color,\n"
                  "                                     CharRevivedException)")


def _reviveimp_present(text: str) -> bool:
    return "CharRevivedException)" in text


_REVIVEIMP = _Patch(
    name="刷声骸复活：把复活异常引进来",
    parts=_FE_PARTS,
    old=_REVIVEIMP_OLD,
    new=_REVIVEIMP_NEW,
    present=_reviveimp_present,
    breaks="下面那条捕获复活异常的补丁会直接报名字没定义",
    unique="CharRevivedException)",
)


_REVIVELOOP_OLD = """            except TaskDisabledException:
                raise
            except Exception as e:
                if self.should_reteleport_after_farm_exception():"""

_REVIVELOOP_NEW = """            except TaskDisabledException:
                raise
            except CharRevivedException:
                # 本地补丁：原地复活成功了就接着刷下一趟。上游只给大世界那条写了
                # 「出错就重新传送」，秘境这条一路往上抛，任务照样停。
                self.log_info('刷声骸模式：复活成功，接着刷下一趟')
                self.is_revived = False
                continue
            except Exception as e:
                if self.should_reteleport_after_farm_exception():"""


def _reviveloop_present(text: str) -> bool:
    return "刷声骸模式：复活成功，接着刷下一趟" in text


_REVIVELOOP = _Patch(
    name="刷声骸复活后继续下一趟",
    parts=_FE_PARTS,
    old=_REVIVELOOP_OLD,
    new=_REVIVELOOP_NEW,
    present=_reviveloop_present,
    breaks="复活了也没用，异常一路抛上去，任务照样停",
    unique="刷声骸模式：复活成功，接着刷下一趟",
)
