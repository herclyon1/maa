/* accept-glassbtn.js — acceptance of the round glass buttons' press (BOARD.md #5). Registered through ACCEPT.add; runs in accept.js's page.
   The button under test is the pushed page's 返回 (.pnav .navbtn.pback — the page is pushed with view.js's openPage for the test and popped after).
   ① size: the three buttons are 44 × 44 (tokens.css --ios-nav-button), so L = (44 + 16) / 44 = 1.3636 (glass-button-press-formula.md §2).
   ② press (R71′, glass-button-press-formula.md §7c probe frames): still 44 at +40 ms; from +52.6 the box follows the probe's lift table (+69.3 34.48/32 …
      peak × 1.390 at +202.6, held L = 60/44) by linear interpolation between frames — sampled every frame against GlassBtn.liftAt(now − downAt), rms ≤ .005;
      the icon is .2 on the first frame after the down (no transition) and scales × the box.
   ③ release (§7c): the box follows the probe's release table from the up (unchanged to +19, first change +36, trough × .899 at +236, back at +800) —
      rms ≤ .005 against GlassBtn.releaseAt(now − upAt); the trough is reported; the icon's opacity runs .2 → 1 over .47 s on cubic-bezier(.25,.1,.25,1)
      from up + 11.7 ms (the read CABasicAnimation: the computed transition string, still ≈ .2 at up + 30 ms, 1 by up + 520 ms).
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
    const iconOp = () => parseFloat(getComputedStyle(btn, "::before").opacity);
    const rms = (a) => Math.sqrt(a.reduce((s, v) => s + v * v, 0) / Math.max(1, a.length));
    const raf = () => new Promise((r) => requestAnimationFrame(r));
    const ev = (el, type, x, y, id = 7) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, isPrimary: true, pointerType: "touch", clientX: x, clientY: y, button: 0, buttons: type === "pointerup" ? 0 : 1 }));
    const sample = (el, ms, t0) => new Promise((resolve) => { const out = []; let first = null;
      const tick = (now) => { if (first === null) first = now; out.push({ t: (now - t0) / 1000, x: scaleOf(el) }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); }; requestAnimationFrame(tick); });
    const pg = document.querySelector("#subpage"); const pop = openPage("检查", "<p>玻璃钮检查</p>"); await sleep(450);
    const navSettled = async () => { const t0 = performance.now(); while (pg.classList.contains("nav-live") && performance.now() - t0 < 3000) await sleep(30); };   // the push (nav.js) still owns .pback::before's opacity while nav-live (R47′ chevron keyframes)
    await navSettled();
    const btn = pg.querySelector(".navbtn.pback"); const r = btn.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    /* ① */
    num("返回钮 44 × 44（--ios-nav-button）", 44, Math.min(r.width, r.height), 0.5);
    const L = GlassBtn.L(btn); num("按下目标 L = (min(W,H)+16)/min(W,H)", 60 / 44, L, 0.001);
    for (const sel of [".topbar .navbtn#discard", ".topbar .navbtn#save"]) { const b = document.querySelector(sel); if (b) { const rr = b.getBoundingClientRect(); const m = Math.min(rr.width, rr.height); if (m > 0) num(`${sel} 44 × 44`, 44, m, 0.5); } }
    /* ② press (R71′ §7c): +52.6 still resting, +69.3 the first grown frame; the box follows the probe's frames (GlassBtn.LIFT_T) from the down */
    const tDown = performance.now(); ev(btn, "pointerdown", cx, cy); await sleep(20); await raf();
    check("按下后第一帧图标 alpha 直接 .2（§7c：+19.3 ms 已 .2，anims 0 条——不是过渡）", ".2 · transition none", `${iconOp()} · ${getComputedStyle(btn, "::before").transitionProperty}`, Math.abs(iconOp() - 0.2) < 0.001 && getComputedStyle(btn, "::before").transitionProperty === "none");
    await sleep(Math.max(0, 40 - (performance.now() - tDown))); const st40 = GlassBtn.state(btn);
    check(`按下 +40 ms：还没抬（探针 +52.6 帧仍 32，+69.3 帧 34.48：起点在 52.6…69.3 内；表首结 ${GlassBtn.LIFT_START}）`, "44 · 未起", `${btn.getBoundingClientRect().width.toFixed(2)} · ${st40 && st40.started ? "已起" : "未起"}`, Math.abs(btn.getBoundingClientRect().width - 44) < 0.01 && !!st40 && !st40.started);
    let st = null; for (let i = 0; i < 20; i++) { st = GlassBtn.state(btn); if (st && st.started) break; await sleep(4); }
    if (!st || !st.started) { check("玻璃钮：按下后起动", "有", "缺", false); return; }
    const hold = await sample(btn, 600, st.downAt);
    num(`按下 盒对 §7c 探针抬起表（GlassBtn.liftAt，t 自 down；${hold.length} 帧，scale = 宽 ÷ 44）rms`, 0, rms(hold.map((s) => s.x - GlassBtn.liftAt(s.t * 1000))), 0.005);
    const pk = hold.reduce((m, s) => (s.x > m.x ? s : m), hold[0]);
    check("抬起峰 × 1.390 @ +202.6（44.48 / 32）后回到持住 L（表：+236 1.383、+336 1.3628、≥ +353 1.3636）", "peak 1.38…1.39 near +190…+215 ms", `peak ${pk.x.toFixed(4)} @ +${Math.round(pk.t * 1000)} ms`, pk.x > 1.38 && pk.x < 1.395 && pk.t * 1000 > 185 && pk.t * 1000 < 220);
    num("按住 600 ms 后 scale = L（盒 60 × 60）", L, scaleOf(btn), 0.005);
    num("按住：盒中心不动（margin 抵消）", cx, (() => { const q = btn.getBoundingClientRect(); return q.left + q.width / 2; })(), 0.5);
    num("按住：图标 alpha = .2（§7 item 4）", 0.2, parseFloat(getComputedStyle(btn, "::before").opacity), 0.01);
    num("按住：图标 scale × 1.3636（§7 item 4 wrapper 36 → 49.09）", L, (() => { const m = /matrix\(([^)]+)\)/.exec(getComputedStyle(btn, "::before").transform); return m ? parseFloat(m[1].split(",")[0]) : 1; })(), 0.005);
    check("玻璃钮 光晕（§7b）：读数已记、不可表达（backdrop-aware vibrantColorMatrix），不画", "GlassBtn.glow.built false + why", GlassBtn.glow ? `${GlassBtn.glow.built} · ${GlassBtn.glow.why} · little ${GlassBtn.glow.littleGlow.size}/${GlassBtn.glow.littleGlow.shadowRadius} · dodge ${GlassBtn.glow.littleGlow.luminance.light}/${GlassBtn.glow.littleGlow.luminance.dark}` : "-", !!GlassBtn.glow && GlassBtn.glow.built === false && GlassBtn.glow.littleGlow.shadowRadius === 45);
    /* ③ release — released OUTSIDE the 70 pt margin so nothing fires and the page stays (a firing release pops the page 350 ms later and hides the
       button mid-curve); the release table (§7c) is the same either way */
    ev(btn, "pointermove", cx + 120, cy); await raf();   // 120 = 22 (half the 44) + 70 + 28: outside the margin around the BOUNDS (the scaled rect would reach 100.6)
    const before = GlassBtn.state(btn); ev(btn, "pointerup", cx + 120, cy); await raf();
    const st2 = GlassBtn.state(btn), upAt = st2 ? st2.upAt : performance.now();
    await sleep(Math.max(0, 30 - (performance.now() - upAt)));
    const op30 = iconOp(), t30 = performance.now() - upAt, want30 = GlassBtn.iconAt(t30), want30b = GlassBtn.iconAt(Math.max(0, t30 - 20));
    check(`松手 +${t30.toFixed(0)} ms：图标 alpha 刚离开 .2（回程 = 读到的 CABasicAnimation：.2 → 1，.47 s，default (.25,.1,.25,1)，beginTime up + 11.7 ms；逐帧写，无 CSS 过渡）`, `${want30b.toFixed(3)}…${want30.toFixed(3)}`, op30.toFixed(3), op30 >= want30b - 0.002 && op30 <= want30 + 0.002 && op30 > 0.2);
    /* one sampling loop from here (≈ up + 30) for 700 ms: the box's scale and the icon's computed alpha per frame, each against the driver's own values of that frame (A15) */
    const rel = [], relIcon = []; { const tI = performance.now(); while (performance.now() - tI < 700) { await raf(); const s0 = GlassBtn.state(btn); rel.push({ t: performance.now() - upAt, x: scaleOf(btn), tD: s0 ? s0.tLast : null }); relIcon.push({ a: iconOp(), want: s0 ? s0.icon : 1, tD: s0 ? s0.tLast : null }); } }
    num(`松手 图标 alpha 对驱动器本帧写入值（${relIcon.length} 帧；写入值 = iconAt(t)，t 自 up）rms`, 0, rms(relIcon.map((s) => s.a - s.want)), 0.002);
    num(`松手 图标 写入值对 iconAt(驱动器本帧 t) 逐帧一致（${relIcon.filter((s) => s.tD != null).length} 帧）rms`, 0, rms(relIcon.filter((s) => s.tD != null).map((s) => s.want - GlassBtn.iconAt(s.tD))), 0.0005);
    num(`松手 盒对 §7c 探针回落表（GlassBtn.releaseAt(驱动器本帧 t)，起点 ${before ? before.x.toFixed(4) : "?"}；${rel.length} 帧）rms`, 0, rms(rel.filter((s) => s.tD != null).map((s) => s.x - GlassBtn.releaseAt(s.tD, before ? before.x : L))), 0.005);
    const tr0 = rel.reduce((m, s) => (s.x < m.x ? s : m), rel[0]);
    check("回落谷 × .899 @ up + 236（28.78 / 32），首个变化帧 up + 36，≈ up + 800 回 1", "trough .89….91 near +225…+250 ms", `trough ${tr0.x.toFixed(4)} @ +${Math.round(tr0.t)} ms`, tr0.x > 0.89 && tr0.x < 0.91 && tr0.t > 220 && tr0.t < 255);
    check("70 pt 外松手无事件（页面仍在）", "还在", pg.classList.contains("in") ? "还在" : "弹出", pg.classList.contains("in"));
    check("松手 +520 ms 后图标 alpha 回 1（11.7 + 470 ms）", "1", String(iconOp()), iconOp() === 1);
    await sleep(Math.max(0, 830 - (performance.now() - upAt)));
    check("松手后盒复位（表末 +800 ms：内联 width 清、宽 44）", "无 · 44", `${btn.style.width || "无"} · ${btn.getBoundingClientRect().width.toFixed(1)}`, !btn.style.width && Math.abs(btn.getBoundingClientRect().width - 44) < 0.01);
    /* ④ tap rule: a release inside the margin fires the button (the page pops) */
    ev(btn, "pointerdown", cx, cy, 8); await sleep(120); ev(btn, "pointerup", cx + 60, cy, 8); await sleep(500);
    check("70 pt 内松手 = 点按（页面弹出）", "弹出", pg.classList.contains("in") ? "还在" : "弹出", !pg.classList.contains("in"));
    await sleep(450); openPage("检查", "<p>玻璃钮检查</p>"); await sleep(450); await navSettled();
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
