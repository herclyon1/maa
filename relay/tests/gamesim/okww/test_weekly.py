"""U5: the weekly boss (战歌重奏) through the real OK-WW with our overlay (gamesim design 1, Weekly and Entry screens).

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows). The task is
OK-WW's own FarmEchoTask with whatever the lane's overlay rebound on it. Each case calls the
methods upstream calls at that point, in upstream's order (FarmEchoTask.run / do_run /
teleport_to_configured_boss, v3.7.4), on the screens the scenario file scripts:

  main path   teleport_to_configured_boss_and_prepare() (book, 前往, spoiler, level page, 单人挑战,
              开启挑战), the fight elided (combat is U7's scripted state), pick_f() at the crystal
              (upstream's F -> handle_claim_button), then incr_drop() as do_run calls it next
              (the read-back and the way back in);
  claim       pick_f() at the crystal, then whatever the claim dialog leads to;
  no crystal  incr_drop() on the realm with the boss still up;
  level page  click_configured_boss_level() on 0/3;
  entry       teleport_to_configured_boss() from the open world;
  单人挑战     click_solo_challenge() on the level page, click_team_challenge() on the 09-21 page;
  T5          the whole run().

Expected values come from the scenario files, each with its evidence (a log line of the game PC,
a recorded frame, upstream's source, the owner's words) - never from the code under test. States
without a recorded frame run on the OCR text and templates their log lines show (provisional,
design 6.1); every case prints which.

Red before green (ci_prepare.py LANES, `select`): each case with a fix is run at <fix>~1 and at the
fix on the OK-WW the machine ran then (v3.7.3 for the 10-05 entry fixes, v3.7.4 otherwise).
"""
import hashlib
import inspect
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_CTX = Path("ark_gamesim.json")
if not _CTX.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; no {_CTX}")
_HERE = json.loads(_CTX.read_text(encoding="utf-8"))["gamesim_okww"]
sys.path.insert(0, _HERE)
try:
    import scenario as scn
    from harness import ScriptedCase
except ImportError as exc:
    raise SystemExit(f"cannot import the harness from {_HERE}: {exc}") from None
from src.task.FarmEchoTask import FarmEchoTask  # noqa: E402
from src.task.WWOneTimeTask import WWOneTimeTask  # noqa: E402

# The fight, elided: 15:25:55 开启挑战 -> 15:27:18 打完了 (ok-script.2026-10-12.log:2572, :2700).
FIGHT_S = 83
# The one fake (design rule 2): WWOneTimeTask.run, the prelude FarmEchoTask.run calls first
# (FarmEchoTask.py:113). It starts MouseResetTask, which a TaskTestCase does not register
# (get_task_by_class returns None), and activates a PostMessage window. Nothing of it is under
# test. Pinned by its body: sha1 of inspect.getsource, as the overlay pins (v3.7.3 and v3.7.4
# WWOneTimeTask.py:7-12 are the same bytes), so an upstream change turns the case red first.
_ONE_TIME_RUN_SHA = "74e7f46544c5"


def _one_time_prelude(task):
    """WWOneTimeTask.run without the mouse reset and the window activation (neither touches the
    game screen): its 0.5 s wait."""
    task.sleep(0.5)


def _after_fight(task):
    """What upstream leaves on the task when a weekly lap's fight is over.

    start_time: FarmEchoTask.run sets it before do_run (FarmEchoTask.py:111-112); incr_drop reads it.
    _in_realm: teleport_to_configured_boss_and_prepare sets it for a team entry
    (FarmEchoTask.py:265-266; 'teleport_to_boss prepared as realm', ok-script.2026-10-12.log:1875)."""
    task.start_time = time.time()
    task._in_realm = True


class TestWeekly(ScriptedCase):
    task_class = FarmEchoTask

    def run_case(self, name, body):
        sc = scn.load(f"weekly/{name}.json")
        print(f"\n=== {name}: provisional states {sc.provisional or 'none'}")
        return self.play(sc, body)

    # -- T2 / T3: the main path
    def test_main_path_1012(self):
        def body(task):
            task.start_time = time.time()
            task.teleport_to_configured_boss_and_prepare()
            task.sleep(FIGHT_S)
            task.pick_f()
            task.incr_drop(None)       # 'farm echo walk_find_echo None' (10-05 bundle ok-script.log:1353)
        self.run_case("main_path_1012", body)

    # -- T2: the claim dialog
    def _claim(self, name):
        def body(task):
            _after_fight(task)
            task.pick_f()
        self.run_case(name, body)

    def test_claim_short_17_24(self):
        self._claim("claim_short_17_24")

    def test_claim_short_18_0(self):
        self._claim("claim_short_18_0")

    def test_claim_bar_240_plus(self):
        self._claim("claim_bar_240_plus")

    def test_claim_bar_unread(self):
        self._claim("claim_bar_unread")

    def test_claim_topup_after_enough_read(self):
        self._claim("claim_topup_after_enough_read")

    def test_claim_no_settlement(self):
        self._claim("claim_no_settlement")

    def test_no_crystal_0952(self):
        def body(task):
            _after_fight(task)
            task.incr_drop(None)
        self.run_case("no_crystal_0952", body)

    # -- the level page
    def test_level_0of3_skip(self):
        self.run_case("level_0of3_skip", lambda task: task.click_configured_boss_level())

    # -- T4: entry screens
    def _entry(self, name):
        self.run_case(name, lambda task: task.teleport_to_configured_boss())

    def test_entry_spoiler_level_page(self):
        self._entry("entry_spoiler_level_page")

    def test_entry_spoiler_arena(self):
        self._entry("entry_spoiler_arena")

    def test_entry_open_world_stops(self):
        self._entry("entry_open_world_stops")

    def test_entry_map_stops(self):
        self._entry("entry_map_stops")

    def test_entry_no_book_screen(self):
        self._entry("entry_no_book_screen")

    def test_boss_challenge_team_page(self):
        self._entry("boss_challenge_team_page")

    def test_solo_reminder_short(self):
        self.run_case("solo_reminder_short", lambda task: task.click_solo_challenge())

    def test_solo_reminder_contradicts(self):
        self.run_case("solo_reminder_contradicts", lambda task: task.click_solo_challenge())

    def test_solo_click_not_taken_0921(self):
        self.run_case("solo_click_not_taken_0921", lambda task: task.click_team_challenge())

    # -- T5: a deliberate skip ends the run once
    def test_run_0of3_not_retried(self):
        got = hashlib.sha1(inspect.getsource(WWOneTimeTask.run).encode("utf-8")).hexdigest()[:12]
        self.assertEqual(got, _ONE_TIME_RUN_SHA, "upstream WWOneTimeTask.run changed: re-read it before faking it")
        with mock.patch.object(WWOneTimeTask, "run", _one_time_prelude):
            self.run_case("run_0of3_not_retried", lambda task: task.run())


if __name__ == "__main__":
    unittest.main()
