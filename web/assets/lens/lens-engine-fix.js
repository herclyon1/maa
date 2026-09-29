/* lens-engine-fix.js — 引擎校正 (engine correction) for the lens displacement maps, default ON (监督局 2026-09-19 08:4x).
   Engine fact (calib/, 2026-09-19): WebKit's feDisplacementMap quantises the displacement to the filter buffer's pixel (one device
   pixel: ½ CSS px at devicePixelRatio 2 — Mac WebKit / wksnap; ⅓ at 3 — the iOS simulator, standalone window) and applies a NEGATIVE
   value one pixel short (truncated toward zero, then −1 px: −1 → −0.5 / −0.67, −4 → −3.5 / −3.67, −12 → −11.5 / −11.67), a
   positive value rounded up to the next pixel (+1.25 → 1.5 / 1.33). Readings: README §0.4 (Mac 2× from wksnap; iOS 3× from the data
   session's tools/touch/calib-sim-3x.txt). Nothing else is off: a constant map decodes to its value on both engines (no zero-point
   offset, no linearRGB decode of the map).
   What this does: for every lens filter (`filter[data-s]`, not the fringe chains `-ab-`, whose seven taps read one map with positive
   and negative scales) it re-encodes the map's R and G channels so that every negative displacement is longer by exactly one device
   pixel (k = 1 / devicePixelRatio CSS px): byte' = byte − k·255/S for byte < 128 — the engine's truncation then lands on the map's
   value (still quantised to its pixel, like the positive side). The map files are untouched (their bytes are the formula's values,
   gen_lens_maps.py); the corrected copies live in blob: URLs for this page load only. The B channel (coverage) is not touched.
   Apply after the <svg> with the filters is in the DOM (and after window.LENS_SS is set when the page supersamples the layers,
   引擎校正 2: then the shortfall is one pixel of the ss× layer = 1/(devicePixelRatio·ss) pt); index.html and lens-test.html load it. Switch: <script data-engine-fix="off">
   or window.LENS_ENGINE_FIX = false before this script; the applied k is exposed as window.LENS_ENGINE_FIX_K. */
