/* toast-glass.js — G8 (2号 2026-09-23): the toast's material = the backdrop of UIAccessibilityHUDView (NATIVE-GAP G8;
   remote-ref/tools/uiprobe/uiprobe-subtree-g8-hud-{light,dark}.json: UICABackdropLayer scale .25, marginWidth 0, filters in array order)
     luminanceCurveMap  inputAmount .75, inputValues (.9, .83, .925, .815) light / (.16, .26, .1, .1) dark
     colorSaturate      inputAmount 1.5
     colorBrightness    inputAmount .1 (light only; the dark layer has no brightness filter)
     gaussianBlur       inputRadius 29.5, inputNormalizeEdges 1, inputDither 1
   Formulas (decompiled, not sampled):
     luminanceCurveMap  remote-ref/tools/lens/g8-luminance-curve.txt — Horner a = 3(v1−v2) + v3 − v0, b = 3(v0 − 2v1 + v2), c = 3(v1 − v0), d = v0;
                        L = sat(dot(rgb, (.2125, .7154, .0721))) on straight colour, y = sat(((aL + b)L + c)L + d), rgb = mix(rgb, y, amount)
     colorSaturate / colorBrightness  remote-ref/tools/lens/g8-saturate-brightness.txt — one 4×5 matrix: Rec.709 (.2126, .7152, .0722) saturation s,
                        brightness = + b on straight R G B (the shader adds b·α to premultiplied colour)
     gaussianBlur       QuartzCore GaussianBlurFilter::render 0x1c398ff24–0x1c398ff48: radius_px = inputRadius × *scale (the surface's px per point,
                        nav-bar-scroll-formula.md §3.4b) × the layer's axis scale; Context::create_blur_surface_internal 0x1c3901f98–0x1c3901fac:
                        the target variance = radius_px² (clamped ≤ 1e8) → σ = inputRadius in points. inputNormalizeEdges (atom 0x1a1, read at
                        0x1c39900a0): colour ÷ blurred coverage — here feGaussianBlur then alpha forced to 1 (feComponentTransfer works on straight colour).
   iOS WebKit takes no url() in backdrop-filter, so (as alert-glass.js) the glass is a still copy of #app under the toast carrying the SVG chain; the copy
   is re-cloned each time the toast shows (view.js toast() sets textContent, which drops the glass → re-inserted by the observer before the frame paints).
   Capture scale: the backdrop layer's scale .25 (probe kvc.scale) = the native backdrop is captured and blurred at a quarter of the screen's px per point and
   drawn back up — the copy is laid out at scale(.25), filtered there (σ 29.5 × .25 in copy units = the native radius_px 29.5 × 3 × .25 = 22.1 px at 3×) and
   scaled ×4 back; the filter also costs 1/16 of the pixels (D 21:5x: full resolution added ~40 ms to the appear frame).
   The text: the HUD's content layer carries vibrantColorMatrix (inputBackdropAware 1; the matrix per theme in the same probe file), whose compositing is
   keyfill-highlight.md §2 (QuartzCore vibrant_color_matrix_sover): the layer's colour is not used, only its α — out = (1 − α)·B + α·clamp(M·B + bias), B = what
   lies under it (here the material). So the page's text is laid out as usual but painted transparent (.glass-read), and a second copy runs the same chain
   plus M (filter #toast-glass-v; B is the blurred material, so it is computed at the same .25 and scaled up) under a mask = the text's own glyphs
   (canvas fillText of each laid-out line, same computed font, at devicePixelRatio).
   Not built (标): inputDither (±½ LSB noise); the capture's downsample kernel (the page is rasterised small instead of box-filtered); the appear scale .95 → 1 also
   scales the copy for its 0.1 s (the native backdrop samples the screen unscaled); the glyph mask is canvas text, not the DOM's own raster (same font and
   positions, antialiasing may differ by a level at edges). */
