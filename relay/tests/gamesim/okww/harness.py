"""Drive the real OK-WW tasks, with our overlay loaded, through recorded screens (gamesim design 1).

Runs only inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows):
ok-script imports pywin32 at module top. Nothing upstream is imitated. `ScriptedCase` is
ok-script's own `ok.test.TaskTestCase` (OK(config) -> TaskManager.load_user_tasks executes
ok_tasks/ark_overrides.py, which ci_prepare.py installed with the relay's own installer), and
after it has started, four pieces are swapped in at the points ok-script's own test setup
uses (ok/test/__init__.py init_ok: `device_manager.capture_method = ImageCaptureMethod(...)`,
`device_manager.interaction = DoNothingInteraction(...)`):

  ScriptedCapture      returns the current state's frame. Upstream's ImageCaptureMethod
                       reverses its list and sticks on the last frame, so it cannot follow
                       a sequence that depends on what the task did.
  RecordingInteraction every input a task gives goes through ok-script's interaction
                       (ok/task/task.py click/back/send_key*/scroll/swipe/input_text/move
                       all call executor.interaction.*). Each is logged as
                       (state, action, x, y | key) and matched against the state's
                       transitions; one that matches nothing fails the case.
  VirtualClock         time.time and time.sleep, on the test thread only. ok-script's test
                       setup runs the executor in debug_mode, whose sleep is time.sleep
                       (ok/task/TaskExecutor.py sleep), and every wait_* loop times out on
                       time.time (wait_condition). Without it, AO's _after_confirm loop
                       (60 x 2 s) costs two real minutes per case.
  environment          hwnd_title is the game's window title (game_lang reads it,
                       BaseWWTask.game_lang); the overlay's REPORT, NO_CLAIM,
                       NO_STAMINA_FLAG and MASTER_POINTER point at per-case temp files;
                       task.screenshot is recorded, so _shot names can be asserted.

A test calls the task's own methods inside `play()`; expectations come from the scenario
file (scenario.py), each with its evidence, never from the code under test.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

CONTEXT = Path("ark_gamesim.json")
if not CONTEXT.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; "
                     f"no {CONTEXT} in {os.getcwd()}")
CTX = json.loads(CONTEXT.read_text(encoding="utf-8"))

import cv2  # noqa: E402  OK-WW's own dependency (opencv-python in its requirements.txt)
import numpy as np  # noqa: E402
from ok import og  # noqa: E402
from ok.device.capture_methods.base import BaseCaptureMethod  # noqa: E402
from ok.device.interaction_methods.base import BaseInteraction  # noqa: E402
from ok.task.task import BaseTask  # noqa: E402
from ok.test.TaskTestCase import TaskTestCase  # noqa: E402
from ok.feature.Box import Box, find_boxes_by_name  # noqa: E402

import scenario as scn  # noqa: E402

MODULE = "ark_overrides"      # ok-script names the module after the file (find_and_instantiate_class)
# The game window's title on the game PC: ok-script.2026-10-07.log line 170,
# "DeviceManager:update_pc_device pc_device: {... 'hwnd': '鸣潮  ', ...}" (two trailing spaces).
WINDOW_TITLE = "鸣潮  "
# What one captured frame costs in virtual time. The game PC measured 160-260 ms per frame
# on 2026-10-10 (gamesim design section 6, item 5); the low end, so a wait loop gets at
# least as many looks at a screen as it did on the machine.
FRAME_S = 0.16
# The redirected overlay paths (AO lines 44, 45, 709, 1623 at a44a536f).
REDIRECTS = ("REPORT", "NO_CLAIM", "NO_STAMINA_FLAG", "MASTER_POINTER")
_REAL_TIME = time.time
_REAL_SLEEP = time.sleep


# --------------------------------------------------------------------------- stopping

class _Halt(BaseException):
    """Stops the task where the scenario ends or leaves its script.

    A BaseException, so task code's `except Exception` (AO's _shot, upstream's retry loops)
    cannot swallow it. Everything is also recorded on the run, so a swallowed one still fails."""


class ScenarioEnd(_Halt):
    """The task reached an end state: the case is over."""


class OffScript(_Halt):
    """The task gave an input no transition of the current state accepts."""


class OverTime(_Halt):
    """The scenario ran past its virtual-time cap (scenario.max_s)."""


# --------------------------------------------------------------------------- clock

class VirtualClock:
    """time.time / time.sleep, virtual on one thread, real everywhere else.

    The executor thread ok-script starts (TaskExecutor.start) keeps real time, and so does
    every other thread. Virtual time starts at the real time when the clock starts."""

    def __init__(self, on_advance=None):
        self.thread = threading.current_thread()
        self.now = _REAL_TIME()
        self.started = self.now
        self.on_advance = on_advance
        self._patches = []

    def _mine(self) -> bool:
        return threading.current_thread() is self.thread

    def time(self) -> float:
        return self.now if self._mine() else _REAL_TIME()

    def sleep(self, seconds) -> None:
        if not self._mine():
            _REAL_SLEEP(seconds)
            return
        self.advance(max(0.0, float(seconds)))

    def advance(self, seconds: float) -> None:
        self.now += seconds
        if self.on_advance is not None:
            self.on_advance()

    @property
    def elapsed(self) -> float:
        return self.now - self.started

    def __enter__(self):
        self._patches = [mock.patch.object(time, "time", self.time),
                         mock.patch.object(time, "sleep", self.sleep)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        self._patches = []
        return False


# --------------------------------------------------------------------------- the run

@dataclass
class Event:
    kind: str            # click | key | key_up | mouse_up | move | scroll | swipe | text | state | decision | shot
    state: str
    t: float             # virtual seconds since the scenario started
    data: dict = field(default_factory=dict)

    def __str__(self):
        bits = " ".join(f"{k}={v!r}" for k, v in self.data.items())
        return f"[{self.t:7.2f}s {self.state}] {self.kind} {bits}"


@dataclass
class Run:
    """What happened in one scenario: the evidence the expectations are checked against."""
    scenario: scn.Scenario
    events: "list[Event]" = field(default_factory=list)
    off_script: "list[str]" = field(default_factory=list)
    state: str = ""
    ended: bool = False
    over_time: bool = False
    raised: "BaseException | None" = None
    trace: str = ""
    log: "list[str]" = field(default_factory=list)
    temp: "Path | None" = None

    def of(self, kind):
        return [e for e in self.events if e.kind == kind]

    @property
    def shots(self) -> "list[str]":
        return [e.data["name"] for e in self.of("shot")]

    @property
    def states(self) -> "list[str]":
        return [e.data["to"] for e in self.of("state")]

    def story(self, limit=60) -> str:
        lines = [str(e) for e in self.events[-limit:]]
        return "\n".join(lines) or "(no events)"


class Script:
    """The state machine of one scenario, fed by the capture, the interaction and the clock."""

    def __init__(self, sc: scn.Scenario, run: Run, task, clock: VirtualClock):
        self.sc = sc
        self.run = run
        self.task = task
        self.clock = clock
        self.state = sc.states[sc.start]
        self.entered = clock.now
        self._frames: "dict[Path, np.ndarray]" = {}
        self._blank = None
        run.state = sc.start
        self._event("state", to=sc.start, why="start")

    # -- bookkeeping
    def _event(self, kind, **data):
        self.run.events.append(Event(kind, self.state.name, round(self.clock.elapsed, 3), data))

    def enter(self, name: str, why: str) -> None:
        self.state = self.sc.states[name]
        self.entered = self.clock.now
        self.run.state = name
        self._event("state", to=name, why=why)
        if self.state.end:
            self.run.ended = True
            raise ScenarioEnd(name)

    # -- the screen
    def frame(self) -> np.ndarray:
        st = self.state
        if st.frame is None:
            # provisional_ocr or a frameless end state: a black screen of the recorded size,
            # so no template matches; the OCR text comes from the state (ScriptedCase._ocr_fun).
            if self._blank is None:
                self._blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
            return self._blank
        if st.frame not in self._frames:
            img = cv2.imdecode(np.fromfile(str(st.frame), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"cannot decode {st.frame}")
            self._frames[st.frame] = img
        return self._frames[st.frame]

    # -- time
    def tick(self) -> None:
        """Called whenever virtual time moves: after_s transitions and the cap."""
        if self.clock.elapsed > self.sc.max_s:
            self.run.over_time = True
            raise OverTime(f"past {self.sc.max_s} virtual seconds in {self.state.name}")
        in_state = self.clock.now - self.entered
        for t in self.state.transitions:
            if t.kind == "after_s" and in_state >= t.arg:
                self.enter(t.to, f"after_s {t.arg}")
                return

    # -- inputs
    def _in_rect(self, rect, x, y) -> bool:
        h, w = self.frame().shape[:2]
        x0, y0, x1, y1 = rect
        return x0 * w <= x <= x1 * w and y0 * h <= y <= y1 * h

    def _feature_box(self, t):
        """The real find_one on the current frame (ok-script FindFeature.find_one)."""
        kwargs = {"frame": self.frame()}
        if t.threshold:
            kwargs["threshold"] = t.threshold
        return self.task.find_one(t.arg, **kwargs)

    def on_input(self, kind: str, **data) -> None:
        self._event(kind, **data)
        if kind in ("key_up", "mouse_up"):
            return              # a release finishes a press the state already accepted
        for t in self.state.transitions:
            if kind == "click" and t.kind == "click" and self._in_rect(t.arg, data["x"], data["y"]):
                self.enter(t.to, f"click in {t.arg}")
                return
            if kind == "click" and t.kind == "feature":
                box = self._feature_box(t)
                if box is not None and box.x <= data["x"] <= box.x + box.width \
                        and box.y <= data["y"] <= box.y + box.height:
                    self.enter(t.to, f"click on {t.arg} {box}")
                    return
            if kind == "key" and t.kind == "key" and str(data.get("key")).lower() == t.arg.lower():
                self.enter(t.to, f"key {t.arg}")
                return
        if self.state.ignore_inputs:
            return
        what = f"{self.state.name}: {kind} {data} matches no transition"
        self.run.off_script.append(what)
        raise OffScript(what)


# --------------------------------------------------------------------------- the four pieces

class ScriptedCapture(BaseCaptureMethod):
    """ok-script's capture interface; the frame is whatever the current state shows."""
    name = "gamesim scripted capture"
    description = "frames of the current scenario state"

    def __init__(self, exit_event):
        super().__init__()
        self.exit_event = exit_event
        self.script: "Script | None" = None
        self._idle = np.zeros((1080, 1920, 3), dtype=np.uint8)

    def do_get_frame(self):
        script = self.script
        if script is None:
            return self._idle.copy()
        if script.clock.thread is threading.current_thread():
            # A frame costs time on the machine too. Advanced before the look, so an
            # after_s transition that falls due now shows the next state's screen.
            script.clock.advance(FRAME_S)
        return script.frame().copy()

    def get_abs_cords(self, x, y):
        return x, y

    def connected(self):
        return True


