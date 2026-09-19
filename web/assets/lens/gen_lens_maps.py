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

--formula (2026-09-19, the default deliverable): the maps are COMPUTED from the decompiled QuartzCore shader formulas with the
probe's original parameters — no measured field goes into a map; the measured fields (seg-phase-*.json) are only compared against
the result (README §1d, lens-field.json). One map serves all three channels (no dispersion: the colour fringe is a separate
glassForeground aberration term, not in the displacement maps). A set of maps per lens width (196 … 256 step 2) for the drag stretch.

  python3 gen_lens_maps.py --formula --series 196:256:2 [--frames <drag lens frames json,…>] [--verify-bg <gx.json,gy.json>[;…]]
      [--verify-label-lift <gx,gy>] [--verify-label-drag <gx,gy,gy-ends>] [--verify-label-mid244 <gx6,gy>] [--out .]
      → seg-f-bg-<w>.png, seg-f-lab-<w>.png, lens-filter.svg (#seg-lens-f-bg-<w>, #seg-lens-f-lab-<w>; feImage href = files),
        lens-field.json (parameters + sources + the width → height table + residuals), lens-test.html
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
AMP_FLOOR = [0.5]                    # a sample is valid where amp ≥ AMP_FLOOR × the profile's median amp (--amp-floor; the label-portal
                                     # gratings fade to 0.25–0.5 of the median in the last 6 pt of the portal, where the field is largest)

def valid(si, ai, med, off):
    """a phase sample is valid where its demodulation amplitude holds and no label glyph sits under the grating
    (seg-lens-refraction.md §2.1: the centre row's 「早班」 makes |s| ≤ 13 unreliable; masked to 20 with margin)"""
    return ai >= AMP_FLOOR[0] * med and not (abs(off) < GLYPH_ROW and abs(si) <= GLYPH_HALF)

SYMMETRIC = [True]                   # odd symmetry u(−s) = −u(s) (the backdrop field: noise suppression); off for the measured label fields

def clean(s, u, amp, off=0.0):
    """mask (valid()), optionally make odd-symmetric, fill gaps by linear interpolation; returns a dict s → u on the file's 1-pt grid"""
    med = statistics.median(amp) if amp else 1.0
    ok = {si: ui for si, ui, ai in zip(s, u, amp or [med] * len(s)) if valid(si, ai, med, off)}
    if not SYMMETRIC[0]: return fill(ok, sorted(set(s)))
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
        # offset against the cleaned G (not the raw G sample, which may itself be masked noise there): a valid R / B sample is then
        # reproduced exactly by base + offset
        d = {si: (ui - base[si]) for si, ui, ai in zip(sc, uc, ampc or [medc] * len(sc)) if valid(si, ai, medc, off) and si in base}
        d = fill(d, grid); out[c] = {k: base[k] + d.get(k, 0.0) for k in grid}
    return out

def build_field(gx_path, gy_path, *more_gy, glyph_rows=True):
    """gx = the x displacement on rows, gy (one or more files) = the y displacement on columns; extra gy files add columns (the
    drag-mid label field has its lens ends in a separate file). glyph_rows=False: no label glyph mask (the label-portal gratings)."""
    gx, gy = load_profiles(gx_path), load_profiles(gy_path)
    rows = {}   # signed y offset → chan → {s: u}  (x displacement along x); rows are kept by their signed offset: the chromatic
    cols = {}   # signed x offset → chan → {s: u}  (y displacement along y)   (R / B) offsets differ top vs bottom
    for off, chans in gx["profiles"].items():
        for c, t in profiles_of(chans, off if glyph_rows else 99.0).items(): rows.setdefault(off, {}).setdefault(c, []).append(t)
    for gpath in (gy_path,) + more_gy:
        g = gy if gpath == gy_path else load_profiles(gpath)
        for off, chans in g["profiles"].items():
            for c, t in profiles_of(chans, 99.0).items(): cols.setdefault(off, {}).setdefault(c, []).append(t)   # columns never cross the label
    def merge(groups):
        out = {}
        for off, chans in groups.items():
            out[off] = {}
            for c, lst in chans.items():
                keys = set().union(*[set(l) for l in lst]); out[off][c] = {k: statistics.mean([l[k] for l in lst if k in l]) for k in keys}
        return out
    return {"gx": gx, "gy": gy, "rows": merge(rows), "cols": merge(cols), "half": (gx["half"], gy["half"]), "files": [os.path.basename(f) for f in (gx_path, gy_path) + more_gy]}

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

# ---------- formula (decompiled): QuartzCore default.metallib, remote-ref/glass-displacement-formula.md ----------
# Sources of every number below: glass-displacement-formula.md §1 (UberShader::sdf_glass_displacement — the CASDFGlassDisplacementEffect
# map), §2 (displacement_map_lpf: sampling offset = inputAmount × D, amount in layer pt), §3 (glass_background_base: inner refraction
# with the same quarter-circle profile; compute_sdf_with_mode: d = shape SDF, gradient ovalization g = normalize(mix(box normal,
# normalize((x, hw·y/hh)), w))); the layer parameters are the probe's in-process readings, seg-lens-refraction.md §1b (A9):
# BackdropView displacementMap +9 / SDF height 36 / element = lens bounds, cornerRadii 22, gradientOvalization 0.5 / effectOffset 0 /
# maskOffset 0 / curvature 1 / angle 0; ClearGlass −17.5 / 11.2 (same element values); ContentLensing −8.8 / 7.04; glassBackground
# inner refraction −6.6 / height 4.4 (seg-lift-material.md §2, glass-displacement-formula.md §4).
try:
    import numpy as np
    from scipy.ndimage import gaussian_filter1d
except ImportError:  # the measured-resampling mode does not need numpy / scipy
    np = gaussian_filter1d = None

def capsule_sdf(x, y, hw, hh, r):
    """rounded-rectangle SDF (negative inside; r = hh → capsule) and its outward unit normal ('box normal': axis-aligned on the straight
    sides, radial from the corner centre in the corner zones). compute_sdf_with_mode's supercircle degenerates to this rounded
    rectangle for r = h/2 (glass-displacement-formula.md §3)."""
    qx = np.abs(x) - (hw - r); qy = np.abs(y) - (hh - r)
    ox = np.maximum(qx, 0); oy = np.maximum(qy, 0)
    d = np.hypot(ox, oy) + np.minimum(np.maximum(qx, qy), 0) - r
    nx = np.where(qx > 0, ox, 0.0) * np.sign(x); ny = np.where(qy > 0, oy, 0.0) * np.sign(y)
    inside = (qx <= 0) & (qy <= 0)
    nx = np.where(inside, np.where(qx > qy, np.sign(x), 0.0), nx); ny = np.where(inside, np.where(qx > qy, 0.0, np.sign(y)), ny)
    n = np.hypot(nx, ny); n = np.where(n == 0, 1.0, n)
    return d, nx / n, ny / n

def ovalized_gradient(x, y, nx, ny, hw, hh, w):
    """compute_sdf_with_mode (formula.md §3): g = normalize(mix(box normal, normalize((x, hw·y/hh)), w)); w = CASDFElementLayer
    .gradientOvalization (0.5 on the lens elements, A9 表 1 #13 / #19)"""
    rx = x; ry = hw * y / hh; rn = np.hypot(rx, ry); rn = np.where(rn == 0, 1.0, rn); rx, ry = rx / rn, ry / rn
    gx = nx + (rx - nx) * w; gy = ny + (ry - ny) * w; gn = np.hypot(gx, gy); gn = np.where(gn == 0, 1.0, gn)
    return gx / gn, gy / gn

def one_minus_p(t, curvature):
    """sdf_glass_displacement (formula.md §1): t = saturate(−e/H); P = mix(t < 1 ? 1 − 0.2929 : 1, sqrt(1 − (1 − t)²), curvature);
    the map carries dir × (1 − P) — 1 at the edge, 0 at depth H (curvature 1: a quarter-circle profile)"""
    t = np.clip(t, 0, 1); circ = np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1)); flat = np.where(t < 1, 1 - 0.2929, 1.0)
    return 1 - (flat + (circ - flat) * curvature)

def layer_disp(x, y, layer):
    """sampling offset (pt) of one displacement layer at (x, y): amount × R(angle)·g × (1 − P(t)), t = saturate(−(d + effectOffset)/H).
    layer = {amount, height, shape: (hw, hh, r), oval, curvature, effect_offset, angle}. Outside the shape (d > 0) t = 0 and the
    shader still writes dir × 1 (its coverage channel, not the vector, removes those pixels) — kept as is: the lens clip does the same."""
    hw, hh, r = layer["shape"]
    d, nx, ny = capsule_sdf(x, y, hw, hh, r); gx, gy = ovalized_gradient(x, y, nx, ny, hw, hh, layer["oval"])
    if layer.get("angle", 0.0):
        c, s_ = math.cos(layer["angle"]), math.sin(layer["angle"]); gx, gy = gx * c - gy * s_, gx * s_ + gy * c
    e = d + layer.get("effect_offset", 0.0); t = np.clip(-e / layer["height"], 0, 1)
    amp = layer["amount"] * one_minus_p(t, layer.get("curvature", 1.0))
    return amp * gx, amp * gy, d

def compose_layers(x, y, layers):
    """total sampling offset u(p) of a stack: layers in SAMPLING order (the first entry is the layer on top, which samples first):
    u = Δ₁(p) + Δ₂(p + Δ₁(p)) + …  (content shown at p lies at p + u)"""
    px, py = np.array(x, float), np.array(y, float)
    for L in layers:
        dx, dy, _ = layer_disp(px, py, L); px = px + dx; py = py + dy
    return px - np.array(x, float), py - np.array(y, float)

def rect_coverage(x, y, hw, hh, px_per_pt):
    """anti-aliased coverage of an axis-aligned rectangle |x| ≤ hw, |y| ≤ hh (1 map pixel wide edge)"""
    fw = 1.0 / px_per_pt
    return np.clip((hw - np.abs(x)) / fw + 0.5, 0, 1) * np.clip((hh - np.abs(y)) / fw + 0.5, 0, 1)

def compose_stages(x, y, layers, box, px_per_pt, source_rect=None):
    """the label / backdrop stack the way CoreAnimation renders it (glass-displacement-formula.md §2): each stage's filter acts on
    its own layer image (clipped first: transparent outside the layer's mask), samples it with clamp_to_edge (a coordinate beyond
    the texture replicates the edge pixel: here the sample position is clamped to the texture box), and multiplies its output by
    its effect shape's coverage (the map's B channel). layers in sampling order; box = (hw, hh) of every stage's texture (the lens
    layer); source_rect = (hw, hh) of the LAST stage's source content when it is smaller than the box (the ContentLensing
    portal 196×28: transparent around it) or None. Returns (u_x, u_y, B) at (x, y): u = clamped final sample − p, B = the product
    of the coverages met on the way (0 where any stage's output is transparent)."""
    hw, hh = box
    px_, py_ = np.array(x, float), np.array(y, float); B = np.ones_like(px_)
    for i, L in enumerate(layers):
        # this stage's output at its own pixel (px_, py_) = its source sampled at (px_ + Δ) × its coverage at (px_, py_)
        _, _, d_here = layer_disp(px_, py_, L); B = B * coverage(d_here, px_per_pt)
        dx, dy, _ = layer_disp(px_, py_, L); px_ = px_ + dx; py_ = py_ + dy
        if i == 0 and source_rect is not None:                       # the first stage's source content sits in a smaller rectangle (the portal)
            B = B * rect_coverage(px_, py_, source_rect[0], source_rect[1], px_per_pt)
        half = 0.5 / DEVICE_PX[0]                                        # §4b.1 A: uv′ = min(clamp, ·), clamp = the last valid texel's centre (½ device px inside the box), then clamp_to_edge
        px_ = np.clip(px_, -hw + half, hw - half); py_ = np.clip(py_, -hh + half, hh - half)
    return px_ - np.array(x, float), py_ - np.array(y, float), B

