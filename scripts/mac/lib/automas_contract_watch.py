"""Does the newest AUTO-MAS release (betas included) still keep every setting the relay reads?

AUTO-MAS installs its own updates on the game machine from the beta channel (the relay's
pre-update asks its backend, boot_stages._stage_preupdate). v5.7.0-beta.3, published
2026-10-13 07:23 UTC and installed there 10-14 08:46 Beijing, moved the MAA user's stage items
from Info to a new Stage group (relay/ark_relay/core/mastercfg.py); the relay read nothing for
13 hours. This tool looks at a release before the machine installs it, from this Mac:

1. asks GitHub for the newest release of AUTO-MAS-Project/AUTO-MAS, prereleases included
   (GET /repos/{repo}/releases, no token; `gh api` when it is installed and logged in);
2. fetches the model definitions at that tag:
   - AUTO-MAS v5.8+: app/models/config/*.py (Pydantic ConfigGroup / DomainEntry models,
     including cross-file inheritance such as OkwwTaskFields and Annotated[..., legacy(...)]);
   - AUTO-MAS v5.10+: also fetches extracted adapter repositories (e.g. AUTO-MAS-MAA-Adapter
     for MaaConfig / MaaUserConfig / MaaPlanConfig) when the release uses the plugin host;
   - pre-v5.8 fallback: app/models/config.py (ConfigItem + module helpers + base classes);
3. compares them with the relay's list (relay/ark_relay/core/mastercfg.py CONTRACT) and
   prints every listed item the release no longer defines where the relay looks, and items
   that moved (the release defines the key elsewhere with legacy / legacy_group / legacy_name
   pointing at the old place).

An item counts as kept when the class defines Group.Key, or - for a key masuser.MOVED knows -
Info.Key (the relay reads both, older AUTO-MAS kept them in Info), or - for a key
mastercfg.SPLIT_USER_KEYS knows - the legacy pre-split key when none of the split keys exist.
A ConfigItem whose group or key is not a string literal (MaaPlanConfig's per-day rows, built in
a loop) is kept as a wildcard and matches any group / key, an f-string key as a pattern
(MaaEndUserConfig's f"If{task}" -> "If*"): such an item cannot be told apart from source alone.

    python3 scripts/mac/lib/automas_contract_watch.py [--tag vX.Y.Z] [--file path]
Exit 0 = nothing the relay reads changed, 2 = something did (printed), 3 = GitHub could not
be read (or the file had no config classes). Output is for us; nothing is scheduled to run
it (the acceptance session decides that).
"""
from __future__ import annotations

import ast
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "AUTO-MAS-Project/AUTO-MAS"
CONFIG_DIR = "app/models/config"
CONFIG_PATH = "app/models/config.py"
# AUTO-MAS v5.10+ moved built-in adapters out of app/models/config/ into separate plugin
# repositories (declared in AUTO-MAS app/core/config/plugin_upgrade.py _ADAPTER_PLUGINS).
ADAPTER_REPOS: dict[str, tuple[str, str]] = {
    "MaaConfig": ("AUTO-MAS-Project/AUTO-MAS-MAA-Adapter", "src/maa_adapter/config"),
    "MaaUserConfig": ("AUTO-MAS-Project/AUTO-MAS-MAA-Adapter", "src/maa_adapter/config"),
    "MaaPlanConfig": ("AUTO-MAS-Project/AUTO-MAS-MAA-Adapter", "src/maa_adapter/config"),
}
_RELAY = Path(__file__).resolve().parents[3] / "relay"
# Seconds per GitHub request.
_TIMEOUT = 30

