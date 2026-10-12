"""Every tool we have written down exists and works against the new relay.

The user asked on 10-11 at 17:28 whether the tools the relay uses are all current, the four
programs checking for updates themselves (BOARD/DECISIONS.md, D-1011 on tools being current). What
nobody checked was our own tooling. On 10-11 eight tools (healthcheck.py, maaend_only_task.py, okww_effective.py,
config-check.py, okww-landed.py, waittime_roundtrip.py, boot_check_remote.py,
skip-shutdown.bat) were still importing the copy of ark_relay frozen in
C:\\ProgramData\\ark-relay at the switch-over - the health check would have re-applied old
OK-WW patches over newer fixes - and nothing noticed. This is lint-repo.sh item 22.

What it checks (offline, a second or so):
  1. Every script path named in the rule files - ~/Claude/CLAUDE.md, the repo CLAUDE.md
     tool table, docs/TOOLING.md, ~/.claude/projects/-Users-herclyon-Claude/memory/*.md -
     exists in this tree. Paths under scripts/, relay/, packaging/ (also written as
     ~/Claude/maa-automation/...) and ark_relay/...; bare script names (`winrun.sh`) only in
     the repo's own two documents, where they can only mean this repo. A path to a relay
     module that moved on 10-11 gets its new place as a hint (the same file name elsewhere
     under relay/ark_relay; relay/ark_relay/_aliases.py while the relay still had it).
  2. No tool under scripts/ puts the old code folder on sys.path: the literal folder (or a
     variable set to it, one level, Python or .bat) inside sys.path.insert/append; or a file
     that imports ark_relay, names the bare folder and never looks for the installed relay
     (relay_code / code_root / current.txt); or a path to code inside the data folder.
     The data paths under it (.env, state, relay.log) stay legitimate for good.
  3. Every `import ark_relay...` / `from ark_relay... import x` in a tool resolves in the
     new relay: as a module or package under relay/ark_relay, or through an old name the
     relay still aliases (none since split-service dropped _aliases.py), and every imported name is a
     submodule or a top-level name of that module. A path to a file inside ark_relay that
     is not there (an old flat path, say) fails too: aliases cover imports, not paths.
  4. The shared top-level checkout (the repository's main worktree, which other sessions
     and the user's tools run from) is not behind origin/main. On 10-11 it sat 359
     commits behind with an estop.sh that did not know the new relay.
  5. Every hook file in ~/.claude/hooks that says it runs is registered (settings.json or
     hooks/registry.json, or run by a registered hook) or listed as paused; every
     ~/.claude/hooks/<x>.py a rule file names exists. 10-06's alert-inbox-hook.py lost its
     registration in the 10-10 slimming and was dead for four days.
  6. Every entry of a paused list whose hook is not running gives a reason built on facts:
     a measured time (`66 ms`) or a dated entry of the error ledgers (`被指出.txt 10-10 18:27`,
     `报错台账.txt 10-11 12:54`). On 10-11 sixteen entries gave only one quote of the user
     (his 10-10 17:12 words that hooks should go off if they slow things down) and nobody had
     measured a hook or looked up what it guards against; he asked for reasons, not his own
     words read back.

    python3 scripts/mac/lib/tool_refs.py [--root DIR] [--doc FILE ...] [--no-git]
                                        [--hooks DIR|none] [--settings FILE]

--doc replaces the default rule files (tests); a default rule file that does not exist on
this machine is skipped with a note. Exit 1 with one `file:line: why` per finding.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

HOME = Path.home()
DEFAULT_DOCS = [
    HOME / "Claude/CLAUDE.md",
    "CLAUDE.md",                        # relative = inside --root
    "docs/TOOLING.md",
    HOME / ".claude/projects/-Users-herclyon-Claude/memory/*.md",
]
# Documents that belong to this repo: a bare script name in them can only mean this repo.
OWN_DOCS = {"CLAUDE.md", "docs/TOOLING.md"}
TOOL_EXT = (".py", ".sh", ".bat", ".cmd", ".ps1")
# Deliberate users of the old layout, each with its reason. Only rule 2 is waived.
OLD_DIR_ALLOW = {
    "scripts/mac/deploy-relay.sh":
        "its LAYOUT=legacy branch deploys to and checks the old service on purpose; the "
        "installed relay takes scripts/mac/lib/deploy-pkg.sh",
    "scripts/windows/smoke.py":
        "deploy-pkg.sh passes --pkg-version=<n> on the installed relay; without an argument "
        "it is the legacy branch's smoke",
}

_PATH_CHARS = r"A-Za-z0-9_./~-"
REPO_PATH = re.compile(
    rf"(?<![{_PATH_CHARS}])(?:(?:~|/Users/[^/\s]+)/Claude/maa-automation/)?"
    r"((?:scripts|relay|packaging)/[A-Za-z0-9_./-]*?[A-Za-z0-9_-]"
    r"\.(?:py|sh|bat|cmd|ps1|swift|iss|js))(?![A-Za-z0-9_/-])")
PKG_PATH = re.compile(
    rf"(?<![{_PATH_CHARS}])(ark_relay/[A-Za-z0-9_./-]*?[A-Za-z0-9_-]\.py)(?![A-Za-z0-9_/-])")
BARE_NAME = re.compile(           # not a <placeholder.py>
    rf"(?<![<{_PATH_CHARS}])([A-Za-z0-9_-]+\.(?:sh|py|bat|ps1))(?![A-Za-z0-9_/-])")

OLD_DIR = r"ProgramData(?:\\\\|\\|/)+ark-relay(?![\w-])"
OLD_DIR_RE = re.compile(OLD_DIR, re.IGNORECASE)
# The bare folder: not followed by a path separator and a name (a data path).
OLD_DIR_BARE = re.compile(OLD_DIR + r"(?!(?:\\\\|\\|/)+[\w.])", re.IGNORECASE)
OLD_CODE_PATH = re.compile(
    OLD_DIR + r"(?:\\\\|\\|/)+(?:ark_relay|service\.py|run\.py|app_main\.py|boot_stages\.py)\b",
    re.IGNORECASE)
# What goes on the path: the argument up to its first ")" (enough for str(X) and r'%X%').
SYS_PATH = re.compile(r"sys\.path\.(?:insert|append)\s*\(([^)]*)|PYTHONPATH=(\S*)")
PY_ASSIGN = re.compile(r"^\s*((?:[A-Za-z_]\w*\s*=\s*)+)")
BAT_SET = re.compile(r'^\s*set\s+"?([A-Za-z_]\w*)=', re.IGNORECASE)
INSTALLED_MARKER = re.compile(r"relay_code|code_root|current\.txt")
IMPORTS_PKG = re.compile(r"\b(?:from|import)\s+ark_relay\b")
FROM_IMPORT = re.compile(r"\bfrom\s+(ark_relay(?:\.\w+)*)\s+import\s+([\w\s,()]+?)(?:;|$|\"|')")
PLAIN_IMPORT = re.compile(r"(?:^|[;\s\"'])import\s+(ark_relay(?:\.\w+)*)")
PKG_REF = re.compile(r"(?<![A-Za-z0-9_-])ark_relay((?:(?:\\\\|\\|/)[A-Za-z0-9_.*]+)+)")


class Finding(list):
    """(where, why) pairs in the order found."""

    def add(self, where: str, why: str) -> None:
        self.append((where, why))


def load_moved(root: Path) -> dict:
    """The relay's own table of moved modules (relay/ark_relay/_aliases.py MOVED).

    {} once the relay drops _aliases.py (split-service): an old name then no longer
    imports, so it must not resolve here either; a path hint still comes from the
    same-name search in check_file."""
    try:
        src = (root / "relay/ark_relay/_aliases.py").read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "MOVED" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def is_comment(line: str, ext: str) -> bool:
    s = line.lstrip()
    if ext in (".bat", ".cmd"):
        return s.lower().startswith(("rem ", "rem\t", "::")) or s.lower() == "rem"
    return s.startswith("#")


class Relay:
    """Resolves dotted names and paths against relay/ark_relay in --root."""

    def __init__(self, root: Path):
        self.pkg = root / "relay/ark_relay"
        self.moved = load_moved(root)
        self._names: dict = {}

    def _file(self, parts: "list[str]") -> "Path | None":
        base = self.pkg.joinpath(*parts) if parts else self.pkg
        if base.with_suffix(".py").is_file() and parts:
            return base.with_suffix(".py")
        if (base / "__init__.py").is_file():
            return base / "__init__.py"
        return None

    def resolve(self, dotted: str) -> "tuple[Path | None, bool]":
        """(the module's file, True when reached only through an old alias)."""
        parts = dotted.split(".")[1:]
        f = self._file(parts)
        if f is not None:
            return f, False
        if parts and parts[0] in self.moved:
            return self._file(self.moved[parts[0]].split(".") + parts[1:]), True
        return None, False

    def top_names(self, f: Path) -> "set[str] | None":
        """Top-level names of a module; None = it can serve any name (__getattr__, *)."""
        if f not in self._names:
            names: "set[str] | None" = set()
            stack = list(ast.parse(f.read_text(encoding="utf-8")).body)
            while stack and names is not None:
                n = stack.pop()
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if n.name == "__getattr__":
                        names = None
                        break
                    names.add(n.name)
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    for a in n.names:
                        if a.name == "*":
                            names = None
                            break
                        names.add(a.asname or a.name.split(".")[0])
                elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for t in targets:
                        for x in ast.walk(t):
                            if isinstance(x, ast.Name):
                                names.add(x.id)
                elif isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                    for field in ("body", "orelse", "finalbody", "handlers"):
                        stack.extend(getattr(n, field, []) or [])
                elif isinstance(n, ast.ExceptHandler):
                    stack.extend(n.body)
            self._names[f] = names
        return self._names[f]

    def check_from(self, module: str, names: "list[str]") -> "list[str]":
        """Why `from module import names` fails in the new relay ([] = it works)."""
        f, _ = self.resolve(module)
        if f is None:
            return [f"{module}: no such module in the new relay (not in relay/ark_relay, "
                    "not an old name the relay still aliases)"]
        bad = []
        for n in names:
            if self.resolve(f"{module}.{n}")[0] is not None:
                continue
            if module == "ark_relay" and n in self.moved:
                continue
            top = self.top_names(f)
            if top is not None and n not in top:
                bad.append(f"{module}.{n}: {f.relative_to(self.pkg.parent.parent)} "
                           "has no such name")
        return bad

    def new_place(self, rel: str) -> str:
        """For an old path relay/ark_relay/<x>..., where it is now ('' = not a moved module)."""
        parts = rel.split("/")[2:]
        if not parts:
            return ""
        head = parts[0][:-3] if parts[0].endswith(".py") else parts[0]
        if head not in self.moved:
            return ""
        new = "relay/ark_relay/" + self.moved[head].replace(".", "/")
        return new + ("/" + "/".join(parts[1:]) if parts[1:] else ".py")


def tracked(root: Path, use_git: bool) -> "list[str]":
    if use_git:
        r = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True,
                           text=True, check=False)
        if r.returncode == 0:
            return r.stdout.splitlines()
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__")]
        out += [str(Path(d, f).relative_to(root)) for f in files]
    return out


