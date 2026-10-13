"""install() leaves ok_tasks/ark_overrides.py alone unless it must change, and never
rewrites it under a running OK-WW (audit 2026-10-13, A2).

ok-script watches ok_tasks/ while OK-WW runs and executes again any .py there that
changes (ok-script task_manager.py _on_debug_dir_changed, which hands a file it has
not recorded as a task to load_single_user_task). Executing the overrides twice
wraps our wrappers again. So:

* identical bytes -> nothing is written and no process list is asked for;
* different bytes while OK-WW runs -> not written, a logged line says so;
* different bytes and OK-WW not running, or no way to tell -> written.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core import procs, texts
from ark_relay.core import config as C
from ark_relay.features.okww_patch import okww_overlay as ov
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


REAL_RUNNING = getattr(ov, "okww_running", None)
asked = []


def running(answer):
    def f():
        asked.append(answer)
        return answer
    return f


WANT = ov.source_text().encode("utf-8")

print("[CRLF copy on disk (same text, other bytes): rewritten to the exact bytes]")
root = tmpdir()
dest = ov.target(root)
dest.parent.mkdir(parents=True)
dest.write_bytes(WANT.replace(b"\n", b"\r\n"))
ov.okww_running = running(False)
try:
    line = ov.install(root)
    check("rewritten", dest.read_bytes(), WANT)
    check("says where", "ok_tasks" in line)

    print("\n[identical bytes: nothing written, no process list asked for]")
    asked.clear()
    os.utime(dest, (1_000_000_000, 1_000_000_000))
    check("returns ''", ov.install(root), "")
    check("process list not asked", asked, [])
    check("file not touched (mtime kept)", int(dest.stat().st_mtime), 1_000_000_000)

    print("\n[different bytes while OK-WW runs: left alone, a logged line]")
    dest.write_bytes(b"# an older overlay\n")
    ov.okww_running = running(True)
    line = ov.install(root)
    check("file unchanged", dest.read_bytes(), b"# an older overlay\n")
    check("says OK-WW is running", "正在运行" in line)
    check("not a fault: 🩹 title", texts.patches(1, [line]).startswith("🩹"))

    print("\n[different bytes, cannot tell whether OK-WW runs: written]")
    ov.okww_running = running(None)
    ov.install(root)
    check("written", dest.read_bytes(), WANT)
finally:
    ov.okww_running = REAL_RUNNING

print("\n[okww_running: pythonw.exe with ok-ww on its command line is OK-WW]")
real_pp, real_win = procs.python_processes, C.IS_WINDOWS
seen = {}


def pp(rows):
    def f(**kw):
        seen.update(kw)
        return rows
    return f


try:
    C.IS_WINDOWS = True
    procs.python_processes = pp([(1, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                                 (2, r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe "
                                     r"D:\ark\okww\data\apps\ok-ww\working\main.py -t 1 -e")])
    check("OK-WW up", ov.okww_running(), True)
    check("asks for python.exe and pythonw.exe", seen.get("hosts"), C.PYTHON_HOSTS)
    check("leaves the outage alarm to the boot self-check", seen.get("warn"), False)
    procs.python_processes = pp([(1, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py")])
    check("only AUTO-MAS: not up", ov.okww_running(), False)
    procs.python_processes = pp(None)
    check("list unreadable: cannot tell", ov.okww_running(), None)
finally:
    C.IS_WINDOWS = real_win
    procs.python_processes = real_pp
check("not Windows: cannot tell", ov.okww_running(), None)

print("\n[procs.python_processes(hosts=...) queries every host name]")
queries = []
real_q = procs._query_once
procs._query_once = lambda query=procs._QUERY: (queries.append(query), ([], ""))[1]
try:
    procs.python_processes(hosts=C.PYTHON_HOSTS)
    procs.python_processes()
finally:
    procs._query_once = real_q
check("pythonw.exe and python.exe both in the query",
      bool(queries) and "Name='pythonw.exe'" in queries[0] and "Name='python.exe'" in queries[0])
check("the default query is unchanged", queries[1:], [procs._QUERY])

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
