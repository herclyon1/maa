#!/usr/bin/env python3
"""Off-machine boot watch: the game machine did not come up for a shift -> the group.

"The machine never powered on" cannot be seen from inside the machine; the relay only
finds out at the next boot, half a day late. The GitHub watchdog that was meant to
catch it (scripts/watchdog.py, .github/workflows/watchdog.yml) needs a Tailscale OAuth
client that was never issued, so it has stayed disabled (queue/watchdog.json
"enabled": false). This Mac never sleeps (pmset SleepDisabled 1) and sits on the same
Tailscale network, so it asks the machine directly. One check per shift, no periodic
heartbeat (the owner's 2026-08-18 ruling, see scripts/watchdog.py).

launchd (scripts/mac/launchd/com.herclyon.ark-bootwatch.plist) runs it a few minutes
after each shift starts: boot 08:40 / 21:20 Beijing (modes.BOOT_TIMES), shift
09:00 / 21:30 (docs/CONFIG.md), check 09:05 / 21:35 Beijing = 10:05 / 22:35 Tokyo.
At that moment the machine must be on whatever the shift does.

    bootwatch.py            # judge now: reachable -> one log line; not -> group alarm
    bootwatch.py --dry-run  # judge and print, push nothing

The owner, 2026-10-12 20:04: an error left unreported is worse than the error.
Pausing (maintenance with the machine off on purpose): queue/watchdog.json
"pause_until": "YYYY-MM-DD" (Beijing date, inclusive) - the same key the GitHub
watchdog reads. A paused check still writes its log line.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER_TZ = timezone(timedelta(hours=8))
HOST = "100.65.39.119"
PORT = 22
# Measured: the machine's System log (event 12, kernel start) shows boots at 08:45:09,
# 08:45:11, 08:45:13 (10-10..10-12 mornings) and 21:20:10 (10-11 evening) - 20 and 15
# minutes before the checks below. So a failed connect is not a slow boot; the retries
# only absorb a network blip, and 4 tries 60 s apart still alarm within the shift's
# first 10 minutes.
TRIES = 4
GAP_S = 60
PY = str(Path.home() / ".local" / "bin" / "python3.14")
LOG = Path.home() / "Library" / "Logs" / "ark-bootwatch.log"
PAUSE_FILE = REPO / "queue" / "watchdog.json"
# Shift start (Beijing) -> name; the check belongs to the latest shift that started.
SHIFTS = (("09:00", "早班"), ("21:30", "晚班"))


def reachable() -> bool:
    for i in range(TRIES):
        r = subprocess.run(["nc", "-z", "-G", "5", HOST, str(PORT)],
                           capture_output=True, check=False)
        if r.returncode == 0:
            return True
        if i < TRIES - 1:
            time.sleep(GAP_S)
    return False


def paused(today: str) -> bool:
    try:
        until = json.loads(PAUSE_FILE.read_text(encoding="utf-8")).get("pause_until") or ""
    except (OSError, ValueError):
        return False        # an unreadable pause file never silences the alarm
    return bool(until) and today <= until


def shift_of(now: datetime) -> str:
    hhmm = now.strftime("%H:%M")
    started = [name for at, name in SHIFTS if at <= hhmm]
    return started[-1] if started else SHIFTS[-1][1]


def log_line(text: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(SERVER_TZ):%m-%d %H:%M} {text}\n")


def push_group(title: str, body: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    r = subprocess.run([PY, str(REPO / "scripts" / "mac" / "push.py"), "--group", title, f.name],
                       capture_output=True, text=True, check=False)
    Path(f.name).unlink(missing_ok=True)
    return r.returncode == 0


def judge(now: datetime, is_up, dry: bool = False, push=push_group) -> str:
    """Return what happened, one word: up / paused / alarmed / push-failed."""
    shift = shift_of(now)
    if is_up():
        log_line(f"{shift}: 游戏机在线")
        return "up"
    if paused(now.strftime("%Y-%m-%d")):
        log_line(f"{shift}: 游戏机连不上，但 queue/watchdog.json 暂停到 pause_until，不报")
        return "paused"
    title = f"🔌 游戏机{shift}到点没开机"
    body = (f"北京 {now:%H:%M} 从 Mac 连游戏机，{TRIES} 次、{(TRIES - 1) * GAP_S // 60} 分钟都连不上。"
            f"\n\n{shift}这一轮多半没跑：可能没通电、没开机，或者开了但断网。"
            f"\n\n（Mac 上的开机检查 scripts/mac/bootwatch.py）")
    if dry:
        print(title, body, sep="\n")
        return "alarmed"
    ok = push(title, body)
    log_line(f"{shift}: 游戏机连不上，{'已报群' if ok else '报群失败'}")
    return "alarmed" if ok else "push-failed"


def main(argv: list[str]) -> int:
    got = judge(datetime.now(SERVER_TZ), reachable, dry="--dry-run" in argv)
    print(got)
    return 1 if got == "push-failed" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
