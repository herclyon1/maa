"""The desktop agent's working files do not pile up in state/desktop/ (review 2026-10-13, s5 #7).

Every read(), click_text() and screenshot() left req-<id>.json, res-<id>.json,
shot-<id>.png and shot-<id>-x2.png behind, and nothing removed them. Now the
request and result go as soon as the answer is read, and screenshots older than
Desktop.WORK_KEEP_SECONDS go at the next run (a fresh one is kept: its path is
quoted in problem notes and in the machine checks' trace). Files of other
features in the same folder are never touched. No Windows here: spawns are faked.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core.desktop import Desktop
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def agent(exe, cwd, args):
    """Behaves like the agent: a screenshot (and its 2x copy for OCR), then the result."""
    req, res = Path(args[-2]), Path(args[-1])
    r = json.loads(req.read_text(encoding="utf-8"))
    shot = Path(r["shot"])
    shot.write_bytes(b"\x89PNG fake")
    shot.with_name(shot.stem + "-x2.png").write_bytes(b"\x89PNG fake")
    res.write_text(json.dumps({"ok": True, "log": [], "ocr": [{"text": "开始游戏"}], "clicked": ["开始游戏"]}),
                   encoding="utf-8")
    return True


state = tmpdir() / "state"
d = Desktop(state, spawn=agent, timeout=5)
work = state / "desktop"
work.mkdir(parents=True, exist_ok=True)
week_ago = time.time() - 8 * 24 * 3600
stale = [work / "req-0000aaaa.json", work / "res-0000aaaa.json", work / "shot-0000aaaa.png",
         work / "shot-0000aaaa-x2.png"]
for f in stale:
    f.write_bytes(b"old")
    os.utime(f, (week_ago, week_ago))
others = [work / "image-ocr.json", work / "poster.png"]       # error_evidence, wuwa_posters
for f in others:
    f.write_bytes(b"keep")
    os.utime(f, (week_ago, week_ago))

print("[一次读屏、一次点字之后]")
scr = d.read()
check("读到了字", scr.has("开始游戏"), True)
check("点到了", d.click_text("开始游戏"), True)
check("没有留下请求文件", sorted(p.name for p in work.glob("req-*.json")), [])
check("没有留下结果文件", sorted(p.name for p in work.glob("res-*.json")), [])
check("这次的截图还在（问题记录里引着它的路径）", scr.shot is not None and Path(scr.shot).is_file(), True)
check("一周前的截图和请求、结果都清掉了", [f.name for f in stale if f.exists()], [])
check("同一个文件夹里别的功能的文件没动", [f.name for f in others if f.exists()], [f.name for f in others])

print("\n[助手没起来：请求文件也不留]")
d2 = Desktop(state, spawn=lambda *a: False, timeout=5)
d2.read()
check("没有留下请求文件", sorted(p.name for p in work.glob("req-*.json")), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
