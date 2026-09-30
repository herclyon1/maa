"""Read-only machine readings for scripts/mac/boot-check.py (docs/NEXT-BOOT.md, 2026-09-30).

    scripts/mac/winrun.sh --py scripts/mac/lib/boot_check_remote.py [--day 2026-09-30]
    python3.14 scripts/mac/lib/boot_check_remote.py --root <fake relay dir> --code-dir relay

Prints one line `BOOTCHECK_JSON=<ascii json>`; the Mac side does all the judging.

Nothing here writes. Bytecode is off, and once the relay readers start an audit
hook refuses (and records) any open-for-write, rename, remove, new directory,
socket connect or subprocess. The only subprocess - the PowerShell query for
boot time and System events - runs before the hook is armed. Relay state is read
through the relay's own readers (gameupdate.pending, core.State.read_ledger,
report._compose_daily) with the legacy-file sweep in StateStore pre-empted,
because that sweep renames files. _compose_daily runs with the banner block
(network, a trace file, a group push), the model call and the plan cache
stubbed out; its notifier raises if anything tries to send.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.dont_write_bytecode = True

from arklog import parse_ts  # noqa: E402

DEFAULT_ROOT = r"C:\ProgramData\ark-relay"
PWSH = r"C:\Program Files\PowerShell\7\pwsh.exe"

# ---------------------------------------------------------------- read-only guard
_ARMED = [False]
BLOCKED: list[str] = []
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_REFUSE = {"os.rename", "os.remove", "os.rmdir", "os.truncate", "os.chmod", "os.link",
           "os.symlink", "shutil.copyfile", "shutil.copymode", "shutil.copystat",
           "shutil.rmtree", "shutil.move", "socket.connect", "socket.sendto",
           "subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.exec",
           "os.posix_spawn", "winreg.SetValue", "winreg.CreateKey", "winreg.DeleteKey"}


def _is_write_open(args) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str):
        return any(c in mode for c in "wax+")
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _audit(event: str, args) -> None:
    if not _ARMED[0]:
        return
    bad = False
    if event == "open":
        bad = _is_write_open(args)
    elif event == "os.mkdir":
        # mkdir(exist_ok=True) on a directory that is already there writes nothing
        bad = not (args and os.path.isdir(str(args[0])))
    elif event in _REFUSE:
        bad = True
    if bad:
        what = f"{event} {str(args[0]) if args else ''}"[:160]
        BLOCKED.append(what)
        raise PermissionError(f"boot-check is read-only: {what}")


sys.addaudithook(_audit)


class _Keep(logging.Handler):
    """Relay warnings go into the JSON rather than onto the stream the Mac parses."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.lines.append(f"{record.levelname} {record.name} {record.getMessage()}"[:300])


_LOGS = _Keep()
logging.getLogger().addHandler(_LOGS)
logging.getLogger().setLevel(logging.INFO)


# ---------------------------------------------------------------- helpers
def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _stamp(line: str, year: int) -> "datetime | None":
    return parse_ts(line, default_year=year)


def _at(day: str, hms: str) -> datetime:
    d = date.fromisoformat(day)
    h, m, s = (int(x) for x in (hms.split(":") + ["0", "0"])[:3])
    return datetime(d.year, d.month, d.day, h, m, s)


def _windows_readings(day: str, events_from: str) -> dict:
    """Boot time and System events 41 / 1074 / 6008 (plus boot/stop markers) from events_from on.

    6008 and 41 are written at the *next* boot, so they are looked for from the
    vanish onwards, not only inside 10:10-10:15; each one names the moment it is about.
    """
    if os.name != "nt":
        return {"err": "不是 Windows，读不到开机时刻和系统事件"}
    if not Path(PWSH).is_file():
        return {"err": "机器上没有 pwsh 7"}
    ps = (
        "$ErrorActionPreference='Stop'\n"
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8\n"
        "$o=[ordered]@{}\n"
        "try { $os=Get-CimInstance Win32_OperatingSystem;"
        " $o.boot=$os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss');"
        " $o.now=(Get-Date).ToString('yyyy-MM-dd HH:mm:ss') } catch { $o.boot_err=\"$_\" }\n"
        "try { $ev=Get-WinEvent -FilterHashtable @{LogName='System';"
        " Id=41,1074,6005,6006,6008,12,13;"
        f" StartTime=[datetime]'{day} {events_from}'}} -MaxEvents 60;"
        " $o.events=@($ev | ForEach-Object { [ordered]@{"
        "t=$_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'); id=$_.Id; provider=$_.ProviderName;"
        " msg=[string]$_.Message; props=@($_.Properties | ForEach-Object { [string]$_.Value }) } }) }"
        " catch { if (\"$($_.FullyQualifiedErrorId)\" -like 'NoMatchingEventsFound*')"
        " { $o.events=@() } else { $o.events_err=\"$_\" } }\n"
        "$o | ConvertTo-Json -Depth 5 -Compress\n"
    )
    b64 = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    try:
        out = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-EncodedCommand", b64],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"err": _err(exc)}
    text = out.stdout.decode("utf-8", "replace").strip()
    try:
        got = json.loads(text)
    except ValueError:
        return {"err": "PowerShell 输出不是 JSON：" + (text or out.stderr.decode("utf-8", "replace"))[:200]}
    for e in got.get("events") or []:
        e["msg"] = " ".join(str(e.get("msg") or "").split())[:400]
    return got


