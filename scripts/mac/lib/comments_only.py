#!/usr/bin/env python3
"""Prove an edit touched only comments and docstrings.

Translating a comment must never change behaviour, but a careless edit inside a
triple-quoted string that is *not* a docstring - a notification template, a
regex, an upstream log line - changes what the program does with no test
necessarily catching it. So the check is mechanical: parse both versions, strip
every docstring, and compare the dumped trees. Anything else that moved shows
up as a difference.

    python3 scripts/mac/lib/comments_only.py <old-dir> <file>...

<old-dir> holds the pre-edit copies under the same relative paths.
"""
from __future__ import annotations

import ast
import pathlib
import sys


def stripped(src: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(ast.parse(ast.unparse(tree)))


def main() -> int:
    old_root = pathlib.Path(sys.argv[1])
    bad = 0
    for name in sys.argv[2:]:
        new = pathlib.Path(name)
        old = old_root / name
        if not old.is_file():
            print(f"✗ {name}: no pre-edit copy under {old_root}")
            bad += 1
            continue
        try:
            same = stripped(old.read_text(encoding="utf-8")) == stripped(new.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"✗ {name}: {exc}")
            bad += 1
            continue
        print(f"{'✓' if same else '✗'} {name}"
              + ("" if same else "  code changed, not just comments"))
        bad += not same
    print(f"{len(sys.argv) - 2} files checked, {bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
