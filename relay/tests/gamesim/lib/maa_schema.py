"""MAA and AUTO-MAS names, values and functions, read from the pinned upstream sources.

The pin is relay/tests/gamesim/upstream/maa-v6.19.0-beta.1/ (SOURCE.txt lists every
file with its repo, tag, commit, git blob sha1 and sha256). Nothing here restates an
upstream rule in our own words: names are parsed out of the upstream files, and where
a rule is code (AUTO-MAS's validators, its week marker, its config copy, its task
lookup) the upstream function itself is executed, cut out of the pinned file.

Used by tests/test_gl_maa_config.py (Mac) and gamesim/maa/append_check.py (Windows).
"""
from __future__ import annotations

import ast
import hashlib
import re
import shutil
import textwrap
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

PIN = Path(__file__).resolve().parents[1] / "upstream" / "maa-v6.19.0-beta.1"
MAA = PIN / "maa"
AUTOMAS = PIN / "automas"


# ---------- the pin itself ----------

def pin_rows() -> list[dict]:
    """SOURCE.txt rows: local, repo, tag, commit, path, blob, sha256."""
    rows = []
    for line in (PIN / "SOURCE.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        local, repo, tag, commit, path, blob, sha = line.split("\t")
        rows.append({"local": local, "repo": repo, "tag": tag, "commit": commit,
                     "path": path, "blob": blob, "sha256": sha})
    return rows


def pin_problems() -> list[str]:
    """Files that differ from SOURCE.txt (edited by hand), are missing, or are not listed."""
    out = []
    listed = set()
    for r in pin_rows():
        listed.add(r["local"])
        f = PIN / r["local"]
        if not f.is_file():
            out.append(f"missing: {r['local']}")
            continue
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            out.append(f"sha256 differs: {r['local']}")
        if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != r["blob"]:
            out.append(f"git blob differs: {r['local']}")
    for f in PIN.rglob("*"):
        rel = f.relative_to(PIN).as_posix()
        if f.is_file() and rel != "SOURCE.txt" and rel not in listed:
            out.append(f"not in SOURCE.txt: {rel}")
    return out


def maa_text(path: str) -> str:
    return (MAA / path).read_text(encoding="utf-8")


def automas_text(path: str) -> str:
    return (AUTOMAS / f"{path}.txt").read_text(encoding="utf-8")


def body_sha(text: str) -> str:
    """sha256 of a function body with line endings normalised."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def cpp_body(path: str, qualified: str) -> str:
    """The definition of C++ function `qualified` (e.g. "asst::FightTask::set_params"),
    from its signature to the matching closing brace."""
    text = maa_text(path)
    m = re.search(r"^[^\n;{}]*\b" + re.escape(qualified) + r"\s*\(", text, re.M)
    if not m:
        raise KeyError(f"{qualified} not in {path}")
    depth, i = 0, text.index("{", m.end())
    while True:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[m.start():i]


def _py_node(text: str, qualname: str) -> ast.AST:
    node: ast.AST = ast.parse(text)
    for part in qualname.split("."):
        node = next(n for n in node.body  # type: ignore[attr-defined]
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and n.name == part)
    return node


def py_body(path: str, qualname: str) -> str:
    """The source of top-level function or method `qualname` ("f" or "Class.f") in an
    AUTO-MAS file, dedented."""
    text = automas_text(path)
    return textwrap.dedent(ast.get_source_segment(text, _py_node(text, qualname), padded=True) or "")


def load_method(path: str, qualname: str, seed: dict):
    """An AUTO-MAS method executed from its pinned source as a plain function taking
    `self` first; `seed` holds the module names it uses."""
    ns = dict(seed)
    exec(compile(py_body(path, qualname), path, "exec"), ns)
    return ns[qualname.rsplit(".", 1)[-1]]


# ---------- MAA's GUI config (gui.new.json) ----------

def cs_properties(path: str) -> dict[str, str]:
    """Public auto-properties of a C# class file: {name: type}."""
    return dict((n, t) for t, n in re.findall(
        r"^\s*public\s+([\w<>?,\s\[\]]+?)\s+(\w+)\s*\{\s*get;", maa_text(path), re.M))


def drone_keys() -> list[str]:
    """InfrastSettingsUserControlModel.UsesOfDronesList: the values the GUI offers."""
    text = maa_text("src/MaaWpfGui/ViewModels/UserControl/TaskQueue/InfrastSettingsUserControlModel.cs")
    block = re.search(r"UsesOfDronesList\s*\{[^}]*\}\s*=\s*new\((.*?)\);", text, re.S)
    if not block:
        raise KeyError("UsesOfDronesList")
    return re.findall(r'\(\s*"(\w+)"\s*,', block.group(1))


def derived_types() -> list[str]:
    """BaseTask's [JsonDerivedType] discriminators: the "$type" values MAA can read back."""
    text = maa_text("src/MaaWpfGui/Configuration/Single/MaaTask/BaseTask.cs")
    return re.findall(r"^\[JsonDerivedType\(typeof\(\w+\),\s*typeDiscriminator:\s*nameof\((\w+)\)\)\]",
                      text, re.M)


def core_param(path: str, prop: str) -> str | None:
    """The MaaCore parameter a GUI property is sent as: `["drones"] = UsesOfDrones` in a
    Serialize() body, or `[JsonProperty("mail")] public bool Mail`."""
    text = maa_text(path)
    m = (re.search(r'\["(\w+)"\]\s*=\s*' + re.escape(prop) + r"\s*,", text)
         or re.search(r'\[JsonProperty\("(\w+)"\)\]\s*public\s+\w+\s+' + re.escape(prop) + r"\b", text))
    return m.group(1) if m else None


def core_reads(path: str) -> set[str]:
    """The parameter names a MaaCore task reads: `params.get("name", ...)`."""
    return set(re.findall(r'params\.get\("(\w+)"', maa_text(path)))


# ---------- MAA's stage data ----------

def make_maa_install(root: Path, yw: str | None = None) -> Path:
    """A MAA folder holding the pinned resource/tasks tree; `yw` ("c09d3fe7" or
    "cc780293") lays that dev commit's Stages/YW.json over it, as MAA's resource
    update did on the machine. No cache/resource: no hot update."""
    tasks = root / "resource" / "tasks"
    shutil.copytree(MAA / "resource" / "tasks", tasks, dirs_exist_ok=True)
    if yw:
        shutil.copyfile(PIN / f"maa-dev-{yw}" / "resource" / "tasks" / "Stages" / "YW.json",
                        tasks / "Stages" / "YW.json")
    return root


# ---------- AUTO-MAS ----------

def load_upstream(path: str, names: list[str], seed: dict) -> dict:
    """Execute the top-level definitions `names` of a pinned AUTO-MAS file, in file
    order, in a namespace seeded with `seed` (the stdlib names they use). Upstream's
    own code runs; nothing is restated."""
    text = automas_text(path)
    ns = dict(seed)
    wanted = set(names)
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            name = target.id if isinstance(target, ast.Name) else ""
        else:
            continue
        if name in wanted:
            node_src = ast.get_source_segment(text, node) or ""
            exec(compile(ast.Module([ast.parse(node_src).body[0]], []), path, "exec"), ns)
            wanted.discard(name)
    if wanted:
        raise KeyError(f"not in {path}: {sorted(wanted)}")
    return ns


def automas_items(cls: str) -> dict[str, ast.Call | None]:
    """ConfigItem declarations of an AUTO-MAS config class:
    {"Section.Key": validator call node, or None for the default StringValidator}."""
    tree = ast.parse(automas_text("app/models/config.py"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    out: dict = {}
    for call in ast.walk(node):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "ConfigItem" and len(call.args) >= 3
                and all(isinstance(a, ast.Constant) for a in call.args[:2])):
            validator = call.args[3] if len(call.args) > 3 else None
            out[f"{call.args[0].value}.{call.args[1].value}"] = validator
    return out


def validator_for(cls: str, item: str):
    """The upstream validator object of `cls`'s `item`, built from its declaration with
    AUTO-MAS's own validator classes. Raises KeyError for an undeclared item and
    ValueError for a validator whose arguments are not literals."""
    call = automas_items(cls)[item]
    ns = load_upstream("app/models/ConfigBase.py",
                       ["ValidatorBase", "StringValidator", "RangeValidator", "OptionsValidator",
                        "BoolValidator"], _validator_seed())
    if call is None:
        return ns["StringValidator"]()
    name = call.func.id if isinstance(call.func, ast.Name) else ""
    if name not in ns:
        raise ValueError(f"{cls} {item}: validator {name} is not one of the executed classes")
    try:
        args = [ast.literal_eval(a) for a in call.args]
    except ValueError as exc:
        raise ValueError(f"{cls} {item}: {name} takes non-literal arguments") from exc
    return ns[name](*args)


def _validator_seed() -> dict:
    return {"ABC": ABC, "abstractmethod": abstractmethod, "Any": Any}


# The AUTO-MAS files that read a MAA script's config while it runs: AutoProxy (the run),
# manager (the client update gate) and the shared game_update task.
READERS = ("app/task/MAA/AutoProxy.py", "app/task/MAA/manager.py", "app/task/game_update.py")


def automas_reads() -> dict[str, str]:
    """Every "Section.Key" the reader files read, with where: literal
    `<config>.get("Section", "Key")` calls, plus the Info keys of constants.MAA_STAGE_KEY
    when AutoProxy reads `.get("Info", stage_key)` for each of them."""
    out: dict[str, str] = {}
    for path in READERS:
        text = automas_text(path)
        for call in ast.walk(ast.parse(text)):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "get" and len(call.args) >= 2):
                continue
            sec, key = call.args[:2]
            if not (isinstance(sec, ast.Constant) and isinstance(sec.value, str)):
                continue
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.setdefault(f"{sec.value}.{key.value}", f"{path}:{call.lineno}")
            elif isinstance(key, ast.Name) and key.id == "stage_key" and path.endswith("AutoProxy.py"):
                for k in load_upstream("app/utils/constants.py", ["MAA_STAGE_KEY"], {})["MAA_STAGE_KEY"]:
                    out.setdefault(f"{sec.value}.{k}", f"{path}:{call.lineno} (MAA_STAGE_KEY)")
    return out