def expand_docs(root: Path, docs: list) -> "tuple[list[tuple[Path, str]], list[str]]":
    """[(file, name shown)], [notes about default files missing on this machine]."""
    out, notes = [], []
    for d in docs:
        p = Path(d)
        if not p.is_absolute():
            p = root / p
        if "*" not in p.name and p.exists():
            p = p.resolve()             # /var vs /private/var: show it relative to --root
        if "*" in p.name:
            hits = sorted(p.parent.glob(p.name))
            if not hits:
                notes.append(f"skipped (not on this machine): {p}")
            out += [(h, str(h).replace(str(HOME), "~")) for h in hits]
        elif p.is_file():
            shown = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            out.append((p, shown.replace(str(HOME), "~")))
        else:
            notes.append(f"skipped (not on this machine): {p}")
    return out, notes


def check_docs(root: Path, docs, relay: Relay, files: "list[str]", bad: Finding) -> int:
    basenames: dict = {}
    for f in files:
        basenames.setdefault(f.rsplit("/", 1)[-1], []).append(f)
    count = 0
    for path, shown in docs:
        own = shown in OWN_DOCS
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            mentioned = [m.group(1) for m in REPO_PATH.finditer(line)]
            mentioned += ["relay/" + m.group(1) for m in PKG_PATH.finditer(line)]
            for rel in mentioned:
                count += 1
                if (root / rel).exists():
                    continue
                hint = relay.new_place(rel) if rel.startswith("relay/ark_relay/") else ""
                if not hint:
                    same = basenames.get(rel.rsplit("/", 1)[-1], [])
                    hint = same[0] if len(same) == 1 else ""
                bad.add(f"{shown}:{i}", f"{rel} does not exist"
                        + (f" (now {hint})" if hint else ""))
            if not own:
                continue
            for m in BARE_NAME.finditer(line):
                name = m.group(1)
                if any(name in r for r in mentioned):
                    continue
                count += 1
                if name not in basenames:
                    bad.add(f"{shown}:{i}", f"script {name} is not in the repo")
    return count


