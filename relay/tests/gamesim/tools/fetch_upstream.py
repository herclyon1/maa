#!/usr/bin/env python3
"""Fetch an upstream tool's source by tag into relay/tests/gamesim/upstream/, or check a copy.

The game-layer tests (relay/tests/test_gl_*.py) read the upstream source of the version
installed on the game PC instead of stand-ins written from memory (gamesim design, rule 2:
upstream is run, never imitated). This tool is the only writer of those copies; nobody
edits them by hand, and `check` re-fetches a copy and fails on any difference.

Only the files our code touches are copied, plus what they import from the same repository
(one level), plus the files defining their base classes (transitively), so a method can be
looked up through its bases the way Python and okww_overlay._method_sha do. The OK-WW
tree is ~76 files with the whole import closure (every character class through
CharFactory); this keeps it to the ~25 a contract check reads.

Each file is stored verbatim under its repository path with `.txt` appended, so the
repository's own Python linters (pyflakes, ruff, deadcode, zh_ratchet) never see
upstream code. `materialize()` writes a copy back out under the real `.py` names.
SOURCE.txt records the repository URL, tag, commit and the sha256 of every file.

    fetch_upstream.py fetch okww v3.7.4     # (re)write relay/tests/gamesim/upstream/okww-v3.7.4/
    fetch_upstream.py check okww v3.7.4     # re-fetch and compare; exit 1 on any difference
    fetch_upstream.py check                 # every copy present
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM = Path(__file__).resolve().parents[1] / "upstream"
SUFFIX = ".txt"
SOURCE = "SOURCE.txt"
# Network calls: GitHub answered a raw file and an ls-remote in under 2 s from this Mac
# (measured 2026-10-13); a minute leaves room for a slow link without hanging forever.
NET_TIMEOUT = 60

# tool -> where it lives, how its copy is named, the files we start from and the top-level
# names whose imports stay inside the repository.
TOOLS = {
    "okww": {
        "repo": "ok-oldking/ok-wuthering-waves",
        "dir": "okww-{tag}",
        "roots": ("src", "config"),
        # The modules ark_overrides.tasks.py imports its classes from (its `from src...`
        # lines), and the two files it cites for the game's launch argument (its closing
        # comment: config.py:203 -> src/game_launcher.py).
        "seeds": (
            "src/task/BaseCombatTask.py",
            "src/task/BaseWWTask.py",
            "src/task/DailyTask.py",
            "src/task/FarmEchoTask.py",
            "src/task/ForgeryTask.py",
            "src/task/NightmareNestTask.py",
            "src/task/SimulationTask.py",
            "src/task/TacetTask.py",
            "config.py",
            "src/game_launcher.py",
        ),
    },
}


def copy_dir(tool: str, tag: str) -> Path:
    return UPSTREAM / TOOLS[tool]["dir"].format(tag=tag, ver=tag.lstrip("v"))


# ── reading a copy ──────────────────────────────────────────────────────────────
def read_manifest(copy: Path) -> dict:
    """SOURCE.txt as {"repo", "tag", "commit", "absent": [paths], "files": {path: sha256}}."""
    out: dict = {"absent": [], "files": {}}
    for line in (copy / SOURCE).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        rest = rest.strip()
        if key in ("repo", "tag", "commit"):
            out[key] = rest
        elif key == "absent":
            out["absent"].append(rest)
        elif len(key) == 64:
            out["files"][rest] = key
    return out


def read_files(copy: Path) -> dict[str, bytes]:
    """{repository path: bytes} for every file the manifest lists."""
    return {p: (copy / (p + SUFFIX)).read_bytes() for p in read_manifest(copy)["files"]}


def materialize(copy: Path, dest: Path) -> Path:
    """Write the copy under dest with the real file names (dest/<repository path>)."""
    for path, data in read_files(copy).items():
        out = dest / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return dest


# ── fetching ────────────────────────────────────────────────────────────────────
def tag_commit(repo: str, tag: str) -> str:
    """The commit a tag points at (the peeled ^{} line for an annotated tag)."""
    out = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}",
                          f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                         capture_output=True, text=True, timeout=NET_TIMEOUT, check=True).stdout
    refs = dict(reversed(line.split("\t")) for line in out.splitlines() if "\t" in line)
    sha = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not sha:
        raise SystemExit(f"tag {tag} not found in {repo}")
    return sha


def raw(repo: str, commit: str, path: str) -> "bytes | None":
    """One file at a commit; None when the repository has no such file there."""
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=NET_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _module_paths(module: str) -> list[str]:
    """Candidate files for a dotted module name: a/b.py, then a/b/__init__.py."""
    base = module.replace(".", "/")
    return [base + ".py", base + "/__init__.py"]


def _imports(tree: ast.AST, roots: tuple) -> "dict[str, str]":
    """{imported name or module: module} for in-repository imports anywhere in the file."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in roots:
                    out[(a.asname or a.name).split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] in roots:
                for a in node.names:
                    out[a.asname or a.name] = f"{node.module}.{a.name}"
                out.setdefault(node.module, node.module)
    return out


