#!/usr/bin/env python3
"""Chinese in comments and docstrings: a ledger that may only shrink.

The rule the user set on 2026-09-08 is 「除了 readme 之外的部分都用英文，因为是你看的
不是人看的」. `docs/` was converted the same day; the code was not, and 1700-odd
lines of Chinese comments and docstrings remain under relay/ and scripts/.
Converting them all in one sweep would churn every file at once, so this does
what the untested-function ledger does instead: it records what is there today
and refuses to let it grow. Touch a file, translate its comments, the number
goes down and can never come back up.

Zero is not the target and never will be: quoting the user's own words keeps the
Chinese original on purpose - translating his words destroys the evidence. What
is forbidden is *writing new* Chinese narration.

Only comments and docstrings are counted. String literals are untouched: the
notification text, the phone page and the Chinese patterns that match upstream
logs are program data, and are supposed to be Chinese.

    python3 scripts/mac/lib/zh_ratchet.py                 # check
    python3 scripts/mac/lib/zh_ratchet.py --update        # rewrite the ledger
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[3]
LEDGER = ROOT / "relay" / "tests" / "zh-baseline.txt"
ROOTS = ("relay", "scripts")
HAN = re.compile(r"[一-鿿]")
ASCII_WORD = re.compile(r"[A-Za-z]")


def narration(line: str) -> bool:
    """Is this line Chinese narration, rather than English prose that quotes Chinese?

    English prose has to be able to name things: 「已停一切」, 鸣潮, a file called
    中继关机开关.bat. Counting every line that contains a Chinese character would tax
    correct English for quoting - and quoting the user's own words is required, since
    translating them destroys the evidence. A line where Chinese outweighs the Latin
    letters is narration; a line of English carrying a quoted term is not.
    """
    return len(HAN.findall(line)) > len(ASCII_WORD.findall(line))


def count(path: pathlib.Path) -> int:
    """Lines of comment or docstring that contain a Chinese character."""
    src = path.read_text(encoding="utf-8")
    n = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and narration(tok.string):
                n += 1
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return n
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                n += sum(1 for line in doc.splitlines() if narration(line))
    return n


def count_shell(path: pathlib.Path) -> int:
    """Same, for shell scripts: comment lines only, no docstrings to consider.

    A `#` inside a string would be counted as a comment here. That costs nothing:
    the ledger only has to be consistent with itself for the ratchet to work.
    """
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines()
               if line.lstrip().startswith("#") and narration(line))


def survey() -> dict[str, int]:
    out = {}
    for r in ROOTS:
        for p in sorted((ROOT / r).rglob("*.py")):
            c = count(p)
            if c:
                out[str(p.relative_to(ROOT))] = c
        for p in sorted((ROOT / r).rglob("*.sh")):
            c = count_shell(p)
            if c:
                out[str(p.relative_to(ROOT))] = c
    return out


def read_ledger() -> dict[str, int]:
    if not LEDGER.is_file():
        return {}
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, n = line.rpartition(" ")
        out[name.strip()] = int(n)
    return out


def write_ledger(now: dict[str, int]) -> None:
    head = ["# Lines of Chinese comment/docstring per file. **This may only shrink.**",
            "# Why, and what stays Chinese on purpose: scripts/mac/lib/zh_ratchet.py",
            f"# total {sum(now.values())} lines in {len(now)} files",
            "# regenerate: python3 scripts/mac/lib/zh_ratchet.py --update"]
    body = [f"{k} {v}" for k, v in sorted(now.items())]
    LEDGER.write_text("\n".join(head + body) + "\n", encoding="utf-8")


def main() -> int:
    now = survey()
    if "--update" in sys.argv:
        write_ledger(now)
        print(f"ledger rewritten: {sum(now.values())} lines in {len(now)} files")
        return 0
    was = read_ledger()
    grew = [(f, was.get(f, 0), n) for f, n in now.items() if n > was.get(f, 0)]
    if grew:
        for f, a, b in grew:
            print(f"✗ {f}: Chinese comment lines {a} -> {b}")
        print("Comments and docstrings are English (the user, 2026-09-08). Quoting his own "
              "words keeps the Chinese original; narration does not.")
        print("A file that was legitimately split: run --update after checking the total "
              "did not rise.")
        return 1
    shrank = sum(was.get(f, 0) - n for f, n in now.items())
    gone = sum(v for f, v in was.items() if f not in now)
    print(f"✓ Chinese in comments: {sum(now.values())} lines in {len(now)} files"
          + (f" (down {shrank + gone} since the ledger; run --update)" if shrank + gone else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
