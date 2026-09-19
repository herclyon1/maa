/* accept-nav.js — push / pop of #subpage against nav-native-formula.md §0 (BOARD.md #2): the one spring ζ 1 / .3 drives the new page's x,
   the old page's parallax, the dimming and the nav items; rest states are index.html's classes. Samples are the last rAF tick's values,
   so each is accepted if it matches the closed form at t, t − 17 or t − 33 ms (frame granularity). */
ACCEPT.add(async function nav({ check, num, sleep }) {
  const N = window.Nav, pg = document.querySelector("#subpage");
  check("nav.js：window.Nav 接管 openPage（view.js 首行守卫）", "Nav.open", N && typeof N.open === "function" ? "Nav.open" : "缺", !!N && typeof N.open === "function" && !!pg);
  if (!N || !pg) return;
  const W = window.innerWidth, crit = (t) => { const u = 2 * Math.PI / .3 * t; return t <= 0 ? 0 : 1 - (1 + u) * Math.exp(-u); };
  const near3 = (want, got, tol) => { const a = want(0), b = want(.034); return got >= Math.min(a, b) - tol && got <= Math.max(a, b) + tol; };   // the sample is the last tick's value: anywhere within the last two frames of the closed form
  const tx = (el) => { const m = getComputedStyle(el).transform; if (!m || m === "none") return 0; const a = m.match(/matrix\(([^)]+)\)/); return a ? parseFloat(a[1].split(",")[4]) : 0; };
  const main = document.querySelector("body > main"), header = document.querySelector("body > header");
  const tr = (el) => { const v = getComputedStyle(el).translate; if (!v || v === "none") return 0; return parseFloat(v); };
  const tOpen = performance.now(); const back = N.open("验收", "<section><div class=\"group\"><div class=\"row\"><label>x</label></div></div></section>");
  await sleep(100);
  check("推入：open() 到弹簧第一帧的延迟（只报不判；真机首帧延迟另计）", "ms", Math.round((N.state.first || performance.now()) - tOpen) + " ms", true);
  { const t0 = N.state.t0; const el = (performance.now() - t0) / 1000, x = tx(pg), dim = parseFloat(getComputedStyle(document.querySelector(".nav-dim")).opacity), from = tr(main);
    check(`推入 +${Math.round(el * 1000)} ms：新页 x = W(1 − p)，p = 1 − (1 + ωt)e^{−ωt}，ω 20.94（.1 s → 62 %：x ≈ ${Math.round(W * (1 - crit(el)))}）`, `${Math.round(W * (1 - crit(el)))} ± 6（前 2 帧内）`, Math.round(x), near3((d) => W * (1 - crit(el - d)), x, 6));
    check(`推入 +${Math.round(el * 1000)} ms：旧页视差 x = −(W − round(.7 W))·p（−132·p）`, `${Math.round(-(W - Math.round(.7 * W)) * crit(el))} ± 3`, Math.round(from), near3((d) => -(W - Math.round(.7 * W)) * crit(el - d), from, 3));
    check(`推入 +${Math.round(el * 1000)} ms：暗幕 alpha = p（黑 .1）`, `${crit(el).toFixed(2)} ± .03`, dim.toFixed(2), near3((d) => crit(el - d), dim, .03) && getComputedStyle(document.querySelector(".nav-dim")).backgroundColor === "rgba(0, 0, 0, 0.1)");
    const p = N.state.p, title = pg.querySelector(".ptitle"), want = N.fIn(N.u2(p));
    check("推入中：新页标题 / 返回钮 alpha = f_in(u₂)，f_in = cubic-bezier(.75,.1,.75,.1)，u₂ 段 [.425, 1]", want.toFixed(3), parseFloat(getComputedStyle(title).opacity).toFixed(3), Math.abs(parseFloat(getComputedStyle(title).opacity) - want) < .02 && Math.abs(parseFloat(getComputedStyle(pg.querySelector(".pback")).opacity) - want) < .02);
    check("推入中：过渡卡片圆角 62 / 影 r12 α.04 (0,−3)（_UIParallaxTransitionCardView）", "62px, 0 -3px 12px α.04", `${getComputedStyle(pg).borderTopLeftRadius}, ${getComputedStyle(pg).boxShadow.slice(0, 40)}`, getComputedStyle(pg).borderTopLeftRadius === "62px" && /rgba\(0, 0, 0, 0\.04\) 0px -3px 12px/.test(getComputedStyle(pg).boxShadow)); }
  await sleep(100);
  { const t0 = N.state.t0; const el = (performance.now() - t0) / 1000, x = tx(pg); check(`推入 +${Math.round(el * 1000)} ms：新页 x（.2 s → 92 %）`, `${Math.round(W * (1 - crit(el)))} ± 6`, Math.round(x), near3((d) => W * (1 - crit(el - d)), x, 6)); }
  await sleep(450);
  check("推入落定：.page.in、body.pushed、驱动类去掉、暗幕 0、transform none / 恒等", "in pushed rest 0", `${pg.classList.contains("in") ? "in" : "-"} ${document.body.classList.contains("pushed") ? "pushed" : "-"} ${pg.classList.contains("nav-live") ? "live" : "rest"} ${getComputedStyle(document.querySelector(".nav-dim")).opacity} tf=${getComputedStyle(pg).transform}`, pg.classList.contains("in") && document.body.classList.contains("pushed") && !pg.classList.contains("nav-live") && /^(none|matrix\(1, 0, 0, 1, 0, 0\))$/.test(getComputedStyle(pg).transform) && parseFloat(getComputedStyle(document.querySelector(".nav-dim")).opacity) === 0);
  back();
  await sleep(100);
  { const t1 = N.state.t0; const el = (performance.now() - t1) / 1000, x = tx(pg), from = tr(main);
    check(`返回 +${Math.round(el * 1000)} ms：顶页 x = W·p′（同一弹簧，角色互换）`, `${Math.round(W * crit(el))} ± 6`, Math.round(x), near3((d) => W * crit(el - d), x, 6));
    check(`返回 +${Math.round(el * 1000)} ms：下页视差 −132·(1 − p′)`, `${Math.round(-(W - Math.round(.7 * W)) * (1 - crit(el)))} ± 3`, Math.round(from), near3((d) => -(W - Math.round(.7 * W)) * (1 - crit(el - d)), from, 3));
    const p = N.state.p, want = 1 - N.fOut(N.u1(1 - p));
    check("返回中：顶页标题 / 返回钮 alpha = 1 − f_out(u₁)，f_out = cubic-bezier(.25,.9,.25,.9)，u₁ 段 [0, .575]", want.toFixed(3), parseFloat(getComputedStyle(pg.querySelector(".ptitle")).opacity).toFixed(3), Math.abs(parseFloat(getComputedStyle(pg.querySelector(".ptitle")).opacity) - want) < .02); }
  await sleep(550);
  check("返回落定：页 hidden、body.pushed 去掉、视差 0", "hidden, -, 0", `${pg.hidden ? "hidden" : "shown"}, ${document.body.classList.contains("pushed") ? "pushed" : "-"}, ${tr(main)}`, pg.hidden && !document.body.classList.contains("pushed") && Math.abs(tr(main)) < .5);
  /* interrupt: pop while the push is mid-flight continues from the current p / v (no jump) */
  const t2 = performance.now(); N.open("验收", "<p>y</p>"); await sleep(120); const pMid = N.state.p, xMid = tx(pg); N.back(); await sleep(17);
  check("推入中途返回：从当前 p / 速度续算，不跳变（打断后一帧内位移 < 60 px）", "< 60", Math.round(Math.abs(tx(pg) - xMid)), Math.abs(tx(pg) - xMid) < 60 && pMid > .5);
  await sleep(700);
  check("中途返回落定：hidden", "hidden", pg.hidden ? "hidden" : "shown", pg.hidden);
});
