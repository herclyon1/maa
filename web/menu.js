/* menu.js — the value row's pull-down menu: a geometry morph from the button's frame to the panel, in place of the old scale-and-fade
   (BOARD.md #3, night batch: geometry and timing only, no material).
   Basis (read values): menu-motion-formula.md §0 table / §2 — appear = one spring each for position x / y, width, height, ζ .8 / response .3 s
   (the liquidMorph spec, ω = 2π/.3); dismiss = the same four with ζ .9 / .3 (liquidMorphShrink); reduce-motion = ζ 1 / .15 cross-fade
   (liquidMorphReduceMotion); no dimming (_hasVisibleBackground NO, the scrim stays transparent); the source is the trigger button's own frame
   (morphPreviewFromAttachmentPoint, anchor (.5, .5)) — here the .menubtn's rect; the corner follows the same spring from the button's corner to
   the menu's (§4.1). menu-card-material.md §1.2 — width 250 (defaultMenuWidth), corner 32 (menuCornerRadius), section insets 10 / 10, item 42
   (the item rules stay index.html's `.menu button`). The panel's placement (below the value, 6 pt gap, ≥ 8 pt from the edges, above when
   there is no room) is the page's existing rule (view.js openMenu), kept.
   Read since (menu-motion-formula.md §7b, R18b): the panel's items have NO per-item delay (the list view has no stagger path; the cells' state
   update does not touch alpha / transform) — the items sit in the panel from the first frame, as here; the "intermediate shape" is a geometry
   interpolation (MagicMorphLayer is a CALayer: frame / corner / transform per destination), not an SDF blend, so it would be a second target on
   the rect springs with the .03 s second step — but how that intermediate rect is computed (jWidthRatio 0 / jHeightRatio .8 / maxJHeight 200)
   is not read, so the four springs still run straight to the target (待读, R18a's live parameters); the refraction lens on the morphing shape
   (lensingSDFLayer) is 不可表达 here; the content's cross-blur / contentScale on the menu path is unread (§6, R18a).
   Springs come from web/motion.js only (BOARD A7, #1). Without Motion this file defines nothing and view.js's old openMenu stays in charge
   (its first line is `if (window.Menu) return Menu.open(anchor, sel);`). */