_CLASS = re.compile(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", re.M)
_DEF = re.compile(r"^def\s+(\w+)\s*\(", re.M)
# A line at column 0 that is not blank, a comment or the close of a wrapped signature.
_TOP_LEVEL = re.compile(r"^(?=[^\s#)\]])", re.M)
_CALL = re.compile(r"\bConfigItem\(")
_STR = re.compile(r"""\s*(f?)(?:"([^"\\]*)"|'([^'\\]*)')\s*$""", re.S)
_KW = re.compile(r"""\b(legacy_group|legacy_name)\s*=\s*["']([^"']+)["']""")
WILD = "*"


# ------------------------------------------------------------------ upstream source (legacy ConfigItem)

def _call_args(text: str, start: int) -> str:
    """The text between the "(" at `start` - 1 and its matching ")", quotes respected."""
    depth, i, quote = 1, start, ""
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return text[start:]


def _split_top(args: str) -> list[str]:
    """`args` split at commas outside brackets and quotes."""
    out, depth, quote, cur = [], 0, "", []
    i = 0
    while i < len(args):
        c = args[i]
        if quote:
            if c == "\\" and i + 1 < len(args):
                cur.append(c)
                i += 1
                c = args[i]
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def _literal(arg: str) -> str:
    """A string literal's value; an f-string as a pattern with "*" for each {...}
    (f"If{MAAEND_DELIVERY_TASK}" -> "If*"); WILD for anything else (a loop variable)."""
    m = _STR.match(arg)
    if not m:
        return WILD
    value = m.group(2) if m.group(2) is not None else m.group(3)
    return re.sub(r"\{[^}]*\}", "*", value) if m.group(1) else value


def _items(body: str) -> dict[tuple[str, str], "tuple[str, str] | None"]:
    """{(group, key): (legacy group, legacy key) or None} of the ConfigItem calls in `body`."""
    out: dict = {}
    for m in _CALL.finditer(body):
        args = _split_top(_call_args(body, m.end()))
        if len(args) < 2:
            continue
        group, key = _literal(args[0]), _literal(args[1])
        kws = dict(_KW.findall(",".join(args[2:])))
        legacy = None
        if kws:
            legacy = (kws.get("legacy_group", group), kws.get("legacy_name", key))
        out[(group, key)] = legacy
    return out


def _helpers(text: str) -> dict[str, str]:
    """Module-level functions: name -> source, up to the next top-level line."""
    out = {}
    for m in _DEF.finditer(text):
        line_end = text.find("\n", m.end())
        nxt = _TOP_LEVEL.search(text, line_end + 1) if line_end >= 0 else None
        out[m.group(1)] = text[m.start():nxt.start() if nxt else len(text)]
    return out


def _parse_legacy(texts: list[str]) -> dict[str, dict]:
    """Legacy pre-v5.8 ConfigItem parser across one or more source texts."""
    if not any("ConfigItem(" in t for t in texts):
        return {}
    all_helpers: dict[str, str] = {}
    file_helpers: list[tuple[str, dict[str, str]]] = []
    for text in texts:
        h = _helpers(text)
        file_helpers.append((text, h))
        for name, src in h.items():
            all_helpers.setdefault(name, src)
    own: dict[str, dict] = {}
    bases: dict[str, str] = {}
    for text, helpers in file_helpers:
        marks = list(_CLASS.finditer(text))
        for i, cm in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            nxt = _TOP_LEVEL.search(text, text.find("\n", cm.end()) + 1)
            if nxt and nxt.start() < end:
                end = nxt.start()
            body = text[cm.end():end]
            found = _items(body)
            for name in dict.fromkeys(re.findall(r"\b(\w+)\(self\)", body)):
                src = helpers.get(name) or all_helpers.get(name, "")
                for k, v in _items(src).items():
                    found.setdefault(k, v)
            own[cm.group(1)] = found
            bases[cm.group(1)] = (cm.group(2) or "").split(",")[0].strip()
    out = {}
    for name in own:
        merged: dict = {}
        seen, cur = set(), name
        while cur in own and cur not in seen:       # own items first, then the bases'
            seen.add(cur)
            for k, v in own[cur].items():
                merged.setdefault(k, v)
            cur = bases.get(cur, "")
        out[name] = merged
    return out


# ------------------------------------------------------------------ upstream source (v5.8+ Pydantic AST)

def _ast_dotted(node: ast.AST) -> "str | None":
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _ast_dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return None


def _ast_group_type(expr: ast.AST) -> "str | None":
    if isinstance(expr, ast.Subscript):
        name = _ast_dotted(expr.value)
        tail = name.rsplit(".", 1)[-1] if name else ""
        if tail == "Annotated" and isinstance(expr.slice, ast.Tuple) and expr.slice.elts:
            return _ast_group_type(expr.slice.elts[0])
        return None
    return _ast_dotted(expr)


def _is_skipped_ann(expr: ast.AST) -> bool:
    name = _ast_dotted(expr.value) if isinstance(expr, ast.Subscript) else _ast_dotted(expr)
    tail = name.rsplit(".", 1)[-1] if name else ""
    return tail in ("ClassVar", "ConfigCollection")


def _ast_legacy(expr: ast.AST, group: str, key: str) -> "tuple[str, str] | None":
    """Extract (legacy_group, legacy_name) from Annotated[T, ..., legacy(group=..., name=...)]."""
    if not (isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Tuple)):
        return None
    name = _ast_dotted(expr.value)
    if not name or name.rsplit(".", 1)[-1] != "Annotated":
        return None
    for meta in expr.slice.elts[1:]:
        if not isinstance(meta, ast.Call):
            continue
        fn = _ast_dotted(meta.func)
        if not fn or fn.rsplit(".", 1)[-1] != "legacy":
            continue
        lg, ln = group, key
        if len(meta.args) >= 1 and isinstance(meta.args[0], ast.Constant) and isinstance(meta.args[0].value, str):
            lg = meta.args[0].value
        if len(meta.args) >= 2 and isinstance(meta.args[1], ast.Constant) and isinstance(meta.args[1].value, str):
            ln = meta.args[1].value
        for kw in meta.keywords:
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                if kw.arg == "group":
                    lg = kw.value.value
                elif kw.arg == "name":
                    ln = kw.value.value
        return (lg, ln)
    return None


