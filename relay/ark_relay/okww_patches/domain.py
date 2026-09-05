"""OK-WW 补丁：domain。从 okww_patch.py 拆出（2026-09-06，只搬不改）。"""
from __future__ import annotations

import logging
from pathlib import Path

from .core import _SRC, _atomic_write, _verify_or_revert

log = logging.getLogger("ark.okww_patch")




# ── 补丁二：副本没打通不该把整个每日任务带走 ──────────────────
# 来龙去脉见 docs/CODE-HISTORY.md「domain.py:(模块级)」
_DOMAIN_IMPORT_OLD = "from ok import Logger\n"
_DOMAIN_IMPORT_NEW = "from ok import Logger, WaitFailedException\n"

_DOMAIN_OLD = """            except (NotInCombatException, CharDeadException):
                self.log_info('farm_in_domain: death recovered, exiting domain')"""

# 下面这段必须和提给上游的 PR 一字不差，否则本地版和上游版会悄悄分叉。
_DOMAIN_NEW = """            except (NotInCombatException, CharDeadException, WaitFailedException):
                # WaitFailedException: 副本没打通（限时结束 / 敌人没清完）就不会掉宝箱，
                # walk_to_treasure 找不到目标会抛它。和死亡一样当成“这一局没打成”，
                # 交给 farm_domain_with_recovery_loop 重进；否则它会一路抛到
                # DailyTask.run，把后面的领奖和附加任务全带走。
                self.log_info('farm_in_domain: attempt failed, exiting domain')"""


def _domain_present(text: str) -> bool:
    return ("NotInCombatException, CharDeadException, WaitFailedException" in text
            and "from ok import Logger, WaitFailedException" in text)


def _apply_domain(root: Path) -> list[str]:
    """副本失败不再拖垮整个每日任务。两段替换，所以单独走一条路。"""
    f = root.joinpath(*_SRC, "DomainTask.py")
    label = "副本失败不拖垮每日任务"
    if not f.exists():
        return [f"OK-WW 补丁：找不到 DomainTask.py，{label} 没能检查"]
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return ["OK-WW 补丁：读不了 DomainTask.py"]

    if _domain_present(text):
        return []
    if _DOMAIN_IMPORT_OLD not in text or _DOMAIN_OLD not in text:
        log.warning("OK-WW 补丁：认不出上游 DomainTask 那两段，不动它")
        return [f"OK-WW 补丁：{label}**贴不上了**（上游结构变了）——"
                "多半是上游已经自己修了，去核对一下就能把这条补丁删掉"]

    new = (text.replace(_DOMAIN_IMPORT_OLD, _DOMAIN_IMPORT_NEW, 1)
               .replace(_DOMAIN_OLD, _DOMAIN_NEW, 1))
    bak = _atomic_write(f, new)
    if bak is None:
        return [f"OK-WW 补丁：{label} 写不进去，副本打不通时每日任务还会整个中断"]
    if err := _verify_or_revert(f, bak, _domain_present, label):
        return [err]
    log.info("OK-WW 补丁：%s 已重新贴上", label)
    return [f"OK-WW 补丁：{label} 已重新贴上（上次更新把它覆盖了）"]
