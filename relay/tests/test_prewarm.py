"""MaaEnd checks for updates at startup and restarts itself when it finds one,
which kills the round AUTO-MAS just launched. The warm-up moves that check into
the boot-to-queue gap. These cover the decision logic and the log parsing - the
launching itself is Windows-only.
"""
import json, os, sys, tempfile, time
from datetime import datetime
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
MAAEND = TMP / "MaaEnd"; (MAAEND / "debug").mkdir(parents=True)

def write_schedule(*queues):
    """queues: (name, time, [script kinds])"""
    q, s, insts, sinsts = {}, {}, [], []
    for i, (name, t, kinds) in enumerate(queues):
        quid = f"q{i}"
        insts.append({"uid": quid})
        items = {}
        for j, kind in enumerate(kinds):
            suid = f"s{i}{j}"
            sinsts.append({"uid": suid})
            path = str(MAAEND) if kind == "MaaEnd" else "D:\\MAA-v5.1.0-win-x64"
            s[suid] = {"Info": {"Name": kind, "Path": path},
                       "SubConfigsInfo": {"UserData": {}}}
            items[f"i{j}"] = {"Info": {"ScriptId": suid}}
        q[quid] = {"Info": {"Name": name, "TimeEnabled": True},
                   "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                      "QueueItem": items}}
    q["instances"] = insts; s["instances"] = sinsts
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(q), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(s), encoding="utf-8")

os.environ.update(ARK_HISTORY_DIR=str(TMP), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import prewarm            # noqa: E402
from ark_relay.config import SERVER_TZ   # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

def at(hh, mm):
    return datetime(2026, 8, 22, hh, mm, tzinfo=SERVER_TZ)

print("[when to warm up]")
write_schedule(("新队列", "09:00", ["MAA", "MaaEnd"]),
               ("Evening-MAA", "21:30", ["MAA"]))
check("08:47, morning queue still ahead", prewarm.wanted_today(AUTOMAS, at(8, 47)), True)
check("21:22, only MAA left tonight",     prewarm.wanted_today(AUTOMAS, at(21, 22)), False)
check("11:00, morning queue已过",          prewarm.wanted_today(AUTOMAS, at(11, 0)), False)

write_schedule(("Evening-Both", "21:30", ["MAA", "MaaEnd"]))
check("evening queue does run MaaEnd",    prewarm.wanted_today(AUTOMAS, at(21, 22)), True)

write_schedule(("新队列", "09:00", ["MAA"]))
check("no MaaEnd anywhere",               prewarm.wanted_today(AUTOMAS, at(8, 47)), False)
check("no AUTO-MAS dir",                  prewarm.wanted_today(None, at(8, 47)), False)

print("\n[reading MaaEnd's own log]")
def log_line(name, body):
    p = MAAEND / "debug" / name
    p.write_text(body, encoding="utf-8")
    os.utime(p, (time.time(), time.time()))
    return p

log_line("2026-08-22-1.log", "old session\n")
time.sleep(0.05)
check("newest log picked", prewarm._newest_log(MAAEND).name, "2026-08-22-1.log")

# The regexes must match the real lines, copied verbatim from the machine.
real = ("2026-08-22 11:49:39 INFO  [App] 检测到刚更新完成: v2.26.0-beta.1\n"
        "2026-08-22 11:49:40 INFO  [App] 更新检查完成: 最新版本=v2.26.0-beta.1, 有更新=false\n")
check("updated-to parsed", bool(prewarm._UPDATED.search(real)), True)
check("version captured",  prewarm._UPDATED.search(real).group(1), "v2.26.0-beta.1")
m = prewarm._DONE.search(real)
check("settled parsed",    bool(m), True)
check("has_update false",  m.group(2), "false")

mid = "2026-08-22 09:00:00 INFO  [App] 更新检查完成: 最新版本=v2.27.0, 有更新=true\n"
check("still downloading", prewarm._DONE.search(mid).group(2), "true")

print("\n[failure is cheap]")
check("no maaend dir -> no-op", prewarm.run(None), "")
check("missing exe -> no-op",   prewarm.run(MAAEND, budget_s=1), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
