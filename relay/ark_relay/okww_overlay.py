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

import ast
import hashlib
import inspect
import json
import logging
import re
from pathlib import Path

from .config import atomic_write_text, master_config_dir

log = logging.getLogger("ark.okww_overlay")

# Same working directory the patches target: ok-script builds the folder from
# os.getcwd(), and OK-WW is always started from there.
_WORKING = ("data", "apps", "ok-ww", "working")
TASKS_DIR = "ok_tasks"
FILE_NAME = "ark_overrides.py"
REPORT = Path(r"C:\ProgramData\ark-okww-overlay.json")
# Where the overrides read the master ConfigFile directory from. Needed because
# ok-script's Config drops unknown keys and rewrites configs/ at load, before the
# extension runs - so 「Only Farm These Nests」 is only ever readable from the master.
MASTER_POINTER = Path(r"C:\ProgramData\ark-okww-master.txt")

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
        return "找不到 OK-WW 目录，中继的改动文件没装上"
    want = source_text()
    try:
        if dest.is_file() and dest.read_text(encoding="utf-8") == want:
            return ""
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, want)
        if dest.read_text(encoding="utf-8") != want:
            return "**中继的改动文件写下去了，但读出来和写的不一样**，OK-WW 会按原版跑"
    except OSError as exc:
        return f"**中继的改动文件装不上（{exc}）**，OK-WW 会按原版跑"
    return f"中继给 OK-WW 的改动文件已装到 {dest}"


def write_master_pointer(automas_dir) -> str:
    """Tell the overrides where AUTO-MAS's OK-WW master directory is. '' when written, else why not."""
    d = master_config_dir(automas_dir, "DailyTask.json")
    if d is None:
        return "找不到 OK-WW 的母本目录，「只刷落渊南丘」这项设置 OK-WW 跑的时候读不到"
    try:
        if MASTER_POINTER.is_file() and MASTER_POINTER.read_text(encoding="utf-8").strip() == str(d):
            return ""
        atomic_write_text(MASTER_POINTER, str(d))
    except OSError as exc:
        return f"母本目录的指路文件写不了（{exc}），「只刷落渊南丘」这项设置 OK-WW 跑的时候读不到"
    return ""


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
        return "中继给 OK-WW 的改动文件自己报错了，改动一条都没生效：" + str(err)[-300:]
    skipped = got.get("skipped") or []
    adapted = got.get("adapted") or []
    parts = []
    if skipped:
        parts.append("OK-WW 有改动没贴上（上游源码和登记的不一致）：" +
                     "；".join(f"{s.get('what')}（{s.get('why')}）" for s in skipped))
    if adapted:
        parts.append("OK-WW 升级改了这几处，中继已按新版适配：" +
                     "、".join(str(a.get("what")) for a in adapted))
    return "\n".join(parts)


# ── before the run: do the pinned copies still match the source on disk? ─────
# The report above only exists once OK-WW has started with the overrides, and OK-WW
# updates itself on start: 10-04 the queue's own launch went v3.7.2 -> v3.7.3 at 09:18
# and the stale copy was found out by the result check, as an alarm, after the run.
# This reads the files instead, right after the boot pre-update, with the same hash the
# overrides compute (inspect.getsource of the method), so a mismatch is known before
# anything runs.
_PIN = re.compile(r'@override\((\w+), "(\w+)", expect_sha=(_\w+)(, adapt=True)?\)')
_SHA_CONST = re.compile(r'^(_\w+) = "([0-9a-f]{12})"', re.M)
# All of src/: the bases are spread over it (CombatCheck lives in src/combat/).
_SRC = ("data", "apps", "ok-ww", "working", "src")


def pins(text: str | None = None) -> list[tuple[str, str, str, bool]]:
    """(class, method, pinned sha, adapts) for every pinned override in the overrides file."""
    text = source_text() if text is None else text
    consts = dict(_SHA_CONST.findall(text))
    return [(c, m, consts.get(k, ""), bool(a)) for c, m, k, a in _PIN.findall(text)]


def _classes(src_dir: Path) -> dict:
    """class name -> (source lines, {method: first line index}, base names), from every file."""
    out = {}
    for f in sorted(src_dir.rglob("*.py")):
        try:
            text = f.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError, ValueError):
            continue
        lines = text.splitlines(keepends=True)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {}
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods[fn.name] = min([d.lineno for d in fn.decorator_list] + [fn.lineno]) - 1
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            out.setdefault(node.name, (lines, methods, bases))
    return out


def _method_sha(classes: dict, cls: str, name: str, seen=None) -> str:
    """inspect.getsource's hash for cls.name, looked up through the bases; '' when not found."""
    seen = set() if seen is None else seen
    if cls in seen or cls not in classes:
        return ""
    seen.add(cls)
    lines, methods, bases = classes[cls]
    if name in methods:
        block = inspect.getblock(lines[methods[name]:])
        return hashlib.sha1("".join(block).encode("utf-8")).hexdigest()[:12]
    for b in bases:
        if got := _method_sha(classes, b, name, seen):
            return got
    return ""


def drift(okww_dir) -> list[dict]:
    """Pinned overrides whose upstream body on disk differs from the pin. [] when all match or no source."""
    if not okww_dir:
        return []
    src = Path(okww_dir).joinpath(*_SRC)
    if not src.is_dir():
        return []
    classes = _classes(src)
    out = []
    for cls, name, want, adapts in pins():
        got = _method_sha(classes, cls, name)
        # '' = not found here: a file this Python cannot parse (upstream uses 3.12
        # f-strings) or a renamed method. The in-process report covers the latter;
        # neither is evidence of a changed body.
        if got and got != want:
            out.append({"what": f"{cls}.{name}", "want": want, "got": got, "adapt": adapts})
    return out


def drift_line(okww_dir, state_dir=None) -> str:
    """One plain line about pinned copies that no longer match, '' when none or already said.

    A copy that goes in skipped (no `adapt`) leaves that override off until it is
    copied again - a fault nothing fixes by itself, so it is said at every boot and
    pre-update (the user, 2026-10-06: 「不论多少次什么错误都要发」; until then it was
    said once per distinct mismatch like the rest). Copies the relay adapted itself
    are said once per distinct mismatch (remembered in `state_dir`).
    """
    found = drift(okww_dir)
    if not found:
        return ""
    adapted = [d["what"] for d in found if d["adapt"]]
    skipped = [d["what"] for d in found if not d["adapt"]]
    sig = ";".join(f"{d['what']}={d['got']}" for d in found)
    mark = Path(state_dir) / "okww-drift.txt" if state_dir else None
    try:
        if (not skipped and mark is not None and mark.is_file()
                and mark.read_text(encoding="utf-8") == sig):
            return ""
        if mark is not None:
            atomic_write_text(mark, sig)
    except OSError:
        pass
    parts = []
    if adapted:
        parts.append(f"{'、'.join(adapted)} 中继会按新版适配后照样换上")
    if skipped:
        parts.append(f"{'、'.join(skipped)} 这一处先按 OK-WW 新版跑，等我们重抄")
    return "OK-WW 升级后，中继的改动有 %d 处和新版对不上：%s" % (len(found), "；".join(parts))
