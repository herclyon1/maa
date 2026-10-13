"""An uninstall that fails part way still does every other step and says what is left.

2026-10-13 (audit of the install / switch-over block, item 2): after `switch.py
uninstall` had stopped the relay and put AUTO-MAS back, any exception (a state link that
would not go, a locked leftover file, an unreadable legacy-items.json) ended Python with
exit 1, skipping the rest; the uninstaller treated every non-zero exit as "AUTO-MAS not
put back" and said 「中继已经重新开起来，什么都没删」 - with no relay, no watchdog and
nothing restarted. Now each step after the rollback runs on its own, legacy.remove()
tries each item on its own, a partial uninstall exits 7 with the failed steps in
uninstall-left.txt, and the installer script shows that message only for exit 3.
Fakes for every Windows call; no Windows needed.
"""
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(ROOT / "packaging"))

import legacy  # noqa: E402
import switch  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def quiet(fn, *args):
    """fn's result with its prints swallowed; an exception becomes its name (a failed
    check, not a crash)."""
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args)
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}"


NAMES = ("APP", "stop", "start", "_handover_rollback", "run", "delete_task_folder",
         "_mark_watchdog_stopped")


def uninstall_in(tmp: Path, *, rollback_rc=0, raise_in=""):
    """switch.uninstall() with every Windows call faked; the steps taken, its code and
    the uninstall-left.txt text ('' = none)."""
    steps = []
    app = tmp / "ArkRelay"
    (app / "versions" / "1300").mkdir(parents=True, exist_ok=True)
    left_file = tmp / "uninstall-left.txt"

    def maybe_raise(name):
        steps.append(name)
        if name == raise_in:
            raise OSError(f"{name} is locked")

    def fake_run(*cmd):
        name = "watchdog remove" if "ark_watchdog.py" in " ".join(map(str, cmd)) else "task delete"
        maybe_raise(name)
        return 0

    saved = [getattr(switch, n) for n in NAMES] + [legacy.remove, getattr(switch, "UNINSTALL_LEFT", None)]
    switch.APP = app
    switch.stop = lambda: steps.append("stop") or 0
    switch.start = lambda: steps.append("start") or 0
    switch._handover_rollback = lambda: steps.append("rollback") or rollback_rc
    switch.run = fake_run
    switch.delete_task_folder = lambda: maybe_raise("task folder") or True
    switch._mark_watchdog_stopped = lambda on: maybe_raise("marker")
    legacy.remove = lambda: maybe_raise("legacy remove") or []
    switch.UNINSTALL_LEFT = left_file
    try:
        rc = quiet(switch.uninstall)
    finally:
        for n, v in zip(NAMES, saved[:len(NAMES)], strict=True):
            setattr(switch, n, v)
        legacy.remove = saved[len(NAMES)]
        if saved[-1] is None:
            del switch.UNINSTALL_LEFT
        else:
            switch.UNINSTALL_LEFT = saved[-1]
    left = left_file.read_text(encoding="utf-8") if left_file.exists() else ""
    return steps, rc, left


ALL = ["stop", "rollback", "watchdog remove", "marker", "task delete", "task folder",
       "legacy remove"]

with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    print("[everything works: exit 0, nothing listed]")
    steps, rc, left = uninstall_in(t / "a")
    check("every step", steps, ALL)
    check("exit 0", rc, 0)
    check("no uninstall-left.txt", left, "")

    print("[AUTO-MAS not put back: nothing removed, relay started, exit 3]")
    steps, rc, left = uninstall_in(t / "b", rollback_rc=1)
    check("steps", steps, ["stop", "rollback", "start"])
    check("exit 3", rc, 3)

    for broken in ("watchdog remove", "marker", "task delete", "task folder", "legacy remove"):
        print(f"[{broken} raises: every other step still runs, exit 7, listed]")
        steps, rc, left = uninstall_in(t / broken.replace(" ", "-"), raise_in=broken)
        check(f"{broken}: every step tried", steps, ALL)
        check(f"{broken}: exit 7 (not 0, not 3)", rc, 7)
        check(f"{broken}: listed in uninstall-left.txt", f"{broken} is locked" in left, True)

print("[legacy.remove: one item that fails does not stop the rest]")
deleted, runs = [], []
saved = (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
         legacy.service_exists, legacy.TAKEOVER_RECORD)


def fake_delete(p):
    if "locked" in str(p):
        raise PermissionError(f"{p} in use")
    deleted.append(str(p))
    return []


legacy.items = lambda: [
    {"kind": "file", "path": "C:\\locked.bat", "action": "remove"},
    {"kind": "file", "path": "C:\\free.bat", "action": "remove"},
    {"kind": "task", "name": "ark-old", "action": "remove"},
    {"kind": "service", "name": "ark-svc", "action": "takeover"},
    {"kind": "file", "path": "C:\\kept.txt", "action": "keep"},
]
legacy._delete_path = fake_delete
legacy._run = lambda *cmd: runs.append(" ".join(cmd)) or (5 if cmd[:2] == ("sc", "delete") else 0)
legacy._task_names = lambda: ["ark-old"]
legacy.service_exists = lambda name: True
with tempfile.TemporaryDirectory() as t:
    legacy.TAKEOVER_RECORD = Path(t) / "legacy-takeover.json"
    try:
        out = quiet(legacy.remove)
    finally:
        (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
         legacy.service_exists, legacy.TAKEOVER_RECORD) = saved