(function () {
  if (!window.Motion || typeof Motion.spring !== "function") return;
  const APPEAR = [0.8, 0.3], DISMISS = [0.9, 0.3], REDUCE = [1, 0.15];   // [ζ, response s]
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
    light: { BlurRadius: 5, BlurDistance0: -83.5, BlurDistance1: -1, BlurDistance2: 0, BlurDistance3: 0, BlurOpacity0: 0.8, BlurOpacity1: 0.4, BlurOpacity2: 0.5, BlurOpacity3: 1, BlurFillBlurRadius: 8, BlurFillDarkenOpacity: 0, BlurFillLightenOpacity: 0.9, BlurFillNormalOpacity: 0.5,
      FaceColorMatrixWhite: 1.03, FaceColorMatrixBlack: 0.4, FaceColorMatrixSaturation: 1.2, FaceColorMatrixFillColor: [1, 1, 1, 0.2], FaceColorMatrixMaxLuma: 1, FaceColorMatrixMaxLumaSDR: 0.94, FaceOpacity: 1, Clamp: 1.07, ClampPreserveHue: 0,
      InnerRefractionAmount: -60, InnerRefractionHeight: 20, OuterRefractionAmount: 41.75, OuterRefractionHeight: 33.4, RefractionOpacity: 0.6, RefractionDistance0: -1, RefractionDistance1: 0,
      KeyFillHighlightAmount: 0.4, KeyFillHighlightAngle: 1.571, KeyFillHighlightColorBias: -0.3, KeyFillHighlightEffectOffset: -0.5333, KeyFillHighlightHeight: 0.5333, KeyFillHighlightSpread: 1.676, KeyFillHighlightSpreadSDR: 1.85,
      RingShadowOpacity: 0.06, RingShadowOffset: 8, RingShadowStrokeWidth: 4, RingShadowBlurRadius: 5, RingShadowMask: 1,
      BleedAmount: 58.45, BleedBlurRadius: 58.45, BleedHeight: 58.45, BleedOpacity: 0.5, BleedColorMatrixBlack: 0.9, BleedColorMatrixSaturation: 1.2, BleedColorMatrixWhite: 1, BleedDarkenBlend: 1, BleedDistance0: 1, BleedDistance1: 0,
      ShadowAmount: 0, ShadowOpacity: 0.4, ShadowRadius: 24, ShadowOffset: [0, 8], ShadowColorMatrixFillColor: [0, 0, 0, 0.3], ShadowBlurRadius: 0, ShadowHeight: 0, ShadowDistanceOffset: 0, ShadowVibrancyContribution: 0, ShadowColorMatrixWhite: 1, ShadowColorMatrixBlack: 0, ShadowColorMatrixSaturation: 1,
      SDRGradientDistance0: 0, SDRGradientDistance1: 0, SDRHoldingToneEnabled: 0, SDRHoldingToneWhite: 1, SDRShadowOpacity: 0, MaxHeadroom: 9999 },
    dark: { BlurFillDarkenOpacity: 0.9, BlurFillLightenOpacity: 0, FaceColorMatrixWhite: 1.125, FaceColorMatrixBlack: 0.125, FaceColorMatrixSaturation: 1.3, FaceColorMatrixFillColor: [0, 0, 0, 0], FaceColorMatrixMaxLuma: 0.35, FaceColorMatrixMaxLumaSDR: 0.35, Clamp: 1.308,
      KeyFillHighlightSpread: 1.309, KeyFillHighlightSpreadSDR: 1.309, BleedOpacity: 0.8, BleedColorMatrixBlack: 0.125, BleedColorMatrixSaturation: 1, BleedColorMatrixWhite: 0.5, BleedDarkenBlend: 0, ShadowOpacity: 0.6 } };
  const BUILT = { BlurRadius: "feGaussianBlur σ = 5 × 4 pt (the 1/4-resolution capture, alert-pipeline-plan §1.3)", FaceColorMatrixFillColor: "flood mixed at the fill's alpha after the blur (alert-native-formula §1 face row: 再 mix 填充色)",
    RingShadowOpacity: "SVG band ring σ 5, multiplied (keyfill-highlight §4)", RingShadowOffset: "the band's shape shifted (0, 8)", RingShadowStrokeWidth: "band width 4 inside the shifted edge", RingShadowBlurRadius: "feGaussianBlur σ 5", RingShadowMask: "clipped to the panel (mask 1)",
    Clamp: "no-op on 8-bit values (never above 1)", ShadowAmount: "0 → the no-displacement branch (alert-native-formula §1); no shadow drawn" };
  Object.assign(BUILT, { "FaceColorMatrixWhite/Black/Saturation": "feColorMatrix = YCC⁻¹·D·YCC (Rec.709, menu-card-material §7.1)", FaceColorMatrixMaxLumaSDR: "the pre-compression k = sat(1 − Y·(1 − MaxLumaSDR)), c′ = c·k + .3(1 − k)(c·k − Y·k) (§7.1)", "BlurFillBlurRadius/Darken/Lighten/Normal": "bf = σ 8 × 4 blur (近似 mip 3), darken / lighten blends + arithmetic mixes (§7.2)", "ShadowOpacity/Radius/Offset/ColorMatrixFillColor": "drop-shadow 0 8 24 rgba(0,0,0,.3 × opacity) on the panel (§7.3; 剖面近似)" });
  const UNBUILT = { "BlurDistance*/BlurOpacity*": "the rim's blur reduction (three-stage r(d)): 待做 with the level-mix construction of topbar.js R3″ (not in R63)", "FaceColorMatrixMaxLuma (EDR)": "SDR screen: MaxLumaSDR used (k_EDR 0, §7.1)",
    "KeyFillHighlight* (in-shader)": "待读: Height .5333 + EffectOffset −.5333 → stroke_mode 1 (keyfill §5.1: |height + offset| < .001) — the stroke-mode branch of the shader is unread; the documented band is stroke_mode 0's", "ShadowColorMatrixWhite/Black/Saturation": "待读: how the four shadow colour keys enter set_ycc_composite (§7.3)", "Bleed capture edge": "the capture's marginWidth for the menu is unread: the bleed blur replicates the filter region's edge (M 120 pt) for clamp_to_edge" };
  Object.assign(BUILT, { "InnerRefraction*/OuterRefraction*/RefractionOpacity/RefractionDistance*": "R63: two feDisplacementMaps (maps from the supercircle SDF, formula §3 uv1/uv2) mixed by .6·sat((d + 1)/1)", "Bleed*": "R63: the bleed-blurred backdrop displaced outward 58.45·Dc through the bleed YCC matrix, weight Opacity·w(d)·(luma or 1 − luma)⁴ (alert-native-formula §3 e)", "highlight layer (menu-glass-sdfdump §3)": "R63: the KeyFill bands (main + diffuse, spread 1.5253) through the dumped vibrantColorMatrix, two stages" });
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
         offset (0, 8), the panel's shape — CSS drop-shadow on the panel (the Gaussian profile vs the shader's erf-type one: 剖面近似, as the read says). */
  const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((acc, v, i) => acc + v * B[i][j], 0)));   // 4×4 affine (3×3 + offset column as homogeneous)
  const faceMatrix = (k) => { const W = k.FaceColorMatrixWhite, Bk = k.FaceColorMatrixBlack, sat = k.FaceColorMatrixSaturation;
    const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]];
    const D = [[W - Bk, 0, 0, Bk], [0, sat, 0, .5 - .5 * sat], [0, 0, sat, .5 - .5 * sat], [0, 0, 0, 1]];
    const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]];
    const M = mul(mul(INV, D), YCC); const r = (v) => (+v.toFixed(5)).toString();
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
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const x = (i + 0.5) / PXG - hw, y = (j + 0.5) / PXG - hh; const [d, gx, gy] = sdfSuper(x, y, hw, hh, r); const o = (j * w + i) * 4;
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
  const ensureFilter = (theme, W, H) => { const k = glassKeys(theme); let svg = document.getElementById("menu-glass-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "menu-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const im = glassImages(W || 250, H || 167, k), M = 120, bleedSig = mixStd(lod(k.BleedBlurRadius)) / CAPTURE, bleedCM = yccMatrix(k.BleedColorMatrixWhite, k.BleedColorMatrixBlack, k.BleedColorMatrixSaturation), dk = k.BleedDarkenBlend ? [1, 0] : [-1, 1];
    const img = (href, name) => `<feImage href="${href}" preserveAspectRatio="none" x="0" y="0" width="${im.W}" height="${im.H}" result="${name}" data-menu-img="${name}"/>`;
    const fill = k.FaceColorMatrixFillColor, comp = 1 - k.FaceColorMatrixMaxLumaSDR, d = k.BlurFillDarkenOpacity, l = k.BlurFillLightenOpacity, n = k.BlurFillNormalOpacity, luma = ".2126 .7152 .0722";
    const flood = fill[3] > 0 ? `<feFlood flood-color="rgb(${fill[0] * 255},${fill[1] * 255},${fill[2] * 255})" flood-opacity="${fill[3]}" result="fill"/><feComposite in="fill" in2="face" operator="over" result="out"/>` : `<feComposite in="face" in2="face" operator="over" result="out"/>`;
    const bfExtra = Math.sqrt((k.BlurFillBlurRadius * 4) ** 2 - (k.BlurRadius * 4) ** 2);   // f2 receives f1's σ20 output: the bf blur adds the rest in quadrature (σ 32 total)
    const blurFill = `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurFillBlurRadius * 4}" result="bf"/>`
      + `<feBlend in="blur" in2="bf" mode="darken" result="mn"/><feBlend in="blur" in2="bf" mode="lighten" result="mx"/>`
      + `<feComposite in="mn" in2="mx" operator="arithmetic" k2="${d}" k3="${l}" result="dl"/><feComposite in="dl" in2="blur" operator="arithmetic" k2="1" k3="${1 - d - l}" result="bfo"/>`
      + `<feComposite in="bfo" in2="bf" operator="arithmetic" k2="${1 - n}" k3="${n}" result="c"/>`;
    const maxLuma = comp > 0 && comp < 1 ? `<feColorMatrix in="c" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="Y"/>`
      + `<feComponentTransfer in="Y" result="k"><feFuncR type="linear" slope="${-comp}" intercept="1"/><feFuncG type="linear" slope="${-comp}" intercept="1"/><feFuncB type="linear" slope="${-comp}" intercept="1"/></feComponentTransfer>`
      + `<feComposite in="c" in2="k" operator="arithmetic" k1="1" result="ck"/><feComposite in="Y" in2="k" operator="arithmetic" k1="1" result="Yk"/>`
      + `<feComponentTransfer in="k" result="ik"><feFuncR type="linear" slope="-1" intercept="1"/><feFuncG type="linear" slope="-1" intercept="1"/><feFuncB type="linear" slope="-1" intercept="1"/></feComponentTransfer>`
      + `<feComposite in="ck" in2="Yk" operator="arithmetic" k2="1" k3="-1" result="dp"/><feComposite in="Yk" in2="ck" operator="arithmetic" k2="1" k3="-1" result="dn"/>`
      + `<feComposite in="dp" in2="ik" operator="arithmetic" k1=".3" result="P"/><feComposite in="dn" in2="ik" operator="arithmetic" k1=".3" result="N"/>`
      + `<feComposite in="ck" in2="P" operator="arithmetic" k2="1" k3="1" result="cp"/><feComposite in="cp" in2="N" operator="arithmetic" k2="1" k3="-1" result="ml"/>` : `<feComposite in="c" in2="c" operator="over" result="ml"/>`;
    const refraction = img(im.inner, "mapi") + img(im.outer, "mapo") + selCh("mapi", 2, "wr") + invert("wr", "wri")
      + `<feDisplacementMap in="blur0" in2="mapi" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="c1"/><feDisplacementMap in="blur0" in2="mapo" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="c2"/>`
      + `<feBlend in="c1" in2="wri" mode="multiply" result="q1"/><feBlend in="c2" in2="wr" mode="multiply" result="q2"/><feComposite in="q1" in2="q2" operator="arithmetic" k2="1" k3="1" result="blur"/>`;
    /* bleed: the backdrop at the bleed blur (σ 293 pt, edgeMode duplicate ≈ the capture's clamp_to_edge) displaced outward by the bleed map, through the bleed colour matrix; the weight = Opacity · w(d) · darken(luma) */
    const bleed = img(im.bleed, "mapb") + selCh("mapb", 2, "wb") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${bleedSig.toFixed(2)}" edgeMode="duplicate" result="bb"/>`
      + `<feDisplacementMap in="bb" in2="mapb" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="bd"/><feColorMatrix in="bd" type="matrix" values="${bleedCM}" result="cb"/>`
      + `<feColorMatrix in="out" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="lm"/><feComponentTransfer in="lm" result="lx"><feFuncR type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncG type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncB type="linear" slope="${dk[0]}" intercept="${dk[1]}"/></feComponentTransfer>`
      + `<feComponentTransfer in="lx" result="l4"><feFuncR type="gamma" exponent="4" amplitude="1" offset="0"/><feFuncG type="gamma" exponent="4" amplitude="1" offset="0"/><feFuncB type="gamma" exponent="4" amplitude="1" offset="0"/></feComponentTransfer>`
      + `<feBlend in="l4" in2="wb" mode="multiply" result="l4w"/><feComponentTransfer in="l4w" result="wbl"><feFuncR type="linear" slope="${k.BleedOpacity}"/><feFuncG type="linear" slope="${k.BleedOpacity}"/><feFuncB type="linear" slope="${k.BleedOpacity}"/></feComponentTransfer>` + invert("wbl", "wbli")
      + `<feBlend in="out" in2="wbli" mode="multiply" result="o0"/><feBlend in="cb" in2="wbl" mode="multiply" result="o1"/><feComposite in="o0" in2="o1" operator="arithmetic" k2="1" k3="1" result="ob"/>`;
    /* the highlight layer: two stages (main bands, then diffuse), each out ← (1 − α)·out + α·V(out) */
    const highlight = img(im.hl, "hl") + img(im.hl2, "hl2") + `<feColorMatrix in="ob" type="matrix" values="${HLK.vibrant.join(" ")} 0 0 0 1 0" result="v1"/>` + invert("hl", "hli")
      + `<feBlend in="ob" in2="hli" mode="multiply" result="h0"/><feBlend in="v1" in2="hl" mode="multiply" result="h1"/><feComposite in="h0" in2="h1" operator="arithmetic" k2="1" k3="1" result="oh"/>`
      + `<feColorMatrix in="oh" type="matrix" values="${HLK.vibrant.join(" ")} 0 0 0 1 0" result="v2"/>` + invert("hl2", "hl2i")
      + `<feBlend in="oh" in2="hl2i" mode="multiply" result="g0"/><feBlend in="v2" in2="hl2" mode="multiply" result="g1"/><feComposite in="g0" in2="g1" operator="arithmetic" k2="1" k3="1" result="final"/>`;
    /* two filters (R63): the chain with refraction + bleed + highlight is ~35 primitives with a σ 293 blur — Chrome paints a url() filter every frame the panel
       repaints (it is not composited), which starved the morph (3–7 frames per 1.5 s vs 70 without it); so the morph runs on #menu-glass-f0 = the R1 / R1′ chain
       and the copy switches to the full #menu-glass-f once the panel has settled (one paint), back to f0 for the dismiss morph */
    const head = (id) => `<filter id="${id}" filterUnits="userSpaceOnUse" x="${-M}" y="${-M}" width="${im.W + 2 * M}" height="${im.H + 2 * M}" color-interpolation-filters="sRGB" data-theme="${theme}" data-blur-radius="${k.BlurRadius}" data-sigma="${k.BlurRadius * 4}" data-bf-sigma="${k.BlurFillBlurRadius * 4}" data-maxluma-complement="${comp}" data-face="${faceMatrix(k)}" data-bleed-sigma="${bleedSig.toFixed(2)}" data-bleed-cm="${bleedCM}" data-size="${im.W}x${im.H}">`;
    /* the rest chain is split over three nested elements (copy: f1 = blur + refraction; wrapper 2: f2 = BlurFill + MaxLuma + face + fill; wrapper 3: f3 = bleed + highlight):
       Blink turns a filter graph into a tree — every `in` reference re-evaluates its subtree — and one 56-primitive chain with its fan-outs wedged headless Chrome
       (bleed + highlight together; either alone ran); each element's SourceGraphic is a raster, so the fan-outs stay cheap */
    const f2chain = blurFill.replace(`stdDeviation="${k.BlurFillBlurRadius * 4}"`, `stdDeviation="${bfExtra.toFixed(3)}"`).replace(/in="blur"/g, 'in="SourceGraphic"');
    svg.innerHTML = head("menu-glass-f1") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur0"/>${refraction}</filter>`
      + head("menu-glass-f2") + `${f2chain}${maxLuma}<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/>${flood}</filter>`
      + head("menu-glass-f3") + `${bleed.replace(/in="out"/g, 'in="SourceGraphic"')}${highlight}</filter>`
      + head("menu-glass-f") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur0"/>${refraction}${blurFill}${maxLuma}<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/>${flood}${bleed}${highlight}</filter>`
      + head("menu-glass-f0") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur"/>${blurFill}${maxLuma}<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/>${flood}</filter>`
      + `<filter id="menu-glass-ring" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="${k.RingShadowBlurRadius}"/></filter>`; return k; };
  /* the ring band: the rounded rect (the panel's box) shifted RingShadowOffset down, the band = the shape minus the same shape inset by the stroke width (evenodd) */
  const ringPath = (w, h, r, off, sw) => { const rr = (x, y, ww, hh, rad) => { const q = Math.max(0, Math.min(rad, ww / 2, hh / 2)); return `M${x + q} ${y}H${x + ww - q}A${q} ${q} 0 0 1 ${x + ww} ${y + q}V${y + hh - q}A${q} ${q} 0 0 1 ${x + ww - q} ${y + hh}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + hh - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
    return rr(0, off, w, h, r) + " " + rr(sw, off + sw, w - 2 * sw, h - 2 * sw, Math.max(0, r - sw)); };
  const buildGlass = (panel, W, H) => { const theme = glassTheme(), k = ensureFilter(theme, W, H); const main = document.getElementById("app"); if (!main) return null;
    const layer = document.createElement("div"); layer.className = "menu-glass"; const copy = main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, script, .menu, .menu-scrim").forEach((e) => e.remove()); copy.className = "menu-glass-copy"; copy.setAttribute("aria-hidden", "true"); copy.inert = true;
    const mr = main.getBoundingClientRect(); copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;pointer-events:none;filter:url(#menu-glass-f0)`;   // the morph's chain; the full chain once settled (R63)
    const ring = document.createElementNS(NS, "svg"); ring.setAttribute("class", "menu-glass-ring"); ring.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;mix-blend-mode:multiply;pointer-events:none;overflow:visible"; const path = document.createElementNS(NS, "path"); path.setAttribute("fill", "#000"); path.setAttribute("fill-rule", "evenodd"); path.setAttribute("fill-opacity", String(k.RingShadowOpacity)); path.setAttribute("filter", "url(#menu-glass-ring)"); ring.appendChild(path);
    const w2 = document.createElement("div"), w3 = document.createElement("div"); w2.className = "menu-glass-w2"; w3.className = "menu-glass-w3"; for (const w of [w2, w3]) w.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none";
    w2.appendChild(copy); w3.appendChild(w2); layer.append(w3, ring); panel.insertBefore(layer, panel.firstChild);
    return { layer, copy, w2, w3, outer: w3, ring, path, mr, theme, keys: k }; };
  const placeGlass = (g, s) => { if (!g) return; const w = s.width.x, h = s.height.x, r = s.r.x; g.outer.style.transform = `translate(${g.mr.left - s.left.x}px, ${g.mr.top - s.top.x}px)`;   // the copy (in its wrappers) stays on the page's pixels while the panel moves

    g.ring.setAttribute("viewBox", `0 0 ${Math.max(1, w)} ${Math.max(1, h)}`); g.path.setAttribute("d", ringPath(w, h, r, g.keys.RingShadowOffset, g.keys.RingShadowStrokeWidth)); };
  /* R63: the filter's region and its generated images are set ONCE per open on the panel's REST box in the copy's coordinates (a per-frame attribute change
     would re-render the whole chain every frame of the morph; the copy's transform alone does not): during the .3 s morph the maps / bands sit at the rest
     box while the panel is still growing towards it — 记录 */
  const placeGlassRest = (g, to) => { if (!g) return; const f = document.getElementById("menu-glass-f"); if (!f) return; const px = to.left - g.mr.left, py = to.top - g.mr.top, M = 120, w = to.width, h = to.height;   // M: the region margin (pt) — the bleed samples ≤ 58.45 pt outside; its σ 293 blur replicates the region's edge (edgeMode duplicate) for the capture's clamp_to_edge; 300 pt made ~40 buffers of 1700×1500 device px and wedged headless Chrome
    f.setAttribute("x", String(px - M)); f.setAttribute("y", String(py - M)); f.setAttribute("width", String(w + 2 * M)); f.setAttribute("height", String(h + 2 * M));
    for (const im of f.querySelectorAll("feImage")) { im.setAttribute("x", String(px)); im.setAttribute("y", String(py)); im.setAttribute("width", String(w)); im.setAttribute("height", String(h)); }
    for (const id of ["menu-glass-f0", "menu-glass-f1", "menu-glass-f2", "menu-glass-f3"]) { const fx = document.getElementById(id); if (!fx) continue; for (const a of ["x", "y", "width", "height"]) fx.setAttribute(a, f.getAttribute(a)); for (const im of fx.querySelectorAll("feImage")) { im.setAttribute("x", String(px)); im.setAttribute("y", String(py)); im.setAttribute("width", String(w)); im.setAttribute("height", String(h)); } } };
  const glassFull = (g, on) => { if (!g || !g.copy) return; g.copy.style.filter = on ? "url(#menu-glass-f1)" : "url(#menu-glass-f0)"; g.w2.style.filter = on ? "url(#menu-glass-f2)" : ""; g.w3.style.filter = on ? "url(#menu-glass-f3)" : ""; };
  const apply = () => { const p = cur.panel.style, s = cur.s; p.left = s.left.x + "px"; p.top = s.top.x + "px"; p.width = s.width.x + "px"; p.height = s.height.x + "px"; p.borderRadius = s.r.x + "px"; p.opacity = String(Math.max(0, Math.min(1, s.a.x))); placeGlass(cur.glass, s); };
  const settled = (goal) => Object.keys(goal).every((k) => Math.abs(cur.s[k].x - goal[k]) < 0.05 && Math.abs(cur.s[k].v) < 1);
  const strip = () => { if (!cur) return; cancelAnimationFrame(cur.raf); cur.panel.remove(); cur.scrim.remove(); removeEventListener("keydown", onKey); cur = null; };
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
  window.Menu = { glass: { keys: glassKeys, built: BUILT, unbuilt: UNBUILT, theme: glassTheme, bleedSigma: () => mixStd(lod(glassKeys(glassTheme()).BleedBlurRadius)) / CAPTURE, images: glassImages }, open, close, onHidden, state: () => cur ? { phase: cur.phase, from: { ...cur.from }, to: { ...cur.to }, reduced: cur.reduced, t0: cur.t0, t: cur.t || 0, frame: cur.frame || 0,
    x: { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, a: cur.s.a.x } } : null };
})();