def coverage(d, px_per_pt):
    """the map's third channel (formula.md §1 / §4b.1 D: cov = saturate(0.5 − d/fw), fw = one device pixel of the native rendering
    (DEVICE_PX, 3× → ⅓ pt); px_per_pt (the map's own resolution) is not the AA width"""
    fw = 1.0 / DEVICE_PX[0]
    return np.clip(-d / fw + 0.5, 0, 1)

def render_formula(path, w_pt, h_pt, layers, px, scale, margin=0.0, source_rect=None, base=None):
    """rasterise the stack of `layers` (sampling order) on the w×h pt lens box at px pixels per pt (margin: extra pt around it,
    0 by default — the samples are clamped to the box like the native textures): R = u_x, G = u_y (byte = 128 + round(u·255/scale)),
    B = the coverage product of compose_stages (the filter multiplies its output by it), A 255.
    base = (bw, bh): the stack is the bw×bh model lens (220×44 r22, portal 196×28) scaled to w×h by the lens's presentation
    transform (seg-lens-refraction.md §1c(d): the flex scale sits on _UILiquidLensView alone, every layer below keeps its model
    bounds and transform) — the field is computed at the unscaled point and its offsets scaled back: u(p) = S·u₀(S⁻¹p)."""
    w, h = int(round((w_pt + 2 * margin) * px)), int(round((h_pt + 2 * margin) * px))
    xs = (np.arange(w) + 0.5) / px - w_pt / 2 - margin; ys = (np.arange(h) + 0.5) / px - h_pt / 2 - margin
    X, Y = np.meshgrid(xs, ys)
    if base:
        sx, sy = w_pt / base[0], h_pt / base[1]
        ux, uy, B = compose_stages(X / sx, Y / sy, layers, (base[0] / 2, base[1] / 2), px, source_rect); ux, uy = ux * sx, uy * sy
    else:
        ux, uy, B = compose_stages(X, Y, layers, (w_pt / 2, h_pt / 2), px, source_rect)
    peak = float(max(np.abs(ux).max(), np.abs(uy).max()))
    if peak > scale / 2: raise ValueError(f"displacement {peak:.2f} pt does not fit scale {scale}")
    ux, uy = engine_fix(ux), engine_fix(uy)
    R = np.clip(np.rint(128 + ux * 255 / scale), 0, 255).astype(np.uint8); G = np.clip(np.rint(128 + uy * 255 / scale), 0, 255).astype(np.uint8)
    Bb = np.rint(np.clip(B, 0, 1) * 255).astype(np.uint8); A = np.full_like(R, 255)
    rows = [bytes(np.stack([R[j], G[j], Bb[j], A[j]], axis=1).reshape(-1)) for j in range(h)]
    write_png(path, w, h, rows); return w, h, peak


def render_aberration(path, w_pt, h_pt, ab, edge, px, scale, oval, margin, sign=1.0, base=None, wh=None):
    """glassForeground's spectral sampling span, formula.md §3b second version (the lens's own keys): the aberration vector is NOT along
    the normal — the IR swaps the two lanes of the rotated gradient and divides each by the source surface's W, H (§3b.3):
    Δ = amount · ( (W/H)·(R(θ)g).y , (H/W)·(R(θ)g).x ) · envelope, R(θ)g = (g.x cosθ − g.y sinθ, g.x sinθ + g.y cosθ), θ = −15°,
    amount +2.3158, height 0; the envelope e = the edge factor (§3b.5, closed). W/H = the foreground's capture box = the layer frame
    + marginWidth 100 on every side, clamped to the screen (§3b.6: drag-mid x 110–330 → 10–430 = 420 × 244 → 1.72; lifted in place
    x 10–230 → 0–330 = 330 × 244 → 1.35) — it changes with the lens's screen position, so the MAP stores the ratio-1 vector
    (wh = 1.0: Δ = amount · ((R(θ)g).y, (R(θ)g).x) · e) and the filter's feColorMatrix `<fid>-wh` multiplies R by W/H and G by H/W
    per frame (filter_aberration). Files: <path> with R/G = Δ (pt, byte = 128 + Δ·255/scale) and B = the edge-band factor
    op = saturate((d − edge_start)/(edge_end − edge_start)) mixed between the edge opacities — the filter uses B (e, the formula)
    or 1 − B (the IR-literal switch), A 255. Stretched sets: the model lens scaled like the other stages (base)."""
    w, h = int(round((w_pt + 2 * margin) * px)), int(round((h_pt + 2 * margin) * px))
    xs = (np.arange(w) + 0.5) / px - w_pt / 2 - margin; ys = (np.arange(h) + 0.5) / px - h_pt / 2 - margin
    X, Y = np.meshgrid(xs, ys)
    sx, sy = (w_pt / base[0], h_pt / base[1]) if base else (1.0, 1.0)
    Xm, Ym = X / sx, Y / sy; hw, hh, r = lens_shape(base[0], base[1]) if base else lens_shape(w_pt, h_pt)
    d, nx, ny = capsule_sdf(Xm, Ym, hw, hh, r); gx, gy = ovalized_gradient(Xm, Ym, nx, ny, hw, hh, oval)
    amount, height, offset, angle = ab
    c, s_ = math.cos(angle), math.sin(angle); rx, ry = gx * c - gy * s_, gx * s_ + gy * c        # R(θ)·g, screen y down
    ratio = wh if wh else 1.0                                                                       # 1.0: W/H is applied by the filter (§3b.6, per position)
    dirx, diry = ratio * ry, rx / ratio                                                             # lanes swapped, × W/H and × H/W (§3b.3)
    # amplitude: t_a = saturate((−d − offset)/height) with the lens's inputAberrationOffset 24.444 (data session, 140-key read) is 0
    # everywhere inside (−d ≤ 22 < 24.444) → amt_a = amount = 2.3158, a constant; the spatial envelope is the edge factor itself:
    # e = saturate((d − edge_start)/(edge_end − edge_start)) with EdgeOpacityStart 1 / End 0 → out ×= 1 − mix(1, 0, e) = e — 1 at the edge,
    # 0 at 8.8 pt inside (formula.md §3b.5 closed 2026-09-19; the check y634 6.4 / 9.6 / 12.8 pt from the end → e .55 / .18 / 0 vs the
    # measured |R−G| .32 / .145 / .017). The same e is the map's B channel = the filter's band mask.
    t = np.clip((-d - offset) / height, 0, 1) if height > 0 else np.zeros_like(d)
    amt = amount * (1 - np.sqrt(np.clip(t * (2 - t), 0, 1)))
    e0, e1, o0, o1 = edge; e = np.clip((d - e0) / (e1 - e0), 0, 1); op = 1 - (o0 + (o1 - o0) * e)    # the visible factor 1 − mix(start, end, e)
    dx, dy = sign * amt * op * dirx * sx, sign * amt * op * diry * sy                               # Δ = amount · swapped direction · e (pt, screen)
    peak = float(max(np.abs(dx).max(), np.abs(dy).max()))
    if peak > scale / 2: raise ValueError(f"aberration span {peak:.2f} pt does not fit scale {scale}")
    if peak > margin: raise ValueError(f"aberration span {peak:.2f} pt exceeds the margin {margin}")
    R = np.clip(np.rint(128 + dx * 255 / scale), 0, 255).astype(np.uint8); G = np.clip(np.rint(128 + dy * 255 / scale), 0, 255).astype(np.uint8)
    B = np.rint(np.clip(op, 0, 1) * 255).astype(np.uint8)
    # A = the lens's coverage (formula.md §3b: out.a = α_elem · cov · ΣA/7 — the foreground's output exists only inside the capsule; the
    # wrapper reaches `margin` pt beyond it so the taps can READ the page there, but nothing is drawn there). Read in the screen frame
    # of the (possibly stretched) set: d of the model × the stretch of the axis the point lies on is within a device pixel of the true one.
    A = np.rint(coverage(d * np.where(np.abs(nx) > np.abs(ny), sx, sy), px) * 255).astype(np.uint8)
    rgba = np.stack([R, G, B, A], axis=2); LAST_AB_MAP[0] = (rgba, margin, px)
    write_png(path, w, h, [bytes(rgba[j].reshape(-1)) for j in range(h)]); return w, h, peak, [path]

LAST_AB_MAP = [None]   # (rgba, margin, px) of the last fringe map rendered — cropped for the end chains (write_ab_end_crops)
END_BOX = [56.0, 4.0]   # --ab-end / --ab-reach: the end chains' VISIBLE width in pt (the wrapper margin 16 + the arc's band reach 22 + 8.8 + the taps' reach 4 → 51, 56 with slack) and the extra
                        # reach of the filtered box beyond it (the taps of the last visible column read this far; clipped away after the filter)
def write_ab_end_crops(out_dir, name, w, h):
    """the fringe map cropped to the two END elements (README §0.8.5, (a)): the left box = lens x ∈ [−margin, END_BOX − margin], the right
    box mirrored, both the full wrapper height; the same bytes as the full map at those pixels (1 px/pt: integer boxes) → <name>-f-abe-<w>-{l,r}.png"""
    rgba, margin, px = LAST_AB_MAP[0]; ew = int(round((END_BOX[0] + END_BOX[1]) * px)); H, W = rgba.shape[:2]
    files = []
    for side, x0 in (("l", 0), ("r", W - ew)):
        crop = rgba[:, x0:x0 + ew]; path = os.path.join(out_dir, f"{name}-f-abe-{w}-{side}.png")
        write_png(path, ew, H, [bytes(crop[j].reshape(-1)) for j in range(H)]); files.append(os.path.basename(path))
    return files

def wh_matrix(wh):
    """feColorMatrix values applying the foreground capture box's W/H to the ratio-1 fringe map: R' = wh·(R − ½) + ½ (Δx × W/H),
    G' = (G − ½)/wh + ½ (Δy × H/W), B (the band factor) and A untouched — formula.md §3b.3 lanes, §3b.6 the box"""
    return f"{wh:g} 0 0 0 {0.5 * (1 - wh):g}  0 {1 / wh:g} 0 0 {0.5 * (1 - 1 / wh):g}  0 0 1 0 0  0 0 0 1 0"

