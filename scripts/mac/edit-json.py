#!/usr/bin/env python3
"""
Safely edit a remote JSON config: locate -> replace -> validate -> structural diff.

Never regex-replace across a whole config file. Scope the replacement to the
enclosing object, then prove that ONLY the intended keys changed.

Usage:
    python3 edit-json.py before.json after.json      # just show the structural diff
"""
import json
import sys


def scope(raw: str, key: str) -> tuple[int, int]:
    """Return (start, end) of the object that immediately follows `"key"`."""
    i = raw.index('{', raw.index(f'"{key}"'))
    depth = 0
    for j in range(i, len(raw)):
        if raw[j] == '{':
            depth += 1
        elif raw[j] == '}':
            depth -= 1
            if depth == 0:
                return i, j + 1
    raise ValueError(f'unbalanced braces after "{key}"')


def replace_in(raw: str, key: str, old: str, new: str, expect: int = 1) -> str:  # deadcode: allow —— 给临时脚本用的库函数
    """Replace `old` with `new`, but only inside the object under `key`."""
    i, e = scope(raw, key)
    blk = raw[i:e]
    n = blk.count(old)
    if n != expect:
        raise AssertionError(f'expected {expect} hit(s) for {old!r} in "{key}", got {n}')
    out = raw[:i] + blk.replace(old, new) + raw[e:]
    json.loads(out)  # must stay valid
    return out


def flatten(obj, path: str = '') -> dict:
    """Flatten to {json-path: scalar} so two configs can be compared key by key."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f'{path}/{k}'))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            out.update(flatten(v, f'{path}[{idx}]'))
    else:
        out[path] = obj
    return out


def diff(before: str, after: str) -> int:
    a, b = flatten(json.loads(before)), flatten(json.loads(after))
    added, removed = set(b) - set(a), set(a) - set(b)
    changed = {k: (a[k], b[k]) for k in a.keys() & b.keys() if a[k] != b[k]}
    print(f'keys {len(a)} -> {len(b)} | +{len(added)} -{len(removed)} ~{len(changed)}')
    for k, (x, y) in sorted(changed.items()):
        print(f'  ~ {k}\n      {x!r} -> {y!r}')
    for k in sorted(removed):
        print(f'  - {k}')
    for k in sorted(added):
        print(f'  + {k}')
    # Anything other than the intended edits should make you stop and look.
    return len(added) + len(removed)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding='utf-8') as f1, open(sys.argv[2], encoding='utf-8') as f2:
        sys.exit(1 if diff(f1.read(), f2.read()) else 0)
