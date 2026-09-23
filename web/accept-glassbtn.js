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
    /* A16 (red twice on first dark runs: 42 vs 42.51): the pre-press cx was read while the pushed page's slide still had half a pixel to go, then the page settled under the
       hold — the measurement, not the box. Now both sides are read at the same instant: the centre from the rect vs the rest centre from the layout tokens (the page's
       left + --ios-nav-side 20 + --ios-nav-button/2 22), which the negative margins must reproduce */
    { const q = btn.getBoundingClientRect(), pgL = pg.getBoundingClientRect().left, side = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-nav-side")) || 20, half = (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-nav-button")) || 44) / 2;
      num("按住：盒中心不动（margin 抵消；同一帧读：矩形中心 vs 页左 + --ios-nav-side 20 + 22）", pgL + side + half, q.left + q.width / 2, 0.5); }
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
    /* ---- R71″ (§7d, R81 probe): partial presses. All releases 120 pt away (outside the 70 pt margin) so the page stays. */
    const b3 = pg.querySelector(".navbtn.pback"); const r3 = b3.getBoundingClientRect(), x3 = r3.left + r3.width / 2, y3 = r3.top + r3.height / 2, far3 = x3 + 120;
    const wOf = () => b3.getBoundingClientRect().width, op3 = () => parseFloat(getComputedStyle(b3, "::before").opacity);
    const sampleW = (ms) => new Promise((resolve) => { const out = []; let first = null; const tick = (now) => { if (first === null) first = now; out.push({ t: now, w: wOf(), a: op3(), s: GlassBtn.state(b3) }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); }; requestAnimationFrame(tick); });
    /* ① a 60 ms tap: no lift at all (the first grown frame +69.3 lies after the up), the icon .2 for a frame then the fade */
    { const tD = performance.now(); ev(b3, "pointerdown", x3, y3, 11); await sleep(20); await raf(); const a20 = op3();
      await sleep(Math.max(0, 60 - (performance.now() - tD))); ev(b3, "pointerup", far3, y3, 11); const tU = performance.now();
      const smp = await sampleW(520); const maxW = Math.max(...smp.map((s) => s.w)), aEnd = op3();   // 520 > 11.7 + 470: the fade is over
      check("玻璃钮 R71″ ① 60 ms 点按（抬手在首个长大帧 +69.3 之前）：几何全程 44 不抬；图标按下一帧 .2，抬手后 .47 s default 淡回 1", "44 all frames · .2 · 1", `max ${maxW.toFixed(2)} (${smp.length} frames) · ${a20} · ${aEnd}`, Math.abs(maxW - 44) < .01 && Math.abs(a20 - .2) < .001 && aEnd === 1 && !b3.style.width); await sleep(200); }
    /* ② a 120 ms tap: the lift runs on ≈ 30 ms past the up (the value at up + 30 ≥ the value at the up), then falls on the release table's timeline from that value — the trough at
       up + 225…250 ms, its depth by the start (k), the switch continuous */
    { const tD = performance.now(); ev(b3, "pointerdown", x3, y3, 12);
      const smpA = await sampleW(Math.max(0, 118 - (performance.now() - tD)));
      ev(b3, "pointerup", far3, y3, 12); const tU = performance.now(); const wUp = wOf();
      const smpB = await sampleW(700);
      /* A16 (red twice): the 'still rising ≈ 30 ms after the up' read must be the driver's own last frame inside the rising window (state.tLast ≤ REVERSE_MS on its release
         clock) — a wall-clock sample at ≥ 30 ms landed on a +47 ms frame under load, already past the reversal; no frame inside the window (a stall) → reported, not judged */
      const inWin = smpB.filter((s) => s.s && s.s.phase === "release" && s.s.tLast != null && s.s.tLast <= GlassBtn.REVERSE_MS), at30 = inWin.length ? inWin[inWin.length - 1] : null, stall30 = !at30;
      const tr = smpB.reduce((m, s) => (s.w < m.w ? s : m), smpB[0]), st12 = smpB[smpB.length - 1].s, kUsed = (smpB.find((s) => s.s && s.s.k != null) || {}).s;
      const jumps = smpB.slice(1).map((s, i) => Math.abs(s.w - smpB[i].w)), maxJump = Math.max(...jumps);
      check("玻璃钮 R71″ ② 120 ms 点按：抬手时已抬起中（宽 > 44），抬手后 ≈ 30 ms 仍在长（驱动器自己 since_up ≤ 30 ms 内最后一帧的宽 ≥ 抬手时的宽，A15；窗口内无帧 = 停顿，只记不判），然后回落", "wUp > 44 · w(≤ up+30) ≥ wUp", `wUp ${wUp.toFixed(2)} · ${at30 ? "w(up+" + at30.s.tLast.toFixed(0) + ") " + at30.w.toFixed(2) : "no frame inside 30 ms (stall: not judged)"}`, wUp > 44.5 && (stall30 || at30.w >= wUp - .05));
      check(`玻璃钮 R71″ ② 回落谷时刻不变（up + 225…250，探针 120 ms 点按 +230），谷深随起点缩（k = ${kUsed ? kUsed.k.toFixed(3) : "?"}：探针从 41.5 起 ×.917）；切换连续（相邻帧宽差 ≤ 3.5 px = 回落表最陡段 2.5 px/帧 × k）`, "trough 225…250 · < 44 · max jump ≤ 3.5", `trough ${tr.w.toFixed(2)} (×${(tr.w / 44).toFixed(3)}) @ up+${(tr.t - tU).toFixed(0)} · max jump ${maxJump.toFixed(2)}`, tr.t - tU > 220 && tr.t - tU < 255 && tr.w < 44 && maxJump <= 3.5);
      await sleep(200); check("玻璃钮 R71″ ② +800 后复位（盒清、44）", "无 · 44", `${b3.style.width || "无"} · ${wOf().toFixed(1)}`, !b3.style.width && Math.abs(wOf() - 44) < .01); }
    /* ③ hold 700 → release → re-press 120 ms into the fall: the icon back to .2 within a frame, the geometry keeps falling until the lift table's start (down₂ + 52.6), then
       re-lifts from that value on the lift timeline (the probe: peak × 1.385 @ down₂ + 204 from 34.14 = the table scaled to what is left), settles at L */
    { ev(b3, "pointerdown", x3, y3, 13); await sleep(700); ev(b3, "pointerup", far3, y3, 13); await sleep(120);
      const wBefore = wOf(), aBefore = op3(); const tD2 = performance.now(); ev(b3, "pointerdown", x3, y3, 14); await raf(); await raf();
      const a2 = op3(), sRe = GlassBtn.state(b3);
      check("玻璃钮 R71″ ③ 回落中再按：图标一帧内瞬回 .2（淡入撤掉），几何先继续落（resuming）", ".2 · resuming · falling", `${aBefore.toFixed(3)} → ${a2} · ${sRe && sRe.resuming ? "resuming" : "-"} · ${wBefore.toFixed(2)} → ${wOf().toFixed(2)}`, Math.abs(a2 - .2) < .001 && !!sRe && sRe.resuming && wOf() <= wBefore + .05);
      const smp = await sampleW(650); const minS = smp.reduce((m, s) => (s.w < m.w ? s : m), smp[0]), pk = smp.reduce((m, s) => (s.w > m.w ? s : m), smp[0]);
      const from = minS.w / 44, wantPeak = from + (1.390 - 1) * (60 / 44 - from) / (60 / 44 - 1);
      check(`玻璃钮 R71″ ③ 再按后：谷在 down₂ + 40…70（落到抬起表起点 52.6 后转向；探针 +38 / 首长大帧 +71），再从谷值按抬起表时间线长起，峰 ≈ from + .39·(L − from)/(L − 1) = ${wantPeak.toFixed(3)}（探针 ×1.385 @ +204）在 down₂ + 185…225`, "trough 40…70 · peak match ± .01 · peak 185…225", `trough ×${from.toFixed(3)} @ +${(minS.t - tD2).toFixed(0)} · peak ×${(pk.w / 44).toFixed(3)} @ +${(pk.t - tD2).toFixed(0)}`, minS.t - tD2 > 35 && minS.t - tD2 < 75 && Math.abs(pk.w / 44 - wantPeak) < .01 && pk.t - tD2 > 185 && pk.t - tD2 < 225);
      num("玻璃钮 R71″ ③ 再按 +650 ms：到位 L（盒 60）", 60 / 44, wOf() / 44, .005);
      ev(b3, "pointerup", far3, y3, 14); await sleep(900); check("玻璃钮 R71″ ③ 松手后复位", "无 · 44", `${b3.style.width || "无"} · ${wOf().toFixed(1)}`, !b3.style.width && Math.abs(wOf() - 44) < .01); }
    /* B3: the top bar's ✕ / ✓ — the glyph is a child .sf (view.js sf()), it must take the same .2 / × L as ::before above; the button itself stays opaque
       while held (§7: only the geometry, the icon alpha and the glow change) — a synthetic pointerdown does not set :active, so that rule is read from the CSSOM */
    { const bar = document.querySelector("#topbar"), was = bar && bar.classList.contains("editing");
      if (bar && !was) bar.classList.add("editing");
      for (const sel of ["#save", "#discard"]) {
        const b = document.querySelector(sel), sf = b && b.querySelector(".sf");
        if (!sf) { check(`玻璃钮 B3 ${sel} 图标 .sf 在`, "有", "缺", false); continue; }
        const q = b.getBoundingClientRect(), Lb = GlassBtn.L(b), x = q.left + q.width / 2, y = q.top + q.height / 2, sfOp = () => parseFloat(getComputedStyle(sf).opacity);
        ev(b, "pointerdown", x, y, 21); await sleep(20); await raf(); const a1 = sfOp();
        await sleep(600); const aH = sfOp(), m = /matrix\(([^)]+)\)/.exec(getComputedStyle(sf).transform), sH = m ? parseFloat(m[1].split(",")[0]) : 1;   // L read at rest (44 → 60/44): GlassBtn.L reads the box, which is 60 while held
        ev(b, "pointermove", x + 120, y, 21); await raf(); ev(b, "pointerup", x + 120, y, 21); await sleep(900); const aE = sfOp();
        check(`玻璃钮 B3 ${sel}：图标 .sf 按下一帧 .2、按住 .2 且 × L（${Lb.toFixed(4)}）、松手后回 1（§7 item 4 / §7c）`, `.2 · .2 · ${Lb.toFixed(4)} · 1`, `${a1} · ${aH} · ${sH.toFixed(4)} · ${aE}`,
          Math.abs(a1 - 0.2) < 0.001 && Math.abs(aH - 0.2) < 0.01 && Math.abs(sH - Lb) < 0.005 && Math.abs(aE - 1) < 0.001); }
      let best = null; for (const ss of document.styleSheets) { let rs; try { rs = ss.cssRules; } catch (e) { continue; } for (const r of rs) if (r.selectorText && /\.topbar \.navbtn(\.navbtn)?:active/.test(r.selectorText) && r.style.opacity) { const sp = (r.selectorText.match(/\.|:/g) || []).length; if (!best || sp >= best.spec) best = { sel: r.selectorText, v: r.style.opacity, spec: sp }; } }
      check("玻璃钮 B3 顶栏钮按住整钮不变淡（§7：只改几何 + 图标 alpha + 光晕；CSSOM 里特异度最高的 :active opacity 规则）", "1", best ? `${best.v}（${best.sel}）` : "无规则", !best || best.v === "1");
      if (bar && !was) bar.classList.remove("editing"); }
    b2.click(); await sleep(450);
  });
})();
