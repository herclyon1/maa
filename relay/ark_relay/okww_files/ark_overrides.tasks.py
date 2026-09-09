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
import re  # noqa: F401 - used by copied upstream bodies
import time  # noqa: F401 - same
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

    # This one replaces upstream's method outright rather than wrapping it, so
    # upstream's own version never runs. Pinning its hash is what keeps that honest:
    # the day they change `revive_action`, ours is stale by definition and would go
    # on running silently. With the pin, it refuses to bind and says why.
    # Recomputed on the machine with inspect.getsource; update it deliberately after
    # reading what upstream changed, never to make a warning go away.
    @override(FarmEchoTask, "revive_action", expect_sha="e99b2d74c31a")
    def revive_action(self):
        # Inside a realm upstream gives up on reviving - there is no teleport tower
        # to run back to - so one death stops the whole task. For an overnight farm
        # that means standing still until morning. The death dialog is on screen and
        # OK-WW already recognises it, so find the confirm button by its own text and
        # take the next lap. **By text, not by position**: the dialog is titled
        # 「选择复苏物品」, and matching 复苏 clicked the title itself on 2026-09-09.
        if not self._in_realm:
            self.teleport_to_heal()
            self.run_until(lambda: False, 's', 1, running=True)
            self.teleport_to_nearest_boss()
            self.sleep(0.5)
            self.run_until(lambda: self.in_combat() or self.find_treasure_icon(),
                           'w', time_out=12, running=True, target=True)
            self.execute_treasure_hunt()
            self.is_revived = True
            return True
        if not farming_echoes():
            return False
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
# Whole-method copies. Each is upstream's own method with our change applied, so
# upstream's version does not run and a change on their side would leave ours
# stale. That is what expect_sha is for: the hash is of their pristine source,
# and the day it differs the copy refuses to bind and says so.
#
# Only code is copied, never the reasoning: that lives in okww_patches/, which
# these are generated from. test_okww_overlay_copies.py regenerates and compares,
# so a hand edit here that the patch files no longer describe fails the build.
# ---------------------------------------------------------------------------

# FarmEchoTask.run, upstream's own body with our change applied.
# What the change is and why: okww_patches/retrycap.py.
def farm_run(self):
    WWOneTimeTask.run(self)
    self.use_liberation = self.config.get('Use Liberation')
    try:
        return self.do_run()
    except TaskDisabledException as e:
        pass
    except Exception as e:
        logger.error('farm 4c error, try handle monthly card', e)
        self._farm_fail_count = getattr(self, '_farm_fail_count', 0) + 1
        if self._farm_fail_count >= 3:
            self.log_info('连续 3 次失败，退出本次周本任务，不再重试')
            raise TaskDisabledException()
        if self.handle_claim_button() or self.handle_monthly_card():
            self.run()
        else:
            raise


