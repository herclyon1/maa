#!/usr/bin/env python3
"""Displacement maps + SVG filter for the lifted segmented-control lens, resampled from the measured displacement field.

Field: the data session's phase files for the segmented control (remote-ref/seg-lens-refraction.md §2, lens_phase.py output):
one file for the x displacement measured on rows, one for the y displacement measured on columns —
profiles[<row or column offset from the lens centre, pt>][R|G|B] = {s, u, mag, amp}, u = content position − screen position (pt) at
screen position s, amp = the demodulation amplitude (used as the validity mask). The lifted lens is 220×44 r 22; what is under it
(track / card) is displaced by this composite field; the label copy inside the lens is NOT displaced (§2.3: width ×1.00–1.01,
height ×1.00, centre offset 0), so it must sit in an unfiltered layer above the filtered copy.

  python3 gen_lens_maps.py --field <gx.json>,<gy.json> [--size 220x44] [--scale 32] [--px 2] [--dark <gx.json>,<gy.json>] [--out .]
      → seg-map-{r,g,b}.png, lens-filter.svg (#seg-lens-warp), lens-field.json, lens-test.html (from lens-test.template.html)

Field model (pure resampling, no analytic fit): each profile is masked where amp < 0.5·median (platter ends) and on the centre
row within |s| ≤ 20 (the label glyph, §2.1),
made odd-symmetric in s (u(−s) = −u(s); R / B keep their measured offset from G), gaps filled linearly; u_x(x, y) interpolates
between the measured rows by y, u_y(x, y) between the measured columns by x (clamped outside the sampled offsets); zero outside the
capsule. --stretch maps a
field measured on another lens size by normalised coordinates (placeholder use only).

Encoding (feDisplacementMap): byte = 128 + round(u·255/S); x → R, y → G, B 128, A 255; zero = byte 128 exactly in all channels.
The browser decodes S·(byte/255 − .5) = u + S/510 (a constant 0.06 pt shared by every channel).
"""
import argparse, base64, json, math, os, statistics, struct, zlib
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- fields ----------
def load_profiles(path):
    d = json.load(open(path)); half = float(d["half"]); out = {}
    for off, chans in d["profiles"].items():
        out[float(off)] = {c: (p["s"], p["u"], p.get("amp")) for c, p in chans.items()}
    return {"file": os.path.basename(path), "half": half, "lens": d.get("lens"), "profiles": out}

GLYPH_ROW, GLYPH_HALF = 6.5, 20.0   # the segment label sits on the centre row (|offset| < 6.5 pt = half the 13-pt glyph height) within |s| ≤ 20 pt

def valid(si, ai, med, off):
    """a phase sample is valid where its demodulation amplitude holds and no label glyph sits under the grating
    (seg-lens-refraction.md §2.1: the centre row's 「早班」 makes |s| ≤ 13 unreliable; masked to 20 with margin)"""
    return ai >= 0.5 * med and not (abs(off) < GLYPH_ROW and abs(si) <= GLYPH_HALF)

def clean(s, u, amp, off=0.0):
    """mask (valid()), make odd-symmetric, fill gaps by linear interpolation; returns a dict s → u on the file's 1-pt grid"""
    med = statistics.median(amp) if amp else 1.0
    ok = {si: ui for si, ui, ai in zip(s, u, amp or [med] * len(s)) if valid(si, ai, med, off)}
    sym = {}
    for si in set(abs(x) for x in s):
        v = [ok[x] * sg for x, sg in ((si, 1), (-si, -1)) if x in ok]
        if v: sym[si] = sum(v) / len(v)
    grid = sorted(set(abs(x) for x in s)); known = sorted(sym)
    if not known: return {}
    def at(si):
        if si in sym: return sym[si]
        lo = max([k for k in known if k < si], default=None); hi = min([k for k in known if k > si], default=None)
        if lo is None: return sym[hi]
        if hi is None: return sym[lo]
        return sym[lo] + (sym[hi] - sym[lo]) * (si - lo) / (hi - lo)
    full = {}
    for si in grid:
        v = at(si); full[si] = v; full[-si] = -v
    return full

