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
import sys
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
_adapted: "list[dict]" = []


def _src_sha(fn) -> str:
    try:
        return hashlib.sha1(inspect.getsource(fn).encode("utf-8")).hexdigest()[:12]
    except (OSError, TypeError):
        return ""


def override(cls, name, *, expect_sha=None, adapt=False):
    """Rebind `cls.name`, but only when upstream still looks the way we think.

    `expect_sha` is for a method we copied wholesale: when upstream's own source
    changes, our copy is stale by definition and applying it would quietly undo
    their fix. Without it, the check is just that the attribute exists.

    `adapt=True` is for the one copy whose job is a standing order rather than a
    fix: find_nest carries 「only 落渊南丘」, and skipping it hands the run to
    upstream's 「every nest with a 0」 - the opposite of the order. So a changed
    upstream body is applied anyway (the copy reads what it can from upstream at
    run time, see _upstream_nest_top) and listed under `adapted`, not `skipped`.
    """
    def wrap(fn):
        label = f"{cls.__name__}.{name}"
        old = getattr(cls, name, None)
        if old is None:
            _skipped.append({"what": label, "why": "上游没有这个方法了（改名或删了）"})
            return fn
        if expect_sha:
            got = _src_sha(old)
            if got != expect_sha and adapt:
                _adapted.append({"what": label,
                                 "why": f"上游正文变了（现在 {got or '读不到'}，我们照着 {expect_sha} 抄的），已按新版适配后照样换上"})
            elif got != expect_sha:
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


# 「本周剩余可收取次数：2/3」 as read before entering the weekly boss.
_WEEKLY_LEFT = re.compile(r"次数[^0-9]{0,6}(\d)\s*[/／]\s*3")


def _weekly_left(text):
    """Claims left this week from the pre-entry OCR, or None when unreadable."""
    m = _WEEKLY_LEFT.search(text or "")
    return int(m.group(1)) if m else None


def _after_claim(task):
    """Weekly boss, right after a claim and 「退出副本」: go back in while claims are left.

    One claim per call to FarmEchoTask was never a design. Until 2026-09-07 the
    three claims came from AUTO-MAS retrying an error: every run claimed once and
    then timed out on the ESC dialog (tests/replay/2026-09-07/wuwa: 06-00-55 read
    2/3, claimed once, 「farm 4c error」; the retry 06-08-44 read 1/3). v5 clicked
    「退出副本」 and the error went away - and with it the retries, so from then on
    it was one claim a day (the user, 2026-09-29 13:28). The laps after the claim
    ran in the open world, where incr_drop does nothing.
    Re-entering goes through upstream's own teleport_to_configured_boss_and_prepare,
    the same call its loop makes after a failed lap, so the 0/3 skip and the
    short-on-waveplates skip in the overrides guard the way back in too. Their
    TaskDisabledException is a deliberate stop and goes up untouched.

    The way back in is also the read-back. 「已点确认」 only says we clicked; the
    game's own counter says whether it took the claim, and that counter sits on
    the boss's level page that every way in passes (click_configured_boss_level
    reads it there). So the re-entry runs after the last claim too: there the
    page reads 0/3 and the 0/3 skip stops before 单人挑战 and goes back to the main
    screen. One path, upstream's own (F2 book, boss page, level page), instead of
    a second copy of its first half that would go stale with their next edit.
    Real counter: 2026-10-05 22:13:04 3/3, claim 22:14:39, 22:15:19 2/3, claim
    22:16:51, 22:17:31 1/3, claim 22:19:50, 22:39:48 0/3 (ok-script.log).
    Anything but one less - unread, unchanged, some other number, a way in that
    never reached the level page, a way in that failed - is a stop (_stop).
    Returns True when back in the realm.
    """
    before = getattr(task, "_ark_weekly_left", None)
    task._ark_weekly_left = None      # consumed: the next level page reads it afresh
    if before is None:
        _stop(task, "weekly_left_unread",
              "周本领奖：进本前没读到本周剩余次数，这次领没领到核对不了，停下不再进本")
    if before <= 1:
        task.log_info("周本领奖：本周三次已领满，回选等级页读一眼次数核对（读到 0/3 就不进本）")
    else:
        task.log_info(f"周本领奖：本周还剩 {before - 1} 次，重新进本接着打（选等级页上回读次数）")
    task._ark_claim_before = before
    failed = None
    try:
        task.teleport_to_configured_boss_and_prepare()
    except TaskDisabledException:
        raise
    except Exception as exc:  # noqa: BLE001 - reported and stopped on below
        failed = exc
    finally:
        # Cleared on every way out, so a later run never compares against it.
        pending, task._ark_claim_before = getattr(task, "_ark_claim_before", None), None
    if pending is not None:
        # The level page never came (the arena straight away, or a failure on the way).
        task.log_info(f"周本领奖：重新进本没到选等级页（{failed!r}），次数没回读")
        _stop(task, "weekly_readback_unread", "周本领奖：回读没读到本周剩余次数")
    if failed is not None:
        _stop(task, "weekly_reenter_failed", f"周本领奖：重新进本没做成 {failed!r}，停下")
    return True


def _stop(task, shot, msg):
    """A screen or a number this code does not know: a picture, the phone told, a stop.

    The user's rule: what is not recognised stops with a screenshot and a report;
    it never carries on blind. TaskDisabledException is the stop upstream itself
    treats as a skip - do_run re-raises it (FarmEchoTask.py:202) and run() returns
    on it (FarmEchoTask.py:113) - so no ESC and no next lap acts on the screen.
    """
    _shot(task, shot)
    task.log_error(msg, notify=True)
    raise TaskDisabledException()


