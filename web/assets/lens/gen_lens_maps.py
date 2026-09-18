#!/usr/bin/env python3
"""Displacement maps + SVG filter for the lifted segmented-control lens (220×44 pt capsule, @3x).

Source of every number: ~/Money/styl-work/remote-ref/lens-refraction.md and the per-pt phase fields in
~/Money/styl-work/remote-ref/tools/lens/phase-lift-{gx,gy}-{light,dark}.json (renderer-output sampling of the
native _UILiquidLensView in its lifted state: content displacement u(s) = content position − screen position, pt).

Model (derived in README.md §2):
  u(p) = −(1 − 1/M)·p + e_c(d)·n̂(p)        M = 1.22 (interior magnification, phase-lift-* interior: u = −0.18·s)
  d    = signed distance to the capsule boundary (inside > 0), n̂ = outward unit normal
  e_c  = P_c(d · 22 / W(n̂)): the measured horizontal edge profile (table P, 1-pt steps, 0 beyond 24 pt) compressed to the
         band width of the local direction (W_X 22 pt at the ends, W_Y 11 pt at the top/bottom); channel c = R/G/B (dispersion)
  outside the capsule (d < 0): u = 0 (the lens clips there)

Encoding (feDisplacementMap): byte = 128 + round(u·255/S) (zero = byte 128 exactly; the browser's S·(byte/255 − .5) then carries a
constant +S/510 pt bias, identical in all channels); x → R channel, y → G channel, B = 128, A = 255; u in pt (= CSS px).
Two map sets: seg-map-* = residual field (band + dispersion only, S 32, 2 px/pt, for #seg-lens-warp — the 1.22 is a CSS scale),
lens-map-* = full field (S 64, 3 px/pt, for #seg-lens-warp-full). One byte step = S/255 → round trip error ≤ S/510 (verify_lens_maps.py).

  python3 gen_lens_maps.py            # writes seg-map-*.png, lens-map-*.png, lens-filter.svg, lens-test.html, lens-field.json, verify-tab-lens-map-g.png
"""
import json, math, struct, zlib, base64, os
HERE = os.path.dirname(os.path.abspath(__file__))
M = 1.22                        # interior magnification (lens-refraction.md §0/§2: u = −0.18·s ⇔ 1/1.22)
K = 1 - 1 / M                   # 0.18033
SCALE = 64.0                    # feDisplacementMap scale (pt); |u| ≤ 25 pt fits in ±32
LENS_W, LENS_H = 220.0, 44.0    # lifted segmented lens (--ios-touch-segment-lift-x 12 / -y 8: 196×28 → 220×44), capsule r 22
PX = 3                          # @3x
# Edge excess P_c(d) [pt] along the outward normal, d = distance inside the boundary along that normal (README §2.2):
# mean of phase-lift-gx-{light,dark}.json rows ±20, RIGHT side (the platter's left end has no grating), each profile's centre
# value (its phase reference, ≈ +0.3 pt) removed; d = 57.84 − s. Negative = the content shown comes from further inside.
# Horizontal band: onset ≈ 22 pt from the end (P ≈ 0 beyond), plateau −4.4…−4.75 within 8 pt of the boundary.
P = {
  "R": [-4.50, -4.568, -4.635, -4.695, -4.744, -4.773, -4.773, -4.729, -4.623, -4.431, -4.127, -3.713, -3.236, -2.772, -2.357, -1.98, -1.618, -1.257, -0.918, -0.637, -0.428, -0.283, -0.188, -0.13, -0.10, 0.0],
  "G": [-4.31, -4.395, -4.481, -4.566, -4.645, -4.709, -4.748, -4.737, -4.645, -4.415, -3.958, -3.232, -2.497, -1.952, -1.546, -1.222, -0.954, -0.726, -0.534, -0.372, -0.239, -0.135, -0.059, -0.007, 0.0, 0.0],
  "B": [-4.20, -4.267, -4.335, -4.396, -4.436, -4.435, -4.35, -4.123, -3.751, -3.32, -2.828, -2.351, -1.977, -1.667, -1.381, -1.114, -0.868, -0.648, -0.453, -0.284, -0.141, -0.027, 0.0, 0.0, 0.0, 0.0],
}
# Band width by direction: horizontal (normal along x) W_X = 22 pt = the table's own scale; vertical (normal along y) W_Y = 11 pt:
# the top/bottom columns ±25 of phase-lift-gy-* (valid to d ≈ 7) sit on P(d·22/11) within 0.4 pt (README §2.3), i.e. the same
# profile compressed 2×. In between (capsule ends) W(n̂) = W_X·|n_x| + W_Y·|n_y|. [渲染器输出采样 + 竖向按 2× 压缩的拟合替代]
W_X, W_Y = 22.0, 11.0
def excess(chan, d, nx=1.0, ny=0.0):
    t = P[chan]
    if d <= 0: return t[0]
    dd = d * W_X / (W_X * abs(nx) + W_Y * abs(ny))
    if dd >= len(t) - 1: return 0.0
    i = int(math.floor(dd)); f = dd - i
    return t[i] * (1 - f) + t[i + 1] * f

