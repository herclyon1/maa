#!/usr/bin/env python3
"""Strip embedded screenshots out of Claude Code session transcripts.

    strip-transcript-images.py                      # survey every transcript
    strip-transcript-images.py --apply              # rewrite all but the live one
    strip-transcript-images.py FILE --apply --force # include a live session

Why: every screenshot is stored inline as base64 in the session's .jsonl. One
run of a GUI task can add a hundred megabytes, and the desktop app has to
rehydrate the whole transcript into the renderer when it restarts - which is
what leaves the window blank. Measured on a real session: 4380 lines, 97 MB,
of which 127 image blocks accounted for 85 MB. Deleting scratch .png files
does nothing for this; the copy that matters is the one inside the transcript.

Each image block is replaced by a text block recording what was there, so the
conversation still reads sensibly and the file stays valid JSONL:

    {"type":"image","source":{...}}  ->  {"type":"text","text":"[截图已清理 · 294 KB · image/jpeg]"}

Safety:
  - the file is rewritten atomically (temp file in the same directory, then
    os.replace), so an interrupted run cannot leave a half-written transcript
  - a transcript touched within --live-window seconds is treated as the live
    session and skipped unless --force is given. Rewriting a file that Claude
    Code is still appending to can lose whatever it wrote in between.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".claude" / "projects"
LIVE_WINDOW = 300  # seconds; a transcript younger than this is probably in use


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return ""


def strip_node(node, stats: dict):
    """Replace every base64 image block in the tree. Returns the new node."""
    if isinstance(node, list):
        return [strip_node(v, stats) for v in node]
    if not isinstance(node, dict):
        return node
    src = node.get("source")
    if node.get("type") == "image" and isinstance(src, dict) and src.get("data"):
        raw = len(src["data"])
        stats["images"] += 1
        stats["bytes"] += raw
        # 3/4 undoes base64 expansion, giving the original image size.
        return {"type": "text",
                "text": f"[截图已清理 · {human(raw * 3 / 4)} · "
                        f"{src.get('media_type', 'image')}]"}
    return {k: strip_node(v, stats) for k, v in node.items()}


def strip_lines(raw: str, stats: dict) -> str:
    out: list[str] = []
    for line in raw.splitlines(keepends=True):
        if not line.strip():
            out.append(line)
            continue
        stats["lines"] += 1
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # Never drop a line we cannot parse - a torn tail is still the
            # user's conversation, and guessing at it is worse than keeping it.
            stats["bad"] += 1
            out.append(line)
            continue
        out.append(json.dumps(strip_node(obj, stats), ensure_ascii=False) + "\n")
    return "".join(out)


def process(path: Path, apply: bool) -> dict:
    """Rewrite one transcript. Safe to run while the session is still writing.

    A live session appends a line per message. Reading the whole file, then
    replacing it, would silently discard anything written in between - which
    is not theoretical: a 103 MB read took long enough for eight lines to
    appear. So the read is pinned to the size observed at the start, and
    whatever arrived after that is stripped and appended just before the swap.
    The remaining race is the microseconds between the final tail read and
    os.replace.
    """
    stats = {"images": 0, "bytes": 0, "lines": 0, "bad": 0, "caught_up": 0}
    size0 = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(size0)          # exactly what existed when we started
    body = strip_lines(head.decode("utf-8", errors="replace"), stats)

    stats["before"], stats["after"] = size0, len(body.encode("utf-8"))
    if not (apply and stats["images"]):
        return stats

    # Catch up on anything appended while we were working, then swap.
    for _ in range(3):
        with path.open("rb") as f:
            f.seek(size0)
            tail = f.read()
        if not tail:
            break
        size0 += len(tail)
        stats["caught_up"] += tail.count(b"\n")
        body += strip_lines(tail.decode("utf-8", errors="replace"), stats)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)   # atomic: readers see old or new, never partial
    stats["after"] = len(body.encode("utf-8"))
    return stats


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="清理会话存档里的内嵌截图")
    ap.add_argument("files", nargs="*", type=Path,
                    help="要处理的 .jsonl；留空则扫描 ~/.claude/projects")
    ap.add_argument("--apply", action="store_true", help="真正写回（默认只统计）")
    ap.add_argument("--force", action="store_true",
                    help="连正在使用的会话也处理（有丢失最新几条的风险）")
    ap.add_argument("--live-window", type=int, default=LIVE_WINDOW,
                    help=f"多少秒内被写过就算「正在使用」（默认 {LIVE_WINDOW}）")
    args = ap.parse_args(argv)

    files = args.files or sorted(DEFAULT_ROOT.rglob("*.jsonl"))
    if not files:
        print("没找到任何会话存档")
        return 1

    now, total_before, total_after, skipped = time.time(), 0, 0, 0
    for p in files:
        if not p.is_file():
            print(f"跳过（不是文件）{p}")
            continue
        age = now - p.stat().st_mtime
        live = age < args.live_window
        if live and not args.force:
            print(f"⏸  {p.name}  {human(p.stat().st_size)}  "
                  f"{int(age)} 秒前刚写过，判定为正在使用，跳过（要处理加 --force）")
            skipped += 1
            continue
        s = process(p, args.apply)
        total_before += s["before"]
        total_after += s["after"]
        tag = "已清理" if (args.apply and s["images"]) else "可清理"
        note = "  ⚠️ 正在使用" if live else ""
        print(f"{'✅' if args.apply and s['images'] else '·'} {p.name}")
        print(f"    {s['lines']} 行，{s['images']} 张截图  {tag}")
        print(f"    {human(s['before'])} → {human(s['after'])}"
              f"（省 {human(s['before'] - s['after'])}）{note}")
        if s["caught_up"]:
            print(f"    ↩︎ 处理期间新写入的 {s['caught_up']} 行已追赶并保留")
        if s["bad"]:
            print(f"    ⚠️ {s['bad']} 行无法解析，已原样保留")

    if total_before:
        print(f"\n合计 {human(total_before)} → {human(total_after)}"
              f"，省 {human(total_before - total_after)}")
    if not args.apply and total_before:
        print("这是预演。真正写回请加 --apply")
    if skipped:
        print(f"{skipped} 个文件因正在使用被跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
