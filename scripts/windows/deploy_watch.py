"""Deploy watch and rollback: deploy-relay.sh runs this on the game machine.

2026-10-10 16:27 a deploy (v20261010082756) put a relay on the machine that
crashed pythonservice.exe a few seconds after every start: 17 restarts in five
minutes, until someone looked. The deploy script had printed green - files,
hashes, RUNNING and the smoke import were all fine, because each restart came
up RUNNING first. And from 16:14 the boot self-check had been red and the keeper
had no handle on AUTO-MAS, also without the deploy noticing. The rule since
(验收, 10-10 17:3x): after a restart, watch the relay for two minutes; a restart,
a self-check that is not all green, or no 「已挂上 AUTO-MAS 进程句柄」 puts the
previous version back by itself and fails the deploy.

Three subcommands:

  snapshot <root> <backup_dir>   the files about to be overwritten (their relative
                                 paths on stdin) and the current code version are
                                 copied to backup_dir; prints "SNAPSHOT <n> <version>"
  restore <root> <backup_dir>    puts them back, deletes the files that were new,
                                 writes the old code version back, clears __pycache__;
                                 prints "RESTORED <n> <version>"
  watch <log> <since> <seconds> <mode> [version]
                                 mode "deploy": the three conditions above;
                                 mode "rollback": one start, no restart, and the
                                 relay names `version` as its code version.
                                 `since` is the machine-local time just before
                                 the service was started ("YYYY-MM-DD HH:MM:SS").
                                 Prints one line per milestone and a last line
                                 "WATCH_OK ..." or "WATCH_FAIL <why>"; exit 0 / 1.

Read-only apart from the two copy steps: it never starts a queue or spends stamina.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "ark-relay"
DISPLAY_NAME = "Ark Relay"            # service.py _svc_display_name_ starts with it
POLL_S = 2.0
TAIL_BYTES = 2_000_000

BOOT = "服务模式启动"
SELFCHECK_FAIL = "开机自检 ✗"
SELFCHECK_OK = re.compile(r"开机自检 \d+ 项全部成立")
HANDLE = "已挂上 AUTO-MAS 进程句柄"
VERSION = re.compile(r"中继代码版本 (\S+)")
_TS = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) ")


# ---------- judging (pure, tested on the Mac) ----------

def lines_since(text: str, since: datetime) -> list[str]:
    """relay.log lines stamped at or after `since` (the log has no year; `since` gives it).
    A line without a stamp (a traceback) goes with the stamped line above it."""
    out, keep = [], False
    for line in text.splitlines():
        m = _TS.match(line)
        if m:
            mo, d, h, mi, s = (int(g) for g in m.groups())
            try:
                at = datetime(since.year, mo, d, h, mi, s)
            except ValueError:
                keep = False
                continue
            keep = at >= since
        if keep:
            out.append(line)
    return out


def judge(lines: list[str], *, pids: list[int], states: list[str], events: list[str],
          elapsed: float, total: float, mode: str = "deploy", version: str = "") -> tuple[str, str]:
    """("ok" | "fail" | "wait", why). Fails as soon as something is wrong; "ok" only
    once the whole `total` has passed with every condition met."""
    boots = sum(BOOT in ln for ln in lines)
    if boots > 1:
        return "fail", f"中继启动后又重启了（{boots} 次「{BOOT}」）"
    if events:
        return "fail", f"系统日志记下中继意外退出：{events[0]}"
    seen = [p for p in pids if p]
    if len(set(seen)) > 1:
        return "fail", f"中继的进程号变了（{' → '.join(str(p) for p in dict.fromkeys(seen))}），中间重启过"
    if states and states[-1] != "RUNNING" and elapsed > 5:
        return "fail", f"服务不在运行（{states[-1]}）"
    if mode == "deploy":
        for ln in lines:
            if SELFCHECK_FAIL in ln:
                return "fail", f"开机自检有项不成立：{ln.split(SELFCHECK_FAIL, 1)[1].strip()}"
        need = []
        if not boots:
            need.append(f"「{BOOT}」")
        if not any(SELFCHECK_OK.search(ln) for ln in lines):
            need.append("「开机自检 N 项全部成立」")
        if not any(HANDLE in ln for ln in lines):
            need.append(f"「{HANDLE}」")
    else:
        got = [m.group(1) for ln in lines for m in [VERSION.search(ln)] if m]
        if got and version and got[-1] != version:
            return "fail", f"起来的是 {got[-1]}，不是要退回的 {version}"
        need = [] if got else ["「中继代码版本」那一行"]
    if elapsed < total:
        return "wait", "、".join(need)
    if need:
        return "fail", f"{int(total)} 秒内没等到 " + "、".join(need)
    return "ok", f"{int(total)} 秒内没有重启" + ("，开机自检全过，已挂上调度程序句柄" if mode == "deploy"
                                               else f"，起来的是 {version}")


# ---------- reading the machine ----------

def _service() -> tuple[int, str]:
    try:
        out = subprocess.run(["sc", "queryex", SERVICE], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return 0, "UNKNOWN"
    text = out.decode("utf-8", errors="replace")
    pid = re.search(r"PID\s*:\s*(\d+)", text)
    state = re.search(r"STATE\s*:\s*\d+\s+(\w+)", text)
    return (int(pid.group(1)) if pid else 0), (state.group(1) if state else "UNKNOWN")


def _crash_events(since: datetime) -> list[str]:
    """Service Control Manager 7031 / 7034 (a service terminated unexpectedly) about
    the relay since `since`."""
    utc = datetime.fromtimestamp(since.timestamp(), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    q = (f"*[System[(EventID=7031 or EventID=7034) and TimeCreated[@SystemTime>='{utc}']]]")
    try:
        out = subprocess.run(["wevtutil", "qe", "System", f"/q:{q}", "/f:xml"],
                             capture_output=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    text = out.decode("utf-8", errors="replace")
    found = []
    for ev in re.findall(r"<Event .*?</Event>", text, flags=re.S):
        if DISPLAY_NAME.lower() in ev.lower() or f">{SERVICE}<" in ev:
            eid = re.search(r"<EventID[^>]*>(\d+)</EventID>", ev)
            at = re.search(r"SystemTime='([^']+)'", ev)
            found.append(f"事件 {eid.group(1) if eid else '?'}（{at.group(1)[:19] if at else '?'} UTC）")
    return found


def _tail(log: str) -> str:
    try:
        with open(log, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def watch(log: str, since_s: str, total: float, mode: str, version: str = "") -> int:
    since = datetime.strptime(since_s, "%Y-%m-%d %H:%M:%S")
    t0 = time.monotonic()
    pids, states, said = [], [], set()
    while True:
        elapsed = time.monotonic() - t0
        pid, state = _service()
        pids.append(pid)
        states.append(state)
        lines = lines_since(_tail(log), since)
        for ln in lines:
            for key in (BOOT, HANDLE, "中继代码版本") if mode == "deploy" else (BOOT, "中继代码版本"):
                if key in ln and key not in said:
                    said.add(key)
                    print(f"  {ln[:120]}", flush=True)
            if SELFCHECK_OK.search(ln) and "selfcheck" not in said:
                said.add("selfcheck")
                print(f"  {ln[:120]}", flush=True)
        verdict, why = judge(lines, pids=pids, states=states, events=_crash_events(since),
                             elapsed=elapsed, total=total, mode=mode, version=version)
        if verdict == "ok":
            print(f"WATCH_OK {why}", flush=True)
            return 0
        if verdict == "fail":
            print(f"WATCH_FAIL {why}", flush=True)
            return 1
        time.sleep(POLL_S)


# ---------- snapshot / restore ----------

def _code_version(root: Path):
    sys.path.insert(0, str(root))
    from ark_relay.statestore import StateStore  # noqa: PLC0415 - the machine's own copy
    return StateStore(root / "state")


def snapshot(root: Path, backup: Path, rels: list[str], version: str) -> dict:
    if backup.exists():
        shutil.rmtree(backup)
    (backup / "files").mkdir(parents=True)
    kept, new = [], []
    for rel in rels:
        src = root / rel
        if src.is_file():
            dst = backup / "files" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            kept.append(rel)
        else:
            new.append(rel)
    info = {"kept": kept, "new": new, "code_version": version}
    (backup / "snapshot.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def restore(root: Path, backup: Path) -> dict:
    info = json.loads((backup / "snapshot.json").read_text(encoding="utf-8"))
    for rel in info["kept"]:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / "files" / rel, dst)
    for rel in info["new"]:
        (root / rel).unlink(missing_ok=True)
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return info


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "snapshot":
        root, backup = Path(argv[2]), Path(argv[3])
        rels = [ln.strip() for ln in sys.stdin.read().split() if ln.strip()]
        version = _code_version(root).get("versions", "code", "") or ""
        info = snapshot(root, backup, rels, version)
        print(f"SNAPSHOT {len(info['kept'])} {version or '-'}")
        return 0
    if cmd == "restore":
        root, backup = Path(argv[2]), Path(argv[3])
        info = restore(root, backup)
        if info["code_version"]:
            _code_version(root).set("versions", "code", info["code_version"])
        print(f"RESTORED {len(info['kept'])} {info['code_version'] or '-'}")
        return 0
    if cmd == "watch":
        return watch(argv[2], argv[3], float(argv[4]), argv[5], argv[6] if len(argv) > 6 else "")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