class _PydanticModelIndex:
    """AST index over AUTO-MAS v5.8+/v5.10 Pydantic ConfigGroup / DomainEntry files."""

    def __init__(self, texts: list[str]) -> None:
        self.file_classes: list[dict[str, ast.ClassDef]] = []
        self.top_classes: dict[str, tuple[int, ast.ClassDef]] = {}
        self.tuple_aliases: dict[str, list[str]] = {}
        for idx, text in enumerate(texts):
            self._index_file(idx, text)

    def _index_file(self, idx: int, text: str) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            self.file_classes.append({})
            return
        local_cls: dict[str, ast.ClassDef] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef):
                local_cls[stmt.name] = stmt
                self.top_classes.setdefault(stmt.name, (idx, stmt))
            elif (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                  and isinstance(stmt.targets[0], ast.Name)
                  and isinstance(stmt.value, (ast.Tuple, ast.List))):
                names = [n for e in stmt.value.elts if (n := _ast_dotted(e))]
                if names and len(names) == len(stmt.value.elts):
                    self.tuple_aliases[stmt.targets[0].id] = names
        self.file_classes.append(local_cls)

    def lookup(self, name: str, file_idx: int,
               outer_nested: dict[str, ast.ClassDef]) -> "tuple[int, ast.ClassDef] | None":
        if name in outer_nested:
            return file_idx, outer_nested[name]
        if "." in name:
            owner, sub = name.split(".", 1)
            local = self.file_classes[file_idx]
            hit = (file_idx, local[owner]) if owner in local else self.top_classes.get(owner)
            if hit:
                h_idx, o_cls = hit
                for s in o_cls.body:
                    if isinstance(s, ast.ClassDef) and s.name == sub:
                        return h_idx, s
            return None
        if name in self.file_classes[file_idx]:
            return file_idx, self.file_classes[file_idx][name]
        return self.top_classes.get(name)

    def expand_bases(self, cls_node: ast.ClassDef) -> list[str]:
        names: list[str] = []
        for b in cls_node.bases:
            if isinstance(b, ast.Starred):
                sn = _ast_dotted(b.value)
                if sn and sn in self.tuple_aliases:
                    names.extend(self.tuple_aliases[sn])
            elif (bn := _ast_dotted(b)):
                names.append(bn)
        return names

    def group_fields(self, file_idx: int, cls_node: ast.ClassDef, group: str,
                     outer_nested: dict[str, ast.ClassDef], seen: set[int]) -> dict[tuple[str, str], "tuple[str, str] | None"]:
        if id(cls_node) in seen:
            return {}
        seen = seen | {id(cls_node)}
        fields: dict[tuple[str, str], "tuple[str, str] | None"] = {}
        for stmt in cls_node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            key = stmt.target.id
            if key.startswith("_") or _is_skipped_ann(stmt.annotation):
                continue
            fields[(group, key)] = _ast_legacy(stmt.annotation, group, key)
        for bn in self.expand_bases(cls_node):
            hit = self.lookup(bn, file_idx, outer_nested)
            if hit:
                for k, v in self.group_fields(hit[0], hit[1], group, outer_nested, seen).items():
                    fields.setdefault(k, v)
        return fields

    def entry_items(self, file_idx: int, cls_node: ast.ClassDef, seen: set[int]) -> dict[tuple[str, str], "tuple[str, str] | None"]:
        if id(cls_node) in seen:
            return {}
        seen = seen | {id(cls_node)}
        nested = {s.name: s for s in cls_node.body if isinstance(s, ast.ClassDef)}
        found: dict[tuple[str, str], "tuple[str, str] | None"] = {}
        for stmt in cls_node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            grp = stmt.target.id
            if grp.startswith("_") or _is_skipped_ann(stmt.annotation):
                continue
            gtype = _ast_group_type(stmt.annotation)
            hit = self.lookup(gtype, file_idx, nested) if gtype else None
            if hit:
                for k, v in self.group_fields(hit[0], hit[1], grp, nested, set()).items():
                    found[k] = v
        for bn in self.expand_bases(cls_node):
            hit = self.lookup(bn, file_idx, {})
            if hit:
                for k, v in self.entry_items(hit[0], hit[1], seen).items():
                    found.setdefault(k, v)
        return found


