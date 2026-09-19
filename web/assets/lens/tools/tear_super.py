#!/usr/bin/env python3
"""tear_super.py — R38a: end_tear.py's closed form with the capsule SDF replaced by QuartzCore's supercircle branch (label-end-tear-closed-vs-map.md
§7 ② + §7b (a′): equal corner radii → supercircle_sdf_image<false>, CPU clamp = sat(2.89158·(1 − hs/r)) = (0, 0) for 220×44 r22 → the supercircle
branch with R = 1.528665·r = 33.63 pt), then the drag-mid 「早班」 ink of tear_fg.py (closed form + the foreground 7-tap kernel) for both SDFs.
usage: tear_super.py <ui2 lens dir> <label png> [circle|super]"""
import sys, math, importlib.util
import numpy as np
from PIL import Image
LENS_DIR, label_png = sys.argv[1], sys.argv[2]; MODES = sys.argv[3:] or ["circle", "super"]
sys.argv = [sys.argv[0], LENS_DIR, label_png]
spec = importlib.util.spec_from_file_location("end_tear", "/Users/herclyon/Money/styl-work/remote-ref/tools/lens/end_tear.py")
et = importlib.util.module_from_spec(spec); sys.modules["end_tear"] = et; spec.loader.exec_module(et)
HW, HH, r = et.HW, et.HH, et.R
KR = 1.528665; R = KR * r
def poly(rho): return (((-0.926054 * rho + 3.15601) * rho - 3.64122) * rho + 1.26803) * rho + 0.268531
def sdf_super(x, y):
    """supercircle_sdf(p, hs, r, clamp = (0, 0)) (IR 9455–9548): q = |p| − hs + R; u = max(0, q/R); ρ = min(u)/max(u); k = ρ²·sat(|u|)·poly(ρ);
    f = |u| + 1 − 1/(1 − k) (half-truncated); d = (f − 1)·R + min(max(q), 0); g = q.x + q.y > 0 ? normalize(max(0, q)) : axis"""
    cx, cy = abs(x) - HW, abs(y) - HH; qx, qy = cx + R, cy + R
    ux, uy = max(0.0, qx / R), max(0.0, qy / R); umax = max(ux, uy); rho = (min(ux, uy) / umax) if umax > 0 else 0.0
    ul = math.hypot(ux, uy); k = rho * rho * min(max(ul, 0.0), 1.0) * poly(rho)
    f = ul + 1.0 - 1.0 / (1.0 - k); f = float(np.float16(f))          # fptrunc … to half, back to float
    d = (f - 1.0) * R + min(max(qx, qy), 0.0)
    sx, sy = (1 if x >= 0 else -1), (1 if y >= 0 else -1)
    if qx + qy > 0: nx, ny = max(0.0, qx) * sx, max(0.0, qy) * sy
    else: nx, ny = (sx, 0.0) if qx > qy else (0.0, sy)
    n = math.hypot(nx, ny) or 1.0
    return d, nx / n, ny / n
# ---- tear_fg.py's ink (verbatim logic) on the chosen SDF ----
im = np.asarray(Image.open(label_png).convert("L")).astype(float); lab = 1 - im / 255.0; Hh, Ww = lab.shape
def lab_at(X, Y):
    fx, fy = X * 6 - 0.5, Y * 6 - 0.5; x0, y0 = int(math.floor(fx)), int(math.floor(fy)); tx, ty = fx - x0, fy - y0
    def at(i, j): return lab[min(max(j, 0), Hh - 1), min(max(i, 0), Ww - 1)]
    return (at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx) * (1 - ty) + (at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx) * ty
CX, CY = 220.0, 195.0
def closed_ink(X, Y):
    x, y = X - CX, Y - CY; d, _, _ = et.sdf_capsule(x, y)
    if d > 0: return lab_at(X, Y), d
    rx, ry, B = et.label_field(x, y); qx, qy, Bb = et.bg_field(x, y)
    dl, _, _ = et.sdf_capsule(rx, ry); Ml = min(max(0.5 - dl / et.FW, 0), 1)
    dq, _, _ = et.sdf_capsule(qx, qy); Mq = min(max(0.5 - dq / et.FW, 0), 1)
    c_lab = lab_at(rx + CX, ry + CY) * Ml * B; c_bg = lab_at(qx + CX, qy + CY) * (1 - Mq) * Bb
    return c_lab + c_bg * (1 - c_lab), d
