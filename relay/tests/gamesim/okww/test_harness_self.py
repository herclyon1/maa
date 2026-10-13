"""The harness itself (gamesim design 1, "Framework"): proves each piece does what the cases rely on.

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows), in the
real ok-script framework with the overlay loaded, on the two recorded 2026-10-07 frames:

  - an input that matches no transition fails the case (and is only recorded under ignore_inputs);
  - a transition fires on a relative rectangle, on a feature (the real find_one on the frame),
    on a key (send_key and back), and after virtual seconds (after_s);
  - the clock is virtual on the test thread only: sleeps and wait_* timeouts cost no real time,
    and another thread still reads real time;
  - the overlay's REPORT, NO_CLAIM, NO_STAMINA_FLAG and MASTER_POINTER point at per-case temp
    files while a scenario runs, and back at the machine paths afterwards;
  - screenshots are recorded by name; the window title makes game_lang zh_CN;
  - provisional_ocr states answer OCR with their logged text, inside the asked region only;
  - the loader refuses a scenario without evidence, and a frame whose UID strip is not black.

The inputs are chosen by each test, so the expected transitions follow from the scenario, not
from the code under test; where a test leans on a recorded fact it names the log line.
"""
import copy
import datetime
import json
import os
import re
import sys
import threading
import time
import unittest
from pathlib import Path

_CTX = Path("ark_gamesim.json")
if not _CTX.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; no {_CTX}")
_HERE = json.loads(_CTX.read_text(encoding="utf-8"))["gamesim_okww"]
sys.path.insert(0, _HERE)
try:
    import harness  # noqa: E402
    import scenario as scn  # noqa: E402
except ImportError as exc:
    raise SystemExit(f"cannot import the harness from {_HERE}: {exc}") from None
import numpy as np  # noqa: E402
from src.task.NightmareNestTask import NightmareNestTask  # noqa: E402

LIST = "nest_list/2026-10-07_092052.png"
MAP = "map_nest_detail/2026-10-07_092055.png"
# The 前往 button of the 落渊南丘 row on LIST; the machine clicked (1729, 500) there
# (ok-script.2026-10-07.log:245).
GO_ROW = [0.835, 0.445, 0.955, 0.495]
EV = "harness self-test input"
# Real seconds a case may take while it spends ten minutes of virtual time (600 s sleep plus
# a 120 s wait). Far below either, so a clock that slept for real cannot pass.
WALL_LIMIT_S = 20


def scenario(states, start, **expect):
    """A scenario dict through the real loader; `expect` keys fill the rest with defaults."""
    full = {"sequence": [], "end": None, "never_states": [], "shots": [], "raises": None,
            "log": [], "log_never": [], "verdict": None}
    full.update(expect)
    return scn.load_dict({"case": "self", "task": ["src.task.NightmareNestTask", "NightmareNestTask"],
                          "start": start, "states": states, "expect": full}, source="test_harness_self")


def go(to, **extra):
    return dict({"to": to, "evidence": EV}, **extra)


