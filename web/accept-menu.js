/* accept-menu.js — acceptance of the value row's pull-down menu (BOARD.md #3, night batch). Registered through ACCEPT.add; runs inside
   accept.js's page (light and dark runs).
   What is checked, and the numbers it is checked against:
   ① appear: the panel's left / top / width / height each follow the closed-form spring ζ .8 / response .3 s (menu-motion-formula.md §0 table
      "出现（长大）弹簧", §2) from the anchor button's rect to the resting menu rect — sampled every animation frame from the panel's own
      getBoundingClientRect(), the deviation from x(t) = target + (start − target)·e^(−ζωt)(cos ωd t + ζω/ωd · sin ωd t), ω = 2π/.3, is
      an rms in pt per property; pass when rms ≤ 1 pt — 1 pt = twice the rounding of a rect read at 1 px (the only source of deviation when the
      page integrates the same closed form on the same frame timestamps).
   ② dismiss: the same four properties follow ζ .9 / .3 (§0 "消失（缩小）弹簧") from the resting rect back to the anchor's rect, same rms bound.
   ③ no dimming: the scrim's background alpha is 0 (§0 "压暗": _hasVisibleBackground NO).
   ④ geometry at rest: width 250, corner 32 (menu-card-material.md §1.2: defaultMenuWidth, menuCornerRadius).
   ⑤ real-device template (BOARD A6, the applicable ones): hidden → the menu is gone (state stripped); the panel's resting background equals the
      page's --alert-fill token in this theme (the material itself is untouched tonight — A5). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptMenu(ctx) {
    const { check, num, sleep } = ctx;
    const cs = (el) => getComputedStyle(el);
    if (!window.Menu) { check("菜单：Menu 未装载（motion.js 未到 → 旧路径）", "Menu", "缺", false); return; }
    const btn = document.querySelector("main .menubtn"); const sel = btn && btn.previousElementSibling;
    if (!btn || !sel || sel.tagName !== "SELECT") { check("菜单：页面上没有值行按钮可测", "有", "缺", false); return; }
    /* the closed-form spring, ζ < 1 (the same expression view.js springStep / Motion.spring integrate) */
    const closed = (start, target, zeta, resp, t) => { const w = 2 * Math.PI / resp, wd = w * Math.sqrt(1 - zeta * zeta), e = Math.exp(-zeta * w * t);
      return target + (start - target) * e * (Math.cos(wd * t) + (zeta * w / wd) * Math.sin(wd * t)); };
    const rms = (a) => Math.sqrt(a.reduce((s, v) => s + v * v, 0) / Math.max(1, a.length));
    const rect = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height }; };
    /* t = the frame's timestamp − the spring's start (Menu.state().t0, the open / close call's performance.now()): the page integrates the same
       closed form step by step on these timestamps, so the sample of frame k must equal x(t_k) exactly (up to the rect's rounding) */
    const sample = (panel, ms, t0) => new Promise((resolve) => { const out = []; let first = null;
      const tick = (now) => { if (first === null) first = now; if (!panel.isConnected) { resolve(out); return; }   // removed on settle (the dismiss): the frame's read would be zeros
        out.push({ t: (now - t0) / 1000, ...rect(panel) }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); };
      requestAnimationFrame(tick); });
    const fit = (samples, from, to, zeta, resp) => { const res = {}; for (const k of ["left", "top", "width", "height"]) {
      res[k] = rms(samples.map((s) => s[k] - closed(from[k], to[k], zeta, resp, s.t))); } return res; };
    btn.scrollIntoView({ block: "center" }); await sleep(100);   // the value row on screen, as a finger would find it
    const a0 = rect(btn);
    /* ① appear */
    btn.click(); await new Promise((r) => requestAnimationFrame(r));
    const panel = document.querySelector(".menu.morph"); if (!panel) { check("菜单：点值行后有 .menu.morph 面板", "有", "缺", false); return; }
    const st = Menu.state(); const open = await sample(panel, 900, st.t0);
    const fin = fit(open, st.from, st.to, 0.8, 0.3);
    for (const k of ["left", "top", "width", "height"]) num(`菜单出现 ${k} 对 ζ.8/r.3 闭式 rms（pt，${open.length} 帧）`, 0, fin[k], 1);
    /* ④ rest geometry */
    const rr = rect(panel); num("菜单静止宽（menu-card-material §1.2 defaultMenuWidth）", 250, rr.width, 0.5);
    num("菜单静止圆角（§1.2 menuCornerRadius）", 32, parseFloat(cs(panel).borderTopLeftRadius), 0.5);
    num("菜单静止位置 = 目标（top）", st.to.top, rr.top, 0.5); num("菜单静止位置 = 目标（left）", st.to.left, rr.left, 0.5);
    /* ③ no dimming */
    const scrim = document.querySelector(".menu-scrim"); const m = /rgba?\([^)]*?,\s*([\d.]+)\)$/.exec(scrim ? cs(scrim).backgroundColor : "");
    check("菜单后无压暗（scrim α = 0）", 0, scrim ? (m ? +m[1] : (cs(scrim).backgroundColor === "transparent" ? 0 : cs(scrim).backgroundColor)) : "无 scrim", !!scrim && (cs(scrim).backgroundColor === "transparent" || (m && +m[1] === 0) || cs(scrim).backgroundColor === "rgba(0, 0, 0, 0)"));
    /* ⑤ background follows the token */
    const probe = document.createElement("div"); probe.style.cssText = "position:fixed;visibility:hidden;background:var(--alert-fill)"; document.body.appendChild(probe);
    check("菜单面板底色 = --alert-fill（本主题）", cs(probe).backgroundColor, cs(panel).backgroundColor, cs(probe).backgroundColor === cs(panel).backgroundColor); probe.remove();
    /* ② dismiss (the scrim tap = cancel = the reverse morph) */
    const from2 = rect(panel); scrim.click(); await new Promise((r) => requestAnimationFrame(r));
    const st2 = Menu.state(); const close = await sample(panel, 900, st2.t0);
    const fout = fit(close, st2.from, st2.to, 0.9, 0.3);
    for (const k of ["left", "top", "width", "height"]) num(`菜单收回 ${k} 对 ζ.9/r.3 闭式 rms（pt，${close.length} 帧）`, 0, fout[k], 1);
    num("菜单收回目标 = 值行按钮框（top）", a0.top, st2.to.top, 0.5); num("菜单收回起点 = 静止框（width）", from2.width, st2.from.width, 0.5);
    await sleep(300); check("菜单收回后面板移除", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph"));
    /* ⑤ hidden strips the state */
    btn.click(); await sleep(50); document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); Menu.onHidden(true); await sleep(50);
    check("菜单：页面 hidden 时菜单剥掉", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph"));
  });
})();