def _parse_pydantic(texts: list[str]) -> dict[str, dict]:
    """Parse AUTO-MAS v5.8+/v5.10 Pydantic ConfigGroup / DomainEntry classes across files."""
    index = _PydanticModelIndex(texts)
    out: dict[str, dict] = {}
    for file_idx, local_cls in enumerate(index.file_classes):
        for name, cls_node in local_cls.items():
            items = index.entry_items(file_idx, cls_node, set())
            if items:
                out.setdefault(name, {}).update(items)
    return out


def parse(source: "str | dict[str, str] | list[str]") -> dict[str, dict]:
    """{class name: {(group, key): legacy or None}} for every config class in AUTO-MAS model
    source(s), supporting both pre-v5.8 ConfigItem and v5.8+/v5.10 Pydantic ConfigGroup models."""
    if isinstance(source, str):
        texts = [source]
    elif isinstance(source, dict):
        texts = list(source.values())
    else:
        texts = list(source)
    out = _parse_legacy(texts)
    for name, items in _parse_pydantic(texts).items():
        if items:
            merged = dict(out.get(name) or {})
            merged.update(items)
            out[name] = merged
    return out


# ------------------------------------------------------------------ the comparison

def _defines(items: dict, group: str, key: str) -> bool:
    return any(fnmatch.fnmatchcase(group, g) and fnmatch.fnmatchcase(key, k) for g, k in items)


_TAG_VER = re.compile(r"v\d+\.\d+\.\d+(?:-beta\.\d+)?")


