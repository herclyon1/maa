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
# The weekly boss / echo farm ending as FAILED (see _end_failed). _ArkStop is made a
# subclass of OK-WW's TaskDisabledException at install time (_install_hooks).
_ArkStop = Exception
# What FarmEchoTask.run logs, then raises as ArkStopped, when a run ends as failed.
FAILED_MARK = "这一趟按失败结束："

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
        if why := getattr(fn, "_ark_refused", ""):
            # The copy itself said it cannot work against this upstream (see refuse()).
            _skipped.append({"what": label, "why": why})
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


def refuse(why):
    """Stacked under @override: keep this copy out and list it as skipped with `why`.

    For a copy that reads something it needs from upstream at install time and could
    not: binding it with a guess is worse than not binding it. '' lets it through.
    """
    def mark(fn):
        fn._ark_refused = why
        return fn
    return mark


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


class ArkStopped(Exception):
    """A FarmEchoTask run (weekly boss or echo farm) that ended without doing its job.

    A plain Exception, so OK-WW counts the task as failed - not skipped, which is
    what its TaskDisabledException means. Raised only by the outermost
    FarmEchoTask.run, after upstream's own run() has returned (_install_hooks).
    A waveplate shortage never raises it (_skip_short)."""


def _end_failed(task, why):
    """End this FarmEchoTask run as FAILED, without anything acting on the screen first.

    Until 2026-10-06 these stops raised TaskDisabledException, which OK-WW ends as
    「skipped」, so a stop on an unknown screen or three failures in a row ended
    the task as if there had been nothing to do. The user ordered every error
    pushed, 2026-10-06: 「只要是报错…不论多少次什么错误都要发」. A waveplate shortage
    is not an error and does not come here (_skip_short).

    The way out is still OK-WW's own: _ArkStop is a TaskDisabledException, the one
    exception upstream lets through untouched - do_run re-raises it
    (FarmEchoTask.py:202), run() returns on it (FarmEchoTask.py:113), and our
    teleport wrapper unwraps it - so no ESC, no retry and no next lap acts on the
    screen. The reason is kept on the task, and the outermost FarmEchoTask.run
    turns it into ArkStopped once upstream's run() is over.
    """
    task._ark_failed = why
    raise _ArkStop()


def _skip_short(task):
    """End this FarmEchoTask run as SKIPPED for a waveplate shortage.

    The game refused the weekly reward for want of crystal waveplates. No reason is
    kept on the task: the outermost FarmEchoTask.run sees none, logs no FAILED_MARK,
    raises no ArkStopped, and OK-WW ends the task as skipped - so AUTO-MAS does not
    retry a run whose retry, minutes later, would find no more waveplates than this
    one. The shortage itself is not hidden: the caller has already logged the skip
    line, and the relay reads it (outcome.WEEKLY_SHORT) as an item undone, pushed to
    the group (outcome.okww_checks; green, daily report only, from 2026-10-07 to 10-11).
    """
    raise _ArkStop()


def _stop(task, shot, msg):
    """A screen or a number this code does not know: a picture, the phone told, a stop.

    The user's rule: what is not recognised stops with a screenshot and a report;
    it never carries on blind. It ends the run as FAILED (_end_failed).
    """
    _shot(task, shot)
    task.log_error(msg, notify=True)
    _end_failed(task, msg)


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


def _weekly(task) -> bool:
    return str(task.config.get("Teleport to Boss") or "") == "Weekly Challenge"


