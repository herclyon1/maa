/* alert-glass.js — the alert panel's glass from the read keys (BOARD R57 / R57′; material only from decoded formulas and dumped keys, A20).
   Keys: the 70-key dumps uiprobe-deep-alert-glasskeys-{light2,dark}.json (alert-native-formula.md §1a, R74) + the highlight layer (UISDFView 320×172,
   vibrantColorMatrix 4×5 + CASDFKeyFillHighlightEffect, both themes alike). Formulas: alert-native-formula.md §1–§4 (§4 ⑦, R75′: the chain closed on
   five greys ≤ 1.1/255 with the three readings below), glass-displacement-formula.md §3, keyfill-highlight.md §2, menu-card-material.md §7.1 (MaxLuma),
   label-end-tear §7 ② / §7b (the continuous-corner supercircle SDF, r 34), nav-bar-scroll-formula.md §3.4b (the mip-level blur).
   Built, in the shader's order, split over three nested filtered elements (f1 on the page copy, f2 / f3 on wrappers — Blink evaluates a filter graph
   as a tree, one long chain wedged Chrome; R63):
     f1  dimming (UIDimmingView black α .2 light / .48 dark under the capture) → the three-stage blur r(d) = 5·(.8 − .4·s1 − .5·s2) as a per-pixel mix
         of pyramid levels (σ = level std ÷ .25 = 8.59 / 18.78 pt; the measured step σ 19.5) → inner −60/20 and outer 43/34.4 refraction mixed by
         .6·sat((d + 1)/1) (RefractionDistance −1 / 0) → BlurFill r 8 (lighten .9 / normal .5 light; darken .9 / normal .5 dark; b = the unrefracted
         capture at mip 3, σ 38.32 pt, sampled at ±.75 mip texels — menu-card-material §7c, R63′);
     f2  MaxLuma with complement 1 − MaxLumaSDR (.06 light / .65 dark; on
         SDR the SDR value applies, §4 ⑦) → the face matrix YCC(white 1.03 / black .4 / sat 1.2; dark 1.125 / .125 / 1.3) with the PREMULTIPLIED fill
         (1,1,1,.2) → ×.8, bias +.2 (light; dark fill 0);
     f3  bleed (Amount / Height / BlurRadius 60.2: the capture at lod 5.9 displaced outward within 60.2 pt of the rim, through YCC(1 / .9 / 1.2; dark
         .5 / .125 / 1), weight Opacity (.5 / .8) · w(d) · luma⁴ (DarkenBlend 1 light) or (1 − luma)⁴ (dark)) → the highlight layer's bands (main + diffuse,
         spread 1.5344) through the dumped vibrant matrix; the soft shadow: drop-shadow 0 8 24 α .3 × ShadowOpacity (.4 / .6).
   Not built / 不可表达 / 近似 (AlertGlass.unbuilt): the in-shader KeyFill (stroke_mode 1, unread), the ring shadow band (stroke 4: 待做), d′ for the blur
   level, the shape's ovalization, the bleed blur's edge replication, BlurFill on the refracted mix. Without an #alert dialog nothing is installed. */
