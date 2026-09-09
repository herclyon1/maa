"""Ark's changes to OK-WW, installed without editing a single upstream file.

ok-script has a documented extension point: with `custom_tasks: True` (which
ok-wuthering-waves sets in its own config.py) the task manager creates an
`ok_tasks/` folder in the working directory and **executes every .py in it** at
startup, before any task runs. It only executes a file that defines at least one
top-level class, so `_Marker` below is load-bearing even though it does nothing.

Running there lets this file rebind methods on upstream's own classes. Python
looks a method up on the class at call time, so a rebind reaches instances that
were already constructed - including the built-in FarmEchoTask that DailyTask
finds through `get_task_by_class`. Subclassing cannot do that: that lookup
returns the first matching instance and the built-ins are registered first.

**Every rebind is checked before it happens.** A method that upstream renamed or
refactored away would otherwise be replaced under a name nobody calls, and the
behaviour would go missing without a word - the exact failure the text patches
kept producing. What was checked, applied and skipped is written to
`ark-okww-overlay.json`, which the relay reads at boot and pushes.
"""
import hashlib
import inspect
import json
import os
import pathlib
import re
import traceback

# The copied method bodies below reach these as module globals. They are filled in by
# _install_copies() rather than imported here, because nothing in OK-WW is importable
# outside OK-WW's own process, and the gate's own tests have to be able to load this
# file on any machine to feed it known-bad input.
logger = None
TaskDisabledException = Exception
CharRevivedException = Exception
WWOneTimeTask = None

REPORT = r"C:\ProgramData\ark-okww-overlay.json"
NO_CLAIM = "C:/ProgramData/ark-okww-farm.no-claim"

_applied: "list[str]" = []
_skipped: "list[dict]" = []


def _src_sha(fn) -> str:
    try:
        return hashlib.sha1(inspect.getsource(fn).encode("utf-8")).hexdigest()[:12]
    except (OSError, TypeError):
        return ""


def override(cls, name, *, expect_sha=None):
    """Rebind `cls.name`, but only when upstream still looks the way we think.

    `expect_sha` is for a method we copied wholesale: when upstream's own source
    changes, our copy is stale by definition and applying it would quietly undo
    their fix. Without it, the check is just that the attribute exists.
    """
    def wrap(fn):
        label = f"{cls.__name__}.{name}"
        old = getattr(cls, name, None)
        if old is None:
            _skipped.append({"what": label, "why": "上游没有这个方法了（改名或删了）"})
            return fn
        if expect_sha:
            got = _src_sha(old)
            if got != expect_sha:
                _skipped.append({"what": label,
                                 "why": f"上游正文变了（现在 {got or '读不到'}，我们照着 {expect_sha} 抄的）"})
                return fn
        setattr(cls, name, fn)
        _applied.append(label)
        return fn
    return wrap


def farming_echoes() -> bool:
    """True while the relay is farming 4-cost echoes."""
    return os.path.exists(NO_CLAIM)


class _Marker:
    """ok-script only executes a file that defines a class. This is that class."""


def _install():
    from src.task.FarmEchoTask import FarmEchoTask

    revive = FarmEchoTask.revive_action

    @override(FarmEchoTask, "revive_action")
    def revive_action(self):
        # Inside a realm upstream gives up on reviving - there is no teleport tower
        # to run back to - so one death stops the whole task. For an overnight farm
        # that means standing still until morning. The death dialog is on screen and
        # OK-WW already recognises it, so find the confirm button by its own text and
        # take the next lap. **By text, not by position**: the dialog is titled
        # 「选择复苏物品」, and matching 复苏 clicked the title itself on 2026-09-09.
        # Only the one case upstream refuses is ours: inside a realm it returns
        # False, because there is no teleport tower to run back to. Everything else
        # is theirs and still runs, so their improvements to it flow through.
        if not (self._in_realm and farming_echoes()):
            return revive(self)
        try:
            found = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
            text = ' '.join(str(b) for b in found)
            if '复苏物品' not in text and '复活' not in text:
                self.log_info(f'刷声骸模式：这不像死亡弹窗，不乱点。整屏读到 {found}')
                return False
            button = None
            for b in found:
                name = str(getattr(b, 'name', '') or '').strip()
                if '确认' in name and len(name) <= 6:
                    button = b
                    break
            if button is None:
                self.log_info(f'刷声骸模式：死亡弹窗上没找到「确认」，整屏读到 {found}')
                return False
            self.log_info(f'刷声骸模式：角色阵亡，用一个复苏物品点「{button}」，接着刷')
            self.click(button, after_sleep=3)
            self.wait_in_team_and_world(time_out=120)
            self.is_revived = True
            return True
        except Exception as e:  # noqa: BLE001 - a failed revive must not kill the run
            self.log_info(f'刷声骸模式：复活这一步没做成 {e!r}')
            return False


