"""Read the YAML AUTO-MAS writes - and only that much YAML.

* block mappings and sequences, including a sequence at its parent key's indent;
* plain scalars (null / ~, YAML 1.1 booleans, ints, floats, else strings), folded over lines;
* single- and double-quoted scalars, folded over lines (scripts.yaml folds long JSON strings);
* the empty flow collections {} and [].

Anything else - a non-empty flow collection, a block scalar (| or >), an anchor or a tag - is
refused with ValueError rather than guessed at. Keys are always strings, as they were in the
JSON. Checked against PyYAML on the machine's own files (relay/tests/test_mas.py
has synthetic copies of every construct; the repo is public, so not the files themselves).
"""
from __future__ import annotations

import sys as _sys
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from ark_relay.core.config import atomic_write_text, master_config_dir
from ark_relay.features import errwatch
from ark_relay.core import texts
masuser = _sys.modules[__name__]  # tests read mastercfg.masuser

_BOOL = {"yes": True, "true": True, "on": True, "no": False, "false": False, "off": False}
_INT = re.compile(r"[-+]?[0-9]+")
_FLOAT = re.compile(r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?")
_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f",
            "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85",
            "_": "\xa0", "L": " ", "P": " "}
_HEX = {"x": 2, "u": 4, "U": 8}


def loads(text: str):
    """The document in `text` as dicts, lists and scalars."""
    p = _Parser(text.splitlines())
    p.skip()
    if p.i >= len(p.lines):
        return None
    value = p.node(p.indent())
    p.skip()
    if p.i < len(p.lines):
        raise ValueError(f"line {p.i + 1}: unexpected content after the document")
    return value


def _miniyaml_plain(s: str):
    if s in ("", "~") or s.lower() == "null":
        return None
    if s.lower() in _BOOL:
        return _BOOL[s.lower()]
    if _INT.fullmatch(s):
        return int(s)
    if _FLOAT.fullmatch(s) and any(c.isdigit() for c in s):
        return float(s)
    if s.lower() in (".inf", "+.inf"):
        return float("inf")
    if s.lower() == "-.inf":
        return float("-inf")
    if s.lower() == ".nan":
        return float("nan")
    return s


class _Parser:
    def __init__(self, lines: list[str]):
        self.lines = list(lines)
        self.i = 0

    def skip(self) -> None:
        while self.i < len(self.lines) and (not self.lines[self.i].strip()
                                            or self.lines[self.i].lstrip().startswith("#")):
            self.i += 1

    def indent(self) -> int:
        line = self.lines[self.i]
        return len(line) - len(line.lstrip(" "))

    def body(self) -> str:
        return self.lines[self.i].strip()

    def node(self, ind: int):
        b = self.body()
        if b == "-" or b.startswith("- "):
            return self.sequence(ind)
        if self.split_key(b) is not None:
            return self.mapping(ind)
        return self.scalar(b, ind - 1)

    def split_key(self, b: str) -> "tuple[str, str] | None":
        """(key, rest) when `b` is a mapping entry, else None."""
        if b[:1] in ("'", '"'):
            q = b[0]
            j = 1
            while j < len(b):
                if b[j] == q:
                    if q == "'" and b[j + 1:j + 2] == "'":
                        j += 2
                        continue
                    break
                j += 2 if (q == '"' and b[j] == "\\") else 1
            after = b[j + 1:]
            if after == ":" or after.startswith(": "):
                return _Parser([b[1:j + 1]]).quoted_line(q), after[1:].strip()
            return None
        if b[:1] in ("{", "[", "|", ">", "&", "*", "!"):
            return None
        if b.endswith(":") and ": " not in b:
            return b[:-1], ""
        k = b.find(": ")
        return (b[:k], b[k + 2:].strip()) if k > 0 else None

    def quoted_line(self, q: str) -> str:
        # A quoted key: the text up to and including its closing quote, on one line.
        return self.quoted(self.lines[0], q, consume=False)

    def mapping(self, ind: int) -> dict:
        out: dict = {}
        while True:
            self.skip()
            if self.i >= len(self.lines) or self.indent() != ind:
                break
            b = self.body()
            if b == "-" or b.startswith("- "):
                break
            kv = self.split_key(b)
            if kv is None:
                raise ValueError(f"line {self.i + 1}: expected 'key: value', got {b[:40]!r}")
            key, rest = kv
            if rest:
                out[str(key)] = self.scalar(rest, ind)
                continue
            self.i += 1
            self.skip()
            if self.i < len(self.lines) and self.indent() > ind:
                out[str(key)] = self.node(self.indent())
            elif self.i < len(self.lines) and self.indent() == ind and (
                    self.body() == "-" or self.body().startswith("- ")):
                out[str(key)] = self.sequence(ind)
            else:
                out[str(key)] = None
        return out

    def sequence(self, ind: int) -> list:
        out: list = []
        while True:
            self.skip()
            if self.i >= len(self.lines) or self.indent() != ind:
                break
            b = self.body()
            if not (b == "-" or b.startswith("- ")):
                break
            content = b[2:].strip()
            if not content:
                self.i += 1
                self.skip()
                out.append(self.node(self.indent()) if self.i < len(self.lines)
                           and self.indent() > ind else None)
                continue
            # The item's own content, re-read as if it started on a line of its own at ind + 2.
            self.lines[self.i] = " " * (ind + 2) + content
            out.append(self.node(ind + 2))
        return out

    def scalar(self, rest: str, parent: int):
        """The value `rest` begins on the current line; consumes it and any continuation."""
        if rest[:1] in ("'", '"'):
            return self.quoted(rest[1:], rest[0])
        if rest == "{}":
            self.i += 1
            return {}
        if rest == "[]":
            self.i += 1
            return []
        if rest[:1] in ("{", "[", "|", ">", "&", "*", "!"):
            raise ValueError(f"line {self.i + 1}: unsupported YAML construct {rest[:20]!r}")
        if " #" in rest:
            rest = rest[:rest.index(" #")].rstrip()
        parts = [rest]
        self.i += 1
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                # A blank line inside a plain scalar is a line break, if the scalar goes on.
                j = self.i
                while j < len(self.lines) and not self.lines[j].strip():
                    j += 1
                if j < len(self.lines) and len(self.lines[j]) - len(self.lines[j].lstrip(" ")) > parent:
                    parts.append("\n" * (j - self.i))
                    self.i = j
                    continue
                break
            if len(line) - len(line.lstrip(" ")) <= parent or line.lstrip().startswith("#"):
                break
            parts.append(" " + line.strip() if not parts[-1].endswith("\n") else line.strip())
            self.i += 1
        return _miniyaml_plain("".join(parts)) if len(parts) == 1 else "".join(parts)

    def quoted(self, text: str, q: str, consume: bool = True) -> str:
        """A quoted scalar whose text after the opening quote is `text`, folded over lines."""
        out: list[str] = []
        while True:
            j, escaped_break = 0, False
            while j < len(text):
                c = text[j]
                if c == q:
                    if q == "'" and text[j + 1:j + 2] == "'":
                        out.append("'")
                        j += 2
                        continue
                    if consume:
                        tail = text[j + 1:].strip()
                        if tail and not tail.startswith("#"):
                            raise ValueError(f"line {self.i + 1}: text after a closing quote")
                        self.i += 1
                    return "".join(out)
                if q == '"' and c == "\\":
                    if j + 1 == len(text):
                        escaped_break = True
                        break
                    e = text[j + 1]
                    if e in _HEX:
                        n = _HEX[e]
                        out.append(chr(int(text[j + 2:j + 2 + n], 16)))
                        j += 2 + n
                        continue
                    if e not in _ESCAPES:
                        raise ValueError(f"line {self.i + 1}: unknown escape \\{e}")
                    out.append(_ESCAPES[e])
                    j += 2
                    continue
                out.append(c)
                j += 1
            if not consume:
                raise ValueError("unterminated quoted key")
            if not escaped_break:
                while out and out[-1] in " \t":
                    out.pop()
            self.i += 1
            blanks = 0
            while self.i < len(self.lines) and not self.lines[self.i].strip():
                blanks += 1
                self.i += 1
            if self.i >= len(self.lines):
                raise ValueError("unterminated quoted scalar")
            out.append("\n" * blanks if blanks else ("" if escaped_break else " "))
            text = self.lines[self.i].lstrip(" \t")


# key -> the group AUTO-MAS v5.7.0-beta.3 keeps it in (Info before that).
MOVED = {
    "Stage": "Stage", "Stage_1": "Stage", "Stage_2": "Stage", "Stage_3": "Stage",
    "StageMode": "Stage", "MedicineNumb": "Stage", "SeriesNumb": "Stage",
    "Annihilation": "Task", "AnnihilationStartWeekday": "Task",
    "InfrastMode": "Task", "InfrastName": "Task",
}


def group_of(user: dict, key: str) -> str:
    """The group that holds `key` for this user: its new group when the user has it there,
    else Info (an AUTO-MAS from before v5.7.0-beta.3)."""
    new = MOVED.get(key)
    if new and isinstance(user.get(new), dict) and key in user[new]:
        return new
    return "Info"


def get(user: dict, key: str, default=None):
    """The value of `key` wherever this user keeps it."""
    return (user.get(group_of(user, key)) or {}).get(key, default)


def resolve(user: dict, old_path: str) -> str:
    """An "Info.<key>" path rewritten to where this user keeps the key now; other paths as is."""
    group, _, key = old_path.partition(".")
    if group == "Info" and key in MOVED:
        return f"{group_of(user, key)}.{key}"
    return old_path


def info_view(user: dict) -> dict:
    """The user's Info as an AUTO-MAS from before v5.7.0-beta.3 had it: Info plus the moved
    items taken from their new groups."""
    out = dict(user.get("Info") or {})
    for key, group in MOVED.items():
        src = user.get(group)
        if isinstance(src, dict) and key in src:
            out[key] = src[key]
    return out


def runs(info: dict) -> bool:
    """Whether AUTO-MAS runs this user at all: app/task/manager_base.py is_user_selected
    (AUTO-MAS-Project/AUTO-MAS 9e605ff7, 2026-10-13) takes a user only when Info.Status is
    on and Info.RemainedDay is not 0 (defaults True and -1, app/models/config.py)."""
    return bool(info.get("Status", True)) and info.get("RemainedDay", -1) != 0


def pick(users) -> "tuple[str, dict] | None":
    """(user id, user) of a script's UserData (the file) or /api/scripts/user/get reply
    (the backend): the first user AUTO-MAS runs, else the first user; None when there is
    none. One choice for every reader and writer (audit 11-08 D-11: the phone's changes
    went to the first user while its snapshot and the plan showed the last). The file's
    "instances" list and any other non-user entry are skipped."""
    found = [(str(k), v) for k, v in (users or {}).items() if k != "instances" and isinstance(v, dict)]
    return next((x for x in found if runs(info_view(x[1]))), found[0] if found else None)


# The JSON file a reader asks for -> the YAML file v5.8 keeps the same settings in.
YAML_OF = {"ScriptConfig.json": "scripts.yaml", "QueueConfig.json": "queues.yaml",
           "PlanConfig.json": "plans.yaml"}
_ISO_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
_TIME_FORM = {"Time": "%H:%M", "LastTimedStart": "%Y-%m-%d %H:%M", "LastStartupTime": "%Y-%m-%d",
              "LastProxyDate": "%Y-%m-%d"}


def source(path: Path) -> Path:
    """The file that holds what `path` names: the JSON while it exists, else its YAML."""
    path = Path(path)
    alt = YAML_OF.get(path.name)
    if alt and not path.exists() and (path.parent / alt).exists():
        return path.parent / alt
    return path