def _ver_key(version: str):
    m = _TAG_VER.search(str(version or ""))
    if not m:
        return None
    base, _, beta = m.group(0).lstrip("v").partition("-beta.")
    parts = [int(x) for x in base.split(".")]
    return (*parts, 0 if beta else 1, int(beta or 0))


def compare(classes: dict[str, dict], contract, moved: "dict[str, str] | None" = None,
            version: str = "", split_keys: "dict[tuple[str, str, str], str] | None" = None) -> list[str]:
    """One plain line per listed item `classes` (parse()) no longer keeps where the relay
    reads it; [] when every item is kept. `moved` is masuser.MOVED: those keys are read from
    their new group or from Info. `split_keys` is mastercfg.SPLIT_USER_KEYS: pre-split schemas
    keeping only the legacy key count as kept. When `version` is given, items introduced after
    it (`since`) are skipped."""
    moved = moved or {}
    split_keys = split_keys or {}
    have = _ver_key(version)
    out = []
    for it in contract:
        if have is not None and getattr(it, "since", ""):
            need = _ver_key(it.since)
            if need is not None and have < need:
                continue
        items = classes.get(it.owner)
        if items is None:
            out.append(f"{it.owner} {it.group}.{it.key}: class {it.owner} is gone (feature {it.use}; read by {it.source})")
            continue
        if _defines(items, it.group, it.key):
            continue
        if it.key in moved and _defines(items, "Info", it.key):
            continue
        legacy_key = split_keys.get((it.kind, it.group, it.key))
        if legacy_key and _defines(items, it.group, legacy_key):
            siblings = [k for (kd, g, k), lk in split_keys.items()
                        if kd == it.kind and g == it.group and lk == legacy_key]
            if not any(_defines(items, it.group, k) for k in siblings):
                continue
        # Moved: the release defines the key somewhere else and names the old place as its legacy.
        to = [f"{g}.{k}" for (g, k), legacy in items.items()
              if legacy == (it.group, it.key) and (g, k) != (it.group, it.key)]
        where = f"moved to {', '.join(to)}" if to else "no longer defined"
        out.append(f"{it.owner} {it.group}.{it.key}: {where} (feature {it.use}; read by {it.source})")
    return out


# ------------------------------------------------------------------ GitHub

