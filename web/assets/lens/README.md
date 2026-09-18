# Segmented-control lens refraction — displacement maps + SVG filter

The lifted / dragged selection lens of the segmented control (`.segctl .lens`, 196×28 → 220×44 r 22 while held) bends what is
under it like the native `_UILiquidLensView`. This folder holds the measured displacement field of the native segmented lens
packed as PNG maps, the `<filter>` that applies them, the generator, a check, a test page, and (`seg-keys.css`, `gen_seg_keys.py`)
the lens kinematics compiled from the native per-frame recordings. Nothing here touches `view.js` / `index.html`; the ui session
wires it in (`.segctl .warp{filter:url(#seg-lens-warp)}`).

| File | What |
|---|---|
| `gen_lens_maps.py` | resamples a measured field (phase files) into the maps + filter + test page + `lens-field.json` |
| `seg-map-{r,g,b}.png` | the field, 440×88 (2 px/pt), byte = 128 + u·255/32; one set for light and dark; clamp-to-edge outside the capsule |
| `seg-map-label-{r,g,b}.png` | DERIVED label-layer field (backdrop × 0.503, band × 0.629), `#seg-lens-warp-label` — see §1b for how far it is from the native |
| `lens-filter.svg` | `#seg-lens-warp`, maps inlined as data URIs (copy the `<svg>` into `index.html` before the scripts) |
| `lens-field.json` | what the maps hold (sources, interior scales, peak, dark-vs-light) |
| `verify_lens_maps.py` | decodes the maps and compares them with the resampled field and with every original phase sample |
| `lens-test.template.html` → `lens-test.html` | the test page (standalone metas; drag / auto-drag / gratings / frame stats) |
| `gen_seg_keys.py` → `seg-keys.css` | lift / release / commit / drag keyframes compiled from the native frame data (§5) |

## 1 Source: the native segmented lens's own field (data session, 2026-09-19)

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

`--label-from-bg 0.503,0.629` writes `seg-map-label-{r,g,b}.png` and `#seg-lens-warp-label`: the backdrop field with its amplitude ×
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

`lens-test.html` (also `~/Money/styl-work/remote-mock/v4/lens-test.html`): a card with two text lines and the 「早班 晚班」 control,
a 220×44 lens over the selected segment holding the filtered copy of the card (labels hidden) and the unfiltered label copy above.
Drag it (pointer events, `touch-action: none`) or 「自动拖 2 s」; the readout gives the rAF frame interval (mean, max, frames >
20 ms), the active filter and the display mode. 「光栅 ↔ / ↕」 lay the period-8 grating under the card like the native measurement,
to compare with `tools/touch/seg-lift-{gx,gy}-light.png`. Headless Chrome 440×956 @3x: the vertical grating is squeezed to 0.82
inside with dense bands at the top / bottom, the horizontal grating keeps its pitch with rainbow ends — the same picture as the
native captures. Safari standalone shots + frame numbers: data session.

## 7 Regenerate

```
R=~/Money/styl-work/remote-ref/tools/touch
cd web/assets/lens && python3 gen_lens_maps.py --field $R/seg-phase-gx-light.json,$R/seg-phase-gy-light.json --dark $R/seg-phase-gx-dark.json,$R/seg-phase-gy-dark.json --label-from-bg 0.503,0.629
python3 verify_lens_maps.py --field $R/seg-phase-gx-light.json,$R/seg-phase-gy-light.json
python3 gen_seg_keys.py
```