(function () {
  const tt = document.getElementById("toast"); if (!tt) return;
  const NS = "http://www.w3.org/2000/svg";
  const MAT = { light: { amount: 0.75, values: [0.9, 0.83, 0.925, 0.815], saturate: 1.5, brightness: 0.1, radius: 29.5,
                         vibrant: [1.5141249895095825, -0.9547510147094727, -0.18437400460243225, 0, 0.0625, -0.485603004693985, 1.04618501663208, -0.1855819970369339, 0, 0.06249997019767761, -0.4868110120296478, -0.952938973903656, 1.8147499561309814, 0, 0.0625, 0, 0, 0, 1, 0] },
                dark: { amount: 0.75, values: [0.16, 0.26, 0.1, 0.1], saturate: 1.5, brightness: 0, radius: 29.5,
                        vibrant: [1.3762500286102295, -0.7345163822174072, -0.14173349738121033, 0, 0.49999991059303284, -0.37351199984550476, 1.0163019895553589, -0.14279049634933472, 0, 0.5, -0.37456899881362915, -0.7329310178756714, 1.6074999570846558, 0, 0.49999991059303284, 0, 0, 0, 1, 0] } };   // vibrant = the content layer's inputColorMatrix (4×5 row-major), same probe files
  const theme = () => (matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light") || document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const sat = (x) => Math.max(0, Math.min(1, x));
  const horner = ([v0, v1, v2, v3]) => [3 * (v1 - v2) + v3 - v0, 3 * (v0 - 2 * v1 + v2), 3 * (v1 - v0), v0];
  const curve = (m) => { const [a, b, c, d] = horner(m.values); return (L) => sat(((a * L + b) * L + c) * L + d); };
  const f5 = (v) => (+v.toFixed(6)).toString();
  /* feComponentTransfer "table" is linear between its n values; 256 values = one per 8-bit input level, so every representable L lands on a node exactly */
  const table = (fn) => Array.from({ length: 256 }, (_, i) => f5(fn(i / 255))).join(" ");
  const satMatrix = (s, b) => { const w = [0.2126, 0.7152, 0.0722], r = (i) => [0, 1, 2].map((j) => f5(i === j ? w[j] + (1 - w[j]) * s : w[j] * (1 - s))).join(" ") + " 0 " + f5(b);
    return [0, 1, 2].map(r).join("  ") + "  0 0 0 1 0"; };
  const K = 0.25;   // UICABackdropLayer scale (uiprobe-subtree-g8-hud-{light,dark}.json kvc.scale), both themes
  const MARGIN = (m) => Math.ceil(3 * m.radius);   // the blur's support beyond the toast (3σ, page units)
  const glass = { layer: null, copy: null, vcopy: null, ups: [], lines: null, theme: null, box: null };
  const ensureFilter = (th) => { const m = MAT[th]; let svg = document.getElementById("toast-glass-svg");
    if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "toast-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.setAttribute("aria-hidden", "true"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    if (svg.dataset.theme === th) return svg.querySelector("filter"); svg.dataset.theme = th;
    const lum = [0, 1, 2].map(() => ".2125 .7154 .0721 0 0").join("  ") + "  0 0 0 1 0", y = table(curve(m));
    const chain = `<feColorMatrix in="SourceGraphic" type="matrix" values="${lum}" result="L"/>`
      + `<feComponentTransfer in="L" result="Y"><feFuncR type="table" tableValues="${y}"/><feFuncG type="table" tableValues="${y}"/><feFuncB type="table" tableValues="${y}"/></feComponentTransfer>`
      + `<feComposite in="SourceGraphic" in2="Y" operator="arithmetic" k1="0" k2="${f5(1 - m.amount)}" k3="${f5(m.amount)}" k4="0" result="curve"/>`
      + `<feColorMatrix in="curve" type="matrix" values="${satMatrix(m.saturate, m.brightness)}" result="mat"/>`
      + `<feGaussianBlur in="mat" stdDeviation="${m.radius * K}" result="blur"/>`
      + `<feComponentTransfer in="blur" result="B"><feFuncA type="discrete" tableValues="1"/></feComponentTransfer>`;
    const head = (id) => `<filter id="${id}" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB" data-theme="${th}" data-margin="${MARGIN(m)}">`;
    svg.innerHTML = head("toast-glass-f") + chain + `</filter>` + head("toast-glass-v") + chain + `<feColorMatrix in="B" type="matrix" values="${m.vibrant.map(f5).join(" ")}"/></filter>`;
    return svg.querySelector("filter"); };
  /* the toast's untransformed box (translate 0 −50% and the appear scale act about its centre) in viewport coordinates */
  const box = () => { const r = tt.getBoundingClientRect(), cs = getComputedStyle(tt), px = (k) => parseFloat(cs[k]) || 0, bb = cs.boxSizing === "border-box";   // the untransformed border box, unrounded (offsetWidth / offsetHeight round to whole px: a 64.66 px toast read as 65 stretched the glyph mask 1 device px by line 2)
    const W = px("width") + (bb ? 0 : px("paddingLeft") + px("paddingRight") + px("borderLeftWidth") + px("borderRightWidth")), H = px("height") + (bb ? 0 : px("paddingTop") + px("paddingBottom") + px("borderTopWidth") + px("borderBottomWidth")); return { l: r.left + r.width / 2 - W / 2, t: r.top + r.height / 2 - H / 2, W, H }; };
  const place = () => { if (!glass.copy) return; const main = document.getElementById("app"); if (!main) return; const b = box(), mr = main.getBoundingClientRect(), f = document.getElementById("toast-glass-f"); if (!f) return;
    const ox = mr.left - b.l, oy = mr.top - b.t, M = +f.dataset.margin; for (const up of glass.ups) up.style.transform = `translate(${ox}px, ${oy}px) scale(${1 / K})`; glass.box = b;   // page point p → toast point ox + p (via the copy at K)
    for (const ff of document.querySelectorAll("#toast-glass-f, #toast-glass-v")) { ff.setAttribute("x", String((-ox - M) * K)); ff.setAttribute("y", String((-oy - M) * K)); ff.setAttribute("width", String((b.W + 2 * M) * K)); ff.setAttribute("height", String((b.H + 2 * M) * K)); } };
  /* the text's glyphs as an α image: every laid-out character (Range client rect per code point, un-scaled about the toast centre like box()) drawn one by one with fillText
     in the toast's computed font at devicePixelRatio, at its own laid-out x — a whole line drawn from its left drifted off the laid-out glyphs on iOS 27 Safari
     (simulator D, 09-23 22:02: ink missed from the glyphs after 「跑 」 on). Layout may trim fullwidth punctuation (CSS Text 4 text-spacing-trim) and canvas draws the
     untrimmed glyph: a trimmed opening bracket (Ps / Pi) loses its start half (the spec's trimmed side), so it is drawn right-aligned in its box. */
  const glyphMask = (b) => { const r = tt.getBoundingClientRect(), sc = r.width / b.W || 1, cx = r.left + r.width / 2, cy = r.top + r.height / 2, un = (x, c) => c + (x - c) / sc;
    const dpr = window.devicePixelRatio || 1, cv = document.createElement("canvas"); cv.width = Math.ceil(b.W * dpr); cv.height = Math.ceil(b.H * dpr); const ctx = cv.getContext("2d"), cs = getComputedStyle(tt);
    ctx.scale(dpr, dpr); ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`; ctx.fillStyle = "#000"; ctx.textBaseline = "alphabetic"; const lines = new Map(), open = /[\p{Ps}\p{Pi}]/u;
    const texts = () => document.createTreeWalker(tt, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.parentElement && n.parentElement.closest(".toast-glass") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
    for (let w = texts(), n = w.nextNode(); n; n = w.nextNode()) { const rg = document.createRange(); for (let i = 0; i < n.data.length; ) { const ch = String.fromCodePoint(n.data.codePointAt(i)); rg.setStart(n, i); rg.setEnd(n, i + ch.length); i += ch.length;
      const q = rg.getClientRects()[0]; if (!q || !q.width || !ch.trim()) continue; const top = un(q.top, cy) - b.t, key = Math.round(top * 4) / 4, left = un(q.left, cx) - b.l, right = un(q.right, cx) - b.l;
      if (!lines.has(key)) lines.set(key, { top, left, text: "", chars: [] }); const Ln = lines.get(key); Ln.text += ch; Ln.chars.push({ ch, left, right }); } }
    // Baseline read from layout, not from font metrics: an empty inline-block's baseline is its bottom margin edge (CSS 2.1 §10.8.1), so a 0x0 one before the first glyph sits with its bottom on line 1's baseline; later lines keep the same top-to-baseline offset (one font, one line-height).
    const first = texts().nextNode(), ls = [...lines.values()];
    if (first && ls.length) { const pr = document.createElement("span"); pr.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline"; first.parentNode.insertBefore(pr, first); const base = un(pr.getBoundingClientRect().bottom, cy) - b.t - ls[0].top; pr.remove();
      for (const Ln of ls) for (const c of Ln.chars) ctx.fillText(c.ch, open.test(c.ch) ? c.right - ctx.measureText(c.ch).width : c.left, Ln.top + base); }
    return { url: cv.toDataURL(), lines: ls }; };
  const build = () => { const main = document.getElementById("app"); if (!main) return; const th = theme(); ensureFilter(th); strip();
    const mr = main.getBoundingClientRect(), ph = Math.max(mr.height, innerHeight + 200);
    const page = main.cloneNode(true); page.removeAttribute("id"); page.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); page.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, dialog").forEach((e) => e.remove());
    page.className = "toast-glass-page"; page.setAttribute("aria-hidden", "true"); page.inert = true; page.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;min-height:${ph}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};transform:scale(${K});transform-origin:0 0`;   // body's colour under #app (#app paints none)
    const mk = (fid, pg) => { const copy = document.createElement("div"); copy.className = "toast-glass-copy"; copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width * K}px;height:${ph * K}px;pointer-events:none;filter:url(#${fid})`; copy.appendChild(pg);
      const up = document.createElement("div"); up.className = "toast-glass-up"; up.style.cssText = "position:absolute;left:0;top:0;transform-origin:0 0;pointer-events:none"; up.appendChild(copy); return { up, copy }; };
    const A = mk("toast-glass-f", page), V = mk("toast-glass-v", page.cloneNode(true)), b = box(), gm = glyphMask(b);
    const vib = document.createElement("div"); vib.className = "toast-glass-vib"; vib.style.cssText = `position:absolute;inset:0;pointer-events:none;-webkit-mask:url(${gm.url}) 0 0 / ${b.W}px ${b.H}px no-repeat;mask:url(${gm.url}) 0 0 / ${b.W}px ${b.H}px no-repeat`; vib.appendChild(V.up);
    const layer = document.createElement("div"); layer.className = "toast-glass"; layer.setAttribute("aria-hidden", "true"); layer.appendChild(A.up); layer.appendChild(vib);
    tt.prepend(layer); glass.layer = layer; glass.copy = A.copy; glass.vcopy = V.copy; glass.ups = [A.up, V.up]; glass.lines = gm.lines; glass.theme = th; tt.classList.add("glass-read"); place(); };
  const strip = () => { if (glass.layer) glass.layer.remove(); glass.layer = glass.copy = glass.vcopy = glass.box = glass.lines = null; glass.ups = []; tt.classList.remove("glass-read"); };
  /* showing = the .show class; view.js toast() rewrites textContent (the layer goes with it) and adds .show in the same task — both land in one observer call */
  new MutationObserver(() => { const on = tt.classList.contains("show"); if (on && (!glass.layer || glass.layer.parentNode !== tt)) build(); }).observe(tt, { attributes: true, attributeFilter: ["class"], childList: true });
  tt.addEventListener("transitionend", (e) => { if (e.target === tt && e.propertyName === "opacity" && !tt.classList.contains("show")) strip(); });   // hidden: drop the copy after the 0.1 s fade
  addEventListener("resize", place); addEventListener("scroll", place, { passive: true });
  window.ToastGlass = { MAT, K, horner, curve, satMatrix, theme, rebuild: build, get layer() { return glass.layer; }, get box() { return glass.box; }, get lines() { return glass.lines; } };
})();