def check_old_dir(rel: str, lines: "list[str]", ext: str, bad: Finding) -> None:
    if rel in OLD_DIR_ALLOW:
        return
    text = "\n".join(lines)
    old_vars = set()
    for line in lines:
        if not OLD_DIR_BARE.search(line) or is_comment(line, ext):
            continue
        m = BAT_SET.match(line) if ext in (".bat", ".cmd") else PY_ASSIGN.match(line)
        if m:
            old_vars.update(re.findall(r"[A-Za-z_]\w*", m.group(1)))
    var_re = (re.compile(r"%(" + "|".join(sorted(old_vars)) + r")%" if ext in (".bat", ".cmd")
                         else r"\b(" + "|".join(sorted(old_vars)) + r")\b")
              if old_vars else None)
    aware = bool(INSTALLED_MARKER.search(text))
    imports = bool(IMPORTS_PKG.search(text))
    for i, line in enumerate(lines, 1):
        if is_comment(line, ext):
            continue
        where = f"{rel}:{i}"
        args = " ".join(m.group(1) or m.group(2) or "" for m in SYS_PATH.finditer(line))
        if args and (OLD_DIR_RE.search(args) or (var_re and var_re.search(args))):
            bad.add(where, "puts the old relay's code folder C:\\ProgramData\\ark-relay on "
                    "sys.path (the installed relay's code is {app}\\versions\\<current.txt>)")
        elif not aware and OLD_CODE_PATH.search(line):
            bad.add(where, "reads code from the old relay's folder in C:\\ProgramData\\ark-relay")
        elif not aware and imports and OLD_DIR_BARE.search(line):
            bad.add(where, "imports ark_relay with C:\\ProgramData\\ark-relay as its code folder "
                    "and never looks for the installed relay (relay_code / current.txt)")


