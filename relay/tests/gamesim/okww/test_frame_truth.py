"""Frame truth: on every recorded frame, the real OCR inside the region our overlay reads finds the
text a person read there (gamesim design section 1, "Frame-truth test (Windows)").

Runs inside an OK-WW checkout laid out by ci_prepare.py (Windows job gamesim-windows, lane
`installed`). Nothing is imitated: the case is ok-script's own TaskTestCase with OK-WW's own
config, as upstream's tests/TestOCR.py is, so `task.ocr` is ok-script's OCR call on the OCR
library OK-WW's config names (onnxocr), with ok-script's own text fixing. The truth comes from
frames.json (relay/tests/gamesim/frames/okww/), where each item names the region it lies in,
the box a person read it at, and the text; it never comes from this code.

What is asserted, per frame:
  - the file is the one frames.json lists (sha256) and OK-WW's UID strip (the real
    config.blur_area) is black - the repository is public;
  - for each truth item, the OCR of its region, restricted to the results whose centre lies in
    the item's box and joined in reading order, contains the text (NFKC, spaces dropped:
    「：」 and ":" are one character to the overlay's patterns);
  - each listed template feature (gray_teleport) is found by ok-script's find_one, at the
    point the machine clicked it.
Text only, never confidence: the game PC runs OCR on OpenVINO / NPU
(ok-script.2026-10-12.log 08:46:31, {'use_openvino': True, 'use_npu': True}), the runner on CPU.

The regions are bound to the code that reads them: each region's `call` must appear verbatim
in the loaded overlay (or in the upstream file the overlay follows), and its first four numbers
must be the region's box, so moving a box in the overlay without moving the truth fails here.
All frames are 1920x1080 (16:9), where ok-script's box_of_screen and ocr(x, y, to_x, to_y) give
the same pixel box (relative_box on the frame size), so one call form covers both.
"""
import hashlib
import json
import re
import sys
import unicodedata
import unittest
from pathlib import Path

_CTX = Path("ark_gamesim.json")
if not _CTX.is_file():
    raise SystemExit(f"run by relay/tests/gamesim/okww/ci_prepare.py inside an OK-WW checkout; no {_CTX}")
CTX = json.loads(_CTX.read_text(encoding="utf-8"))
FRAMES = Path(CTX["gamesim_okww"]).parent / "frames" / "okww"

from config import config  # noqa: E402  OK-WW's own config.py, as its tests import it
from ok.test.TaskTestCase import TaskTestCase  # noqa: E402
from src.task.FarmEchoTask import FarmEchoTask  # noqa: E402

import cv2  # noqa: E402  OK-WW's own dependency
import numpy as np  # noqa: E402

OVERLAY_MODULE = "ark_overrides"   # ok-script names the module after the file in ok_tasks/
_NUM = re.compile(r"\d+(?:\.\d+)?")
# The machine's click on a template, as its log line writes it: 'left_click gray_teleport (1351, 1007)'.
_CLICK = re.compile(r"left_click (\w+) \((\d+), (\d+)\)")


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text)).replace(" ", "")


