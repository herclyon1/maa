"""dispatch_guard.py must not read "cannot ask" as "nothing there".

Silent-failure audit rows:
* scripts/windows/dispatch_guard.py:98 - live_tasks returned [] when AUTO-MAS's
  runtime-snapshot was unreachable, timed out or not JSON. stop then printed
  「AUTO-MAS 没有在跑的任务」 and went straight to taskkill: the 2026-09-01 chain
  (taskkill read as a crash, AUTO-MAS retries the queue) the module exists to
  prevent.
* scripts/windows/dispatch_guard.py:164 - a corrupt test-windows.json read as
  "no window open": test-status exited 0 and test_on overwrote the history.
"""
import contextlib
import io
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay" / "tests"))
sys.path.insert(0, str(ROOT / "scripts" / "windows"))
import dispatch_guard as g  # noqa: E402
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Answer:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body


def quiet(fn, *a):
    """(value or SystemExit code, stdout) of fn(*a)."""
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            got = fn(*a)
    except SystemExit as e:
        got = ("exit", e.code)
    return got, out.getvalue()


REFUSED = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
SNAP_EMPTY = json.dumps({"tasks": []}).encode()
SNAP_MAA = json.dumps({"tasks": [{"taskId": "t1", "task_info": [{"name": "MAA"}]}]}).encode()


def snapshots(*answers):
    """urlopen answering the runtime-snapshot with each item in turn (the last one repeats);
    an exception item is raised."""
    left = list(answers)

    def urlopen(*a, **k):
        item = left.pop(0) if len(left) > 1 else left[0]
        if isinstance(item, BaseException):
            raise item
        return Answer(item)
    return urlopen


print("[live_tasks: cannot ask is None, nothing running is []]")
g.urllib.request.urlopen = snapshots(REFUSED)
check("connection refused -> None", quiet(g.live_tasks)[0], None)
g.urllib.request.urlopen = snapshots(TimeoutError("timed out"))
check("timeout -> None", quiet(g.live_tasks)[0], None)
g.urllib.request.urlopen = snapshots(b"<html>not json</html>")
check("not JSON -> None", quiet(g.live_tasks)[0], None)
g.urllib.request.urlopen = snapshots(SNAP_EMPTY)
check("an empty snapshot -> []", quiet(g.live_tasks)[0], [])


def stop_with(urlopen, running_seq):
    """stop_all with the snapshot answered by `urlopen` and running() giving `running_seq` in turn."""
    kills = []
    runs = list(running_seq)
    g.urllib.request.urlopen = urlopen
    g.running = lambda: runs.pop(0) if len(runs) > 1 else runs[0]
    g.post = lambda *a, **k: {"message": "操作成功"}
    g.subprocess.run = lambda args, **k: kills.append(args)
    g.okww_pids = lambda: []
    g.time.sleep = lambda s: None
    ok, out = quiet(g.stop_all)
    return ok, out, [k for k in kills if k and k[0] == "taskkill"]


print("[stop with AUTO-MAS unreachable and MAA still up: no taskkill]")
ok, out, kills = stop_with(snapshots(REFUSED), [(["MAA"], [])])
check("no taskkill was run", kills, [])
check("stop_all reports failure", ok, False)
check("it does not claim nothing is running", "没有在跑的任务" in out, False)
check("it says why it refused to kill", "不 taskkill" in out, True)

print("[the 12 s recheck cannot ask: still no taskkill]")
ok, out, kills = stop_with(snapshots(SNAP_MAA, REFUSED), [(["MAA"], [])])
check("no taskkill after a failed recheck", kills, [])
check("stop_all reports failure after a failed recheck", ok, False)

print("[AUTO-MAS answered nothing running and a game is left: taskkill as before]")
ok, out, kills = stop_with(snapshots(SNAP_EMPTY), [([], ["Endfield"]), ([], [])])
check("taskkill was run", len(kills) > 0, True)
check("stop_all reports clean after taskkill", ok, True)

print("[AUTO-MAS unreachable but nothing running: clean]")
ok, out, kills = stop_with(snapshots(REFUSED), [([], [])])
check("no taskkill when nothing runs", kills, [])
check("stop_all reports clean when nothing runs", ok, True)

print("[a corrupt test-windows.json is not 'no window open']")
d = tmpdir()
g.TEST_WINDOWS = str(d / "test-windows.json")
check("missing file: test-status says closed (exit 0)", quiet(g.test_status)[0], 0)
Path(g.TEST_WINDOWS).write_text('[{"since": "2026-10-10T01:00:00+08:00", "until": nu', encoding="utf-8")
before = Path(g.TEST_WINDOWS).read_bytes()
got, out = quiet(g.test_status)
check("test-status exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
check("it does not print the closed status line", "测试窗口：没开" in out, False)
got, out = quiet(g.test_on, "MAA")
check("test_on exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
got, out = quiet(g.test_off)
check("test_off exits non-zero", isinstance(got, tuple) and got[1] not in (0, None), True)
check("the file is untouched", Path(g.TEST_WINDOWS).read_bytes(), before)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
