"""MaaEnd's option schema, read from MaaEnd's own files, and MXU's load and run rules.

What the relay writes into the AUTO-MAS master copy of MXU's config
(`mxu-MaaEnd.json`) is judged here against the **installed** MaaEnd's
definitions, never against tables in the relay. Two upstream sources:

* MaaEnd (github.com/MaaEnd/MaaEnd), `assets/`: `interface.json`, every file it
  imports (`tasks/**`), `locales/interface/zh_cn.json`, and the names of the
  pipeline nodes under `resource/pipeline/` (generated from those files at fetch
  time; the files themselves are not kept). Stored under
  `relay/tests/gamesim/upstream/maaend-<tag>/`, byte for byte, with SOURCE.txt.
* MXU (github.com/MistEO/MXU), the GUI the machine runs MaaEnd with. Its load and
  run rules live in TypeScript (`src/stores/helpers.ts` sanitizeOptionValue,
  `src/stores/appStore.ts` config load, `src/utils/pipelineOverride.ts`
  collectOptionOverrides). No JavaScript runtime is on the Mac gate, so those
  functions are ported below. Each port names the upstream function it follows;
  the test pins the sha256 of each vendored file and of each ported function's
  body, so an MXU change turns the test red before the port drifts. The ports
  are validated against MXU's own log lines from the machine (test_gl_maaend_config).

Version on the machine (INSTALLED): read from MXU's app log, see the evidence
string. To swap in the machine's own copy once U0 pulls it: copy
`D:\\ark\\maaend\\interface.json`, `tasks\\`, `locales\\interface\\zh_cn.json`
into `upstream/maaend-<tag>-machine/`, run
`python3.14 maaend_schema.py source <that dir> <tag>` to write its SOURCE.txt
(it records sha256 only; a machine copy has no git blob to check against), and
point INSTALLED_DIR at it.

Command line (needs network; never run by a test):
    python3.14 maaend_schema.py fetch-maaend <tag> [--base <dir of a stored tag>]
    python3.14 maaend_schema.py fetch-mxu <tag>
    python3.14 maaend_schema.py verify <dir>
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

UPSTREAM = Path(__file__).resolve().parents[1] / "upstream"

INSTALLED = "v2.33.0-beta.2"
INSTALLED_EVIDENCE = (
    "daydata D:/ark/maaend/debug/mxu-tauri.log "
    "'[2026-10-13][09:59:13] ... [telemetry] 已初始化 (release=MXU@2.7.1+MaaEnd@v2.33.0-beta.2)'; "
    "2026-10-12-3.log '10:59:40 INFO [App] 检测到刚更新完成: v2.33.0-beta.2'; the 68 imports "
    "MXU merged at 2026-10-13 09:59:17 equal this tag's interface.json imports")
INSTALLED_DIR = UPSTREAM / f"maaend-{INSTALLED}"
MXU = "v2.7.1"
MXU_DIR = UPSTREAM / f"mxu-{MXU}"

MAAEND_REPO = "MaaEnd/MaaEnd"
MXU_REPO = "MistEO/MXU"
MXU_FILES = ("src/stores/helpers.ts", "src/stores/appStore.ts", "src/utils/pipelineOverride.ts",
             "src/utils/optionHelpers.ts", "src/types/specialTasks.ts", "src/services/interfaceLoader.ts")
PIPELINE_PREFIX = "assets/resource/pipeline/"
NODES_FILE = "pipeline-nodes.txt"


# ---------------------------------------------------------------- JSONC

_JSONC = re.compile(r'"(?:[^"\\]|\\.)*+"|//[^\n]*+|(?>/\*.*?\*/)|,(?=(?:\s|//[^\n]*+|(?>/\*.*?\*/))*+[}\]])', re.S)


def jsonc_loads(text: str):
    """JSON with // and /* */ comments and trailing commas, as MaaEnd writes it.

    One regex scan, left to right: a string is matched whole before anything
    inside it can be read as a comment, so "https://" in a value and a comment
    after a value on the same line are both handled. Possessive and atomic
    groups keep a comment from being matched only in part (interface.json has
    commented-out blocks whose text ends in "}"). Written separately from the
    relay's parser on purpose: the test compares the two.
    """
    return json.loads(_JSONC.sub(lambda m: m.group(0) if m.group(0)[0] == '"' else "", text))


def _read_jsonc(path: Path):
    return jsonc_loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- SOURCE.txt

def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def read_source(d: Path) -> dict:
    """SOURCE.txt as {"meta": {key: value}, "file": {path: (sha256, blob)},
    "same": {path: blob}, "src": {path: blob}, "derived": {path: sha256}}."""
    out: dict = {"meta": {}, "file": {}, "same": {}, "src": {}, "derived": {}}
    for line in (Path(d) / "SOURCE.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        kind, _, rest = line.partition(" ")
        if kind == "file":
            sha, blob, path = rest.split(" ", 2)
            out["file"][path] = (sha, blob)
        elif kind == "same":
            blob, path = rest.split(" ", 1)
            out["same"][path] = blob
        elif kind == "src":
            blob, path = rest.split(" ", 1)
            out["src"][path] = blob
        elif kind == "derived":
            sha, path = rest.split(" ", 1)
            out["derived"][path] = sha
        else:
            out["meta"][kind] = rest
    return out


def verify(d: Path) -> list[str]:
    """Every problem with a stored upstream directory: a file whose bytes do not
    match SOURCE.txt, a file not listed, a listed file missing, an overlay whose
    base does not hold the same blob."""
    d = Path(d)
    src = read_source(d)
    bad: list[str] = []
    listed = set(src["file"]) | set(src["derived"]) | {"SOURCE.txt"}
    for path, (sha, blob) in src["file"].items():
        f = d / path
        if not f.is_file():
            bad.append(f"missing {path}")
            continue
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            bad.append(f"sha256 differs {path}")
        if blob != "-" and git_blob_sha1(data) != blob:
            bad.append(f"git blob differs {path}")
    for path, sha in src["derived"].items():
        f = d / path
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != sha:
            bad.append(f"derived file differs {path}")
    for f in d.rglob("*"):
        if f.is_file() and f.relative_to(d).as_posix() not in listed:
            bad.append(f"not in SOURCE.txt {f.relative_to(d).as_posix()}")
    if src["same"]:
        base = UPSTREAM / src["meta"].get("base", "")
        base_files = read_source(base)["file"] if (base / "SOURCE.txt").is_file() else {}
        for path, blob in src["same"].items():
            if (base_files.get(path) or ("", ""))[1] != blob:
                bad.append(f"overlay base does not hold {path} at blob {blob}")
    return bad


def materialize(d: Path, into: Path) -> Path:
    """A full install-shaped directory for a stored tag: an overlay's base files
    plus its own. Returns `into`."""
    d = Path(d)
    src = read_source(d)
    if src["same"]:
        base = UPSTREAM / src["meta"]["base"]
        for path in src["same"]:
            (into / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / path, into / path)
    for path in list(src["file"]) + list(src["derived"]):
        (into / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(d / path, into / path)
    return into


# ---------------------------------------------------------------- definitions

class Defs:
    """A MaaEnd install's ProjectInterface V2 definitions, merged the way MXU
    merges them (interfaceLoader.ts mergeImported: imports in listed order; tasks
    appended, the first of a name is the one `find` returns; options spread, a
    later import's definition wins; global_option appended without repeats).

    `options`: option name -> definition; `tasks`: task name -> declaration;
    `global_option`: the merged list; `dup_options` / `dup_tasks`: names declared
    more than once (the relay's flat index keeps the first, MXU the last option);
    `iface`: interface.json itself; `zh`: the zh_cn table; `nodes`: pipeline
    node names (empty when the directory holds no pipeline-nodes.txt).
    """

    def __init__(self, d: Path) -> None:
        d = Path(d)
        self.dir = d
        self.iface = _read_jsonc(d / "interface.json")
        self.imports = [str(x) for x in self.iface.get("import") or []]
        self.options: dict = {}
        self.tasks: dict = {}
        self.global_option: list[str] = []
        self.task_file: dict[str, str] = {}
        self.option_file: dict[str, str] = {}
        self.dup_options: list[str] = []
        self.dup_tasks: list[str] = []
        for rel, doc in [("interface.json", self.iface)] + [(r, _read_jsonc(d / r)) for r in self.imports]:
            for name, spec in (doc.get("option") or {}).items():
                if name in self.options:
                    self.dup_options.append(name)
                self.options[name] = spec
                self.option_file[name] = rel
            for t in doc.get("task") or []:
                if t["name"] in self.tasks:
                    self.dup_tasks.append(t["name"])
                    continue
                self.tasks[t["name"]] = t
                self.task_file[t["name"]] = rel
            self.global_option += [g for g in doc.get("global_option") or [] if g not in self.global_option]
        zh = d / "locales" / "interface" / "zh_cn.json"
        self.zh = json.loads(zh.read_text(encoding="utf-8")) if zh.is_file() else {}
        nodes = d / NODES_FILE
        self.nodes = set(nodes.read_text(encoding="utf-8").split()) if nodes.is_file() else set()

    def cases(self, option: str) -> list[str]:
        return [str(c["name"]) for c in (self.options.get(option) or {}).get("cases") or []]

    def kind(self, option: str) -> str:
        """The option's type; MXU treats a missing type as select (helpers.ts)."""
        return str((self.options.get(option) or {}).get("type") or "select")


# ---------------------------------------------------------------- MXU ports

# The MXU code each port below follows: name -> (file, start anchor, end anchor).
# With no end anchor the region runs to the first line that closes a top-level
# block ("}" or "};" at column 0). The test pins each region's sha256, so a new
# MXU tag that changes one of them is seen before the port is trusted again.
PORTS = {
    "createDefaultOptionValue": ("src/stores/helpers.ts", "export const createDefaultOptionValue =", None),
    "sanitizeOptionValue": ("src/stores/helpers.ts", "export const sanitizeOptionValue =", None),
    "sanitizeOptionValues": ("src/stores/helpers.ts", "export const sanitizeOptionValues =", None),
    "YES/NO case names": ("src/utils/optionHelpers.ts", "const YES_CASE_NAMES", "const NO_CASE_NAMES"),
    "findSwitchCase": ("src/utils/optionHelpers.ts", "export function findSwitchCase", None),
    "convertHotkeyKeyName": ("src/utils/pipelineOverride.ts", "const convertHotkeyKeyName =", None),
    "splitHotkeyCombo": ("src/utils/pipelineOverride.ts", "const splitHotkeyCombo =", None),
    "collectOptionOverrides": ("src/utils/pipelineOverride.ts", "const collectOptionOverrides =", None),
    "generateTaskPipelineOverride": ("src/utils/pipelineOverride.ts", "export const generateTaskPipelineOverride =", None),
    "mergeImported": ("src/services/interfaceLoader.ts", "function mergeImported(", None),
    "cleanOptionValues": ("src/stores/appStore.ts", "function cleanOptionValues(", None),
    "load: valid task names": ("src/stores/appStore.ts", "const validTaskNames = new Set([",
                               "initializeAllOptionValues(taskDef.option, pi.option)"),
    "load: recentlyClosed": ("src/stores/appStore.ts", "recentlyClosed: (config.recentlyClosed || []).map(",
                             "restoreOptionValuesFromConfig(config.globalOptionValues || {}, pi, projectName),\n"
                             "          };"),
}


def port_region(name: str, mxu_dir: Path = MXU_DIR) -> str:
    """The text of the MXU code a port follows (PORTS); '' when an anchor is gone."""
    rel, start, end = PORTS[name]
    text = (Path(mxu_dir) / rel).read_text(encoding="utf-8")
    i = text.find(start)
    if i < 0:
        return ""
    if end is not None:
        j = text.find(end, i)
        return "" if j < 0 else text[i:j + len(end)]
    m = re.compile(r"\n\};?\n").search(text, i)
    return "" if not m else text[i:m.end()]


YES =("Yes", "yes", "Y", "y")            # optionHelpers.ts YES_CASE_NAMES
NO = ("No", "no", "N", "n")               # optionHelpers.ts NO_CASE_NAMES


def find_switch_case(cases, checked: bool):
    """Port of optionHelpers.ts findSwitchCase."""
    names = YES if checked else NO
    return next((c for c in cases or [] if c.get("name") in names), None)


def default_value(od: dict) -> dict:
    """Port of helpers.ts createDefaultOptionValue."""
    kind = od.get("type")
    if kind == "input":
        return {"type": "input", "values": {i["name"]: i.get("default") or "" for i in od.get("inputs") or []}}
    if kind == "hotkey":
        return {"type": "hotkey", "values": {i["name"]: i.get("default") or "" for i in od.get("hotkeys") or []}}
    cases = od.get("cases") or []
    if kind == "switch":
        dc = od.get("default_case") or (cases[0]["name"] if cases else None) or "Yes"
        return {"type": "switch", "value": dc in YES}
    if kind == "checkbox":
        return {"type": "checkbox", "caseNames": list(od.get("default_case") or [])}
    dc = od.get("default_case") or (cases[0]["name"] if cases else None) or ""
    return {"type": "select", "caseName": dc}


def sanitize_option_value(key: str, value: dict, options: dict, warn: list) -> "dict | None":
    """Port of helpers.ts sanitizeOptionValue: the saved value MXU keeps, or None
    (dropped: MXU then runs the default). Appends MXU's exact warning text to `warn`."""
    od = options.get(key)
    if not od:
        warn.append(f'选项 "{key}" 已不存在，已丢弃保存值')
        return None
    expected = od.get("type") or "select"
    if value.get("type") != expected:
        warn.append(f'选项 "{key}" 的类型已从 "{value.get("type")}" 变更为 "{expected}"，已重置为默认值')
        return None
    if expected == "select":
        if not any(c.get("name") == value.get("caseName") for c in od.get("cases") or []):
            warn.append(f'选项 "{key}" 的 case "{value.get("caseName")}" 已不存在，已重置为默认值')
            return None
        return value
    if expected == "checkbox":
        valid = {c.get("name") for c in od.get("cases") or []}
        saved = list(value.get("caseNames") or [])
        kept = [x for x in saved if x in valid]
        if len(kept) != len(saved):
            gone = ", ".join(str(x) for x in saved if x not in valid)
            warn.append(f'选项 "{key}" 包含已不存在的 case "{gone}"，已过滤')
        if saved and not kept:
            warn.append(f'选项 "{key}" 保存的 case 已全部失效，已重置为默认值')
            return None
        return {"type": "checkbox", "caseNames": kept}
    if expected == "input":
        valid = {i.get("name") for i in od.get("inputs") or []}
        return {"type": "input", "values": {k: v for k, v in (value.get("values") or {}).items() if k in valid}}
    return value


def special_task_names(mxu_dir: Path = MXU_DIR) -> set[str]:
    """MXU's built-in task names (specialTasks.ts MXU_*_TASK_NAME constants)."""
    text = (Path(mxu_dir) / "src/types/specialTasks.ts").read_text(encoding="utf-8")
    return set(re.findall(r"export const MXU_\w+_TASK_NAME = '([^']+)'", text))


def mxu_load(doc: dict, defs: Defs, mxu_dir: Path = MXU_DIR) -> list[str]:
    """Every warning MXU logs when it loads this config (appStore.ts, config load):
    instances' tasks it does not know are removed (one line per instance); every
    other task's optionValues, every recentlyClosed task's, and globalOptionValues
    go through sanitizeOptionValue. MXU's own tasks are left alone."""
    special = special_task_names(mxu_dir)
    warn: list[str] = []
    valid = set(defs.tasks) | special
    for inst in doc.get("instances") or []:
        bad = [t.get("taskName") for t in inst.get("tasks") or [] if t.get("taskName") not in valid]
        if bad:
            warn.append(f'实例 "{inst.get("name")}" 中有 {len(bad)} 个无效任务被移除: {bad}')
        for t in inst.get("tasks") or []:
            if t.get("taskName") in valid and t.get("taskName") not in special:
                for k, v in (t.get("optionValues") or {}).items():
                    sanitize_option_value(k, v, defs.options, warn)
    for rc in doc.get("recentlyClosed") or []:
        for t in rc.get("tasks") or []:
            if t.get("taskName") not in special:
                for k, v in (t.get("optionValues") or {}).items():
                    sanitize_option_value(k, v, defs.options, warn)
    for k, v in (doc.get("globalOptionValues") or {}).items():
        sanitize_option_value(k, v, defs.options, warn)
    return warn


def _hotkey_table(mxu_dir: Path, controller_type: str) -> dict[str, int]:
    """HOTKEY_KEY_MAP[controller_type] read out of the vendored pipelineOverride.ts."""
    text = (Path(mxu_dir) / "src/utils/pipelineOverride.ts").read_text(encoding="utf-8")
    m = re.search(r"\n  " + re.escape(controller_type) + r": \{\n(.*?)\n  \},", text, re.S)
    table: dict[str, int] = {}
    for k, v in re.findall(r"^\s*'?([A-Z0-9]+)'?: (0x[0-9a-f]+),", m.group(1) if m else "", re.M):
        table[k] = int(v, 16)
    return table


class Resolver:
    """Port of pipelineOverride.ts generateTaskPipelineOverride / collectOptionOverrides:
    the pipeline override MXU sends for one task, and every option it reads on the
    way (`reached`, option -> the value in effect)."""

    def __init__(self, defs: Defs, mxu_dir: Path = MXU_DIR) -> None:
        self.defs = defs
        self.mxu_dir = mxu_dir

    def _incompatible(self, od: dict, controller: str, resource: str) -> bool:
        if od.get("controller") and controller not in od["controller"]:
            return True
        return bool(od.get("resource")) and resource not in od["resource"]

    def _collect(self, key, values, out, reached, controller, resource, ctype) -> None:
        od = self.defs.options.get(key)
        if not od or self._incompatible(od, controller, resource):
            return
        saved = values.get(key)
        val = (sanitize_option_value(key, saved, self.defs.options, []) if saved else None) or default_value(od)
        reached[key] = val
        if val["type"] == "checkbox" and od.get("type") == "checkbox":
            picked = set(val["caseNames"])
            out.extend(c["pipeline_override"] for c in od.get("cases") or []
                       if c.get("name") in picked and c.get("pipeline_override"))
        elif val["type"] in ("select", "switch") and "cases" in od:
            if val["type"] == "switch":
                sc = find_switch_case(od["cases"], bool(val["value"]))
                name = sc["name"] if sc else ("Yes" if val["value"] else "No")
            else:
                name = val["caseName"]
            case = next((c for c in od["cases"] if c.get("name") == name), None)
            if case and case.get("pipeline_override"):
                out.append(case["pipeline_override"])
            for sub in (case or {}).get("option") or []:
                self._collect(sub, values, out, reached, controller, resource, ctype)
        elif val["type"] in ("input", "hotkey") and od.get("pipeline_override"):
            out.append(self._fill(od, val, ctype))

    def _fill(self, od: dict, val: dict, ctype: str):
        s = json.dumps(od["pipeline_override"], ensure_ascii=False, separators=(",", ":"))
        boxes = od.get("hotkeys") if od.get("type") == "hotkey" else od.get("inputs")
        for box in boxes or []:
            name = box["name"]
            got = val["values"].get(name)
            text = got if got is not None else (box.get("default") or "")
            if od.get("type") == "hotkey":
                table = _hotkey_table(self.mxu_dir, ctype) or (
                    {} if ctype == "MacOS" else _hotkey_table(self.mxu_dir, "Win32"))
                parts = [p.strip() for p in text.split("+") if p.strip()]
                primary, mods = (parts[-1], parts[:-1]) if parts else ("", [])

                def code(k: str) -> str:
                    v = table.get(k.strip().upper()) if k else None
                    return str(v) if v is not None else ""
                for ph, kc in ((f"{{{name}}}", code(primary)), (f"{{{name}.primary}}", code(primary)),
                               (f"{{{name}.modifier1}}", code(mods[0] if mods else "")),
                               (f"{{{name}.modifier2}}", code(mods[1] if len(mods) > 1 else ""))):
                    s = s.replace(f'"{ph}"', kc or "0").replace(ph, kc or "0")
                continue
            kind = box.get("pipeline_type") or "string"
            ph = f"{{{name}}}"
            if kind == "int":
                s = s.replace(f'"{ph}"', text or "0").replace(ph, text or "0")
            elif kind == "bool":
                b = "true" if (text or "").lower() in ("true", "1", "yes", "y") else "false"
                s = s.replace(f'"{ph}"', b).replace(ph, b)
            else:
                s = s.replace(f'"{ph}"', json.dumps(text, ensure_ascii=False))
                s = s.replace(ph, json.dumps(text, ensure_ascii=False)[1:-1])
        return json.loads(s)

    def task(self, task: dict, controller: str, resource: str, global_values: "dict | None" = None
             ) -> "tuple[list, dict]":
        """(overrides MXU sends for this config entry, {option: value in effect})."""
        out: list = []
        reached: dict = {}
        td = self.defs.tasks.get(task.get("taskName"))
        if not td:
            return out, reached
        cdef = next((c for c in self.defs.iface.get("controller") or [] if c.get("name") == controller), {})
        ctype = cdef.get("type") or ""
        if td.get("pipeline_override"):
            out.append(td["pipeline_override"])
        values = task.get("optionValues") or {}
        for key in self.defs.global_option:
            self._collect(key, global_values or {}, out, reached, controller, resource, ctype)
        rdef = next((r for r in self.defs.iface.get("resource") or [] if r.get("name") == resource), {})
        for key in rdef.get("option") or []:
            self._collect(key, values, out, reached, controller, resource, ctype)
        for key in cdef.get("option") or []:
            self._collect(key, values, out, reached, controller, resource, ctype)
        for key in td.get("option") or []:
            self._collect(key, values, out, reached, controller, resource, ctype)
        return out, reached


def entry_check(defs: Defs, task_name: str, key: str, value: dict) -> "str | None":
    """Why a saved option value is not one MaaEnd defines for this task, or None.

    The checks MXU applies at load (sanitize) plus what the ProjectInterface V2
    document requires of a value (docs/en_us/3.3-ProjectInterfaceV2.md): an input
    box's text must fullmatch its `verify` pattern, and the option must be one
    this task's option tree can reach.
    """
    warn: list[str] = []
    kept = sanitize_option_value(key, value, defs.options, warn)
    if warn or kept != value:
        return "; ".join(warn) or f'选项 "{key}" 的值被 MXU 改写为 {kept!r}'
    od = defs.options[key]
    if od.get("type") == "input":
        for box in od.get("inputs") or []:
            text = (value.get("values") or {}).get(box["name"])
            if text is not None and box.get("verify") and not re.fullmatch(box["verify"], str(text)):
                return f"{key}.{box['name']} = {text!r} does not match verify {box['verify']!r}"
    if key not in option_tree(defs, task_name):
        return f"{key} is not in task {task_name}'s option tree"
    return None


def option_tree(defs: Defs, task_name: str) -> set[str]:
    """Every option a task can reach through any case (select / switch nesting),
    plus the interface's global, resource and controller options."""
    seen: set[str] = set()
    stack = list((defs.tasks.get(task_name) or {}).get("option") or [])
    stack += list(defs.global_option)
    for r in defs.iface.get("resource") or []:
        stack += list(r.get("option") or [])
    for c in defs.iface.get("controller") or []:
        stack += list(c.get("option") or [])
    while stack:
        o = stack.pop()
        if o in seen:
            continue
        seen.add(o)
        for c in (defs.options.get(o) or {}).get("cases") or []:
            stack.extend(c.get("option") or [])
    return seen


def override_nodes(overrides) -> set[str]:
    """Node names a pipeline override (list of objects, or one object) touches."""
    parts = overrides if isinstance(overrides, list) else [overrides]
    return {str(k) for p in parts if isinstance(p, dict) for k in p}


def logged_overrides(log_text: str) -> dict[str, list]:
    """{entry: override list} from MXU app log lines
    `任务[i]: entry=<entry>, pipelineOverride=[...]` (last one per entry)."""
    out: dict[str, list] = {}
    for m in re.finditer(r"entry=(\S+?), pipelineOverride=(\[.*\])\s*$", log_text, re.M):
        out[m.group(1)] = json.loads(m.group(2))
    return out


def mxu_warnings(log_text: str) -> list[str]:
    """The `WARN  [Config] ...` messages of one MXU app log, without timestamps."""
    return re.findall(r"^\S+ \S+ WARN  \[Config\] (.+?)\s*$", log_text, re.M)


# ---------------------------------------------------------------- fetch (network)

def _get(url: str) -> bytes:
    # Unauthenticated: one fetch makes two API calls (tag ref, tree); the files
    # come from raw.githubusercontent.com, which the API rate limit does not count.
    req = urllib.request.Request(url, headers={"User-Agent": "ark-gamesim"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _tag_tree(repo: str, tag: str) -> "tuple[str, dict[str, tuple[str, int]]]":
    ref = json.loads(_get(f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}"))["object"]
    if ref["type"] == "tag":
        ref = json.loads(_get(ref["url"]))["object"]
    commit = ref["sha"]
    tree = json.loads(_get(f"https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1"))
    if tree.get("truncated"):
        raise SystemExit("tree listing truncated")
    return commit, {e["path"]: (e["sha"], e.get("size", 0)) for e in tree["tree"] if e["type"] == "blob"}


def _blob(repo: str, commit: str, path: str, want: str) -> bytes:
    data = _get(f"https://raw.githubusercontent.com/{repo}/{commit}/{path}")
    if git_blob_sha1(data) != want:
        raise SystemExit(f"{path}: downloaded bytes are not blob {want}")
    return data


def _write_source(dest: Path, head: list[str], body: list[str]) -> None:
    (dest / "SOURCE.txt").write_text("\n".join(head + body) + "\n", encoding="utf-8")


def fetch_maaend(tag: str, base: "str | None" = None) -> Path:
    """Store MaaEnd `tag`'s definitions under upstream/maaend-<tag>/.

    With `base` (a stored tag directory name), files whose git blob equals the
    base's are recorded as `same` and not stored again."""
    commit, tree = _tag_tree(MAAEND_REPO, tag)
    dest = UPSTREAM / f"maaend-{tag}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    base_files = read_source(UPSTREAM / base)["file"] if base else {}
    iface = _blob(MAAEND_REPO, commit, "assets/interface.json", tree["assets/interface.json"][0])
    rels = ["interface.json"] + [str(x) for x in jsonc_loads(iface.decode("utf-8")).get("import") or []]
    rels.append("locales/interface/zh_cn.json")
    body: list[str] = []
    for rel in rels:
        path = "assets/" + rel
        if path not in tree:
            body.append(f"# listed but absent at this tag: {rel}")
            continue
        blob = tree[path][0]
        if base and (base_files.get(rel) or ("", ""))[1] == blob:
            body.append(f"same {blob} {rel}")
            continue
        data = iface if rel == "interface.json" else _blob(MAAEND_REPO, commit, path, blob)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(data)
        body.append(f"file {hashlib.sha256(data).hexdigest()} {blob} {rel}")
    nodes: set[str] = set()
    pipes = sorted(p for p in tree if p.startswith(PIPELINE_PREFIX) and p.endswith(".json"))
    for p in pipes:
        doc = jsonc_loads(_blob(MAAEND_REPO, commit, p, tree[p][0]).decode("utf-8"))
        nodes.update(k for k in doc if not k.startswith("$"))
        body.append(f"src {tree[p][0]} {p}")
    text = "\n".join(sorted(nodes)) + "\n"
    (dest / NODES_FILE).write_text(text, encoding="utf-8")
    body.insert(0, f"derived {hashlib.sha256(text.encode('utf-8')).hexdigest()} {NODES_FILE}")
    head = [
        "# MaaEnd definitions as released, byte for byte; never edit by hand.",
        f"# Written by: python3.14 relay/tests/gamesim/lib/maaend_schema.py fetch-maaend {tag}"
        + (f" --base {base}" if base else ""),
        "# Kept: assets/interface.json, every file it imports, assets/locales/interface/zh_cn.json.",
        f"# {NODES_FILE}: the top-level keys of every {PIPELINE_PREFIX}**.json (the src lines),",
        "# i.e. the pipeline node names; the pipeline files themselves are not kept.",
        "# file <sha256> <git blob sha1> <path>   stored here",
        "# same <git blob sha1> <path>            identical in the base directory, not stored",
        f"repo https://github.com/{MAAEND_REPO}",
        f"tag {tag}",
        f"commit {commit}",
        "prefix assets/",
    ] + ([f"base {base}"] if base else [])
    _write_source(dest, head, body)
    return dest


def fetch_mxu(tag: str) -> Path:
    """Store the MXU source files the ports follow under upstream/mxu-<tag>/."""
    commit, tree = _tag_tree(MXU_REPO, tag)
    dest = UPSTREAM / f"mxu-{tag}"
    if dest.exists():
        shutil.rmtree(dest)
    body: list[str] = []
    for path in MXU_FILES:
        data = _blob(MXU_REPO, commit, path, tree[path][0])
        (dest / path).parent.mkdir(parents=True, exist_ok=True)
        (dest / path).write_bytes(data)
        body.append(f"file {hashlib.sha256(data).hexdigest()} {tree[path][0]} {path}")
    head = ["# MXU source files that maaend_schema.py ports; byte for byte, never edit by hand.",
            f"# Written by: python3.14 relay/tests/gamesim/lib/maaend_schema.py fetch-mxu {tag}",
            f"repo https://github.com/{MXU_REPO}", f"tag {tag}", f"commit {commit}"]
    _write_source(dest, head, body)
    return dest


def write_machine_source(d: Path, tag: str) -> None:
    """SOURCE.txt for a copy pulled from the machine (sha256 only, blob '-')."""
    d = Path(d)
    body = [f"file {hashlib.sha256(f.read_bytes()).hexdigest()} - {f.relative_to(d).as_posix()}"
            for f in sorted(d.rglob("*")) if f.is_file() and f.name != "SOURCE.txt"]
    _write_source(d, ["# MaaEnd definitions copied read-only from the game machine's install.",
                      f"tag {tag}", "repo machine D:/ark/maaend"], body)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "fetch-maaend":
        base = argv[argv.index("--base") + 1] if "--base" in argv else None
        print(fetch_maaend(argv[1], base))
    elif len(argv) == 2 and argv[0] == "fetch-mxu":
        print(fetch_mxu(argv[1]))
    elif len(argv) == 3 and argv[0] == "source":
        write_machine_source(Path(argv[1]), argv[2])
    elif len(argv) == 2 and argv[0] == "verify":
        bad = verify(Path(argv[1]))
        print("\n".join(bad) or "ok")
        return 1 if bad else 0
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