def _install_claim():
    """Weekly boss (战歌重奏): take the reward instead of cancelling it.

    Upstream's claim step is BaseWWTask.handle_claim_button: wait for the claim
    dialog (has_claim) and press ESC, i.e. 取消. The change is that one step, on
    FarmEchoTask only (the ESC stays right for every other task): on the weekly
    boss's claim dialog, click 确认 instead.

    One piece upstream does not do in the weekly realm: get to the crystal. After
    the fight upstream's next lap, in the realm and out of combat, leaves it
    (ESC + exit confirm, FarmEchoTask.py:147-152, v3.7.4 the same), because
    in_world() is False inside a realm (BaseWWTask.in_world: no world_earth_icon,
    illusive_realm_exit present). Its walk to a treasure (:163-164) runs only in
    the open world, and with Teleport to Boss on, its follow-up is
    enter_configured_boss_realm_from_f (:369-373), never scroll_and_click_buttons.
    So incr_drop - called once per lap right after the echo pickup - walks there
    with upstream's own walk_to_treasure and presses F with its own pick_f, which
    calls handle_claim_button exactly as scroll_and_click_buttons does.
    Echo farm: the relay farms with 「Boss Challenge」 (echofarm.py writes it), so
    neither hook acts there; farming_echoes() guards a stale weekly config.
    """
    from src.task.FarmEchoTask import FarmEchoTask

    upstream_incr = FarmEchoTask.incr_drop
    upstream_claim = getattr(FarmEchoTask, "handle_claim_button", None)

    @override(FarmEchoTask, "handle_claim_button")
    def handle_claim_button(self):
        # Basis: upstream BaseWWTask.handle_claim_button (wait has_claim, 1.5 s, sleep
        # 0.5), with 确认 for its ESC; WWA doWeeklyChallenge (领取奖励 -> 确认 -> the
        # follow-up dialog -> 退出副本 / 重新挑战).
        if not _weekly(self) or farming_echoes():
            return upstream_claim(self)
        if not self.wait_until(self.has_claim, raise_if_not_found=False, time_out=1.5):
            return None
        self.sleep(0.5)
        # has_claim matches the dialog's cancel button, which the exit-realm dialog
        # and the solute offer share; upstream's run() also calls this on any
        # two-button dialog after an error (#1649). Only the claim dialog's own text
        # is confirmed (WWA reads it the same way); anything else gets upstream's ESC.
        found, text = _screen_read(self)
        if "领取奖励" not in text:
            return upstream_claim(self)
        # 10-12 11:44 the claim was confirmed with 17 waveplates and 24 backup: the
        # backup became waveplates, 41 was still short of 60, and the reward was not
        # taken. Read the top bar first (WWA does the same on this dialog and does not
        # confirm below 60); when together they cannot pay, cancel and skip as short,
        # leaving the backup untouched. A bar that is not read is not confirmed blind:
        # that is how 10-12 11:44 spent the backup for nothing. It stops with a picture.
        # Logged before the click, which can raise (f40d0b19).
        wave, spare = _waveplates(self, found)
        if wave is None or spare is None:
            _stop(self, "weekly_claim_bar_unread",
                  f"周本领奖：领奖框上顶栏的波片没读全（波片 {wave}，备用 {spare}），不点确认，停下。"
                  f"整屏读到 {text[:400]}")
        self.log_info(f"周本领奖：顶栏读到波片 {wave}/240，备用 {spare}")
        if wave + spare < _CLAIM_COST:
            self.log_info(f"结晶波片不足，取消并跳过本次周本（波片 {wave} + 备用 {spare}，"
                          f"不够领一次的 {_CLAIM_COST}，不动备用体力）")
            _shot(self, "weekly_short_claim")
            self.click_dialog_left_button()
            self.sleep(1)
            _skip_short(self)
        self.log_info(f"周本领奖：认出弹窗，点确认。读到 {text[:400]}")
        btn = self.click_dialog_right_button()
        if self.wait_feature("gem_add_stamina", horizontal_variance=0.4, vertical_variance=0.05,
                             time_out=3, settle_time=0.5):
            # Not enough waveplates: the game's top-up dialog, answered with the clicks
            # upstream's BaseWWTask.use_stamina makes on it (:445-450). The click at
            # (0.70, 0.71) confirms whatever the dialog has selected. With backup
            # waveplates that is the backup (09-14 walk-through: 「默认选中备用体力」),
            # which is what the user asked for on 09-14, in his own words
            # 「体力不够刷一次周本就用备用体力，备用体力有」 (short for the weekly boss: use the backup).
            # With none it offers crystal solute and astrite (10-12 11:45:02: 「请选择补充方式」,
            # 19 solute, 15652 astrite), and 10-12 15:29 and 15:31 paid that way: backup
            # 0, the clicks went through, both claims were taken (ok-script.2026-10-12
            # .log:2793-2821, :2874-2902). So this is reached only with both bar values
            # read and wave < 60 <= wave + backup (the checks above), i.e. there is
            # backup and it covers the gap. A top-up dialog after a bar that read 60 or
            # more means the read was wrong: cancel and stop, never click it.
            if wave >= _CLAIM_COST:
                why = (f"周本领奖：顶栏读到波片 {wave}/240 够领，游戏却弹了补充波片的框，"
                       f"不点补充（可能动结晶溶剂），取消并停下")
                _shot(self, "weekly_topup_unexpected")    # the dialog itself, before the cancel
                self.back(after_sleep=1)
                self.click_dialog_left_button()
                self.log_error(why, notify=True)
                _end_failed(self, why)
            self.log_info("周本领奖：波片不够，动用备用体力")
            self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
            self.click_relative(0.70, 0.71, hcenter=True, after_sleep=1)
            self.back(after_sleep=1)
            self.click(btn, after_sleep=1)
            if self.wait_feature("gem_add_stamina", horizontal_variance=0.4, vertical_variance=0.05,
                                 time_out=3, settle_time=0.5):
                # Backup spent and still short: what is offered now is solute / astrite
                # (10-12 11:44). WWA answers this follow-up with 取消; so do we, and the
                # top-up clicks are never made on this one.
                # Logged before the clicks: the relay reads it as a shortage, not an error.
                _shot(self, "weekly_short_claim")
                self.log_info("结晶波片不足，取消并跳过本次周本（备用体力用上了仍不够 60，不点补充）")
                self.back(after_sleep=1)
                self.click_dialog_left_button()
                _skip_short(self)
        _shot(self, "weekly_claimed")
        self.log_info("周本领奖：已点确认")
        # The settlement page (挑战成功, 退出副本 / 重新挑战; WWA WeeklyExit). 退出副本
        # puts us back in the open world, from where _after_claim goes back in.
        if self.wait_click_ocr(match=re.compile("退出副本"), time_out=15, raise_if_not_found=False,
                               after_sleep=2):
            self.log_info("周本领奖：结算页点了「退出副本」")
            self.wait_in_team_and_world(time_out=120)
            self._ark_claimed = True
        else:
            # A screen we do not know after a confirmed claim. Handing it back let
            # upstream's next lap press ESC and wait for an exit confirm on it
            # (FarmEchoTask.py:151-157), which timed out into 「farm 4c error」 on
            # 10-05 10:34:50. A stop presses nothing (restored from b93709e8).
            _stop(self, "weekly_no_settlement",
                  f"周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。"
                  f"整屏读到 {_screen_text(self)[:400]}")
        return True

    @override(FarmEchoTask, "incr_drop")
    def incr_drop(self, dropped):
        upstream_incr(self, dropped)
        if not _weekly(self) or farming_echoes():
            return
        # A claim already made this lap through upstream's own pickup (pick_echo /
        # walk_find_echo -> pick_f -> handle_claim_button, BaseWWTask.py:577-591,
        # FarmEchoTask.py:187-199) has clicked 「退出副本」 and left us in the open
        # world, where the check below returns. The read-back and the way back in
        # still have to happen, here as after our own walk to the crystal.
        if getattr(self, "_ark_claimed", False):
            self._ark_claimed = False
            _after_claim(self)
            return
        if not getattr(self, "_in_realm", False) or self.in_world():
            return
        # Upstream's own test for a treasure to walk to (walk_to_treasure_and_restart,
        # and the 5 s wait for it in do_run). No crystal, or a walk that does not get
        # there, used to go back to upstream (a8cc86b6, after 10-12 09:52:20). Its
        # next lap in the realm presses ESC and leaves (FarmEchoTask.py:151-157), so
        # the reward was left behind without a word. Both are screens this code does
        # not understand, and the file's rule for those is a picture and a stop (_stop).
        if not self.wait_until(self.find_treasure_icon, time_out=5, raise_if_not_found=False):
            _stop(self, "weekly_no_crystal",
                  f"周本领奖：这一圈打完没看到结晶，不领就会被上游按 ESC 退本，停下。整屏读到 {_screen_text(self)[:400]}")
        self.log_info("周本领奖：打完了，去结晶按 F")
        self._ark_claimed = False
        try:
            self.walk_to_treasure()
        except TaskDisabledException:
            raise
        except Exception as exc:  # noqa: BLE001 - reported and stopped on
            _stop(self, "weekly_walk_failed",
                  f"周本领奖：没走到结晶 {exc!r}，不领就会被上游按 ESC 退本，停下。整屏读到 {_screen_text(self)[:400]}")
        self.pick_f()
        if getattr(self, "_ark_claimed", False):
            self._ark_claimed = False
            _after_claim(self)


class _EarlyOpen(Exception):
    """Confirmed the 限时提前开放 dialog and landed straight in the arena."""


_BOOK_SCREENS = ['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close']
_ENTRY_LOOKS = 60       # looks 2 s apart after 「确认前往」: upstream's own 120 s for a realm
_WORLD_LOOKS = 3        # looks in a row in the open world before calling it the open world


