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

from ark_relay.core.config import atomic_write_text, master_config_dir

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


class OverlayTrouble(Exception):
    """install() or write_master_pointer() could not do its job; str(exc) is the plain line.

    Raised, not returned as a line, so the caller cannot mistake it for a healthy
    note: until 2026-10-13 these were plain strings, and the push title was chosen
    by matching words (texts._PATCH_TROUBLE) that none of them contained - OK-WW ran
    as plain upstream while every report said 🩹 (log only).
    """


def install(okww_dir) -> str:
    """Copy the overrides into place. Returns a line to log, '' when unchanged.

    Raises OverlayTrouble when they are not in place afterwards.
    """
    dest = target(okww_dir)
    if dest is None:
        raise OverlayTrouble("找不到 OK-WW 目录，中继的改动文件没装上，OK-WW 会按原版跑")
    want = source_text()
    data = want.encode("utf-8")          # atomic_write_text writes exactly these bytes
    try:
        # Bytes, so the file is left alone (not even its mtime touched) when it is
        # already right. ok-script watches ok_tasks/ while OK-WW runs and executes
        # again any .py there that changes (ok-script task_manager.py
        # _on_debug_dir_changed): a second execution wraps our wrappers again.
        if dest.is_file() and dest.read_bytes() == data:
            return ""
        if okww_running():
            return ("OK-WW 正在运行，中继的改动文件这次先不换（换了它会把新文件再执行一遍，改动套两层），"
                    "下次中继启动时再装")
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, want)
        if dest.read_bytes() != data:
            raise OverlayTrouble("**中继的改动文件写下去了，但读出来和写的不一样**，OK-WW 会按原版跑")
    except OSError as exc:
        raise OverlayTrouble(f"**中继的改动文件装不上（{exc}）**，OK-WW 会按原版跑") from exc
    return f"中继给 OK-WW 的改动文件已装到 {dest}"


def okww_running() -> "bool | None":
    """Is OK-WW itself up: a python.exe / pythonw.exe with config.OKWW_CMDLINE on its
    command line? None when it cannot be told (not Windows, or the process list
    could not be read).

    install() writes on None: at boot OK-WW is normally not running, and a stale
    overlay left in place silently is the worse outcome.
    """
    import os  # noqa: PLC0415

    if os.name != "nt":
        return None
    from ark_relay.core import procs  # noqa: PLC0415
    from ark_relay.core.config import OKWW_CMDLINE, PYTHON_HOSTS  # noqa: PLC0415
    # warn=False: an unreadable process list is not this step's to alarm on; the boot
    # self-check (later in the same boot) pushes the one alarm for that outage.
    rows = procs.python_processes(hosts=PYTHON_HOSTS, warn=False)
    if rows is None:
        log.info("程序列表读不到，不知道 OK-WW 开没开着，照常装中继的改动文件")
        return None
    return any(OKWW_CMDLINE in cmd.lower() for _pid, cmd in rows)


def write_master_pointer(automas_dir) -> str:
    """Tell the overrides where AUTO-MAS's OK-WW master directory is. '' when written or already right.

    Raises OverlayTrouble when the pointer cannot be written.
    """
    d = master_config_dir(automas_dir, "DailyTask.json")
    if d is None:
        raise OverlayTrouble("找不到 OK-WW 的母本目录，「只刷指定残象聚落」这项设置 OK-WW 跑的时候读不到")
    try:
        if MASTER_POINTER.is_file() and MASTER_POINTER.read_text(encoding="utf-8").strip() == str(d):
            return ""
        atomic_write_text(MASTER_POINTER, str(d))
        if MASTER_POINTER.read_text(encoding="utf-8").strip() != str(d):
            raise OverlayTrouble("母本目录的指路文件写下去了，但读出来和写的不一样，「只刷指定残象聚落」这项设置 OK-WW 跑的时候读不到")
    except OSError as exc:
        raise OverlayTrouble(f"母本目录的指路文件写不了（{exc}），「只刷指定残象聚落」这项设置 OK-WW 跑的时候读不到") from exc
    return ""


