"""Hand AUTO-MAS the jobs it already does, at switch-over time.

Run by the installer's switch-over step (and by uninstall / rollback), with the
packaged Python and nothing but the standard library: it must not import
ark_relay, whose layout is being moved while this file is written.

    python automas_handover.py plan      [--state-dir DIR] [--okww-dir DIR] [--with-wuwa-update]
    python automas_handover.py apply     [same options]
    python automas_handover.py rollback  [--state-dir DIR]

`plan` reads only. `apply` changes AUTO-MAS settings through its own backend
(POST http://127.0.0.1:<ARK_MAS_PORT or 36163>/api/...) and reads every value
back; the values it replaced are saved to <state-dir>/automas-handover.json
first, and `rollback` puts exactly those back. Exit code 0 = every step done
(or already in place), 1 = a step was refused or could not be read back,
2 = the backend could not be reached at all.

Never edits AUTO-MAS's config files: while AUTO-MAS runs it writes its
in-memory copy back over them (relay/ark_relay/annihilation.py `_write_via_api`,
the 2026-08-31 04:01 wipe), so only the backend's own update endpoints are used.
The backend refuses updates while a task runs (HTTP 200 with `code` != 200);
that is reported as a refusal, and the step is safe to run again later.

What it hands over (BOARD/新中继-重叠可撤核对.md, checked against AUTO-MAS
v5.7.0-beta.1 source and the machine's config on 2026-10-11):

  13  weekly annihilation  MAA user Info.Annihilation: "Close" (the old relay's
                           weekly switch) back to the map it saved
                           (state.json weekly.annihilation.restore_to). AUTO-MAS
                           then keeps its own weekly record
                           (Data.AnnihilationCompletedWeek), which it only does
                           with Info.IfQuickConfig on - checked, not changed.
  10a Arknights client     MAA script Run.IfCheckGameUpdate and
                           Run.IfAutoInstallGameApk -> true (Official server
                           only; Info.Server is checked).
  10b WuWa client          OK-WW script Game.Enabled -> true and Game.Path ->
                           the Kuro launcher. Only with --with-wuwa-update: it
                           hands the game's start and stop to AUTO-MAS and the
                           patch download counts against the 120-minute hard
                           limit, so it needs one trial run on an update day.
  20  AUTO-MAS autostart   Config Start.IfSelfStart must be true (AUTO-MAS then
                           keeps its own AUTO-MAS_AutoStart logon task) -
                           checked, set to true when false.
  9a, 9b, 1, 3, 16         no AUTO-MAS setting to change: the relay code that
                           duplicated them is removed (list in the board file
                           打包-交接AUTO-MAS-删代码清单-1011.md); `plan` prints
                           the values those removals rely on.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_DIR = Path(r"C:\ProgramData\ark-relay\state")
DEFAULT_OKWW_DIR = Path(r"D:\ark\okww")
BACKUP_FILE = "automas-handover.json"
# AUTO-MAS's own default for Info.Annihilation (app/models/config.py, MAA user).
ANNIHILATION_DEFAULT = "Annihilation"


class Unreachable(Exception):
    """The backend did not answer at all."""


class Refused(Exception):
    """The backend answered but did not take the change, or read back something else."""


def base() -> str:
    return f"http://127.0.0.1:{os.environ.get('ARK_MAS_PORT', '36163')}"


def mas(path: str, body: dict | None = None, timeout: int = 20) -> dict:
    """POST to the backend; every endpoint is POST, reads included."""
    req = urllib.request.Request(base() + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            reply = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # it answered: a refusal, not "unreachable"
        raise Refused(f"{path}: HTTP {exc.code} {exc.read()[:200]!r}") from exc
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise Unreachable(f"{path}: {exc}") from exc
    if isinstance(reply, dict) and "code" in reply and reply.get("code") != 200:
        raise Refused(f"{path}: {reply.get('message') or reply.get('code')}")
    return reply


def dig(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            raise KeyError(path)
        obj = obj[part]
    return obj


def nest(path: str, value) -> dict:
    out: dict = {}
    cur = out
    parts = path.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
    return out


# ---------- where each value lives ----------

def script_id(name: str) -> str:
    """The script whose Info.Name is `name` (MAA / MaaEnd / OK-WW), by name as the relay does."""
    for sid, sc in (mas("/api/scripts/get").get("data") or {}).items():
        if isinstance(sc, dict) and str((sc.get("Info") or {}).get("Name") or "").lower() == name.lower():
            return sid
    raise Refused(f"no script named {name!r}")


def first_user(sid: str) -> tuple[str, dict]:
    users = mas("/api/scripts/user/get", {"scriptId": sid}).get("data") or {}
    for uid, user in users.items():
        if isinstance(user, dict):
            return uid, user
    raise Refused(f"script {sid} has no user")


class Target:
    """One setting: how to read it and how to write it."""

    def __init__(self, kind: str, script: str, path: str):
        self.kind, self.script, self.path = kind, script, path

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.script}:{self.path}"

    def read(self):
        if self.kind == "setting":
            return dig(mas("/api/setting/get").get("data") or {}, self.path)
        sid = script_id(self.script)
        if self.kind == "script":
            return dig((mas("/api/scripts/get").get("data") or {})[sid], self.path)
        return dig(first_user(sid)[1], self.path)

    def write(self, value) -> None:
        if self.kind == "setting":
            mas("/api/setting/update", {"data": nest(self.path, value)})
        else:
            sid = script_id(self.script)
            if self.kind == "script":
                mas("/api/scripts/update", {"scriptId": sid, "data": nest(self.path, value)})
            else:
                uid, _ = first_user(sid)
                mas("/api/scripts/user/update", {"scriptId": sid, "userId": uid, "data": nest(self.path, value)})
        now = self.read()
        if now != value:
            raise Refused(f"{self.key}: wrote {value!r}, reads back {now!r}")


# ---------- the steps ----------

def annihilation_restore(state_dir: Path) -> str:
    """The map the old relay saved before closing annihilation for the week."""
    try:
        data = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
        saved = ((data.get("weekly") or {}).get("annihilation") or {}).get("restore_to")
    except (OSError, ValueError, AttributeError):
        saved = None
    return str(saved or ANNIHILATION_DEFAULT)


def wuwa_launcher(okww_dir: Path) -> Path | None:
    """The Kuro launcher, found the way relay/ark_relay/gameupdate_games.py finds
    it: the game exe named in OK-WW's configs, then launcher.exe in a sibling
    "Wuthering Waves" folder or the game folder's parent."""
    game = None
    for f in (okww_dir / "data" / "apps" / "ok-ww" / "working" / "configs").glob("*.json"):
        try:
            m = re.search(r'"([^"]*Wuthering Waves\.exe)"', f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if m and Path(m.group(1).replace("\\\\", "\\")).exists():
            game = Path(m.group(1).replace("\\\\", "\\"))
            break
    if game is None:
        fallback = Path(r"D:\Wuthering Waves Game\Wuthering Waves.exe")
        game = fallback if fallback.exists() else None
    if game is None:
        return None
    parent = game.parent.parent
    for cand in (parent / "Wuthering Waves" / "launcher.exe", parent / "launcher.exe"):
        if cand.is_file():
            return cand
    return None


def steps(state_dir: Path, okww_dir: Path, with_wuwa: bool) -> list[dict]:
    """Each step: id, target, want (value or callable(current) -> value), checks."""
    out = [
        {"id": "13", "what": "weekly annihilation back to AUTO-MAS",
         "target": Target("user", "MAA", "Info.Annihilation"),
         "want": lambda cur: annihilation_restore(state_dir) if cur == "Close" else cur,
         "require": [(Target("user", "MAA", "Info.IfQuickConfig"), True)]},
        {"id": "10a", "what": "Arknights client update by AUTO-MAS (check)",
         "target": Target("script", "MAA", "Run.IfCheckGameUpdate"), "want": lambda cur: True,
         "require": [(Target("user", "MAA", "Info.Server"), "Official")]},
        {"id": "10a", "what": "Arknights client update by AUTO-MAS (install)",
         "target": Target("script", "MAA", "Run.IfAutoInstallGameApk"), "want": lambda cur: True,
         "require": [(Target("user", "MAA", "Info.Server"), "Official")]},
        {"id": "20", "what": "AUTO-MAS keeps its own logon autostart",
         "target": Target("setting", "", "Start.IfSelfStart"), "want": lambda cur: True, "require": []},
    ]
    if with_wuwa:
        launcher = wuwa_launcher(okww_dir)
        path_step = {"id": "10b", "what": "WuWa launcher path for AUTO-MAS",
                     "target": Target("script", "OK-WW", "Game.Path"),
                     "want": (lambda cur, p=launcher: str(p) if p else None), "require": []}
        out.append(path_step)
        if launcher is not None:  # never let AUTO-MAS start the game without the launcher it updates through
            need_path = [(Target("script", "OK-WW", "Game.Path"), str(launcher))]
            out += [
                {"id": "10b", "what": "WuWa auto update",
                 "target": Target("script", "OK-WW", "Game.IfAutoUpdate"), "want": lambda cur: True,
                 "require": need_path},
                {"id": "10b", "what": "AUTO-MAS starts and updates WuWa",
                 "target": Target("script", "OK-WW", "Game.Enabled"), "want": lambda cur: True,
                 "require": need_path},
            ]
    return out


# Read-only facts the code removals (9a, 9b, 1, 3, 16) rely on; printed by `plan`.
FACTS = [
    ("1", Target("script", "MAA", "Run.HardTimeLimit")),
    ("1", Target("script", "MaaEnd", "Run.HardTimeLimit")),
    ("1", Target("script", "OK-WW", "Run.HardTimeLimit")),
    ("1", Target("script", "OK-WW", "Run.RunTimeLimit")),
    ("13", Target("user", "MAA", "Data.AnnihilationCompletedWeek")),
    ("13", Target("user", "MAA", "Info.AnnihilationStartWeekday")),
]


def _backup_path(state_dir: Path) -> Path:
    return state_dir / BACKUP_FILE


def plan(state_dir: Path, okww_dir: Path, with_wuwa: bool, do_apply: bool) -> int:
    bad = 0
    saved: dict = {}
    if do_apply and _backup_path(state_dir).exists():
        saved = json.loads(_backup_path(state_dir).read_text(encoding="utf-8")).get("old") or {}
    for st in steps(state_dir, okww_dir, with_wuwa):
        t = st["target"]
        try:
            missing = [(r.key, want, r.read()) for r, want in st["require"]]
            missing = [m for m in missing if m[2] != m[1]]
            cur = t.read()
            want = st["want"](cur)
        except (Refused, KeyError) as exc:
            print(f"[{st['id']}] {st['what']}: cannot read: {exc}")
            bad += 1
            continue
        if missing:
            print(f"[{st['id']}] {st['what']}: skipped, needs " +
                  "; ".join(f"{k}={w!r} (is {c!r})" for k, w, c in missing))
            bad += 1
            continue
        if want is None:
            print(f"[{st['id']}] {st['what']}: no value found (launcher.exe not found)")
            bad += 1
            continue
        if cur == want:
            print(f"[{st['id']}] {st['what']}: already {cur!r}")
            continue
        if not do_apply:
            print(f"[{st['id']}] {st['what']}: {t.key} {cur!r} -> {want!r}")
            continue
        saved.setdefault(t.key, cur)  # the value before the first apply, never overwritten
        _backup_path(state_dir).parent.mkdir(parents=True, exist_ok=True)
        _backup_path(state_dir).write_text(json.dumps(
            {"old": saved, "at": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            t.write(want)
            print(f"[{st['id']}] {st['what']}: {t.key} {cur!r} -> {want!r}, read back")
        except Refused as exc:
            print(f"[{st['id']}] {st['what']}: refused: {exc}")
            bad += 1
    if not do_apply:
        for sid, t in FACTS:
            try:
                print(f"[{sid}] fact {t.key} = {t.read()!r}")
            except (Refused, KeyError) as exc:
                print(f"[{sid}] fact {t.key}: cannot read: {exc}")
    return 1 if bad else 0


def rollback(state_dir: Path) -> int:
    p = _backup_path(state_dir)
    if not p.exists():
        print("nothing to roll back: no " + BACKUP_FILE)
        return 0
    old = json.loads(p.read_text(encoding="utf-8")).get("old") or {}
    bad = 0
    for key, value in old.items():
        kind, script, path = key.split(":", 2)
        try:
            Target(kind, script, path).write(value)
            print(f"restored {key} = {value!r}")
        except (Refused, KeyError) as exc:
            print(f"could not restore {key}: {exc}")
            bad += 1
    if not bad:
        p.unlink()
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("plan", "apply", "rollback"))
    ap.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    ap.add_argument("--okww-dir", type=Path, default=DEFAULT_OKWW_DIR)
    ap.add_argument("--with-wuwa-update", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.action == "rollback":
            return rollback(a.state_dir)
        return plan(a.state_dir, a.okww_dir, a.with_wuwa_update, a.action == "apply")
    except Unreachable as exc:
        print(f"AUTO-MAS backend not reachable: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
