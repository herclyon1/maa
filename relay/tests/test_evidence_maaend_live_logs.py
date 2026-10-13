"""A MaaEnd bundle keeps the logs that were still being written at the end of its window.

The case is 2026-10-12 (ledger-2026-10-12.jsonl): MaaEnd-06-04-00 failed, run
10:05:05-10:58:09 (+08:00); its retry MaaEnd-06-58-38 ran 10:59:40-11:38:12 and
kept writing the same logs, so when the bundle was built at 11:38:15 maafw.log,
the MXU day log, go-service.log and mxu-tauri.log all had mtimes near 11:38,
past t1 = 11:03:09. The old rule (mtime inside the window) dropped every one of
them and shipped only the config and the screenshot (audit s17 F1).

The file layout below mirrors the real debug/ tree of 2026-10-11 (staged copy
of MaaEnd-05-30-34): maafw rotates into maafw.bak.<time>.log, cpp-algo/debug
has its own maafw, go-service.log is JSON lines, mxu-tauri.log stamps
`[YYYY-MM-DD][HH:MM:SS]`. The first lines below are in those formats.
"""
import os
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

os.environ["TZ"] = "Asia/Shanghai"      # the machine's clock: MaaEnd stamps local Beijing time
time.tzset()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.features.evidence import evidence as ev  # noqa: E402
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def at(hms: str, day: str = "2026-10-12") -> float:
    return datetime.fromisoformat(f"{day}T{hms}+08:00").timestamp()


def maafw_lines(start: str, end: str, step_s: int = 60) -> str:
    out, t = [], at(start)
    while t <= at(end):
        s = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
        out.append(f"[{s}.000][DBG][Px9200][Tx16448][Logger] line {s}")
        t += step_s
    return "\n".join(out) + "\n"


root = tmpdir() / "maaend"
dbg = root / "debug"
(dbg / "on_error").mkdir(parents=True)
(dbg / "cpp-algo" / "debug").mkdir(parents=True)
(root / "config").mkdir()