(function () {
  const dlg = document.getElementById("alert"); if (!dlg) return;
  /* R57′: the 70-key dump (alert-native-formula.md §1a, R74: uiprobe-deep-alert-glasskeys-{light2,dark}.json; §4 ⑦ R75′: the chain closed on five greys ≤ 1.1/255) —
     light column, the 17 dark differences in DARK; the 09-19 26-key dump had missed the keys that were set (fill, sat, MaxLumaSDR, the bleed set, the refraction distances, BlurFill …) */
  const LIGHT = { BlurRadius: 5, BlurOpacity0: 0.8, BlurOpacity1: 0.4, BlurOpacity2: 0.5, BlurDistance0: -86, BlurDistance1: -1, BlurDistance2: 0, Clamp: 1.0696,
    FaceColorMatrixWhite: 1.03, FaceColorMatrixBlack: 0.4, FaceColorMatrixSaturation: 1.2, FaceColorMatrixFillColor: [1, 1, 1, 0.2], FaceColorMatrixMaxLuma: 1, FaceColorMatrixMaxLumaSDR: 0.94,
    InnerRefractionAmount: -60, InnerRefractionHeight: 20, OuterRefractionAmount: 43, OuterRefractionHeight: 34.4, RefractionOpacity: 0.6, RefractionDistance0: -1, RefractionDistance1: 0,
    BlurFillBlurRadius: 8, BlurFillLightenOpacity: 0.9, BlurFillDarkenOpacity: 0, BlurFillNormalOpacity: 0.5,
    KeyFillHighlightAmount: 0.4, KeyFillHighlightColorBias: -0.3, KeyFillHighlightSpread: 1.6755, KeyFillHighlightSpreadSDR: 1.85, KeyFillHighlightHeight: 0.5333, KeyFillHighlightEffectOffset: -0.5333, KeyFillHighlightAngle: 1.5708,
    RingShadowOpacity: 0.06, RingShadowStrokeWidth: 4, RingShadowOffset: 8, RingShadowBlurRadius: 5, RingShadowMask: 1, ShadowAmount: 0, ShadowOffset: [0, 8], ShadowOpacity: 0.4, ShadowRadius: 24, ShadowColorMatrixFillColor: [0, 0, 0, 0.3],
    BleedAmount: 60.2, BleedHeight: 60.2, BleedBlurRadius: 60.2, BleedOpacity: 0.5, BleedColorMatrixWhite: 1, BleedColorMatrixBlack: 0.9, BleedColorMatrixSaturation: 1.2, BleedDarkenBlend: 1, BleedDistance0: 1, BleedDistance1: 0,
    SDRGradientDistance0: 0, SDRGradientDistance1: 0, MaxHeadroom: 9999, CaptureScale: 0.25, CaptureMargin: 60.2, Panel: [320, 172], CornerRadius: 34, Dimming: 0.2 };   // Dimming: UIDimmingView black α .2 light / .48 dark (§0; --ios-alert-dimming)
  const DARK = { FaceColorMatrixWhite: 1.125, FaceColorMatrixBlack: 0.125, FaceColorMatrixSaturation: 1.3, FaceColorMatrixFillColor: [0, 0, 0, 0], FaceColorMatrixMaxLuma: 0.35, FaceColorMatrixMaxLumaSDR: 0.35, Clamp: 1.3083,
    KeyFillHighlightSpread: 1.309, KeyFillHighlightSpreadSDR: 1.309, ShadowOpacity: 0.6, BleedColorMatrixWhite: 0.5, BleedColorMatrixBlack: 0.125, BleedColorMatrixSaturation: 1, BleedDarkenBlend: 0, BleedOpacity: 0.8,
    BlurFillLightenOpacity: 0, BlurFillDarkenOpacity: 0.9, Dimming: 0.48 };
  const keysFor = (th) => ({ ...LIGHT, ...(th === "dark" ? DARK : {}) });
  const KEYS = LIGHT;
  const HL = { curvature: 0.75, keyHeight: 1, keySpread: 1.5344, keyAngle: 0, fillAngle: Math.PI, keyAmount: 0.5, fillAmount: 0.5, diffuseAmountScale: 0.15, diffuseHeightScale: 8, diffuseSpreadScale: 0.65,
    vibrant: [1.1202, -0.1894, -0.019, 0, 0.1471, -0.0563, 0.9871, -0.0191, 0, 0.1471, -0.0563, -0.1893, 1.1574, 0, 0.1471] };
  const VB_STD = [0, 2.147, 4.694, 9.581, 19.263, 38.579, 77.023];   // the pyramid levels' stds in capture px (tools/vb_kernel.py, nav-bar-scroll-formula §3.4b)
  const mixStd = (L) => { const k0 = Math.min(Math.floor(L), VB_STD.length - 2), f = L - k0; return Math.sqrt((1 - f) * VB_STD[k0] ** 2 + f * VB_STD[k0 + 1] ** 2); };
  const UNBUILT = { Clamp: "no-op on 8-bit values (limit ≥ 1)", KeyFillInShader: "要建: Height .5333 + EffectOffset −.5333 → stroke_mode 1 — keyfill-highlight §2c read (R80); built for the menu in R63′ (menu.js strokeMap / #menu-stroke-f: a layer outside the pane), the same construction is due here",
    RingShadow: "待做: stroke 4 / offset 8 / blur 5 / mask 1 — the band of keyfill §4 (the menu has it built; not added here yet)", BlurDistancePrime: "d′ = refraction + d: the blur level is taken at d (待读: which refraction term)",
    GradientOvalization: "the backdrop shape's ovalization not read → 0", BleedEdge: "近似: the capture box (panel ± 60.2, clamped to the copy) is TILED and blurred σ 100 for its mean — the native sampler's clamp_to_edge replicates the edge column instead; equal on a flat page", BlurFillTexelPair: "近似: the ±.75 mip-3 texel pair is taken on both axes (uv ± off with off = lod·(.25/size) read as a float2, menu-card-material §7c); one-axis or the base-texel reading (±3 pt) would differ only on structured content" };
  const theme = () => (matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light") || document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const sat = (x) => Math.max(0, Math.min(1, x));
  /* the continuous-corner rounded rect (label-end-tear §7 ②: supercircle_sdf with clamp = sat(2.89158·(1 − hs/r)) = (0, 0) here → the supercircle branch, R = 1.528665·r) */
  const KR = 1.528665;
  const poly = (rho) => (((-0.926054 * rho + 3.15601) * rho - 3.64122) * rho + 1.26803) * rho + 0.268531;
  const sdf = (x, y, hw, hh, r) => { const R = KR * r; const cx = Math.abs(x) - hw, cy = Math.abs(y) - hh; const qx = cx + R, qy = cy + R;
    const ux = Math.max(0, qx / R), uy = Math.max(0, qy / R); const umax = Math.max(ux, uy); const rho = umax > 0 ? Math.min(ux, uy) / umax : 0; const ul = Math.hypot(ux, uy);
    const k = rho * rho * sat(ul) * poly(rho); const f = ul + 1 - 1 / (1 - k); const d = R * (f - 1) + Math.min(Math.max(qx, qy), 0);
    let gx, gy; if (qx + qy > 0) { gx = Math.max(0, qx); gy = Math.max(0, qy); } else if (qx > qy) { gx = 1; gy = 0; } else { gx = 0; gy = 1; }
    const gn = Math.hypot(gx, gy) || 1; return [d, (gx / gn) * (x >= 0 ? 1 : -1), (gy / gn) * (y >= 0 ? 1 : -1)]; };
  const Dc = (t) => 1 - Math.sqrt(Math.max(0, 2 * t - t * t));   // 1 − P at curvature 1 (formula §1 / §3: the refraction's (1 − sqrt(t(2 − t))))
  const level = (r) => Math.max(0, r >= 2 ? Math.log2(r) : Math.log2(1 + r / 2));
  const band = (e, h, cosS, bias, curv, ndir, fw) => { const t = sat(e / h); const prof = (t < 1 ? 1 : 0) * (1 - curv) + (1 - t) * curv; const aa = sat(e / fw + 0.5) * sat((h - e) / fw + 0.5);
    const ang = sat((ndir - cosS) / (1 - cosS)); const vv = e < -5 ? 0 : prof * aa * ang; return vv / (1 + bias * (1 - vv)); };
  const PX = 2;   // px per pt of the generated images
  const images = (() => { const cache = {}; return (W, H) => { const key = W + "x" + H; if (cache[key]) return cache[key];
    const hw = W / 2, hh = H / 2, r = KEYS.CornerRadius, w = Math.round(W * PX), h = Math.round(H * PX);   // the maps use keys shared by both themes (refraction, bleed geometry)
    const mk = () => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };
    const cw = mk(), cin = mk(), cout = mk(), chl = mk(), chl2 = mk(), cbl = mk(); const iw = cw.getContext("2d").createImageData(w, h), iin = cin.getContext("2d").createImageData(w, h), iout = cout.getContext("2d").createImageData(w, h), ihl = chl.getContext("2d").createImageData(w, h), ihl2 = chl2.getContext("2d").createImageData(w, h), ibl = cbl.getContext("2d").createImageData(w, h);
    const S = 128;   // the maps' displacement scale (pt at byte 255 − 128)
    const cosK = Math.cos(HL.keySpread), cosD = Math.cos(HL.diffuseSpreadScale * HL.keySpread), biasD = 1 / (HL.diffuseAmountScale * HL.keyAmount) - 2, hD = HL.diffuseHeightScale * HL.keyHeight, fw = 1 / 3;
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const x = (i + 0.5) / PX - hw, y = (j + 0.5) / PX - hh; const [d, gx, gy] = sdf(x, y, hw, hh, r); const o = (j * w + i) * 4;
      /* the blur level weights */
      const s1 = sat((d - KEYS.BlurDistance0) / (KEYS.BlurDistance1 - KEYS.BlurDistance0)), s2 = sat((d - KEYS.BlurDistance1) / (KEYS.BlurDistance2 - KEYS.BlurDistance1));
      const rr = KEYS.BlurRadius * (KEYS.BlurOpacity0 - KEYS.BlurOpacity1 * s1 - KEYS.BlurOpacity2 * s2); const L = d > 0 ? 0 : level(Math.max(0, rr));
      for (let k = 0; k < 3; k++) iw.data[o + k] = Math.round(255 * Math.max(0, 1 - Math.abs(L - k)));
      iw.data[o + 3] = 255; const wr = Math.round(255 * KEYS.RefractionOpacity * sat((d - KEYS.RefractionDistance0) / (KEYS.RefractionDistance1 - KEYS.RefractionDistance0)));   // the outer-refraction mix weight (kept in the inner map's B: a PNG's alpha would premultiply the weights)
      /* the two refraction maps: D = amount·Dc(t)·g (formula §3 uv1 / uv2), encoded 128 + D·255/S */
      const ti = sat(-d / KEYS.InnerRefractionHeight), to = sat(-d / KEYS.OuterRefractionHeight);
      const di = KEYS.InnerRefractionAmount * Dc(ti), dout = KEYS.OuterRefractionAmount * Dc(to);
      iin.data[o] = Math.round(128 + di * gx * 255 / S); iin.data[o + 1] = Math.round(128 + di * gy * 255 / S); iin.data[o + 2] = wr; iin.data[o + 3] = 255;
      iout.data[o] = Math.round(128 + dout * gx * 255 / S); iout.data[o + 1] = Math.round(128 + dout * gy * 255 / S); iout.data[o + 2] = 0; iout.data[o + 3] = 255;
      /* the bleed map (§4 ⑦ / §3 e): offset 60.2·(1 − sqrt(t(2 − t)))·g outward within 60.2 pt of the rim (0 inside → the point itself); B = w(d) = sat((d − 1)/(0 − 1)) */
      const db = KEYS.BleedAmount * Dc(sat(-d / KEYS.BleedHeight)), wb = Math.round(255 * sat((d - KEYS.BleedDistance0) / (KEYS.BleedDistance1 - KEYS.BleedDistance0)));
      ibl.data[o] = Math.round(128 + db * gx * 255 / S); ibl.data[o + 1] = Math.round(128 + db * gy * 255 / S); ibl.data[o + 2] = wb; ibl.data[o + 3] = 255;
      /* the highlight α (keyfill §2, as lens-webgl.js FS2): key band from the top (dir (0, −1)), fill band from the bottom (dir (0, 1)), each main 1 pt + diffuse 8 pt */
      const e = -d; let a1 = 0, a2 = 0;   // stage 1: the two main bands (key from the top, fill from the bottom) as one α; stage 2: the two diffuse bands (FS2's three sequential mixes)
      if (d <= 0) { for (const dy of [-1, 1]) { const nd = gy * dy; a1 += band(e, HL.keyHeight, cosK, 0, HL.curvature, nd, fw); a2 = 1 - (1 - a2) * (1 - sat(band(e, hD, cosD, biasD, 1, nd, fw))); } }
      ihl.data[o] = ihl.data[o + 1] = ihl.data[o + 2] = Math.round(255 * sat(a1)); ihl.data[o + 3] = 255; ihl2.data[o] = ihl2.data[o + 1] = ihl2.data[o + 2] = Math.round(255 * sat(a2)); ihl2.data[o + 3] = 255; }
    cw.getContext("2d").putImageData(iw, 0, 0); cin.getContext("2d").putImageData(iin, 0, 0); cout.getContext("2d").putImageData(iout, 0, 0); chl.getContext("2d").putImageData(ihl, 0, 0); chl2.getContext("2d").putImageData(ihl2, 0, 0); cbl.getContext("2d").putImageData(ibl, 0, 0);
    cache[key] = { weights: cw.toDataURL("image/png"), inner: cin.toDataURL("image/png"), outer: cout.toDataURL("image/png"), hl: chl.toDataURL("image/png"), hl2: chl2.toDataURL("image/png"), bleed: cbl.toDataURL("image/png"), S, w, h, W, H }; return cache[key]; }; })();
  const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((acc, v, i) => acc + v * B[i][j], 0)));
  const yccMatrix = (W, Bk, s, fill) => { const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]]; const D = [[W - Bk, 0, 0, Bk], [0, s, 0, .5 - .5 * s], [0, 0, s, .5 - .5 * s], [0, 0, 0, 1]];
    const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]]; let M = mul(mul(INV, D), YCC);
    if (fill && fill[3] > 0) M = M.map((row, i) => i < 3 ? row.map((v, j) => v * (1 - fill[3]) + (j === 3 ? fill[i] * fill[3] : 0)) : row);   // §4 ⑦: set_ycc_composite scales the whole matrix by (1 − a) and adds the PREMULTIPLIED fill (rgb·a) to the bias
    const r = (v) => (+v.toFixed(5)).toString(); return [0, 1, 2].map((i) => `${r(M[i][0])} ${r(M[i][1])} ${r(M[i][2])} 0 ${r(M[i][3])}`).join(" ") + " 0 0 0 1 0"; };
  const faceMatrix = (k = KEYS) => yccMatrix(k.FaceColorMatrixWhite, k.FaceColorMatrixBlack, k.FaceColorMatrixSaturation, k.FaceColorMatrixFillColor);
  const bleedMatrix = (k = KEYS) => yccMatrix(k.BleedColorMatrixWhite, k.BleedColorMatrixBlack, k.BleedColorMatrixSaturation, null);
  const invert = (src, name) => `<feComponentTransfer in="${src}" result="${name}"><feFuncR type="linear" slope="-1" intercept="1"/><feFuncG type="linear" slope="-1" intercept="1"/><feFuncB type="linear" slope="-1" intercept="1"/></feComponentTransfer>`;
  const NS = "http://www.w3.org/2000/svg";
  const sel = (src, ch, name) => `<feColorMatrix in="${src}" type="matrix" values="${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  0 0 0 0 1" result="${name}"/>`;
  /* MaxLuma (§4 ⑦, IR %568–%584): c′ = c·k + .3(1 − k)(c·k − Y·k), k = sat(1 − comp·Y). Arranged as c′ = c·A(Y) − B(Y) with A = k(1.3 − .3k), B = .3(1 − k)kY (the same formula,
     regrouped by Y): two luma LUTs (feComponentTransfer table, 33 samples of a quadratic) and two arithmetic composites whose α stays 1 — the earlier form's difference
     terms (c·k − Y·k) had α 0 in Chrome's premultiplied 8-bit buffers (clamped to 0: the chroma term silently vanished) */
  const lut = (fn, n = 33) => Array.from({ length: n }, (_, i) => (+fn(i / (n - 1)).toFixed(5)).toString()).join(" ");
  const tf3 = (name, src, values) => `<feComponentTransfer in="${src}" result="${name}"><feFuncR type="table" tableValues="${values}"/><feFuncG type="table" tableValues="${values}"/><feFuncB type="table" tableValues="${values}"/></feComponentTransfer>`;
  const maxLumaChain = (src, comp, luma) => { const kOf = (Y) => Math.max(0, Math.min(1, 1 - comp * Y)), A = (Y) => { const k = kOf(Y); return k * (1.3 - .3 * k); }, iB4 = (Y) => { const k = kOf(Y); return 1 - 4 * .3 * (1 - k) * k * Y; };   // B ≤ .017 light / .068 dark: stored ×4 (feComponentTransfer truncates to 8 bits — 1 − B would lose a whole unit)
    return comp > 0 && comp < 1 ? `<feColorMatrix in="${src}" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="Y"/>` + tf3("A", "Y", lut(A)) + tf3("iB4", "Y", lut(iB4))
      + `<feComposite in="${src}" in2="A" operator="arithmetic" k1="1" result="cA"/><feComposite in="cA" in2="iB4" operator="arithmetic" k2="1" k3=".25" k4="-.25" result="ml"/>` : `<feComposite in="${src}" in2="${src}" operator="over" result="ml"/>`; };
  /* α reset: BlurFill's arithmetic mixes pass through α .9 and come back to ≈ .992, not 1 (Chrome rounds each premultiplied 8-bit buffer); every later feBlend then adds
     (1 − α)·backdrop (+2/255 on a 128 grey) — un-premultiply and pin α = 1 (feFuncA discrete [1]); inside the panel clip the source is opaque everywhere */
  const alphaOne = (src, name) => `<feComponentTransfer in="${src}" result="${name}"><feFuncA type="discrete" tableValues="1"/></feComponentTransfer>`;
  const ensureFilter = (W, H, th) => { const k = keysFor(th); let svg = document.getElementById("alert-glass-svg"); const sig = W + "x" + H + "/" + th; if (svg && svg.dataset.size === sig) return k; if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "alert-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); } svg.dataset.size = sig;
    const im = images(W, H), base = k.CaptureScale, sigs = [1, 2].map((lv) => VB_STD[lv] / base), M = 120, luma = ".2126 .7152 .0722";
    const bfSig = mixStd(level(k.BlurFillBlurRadius)) / base, bfOff = 0.75 * 8 / base, bleedSig = mixStd(level(k.BleedBlurRadius)) / base, comp = 1 - k.FaceColorMatrixMaxLumaSDR, dk = k.BleedDarkenBlend ? [1, 0] : [-1, 1];
    const d = k.BlurFillDarkenOpacity, l = k.BlurFillLightenOpacity, n = k.BlurFillNormalOpacity;
    const img = (href, name) => `<feImage href="${href}" preserveAspectRatio="none" x="0" y="0" width="${W}" height="${H}" result="${name}" data-alert-img="${name}"/>`;
    const M2 = 300, bleedBlur = Math.min(bleedSig, M2 / 3);   /* f2's region is wider: the bleed's capture average (lod 5.9 ≈ σ 298 pt on a clamp_to_edge capture) is taken over the capture box TILED
       (feTile: the capture box = panel ± 60.2 repeated; the clamp replication itself is not an SVG primitive — 近似) and blurred with σ = min(298, M2/3) so the blur's support stays inside the region
       (edgeMode is not honoured by Chrome's feGaussianBlur: a wider σ blurs in transparency and the bleed target leaks its weight — R57′ debug: black → 82 instead of 32) */
    const head = (id, m = M) => `<filter id="${id}" filterUnits="userSpaceOnUse" x="${-m}" y="${-m}" width="${W + 2 * m}" height="${H + 2 * m}" color-interpolation-filters="sRGB" data-theme="${th}" data-margin="${m}" data-sigma="${sigs.map((v) => v.toFixed(3)).join(",")}" data-base="${base}" data-face="${faceMatrix(k)}" data-map-scale="${im.S}" data-bf-sigma="${bfSig.toFixed(2)}" data-bf-off="${bfOff}" data-bleed-sigma="${bleedSig.toFixed(2)}" data-bleed-blur="${bleedBlur.toFixed(2)}" data-bleed-cm="${bleedMatrix(k)}" data-maxluma-complement="${comp}" data-dimming="${k.Dimming}">`;
    /* f1 (the copy): the dimming under the capture → the three-stage blur as a per-pixel level mix → inner / outer refraction mixed by RefractionOpacity·sat((d + 1)/1) */
    const f1 = head("alert-glass-f1", 220)   /* f1's output must be opaque wherever f2 samples: the bf blur's tail (3σ ≈ 100 pt) beyond the capture box; a narrower f1 left f2 blurring in transparency → a 30-level bright band 60 pt inside the rim (R57′ debug) */
      + `<feFlood flood-color="rgb(0,0,0)" flood-opacity="${k.Dimming}" result="dim"/><feComposite in="dim" in2="SourceGraphic" operator="over" result="src"/>`
      + `<feGaussianBlur in="src" stdDeviation="${sigs[0]}" result="b1"/><feGaussianBlur in="src" stdDeviation="${sigs[1]}" result="b2"/>`
      + img(im.weights, "wimg0") + `<feFlood flood-color="rgb(255,0,0)" result="w0out"/><feComposite in="wimg0" in2="w0out" operator="over" result="wimg"/>` + sel("wimg", 0, "w0") + sel("wimg", 1, "w1") + sel("wimg", 2, "w2")   /* every generated image is made opaque beyond its box (feBlend multiply leaks (1 − α)·source where a weight is half-transparent: a 1-px bright ring at the rim that f2's blurs spread 60 pt inward — R57′ debug); beyond the panel the weights select level 0 (the plain source), so f2's blurs across the rim see the page */
      + img(im.inner, "mapi") + `<feFlood flood-color="rgb(128,128,0)" result="mid"/><feComposite in="mapi" in2="mid" operator="over" result="mapiF"/>` + sel("mapiF", 2, "wr") + invert("wr", "wri")
      + `<feBlend in="src" in2="w0" mode="multiply" result="p0"/><feBlend in="b1" in2="w1" mode="multiply" result="p1"/><feBlend in="b2" in2="w2" mode="multiply" result="p2"/>`
      + `<feComposite in="p0" in2="p1" operator="arithmetic" k2="1" k3="1" result="s01"/><feComposite in="s01" in2="p2" operator="arithmetic" k2="1" k3="1" result="mix"/><feComposite in="mix" in2="src" operator="over" result="blur"/>`   /* outside the panel box the weights image is transparent (the mix vanishes): the plain source there — f2's blurs sample across the rim */
      + img(im.outer, "mapo") + `<feComposite in="mapo" in2="mid" operator="over" result="mapoF"/>`   /* the maps' transparent surround → zero displacement, zero mix weight */
      + `<feDisplacementMap in="blur" in2="mapiF" scale="${im.S}" xChannelSelector="R" yChannelSelector="G" result="c1"/><feDisplacementMap in="blur" in2="mapoF" scale="${im.S}" xChannelSelector="R" yChannelSelector="G" result="c2"/>`
      + `<feBlend in="c1" in2="wri" mode="multiply" result="q1"/><feBlend in="c2" in2="wr" mode="multiply" result="q2"/><feComposite in="q1" in2="q2" operator="arithmetic" k2="1" k3="1" result="c"/>`
      /* BlurFill here (R63′ / menu-card-material §7c): b = the UNREFRACTED dimmed capture at mip lod = log2(BlurFillBlurRadius 8) = 3 (level std 9.581 capture px → σ 38.32 pt), sampled at uv ± .75 mip-3
         texels (8 capture px = 32 pt each → ±24 pt on both axes) and averaged; c′ = D·min(c, b) + L·max(c, b) + (1 − D − L)·c, c″ = mix(c′, b, N) with c = the refracted mix; then α pinned to 1 */
      + `<feGaussianBlur in="src" stdDeviation="${bfSig.toFixed(2)}" result="bfb"/><feOffset in="bfb" dx="${bfOff}" dy="${bfOff}" result="bfp"/><feOffset in="bfb" dx="${-bfOff}" dy="${-bfOff}" result="bfm"/><feComposite in="bfp" in2="bfm" operator="arithmetic" k2=".5" k3=".5" result="bf"/>`
      + `<feBlend in="c" in2="bf" mode="darken" result="mn"/><feBlend in="c" in2="bf" mode="lighten" result="mx"/>`
      + `<feComposite in="mn" in2="mx" operator="arithmetic" k2="${d}" k3="${l}" result="dl"/><feComposite in="dl" in2="c" operator="arithmetic" k2="1" k3="${1 - d - l}" result="bfo"/><feComposite in="bfo" in2="bf" operator="arithmetic" k2="${1 - n}" k3="${n}" result="cbf0"/>` + alphaOne("cbf0", "cbf") + `</filter>`;
    /* f2 (wrapper 2, SourceGraphic = f1's output = the BlurFilled refracted mix): MaxLuma (menu-card-material §7.1 form) → the face matrix with the premultiplied fill → bleed */
    const f2 = head("alert-glass-f2", M2)
      + maxLumaChain("SourceGraphic", comp, luma)
      + `<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/>`
      /* bleed (§4 ⑦): c_b = bleed_cm · capture(uv_b, lod 5.9) — the capture here = this filter's SourceGraphic (the refracted level mix, σ ≤ 18.8, negligible under the bleed's σ 298),
         displaced outward by the bleed map within 60.2 pt of the rim; w = Opacity · w(d) · luma(face)⁴ (DarkenBlend 1) or (1 − luma)⁴ (0, dark); c₃ = mix(face, c_b, w) */
      + img(im.bleed, "mapb") + `<feFlood flood-color="rgb(128,128,0)" result="midb"/><feComposite in="mapb" in2="midb" operator="over" result="mapbF"/>` + sel("mapbF", 2, "wb") + `<feOffset in="SourceGraphic" dx="0" dy="0" x="${-k.CaptureMargin}" y="${-k.CaptureMargin}" width="${W + 2 * k.CaptureMargin}" height="${H + 2 * k.CaptureMargin}" result="cap" data-alert-cap="1"/><feTile in="cap" result="tiled"/><feGaussianBlur in="tiled" stdDeviation="${bleedBlur.toFixed(2)}" result="bb"/>`
      + `<feDisplacementMap in="bb" in2="mapbF" scale="${im.S}" xChannelSelector="R" yChannelSelector="G" result="bd"/><feColorMatrix in="bd" type="matrix" values="${bleedMatrix(k)}" result="cb"/>`
      + `<feColorMatrix in="face" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="lm"/><feComponentTransfer in="lm" result="lx"><feFuncR type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncG type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncB type="linear" slope="${dk[0]}" intercept="${dk[1]}"/></feComponentTransfer>`
      + tf3("w4", "lx", lut((L) => k.BleedOpacity * L ** 4, 65))   /* w = Opacity · L⁴ as one luma LUT (65 samples of the quartic), then × w(d) from the map */
      + `<feBlend in="w4" in2="wb" mode="multiply" result="wbl"/>` + invert("wbl", "wbli")
      + `<feBlend in="face" in2="wbli" mode="multiply" result="o0"/><feBlend in="cb" in2="wbl" mode="multiply" result="o1"/><feComposite in="o0" in2="o1" operator="arithmetic" k2="1" k3="1" result="ob"/></filter>`;
    /* f3 (wrapper 3, SourceGraphic = the bleed output): the highlight layer's two stages through the vibrant matrix */
    const f3 = head("alert-glass-f3")
      + img(im.hl, "hl0") + img(im.hl2, "hl20") + `<feFlood flood-color="rgb(0,0,0)" result="blk3"/><feComposite in="hl0" in2="blk3" operator="over" result="hl"/><feComposite in="hl20" in2="blk3" operator="over" result="hl2"/>`
      + `<feColorMatrix in="SourceGraphic" type="matrix" values="${HL.vibrant.join(" ")} 0 0 0 1 0" result="vib"/>` + invert("hl", "hli")
      + `<feBlend in="SourceGraphic" in2="hli" mode="multiply" result="f0"/><feBlend in="vib" in2="hl" mode="multiply" result="f1"/><feComposite in="f0" in2="f1" operator="arithmetic" k2="1" k3="1" result="o1h"/>`
      + `<feColorMatrix in="o1h" type="matrix" values="${HL.vibrant.join(" ")} 0 0 0 1 0" result="vib2"/>` + invert("hl2", "hl2i")
      + `<feBlend in="o1h" in2="hl2i" mode="multiply" result="g0"/><feBlend in="vib2" in2="hl2" mode="multiply" result="g1"/><feComposite in="g0" in2="g1" operator="arithmetic" k2="1" k3="1" result="out"/></filter>`;
    svg.innerHTML = f1 + f2 + f3; return k; };
  const glass = { layer: null, copy: null, w2: null, w3: null, theme: null };
  const place = () => { if (!glass.copy || !dlg.open) return; const dr = dlg.getBoundingClientRect(), mr = document.getElementById("app").getBoundingClientRect(); const M = 120, W = dlg.offsetWidth, H = dlg.offsetHeight;
    /* the panel's box in the copy's coordinates (the copy = #app's pixels): the dialog's untransformed box from its rect centre and layout size (the appear animation scales it about the centre); the pane is the dialog box oversized by 60 */
    const pl = dr.left + dr.width / 2 - W / 2, pt = dr.top + dr.height / 2 - H / 2; const px = pl - mr.left, py = pt - mr.top; glass.w3.style.transform = `translate(${mr.left - (pl - 60)}px, ${mr.top - (pt - 60)}px)`;
    for (const id of ["alert-glass-f1", "alert-glass-f2", "alert-glass-f3"]) { const f = document.getElementById(id); if (!f) continue; const m = +f.dataset.margin || M; f.setAttribute("x", String(px - m)); f.setAttribute("y", String(py - m)); for (const im of f.querySelectorAll("feImage")) { im.setAttribute("x", String(px)); im.setAttribute("y", String(py)); }
      /* the capture box (panel ± CaptureMargin), clamped to the copy's own box: the copy has no pixels beyond #app (native clamp_to_edge would replicate the edge column; the clamped box's mean drops that strip instead) */
      const cap = f.querySelector("[data-alert-cap]"); if (cap) { const cw = glass.copy.offsetWidth, ch = glass.copy.offsetHeight, cm = KEYS.CaptureMargin, x0 = Math.max(0, px - cm), y0 = Math.max(0, py - cm), x1 = Math.min(cw, px + W + cm), y1 = Math.min(ch, py + H + cm); cap.setAttribute("x", String(x0)); cap.setAttribute("y", String(y0)); cap.setAttribute("width", String(Math.max(1, x1 - x0))); cap.setAttribute("height", String(Math.max(1, y1 - y0))); } } };
  const build = () => { const th = theme(); const main = document.getElementById("app"), pane = dlg.querySelector(".pane"); if (!main || !pane) return; strip(); ensureFilter(dlg.offsetWidth, dlg.offsetHeight, th);
    const layer = document.createElement("div"); layer.className = "alert-glass"; const copy = main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, script, .menu, .menu-scrim, dialog").forEach((e) => e.remove());
    copy.className = "alert-glass-copy"; copy.setAttribute("aria-hidden", "true"); copy.inert = true; const mr = main.getBoundingClientRect(); copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;min-height:${Math.max(mr.height, innerHeight + 200)}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};filter:url(#alert-glass-f1)`;   // the page colour under #app (body's background; #app paints none): without it the copy's gaps are transparent and the live page shows through the glass
    /* three nested filtered elements (f1 on the copy, f2 / f3 on the wrappers): Blink evaluates a filter graph as a tree, one long chain wedged Chrome (R63) */
    const w2 = document.createElement("div"), w3 = document.createElement("div"); w2.className = "alert-glass-w2"; w3.className = "alert-glass-w3"; w2.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none;filter:url(#alert-glass-f2)"; w3.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none;filter:url(#alert-glass-f3)";
    w2.appendChild(copy); w3.appendChild(w2); layer.appendChild(w3); pane.appendChild(layer); glass.layer = layer; glass.copy = copy; glass.w2 = w2; glass.w3 = w3; glass.theme = th; dlg.classList.add("glass-read"); dlg.classList.toggle("glass-dark", th === "dark"); place(); };
  const strip = () => { if (glass.layer) glass.layer.remove(); glass.layer = glass.copy = glass.w2 = glass.w3 = null; };
  /* the dialog's open state: showModal() has no event — watch the `open` attribute */
  new MutationObserver(() => { if (dlg.open) build(); else strip(); }).observe(dlg, { attributes: true, attributeFilter: ["open"] });
  addEventListener("resize", place); addEventListener("scroll", place, { passive: true });
  window.AlertGlass = { keys: KEYS, keysFor, dark: DARK, highlight: HL, unbuilt: UNBUILT, images, faceMatrix, bleedMatrix, sdf, level, mixStd, theme, rebuild: build, get layer() { return glass.layer; }, VB_STD };
})();