def fill(table, grid):
    """linear gap filling of a {s: v} table over the grid"""
    known = sorted(table); out = {}
    if not known: return {}
    for si in grid:
        if si in table: out[si] = table[si]; continue
        lo = max([k for k in known if k < si], default=None); hi = min([k for k in known if k > si], default=None)
        out[si] = table[hi] if lo is None else table[lo] if hi is None else table[lo] + (table[hi] - table[lo]) * (si - lo) / (hi - lo)
    return out

def profiles_of(chans, off):
    """G: masked + odd-symmetric; R / B: G + the measured (c − G) offset kept as is (the dispersion has an even part near the
    top / bottom rows — a uniform chromatic shift — that odd symmetry would cancel), gaps filled"""
    s, uG, ampG = chans["G"]
    base = clean(s, uG, ampG, off); grid = sorted(base); out = {"G": base}
    for c in chans:
        if c == "G": continue
        sc, uc, ampc = chans[c]; medc = statistics.median(ampc) if ampc else 1.0
        d = {si: (ui - gi) for si, ui, ai, gi in zip(sc, uc, ampc or [medc] * len(sc), uG) if valid(si, ai, medc, off)}
        d = fill(d, grid); out[c] = {k: base[k] + d.get(k, 0.0) for k in grid}
    return out

def build_field(gx_path, gy_path):
    gx, gy = load_profiles(gx_path), load_profiles(gy_path)
    rows = {}   # signed y offset → chan → {s: u}  (x displacement along x); rows are kept by their signed offset: the chromatic
    cols = {}   # signed x offset → chan → {s: u}  (y displacement along y)   (R / B) offsets differ top vs bottom
    for off, chans in gx["profiles"].items():
        for c, t in profiles_of(chans, off).items(): rows.setdefault(off, {}).setdefault(c, []).append(t)
    for off, chans in gy["profiles"].items():
        for c, t in profiles_of(chans, 99.0).items(): cols.setdefault(off, {}).setdefault(c, []).append(t)   # columns never cross the label
    def merge(groups):
        out = {}
        for off, chans in groups.items():
            out[off] = {}
            for c, lst in chans.items():
                keys = set().union(*[set(l) for l in lst]); out[off][c] = {k: statistics.mean([l[k] for l in lst if k in l]) for k in keys}
        return out
    return {"gx": gx, "gy": gy, "rows": merge(rows), "cols": merge(cols), "half": (gx["half"], gy["half"])}

def sample1d(table, s):
    """linear interpolation in a {s: u} table (1-pt grid); 0 beyond its range"""
    if not table: return 0.0
    lo, hi = math.floor(s), math.ceil(s)
    if lo not in table or hi not in table: return 0.0
    if lo == hi: return table[lo]
    return table[lo] + (table[hi] - table[lo]) * (s - lo)

def interp_offsets(groups, chan, off, s):
    """value at the signed offset off by interpolating between the two nearest measured offsets (clamped), each sampled at s"""
    ks = sorted(groups); c = chan if chan in groups[ks[0]] else "G"
    if off <= ks[0]: return sample1d(groups[ks[0]][c], s)
    if off >= ks[-1]: return sample1d(groups[ks[-1]][c], s)
    lo = max(k for k in ks if k <= off); hi = min(k for k in ks if k >= off)
    if lo == hi: return sample1d(groups[lo][c], s)
    a, b = sample1d(groups[lo][c], s), sample1d(groups[hi][c], s)
    return a + (b - a) * (off - lo) / (hi - lo)

def capsule_inside(x, y, hw, hh):
    c = hw - hh
    return abs(y) <= hh if abs(x) <= c else math.hypot(abs(x) - c, y) <= hh

def capsule_edge_distance(x, y, hw, hh):
    """signed distance inside the capsule boundary (> 0 inside) and the nearest boundary point's inward direction"""
    c = hw - hh
    if abs(x) <= c: d = hh - abs(y); n = (0.0, -1.0 if y > 0 else 1.0)
    else:
        cx = c if x > 0 else -c; dx, dy = x - cx, y; r = math.hypot(dx, dy); d = hh - r; n = (-dx / r, -dy / r) if r > 1e-9 else (0.0, 1.0)
    return d, n

