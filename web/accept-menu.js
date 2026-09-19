/* accept-menu.js — acceptance of the value row's pull-down menu (BOARD.md #3, night batch). Registered through ACCEPT.add; runs inside
   accept.js's page (light and dark runs).
   What is checked, and the numbers it is checked against:
   ① appear: the panel's left / top / width / height each follow the closed-form spring ζ .8 / response .3 s (menu-motion-formula.md §0 table
      "出现（长大）弹簧", §2) from the anchor button's rect to the resting menu rect. Per frame two readings — the driver's spring value and clock
      (Menu.state().x / .t) and the panel's getBoundingClientRect() — and two checks: the spring value is x(t) = target + (start − target)·
      e^(−ζωt)(cos ωd t + ζω/ωd · sin ωd t), ω = 2π/.3, on the driver's own clock (rms ≤ .01 pt: the analytic step is exact), and the DOM shows
      the spring value (rect − x, rms ≤ 1 pt = twice the rounding of a rect read at 1 px).
   ② dismiss: the same four properties follow ζ .9 / .3 (§0 "消失（缩小）弹簧") from the resting rect back to the anchor's rect, same two checks.
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
    /* two readings per frame: the panel's rect (what the DOM shows) and the driver's own state (Menu.state(): x = the spring's value, t = its clock).
       Two checks come out of them (验收 00:2x: the one-piece check "rect vs closed form on the sampler's timestamps" read 6–7 pt under load — a frame
       in which the sampler and the driver did not run together, whichever side it was): ① the DOM shows the driver's value (rect − x, ≤ 1 pt = twice
       the rounding of a rect read at 1 px); ② the driver's value is the closed form on its own clock (x − x(t), ≤ .01 pt: the analytic step is exact) */
    const sample = (panel, ms) => new Promise((resolve) => { const out = []; let first = null;
      const tick = (now) => { if (first === null) first = now; if (!panel.isConnected) { resolve(out); return; }   // removed on settle (the dismiss): the frame's read would be zeros
        const st = Menu.state(); if (st) out.push({ t: st.t, r: rect(panel), x: { ...st.x }, op: parseFloat(cs(panel).opacity) }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); };
      requestAnimationFrame(tick); });
    const fit = (samples, from, to, zeta, resp) => { const res = {}; for (const k of ["left", "top", "width", "height"]) {
      res[k] = { dom: rms(samples.map((s) => s.r[k] - s.x[k])), model: rms(samples.map((s) => s.x[k] - closed(from[k], to[k], zeta, resp, s.t))) }; } return res; };
    btn.scrollIntoView({ block: "center" }); await sleep(100);   // the value row on screen, as a finger would find it
    const a0 = rect(btn);
    /* ① appear */
    btn.click(); await new Promise((r) => requestAnimationFrame(r));
    const panel = document.querySelector(".menu.morph"); if (!panel) { check("菜单：点值行后有 .menu.morph 面板", "有", "缺", false); return; }
    const st = Menu.state(); const open = await sample(panel, 900);
    const fin = fit(open, st.from, st.to, 0.8, 0.3);
    for (const k of ["left", "top", "width", "height"]) { num(`菜单出现 ${k}：弹簧值对 ζ.8/r.3 闭式 rms（pt，${open.length} 帧，驱动自己的时钟）`, 0, fin[k].model, 0.01); num(`菜单出现 ${k}：面板矩形 = 弹簧值 rms（pt）`, 0, fin[k].dom, 1); }
    /* R19 (menu-motion-formula.md §7b, R18b): no per-item delay — every item is fully opaque and in place on the first frame after the open (the
       list view has no stagger); the intermediate shape (a geometry step) waits for its rect's formula (待读), so nothing else to check */
    { const items = [...panel.querySelectorAll(".menu-body button")]; const ops = items.map((b) => parseFloat(cs(b).opacity)); const rects = items.map((b) => b.getBoundingClientRect().height);
      check(`菜单项无逐项延迟（§7b）：首帧后 ${items.length} 项 opacity 全 1、各 42 高`, "全 1 · 42", `${ops.map((v) => v.toFixed(2)).join("/")} · ${rects.map((h) => h.toFixed(0)).join("/")}`, items.length > 0 && ops.every((v) => v === 1) && rects.every((h) => Math.abs(h - 42) <= 0.5)); }
    /* ④ rest geometry */
    const rr = rect(panel); num("菜单静止宽（menu-card-material §1.2 defaultMenuWidth）", 250, rr.width, 0.5);
    num("菜单静止圆角（§1.2 menuCornerRadius）", 32, parseFloat(cs(panel).borderTopLeftRadius), 0.5);
    num("菜单静止位置 = 目标（top）", st.to.top, rr.top, 0.5); num("菜单静止位置 = 目标（left）", st.to.left, rr.left, 0.5);
    /* ③ no dimming */
    const scrim = document.querySelector(".menu-scrim"); const m = /rgba?\([^)]*?,\s*([\d.]+)\)$/.exec(scrim ? cs(scrim).backgroundColor : "");
    check("菜单后无压暗（scrim α = 0）", 0, scrim ? (m ? +m[1] : (cs(scrim).backgroundColor === "transparent" ? 0 : cs(scrim).backgroundColor)) : "无 scrim", !!scrim && (cs(scrim).backgroundColor === "transparent" || (m && +m[1] === 0) || cs(scrim).backgroundColor === "rgba(0, 0, 0, 0)"));
    /* R1 — the glass layer: keys = menu-glass-sdfdump-2026-09-19.md §2 (the table below is that table's light column + the dark differences), the
       layer exists, the built terms carry the keys (feGaussianBlur σ = BlurRadius × 4, the fill flood, the ring band .06 / 8 / 4 / σ 5, clipped), the
       old sampled substitute is off (background transparent, no backdrop-filter, no box-shadow); nothing pixel-wise (BOARD A15) */
    { const DOC = { light: { BlurRadius: 5, BlurDistance0: -83.5, BlurDistance1: -1, BlurDistance2: 0, BlurDistance3: 0, BlurOpacity0: 0.8, BlurOpacity1: 0.4, BlurOpacity2: 0.5, BlurOpacity3: 1, BlurFillBlurRadius: 8, BlurFillDarkenOpacity: 0, BlurFillLightenOpacity: 0.9, BlurFillNormalOpacity: 0.5,
        FaceColorMatrixWhite: 1.03, FaceColorMatrixBlack: 0.4, FaceColorMatrixSaturation: 1.2, FaceColorMatrixFillColor: [1, 1, 1, 0.2], FaceColorMatrixMaxLuma: 1, FaceColorMatrixMaxLumaSDR: 0.94, FaceOpacity: 1, Clamp: 1.07, ClampPreserveHue: 0,
        InnerRefractionAmount: -60, InnerRefractionHeight: 20, OuterRefractionAmount: 41.75, OuterRefractionHeight: 33.4, RefractionOpacity: 0.6, RefractionDistance0: -1, RefractionDistance1: 0,
        KeyFillHighlightAmount: 0.4, KeyFillHighlightAngle: 1.571, KeyFillHighlightColorBias: -0.3, KeyFillHighlightEffectOffset: -0.5333, KeyFillHighlightHeight: 0.5333, KeyFillHighlightSpread: 1.676, KeyFillHighlightSpreadSDR: 1.85,
        RingShadowOpacity: 0.06, RingShadowOffset: 8, RingShadowStrokeWidth: 4, RingShadowBlurRadius: 5, RingShadowMask: 1,
        BleedAmount: 58.45, BleedBlurRadius: 58.45, BleedHeight: 58.45, BleedOpacity: 0.5, BleedColorMatrixBlack: 0.9, BleedColorMatrixSaturation: 1.2, BleedColorMatrixWhite: 1, BleedDarkenBlend: 1, BleedDistance0: 1, BleedDistance1: 0,
        ShadowAmount: 0, ShadowOpacity: 0.4, ShadowRadius: 24, ShadowOffset: [0, 8], ShadowColorMatrixFillColor: [0, 0, 0, 0.3] },
      dark: { BlurFillDarkenOpacity: 0.9, BlurFillLightenOpacity: 0, FaceColorMatrixWhite: 1.125, FaceColorMatrixBlack: 0.125, FaceColorMatrixSaturation: 1.3, FaceColorMatrixFillColor: [0, 0, 0, 0], FaceColorMatrixMaxLuma: 0.35, FaceColorMatrixMaxLumaSDR: 0.35, Clamp: 1.308, KeyFillHighlightSpread: 1.309, KeyFillHighlightSpreadSDR: 1.309, BleedOpacity: 0.8, BleedColorMatrixBlack: 0.125, BleedColorMatrixSaturation: 1, BleedColorMatrixWhite: 0.5, BleedDarkenBlend: 0, ShadowOpacity: 0.6 } };
      const theme = Menu.glass ? Menu.glass.theme() : "light"; const want = { ...DOC.light, ...(theme === "dark" ? DOC.dark : {}) }; const got = Menu.glass ? Menu.glass.keys(theme) : {};
      const bad = Object.keys(want).filter((k) => JSON.stringify(want[k]) !== JSON.stringify(got[k]));
      check(`菜单玻璃键表 = sdfdump §2（${theme}，${Object.keys(want).length} 键）`, "全同", bad.length ? "差：" + bad.join(",") : "全同", bad.length === 0);
      const layer = panel.querySelector(".menu-glass"), copy = panel.querySelector(".menu-glass-copy"), f = document.getElementById("menu-glass-f"), blur = f && f.querySelector("feGaussianBlur"), flood = f && f.querySelector("feFlood"), ringP = panel.querySelector(".menu-glass-ring path"), fr = document.getElementById("menu-glass-ring");
      check("菜单玻璃层存在（#app 复本 + 环影），在项之下", "layer+copy+ring", `${layer ? "layer" : "-"}+${copy ? "copy" : "-"}+${ringP ? "ring" : "-"}`, !!layer && !!copy && !!ringP && layer === panel.firstElementChild);
      num("菜单玻璃 模糊 σ = BlurRadius 5 × 4 pt（1/4 分辨率采样，alert-pipeline-plan §1.3）", 20, blur ? parseFloat(blur.getAttribute("stdDeviation")) : NaN, 0.01);
      if (want.FaceColorMatrixFillColor[3] > 0) { check("菜单玻璃 填充混合 = FaceColorMatrixFillColor（白 α .2）", "rgb(255,255,255) .2", flood ? `${flood.getAttribute("flood-color")} ${flood.getAttribute("flood-opacity")}` : "无", !!flood && flood.getAttribute("flood-opacity") === "0.2" && /255,\s*255,\s*255/.test(flood.getAttribute("flood-color"))); }
      else check("菜单玻璃 填充混合：暗色 fill α 0 → 无 flood", "无", flood ? "有" : "无", !flood);
      check("菜单玻璃 环影带：α .06、偏移 8、带宽 4、σ 5、裁到面板（mask 1）", ".06 · 8 · 4 · σ5 · clip", ringP ? `${ringP.getAttribute("fill-opacity")} · ${/M\S+ (\S+)/.exec(ringP.getAttribute("d") || "")?.[1]} · ${fr ? fr.querySelector("feGaussianBlur").getAttribute("stdDeviation") : "-"} · ${layer ? cs(layer).overflow : "-"}` : "无", !!ringP && ringP.getAttribute("fill-opacity") === "0.06" && /^M\S+ 8H/.test(ringP.getAttribute("d") || "") && !!fr && fr.querySelector("feGaussianBlur").getAttribute("stdDeviation") === "5" && !!layer && cs(layer).overflow === "hidden" && cs(ringP.parentElement).mixBlendMode === "multiply");
      check("菜单面板旧底（采样替代）关：background transparent、无 backdrop-filter、无 box-shadow", "transparent · none · none", `${cs(panel).backgroundColor} · ${cs(panel).backdropFilter || cs(panel).webkitBackdropFilter} · ${cs(panel).boxShadow}`, cs(panel).backgroundColor === "rgba(0, 0, 0, 0)" && (cs(panel).backdropFilter || cs(panel).webkitBackdropFilter) === "none" && cs(panel).boxShadow === "none");
      const mr = document.getElementById("app").getBoundingClientRect(), pr2 = panel.getBoundingClientRect(), tm = /matrix\(([^)]+)\)/.exec(cs(copy).transform), tx = tm ? tm[1].split(",").map(parseFloat) : null;
      check("菜单玻璃 复本对齐页面（translate = 页 − 面板）", `${(mr.left - pr2.left).toFixed(1)}, ${(mr.top - pr2.top).toFixed(1)}`, tx ? `${tx[4].toFixed(1)}, ${tx[5].toFixed(1)}` : "-", !!tx && Math.abs(tx[4] - (mr.left - pr2.left)) <= 1 && Math.abs(tx[5] - (mr.top - pr2.top)) <= 1);
      /* R1′ (menu-card-material.md §7): BlurFill, MaxLuma, the face matrix, the soft shadow — the filter's primitives carry the keys */
      const fm = f && f.querySelector('feColorMatrix[result="face"]'), bfb = f && f.querySelector('feGaussianBlur[result="bf"]'), kc = f && f.querySelector('feComponentTransfer[result="k"] feFuncR');
      num("菜单玻璃 BlurFill：bf 模糊 σ = BlurFillBlurRadius 8 × 4（近似 mip 3，§7.2）", 32, bfb ? parseFloat(bfb.getAttribute("stdDeviation")) : NaN, 0.01);
      { const dl = f && f.querySelector('feComposite[result="dl"]'), cmix = f && f.querySelector('feComposite[result="c"]');
        check("菜单玻璃 BlurFill：darken·min + lighten·max + (1−d−l)·c，再 mix(·, bf, normal)（§7.2）", `${want.BlurFillDarkenOpacity} · ${want.BlurFillLightenOpacity} · normal ${want.BlurFillNormalOpacity}`, dl && cmix ? `${dl.getAttribute("k2")} · ${dl.getAttribute("k3")} · normal ${cmix.getAttribute("k3")}` : "无", !!dl && !!cmix && +dl.getAttribute("k2") === want.BlurFillDarkenOpacity && +dl.getAttribute("k3") === want.BlurFillLightenOpacity && +cmix.getAttribute("k3") === want.BlurFillNormalOpacity); }
      num("菜单玻璃 MaxLuma 压亮：k = 1 − Y·(1 − MaxLumaSDR)（§7.1）", -(1 - want.FaceColorMatrixMaxLumaSDR), kc ? parseFloat(kc.getAttribute("slope")) : NaN, 1e-6);
      { const expect = (() => { const W = want.FaceColorMatrixWhite, Bk = want.FaceColorMatrixBlack, sat = want.FaceColorMatrixSaturation; const white = [.2126, .7152, .0722]; const r0 = white.map((w) => (W - Bk) * w); // the Y row through YCC⁻¹ contributes (W−B)·luma to each channel; a full check re-derives the R row: R = Y' + 1.5748 Cr' − .7874
          const Cr = [.5, -.4542, -.0458]; const R = white.map((w, i) => (W - Bk) * w + 1.5748 * sat * Cr[i]); const Roff = Bk + 1.5748 * (sat * .5 + .5 - .5 * sat) - .7874; return { R, Roff }; })();
        const got = fm ? fm.getAttribute("values").split(/\s+/).map(parseFloat) : null;
        check("菜单玻璃 面矩阵 = YCC⁻¹·D·YCC（Rec.709；R 行核：(W−B)·luma + 1.5748·sat·Cr，偏置 B + 1.5748(.5 − .5sat + .5) − .7874）", expect.R.map((v) => v.toFixed(4)).join(" ") + " | " + expect.Roff.toFixed(4), got ? got.slice(0, 3).map((v) => v.toFixed(4)).join(" ") + " | " + got[4].toFixed(4) : "无", !!got && expect.R.every((v, i) => Math.abs(v - got[i]) < 1e-4) && Math.abs(expect.Roff - got[4]) < 1e-4); }
      { const sh = cs(panel).filter; const m = /drop-shadow\(rgba\(0, 0, 0, ([\d.]+)\) 0px 8px 24px\)/.exec(sh);
        check("菜单玻璃 软影（§7.3：amount 0 仍画）：黑 α .3 × ShadowOpacity、半径 24、偏移 (0, 8)（剖面近似）", `α ${(0.3 * want.ShadowOpacity).toFixed(2)} · 0 8 24`, sh, !!m && Math.abs(parseFloat(m[1]) - 0.3 * want.ShadowOpacity) < 0.005); }
      check("菜单玻璃 未接项已列（Menu.glass.unbuilt）", "≥ 5 项", Menu.glass ? Object.keys(Menu.glass.unbuilt).length + " 项" : "-", !!Menu.glass && Object.keys(Menu.glass.unbuilt).length >= 5); }
    /* ② dismiss (the scrim tap = cancel = the reverse morph) */
    const from2 = rect(panel); scrim.click(); await new Promise((r) => requestAnimationFrame(r));
    const st2 = Menu.state(); const close = await sample(panel, 900);
    const fout = fit(close, st2.from, st2.to, 0.9, 0.3);
    for (const k of ["left", "top", "width", "height"]) { num(`菜单收回 ${k}：弹簧值对 ζ.9/r.3 闭式 rms（pt，${close.length} 帧）`, 0, fout[k].model, 0.01); num(`菜单收回 ${k}：面板矩形 = 弹簧值 rms（pt）`, 0, fout[k].dom, 1); }
    num("菜单收回目标 = 值行按钮框（top）", a0.top, st2.to.top, 0.5); num("菜单收回起点 = 静止框（width）", from2.width, st2.from.width, 0.5);
    await sleep(300); check("菜单收回后面板移除", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph"));
    /* R32 — reduce motion (menu-motion-formula.md §0 "减少动态效果": liquidMorphReduceMotion ζ 1 / response .15, a cross-fade): the geometry is at the
       resting rect from the first frame, the opacity follows ζ 1 / .15 from 0 to 1 on the driver's clock; the dismiss fades to 0 the same way, geometry
       unchanged. Forced through Menu.open's hook (the runner cannot set prefers-reduced-motion) */
    { Menu.open(btn, sel, { reduced: true }); await new Promise((r) => requestAnimationFrame(r)); const pr = document.querySelector(".menu.morph"), sr = Menu.state();
      const critical = (start, target, resp, t) => { const w = 2 * Math.PI / resp; return target + (start - target) * (1 + w * t) * Math.exp(-w * t); };
      const smp = await sample(pr, 500);
      const geo = rms(smp.flatMap((s) => ["left", "top", "width", "height"].map((k) => s.r[k] - sr.to[k])));
      num("菜单减少动态效果：几何从首帧起 = 静止框（rms，pt）", 0, geo, 1);
      num(`菜单减少动态效果：opacity 对 ζ1/.15 闭式 0 → 1 rms（${smp.length} 帧，驱动时钟）`, 0, rms(smp.map((s) => s.x.a - critical(0, 1, 0.15, s.t))), 0.01);
      num("菜单减少动态效果：面板计算 opacity = 弹簧值（同帧读，rms）", 0, rms(smp.map((s) => s.op - s.x.a)), 0.02);
      const before = Menu.state(); document.querySelector(".menu-scrim").click(); await new Promise((r) => requestAnimationFrame(r)); const s2 = Menu.state(); const out2 = await sample(pr, 500);
      num("菜单减少动态效果 收回：opacity 对 ζ1/.15 闭式 → 0 rms", 0, rms(out2.map((s) => s.x.a - critical(before.x.a, 0, 0.15, s.t))), 0.01);
      num("菜单减少动态效果 收回：几何不动（rms，pt）", 0, rms(out2.flatMap((s) => ["left", "top", "width", "height"].map((k) => s.r[k] - s2.from[k]))), 1);
      await sleep(200); check("菜单减少动态效果 收回后面板移除", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph")); }
    /* ⑤ hidden strips the state */
    btn.click(); await sleep(50); document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); Menu.onHidden(true); await sleep(50);
    check("菜单：页面 hidden 时菜单剥掉", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph"));
  });
})();