def filter_inner_shadow(name, opacity=0.06, offset=7.0, radius=3.0):
    """B6-c (2026-09-19): the ClearGlass inner shadow layer #21 (keys seg-lens-refraction.md §1c(b): invertsShadow 1, shadowPathIsBounds 1, black
    shadowOpacity .06, shadowRadius 3, shadowOffset (0, 7)) drawn as QuartzCore rasterises it — keyfill-highlight.md §5.2c (emit_shadow_path
    0x1c3ad0d3c, closed form fixed by the data session's four sdfset variants A / R / O / P): α(p) = op · M(p) · blur_σ(M − M↓offset)(p), M = the
    capsule mask, σ = shadowRadius in pt (predict-seg-hold.md §0d: gaussian_vimage_8, σ = radius, offset a float, opacity without another factor)
    — the band the shape leaves when its own copy is moved down by the offset, blurred, clipped back to the shape; NOT the complement blurred
    (CSS inset box-shadow: that gives .059 on the top row where the raster reads .033). Apply to a black capsule element of the lens box
    (background #000, border-radius r): the output is the shadow alone (the source's own fill is not emitted). Top edge, straight run:
    I(y) = op · [Φ((y_top + off − y)/σ) − Φ((y_top − y)/σ)] → rows 602…613 = .033 .039 .044 .045 .044 .039 .033 .026 .019 .012 .007 .004 (§5.2c
    table, measured ≤ .004 off from 603). The lift: offset, opacity and radius ride the lift curve (§1c(b)) — set dy = off·p, stdDeviation = σ·p,
    slope = op·p per frame (or opacity × p on the element)."""
    fid = f"{name}-lens-f-ish"
    return f"""  <filter id="{fid}" x="-25%" y="-25%" width="150%" height="150%" color-interpolation-filters="sRGB" data-op="{opacity:g}" data-offset="{offset:g}" data-sigma="{radius:g}">
    <!-- #21 inner shadow, keyfill-highlight.md §5.2c: op · M · blur_σ(M − M↓off), op {opacity:g} / offset (0, {offset:g}) / σ = shadowRadius {radius:g} pt; M = the element's own alpha (the capsule) -->
    <feOffset in="SourceAlpha" dx="0" dy="{offset:g}" result="moff"/>
    <feComposite in="SourceAlpha" in2="moff" operator="out" result="band"/>
    <feGaussianBlur in="band" stdDeviation="{radius:g}" result="blur"/>
    <feComposite in="blur" in2="SourceAlpha" operator="in" result="clip"/>
    <feComponentTransfer in="clip" result="alpha"><feFuncA type="linear" slope="{opacity:g}" intercept="0"/></feComponentTransfer>
    <feFlood flood-color="#000" flood-opacity="1" result="black"/>
    <feComposite in="black" in2="alpha" operator="in"/>
  </filter>"""


def filter_aberration_lean(fid, hrefs, w, h, scale, margin, note, alpha_elem, edr, wh, taps, end_box=None):
    """The same chain as filter_aberration (mode flip) with the SAME output and fewer pixels / passes (2026-09-19, 监督局: the dispersion layer
    alone costs 19 ms per frame on the phone — data session 36916a9). Band-only computation is NOT available in WebKit: a filter primitive's
    own subregion (x/y/width/height, primitiveUnits objectBoundingBox or userSpaceOnUse) renders the subregion blank / the element blank
    (calib/webkit-primitive-subregion.html), so every primitive runs over the whole filter region. What is cut, exactly: (1) the k = 0 tap is
    the source itself — its feDisplacementMap (scale 0) goes, SourceGraphic feeds its two matrices (7 → 6 displacement passes); (2) the
    wrapper margin (the maps of this chain, <name>-f-abl-<w>.png, are rendered with --abl-margin, 8 pt: the taps reach at most the map's
    peak × W/H ≈ 2.3 × 1.72 = 4 pt, README §0.5), so the filter region shrinks from (w + 32) × (h + 32) to (w + 16) × (h + 16) — the page
    lays the wrapper out with AM = the margin of the chain it uses. Kept: the ΣA/7 alpha chain (exactness where a tap reads a transparent
    pixel; folding α/7 into the colour matrices would cost ±3 levels of 8-bit premultiplied precision — measured, not done)."""
    box = f' data-box="{end_box[0]:g}x{end_box[1]:g}" data-reach="{end_box[2]:g}"' if end_box else ""
    out = [f'  <filter id="{fid}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB" data-s="{scale:g}" data-wh="{wh:g}" data-lean="1" data-margin="{margin:g}"{box}>',
           (f"    <!-- {note}; apply to the END element of {end_box[0]:g}×{end_box[1]:g} pt (its own filter region); LEAN chain, README §0.8.5 -->" if end_box else
            f"    <!-- {note}; LEAN chain (same output: 6 displacement passes, the k = 0 tap is the source; margin {margin:g} pt — README §0.8.4); apply to the wrapper of {w + 2 * margin:g}×{h + 2 * margin:g} pt = the lens {w:g}×{h:g} plus {margin:g} pt on every side (AM = {margin:g}) -->"),
           f'    <feImage href="{hrefs[0]}" preserveAspectRatio="none" result="abmap"/>',
           f'    <feColorMatrix in="abmap" id="{fid}-wh" type="matrix" values="{wh_matrix(wh)}" result="abwh"/>',
           '    <feColorMatrix in="abmap" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 1 0 0" result="mask"/>',
           '    <feColorMatrix in="abmap" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cov"/>']
    for i, (k, sg) in enumerate(taps):
        wr = k / 2 if sg > 0 else 0.0; wg = (1 - k) / 3; wb = k / 2 if sg < 0 else 0.0
        src = "SourceGraphic" if k == 0 else f"t{i}"
        if k != 0: out.append(f'    <feDisplacementMap in="SourceGraphic" in2="abwh" scale="{sg * k * scale:g}" xChannelSelector="R" yChannelSelector="G" result="t{i}"/>')
        out.append(f'    <feColorMatrix in="{src}" type="matrix" values="{wr:g} 0 0 0 0  0 {wg:g} 0 0 0  0 0 {wb:g} 0 0  0 0 0 1 0" result="w{i}"/>')
        out.append(f'    <feColorMatrix in="{src}" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 {1 / 7:g} 0" result="a{i}"/>')
    prev, preva = "w0", "a0"
    for i in range(1, len(taps)):
        out.append(f'    <feComposite in="{prev}" in2="w{i}" operator="arithmetic" k1="0" k2="1" k3="1" k4="0" result="s{i}"/>'); prev = f"s{i}"
        out.append(f'    <feComposite in="{preva}" in2="a{i}" operator="arithmetic" k1="0" k2="1" k3="1" k4="0" result="sa{i}"/>'); preva = f"sa{i}"
    out += [f'    <feColorMatrix in="{prev}" type="matrix" values="{edr:g} 0 0 0 0  0 {edr:g} 0 0 0  0 0 {edr:g} 0 0  0 0 0 {alpha_elem:g} 0" result="fge"/>',
            f'    <feComposite in="fge" in2="{preva}" operator="in" result="fgc"/>', '    <feComposite in="fgc" in2="mask" operator="in" result="fgb"/>',
            '    <feComposite in="fgb" in2="cov" operator="in" result="fg"/>',
            '    <feComposite in="SourceGraphic" in2="cov" operator="in" result="srcc"/>',
            '    <feComposite in="fg" in2="srcc" operator="over"/>', "  </filter>"]
    return "\n".join(out)


def filter_aberration(fid, hrefs, w, h, scale, mode, margin, note, alpha_elem=1.0, edr=1.0, wh=1.72, peak=0.0, lean=False, end_box=None):
    """glass_foreground_base's 7-tap spectral chain (formula.md §3b) on SourceGraphic = the wrapper of the lens content extended by
    `margin` pt (the two displaced layers over a plain copy of the page, so the outward taps read the page beyond the lens like the
    foreground's backdrop capture): k = 1, 2/3, 1/3 at +kΔ: R += r·k, G += g·(1 − k); k = 0, 1/3, 2/3, 1 at −kΔ: G += g·(1 − k),
    B += b·k; out = (R/2, G/3, B/2) × ΣA/7 × band mask, composited over the content. Each tap is a feDisplacementMap on the Δ map
    with scale ±k·S, its channels weighted by feColorMatrix, summed by feComposite arithmetic; the taps' alphas / 7 are summed the
    same way for ΣA/7. Band mask = B of the map: mode 'flip' = op (the outer band), mode 'ir' = 1 − op (the IR-literal interior).
    The map holds the ratio-1 vector; `<fid>-wh` (feColorMatrix, data-wh) applies W/H of the foreground's capture box — the lens
    frame + 100 pt on every side clamped to the screen (§3b.6): the page sets its values per frame with wh_matrix(W/H); `wh` is the
    value written (1.72 = the drag-mid position on the 440-pt screen, the position of every verification frame). The `in` with the
    band factor e followed by `over` IS §3b.6's blend screen = e·dispersed + (1 − e)·below (fg's alpha = e after the `in`)."""
    if peak and peak * max(wh, 1 / wh) > scale / 2: raise ValueError(f"fringe span {peak:.2f} × W/H {wh:g} does not fit scale {scale}")
    taps = [(1.0, 1), (2 / 3, 1), (1 / 3, 1), (0.0, -1), (1 / 3, -1), (2 / 3, -1), (1.0, -1)]
    if lean: return filter_aberration_lean(fid, hrefs, w, h, scale, margin, note, alpha_elem, edr, wh, taps, end_box)
    out = [f'  <filter id="{fid}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB" data-s="{scale:g}" data-wh="{wh:g}">',
           f"    <!-- {note}; band mask: {mode}; apply to the wrapper of {w + 2 * margin:g}×{h + 2 * margin:g} pt = the lens {w:g}×{h:g} plus {margin:g} pt on every side; W/H = capture box (lens frame + 100 pt each side, clamped to the screen) / its height, set #{fid}-wh per frame: R×wh + ½(1−wh), G×1/wh + ½(1−1/wh) (formula.md §3b.6: 1.72 at x 110–330, 1.35 at x 10–230) -->",
           f'    <feImage href="{hrefs[0]}" preserveAspectRatio="none" result="abmap"/>',
           f'    <feColorMatrix in="abmap" id="{fid}-wh" type="matrix" values="{wh_matrix(wh)}" result="abwh"/>',
           '    <feColorMatrix in="abmap" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 1 0 0" result="mask"/>' if mode == "flip" else
           '    <feColorMatrix in="abmap" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 -1 0 1" result="mask"/>']   # ir = the formula's 1 − op (§3b.2); flip = op, the switch
    for i, (k, sg) in enumerate(taps):
        wr = k / 2 if sg > 0 else 0.0; wg = (1 - k) / 3; wb = k / 2 if sg < 0 else 0.0
        out.append(f'    <feDisplacementMap in="SourceGraphic" in2="abwh" scale="{sg * k * scale:g}" xChannelSelector="R" yChannelSelector="G" result="t{i}"/>')
        out.append(f'    <feColorMatrix in="t{i}" type="matrix" values="{wr:g} 0 0 0 0  0 {wg:g} 0 0 0  0 0 {wb:g} 0 0  0 0 0 1 0" result="w{i}"/>')
        out.append(f'    <feColorMatrix in="t{i}" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 {1 / 7:g} 0" result="a{i}"/>')
    prev, preva = "w0", "a0"
    for i in range(1, len(taps)):
        out.append(f'    <feComposite in="{prev}" in2="w{i}" operator="arithmetic" k1="0" k2="1" k3="1" k4="0" result="s{i}"/>'); prev = f"s{i}"
        out.append(f'    <feComposite in="{preva}" in2="a{i}" operator="arithmetic" k1="0" k2="1" k3="1" k4="0" result="sa{i}"/>'); preva = f"sa{i}"
    # §3b: out.rgb = (R/2, G/3, B/2) × α_elem × cov × ΣA/7 × edr, out.a = α_elem × cov × ΣA/7, then source-over the content below.
    # The colour sum (alpha clamped to 1) × edr on its colour and × α_elem on its alpha (feColorMatrix, unpremultiplied), then `in`
    # with ΣA/7 and with the band mask (cov = the lens clip), then `over`. α_elem and edr are 1 until the old page reads them.
    out += [f'    <feColorMatrix in="{prev}" type="matrix" values="{edr:g} 0 0 0 0  0 {edr:g} 0 0 0  0 0 {edr:g} 0 0  0 0 0 {alpha_elem:g} 0" result="fge"/>',
            f'    <feComposite in="fge" in2="{preva}" operator="in" result="fgc"/>', '    <feComposite in="fgc" in2="mask" operator="in" result="fgb"/>',
            '    <feColorMatrix in="abmap" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cov"/>',   # A = the lens coverage: §3b out.a = α_elem·cov·ΣA/7 — nothing outside the capsule (the wrapper's margin is read, not drawn)
            '    <feComposite in="fgb" in2="cov" operator="in" result="fg"/>',
            '    <feComposite in="SourceGraphic" in2="cov" operator="in" result="srcc"/>',   # the wrapper's own output is the capsule too: its margin copy is READ by the taps, never shown (the real page shows there)
            '    <feComposite in="fg" in2="srcc" operator="over"/>', "  </filter>"]
    return "\n".join(out)

