"""P1: the real ok-script framework loads our OK-WW overlay and every rebind takes (gamesim design 5).

Runs only inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows):
ok-script imports pywin32 at module top. ci_prepare.py has already put the overlay in
<working>/ok_tasks/ark_overrides.py with okww_overlay.install(), the relay's own installer,
and deleted any old report. This file is copied into OK-WW's tests/ and run by OK-WW's own
run_test.py, so it starts the framework exactly the way upstream's tests do: TaskTestCase ->
ok.test.init_ok -> OK(config) -> TaskManager.load_user_tasks, which executes every .py in
ok_tasks/ (ok-script 2.0.8 ok/core/task_manager.py). Nothing is stood in for.

What must hold, read from the report the overlay itself writes (the file the relay reads at
boot, okww_overlay.REPORT) and from the classes it rebinds:
  - the report was written by this start, and error == '';
  - skipped == [] and adapted == [] (okww_overlay.report_line() is '' only then);
  - applied is exactly the rebinds a static read of the installed file finds
    (test_gl_okww_contract.rebinds, U1's reader, run by ci_prepare.py), and on the gate lane
    that is 26 (design 5, P1: "the report shows 26 applied");
  - each applied method on OK-WW's class is now the overlay's function.

Red before green (ci_prepare.py LANES): the overlay before f6b5f432 on OK-WW v3.7.3 fails
here with find_nest skipped, the relay.log line of 2026-10-04 21:20:19; f6b5f432 passes.
"""
import json
import os
import sys
import time
import unittest
from pathlib import Path

CONTEXT = Path("ark_gamesim.json")
if not CONTEXT.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; "
                     f"no {CONTEXT} in {os.getcwd()}")
CTX = json.loads(CONTEXT.read_text(encoding="utf-8"))
STARTED = time.time()

from config import config  # noqa: E402  OK-WW's own config.py, as its tests import it
from ok import og  # noqa: E402
from ok.test.TaskTestCase import TaskTestCase  # noqa: E402
from src.task.FarmEchoTask import FarmEchoTask  # noqa: E402

# The gate lane's count: design section 5, P1 ("26 applied"), and U1's static read of
# ark_overrides.tasks.py at 1ae09c11 (test_gl_okww_contract.py prints "(26 rebinds)").
INSTALLED_REBINDS = 26
MODULE = "ark_overrides"      # ok-script names the module after the file (find_and_instantiate_class)


def _owner_and_method(label):
    return ".".join(label.split(".")[-2:])


class TestOverlayLoads(TaskTestCase):
    task_class = FarmEchoTask     # any OK-WW task; upstream's tests/TestFarmEcho.py uses this one
    config = config

    @classmethod
    def setUpClass(cls):
        super().setUpClass()      # OK(config): the overlay is executed here, or never
        path = Path(CTX["report"])
        cls.report_path = path
        cls.report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        cls.report_mtime = path.stat().st_mtime if path.is_file() else None
        cls.module = sys.modules.get(MODULE)
        cls.load_errors = dict(og.task_manager.task_errors)
        print(f"lane {CTX['lane']}: OK-WW {CTX['okww_tag']} ({CTX['okww_commit'][:12]}), "
              f"overlay {CTX['overlay']} ({CTX['overlay_sha256'][:12]})")
        print("report: " + json.dumps(cls.report, ensure_ascii=False))
        print(f"task_manager.task_errors: {cls.load_errors}")

    def _report(self):
        if self.report is None:
            self.fail(f"the overlay wrote no report at {self.report_path}")
        return self.report

    def test_overlay_was_executed_by_the_task_manager(self):
        self.assertIsNotNone(self.module, f"ok-script did not execute ok_tasks/{MODULE}.py")
        self.assertEqual(self.load_errors, {}, "ok-script's task manager failed to load a file")

    def test_report_written_by_this_start(self):
        self._report()
        self.assertGreaterEqual(self.report_mtime, STARTED - 1, "the report on disk predates this start")
        self.assertEqual(set(self.report), {"applied", "skipped", "adapted", "error"})
        if self.module is not None:
            self.assertEqual(self.report["applied"], list(self.module._applied),
                             "the report is not the one this process wrote")

    def test_no_error(self):
        self.assertEqual(self._report()["error"], "")

    def test_nothing_skipped(self):
        self.assertEqual(self._report()["skipped"], [])

    def test_nothing_adapted(self):
        self.assertEqual(self._report()["adapted"], [])

    def test_applied_is_every_rebind(self):
        applied = self._report()["applied"]
        self.assertEqual(len(applied), len(set(applied)), "a rebind was applied twice")
        # The static reader names the target as the overlay's source does (a class, or the
        # module variable start_controller before 788c031b); the report uses its __name__
        # (ok.core.start_controller). Owner and method are what both agree on.
        self.assertEqual(sorted(_owner_and_method(a) for a in applied),
                         sorted(_owner_and_method(a) for a in CTX["expected_applied"]))
        if CTX["lane"] == "installed":
            self.assertEqual(len(applied), INSTALLED_REBINDS)

    def test_rebinds_are_live_on_okww_classes(self):
        """The report says applied; the class attribute says whether it really is ours now."""
        not_ours = []
        for label in self._report()["applied"]:
            owner, _, name = label.rpartition(".")
            if owner in sys.modules:          # a module-level function (ok.core.start_controller)
                owners = [sys.modules[owner]]
            else:
                owners = [obj for mod in list(sys.modules.values())
                          if getattr(mod, "__name__", "").startswith(("src.", "ok."))
                          for obj in [vars(mod).get(owner)] if isinstance(obj, type)]
            if not owners or not any(getattr(getattr(c, name, None), "__module__", None) == MODULE
                                     for c in owners):
                not_ours.append(label)
        self.assertEqual(not_ours, [])


if __name__ == "__main__":
    unittest.main()
