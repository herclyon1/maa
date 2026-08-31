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

import hashlib
import logging
import os
import py_compile
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("ark.okww_patch")

_SRC = ("data", "apps", "ok-ww", "working", "src", "task")


@dataclass(frozen=True)
class _Patch:
    name: str               # 人话名字，进通知
    parts: tuple            # 相对 okww_dir 的路径
    old: str                # 上游原样那段
    new: str                # 我们要的那段
    present: Callable[[str], bool]      # 已经在位了吗
    breaks: str             # 贴不上会怎样，写给人看
    upstream: str = ""      # 提给上游之后填 PR 链接；合并了就删掉这条补丁


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


# ── 补丁二：副本没打通不该把整个每日任务带走 ──────────────────
# 2026-08-26 实测：凝素领域限时没打完 → 不掉宝箱 → walk_to_treasure 抛
# WaitFailedException → 它不在 except 里 → 一路穿到 DailyTask.run。
# 当天连续四次「Daily Task exception stopped」，领奖 / 邮件 / 附加任务全跳过，
# total daily points 0。而紧邻的 farm_domain_with_recovery_loop 里作者写了
# max_recovery_retries=3 的恢复重试，只能通过 return False 进入，
# 于是对这个失败模式完全是死代码。
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


PATCHES: tuple[_Patch, ...] = (
    _Patch(
        name="领奖顺序",
        parts=(*_SRC, "DailyTask.py"),
        old=_REWARD_OLD, new=_REWARD_NEW, present=_reward_present,
        breaks="周常乐园的奖励会领不到",
    ),
    # 这条是两段替换，用 old/new 表达不了，走 _apply_domain 特判。
)