def read_image(path: Path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def text_in_box(boxes, box, w, h) -> str:
    """The OCR results whose centre lies in `box` (relative x0, y0, x1, y1), joined in reading order."""
    x0, y0, x1, y1 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
    inside = [b for b in boxes
              if x0 <= b.x + b.width / 2 <= x1 and y0 <= b.y + b.height / 2 <= y1]
    inside.sort(key=lambda b: (round((b.y + b.height / 2) / 20), b.x))
    return "".join(norm(b.name) for b in inside)


class TestFrameTruth(TaskTestCase):
    task_class = FarmEchoTask
    config = config

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.index = json.loads((FRAMES / "frames.json").read_text(encoding="utf-8"))
        cls.regions = cls.index["regions"]
        overlay = sys.modules.get(OVERLAY_MODULE)
        if overlay is None:
            raise RuntimeError(f"ok-script did not load ok_tasks/{OVERLAY_MODULE}.py")
        path = Path(overlay.__file__)
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != CTX["overlay_sha256"]:
            raise RuntimeError(f"loaded overlay {got[:12]} is not the lane's {CTX['overlay']}")
        cls.sources = {"overlay": path.read_text(encoding="utf-8")}
        cls.ocr_cache = {}

    def frames(self):
        return self.index["frames"]

    def ocr_region(self, frame, region):
        """ok-script's OCR of one region of one frame (cached: several items share a region)."""
        key = (frame["path"], region)
        if key not in self.ocr_cache:
            self.set_image(str(FRAMES / frame["path"]))
            x0, y0, x1, y1 = self.regions[region]["box"]
            self.ocr_cache[key] = self.task.ocr(x0, y0, x1, y1) or []
        return self.ocr_cache[key]

    # -- the regions are the overlay's -------------------------------------------------------
    def test_regions_are_the_ones_the_code_reads(self):
        for name, r in self.regions.items():
            with self.subTest(region=name):
                where = r["file"]
                if where == "overlay":
                    text = self.sources["overlay"]
                else:
                    self.assertTrue(where.startswith("upstream:"), where)
                    text = Path(where.split(":", 1)[1]).read_text(encoding="utf-8")
                self.assertIn(r["call"], text, f"region {name}: {where} no longer has {r['call']!r}")
                nums = [float(n) for n in _NUM.findall(r["call"])[:4]]
                self.assertEqual(nums, [float(v) for v in r["box"]],
                                 f"region {name}: the call's box {nums} is not the region's {r['box']}")

    # -- the files ---------------------------------------------------------------------------
    def test_frames_are_the_listed_files_with_the_uid_strip_black(self):
        listed = {f["path"] for f in self.frames()}
        on_disk = {p.relative_to(FRAMES).as_posix() for p in FRAMES.rglob("*.png")}
        self.assertEqual(on_disk, listed, "every committed frame is in frames.json, and only those")
        blur = self.config["blur_area"]
        for f in self.frames():
            with self.subTest(frame=f["path"]):
                p = FRAMES / f["path"]
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), f["sha256"])
                img = read_image(p)
                h, w = img.shape[:2]
                self.assertEqual([w, h], [1920, 1080], "16:9 at 1920x1080, as recorded on the game PC")
                b = blur(w, h)
                strip = img[b.y:b.y + b.height, b.x:b.x + b.width]
                self.assertTrue(strip.size > 0 and int(strip.max()) == 0,
                                f"UID strip {b} is not black (max {int(strip.max()) if strip.size else None})")

    # -- the text ----------------------------------------------------------------------------
    def test_truth_text_is_read_in_its_region(self):
        missed = []
        for f in self.frames():
            for t in f["truth"]:
                with self.subTest(frame=f["path"], text=t["text"], region=t["region"]):
                    w, h = f["size"]
                    boxes = self.ocr_region(f, t["region"])
                    got = text_in_box(boxes, t["box"], w, h)
                    if norm(t["text"]) not in got:
                        near = [f"{b.name}@({b.x},{b.y})" for b in boxes][:40]
                        missed.append(f"{f['path']} [{t['region']}] want {t['text']!r} in {t['box']}, "
                                      f"read there {got!r}; region read {near}")
                    self.assertIn(norm(t["text"]), got)
        for m in missed:
            print("MISSED " + m)
        print(f"truth: {sum(len(f['truth']) for f in self.frames())} items on {len(self.frames())} frames, "
              f"{len(missed)} missed")

    def test_a_truth_in_the_wrong_box_is_not_read(self):
        # The check above can fail: the 0/41 row's text is not read in the 0/48 row's box.
        f = next(f for f in self.frames() if f["path"] == "nest_list/2026-10-07_092052.png")
        t48 = next(t for t in f["truth"] if t["text"] == "已击败残象：0/48")
        boxes = self.ocr_region(f, "nest_list")
        got = text_in_box(boxes, t48["box"], *f["size"])
        self.assertIn(norm("已击败残象：0/48"), got)
        self.assertNotIn(norm("已击败残象：0/41"), got)

    # -- the templates -----------------------------------------------------------------------
    def test_features_are_found_where_the_machine_clicked(self):
        n = 0
        for f in self.frames():
            for feat in f.get("features", []):
                with self.subTest(frame=f["path"], feature=feat["name"]):
                    click = _CLICK.search(feat["evidence"]) or _CLICK.search(f.get("evidence", ""))
                    self.assertIsNotNone(click, f"no click point in the evidence for {feat['name']}")
                    self.assertEqual(click.group(1), feat["name"])
                    cx, cy = int(click.group(2)), int(click.group(3))
                    self.set_image(str(FRAMES / f["path"]))
                    box = self.task.find_one(feat["name"])
                    self.assertIsNotNone(box, f"{feat['name']} not found")
                    self.assertTrue(box.x <= cx <= box.x + box.width and box.y <= cy <= box.y + box.height,
                                    f"{feat['name']} found at {box}, the machine clicked ({cx}, {cy})")
                    n += 1
        print(f"features: {n} found where the machine clicked")


if __name__ == "__main__":
    unittest.main()
