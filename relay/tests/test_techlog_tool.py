"""scripts/mac/techlog.py reads the technical log right and never reports a failed read as clean.

The tool runs as a subprocess against a fake winrun (TECHLOG_WINRUN) that runs the
generated `--py` scripts locally, with an arklog shim whose server_today() is the
fixed machine date 2026-10-10 and whose RELAY_LOG is a local file. So the read script
and the handled script really run: the first really reads the day files and relay.log
through arklog.since_minutes, the second really appends, and the re-read really decides.
"""
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay" / "tests"))
from _tmp import tmpdir  # noqa: E402

TOOL = ROOT / "scripts" / "mac" / "techlog.py"
spec = importlib.util.spec_from_file_location("techlog_tool", TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


FAKE = r'''
import json, os, subprocess, sys, time
from pathlib import Path
cfg = json.loads(Path(__file__).with_name("fake.json").read_text(encoding="utf-8"))
mode = cfg["mode"]
with open(cfg["log"], "a", encoding="utf-8") as fh:
    fh.write(repr(sys.argv[1:]) + "\n")
if mode == "down":
    sys.stderr.write("winrun: remote produced no output (script never ran, or machine unreachable)\n")
    sys.exit(4)
if mode == "hang":
    time.sleep(60)
if sys.argv[1] != "--py":
    sys.exit(9)
reading = "TECHLOG_DONE" in Path(sys.argv[2]).read_text(encoding="utf-8")
if mode == "pyfail" and not reading:
    sys.stderr.write("winrun: remote produced no output\n")
    sys.exit(4)
print("[机器时间] 10-10 23:00:00")
r = subprocess.run([sys.executable, sys.argv[2]], capture_output=True, text=True,
                   env=dict(os.environ, PYTHONPATH=cfg["shim"]))
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
'''

base = tmpdir()
fake = base / "fake_winrun.py"
fake.write_text(FAKE, encoding="utf-8")
tech = base / "tech"
tech.mkdir()
log = base / "calls.log"
relay_log = base / "relay.log"
relay_log.write_text("", encoding="utf-8")
shim = base / "shim"
shim.mkdir()
(shim / "arklog.py").write_text(
    "import importlib.util\nfrom datetime import date\n"
    f"spec = importlib.util.spec_from_file_location('_arklog', {str(ROOT / 'scripts' / 'mac' / 'lib' / 'arklog.py')!r})\n"
    "m = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n"
    "since_minutes = m.since_minutes\n"
    "def server_today():\n    return date(2026, 10, 10)\n"
    f"RELAY_LOG = {str(relay_log)!r}\n", encoding="utf-8")
BOOT = "服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）"
STOP = "收到停止信号，退出"
RET = "主流程已返回，向 SCM 报告已停止；还活着的线程：MainThread、phone-mailbox"


def relay_lines(events):
    """relay.log lines, [(seconds ago, message)], in the relay's own format, on this clock (arklog's)."""
    now = datetime.now()
    out = [(now - timedelta(seconds=150 * 60)).strftime("%m-%d %H:%M:%S") + " INFO    ark.service  next alarm"]
    for ago, msg in sorted(events, key=lambda e: -e[0]):
        out.append((now - timedelta(seconds=ago)).strftime("%m-%d %H:%M:%S") + f" INFO    ark.service  {msg}")
    relay_log.write_text("\n".join(out) + "\n", encoding="utf-8")


# The reachability probe connects here; a thread accepts and drops each connection.
listener = socket.create_server(("127.0.0.1", 0))
threading.Thread(target=lambda: [listener.accept()[0].close() for _ in iter(int, 1)], daemon=True).start()
REACHABLE = f"127.0.0.1:{listener.getsockname()[1]}"
with socket.create_server(("127.0.0.1", 0)) as _s:
    CLOSED = f"127.0.0.1:{_s.getsockname()[1]}"   # nothing listens here once it is closed


def run(*args, mode="ok", timeout="15", probe=REACHABLE):
    (base / "fake.json").write_text(json.dumps({"mode": mode, "log": str(log), "shim": str(shim)}),
                                    encoding="utf-8")
    env = dict(os.environ, TECHLOG_WINRUN=f"{sys.executable} {fake}", TECHLOG_REMOTE_DIR=str(tech),
               TECHLOG_FETCH_TIMEOUT=timeout, TECHLOG_PROBE=probe, TECHLOG_PROBE_TIMEOUT="1")
    r = subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env, timeout=60)
    return r.returncode, r.stdout, r.stderr


relay_lines([])   # a quiet hour: one line, older than the window

print("[no file on any of the three days: the relay has not written one yet]")
log.write_text("")
rc, out, err = run("red")
check("exit code", rc, 0)
check("says there is no technical log yet", out.splitlines(),
      [f"{tool.NO_LOG}（2026-10-08..2026-10-10 机器上都没有文件）"])
check("one round trip", len(log.read_text().splitlines()), 1)

