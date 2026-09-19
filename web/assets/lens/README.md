# Segmented-control lens refraction — displacement maps + SVG filter

The lifted / dragged selection lens of the segmented control (`.segctl .lens`, 196×28 → 220×44 r 22 while held) bends what is
under it like the native `_UILiquidLensView`. This folder holds the displacement maps COMPUTED from the decompiled QuartzCore
formulas with the probe's original layer parameters (§0, 反编译原值（公式 + 探针参数）), one set per lens width for the drag
stretch, the `<filter>`s that apply them, the generator, a test page, and (`seg-keys.css`, `gen_seg_keys.py`) the lens kinematics
compiled from the native per-frame recordings. Nothing here touches `view.js` / `index.html`; the ui session wires it in.

| File | What |
|---|---|
| `gen_lens_maps.py --formula` | computes the maps from the formulas (§0), writes the filters, the test page, `lens-field.json` (parameters, sources, width → height table, residuals) |
| `seg-f-bg-<w>.png` | backdrop map for lens width w (196 … 256 step 2; 220 = lifted at rest): what lies under the lens (track / card). The lens box at 2 px/pt, R/G = the clamped sampling offset (byte = 128 + u·255/S, S 40 or 48 per set), B = the coverage the filter multiplies by, one map for all colour channels |
| `seg-f-lab-<w>.png` | label-copy map for width w (the label copy's two displacement stages on the whole lens — formula.md §4b: portal #32 does not clip; B = the product of the two stages' capsule coverages, §0.2 / §0.3) |
| `lens-filter.svg` | `#seg-lens-f-bg-<w>` / `#seg-lens-f-lab-<w>`: feImage (href = the PNG files as `index.html` sees them, `assets/lens/…`) → feDisplacementMap → feComposite with the map's B; `#seg-lens-f-ab-<w>` / `-ab-ir-<w>`: the fringe chain (§0.5, test page only for now); copy the `<svg>` into `index.html` |
| `seg-f-ab-<w>.png` | the fringe span map (§0.5): lens + 16 pt, 1 px/pt, R/G = the ratio-1 vector Δ₁ (its own S, `S_ab` 12), B = the edge-band factor e; the filter's `#…-wh` colour matrix applies W/H per lens position |
| `lens-field.json` | everything the maps hold: formulas, parameters with sources, per-width heights (and where each comes from), the residual tables |
| `lens-test.template.html` → `lens-test.html` | the test page (standalone metas; `?w=<width>` picks a set; drag / auto-drag / gratings / frame stats) |
| `gen_seg_keys.py` → `seg-keys.css` | lift / release / commit / drag keyframes compiled from the native frame data (§5) |
| `verify_lens_maps.py`, `gen_lens_maps.py` without `--formula` | the earlier measured-resampling mode (§1–§4, record only): resamples the phase files into maps — no longer part of the deliverable |
| `calib/` | WebKit feDisplacementMap calibration (`gen_calib.py` → maps + `webkit-displacement.html`, `check_calib.py` reads a render): the engine applies negative displacements one device pixel short (§0.4) |
| `tools/air_sampler.py` | lists the functions of a Metal library (`.metallib`) and decodes every constexpr sampler state they carry (bit layout read with the Metal compiler, §0.8.14) |
| `tools/fringe_check.py` | the A1 8× three-item check (coloured share of the outer 12 pt, saturation mean / median, the ends' colour order) on any screenshot of the held lens (§0.5) |
| `lens-supersample.js` | 引擎校正 2, default on (`?ss=0` off): wraps every filtered lens layer in a composited ½ wrapper and lays it out 2× (the filter runs on a 2× raster), folds SS into the filters' `data-s` / scale / region (§0.4); one `<script>` line before view.js and lens-engine-fix.js |
| `lens-engine-fix.js` | 引擎校正, default on: re-encodes the bg / label maps at page load so negative displacements are one device pixel longer (k = 1/devicePixelRatio), blob: copies only (§0.4); load after the `<svg>` |

## 0 Formula maps — 反编译原值（公式 + 探针参数） (2026-09-19)

No measured field goes into any map. The measured fields (§1) only check the result (§0.4). Every number and its source:

### 0.1 The formulas (`~/Money/styl-work/remote-ref/glass-displacement-formula.md`, the old page session's decompilation of
`QuartzCore.framework/default.metallib` + the QuartzCore binary, iOS 27.0 simulator 24A434)

| Step | Formula | Where read |
|---|---|---|
| shape | `d` = signed distance of the layer's element (negative inside); the lens element is its bounds with cornerRadii 22 = a capsule (the supercircle SDF degenerates to the rounded rectangle at r = h/2); outward normal from the same SDF | §3 `compute_sdf_with_mode`, `supercircle_sdf` |
| gradient ovalization | `g = normalize(mix(box normal, normalize((x, hw·y/hh)), w))`, `w` = `CASDFElementLayer.gradientOvalization` | §3 (`SdfFragmentUniforms.arg.w`) |
| displacement map (`CASDFGlassDisplacementEffect`) | `e = d + effectOffset; t = saturate(−e/H); P = mix(t < 1 ? 1 − 0.2929 : 1, sqrt(1 − (1 − t)²), curvature); D = R(angle)·g·(1 − P)`; third channel = shape coverage `saturate((−e − maskOffset)/fwidth + .5)` | §1 `UberShader::sdf_glass_displacement` (IR) |
| displacement filter | `out(p) = src(p + inputAmount·D(p)) × coverage`, `inputAmount` in layer pt; negative = sampling towards the inside of the shape | §2 `displacement_map_lpf`, `SampleMapFilter::render` |
| glass background inner refraction | `t = saturate(−d/H); amt = amount·(1 − sqrt(t(2 − t)))` = the same quarter-circle profile, on the filter layer's own bounds + corner radii | §3 `glass_background_base` |
| composition | layers in sampling order (the layer on top samples first): `u(p) = Δ₁(p) + Δ₂(p + Δ₁(p))`; content shown at p lies at p + u | §5 (`validate2.py`) |

### 0.2 The parameters (all 原值; `seg-lens-refraction.md` §1b, A9 in-process dump `uiprobe-sdf-seg-lift-{light,dark}.json`, light = dark)

| Map | Stack in sampling order | amount / SDF height | element | Source |
|---|---|---|---|---|
| `seg-f-bg-<w>` (what lies under the lens) | 1 glassBackground inner refraction → 2 BackdropView displacementMap | −6.6 / 4.4 → **+9 / 36** | lens capsule w×h, r = min(22, h/2), gradientOvalization **0.5** (both stages) | §1b 表 1 #12/#13 (BackdropView height 36, element cornerRadii 22, ovalization 0.5, effectOffset 0, maskOffset 0, curvature 1, angle 0), 表 3 #11 (inputAmount +9; the page content passes only through this layer — switching it off changes 81 % of the lens pixels, ClearGlass off changes 0 %); glassBackground inner −6.6 / 4.4: `seg-lift-material.md` §2, formula.md §4 |
| `seg-f-lab-<w>` (the label copy) | 1 ClearGlass displacementMap → 2 ContentLensing displacementMap | **−17.5 / 11.2** → **−8.8 / 7.04** | lens capsule, ovalization 0.5 (both) | §1b 表 1 #18/#19 (11.2, ovalization 0.5), #30 (7.04), 表 2/3 (#17 −17.5 acts on the segment-content copy, #29 −8.8 on the ClearGlass copy: the label passes both, in that order). The ContentLensing element is the lens capsule (监督局 05:0x after the old page's recomputation: the 196×28 portal rectangle gives rms 1.37 / max 3.85 inside the portal, the capsule 0.35 / 1.10) |

Sampling order = layer order, the outer layer first: the ContentLensing filter's image is portal #32 (196×28) showing the
ClearGlass layer, whose image is the capsule-clipped segment content (§1b 表 2, formula.md §2) — so u = Δ_L(p) + Δ_C(p + Δ_L(p))
(`--label-layers` lists ContentLensing first). The acceptance session's / `validate_label.py`'s formula samples ClearGlass first;
inside the portal the two differ by ≤ 0.1 rms (§0.4, `*_reversed_order`), at the ends by 0.3–1.5 pt. Backdrop: glassBackground
(the glass group's own backdrop capture, on top) samples first, then BackdropView.

Sampling and source rules — **formula.md §4b, the final structure (2026-09-19)**: the `displacement_map_lpf` sampler is
clamp_to_edge (a coordinate beyond the stage's texture replicates the edge pixel — the map stores the sample position clamped
to the lens box); each stage's filter acts on its layer image, clipped first (transparent outside the layer's mask), then
displaced, then multiplied by the effect shape's coverage (the map's B channel). Layers, bottom up: **0** the page + track +
segment content, with the DestOut (#43, r 22 capsule) punching the segment content out INSIDE the capsule only (the strokes
outside it stay: §6d, all three switches leave them); **1** BackdropView #11 (marginWidth 0) captures the 220×44 frame = page +
track + what of the segment content is left in the frame's corners, +9 / 36, outward samples beyond the frame replicate the
edge column (the §6d slivers in the rim band are that replicated column, not content from outside); **2** ClearGlass #17 −17.5 /
11.2 on portal #20 (220×44, masksToBounds r 22 → the segment content 400×32 clipped to the capsule BEFORE the displacement);
**3** glassBackground −6.6 / 4.4 on layer 1's output; **4** ContentLensing #29 −8.8 / 7.04 on portal #32 — 196×28 but
**masksToBounds 0, cornerRadii 0: it does not clip**, its image is the whole 220×44 ClearGlass layer (`--label-portal 0`; the
A9 read + the native |s| 100–109 still showing 「班」 strips + §6d's −8.8 switch moving the right band 416 → 243); **5**
glassForeground (§0.5); **7** the `_UILiquidLensView` presentation transform scales all of it (§0.3). In the label map:
B(p) = cov(p) × cov(p + Δ_L(p)), the final sample position clamped to the box; in the backdrop map B(p) = cov(p) × cov(p + Δ_G(p)).

Not read by the probe and therefore stated: the glassBackground shader's own SDF ovalization — the old page's residual table
(rms 0.12–0.16, §0.4) computes both backdrop stages on the same capsule with ovalization 0.5, kept here. (The drag frames'
DestOut cornerRadius 22 is the model value; on screen it is scaled with the rest, §1c(d).)

### 0.3 The maps

Encoding as before, S per set: 40 wherever the set's stack fits ±20 pt (the 220 set and 19 more — the 220 maps are byte for byte
those of cdb33f4; changing S re-quantises the end-zone samples by up to 0.09 pt, half a device column on the 1-pt end lines, which
the ui session saw as 111/112 → 203.9/204.7), 48 for the eleven stretch sets whose scaled label stack exceeds it (w 228, 238 …
256; `lens-field.json` → `sets[w].S`, and every `<filter>` carries `data-s`): byte = 128 + round(u·255/S), x → R, y → G,
u = content − screen (pt, +x right, +y down), zero = byte 128; B = the shape coverage the shader writes (255 inside, anti-aliased
edge, 0 outside — the lens clip does the same job in the web, feDisplacementMap ignores B); A 255. 2 px/pt. The browser decodes
S·(byte/255 − .5) = u + S/510 (0.08 / 0.09 pt, every channel alike). No dispersion: the colour fringe is glassForeground's aberration
term (formula.md §3, `aberrate_texture`), not decompiled yet — one map feeds all three channels, so the filter is a single
`feDisplacementMap` on `SourceGraphic`. Outside the capsule (the box corners, clipped away by the lens; the shader's coverage is 0 there) B is 0 and R/G hold the clamped
sample of the formula like everywhere else.

**One set per lens width** (`--series 196:256:2`, 31 widths × 3 maps, 530 KB of PNG in total, ≤ 1 MB): during the drag the
lens stretches (253.5×36.2 at the fastest recorded move, 204×47.5 on the overshoot); the page picks the set of the current width
(nearest even width, no interpolation). **What a stretched set is** (`seg-lens-refraction.md` §1c(d), the data session's in-process
reading of the drag frames): the flex scale sits on `_UILiquidLensView`'s presentation transform alone — every layer below (the
SDF elements, the five portals, the glass group, DestOut) keeps its model bounds and identity transform and is simply scaled with
the parent: 221.78×43.42 = (1.0081, 0.9867) × 220×44 with the portal 197.59×27.63, 204.67×47.37 = (0.9303, 1.0767) on the rebound.
So a set of width w and height h is the 220×44 model (capsule r 22, portal 196×28, all four stages) scaled by (w/220, h/44):
u(p) = S·u₀(S⁻¹p) — elliptical ends, the portal = scale × 196×28 (217.4×24.4 at 244×38.4), never a capsule of radius h/2. Each set's
height is the native's at that width: linear between the two nearest recorded drag frames of `seg-native-abc-frames.json` (phase
drag) and `uiprobe-motion-segdragmid-light.json` (lenstrace); 196, 254 and 256 lie outside the recorded 197.5 … 253.5 and take the
nearest frame's height (flagged `clamped` in `lens-field.json`). The lift (196×28 → 220×44) is a different path (both dimensions
grow, the amounts ramp with the same curve, `seg-keys.css`); the sets are not for it — animate the filter's `scale` 0 → S (its
`data-s`, 40 for the 220 set).

