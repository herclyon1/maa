"""tests/_parts.py, the runner of the merged test files (dispatch relay-slim-round1-1108):

* a part that exits non-zero, or raises, is a failed part, and the parts after it still run;
* what a part changed is back before the next one: os.environ, a stdlib attribute it swapped
  (urlopen), a logger's propagate flag, a module it imported (dropped from sys.modules), its
  working directory.
"""
import logging
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import run_parts
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


REAL = urllib.request.urlopen
# A variable of this test only (not a setting of the relay, so not in docs/CONFIG.md).
VAR = "PARTS_TEST_VARIABLE"
CWD = os.getcwd()
seen = {}


def _part_changes_everything():
    os.environ[VAR] = "1"
    urllib.request.urlopen = lambda *a, **k: None
    logging.getLogger("ark.test_parts").propagate = False
    import colorsys  # noqa: PLC0415 - a module this part brings in
    colorsys.rgb_to_hsv(0, 0, 0)
    os.chdir(tmpdir())
    sys.exit(1)


def _part_sees_nothing_of_it():
    seen["env"] = VAR in os.environ
    seen["urlopen"] = urllib.request.urlopen is REAL
    seen["propagate"] = logging.getLogger("ark.test_parts").propagate
    seen["module"] = "colorsys" in sys.modules
    seen["cwd"] = os.getcwd()


def _part_raises():
    raise RuntimeError("a part that crashes")


print("[three parts: one exits 1, one checks, one raises]")
check("the run fails", run_parts([_part_changes_everything, _part_sees_nothing_of_it, _part_raises]), 1)
check("……and every part ran", "cwd" in seen, True)
check("the next part does not see the first one's environment variable", seen.get("env"), False)
check("……nor its fake urlopen", seen.get("urlopen"), True)
check("……nor its logger flag", seen.get("propagate"), True)
check("……nor the module it imported", seen.get("module"), False)
check("……nor its working directory", seen.get("cwd"), CWD)
check("all passing parts: 0", run_parts([_part_sees_nothing_of_it]), 0)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
