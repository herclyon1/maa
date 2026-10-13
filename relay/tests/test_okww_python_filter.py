"""Which pythons count as OK-WW's own, and what an unreadable list means.

The filter (preupdate_okww._OKWW_PY) decides what game_alive reports, what
stop_okww_script stops, what _okww_left kills by number and what the full stop
takes down. It matched a bare '*ok-ww*', and PowerShell's -like ignores case, so
any python with "OK-WW" among its arguments was taken for OK-WW:
`dispatch_guard.py start OK-WW` matched itself (scripts/windows/dispatch_guard.py).
It now matches OK-WW's install folder. The -like patterns are run here with
fnmatch on lowered strings, which is what -like does for '*' and '?'.

okww_python_pids read a failed query (empty stdout) as "none running"; a nonzero
exit, or empty output with an error on stderr, is now None.
"""
import fnmatch
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.preupdate import preupdate_okww as P

fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


def is_okww(cmdline: str, ps: str = P._OKWW_PY) -> bool:
    """Does the Where-Object of `ps` keep a process with this command line?"""
    pats = re.findall(r"-like\s+'([^']*)'", ps)
    return any(fnmatch.fnmatchcase(cmdline.lower(), p.lower()) for p in pats)


print("[the filter: OK-WW's install folder, nothing else]")
# OK-WW's real line, ok-script.2026-10-12.log 15:23:30, run by echofarm._launch's pythonw.
REAL = r'"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe" D:\ark\okww\data\apps\ok-ww\working\main.py -t 2 -e'
check("OK-WW as the echo farm starts it", is_okww(REAL), True)
check("OK-WW's own python running -m ok",
      is_okww(r'"D:\ark\okww\data\apps\ok-ww\python\python.exe" -m ok run_task FarmEchoTask -e'), True)
check("the dispatch gate asked about OK-WW is not OK-WW",
      is_okww(r'"C:\Python314\python.exe" C:\ark\scripts\dispatch_guard.py start OK-WW'), False)
check("...nor a python that only names it in lower case",
      is_okww(r'"C:\Python314\python.exe" C:\tools\note.py ok-ww'), False)
check("...nor the relay itself",
      is_okww(r'"C:\ark-relay\python\pythonservice.exe" C:\ark-relay\service.py'), False)
estop = (Path(__file__).resolve().parents[2] / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8")
check("the emergency stop's python filter is the folder too",
      re.findall(r'CommandLine -like "([^"]*)"', estop), [r"*\ok-ww\*"])

print("[an unreadable list is None (unknown), never [] (none left)]")
# 2026-10-13 review: pwsh started, the query failed, stdout was empty - and empty
# read as "no OK-WW running", so the relaunch went ahead and game_alive said clean.


class Done:
    def __init__(self, rc, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = rc, out, err


real_py = P._okww_py
cases = [
    ("nothing running: empty output, exit 0, no error", Done(0), []),
    ("one running", Done(0, b'{"ProcessId":4242}'), [4242]),
    ("two running", Done(0, b'[{"ProcessId":1},{"ProcessId":2}]'), [1, 2]),
    ("the query failed: exit 1, empty output", Done(1, b"", b"Get-CimInstance : Invalid class"), None),
    ("an error on stderr with empty output, exit 0", Done(0, b"", b"Get-CimInstance : Access denied"), None),
    ("a nonzero exit even with output", Done(1, b'{"ProcessId":4242}'), None),
    ("pwsh did not run at all", None, None),
]
try:
    for label, done, want in cases:
        P._okww_py = lambda tail, d=done: d
        check(label, P.okww_python_pids(), want)
finally:
    P._okww_py = real_py

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