**The filter and the layer** (the acceptance session's ③ and the source rules of formula.md §2): `x=0 y=0 width=100%
height=100%`, feImage (the map, stretched to the element box) → feDisplacementMap on SourceGraphic → feComposite `in` with the
map's B moved into alpha by feColorMatrix (= `out = src(p + u(p)) × map.B`). The filtered layer is the lens box (w×h) with
`overflow:hidden` — its bounding box is its border box in every engine — and its own clip: the label layer is clipped to the capsule
BEFORE the filter (`border-radius` = min(22, h/2): the native portal #20 masks the segment content with r 22, then ClearGlass
displaces — 先裁再位移), the copy of what lies under the lens keeps the box and holds, besides the page and the track, the
segment content with the lens capsule cut out (`.punch`, `clip-path: path(evenodd …)` = the DestOut of §4b layer 0: the frame
corners keep the label pixels and the map's clamp replicates that edge column into the rim band; `?punch=0` = without, for the
record). No region beyond the box is needed: the map's samples
never leave it (clamp_to_edge baked in), so nothing is transparent-from-outside and the one-pixel coloured lines of the diagnostic
(05:0x: page y 113.00 a full row of (0,255,255), y 152.33/152.67 (0,255,255)/(0,0,255), from channels straddling the box edge)
are gone: 0 off-neutral pixels in the lifted rest frame in Chrome and in WebKit (scan of the whole lens area).

Not the `filterUnits="userSpaceOnUse" x=-10 y=-10 width=240 height=64` + `feImage x/y/width/height` form: WebKit (macOS 27.2
system WebKit, offscreen `WKWebView`, `scratchpad/wk/wksnap.swift`) renders NOTHING for an element carrying that filter (a
calibration page with a striped box: the box vanishes; a constant map with the default region displaces exactly 4 pt = 4 pt in the
same page), and with the default region it takes an overflowing child into the objectBoundingBox region (a 400-wide copy inside a
220×44 layer without `overflow:hidden`: WebKit's band came out 7.7–37.5 instead of 9–35). With the box layer: Chrome band
9.3–35.0, WebKit 8.7–35.0 on the centre column, native 9–35 (`seg-lens-drag-mid.md` §0: 611/637).

### 0.4 Check — the formula against the measured fields (`--verify-*`; residuals in `lens-field.json` → `verification`)

Method = the old page's `validate2.py`: prediction along each measured profile, its centre value removed (the demodulation's unwrap
pins u(centre) ≈ 0), Gaussian σ 3 pt (the demodulation's own smoothing), points at depth ≥ 3 pt from the lens edge (the phase folds
in the last 3 pt), samples with amplitude ≥ 0.5 × median (backdrop) / 0.25 × median (label gratings fade at the portal edge), the
backdrop centre row without |s| ≤ 20 (the label glyph under the grating). Label sets are also reported inside the portal
(|x| ≤ 96, |y| ≤ 12 — the region the label copy actually shows; outside it the phase method aliases at |Δ| > 4, period 8).

<!-- verify:begin -->

**Backdrop `seg-f-bg` (glassBackground −6.6/4.4 → BackdropView +9/36, ovalization 0.5) vs the page-grating fields** — the old page's table: gx 0.16 (0.18 without the centre noise) / gy 0.12–0.15

| file | lens | rms (all rows) | max | per row: rms / max @ s | points > 0.3 pt |
|---|---|---|---|---|---|
| `seg-phase-gx-light.json` | 220×44 | **0.10** | 0.82 | -16: 0.02 / 0.15 @ -98; -8: 0.08 / 0.76 @ -105; +0: 0.18 / 0.62 @ +107; +8: 0.09 / 0.82 @ -105; +16: 0.02 / 0.07 @ +92 | 13 |
| `seg-phase-gy-light.json` | 220×44 | **0.14** | 0.49 | -80: 0.12 / 0.37 @ +19; -50: 0.14 / 0.45 @ +19; -30: 0.15 / 0.49 @ +19; +30: 0.15 / 0.49 @ +19; +50: 0.14 / 0.45 @ +19; +80: 0.12 / 0.36 @ +19 | 16 |
| `seg-phase-gx-dark.json` | 220×44 | **0.10** | 0.82 | -16: 0.02 / 0.15 @ -98; -8: 0.08 / 0.76 @ -105; +0: 0.17 / 0.45 @ +106; +8: 0.09 / 0.82 @ -105; +16: 0.02 / 0.07 @ +92 | 12 |
| `seg-phase-gy-dark.json` | 220×44 | **0.14** | 0.48 | -80: 0.12 / 0.36 @ +19; -50: 0.14 / 0.45 @ +19; -30: 0.15 / 0.48 @ +19; +30: 0.15 / 0.48 @ +19; +50: 0.14 / 0.45 @ +19; +80: 0.12 / 0.36 @ +19 | 16 |

**verification only: BackdropView +9/36 alone** — the glassBackground stage is needed (gy 0.85 without it, 0.14 with)

| file | lens | rms (all rows) | max | per row: rms / max @ s | points > 0.3 pt |
|---|---|---|---|---|---|
| `seg-phase-gx-light.json` | 220×44 | **0.26** | 3.12 | -16: 0.13 / 1.01 @ +98; -8: 0.20 / 1.74 @ +105; +0: 0.46 / 3.12 @ +107; +8: 0.19 / 1.65 @ +105; +16: 0.14 / 1.08 @ +98 | 36 |
| `seg-phase-gy-light.json` | 220×44 | **0.85** | 2.97 | -80: 0.82 / 2.74 @ +19; -50: 0.86 / 2.90 @ +19; -30: 0.88 / 2.97 @ +19; +30: 0.88 / 2.97 @ +19; +50: 0.86 / 2.90 @ +19; +80: 0.82 / 2.74 @ +19 | 60 |
| `seg-phase-gx-dark.json` | 220×44 | **0.23** | 2.86 | -16: 0.13 / 1.01 @ +98; -8: 0.20 / 1.76 @ +105; +0: 0.40 / 2.86 @ -107; +8: 0.20 / 1.67 @ +105; +16: 0.14 / 1.08 @ +98 | 35 |
| `seg-phase-gy-dark.json` | 220×44 | **0.85** | 2.96 | -80: 0.81 / 2.74 @ +19; -50: 0.86 / 2.89 @ +19; -30: 0.88 / 2.96 @ +19; +30: 0.88 / 2.96 @ +19; +50: 0.86 / 2.89 @ +19; +80: 0.81 / 2.73 @ +19 | 60 |

**Label copy `seg-f-lab` (ContentLensing −8.8/7.04 sampled first, then ClearGlass −17.5/11.2, lens capsule) vs the label-grating fields, lifted at rest**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-gx-light.json` | 220×44 | **0.80** | 10.47 | -10: 0.74 / 6.79 @ +104; -5: 0.60 / 5.21 @ +106; +0: 0.36 / 3.92 @ +104; +5: 0.61 / 5.34 @ +106; +10: 1.33 / 10.47 @ -103 | -10: 0.12 / 1.19; -5: 0.02 / 0.28; +0: 0.02 / 0.17; +5: 0.02 / 0.23; +10: 0.11 / 1.09 | 45 |
| `seg-phase-label-gy-light.json` | 220×44 | **4.23** | 12.14 | -90: 2.63 / 7.08 @ -17; -60: 5.16 / 11.95 @ -19; -30: 4.79 / 12.14 @ +19; +0: 3.30 / 9.65 @ +17; +30: 4.79 / 12.14 @ +19; +60: 5.16 / 11.95 @ -19; +90: 2.89 / 7.37 @ +17 | -90: 0.31 / 0.92; -60: 0.36 / 1.08; -30: 0.35 / 1.03; +0: 0.34 / 1.00; +30: 0.35 / 1.03; +60: 0.36 / 1.08; +90: 0.27 / 0.78 | 122 |

**the same, dragged to the divider (lens 220×44 at x 220)**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-dragmid-gx-light.json` | 220×44 | **0.14** | 1.65 | -10: 0.10 / 0.64 @ -102; -5: 0.14 / 1.15 @ -103; +0: 0.21 / 1.65 @ -104; +5: 0.13 / 1.07 @ +103; +10: 0.08 / 0.46 @ -103 | -10: 0.03 / 0.26; -5: 0.01 / 0.03; +0: 0.00 / 0.01; +5: 0.00 / 0.02; +10: 0.01 / 0.06 | 33 |
| `seg-phase-label-dragmid-gy-light.json` | 220×44 | **4.28** | 12.14 | -90: 2.71 / 7.39 @ -17; -60: 5.16 / 11.95 @ -19; -30: 4.79 / 12.14 @ +19; +0: 3.67 / 8.03 @ -19; +30: 4.79 / 12.14 @ +19; +60: 5.16 / 11.96 @ -19; +90: 2.90 / 7.37 @ +17 | -90: 0.28 / 0.80; -60: 0.36 / 1.08; -30: 0.35 / 1.03; +0: 1.86 / 3.12; +30: 0.35 / 1.03; +60: 0.36 / 1.08; +90: 0.27 / 0.78 | 136 |
| `seg-phase-label-dragmid-gy-ends-light.json` | 220×44 | **1.72** | 7.18 | -104: 0.17 / 0.42 @ +10; -100: 1.04 / 3.59 @ -14; -96: 2.81 / 7.17 @ -17; +96: 2.79 / 7.18 @ -17; +100: 0.97 / 3.42 @ -14; +104: 0.12 / 0.33 @ -10 | -96: 0.28 / 0.79; +96: 0.25 / 0.74 | 53 |

**the same, the stretched 244×38.3 frame (period-6 grating for gx)**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-mid244-gx6-light.json` | 244.05×38.3501 | **1.00** | 5.87 | -10: 0.54 / 3.98 @ -115; -5: 0.58 / 4.59 @ -118; +0: 0.58 / 4.78 @ -119; +5: 0.55 / 4.60 @ -118; +10: 1.94 / 5.87 @ -94 | -10: 0.17 / 1.28; -5: 0.12 / 0.99; +0: 0.10 / 0.85; +5: 0.12 / 1.03; +10: 1.34 / 5.87 | 128 |
| `seg-phase-label-mid244-gy-light.json` | 244.05×38.3501 | **2.87** | 10.61 | -108: 0.81 / 2.02 @ +12; -104: 1.06 / 4.36 @ -16; -100: 1.06 / 4.37 @ -16; -96: 1.35 / 4.42 @ -16; -80: 2.97 / 7.78 @ +16; -40: 3.96 / 10.58 @ +16; +0: 2.88 / 8.63 @ -15; +40: 3.37 / 10.06 @ +16; +80: 3.98 / 10.61 @ +16; +96: 3.85 / 10.31 @ +16; +100: 3.53 / 9.46 @ +16; +104: 3.06 / 7.97 @ +16; +108: 2.40 / 7.25 @ -15 | -96: 0.58 / 1.47; -80: 0.64 / 1.67; -40: 0.83 / 2.27; +0: 0.82 / 2.19; +40: 0.81 / 2.18; +80: 0.82 / 2.26; +96: 0.79 / 2.17 | 204 |

**verification only: the two label stages in the other sampling order (ClearGlass first — the acceptance session's / validate_label.py's formula), lifted**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-gx-light.json` | 220×44 | **0.93** | 11.53 | -10: 0.88 / 8.41 @ +104; -5: 0.75 / 6.88 @ +106; +0: 0.40 / 4.42 @ +104; +5: 0.76 / 7.01 @ +106; +10: 1.48 / 11.53 @ -103 | -10: 0.12 / 1.19; -5: 0.02 / 0.28; +0: 0.02 / 0.17; +5: 0.02 / 0.23; +10: 0.11 / 1.09 | 45 |
| `seg-phase-label-gy-light.json` | 220×44 | **4.61** | 14.03 | -90: 2.80 / 7.84 @ -17; -60: 5.66 / 13.76 @ -19; -30: 5.24 / 14.03 @ +19; +0: 3.49 / 10.51 @ +17; +30: 5.24 / 14.03 @ +19; +60: 5.66 / 13.76 @ -19; +90: 3.10 / 8.14 @ +17 | -90: 0.32 / 0.94; -60: 0.37 / 1.10; -30: 0.36 / 1.05; +0: 0.35 / 1.02; +30: 0.36 / 1.05; +60: 0.37 / 1.10; +90: 0.28 / 0.80 | 122 |

**verification only: reversed order, dragged**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-dragmid-gx-light.json` | 220×44 | **0.21** | 2.15 | -10: 0.17 / 1.27 @ -102; -5: 0.19 / 1.53 @ -103; +0: 0.27 / 2.15 @ -104; +5: 0.17 / 1.45 @ +103; +10: 0.25 / 2.01 @ +104 | -10: 0.03 / 0.26; -5: 0.01 / 0.03; +0: 0.00 / 0.01; +5: 0.00 / 0.02; +10: 0.01 / 0.06 | 37 |
| `seg-phase-label-dragmid-gy-light.json` | 220×44 | **4.70** | 14.03 | -90: 2.88 / 8.15 @ -17; -60: 5.66 / 13.76 @ -19; -30: 5.24 / 14.03 @ +19; +0: 4.19 / 9.95 @ -19; +30: 5.24 / 14.03 @ +19; +60: 5.66 / 13.77 @ -19; +90: 3.10 / 8.14 @ +17 | -90: 0.28 / 0.82; -60: 0.37 / 1.10; -30: 0.36 / 1.05; +0: 1.86 / 3.14; +30: 0.36 / 1.05; +60: 0.37 / 1.10; +90: 0.28 / 0.80 | 136 |
| `seg-phase-label-dragmid-gy-ends-light.json` | 220×44 | **2.05** | 8.70 | -104: 0.49 / 1.23 @ +10; -100: 1.37 / 4.62 @ -14; -96: 3.26 / 8.69 @ -17; +96: 3.24 / 8.70 @ -17; +100: 1.30 / 4.44 @ -14; +104: 0.44 / 1.14 @ -10 | -96: 0.30 / 0.87; +96: 0.28 / 0.82 | 66 |

Reading the tables (numbers from `lens-field.json` → `verification`, every point listed there):

* Backdrop: rms 0.10 (gx) / 0.14 (gy), light = dark. Above 0.3 pt only at the ends of the ±8 rows (x ±104/105, depth 5: measured
  ±3.7 vs formula ±3.0–3.3) and at s = ±17…19 of the gy columns (depth 3–5: measured 2.6–3.2 vs formula 2.9–3.6) — the last
  5 pt before the edge, where the formula's profile steepens (its slope is infinite at the edge) and the demodulation smooths
  over the edge. The centre row's 0.18 is the label glyph's neighbourhood (masked |s| ≤ 20; the old page reads 0.35 → 0.18 alike).
* Label copy inside the portal (where the labels are): lifted gx 0.02–0.12 / gy 0.27–0.36 (max 0.8–1.1 at |y| 11–12, the portal
  edge's smoothed overshoot), dragged gx 0.00–0.03, ends columns ±96 0.25–0.28 — the same numbers the old page reports
  (lift gy .35 / 1.10, dragmid gx .02 / .36, gy-ends .28 / .83; its order samples ClearGlass first, `*_reversed_order` here).
* Label copy outside the portal (|s| > 98 on the ±10 rows, |y| > 12): the measured field is the ClearGlass band, the formula's
  values are larger — dragmid rows ±10 at |s| 100…102: measured 1.5 … 2.4, formula 1.9 … 3.0 (residual up to 1.65 pt; 2.1 with
  ClearGlass sampled first); the
  formula folds the last 11.2 pt (|du/ds| = 17.5/11.2 > 1: the content mirrors) where the measured slope is 0.57 (magnification
  ×2.3, `seg-lens-drag-mid.md` §5). Beyond |Δ| > 4 the period-8 phase method aliases and cannot check the −17.5 profile at all
  (the old page's note); the points above are the measurable part of that band and are the open item for the old page session.
  The lifted top / bottom band (|y| 14–19, gy files) reads the opposite sign of the formula (measured −3.9 at y −17 on column −90,
  formula +3.9): there the lens shows the segment content through a path whose sign matches the BackdropView profile, not the
  ClearGlass one — outside the portal the label copy is not what the grating measured. Listed, not adjusted.
* The two label stages in the other order differ by ≤ 0.1 rms inside the portal (the ContentLensing band lies outside it) and by
  0.3–1.5 pt at the ends (ClearGlass first is further from the measurement there).
* mid244: inside the portal gx 0.10–0.17 (row +10: 1.34, at s −94…−83 where the period-6 file carries a 1.4 pt step the
  period-8 file does not), gy 0.6–0.9 (the portal edges at |y| 12 lie 3 pt closer to the lens edge in the 38.3-tall lens, so the
  smoothed formula band overshoots more) — the same picture as the lifted set; the old page: lift and mid244 agree point by point
  inside the portal.

What the pictures show (`~/Money/styl-work/remote-mock/v4/lens/formula/`): lifted at rest the track band inside the lens sits at
9 … 35 pt from the lens top on the centre column (native `seg-lift-light.png` 611/637; Chrome 9.3/35.0; WebKit 8.7/35.0), its
ends follow the capsule (no vertical cut — the old measured maps cut it at the last measured column); a 1-pt notch of the band's
top edge at x ±98…100 (formula −2.9 pt of vertical pull there, native ≥ −3.0: a boundary case of the band edge at exactly row 9);
0 coloured pixels along the long edges in both engines. Dragged to the divider (`dragmid-4x-native-chrome-webkit-244.png`, rows:
native / Chrome / WebKit / the 244 set placed at the divider): with the source rules the label beyond the portal (|x| > 98) is cut
— at the rim only a thin strip of the glyph edge pulled by the ContentLensing band remains (the native shows the glyph parts
there as compressed slivers with colour fringes; what the ClearGlass copy shows beyond the portal is the open item with the old
page session), and the 244 set cuts the labels 24 pt inside each end because the portal stays 196 wide (not read during the drag).

The ring of dark dots along the capsule ends in the earlier dragged frame (f2e5d79, `dragmid-rim-dots-4x-native-formula-labelonly-labeloff.png`,
rows: native / formula / label filter only / label displacement off) was on the label layer only (74 dark rim pixels outside the
glyph rows with the label filter, 0 with it off): traced through the map, each sat 0.5–0.9 pt inside the edge where the
ClearGlass stage pulls 10–13 pt inward, and 56 of 74 landed on a stroke of 「班」 in the unfiltered label copy (e.g. (−107.0, −9.9)
→ u (+9.8, +4.8) → source (−97.2, −5.1), L = 0/47). With the source rules (the ContentLensing stage's 196×28 portal in B, the
capsule clip before ClearGlass, clamp_to_edge) those samples fall outside the portal and are masked: 0 dark rim pixels in Chrome
and WebKit (`dragmid-4x-native-chrome-webkit-244.png`), the rest frame unchanged.

**§4b final structure against the native (2026-09-19, WebKit 440×956 @3x, `final-4x-{light,dark}.png` rows native / ours, ends
at 4×; `wk-{mid,rest}-final-{light,dark}.png` full frames).** The test page's labels now sit where the native's do (200-pt
segments: 早班 ink x 107.67–132.17 / 晚班 308–332.17 against the native 107.67–132 / 308–332; the earlier page had them 1 pt
nearer the centre and every end number reported before this line was measured on that — superseded). Ink = pixels < 100 (light)
/ > 200 (dark), counted in the label's resting ink box like `seg-lens-drag-mid.md` §0c; the drag-mid state = `?native=1&lensx=220`:

| §0c item | native | ours light | ours dark |
|---|---|---|---|
| 左「早班」 ink under the left end | −37 % (dark −57 %), box unchanged | −28 %, box rows unchanged (13.5 → 25.0) | −32 % |
| 右「晚班」 ink | +37 % | +37 % | +51 % |
| 右「班」 height | 11.33 → 15.0 (dark → 12.0) | 11.67 → 13.66 | 11.67 → 13.17 |
| §6d regions (pt², y 612–636 ↔ page 120.89–144.89), 左外 100–110 / 左带 110–114 / 左内 114–136 / 右内 304–326 / 右带 326–330 / 右外 330–340 | 6.1 / 6.2 / 52.8 / 88.4 / 46.0 / 10.4 (from the A1 frame) | 8.5 / 7.5 / 68.7 / 107.4 / 48.2 / 9.7 (unfiltered: 8.5 / 25.0 / 84.3 / 89.6 / 21.5 / 9.7 — our 6 px/pt raster carries ~15 % more ink than the 3× native) | — |
| bars (`?pattern=bars`, G 50 % crossings) y634 ↔ 12 pt above the bottom edge, left end | … 107.84 · **111.78 · 112.52** (0.74) · 116.04 · 119.24 · 122.50 · 125.86 · 129.41 · 133.06 · 136.97 (gaps 3.52 3.20 3.26 3.36 3.55 3.65 3.91: compression ×.80–.91, one fold in the last pt) | … 107.92 · **111.95 · 112.88** (0.93) · 115.37 · 118.89 · 121.92 · 125.41 · 128.92 · 132.41 · 136.42 (gaps 2.49 3.52 3.03 3.49 3.51 3.49 4.01: ×.62–.88; the fold pair 0.93) | same maps |
| bars y634 right end | … 320.43 · 323.61 · **327.09 · 327.75** (0.66) · 331.84 | … 320.41 · 323.41 · **326.85 · 327.95** (1.10) · 331.92 (gaps before: 3.56 3.49 3.51 2.99 3.00 3.44) | |
| bars y610 ↔ 8 pt below the top edge (the top band: stretch) | left 107.83 · 111.84 · **119.50** (7.66 = one edge gone, ×1.9) · 122.82 · 126.16; right 320.16 · **327.84** (7.68) · 331.83 | left 107.92 · 111.92 · **118.87** (6.95, ×1.74) · 122.40 · 125.86; right 319.94 · **327.92** (7.98) · 331.92 | |
| rest band on the centre column (x 121) | 9 … 35 (611/637) | 8.7 … 35.0 | 8.7 … 35.0 |

What is met: the left label's ink loss with its box unchanged, the right label's +37 %, the §6d band regions (7.5 / 48.2 against
6.2 / 46.0), the compression of the last 10 pt, the fold pair within 1 pt of the edge, the top-band stretch (one edge lost) and
the rest band. What is not: the right 「班」 stretches to 13.7 instead of 15.0 and its end is a compressed lump where the native
shows horizontal streaks (the last 3 pt of the label path: the ClearGlass band's profile there is not in any measured field —
the phase method stops at the portal, §0.4 above, and the §6d bars are page content, i.e. the backdrop path); the gap just
inside the fold reads 2.49 against 3.52 (the same 1–1.5 pt over-pull of the two-stage backdrop at (−8, ±103…105) the tables
above list, `points > 0.3 pt`). The two label stages in the other order (ClearGlass first) were rendered too: the left label's
box grows to 16.3 pt tall (fragments pulled along the rim) where the native's is unchanged — the §4b order stays.

Two marks from the acceptance session's side-by-side of 16a9311 (`accept-gates/2026-09-19-cmp-16a9311-{light,dark}-ends.png`),
traced layer by layer (`?bg=0` / `?lab=0` / `?ab=0` / `?punch=0`, WebKit, current labels; `ghost-variants.png`, `dark-right-zoom.png`):
* the faint light-grey 「‹‹」 above the left end's fold strip (rows 128–129, x 110.5–114.8): it goes away with `?punch=0` or
  `?bg=0` and stays with `?ab=0` / `?lab=0` — it is **the backdrop path on the segment content's residue**: the 0.3-pt sliver of
  「早」 that the capsule punch leaves inside the 220×44 frame at x 110–110.33 (rows 128–136), replicated into the rim band by
  the map's clamp (the sliver's column is the frame's edge column), bent per row by the map's vertical component and faint
  because that column is the glyph's anti-aliased edge. That is §4b layer 1 / §6d: 「边带里多出来的是 BackdropView 底图路径把透镜外
  细条拉进来的复本」, ≈ 55 % of the native's band ink (BackdropView off: right band 416 → 185). Not removed: removing it means
  removing the residue or the clamp, both read. Its look differs from the native's slivers (thin, full-ink, horizontal) — the
  residue's first column and the band profile at the last 3 pt, the same open item as the 「班」 lump.
* the over-bright white patch at the dark right end: the label layer's own output — with the fringe chain off it is still there
  (82.5 pt² brighter than 235 in x 318–331, y 120–146; 0 coloured px), with the label filter off it is gone (22.9 pt² = the plain
  glyph). No tap and no α term: it is 「班」's right part folded into a lump by the label stack's last 3 pt (the light mode's black
  lump, §0c above), white because the dark label is white; the chain only colours its rim. Same open item.

**The label path's last 12 pt against the data's segment-grating field (2026-09-19 08:0x order; `tools/touch/seg-label-dragmid-{bars8,gx8}-seg-light.png`
@3x, lens held at the divider (lenstrace held_lens (110.43, 602.08, 219.57, 43.85)), the gratings as 196×28 segment images (`pattern bars|gx 8 2`,
read from the rest frames: bars8 = 4 pt black / 4 pt white from the image's left edge x 22 / 222, gx8 = 127.5 + 75.5·cos(2π(x − 23.833)/8));
the test page reproduces them (`?content=bars8|gx8`, phase checked on the unlensed segment: bars identical, gx8 within 5/255);
`ends-{bars8,gx8}-native-vs-webkit.png` = both ends at 12 px/pt, native over ours; `native-grating-ends.png`.**

Edge sequences (bars8, G-channel 50 % crossings, page x; native rows ↔ ours = native − 491.11): "map exact" = the delivered
`seg-f-lab-220.png` decoded (bilinear, 2 px/pt) and applied to the same bars in numpy (the source capsule-clipped, transparent
outside the 28-pt image band, the map's B as the mask); "map + WK rule" = the same with WebKit's displacement rounding (below);
"WebKit" = the render (`?content=bars8&bg=0&ab=0&punch=0`, the label layer alone — identical edges with everything on):

| row | end | native | map exact | map + WK rule | WebKit |
|---|---|---|---|---|---|
| 616 (band top + 6) | right | 309.83 · 313.83 · **318.20** · 329.83 | 309.92 · 313.92 · 318.25 | 310 · 314 · 318 | 309.92 · 313.92 · 317.92 · 329.92 |
| 616 | left | 109.83 · **121.46** · 125.83 · 129.83 | 121.58 · 125.92 · 129.92 | 122 · 126 · 130 | 109.92 · 121.47 · 125.92 · 129.92 |
| 632 (band bottom − 6) | right | 309.83 · 313.83 · **318.27** · 329.84 | (as 616) | | 309.92 · 313.92 · 317.92 · 329.92 |
| 632 | left | 109.83 · **121.39** · 125.83 · 129.83 | | | 109.92 · 121.42 · 125.92 · 129.92 |
| 624 (centre) | right | 317.83 · **324.03** (the eye) · **329.24 · 329.75** (fold) | 317.92 · **323.92** · **329.42 · 329.92** | 318 · **322** | 317.92 · **321.92** |
| 624 | left | 109.93 · 110.40 (fold) · **115.64** (eye) · 121.83 | 109.92 · 111.5 · 112.67 · 114.0 · 115.33 · 121.92 | 110 … 117 (flicker) · 122 | 109.91 · 111.49 · 112.34 · 113.97 · 115.41 · 121.92 |
| 606 (lens top + 4, above the band) | right | **311.75 · 317.25** (a bar pulled up out of the band) | 318.08 (the bar's edge, the sample at the band's top row) | 316.5 · 317.0 | — |
| 606 | left | **122.40 · 127.92** | 121.67 | 122 | 121.98 · 123.38 |
| 642 (lens bottom − 4) | right | **311.86 · 317.44** | 318.08 | 316.5 · 317.0 | 315.39 · 316.97 |
| 642 | left | **122.24 · 127.81** | 121.67 | 122 | 121.84 · 124.42 |

Vertical extent of the black bars per column at the right end (top-most / bottom-most black row; the band undisplaced = 610–638):
native x 304: 608.3 / 639.3; 310: 612.3 / 635.3; 312: 606.0 / 642.0; 314: 604.0 / 643.7; 316: 604.3 / 643.0; 318: 617.7 / 630.0;
320: 612.7 / 635.0; 324: 610.7 / 637.3; 328: 610.0 / 637.7 — ours (WebKit) 304: 609.7 / 638.0; 310: 609.8 / 637.8; 312: 609.2 /
638.5; 314: 608.2 / 639.8; 318: 612.8 / 643.5; 320: 610.3 / 636.8; 324: 609.2 / 638.5; 328: 610.2 / 638.0. The map at (312 … 316,
row 604 … 608) samples at lens y 7.8 … 9.1, i.e. the band's top row (8): the formula stretches the band's first pt over rows
604–608 (native: black from 604.0 at x 314); a sample 0.1–0.2 pt above the band reads transparent, and the bottom half's
upward samples are the engine's short ones (below) — hence ours starts at 608–609 and ends at 638–640 where the native runs
604–644.

What the field says about the two-stage sampling: **it holds.** Six pt inside the band (rows 616 / 632, depth ≥ 9 at the ends)
the map's edges sit within 0.35 pt of the native's at both ends; on the centre row the map puts the eye at 323.92 and the rim
fold at 329.42 / 329.92 against the native's 324.03 and 329.24 / 329.75 (≤ 0.2 pt); at the left end the map's stationary
sample sits at s ≈ 118.0 — a bar boundary — so the map flickers (111.5 … 115.3) where the native's eye is a clean bar
(110.4–115.64, its s inside 114 … 118): a difference of ≤ 0.3 pt in u over the last 5 pt, the native's u the smaller one; on
the rows 4 pt from the lens top / bottom the formula's pull lands the sample 0.1–0.4 pt outside the band where the native's
lands inside — a difference of ≤ 1 pt at depth 1–3.5, both stages half each there (L 1.0–4.8, C 1.7–2.9), not assignable
to one. The other order (ClearGlass first) adds edges the native does not have (row 616 right 327.3 / 328.4 / 330.5, row 624
left 108.5 / 110.1 / 110.75 / 114.3) — excluded. Nothing in the maps or the order changes on this field.

**Why the WebKit render is not the map — the engine's displacement rounding (`calib/`, 2026-09-19):** constant, ramp and
step maps on isolated marks (`calib/gen_calib.py` → `webkit-displacement.html`, read back by `check_calib.py`; the same
encoding and filter as the lens maps; wksnap, macOS 27.2 WebKit, offscreen WKWebView @3x):

| map u (CSS px) | −0.25 | −0.5 | −0.75 | −1 | −1.25 | −1.5 | −1.75 | −2 | −2.5 | −3 | −3.75 | −4 | −5.25 | −6 | −8 | −12 | +1 | +1.25 | +2.5 | +4 | +8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| applied, x | 0 | 0 | 0 | −0.5 | −0.5 | −1 | −1 | −1.5 | −2 | −2.5 | −3 | −3.5 | −4.5 | −5.5 | −7.5 | −11.5 | +1 | +1.5 | +2.5 | +4 | +8 |
| applied, y (−4 / −1 / +1 / +4) | | | | −0.5 | | | | | | | | −3.5 | | | | | +1 | | | +4 | |

The displacement is quantised to the filter's pixel — ½ CSS px in this render — with positive values rounded up to the next
pixel and **negative values truncated toward zero and one pixel short** (−1 → −0.5, −4 → −3.5, −12 → −11.5; the ramp
0 → −10 over 20 pt shows its edges 1.1 pt early, the step −4 gives 3.5). Applying that rule to the map in numpy reproduces the
render's centre row exactly (322 against the render's 321.92; the map's 323.92 and the fold gone). At the lens ends the
label stack samples inward, so the right end's x (negative) and the bottom half's y (negative) are the short ones; where the
sample position is stationary (the eye, the label's last 3 pt) a ½-pt shortfall moves the visible edge by 2 pt — the right
「班」's lump instead of the native's streaks and its 13.7-pt height, the eye 8 pt wide instead of 5.2, the band's bottom edge
at 639.8 instead of 643.7, and the §6d gap 2.49 at the left end (the backdrop path's outward x is negative there). Not an
Apple value. **On the iOS simulator (iPhone 18 Pro Max, iOS 27.0, 3×, the standalone home-screen window; the data session
2026-09-19, `tools/touch/calib-sim-3x.{png,txt}`, read with the same crossing method) the same rule with the step = one device
pixel = ⅓ CSS px:** x −0.25 → 0, −0.5 → 0, −0.75 → −0.33, −1 → −0.67, −1.25 → −1.0, −1.5 → −1.0, −1.75 → −1.33, −2 → −1.67,
−2.5 → −2.0, −3 → −2.67, −3.75 → −3.33, −4 → −3.67, −5.25 → −4.67, −6 → −5.67, −8 → −7.67, −12 → −11.67; +1 → 1.0, +1.25 → 1.33,
+2.5 → 2.67, +4 / +8 / +12 exact; y −4 → −3.67, −1 → −0.67, +1 / +4 exact; the other axis 0.00 on every map (so a constant map
decodes to its value: no zero-point offset, no linearRGB decode of the map on that path). Negative values: truncated toward zero
and one device pixel short; positive: rounded up to the next device pixel. The calibration page now carries the viewport and
standalone metas (without them iOS lays it out at 980 px and the step cannot be read).

**引擎校正 — the engine correction, default ON (监督局 2026-09-19 08:4x):** `lens-engine-fix.js`, loaded after the `<svg>` with the
filters (index.html, lens-test.html), re-encodes at page load every `#…-f-bg-` / `-f-lab-` map's R and G channels so that every
negative displacement is longer by exactly one device pixel, k = 1 / devicePixelRatio CSS px (2× → ½, 3× → ⅓): byte′ = byte −
k·255/S for byte < 128, into blob: copies (the map files stay the formula's values; `data-engine-fixed` on the feImage). The
engine's truncation then lands on the map's value, still quantised to its pixel like the positive side. Not the fringe chains
(seven taps read one map with positive and negative scales). Off for the record: `?enginefix=0` on the test page, or
`window.LENS_ENGINE_FIX = false` / `<script data-engine-fix="off">` before the script; `--engine-fix <pt>` bakes the same into the
files for a static build (default 0). It is a property of the renderer, not of the lens.

With it on (wksnap 2×, k ½; the same rows as above): centre row right end 317.92 · **323.92** · **329.42 · 329.94** — the map's and the
native's eye and rim fold (324.03 · 329.24 / 329.75); row 642 right 313.42–317.97 (native 311.86–317.44; before 315.4–317.0), left
121.86–126.42 (native 122.24–127.81); row 606 unchanged (its y is the positive lane — the ≤ 1 pt of the formula there); page bars
y634 left gaps 0.93 · **3.00** · 3.51 · 3.03 · 3.49 (the 2.49 gone; native 3.52), y610 left stretch gap **7.46** (native 7.66);
§0c: 左「早班」 ink −25 % (dark −30 %), box unchanged; 右「晚班」 ink +17 % (dark +26 %), 「班」 height 11.67 → **14.16** (dark 13.67;
native 15.0; before 13.66).

**formula.md §4b.1 (the old page's closed form for the label copy at the ends, 2026-09-19) against these maps:** the composition
`compose_stages` IS §4b.1 D — q = p − 8.8·Dc(s/7.04)·g, r = q − 17.5·Dc(s₂/11.2)·g₂, pixel = label(r)·cov(p)·cov_L2(q), the same
ovalized g (mix of the capsule normal and normalize((p.x, 5·p.y)), ½), the same Dc = 1 − √(2t − t²); along the end's normal it
returns §4b.1 C's table to the last digit (s 0 / .5 / 1 / 2 / 2.64 / 4 / 5 / 6 / 7.04 / 8 / 9 / 10 / 11.2 → r 9.21 / 8.01 / 7.92 /
7.95 / 7.97 / 7.93 / 7.93 / 8.02 / 8.29 / 8.73 / 9.34 / 10.10 / 11.2; r_min 7.92 at the fold q* 5.16). Two read details of §4b.1 A / D
were not in the generator and are now (`--device-px 3`): the coverage's anti-alias width = one device pixel (⅓ pt; it was one map
texel, ½ pt) and the sampler's clamp = the last texel centre (½ device px inside the box, then clamp_to_edge). The 31 + 12 sets
regenerated: the 220 label map's R / G bytes are unchanged (the clamp's ⅙ pt is below a byte), its B changes on 256 boundary
pixels (the narrower ramp); the backdrop map's boundary bytes by ≤ 1 (the clamp). The phase residuals are unchanged.

What §4b.1's platform means for the checks (`4b1-4x-{light,dark}.png`, rows: native / the maps rendered EXACTLY in numpy — the
formula at 6 px/pt with a bilinear fetch of the label raster, no engine / WebKit with the engine correction; `numpy-label-*.png`):
the exact render gives 右「班」 height **15.33** (light) / **15.00** (dark) against the native's 15.0 and the native's horizontal streaks
(the source column at depth 7.92–8.0 replicated over s .5–6: the glyph's horizontal strokes become streaks); WebKit gives 14.16 /
13.50 and a lump — the platform is 0.1 pt wide, so the engine's ½-px quantisation of the fetch (fact 1) lands one source column
over, on 「班」's vertical stroke. 左「早班」 ink −30 % in the exact render (native −37 %; WebKit −25 %); 右「晚班」's thresholded ink
(< 100 at 6 px/pt) reads −10 % in the exact render (blended streaks) where the native's +37 % is counted at 3 px/pt on
hard pixels — the ink count is not comparable across rasters, the height and the morphology are.

**Engine fact 2 — the source fetch is nearest-neighbour at the device pixel, CoreAnimation's is bilinear (2026-09-19; not
treated, candidates listed for the supervisor):** what the calibration shows is a displacement quantised to whole device pixels
(the applied values above are all multiples of the pixel; a bilinear fetch would need no quantisation) and the renders show only
source values at a displaced edge — never a blend: on the row where the displaced track edge runs along the row (page row 637 =
the band's bottom, lens y 35: the map's samples sit at lens y 37.7–38.1, on the track's bottom edge 38) WebKit and Chrome give
whole columns of track (238 / 239) or page (255 / 244) — ours 117–124 page, 125–130 track, 131 + page; the ui session's the
same blocks in Chrome (its filter region checked = the lens box: the copy appears from x ≈ 116 like the map's boundary; its
step at x 122 on row 610 is where its samples cross the track's top edge — in the 220 map that row's u_y passes −2 between x 117
and 118 and sits at −3.0 … −3.3 from 118 on, so a crossing at 122 puts its sampled edge about 1 pt higher relative to the map
than in the test page (track top = lens y 6); a wiring detail of its page, not the map) — while the native's same row is a flat 240–241, the blend of track 228 and page 243 that a bilinear
fetch of a sample 0.1–0.3 pt inside the edge gives. The same fact makes the ends' "hard" bands and the §6d notch. The
correction above fixes the one-pixel shortfall on negative values; the quantisation and the nearest fetch stay. Candidates
(none implemented; each with what it does, its cost, and whether `calib/` can verify it):

| candidate | what | cost | calib check |
|---|---|---|---|
| A. supersample the displaced layers | `transform: scale(2)` on the filtered layer inside a wrapper scaled ½ (WebKit renders a filter at the layer's device scale, so its buffer gets 2× the pixels; the wrapper's downscale then averages 2×2 buffer pixels ≈ a box filter over the displaced result) | 4× filter pixels per layer per frame (220×44 pt @3× = 1.4 M px → 5.6 M; two layers + the fringe chain); frame time to be measured on the phone | yes — the step should halve (−1 → −0.75 at 2×) and the displaced mark edges show a 2-level ramp; the notch on row 637 becomes 2-level |
| B. bilinear fetch in a shader | a WebGL (or 2D canvas) copy of the displacement in the decompiled formula's own sampling (`displacement_map_lpf` linear), drawing the lens's source content into a texture | the source is DOM (track, labels): it has to be re-drawn into the canvas per frame (SVG foreignObject serialisation or a programmatic redraw of the track and glyphs) — a second rendering path for the lens content | yes — constant and fractional maps on marks give blended edge values; the ramp edges land where the map says |
| C. finer maps (6 px/pt instead of 2) | more texels | 9× map bytes | no effect expected: the quantisation is the output buffer's, not the map's (the constant-map calibration is resolution-independent) — a calib run would show the same table |
| D. soften the source edge (blur the track / glyph copy by a pixel) | hides the blocks by changing the content | forbidden by the rules (涂软 = masking, not a renderer fact) — listed only to say it is not on the table | — |

A is the one that changes the fact without a second rendering path; its frame cost is the question (the test page's 自动拖 2 s
frame stats on the phone would answer it).

**引擎校正 2 — candidate A done (2026-09-19, 监督局 09:2x; default ON in the test page, `?ss=0` off; not yet in index.html — the data
session measures the frame time on the phone first):** each filtered layer is laid out at SS = 2 × its size with its copy scaled 2×
inside (`.ss2`), in a composited wrapper scaled ½ (`.ssw`: `scale3d(.5,.5,1)`, `will-change: transform`); WebKit then rasterises the
layer at 2× and runs the software filter on that raster, CA downsamples the composited wrapper with bilinear sampling. Two engine
facts found on the way, both measured with `calib/`: (1) the filter of a layer under a scaled ancestor has its objectBoundingBox
region resolved in UNSCALED units — `width="100%"` stretched the map over twice the layer (`calib/webkit-region-under-scale.html`:
the 25 %-step map's step landed at 220 instead of 165; with `50%` it lands right) — so the page sets the region to 100/SS % and the
feDisplacementMap `scale` to data-s × SS (the map's pt are SS layer px); the filter definitions in `lens-filter.svg` stay as
generated; (2) in this composited path WebKit's buffer is at the device scale (wksnap @3: the constant-map shortfall reads ⅙ pt
with SS 2 — 4 → 3.83 — where the plain page read ½; on a 3× phone the quantum becomes ⅙ pt). `lens-engine-fix.js` takes SS from
`window.LENS_SS` (k per layer pixel). The maps and the formulas are untouched. `ss-4x-{light,dark}.png` (rows native / the exact
formula / WebKit ss off / WebKit ss on):

| | native | ss off (bed84e4) | **ss on** |
|---|---|---|---|
| bars8 row 606 (lens top + 4) right / left | 311.75–317.25 / 122.40–127.92 | — / 121.97–123.42 | **312.42–318.41 / 121.67–127.41** |
| row 642 (lens bottom − 4) | 311.86–317.44 / 122.24–127.81 | 313.42–317.97 / 121.86–126.42 | **312.42–318.18 / 121.67–127.42** |
| row 616 right | 309.83 · 313.83 · 318.20 · 329.83 | 317.92 | 309.92 · 313.92 · **318.42** · 329.92 |
| row 624 (centre) right: the eye and the rim fold | 324.03; 329.24 / 329.75 | 323.92; 329.42 / 329.94 | 324.17 (then the ¼-pt flicker of the knife-edge); 329.42 / 329.94 |
| row 624 left: the eye | 110.40 … 115.64 | 111.5 … 115.4 flicker | 110.42 … 115.92 |
| 右「班」 height (light / dark) | 15.0 / 12.0 | 14.16 / 13.50 | **14.83 / 14.00** |
| 右「班」 shape | horizontal streaks with fringes | a lump | **streaks with fringes** |
| 左「早班」 ink (light / dark) | −37 % / −57 % | −25 % / −30 % | −19 % / −34 % |
| page bars y634 left gaps (fold pair, then) | 0.74 · 3.52 · 3.20 · 3.26 · 3.36 · 3.55 · 3.65 | 0.93 · 3.00 · 3.51 · 3.03 · 3.49 | 0.37 · 4.05 · 3.02 · 3.29 · 3.23 · 3.51 |
| page bars y610 left stretch gap | 7.66 | 7.46 | 7.53 |
| rest band, centre column | 9 … 35 | 8.7 … 35.0 | 9.2 … 35.0 |
| fringe (tools/fringe_check.py): share / saturation, light | 1.36 % / 69 | 1.15 % / 82.7 | **1.38 %** / 85.0 |
| dark | 1.38 % / 71 | 1.02 % / 79.0 | 1.20 % / 77.9 |

**Wiring for index.html = one line (2026-09-19, `lens-supersample.js`; 监督局's order): right after the `<svg>` with the lens filters and
BEFORE `view.js` and `lens-engine-fix.js`:**
```html
<script src="assets/lens/lens-supersample.js"></script>   <!-- 引擎校正 2, default on; ?ss=0 off -->
```
The script does the three steps below by itself, also for layers created later (a MutationObserver): it wraps every filtered lens
layer it knows (`.segctl .warp .disp`, `.segctl .warpl .displ`, the tab equivalents, the test page's `.layer.bg/.lab`; other
selectors via `data-targets` on the script tag) in a composited ½ wrapper inside the layer's own container, lays the layer out at
200 % with its former children inside a 2×-scaled `.ss2`, doubles the layer's border-radius (`calc(var(--rr) × 2)`), and on every
`#seg-lens-f-bg-* / -lab-*` (and tab) filter sets the region to 50 %, keeps the file's S in `data-s0` and writes `data-s = S × 2` —
so `view.js`'s `sOf(id)` writes `scale = data-s × progress` unchanged, and `lens-engine-fix.js` takes `data-s` as the layer-px scale
when `data-s0` is present. `window.LENS_SS` = 2 (1 when off), `window.LENS_SS_DONE`, `window.LENS_SS_APPLY()` for pages that build
layers after load. The test page runs on the same script (`lens-test.template.html`: `.slot` + `.layer` = the container + filtered
element pattern of `.warp` + `.disp`); its numbers are the table above (identical to the inline implementation of a0fed29).

The three steps it performs (for reference; nothing to copy by hand any more; `SS = 2`, `?ss=0` → `SS = 1` skips all three):

1. Structure — for each displaced layer (the backdrop copy `.warp`-equivalent and the label copy), replace
   `<div class="layer">…copies…</div>` by
   ```html
   <div class="ssw" style="position:absolute;left:LEFT;top:TOP;width:Wpx;height:Hpx;transform-origin:0 0;transform:scale3d(.5,.5,1);will-change:transform">
     <div class="layer" style="position:absolute;left:0;top:0;width:calc(W*2)px;height:calc(H*2)px;overflow:hidden;border-radius:calc(R*2)px;filter:url(#seg-lens-f-lab-220)">
       <div class="ss2" style="position:absolute;left:0;top:0;width:Wpx;height:Hpx;transform-origin:0 0;transform:scale(2)">…the copies, positioned exactly as before…</div>
     </div>
   </div>
   ```
   (W×H = the lens box, LEFT/TOP = where the layer sat, R = the capsule radius on the label layer only; the wrapper keeps the old
   position and size, the layer is 2× and untransformed, the copies untouched inside `.ss2`.)
2. Filter attributes, once per used filter, before the engine-fix script runs:
   ```js
   window.LENS_SS = 2;
   for (const id of ["seg-lens-f-bg-220", "seg-lens-f-lab-220"]) {            // the sets the page uses
     const f = document.getElementById(id), fe = f.querySelector("feDisplacementMap");
     if (!fe.dataset.ss) { fe.dataset.ss = "2"; fe.setAttribute("scale", String(parseFloat(fe.getAttribute("scale")) * 2)); f.setAttribute("width", "50%"); f.setAttribute("height", "50%"); }
   }
   ```
   (`scale` = data-s × 2 because a map pt is two layer px; the region 50 % because WebKit resolves it in unscaled units under the
   scaled ancestor — fact (1) above; when the page animates `scale` 0 → S for the lift, animate to S × 2.)
3. Load `assets/lens/lens-engine-fix.js` AFTER step 2 (it reads `window.LENS_SS` and uses k = 1/(devicePixelRatio·SS) per map).
   Nothing else changes: the map files, `lens-filter.svg`, the fringe chain on the wrapper of both layers (still the plain lens box +
   16 pt), the punch / clip rules. The test page's implementation is the reference (`lens-test.template.html`: `SS`, `.ssw`, `.ss2`).

**Does A remove the ends' hard bands (engine fact 2)?** — the backdrop layer alone (`?lab=0&ab=0`), the band's bottom-edge row 637
and top-edge row 610 at the left end, x 114 … 133 per pt, and the vertical profile through the displaced track top at x 320
(rows 606 → 614 by ⅓ pt); native from `seg-native-dragmid-{light,dark}-full.png`:

| | light: row 637 x 114–133 | dark: row 637 | light: x 320 rows 606 → 614 (⅓ pt) |
|---|---|---|---|
| native | 190 220 220 227 233 237 239 ×13 240 ×4 (one level after the rim) | 24 32 21 14 9 6 4 4 5 6 ×6 5 5 4 4 4 | 240 237 233 229 230 … 228 228 225 216 214 … (the step over ≈ 1 pt, 3 samples) |
| ss off | 212 238 240 247 252 ×6 251 **244 243 ×5 244** 251 252 ×2 (the 6-column block of track between page) | 44 49 46 36 31 ×6 **42 ×6** 31 ×3 (the block) | 255 … 255 **242** 238 … (one ⅓-pt sample between) |
| ss on | 212 237 238 247 252 ×4 251 **247 ×11** (a single blended level, the block gone) | 44 49 49 37 31 ×4 33 **37 ×11** (gone) | 255 … 255 **254** 238 … (one ⅓-pt sample between) |

Right end, row 637 x 306–325: native 240 ×4 239 239 238 238 239 ×4 240 239 238 234 225 213 213 187 (light) / 4 4 4 5 5 6 6 6 7 6 6 5 4 4 4 8 15 23 33 24 (dark);
ss off 252 252 251 **243 ×6** 244 251 252 ×6 247 240 238 212 / 31 ×3 **42 ×6** 31 ×7 36 46 49 44 (the block); ss on **247 ×11** 251 252 ×4 247 238 237 212 /
**37 ×11** 33 31 ×4 37 49 49 44 (a single blended level). Row 610 right: no block on either side (native 223–227 / 3–6, ours 249–255 / 28–35:
the tone, not the edge).

So A turns the row-parallel block (the displaced track edge riding along the row, decided per column) into the flat blended level the
native shows there (247 = the mean of page 252 and track 243, as the native's 239 is of 243 and 228 + its material tone) — the notch
and the hard horizontal blocks at the ends are gone. The vertical transition across the displaced edge stays one ⅓-pt sample wide
(the 2×2 average gives at most one intermediate row) where the native's spreads over ≈ 1 pt (bilinear); the tone between the rim
and the band (material, §0.4 above) is not A's business.

The rows 4 pt from the lens top / bottom, the streaks and the fringe share come to the native with it; what stays is the knife-edge
flicker in the eye (the platform straddles a bar boundary; the native's bilinear fetch blends it), the 0.17 pt short in the height
and the saturation. Cost: 4× the filter pixels per layer (two layers; the fringe chain on the wrapper untouched) — the data
session's standalone recording, on / off, decides whether it is on in index.html (`lens-test.html?native=1&lensx=220&ss=1` vs
`&ss=0`, 自动拖 2 s → `window.FRAME_STATS`).

The top / bottom bands at the ends (the acceptance session's B6 preview, 2026-09-19: "whitish and hard", `bands-native-bgonly-all.png`,
`topband-zoom.png`; the test page with the backdrop filter alone): the track's displaced edge sits where the native's does (top
band x 300: ours 610.3–610.5 against 610.7–611, x 322: 610.5 against 610.7; bottom band x 300: 637.0 against 637.3) and is as
hard (the native's 228 → 219 → 214 over 0.67 pt, ours 255 → 242 → 238 over 0.5 pt; the bottom edge one step in both). What
differs is the 5 pt between the rim and that edge: the native carries the glass tone there (light: 240 under the rim falling
to 228 at the track, the page being 243; dark: 0–3 against the page's 28, so the folded track edge (26) sits on black), ours
the page colour (255 / 28) with the track (238 / 50) straight on it. That is the glassBackground face / ring shadow / inner
shadow and KeyFill (§4b layer 3, `keyfill-highlight.md`) above the displacement, and the test page's dark palette — not the
backdrop map (no B step, no ledge at the ends).

<!-- verify:end -->

### 0.5 Colour fringe — glassForeground's 7-tap spectral sampling (test page + `lens-filter.svg`; not wired into index.html)

Source: `glass-displacement-formula.md` §3b second version (the old page session) on the lens's own keys read in-process by the
data session (`seg-lens-refraction.md` §1c(a) and the 140-key read): #33 glassForeground inputAberrationAmount **+2.3158**,
inputAberrationAngle **−0.2618 rad (−15°)**, inputAberrationHeight **0**, inputAberrationOffset **24.444**, inputEdgeStart
**−8.8**, inputEdgeEnd **0**, inputEdgeOpacityStart **1**, inputEdgeOpacityEnd **0**, inputRefractionAmount 0 / Height 0 (uv1 = uv),
layer opacity 1, normalBlendMode, backdrop marginWidth 100 (source surface = the capture box, §3b.6 below). What the shader
does (§3b.2, IR `fg_base.named.ll`): `R(θ)g = (g.x cosθ − g.y sinθ, g.x sinθ + g.y cosθ)`; **the aberration vector swaps the two
lanes** of that and divides each by the source surface's W and H (%79–%82, unlike the refraction vector):
`Δ = amt_a · ( (W/H)·(R(θ)g).y , (H/W)·(R(θ)g).x )` — so Δ.x follows g.y, which is why the same end has R/B the other way round on
different rows (the data's §6b(b)). Amplitude: `t_a = saturate((−d − 24.444)/height)` is 0 everywhere inside the lens (−d ≤ 22),
so `amt_a = 2.3158`, a constant; the spatial envelope is the edge factor: `e = saturate((d + 8.8)/8.8)`, `out ×= 1 − mix(1, 0, e) = e`
— 1 at the edge, 0 at 8.8 pt inside (§3b.5 closed 2026-09-19 06:xx; the check y634 6.4 / 9.6 / 12.8 pt from the end → e .55 /
.18 / 0 against the measured |R−G| .32 / .145 / .017). Seven taps: k = 1, 2/3, 1/3 at p + kΔ → R += r·k, G += g·(1 − k); k = 0, 1/3,
2/3, 1 at p − kΔ → G += g·(1 − k), B += b·k; `out = (R/2, G/3, B/2)·α·cov·ΣA/7·edr`, `α = cov·ΣA/7`, source-over. The old page's
sign check (§3b.4): y634 right end g (.83, .55) → Δ.x > 0 → R−G < 0 ✓ (−0.32), left end → R−G < 0 ✓ (−0.113), y610 left end
g (−.77, −.64) → Δ.x < 0 → R−G > 0 ✓ (+0.77); the y610/y634 ratio 2.6 vs 2.4 ✓; angle + π ≡ amount negated ✓.

**W and H** (formula.md §3b.6, the data's A9 read): the foreground's source surface is its backdrop capture = the layer frame +
marginWidth 100 on every side, clamped to the screen — so W/H changes with the lens's screen position: dragged to the divider
x 110–330 on the 440-pt screen → 10–430 × (502–746) = 420 × 244 → **1.72**; lifted in place x 10–230 → 0–330 × 244 → **1.35**.
The map therefore stores the ratio-1 vector Δ₁ = amount · ((R(θ)g).y, (R(θ)g).x) · e, and the filter applies W/H in a
`feColorMatrix` (`#seg-lens-f-ab-<w>-wh`, `data-wh`): R × W/H + ½(1 − W/H), G × H/W + ½(1 − H/W) — `gen_lens_maps.wh_matrix`; the
test page sets it every frame from the lens's `getBoundingClientRect()` and the viewport (`whRule()`; `?wh=` pins it; the value
written into the SVG is the drag-mid 1.72, the state of every check here). Not read: the capture box of a stretched lens
(presentation transform ≠ 1) — the page applies the same rule to the screen frame. The fringe maps carry their own scale
(`S_ab` = 4·⌈amount⌉ = 12, `data-s` on the fringe filter: a 0.05-pt step, room for W/H up to 2.6).

**The blend** (§3b.6): screen = e·(R/2, G/3, B/2) + (1 − e)·below — the chain's `in` with the band factor e followed by `over` is
exactly that (after the `in`, fg's alpha is e; source-over then gives e·fg + (1 − e)·below); e is not a mask.

In SVG: one map `seg-f-ab-<w>.png` (R/G = Δ₁ in pt at `S_ab`; B = e; 1 px/pt; lens + 16 pt), the W/H colour matrix, seven
`feDisplacementMap` on it (`scale = ±k·S_ab`), per-tap `feColorMatrix` weights and alpha/7, `feComposite arithmetic` sums, `in`
with ΣA/7, `in` with the band factor e (B), `over`. `#seg-lens-f-ab-<w>` is the formula (test page default `?ab=flip`);
`#seg-lens-f-ab-ir-<w>` (1 − e) is the record of the first reading of the edge opacities. The chain sits on a wrapper of the
lens box extended by 16 pt (`overflow:hidden`, own stacking context) over a plain copy of the page (the foreground's backdrop
capture reaches 100 pt beyond the lens; with the lens box alone the outward taps read transparent).

**Against the native** (WebKit, dragged to the divider; `fringe-8x-native-webkit.png` rows native / ours; the A1 PNG
`seg-native-dragmid-light.png`; bars = `?pattern=bars`, per-channel 50 % crossings, `webkit-dragmid-bars-full.png`):

| | native | ours |
|---|---|---|
| coloured px (max − min > 40) per 2-pt bin from the end, left / right | 629 383 130 0 0 0 / 714 519 193 0 0 0 (dark 614 361 138 / 730 555 215) | 276 162 50 0 0 0 / 544 183 41 6 0 0 (dark 291 161 38 / 528 133 13) — §4b structure, labels at the native x; the earlier 384 303 197 / 766 555 267 was with the labels 1 pt off |
| share of the outer 12 pt; mean saturation | 1.4 %; 69 (dark 1.4 %; 71) | 0.6 %; 96 (dark 0.6 %; 89). The count is mostly the colour on the label fragments at the ends (a horizontal streak carries more coloured pixels than a lump, §0.4); with W/H pinned to 1 / 1.72 / 2.5 it reads 1.0 / 0.7 / 0.5 % (the ends' aberration is the vertical lane × H/W) |
| strongest coloured px, left / right end | (110.33, 625) (214,189,56) yellow-orange / (328.33, 617) (14,72,217) blue | (−109.3, −5.2) (229,143,4) yellow-orange / (109.2, −0.7) (2,83,224) blue |
| bars y634 right end: R−G / B−G at 6.4 (ours 6.5), 9.6 (9.5), 12.8 (12.5) | −0.32 / +0.59; −0.145 / +0.135; −0.017 / +0.02 | −0.24 / +0.01; −0.06 / +0.01; 0.00 / 0.00 |
| bars y634 left end 9.2 (ours 9.0), 12.5 (12.0) | −0.113 / +0.099; −0.01 / 0 | −0.14 / +0.07; −0.02 / 0.00 |
| bars y610 left end 9.5 (ours 9.0), 12.8 (12.5), 16 (15.9) | +0.77 / −1.20; +0.11 / −0.12; +0.05 / −0.04 | +0.12 / −0.68; +0.02 / −0.08; +0.01 / −0.04 |
| middle 41 edges | 0.000 | ≤ 0.003 |

The band's extent and both ends' colours (yellow-orange left, blue right) sit with the native; the saturation is 96 against 69
(the blend is the §3b.6 α = e blend already, see above; §3b.6 names the KeyFill layer's vibrantColorMatrix on the 1–2 pt highlight
band — `keyfill-highlight.md` §2, not part of these maps — as the only remaining term above the fringe) and the bars offsets have
the native's signs at 0.5–0.75 of its size on the checked rows (the right end's B−G at 6.4 pt reads 0.01 against 0.59). Left
as is; nothing adjusted. Neighbouring text 8 pt from the control is not pulled in (native neither, `seg-neighbors-light-hold.png`).

**The composition formula of the old page's 单 b (2026-09-19, formula.md §3b.2 %170–%199 + §3b.6):** screen = e·edr·(R/2, G/3, B/2)
+ (1 − e)·below, e = saturate((d + 8.8)/8.8)·[depth < 24.44] (d = the capsule SDF, negative inside), R/G/B the 7-tap sums, w ≡ 1,
cov 1, ΣA/7 1, edr_scale 1 — the chain above is this formula term for term (nothing added). Its check against the A1 PNG at
the native's 3 px/pt (our render box-filtered 6 → 3 px/pt; the outer 12 pt of both ends; the three candidates the old page
listed for a saturation above the native's, each rendered on its own — none adopted):

| | share of the outer 12 pt | mean / median saturation (max − min, px > 40) | coloured px per 2-pt bin from the edge, left / right |
|---|---|---|---|
| native A1 light (dark) | 1.36 % (1.38 %) | 69 / 62 (71 / 63) | 629 383 130 / 714 519 193 |
| **the formula** (α = e, three taps per side, W/H 1.72) light (dark) | 0.64 % (0.57 %) | 93 / 81 (88 / 77) | 66 39 9 / 135 47 11 |
| ① e as a mask (band 1) | 0.89 % | 99 / 84 | 73 50 33 16 / 140 57 28 32 |
| ② one tap for R and B (k = 1 only) | 0.80 % | 113 / 104 | 81 49 12 / 160 62 15 |
| ③ W/H = 220/44 = 5 | 0.78 % | 102 / 92 | 96 23 4 / 186 51 18 |
| the chain off | 0 % | — | 0 / 0 |

**The check tool (B4-c' / C1, 2026-09-19): `tools/fringe_check.py <png> [--layout auto|wksnap|seghold|native-crop] [--lens x,y,w,h]
[--scale px/pt] [--theme light|dark] [--json]`** — the three items above on any screenshot of the held lens (a wksnap 440×956 @6
render of the test page, a standalone 3× device screenshot of `index.html?seghold` (lens 110, 731.67, 220, 44 — the C1 tables'
track top 737.67), or the native crops), measured at the native's 3 px/pt (a 6 px/pt render is box-filtered first); the colour
order per 2-pt row with a centroid test whose expectation flips with the theme (dark = white labels: right yellow-above-blue,
left blue-above-yellow — as the native dark crop reads). Expected values from the native crops and the current test page
(engine correction on, wksnap 2×):

| image | share of the outer 12 pt | saturation mean / median | right end order | left end order |
|---|---|---|---|---|
| native `seg-native-dragmid-light.png` | **1.36 %** (2-pt bins L 629 383 130 / R 714 519 193) | **68.9 / 62** | blue above yellow (centroids −1.4 / +3.0) | yellow above blue (−2.5 / +0.2) |
| native `seg-native-dragmid-dark.png` | **1.38 %** (614 361 138 / 730 555 215) | **70.7 / 63** | yellow above blue (−2.2 / +0.9) | blue above yellow (−2.4 / +0.7) |
| test page light, `wk-mid-fix-light.png` | 1.15 % (130 64 7 / 204 111 36) | 82.7 / 73 | OK (−1.7 / +5.2) | OK (−0.2 / +0.8) |
| test page dark, `wk-mid-fix-dark.png` | 1.02 % (128 53 4 / 192 88 24) | 79.0 / 70 | OK (−1.7 / +5.4) | OK (−0.6 / +0.9) |

(Before the engine correction the test page read 0.64 % / 93 — the rounding shortfall shrank the streaks; the table of candidates
below was taken then.)

Every candidate raises the saturation further, so none of the three is the difference. What the numbers say instead: (a) the
colour order per streak is the native's — right end blue above / yellow below, left end yellow above / blue below, per 2-pt
row at both ends; (b) with the chain off the ends carry no colour at all, i.e. every coloured pixel comes from the chain, and
the native has ten times as many of them in the first 2 pt of the rim (629 / 714 against 66 / 135): the native's rim line runs
round the whole capsule over uniform track and page — the taps there straddle the luminance step of the glass material at the
rim (glassBackground's inner shadow / ring shadow / face tone, layers 3 of §4b: the foreground's source), which the test page's
stack does not have (its track continues unchanged across the rim); (c) the pixels we do have are the label fragments' edges
(black on white) and they read more saturated per pixel than the native's strongest (219 against 163 at the same 3 px/pt) while
our per-channel offsets on the bars are 0.5–0.75 of the native's — a sharper sampling of a smaller shift, not a larger shift.
So the two summary numbers (1.4 %, 69) are numbers of the fringe on the material stack; on this test page they cannot be
reached by the chain and are not. The old page's check point (EdgeStart −8.8 → −17.6 doubles the band, e at 4.4 pt .5 → .75,
Δ unchanged) holds in the maps by construction (B = e; `--edge=-17.6/0/1/0`).

Frame interval, headless Chrome 440×956 @3x, software raster (`scratchpad/frames_chrome.py`, 自动拖 2 s, 120 frames):
without the chain 16.9–17.1 ms mean (max 50–67, 1 frame > 20 ms), with the chain 16.9 ms (max 33, 2 frames > 20 ms) — 60 Hz in
both; the simulator Safari number waits for the data session.

### 0.7 The tab bar's selection lens (`tab/`, 2026-09-19) — same generator, the tab lens's own keys

Source: `remote-ref/tab-lens-native.md` + `tools/uiprobe/tab-lens-table.md` (the data session's in-process dump of the floating
tab bar's `_UILiquidLensView`, Small variant, light = dark): lifted lens **110×70**, cornerRadii **35** (capsule), resting 94×54;
BackdropView displacementMap **+9** / SDF height **36** (as the segment lens), ClearGlass **−17.5 / 11.2**, ContentLensing **−14 / 11.2**
on the **94×54** portal, glassBackground inner refraction **−10.5 / 7**, glassForeground aberration **3.6842 / offset 38.889 /
angle −15° / height 0 / edge −14 … 0 / opacity 1 → 0**, gradientOvalization 0.5 on the two lens-sized elements (every item that
differs from the segment lens is × 70/44 = 1.591, the ratio of the lens heights — an arithmetic relation between readings, not a
derivation). `gen_lens_maps.py --formula --name tab --size 110x70 --series 94:116:2 --lift-path 94x54 --label-portal 0 --corner-radius half
--label-region 28x20 --bg-layers=-10.5/7/0.5/lens,9/36/0.5/lens --label-layers=-14/11.2/0.5/lens,-17.5/11.2/0.5/lens
--aberration=3.6842/0/38.889/-0.2618 --edge=-14/0/1/0 --href-prefix assets/lens/tab/ --out tab --verify-chain 1.0516/1.16/134,904/220,904/8
--verify-label-lift <tools/lens/phase-lift-{gx,gy}-{light,dark}.json>` (`--label-portal 0`: §4b, the ContentLensing portal does not
clip — same as the segment lens; `--corner-radius half`: r = h/2 = 35 on the lifted lens — **the first issue of these sets (1bb97a6)
took the segment lens's r 22 through `lens_shape`; wrong, replaced 2026-09-19**) → `tab/tab-f-{bg,lab,ab}-<w>.png` (12 sets,
300 KB; tracked since this issue — `.gitignore` un-ignores `web/assets/lens/tab/*.png`, the first issue's PNGs never entered the
repository), `tab/lens-filter.svg` (`#tab-lens-f-bg-<w>` …, hrefs `assets/lens/tab/`), `tab/lens-field.json`,
`tab/lens-test-tab.html` (`?tab=1`). Sets: w 94 … 108 = the lift path (both dimensions grow by the same amount from 94×54 to
110×70, the model bounds change, r = h/2, the SDF heights stay), **110 = the lifted model, the set the page uses** (below), 112 … 116
= the lifted model scaled uniformly, kept for a wiring without transforms (u(p) = S·u₀(S⁻¹p), §0.3; 116 ≈ the presented 115.68 —
not exact, the transform is).

**Where the 1.22 comes from and how the page is built** (`tab-lens-native.md` §3, `formula.md` §5b — the data's read + the old page's
recomputation `tools/lens/validate_tab.py`, 2026-09-19): the centre magnification 1.22 measured by the phase method is **two
transforms, not a shader term** — ① the three `_UITabButton`s of the SelectedContentView (the source of `liftedContentViewPortal`,
i.e. the copy inside the lens; the measurement's PatternView is another subview of it) carry transform scale **1.16** about their
own centres while lifted (icon 29.33 → 34.03, TitleWrapper 94 → 109.04; 1 at rest; the data's supplementary read
`tools/uiprobe/uiprobe-sdf-tabpat-{rest,lift}-light.json`: the measurement's PatternView, a direct subview of the
SelectedContentView as well, reads transform (1.16, 1.16) about its own centre (220, 904) while lifted and 1 at rest —
UIKit sets the 1.16 on each direct subview; the SelectedContentView itself stays at 1); ② the whole floating platter
`_UITabBarItemPlatterView` presents at scale **1.0516** about its centre (220, 904) during the lift (model identity; presFrame
(75.93, 871.40, 288.14, 65.20); the lens inside it (79, 869, 110, 70) → (71.72, 867.19, 115.68, 73.61)); 1.16 × 1.0516 = 1.220.
The four displacement stages act in the lens's 110×70 model space (BackdropView zoom 0 / scale 1 on every backdrop layer). The
test page (`?tab=1`) does exactly that: the lens element carries `scale(1.0516)` about the platter centre, the copies inside it
(page + platter + items, in the lens's model space) the inverse about the same point (so the page stays 1:1 on screen and the
platter 1.0516 — the BackdropView captures the screen in the platter's model space), the label copy's items `scale(1.16)` about
their own centres (`body.tab .lens .labels .tabbar span`), the maps of the 110 set on the layers; the three items sit 86 pt apart
(94×54 buttons at 134 / 220 / 306: the resting lens 94×54 at (87, 877) covers the first), the lens centre at the first button's
(134 model → 129.56 presented). Not in the page: the items' icons and the selected tint (the copy shows the label text), the
platter's own material (white with shadow in the native; the test page's `--track`), KeyFill.

**Check against the tab lens's phase fields through that chain** (`--verify-chain`: screen offset s from the presented lens centre →
model s / 1.0516 → the two label stages with the per-stage box clamp → the sample in the platter's model space → the copy scaled
1.16 about the platter centre → u = content − screen, brought to the measurement by whole grating periods at the centre; the
method otherwise as §0.4; `tools/lens/phase-lift-{gx,gy}-{light,dark}.json`, rows ±20 / columns ±25; `in` = |x| ≤ 28, |y| ≤ 20):

| file | depth ≥ 3: rms / max | depth ≥ 8: per line rms / max @ s, in = the centre zone | points > 0.3 (depth ≥ 8) |
|---|---|---|---|
| `phase-lift-gx-light.json` | 0.49 / 2.27 | −20: **0.45** / 2.27 @ −40 in 0.01 / 0.04; +20: **0.34** / 1.78 @ −41 in 0.07 / 0.19 | 10 |
| `phase-lift-gy-light.json` | 1.39 / 7.28 | −25: **0.35** / 1.61 @ −28 in 0.04 / 0.09; +25: **0.23** / 1.28 @ −28 in 0.04 / 0.09 | 12 |
| `phase-lift-gx-dark.json` | 1.18 / 7.52 | −20: **0.11** / 0.77 @ −41 in 0.01 / 0.03; +20: **0.29** / 1.05 @ −41 in 0.29 / 0.80 | 20 |
| `phase-lift-gy-dark.json` | 1.18 / 5.70 | −25: **0.18** / 0.68 @ +28 in 0.04 / 0.09; +25: **0.18** / 0.98 @ +28 in 0.04 / 0.09 | 10 |

The old page's `validate_tab.py` on the same chain: gx-light 0.44 / 0.34, gy-light 0.35 / 0.23, gx-dark 0.12 / 0.29, gy-dark
0.18 / 0.19 (depth ≥ 8) — the same numbers. Against the 0.3 line: gx-light −20 (0.45) and gy-light −25 (0.35) sit above it, the
rest below; the centre zone reads ≤ 0.07 except the dark +20 row (0.29, a measured asymmetry at s −7 … −14 that the light row
does not have). The points over 0.3 at depth ≥ 8 are the columns' |s| 25–28 (8.8–11.8 pt from the top / bottom edge, the −17.5
band's outer half) and the rows' |s| ≈ 40. Listed, nothing adjusted. Verification only: the two stages in the other order
(ClearGlass first) 0.51 / 1.46 / 1.28 / 1.31 (depth ≥ 3) — worse on every file; the maps **without** the two transforms
4.98 / 3.18 / 4.52 / 2.83 (the earlier "not met" 4.4–6.3 was this, on the r 22 shape).

Held state in WebKit (`tab-lens-native-vs-webkit.png`, rows per theme: native held / ours / ours unfiltered, 160×88 pt about the
presented lens centre at 6 px/pt): the copy at 1.22 (the label; the native's icon + title), the platter's presented size, the
band along the lens's top / bottom where the lens (70 tall) reaches 4 pt beyond the platter (62) and the frame's edge column is
replicated inward — the native shows the page above the platter there, ours the card — and the inner band. Not ours: the rim
highlight (KeyFill), the tint, the icons.

**Not met by the maps alone, and now read**: the tab lens magnifies its content **1.22 uniformly** at the centre
(`lens-refraction.md` §0: u = −0.18·s within |s| ≤ 28 horizontally / 20 vertically, then a rising edge zone, max displacement
12–14 pt) — the stack as read gives ≈ 0 at the centre (BackdropView +9 / 36 on a 35-pt half-height: t = 35/36 → 1 − P = 0.0004;
the glassBackground −10.5 / 7 and the label stages are edge bands) and only the bands near the edges. The data session read
where the 1.22 comes from (`tab-lens-native.md` §3, 2026-09-19): **two transforms, not a displacement** — ① the content copied
into the lens (the SelectedContentView's three `_UITabButton`s, the source of `liftedContentViewPortal`) carries transform
scale **1.16** while lifted (1 at rest); ② the whole floating platter `_UITabBarItemPlatterView` presents at scale **1.0516**
during the lift (the lens goes with it: 110×70 → 115.68×73.61 on screen); 1.16 × 1.0516 = **1.220**. The four displacement
stages do only the edge bands; in the segment lens's tree both factors are 1, hence its centre 1.00. So the tab page must scale
the label copy 1.16 about the lens centre and the platter 1.0516 (the presentation transform of §0.3, on the whole stack), then
apply these maps — the fields above were measured with both transforms in and are not comparable with the maps alone (the tab
maps' own check waits for that page; not done here, the tab order comes after the segment lens). The WebKit render
(`tab-lens-native-vs-webkit.png`, rows none / light / dark / native held) shows the edge bands only.

### 0.8 Tab bar lens — wiring package for GOAL 3 (2026-09-19; not wired here; one page for the ui session)

Sources: `remote-ref/tab-lens-native.md` §0 / §3 (the data session's A9 dump: layers, keys, transforms), `tools/uiprobe/tab-lens-table.md`
(the 82-layer table), `remote-ref/tab-lens-motion.md` §0 / §4 (the old page session's per-frame curves), `formula.md` §4b (the layer
structure, the same for the tab lens — "标签栏透镜同结构"), §5b (the two transforms in the copy chain), this README §0.7 (the sets, the
chain check). Model geometry in the platter's own coordinates (the probe's window coordinates: platter (83, 873, 274, 62), centre
(220, 904); the three `_UITabButton`s 94×54 at centres 134 / 220 / 306, i.e. 86 pt apart; the resting lens 94×54 r27 at (87, 877) = on
the first button, centre (134, 904); the lifted lens 110×70 r35 at (79, 869), the same centre).

**1. The sets** (`tab/tab-f-{bg,lab,ab}-<w>.png`, `tab/lens-filter.svg` → `#tab-lens-f-bg-<w>`, `#tab-lens-f-lab-<w>`, `#tab-lens-f-ab-<w>`
(the fringe; `-ab-ir-` = record), hrefs `assets/lens/tab/…`; copy the `<svg>` into index.html like the segment one and load
`assets/lens/lens-engine-fix.js` after it):

| w | h | r | what | S (`data-s` of bg / lab) | S_ab (fringe) |
|---|---|---|---|---|---|
| 94 … 108 step 2 | 54 … 68 (= w − 40) | h/2 | the lift path: the model bounds grow from 94×54 to 110×70 by the same amount on both axes, the SDF heights stay (36 / 11.2 / 7) | 40 | 16 |
| 110 | 70 | 35 | the lifted model — **the set the lifted / held lens uses** (the platter's 1.0516 is a transform, below) | 48 | 16 |
| 112 … 116 | 71.27 … 73.82 | h/2 | the lifted model scaled uniformly, for a wiring without the platter transform only (116 ≈ 115.68 presented, not exact) | 48 | 16 |

Pick the set by the lens's model width (even; nearest), no interpolation; the filter's `scale` attribute = the set's `data-s` × the
lift progress p (native: the displacement amounts +9 / −17.5 / −14 ramp on the same spring as the size; the bg map is linear in
the amounts, the label map (two stages composed) nearly so — ≤ the map quantisation for p ≥ 0.5; at p 0 the filters are off).

**2. The two transforms** (tab-lens-native.md §3; the verification chain of §0.7 = validate_tab.py): while lifted the platter
`_UITabBarItemPlatterView` presents at scale **1.0516** about its centre (220, 904) (model identity; presFrame (75.93, 871.40,
288.14, 65.20); the lens inside → (71.72, 867.19, 115.68, 73.61)); each direct subview of the SelectedContentView (the three
buttons; the copy the portal shows) carries transform scale **1.16** about its own centre (icon 29.33 → 34.03, TitleWrapper
94 → 109.04). 1.16 × 1.0516 = 1.22 at the centre. In the page: the lens element (110×70, position in the platter's model space)
carries `transform: scale(var(--tplatter-scale))` with `transform-origin` at the platter centre (in its own coordinates: platter
centre − lens position); the copies inside it (the page + the platter + its items, in the lens's model space) carry the inverse
`scale(calc(1 / var(--tplatter-scale)))` about the same point, so on screen the page stays 1:1 and the platter 1.0516 (the
BackdropView captures the screen in the platter's model space); the label copy's items carry `scale(var(--titem-scale))` about
their own centres; the platter itself `scale(var(--tplatter-scale))` about its centre. The filters act in the lens's model space
(the 110 set). Test page: `tab/lens-test-tab.html?tab=1` does exactly this (`PS`, the copies' inverse, `.labels .tabbar span`).

**3. The layers** (formula.md §4b mapped onto the tab lens with its own keys; tab-lens-native.md §0):

| # | layer | what the page does | keys (原值) |
|---|---|---|---|
| 0 | the platter + its normal items | the page; **DestOut #76** (110×70 r35 at the lens frame, opacity 0 → 1 on lift) punches the normal items INSIDE the capsule only — the copy in the backdrop layer keeps the platter + the items with the capsule cut out (`.punch`, `clip-path: path(evenodd …)`, the capsule scaled with the lens) | DestOut cornerRadius 35 |
| rest | `_UITabSelectionView` #30 | the resting selection platter under the items: a backdrop (scale .25) with gaussianBlur 2 (normalizeEdges 1) + colorMatrix (diag 1.185 / 1.150 / 1.195, row bias −.050 / −.005, offset −0.2), 94×54 r27, **opacity 1 → 0 on lift** — material tokens (界面1号 / 材质); it fades as the lens lifts | tab-lens-table.md #30 |
| 1 | BackdropView #27 (marginWidth 0) | `#tab-lens-f-bg-<w>` on the copy of what lies under the lens (page + platter + punched items): stages −10.5 / 7 (glassBackground inner refraction, sampled first) → +9 / 36 (SDF capsule r35, ovalization .5); the layer = the lens box, overflow hidden, samples clamped in the map | displacementMap +9, SDF height 36, curvature 1 |
| 2 + 4 | ClearGlass #34 (−17.5 / 11.2 on portal #36 → SelectedContentView, hidesSourceLayer 1, masksToBounds r35) and ContentLensing #46 (−14 / 11.2 on the 94×54 portal, does not clip) | `#tab-lens-f-lab-<w>` on the label copy (the SelectedContentView copy: the items at 1.16, capsule-clipped BEFORE the filter by the layer's border-radius); u = Δ_L(p) + Δ_C(p + Δ_L(p)) | −14 / 11.2 → −17.5 / 11.2 |
| 3 | glassBackground #41 (marginWidth .667) | the material on top of layer 1: KeyFill .5, ring shadow offset 8 / opacity .1 / stroke 4 / blur 3, ShadowAmount 17.5, BlurDistance0 −10, FaceColorMatrix white 1 / black 0, BleedDarkenBlend light 1 / dark 0 — material tokens; only the −10.5 / 7 refraction is in the map | seg-lift-material.md §2 keys × the tab's three differences |
| 5 | glassForeground #49 (marginWidth 100) | `#tab-lens-f-ab-<w>` on the wrapper of both layers over a plain page copy (16 pt beyond the lens); W/H per frame from the capture box (lens screen frame + 100 each side, clamped to the screen) into `#tab-lens-f-ab-<w>-wh` (`wh_matrix`); blend α = e | aberration 3.6842 / offset 38.889 / angle −0.2618 / edge −14 … 0 / opacity 1 → 0 |
| 6 | KeyFill UISDFView #52 + vibrantColorMatrix | the highlight (keyfill-highlight.md §2; curvature .75, the 22 params as the segment lens) — material | |
| 7 | inner shadow #37 | invertsShadow 1, .06 / r3 / (0, 7), r35 — material | |
| glow | `_UIFlexInteractionGlowContainerView` (platter-sized, white, opacity .845, vibrant matrix) + `_UIFlexInteractionLittleGlowView` (93×93 circle at (87.5, 857.5), white shadow r 46.5, opacity **0 → .2 on lift**) | the platter's lift glow — the segment lens does not have it | tab-lens-native.md §0 |
| pres | `_UILiquidLensView` presentation transform | not used by the tab (the platter carries the 1.0516; the flex stretch during a page change is the lens's own size, sets 112 … 116 or the transform) | |

**4. Motion** (tab-lens-motion.md §0 / §4 — the read curves; the drag rule is unverified):

| state | curve | drives |
|---|---|---|
| lift (press the selected item) | one spring **ζ 1 / response 0.25 s** (ω 25.13) for everything, start = the animation's start (the SDF height's frame) + ≤ 5 ms | size 94×54 → 110×70 (r 27 → 35, the set by w), the filters' scale 0 → S (Backdrop +9 h36, ClearGlass −17.5 h11.2, ContentLensing −14 h11.2), `_UITabSelectionView` α 1 → 0, DestOut α 0 → 1, `--titem-scale` 1 → 1.16, `--tplatter-scale` 1 → 1.0516, little glow α 0 → .2 |
| drop (release) | the same quantities back, **ζ 1 / 0.4 s** (ω 15.71), no delay; the ±1.6 pt wobble 0.25 s after settling is unread — not done | |
| page change (tap another item) | position **ζ .85 / 0.4 s** from the old item centre to the new (86 pt) + the lift spring at the same time + the flex stretch (loupe: width up to 1.15 × 110 = 126.5, peak 126.2 at +0.15 s; height rebound 79.5 at +0.5 s → 73.6 at +0.9 s) | the sets 112 … 116 cover the stretch only up to 116; beyond it the 110 set under a transform (§0.3's rule) until the data session records the drag / stretch frames |
| drag (hold and move) | flex-interaction.md §6 (target = finger, ζ .85 / .2, effective the next tick, + drift (1 − sX)·W/2; loupe min .75 / max 1.15) — **unverified for the tab** | |

**5. Per-frame variables** (one place, the lift progress p from the spring; the page sets them, the CSS reads them):
`--tlens-w` / `--tlens-h` (the model size: 94 + 16p × 54 + 16p; the set = the nearest even w), `--tlens-r` (h/2), `--tlens-x` / `--tlens-y`
(the lens's model position in the platter: 79 + 86·(item index) − 8·… i.e. centre (134 + 86·i, 904) − size/2), `--tplatter-scale`
(1 → 1.0516), `--titem-scale` (1 → 1.16), `--tlens-scale-bg` / `--tlens-scale-lab` (the feDisplacementMap `scale` attribute = the
set's data-s × p; set on the elements, not CSS), `--tsel-alpha` (1 → 0), `--tdestout-alpha` (0 → 1), `--tglow-alpha` (0 → .2),
`--tab-ab-wh` (the fringe W/H: capture box (lens screen frame ± 100, clamped to the screen) width / height → the `#…-wh`
matrix values; 1.72-class numbers for the segment, ≈ 1.08 for a lens at the bottom of the 956 screen), `--tlens-ab-scale` (the
fringe filter's scale: the aberration amount does not appear in the motion trace — not ramped in the read data; at p 0 the layer is
off). Nothing here is a fitted value: every number above is a read key or the read curve; what is not read (the drag rule, the wobble,
the stretch beyond 116) is marked so.

#### 0.8.1 The page's own set family: `tab5/` (2026-09-19, ui2; the wiring itself not yet committed — stopped at the 10:55 order)

The page shows five tabs (状态 / 方舟 / 终末地 / 鸣潮 / 手机); on the 440-pt screen `nav.tabs` is 416 wide (`max-width: calc(100% − 24px)`)
and each button 81.59×54 (read in WebKit: `getBoundingClientRect` of the five buttons: x 16 / 97.59 / 179.19 / 260.78 / 342.38, w 81.59;
`.glide` 82 = `offsetWidth`). The native probe's family (`tab/`, 94×54 → 110×70) is the three-button layout; the lift rule read there is
+16 pt on both axes on one spring (94 → 110, 54 → 70; tab-lens-motion.md §4), the SDF heights stay — so the page needs the family on
its own resting size, on the 2-pt set grid: **`tab5/` = 82×54 → 98×70** (9 sets, w 82 … 98 step 2, h = w − 28, r = h/2, the
lifted set 98 S 48, the path S 40, S_ab 16; the lens model at progress p = (82 + 16p) × (54 + 16p), set = nearest even w; the
0.41-pt difference 82 vs 81.59 is the grid, the box is the set's size). Same recipe as §0.7, only the sizes differ:
`gen_lens_maps.py --formula --name tab --size 98x70 --series 82:98:2 --lift-path 82x54 --label-portal 0 --corner-radius half
--label-region 28x20 --bg-layers=-10.5/7/0.5/lens,9/36/0.5/lens --label-layers=-14/11.2/0.5/lens,-17.5/11.2/0.5/lens
--aberration=3.6842/0/38.889/-0.2618 --edge=-14/0/1/0 --href-prefix assets/lens/tab5/ --out tab5` → `tab5/tab-f-{bg,lab,ab}-<w>.png`
(205 KB), `tab5/lens-filter.svg` (the same ids `#tab-lens-f-{bg,lab,ab}-<w>` — one family per page; the page includes `tab5/`, the
test page `tab/`), `tab5/lens-field.json`. No verification block: there is no measured five-button field (the phase files are the
three-button probe); whether the native lifts a narrower button by the same +16 is UNREAD (marked, not assumed elsewhere).
Peaks: bg 7.8 pt on every set, lab 13.9 (82) → 22.6 (98) pt.

Engine note for the wiring (from `calib/webkit-region-under-scale.html`, only read at ½): the filtered layers must NOT sit under the
platter's 1.0516 transform — the fact is read at scale ½ only, so the wiring lays the lens stack out in screen coordinates (the model
box × 1.0516 about the platter centre, the filter `scale` attribute × 1.0516 — u_screen(p) = 1.0516·u_model(p / 1.0516), the map
stretched over the presented box), the real `nav.tabs` carries `translateX(-50%) scale(1.0516)`; the page copy inside the lens stays
1:1. `backdrop-filter` inside a software-filtered element does not blur (wksnap `bftest`: the fill renders, the blur does not), so the
platter copy inside the lens is a clone of the page under the bar with `filter: var(--glass-filter)` + `var(--glass-fill)` in the
platter capsule.

### 0.8.2 B6-c — the segment lens's edge lines, the asset + the patch text (2026-09-19 11:5x; `B6C-PATCH.md`)

`lens-filter.svg` → `#seg-lens-f-ish` (generated: `gen_lens_maps.py` `filter_inner_shadow`, also `#tab-lens-f-ish` in the tab families
when they are regenerated): the ClearGlass inner shadow #21 as QuartzCore rasterises it — keyfill-highlight.md §5.2c: α = op · M · blur_σ(M −
M↓off), op .06 / offset 7 / σ = shadowRadius 3 — as feOffset → feComposite out → feGaussianBlur → feComposite in → α × .06, on a black capsule
of the lens box. WebKit column x 220 rows 602–613 vs the closed form: within .001 on 602–609, the tail one 8-bit level low (table in
`B6C-PATCH.md` §4); the old CSS inset box-shadow reads .057 on the top rows (the complement construction, ruled out by §5.2c). The other three
items of the order (k without compression — amount uniform 1/.5 − 2 = 0, keyfill §5.1 B6-3; the fwidth AA — per-fragment, ⅓ pt at 3×, equal
to the hard rings at pixel centres on the straight edges and to coverage AA on the arcs, keyfill §2 B6-2; the white stack clipped to the
capsule; the #36 main band on the straight runs only, predict §6.1 rows 5–6) are view.js / index.html numbers of the ui session: written as line + old → new + source in `B6C-PATCH.md` §1–§3, §4b. The regeneration
also restored `lens-field.json`'s `verification` block (it had been emptied by a run without `--verify-*`; §7's command).

### 0.8.3 Tab bar lens — WIRED (2026-09-19 12:xx, ui2; `web/assets/lens/tab-lens.js`, index.html's tab-bar block, the `tab5/` family)

One line in index.html after view.js: `<script src="assets/lens/tab-lens.js"></script>` (`?tlens=0` off → the page's previous glide-scale lift;
`?tlens-ab=0` without the colour fringe; `?tlens-clock=timer|manual` = the offscreen-WebKit instruments below). Nothing in view.js changes:
the script watches the states attachTabBar already writes on the bar (`.glide` gets `lift-sel` +125 ms on the selected item / `lift` +140 ms
on another, its inline left / width = the item under the finger, `nav` gets `drag`, the classes go at the up, `button.on` moves at a
selection) with a MutationObserver on `#tabs` and draws. The filters come from `tab5/lens-filter.svg`, fetched and inserted at load (the
HTML parser — the file's comments carry `--`), then `LENS_SS_APPLY()` / `LENS_ENGINE_FIX_APPLY()` (new hook in lens-engine-fix.js) run over them.

Structure (formula.md §4b with the tab's keys, §0.8 table 3; one fixed element `.tabbar-lens` in screen coordinates — the platter's 1.0516 is
folded into the layout and the filter `scale`, not an ancestor transform of the filtered layers (the region fact is read at ½ only)):
`.stack` (lens box + 16 pt; `#tab-lens-f-ab-<w>` on it, W/H per frame from the capture box lens ± 100 clamped to the screen) holding
`.base` (a plain copy: the page = a clone of `<main>` without ids, the platter = a clone-blurred page under `--glass-fill` + `--glass-rim` in
the capsule scaled with the real one, the items = a `<nav class="tabs">` shell with the `.seg` clone so index.html's own rules dress the
copies; a backdrop-filter inside a software-filtered layer does not blur, README §0.8.1) → `.warp > .disp` (`#tab-lens-f-bg-<w>`; the same
copy, the items outside the capsule + inside at 1 − p = DestOut #76) → `.ish` (`#tab-lens-f-ish`, α × p) → `.warpl > .displ`
(`#tab-lens-f-lab-<w>`; the items at 1 → 1.16 about their own centres, border-radius-clipped before the filter). The real `.plat` / `.seg` /
`.glide` scale 1 → 1.0516 about the platter centre (`--tplatter-scale`), the real `.glide` fades 1 → 0 (`--tsel-alpha`); its old scale lifts are off
under `nav.tabs.tlens`. Model box at progress p = (w0 + 16p) × (54 + 16p), w0 = the item's width (82 here), set = nearest even width of the
family, presented = model × s about the platter centre, s = 1 + .0516p; feDisplacementMap scale = data-s × p × s (the map's model pt →
presented pt; u_screen(q) = s·u_model(q/s)), the fringe taps ±S_ab·k × p × s.

Two generator changes made for it (both families and the segment regenerated; R/G/B of every map unchanged, the fringe maps' A channel new):
* the fringe map's **A = the lens coverage** and the chain's output is `in` it — formula.md §3b out.a = α_elem · cov · ΣA/7: the foreground draws
  nothing outside the capsule; before, the band factor e (B, = 1 outside) let the taps repaint the whole 16-pt margin with displaced pixels —
  invisible on the segment's flat track, a smeared rectangle over the page here;
* the chain's SourceGraphic is also `in` the coverage: the wrapper's margin copy is READ by the outward taps and never shown (the real page
  shows there — no patch around the lens where the copy differs from the live platter). The segment's inline copy in index.html (the ui
  session's) still has the old chain; `lens-filter.svg` here is the new one (`tools/fringe_check.py` on lens-test.html?native=1&lensx=220
  after: share 1.35 %, saturation 81.6 / 75, right end blue above yellow, left yellow above blue — the same as before the change).
* the page clones are clipped (`overflow: hidden` wrappers): WebKit takes an overflowing child into a filter's objectBoundingBox region.

Motion (tab-lens-motion.md §0 / §4 read curves; analytic damped-spring steps, time-based): lift ζ 1 / .25 s on every quantity; drop ζ 1 / .4 s;
press another item while held = position ζ .85 / .4 s + the lift at the same time; the drag retargets the same position spring. Offscreen check
(`?tlens-clock=manual`, `window.__tabLensStep(16.667)` per frame, the states set on the glide by the test script; scratchpad `js-curves.js`):

| curve | t (s) | page | formula | box (presented) |
|---|---|---|---|---|
| lift ζ 1 / .25 (p) | .017 / .05 / .1 / .2 / .3 / .5 | .0667 / .3577 / .7154 / .9605 / .9955 / 1.0000 | .0669 / .3577 / .7154 / .9605 / .9955 / 1.0000 | 83.35×55.26 → 96.90×67.86 → 103.06×73.61 (= 98×70 × 1.0516; native height 73.61) |
| drop ζ 1 / .4 (p from 1) | .017 / .117 / .217 / .317 / .417 / .517 | .9712 / .4532 / .1465 / .0413 / .0108 / .0027 | same to 4 places | 102.43×73.02 → 82.06×54.05 |
| page change ζ .85 / .4 (x 45 → 127) + lift | .017 / .083 / .15 / .217 / .283 / .35 / .55 | 47.42 / 78.54 / 106.52 / 120.85 / 126.15 / 127.44 / 127.09 | 47.42 / 78.50 / 106.51 / 120.85 / 126.15 / 127.44 / 127.09 | p .0667 / .6189 / .8900 / .9722 / .9934 / .9985 / 1 |

Pictures (`remote-mock/v4/lens/tab/`): `tab-held-native-vs-web.png` (native 3-button held vs the page held, light / dark; the page in wksnap
has no backdrop blur on the real platter — the device does), `web-{held,drop,move,held2}-{light,dark}-crop.png`.

The drag (13:0x, the old page's read rule tab-lens-motion.md §6.6, UIKitCore `_animateSelection` + the drag lenstrace rms .55 / max .75): while
`nav.drag` is on and the finger is down, the position target = finger x − a·W + W/2 (a = the press point's fraction inside the item, read from
the bar's own pointer events in the capture phase — view.js's handlers untouched), the left edge hard-clamped to the items' run, spring
ζ .85 / .2 retargeted on every move (continuing value and velocity), no rubber band; after the up ζ .9 / .4 to the item under the finger
(view.js's choice of item). Offscreen check (`js-drag.js`: press at a = .6, ten 6-pt moves, release on item 2): targets 50.76 → 104.76 in
6-pt steps (= finger − .603 × 82 + 41), x 45 → 104.76 settled at +.5 s, the release → 127.02 (item 2's centre 127). The jump to a pressed
item without a drag stays ζ .85 / .4 (the ① trace, §3); the two read values differ and both are kept where each was read.

Not done (next, in this order): the material — KeyFill highlight #52, ring shadow, dark line, the little glow α 0 → .2 (the tab's keys =
seg-lift-material.md §2 × the three differences, the ui session's tokens); the loupe flex sX / sY on the lifted box with drift tx =
sX(1 − sX)·55 (§6.6, read — needs per-axis map scaling, the `-wh`-style colour matrix); the wobble after the drop (unread);
a quick tap's lens (unread — the glide slides as before); the `_UITabSelectionView` copy inside the capture during the ramp (omitted); frame
cost on the device (the data session's 36916a9 reads the fringe chain and the supersampling as the heavy parts on the segment — `?tlens-ab=0`
is the switch here). Engine fact for the geometry: the glide's `offsetLeft` reads its CSS transition mid-flight, so the script reads the
inline `style.left / width` (the target view.js wrote).

**R2 (2026-09-20 03:2x, BOARD round 2, 验收's (b)): the material through `lens-webgl.js`, geometry mode.** `tab-lens.js` puts a canvas over the bar
(nav's box + 24 pt on every side: the lifted 98 × 70 over the 62 bar and the fringe wrapper 16) and drives `LensWebGL` with the tab5 family:
`setsFromFilters("tab", heights)` from tab5/lens-filter.svg (data-s 40, 48 for the 98 set, fringe 16) and tab5/lens-field.json (heights 54 … 70);
the lift rides the 98 set stretched over the growing box (as the segment lens rides its 220 set, §0.3), `pd = lift` (DestOut on the lift
spring, tab-lens-motion §4), `wh` from the capture-box rule per frame, the geometry driver's p / x / W / H fed to setState each frame, lift 0 at
rest (the canvas cleared). The backdrop: the page colour everywhere and the platter's fill (`.plat`'s background-color) as its capsule — the page
under the bar cannot be drawn into a canvas (标不可表达: the blurred page in the platter, the page content the lens would show above the bar);
the items are drawn with their own alpha (`labelsDirect`, a package option added for this: tinted mask icons, tab images, the labels in their
computed font / colour) — no single-ink alpha recovery. Not drawn: the items' 1.16 scale of the SelectedContentView copy (the package has no
label scale: 待做), `_UITabSelectionView`'s own α 1 → 0 (the glide stays the geometry driver's). `?tlens-gl=0` leaves the canvas out.
Offscreen: nine sets loaded, a press on the selected item draws 26 frames on set 98 (34 482 opaque px @2×), cleared at the settle;
`accept-tabbar.js` R2 rows (sets, keys, canvas box, frames / set / pd during a lift, lift 0 at rest, no JS error); headless Chrome 545 / 545.

### 0.8.4 Frame cost of the fringe chain — the lean chain `#…-f-abl-<w>` and the baked 引擎校正 maps (2026-09-19 12:5x, ui2)

Order (监督局 12:2x, after the data session's 36916a9: on the phone the dispersion layer alone makes a drag frame 37–38 ms (19 ms of it),
the supersampling 27–30, both off 18.9; the page's JS is 0–2 ms per tick — the cost is the filter rendering): compute the chain only over
the edge band, no visual constant changed, target ≤ 20 ms; as a switch.

**Engine fact first** (`calib/webkit-primitive-subregion.html` + `.png`): WebKit does not honour a filter primitive's own subregion —
with `primitiveUnits="objectBoundingBox"` the subregion renders blank and the rest of the element half-displaced, with a userSpaceOnUse
subregion the whole element renders blank. Every primitive of a chain runs over the whole filter region; a band cannot be carved out by
regions. Duplicating the lens content into four band-strip elements would re-render the displaced layers four times (their filter region
is their own box, not the strip) — no gain. Reading the chain at half resolution (a half-scale duplicate of the stack) is not the same
output (the fringe colours sample a coarser image) — not done under the 红线. What CAN be cut without changing a single output byte:

`#seg-lens-f-abl-<w>` (and `#tab-lens-f-abl-<w>`, generated next to the `-ab-` chains, same maps): the k = 0 tap is the source itself
(SourceGraphic instead of a scale-0 feDisplacementMap — 7 → 6 displacement passes, the expensive primitive); everything else is the
old chain (the two colour matrices per tap and the ΣA/7 alpha chain stay: folding α/7 into the colour matrices costs ±3 levels of 8-bit
premultiplied precision — measured on a flat colour; dropping the alpha chain changes the ends where a tap reads a transparent pixel —
both tried and rejected). Check (wksnap 3 px/pt, `lens-test.html?native=1&lensx=220` vs `&ab=lean`, light and dark): **0 pixels differ**
(max |Δ| 0 over the whole image). A smaller wrapper (`--abl-margin 8`, the taps reach ≤ peak × W/H = 2.3 × 1.72 = 4 pt) was tried too:
≤ 15 levels of difference on the ends (0.1 % of the lens pixels, light) and on the bottom rim row (dark) — not identical, so the lean
chain keeps the 16-pt wrapper and the `-ab-` map (no extra files; `--abl-margin` documents the trial).
Expected on the phone: one of seven displacement passes fewer — about 1/7 of the chain's 19 ms; NOT ≤ 20 ms in total. The honest number
is the data session's to measure (`?segx=abl` below); the fringe at full fidelity costs six full-region displacement passes in this engine.
The supersampling: its displaced layers cover the whole lens (the bg field is 36 pt deep, the label field the whole portal) — nothing to
band there either.

Switch (the ui session's segment code, one token): where view.js sets `stack.style.filter = url(#seg-lens-f-ab-${set})`, use `-abl-` when
`SEGX.includes("abl")` (?segx=abl), and read the W/H matrix `#seg-lens-f-ab{l}-${set}-wh` accordingly; AM stays 16. The test page: `?ab=lean`.
The engine-fix script now skips every `-f-ab` chain (`-ab-`, `-ab-ir-`, `-abl-`; it used to match `-abl-` as a lens map and re-encode
its fringe map — the first lean run differed by that).

**Baked 引擎校正 (备一手, 验收 12:2x)**: `gen_lens_maps.py --engine-fix-sets 2,3` writes every bg / lab map twice more, `<map>@2x.png`
(k = ½ pt) and `<map>@3x.png` (k = ⅓ pt) with the correction applied BEFORE encoding (`engine_fix(u)`, the same rule lens-engine-fix.js
applies to the bytes at run time), 124 files, 1.0 MB, and marks the filters `data-baked="2,3"`. `lens-map-dpr.js` (one line BEFORE
lens-engine-fix.js: `<script src="assets/lens/lens-map-dpr.js"></script>`) points each such filter's feImage at the file for
devicePixelRatio × LENS_SS (2 → @2x, 3 → @3x; a ratio without a file keeps the run-time fix) and marks it `data-engine-baked`, which
lens-engine-fix.js honours (no blob: URL is made). Check (wksnap 2×, `?ss=0` baked vs `?ss=0&mapdpr=0` run-time): the two differ on 0.3 %
of the lens pixels by one byte step of the map (the correction is rounded once instead of twice: ≤ .16 pt at S 40), i.e. single pixels on
high-contrast edges; the fringe check is unchanged. If the data session's bisection confirms the blob: images as the cost, this replaces
lens-engine-fix.js on the page; if not, the files stay unused. `?mapdpr=0` turns it off. tab-lens.js calls `LENS_MAP_DPR_APPLY()` for its
late filters (the tab families carry no baked sets yet — `data-baked` absent → nothing happens).

### 0.8.5 (a) The fringe chain on two END elements only — built, measured, NOT ≤ 20 ms (2026-09-19 13:5x; 验收 / 监督局 13:0x)

Structure (`lens-test.html?ab=ends`; the generator: `--ab-end 56 --ab-reach 4`, `#seg-lens-f-abe-<w>-l / -r` on the map's end crops
`seg-f-abe-<w>-{l,r}.png` (60 × 76 px = the wrapper's first / last 60 pt, the same bytes as the full map there), also for the tab families):
the main `.stack` carries no chain and is clipped `inset(0 56px 0 56px)` (it draws nothing under the ends, so the ends composite over the
scene exactly as the whole-stack chain did — without that cut-out the capsule's AA row double-composites: +6 … 8 levels along the arc,
measured); two `.fend` elements at the wrapper's left / right, each 60 × 76 pt (filtered box = the visible 56 + the taps' reach 4, the
inner 4 clipped after the filter by `clip-path` — a band pixel's taps read up to 4 pt beyond it and the element's box ends there:
without the reach the last 4 pt showed cyan / yellow tap artefacts at the seam), holding a clone of the whole stack (the same portal
copies, the same clips, the same displaced layers — re-synced in place() by copying every descendant's inline style in DOM order), the
LEAN chain on each with its own W/H matrix. 56 = margin 16 + the arc's band (r 22 + envelope 8.8) + the taps' reach 4 = 50.8 with slack:
with 29 (band + reach only) the corners' band around the arc (up to 30.8 pt in) was cut and the full chain differed up to 149 levels.

Same output? (wksnap 3 px/pt, drag-mid `native=1&lensx=220`, vs the whole-stack chain; light / dark; `?ss=0` — with the supersampling
on, the ½ wrappers inside a software-filtered element are flattened in software while under no filter CA composites them: the middle
then differs by ≤ 9 / 13 levels everywhere along the rim rows, an engine artefact that also separates `ab=flip` from `ab=0`):

| region (lens 110–330 × 110.9–154.9) | light max / px > 3 | dark max / px > 3 | what it is |
|---|---|---|---|
| the ends (x 94–150, 290–346) | 26 / 7 | 3 / 0 | 7 pixels at the seam's corner |
| the seam columns 149–151 / 289–291 | 26 / 7 | 13 / 39 | the step between chain and no-chain on the long-edge band rows |
| the middle (x 151–289) | 1 / 0 (2206 px at 1 level) | 13 / 2481 | **the long-edge dispersion is lost**: the taps' vertical component (θ −15°: ±.35 pt) smears the track's top / bottom edge by up to 13 levels (dark: track 29 on page 0) — the native's "0.3 pt of dispersion along the long edges" (§0d). The premise "带外无差" holds only where the content is uniform across ±4 pt |

So (a) is not the same output: it drops the long-edge smear (≤ 13 levels on one row per edge, dark) and keeps the ends. Covering the
long edges with two more strip elements (17 pt × the middle width, each again holding the displaced layers) brings the computed area
back to ~72 % of the whole — no gain.

Frame time (a VISIBLE offscreen-corner WKWebView, `scratchpad/wk/wktime.swift`: rAF runs at the display rate; the page's own 2-s auto
drag, mean interval; Mac 2× display, body zoom 1.5 = 3 px/pt (the phone's raster) and 3 = 6 px/pt (4× the pixels, above the vsync floor)):

| variant | zoom 1.5 (3 px/pt) mean / max ms | zoom 3 (6 px/pt) mean / max ms |
|---|---|---|
| whole-stack chain `ab=flip` | 29.3 / 58 | 170 / 233 |
| ends only `ab=ends` | 20.2 / 34 | 81.6 / 112 |
| no chain `ab=0` | 16.7 / 18 (the vsync floor) | 17.0 / 36 |
| lean chain `ab=lean` | — | 160 / 212 |

Above the floor the ends cost 42 % of the whole chain (65 vs 153 ms at 6 px/pt: the 47 % area plus the duplicated displaced layers).
Projection for the phone from the data session's 36916a9 (no chain 18.9, whole chain +19): ends ≈ +8 → **≈ 27 ms**, not ≤ 20; the
lean chain saves another 1/7 of that. Verdict: (a) does not reach the target and is not the same output → the WebGL prototype
(§0.8.6) is the path; the switch stays in the test page for the record (`?ab=ends`), nothing wired.

### 0.8.6 WebGL prototype of the whole chain — `lens-webgl-test.html` (2026-09-19 14:0x; 验收 / 监督局 13:1x order)

Why: the SVG software filters cannot carry the full-fidelity fringe at frame rate on the phone (§0.8.4–0.8.5). The same chain in two
fragment-shader passes on the GPU, every constant from the decompiled documents (its source is in the shader comment next to it), the
backdrop drawn by the page into textures (not the DOM): `web/assets/lens/lens-webgl-test.html?state=rest|lift|mid&theme=light|dark[&dpr=3]`.

Backdrop textures (canvas 2D at devicePixelRatio): the page bg, the scene card (20, 72.56, 400, 148.98) r 26, the control (20, 116.89, 400, 32)
r 16 in `--track`, the resting flat platter 196×28 r 14 (rest only) — and, in a second texture, the labels alone (13 px system font, 早班
weight 500, centred at x 120 / 320, y 132.89) — all read from lens-test.html?native=1 in WebKit, so the lens sits at the same coordinates
(mid: 110–330 × 110.89–154.89; lift: 10–230). Fields: the existing maps `seg-f-bg-220.png` / `seg-f-lab-220.png` (B = coverage) and
`seg-f-ab-220.png` (Δ × e, B = e, A = coverage) as textures, sampled bilinearly (CA samples bilinearly — the SVG engine's nearest fetch and
one-pixel quantisation, README §0.4, do not exist here; no engine correction; the label ends' closure and clamp are in the maps, §4b.1).

Pass 1 (an FBO over the wrapper = lens ± 16 pt): per fragment (page pt) — the backdrop copy through the bg map (BackdropView +9/36 after
glassBackground −6.6/4.4, samples clamped in the map) with the DestOut punch (the labels only OUTSIDE the capsule at the source position,
§4b); glassBackground's ring shadow (keyfill §4: black α = .1·[N((d_r + 4)/3) − N(d_r/3)], d_r = the SDF of the capsule shifted 8 down, inside
and outside) and built-in KeyFill dark line (keyfill §5.1: EffectOffset −.6667, Height 1, dir (1, 0), S = −.5, amount uniform 0, colorBias
−.3, prof mix(1, 1 − e, .75), aa by fwidth, rgb' = rgb·(1 − .3·k·(3 − 2·rgb))); the label copy through the lab map (ContentLensing −8.8/7.04
then ClearGlass −17.5/11.2) clipped to the capsule at the destination (portal #20, 1-px AA by fwidth); the inner shadow #21 (keyfill §5.2c:
.06·M·blur_σ3(M − M↓7), computed once into a texture on a 1-pt grid over ±9 pt). Pass 2 (the canvas): the page, then over the wrapper the
7-tap dispersion (formula §3b.3 / 3b.7: taps at ±kΔ, k = 1, ⅔, ⅓, 0 with the R / G / B weights, Δ from the map × (W/H, H/W), W/H from
the capture box lens ± 100 clamped to the screen, screen = e·edr·(R/2, G/3, B/2) + (1 − e)·below, edr 1), then the #36 KeyFill highlight
(keyfill §2: three emits — main band h 1 / cos .174 / curvature .75, diffuse key and fill h 8 / cos .615 / bias 11.33 — each source-over
through V(b) = min(1, .9118·b + .1471); the AA ±fw/2 by fwidth). Lift progress p scales the amounts, the shadow / line / highlight α (p = 0
at rest → nothing drawn). Drag: the lens follows the pointer directly (no spring — a rendering prototype); 「自动拖 2 s」 as lens-test.

Checks (`tools/fringe_check.py`; the page rendered at the phone's raster — `?dpr=3` and a wksnap at scale 1.5 = 3 px/pt, measured as is
(`--lens 110,110.89,220,44 --scale 3 --measure 0`); a 2× canvas upscaled in a 6-px/pt snapshot reads 1.31 % / 74 — the resampling blurs the
fringe, so those earlier numbers were the instrument's, not the page's); pictures `remote-mock/v4/lens/webgl/webgl-states.png`,
`webgl-{rest,lift,mid}-{light,dark}-3x.png`):

| | share of the outer 12 pt | saturation mean / median | ends' colour order |
|---|---|---|---|
| native (light / dark) | 1.36 % / 1.38 % | 69 / 62 · 71 / 63 | right blue above yellow, left yellow above blue (dark reversed) |
| SVG chain, ss + engine fix, 3 px/pt (lens-test.html?native=1&lensx=220) | 1.37 % | 82.9 / 76 | same |
| **WebGL light, 3 px/pt** | **1.79 %** | **92.4 / 87** | right blue above yellow, left yellow above blue ✓ |
| **WebGL dark, 3 px/pt** | **1.69 %** | **88.2 / 84** | reversed ✓ |

The exact chain (bilinear, no engine quantisation) disperses MORE than the SVG one (whose negative lanes run one device pixel short) and both
more than the native: the order and the band's extent are right, the strength is not — formula.md §3b.8's open item (the source's contrast).
The candidate "a capture scale below 1 on #33" is CLOSED by the data session's read (uiprobe-sdf-exp9-{light-page,dark-flat}.json, 14:xx):
#33 glassForeground CABackdropLayer scale 1 / contentsScale 1 / rasterizationScale 1 / zoom 0 / marginWidth 100; #25 glassBackground all 1
(marginWidth .667); #11 BackdropView all 1 — no capture below 1× in the native lens group (only the nav pocket's blur backdrop is .5). Not tuned.

**Device (the data session, fb7bbdc, 3× standalone, `tools/touch/seg-webgl-fb7bbdc.md`)**: frame rate — mid, light, the 2-s auto drag: 125
frames, mean **16.4 ms**, max 19, no frame > 20 (the page's own rAF mean 17.0 / max 37, gl.finish 0.07 ms); fringe light **1.63 % / 88.3 / 78.5**,
dark 1.57 % / 83.1 / 76.0, the ends' order right (native 1.36 / 69 / 62; the Mac 1.79 / 92.4); the judge table: the edge rows 601 / 646 =
native; the end line's column at the right end 327 vs native 328 (the whole 1 pt left); column x 220 after the backdrop's own offset (the
test page's canvas track is 10 levels brighter than native light / 22 dark, subtracted): light 602 −5.3 / 645 −11.0 / 646 +5.2, dark 602
−5.5, 603–610 +4 … +6, 645 −10.5; the right 「班」 height 14.33 vs 15.0 (dark 12.33 vs 12.0); the left 「早」 box = native but ink 751 vs 569
(dark 477 vs 376); 「早班」 ink rest / lift / mid light 905 / 925 / 760 vs native 905 / 941 / 586, dark 778 / 709 / 484 vs 856 / 773 / 379 — the
text under the glass keeps more ink than native (native lightens it 35 % in the mid state, the shader 16 %). Open, not tuned: the label
copy's own lightening (a key on the portal / ContentLensing layer — opacity, a colour matrix — not in the read chain), the 1-pt end shift,
the edge rows' 5–11 levels.

Frame time (a visible WKWebView on the Mac, the page's 2-s auto drag; `?dpr=` sets the pixel count):

| pixel count | rAF interval mean / max | draw → gl.finish mean / max |
|---|---|---|
| 2× (Mac) | 17.0 / 57 ms (the first frame) | 0.1 / 1.0 ms |
| 3× (the phone's) | 16.8 / 31 | 0.1 / 1.0 |
| 6× (4× the phone's) | 16.8 / 34 | 0.1 / 1.0 |

vsync-bound at every size; the GPU work is far under the budget (gl.finish returns in ≤ 1 ms). The phone: the data session's standalone
measurement (rAF interval + fringe_check + predict-seg-hold's judge table). `window.__segLens` carries t / x / v / target / dt / phase / set /
lift / w / h / frame / gpu_ms for seg-frames-logger.js.

Not in the prototype (listed, not hidden): the lens's own motion (the springs, the flex stretch — view.js's loop would drive lensX / p);
the scene's paragraphs above and below the control (lens-test.html has them; the native probe's content differs anyway); the label
texture is canvas text (the same font and size; its vertical placement is `textBaseline: middle` at the DOM's line centre — to be read
against lens-test's glyph rows at the same coordinates); the DestOut / lift ramps of the SVG page's first frames (§4.1) — p is 0 or 1 here.

### 0.8.7 `lens-webgl.js` — the WebGL lens as a package, the interface for view.js (2026-09-19 14:5x; 验收 / 监督局 13:4x, 界面1号's face 14:3x)

`web/assets/lens/lens-webgl.js` (the shaders of §0.8.6 verbatim; `lens-webgl-test.html` is its harness — `?ui=1` drives it through this very
interface). The interface 界面1号 asked for, implemented as asked:
```
<script src="assets/lens/lens-webgl.js"></script>                                   // after the inline <svg> and lens-engine-fix.js
const L = LensWebGL.create({ canvas, assets: "assets/lens/", set: 220, dpr: devicePixelRatio });
     // canvas = the page's wrapper element in .segctl (the lens box ± 16 pt, the same place / size as .stack; the page sets its left / top /
     //   width / height per frame, alpha on); the sets are read off the page's inline <svg> (#seg-lens-f-bg-<w> …, data-s, the plain files
     //   behind lens-engine-fix.js's blob: copies via data-href-orig) — the map table of every width the page has; `set` = the one preloaded;
     //   without an inline <svg>: assets + seg-f-{bg,lab,ab}-<set>.png with S 40 / Sab 12. Returns null when webgl2 is missing; throws on a
     //   shader / link failure → the page's fallback to the SVG stack (its ?gl=0 switch)
await L.ready;                                                                       // shaders compiled, the preloaded set's three maps uploaded
L.setBackdrop({ region: { x, y, w, h }, ink: [r, g, b], page: (ctx) => {…}, labels: (ctx) => {…} });
     // 2D callbacks in PAGE pt (the context is translated to the region): "page" = everything under the lens except the segment labels
     //   (the body colour, the track's rounded rect from computed style, the resting flat platter while p = 0), "labels" = the labels
     //   alone (the real buttons' font / weight / colour / position); region = the page rectangle the two textures hold (the control's row
     //   ± the lens's reach, e.g. the control's box ± 64 pt); ink = the labels' colour (the alpha recovery, below). Call it again when the
     //   value, the theme, the labels or the size change.
const gpuMs = L.draw({ lensX, lensY, w, h, p, pd, wh, platter: { rgba: [r, g, b, a], alpha } });
     // every frame, uniforms only: lensX / lensY = the lens box's page top-left (the canvas sits at lensX − 16, lensY − 16), w × h = the
     //   model box (the nearest set; the canvas backing is resized when w / h change), p = the material progress (the displacement amounts,
     //   the lines, the highlight, the shadows — 0 draws nothing), pd = the DestOut α (the capsule's alpha over the real content: §4.1 /
     //   §4.3's ramps — 1 while held), wh = W/H of the capture box (§3b.6, the page's abFrame rule), platter = the resting platter
     //   (restingBackground #5, _controlForegroundColor) as { rgba, alpha: 1 − p } — drawn inside the capsule above the displaced backdrop
     //   and below the lines / labels (界面1号 ⑥; not in the backdrop texture). Returns the CPU→gl.finish ms (opts.finish: true) — L.stats.
```
Outside the capsule the canvas paints α only (界面1号 ⑤): the ring shadow (black α) and the dark line's row as a black α equal to the
darkening those two terms apply to the colour under them (read from the copy at that pixel) — the live DOM and its labels are the
"outside" of the DestOut punch, nothing of the copy is drawn there, no AA edge is composited twice.
The flex stretch stays the page's (a CSS transform on the canvas, as on .stack). `window.__segLens` stays the page's loop's. The canvas paints
only the capsule (opaque × pd) and, outside it, black α — the rest is transparent, the live DOM shows through; the copies have to match
the DOM inside the capsule only. Position the canvas on whole pt (the page already puts the control's top on a whole pt): a fractional
layer position resamples the canvas by up to a pixel.

Engine facts met while packaging (in the file's comments): an FBO's row 0 is the viewport's bottom — pass 2 reads pass 1 and the inner-
shadow texture with a flipped t (the prototype's first pictures had the labels upside down: 验收's first check); macOS WebKit smooths canvas
text only on a canvas attached to the document (detached: the same 13 px glyph's ink box 108.5–131.33 instead of the DOM's 107.67–132),
so the scratch canvases are attached off-screen while drawn, and the labels' alpha is recovered per pixel from the opaque page and
page + labels renders (P = Pg·(1 − a) + ink·a). Check at 6 px/pt (`?dpr=6`, wksnap scale 3 = no resampling): the undisplaced right label's
ink box = lens-test.html's DOM text exactly (308–332 × 127.5–139, 4394 px both); the left label inside the lifted lens 107.67–132 ×
127.5–139.17 (DOM 127.5–139.0; 4283 vs 4355 px) — the label row is closed to ⅙ pt. The wrapper is snapped to the device grid so pass 2's
bilinear read of pass 1 lands on texel centres. `?ui=1` on the harness renders the same lens through this interface (the harness's control
sits on a fractional y, so its canvas is resampled — on the page the top is a whole pt).

The harness's own form still works: `create(canvas, { sets, backdrop(ctx, which), ink, width, height, dpr })`, `setState({ cx, cy, w, h,
lift, pd, wh })`, `redrawBackdrop()`, `backdropCanvas()`; `LensWebGL.setsFromFilters("seg")` builds the set table from the inline <svg>.

### 0.8.8 The three device residuals of the WebGL lens, audited against the documents (2026-09-19 14:3x; 监督局 / 验收 — checked, not tuned)

**① The fringe's strength (device 1.63 % / 88 vs native 1.36 % / 69; `seg-webgl-fb7bbdc.md`).** The shader's chain against formula.md §3b.7 item
by item: the seven taps at ±kΔ with the R / G / B weights k/2, (1 − k)/3, k/2 ✓ (FS2); Δ = the fringe map's ratio-1 vector × (W/H, H/W) with
W/H from the capture box (§3b.6) ✓; the envelope e = saturate((d + 8.8)/8.8) with EdgeOpacityStart 1 / End 0 ✓ (the map's B, generated by
that formula) × cov (A) ✓; [depth < 24.444] = 1 inside ✓; edr 1 ✓; α_elem 1, ΣA/7 = 1 ✓; the composite screen = e·edr·(R/2, G/3, B/2) + (1 −
e)·below ✓ (FS2 `col`); the source "below" = pass 1 = glassBackground's output (the displaced backdrop with its ring shadow and dark line) + the
label copy + the inner shadow ✓ (§3b.6's list); the order above it: the #36 highlight through the vibrant matrix ✓. Nothing of §3b.7 is
missing or out of order. What the shader does NOT carry, listed for the old page / the data session: (a) the #36 vibrantColorMatrix is the
grey-axis form V(b) = .9118·b + .1471 — the read matrix is .9118·S(1.29) + .1471 (seg-lift-material.md §2: a 1.29× saturation on the
highlight rows; applying it would raise, not lower, the saturation there); (b) glassBackground's Shadow term (ShadowAmount 11 / Offset (0, 7)
/ Opacity .001 / Radius 8 — opacity .001) and BlurDistance0 −10 (BlurOpacity0 0), FaceColorMatrix white 1 / black 0 (identity for the lens —
keyfill §5.1), all ≤ 1 level; (c) the capture-scale candidate is closed (#11 / #25 / #33 scale, contentsScale, rasterizationScale all 1).
The remaining difference tracks the SOURCE the taps read: the test page's own track (10 levels brighter than native light / 22 dark, the data
session's note — the page's DOM colours replace it in the wiring) and the label copy's extra ink at the ends (② — the fringe's share is
measured over the outer 12 pt where the torn labels sit; more edge contrast in the source → more colour after the taps: §3b.8's "source
contrast" item). Nothing to change in the chain.

**② The text under the glass keeps too much ink (mid: native 905 → 586 = −35 %, WebGL 905 → 760 = −16 %; the left 「早」 751 vs 569).** The
label copy's path in the read chain (seg-lens-refraction.md §1b tables 2–3, §1c): the segment content → portal #20 (`liftedContentViewPortal`,
matchesOpacity 1, sourceLayerOpacityScale 1, cornerRadii 22, masksToBounds 1) → the ClearGlass layer #17 (displacementMap −17.5, SDF 11.2)
→ the ClearGlass inner layer #16 (cornerRadii 22) + the inner shadow #21 → portal #32 (hidesSourceLayer 1, matchesOpacity 1, masksToBounds 0)
→ ContentLensing #29 (−8.8, SDF 7.04) → the glass group. No opacity < 1, no colour matrix, no vibrancy on that path in the dump (the only
vibrantColorMatrix is #36's, the highlight; the only shadow #21's). So the native's lightening is not a colour key: it is the geometry — the
two-stage field tears the glyph at the ends (§0c: 「早」 compressed / torn at x 110–119, −37 %). In the shader: the composed field from the
lab map ✓, the clamp to the last texel centre (§4b.1) ✓, the stages' masks (the map's B) ✓, and — fixed here (7d314ca → this commit) — the
source clip BEFORE the displacement (portal #20's r22 mask at the SAMPLED position, 先裁再位移, the SVG page's `.displ` border-radius): a
sample that lands outside the capsule now reads transparent. It changes the corners, not the count: mid 「早班」 ink 1110 → 934 at 3 px/pt
(−16 %, unchanged) — the samples the map sends stay inside the capsule. What is left is the FIELD's own tearing magnitude at the ends
(README §1b rounds 1–2 and the §4b check: the formula composition puts 「早」's box where the native's is, its ink count does not follow —
"an ink count cannot separate the two"); the device now says the shader keeps 32 % more ink than native on that glyph. The old page's
closed-form check (15:2x, `remote-ref/label-end-tear-closed-vs-map.md`, `tools/lens/end_tear.py`): the map = the §4b.1 closed form to
≤ .10 pt (the quantisation ±.078 + the bilinear ≤ .03; compose_stages vs the scalar form 1.4e-14), the only block being the outermost ⅓ pt
(closed u(0) 9.21 / B .5, the map 8.00 / 1.0 — the 2-px/pt texel centre at .25 pt misses the edge drop: the generator's sampling, not the
clamp); the same 「早班」 bitmap through pass 1: closed form 80 % of the resting ink, the map 80 %, the device's WebGL 84 %, the native 65 % —
the map carries the closed form faithfully, the closed form is 30 % away from the native; and the native's end field (the drag-mid phase
data) has NO fold at all (u .87 … .38 on the centre line, 7.6 → 1.5 on the ±10 rows, monotone): the nested sampling's tear is not in the
native, which is weaker and flatter there, so its 35 % is an INTENSITY term (candidates: the seven taps' weights on black text, the
KeyFill band's V lift, the copy-over-backdrop composite), not a displacement one. Open with the old page / the data session (whether CA
nests the two displacement maps — SampleMapFilter around 0x1c3991ab8 unread; or the A9 switch: L2 alone / L4 alone at the end).

**③ The right end 1 pt left (the end line's column 327 vs native 328; the left end 111 = native).** The shader's capsule: u_lens = (110,
110.891, 220, 44) → the SDF's zero line at x = 330.000 (sdf: q = |p| − (88, 0), the right cap centred at x 308, r 22); the dark line's band d ∈
[−.333, +.667] → x 329.33 … 330.67 on the right (its centre 330.0), 109.33 … 110.67 on the left (centre 110.0) — symmetric to the pt. The
harness's lens (`?state=mid`) is the same box as lens-test.html?native=1&lensx=220. A 1-pt asymmetry is not in the geometry the shader is
given; candidates the data session can separate on the same frame: which line "端线列" reads (the dark line, the light line at 329.83 …, or
the label's edge), and the canvas's own placement on the phone (the harness's canvas top is fractional, 94.891; x is 94 — whole).
**Warm-up (14:5x; 监督局: the wired page's first glass frame stalled 46–55 ms on a tap / a light drag, 0 on the second gesture — `seg-webgl-78284dd.md`):**
`lens-webgl.js` now draws one lifted frame through both passes when `ready` resolves and after every `setBackdrop` (into the FBO and the
canvas, finished, the canvas cleared in the same task — the cleared buffer is what gets presented, which also allocates the layer's display
surface), `L.stats.warmMs`; `?glwarm=0` / `{ warm: false }` off. The page's own earlier prewarm (a lift-1 setState) did not cover the first
one or two gestures after a reopen (the data session) — the textures a gesture's `setBackdrop` uploads are the remaining first-use cost,
now warmed right after each upload. For the data session to re-read on the same gestures.

**The platter fade's start (监督局: the page's fade begins 13–17 ms later than the native's):** seg-lens-refraction.md §4.4 — the lift GEOMETRY
spring (bounds 196×28 → 220×44, position, DestOut cornerRadius, BackdropView 0 → 9) is called at +110 ms after the down (tap: +171), the
MATERIAL spring (the white platter UIView#5 opacity 1 → 0, DestOut opacity 0 → 1, the highlight, ClearGlass 0 → −17.5, ContentLensing
0 → −8.8) at +121 ms (tap: +181), both ζ 1 / .25 s: the platter's fade starts 11 ms AFTER the growth. The `platter.alpha` the page hands
draw() should be 1 − p_material with p_material on that second spring (+121), not the geometry's; the page's model is view.js's.

**The right end's line (the data session on 78284dd, row 616, 3 px/pt):** the box is right (both ends' zero lines = native); the dark line
at the right end is 3× deeper (211 → 83 vs 213 → 168) and 10 px wide (vs 4), spreading inward from x 324.7 — hence the 1-pt centroid shift.
In the harness (`lens-webgl-test.html?state=mid&dpr=3`, 3 px/pt, the row 8 pt above the centre = 616's) the two ends are identical: left
231 / 180 / 185 / 205 (x 110.67 …), right 215 / 185 / 180 / 231 — min 180 both, 2 px wide; the right end's deep wide feature is where the
page's stretched 「班」 reaches the rim rows (the harness's centre row shows the glyph's ink at x 330–332 too). To be compared on the same
row between the harness and the page (the page's labels / lens box are the page's inputs).

**R8 (2026-09-20 02:4x, BOARD round 2 — the right end's 1 pt, cause hunt):** the device's row 616 (seg-dragmid-compare-d02487f.md, 3 px/pt,
light): native 325:214 326:212 327:205 **328:179** 329:209 330:228 (a 1-px dip, 2 px wide); the page 324:202 325:165 326:100 **327:83** 328:139
329:201 330:228 (min 83, 6 px = 2 pt wide, from 324.7 inward; dark: native a 27 → 45 bump at 327–328, the page 34 / 59 / 120 / **150** / 89
at 324–328). The same row in the harness (`?state=mid&dpr=3`, the composited snapshot at 3 px/pt, the same box and labels): right 328.33: 205
· **328.67: 183** · 329.0: 196, left 111.0: 183 — one column, symmetric, the native right end's shape. Four label variants (as is, both regular,
the right label weight 600, no labels) give the identical row (the row is 2.3 pt above the label ink on both device and harness, so the label
copy is not in it); the maps, the shader and the box are the same files on both. So the cause is not the maps, not the labels, not the
geometry: it is only on the device, at the right end only — an engine / GPU difference in rendering the pass-2 rim terms there. Not
reproducible on the Mac, so not fixed; three A/B switches for the device instead (数据, the same row 616 on each): `?glab=nodark2` (the outside
dark line of pass 2 off — in the harness the whole rim dip is that term: 227 / 236 without it), `?glab=noring2` (the outside ring off),
`?glab=nofringe` (the dispersion taps off). Whichever switch flattens the page's 324–329 feature names the term; the default render is
byte-identical to before (0 diff at 3×). 待读 until then.

### 0.8.9 GL prewarm — what is moved off the first glass frame (2026-09-19 15:0x; 验收 / 监督局: the wired page's first glass frame stalled 46–55 ms)

What a WebGL lens pays the first time, and where `lens-webgl.js` now pays it instead (each step timed with gl.finish into `L.stats.prewarm`;
the numbers = the Mac at 3× (`?dpr=3`), a warm shader cache unless noted):

| step | when it used to hit | now | ms (Mac 3×) |
|---|---|---|---|
| shader compile + link (3 programs) | create() (idle) — but the driver may defer the pipeline to the first draw | create(), then the prewarm draw finishes the pipelines | `compileMs` 8–21 (350 on a cold cache) |
| the set's three maps → textures, the inner-shadow FBO (361-tap pass) | the set's load, on `ready` | same, finished (`mapsMs_<w>`, `ishMs_<w>`) | 1 / 0 |
| the backdrop textures (page, labels; the alpha recovery loop) | `setBackdrop()` / `redrawBackdrop()` — a gesture's first frame if the page calls it there | same call, then a prewarm frame right after it (`backdropMs`) | 13 (the control's row region) / 56 (a whole-page region) |
| the pass-1 FBO allocation | the first draw | the prewarm's first draw, ONCE at the canvas size (`fboMs`; a smaller wrapper draws into its top-left, `u_ascale`) | 0 |
| the canvas backing store | every frame the wrapper's size changed (`canvas.width =` reallocates: the lift's bounds change every frame) | allocated ONCE at the largest wrapper the sets can need (ui form: max width + 32 × 80; the CSS size is set by the package, the page moves the element only) | — |
| the first pass-1 / pass-2 draw (pipeline warm-up, texture first use) | the first glass frame | the prewarm draw: one lifted frame (the preloaded set, lift 1, pd 1, the current backdrop) through both passes, gl.finish after each (`pass1Ms`, `pass2Ms`) | 0–3 / 0–17 |
| the layer's display surface | the first presented frame | the prewarm ends with clear() + finish: the cleared buffer is presented (`clearMs`) | 0 |

`L.prewarm()` runs it on demand; it also runs by itself when `ready` resolves and after every `setBackdrop()` / `redrawBackdrop()` (a theme /
value / size change re-uploads the backdrop textures, so the frame after it is warmed too); a real frame drawn before a warm-up is put back
after it. `?glwarm=0` / `{ warm: false }` off. The page: create + setBackdrop at idle, keep the canvas (never destroy / recreate it), call
`L.redrawBackdrop()` (or setBackdrop) when the value / theme / labels change — nothing else. Nothing in the chain changed.
The data session's read of the wired page before this (78284dd): the page's own lift-1 prewarm did not cover the first one or two gestures
after a reopen — consistent with the backdrop upload and the per-frame backing reallocation being the remaining first-frame costs, both
moved here; to be re-read on the same gestures (tap up + 83 / + 129 frames, the drag's lift).

### 0.8.10 a20df11's two regressions (2026-09-19 15:1x; the site rolled back to the SVG stack) — what they were, package side

**① The white platter missing on the first lift frame, half on the second, right from the third.** Not a lag of the uniform (draw() sets
u_platter on the frame it is given). The package composited the WHOLE capsule × pd (the DestOut α: §4.1's .396 / .98 / 1 on the first three
lift frames) — so on frame 1 the lens's output, platter included, was 40 % over the page's DOM, whose own resting platter the lift hides.
The native's DestOut punch does not scale the lens's output: it removes the real content UNDER the lens progressively, i.e. it fades the real
labels out of the BackdropView's capture. Fixed (this commit): pass 1's source punch is `labels × (1 − M(q) · pd)` (the labels inside the
capsule at the source fade with pd), pass 2's capsule is opaque whenever p > 0. The platter and everything else are unaffected by pd now.

**② The dark theme's left 「早」 losing its first 5 pt (box 113.33 / 18.67 vs 78284dd's 109.33 / 22.67; light right).** Not the source clip:
in the harness (`?state=mid&dpr=3`, 3 px/pt, dark and light) the glyph's box and ink are identical with the #20 clip at the sampled position
on and off (`?srcclip=0`): light 107.67–120.67 / 321 px, dark 107.67–120.67 / 298 px — the map's samples for that glyph never leave the
capsule, so the clip has nothing to cut; and nothing in dc2af2a / d3a6dce depends on the theme. What does depend on the theme in the
package is the labels' alpha recovery, which needs the labels' ink colour: a = (P − Pg)/(ink − Pg) — with the light theme's black handed
over in the dark theme (white glyphs on a dark track) the recovered alpha collapses wherever a glyph is anti-aliased: thin strokes go first,
the 「早」's left strokes are the thinnest. Package side (this commit): the ink is detected from the renders themselves (the colour of the
pixel the labels changed most); a given `ink` is used only when it is within 48 levels of the detected one (`L.stats.ink` tells which). For
界面1号 to confirm on the page: the value of `ink` passed in the dark theme at that frame.
**The tap path's first glass frame (d02487f on the device: the drag's first frame is fine after the prewarm, +113 / +118 vs native +116 / +119;
a tap's — commit → render → the first lens frame — still 47 / 50 ms):** what sits on that frame and not on the drag's is the value flip's
`redrawBackdrop` (the labels' weight changes): draw the two 2D canvases, read them back, the alpha recovery loop, two texture uploads —
on the Mac 19 ms for the control's row at 3× (draw 3, the loop 13, upload 2), more on the phone. Now: `redrawBackdrop()` and a later
`setBackdrop()` DEFER the work to the next task (setTimeout 0) and draw the frames until then with the previous textures, then prewarm
again — the native crossfades the label's weight / contents over 0.2 s (seg-lens-refraction §4.4), so one frame with the old label is inside
its own transition; `{ sync: true }` draws at once (the harness; a setup call before any frame is sync by itself). The scratch canvases are
kept and re-used (`willReadFrequently`), the textures re-uploaded in place, the loop skips the pixels the labels did not touch
(`stats.prewarm.backdropDrawMs / AlphaMs / UploadMs`). The device's re-read of the tap path is the check (the data session).

**The tap path's remaining stalled frame (ee169d2 on the device: up + 82 / 83 → 38 / 60 ms, the next frame fine; 监督局 15:3x):** what the
package still did on a gesture frame and not before it — the lens starts a lift at 196 × 28 and grows to 220 × 44, and `setState` asked for
the nearest SET of the current width: 196, 198, … — none loaded (only 220 is preloaded), so each width's three maps were fetched, decoded,
uploaded and its inner-shadow pass (361 taps) rendered — with a gl.finish for the timing — in the microtask of the load's arrival, i.e. on
whichever gesture frame the images landed (one to three frames into the lift: up + 82 fits). The drag path (a press on the selected segment)
draws at 220 from its first frame and never asks for another set. Fixed (this commit): (1) any width ≤ the preloaded set's uses that set,
stretched over the box — the lift rides the 220 set with the scale ramp, README §0.3's rule, the SVG page's behaviour; only the drag stretch
(> 220) has its own sets; (2) those sets are loaded one per idle slot after the first prewarm (`preloadAll: false` leaves them to first
use); (3) no gl.finish on a load's arrival except the preloaded set's. Instrument for the device: `?gltrace=1` (or `{ trace: true }`) puts a
gl.finish after every step of every frame — bind FBO + program 1, uniforms + binds, pass 1, clear + program 2, uniforms + binds, pass 2 — into
`L.stats.trace` (`stats.traces` keeps the last 60); the page can copy `L.stats.trace` into `window.__segLens` so seg-frames-logger.js records
it per frame (the data session has no JS entry on the device otherwise). On the Mac every step reads 0 ms (the 1-ms clock).
**The ghost lens after a re-render (验收 17:xx: a lifted capsule at the left half, over the resting platter, gone on reload):** the package's
bug. A warm-up frame is drawn with setState, which stored it as `last`; the NEXT warm-up (a re-render's deferred redrawBackdrop → warm)
captured that stored warm-up state as "the frame to put back" and re-drew it after its clear — the lifted capsule at the canvas's top-left
(16 … 236 × 16 … 60 pt: the warm-up's own geometry), left on screen. Reproduced in the harness (rest → redrawBackdrop → prewarm: 51 834 opaque
pixels), fixed: a warm-up frame never becomes `last`, and after a warm-up the canvas is either restored to a REAL lifted frame or cleared.

**The same ghost after a theme switch (验收 17:5x, the 17:48 build with the fix above: the switch open / off re-render is clean; light → dark
clean; dark → light leaves the same capsule):** the theme handler (view.js `matchMedia("(prefers-color-scheme: dark)")` → `redrawBackdrop()`,
not setBackdrop) goes through the same deferred redraw + warm-up. The Mac WKWebView does NOT reproduce it — the deployed package in the deployed
page (`?demo=1`, one segment, a press-and-release, then the appearance switched dark → light with the window shown and with it hidden, `wktheme`)
reads 0 opaque pixels after every step and the snapshot shows the clean control — so the phone-side mechanism is not pinned down here. What
the package could still do to put a warm-up frame on screen is now removed structurally: a warm-up never draws the canvas at all. Its pass 2
goes into FBO B (canvas-sized, allocated on the first warm-up), the canvas keeps whatever the page last drew or cleared (a live gesture's
frame is not blinked; a rest canvas stays transparent), and only an instance's first warm-up clears the canvas (the display surface's
allocation). The restore-the-last-frame logic is gone with it (no `last` state at all). One more guard on the page's side of the contract:
`setState` clears only at lift ≤ 0 again (fb84a7e cleared below .005, b313aed below .001; both WRONG — §0.8.12: the page hides its own platter
while it keeps `.lift`, so the canvas must draw until the page itself sends lift 0; the frames of the tail are an opaque copy of the backdrop
and the page is responsible for ending them with lift 0, which its loop does at settle). The numbers below were computed for 验收's question
what a frame at lift .005 / .001 is in pixels; they still hold, they just do not license a package-side bound.
What a frame at a tiny lift differs from rest by, computed from the inputs (lift 0 → 1 = 196×28 → 220×44 is linear in the page's `w = W0 + 2·LX·q`,
`h = H0 + 2·LY·q`, LX 12 / LY 8; the shader's displacement = decode(map)·S·p; the shading terms ring .1, dark line, inner shadow .06, highlight
emits and the fringe envelope are all × p):
* box: 24·p × 16·p pt → p = .005: 0.12 × 0.08 pt = 0.36 × 0.24 px @3x (0.18 / 0.12 px per side); p = .001: 0.024 × 0.016 pt = 0.072 × 0.048 px.
* displacement: the 220 set's maps hold at most |u| = 5.002 pt (bg), 9.401 pt (label), 2.338 pt (fringe) at p = 1 (read from seg-f-bg/lab/ab-220.png
  bytes, (byte − 128)·S/255 with S = 40 / 40 / 12 from lens-filter.svg data-s) → p = .005: 0.025 / 0.047 / 0.012 pt = 0.075 / 0.141 / 0.035 px @3x
  (fringe × W/H 1.72 = 0.060 px); p = .001: 0.015 / 0.028 / 0.007 px. All below one device pixel by an order of magnitude: no edge moves a pixel,
  the bilinear read blends ≤ 14 % of a neighbouring texel at the label map's largest value.
* shading: each term ≤ its full-lift maximum × p — ring .1·p = .0005 (0.13 of a level), dark line .3·k·c(3 − 2c) ≤ .3375·p = .0017 (0.43 level),
  inner shadow .06·p = .0003 (0.08 level), the highlight emits and the fringe envelope ≤ 1·p = .005 (1.3 levels at most, on the rim only).
* measured (renderer output, the harness at 3×, light, the lens box ± 30 pt, against the rest frame): p = .001 → max 1 level of 255 (1 648 px at 1,
  none at 2); p = .005 → max 1 level (5 902 px at 1); p = .01 → max 2 levels (110 px at 2). One level is below what the 8-bit display shows as a step.
* time: the fall material spring (ζ 1 / .4 s, springStep's critically damped closed form x = (1 + ωt)e^{−ωt}, ω = 2π/.4) passes .005 at 473 ms and
  .001 at 588 ms after the fall starts — 115 ms (7 frames at 60 Hz, 14 at 120 Hz) in which the .005 bound showed the DOM where the .001 bound shows
  the copy; per the numbers above the two are within 1 level of each other.
Harness: `js-ghost.js` / `js-ghost2.js` (rest → redraw → warm, lifted → redraw → warm, a gesture ending at lift .0017 → setBackdrop dark /
light, dark → light at rest) all 0 opaque pixels except the real lifted frame, which the deferred redraw leaves intact (51 824 px before
and after); the mid render (light / dark, @3x) is identical to the previous commit (max diff 0).
### 0.8.11 The first lens gesture after load (2026-09-19 18:xx; 数据 seg-final-181053.md ①, then the instrumented re-record) — observed once, not reproduced, nothing changed

**The observation (v=181053, the simulator's standalone clip, one-segment demo, a press on the selected segment as the first lens
gesture after load — the page had been open a while, one dialog opened and cancelled before it):** ~190 ms of main-thread silence around
the down, the lift's first frame "one step for two". Read from the data session's record (`ark-segframes-abc-fceb5de.json`, times from
the recorder's capture of the down):
* −144 ms: the recorder's last normal frame; the frame due at −127 did not come; the down was dispatched at +5 → the main thread was busy
  from ≤ −127 until the dispatch, ≥ 127 ms, with NO `seg:` mark inside (the prewarm `seg:prewarm-build` — which had run at load + 0.4–0.6 s —,
  the engine fix `seg:enginefix`, the build `seg:build`, the upload `seg:gl-upload` are all marked; none of them was there). So not the
  package's warm-up or uploads, not the page's build; the owner is not in the record.
* +5 … +16: the recorder's own down work (its reading() forces layout) and the other press handlers, 11 ms.
* +16 … +46: `seg:build` 30 ms (the second gesture of the run: 0 ms) — segLens's construction, page side, first execution.
* +54 … +71: the first tick 17 ms (second gesture: 1 ms) — the gesture's first GL frame (p = .0012 already draws a full frame in the
  0c84158 package); the prewarm had run at load + 0.5 s, the gesture came much later.
* The "two steps in one": view.js counts the 109 ms lift delay from the touch's timeStamp; the touch was dispatched ≥ 127 ms late, so the
  lift was already due at tick 1 and tick 2 integrated the clamped 40 ms step (p = .28 at +94).
127 + 11 + 30 + 17 ≈ 190. The Mac does not reproduce any of it (a real mouse press on the deployed page in a WKWebView: `seg:build` 1 ms,
first tick 5 ms, no gap before the down; `scratchpad/wk/wktheme`, built for this: load, run JS, switch the appearance, hide / show the window,
press through the window server, snapshot).

**The instrument (ui2 6dbd2f9, `web/seg-frames-logger.js` only):** every pointer entry carries `lag` = performance.now() − event.timeStamp
at the capture listener (how long the event waited for the main thread); the page's render() / updateLive() are wrapped as
`seg:page-render` / `seg:page-updateLive` measures; Long Tasks would be re-emitted as `seg:longtask` (WebKit reports
`longtask_supported: false`). With it the data session re-recorded a cold first gesture (a TAP on an unselected segment this time; host load
3–4): down `lag` 36 ms (one 46 ms frame's wait), `seg:build` 2 ms, `seg:gl-upload` 0 — no block before the down; the 190 ms did not recur.
Conclusion (监督局): no evidence, no change; the package and the page stay as they are.

**What the tap record does show, package side, for when it is wanted:** the down frame of a tap is 46 ms with 2 ms of marked work in it.
The rest is the deferred backdrop redraw (segGlRedraw → redrawBackdrop → the setTimeout-0 task: two 2D canvases, the label alpha recovery, two
texture uploads, then a warm-up) — it runs in the task after the handler, before the next frame, and `seg:gl-upload` measures only the
synchronous part. On the Mac that task is backdrop 4–11 ms + warm-up 6–8 ms; the phone's number is not measured (a `seg:gl-redraw` measure
around the deferred task would give it). It exists only on the tap path (the drag path does not redraw at the down), and only because the
labels texture must carry the weight of the segment about to be selected (`futureOn`). The way to take it off the down entirely: draw and
upload one labels texture per possible selection at idle (n segments → n textures, once after the prewarm) and at the down only switch which
one is bound — no draw, no alpha pass, no upload, no warm-up. Two package calls (prepareLabels(i, draw), useLabels(i)) plus one page-side
line at the down; not done, not scheduled.

### 0.8.12 The flash at the end of a tap on 190821 (2026-09-19 19:3x; the user's phone; 监督局's forensic order) — the package's rest bound, reverted

**Symptom:** on v=190821 a tap on 「早班」 flashes once at the end; 181053 does not. The two differ, lens-wise, by fb84a7e / b313aed (warm-up
offscreen, lift < .005 then < .001 clears the canvas) and the page's 5d71467.
**Evidence (tick by tick):** the deployed tree run whole in an offscreen WKWebView (`?demo=1`), a press-and-release on the unselected segment,
the page's own loop stepped with `loop.step(16.7)` through the whole tap (lift → fall → rest); per tick: the loop's p, whether the control
carries `.lift`, the DOM platter's computed background (`.segctl.lift .lens{background:transparent}`, index.html), whether the package drew or
cleared (`stats.frames`), and the canvas's opaque pixel count (offscreen nothing is presented, so readPixels reads the real buffer).
190821: ticks 0–4 p = 0, no `.lift`, DOM platter white; tick 5 p = .067, `.lift` on → DOM platter transparent, canvas 31 324 px (the canvas is now
the platter); ticks 40–52 the fall's tail p .0169 → .0011, drawing; **ticks 53–74 (22 ticks = 367 ms at 60 Hz): p .0008 → 0, `.lift` still on
(view.js's frame() keeps it while p > 0) so the DOM platter stays transparent, and the package — p < .001 — clears: no platter anywhere, the
white capsule is gone**; tick 75 the loop settles, the page's clear() removes `.lift`, the DOM platter is back. 181053 (0c84158, p ≤ 0 clears):
0 such ticks, the last draw is the p = 0 tick, the same frame as the page's clear. 190821 with the one line put back to `p <= 0`: 0 such ticks.
**Lesson:** rest is the page's call. The page decides when the DOM platter shows (`.lift` off, in its clear()) and tells the package with lift 0;
the package must draw until then. A package-side "small enough lift" bound, however well it is justified in pixels (§0.8.10), breaks that
contract. Fixed: `p <= 0` again. The fixed check: `scripts/mac/seg-tap-platter-check.sh` runs the sequence above against web/ and fails on any
tick where the control has `.lift` and the canvas is clear (the page's platter hidden and the package's gone) — run it before any change to
the rest / clear logic on either side.

### 0.8.13 R31 — the tap's down frame without a backdrop redraw: label variants (2026-09-20 02:xx; BOARD.md round 2)

§0.8.11 ③: on the tap path the page redrew the backdrop at the down (futureOn: the labels with the segment about to be selected in the
selected weight) — two 2D canvases, the alpha recovery, two uploads and a warm-up in the task after the handler; ~40 ms of the down frame on
the phone. Now the package keeps one labels texture per selection: `prepareLabels(key, labels)` draws the page canvas once more and the labels
with the caller's callback `(ctx2d, info) → void` (info.region as for setBackdrop), recovers the alpha against the page render, uploads into a
texture kept under `key` (re-used on the next prepare of the same key) and records `seg:gl-prepare`; `useLabels(key)` binds that texture for the
following frames — a variable assignment, nothing drawn, nothing uploaded; `hasLabels(key)` tells whether it is there. The live texture of
`redrawBackdrop` / `redrawNow` stays the default; a redraw drops every variant (the page's content changed) and sets `stats.labels = "live"`;
`stats.labels` = the bound key otherwise. The deferred redraw task records `seg:gl-redraw-task` (redrawNow + warm-up) and every redrawNow
`seg:gl-redraw`, so the frames recorder shows where a redraw ran.
Wiring (view.js, the ui session's line): after the prewarm, at idle, `for (i of segments) lens.prepareLabels(i, (x, info) => drawLabels(x, i))`
where drawLabels draws the labels with segment i as the selected one (the futureOn drawing); at the down on segment p: `lens.useLabels(p)`
instead of `segGlRedraw(seg)`; at the commit the selection is p, so the bound texture already matches (the deferred redraw at segSync may stay
as a safety net — it re-prepares nothing, the page prepares again at idle); after a render / theme change: prepare again at idle.
Harness: `prepareLabels("bold", …)` → 1 seg:gl-prepare; `useLabels` → 0 redraw measures, 0 frames; a frame with the bold variant differs from
the live one (7 648 px @2x); after `redrawNow` the variant is gone and the render equals the live one (0 diff). The accept row (accept.js 分段
section) exercises the API on the page's instance; the page-path row (a tap's down frame with no seg:gl-redraw-task) goes in with the wiring.

### 0.8.14 R37 — the fringe's "source" item read: CA's sampler for the label copy, mips, and the map's quantisation (2026-09-20 04:xx; BOARD round 2)

The question (formula.md §3b.8): the band's label ink is grey on the native (darkest G 36–44 in the ±1 pt box), black on the web (9), the chain's gain is
the same on both (.48), so the saturation difference (69 vs 85) is in the SOURCE the seven taps read. Three reads, in `remote-ref/glass-displacement-formula.md`
§3b.9 with the addresses: **①** `displacement_map_lpf` samples both its textures through one constexpr sampler, `0x7bff0000082a49` = clamp_to_edge,
`filter::linear`, `mip_filter::nearest`, implicit-LOD `sample()` — decoded by compiling one probe sampler per field with the same Metal compiler version
that built QuartzCore's library (32023.921; the bit layout is in `tools/air_sampler.py`, which also lists every function of a `.metallib` and decodes
its samplers: the ten sampler states of `default.metallib` are in its output). **②** intermediate surfaces are allocated without mip levels unless a
surface flag is set (`MetalContext::create_surface_with_properties` +0xb9c / +0xc6c); which filter inputs get the flag is unread — bounded: mips act
only where the sampling is minified (the ends' compression zone s ∈ [6, 11.2]); the platform (magnified ×55) reads level 0 either way, so the band's
grey is not a mip. **③** the web's 8-bit 2 px/pt label map is not the term either: the field evaluated per pixel in float in FS1 (`lstage` / `gOval`
— formula §1 + §2 composed like `gen_lens_maps.py compose_stages`, coverage fw ⅓ pt, the ⅙ pt clamp, the amounts riding the lift) gives, on the Mac
harness at 3 px/pt with §3b.8's judge (`scratchpad/r37_sat.py`): share 1.52 → 1.52 %, saturation 89.8 → 89.1, darkest G 7.6 → 7.5, gain .48 → .48.

Wired: the float field is the default (`opts.labMode` / `?gllab=map` returns to the map; `stats.labMode`, `stats.labelStages`, `stats.rmax`); the
capsule radius is a uniform (`opts.rmax`: the segment lens 22 clamped to h/2, the tab lens h/2 — before this the tab overlay's outline terms (ring,
dark line, KeyFill, DestOut punch, source clip) used r 22 on a 70-pt capsule: fixed); `tab-lens.js` passes the tab family's stages −14 / 11.2 →
−17.5 / 11.2 and each set's model box (lift path = the set, stretch = 110×70). What is left for the source item: the device says rest 905 / 905 and
lift 941 / 925 agree, only drag-mid differs (586 / 760, seg-webgl-fb7bbdc.md §3) — the same end-zone term as R38 (`label-end-tear-closed-vs-map.md`
§0 item 4); next reads listed in §3b.9 (the mip flag's origin; L2 / L4 alone on the probe; the nested evaluation in `CA::Render`). The Mac harness's
own label bitmap is 13 % heavier than the native crop's (WebKit macOS rasterisation) — a Mac-only difference, not the phone's.

### 0.9 Page sheet (#picker) — B7 visual package (2026-09-19; tokens + a static test page, not wired)

Sources: `remote-ref/sheet-native.md` (the data session's 10th order: A9 `sheetivars` / `corners` / `subtree` / motion, iOS 27.0 3×) and
`remote-ref/sheet-native-formula.md` (the old page session's UIKitCore decompilation §0–§9; §7b = the `#picker` rules). Delivered:
* `web/tokens.css` → the `--ios-pagesheet-*` block (light + dark), one line per value with its source: geometry (top 62, height 894),
  corners (top 38 = `minimumEdgeAttachedCornerRadii` TL/TR, bottom 62 = the display corner via `_environmentCornerRadii`, the curve
  continuous), background (systemBackground 255 / (28,28,30) elevated), the shadow layer (`_UIRoundedRectShadowView` alpha 0, shadowOpacity
  0 / radius 2), the dimming (black .2 / .48 = `_dimmingViewColor`; α × (1 − offset/894) while dragging), the grabber (60×4 capsule,
  spacing 6; NOT drawn: `__hasGrabber 0`), the medium ratio (.56 / .63 — large only here), the metrics (topOffset 10 / 8, side padding 25),
  the Done button (44 disc at (376, 82), inner 36, the check 24×22.67 at (386, 93), systemBlue tint, SDF r 22, KeyFill as the segment lens;
  press glow ζ 1 / r .1, release glow ×4 ζ 1 / r .5, the check α .2 → 1 in 0.47 s), the title (93.67 / 20.67, Semibold 17), the
  appear / dismiss spring (ζ 1 / response 0.3441442 s, ω₀ 18.257), the release rule (1000 pt/s → ζ .8; projection 0.099 s; boundary
  447; pan hysteresis 10) — and the UNREAD list (E, the medium formula, the velocity estimator, the grabber colour / distance rule, the
  corner animation, the scale-down behind).
* `web/assets/sheet/sheet-test.html` — the sheet as static geometry (dimming + sheet + title + Done disc with an approximated check
  glyph) from those tokens, standalone metas, the page behind = the probe's Modals page colour so the dimmed rows compare 1:1;
  `web/assets/sheet/geom_check.py <native> <web> [--dark] [--out png]` reads both frames at the same coordinates.

Against `tools/touch/sheet-native-{light,dark}-presented.png` (3×) — wksnap 440×956 @6 (`sheet-cmp-{light,dark}.png`, native above ours):

| item | native light / dark | ours light / dark |
|---|---|---|
| sheet top row (x 220) | 62.0 / 62.0 | 62.0 / 62.0 |
| dimmed rows 0–56 at x 220 | (194,194,198) / (0,0,0) | (194,194,198) / (0,0,0) — exact |
| top-left corner contour vs a circle R 38, mean |Δ| rows 62–100 | 0.49 (the continuous curve: row 62.17 x 39.33 vs the circle's 34.3, 63.17 30.0 vs 28.7, 64.17 25.67 vs 25.3, ≤ 0.3 from row 65) | 0.06 (a circular corner: rows 62.17 / 63.17 / 64.17 at 34.33 / 28.67 / 25.33) — **the continuous curve's first 2 rows differ by 5 / 1.3 pt; CSS has no continuous corner and its formula is unread** |
| the Done disc's box | 375.67–420.33 × 81.67–126.67 (AA) / 376–420 × 82–126 | 376–420 × 82–126 |
| the check's ink box | — / 389–407 × 95.33–113.33 | — / 389.17–406.83 × 96.5–112.5 (the shape approximated) |
| the title's box | 177–263.33 × 97.67–113.67 | 177.17–263.83 × 97.83 (dark 98.0)–113.67 |

Not in the page (and not claimed): the Done disc's glass material (the 26 glassBackground keys unread; a flat systemBlue disc here), the
nav bar's material, the content of the sheet, the motion (the tokens carry the springs; nothing animates here), the continuous corner curve.

## 1 Source (measured-resampling mode, record): the native segmented lens's own field (data session, 2026-09-19)

`~/Money/styl-work/remote-ref/seg-lens-refraction.md` §0/§2 and `tools/touch/seg-phase-{gx,gy}-{light,dark}.json` — renderer-output
sampling on the system `UISegmentedControl` (iOS 27.0 simulator, lifted 220×44 r 22): a period-8 grating under the control, the
lifted frame demodulated against a reference built from the lens's own outside row / column (`lens_phase.py`); `u` = content
position − screen position (pt) at screen position `s`, per channel R/G/B, `amp` = demodulation amplitude. gx: rows −16 / −8 /
0 / +8 / +16 pt from the lens centre (x displacement); gy: columns ±30 / ±50 / ±80 (y displacement). Light and dark are the same
field (mean |Δ| 0.02 pt, max 0.47), one map set serves both.

What the field says (unlike the tab-bar lens, which magnifies 1.22): **horizontally no magnification** (|s| ≤ 80: u within ±0.5,
M 1.00 — the centre row carries a constant ±0.5 pt level step across the middle, not a slope; `lens-field.json` reports the local
slope, 1.00), the ends within 24 pt bend to ±3.4 pt (M 0.84–0.88 then 1.2–1.5 in the outermost 4 pt) with a rainbow band (R−B up to
3.6 pt); **vertically the content is squeezed to 0.82** (u = +0.22·s inside), the top / bottom 12 pt bend to ±3.4 (M 0.82 → 1.29)
with a thin colour fringe (0.2–0.3 pt). The label copy inside the lens is **not** displaced (§2.3: width ×1.00–1.01, height ×1.00,
centre 0) — the ContentLensingView's own displacement only reaches the portal's edges — so the label must sit in an unfiltered
layer above the filtered copy. Layer amounts for reference: ClearGlass −17.5 / SDF height 11.2, ContentLensing −8.8 / 7.04
(`seg-lift-material.md` §1); they are inside the measured composite and are not used as numbers here.

## 1b Label layer — DERIVED, not measured (2026-09-19, one round per the acceptance session)

`--label-from-bg 0.503,0.629,196x28` writes `seg-map-label-{r,g,b}.png` and `#seg-lens-warp-label`: the backdrop field with its amplitude ×
0.503 and its edge band compressed towards the boundary × 0.629 — the native ContentLensingView shares the ClearGlass SDF shape and
differs only in amount (−8.8 vs −17.5) and SDF height (7.04 vs 11.2), both 原值 (`seg-lens-drag-mid.md` §0 标签场逐点剖面); the label
field itself could not be measured (no grating under a label). Apply it to the label copy only. `lens-field.json` → `label_layer`.

Check against the native mid-drag state (lens centre x 220 over the divider, `seg-lens-drag-mid.md` §0c), headless Chrome 440×956 @3x,
`lens-test.html?native=1&lensx=220&label=warp` (control at x 20…420, segment centres 120 / 320 like the probe), ink = pixels darker
than 110 (light) / lighter than 150 (dark) in the label box, rest = the same page without the filters:

| item | native (§0c) | web light | web dark |
|---|---|---|---|
| 左「早」ink under the left end | −37 % (compressed / torn at x 110–119) | +11 % (bolder: the lighten merge thickens anti-aliased edges), no compression | −5 % |
| 右「班」glyph height | 11.33 → 15.0 pt (+37 %) | 11.67 → 12.0 | 12.0 → 12.0 |
| colour fringe, right / left end (track row) | 7.7 / 1.7 pt (dark 8.0 / 1.3) | 0 / 0 | 0 / 0 |

The derivation is far too weak: the backdrop band is ±3.4 pt over the last 24 pt, halved that is ±1.7 pt on a 12-pt glyph, and the
uniform grey track shows no dispersion at all. The native label bending is a different regime — the label portal (196×28) sits 12 pt
inside the lens ends / 8 pt inside its top and bottom, so its own SDF edge (height 7.04) lies exactly where the labels are when the
lens straddles the divider, and bends them by ±37 %. Reproducing it needs the label portal's own field (a grating rendered as segment
content), not a scaled copy of the backdrop's. Shots: `~/Money/styl-work/remote-mock/v4/lens/dragmid/web-dragmid-{light,dark}-{full,zoom}.png`.

Maps, edge: the field is continued outside the capsule from the nearest boundary point (clamp-to-edge) instead of dropping to 0 —
the lens clips those pixels, and the drop made every boundary pixel a ≥ 1.5 pt step (195 / 200 / 198 steps in the top / bottom 20 px
rows of r / g / b before; the acceptance count read 133 / 108 / 97). After: 0 steps in all six maps (`lens-field.json` →
`jumps_ge_1.5pt_top_bottom_20px`); the native's long edges show 0.3 pt of dispersion and no stray points (§0d). verify_lens_maps.py
unchanged: gx mean 0.04 pt, gy 0.07 pt, 100 % ≤ 0.3 (the check samples inside the capsule only).

### 1b, round 2 — the band on the portal geometry (2026-09-19)

`--label-from-bg 0.503,0.629,196x28,196x28`: the label portal is a 196×28 capsule centred in the 220×44 lens (inset 12 / 8,
`seg-lens-refraction.md` §2.3); a point d inside the portal boundary reads the backdrop field d / 0.629 inside the backdrop boundary
at the corresponding boundary point (same x on the straight edges, same angle on the end circles), the backdrop's uniform interior
part (0.218·y) removed so the portal's centre stays undistorted (§2.3), × 0.503; outside the portal clamp-to-edge. Still DERIVED.
Same check (headless Chrome, `?native=1&lensx=220&label=warp`):

| item | native (§0c) | round 1 (lens-shaped band) light / dark | round 2 (portal band) light / dark |
|---|---|---|---|
| 左「早」ink | −37 % | +11 % / −5 % | +15 % / −1 % |
| 右「班」height | 11.33 → 15.0 (+37 %) | 11.67 → 12.0 / 12.0 → 12.0 | 11.67 → 12.0 / 12.0 → 12.0 |
| colour fringe right / left end | 7.7 / 1.7 pt (dark 8.0 / 1.3) | 0 / 0 | 0 / 0 (dark 3.3 / 0 on the glyph rows) |

Not reached either: the derived band peaks at ±2.0 pt (0.503 × the backdrop's ±3.4 → ±1.7, plus the dispersion offsets) over
the portal's last ~7.5 pt, which moves a 12-pt glyph by a fraction of a pixel row; the native tears 「早」 apart and stretches 「班」
by a third, i.e. its portal displacement at the edge is an order of magnitude larger than the backdrop band scaled by the amount
ratio — the amount ratio does not carry over to the visible displacement (the SDF height changes the gradient, not only the
band width). Shots: `remote-mock/v4/lens/dragmid/web-dragmid-r2-{light,dark}-{full,zoom}.png`. The data session is measuring the
portal field directly (A3); when it lands, `gen_lens_maps.py --field` on that pair replaces the derivation.

## 1c Label layer — MEASURED portal fields (data session A3, 2026-09-19) — 采样替代（直量）

The derivations of §1b are superseded (kept as records). The label copy inside the lens is now displaced by the label portal's own
fields, measured by the data session with a grating rendered as segment content (`seg-lens-drag-mid.md` §5), resampled exactly like
the backdrop (masking, gap filling, interpolation between the measured rows / columns, clamp-to-edge; no symmetrisation, no scaling):

| set | files (`remote-ref/tools/touch/`) | rows y / columns x (pt from the lens centre) | maps | filter |
|---|---|---|---|---|
| lifted, at rest position | `seg-phase-label-gx-light.json` + `seg-phase-label-gy-light.json` | rows −10 … +10 (step 5); columns 0, ±30, ±60, ±90 | `seg-map-label-lift-{r,g,b}.png` | `#seg-lens-warp-label-lift` |
| dragged to the divider (lens centre x 220) | `seg-phase-label-dragmid-gx-light.json` + `-gy-light.json` + `-gy-ends-light.json` | rows −10 … +10; columns 0, ±30, ±60, ±90 and the ends ±96, ±100, ±104 | `seg-map-label-drag-{r,g,b}.png` | `#seg-lens-warp-label-drag` |

Coordinate system: both sets are in the lens box (220×44 r 22, the same box the backdrop maps use; the portal 196×28 sits centred in
it, the field outside the portal is the measured value there, clamp-to-edge outside the lens). Apply the filter to the 220×44 label
layer (the label copy inside it, shifted by −(lens position)) — the filter region is the element's own box, so it must be the lens
box, not the 400-wide copy. Encoding as the backdrop (byte = 128 + u·255/32). The validity floor for these gratings is 0.25 × the
median amplitude (they fade to 0.25–0.5 in the last 6 pt of the portal, where the field is largest; `--label-amp-floor`). Dark
fields are the same as light (the data session measured light only; the backdrop's dark/light agreement is 0.02 pt).

What they hold (seg-lens-drag-mid.md §5): lifted — inside the portal u ≡ 0 (M 1.000), the last 6 pt of the ends compressed to 0.58
and the top / bottom 6 pt to 0.54; dragged — the last ~10 pt of the ends pulled outward (|s| 86–98: M 1.0 → 1.44, beyond u ±3.9 /
±7.7), vertical magnification 1.20–1.29 at the ends, R−B 3.0–3.6 pt (≈ 8 pt colour fringe).

Switching between the two sets — 接线占位，等原理 (a wiring placeholder until the decompiled shader / SDF principle says how the
portal field changes with the lens geometry; not a measured or decompiled rule): the lifted set at the rest width 220, the drag set
at the stretched drag width (244 … 253, `seg-lens-drag-mid.md` §0 过程), a cross-fade of the two filtered label layers by the lens
width in between. When the principle is decompiled (the old page's shader formula), both fields and this switch are computed from
it and the placeholder goes.

Check (`verify_lens_maps.py --field … --label-lift … --label-drag …`):
```
### seg-map ← seg-phase-gx-light.json, seg-phase-gy-light.json (amp floor 0.5)
A. seg-map-r.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-g.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-b.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
B. decoded map vs the original phase samples (valid samples, all rows / columns / channels):
   gx (x displacement, rows): n=3042 mean |Δ| 0.04 pt, median 0.03, ≤ 0.3 pt: 100 %, worst 0.30 at offset 0 G s=110 (sample +0.70, map +1.00)
   gy (y displacement, columns): n=810 mean |Δ| 0.07 pt, median 0.06, ≤ 0.3 pt: 100 %, worst 0.27 at offset 80 G s=-21 (sample -1.36, map -1.63)
### seg-map-label-lift ← seg-phase-label-gx-light.json, seg-phase-label-gy-light.json (amp floor 0.25)
A. seg-map-label-lift-r.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-label-lift-g.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-label-lift-b.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
B. decoded map vs the original phase samples (valid samples, all rows / columns / channels):
   gx (x displacement, rows): n=3048 mean |Δ| 0.01 pt, median 0.00, ≤ 0.3 pt: 100 %, worst 0.35 at offset 10 B s=-101 (sample -5.74, map -5.40)
   gy (y displacement, columns): n=821 mean |Δ| 0.09 pt, median 0.02, ≤ 0.3 pt: 91 %, worst 0.72 at offset 60 B s=-14 (sample -3.98, map -3.26)
### seg-map-label-drag ← seg-phase-label-dragmid-gx-light.json, seg-phase-label-dragmid-gy-light.json, seg-phase-label-dragmid-gy-ends-light.json (amp floor 0.25)
A. seg-map-label-drag-r.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-label-drag-g.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-label-drag-b.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
B. decoded map vs the original phase samples (valid samples, all rows / columns / channels):
   gx (x displacement, rows): n=3129 mean |Δ| 0.01 pt, median 0.00, ≤ 0.3 pt: 99 %, worst 0.61 at offset -10 R s=-107 (sample +6.76, map +6.15)
   gy (y displacement, columns): n=1464 mean |Δ| 0.10 pt, median 0.05, ≤ 0.3 pt: 91 %, worst 2.35 at offset 100 B s=-17 (sample -7.37, map -5.02)
```
The worst points sit on the portal edge where adjacent samples differ by 7 pt (the map pixel centre falls between them) — every
mean is ≤ 0.10 pt, 88–100 % of the samples are within 0.3 pt.

Mid-drag check vs `seg-lens-drag-mid.md` §0c (`lens-test.html?native=1&lensx=220&label=drag`, headless Chrome 440×956 @3x, both
filters on their 220×44 layers; ink = pixels darker than 110 light / lighter than 150 dark in the glyph box rows 116–150):

| item | native (§0c) | web light | web dark |
|---|---|---|---|
| 左「早」ink | −37 % (compressed / torn at x 110–119) | +41 % (smeared outward over the same 10 pt, stretched to 15.7 pt tall) | +1 % (height 11.33 → 14.0) |
| 右「班」height | 11.33 → 15.0 (+32 %) | 11.67 → 15.33 (+31 %) | 12.0 → 14.33 (+19 %) |
| colour fringe right / left end | 7.7 / 1.7 pt (dark 8.0 / 1.3) | 0.67 / 2.0 pt | 7.67 / 7.67 pt |

The right label's stretch now matches; the left glyph is displaced by the right amount but the web smears it (point-sampled
displacement of anti-aliased strokes plus the lighten merge thickening edges) where the native compresses it — an ink count cannot
separate the two, the zoom `web-dragmid-measured-ends-4x.png` shows it; the fringes read 2 / 0.7 pt on the light page (the native's
8 pt band is measured on the grating, ours on black glyphs) and 7.7 / 7.7 on the dark page. Shots:
`remote-mock/v4/lens/dragmid/web-dragmid-measured-{light,dark}-{full,zoom}.png`, `-ends-4x.png`.

## 2 Resampling (no analytic model)

Each profile is masked where `amp < 0.5·median` (platter ends) and, on the centre row, within |s| ≤ 20 (the 「早班」 glyph, §2.1);
G is made odd-symmetric in s (u(−s) = −u(s)); R and B keep their measured offset from G (the chromatic offsets have an even part
near the top / bottom rows that odd symmetry would cancel); gaps are filled linearly. `u_x(x, y)` interpolates between the measured
rows by y, `u_y(x, y)` between the measured columns by x, clamped outside the sampled offsets (|y| > 16 uses row ±16, |x| > 80
column ±80 — the capsule ends beyond the outermost column are the only extrapolated region); zero outside the capsule. A field
measured on another lens size can be stretched by normalised coordinates (`--stretch`, placeholder use only).

## 3 Encoding and the filter

`byte = 128 + round(u · 255 / S)`, S 32; x → R, y → G, B = 128, A = 255; zero is byte 128 exactly in every channel (with
`255·(.5 + u/S)` a 1e-3 residual rounds to 127 or 128 per channel and the point sampler paints colour fringes on every glyph edge).
The browser decodes `S·(byte/255 − .5)` = u + S/510, a constant 0.06 pt shared by all channels. `feDisplacementMap`:
`P'(x,y) = P(x + scale·(R − .5), y + scale·(G − .5))`, scale in user units; the filter region is the element's own box (`x=0 y=0
width=100% height=100%`) and each `feImage` is stretched to it (`preserveAspectRatio="none"`); `color-interpolation-filters="sRGB"`.
Per-channel maps carry the dispersion: `feColorMatrix` isolates one channel of the source → `feDisplacementMap` with that channel's
map → `feBlend lighten` merges the three (the ui session's pipeline). Apply to the OPAQUE copy of what lies under the lens; the
interior scale (1.00 × 0.82) is in the field — no CSS zoom; the label copy goes in an unfiltered layer above. Animate the `scale`
attribute 0 → 32 with the lift curve of `seg-keys.css` (§4.1 of seg-lens-refraction.md: every lens quantity shares that curve).

## 4 Check (`python3 verify_lens_maps.py --field <gx>,<gy>`)

```
A. seg-map-r.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-g.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
A. seg-map-b.png 440×88 S 32: decoded − resampled field max |Δ| = 0.063 pt (one byte = 0.125) OK
B. decoded map vs the original phase samples (valid samples, all rows / columns / channels):
   gx (x displacement, rows): n=3042 mean |Δ| 0.04 pt, median 0.03, ≤ 0.3 pt: 100 %, worst 0.73 at offset 16 B s=103 (sample +0.73, map +0.00)
   gy (y displacement, columns): n=810 mean |Δ| 0.07 pt, median 0.05, ≤ 0.3 pt: 100 %, worst 0.32 at offset 80 R s=-21 (sample -1.31, map -1.63)
```
A = the encoding round trip; B = the decoded map against every valid original sample of every row / column / channel. The gx
worst point is the boundary pixel at s 103 of row 16 (outside the capsule in the map, on it in the sample).

## 5 Kinematics: `gen_seg_keys.py` → `seg-keys.css`

The lens motion is compiled from the native per-frame data instead of hand-tuned curves. Inputs: `seg-lift-frames-light.json`
(lenstrace of a press on the selected segment: lift + in-place release, seg-lens-refraction.md §4.1 / §4.3), `seg-native-abc-frames.json`
+ `touch-local.uiprobe-abc.json` (drag follow B, drop after the drag C), `seg-native-tap-frames.json` (commit after a tap D).
Output: `<ms> <value>` key lists (tokens.css convention) + `linear()` easings + `@keyframes` for the size ratios:

- lift: starts down + 109 ms, 220×44 at + 359 ms (250 ms); w, h, DestOut r, the displacement amount (= filter `scale`) and the
  platter fade all sit on one progress curve (w vs h differ ≤ 0.004, amount ≤ 0.012) → `--ios-touch-segment-lift-keys/-easing`
  (+ `-w-keys`, `-h-keys`, `-warp-keys`, `-platter-keys`, `-destout-keys`)
- release in place: every delay counts from the up to that animation's last unchanged frame (key 0 = the value still at rest,
  like the lift): geometry + 31 → 196×28 by + 281 ms; displacement + 31 → 0 by + 581; platter + 31 → 1 by + 515; DestOut + 198
  (still 1 there; .841 at + 215) → ≤ .006 by + 598 → `--ios-touch-segment-release-*`
- drag follow: a first-order lag τ 88 ms fits the lens centre with rms 10.4 pt, a damped spring ω 22 / ζ 0.95 with 7.1 pt; the lens
  stretches (w up to 253) because its leading edge follows the finger faster (ω 21 / ζ 0.75, rms 6.4) than its trailing edge (ω 24 /
  ζ 1.20, rms 10.5, overshoots to w 197.5 at the release) → `--ios-touch-segment-follow-*` (all fits, with the residuals)
- drop after a drag: x from the release position to the target segment, w/h ratios; the last frame off the final rect is up + 754 ms,
  the keys end on the first frame on it (+ 771; the recording itself runs to + 1313) → `--ios-touch-segment-drop-*`
- commit after a tap: moves up + 120 ms after the release, x overshoot 1.075 at + 569 ms (449 ms after the first move — tokens.css's
  lens-x-keys has 1.075 at 476 ms on the same time base, mean |Δ| 4.8 pt of the 200-pt travel), w peak ×1.239 at + 285, h ×1.379 at
  + 219 → `--ios-touch-segment-commit-*`

Self-test: every key list re-evaluated at its source frames reproduces them within 0.05 pt (limit 0.5). A press on the selected
segment then works as: lift keys → (drag: edge springs) → release keys or drop keys; a tap on the other segment: commit keys.

## 6 Test page

`lens-test.html` (from the template; standalone metas, safe-area padding): the scene card with the segmented control, the lens
over it as two layers — the filtered copy of what lies under it (`#seg-lens-f-bg-<w>`) and the filtered label copy
(`#seg-lens-f-lab-<w>`) — draggable (pointer events, frame stats), 自动拖 2 s, gratings ↔ / ↕ (period 8 like the native
measurement). Query: `?native=1` (control at x 20…420 like the probe), `?lensx=<page x of the lens centre>` (220 = the divider),
`?w=<width>` (a drag-stretch set: lens box w × the set's height, its filters), `?bg=0` / `?lab=0` (that layer unfiltered),
`?ab=ir|flip|0` (the fringe chain), `?pattern=bars` (hard bars under the lens for the per-channel edge check),
`?content=bars8|gx8` (the data session's segment-content gratings in place of the labels, §0.4), `?wh=<W/H>`
(pins the fringe's W/H; otherwise `whRule()` = the capture-box rule of §0.5 from the lens's screen rect), `?punch=0` (the
backdrop copy without the segment-content residue, record). Layers, per formula.md §4b: the page (layer 0) keeps its labels
outside the lens capsule — inside it they are cut (the lens box covers them); the backdrop layer (1) holds `.clone` = the card
and track and `.punch` = the segment content with the lens capsule cut out (`clip-path: path(evenodd …)`, the model capsule
scaled with the lens), filtered by `#seg-lens-f-bg-<w>`; the label layer (2/4) holds the label copy clipped to the capsule
before its filter `#seg-lens-f-lab-<w>`; the fringe chain (5) sits on the wrapper of both over a plain copy of the page. The
control's two segments are 200 pt each (label centres 120 / 320 in `?native=1`, ink boxes at the native's x — §0.4). The
§0c / §6d / bars checks of this structure are in §0.4 (earlier rounds of this paragraph — the 196×28 portal cut, the labels
1 pt off — are superseded). The map files are referenced by bare name (the page sits next to them); `index.html` references
them as `assets/lens/…`.

## 7 Regenerate

```
R=~/Money/styl-work/remote-ref/tools/touch; U=~/Money/styl-work/remote-ref/tools/uiprobe
cd web/assets/lens && python3 gen_lens_maps.py --formula --series 196:256:2 \
  --frames $R/seg-native-abc-frames.json,$U/uiprobe-motion-segdragmid-light.json \
  --verify-bg "$R/seg-phase-gx-light.json,$R/seg-phase-gy-light.json;$R/seg-phase-gx-dark.json,$R/seg-phase-gy-dark.json" \
  --verify-label-lift $R/seg-phase-label-gx-light.json,$R/seg-phase-label-gy-light.json \
  --verify-label-drag $R/seg-phase-label-dragmid-gx-light.json,$R/seg-phase-label-dragmid-gy-light.json,$R/seg-phase-label-dragmid-gy-ends-light.json \
  --verify-label-mid244 $R/seg-phase-label-mid244-gx6-light.json,$R/seg-phase-label-mid244-gy-light.json
python3 gen_seg_keys.py
```
(`--bg-layers` / `--label-layers` take `amount/height/ovalization/shape,…` in sampling order if a parameter changes; defaults
`--label-portal 0` (§4b), `--ab-wh 1.72` (the value written into the fringe filters; the page sets it per frame), `--ab-scale 0`
= 4·⌈amount⌉; the tab lens command is in §0.7; the measured-resampling mode of §1–§4 is `gen_lens_maps.py --field …` +
`verify_lens_maps.py`, kept for checks only.)