# FarmEchoTask.do_run, upstream's own body with our change applied.
# What the change is and why: okww_patches/claim.py + revive.py.
def farm_do_run(self):
    count = 0
    self._in_realm = self.in_realm()
    self.manage_boss_parameters()
    self.log_info(f'in_realm: {self._in_realm}')
    self._farm_start_time = time.time()
    self._has_treasure = False
    self.is_revived = False
    self.init_parameters()
    if self.teleport_to_boss_enabled():
        self.teleport_to_configured_boss_and_prepare()
    while count < self.config.get("Repeat Farm Count", 0):
        try:
            self.in_realm_check(60)
            self.log_debug(f'start farming {count} {self._in_realm}')
            if not self.is_revived:
                self.manage_boss_interactions()
            else:
                self.is_revived = False
            if self._just_entered_boss_realm:
                self._just_entered_boss_realm = False
            elif not self.in_combat():
                if self._in_realm and not self.in_world():
                    _exited = False
                    import os as _os
                    _claim_ok = not _os.path.exists('C:/ProgramData/ark-okww-farm.no-claim')
                    try:
                        self.walk_to_treasure()
                        self.pick_f(handle_claim=False)
                        self.sleep(2)
                        _o = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0))
                        _txt = ' '.join(str(_b) for _b in (_o or []))
                        if not _claim_ok:
                            self.log_info('刷声骸模式：不领周本奖励，一片结晶波片都不花')
                            if self.teleport_to_boss_enabled() and self._in_realm:
                                self.log_info('刷声骸模式：按 F 重新进一趟')
                                self.enter_configured_boss_realm_from_f()
                                _exited = True
                        elif '领取奖励需消耗' in _txt and '结晶波片' in _txt:
                            self.log_info(f'周本领奖：认出弹窗，点确认。读到 {_txt[:70]}')
                            _btn = self.click_dialog_right_button()
                            if self.wait_feature('gem_add_stamina',
                                                 horizontal_variance=0.4,
                                                 vertical_variance=0.05,
                                                 time_out=3, settle_time=0.5):
                                self.log_info('周本领奖：波片不够，动用备用体力')
                                self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
                                self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
                                self.back(after_sleep=1)
                                self.click(_btn, after_sleep=1)
                            self.sleep(3)
                            self.log_info('周本领奖：已点确认')
                            _o2 = None
                            for _i in range(8):
                                _o2 = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0))
                                _quit = next((_b for _b in (_o2 or []) if '退出副本' in str(_b)), None)
                                if _quit is not None:
                                    self.click(_quit, after_sleep=2)
                                    _exited = True
                                    self.log_info('周本领奖：结算页点了「退出副本」')
                                    break
                                self.sleep(1)
                            if not _exited:
                                self.log_info(f'周本领奖：没等到结算页，整屏读到 {_o2}')
                        else:
                            try:
                                self.screenshot('no_claim_ui')
                            except Exception:
                                pass
                            self.log_info(f'周本领奖：没认出领奖弹窗，整屏读到 {_o}')
                    except Exception as _e:
                        self.log_info(f'周本领奖：这一步没做成，按原样退出 {_e!r}')
                    if not _exited:
                        self.send_key('esc', after_sleep=0.5)
                        self.wait_click_feature('claim_cancel_button_hcenter_vcenter', relative_x=2,
                                                raise_if_not_found=True,
                                                post_action=lambda: self.send_key('esc', after_sleep=1),
                                                settle_time=1)
                    self.wait_in_team_and_world(time_out=120)
                    self.sleep(0.1)
                else:
                    if self._has_treasure:
                        self.wait_until(
                            lambda: self.find_treasure_icon() or self.in_combat(
                                target=True) or self.find_f_with_text(),
                            time_out=5, raise_if_not_found=False)
                    if not self.in_combat():
                        self.log_info('not in combat try click restart')
                        if self.walk_to_treasure_and_restart():
                            self.handle_boss_restart_after_treasure()
                        else:
                            self.scroll_and_click_buttons()

            count += 1
            self.log_info('start wait in combat')
            if not self._in_realm and not self._has_treasure and not self.in_combat():
                self.go_to_boss_minimap()
                self.execute_treasure_hunt()

            self.sleep(self.combat_wait_time)
            self.log_info(f'combat_wait_time: {self.combat_wait_time}')
            self.check_boss_name()

            self.combat_once(wait_combat_time=5, raise_if_not_found=False)
            if self.is_revived:
                continue

            if self.pick_echo():
                logger.info(f'farm echo on the face')
                dropped = True
            elif self.config.get('Echo Pickup Method', "Yolo") == "Yolo":
                dropped = \
                    self.yolo_find_echo(turn=self._in_realm, use_color=False, time_out=self.yolo_time_out,
                                        threshold=self.yolo_threshold)[0]
                logger.info(f'farm echo yolo find {dropped}')
            elif self.config.get('Echo Pickup Method', "Yolo") == "Run in Circle":
                dropped = self.run_in_circle_to_find_echo(circle_count=2)
                logger.info(f'farm echo walk_circle_find_echo {dropped}')
            else:
                dropped = self.walk_find_echo()
                logger.info(f'farm echo walk_find_echo {dropped}')
            self.incr_drop(dropped)
            if not self.bypass_end_wait:
                if dropped and not self._has_treasure:
                    self.wait_until(self.in_combat, raise_if_not_found=False, time_out=5)
                else:
                    self.wait_until(self.in_combat, raise_if_not_found=False, time_out=1)
        except TaskDisabledException:
            raise
        except CharRevivedException:
            self.log_info('刷声骸模式：复活成功，接着刷下一趟')
            self.is_revived = False
            continue
        except Exception as e:
            if self.should_reteleport_after_farm_exception():
                self.log_error('Farm failed after walking into boss combat, teleporting again', e)
                self.is_revived = False
                self.teleport_to_configured_boss_and_prepare()
                continue
            raise


