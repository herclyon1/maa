"""maaend_task.py must not exit 0 when the run timed out or the agent did not stop.

Silent-failure audit row scripts/mac/lib/maaend_task.py:92: 「停 agent 失败」 was
printed and main still returned 0, as did the timeout path, so a chained `&&`
or any caller saw success while the MaaEnd agent might still be running.
"""
import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
import maaend_task as mt  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def run(agent_stop_fails, still_running):
    calls = []

    def api(path, body=None, timeout=30):
        calls.append(path)
        if path == "/maa/state":
            return {"instances": {"i1": {"connected": True, "resource_loaded": True,
                                         "is_running": still_running}}}
        if path.endswith("/agent/stop") and agent_stop_fails:
            raise OSError("connection reset")
        return {"ok": True}

    mt.api = api
    mt.preflight = lambda: ({"i1": {"connected": True, "resource_loaded": True}}, [])
    mt.pick_instance = lambda inst: "i1"
    mt.ensure_resource = lambda k: None
    mt.time.sleep = lambda s: None
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = mt.main(["maaend_task.py", "--entry", "E", "--go", "--timeout", str(1 if not still_running else 0)])
    return rc, out.getvalue(), calls


print("[the run finished, agent stopped]")
rc, out, calls = run(agent_stop_fails=False, still_running=False)
check("exit 0", rc, 0)
check("agent stop was asked", "/maa/instances/i1/agent/stop" in calls, True)

print("[the run finished, agent stop failed]")
rc, out, _ = run(agent_stop_fails=True, still_running=False)
check("the failure is printed", "停 agent 失败" in out, True)
check("exit non-zero after a failed agent stop", rc, 1)

print("[the run timed out]")
rc, out, calls = run(agent_stop_fails=False, still_running=True)
check("the task was stopped", "/maa/instances/i1/tasks/stop" in calls, True)
check("exit non-zero after a timeout", rc, 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
