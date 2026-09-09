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
from .okww_patches.bosstip import (_BOSSTIP_OLD, _BOSSTIP_OLD_FULL, _BOSSTIP_NEW, _BOSSTIP_V1,
                                   _BOSSTIP_V2, _BOSSTIP_V3, _bosstip_present, _BOSSTIP,
                                   _EARLY_OLD, _EARLY_NEW, _EARLYOPEN)
from .okww_patches.revive import (_REVIVE, _REVIVE_OLD, _REVIVE_NEW, _REVIVE_V1, _REVIVEIMP,
                                  _REVIVEIMP_OLD, _REVIVEIMP_NEW, _REVIVELOOP,
                                  _REVIVELOOP_OLD, _REVIVELOOP_NEW)
from .okww_patches.claim import _CLAIM_OLD, _CLAIM_NEW, _CLAIM_V1, _CLAIM_V2, _CLAIM_V3, _CLAIM_V4, _CLAIM_V5, _CLAIM_V6, _CLAIM_TAIL, _CLAIM_OLD_FULL, _claim_present, _CLAIM
from .okww_patches.core import _SRC, _Patch, _atomic_write, _atomic_write_bytes, _verify_or_revert, _stacked, _apply_one, _revert_text
from .okww_patches.count import _COUNT_OLD, _COUNT_V1, _COUNT_V2, _COUNT_NEW, _count_present, _COUNT
from .okww_patches.domain import _DOMAIN_IMPORT_OLD, _DOMAIN_IMPORT_NEW, _DOMAIN_OLD, _DOMAIN_NEW, _domain_present, _apply_domain
from .okww_patches.farmerr import _FARMERR_OLD, _FARMERR_NEW, _farmerr_present, _FARMERR
from .okww_patches.letpass import _LETPASS_OLD, _LETPASS_NEW, _letpass_present, _LETPASS
from .okww_patches.nest import _NEST_DIR, _NEST_UPSTREAM, _NEST_PATCHED, _sha, _NEST_MARKER, _NEST_KNOWN_OURS, _apply_nest, nest_patch_present
from .okww_patches.nofarm import _NOFARM_OLD, _NOFARM_NEW, _nofarm_present, _NOFARM
from .okww_patches.nowave import _NOWAVE_OLD, _NOWAVE_V2, _NOWAVE_NEW, _NOWAVE_V1, _NOWAVE_V3A, _NOWAVE_V3B, _nowave_present, _NOWAVE
from .okww_patches.retrycap import _RETRYCAP_OLD, _RETRYCAP_NEW, _retrycap_present, _RETRYCAP
from .okww_patches.reward import _REWARD_OLD, _REWARD_NEW, _reward_present, PATCHES
from .okww_patches.shot import _SHOT_OLD, _SHOT_NEW, _shot_present, _SHOT
from .okww_patches.shot2 import _SHOT2_OLD, _SHOT2_NEW, _shot2_present, _SHOT2
from .okww_patches.stamina import _STAMINA_OLD, _STAMINA_NEW, _STAMINA_V1, _stamina_present, _STAMINA
from .okww_patches.starve import _STARVE_OLD, _STARVE_NEW, _starve_present, _apply_starve
from .okww_patches.teamshot import _TEAMSHOT_OLD, _TEAMSHOT_NEW, _teamshot_present, _TEAMSHOT

log = logging.getLogger("ark.okww_patch")

