/* lens-supersample.js — 引擎校正 2 (candidate A of README §0.4), default ON, one line to include:
     <script src="assets/lens/lens-supersample.js"></script>   right after the <svg> with the lens filters, BEFORE view.js and lens-engine-fix.js
   Off: ?ss=0 in the URL, or window.LENS_SS = 1 before this script; SS = 2 otherwise (window.LENS_SS is set for lens-engine-fix.js).
   Engine facts (calib/, README §0.4): WebKit's software feDisplacementMap works on a buffer at the layer's raster scale and fetches the
   source nearest-neighbour at that pixel; a filtered layer laid out SS× larger inside a composited wrapper scaled 1/SS is rasterised
   SS× finer and CA downsamples it (2×2 box at SS 2), halving the displacement quantum and the negative-lane shortfall and blending
   the row-parallel hard blocks of a displaced edge. Under a scaled ancestor WebKit resolves a filter's objectBoundingBox region in
   UNSCALED units, so the region must be 100/SS % (calib/webkit-region-under-scale.html).
   What it does, for every filtered lens layer (the targets: the segment page's .warp .disp / .warpl .displ, the test page's .layer.bg /
   .layer.lab, the tab equivalents), also when they are created later (MutationObserver):
     container C  (the layer's slot, W×H, its own clip-path / opacity / --rr untouched)
       └ .ssw      inset 0 of C, transform-origin 0 0, transform scale3d(1/SS,1/SS,1), will-change: transform   (composited)
           └ E     the filtered element itself, moved in: left/top 0, width/height SS×100 %, border-radius × SS (calc on --rr); its
                   style.filter keeps being set per frame by the page
               └ .ss2  100/SS % of E, transform scale(SS), origin 0 0 — E's former children, positioned exactly as before
   and for every lens filter definition (#seg-lens-f-bg-*, -lab-*, #tab-lens-f-bg-*, -lab-*): width/height = 100/SS %, data-s0 = the
   file's S, data-s = S × SS (a map pt is SS layer px; view.js's sOf(id) then writes scale = data-s × progress), the resting scale
   attribute × SS. Not the fringe chains (-ab-). The map files, lens-filter.svg and the formulas are untouched. */
(function () {
  const q = new URLSearchParams(location.search);
  const SS = q.get("ss") === "0" ? 1 : (window.LENS_SS && window.LENS_SS > 0 ? window.LENS_SS : 2);
  window.LENS_SS = SS;
  if (SS === 1) { window.LENS_SS_DONE = true; return; }
  const me = document.currentScript;
  const TARGETS = (me && me.dataset.targets) || ".segctl .warp .disp, .segctl .warpl .displ, .tabbar-lens .disp, .tabbar-lens .displ, .lens .layer.bg, .lens .layer.lab";
  const FILTERS = 'filter[id^="seg-lens-f-bg-"], filter[id^="seg-lens-f-lab-"], filter[id^="tab-lens-f-bg-"], filter[id^="tab-lens-f-lab-"]';
  const fixFilters = () => {
    for (const f of document.querySelectorAll(FILTERS)) {
      if (f.dataset.s0) continue;
      const S = parseFloat(f.dataset.s) || 40; f.dataset.s0 = String(S); f.dataset.s = String(S * SS);
      f.setAttribute("width", `${100 / SS}%`); f.setAttribute("height", `${100 / SS}%`);
      const fe = f.querySelector("feDisplacementMap"); if (fe) fe.setAttribute("scale", String(parseFloat(fe.getAttribute("scale")) * SS));
    }
  };
  const wrap = (E) => {
    if (E.dataset.ss || !E.parentElement) return;
    E.dataset.ss = String(SS);
    const C = E.parentElement;
    const w = document.createElement("div"); w.className = "ssw"; w.style.cssText = `position:absolute;left:0;top:0;width:100%;height:100%;transform-origin:0 0;transform:scale3d(${1 / SS},${1 / SS},1);will-change:transform;pointer-events:none`;
    const inner = document.createElement("div"); inner.className = "ss2"; inner.style.cssText = `position:absolute;left:0;top:0;width:${100 / SS}%;height:${100 / SS}%;transform-origin:0 0;transform:scale(${SS})`;
    while (E.firstChild) inner.appendChild(E.firstChild);
    E.appendChild(inner);
    E.style.left = "0"; E.style.top = "0"; E.style.right = "auto"; E.style.bottom = "auto"; E.style.width = `${100 * SS}%`; E.style.height = `${100 * SS}%`;
    const br = getComputedStyle(E).borderRadius; if (br && br !== "0px") E.style.borderRadius = `calc(var(--rr, ${br}) * ${SS})`;
    C.insertBefore(w, E); w.appendChild(E);
  };
  const run = () => { fixFilters(); for (const E of document.querySelectorAll(TARGETS)) wrap(E); };
  const mo = new MutationObserver((muts) => { let hit = false; for (const m of muts) for (const n of m.addedNodes) if (n.nodeType === 1) { hit = true; break; } if (hit) run(); });
  const start = () => { run(); mo.observe(document.documentElement, { childList: true, subtree: true }); window.LENS_SS_DONE = true; };
  window.LENS_SS_APPLY = run;
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", start); else start();
})();
