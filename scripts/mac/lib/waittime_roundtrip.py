"""Live check that commands._set_wait_time goes through the AUTO-MAS API and touches nothing else.

    scripts/mac/winrun.sh --py scripts/mac/lib/waittime_roundtrip.py
    (normally through: scripts/mac/boot-check.py --wtest)

THIS WRITES CONFIG: MaaEnd's Game/WaitTime is set to its current value + 1 and
then back, both through the relay's own _set_wait_time. It refuses to run while
anything is busy - AUTO-MAS reporting a task (the relay's own Engine check), any
BUSY_PROCS process, or OK-WW's python - and when it cannot tell.

Prints one line `WTEST_JSON=<ascii json>`: busy, before, up/back [ok, message, ms],
diff_up / diff_end (flattened /<sid>/... paths whose value changed), new_bak
(ScriptConfig.json.bak-* files that appeared), file mtimes.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

R = Path(r"C:\ProgramData\ark-relay")
sys.path.insert(0, str(R))
from ark_relay.__main__ import _load_dotenv  # noqa: E402

_load_dotenv(R / ".env")
from ark_relay import commands as c  # noqa: E402
from ark_relay import procs  # noqa: E402
from ark_relay.config import BUSY_PROCS, OKWW_CMDLINE  # noqa: E402
from ark_relay.engine import Engine  # noqa: E402


def busy_now() -> list:
    busy = []
    if Engine._scripts_running():
        busy.append("AUTO-MAS 或进程表说有任务在跑")
    try:
        tl = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                            timeout=20).stdout.decode("utf-8", "replace").lower()
    except (OSError, subprocess.SubprocessError):
        return busy + ["进程表读不到"]
    busy += [n for n in BUSY_PROCS if n.lower() in tl]
    py = procs.python_processes()
    if py is None:
        busy.append("python 进程表读不到（看不出 OK-WW 在不在跑）")
    elif any(OKWW_CMDLINE in cmd.lower() for _, cmd in py):
        busy.append("OK-WW (python)")
    return busy


def flat(o, p=""):
    r = {}
    if isinstance(o, dict):
        for k, v in o.items():
            r.update(flat(v, p + "/" + k))
    else:
        r[p] = o
    return r


out = {"busy": busy_now()}
if out["busy"]:
    print("WTEST_JSON=" + json.dumps(out, ensure_ascii=True))
    sys.exit(0)
sc = Path(os.environ["ARK_AUTOMAS_DIR"]) / "config" / "ScriptConfig.json"


def snap():
    d = c._mas("/api/scripts/get")["data"]
    return d, sc.stat().st_mtime, sorted(p.name for p in sc.parent.glob("ScriptConfig.json.bak-*"))


d0, m0, b0 = snap()
sid = next(k for k, v in d0.items() if v["Info"]["Name"].lower() == "maaend")
out["sid"] = sid
cur = d0[sid]["Game"]["WaitTime"]
out["before"] = cur
t = time.time()
ok1, msg1 = c._set_wait_time(cur + 1)
out["up"] = [ok1, msg1, round((time.time() - t) * 1000)]
d1, m1, b1 = snap()
t = time.time()
ok2, msg2 = c._set_wait_time(cur)
out["back"] = [ok2, msg2, round((time.time() - t) * 1000)]
d2, m2, b2 = snap()
f0, f1, f2 = flat(d0), flat(d1), flat(d2)
out["diff_up"] = {k: [f0.get(k), f1.get(k)] for k in set(f0) | set(f1) if f0.get(k) != f1.get(k)}
out["diff_end"] = {k: [f0.get(k), f2.get(k)] for k in set(f0) | set(f2) if f0.get(k) != f2.get(k)}
out["file_mtime"] = [time.strftime("%H:%M:%S", time.localtime(x)) for x in (m0, m1, m2)]
out["new_bak"] = sorted(set(b2) - set(b0))
out["file_waittime_after_restore"] = (json.loads(sc.read_text(encoding="utf-8"))
                                      .get(sid, {}).get("Game", {}).get("WaitTime"))
print("WTEST_JSON=" + json.dumps(out, ensure_ascii=True))
