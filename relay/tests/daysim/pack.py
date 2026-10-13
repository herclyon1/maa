#!/usr/bin/env python3
"""daysim light packs: a recorded day small enough to commit, for the Windows CI.

    python3.14 -I pack.py build 2026-10-06        # days/<D>/pack.tar.zst from the Mac corpus
    python3.14 -I pack.py unpack <dir> [D ...]    # what CI runs; then DAYSIM_CORPUS=<dir> run.py
    python3.14 -I pack.py compare 2026-10-06      # Mac: the day from its pack == from the corpus

The full corpus (~/Claude/daysim-corpus/<D>/) holds hundreds of MB of game logs; a pack
holds only the corpus files the day's seed.json and events.jsonl name, plus the
programs' own files (install.json), and makes the bulk of them cheap without moving a
byte (design.md section 5, "maafw trimmed"):

* a text log over LOG_BLANK_MIN bytes keeps its first and last KEEP_EDGE_LINES lines and
  every line that is neither DBG/TRC chatter nor stamped more than OLD_LINE_H before the
  day; a chatter line keeps its first STAMP_BYTES bytes (time stamp and level) and the
  rest becomes spaces, an old line becomes all spaces. Offsets, lengths and line counts
  stay as recorded, so the events' log_chunk slices still fit;
* an image over IMAGE_BLANK_MIN bytes (MaaEnd's on_error shots, MAA failure shots)
  becomes zeros of the same length.

A pack is only as good as `compare`: the day replayed from it must give the same
failure lines, pushes, power commands and ledger verdicts as from the full corpus.
Every member is scanned with slice.secret_hits and the public-repo identity pattern
(lint-repo item 12) before it is written; pack.json inside lists each member's
original sha256 and what was done to it. A pack over MAX_BYTES is refused.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import install  # noqa: E402

DAYS = HERE / "days"
CORPUS_ROOT = install.CORPUS_ROOT
# design.md section 5: "days/D/pack.tar.zst <=5 MB".
MAX_BYTES = 5 * 1024 * 1024
LOG_BLANK_MIN = 1 << 20
IMAGE_BLANK_MIN = 64 << 10
KEEP_EDGE_LINES = 200
# "[2026-10-13 09:53:52.735][DBG]" is 30 bytes: MAA, MaaFramework and MaaEnd stamp lines so.
STAMP_BYTES = 30
CHATTER = re.compile(rb"^\[\d{4}-\d\d-\d\d [\d:.]+\]\[(DBG|TRC)\]")
# A stamped line older than this before the day's 00:00 is blanked too (whatever its level):
# a run's verdict reads its own window, and the longest cross-midnight look back is the
# evening shift that ends after 00:00. `compare` is what proves the cut changes nothing.
OLD_LINE_H = 12
STAMP = re.compile(rb"^\[?(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")
LINT = HERE.parents[2] / "scripts" / "mac" / "lint-repo.sh"


def identity_pattern() -> "re.Pattern[bytes]":
    """lint-repo.sh item 12's pattern (other people's identity / login details never reach
    the public repo), read from there so there is one copy and this file does not hold it."""
    text = LINT.read_text(encoding="utf-8")
    m = re.search(r"公开仓库里不许有他人身份信息\"\n.*?grep -rnE '([^']+)'", text, re.S)
    if not m:
        raise SystemExit(f"cannot find item 12's pattern in {LINT}")
    return re.compile(m.group(1).encode())


def referenced(day: str, corpus: Path) -> list[str]:
    """Corpus-relative paths the day's seed and events name (world.corpus_file and
    every `file` reference), that exist in the corpus."""
    seed = json.loads((DAYS / day / "seed.json").read_text(encoding="utf-8"))
    docs = [seed] + [json.loads(ln) for ln in (DAYS / day / "events.jsonl").read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
    found: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("file"), str):
                found.add(x["file"])
            if isinstance(x.get("path"), str) and ":" in x["path"]:
                found.add(x.get("file") if isinstance(x.get("file"), str)
                          else "files/" + x["path"].replace(":", "", 1))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(docs)
    return sorted(r for r in found if (corpus / r).is_file())


def blank_log(data: bytes, before: bytes = b"") -> bytes:
    """`before`: "YYYY-MM-DD HH:MM:SS"; a line stamped earlier is blanked whatever its level."""
    lines = data.split(b"\n")
    n = len(lines)
    out = []
    for i, ln in enumerate(lines):
        old = False
        if before and (m := STAMP.match(ln)):
            old = m.group(1).replace(b"T", b" ") < before
        if i < KEEP_EDGE_LINES or i >= n - KEEP_EDGE_LINES or not (old or CHATTER.match(ln)):
            out.append(ln)
        else:
            keep = b"" if old else ln[:STAMP_BYTES]
            tail = b"\r" if ln.endswith(b"\r") else b""
            out.append(keep + b" " * (len(ln) - len(keep) - len(tail)) + tail)
    res = b"\n".join(out)
    assert len(res) == len(data) and res.count(b"\n") == data.count(b"\n")
    return res


def lighten(rel: str, data: bytes, day: str = "") -> tuple[bytes, str]:
    low = rel.lower()
    if low.endswith(IMAGE_SUFFIXES) and len(data) > IMAGE_BLANK_MIN:
        return bytes(len(data)), "image zeroed"
    if len(data) > LOG_BLANK_MIN and (low.endswith(".log") or "/debug/" in low):
        before = b""
        if day:
            cut = datetime.fromisoformat(day) - timedelta(hours=OLD_LINE_H)
            before = cut.strftime("%Y-%m-%d %H:%M:%S").encode()
        return blank_log(data, before), "chatter and old lines blanked"
    return data, "as recorded"


def build(day: str, corpus_root: Path = CORPUS_ROOT, out: "Path | None" = None) -> Path:
    corpus = corpus_root / day
    if not corpus.is_dir():
        raise SystemExit(f"no corpus at {corpus}")
    members: list[tuple[str, bytes, float]] = []
    index = []
    for rel in referenced(day, corpus):
        src = corpus / rel
        raw = src.read_bytes()
        data, how = lighten(rel, raw, day)
        members.append((f"{day}/{rel}", data, src.stat().st_mtime))
        index.append({"path": f"{day}/{rel}", "sha256": hashlib.sha256(raw).hexdigest(), "how": how})
    for ent in json.loads(install.MANIFEST.read_text(encoding="utf-8")).get("files", []):
        rel = ent["path"]
        src = install.ROOT / rel
        if not src.is_file():
            raise SystemExit(f"install copy missing: {src}")
        members.append((f"_install/{rel}", src.read_bytes(), src.stat().st_mtime))
        index.append({"path": f"_install/{rel}", "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                      "how": "as recorded"})
    import slice as sl  # noqa: PLC0415  heavy: imports scripts/mac/redact.py
    bad = [(name, h) for name, data, _ in members if (h := sl.secret_hits(data))]
    ident = identity_pattern()
    bad += [(name, ["identity"]) for name, data, _ in members if ident.search(data)]
    if bad:
        raise SystemExit(f"refused: secret / identity patterns in {bad[:5]}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        def add(name, data, mtime):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode = len(data), int(mtime), 0o644
            tf.addfile(ti, io.BytesIO(data))
        add("pack.json", json.dumps({"day": day, "members": index}, ensure_ascii=False, indent=0).encode(), 0)
        for name, data, mtime in sorted(members):
            add(name, data, mtime)
    from compression import zstd  # noqa: PLC0415  Python 3.14+
    blob = zstd.compress(buf.getvalue(), level=19)
    if len(blob) > MAX_BYTES:
        raise SystemExit(f"{day}: pack is {len(blob) / 2**20:.1f} MiB, over {MAX_BYTES / 2**20:.0f} MiB")
    out = out or DAYS / day / "pack.tar.zst"
    out.write_bytes(blob)
    print(f"{out}: {len(blob) / 2**20:.2f} MiB, {len(members)} files "
          f"({sum(1 for i in index if i['how'] != 'as recorded')} lightened)")
    return out


def unpack(dest: Path, days: list[str]) -> list[str]:
    """Each day's pack into dest/<D>/ and dest/_install/; the days unpacked."""
    done = []
    for day in days or sorted(p.parent.name for p in DAYS.glob("*/pack.tar.zst")):
        pack = DAYS / day / "pack.tar.zst"
        if not pack.exists():
            raise SystemExit(f"no pack for {day}")
        with tarfile.open(pack, "r:zst") as tf:
            tf.extractall(dest, filter="data")
        (dest / "pack.json").replace(dest / f"pack-{day}.json")
        done.append(day)
    print(f"unpacked {', '.join(done)} into {dest}")
    return done


