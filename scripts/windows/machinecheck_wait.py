"""E2 of the deploy: wait for this deploy's boot batch of machine checks to
judge, and fail when a group push went out meanwhile.

Runs on the game machine after a deploy restart, over ssh, as the last gate
before deploy-relay.sh prints 「部署完成」. It reads the two files the relay
already keeps, and answers one question: since this deploy's version took over,
has the boot batch judged, and was the group quiet?

* state/machinecheck.json - one row per judged check; the row carries the code
  version that judged it and the event that exercised it. The boot batch is one
  single machinecheck.judge() call (boot_stages._stage_machinecheck, the last
  boot step), so one row of this version with event "boot" means the whole
  batch has run.
* state/alerts/<YYYYMMDD>.jsonl - the copy of every group push (alertlog.py),
  also carrying the version.

Exit codes:

  0  the boot batch judged at this version and no group push of this version
  1  a group push of this version went out (one ALARM line per push)
  2  the boot batch never judged within the timeout (the relay is still booting)

Read-only by design: it reads the relay's own files and never dispatches a
queue or spends stamina.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def read_rows(state_dir: str, name: str) -> dict:
    """The JSON object in state/<name> (machinecheck.json); {} when none or unreadable."""
    try:
        data = json.loads((Path(state_dir) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def alerts_with_version(state_dir: str, version: str) -> list[dict]:
    """The group-push copy rows (state/alerts/*.jsonl) carrying this version."""
    out: list[dict] = []
    dirp = Path(state_dir) / "alerts"
    if not dirp.is_dir():
        return out
    for f in sorted(dirp.glob("*.jsonl")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and str(row.get("version") or "") == version:
                out.append(row)
    return out


def boot_judged(state_dir: str, version: str) -> bool:
    """Whether this version's boot batch of machine checks has judged at least once."""
    return any(isinstance(r, dict) and str(r.get("version") or "") == version
               and r.get("event") == "boot"
               for r in read_rows(state_dir, "machinecheck.json").values())


def verdict(state_dir: str, version: str) -> tuple[str, list[dict]]:
    """(state, alarms) for this instant: 'alarm', 'boot', or 'wait'.

    'alarm' wins over 'boot': a push during the window is a failure whether or
    not the boot batch has finished."""
    alarms = alerts_with_version(state_dir, version)
    if alarms:
        return "alarm", alarms
    if boot_judged(state_dir, version):
        return "boot", []
    return "wait", []


def main(argv: list[str]) -> int:
    state_dir, version = argv[0], argv[1]
    timeout = float(argv[2]) if len(argv) > 2 else 180.0
    deadline = time.monotonic() + timeout
    while True:
        state, alarms = verdict(state_dir, version)
        if state == "alarm":
            for a in alarms:
                print(f"ALARM {a.get('ts', '')} {a.get('game', '')} {a.get('title', '')} "
                      f"{str(a.get('text', ''))[:120]}")
            print(f"MCWAIT_ALARM {len(alarms)}")
            return 1
        if state == "boot":
            print("MCWAIT_OK")
            return 0
        if time.monotonic() >= deadline:
            print("MCWAIT_TIMEOUT boot batch never judged (relay still booting?)")
            return 2
        time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
