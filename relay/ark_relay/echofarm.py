"""Farm 4-cost boss echoes until a wall-clock time.

Asked for on 2026-09-09 in these words: 「刷的时候不要按次数，而是时间来，
比如说刷到北京时间八点半这种」 - farm to a clock time, not to a repeat count.
OK-WW only understands `Repeat Farm Count`, so the count is set high and **this**
decides when to stop: the engine checks the deadline on every tick and stops the
run when it passes.

Two things this owes the operator, both learned the hard way elsewhere in this
repo:

* **The previous FarmEchoTask config is saved and put back.** That file is shared
  with the daily's weekly-boss step, so leaving it pointed at an overworld boss
  would silently change what the 09:00 run does.
* **Starting is a session-1 problem.** The relay lives in session 0 and has no
  desktop, so OK-WW is launched the way AUTO-MAS is revived - a .bat run through
  a scheduled task - not with Popen, which would start a process that can never
  see the game window.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.echofarm")

TASK_NAME = "ark-okww-farm"
BAT = r"C:\ProgramData\ark-okww-farm.bat"
# FarmEchoTask is one-time task 2 in OK-WW's own list (okww-task.sh --list).
OKWW_TASK_INDEX = 2
# High enough that the clock always ends the run, low enough to be a real number.
BIG_COUNT = 100000


def _cfg_path(okww_dir) -> Path | None:
    return (Path(okww_dir) / "configs" / "FarmEchoTask.json") if okww_dir else None


def _store(state_dir):
    from .statestore import StateStore  # noqa: PLC0415 - avoids an import cycle
    return StateStore(Path(state_dir))


def current(state_dir) -> dict:
    """The farm in progress, or {}."""
    rec = _store(state_dir).get("queues", "echo_farm")
    return dict(rec) if isinstance(rec, dict) else {}


def deadline_of(rec: dict) -> datetime | None:
    try:
        return datetime.strptime(str(rec.get("until")), "%Y-%m-%d %H:%M").replace(tzinfo=SERVER_TZ)
    except (TypeError, ValueError):
        return None


def resolve_until(hhmm: str, now: datetime | None = None) -> datetime | None:
    """'08:30' -> the next moment it is 08:30 on the machine's clock."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        hh, mm = (int(x) for x in str(hhmm).strip().split(":"))
    except (TypeError, ValueError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return when if when > now else when + timedelta(days=1)


def _write_cfg(path: Path, values: dict) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(values)
    atomic_write_text(path, json.dumps(doc, ensure_ascii=False, indent=1))
    return json.loads(path.read_text(encoding="utf-8"))


def _launch() -> tuple[bool, str]:
    """Start OK-WW's FarmEchoTask on the interactive desktop."""
    py = Path(r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe")
    main = Path(r"D:\ark\okww\data\apps\ok-ww\working\main.py")
    if not py.is_file() or not main.is_file():
        return False, f"找不到 OK-WW 的程序（{py} / {main}）"
    Path(BAT).write_text(
        f'@echo off\r\ncd /d "{main.parent}"\r\n"{py}" "{main}" -t {OKWW_TASK_INDEX} -e\r\n',
        encoding="utf-8")
    subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], capture_output=True)
    mk = subprocess.run(["schtasks", "/create", "/tn", TASK_NAME, "/tr", BAT, "/sc", "once",
                         "/st", "00:00", "/ru", "Administrator", "/it", "/f"], capture_output=True)
    if mk.returncode != 0:
        return False, f"建计划任务失败：{mk.stderr.decode('utf-8', 'replace')[:120]}"
    run = subprocess.run(["schtasks", "/run", "/tn", TASK_NAME], capture_output=True)
    if run.returncode != 0:
        return False, f"启动计划任务失败：{run.stderr.decode('utf-8', 'replace')[:120]}"
    return True, ""


def stop_okww() -> None:
    """End the farm process. The game itself is left alone."""
    subprocess.run(["schtasks", "/end", "/tn", TASK_NAME], capture_output=True)
    from .preupdate_okww import _okww_quiesce  # noqa: PLC0415
    _okww_quiesce()


def start(cfg, boss: int, until_hhmm: str, name: str = "") -> tuple[bool, str]:
    """Point OK-WW at one overworld boss and farm it until `until_hhmm`."""
    path = _cfg_path(getattr(cfg, "okww_dir", None) or os.environ.get("ARK_OKWW_DIR"))
    if not path or not path.is_file():
        return False, "找不到 OK-WW 的 FarmEchoTask 配置"
    try:
        boss = int(boss)
    except (TypeError, ValueError):
        return False, f"「第几个」要是数字，收到 {boss!r}"
    if not 1 <= boss <= 30:
        return False, f"「第几个」超出范围：{boss}"
    until = resolve_until(until_hhmm)
    if until is None:
        return False, f"结束时刻看不懂：{until_hhmm!r}（要 08:30 这种）"
    running = current(cfg.state_dir)
    if running:
        return False, (f"已经在刷{running.get('name') or ''}了，刷到 {running.get('until')}。"
                       "要换目标先停掉现在这一趟")

    saved = json.loads(path.read_text(encoding="utf-8"))
    back = _write_cfg(path, {"Teleport to Boss": "Boss Challenge",
                             "Which Boss Challenge to Teleport": boss,
                             "Repeat Farm Count": BIG_COUNT})
    if back.get("Which Boss Challenge to Teleport") != boss:
        atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=1))
        return False, "写完回读不对，配置已还原，没有开跑"

    ok, why = _launch()
    if not ok:
        atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=1))
        return False, f"{why}；配置已还原"

    _store(cfg.state_dir).set("queues", "echo_farm", {
        "boss": boss, "name": name or f"第 {boss} 个",
        "until": until.strftime("%Y-%m-%d %H:%M"),
        "started": datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d %H:%M"),
        "saved": saved,
    })
    return True, f"开始刷{name or f'第 {boss} 个'}，刷到 {until:%H:%M} 为止（机器时间）"


def finish(cfg, why: str) -> str:
    """Stop the farm and put the config back. '' when nothing was running."""
    rec = current(cfg.state_dir)
    if not rec:
        return ""
    stop_okww()
    note = ""
    path = _cfg_path(getattr(cfg, "okww_dir", None) or os.environ.get("ARK_OKWW_DIR"))
    saved = rec.get("saved")
    if path and path.is_file() and isinstance(saved, dict):
        try:
            atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=1))
            back = json.loads(path.read_text(encoding="utf-8"))
            if back.get("Teleport to Boss") != saved.get("Teleport to Boss"):
                note = "；**配置没还原成功，明早周本可能刷错目标**"
        except OSError:
            note = "；**配置没能还原，明早周本可能刷错目标**"
    else:
        note = "；**找不到配置文件，没能还原**"
    _store(cfg.state_dir).pop("queues", "echo_farm")
    started = rec.get("started") or "?"
    return f"刷{rec.get('name') or ''}结束（{why}）。{started} 开始，配置已还原{note}"


def tick(cfg, now: datetime | None = None) -> str:
    """Called every engine tick. Returns a line to push when the farm just ended."""
    rec = current(cfg.state_dir)
    if not rec:
        return ""
    until = deadline_of(rec)
    if until is None:
        return finish(cfg, "结束时刻读不出来，为安全起见停掉")
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if now >= until:
        return finish(cfg, f"到点了（{until:%H:%M}）")
    return ""