def _gh(path: str) -> "str | None":
    """`gh api <path>` output, or None when gh is missing or fails."""
    gh = shutil.which("gh") or next(
        (p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if Path(p).is_file()), None)
    if not gh:
        return None
    try:
        r = subprocess.run([gh, "api", path], capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _http(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ark-relay-contract-watch",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def newest_tag(repo: str = REPO) -> str:
    """The newest release's tag, prereleases included (the list is newest first)."""
    path = f"repos/{repo}/releases?per_page=10"
    raw = _gh(path) or _http(f"https://api.github.com/{path}")
    rels = [r for r in json.loads(raw) if isinstance(r, dict) and not r.get("draft")]
    if not rels:
        raise ValueError(f"no releases listed for {repo}")
    rels.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    return str(rels[0]["tag_name"])


def _list_py_files(repo: str, dir_path: str, ref: str) -> list[str]:
    path = f"repos/{repo}/contents/{dir_path}?ref={ref}"
    raw = _gh(path) or _http(f"https://api.github.com/{path}")
    entries = json.loads(raw)
    if not isinstance(entries, list):
        raise ValueError(f"{repo}/{dir_path}@{ref} is not a directory listing")
    return sorted(
        str(e["path"]) for e in entries
        if isinstance(e, dict) and e.get("type") == "file" and str(e.get("path", "")).endswith(".py")
    )


def _fetch_dir_sources(repo: str, dir_path: str, ref: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in _list_py_files(repo, dir_path, ref):
        if p.endswith("/__init__.py"):
            continue
        out[f"{repo}:{p}"] = _http(f"https://raw.githubusercontent.com/{repo}/{ref}/{p}")
    return out


def fetch_config(tag: str) -> dict[str, str]:
    """Fetch AUTO-MAS model source files for `tag`: v5.8+ app/models/config/*.py, falling back
    to pre-v5.8 single-file app/models/config.py when the directory does not exist (404)."""
    try:
        sources = _fetch_dir_sources(REPO, CONFIG_DIR, tag)
        if sources:
            return sources
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    return {f"{REPO}:{CONFIG_PATH}": _http(f"https://raw.githubusercontent.com/{REPO}/{tag}/{CONFIG_PATH}")}


def _fetch_plugin_adapters(sources: dict[str, str], classes: dict[str, dict], contract) -> dict[str, str]:
    """For plugin-host releases (v5.10+, which ship app/models/config/plugin*.py), fetch
    official extracted adapter repos for any contract owner missing from the core config dir."""
    if not any(k.endswith(("/plugin.py", "/plugin_script.py")) for k in sources):
        return sources
    needed: dict[tuple[str, str], None] = {}
    for it in contract:
        if it.owner not in classes and it.owner in ADAPTER_REPOS:
            needed[ADAPTER_REPOS[it.owner]] = None
    if not needed:
        return sources
    merged = dict(sources)
    for adapter_repo, adapter_dir in needed:
        atag = newest_tag(adapter_repo)
        merged.update(_fetch_dir_sources(adapter_repo, adapter_dir, atag))
    return merged


def _read_local(path: Path) -> dict[str, str]:
    if path.is_file():
        return {path.name: path.read_text(encoding="utf-8")}
    if not path.is_dir():
        raise FileNotFoundError(str(path))
    roots: list[Path] = []
    for cand in (path / "repo" / "app" / "models" / "config",
                 path / "app" / "models" / "config"):
        if cand.is_dir():
            roots.append(cand)
            break
    else:
        roots.append(path)
    sp = path / "plugins" / "pypi" / "site-packages"
    if sp.is_dir():
        for pkg in sorted(sp.iterdir()):
            if pkg.is_dir() and not pkg.name.startswith(".") and not pkg.name.endswith((".dist-info", ".egg-info")):
                if (pkg / "config").is_dir():
                    roots.append(pkg / "config")
    out: dict[str, str] = {}
    for base in roots:
        for f in sorted(base.rglob("*.py")):
            rel = f.relative_to(base).parts
            if any(p.startswith(".") or p in ("__pycache__", "legacy_config") for p in rel):
                continue
            out[str(f)] = f.read_text(encoding="utf-8", errors="replace")
    return out


def _relay_contract():
    sys.path.insert(0, str(_RELAY))
    from ark_relay.core import mastercfg as masuser, mastercfg as mascontract  # noqa: PLC0415
    return mascontract.CONTRACT, masuser.MOVED, masuser.SPLIT_USER_KEYS


def main(argv: list[str]) -> int:
    tag, file = "", ""
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--tag" and args:
            tag = args.pop(0)
        elif a == "--file" and args:
            file = args.pop(0)
        else:
            print(__doc__)
            return 3
    contract, moved, split_keys = _relay_contract()
    try:
        if file:
            sources, tag = _read_local(Path(file)), tag or file
            classes = parse(sources)
        else:
            tag = tag or newest_tag()
            sources = fetch_config(tag)
            classes = parse(sources)
            expanded = _fetch_plugin_adapters(sources, classes, contract)
            if len(expanded) > len(sources):
                classes = parse(expanded)
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        print(f"GitHub could not be read: {type(exc).__name__}: {exc}")
        return 3
    if not classes:
        print(f"{tag}: {CONFIG_DIR} / {CONFIG_PATH} has no config classes - not the source expected")
        return 3
    gaps = compare(classes, contract, moved, version=tag, split_keys=split_keys)
    if not gaps:
        print(f"{tag}: all {len(contract)} AUTO-MAS settings the relay reads are still there")
        return 0
    print(f"{tag}: {len(gaps)} of {len(contract)} AUTO-MAS settings the relay reads changed:")
    for g in gaps:
        print(f"  - {g}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