# ---------------------------------------------------------------- relay readings
def _log_readings(log_file: Path, day: str, win_from: str, win_to: str,
                  runs: list[tuple[str, str]]) -> dict:
    out: dict = {"file": str(log_file)}
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        out["err"] = _err(exc)
        return out
    year = date.fromisoformat(day).year
    start, end = _at(day, win_from), _at(day, win_to)
    day0, day1 = _at(day, "00:00:00"), _at(day, "23:59:59")
    on_day: list[str] = []
    window: list[str] = []
    after: list[str] = []          # every line after the window, file order
    last_before = first_after = None
    cur = None
    for ln in lines:
        ts = _stamp(ln, year)
        if ts is not None:
            cur = ts
        if cur is None:
            continue
        if day0 <= cur <= day1:
            on_day.append(ln)
        if start <= cur <= end:
            window.append(ln)
        if cur <= end and ts is not None:
            last_before = ln
        if cur > end:
            if first_after is None and ts is not None:
                first_after = ln
            after.append(ln)
    out["day_lines"] = len(on_day)
    out["updated"] = [ln for ln in on_day if "代码已更新" in ln][-3:]
    out["cos_version"] = [ln for ln in on_day
                          if "COS 上有新版 v" in ln or "COS 上最新一次部署是 v" in ln][-5:]
    out["window_count"] = len(window)
    out["window_gameupdate"] = [ln for ln in window if "游戏更新：" in ln]
    out["window_first"] = window[0] if window else None
    out["window_last"] = window[-1] if window else None
    out["last_before_end"] = last_before
    out["first_after_end"] = first_after
    out["starts_after"] = [ln for ln in after if "服务模式启动" in ln][:5]
    out["backfill"] = {}
    for script, rid in runs:
        needle = f"⏹ 补记：{script} {rid}（"
        hits = [ln for ln in lines if needle in ln]
        out["backfill"][rid] = {"count": len(hits), "lines": hits[:5]}
    return out


class _NoSend:
    """Stands in for the notifier: any attempt to push fails loudly instead of sending."""

    def __getattr__(self, name):
        def refuse(*_a, **_k):
            BLOCKED.append(f"notifier.{name}")
            raise RuntimeError(f"boot-check refuses notifier.{name}")
        return refuse