def module_refs(rel: str, lines: "list[str]", ext: str) -> "list[tuple[int, str, list[str]]]":
    """(line, module, names imported from it) for every ark_relay import in a tool."""
    refs: dict = {}
    if ext == ".py":
        try:
            tree = ast.parse("\n".join(lines))
        except SyntaxError:
            tree = None
        for n in ast.walk(tree) if tree else []:
            if isinstance(n, ast.ImportFrom) and not n.level and (n.module or "").split(".")[0] == "ark_relay":
                refs[n.lineno] = [(n.module, [a.name for a in n.names])]
            elif isinstance(n, ast.Import):
                mods = [(a.name, []) for a in n.names if a.name.split(".")[0] == "ark_relay"]
                if mods:
                    refs[n.lineno] = mods
    for i, line in enumerate(lines, 1):
        if i in refs or is_comment(line, ext):
            continue
        got = []
        for m in FROM_IMPORT.finditer(line):
            names = [x.split()[0] for x in m.group(2).replace("(", " ").replace(")", " ").split(",")
                     if x.split()]
            got.append((m.group(1), names))
        got += [(m.group(1), []) for m in PLAIN_IMPORT.finditer(line)
                if not FROM_IMPORT.search(line)]
        if got:
            refs[i] = got
    return [(i, mod, names) for i in sorted(refs) for mod, names in refs[i]]


