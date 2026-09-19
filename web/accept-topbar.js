/* accept-topbar.js — acceptance for the top bar's scroll behaviour (BOARD.md #4, topbar.js / topbar.css; remote-ref/nav-bar-scroll-formula.md).
   Registers through ACCEPT.add(ctx): ctx.check(item, expect, got, ok) / ctx.num(item, expect, got, tol) / ctx.col(item, [r,g,b,a], got).
   The checks scroll the page programmatically and read the CSS variables topbar.js sets and the titles' computed styles. */
window.ACCEPT && ACCEPT.add(async (ctx) => {
  const { check, num, col, sleep } = ctx;
  const T = window.Topbar, root = document.documentElement, cs = (el, ps) => getComputedStyle(el, ps || null);
  const h1 = document.querySelector("header h1"), small = document.querySelector("#topbar span");
  check("顶栏 topbar.js 接管（window.Topbar 在）", "true", String(!!T), !!T);
  if (!T || !h1 || !small) return;
  const v = (n) => parseFloat(root.style.getPropertyValue(n)) || 0;
  const y0 = window.scrollY;
  const go = async (y) => { window.scrollTo(0, y); await sleep(60); T.apply(); await sleep(260); };   // 0.2 s opacity transitions settle
  const p = T.p, B = T.B, sw = 0.95 * (p - B);
  const snapWas = T.snap; T.snap = false;   // the release snap (2.8) would move the programmatic scrolls to a resting point mid-check
  num("折叠范围 p = 大标题底 − 栏底（探针 §10：106−54 = 52 的页面等价）", p, p, 0.01);
  /* progress formula (2.4): c = p − s, (c − b)/(p − b), b 14 */
  num("progress(s=0) = 1（2.4）", 1, T.progressOf(0), 0.001);
  num(`progress(s = p − b = ${(p - B).toFixed(1)}) = 0（2.4：c ≤ 0 ... c = b → 0）`, 0, T.progressOf(p - B), 0.001);
  num(`progress(s = ${(p / 2).toFixed(1)}) = ((p/2) − b)/(p − b)`, (p / 2 - B) / (p - B), T.progressOf(p / 2), 0.001);
  /* rest: large title alpha 1, small 0, no edge line, no clip */
  await go(0);
  num("静止：大标题 alpha 1（§4 item 1 不淡出）", 1, parseFloat(cs(h1).opacity), 0.01);
  num("静止：小标题 alpha 0", 0, parseFloat(cs(small).opacity), 0.01);
  num("静止：栏底线 --tb-edge 0（§3 shouldHideAtTop）", 0, v("--tb-edge"), 0.001);
  num("静止：裁切 0", 0, parseFloat(root.style.getPropertyValue("--tb-clip")) || 0, 0.01);
  num("静止：拉伸 1", 1, v("--tb-stretch"), 0.0001);
  /* under the bar but before the switch: still alpha 1, clipped, edge line on */
  const s1 = Math.max(1, Math.min(sw - 6, p - B - 2));
  await go(s1);
  num(`滚 ${s1.toFixed(1)}（切换前）：大标题 alpha 仍 1`, 1, parseFloat(cs(h1).opacity), 0.01);
  num(`滚 ${s1.toFixed(1)}：小标题 alpha 仍 0`, 0, parseFloat(cs(small).opacity), 0.01);
  num(`滚 ${s1.toFixed(1)}：栏底线 --tb-edge 1`, 1, v("--tb-edge"), 0.001);
  check(`滚 ${s1.toFixed(1)}：大标题被栏底裁切（--tb-clip > 0）`, "> 0", root.style.getPropertyValue("--tb-clip"), (parseFloat(root.style.getPropertyValue("--tb-clip")) || 0) > 0);
  /* the switch: progress < 0.05 ⇔ s > 0.95 (p − b) — one side, then the other */
  await go(sw - 1);
  num(`滚 ${(sw - 1).toFixed(1)}（阈值前 1 pt）：小标题 0`, 0, parseFloat(cs(small).opacity), 0.01);
  await go(sw + 1);
  num(`滚 ${(sw + 1).toFixed(1)}（阈值后 1 pt，2.5 progress < .05）：小标题 1`, 1, parseFloat(cs(small).opacity), 0.01);
  num(`滚 ${(sw + 1).toFixed(1)}：大标题 0`, 0, parseFloat(cs(h1).opacity), 0.01);
  check("切换过渡 0.2 s（2.5；小标题 transition-duration）", "0.2s", cs(small).transitionDuration, /^0\.2s/.test(cs(small).transitionDuration));
  check("切换过渡 0.2 s（大标题）", "0.2s", cs(h1).transitionDuration, /^0\.2s/.test(cs(h1).transitionDuration));
  check("小标题无位移（§6 item 8：只 alpha）", "none", cs(small).transform, cs(small).transform === "none");
  /* release snap (2.8): nearest resting point by the midpoint */
  num("松手吸附 s = p/2 − 1 → 0", 0, T.snapTarget(p / 2 - 1), 0.001);
  num("松手吸附 s = p/2 + 1 → p", p, T.snapTarget(p / 2 + 1), 0.001);
  /* pull-down stretch (2.7): clamp(1 + over/(dpr × screenH × .66), 1, 1.1) */
  const k = devicePixelRatio * screen.height * 0.66;
  num("拉伸 over 0 → 1", 1, T.stretchOf(0), 0.0001);
  num(`拉伸 over ${(k * 0.05).toFixed(1)} → 1.05`, 1.05, T.stretchOf(k * 0.05), 0.0005);
  num(`拉伸 over ${(k * 0.3).toFixed(1)} → 封顶 1.1`, 1.1, T.stretchOf(k * 0.3), 0.0001);
  /* 真机坑 (A6, the applicable ones): the edge line follows the theme token; the old view.js entry is guarded off */
  const line = getComputedStyle(document.querySelector("#topbar"), "::after").backgroundColor;
  const probe = document.createElement("i"); probe.style.cssText = "position:fixed;left:-9999px;top:0;color:var(--line)"; document.body.appendChild(probe);
  check("栏底线颜色 = 令牌 --line（切主题后跟令牌）", cs(probe).color, line, line === cs(probe).color); probe.remove();
  await go(sw + 1);
  check("旧入口 view.js onScroll 已让位（--big 不再由它驱动：为空或 0）", "空/0", root.style.getPropertyValue("--big") || "空", !(parseFloat(root.style.getPropertyValue("--big")) > 0));
  T.snap = snapWas; window.scrollTo(0, y0); await sleep(60); T.apply();
});
