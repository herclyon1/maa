/* menu.js — the value row's pull-down menu: a geometry morph from the button's frame to the panel, in place of the old scale-and-fade
   (BOARD.md #3, night batch: geometry and timing only, no material).
   Basis (read values): menu-motion-formula.md §0 table / §2 / §8b — appear AND dismiss = one spring each for position x / y, width, height (and
   the corner), ζ .8 / response .3 s: the liquidMorph spec (ω = 2π/.3) is what AnimationKit's LiquidMorphAnimation puts into every MagicMorph
   Parameters (0x1de4106cc–0x1de410734, §8b ①) — the settings' liquidMorphShrink ζ .9 / .3 has no reader outside MorphAnimationSettings itself, so
   the dismiss is NOT ζ .9 (R19″ / R72′; the old §0 "消失 ζ .9" row is the unwired default); reduce-motion = liquidMorphReduceMotion ζ 1 / .15
   cross-fade (0x1de41065c–0x1de4106c4, R32); no dimming (_hasVisibleBackground NO, the scrim stays transparent); the source is the trigger button's own frame
   (morphPreviewFromAttachmentPoint, anchor (.5, .5)) — here the .menubtn's rect; the corner follows the same spring from the button's corner to
   the menu's (§4.1). menu-card-material.md §1.2 — width 250 (defaultMenuWidth), corner 32 (menuCornerRadius), section insets 10 / 10, item 42
   (the item rules stay index.html's `.menu button`). The panel's placement (below the value, 6 pt gap, ≥ 8 pt from the edges, above when
   there is no room) is the page's existing rule (view.js openMenu), kept.
   Read since (menu-motion-formula.md §7b, R18b): the panel's items have NO per-item delay (the list view has no stagger path; the cells' state
   update does not touch alpha / transform) — the items sit in the panel from the first frame, as here. §8b ③ (R72′): the intermediate shape
   (§7c) and the .03 s second step are NOT walked on iOS 27.0 — Parameters.useIntermediateShape is 0 on all five AnimationKit and four UIKit
   construction paths, and the milestone builder 0x1de415fd4 / secondStepDelay are read only inside that dead branch — so the morph is the source
   geometry → the target geometry in ONE step on the six liquidMorph springs, which is what runs here (the springs were already straight; the
   "待读" is closed). crossBlurWhenMorphing = 2 (auto, §8b ②): off when the content is match-moved, otherwise a Background witness Bool whose
   property is unread — not wired (noted in Menu.morph.crossBlur); the refraction lens on the morphing shape (lensingSDFLayer) is 不可表达 here;
   contentScale = 1 (§8b ①).
   Springs come from web/motion.js only (BOARD A7, #1). Without Motion this file defines nothing and view.js's old openMenu stays in charge
   (its first line is `if (window.Menu) return Menu.open(anchor, sel);`). */
