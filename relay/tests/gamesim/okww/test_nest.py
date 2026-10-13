"""T13: the nightmare-nest list and the map after it (gamesim design 1, "Nest").

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows). The task is
OK-WW's own NightmareNestTask with whatever our overlay rebound on it, on recorded frames of the
nest list and the map. Each case calls what upstream's run() loop calls - get_nest_to_go(), or
find_nest() then combat_nest() for a lap whose book is already open (openF2Book needs the open
world, which has no frame) - and every expected value is in the scenario file with its evidence.
The 10-07 pointer case is test_p2_find_nest.py (P2).

Red before green: GAMESIM_LANES below runs each case alone (unittest -k) at the fix's parent and
at the fix; the red lane must fail at an assertion (ci_prepare.py run).
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
    import fakes
    from harness import ScriptedCase
except ImportError as exc:
    raise SystemExit(f"cannot import the harness from {_HERE}: {exc}") from None
from src.task.BaseWWTask import BaseWWTask  # noqa: E402
from src.task.NightmareNestTask import NightmareNestTask  # noqa: E402

# A literal (ci_prepare.py reads it statically). f6b5f432~1 on v3.7.3 is the pair the machine ran
# on 10-04/05; the red lane's relay_line is what the relay said about that load report
# (relay.log 2026-10-04 21:20:19, ci_prepare.MACHINE_2026_10_04).
GAMESIM_LANES = {
    "t13-allfull-red-2ae8d291": {"tag": "v3.7.4", "overlay": "2ae8d291~1", "select": "test_n2_",
                                 "expect": "red", "relay_line": None},
    "t13-allfull-green-2ae8d291": {"tag": "v3.7.4", "overlay": "2ae8d291", "select": "test_n2_",
                                   "expect": "green", "relay_line": None},
    "t13-mapopen-red-92add28e": {"tag": "v3.7.4", "overlay": "92add28e~1", "select": "test_n3_",
                                 "expect": "red", "relay_line": None},
    "t13-mapopen-green-92add28e": {"tag": "v3.7.4", "overlay": "92add28e", "select": "test_n3_",
                                   "expect": "green", "relay_line": None},
    "t13-partial-red-f6b5f432": {"tag": "v3.7.3", "overlay": "f6b5f432~1", "select": "test_n4_",
                                 "expect": "red",
                                 "relay_line": "OK-WW 有改动没贴上（上游源码和登记的不一致）：NightmareNestTask.find_nest"
                                               "（上游正文变了（现在 12d040afa102，我们照着 3b0271924cac 抄的））"},
    "t13-partial-green-f6b5f432": {"tag": "v3.7.3", "overlay": "f6b5f432", "select": "test_n4_",
                                   "expect": "green"},
}


def fresh(task):
    """The task as at the start of a run: upstream's per-run sets emptied (as its run() does,
    NightmareNestTask.py:45-46) and the overlay's per-run attributes (all named _ark_*) dropped."""
    task._unreachable_nests.clear()
    task._nest_deaths.clear()
    for name in [n for n in vars(task) if n.startswith("_ark_")]:
        delattr(task, name)


class TestNest(ScriptedCase):
    task_class = NightmareNestTask

    def setUp(self):
        fresh(self.task)

    def lap(self, task):
        """One lap with the book open on the list: find_nest, then combat_nest on what it chose."""
        task._init_queue()                 # what run() does before its first get_nest_to_go
        nest = task.find_nest()
        self.decide("find_nest", getattr(nest, "cache_key", None))
        if nest is not None:
            task.combat_nest(nest)

    def test_n1_full_nest_passed_banner_map_travelled(self):
        self.play("nest/pointer_two_banner_1013.json", self.lap)

    def test_n2_all_full_both_pages(self):
        def body(task):
            task._init_queue()
            nest = task.get_nest_to_go()
            self.decide("get_nest_to_go", getattr(nest, "cache_key", None))
        with fakes.pinned(BaseWWTask, "openF2Book", fakes.book_already_open(self)):
            self.play("nest/all_full_1013.json", body)

    def test_n3_unreachable_nest_map_closed(self):
        def body(task):
            # Inside the daily (the 10-05 run was DailyTask's 「Auto Farm all Nightmare Nest」), upstream
            # replaces the nest task's ensure_main with a do-nothing lambda (DailyTask.py:98-99).
            task.ensure_main = lambda *args, **kwargs: None
            self.lap(task)
            task.get_nest_to_go()          # the next lap of run()'s loop
        try:
            self.play("nest/map_left_open.json", body)
        finally:
            self.task.__dict__.pop("ensure_main", None)   # as DailyTask.py:115 does

    def test_n4_started_nest_chosen(self):
        self.play("nest/partial_6of41_1012.json", self.lap)


if __name__ == "__main__":
    unittest.main()