def parse_text(src: Path, text: str) -> dict:
    """Parse `text` from `src` (.json or .yaml) into the v5.7 JSON shape."""
    if Path(src).suffix == ".json":
        return json.loads(text)
    doc = loads(text)
    if not isinstance(doc, dict):
        raise ValueError(f"{Path(src).name}: not a mapping")
    return legacy(doc)


def read(path: Path) -> dict:
    """The settings `path` names, in the v5.7 JSON shape.

    Raises what reading the JSON would (OSError, ValueError) when neither file can be read,
    so a reader's error handling stays as it was."""
    src = source(path)
    return parse_text(src, Path(src).read_text(encoding="utf-8"))


def legacy(node: dict) -> dict:
    """v5.8's {"order", "data"} collection as v5.7's {"instances", <uid>: ...}."""
    out: dict = {"instances": list(node.get("order") or [])}
    for uid, item in (node.get("data") or {}).items():
        out[str(uid)] = _item(item)
    return out


def _item(item):
    if not isinstance(item, dict):
        return item
    plain, subs = {}, {}
    for k, v in item.items():
        if _collection(v):
            subs[k] = legacy(v)
        else:
            plain[k] = _local(v, k)
    if subs:
        plain["SubConfigsInfo"] = subs
    return plain


def _local(v, key: str = ""):
    """`v` with v5.8's UTC ISO times put back into v5.7's local forms (_TIME_FORM)."""
    if isinstance(v, dict):
        return {k: _local(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_local(x, key) for x in v]
    if isinstance(v, str) and _ISO_Z.fullmatch(v):
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415 - config imports a lot
        at = datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(SERVER_TZ)
        return at.strftime(_TIME_FORM.get(key, "%Y-%m-%d %H:%M:%S"))
    return v


def _collection(v) -> bool:
    return isinstance(v, dict) and set(v) == {"order", "data"}


@dataclass(frozen=True)
class Item:
    kind: str       # "MAA" | "MaaEnd" | "OK-WW" | "queue" | "plan"
    level: str      # "script" | "user" | "queue" | "timeset" | "queueitem" | "plan"
    group: str
    key: str
    use: str        # feature id: texts.MAS_SETTING_WHAT / MAS_SETTING_BREAKS
    source: str     # where the relay reads (or writes) it
    since: str = "" # the AUTO-MAS version that brought it in; judged only from that version on

    @property
    def owner(self) -> str:
        """The AUTO-MAS model class that defines it (app/models/config.py)."""
        return OWNER[(self.kind, self.level)]

    @property
    def path(self) -> str:
        return f"{self.group}.{self.key}"


OWNER = {
    ("MAA", "script"): "MaaConfig", ("MAA", "user"): "MaaUserConfig",
    ("MaaEnd", "script"): "MaaEndConfig", ("MaaEnd", "user"): "MaaEndUserConfig",
    ("OK-WW", "script"): "OkwwConfig", ("OK-WW", "user"): "OkwwUserConfig",
    ("queue", "queue"): "QueueConfig", ("queue", "timeset"): "TimeSet",
    ("queue", "queueitem"): "QueueItem", ("plan", "plan"): "MaaPlanConfig",
}
# A ScriptConfig.json instance's "type" -> script kind (the machine's file has it; older test
# layouts do not, then the install path decides, as plan._script_kind does).
TYPE_KIND = {"MaaConfig": "MAA", "MaaEndConfig": "MaaEnd", "OkwwConfig": "OK-WW"}


def _items(kind, level, group, keys, use, source, since=""):
    return [Item(kind, level, group, k, use, source, since) for k in keys]


CONTRACT: tuple[Item, ...] = tuple([
    # ---- script level (ScriptConfig.json <script uid>.<group>)
    *_items("MAA", "script", "Info", ("Path",), "script_path",
            "plan.py:_scripts/_script_kind, stagegate.py:_maa_script, annihilation.py:_maa_users"),
    *_items("MaaEnd", "script", "Info", ("Path",), "script_path",
            "plan.py:_scripts/_script_kind, plan.py:script_dir, sanity_plan.py"),
    *_items("OK-WW", "script", "Info", ("RootPath",), "script_path",
            "plan.py:_scripts/_script_kind, plan.py:script_dir"),
    *_items("MAA", "script", "Info", ("Name",), "script_name",
            "snapshot.py:maa_from_files, commands.py:_find_user"),
    *_items("MaaEnd", "script", "Info", ("Name",), "script_name", "commands.py:_find_user"),
    *_items("OK-WW", "script", "Info", ("Name",), "script_name",
            "plan.py:_okww_quick_overrides, commands.py:_find_user"),
    *_items("MAA", "script", "Run", ("IfCheckGameUpdate", "IfAutoInstallGameApk"), "client_update",
            "selfcheck.py:_handed_updates_gaps"),
    *_items("OK-WW", "script", "Game", ("Enabled", "Path", "IfAutoUpdate"), "client_update",
            "selfcheck.py:_handed_updates_gaps"),
    *_items("MaaEnd", "script", "Game", ("WaitTime",), "maaend_wait",
            "commands.py:_set_wait_time (write)"),
    *_items("MaaEnd", "script", "Game", ("Path",), "maaend_launch",
            "efstart_setup.py:install/launcher_for (write)"),
    *_items("MaaEnd", "script", "Game", ("LaunchMode", "LauncherPath"), "maaend_launch",
            "efstart_setup.py:install/launcher_for (write LaunchMode)", since="v5.7.0-beta.4"),
    *_items("MaaEnd", "script", "Game", ("ControllerType",), "maaend_launch",
            "efstart_setup.py:install (maaend_launch.check)"),
    *_items("MaaEnd", "script", "Game", ("SetResolution", "CloseOnFinish", "RestoreDisplayType",
                                         "RestoreResolution"), "maaend_window",
            "efstart_setup.py:install/restore (write)"),
    *_items("MaaEnd", "script", "Update", ("TakeoverEnabled", "Channel"), "maaend_update",
            "mastercfg.py:check_maaend_preupdate, selfcheck.py:_handed_updates_gaps", since="v5.8.0"),
    # ---- MAA user (SubConfigsInfo.UserData.<uid>); Stage.* and Task.Annihilation via masuser
    *_items("MAA", "user", "Stage", ("StageMode", "Stage", "Stage_1", "Stage_2", "Stage_3", "SeriesNumb"),
            "stage", "plan.py:_scripts, stagegate.py:run_verdict, snapshot.py:maa_fields, "
            "commands.py:_set_stage (write)"),
    *_items("MAA", "user", "Stage", ("MedicineNumb",), "medicine",
            "plan.py:_stage_bits, snapshot.py:maa_fields, commands.py:_set_medicine (write)"),
    # Whether AUTO-MAS runs the user at all (app/task/manager_base.py is_user_selected): the
    # stage gate leaves out a user it does not run, and the phone and the plan take the
    # first one it does run (masuser.pick).
    *_items("MAA", "user", "Info", ("Status", "RemainedDay"), "stage",
            "masuser.py:runs/pick, stagegate.py:run_verdict, commands.py:_find_user, snapshot.py"),
    *_items("MAA", "user", "Task", ("IfFight",), "fight",
            "plan.py:_scripts, stagegate.py:run_verdict, snapshot.py:maa_fields"),
    *_items("MAA", "user", "Task", ("Annihilation",), "annihilation",
            "plan.py:_scripts, annihilation.py:WeeklyGate._status, snapshot.py:maa_fields"),
    *_items("MAA", "user", "Data", ("AnnihilationCompletedWeek",), "annihilation",
            "annihilation.py:WeeklyGate._status"),
    *_items("MAA", "user", "Task", ("IfActivityFirst", "ActivityStageIndex"), "activity",
            "snapshot.py:maa_fields, phone.py:state_payload"),
    # ---- MaaEnd user: the items the phone shows and changes (mas_labels.SHOWN)
    *_items("MaaEnd", "user", "Task", ("IfSanity", "IfAutoUseSpMedication", "SanityTaskType",
                                       "AutoEssenceSpecifiedLocation"), "maaend_phone",
            "snapshot.py:_mas, mas_labels.py:SHOWN, commands.py:_set_config (write)"),
    # ---- OK-WW user: the quick config the plan shows instead of OK-WW's own file
    *_items("OK-WW", "user", "Info", ("IfQuickConfig",), "okww_quick", "plan.py:_okww_quick_overrides"),
    *_items("OK-WW", "user", "Task", ("WhichToFarm", "WhichTacetSuppressionToFarm",
                                      "WhichForgeryChallengeToFarm", "MaterialSelection",
                                      "FarmNightmareNestForDailyEcho", "AdditionalTasks"), "okww_quick",
            "plan.py:_okww_quick_overrides, mas_labels.py:SHOWN"),
    # ---- QueueConfig.json
    *_items("queue", "queue", "Info", ("Name", "TimeEnabled", "CycleEnabled"), "queue_timer",
            "plan.py:_queues/queue_rows, queues.py:apply (write TimeEnabled), commands.py:skip_script_in_queue"),
    *_items("queue", "queue", "Info", ("AfterAccomplish",), "queue_after", "plan.py:_queues/next_plan"),
    *_items("queue", "queue", "Info", ("StartUpMode",), "queue_startup", "plan.py:_startup_runs"),
    *_items("queue", "timeset", "Info", ("Enabled", "Time", "Days"), "queue_timer",
            "plan.py:_queues/_queue_times"),
    *_items("queue", "queueitem", "Info", ("ScriptId",), "queue_items",
            "plan.py:_queues/queue_rows, commands.py:skip_script_in_queue, snapshot.py"),
    *_items("queue", "queueitem", "Schedule", ("Days",), "queue_items",
            "plan.py:_queues, commands.py:skip_script_in_queue (write)"),
    # ---- PlanConfig.json (the MAA stage plan a user's StageMode may point at)
    *_items("plan", "plan", "Info", ("Mode",), "plan_table", "plan.py:_stage_bits, stagegate.py"),
    *_items("plan", "plan", "ALL", ("Stage", "Stage_1", "Stage_2", "Stage_3", "MedicineNumb"),
            "plan_table", "plan.py:_stage_bits, stagegate.py"),
])


@dataclass
class Result:
    missing: list          # [Item] not found where the relay reads it
    unreadable: list       # [file name] that could not be read as JSON
    judged: int            # how many items had at least one node to be judged on


def _load(path: Path):
    """The file's settings - the JSON, or AUTO-MAS v5.8's YAML in the same shape (masconfig,
    ledger #113); None when it is not there; raises ValueError / OSError otherwise."""
    try:
        return read(path)
    except FileNotFoundError:
        return None


def _nodes(data) -> list[tuple[dict, dict]]:
    """[(instance, node)] of a MultipleConfig file / SubConfigsInfo block, in instance order."""
    if not isinstance(data, dict):
        return []
    out = []
    for inst in data.get("instances") or []:
        node = data.get(inst.get("uid")) if isinstance(inst, dict) else None
        if isinstance(node, dict):
            out.append((inst, node))
    return out


def _entries(block) -> list[dict]:
    """The entries of a TimeSet / QueueItem block: every dict value but the instances list."""
    if not isinstance(block, dict):
        return []
    return [v for k, v in block.items() if k != "instances" and isinstance(v, dict)]


def _script_kind(inst: dict, node: dict) -> str:
    from ark_relay.core import plan  # noqa: PLC0415 - plan imports config; keep this module light
    kind = TYPE_KIND.get(str(inst.get("type") or ""))
    if kind:
        return kind
    info = node.get("Info") or {}
    return plan._script_kind(info.get("Path") or info.get("RootPath") or "")


def _has(node: dict, group: str, key: str) -> bool:
    g = node.get(group)
    return isinstance(g, dict) and key in g


def _user_has(user: dict, item: Item) -> bool:
    if MOVED.get(item.key) == item.group:
        return _has(user, group_of(user, item.key), item.key)
    return _has(user, item.group, item.key)


def nodes_by_level(cfg_dir: Path, unreadable: list) -> dict[tuple[str, str], list[dict]]:
    """{(kind, level): [node]} from the three files; a file that cannot be read goes to
    `unreadable` and gives no nodes."""
    def load(name):
        try:
            return _load(cfg_dir / name)
        except (OSError, ValueError):
            unreadable.append(name)
            return None
    out: dict = {k: [] for k in OWNER}
    for inst, node in _nodes(load("ScriptConfig.json")):
        kind = _script_kind(inst, node)
        if not kind:
            continue
        out[(kind, "script")].append(node)
        users = (node.get("SubConfigsInfo") or {}).get("UserData")
        out[(kind, "user")] += [u for _, u in _nodes(users)] or _entries(users)
    for _, node in _nodes(load("QueueConfig.json")):
        out[("queue", "queue")].append(node)
        sub = node.get("SubConfigsInfo") or {}
        out[("queue", "timeset")] += _entries(sub.get("TimeSet"))
        out[("queue", "queueitem")] += _entries(sub.get("QueueItem"))
    plans = load("PlanConfig.json")
    for inst, node in _nodes(plans) or [({}, v) for v in _entries(plans)]:
        # Only the MAA stage plans: the file may hold MaaEnd / BAAH / MSS plans as well.
        if inst.get("type", "MaaPlanConfig") == "MaaPlanConfig" and isinstance(node.get("ALL"), dict):
            out[("plan", "plan")].append(node)
    return out


_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")


def version_key(version: str) -> "tuple[int, ...] | None":
    """v5.7.0-beta.4 -> (5, 7, 0, 0, 4); v5.7.0 -> (5, 7, 0, 1, 0), after its betas; None
    when it does not read as an AUTO-MAS version."""
    m = _VERSION.match(str(version or "").strip())
    if not m:
        return None
    major, minor, patch, beta = m.groups()
    return (int(major), int(minor), int(patch), 0 if beta else 1, int(beta or 0))


def check(automas_dir, version: str = "") -> Result:
    """Every CONTRACT item a node of its kind does not have, read from <automas_dir>/config.

    `version` is the installed AUTO-MAS's own (the backend's /api/core/health; its
    res/version.json is not rewritten by newer builds). An item with `since` is judged only
    when that version is known and not older: an older AUTO-MAS never had it, and the
    recorded days of the day simulator run v5.6.2 to v5.7.0-beta.3."""
    cfg_dir = Path(automas_dir) / "config" if automas_dir else None
    if cfg_dir is None or not cfg_dir.is_dir():
        return Result([], ["config"], 0)
    unreadable: list = []
    by_level = nodes_by_level(cfg_dir, unreadable)
    have = version_key(version)
    missing, judged = [], 0
    for item in CONTRACT:
        nodes = by_level.get((item.kind, item.level)) or []
        if not nodes:
            continue
        if item.since and (have is None or have < version_key(item.since)):
            continue
        judged += 1
        if item.level == "user":
            ok = all(_user_has(n, item) for n in nodes)
        else:
            ok = all(_has(n, item.group, item.key) for n in nodes)
        if not ok:
            missing.append(item)
    return Result(missing, unreadable, judged)


MAAEND_PREUPDATE_WANT_CHANNEL = "beta"


def _find_maaend_script(automas_dir=None, scripts=None) -> "tuple[dict | None, bool]":
    """(MaaEnd script node, on_v58_yaml) from live `/api/scripts/get` dict or disk config."""
    has_yaml = bool(automas_dir and (Path(automas_dir) / "config" / "scripts.yaml").is_file())
    if isinstance(scripts, dict):
        for sc in scripts.values():
            if not isinstance(sc, dict):
                continue
            info = sc.get("Info") or {}
            name = str(info.get("Name") or "")
            if name.lower() == "maaend":
                return sc, has_yaml
    if automas_dir:
        cfg_dir = Path(automas_dir) / "config"
        try:
            data = _load(cfg_dir / "ScriptConfig.json")
        except (OSError, ValueError):
            data = None
        for inst, node in _nodes(data):
            if _script_kind(inst, node) == "MaaEnd":
                return node, has_yaml
    return None, has_yaml


def check_maaend_preupdate(automas_dir=None, scripts=None, version: str = "") -> list[str]:
    """Detect MaaEnd pre-update chain break on AUTO-MAS v5.8+ (`Update.TakeoverEnabled` / `Channel`).

    On v5.8+, AUTO-MAS took over MaaEnd updating (relay preupdate_maaend removed 21fa826f),
    defaulting Update.TakeoverEnabled=false and Channel=stable; when either stays at default,
    MaaEnd runs stale and only updates after the shift. Legacy v5.7 configs without an Update
    group, scripts.yaml, or version >= v5.8.0 return [].
    """
    node, has_yaml = _find_maaend_script(automas_dir, scripts)
    vk = version_key(version)
    v58 = bool(vk is not None and vk >= version_key("v5.8.0"))
    has_update = isinstance(node, dict) and isinstance(node.get("Update"), dict)
    if not (has_update or has_yaml or v58):
        return []
    if node is None:
        return ["终末地开跑前由调度程序接管更新：调度程序里没有 MaaEnd 这个脚本"]
    upd = node.get("Update")
    if not isinstance(upd, dict):
        return ["终末地开跑前由调度程序接管更新：读不到更新设置"]
    gaps: list[str] = []
    takeover = upd.get("TakeoverEnabled")
    if takeover is not True:
        now = "读不到这一项" if takeover is None else ("关着" if takeover is False else "不是开着")
        gaps.append(f"终末地开跑前由调度程序接管更新：{now}")
    chan = upd.get("Channel")
    chan_norm = str(chan or "").strip().lower()
    if chan_norm != MAAEND_PREUPDATE_WANT_CHANNEL:
        if not chan_norm:
            now = "读不到这一项"
        elif chan_norm == "stable":
            now = "现在是稳定版而不是测试版"
        else:
            now = "现在不是测试版"
        gaps.append(f"终末地更新通道：{now}")
    return gaps


log = logging.getLogger("ark.mastercfg")

# read_maa runs on every phone publish and a WARNING is a group message
# (errwatch): each condition is said once and forgotten once it clears.
_maa_said: dict[str, str] = {}


def _maa_warn_once(site: str, why: str, msg: str, *args, exc_info: bool = False) -> None:
    if _maa_said.get(site) != why:
        log.warning(msg, *args, exc_info=exc_info)
        _maa_said[site] = why

MAA_DRONES: tuple[tuple[str, str], ...] = (
    ("_NotUse", "不使用"),
    ("Money", "贸易站 · 龙门币"),
    ("SyntheticJade", "贸易站 · 合成玉"),
    ("CombatRecord", "制造站 · 作战记录"),
    ("PureGold", "制造站 · 赤金"),
    ("OriginStone", "制造站 · 源石碎片"),
    ("Chip", "制造站 · 芯片"),
)


MAA_DRONES_PATH = "Infrast/UsesOfDrones"


MAA_AWARD: tuple[tuple[str, str], ...] = (
    ("Award", "领取每日/每周任务奖励"),
    ("Mail", "领取所有邮件奖励"),
    ("FreeGacha", "每日免费单抽"),
    ("Orundum", "领取幸运墙的每日合成玉奖励"),
    ("Mining", "领取限时开采许可的每日合成玉奖励"),
    ("SpecialAccess", "领取周年赠送月卡奖励"),
    ("SignInEvent", "限时签到活动领取"),
)

# MAA's one-of-a-kind tasks and the names AUTO-MAS gives them (MAA_TASKS /
# MAA_TASKS_ZH in app/utils/constants.py, pinned by test_gl's guinew case).
MAA_SINGLETON_TASKS: dict[str, str] = {
    "StartUp": "开始唤醒",
    "Infrast": "基建换班",
    "Recruit": "自动公招",
    "Mall": "信用收支",
    "Award": "领取奖励",
}


MAA_AWARD_PATHS = {f"Award/{k}": zh for k, zh in MAA_AWARD}


def maa_master(automas_dir) -> Path | None:
    root = Path(automas_dir) / "data" if automas_dir else None
    return next((f for f in (root.glob("*/Default/ConfigFile/gui.new.json") if root else [])), None)


def _maa_tasks(doc: dict, match, canonical_name: str = "") -> list[dict]:
    """Every task in the current configuration's TaskQueue that `match` accepts,
    the one named `canonical_name` first: the entry AUTO-MAS hands MAA
    (_find_task_source returns an exact (TaskType, Name) match before anything else).
    """
    cfgs = doc.get("Configurations") or {}
    c = cfgs.get(doc.get("Current") or "Default") or cfgs.get("Default") or {}
    found = [t for t in c.get("TaskQueue") or [] if isinstance(t, dict) and match(t)]
    if canonical_name:
        found.sort(key=lambda t: t.get("Name") != canonical_name)   # stable: queue order otherwise
    return found


def _maa_task(doc: dict, match, canonical_name: str = "") -> dict | None:
    """The task AUTO-MAS would hand MAA: see _maa_tasks."""
    return next(iter(_maa_tasks(doc, match, canonical_name)), None)


def _is_type(t: dict, task_type: str) -> bool:
    return t.get("TaskType") == task_type or t.get("Type") == task_type


def _infrast_match(t: dict) -> bool:
    return _is_type(t, "Infrast") or "UsesOfDrones" in t


def _award_match(t: dict) -> bool:
    return _is_type(t, "Award") or ("Mail" in t and "FreeGacha" in t)


def _maa_infrast(doc: dict) -> dict | None:
    return _maa_task(doc, _infrast_match, MAA_SINGLETON_TASKS["Infrast"])


def _maa_award(doc: dict) -> dict | None:
    return _maa_task(doc, _award_match, MAA_SINGLETON_TASKS["Award"])


def _maa_infrasts(doc: dict) -> list[dict]:
    return _maa_tasks(doc, _infrast_match, MAA_SINGLETON_TASKS["Infrast"])


def _maa_awards(doc: dict) -> list[dict]:
    return _maa_tasks(doc, _award_match, MAA_SINGLETON_TASKS["Award"])


def read_maa(automas_dir) -> dict:
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maa_master(automas_dir)
    if not f or not f.is_file():
        # Said, so the phone page's missing section has a cause in the log.
        _maa_warn_once("master", f"missing: {f}", "母本配置文件不在：%s（手机页那一段会标成读不到）", f or "没找到路径")
        return out
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _maa_warn_once("master", f"unreadable: {type(exc).__name__}: {exc}", "母本 gui.new.json 读不出来",
                   exc_info=True)
        return out
    _maa_said.pop("master", None)
    task = _maa_infrast(doc)
    if task is not None:
        out["values"][MAA_DRONES_PATH] = str(task.get("UsesOfDrones") or "")
        out["options"][MAA_DRONES_PATH] = [[label, key] for key, label in MAA_DRONES]
        out["labels"][MAA_DRONES_PATH] = "基建无人机用在哪"
    award = _maa_award(doc)
    if award is not None:
        for key, zh in MAA_AWARD:
            out["values"][f"Award/{key}"] = bool(award.get(key, False))
            out["labels"][f"Award/{key}"] = zh
    return out


def write_maa(automas_dir, maa_dir, path: str, value) -> tuple[bool, str]:
    """Change what the infrastructure drones are used on. Both the master copy
    and the copy in the MAA directory are written; only the seven values MAA
    itself declares are accepted.
    """
    if str(path) in MAA_AWARD_PATHS:
        return _write_maa_award(automas_dir, maa_dir, str(path), value)
    if str(path) != MAA_DRONES_PATH:
        return False, f"MAA 只开放 {MAA_DRONES_PATH} 和 {sorted(MAA_AWARD_PATHS)} 这几项，已拒绝 {path!r}"
    keys = {k for k, _ in MAA_DRONES}
    if str(value) not in keys:
        return False, f"无人机用途不认识取值 {value!r}，它只接受 {sorted(keys)}"
    err, before, written = _write_maa_copies(
        automas_dir, maa_dir, _maa_infrasts, "UsesOfDrones", str(value),
        "里找不到带 UsesOfDrones 的基建任务，已拒绝", lambda t: t.get("UsesOfDrones"))
    if err:
        return False, err
    zh = dict(MAA_DRONES)
    if before == str(value):
        return True, f"基建无人机本来就用在{zh[str(value)]}"
    return True, f"基建无人机用在哪：{zh.get(str(before), before)} → {zh[str(value)]}（写了 {len(written)} 份）"


def _write_maa_award(automas_dir, maa_dir, path: str, value) -> tuple[bool, str]:
    """Flip one switch of the 领取奖励 task in both copies of gui.new.json."""
    if not isinstance(value, bool):
        return False, f"{path} 只接受开/关，已拒绝 {value!r}"
    key = path.split("/", 1)[1]
    zh = MAA_AWARD_PATHS[path]
    err, before, written = _write_maa_copies(
        automas_dir, maa_dir, _maa_awards, key, value,
        "里找不到领取奖励任务，已拒绝", lambda t: bool(t.get(key, False)))
    if err:
        return False, err
    state = "开" if value else "关"
    if before is value:
        return True, f"「{zh}」本来就是{state}的"
    return True, f"「{zh}」：{'开' if before else '关'} → {state}（写了 {len(written)} 份）"


def _write_maa_copies(automas_dir, maa_dir, find_all, key: str, value, no_task: str,
                      read_before) -> "tuple[str, object, list[str]]":
    """Set t[key] = value for every t in find_all(doc), in the master gui.new.json
    and in MAA's own copy. find_all puts the entry AUTO-MAS uses first; every
    copy of the task is written, so whichever one is used carries the value.

    The master copy is the one that counts: AUTO-MAS copies
    data/<script>/<user>/ConfigFile over MAA's config dir before each run
    (task/MAA/AutoProxy.py _copy_source_config), so without it nothing is
    written. Both files are parsed and checked before either is written, so a
    refusal leaves both untouched. Each file is written atomically and read
    back. `read_before(task)` gives the old value, from the master's first entry.
    Returns (error, old value, names of the files written); error is "" on
    success and, when it is not, names the files already written.
    """
    master = maa_master(automas_dir)
    if not master or not master.is_file():
        return ("找不到 AUTO-MAS 里 MAA 的母本配置，没改（只改 MAA 自己那份，"
                "下次开跑前会被母本盖掉）"), None, []
    targets = [master]
    if maa_dir and (own := Path(maa_dir) / "config" / "gui.new.json").is_file():
        targets.append(own)
    docs = []
    for f in targets:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return f"{f} 读不出来（{type(exc).__name__}），两份都没改", None, []
        if not find_all(doc):
            return f"{f.name} {no_task}（两份都没改）", None, []
        docs.append(doc)
    before = read_before(find_all(docs[0])[0])
    written: list[str] = []
    for f, doc in zip(targets, docs, strict=True):
        for t in find_all(doc):
            t[key] = value
        try:
            atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=4))
            back = find_all(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            back, problem = [], f"写的时候出错（{type(exc).__name__}）"
        else:
            problem = "写进去之后读出来和写的不一样"
        if not back or any(t.get(key) != value for t in back):
            # Only the master can come before: it is already changed, and
            # AUTO-MAS copies it over MAA's own file before the next run.
            done = "；母本已经改好，下次开跑会照它覆盖 MAA 自己那份" if written else ""
            return f"{f} {problem}{done}", before, written
        written.append(f)
    return "", before, [w.name for w in written]


def _placeholder(v) -> bool:
    """MAA's unfilled default, e.g. "{{ HighPriorityDefault }}" (see AutoProxy.py's
    comment where it fills a missing source from the preset)."""
    return isinstance(v, str) and "{{" in v


def dedup_maa_task_queue(doc: dict) -> list[str]:
    """Fold each one-of-a-kind task's copies into one entry, in every configuration.

    The first entry of the type is kept in its place; a later copy only fills a
    key the first lacks or holds as a placeholder ("Name" and "IsEnable" are not
    taken, placeholders never are). The Award switches are on when any copy has
    them on. The kept entry is named as AUTO-MAS names it, so its exact match
    finds it and its write-back no longer appends a copy, and "$type" stays the
    first key (MAA's System.Text.Json reads it from there; AutoProxy.py
    _with_type_first). Returns what was folded, e.g. ["领取奖励（2 条合成 1 条）"].
    """
    folded: list[str] = []
    award_keys = [k for k, _ in MAA_AWARD]
    for scheme, c in (doc.get("Configurations") or {}).items():
        queue = c.get("TaskQueue") if isinstance(c, dict) else None
        if not isinstance(queue, list):
            continue
        for task_type, zh in MAA_SINGLETON_TASKS.items():
            idxs = [i for i, t in enumerate(queue) if isinstance(t, dict) and _is_type(t, task_type)]
            if len(idxs) < 2:
                continue
            merged = dict(queue[idxs[0]])
            for i in idxs[1:]:
                for k, v in queue[i].items():
                    if k in ("Name", "IsEnable") or _placeholder(v):
                        continue
                    if k not in merged or _placeholder(merged[k]):
                        merged[k] = v
            if task_type == "Award":
                for k in award_keys:
                    merged[k] = any(bool(queue[i].get(k, False)) for i in idxs)
            merged["Name"] = zh
            merged["TaskType"] = task_type
            queue[idxs[0]] = {"$type": merged.get("$type") or f"{task_type}Task", **merged}
            for i in reversed(idxs[1:]):
                del queue[i]
            where = "" if scheme == "Default" else f"「{scheme}」方案的"
            folded.append(f"{where}{zh}（{len(idxs)} 条合成 1 条）")
    return folded


def heal_maa_master(automas_dir, maa_dir=None) -> tuple[list[str], str]:
    """Run dedup_maa_task_queue on the master gui.new.json and on MAA's own copy.

    Returns (what was folded, note); ([], "") when there was nothing to fold or
    no master (read_maa already says that one). The master is backed up first,
    one level above ConfigFile: AUTO-MAS copies that whole folder into MAA's
    config dir before every run. Each file is read back after writing.
    """
    master = maa_master(automas_dir)
    if not master or not master.is_file():
        return [], ""
    targets = [master]
    if maa_dir and (own := Path(maa_dir) / "config" / "gui.new.json").is_file():
        targets.append(own)
    folded: list[str] = []
    notes: list[str] = []
    for f in targets:
        try:
            raw = f.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError) as exc:
            notes.append(f"{f} 读不出来（{type(exc).__name__}），没去重")
            continue
        merged = dedup_maa_task_queue(doc)
        if not merged:
            continue
        bak = None
        if f == master:
            bak = f.parent.parent / f"{f.name}.bak-dedup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            bak.write_bytes(raw)
        try:
            atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=4))
            left = dedup_maa_task_queue(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            notes.append(f"{f} 写的时候出错（{type(exc).__name__}）" + (f"，{bak.name} 是原样" if bak else ""))
            continue
        if left:
            notes.append(f"{f} 写进去之后再读还有重复：{'、'.join(left)}" + (f"，{bak.name} 是原样" if bak else ""))
            continue
        which = "母本" if f == master else "MAA 自己那份"
        folded += [m for m in merged if m not in folded]
        notes.append(f"MAA {which}里重复的任务合并了：{'、'.join(merged)}" + (f"（原文件备份为 {bak.name}）" if bak else ""))
    return folded, "；".join(notes)


# read_okww runs on every phone-state publish and a WARNING is a group message:
# a config file that exists but cannot be read is said once per condition (file
# -> the error last said), forgotten once it reads again.
_last_error: dict[str, str] = {}


OKWW_SHOWN: dict[str, tuple[str, ...]] = {
    "DailyTask.json": (
        "Which to Farm",
        "Material Selection",
        "Which Forgery Challenge to Farm",
        "Which Tacet Suppression to Farm",
    ),
}


OKWW_READONLY: dict[str, tuple[str, ...]] = {
    "NightmareNestTask.json": ("Only Farm These Nests",),
}
# The nests that order names, in list order; the master's value is these joined by ",".
ONLY_NESTS: tuple[str, ...] = ("梦枢天罗", "落渊南丘")


def nest_names(raw) -> list[str]:
    """The setting split the way the overrides split it: on ASCII or full-width commas."""
    return [n.strip() for n in re.split(r"[,，]", str(raw or "")) if n.strip()]


def okww_file(automas_dir, name: str) -> Path | None:
    d = master_config_dir(automas_dir, "DailyTask.json")
    return (d / name) if d else None


# Which sub-setting appears below depends on which entry of "what to farm" is
# selected. Taken from OK-WW's own sub_configs.
OKWW_SUBS = {
    "Tacet Suppression": ["DailyTask.json/Which Tacet Suppression to Farm"],
    "Forgery Challenge": ["DailyTask.json/Which Forgery Challenge to Farm"],
    "Simulation Challenge": ["DailyTask.json/Material Selection"],
}


_LIST = {
    "Which to Farm": r"support_tasks\s*=\s*\[([^\]]*)\]",
    "Material Selection": r"material_option_list\s*=\s*\[([^\]]*)\]",
}


def _okww_cases(okww_dir) -> dict[str, list[str]]:
    """The dropdown candidates are read from OK-WW's **own source**, never invented here."""
    out: dict[str, list[str]] = {}
    if not okww_dir:
        return out
    f = (Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "src"
         / "task" / "DailyTask.py")
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for key, pat in _LIST.items():
        m = re.search(pat, text, re.S)
        if m:
            vals = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))
            if vals:
                out[key] = vals
    return out