class TestHarness(harness.ScriptedCase):
    task_class = NightmareNestTask

    # -- inputs and transitions
    def test_unmatched_input_fails(self):
        sc = scenario({"list": {"frame": LIST, "transitions": [go("done", click=GO_ROW)]},
                       "done": {"end": True}}, "list")
        run = self.run_scenario(sc, lambda task: task.click_relative(0.1, 0.1))
        self.assertFalse(run.ended)
        self.assertEqual(len(run.off_script), 1, run.off_script)
        self.assertIn("matches no transition", run.off_script[0])
        with self.assertRaises(AssertionError):
            self.check(run)

    def test_unmatched_input_is_recorded_under_ignore_inputs(self):
        sc = scenario({"list": {"frame": LIST, "ignore_inputs": True,
                                "transitions": [go("done", click=GO_ROW)]},
                       "done": {"end": True}}, "list")
        run = self.run_scenario(sc, lambda task: task.click_relative(0.1, 0.1))
        self.assertEqual(run.off_script, [])
        self.assertEqual([(e.data["x"], e.data["y"]) for e in run.of("click")], [(192, 108)])
        self.check(run)

    def test_rectangle_transition(self):
        sc = scenario({"list": {"frame": LIST, "transitions": [go("done", click=GO_ROW)]},
                       "done": {"end": True}}, "list",
                      end="done", sequence=[{"click": [1729, 500], "within": 0, "evidence": EV},
                                            {"state": "done", "evidence": EV}])
        self.play(sc, lambda task: task.click(1729, 500))

    def test_feature_transition(self):
        """gray_teleport is on MAP: the machine clicked it at (1351, 1007) right after this
        screenshot (ok-script.2026-10-07.log:249). A click there fires the feature transition,
        a click on the map's far corner does not."""
        states = {"map": {"frame": MAP, "transitions": [go("done", feature="gray_teleport", threshold=0.7)]},
                  "done": {"end": True}}
        self.play(scenario(states, "map", end="done"), lambda task: task.click(1351, 1007))
        run = self.run_scenario(scenario(states, "map"), lambda task: task.click(100, 100))
        self.assertFalse(run.ended)
        self.assertEqual(len(run.off_script), 1, run.off_script)

    def test_key_transition(self):
        states = {"list": {"frame": LIST, "transitions": [go("done", key="esc")]}, "done": {"end": True}}
        self.play(scenario(states, "list", end="done"), lambda task: task.send_key("esc"))
        self.play(scenario(states, "list", end="done"), lambda task: task.back())
        run = self.run_scenario(scenario(states, "list"), lambda task: task.send_key("f2"))
        self.assertFalse(run.ended)
        self.assertEqual(len(run.off_script), 1, run.off_script)

    def test_after_s_transition(self):
        states = {"list": {"frame": LIST, "transitions": [go("map", after_s=30)]},
                  "map": {"frame": MAP, "transitions": [go("done", key="esc")]},
                  "done": {"end": True}}

        def body(task):
            task.sleep(10)
            self.decide("state after 10 s", self.capture.script.state.name)
            task.sleep(25)
            self.decide("state after 35 s", self.capture.script.state.name)
            task.send_key("esc")
        t0 = time.perf_counter()
        self.play(scenario(states, "list", end="done", sequence=[
            {"decision": "state after 10 s", "value": "list", "evidence": EV},
            {"state": "map", "evidence": EV},
            {"decision": "state after 35 s", "value": "map", "evidence": EV},
            {"state": "done", "evidence": EV}]), body)
        self.assertLess(time.perf_counter() - t0, WALL_LIMIT_S)

    # -- the clock
    def test_clock_is_virtual_on_the_test_thread_only(self):
        seen = {}

        def other():
            seen["other"] = time.time()
            seen["real"] = datetime.datetime.now().timestamp()     # not routed through time.time

        def body(task):
            t0 = time.time()
            task.sleep(600)
            seen["slept"] = time.time() - t0
            t1 = time.time()
            found = task.wait_until(lambda: False, time_out=120)   # ok-script's wait_condition
            seen["waited"] = time.time() - t1
            seen["found"] = found
            th = threading.Thread(target=other)
            th.start()
            th.join()
            seen["virtual_now"] = time.time()

        sc = scenario({"list": {"frame": LIST, "ignore_inputs": True}}, "list")
        w0 = time.perf_counter()
        run = self.run_scenario(sc, body)
        wall = time.perf_counter() - w0
        self.assertIsNone(run.raised, run.trace)
        self.assertGreaterEqual(seen["slept"], 600)
        self.assertGreaterEqual(seen["waited"], 120)
        self.assertIsNone(seen["found"])
        self.assertLess(wall, WALL_LIMIT_S, "the clock slept for real")
        self.assertLess(abs(seen["other"] - seen["real"]), 5, "another thread saw virtual time")
        self.assertGreater(seen["virtual_now"] - seen["real"], 600)
        self.assertIs(time.time, harness._REAL_TIME, "time.time not restored")
        self.assertIs(time.sleep, harness._REAL_SLEEP, "time.sleep not restored")

    def test_over_time_cap_stops_a_stuck_task(self):
        d = {"case": "self", "task": ["src.task.NightmareNestTask", "NightmareNestTask"], "start": "list",
             "max_s": 50, "states": {"list": {"frame": LIST, "ignore_inputs": True}}, "expect": {}}
        run = self.run_scenario(scn.load_dict(d), lambda task: task.wait_until(lambda: False, time_out=3600))
        self.assertTrue(run.over_time)
        with self.assertRaises(AssertionError):
            self.check(run)

    # -- environment
    def test_overlay_paths_go_to_temp_files(self):
        mod = self.overlay
        before = {n: getattr(mod, n) for n in harness.REDIRECTS}
        real_report = Path(before["REPORT"])
        report_mtime = real_report.stat().st_mtime if real_report.is_file() else None
        seen = {}

        def body(task):
            for name in harness.REDIRECTS:
                seen[name] = Path(getattr(mod, name))
            seen["no_claim"] = mod.farming_echoes()           # AO reads NO_CLAIM at call time
            seen["stamina_flag"] = os.path.exists(mod.NO_STAMINA_FLAG)
            seen["pointer"] = Path(mod.MASTER_POINTER).read_text(encoding="utf-8")
            mod._write_report("gamesim probe")              # AO's own writer, to REPORT
            seen["report"] = json.loads(Path(mod.REPORT).read_text(encoding="utf-8"))

        d = {"case": "self", "task": ["src.task.NightmareNestTask", "NightmareNestTask"], "start": "list",
             "config": {"evidence": EV, "flags": {"no_claim": True, "no_stamina": True},
                        "master": {"NightmareNestTask.json": {"Only Farm These Nests": "x"}}},
             "states": {"list": {"frame": LIST, "ignore_inputs": True}}, "expect": {}}
        run = self.run_scenario(scn.load_dict(d), body)
        self.assertIsNone(run.raised, run.trace)
        for name in harness.REDIRECTS:
            self.assertEqual(seen[name].parent if name != "NO_STAMINA_FLAG" else seen[name].parent.parent,
                             run.temp, f"{name} is not under the case's temp folder: {seen[name]}")
        self.assertTrue(seen["no_claim"])
        self.assertTrue(seen["stamina_flag"])
        self.assertEqual(json.loads((Path(seen["pointer"]) / "NightmareNestTask.json").read_text(encoding="utf-8")),
                         {"Only Farm These Nests": "x"})
        self.assertEqual(seen["report"]["error"], "gamesim probe")
        self.assertEqual({n: getattr(mod, n) for n in harness.REDIRECTS}, before, "paths not restored")
        if report_mtime is not None:
            self.assertEqual(real_report.stat().st_mtime, report_mtime, "the machine-path report was written")
        # And without flags nothing is there: NO_CLAIM absent reads as not farming.
        run = self.run_scenario(scenario({"list": {"frame": LIST, "ignore_inputs": True}}, "list"),
                                lambda task: self.decide("no_claim", mod.farming_echoes()))
        self.assertEqual([e.data["value"] for e in run.of("decision")], [False])

    def test_screenshots_and_window_title(self):
        def body(task):
            self.overlay._shot(task, "gamesim_probe")     # how the overlay takes its pictures
            self.decide("game_lang", task.game_lang)
        self.play(scenario({"list": {"frame": LIST, "ignore_inputs": True}}, "list",
                           shots=[{"name": "gamesim_probe", "evidence": EV}],
                           sequence=[{"decision": "game_lang", "value": "zh_CN",
                                      "evidence": "the PC's window title '鸣潮  ' (ok-script.2026-10-07.log:170); "
                                                  "BaseWWTask.game_lang maps 鸣潮 to zh_CN"}]), body)

    def test_provisional_ocr(self):
        count = "已击败残象：0/41"
        sc = scenario({"list": {"provisional_ocr": [
            {"text": count, "box": [0.4635, 0.488, 0.565, 0.517],
             "evidence": "ok-script.2026-10-07.log:243 Box(name='已击败残象：0/41', x=890, y=527, width=195, height=31)"},
            {"text": "落渊南丘残象聚落", "box": [0.463, 0.425, 0.575, 0.454], "evidence": EV}],
            "ignore_inputs": True}}, "list")
        self.assertEqual(sc.provisional, ["list"])

        def body(task):
            counts = task.ocr(0.35, 0.25, 1, 0.96, match=re.compile(r"(\d{1,2})/(\d{1,2})"))
            self.decide("counts", [b.name for b in counts])
            self.decide("all", sorted(b.name for b in task.ocr(0.35, 0.25, 1, 0.96)))
            self.decide("outside", [b.name for b in task.ocr(0, 0, 0.3, 0.2)])
            self.decide("box", [(b.x, b.y) for b in counts])
        run = self.run_scenario(sc, body)
        self.assertIsNone(run.raised, run.trace)
        got = {e.data["name"]: e.data["value"] for e in run.of("decision")}
        self.assertEqual(got["counts"], [count])
        self.assertEqual(got["all"], sorted([count, "落渊南丘残象聚落"]))
        self.assertEqual(got["outside"], [])
        self.assertEqual(got["box"], [(890, 527)])

    # -- the loader and the frames
    def test_loader_refuses_missing_evidence_and_bad_references(self):
        good = {"case": "self", "task": ["src.task.NightmareNestTask", "NightmareNestTask"], "start": "list",
                "states": {"list": {"frame": LIST, "transitions": [go("done", key="esc")]}, "done": {"end": True}},
                "expect": {"sequence": [{"state": "done", "evidence": EV}]}}
        scn.load_dict(copy.deepcopy(good))
        bad = []
        d = copy.deepcopy(good)
        del d["states"]["list"]["transitions"][0]["evidence"]
        bad.append(("transition without evidence", d))
        d = copy.deepcopy(good)
        del d["expect"]["sequence"][0]["evidence"]
        bad.append(("expectation without evidence", d))
        d = copy.deepcopy(good)
        d["states"]["list"]["transitions"][0]["to"] = "nowhere"
        bad.append(("transition to an unknown state", d))
        d = copy.deepcopy(good)
        d["expect"]["sequnce"] = []
        bad.append(("misspelt key", d))
        d = copy.deepcopy(good)
        d["states"]["list"]["frame"] = "nest_list/not-recorded.png"
        bad.append(("frame not in the library", d))
        d = copy.deepcopy(good)
        d["config"] = {"task": {"Which to Farm": []}}
        bad.append(("config without evidence", d))
        for why, d in bad:
            with self.subTest(why):
                with self.assertRaises(scn.ScenarioError):
                    scn.load_dict(d)

    def test_uid_strip_is_black_on_every_library_frame(self):
        blur = self.config["blur_area"]
        index = scn.frame_index()
        self.assertLessEqual({LIST, MAP}, set(index))
        self.check_frames([scn.FRAMES / p for p in sorted(index)])   # every committed frame
        lit = np.full((1080, 1920, 3), 7, dtype=np.uint8)
        self.assertEqual(scn.uid_strip_dark(lit, blur(1920, 1080)), (False, 7))
        lit[1054:1079, 1688:1912] = 0                          # the strip blur_area(1920, 1080) names
        self.assertEqual(scn.uid_strip_dark(lit, blur(1920, 1080)), (True, 0))


if __name__ == "__main__":
    unittest.main()
