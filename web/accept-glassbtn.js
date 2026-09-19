/* accept-glassbtn.js — acceptance of the round glass buttons' press (BOARD.md #5). Registered through ACCEPT.add; runs in accept.js's page.
   The button under test is the pushed page's 返回 (.pnav .navbtn.pback — the page is pushed with view.js's openPage for the test and popped after).
   ① size: the three buttons are 44 × 44 (tokens.css --ios-nav-button), so L = (44 + 16) / 44 = 1.3636 (glass-button-press-formula.md §2).
   ② press: from the down, the computed scale follows the closed-form spring ζ .625 / response .262 s (the ultraSmall tracking spring, §0 table) from
      1 to L — sampled every frame from the button's computed transform matrix, rms ≤ .005 (= 1.3636 × the 1/255 quantisation a matrix read can
      carry, rounded up; the page integrates the same closed form on the same timestamps).
   ③ release: from the up, the scale follows ζ .375 / .4 from its value AND velocity at the up back to 1 (underdamped: it passes below 1 — the check
      uses the general closed form with v0, so the overshoot is part of the expectation), same rms bound; the minimum below 1 is reported.
   ④ tap rule: a release inside the 70 pt margin fires the button (the page pops), a release 120 pt away fires nothing (the page stays) — the margin is
      around the control's bounds, not its scaled presentation.
   ⑤ template: hidden strips the press (transform gone, no click). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptGlassBtn(ctx) {
    const { check, num, sleep } = ctx;
    if (!window.GlassBtn) { check("玻璃钮：GlassBtn 未装载（motion.js 未到）", "GlassBtn", "缺", false); return; }
    if (typeof openPage !== "function") { check("玻璃钮：openPage 不可用，无法推入页取返回钮", "有", "缺", false); return; }
    /* R4: the press grows the BOX (44 → 60, glass-button-press-formula.md §7 item 2), not a transform — the scale read = the rect's width ÷ 44 (tokens.css
       --ios-nav-button); the glyph's ::before scales by --gb-scale and fades to .2 (§7 item 4) */
    const W0 = 44; const scaleOf = (el) => el.getBoundingClientRect().width / W0;
    const closed = (start, target, v0, zeta, resp, t) => { const w = 2 * Math.PI / resp, wd = w * Math.sqrt(1 - zeta * zeta), dx = start - target, e = Math.exp(-zeta * w * t);
      return target + e * (dx * Math.cos(wd * t) + ((v0 + zeta * w * dx) / wd) * Math.sin(wd * t)); };
    const rms = (a) => Math.sqrt(a.reduce((s, v) => s + v * v, 0) / Math.max(1, a.length));
    const raf = () => new Promise((r) => requestAnimationFrame(r));
    const ev = (el, type, x, y, id = 7) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, isPrimary: true, pointerType: "touch", clientX: x, clientY: y, button: 0, buttons: type === "pointerup" ? 0 : 1 }));
    const sample = (el, ms, t0) => new Promise((resolve) => { const out = []; let first = null;
      const tick = (now) => { if (first === null) first = now; out.push({ t: (now - t0) / 1000, x: scaleOf(el) }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); }; requestAnimationFrame(tick); });
    const pg = document.querySelector("#subpage"); const pop = openPage("检查", "<p>玻璃钮检查</p>"); await sleep(450);
    const btn = pg.querySelector(".navbtn.pback"); const r = btn.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    /* ① */
    num("返回钮 44 × 44（--ios-nav-button）", 44, Math.min(r.width, r.height), 0.5);
    const L = GlassBtn.L(btn); num("按下目标 L = (min(W,H)+16)/min(W,H)", 60 / 44, L, 0.001);
    for (const sel of [".topbar .navbtn#discard", ".topbar .navbtn#save"]) { const b = document.querySelector(sel); if (b) { const rr = b.getBoundingClientRect(); const m = Math.min(rr.width, rr.height); if (m > 0) num(`${sel} 44 × 44`, 44, m, 0.5); } }
    /* ② press: the lift starts LIFT_START = 58 ms after the down (§7b: 36 at +57, 36.75 at +73 → the tracking spring's start at +57.7); before it the box
       is still 44; from the start the box follows ζ .625 / .262 to 60 (L = 1.3636) */
    ev(btn, "pointerdown", cx, cy); await sleep(40); const st40 = GlassBtn.state(btn);
    check(`按下 +40 ms：还没抬（起点 +${GlassBtn.LIFT_START} ms，§7b）`, "44 · 未起", `${btn.getBoundingClientRect().width.toFixed(2)} · ${st40 && st40.started ? "已起" : "未起"}`, Math.abs(btn.getBoundingClientRect().width - 44) < 0.01 && !!st40 && !st40.started);
    let st = null; for (let i = 0; i < 20; i++) { st = GlassBtn.state(btn); if (st && st.started) break; await sleep(4); }
    if (!st || !st.started) { check("玻璃钮：按下后起动", "有", "缺", false); return; }
    num("抬起起点 = 按下 + 58 ms（§7b 解得 57.7）", 58, st.t0 - st.downAt, 8);
    const hold = await sample(btn, 600, st.t0);
    num(`按下 盒 44→60 对 ζ.625/r.262 闭式 rms（${hold.length} 帧，scale = 宽 ÷ 44）`, 0, rms(hold.map((s) => s.x - closed(1, L, 0, 0.625, 0.262, s.t))), 0.005);
    num("按住 600 ms 后 scale = L（盒 60 × 60）", L, scaleOf(btn), 0.005);
    num("按住：盒中心不动（margin 抵消）", cx, (() => { const q = btn.getBoundingClientRect(); return q.left + q.width / 2; })(), 0.5);
    num("按住：图标 alpha = .2（§7 item 4）", 0.2, parseFloat(getComputedStyle(btn, "::before").opacity), 0.01);
    num("按住：图标 scale × 1.3636（§7 item 4 wrapper 36 → 49.09）", L, (() => { const m = /matrix\(([^)]+)\)/.exec(getComputedStyle(btn, "::before").transform); return m ? parseFloat(m[1].split(",")[0]) : 1; })(), 0.005);
    check("玻璃钮 光晕（§7b）：读数已记、不可表达（backdrop-aware vibrantColorMatrix），不画", "GlassBtn.glow.built false + why", GlassBtn.glow ? `${GlassBtn.glow.built} · ${GlassBtn.glow.why} · little ${GlassBtn.glow.littleGlow.size}/${GlassBtn.glow.littleGlow.shadowRadius} · dodge ${GlassBtn.glow.littleGlow.luminance.light}/${GlassBtn.glow.littleGlow.luminance.dark}` : "-", !!GlassBtn.glow && GlassBtn.glow.built === false && GlassBtn.glow.littleGlow.shadowRadius === 45);
    /* ③ release curve — released OUTSIDE the 70 pt margin so nothing fires and the page stays (a firing release pops the page 350 ms later and hides the
       button mid-curve); the release spring is the same either way */
    ev(btn, "pointermove", cx + 120, cy); await raf();   // 120 = 22 (half the 44) + 70 + 28: outside the margin around the BOUNDS (the scaled rect would reach 100.6)
    const before = GlassBtn.state(btn); ev(btn, "pointerup", cx + 120, cy); await raf();
    const st2 = GlassBtn.state(btn); const rel = await sample(btn, 900, st2 ? st2.t0 : performance.now());
    const pred = rel.map((s) => closed(before.x, 1, before.v, 0.375, 0.4, s.t));
    num(`松手 scale 对 ζ.375/r.4 闭式 rms（${rel.length} 帧，含过冲；最大差 ${Math.max(...rel.map((s, i) => Math.abs(s.x - pred[i]))).toFixed(4)}）`, 0, rms(rel.map((s, i) => s.x - pred[i])), 0.005);
    check("松手过冲到 1 以下（欠阻尼 ζ .375）", "< 1", Math.min(...rel.map((s) => s.x)).toFixed(4), Math.min(...rel.map((s) => s.x)) < 1);
    check("70 pt 外松手无事件（页面仍在）", "还在", pg.classList.contains("in") ? "还在" : "弹出", pg.classList.contains("in"));
    await sleep(600); check("松手后盒复位（内联 width 清、宽 44；ζ .375 settle ≈ 1.2 s）", "无 · 44", `${btn.style.width || "无"} · ${btn.getBoundingClientRect().width.toFixed(1)}`, !btn.style.width && Math.abs(btn.getBoundingClientRect().width - 44) < 0.01);
    /* ④ tap rule: a release inside the margin fires the button (the page pops) */
    ev(btn, "pointerdown", cx, cy, 8); await sleep(120); ev(btn, "pointerup", cx + 60, cy, 8); await sleep(500);
    check("70 pt 内松手 = 点按（页面弹出）", "弹出", pg.classList.contains("in") ? "还在" : "弹出", !pg.classList.contains("in"));
    await sleep(450); openPage("检查", "<p>玻璃钮检查</p>"); await sleep(450);
    const b2 = pg.querySelector(".navbtn.pback"); const r2 = b2.getBoundingClientRect(), x2 = r2.left + r2.width / 2, y2 = r2.top + r2.height / 2;
    /* ⑤ hidden strips */
    ev(b2, "pointerdown", x2, y2, 9); await sleep(100);
    const hiddenDesc = Object.getOwnPropertyDescriptor(Document.prototype, "hidden"); Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); await sleep(30);
    check("hidden 时按下态剥掉（盒清）", "无", b2.style.width || "无", !b2.style.width);
    delete document.hidden; if (hiddenDesc) Object.defineProperty(Document.prototype, "hidden", hiddenDesc);
    ev(b2, "pointerup", x2, y2, 9); await sleep(300);
    b2.click(); await sleep(450);
  });
})();