def _readback(task, before, after, raw):
    """The level page after a claim: the counter must read exactly one less."""
    if after is None:
        task.log_info(f"周本领奖：回读时选等级页读到 {raw}")
        _stop(task, "weekly_readback_unread", "周本领奖：回读没读到本周剩余次数")
    if after == before - 1:
        task.log_info(f"周本领奖：回读确认领到，本周剩余 {before}/3→{after}/3")
        return
    if after == before:
        _stop(task, "weekly_claim_unchanged", f"周本领奖：回读次数没变（{after}/3），这次没领到")
    _stop(task, "weekly_readback_mismatch", f"周本领奖：回读对不上，本周剩余 {before}/3→{after}/3，停下")


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


def _install_claim():
    """Weekly boss (战歌重奏): actually take the reward.

    Upstream FarmEchoTask is 「farm 4-cost echoes」: after the boss it absorbs the
    dropped echo and goes back to the loop; the reward crystal (F → 「领取奖励需
    消耗60点结晶波片」) is never visited. Until 2026-09-09 this lived in a copied
    do_run, at the top of the next lap; the rewrite dropped it, and on 09-14
    the first re-add hooked handle_claim_button - which only runs when upstream
    itself sees a claim dialog, so it never fired (13:59 that day: 「farm echo on
    the face」 and the task ended, one lap, no crystal). incr_drop is called once
    per lap right after the echo pickup, in the same lap, so the claim goes there.
    """
    from src.task.FarmEchoTask import FarmEchoTask

    upstream_incr = FarmEchoTask.incr_drop

    def _full_ocr(self):
        found = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
        return found, " ".join(str(b) for b in found)

    @override(FarmEchoTask, "incr_drop")
    def incr_drop(self, dropped):
        upstream_incr(self, dropped)
        weekly = str(self.config.get("Teleport to Boss") or "") == "Weekly Challenge"
        # Echo farm: nothing here, and the text patch's 「不退本按 F 重进」 is not
        # brought back. The relay farms with 「Boss Challenge」 (echofarm.py, the
        # config it writes), so `weekly` is already False on every echo-farm lap;
        # farming_echoes() is only the waveplate guard against a stale weekly
        # config. And upstream v3.7.3 loops a realm boss by itself: in the realm and
        # out of combat it leaves (ESC + exit confirm, FarmEchoTask.py:147-152), and
        # the next lap walks to the entrance and presses F back in (:163-164 ->
        # handle_boss_restart_after_treasure :369-373 -> enter_configured_boss_realm_from_f
        # :342-355). It never re-enters without leaving; the old in-realm F was ours.
        if not weekly or farming_echoes() or not getattr(self, "_in_realm", False):
            return
        out = stuck = False
        try:
            # Laps after the claim start in the open world (17:51 on 09-14: two
            # 30-second walks to a crystal that was not there). Only inside the realm.
            if self.in_world():
                return
            fought = getattr(self, "_ark_fought", None)
            if fought is None:
                # combat_once's wrapper sets this on every lap, so unset means that
                # wrapper did not run (skipped by override(), or a lap that bypassed
                # it). Not knowing is not 「fought」: no walk to a crystal on a guess.
                _shot(self, "weekly_fight_unknown")
                self.log_info("周本领奖：这一圈打没打没记到（combat_once 的钩子没跑），不去找结晶")
                return
            if not fought:
                # No fight, so no crystal: walking to one only times out, and the
                # next lap's ESC lands on whatever screen this really is.
                self.log_info("周本领奖：这一圈没打起来（进场后一直没进战斗），不去找结晶")
                try:
                    self.screenshot("weekly_no_fight")
                except Exception:
                    pass
                return
            self.log_info("周本领奖：打完了，去结晶按 F")
            self.walk_to_treasure()
            self.pick_f(handle_claim=False)
            self.sleep(2)
            found, text = _full_ocr(self)
            if "领取奖励需消耗" not in text or "结晶波片" not in text:
                try:
                    self.screenshot("no_claim_ui")
                except Exception:
                    pass
                self.log_info(f"周本领奖：没认出领奖弹窗，整屏读到 {text[:120]}")
                return
            self.log_info(f"周本领奖：认出弹窗，点确认。读到 {text[:70]}")
            btn = self.click_dialog_right_button()
            if self.wait_feature("gem_add_stamina", horizontal_variance=0.4, vertical_variance=0.05,
                                 time_out=3, settle_time=0.5):
                # 「用备用体力补足」 - the two clicks are the game's own dialog, copied
                # from BaseWWTask.use_stamina (the user's order of 2026-09-14: use the backup).
                self.log_info("周本领奖：波片不够，动用备用体力")
                self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
                self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
                self.back(after_sleep=1)
                self.click(btn, after_sleep=1)
            self.sleep(3)
            # The reward screen itself, so a claim can be checked afterwards
            # (中继二 10-05 23:3x: no picture at this moment to recheck by).
            _shot(self, "weekly_claimed")
            self.log_info("周本领奖：已点确认")
            # The game then shows the full-screen 「挑战成功」 settlement (ESC does
            # nothing there); 「退出副本」 returns to the open world.
            last = None
            for _ in range(8):
                last, _t = _full_ocr(self)
                quit_btn = next((b for b in last if "退出副本" in str(b)), None)
                if quit_btn is not None:
                    self.click(quit_btn, after_sleep=2)
                    self.log_info("周本领奖：结算页点了「退出副本」")
                    self.wait_in_team_and_world(time_out=120)
                    out = True
                    break
                self.sleep(1)
            else:
                stuck = True
        except Exception as exc:  # noqa: BLE001 - a failed claim must not kill the run
            self.log_info(f"周本领奖：这一步没做成 {exc!r}")
        # Outside the try, so these reach run(). No settlement page after a confirmed
        # claim is a screen we do not know. Returning would hand it to upstream's next
        # lap, whose first move in a realm is ESC and an exit confirm
        # (FarmEchoTask.py:147-152) - on 10-05 10:34:50 that timed out into 「farm 4c
        # error」. A stop presses nothing.
        if stuck:
            _stop(self, "weekly_no_settlement",
                  f"周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。整屏读到 {last}")
        if out:
            _after_claim(self)


