"""The harness's two scripted pieces the echo-farm cases rely on (harness.py: provisional features, the fight).

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows), in the real
ok-script framework with the overlay loaded:

  - a declared feature is what find_one finds, only inside the caller's search box; on a black
    (frameless) screen an undeclared name finds nothing, on a recorded frame it goes to the real
    matcher (gray_teleport on the 10-07 map, where the machine clicked it: ok-script.2026-10-07.log:249);
  - the fight: combat_once on a screen with no fight fails the case; `returns` returns and moves on;
    `revived` sets is_revived and raises upstream's CharRevivedException, which the overlay's
    combat_once swallows; `realm_revive` raises it without is_revived and the overlay lets it go;
    in_combat() is true exactly on a state with a fight;
  - the faked upstream bodies are the pinned ones, a changed pin refuses to fake, and the
    overlay's closure gets upstream's combat_once back after the case.
"""
import json
import sys
import unittest
from pathlib import Path

_CTX = Path("ark_gamesim.json")
if not _CTX.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; no {_CTX}")
_HERE = json.loads(_CTX.read_text(encoding="utf-8"))["gamesim_okww"]
sys.path.insert(0, _HERE)
try:
    import harness
    import scenario as scn
except ImportError as exc:
    raise SystemExit(f"cannot import the harness from {_HERE}: {exc}") from None
from src.task.BaseCombatTask import BaseCombatTask, CharRevivedException  # noqa: E402
from src.task.FarmEchoTask import FarmEchoTask  # noqa: E402

EV = "harness self-test input"
MAP = "map_nest_detail/2026-10-07_092055.png"
BOOK = [0.0224, 0.262, 0.0563, 0.3315]       # gray_book_boss as logged: Box(x=43, y=283, width=65, height=75)


def scenario(states, start, **expect):
    full = {"sequence": [], "end": None, "never_states": [], "shots": [], "raises": None,
            "log": [], "log_never": [], "verdict": None}
    full.update(expect)
    return scn.load_dict({"case": "self", "task": ["src.task.FarmEchoTask", "FarmEchoTask"],
                          "start": start, "states": states, "expect": full}, source="test_harness_fight")


def overlay_cells():
    fn = FarmEchoTask.__dict__.get("combat_once")
    return [c.cell_contents for c in (getattr(fn, "__closure__", None) or ())]