print("[red items over two days, one handled in the later day's file]")
(tech / "2026-10-09.md").write_text(
    "\n## 23:00 收工体检\n🔴 R-20261009-2300-1 自检没过：补丁不在\n🔴 R-20261009-2300-2 关机没成功\n",
    encoding="utf-8")
(tech / "2026-10-10.md").write_text(
    "\n## 09:00 处理\n✅ R-20261009-2300-1 已处理（abc1234）\n"
    "\n## 23:00 收工体检\n🔴 R-20261010-2300-1 relay.log 有 ERROR\n", encoding="utf-8")
rc, out, err = run("red")
check("exit code", rc, 0)
check("only the unhandled items, with the day of their red line", out.splitlines(),
      ["R-20261009-2300-2\t2026-10-09\t关机没成功", "R-20261010-2300-1\t2026-10-10\trelay.log 有 ERROR"])
rc, out, err = run("red", "--days", "1")
check("--days 1 reads the machine's today only", out.splitlines(),
      ["R-20261010-2300-1\t2026-10-10\trelay.log 有 ERROR"])
rc, out, err = run("red", "--days", "0")
check("--days 0 is refused", rc, 1)

print("[read failure]")
rc, out, err = run("red", mode="down")
check("exit code", rc, 2)
check("one 没读到 line naming why", out.splitlines(),
      ["技术日志没读到：最近 3 天（winrun: remote produced no output (script never ran, or machine unreachable)）"])
rc, out, err = run("red", "--days", "1", mode="hang", timeout="1")
check("a hung read: exit code", rc, 2)
check("a hung read: says it timed out", out.splitlines(), ["技术日志没读到：最近 1 天（超过 1 秒没回来）"])
locked = tech / "2026-10-08.md"
locked.write_text("x\n", encoding="utf-8")
locked.chmod(0)
try:
    rc, out, err = run("red")
    check("a day the machine cannot open: exit code", rc, 2)
    check("a day the machine cannot open: named", out.splitlines(),
          ["技术日志没读到：最近 3 天（2026-10-08（PermissionError））"])
finally:
    locked.chmod(0o644)
    locked.unlink()

print("[machine unreachable: one fast line, exit 3, nothing else tried]")
for label, probe in (("refused", CLOSED), ("no answer", "203.0.113.1:22")):
    log.write_text("")
    t0 = time.monotonic()
    rc, out, err = run("red", mode="hang", probe=probe)
    took = time.monotonic() - t0
    check(f"{label}: exit code", rc, 3)
    check(f"{label}: the one line", out.startswith("游戏机现在连不上（关机或断网）：") and len(out.splitlines()) == 1, True)
    check(f"{label}: fast (the hanging read was never started)", (took < 5, log.read_text()), (True, ""))
rc, out, err = run("handled", "R-20261010-2300-1", "def5678", probe=CLOSED)
check("handled while unreachable: exit code", rc, 3)

print("[show]")
rc, out, err = run("show", "2026-10-09")
check("show prints the file", out, (tech / "2026-10-09.md").read_text(encoding="utf-8"))
rc, out, err = run("show", "2026-10-01")
check("show of a missing day: exit code", rc, 0)
check("show of a missing day: says so", out.strip(), f"{tool.NO_LOG}（2026-10-01 机器上没有这天的文件）")
rc, out, err = run("show", "2026-10-11")
check("show of a day after the machine's today: exit code", rc, 1)
rc, out, err = run("show", "2026-13-01")
check("show of an impossible date: exit code", rc, 1)
rc, out, err = run("show", "2026-10-09", mode="down")
check("show when the read fails: exit code", rc, 2)

print("[handled]")
log.write_text("")
before = (tech / "2026-10-10.md").read_text(encoding="utf-8")
rc, out, err = run("handled", "R-20261010-2300-1", "def5678")
check("exit code", rc, 0)
check("confirmed", out.strip(), "已标处理：R-20261010-2300-1（def5678），复查确认")
after = (tech / "2026-10-10.md").read_text(encoding="utf-8")
check("exactly the handled line was appended", after[len(before):],
      tool.handled_line("R-20261010-2300-1", "def5678") + "\n")
check("no command line carried Chinese", all(ln.isascii() for ln in log.read_text(encoding="utf-8").splitlines()), True)
check("read, write, re-read: three round trips", len(log.read_text().splitlines()), 3)
rc, out, err = run("red")
check("red no longer lists it", out.splitlines(), ["R-20261009-2300-2\t2026-10-09\t关机没成功"])

rc, out, err = run("handled", "R-20261010-2300-1", "def5678")
check("marking it again: exit code", rc, 0)
check("marking it again: nothing appended", (tech / "2026-10-10.md").read_text(encoding="utf-8"), after)

rc, out, err = run("handled", "R-20261010-0000-9", "def5678")
check("an id that is not in the log: exit code", rc, 1)
check("an id that is not in the log: file untouched", (tech / "2026-10-10.md").read_text(encoding="utf-8"), after)
rc, out, err = run("handled", "R-20261011-0000-1", "def5678")
check("an id dated after the machine's today: exit code", rc, 1)
rc, out, err = run("handled", "R-20261010-2300-1", "bad commit")
check("a malformed commit: exit code", rc, 1)