def last_report() -> dict:
    """What the overrides said last time OK-WW started. {} when it never ran."""
    try:
        return json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def report_snapshot() -> dict:
    """The report as it is on disk now, plus when it was written: {applied, skipped,
    adapted, error, written (ISO 8601, server clock)}; {} when there is none.

    OK-WW rewrites it at every start, so it speaks for the start that wrote it -
    a run's machine check compares it with that run's own log (machinechecks/runs.py).
    """
    got = last_report()
    if not isinstance(got, dict) or not got:
        return {}
    try:
        mtime = REPORT.stat().st_mtime
    except OSError:
        return {}
    from datetime import datetime  # noqa: PLC0415
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    out = {k: got.get(k) for k in ("applied", "skipped", "adapted", "error")}
    out["written"] = datetime.fromtimestamp(mtime, tz=SERVER_TZ).isoformat(timespec="seconds")
    return out


def report_line() -> str:
    """A plain-Chinese line when something did not take. '' when all is well.

    Only speaks up about trouble: 「全都贴上了」 every boot is noise, a skipped
    override is the whole reason this file exists.
    """
    got = last_report()
    if not got:
        return ""
    if err := got.get("error"):
        return _error_line(got, str(err))
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


# Every override site in the overrides file: `@override(Cls, "name"...)` and the
# stamina hooks bound through `_farm_hook(Cls, "name")`.
_SITE = re.compile(r'(?:@override|_farm_hook)\((\w+), "(\w+)"')


def _error_line(got: dict, err: str) -> str:
    """The report says the overrides file raised part-way: which overrides are live, which are not.

    The overrides are applied one by one and the report is written from the except
    (ark_overrides.py, the block at the end), so `applied` is exactly what landed
    before the error; the sites that are neither applied nor skipped did not.
    """
    applied = [str(a) for a in (got.get("applied") or [])]
    if not applied:
        return "中继给 OK-WW 的改动文件自己报错了，改动一条都没生效：" + err[-300:]
    done = applied + [str(s.get("what", "")).split("（")[0] for s in (got.get("skipped") or [])
                      if isinstance(s, dict)]
    try:
        sites = [f"{c}.{m}" for c, m in _SITE.findall(source_text())]
    except OSError:
        sites = []
    missing = [t for t in dict.fromkeys(sites)
               if not any(a == t or a.endswith("." + t) for a in done)]
    line = (f"中继给 OK-WW 的改动文件自己报错了，停在半路：已生效 {len(applied)} 条（{'、'.join(applied)}）"
            + (f"；没生效 {len(missing)} 条（{'、'.join(missing)}）" if missing else "；之后的没装上"))
    return line + "。报错：" + err[-300:]


def nest_patch_present(okww_dir) -> bool | None:
    """Is the nest override (find_nest) bound in OK-WW? None when it cannot be told.

    「Only Farm These Nests」 is an option only our override reads; upstream has no
    such setting. When the override does not bind, every nest gets farmed while the
    config still says 「只打落渊南丘」, so tomorrow's plan has to look at what OK-WW
    reported binding at its last start, not at the config.
    """
    if not okww_dir:
        return None
    got = last_report()
    if got:
        # Applied first: the overrides are applied one by one, so a file that raised
        # later on (`error`) can still have bound find_nest before it.
        bound = got.get("applied") or []
        if any(b.endswith(".find_nest") for b in bound):
            return True
        if got.get("error"):
            return False
        if any(s.get("what", "").endswith(".find_nest") for s in (got.get("skipped") or [])):
            return False
    # No report yet: OK-WW has not started since the overlay was installed. Say
    # 「cannot tell」 rather than guessing either way.
    return None


