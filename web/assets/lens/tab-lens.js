/* tab-lens.js — the tab bar's lifted selection lens (GOAL 3; README §0.8 / §0.8.1 / §0.8.3). One line to include, after view.js:
     <script src="assets/lens/tab-lens.js"></script>          (?tlens=0 off; ?tlens-ab=0 without the colour fringe; data-family="assets/lens/tab5/")
   What it is: the Liquid Glass lens that lifts off the selected tab (formula.md §4b — the segment lens's layer structure with the tab's keys,
   tab-lens-native.md §0 / §3), driven by the states view.js's attachTabBar already sets on the page (nothing in view.js changes): .glide gets
   `lift-sel` (+125 ms on the selected item) / `lift` (+140 ms on another item), its inline left / width = the item under the finger, nav gets
   `drag`, the classes go at the up, `button.on` moves at a selection. This script only watches those (MutationObserver) and draws.
   Layers (one fixed element .tabbar-lens in screen coordinates; the platter's presentation scale is NOT an ancestor transform of the filtered
   layers — the engine fact of calib/webkit-region-under-scale.html is read at ½ only — it is folded into the layout and the filter scale):
     .stack (lens box + 16 pt; the colour fringe chain #tab-lens-f-ab-<w> on it, W/H per frame from the capture box — layer 5)
       .base   the plain copy under the wrapper: the page (a clone of <main>), the platter (clone-blurred page + the glass fill), the items
       .warp > .disp (#tab-lens-f-bg-<w>, layer 1 = BackdropView +9/36 after glassBackground −10.5/7): the same copy with the items punched
               out inside the capsule (DestOut #76, α = the lift progress; the box corners keep them — the map's clamp reads them at the rim)
       .ish    the inner shadow #37 (#tab-lens-f-ish: keyfill-highlight.md §5.2c op·M·blur_σ(M − M↓7), keys .06 / (0, 7) / r 3, α × progress)
       .warpl > .displ (#tab-lens-f-lab-<w>, layers 2 + 4 = ContentLensing −14/11.2 then ClearGlass −17.5/11.2): the SelectedContentView copy —
               the items at scale 1 → 1.16 about their own centres, capsule-clipped BEFORE the filter (the layer's border-radius)
   Geometry (tab-lens-native.md §3, formula.md §5b): model = the platter's resting frame; lens model box at progress p = (w0 + 16p) × (54 + 16p),
   r = h/2, centred on the item (w0 = the item width: 82 on the 440 screen, the tab5/ family; the native 94 → 110 read as +16 on both axes);
   presented = model scaled 1 → 1.0516 about the platter centre (the real .plat / .seg / .glide carry that scale, --tplatter-scale); the maps
   (model pt) are stretched over the presented box and the feDisplacementMap scale = data-s × p × s. Set = the nearest even width of the family.
   Motion (tab-lens-motion.md §4, the read curves): lift = ONE spring ζ 1 / response .25 s for every quantity (size, r, the three amounts,
   _UITabSelectionView α 1 → 0 (= .glide, --tsel-alpha), DestOut 0 → 1, items 1 → 1.16, platter 1 → 1.0516); drop = the same back with
   ζ 1 / .4 s; page change while held (press another item / drag) = position ζ .85 / .4 s from the old centre to the new + the lift at the same
   time (the flex stretch of the loupe is NOT drawn: no read sets beyond the lift for this family; the ±1.6 pt wobble after the drop unread; a
   quick tap without the +140 ms lift keeps view.js's glide slide — the tap's lens trace is unread). The drag while lifted retargets the same
   position spring (UIKitCore reads ζ .85 / .2 for the highlighted selection view (§6) — the presented trace fits .4 (§3); .4 kept, recorded).
   Not drawn yet (material, the ui session's tokens): the KeyFill highlight, the ring shadow, the dark line, the little glow (α 0 → .2).
   Instrument: window.__tabLens = the per-frame state (t s since the start, p, x, v, target, set, s, phase). */
