#!/usr/bin/env python3
"""Decode seg-map-{r,g,b}.png back into a displacement field and compare it point by point:
  A. against the resampled field of gen_lens_maps.py (encoding round trip; must be ≤ 0.3 pt everywhere);
  B. against the ORIGINAL phase samples (seg-phase-gx/gy-*.json, every valid 1-pt sample of every measured row / column and
     channel; a sample is valid where amp ≥ 0.5·median) — the fit of the resampling (masking, odd symmetry, row averaging).
Exit 1 when A exceeds 0.3 pt anywhere or B's mean exceeds 0.3 pt.
  python3 verify_lens_maps.py --field <gx.json>,<gy.json> [--maps .] [--size 220x44] [--scale 32] [--px 2]
"""
import argparse, importlib, os, statistics, struct, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
G = importlib.import_module("gen_lens_maps")

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
        if f == 1:
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

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--field", required=True); ap.add_argument("--maps", default=HERE); ap.add_argument("--size", default="220x44")
    ap.add_argument("--scale", type=float, default=32.0); ap.add_argument("--px", type=int, default=2)
    ap.add_argument("--label-lift"); ap.add_argument("--label-drag"); ap.add_argument("--amp-floor", type=float, default=0.5); ap.add_argument("--label-amp-floor", type=float, default=0.25)
    a = ap.parse_args(); W, H = (float(v) for v in a.size.lower().split("x")); hw, hh = W / 2, H / 2
    fails = 0
    for prefix, spec, glyph in (("seg-map", a.field, True), ("seg-map-label-lift", a.label_lift, False), ("seg-map-label-drag", a.label_drag, False)):
        if not spec: continue
        G.AMP_FLOOR[0] = a.amp_floor if glyph else a.label_amp_floor; G.SYMMETRIC[0] = glyph
        print(f"### {prefix} ← {', '.join(x.split('/')[-1] for x in spec.split(','))} (amp floor {G.AMP_FLOOR[0]})")
        fails += check_set(G.build_field(*spec.split(","), glyph_rows=glyph), prefix, glyph, a, W, H, hw, hh)
    sys.exit(1 if fails else 0)

def check_set(F, prefix, glyph, a, W, H, hw, hh):
    fails = 0
    maps = {}
    for c in "RGB":
        w, h, rows = read_png(os.path.join(a.maps, f"{prefix}-{c.lower()}.png")); maps[c] = (w, h, rows); worst = 0.0
        for j in range(h):
            y = (j + 0.5) / a.px - hh
            for i in range(w):
                x = (i + 0.5) / a.px - hw
                ux, uy = G.field_at(F, x, y, c, hw, hh, False); p = rows[j][i * 4:i * 4 + 4]
                worst = max(worst, abs((p[0] - 128) / 255 * a.scale - ux), abs((p[1] - 128) / 255 * a.scale - uy))
        print(f"A. {prefix}-{c.lower()}.png {w}×{h} S {a.scale:g}: decoded − resampled field max |Δ| = {worst:.3f} pt (one byte = {a.scale / 255:.3f})", "OK" if worst <= 0.3 else "FAIL")
        fails += worst > 0.3
    # B: decoded map vs the raw samples
    def decoded(c, x, y, comp):
        w, h, rows = maps[c]; i = min(w - 1, max(0, int((x + hw) * a.px))); j = min(h - 1, max(0, int((y + hh) * a.px)))
        p = rows[j][i * 4:i * 4 + 4]; return (p[comp] - 128) / 255 * a.scale
    diffs = {"gx (x displacement, rows)": [], "gy (y displacement, columns)": []}
    gys = [F["gy"]] + [G.load_profiles(os.path.join(os.path.dirname(a.field.split(",")[0]), f)) for f in F["files"][2:]]
    for key, profs, comp, axis in (("gx (x displacement, rows)", [F["gx"]], 0, "x"), ("gy (y displacement, columns)", gys, 1, "y")):
      for prof in profs:
        for off, chans in prof["profiles"].items():
            for c, (s, u, amp) in chans.items():
                med = statistics.median(amp) if amp else 1.0
                for si, ui, ai in zip(s, u, amp or [med] * len(s)):
                    if not G.valid(si, ai, med, (off if axis == "x" else 99.0) if glyph else 99.0): continue
                    x, y = (si, off) if axis == "x" else (off, si)
                    if not G.capsule_inside(x, y, hw, hh): continue
                    diffs[key].append((abs(decoded(c, x, y, comp) - ui), off, c, si, ui, decoded(c, x, y, comp)))
    print("B. decoded map vs the original phase samples (valid samples, all rows / columns / channels):")
    for key, v in diffs.items():
        if not v: continue
        d = sorted(x[0] for x in v); worst = max(v, key=lambda t: t[0]); mean = sum(d) / len(d)
        print(f"   {key}: n={len(v)} mean |Δ| {mean:.2f} pt, median {d[len(d) // 2]:.2f}, ≤ 0.3 pt: {100 * sum(1 for x in d if x <= 0.3) / len(d):.0f} %, worst {worst[0]:.2f} at offset {worst[1]:g} {worst[2]} s={worst[3]:g} (sample {worst[4]:+.2f}, map {worst[5]:+.2f})")
        if mean > 0.3: fails += 1
    return fails

if __name__ == "__main__": main()