R_MAX = [22.0]   # the lens's corner radius cap: 22 for the segment lens (--corner-radius 22), h/2 for the tab bar's (--corner-radius half)
DEVICE_PX = [3.0]   # device pixels per pt of the native rendering (3× phone): the coverage's 1-px anti-alias width (formula.md §4b.1 D:
                    # cov = saturate(.5 − d/fw), fw = 1 px) and the sampler's clamp to the LAST TEXEL CENTRE (§4b.1 A: clamp = (size − .5)/texsize)
ENGINE_FIX = [0.0]   # --engine-fix: 引擎校正, default 0 = off. WebKit's feDisplacementMap applies a NEGATIVE displacement one filter pixel short
                     # (calib/, 2026-09-19: Mac WebKit 2× buffer ½ CSS px: −1 → −0.5, −4 → −3.5; iOS simulator 3×: ⅓ px: −1 → −0.67, −4 → −3.67;
                     # positive values exact / rounded up). A value here (pt) is subtracted from every negative u before encoding so the
                     # engine lands on the intended value; it is the engine's pixel (0.5 on a 2× buffer, 0.333 at 3×), not an Apple value.

def engine_fix(u):
    """the optional engine correction (ENGINE_FIX, default off): negative displacements pre-extended by the engine's pixel"""
    k = ENGINE_FIX[0]
    return u if not k else np.where(u < 0, u - k, u)

def lens_shape(w, h, r_max=None):
    """(hw, hh, r): the lens capsule; segment lens r = min(22, h/2): DestOut cornerRadius stays 22 through the drag
    (uiprobe-motion-segdragmid lenstrace), CoreAnimation clamps a radius above h/2; tab bar lens r = h/2 (tab-lens-native.md §0:
    cornerRadii 35 ×4 = 70/2 on every element, DestOut cornerRadius 35)"""
    r_max = R_MAX[0] if r_max is None else r_max
    return (w / 2, h / 2, min(r_max, h / 2))

def drag_frames(paths):
    """(w, h) of the lifted lens in every recorded DRAG frame: seg-native-abc-frames.json (phase 'drag', _UILiquidLensView#0) and
    uiprobe-motion-segdragmid-*.json (lenstrace entries between the lift settling at 220×44 and the release)"""
    pts = []
    for p in paths:
        d = json.load(open(p))
        if "frames" in d:
            for f in d["frames"]:
                if f.get("phase") != "drag": continue
                for l in f["lens"]:
                    if l["view"].endswith("#0") and l["alpha"] > 0: pts.append((float(l["rect"][2]), float(l["rect"][3]), os.path.basename(p)))
        elif "entries" in d:
            ent = [e for e in d["entries"] if e.get("kind") == "lenstrace"]; started = False
            for e in ent:
                r = e["lensPres"]
                if not started and abs(r[2] - 220) < 0.05 and abs(r[3] - 44) < 0.05: started = True; continue
                if started:
                    if e.get("destOut.cornerRadius", 22) < 21.99: break          # the release shrinks DestOut's radius: end of the drag
                    if abs(r[2] - 220) < 0.05 and abs(r[3] - 44) < 0.05: continue
                    pts.append((float(r[2]), float(r[3]), os.path.basename(p)))
    return sorted(pts)

def height_for_width(pts, w):
    """lens height at width w from the recorded drag frames: linear between the nearest recorded frame below and above; outside the
    recorded range the nearest frame's height (flagged 'clamped' — 采样替代)"""
    below = [p for p in pts if p[0] <= w]; above = [p for p in pts if p[0] >= w]
    if not below: return above[0][1], "clamped", [above[0]]
    if not above: return below[-1][1], "clamped", [below[-1]]
    a, b = below[-1], above[0]
    if b[0] == a[0]: return a[1], "frame", [a]
    return a[1] + (b[1] - a[1]) * (w - a[0]) / (b[0] - a[0]), "between frames", [a, b]

def filter_formula(fid, href, w, h, scale, margin, note, baked=""):
    """displacement_map_lpf in SVG: out = src(p + u(p)) × map.B — feImage (the map, stretched to the element box), feDisplacementMap on
    SourceGraphic, then feComposite `in` with the map's B channel as alpha (feColorMatrix moves B into alpha). The layer must be the
    lens box (w×h) with its own clip (capsule for the label copy — the native clips first, then displaces; the box for the copy of
    what lies under the lens) and overflow hidden: the map's samples never leave the box (clamp_to_edge baked into the map), so no
    region beyond the box is needed. Default filter region and units only: WebKit renders nothing with userSpaceOnUse regions."""
    baked_attr = f' data-baked="{baked}"' if baked else ""
    return "\n".join([f'  <filter id="{fid}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB" data-s="{scale:g}"{baked_attr}>',
                      f"    <!-- {note}; apply to the {w:g}×{h:g} pt lens layer; data-s = the encoding scale S of this set (feDisplacementMap scale = S × lift progress) -->",
                      f'    <feImage href="{href}" preserveAspectRatio="none" result="map"/>',
                      '    <feColorMatrix in="map" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 1 0 0" result="mask"/>',
                      f'    <feDisplacementMap in="SourceGraphic" in2="map" scale="{scale:g}" xChannelSelector="R" yChannelSelector="G" result="disp"/>',
                      '    <feComposite in="disp" in2="mask" operator="in"/>',
                      "  </filter>"])

def parse_layers(spec, w, h, portal=None):
    """'amount/height/oval/shape,…' in sampling order; shape = lens | portal (196×28 r0)"""
    out = []
    for part in spec.split(","):
        amount, height, oval, shape = part.split("/")
        shp = lens_shape(w, h) if shape == "lens" else (portal[0] / 2, portal[1] / 2, 0.0)
        out.append({"amount": float(amount), "height": float(height), "oval": float(oval), "shape": shp, "shape_name": shape, "curvature": 1.0, "effect_offset": 0.0, "angle": 0.0})
    return out

