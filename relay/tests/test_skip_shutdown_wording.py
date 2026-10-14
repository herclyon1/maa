"""The 「下次跑完不关机」 mark is named and described one way everywhere a human reads it.

The mark is one-shot: it is spent when the next 早班/晚班 run finishes, that
shutdown occasion is skipped, the re-checks after it stay on, and the run after
that shuts down as usual (modes.skip_armed; behaviour pinned in test_shutdown.py
"[one-shot mark]"). We misread it twice because the words around it were wrong:
other names for the same mark (「今晚别关机」, 「这次别关机」, ...) and a receipt
that said 「已取消，跑完照常关机」 as if a spent mark could still be cancelled.
The user's words are kept below as data (USER_1011).

Checks:
1. No file a human reads (relay code and comments, web/, docs/, scripts/) uses
   another name for the mark. Dated audit/handover records are history and keep
   the words they were written with.
2. set_skip_shutdown's receipts, as returned by the function, name the mark;
   pulling it back always says the mark was 「还没用上」 and never a bare 「已取消」.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

RELAY = Path(__file__).resolve().parents[1]
REPO = RELAY.parent
sys.path.insert(0, str(RELAY))

from ark_relay.features.modes import modes  # noqa: E402

USER_1011 = (
    "10-11 15:25「跑完不关机是一次标记，标记下一次跑完不关机，他不是状态，跑完了哪来的取消？」",
    "10-11 15:33「你应该真的应该好好的把那个文档那个注释所有的东西都改清楚，你每次都这样。」",
    "10-11 15:34「这个显而易见就是因为文档里面注释里面写错了」",
)
NAME = "下次跑完不关机"

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


# ---------- 1. one name ----------
print("[one name for the mark in every human-read file]")
OTHER_NAMES = re.compile(r"今晚别关机|这次别关机|下一次别关机|下次不关机|下一次跑完别关机")
WEB = REPO / "web"
ROOTS = [RELAY / "ark_relay", WEB, REPO / "docs", REPO / "scripts" / "windows", REPO / "scripts" / "mac"]
TOP = [p for p in RELAY.glob("*.py")] + [RELAY / "README.md", REPO / "README.md"]
EXTS = {".py", ".js", ".html", ".css", ".md", ".bat", ".ps1", ".sh", ".txt", ".json"}
# Dated records: what was seen and said on that day, quoted as it was. Rewriting
# them would falsify the record, so they are left out.
HISTORY = re.compile(r"^docs/(SURVEY-.*|ERROR-LEDGER-.*|NEXT-BOOT|SILENT-FAILURES-AUDIT|CODE-HISTORY)\.md$")


def files():
    for root in ROOTS:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in EXTS and "node_modules" not in p.parts:
                yield p
    for p in TOP:
        if p.is_file():
            yield p


hits = []
scanned = 0
for p in files():
    rel = p.relative_to(REPO).as_posix()
    if HISTORY.match(rel) or rel == "relay/manifest.json":
        continue
    scanned += 1
    for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if OTHER_NAMES.search(line):
            hits.append(f"{rel}:{n}: {line.strip()[:80]}")
check("files scanned (sanity: the walk found the tree)", scanned > 300, True)
check("no other name for the mark", hits, [])
check("web/ is in the walk", WEB.is_dir(), True)


# ---------- 2. receipts ----------
print("\n[set_skip_shutdown receipts say which run, and that only an unspent mark is pulled back]")
d = tmpdir()
ok_on, on = modes.set_skip_shutdown(d, True)
ok_back, back = modes.set_skip_shutdown(d, False)          # armed -> pulled back
ok_none, none = modes.set_skip_shutdown(d, False)          # nothing armed (never, or spent)
check("all accepted", (ok_on, ok_back, ok_none), (True, True, True))
for label, text in (("arm", on), ("pull back", back), ("nothing to pull back", none)):
    check(f"{label}: names the mark", NAME in text, True)
    check(f"{label}: names the run (早班/晚班)", "早班/晚班" in text, True)
check("arm: says it is one-time", "只管一次" in on, True)
# App review 10-14: one sentence, not three clauses about the run after the next
check("arm: one short sentence", len(on) <= 32 and "再下一趟" not in on, True)
_ok_off, off = modes.set_debug(d, off=True)
check("debug off: says it is off, asks for nothing", off, "调试模式已关闭")
for label, text in (("pull back", back), ("nothing to pull back", none)):
    check(f"{label}: says 还没用上", "还没用上" in text, True)
    check(f"{label}: no bare 已取消", "已取消" in text, False)
    check(f"{label}: next run shuts down as usual", "照常关机" in text, True)
check("nothing to pull back: says it may already be spent", "已经用掉" in none, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