class _EarlyOpen(Exception):
    """Confirmed the 限时提前开放 dialog and landed straight in the arena."""


def _install_teleport():
    from ok import TaskDisabledException
    from src.task.BaseWWTask import BaseWWTask
    from src.task.FarmEchoTask import FarmEchoTask

    inner = BaseWWTask.click_on_book_target

    @override(BaseWWTask, "click_on_book_target")
    def click_on_book_target(self, serial_number, total_number, structure=None):
        # A limited-time-early boss pops a spoiler dialog after the challenge button
        # is clicked. Its text is matched below. Upstream does not know that dialog,
        # so the wait that follows
        # times out and the whole run dies with 「Teleport to boss failed」. The dialog
        # costs nothing - it is a spoiler warning - but it is identified by its own
        # text before anything is clicked: a bare 「there is a confirm button」 test
        # would happily confirm a waveplate prompt, the one mistake this must not make.
        try:
            return inner(self, serial_number, total_number, structure)
        except Exception:
            try:
                found = self.ocr(box=self.box_of_screen(0.25, 0.40, 0.78, 0.56)) or []
            except Exception:
                raise
            text = ' '.join(str(b) for b in found)
            if '确认前往' not in text and '剧情体验' not in text:
                self.log_info(f'传送前没认出提示框，这块屏幕读到：{text[:120]!r}')
                # Not the spoiler dialog, so the wait simply ran out. Upstream gives
                # the game 10 seconds and 19 runs across five days have died on that
                # one - 2026-09-09's pilot among them, with the team screen appearing
                # right after the timeout. Give it one more look before giving up:
                # slower than upstream is free, a dead daily is not.
                again = self.wait_feature(
                    ['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'],
                    time_out=15, settle_time=0.5, raise_if_not_found=False)
                if not again:
                    raise
                self.log_info('传送界面来晚了，多等 15 秒等到了，接着走')
                return again.name == 'team_close'
            self.log_info('限时提前开放的剧情提示框，点确认前往')
            self.click_dialog_right_button()
            # Confirming drops the player straight into the arena: no fast-travel UI
            # and no team screen, so neither of upstream's two branches fits. Leaving
            # by exception skips both of them.
            self.log_info('限时提前开放：确认后直接进场，跳过队伍和传送这两步')
            raise _EarlyOpen from None

    outer = FarmEchoTask.teleport_to_configured_boss

    @override(FarmEchoTask, "teleport_to_configured_boss")
    def teleport_to_configured_boss(self):
        try:
            return outer(self)
        except _EarlyOpen:
            # True means 「already in the realm」, which is what being dropped into
            # the arena amounts to.
            return True

    prepare = FarmEchoTask.teleport_to_configured_boss_and_prepare

    @override(FarmEchoTask, "teleport_to_configured_boss_and_prepare")
    def teleport_to_configured_boss_and_prepare(self):
        # 「Skip this on purpose」 is a signal, not a failure. Upstream wraps every
        # exception here in RuntimeError, so run()'s own `except TaskDisabledException`
        # never saw it and a deliberate skip was retried as an error.
        try:
            return prepare(self)
        except RuntimeError as exc:
            if isinstance(exc.__cause__, TaskDisabledException):
                raise exc.__cause__ from None
            raise


