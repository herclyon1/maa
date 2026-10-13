"""Echo farm (FarmEchoTask with Teleport to Boss = Boss Challenge, as the relay's echo farm runs it):
OK-WW's own task with our overlay, through the scenarios in scenarios/echofarm/ (gamesim design 1,
"Echo farm"; cases T4 and T5 of design 5).

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows). Every body is
the task's own entry point, `task.run()` - the overlay's FarmEchoTask.run, upstream's run, do_run -
so what is tested is the real control flow; the screens come from the scenario (recorded frames,
upstream's own recorded test images, or what the game PC's log says was on screen), and the fight
is scripted at the function the overlay wraps (harness.py, "the fight"). Expected values come from
the scenario files, each with its evidence, never from this code.

  main_book_team_1013          the 10-13 11:54-11:57 run: book -> team screen -> fight -> echo -> lap 2
  level_page_book_lv80         35d6166b: a book entry that opens the level page picks Lv.80 (constructed)
  revive_is_revived_continues  a revive that sets is_revived goes on in place (constructed)
  realm_revive_reteleports     a realm revive without it goes up to do_run's re-teleport (constructed)
  three_failures_arkstopped    three failed bodies -> ArkStopped (constructed)
  retry_passes_retries         upstream's run(retries - 1) lands on ours and works (constructed)

Red before green (design rule 1): each fix has a red and a green lane in ci_prepare.LANES, at the
OK-WW the game PC ran then (v3.7.3 until 10-06, v3.7.4 after). A lane runs only its cases (LANES
below). In a red lane a case must fail at an assertion, and for the reason it names: a case that
passes, or fails for another reason, is an error, which ci_prepare's red lane does not accept.
"""
import json
import sys
import unittest
from pathlib import Path

_CTX = Path("ark_gamesim.json")
if not _CTX.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; no {_CTX}")
CTX = json.loads(_CTX.read_text(encoding="utf-8"))
sys.path.insert(0, CTX["gamesim_okww"])
try:
    from harness import ScriptedCase
except ImportError as exc:
    raise SystemExit(f"cannot import the harness from {CTX['gamesim_okww']}: {exc}") from None
from src.task.FarmEchoTask import FarmEchoTask  # noqa: E402

ALL = ("main_book_team_1013", "level_page_book_lv80", "revive_is_revived_continues",
       "realm_revive_reteleports", "three_failures_arkstopped", "retry_passes_retries")

# lane -> {case: None (must pass) | the text its failure must contain (red)}. A lane not named
# here runs nothing from this file (the p1 / p2 lanes are other tests').
LANES = {
    "installed": {c: None for c in ALL},
    # 35d6166b (10-13, OK-WW v3.7.4): the level on a Boss Challenge book entry.
    "u7-red-35d6166b": {
        "main_book_team_1013": "no log line matches '刷声骸选等级：前往后是队伍界面",
        "level_page_book_lv80": "off script: level_page: click",
    },
    "u7-green-35d6166b": {"main_book_team_1013": None, "level_page_book_lv80": None},
    # b24c48fc (10-13, v3.7.4): run takes and passes on upstream's retries.
    "u7-red-b24c48fc": {"retry_passes_retries": "the task raised TypeError"},
    "u7-green-b24c48fc": {"retry_passes_retries": None},
    # 034a555d (10-06, v3.7.3): swallow a revive that put us back at the boss.
    "u7-red-034a555d": {"revive_is_revived_continues": "no log line matches '刷声骸模式：复活成功"},
    "u7-green-034a555d": {"revive_is_revived_continues": None},
    # 86bc0960 (10-06, v3.7.3): a realm revive goes up to upstream's re-teleport.
    "u7-red-86bc0960": {"realm_revive_reteleports": "off script: healed:"},
    "u7-green-86bc0960": {"realm_revive_reteleports": None},
    # 7b1099a1 (10-06, v3.7.3): three failures end the task as failed, not skipped.
    "u7-red-7b1099a1": {"three_failures_arkstopped": "expected ArkStopped"},
    "u7-green-7b1099a1": {"three_failures_arkstopped": None},
}
PLAN = LANES.get(CTX["lane"], {})


def f2_presses(run) -> int:
    return sum(1 for e in run.of("key") if str(e.data.get("key")).lower() == "f2")


class TestEchoFarm(ScriptedCase):
    task_class = FarmEchoTask

    def case(self, name, extra=None):
        """Run scenarios/echofarm/<name>.json through task.run() and judge it for this lane."""
        if name not in PLAN:
            self.skipTest(f"lane {CTX['lane']} does not run {name}")
        red = PLAN[name]
        run = self.run_scenario(f"echofarm/{name}.json", lambda task: task.run())
        print(f"{name}: provisional states {run.scenario.provisional}")
        try:
            self.check(run)
            if extra:
                extra(run)
        except AssertionError as exc:
            if red is None:
                raise
            if red not in str(exc):
                raise RuntimeError(f"{name} is red on lane {CTX['lane']} for another reason than "
                                   f"{red!r}:\n{exc}") from None
            print(f"{name}: red as expected ({red!r})")
            raise
        if red is not None:
            raise RuntimeError(f"{name} passed on red lane {CTX['lane']}; it must fail on {red!r}")

    def test_main_book_team_1013(self):
        self.case("main_book_team_1013")

    def test_level_page_book_lv80(self):
        self.case("level_page_book_lv80")

    def test_revive_is_revived_continues(self):
        self.case("revive_is_revived_continues")

    def test_realm_revive_reteleports(self):
        def no_third_trip(run):
            # One death, one re-teleport: two book trips, not a walk or a third trip.
            self.assertEqual(f2_presses(run), 2, "two book trips: the first, and FarmEchoTask.do_run :221's re-teleport")
        self.case("realm_revive_reteleports", no_third_trip)

    def test_three_failures_arkstopped(self):
        def three_bodies(run):
            # ddf68376 (2026-09-01): 「连续 3 次 farm 4c error 直接结束本次任务」 - three bodies, not four.
            self.assertEqual(f2_presses(run), 3, "three failed bodies, then the stop (ddf68376)")
        self.case("three_failures_arkstopped", three_bodies)

    def test_retry_passes_retries(self):
        self.case("retry_passes_retries")


if __name__ == "__main__":
    unittest.main()
