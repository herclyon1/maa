# Segmented-control lens refraction — displacement maps + SVG filter

The lifted / dragged selection lens of the segmented control (`.segctl .lens`, 196×28 → 220×44 while held,
`--ios-touch-segment-lift-x/-y`) bends the content under it like the native `_UILiquidLensView`. This folder
holds the displacement field as PNG maps, the `<filter>` that applies them, the generator, a round-trip /
fit check and a minimal test page. Nothing here touches `view.js` / `index.html`; the ui session wires it in
(`.segctl .warp{filter:url(#seg-lens-warp)}`, its message of 2026-09-19).

| File | What |
|---|---|
| `gen_lens_maps.py` | the model + generator (writes everything below) |
| `seg-map-{r,g,b}.png` | **residual** field (edge band + dispersion only), 440×88 (2 px/pt), S 32 → `#seg-lens-warp` |
| `lens-map-{r,g,b}.png` | **full** field (band + the 1.22 magnification), 660×132 (3 px/pt), S 64 → `#seg-lens-warp-full` |
| `lens-filter.svg` | the two filters, maps inlined as data URIs (copy the `<svg>` into `index.html` before the scripts) |
| `lens-field.json` | the numbers behind the maps (tables, widths, encoding, sources) |
| `verify_lens_maps.py` | decodes the maps and compares them with the model and with the original phase samples |
| `verify-tab-lens-map-g.png` | the same model on the measured tab-bar lens (only for the check) |
| `lens-test.template.html` → `lens-test.html` | the test page (`?` nothing; standalone metas; drag / auto-drag / gratings / frame stats) |

## 1 Sources (all renderer-output sampling of iOS 27.0's native lens, `~/Money/styl-work/remote-ref/`)

- `lens-refraction.md` §0/§2: interior displacement `u(s) = −0.18·s` in both axes ⇔ uniform magnification **1.22**
  (`M = 1 / (1 − 0.18)`); §3: dispersion R vs B 1–2 pt only inside the band, no highlight ring, 1 pt bright / 1 pt dark
  boundary lines (rim.json: +15…18 / −30 per 255 on a 128 grey); §4.2: the magnification reaches 1.20 at 100 ms and 1.22
  from 150 ms while the band amount follows the 370 ms lift curve (§4.1).
- `tools/lens/phase-lift-gx-{light,dark}.json`, rows ±20 pt from the lens centre, channels R/G/B, 1 pt steps: the x
  displacement across the lifted tab-bar lens (presented 115.68×73.61). Only the RIGHT half (s ≥ 20) is used: the platter's
  left end has no grating beyond s −46 and the σ 3 pt demodulation window reaches in to −37. Each profile's centre value
  (its phase reference, ≈ +0.3 pt) is subtracted.
- `tools/lens/phase-lift-gy-{light,dark}.json`, columns ±25, the y displacement; valid for |s| ≤ 27 (no grating above /
  below the 62 pt platter; the window reaches 3 pt in) → the vertical band is seen only for d ≥ 10.
- The horizontal profiles at rows ±20 keep displacing right up to s 57 = the rect edge (u −14 at s 56, row 20): the lifted
  displacement shape at |y| = 20 reaches the full half-width, so the band is reduced with the straight-edge distance
  `d = 57.84 − s`, not the DestOut layer's r 35 circle (which would put the boundary at 52.75 on that row).

## 2 Model

`u(p) = −K·p + e_c(d, n̂)·n̂`, `K = 1 − 1/1.22 = 0.180`, p = position from the lens centre (pt, +x right, +y down),
d = distance inside the capsule boundary along the outward unit normal n̂ (capsule 220×44, r 22), c = channel.

- **Interior**: the uniform magnification. In `#seg-lens-warp` it is NOT in the map — the content inside the lens carries
  `zoom: 1.22` (a real resample); the map only holds the band. In `#seg-lens-warp-full` it is in the map.
- **Band**: `e_c(d, n̂) = P_c(d · 22 / W(n̂))`, `W(n̂) = 22·|n_x| + 11·|n_y|`. `P_c` is the measured horizontal profile
  (1 pt bins, `lens-field.json` → `edge_excess_pt_by_d`), G channel: 0 → −4.31, plateau −4.4…−4.75 for d 1–8, ramp to 0 by
  d ≈ 23. Negative = the content shown comes from further inside; the slope of the ramp (−0.37/pt) is what makes M ≈ 2.2 at
  d ≈ 10 (the measured peak 2.26). Outside the capsule (d < 0) u = 0.
