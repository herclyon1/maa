#!/usr/bin/env python3
"""endfield_role never guesses between several bound Endfield roles.

No binding response has been recorded (fixtures/skland-endfield holds wiki and
catalog pages only), so the shape below follows docs/SKLAND-API.md line 24:
roleId and serverId sit in bindingList[].roles[]. Before 2026-10-06 the first
role was returned whatever else was bound.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import skland

FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def _apps(*roles):
    return [{"appCode": "arknights", "bindingList": [{"uid": "1"}]},
            {"appCode": "endfield", "bindingList": [{"uid": "9", "roles": list(roles)}]}]


def _role(apps):
    skland.bindings = lambda cred: apps
    try:
        return skland.endfield_role(None)
    except skland.SklandError as exc:
        return str(exc)


def main() -> int:
    a = {"roleId": "1001", "serverId": "1"}
    b = {"roleId": "2002", "serverId": "2"}
    require("one role is returned", _role(_apps(a)) == ("1001", "1"), repr(_role(_apps(a))))
    require("the same role listed twice is still one role", _role(_apps(a, dict(a))) == ("1001", "1"))
    two = _role(_apps(a, b))
    require("two roles: refused, not the first one", isinstance(two, str) and "2 个终末地角色" in two, repr(two))
    none = _role(_apps())
    require("no role: refused", isinstance(none, str) and "没找到" in none, repr(none))
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