class TestHarnessFight(harness.ScriptedCase):
    task_class = FarmEchoTask

    # -- provisional features
    def test_declared_feature_inside_the_search_box_only(self):
        sc = scenario({"book": {"features": [{"name": "gray_book_boss", "box": BOOK, "evidence": EV}],
                                "ignore_inputs": True}}, "book")
        got = {}

        def body(task):
            got["any"] = task.find_one("gray_book_boss")
            got["in_box"] = task.find_one("gray_book_boss", box=task.box_of_screen(0.0, 0.2, 0.1, 0.4))
            got["out_box"] = task.find_one("gray_book_boss", box=task.box_of_screen(0.5, 0.5, 1.0, 1.0))
            got["undeclared"] = task.find_one("team_start_challenge")
            got["list"] = task.find_one(["team_close", "gray_book_boss"])
        run = self.run_scenario(sc, body)
        self.assertIsNone(run.raised, run.trace)
        self.assertEqual((got["any"].x, got["any"].y, got["any"].width, got["any"].height), (43, 283, 65, 75))
        self.assertIsNotNone(got["in_box"])
        self.assertIsNone(got["out_box"])
        self.assertIsNone(got["undeclared"], "a black screen shows no template")
        self.assertEqual(got["list"].name, "gray_book_boss")

    def test_recorded_frame_keeps_the_real_matcher(self):
        sc = scenario({"map": {"frame": MAP, "features": [{"name": "team_close", "box": [0.92, 0.02, 0.96, 0.09],
                                                           "evidence": EV}], "ignore_inputs": True}}, "map")
        got = {}

        def body(task):
            got["teleport"] = task.find_one("gray_teleport", threshold=0.7)
            got["team_close"] = task.find_one("team_close")
        run = self.run_scenario(sc, body)
        self.assertIsNone(run.raised, run.trace)
        t = got["teleport"]
        self.assertIsNotNone(t, "the real matcher still finds gray_teleport on the recorded map")
        self.assertTrue(t.x <= 1351 <= t.x + t.width and t.y <= 1007 <= t.y + t.height, t)
        self.assertIsNotNone(got["team_close"])

    # -- the fight
    def fight_states(self, outcome):
        return {"boss": {"features": [{"name": "char_2_text", "box": [0.9052, 0.3194, 0.913, 0.3361], "evidence": EV}],
                         "fight": {"outcome": outcome, "to": "after", "evidence": EV}},
                "after": {"features": [{"name": "char_2_text", "box": [0.9052, 0.3194, 0.913, 0.3361], "evidence": EV}],
                          "ignore_inputs": True}}

    def test_fight_returns(self):
        got = {}

        def body(task):
            got["before"] = task.in_combat()
            got["result"] = task.combat_once()
            got["after"] = task.in_combat(target=True)
        run = self.run_scenario(scenario(self.fight_states("returns"), "boss"), body)
        self.assertIsNone(run.raised, run.trace)
        self.assertEqual((got["before"], got["result"], got["after"]), (True, True, False))
        self.assertEqual(run.states, ["boss", "after"])
        self.assertEqual([e.data["outcome"] for e in run.of("fight")], ["returns"])

    def test_fight_revived_is_swallowed_by_the_overlay(self):
        def body(task):
            task.is_revived = False
            task.combat_once()
        run = self.run_scenario(scenario(self.fight_states("revived"), "boss"), body)
        self.assertIsNone(run.raised, run.trace)
        self.assertTrue(self.task.is_revived)
        self.assertTrue(any("刷声骸模式：复活成功" in line for line in run.log), run.log[-5:])

    def test_fight_realm_revive_goes_up(self):
        def body(task):
            task.is_revived = False
            task.combat_once()
        run = self.run_scenario(scenario(self.fight_states("realm_revive"), "boss"), body)
        self.assertIsInstance(run.raised, CharRevivedException)
        self.assertFalse(self.task.is_revived)
        self.assertEqual(run.state, "after")

    def test_fight_on_a_screen_without_one_fails(self):
        sc = scenario({"boss": {"features": [{"name": "char_2_text", "box": [0.9052, 0.3194, 0.913, 0.3361],
                                              "evidence": EV}],
                                "fight": {"outcome": "returns", "to": "after", "evidence": EV}},
                       "after": {"features": [{"name": "char_2_text", "box": [0.9052, 0.3194, 0.913, 0.3361],
                                               "evidence": EV}]}}, "boss")

        def body(task):
            task.combat_once()
            task.combat_once()
        run = self.run_scenario(sc, body)
        self.assertEqual(len(run.off_script), 1, run.off_script)
        self.assertIn("no fight", run.off_script[0])

    # -- pins and restore
    def test_pins_and_restore(self):
        up = BaseCombatTask.combat_once
        self.assertIn(up, overlay_cells(), "the overlay's combat_once holds upstream's in its closure")
        for (cls, name), sha in harness.FAKED.items():
            with self.subTest(f"{cls}.{name}"):
                mod = __import__("src.combat.CombatCheck" if cls == "CombatCheck" else "src.task.BaseCombatTask",
                                 fromlist=[cls])
                self.assertEqual(harness._src_sha(getattr(getattr(mod, cls), name)), sha)
        run = self.run_scenario(scenario(self.fight_states("returns"), "boss"), lambda task: task.combat_once())
        self.assertIsNone(run.raised, run.trace)
        self.assertIn(up, overlay_cells(), "upstream's combat_once is back in the closure after the case")
        self.assertNotIn("in_combat", self.task.__dict__)
        saved = dict(harness.FAKED)
        try:
            harness.FAKED[("BaseCombatTask", "combat_once")] = "000000000000"
            with self.assertRaises(AssertionError) as caught:
                self.run_scenario(scenario(self.fight_states("returns"), "boss"), lambda task: task.combat_once())
            self.assertIn("re-read the new body", str(caught.exception))
        finally:
            harness.FAKED.clear()
            harness.FAKED.update(saved)
        self.assertIn(up, overlay_cells())


if __name__ == "__main__":
    unittest.main()
