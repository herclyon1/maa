/* lens-map-dpr.js — 引擎校正 BAKED INTO THE MAP FILES (the alternative to lens-engine-fix.js's run-time blob: re-encoding; 验收 2026-09-19, README
   §0.8.4). gen_lens_maps.py --engine-fix-sets 2,3 writes every bg / lab map twice more: <map>@2x.png with k = ½ pt and <map>@3x.png with
   k = ⅓ pt taken off every NEGATIVE displacement before encoding (the engine fact of README §0.4 / calib: WebKit applies a negative
   displacement one device pixel short), and marks the filter data-baked="2,3". This script points each such filter's feImage at the file
   for the device (devicePixelRatio 2 → @2x, 3 → @3x; other ratios, or lens-supersample.js active with SS > 1 (the shortfall is then
   1/(ratio·SS) pt and no file exists for it), keep the plain file and the run-time fix) and marks it data-engine-baked, which
   lens-engine-fix.js honours (it leaves the feImage alone). One line, BEFORE lens-engine-fix.js:
     <script src="assets/lens/lens-map-dpr.js"></script>
   Filters added later (tab-lens.js) call window.LENS_MAP_DPR_APPLY(). Not the fringe maps (-f-ab-). ?mapdpr=0 turns it off. */
(function () {
  const q = new URLSearchParams(location.search);
  if (q.get("mapdpr") === "0") return;
  const run = () => {
    const ratio = Math.round(window.devicePixelRatio || 1) * (window.LENS_SS || 1);
    for (const f of document.querySelectorAll("filter[data-baked]")) {
      if (/-f-ab/.test(f.id)) continue;
      const have = String(f.dataset.baked).split(",").map((v) => parseInt(v, 10));
      if (!have.includes(ratio)) continue;
      for (const fe of f.querySelectorAll("feImage")) {
        const href = fe.getAttribute("href") || fe.getAttributeNS("http://www.w3.org/1999/xlink", "href");
        if (!href || /@\dx\.png$/.test(href) || href.startsWith("blob:")) continue;
        fe.setAttribute("href", href.replace(/\.png$/, `@${ratio}x.png`)); fe.dataset.engineBaked = String(1 / ratio);
      }
    }
    window.LENS_MAP_DPR_RATIO = ratio;
  };
  window.LENS_MAP_DPR_APPLY = run;
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", run); else run();
})();
