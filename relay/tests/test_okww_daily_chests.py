"""OK-WW's daily activity chests: every chest up to the points is claimed, and checked.

2026-10-10 the run ended at 80 points with the 20-80 chests unclaimed and
「Daily Task Completed」 in the log, and the relay said nothing (the user's words, 10-10
19:4x and 19:55, are quoted in docs/OKWW-PATCHES.md and docs/NOTIFICATIONS.md).
Upstream's claim_daily clicks one fixed point, the 100 chest, and never looks again
(DailyTask.py claim_daily, sha 2b4977b62f7c).

The sample is his own screenshot of the chest row (fixtures/ww-daily-80-1010-row.png,
from BOARD/evidence/ww-daily-80-1010.png): 80 points, 20-80 claimed (he claimed them
by hand), 100 not. The 「80 points, 20-80 not claimed」 state of that morning is the
same row with the 100 chest's unclaimed picture put over the 20-80 chests.

2026-10-11 09:29 all five were claimed (140 points), yet 「100 档点了没领到」 went out:
the 100 chest was looked for by its label's box centre, and 「100」 is a digit wider
than 「20」-「80」, so the look landed 14 px left of the tick (0.35; 0.96 where the tick
is). The reward preview the click opens was on screen too, but it stops above the
tick. That run's screenshot is fixtures/ww-daily-140-1011-row.png (the bottom of the
1920x1080 frame, y 800-1010, preview included).
"""
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from ark_relay.features.okww_patch import okww_overlay  # noqa: E402
from ark_relay.features.verify import outcome  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


ns = {"__name__": "ark_overrides_test"}
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)

ROW = np.array(Image.open(HERE / "fixtures" / "ww-daily-80-1010-row.png").convert("RGB"))
H, W = ROW.shape[:2]
# The tier labels' glyph boxes in the fixture (x0, y0, x1, y1), measured on the picture.
GLYPHS = {20: (592, 93, 615, 112), 40: (884, 93, 907, 112), 60: (1177, 93, 1201, 112),
          80: (1471, 93, 1493, 112), 100: (1749, 93, 1787, 112)}


def box(name, x0, y0, x1, y1, pad=0):
    return types.SimpleNamespace(name=name, x=x0 - pad, y=y0 - pad, width=x1 - x0 + 1 + 2 * pad,
                                 height=y1 - y0 + 1 + 2 * pad)


LABELS = [box(str(t), *g, pad=4) for t, g in GLYPHS.items()]
# What else the OCR reads as a tier number: the big points 「80」 at the left, above the row,
# and a quest row's 「20」 further up.
DECOYS = [box("80", 225, 15, 280, 65), box("20", 180, 2, 205, 14)]

print("[the row: labels, step, where the chests are]")
labels = ns["tier_labels"](LABELS + DECOYS, H)
check("five tiers, decoys dropped", sorted(labels), [20, 40, 60, 80, 100])
check("the 80 kept is the row's", labels[80][1] > 90, True)
step = ns["tier_step"](labels)
check("one tier step ~ 293 px", abs(step - 293) <= 1, True)
chest = {t: ns["chest_at"](labels, step, t) for t in labels}
check("the 20 chest is the circle at (663, 75), within a pixel",
      abs(chest[20][0] - 663) <= 1 and abs(chest[20][1] - 75) <= 1, True)