def _facts(outputs: dict, failures: list[str]) -> dict:
    return {
        "failures": sorted(failures),
        # ntfy by count only: the phone page's hb / state / bye at a stop land a second
        # apart between two runs of the same input (measured 10-06: 06:21:32 vs :33).
        "pushes": sorted((p.get("t"), p.get("ch"), p.get("title")) for p in outputs.get("pushes") or []
                         if p.get("ch") != "ntfy"),
        "ntfy": sum(1 for p in outputs.get("pushes") or [] if p.get("ch") == "ntfy"),
        "power": sorted((p.get("t"), p.get("cmd")) for p in outputs.get("power") or []),
        "ledger": sorted((r.get("run_id"), r.get("ok"), json.dumps(r.get("failed_tasks"), ensure_ascii=False))
                         for r in outputs.get("ledger") or []),
        "sim_errors": len(outputs.get("sim_errors") or []),
    }


def _run(day: str, corpus_root: Path, out: Path) -> dict:
    env = dict(os.environ, DAYSIM_CORPUS=str(corpus_root))
    p = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "--day", day, "--strict", "--out", str(out)],
                       env=env, capture_output=True, text=True, encoding="utf-8", check=False)
    outputs = json.loads((out / day / "outputs.json").read_text(encoding="utf-8"))
    failures = [ln.strip()[5:] for ln in p.stdout.splitlines() if ln.startswith("  FAIL ")]
    return _facts(outputs, failures)


def compare(day: str) -> int:
    """The day from its pack against the day from the full corpus (Mac only)."""
    tmp = Path(tempfile.mkdtemp(prefix=f"daysim-pack-{day}-"))
    try:
        unpack(tmp / "corpus", [day])
        light = _run(day, tmp / "corpus", tmp / "out-light")
        shutil.rmtree(tmp / "corpus")
        full = _run(day, CORPUS_ROOT, tmp / "out-full")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    diff = [k for k in full if full[k] != light[k]]
    for k in diff:
        print(f"DIFF {k}:\n  full : {full[k]}\n  light: {light[k]}")
    print(f"{day}: pack {'== corpus' if not diff else 'DIFFERS from corpus'} "
          f"({len(full['pushes'])} pushes, {len(full['ledger'])} ledger rows, {len(full['failures'])} failure lines)")
    return 1 if diff else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("day")
    u = sub.add_parser("unpack")
    u.add_argument("dest", type=Path)
    u.add_argument("days", nargs="*")
    c = sub.add_parser("compare")
    c.add_argument("day")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        build(a.day)
        return 0
    if a.cmd == "unpack":
        a.dest.mkdir(parents=True, exist_ok=True)
        unpack(a.dest, a.days)
        return 0
    return compare(a.day)


if __name__ == "__main__":
    sys.exit(main())