def capsule_sdf(x, y, hw, hh):
    """Stadium of half-size hw×hh (r = hh): inside distance (> 0 inside) and outward normal."""
    c = hw - hh
    if abs(x) <= c:
        d = hh - abs(y); n = (0.0, 1.0 if y > 0 else -1.0 if y < 0 else 0.0)
    else:
        cx = c if x > 0 else -c; dx, dy = x - cx, y; r = math.hypot(dx, dy)
        d = hh - r; n = (dx / r, dy / r) if r > 1e-9 else (1.0, 0.0)
    return d, n

def rrect_sdf(x, y, hw, hh, r):
    """Rounded rectangle (circular corners) — the tab-bar lens geometry used for verification against the phase JSON."""
    qx, qy = abs(x) - (hw - r), abs(y) - (hh - r)
    if qx > 0 and qy > 0:
        rr = math.hypot(qx, qy); d = r - rr; n = (qx / rr * (1 if x > 0 else -1), qy / rr * (1 if y > 0 else -1))
    elif qx > qy:
        d = hw - abs(x); n = (1.0 if x > 0 else -1.0, 0.0)
    else:
        d = hh - abs(y); n = (0.0, 1.0 if y > 0 else -1.0)
    return d, n

def rect_sdf(x, y, hw, hh):
    """Plain rectangle — the verification geometry for the tab-bar lens rows ±20 / columns ±25 (README §2.2: the phase profiles
    were reduced with the straight-edge distance, and the lifted shape's boundary at |y| = 20 is at ≈ 57.5, not the r35 circle)."""
    dx, dy = hw - abs(x), hh - abs(y)
    if dx < dy: return dx, (1.0 if x > 0 else -1.0, 0.0)
    return dy, (0.0, 1.0 if y > 0 else -1.0)

def field(x, y, chan, sdf, residual=False):
    """full: u = −K·p + e·n̂ (interior magnification 1.22 + edge band); residual: e·n̂ only (the 1.22 comes from a CSS scale)"""
    d, (nx, ny) = sdf(x, y)
    if d < 0: return 0.0, 0.0
    e = excess(chan, d, nx, ny)
    return (e * nx, e * ny) if residual else (-K * x + e * nx, -K * y + e * ny)

def encode(u, scale=None):
    """byte = 128 + round(u·255/S): zero is exactly byte 128 in every channel (a byte = 255·(.5 + u/S) would round 0 to 127 or 128
    depending on the sign of a 1e-3 residual, and the three channel maps then disagree by one byte at scattered interior pixels —
    feDisplacementMap point-samples, so a one-byte channel difference paints colour fringes on every glyph edge). The browser decodes
    S·(byte/255 − .5), i.e. everything carries a constant +S/510 pt (0.06 pt) which is the same for all channels and invisible."""
    scale = scale or SCALE
    v = 128 + int(round(u * 255 / scale))
    if v < 0 or v > 255: raise ValueError(f"displacement {u} pt does not fit scale {scale}")
    return v

def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)

def render_map(path, wpt, hpt, chan, sdf, px=PX, scale=None, residual=False):
    w, h = int(round(wpt * px)), int(round(hpt * px)); rows = []
    for j in range(h):
        y = (j + 0.5) / px - hpt / 2; row = bytearray()
        for i in range(w):
            x = (i + 0.5) / px - wpt / 2
            ux, uy = field(x, y, chan, sdf, residual)
            row += bytes((encode(ux, scale), encode(uy, scale), 128, 255))
        rows.append(row)
    write_png(path, w, h, rows); return w, h

RES_SCALE, RES_PX = 32.0, 2       # residual maps: |e| ≤ 4.8 pt fits S 32 (界面1号's constant); 2 px/pt → 440×88 (their suggestion)

def data_uri(name): return "data:image/png;base64," + base64.b64encode(open(os.path.join(HERE, name), "rb").read()).decode()

def filter_svg(fid, maps, scale, note):
    """maps = {chan: file}; 界面1号's pipeline: isolate a channel of the source → displace with that channel's map → feBlend lighten;
       region = the element's box (objectBoundingBox 0..100 %), feImage stretched to it (preserveAspectRatio none)"""
    iso = {"R": "1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0", "G": "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0", "B": "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0"}
    out = [f'  <filter id="{fid}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">', f"    <!-- {note} -->"]
    for c in "RGB":
        out.append(f'    <feImage href="{data_uri(maps[c])}" preserveAspectRatio="none" result="map{c}"/>')
    for c in "RGB":
        out.append(f'    <feColorMatrix in="SourceGraphic" type="matrix" values="{iso[c]}" result="src{c}"/>')
        out.append(f'    <feDisplacementMap in="src{c}" in2="map{c}" scale="{scale:g}" xChannelSelector="R" yChannelSelector="G" result="d{c}"/>')
    out.append('    <feBlend in="dR" in2="dG" mode="lighten" result="dRG"/>')
    out.append('    <feBlend in="dRG" in2="dB" mode="lighten"/>')
    out.append("  </filter>")
    return "\n".join(out)