class _EarlyOpen(Exception):
    """Confirmed the 限时提前开放 dialog and landed straight in the arena."""


_BOOK_SCREENS = ['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close']
_ENTRY_LOOKS = 60       # looks 2 s apart after 「确认前往」: upstream's own 120 s for a realm
_WORLD_LOOKS = 3        # looks in a row in the open world before calling it the open world


def _screen_text(task) -> str:
    try:
        return " ".join(str(b) for b in (task.ocr(box=task.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []))
    except Exception as exc:
        return f"读不出（{exc!r}）"


def _shot(task, name):
    try:
        task.screenshot(name)
    except Exception:
        pass


def _entry_unknown(task, seen, why):
    """Stop where we are: screenshot, the whole screen in the log, no walking on a guess."""
    _shot(task, "weekly_entry_unknown")
    task.log_info(f"进本：{why}这一屏认不出，停下不走（不去大世界走路）。整屏读到 {seen[:600]}")


def _after_confirm(task):
    """Where did 「确认前往」 put us? Look until it is a screen we know; otherwise stop.

    The dialog reads 「提前到达目标位置可能影响剧情体验，是否确认前往？」 (bosstip.py).
    Two screens have followed it for real:
    * the boss's level page (2026-10-05 22:05 and 22:17, weekly boss 天演溯心, page
      「定序诸理之律」, 推荐等级40-90, 单人挑战; screenshot 22-07-04.390): return True,
      which is upstream's own 「team screen」 answer from click_on_book_target, so
      upstream's weekly branch (level, 单人挑战, 开启挑战) runs from here exactly as on a
      run without the dialog - one copy of those steps, upstream's;
    * the arena itself (2026-09-09 天傀劫煞): _EarlyOpen, the caller returns True.
    Anything else - the open world, a screen not seen before, nothing after two
    minutes - is a screenshot, the screen's text in the log and an exception, which
    upstream turns into 「Teleport to boss failed」 and run() ends the task. The
    22:05 run walked the open world on a guess and failed twenty seconds later; a
    stop with a picture is the honest version of that.
    The page is looked at again and again, not once: a slow load or one missed read
    must not decide the way.
    """
    seen, world = "", 0
    weekly = str(task.config.get("Teleport to Boss") or "") == "Weekly Challenge"
    for _ in range(_ENTRY_LOOKS):
        task.sleep(2)
        # Upstream's own four screens after 「前往」 (BaseWWTask.click_on_book_target,
        # v3.7.3): the team screen, or the map with the fast-travel button. The
        # 2026-09-09 version (868d09f5) waited for these after the dialog; the move
        # into this file (cfdd4f04) dropped it.
        feature = task.wait_feature(_BOOK_SCREENS, time_out=0.5, settle_time=0, raise_if_not_found=False)
        if feature is not None and getattr(feature, "name", "") == "team_close":
            _shot(task, "early_open_team")
            task.log_info("限时提前开放：确认后是队伍界面，按上游原路进本")
            return True
        if feature is not None:
            if weekly:
                # The weekly boss has a level page, never a map; walking from a map
                # is exactly the open-world guess this must not make.
                _entry_unknown(task, _screen_text(task), "限时提前开放确认后出了传送地图（周本不该有），")
                raise RuntimeError("限时提前开放确认后是传送地图，周本不走")
            _shot(task, "early_open_map")
            task.log_info(f"限时提前开放：确认后是传送地图（{feature.name}），按上游传送原路走")
            return False
        seen = _screen_text(task)
        if "单人挑战" in seen or "推荐等级" in seen:
            _shot(task, "early_open_team")
            task.log_info(f"限时提前开放：确认后是这个 Boss 的选等级页，按正常进本走（选等级→单人挑战→开启挑战）。"
                          f"整屏读到 {seen[:600]}")
            return True
        if task.in_team_and_world():
            if task.in_realm():
                _shot(task, "early_open_landed")
                task.log_info(f"限时提前开放：确认后直接进场，in_realm=True，整屏读到 {seen[:600]}")
                raise _EarlyOpen
            world += 1
            if world >= _WORLD_LOOKS:
                break
        else:
            world = 0
    _entry_unknown(task, seen, f"限时提前开放确认后（in_world={bool(task.in_world())}）")
    raise RuntimeError("限时提前开放确认后画面认不出，停下")


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
                    _BOOK_SCREENS,
                    time_out=15, settle_time=0.5, raise_if_not_found=False)
                if not again:
                    _entry_unknown(self, _screen_text(self), "点了前往，传送界面多等 15 秒也没来，")
                    raise
                self.log_info('传送界面来晚了，多等 15 秒等到了，接着走')
                return again.name == 'team_close'
            self.log_info(f'限时提前开放的剧情提示框，点确认前往。框里读到：{text[:160]}')
            self.click_dialog_right_button()
            # Neither upstream's fast-travel wait nor its team wait fits what comes
            # next; _after_confirm looks and answers in upstream's own terms.
            try:
                return _after_confirm(self)
            except _EarlyOpen:
                raise _EarlyOpen from None

    outer = FarmEchoTask.teleport_to_configured_boss

    @override(FarmEchoTask, "teleport_to_configured_boss")
    def teleport_to_configured_boss(self):
        try:
            return outer(self)
        except _EarlyOpen:
            # True means 「already in the realm」, which is what being dropped into
            # the arena amounts to; upstream's level and team clicks are skipped.
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

