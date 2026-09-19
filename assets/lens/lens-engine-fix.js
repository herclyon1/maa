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
  const fix = async (fe) => {
    const filter = fe.closest("filter"); if (!filter || /-ab-/.test(filter.id)) return;
    const S = parseFloat(filter.dataset.s); const href = fe.getAttribute("href") || fe.getAttributeNS("http://www.w3.org/1999/xlink", "href");
    if (!(S > 0) || !href || href.startsWith("blob:")) return;
    const ssHere = filter.dataset.s0 ? 1 : ss;                    /* lens-supersample.js already folded SS into data-s (data-s0 = the file's S) */
    const blob = await (await fetch(href)).blob(); const bmp = await createImageBitmap(blob);
    const cv = document.createElement("canvas"); cv.width = bmp.width; cv.height = bmp.height;
    const ctx = cv.getContext("2d", { willReadFrequently: true }); ctx.drawImage(bmp, 0, 0);
    const im = ctx.getImageData(0, 0, cv.width, cv.height), d = im.data, step = k * 255 / (S * ssHere);
    for (let i = 0; i < d.length; i += 4) { if (d[i] < 128) d[i] = Math.max(0, Math.round(d[i] - step)); if (d[i + 1] < 128) d[i + 1] = Math.max(0, Math.round(d[i + 1] - step)); }
    ctx.putImageData(im, 0, 0);
    const url = URL.createObjectURL(await new Promise((r) => cv.toBlob(r, "image/png")));
    fe.setAttribute("href", url); fe.dataset.engineFixed = String(k);
  };
  const run = () => Promise.all([...document.querySelectorAll("filter[data-s] feImage")].map((fe) => fix(fe).catch((e) => console.warn("lens-engine-fix", fe, e))))
    .then(() => { window.LENS_ENGINE_FIX_DONE = true; dispatchEvent(new CustomEvent("lens-engine-fix")); });
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", run); else run();
})();