def portal_field_at(F, x, y, chan, hw, hh, pw, ph, gain, band, stretch):
    """label layer on the PORTAL geometry (second round, acceptance 2026-09-19): the label portal is a pw×ph capsule centred in the
    hw×hh lens (196×28 in 220×44: inset 12 / 8). Its band is the backdrop field's band mapped by 'the same SDF shape': a point d inside
    the portal boundary reads the backdrop field d / band inside the backdrop boundary at the corresponding boundary point (same x on
    the straight edges, same angle on the end circles), minus the backdrop's uniform interior part (0.22·y), × gain. Outside the portal
    the field is continued from its boundary (clamp-to-edge); inside beyond the band it is ~0 (the measured label centre is not
    distorted, seg-lens-refraction.md §2.3)."""
    d, n = capsule_edge_distance(x, y, pw / 2, ph / 2)
    if d < 0: x, y = x + n[0] * (-d + 0.25), y + n[1] * (-d + 0.25); d = 0.25
    # corresponding backdrop boundary point
    cp, cb = pw / 2 - ph / 2, hw / 2 - hh / 2
    if abs(x) <= cp: bx, by = x, (hh / 2 if y > 0 else -hh / 2)
    else:
        sx_ = 1 if x > 0 else -1; ang = math.atan2(y, x - sx_ * cp); bx, by = sx_ * cb + hh / 2 * math.cos(ang), hh / 2 * math.sin(ang)
    qx, qy = bx + n[0] * (d / band), by + n[1] * (d / band)          # d/band inside the backdrop boundary, same inward direction
    ux, uy = field_at(F, qx, qy, chan, hw, hh, stretch)
    uy -= 0.2180 * qy                                                # the backdrop's uniform vertical compression is not part of the band
    return ux * gain, uy * gain

def field_at(F, x, y, chan, hw, hh, stretch, gain=1.0, band=1.0):
    """(u_x, u_y) in pt at lens-relative (x, y) for the target capsule hw×hh.
    Outside the capsule the field is continued from the nearest boundary point (clamp-to-edge): the lens clips those pixels, and
    a hard drop to 0 there made every boundary pixel a ≥ 1.5 pt jump that the map sampler bled into the edge.
    band < 1 compresses the edge band towards the boundary (d → d / band) — used for the label layer's derived field."""
    d, n = capsule_edge_distance(x, y, hw, hh)
    if d < 0: x, y = x + n[0] * (-d + 0.5), y + n[1] * (-d + 0.5); d = 0.5
    if band != 1.0 and d < 24 / band:
        # a point d inside the boundary reads the backdrop field at d / band inside, along the same inward direction
        x, y = x + n[0] * (d / band - d), y + n[1] * (d / band - d)
    kx = F["half"][0] / hw if stretch else 1.0; ky = F["half"][1] / hh if stretch else 1.0
    ux = interp_offsets(F["rows"], chan, y * ky, x * kx) / kx
    uy = interp_offsets(F["cols"], chan, x * kx, y * ky) / ky
    return ux * gain, uy * gain

# ---------- maps ----------
def encode(u, scale):
    v = 128 + int(round(u * 255 / scale))
    if v < 0 or v > 255: raise ValueError(f"displacement {u:.2f} pt does not fit scale {scale}")
    return v

def png_rows(path):
    """minimal PNG reader (8-bit RGBA, any filter type) → (w, h, rows of bytes)"""
    data = open(path, "rb").read(); pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n, = struct.unpack(">I", data[pos:pos + 4]); t = data[pos + 4:pos + 8]; d = data[pos + 8:pos + 8 + n]; pos += 12 + n
        if t == b"IHDR": w, h = struct.unpack(">II", d[:8])
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
                a_ = line[i - 4] if i >= 4 else 0; b_ = prev[i]; c_ = prev[i - 4] if i >= 4 else 0; p_ = a_ + b_ - c_; pa, pb, pc = abs(p_ - a_), abs(p_ - b_), abs(p_ - c_)
                line[i] = (line[i] + (a_ if pa <= pb and pa <= pc else b_ if pb <= pc else c_)) & 255
        rows.append(line); prev = line
    return w, h, rows