# ---------------------------------------------------------------------------
# Every change below hooks the smallest method that contains it, so upstream's own
# code keeps running and their edits flow through. The first shape of this file
# carried five whole-method copies (30 to 90 lines each, frozen). Upstream ships
# roughly every other day, and each copy would have gone stale the moment they
# touched that method - loudly, thanks to the hash pin, but the change would still
# have stopped happening. Hooking one call deeper removes that exposure entirely.
#
# Two things still replace a method outright, because upstream's own body is what
# has to go: revive_action (its realm branch is a bare `return False`) and
# click_team_challenge (the whole point is to split it in two). Both are pinned.
# ---------------------------------------------------------------------------

# Upstream's click_team_challenge is three lines and this replaces all of them,
# so it is pinned like any other replacement.
_TEAM_CHALLENGE_SHA = "daeaf5a0f809"
NO_STAMINA_FLAG = r"C:\ProgramData\ark-relay\state\no-stamina-farm.flag"
_MAX_FARM_RETRIES = 3


def _install_hooks():
    global logger, TaskDisabledException, CharRevivedException
    from ok import Logger
    from ok import TaskDisabledException as _TDE
    from src.task.BaseCombatTask import CharRevivedException as _CRE
    from src.task.DailyTask import DailyTask
    from src.task.FarmEchoTask import FarmEchoTask
    from src.task.ForgeryTask import ForgeryTask
    from src.task.SimulationTask import SimulationTask
    from src.task.TacetTask import TacetTask

    logger = Logger.get_logger("ark_overrides")
    TaskDisabledException, CharRevivedException = _TDE, _CRE

    # -- 4C farm: stop retrying for ever ------------------------------------
    farm_run = FarmEchoTask.run

    @override(FarmEchoTask, "run")
    def run(self):
        # Upstream retries by calling run() again from its own except, with no
        # limit: one bad night span 50 minutes of that. Counting the depth here
        # caps it without touching their body.
        self._ark_depth = getattr(self, "_ark_depth", 0) + 1
        try:
            if self._ark_depth > _MAX_FARM_RETRIES:
                self.log_info(f"连续 {_MAX_FARM_RETRIES} 次失败，退出本次任务，不再重试")
                raise TaskDisabledException()
            return farm_run(self)
        finally:
            self._ark_depth -= 1

    # -- 4C farm: a revived death is not the end of the run ------------------
    farm_combat = FarmEchoTask.combat_once

    @override(FarmEchoTask, "combat_once")
    def combat_once(self, *a, **kw):
        # Reviving raises CharRevivedException, which upstream's loop does not
        # catch, so a successful revive still stopped the task. Swallowing it
        # here lets the loop reach its own `if self.is_revived: continue`.
        try:
            return farm_combat(self, *a, **kw)
        except CharRevivedException:
            self.log_info("刷声骸模式：复活成功，接着刷下一趟")
            return None

    # -- weekly boss: read the remaining count before entering --------------
    pick_level = FarmEchoTask.click_configured_boss_level

    @override(FarmEchoTask, "click_configured_boss_level")
    def click_configured_boss_level(self):
        try:
            self.screenshot("weekly_remaining")
        except Exception:
            pass
        left = None
        try:
            left = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
            self.log_info(f"周本本周剩余次数原文: {left}")
        except Exception:
            pass
        text = " ".join(str(b) for b in (left or []))
        if re.search(r"次数[^0-9]{0,6}0\s*[/／]\s*3", text):
            # Read 0/3 and entered anyway once: five minutes of 「收取物资次数已达到
            # 上限」 and the daily pushed back for nothing.
            self.log_info("本周周本次数已领满（0/3），不进本，跳过")
            try:
                self.ensure_main(time_out=30)
            except Exception:
                pass
            raise TaskDisabledException()
        try:
            name = self.ocr(box=self.box_of_screen(0.62, 0.13, 0.86, 0.20))
            self.log_info(f"周本名称原文: {name}")
        except Exception:
            pass
        return pick_level(self)

    # -- weekly boss: short on waveplates means skip, not fight for nothing --
    @override(FarmEchoTask, "click_team_challenge", expect_sha=_TEAM_CHALLENGE_SHA)
    def click_team_challenge(self):
        # Upstream clicks the challenge button and confirms whatever dialog follows
        # in one go. That dialog can be the one saying there are not enough
        # waveplates to collect a reward, and confirming it fights the boss for
        # nothing. Split in two so the dialog is read before anything is confirmed.
        try:
            self.wait_click_feature("team_start_challenge", raise_if_not_found=True,
                                    click_after_delay=0.5, after_sleep=1)
        except Exception:
            seen = []
            try:
                seen = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
            except Exception:
                pass
            text = " ".join(str(b) for b in seen)
            if "结晶波片不足" in text or "无法获取奖励" in text:
                self.log_info("波片不足挡住开启挑战，点取消跳过本次周本")
                try:
                    self.click_dialog_left_button()
                    self.sleep(1)
                except Exception:
                    pass
                raise TaskDisabledException()
            try:
                self.screenshot("no_start_btn")
                self.log_info(f"找不到开启挑战，整屏读到: {seen}")
            except Exception:
                pass
            raise
        after = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60))
        self.log_info(f"开启挑战后读到: {after}")
        if any("结晶波片" in str(b) or "无法获取奖励" in str(b) for b in (after or [])):
            self.log_info("结晶波片不足，取消并跳过本次周本")
            try:
                self.screenshot("nowave_dialog")
            except Exception:
                pass
            self.click_dialog_left_button()
            self.sleep(1)
            raise TaskDisabledException()
        self.wait_click_skip_dialog_confirm()

    # -- tacet field: keep one settlement screenshot for the daily report ----
    tacet_stamina = TacetTask.use_stamina

    @override(TacetTask, "use_stamina")
    def use_stamina(self, *a, **kw):
        can_continue, used = tacet_stamina(self, *a, **kw)
        if not can_continue:
            try:
                self.screenshot("tacet_drops")
            except Exception:
                pass
        return can_continue, used

    # -- daily: additional tasks first, and never let them sink the run -----
    daily_run = DailyTask.run

    @override(DailyTask, "run")
    def daily(self):
        # One flag per run. Without resetting it here the second daily of a boot
        # would skip its additional tasks entirely.
        self._ark_additional_ran = False
        return daily_run(self)

    open_daily = DailyTask.open_daily

    @override(DailyTask, "open_daily")
    def open_daily_first(self):
        # The weekly boss lives in the additional tasks and each chest costs 60
        # stamina. Upstream runs them last, by which time the stamina farm has
        # spent its 180 and only one chest of three can be opened. Upstream also
        # leaves the call bare because it is their last statement; moved ahead of
        # everything it has to be wrapped, or one weekly-boss error takes the
        # daily, the mail and the pass down with it.
        if not getattr(self, "_ark_additional_ran", False):
            try:
                self.run_additional_tasks()
            except Exception as exc:  # noqa: BLE001
                self.log_error(f"附加任务出错，不拖垮当趟日常: {exc}", exception=exc)
                try:
                    self.screenshot("additional_tasks_error")
                except Exception:
                    pass
        return open_daily(self)

    run_additional = DailyTask.run_additional_tasks

    @override(DailyTask, "run_additional_tasks")
    def run_additional_tasks(self):
        # Upstream calls this as the last statement of run(). We call it early, from
        # open_daily; this makes their trailing call a no-op instead of a second run.
        # The first shape reset the flag in a finally, so the trailing call ran the
        # weekly boss a second time - it only went unnoticed because there was
        # nothing left for it to do.
        if getattr(self, "_ark_additional_ran", False):
            return None
        self._ark_additional_ran = True
        return run_additional(self)

    # -- daily: the stamina farm itself -------------------------------------
    def _farm_hook(cls, name):
        original = getattr(cls, name)

        def hooked(self, *a, **kw):
            if os.path.exists(NO_STAMINA_FLAG):
                self.log_info("刷体力已禁用（标记文件在），这一趟不花波片")
                return None
            # daily=False means must_use=0: farm until there is not enough stamina
            # to enter, so whatever the weekly boss did not spend is still used.
            kw.pop("daily", None)
            kw.pop("used_stamina", None)
            return original(self, *a, **kw)

        override(cls, name)(hooked)

    _farm_hook(TacetTask, "farm_tacet")
    _farm_hook(ForgeryTask, "farm_forgery")
    _farm_hook(SimulationTask, "farm_simulation")


