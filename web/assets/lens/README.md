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
own centres while lifted (icon 29.33 → 34.03, TitleWrapper 94 → 109.04; 1 at rest); ② the whole floating platter
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
`?ab=ir|flip|0` (the fringe chain), `?pattern=bars` (hard bars under the lens for the per-channel edge check), `?wh=<W/H>`
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
