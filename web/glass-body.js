/* glass-body.js — the glass BODY of the round glass buttons (.navbtn) and the tab bar platter: MaxLuma + the face matrix with its fill, from their own
   glassBackground keys (外观 10-01; probe: BOARD/evidence/外观-1001-圆钮/button-glassBackground-both.json, 外观-1001-标签栏/platter-glassBackground-both.json —
   the two agree on every face key): light White 1.03 / Black .4 / Saturation 1.2 / Fill (1,1,1,.2) / MaxLumaSDR .94; dark 1.125 / .125 / 1.3 / fill none / .6.
   Formulas (menu-card-material.md §7.1, alert-glass.js faceMatrix): MaxLuma k = sat(1 − (1 − MaxLumaSDR)·Y), c′ = mix(Y·k, c·k, 1 + .3(1 − k))
     = c·A(Y) − B(Y) with A = k(1.3 − .3k), B = .3·Y·k(1 − k); face = YCC⁻¹·D·YCC scaled by (1 − fill α) plus the premultiplied fill.
   Checked on six flat greys against the native body (simulator A, UIProbe `pagebg`, BOARD/evidence/外观-1001-钮体/README.md): the formula runs
   0.5–2.4 levels above the native reading on every grey, both themes (e.g. light 128 → 195.2 vs 193 / 194; dark 255 → 185 vs 183 / 184).
   Only Blink takes url() in backdrop-filter (tested: headless Chrome applies it; WebKit does not) — Blink gets the SVG chain after the CSS blur;
   WebKit (iOS: record, not fixed — user 10-01 02:15) keeps the old CSS recipe (index.html --glass-filter / --glass-fill). The switch is html.gb-svg,
   set here when the engine is not WebKit (CSS.supports mix-blend-mode plus-darker = WebKit, as accept-alert-view.js:53 / menu.js). */
(function () {
  "use strict";
  if (window.CSS && CSS.supports && CSS.supports("mix-blend-mode", "plus-darker")) return;   // WebKit: url() in backdrop-filter does nothing there
  const KEYS = { l: { W: 1.03, B: .4, S: 1.2, fill: [1, 1, 1, .2], ml: .94 }, d: { W: 1.125, B: .125, S: 1.3, fill: [0, 0, 0, 0], ml: .6 } };
  const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((acc, v, i) => acc + v * B[i][j], 0)));
  const ycc = (W, Bk, s, fill) => { const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]];
    const D = [[W - Bk, 0, 0, Bk], [0, s, 0, .5 - .5 * s], [0, 0, s, .5 - .5 * s], [0, 0, 0, 1]];
    const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]]; let M = mul(mul(INV, D), YCC);
    if (fill[3] > 0) M = M.map((row, i) => i < 3 ? row.map((v, j) => v * (1 - fill[3]) + (j === 3 ? fill[i] * fill[3] : 0)) : row);   // alert-glass.js yccMatrix, §4 ⑦
    const r = (v) => (+v.toFixed(5)).toString(); return [0, 1, 2].map((i) => `${r(M[i][0])} ${r(M[i][1])} ${r(M[i][2])} 0 ${r(M[i][3])}`).join(" ") + " 0 0 0 1 0"; };
  const lut = (fn, n = 33) => Array.from({ length: n }, (_, i) => (+fn(i / (n - 1)).toFixed(5)).toString()).join(" ");
  const chain = (id, k) => { const comp = 1 - k.ml, kOf = (Y) => Math.max(0, Math.min(1, 1 - comp * Y)), A = (Y) => { const q = kOf(Y); return q * (1.3 - .3 * q); },
      iB = (Y) => { const q = kOf(Y); return 1 - .3 * Y * q * (1 - q); }, L = ".2126 .7152 .0722 0 0";
    return `<filter id="${id}" x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB">`
      + `<feColorMatrix in="SourceGraphic" type="matrix" values="${L} ${L} ${L} 0 0 0 1 0" result="Y"/>`
      + `<feComponentTransfer in="Y" result="A"><feFuncR type="table" tableValues="${lut(A)}"/><feFuncG type="table" tableValues="${lut(A)}"/><feFuncB type="table" tableValues="${lut(A)}"/></feComponentTransfer>`
      + `<feComponentTransfer in="Y" result="iB"><feFuncR type="table" tableValues="${lut(iB)}"/><feFuncG type="table" tableValues="${lut(iB)}"/><feFuncB type="table" tableValues="${lut(iB)}"/></feComponentTransfer>`
      + `<feComposite in="SourceGraphic" in2="A" operator="arithmetic" k1="1" k2="0" k3="0" k4="0" result="cA"/>`   // c·A (α 1·1)
      + `<feComposite in="cA" in2="iB" operator="arithmetic" k1="0" k2="1" k3="1" k4="-1" result="ml"/>`   // c·A + (1 − B) − 1 = c·A − B (α 1 + 1 − 1)
      + `<feColorMatrix in="ml" type="matrix" values="${ycc(k.W, k.B, k.S, k.fill)}"/></filter>`; };
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.setAttribute("aria-hidden", "true"); svg.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
  svg.innerHTML = chain("gb-body-l", KEYS.l) + chain("gb-body-d", KEYS.d);
  /* the same chain on one flat colour (the page's) → .plat data-flat: the tab lens (assets/lens/tab-lens.js) draws the platter into its flat backdrop
     from it (it used the platter's background colour, which is none now) */
  const flat = (rgb, k) => { const Y = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2], q = Math.max(0, Math.min(1, 1 - (1 - k.ml) * Y)), t = 1.3 - .3 * q;
    const c = rgb.map((v) => v * q * t + Y * q * (1 - t)), M = ycc(k.W, k.B, k.S, k.fill).split(" ").map(Number);
    return [0, 1, 2].map((i) => Math.round(255 * Math.max(0, Math.min(1, M[i * 5] * c[0] + M[i * 5 + 1] * c[1] + M[i * 5 + 2] * c[2] + M[i * 5 + 4])))); };
  const dark = () => { const t = document.documentElement.dataset.theme; return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; };
  const mark = () => { const plat = document.querySelector("nav.tabs .plat"); if (!plat) return;
    const m = /rgba?\(([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/.exec(getComputedStyle(document.body).backgroundColor || ""), bg = m ? [+m[1] / 255, +m[2] / 255, +m[3] / 255] : [1, 1, 1];
    const v = `rgb(${flat(bg, dark() ? KEYS.d : KEYS.l).join(", ")})`; if (plat.dataset.flat !== v) plat.dataset.flat = v; };
  const put = () => { document.body.appendChild(svg); document.documentElement.classList.add("gb-svg"); mark();
    const mq = matchMedia("(prefers-color-scheme: dark)"); (mq.addEventListener ? mq.addEventListener("change", mark) : mq.addListener(mark));
    if (window.MutationObserver) { const nav = document.getElementById("tabs"); if (nav) new MutationObserver(mark).observe(nav, { childList: true });
      new MutationObserver(mark).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] }); } };
  if (document.body) put(); else document.addEventListener("DOMContentLoaded", put);
  window.GlassBody = { KEYS, chain, flat, mark };
})();