# Weekly boss, 「单人挑战」: where upstream's one blind click lands. The box is the
# bottom-right strip the button sits in; on the 2026-09-21 screenshots (1920x1080,
# 10-20-43.029_weekly_remaining / 10-20-58.624_no_start_btn) the text 「单人挑战」
# reads at x1474-1598 y965-1001, inside it.
SOLO_BOX = (0.60, 0.84, 0.98, 0.96)
_SOLO_WAIT = 5          # seconds for 开启挑战 after each click
_SOLO_RETRIES = 3       # extra clicks on 单人挑战 before the old error path runs
_CHALLENGE_LOOKS = 6    # reads 1 s apart after 开启挑战 (~5 s) for the waveplate dialog

# Stamina: upstream's own read box (BaseWWTask.get_stamina) and pattern. get_stamina
# is replaced outright (its body is the bug), so it is pinned: hash of the game
# machine's copy pulled 2026-09-23 (ark-evidence/M5b-0923/src, BaseWWTask.py:409-424).
_GET_STAMINA_SHA = "8ba6c1344ff8"
STAMINA_BOX = (0.49, 0.0, 0.92, 0.10)
_STAMINA_PAIR = re.compile(r"(\d+)/(\d+)")
_STAMINA_DIALOG_READS = 5   # reads, 1 s apart, inside use_stamina's reward dialog