def _relay_readings(root: Path, day: str, runs: list[tuple[str, str]]) -> dict:
    out: dict = {}
    try:
        from ark_relay import core, gameupdate, report, statestore  # noqa: PLC0415
        from ark_relay.config import Config  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        out["err"] = "import ark_relay 失败：" + _err(exc)
        return out
    cfg = Config()
    sd = Path(cfg.state_dir)
    if not sd.is_absolute():
        sd = (root / sd).resolve()
    cfg.state_dir = sd
    out["state_dir"] = str(sd)
    if not sd.is_dir():
        out["err"] = f"状态目录不存在：{sd}"
        return out
    # StateStore's first construction per directory sweeps legacy files (renames,
    # writes state.json). Mark it done so every read below is a pure read.
    statestore._SWEPT.add(str(sd))

    try:
        out["code_version"] = statestore.StateStore(sd).get("versions", "code")
    except Exception as exc:  # noqa: BLE001
        out["code_version_err"] = _err(exc)
    try:
        out["pending"] = gameupdate.pending(sd)
        out["pending_legacy_file"] = (sd / "gameupdate-pending.json").exists()
    except Exception as exc:  # noqa: BLE001
        out["pending_err"] = _err(exc)

    state = core.State(sd)
    ledger = state.ledger_path(day)
    out["ledger_file"] = str(ledger)
    out["ledger_exists"] = ledger.exists()
    entries = state.read_ledger(day)
    out["ledger_entries"] = len(entries)
    out["ledger"] = {}
    for script, rid in runs:
        e = next((x for x in entries if x.get("run_id") == rid), None)
        out["ledger"][rid] = None if e is None else {
            "script": e.get("script"), "started": e.get("started"),
            "finished": e.get("finished"), "ok": e.get("ok"),
            "manual_stop": (e.get("raw") or {}).get("manual_stop")}

    # The daily report as the relay would render it, with every outward effect cut.
    def _no_banners(*_a, **_k):
        raise RuntimeError("boot-check: banner block skipped (network + trace file + group push)")

    report.banners.collect = _no_banners
    report.banners.save_trace = lambda *_a, **_k: None
    report.summary.daily_report = lambda *_a, **_k: ""
    report.plan.next_plan = lambda *_a, **_k: ""

    class _Eng:
        pass

    eng = _Eng()
    eng.cfg, eng.state, eng.notifier = cfg, state, _NoSend()
    eng._announce_banners = lambda *_a, **_k: None
    before = len(BLOCKED)
    try:
        title, body = report._compose_daily(eng, day, entries)
    except Exception as exc:  # noqa: BLE001
        out["compose_err"] = _err(exc)
    else:
        rows = body.splitlines()
        out["compose_title"] = title
        out["compose_stop_rows"] = [r for r in rows if r.startswith("⏹")][:10]
        out["compose_rows"] = {}
        for script, rid in runs:
            e = next((x for x in entries if x.get("run_id") == rid), None)
            hm = core._hm(datetime.fromisoformat(e["started"])) if e else None
            out["compose_rows"][rid] = next(
                (r for r in rows if hm and r.startswith(f"⏹ {script}") and hm in r), None)
            out.setdefault("compose_any_rows", {})[rid] = next(
                (r for r in rows if hm and r.split("　")[0].endswith(script) and hm in r), None)
    out["compose_blocked"] = BLOCKED[before:]
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=DEFAULT_ROOT, help="relay directory (.env, relay.log)")
    p.add_argument("--code-dir", default="", help="where ark_relay lives (default: --root)")
    p.add_argument("--day", default="2026-09-30")
    p.add_argument("--win-from", default="10:10:42")
    p.add_argument("--win-to", default="10:15:00")
    p.add_argument("--events-from", default="10:10:00")
    p.add_argument("--runs", default="OK-WW:OK-WW-05-40-56,MaaEnd:MaaEnd-05-46-45")
    a = p.parse_args()
    root = Path(a.root).resolve() if os.name != "nt" else Path(a.root)
    code_dir = Path(a.code_dir).resolve() if a.code_dir else root
    runs = [tuple(x.split(":", 1)) for x in a.runs.split(",") if ":" in x]
    res: dict = {"root": str(root), "day": a.day, "win": [a.win_from, a.win_to]}

    # Same order as boot_stages._stage_bootstrap: log path first, then .env.
    os.environ.setdefault("ARK_LOG_FILE", str(root / "relay.log"))
    sys.path.insert(0, str(code_dir))
    os.chdir(root)                      # a relative ARK_STATE_DIR resolves here, as run.py does
    try:
        from ark_relay.__main__ import _load_dotenv  # noqa: PLC0415
        _load_dotenv(root / ".env")
    except Exception as exc:  # noqa: BLE001
        res["env_err"] = _err(exc)
    res["windows"] = _windows_readings(a.day, a.events_from)

    _ARMED[0] = True                    # from here on nothing may write, connect or spawn
    res["log"] = _log_readings(Path(os.environ["ARK_LOG_FILE"]), a.day, a.win_from,
                               a.win_to, runs)
    try:
        res["relay"] = _relay_readings(root, a.day, runs)
    except Exception as exc:  # noqa: BLE001
        res["relay"] = {"err": _err(exc)}
    res["blocked"] = BLOCKED
    res["warnings"] = _LOGS.lines[-15:]
    print("BOOTCHECK_JSON=" + json.dumps(res, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
