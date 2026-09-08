"""Re-apply our local patches to OK-WW - its auto-update replaces `src` wholesale.

The patches applied on 2026-08-25 were all gone by 08-26: updating OK-WW from
v3.6.5 to v3.6.6-beta.1 replaced the entire `src` directory, taking the `.bak`
files left beside them with it. The user's own words:
「一个是 bug，两个是功能增加，Bug 可能被修了，但是功能增加我们需要呀」
(one is a bug, two are feature additions; the bug may have been fixed, but we
need the features). The features cannot be left to upstream, so they get
re-applied on every boot.

Three design rules:

* **Idempotent.** Already there means do nothing and return nothing. Running this
  once per boot must cost close to zero.
* **If the upstream text is unrecognisable, leave it alone.** Forcing a
  replacement after upstream restructured the code just corrupts the file.
  Better to report "this no longer applies" and have a human look than to patch
  by guesswork.
* **Every write is followed by a read-back and a compile.** Written is not the
  same as correct, and broken syntax stops the whole daily task from starting.

**Only patches that genuinely require touching the source belong here.** Anything
achievable at the config layer must not come here: the weekly garden's "check
once a week" lives in the config layer (`garden.py`, modelled on the weekly gate
in `annihilation.py`), because config is not overwritten by updates and is
therefore immune to this problem by construction.

**A patch that has been accepted upstream should be deleted from here once it is
merged** - do not leave the local version and the upstream version coexisting for
long, because both edit the same code and will eventually collide. Each patch's
`upstream` field records where it went.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .okww_patches.tacetshot import _TACETSHOT_OLD, _TACETSHOT_NEW, _TACETSHOT_V1, _TACETSHOT_V1_OLD, _tacetshot_present, _TACETSHOT
from .okww_patches.claim import _CLAIM_OLD, _CLAIM_NEW, _CLAIM_V1, _CLAIM_V2, _CLAIM_V3, _CLAIM_V4, _CLAIM_TAIL, _CLAIM_OLD_FULL, _claim_present, _CLAIM
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

log = logging.getLogger("ark.okww_patch")

# The tests and other callers import the old names from here, so every name in
# the submodules is re-exported verbatim.
__all__ = [
    'ensure_patches', 'ensure_if_updated',
    '_CLAIM_OLD',
    '_CLAIM_NEW',
    '_CLAIM_V1',
    '_CLAIM_V2',
    '_CLAIM_V3',
    '_CLAIM_V4',
    '_CLAIM_TAIL',
    '_CLAIM_OLD_FULL',
    '_TACETSHOT_OLD', '_TACETSHOT_NEW', '_TACETSHOT_V1', '_TACETSHOT_V1_OLD', '_tacetshot_present', '_TACETSHOT',
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


def ensure_if_updated(state_dir: Path, okww_dir: Path | None) -> list[str]:
    """Re-apply only when OK-WW's version changed; otherwise do nothing. Used by
    engine.tick.

    OK-WW updates itself when it launches, which is not necessarily during the
    boot-time pre-update: on 2026-09-06 the pre-update said 「无需更新」 at 08:46,
    and then the 09:20 round installed a new version on launch, replacing all of
    `src` and wiping every patch. That round ran unpatched until the service was
    restarted at 11:30. The version lives in `current_version` inside
    data/apps/ok-ww/app.json; check it every round and re-apply when it changed.
    """
    if not okww_dir:
        return []
    app = Path(okww_dir) / "data" / "apps" / "ok-ww" / "app.json"
    try:
        import json  # noqa: PLC0415
        version = str(json.loads(app.read_text(encoding="utf-8")).get("current_version") or "")
    except (OSError, ValueError):
        return []
    if not version:
        return []
    from .statestore import StateStore  # noqa: PLC0415
    store = StateStore(state_dir)
    seen = str(store.get("versions", "okww") or "")
    if seen == version:
        return []
    notes = ensure_patches(okww_dir)
    try:
        store.set("versions", "okww", version)
    except OSError:
        log.warning("记不住 OK-WW 版本号，下一轮会再贴一遍（幂等，无害）")
    if seen and notes:
        notes.insert(0, f"OK-WW 从 {seen} 换成了 {version}，补丁重新贴上")
    return notes


def ensure_patches(okww_dir: Path | None) -> list[str]:
    """Make sure the local patches are in place. Returns what was actually done
    this time (empty means everything was already in place).

    来龙去脉见 docs/CODE-HISTORY.md「okww_patch.py:ensure_patches」。
    """
    if not okww_dir:
        return []
    root = Path(okww_dir)
    done: list[str] = []
    done.extend(_apply_nest(root))
    # Restored on 2026-08-31: the weekly boss has to run before the daily stamina
    # farming, otherwise only 60 stamina is left. This is not an aesthetic
    # complaint about upstream ordering, it makes **the allocation the user asked
    # for impossible**: one weekly-boss chest costs 60 stamina, three cost 180,
    # and the daily step burns all 180 first.
    done.extend(_apply_one(root, _STAMINA))
    done.extend(_apply_one(root, _NOFARM))
    # Withdrawn on 2026-08-31, so what happens here is a **revert**: the premise
    # was wrong to begin with - OK-WW's own error() already prints the stack, and
    # the exception was never swallowed.
    # 来龙去脉见 docs/CODE-HISTORY.md「okww_patch.py:ensure_patches」
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _FARMERR_NEW, _FARMERR_OLD, "周本活锁：打出被吞掉的异常"))
    # The screenshot patch has answered its question (there is no auto-claim on
    # screen after the boss dies), so revert it.
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _SHOT2_NEW, _SHOT2_OLD, "退秘境前留证据截图"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _CLAIM_V1, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v1"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _CLAIM_V2, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v2"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _CLAIM_V3, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v3"))
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _CLAIM_V4, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v4"))
    done.extend(_apply_one(root, _CLAIM))
    done.extend(_revert_text(root, (*_SRC, "TacetTask.py"),
                             _TACETSHOT_V1, _TACETSHOT_V1_OLD, "无音区留两张图给日报 v1"))
    done.extend(_apply_one(root, _TACETSHOT))
    # The evidence patch has answered its question (the screen shows the
    # 「结晶波片不足」 popup), so withdraw it.
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _TEAMSHOT_NEW, _TEAMSHOT_OLD,
                             "开启挑战找不到时留证据截图"))
    # Every historical version has to be reverted first or they stack: the v1/v2
    # replacement texts each end with the anchor itself, so one change to
    # present() applies another layer on top.
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
    # The screenshot patch's question is settled: what it captured on 2026-08-31
    # was the 「确认离开」 exit popup, not a claim popup (the name
    # claim_cancel_button refers to the generic two-button popup). Keeping it only
    # saves one useless image per boss fight, so revert it deliberately.
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _SHOT_NEW, _SHOT_OLD, "周本领奖前留证据截图"))
    # The three below are reverts, not applications.
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
