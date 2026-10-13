"""One OK-WW start, the way upstream's own tests start it; says what the start loaded.

Copied by test_install_cycle.py into <working>/tests/ of an OK-WW tree it laid out, and run
there with OK-WW's Python through OK-WW's own run_test.py (what its run_tests.ps1 and
test.yml do). TaskTestCase -> ok.test.init_ok -> OK(config) -> TaskManager.load_user_tasks
executes every .py in <working>/ok_tasks/ (ok-script 2.0.8 ok/core/task_manager.py), so our
overlay is executed here exactly as at OK-WW's start on the game PC, or not at all.

It asserts nothing about the overlay: the relay side reads the overlay's own report back
(okww_overlay.last_report, the file the relay reads at boot) and this file's answer, and
judges. Written to OUT, next to OK-WW's main.py (the folder run_test.py runs in).

Windows only: ok-script imports pywin32 at module top (ok/util/window.py).
"""
import json
import sys
import unittest
from pathlib import Path

OUT = Path("ark_install_probe.json")

from config import config  # noqa: E402  OK-WW's own config.py, as its tests import it
from ok import og  # noqa: E402
from ok.test.TaskTestCase import TaskTestCase  # noqa: E402
from src.task.FarmEchoTask import FarmEchoTask  # noqa: E402

MODULE = "ark_overrides"      # ok-script names the module after the file (find_and_instantiate_class)


class OkwwStart(TaskTestCase):
    task_class = FarmEchoTask     # any OK-WW task; upstream's tests/TestFarmEcho.py uses this one
    config = config

    def test_start(self):
        mod = sys.modules.get(MODULE)
        OUT.write_text(json.dumps({
            "overlay_executed": mod is not None,
            "applied_in_process": list(getattr(mod, "_applied", None) or []) if mod else None,
            "task_errors": {str(k): str(v) for k, v in dict(og.task_manager.task_errors).items()},
        }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