class RecordingInteraction(BaseInteraction):
    """ok-script's interaction interface: every input is recorded and matched, none is sent."""

    def __init__(self, capture):
        super().__init__(capture)
        self.script: "Script | None" = None

    def _input(self, kind, **data):
        if self.script is None:
            raise AssertionError(f"input {kind} {data} outside a scenario")
        self.script.on_input(kind, **data)

    def click(self, x=-1, y=-1, move_back=False, name=None, move=True, down_time=0.05, key="left"):
        self._input("click", x=int(x), y=int(y), button=key, name=name)

    def mouse_down(self, x=-1, y=-1, name=None, key="left"):
        self._input("click", x=int(x), y=int(y), button=key, name=name, down=True)

    def mouse_up(self, key="left"):
        self._input("mouse_up", button=key)

    def send_key(self, key, down_time=0.02):
        self._input("key", key=str(key))

    def send_key_down(self, key):
        self._input("key", key=str(key), down=True)

    def send_key_up(self, key):
        self._input("key_up", key=str(key))

    def back(self, *args, **kwargs):
        self._input("key", key="esc", via="back")

    def move(self, x, y):
        self._input("move", x=int(x), y=int(y))

    def scroll(self, x, y, scroll_amount):
        self._input("scroll", x=int(x), y=int(y), amount=scroll_amount)

    def swipe(self, from_x, from_y, to_x, to_y, duration, settle_time=0):
        self._input("swipe", x=int(from_x), y=int(from_y), to_x=int(to_x), to_y=int(to_y))

    def input_text(self, text):
        self._input("text", text=text)