def check_tool(root: Path, rel: str, relay: Relay, bad: Finding) -> "tuple[int, int]":
    ext = Path(rel).suffix.lower()
    lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    check_old_dir(rel, lines, ext, bad)
    n_imports = 0
    for i, mod, names in module_refs(rel, lines, ext):
        n_imports += 1
        why = relay.check_from(mod, names) if names else (
            [] if relay.resolve(mod)[0] else [f"{mod}: no such module in the new relay"])
        for w in why:
            bad.add(f"{rel}:{i}", w)
    n_paths = 0
    for i, line in enumerate(lines, 1):
        if is_comment(line, ext):
            continue
        for m in PKG_REF.finditer(line):
            parts = [p for p in re.split(r"[\\/]+", m.group(1)) if p]
            cut = next((k for k, p in enumerate(parts) if "*" in p or p == "__pycache__"), len(parts))
            parts = [p.rstrip(".") for p in parts[:cut]]
            if not parts:
                continue
            n_paths += 1
            if not relay.pkg.joinpath(*parts).exists():
                old = "relay/ark_relay/" + "/".join(parts)
                hint = relay.new_place(old)
                if not hint:            # moved without an alias (added after 10-11): same name
                    same = list(relay.pkg.rglob(parts[-1]))
                    hint = str(same[0].relative_to(root)) if len(same) == 1 else ""
                bad.add(f"{rel}:{i}", f"ark_relay/{'/'.join(parts)} is not in the new relay"
                        + (f" (now {hint})" if hint else ""))
    return n_imports, n_paths


HOOK_EVENT = re.compile(r"\b(?:PreToolUse|PostToolUse|UserPromptSubmit|Stop|SubagentStop|"
                        r"SessionStart|SessionEnd|PreCompact|Notification)\b")
READS_STDIN = re.compile(r"json\.loads?\(\s*sys\.stdin|sys\.stdin\.read")
PY_NAME = re.compile(r"([A-Za-z0-9_-]+)\.py\b")
MOD_CALL = re.compile(r"""mod\(\s*['"]([A-Za-z0-9_-]+)['"]""")
HOOK_PATH = re.compile(r"~/\.claude/hooks/([A-Za-z0-9_-]+\.py)\b")
# A paused-list reason built on facts: a measured time, or a dated entry of the two error ledgers
# (BOARD/被指出.txt, BOARD/报错台账.txt). A quote of the user, dated or not, is neither.
MEASURED_MS = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s*(?:ms|毫秒)(?![A-Za-z])")
LEDGER_DATE = re.compile(r"(?:被指出|报错台账)(?:\.txt)?[^；;。\n]{0,60}?(?<!\d)\d{2}-\d{2}(?![\d-])")
# Entries paused before 10-11 that nobody has measured yet: named here so the debt shows as a
# note on every run instead of turning the check red; take a name out once its entry says ms.
PAUSED_UNMEASURED = {"admit-guard", "decision-guard", "excuse-guard", "nitpick-guard", "visible-guard"}


def _commands(node) -> "list[str]":
    """Every "command" string anywhere in a settings / registry structure."""
    if isinstance(node, dict):
        out = [node["command"]] if isinstance(node.get("command"), str) else []
        return out + [c for v in node.values() for c in _commands(v)]
    if isinstance(node, list):
        return [c for v in node for c in _commands(v)]
    return []


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def code_only(src: str) -> str:
    """The source without comments and docstrings: "replaces caught-guard.py" in prose is
    not a hook running another one."""
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
                for k in range(body[0].lineno - 1, body[0].end_lineno):
                    lines[k] = ""
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                r, c = tok.start
                lines[r - 1] = lines[r - 1][:c]
    except (SyntaxError, tokenize.TokenError, IndexError):
        pass
    return "\n".join(lines)


