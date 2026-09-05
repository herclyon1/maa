"""把本地给 OK-WW 打的补丁重新贴回去——因为它的自动更新会整段覆盖 src。

2026-08-25 打的补丁，到 08-26 全没了：OK-WW 从 v3.6.5 更新到 v3.6.6-beta.1
时整个 `src` 目录被替换，连我留在同目录的 `.bak` 一起消失。用户的原话是
「一个是 bug，两个是功能增加，Bug 可能被修了，但是功能增加我们需要呀」——
功能不能指望上游，只能每次开机自己贴回去。

设计上的三条：

* **幂等。** 已经在就什么都不做，返回空。每次开机跑一遍的代价必须接近零。
* **认不出上游那段就不动。** 上游改了结构还硬替换，只会把文件改坏。
  宁可报「贴不上了」让人去看，也不许猜着改。
* **改完必须回读 + 编译。** 写进去不等于对，语法坏了会让整个日常任务起不来。

**这里只放「非改源码不可」的补丁。** 能在配置层做的一律不要来这儿：
周常乐园的「本周只查一次」就是配置层做的（`garden.py`，照 `annihilation.py`
那套周门写的），因为配置不会被更新覆盖，天然免疫这个问题。

**已提给上游的补丁在合并之后就该从这里删掉**，别让本地版本和上游版本
长期并存——两边都改同一段代码，早晚打架。每条补丁的 `upstream` 字段
记着它的去向。
"""
from __future__ import annotations

from pathlib import Path

from .okww_patches.claim import _CLAIM_OLD, _CLAIM_NEW, _CLAIM_V1, _CLAIM_V2, _CLAIM_V3, _claim_present, _CLAIM
from .okww_patches.core import _SRC, _Patch, _atomic_write, _atomic_write_bytes, _verify_or_revert, _stacked, _apply_one, _revert_text
from .okww_patches.count import _COUNT_OLD, _COUNT_V1, _COUNT_NEW, _count_present, _COUNT
from .okww_patches.domain import _DOMAIN_IMPORT_OLD, _DOMAIN_IMPORT_NEW, _DOMAIN_OLD, _DOMAIN_NEW, _domain_present, _apply_domain
from .okww_patches.farmerr import _FARMERR_OLD, _FARMERR_NEW, _farmerr_present, _FARMERR
from .okww_patches.letpass import _LETPASS_OLD, _LETPASS_NEW, _letpass_present, _LETPASS
from .okww_patches.nest import _NEST_DIR, _NEST_UPSTREAM, _NEST_PATCHED, _sha, _NEST_MARKER, _NEST_KNOWN_OURS, _apply_nest
from .okww_patches.nofarm import _NOFARM_OLD, _NOFARM_NEW, _nofarm_present, _NOFARM
from .okww_patches.nowave import _NOWAVE_OLD, _NOWAVE_V2, _NOWAVE_NEW, _NOWAVE_V1, _NOWAVE_V3A, _NOWAVE_V3B, _nowave_present, _NOWAVE
from .okww_patches.retrycap import _RETRYCAP_OLD, _RETRYCAP_NEW, _retrycap_present, _RETRYCAP
from .okww_patches.reward import _REWARD_OLD, _REWARD_NEW, _reward_present, PATCHES
from .okww_patches.shot import _SHOT_OLD, _SHOT_NEW, _shot_present, _SHOT
from .okww_patches.shot2 import _SHOT2_OLD, _SHOT2_NEW, _shot2_present, _SHOT2
from .okww_patches.stamina import _STAMINA_OLD, _STAMINA_NEW, _stamina_present, _STAMINA
from .okww_patches.starve import _STARVE_OLD, _STARVE_NEW, _starve_present, _apply_starve
from .okww_patches.teamshot import _TEAMSHOT_OLD, _TEAMSHOT_NEW, _teamshot_present, _TEAMSHOT

