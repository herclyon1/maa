"""What an OK-WW task's config file may hold, read from the upstream source of a fetched tag.

OK-WW never documents its config files; the truth is each task's __init__ (and its
bases' up to ok-script's BaseTask), which fill `default_config` and `config_type`,
and ok-script's `Config.verify_config`, which at load keeps a key only when the
task's default_config has it with a value of the same type, puts the default back
otherwise, and rewrites the file (ok/util/config.py; PITFALLS 2026-09-10: a key only
our overlay knew was gone before any of our code ran).

So this module:
  - evaluates the __init__ chain of a task class from the fetched source, in method
    resolution order, for the statements that build its config: literals, module
    constants (imported ones too), `self.<attr>`, locals, `.update(...)`, item
    assignment, `sum` / `len` / `list`, and calls of argument-less methods of the
    class (`self.add_exit_after_config()`). A statement it cannot evaluate that
    touches default_config or config_type is listed in `skipped`, never guessed;
  - runs ok-script's own Config.verify_config, imported from the fetched copy (only
    ok/util/{config,file,logger}.py execute; the `ok` package __init__, which needs
    Windows, is bypassed by registering the two package names with their paths);
  - lists every place the source reads a config key: `<x>.config.get(KEY ...)` and
    `<x>.config[KEY]`, with KEY a literal or a module constant.

    s = Schema("v3.7.4", "2.0.8")
    t = s.task("FarmEchoTask")      # t.defaults, t.types, t.attrs, t.skipped
    kept, changed = s.verify(t.defaults, doc)
    s.reads("Boss Level")           # [Read(path, line, cls, method, receiver)]
"""
from __future__ import annotations

import ast
import importlib
import shutil
import sys
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fetch_upstream as fu


class Unknown:
    """A value the evaluator could not compute; carries where, so a failure can say so."""

    def __init__(self, where: str):
        self.where = where

    def __repr__(self):
        return f"<unknown: {self.where}>"


@dataclass
class Read:
    key: str
    path: str
    line: int
    cls: str
    method: str
    receiver: str           # 'self' or the expression the config belongs to


@dataclass
class Task:
    name: str
    defaults: dict
    types: dict
    attrs: dict
    skipped: list = field(default_factory=list)   # (path:line, source) of unevaluated config statements


_BUILTINS = {"sum": sum, "len": len, "list": list, "dict": dict, "tuple": tuple, "set": set,
             "sorted": sorted, "str": str, "int": int}


class _Module:
    """One source file: its tree, its lines and (lazily) its constants."""

    def __init__(self, path: str, text: str):
        self.path = path
        self.text = text
        self.tree = ast.parse(text)
        self.lines = text.splitlines(keepends=True)
        self.consts: "dict | None" = None