# ---------------------------------------------------------------------------
# Nightmare nests. This used to be the last thing replacing a whole upstream file
# (391 lines over their 255). Two of the three changes are wrappers; only find_nest
# is replaced, and upstream's is 17 lines.
# ---------------------------------------------------------------------------

ONLY_NESTS = "Only Farm These Nests"
# Seconds to wait for the point list to render. Long enough to cover a slow load,
# short enough not to hang the task when the list really is empty.
NEST_LIST_TIMEOUT = 15
# How many line-heights below a nest's name its count may sit, measured in game on
# 2026-08-27: the name's row centre was 317.5 and its count's 388.0, 70.5px apart,
# about 2.35 rows; the next nest's name was 148px away, about 4.9 rows. Four rows
# covers the first and cannot reach the second.
NEST_ROW_SPAN = 4
_KNOWN_DENOMINATORS = ("24", "36", "48", "41")
_NEST_FIND_SHA = "3b0271924cac"


def _install_nest():
    from src.task.NightmareNestTask import NestTarget, NightmareNestTask

    def only_names(self):
        """The nests the operator asked for, or [] for 「all of them」."""
        raw = (self.config.get(ONLY_NESTS) or "").strip()
        if not raw:
            # The key may predate this task's default_config, in which case OK-WW's
            # Config drops it on load. The saved file still has it.
            try:
                import json
                cfg = (pathlib.Path(os.getcwd()) / "configs" / "NightmareNestTask.json")
                raw = str(json.loads(cfg.read_text(encoding="utf-8")).get(ONLY_NESTS) or "").strip()
            except Exception:  # noqa: BLE001
                raw = ""
        return [n.strip() for n in re.split(r"[,，]", raw) if n.strip()]

    def wanted_rows(self):
        """Row centres of the wanted nests' names, or None when none were asked for."""
        names = only_names(self)
        if not names:
            return None
        # The list is still rendering right after the click. OCR-ing two seconds in
        # read nothing, which looked exactly like 「that nest is not in the list」 and
        # skipped the whole task for a day. Wait for any count to appear instead of
        # for a fixed number of seconds.
        for _ in range(NEST_LIST_TIMEOUT):
            if self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re):
                break
            self.sleep(1)
        boxes = self.ocr(0.35, 0.13, 1, 0.96)
        rows = [b.y + b.height / 2 for name in names for b in boxes
                if name in (b.name or "")]
        # Substring, not equality: OCR reads 「落渊南丘残象聚落」 while the setting says
        # 「落渊南丘」, and exact matching found nothing.
        if not rows:
            # Not 「all full」 - 「the names configured are not in this list」. Same
            # outcome, opposite cause, and it has to be visible.
            self.log_error("nightmare nest: 列表里没找到指定的点位 "
                           f"{names}；实际读到的是 {[b.name for b in boxes]}", notify=True)
        return rows

    @override(NightmareNestTask, "find_nest", expect_sha=_NEST_FIND_SHA)
    def find_nest(self):
        rows = wanted_rows(self)
        if rows is not None and not rows:
            return None
        hit_wanted = False
        seen_full = False
        seen_blacklisted = False
        odd_denoms = []
        for count_box in self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re):
            for match in re.finditer(self.count_re, count_box.name):
                numerator, denominator = match.group(1), match.group(2)
                if rows is not None:
                    row = count_box.y + count_box.height / 2
                    span = count_box.height * NEST_ROW_SPAN
                    if not any(-count_box.height <= row - w <= span for w in rows):
                        continue
                    hit_wanted = True
                if denominator not in _KNOWN_DENOMINATORS:
                    odd_denoms.append(count_box.name)
                    continue
                if numerator == denominator:
                    seen_full = True
                    continue
                # Upstream also required numerator == '0', so a nest was skipped for
                # ever once a single echo had been cleared from it. Four nests sat at
                # 10/41 and 6/48 and the task reported nothing to do.
                cache_key = self._make_nest_cache_key(count_box, denominator)
                if cache_key in self._unreachable_nests:
                    seen_blacklisted = True
                    self.log_info(f"skip cached unreachable nightmare nest: {cache_key}")
                    continue
                self.log_info(f"{count_box} is not complete")
                if not hasattr(self, "_ark_nest_progress"):
                    self._ark_nest_progress = {}
                self._ark_nest_progress[cache_key] = numerator
                count_box.x = self.width_of_screen(0.9)
                count_box.y -= count_box.height * 0.9
                count_box.height = 1
                count_box.width = 1
                return NestTarget(count_box, cache_key)
        if rows is not None and hit_wanted:
            # 「Nothing to farm」 had four different causes and one message, so a
            # misread denominator and a real completion looked identical afterwards.
            if odd_denoms:
                self.log_error("nightmare nest: 计数的分母不在已知列表（24/36/48/41），"
                               f"多半是 OCR 读错：{odd_denoms}。本轮跳过，"
                               "但**这不是打满**，请到游戏里核对真实计数", notify=True)
            elif seen_blacklisted and not seen_full:
                self.log_info("nightmare nest: 指定点位本轮已拉黑（打完一局计数没涨），"
                              "跳过——**不是打满**")
            elif seen_full:
                self.log_info("nightmare nest: 指定点位都已打满，跳过")
            else:
                self.log_info("nightmare nest: 指定点位没有可用的计数，跳过")
        return None

    next_nest = NightmareNestTask.get_nest_to_go

    @override(NightmareNestTask, "get_nest_to_go")
    def get_nest_to_go(self):
        # find_nest keeps picking any nest that is not full, so a nest the team
        # cannot beat is chosen again every lap - the game's 「挑战失败」 screen is not
        # one OK-WW knows, so it re-entered every two minutes for ever. Judge by the
        # result instead of by that screen: a lap that moved no counter is a lap not
        # worth repeating, whatever the reason.
        while (nest := next_nest(self)) is not None:
            key = getattr(nest, "cache_key", None)
            if key is None:
                return nest
            progress = getattr(self, "_ark_nest_progress", {}).get(key, "")
            stamp = f"{key}@{progress}"
            tried = getattr(self, "_ark_nest_tried", None)
            if tried is None:
                tried = self._ark_nest_tried = set()
            if stamp in tried:
                self._unreachable_nests.add(key)
                self.log_info("nightmare nest: no progress after an attempt, "
                              f"skip: {key} (still {progress})")
                continue
            tried.add(stamp)
            return nest
        return None

    nest_run = NightmareNestTask.run

    @override(NightmareNestTask, "run")
    def run(self):
        self._ark_nest_tried = set()
        self._ark_nest_progress = {}
        return nest_run(self)


def _write_report(error=""):
    try:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump({"applied": _applied, "skipped": _skipped, "error": error},
                      fh, ensure_ascii=False)
    except OSError:
        pass


try:
    _install_hooks()
    _install()
    _install_teleport()
    _install_nest()
except Exception:  # noqa: BLE001 - never stop OK-WW from starting
    _write_report(traceback.format_exc()[-800:])
else:
    _write_report()