def verify_against(path, layers_for, depth_min=3.0, sigma=3.0, tol=0.3, glyph_rows=False, region=None, base=None, chain=None):
    """compare the formula's composite field with one measured phase file (lens_phase.py format) the way the old page's validate2.py
    does: prediction along the profile, centre value removed (the measurement's unwrap pins u(centre) ≈ 0), Gaussian σ 3 pt (the
    demodulation's own smoothing), points at depth ≥ 3 pt from the lens edge (the phase folds in the last 3 pt); a sample counts
    where its demodulation amplitude is ≥ AMP_FLOOR × the profile's median. layers_for(w, h) builds the stack for the file's lens.
    region: optional (hx, hy) — report the residual inside |x| ≤ hx, |y| ≤ hy as well.
    chain (the tab bar's lens, formula.md §5b / tab-lens-native.md §3): {lens_scale, content_scale, model_centre, platter_centre,
    period} — the screen offset s from the presented lens centre is taken to the lens's model space (s / lens_scale, the platter's
    presentation transform about platter_centre), the stages sample there with the per-stage box clamp (compose_stages), the sample
    lands in the copy of the content that is scaled content_scale about platter_centre (the SelectedContentView's subviews' lift
    transform; the PatternView's centre = platter_centre), and the measured u is read modulo the grating period, so the prediction
    is brought to the measurement by whole periods at the centre instead of being pinned to 0 there."""
    d = json.load(open(path)); axis = d["axis"]; lw, lh = float(d["lens"][2]), float(d["lens"][3])
    bw, bh = base if base else (lw, lh); sx, sy = lw / bw, lh / bh; hw, hh, r = lens_shape(bw, bh)   # the measured lens = the model scaled
    layers = layers_for(bw, bh); rows = []; over = []
    for off, chans in d["profiles"].items():
        off = float(off); p = chans["G"]; s = np.array(p["s"], float); u = np.array(p["u"], float); amp = np.array(p["amp"], float)
        x, y = (s, np.full_like(s, off)) if axis == "x" else (np.full_like(s, off), s)
        ic = int(np.argmin(np.abs(s)))
        if chain:
            ls, cs = chain["lens_scale"], chain["content_scale"]; mc, pc = chain["model_centre"], chain["platter_centre"]; period = chain.get("period", 8.0)
            mx, my = x / ls, y / ls                                                        # screen → the lens's model space (relative to the lens centre)
            ux, uy, _ = compose_stages(mx, my, layers, (hw, hh), 1.0)                       # the stages, per-stage box clamp
            qx, qy = mx + ux + mc[0], my + uy + mc[1]                                       # the sample in the platter's model space
            cx, cy = pc[0] + (qx - pc[0]) / cs, pc[1] + (qy - pc[1]) / cs                   # the copy's content is scaled cs about the platter centre
            scx, scy = pc[0] + (mc[0] - pc[0]) * ls + x, pc[1] + (mc[1] - pc[1]) * ls + y   # the screen point (presented lens centre + s)
            pred = (cx - scx) if axis == "x" else (cy - scy)
            pred = pred - period * np.round((pred[ic] - u[ic]) / period)                   # whole periods at the centre (the measurement is modulo the period)
        else:
            ux, uy = compose_layers(x / sx, y / sy, layers); ux, uy = ux * sx, uy * sy; pred = ux if axis == "x" else uy
            pred = pred - pred[ic]
        step = float(s[1] - s[0]) if len(s) > 1 else 1.0; ps = gaussian_filter1d(pred, sigma / step)
        dd, _, _ = capsule_sdf(x / sx, y / sy, hw, hh, r); depth = -dd * min(sx, sy)
        m = depth >= depth_min; med = float(np.median(amp)); m &= amp >= AMP_FLOOR[0] * med
        if glyph_rows and abs(off) < GLYPH_ROW: m &= np.abs(s) > GLYPH_HALF
        res = ps - u
        if not m.any(): continue
        rms = float(np.sqrt(np.mean(res[m] ** 2))); i = int(np.argmax(np.where(m, np.abs(res), -1)))
        row = {"offset": off, "n": int(m.sum()), "rms": round(rms, 3), "max": round(float(abs(res[i])), 3), "max_at_s": float(s[i])}
        if region:
            rm = m & (np.abs(x) <= region[0]) & (np.abs(y) <= region[1])
            if rm.any(): row["inside_rms"] = round(float(np.sqrt(np.mean(res[rm] ** 2))), 3); row["inside_max"] = round(float(np.abs(res[rm]).max()), 3); row["inside_n"] = int(rm.sum())
        rows.append(row)
        for k in np.where(m & (np.abs(res) > tol))[0]: over.append({"offset": off, "s": float(s[k]), "measured": round(float(u[k]), 2), "formula": round(float(ps[k]), 2), "residual": round(float(res[k]), 2)})
    return {"file": os.path.basename(path), "lens": [lw, lh], "axis": axis, "rows": rows, "over_tol": over,
            "rms_all": round(float(np.sqrt(np.mean([r["rms"] ** 2 for r in rows]))), 3) if rows else None, "max_all": max((r["max"] for r in rows), default=None)}

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
    """8-bit RGBA; the smallest of the PNG row filters None / Sub / Up / Paeth (the fields are smooth: Sub or Up halves the size)"""
    def filt(t):
        out = b""; prev = bytes(w * 4)
        for r in rows:
            r = bytes(r)
            if t == 0: line = r
            elif t == 1: line = bytes((r[i] - (r[i - 4] if i >= 4 else 0)) & 255 for i in range(len(r)))
            elif t == 2: line = bytes((r[i] - prev[i]) & 255 for i in range(len(r)))
            else:
                def pred(i):
                    a_ = r[i - 4] if i >= 4 else 0; b_ = prev[i]; c_ = prev[i - 4] if i >= 4 else 0; p_ = a_ + b_ - c_
                    pa, pb, pc = abs(p_ - a_), abs(p_ - b_), abs(p_ - c_)
                    return a_ if pa <= pb and pa <= pc else b_ if pb <= pc else c_
                line = bytes((r[i] - pred(i)) & 255 for i in range(len(r)))
            out += bytes((t,)) + line; prev = r
        return zlib.compress(out, 9)
    idat = min((filt(t) for t in (0, 1, 2, 4)), key=len)
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))

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

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--field", help="<gx.json>,<gy.json> the measured composite field (measured-resampling mode; verification input with --formula)")
    ap.add_argument("--formula", action="store_true", help="compute the maps from the decompiled shader formulas (README §1d); the --verify-* files are only compared against")
    ap.add_argument("--bg-layers", default="-6.6/4.4/0.5/lens,9/36/0.5/lens", help="backdrop stack in sampling order, amount/height/ovalization/shape: glass_background inner refraction −6.6 / 4.4 (sampled first) then BackdropView +9 / 36, both on the lens capsule, ovalization 0.5")
    ap.add_argument("--label-layers", default="-8.8/7.04/0.5/lens,-17.5/11.2/0.5/lens", help="label-copy stack in sampling order (the outer layer samples first): ContentLensing −8.8 / 7.04 (its image is the 196×28 portal showing the ClearGlass layer) then ClearGlass −17.5 / 11.2 (its image is the capsule-clipped segment content), both on the lens capsule")
    ap.add_argument("--series", default="196:256:2", help="lens widths lo:hi:step for the drag-stretch sets (each set's height from --frames)")
    ap.add_argument("--frames", help="recorded drag lens frames: seg-native-abc-frames.json,uiprobe-motion-segdragmid-light.json (width → height)")
    ap.add_argument("--name", default="seg", help="file / id prefix: seg (segmented control) → seg-f-bg-<w>.png, #seg-lens-f-bg-<w>; tab (tab bar) → tab-f-bg-<w>.png, #tab-lens-f-bg-<w>")
    ap.add_argument("--lift-path", default="", help="WxH of the resting lens for sets narrower than --size: those are the LIFT path (both dimensions grow by the same amount to --size, model bounds change, r = h/2, the SDF heights stay), e.g. 94x54 for the tab bar; sets wider than --size are the stretched model")
    ap.add_argument("--href-prefix", default="assets/lens/", help="path of the map files as index.html sees them (lens-filter.svg); lens-test.html uses bare file names")
    ap.add_argument("--margin", type=float, default=0.0, help="extra pt of map around the lens box (0: the maps are the lens box; samples are clamped to it like the native textures)")
    ap.add_argument("--aberration", default="2.3158/0/24.444/-0.2618", help="glassForeground spectral sampling amount/height/offset/angle — the lens's own keys (seg-lens-refraction.md §1c(a), the 140-key read): inputAberrationAmount 2.3158, Height 0, Offset 24.444 (t_a = 0 inside → the amount is constant), Angle −0.2618 rad; → seg-f-ab-<w>.png; 'off' = none")
    ap.add_argument("--ab-sign", type=float, default=1.0, help="verification switch for the fringe: +1 = as read (Δ = amt_a·g with amt_a −15 and g outward: the +kΔ taps that feed R sample INWARD); −1 = the opposite direction (R samples outward) — the A1 PNG's hue order (red at the rim) is reproduced by −1, see README §0.5")
    ap.add_argument("--ab-alpha", type=float, default=1.0, help="α_elem of the glassForeground output (§3b out.a = α_elem·cov·ΣA/7): layer #33 opacity 1, compositingFilter normalBlendMode (§1c(a))")
    ap.add_argument("--ab-edr", type=float, default=1.0, help="the edr factor of §3b (out.rgb ×= edr): to be read by the old page; 1 until then")
    ap.add_argument("--ab-wh", type=float, default=1.72, help="W/H written into the fringe filters' colour matrix (data-wh): the foreground capture box = lens frame + 100 pt each side clamped to the screen, over its height (formula.md §3b.6: 1.72 at the drag-mid position x 110–330, 1.35 lifted in place x 10–230); the page sets it per frame")
    ap.add_argument("--ab-scale", type=float, default=0.0, help="S of the fringe maps (their own data-s; 0 = 4·ceil(amount): room for W/H up to 2·⌈amount⌉/amount)")
    ap.add_argument("--label-region", default="96x12", help="the 'inside' region reported for the label verifications: |x| ≤ hx, |y| ≤ hy (segment lens: the portal 196×28; tab lens: 28x20, the uniform-zoom zone of lens-refraction.md §0)")
    ap.add_argument("--engine-fix-sets", default="", help="also write the bg / lab maps with 引擎校正 BAKED IN, one file set per device scale: '2,3' → <name>-f-bg-<w>@2x.png (k = ½ pt) and @3x (k = ⅓ pt); the page picks the file by devicePixelRatio (lens-map-dpr.js) instead of re-encoding blob: copies at run time (lens-engine-fix.js)")
    ap.add_argument("--engine-fix", type=float, default=0.0, help="引擎校正 (default 0 = off): pt subtracted from every NEGATIVE displacement before encoding, = the engine's filter pixel that WebKit's feDisplacementMap drops on negative values (calib/: 0.5 on a 2× buffer, 0.333 at 3×); README §0.4")
    ap.add_argument("--device-px", type=float, default=3.0, help="device pixels per pt of the native rendering: the coverage's 1-px AA width and the sampler's clamp to the last texel centre (formula.md §4b.1 A / D); 3 = the phone")
    ap.add_argument("--corner-radius", default="22", help="the lens capsule's corner radius: 22 (segment lens, clamped to h/2) or 'half' (tab bar lens: h/2 on every element, tab-lens-native.md §0)")
    ap.add_argument("--verify-chain", default="", help="tab bar lens (formula.md §5b): lens_scale/content_scale/model_centre_x,y/platter_centre_x,y[/period] — the phase files are read through the platter's presentation transform (1.0516 about the platter centre) and the copy's lift scale (1.16 about the platter centre); applied to --verify-label-lift")
    ap.add_argument("--ab-end", type=float, default=56.0, help="(a) the END elements' VISIBLE width in pt for the end-only fringe chains #<name>-lens-f-abe-<w>-{l,r}: wrapper margin 16 + the arc's band reach (r 22 + envelope 8.8) + the taps' reach (peak × max W/H ≈ 4) = 50.8, 56 with slack (integer: the crop is whole map pixels)")
    ap.add_argument("--ab-reach", type=float, default=4.0, help="the end element's filtered box extends this far beyond its visible width (the last visible column's taps read it); the page clips it after the filter")
    ap.add_argument("--abl-margin", type=float, default=16.0, help="the LEAN fringe chain's wrapper margin (pt); = --ab-margin (default) → the chain reads the -f-ab- map itself, no extra file. A smaller margin (8 was tried: the taps reach ≤ peak × W/H ≈ 4 pt) writes <name>-f-abl-<w>.png at that margin, but WebKit's output then differs from the 16-pt chain by ≤ 15 levels on the ends / the bottom rim row (README §0.8.4) — not identical, so not the default")
    ap.add_argument("--ab-margin", type=float, default=16.0, help="the fringe wrapper's extension (pt) beyond the lens on every side (≥ the 15 pt span: the foreground's backdrop capture has marginWidth 100, its outward taps read the page beyond the lens)")
    ap.add_argument("--ab-px", type=int, default=1, help="pixels per pt of the fringe maps (the spans are smooth: 1 px/pt keeps the four maps per width small)")
    ap.add_argument("--edge", default="-8.8/0/1/0", help="glassForeground edge band start/end/opacityStart/opacityEnd — the lens's keys inputEdgeStart −8.8 / inputEdgeEnd 0, inputEdgeOpacityStart 1 / End 0 (data session, 140-key read) → the factor 1 − mix(start, end, e) = e is the envelope and the map's B channel")
    ap.add_argument("--label-portal", default="0", help="the ContentLensing stage's source content rectangle centred in the lens; 0 (default) = the whole lens: portal #32 does not clip (masksToBounds 0, formula.md §4b, the old page's final structure 2026-09-19); '196x28' = the earlier rule, kept for comparison")
    ap.add_argument("--verify-bg", help="measured backdrop fields to compare: gx.json,gy.json[;gx2.json,gy2.json…]")
    ap.add_argument("--verify-label-lift", help="measured label-portal fields, lifted at rest: gx.json,gy.json")
    ap.add_argument("--verify-label-drag", help="measured label-portal fields, dragged to the divider: gx.json,gy.json,gy-ends.json")
    ap.add_argument("--verify-label-mid244", help="measured label-portal fields at the stretched 244×38.4 frame: gx6.json,gy.json")
    ap.add_argument("--size", default="220x44"); ap.add_argument("--scale", type=float, default=32.0); ap.add_argument("--px", type=int, default=2)
    ap.add_argument("--stretch", action="store_true", help="the field was measured on another lens size: map it by normalised coordinates")
    ap.add_argument("--dark", help="<gx.json>,<gy.json> the same field measured in dark mode (compared, maps use --field)")
    ap.add_argument("--amp-floor", type=float, default=0.5, help="validity: amp ≥ this × median (backdrop field)")
    ap.add_argument("--label-amp-floor", type=float, default=0.25, help="validity floor for the label-portal fields (their gratings fade at the portal edges)")
    ap.add_argument("--label-lift", help="<gx.json>,<gy.json>[,<gy2.json>…] the MEASURED label-portal field, lifted state → seg-map-label-lift-{r,g,b}.png, #seg-lens-warp-label-lift")
    ap.add_argument("--label-drag", help="<gx.json>,<gy.json>[,<gy2.json>…] the MEASURED label-portal field, dragged to the divider → seg-map-label-drag-{r,g,b}.png, #seg-lens-warp-label-drag")
    ap.add_argument("--label-from-bg", help="<gain>,<band>[,<portal WxH>]: derive the label layer's maps from the backdrop field — amplitude × gain, edge band compressed × band (native ContentLensing −8.8/−17.5 = 0.503, SDF height 7.04/11.2 = 0.629); with a portal size the band sits on the portal capsule centred in the lens (196x28: inset 12 / 8) and the backdrop's uniform interior part is removed")
    ap.add_argument("--out", default=HERE)
    return ap

