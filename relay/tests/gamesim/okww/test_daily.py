"""T14: the daily task's chests, battle pass, stamina read and leftover farm (gamesim design 1, "Daily").

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows). The task is
OK-WW's own DailyTask with whatever our overlay rebound on it; each case calls the method the
machine was in when it went wrong (claim_daily, claim_battle_pass, get_stamina, open_daily), on
the recorded page or, where none was recorded, on a provisional_ocr state citing the real log
line. Every expected value is in the scenario file with its evidence, never from the code under
test. The frame library has no open-world frame, so the two upstream calls that need the world -
openF2Book and ensure_main - are pinned stand-ins (fakes.py) where a case passes through them.

Red before green: GAMESIM_LANES below runs each case alone (unittest -k) at the fix's parent and
at the fix; the red lane must fail at an assertion (ci_prepare.py run).
"""
import contextlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_CTX = Path("ark_gamesim.json")
if not _CTX.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; no {_CTX}")
_HERE = json.loads(_CTX.read_text(encoding="utf-8"))["gamesim_okww"]
sys.path.insert(0, _HERE)
try:
    import fakes
    from harness import ScriptedCase
except ImportError as exc:
    raise SystemExit(f"cannot import the harness from {_HERE}: {exc}") from None
from src.task.BaseWWTask import BaseWWTask  # noqa: E402
from src.task.DailyTask import DailyTask  # noqa: E402
from src.task.TacetTask import TacetTask  # noqa: E402

# OK-WW tags: the machine ran v3.7.4 from 2026-10-06 (frames.json okww fields, ok-script init
# lines); v3.7.4's get_stamina, claim_daily and claim_battle_pass bodies are the ones each fix
# was written against (the overlay pins 8ba6c1344ff8, 2b4977b62f7c, e9e8d67cb3bc).
GAMESIM_LANES = {
    "t14-chest140-red-b9ad39b4": {"tag": "v3.7.4", "overlay": "b9ad39b4~1", "select": "test_d1_",
                                  "expect": "red", "relay_line": None},
    "t14-chest140-green-b9ad39b4": {"tag": "v3.7.4", "overlay": "b9ad39b4", "select": "test_d1_",
                                    "expect": "green", "relay_line": None},
    "t14-chest80-red-fe0797c7": {"tag": "v3.7.4", "overlay": "fe0797c7~1", "select": "test_d2_",
                                 "expect": "red", "relay_line": None},
    "t14-chest80-green-fe0797c7": {"tag": "v3.7.4", "overlay": "fe0797c7", "select": "test_d2_",
                                   "expect": "green", "relay_line": None},
    "t14-pass-red-0188b2c1": {"tag": "v3.7.4", "overlay": "0188b2c1~1", "select": "test_d3_",
                              "expect": "red", "relay_line": None},
    "t14-pass-green-0188b2c1": {"tag": "v3.7.4", "overlay": "0188b2c1", "select": "test_d3_",
                                "expect": "green", "relay_line": None},
    "t14-stamina-red-a549c57e": {"tag": "v3.7.4", "overlay": "a549c57e~1", "select": "test_d4_",
                                 "expect": "red", "relay_line": None},
    "t14-stamina-green-a549c57e": {"tag": "v3.7.4", "overlay": "a549c57e", "select": "test_d4_",
                                   "expect": "green", "relay_line": None},
    "t14-gate-red-86bc0960": {"tag": "v3.7.4", "overlay": "86bc0960~1", "select": "test_d5_",
                              "expect": "red", "relay_line": None},
    "t14-gate-green-86bc0960": {"tag": "v3.7.4", "overlay": "86bc0960", "select": "test_d5_",
                                "expect": "green", "relay_line": None},
    "t14-flag-red-e4f49004": {"tag": "v3.7.4", "overlay": "e4f49004~1", "select": "test_d6_",
                              "expect": "red", "relay_line": None},
    "t14-flag-green-e4f49004": {"tag": "v3.7.4", "overlay": "e4f49004", "select": "test_d6_",
                                "expect": "green", "relay_line": None},
}