class Schema:
    def __init__(self, okww_tag: str, okscript_ver: str):
        self.okww = fu.copy_dir("okww", okww_tag)
        self.okscript = fu.copy_dir("okscript", "v" + okscript_ver)
        self.modules: dict[str, _Module] = {}
        for copy in (self.okww, self.okscript):
            for path, data in fu.read_files(copy).items():
                if path.endswith(".py"):
                    self.modules[path] = _Module(path, data.decode("utf-8"))
        # Class name -> (module, ClassDef). OK-WW first: a name defined in both is OK-WW's.
        self.classes: dict[str, tuple[_Module, ast.ClassDef]] = {}
        for mod in self.modules.values():
            for node in mod.tree.body:
                if isinstance(node, ast.ClassDef):
                    self.classes.setdefault(node.name, (mod, node))
        self._verify = None
        self._reads: "list[Read] | None" = None

    # ── classes ──────────────────────────────────────────────────────────────
    def bases(self, cls: str) -> list[str]:
        return [b.id for b in self.classes[cls][1].bases if isinstance(b, ast.Name)]

    def mro(self, cls: str) -> list[str]:
        """C3 linearisation; a base outside both copies ends its chain."""
        if cls not in self.classes:
            return [cls]
        seqs = [self.mro(b) for b in self.bases(cls)] + [self.bases(cls)]
        out = [cls]
        while any(seqs):
            for seq in seqs:
                head = seq[0] if seq else None
                if head and not any(head in s[1:] for s in seqs):
                    break
            else:
                raise TypeError(f"no consistent MRO for {cls}")
            out.append(head)
            seqs = [s[1:] if s and s[0] == head else s for s in seqs]
        return out

    def method(self, cls: str, name: str) -> "tuple[str, _Module, ast.FunctionDef] | None":
        for c in self.mro(cls):
            if c not in self.classes:
                continue
            mod, node = self.classes[c]
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == name:
                    return c, mod, fn
        return None

    # ── constants ────────────────────────────────────────────────────────────
    def _module_of(self, dotted: str) -> "_Module | None":
        base = dotted.replace(".", "/")
        return self.modules.get(base + ".py") or self.modules.get(base + "/__init__.py")

    def consts(self, mod: _Module) -> dict:
        """Top-level names of a module that evaluate: assignments and in-copy imports."""
        if mod.consts is not None:
            return mod.consts
        mod.consts = {}
        for node in mod.tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                src = self._module_of(node.module)
                if src is not None and src is not mod:
                    got = self.consts(src)
                    for a in node.names:
                        if a.name in got:
                            mod.consts[a.asname or a.name] = got[a.name]
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                val = self._ev(node.value, mod, {}, {})
                if not isinstance(val, Unknown):
                    mod.consts[node.targets[0].id] = val
        return mod.consts

    # ── the evaluator ────────────────────────────────────────────────────────
    def _ev(self, node, mod: _Module, local: dict, attrs: dict):
        where = f"{mod.path}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            vals = [self._ev(e, mod, local, attrs) for e in node.elts]
            return vals if isinstance(node, ast.List) else tuple(vals)
        if isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                return Unknown(where)
            keys = [self._ev(k, mod, local, attrs) for k in node.keys]
            if any(isinstance(k, Unknown) for k in keys):
                return Unknown(where)
            return dict(zip(keys, [self._ev(v, mod, local, attrs) for v in node.values], strict=True))
        if isinstance(node, ast.Name):
            if node.id in local:
                return local[node.id]
            if node.id in self.consts(mod):
                return self.consts(mod)[node.id]
            return Unknown(where)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            return attrs.get(node.attr, Unknown(where))
        if isinstance(node, ast.Subscript):
            val = self._ev(node.value, mod, local, attrs)
            idx = self._ev(node.slice, mod, local, attrs)
            try:
                return val[idx]
            except (TypeError, KeyError, IndexError):
                return Unknown(where)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = self._ev(node.left, mod, local, attrs), self._ev(node.right, mod, local, attrs)
            try:
                return a + b
            except TypeError:
                return Unknown(where)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BUILTINS
                and not node.keywords):
            args = [self._ev(a, mod, local, attrs) for a in node.args]
            if any(isinstance(a, Unknown) for a in args):
                return Unknown(where)
            try:
                return _BUILTINS[node.func.id](*args)
            except (TypeError, ValueError):
                return Unknown(where)
        return Unknown(where)

    def _container(self, node, mod, local, attrs):
        """The dict/list a statement mutates: self.<attr> or a local name."""
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            return attrs.get(node.attr)
        if isinstance(node, ast.Name):
            return local.get(node.id)
        return None

    def _run(self, cls: str, fn: ast.FunctionDef, mod: _Module, attrs: dict, skipped: list, depth=0):
        local: dict = {}
        for st in fn.body:
            if not self._step(cls, st, mod, local, attrs, skipped, depth):
                src = ast.get_source_segment(mod.text, st) or ""
                if "default_config" in src or "config_type" in src:
                    skipped.append((f"{mod.path}:{st.lineno}", src.splitlines()[0].strip()))

    def _step(self, cls, st, mod, local, attrs, skipped, depth) -> bool:
        """Apply one statement; False when it is not one this evaluator models."""
        if isinstance(st, ast.Assign) and len(st.targets) == 1:
            t, val = st.targets[0], self._ev(st.value, mod, local, attrs)
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                attrs[t.attr] = val
                return True
            if isinstance(t, ast.Name):
                local[t.id] = val
                return True
            if isinstance(t, ast.Subscript):
                box = self._container(t.value, mod, local, attrs)
                key = self._ev(t.slice, mod, local, attrs)
                if isinstance(box, dict) and not isinstance(key, Unknown):
                    box[key] = val
                    return True
            return False
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            call = st.value
            f = call.func
            if isinstance(f, ast.Attribute) and f.attr == "__init__":
                return True             # super().__init__(...): the MRO walk runs the bases' bodies
            if isinstance(f, ast.Attribute) and f.attr == "update" and len(call.args) == 1 and not call.keywords:
                box = self._container(f.value, mod, local, attrs)
                arg = self._ev(call.args[0], mod, local, attrs)
                if isinstance(box, dict) and isinstance(arg, dict):
                    box.update(arg)
                    return True
                return False
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self"
                    and not call.args and not call.keywords and depth < 3):
                found = self.method(cls, f.attr)
                if found:
                    self._run(cls, found[2], found[1], attrs, skipped, depth + 1)
                    return True
            return False
        return isinstance(st, ast.Pass)

    def task(self, cls: str) -> Task:
        """default_config, config_type and the other attributes a task's __init__ chain sets."""
        attrs: dict = {}
        skipped: list = []
        for c in reversed(self.mro(cls)):
            if c not in self.classes:
                continue
            mod, node = self.classes[c]
            init = next((f for f in node.body if isinstance(f, ast.FunctionDef) and f.name == "__init__"), None)
            if init is not None:
                self._run(cls, init, mod, attrs, skipped)
        return Task(cls, dict(attrs.get("default_config") or {}), dict(attrs.get("config_type") or {}),
                    attrs, skipped)

    # ── where keys are read ──────────────────────────────────────────────────
    def reads(self, key: "str | None" = None) -> list[Read]:
        """Read sites in OK-WW's src/ (all, or of one key)."""
        if self._reads is None:
            self._reads = []
            for mod in self.modules.values():
                if mod.path.startswith("src/"):
                    self._reads += read_sites(mod.tree, self.consts(mod), mod.path)
        return [r for r in self._reads if key is None or r.key == key]

    # ── ok-script's own loader ───────────────────────────────────────────────
    def verify(self, defaults: dict, doc: dict) -> "tuple[dict, bool]":
        """(what ok-script keeps of `doc` at load, whether it rewrote the file), by its own code."""
        if self._verify is None:
            self._verify = _load_verify(self.okscript)
        return self._verify(doc, defaults)