def _atomic_write(f: Path, text: str) -> Path | None:
    """备份 → 原子替换。返回备份路径，写不进去返回 None。"""
    bak = f.with_name(f"{f.stem}.py.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(f, bak)
        tmp = f.with_suffix(".py.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, f)      # 原子替换，别让半截文件被 OK-WW 读到
    except OSError:
        log.warning("OK-WW 补丁：写不进去 %s", f.name, exc_info=True)
        return None
    return bak


def _atomic_write_bytes(f: Path, data: bytes) -> Path | None:
    """原样写字节。整份替换不能经过 write_text——它会按平台改写行尾。"""
    bak = f.with_name(f"{f.stem}.py.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(f, bak)
        tmp = f.with_suffix(".py.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, f)
    except OSError:
        log.warning("OK-WW 补丁：写不进去 %s", f.name, exc_info=True)
        return None
    return bak


def _verify_or_revert(f: Path, bak: Path, present: Callable[[str], bool],
                      label: str) -> str:
    """回读 + 编译。写进去不等于对，语法坏了整个日常任务都起不来。"""
    back = f.read_text(encoding="utf-8", errors="replace")
    if not present(back):
        shutil.copy2(bak, f)
        log.error("OK-WW 补丁：%s 回读不对，已还原", label)
        return f"OK-WW 补丁：{label} 回读不对，已还原成上游版"
    try:
        py_compile.compile(str(f), doraise=True)
    except (py_compile.PyCompileError, OSError):
        shutil.copy2(bak, f)
        log.error("OK-WW 补丁：%s 语法检查没过，已还原", label, exc_info=True)
        return f"OK-WW 补丁：{label} 改完语法不对，已还原成上游版"
    return ""


def _apply_one(root: Path, p: _Patch) -> list[str]:
    # 注意 present() 的判据必须跟着 new 一起改。
    # 2026-08-31 踩过：我给「波片不足时跳过周本」加了调试行，present() 认的
    # 还是那句没变过的日志，_apply_one 判成「已在位」直接返回，新版本
    # **一声不吭地没部署**，我却在日志里找那行调试输出，白等一趟。
    # 判据要认 new 里**这一版独有**的东西，改了内容就要跟着改判据。
    f = root.joinpath(*p.parts)
    if not f.exists():
        log.warning("OK-WW 补丁：找不到 %s，跳过", f)
        return [f"OK-WW 补丁：找不到 {f.name}，{p.name} 没能检查"]
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        log.warning("OK-WW 补丁：读不了 %s", f, exc_info=True)
        return [f"OK-WW 补丁：读不了 {f.name}"]

    if p.present(text):
        return []                      # 幂等：在位就不留痕迹也不报噪音
    if p.old not in text:
        # 上游改了结构。硬替换只会把文件改坏，所以停手并出声。
        log.warning("OK-WW 补丁：认不出上游 %s 那段，结构可能变了，不动它", p.name)
        return [f"OK-WW 补丁：{p.name}**贴不上了**（上游结构变了），"
                f"{p.breaks}，需要人工看一眼"]

    bak = _atomic_write(f, text.replace(p.old, p.new, 1))
    if bak is None:
        return [f"OK-WW 补丁：{p.name} 写不进去，{p.breaks}"]
    if err := _verify_or_revert(f, bak, p.present, p.name):
        return [err]
    log.info("OK-WW 补丁：%s 已重新贴上", p.name)
    return [f"OK-WW 补丁：{p.name} 已重新贴上（上次更新把它覆盖了）"]


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


# ── 补丁三：巢穴任务（整文件替换）──────────────────────────────
# 这条补丁改了三处、还加了一个方法和一个配置项，用文本替换拼太脆。
# 改成**整文件替换 + 哈希守卫**：只有当机器上那份和我们记录的上游版
# 一字不差时才替换；上游一改动哈希就对不上，我们停手并出声，
# 绝不拿旧补丁去盖新代码。
#
# 三处改动：
#   1. 允许续刷未打满的点位（原来只认「已击败 0/N」，刷过一只就永久放弃）
#      —— 上游 PR ok-oldking/ok-wuthering-waves#1629
#   2. 同一点位打完没进展就跳过，别无限重进（队伍打不过时游戏弹「挑战失败」）
#   3. 新增「只刷指定点位」配置（对应 issue #1622，上游还没有这个能力）
_NEST_DIR = Path(__file__).with_name("okww_files")
_NEST_UPSTREAM = _NEST_DIR / "NightmareNestTask.upstream.py"
_NEST_PATCHED = _NEST_DIR / "NightmareNestTask.patched.py"


def _sha(data: bytes) -> str:
    """按**内容**算哈希，不算行尾符。

    Windows 上 `write_text` 会把 \n 换成 \r\n，于是同一份内容在两台机器上
    字节不同、哈希不同。2026-08-26 就因此把「已经贴好的补丁」误判成
    「和上游对不上」。统一成 \n 再算，比的就是内容本身。
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# 我们自己发布过的历次 NightmareNestTask 版本的哈希。
# 为什么需要：护栏原本只认「上游那份」和「当前这份」，一旦我们自己改了补丁，
# 机器上那份就两边都不是，于是被判成「有人手改过」而拒绝覆盖——
# 结果是自己的修复永远推不上去。历史版本记在这里，见到就照常覆盖。
# 我方标记：上游源码里绝不会出现的、我们自己造的配置常量。
# 见到它 = 现场那份出自我们之手，可以放心覆盖成最新版。
_NEST_MARKER = b"Only Farm These Nests"

_NEST_KNOWN_OURS = {
    "6b27d6f03f7210f80cb5da823a55c5732f26935f16ab775196aee80376b2ff7e",   # 2026-08-27 12:05：hit_wanted 版（与最终版只差 docstring，漏记了哈希）
    "788a8b633498b44f33dbd56d96b971cc95265e88719f6dc0a9f47fe2b4897916",   # 2026-08-27 11:35：临时的几何日志版
    "fc7207ff2047999241cd1ce44996b54b13f2a9d1d0169e344615490bf57e85d5",   # 2026-08-27 11:26：包含匹配，但行匹配容差只有一倍行高
    "48ec36c8c117854dfdd86d160a89bc76ce6e26a9b1c445c7605935b69f044726",   # 2026-08-27 上午：指定点位用了精确匹配，对不上「落渊南丘残象聚落」
    "72cf1da2e840918fe62656acfb5b9434e84b1f320829ccf256d7f9aa9c9fcc34",   # 2026-08-27 之前：指定点位只 OCR 一次，不等列表渲染
}


def _apply_nest(root: Path) -> list[str]:
    f = root.joinpath(*_SRC, "NightmareNestTask.py")
    label = "巢穴任务（续刷 / 不空转 / 可指定点位）"
    if not f.exists():
        return [f"OK-WW 补丁：找不到 NightmareNestTask.py，{label} 没能检查"]
    if not (_NEST_UPSTREAM.exists() and _NEST_PATCHED.exists()):
        log.warning("OK-WW 补丁：缺少 okww_files 里的参照文件")
        return [f"OK-WW 补丁：{label} 缺少参照文件，没能检查"]

    try:
        cur = f.read_bytes()
    except OSError:
        return ["OK-WW 补丁：读不了 NightmareNestTask.py"]

    patched = _NEST_PATCHED.read_bytes()
    if _sha(cur) == _sha(patched):
        return []                       # 幂等：已经是我们这份
    # 上游永远不会包含我们自己造的这个配置常量，所以见到它就说明现场那份
    # 是我们贴过的某个版本，照常覆盖。
    # 为什么不只靠 _NEST_KNOWN_OURS：那张表要求**每次改补丁都手动补一条哈希**，
    # 2026-08-29 我改了补丁却忘了补，于是修复推不上去，部署还照常报成功
    # （只在日志里留了一行 warning）。靠人记的步骤迟早会漏，标记不会。
    ours_by_marker = _NEST_MARKER in cur
    if not ours_by_marker and _sha(cur) not in _NEST_KNOWN_OURS and \
            _sha(cur) != _sha(_NEST_UPSTREAM.read_bytes()):
        # 既不是上游那份、也不是我们那份——上游改过了，或者有人手改过。
        # 这时候硬盖会把别人的改动抹掉，所以停手。
        log.warning("OK-WW 补丁：NightmareNestTask.py 和记录的上游版对不上，不动它")
        return [f"OK-WW 补丁：{label}**贴不上了**——文件和记录的上游版不一致，"
                "多半是上游更新了，需要人工重做这份补丁"]

    bak = _atomic_write_bytes(f, patched)
    if bak is None:
        return [f"OK-WW 补丁：{label} 写不进去"]
    if err := _verify_or_revert(f, bak, lambda s: _sha(s.encode("utf-8")) == _sha(patched), label):
        return [err]
    log.info("OK-WW 补丁：%s 已重新贴上", label)
    return [f"OK-WW 补丁：{label} 已重新贴上（上次更新把它覆盖了）"]

# ── 补丁四：主C饿死兜底 ────────────────────────────────────────
# 协奏攒不满时 has_buff() 恒为 False，_unbuffed_non_main_target 会让两个辅助
# 无限互切，主C永远上不了场——而主C正是唯一有机会把协奏打起来的人。
# 2026-08-26 实测：56 次切人决策里主C 0 次，全程零输出被磨死。
# 根因是游戏键位被改过（见 issue #1626），已经修好；这条留作保险，
# 平时处于休眠状态（实测健康局面下切人序列与上游完全一致）。
# 2026-08-27：它当初是手工打的、没进这个清单，OK-WW 一更新就被冲掉了。
_STARVE_OLD = """    def _choose_switch_target_by_buff_time(self, current_char, candidates):
        if not candidates:
            return current_char
"""

_STARVE_NEW = """    # 本地补丁：主C饿死兜底。协奏攒不满时 has_buff() 恒为 False，
    # _unbuffed_non_main_target 会让两个辅助无限互切，主C永远上不了场——
    # 而主C正是唯一有机会把协奏打起来的人，于是死锁自我维持。
    # 上游 issue: ok-oldking/ok-wuthering-waves#1626
    MAIN_DPS_STARVE_SECONDS = 25.0

    def _starved_main_dps_target(self, candidates):
        now = time.time()
        starved = [char for char in candidates
                   if char.is_main_dps
                   and (char.last_switch_in_time < 0
                        or now - char.last_switch_in_time > self.MAIN_DPS_STARVE_SECONDS)]
        return self._oldest_switch_target(starved)

    def _choose_switch_target_by_buff_time(self, current_char, candidates):
        if not candidates:
            return current_char

        if not current_char.is_main_dps:
            if starved := self._starved_main_dps_target(candidates):
                return starved
"""


def _starve_present(text: str) -> bool:
    return "_starved_main_dps_target" in text


def _apply_starve(root: Path) -> list[str]:
    f = root.joinpath(*_SRC, "BaseCombatTask.py")
    label = "主C饿死兜底"
    if not f.exists():
        return [f"OK-WW 补丁：找不到 BaseCombatTask.py，{label} 没能检查"]
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return ["OK-WW 补丁：读不了 BaseCombatTask.py"]
    if _starve_present(text):
        return []
    if _STARVE_OLD not in text:
        log.warning("OK-WW 补丁：认不出上游 _choose_switch_target_by_buff_time，不动它")
        return [f"OK-WW 补丁：{label}**贴不上了**（上游结构变了），需要人工看一眼"]
    bak = _atomic_write(f, text.replace(_STARVE_OLD, _STARVE_NEW, 1))
    if bak is None:
        return [f"OK-WW 补丁：{label} 写不进去"]
    if err := _verify_or_revert(f, bak, _starve_present, label):
        return [err]
    log.info("OK-WW 补丁：%s 已重新贴上", label)
    return [f"OK-WW 补丁：{label} 已重新贴上（上次更新把它覆盖了）"]

def _revert_text(root: Path, parts: tuple, new: str, old: str,
                 label: str) -> list[str]:
    """把一段本地改动还原回上游原样。找不到就当已经还原了，不出声。

    **只停止重打是不够的**：`ensure_patches` 只会打不会撤，
    从清单里删掉一条补丁，已经贴在机器上的那份还在，
    要等 OK-WW 下次更新覆盖文件才会消失。所以要主动撤。
    """
    f = root.joinpath(*parts)
    if not f.exists():
        return []
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return [f"OK-WW 补丁：读不了 {f.name}，{label} 没能撤销"]
    if new not in text:
        return []                       # 幂等：已经是上游原样
    bak = _atomic_write(f, text.replace(new, old, 1))
    if bak is None:
        return [f"OK-WW 补丁：{label} 撤销失败，写不进去"]
    log.info("OK-WW 补丁：%s 已撤销，还原成上游原样", label)
    return [f"OK-WW 补丁：{label} 已撤销（证据不足，见 2026-08-30 的结论）"]


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


# ── 补丁：周本领奖那一刻先截一张图 ────────────────────────────
# 2026-08-31：周本打满三轮，体力一点没动，说明奖励没领到。
# 那行代码是 `wait_click_feature('claim_cancel_button…', relative_x=2)`——
# `relative_x` 是「框内相对 X」，2 就是从取消按钮左边缘往右两个按钮宽度，
# **本意就是去点右边的领取按钮**（用户说领取在弹窗右下角）。日志里点在
# (538, 675)，偏够没偏够，不看那一刻的画面就说不清。
#
# 这个补丁**不改任何行为**，只是在点击之前存一张图。下次周本一跑就有证据，
# 不用再靠猜按钮坐标——猜坐标去改生产脚本正是 826 那类错。
_SHOT_OLD = """                        self.send_key('esc', after_sleep=0.5)
                        self.wait_click_feature('claim_cancel_button_hcenter_vcenter', relative_x=2,
                                                raise_if_not_found=True,
                                                post_action=lambda: self.send_key('esc', after_sleep=1),
                                                settle_time=1)"""

_SHOT_NEW = """                        self.send_key('esc', after_sleep=0.5)
                        # 本地补丁：先留一张证据，再点。行为不变。
                        try:
                            self.screenshot('weekly_claim_dialog')
                        except Exception:
                            pass
                        self.wait_click_feature('claim_cancel_button_hcenter_vcenter', relative_x=2,
                                                raise_if_not_found=True,
                                                post_action=lambda: self.send_key('esc', after_sleep=1),
                                                settle_time=1)"""


def _shot_present(text: str) -> bool:
    return "weekly_claim_dialog" in text


_SHOT = _Patch(
    name="周本领奖前留证据截图",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_SHOT_OLD,
    new=_SHOT_NEW,
    present=_shot_present,
    breaks="下次周本还是拿不到那一刻的画面，只能继续猜按钮位置",
)


# ---- 周本活锁：把被吞掉的异常打出来 ----------------------------------------
#
# 2026-08-31 实测：12:35:53→12:47:44 之间「传送 → found a claim reward → 传送」
# 转了 21 圈、35 秒一圈，白烧 12 分钟才真打上 Boss。上游那段是：
#
#     except Exception as e:
#         logger.error('farm 4c error, try handle monthly card', e)
#         if self.handle_claim_button() or self.handle_monthly_card():
#             self.run()
#
# logging 把第二个位置参数当成 msg 的 printf 参数，而 msg 里没有 %s，
# 于是**异常内容整个丢掉**——日志里只剩一句没有信息量的 'farm 4c error'，
# 真因查不到。这条补丁只把它改成 exc_info=True，**不动任何控制流**：
# 递归、重试次数、判定全部原样。下一次周本一跑，真因就会自己写在日志里。
#
# 递归没有上限这件事是上游的设计问题，已提 issue，本地不擅自改控制流——
# 改了就等于在没有证据的情况下动生产脚本。
_FARMERR_OLD = """            logger.error('farm 4c error, try handle monthly card', e)"""

_FARMERR_NEW = """            # 本地补丁：上游把异常当成 printf 参数传进去了，内容会被丢掉。
            logger.error(f'farm 4c error, try handle monthly card: {e!r}',
                         exc_info=True)"""


def _farmerr_present(text: str) -> bool:
    return "farm 4c error, try handle monthly card: {e!r}" in text


_FARMERR = _Patch(
    name="周本活锁：打出被吞掉的异常",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_FARMERR_OLD,
    new=_FARMERR_NEW,
    present=_farmerr_present,
    breaks="周本活锁的真因继续查不到，日志里只有一句没信息量的 farm 4c error",
)


# ---- 周本退秘境前先留证据 -------------------------------------------------
#
# 2026-08-31 定位到：打完 Boss、捡完声骸之后，`do_run` 走的是
#     if self._in_realm and not self.in_world():
#         self.send_key('esc', ...)                 ← 直接退秘境
# 宝箱那一步整个不存在。上一版截图拍在 esc **之后**，只拍到「确认离开」
# 弹窗，白拍一次。这次挪到 esc **之前**，拍的是 Boss 刚死那一刻的画面，
# 用来确认宝箱到底以什么形式出现（F 提示？图标？还是要走过去？）。
#
# 零行为改动：只加一次截图，try 包住，失败也不影响流程。
_SHOT2_OLD = """                    if self._in_realm and not self.in_world():
                        self.send_key('esc', after_sleep=0.5)"""

_SHOT2_NEW = """                    if self._in_realm and not self.in_world():
                        # 本地补丁：退秘境之前先留一张图，看宝箱长什么样。
                        try:
                            self.screenshot('boss_dead_before_exit')
                        except Exception:
                            pass
                        self.send_key('esc', after_sleep=0.5)"""


def _shot2_present(text: str) -> bool:
    return "boss_dead_before_exit" in text


_SHOT2 = _Patch(
    name="退秘境前留证据截图",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_SHOT2_OLD,
    new=_SHOT2_NEW,
    present=_shot2_present,
    breaks="拿不到 Boss 刚死那一刻的画面，宝箱怎么领只能靠猜",
)


# ---- 找不到「开启挑战」时留证据 -------------------------------------------
#
# 2026-08-31 真因（堆栈从 12:35 起就在日志里，是我没去读）：
#     teleport_to_configured_boss_and_prepare
#       → teleport_to_configured_boss
#         → click_team_challenge()
#           → wait_click_feature('team_start_challenge', raise_if_not_found=True)
#             → WaitFailedException
# 传送到周本之后找不到「开启挑战」按钮，于是抛异常 → 重试 → 再传送，
# 12:35→12:47 空转 21 圈。上游 #1551 讲的是同一个模板匹配失败。
#
# 周本这条路在点按钮之前还有一次写死坐标的点击 self.click(0.880, 0.911)，
# 那一下歪了后面就全错。到底是模板没匹配上还是页面根本没打开，
# **不看那一刻的画面说不清**，所以先留图再抛，`raise` 保证行为不变。
_TEAMSHOT_OLD = """            self.click_team_challenge()"""

_TEAMSHOT_NEW = """            # 本地补丁：找不到「开启挑战」时先留一张图再抛，行为不变。
            try:
                self.click_team_challenge()
            except Exception:
                try:
                    self.screenshot('no_start_challenge')
                except Exception:
                    pass
                raise"""


def _teamshot_present(text: str) -> bool:
    return "no_start_challenge" in text


_TEAMSHOT = _Patch(
    name="开启挑战找不到时留证据截图",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_TEAMSHOT_OLD,
    new=_TEAMSHOT_NEW,
    present=_teamshot_present,
    breaks="周本空转的那一刻画面拿不到，只能继续猜是模板问题还是坐标问题",
)


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

_NOWAVE_NEW = """            # 本地补丁：波片不足时游戏会弹「无法获取奖励，是否继续进入」，
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


def _nowave_present(text: str) -> bool:
    # 认 **这一版独有** 的字串。只认那句没变过的日志会让改动静默不部署——
    # 2026-08-31 已经栽过一次：v2 加了调试输出，判据没跟着改，
    # _apply_one 判成「已在位」直接返回，我却在日志里找那行输出。
    return "v2 开启挑战前读到" in text


_NOWAVE = _Patch(
    name="波片不足时跳过周本",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_NOWAVE_OLD,
    new=_NOWAVE_NEW,
    present=_nowave_present,
    breaks="波片不够时周本会空转十几分钟，而且是不拿奖励地白打",
)


# ---- 进本之前拍一张 Boss 页面，看本周还剩几次 ----------------------------
#
# 2026-08-31 用户问：「你确定刷的两次周本奖励是 90 级的副本？」——问得对，
# 等级 90 是 16:20 才写进母本、16:41 才同步过去，之前几趟点的都是
# 「推荐等级80」。而「已用 2 次」这个数是我从体力消耗**推算**的，
# 不是读到的。推算已经错过好几回了，这次去读真的。
#
# 安全性：波片不足时进不去（会弹「结晶波片不足」，我们的补丁取消并跳过），
# **不消耗次数**。所以这张图可以在波片不够的时候放心拍。
_COUNT_OLD = """                self.click_configured_boss_level()"""

_COUNT_NEW = """                # 本地补丁：选等级之前拍一张，页面上有本周剩余次数。
                try:
                    self.screenshot('weekly_remaining')
                except Exception:
                    pass
                self.click_configured_boss_level()"""


def _count_present(text: str) -> bool:
    return "weekly_remaining" in text


_COUNT = _Patch(
    name="进本前拍一张看剩余次数",
    parts=(*_SRC, "FarmEchoTask.py"),
    old=_COUNT_OLD,
    new=_COUNT_NEW,
    present=_count_present,
    breaks="本周还剩几次只能靠体力推算，而推算已经错过好几回",
)


def ensure_patches(okww_dir: Path | None) -> list[str]:
    """确保本地补丁在位。返回这次实际做了什么（空表示本来就在位）。

    2026-08-30 从四个减到一个。留下的只有残象聚落那份整份替换，
    因为「只刷指定点位」上游根本没有，只能靠换掉整个文件拿到。

    撤掉的三个，理由都是**没有证据说它们现在还在起作用**：

    * 主C饿死兜底 —— 是我们自己改过游戏键位造成的（已在上游 #1632
      承认并自行关闭 PR）。键位改回默认后症状再没出现。
    * 副本失败不拖垮每日任务 —— 对应 08-26 那次「走向宝箱捡不到东西 →
      等待超时 → 整个日常崩掉」，多半是背包满。而这条补丁是 08-28 才加的，
      **症状 08-27 就已经不再出现**，加它之前病就好了。
    * 领奖置底 —— 上游作者 2026-08-29 关闭了 PR #1631，没有留任何说明。
      而且这个顺序是作者有意为之，`config_description` 里明写着。
      改成 issue 去问「能不能做成可配置」，本地不再改。

    三个都主动还原，不是只停止重打。
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
    # 2026-08-31 撤回：前提就是错的。ok.util.logger.Logger.error 的签名是
    # error(self, message, exception=None)，第二个参数**本来就是异常**，
    # 它内部走 exception_to_str(exception) 打印堆栈。上游写法没问题。
    # 而我加的 exc_info=True 这个封装根本不认，当场 TypeError，
    # 把一次可恢复的重试变成了硬崩溃（16:00 那趟就是这么死的）。
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _FARMERR_NEW, _FARMERR_OLD, "周本活锁：打出被吞掉的异常"))
    done.extend(_apply_one(root, _SHOT2))
    # 取证补丁已经问到答案（画面是「结晶波片不足」弹窗），撤回。
    done.extend(_revert_text(root, (*_SRC, "FarmEchoTask.py"),
                             _TEAMSHOT_NEW, _TEAMSHOT_OLD,
                             "开启挑战找不到时留证据截图"))
    done.extend(_apply_one(root, _NOWAVE))
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