(function () {
  const q = new URLSearchParams(location.search);
  if (q.get("tlens") === "0") return;
  const me = document.currentScript;
  const FAMILY = (me && me.dataset.family) || "assets/lens/tab5/";
  const FRINGE = q.get("tlens-ab") !== "0";
  /* instrument (wksnap's offscreen WKWebView never fires requestAnimationFrame and throttles timers — document hidden): ?tlens-clock=timer drives the
     loop by setTimeout; ?tlens-clock=manual gives the loop a virtual clock stepped by window.__tabLensStep(dt_ms) from the test script (deterministic:
     the springs integrate the dt they are given). The device uses requestAnimationFrame. */
  const CLOCK = q.get("tlens-clock") || "raf";
  let vnow = 0, pendingTick = null;
  const clockNow = () => CLOCK === "manual" ? vnow : performance.now();
  const tick = (fn) => { if (CLOCK === "manual") pendingTick = fn; else if (CLOCK === "timer") setTimeout(() => fn(performance.now()), 16.667); else requestAnimationFrame(fn); };
  window.__tabLensStep = (dt) => { vnow += dt; const f = pendingTick; pendingTick = null; if (f) f(vnow); return !!f; };
  const AM = 16;                                                              // the fringe wrapper's margin (lens-field.json aberration.wrapper; ≥ the 15 pt tap span)
  const LIFT = 16, PLATTER = 1.0516, ITEM = 1.16;                             // +16 on both axes (94×54 → 110×70), platter 1.0516, items 1.16 (tab-lens-native.md §3)
  const SP_LIFT = { z: 1, w: 2 * Math.PI / .25 }, SP_DROP = { z: 1, w: 2 * Math.PI / .4 }, SP_POS = { z: .85, w: 2 * Math.PI / .4 };   // tab-lens-motion.md §0 / §4
  const step = (st, target, sp, dt) => {                                      // analytic damped-spring step from (x, v): ζ ≥ 1 critically damped, else under-damped
    const dx = st.x - target;
    if (sp.z >= 1) { const A = dx, B = st.v + sp.w * dx, e = Math.exp(-sp.w * dt); st.x = target + (A + B * dt) * e; st.v = (B - sp.w * (A + B * dt)) * e; }
    else { const wd = sp.w * Math.sqrt(1 - sp.z * sp.z), e = Math.exp(-sp.z * sp.w * dt), A = dx, B = (st.v + sp.z * sp.w * dx) / wd, c = Math.cos(wd * dt), s = Math.sin(wd * dt);
      st.x = target + e * (A * c + B * s); st.v = e * (-sp.z * sp.w * (A * c + B * s) + wd * (B * c - A * s)); }
  };
  const sets = [];                                                            // the family's widths (from the filter ids), ascending
  const setFor = (w) => { let best = sets[0] || 82, d = Infinity; for (const s of sets) { const dd = Math.abs(s - w); if (dd < d) { d = dd; best = s; } } return best; };
  const sOf = (id) => { const f = document.getElementById(id); return f ? parseFloat(f.getAttribute("data-s")) || 40 : 40; };   // data-s = the set's encoding S (× SS when lens-supersample.js folded it in)

  /* the filters: the family's lens-filter.svg is fetched and inserted (its feImage hrefs are the page's paths), then the two engine corrections re-run over it */
  let ready = false;
  const loadFilters = async () => {
    try {
      const txt = await (await fetch(FAMILY + "lens-filter.svg")).text();
      const svg = document.importNode(new DOMParser().parseFromString(txt, "text/html").querySelector("svg"), true);   // the HTML parser, as index.html's inline copy: the file's comments hold "--" (XML would refuse them)
      svg.setAttribute("data-tab-lens", FAMILY); document.body.appendChild(svg);
      for (const f of svg.querySelectorAll('filter[id^="tab-lens-f-bg-"]')) sets.push(parseInt(f.id.slice("tab-lens-f-bg-".length), 10));
      sets.sort((a, b) => a - b);
      if (window.LENS_SS_APPLY) window.LENS_SS_APPLY();
      if (window.LENS_ENGINE_FIX_APPLY) await window.LENS_ENGINE_FIX_APPLY();
      ready = true;
    } catch (e) { console.warn("tab-lens: filters", e); }
  };

  const el = (cls, parent, css) => { const d = document.createElement("div"); d.className = cls; if (css) d.style.cssText = css; if (parent) parent.appendChild(d); return d; };
  const stripIds = (n) => { n.removeAttribute("id"); for (const c of n.querySelectorAll("[id]")) c.removeAttribute("id"); return n; };
  /* a copy of the page (what lies under the bar): <main> cloned without ids, laid out at the page's width; the body colour behind it */
  const pageCopy = (parent, main, mr) => { const w = el("pg", parent, `position:absolute;inset:0;overflow:hidden;background:${getComputedStyle(document.body).backgroundColor}`);   // overflow hidden: WebKit takes an overflowing child into a filter's objectBoundingBox region — the page clone must not enlarge the lens filters' buffers
    const m = stripIds(main.cloneNode(true)); m.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;margin:0;pointer-events:none`; w.appendChild(m); w._m = m; return w; };
  /* the platter as the lens sees it: the capsule (scaled 1 → 1.0516 with the real one) holding the page blurred by the glass recipe (a
     backdrop-filter inside a software-filtered layer does not blur — README §0.8.1 — so the copy blurs a page clone with `filter`) and the fill + rim */
  const BM = 32;                                                              // the blurred clone's clip margin beyond the platter box: > 3σ of the glass blur (10 px), so the capsule's edge sees real pixels
  const platterCopy = (parent, main, mr, pr) => { const pl = el("pl", parent, `position:absolute;left:0;top:0;width:${pr.width}px;height:${pr.height}px`);
    const inv = el("inv", pl); const bp = el("blurpg", inv, `position:absolute;left:${-BM}px;top:${-BM}px;width:${pr.width + 2 * BM}px;height:${pr.height + 2 * BM}px;overflow:hidden;background:${getComputedStyle(document.body).backgroundColor}`);
    const m = stripIds(main.cloneNode(true)); m.style.cssText = `position:absolute;left:${mr.left - pr.left + BM}px;top:${mr.top - pr.top + BM}px;width:${mr.width}px;margin:0;pointer-events:none`; bp.appendChild(m);
    el("fill", pl); return pl; };
  /* the items as a shell <nav class="tabs"> (so index.html's nav.tabs button rules dress the copies; the page copies live outside any nav.tabs) */
  const itemsCopy = (parent, nav, seg, pr) => { const sh = nav.cloneNode(false); sh.removeAttribute("id"); sh.removeAttribute("hidden"); sh.classList.remove("drag", "tlens");
    sh.style.cssText = `position:absolute;left:0;top:0;bottom:auto;width:${pr.width}px;height:${pr.height}px;max-width:none;margin:0;padding:0;display:block;transform:none;z-index:auto;pointer-events:none`;
    const s = seg.cloneNode(true); s.removeAttribute("id"); for (const b of s.querySelectorAll("button")) b.removeAttribute("id"); s.style.cssText = `position:absolute;left:0;top:0;width:${pr.width}px;height:${pr.height}px;box-sizing:border-box`;
    sh.appendChild(s); parent.appendChild(sh); return sh; };

  /* the item under the finger / the selection, in platter (nav) coordinates: the glide's INLINE left / width (view.js's liftTo / glide() write them;
     offsetLeft would read the glide's CSS transition mid-flight, i.e. the old value on the frame the target changes) */
  const centreOf = (g) => { const l = parseFloat(g.style.left), w = parseFloat(g.style.width); return (isNaN(l) ? g.offsetLeft : l) + (isNaN(w) ? g.offsetWidth : w) / 2; };
  let loop = null;
  const attach = (nav) => {
    const glide = nav.querySelector(".glide"), seg = nav.querySelector(".seg"), main = document.getElementById("app");
    if (!glide || !seg || !main) return null;
    nav.classList.add("tlens");
    const st = { nav, glide, seg, main, X: centreOf(glide), lastX: centreOf(glide) };
    return st;
  };
  const start = (st) => {
    if (loop) { loop.stop(); }
    const nav = st.nav, glide = st.glide, main = st.main;
    const pr = nav.getBoundingClientRect(), mr = main.getBoundingClientRect(), PC = { x: pr.width / 2, y: pr.height / 2 };
    const w0 = parseFloat(glide.style.width) || glide.offsetWidth || (sets[0] || 82), h0 = glide.offsetHeight || 54;   // the resting lens = the item's box (view.js: the button's offsetWidth; 82 on the 440 screen)
    /* the element and its layers */
    const root = el("tabbar-lens tlens on", document.body, "position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;z-index:7");
    const stack = el("stack", root), base = el("base", stack), warp = el("warp", stack), disp = el("disp", warp), ish = el("ish", stack), warpl = el("warpl", stack), displ = el("displ", warpl);
    const copy = el("copy", disp), copyl = el("copy", displ), copyb = el("copy", base);
    // .base: page + platter + items (undisplaced; the fringe taps read it around the lens)
    const bPg = pageCopy(copyb, main, mr), bPl = platterCopy(copyb, main, mr, pr), bIt = itemsCopy(copyb, nav, st.seg, pr);
    // layer 1's copy: page + platter + the items outside the capsule (+ inside at 1 − DestOut)
    const pg = pageCopy(copy, main, mr), pl = platterCopy(copy, main, mr, pr), punchOut = el("punch", copy, "position:absolute;inset:0"), punchIn = el("punchin", copy, "position:absolute;inset:0");
    const itOut = itemsCopy(punchOut, nav, st.seg, pr), itIn = itemsCopy(punchIn, nav, st.seg, pr);
    // layers 2 + 4's copy: the items at 1.16 (label shell)
    const itLab = itemsCopy(copyl, nav, st.seg, pr);
    if (!FRINGE) stack.style.filter = "none";
    /* springs: p = the lift progress (everything rides it), X = the lens's model centre x */
    const P = { x: 0, v: 0 }, XS = { x: st.lastX, v: 0 };
    let pTarget = 1, running = true, last = clockNow(), t0 = last, curSet = 0, abKey = "", phase = "lift", frameN = 0;
    const glideOrigin = () => { glide.style.transformOrigin = `${PC.x - glide.offsetLeft}px ${PC.y - glide.offsetTop}px`; };   // the glide scales about the platter centre, like the platter
    const setTargets = () => { const lifted = glide.classList.contains("lift") || glide.classList.contains("lift-sel"); pTarget = lifted ? 1 : 0; st.X = centreOf(glide); phase = lifted ? (Math.abs(st.X - XS.x) > .5 ? "move" : "lift") : "drop"; glideOrigin(); };
    setTargets();
    const frame = (now) => { try { frame0(now); } catch (e) { window.__tabLensErr = String(e && e.stack || e); console.error("tab-lens frame", e); stop(); } };
    const frame0 = (now) => {
      if (!running) return;
      const dt = Math.min(1, Math.max(0, (now - last) / 1000)); last = now; frameN++;   // time-based like a CA spring (a stalled frame lands where the clock says; only a > 1 s stall is cut)
      step(P, pTarget, pTarget > .5 ? SP_LIFT : SP_DROP, dt); step(XS, st.X, SP_POS, dt);
      const p = Math.max(0, Math.min(1, P.x)), s = 1 + (PLATTER - 1) * p, x = XS.x;
      const wm = w0 + LIFT * p, hm = h0 + LIFT * p, set = setFor(Math.round(wm));
      const cx = PC.x + s * (x - PC.x), cy = PC.y, W = s * wm, H = s * hm, R = H / 2;
      const L = cx - W / 2 - AM, T = cy - H / 2 - AM;                     // the stack box in platter coordinates
      const SL = pr.left + L, ST = pr.top + T;                            // … on screen
      root.style.left = SL + "px"; root.style.top = ST + "px"; root.style.width = (W + 2 * AM) + "px"; root.style.height = (H + 2 * AM) + "px";
      root.style.setProperty("--rr", R + "px");
      for (const e of [warp, warpl, ish]) { e.style.left = AM + "px"; e.style.top = AM + "px"; e.style.width = W + "px"; e.style.height = H + "px"; }
      // the copies keep their screen positions: offsets relative to the stack box (base) / the lens box (warp, warpl)
      const off = (w, dx, dy) => { w.style.left = dx + "px"; w.style.top = dy + "px"; };
      for (const [pgw, dx, dy] of [[bPg, 0, 0], [pg, AM, AM]]) { off(pgw._m, mr.left - SL - dx, mr.top - ST - dy); }   // dx / dy = the layer's origin from the stack's (the lens layers sit AM inside)
      for (const [w, dx, dy] of [[bPl, 0, 0], [pl, AM, AM], [bIt, 0, 0], [itOut, AM, AM], [itIn, AM, AM], [itLab, AM, AM]]) off(w, -L - dx, -T - dy);
      for (const w of [bPl, pl, bIt, itOut, itIn, itLab]) w.style.transform = `scale(${s.toFixed(5)})`;
      for (const w of [bPl, pl]) w.firstElementChild.style.transform = `scale(${(1 / s).toFixed(6)})`;
      itLab.style.setProperty("--titem", (1 + (ITEM - 1) * p).toFixed(5));
      punchIn.style.opacity = (1 - p).toFixed(4);                        // DestOut #76 α 0 → 1 on the lift spring: the real items inside the capsule fade out of the capture
      punchIn.style.clipPath = `inset(0 round ${R.toFixed(3)}px)`;
      punchOut.style.clipPath = `path(evenodd, "M0 0H${W.toFixed(3)}V${H.toFixed(3)}H0Z M${R.toFixed(3)} 0H${(W - R).toFixed(3)}A${R.toFixed(3)} ${R.toFixed(3)} 0 0 1 ${(W - R).toFixed(3)} ${H.toFixed(3)}H${R.toFixed(3)}A${R.toFixed(3)} ${R.toFixed(3)} 0 0 1 ${R.toFixed(3)} 0Z")`;
      if (set !== curSet) { curSet = set; disp.style.filter = `url(#tab-lens-f-bg-${set})`; displ.style.filter = `url(#tab-lens-f-lab-${set})`; if (FRINGE) stack.style.filter = document.getElementById(`tab-lens-f-ab-${set}`) ? `url(#tab-lens-f-ab-${set})` : "none"; }
      for (const id of [`tab-lens-f-bg-${set}`, `tab-lens-f-lab-${set}`]) { const fd = document.querySelector(`#${id} feDisplacementMap`); if (fd) fd.setAttribute("scale", (sOf(id) * p * s).toFixed(3)); }
      if (FRINGE) {                                                       // layer 5: W/H = the capture box (lens screen frame ± 100 clamped to the screen), taps ±S_ab·k × p × s
        const f = document.getElementById(`tab-lens-f-ab-${set}`);
        if (f) { const l0 = SL + AM, t0s = ST + AM, wh = (Math.min(l0 + W + 100, innerWidth) - Math.max(l0 - 100, 0)) / (Math.min(t0s + H + 100, innerHeight) - Math.max(t0s - 100, 0));
          const key = `${set}|${wh.toFixed(4)}|${(p * s).toFixed(4)}`;
          if (key !== abKey) { abKey = key; const m = f.querySelector(`#tab-lens-f-ab-${set}-wh`); if (m) m.setAttribute("values", `${wh.toFixed(4)} 0 0 0 ${(0.5 * (1 - wh)).toFixed(4)}  0 ${(1 / wh).toFixed(4)} 0 0 ${(0.5 * (1 - 1 / wh)).toFixed(4)}  0 0 1 0 0  0 0 0 1 0`);
            const S = parseFloat(f.getAttribute("data-s")) || 16, taps = f.querySelectorAll("feDisplacementMap"), n = taps.length; taps.forEach((t, i) => t.setAttribute("scale", (S * p * s * (1 - 2 * i / (n - 1))).toFixed(3))); } }
      }
      ish.style.opacity = p.toFixed(4);
      nav.style.setProperty("--tplatter-scale", s.toFixed(5)); nav.style.setProperty("--tsel-alpha", (1 - p).toFixed(4));
      window.__tabLens = { t: (now - t0) / 1000, p, v: P.v, x, xv: XS.v, target: st.X, set, s, phase, w: W, h: H, frame: frameN };
      if (pTarget === 0 && p < .002 && Math.abs(P.v) < .02 && Math.abs(XS.x - st.X) < .05) { stop(); return; }
      tick(frame);
    };
    const stop = () => { running = false; root.remove(); nav.style.removeProperty("--tplatter-scale"); nav.style.removeProperty("--tsel-alpha"); glide.style.removeProperty("transform-origin"); if (loop && loop.stop === stop) loop = null; window.__tabLens = null; };
    loop = { stop, retarget: setTargets, st };
    tick(frame);
  };

  /* watch the page's own state: the glide's classes and inline box (view.js's liftTo / glide()), the bar's rebuilds (every render replaces nav's children) */
  let st = null;
  const onMut = (muts) => {
    const nav = document.getElementById("tabs"); if (!nav || !ready) return;
    let rebuilt = false, glideChanged = false;
    for (const m of muts) { if (m.type === "childList" && m.target === nav) rebuilt = true; else if (m.type === "attributes" && m.target !== nav && m.target.classList && m.target.classList.contains("glide") && !(m.attributeName === "style" && loop && m.target.style.transformOrigin && m.oldValue === null)) glideChanged = true; }
    if (rebuilt || !st || st.nav !== nav || st.glide !== nav.querySelector(".glide")) { if (loop) loop.stop(); st = attach(nav); if (!st) return; }
    if (!glideChanged) return;
    const g = st.glide, lifted = g.classList.contains("lift") || g.classList.contains("lift-sel"), cur = centreOf(g);
    if (loop) { loop.retarget(); st.X = cur; return; }                            // a retarget while running: the item under the finger moved / the selection landed
    if (lifted) { st.lastX = st.X; start(st); }                                   // the lift begins from the resting centre the glide had before this mutation
    st.X = cur;
  };
  const mo = new MutationObserver((muts) => { try { onMut(muts); } catch (e) { window.__tabLensErr = String(e && e.stack || e); console.error("tab-lens", e); } });
  const init = async () => {
    await loadFilters();
    const nav = document.getElementById("tabs"); if (!nav) return;
    st = attach(nav);
    mo.observe(nav, { subtree: true, childList: true, attributes: true, attributeFilter: ["class", "style"] });   // nav itself is static; view.js rewrites its children on every render
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", init); else init();
})();
