/* accept-alert-view.js — the page's alert dialog as view.js drives it (ask(); 界面): the static rows (closed geometry, pane substitutes / read keys)
   and the interactions that were accept.js's "alert" sections — one alert at a time, the appear animation (.settled) and the read-key glass layer,
   the 停止一切 tile's dialog title inside the box. accept-alert.js (2号) holds the glass keys themselves. Split out of accept.js 2026-09-20 (BOARD 收尾单 ②). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptAlertView(ctx) {
    const { check, num, col, sleep, settle, raf, sec, segRest, tabRest, fadeRest, at, pev, cs, px, T, dark, near, rgb, same, fmt, satTop, varColor, probe, q, bs, onText, thisShift, R } = ctx;
    sec("static", { layer: "static", dark: true });
  /* The confirm alert (closed, but its computed geometry is there) */
  const alert = document.querySelector("dialog#alert");
  if (alert) {
    num("弹窗宽 320（--ios-alert-w）", 320, px(cs(alert).width)); num("弹窗圆角 34（--ios-alert-radius）", 34, px(cs(alert).borderTopLeftRadius));
    const ab = alert.querySelector(".acts button"); if (ab) { num("弹窗按钮高 48（--ios-alert-button-h）", 48, px(cs(ab).height)); num("弹窗按钮圆角 24（--ios-alert-button-radius）", 24, px(cs(ab).borderTopLeftRadius)); }
    /* materials (spec-extract ⑨, end-to-end measured): pane = blur 20 (5 ÷ backdrop scale .25) · saturate 1.94 · brightness 1.071 + white .538 (dark 1.73 / .755 / .135) */
    const bf = (el) => cs(el).backdropFilter || cs(el).webkitBackdropFilter || "";
    const pane = alert.querySelector(".pane"), wantPane = dark ? "blur(20px) saturate(1.73) brightness(0.755)" : "blur(20px) saturate(1.94) brightness(1.071)";
    check("弹窗玻璃层是独立的 .pane（按钮的混合要看得见它）", "pane", pane ? "pane" : "缺", !!pane);
    /* R57 (alert-glass.js): in the light theme the pane's sampled substitute is off and the read-keys layer carries the glass (accept-alert.js has its rows);
       the dark theme's keys are unread — the substitute stays there */
    /* the closed pane still carries index.html's sampled substitute (the dark theme's keys are unread; the light theme's open dialog gets the read-keys
       layer from alert-glass.js — R57, accept-alert.js has those rows) */
    check("弹窗玻璃滤镜链（关着的 pane）= 端到端实测（--ios-alert-glass-filter：blur 20 · saturate · brightness；开着时由 R57 / R57′ 读键层接管，两主题）", wantPane, pane ? bf(pane).replace(/\s+/g, " ") : "缺", !!pane && bf(pane).replace(/\s+/g, " ") === wantPane);
    col("弹窗叠白（关着的 pane；--ios-alert-glass-white .538 / 暗 .135）", dark ? [255, 255, 255, .135] : [255, 255, 255, .538], pane ? cs(pane).backgroundColor : "");
    col("弹窗遮罩（--ios-alert-dimming）", dark ? [0, 0, 0, .48] : [0, 0, 0, .2], varColor("--ios-alert-dimming", probe));
    check("弹窗玻璃无描边无阴影（pipeline #10）", "none", pane ? cs(pane).boxShadow : "缺", !!pane && cs(pane).boxShadow === "none");
    if (pane) { const pr = cs(pane); check("弹窗玻璃层外扩 60 pt 再用 clip-path 裁回 r34（marginWidth 60.2 ← ⑨；Safari 合成层不吃 overflow 圆角）", "top -60px / inset(60px round 34px)", `${pr.top} / ${pr.clipPath}`, /-60px/.test(pr.top) && /inset\(60px round 34px\)/.test(pr.clipPath)); check("dialog 上没有 clip-path（Chrome 会把它当 backdrop root，模糊失效）", "none", cs(alert).clipPath, cs(alert).clipPath === "none"); }
    { const want = innerHeight / 2 + 14, gotTop = px(cs(alert).top);   // 50dvh + 14 = 492 只在 web view 盖满 956 时成立（black-translucent；数据会话 fd61e71：default/black 下 web view 只有 894 高，中心 522）
      check("弹窗位置 = 整屏原生 frame（中心 = 屏高/2 + 14 → y 406 于 956，④）", `${Math.round(want * 10) / 10}px & translate -50%`, `${cs(alert).top} ${cs(alert).translate}`, Math.abs(gotTop - want) < 1 && /-50%/.test(cs(alert).translate)); }
    const at2 = alert.querySelector("h2"), am = alert.querySelector(".dlg-b");
    check("弹窗标题左对齐、labelColor（④ 帧 (30,22,260) / pipeline §1.9）", "left label", `${cs(at2).textAlign} ${cs(at2).color}`, cs(at2).textAlign === "left" && same(cs(at2).color, dark ? [255, 255, 255] : [0, 0, 0]));
    check("弹窗说明左对齐，底距 20.33（按钮顶 108 − 49.67 − 38，④）", "left 20.33px", `${cs(am).textAlign} ${cs(am).paddingBottom}`, cs(am).textAlign === "left" && near(px(cs(am).paddingBottom), 20.33, 0.05));
    if (CSS.supports("mix-blend-mode", "plus-darker")) check("弹窗说明字 = 面板 −0.4 / +0.3（pipeline §1.9：plus-darker rgb(153) / plus-lighter rgb(77)）", dark ? "rgb(77) plus-lighter" : "rgb(153) plus-darker", `${cs(am).color} ${cs(am).mixBlendMode}`, same(cs(am).color, dark ? [77, 77, 77] : [153, 153, 153]) && cs(am).mixBlendMode === (dark ? "plus-lighter" : "plus-darker"));
    else col("弹窗说明字 Chrome 常量（236 − 102 / 暗 35 + 76.5）", dark ? [111, 111, 111] : [134, 134, 135], cs(am).color);
    const cbtn = alert.querySelector("#alert-cancel"), okb = alert.querySelector("#alert-ok");
    if (cbtn) col("「取消」字 = labelColor（pipeline §1.9，不是 tint）", dark ? [255, 255, 255] : [0, 0, 0], cs(cbtn).color);
    if (okb) { okb.classList.add("danger"); col("「停止」字 = M_red × 按钮底（白底亮色实测 (235,42,45)，pipeline §1.9）", dark ? [255, 105, 108] : [235, 42, 45], cs(okb).color); check("「停止」按钮底透明（不再被 .acts button.danger 的白底盖住）", "rgba(0, 0, 0, 0)", cs(okb).backgroundColor, cs(okb).backgroundColor === "rgba(0, 0, 0, 0)"); okb.classList.remove("danger"); okb.classList.add("primary"); }
    check("弹窗面板无字区取样目标 ≈ (236,236,237)±3 亮 / 列表底 — 数据会话模拟器截图取样（accept 量不到像素）", "236±3", "见数据会话取样", true);
    const dbtn = alert.querySelector(".acts button:not(.primary)");
    if (dbtn) {
      const ov = cs(dbtn, "::before"), pd = CSS.supports("mix-blend-mode", "plus-darker");
      if (pd) { col("弹窗按钮 = 面板 −30.9/255：plus-darker 叠 rgb(224)（暗 +27.9 plus-lighter rgb(28)，pipeline §1.8）", dark ? [28, 28, 28] : [224, 224, 224], ov.backgroundColor); check("弹窗按钮混合模式", dark ? "plus-lighter" : "plus-darker", ov.mixBlendMode, ov.mixBlendMode === (dark ? "plus-lighter" : "plus-darker")); }
      else col("弹窗按钮 Chrome 等值常量 α .131 / .127（--ios-alert-button-fallback）", dark ? [255, 255, 255, .127] : [0, 0, 0, .131], ov.backgroundColor);
    }
  }
  /* Behaviour 1: one alert at a time; Chrome runs the pane flat until the appear animation ends (.settled), WebKit keeps it from frame 1 */
  if (sec("appear", { layer: "timing", dark: true }) && typeof ask === "function" && document.querySelector("#alert")) {   // appear animation + the read-key glass layer in both themes (R57′)
    const d = document.querySelector("#alert"), pane = d.querySelector(".pane"), bf = (el) => getComputedStyle(el).backdropFilter || getComputedStyle(el).webkitBackdropFilter || "";
    /* the appear animation's end costs no frame (index.html alert-in: held at .999, forwards; 老网页 09-23 模拟器 A: ending at 1 cost 42–74 ms right there) */
    const fts = [], fr = (t) => { fts.push(t); if (fts.length < 90) requestAnimationFrame(fr); }; let aeAt = 0; let aeFirst = ""; const aeL = (e) => { if (!aeFirst) aeFirst = `${e.animationName}@${e.target === d ? "dialog" : e.target.tagName.toLowerCase() + (e.target.className && typeof e.target.className === "string" ? "." + e.target.className.split(" ")[0] : "")}`; if (e.target === d && e.animationName === "alert-in" && !aeAt) aeAt = performance.now(); }; d.addEventListener("animationend", aeL); requestAnimationFrame(fr);
    const p1 = ask("测", "一", "好"); const p2 = ask("测二", "二", "好");
    const second = await Promise.race([p2.then((v) => `resolved ${v}`), sleep(50).then(() => "pending")]);
    check("弹窗重入保护：开着时再 ask 立即回 false，不叠第二层", "resolved false · 1 open", `${second} · ${document.querySelectorAll("dialog[open]").length} open`, second === "resolved false" && document.querySelectorAll("dialog[open]").length === 1);
    const chrome = !CSS.supports("mix-blend-mode", "plus-darker");
    const glassRead2 = !!window.AlertGlass;   // R57′: the read-key layer is built in both themes (the dark keys came with 数据 R74)
    if (glassRead2) check("弹窗出现动画期间读键玻璃层已在（R57：层随弹窗同帧建）", "层", window.AlertGlass.layer ? "层" : "无", !!window.AlertGlass.layer);
    else check(chrome ? "弹窗出现动画期间玻璃层先走平底（Chrome 路：无 backdrop-filter）" : "弹窗出现动画期间玻璃层就是精确层（WebKit 路）", chrome ? "none" : "blur", bf(pane), chrome ? bf(pane) === "none" : /blur/.test(bf(pane)));
    await settle(() => d.classList.contains("settled"), 520);   // S1: the appear animation's own end (.settled), ≤ the old 520
    if (glassRead2) check("弹窗出现动画结束 → .settled，读键玻璃层在（R57 / R57′ 两主题）", "settled + 层", `${d.classList.contains("settled") ? "settled" : "-"} + ${window.AlertGlass.layer ? "层" : "无"}`, d.classList.contains("settled") && !!window.AlertGlass.layer);
    else check("弹窗出现动画结束 → .settled，玻璃层到位（--ios-alert-glass-filter）", "settled + blur", `${d.classList.contains("settled") ? "settled" : "-"} + ${bf(pane).slice(0, 10)}`, d.classList.contains("settled") && /blur/.test(bf(pane)));
    /* waits for the dialog's own alert-in end: view.js:50 takes the first animationend from anywhere inside it, so .settled can come early */
    { await settle(() => aeAt, 900); await sleep(160); d.removeEventListener("animationend", aeL); let gap = 0; for (let i = 1; i < fts.length; i++) if (fts[i] > aeAt - 20 && fts[i] < aeAt + 140) gap = Math.max(gap, fts[i] - fts[i - 1]);
      check("弹窗出现动画结束那一下不掉帧：结束前后 −20…+140 ms 最大帧隔 ≤ 34 ms；静止 opacity .999（弹簧 T 0.404 s 处的值）、fill forwards", "≤ 34 ms · .999 · forwards", `${aeAt ? Math.round(gap) + " ms" : "未见结束"} · ${getComputedStyle(d).opacity} · ${getComputedStyle(d).animationFillMode}（先到的动画结束事件 ${aeFirst || "无"}）`, !!aeAt && gap <= 34 && Math.abs(parseFloat(getComputedStyle(d).opacity) - 0.999) < 1e-4 && getComputedStyle(d).animationFillMode === "forwards"); }
    check("弹窗首帧时间戳记录（?diag：alert f1/f2）", "f1 ≤ 40 ms", window.ALERT_T ? `f1 +${Math.round(ALERT_T.f1 - ALERT_T.open)} f2 +${Math.round(ALERT_T.f2 - ALERT_T.open)} ms` : "缺", !!window.ALERT_T && ALERT_T.f1 - ALERT_T.open <= 40);
    document.querySelector("#alert-cancel").click(); await settle(() => !d.open, 450); await p1;   // S1: closed = the dialog's own open flag
    check("弹窗取消后关闭", "closed", d.open ? "open" : "closed", !d.open);
  }
  /* 验收 09-19 18:0x: with the page unscrolled, the ask() dialog opened from the 停止一切 tile must show its title (the dialog is overflow:clip — not a scroll
     container — and ask() resets scrollTop; before: .pane's −60 inset gave 60 px of scrollable overflow and the title scrolled out of the box) */
  if (sec("estop", { layer: "timing", dark: false })) { const tile = document.querySelector("#estop"), dlg = document.querySelector("#alert");
    if (tile && dlg && !dlg.open) { scrollTo(0, 0); await sleep(100); tile.click(); await settle(() => dlg.open && dlg.classList.contains("settled"), 700);   // S1: open and its appear animation over
      const dr = dlg.getBoundingClientRect(), tr = dlg.querySelector("#alert-t").getBoundingClientRect(); dlg.scrollTop = 60; const st = dlg.scrollTop;
      check("顶部未滚动时点磁贴弹窗：标题在弹窗盒内（盒顶 ≤ 标题顶，标题有高度）、弹窗不可滚（overflow clip，scrollTop 设 60 读回 0）", "title inside · scrollTop 0", `open ${dlg.open} · box ${Math.round(dr.top)}…${Math.round(dr.bottom)} title ${Math.round(tr.top)}…${Math.round(tr.bottom)} "${dlg.querySelector("#alert-t").textContent}" · scrollTop ${st} · overflow ${getComputedStyle(dlg).overflow}`, dlg.open && tr.height > 10 && tr.top >= dr.top - 0.5 && tr.bottom <= dr.bottom + 0.5 && st === 0);
      const cancel = dlg.querySelector("#alert-cancel"); if (cancel) cancel.click(); await settle(() => !dlg.open, 600); } }
  }, { layer: "timing", dark: true });
})();