def _config_receiver(node) -> bool:
    """`<x>.config`, or a bare `config` (the daily hands its own to farm_tacet(config=...))."""
    return (isinstance(node, ast.Attribute) and node.attr == "config") or (
        isinstance(node, ast.Name) and node.id == "config")


def read_sites(tree: ast.AST, consts: dict, path: str) -> list[Read]:
    """Every `<x>.config.get(KEY ...)` / `<x>.config[KEY]` / `config.get(KEY ...)` under a tree."""
    out = []

    def key_of(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and isinstance(consts.get(node.id), str):
            return consts[node.id]
        return None

    def visit(node, cls, fn):
        for child in ast.iter_child_nodes(node):
            c, f = cls, fn
            if isinstance(child, ast.ClassDef):
                c = child.name
            elif isinstance(child, ast.FunctionDef):
                f = child.name if fn == "" else f"{fn}.{child.name}"
            target = None
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "get"
                    and _config_receiver(child.func.value) and child.args):
                target = (child.func.value, child.args[0])
            elif (isinstance(child, ast.Subscript) and _config_receiver(child.value)
                  and isinstance(child.ctx, ast.Load)):
                target = (child.value, child.slice)
            if target is not None and (k := key_of(target[1])) is not None:
                owner = target[0].value if isinstance(target[0], ast.Attribute) else target[0]
                out.append(Read(k, path, child.lineno, cls, fn, ast.unparse(owner)))
            visit(child, c, f)

    visit(tree, "", "")
    return out


def _load_verify(okscript_copy: Path):
    """ok-script's Config.verify_config as a function (doc, defaults) -> (kept, changed)."""
    root = Path(tempfile.mkdtemp(prefix="gamesim-okscript-"))
    fu.materialize(okscript_copy, root)
    saved = {k: v for k, v in sys.modules.items() if k == "ok" or k.startswith("ok.")}
    try:
        for name in ("ok", "ok.util"):
            pkg = types.ModuleType(name)
            pkg.__path__ = [str(root.joinpath(*name.split(".")))]
            sys.modules[name] = pkg
        config = importlib.import_module("ok.util.config")
    finally:
        for k in [k for k in sys.modules if k == "ok" or k.startswith("ok.")]:
            del sys.modules[k]
        sys.modules.update(saved)
        # Loaded and compiled; the files are not read again (Config is never constructed,
        # so no path is resolved against them).
        shutil.rmtree(root, ignore_errors=True)

    def verify(doc: dict, defaults: dict) -> "tuple[dict, bool]":
        # A task's Config gets validator=BaseTask.validate, which asks validate_config;
        # the caller checks that no class in the task's MRO overrides validate_config
        # (BaseTask's own returns None, i.e. valid), so no validator is the same thing.
        cfg = config.Config.__new__(config.Config)
        cfg.validator = None
        changed = cfg.verify_config(dict(doc), defaults)
        return dict(cfg), changed

    return verify