def _norm_sha(data: bytes) -> str:
    """sha256 of the content with CRLF folded to LF (the same file checked out on
    Windows and on the Mac must compare equal)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def nest_source_pristine(okww_dir) -> "tuple[bool, str]":
    """Is the NightmareNestTask.py OK-WW runs upstream's own, untouched? (ok, detail)

    The reference is OK-WW's own git checkout (repo/), which its updater pulls from
    the official source; working/ is copied from it and is what runs. Nothing of ours
    edits that file (the nest change lives in ok_tasks/ark_overrides.py), so any
    difference means someone edited the running copy.
    """
    root = Path(okww_dir)
    work = root.joinpath(*_SRC, "task", "NightmareNestTask.py")
    repo = root.joinpath("data", "apps", "ok-ww", "repo", "src", "task", "NightmareNestTask.py")
    try:
        cur = work.read_bytes()
    except OSError as exc:
        return False, f"读不了运行的那份（{exc}）"
    sha = hashlib.sha1(cur).hexdigest()[:10]
    try:
        ref = repo.read_bytes()
    except OSError as exc:
        return False, f"OK-WW 自己的 git 副本读不了（{exc}），没法核对；运行的那份 sha1 {sha}"
    if _norm_sha(cur) != _norm_sha(ref):
        return False, (f"运行的那份（{len(cur)} 字节，sha1 {sha}）和 OK-WW 自己的 git 副本"
                       f"（{len(ref)} 字节，sha1 {hashlib.sha1(ref).hexdigest()[:10]}）不一样，有人改过")
    return True, f"{len(cur)} 字节，sha1 {sha}"


# ── before the run: do the pinned copies still match the source on disk? ─────
# The report above only exists once OK-WW has started with the overrides, and OK-WW
# updates itself on start: 10-04 the queue's own launch went v3.7.2 -> v3.7.3 at 09:18
# and the stale copy was found out by the result check, as an alarm, after the run.
# This reads the files instead, right after the boot pre-update, with the same hash the
# overrides compute (inspect.getsource of the method), so a mismatch is known before
# anything runs.
_PIN = re.compile(r'@override\((\w+), "(\w+)", expect_sha=(_\w+)(, adapt=True)?\)')
_SHA_CONST = re.compile(r'^(_\w+) = "([0-9a-f]{12})"', re.M)
# The copies that check their fingerprint themselves instead of through expect_sha
# (claim_daily, claim_battle_pass: on a mismatch they hand the call to upstream's
# body), written as
#     claim = DailyTask.claim_battle_pass
#     sha = _src_sha(claim)
#     if sha != _BATTLE_PASS_SHA:
# Without this the pre-run drift check missed them (audit 2026-10-13, A3).
_SELF_PIN = re.compile(r'^\s*(\w+) = (\w+)\.(\w+)\s*\n\s*(\w+) = _src_sha\(\1\)\s*\n\s*if \4 != (_\w+):', re.M)
# All of src/: the bases are spread over it (CombatCheck lives in src/combat/).
_SRC = ("data", "apps", "ok-ww", "working", "src")


def pins(text: str | None = None) -> list[tuple[str, str, str, bool]]:
    """(class, method, pinned sha, adapts) for every pinned override in the overrides file:
    the expect_sha= ones, then the ones that check their own fingerprint (never adapted)."""
    text = source_text() if text is None else text
    consts = dict(_SHA_CONST.findall(text))
    out = [(c, m, consts.get(k, ""), bool(a)) for c, m, k, a in _PIN.findall(text)]
    out += [(c, m, consts.get(k, ""), False) for _v, c, m, _s, k in _SELF_PIN.findall(text)]
    return out


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
    # Adapting can still refuse at OK-WW start (find_nest: box top unreadable);
    # that start's report then lists it as skipped, said at the next boot. Until
    # then an adapted copy is not a fault, so its sentence carries none of the
    # words texts._PATCH_TROUBLE turns into the ⚠️ title (audit 2026-10-13, A5):
    # it stays a logged line.
    adapt_part = (f"OK-WW 升级改了 {'、'.join(adapted)}，中继会按新版适配后换上，适配不了就不换，并另外报出来"
                  if adapted else "")
    if not skipped:
        return adapt_part
    line = (f"OK-WW 升级后，中继的改动有 {len(skipped)} 处和新版对不上："
            f"{'、'.join(skipped)} 这一处先按 OK-WW 新版跑，等我们重抄")
    return line + (f"；另外 {adapt_part}" if adapt_part else "")
