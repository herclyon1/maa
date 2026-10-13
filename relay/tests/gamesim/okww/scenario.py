"""Scenario files for the OK-WW game-layer harness (gamesim design section 1, "Scenarios").

One JSON file per case, relay/tests/gamesim/okww/scenarios/<task>/<case>.json. Pure Python, so it
loads on any machine; only the UID-strip check needs OpenCV (OK-WW's Python has it).

Rule 1 of the design is enforced here, at load: every transition, every expectation and the
config each carry an `evidence` string (a ledger line, a recorded frame, a real log line, the
owner's words). A scenario without it does not load.

Shape (keys not listed here are refused, so a typo cannot silently drop an expectation):

    {
      "case": "find_nest_pointer_1007",
      "about": "what the case proves",
      "task": ["src.task.NightmareNestTask", "NightmareNestTask"],
      "start": "<state>",
      "max_s": 1200,                      # optional virtual-second cap (default MAX_S)
      "config": {
        "evidence": "...",
        "task": {"<key>": value},          # set through ok-script's own Config
        "master": {"<Task>.json": {...}},  # files in the master dir MASTER_POINTER names
        "flags": {"no_claim": bool, "no_stamina": bool}
      },
      "states": {
        "<name>": {
          "frame": "<screen-id>/<date>_<time>.png"        # under frames/okww/, sha256 in frames.json
            | "provisional_ocr": [{"text": "...", "box": [x0, y0, x1, y1], "evidence": "..."}]
              and/or "provisional_features": [{"name": "<OK-WW feature>", "box": [x0, y0, x1, y1],
                                               "evidence": "..."}],
          "transitions": [
            {"click": [x0, y0, x1, y1], "to": "<state>", "evidence": "..."},   # relative rectangle
            {"feature": "<name>", "threshold": 0.7, "to": ..., "evidence": ...}, # click in find_one's box
            {"key": "esc", "to": ..., "evidence": ...},
            {"after_s": 30, "to": ..., "evidence": ...}                         # virtual seconds in state
          ],
          "ignore_inputs": false,         # true: inputs that match nothing are recorded, not failed
          "end": false                    # true: entering it stops the task (the scenario is done)
        }
      },
      "expect": {
        "sequence": [                     # ordered subsequence of what happened
          {"decision": "<name>", "value": ..., "evidence": ...},
          {"click": [x, y], "within": 20, "evidence": ...},   # absolute pixels, as OK-WW logs them
          {"key": "esc", "evidence": ...},
          {"state": "<name>", "evidence": ...},
          {"shot": "<name>", "evidence": ...}
        ],
        "end": "<state>" | null,          # the state the run must have reached and stopped in
        "never_states": ["<state>", ...],
        "shots": [{"name": "...", "evidence": "..."}],
        "raises": {"name": "_ArkStop", "evidence": "..."} | null,
        "log": [{"re": "...", "evidence": "..."}],
        "log_never": [{"re": "...", "evidence": "..."}],
        "verdict": null                   # the relay's verdict (design section 3): U8
      }
    }
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / "scenarios"
FRAMES = HERE.parent / "frames" / "okww"
FRAMES_JSON = FRAMES / "frames.json"

# The virtual-time cap of one scenario when it names none: OK-WW's own CI gives its whole
# test step 20 minutes (ok-wuthering-waves v3.7.4 .github/workflows/test.yml, "Run tests"
# timeout-minutes: 20). A task still waiting after that long on a scripted screen is stuck.
MAX_S = 1200

_TOP = {"case", "about", "task", "start", "max_s", "config", "states", "expect"}
_CONFIG = {"evidence", "task", "master", "flags"}
_FLAGS = {"no_claim", "no_stamina"}
_STATE = {"frame", "provisional_ocr", "provisional_features", "transitions", "ignore_inputs", "end",
          "about", "fight"}
_TRANSITION_KINDS = ("click", "feature", "key", "after_s")
_TRANSITION = set(_TRANSITION_KINDS) | {"to", "evidence", "threshold"}
_EXPECT = {"sequence", "end", "never_states", "shots", "raises", "log", "log_never", "verdict"}
_STEP_KINDS = ("decision", "click", "key", "state", "shot")
_STEP = set(_STEP_KINDS) | {"value", "within", "evidence"}


class ScenarioError(ValueError):
    """The file is not a usable scenario; the message says where."""


@dataclass
class Transition:
    kind: str                 # click | feature | key | after_s
    arg: object               # rectangle | feature name | key | seconds
    to: str
    evidence: str
    threshold: float = 0.0    # feature only; 0 = find_one's default


@dataclass
class State:
    name: str
    frame: "Path | None"
    provisional_ocr: "list[dict] | None"
    transitions: "list[Transition]"
    ignore_inputs: bool = False
    end: bool = False
    # Templates the logged screen showed (each with the log line that found or clicked it),
    # answered instead of template matching on a frame that was never recorded.
    provisional_features: "list[dict] | None" = None


@dataclass
class Scenario:
    case: str
    about: str
    task: "tuple[str, str]"
    start: str
    max_s: float
    config: dict
    states: "dict[str, State]"
    expect: dict
    source: str = ""
    frames: "list[Path]" = field(default_factory=list)

    @property
    def provisional(self) -> "list[str]":
        """States that run on OCR text and features from logs instead of a recorded frame (design 6.1)."""
        return [s.name for s in self.states.values()
                if s.provisional_ocr is not None or s.provisional_features is not None]


def _need(cond, where, why):
    if not cond:
        raise ScenarioError(f"{where}: {why}")


def _evidence(d, where):
    ev = d.get("evidence")
    _need(isinstance(ev, str) and ev.strip(), where,
          "needs an `evidence` string (a ledger line, a frame, a log line or the owner's words)")
    return ev


def _keys(d, allowed, where):
    _need(isinstance(d, dict), where, "must be an object")
    extra = sorted(set(d) - allowed)
    _need(not extra, where, f"unknown key(s) {extra}; allowed {sorted(allowed)}")


def _rect(r, where):
    _need(isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) for v in r), where,
          "a rectangle is [x0, y0, x1, y1] relative to the screen")
    x0, y0, x1, y1 = r
    _need(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1, where, f"{r} is not a relative rectangle")
    return tuple(float(v) for v in r)


def frame_index() -> "dict[str, dict]":
    """frames.json by path (relative to frames/okww/)."""
    if not FRAMES_JSON.is_file():
        return {}
    data = json.loads(FRAMES_JSON.read_text(encoding="utf-8"))
    return {f["path"]: f for f in data["frames"]}


def _frame(rel, where, index):
    _need(isinstance(rel, str) and rel, where, "frame must be a path under frames/okww/")
    path = (FRAMES / rel).resolve()
    _need(FRAMES.resolve() in path.parents, where, f"{rel} is outside frames/okww/")
    _need(path.is_file(), where, f"no frame file {path}")
    entry = index.get(rel)
    _need(entry is not None, where, f"{rel} is not in {FRAMES_JSON.name}")
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    _need(got == entry["sha256"], where, f"{rel} sha256 {got[:12]} != {FRAMES_JSON.name} {entry['sha256'][:12]}")
    return path


def _transition(t, where, names):
    _keys(t, _TRANSITION, where)
    kinds = [k for k in _TRANSITION_KINDS if k in t]
    _need(len(kinds) == 1, where, f"exactly one of {list(_TRANSITION_KINDS)}, got {kinds}")
    kind = kinds[0]
    _need(t.get("to") in names, where, f"`to` {t.get('to')!r} is not a state")
    ev = _evidence(t, where)
    if kind == "click":
        arg = _rect(t["click"], where)
    elif kind == "after_s":
        _need(isinstance(t["after_s"], (int, float)) and t["after_s"] > 0, where, "after_s must be > 0")
        arg = float(t["after_s"])
    else:
        _need(isinstance(t[kind], str) and t[kind], where, f"{kind} must be a name")
        arg = t[kind]
    threshold = t.get("threshold", 0.0)
    _need(kind == "feature" or "threshold" not in t, where, "threshold is for feature transitions")
    return Transition(kind, arg, t["to"], ev, float(threshold))


def _state(name, s, index, names):
    where = f"state {name}"
    _keys(s, _STATE, where)
    # Combat is a scripted state whose fake is pinned by the upstream body hash (design 1,
    # rule 2); the echo-farm unit (U7) brings it with its first case.
    _need("fight" not in s, where, "fight states are not supported yet (gamesim U7)")
    has_frame = "frame" in s
    has_prov = "provisional_ocr" in s or "provisional_features" in s
    end = bool(s.get("end", False))
    _need(has_frame + has_prov == 1 or (end and not has_frame and not has_prov), where,
          "needs either `frame` or provisional_ocr / provisional_features (an end state may have neither)")
    frame = _frame(s["frame"], where, index) if has_frame else None
    ocr = _provisional(s, "provisional_ocr", "text", where)
    feats = _provisional(s, "provisional_features", "name", where)
    trans = [_transition(t, f"{where} transitions[{i}]", names) for i, t in enumerate(s.get("transitions", []))]
    _need(not (end and trans), where, "an end state has no transitions")
    return State(name, frame, ocr, trans, bool(s.get("ignore_inputs", False)), end, feats)


def _provisional(s, key, label, where):
    """[{label, box, evidence}] of a provisional state, or None when the state has no `key`."""
    if key not in s:
        return None
    _need(isinstance(s[key], list) and s[key], where, f"{key} is a non-empty list")
    out = []
    for i, b in enumerate(s[key]):
        w = f"{where} {key}[{i}]"
        _keys(b, {label, "box", "evidence"}, w)
        _need(isinstance(b.get(label), str) and b[label], w, f"{label} must be a string")
        out.append({label: b[label], "box": _rect(b.get("box"), w), "evidence": _evidence(b, w)})
    return out


def _expect(e, names):
    _keys(e, _EXPECT, "expect")
    seq = []
    for i, step in enumerate(e.get("sequence", [])):
        where = f"expect.sequence[{i}]"
        _keys(step, _STEP, where)
        kinds = [k for k in _STEP_KINDS if k in step]
        _need(len(kinds) == 1, where, f"exactly one of {list(_STEP_KINDS)}, got {kinds}")
        _evidence(step, where)
        if kinds[0] == "click":
            c = step["click"]
            _need(isinstance(c, list) and len(c) == 2 and isinstance(step.get("within"), (int, float)),
                  where, "a click is [x, y] in pixels with `within` (pixels)")
        if kinds[0] == "decision":
            _need("value" in step, where, "a decision needs its `value`")
        if kinds[0] == "state":
            _need(step["state"] in names, where, f"{step['state']!r} is not a state")
        seq.append(step)
    end = e.get("end")
    _need(end is None or end in names, "expect.end", f"{end!r} is not a state")
    never = e.get("never_states", [])
    _need(all(n in names for n in never), "expect.never_states", f"unknown state in {never}")
    for i, s in enumerate(e.get("shots", [])):
        _keys(s, {"name", "evidence"}, f"expect.shots[{i}]")
        _evidence(s, f"expect.shots[{i}]")
    raises = e.get("raises")
    if raises is not None:
        _keys(raises, {"name", "evidence"}, "expect.raises")
        _evidence(raises, "expect.raises")
    for key in ("log", "log_never"):
        for i, r in enumerate(e.get(key, [])):
            _keys(r, {"re", "evidence"}, f"expect.{key}[{i}]")
            _evidence(r, f"expect.{key}[{i}]")
            try:
                re.compile(r["re"])
            except (re.error, KeyError, TypeError) as exc:
                raise ScenarioError(f"expect.{key}[{i}]: bad regex: {exc}") from None
    # The verdict chain (design section 3) feeds the emitted log to the relay; U8 builds it.
    _need(e.get("verdict") is None, "expect.verdict", "verdicts are not evaluated yet (gamesim U8)")
    return {"sequence": seq, "end": end, "never_states": never, "shots": e.get("shots", []),
            "raises": raises, "log": e.get("log", []), "log_never": e.get("log_never", [])}


def load_dict(d: dict, source: str = "<dict>") -> Scenario:
    _keys(d, _TOP, source)
    for k in ("case", "task", "start", "states", "expect"):
        _need(k in d, source, f"missing `{k}`")
    task = d["task"]
    _need(isinstance(task, list) and len(task) == 2 and all(isinstance(t, str) for t in task), source,
          "task is [module, class], as OK-WW's config.py names its tasks")
    states = d["states"]
    _need(isinstance(states, dict) and states, source, "states must be a non-empty object")
    names = set(states)
    _need(d["start"] in names, source, f"start {d['start']!r} is not a state")
    index = frame_index()
    built = {n: _state(n, s, index, names) for n, s in states.items()}
    cfg = d.get("config", {})
    _keys(cfg, _CONFIG, "config")
    if set(cfg) - {"evidence"}:
        _evidence(cfg, "config")
    _need(isinstance(cfg.get("task", {}), dict), "config.task", "must be an object")
    master = cfg.get("master", {})
    _need(isinstance(master, dict) and all(isinstance(v, dict) for v in master.values()), "config.master",
          "maps a file name to its JSON object")
    _keys(cfg.get("flags", {}), _FLAGS, "config.flags")
    max_s = d.get("max_s", MAX_S)
    _need(isinstance(max_s, (int, float)) and max_s > 0, source, "max_s must be > 0")
    sc = Scenario(case=d["case"], about=d.get("about", ""), task=(task[0], task[1]), start=d["start"],
                  max_s=float(max_s), config=cfg, states=built, expect=_expect(d["expect"], names),
                  source=source)
    sc.frames = sorted({s.frame for s in built.values() if s.frame is not None})
    return sc


def load(path: "str | Path") -> Scenario:
    """A scenario file; a relative path is taken under scenarios/."""
    p = Path(path)
    if not p.is_absolute():
        p = SCENARIOS / p
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"{p}: {exc}") from None
    return load_dict(data, source=str(p))


def uid_strip_dark(frame, box) -> "tuple[bool, int]":
    """Whether every pixel inside `box` (an ok-script Box from OK-WW's config.blur_area) is 0.

    The repository is public; the UID strip of every recorded frame is blacked out
    (design 1, "Privacy"). Returns (all zero, brightest value found)."""
    region = frame[box.y:box.y + box.height, box.x:box.x + box.width]
    peak = int(region.max()) if region.size else 0
    return region.size > 0 and peak == 0, peak
