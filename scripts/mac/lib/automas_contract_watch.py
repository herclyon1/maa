"""Does the newest AUTO-MAS release (betas included) still keep every setting the relay reads?

AUTO-MAS installs its own updates on the game machine from the beta channel (the relay's
pre-update asks its backend, boot_stages._stage_preupdate). v5.7.0-beta.3, published
2026-10-13 07:23 UTC and installed there 10-14 08:46 Beijing, moved the MAA user's stage items
from Info to a new Stage group (relay/ark_relay/core/masuser.py); the relay read nothing for
13 hours. This tool looks at a release before the machine installs it, from this Mac:

1. asks GitHub for the newest release of AUTO-MAS-Project/AUTO-MAS, prereleases included
   (GET /repos/{repo}/releases, no token; `gh api` when it is installed and logged in);
2. fetches app/models/config.py at that tag (raw.githubusercontent.com) and reads every
   ConfigItem("Group", "Key", ..., legacy_group=..., legacy_name=...) per config class, with
   the module-level helpers a class calls with itself (init_maaend_task_config(self)) and
   the items of its base class;
3. compares them with the relay's list (relay/ark_relay/core/mascontract.py CONTRACT) and
   prints every listed item the release no longer defines where the relay looks, and items
   that moved (the release defines the key elsewhere with legacy_group / legacy_name
   pointing at the old place).

An item counts as kept when the class defines Group.Key, or - for a key masuser.MOVED knows -
Info.Key (the relay reads both, older AUTO-MAS kept them in Info). A ConfigItem whose group
or key is not a string literal (MaaPlanConfig's per-day rows, built in a loop) is kept as a
wildcard and matches any group / key, an f-string key as a pattern (MaaEndUserConfig's
f"If{task}" -> "If*"): such an item cannot be told apart from source alone.

    python3 scripts/mac/lib/automas_contract_watch.py [--tag vX.Y.Z] [--file config.py]
Exit 0 = nothing the relay reads changed, 2 = something did (printed), 3 = GitHub could not
be read (or the file had no config classes). Output is for us; nothing is scheduled to run
it (the acceptance session decides that).
"""
from __future__ import annotations

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
CONFIG_PATH = "app/models/config.py"
_RELAY = Path(__file__).resolve().parents[3] / "relay"
# Seconds per GitHub request. Measured 10-14 22:5x from this Mac: the whole run (release list
# via gh + config.py from raw.githubusercontent.com) took 0.74 s, the config.py fetch alone
# 0.07 s; 30 s leaves room for a slow network without hanging a session.
_TIMEOUT = 30

_CLASS = re.compile(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", re.M)
_DEF = re.compile(r"^def\s+(\w+)\s*\(", re.M)
# A line at column 0 that is not blank, a comment or the close of a wrapped signature.
_TOP_LEVEL = re.compile(r"^(?=[^\s#)\]])", re.M)
_CALL = re.compile(r"\bConfigItem\(")
_STR = re.compile(r"""\s*(f?)(?:"([^"\\]*)"|'([^'\\]*)')\s*$""", re.S)
_KW = re.compile(r"""\b(legacy_group|legacy_name)\s*=\s*["']([^"']+)["']""")
WILD = "*"


# ------------------------------------------------------------------ upstream source

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


def parse(text: str) -> dict[str, dict]:
    """{class name: {(group, key): legacy or None}} for every class in an AUTO-MAS config.py,
    with the items of the helpers it calls with itself and of its base class."""
    helpers = _helpers(text)
    marks = list(_CLASS.finditer(text))
    own: dict[str, dict] = {}
    bases: dict[str, str] = {}
    for i, cm in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        # A class body ends at the next top-level line (a module-level def or constant).
        nxt = _TOP_LEVEL.search(text, text.find("\n", cm.end()) + 1)
        if nxt and nxt.start() < end:
            end = nxt.start()
        body = text[cm.end():end]
        found = _items(body)
        for name in dict.fromkeys(re.findall(r"\b(\w+)\(self\)", body)):
            for k, v in _items(helpers.get(name, "")).items():
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


# ------------------------------------------------------------------ the comparison

def _defines(items: dict, group: str, key: str) -> bool:
    return any(fnmatch.fnmatchcase(group, g) and fnmatch.fnmatchcase(key, k) for g, k in items)


def compare(classes: dict[str, dict], contract, moved: "dict[str, str] | None" = None) -> list[str]:
    """One plain line per listed item `classes` (parse()) no longer keeps where the relay
    reads it; [] when every item is kept. `moved` is masuser.MOVED: those keys are read from
    their new group or from Info."""
    moved = moved or {}
    out = []
    for it in contract:
        items = classes.get(it.owner)
        if items is None:
            out.append(f"{it.owner} {it.group}.{it.key}: class {it.owner} is gone (feature {it.use}; read by {it.source})")
            continue
        if _defines(items, it.group, it.key):
            continue
        if it.key in moved and _defines(items, "Info", it.key):
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
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _http(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ark-relay-contract-watch",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def newest_tag() -> str:
    """The newest release's tag, prereleases included (the list is newest first)."""
    path = f"repos/{REPO}/releases?per_page=10"
    raw = _gh(path) or _http(f"https://api.github.com/{path}")
    rels = [r for r in json.loads(raw) if isinstance(r, dict) and not r.get("draft")]
    if not rels:
        raise ValueError("no releases listed")
    rels.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    return str(rels[0]["tag_name"])


def fetch_config(tag: str) -> str:
    return _http(f"https://raw.githubusercontent.com/{REPO}/{tag}/{CONFIG_PATH}")


def _relay_contract():
    sys.path.insert(0, str(_RELAY))
    from ark_relay.core import masuser, mascontract  # noqa: PLC0415
    return mascontract.CONTRACT, masuser.MOVED


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
    try:
        if file:
            text, tag = Path(file).read_text(encoding="utf-8"), tag or file
        else:
            tag = tag or newest_tag()
            text = fetch_config(tag)
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        print(f"GitHub could not be read: {type(exc).__name__}: {exc}")
        return 3
    classes = parse(text)
    if not classes:
        print(f"{tag}: {CONFIG_PATH} has no config classes - not the file expected")
        return 3
    contract, moved = _relay_contract()
    gaps = compare(classes, contract, moved)
    if not gaps:
        print(f"{tag}: all {len(contract)} AUTO-MAS settings the relay reads are still there")
        return 0
    print(f"{tag}: {len(gaps)} of {len(contract)} AUTO-MAS settings the relay reads changed:")
    for g in gaps:
        print(f"  - {g}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