def check_hooks(hooks: Path, settings: Path, docs, bad: Finding) -> str:
    """Every hook file that says it runs is registered ('' = no hooks folder here).

    10-06's alert-inbox-hook.py lost its registration in the 10-10 slimming and was dead for
    four days. Registered = named in a command of settings.json or of hooks/registry.json
    (dispatch.py runs those), or run by a registered hook (resource-guard.py runs disk-guard,
    reply-gate.py runs brief-guard: a file name or mod('name') in its code - not in a
    comment or docstring - followed through). Paused on purpose = named in a list of {event, hook} entries kept as a .json
    in the hooks folder. A hook file = a .py there (not a _helper) that reads the hook
    payload from stdin and names a hook event. A rule file naming ~/.claude/hooks/<x>.py
    that is not there fails too."""
    if not hooks.is_dir():
        return ""
    names = {f.stem for f in hooks.glob("*.py")}
    cmds = _commands(_json(settings) or {}) + _commands(_json(hooks / "registry.json") or {})
    registered = {m.group(1) for c in cmds for m in PY_NAME.finditer(c)}
    paused, entries = set(), []
    for j in sorted(hooks.glob("*.json")):
        data = _json(j) if j.name != "registry.json" else None
        if isinstance(data, list) and data and all(isinstance(e, dict) and "hook" in e for e in data):
            paused |= {m.group(1) for c in _commands(data) for m in PY_NAME.finditer(c)}
            entries += [(j, e) for e in data]
    running, todo = set(), [n for n in registered if n in names]
    while todo:
        n = todo.pop()
        if n in running:
            continue
        running.add(n)
        src = code_only((hooks / f"{n}.py").read_text(encoding="utf-8", errors="replace"))
        todo += [m.group(1) for r in (PY_NAME, MOD_CALL) for m in r.finditer(src)
                 if m.group(1) in names and m.group(1) not in running]
    unmeasured = set()
    for j, e in entries:
        stems = {m.group(1) for c in _commands(e) for m in PY_NAME.finditer(c)} - {"soft", "dispatch"}
        if not stems or stems & running:
            continue
        reason = e.get("paused") if isinstance(e.get("paused"), str) else ""
        if MEASURED_MS.search(reason) or LEDGER_DATE.search(reason):
            continue
        if stems <= PAUSED_UNMEASURED:
            unmeasured |= stems
            continue
        bad.add(f"{str(j).replace(str(HOME), '~')}: {', '.join(sorted(stems))}",
                "paused-list reason has no measured time (N ms) and no dated entry of "
                "被指出.txt / 报错台账.txt - a quote of the user is not a reason: "
                + (repr(reason[:60]) if reason else "no reason at all"))
    hook_files = []
    for f in sorted(hooks.glob("*.py")):
        src = f.read_text(encoding="utf-8", errors="replace")
        if not f.name.startswith("_") and READS_STDIN.search(src) and HOOK_EVENT.search(src[:4000]):
            hook_files.append(f)
    stems = {f.stem for f in hook_files}
    for f in hook_files:
        if f.stem not in running and f.stem not in paused:
            bad.add(str(f).replace(str(HOME), "~"),
                    "a hook file that is not registered (settings.json, hooks/registry.json), "
                    "not run by a registered hook and not in a paused list")
    for path, shown in docs:
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in HOOK_PATH.finditer(line):
                if not (hooks / m.group(1)).exists():
                    bad.add(f"{shown}:{i}", f"~/.claude/hooks/{m.group(1)} does not exist")
    return (f"{len(stems)} hook files: {len(stems & running)} registered or run by one, "
            f"{len(stems & paused - running)} paused"
            + (f" ({len(unmeasured)} paused before 10-11 still unmeasured: {', '.join(sorted(unmeasured))})"
               if unmeasured else ""))