def collect(tool: str, commit: str) -> "tuple[dict[str, bytes], list[str]]":
    """({path: bytes}, absent seeds): the seeds, their in-repo imports, and base-class files."""
    spec = TOOLS[tool]
    repo, roots = spec["repo"], spec["roots"]
    files: dict[str, bytes] = {}
    missing: set[str] = set()

    def get(path: str) -> "bytes | None":
        if path in files:
            return files[path]
        if path in missing:
            return None
        data = raw(repo, commit, path)
        if data is None:
            missing.add(path)
        else:
            files[path] = data
        return data

    def resolve(module: str) -> "str | None":
        """The file a dotted name lives in: the longest prefix that is a module."""
        parts = module.split(".")
        for i in range(len(parts), 0, -1):
            for cand in _module_paths(".".join(parts[:i])):
                if get(cand) is not None:
                    return cand
        return None

    absent = [s for s in spec["seeds"] if get(s) is None]
    seeds = [s for s in spec["seeds"] if s in files]
    trees = {s: ast.parse(files[s].decode("utf-8")) for s in seeds}
    for s in seeds:                       # one level of imports from the seeds
        for module in set(_imports(trees[s], roots).values()):
            resolve(module)
    # Base classes, transitively: a method is looked up through them.
    todo = list(files)
    while todo:
        path = todo.pop()
        if not path.endswith(".py"):
            continue
        tree = ast.parse(files[path].decode("utf-8"))
        names = _imports(tree, roots)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for b in node.bases:
                if isinstance(b, ast.Name) and b.id in names:
                    before = set(files)
                    resolve(names[b.id])
                    todo += sorted(set(files) - before)
    # Parent packages, so a materialized copy imports like the real tree.
    for path in list(files):
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            get("/".join(parts[:i]) + "/__init__.py")
    return files, absent


def manifest_text(repo: str, tag: str, commit: str, files: dict, absent: list) -> str:
    lines = [
        "# Written by relay/tests/gamesim/tools/fetch_upstream.py; never edit by hand.",
        f"# Each file is stored verbatim as <path>{SUFFIX}; sha256 is of those bytes.",
        f"repo https://github.com/{repo}",
        f"tag {tag}",
        f"commit {commit}",
    ]
    lines += [f"absent {p}" for p in sorted(absent)]
    lines += [f"{hashlib.sha256(files[p]).hexdigest()} {p}" for p in sorted(files)]
    return "\n".join(lines) + "\n"


def fetch(tool: str, tag: str) -> Path:
    spec = TOOLS[tool]
    commit = tag_commit(spec["repo"], tag)
    files, absent = collect(tool, commit)
    copy = copy_dir(tool, tag)
    if copy.exists():
        shutil.rmtree(copy)
    for path, data in files.items():
        out = copy / (path + SUFFIX)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    (copy / SOURCE).write_text(manifest_text(spec["repo"], tag, commit, files, absent), encoding="utf-8")
    print(f"{copy.relative_to(UPSTREAM.parent)}: {len(files)} files at {tag} ({commit[:12]})"
          + (f", absent: {', '.join(absent)}" if absent else ""))
    return copy


def check(tool: str, tag: str) -> list[str]:
    """Differences between the copy on disk and a fresh fetch of the same tag ([] = identical)."""
    spec = TOOLS[tool]
    copy = copy_dir(tool, tag)
    if not (copy / SOURCE).is_file():
        return [f"{copy.name}: no copy"]
    have = read_manifest(copy)
    problems = []
    for path, sha in have["files"].items():
        f = copy / (path + SUFFIX)
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != sha:
            problems.append(f"{copy.name}/{path}: bytes on disk differ from SOURCE.txt")
    commit = tag_commit(spec["repo"], tag)
    if commit != have.get("commit"):
        problems.append(f"{copy.name}: tag {tag} now points at {commit}, copy is of {have.get('commit')}")
    files, absent = collect(tool, commit)
    want = manifest_text(spec["repo"], tag, commit, files, absent)
    if want != (copy / SOURCE).read_text(encoding="utf-8"):
        problems.append(f"{copy.name}: a fresh fetch gives a different SOURCE.txt (rerun fetch and review the diff)")
    return problems


def copies() -> "list[tuple[str, str]]":
    """(tool, tag) of every copy on disk."""
    out = []
    for d in sorted(UPSTREAM.glob("*/" + SOURCE)):
        tag = read_manifest(d.parent)["tag"]
        tool = next((t for t in TOOLS if copy_dir(t, tag) == d.parent), None)
        if tool:
            out.append((tool, tag))
    return out


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=("fetch", "check"))
    ap.add_argument("tool", nargs="?", choices=sorted(TOOLS))
    ap.add_argument("tag", nargs="?")
    a = ap.parse_args(argv)
    if a.action == "fetch":
        if not (a.tool and a.tag):
            ap.error("fetch needs a tool and a tag")
        fetch(a.tool, a.tag)
        return 0
    todo = [(a.tool, a.tag)] if a.tool and a.tag else copies()
    problems = [p for t, g in todo for p in check(t, g)]
    for p in problems:
        print(f"  ✗ {p}")
    print(f"{len(todo)} copies checked: " + ("identical to upstream" if not problems else f"{len(problems)} differences"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
