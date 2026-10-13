"""P2: on the 2026-10-07 nest list, the standing order 「只刷 落渊南丘」 sends the run to 落渊南丘 (gamesim design 5).

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows). The task
is OK-WW's own NightmareNestTask with whatever our overlay rebound on it; the test calls the
same methods upstream's NightmareNestTask.run / get_nest_to_go do, in the same order:
_init_queue(), find_nest() on the list, then combat_nest(nest), whose first input is the click
on the chosen row and whose travel step clicks gray_teleport on the map. Expected values come
from the game PC's log of that moment (scenarios/nest/find_nest_pointer_1007.json, each with
its line), not from the code under test.

Red before green (ci_prepare.py LANES): the overlay at f6b5f432~1 on OK-WW v3.7.3 - the pair the
machine ran on 10-04/05 - leaves find_nest to upstream, which takes the first nest reading 0
(梦枢天罗 0/48), so the click lands on the wrong row and the case fails; f6b5f432 passes.
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
    from harness import ScriptedCase
except ImportError as exc:
    raise SystemExit(f"cannot import the harness from {_HERE}: {exc}") from None
from src.task.NightmareNestTask import NightmareNestTask  # noqa: E402

SCENARIO = "nest/find_nest_pointer_1007.json"


class TestFindNestPointer(ScriptedCase):
    task_class = NightmareNestTask

    def test_pointer_row_is_chosen_and_clicked(self):
        def body(task):
            task._init_queue()                 # what run() does before get_nest_to_go
            nest = task.find_nest()
            self.decide("find_nest", getattr(nest, "cache_key", None))
            if nest is not None:
                task.combat_nest(nest)         # clicks the chosen row, then travels
        self.play(SCENARIO, body)


if __name__ == "__main__":
    unittest.main()
