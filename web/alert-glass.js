/* alert-glass.js — the alert panel's glass from the read keys (BOARD R57; material only from decoded formulas and dumped keys, A20).
   Keys: uiprobe-deep-alert-glasskeys.json (the 26 inputs of the UISDFBackdropView 320×172's glassBackground filter, light) + the highlight
   layer (uiprobe-deep-alert-{light,dark}.json: UISDFView 320×172, vibrantColorMatrix 4×5 + CASDFKeyFillHighlightEffect, both themes alike).
   Formulas: alert-native-formula.md §0–§3 (the keys → GlassBackgroundUniforms), glass-displacement-formula.md §3 (glass_background_base),
   keyfill-highlight.md §2 (the highlight bands + vibrantColorMatrix), label-end-tear-closed-vs-map.md §7 ② / §7b (the continuous-corner
   supercircle SDF the shape uses: cornerCurve continuous r 34), nav-bar-scroll-formula.md §3.4b (the mip-level blur: the same lod scheme).
   Built (light), in the shader's order:
     blur  — r(d) = 5·(.8 − .4·s1 − .5·s2), s1 = sat((d + 86)/85), s2 = sat((d + 1)/1) (BlurRadius 5, BlurOpacity .8/.4/.5, BlurDistance −86/−1/0);
             lod L = log2 r (r ≥ 2) / log2(1 + r/2): 2 at the centre → 1 at 1 pt from the rim → 0 at the rim; the pyramid levels as Gaussians of the
             level stds (2.147 / 4.694 capture px, tools/vb_kernel.py) ÷ the capture scale .25 px/pt = 8.59 / 18.78 pt (the alert's measured step
             width 50 pt = σ 19.5 ✓ alert-pipeline-plan §1.3), mixed per pixel by tent weights from a weights image (R/G/B = levels 0/1/2) — the
             same level-mix construction as topbar.js R3″ (剖面近似 per level: ≤ 1.4/255, R3‴);
     refraction — c = mix(c1, c2, .6·sat((d + 11)/8)): c1 = the blur sampled at uv + (−60)·(1 − sqrt(t(2 − t)))·g, t = sat(−d/20) (inner);
             c2 at uv + 43·(…)·g, t = sat(−d/34.4) (outer); RefractionDistance defaults −11 / −3 → two feDisplacementMaps from generated maps and a
             per-pixel mix weight;
     face  — CA::ColorMatrix::set_ycc_composite(white 1.03, black .4, saturation 1 (default), fill transparent (default)): YCC⁻¹·D·YCC (menu.js R1′);
     highlight layer — α(p) = the KeyFill bands (key: height 1 / curvature .75 / spread 1.5344 → cos .0364, angle 0 → from the top; fill: angle π →
             from the bottom; diffuse ×.15 / ×8 / ×.65) through the dumped vibrantColorMatrix (.9118·S(1.29) + .1471): out = mix(c, V·c, α);
     shadow — ShadowAmount 0, Opacity .4, Radius 24, Offset (0, 8): the soft shadow of menu-card-material §7.3 (drop-shadow 0 8 24 α .12; the
             plan's #10 saw none over the dimming — kept as the read says).
   Not built / 不可表达 (recorded in AlertGlass.unbuilt): Bleed (defaults amount 400 / height 500 / opacity .2: the capture's clamp-to-edge colour
   280 pt outside — no clamp-to-edge sampling in SVG; ≤ 6/255 per §3), Clamp 1.0696 (no-op on 8-bit), KeyFill in-shader (height 0 → off),
   RingShadow (stroke 0 → 0), the blur's d′ = refraction + d (d used), the SDF's gradient ovalization (unread → 0), the dark theme's 26 keys
   (not dumped: the dark alert keeps the sampled --ios-alert-glass-filter until read). Without Motion / an #alert dialog nothing is installed. */