# The serial keys and the task file whose `self.structure = [...]` sums to the list
# length; upstream raises IndexError past it (v3.7.4: TacetTask.py:18 [4, 5, 5, 7]
# and :69 / :111-112, index = serial - 1 must be < 21; ForgeryTask.py:23
# [5, 5, 5, 5] and :39 / :63-64, serial must be <= 20). The fallback is those sums,
# used only when OK-WW's source cannot be read.
_SERIAL = {
    "Which Tacet Suppression to Farm": ("TacetTask.py", 21),
    "Which Forgery Challenge to Farm": ("ForgeryTask.py", 20),
}
_STRUCTURE = re.compile(r"self\.structure\s*=\s*\[([\d,\s]+)\]")


def _okww_serial_max(okww_dir, key: str) -> "int | None":
    """How many entries OK-WW's list for `key` has, read from its own source; the
    v3.7.4 fallback when that cannot be read; None for a key that is not a serial."""
    if key not in _SERIAL:
        return None
    name, fallback = _SERIAL[key]
    if okww_dir:
        f = (Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "src" / "task" / name)
        try:
            m = _STRUCTURE.search(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            m = None
        if m:
            return sum(int(x) for x in re.findall(r"\d+", m.group(1)))
    return fallback


def _okww_doc(f: Path) -> "dict | None":
    """One existing OK-WW config file, or None (said once) when it cannot be read:
    its rows would otherwise just vanish from the phone page."""
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        why = f"{type(exc).__name__}: {exc}"
        if _last_error.get(str(f)) != why:
            log.warning("鸣潮母本 %s 读不到（%s），手机页上它那几项这次不显示", f.name, why)
            _last_error[str(f)] = why
        return None
    _last_error.pop(str(f), None)
    return doc


def _okww_index_display(key: str, value) -> "str | None":
    """Human-readable label for WuWa F2 serial keys; None for non-serial keys."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    from ark_relay.core.wuwa_tables import wuwa_forgery, wuwa_tacet  # noqa: PLC0415
    if key == "Which Tacet Suppression to Farm":
        return wuwa_tacet.sets_label(value)
    if key == "Which Forgery Challenge to Farm":
        return wuwa_forgery.label(value)
    return None


def _okww_index_options(key: str) -> "list[list] | None":
    from ark_relay.core.wuwa_tables import wuwa_forgery, wuwa_tacet  # noqa: PLC0415
    if key == "Which Tacet Suppression to Farm":
        return [[lbl, idx] for idx, lbl in wuwa_tacet.choices()]
    if key == "Which Forgery Challenge to Farm":
        return [[lbl, idx] for idx, lbl in wuwa_forgery.choices()]
    return None


def read_okww(automas_dir, okww_dir) -> dict:
    """Values, candidates and Chinese names. Every Chinese name comes from the
    ok.po that ships with OK-WW (`Forgery Challenge` is officially 「凝素领域」,
    `Tacet Suppression` 「无音区」). Tacet Suppression and Forgery Challenge indices
    carry echo-set / weapon-material options and display names from wuwa_tables.
    """
    out: dict = {"values": {}, "options": {}, "labels": {}, "display": {}, "readonly": {},
                 "subs": OKWW_SUBS}
    try:
        from ark_relay.core import plan  # noqa: PLC0415
        zh = plan._okww_zh(Path(okww_dir) if okww_dir else None)
    except Exception:  # noqa: BLE001
        zh = {}
    cases = _okww_cases(okww_dir)
    for name, wanted in OKWW_SHOWN.items():
        f = okww_file(automas_dir, name)
        if not f or not f.is_file():
            continue
        if (doc := _okww_doc(f)) is None:
            continue
        for key in wanted:
            if key not in doc:
                continue
            path = f"{name}/{key}"
            out["values"][path] = doc[key]
            if zh.get(key):
                out["labels"][path] = zh[key]
            if key in cases:
                out["options"][path] = [[zh.get(v, v), v] for v in cases[key]]
            elif (idx_opts := _okww_index_options(key)) is not None:
                out["options"][path] = idx_opts
            if (disp := _okww_index_display(key, doc[key])) is not None:
                out["display"][path] = disp
    for name, wanted in OKWW_READONLY.items():
        f = okww_file(automas_dir, name)
        if not f or not f.is_file():
            continue
        if (doc := _okww_doc(f)) is None:
            continue
        for key in wanted:
            if key in doc:
                out["readonly"][f"{name}/{key}"] = doc[key]
                if zh.get(key):
                    out["labels"][f"{name}/{key}"] = zh[key]
    return out


def write_okww(automas_dir, path: str, value, okww_dir=None) -> tuple[bool, str]:
    """Write one phone-editable OK-WW master value. A dropdown key (_LIST) only takes
    one of the candidates read from OK-WW's own source (`okww_dir`): upstream sends
    any 「Which to Farm」 that is not Tacet or Forgery to the simulation domain
    (v3.7.4, DailyTask.py:125-127), so a stray string would farm the wrong thing
    without a word. When the source cannot be read, nothing is checked, as before."""
    name, _, key = str(path).partition("/")
    if name in OKWW_READONLY and key in OKWW_READONLY[name]:
        return False, f"{key} 在手机上是只读的（死命令：残象聚落只刷梦枢天罗、落渊南丘）"
    if key not in OKWW_SHOWN.get(name, ()):
        return False, f"{path} 不在手机可改的清单里，已拒绝"
    f = okww_file(automas_dir, name)
    if not f or not f.is_file():
        return False, f"找不到 OK-WW 的母本 {name}"
    doc = json.loads(f.read_text(encoding="utf-8"))
    if key not in doc:
        return False, (f"{name} 里没有「{key}」这一项，已拒绝"
                       "（设置里本来没有它，中继不会自己新建）")
    before = doc[key]
    if isinstance(before, bool):
        new: object = bool(value)
    elif isinstance(before, int) and not isinstance(before, bool):
        try:
            new = int(value)
        except (TypeError, ValueError):
            return False, f"「{key}」要一个整数，收到 {value!r}"
        top = _okww_serial_max(okww_dir, key)
        if top is not None and not 1 <= new <= top:
            return False, f"「{key}」只能是 1 到 {top}（OK-WW 的列表就这么多个），收到 {new}，已拒绝"
    else:
        new = str(value)
        allowed = _okww_cases(okww_dir).get(key)
        if allowed and new not in allowed:
            return False, f"「{key}」只能是 {'、'.join(allowed)} 之一，收到 {new!r}，已拒绝"
    if before == new:
        disp = _okww_index_display(key, before)
        shown = f"{before}（{disp}）" if disp else repr(before)
        return True, f"「{key}」本来就是 {shown}，没有改动"
    doc[key] = new
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    now = json.loads(f.read_text(encoding="utf-8")).get(key)
    if now != new:
        return False, f"写了但没生效：「{key}」现在是 {now!r}"
    b_disp, n_disp = _okww_index_display(key, before), _okww_index_display(key, now)
    b_s = f"{before}（{b_disp}）" if b_disp else repr(before)
    n_s = f"{now}（{n_disp}）" if n_disp else repr(now)
    return True, f"「{key}」：{b_s} → {n_s}"


# MAA and OK-WW config live in mastercfg_maa / mastercfg_okww; callers and tests
# say mastercfg.<name>, so those names are importable from here too.


# This module's public names plus every name re-exported from the modules above
# (callers and tests say mastercfg.<name>); pyflakes and ruff count a listed name as used.


# A WARNING is a group message (errwatch), and read_maaend runs on every phone
# publish: each condition is said once (site -> what was said) and forgotten
# once it clears, so it is said again if it comes back.
_said: dict[str, str] = {}


def _warn_once(site: str, why: str, msg: str, *args, exc_info: bool = False) -> None:
    if _said.get(site) != why:
        log.warning(msg, *args, exc_info=exc_info)
        _said[site] = why


def _cleared(site: str) -> None:
    _said.pop(site, None)


# The items that show up on the phone for tasks that list them by hand.
MAAEND_SHOWN: dict[str, tuple[str, ...]] = {
    "AutoCollect": (
        "@enabled",
        # Besides the switch: which days and which routes it gathers.
        "AutoCollectSchedule",          # Which days to gather (哪几天采)
        "AutoCollectValleyIV",
        "AutoCollectValleyIVRareItems",
        "AutoCollectValleyIVCommonItems",
        "AutoCollectWuling",
        "AutoCollectWulingRareItems",
        "AutoCollectWulingCommonItems",
        # The route lists stay listed for a MaaEnd still on the route format; a key with no definition and no
        # saved value is skipped quietly, so on v2.36 they show nothing once the master is migrated.
        "AutoCollectValleyIVRareRoutes",
        "AutoCollectValleyIVCommonRoutes",
        "AutoCollectWulingRareRoutes",
        "AutoCollectWulingCommonRoutes",
        "AutoCollectMode",              # Tick-list or target-inventory gathering
    ),
}

# Sanity tasks: the phone gets each one's whole option tree, straight from the
# MaaEnd definitions, so no choice MaaEnd offers is missing. MaaEnd itself puts
# exactly these two in the group "sanity_sink" (v2.30.0-rc.1 task declarations);
# any other task MaaEnd adds to that group is picked up too.
# ProtocolSpace sits before AutoEssence in the task list, so with both on it
# spends the sanity first.
MAAEND_TREE_TASKS: tuple[str, ...] = ("ProtocolSpace", "AutoEssence")
MAAEND_TREE_GROUP = "sanity_sink"


_HAN = re.compile(r"[一-鿿]")


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas, leaving strings alone.

    Regex stripping is not enough: MaaEnd writes `"enabled": false //不购买任意物品`
    - a comment after a value on the same line - and CreditShopping.json and
    PuzzleSolver.json failed to parse on that, so the tasks they declare
    (CreditShoppingN2) were reported as orphans. A regex that removes `//.*`
    anywhere would eat "https://" inside strings, so this walks the text.
    Trailing commas are dropped by a second walk for the same reason: a regex
    over the whole text also turned the `\\d{6,}` inside AutoStockStaple.json's
    verify rules into `\\d{6}`.
    """
    return _strip_trailing_commas(_strip_comments(text))


def _strip_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c); i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Drop a comma outside strings whose next non-space character is } or ]."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1; continue
        out.append(c); i += 1
    return "".join(out)