def check_toplevel(root: Path, bad: Finding) -> str:
    """The repository's main worktree against origin/main ('' = nothing to compare)."""
    r = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"],
                       capture_output=True, text=True, check=False)
    if r.returncode or not r.stdout.startswith("worktree "):
        return ""
    top = r.stdout.splitlines()[0][len("worktree "):]
    branch = next((ln.split("/")[-1] for ln in r.stdout.split("\n\n")[0].splitlines()
                   if ln.startswith("branch ")), "(detached)")
    behind = subprocess.run(["git", "-C", top, "rev-list", "--count", "HEAD..origin/main"],
                            capture_output=True, text=True, check=False)
    if behind.returncode:
        return ""
    n = int(behind.stdout.strip() or 0)
    moved = ""
    if n:
        # Behind is the normal state right after anyone's push from a worktree, so being
        # behind alone blocked the next session's push or deploy (10-11 22:4x and 23:03,
        # push-lint-guard). Bring it along the way ff-toplevel.sh does - a fast-forward on
        # a clean main only, never a stash or reset (~/Claude/CLAUDE.md safety rule 4) -
        # and report only what that leaves behind: a dirty tree, another branch, a refusal.
        ff = subprocess.run([str(Path(__file__).resolve().parent / "ff-toplevel.sh"), top],
                            capture_output=True, text=True, check=False)
        left = subprocess.run(["git", "-C", top, "rev-list", "--count", "HEAD..origin/main"],
                              capture_output=True, text=True, check=False)
        if not left.returncode and int(left.stdout.strip() or 0) == 0:
            moved, n = f", fast-forwarded {n} commits", 0
        else:
            why = (ff.stdout.strip().splitlines() or ["ff-toplevel.sh said nothing"])[0].strip()
            fix = (f"git -C {top} merge --ff-only origin/main (when it has no uncommitted changes)"
                   if branch == "main" else f"it is on {branch}, not main")
            bad.add(top, f"the shared top-level checkout is {n} commits behind origin/main: {fix}; "
                         f"not brought along: {why}")
    return f"top-level checkout ({branch}) {'behind' if n else 'at'} origin/main{moved}"


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[3]))
    ap.add_argument("--doc", action="append", help="rule file to read (repeatable; "
                    "replaces the defaults)")
    ap.add_argument("--no-git", action="store_true", help="walk the tree instead of git "
                    "ls-files, and skip the top-level checkout check")
    ap.add_argument("--hooks", default=str(HOME / ".claude/hooks"),
                    help="hooks folder ('none' skips the hook check)")
    ap.add_argument("--settings", default=str(HOME / ".claude/settings.json"))
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    relay = Relay(root)
    files = tracked(root, not a.no_git)
    docs, notes = expand_docs(root, a.doc or DEFAULT_DOCS)
    bad = Finding()
    n_doc = check_docs(root, docs, relay, files, bad)
    self_rel = "scripts/mac/lib/tool_refs.py"
    tools = sorted(f for f in files if f.startswith("scripts/") and f.endswith(TOOL_EXT)
                   and f != self_rel and (root / f).is_file())
    n_imp = n_pkg = 0
    for rel in tools:
        i, p = check_tool(root, rel, relay, bad)
        n_imp += i
        n_pkg += p
    top = "" if a.no_git else check_toplevel(root, bad)
    hooks = "" if a.hooks == "none" else check_hooks(Path(a.hooks), Path(a.settings), docs, bad)
    for n in notes:
        print(f"  note: {n}")
    for where, why in bad:
        print(f"{where}: {why}")
    summary = (f"{n_doc} script paths in {len(docs)} rule files; {len(tools)} tools with "
               f"{n_imp} ark_relay imports and {n_pkg} ark_relay paths"
               + (f"; {top}" if top else "") + (f"; {hooks}" if hooks else ""))
    if bad:
        print(f"{len(bad)} problems ({summary})")
        return 1
    print(f"all point at the new relay ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