# 测试和别处按旧名字从这里取，子模块里的名字全部原样再导出。
__all__ = [
    'ensure_patches',
    '_CLAIM_OLD',
    '_CLAIM_NEW',
    '_CLAIM_V1',
    '_CLAIM_V2',
    '_CLAIM_V3',
    '_claim_present',
    '_CLAIM',
    '_SRC',
    '_Patch',
    '_atomic_write',
    '_atomic_write_bytes',
    '_verify_or_revert',
    '_stacked',
    '_apply_one',
    '_revert_text',
    '_COUNT_OLD',
    '_COUNT_V1',
    '_COUNT_NEW',
    '_count_present',
    '_COUNT',
    '_DOMAIN_IMPORT_OLD',
    '_DOMAIN_IMPORT_NEW',
    '_DOMAIN_OLD',
    '_DOMAIN_NEW',
    '_domain_present',
    '_apply_domain',
    '_FARMERR_OLD',
    '_FARMERR_NEW',
    '_farmerr_present',
    '_FARMERR',
    '_LETPASS_OLD',
    '_LETPASS_NEW',
    '_letpass_present',
    '_LETPASS',
    '_NEST_DIR',
    '_NEST_UPSTREAM',
    '_NEST_PATCHED',
    '_sha',
    '_NEST_MARKER',
    '_NEST_KNOWN_OURS',
    '_apply_nest',
    '_NOFARM_OLD',
    '_NOFARM_NEW',
    '_nofarm_present',
    '_NOFARM',
    '_NOWAVE_OLD',
    '_NOWAVE_V2',
    '_NOWAVE_NEW',
    '_NOWAVE_V1',
    '_NOWAVE_V3A',
    '_NOWAVE_V3B',
    '_nowave_present',
    '_NOWAVE',
    '_RETRYCAP_OLD',
    '_RETRYCAP_NEW',
    '_retrycap_present',
    '_RETRYCAP',
    '_REWARD_OLD',
    '_REWARD_NEW',
    '_reward_present',
    'PATCHES',
    '_SHOT_OLD',
    '_SHOT_NEW',
    '_shot_present',
    '_SHOT',
    '_SHOT2_OLD',
    '_SHOT2_NEW',
    '_shot2_present',
    '_SHOT2',
    '_STAMINA_OLD',
    '_STAMINA_NEW',
    '_stamina_present',
    '_STAMINA',
    '_STARVE_OLD',
    '_STARVE_NEW',
    '_starve_present',
    '_apply_starve',
    '_TEAMSHOT_OLD',
    '_TEAMSHOT_NEW',
    '_teamshot_present',
    '_TEAMSHOT',
]


def ensure_patches(okww_dir: Path | None) -> list[str]:
    """确保本地补丁在位。返回这次实际做了什么（空表示本来就在位）。

    来龙去脉见 docs/CODE-HISTORY.md「okww_patch.py:ensure_patches」。
    """
    if not okww_dir:
        return []
    root = Path(okww_dir)
    done: list[str] = []
    done.extend(_apply_nest(root))
    # 2026-08-31 加回来一条：周本要在日常刷体力之前跑，否则只剩 60 体力。
    # 这条不是「上游顺序不合理」的审美问题，是**用户要的分配做不到**：
    # 一次周本宝箱 60 体力，三次就是 180，而日常那步会先把 180 吃光。
    done.extend(_apply_one(root, _STAMINA))
    done.extend(_apply_one(root, _NOFARM))
    # 2026-08-31 撤回：前提就是错的。ok.util.logger.Logger.error 的签名是
    # 来龙去脉见 docs/CODE-HISTORY.md「okww_patch.py:ensure_patches」
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _FARMERR_NEW, _FARMERR_OLD, "周本活锁：打出被吞掉的异常"))
    # 截图补丁已经问到答案（Boss 死后画面上没有自动领奖这回事），还原。
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _SHOT2_NEW, _SHOT2_OLD, "退秘境前留证据截图"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _CLAIM_V1, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v1"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _CLAIM_V2, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v2"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _CLAIM_V3, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v3"))
    done.extend(_apply_one(root, _CLAIM))
    # 取证补丁已经问到答案（画面是「结晶波片不足」弹窗），撤回。
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _TEAMSHOT_NEW, _TEAMSHOT_OLD,
                             "开启挑战找不到时留证据截图"))
    # 历史版本必须先全部还原，否则会叠加：v1/v2 的替换文本末尾都带着
    # 锚点本身，present() 一变就会再贴一层。
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _COUNT_V1, _COUNT_OLD, "进本前拍一张看剩余次数 v1"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _NOWAVE_V1 + "\n", "", "波片不足时跳过周本 v1"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _NOWAVE_V2, _NOWAVE_OLD, "波片不足时跳过周本 v2"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _NOWAVE_V3A, _NOWAVE_OLD, "波片不足时跳过周本 v3a"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _NOWAVE_V3B, _NOWAVE_OLD, "波片不足时跳过周本 v3b"))
    done.extend(_apply_one(root, _NOWAVE))
    done.extend(_apply_one(root, _RETRYCAP))
    done.extend(_apply_one(root, _LETPASS))
    done.extend(_apply_one(root, _COUNT))
    # 截图补丁的问题已经问完了：2026-08-31 拍到的是「确认离开」退出弹窗，
    # 不是领奖弹窗（claim_cancel_button 这个名字指的是通用双按钮弹窗）。
    # 留着只会每打一次 Boss 就多存一张没用的图，所以主动还原。
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _SHOT_NEW, _SHOT_OLD, "周本领奖前留证据截图"))
    # 以下三条：撤销，不是应用。
    for p in PATCHES:
        done.extend(_revert_text(root, p.parts, p.new, p.old, p.name))
    done.extend(_revert_text(root, (*_SRC, "DomainTask.py"),
                             _DOMAIN_NEW, _DOMAIN_OLD, "副本失败不拖垮每日任务"))
    done.extend(_revert_text(root, (*_SRC, "DomainTask.py"),
                             _DOMAIN_IMPORT_NEW, _DOMAIN_IMPORT_OLD,
                             "副本补丁的 import"))
    done.extend(_revert_text(root, (*_SRC, "BaseCombatTask.py"),
                             _STARVE_NEW, _STARVE_OLD, "主C饿死兜底"))
    return done