def _jsonc(path: Path) -> dict:
    """MaaEnd task definitions are JSON with comments and trailing commas.

    A file that already parses as JSON is taken as it is: JSON has no comments and no
    trailing commas outside strings, so _strip_jsonc would hand it back unchanged.
    Only the rest goes through the character walker. Measured 2026-10-16 on the 10-12
    machine's MaaEnd (daysim): of interface.json and the 68 files it imports, 63 (4.4 of
    4.7 MB) are plain JSON; walking every file made one _read_maaend_defs take 0.33 s,
    about five reads a relay boot, and with this 0.03 s.
    """
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(_strip_jsonc(text))


class _Locale:
    """`$key` -> Chinese. On a miss, strip the `$` and return it as is. Never invent one."""

    def __init__(self, maaend_dir: Path | None) -> None:
        self.table: dict[str, str] = {}
        if not maaend_dir:
            return
        f = Path(maaend_dir) / "locales" / "interface" / "zh_cn.json"
        try:
            self.table = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _warn_once("locale", f"{f}: {type(exc).__name__}", "读不到 MaaEnd 的中文语言包，手机上只能显示英文键名")
            return
        _cleared("locale")

    def __call__(self, ref: object) -> str:
        s = str(ref or "")
        return self.table.get(s[1:], s[1:]) if s.startswith("$") else s