def main():
    def cap(x, y): return capsule_sdf(x, y, LENS_W / 2, LENS_H / 2)
    full = {c: f"lens-map-{c.lower()}.png" for c in "RGB"}; res = {c: f"seg-map-{c.lower()}.png" for c in "RGB"}
    for c in "RGB":
        render_map(os.path.join(HERE, full[c]), LENS_W, LENS_H, c, cap)                                              # full field, S 64, 3 px/pt
        render_map(os.path.join(HERE, res[c]), LENS_W, LENS_H, c, cap, px=RES_PX, scale=RES_SCALE, residual=True)   # band + dispersion only, S 32, 2 px/pt
    TW, TH = 115.68, 73.61   # the measured tab-bar lens, same model, rect reduction — only for verify_lens_maps.py
    def tab(x, y): return rect_sdf(x, y, TW / 2, TH / 2)
    render_map(os.path.join(HERE, "verify-tab-lens-map-g.png"), TW, TH, "G", tab)
    head = """<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true">
  <!-- Lifted segmented-control lens (220×44 pt capsule). Generated by gen_lens_maps.py — do not edit by hand; sources in README.md.
       feDisplacementMap: P'(x,y) = P(x + scale·(R − .5), y + scale·(G − .5)), scale in user units (CSS px = pt). The filter region is the
       element's own box and the maps are stretched to it, so apply the filter to the lens-shaped element itself (max 220×44).
       color-interpolation-filters="sRGB" is required: with the default linearRGB the map bytes would be gamma-decoded before use.
       #seg-lens-warp (RECOMMENDED): edge band + dispersion only (byte = 128 + u·255/32, 440×88); the interior 1.22 magnification is a
         CSS transform scale(1.22) about the lens centre on the content inside — a real resample, so text stays crisp (feDisplacementMap
         point-samples and doubles pixel columns when it magnifies). Animate: scale attribute 0 → 32 with the lift progress, and the CSS
         scale 1 → 1.22 (lens-refraction.md §4.2: the magnification arrives earlier than the band — 1.20 at 100 ms, 1.22 from 150 ms).
       #seg-lens-warp-full: the whole field in the map (byte = 128 + u·255/64, 660×132) — one mechanism, but magnified text ghosts. -->
"""
    filt = head + filter_svg("seg-lens-warp", res, RES_SCALE, "residual: band + dispersion, S 32; content inside must carry scale(1.22)") + "\n" + \
           filter_svg("seg-lens-warp-full", full, SCALE, "full field incl. the 1.22 magnification, S 64") + "\n</svg>\n"
    open(os.path.join(HERE, "lens-filter.svg"), "w").write(filt)
    tpl = open(os.path.join(HERE, "lens-test.template.html"), encoding="utf-8").read()
    open(os.path.join(HERE, "lens-test.html"), "w", encoding="utf-8").write(tpl.replace("{{FILTER}}", filt.strip()))
    json.dump({"lens_pt": [LENS_W, LENS_H], "capsule_radius_pt": LENS_H / 2, "magnification": M, "k": K,
               "maps": {"seg-map-{r,g,b}.png": {"field": "residual (band + dispersion)", "scale": RES_SCALE, "px_per_pt": RES_PX, "size_px": [int(LENS_W * RES_PX), int(LENS_H * RES_PX)]},
                        "lens-map-{r,g,b}.png": {"field": "full (−0.18·p + band)", "scale": SCALE, "px_per_pt": PX, "size_px": [int(LENS_W * PX), int(LENS_H * PX)]}},
               "encoding": "byte = 128 + round(u·255/scale) (zero = 128 exactly; browser decodes scale·(byte/255 − .5) = u + scale/510); x→R, y→G; B 128; u = content position − screen position (pt, +x right, +y down)",
               "edge_excess_pt_by_d": P, "band_width_pt": {"x": W_X, "y": W_Y, "blend": "W = W_X·|n_x| + W_Y·|n_y|"},
               "sources": ["remote-ref/lens-refraction.md §0 §2 §3 §4.2", "remote-ref/tools/lens/phase-lift-gx-{light,dark}.json rows ±20 (R/G/B, right side, centre offset removed)",
                            "remote-ref/tools/lens/phase-lift-gy-{light,dark}.json columns ±25 (band width 11 pt vertical)"]},
              open(os.path.join(HERE, "lens-field.json"), "w"), indent=1, ensure_ascii=False)
    print("maps: residual", int(LENS_W * RES_PX), "×", int(LENS_H * RES_PX), "S", RES_SCALE, "; full", int(LENS_W * PX), "×", int(LENS_H * PX), "S", SCALE, "; filter", os.path.getsize(os.path.join(HERE, "lens-filter.svg")), "bytes")

if __name__ == "__main__": main()