THETA = -0.2618; WH = 1.72; AMP = 2.3158
def delta(x, y):
    d, gx, gy = et.g_oval(x, y); c, s = math.cos(THETA), math.sin(THETA); rgx, rgy = c * gx - s * gy, s * gx + c * gy
    return AMP * WH * rgy, AMP / WH * rgx
def e_of(d): return min(max((d + 8.8) / 8.8, 0.0), 1.0)
def fg_ink(X, Y):
    base, d = closed_ink(X, Y)
    if d > 0: return base
    e = e_of(d)
    if e <= 0: return base
    dx, dy = delta(X - CX, Y - CY)
    Rr = sum(k * closed_ink(X + k * dx, Y + k * dy)[0] for k in (1, 2/3, 1/3)) / 2
    Bc = sum(k * closed_ink(X - k * dx, Y - k * dy)[0] for k in (1, 2/3, 1/3)) / 2
    G = (closed_ink(X, Y)[0] + sum((1 - k) * (closed_ink(X + k * dx, Y + k * dy)[0] + closed_ink(X - k * dx, Y - k * dy)[0]) for k in (1/3, 2/3))) / 3
    return e * (.2126 * Rr + .7152 * G + .0722 * Bc) + (1 - e) * base
circle = et.sdf_capsule
for mode in MODES:
    et.sdf_capsule = circle if mode == "circle" else sdf_super
    x0, x1, y0, y1 = 95, 145, 185, 205; thresh = .56
    n = {"rest": 0, "closed": 0, "fg": 0}; nend = {"rest": 0, "closed": 0, "fg": 0}
    for j in range(int((y1 - y0) * 3)):
        Y = y0 + (j + .5) / 3
        for i in range(int((x1 - x0) * 3)):
            X = x0 + (i + .5) / 3; rr = lab_at(X, Y); c, _ = closed_ink(X, Y); f = fg_ink(X, Y)
            for k, v in (("rest", rr), ("closed", c), ("fg", f)):
                if v > thresh:
                    n[k] += 1
                    if X < 116: nend[k] += 1
    print("%-6s ink 「早班」 x 95–145 × y 185–205 (cov > .56): rest %d, closed %d (%.1f %%), closed+fg %d (%.1f %%); end x<116: %d / %d / %d" % (mode, n["rest"], n["closed"], 100*n["closed"]/n["rest"], n["fg"], 100*n["fg"]/n["rest"], nend["rest"], nend["closed"], nend["fg"]))
# the two SDFs along the end (centre line and rows ±4 / ±8), the last 12 pt
print("\nleft end, centre line: x_model  d_circle  d_super  | g_circle  g_super (oval .5)")
for s in (0, 0.33, 1, 2, 3, 4, 6, 8, 10, 12):
    x = -HW + s
    for y in (0.0,):
        dc, ncx, ncy = circle(x, y); ds, nsx, nsy = sdf_super(x, y)
        et.sdf_capsule = circle; _, gcx, gcy = et.g_oval(x, y); et.sdf_capsule = sdf_super; _, gsx, gsy = et.g_oval(x, y)
        print("  s %5.2f  d %7.3f %7.3f | g (%.3f, %.3f) (%.3f, %.3f)" % (s, dc, ds, gcx, gcy, gsx, gsy))
print("rows y = 4 / 8 / 12 / 16, s = 0 … 4:")
for y in (4.0, 8.0, 12.0, 16.0):
    line = []
    for s in (0, 1, 2, 4):
        x = -HW + s; dc, _, _ = circle(x, y); ds, _, _ = sdf_super(x, y); line.append("s%g: %6.2f/%6.2f" % (s, dc, ds))
    print("  y %4.1f  " % y + "  ".join(line))