def maaend_master(automas_dir) -> Path | None:
    d = master_config_dir(automas_dir, "mxu-MaaEnd.json")
    return (d / "mxu-MaaEnd.json") if d else None


def _maaend_instance(doc: dict) -> dict:
    """The AUTO-MAS instance (id "automas"), as plan.py and sanity_plan read it;
    the first one when none is marked (11-08 [D-08]: a second instance listed
    first had its tasks edited instead)."""
    ins = [i for i in (doc.get("instances") or []) if isinstance(i, dict)]
    for i in ins:
        if i.get("id") == "automas" or i.get("name") == "AUTO-MAS":
            return i
    return ins[0] if ins else {}


def _maaend_task(doc: dict, name: str) -> dict | None:
    for t in _maaend_instance(doc).get("tasks", []):
        if t.get("taskName") == name:
            return t
    return None


def set_maaend_enabled(task: dict, on: bool, controller_name) -> bool:
    """Switch a MaaEnd task on or off the way MXU's own UI saves it; True when
    anything changed.

    MXU keeps a per-controller copy of the switch: on every save
    (`src/stores/appStore.ts` generateConfig) it writes
    `enabledByController = cacheTaskEnabledForController(cache, inst.controllerName,
    enabled)` (`src/utils/taskControllerCache.ts`, the same at v2.7.1 and v2.8.0):
    no controller name -> the cache as it was; otherwise `{...cache,
    [controllerName]: enabled}`, so a bare boolean (spread to nothing) becomes a
    dict and other controllers' entries are kept. Writing only `enabled` leaves a
    stale copy that MXU reads when the instance moves to another controller.
    `controller_name` is the task's instance's `controllerName`."""
    before = (task.get("enabled"), task.get("enabledByController"))
    task["enabled"] = on
    if controller_name:
        ctl = task.get("enabledByController")
        cache = dict(ctl) if isinstance(ctl, dict) else {}
        cache[str(controller_name)] = on
        task["enabledByController"] = cache
    return (task.get("enabled"), task.get("enabledByController")) != before


