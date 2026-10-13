"""T6 on Windows: runs the install cycle (gamesim/install/test_install_cycle.py) in full mode.

The cycle needs both interpreters of the job: the relay's 3.14.8 for okww_overlay (install,
drift, report_line) and OK-WW's 3.12.10 for each OK-WW start. This file is copied into
OK-WW's tests/ by ci_prepare.py and run by OK-WW's run_test.py with OK-WW's Python (the
`installed` lane globs gamesim/okww/test_*.py, so no lane or workflow edit is needed); it
starts the cycle with the relay's Python (RELAY_PY, which the workflow's "Interpreters"
step puts in GITHUB_ENV for every later step) and hands it its own interpreter.

The cycle works on its own OK-WW tree under the runner's temp folder, never on the lane's,
and removes the overlay's report at the end (one fixed path the lane reads after each test).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONTEXT = Path("ark_gamesim.json")
if not CONTEXT.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; "
                     f"no {CONTEXT} in {os.getcwd()}")
CTX = json.loads(CONTEXT.read_text(encoding="utf-8"))
CYCLE = Path(CTX["gamesim_okww"]).parent / "install" / "test_install_cycle.py"
# ci_prepare.TEST_TIMEOUT_S gives this file 600 s; the cycle's five OK-WW starts are capped
# at 100 s each (test_install_cycle.START_TIMEOUT_S), the rest is three shallow fetches.
CYCLE_TIMEOUT_S = 570


class TestInstallCycle(unittest.TestCase):
    def test_install_cycle(self):
        relay_py = os.environ.get("RELAY_PY")
        self.assertTrue(relay_py, "RELAY_PY is not set: the workflow's Interpreters step writes it to GITHUB_ENV")
        root = Path(tempfile.gettempdir()) / "ark-install-cycle"
        try:
            p = subprocess.run([relay_py, "-u", str(CYCLE), "--okww-python", sys.executable, "--root", str(root)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=CYCLE_TIMEOUT_S)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        out = (p.stdout + p.stderr).rstrip()
        print(out, flush=True)
        self.assertEqual(p.returncode, 0, "the install cycle failed (output above)")
        self.assertEqual(out.splitlines()[-1], "all checks passed")


if __name__ == "__main__":
    unittest.main()
