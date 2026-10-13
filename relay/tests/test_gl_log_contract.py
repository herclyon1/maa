"""The T7 log contract on the Mac (gamesim design 3): runs gamesim/chain/test_log_contract.py.

That test judges, with the relay's own verdict code, the real machine logs the relay once misread
and the scenario logs the real overlay printed on Windows (committed copies in
gamesim/chain/logs/). It lives under gamesim/chain/ because the Windows job runs it on fresh logs
(ci_prepare.py, lane `installed`); this file puts the same check in the Mac gate, which runs
tests/test_*.py only.

    relay-python tests/test_gl_log_contract.py
"""
import subprocess
import sys
from pathlib import Path

CHAIN = Path(__file__).resolve().parent / "gamesim" / "chain" / "test_log_contract.py"

p = subprocess.run([sys.executable, str(CHAIN)], capture_output=True, text=True, encoding="utf-8")
out = p.stdout + p.stderr
print(out.rstrip())
last = (out.strip().splitlines() or [""])[-1]
if p.returncode != 0 or not last.endswith("all checks passed"):
    print("FAILED: gamesim/chain/test_log_contract.py")
    sys.exit(1)
print("all checks passed")