def mk(rel: str, text: str, mtime: float) -> Path:
    p = root / rel
    p.write_text(text, encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


window = ev.run_window(datetime.fromisoformat("2026-10-12T10:05:05+08:00"),
                       datetime.fromisoformat("2026-10-12T10:58:09+08:00"))
check("t1 is the run's end plus the slack (11:03:09)", window[1], at("11:03:09"))

mk("config/mxu-MaaEnd.json", "{}", at("08:00:00", "2026-09-30"))
mk("debug/maafw.bak.2026.10.12-09.40.00.000.log", maafw_lines("09:20:00", "09:40:00"), at("09:40:00"))  # before t0: out
mk("debug/maafw.bak.2026.10.12-10.10.00.000.log", maafw_lines("09:40:00", "10:10:00"), at("10:10:00"))  # holds t0
mk("debug/maafw.bak.2026.10.12-10.30.00.000.log", maafw_lines("10:10:00", "10:30:00"), at("10:30:00"))  # in window
mk("debug/maafw.bak.2026.10.12-11.10.00.000.log", maafw_lines("10:30:00", "11:10:00"), at("11:10:00"))  # holds t1
mk("debug/maafw.bak.2026.10.12-11.25.00.000.log", maafw_lines("11:10:00", "11:25:00"), at("11:25:00"))  # retry only: out
mk("debug/maafw.log", maafw_lines("11:25:00", "11:38:00"), at("11:38:12"))                               # retry only: out
mk("debug/2026-10-12-3.log",
   "2026-10-12 09:58:00 INFO  [App] start\n2026-10-12 10:40:00 INFO  [App] mid\n"
   "2026-10-12 11:30:00 INFO  [App] retry\n", at("11:38:12"))                                          # still open: in
mk("debug/go-service.log",
   '{"level":"info","time":"2026-09-10T16:56:39+08:00","message":"MaaEnd Agent Service"}\n'
   '{"level":"info","time":"2026-10-12T10:40:00+08:00","message":"in the run"}\n'
   '{"level":"info","time":"2026-10-12T11:38:00+08:00","message":"Agent server shutdown"}\n',
   at("11:38:12"))                                                                                      # still open: in
mk("debug/mxu-tauri.log",
   "[2026-10-10][09:14:23][DEBUG][mxu_lib] old\n[2026-10-12][10:40:00][INFO][mxu_lib] in the run\n"
   "[2026-10-12][11:38:00][INFO][mxu_lib] retry\n", at("11:38:12"))                                     # still open: in
mk("debug/odd.log", "no stamps at all\njust text\n", at("11:38:12"))                                   # unreadable stamps: whole
mk("debug/cpp-algo/debug/maafw.log", maafw_lines("10:20:00", "11:38:00"), at("11:38:12"))               # subdir, still open: in
mk("debug/on_error/e.png", "png", at("10:50:00"))

print("[10-12 MaaEnd-06-04-00: the logs the retry kept writing stay in the bundle]")
got = [n for _, n in ev.maaend_entries(root, window)]
check("logs: the in-window bak, the bak holding t1, the open logs; not the retry-only ones",
      [n for n in got if n.endswith(".log")],
      ["2026-10-12-3.log", "go-service.log", "maafw.bak.2026.10.12-10.10.00.000.log",
       "maafw.bak.2026.10.12-10.30.00.000.log",
       "maafw.bak.2026.10.12-11.10.00.000.log", "mxu-tauri.log", "odd.log", "cpp-algo/debug/maafw.log"])
check("config and the screenshot still in", ("config/mxu-MaaEnd.json" in got, "on_error/e.png" in got), (True, True))

print("\n[the long ones are cut to the window when packed]")
parts = ev.bundle_maaend(root, tmpdir() / "out", "v2.28.0", window, datetime(2026, 10, 12, 11, 38, 15))
check("one volume", len(parts), 1)
with zipfile.ZipFile(parts[0]) as z:
    names = z.namelist()
    body = {n: z.read(n).decode("utf-8") for n in names if n.endswith(".log")}
check("same names in the archive", [n for n in names if n.endswith(".log")],
      [n for n in got if n.endswith(".log")])
gs = body.get("go-service.log", "")
check("go-service.log: the run's line kept, last month's and the retry's cut",
      ("in the run" in gs, "MaaEnd Agent Service" in gs, "shutdown" in gs), (True, False, False))
tauri = body.get("mxu-tauri.log", "")
check("mxu-tauri.log cut to the window", ("in the run" in tauri, "old" in tauri, "retry" in tauri), (True, False, False))
bak = body.get("maafw.bak.2026.10.12-11.10.00.000.log", "")
check("the bak holding t1 ends at t1", ("2026-10-12 11:03:00" in bak, "2026-10-12 11:04:00" in bak), (True, False))
check("the bak holding t1 keeps the run's part", "2026-10-12 10:30:00" in bak)
check("a log with no readable stamps goes in whole", body.get("odd.log"), "no stamps at all\njust text\n")
b0 = body.get("maafw.bak.2026.10.12-10.10.00.000.log", "")
check("the bak holding t0 starts at t0", ("2026-10-12 10:00:00" in b0, "2026-10-12 10:01:00" in b0), (False, True))
check("an in-window log goes in untouched",
      body.get("maafw.bak.2026.10.12-10.30.00.000.log"),
      (dbg / "maafw.bak.2026.10.12-10.30.00.000.log").read_text(encoding="utf-8"))
check("no slice files left beside the volumes", sorted(p.name for p in parts[0].parent.iterdir()),
      [parts[0].name])
src_size = (dbg / "go-service.log").stat().st_size
check("the source logs are not touched", ("MaaEnd Agent Service" in (dbg / "go-service.log").read_text(encoding="utf-8"),
                                          src_size > len(gs.encode())), (True, True))

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall passed")
