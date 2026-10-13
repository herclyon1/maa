"""The day replay's light packs (tests/daysim/pack.py, days/<D>/pack.tar.zst) for the Windows CI.

What is pinned here:
- blanking keeps a log's length, its line count and every line's offset (the events'
  log_chunk slices are offsets into the recorded file), keeps non-chatter lines and the
  first / last lines whole, keeps a chatter line's time stamp, blanks a line stamped
  more than OLD_LINE_H before the day entirely;
- a big picture becomes zeros of the same length; a small file and a non-log stay as
  recorded;
- each committed pack is at most 5 MiB, reads with tarfile 'r:zst', lists its members in
  pack.json, and holds every corpus file its day's events name plus every install copy.
"""
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "daysim"))
sys.path.insert(0, str(HERE))
import pack  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


print("[blanking keeps every offset]")
edge = pack.KEEP_EDGE_LINES
head = [b"[2026-10-13 08:00:00.000][DBG][Px1] head %d" % i for i in range(edge)]
body = [b"[2026-10-13 09:00:00.000][DBG][Px1][Tx2] chatter chatter chatter",
        b"[2026-10-13 09:00:01.000][INF][Px1][Tx2] Tasker.Task.Succeeded",
        b"[2026-10-12 08:00:00.000][INF][Px1][Tx2] yesterday morning\r",
        b"no stamp at all"]
tail = [b"[2026-10-13 10:00:00.000][DBG][Px1] tail %d" % i for i in range(edge)]
# No final newline here: the piece after a final newline counts as one of the edge lines.
data = b"\n".join(head + body + tail)
out = pack.blank_log(data, b"2026-10-12 12:00:00")
lines = out.split(b"\n")
check("same length", len(out), len(data))
check("same line count", out.count(b"\n"), data.count(b"\n"))
check("every line keeps its offset", [len(x) for x in lines], [len(x) for x in data.split(b"\n")])
check("first lines whole", lines[:edge], head)
check("last lines whole", lines[edge + len(body):], tail)
check("chatter keeps its stamp", lines[edge].rstrip(), b"[2026-10-13 09:00:00.000][DBG]")
check("a non-chatter line stays", lines[edge + 1], body[1])
check("a line from before the cut is all spaces (CR kept)", lines[edge + 2], b" " * (len(body[2]) - 1) + b"\r")
check("an unstamped line stays", lines[edge + 3], body[3])

print("\n[what is lightened]")
big = b"x" * (pack.IMAGE_BLANK_MIN + 1)
check("a big picture becomes zeros", pack.lighten("files/D/ark/maaend/debug/on_error/a.png", big),
      (bytes(len(big)), "image zeroed"))
check("a small picture stays", pack.lighten("files/a.png", b"png")[1], "as recorded")
check("a big JSON stays", pack.lighten("derived/x/ak-posts.json", b"{}" * pack.LOG_BLANK_MIN)[1], "as recorded")

print("\n[the committed packs]")
packs = sorted(pack.DAYS.glob("*/pack.tar.zst"))
check("packs committed", [p.parent.name for p in packs], ["2026-10-06", "2026-10-13"])
for p in packs:
    day = p.parent.name
    check(f"{day}: at most 5 MiB", p.stat().st_size <= pack.MAX_BYTES, True)
    with tarfile.open(p, "r:zst") as tf:
        names = tf.getnames()
        index = json.loads(tf.extractfile("pack.json").read())
    check(f"{day}: pack.json lists every member", sorted(m["path"] for m in index["members"]),
          sorted(n for n in names if n != "pack.json"))
    refs = set()
    for ln in (pack.DAYS / day / "events.jsonl").read_text(encoding="utf-8").splitlines():
        ev = json.loads(ln)
        for ref in (ev, ev.get("json") or {}, ev.get("log") or {}):
            if isinstance(ref.get("file"), str):
                refs.add(f"{day}/{ref['file']}")
    check(f"{day}: every corpus file the events name is in the pack", sorted(refs - set(names)), [])
    inst = {f"_install/{e['path']}" for e in json.loads(pack.install.MANIFEST.read_text(encoding="utf-8"))["files"]}
    check(f"{day}: every install copy is in the pack", sorted(inst - set(names)), [])

print()
if fails:
    print(f"FAILED: {len(fails)}: {fails}")
    sys.exit(1)
print("all checks passed")
