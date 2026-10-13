"""OK-WW's python check on a phone publish: cached, and never asked by the stop push.

snapshot._runtime asked redbutton._okww_python_alive on every publish (f6a8e515);
an unreadable process list retries 3 x 3 s (procs.python_processes), so the
停止前 push, which must land inside SvcStop's 15 s timer, could stall 6 s+.
Now one answer serves snapshot.OKWW_ALIVE_TTL seconds, and the 停止前 / 关机前
pushes (phone.send_state) never ask: they report the last answer, or 「没查」.
"""
import contextlib
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.phone import phone, redbutton, snapshot

# getattr: on the old code (no cache) the test reaches its assertions and fails there.
CACHE = getattr(snapshot, "_okww_alive", {"at": 0.0, "alive": None})
TTL = getattr(snapshot, "OKWW_ALIVE_TTL", 30.0)
NO_QUERY = getattr(snapshot, "no_process_query", contextlib.nullcontext)

fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


asked = []


def fake_alive():
    asked.append(1)
    return True


class Box:
    last_error = ""
    quota = types.SimpleNamespace(total=lambda: 0)

    def publish(self, payload):
        return True


def tmp():
    return tempfile.mkdtemp()


cfg = types.SimpleNamespace(automas_dir=tmp(), maaend_dir=tmp(), okww_dir=tmp(), state_dir=tmp())
saved = (redbutton._okww_python_alive, subprocess.run, dict(CACHE))
redbutton._okww_python_alive = fake_alive
subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout="", stderr="", returncode=0)
try:
    print("\n[30 秒内两次上报只查一次鸣潮脚本的 python]")
    CACHE.update(at=None, alive=None)
    a = snapshot.read_runtime()
    b = snapshot.read_runtime()
    check("查了一次", len(asked), 1)
    check("两次都报鸣潮脚本在跑", [a["程序"].get("ok-ww"), b["程序"].get("ok-ww")], [True, True])

    print("\n[停止前那份不查，报上次的结果]")
    asked.clear()
    CACHE["at"] = (CACHE["at"] or 0.0) - TTL - 1    # the cached answer is stale
    ok, payload, _ = phone.send_state(Box(), cfg, "停止前")
    check("送到了", ok, True)
    check("停止前没查", len(asked), 0)
    check("停止前报上次的结果", "ok-ww" in (payload.get("run") or {}).get("在跑的", []), True)

    print("\n[关机前一次都没查过：不查，写「没查」]")
    CACHE.update(at=None, alive=None)
    phone.send_state(Box(), cfg, "关机前")
    check("关机前没查", len(asked), 0)
    with NO_QUERY():
        check("没查过时写「没查」", snapshot.read_runtime().get("OK-WW python"), "没查")

    print("\n[普通上报过期了照常再查]")
    phone.send_state(Box(), cfg, "刷新")
    check("刷新查了一次", len(asked), 1)
finally:
    redbutton._okww_python_alive, subprocess.run = saved[0], saved[1]
    CACHE.clear()
    CACHE.update(saved[2])

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall passed")
