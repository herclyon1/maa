/* menu.js — the value row's pull-down menu: a geometry morph from the button's frame to the panel, in place of the old scale-and-fade
   (BOARD.md #3, night batch: geometry and timing only, no material).
   Basis (read values): menu-motion-formula.md §0 table / §2 — appear = one spring each for position x / y, width, height, ζ .8 / response .3 s
   (the liquidMorph spec, ω = 2π/.3); dismiss = the same four with ζ .9 / .3 (liquidMorphShrink); reduce-motion = ζ 1 / .15 cross-fade
   (liquidMorphReduceMotion); no dimming (_hasVisibleBackground NO, the scrim stays transparent); the source is the trigger button's own frame
   (morphPreviewFromAttachmentPoint, anchor (.5, .5)) — here the .menubtn's rect; the corner follows the same spring from the button's corner to
   the menu's (§4.1). menu-card-material.md §1.2 — width 250 (defaultMenuWidth), corner 32 (menuCornerRadius), section insets 10 / 10, item 42
   (the item rules stay index.html's `.menu button`). The panel's placement (below the value, 6 pt gap, ≥ 8 pt from the edges, above when
   there is no room) is the page's existing rule (view.js openMenu), kept.
   Unread, left out (menu-motion-formula.md §6): the intermediate shape (growing .25 / shrinking .9) and the .03 s second-step delay that belongs
   to it — the four springs run straight to the target from the frame of the call; the content's cross-blur / contentScale on the menu path —
   the items sit in the panel from the first frame, clipped by it.
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
  const UNBUILT = { "BlurDistance*/BlurOpacity*": "不可表达 in one feGaussianBlur (the rim's 1 pt reduction)", "FaceColorMatrixWhite/Black/Saturation": "待读: the luma weights of set_ycc_composite", "FaceColorMatrixMaxLuma*": "待读: formula", "BlurFill*": "待读: formula",
    "InnerRefraction*/OuterRefraction*/RefractionOpacity/RefractionDistance*": "待做: a displacement map for the r32 rounded rect (generator makes capsules)", "KeyFillHighlight*": "待做: the in-shader highlight block with these keys", "Bleed*": "待做: the SDF-distance bleed (alert-pipeline-plan §1.3 variant e)", "Shadow* (opacity .4/.6, radius 24)": "待读: whether a soft shadow remains with amount 0" };
  const glassTheme = () => (matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light") || document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const glassKeys = (theme) => ({ ...GLASS_KEYS.light, ...(theme === "dark" ? GLASS_KEYS.dark : {}) });
  const NS = "http://www.w3.org/2000/svg";
  const ensureFilter = (theme) => { const k = glassKeys(theme); let svg = document.getElementById("menu-glass-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "menu-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const fill = k.FaceColorMatrixFillColor; const flood = fill[3] > 0 ? `<feFlood flood-color="rgb(${fill[0] * 255},${fill[1] * 255},${fill[2] * 255})" flood-opacity="${fill[3]}" result="fill"/><feComposite in="fill" in2="blur" operator="over"/>` : "";
    svg.innerHTML = `<filter id="menu-glass-f" x="-25%" y="-25%" width="150%" height="150%" color-interpolation-filters="sRGB" data-theme="${theme}" data-blur-radius="${k.BlurRadius}" data-sigma="${k.BlurRadius * 4}"><feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur"/>${flood}</filter>`
      + `<filter id="menu-glass-ring" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="${k.RingShadowBlurRadius}"/></filter>`; return k; };
  /* the ring band: the rounded rect (the panel's box) shifted RingShadowOffset down, the band = the shape minus the same shape inset by the stroke width (evenodd) */
  const ringPath = (w, h, r, off, sw) => { const rr = (x, y, ww, hh, rad) => { const q = Math.max(0, Math.min(rad, ww / 2, hh / 2)); return `M${x + q} ${y}H${x + ww - q}A${q} ${q} 0 0 1 ${x + ww} ${y + q}V${y + hh - q}A${q} ${q} 0 0 1 ${x + ww - q} ${y + hh}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + hh - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
    return rr(0, off, w, h, r) + " " + rr(sw, off + sw, w - 2 * sw, h - 2 * sw, Math.max(0, r - sw)); };
  const buildGlass = (panel) => { const theme = glassTheme(), k = ensureFilter(theme); const main = document.getElementById("app"); if (!main) return null;
    const layer = document.createElement("div"); layer.className = "menu-glass"; const copy = main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, script, .menu, .menu-scrim").forEach((e) => e.remove()); copy.className = "menu-glass-copy"; copy.setAttribute("aria-hidden", "true"); copy.inert = true;
    const mr = main.getBoundingClientRect(); copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;pointer-events:none;filter:url(#menu-glass-f)`;
    const ring = document.createElementNS(NS, "svg"); ring.setAttribute("class", "menu-glass-ring"); ring.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;mix-blend-mode:multiply;pointer-events:none;overflow:visible"; const path = document.createElementNS(NS, "path"); path.setAttribute("fill", "#000"); path.setAttribute("fill-rule", "evenodd"); path.setAttribute("fill-opacity", String(k.RingShadowOpacity)); path.setAttribute("filter", "url(#menu-glass-ring)"); ring.appendChild(path);
    layer.append(copy, ring); panel.insertBefore(layer, panel.firstChild);
    return { layer, copy, ring, path, mr, theme, keys: k }; };
  const placeGlass = (g, s) => { if (!g) return; const w = s.width.x, h = s.height.x, r = s.r.x; g.copy.style.transform = `translate(${g.mr.left - s.left.x}px, ${g.mr.top - s.top.x}px)`;   // the copy stays on the page's pixels while the panel moves
    g.ring.setAttribute("viewBox", `0 0 ${Math.max(1, w)} ${Math.max(1, h)}`); g.path.setAttribute("d", ringPath(w, h, r, g.keys.RingShadowOffset, g.keys.RingShadowStrokeWidth)); };
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
    if (settled(goal)) { if (cur.phase === "out") { strip(); return; } cur.raf = 0; return; }   // "in" settled: the panel rests, the loop stops
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
    const glass = buildGlass(panel);
    const h = body.offsetHeight;   // items × 42 + the 10 / 10 insets
    const from = anchorRect(anchor), to = restRect(anchor, h), reduced = o && o.reduced != null ? !!o.reduced : reduce();
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
    cur.scrim.style.pointerEvents = "none"; run(); cur.t0 = cur.prev; cur.t = 0; cur.frame = 0;
  }
  /* hidden strips the state at once (BOARD A6 template): nothing animates while the page is away and a half-open menu must not come back */
  const onHidden = (force) => { if (force || document.hidden) strip(); };
  document.addEventListener("visibilitychange", () => onHidden(false));
  window.Menu = { glass: { keys: glassKeys, built: BUILT, unbuilt: UNBUILT, theme: glassTheme }, open, close, onHidden, state: () => cur ? { phase: cur.phase, from: { ...cur.from }, to: { ...cur.to }, reduced: cur.reduced, t0: cur.t0, t: cur.t || 0, frame: cur.frame || 0,
    x: { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, a: cur.s.a.x } } : null };
})();
