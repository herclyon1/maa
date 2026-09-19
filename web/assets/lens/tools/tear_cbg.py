#!/usr/bin/env python3
"""tear_cbg.py — R38a 续: the backdrop copy's share of the drag-mid 「早班」 end-zone ink in the closed form, decomposed the way 数据's R65 switched the
native layers (bg off / all off / bg only), plus the bg-path variants (capture margin, the glass_background inner stage, the supercircle) and the
lifted-state softening test (the label copy rasterised at 1 … 3 px/pt and magnified to 3×, R52's metrics). Numbers in label-end-tear-closed-vs-map.md §7e.
usage: tear_cbg.py <ui2 lens dir> <label png (tear/label-native-m.png, 6 px/pt)> [bg|super|soft]  (default: all three)
The closed form is end_tear.py's (imported from ~/Money/styl-work/remote-ref/tools/lens), the counting = tear_fg.py's (x 95–145 × y 185–205, cov > .56, 3 px/pt)."""
import sys, math, importlib.util
import numpy as np
from PIL import Image
LENS_DIR, label_png = sys.argv[1], sys.argv[2]; WHAT = sys.argv[3:] or ["bg", "super", "soft"]
spec = importlib.util.spec_from_file_location("end_tear", "/Users/herclyon/Money/styl-work/remote-ref/tools/lens/end_tear.py")
et = importlib.util.module_from_spec(spec); sys.modules["end_tear"] = et; sys.argv = [sys.argv[0], LENS_DIR, label_png]; spec.loader.exec_module(et)
lab6 = 1 - np.asarray(Image.open(label_png).convert("L")).astype(float) / 255.0; Hh, Ww = lab6.shape
def lab_at(X, Y):
    fx, fy = X * 6 - 0.5, Y * 6 - 0.5; x0, y0 = int(math.floor(fx)), int(math.floor(fy)); tx, ty = fx - x0, fy - y0
    def at(i, j): return lab6[min(max(j, 0), Hh - 1), min(max(i, 0), Ww - 1)]
    return (at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx) * (1 - ty) + (at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx) * ty
CX, CY = 220.0, 195.0
def clamp_m(x, y, m):
    if m is None: return x, y
    h = 0.5 / 3.0; return min(max(x, -et.HW - m + h), et.HW + m - h), min(max(y, -et.HH - m + h), et.HH + m - h)
def bg_field(x, y, margin=0.0, bgi=True):
    if bgi: qx, qy, d0 = et.stage(x, y, et.BGI); B = et.cov(d0); qx, qy = clamp_m(qx, qy, margin)
    else: qx, qy, B = x, y, 1.0
    rx, ry, d1 = et.stage(qx, qy, et.BG); B *= et.cov(d1); return (*clamp_m(rx, ry, margin), B)
def closed_ink(X, Y, labels=True, bgon=True, margin=0.0, bgi=True, sdf_lab=None, sdf_bg=None):
    x, y = X - CX, Y - CY; sl = sdf_lab or et.sdf_capsule; sb = sdf_bg or et.sdf_capsule
    d, _, _ = sl(x, y)
    if d > 0: return lab_at(X, Y)
    et.sdf_capsule = sl
    if labels: rx, ry, B = et.label_field(x, y)
    else: rx, ry, B = x, y, 1.0
    dl, _, _ = sl(rx, ry); Ml = et.cov(dl); c_lab = lab_at(rx + CX, ry + CY) * Ml * B
    if not bgon: return c_lab
    et.sdf_capsule = sb; qx, qy, Bb = bg_field(x, y, margin, bgi); dq, _, _ = sb(qx, qy); Mq = et.cov(dq)
    return c_lab + lab_at(qx + CX, qy + CY) * (1 - Mq) * Bb * (1 - c_lab)
def ink(**kw):
    n = ne = ni = 0
    for j in range(60):
        Y = 185 + (j + .5) / 3
        for i in range(150):
            X = 95 + (i + .5) / 3
            if closed_ink(X, Y, **kw) > .56:
                n += 1; ne += X < 116; ni += 110 <= X < 116
    return n, ne, ni
circle = et.sdf_capsule
def decompose(tag, **kw):
    full, off, only, none = ink(**kw), ink(bgon=False, **kw), ink(labels=False, **kw), ink(labels=False, bgon=False, **kw)
    print("%-34s full %4d/%3d(%3d)  bg off %4d/%3d(%3d)  bg only %4d/%3d(%3d)  all off %4d/%3d(%3d)  → bg term with fields %+d, without %+d" % (tag, *full, *off, *only, *none, full[1] - off[1], only[1] - none[1]))
if "bg" in WHAT:
    print("closed form (circle), 早班 x 95–145 (total / end x<116 / 110–116); native R65: full 642/176(120) · #11 off 591/125(69) · bg only 881/356(300) · all off 792/267(211) → +51 / +89")
    decompose("as built (bg clamped to the box, BGI+BG)")
    decompose("capture margin 9 (real content)", margin=9.0); decompose("capture margin 80", margin=80.0); decompose("no clamp", margin=None)
    decompose("no BGI stage (only BG +9/36)", bgi=False); decompose("no BGI, margin 80", bgi=False, margin=80.0)
if "super" in WHAT:
    src = open(__file__.replace("tear_cbg.py", "tear_super.py")).read(); HW, HH, r = et.HW, et.HH, et.R; KR = 1.528665; R = KR * r
    exec(src[src.index("def poly"):src.index("# ---- tear_fg.py")])
    print("\nsupercircle (label-end-tear §7b) on which path:")
    decompose("supercircle on all paths", sdf_lab=sdf_super, sdf_bg=sdf_super); decompose("supercircle labels, circle bg (as built)", sdf_lab=sdf_super, sdf_bg=circle)
    et.sdf_capsule = circle
if "soft" in WHAT:
    def sample3x(ppp):
        k = int(round(6 / ppp)); h, w = Hh // k, Ww // k; small = lab6[:h * k, :w * k].reshape(h, k, w, k).mean(axis=(1, 3))
        out_h, out_w = h * k // 2, w * k // 2; ys = (np.arange(out_h) + .5) / 3 * ppp - .5; xs = (np.arange(out_w) + .5) / 3 * ppp - .5
        y0 = np.clip(np.floor(ys).astype(int), 0, h - 2); x0 = np.clip(np.floor(xs).astype(int), 0, w - 2); ty = (ys - y0)[:, None]; tx = (xs - x0)[None, :]
        a, b, c, d = small[y0][:, x0], small[y0][:, x0 + 1], small[y0 + 1][:, x0], small[y0 + 1][:, x0 + 1]
        return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
    def metrics(img3):
        p = img3[185 * 3:205 * 3, 95 * 3:145 * 3]; core = p[p > .56]
        return "n>.56 %4d  core %.3f  mid(.2–.56) %4d  peak cols %2d  end x<116 %3d  n>.25 %4d" % ((p > .56).sum(), core.mean() if core.size else 0, ((p > .2) & (p <= .56)).sum(), (p.max(axis=0) > .9).sum(), (p[:, :63] > .56).sum(), (p > .25).sum())
    print("\nlifted-state softening (all fields off; native R52 rest → bothoff: core .924 → .852, mid 254 → 787, peak cols 66 → 50; R65 end x<116 333 → 267, n>.56 942 → 792):")
    for ppp in (3.0, 2.0, 1.5, 1.0): print("  label copy rasterised at %.1f px/pt, shown at 3×:  %s" % (ppp, metrics(sample3x(ppp))))