def _confirm_solo(task):
    """Make sure the click on 「单人挑战」 was taken; returns how many extra clicks it took.

    Upstream's teleport_to_configured_boss picks the level, clicks (0.880, 0.911)
    once and never looks at the result (FarmEchoTask.py:262-264). On 2026-09-21 the
    click landed inside the button and the game did not take it: the screen stayed
    on 单人挑战 and the run died ten seconds later on 「no 开启挑战」. This waits for
    开启挑战; while it is missing and 单人挑战 is still on screen, it takes a screenshot,
    logs a line and clicks the button where OCR actually found it, up to
    _SOLO_RETRIES times. Anything else on screen (the waveplate dialog, some other
    screen) is left to click_team_challenge's own handling below.
    """
    for n in range(_SOLO_RETRIES + 1):
        if task.wait_feature("team_start_challenge", time_out=_SOLO_WAIT, raise_if_not_found=False):
            if n:
                task.log_info(f"周本：补点单人挑战 {n} 次后等到了开启挑战")
            return n
        if n == _SOLO_RETRIES:
            break
        seen = task.ocr(box=task.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
        text = " ".join(str(getattr(b, "name", b)) for b in seen)
        if "结晶波片不足" in text or "无法获取奖励" in text:
            return n
        solo = [b for b in (task.ocr(box=task.box_of_screen(*SOLO_BOX)) or [])
                if "单人挑战" in str(getattr(b, "name", ""))]
        if not solo:
            task.log_info(f"周本：{_SOLO_WAIT} 秒没等到开启挑战，屏上也没有单人挑战，整屏读到: {text[:160]}")
            return n
        b = solo[0]
        try:
            task.screenshot(f"solo_retry_{n + 1}")
        except Exception:
            pass
        task.log_info(f"周本：点单人挑战后 {_SOLO_WAIT} 秒没等到开启挑战，屏上仍是单人挑战，"
                      f"补点第 {n + 1} 次 ({b.x + b.width // 2},{b.y + b.height // 2})")
        task.click_box(b, after_sleep=0)
    task.log_info(f"周本：补点单人挑战 {_SOLO_RETRIES} 次都没进开启挑战")
    return _SOLO_RETRIES


def _parse_stamina(names):
    """(current, back_up) from the stamina strip's text blocks in reading order, or None.

    Upstream (BaseWWTask.py:409-424) takes the block matching 数/数 as the current
    stamina, leaves it at 0 when there is none, and lets every later pure number
    overwrite the backup. When 240/240 came back split, that read 「0 / 240」
    (2026-09-21 10:25:49, OK-WW-05-33-53.log:1524) and a full 240 was spent as 60.
    Here: a single block first (searched, as upstream does), then two or three
    neighbours joined (the join has to be exactly 数/数); the backup is only the pure
    number right before the 数/数; nothing found is None, never 0.
    """
    names = [str(n).replace(" ", "") for n in names]
    for span in (1, 2, 3):
        for i in range(len(names) - span + 1):
            joined = "".join(names[i:i + span])
            m = _STAMINA_PAIR.search(joined) if span == 1 else _STAMINA_PAIR.fullmatch(joined)
            if m:
                left = names[i - 1] if i else ""
                return int(m.group(1)), int(left) if left.isdigit() else 0
    return None


def _read_stamina(task, in_dialog):
    reads = _STAMINA_DIALOG_READS if in_dialog else 1
    where = "领奖框" if in_dialog else ""
    for n in range(reads):
        if n:
            task.sleep(1)
        boxes = task.wait_ocr(*STAMINA_BOX, raise_if_not_found=False) or []
        boxes = sorted(boxes, key=lambda b: b.x)
        names = [b.name for b in boxes]
        task.log_info(f"体力读字原文{where}（第 {n + 1} 次）: {names}")
        got = _parse_stamina(names)
        if got:
            return got
    try:
        task.screenshot("stamina_error")
    except Exception:
        pass
    task.log_info(f"体力{where}读了 {reads} 次都没有「数/数」，按没读到处理（-1），不当 0")
    return None


def _install_hooks():
    global logger, TaskDisabledException, CharRevivedException
    from ok import Logger
    from ok import TaskDisabledException as _TDE
    from src.task.BaseCombatTask import CharRevivedException as _CRE
    from src.task.BaseWWTask import BaseWWTask
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
        # Whether this lap saw a fight at all: the weekly claim only walks to the
        # crystal after one (incr_drop). 10-05 10:33:49 it went looking for a
        # crystal 20 seconds after landing, with no fight in between.
        self._ark_fought = False
        try:
            got = farm_combat(self, *a, **kw)
        except CharRevivedException:
            self._ark_fought = True
            self.log_info("刷声骸模式：复活成功，接着刷下一趟")
            return None
        self._ark_fought = bool(got)
        return got

    # -- weekly boss: read the remaining count before entering --------------
    pick_level = FarmEchoTask.click_configured_boss_level

    @override(FarmEchoTask, "click_configured_boss_level")
    def click_configured_boss_level(self):
        _shot(self, "weekly_remaining")
        left = raw = None
        try:
            left = raw = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
            self.log_info(f"周本本周剩余次数原文: {left}")
        except Exception as exc:
            raw = f"读不出（{exc!r}）"
        text = " ".join(str(b) for b in (left or []))
        now = _weekly_left(text)
        self._ark_weekly_left = now
        # Right after a claim this page is the read-back (_after_claim): the counter
        # has to read one less, or the run stops here, before 单人挑战.
        before, self._ark_claim_before = getattr(self, "_ark_claim_before", None), None
        if before is not None:
            _readback(self, before, now, raw)
        if now is None:
            # Unread used to mean 「enter anyway」: the reward costs 60 waveplates
            # and nothing would say whether one was left to take.
            _stop(self, "weekly_left_unread",
                  f"周本：选等级页上没读到本周剩余次数，停下不进本。读到 {raw}")
        if now == 0:
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
        _confirm_solo(self)
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
        # The dialog is looked for again and again, not once. One read 1 s after
        # 开启挑战 missed it on 2026-08-31, upstream's confirm then took the
        # 「无法获取奖励」 dialog, and the boss was fought for no reward. Nothing is
        # confirmed here any more: the one dialog known to follow is that one, and
        # its answer is 取消. A dialog that is up (upstream's own confirm-button
        # template, the one its wait_click_skip_dialog_confirm looks for) but whose
        # text is not that one is unknown: picture, report, stop. Reaching the
        # arena, or the whole window with no dialog, means there is nothing to answer.
        dialog = None
        for n in range(_CHALLENGE_LOOKS):
            if n:
                self.sleep(1)
            after = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60)) or []
            if after or not n:
                self.log_info(f"开启挑战后读到（第 {n + 1} 次）: {after}")
            if any("结晶波片" in str(b) or "无法获取奖励" in str(b) for b in after):
                self.log_info("结晶波片不足，取消并跳过本次周本")
                _shot(self, "nowave_dialog")
                self.click_dialog_left_button()
                self.sleep(1)
                raise TaskDisabledException()
            dialog = self.find_one(['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                                   horizontal_variance=0.1, vertical_variance=0.1)
            if dialog is None and self.in_team_and_world():
                break
        if dialog is not None:
            _stop(self, "challenge_dialog_unknown",
                  f"开启挑战后弹出认不出的对话框，不点确认，停下。整屏读到 {_screen_text(self)[:600]}")

    # -- stamina: an unread 数/数 is 「unknown」, not 0 ------------------------
    @override(BaseWWTask, "get_stamina", expect_sha=_GET_STAMINA_SHA)
    def get_stamina(self):
        # Inside use_stamina the reward dialog is already open and upstream spends
        # on whatever this returns, so it reads again 1 s apart. Everywhere else a
        # miss goes back as -1, which farm_tacet already answers with a click and a
        # second read (TacetTask.py:58-61).
        in_dialog = sys._getframe(1).f_code.co_name == "use_stamina"
        got = _read_stamina(self, in_dialog)
        current, back_up = got if got else (-1, -1)
        self.info_set("current_stamina", current)
        self.info_set("back_up_stamina", back_up)
        return current, back_up, (current + back_up if got else -1)

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
# Tacet field list groups. WuWa 3.7 (2026-09-30) put 沉心域 and 烬心域 at the top
# of F2 「素材获取 → 无音清剿」, so the groups went from [2, 5, 5, 7] to
# [4, 5, 5, 7] (read in game, BOARD/evidence/鸣潮3.7-选项-0930/README.md).
# Upstream (v3.6.9-beta.1) still sets [2, 5, 5, 7] in TacetTask.__init__, and
# click_on_book_target scrolls by that list, so from the fifth field down every
# click lands on the wrong row. Only that exact stale list is replaced: once
# upstream ships its own list, or the instance carries anything else (the
# 2026-09-30 hand edit on the machine says [4, 5, 5, 7]), theirs stands.
# The instances exist before this file runs, so the list is fixed at call time
# rather than in __init__. door_walk_method is left alone: upstream defines it
# but nothing reads it.
# ---------------------------------------------------------------------------
_TACET_GROUPS_OLD = [2, 5, 5, 7]
_TACET_GROUPS_37 = [4, 5, 5, 7]


def _tacet_groups(task):
    """Swap upstream's pre-3.7 group list for the 3.7 one on this task; return the log line."""
    have = list(getattr(task, "structure", None) or [])
    if have == _TACET_GROUPS_OLD:
        task.structure = list(_TACET_GROUPS_37)
        task.total_number = sum(task.structure)
        return (f"无音区分组：上游还是 {have}，按鸣潮 3.7 改成 {task.structure}"
                f"（共 {task.total_number} 个）")
    return (f"无音区分组：{have}（共 {getattr(task, 'total_number', '?')} 个），"
            f"不是 3.7 之前的旧分组，照这份点")


def _install_tacet_groups():
    from src.task.TacetTask import TacetTask

    # getattr, not attribute access: a rename upstream must end up in the skipped
    # list below, not raise here and take every install after this one with it.
    teleport = getattr(TacetTask, "teleport_to_tacet", None)

    @override(TacetTask, "teleport_to_tacet")
    def teleport_to_tacet(self, index):
        self.log_info(_tacet_groups(self))
        return teleport(self, index)


# ---------------------------------------------------------------------------
# Nightmare nests. This used to be the last thing replacing a whole upstream file
# (391 lines over their 255). Two of the three changes are wrappers; only find_nest
# is replaced, and upstream's is 17 lines.
# ---------------------------------------------------------------------------

ONLY_NESTS = "Only Farm These Nests"
# Where the relay says AUTO-MAS's master ConfigFile directory is. The value of
# ONLY_NESTS has to be read from there: AUTO-MAS copies that directory over
# configs/ before OK-WW starts, but ok-script's Config drops every key that is
# not in the task's default_config and **rewrites the file** at load, which
# happens before this extension runs. Reading configs/ afterwards therefore
# finds nothing - that is how every run from 2026-09-10 to 09-13 farmed all four
# nests while the master said 落渊南丘 only.
MASTER_POINTER = r"C:\ProgramData\ark-okww-master.txt"
# Seconds to wait for the point list to render. Long enough to cover a slow load,
# short enough not to hang the task when the list really is empty.
NEST_LIST_TIMEOUT = 15
# How many line-heights below a nest's name its count may sit, measured in game on
# 2026-08-27: the name's row centre was 317.5 and its count's 388.0, 70.5px apart,
# about 2.35 rows; the next nest's name was 148px away, about 4.9 rows. Four rows
# covers the first and cannot reach the second.
NEST_ROW_SPAN = 4
_KNOWN_DENOMINATORS = ("24", "36", "48", "41")
# Pinned to OK-WW v3.7.3 (2026-10-03), whose find_nest moved the top of the list's
# OCR box from 0.13 to 0.25 of the screen. v3.6.9-beta.1 and v3.7.2 were 3b0271924cac;
# the morning runs of 10-04 and 10-05 skipped our copy on that difference and farmed
# upstream's way. A future change is adapted to, not skipped (override(adapt=True)).
_NEST_FIND_SHA = "12d040afa102"
# Upstream's top edge for the list, used when its source cannot be read at run time.
NEST_TOP = 0.25
# The two nest sentences the relay's log reader keys on (collector_okww, outcome).
NEST_COUNT_UNREAD = "指定点位的名字读到了，计数没读到"
NEST_ADAPTED = "只刷指定点位的过滤是按 OK-WW 新版适配装上的"
_NEST_TOP_RE = re.compile(r"self\.ocr\(\s*0\.35\s*,\s*(0?\.\d+)\s*,\s*1\s*,\s*0\.96")


def _upstream_nest_top(fn) -> float:
    """The top of upstream's nest-list OCR box, read from its own find_nest.

    Following upstream here is what keeps our copy current when they move the box
    again: 10-03 they moved it from 0.13 to 0.25. Anything odd falls back to NEST_TOP.
    """
    try:
        m = _NEST_TOP_RE.search(inspect.getsource(fn))
    except (OSError, TypeError):
        m = None
    try:
        top = float(m.group(1)) if m else NEST_TOP
    except ValueError:
        top = NEST_TOP
    return top if 0.0 < top < 0.6 else NEST_TOP


def _install_nest():
    from src.task.NightmareNestTask import NestTarget, NightmareNestTask

    top = _upstream_nest_top(getattr(NightmareNestTask, "find_nest", None))

    def _read_only(path):
        try:
            return str(json.loads(pathlib.Path(path).read_text(encoding="utf-8")).get(ONLY_NESTS) or "").strip()
        except Exception:  # noqa: BLE001 - a missing or broken file is 「not set here」
            return ""

    def only_names(self):
        """The nests the operator asked for, or [] for 「all of them」.

        Sources, in order: the loaded config (only if the key survived), the
        master directory the relay points at, then configs/ as a last resort.
        Which one answered is logged once per run, and 「nothing anywhere」 is an
        error with a push - silently farming every nest is the failure this exists
        to prevent.
        """
        raw, src = (self.config.get(ONLY_NESTS) or "").strip(), "运行中的设置"
        if not raw:
            try:
                master = pathlib.Path(MASTER_POINTER).read_text(encoding="utf-8").strip()
            except OSError:
                master = ""
            if master:
                raw, src = _read_only(pathlib.Path(master) / "NightmareNestTask.json"), "母本"
        if not raw:
            raw, src = _read_only(pathlib.Path(os.getcwd()) / "configs" / "NightmareNestTask.json"), "configs 目录"
        names = [n.strip() for n in re.split(r"[,，]", raw) if n.strip()]
        if getattr(self, "_ark_only_logged", None) != names:
            self._ark_only_logged = names
            if names:
                self.log_info(f"nightmare nest: 只刷 {names}（设置来自{src}）")
            else:
                self.log_error("nightmare nest: 没有「只刷指定点位」的设置，会按上游行为刷全部点位；"
                               "母本、configs 目录和运行中的设置里都没有", notify=True)
        return names

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
            if self.ocr(0.35, top, 1, 0.96, match=self.count_re):
                break
            self.sleep(1)
        boxes = self.ocr(0.35, top, 1, 0.96)
        # Kept for find_nest: when a wanted name has no count beside it, this raw
        # read goes into the log, so the cause can be read off afterwards.
        self._ark_nest_raw = [(b.name, round(b.y)) for b in boxes]
        rows = [b.y + b.height / 2 for name in names for b in boxes
                if name in (b.name or "")]
        # Substring, not equality: OCR reads 「落渊南丘残象聚落」 while the setting says
        # 「落渊南丘」, and exact matching found nothing.
        if rows:
            self._ark_nest_seen = True
        else:
            # Since v3.7.3 the list has a second, scrolled page (go_nest_scroll), and
            # the wanted nest is on one page only. Missing here says nothing yet; the
            # run override says it once, at the end, if no page had it.
            self._ark_nest_missed = [b.name for b in boxes]
        return rows

    def beside(count_box, name_row):
        """Whether a count sits on the row of the name centred at `name_row`."""
        row = count_box.y + count_box.height / 2
        return -count_box.height <= row - name_row <= count_box.height * NEST_ROW_SPAN

    def uncounted(rows, counts):
        """Wanted name rows that have no 「x/y」 count beside them."""
        return [w for w in rows if not any(beside(c, w) for c in counts)]

    @override(NightmareNestTask, "find_nest", expect_sha=_NEST_FIND_SHA, adapt=True)
    def find_nest(self):
        rows = wanted_rows(self)
        if rows is not None and not rows:
            return None
        counts = self.ocr(0.35, top, 1, 0.96, match=self.count_re)
        if rows and uncounted(rows, counts):
            # One more look: the rows of the list do not always finish rendering together.
            self.sleep(1)
            counts = self.ocr(0.35, top, 1, 0.96, match=self.count_re)
        hit_wanted = False
        seen_full = False
        seen_blacklisted = False
        odd_denoms = []
        for count_box in counts:
            for match in re.finditer(self.count_re, count_box.name):
                numerator, denominator = match.group(1), match.group(2)
                if rows is not None:
                    if not any(beside(count_box, w) for w in rows):
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
        if rows and (unread := uncounted(rows, counts)):
            # The name was read and its count was not. Skipping that row silently
            # left 「都已打满」 or nothing at all in the log, for a nest nobody had
            # looked at. Stop on this page with a picture and the raw read instead.
            _shot(self, "nest_count_unread")
            self.log_error(f"nightmare nest: {NEST_COUNT_UNREAD}（名字所在行 {[round(w) for w in unread]}），"
                           f"这一屏不刷——**不是打满**。识字原文 {getattr(self, '_ark_nest_raw', None)}，"
                           "截图 nest_count_unread", notify=True)
            return None
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
        # Back to the open world before opening the book again. Upstream goes straight
        # to openF2Book, and after 「nightmare nest unreachable」 its single back()
        # leaves the map open: F2 then finds no book and the whole task dies with
        # 「can't find gray_book_boss」 (10-05 10:35:22). A person would close the map
        # first. ensure_main is upstream's own way back, with the same 30 s cap its run uses.
        if getattr(self, "_ark_nest_calls", 0):
            try:
                self.ensure_main(time_out=30)
            except TaskDisabledException:
                raise
            except Exception:  # noqa: BLE001 - openF2Book below says it if this did not help
                pass
        self._ark_nest_calls = getattr(self, "_ark_nest_calls", 0) + 1
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

    # Pictures at the two moments a nest lap cannot be checked without: the list
    # as the nest is clicked, and the map around 「nightmare nest unreachable」
    # (10-05 10:35: 0/48 clicked, unreachable, no picture of either). Upstream
    # v3.7.3 NightmareNestTask.py:84 and :163; wrapped, not copied.
    go = getattr(NightmareNestTask, "combat_nest", None)

    @override(NightmareNestTask, "combat_nest")
    def combat_nest(self, nest):
        _shot(self, "nest_go")
        self.log_info(f"nightmare nest: 点进点位 {getattr(nest, 'cache_key', '')}（截图 nest_go）")
        return go(self, nest)

    travel = getattr(NightmareNestTask, "_travel_to_nest_or_skip", None)

    @override(NightmareNestTask, "_travel_to_nest_or_skip")
    def _travel_to_nest_or_skip(self, nest):
        _shot(self, "nest_travel")
        went = travel(self, nest)
        if not went:
            _shot(self, "nest_unreachable")
            self.log_info(f"nightmare nest: 传送不过去 {getattr(nest, 'cache_key', '')}（截图 nest_travel / nest_unreachable）")
        return went

    def nest_entry(self, upstream):
        """What both of upstream's entries share: per-run resets, the gate, the alarm.

        run() is the task; run_capture_mode() is DailyTask's 「Farm Nightmare Nest
        for Daily Echo」 (upstream DailyTask.py:106), which calls it directly and so
        went round everything that used to live in run() alone.
        """
        self._ark_nest_tried = set()
        self._ark_nest_progress = {}
        self._ark_only_logged = None      # log the filter's source once per run
        self._ark_nest_calls = 0
        self._ark_nest_seen = False
        self._ark_nest_missed = None
        self._ark_nest_raw = None
        unreachable = getattr(self, "_unreachable_nests", None)
        if unreachable is not None:
            unreachable.clear()           # upstream's entries do this too; ours must not depend on it
        if "NightmareNestTask.find_nest" not in _applied and only_names(self):
            # Our find_nest is the filter. Without it upstream picks every nest that
            # reads 0 - the opposite of the standing order (only 落渊南丘). Not farming
            # is the lesser harm, and the report already names why.
            self.log_info("nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴")
            return None
        if any(a.get("what") == "NightmareNestTask.find_nest" for a in _adapted) and only_names(self):
            # Upstream changed find_nest and our copy went in adapted, not verified.
            # Said in OK-WW's own log so the run's report carries it (collector_okww).
            self.log_info(f"nightmare nest: {NEST_ADAPTED}，这一轮请核对只进了指定点位")
        try:
            return upstream()
        finally:
            if self._ark_nest_missed is not None and not self._ark_nest_seen:
                # Not 「all full」 - 「the names configured are not in this list」. Same
                # outcome, opposite cause, and it has to be visible.
                self.log_error("nightmare nest: 列表里没找到指定的点位 "
                               f"{only_names(self)}；实际读到的是 {self._ark_nest_missed}", notify=True)

    nest_run = NightmareNestTask.run
    capture_run = getattr(NightmareNestTask, "run_capture_mode", None)

    @override(NightmareNestTask, "run")
    def run(self):
        return nest_entry(self, lambda: nest_run(self))

    @override(NightmareNestTask, "run_capture_mode")
    def run_capture_mode(self):
        return nest_entry(self, lambda: capture_run(self))


# What the official launcher passes to Wuthering Waves.exe, read from Win32_Process
# on 2026-10-01 while the launcher had the game up: `"Wuthering Waves.exe" -krqlv=hd
# -krqlv=hd`, nothing else.
LAUNCH_ARG = "-krqlv=hd"


def _install_launch():
    # Since the 3.7 client (installed 2026-09-30) a bare start of Wuthering Waves.exe
    # dies about ten seconds in with "Fatal error: [File:Unknown] [Line: 54] / kuro:
    # Use launcher to start game!", and the dialog holds the process open. OK-WW
    # starts it bare - start_controller.start_device passes no arguments unless
    # "Launch with DX11" is on, and there is no setting for any other - so it waited
    # for a window that never came until AUTO-MAS's 120-minute limit, three times
    # running on 10-01. With -krqlv=hd added the same exe reaches the login screen.
    #
    # start_controller imports `execute` into its own namespace and calls it by bare
    # name, so rebinding it there reaches start_device without copying that method.
    import ok.core.start_controller as start_controller

    start_execute = start_controller.execute

    @override(start_controller, "execute")
    def execute(game_cmd, arguments=None, *args, **kwargs):
        if (isinstance(game_cmd, str)
                and game_cmd.strip().strip('"').casefold().endswith("wuthering waves.exe")
                and "-krqlv" not in (arguments or "")):
            arguments = f"{arguments} {LAUNCH_ARG}" if arguments else LAUNCH_ARG
        return start_execute(game_cmd, arguments, *args, **kwargs)


def _write_report(error=""):
    if os.name != "nt":
        return          # the relay's tests exec this file on a Mac; no report there
    try:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump({"applied": _applied, "skipped": _skipped, "adapted": _adapted, "error": error},
                      fh, ensure_ascii=False)
    except OSError:
        pass


# On its own, ahead of the rest: without it the game never starts, so nothing else
# here matters - and a failure in the block below must not take it down too.
try:
    _install_launch()
except Exception:  # noqa: BLE001 - never stop OK-WW from starting
    _skipped.append({"what": "ok.core.start_controller.execute",
                     "why": "启动参数没挂上：" + traceback.format_exc()[-300:]})

try:
    _install_hooks()
    _install()
    _install_teleport()
    _install_nest()
    _install_claim()
    _install_tacet_groups()
except Exception:  # noqa: BLE001 - never stop OK-WW from starting
    _write_report(traceback.format_exc()[-800:])
else:
    _write_report()