(function () {
  if (!window.Motion || typeof Motion.spring !== "function") return;
  const APPEAR = [0.8, 0.3], DISMISS = [0.8, 0.3], REDUCE = [1, 0.15];   // [ζ, response s] — appear and dismiss both liquidMorph (§8b ①: liquidMorphShrink unread by the animation); reduce motion liquidMorphReduceMotion
  const MORPH = { oneStep: true, useIntermediateShape: 0, secondStepDelay: null, contentScale: 1, crossBlur: { params: 2, meaning: "auto: 0 when source and target share a magicMoveIdentifier, else the item Background's witness Bool (property unread)", wired: false } };   // §8b, R19″
  const W = 250, R = 32, GAP = 6, EDGE = 8;
  let cur = null;   // the open menu: { panel, scrim, sel, from, to, s: { left, top, width, height, r, a }, phase: "in" | "out", prev, raf }
  const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const restRect = (anchor, h) => { const r = anchor.getBoundingClientRect(); const right = Math.max(EDGE, innerWidth - r.right), left = innerWidth - right - W;
    const top = r.bottom + GAP + h <= innerHeight - EDGE ? r.bottom + GAP : Math.max(EDGE, r.top - GAP - h); return { left, top, width: W, height: h }; };
  const anchorRect = (anchor) => { const r = anchor.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height }; };
  const cornerOf = (el) => parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
  /* ---- the panel's glass (BOARD R1; material by the read keys only, BOARD A20) ----
     Keys: menu-glass-sdfdump-2026-09-19.md §2 (the glassBackground filter's 70 inputs on the menu's CABackdropLayer, light / dark) and §3 (the
     highlight layer). Formula: alert-native-formula.md §1 (the same glassBackground shader, the alert's keys → uniforms) and keyfill-highlight.md §4
     (the ring shadow). What this layer does, per term:
       BlurRadius 5 → the backdrop (a clone of #app under the panel) through feGaussianBlur σ 20 pt: §1.3 of alert-pipeline-plan — the 5 is in
         samples of the 1/4-resolution capture (5 ÷ .25 = 20 pt); the edge reduction (BlurDistance0/1 −83.5 / −1: r → 0 within 1 pt of the rim) is
         under one pixel of the blur's own footprint and is not built (不可表达 in one feGaussianBlur; noted in keys());
       FaceColorMatrixFillColor (1,1,1,.2) light / (0,0,0,0) dark → the fill mix after the face matrix (§1: "再 mix 填充色"): out = mix(c, fill, .2),
         a white flood composited at .2; the face matrix's white 1.03 / black .4 / saturation 1.2 (dark 1.125 / .125 / 1.3) act in YCC — the luma
         weights of CA::ColorMatrix::set_ycc_composite are not read (待读), so the matrix itself is not applied (keys() says so);
       RingShadow opacity .06 / offset 8 / stroke 4 / blur 5 / mask 1 → keyfill-highlight.md §4: term = .06 · (N((d_r + 4)/5) − N(d_r/5)) inside the
         shape, d_r = the shape's SDF at p + (0, 8); built as an SVG ring band (the rounded rect shifted 8 pt down, the 4 pt band inside its edge)
         blurred σ 5 and multiplied over the glass (col·(1 − term)), clipped to the panel (mask 1);
       Clamp 1.07 / 1.308 (clamp(c/a, −.75, limit) at the output) → no effect on 8-bit sRGB values (they never exceed 1): nothing to build;
       ShadowAmount 0 with ShadowOpacity .4 / .6, Radius 24, Offset (0, 8) → §1: amount 0 takes the no-displacement branch; whether a soft shadow
         remains is 待读, none drawn; the page's old box-shadow (the alert's sampled substitute) is removed with the old background.
       Not built, 待读 / 不可表达 (listed in keys()): InnerRefraction −60 / 20 and OuterRefraction 41.75 / 33.4 with RefractionOpacity .6 (a
         displacement map for the r32 rounded rect — the segment lens's generator makes capsules only), the in-shader KeyFill highlight (amount .4,
         angle 1.571, bias −.3, offset −.5333, height .5333, spread 1.676 / 1.309), the highlight layer of §3 (CASDFKeyFillHighlightEffect), Bleed
         (58.45 / .5 light .8 dark, the SDF-distance bleed of alert-pipeline-plan §1.3 variant e), BlurFill (8, lighten .9 / darken .9, normal .5:
         formula not read), FaceColorMatrixMaxLuma (1 / .35: formula not read). */
  const GLASS_KEYS = {
    light: { GradientOvalization: 0.5,   // 数据 R109: the menu's glass elements' gradientOvalization (materials[13]/[14] and the elements under the LensingSDFLayer) = .5 (alert-native-formula §4 ⑨: the gradient only)
      BlurRadius: 5, BlurDistance0: -83.5, BlurDistance1: -1, BlurDistance2: 0, BlurDistance3: 0, BlurOpacity0: 0.8, BlurOpacity1: 0.4, BlurOpacity2: 0.5, BlurOpacity3: 1, BlurFillBlurRadius: 8, BlurFillDarkenOpacity: 0, BlurFillLightenOpacity: 0.9, BlurFillNormalOpacity: 0.5,
      FaceColorMatrixWhite: 1.03, FaceColorMatrixBlack: 0.4, FaceColorMatrixSaturation: 1.2, FaceColorMatrixFillColor: [1, 1, 1, 0.2], FaceColorMatrixMaxLuma: 1, FaceColorMatrixMaxLumaSDR: 0.94, FaceOpacity: 1, Clamp: 1.07, ClampPreserveHue: 0,
      InnerRefractionAmount: -60, InnerRefractionHeight: 20, OuterRefractionAmount: 41.75, OuterRefractionHeight: 33.4, RefractionOpacity: 0.6, RefractionDistance0: -1, RefractionDistance1: 0,
      KeyFillHighlightAmount: 0.4, KeyFillHighlightAngle: 1.571, KeyFillHighlightColorBias: -0.3, KeyFillHighlightEffectOffset: -0.5333, KeyFillHighlightHeight: 0.5333, KeyFillHighlightSpread: 1.676, KeyFillHighlightSpreadSDR: 1.85,
      RingShadowOpacity: 0.06, RingShadowOffset: 8, RingShadowStrokeWidth: 4, RingShadowBlurRadius: 5, RingShadowMask: 1,
      BleedAmount: 58.45, BleedBlurRadius: 58.45, BleedHeight: 58.45, BleedOpacity: 0.5, BleedColorMatrixBlack: 0.9, BleedColorMatrixSaturation: 1.2, BleedColorMatrixWhite: 1, BleedDarkenBlend: 1, BleedDistance0: 1, BleedDistance1: 0,
      ShadowAmount: 0, ShadowOpacity: 0.4, ShadowRadius: 24, ShadowOffset: [0, 8], ShadowColorMatrixFillColor: [0, 0, 0, 0.3], ShadowBlurRadius: 0, ShadowHeight: 0, ShadowDistanceOffset: 0, ShadowVibrancyContribution: 0, ShadowColorMatrixWhite: 1, ShadowColorMatrixBlack: 0, ShadowColorMatrixSaturation: 1,
      SDRGradientDistance0: 0, SDRGradientDistance1: 0, SDRHoldingToneEnabled: 0, SDRHoldingToneWhite: 1, SDRShadowOpacity: 0, MaxHeadroom: 9999 },
    dark: { BlurFillDarkenOpacity: 0.9, BlurFillLightenOpacity: 0, FaceColorMatrixWhite: 1.125, FaceColorMatrixBlack: 0.125, FaceColorMatrixSaturation: 1.3, FaceColorMatrixFillColor: [0, 0, 0, 0], FaceColorMatrixMaxLuma: 0.35, FaceColorMatrixMaxLumaSDR: 0.35, Clamp: 1.308,
      KeyFillHighlightSpread: 1.309, KeyFillHighlightSpreadSDR: 1.309, BleedOpacity: 0.8, BleedColorMatrixBlack: 0.125, BleedColorMatrixSaturation: 1, BleedColorMatrixWhite: 0.5, BleedDarkenBlend: 0, ShadowOpacity: 0.6 } };
  const BUILT = { BlurRadius: "feGaussianBlur σ = 5 × 4 pt (the 1/4-resolution capture, alert-pipeline-plan §1.3)", FaceColorMatrixFillColor: "folded into the face matrix, premultiplied (matrix × (1 − a), bias + rgb·a; alert-native-formula §4 ⑦ set_ycc_composite)",
    RingShadowOpacity: "SVG band ring σ 5, multiplied (keyfill-highlight §4)", RingShadowOffset: "the band's shape shifted (0, 8)", RingShadowStrokeWidth: "band width 4 inside the shifted edge", RingShadowBlurRadius: "feGaussianBlur σ 5", RingShadowMask: "clipped to the panel (mask 1)",
    Clamp: "no-op on 8-bit values (never above 1)", ShadowAmount: "0 → the no-displacement branch (alert-native-formula §1); no shadow drawn" };
  Object.assign(BUILT, { "FaceColorMatrixWhite/Black/Saturation": "feColorMatrix = YCC⁻¹·D·YCC (Rec.709, menu-card-material §7.1)", FaceColorMatrixMaxLumaSDR: "the pre-compression k = sat(1 − Y·(1 − MaxLumaSDR)), c′ = c·k + .3(1 − k)(c·k − Y·k) (§7.1) as c·A(Y) − B(Y): two luma LUTs, α kept 1 (R57′)", "BlurFillBlurRadius/Darken/Lighten/Normal": "b = the unrefracted capture at mip 3 (level std 9.581 → σ 38.32 pt) sampled at ±.75 mip texels (±24 pt) and averaged, then darken / lighten blends + arithmetic mixes on the refracted c (§7.2 / §7c, R63′)", "ShadowOpacity/Radius/Offset/ColorMatrixFillColor": "drop-shadow 0 8 24 rgba(0,0,0,.3 × opacity) on the panel (§7.3; 剖面近似)" });
  const UNBUILT = { "BlurDistance*/BlurOpacity*": "the rim's blur reduction (three-stage r(d)): 待做 with the level-mix construction of topbar.js R3″ (not in R63)", "FaceColorMatrixMaxLuma (EDR)": "SDR screen: MaxLumaSDR used (k_EDR 0, §7.1)",
 "ShadowColorMatrixWhite/Black/Saturation": "待读: how the four shadow colour keys enter set_ycc_composite (§7.3)", "Bleed capture edge": "近似: the capture box (panel ± marginWidth 58.45 (R84), clamped to the copy) tiled and blurred σ 100 = its mean; native clamp_to_edge replicates the edge column instead (R57′)" };
  Object.assign(BUILT, { GradientOvalization: "R63″: .5 (数据 R109) — g = normalize(mix(shape normal, normalize((x, hw/hh·y)), .5)) on the refraction / bleed maps and the highlight / stroke n·dir (alert-native-formula §4 ⑨)",
    "KeyFillHighlight* (in-shader, stroke_mode 1)": "R63′: keyfill-highlight §2c — the band outside the shape (edge − fw/2 … edge + .5333), k per pixel from the SDF normal and SpreadSDR, colour B″ = mix(B, min(face(B), B), k)·(1 + ColorBias·k·(3 − 2B″)) on a second page copy in its own layer (#menu-stroke-f); at rest only",
    "InnerRefraction*/OuterRefraction*/RefractionOpacity/RefractionDistance*": "R63: two feDisplacementMaps (maps from the supercircle SDF, formula §3 uv1/uv2) mixed by .6·sat((d + 1)/1)", "Bleed*": "R63 / R57′: the capture box's mean (feTile + σ 100 blur; lod 5.87 ≈ a 128-pt texel) displaced outward 58.45·Dc through the bleed YCC matrix, weight Opacity·w(d)·(luma or 1 − luma)⁴ as one 65-sample LUT (alert-native-formula §4 ⑦)", "highlight layer (menu-glass-sdfdump §3)": "R63: the KeyFill bands (main + diffuse, spread 1.5253) through the dumped vibrantColorMatrix, two stages" });
  const glassTheme = () => (matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light") || document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const glassKeys = (theme) => ({ ...GLASS_KEYS.light, ...(theme === "dark" ? GLASS_KEYS.dark : {}) });
  const NS = "http://www.w3.org/2000/svg";
  /* R1′ (menu-card-material.md §7, R35 — the glassBackground shader's IR): the three terms that were 待读, now built in the SVG chain, in the shader's order
     blur → BlurFill → MaxLuma → face matrix → fill mix:
       BlurFill (§7.2): bf = the backdrop at mip log2(r) (r = BlurFillBlurRadius 8 → mip 3; here feGaussianBlur σ = 8 × 4 pt on the same 1/4-resolution
         reading as the main blur — the mip's two-point average is 近似 mip, as the read says); out = darken·min(c, bf) + lighten·max(c, bf) +
         (1 − darken − lighten)·c; final = mix(out, bf, normal) — min / max = feBlend darken / lighten, the mixes = feComposite arithmetic (exact);
       MaxLuma (§7.1, before the face matrix): complement = 1 − MaxLumaSDR (SDR screen, k_EDR 0): light .06 / dark .65; Y = .2126 R + .7152 G + .0722 B;
         k = saturate(1 − Y·complement); c′ = mix(Y·k, c·k, 1 + .3(1 − k)) = c·k + .3(1 − k)·(c·k − Y·k) — the products through feComposite arithmetic
         k1 (i1·i2), the signed difference as its positive and negative parts (SVG clamps intermediates at 0), then c·k + P − N;
       face matrix (§7.1): M = YCC⁻¹ · D · YCC with Rec.709 YCC (Y = .2126/.7152/.0722; Cb = −.1146/−.3854/.5 + .5; Cr = .5/−.4542/−.0458 + .5), D:
         Y′ = (White − Black)·Y + Black, Cb′ / Cr′ = sat·(·) + (.5 − .5 sat), YCC⁻¹ (R = Y + 1.5748 Cr − .7874; G = Y − .18732 Cb − .46812 Cr + .32772;
         B = Y + 1.8556 Cb − .9278) — one feColorMatrix computed here from those constants (exact); then the fill mix (a flood at the fill's alpha);
       the soft shadow (§7.3): ShadowAmount 0 only skips the displacement — the shadow is drawn: black α .3 × ShadowOpacity (.4 light / .6 dark), radius 24,
         offset (0, 8), the panel's shape — CSS drop-shadow on the panel; the shader's profile is .5·erfc(d/R) = a Gaussian edge of σ = R/√2 = 16.9706 (§7.3b), so
         drop-shadow's σ argument is 16.9706 — exact on straight edges, corners (convolution vs SDF distance) remain 表达差异. */
  const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((acc, v, i) => acc + v * B[i][j], 0)));   // 4×4 affine (3×3 + offset column as homogeneous)
  const faceMatrix = (k) => { const W = k.FaceColorMatrixWhite, Bk = k.FaceColorMatrixBlack, sat = k.FaceColorMatrixSaturation, fill = k.FaceColorMatrixFillColor;
    const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]];
    const D = [[W - Bk, 0, 0, Bk], [0, sat, 0, .5 - .5 * sat], [0, 0, sat, .5 - .5 * sat], [0, 0, 0, 1]];
    const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]];
    let M = mul(mul(INV, D), YCC); const r = (v) => (+v.toFixed(5)).toString();
    /* the fill (alert-native-formula §4 ⑦, set_ycc_composite 0x1c3982748–0x1c39827a0): the whole matrix × (1 − a), the PREMULTIPLIED fill (rgb·a) added to the bias — one
       matrix instead of a flood composited after it (R57′: the extra 8-bit step cost a unit on the five-grey check) */
    if (fill && fill[3] > 0) M = M.map((row, i) => i < 3 ? row.map((v, j) => v * (1 - fill[3]) + (j === 3 ? fill[i] * fill[3] : 0)) : row);
    return [0, 1, 2].map((i) => `${r(M[i][0])} ${r(M[i][1])} ${r(M[i][2])} 0 ${r(M[i][3])}`).join(" ") + " 0 0 0 1 0"; };
  /* ---- R63: the three items left open by R1 / R1′ — refraction, the highlight layer, bleed (plus the in-shader KeyFill, which turns out 待读) ----
     Refraction (glass-displacement-formula.md §3 %299–%557): uv1 = uv + InnerRefractionAmount·(1 − sqrt(t(2 − t)))·g, t = sat(−d/InnerRefractionHeight);
       uv2 the same with the Outer keys; c = mix(c1, c2, RefractionOpacity·sat((d − Distance0)/(Distance1 − Distance0))) — the menu's keys −60 / 20,
       41.75 / 33.4, .6, distances −1 / 0 (menu-glass-sdfdump §2): two feDisplacementMaps from maps generated here on the panel's rest box and a
       per-pixel mix weight; the shape = the continuous-corner rounded rect (cornerRadii 32 continuous → the supercircle branch, label-end-tear §7 ②).
     Highlight layer (menu-glass-sdfdump §3: CASDFKeyFillHighlightEffect curvature .75, key / fill height 1, spread 1.5253 both, amount .5, diffuse
       .15 / ×8 / ×.65, angles 0 / π; vibrantColorMatrix = the dumped 4×5): keyfill-highlight.md §2 bands — main (key from the top + fill from the
       bottom) then diffuse, each stage out ← (1 − α)·out + α·V(out) (the three-emit rule) — generated α images, the matrix as feColorMatrix.
     Bleed (alert-native-formula §3 variant e with the menu's keys: Amount / Height / BlurRadius 58.45, Opacity .5 light / .8 dark, colour matrix
       white 1 / black .9 / sat 1.2 light (dark .5 / .125 / 1), DarkenBlend 1 light / 0 dark, Distance 1 / 0): uv_b = uv + 58.45·(1 − sqrt(t(2 − t)))·g,
       t = sat(−d/58.45); c_b = bleed_cm·backdrop_blurred(uv_b) (BleedBlurRadius 58.45 → lod 5.87 → the level mix's std ÷ .25 = 293 pt: one
       feGaussianBlur with edgeMode duplicate for the capture's clamp_to_edge); darken = ((x·luma(c) + y)²·w)², (x, y) = (1, 0) light / (−1, 1)
       dark, w = sat((d − 1)/(0 − 1)) = 1 inside; c′ = mix(c, c_b, Opacity·darken) — luma⁴ through feComponentTransfer gamma 4.
     In-shader KeyFill (keyfill §5.1): the menu's Height .5333 with EffectOffset −.5333 gives stroke_mode = (offset < 0) ∧ |height + offset| < .001 = 1
       (0x1c3a68418–0x1c3a68444) — the stroke-mode branch is unread; the documented band is stroke_mode 0's → 待读, not built (UNBUILT). */
  const KR = 1.528665, satf = (x) => Math.max(0, Math.min(1, x));
  const scPoly = (rho) => (((-0.926054 * rho + 3.15601) * rho - 3.64122) * rho + 1.26803) * rho + 0.268531;
  /* R63″ (数据 R109: gradientOvalization .5; alert-native-formula §4 ⑨ R83): g = normalize(mix(g_shape, normalize((x, (hw/hh)·y)), o)) — the gradient only, d untouched; the refraction / bleed
     map directions and the highlight / stroke n·dir turn towards the centre along the long edges */
  const gOval = (x, y, hw, hh, gx, gy, o) => { if (!(o > 0)) return [gx, gy]; const rx = x, ry = (hw / hh) * y, rn = Math.hypot(rx, ry) || 1; const mx = gx + (rx / rn - gx) * o, my = gy + (ry / rn - gy) * o, mn = Math.hypot(mx, my) || 1; return [mx / mn, my / mn]; };
  const sdfSuper = (x, y, hw, hh, r) => { const R = KR * r; const cx = Math.abs(x) - hw, cy = Math.abs(y) - hh; const qx = cx + R, qy = cy + R;
    const ux = Math.max(0, qx / R), uy = Math.max(0, qy / R); const umax = Math.max(ux, uy); const rho = umax > 0 ? Math.min(ux, uy) / umax : 0; const ul = Math.hypot(ux, uy);
    const kk = rho * rho * satf(ul) * scPoly(rho); const f = ul + 1 - 1 / (1 - kk); const d = R * (f - 1) + Math.min(Math.max(qx, qy), 0);
    let gx, gy; if (qx + qy > 0) { gx = Math.max(0, qx); gy = Math.max(0, qy); } else if (qx > qy) { gx = 1; gy = 0; } else { gx = 0; gy = 1; }
    const gn = Math.hypot(gx, gy) || 1; return [d, (gx / gn) * (x >= 0 ? 1 : -1), (gy / gn) * (y >= 0 ? 1 : -1)]; };
  const Dc = (t) => 1 - Math.sqrt(Math.max(0, 2 * t - t * t));
  const bandf = (e, h, cosS, bias, curv, ndir, fw) => { const t = satf(e / h); const prof = (t < 1 ? 1 : 0) * (1 - curv) + (1 - t) * curv; const aa = satf(e / fw + 0.5) * satf((h - e) / fw + 0.5);
    const ang = satf((ndir - cosS) / (1 - cosS)); const vv = e < -5 ? 0 : prof * aa * ang; return vv / (1 + bias * (1 - vv)); };
  const HLK = { curvature: 0.75, height: 1, spread: 1.5253, amount: 0.5, diffuseAmountScale: 0.15, diffuseHeightScale: 8, diffuseSpreadScale: 0.65, vibrant: [1.1202, -0.1894, -0.019, 0, 0.1471, -0.0563, 0.9871, -0.0191, 0, 0.1471, -0.0563, -0.1893, 1.1574, 0, 0.1471] };
  const VB_STD = [0, 2.147, 4.694, 9.581, 19.263, 38.579, 77.023], CAPTURE = 0.25;   // the pyramid levels' stds (capture px; tools/vb_kernel.py) and the capture scale (as the alert's, alert-native-formula §0)
  const mixStd = (L) => { const k0 = Math.min(Math.floor(L), VB_STD.length - 2), f = L - k0; return Math.sqrt((1 - f) * VB_STD[k0] ** 2 + f * VB_STD[k0 + 1] ** 2); };
  const lod = (r) => Math.max(0, r >= 2 ? Math.log2(r) : Math.log2(1 + r / 2));
  const PXG = 2, MAPS = 128;
  const glassImages = (() => { const cache = {}; return (W, H, k) => { const key = `${W}x${H}`; if (cache[key]) return cache[key]; const hw = W / 2, hh = H / 2, r = 32, w = Math.round(W * PXG), h = Math.round(H * PXG);
    const mk = () => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; }; const cin = mk(), cout = mk(), chl = mk(), chl2 = mk(), cbl = mk();
    const iin = cin.getContext("2d").createImageData(w, h), iout = cout.getContext("2d").createImageData(w, h), ihl = chl.getContext("2d").createImageData(w, h), ihl2 = chl2.getContext("2d").createImageData(w, h), ibl = cbl.getContext("2d").createImageData(w, h);
    const cosK = Math.cos(HLK.spread), cosD = Math.cos(HLK.diffuseSpreadScale * HLK.spread), biasD = 1 / (HLK.diffuseAmountScale * HLK.amount) - 2, hD = HLK.diffuseHeightScale * HLK.height, fw = 1 / 3;
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const x = (i + 0.5) / PXG - hw, y = (j + 0.5) / PXG - hh; const [d, gsx, gsy] = sdfSuper(x, y, hw, hh, r); const [gx, gy] = gOval(x, y, hw, hh, gsx, gsy, k.GradientOvalization); const o = (j * w + i) * 4;   // R63″: the ovalized gradient drives the directions
      const di = k.InnerRefractionAmount * Dc(satf(-d / k.InnerRefractionHeight)), dout = k.OuterRefractionAmount * Dc(satf(-d / k.OuterRefractionHeight));
      const wr = Math.round(255 * k.RefractionOpacity * satf((d - k.RefractionDistance0) / (k.RefractionDistance1 - k.RefractionDistance0)));
      iin.data[o] = Math.round(128 + di * gx * 255 / MAPS); iin.data[o + 1] = Math.round(128 + di * gy * 255 / MAPS); iin.data[o + 2] = wr; iin.data[o + 3] = 255;
      iout.data[o] = Math.round(128 + dout * gx * 255 / MAPS); iout.data[o + 1] = Math.round(128 + dout * gy * 255 / MAPS); iout.data[o + 2] = 0; iout.data[o + 3] = 255;
      const db = k.BleedAmount * Dc(satf(-d / k.BleedHeight)); const wb = Math.round(255 * satf((d - k.BleedDistance0) / (k.BleedDistance1 - k.BleedDistance0)));   // the bleed map (outward) and w(d)
      ibl.data[o] = Math.round(128 + db * gx * 255 / MAPS); ibl.data[o + 1] = Math.round(128 + db * gy * 255 / MAPS); ibl.data[o + 2] = wb; ibl.data[o + 3] = 255;
      const e = -d; let a1 = 0, a2 = 0;
      if (d <= 0) { for (const dy of [-1, 1]) { const nd = gy * dy; a1 += bandf(e, HLK.height, cosK, 0, HLK.curvature, nd, fw); a2 = 1 - (1 - a2) * (1 - satf(bandf(e, hD, cosD, biasD, 1, nd, fw))); } }
      ihl.data[o] = ihl.data[o + 1] = ihl.data[o + 2] = Math.round(255 * satf(a1)); ihl.data[o + 3] = 255; ihl2.data[o] = ihl2.data[o + 1] = ihl2.data[o + 2] = Math.round(255 * satf(a2)); ihl2.data[o + 3] = 255; }
    cin.getContext("2d").putImageData(iin, 0, 0); cout.getContext("2d").putImageData(iout, 0, 0); chl.getContext("2d").putImageData(ihl, 0, 0); chl2.getContext("2d").putImageData(ihl2, 0, 0); cbl.getContext("2d").putImageData(ibl, 0, 0);
    cache[key] = { inner: cin.toDataURL("image/png"), outer: cout.toDataURL("image/png"), hl: chl.toDataURL("image/png"), hl2: chl2.toDataURL("image/png"), bleed: cbl.toDataURL("image/png"), W, H }; return cache[key]; }; })();
  const yccMatrix = (W, Bk, sat) => { const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]];
    const D = [[W - Bk, 0, 0, Bk], [0, sat, 0, .5 - .5 * sat], [0, 0, sat, .5 - .5 * sat], [0, 0, 0, 1]]; const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]];
    const M = mul(mul(INV, D), YCC); const r = (v) => (+v.toFixed(5)).toString(); return [0, 1, 2].map((i) => `${r(M[i][0])} ${r(M[i][1])} ${r(M[i][2])} 0 ${r(M[i][3])}`).join(" ") + " 0 0 0 1 0"; };
  const selCh = (src, ch, name) => `<feColorMatrix in="${src}" type="matrix" values="${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  0 0 0 0 1" result="${name}"/>`;
  const invert = (src, name) => `<feComponentTransfer in="${src}" result="${name}"><feFuncR type="linear" slope="-1" intercept="1"/><feFuncG type="linear" slope="-1" intercept="1"/><feFuncB type="linear" slope="-1" intercept="1"/></feComponentTransfer>`;
  /* MaxLuma (menu-card-material §7.1; alert-native-formula §4 ⑦, IR %568–%584): c′ = c·k + .3(1 − k)(c·k − Y·k), k = sat(1 − comp·Y). Arranged as c′ = c·A(Y) − B(Y)
     with A = k(1.3 − .3k), B = .3(1 − k)kY (the same formula, regrouped by Y): two luma LUTs (feComponentTransfer table, 33 samples of a quadratic) and two
     arithmetic composites whose α stays 1 — the earlier form's difference terms (c·k − Y·k) had α 0 in Chrome's premultiplied 8-bit buffers (clamped to 0: the
     chroma term silently vanished) */
  const lut = (fn, n = 33) => Array.from({ length: n }, (_, i) => (+fn(i / (n - 1)).toFixed(5)).toString()).join(" ");
  const tf3 = (name, src, values) => `<feComponentTransfer in="${src}" result="${name}"><feFuncR type="table" tableValues="${values}"/><feFuncG type="table" tableValues="${values}"/><feFuncB type="table" tableValues="${values}"/></feComponentTransfer>`;
  const maxLumaChain = (src, comp, luma) => { const kOf = (Y) => Math.max(0, Math.min(1, 1 - comp * Y)), A = (Y) => { const k = kOf(Y); return k * (1.3 - .3 * k); }, iB4 = (Y) => { const k = kOf(Y); return 1 - 4 * .3 * (1 - k) * k * Y; };   // B ≤ .017 light / .068 dark: stored ×4 (feComponentTransfer truncates to 8 bits — 1 − B would lose a whole unit)
    return comp > 0 && comp < 1 ? `<feColorMatrix in="${src}" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="Y"/>` + tf3("A", "Y", lut(A)) + tf3("iB4", "Y", lut(iB4))
      + `<feComposite in="${src}" in2="A" operator="arithmetic" k1="1" result="cA"/><feComposite in="cA" in2="iB4" operator="arithmetic" k2="1" k3=".25" k4="-.25" result="ml"/>` : `<feComposite in="${src}" in2="${src}" operator="over" result="ml"/>`; };
  /* α reset: BlurFill's arithmetic mixes pass through α .9 and come back to ≈ .992, not 1 (Chrome rounds each premultiplied 8-bit buffer); every later feBlend then adds
     (1 − α)·backdrop (+2/255 on a 128 grey) — un-premultiply and pin α = 1 (feFuncA discrete [1]); inside the panel clip the source is opaque everywhere */
  const alphaOne = (src, name) => `<feComponentTransfer in="${src}" result="${name}"><feFuncA type="discrete" tableValues="1"/></feComponentTransfer>`;
  const ensureFilter = (theme, W, H) => { const k = glassKeys(theme); let svg = document.getElementById("menu-glass-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "menu-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const im = glassImages(W || 250, H || 167, k), M = 120, bleedSig = mixStd(lod(k.BleedBlurRadius)) / CAPTURE, bleedCM = yccMatrix(k.BleedColorMatrixWhite, k.BleedColorMatrixBlack, k.BleedColorMatrixSaturation), dk = k.BleedDarkenBlend ? [1, 0] : [-1, 1];
    const img = (href, name) => `<feImage href="${href}" preserveAspectRatio="none" x="0" y="0" width="${im.W}" height="${im.H}" result="${name}" data-menu-img="${name}"/>`;
    const fill = k.FaceColorMatrixFillColor, comp = 1 - k.FaceColorMatrixMaxLumaSDR, d = k.BlurFillDarkenOpacity, l = k.BlurFillLightenOpacity, n = k.BlurFillNormalOpacity, luma = ".2126 .7152 .0722";
    const faceCM = `<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="out"/>`;   // the face matrix with the fill folded in (faceMatrix) — its output is the face `out`
    /* BlurFill (menu-card-material §7c, R82 correction): b = the UNREFRACTED capture's mip lod = log2(BlurFillBlurRadius 8) = 3 (level std 9.581 capture px → σ 38.32 pt) sampled at
       uv ± .75 mip-3 texels (a texel = 8 capture px = 32 pt → ±24 pt, on both axes) and averaged; c′ = Darken·min(c, b) + Lighten·max(c, b) + (1 − D − L)·c, c″ = mix(c′, b, Normal), c = the
       refracted colour. So the stage lives in f1 (which has both the source and the refracted mix) — no σ-in-quadrature over the refracted output (R63's 近似) */
    const bfSig = mixStd(lod(k.BlurFillBlurRadius)) / CAPTURE, bfOff = 0.75 * 8 / CAPTURE;
    const blurFill = `<feGaussianBlur in="SourceGraphic" stdDeviation="${bfSig.toFixed(2)}" result="bfb"/><feOffset in="bfb" dx="${bfOff}" dy="${bfOff}" result="bfp"/><feOffset in="bfb" dx="${-bfOff}" dy="${-bfOff}" result="bfm"/><feComposite in="bfp" in2="bfm" operator="arithmetic" k2=".5" k3=".5" result="bf"/>`
      + `<feBlend in="blur" in2="bf" mode="darken" result="mn"/><feBlend in="blur" in2="bf" mode="lighten" result="mx"/>`
      + `<feComposite in="mn" in2="mx" operator="arithmetic" k2="${d}" k3="${l}" result="dl"/><feComposite in="dl" in2="blur" operator="arithmetic" k2="1" k3="${1 - d - l}" result="bfo"/>`
      + `<feComposite in="bfo" in2="bf" operator="arithmetic" k2="${1 - n}" k3="${n}" result="c0"/>` + alphaOne("c0", "c");
    const maxLuma = maxLumaChain("c", comp, luma);
    /* every generated image is made opaque beyond the panel box (R57′: feBlend multiply leaks (1 − α)·source at a half-transparent image edge — a bright ring the blurs spread inward): maps over (128,128,0) = no displacement / zero weight, band images over black */
    const refraction = img(im.inner, "mapi0") + img(im.outer, "mapo0") + `<feFlood flood-color="rgb(128,128,0)" result="mid"/><feComposite in="mapi0" in2="mid" operator="over" result="mapi"/><feComposite in="mapo0" in2="mid" operator="over" result="mapo"/>` + selCh("mapi", 2, "wr") + invert("wr", "wri")
      + `<feDisplacementMap in="blur0" in2="mapi" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="c1"/><feDisplacementMap in="blur0" in2="mapo" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="c2"/>`
      + `<feBlend in="c1" in2="wri" mode="multiply" result="q1"/><feBlend in="c2" in2="wr" mode="multiply" result="q2"/><feComposite in="q1" in2="q2" operator="arithmetic" k2="1" k3="1" result="blur"/>`;
    /* bleed: the backdrop's capture average displaced outward by the bleed map, through the bleed colour matrix; the weight = Opacity · w(d) · darken(luma).
       The average: the capture box (panel ± CAPM — the menu's own capture margin is unread, the alert's 60.2 taken) TILED, then blurred with σ = min(293, M2 / 3) inside
       f2's wider region — Chrome ignores feGaussianBlur's edgeMode (a σ 293 blur in a 120 margin blurred in transparency), and a tiled box's blur is its mean (R57′) */
    const CAPM = k.BleedBlurRadius, M2 = 300, bleedBlur = Math.min(bleedSig, M2 / 3);   // CAPM: the menu backdrop's marginWidth 58.45 = BleedBlurRadius (数据 R84, menu-glass-sdfdump §2 layers[32]; UIKit takes the largest of four keys — bleed's is the BlurRadius)
    const bleed = img(im.bleed, "mapb0") + `<feFlood flood-color="rgb(128,128,0)" result="midb"/><feComposite in="mapb0" in2="midb" operator="over" result="mapb"/>` + selCh("mapb", 2, "wb")
      + `<feOffset in="SourceGraphic" dx="0" dy="0" x="${-CAPM}" y="${-CAPM}" width="${im.W + 2 * CAPM}" height="${im.H + 2 * CAPM}" result="cap" data-menu-cap="${CAPM}"/><feTile in="cap" result="tiled"/><feGaussianBlur in="tiled" stdDeviation="${bleedBlur.toFixed(2)}" result="bb"/>`
      + `<feDisplacementMap in="bb" in2="mapb" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="bd"/><feColorMatrix in="bd" type="matrix" values="${bleedCM}" result="cb"/>`
      + `<feColorMatrix in="out" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="lm"/><feComponentTransfer in="lm" result="lx"><feFuncR type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncG type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncB type="linear" slope="${dk[0]}" intercept="${dk[1]}"/></feComponentTransfer>`
      + tf3("w4", "lx", lut((L) => k.BleedOpacity * L ** 4, 65))   /* w = Opacity · L⁴ as one luma LUT (65 samples of the quartic), then × w(d) from the map */
      + `<feBlend in="w4" in2="wb" mode="multiply" result="wbl"/>` + invert("wbl", "wbli")
      + `<feBlend in="out" in2="wbli" mode="multiply" result="o0"/><feBlend in="cb" in2="wbl" mode="multiply" result="o1"/><feComposite in="o0" in2="o1" operator="arithmetic" k2="1" k3="1" result="ob"/>`;
    /* the highlight layer: two stages (main bands, then diffuse), each out ← (1 − α)·out + α·V(out) */
    const highlight = img(im.hl, "hl0") + img(im.hl2, "hl20") + `<feFlood flood-color="rgb(0,0,0)" result="blk"/><feComposite in="hl0" in2="blk" operator="over" result="hl"/><feComposite in="hl20" in2="blk" operator="over" result="hl2"/>` + `<feColorMatrix in="ob" type="matrix" values="${HLK.vibrant.join(" ")} 0 0 0 1 0" result="v1"/>` + invert("hl", "hli")
      + `<feBlend in="ob" in2="hli" mode="multiply" result="h0"/><feBlend in="v1" in2="hl" mode="multiply" result="h1"/><feComposite in="h0" in2="h1" operator="arithmetic" k2="1" k3="1" result="oh"/>`
      + `<feColorMatrix in="oh" type="matrix" values="${HLK.vibrant.join(" ")} 0 0 0 1 0" result="v2"/>` + invert("hl2", "hl2i")
      + `<feBlend in="oh" in2="hl2i" mode="multiply" result="g0"/><feBlend in="v2" in2="hl2" mode="multiply" result="g1"/><feComposite in="g0" in2="g1" operator="arithmetic" k2="1" k3="1" result="final"/>`;
    /* two filters (R63): the chain with refraction + bleed + highlight is ~35 primitives with a σ 293 blur — Chrome paints a url() filter every frame the panel
       repaints (it is not composited), which starved the morph (3–7 frames per 1.5 s vs 70 without it); so the morph runs on #menu-glass-f0 = the R1 / R1′ chain
       and the copy switches to the full #menu-glass-f once the panel has settled (one paint), back to f0 for the dismiss morph */
    const head = (id, m = M) => `<filter id="${id}" filterUnits="userSpaceOnUse" x="${-m}" y="${-m}" width="${im.W + 2 * m}" height="${im.H + 2 * m}" color-interpolation-filters="sRGB" data-theme="${theme}" data-margin="${m}" data-blur-radius="${k.BlurRadius}" data-sigma="${k.BlurRadius * 4}" data-bf-sigma="${bfSig.toFixed(2)}" data-bf-off="${bfOff}" data-maxluma-complement="${comp}" data-face="${faceMatrix(k)}" data-bleed-sigma="${bleedSig.toFixed(2)}" data-bleed-blur="${bleedBlur.toFixed(2)}" data-bleed-cm="${bleedCM}" data-size="${im.W}x${im.H}">`;
    /* the rest chain is split over three nested elements (copy: f1 = blur + refraction; wrapper 2: f2 = BlurFill + MaxLuma + face + fill; wrapper 3: f3 = bleed + highlight):
       Blink turns a filter graph into a tree — every `in` reference re-evaluates its subtree — and one 56-primitive chain with its fan-outs wedged headless Chrome
       (bleed + highlight together; either alone ran); each element's SourceGraphic is a raster, so the fan-outs stay cheap */
    svg.innerHTML = head("menu-glass-f1", 220) + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur0"/>${refraction}${blurFill}</filter>`   /* f1 = blur + refraction + BlurFill (b from the unrefracted source, §7c); its region 220 ≥ f2's 300 − its blurs' reach: f2 samples an opaque raster wherever its σ 100 tile blur reads */
      + head("menu-glass-f2", M2) + `${maxLumaChain("SourceGraphic", comp, luma)}${faceCM}${bleed}</filter>`   /* the bleed's capture sample = this filter's SourceGraphic (the BlurFilled refracted mix, negligible under σ 100), its weight from `out` (R57′: it had been sampling the face output) */
      + head("menu-glass-f3") + `${highlight.replace(/in="ob"/g, 'in="SourceGraphic"')}</filter>`
      + head("menu-glass-f") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur0"/>${refraction}${blurFill}${maxLuma}${faceCM}${bleed}${highlight}</filter>`
      + head("menu-glass-f0") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur"/>${blurFill}${maxLuma}${faceCM}</filter>`
      + `<filter id="menu-glass-ring" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="${k.RingShadowBlurRadius}"/></filter>`; return k; };
  /* the ring band: the rounded rect (the panel's box) shifted RingShadowOffset down, the band = the shape minus the same shape inset by the stroke width (evenodd) */
  const ringPath = (w, h, r, off, sw) => { const rr = (x, y, ww, hh, rad) => { const q = Math.max(0, Math.min(rad, ww / 2, hh / 2)); return `M${x + q} ${y}H${x + ww - q}A${q} ${q} 0 0 1 ${x + ww} ${y + q}V${y + hh - q}A${q} ${q} 0 0 1 ${x + ww - q} ${y + hh}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + hh - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
    return rr(0, off, w, h, r) + " " + rr(sw, off + sw, w - 2 * sw, h - 2 * sw, Math.max(0, r - sw)); };
  const buildGlass = (panel, W, H) => { const theme = glassTheme(), k = ensureFilter(theme, W, H); const main = document.getElementById("app"); if (!main) return null;
    const layer = document.createElement("div"); layer.className = "menu-glass"; const copy = main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim").forEach((e) => e.remove()); copy.className = "menu-glass-copy"; copy.setAttribute("aria-hidden", "true"); copy.inert = true;
    const mr = main.getBoundingClientRect(); copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;min-height:${Math.max(mr.height, innerHeight + 200)}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};filter:url(#menu-glass-f0)`;   // the morph's chain; the full chain once settled (R63); the page colour under #app (body's, #app paints none — R57′: a transparent-backed copy blurred to α < 1 let the live page through the glass)
    const ring = document.createElementNS(NS, "svg"); ring.setAttribute("class", "menu-glass-ring"); ring.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;mix-blend-mode:multiply;pointer-events:none;overflow:visible"; const path = document.createElementNS(NS, "path"); path.setAttribute("fill", "#000"); path.setAttribute("fill-rule", "evenodd"); path.setAttribute("fill-opacity", String(k.RingShadowOpacity)); path.setAttribute("filter", "url(#menu-glass-ring)"); ring.appendChild(path);
    const w2 = document.createElement("div"), w3 = document.createElement("div"); w2.className = "menu-glass-w2"; w3.className = "menu-glass-w3"; for (const w of [w2, w3]) w.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none";
    w2.appendChild(copy); w3.appendChild(w2); layer.append(w3, ring); panel.insertBefore(layer, panel.firstChild);
    return { layer, copy, w2, w3, outer: w3, ring, path, mr, theme, keys: k }; };
  const placeGlass = (g, s) => { if (!g) return; const w = s.width.x, h = s.height.x, r = s.r.x; g.outer.style.transform = `translate(${g.mr.left - s.left.x}px, ${g.mr.top - s.top.x}px)`;   // the copy (in its wrappers) stays on the page's pixels while the panel moves

    g.ring.setAttribute("viewBox", `0 0 ${Math.max(1, w)} ${Math.max(1, h)}`); g.path.setAttribute("d", ringPath(w, h, r, g.keys.RingShadowOffset, g.keys.RingShadowStrokeWidth)); };
  /* R63: the filter's region and its generated images are set ONCE per open on the panel's REST box in the copy's coordinates (a per-frame attribute change
     would re-render the whole chain every frame of the morph; the copy's transform alone does not): during the .3 s morph the maps / bands sit at the rest
     box while the panel is still growing towards it — 记录 */
  const placeGlassRest = (g, to) => { if (!g) return; const px = to.left - g.mr.left, py = to.top - g.mr.top, w = to.width, h = to.height;
    for (const id of ["menu-glass-f", "menu-glass-f0", "menu-glass-f1", "menu-glass-f2", "menu-glass-f3"]) { const fx = document.getElementById(id); if (!fx) continue; const m = +fx.dataset.margin || 120;   // each filter's own margin (f1 220, f2 300 for the bleed's tile blur, the rest 120 — the bleed map reaches ≤ 58.45 pt outside)
      fx.setAttribute("x", String(px - m)); fx.setAttribute("y", String(py - m)); fx.setAttribute("width", String(w + 2 * m)); fx.setAttribute("height", String(h + 2 * m));
      for (const im of fx.querySelectorAll("feImage")) { im.setAttribute("x", String(px)); im.setAttribute("y", String(py)); im.setAttribute("width", String(w)); im.setAttribute("height", String(h)); }
      /* the capture box, clamped to the copy's own box (a panel near the page's edge: the copy has no pixels beyond it — native clamp_to_edge would replicate the edge column; the clamped box's mean drops that strip instead) */
      const cap = fx.querySelector("[data-menu-cap]"); if (cap) { const cm = +cap.dataset.menuCap || 58.45, cw = g.copy.offsetWidth, ch = g.copy.offsetHeight, x0 = Math.max(0, px - cm), y0 = Math.max(0, py - cm), x1 = Math.min(cw, px + w + cm), y1 = Math.min(ch, py + h + cm); cap.setAttribute("x", String(x0)); cap.setAttribute("y", String(y0)); cap.setAttribute("width", String(Math.max(1, x1 - x0))); cap.setAttribute("height", String(Math.max(1, y1 - y0))); } } };
  /* ---- R63′: the in-shader KeyFill's STROKE mode (keyfill-highlight.md §2c; keys menu-glass-sdfdump §2: Amount .4, Angle 1.571, ColorBias −.3, EffectOffset −.5333,
     Height .5333, SpreadSDR 1.85 light / 1.309 dark). stroke_mode = (EffectOffset < 0) ∧ |Height + EffectOffset| < .001 = 1 → the band is OUTSIDE the shape: from
     half a device pixel inside the edge to h = .5333 pt beyond it (prof 1, aa_in = 1 − cov, aa_out = sat(e/fw + .5), e = h − d, fw = one device pixel), per pixel
     k = Σ_{key, fill} v·ang / (1 + a·(1 − v·ang)), a = 1/Amount − 2 = .5, ang = sat((±n·dir − S)/(1 − S)), S = cos(SpreadSDR) (f_EDR 0), dir = (sin Angle, −cos Angle) =
     (1, 0): the left / right sides get k 1 on the outer pixel, the top / bottom sat(−S/(1 − S)) = .216 twice (.31 after the compression) light and 0 dark.
     Colour (§2c %727–%853, α < 1 pixels): B = the capture under the pixel, B′ = face_cm(B) (with the MaxLuma compression), ColorBias < 0 → min(B′, B), B″ = mix(B, ·, k),
     rgb′ = B″·(1 + ColorBias·k·(3 − 2·B″)), extension 1 → α′ = k → on screen the pixel IS rgb′. The panel clips its children (overflow hidden), so the stroke is
     its own fixed layer under the panel (z 8, inserted before it): a second copy of #app clipped by clip-path to the ring [edge − fw/2, edge + h + fw] and filtered
     by #menu-stroke-f (the k map at devicePixelRatio px/pt over the panel box ± 3 pt, the chain above in feBlend darken / multiply / a 3x − 2x² LUT). Placed once at
     the rest box when the full chain comes on (settled), removed for the morph and at close (形变期间无描边: 记录). */
  const strokeMap = (W, H, r, k, dpr) => { const E = 3, S = Math.cos(k.KeyFillHighlightSpreadSDR), a = 1 / k.KeyFillHighlightAmount - 2, h = k.KeyFillHighlightHeight, fw = 1 / dpr, dir = [Math.sin(k.KeyFillHighlightAngle), -Math.cos(k.KeyFillHighlightAngle)];
    const w = Math.round((W + 2 * E) * dpr), hh = Math.round((H + 2 * E) * dpr), c = document.createElement("canvas"); c.width = w; c.height = hh; const ctx = c.getContext("2d"), id = ctx.createImageData(w, hh); let kmax = 0, kside = 0, ktop = 0;
    for (let j = 0; j < hh; j++) for (let i = 0; i < w; i++) { const x = (i + .5) / dpr - E - W / 2, y = (j + .5) / dpr - E - H / 2; const [d, gsx, gsy] = sdfSuper(x, y, W / 2, H / 2, r); const [gx, gy] = gOval(x, y, W / 2, H / 2, gsx, gsy, k.GradientOvalization); const o = (j * w + i) * 4; let kk = 0;   // R63″: n·dir on the ovalized normal
      const cov = satf(0.5 - d / fw);
      if (!(d - h >= fw / 2 || cov >= 1)) { const e = h - d, v = (1 - cov) * satf(e / fw + 0.5), nd = gx * dir[0] + gy * dir[1];
        for (const sgn of [1, -1]) { const ang = satf((sgn * nd - S) / (1 - S)), va = v * ang; kk += va / (1 + a * (1 - va)); } kk = Math.min(1, kk); }
      id.data[o] = id.data[o + 1] = id.data[o + 2] = Math.round(255 * kk); id.data[o + 3] = 255; kmax = Math.max(kmax, kk);
      if (Math.abs(y) < 0.5 && x < -W / 2 && x > -W / 2 - 1.5 * fw) kside = Math.max(kside, kk); if (Math.abs(x) < 0.5 && y < -H / 2 && y > -H / 2 - 1.5 * fw) ktop = Math.max(ktop, kk); }
    ctx.putImageData(id, 0, 0); return { href: c.toDataURL("image/png"), E, dpr, kmax, kside, ktop }; };
  const strokeFilter = (theme, W, H, r) => { const k = glassKeys(theme), dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)), m = strokeMap(W, H, r, k, dpr), E = m.E, comp = 1 - k.FaceColorMatrixMaxLumaSDR, luma = ".2126 .7152 .0722", bias = -k.KeyFillHighlightColorBias;
    let svg = document.getElementById("menu-stroke-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "menu-stroke-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const mode = k.KeyFillHighlightColorBias < 0 ? "darken" : "lighten", qmax = 9 / 8;   // 3x − 2x² peaks at 1.125 (x = .75): the LUT stores it ÷ 1.125
    svg.innerHTML = `<filter id="menu-stroke-f" filterUnits="userSpaceOnUse" x="${-E}" y="${-E}" width="${W + 2 * E}" height="${H + 2 * E}" color-interpolation-filters="sRGB" data-theme="${theme}" data-e="${E}" data-dpr="${dpr}" data-kmax="${m.kmax.toFixed(3)}" data-kside="${m.kside.toFixed(3)}" data-ktop="${m.ktop.toFixed(3)}" data-s="${Math.cos(k.KeyFillHighlightSpreadSDR).toFixed(4)}" data-bias="${bias}">`
      + `<feImage href="${m.href}" preserveAspectRatio="none" x="${-E}" y="${-E}" width="${W + 2 * E}" height="${H + 2 * E}" result="k0" data-stroke-img="1"/><feFlood flood-color="rgb(0,0,0)" result="blk"/><feComposite in="k0" in2="blk" operator="over" result="kk"/>` + invert("kk", "kki")
      + maxLumaChain("SourceGraphic", comp, luma) + `<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/><feBlend in="SourceGraphic" in2="face" mode="${mode}" result="bmin"/>`
      + `<feBlend in="SourceGraphic" in2="kki" mode="multiply" result="t1"/><feBlend in="bmin" in2="kk" mode="multiply" result="t2"/><feComposite in="t1" in2="t2" operator="arithmetic" k2="1" k3="1" result="bmix"/>`
      + tf3("qh", "bmix", lut((x) => (3 * x - 2 * x * x) / qmax)) + `<feBlend in="qh" in2="kk" mode="multiply" result="t"/>` + invert("t", "ti")
      + `<feComposite in="bmix" in2="ti" operator="arithmetic" k2="1" k3="${(bias * qmax).toFixed(5)}" k4="${(-bias * qmax).toFixed(5)}" result="out"/></filter>`;   // rgb′ = B″ − bias·k·(3B″ − 2B″²): + c·(1 − t) − c keeps α 1
    return { E, dpr, map: m }; };
  const roundRect = (x, y, w, h, r) => { const q = Math.max(0, Math.min(r, w / 2, h / 2)); return `M${x + q} ${y}H${x + w - q}A${q} ${q} 0 0 1 ${x + w} ${y + q}V${y + h - q}A${q} ${q} 0 0 1 ${x + w - q} ${y + h}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + h - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
  const buildStroke = (g, panel, to, r) => { if (!g || !g.copy) return null; const main = document.getElementById("app"); if (!main) return null; const W = to.width, H = to.height, th = g.theme, f = strokeFilter(th, W, H, r), E = f.E, fw = 1 / f.dpr, h = g.keys.KeyFillHighlightHeight;
    const el = document.createElement("div"); el.className = "menu-stroke"; el.setAttribute("aria-hidden", "true"); const L = to.left - E, T = to.top - E;
    el.style.cssText = `position:fixed;left:${L}px;top:${T}px;width:${W + 2 * E}px;height:${H + 2 * E}px;overflow:hidden;pointer-events:none;z-index:8;clip-path:path(evenodd, "${roundRect(E - h - fw, E - h - fw, W + 2 * (h + fw), H + 2 * (h + fw), r + h + fw)} ${roundRect(E + fw / 2, E + fw / 2, W - fw, H - fw, Math.max(0, r - fw / 2))}")`;
    const copy = main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, .menu-stroke").forEach((e) => e.remove()); copy.className = "menu-stroke-copy"; copy.inert = true;
    const mr = g.mr; copy.style.cssText = `position:absolute;left:${mr.left - L}px;top:${mr.top - T}px;width:${mr.width}px;min-height:${Math.max(mr.height, innerHeight + 200)}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};filter:url(#menu-stroke-f)`;
    const fx = document.getElementById("menu-stroke-f"), px = to.left - mr.left, py = to.top - mr.top; fx.setAttribute("x", String(px - E)); fx.setAttribute("y", String(py - E)); const im = fx.querySelector("feImage"); im.setAttribute("x", String(px - E)); im.setAttribute("y", String(py - E));
    el.appendChild(copy); document.body.insertBefore(el, panel); return el; };
  const glassFull = (g, on) => { if (!g || !g.copy) return; g.copy.style.filter = on ? "url(#menu-glass-f1)" : "url(#menu-glass-f0)"; g.w2.style.filter = on ? "url(#menu-glass-f2)" : ""; g.w3.style.filter = on ? "url(#menu-glass-f3)" : "";
    if (g.stroke) { g.stroke.remove(); g.stroke = null; } if (on && cur && cur.panel) g.stroke = buildStroke(g, cur.panel, cur.to, cur.s.r.x); };   // R63′: the stroke layer only at rest
  const apply = () => { const p = cur.panel.style, s = cur.s; p.left = s.left.x + "px"; p.top = s.top.x + "px"; p.width = s.width.x + "px"; p.height = s.height.x + "px"; p.borderRadius = s.r.x + "px"; p.opacity = String(Math.max(0, Math.min(1, s.a.x))); placeGlass(cur.glass, s); };
  const settled = (goal) => Object.keys(goal).every((k) => Math.abs(cur.s[k].x - goal[k]) < 0.05 && Math.abs(cur.s[k].v) < 1);
  const strip = () => { if (!cur) return; cancelAnimationFrame(cur.raf); if (cur.glass && cur.glass.stroke) { cur.glass.stroke.remove(); cur.glass.stroke = null; } cur.panel.remove(); cur.scrim.remove(); removeEventListener("keydown", onKey); cur = null; };
  const tick = (now) => { if (!cur) return;
    if (now <= cur.prev) { cur.raf = requestAnimationFrame(tick); return; }   // a frame stamped before the spring's start (Chrome: rAF's `now` is the frame's start, which can precede the call): nothing to integrate yet, the time base stays
    const dt = Math.min(1, (now - cur.prev) / 1000); cur.prev = now;   // time-based like a CA spring: a stalled frame lands where the clock says (the analytic step is exact for any dt); no 40 ms clamp — that clamp made the panel fall behind its own closed form after every long frame (验收 00:2x: rms 7 pt under load), only a > 1 s stall is cut
    const goal = cur.phase === "in" ? cur.goalIn : cur.goalOut, spec = cur.phase === "in" ? (cur.reduced ? REDUCE : APPEAR) : (cur.reduced ? REDUCE : DISMISS);
    for (const k of Object.keys(goal)) Motion.spring(cur.s[k], goal[k], spec, dt);
    cur.t = (now - cur.t0) / 1000; cur.frame = (cur.frame || 0) + 1;   // the driver's own clock: every frame's x is the closed form at this t (the analytic step is exact)
    apply();
    if (settled(goal)) { if (cur.phase === "out") { strip(); return; } cur.raf = 0; glassFull(cur.glass, true); return; }   // "in" settled: the panel rests, the loop stops; the glass switches to the full chain (R63)
    cur.raf = requestAnimationFrame(tick); };
  const run = () => { if (cur.raf) cancelAnimationFrame(cur.raf); cur.prev = performance.now(); cur.raf = requestAnimationFrame(tick); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function open(anchor, sel, o) {   // o.reduced: the reduce-motion path forced (the acceptance's hook; the page never passes it — the media query decides)
    strip();
    const scrim = document.createElement("div"); scrim.className = "menu-scrim";
    const panel = document.createElement("div"); panel.className = "menu morph"; panel.setAttribute("role", "menu");
    const body = document.createElement("div"); body.className = "menu-body"; panel.appendChild(body);
    for (const o of sel.options) {
      const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "menuitemradio"); if (o.selected) b.classList.add("on");
      const ck = document.createElement("i"); ck.className = "ck"; const sym = typeof SYM !== "undefined" && SYM["checkmark"];   // view.js's SYM is a top-level const (not on window)
      if (sym) ck.setAttribute("style", `-webkit-mask-image:url(${sym});mask-image:url(${sym})`);
      b.appendChild(ck); b.appendChild(document.createTextNode(o.textContent));
      b.onclick = () => { if (sel.value !== o.value) { sel.value = o.value; sel.dispatchEvent(new Event("change", { bubbles: true })); } close(); };
      body.appendChild(b);
    }
    scrim.onclick = close;
    document.body.append(scrim, panel);
    const h = body.offsetHeight;   // items × 42 + the 10 / 10 insets
    const glass = buildGlass(panel, 250, h);
    const from = anchorRect(anchor), to = restRect(anchor, h), reduced = o && o.reduced != null ? !!o.reduced : reduce();
    placeGlassRest(glass, to);
    const start = reduced ? { ...to } : from;
    const s = { left: { x: start.left, v: 0 }, top: { x: start.top, v: 0 }, width: { x: start.width, v: 0 }, height: { x: start.height, v: 0 }, r: { x: reduced ? R : cornerOf(anchor), v: 0 }, a: { x: reduced ? 0 : 1, v: 0 } };
    cur = { panel, scrim, sel, anchor, from, to, s, reduced, glass, phase: "in", goalIn: { left: to.left, top: to.top, width: to.width, height: to.height, r: R, a: 1 }, goalOut: null, prev: 0, raf: 0, t0: 0 };
    apply(); addEventListener("keydown", onKey); run(); cur.t0 = cur.prev;   // t0 = the spring's start (the call's performance.now()): the closed form x(t) holds at t = frame timestamp − t0
  }
  function close() {
    if (!cur) return;
    if (cur.phase === "out") return;
    const back = anchorRect(cur.anchor);   // the button's frame now (the page may have scrolled)
    cur.phase = "out"; cur.from = { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x }; cur.to = back;
    cur.goalOut = cur.reduced ? { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, r: R, a: 0 } : { left: back.left, top: back.top, width: back.width, height: back.height, r: cornerOf(cur.anchor), a: 1 };
    cur.scrim.style.pointerEvents = "none"; glassFull(cur.glass, false); run(); cur.t0 = cur.prev; cur.t = 0; cur.frame = 0;   // the dismiss morph on the light chain (R63)
  }
  /* hidden strips the state at once (BOARD A6 template): nothing animates while the page is away and a half-open menu must not come back */
  const onHidden = (force) => { if (force || document.hidden) strip(); };
  document.addEventListener("visibilitychange", () => onHidden(false));
  window.Menu = { glass: { keys: glassKeys, built: BUILT, unbuilt: UNBUILT, gOval, sdf: sdfSuper, theme: glassTheme, bleedSigma: () => mixStd(lod(glassKeys(glassTheme()).BleedBlurRadius)) / CAPTURE, images: glassImages }, morph: MORPH, springs: { appear: [...APPEAR], dismiss: [...DISMISS], reduce: [...REDUCE] }, open, close, onHidden, state: () => cur ? { phase: cur.phase, from: { ...cur.from }, to: { ...cur.to }, reduced: cur.reduced, t0: cur.t0, t: cur.t || 0, frame: cur.frame || 0,
    x: { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, a: cur.s.a.x } } : null };
})();