# FarmEchoTask.teleport_to_configured_boss, upstream's own body with our change applied.
# What the change is and why: okww_patches/count.py + nowave.py.
def farm_teleport(self):
    teleport_to_boss = self.config.get('Teleport to Boss', 'No')
    self.ensure_main(time_out=180)
    if teleport_to_boss == 'Weekly Challenge':
        feature = 'zhange'
        serial_number = self.config.get('Which Weekly Boss to Teleport', 1)
        total_number = self.total_weekly_number
    elif teleport_to_boss == 'Boss Challenge':
        feature = 'qiangdi'
        serial_number = self.config.get('Which Boss Challenge to Teleport', 1)
        total_number = self.total_boss_number
    else:
        raise RuntimeError(f'Unknown Teleport to Boss config: {teleport_to_boss}')

    self.info_set('Teleport to Boss', f'{teleport_to_boss} {serial_number - 1}')
    self.openF2Book('gray_book_boss')
    self.open_boss_book(feature)
    is_team = self.click_on_book_target(serial_number, total_number)
    if is_team:
        if teleport_to_boss == 'Weekly Challenge':
            try:
                self.screenshot('weekly_remaining')
            except Exception:
                pass
            _left = None
            try:
                _left = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
                self.log_info(f'周本本周剩余次数原文: {_left}')
            except Exception:
                pass
            import re as _re
            _lt = ' '.join(str(_b) for _b in (_left or []))
            if _re.search(r'次数[^0-9]{0,6}0\s*[/／]\s*3', _lt):
                self.log_info('本周周本次数已领满（0/3），不进本，跳过')
                try:
                    self.ensure_main(time_out=30)
                except Exception:
                    pass
                raise TaskDisabledException()
            try:
                _name = self.ocr(box=self.box_of_screen(0.62, 0.13, 0.86, 0.20))
                self.log_info(f'周本名称原文: {_name}')
            except Exception:
                pass
            self.click_configured_boss_level()
            self.click(0.880, 0.911, after_sleep=2)
        try:
            self.wait_click_feature('team_start_challenge', raise_if_not_found=True,
                                    click_after_delay=0.5, after_sleep=1)
        except Exception:
            _s = []
            try:
                _s = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
            except Exception:
                pass
            _t = ' '.join(str(_b) for _b in _s)
            if '结晶波片不足' in _t or '无法获取奖励' in _t:
                self.log_info('波片不足挡住开启挑战，点取消跳过本次周本')
                try:
                    self.click_dialog_left_button()
                    self.sleep(1)
                except Exception:
                    pass
                raise TaskDisabledException()
            try:
                self.screenshot('no_start_btn')
                self.log_info(f'找不到开启挑战，整屏读到: {_s}')
            except Exception:
                pass
            raise
        _seen = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60))
        self.log_info(f'v3 开启挑战后读到: {_seen}')
        if any('结晶波片' in str(_b) or '无法获取奖励' in str(_b) for _b in (_seen or [])):
            self.log_info('结晶波片不足，取消并跳过本次周本')
            try:
                self.screenshot('nowave_dialog')
            except Exception:
                pass
            self.click_dialog_left_button()
            self.sleep(1)
            raise TaskDisabledException()
        self.wait_click_skip_dialog_confirm()
    else:
        self.wait_click_travel()
    self.wait_in_team_and_world(time_out=120)
    self.sleep(2)
    return is_team


# TacetTask.farm_tacet, upstream's own body with our change applied.
# What the change is and why: okww_patches/tacetshot.py.
def tacet_farm(self, daily=False, used_stamina=0, config=None):
    if config is None:
        config = self.config
    if daily:
        must_use = 180 - used_stamina
    else:
        must_use = 0
    self.info_incr('used stamina', 0)
    while True:
        self.sleep(1)
        self.openF2Book("gray_book_boss")
        current, back_up, total = self.get_stamina()
        if current == -1:
            self.click_relative(0.04, 0.4, after_sleep=1)
            current, back_up, total = self.get_stamina()
        if total < self.stamina_once:
            return self.not_enough_stamina()

        self.open_boss_book('wuyin')
        index = config.get('Which Tacet Suppression to Farm', 1) - 1
        self.teleport_to_tacet(index)
        self.click_team_challenge()
        while True:
            self.wait_in_team_and_world(time_out=120)
            self.combat_once(target=True)
            self.walk_to_treasure()
            self.pick_f(handle_claim=False)
            self.sleep(2)
            if not self.has_claim_stamina():
                self.esc_cancel()
                self.log_info('is not claim treasure, restart challenge')
                continue
            can_continue, used = self.use_stamina(once=self.stamina_once, must_use=must_use)
            self.info_incr('used stamina', used)
            self.sleep(4)
            if not can_continue:
                try:
                    self.screenshot('tacet_drops')
                except Exception:
                    pass
                self.click_relative(0.365, 0.853, hcenter=True)
                self.wait_in_team_and_world(time_out=120)
                return None
            else:
                self.click_relative(0.640, 0.851, hcenter=True, after_sleep=0.2)
                self.wait_click_skip_dialog_confirm()
            must_use -= used