class _LogTap(logging.Handler):
    """ok-script logs everything through the `ok` logger as '<Name>:<message>' (ok/util/logger.py)."""

    def __init__(self, sink):
        super().__init__(logging.DEBUG)
        self.sink = sink

    def emit(self, record):
        try:
            self.sink.append(f"{record.levelname} {record.getMessage()}")
        except Exception:  # noqa: BLE001 - a log line that cannot format is not a test failure
            pass


# --------------------------------------------------------------------------- the case

class ScriptedCase(TaskTestCase):
    """ok-script's TaskTestCase with the four pieces swapped in; one task class per file.

    ok.test.init_ok builds one OK per process and tearDownClass quits it, as in every
    upstream test, so each test file runs in its own process (ci_prepare.py does that)."""
    task_class = None
    config = None

    @classmethod
    def setUpClass(cls):
        if cls.config is None:
            from config import config      # OK-WW's own config.py, as its tests import it
            cls.config = config
        super().setUpClass()                 # OK(config): the overlay is executed here, or never
        from ok.test import ok as started
        dm = started.device_manager
        cls.capture = ScriptedCapture(dm.exit_event)
        cls.interaction = RecordingInteraction(cls.capture)
        dm.capture_method = cls.capture      # where init_ok put ImageCaptureMethod
        dm.interaction = cls.interaction     # where init_ok put DoNothingInteraction
        cls.overlay = sys.modules.get(MODULE)
        if cls.overlay is None:
            raise RuntimeError(f"ok-script did not execute ok_tasks/{MODULE}.py; "
                               f"task errors {dict(og.task_manager.task_errors)}")
        got = hashlib.sha256(Path(cls.overlay.__file__).read_bytes()).hexdigest()
        if got != CTX["overlay_sha256"]:
            raise RuntimeError(f"loaded overlay {got[:12]} is not the lane's {CTX['overlay']} "
                               f"({CTX['overlay_sha256'][:12]})")
        report = getattr(cls.overlay, "REPORT", None)
        cls.load_report = json.loads(Path(report).read_text(encoding="utf-8")) \
            if report and Path(report).is_file() else None
        print(f"lane {CTX['lane']}: OK-WW {CTX['okww_tag']} ({CTX['okww_commit'][:12]}), "
              f"overlay {CTX['overlay']} ({CTX['overlay_sha256'][:12]}); load report "
              + json.dumps(cls.load_report, ensure_ascii=False))

    # -- environment
    def _redirect(self, sc: scn.Scenario, tmp: Path) -> "dict[str, object]":
        """Point the overlay's machine paths at files under `tmp`; return what to restore."""
        mod = self.overlay
        saved = {name: getattr(mod, name, _MISSING) for name in REDIRECTS}
        paths = {"REPORT": tmp / "ark-okww-overlay.json",
                 "NO_CLAIM": tmp / "ark-okww-farm.no-claim",
                 "NO_STAMINA_FLAG": tmp / "state" / "no-stamina-farm.flag",
                 "MASTER_POINTER": tmp / "ark-okww-master.txt"}
        # REPORT is written while OK(config) executes the overlay, before any test code can
        # run, so the load-time report stays at the machine path (test_overlay_loads.py reads
        # it there). A copy goes to the temp file; anything written later lands there.
        if saved["REPORT"] is not _MISSING and Path(str(saved["REPORT"])).is_file():
            shutil.copyfile(str(saved["REPORT"]), paths["REPORT"])
        flags = sc.config.get("flags", {})
        if flags.get("no_claim"):
            paths["NO_CLAIM"].write_text("", encoding="utf-8")
        if flags.get("no_stamina"):
            paths["NO_STAMINA_FLAG"].parent.mkdir(parents=True, exist_ok=True)
            paths["NO_STAMINA_FLAG"].write_text("", encoding="utf-8")
        master = sc.config.get("master", {})
        if master:
            mdir = tmp / "master"
            mdir.mkdir()
            for name, body in master.items():
                (mdir / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            paths["MASTER_POINTER"].write_text(str(mdir), encoding="utf-8")
        for name, path in paths.items():
            setattr(mod, name, str(path))
        return saved

    def _restore(self, saved):
        for name, value in saved.items():
            if value is _MISSING:
                if hasattr(self.overlay, name):
                    delattr(self.overlay, name)
            else:
                setattr(self.overlay, name, value)

    def _apply_task_config(self, sc) -> dict:
        """Set the scenario's task keys through ok-script's own Config; return the old values."""
        old = {}
        for key, value in sc.config.get("task", {}).items():
            old[key] = self.task.config.get(key, _MISSING)
            self.task.config[key] = value
            if self.task.config.get(key) != value:
                raise AssertionError(f"ok-script's Config refused {key}={value!r} "
                                     f"(kept {self.task.config.get(key)!r})")
        return old

    def _restore_task_config(self, old):
        for key, value in old.items():
            if value is _MISSING:
                self.task.config.pop(key, None)
            else:
                self.task.config[key] = value

    def _ocr_fun(self, real):
        """OCR for provisional_ocr states: the state's logged text, through ok-script's own
        text fixing and match filtering (OCR.fix_texts, find_boxes_by_name)."""
        case = self

        def pick(lib):
            fun = real(lib)
            script = case.capture.script
            if script is None or script.state.provisional_ocr is None:
                return fun

            def provisional(box, image, match, scale_factor, threshold, lib_name):
                h, w = script.frame().shape[:2]
                found = []
                for item in script.state.provisional_ocr:
                    x0, y0, x1, y1 = item["box"]
                    b = Box(x0 * w, y0 * h, to_x=x1 * w, to_y=y1 * h, confidence=1.0, name=item["text"])
                    cx, cy = b.x + b.width / 2, b.y + b.height / 2
                    if box is None or (box.x <= cx <= box.x + box.width and box.y <= cy <= box.y + box.height):
                        found.append(b)
                case.task.fix_texts(found)
                ocr_boxes = list(found)
                if match is not None:
                    found = find_boxes_by_name(found, match)
                return found, ocr_boxes
            return provisional
        return pick

    # -- running
    def decide(self, name: str, value) -> None:
        """Record a decision the test read off the task (a return value, an attribute)."""
        script = self.capture.script
        if script is None:
            raise AssertionError("decide() outside play()")
        script._event("decision", name=name, value=value)

    def run_scenario(self, sc: "scn.Scenario | str", body) -> Run:
        """Run `body(task)` against the scenario and return what happened (no assertions)."""
        if not isinstance(sc, scn.Scenario):
            sc = scn.load(sc)
        want = sc.task[1]
        if type(self.task).__name__ != want:
            raise AssertionError(f"scenario {sc.case} drives {want}, this case has {type(self.task).__name__}")
        self.check_frames(sc.frames)
        tmp = Path(tempfile.mkdtemp(prefix=f"gamesim-{sc.case}-"))
        run = Run(sc, temp=tmp)
        task = self.task
        tap = _LogTap(run.log)
        ok_logger = logging.getLogger("ok")
        saved = self._redirect(sc, tmp)
        old_cfg = self._apply_task_config(sc)
        real_shot = task.screenshot
        real_ocr_fun = task.ocr_fun

        def shot(name=None, frame=None, show_box=False, frame_box=None):
            if self.capture.script is not None:
                self.capture.script._event("shot", name=name)
            return real_shot(name, frame=frame, show_box=show_box, frame_box=frame_box)

        title = mock.patch.object(BaseTask, "hwnd_title", new_callable=mock.PropertyMock,
                                  return_value=WINDOW_TITLE)
        clock = VirtualClock()
        script = Script(sc, run, task, clock)
        clock.on_advance = script.tick
        ok_logger.addHandler(tap)
        task.screenshot = shot
        task.ocr_fun = self._ocr_fun(real_ocr_fun)
        self.capture.script = script
        self.interaction.script = script
        task.executor.reset_scene()           # the next look takes the start state's frame
        try:
            with title, clock:
                try:
                    body(task)
                except ScenarioEnd:
                    pass
                except _Halt as exc:
                    run.raised = exc
                except Exception as exc:  # noqa: BLE001 - the task's own exceptions are outcomes
                    run.raised = exc
                    run.trace = traceback.format_exc()
        finally:
            self.capture.script = None
            self.interaction.script = None
            for attr in ("screenshot", "ocr_fun"):
                task.__dict__.pop(attr, None)
            ok_logger.removeHandler(tap)
            self._restore_task_config(old_cfg)
            self._restore(saved)
            task.executor.reset_scene()
        print(f"\n--- scenario {sc.case}: state {run.state}, ended {run.ended}, "
              f"{clock.elapsed:.1f} virtual s, {len(run.events)} events")
        print(run.story())
        if run.trace:
            print(run.trace)
        return run

    def check_frames(self, paths) -> None:
        """Every frame in `paths` has OK-WW's UID strip blacked out (config.blur_area)."""
        blur = self.config.get("blur_area")
        if blur is None:
            raise AssertionError("OK-WW's config has no blur_area; cannot check the UID strip")
        for path in paths:
            img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            h, w = img.shape[:2]
            dark, peak = scn.uid_strip_dark(img, blur(w, h))
            if not dark:
                raise AssertionError(f"{path.name}: the UID strip {blur(w, h)} is not black (max {peak}); "
                                     "the repository is public")

    def check(self, run: Run) -> None:
        """Assert the scenario's expectations on what happened."""
        sc, exp = run.scenario, run.scenario.expect
        problems = []
        if run.off_script:
            problems += [f"off script: {w}" for w in run.off_script]
        if run.over_time:
            problems.append(f"ran past {sc.max_s} virtual seconds")
        want_raise = exp["raises"]
        got = run.raised if not isinstance(run.raised, _Halt) else None
        if want_raise is None and got is not None:
            problems.append(f"the task raised {type(got).__name__}: {got}")
        if want_raise is not None:
            names = [c.__name__ for c in type(got).__mro__] if got is not None else []
            if want_raise["name"] not in names:
                problems.append(f"expected {want_raise['name']} ({want_raise['evidence']}), "
                                f"got {type(got).__name__ if got else 'no exception'}")
        if exp["end"] is not None and not (run.ended and run.state == exp["end"]):
            problems.append(f"expected to end in {exp['end']}, stopped in {run.state} (ended={run.ended})")
        hit = sorted(set(exp["never_states"]) & set(run.states))
        if hit:
            problems.append(f"entered never_states {hit}")
        for s in exp["shots"]:
            if s["name"] not in run.shots:
                problems.append(f"no screenshot {s['name']!r} ({s['evidence']}); shots {run.shots}")
        for r in exp["log"]:
            if not any(re.search(r["re"], line) for line in run.log):
                problems.append(f"no log line matches {r['re']!r} ({r['evidence']})")
        for r in exp["log_never"]:
            bad = [line for line in run.log if re.search(r["re"], line)]
            if bad:
                problems.append(f"log line matches forbidden {r['re']!r}: {bad[0][:200]}")
        problems += _sequence_problems(exp["sequence"], run.events)
        if problems:
            self.fail(f"scenario {sc.case} ({sc.source}):\n  - " + "\n  - ".join(problems)
                      + "\nlast events:\n" + run.story(30))

    def play(self, sc: "scn.Scenario | str", body) -> Run:
        """run_scenario + check: the usual way a case runs."""
        run = self.run_scenario(sc, body)
        self.check(run)
        return run


_MISSING = object()


def _step_matches(step, e: Event) -> bool:
    if "decision" in step:
        return e.kind == "decision" and e.data["name"] == step["decision"] and e.data["value"] == step["value"]
    if "click" in step:
        x, y = step["click"]
        return e.kind == "click" and abs(e.data["x"] - x) <= step["within"] and abs(e.data["y"] - y) <= step["within"]
    if "key" in step:
        return e.kind == "key" and str(e.data["key"]).lower() == str(step["key"]).lower()
    if "state" in step:
        return e.kind == "state" and e.data["to"] == step["state"]
    if "shot" in step:
        return e.kind == "shot" and e.data["name"] == step["shot"]
    return False


def _sequence_problems(sequence, events) -> "list[str]":
    """The expected steps must appear in this order (other events may come between)."""
    i = 0
    for step in sequence:
        while i < len(events) and not _step_matches(step, events[i]):
            i += 1
        if i == len(events):
            shown = {k: v for k, v in step.items() if k != "evidence"}
            return [f"expected step {shown} ({step['evidence']}) did not happen in order"]
        i += 1
    return []