rc, out, err = run("handled", "R-20261009-2300-2", "def5678", mode="pyfail")
check("a write that fails: exit code", rc, 1)
check("a write that fails: says the re-check did not pass", "复查没过" in err, True)

rc, out, err = run("handled", "R-20261009-2300-2", "def5678", mode="down")
check("handled while the read fails: exit code", rc, 2)

rc, out, err = run("handled", "R-20261009-2300-2", "def5678")
check("handled into the red line's file: exit code", rc, 0)
check("the line landed in 2026-10-09.md", (tech / "2026-10-09.md").read_text(encoding="utf-8").splitlines()[-1],
      tool.handled_line("R-20261009-2300-2", "def5678"))
rc, out, err = run("red")
check("nothing red left: files exist, stdout empty", (rc, out), (0, ""))

print("[relay crash-restart loop, read live from relay.log]")
for f in tech.glob("*.md"):
    f.unlink()
# 2026-10-10 16:27:59 stop, then 16 boots 18-20 s apart with no stop between (16:28:03 .. 16:32:46),
# then a clean stop and boot at 16:33:03 - as read from the machine's relay.log. Placed 20 minutes ago.
gaps = [18, 19, 20, 22, 19, 18, 18, 20, 18, 17, 19, 19, 19, 18, 19]
t, loop = 20 * 60, [(20 * 60 + 4, STOP), (20 * 60 + 4, RET), (20 * 60, BOOT)]
for g in gaps:
    t -= g
    loop.append((t, BOOT))
loop += [(t - 17, STOP), (t - 17, RET), (t - 17.5, BOOT)]
relay_lines(loop)
rc, out, err = run("red")
check("exit code", rc, 0)
check("a live red item, and no 'no log yet' line beside it", out.splitlines(),
      ["R-LIVE-restarts\t2026-10-10\t中继最近 60 分钟重启了 17 次，其中 15 次不是正常停止"])

# Deploy restarts: stop lines before each boot. One of them shaped like 16:59:15-16:59:30 (a second boot 12 s later).
relay_lines([(50 * 60, STOP), (50 * 60, RET), (50 * 60 - 3, BOOT),
             (40 * 60, STOP), (40 * 60, RET), (40 * 60 - 3, BOOT), (40 * 60 - 15, BOOT),
             (30 * 60, STOP), (30 * 60, RET), (30 * 60 - 3, BOOT),
             (10 * 60, STOP), (10 * 60, RET), (10 * 60 - 5, BOOT)])
rc, out, err = run("red")
check("deploy restarts: nothing red", (rc, out.startswith(tool.NO_LOG)), (0, True))
check("deploy restarts: the summary counts them", "restarts in the last 60 min: 5 (1 without a stop)" in err, True)

relay_lines([(80 * 60 - 20 * i, BOOT) for i in range(10)])
rc, out, err = run("red")
check("a loop that ended before the window: nothing red", (rc, out.startswith(tool.NO_LOG)), (0, True))
rc, out, err = run("handled", "R-LIVE-restarts", "def5678")
check("a live item cannot be marked handled", rc, 1)

print("[the generated scripts pass winrun's send gates]")
gens = {
    "techlog_read.py": tool.READ_SCRIPT.format(tech_dir=tool.REMOTE_DIR, first=None, back=2, max_days=tool.MAX_DAYS,
                                               live=True, wide=75, narrow=60),
    "techlog_handled.py": tool.WRITE_SCRIPT.format(tech_dir=tool.REMOTE_DIR, day="2026-10-10",
                                                   line=tool.handled_line("R-20261010-2300-1", "def5678")),
}
for name, text in gens.items():
    gen = base / name
    gen.write_text(text, encoding="utf-8")
    compile(text, str(gen), "exec")
    r = subprocess.run([str(ROOT / "scripts" / "mac" / "winrun.sh"), "--py", str(gen)], capture_output=True, text=True,
                       env=dict(os.environ, WINRUN_DRY_RUN="1"), timeout=30)
    check(f"{name}: winrun dry run lets it through", (r.returncode, "dry-run" in r.stdout), (0, True))

print("[the format matches the relay's writer, when it is on this branch]")
writer = ROOT / "relay" / "ark_relay" / "techlog.py"
if writer.is_file():
    src = writer.read_text(encoding="utf-8")
    check("RED_LINE", f'RED_LINE = re.compile(r"{tool.RED_LINE.pattern}")' in src, True)
    check("DONE_LINE", f'DONE_LINE = re.compile(r"{tool.DONE_LINE.pattern}")' in src, True)
    m = re.search(r'return f"\{DONE\} \{item_id\} (.*)"', src)
    check("handled_line", m and tool.handled_line("X", "Y") == f"✅ X {m.group(1)}".replace("{commit}", "Y"), True)
else:
    print("  - relay/ark_relay/techlog.py is not on this branch yet; compared once it lands")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