check("the items after the locked one still removed",
      (deleted, "schtasks /delete /tn ark-old /f" in runs), (["C:\\free.bat"], True))
check("returns what was not removed (the locked file, the failed sc delete)",
      isinstance(out, list) and len(out) == 2 and "locked.bat" in out[0] and "ark-svc" in out[1], True)
legacy.items = lambda: (_ for _ in ()).throw(ValueError("bad json"))
try:
    out = quiet(legacy.remove)
finally:
    legacy.items = saved[0]
check("an unreadable list is one failure, not an exception",
      isinstance(out, list) and len(out) == 1 and "bad json" in out[0], True)

print("[uninstall removes the OK-WW overlay file, and nothing else in OK-WW]")
# gamesim U9 reported that no code removes ok_tasks/ark_overrides.py (its install cycle
# deleted the file itself). It is removed: legacy-items.json lists it as a `file` item with
# action `takeover`, and legacy.remove() deletes every remove/takeover item. Pinned here with
# the real list, the real remove() and the real _delete_path.
sys.path.insert(0, str(RELAY))
from pathlib import PureWindowsPath  # noqa: E402
from ark_relay.features.okww_patch import okww_overlay  # noqa: E402

OKWW_ROOT = PureWindowsPath(r"D:\ark\okww")     # the machine's OK-WW folder (legacy-items.json)
want = PureWindowsPath(*okww_overlay._WORKING, okww_overlay.TASKS_DIR, okww_overlay.FILE_NAME)
saved_items_file = legacy.ITEMS
legacy.ITEMS = RELAY / "handover" / "legacy-items.json"     # handover\ next to legacy.py when packaged
real_items = legacy.items()
ours = [it for it in real_items if it.get("kind") == "file"
        and PureWindowsPath(it["path"]).name == okww_overlay.FILE_NAME]
check("legacy-items.json lists the overlay file once, as removed at uninstall",
      [(it["action"] in ("remove", "takeover"), PureWindowsPath(it["path"]) == OKWW_ROOT / want) for it in ours],
      [(True, True)])
asked = []
saved = (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
         legacy.service_exists, legacy.TAKEOVER_RECORD)
legacy._delete_path = lambda p: asked.append(PureWindowsPath(str(p))) or []
legacy._run = lambda *cmd: 0
legacy._task_names = lambda: []
legacy.service_exists = lambda name: False
with tempfile.TemporaryDirectory() as t:
    legacy.TAKEOVER_RECORD = Path(t) / "legacy-takeover.json"
    try:
        quiet(legacy.remove)
    finally:
        (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
         legacy.service_exists, legacy.TAKEOVER_RECORD) = saved
        legacy.ITEMS = saved_items_file
check("remove() with the real list deletes the overlay file", OKWW_ROOT / want in asked, True)
check("and nothing else under OK-WW's folder",
      [str(p) for p in asked if str(p).lower().startswith(str(OKWW_ROOT).lower() + "\\")
       and not (p.match("*.py.bak-*") and p.parent.name == "task")], [str(OKWW_ROOT / want)])
with tempfile.TemporaryDirectory() as t:
    root = Path(t) / "okww"
    dest = okww_overlay.target(root)
    dest.parent.mkdir(parents=True)
    dest.write_text("# ours\n", encoding="utf-8")
    theirs = dest.parent / "user_task.py"           # a task the owner put there himself
    theirs.write_text("# his\n", encoding="utf-8")
    upstream = root.joinpath(*okww_overlay._WORKING, "src", "task", "DailyTask.py")
    upstream.parent.mkdir(parents=True)
    upstream.write_text("# upstream\n", encoding="utf-8")
    local = {**ours[0], "path": str(root.joinpath(*PureWindowsPath(ours[0]["path"]).relative_to(OKWW_ROOT).parts))} \
        if ours else {}
    failed, _ = quiet(legacy._remove_one, local, None) if ours else ([], None)
    check("the real removal of that item: our file gone, his task and upstream's file kept",
          (failed, dest.exists(), theirs.exists(), upstream.exists()), ([], False, True, True))

print("[the uninstaller: 「中继已经重新开起来，什么都没删」 only for exit 3]")
iss = (ROOT / "packaging" / "ark-relay.iss").read_text(encoding="utf-8-sig")
m = re.search(r"\nprocedure CurUninstallStepChanged\b.*?\nend;", iss, re.S)
body = m.group(0) if m else ""
branches = re.split(r"\n    (?:else )?if Rc ", body)
restarted = [b.split("\n", 1)[0] for b in branches if "中继已经重新开起来，什么都没删" in b]
check("that message sits only in the Rc = 3 branch", restarted, ["= 3 then"])
seven = next((b for b in branches if b.startswith("= 7 then")), "")
check("exit 7 shows what is left (uninstall-left.txt) and does not abort",
      ("UninstallLeft()" in seven, "RaiseException" in seven), (True, False))
check("the left list is read from the file switch.py writes",
      "uninstall-left.txt" in iss and switch.UNINSTALL_LEFT.name == "uninstall-left.txt"
      if hasattr(switch, "UNINSTALL_LEFT") else False, True)
other = next((b for b in branches if b.startswith("<> 0 then")), "")
check("any other code starts the relay again before aborting",
      0 <= other.find("RunSwitch('start')") < other.find("RaiseException"), True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