def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

def render(path, F, chan, wpt, hpt, px, scale, stretch, gain, band=1.0, portal=None):
    w, h = int(round(wpt * px)), int(round(hpt * px)); rows = []; peak = 0.0
    for j in range(h):
        y = (j + 0.5) / px - hpt / 2; row = bytearray()
        for i in range(w):
            x = (i + 0.5) / px - wpt / 2
            ux, uy = portal_field_at(F, x, y, chan, wpt, hpt, portal[0], portal[1], gain, band, stretch) if portal else field_at(F, x, y, chan, wpt / 2, hpt / 2, stretch, gain, band)
            peak = max(peak, abs(ux), abs(uy))
            row += bytes((encode(ux, scale), encode(uy, scale), 128, 255))
        rows.append(row)
    write_png(path, w, h, rows); return w, h, peak

# ---------- filter ----------
ISO = {"R": "1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0", "G": "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0", "B": "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0"}
def data_uri(path): return "data:image/png;base64," + base64.b64encode(open(path, "rb").read()).decode()

def filter_rgb(fid, maps, scale, note):
    """opaque backdrop: per-channel maps (dispersion), the ui session's pipeline — isolate a channel → displace → feBlend lighten"""
    out = [f'  <filter id="{fid}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">', f"    <!-- {note} -->"]
    out += [f'    <feImage href="{data_uri(maps[c])}" preserveAspectRatio="none" result="map{c}"/>' for c in "RGB"]
    for c in "RGB":
        out.append(f'    <feColorMatrix in="SourceGraphic" type="matrix" values="{ISO[c]}" result="src{c}"/>')
        out.append(f'    <feDisplacementMap in="src{c}" in2="map{c}" scale="{scale:g}" xChannelSelector="R" yChannelSelector="G" result="d{c}"/>')
    out += ['    <feBlend in="dR" in2="dG" mode="lighten" result="dRG"/>', '    <feBlend in="dRG" in2="dB" mode="lighten"/>', "  </filter>"]
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--field", required=True, help="<gx.json>,<gy.json> the measured composite field")
    ap.add_argument("--size", default="220x44"); ap.add_argument("--scale", type=float, default=32.0); ap.add_argument("--px", type=int, default=2)
    ap.add_argument("--stretch", action="store_true", help="the field was measured on another lens size: map it by normalised coordinates")
    ap.add_argument("--dark", help="<gx.json>,<gy.json> the same field measured in dark mode (compared, maps use --field)")
    ap.add_argument("--label-from-bg", help="<gain>,<band>[,<portal WxH>]: derive the label layer's maps from the backdrop field — amplitude × gain, edge band compressed × band (native ContentLensing −8.8/−17.5 = 0.503, SDF height 7.04/11.2 = 0.629); with a portal size the band sits on the portal capsule centred in the lens (196x28: inset 12 / 8) and the backdrop's uniform interior part is removed")
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args(); W, H = (float(v) for v in a.size.lower().split("x"))
    F = build_field(*a.field.split(","))
    maps = {}; peak = 0.0
    for c in "RGB":
        p = os.path.join(a.out, f"seg-map-{c.lower()}.png"); w, h, pk = render(p, F, c, W, H, a.px, a.scale, a.stretch, 1.0); maps[c] = p; peak = max(peak, pk)
    # label layer: DERIVED, not measured — the same SDF shape with the native ContentLensing amount / height ratios (README §1b)
    lmaps = {}; lpeak = 0.0
    if a.label_from_bg:
        parts = a.label_from_bg.split(","); gain, band = float(parts[0]), float(parts[1])
        portal = tuple(float(v) for v in parts[2].lower().split("x")) if len(parts) > 2 else None
        for c in "RGB":
            p = os.path.join(a.out, f"seg-map-label-{c.lower()}.png"); _, _, pk = render(p, F, c, W, H, a.px, a.scale, a.stretch, gain, band, portal); lmaps[c] = p; lpeak = max(lpeak, pk)
    # jump statistics: adjacent-pixel steps ≥ 1.5 pt in the top / bottom 20 px rows (the acceptance count), after clamp-to-edge
    def jumps(path):
        w_, h_, rows_ = png_rows(path); n = 0
        for j in range(h_):
            if not (j < 20 or j >= h_ - 20): continue
            for i in range(w_):
                for ii, jj in ((i - 1, j), (i, j - 1)):
                    if ii < 0 or jj < 0: continue
                    a_, b_ = rows_[j][i * 4:i * 4 + 2], rows_[jj][ii * 4:ii * 4 + 2]
                    if max(abs(a_[0] - b_[0]), abs(a_[1] - b_[1])) * a.scale / 255 >= 1.5: n += 1
        return n
    jump_counts = {os.path.basename(p): jumps(p) for p in list(maps.values()) + list(lmaps.values())}
    # interior scales from the LOCAL slope away from the centre (row 0 carries a constant ±0.5 pt step at the centre — a level offset between
    # its two halves, not a magnification — so a centre-spanning difference quotient would read 0.987 where the content is at 1.00)
    sx = ((interp_offsets(F["rows"], "G", 0, 70) - interp_offsets(F["rows"], "G", 0, 40)) / 30 + (interp_offsets(F["rows"], "G", 0, -40) - interp_offsets(F["rows"], "G", 0, -70)) / 30) / 2
    sy = (interp_offsets(F["cols"], "G", 50, 10) - interp_offsets(F["cols"], "G", 50, -10)) / 20
    info = {"size_pt": [W, H], "scale": a.scale, "px_per_pt": a.px, "map_px": [w, h], "stretch": a.stretch,
            "encoding": "byte = 128 + round(u·255/scale); x→R, y→G; B 128; u = content − screen (pt, +x right, +y down); browser decodes scale·(byte/255 − .5) = u + scale/510",
            "field": {"gx": F["gx"]["file"], "gy": F["gy"]["file"], "measured_lens": F["gx"]["lens"], "half": F["half"], "rows_y": sorted(F["rows"]), "cols_x": sorted(F["cols"]), "peak_pt": round(peak, 2),
                      "interior": {"du_x/dx at y 0 (|x| 40–70, local slope)": round(sx, 4), "x scale": round(1 / (1 + sx), 2), "du_y/dy at x 50 (|y| ≤ 10)": round(sy, 4), "y scale": round(1 / (1 + sy), 3),
                                   "note": "row 0 holds a constant ±0.5 pt level step across the centre (seg-lens-refraction.md §0: M 1.00); the x scale is 1.00 within the noise"}},
            "label_copy": "measured: not displaced at the centre (seg-lens-refraction.md §2.3); the derived #seg-lens-warp-label bends it only near the ends (README §1b)",
            "label_layer": ({"derived_not_measured": True, "from": "backdrop field", "gain": float(a.label_from_bg.split(",")[0]), "band": float(a.label_from_bg.split(",")[1]),
                             "portal_pt": (a.label_from_bg.split(",")[2] if len(a.label_from_bg.split(",")) > 2 else None), "interior": "backdrop uniform part removed (label centre measured undistorted, §2.3)" if len(a.label_from_bg.split(",")) > 2 else "backdrop interior × gain",
                             "source": "seg-lens-drag-mid.md §0 标签场逐点剖面: ContentLensing shares the ClearGlass SDF shape, amount −8.8 vs −17.5, SDF height 7.04 vs 11.2 (原值); the field itself is not measured",
                             "peak_pt": round(lpeak, 2)} if a.label_from_bg else None),
            "edge": "clamp-to-edge outside the capsule (the field continues from the nearest boundary point; the lens clips those pixels)",
            "jumps_ge_1.5pt_top_bottom_20px": jump_counts,
            "sources": ["remote-ref/seg-lens-refraction.md §0 §2 §2.3", "remote-ref/seg-lift-material.md §1", "remote-ref/tools/touch/seg-phase-{gx,gy}-{light,dark}.json (data session, 2026-09-19)"]}
    print(f"maps {w}×{h} px, S {a.scale:g}, peak |u| {peak:.2f} pt; interior du_x/dx {sx:+.4f} (x scale {1 / (1 + sx):.2f}), du_y/dy {sy:+.4f} (y scale {1 / (1 + sy):.3f}); jumps ≥ 1.5 pt (top/bottom 20 px): {jump_counts}")
    if lmaps: print(f"label maps (derived): gain × band {a.label_from_bg}, peak |u| {lpeak:.2f} pt")
    if a.dark:
        dk = build_field(*a.dark.split(",")); diffs = []
        for j in range(0, int(H)):
            for i in range(0, int(W), 2):
                x, y = i + 0.5 - W / 2, j + 0.5 - H / 2
                if not capsule_inside(x, y, W / 2, H / 2): continue
                l = field_at(F, x, y, "G", W / 2, H / 2, a.stretch); d = field_at(dk, x, y, "G", W / 2, H / 2, a.stretch); diffs.append(max(abs(l[0] - d[0]), abs(l[1] - d[1])))
        info["dark_vs_light"] = {"gx": dk["gx"]["file"], "gy": dk["gy"]["file"], "mean_abs_diff_pt": round(sum(diffs) / len(diffs), 3), "max_abs_diff_pt": round(max(diffs), 2)}
        print(f"dark vs light field: mean |Δ| {info['dark_vs_light']['mean_abs_diff_pt']} pt, max {info['dark_vs_light']['max_abs_diff_pt']} pt (one map set serves both)")
    head = f"""<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true">
  <!-- Lifted segmented-control lens ({a.size} pt capsule r 22). Generated by gen_lens_maps.py from the measured composite field
       (README.md; seg-lens-refraction.md §2). feDisplacementMap: P'(x,y) = P(x + scale·(R − .5), y + scale·(G − .5)), scale {a.scale:g} in
       user units; the region is the element's own box and the maps are stretched to it. color-interpolation-filters="sRGB" is required
       (default linearRGB would gamma-decode the bytes). The interior scale of the content (1.00 wide / 0.82 tall) is IN the field: no
       CSS zoom. Apply to the OPAQUE copy of what lies under the lens (track / card); the label copy is not displaced natively — keep it
       in an unfiltered layer above. Per-channel maps carry the dispersion (R−B up to 3.6 pt at the ends), merged with feBlend lighten.
       Animate: the scale attribute 0 → {a.scale:g} with the lift curve of seg-keys.css (seg-lens-refraction.md §4.1: all lens quantities share it). -->
"""
    svg = head + filter_rgb("seg-lens-warp", maps, a.scale, f"composite field: {F['gx']['file']} + {F['gy']['file']}")
    if lmaps: svg += "\n" + filter_rgb("seg-lens-warp-label", lmaps, a.scale, f"LABEL LAYER, DERIVED (not measured): the backdrop field's band × {a.label_from_bg.split(',')[0]} amplitude, band × {a.label_from_bg.split(',')[1]}" + (f", on the {a.label_from_bg.split(',')[2]} label portal centred in the lens" if len(a.label_from_bg.split(',')) > 2 else "") + " (ContentLensing −8.8 / 7.04 vs ClearGlass −17.5 / 11.2, seg-lens-drag-mid.md §0); apply to the label copy only")
    svg += "\n</svg>\n"
    open(os.path.join(a.out, "lens-filter.svg"), "w").write(svg)
    tpl = os.path.join(HERE, "lens-test.template.html")
    if os.path.exists(tpl): open(os.path.join(a.out, "lens-test.html"), "w", encoding="utf-8").write(open(tpl, encoding="utf-8").read().replace("{{FILTER}}", svg.strip()))
    json.dump(info, open(os.path.join(a.out, "lens-field.json"), "w"), indent=1, ensure_ascii=False)
    print("filter", os.path.getsize(os.path.join(a.out, "lens-filter.svg")), "bytes")

if __name__ == "__main__": main()
