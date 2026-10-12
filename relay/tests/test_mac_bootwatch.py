"""scripts/mac/bootwatch.py: the machine not reachable at shift time rings the group.

Until 2026-10-12 nothing off the machine noticed a shift where it never powered on
(the GitHub watchdog has no Tailscale key and stayed disabled); the relay only saw it
at the next boot. The owner, 20:04: an error left unreported is worse than the error.
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("bootwatch", ROOT / "scripts" / "mac" / "bootwatch.py")
bw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bw)

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


d = tmpdir()
bw.LOG = d / "bootwatch.log"
bw.PAUSE_FILE = d / "watchdog.json"
BJ = timezone(timedelta(hours=8))
pushed = []


def push(title, body):
    pushed.append(title)
    return True


morning = datetime(2026, 10, 13, 9, 5, tzinfo=BJ)
evening = datetime(2026, 10, 13, 21, 35, tzinfo=BJ)

print("\n[machine up: no push, one log line]")
check("up", bw.judge(morning, lambda: True, push=push), "up")
check("nothing pushed", pushed, [])
check("logged", "早班: 游戏机在线" in bw.LOG.read_text(encoding="utf-8"))

print("\n[machine down at the evening shift: the group]")
check("alarmed", bw.judge(evening, lambda: False, push=push), "alarmed")
check("title names the shift", pushed, ["🔌 游戏机晚班到点没开机"])

print("\n[paused for maintenance: not pushed, still logged]")
pushed.clear()
bw.PAUSE_FILE.write_text(json.dumps({"pause_until": "2026-10-13"}), encoding="utf-8")
check("paused", bw.judge(morning, lambda: False, push=push), "paused")
check("nothing pushed", pushed, [])
check("pause ended the day before: rings", (bw.judge(morning + timedelta(days=1), lambda: False, push=push), pushed),
      ("alarmed", ["🔌 游戏机早班到点没开机"]))

print("\n[an unreadable pause file never silences it]")
pushed.clear()
bw.PAUSE_FILE.write_text("{not json", encoding="utf-8")
check("rings", bw.judge(morning, lambda: False, push=push), "alarmed")

print("\n[the push itself failed: exit non-zero, logged]")
check("push-failed", bw.judge(morning, lambda: False, push=lambda t, b: False), "push-failed")
check("logged as failed", "报群失败" in bw.LOG.read_text(encoding="utf-8"))

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