def main():
    ap = build_parser(); a = ap.parse_args(); W, H = (float(v) for v in a.size.lower().split("x"))
    if a.aberration != "off" and not a.ab_scale: a.ab_scale = 4.0 * math.ceil(float(a.aberration.split("/")[0]))   # own S of the fringe maps: seg 12, tab 16
    R_MAX[0] = float("inf") if a.corner_radius == "half" else float(a.corner_radius)
    DEVICE_PX[0] = a.device_px
    ENGINE_FIX[0] = a.engine_fix; END_BOX[0] = a.ab_end; END_BOX[1] = a.ab_reach
    a.S_ab = a.ab_scale
    AMP_FLOOR[0] = a.amp_floor
    if a.formula:
        if a.scale == 32.0: a.scale = 40.0   # the label stack reaches 17.5 pt at the lens edge (ClearGlass −17.5): S 40 holds ±20 pt at 0.157 pt per byte step; a set whose scaled stack exceeds that gets S 48 (main_formula)
        return main_formula(a, W, H)
    if not a.field: ap.error("--field is required without --formula")
    return main_measured(a, W, H)

def main_measured(a, W, H):
    """the earlier measured-resampling mode (README §1–§4): maps resampled from the phase files — record / checks only"""
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
    # measured label-portal fields (data session A3, seg-lens-drag-mid.md §5): resampled exactly like the backdrop, no derivation
    LF = {}
    for name, spec in (("lift", a.label_lift), ("drag", a.label_drag)):
        if not spec: continue
        AMP_FLOOR[0] = a.label_amp_floor; SYMMETRIC[0] = False; Fl = build_field(*spec.split(","), glyph_rows=False); AMP_FLOOR[0] = a.amp_floor; SYMMETRIC[0] = True; LF[name] = Fl; lm = {}; lp = 0.0
        for c in "RGB":
            p = os.path.join(a.out, f"seg-map-label-{name}-{c.lower()}.png"); _, _, pk = render(p, Fl, c, W, H, a.px, a.scale, a.stretch, 1.0); lm[c] = p; lp = max(lp, pk)
        lmaps_measured = globals().setdefault("_LM", {}); lmaps_measured[name] = (lm, lp, Fl)
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
    LM = globals().get("_LM", {})
    jump_counts = {os.path.basename(p): jumps(p) for p in list(maps.values()) + list(lmaps.values()) + [p for lm, _, _ in LM.values() for p in lm.values()]}
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
            "label_measured": {name: {"sampled_substitute": "采样替代（直量）", "files": Fl["files"], "amp_floor": a.label_amp_floor, "symmetrised": False, "measured_lens": Fl["gx"]["lens"], "rows_y": sorted(Fl["rows"]), "cols_x": sorted(Fl["cols"]), "peak_pt": round(lp, 2),
                                      "filter": f"#seg-lens-warp-label-{name}", "maps": f"seg-map-label-{name}-{{r,g,b}}.png", "source": "remote-ref/seg-lens-drag-mid.md §5 (data session A3)"} for name, (lm, lp, Fl) in LM.items()},
            "edge": "clamp-to-edge outside the capsule (the field continues from the nearest boundary point; the lens clips those pixels)",
            "jumps_ge_1.5pt_top_bottom_20px": jump_counts,
            "sources": ["remote-ref/seg-lens-refraction.md §0 §2 §2.3", "remote-ref/seg-lift-material.md §1", "remote-ref/tools/touch/seg-phase-{gx,gy}-{light,dark}.json (data session, 2026-09-19)"]}
    print(f"maps {w}×{h} px, S {a.scale:g}, peak |u| {peak:.2f} pt; interior du_x/dx {sx:+.4f} (x scale {1 / (1 + sx):.2f}), du_y/dy {sy:+.4f} (y scale {1 / (1 + sy):.3f}); jumps ≥ 1.5 pt (top/bottom 20 px): {jump_counts}")
    if lmaps: print(f"label maps (derived): gain × band {a.label_from_bg}, peak |u| {lpeak:.2f} pt")
    for name, (lm, lp, Fl) in LM.items(): print(f"label maps (measured, {name}): {', '.join(Fl['files'])}; rows {sorted(Fl['rows'])}, cols {sorted(Fl['cols'])}; peak |u| {lp:.2f} pt")
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
    for name, (lm, lp, Fl) in LM.items():
        svg += "\n" + filter_rgb(f"seg-lens-warp-label-{name}", lm, a.scale, f"LABEL LAYER, MEASURED ({name} state, 采样替代): {' + '.join(Fl['files'])} (data session A3, seg-lens-drag-mid.md §5); apply to the label copy only")
    svg += "\n</svg>\n"
    open(os.path.join(a.out, "lens-filter.svg"), "w").write(svg)
    tpl = os.path.join(HERE, "lens-test.template.html")
    if os.path.exists(tpl): open(os.path.join(a.out, "lens-test.html"), "w", encoding="utf-8").write(open(tpl, encoding="utf-8").read().replace("{{FILTER}}", svg.strip()))
    json.dump(info, open(os.path.join(a.out, "lens-field.json"), "w"), indent=1, ensure_ascii=False)
    print("filter", os.path.getsize(os.path.join(a.out, "lens-filter.svg")), "bytes")

def render_baked_sets(a, w, h, bg, lab, S_set, base_wh, portal_rect, fbg, flab):
    """--engine-fix-sets: the same bg / lab maps (this set's S) with the 引擎校正 baked in — k = 1/dpr pt taken off every negative displacement
    before encoding — as <map>@<dpr>x.png (lens-map-dpr.js picks the file by devicePixelRatio × SS; README §0.8.4)"""
    for dpr in [int(v) for v in a.engine_fix_sets.split(",") if v.strip()]:
        k0 = ENGINE_FIX[0]; ENGINE_FIX[0] = 1.0 / dpr
        try: render_formula(os.path.join(a.out, fbg.replace(".png", f"@{dpr}x.png")), w, h, bg, a.px, S_set, a.margin, None, base_wh); render_formula(os.path.join(a.out, flab.replace(".png", f"@{dpr}x.png")), w, h, lab, a.px, S_set, a.margin, portal_rect, base_wh)
        finally: ENGINE_FIX[0] = k0

def render_fringe_maps(a, w, h, base_wh):
    """the colour-fringe map of a set (<name>-f-ab-<w>.png) and the lean chain's (the same file when --abl-margin = --ab-margin; its own
    <name>-f-abl-<w>.png otherwise) → (file, peak_pt, [files], [lean files])"""
    if a.aberration == "off": return None, None, [], [], []
    fab = f"{a.name}-f-ab-{w}.png"; ab = tuple(float(v) for v in a.aberration.split("/")); edge = tuple(float(v) for v in a.edge.split("/"))
    _, _, pk_ab, fl = render_aberration(os.path.join(a.out, fab), w, h, ab, edge, a.ab_px, a.S_ab, 0.5, a.ab_margin, a.ab_sign, base_wh)
    if a.abl_margin == a.ab_margin: fll = list(fl)   # the lean chain reads the -f-ab- map (same margin → same map)
    else: _, _, _, fll = render_aberration(os.path.join(a.out, f"{a.name}-f-abl-{w}.png"), w, h, ab, edge, a.ab_px, a.S_ab, 0.5, a.abl_margin, a.ab_sign, base_wh)
    fabe = write_ab_end_crops(a.out, a.name, w, h)
    return fab, pk_ab, [os.path.basename(f) for f in fl], [os.path.basename(f) for f in fll], fabe