- **Band width** 22 pt along x is the table's own scale (onset s ≈ 36 on rows ±20). Along y the onset sits at d ≈ 13
  (columns ±25: e = 0 for d ≥ 13, −0.15 at 12, −0.4 at 10, −0.65 at 9), which the same profile compressed 2× (W_Y = 11)
  reproduces within 0.4 pt over the valid range d ≥ 10. The vertical band's inner part (d < 10) and the capsule ends
  (normal in between, W blended by the normal's components) are **拟合替代** — no valid grating there / never measured.
- **Dispersion**: `P_R` and `P_B` are the same reduction of the R / B channels: R lags G by up to 0.8 pt at d 12–16 and
  B leads by up to 1.3 pt at d 2–4 (§3's "1–2 pt at 4–12 pt inside"). The three maps are otherwise identical.
- **Not modelled**: the 1 pt bright / dark boundary lines (a `box-shadow` on the test page, `inset 0 0 0 1px rgb(255 255 255 /
  .126)` + `0 0 0 1px rgb(0 0 0 / .23)` from rim.json's +16 / −30 on 128 grey); the time course — the maps are the steady state,
  scale the filter's `scale` attribute with the §4.1 curve and the `zoom` with §4.2's; the 220×44 lens itself was never
  measured (§5: "分段控件透镜没单独量") — the field is the tab-bar lens's, in absolute pt.

## 3 Encoding and the filter

`byte = 128 + round(u · 255 / S)`; x → R, y → G, B = 128, A = 255; u in pt = CSS px. Zero is byte 128 exactly in every
channel (with `255·(.5 + u/S)` a 1e-3 residual rounds to 127 or 128 and the three channel maps disagree by one byte at
scattered interior pixels — `feDisplacementMap` point-samples, so that paints colour fringes on every glyph edge). The
browser decodes `S·(byte/255 − .5)` = u + S/510 pt, a constant 0.06 pt shared by all channels, invisible.

`feDisplacementMap`: `P'(x,y) = P(x + scale·(R − .5), y + scale·(G − .5))`, `scale` in user units. The filter's region is the
element's own box (`x="0" y="0" width="100%" height="100%"`, objectBoundingBox) and each `feImage` is stretched to it
(`preserveAspectRatio="none"`), so the map's normalised coordinates follow the lens box as it grows; `scale` keeps the pt
magnitudes. `color-interpolation-filters="sRGB"` is required (default linearRGB would gamma-decode the map bytes).

Pipeline (the ui session's): `feColorMatrix` isolates one channel of the source → `feDisplacementMap` with that channel's map
→ `feBlend mode="lighten"` merges the three (each carries zeros in the other channels). Apply to the lens-shaped element with
an OPAQUE background; keep `zoom: 1.22` (not `transform: scale`) on the content inside — in Chrome a transformed child under an
SVG filter paints channel-split fragments on glyph edges; `zoom` lays out at the larger size and the filter source is plain.
Animate: `scale` attribute 0 → 32 with the lift progress, `zoom` 1 → 1.22 with the (earlier) magnification curve.

Sizes: residual maps 3 × ~5 KB PNG (data URIs ≈ 20 KB in the filter), full maps 3 × ~28 KB.

## 4 Check (`python3 verify_lens_maps.py`, 2026-09-19)

```
A. lens-map-{r,g,b}.png 660×132 S 64: decoded − model max |Δ| = 0.125 pt   (one byte = 0.251)
A. seg-map-{r,g,b}.png  440×88  S 32: decoded − model max |Δ| = 0.063 pt   (one byte = 0.125)
B. model vs phase-lift-* G samples (tab-bar lens 115.68×73.61, centre offset removed):
   interior (t ≥ 1):                    n=512  mean |Δ| 0.12 pt, ≤ 0.3 pt: 92 %, worst 1.12 (gx-dark row 20, s −9)
   band, horizontal rows ±20 (t < 1):   n=64   mean |Δ| 0.14 pt, ≤ 0.3 pt: 91 %, worst 0.50 (gx-dark row 20, s 44)
   band, vertical columns ±25 (d ≥ 10): n=24   mean |Δ| 0.36 pt, ≤ 0.3 pt: 54 %, worst 1.15 (gy-dark col −25, s −26)
```
A is the encoding round trip (≤ 0.3 pt everywhere). B is the fit: the horizontal band is the data itself (by construction), the
vertical band is the 2× compression assumption, the interior residual is the profiles' own scatter (the four datasets differ
by ±0.3 pt at the same point). Exit 1 if A exceeds 0.3 pt anywhere or the interior mean exceeds 0.3 pt.

## 5 Test page

`lens-test.html` (also copied to `~/Money/styl-work/remote-mock/v4/lens-test.html`): a card with two text lines and the
「早班 晚班」 control, a 220×44 lens over the selected segment holding a clone of the card. Drag it (pointer events,
`touch-action: none`), or 「自动拖 2 s」 for a finger-free 60 Hz run; the readout gives the rAF frame interval (mean, max,
frames > 20 ms), the active filter and the display mode. Buttons switch 边带贴图 + CSS 放大 (`#seg-lens-warp`, recommended) /
全场贴图 (`#seg-lens-warp-full`) / 只放大 1.22 / 无, and lay a period-8 grating under the card (↔ / ↕) like the native
measurement (`pattern gx 8`), so the bend can be compared with `tools/lens/lens-lift-{gx,gy}-light.png`. Headless Chrome
440×956 @3x: the interior pitch under the lens is 29.3 device px for 24 outside (×1.22), the ends and the top / bottom
bands bend with orange / blue fringes; to be confirmed on the simulator's Safari (standalone) by the data session — Safari
runs `filter: url()` on the CPU, the frame numbers are what the readout shows there.

## 6 Regenerate

```
cd web/assets/lens && python3 gen_lens_maps.py && python3 verify_lens_maps.py
```
