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
   (an SVG image of the same text laid out by the engine with the toast's computed styles, see glyphMask).
   Not built (标): inputDither (±½ LSB noise); the capture's downsample kernel (the page is rasterised small instead of box-filtered); the appear scale .95 → 1 also
   scales the copy for its 0.1 s (the native backdrop samples the screen unscaled); the glyph mask is the engine's own layout of the same text in an image,
   not the DOM text's raster itself (same font and positions, antialiasing may differ by a level at edges). */
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
  const glass = { layer: null, copy: null, vcopy: null, ups: [], maskText: null, maskLines: null, theme: null, box: null };
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
  /* the text's glyphs as an α image laid out by the engine itself: an SVG image whose foreignObject holds the toast's text in a box of the toast's border-box size
     with its computed text styles, painted black — the same fonts, line breaks, punctuation trimming and fractional glyph positions as the DOM text (the mask is
     that image at b.W × b.H on the layer). The earlier canvas text sat 1.0–1.6 device px left of the laid-out glyphs on iOS 27 Safari (simulator D, 09-23 22:4x):
     WebKit's per-character Range rects are whole pixels (现 30–45, 在 44–60, 正 59–75) and the canvas font's advances differ from the DOM's
     (measureText 现 14.88 / 在 14.03 / five glyphs 71.01 against about 74 laid out). */
  const STYLE = ["display", "font-family", "font-size", "font-weight", "font-style", "font-stretch", "font-variant", "font-feature-settings", "font-variation-settings", "font-kerning",
    "font-optical-sizing", "font-synthesis", "line-height", "letter-spacing", "word-spacing", "text-align", "text-align-last", "text-indent", "text-transform", "text-spacing-trim",
    "text-autospace", "white-space", "white-space-collapse", "text-wrap", "word-break", "overflow-wrap", "line-break", "hyphens", "tab-size", "direction", "unicode-bidi",
    "writing-mode", "text-rendering", "-webkit-font-smoothing", "padding-top", "padding-right", "padding-bottom", "padding-left", "border-top-width", "border-right-width",
    "border-bottom-width", "border-left-width", "overflow", "text-overflow", "-webkit-line-clamp", "-webkit-box-orient", "align-items", "justify-content", "flex-direction"];
  const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const glyphMask = (b) => { const cs = getComputedStyle(tt), lang = (tt.closest("[lang]") || document.documentElement).getAttribute("lang") || "";
    const text = [...tt.childNodes].filter((n) => n.nodeType === 3).map((n) => n.data).join("");   // the toast's own text (view.js toast() sets textContent; the glass layer is an element)
    const css = STYLE.map((k) => { const v = cs.getPropertyValue(k); return v ? `${k}:${v}` : ""; }).filter(Boolean).join(";").replace(/"/g, "'");
    const div = `<div xmlns="http://www.w3.org/1999/xhtml"${lang ? ` lang="${lang}"` : ""} style="box-sizing:border-box;margin:0;width:${b.W}px;height:${b.H}px;border-style:solid;border-color:transparent;color:#000;background:none;${esc(css)}">${esc(text)}</div>`;
    /* one mask layer per line: the image document rounds each baseline to a whole CSS px, the page to a device px (TextBoxPainter.cpp textOriginFromPaintRect:
       y = roundToDevicePixel(box y + ascent, document deviceScaleFactor); SVGImage.cpp never sets one, Page.h:1589 defaults it to 1), so on D (dpr 3) line 1 at
       27.65625 painted at 28 in the image and 83/3 in the page (mask 1 device px low), line 2 at 47.984375 at 48 in both. Layer i is the whole text clipped to
       line i's box, moved by page baseline − image baseline, both from that rule (the move is a whole number of device px, so its own placement does not round). */
    /* the image's own size is whole CSS px: SVGImage.cpp drawForContainer (L237–247) lays the image out in roundedIntSize(container) and scales the source rect by
       rounded / exact to "compensate", so a 64.65625 px tall image was laid out 65 tall and drawn into 64.65625 — every glyph 0.9947 of its height (D 09-23 23:3x:
       Latin E 32.445 → 32.106 device px; SVGImageForContainer.cpp L39–41 reports the same rounded size). ceil(W) × ceil(H) is drawn 1 : 1; the text box inside stays b.W × b.H. */
    const IW = Math.ceil(b.W), IH = Math.ceil(b.H), LIFT = 1;
    const bl = baselines(b), dpr = devicePixelRatio || 1, lead = bl.length ? bl[0] - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.borderTopWidth) || 0) : 0;
    const layers = (bl.length ? bl : [null]).map((y, i) => { const y0 = i && y !== null ? y - lead : 0, y1 = y !== null && i < bl.length - 1 ? bl[i + 1] - lead : b.H;
      const dy = y === null ? 0 : Math.round((b.t + y) * dpr) / dpr - b.t - Math.round(y);
      /* the layer is placed at dy + LIFT with the image's content drawn LIFT px higher inside it, so the mask offset is always > 0: BackgroundPainter.cpp
         L796–801 (no-repeat) moves the destination rect by a positive offset but turns a negative one into the tile phase, and L610–615 snaps phase and
         destination rect separately — on D a negative dy put line 1 1 device px off at 6 of 8 panel tops (09-23 23:4x sweep k/24 px: +1 +1 +1 −1 −1 +1 0 0),
         while line 2 (dy ≥ 0) was 0 at all 8. |dy| ≤ ⅔ (½ px baseline rounding + ⅙ px device rounding), LIFT = 1 whole CSS px = 3 device px on D (moves no rounding). */
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${IW}" height="${IH}"><clipPath id="l"><rect x="0" y="${y0}" width="${b.W}" height="${y1 - y0}"/></clipPath><g transform="translate(0 ${-LIFT})"><g clip-path="url(#l)"><foreignObject x="0" y="0" width="${b.W}" height="${b.H}">${div}</foreignObject></g></g></svg>`;
      return { url: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg), dy: dy + LIFT }; });
    return { layers, text, baselines: bl, IW, IH }; };
  /* each line's baseline in the toast's untransformed box, unrounded (layout units): one zero-size inline-block before the text gives line 1's baseline; line n's
     = line 1's + (top of line n's first character's box − top of line 1's), both boxes of the same font. A mark inside a later line was wrong for Latin text:
     it adds a wrap opportunity mid-word, so "to f|inish" pulled the "f" and the mark back onto line 1 (D 09-23 23:5x: both baselines read 27.656). */
  const baselines = (b) => { const tn = [...tt.childNodes].find((n) => n.nodeType === 3); if (!tn || !tn.data) return [];
    const s = tn.data, r = document.createRange(), tops = []; let prev = null;
    for (let i = 0; i < s.length; i += s.codePointAt(i) > 0xffff ? 2 : 1) { if (/\s/.test(s[i])) continue;   // a line never starts with collapsible white space
      r.setStart(tn, i); r.setEnd(tn, i + (s.codePointAt(i) > 0xffff ? 2 : 1)); const q = r.getClientRects()[0]; if (!q) continue;
      if (prev === null || q.top > prev + q.height / 2) tops.push(q.top); prev = q.top; }
    if (!tops.length) return [];
    const m = document.createElement("span"); m.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline"; tt.insertBefore(m, tn);
    const tr = tt.getBoundingClientRect(), sc = tr.height / b.H || 1, bl0 = m.getBoundingClientRect().bottom; m.remove();   // the appear scale acts about the centre
    return tops.map((t) => (bl0 + (t - tops[0]) - tr.top - tr.height / 2) / sc + b.H / 2); };
  const build = () => { const main = document.getElementById("app"); if (!main) return; const th = theme(); ensureFilter(th); strip();
    const mr = main.getBoundingClientRect(), ph = Math.max(mr.height, innerHeight + 200);
    const page = main.cloneNode(true); page.removeAttribute("id"); page.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); page.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, dialog").forEach((e) => e.remove());
    page.className = "toast-glass-page"; page.setAttribute("aria-hidden", "true"); page.inert = true; page.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;min-height:${ph}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};transform:scale(${K});transform-origin:0 0`;   // body's colour under #app (#app paints none)
    const mk = (fid, pg) => { const copy = document.createElement("div"); copy.className = "toast-glass-copy"; copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width * K}px;height:${ph * K}px;pointer-events:none;filter:url(#${fid})`; copy.appendChild(pg);
      const up = document.createElement("div"); up.className = "toast-glass-up"; up.style.cssText = "position:absolute;left:0;top:0;transform-origin:0 0;pointer-events:none"; up.appendChild(copy); return { up, copy }; };
    const A = mk("toast-glass-f", page), V = mk("toast-glass-v", page.cloneNode(true)), b = box(), gm = glyphMask(b);
    const vib = document.createElement("div"); vib.className = "toast-glass-vib"; vib.style.cssText = `position:absolute;inset:0;pointer-events:none;${["-webkit-mask", "mask"].map((k) => `${k}:${gm.layers.map((l) => `url("${l.url}") 0 ${l.dy}px / ${gm.IW}px ${gm.IH}px no-repeat`).join(", ")}`).join(";")}`; vib.appendChild(V.up);
    const layer = document.createElement("div"); layer.className = "toast-glass"; layer.setAttribute("aria-hidden", "true"); layer.appendChild(A.up); layer.appendChild(vib);
    tt.prepend(layer); glass.layer = layer; glass.copy = A.copy; glass.vcopy = V.copy; glass.ups = [A.up, V.up]; glass.maskText = gm.text; glass.maskLines = gm.layers.map((l, i) => ({ baseline: gm.baselines[i], dy: l.dy })); glass.theme = th; tt.classList.add("glass-read"); place(); };
  const strip = () => { if (glass.layer) glass.layer.remove(); glass.layer = glass.copy = glass.vcopy = glass.box = glass.maskText = glass.maskLines = null; glass.ups = []; tt.classList.remove("glass-read"); };
  /* showing = the .show class; view.js toast() rewrites textContent (the layer goes with it) and adds .show in the same task — both land in one observer call */
  new MutationObserver(() => { const on = tt.classList.contains("show"); if (on && (!glass.layer || glass.layer.parentNode !== tt)) build(); }).observe(tt, { attributes: true, attributeFilter: ["class"], childList: true });
  tt.addEventListener("transitionend", (e) => { if (e.target === tt && e.propertyName === "opacity" && !tt.classList.contains("show")) strip(); });   // hidden: drop the copy after the 0.1 s fade
  addEventListener("resize", place); addEventListener("scroll", place, { passive: true });
  window.ToastGlass = { MAT, K, horner, curve, satMatrix, theme, rebuild: build, get layer() { return glass.layer; }, get box() { return glass.box; }, get maskText() { return glass.maskText; }, get maskLines() { return glass.maskLines; } };
})();
