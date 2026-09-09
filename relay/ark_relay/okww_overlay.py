"""Install Ark's overrides into OK-WW's own extension point, and check they took.

ok-script executes every `.py` under `<working>/ok_tasks/` at startup. Putting our
changes there means no upstream file is edited at all: an OK-WW update cannot
half-apply them, there is no previous version to revert first, and the whole class
of 「贴不上了」/「叠了」 failures stops existing.

The file writes a report saying what it applied and what it skipped. Reading that
back is the point: an override that silently did not happen is worse than no
override, because everything downstream still assumes it did.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import atomic_write_text

log = logging.getLogger("ark.okww_overlay")

# Same working directory the patches target: ok-script builds the folder from
# os.getcwd(), and OK-WW is always started from there.
_WORKING = ("data", "apps", "ok-ww", "working")
TASKS_DIR = "ok_tasks"
FILE_NAME = "ark_overrides.py"
REPORT = Path(r"C:\ProgramData\ark-okww-overlay.json")

_SOURCE = Path(__file__).with_name("okww_files") / "ark_overrides.tasks.py"


def source_text() -> str:
    return _SOURCE.read_text(encoding="utf-8")


def target(okww_dir) -> "Path | None":
    if not okww_dir:
        return None
    return Path(okww_dir).joinpath(*_WORKING, TASKS_DIR, FILE_NAME)


def install(okww_dir) -> str:
    """Copy the overrides into place. Returns a line to log, '' when unchanged."""
    dest = target(okww_dir)
    if dest is None:
        return "找不到 OK-WW 目录，覆盖文件没装上"
    want = source_text()
    try:
        if dest.is_file() and dest.read_text(encoding="utf-8") == want:
            return ""
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, want)
        if dest.read_text(encoding="utf-8") != want:
            return "**覆盖文件写下去了但回读不对**，OK-WW 会按上游原样跑"
    except OSError as exc:
        return f"**覆盖文件装不上（{exc}）**，OK-WW 会按上游原样跑"
    return f"OK-WW 覆盖文件已装到 {dest}"


def last_report() -> dict:
    """What the overrides said last time OK-WW started. {} when it never ran."""
    try:
        return json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def report_line() -> str:
    """A plain-Chinese line when something did not take. '' when all is well.

    Only speaks up about trouble: 「全都贴上了」 every boot is noise, a skipped
    override is the whole reason this file exists.
    """
    got = last_report()
    if not got:
        return ""
    if err := got.get("error"):
        return "OK-WW 覆盖文件自己报错了，改动一条都没生效：" + str(err)[-300:]
    skipped = got.get("skipped") or []
    if not skipped:
        return ""
    return ("OK-WW 有改动没贴上，上游多半改了结构：" +
            "；".join(f"{s.get('what')}（{s.get('why')}）" for s in skipped))