# DailyTask.run, upstream's own body with our changes applied.
# What the changes are and why: okww_patches/stamina.py + nofarm.py.
def daily_run(self):
    self.validate_additional_tasks()

    WWOneTimeTask.run(self)
    self.logged_in = False
    self.ensure_main(time_out=180)

    additional_tasks = self.config.get(ADDITIONAL_TASKS) or []
    condition1 = AUTO_FARM_NIGHTMARE_NEST in additional_tasks
    condition2 = self.config.get('Farm Nightmare Nest for Daily Echo')

    used_stamina, daily_reward_ready = self.open_daily()
    need_stamina = not daily_reward_ready and used_stamina < 180
    need_nightmare = condition1 or (
            condition2
            and not daily_reward_ready
            and self.config.get('Which to Farm', self.support_tasks[0]) != self.support_tasks[0]
    )

    if need_nightmare:
        try:
            self.get_task_by_class(NightmareNestTask).ensure_main = lambda *args, **kwargs: None

            if condition1:
                self.log_debug('Auto Farm all Nightmare Nest')
                self.run_task_by_class(NightmareNestTask)
            elif condition2:
                self.log_debug('Farm Nightmare Nest for Daily Echo')
                self.get_task_by_class(NightmareNestTask).run_capture_mode()
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error("NightmareNestTask Failed", e)
            self.screenshot('NightmareNestTask')
            self.ensure_main(time_out=180)
        finally:
            self.get_task_by_class(NightmareNestTask).__dict__.pop('ensure_main', None)

    try:
        self.run_additional_tasks()
    except Exception as _e:
        self.log_error(f'附加任务出错，不拖垮当趟日常: {_e}', exception=_e)
        try:
            self.screenshot('additional_tasks_error')
        except Exception:
            pass
    self.ensure_main(time_out=180)
    self.open_daily()

    target = self.config.get('Which to Farm', self.support_tasks[0])
    import os as _os
    if _os.path.exists(r'C:\ProgramData\ark-relay\state\no-stamina-farm.flag'):
        self.log_info('本地补丁：刷体力已禁用（标记文件在），这一趟不花波片')
    elif target == self.support_tasks[0]:
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
    self.log_info('Daily Task Completed', notify=True)


def _install_copies():
    global logger, TaskDisabledException, CharRevivedException, WWOneTimeTask
    from ok import Logger
    from ok import TaskDisabledException as _TDE
    from src.task.BaseCombatTask import CharRevivedException as _CRE
    from src.task.DailyTask import DailyTask
    from src.task.FarmEchoTask import FarmEchoTask
    from src.task.TacetTask import TacetTask
    from src.task.WWOneTimeTask import WWOneTimeTask as _WOT

    logger = Logger.get_logger("ark_overrides")
    TaskDisabledException, CharRevivedException, WWOneTimeTask = _TDE, _CRE, _WOT

    override(FarmEchoTask, "run", expect_sha="8456c3034aef")(farm_run)
    override(FarmEchoTask, "do_run", expect_sha="944d6ebebea1")(farm_do_run)
    override(FarmEchoTask, "teleport_to_configured_boss", expect_sha="d0c3a2650802")(farm_teleport)
    override(TacetTask, "farm_tacet", expect_sha="d8194fb3edab")(tacet_farm)
    override(DailyTask, "run", expect_sha="a447990af646")(daily_run)


def _write_report(error=""):
    try:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump({"applied": _applied, "skipped": _skipped, "error": error},
                      fh, ensure_ascii=False)
    except OSError:
        pass


try:
    _install_copies()
    _install()
    _install_teleport()
except Exception:  # noqa: BLE001 - never stop OK-WW from starting
    _write_report(traceback.format_exc()[-800:])
else:
    _write_report()
