/* motion.js — the page's shared motion primitives (BOARD.md #1, 2026-09-19): the three pieces the device checks of B14 settled
   (remote-ref/tools/touch/b14-cell-{8bf3bcd,65850cb}.md, seg-webgl-c6c35aa.md), pulled out of controls.js so every control uses ONE copy.
   Global `window.Motion`; referenced lazily (inside handlers), so the script order among the control files does not matter.
   - spring(s, target, [zeta, response], dt): one closed-form step of x'' = −ω²(x − target) − 2ζωx', ω = 2π / response, from the current
     value / velocity (s = {x, v}); ζ < 1 underdamped, ζ ≥ 1 critical — the same formula as view.js springStep (flex-interaction.md §6).
   - afterPaint(fn): rAF → rAF. A rAF callback runs before its frame's paint, so a callback nested in a second rAF runs only after the first
     frame was painted; a setTimeout(0) after a rAF is NOT guaranteed to wait for the paint on the device (数据 3ecf176 check).
   - swallowNextClick(el, ms): the browser's own click for a touch the page already handled arrives 40–60 ms after the up on Android
     (数据 seg-webgl-c6c35aa.md ①), long after any 0-ms flag; the element carries data-rc until that click is swallowed, or ms.
   - click(el): the click the page fires itself (never swallowed). */
(() => {
  "use strict";
  const spring = (s, target, [zeta, response], dt) => {
    if (!(dt > 0)) return s;
    const w = 2 * Math.PI / response, dx = s.x - target, v = s.v;
    if (zeta < 1) {
      const wd = w * Math.sqrt(1 - zeta * zeta), B = (v + zeta * w * dx) / wd, e = Math.exp(-zeta * w * dt), c = Math.cos(wd * dt), sn = Math.sin(wd * dt);
      s.x = target + e * (dx * c + B * sn); s.v = e * (-zeta * w * (dx * c + B * sn) + (-dx * wd * sn + B * wd * c));
    } else {
      const e = Math.exp(-w * dt), B = v + w * dx; s.x = target + e * (dx + B * dt); s.v = e * (B - w * (dx + B * dt));
    }
    return s;
  };
  const afterPaint = (fn) => requestAnimationFrame(() => requestAnimationFrame(fn));
  let synthetic = false;
  const swallowNextClick = (el, ms = 700) => { el.dataset.rc = "1"; setTimeout(() => { delete el.dataset.rc; }, ms); };
  const click = (el) => { synthetic = true; try { el.click(); } finally { synthetic = false; } };
  document.addEventListener("click", (e) => {
    if (synthetic) return;
    const el = e.target.closest && e.target.closest("[data-rc]");
    if (el) { delete el.dataset.rc; e.preventDefault(); e.stopImmediatePropagation(); }   // the browser's click for a press the page handled
  }, true);
  window.Motion = { spring, afterPaint, swallowNextClick, click, isSynthetic: () => synthetic };
})();