def _screen_read(task):
    """(boxes, text) of one full-screen OCR; no boxes and the error as text when it fails."""
    try:
        found = task.ocr(box=task.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
    except Exception as exc:
        return [], f"读不出（{exc!r}）"
    return found, " ".join(str(b) for b in found)


def _screen_text(task) -> str:
    return _screen_read(task)[1]


_CLAIM_COST = 60       # the claim dialog asks for 60 crystal waveplates
# 「41/240」, and 「240/240+」 when the waveplates are full (0921-weekly.log:18; the level
# page 10-05 22:17:31 read 「0/240+」).
_WAVE_READ = re.compile(r"(\d{1,3})\s*/\s*240\+?")
_DIGITS = re.compile(r"\d{1,3}")


def _waveplates(task, found):
    """(waveplates, backup) from the top bar of a full-screen read, None for what is unread.

    The bar reads [backup] [waveplates/240] [astrite], left to right (10-12 11:45:02
    screenshot weekly_no_settlement: 0, 41/240, 15652): the backup is the bare number
    nearest to the left of the /240 box. Restored from 2ae8d291.
    """
    try:
        top = task.height_of_screen(0.1)
        strip = [(str(getattr(b, "name", b)).strip(), b) for b in found if b.y < top]
        cur = next(((b, int(m.group(1))) for n, b in strip if (m := _WAVE_READ.fullmatch(n))), None)
        if cur is None:
            return None, None
        left = [(b.x, int(n)) for n, b in strip if b.x < cur[0].x and _DIGITS.fullmatch(n)]
        return cur[1], (max(left)[1] if left else None)
    except Exception:  # noqa: BLE001 - plain strings or no frame: unread, and the caller stops
        return None, None


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
# A few still replace a method outright, because upstream's own body is what has
# to go: click_team_challenge (the whole point is to split it in two), get_stamina
# (its body is the bug) and find_nest (the nest filter). Each is pinned to
# upstream's hash. revive_action was one until 2026-10-13. It is gone because
# v3.7.4 FarmEchoTask.revive_action (:92-106) hands a realm death to
# BaseCombatTask.revive_action (:227-240) whenever Teleport to Boss is on. That
# cancels the revive popup (close_revive_popup, :202-224), leaves the realm to heal,
# and do_run teleports back (FarmEchoTask.py:216-229), at most 3 times per run; after
# that do_run returns and the relay's echo farm relaunches OK-WW after 5 quiet
# minutes (echofarm.RESTART_QUIET_MINUTES). Ours clicked 确认 and spent a revive
# item on every death to carry on in place.
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
_CHALLENGE_LOOKS = 6    # reads 1 s apart after 开启挑战 (~5 s) for an unknown dialog
# Seconds to wait for the 「无法获取奖励」 reminder after 单人挑战. Upstream waits 1 s
# (FarmEchoTask.py:374-378); on 10-12 11:43:16 and 15:28:19 it was found within
# 0.3 s of that window opening. 2 s leaves room for a slower frame.
_SOLO_DIALOG_WAIT = 2
_CONFIRM_BTNS = ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter']

# Stamina: upstream's own read box (BaseWWTask.get_stamina) and pattern. get_stamina
# is replaced outright (its body is the bug), so it is pinned: hash of the game
# machine's copy pulled 2026-09-23 (ark-evidence/M5b-0923/src, BaseWWTask.py:409-424).
_GET_STAMINA_SHA = "8ba6c1344ff8"
STAMINA_BOX = (0.49, 0.0, 0.92, 0.10)
_STAMINA_PAIR = re.compile(r"(\d+)/(\d+)")
_STAMINA_DIALOG_READS = 5   # reads, 1 s apart, inside use_stamina's reward dialog


def _confirm_solo(task):
    """Make sure the click on 「单人挑战」 was taken; returns how many extra clicks it took.

    The click on 单人挑战 is one click at (0.880, 0.911) (v3.7.4 click_solo_challenge,
    FarmEchoTask.py:374-378, and ours for the weekly boss), and nothing checks that
    the game took it. On 2026-09-21 the click landed inside the button and the game
    did not take it: the screen stayed on 单人挑战 and the run died ten seconds later
    on 「no 开启挑战」. This waits for 开启挑战; while it is missing and 单人挑战 is
    still on screen, it takes a screenshot, logs a line and clicks the button where
    OCR actually found it, up to _SOLO_RETRIES times. Anything else on screen is
    left to click_team_challenge's own handling below. The 「无法获取奖励」 reminder is
    answered before this, in click_solo_challenge.
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


# ---------------------------------------------------------------------------
# Daily activity chests (2026-10-10). Upstream's claim_daily clicks one fixed
# point, the 100 chest (upstream PR #1135 found it by OCR of 「100」 at the bottom
# right; #1147 moved the fallback point), and never looks again. Below 100 points
# the 20-80 chests are never clicked: 10-10 ended at 80 points with all four
# unclaimed and 「Daily Task Completed」 in the log; the user's words (10-10 19:4x) are
# quoted in docs/OKWW-PATCHES.md, 「Daily activity chests」.
#
# Now every chest up to the points read is clicked, and each is checked afterwards
# by the claimed mark (a white tick in a dark circle) at its place. Places are
# measured from the tier labels the OCR finds, in units of one tier step (label
# centre to label centre for 20 points), so the OCR box size and the screen size
# do not matter. Geometry and the tick were taken from the user's own screenshot
# BOARD/evidence/ww-daily-80-1010.png (claimed 20-80: score 0.94-0.99; the
# unclaimed 100: 0.49). The relay reads the lines below (outcome.okww_checks).
#
# A label is placed by the centre of its last two digits, not of its box: the chest
# keeps one distance from the label's right edge, so 「100」's box centre sits half a
# digit further left than a two-digit label's. Placed by the box centre, the 100 chest
# was looked for 14 px left of its tick on 2026-10-11 09:29 (all five claimed; the
# tick scored 0.96 where it is, 0.35 where it was looked for) and 「没领到」 went out.
# Evidence: tests/fixtures/ww-daily-140-1011-row.png, from that run's screenshot.
# ---------------------------------------------------------------------------
_CLAIM_DAILY_SHA = "2b4977b62f7c"       # upstream claim_daily as copied in _claim_daily_checked
DAILY_TIERS = (20, 40, 60, 80, 100)
DAILY_POINTS_LINE = "活跃奖励：活跃度 "
DAILY_OK = "活跃奖励：领完核对通过"
DAILY_FAILED = "活跃奖励没领到："
DAILY_UNCHECKED = "活跃奖励：没有核对，"
_CHEST_DX, _CHEST_DY, _CHEST_D = 0.203, -0.094, 0.218
_CHECKED_MIN = 0.75
_CHECK_N = 20
_CHECK_T = (
    "3+oqMzk2OjQyJyQ1MDAwMDA2r/TkLy8yLiwtNjwlJic+Pj9DPUI+0Cg2NTMqLjIzJiUlJTY6RUhIT870MjAwLTU8"
    "OUImJSUlOz1ARVKe+No4Kik6QDkvLiclKCcrRVBTUPL5UTcsM3BmaHlaW0UtWFxoeYTh82BPNjNvdm2EbmtnY1Ni"
    "aHB5vfaoT00xR2qEdHB3d3JlUGxwdrr053pxQDZKbnH19PK1fmBVd3qU8+x0cWxALDFeaPX09PPweXVedvL1Z2Bi"
    "TSsmMDlF9fjz9fTzknf09qFMQzctKT06ZmlxZ6nx9fXsmPPgcUhsXlM3NUBkeW1neonq9PT3439wW29vYzY7O2Jx"
    "b250fYj29vaAdWl+Z2FjLzA6ZGduanV1fPL1v3JwgW5kaFovMDhoXnBwb2x04ut4cIJvYWxqOC0sNT89PUdPU0vX"
    "UkxJS0RMSDwsNCo5OjAoLDU+MDcyMTs3Njs3Niwvyi0tNzYxMD8+LSwsPDg2LywwMmjvxS0sMDY7MzgsKjc4NC0t"
    "NDFo8g=="
)


def _check_template():
    import base64
    import numpy as np
    raw = np.frombuffer(base64.b64decode(_CHECK_T), dtype=np.uint8)
    return raw.reshape(_CHECK_N, _CHECK_N).astype(float)


def _sample(gray, cx, cy, d, n=_CHECK_N):
    """An n x n nearest-neighbour sample of the d x d square centred on (cx, cy), or None off the frame."""
    import numpy as np
    xs = (cx - d / 2 + (np.arange(n) + 0.5) * d / n).astype(int)
    ys = (cy - d / 2 + (np.arange(n) + 0.5) * d / n).astype(int)
    if xs.min() < 0 or ys.min() < 0 or xs.max() >= gray.shape[1] or ys.max() >= gray.shape[0]:
        return None
    return gray[np.ix_(ys, xs)].astype(float)


def _ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    den = float((a * a).sum() * (b * b).sum()) ** 0.5
    return float((a * b).sum() / den) if den else 0.0


def tier_labels(boxes, frame_h):
    """OCR boxes (name, x, y, width, height) -> {tier: (cx, cy)} for the chest row.

    cx is the centre of the label's last two digits (its box centre for 20-80, a third
    of the box in from the right edge for 100): the chest keeps one distance from the
    label's right edge, so this puts every chest at the same offset from its cx.
    The big points number at the left can read 「80」 too, and a quest row 「20」; only
    boxes on the row most labels share are kept, one per tier."""
    got = []
    for b in boxes or []:
        name = str(getattr(b, "name", "")).strip()
        if name.isdigit() and int(name) in DAILY_TIERS:
            got.append((int(name), b.x + b.width - b.width / len(name), b.y + b.height / 2))
    if not got:
        return {}
    ys = sorted(y for _, _, y in got)
    mid = ys[len(ys) // 2]
    out = {}
    for t, x, y in got:
        if abs(y - mid) <= 0.03 * frame_h and (t not in out or abs(y - mid) < abs(out[t][1] - mid)):
            out[t] = (x, y)
    return out


def tier_step(labels):
    """One tier step in pixels (median over neighbouring labels), or None under two labels."""
    ts = sorted(labels)
    steps = [(labels[b][0] - labels[a][0]) / ((b - a) / 20) for a, b in zip(ts, ts[1:])]
    steps = sorted(s for s in steps if s > 0)
    return steps[len(steps) // 2] if steps else None


def chest_at(labels, step, tier):
    x, y = labels[tier]
    return x + _CHEST_DX * step, y + _CHEST_DY * step


def tier_scores(gray, labels, step):
    """{tier: how much its chest looks claimed} (normalised correlation with the tick, 1 = same)."""
    t_img = _check_template()
    out = {}
    for tier in labels:
        cx, cy = chest_at(labels, step, tier)
        best = -1.0
        for d in (0.200, 0.218, 0.236):
            for ox in (-0.02, -0.01, 0.0, 0.01, 0.02):
                for oy in (-0.02, -0.01, 0.0, 0.01, 0.02):
                    crop = _sample(gray, cx + ox * step, cy + oy * step, d * step)
                    if crop is not None:
                        best = max(best, _ncc(crop, t_img))
        out[tier] = round(best, 2)
    return out


def _gray(task):
    try:
        task.next_frame()
    except Exception:
        pass
    frame = getattr(task, "frame", None)
    if frame is None:
        return None
    return frame.mean(axis=2) if frame.ndim == 3 else frame.astype(float)


def _bar(task):
    """(labels, step, gray) for the chest row on screen, or None.

    A reward window over the page hides the row: one ESC closes it. Failing that the
    dailies page is opened again the way upstream's open_daily does (openF2Book goes
    back to the world first, BaseWWTask.openF2Book), so no second ESC lands in the world."""
    for attempt in range(3):
        if attempt == 1:
            task.send_key('esc', after_sleep=1.5)
        elif attempt == 2:
            task.openF2Book('gray_book_quest')
            task.click(0.17, 0.12, after_sleep=1)
        gray = _gray(task)
        boxes = task.ocr(0.2, 0.75, 1.0, 1.0, match=re.compile(r'^(20|40|60|80|100)$'))
        labels = tier_labels(boxes, gray.shape[0] if gray is not None else 1080)
        step = tier_step(labels)
        if gray is not None and step and len(labels) >= 3:
            return labels, step, gray
    return None


def _read_points(task):
    """The big points number, read the way upstream's get_total_daily_points does
    (number_re = (\\d+), non-digits stripped), or None when there is none."""
    boxes = task.ocr(0.19, 0.8, 0.30, 0.93, match=re.compile(r'(\d+)'))
    for b in boxes or []:
        digits = re.sub(r'\D', '', str(b.name))
        if 1 <= len(digits) <= 3:
            return int(digits)
    return None


def _claim_tiers(task):
    """Click every chest the points reach, then check each one shows the claimed tick."""
    bar = _bar(task)
    if bar is None:
        _shot(task, "daily_reward_row_unread")
        task.log_info(f"{DAILY_FAILED}活跃度那一排宝箱没认出来，没法领")
        return
    points = _read_points(task)
    if points is None:
        _shot(task, "daily_reward_points_unread")
        task.log_info(f"{DAILY_FAILED}活跃度的分数没读到，没法领")
        return
    task.log_info(f"{DAILY_POINTS_LINE}{points}")
    due = [t for t in DAILY_TIERS if t <= points]
    labels, step, gray = bar
    scores = tier_scores(gray, labels, step)
    for _round in range(2):
        todo = [t for t in due if t in labels and scores.get(t, -1) < _CHECKED_MIN]
        if not todo:
            break
        for t in todo:
            cx, cy = chest_at(labels, step, t)
            task.log_info(f"活跃奖励：点 {t} 档宝箱（{cx:.0f},{cy:.0f}）")
            task.click_relative(cx / gray.shape[1], cy / gray.shape[0], after_sleep=2)
            again = _bar(task)
            if again is None:
                break
            labels, step, gray = again
        scores = tier_scores(gray, labels, step)
    shown = "，".join(f"{t}:{scores.get(t, '无')}" for t in DAILY_TIERS)
    missing = [t for t in due if scores.get(t, -1) < _CHECKED_MIN]
    if missing:
        _shot(task, "daily_reward_unclaimed")
        task.log_info(f"{DAILY_FAILED}{'、'.join(map(str, missing))} 档点了没领到（活跃度 {points}，各档对勾分 {shown}）")
    else:
        task.log_info(f"{DAILY_OK}（活跃度 {points}，已领 {'、'.join(map(str, due)) or '无'}，各档对勾分 {shown}）")


def _claim_daily_checked(task):
    """Upstream claim_daily (sha _CLAIM_DAILY_SHA) up to its one blind click, then _claim_tiers."""
    task.info_set('current task', 'claim daily')
    task.openF2Book('gray_book_quest')
    if not task.find_one('boss_proceed', box=task.box_of_screen(0.803, 0.189, 0.960, 0.312)):
        task.log_info('no_boss_proceed, click claim')
        task.click(0.885, 0.250, after_sleep=2)
    try:
        _claim_tiers(task)
    finally:
        task.ensure_main(time_out=10)


# ---------------------------------------------------------------------------
# Battle pass (先约电台, Pioneer Podcast) (2026-10-11). Upstream's claim_battle_pass
# (DailyTask.py, sha _BATTLE_PASS_SHA: v3.7.4 on the machine and upstream master, both
# read 10-11; fixture tests/fixtures/okww-DailyTask-v3.7.4.py.txt) presses Alt, clicks
# the podcast icon at the top right, and waits 10 s for a number in the level box.
# No number: one ERROR line, 「can not battle pass, maybe ended」, no screenshot, no
# second try, and the run carries on to 「Daily Task Completed」, which the relay read
# as a clean run. That happened twice in the AUTO-MAS history (2026-08-14 .. 10-11,
# read on the machine on 10-11): 08-26 21:13 (the game was off the world screen; the
# ensure_main after it timed out) and 09-29 09:28 (back in the world 3 s later; why
# the page showed no number is not known - nothing was kept). 「maybe ended」 was not
# it on 09-29: version 3.6, and with it the podcast period, ran to 2026-09-30 03:59
# (3.7 maintenance 09-30 04:00-11:00 UTC+8, official 3.7 notice; period end per the
# community wiki). A period ends at 03:59 before a maintenance that already stops
# the morning run, so 「ended」 should not be met in a run at all. That day's podcast
# points went unclaimed and nobody heard (BOARD 未进群报错-OKWW-AUTOMAS-1010.md).
# What is wanted (the user, 10-11 17:36): the daily podcast points not lost.
#
# Now: a miss is photographed with the whole screen's text in the log, the game goes
# back to the world, and the page is opened once more in the same run. A second miss
# logs BATTLE_PASS_FAILED (and upstream's own ERROR sentence, which the relay's
# translation table already knows); the relay makes it an item undone
# (outcome.battle_pass_checks). Once open, upstream's clicks run unchanged; whether
# they claimed is not checked - there is no picture of a claimed page to check against
# yet, so the line says 「点了领取」, not 「领到了」.
# ---------------------------------------------------------------------------
_BATTLE_PASS_SHA = "e9e8d67cb3bc"       # upstream claim_battle_pass as copied in _claim_battle_pass_checked
BATTLE_PASS_LEVEL_BOX = (0.2, 0.13, 0.32, 0.22)
BATTLE_PASS_OK = "战令：页面打开了，点了领取（等级 "
BATTLE_PASS_RETRY = "战令：第一次没打开，回大世界再开一次"
BATTLE_PASS_FAILED = "战令没领到："
BATTLE_PASS_UNCHECKED = "战令：没有重试，"


def _battle_pass_open(task):
    """Upstream's open: Alt + click on the podcast icon, then up to 10 s for a level number.
    Returns the number read, or None."""
    task.send_key_down('alt')
    task.sleep(0.05)
    task.click_relative(0.86, 0.05)
    task.send_key_up('alt')
    boxes = task.wait_ocr(*BATTLE_PASS_LEVEL_BOX, match=re.compile(r'\d+'), settle_time=1,
                          raise_if_not_found=False)
    if not boxes:
        return None
    first = boxes[0] if isinstance(boxes, (list, tuple)) else boxes
    return str(getattr(first, "name", first)).strip() or "?"


def _claim_battle_pass_checked(task):
    """Upstream claim_battle_pass (sha _BATTLE_PASS_SHA), with one more try at opening the page."""
    task.log_info('battle pass')
    level = _battle_pass_open(task)
    if level is None:
        _shot(task, "battle_pass_unopened_1")
        task.log_info(f"{BATTLE_PASS_RETRY}。整屏读到 {_screen_text(task)[:400]}")
        task.ensure_main()
        level = _battle_pass_open(task)
        if level is None:
            _shot(task, "battle_pass_unopened_2")
            seen = _screen_text(task)[:400]
            task.log_error('can not battle pass, maybe ended')
            task.log_info(f"{BATTLE_PASS_FAILED}战令页开了两次都没读到等级数字"
                          f"（这期战令已经结束，或者页面没打开；截图 battle_pass_unopened_1/2）。整屏读到 {seen}")
            task.ensure_main()
            return
        retried = "（第二次打开的）"
    else:
        retried = ""
    task.click_relative(0.04, 0.3, after_sleep=1)
    task.click_relative(0.68, 0.91, hcenter=True, after_sleep=3)
    task.click_relative(0.04, 0.17, after_sleep=2)
    task.click_relative(0.68, 0.91, hcenter=True, after_sleep=2)
    task.wait_ocr(*BATTLE_PASS_LEVEL_BOX, match=re.compile(r'\d+'),
                  post_action=lambda: task.click(0.68, 0.91, after_sleep=1), settle_time=1,
                  raise_if_not_found=False)
    task.log_info(f"{BATTLE_PASS_OK}{level}）{retried}")
    task.ensure_main()


def _install_battle_pass():
    from src.task.DailyTask import DailyTask

    claim = DailyTask.claim_battle_pass
    sha = _src_sha(claim)
    if sha != _BATTLE_PASS_SHA:
        _skipped.append({"what": "DailyTask.claim_battle_pass（战令没打开时再开一次）",
                         "why": f"上游正文变了（现在 {sha or '读不到'}，我们照着 {_BATTLE_PASS_SHA} 抄的）"})

    @override(DailyTask, "claim_battle_pass")
    def claim_battle_pass(self):
        if sha == _BATTLE_PASS_SHA:
            return _claim_battle_pass_checked(self)
        self.log_info(f"{BATTLE_PASS_UNCHECKED}上游领战令的正文变了（现在 {sha or '读不到'}，"
                      f"我们照着 {_BATTLE_PASS_SHA} 抄的），照上游领")
        return claim(self)


def _install_hooks():
    global logger, TaskDisabledException, CharRevivedException, _ArkStop
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
    _ArkStop = type("ArkStop", (_TDE,), {"__doc__": "Unwinds a FarmEchoTask run that ends as failed (_end_failed)."})

    # -- 4C farm: stop retrying for ever; a stop ends the task as FAILED -----
    farm_run = FarmEchoTask.run

    @override(FarmEchoTask, "run")
    def run(self, retries=3):
        # Upstream retries by calling run() again from its own except. Up to v3.7.3
        # that had no limit (one bad night spun 50 minutes of it); v3.7.4 takes
        # run(self, retries=3) and retries with self.run(retries - 1) while
        # retries > 0 (FarmEchoTask.py:108, :122-123, upstream #1649). That call
        # lands here, so `retries` is taken and passed on: without it every retry
        # was a TypeError (10-13). The depth count below caps it without touching
        # their body; it is the tighter cap (3 bodies, upstream's would allow 4)
        # and still holds if a later upstream drops its own. Three failures in a row is a
        # failure, so it ends the task as one (_end_failed), as does every stop
        # that went through _end_failed below; the outermost call raises it once
        # upstream's run() is over, and OK-WW counts the task as failed.
        self._ark_depth = getattr(self, "_ark_depth", 0) + 1
        outer = self._ark_depth == 1
        if outer:
            self._ark_failed = None
        try:
            if self._ark_depth > _MAX_FARM_RETRIES:
                self.log_info(f"连续 {_MAX_FARM_RETRIES} 次失败，退出本次任务，不再重试")
                _end_failed(self, f"连续 {_MAX_FARM_RETRIES} 次失败，退出本次任务，不再重试")
            got = farm_run(self, retries)
        except _ArkStop:
            if not outer:
                raise
            got = None
        finally:
            self._ark_depth -= 1
        why = getattr(self, "_ark_failed", None) if outer else None
        if why:
            self._ark_failed = None
            self.log_error(f"{FAILED_MARK}{why}")
            raise ArkStopped(why)
        return got

    # -- 4C farm: a revived death is not the end of the run ------------------
    farm_combat = FarmEchoTask.combat_once

    @override(FarmEchoTask, "combat_once")
    def combat_once(self, *a, **kw):
        # A revive raises CharRevivedException. Upstream v3.7.4 catches it in
        # do_run (FarmEchoTask.py:216-229) with a fresh teleport to the boss, at
        # most 3 times per run. A revive that already put us back at the boss sets
        # is_revived - upstream's own overworld one (FarmEchoTask.py:98-106) - and
        # for that the exception stops here, so the loop takes its
        # `if self.is_revived: continue` (FarmEchoTask.py:182-183) without a
        # second trip and without the cap. A revive inside a realm does not set it
        # - BaseCombatTask.revive_action (:227-240) cancels the popup and leaves
        # the realm, for the weekly boss and the echo farm alike - and goes up
        # untouched to that re-teleport; swallowing it sent the loop looking for
        # an echo at the tower. do_run clears is_revived at the top of every lap
        # (FarmEchoTask.py:144-147), so it is False here unless this fight's
        # revive set it.
        #
        # Why not the whole lap, as the text patch did (okww_patches/revive.py:
        # 139-148)? Upstream had no handler then, and a revive anywhere in the lap
        # stopped the task. A revive can still surface outside combat_once: the
        # executor runs sleep_check every 0.4 s during any sleep (ok-script
        # TaskExecutor.py:316-333, interval CombatCheck.py:26) and
        # BaseCombatTask.sleep_check (:781-794) raises while _in_combat is set,
        # e.g. in the combat_wait sleep before combat_once (FarmEchoTask.py:174).
        # Those go to upstream's do_run handler (re-teleport, cap 3); Teleport to
        # Boss is on in both of our modes (echofarm.py writes Boss Challenge, the
        # weekly boss Weekly Challenge), which is that handler's condition. Not yet
        # seen in a log: that re-teleport starting from inside a realm after our
        # in-place revive.
        try:
            return farm_combat(self, *a, **kw)
        except CharRevivedException:
            if not getattr(self, "is_revived", False):
                raise
            self.log_info("刷声骸模式：复活成功，接着刷下一趟")
            return None

    # -- weekly boss: read the remaining count before entering --------------
    pick_level = FarmEchoTask.click_configured_boss_level

    @override(FarmEchoTask, "click_configured_boss_level")
    def click_configured_boss_level(self):
        # Weekly boss only. Upstream calls this for the echo farm too (Teleport to
        # Boss = 「Boss Challenge」, which echofarm.py writes; FarmEchoTask.py:351 via
        # :316-317 and :383-384), and a 4C boss's level page has no 「本周剩余可收取
        # 次数」: the unread-count stop below would end the farm at its first boss.
        if not _weekly(self) or farming_echoes():
            return pick_level(self)
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
            # 上限」 and the daily pushed back for nothing. The game's own counter says
            # there is nothing left to do this week, so this - and only this - ends
            # the run as OK-WW's 「skipped」; the daily report says 「进本前读到本周
            # 0/3」 (collector_okww._okww_steps). It is also how the last claim of
            # the week ends (_after_claim reads the page once more).
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

    # -- weekly boss: the 「无法获取奖励」 reminder after 单人挑战 ------------------
    solo_challenge = getattr(FarmEchoTask, "click_solo_challenge", None)

    @override(FarmEchoTask, "click_solo_challenge")
    def click_solo_challenge(self):
        # v3.7.4 clicks 单人挑战 and, within 1 s, confirms any dialog and ticks
        # 「本次登录不再提示」 (FarmEchoTask.py:374-378, BaseWWTask.py:1069-1113). Its
        # comment: when waveplates (backup included) are short, 「无法获取奖励，是否继续
        # 进入」 comes up before the team screen. For the echo farm that is right (no
        # reward wanted) and stays upstream's. For the weekly boss it confirmed a
        # fight for no reward (10-12 11:43:16, ok-script.2026-10-12.log:1864-1870;
        # 15:28:19, :2735-2740), and the tick hid the reminder for the rest of that
        # login (:2877). Here: the same click; a dialog is read before anything is
        # pressed. The reminder with waveplates + backup under one claim is a
        # shortage: 取消, skipped. With enough, 确认 without the tick (the reward is
        # paid at the crystal; the claim hook reads the bar again there). Any other
        # dialog, or a bar that cannot be read, is a picture and a stop.
        if not _weekly(self) or farming_echoes():
            return solo_challenge(self)
        self.click(0.880, 0.911, after_sleep=2)
        up = self.wait_until(lambda: self.find_one(_CONFIRM_BTNS, horizontal_variance=0.1,
                                                   vertical_variance=0.1),
                             time_out=_SOLO_DIALOG_WAIT, raise_if_not_found=False)
        if not up:
            return None
        found, text = _screen_read(self)
        if "结晶波片不足" not in text and "无法获取奖励" not in text:
            _stop(self, "solo_dialog_unknown",
                  f"周本：点单人挑战后弹出认不出的对话框，不点确认，停下。整屏读到 {text[:600]}")
        wave, spare = _waveplates(self, found)
        if wave is None or spare is None:
            _stop(self, "solo_dialog_bar_unread",
                  f"周本：点单人挑战后弹出「无法获取奖励」，顶栏的波片没读全（波片 {wave}，备用 {spare}），"
                  f"不点确认，停下。整屏读到 {text[:400]}")
        self.log_info(f"周本：点单人挑战后弹出「无法获取奖励」，顶栏读到波片 {wave}/240，备用 {spare}")
        if wave + spare < _CLAIM_COST:
            # Logged before the click, which can raise: the relay reads this line as a
            # shortage (outcome.WEEKLY_SHORT), an item undone, not an error.
            self.log_info(f"结晶波片不足，取消并跳过本次周本（单人挑战后的提醒框：波片 {wave} + 备用 {spare}，"
                          f"不够领一次的 {_CLAIM_COST}）")
            _shot(self, "nowave_dialog")
            self.click_dialog_left_button()
            self.sleep(1)
            _skip_short(self)
        self.log_info(f"周本：波片 {wave} + 备用 {spare} 够领一次，提醒框点确认（不勾「本次登录不再提示」）")
        self.click_dialog_right_button()
        return None

    # -- every boss entry: 单人挑战 taken, then 开启挑战; an unknown dialog stops --
    @override(FarmEchoTask, "click_team_challenge", expect_sha=_TEAM_CHALLENGE_SHA)
    def click_team_challenge(self):
        # Upstream clicks the challenge button and confirms whatever dialog follows
        # in one go. Split in two so a dialog is read before anything is confirmed.
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
            try:
                self.screenshot("no_start_btn")
                self.log_info(f"找不到开启挑战，整屏读到: {seen}")
            except Exception:
                pass
            raise
        # Nothing is confirmed after 开启挑战. Under v3.7.4 the 「无法获取奖励」 reminder
        # comes after 单人挑战, before the team screen (click_solo_challenge above);
        # every 「开启挑战后读到」 line on the machine since 10-06 is []. A dialog
        # that is up here (upstream's own confirm-button template, the one its
        # wait_click_skip_dialog_confirm looks for) is unknown: picture, report,
        # stop. Reaching the arena, or the whole window with no dialog, means there
        # is nothing to answer.
        dialog = None
        for n in range(_CHALLENGE_LOOKS):
            if n:
                self.sleep(1)
            after = self.ocr(box=self.box_of_screen(0.20, 0.35, 0.80, 0.60)) or []
            if after or not n:
                self.log_info(f"开启挑战后读到（第 {n + 1} 次）: {after}")
            dialog = self.find_one(_CONFIRM_BTNS, horizontal_variance=0.1, vertical_variance=0.1)
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
    # Whether one of the three farm_* methods was called during this daily run.
    # Set by _farm_hook's wrapper (it runs on the farm task, not on DailyTask, so
    # the flag lives here), read by claim_daily below.
    farm_called = {"ran": False}
    daily_run = DailyTask.run

    @override(DailyTask, "run")
    def daily(self):
        # One flag per run. Without resetting it here the second daily of a boot
        # would skip its additional tasks entirely.
        self._ark_additional_ran = False
        farm_called["ran"] = False
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
            except TaskDisabledException:
                # OK-WW's stop / skip signal (the task disabled, a stop from AUTO-MAS):
                # it ends the daily, as it does everywhere upstream
                # (DailyTask.check_weekly_garden / check_discarded_echo re-raise it).
                # Our own weekly stops never get here: FarmEchoTask.run turns them
                # into ArkStopped or a plain return.
                raise
            except Exception as exc:  # noqa: BLE001
                self.log_error(f"附加任务出错，不拖垮当趟日常: {exc}", exception=exc)
                try:
                    self.screenshot("additional_tasks_error")
                except Exception:
                    pass
        got = open_daily(self)
        # (used_stamina, daily_reward_ready) as upstream read them after the weekly
        # boss; claim_daily's log line quotes them.
        self._ark_daily_read = got
        return got

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
                # Counted as called: the farm was reached and said why it did not run.
                # Left unset, claim_daily_after_farm took it for 「upstream did not farm」,
                # logged 「按刷到空…」 and called the farm a second time.
                farm_called["ran"] = True
                self.log_info("刷体力已禁用（标记文件在），这一趟不花波片")
                return None
            farm_called["ran"] = True
            # daily=False means must_use=0: farm until there is not enough stamina
            # to enter, not just up to upstream's daily 180. That only covers the
            # days upstream calls the farm at all; the days its gate skips it are
            # claim_daily's below.
            kw.pop("daily", None)
            kw.pop("used_stamina", None)
            return original(self, *a, **kw)

        override(cls, name)(hooked)

    _farm_hook(TacetTask, "farm_tacet")
    _farm_hook(ForgeryTask, "farm_forgery")
    _farm_hook(SimulationTask, "farm_simulation")

    # -- daily: farm to empty even when upstream's gate says not to ----------
    claim_daily = DailyTask.claim_daily
    claim_sha = _src_sha(claim_daily)
    if claim_sha != _CLAIM_DAILY_SHA:
        _skipped.append({"what": "DailyTask.claim_daily（活跃奖励逐档领、领完核对）",
                         "why": f"上游正文变了（现在 {claim_sha or '读不到'}，我们照着 {_CLAIM_DAILY_SHA} 抄的）"})

    @override(DailyTask, "claim_daily")
    def claim_daily_after_farm(self):
        # Upstream v3.7.3 farms only when `not daily_reward_ready and used_stamina
        # < 180` (DailyTask.py:88-89, read by open_daily). With the additional tasks
        # moved into open_daily, that read comes after the weekly boss: three chests
        # spend exactly 180, the gate closes, and every waveplate above 180 sits
        # unused. Same when the daily points are already at 100. The standing order
        # is to farm to empty, which the copy before d035709a did unconditionally
        # (re-read, then farm; tests/replay/2026-09-07/wuwa/OK-WW-07-27-50.log:410-420
        # read 180/180 and still farmed 75 + 26). claim_daily is the first call
        # after upstream's farm block (DailyTask.py:118-130), so the farm upstream
        # skipped runs here, in the same place and before 「Daily Task Completed」,
        # which the relay reads as the end of the run.
        if not farm_called["ran"]:
            used, ready = getattr(self, "_ark_daily_read", None) or ("?", "?")
            self.log_info(f"上游这趟不刷体力（已用 {used}/180，活跃度满 {ready}），"
                          f"按「刷到空」把剩下的体力刷掉")
            try:
                target = self.config.get('Which to Farm', self.support_tasks[0])
                if target == self.support_tasks[0]:
                    self.get_task_by_class(TacetTask).farm_tacet(config=self.config)
                elif target == self.support_tasks[1]:
                    self.get_task_by_class(ForgeryTask).farm_forgery(config=self.config)
                else:
                    self.get_task_by_class(SimulationTask).farm_simulation(config=self.config)
                self.sleep(4)
            except TaskDisabledException:
                raise
            except Exception as exc:  # noqa: BLE001 - upstream would have claimed without it
                self.log_error(f"补刷体力出错，照常领日常奖励: {exc}", exception=exc)
                try:
                    self.screenshot("leftover_farm_error")
                    self.ensure_main(time_out=180)
                except Exception:
                    pass
        # Every chest up to the points, checked (_claim_daily_checked); upstream's own
        # claim when its body is no longer the one we copied, said in the log for the relay.
        if claim_sha == _CLAIM_DAILY_SHA:
            return _claim_daily_checked(self)
        self.log_info(f"{DAILY_UNCHECKED}上游领奖正文变了（现在 {claim_sha or '读不到'}，我们照着 {_CLAIM_DAILY_SHA} 抄的），照上游点 100 档")
        return claim_daily(self)


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
# The two nest sentences the relay's log reader keys on (collector_okww, outcome).
NEST_COUNT_UNREAD = "指定点位的名字读到了，计数没读到"
NEST_ADAPTED = "只刷指定点位的过滤是按 OK-WW 新版适配装上的"
_NEST_TOP_RE = re.compile(r"self\.ocr\(\s*0\.35\s*,\s*(0?\.\d+)\s*,\s*1\s*,\s*0\.96")


def _upstream_nest_top(fn) -> "float | None":
    """The top of upstream's nest-list OCR box, read from its own find_nest; None when unreadable.

    Following upstream here is what keeps our copy current when they move the box
    again: 10-03 they moved it from 0.13 to 0.25. There is no fallback value: a guessed
    top reads the wrong rows, and that is how 10-03 clicked an unreachable 0/48 nest
    without a word. None keeps find_nest out (refuse), which the report says.
    """
    try:
        m = _NEST_TOP_RE.search(inspect.getsource(fn))
    except (OSError, TypeError):
        return None
    try:
        top = float(m.group(1)) if m else None
    except ValueError:
        return None
    return top if top is not None and 0.0 < top < 0.6 else None


def _install_nest():
    from src.task.NightmareNestTask import NestTarget, NightmareNestTask

    top = _upstream_nest_top(getattr(NightmareNestTask, "find_nest", None))
    # Reported through the overlay's skipped list (relay: okww_overlay.report_line, pushed
    # to the group at boot); nest_entry then skips the nests for the run, as for any
    # find_nest that did not bind.
    top_unread = "" if top is not None else (
        "上游 find_nest 里读不到点位列表识字区的上沿（写法变了，或读到的值不在 0 到 0.6 之间），"
        "不拿猜的值去点，这一轮不刷巢穴")

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
    @refuse(top_unread)
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
                # The list itself is the proof of 「full」 (10-12 11:48:10 left only the log line).
                _shot(self, "nest_all_full")
                self.log_info("nightmare nest: 指定点位都已打满，跳过（截图 nest_all_full）")
            else:
                self.log_info("nightmare nest: 指定点位没有可用的计数，跳过")
        return None

    next_nest = NightmareNestTask.get_nest_to_go

    @override(NightmareNestTask, "get_nest_to_go")
    def get_nest_to_go(self):
        # Close the map left open by 「nightmare nest unreachable」 before the book is
        # opened again. Upstream's _travel_to_nest_or_skip (NightmareNestTask.py:163-180)
        # ends with a single back(), which can leave the map open; openF2Book then
        # finds no book and the task dies with 「can't find gray_book_boss」 (10-05
        # 10:35:22). openF2Book's own ensure_main (BaseWWTask.py:1019) would close it,
        # but inside the daily that ensure_main is a do-nothing lambda on purpose
        # (DailyTask.py:98-99, so the nest run keeps the book open), so it cannot.
        # One more back, only when the world is not already on screen (a back in the
        # world opens the game menu), then a short wait for the world.
        if getattr(self, "_ark_close_map", False):
            self._ark_close_map = False
            if not self.in_team_and_world():
                self.back(after_sleep=1)
                if not self.wait_until(self.in_team_and_world, time_out=5, raise_if_not_found=False):
                    _shot(self, "nest_map_still_open")
                    self.log_info("nightmare nest: 传送不过去之后关了一次地图，还是没回到大世界"
                                  f"（截图 nest_map_still_open）。整屏读到 {_screen_text(self)[:300]}")
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
            self._ark_close_map = True     # get_nest_to_go closes the map before the book
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
        self._ark_close_map = False
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
    _install_teleport()
    _install_nest()
    _install_claim()
    _install_tacet_groups()
    _install_battle_pass()
except Exception:  # noqa: BLE001 - never stop OK-WW from starting
    _write_report(traceback.format_exc()[-800:])
else:
    _write_report()
