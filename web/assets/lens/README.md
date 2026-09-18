# Segmented-control lens refraction — displacement maps + SVG filter

The lifted / dragged selection lens of the segmented control (`.segctl .lens`, 196×28 → 220×44 r 22 while held) bends what is
under it like the native `_UILiquidLensView`. This folder holds the displacement maps COMPUTED from the decompiled QuartzCore
formulas with the probe's original layer parameters (§0, 反编译原值（公式 + 探针参数）), one set per lens width for the drag
stretch, the `<filter>`s that apply them, the generator, a test page, and (`seg-keys.css`, `gen_seg_keys.py`) the lens kinematics
compiled from the native per-frame recordings. Nothing here touches `view.js` / `index.html`; the ui session wires it in.

| File | What |
|---|---|
| `gen_lens_maps.py --formula` | computes the maps from the formulas (§0), writes the filters, the test page, `lens-field.json` (parameters, sources, width → height table, residuals) |
| `seg-f-bg-<w>.png` | backdrop map for lens width w (196 … 256 step 2; 220 = lifted at rest): what lies under the lens (track / card). Covers the lens + 10 pt on every side (the filtered layer's size), 2 px/pt, byte = 128 + u·255/40, one map for all colour channels |
| `seg-f-lab-<w>.png` | label-copy map for width w (the label copy's two displacement stages, §0.2) |
| `lens-filter.svg` | `#seg-lens-f-bg-<w>` / `#seg-lens-f-lab-<w>` (feImage href = the PNG files as `index.html` sees them, `assets/lens/…`; copy the `<svg>` into `index.html`) |
| `lens-field.json` | everything the maps hold: formulas, parameters with sources, per-width heights (and where each comes from), the residual tables |
| `lens-test.template.html` → `lens-test.html` | the test page (standalone metas; `?w=<width>` picks a set; drag / auto-drag / gratings / frame stats) |
| `gen_seg_keys.py` → `seg-keys.css` | lift / release / commit / drag keyframes compiled from the native frame data (§5) |
| `verify_lens_maps.py`, `gen_lens_maps.py` without `--formula` | the earlier measured-resampling mode (§1–§4, record only): resamples the phase files into maps — no longer part of the deliverable |

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

Not read by the probe and therefore stated: the glassBackground shader's own SDF ovalization — the old page's residual table
(rms 0.12–0.16, §0.4) computes both backdrop stages on the same capsule with ovalization 0.5, kept here; the SDF elements'
cornerRadii during the drag (A9 read the rest state only) — DestOut's cornerRadius stays 22 through the whole drag
(`uiprobe-motion-segdragmid-light.json` lenstrace), so r = min(22, h/2).

### 0.3 The maps

Encoding as before but S = 40 (the label stack reaches 17.5 pt at the lens edge): byte = 128 + round(u·255/40), x → R, y → G,
u = content − screen (pt, +x right, +y down), zero = byte 128; B = the shape coverage the shader writes (255 inside, anti-aliased
edge, 0 outside — the lens clip does the same job in the web, feDisplacementMap ignores B); A 255. 2 px/pt. The browser decodes
S·(byte/255 − .5) = u + S/510 (0.08 pt, every channel alike). No dispersion: the colour fringe is glassForeground's aberration
term (formula.md §3, `aberrate_texture`), not decompiled yet — one map feeds all three channels, so the filter is a single
`feDisplacementMap` on `SourceGraphic`. Outside the capsule (the 10-pt margin, clipped away by the lens; the shader's coverage is
0 there) the map continues the field from the nearest boundary point — the shader's own out-of-shape value is the full unit
vector, which the stacked amounts push past the encodable range, and a constant continuation keeps the PNGs small and lets the
lens's anti-aliased boundary pixels sample like the boundary.

**One set per lens width** (`--series 196:256:2`, 31 widths × 2 maps, 609 KB of PNG in total, ≤ 1 MB): during the drag the
lens stretches (253.5×36.2 at the fastest recorded move, 204×47.5 on the overshoot) and the field follows the capsule, so the
page picks the set of the current width (nearest even width, no interpolation). Each set's height is the native's at that width:
linear between the two nearest recorded drag frames of `seg-native-abc-frames.json` (phase drag) and
`uiprobe-motion-segdragmid-light.json` (lenstrace); 196, 254 and 256 lie outside the recorded 197.5 … 253.5 and take the nearest
frame's height (flagged `clamped` in `lens-field.json`). The lift (196×28 → 220×44) is a different path (both dimensions grow, the
amounts ramp with the same curve, `seg-keys.css`); the sets are not for it — animate the filter's `scale` 0 → 40 on the 220 set.

**The filter, the layer and the source** (the acceptance session's ③, 05:0x, done differently for a WebKit reason): each map
covers the lens box plus 10 pt on every side (`layer_pt` of each set in `lens-field.json`; 480×128 px for the 220 set) and the
filter is the plain `x=0 y=0 width=100% height=100%` region with the map filling it. So the filtered layer is the lens box
EXTENDED by 10 pt (w+20 × h+20, `overflow:hidden`, placed at −10/−10 inside the lens, which clips the result to its capsule),
and the copy inside it is shifted by −(lens position) + 10. **The source must extend past the lens**: with the layer equal to the
lens box, a sample pulled from outside it is transparent, and one-pixel coloured lines ran along the long edges — at 2 pt inside
the top edge the three channels' sample positions straddled the box edge by 0.12 pt and the 3× nearest sampling turned that into
whole missing channels (page y 113.00 a full row of (0,255,255), y 152.33/152.67 (0,255,255)/(0,0,255); diagnostic 05:0x).
Now 0 off-neutral pixels in the lifted rest frame in Chrome and in WebKit (scan of the whole lens area).

Why not the `filterUnits="userSpaceOnUse" x=-10 y=-10 width=240 height=64` + `feImage x/y/width/height` form the acceptance
session asked for: WebKit (macOS 27.2 system WebKit, offscreen `WKWebView`, `scratchpad/wk/wksnap.swift`) renders NOTHING for an
element carrying that filter (a calibration page with a striped box: the box vanishes; a constant map with the default region
displaces exactly 4 pt = 4 pt in the same page), and with the default region it takes an overflowing child into the
objectBoundingBox region (the test page's 400-wide copy inside a 220×44 layer: WebKit's band came out 7.7–37.5 instead of 9–35).
The extended layer with `overflow:hidden` has the same bounding box everywhere: Chrome band 9.3–35.0, WebKit 8.7–35.0 on the
centre column, native 9–35 (`seg-lens-drag-mid.md` §0: 611/637). Both renders are in the proof images.

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

**Label copy `seg-f-lab` (ClearGlass −17.5/11.2 → ContentLensing −8.8/7.04, lens capsule) vs the label-grating fields, lifted at rest**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-gx-light.json` | 220×44 | **0.93** | 11.53 | -10: 0.88 / 8.41 @ +104; -5: 0.75 / 6.88 @ +106; +0: 0.40 / 4.42 @ +104; +5: 0.76 / 7.01 @ +106; +10: 1.48 / 11.53 @ -103 | -10: 0.12 / 1.19; -5: 0.02 / 0.28; +0: 0.02 / 0.17; +5: 0.02 / 0.23; +10: 0.11 / 1.09 | 45 |
| `seg-phase-label-gy-light.json` | 220×44 | **4.61** | 14.03 | -90: 2.80 / 7.84 @ -17; -60: 5.66 / 13.76 @ -19; -30: 5.24 / 14.03 @ +19; +0: 3.49 / 10.51 @ +17; +30: 5.24 / 14.03 @ +19; +60: 5.66 / 13.76 @ -19; +90: 3.10 / 8.14 @ +17 | -90: 0.32 / 0.94; -60: 0.37 / 1.10; -30: 0.36 / 1.05; +0: 0.35 / 1.02; +30: 0.36 / 1.05; +60: 0.37 / 1.10; +90: 0.28 / 0.80 | 122 |

**the same, dragged to the divider (lens 220×44 at x 220)**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-dragmid-gx-light.json` | 220×44 | **0.21** | 2.15 | -10: 0.17 / 1.27 @ -102; -5: 0.19 / 1.53 @ -103; +0: 0.27 / 2.15 @ -104; +5: 0.17 / 1.45 @ +103; +10: 0.25 / 2.01 @ +104 | -10: 0.03 / 0.26; -5: 0.01 / 0.03; +0: 0.00 / 0.01; +5: 0.00 / 0.02; +10: 0.01 / 0.06 | 37 |
| `seg-phase-label-dragmid-gy-light.json` | 220×44 | **4.70** | 14.03 | -90: 2.88 / 8.15 @ -17; -60: 5.66 / 13.76 @ -19; -30: 5.24 / 14.03 @ +19; +0: 4.19 / 9.95 @ -19; +30: 5.24 / 14.03 @ +19; +60: 5.66 / 13.77 @ -19; +90: 3.10 / 8.14 @ +17 | -90: 0.28 / 0.82; -60: 0.37 / 1.10; -30: 0.36 / 1.05; +0: 1.86 / 3.14; +30: 0.36 / 1.05; +60: 0.37 / 1.10; +90: 0.28 / 0.80 | 136 |
| `seg-phase-label-dragmid-gy-ends-light.json` | 220×44 | **2.05** | 8.70 | -104: 0.49 / 1.23 @ +10; -100: 1.37 / 4.62 @ -14; -96: 3.26 / 8.69 @ -17; +96: 3.24 / 8.70 @ -17; +100: 1.30 / 4.44 @ -14; +104: 0.44 / 1.14 @ -10 | -96: 0.30 / 0.87; +96: 0.28 / 0.82 | 66 |

**the same, the stretched 244×38.3 frame (period-6 grating for gx)**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-mid244-gx6-light.json` | 244.05×38.3501 | **1.07** | 6.59 | -10: 0.65 / 5.23 @ -115; -5: 0.75 / 6.31 @ -118; +0: 0.74 / 6.59 @ -119; +5: 0.70 / 6.32 @ -118; +10: 1.93 / 5.87 @ -94 | -10: 0.17 / 1.28; -5: 0.12 / 0.99; +0: 0.10 / 0.85; +5: 0.12 / 1.03; +10: 1.34 / 5.87 | 128 |
| `seg-phase-label-mid244-gy-light.json` | 244.05×38.3501 | **3.25** | 12.09 | -108: 0.91 / 2.33 @ +12; -104: 1.31 / 5.71 @ -16; -100: 1.31 / 5.72 @ -16; -96: 1.71 / 5.79 @ -16; -80: 3.43 / 9.19 @ +16; -40: 4.45 / 12.09 @ +16; +0: 3.22 / 9.71 @ -15; +40: 3.79 / 11.57 @ +16; +80: 4.44 / 12.02 @ +16; +96: 4.29 / 11.68 @ +16; +100: 3.97 / 10.81 @ +16; +104: 3.50 / 9.33 @ +16; +108: 2.86 / 8.67 @ -15 | -96: 0.63 / 1.66; -80: 0.69 / 1.86; -40: 0.90 / 2.48; +0: 0.89 / 2.40; +40: 0.88 / 2.39; +80: 0.88 / 2.45; +96: 0.85 / 2.36 | 204 |

**verification only: the two label stages in the other sampling order (ContentLensing first), lifted**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-gx-light.json` | 220×44 | **0.80** | 10.47 | -10: 0.74 / 6.79 @ +104; -5: 0.60 / 5.21 @ +106; +0: 0.36 / 3.92 @ +104; +5: 0.61 / 5.34 @ +106; +10: 1.33 / 10.47 @ -103 | -10: 0.12 / 1.19; -5: 0.02 / 0.28; +0: 0.02 / 0.17; +5: 0.02 / 0.23; +10: 0.11 / 1.09 | 45 |
| `seg-phase-label-gy-light.json` | 220×44 | **4.23** | 12.14 | -90: 2.63 / 7.08 @ -17; -60: 5.16 / 11.95 @ -19; -30: 4.79 / 12.14 @ +19; +0: 3.30 / 9.65 @ +17; +30: 4.79 / 12.14 @ +19; +60: 5.16 / 11.95 @ -19; +90: 2.89 / 7.37 @ +17 | -90: 0.31 / 0.92; -60: 0.36 / 1.08; -30: 0.35 / 1.03; +0: 0.34 / 1.00; +30: 0.35 / 1.03; +60: 0.36 / 1.08; +90: 0.27 / 0.78 | 122 |

**verification only: reversed order, dragged**

| file | lens | rms (all rows) | max | per row: rms / max @ s | inside the portal (|x| ≤ 96, |y| ≤ 12) rms / max | points > 0.3 pt |
|---|---|---|---|---|---|---|
| `seg-phase-label-dragmid-gx-light.json` | 220×44 | **0.14** | 1.65 | -10: 0.10 / 0.64 @ -102; -5: 0.14 / 1.15 @ -103; +0: 0.21 / 1.65 @ -104; +5: 0.13 / 1.07 @ +103; +10: 0.08 / 0.46 @ -103 | -10: 0.03 / 0.26; -5: 0.01 / 0.03; +0: 0.00 / 0.01; +5: 0.00 / 0.02; +10: 0.01 / 0.06 | 33 |
| `seg-phase-label-dragmid-gy-light.json` | 220×44 | **4.28** | 12.14 | -90: 2.71 / 7.39 @ -17; -60: 5.16 / 11.95 @ -19; -30: 4.79 / 12.14 @ +19; +0: 3.67 / 8.03 @ -19; +30: 4.79 / 12.14 @ +19; +60: 5.16 / 11.96 @ -19; +90: 2.90 / 7.37 @ +17 | -90: 0.28 / 0.80; -60: 0.36 / 1.08; -30: 0.35 / 1.03; +0: 1.86 / 3.12; +30: 0.35 / 1.03; +60: 0.36 / 1.08; +90: 0.27 / 0.78 | 136 |
| `seg-phase-label-dragmid-gy-ends-light.json` | 220×44 | **1.72** | 7.18 | -104: 0.17 / 0.42 @ +10; -100: 1.04 / 3.59 @ -14; -96: 2.81 / 7.17 @ -17; +96: 2.79 / 7.18 @ -17; +100: 0.97 / 3.42 @ -14; +104: 0.12 / 0.33 @ -10 | -96: 0.28 / 0.79; +96: 0.25 / 0.74 | 53 |

Reading the tables (numbers from `lens-field.json` → `verification`, every point listed there):

* Backdrop: rms 0.10 (gx) / 0.14 (gy), light = dark. Above 0.3 pt only at the ends of the ±8 rows (x ±104/105, depth 5: measured
  ±3.7 vs formula ±3.0–3.3) and at s = ±17…19 of the gy columns (depth 3–5: measured 2.6–3.2 vs formula 2.9–3.6) — the last
  5 pt before the edge, where the formula's profile steepens (its slope is infinite at the edge) and the demodulation smooths
  over the edge. The centre row's 0.18 is the label glyph's neighbourhood (masked |s| ≤ 20; the old page reads 0.35 → 0.18 alike).
* Label copy inside the portal (where the labels are): lifted gx 0.02–0.12 / gy 0.28–0.37 (max 0.8–1.1 at |y| 11–12, the portal
  edge's smoothed overshoot), dragged gx 0.00–0.03, ends columns ±96 0.28–0.30 — the same numbers the old page reports
  (lift gy .35 / 1.10, dragmid gx .02 / .36, gy-ends .28 / .83).
* Label copy outside the portal (|s| > 98 on the ±10 rows, |y| > 12): the measured field is the ClearGlass band, the formula's
  values are larger — dragmid rows ±10 at |s| 99…104: measured 1.2 … 2.4, formula 1.5 … 3.7 (residual up to 2.1 pt); the
  formula folds the last 11.2 pt (|du/ds| = 17.5/11.2 > 1: the content mirrors) where the measured slope is 0.57 (magnification
  ×2.3, `seg-lens-drag-mid.md` §5). Beyond |Δ| > 4 the period-8 phase method aliases and cannot check the −17.5 profile at all
  (the old page's note); the points above are the measurable part of that band and are the open item for the old page session.
  The lifted top / bottom band (|y| 14–19, gy files) reads the opposite sign of the formula (measured −3.9 at y −17 on column −90,
  formula +3.9): there the lens shows the segment content through a path whose sign matches the BackdropView profile, not the
  ClearGlass one — outside the portal the label copy is not what the grating measured. Listed, not adjusted.
* The two label stages in the other order differ by ≤ 0.1 rms inside the portal (the ContentLensing band lies outside it).
* mid244: inside the portal gx 0.10–0.17 (row +10: 1.34, at s −94…−83 where the period-6 file carries a 1.4 pt step the
  period-8 file does not), gy 0.6–0.9 (the portal edges at |y| 12 lie 3 pt closer to the lens edge in the 38.3-tall lens, so the
  smoothed formula band overshoots more) — the same picture as the lifted set; the old page: lift and mid244 agree point by point
  inside the portal.

What the pictures show (`~/Money/styl-work/remote-mock/v4/lens/formula/`): lifted at rest the track band inside the lens sits at
9 … 35 pt from the lens top on the centre column (native `seg-lift-light.png` 611/637; Chrome 9.3/35.0; WebKit 8.7/35.0), its
ends follow the capsule (no vertical cut — the old measured maps cut it at the last measured column); a 1-pt notch of the band's
top edge at x ±98…100 (formula −2.9 pt of vertical pull there, native ≥ −3.0: a boundary case of the band edge at exactly row 9);
0 coloured pixels along the long edges in both engines. Dragged to the divider, the glyphs at the lens ends are folded by the ClearGlass band (mirrored
fragments) where the native shows them magnified ×2.3 into thin slivers — the open item above.

<!-- verify:end -->

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
`?w=<width>` (a drag-stretch set: lens box w × the set's height, its filters), `?bg=0` / `?lab=0` (that layer unfiltered).
The map files are referenced by bare name (the page sits next to them); `index.html` references them as `assets/lens/…`.

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
(`--bg-layers` / `--label-layers` take `amount/height/ovalization/shape,…` in sampling order if a parameter changes; the
measured-resampling mode of §1–§4 is `gen_lens_maps.py --field …` + `verify_lens_maps.py`, kept for checks only.)
