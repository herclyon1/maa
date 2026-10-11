#!/usr/bin/env python3
"""New timing / retry / threshold numbers must say where they come from.

The user, 10-11 19:14, after a day of numbers we made up ourselves - the flat 120 s
post-deploy wait (22c925b8, never measured), the "split past 800 lines" rule (dropped the
same day) - said 「下次是一百二十秒」: once picked, such a number stays forever. The fix
for the 120 s (c76d94a5) is the model: 22 s, with the measurement written above it.

So every line *added* since the branch left origin/main, in *.py and *.sh under scripts/
and relay/ (relay/tests/ excluded), that sets one of these to a literal number > 1:

    sleep N, time.sleep(N), timeout=N, --timeout N, timeout N cmd,
    NAME_S = N, NAME_S="${NAME_S:-N}", *_TIMEOUT*, *_RETRIES*, *_LIMIT*, *_MAX*, ...

must have, on that line or in the 6 lines above it, a comment naming its source: the word
"measured" (or 实测), a documentation URL, or the user's own words in 「...」 together
with the time he said them (MM-DD or HH:MM). Old lines are never judged.

    python3 scripts/mac/lib/num_source.py                  # vs merge-base with origin/main
    python3 scripts/mac/lib/num_source.py --root DIR --base REV
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
DIRS = ("scripts", "relay")
EXCLUDE_DIRS = ("relay/tests/",)
# The rule text itself names every pattern it looks for.
EXCLUDE_FILES = ("scripts/mac/lint-repo.sh", "scripts/mac/lib/num_source.py")
SUFFIXES = (".py", ".sh")
WINDOW = 6

N = r"(\d+(?:\.\d+)?)(?![\w.])"
NAME_HINT = re.compile(
    r"(?:^|_)(?:TIMEOUT|RETRIES|RETRY|TRIES|ATTEMPTS|LIMIT|MAX|THRESHOLD|DELAY|INTERVAL|WAIT)(?:_|$)"
    r"|_(?:S|SEC|SECS|SECONDS|MS|MIN|MINS|MINUTES|HOURS)$")
RULES = (
    ("sleep N", re.compile(r"\bsleep\s+" + N)),
    ("sleep(N)", re.compile(r"\bsleep\(\s*" + N)),
    ("timeout=N", re.compile(r"(?i)\b\w*timeout\s*=\s*" + N)),
    ("--timeout N", re.compile(r"--[\w-]*(?:timeout|max-time)[\s=]+" + N)),
    ("timeout N cmd", re.compile(r"\btimeout\s+" + N)),
)
ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]*)\s*(?::\s*[A-Za-z_][\w\[\], .]*)?=\s*['\"]?(?:\$\{\w+:[-=])?" + N)
DEFAULT = re.compile(r"\$\{([A-Z][A-Z0-9_]*):[-=]" + N)
COMMENT = re.compile(r"(?:^|\s)#")

MEASURED = re.compile(r"(?i)\bmeasured\b|实测")
URL = re.compile(r"https?://")
QUOTE = re.compile(r"「[^」]+」")
WHEN = re.compile(r"\b\d{1,2}-\d{1,2}\b|\b\d{1,2}:\d{2}\b")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def split_comment(line: str) -> "tuple[str, str]":
    """(code, comment) - a `#` at the start or after whitespace opens the comment."""
    m = COMMENT.search(line)
    return (line, "") if m is None else (line[:m.start()], line[m.start():])


def offence(line: str) -> "str | None":
    """The rule an added line breaks with a literal > 1, or None."""
    code, _ = split_comment(line)
    if not code.strip():
        return None
    for rule, rx in RULES:
        for m in rx.finditer(code):
            if float(m.group(1)) > 1:
                return f"{rule}, N = {m.group(1)}"
    for rx in (ASSIGN, DEFAULT):
        for m in rx.finditer(code):
            if NAME_HINT.search(m.group(1)) and float(m.group(2)) > 1:
                return f"{m.group(1)} = {m.group(2)}"
    return None


def sourced(lines: "list[str]", idx: int) -> bool:
    """Does a comment on line idx (0-based) or the WINDOW lines above it name a source?"""
    notes = [split_comment(x)[1] for x in lines[max(0, idx - WINDOW):idx + 1]]
    if any(MEASURED.search(c) or URL.search(c) for c in notes):
        return True
    # His words carry their time on the same line or the one next to it. A quote and a
    # time further apart are two unrelated things: 22c925b8's flat 120 s sat under a
    # comment holding an incident time and a quoted relay log line, and nothing of his.
    return any(QUOTE.search(c) and any(WHEN.search(x) for x in notes[max(0, i - 1):i + 2])
               for i, c in enumerate(notes))


def git(root: pathlib.Path, *args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false", *args],
                          capture_output=True, text=True)


def judged(path: str) -> bool:
    return (path.endswith(SUFFIXES) and path not in EXCLUDE_FILES
            and not path.startswith(EXCLUDE_DIRS))


def added_lines(root: pathlib.Path, base: str) -> "dict[str, set[int]]":
    """{path: new-side line numbers added since base}, working tree and untracked files included."""
    out = git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, "--", *DIRS).stdout
    added: "dict[str, set[int]]" = {}
    path = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            if path is not None and not judged(path):
                path = None
        elif path and line.startswith("@@"):
            m = HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                added.setdefault(path, set()).update(range(start, start + count))
    for path in git(root, "ls-files", "--others", "--exclude-standard", "--", *DIRS).stdout.splitlines():
        if judged(path):
            n = len((root / path).read_text(encoding="utf-8", errors="replace").splitlines())
            added[path] = set(range(1, n + 1))
    return added


def scan(root: pathlib.Path, base: str) -> "list[tuple[str, int, str, str]]":
    """[(path, line, code, rule)] for each added number without a source."""
    found = []
    for path, nums in sorted(added_lines(root, base).items()):
        f = root / path
        if not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for n in sorted(nums):
            if n > len(lines) or lines[n - 1].lstrip().startswith("#"):
                continue
            rule = offence(lines[n - 1])
            if rule and not sourced(lines, n - 1):
                found.append((path, n, lines[n - 1].strip(), rule))
    return found


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--base", help="revision to diff against (default: merge-base with origin/main)")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    base = a.base
    if base is None:
        r = git(root, "merge-base", "HEAD", "origin/main")
        if r.returncode != 0:
            print("no origin/main to diff against - skipped")
            return 0
        base = r.stdout.strip()
    found = scan(root, base)
    for path, n, code, rule in found:
        print(f"{path}:{n}: {code}")
        print(f"    {rule}: timing/retry/threshold number without a source")
    if found:
        print(f"{len(found)} new number(s) without a source - within the {WINDOW} lines above, add a"
              " comment with Measured: ... (or 实测), a doc URL, or his words 「...」 with MM-DD / HH:MM")
        return 1
    print(f"every new timing/retry/threshold number since {base[:8]} names its source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
