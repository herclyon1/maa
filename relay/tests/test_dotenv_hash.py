"""The relay's .env loader must not cut a value at a '#' inside quotes or inside the value.

Audit s2 F7 (2026-10-13): _load_dotenv did value.split("#")[0] on every line, so
KEY="abc#def" loaded as 'abc'. Comments still end an unquoted value at ' #'.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import __main__ as relay_main  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


env = tmpdir() / ".env"
env.write_text("\n".join([
    "# a comment line",
    'ARKT_QUOTED="https://example.invalid/hook#frag"   # trailing comment',
    "ARKT_SINGLE='p#ss word'",
    "ARKT_BARE=abc#def",
    "ARKT_COMMENTED=plain # a note",
    "ARKT_PLAIN=value",
]) + "\n", encoding="utf-8")
for k in ("ARKT_QUOTED", "ARKT_SINGLE", "ARKT_BARE", "ARKT_COMMENTED", "ARKT_PLAIN"):
    os.environ.pop(k, None)
relay_main._load_dotenv(env)

print("[a '#' inside the value survives; a ' #' comment is still dropped]")
check("double-quoted value keeps its '#'", os.environ.get("ARKT_QUOTED"), "https://example.invalid/hook#frag")
check("single-quoted value keeps '#' and space", os.environ.get("ARKT_SINGLE"), "p#ss word")
check("unquoted '#' with no space before it is part of the value", os.environ.get("ARKT_BARE"), "abc#def")
check("unquoted ' #' starts a comment", os.environ.get("ARKT_COMMENTED"), "plain")
check("plain value", os.environ.get("ARKT_PLAIN"), "value")

print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
sys.exit(1 if fails else 0)
