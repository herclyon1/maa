#!/usr/bin/env python3
"""Decode the displacement maps back into a field and compare, point by point:
  A. lens-map-{r,g,b}.png (full field, S 64) and seg-map-{r,g,b}.png (residual band field, S 32), 220×44 capsule, against the
     model of gen_lens_maps.py — the encoding round trip (must be ≤ 0.3 pt);
  B. verify-tab-lens-map-g.png (the same model rendered on the measured tab-bar lens, 115.68×73.61 r 35) against the ORIGINAL
     renderer-output samples phase-lift-gx-{light,dark}.json (rows ±20, x displacement) and phase-lift-gy-{light,dark}.json
     (columns ±25, y displacement, |s| ≤ 30 where the grating exists), G channel — the model fit, reported per zone.
Exit 1 when A exceeds 0.3 pt anywhere or the interior of B (d ≥ 12) exceeds 0.3 pt in mean.
  python3 verify_lens_maps.py [--ref ~/Money/styl-work/remote-ref/tools/lens]
"""
import importlib, json, os, struct, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
G = importlib.import_module("gen_lens_maps")   # the model next to this file
REF = os.path.expanduser(sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else "~/Money/styl-work/remote-ref/tools/lens")

def read_png(path):
    data = open(path, "rb").read(); assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n, = struct.unpack(">I", data[pos:pos + 4]); t = data[pos + 4:pos + 8]; d = data[pos + 8:pos + 8 + n]; pos += 12 + n
        if t == b"IHDR": w, h, bd, ct = struct.unpack(">IIBB", d[:10]); assert bd == 8 and ct == 6
        elif t == b"IDAT": idat += d
    raw = zlib.decompress(idat); stride = w * 4; rows = []; prev = bytearray(stride)
    for j in range(h):
        f = raw[j * (stride + 1)]; line = bytearray(raw[j * (stride + 1) + 1:(j + 1) * (stride + 1)])
        if f == 0: pass
        elif f == 1:
            for i in range(4, stride): line[i] = (line[i] + line[i - 4]) & 255
        elif f == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride): line[i] = (line[i] + ((line[i - 4] if i >= 4 else 0) + prev[i]) // 2) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0; b = prev[i]; c = prev[i - 4] if i >= 4 else 0
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line); prev = line
    return w, h, rows

def decode(rows, i, j):
    px = rows[j][i * 4:i * 4 + 4]
    return (px[0] - 128) / 255 * G.SCALE, (px[1] - 128) / 255 * G.SCALE   # zero = byte 128 (gen_lens_maps.encode)

def sample(rows, w, h, wpt, hpt, x, y):
    """decoded displacement at lens-relative (x, y) pt, nearest map pixel"""
    i = min(w - 1, max(0, int((x + wpt / 2) * G.PX))); j = min(h - 1, max(0, int((y + hpt / 2) * G.PX)))
    return decode(rows, i, j)

fails = 0
def cap(a, b): return G.capsule_sdf(a, b, G.LENS_W / 2, G.LENS_H / 2)
# ---- A: round trip on the two map sets (full S 64 @3 px/pt, residual S 32 @2 px/pt)
for prefix, scale, px, residual in (("lens-map", G.SCALE, G.PX, False), ("seg-map", G.RES_SCALE, G.RES_PX, True)):
    for chan in "RGB":
        w, h, rows = read_png(os.path.join(HERE, f"{prefix}-{chan.lower()}.png")); worst = 0.0
        for j in range(h):
            y = (j + 0.5) / px - G.LENS_H / 2
            for i in range(w):
                x = (i + 0.5) / px - G.LENS_W / 2
                ux, uy = G.field(x, y, chan, cap, residual)
                p_ = rows[j][i * 4:i * 4 + 4]; dx, dy = (p_[0] - 128) / 255 * scale, (p_[1] - 128) / 255 * scale   # zero = byte 128 (gen_lens_maps.encode)
                worst = max(worst, abs(dx - ux), abs(dy - uy))
        print(f"A. {prefix}-{chan.lower()}.png {w}×{h} S {scale:g}: decoded − model max |Δ| = {worst:.3f} pt (one byte = {scale / 255:.3f})", "OK" if worst <= 0.3 else "FAIL")
        fails += worst > 0.3
# ---- B: model vs the original phase samples on the tab-bar lens geometry (rect reduction, README §2.2)
TW, TH = 115.68, 73.61
w, h, rows = read_png(os.path.join(HERE, "verify-tab-lens-map-g.png"))
zones = {"interior (band parameter t ≥ 1)": [], "band, horizontal rows ±20 (t < 1)": [], "band, vertical columns ±25 (t < 1, d ≥ 10 only: no valid grating nearer the platter edge)": []}
for axis, files, lines, comp in (("x", ["phase-lift-gx-light.json", "phase-lift-gx-dark.json"], ["-20.0", "20.0"], 0),
                                 ("y", ["phase-lift-gy-light.json", "phase-lift-gy-dark.json"], ["-25.0", "25.0"], 1)):
    for fn in files:
        d0 = json.load(open(os.path.join(REF, fn)))
        for line in lines:
            p = d0["profiles"][line]["G"]; off = float(line); u0 = p["u"][p["s"].index(0.0)]   # centre value = the profile's phase reference (≈ +0.3 pt)
            for s_, u in zip(p["s"], p["u"]):
                if axis == "x" and s_ < -37: continue    # left of the platter end (no grating beyond −46, the σ 3 pt window reaches to −37)
                if axis == "y" and abs(s_) > 27: continue  # no grating above/below the platter beyond 30, and the σ 3 pt window reaches 3 pt in
                x, y = (s_, off) if axis == "x" else (off, s_)
                d, (nx, ny) = G.rect_sdf(x, y, TW / 2, TH / 2)
                t = d * G.W_X / (G.W_X * abs(nx) + G.W_Y * abs(ny)) / (len(G.P["G"]) - 1)
                got = sample(rows, w, h, TW, TH, x, y)[comp]
                zone = "interior (band parameter t ≥ 1)" if t >= 1 else ("band, horizontal rows ±20 (t < 1)" if axis == "x" else "band, vertical columns ±25 (t < 1, d ≥ 10 only: no valid grating nearer the platter edge)")
                zones[zone].append((abs(got - (u - u0)), fn, line, s_, u - u0, got))
print("B. model (decoded from verify-tab-lens-map-g.png) vs phase-lift-* G samples (centre offset removed), tab-bar lens 115.68×73.61:")
for z, v in zones.items():
    if not v: continue
    diffs = sorted(x[0] for x in v); mean = sum(diffs) / len(diffs); worst = max(v, key=lambda t_: t_[0])
    within = sum(1 for x in diffs if x <= 0.3) / len(diffs)
    print(f"   {z}: n={len(v)} mean |Δ| {mean:.2f} pt, median {diffs[len(diffs) // 2]:.2f}, ≤ 0.3 pt: {within * 100:.0f} %, worst {worst[0]:.2f} pt at {worst[1]} {worst[2]} s={worst[3]:g} (measured {worst[4]:.2f}, model {worst[5]:.2f})")
    if z.startswith("interior") and mean > 0.3: fails += 1
sys.exit(1 if fails else 0)