# The tests and other callers import the old names from here, so every name in
# the submodules is re-exported verbatim.
__all__ = [
    'ensure_patches', 'ensure_if_updated', 'nest_patch_present', 'active_patches',
    '_BOSSTIP', '_BOSSTIP_OLD', '_BOSSTIP_NEW', '_bosstip_present',
    '_EARLYOPEN', '_EARLY_OLD', '_EARLY_NEW',
    '_REVIVE', '_REVIVE_OLD', '_REVIVE_NEW', '_REVIVE_V1',
    '_REVIVEIMP', '_REVIVEIMP_OLD', '_REVIVEIMP_NEW',
    '_REVIVELOOP', '_REVIVELOOP_OLD', '_REVIVELOOP_NEW',
    '_CLAIM_OLD',
    '_CLAIM_NEW',
    '_CLAIM_V1',
    '_CLAIM_V2',
    '_CLAIM_V3',
    '_CLAIM_V4',
    '_CLAIM_V5',
    '_CLAIM_V6',
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


def _ensure_stamina(root: Path) -> list[str]:
    """Move _STAMINA to its current version, with _NOFARM riding inside it.

    _NOFARM's anchor sits inside _STAMINA's body, so on a machine where both are
    applied the file holds v1 *with NOFARM's rewrite in it* - and the plain v1
    text no longer matches. On 2026-09-09 that made the v1 revert a no-op, so v2
    found neither the upstream text nor its own marker and reported 「贴不上了」
    (caught by the deploy gate, which is what that gate is for). So the revert has
    to recognise both shapes of v1 before v2 goes on, and NOFARM goes back on top
    afterwards, the same as before.
    """
    done: list[str] = []
    path = (*_SRC, "DailyTask.py")
    v1_with_nofarm = _STAMINA_V1.replace(_NOFARM_OLD, _NOFARM_NEW)
    if v1_with_nofarm != _STAMINA_V1:
        done.extend(_revert_text(root, path, v1_with_nofarm, _STAMINA_OLD,
                                 "附加任务先于体力刷取 v1（含不刷体力开关）"))
    done.extend(_revert_text(root, path, _STAMINA_V1, _STAMINA_OLD, "附加任务先于体力刷取 v1"))
    done.extend(_apply_one(root, _STAMINA))
    done.extend(_apply_one(root, _NOFARM))
    return done


# ---------------------------------------------------------------- the inventory
# Everything ensure_patches does is listed here, in two tables, so "what is
# running on the machine right now" is a lookup and not a read of a 100-line
# function that mixed 9 applications with 18 reverts (survey 2026-09-08, #46).
#
# _REVERTS: historical versions and withdrawn patches, restored to upstream text
# before anything is applied. They have to come first or versions stack (see
# core._Patch.unique). Each entry: (path parts, text as it was applied, upstream
# text, label). An entry stays here for as long as an update could re-expose the
# old text - which, after OK-WW's 09-06 src replacement, means for as long as
# the .bak files it left beside them could be restored by hand.
_FE = (*_SRC, "FarmEchoTask.py")
_BW = (*_SRC, "BaseWWTask.py")
_TT = (*_SRC, "TacetTask.py")
_DT = (*_SRC, "DailyTask.py")

# Both stamina changes live inside DailyTask.run, and one sits inside the other's
# region, so reverting them one at a time made the second look stacked. The whole
# method is put back in one move instead: unambiguous, and it cannot half-happen.
_DAILY_RUN_PRISTINE = (Path(__file__).with_name("okww_files")
                       / "DailyTask.run.upstream.txt").read_text(encoding="utf-8")
_DAILY_RUN_PATCHED = (_DAILY_RUN_PRISTINE
                      .replace(_STAMINA_OLD, _STAMINA_NEW, 1)
                      .replace(_NOFARM_OLD, _NOFARM_NEW, 1))
_REVERTS: "list[tuple[tuple, str, str, str]]" = [
    # Withdrawn 2026-08-31: OK-WW's own error() already prints the stack.
    (_FE, _FARMERR_NEW, _FARMERR_OLD, "周本活锁：打出被吞掉的异常"),
    # Evidence screenshots whose questions have been answered.
    (_FE, _SHOT2_NEW, _SHOT2_OLD, "退秘境前留证据截图"),
    (_FE, _TEAMSHOT_NEW, _TEAMSHOT_OLD, "开启挑战找不到时留证据截图"),
    (_FE, _SHOT_NEW, _SHOT_OLD, "周本领奖前留证据截图"),
    # Earlier versions of patches that are still applied (current version below).
    (_FE, _CLAIM_V1, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v1"),
    (_FE, _CLAIM_V2, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v2"),
    (_FE, _CLAIM_V3, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v3"),
    (_FE, _CLAIM_V4, _CLAIM_OLD, "打完 Boss 真正领周本奖励 v4"),
    (_FE, _CLAIM_V5, _CLAIM_OLD_FULL, "打完 Boss 真正领周本奖励 v5"),
    (_FE, _CLAIM_V6, _CLAIM_OLD_FULL, "打完 Boss 真正领周本奖励 v6"),
    (_BW, _BOSSTIP_V1, _BOSSTIP_OLD, "限时提前开放的 boss v1"),
    (_BW, _BOSSTIP_V2, _BOSSTIP_OLD, "限时提前开放的 boss v2"),
    (_BW, _BOSSTIP_V3, _BOSSTIP_OLD_FULL, "限时提前开放的 boss v3"),
    (_FE, _REVIVE_V1, _REVIVE_OLD, "刷声骸时原地复活 v1"),
    (_FE, _REVIVE_NEW, _REVIVE_OLD, "刷声骸时原地复活 v2（已搬到 ok_tasks，源文件还原）"),
    (_DT, _DAILY_RUN_PATCHED, _DAILY_RUN_PRISTINE,
     "日常里的体力两条（已搬到 ok_tasks，整段还原）"),
    (_FE, _CLAIM_NEW, _CLAIM_OLD_FULL, "打完 Boss 真正领周本奖励（已搬到 ok_tasks，源文件还原）"),
    (_TT, _TACETSHOT_NEW, _TACETSHOT_OLD, "无音区结算页留一张给日报（已搬到 ok_tasks，源文件还原）"),
    (_FE, _NOWAVE_NEW, _NOWAVE_OLD, "波片不足时跳过周本（已搬到 ok_tasks，源文件还原）"),
    (_FE, _RETRYCAP_NEW, _RETRYCAP_OLD, "兜底重试上限（已搬到 ok_tasks，源文件还原）"),
    (_FE, _COUNT_NEW, _COUNT_OLD, "进本前拍一张看剩余次数（已搬到 ok_tasks，源文件还原）"),
    (_FE, _REVIVEIMP_NEW, _REVIVEIMP_OLD, "刷声骸复活：把复活异常引进来（已搬到 ok_tasks，源文件还原）"),
    (_FE, _REVIVELOOP_NEW, _REVIVELOOP_OLD, "刷声骸复活后继续下一趟（已搬到 ok_tasks，源文件还原）"),
    (_FE, _EARLY_NEW, _EARLY_OLD, "限时提前开放的 boss：进场后跳过队伍和传送界面（已搬到 ok_tasks，源文件还原）"),
    (_BW, _BOSSTIP_NEW, _BOSSTIP_OLD_FULL, "限时提前开放的 boss：认出剧情提示框（已搬到 ok_tasks，源文件还原）"),
    (_FE, _LETPASS_NEW, _LETPASS_OLD, "放行主动跳过的信号（已搬到 ok_tasks，源文件还原）"),
    ((*_SRC, "TacetTask.py"), _TACETSHOT_V1, _TACETSHOT_V1_OLD, "无音区留两张图给日报 v1"),
    (_FE, _COUNT_V1, _COUNT_OLD, "进本前拍一张看剩余次数 v1"),
    (_FE, _COUNT_V2, _COUNT_OLD, "进本前拍一张看剩余次数 v2"),
    (_FE, _NOWAVE_V1 + "\n", "", "波片不足时跳过周本 v1"),
    (_FE, _NOWAVE_V2, _NOWAVE_OLD, "波片不足时跳过周本 v2"),
    (_FE, _NOWAVE_V3A, _NOWAVE_OLD, "波片不足时跳过周本 v3a"),
    (_FE, _NOWAVE_V3B, _NOWAVE_OLD, "波片不足时跳过周本 v3b"),
    # Withdrawn outright.
    *[(p.parts, p.new, p.old, p.name) for p in PATCHES],
    ((*_SRC, "DomainTask.py"), _DOMAIN_NEW, _DOMAIN_OLD, "副本失败不拖垮每日任务"),
    ((*_SRC, "DomainTask.py"), _DOMAIN_IMPORT_NEW, _DOMAIN_IMPORT_OLD, "副本补丁的 import"),
    ((*_SRC, "BaseCombatTask.py"), _STARVE_NEW, _STARVE_OLD, "主C饿死兜底"),
]

# _APPLIES: what is in effect on the machine, in application order. The nest
# file replacement and the stamina/nofarm pair are steps of their own (the
# nest is a whole-file swap; nofarm's anchor lives inside stamina's body).
_APPLIES: "list[_Patch]" = []


def active_patches() -> list[str]:
    """Names of everything applied every boot, in order - the source of truth for
    docs/OKWW-PATCHES.md and for anyone asking what runs."""
    return ["巢穴任务（整份文件替换）"] + [p.name for p in _APPLIES]


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
    done.extend(_ensure_stamina(root))
    for parts, new, old, label in _REVERTS:
        done.extend(_revert_text(root, parts, new, old, label))
    for patch in _APPLIES:
        done.extend(_apply_one(root, patch))
    return done