(function () {
  const dlg = document.getElementById("alert"); if (!dlg) return;
  const KEYS = { BlurRadius: 5, BlurOpacity0: 0.8, BlurOpacity1: 0.4, BlurOpacity2: 0.5, BlurDistance0: -86, BlurDistance1: -1, BlurDistance2: 0, Clamp: 1.0696,
    FaceColorMatrixWhite: 1.03, FaceColorMatrixBlack: 0.4, FaceColorMatrixSaturation: 1, InnerRefractionAmount: -60, InnerRefractionHeight: 20, OuterRefractionAmount: 43, OuterRefractionHeight: 34.4,
    RefractionOpacity: 0.6, RefractionDistance0: -11, RefractionDistance1: -3, KeyFillHighlightAmount: 0.4, KeyFillHighlightColorBias: -0.3, KeyFillHighlightSpread: 1.6755, KeyFillHighlightSpreadSDR: 1.85, KeyFillHighlightHeight: 0,
    RingShadowOpacity: 0.06, RingShadowStrokeWidth: 0, ShadowAmount: 0, ShadowOffset: [0, 8], ShadowOpacity: 0.4, ShadowRadius: 24, SDRGradientDistance0: 0, SDRGradientDistance1: 0,
    BleedAmount: 400, BleedHeight: 500, BleedOpacity: 0.2, BleedDarkenBlend: 1, CaptureScale: 0.25, CaptureMargin: 60.2, Panel: [320, 172], CornerRadius: 34, Dimming: 0.2 };   // Dimming: UIDimmingView black α .2 light (alert-native-formula §0; --ios-alert-dimming)
  const HL = { curvature: 0.75, keyHeight: 1, keySpread: 1.5344, keyAngle: 0, fillAngle: Math.PI, keyAmount: 0.5, fillAmount: 0.5, diffuseAmountScale: 0.15, diffuseHeightScale: 8, diffuseSpreadScale: 0.65,
    vibrant: [1.1202, -0.1894, -0.019, 0, 0.1471, -0.0563, 0.9871, -0.0191, 0, 0.1471, -0.0563, -0.1893, 1.1574, 0, 0.1471] };
  const VB_STD = [0, 2.147, 4.694, 9.581];   // the pyramid levels' stds in capture px (tools/vb_kernel.py, nav-bar-scroll-formula §3.4b)
  const UNBUILT = { Bleed: "不可表达: clamp-to-edge sampling 280 pt outside the capture (≤ 6/255, alert-native-formula §3)", Clamp: "no-op on 8-bit values", KeyFillInShader: "height 0 → off (§1)", RingShadow: "stroke 0 → 0 (keyfill §4)",
    BlurDistancePrime: "d′ = refraction + d: the blur level is taken at d (待读: which refraction term)", GradientOvalization: "the backdrop shape's ovalization not read → 0", Dark: "待读: the dark theme's 26 keys (the glasskeys dump is light) — the dark alert keeps --ios-alert-glass-filter (采样替代)",
    InteriorLift: "待读: over white the built chain gives 231 (dimming .8 → face .904), alert-pipeline-plan measured 238 and its end-to-end put the highlight layer's vibrant matrix over the whole panel (247.7); whether the KeyFill layer's α is non-zero across the interior (fillAmount .5?) is keyfill-highlight §2's α_kf outside the bands — not built" };
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
    const hw = W / 2, hh = H / 2, r = KEYS.CornerRadius, w = Math.round(W * PX), h = Math.round(H * PX);
    const mk = () => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };
    const cw = mk(), cin = mk(), cout = mk(), chl = mk(), chl2 = mk(); const iw = cw.getContext("2d").createImageData(w, h), iin = cin.getContext("2d").createImageData(w, h), iout = cout.getContext("2d").createImageData(w, h), ihl = chl.getContext("2d").createImageData(w, h), ihl2 = chl2.getContext("2d").createImageData(w, h);
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
      /* the highlight α (keyfill §2, as lens-webgl.js FS2): key band from the top (dir (0, −1)), fill band from the bottom (dir (0, 1)), each main 1 pt + diffuse 8 pt */
      const e = -d; let a1 = 0, a2 = 0;   // stage 1: the two main bands (key from the top, fill from the bottom) as one α; stage 2: the two diffuse bands (FS2's three sequential mixes)
      if (d <= 0) { for (const dy of [-1, 1]) { const nd = gy * dy; a1 += band(e, HL.keyHeight, cosK, 0, HL.curvature, nd, fw); a2 = 1 - (1 - a2) * (1 - sat(band(e, hD, cosD, biasD, 1, nd, fw))); } }
      ihl.data[o] = ihl.data[o + 1] = ihl.data[o + 2] = Math.round(255 * sat(a1)); ihl.data[o + 3] = 255; ihl2.data[o] = ihl2.data[o + 1] = ihl2.data[o + 2] = Math.round(255 * sat(a2)); ihl2.data[o + 3] = 255; }
    cw.getContext("2d").putImageData(iw, 0, 0); cin.getContext("2d").putImageData(iin, 0, 0); cout.getContext("2d").putImageData(iout, 0, 0); chl.getContext("2d").putImageData(ihl, 0, 0); chl2.getContext("2d").putImageData(ihl2, 0, 0);
    cache[key] = { weights: cw.toDataURL("image/png"), inner: cin.toDataURL("image/png"), outer: cout.toDataURL("image/png"), hl: chl.toDataURL("image/png"), hl2: chl2.toDataURL("image/png"), S, w, h, W, H }; return cache[key]; }; })();
  const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((acc, v, i) => acc + v * B[i][j], 0)));
  const faceMatrix = () => { const W = KEYS.FaceColorMatrixWhite, Bk = KEYS.FaceColorMatrixBlack, s = KEYS.FaceColorMatrixSaturation;
    const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]]; const D = [[W - Bk, 0, 0, Bk], [0, s, 0, .5 - .5 * s], [0, 0, s, .5 - .5 * s], [0, 0, 0, 1]];
    const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]]; const M = mul(mul(INV, D), YCC); const r = (v) => (+v.toFixed(5)).toString();
    return [0, 1, 2].map((i) => `${r(M[i][0])} ${r(M[i][1])} ${r(M[i][2])} 0 ${r(M[i][3])}`).join(" ") + " 0 0 0 1 0"; };
  const NS = "http://www.w3.org/2000/svg";
  const sel = (src, ch, name) => `<feColorMatrix in="${src}" type="matrix" values="${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  0 0 0 0 1" result="${name}"/>`;
  const ensureFilter = (W, H) => { let svg = document.getElementById("alert-glass-svg"); if (svg && svg.dataset.size === W + "x" + H) return; if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "alert-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); } svg.dataset.size = W + "x" + H;
    const im = images(W, H), base = KEYS.CaptureScale, sig = [1, 2].map((k) => VB_STD[k] / base), M = KEYS.CaptureMargin;
    /* the filter runs on the page copy; its region and the images sit on the panel's box in the copy's coordinates (set per placement: x, y attributes) */
    const img = (href, name) => `<feImage href="${href}" preserveAspectRatio="none" x="0" y="0" width="${W}" height="${H}" result="${name}" data-alert-img="${name}"/>`;
    svg.innerHTML = `<filter id="alert-glass-f" filterUnits="userSpaceOnUse" x="${-M}" y="${-M}" width="${W + 2 * M}" height="${H + 2 * M}" color-interpolation-filters="sRGB" data-sigma="${sig.map((v) => v.toFixed(3)).join(",")}" data-base="${base}" data-face="${faceMatrix()}" data-map-scale="${im.S}">`
      + `<feFlood flood-color="rgb(0,0,0)" flood-opacity="${KEYS.Dimming}" result="dim"/><feComposite in="dim" in2="SourceGraphic" operator="over" result="src"/>`   /* the UIDimmingView (black α .2) lies under the backdrop layer: the capture sees the dimmed page (alert-native-formula §0 row 1) */
      + `<feGaussianBlur in="src" stdDeviation="${sig[0]}" result="b1"/><feGaussianBlur in="src" stdDeviation="${sig[1]}" result="b2"/>`
      + img(im.weights, "wimg") + sel("wimg", 0, "w0") + sel("wimg", 1, "w1") + sel("wimg", 2, "w2") + img(im.inner, "mapi") + sel("mapi", 2, "wr")
      + `<feBlend in="src" in2="w0" mode="multiply" result="p0"/><feBlend in="b1" in2="w1" mode="multiply" result="p1"/><feBlend in="b2" in2="w2" mode="multiply" result="p2"/>`
      + `<feComposite in="p0" in2="p1" operator="arithmetic" k2="1" k3="1" result="s01"/><feComposite in="s01" in2="p2" operator="arithmetic" k2="1" k3="1" result="blur"/>`
      + img(im.outer, "mapo")
      + `<feDisplacementMap in="blur" in2="mapi" scale="${im.S}" xChannelSelector="R" yChannelSelector="G" result="c1"/><feDisplacementMap in="blur" in2="mapo" scale="${im.S}" xChannelSelector="R" yChannelSelector="G" result="c2"/>`
      + `<feComponentTransfer in="wr" result="wri"><feFuncR type="linear" slope="-1" intercept="1"/><feFuncG type="linear" slope="-1" intercept="1"/><feFuncB type="linear" slope="-1" intercept="1"/></feComponentTransfer>`
      + `<feBlend in="c1" in2="wri" mode="multiply" result="q1"/><feBlend in="c2" in2="wr" mode="multiply" result="q2"/><feComposite in="q1" in2="q2" operator="arithmetic" k2="1" k3="1" result="c"/>`
      + `<feColorMatrix in="c" type="matrix" values="${faceMatrix()}" result="face"/>`
      + img(im.hl, "hl") + img(im.hl2, "hl2") + `<feColorMatrix in="face" type="matrix" values="${HL.vibrant.join(" ")} 0 0 0 1 0" result="vib"/>`
      + `<feComponentTransfer in="hl" result="hli"><feFuncR type="linear" slope="-1" intercept="1"/><feFuncG type="linear" slope="-1" intercept="1"/><feFuncB type="linear" slope="-1" intercept="1"/></feComponentTransfer>`
      + `<feBlend in="face" in2="hli" mode="multiply" result="f0"/><feBlend in="vib" in2="hl" mode="multiply" result="f1"/><feComposite in="f0" in2="f1" operator="arithmetic" k2="1" k3="1" result="o1"/>`
      + `<feColorMatrix in="o1" type="matrix" values="${HL.vibrant.join(" ")} 0 0 0 1 0" result="vib2"/>`
      + `<feComponentTransfer in="hl2" result="hl2i"><feFuncR type="linear" slope="-1" intercept="1"/><feFuncG type="linear" slope="-1" intercept="1"/><feFuncB type="linear" slope="-1" intercept="1"/></feComponentTransfer>`
      + `<feBlend in="o1" in2="hl2i" mode="multiply" result="g0"/><feBlend in="vib2" in2="hl2" mode="multiply" result="g1"/><feComposite in="g0" in2="g1" operator="arithmetic" k2="1" k3="1" result="out"/></filter>`; };
  const glass = { layer: null, copy: null };
  const place = () => { if (!glass.copy || !dlg.open) return; const dr = dlg.getBoundingClientRect(), mr = document.getElementById("app").getBoundingClientRect(); const M = KEYS.CaptureMargin, W = dlg.offsetWidth, H = dlg.offsetHeight;
    /* the panel's box in the copy's coordinates (the copy = #app's pixels): the dialog's untransformed box from its rect centre and layout size (the appear animation scales it about the centre); the pane is the dialog box oversized by 60 */
    const pl = dr.left + dr.width / 2 - W / 2, pt = dr.top + dr.height / 2 - H / 2; const px = pl - mr.left, py = pt - mr.top; glass.copy.style.transform = `translate(${mr.left - (pl - 60)}px, ${mr.top - (pt - 60)}px)`;
    const f = document.getElementById("alert-glass-f"); if (f) { f.setAttribute("x", String(px - M)); f.setAttribute("y", String(py - M)); for (const im of f.querySelectorAll("feImage")) { im.setAttribute("x", String(px)); im.setAttribute("y", String(py)); } } };
  const build = () => { if (theme() !== "light") { strip(); dlg.classList.remove("glass-read"); return; }   // dark keys unread: the old substitute stays
    const main = document.getElementById("app"), pane = dlg.querySelector(".pane"); if (!main || !pane) return; strip(); ensureFilter(dlg.offsetWidth, dlg.offsetHeight);
    const layer = document.createElement("div"); layer.className = "alert-glass"; const copy = main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, script, .menu, .menu-scrim, dialog").forEach((e) => e.remove());
    copy.className = "alert-glass-copy"; copy.setAttribute("aria-hidden", "true"); copy.inert = true; const mr = main.getBoundingClientRect(); copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;pointer-events:none;filter:url(#alert-glass-f)`;
    layer.appendChild(copy); pane.appendChild(layer); glass.layer = layer; glass.copy = copy; dlg.classList.add("glass-read"); place(); };
  const strip = () => { if (glass.layer) glass.layer.remove(); glass.layer = glass.copy = null; };
  /* the dialog's open state: showModal() has no event — watch the `open` attribute */
  new MutationObserver(() => { if (dlg.open) build(); else strip(); }).observe(dlg, { attributes: true, attributeFilter: ["open"] });
  addEventListener("resize", place); addEventListener("scroll", place, { passive: true });
  window.AlertGlass = { keys: KEYS, highlight: HL, unbuilt: UNBUILT, images, faceMatrix, sdf, level, theme, rebuild: build, get layer() { return glass.layer; }, VB_STD };
})();