def fresh(task):
    """The task as at the start of a run: the overlay's per-run attributes (all named _ark_*) dropped."""
    for name in [n for n in vars(task) if n.startswith("_ark_")]:
        delattr(task, name)


def farm_reached(value, required=True) -> bool:
    """Set the overlay's 「a farm_* was called in this daily run」 flag.

    It lives in the closure of the overlay's claim_daily (claim_daily_after_farm: farm_called),
    reset by its DailyTask.run override at the start of each run and set by the farm hook. The
    cases enter the daily part-way, so they set it to what the machine's run had at that point.
    Overlays before 86bc0960 have no such flag; `required=False` lets those through."""
    cells = []
    for cell in getattr(DailyTask.claim_daily, "__closure__", None) or ():
        try:
            contents = cell.cell_contents
        except ValueError:          # an empty cell
            continue
        if isinstance(contents, dict) and "ran" in contents:
            cells.append(contents)
    if len(cells) != 1:
        if required:
            raise RuntimeError(f"the overlay's claim_daily holds {len(cells)} farm_called flags, not 1")
        return False
    cells[0]["ran"] = value
    return True


class TestDaily(ScriptedCase):
    task_class = DailyTask

    def setUp(self):
        fresh(self.task)

    @contextlib.contextmanager
    def farm_spy(self, stop):
        """Record each call of TacetTask.farm_tacet (the overlay's farm hook, or upstream's own).

        stop=True ends the scenario in its `farming` state at the call: the farm's own screens are
        not this case. stop=False lets the call through."""
        hooked = TacetTask.__dict__["farm_tacet"]
        case = self

        def farm_tacet(task, *a, **kw):
            case.decide("farm_tacet", {"daily": bool(kw.get("daily", False))})
            if stop:
                case.capture.script.enter("farming", "TacetTask.farm_tacet called")
            return hooked(task, *a, **kw)

        with mock.patch.object(TacetTask, "farm_tacet", farm_tacet):
            yield

    def book_open(self):
        return fakes.pinned(BaseWWTask, "openF2Book", fakes.book_already_open(self))

    # -- chests
    def test_d1_chest_row_140_all_claimed(self):
        farm_reached(True)
        with self.book_open():
            self.play("daily/chest_row_140_1011.json", lambda task: task.claim_daily())

    def test_d2_chest_row_80_each_due_chest(self):
        farm_reached(True)
        with self.book_open():
            self.play("daily/chest_row_80_1010.json", lambda task: task.claim_daily())

    # -- battle pass
    def test_d3_battle_pass_opened_again(self):
        with fakes.pinned(BaseWWTask, "ensure_main", fakes.world_already_shown(self)):
            self.play("daily/battle_pass_reopen.json", lambda task: task.claim_battle_pass())

    # -- stamina
    def test_d4_split_stamina_strip(self):
        def body(task):
            got = task.get_stamina()
            self.decide("get_stamina", [got[0], got[1]])
        self.play("daily/stamina_split_0921.json", body)

    # -- the leftover farm
    def test_d5_gate_shut_leftover_farmed(self):
        farm_reached(False, required=False)

        def body(task):
            got = task.open_daily()
            self.decide("open_daily", list(got))
            # (0, True) shuts upstream's gate (DailyTask.py:89): run() skips its farm block
            # (:117-128) and calls claim_daily next (:130).
            task.claim_daily()
        with self.book_open(), self.farm_spy(stop=True):
            self.play("daily/gate_180_leftover.json", body)

    def test_d6_no_stamina_flag_counted(self):
        farm_reached(False)

        def body(task):
            # The gate open (progress 0, points 0): run() calls the farm (DailyTask.py:117-121), then claim_daily.
            task.get_task_by_class(TacetTask).farm_tacet(daily=True, used_stamina=0, config=task.config)
            task.claim_daily()
        with self.book_open(), self.farm_spy(stop=False):
            self.play("daily/no_stamina_flag.json", body)


if __name__ == "__main__":
    unittest.main()