# ── which key is read under which mode, through the overlay too ─────────────────
class ModeReads:
    """Is `key` read on a path that only runs when a mode setting equals `mode`?

    A mode is the value an `if` compares a setting with (FarmEchoTask's 'Teleport to Boss':
    `if teleport_to_boss == 'Weekly Challenge':`). A key counts as read under that mode when,
    inside such an `if` body, the key is read or a call leads (up to `depth` calls deep) to
    a function that reads it. Calls resolve as they would at run time with the overlay
    installed: `self.<name>()` goes to the overlay's rebind of <name> when it has one, else
    to upstream's method in the class's MRO; inside the overlay a name bound to an upstream
    method (`pick_level = FarmEchoTask.click_configured_boss_level`) goes to upstream's, and
    any other name to the overlay function of that name. An unguarded call path (upstream's
    walk-in entry) counts for no mode: which screens it reaches is the game's, not config's.
    """

    def __init__(self, schema: Schema, cls: str, overlay_text: str = ""):
        self.s, self.cls = schema, cls
        self.upstream: dict[str, tuple[ast.FunctionDef, dict, str]] = {}
        for c in reversed(schema.mro(cls)):
            if c in schema.classes:
                mod, node = schema.classes[c]
                for fn in node.body:
                    if isinstance(fn, ast.FunctionDef):
                        self.upstream[fn.name] = (fn, schema.consts(mod), mod.path)
        self.ao_funcs: dict[str, ast.FunctionDef] = {}
        self.ao_rebinds: dict[str, ast.FunctionDef] = {}
        self.ao_alias: dict[str, str] = {}
        self.ao_consts: dict = {}
        self._memo: dict = {}
        if overlay_text:
            self._read_overlay(ast.parse(overlay_text), set(schema.mro(cls)))

    def _read_overlay(self, tree, mro):
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Constant)):
                self.ao_consts[node.targets[0].id] = node.value.value
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                self.ao_funcs.setdefault(node.name, node)
                for d in node.decorator_list:
                    if (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "override" and len(d.args) >= 2
                            and isinstance(d.args[0], ast.Name) and d.args[0].id in mro
                            and isinstance(d.args[1], ast.Constant)):
                        self.ao_rebinds[d.args[1].value] = node
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                  and isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name)
                  and node.value.value.id in mro):
                self.ao_alias[node.targets[0].id] = node.value.attr

    def _callees(self, node, in_overlay: bool):
        """(function, consts, path, in_overlay) for each call under node, resolved as at run time."""
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            f = call.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
                if f.attr in self.ao_rebinds:
                    yield self.ao_rebinds[f.attr], self.ao_consts, "overlay", True
                elif f.attr in self.upstream:
                    yield self.upstream[f.attr] + (False,)
            elif isinstance(f, ast.Name) and in_overlay:
                if f.id in self.ao_alias and self.ao_alias[f.id] in self.upstream:
                    yield self.upstream[self.ao_alias[f.id]] + (False,)
                elif f.id in self.ao_funcs:
                    yield self.ao_funcs[f.id], self.ao_consts, "overlay", True

    def _reads(self, node, key, consts, path, in_overlay, depth, seen) -> bool:
        if any(r.key == key for r in read_sites(ast.Module(body=[node], type_ignores=[]), consts, path)):
            return True
        if depth <= 0:
            return False
        for fn, c, p, ov in self._callees(node, in_overlay):
            if id(fn) not in seen:
                seen.add(id(fn))
                if self._reads(fn, key, c, p, ov, depth - 1, seen):
                    return True
        return False

    def read_under(self, key: str, mode: str, depth: int = 4) -> list[str]:
        """Where `key` is read under `mode` ([] = nowhere): 'path:line' of each guarding if."""
        if (key, mode, depth) not in self._memo:
            self._memo[key, mode, depth] = self._read_under(key, mode, depth)
        return self._memo[key, mode, depth]

    def _read_under(self, key: str, mode: str, depth: int) -> list[str]:
        out = []
        functions = [(fn, c, p, False) for fn, c, p in self.upstream.values()]
        functions += [(fn, self.ao_consts, "overlay", True) for fn in self.ao_funcs.values()]
        for fn, consts, path, ov in functions:
            if not ov and fn.name in self.ao_rebinds and fn.name not in self.ao_alias.values():
                continue          # replaced by the overlay, and the overlay never calls upstream's body
            for node in ast.walk(fn):
                if not (isinstance(node, ast.If) and any(isinstance(c, ast.Constant) and c.value == mode
                                                         for c in ast.walk(node.test))):
                    continue
                if any(self._reads(st, key, consts, path, ov, depth, set()) for st in node.body):
                    out.append(f"{path}:{node.lineno}")
        return sorted(set(out))
