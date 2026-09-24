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
         spread 1.5344) through the dumped vibrant matrix; the soft shadow: drop-shadow 0 8 σ 16.9706 (= R 24 / √2, menu-card-material §7.3b) α .3 × ShadowOpacity (.4 / .6).
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
    SDRGradientDistance0: 0, SDRGradientDistance1: 0, MaxHeadroom: 9999, CaptureScale: 0.25, CaptureMargin: 60.2, Panel: [320, 172], CornerRadius: 34, Dimming: 0.2, GradientOvalization: 0.5 };   // GradientOvalization .5: 数据 R85 materials[62].gradientOvalization (alert-native-formula §4 ⑨: the gradient only, not d)   // Dimming: UIDimmingView black α .2 light / .48 dark (§0; --ios-alert-dimming)
  const DARK = { FaceColorMatrixWhite: 1.125, FaceColorMatrixBlack: 0.125, FaceColorMatrixSaturation: 1.3, FaceColorMatrixFillColor: [0, 0, 0, 0], FaceColorMatrixMaxLuma: 0.35, FaceColorMatrixMaxLumaSDR: 0.35, Clamp: 1.3083,
    KeyFillHighlightSpread: 1.309, KeyFillHighlightSpreadSDR: 1.309, ShadowOpacity: 0.6, BleedColorMatrixWhite: 0.5, BleedColorMatrixBlack: 0.125, BleedColorMatrixSaturation: 1, BleedDarkenBlend: 0, BleedOpacity: 0.8,
    BlurFillLightenOpacity: 0, BlurFillDarkenOpacity: 0.9, Dimming: 0.48 };
  const keysFor = (th) => ({ ...LIGHT, ...(th === "dark" ? DARK : {}) });
  const KEYS = LIGHT;
  const HL = { curvature: 0.75, keyHeight: 1, keySpread: 1.5344, keyAngle: 0, fillAngle: Math.PI, keyAmount: 0.5, fillAmount: 0.5, diffuseAmountScale: 0.15, diffuseHeightScale: 8, diffuseSpreadScale: 0.65,
    vibrant: [1.1202, -0.1894, -0.019, 0, 0.1471, -0.0563, 0.9871, -0.0191, 0, 0.1471, -0.0563, -0.1893, 1.1574, 0, 0.1471] };
  const VB_STD = [0, 2.147, 4.694, 9.581, 19.263, 38.579, 77.023];   // the pyramid levels' stds in capture px (tools/vb_kernel.py, nav-bar-scroll-formula §3.4b)
  const mixStd = (L) => { const k0 = Math.min(Math.floor(L), VB_STD.length - 2), f = L - k0; return Math.sqrt((1 - f) * VB_STD[k0] ** 2 + f * VB_STD[k0 + 1] ** 2); };
  const UNBUILT = { Clamp: "no-op on 8-bit values (limit ≥ 1)", StrokeAtRest: "the KeyFill stroke (R57″) is placed once the appear animation has settled (.settled), not during the .4 s scale-in (the copy inside a scaling dialog would misalign) — 记录", BlurDistancePrime: "d′ = refraction + d: the blur level is taken at d (待读: which refraction term)",
BleedEdge: "近似: the capture box (panel ± 60.2, clamped to the copy) is TILED and blurred σ 100 for its mean — the native sampler's clamp_to_edge replicates the edge column instead; equal on a flat page", BlurFillTexelPair: "近似: the ±.75 mip-3 texel pair is taken on both axes (uv ± off with off = lod·(.25/size) read as a float2, menu-card-material §7c); one-axis or the base-texel reading (±3 pt) would differ only on structured content" };
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
  /* R57⁗ (§4 ⑨, R83 / R85): gradientOvalization o mixes the shape's normal with the inscribed ellipse's radial direction g_oval = normalize((x, (hw/hh)·y)) — g = normalize(mix(g_shape, g_oval, o)), d untouched;
     it turns the refraction / bleed displacement directions and the KeyFill / highlight n·dir towards the centre along the long edges (x = ±120 on the 320-wide panel: 18°) */
  const gOval = (x, y, hw, hh, gx, gy, o) => { if (!(o > 0)) return [gx, gy]; const rx = x, ry = (hw / hh) * y, rn = Math.hypot(rx, ry) || 1; const mx = gx + (rx / rn - gx) * o, my = gy + (ry / rn - gy) * o, mn = Math.hypot(mx, my) || 1; return [mx / mn, my / mn]; };
  const Dc = (t) => 1 - Math.sqrt(Math.max(0, 2 * t - t * t));   // 1 − P at curvature 1 (formula §1 / §3: the refraction's (1 − sqrt(t(2 − t))))
  const level = (r) => Math.max(0, r >= 2 ? Math.log2(r) : Math.log2(1 + r / 2));
  const band = (e, h, cosS, bias, curv, ndir, fw) => { const t = sat(e / h); const prof = (t < 1 ? 1 : 0) * (1 - curv) + (1 - t) * curv; const aa = sat(e / fw + 0.5) * sat((h - e) / fw + 0.5);
    const ang = sat((ndir - cosS) / (1 - cosS)); const vv = e < -5 ? 0 : prof * aa * ang; return vv / (1 + bias * (1 - vv)); };
  const PX = 2;   // px per pt of the generated images
  /* the six maps' bytes as a pure function of (W, H, the keys): run on the main thread by images(), or — its source text, with the helpers it calls — in the
     map worker (imagesAsync), the same code on the same engine, so the same bytes. 界面 09-23: an alert of a size not cached built them inside the open
     (R57‴'s 0 ms task after the first frame): 86–97 ms of main thread on simulator B (224 on the first call), the open's rAF gap 71–96 ms (4 / 4 cold opens,
     warm 38–42) — every new message length is a new size. */
  const mapPixels = (W, H, KEYS, HL) => { const hw = W / 2, hh = H / 2, r = KEYS.CornerRadius, w = Math.round(W * PX), h = Math.round(H * PX);   // the maps use keys shared by both themes (refraction, bleed geometry)
    const n = w * h * 4, iw = new Uint8ClampedArray(n), iin = new Uint8ClampedArray(n), iout = new Uint8ClampedArray(n), ihl = new Uint8ClampedArray(n), ihl2 = new Uint8ClampedArray(n), ibl = new Uint8ClampedArray(n);
    const S = 128;   // the maps' displacement scale (pt at byte 255 − 128)
    let hlInset = 0;   // the deepest highlight pixel (hl or hl2 byte > 0), as its distance from the nearer bbox edge — f3 computes only the rim strips that deep (+1 pt)
    const cosK = Math.cos(HL.keySpread), cosD = Math.cos(HL.diffuseSpreadScale * HL.keySpread), biasD = 1 / (HL.diffuseAmountScale * HL.keyAmount) - 2, hD = HL.diffuseHeightScale * HL.keyHeight, fw = 1 / 3;
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const x = (i + 0.5) / PX - hw, y = (j + 0.5) / PX - hh; const [d, gsx, gsy] = sdf(x, y, hw, hh, r); const [gx, gy] = gOval(x, y, hw, hh, gsx, gsy, KEYS.GradientOvalization); const o = (j * w + i) * 4;   // R57⁗: the ovalized gradient drives the directions below
      /* the blur level weights */
      const s1 = sat((d - KEYS.BlurDistance0) / (KEYS.BlurDistance1 - KEYS.BlurDistance0)), s2 = sat((d - KEYS.BlurDistance1) / (KEYS.BlurDistance2 - KEYS.BlurDistance1));
      const rr = KEYS.BlurRadius * (KEYS.BlurOpacity0 - KEYS.BlurOpacity1 * s1 - KEYS.BlurOpacity2 * s2); const L = d > 0 ? 0 : level(Math.max(0, rr));
      for (let k = 0; k < 3; k++) iw[o + k] = Math.round(255 * Math.max(0, 1 - Math.abs(L - k)));
      iw[o + 3] = 255; const wr = Math.round(255 * KEYS.RefractionOpacity * sat((d - KEYS.RefractionDistance0) / (KEYS.RefractionDistance1 - KEYS.RefractionDistance0)));   // the outer-refraction mix weight (kept in the inner map's B: a PNG's alpha would premultiply the weights)
      /* the two refraction maps: D = amount·Dc(t)·g (formula §3 uv1 / uv2), encoded 128 + D·255/S */
      const ti = sat(-d / KEYS.InnerRefractionHeight), to = sat(-d / KEYS.OuterRefractionHeight);
      const di = KEYS.InnerRefractionAmount * Dc(ti), dout = KEYS.OuterRefractionAmount * Dc(to);
      iin[o] = Math.round(128 + di * gx * 255 / S); iin[o + 1] = Math.round(128 + di * gy * 255 / S); iin[o + 2] = wr; iin[o + 3] = 255;
      iout[o] = Math.round(128 + dout * gx * 255 / S); iout[o + 1] = Math.round(128 + dout * gy * 255 / S); iout[o + 2] = 0; iout[o + 3] = 255;
      /* the bleed map (§4 ⑦ / §3 e): offset 60.2·(1 − sqrt(t(2 − t)))·g outward within 60.2 pt of the rim (0 inside → the point itself); B = w(d) = sat((d − 1)/(0 − 1)) */
      const db = KEYS.BleedAmount * Dc(sat(-d / KEYS.BleedHeight)), wb = Math.round(255 * sat((d - KEYS.BleedDistance0) / (KEYS.BleedDistance1 - KEYS.BleedDistance0)));
      ibl[o] = Math.round(128 + db * gx * 255 / S); ibl[o + 1] = Math.round(128 + db * gy * 255 / S); ibl[o + 2] = wb; ibl[o + 3] = 255;
      /* the highlight α (keyfill §2, as lens-webgl.js FS2): key band from the top (dir (0, −1)), fill band from the bottom (dir (0, 1)), each main 1 pt + diffuse 8 pt */
      const e = -d; let a1 = 0, a2 = 0;   // stage 1: the two main bands (key from the top, fill from the bottom) as one α; stage 2: the two diffuse bands (FS2's three sequential mixes)
      if (d <= 0) { for (const dy of [-1, 1]) { const nd = gy * dy; a1 += band(e, HL.keyHeight, cosK, 0, HL.curvature, nd, fw); a2 = 1 - (1 - a2) * (1 - sat(band(e, hD, cosD, biasD, 1, nd, fw))); } }
      if (Math.round(255 * sat(a1)) > 0 || Math.round(255 * sat(a2)) > 0) hlInset = Math.max(hlInset, Math.min(hw - Math.abs(x), hh - Math.abs(y))); ihl[o] = ihl[o + 1] = ihl[o + 2] = Math.round(255 * sat(a1)); ihl[o + 3] = 255; ihl2[o] = ihl2[o + 1] = ihl2[o + 2] = Math.round(255 * sat(a2)); ihl2[o + 3] = 255; }
    return { bufs: [iw, iin, iout, ihl, ihl2, ibl], S, w, h, hlInset }; };
  const MAP_NAMES = ["weights", "inner", "outer", "hl", "hl2", "bleed"];
  const imageCache = {};
  const encodeMaps = (W, H, px) => { const out = { S: px.S, w: px.w, h: px.h, W, H, hlInset: px.hlInset };
    px.bufs.forEach((b, i) => { const c = document.createElement("canvas"); c.width = px.w; c.height = px.h; c.getContext("2d").putImageData(new ImageData(b, px.w, px.h), 0, 0); out[MAP_NAMES[i]] = c.toDataURL("image/png"); }); return out; };
  const images = (W, H) => { const key = W + "x" + H; return imageCache[key] || (imageCache[key] = encodeMaps(W, H, mapPixels(W, H, KEYS, HL))); };
  /* the map worker: mapPixels and its helpers by source text, PNG-encoded there on an OffscreenCanvas (FileReaderSync → data URL) when the worker has one, else the
     bytes come back and are encoded here. A worker that cannot start or fails is recorded (AlertGlass.mapWorker = "main: …", accept row) and that size is
     built on the main thread as before. */
  const mapWorker = { w: null, state: "idle", pending: {}, gen: {} };   // gen: per size, bumped by forget() — a result for an older generation is dropped
  const imagesAsync = (W, H) => { const key = W + "x" + H; if (imageCache[key]) return Promise.resolve(imageCache[key]); if (mapWorker.pending[key]) return mapWorker.pending[key].p;
    const main = (why) => { mapWorker.state = "main: " + why; return Promise.resolve(images(W, H)); };
    if (mapWorker.state.startsWith("main")) return main(mapWorker.state.slice(6));
    try { if (!mapWorker.w) { const src = `const PX = ${PX}, KR = ${KR}; const sat = ${sat}; const poly = ${poly}; const sdf = ${sdf}; const gOval = ${gOval}; const Dc = ${Dc}; const level = ${level}; const band = ${band}; const mapPixels = ${mapPixels};
onmessage = async (e) => { const { key, gen, W, H, KEYS, HL } = e.data; try { const t0 = performance.now(), px = mapPixels(W, H, KEYS, HL), t1 = performance.now(); let urls = null;
  if (typeof OffscreenCanvas === "function" && typeof FileReaderSync === "function") { urls = []; for (const b of px.bufs) { const c = new OffscreenCanvas(px.w, px.h); c.getContext("2d").putImageData(new ImageData(b, px.w, px.h), 0, 0); urls.push(new FileReaderSync().readAsDataURL(await c.convertToBlob({ type: "image/png" }))); } }
  const ms = [Math.round(t1 - t0), Math.round(performance.now() - t1)]; if (urls) postMessage({ key, gen, ms, urls, S: px.S, w: px.w, h: px.h, hlInset: px.hlInset }); else postMessage({ key, gen, ms, bufs: px.bufs, S: px.S, w: px.w, h: px.h, hlInset: px.hlInset }, px.bufs.map((b) => b.buffer)); }
  catch (err) { postMessage({ key, gen, error: String(err && err.message || err) }); } };`;
        mapWorker.w = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" }))); mapWorker.state = "worker";
        mapWorker.w.onmessage = (e) => { const m = e.data, q = mapWorker.pending[m.key]; if (m.ms) mapWorker.ms = m.ms; if (!q || m.gen !== (mapWorker.gen[m.key] || 0)) return; delete mapWorker.pending[m.key];
          if (m.error) { mapWorker.state = "main: " + m.error; q.res(images(q.W, q.H)); return; }
          if (!imageCache[m.key]) { if (m.urls) { const o = { S: m.S, w: m.w, h: m.h, W: q.W, H: q.H, hlInset: m.hlInset }; m.urls.forEach((u, i) => { o[MAP_NAMES[i]] = u; }); imageCache[m.key] = o; mapWorker.encoded = "worker"; }
            else { imageCache[m.key] = encodeMaps(q.W, q.H, m); mapWorker.encoded = "main"; } }
          q.res(imageCache[m.key]); };
        mapWorker.w.onerror = (e) => { mapWorker.state = "main: " + (e.message || "worker error"); for (const k of Object.keys(mapWorker.pending)) { const q = mapWorker.pending[k]; delete mapWorker.pending[k]; q.res(images(q.W, q.H)); } }; } }
    catch (err) { return main(String(err && err.message || err)); }
    const q = { W, H }; q.p = new Promise((res) => { q.res = res; }); mapWorker.pending[key] = q; mapWorker.w.postMessage({ key, gen: mapWorker.gen[key] || 0, W, H, KEYS, HL }); return q.p; };
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
  /* R57‴: the open frame must not pay for images(): 195k pixels × six maps ≈ 52 ms on the first open of a session (the harness's first-frame row: f1 +42 > 40). So an
     open whose maps are not cached builds this LIGHT chain first — the dimming, one blur at the interior level (deep inside r = 5·.8 = 4 → level 2, σ 18.78; the rim's
     sharpening and the refraction / bleed / highlight need the maps), BlurFill, MaxLuma, the face — one url() on the copy, no wrappers filtered; the first frame paints,
     then the map worker (imagesAsync; 界面 09-23 — the earlier 0 ms task after the first frame held the main thread 86–97 ms on simulator B) makes the maps
     and the copy switches to f1 / f2 / f3. The size is remembered in localStorage (ark-alert-size) and pre-warmed (in the worker) after the next load, so a
     repeat session opens on the full chain at once. */
  /* 串3 filter-chain stall (界面-串2 simulator B: rAF one frame per ~1.5 s with the alert open, f1 alone 1.3 s, f2 alone 2.0 s): WebKit renders a CSS filter:url() at
     page().deviceScaleFactor (RenderLayer::ensureLayerFilters) whatever the transforms, and FilterResults caches effect results only up to maxAllowedMemoryCost 100 MB
     (FilterResults.cpp canCacheResult); f1's 760×592 pt region at 3× is ~16 MB per result (image buffer + pixel buffers), so past the first few results every shared input
     is recomputed per consumer (measured by truncating f1 after each primitive: c 492 ms → dl 911 → bfo 1320). The native backdrop under this material is captured at
     CABackdropLayer scale .25 (alert-native-formula.md §0 row 2, KEYS.CaptureScale): so f0 / f1 / f2 run on content laid out at 1 / G with G = dpr / CaptureScale
     (the copy inside is scaled 1 / G, every length of those filters divided by G) and the result is scaled back ×G — the glass background at the capture's own
     resolution. f3 (the highlight, UISDFView at full resolution — row 5) stays unscaled. ?glassres=full keeps G = 1 (instrument). */
  const gres = (k) => (/[?&]glassres=full\b/.test(location.search) ? 1 : (window.devicePixelRatio || 1) / k.CaptureScale);
  const shrink = (f, g) => { f.dataset.gres = String(g); if (g === 1) return; for (const a of ["width", "height"]) f.setAttribute(a, String(+f.getAttribute(a) / g));
    for (const e of f.children) for (const a of ["x", "y", "width", "height", "stdDeviation", "dx", "dy", "scale"]) { if (!e.hasAttribute(a) || (a === "scale" && e.tagName !== "feDisplacementMap")) continue; e.setAttribute(a, String(+e.getAttribute(a) / g)); } };
  const ensureLight = (W, H, th) => { const k = keysFor(th); let svg = document.getElementById("alert-glass-svg0"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "alert-glass-svg0"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const sig = W + "x" + H + "/" + th + "/" + gres(k); if (svg.dataset.size === sig) return; svg.dataset.size = sig;
    const base = k.CaptureScale, sig2 = VB_STD[2] / base, bfSig = mixStd(level(k.BlurFillBlurRadius)) / base, bfOff = 0.75 * 8 / base, comp = 1 - k.FaceColorMatrixMaxLumaSDR, luma = ".2126 .7152 .0722", d = k.BlurFillDarkenOpacity, l = k.BlurFillLightenOpacity, n = k.BlurFillNormalOpacity, M = 120;
    svg.innerHTML = `<filter id="alert-glass-f0" filterUnits="userSpaceOnUse" x="${-M}" y="${-M}" width="${W + 2 * M}" height="${H + 2 * M}" color-interpolation-filters="sRGB" data-theme="${th}" data-margin="${M}" data-sigma="${sig2.toFixed(3)}">`
      + `<feFlood flood-color="rgb(0,0,0)" flood-opacity="${k.Dimming}" result="dim"/><feComposite in="dim" in2="SourceGraphic" operator="over" result="src"/><feGaussianBlur in="src" stdDeviation="${sig2.toFixed(3)}" result="c"/>`
      + `<feGaussianBlur in="src" stdDeviation="${bfSig.toFixed(2)}" result="bfb"/><feOffset in="bfb" dx="${bfOff}" dy="${bfOff}" result="bfp"/><feOffset in="bfb" dx="${-bfOff}" dy="${-bfOff}" result="bfm"/><feComposite in="bfp" in2="bfm" operator="arithmetic" k2=".5" k3=".5" result="bf"/>`
      + `<feBlend in="c" in2="bf" mode="darken" result="mn"/><feBlend in="c" in2="bf" mode="lighten" result="mx"/><feComposite in="mn" in2="mx" operator="arithmetic" k2="${d}" k3="${l}" result="dl"/><feComposite in="dl" in2="c" operator="arithmetic" k2="1" k3="${1 - d - l}" result="bfo"/><feComposite in="bfo" in2="bf" operator="arithmetic" k2="${1 - n}" k3="${n}" result="cbf0"/>` + alphaOne("cbf0", "cbf")
      + maxLumaChain("cbf", comp, luma) + `<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/></filter>`; shrink(svg.firstElementChild, gres(k)); };
  const ensureFilter = (W, H, th) => { const k = keysFor(th); let svg = document.getElementById("alert-glass-svg"); const sig = W + "x" + H + "/" + th + "/" + gres(k); if (svg && svg.dataset.size === sig) return k; if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "alert-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); } svg.dataset.size = sig;
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
    /* f3 (wrapper 3, SourceGraphic = the bleed output): the highlight layer's two stages through the vibrant matrix. Both stages are mix(c, vib(c), α) with α = the
       hl / hl2 maps, which are 0 deeper than im.hlInset from the bbox edge (14.75 pt on every size tried: 320×152 / 172 / 300, 270×200 — the diffuse band's
       8.17 pt from the rim plus the continuous corner's inset) — there the output is SourceGraphic exactly (×1 + 0). So the chain runs only on the four rim
       strips (s = hlInset + 1 pt, the maps' bilinear reach: 2 texels) through primitive subregions, merged over SourceGraphic: the same pixels, 29 % of the
       area on 320×152. Measured (simulator B, 09-23 22:3x, low load): f3 was the costly filter — open with f3 off 31–38 ms frame gaps (= the page without the
       glass), with it 44–60; repainting the open alert: all filters 32–41 ms a frame, f3 alone 23–24, f1 / f2 / f1 + f2 17 (one vsync). */
    const sw = Math.ceil(im.hlInset + 1), strips = sw * 2 < Math.min(W, H) ? [[0, 0, W, sw], [0, H - sw, W, sw], [0, sw, sw, H - 2 * sw], [W - sw, sw, sw, H - 2 * sw]] : [[0, 0, W, H]];
    const sub = (i) => { const [x, y, w, h] = strips[i]; return `x="${x}" y="${y}" width="${w}" height="${h}" data-strip="${x},${y}"`; };
    const f3 = head("alert-glass-f3", 0).replace("<filter ", `<filter data-strips="${strips.length}" data-strip-width="${sw}" `)   // margin 0: f3 is per pixel (images, flood, matrices, blends — no primitive reads a neighbour) and the pane clips the glass to the panel box (clip-path inset(60px round 34px), alert-glass.css:7), so the pixels outside the panel it used to compute (M 120 each side: 560×392 pt vs 320×152 at devicePixelRatio) were never shown
      + img(im.hl, "hl0") + img(im.hl2, "hl20")
      + strips.map((_, i) => { const r = (n) => n + "_" + i, a = sub(i);
        return `<feFlood flood-color="rgb(0,0,0)" ${a} result="${r("blk3")}"/><feComposite in="hl0" in2="${r("blk3")}" operator="over" ${a} result="${r("hl")}"/><feComposite in="hl20" in2="${r("blk3")}" operator="over" ${a} result="${r("hl2")}"/>`
          + `<feColorMatrix in="SourceGraphic" type="matrix" values="${HL.vibrant.join(" ")} 0 0 0 1 0" ${a} result="${r("vib")}"/>` + invert(r("hl"), r("hli")).replace("<feComponentTransfer ", `<feComponentTransfer ${a} `)
          + `<feBlend in="SourceGraphic" in2="${r("hli")}" mode="multiply" ${a} result="${r("f0")}"/><feBlend in="${r("vib")}" in2="${r("hl")}" mode="multiply" ${a} result="${r("f1")}"/><feComposite in="${r("f0")}" in2="${r("f1")}" operator="arithmetic" k2="1" k3="1" ${a} result="${r("o1h")}"/>`
          + `<feColorMatrix in="${r("o1h")}" type="matrix" values="${HL.vibrant.join(" ")} 0 0 0 1 0" ${a} result="${r("vib2")}"/>` + invert(r("hl2"), r("hl2i")).replace("<feComponentTransfer ", `<feComponentTransfer ${a} `)
          + `<feBlend in="${r("o1h")}" in2="${r("hl2i")}" mode="multiply" ${a} result="${r("g0")}"/><feBlend in="${r("vib2")}" in2="${r("hl2")}" mode="multiply" ${a} result="${r("g1")}"/><feComposite in="${r("g0")}" in2="${r("g1")}" operator="arithmetic" k2="1" k3="1" ${a} result="${r("out")}"/>`; }).join("")
      + `<feMerge result="out"><feMergeNode in="SourceGraphic"/>${strips.map((_, i) => `<feMergeNode in="out_${i}"/>`).join("")}</feMerge></filter>`;
    svg.innerHTML = f1 + f2 + f3; for (const id of ["alert-glass-f1", "alert-glass-f2"]) shrink(svg.querySelector("#" + id), gres(k)); return k; };
  /* ---- R57″: the in-shader KeyFill's STROKE mode and the RingShadow, the menu's construction (menu.js R63′; keyfill-highlight.md §2c / §4; keys = the 70-key truths:
     KeyFill Amount .4 / Angle 1.5708 / ColorBias −.3 / EffectOffset −.5333 / Height .5333 / SpreadSDR 1.85 light, 1.309 dark; RingShadow StrokeWidth 4 / Offset 8 /
     BlurRadius 5 / Mask 1 / Opacity .06).
     Stroke: stroke_mode = (Offset < 0) ∧ |Height + Offset| < .001 = 1 → the band lies OUTSIDE the shape (edge − fw/2 … edge + .5333 pt), k per pixel = Σ_{key, fill}
     v·ang / (1 + a(1 − v·ang)), v = (1 − cov)·sat(e/fw + .5), e = h − d, ang = sat((±n·dir − S)/(1 − S)), S = cos(SpreadSDR), dir = (1, 0), a = 1/Amount − 2; colour
     B″ = mix(B, min(face(B), B), k)·(1 + ColorBias·k·(3 − 2B″)) with B = the DIMMED page under the pixel (the capture sits on the UIDimmingView) — the pane clips
     to the panel (clip-path) and the dialog clipped its overflow, so the stroke is its own layer inside the dialog (dialog#alert.glass-read gets overflow: visible
     in alert-glass.css): a second copy of #app clipped to the ring by clip-path, through #alert-stroke-f (the k map at devicePixelRatio, the dimming flood, the
     face + MaxLuma chain, darken, the (3x − 2x²) LUT, a k4-safe subtraction). Placed once the appear animation has settled (.settled), removed at close.
     Ring shadow (mask 1 → only inside the shape): the shape shifted RingShadowOffset down, the band StrokeWidth wide just inside it, blurred σ BlurRadius, black at
     Opacity, multiplied onto the glass layer inside the pane (its clip-path is the mask). */
  /* 界面 09-23: the map is built once per size / theme / scale (strokeCache) and pre-warmed at idle with images() — built inside the .settled handler it held the
     main thread 61–97 ms right at the end of the appear animation (simulator B, 09-23 22:30, instrumented buildStroke: strokeFilter 61 / 62 / 63 / 65 / 97 ms,
     the rest ≤ 1; the rAF gap there 79–114 ms). Pixels of the two straight-edge strips (|x| ≤ W/2 − R, |y| ≤ H/2 − 1 and the transpose; R = KR·r) have
     d = |y| − H/2 (resp. |x| − W/2) ≤ −1 exactly (sdf: q ≤ 0 on one axis → d = the other axis's distance), so cov = 1 and k = 0 there — skipped without the sdf. */
  const strokeCache = {};
  const strokeMap = (W, H, r, k, dpr) => { const key = W + "x" + H + "/" + r + "/" + k.KeyFillHighlightSpreadSDR + "/" + dpr; if (strokeCache[key]) return strokeCache[key];
    const E = 3, S = Math.cos(k.KeyFillHighlightSpreadSDR), a = 1 / k.KeyFillHighlightAmount - 2, h = k.KeyFillHighlightHeight, fw = 1 / dpr, dir = [Math.sin(k.KeyFillHighlightAngle), -Math.cos(k.KeyFillHighlightAngle)];
    const w = Math.round((W + 2 * E) * dpr), hh = Math.round((H + 2 * E) * dpr), c = document.createElement("canvas"); c.width = w; c.height = hh; const ctx = c.getContext("2d"), id = ctx.createImageData(w, hh); let kside = 0, ktop = 0;
    const R = KR * r, ix = W / 2 - R, iy = H / 2 - R;
    for (let j = 0; j < hh; j++) for (let i = 0; i < w; i++) { const x = (i + .5) / dpr - E - W / 2, y = (j + .5) / dpr - E - H / 2; const ax = Math.abs(x), ay = Math.abs(y);
      if ((ax <= ix && ay <= H / 2 - 1) || (ay <= iy && ax <= W / 2 - 1)) { const o = (j * w + i) * 4; id.data[o + 3] = 255; continue; }
      const [d, gsx, gsy] = sdf(x, y, W / 2, H / 2, r); const [gx, gy] = gOval(x, y, W / 2, H / 2, gsx, gsy, k.GradientOvalization); const o = (j * w + i) * 4; let kk = 0;   // R57⁗: n·dir on the ovalized normal
      const cov = sat(0.5 - d / fw);
      if (!(d - h >= fw / 2 || cov >= 1)) { const e = h - d, v = (1 - cov) * sat(e / fw + 0.5), nd = gx * dir[0] + gy * dir[1];
        for (const sgn of [1, -1]) { const ang = sat((sgn * nd - S) / (1 - S)), va = v * ang; kk += va / (1 + a * (1 - va)); } kk = Math.min(1, kk); }
      id.data[o] = id.data[o + 1] = id.data[o + 2] = Math.round(255 * kk); id.data[o + 3] = 255;
      if (Math.abs(y) < 0.5 && x < -W / 2 && x > -W / 2 - 1.5 * fw) kside = Math.max(kside, kk); if (Math.abs(x) < 0.5 && y < -H / 2 && y > -H / 2 - 1.5 * fw) ktop = Math.max(ktop, kk); }
    ctx.putImageData(id, 0, 0); return (strokeCache[key] = { href: c.toDataURL("image/png"), E, dpr, kside, ktop }); };
  const warmStroke = (W, H, th = theme()) => { const k = keysFor(th), t0 = performance.now(); strokeMap(W, H, k.CornerRadius, k, Math.min(3, Math.max(1, window.devicePixelRatio || 1))); return performance.now() - t0; };   // the key strokeFilter uses
  const strokeFilter = (th, W, H, r) => { const k = keysFor(th), dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)), m = strokeMap(W, H, r, k, dpr), E = m.E, comp = 1 - k.FaceColorMatrixMaxLumaSDR, luma = ".2126 .7152 .0722", bias = -k.KeyFillHighlightColorBias, qmax = 9 / 8;
    let svg = document.getElementById("alert-stroke-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "alert-stroke-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const mode = k.KeyFillHighlightColorBias < 0 ? "darken" : "lighten";
    /* 界面 09-23: the chain runs only where the ring can show. The layer's clip-path is the ring between the rounded rects at E − h − fw and E + fw / 2 (radii
       r + h + fw / r − fw / 2 about the same centres E + r), so every shown pixel lies in the four corner squares c = E + r + 1 or the four edge bands
       t = E + 1 deep; every primitive is per pixel (floods, the image, matrices, transfers, blends — none reads a neighbour), so each region's pixels are the
       same as the full chain's and the rest is clipped away. 10 % of the 326×158 area. Measured (simulator B, 09-23 23:2x, low load): this filter was the costly
       one at close — the dialog's repaint when alert-out starts re-renders it (rAF gaps 45–49 + 36–43 ms at the close; with its filter off 21–24, with the stroke
       gone ≤ 25); in the GPU process CSSFilterRenderer ~36 ms of ~62 per open / close cycle (sample, 10 cycles: 594 samples, without the stroke 235). */
    const Wf = W + 2 * E, Hf = H + 2 * E, c = Math.ceil(E + r + 1), t = E + 1;
    const rings = 2 * c < Math.min(Wf, Hf) ? [[0, 0, c, c], [Wf - c, 0, c, c], [0, Hf - c, c, c], [Wf - c, Hf - c, c, c], [c, 0, Wf - 2 * c, t], [c, Hf - t, Wf - 2 * c, t], [0, c, t, Hf - 2 * c], [Wf - t, c, t, Hf - 2 * c]] : [[0, 0, Wf, Hf]];
    const ring = (i, chain) => { const [x, y, w, h] = rings[i]; return chain.replace(/\b(in2?|result)="(\w+)"/g, (a, n, v) => (v === "SourceGraphic" || v === "k0" ? a : `${n}="${v}_${i}"`))
      .replace(/<(fe(?!Func|MergeNode)\w+) /g, (a) => `${a}x="${x - E}" y="${y - E}" width="${w}" height="${h}" data-strip="${x},${y}" `); };
    svg.innerHTML = `<filter id="alert-stroke-f" data-rings="${rings.length}" filterUnits="userSpaceOnUse" x="${-E}" y="${-E}" width="${W + 2 * E}" height="${H + 2 * E}" color-interpolation-filters="sRGB" data-theme="${th}" data-e="${E}" data-dpr="${dpr}" data-kside="${m.kside.toFixed(3)}" data-ktop="${m.ktop.toFixed(3)}" data-s="${Math.cos(k.KeyFillHighlightSpreadSDR).toFixed(4)}" data-bias="${bias}" data-dimming="${k.Dimming}">`
      + `<feImage href="${m.href}" preserveAspectRatio="none" x="${-E}" y="${-E}" width="${W + 2 * E}" height="${H + 2 * E}" result="k0" data-stroke-img="1"/>` + rings.map((_, i) => ring(i, `<feFlood flood-color="rgb(0,0,0)" flood-opacity="${k.Dimming}" result="dim"/><feComposite in="dim" in2="SourceGraphic" operator="over" result="src"/>`
      + `<feFlood flood-color="rgb(0,0,0)" result="blk"/><feComposite in="k0" in2="blk" operator="over" result="kk"/>` + invert("kk", "kki")
      + maxLumaChain("src", comp, luma) + `<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/><feBlend in="src" in2="face" mode="${mode}" result="bmin"/>`
      + `<feBlend in="src" in2="kki" mode="multiply" result="t1"/><feBlend in="bmin" in2="kk" mode="multiply" result="t2"/><feComposite in="t1" in2="t2" operator="arithmetic" k2="1" k3="1" result="bmix"/>`
      + tf3("qh", "bmix", lut((x) => (3 * x - 2 * x * x) / qmax)) + `<feBlend in="qh" in2="kk" mode="multiply" result="t"/>` + invert("t", "ti")
      + `<feComposite in="bmix" in2="ti" operator="arithmetic" k2="1" k3="${(bias * qmax).toFixed(5)}" k4="${(-bias * qmax).toFixed(5)}" result="out"/>`)).join("")
      + `<feMerge result="out">${rings.map((_, i) => `<feMergeNode in="out_${i}"/>`).join("")}</feMerge></filter>`;
    return { E, dpr, map: m }; };
  const roundRect = (x, y, w, h, r) => { const q = Math.max(0, Math.min(r, w / 2, h / 2)); return `M${x + q} ${y}H${x + w - q}A${q} ${q} 0 0 1 ${x + w} ${y + q}V${y + h - q}A${q} ${q} 0 0 1 ${x + w - q} ${y + h}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + h - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
  const buildStroke = () => { if (!glass.copy || !dlg.open || glass.stroke) return; const t0 = performance.now(), main = document.getElementById("app"); if (!main) return; const th = glass.theme, k = keysFor(th), W = dlg.offsetWidth, H = dlg.offsetHeight, r = k.CornerRadius, f = strokeFilter(th, W, H, r), E = f.E, fw = 1 / f.dpr, h = k.KeyFillHighlightHeight;
    const dr = dlg.getBoundingClientRect(), mr = main.getBoundingClientRect(), pl = dr.left + dr.width / 2 - W / 2, pt = dr.top + dr.height / 2 - H / 2;   // the untransformed panel box (the appear animation scales about the centre; at .settled it is 1)
    const el = glass.strokeHost || document.createElement("div"); el.classList.add("alert-stroke"); el.setAttribute("aria-hidden", "true");
    el.style.cssText = `position:absolute;left:${-E}px;top:${-E}px;width:${W + 2 * E}px;height:${H + 2 * E}px;overflow:hidden;pointer-events:none;z-index:-3;clip-path:path(evenodd, "${roundRect(E - h - fw, E - h - fw, W + 2 * (h + fw), H + 2 * (h + fw), r + h + fw)} ${roundRect(E + fw / 2, E + fw / 2, W - fw, H - fw, Math.max(0, r - fw / 2))}")`;
    const copy = main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, .menu-stroke, dialog").forEach((e) => e.remove()); copy.className = "alert-stroke-copy"; copy.inert = true;
    copy.style.cssText = `position:absolute;left:${mr.left - (pl - E)}px;top:${mr.top - (pt - E)}px;width:${mr.width}px;min-height:${Math.max(mr.height, innerHeight + 200)}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};filter:url(#alert-stroke-f)`;
    const fx = document.getElementById("alert-stroke-f"), px = pl - mr.left, py = pt - mr.top; fx.setAttribute("x", String(px - E)); fx.setAttribute("y", String(py - E)); const im = fx.querySelector("feImage"); im.setAttribute("x", String(px - E)); im.setAttribute("y", String(py - E));
    for (const e of fx.querySelectorAll("[data-strip]")) { const [sx, sy] = e.dataset.strip.split(",").map(Number); e.setAttribute("x", String(px - E + sx)); e.setAttribute("y", String(py - E + sy)); }   // the ring regions
    el.appendChild(copy); if (!el.parentNode) dlg.insertBefore(el, dlg.firstChild); glass.stroke = el; glass.strokeMs = performance.now() - t0; };   // strokeMs: the .settled handler's own main-thread time (accept-alert)
  const ringPath = (w, h, r, off, sw) => roundRect(0, off, w, h, r) + " " + roundRect(sw, off + sw, w - 2 * sw, h - 2 * sw, Math.max(0, r - sw));   // the shape shifted down `off`, minus the same shape inset by the stroke width (evenodd = the band just inside the shifted outline)
  const F12 = "url(#alert-glass-f1) url(#alert-glass-f2)";   // f1 then f2 on the one element (see place())
  const glass = { layer: null, copy: null, page: null, w2: null, w3: null, up: null, g: 1, theme: null, stroke: null, strokeHost: null, ring: null, ringImg: null, light: false, warmedAt: 0 };
  const place = () => { if (!glass.copy || !dlg.open) return; const dr = dlg.getBoundingClientRect(), mr = document.getElementById("app").getBoundingClientRect(); const M = 120, W = dlg.offsetWidth, H = dlg.offsetHeight;
    /* the panel's box in the copy's coordinates (the copy = #app's pixels): the dialog's untransformed box from its rect centre and layout size (the appear animation scales it about the centre); the pane is the dialog box oversized by 60 */
    const pl = dr.left + dr.width / 2 - W / 2, pt = dr.top + dr.height / 2 - H / 2; const px = pl - mr.left, py = pt - mr.top; /* WebKit (simulator D, 09-25, measured two ways: a 40 pt black square in the copy under the panel's centre, and each filter's whole chain swapped for a red
       feFlood): a filter's result lands shifted by its region's origin when that origin is right of / below the filtered element's own origin (f3 at 60 / 164.8:
       square +59.2 / +61.2 pt), and a filtered child (the copy, f1) inside a filtered parent (w2, f2) is drawn from the parent's region origin whatever the
       child's own offset or region (f1 + f2: square +58.7 / +60.3 pt with each alone ±0.4; f1 red through an identity f2 started at f2's top, 80 pt above f1's).
       That was the page 60 pt up-left in the glass (the 「游戏机（演示）」 row, the blue play button). So every filtered element sits on its region's top-left
       and every region is at 0 / 0 (数据 09-25 00:34, the stroke's same rule): the layer on the panel box, w3 (f3) at its origin with f3 = the panel;
       w2 (f2) and the copy (f1 / f0) both at the outer margin's corner, the copy's filter widened to the same box (the red check: f1, f2 and f1 through f2
       all at 80.0 pt = the panel top 380.3 − 300); maps, strips and the capture box relative to that corner.
       f2 is chained on the copy's own filter list (F12), not on w2: with f1 nested inside f2 the page still landed ≈ +60 / +60 pt in the glass although
       f1 / f2 / f1 through an identity f2 all read 0 — only f2's last step (the arithmetic sum of the face and the capture-bleed branch) moved it, and moving
       the layer or the pane did not move it on screen (simulator D 09-25 01:4x, a magenta 60-pt marker in the copy: nested 110 +55.0 / +45.2 clipped at the
       rim, chained +0.1 / +2.1, chained + f3 +0.3 / +2.0; f1 alone +0.3 / +3.0 is its refraction) */
    const f2on = /alert-glass-f2/.test(glass.copy.style.filter), fc = document.getElementById(/alert-glass-f0/.test(glass.copy.style.filter) ? "alert-glass-f0" : "alert-glass-f1"), f2 = document.getElementById("alert-glass-f2");
    const mo = f2on && f2 ? +f2.dataset.margin : fc ? +fc.dataset.margin : M, g = glass.g, ox = px - mo, oy = py - mo;   // the outer box's corner in page units (#app's)
    glass.up.style.transform = `translate(${-mo}px, ${-mo}px) scale(${g})`; glass.page.style.left = `${-ox / g}px`; glass.page.style.top = `${-oy / g}px`;
    glass.copy.style.width = `${(W + 2 * mo) / g}px`; glass.copy.style.height = `${(H + 2 * mo) / g}px`;
    for (const id of ["alert-glass-f0", "alert-glass-f1", "alert-glass-f2", "alert-glass-f3"]) { const f = document.getElementById(id); if (!f) continue; const inW3 = id === "alert-glass-f3", fg = +f.dataset.gres || 1, q = inW3 ? 0 : mo;   // q: the panel's corner from the element's origin, page units
      f.setAttribute("x", "0"); f.setAttribute("y", "0"); if (!inW3) { f.setAttribute("width", String((W + 2 * mo) / fg)); f.setAttribute("height", String((H + 2 * mo) / fg)); }
      for (const im of f.querySelectorAll("feImage")) { im.setAttribute("x", String(q / fg)); im.setAttribute("y", String(q / fg)); }
      for (const e of f.querySelectorAll("[data-strip]")) { const [sx, sy] = e.dataset.strip.split(",").map(Number); e.setAttribute("x", String((q + sx) / fg)); e.setAttribute("y", String((q + sy) / fg)); }   // f3's rim strips
      /* the capture box (panel ± CaptureMargin), clamped to the copy's own box: the copy has no pixels beyond #app (native clamp_to_edge would replicate the edge column; the clamped box's mean drops that strip instead) */
      const cap = f.querySelector("[data-alert-cap]"); if (cap) { const cw = glass.page.offsetWidth, ch = glass.page.offsetHeight, cm = KEYS.CaptureMargin, x0 = Math.max(0, px - cm), y0 = Math.max(0, py - cm), x1 = Math.min(cw, px + W + cm), y1 = Math.min(ch, py + H + cm); cap.setAttribute("x", String((x0 - ox) / fg)); cap.setAttribute("y", String((y0 - oy) / fg)); cap.setAttribute("width", String(Math.max(1, x1 - x0) / fg)); cap.setAttribute("height", String(Math.max(1, y1 - y0) / fg)); } } };
  const refilter = (copy) => requestAnimationFrame(() => requestAnimationFrame(() => { if (glass.copy !== copy) return; for (const id of ["alert-glass-f0", "alert-glass-f1", "alert-glass-f2", "alert-glass-f3"]) { const f = document.getElementById(id); if (f) f.setAttribute("x", f.getAttribute("x") || "0"); } }));
  const build = () => { const th = theme(); const main = document.getElementById("app"), pane = dlg.querySelector(".pane"); if (!main || !pane) return; strip(); const W = dlg.offsetWidth, H = dlg.offsetHeight, warm = !!imageCache[W + "x" + H];
    if (warm) ensureFilter(W, H, th); else ensureLight(W, H, th);   // R57‴
    try { localStorage.setItem("ark-alert-size", W + "x" + H); } catch (e) {}
    const layer = document.createElement("div"); layer.className = "alert-glass"; layer.style.cssText = `left:60px;top:60px;right:auto;bottom:auto;width:${dlg.offsetWidth}px;height:${dlg.offsetHeight}px`;   /* on the panel box (the pane is it ± 60): see place() */ const page = main.cloneNode(true); page.removeAttribute("id"); page.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); page.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, dialog").forEach((e) => e.remove());
    const g = gres(keysFor(th)), mr = main.getBoundingClientRect(), ph = Math.max(mr.height, innerHeight + 200);
    page.className = "alert-glass-page"; page.setAttribute("aria-hidden", "true"); page.inert = true; page.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;min-height:${ph}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};transform:scale(${1 / g});transform-origin:0 0`;
    const copy = document.createElement("div"); copy.className = "alert-glass-copy"; copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width / g}px;height:${ph / g}px;pointer-events:none;filter:${warm ? F12 : "url(#alert-glass-f0)"}`; copy.appendChild(page);   // the page colour under #app (body's background; #app paints none): without it the copy's gaps are transparent and the live page shows through the glass
    /* three nested filtered elements (f1 on the copy, f2 / f3 on the wrappers): Blink evaluates a filter graph as a tree, one long chain wedged Chrome (R63) */
    const w2 = document.createElement("div"), w3 = document.createElement("div"); w2.className = "alert-glass-w2"; w3.className = "alert-glass-w3"; w2.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none;"; w3.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none;transform:translate(0px, 0px);" +   /* the identity transform stays: without one WebKit drew nothing of f3 (simulator D 09-25 00:4x, the marker test in place()) */
      (warm ? "filter:url(#alert-glass-f3)" : "");
    const up = document.createElement("div"); up.className = "alert-glass-up"; up.style.cssText = `position:absolute;left:0;top:0;width:100%;pointer-events:none;transform:scale(${g});transform-origin:0 0`;   // the glass background back to page units (see gres)
    w2.appendChild(copy); up.appendChild(w2); w3.appendChild(up); layer.appendChild(w3);
    /* R57″ ring shadow (keyfill §4, RingShadow keys; mask 1 = the pane's clip-path): the band of the shape shifted 8 down, 4 wide inside it, σ 5, black .06, multiplied */
    { const k = keysFor(th), W = dlg.offsetWidth, H = dlg.offsetHeight; let rsvg = document.getElementById("alert-ring-svg"); if (!rsvg) { rsvg = document.createElementNS(NS, "svg"); rsvg.id = "alert-ring-svg"; rsvg.setAttribute("width", "0"); rsvg.setAttribute("height", "0"); rsvg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(rsvg); }
      rsvg.innerHTML = `<filter id="alert-glass-ring" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="${k.RingShadowBlurRadius}"/></filter>`;
      const ring = document.createElementNS(NS, "svg"); ring.setAttribute("class", "alert-glass-ring"); ring.setAttribute("viewBox", `0 0 ${W} ${H}`); ring.style.cssText = `position:absolute;left:0;top:0;width:${W}px;height:${H}px;mix-blend-mode:multiply;pointer-events:none;overflow:visible`;
      const path = document.createElementNS(NS, "path"); path.setAttribute("fill", "#000"); path.setAttribute("fill-rule", "evenodd"); path.setAttribute("fill-opacity", String(k.RingShadowOpacity)); path.setAttribute("filter", "url(#alert-glass-ring)"); path.setAttribute("d", ringPath(W, H, k.CornerRadius, k.RingShadowOffset, k.RingShadowStrokeWidth)); path.dataset.ring = `${k.RingShadowOffset}/${k.RingShadowStrokeWidth}/${k.RingShadowBlurRadius}/${k.RingShadowOpacity}`; ring.appendChild(path); layer.appendChild(ring); glass.ring = ring;
      /* the ring as a bitmap made at idle from this same SVG (ringBitmap below): drawn from the SVG, its σ 5 blur ran anew in the first frame of every open —
         10–13 ms of the open's second frame (simulator B, 09-24 00:4x, 10 alternating opens each: second frame 45 → 32 with the ring off, blur off 32, blend
         mode normal 40 = on); the bitmap in its place: the panel ± 30 pt of the screenshot 0 pixels different, second frame 47 → 40 */
      const bm = ringCache[ringSig(W, H, th)]; if (bm && bm.img) { const im = bm.img.cloneNode(); im.className = "alert-glass-ring-img"; im.setAttribute("aria-hidden", "true"); im.dataset.ring = path.dataset.ring;
        im.style.cssText = `position:absolute;left:${-RING_M}px;top:${-RING_M}px;width:${bm.vw}px;height:${bm.vh}px;mix-blend-mode:multiply;pointer-events:none`; ring.style.display = "none"; layer.insertBefore(im, ring); glass.ringImg = im; }
      else ringBitmap(W, H, th); }
    /* The stroke's own composited layer, in place from the open (alert-glass.css .alert-stroke-host): as part of the dialog's backing the stroke copy's filter
       re-ran on every repaint of anything over the panel — a button's press / focus, a text change, the start of alert-out at close — one 26–49 ms frame each
       (simulator B, 09-23 23:3x: the cancel button's colour changed with the alert open 32 / 33 ms, with the stroke on its own layer 17–19; the screen
       pixel-identical). Created at the open with the panel's box so the layer tree has its final shape from the first frame: added at .settled, the new layer
       re-laid the dialog's layers and repainted the glass (29–31 ms at .settled). The copy goes in at .settled (buildStroke). */
    const host = document.createElement("div"); host.className = "alert-stroke-host"; host.setAttribute("aria-hidden", "true");
    host.style.cssText = `position:absolute;left:-3px;top:-3px;width:${W + 6}px;height:${H + 6}px;pointer-events:none;z-index:-3`; dlg.insertBefore(host, dlg.firstChild); glass.strokeHost = host;
    pane.appendChild(layer); glass.layer = layer; glass.copy = copy; glass.page = page; glass.w2 = w2; glass.w3 = w3; glass.up = up; glass.g = g; glass.theme = th; dlg.classList.add("glass-read"); dlg.classList.toggle("glass-dark", th === "dark"); place(); if (dlg.classList.contains("settled")) buildStroke();
    /* WebKit: a new copy pointing at the cached (already built) filters paints as if f1 were absent — the undimmed, unblurred page through f2 / f3, a near-white
       panel (simulator D, 09-24 23:4x, every open of the live page: 253 / 255 / 255 / 224 at four panel points, the native alert 233–238) — until any attribute of the
       filter changes; the same attribute set again two frames after the open re-resolves it (212 / 218 / 231 / 198, three opens out of three) */
    refilter(copy);
    if (!warm) { glass.light = true; imagesAsync(W, H).then(() => { if (glass.copy !== copy || !dlg.open) return; ensureFilter(W, H, th); copy.style.filter = F12; w3.style.filter = "url(#alert-glass-f3)"; glass.light = false; glass.warmedAt = performance.now(); place(); refilter(copy); }); } };   // R57‴: the full chain once the maps are made — in the map worker (界面 09-23), the light chain meanwhile
  /* ringBitmap: the ring's SVG (the same path, fill and #alert-glass-ring filter as build) as an image at devicePixelRatio, drawn into a canvas once (WebKit
     rasterizes it with the same filter code as the page), kept as a decoded PNG per size / theme / scale; build uses it from the next open, warmUp at idle */
  const RING_M = 40, ringCache = {}, ringSig = (W, H, th) => `${W}x${H}/${th}/${window.devicePixelRatio || 1}`;
  const ringBitmap = (W, H, th) => { const sig = ringSig(W, H, th); if (ringCache[sig]) return ringCache[sig].p; const k = keysFor(th), dpr = window.devicePixelRatio || 1, cw = Math.ceil((W + 2 * RING_M) * dpr), ch = Math.ceil((H + 2 * RING_M) * dpr), vw = cw / dpr, vh = ch / dpr;
    const src = `<svg xmlns="${NS}" width="${cw}" height="${ch}" viewBox="${-RING_M} ${-RING_M} ${vw} ${vh}"><filter id="alert-glass-ring" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="${k.RingShadowBlurRadius}"/></filter>`
      + `<path d="${ringPath(W, H, k.CornerRadius, k.RingShadowOffset, k.RingShadowStrokeWidth)}" fill="#000" fill-rule="evenodd" fill-opacity="${k.RingShadowOpacity}" filter="url(#alert-glass-ring)"/></svg>`;
    const e = ringCache[sig] = { img: null, vw, vh }; e.p = (async () => { try { const sv = new Image(); sv.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(src); await sv.decode();
      const c = document.createElement("canvas"); c.width = cw; c.height = ch; c.getContext("2d").drawImage(sv, 0, 0); const blob = await new Promise((r) => c.toBlob(r, "image/png")); if (!blob) throw new Error("toBlob");
      const im = new Image(); im.src = URL.createObjectURL(blob); await im.decode(); e.img = im; } catch (err) { delete ringCache[sig]; } })(); return e.p; };
  const strip = () => { if (glass.layer) glass.layer.remove(); if (glass.stroke) glass.stroke.remove(); if (glass.strokeHost) glass.strokeHost.remove(); glass.layer = glass.copy = glass.page = glass.w2 = glass.w3 = glass.up = glass.stroke = glass.strokeHost = glass.ring = glass.ringImg = null; glass.light = false; };
  /* the dialog's open state: showModal() has no event — watch the `open` attribute */
  new MutationObserver(() => { if (dlg.open) build(); else strip(); }).observe(dlg, { attributes: true, attributeFilter: ["open"] });
  new MutationObserver(() => { if (dlg.open && dlg.classList.contains("settled") && glass.copy && !glass.stroke) buildStroke(); }).observe(dlg, { attributes: true, attributeFilter: ["class"] });   // R57″: the stroke once the appear animation has settled (the dialog's scale is 1 then)
  addEventListener("resize", place); addEventListener("scroll", place, { passive: true });
  /* R57‴ pre-warm: the last opened alert's size (localStorage) has its maps generated at idle after load — a repeat session opens on the full chain in its first frame */
  { const warmUp = () => { try { const sz = localStorage.getItem("ark-alert-size"); if (!sz) return; const [W, H] = sz.split("x").map(Number); if (W > 0 && H > 0 && !imageCache[sz]) imagesAsync(W, H).then(() => { glass.prewarmed = sz; });
        if (W > 0 && H > 0) idle(() => { warmStroke(W, H); glass.strokeWarmed = sz; }); if (W > 0 && H > 0) idle(() => ringBitmap(W, H, theme())); } catch (e) {} };   // the stroke's k map too, in its own idle slot
    const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 3000 }) : setTimeout(fn, 1500)); if (document.readyState === "complete") idle(warmUp); else addEventListener("load", () => idle(warmUp), { once: true }); }
  window.AlertGlass = { forget: (W, H) => { delete imageCache[W + "x" + H]; delete mapWorker.pending[W + "x" + H]; mapWorker.gen[W + "x" + H] = (mapWorker.gen[W + "x" + H] || 0) + 1; const f = document.getElementById("alert-glass-svg"); if (f) delete f.dataset.size; },   // instrument: that size opens cold again (accept-alert first-open check); a worker result still on its way for it is dropped
     keys: KEYS, keysFor, dark: DARK, highlight: HL, unbuilt: UNBUILT, images, faceMatrix, bleedMatrix, sdf, level, mixStd, theme, rebuild: build, get layer() { return glass.layer; }, get light() { return glass.light; }, get warmedAt() { return glass.warmedAt; }, get strokeWarmed() { return glass.strokeWarmed; }, get strokeMs() { return glass.strokeMs; }, get ringImg() { return glass.ringImg; }, ringBitmap, warmStroke, imagesAsync, get mapWorker() { return mapWorker.state + (mapWorker.encoded ? " / png " + mapWorker.encoded : "") + (mapWorker.ms ? " / " + mapWorker.ms.join("+") + " ms" : ""); }, cached: (W, H) => !!imageCache[W + "x" + H], gOval, VB_STD };
})();