def main_formula(a, W, H):
    """--formula: maps computed from the decompiled formulas (no measured field in any map); one set per lens width for the drag"""
    portal = (196.0, 28.0)
    lo, hi, step = (int(v) for v in a.series.split(":")); widths = list(range(lo, hi + 1, step))
    if int(W) not in widths: widths.append(int(W)); widths.sort()
    pts = drag_frames(a.frames.split(",")) if a.frames else []
    sets = {}; total_bytes = 0
    for w in widths:
        lift = bool(a.lift_path) and w < W
        if w == int(W): h, how, src = H, f"the lifted lens ({W:g}×{H:g})", []
        elif lift:
            rw, rh = (float(v) for v in a.lift_path.lower().split("x")); h = H - (W - w) * (H - rh) / (W - rw); how, src = f"lift path {rw:g}×{rh:g} → {W:g}×{H:g} (both dimensions on the same curve, model bounds)", []
        elif pts: h, how, src = height_for_width(pts, w)
        elif a.lift_path: h = H * w / W; how, src = f"stretch beyond {W:g}: the lifted model scaled uniformly (the tab lens's presented 115.7×73.6 = 110×70 × 1.052)", []
        else: h, how, src = H, "no --frames: rest height", []
        # the model lens: the lifted size (its scaled image for the stretch sets); on the lift path the model bounds themselves change
        MW, MH = (float(w), float(h)) if lift else (W, H); base_wh = None if lift else (W, H)
        bg = parse_layers(a.bg_layers, MW, MH, portal); lab = parse_layers(a.label_layers, MW, MH, portal)
        fbg, flab = f"{a.name}-f-bg-{w}.png", f"{a.name}-f-lab-{w}.png"
        portal_rect = None if a.label_portal in ("0", "") else tuple(float(v) / 2 for v in a.label_portal.lower().split("x"))
        # encoding scale per set: S 40 wherever the scaled stack fits ±20 pt (the 220 set stays byte-identical to cdb33f4 — a change of S moves
        # the quantised end-zone samples by up to 0.09 pt, half a device column on the 1-pt end lines), S 48 only for the widest stretch sets
        S_set = a.scale
        try: mw, mh, pk_bg = render_formula(os.path.join(a.out, fbg), w, h, bg, a.px, S_set, a.margin, None, base_wh); _, _, pk_lab = render_formula(os.path.join(a.out, flab), w, h, lab, a.px, S_set, a.margin, portal_rect, base_wh)
        except ValueError:
            S_set = 48.0; mw, mh, pk_bg = render_formula(os.path.join(a.out, fbg), w, h, bg, a.px, S_set, a.margin, None, base_wh); _, _, pk_lab = render_formula(os.path.join(a.out, flab), w, h, lab, a.px, S_set, a.margin, portal_rect, base_wh)
        render_baked_sets(a, w, h, bg, lab, S_set, base_wh, portal_rect, fbg, flab)
        fab, pk_ab, fabs, fabls, fabes = render_fringe_maps(a, w, h, base_wh)
        nb = os.path.getsize(os.path.join(a.out, fbg)) + os.path.getsize(os.path.join(a.out, flab)) + sum(os.path.getsize(os.path.join(a.out, f)) for f in fabs); total_bytes += nb
        sets[w] = {"h": round(h, 2), "scale": [round(w / W, 4), round(h / H, 4)], "S": S_set, "layer_pt": [w + 2 * a.margin, round(h + 2 * a.margin, 2)], "map_px": [mw, mh], "h_source": how, "frames": [[round(f[0], 2), round(f[1], 2), f[2]] for f in src],
                   "label_portal_pt": a.label_portal, "ab": fab, "ab_files": fabs, "abl_files": fabls, "abl_margin": a.abl_margin, "abe_files": fabes, "abe_box_pt": END_BOX[0] + END_BOX[1], "abe_visible_pt": END_BOX[0], "abe_reach_pt": END_BOX[1], "peak_ab_pt": (round(pk_ab, 2) if pk_ab is not None else None), "S_ab": a.S_ab,
                   "bg": fbg, "lab": flab, "peak_bg_pt": round(pk_bg, 2), "peak_lab_pt": round(pk_lab, 2), "bytes": nb,
                   "model": [MW, round(MH, 2)], "lift_path": bool(lift),
                   "filters": [f"{a.name}-lens-f-bg-{w}", f"{a.name}-lens-f-lab-{w}"] + ([f"{a.name}-lens-f-ab-{w}", f"{a.name}-lens-f-ab-ir-{w}"] if fab else [])}
    # filters: one file per set; hrefs as index.html sees them (lens-filter.svg) and bare names (lens-test.html)
    def svg_for(prefix):
        head = f"""<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true">
  <!-- Lifted segmented-control lens: displacement maps COMPUTED from the decompiled QuartzCore formulas with the probe's original
       parameters (gen_lens_maps.py --formula; README.md §1d; remote-ref/glass-displacement-formula.md, seg-lens-refraction.md §1b).
       One set per lens width w (drag stretch, 196 … 256 step 2, height from the recorded drag frames): #seg-lens-f-bg-<w> for the
       opaque copy of what lies under the lens (track / card), #seg-lens-f-lab-<w> for the label copy; pick the set by the current
       lens width, no interpolation. feDisplacementMap: P'(x,y) = P(x + scale·(R − .5), y + scale·(G − .5)), scale {a.scale:g} = the
       encoding scale S (byte = 128 + u·255/S, u in pt); color-interpolation-filters="sRGB" is required. Each map covers the lens
       box plus {a.margin:g} pt on every side and the filter region is the element's own box: apply the filter to a layer of that
       extended size (w+{2 * a.margin:g} × h+{2 * a.margin:g}, overflow hidden, placed at −{a.margin:g}/−{a.margin:g} inside the lens which clips it to
       the capsule). THE SOURCE MUST EXTEND PAST THE LENS — with the layer equal to the lens box the outward sampling at the edges
       reads transparent and one-pixel coloured lines appear along the long edges (README §0.3). userSpaceOnUse regions and
       feImage subregions are not used: WebKit renders nothing with them, and it takes an overflowing child into the
       objectBoundingBox region. No dispersion in these maps (the colour
       fringe is glassForeground's aberration term, not yet decompiled): one map feeds all channels. Animate the lift by the scale
       attribute 0 → {a.scale:g} with the lift curve of seg-keys.css.
       ENGINE FACT (calib/, 2026-09-19): WebKit's feDisplacementMap quantises the displacement to one device pixel (½ CSS px at
       devicePixelRatio 2 — Mac WebKit; ⅓ at 3 — iOS, standalone window) and applies a NEGATIVE displacement one pixel short
       (−1 → −0.5 / −0.67, −4 → −3.5 / −3.67), a positive one rounded up to the next pixel; a constant map decodes to its value
       (no zero-point offset, no linearRGB decode). 引擎校正: load lens-engine-fix.js after this <svg> — it re-encodes every
       #…-f-bg-/-lab- map's R/G at page load so negative values are longer by exactly one device pixel (k = 1/devicePixelRatio,
       byte' = byte − k·255/S for byte < 128), blob: copies only, the files untouched; not the fringe chains. README §0.4.
       引擎校正 2 (supersampled displacement layers, default on in lens-test, ?ss=0 off): lay each filtered layer out at SS× its
       size (SS 2) with its copy scaled SS× inside, in a composited wrapper scaled 1/SS (scale3d + will-change: transform) —
       WebKit then runs the software filter on an SS×-size raster and CA downsamples it, halving the displacement quantum and
       the negative-lane shortfall; set the feDisplacementMap scale to data-s × SS (the map's pt are SS layer px) and the filter
       region to 100/SS % (WebKit resolves the region of a layer under a scaled ancestor in unscaled units — calib/
       webkit-region-under-scale.html); lens-engine-fix.js reads window.LENS_SS for its k. Frame cost 4× the filter pixels
       per layer — measured on the phone before it goes into index.html (README §0.4). -->
"""
        body = []
        for w, st in sets.items():
            body.append(filter_formula(st["filters"][0], prefix + st["bg"], w, st["h"], st["S"], a.margin, f"backdrop, lens {w}×{st['h']:g} = the 220×44 model scaled by ({st['scale'][0]}, {st['scale'][1]}): {a.bg_layers} (sampling order); encoding S {st['S']:g}", a.engine_fix_sets))
            body.append(filter_formula(st["filters"][1], prefix + st["lab"], w, st["h"], st["S"], a.margin, f"label copy, lens {w}×{st['h']:g}: {a.label_layers}; encoding S {st['S']:g}", a.engine_fix_sets))
            if st.get("ab"):
                for mode, fid in (("flip", st["filters"][2]), ("ir", st["filters"][3])):   # #seg-lens-f-ab-<w> = the band factor e (the formula with EdgeOpacityStart 1 / End 0), #seg-lens-f-ab-ir-<w> = 1 − e (record of the first reading)
                    body.append(filter_aberration(fid, [prefix + f for f in st["ab_files"]], w, st["h"], st["S_ab"], mode, a.ab_margin, f"colour fringe: glassForeground 7-tap spectral sampling, amount/height/offset/angle {a.aberration}, edge band {a.edge}, tap direction sign {a.ab_sign:g}, α_elem {a.ab_alpha:g}, edr {a.ab_edr:g}, lens {w}×{st['h']:g}; apply to the wrapper of the two displaced layers", a.ab_alpha, a.ab_edr, a.ab_wh, st["peak_ab_pt"] or 0.0))
                body.append(filter_aberration(st["filters"][2].replace("-f-ab-", "-f-abl-"), [prefix + f for f in st["abl_files"]], w, st["h"], st["S_ab"], "flip", a.abl_margin, f"colour fringe, the same formula as #{st['filters'][2]}", a.ab_alpha, a.ab_edr, a.ab_wh, st["peak_ab_pt"] or 0.0, lean=True))
                for side, f in zip(("l", "r"), st["abe_files"]):   # (a): the chain on an END element only — its own box = the wrapper's end crop, the same numbers (README §0.8.5)
                    body.append(filter_aberration(st["filters"][2].replace("-f-ab-", "-f-abe-") + f"-{side}", [prefix + f], w, st["h"], st["S_ab"], "flip", a.ab_margin, f"colour fringe on the {'left' if side == 'l' else 'right'} END element ({END_BOX[0] + END_BOX[1]:g} × {st['h'] + 2 * a.ab_margin:g} pt = the wrapper's {'first' if side == 'l' else 'last'} {END_BOX[0] + END_BOX[1]:g} pt: margin {a.ab_margin:g} + the arc's band 22 + 8.8 + tap reach, of which the inner {END_BOX[1]:g} pt are clipped after the filter), the same formula as #{st['filters'][2]} on the map's crop", a.ab_alpha, a.ab_edr, a.ab_wh, st["peak_ab_pt"] or 0.0, lean=True, end_box=(END_BOX[0] + END_BOX[1], st["h"] + 2 * a.ab_margin, END_BOX[1])))
        body.append(filter_inner_shadow(a.name))
        return head + "\n".join(body) + "\n</svg>\n"
    open(os.path.join(a.out, "lens-filter.svg"), "w").write(svg_for(a.href_prefix))
    tpl = os.path.join(HERE, "lens-test.template.html")
    if os.path.exists(tpl):
        series_js = json.dumps({str(w): st["h"] for w, st in sets.items()})
        page = "lens-test.html" if a.name == "seg" else f"lens-test-{a.name}.html"
        rel = "" if os.path.abspath(a.out) == os.path.abspath(HERE) else os.path.relpath(HERE, os.path.abspath(a.out)) + "/"   # lens-engine-fix.js sits next to the generator
        open(os.path.join(a.out, page), "w", encoding="utf-8").write(open(tpl, encoding="utf-8").read().replace("{{FILTER}}", svg_for("").strip()).replace("{{SERIES}}", series_js).replace('src="lens-engine-fix.js"', f'src="{rel}lens-engine-fix.js"').replace('src="lens-supersample.js"', f'src="{rel}lens-supersample.js"').replace('src="lens-map-dpr.js"', f'src="{rel}lens-map-dpr.js"'))
    # verification (the only place measured fields enter): the formula against the phase files, validate2.py's method
    verify = {}
    chain = None
    if a.verify_chain:
        cp = a.verify_chain.split("/")
        chain = {"lens_scale": float(cp[0]), "content_scale": float(cp[1]), "model_centre": tuple(float(v) for v in cp[2].split(",")), "platter_centre": tuple(float(v) for v in cp[3].split(",")), "period": float(cp[4]) if len(cp) > 4 else 8.0}
    def run(group, spec, floor, glyph, region, use_chain=False, depth_min=3.0):
        out = []
        for f in group.split(","):
            AMP_FLOOR[0] = floor
            out.append(verify_against(f, lambda w, h: parse_layers(spec, w, h, portal), depth_min=depth_min, glyph_rows=glyph, region=region, base=(W, H), chain=chain if use_chain else None))
        AMP_FLOOR[0] = a.amp_floor; return out
    lreg = tuple(float(v) for v in a.label_region.lower().split("x"))
    if a.verify_bg:
        verify["backdrop"] = [r for g in a.verify_bg.split(";") for r in run(g, a.bg_layers, a.amp_floor, True, None)]
        verify["backdrop_without_glass_background"] = [r for g in a.verify_bg.split(";") for r in run(g, a.bg_layers.split(",", 1)[1], a.amp_floor, True, None)]   # verification only: BackdropView alone
    lab_alt = ",".join(reversed(a.label_layers.split(",")))   # the other sampling order (ClearGlass first, the acceptance session's / validate_label.py's formula)
    for name, files in (("label_lift", a.verify_label_lift), ("label_drag", a.verify_label_drag), ("label_mid244", a.verify_label_mid244)):
        if not files: continue
        verify[name] = run(files, a.label_layers, a.label_amp_floor, False, lreg, use_chain=bool(chain))
        verify[name + "_reversed_order"] = run(files, lab_alt, a.label_amp_floor, False, lreg, use_chain=bool(chain))   # verification only: ClearGlass sampled first
        if chain:   # the old page's validate_tab.py reports depth ≥ 8 as well; and, verification only, the same files without the two transforms (the maps alone)
            verify[name + "_depth8"] = run(files, a.label_layers, a.label_amp_floor, False, lreg, use_chain=True, depth_min=8.0)
            verify[name + "_without_transforms"] = run(files, a.label_layers, a.label_amp_floor, False, lreg, use_chain=False)
    info = {"mode": "formula", "label": "反编译原值（公式 + 探针参数）",
            "formula": {"map": "glass-displacement-formula.md §1 sdf_glass_displacement: e = d + effectOffset; t = saturate(−e/H); P = mix(t<1 ? 0.7071 : 1, sqrt(1 − (1−t)²), curvature); D = R(angle)·g·(1 − P); coverage = saturate((−e − maskOffset)/fwidth + .5)",
                        "filter": "§2 displacement_map: out(p) = src(p + amount·D(p)) × coverage, amount in layer pt (negative = towards the inside of the shape)",
                        "glass_background": "§3 inner refraction: t = saturate(−d/H); amt = amount·(1 − sqrt(t(2 − t))) = the same profile; sampled before the layers below it",
                        "sdf": "§3 compute_sdf_with_mode: d = rounded-rectangle SDF (the supercircle degenerates to it at r = h/2); g = normalize(mix(box normal, normalize((x, hw·y/hh)), gradientOvalization))",
                        "composition": "layers in sampling order, u(p) = Δ₁(p) + Δ₂(p + Δ₁(p)) (content shown at p lies at p + u; validate2.py, glass-displacement-formula.md §5)"},
            "parameters": {"backdrop": a.bg_layers, "label": a.label_layers, "curvature": 1, "angle": 0, "effectOffset": 0, "maskOffset": 0, "gradientOvalization": 0.5,
                           "sources": {"amounts / SDF heights": "seg-lens-refraction.md §1b 表 1 (A9 in-process: #12 BackdropView height 36, displacementMap +9; #18 ClearGlass 11.2 / −17.5; #30 ContentLensing 7.04 / −8.8), §0",
                                       "glass_background inner refraction −6.6 / 4.4": "seg-lift-material.md §2 glassBackground keys; glass-displacement-formula.md §4",
                                       "gradientOvalization 0.5, cornerRadii 22, effectOffset 0, maskOffset 0, curvature 1, angle 0": "seg-lens-refraction.md §1b 表 1 #13 / #19 (原值)",
                                       "which layer acts on what": "seg-lens-refraction.md §1b 表 3 (switch test: page content only through BackdropView; the label copy through ClearGlass then ContentLensing); the ContentLensing element taken as the lens capsule (监督局 05:0x after the old page's recomputation: the 196×28 rectangle gives rms 1.37 inside the portal)",
                                       "sampling order": "the outer layer samples first: ContentLensing's image is portal #32 (196×28) showing the ClearGlass layer, whose image is the capsule-clipped segment content (formula.md §2, §1b 表 2) → u = Δ_L(p) + Δ_C(p + Δ_L(p)); the other order (validate_label.py) differs ≤ 0.1 rms inside the portal (verification → *_reversed_order)",
                                       "sampling / source rules": "formula.md §2 + §4b (final structure): clamp_to_edge (the sample position is clamped to the stage's texture box; BackdropView marginWidth 0 → no content beyond its 220×44 frame, the edge column is replicated), clip first then displace (portal #20 clips the segment content to the r22 capsule before ClearGlass; portal #32 (ContentLensing's source) does NOT clip, masksToBounds 0 — the label stack acts on the whole lens), output × the effect shape's coverage (the map's B channel, applied by feComposite)",
                                       "glass_background SDF shape / ovalization": "the filter layer's own bounds + corner radii (监督局 05:0x); its ovalization is not read by the probe — the old page's residual table (rms 0.12–0.16) uses 0.5 on both backdrop layers, kept here"}},
            "encoding": {"device_px": a.device_px, "coverage_aa": "cov = saturate(.5 − d/fw), fw = 1 device px = 1/device_px pt (formula.md §4b.1 D)", "clamp": "the sample position is clamped to the last texel centre of the stage's texture (½ device px inside the box) then clamp_to_edge (formula.md §4b.1 A)",
                         "engine_fix_pt": a.engine_fix, "engine_fix": "引擎校正: WebKit's feDisplacementMap applies negative values one device pixel short (calib/: Mac 2× ½ px, iOS simulator 3× ⅓ px), positive rounded up; the correction is applied AT PAGE LOAD by lens-engine-fix.js (default on, k = 1/devicePixelRatio: every negative R/G byte −k·255/S, blob: copies, files untouched); --engine-fix <pt> bakes the same into the files for a static build (default 0 = not baked); README §0.4",
                         "scale": "per set: sets[w].S — 40 where the scaled stack fits ±20 pt, 48 for the widest stretch sets; the filter element carries data-s", "px_per_pt": a.px, "bytes": "R = 128 + round(u_x·255/S), G = same for u_y, B = shape coverage (255 inside, anti-aliased edge), A 255; u = content − screen (pt, +x right, +y down); the browser decodes S·(byte/255 − .5) = u + S/510",
                         "channels": "one map for all three colour channels (no dispersion)"},
            "sets": sets, "series": {"widths": widths, "step": step, "height_source": "linear between the two nearest recorded drag frames (seg-native-abc-frames.json phase drag; uiprobe-motion-segdragmid-light.json lenstrace); outside the recorded range the nearest frame (flagged clamped)", "shape": "the 220×44 r22 model lens scaled by (w/220, h/44) — seg-lens-refraction.md §1c(d): the flex scale sits on _UILiquidLensView's presentation transform alone, the layers below (SDF elements, portals 196×28, glass group) keep their model bounds; elliptical ends, the portal = scale × 196×28", "total_bytes": total_bytes},
            "aberration": ({"map": f"{a.name}-f-ab-<w>.png: the lens box plus {a.ab_margin:g} pt on every side at {a.ab_px} px/pt; R/G = the ratio-1 vector Δ₁ (pt) = amount · ((R(θ)g).y, (R(θ)g).x) · e(d) (§3b.3 direction with the lanes swapped; e = the edge factor, 1 at the edge → 0 at |EdgeStart| pt), B = e = the filter's band factor; own scale sets[w].S_ab (data-s on the fringe filter)",
                            "W_over_H": {"applied_by": "the fringe filter's feColorMatrix #<fid>-wh (data-wh): R × W/H + ½(1 − W/H), G × H/W + ½(1 − H/W) — Δ = (W/H · Δ₁.x, H/W · Δ₁.y); the page sets it per frame (lens-test: whRule())",
                                         "rule": "formula.md §3b.6: W × H = the foreground's capture box = the lens frame + marginWidth 100 (A9 #33) on every side, clamped to the screen — read at two positions of the 220×44 lens on the 440×956 screen: drag-mid x 110–330 → 10–430 = 420 × 244 → 1.72; lifted in place x 10–230 → 0–330 = 330 × 244 → 1.35; the value written into the SVG is the drag-mid 1.72 (the position of every verification frame)",
                                         "written": a.ab_wh, "not_read": "the capture box of a STRETCHED lens (presentation transform ≠ 1) was not read; the page applies the same rule to the lens's screen frame"},
                            "wrapper": f"the chain filter sits on a wrapper of the lens box extended by {a.ab_margin:g} pt (overflow hidden), holding a plain copy of the page under the two displaced layers: the foreground's backdrop capture has marginWidth 100 (A9 #33), its outward taps read the page beyond the lens — with the lens box alone they read transparent and a saturated yellow ring appears",
                            "formula": "formula.md §3b glass_foreground_base: t_a = saturate((−d − offset)/height); amt_a = amount·(1 − sqrt(t_a(2 − t_a))); 7 taps k = 1, 2/3, 1/3 at +kΔ (R += r·k, G += g·(1−k)), k = 0, 1/3, 2/3, 1 at −kΔ (G += g·(1−k), B += b·k); out = (R/2, G/3, B/2); edge band out ×= 1 − op",
                            "parameters": {"amount/height/offset/angle": a.aberration, "edge start/end/opacity": a.edge, "tap_direction_sign": a.ab_sign, "alpha_elem": a.ab_alpha, "edr": a.ab_edr,
                                           "source": "seg-lens-refraction.md §1c(a) (A9 sdfdump, in-process): #33 glassForeground inputAberrationAmount 2.3158, inputAberrationAngle −0.2618 (−15°), inputAberrationHeight 0, inputEdgeStart −8.8, inputEdgeEnd 0, inputRefractionAmount 0 / Height 0 (no refraction term), layer opacity 1, normalBlendMode; the old page's '−15 / 20' were the angle in degrees and an unread height",
                                           "mask": "the formula (§3b.2 %195–%199) with the lens's keys inputEdgeOpacityStart 1 / End 0: out ×= 1 − mix(1, 0, e) = e = saturate((d + 8.8)/8.8) → #seg-lens-f-ab-<w> (the test page's default); 1 − e (#seg-lens-f-ab-ir-<w>) is the record of the first reading",
                                           "tap sides (sign +1)": "Δ = amt_a·R(angle)·g with amt_a = +2.3158 (no falloff) and g the outward gradient rotated by −15° → Δ points OUTWARD (rotated); R accumulates the taps at uv + kΔ (outward), B the taps at uv − kΔ (inward) — the data session's sdfset: angle + π ≡ amount negated, pixel-identical (seg-lens-drag-mid.md §6b(d)); sign −1 only for verification"},
                            "shape": "the lens capsule with gradient ovalization 0.5 like the other stages — the foreground's SDF element and ovalization were not read (formula.md §3b: its element comes through a portal from the glass group)",
                            "mask_switch": "#seg-lens-f-ab-<w> = e (the formula, default); #seg-lens-f-ab-ir-<w> = 1 − e (record); test page ?ab=flip (default) | ir | 0",
                            "applies_to": "the wrapper of the two displaced layers (the foreground samples what lies below it inside the lens); test page ?ab=flip|ir|0"} if a.aberration != "off" else None),
            "filter": {"region": "the element's own box (objectBoundingBox 0/0/100%/100%), the map fills it", "layer": f"the lens box extended by {a.margin:g} pt on every side (layer_pt of each set), overflow hidden, at −{a.margin:g}/−{a.margin:g} inside the lens; the lens capsule clips it", "requirement": "the source must extend past the lens: with the layer equal to the lens box the outward sampling at the edges reads transparent (1-px coloured lines along the long edges)", "not_used": "userSpaceOnUse region + feImage subregion (Chrome only: WebKit renders nothing with them, and its objectBoundingBox region follows an overflowing child)"},
            "verification": verify,
            "sources": ["remote-ref/glass-displacement-formula.md §1–§5", "remote-ref/seg-lens-refraction.md §0, §1b, §2", "remote-ref/tools/touch/seg-phase-*.json (comparison only)"]}
    json.dump(info, open(os.path.join(a.out, "lens-field.json"), "w"), indent=1, ensure_ascii=False)
    print(f"{len(sets)} sets ({widths[0]}…{widths[-1]} step {step}), {total_bytes / 1024:.0f} KB of PNG; filter {os.path.getsize(os.path.join(a.out, 'lens-filter.svg'))} bytes")
    for w, st in sets.items(): print(f"  w {w}: h {st['h']:g} scale {st['scale']} S {st['S']:g} ({st['h_source']}) peak bg {st['peak_bg_pt']} lab {st['peak_lab_pt']} pt, {st['bytes']} B")
    for name, res in verify.items():
        print(f"== {name}")
        for r in res:
            print(f"  {r['file']}: rms {r['rms_all']} max {r['max_all']} pt; " + "; ".join(f"{row['offset']:+g}: {row['rms']:.2f}/{row['max']:.2f}@{row['max_at_s']:+g}" + (f" in {row['inside_rms']:.2f}/{row['inside_max']:.2f}" if 'inside_rms' in row else "") for row in r["rows"]))
            if r["over_tol"]: print(f"    > 0.3 pt: {len(r['over_tol'])} points: " + ", ".join(f"({o['offset']:+g},{o['s']:+g}) m {o['measured']} f {o['formula']}" for o in r["over_tol"][:12]) + (" …" if len(r["over_tol"]) > 12 else ""))


if __name__ == "__main__": main()