print("\n[his screenshot: 20-80 claimed, 100 not]")
gray = ROW.mean(axis=2)
scores = ns["tier_scores"](gray, labels, step)
print("    scores:", scores)
check("20-80 read as claimed", all(scores[t] >= ns["_CHECKED_MIN"] for t in (20, 40, 60, 80)), True)
check("100 reads as not claimed", scores[100] < ns["_CHECKED_MIN"], True)
small = np.array(Image.fromarray(ROW).resize((W * 3 // 5, H * 3 // 5))).mean(axis=2)
lab_s = {t: (x * 0.6, y * 0.6) for t, (x, y) in labels.items()}
sc_s = ns["tier_scores"](small, lab_s, ns["tier_step"](lab_s))
check("the same at 0.6 of the size", [sc_s[t] >= ns["_CHECKED_MIN"] for t in (20, 40, 60, 80, 100)],
      [True, True, True, True, False])

# The morning's state: the 100 chest's unclaimed picture over 20-80.
R = 46
cx100, cy100 = (round(v) for v in chest[100])
UNCLAIMED = ROW[cy100 - R:cy100 + R, cx100 - R:cx100 + R].copy()
CLAIMED = {t: ROW[round(chest[t][1]) - R:round(chest[t][1]) + R, round(chest[t][0]) - R:round(chest[t][0]) + R].copy()
           for t in (20, 40, 60, 80)}


def morning():
    img = ROW.copy()
    for t in (20, 40, 60, 80):
        x, y = (round(v) for v in chest[t])
        img[y - R:y + R, x - R:x + R] = UNCLAIMED
    return img


class Game:
    """The dailies page: OCR answers, clicks claim a chest (when the game takes them)."""

    def __init__(self, frame, points="80", takes=True, ocr_labels=None, chests=None):
        self.frame, self.points, self.takes = frame, points, takes
        self.ocr_labels = LABELS + DECOYS if ocr_labels is None else ocr_labels
        self.chests = chest if chests is None else chests
        self.clicks, self.logs, self.keys = [], [], []

    def next_frame(self):
        return self.frame

    def ocr(self, *a, match=None, **k):
        if match is not None and "100" in match.pattern:
            return self.ocr_labels
        return [box(self.points, 225, 15, 280, 65)] if self.points else []

    def click_relative(self, rx, ry, **k):
        x, y = rx * self.frame.shape[1], ry * self.frame.shape[0]
        for t, (cx, cy) in self.chests.items():
            if abs(x - cx) < 30 and abs(y - cy) < 30:
                self.clicks.append(t)
                if self.takes and t in CLAIMED:
                    ix, iy = round(cx), round(cy)
                    self.frame = self.frame.copy()
                    self.frame[iy - R:iy + R, ix - R:ix + R] = CLAIMED[t]
                return
        self.clicks.append(("miss", round(x), round(y)))

    def log_info(self, msg, **k):
        self.logs.append(msg)

    def send_key(self, key, **k):
        self.keys.append(key)

    def openF2Book(self, *a):  # noqa: N802 - upstream's name
        self.keys.append("book")

    def click(self, *a, **k):
        pass

    def screenshot(self, name):
        self.logs.append(f"[shot {name}]")


print("\n[the morning: 80 points, 20-80 not claimed -> each clicked, each checked]")
g = Game(morning())
check("before: 20-80 read as not claimed",
      [v < ns["_CHECKED_MIN"] for t, v in ns["tier_scores"](g.frame.mean(axis=2), labels, step).items() if t != 100],
      [True] * 4)
ns["_claim_tiers"](g)
check("clicked 20, 40, 60, 80 - not 100", g.clicks, [20, 40, 60, 80])
check("the points line for the relay", "活跃奖励：活跃度 80" in g.logs, True)
check("checked: all claimed", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)
check("no ESC needed", g.keys, [])

print("\n[the game does not take the clicks -> tried twice, then said, with a screenshot]")
g = Game(morning(), takes=False)
ns["_claim_tiers"](g)
check("each chest tried twice", sorted(g.clicks), sorted([20, 40, 60, 80] * 2))
failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
check("one 「没领到」 line naming 20-80", bool(failed) and "20、40、60、80 档点了没领到" in failed[0], True)
check("screenshot taken", "[shot daily_reward_unclaimed]" in g.logs, True)

print("\n[already claimed (his screenshot) -> nothing clicked, checked]")
g = Game(ROW.copy())
ns["_claim_tiers"](g)
check("nothing clicked", g.clicks, [])
check("checked", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)

print("\n[points not read -> said, nothing clicked]")
g = Game(morning(), points="")
ns["_claim_tiers"](g)
check("nothing clicked", g.clicks, [])
check("said", any(m.startswith("活跃奖励没领到：活跃度的分数没读到") for m in g.logs), True)

print("\n[10-11 09:29: all five claimed, the reward preview over the 100 chest -> checked, nothing clicked]")
ROW11 = np.array(Image.open(HERE / "fixtures" / "ww-daily-140-1011-row.png").convert("RGB"))
# Glyph boxes of the tier labels in that picture (x0, y0, x1, y1), and where each tick is
# (the best match of the tick, searched over +-40 px): 「100」 is 45 px wide, the rest 29-31.
GLYPHS11 = {20: (683, 174, 711, 193), 40: (937, 174, 967, 193), 60: (1193, 174, 1222, 193),
            80: (1449, 174, 1478, 193), 100: (1690, 174, 1734, 193)}
TICKS11 = {80: (1520, 159), 100: (1776, 159)}
LABELS11 = [box(str(t), *g, pad=4) for t, g in GLYPHS11.items()]
lab11 = ns["tier_labels"](LABELS11, ROW11.shape[0])
step11 = ns["tier_step"](lab11)
ch11 = {t: ns["chest_at"](lab11, step11, t) for t in lab11}
check("80 and 100 looked for within 5 px of their ticks",
      [abs(ch11[t][0] - x) <= 5 and abs(ch11[t][1] - y) <= 5 for t, (x, y) in TICKS11.items()], [True, True])
gray11 = ROW11.mean(axis=2)
sc11 = ns["tier_scores"](gray11, lab11, step11)
print("    scores:", sc11)
check("all five read as claimed, preview and all", [sc11[t] >= ns["_CHECKED_MIN"] for t in ns["DAILY_TIERS"]],
      [True] * 5)
# The cause, kept on record: placed by the box centre (the code before), 100 misses its tick.
by_centre = {int(b.name): (b.x + b.width / 2, b.y + b.height / 2) for b in LABELS11}
old = ns["tier_scores"](gray11, by_centre, ns["tier_step"](by_centre))
check("by the box centre the 100 tick is missed (the false alarm)",
      [old[t] >= ns["_CHECKED_MIN"] for t in ns["DAILY_TIERS"]], [True, True, True, True, False])
g = Game(ROW11.copy(), points="140", takes=False, ocr_labels=LABELS11, chests=ch11)
ns["_claim_tiers"](g)
check("nothing clicked", g.clicks, [])
check("checked: 领完核对通过", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)
check("no 「没领到」", any(m.startswith("活跃奖励没领到") for m in g.logs), False)

print("\n[the relay: the overlay's lines -> items undone (pushed as 「这一轮没干完」)]")
LOG_OK = "活跃奖励：活跃度 80\n活跃奖励：领完核对通过（活跃度 80，已领 20、40、60、80）\nDaily Task Completed"
got = {c.label: (c.ok, c.detail) for c in outcome.daily_reward_checks(LOG_OK)}
check("claimed: green", got.get("每日活跃奖励领到了"), (True, ""))
check("80 points: red, says how many", got.get("每日活跃满 100"), (False, "今天活跃 80 分，没满 100"))
LOG_BAD = "活跃奖励：活跃度 80\n活跃奖励没领到：20、40、60、80 档点了没领到（活跃度 80）\nDaily Task Completed"
got = {c.label: (c.ok, c.detail) for c in outcome.daily_reward_checks(LOG_BAD)}
check("not claimed: red, says which", got.get("每日活跃奖励领到了"), (False, "20、40、60、80 档点了没领到（活跃度 80）"))
LOG_FULL = "活跃奖励：活跃度 100\n活跃奖励：领完核对通过（…）"
check("100 points: both green", [c.ok for c in outcome.daily_reward_checks(LOG_FULL)], [True, True])
LOG_UP = "活跃奖励：没有核对，上游领奖正文变了（现在 abc，我们照着 2b4977b62f7c 抄的），照上游点 100 档"
check("upstream changed: red", [(c.label, c.ok) for c in outcome.daily_reward_checks(LOG_UP)],
      [("每日活跃奖励领到了", False)])
check("an old log says nothing new", outcome.daily_reward_checks("Daily Task Completed"), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