def _maaend_defs(maaend_dir) -> tuple[dict, dict]:
    """(option definitions, task declarations) for the whole MaaEnd install.

    Read from the files `interface.json` imports, which is MaaEnd's own list of
    where its definitions live (a task's file is not always tasks/<task>.json:
    AutoEssence is tasks/AutoEssence/AutoEssence.json). Option names are unique
    across the install, so one flat index is enough. A file that fails to parse
    is skipped and logged.
    """
    opts, tasks, _unread, _listed = _read_maaend_defs(maaend_dir)
    return opts, tasks


def _read_maaend_defs(maaend_dir) -> "tuple[dict, dict, list[tuple[Path, str | None]], bool]":
    """_maaend_defs plus what it could not see: (opts, tasks, unread, listed).

    `unread` is every existing definition file that did not parse, with its raw
    text (None when it could not even be opened; a listed file that does not
    exist defines nothing and is not in it); `listed` is False when the file list is
    the fallback glob because interface.json - MaaEnd's own list - was unreadable.
    """
    opts: dict = {}
    tasks: dict = {}
    unread: list = []
    if not maaend_dir:
        return opts, tasks, unread, False
    root = Path(maaend_dir)
    files: list[Path] = []
    try:
        iface = _jsonc(root / "interface.json")
        files = [root / rel for rel in (iface.get("import") or []) if isinstance(rel, str)]
    except (OSError, ValueError, TypeError) as exc:
        _warn_once("interface", f"{root}: {type(exc).__name__}", "读不到 MaaEnd 的 interface.json，退回按文件名找定义")
    else:
        _cleared("interface")
    listed = bool(files)
    if not files:
        files = sorted((root / "tasks").glob("**/*.json"))
    for f in files:
        try:
            d = _jsonc(f)
        except (OSError, ValueError, TypeError) as exc:
            log.debug("MaaEnd 定义文件读不了 %s: %s", f.name, exc)
            if not f.exists():
                continue            # nothing on disk: it defines nothing
            try:
                unread.append((f, f.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                unread.append((f, None))
            continue
        for name, spec in (d.get("option") or {}).items():
            opts.setdefault(name, spec or {})
        for t in d.get("task") or []:
            if isinstance(t, dict) and t.get("name"):
                tasks.setdefault(t["name"], t)
    return opts, tasks, unread, listed


def _maaend_option_def(maaend_dir, task_name: str, opt: str, opts: dict | None = None) -> dict:
    """The definition of one option, from the install-wide index."""
    if opts is None:
        opts, _ = _maaend_defs(maaend_dir)
    return opts.get(opt) or {}


def _switch_on(case_name) -> bool:
    """MaaFramework ProjectInterface V2: a switch case named Yes/yes/Y/y is the
    on case (docs/en_us/3.3-ProjectInterfaceV2.md, "switch" under cases)."""
    return str(case_name) in ("Yes", "yes", "Y", "y")


_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)\s*")


def _plain(label: str) -> str:
    """Drop the Markdown item icons some MaaEnd labels start with, e.g.
    SupplyPlanLimits: "![](resource/image/UI/Item/item_gold.png) <name>"."""
    return _MD_IMAGE.sub("", str(label or "")).strip()


def _maaend_tree(opts: dict, roots: list[str]) -> tuple[str, ...]:
    """Every option reachable from `roots` through the cases' sub-options,
    parents before children, each once."""
    seen: list[str] = []

    def walk(o: str) -> None:
        if o in seen:
            return
        seen.append(o)
        for c in (opts.get(o) or {}).get("cases") or []:
            for sub in c.get("option") or []:
                walk(str(sub))

    for r in roots:
        walk(r)
    return tuple(seen)


def _maaend_default(d: dict) -> dict | None:
    """The config entry MaaEnd would run for an option absent from the config,
    in the same shape the config uses. None when the definition gives no
    default (a select without default_case)."""
    kind = str(d.get("type") or "")
    if kind == "select":
        return {"type": "select", "caseName": d["default_case"]} if d.get("default_case") is not None else None
    if kind == "switch":
        return {"type": "switch", "value": _switch_on(d.get("default_case"))}
    if kind == "checkbox":
        return {"type": "checkbox", "caseNames": [str(x) for x in d.get("default_case") or []]}
    if kind == "input":
        boxes = [i for i in d.get("inputs") or [] if i.get("name")]
        if not boxes:
            return None
        return {"type": "input", "values": {str(i["name"]): str(i.get("default", "")) for i in boxes}}
    return None


def _maaend_value(kind: str, cur: dict, d: dict, zh) -> tuple:
    """(value for the page, input boxes or None). Several input boxes give
    {input name: text} and [[Chinese label, input name]]; one box gives its text."""
    if kind == "switch":
        return bool(cur.get("value")), None
    if kind == "select":
        return cur.get("caseName"), None
    if kind == "checkbox":
        return list(cur.get("caseNames") or []), None
    vals = cur.get("values") or {}
    boxes = [i for i in d.get("inputs") or [] if i.get("name")]
    if len(boxes) > 1:
        return ({str(i["name"]): str(vals.get(i["name"], i.get("default", ""))) for i in boxes},
                [[_plain(zh(i.get("label"))) or str(i["name"]), str(i["name"])] for i in boxes])
    return next(iter(vals.values()), ""), None


def _maaend_children(task_name: str, kind: str, d: dict) -> dict:
    """{case name: [task/option it opens]}; a switch is keyed "true"/"false"."""
    kids = {}
    for c in d.get("cases") or []:
        sub = [f"{task_name}/{o}" for o in c.get("option") or []]
        if sub and c.get("name") is not None:
            name = str(c["name"])
            if kind == "switch":
                name = "true" if _switch_on(name) else "false"
            kids[name] = sub
    return kids


def read_maaend(automas_dir, maaend_dir) -> dict:
    """Returns `{"values": {"task/option": value},
    "options": {"task/option": [[Chinese label, value]]},
    "labels": {"task/option": Chinese name}}`. Empty when it cannot be read,
    and the page then hides that section.
    """
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        # Said, so the phone page's missing section has a cause in the log.
        _warn_once("master", f"missing: {f}", "母本配置文件不在：%s（手机页那一段会标成读不到）", f or "没找到路径")
        return out
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn_once("master", f"unreadable: {type(exc).__name__}: {exc}", "母本 mxu-MaaEnd.json 读不出来",
                   exc_info=True)
        return out
    _cleared("master")
    zh = _Locale(Path(maaend_dir) if maaend_dir else None)
    all_opts, all_tasks = _maaend_defs(maaend_dir)
    # A task the config still carries but no definition file declares any more.
    if all_tasks:
        # MXU's own entries (__MXU_WEBHOOK__ and the like) are not MaaEnd tasks and
        # never appear in its definitions; they are not orphans.
        out["orphans"] = sorted({t.get("taskName") for inst in doc.get("instances") or []
                                 for t in inst.get("tasks") or []
                                 if t.get("taskName") and not str(t.get("taskName")).startswith("__")
                                 and t.get("taskName") not in all_tasks})
    # The page must never show a raw key. Anything that fails to translate is
    # listed here, logged, and shown on the page as untranslated, not as English.
    out["untranslated"] = []
    shown: dict[str, tuple[str, ...]] = dict(MAAEND_SHOWN)
    tree_tasks = list(MAAEND_TREE_TASKS) + sorted(
        n for n, t in all_tasks.items()
        if MAAEND_TREE_GROUP in (t.get("group") or []) and n not in MAAEND_TREE_TASKS)
    # For the tree tasks the page also gets the shape of the tree: the task's
    # top-level options ("roots") and which choice opens which options
    # ("children", keyed by case name; a switch is keyed "true"/"false").
    # An option whose parent does not currently open it is still listed, with
    # the value MaaEnd would run if it were opened.
    out["roots"] = {}
    out["children"] = {}
    # Options with several input boxes: [[Chinese label, input name]] per box;
    # their value is then {input name: text} instead of one string.
    out["inputs"] = {}
    for n in tree_tasks:
        roots = [str(o) for o in (all_tasks.get(n) or {}).get("option") or []]
        shown[n] = ("@enabled",) + _maaend_tree(all_opts, roots)
        out["roots"][n] = [f"{n}/{o}" for o in roots]
    for task_name, wanted in shown.items():
        task = _maaend_task(doc, task_name)
        if task is None:
            continue
        defs = all_opts
        decl = all_tasks.get(task_name) or {}
        out["labels"][f"{task_name}/@enabled"] = zh(
            decl.get("label") or f"$task.{task_name}.label")
        for opt in wanted:
            key = f"{task_name}/{opt}"
            if opt == "@enabled":
                out["values"][key] = bool(task.get("enabled"))
                continue
            d = defs.get(opt) or _maaend_option_def(maaend_dir, task_name, opt, defs)
            cur = (task.get("optionValues") or {}).get(opt)
            if cur is None:
                # Not in the config yet: MaaEnd then runs its default. Show the
                # default so the page can offer the choice (and write_maaend may
                # create the key, since the definition declares it).
                cur = _maaend_default(d) if d else None
                if cur is None and d.get("type") == "select":
                    # No declared default (ProtocolSpaceTab, the lines, the A/B
                    # sets): the value is unknown (None), the choices still go out.
                    cur = {"type": "select", "caseName": None}
                if cur is None:
                    continue
            label = zh(d.get("label"))
            if not label or label == d.get("label", "").lstrip("$") or not _HAN.search(label):
                out["untranslated"].append(key)
                _warn_once(f"untranslated:{key}", "found" if d else "missing",
                           "MaaEnd 选项 %s 没有中文名（定义%s），手机页会标成没翻译",
                           key, "找到了" if d else "找不到")
            else:
                _cleared(f"untranslated:{key}")
            out["labels"][key] = _plain(label) or opt
            kind = str(cur.get("type") or d.get("type") or "")
            if kind in ("switch", "select", "checkbox", "input"):
                out["values"][key], boxes = _maaend_value(kind, cur, d, zh)
                if boxes:
                    out["inputs"][key] = boxes
            if task_name in tree_tasks and _maaend_children(task_name, kind, d):
                out["children"][key] = _maaend_children(task_name, kind, d)
            if kind in ("select", "checkbox"):
                cases = [[_plain(zh(c.get("label"))) or str(c.get("name")), str(c.get("name"))]
                         for c in (d.get("cases") or []) if c.get("name")]
                if cases:
                    out["options"][key] = cases
                    _cleared(f"no_cases:{key}")
                else:
                    if key not in out["untranslated"]:
                        out["untranslated"].append(key)
                    _warn_once(f"no_cases:{key}", "no cases",
                               "MaaEnd 选项 %s 是选择项但没有可选值，手机页只能给个文本框", key)
    return out


def write_maaend(automas_dir, maaend_dir, path: str, value) -> tuple[bool, str]:
    """Change one item in the master copy. Write only what already exists, then
    read it back -- the same rule as `commands._set_config`.
    """
    task_name, _, opt = str(path).partition("/")
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return False, "找不到 MaaEnd 的母本配置"
    doc = json.loads(f.read_text(encoding="utf-8"))
    task = _maaend_task(doc, task_name)
    if task is None:
        return False, f"母本里没有任务 {task_name}，已拒绝"
    label = task_name
    if opt == "@enabled":
        before = bool(task.get("enabled"))
        if before == bool(value):
            return True, f"{task_name} 本来就是{'开' if before else '关'}着的"
        set_maaend_enabled(task, bool(value), _maaend_instance(doc).get("controllerName"))
    else:
        d = _maaend_option_def(maaend_dir, task_name, opt)
        cur = (task.get("optionValues") or {}).get(opt)
        if cur is None:
            # Only a key MaaEnd's own definition declares for this task may be
            # created, in the shape the definition gives it; nothing else is
            # invented.
            declared = {str(c.get("name")) for c in (d.get("cases") or [])}
            made = _maaend_default(d) if d else None
            if made is None and d.get("type") == "select" and str(value) in declared:
                # A select with no default_case (ProtocolSpaceTab, the three
                # lines, the four A/B sets): created with the value being written.
                made = {"type": "select", "caseName": None}
            if made is None:
                return False, (f"{task_name} 里没有 {opt} 这一项，已拒绝"
                               "（设置里本来没有它，中继不会自己新建）")
            task.setdefault("optionValues", {})[opt] = made
            cur = made
            log.info("母本里 %s 还没有 %s，按 MaaEnd 定义建了这一项：%r", task_name, opt, made)
        kind = str(cur.get("type") or "")
        # The value must be one this item itself declares; no filling in whatever
        allowed = {str(c.get("name")) for c in (d.get("cases") or [])}
        if kind == "switch":
            before = bool(cur.get("value"))
            if isinstance(value, bool):
                cur["value"] = value
            elif str(value).lower() in ("true", "false"):
                cur["value"] = str(value).lower() == "true"
            else:
                return False, f"{opt} 是开关，只接受真或假，收到的是 {value!r}"
        elif kind == "select":
            before = cur.get("caseName")
            if allowed and str(value) not in allowed:
                return False, f"{opt} 不认识取值 {value!r}，它只接受 {sorted(allowed)}"
            cur["caseName"] = str(value)
        elif kind == "checkbox":
            before = list(cur.get("caseNames") or [])
            picked = [str(v) for v in (value if isinstance(value, list) else [value])]
            if allowed and not set(picked) <= allowed:
                return False, f"{opt} 里有不认识的取值：{sorted(set(picked) - allowed)}"
            if not picked:
                return False, f"{opt} 不能一个都不选"
            cur["caseNames"] = picked
        elif kind == "input":
            vals = cur.setdefault("values", {})
            boxes = {str(i["name"]): i for i in d.get("inputs") or [] if i.get("name")}
            if isinstance(value, dict):
                # Several boxes: change only the ones named.
                want = {str(k): str(v) for k, v in value.items()}
            else:
                name = next(iter(vals), "") or next(iter(boxes), "")
                if not name:
                    return False, f"{opt} 没有可填的输入框"
                want = {name: str(value)}
            unknown = sorted(set(want) - set(boxes or vals))
            if unknown:
                return False, f"{opt} 没有这些输入框：{unknown}"
            for name, text in want.items():
                rule = (boxes.get(name) or {}).get("verify")
                if rule and not re.fullmatch(rule, text):
                    return False, f"{opt} 的 {name} 填的 {text!r} 不合格式（{rule}）"
            before = dict(vals) if len(want) > 1 or isinstance(value, dict) else vals.get(next(iter(want)))
            vals.update(want)
        else:
            return False, f"{opt} 是没见过的类型 {kind!r}，不敢动"
        label = f"{task_name} 的 {opt}"
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    if opt == "@enabled":
        return _maaend_readback(f, task_name, opt, label, task["enabled"], "@enabled", before, None)
    return _maaend_readback(f, task_name, opt, label, cur, kind, before,
                            next(iter(want)) if kind == "input" else None)


def _maaend_readback(f: Path, task_name: str, opt: str, label: str, wrote, kind: str,
                     before, box: "str | None") -> tuple[bool, str]:
    """Read back the item write_maaend just wrote, from the file, and compare it
    with what was written (read_maaend covers only the items the phone shows).
    `wrote` is the enabled flag or the option's whole value; `box` is the one
    input box changed when a single box was written."""
    back_task = _maaend_task(json.loads(f.read_text(encoding="utf-8")), task_name) or {}
    if kind == "@enabled":
        now = back_task.get("enabled")
        if now is not wrote:
            return False, f"{task_name} 的开关写进去之后读出来和写的不一样，没改成"
        return True, f"{label}：{before!r} → {now!r}"
    back = (back_task.get("optionValues") or {}).get(opt)
    if back != wrote:
        return False, f"{label} 写进去之后读出来和写的不一样，没改成"
    if kind == "switch":
        now = back.get("value")
    elif kind == "select":
        now = back.get("caseName")
    elif kind == "checkbox":
        now = back.get("caseNames")
    elif isinstance(before, dict):
        now = back.get("values")
    else:
        now = (back.get("values") or {}).get(box)
    return True, f"{label}：{before!r} → {now!r}"


def prune_maaend_orphans(automas_dir, maaend_dir) -> tuple[list[str], str]:
    """Remove config entries for tasks this MaaEnd no longer has. Returns (removed, note).

    A dead entry (MaaEnd v2.28 dropped AutoUseSpMedication, for one) would be
    warned about on the phone page every day; it is removed instead.

    It never removes an entry MaaEnd still defines. Two independent signals are
    required, because the definition index alone is not proof: a definition file
    that fails to parse makes every task it declares look absent. A task
    that is missing from the definitions **and** has no `task.<name>.label` in
    MaaEnd's own language pack is one MaaEnd does not know. On top of that it
    refuses outright - ([], reason) - when it cannot see every definition:
    interface.json (MaaEnd's list of definition files) unreadable, a listed file
    that cannot be opened, or a candidate named in a file that does not parse.
    MXU's internal entries (`__*`) are never touched. The file is backed up first.

    Every deletion and every refusal is a WARNING logged here, so it reaches the
    group (errwatch) each time: a deletion names each entry and whether it was
    switched on. The caller need not log the note again.
    """
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return _prune_refused("找不到 MaaEnd 的母本")
    _, tasks, unread, listed = _read_maaend_defs(maaend_dir)
    if not tasks:
        return _prune_refused("读不到 MaaEnd 的任务定义，不动配置")
    if not listed:
        return _prune_refused("读不到 MaaEnd 的任务定义清单（interface.json），不知道定义全不全，不动配置")
    if blind := [x.name for x, text in unread if text is None]:
        return _prune_refused(f"MaaEnd 的任务定义文件打不开（{'、'.join(blind)}），不知道里面有哪些任务，不动配置")
    zh = _Locale(Path(maaend_dir) if maaend_dir else None)
    if not zh.table:
        return _prune_refused("读不到 MaaEnd 的语言包，不动配置")
    doc = json.loads(f.read_text(encoding="utf-8"))
    removed: list[str] = []
    named: list[str] = []          # 「name（开着/关着）」 for the warning
    for inst in doc.get("instances") or []:
        keep = []
        for t in inst.get("tasks") or []:
            name = str(t.get("taskName") or "")
            dead = (name and not name.startswith("__") and name not in tasks
                    and f"task.{name}.label" not in zh.table)
            if dead and (seen := [x.name for x, text in unread if f'"{name}"' in (text or "")]):
                return _prune_refused(f"MaaEnd 的「{name}」不在读得出的任务定义里，但读不了的定义文件"
                                      f"（{'、'.join(seen)}）里提到它；定义看不全，就不动配置")
            if dead:
                removed.append(name)
                named.append(f"{name}（{'开着' if t.get('enabled') else '关着'}）")
            else:
                keep.append(t)
        inst["tasks"] = keep
    if not removed:
        return [], ""
    bak = f.with_name(f.name + f".bak-orphans-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    bak.write_bytes(f.read_bytes())
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    left = [t.get("taskName") for inst in back.get("instances") or [] for t in inst.get("tasks") or []]
    if any(n in left for n in removed):
        return _prune_refused(f"删 MaaEnd 的死条目时写进去之后读出来和写的不一样，{bak.name} 是原样")
    msg = f"MaaEnd 这一版已经没有这些任务了，已从配置里删掉：{'、'.join(named)}（原文件备份为 {bak.name}）"
    # Every removal reaches the group under its own title (errwatch pushes WARNINGs).
    log.warning("%s", msg, extra=errwatch.alarm(texts.MAAEND_PRUNED, msg))
    return removed, (f"MaaEnd 这一版已经没有这些任务，配置里的死条目已清掉：{'、'.join(removed)}"
                     f"（原文件备份为 {bak.name}）")


def _prune_refused(note: str) -> tuple[list[str], str]:
    msg = f"MaaEnd 配置里失效的任务没有删：{note}"
    log.warning("%s", msg, extra=errwatch.alarm(texts.MAAEND_PRUNED_REFUSED, msg))
    return [], note


_COLLECT_ITEMS = {
    "AutoCollectValleyIVRareRoutes": ("AutoCollectValleyIVRareItems", {
        "Route4": ["item_plant_crylplant_1_2"], "Route5": ["item_plant_spcstone_1_1"],
        "Route6": ["item_plant_mushroom_1_1"], "Route13": ["item_plant_spcstone_1_2"],
        "Route14": ["item_plant_crylplant_1_1"]}),
    "AutoCollectValleyIVCommonRoutes": ("AutoCollectValleyIVCommonItems", {
        "CommonRoute1": ["item_plant_moss_spc_1"], "CommonRoute2": ["item_plant_moss_spc_2"]}),
    "AutoCollectWulingRareRoutes": ("AutoCollectWulingRareItems", {
        "Route1": ["item_plant_crylplant_2_1"], "Route2": ["item_plant_crylplant_2_2"],
        "Route3": ["item_plant_crylplant_1_3"], "Route7": ["item_plant_mushroom_2_1", "item_plant_spcstone_2_2"],
        "Route8": ["item_plant_mushroom_2_2"], "Route9": ["item_plant_spcstone_2_1"],
        "Route10": ["item_plant_mushroom_1_3"], "Route11": ["item_plant_spcstone_1_3"],
        "Route12": ["item_plant_mushroom_1_2"], "Route15": ["item_plant_crylplant_2_3"],
        "Route16": ["item_plant_spcstone_2_3"], "Route17": ["item_plant_mushroom_2_3"]}),
    "AutoCollectWulingCommonRoutes": ("AutoCollectWulingCommonItems", {
        "CommonRoute3": ["item_plant_tundra_insect_2"], "CommonRoute4": ["item_plant_tundra_insect_1"],
        "CommonRoute5": ["item_plant_grass_spc_1"], "CommonRoute6": ["item_plant_sp_3"],
        "CommonRoute7": ["item_plant_grass_spc_2"], "CommonRoute8": ["item_plant_sp_4"]}),
}
_COLLECT_SPLIT = {
    "AutoCollectRoutes": ("AutoCollectValleyIVRareRoutes", "AutoCollectWulingRareRoutes"),
    "AutoCollectCommonRoutes": ("AutoCollectValleyIVCommonRoutes", "AutoCollectWulingCommonRoutes"),
}


def _cases(opts: dict, name: str) -> list[str]:
    return [c.get("name") for c in (opts.get(name) or {}).get("cases") or [] if c.get("name")]


def _checkbox_to_switch(task: str, key: str, ov: dict, opts: dict, zh) -> "str | None":
    """Carry a checkbox of items over to the switch + `<key>Items` that replaced it.

    MaaEnd v2.31/v2.32 turned each 自动囤货 buy list (e.g.
    AutoStockBuyDailyGoodsValleyIV) from a checkbox of items into a switch whose
    on case opens `<key>Items`, a checkbox of the same item names. MaaEnd resets
    a saved value whose type changed to the default (「选项 "…" 的类型已从
    "checkbox" 变更为 "switch"，已重置为默认值」). The picks go to `<key>Items` unchanged; the switch is on when
    anything was picked and off when nothing was (an empty list bought nothing).
    Only that exact shape is translated, and only when every picked item is a
    choice of the new list - otherwise the value is left for the check to report.
    Returns the change line (named by MaaEnd's own Chinese labels: the option
    that opens it, then its own), or None when nothing was done.
    """
    cur = ov.get(key) or {}
    spec = opts.get(key) or {}
    if cur.get("type") != "checkbox" or spec.get("type") != "switch":
        return None
    items = key + "Items"
    on = next((c for c in spec.get("cases") or [] if _switch_on(c.get("name"))), None)
    if (not on or items not in (on.get("option") or [])
            or (opts.get(items) or {}).get("type") != "checkbox"):
        return None
    picked = [str(x) for x in cur.get("caseNames") or []]
    if any(x not in _cases(opts, items) for x in picked):
        return None
    ov[key] = {"type": "switch", "value": bool(picked)}
    ov[items] = {"type": "checkbox", "caseNames": picked}
    parent = next((o for o in opts.values()
                   if any(key in (c.get("option") or []) for c in o.get("cases") or [])), {})
    what = " · ".join(x for x in (zh(parent.get("label")), zh(spec.get("label"))) if x)
    return (f"{what or key}：改成了开关，设为{'开' if picked else '关'}"
            + (f"，原来勾的 {len(picked)} 样照旧勾上" if picked else "（原来一样都没勾）"))


def _stale_entry(entry: dict, opts: dict, tasks: dict) -> bool:
    """A closed-tab record whose task (definition read) carries a key MaaEnd no longer has."""
    return any(str(t.get("taskName") or "") in tasks
               and any(k not in opts for k in (t.get("optionValues") or {}))
               for t in entry.get("tasks") or [])


def _prune_recently_closed(doc: dict, opts: dict, tasks: dict) -> int:
    """Drop stale records from MXU's recentlyClosed list; returns how many went.

    MXU keeps the tabs the user closed under recentlyClosed, option values and
    all, and re-validates them on every load, logging 「已不存在」 for each dead
    key in them.
    """
    before = doc.get("recentlyClosed") or []
    kept = [e for e in before if not _stale_entry(e, opts, tasks)]
    if len(kept) != len(before):
        doc["recentlyClosed"] = kept
    return len(before) - len(kept)


def _migrate_blind(opts, tasks, unread, listed) -> "str | None":
    """migrate_maaend_options' refusal when it cannot see every definition."""
    if not opts or not tasks:
        return "读不到 MaaEnd 的选项定义，不动配置"
    if not listed:
        return "读不到 MaaEnd 的定义文件清单（interface.json），不知道定义全不全，不动配置"
    if blind := [x.name for x, text in unread if text is None]:
        return f"MaaEnd 的定义文件打不开（{'、'.join(blind)}），不知道里面有哪些选项，不动配置"
    return None


def _named_in_unread(keys, unread) -> "str | None":
    """The refusal when a key about to be dropped is named in a file that did not parse."""
    for k in keys:
        if seen := [x.name for x, text in unread if f'"{k}"' in (text or "")]:
            return (f"MaaEnd 的「{k}」不在读得出的选项定义里，但读不了的定义文件"
                    f"（{'、'.join(seen)}）里提到它；定义看不全，就不动配置")
    return None


def _migrate_left_over(back: dict, opts, tasks, switched) -> "str | None":
    """What the migration should have rewritten but the read-back still has."""
    for inst in back.get("instances") or []:
        for task in inst.get("tasks") or []:
            ov = task.get("optionValues") or {}
            if str(task.get("taskName") or "") in tasks and any(k not in opts for k in ov):
                return "旧写法的项还在"
            if any((ov.get(k) or {}).get("type") == "checkbox" for k in switched):
                return "改成开关的项还是多选"
    if any(_stale_entry(e, opts, tasks) for e in back.get("recentlyClosed") or []):
        return "「最近关闭」里旧写法的项还在"
    return None


def _routes_to_items(name: str, ov: dict, opts: dict) -> list[str]:
    """AutoCollect v2.36: route lists -> item lists (the same picks, by what each route gathered)."""
    changes: list[str] = []
    for old, (new_key, items) in _COLLECT_ITEMS.items():
        if old not in ov or new_key in ov or new_key not in opts:
            continue
        picked = list((ov[old] or {}).get("caseNames") or [])
        valid = set(_cases(opts, new_key))
        mine, unknown = [], []
        for route in picked:
            got = [i for i in items.get(route, []) if i in valid]
            if got:
                mine.extend(i for i in got if i not in mine)
            else:
                unknown.append(route)
        ov[new_key] = {"type": "checkbox", "caseNames": mine}
        changes.append(f"{name}/{old} → {new_key}（原来勾的 {len(picked)} 条路线换成 {len(mine)} 样采集物"
                       + (f"；对不上的：{'、'.join(unknown)}" if unknown else "") + "）")
    return changes


def migrate_maaend_options(automas_dir, maaend_dir) -> tuple[list[str], str]:
    """Rewrite option values in the master that this MaaEnd no longer understands.

    Returns (changes, note). A key is dead only when its task's definition file
    was read successfully **and** the key is absent from the whole install's
    option index - a definition file that fails to parse must not make its
    options look dead (9 of MaaEnd v2.32's tasks take options from other files,
    e.g. StashBackpack.json, Location/*.json). So, as prune_maaend_orphans does,
    it refuses outright - ([], reason) - when it cannot see every definition:
    interface.json unreadable (the file list is a guess), a listed file that
    cannot be opened, or a key it would drop named in a file that does not parse.
    MXU's own `__*` tasks are never touched. The file is backed up first and
    read back after.
    """
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return [], "找不到 MaaEnd 的母本"
    opts, tasks, unread, listed = _read_maaend_defs(maaend_dir)
    if why := _migrate_blind(opts, tasks, unread, listed):
        return [], why

    zh = _Locale(Path(maaend_dir))
    doc = json.loads(f.read_text(encoding="utf-8"))
    changes: list[str] = []
    switched: list[str] = []
    for inst in doc.get("instances") or []:
        for task in inst.get("tasks") or []:
            name = str(task.get("taskName") or "")
            if not name or name.startswith("__") or name not in tasks:
                continue
            ov = task.get("optionValues")
            if not isinstance(ov, dict):
                continue
            # 自动采集: one route list -> per-region switch + rare/common lists.
            for old, (valley, wuling) in _COLLECT_SPLIT.items():
                if old not in ov or valley in ov or wuling in ov:
                    continue
                picked = set((ov[old] or {}).get("caseNames") or [])
                for new in (valley, wuling):
                    mine = [c for c in _cases(opts, new) if c in picked]
                    ov[new] = {"type": "checkbox", "caseNames": mine}
                    region = "AutoCollectValleyIV" if "ValleyIV" in new else "AutoCollectWuling"
                    ov.setdefault(region, {"type": "switch", "value": True})
                changes.append(f"{name}/{old} → 按区域拆成 {valley}、{wuling}"
                               f"（保留原来勾的 {len(picked)} 条）")
            changes += _routes_to_items(name, ov, opts)
            if name == "AutoCollect" and "AutoCollectMode" in opts and "AutoCollectMode" not in ov:
                ov["AutoCollectMode"] = {"type": "select", "caseName": "Always"}
                changes.append(f"{name}/AutoCollectMode 补上默认值 Always")
            # 基质刷取: the location list now hangs under AutoEssenceMenu=Random;
            # without the menu key MaaEnd falls back to its default location.
            if name == "AutoEssence":
                if "AutoEssenceMenu" in opts and "AutoEssenceMenu" not in ov:
                    ov["AutoEssenceMenu"] = {"type": "select", "caseName": "Random"}
                    changes.append(f"{name}/AutoEssenceMenu 补上 Random（原来的按地点随机刷）")
                if ("AutoUseSpMedication" in opts and "AutoUseSpMedication" not in ov
                        and "AutoEssenceSpMedicationExpireWithinDays" in ov):
                    ov["AutoUseSpMedication"] = {"type": "select", "caseName": "UseMedication"}
                    changes.append(f"{name}/AutoUseSpMedication 补上 UseMedication（原来就在吃药）")
            for k in list(ov):
                if line := _checkbox_to_switch(name, k, ov, opts, zh):
                    changes.append(line)
                    switched.append(k)
            dead = [k for k in list(ov) if k not in opts]
            if why := _named_in_unread(dead, unread):
                return [], why
            for k in dead:
                del ov[k]
            if dead:
                changes.append(f"{name} 去掉新版本没有的 {len(dead)} 项：{'、'.join(dead)}")
    if why := _named_in_unread((k for e in doc.get("recentlyClosed") or [] for t in e.get("tasks") or []
                                for k in (t.get("optionValues") or {}) if k not in opts), unread):
        return [], why
    if dropped := _prune_recently_closed(doc, opts, tasks):
        changes.append(f"清掉界面里 {dropped} 条「最近关闭」的旧记录（全是旧格式的设置）")
    if not changes:
        return [], ""
    bak = f.with_name(f.name + f".bak-migrate-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    bak.write_bytes(f.read_bytes())
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    if what := _migrate_left_over(json.loads(f.read_text(encoding="utf-8")), opts, tasks, switched):
        return [], f"写进去之后再读，{what}，{bak.name} 是原样"
    return changes, ("MaaEnd 换了版本后旧设置的写法它不认了，母本已按原意改写：\n"
                     + "\n".join(f"· {c}" for c in changes)
                     + f"\n（原文件备份为 {bak.name}）")

__all__ = ['MAAEND_SHOWN', 'MAAEND_TREE_GROUP', 'MAAEND_TREE_TASKS', 'MAA_AWARD', 'MAA_AWARD_PATHS', 'MAA_DRONES', 'MAA_DRONES_PATH', 'MAA_SINGLETON_TASKS', 'OKWW_READONLY', 'OKWW_SHOWN', 'OKWW_SUBS', '_LIST', '_last_error', '_maa_award', '_maa_awards', '_maa_infrast', '_maa_infrasts', '_maa_task', '_maa_tasks', '_okww_cases', '_okww_doc', '_write_maa_award', '_write_maa_copies', 'dedup_maa_task_queue', 'heal_maa_master', 'log', 'maa_master', 'maaend_master', 'migrate_maaend_options', 'okww_file', 'prune_maaend_orphans', 'read_maa', 'read_maaend', 'read_okww', 'set_maaend_enabled', 'write_maa', 'write_maaend', 'write_okww']
