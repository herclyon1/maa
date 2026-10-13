#!/usr/bin/env python3
"""Add a recorded OK-WW screen to the gamesim frame library, or check the library (Mac).

The library is relay/tests/gamesim/frames/okww/<screen-id>/<YYYY-MM-DD>_<HHMMSS>[_variant].png
plus one frames.json (gamesim design section 1, "Frame library"). The repository is public,
so every frame has OK-WW's UID strip blacked out. The strip is OK-WW's own: blur_area() from
the installed tag's config.py (relay/tests/gamesim/upstream/okww-<tag>/config.py.txt) run
with ok-script's own Box class (upstream/okscript-2.0.8/ok/feature/Box.py.txt), both copies
checked against their SOURCE.txt first. The Windows job checks the strip again with the real
config.blur_area (harness.ScriptedCase.check_frames, test_frame_truth.py).

    add_frame.py add SRC.png --screen-id ID --date 2026-10-12 --time 09:51:16.594 \\
        --okww v3.7.4 --source "game PC .../09-51-16.594_x_original.png" \\
        --evidence "ok-script.2026-10-12.log:1083 '...'" [--variant 3of3] [--shot NAME] [--about TEXT]
    add_frame.py propose LOG --at "2026-10-12 09:51:16"      # the machine's own lines (OCR it logged) within 3 s
    add_frame.py crops [PATH ...] --out DIR                   # each truth box cut out at full size, for the eye check
    add_frame.py check                                        # every entry: file, sha256, strip, truth boxes, regions

`add` writes the frame and a frames.json entry with an empty truth list; a person then fills
`truth` ({region, box, text, evidence}) after looking at `crops`, and sets `truth_checked`.
Truth text is what the screen shows, taken where possible verbatim from the OCR the machine
logged for that frame (`propose`); the proposal is never the truth by itself.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import re
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

GAMESIM = Path(__file__).resolve().parents[1]
FRAMES = GAMESIM / "frames" / "okww"
FRAMES_JSON = FRAMES / "frames.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_upstream as fu  # noqa: E402

# The OK-WW the game PC runs (test_gl_okww_contract.INSTALLED); its config.py has blur_area.
OKWW_TAG = "v3.7.4"
OKSCRIPT_TAG = "v2.0.8"
SCREEN_ID = re.compile(r"[a-z][a-z0-9_]*")
VARIANT = re.compile(r"[A-Za-z0-9-]+")
# The machine's lines around a screenshot: OK-WW writes the _shot file and logs the line
# that names it in the same millisecond (ok-script.2026-10-07.log:244 vs the file
# 09-20-52.282_nest_go_original.png); the clicks the screen led to come within 3 s
# (nest_travel 09:20:55.143, gray_teleport click logged 09:20:55.371, :249).
PROPOSE_WINDOW_S = 3


# --------------------------------------------------------------------------- the strip

def _pinned(tool: str, tag: str, path: str) -> str:
    """One file of a fetched upstream copy, after checking its sha256 against SOURCE.txt."""
    copy = fu.copy_dir(tool, tag)
    want = fu.read_manifest(copy)["files"].get(path)
    if want is None:
        raise SystemExit(f"{copy.name}/SOURCE.txt does not list {path}")
    data = (copy / (path + fu.SUFFIX)).read_bytes()
    if hashlib.sha256(data).hexdigest() != want:
        raise SystemExit(f"{copy.name}/{path}{fu.SUFFIX} differs from its SOURCE.txt sha256")
    return data.decode("utf-8")


def blur_area():
    """OK-WW's config.blur_area(width, height) at OKWW_TAG, returning ok-script's Box."""
    box_src = _pinned("okscript", OKSCRIPT_TAG, "ok/feature/Box.py")
    cfg_src = _pinned("okww", OKWW_TAG, "config.py")
    # Box.py imports only the ok-script logger; it is given the standard logging module's.
    stub = types.ModuleType("ok.util.logger")
    stub.Logger = type("Logger", (), {"get_logger": staticmethod(logging.getLogger)})
    saved = {k: sys.modules.get(k) for k in ("ok", "ok.util", "ok.util.logger")}
    sys.modules.update({"ok": types.ModuleType("ok"), "ok.util": types.ModuleType("ok.util"),
                        "ok.util.logger": stub})
    try:
        box_ns: dict = {"__name__": "ok.feature.Box"}
        exec(compile(box_src, "ok/feature/Box.py", "exec"), box_ns)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    fn = next((n for n in ast.parse(cfg_src).body
               if isinstance(n, ast.FunctionDef) and n.name == "blur_area"), None)
    if fn is None:
        raise SystemExit(f"okww-{OKWW_TAG}/config.py has no blur_area()")
    ns: dict = {"Box": box_ns["Box"]}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "config.py", "exec"), ns)
    return ns["blur_area"]


def strip_peak(arr, box) -> int:
    """Brightest value inside `box` of an HxWx3 array (0 = blacked out)."""
    region = arr[box.y:box.y + box.height, box.x:box.x + box.width]
    if region.size == 0:
        raise SystemExit(f"blur_area {box} lies outside the frame")
    return int(region.max())


# --------------------------------------------------------------------------- library

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_index() -> dict:
    return json.loads(FRAMES_JSON.read_text(encoding="utf-8"))


def save_index(data: dict) -> None:
    FRAMES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def add(a) -> int:
    for name, val in (("--date", a.date), ("--time", a.time), ("--okww", a.okww),
                      ("--source", a.source), ("--evidence", a.evidence)):
        if not val:
            raise SystemExit(f"{name} is required: a frame without its origin is not evidence")
    if not SCREEN_ID.fullmatch(a.screen_id):
        raise SystemExit(f"screen id {a.screen_id!r}: lower case, digits and _ (named by what the screen shows)")
    if a.variant and not VARIANT.fullmatch(a.variant):
        raise SystemExit(f"variant {a.variant!r}: letters, digits and -")
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", a.date) or not re.fullmatch(r"\d\d:\d\d:\d\d(\.\d+)?", a.time):
        raise SystemExit("--date YYYY-MM-DD, --time HH:MM:SS[.mmm] (the game PC's clock, UTC+8)")
    src = Path(a.src)
    img = Image.open(src)
    if img.mode != "RGB":
        raise SystemExit(f"{src.name}: mode {img.mode}, OK-WW screenshots are RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]
    box = blur_area()(w, h)
    arr[box.y:box.y + box.height, box.x:box.x + box.width] = 0
    rel = f"{a.screen_id}/{a.date}_{a.time[:8].replace(':', '')}" + (f"_{a.variant}" if a.variant else "") + ".png"
    out = FRAMES / rel
    data = load_index()
    if any(f["path"] == rel for f in data["frames"]):
        raise SystemExit(f"{rel} is already in frames.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Lossless: the pixels are the recording's except the strip; only the zlib effort differs.
    Image.fromarray(arr).save(out, optimize=True, compress_level=9)
    back = np.array(Image.open(out))
    if back.shape != arr.shape or (back != arr).any():
        raise SystemExit(f"{rel}: the written PNG does not read back as the blacked-out frame")
    if strip_peak(back, box):
        raise SystemExit(f"{rel}: the UID strip is not black after writing")
    entry = {
        "path": rel, "screen_id": a.screen_id, "about": a.about or "",
        "shot": a.shot or "",
        "source": f"{a.source}, original sha256 {sha256(src)}",
        "evidence": a.evidence,
        "sha256": sha256(out),
        "date": f"{a.date} {a.time} (game PC, UTC+8)",
        "okww": a.okww,
        "size": [w, h],
        "uid_strip": (f"blacked out: OK-WW config.blur_area({w}, {h}) = Box(x={box.x}, y={box.y}, "
                      f"width={box.width}, height={box.height}) (ok-wuthering-waves {OKWW_TAG} config.py), "
                      "every pixel 0; checked again on Windows with the real config.blur_area"),
        "truth": [], "truth_checked": "", "features": [], "cases_using": [],
    }
    data["frames"].append(entry)
    save_index(data)
    print(json.dumps(entry, ensure_ascii=False, indent=1))
    print(f"{rel}: {out.stat().st_size // 1024} KiB; fill `truth` after `add_frame.py crops {rel} --out DIR`")
    return 0


def propose(a) -> int:
    """The machine's own TaskExecutor lines within PROPOSE_WINDOW_S of a moment."""
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d) (\d\d):(\d\d):(\d\d)", a.at)
    if not m:
        raise SystemExit('--at "YYYY-MM-DD HH:MM:SS"')
    day, t0 = m.group(1), int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))
    stamp = re.compile(r"(\d{4}-\d\d-\d\d) (\d\d):(\d\d):(\d\d)")
    for n, line in enumerate(Path(a.log).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = stamp.match(line)
        if not s or s.group(1) != day or " DEBUG " in line:
            continue
        t = int(s.group(2)) * 3600 + int(s.group(3)) * 60 + int(s.group(4))
        if abs(t - t0) <= PROPOSE_WINDOW_S:
            print(f"{Path(a.log).name}:{n}: {line[:400]}")
    return 0


def crops(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data = load_index()
    regions = data.get("regions", {})
    for f in data["frames"]:
        if a.paths and f["path"] not in a.paths:
            continue
        img = Image.open(FRAMES / f["path"]).convert("RGB")
        w, h = img.size
        for i, t in enumerate(f["truth"]):
            x0, y0, x1, y1 = t["box"]
            pad = 8
            c = img.crop((max(0, int(x0 * w) - pad), max(0, int(y0 * h) - pad),
                          min(w, int(x1 * w) + pad), min(h, int(y1 * h) + pad)))
            name = f["path"].replace("/", "__")[:-4] + f"__{i}.png"
            c.save(out / name)
            print(f"{out / name}: {t['text']!r} in {t.get('region')} {regions.get(t.get('region'), {}).get('box')}")
        if a.regions:
            img2 = img.copy()
            d = ImageDraw.Draw(img2)
            for t in f["truth"]:
                x0, y0, x1, y1 = t["box"]
                d.rectangle((x0 * w, y0 * h, x1 * w, y1 * h), outline="red", width=3)
            img2.save(out / (f["path"].replace("/", "__")[:-4] + "__boxes.png"))
    return 0


def check(a) -> int:
    data = load_index()
    regions = data.get("regions", {})
    problems = []
    blur = blur_area()
    on_disk = {p.relative_to(FRAMES).as_posix() for p in FRAMES.rglob("*.png")}
    listed = set()
    for f in data["frames"]:
        rel = f["path"]
        listed.add(rel)
        p = FRAMES / rel
        if not p.is_file():
            problems.append(f"{rel}: no file")
            continue
        if sha256(p) != f["sha256"]:
            problems.append(f"{rel}: sha256 {sha256(p)[:12]} != frames.json {f['sha256'][:12]}")
        if rel.split("/")[0] != f["screen_id"]:
            problems.append(f"{rel}: folder is not its screen_id {f['screen_id']}")
        arr = np.array(Image.open(p).convert("RGB"))
        h, w = arr.shape[:2]
        if [w, h] != f["size"]:
            problems.append(f"{rel}: size {w}x{h} != frames.json {f['size']}")
        if peak := strip_peak(arr, blur(w, h)):
            problems.append(f"{rel}: UID strip not black (max {peak})")
        for k in ("source", "date", "okww"):
            if not f.get(k):
                problems.append(f"{rel}: no {k}")
        if f["truth"] and not f.get("truth_checked"):
            problems.append(f"{rel}: truth without truth_checked")
        for t in f["truth"]:
            x0, y0, x1, y1 = t["box"]
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                problems.append(f"{rel}: truth box {t['box']} out of the frame")
            if not t.get("text"):
                problems.append(f"{rel}: truth without text")
            r = regions.get(t.get("region"))
            if r is None:
                problems.append(f"{rel}: truth {t.get('text')!r}: region {t.get('region')!r} is not in regions")
                continue
            rx0, ry0, rx1, ry1 = r["box"]
            if not (rx0 <= x0 and ry0 <= y0 and x1 <= rx1 and y1 <= ry1):
                problems.append(f"{rel}: truth {t['text']!r} box {t['box']} is not inside region "
                                f"{t['region']} {r['box']}")
    for rel in sorted(on_disk - listed):
        problems.append(f"{rel}: on disk, not in frames.json")
    for name, r in regions.items():
        for k in ("box", "file", "call", "why"):
            if k not in r:
                problems.append(f"region {name}: no {k}")
    size = sum((FRAMES / f["path"]).stat().st_size for f in data["frames"] if (FRAMES / f["path"]).is_file())
    print(f"{len(data['frames'])} frames, {size / 1e6:.1f} MB, {sum(len(f['truth']) for f in data['frames'])} truth items, "
          f"{len(data.get('unrecorded', []))} unrecorded screens")
    for pr in problems:
        print(f"  ✗ {pr}")
    print("all checks passed" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("src")
    p.add_argument("--screen-id", required=True)
    p.add_argument("--date")
    p.add_argument("--time")
    p.add_argument("--okww")
    p.add_argument("--source")
    p.add_argument("--evidence")
    p.add_argument("--variant")
    p.add_argument("--shot")
    p.add_argument("--about")
    p = sub.add_parser("propose")
    p.add_argument("log")
    p.add_argument("--at", required=True)
    p = sub.add_parser("crops")
    p.add_argument("paths", nargs="*")
    p.add_argument("--out", required=True)
    p.add_argument("--regions", action="store_true", help="also save each frame with its truth boxes drawn")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    return {"add": add, "propose": propose, "crops": crops, "check": check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
