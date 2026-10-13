"""daysim: the desktop agent (desktop.Desktop) answered from the machine's own records.

On the machine every screen read, OCR of an image file, click and screenshot is a
PowerShell agent started in the desktop session: Desktop._run writes
state/desktop/req-<id>.json, starts the agent, and polls for res-<id>.json
(core/desktop.py). The machine keeps both files for WORK_KEEP_SECONDS, so the
day's pull has them (daydata C/ProgramData/ark-relay/state/desktop/: 460 requests,
458 with their result, pulled 10-13).

FakeDesktop replaces the agent start - the two staticmethods every Desktop
built afterwards uses (`Desktop._spawn_default`, `Desktop._spawn_hidden_default`)
- with a function that reads the request, finds the recorded answer to the same
request, writes it as the result file and returns True; Desktop._run then finds
the result on its first look, with no wait. A request is "the same" when the
focus window, the action list and, for OCR of a file or a click, the file's
name and the text match; among those, the recording nearest the sim time that
was not used yet. A request never recorded gets an empty read (`ok`, no lines)
and a `sim_note` - "nothing on the screen", never an agent failure, which would
log a WARNING the machine never logged.

Screenshots are not in the pull (only the JSONs), so `screenshot()` returns
None in the sim and an evidence bundle has no picture.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC8 = timezone(timedelta(hours=8))
UNRECORDED = {"ok": True, "ocr": [], "log": ["daysim: no recorded answer"]}
_REAL: dict = {}


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC8).isoformat(timespec="seconds")


def _base(path: str) -> str:
    return re.split(r"[\\/]", str(path or ""))[-1]


def request_key(req: dict) -> tuple:
    """What makes two agent requests the same question."""
    acts = []
    for a in req.get("actions") or []:
        act = str(a.get("act") or "")
        if act == "ocrfile":
            acts.append((act, _base(a.get("path"))))
        elif act == "click_text":
            acts.append((act, str(a.get("text") or "")))
        elif act == "wait":
            acts.append((act, int(a.get("ms") or 0)))
        else:
            acts.append((act, json.dumps({k: v for k, v in a.items() if k != "act"}, sort_keys=True)))
    return (req.get("focus"), tuple(acts))


class FakeDesktop:
    def __init__(self, sched, recorded_dir=None):
        self.sched = sched
        self.recorded: "dict[tuple, list[dict]]" = {}    # key -> [{t, res, used}]
        self.asked: "list[dict]" = []                    # every request: t, key, answered
        if recorded_dir is not None:
            self.load(Path(recorded_dir))

    def load(self, folder: Path) -> int:
        """Every req-<id>.json with its res-<id>.json; the time is the request's
        mtime (the pull keeps mtimes). -> pairs loaded."""
        n = 0
        for req in sorted(folder.glob("req-*.json")):
            res = req.with_name("res-" + req.name[len("req-"):])
            if not res.is_file():
                continue
            try:
                q = json.loads(req.read_text(encoding="utf-8-sig"))
                a = json.loads(res.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            self.add(req.stat().st_mtime, q, a)
            n += 1
        return n

    def add(self, t: float, req: dict, res: dict) -> None:
        """One recorded pair (events.jsonl kind "desktop" feeds these too)."""
        self.recorded.setdefault(request_key(req), []).append({"t": float(t), "res": res, "used": False})

    def answer(self, req: dict) -> dict:
        now = float(self.sched.now())
        key = request_key(req)
        cands = self.recorded.get(key) or []
        fresh = [c for c in cands if not c["used"]]
        pool = fresh or cands
        if not pool:
            self.sched.out("sim_note", t=iso(now), what="desktop request not recorded",
                           focus=req.get("focus"), acts=[a[0] for a in key[1]])
            self.asked.append({"t": now, "key": key, "answered": False})
            return dict(UNRECORDED)
        best = min(pool, key=lambda c: abs(c["t"] - now))
        if not fresh:
            self.sched.out("sim_note", t=iso(now), what="desktop answer reused", focus=req.get("focus"))
        best["used"] = True
        self.asked.append({"t": now, "key": key, "answered": True, "recorded_at": best["t"]})
        out = {k: v for k, v in best["res"].items() if k != "shot"}
        return out

    def spawn(self, exe, cwd, args) -> bool:
        """Stands in for the agent start: args end with the request and result paths."""
        req_path, res_path = Path(args[-2]), Path(args[-1])
        req = json.loads(req_path.read_text(encoding="utf-8-sig"))
        data = json.dumps(self.answer(req), ensure_ascii=False)
        tmp = res_path.with_name(res_path.name + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, res_path)
        return True

    def install(self) -> "FakeDesktop":
        from ark_relay.core import desktop  # noqa: PLC0415 - the relay is on sys.path by now
        if _REAL:
            raise RuntimeError("FakeDesktop already installed")
        _REAL.update(cls=desktop.Desktop, spawn=desktop.Desktop.__dict__["_spawn_default"],
                     hidden=desktop.Desktop.__dict__["_spawn_hidden_default"])
        desktop.Desktop._spawn_default = staticmethod(self.spawn)
        desktop.Desktop._spawn_hidden_default = staticmethod(self.spawn)
        return self

    @staticmethod
    def uninstall() -> None:
        if not _REAL:
            return
        _REAL["cls"]._spawn_default = _REAL["spawn"]
        _REAL["cls"]._spawn_hidden_default = _REAL["hidden"]
        _REAL.clear()