(function () {
  const me = document.currentScript;
  if (window.LENS_ENGINE_FIX === false || (me && me.dataset.engineFix === "off")) { window.LENS_ENGINE_FIX_K = 0; return; }
  const k = 1 / (window.devicePixelRatio || 1);                 /* one device pixel, in CSS px of the filtered layer */
  const ss = window.LENS_SS || 1;                                 /* 引擎校正 2: the layer is laid out ss× larger (README §0.4), so a map pt is ss layer px and the encoding scale in layer px is data-s × ss */
  window.LENS_ENGINE_FIX_K = k / ss;                              /* the shortfall in pt */
  /* The re-encoding (fetch → decode → getImageData → per-pixel loop → PNG) runs in a Worker on an OffscreenCanvas when the browser has one:
     on the main thread it took 305 ms of the first second at the user's phone speed (Chrome 394×790 dpr 3.25, CPU ×4: frames of 75–119 ms
     at load, all in this loop). Same steps, same bytes; the main thread only swaps the href. Without OffscreenCanvas, or when the worker
     fails, the main-thread path below does it as before. */
  const recode = (d, step) => {
    for (let i = 0; i < d.length; i += 4) { if (d[i] < 128) d[i] = Math.max(0, Math.round(d[i] - step)); if (d[i + 1] < 128) d[i + 1] = Math.max(0, Math.round(d[i + 1] - step)); }
  };
  const onMain = async (href, step) => {
    via.main++;
    const blob = await (await fetch(href)).blob(); const bmp = await createImageBitmap(blob);
    const cv = document.createElement("canvas"); cv.width = bmp.width; cv.height = bmp.height;
    const ctx = cv.getContext("2d", { willReadFrequently: true }); ctx.drawImage(bmp, 0, 0);
    const im = ctx.getImageData(0, 0, cv.width, cv.height); recode(im.data, step);
    ctx.putImageData(im, 0, 0);
    return new Promise((r) => cv.toBlob(r, "image/png"));
  };
  let worker = null, seq = 0; const pending = {}; const via = window.LENS_ENGINE_FIX_VIA = { worker: 0, main: 0, errors: [] };   /* instrument: where each map was re-encoded */
  const offMain = (href, step) => {
    if (worker === false) return onMain(href, step);
    if (!worker) {
      try {
        const src = `const recode = ${recode};
onmessage = async (e) => {
  const { id, href, step } = e.data;
  try {
    const bmp = await createImageBitmap(await (await fetch(href)).blob());
    const cv = new OffscreenCanvas(bmp.width, bmp.height), ctx = cv.getContext("2d", { willReadFrequently: true }); ctx.drawImage(bmp, 0, 0);
    const im = ctx.getImageData(0, 0, cv.width, cv.height); recode(im.data, step); ctx.putImageData(im, 0, 0);
    postMessage({ id, blob: await cv.convertToBlob({ type: "image/png" }) });
  } catch (err) { postMessage({ id, error: String(err) }); }
};`;
        worker = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
        worker.onmessage = (e) => { const p = pending[e.data.id]; if (!p) return; delete pending[e.data.id]; if (e.data.blob) { via.worker++; p.ok(e.data.blob); } else { via.errors.push(e.data.error); onMain(p.href, p.step).then(p.ok, p.no); } };   /* a failed map: redo it on the main thread */
        worker.onerror = (e) => { via.errors.push("worker: " + (e.message || "error")); worker.terminate(); worker = false; for (const id in pending) { const p = pending[id]; delete pending[id]; onMain(p.href, p.step).then(p.ok, p.no); } };   /* no worker: everything waiting goes back to the main thread */
      } catch (e) { worker = false; return onMain(href, step); }
    }
    return new Promise((ok, no) => { const id = ++seq; pending[id] = { href, step, ok, no }; worker.postMessage({ id, href: new URL(href, document.baseURI).href, step });
      setTimeout(() => { const p = pending[id]; if (!p) return; delete pending[id]; via.errors.push("timeout"); onMain(href, step).then(ok, no); }, 8000); });   /* a worker that never answers must not hold the tab lens (tab-lens.js awaits this run) */   /* absolute: the worker's base is its blob: URL */
  };
  /* The href swaps go out a few per frame (8 ms budget): the worker's answers arrive in bursts (it is not slowed with the page), and each swap
     re-resolves the filter — 62 in one task made a 44–75 ms frame at CPU ×4. */
  const swapQ = []; let swapping = false;
  const later = (f) => (document.hidden ? setTimeout(f, 0) : requestAnimationFrame(f));   /* a hidden page gets no frames */
  const swap = () => { const t0 = performance.now(); while (swapQ.length && performance.now() - t0 < 8) swapQ.shift()(); if (swapQ.length) later(swap); else swapping = false; };
  const fix = async (fe) => {
    const filter = fe.closest("filter"); if (!filter || /-f-ab/.test(filter.id)) return;   /* not the fringe chains: -f-ab-, -f-ab-ir-, -f-abl- */
    const S = parseFloat(filter.dataset.s); const href = fe.getAttribute("href") || fe.getAttributeNS("http://www.w3.org/1999/xlink", "href");
    if (!(S > 0) || !href || href.startsWith("blob:") || fe.dataset.engineBaked) return;   /* data-engine-baked: lens-map-dpr.js already points at a file with the correction baked in */
    const ssHere = filter.dataset.s0 ? 1 : ss;                    /* lens-supersample.js already folded SS into data-s (data-s0 = the file's S) */
    const step = k * 255 / (S * ssHere);
    const png = typeof OffscreenCanvas === "function" && typeof Worker === "function" ? await offMain(href, step) : await onMain(href, step);
    await new Promise((done) => { swapQ.push(() => {
      const url = URL.createObjectURL(png);
      fe.dataset.hrefOrig = href; fe.setAttribute("href", url); fe.dataset.engineFixed = String(k);   /* data-href-orig: the file (lens-webgl.js samples the plain map) */
      done(); }); if (!swapping) { swapping = true; later(swap); } });
  };
  const run = () => Promise.all([...document.querySelectorAll("filter[data-s] feImage")].map((fe) => fix(fe).catch((e) => console.warn("lens-engine-fix", fe, e))))
    .then(() => { window.LENS_ENGINE_FIX_DONE = true; dispatchEvent(new CustomEvent("lens-engine-fix")); });
  window.LENS_ENGINE_FIX_APPLY = run;                            /* for filters added later (tab-lens.js loads its family's <svg> by fetch): re-run; blob: hrefs are skipped */
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", run); else run();
})();
