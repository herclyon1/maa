/* accept-tabbar.js — acceptance of the tab bar's lifted selection lens, geometry mode (BOARD.md #7a; web/assets/lens/tab-lens.js). Registered
   through ACCEPT.add; runs in accept.js's page (light and dark).
   ① delay: pressing another item, the glide gets .lift after the page's +140 ms (tokens.css --ios-touch-tab-glide-delay; interaction spec §2 T1);
      pressing the selected item, .lift-sel after +125 ms (--ios-touch-tab-selected-lift-delay, T3) — measured from the pointerdown, ± one frame + the
      timer's slack (accepted window [delay − 5, delay + 50] ms).
   ② lift: from the lift's start (window.__tabLens.t0) the glide's width and height follow ζ 1 / .25 (tab-lens-motion.md §0 "抬起") from the item's
      box w0 × 54 to (w0 + 16) × (54 + 16) (§0 / §4: 94×54 → 110×70 = +16 on both axes); the box centre x follows ζ .85 / .4 (§3, the jump to a
      pressed item) from the old centre to the pressed item's; rms ≤ 1 pt per quantity (twice the rounding of a rect read at 1 px — the page
      integrates the same closed form on the same frame timestamps).
   ③ drop: from the up the width / height follow ζ 1 / .4 (§0 "落回") from the value at the up back to w0 × 54; rms ≤ 1 pt.
   ④ rest: after the drop the driver is off (nav without .tl-on) and the glide shows view.js's box for the selected item (left = its offsetLeft,
      width = its offsetWidth, height 54).
   ⑤ template (BOARD A6): the bar's .plat is the same node after the gesture (no rebuild); hidden while lifted → the driver stops and the glide is
      back on view.js's box; the keyboard rule's two lines (view.js __tabKbd) as in accept.js.
   #7b the drag (tab-lens-motion.md §6.5 / §6.6): the target while dragging = finger x − a·W + W/2 (a = .5 when pressed at the centre → the finger),
      the centre vs the closed form ζ .85 / .2 from the value and velocity before the move (rms ≤ 1 pt), the hard clamp at the items' run, the up:
      target = the centre of the item under the finger, ζ .9 / .4 from the value and velocity at the up, that item selected, driver off at rest;
      hidden mid-drag stops the driver. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptTabBar(ctx) {
    const { check, num, sleep } = ctx;
    const nav = document.querySelector("nav.tabs"); if (!nav) { check("标签栏：页面无 nav.tabs", "有", "缺", false); return; }
    if (!nav.classList.contains("tlens")) { check("标签栏：tab-lens.js 未接（nav 无 .tlens：挂钩行 / motion.js）", "tlens", nav.className, false); return; }
    const seg = nav.querySelector(".seg"), g = nav.querySelector(".glide"), bs = [...seg.querySelectorAll("button")], plat0 = nav.querySelector(".plat");
    const crit = (start, target, resp, t) => { const w = 2 * Math.PI / resp; return target + (start - target) * (1 + w * t) * Math.exp(-w * t); };   // ζ 1
    const under = (start, target, zeta, resp, t) => { const w = 2 * Math.PI / resp, wd = w * Math.sqrt(1 - zeta * zeta), e = Math.exp(-zeta * w * t); return target + (start - target) * e * (Math.cos(wd * t) + (zeta * w / wd) * Math.sin(wd * t)); };
    const rms = (a) => Math.sqrt(a.reduce((s, v) => s + v * v, 0) / Math.max(1, a.length));
    const rect = () => { const r = g.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height, cx: r.left + r.width / 2 }; };
    const ev = (el, t, x, y, id = 4) => el.dispatchEvent(new PointerEvent(t, { bubbles: true, cancelable: true, pointerId: id, isPrimary: true, pointerType: "touch", clientX: x, clientY: y, button: 0, buttons: t === "pointerup" ? 0 : 1 }));
    const sample = (ms, t0) => new Promise((resolve) => { const out = []; let first = null; const tick = (now) => { if (first === null) first = now; out.push({ t: (now - t0) / 1000, ...rect(), p: window.__tabLens ? window.__tabLens.p : null }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); }; requestAnimationFrame(tick); });
    const px = (name, fb) => { const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)); return Number.isNaN(v) ? fb : v; };
    const waitClass = async (cls, ms) => { const t0 = performance.now(); while (performance.now() - t0 < ms) { if (g.classList.contains(cls)) return performance.now() - t0; await sleep(4); } return null; };
    const on0 = bs.findIndex((b) => b.classList.contains("on")); const other = bs[on0 === 0 ? 1 : 0]; const w0 = other.offsetWidth, h0 = g.offsetHeight;
    const r0 = rect(); const or = other.getBoundingClientRect(), ox = or.left + or.width / 2, oy = or.top + or.height / 2;
    /* ① + ② press another item */
    ev(other, "pointerdown", ox, oy); const dLift = await waitClass("lift", 600);
    const delay = px("--ios-touch-tab-glide-delay", 140);
    check(`按下未选中项 +${delay} ms 抬起（.lift）`, `${delay}…${delay + 50} ms`, dLift === null ? "没抬" : Math.round(dLift) + " ms", dLift !== null && dLift >= delay - 5 && dLift <= delay + 50);
    await new Promise((r) => requestAnimationFrame(r)); const L0 = window.__tabLens;
    if (!L0) { check("标签栏：抬起后驱动在跑（window.__tabLens）", "有", "缺", false); ev(other, "pointerup", ox, oy); return; }
    const lift = await sample(600, L0.t0);
    num(`抬起 宽 对 ζ1/.25 闭式 rms（${lift.length} 帧；${w0} → ${w0 + 16}）`, 0, rms(lift.map((s) => s.width - crit(w0, w0 + 16, 0.25, s.t))), 1);
    num(`抬起 高 对 ζ1/.25 闭式 rms（${h0} → ${h0 + 16}）`, 0, rms(lift.map((s) => s.height - crit(h0, h0 + 16, 0.25, s.t))), 1);
    num("抬起 中心 x 对 ζ.85/.4 闭式 rms（旧项中心 → 按下项中心）", 0, rms(lift.map((s) => s.cx - under(r0.cx, ox, 0.85, 0.4, s.t))), 1);
    num("抬满后 宽 = w0 + 16", w0 + 16, rect().width, 0.5); num("抬满后 高 = 54 + 16", h0 + 16, rect().height, 0.5);
    num("抬满后 圆角 = 高 / 2（胶囊，999px）", (h0 + 16) / 2, Math.min(parseFloat(getComputedStyle(g).borderTopLeftRadius), rect().height / 2), 0.5);
    /* ③ drop */
    /* the drop's time base = the last frame before the up (window.__tabLens.tf): the retarget keeps the loop's clock, the state at that frame is `up` */
    const up = rect(); const Lup = window.__tabLens; ev(other, "pointerup", ox, oy); await new Promise((r) => requestAnimationFrame(r));
    const drop = await sample(700, Lup ? Lup.tf : performance.now());
    num(`落回 宽 对 ζ1/.4 闭式 rms（${drop.filter((s) => s.p !== null).length} 帧）`, 0, rms(drop.filter((s) => s.p !== null).map((s) => s.width - crit(up.width, w0, 0.4, s.t))), 1);
    num("落回 高 对 ζ1/.4 闭式 rms", 0, rms(drop.filter((s) => s.p !== null).map((s) => s.height - crit(up.height, h0, 0.4, s.t))), 1);
    /* ④ rest */
    await sleep(200); const onNow = bs.find((b) => b.classList.contains("on")); const rr = rect();
    check("落回后驱动停（nav 无 .tl-on）", "无", nav.classList.contains("tl-on") ? "还在" : "无", !nav.classList.contains("tl-on"));
    num("静止：glide 宽 = 选中项宽", onNow ? onNow.offsetWidth : w0, rr.width, 0.5); num("静止：glide 高 = 54", h0, rr.height, 0.5);
    num("静止：glide 左 = 选中项 offsetLeft", onNow ? nav.getBoundingClientRect().left + onNow.offsetLeft + seg.offsetLeft : rr.left, rr.left, 1);
    /* ⑤ template */
    check("手势后 .plat 是同一节点（未重建）", "同", nav.querySelector(".plat") === plat0 ? "同" : "新节点", nav.querySelector(".plat") === plat0);
    const selB = bs.find((b) => b.classList.contains("on")); const sr = selB.getBoundingClientRect(), sx = sr.left + sr.width / 2, sy = sr.top + sr.height / 2;
    ev(selB, "pointerdown", sx, sy, 5); const dSel = await waitClass("lift-sel", 600); const selDelay = px("--ios-touch-tab-selected-lift-delay", 125);
    check(`按下已选中项 +${selDelay} ms 抬起（.lift-sel）`, `${selDelay}…${selDelay + 50} ms`, dSel === null ? "没抬" : Math.round(dSel) + " ms", dSel !== null && dSel >= selDelay - 5 && dSel <= selDelay + 50);
    await sleep(150); const hiddenDesc = Object.getOwnPropertyDescriptor(Document.prototype, "hidden"); Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); await sleep(30);
    check("抬起中 hidden → 驱动停、glide 回 view.js 的框", "无 .tl-on", nav.classList.contains("tl-on") ? "还在" : "无 .tl-on", !nav.classList.contains("tl-on"));
    delete document.hidden; if (hiddenDesc) Object.defineProperty(Document.prototype, "hidden", hiddenDesc);
    ev(selB, "pointerup", sx, sy, 5); await sleep(700);
    /* ---- R33 (tab-lens-motion.md §3a): a quick tap on another item — the lens lifts (ζ 1 / .25) and slides (ζ .85 / .4) from the tap together, and falls
       (ζ 1 / .4) from the frame the slide arrives (first within .5 pt of the target), not at the up; the selection changes at the up (view.js) */
    { const sel0 = bs.find((b) => b.classList.contains("on")), tgt = bs[bs.indexOf(sel0) === 0 ? 1 : 0], tr = tgt.getBoundingClientRect(), tx = tr.left + tr.width / 2, ty = tr.top + tr.height / 2, navL2 = nav.getBoundingClientRect().left;
      const cxNav2 = () => rect().cx - navL2; const c0 = cxNav2();
      ev(tgt, "pointerdown", tx, ty, 12); await sleep(40); ev(tgt, "pointerup", tx, ty, 12);
      let L0 = null; for (let i = 0; i < 30 && !L0; i++) { await new Promise((r) => requestAnimationFrame(r)); L0 = window.__tabLens; }   // the selection's render and the driver's first frame follow the up within a few frames
      const samples = []; await new Promise((res) => { let first = null; const tick = (now) => { if (first === null) first = now; const L = window.__tabLens; samples.push({ t: now, cx: cxNav2(), h: rect().height, p: L ? L.p : null, ph: L ? L.phase : null, x: L ? L.x : null, target: L ? L.target : null }); if (now - first < 900) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
      const target = tx - navL2; const tapFrames = samples.filter((s) => s.ph === "tap"), dropIdx = samples.findIndex((s) => s.ph === "drop"), atDrop = dropIdx > 0 ? samples[dropIdx - 1] : null, firstDrop = dropIdx >= 0 ? samples[dropIdx] : null;
      check("R33 快速点另一项：松手后驱动进 tap 相（抬起 + 滑行同步起步）", "tap · p > 0 · x 在动", L0 ? `${L0.phase} · p ${L0.p.toFixed(3)} · x ${cxNav2().toFixed(1)}→${target.toFixed(1)}` : "无驱动", !!L0 && (L0.phase === "tap" || L0.phase === "drop") && tapFrames.length >= 3);
      check(`R33 到位那帧起落回（到位 = 位置弹簧首次 |x − 目标| ≤ .5 pt）：drop 首帧 |Δx| ≤ .5、drop 前高仍在抬起（${atDrop ? atDrop.h.toFixed(1) : "-"} > 54）`, "|Δx| ≤ .5 · h > 54", firstDrop && atDrop ? `|Δx| ${Math.abs(firstDrop.x - firstDrop.target).toFixed(2)}（前一帧 ${Math.abs(atDrop.x - atDrop.target).toFixed(2)}）· h ${atDrop.h.toFixed(1)} · ${tapFrames.length} tap 帧` : "无 drop", !!firstDrop && !!atDrop && Math.abs(firstDrop.x - firstDrop.target) <= 0.5 && Math.abs(atDrop.x - atDrop.target) > 0.5 && atDrop.h > 54);
      const dropS = samples.slice(dropIdx).filter((s) => s.ph === "drop"); const pDrop = dropS.map((s) => s.p);
      check("R33 落回：高沿 ζ1/.4 单调回到 54（p 单调降）", "单调 · 末 54", `${pDrop.length} 帧 · 末 h ${samples[samples.length - 1].h.toFixed(1)}`, pDrop.length >= 5 && pDrop.every((v, i) => i === 0 || v <= pDrop[i - 1] + 1e-6) && Math.abs(samples[samples.length - 1].h - 54) <= 0.5);
      const onNow = bs.find((b) => b.classList.contains("on")); check("R33 松手即选中被点项、胶囊落定在其中心", tgt.dataset.tab, `${onNow ? onNow.dataset.tab : "-"} · ${cxNav2().toFixed(1)} vs ${target.toFixed(1)}`, onNow === tgt && Math.abs(cxNav2() - target) <= 1.5);
      delete seg.dataset.pe; await sleep(200);
      /* back to the original tab for the flows below (a second quick tap; the same path) */
      const sr0 = sel0.getBoundingClientRect(); ev(sel0, "pointerdown", sr0.left + sr0.width / 2, sr0.top + sr0.height / 2, 13); await sleep(40); ev(sel0, "pointerup", sr0.left + sr0.width / 2, sr0.top + sr0.height / 2, 13); await sleep(1200); delete seg.dataset.pe; }
    /* ---- R2 (b) the material overlay (tab-lens.js glAttach → lens-webgl.js): the canvas over the bar, the tab5 family's nine sets with the filters' keys
       (data-s 40, 48 for the 98 set, fringe 16; heights 54 … 70 from lens-field.json), the lift riding the 98 set with frames drawn, cleared at rest */
    { const g = window.__tabLensGL && window.__tabLensGL();
      if (!g) check("R2 标签栏透镜材质：WebGL 覆盖层（?tlens-gl=0 关）", "有", window.LensWebGL ? "缺（无 webgl2 或家族未载）" : "缺 LensWebGL", false);
      else { await g.lens.ready; const L = g.lens; const sets = Object.keys(L.sets).map(Number).sort((a, b) => a - b);
        check("R2 材质：tab5 家族九组已载（82 … 98）", "82,84,…,98", sets.join(","), sets.length === 9 && sets[0] === 82 && sets[8] === 98);
        check("R2 材质键 = 家族滤镜 data-s（bg/lab S 40，98 组 48；色散 S_ab 16）、高 54 … 70（lens-field.json）", "S 40/48 · Sab 16 · h 54/70", `S ${L.sets[82] && L.sets[82].S}/${L.sets[98] && L.sets[98].S} · Sab ${L.sets[82] && L.sets[82].Sab} · h ${L.sets[82] && L.sets[82].h}/${L.sets[98] && L.sets[98].h}`, !!L.sets[82] && !!L.sets[98] && L.sets[82].S === 40 && L.sets[98].S === 48 && L.sets[82].Sab === 16 && L.sets[82].h === 54 && L.sets[98].h === 70);
        const cr = g.canvas.getBoundingClientRect(), nr = nav.getBoundingClientRect();
        num("R2 材质：canvas 盖 nav 每边 +24（抬起 98×70 与色散包 16 都在内）", 24, nr.left - cr.left, 0.5); num("R2 材质：canvas 高 = nav + 48", nr.height + 48, cr.height, 0.5);
        const selB3 = bs.find((b) => b.classList.contains("on")); const r3 = selB3.getBoundingClientRect(); const f0 = L.stats.frames;
        ev(selB3, "pointerdown", r3.left + r3.width / 2, r3.top + r3.height / 2, 11); await waitClass("lift-sel", 600); await sleep(300);
        const fLift = L.stats.frames - f0, setLift = L.stats.set, lastLift = L.stats.last;
        check("R2 材质：抬起中包在画帧（stats.frames 增）、走 98 组（抬起骑最大组，README §0.3）、pd = lift", "frames > 5 · set 98 · pd = lift", `frames +${fLift} · set ${setLift} · lift ${lastLift ? lastLift.lift.toFixed(3) : "-"} pd ${lastLift ? lastLift.pd.toFixed(3) : "-"}`, fLift > 5 && setLift === 98 && !!lastLift && Math.abs(lastLift.lift - lastLift.pd) < 1e-6);
        ev(selB3, "pointerup", r3.left + r3.width / 2, r3.top + r3.height / 2, 11); await sleep(900); delete seg.dataset.pe;
        check("R2 材质：落定后画布清（最后一帧 lift 0）、无 JS 错", "lift 0 · no error", `lift ${L.stats.last ? L.stats.last.lift : "-"} · ${window.__tabLensErr || "no error"}`, !!L.stats.last && L.stats.last.lift === 0 && !window.__tabLensErr);
        check("R2 材质：平台里透出的页面、项复本 1.16 缩放——未画（不可表达 / 待做，tab-lens.js 注释）", "记录", "记录", true);
        /* R37: the tab lens is a capsule r = h/2 (tab-lens-native.md §0 cornerRadii 35 = 70/2 — the outline terms took the segment lens's r 22 before), its label stack
           ContentLensing −14 / 11.2 then ClearGlass −17.5 / 11.2 (tab-lens-native.md §3, tab/lens-field.json), the field in float (closed) */
        check("R2/R37 材质：胶囊 r = h/2（rmax ≥ 35）、标签两级 −14/11.2 → −17.5/11.2、场按式逐像素（closed）", "rmax ≥ 35 · −14/11.2,−17.5/11.2 · closed", `rmax ${L.stats.rmax} · ${(L.stats.labelStages || []).join("/")} · ${L.stats.labMode}`, L.stats.rmax >= 35 && (L.stats.labelStages || []).join(",") === "-14,11.2,-17.5,11.2" && L.stats.labMode === "closed"); } }
    /* ---- #7b the drag (tab-lens-motion.md §6.5 / §6.6): while the selected item is held and lifted, the capsule's centre springs (ζ .85 / .2, retargeted
       on every move) to finger x − a·W + W/2 (a = where in the item the finger went down; pressed at the centre a = .5 → the target is the finger), the
       left edge hard-clamped to the items' run; at the up ζ .9 / .4 to the centre of the item under the finger, which becomes the selection */
    { const selB2 = bs.find((b) => b.classList.contains("on")), idx2 = bs.indexOf(selB2), nbr = bs[idx2 === bs.length - 1 ? idx2 - 1 : idx2 + 1], dir = bs.indexOf(nbr) > idx2 ? 1 : -1;
      const sr2 = selB2.getBoundingClientRect(), sx2 = sr2.left + sr2.width / 2, sy2 = sr2.top + sr2.height / 2, navL = nav.getBoundingClientRect().left, w0b = selB2.offsetWidth;
      const underDamped = (x0, v0, target, zeta, resp, t) => { const w = 2 * Math.PI / resp, wd = w * Math.sqrt(1 - zeta * zeta), dx = x0 - target, e = Math.exp(-zeta * w * t); return target + e * (dx * Math.cos(wd * t) + ((v0 + zeta * w * dx) / wd) * Math.sin(wd * t)); };
      const cxNav = () => rect().cx - navL;
      const sampleX = (ms, t0) => new Promise((resolve) => { const out = []; let first = null; const tick = (now) => { if (first === null) first = now; out.push({ t: (now - t0) / 1000, cx: cxNav() }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); }; requestAnimationFrame(tick); });
      ev(selB2, "pointerdown", sx2, sy2, 6); const dl = await waitClass("lift-sel", 600); await sleep(450);   // lifted and settled
      if (dl === null) check("7b：按住已选中项抬起", "lift-sel", "没抬", false);
      else {
        const Lm = window.__tabLens; const xm = Lm ? Lm.x : cxNav(), vm = Lm ? Lm.xv : 0, tfm = Lm ? Lm.tf : performance.now();
        const fx1 = sx2 + dir * 40; ev(selB2, "pointermove", fx1, sy2, 6); await new Promise((r) => requestAnimationFrame(r));
        const Lt = window.__tabLens; const want1 = fx1 - navL;   // a = .5: target = the finger (nav coordinates)
        num("7b 拖动目标 = 手指 x − a·W + W/2（按在中心 a = .5 → 手指 x，nav 坐标）", want1, Lt ? Lt.target : NaN, 0.5);
        check("7b 拖动中 nav.drag + 驱动 phase drag", "drag", `${nav.classList.contains("drag") ? "drag" : "-"} ${Lt ? Lt.phase : "-"}`, nav.classList.contains("drag") && !!Lt && Lt.phase === "drag");
        /* R64: the presented centre now carries the flex drift (sX·dx) — the position spring is judged on the driver's own x, the drift on the rect */
        const mv = []; await new Promise((resolve) => { let first = null; const tick = (now) => { if (first === null) first = now; const L = window.__tabLens; mv.push({ t: (now - tfm) / 1000, cx: cxNav(), x: L ? L.x : cxNav(), xc: L ? L.xc : cxNav(), fx: L && L.flex ? { ...L.flex, trace: undefined } : null, wp: L ? L.wp : NaN, hp: L ? L.hp : NaN, w: L ? L.w : NaN, h: L ? L.h : NaN, r: rect() }); if (now - first < 400) requestAnimationFrame(tick); else resolve(); }; requestAnimationFrame(tick); });
        num(`7b 拖动 位置弹簧 x 对 ζ.85/.2 闭式 rms（${mv.length} 帧，自移动前一帧的 x / v 起；驱动器本帧值）`, 0, rms(mv.map((s) => s.x - underDamped(xm, vm, want1, 0.85, 0.2, s.t))), 1);
        { const withF = mv.filter((s) => s.fx), peak = withF.reduce((m, s) => (s.fx.sx > m ? s.fx.sx : m), 1), dip = withF.reduce((m, s) => (s.fx.sy < m ? s.fx.sy : m), 1), spec0 = withF.length ? withF[0].fx.spec : null;
          check("R64 拖动中 flex 变体 = loupe（模型 (w0+16)×(h0+16) → d 70 → t 1；flex-interaction.md §2 / tab-lens-motion.md §6.4：pts 100、min .75、max 1.15、N 2500、ζ 1/.5、tracking .9/.5），手指在时走 tracking 弹簧", "pts 100 · .75/1.15 · N 2500 · ζ 1/.5 · tracking .9/.5 · sp .9/.5", spec0 ? `pts ${spec0.pts} · ${spec0.min}/${spec0.max} · N ${spec0.N} · ζ ${spec0.zeta}/${spec0.resp} · tracking ${spec0.tzeta}/${spec0.tresp} · sp ${withF[0].fx.sp.join("/")}` : "no flex", !!spec0 && spec0.pts === 100 && spec0.min === .75 && spec0.max === 1.15 && spec0.N === 2500 && spec0.zeta === 1 && spec0.resp === .5 && spec0.tzeta === .9 && spec0.tresp === .5 && withF[0].fx.sp[0] === .9 && withF[0].fx.sp[1] === .5);
          check("R64 拖动加速时 X 伸 Y 缩（§3：sX = lerp(1, hi, a/N) 钳 [.9, 1.1] 目标，sY 反向）：拖动段 sX 峰 > 1、sY 谷 < 1，目标不出 [.9, 1.1]", "peak sX > 1.005 · dip sY < .995 · targets in [.9, 1.1]", `peak sX ${peak.toFixed(4)} · dip sY ${dip.toFixed(4)} · targets ${withF.every((s) => s.fx.target.sX >= .9 - 1e-9 && s.fx.target.sX <= 1.1 + 1e-9 && s.fx.target.sY >= .9 - 1e-9 && s.fx.target.sY <= 1.1 + 1e-9) ? "in" : "OUT"}`, withF.length > 10 && peak > 1.005 && dip < .995 && withF.every((s) => s.fx.target.sX >= .9 - 1e-9 && s.fx.target.sX <= 1.1 + 1e-9 && s.fx.target.sY >= .9 - 1e-9 && s.fx.target.sY <= 1.1 + 1e-9));
          const geoOK = withF.every((s) => Math.abs(s.r.width - s.w * s.fx.sx) < .6 && Math.abs(s.r.height - s.h * s.fx.sy) < .6 && Math.abs((s.cx) - (s.x + s.fx.sx * s.fx.dx)) < .6);
          check("R64 呈现盒 = W·sX × H·sY，中心 = 位置弹簧 + sX·drift（§6.6 / §6.4 先缩放后平移）——逐帧对驱动器本帧值（± .6 px）", "every frame", geoOK ? "every frame" : "OFF", withF.length > 10 && geoOK);
          /* the three floats integrate the analytic flex spring toward that frame's targets from the previous frame's state (the driver's own dt) */
          const tr = window.__tabLens && window.__tabLens.flex ? window.__tabLens.flex.trace : [], stepRef = (x, v, target, [z, r], dt) => { const w = 2 * Math.PI / r, dx = x - target; if (z < 1) { const wd = w * Math.sqrt(1 - z * z), B = (v + z * w * dx) / wd, e = Math.exp(-z * w * dt); return target + e * (dx * Math.cos(wd * dt) + B * Math.sin(wd * dt)); } const e = Math.exp(-w * dt), B = v + w * dx; return target + e * (dx + B * dt); };
          let maxErr = 0, n = 0; for (let i = 1; i < tr.length; i++) { const a0 = tr[i - 1], b0 = tr[i]; if (!(b0.dt > 0)) continue; maxErr = Math.max(maxErr, Math.abs(stepRef(a0.sx, a0.vsx, b0.tSx, b0.sp, b0.dt) - b0.sx), Math.abs(stepRef(a0.sy, a0.vsy, b0.tSy, b0.sp, b0.dt) - b0.sy), Math.abs(stepRef(a0.dx, a0.vdx, b0.tDx, b0.sp, b0.dt) - b0.dx)); n++; }
          check(`R64 三个 flex 浮点逐帧 = 解析弹簧一步（自上一帧的值 / 速度，向本帧目标，本帧 dt；${n} 帧，最大差）`, "≤ 1e-6", maxErr.toExponential(2), n > 10 && maxErr <= 1e-6); }
        const segR = seg.getBoundingClientRect(), padR = parseFloat(getComputedStyle(seg).paddingRight) || 0, padL = parseFloat(getComputedStyle(seg).paddingLeft) || 0;
        const far = dir > 0 ? sx2 + 400 : sx2 - 400; ev(selB2, "pointermove", far, sy2, 6); await new Promise((r) => requestAnimationFrame(r)); const Lc = window.__tabLens;
        const clampWant = dir > 0 ? segR.right - navL - padR - w0b / 2 : segR.left - navL + padL + w0b / 2;
        num("7b 拖过端点：目标硬钳在轨道端（§6.6 无橡皮筋）", clampWant, Lc ? Lc.target : NaN, 0.5);
        const nr = nbr.getBoundingClientRect(), nx = nr.left + nr.width / 2; ev(selB2, "pointermove", nx, sy2, 6); await sleep(350);   // over the neighbour, settled there
        const Lu = window.__tabLens; const xu = Lu ? Lu.x : cxNav(), vu = Lu ? Lu.xv : 0, tfu = Lu ? Lu.tf : performance.now();
        ev(selB2, "pointerup", nx, sy2, 6); await new Promise((r) => requestAnimationFrame(r)); const Lr = window.__tabLens;
        num("7b 松手目标 = 手指下那项的中心（§6.5 落点）", nx - navL, Lr ? Lr.target : NaN, 0.5);
        const rl = await sampleX(500, tfu);
        num(`7b 松手 中心 x 对 ζ.9/.4 闭式 rms（${rl.length} 帧，自松手前一帧的 x / v 起）`, 0, rms(rl.map((s) => s.cx - underDamped(xu, vu, nx - navL, 0.9, 0.4, s.t))), 1);
        await sleep(400); const onB = bs.find((b) => b.classList.contains("on"));
        check("7b 松手后选中 = 手指下那项", nbr.dataset.tab || "邻项", onB ? (onB.dataset.tab || "?") : "-", onB === nbr);
        num("7b 落定：胶囊中心 = 该项中心", nx - navL, cxNav(), 1); check("7b 落定后驱动停（无 .tl-on）", "无", nav.classList.contains("tl-on") ? "还在" : "无", !nav.classList.contains("tl-on"));
        num("R64 落定后 flex 归位：胶囊宽 = 项宽（sX → 1，drift → 0）", w0b, rect().width, 1);
        /* template: hidden mid-drag strips the driver */
        const b3 = bs.find((b) => b.classList.contains("on")); const r3 = b3.getBoundingClientRect(), x3 = r3.left + r3.width / 2, y3 = r3.top + r3.height / 2;
        ev(b3, "pointerdown", x3, y3, 7); await waitClass("lift-sel", 600); ev(b3, "pointermove", x3 + 20, y3, 7); await sleep(100);
        const hd = Object.getOwnPropertyDescriptor(Document.prototype, "hidden"); Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
        document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); await sleep(30);
        check("7b 拖动中 hidden → 驱动停", "无 .tl-on", nav.classList.contains("tl-on") ? "还在" : "无 .tl-on", !nav.classList.contains("tl-on"));
        delete document.hidden; if (hd) Object.defineProperty(Document.prototype, "hidden", hd);
        ev(b3, "pointerup", x3, y3, 7); await sleep(600);
      } }
    /* ---- R59′b Reduce Motion (page-inventory.md §12b ② decompiled: no setLifted:, no .95 platter scale; R59″ records tabhold / tabtap: the lens still slides
       259 → 87 from the down, both records = the closed spring ζ .9 / .2 to .11 pt rms — tab-lens.js header): forced through window.__forceRM like view.js's
       段 rows. Pressing another item: the driver starts at the down (phase rm), the centre follows ζ .9 / .2 to the item's centre, width / height never
       leave w0 × 54 and p stays 0 (no lift, no flex); while the finger is held the driver stays on and the lens is parked on the item; the up selects it and
       the driver stops at rest on view.js's box; a drag under RM: no lift, the target = the finger rule. */
    { window.__forceRM = true; try {
      const closedRM = (x0, target, t) => { const w = 2 * Math.PI / 0.2, z = 0.9, wd = w * Math.sqrt(1 - z * z), e = Math.exp(-z * w * t); return target + (x0 - target) * e * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t)); };
      const navL4 = nav.getBoundingClientRect().left, cx4 = () => rect().cx - navL4;
      const sel4 = bs.find((b) => b.classList.contains("on")), tgt4 = bs[bs.indexOf(sel4) === 0 ? 1 : 0], tr4 = tgt4.getBoundingClientRect(), tx4 = tr4.left + tr4.width / 2, ty4 = tr4.top + tr4.height / 2, w04 = tgt4.offsetWidth, c04 = cx4();
      const tDown = performance.now(); ev(tgt4, "pointerdown", tx4, ty4, 21); let L4 = null, nf = 0; for (; nf < 4 && !L4; nf++) { await new Promise((r) => requestAnimationFrame(r)); L4 = window.__tabLens; }   // the driver's first integrated frame: a rAF stamped before the start re-ticks (tab-lens.js frame0), so the state appears on the first or second frame
      check(`R59′b RM 按下另一项：驱动在按下后 ≤ 2 帧起（不等 +140 抬起；起点 +${L4 ? Math.round(L4.t0 - tDown) : "-"} ms）、phase rm、p 0、目标 = 该项中心`, "≤ 2 帧 · rm · p 0 · 目标 = 中心", L4 ? `${nf} 帧 · ${L4.phase} · p ${L4.p.toFixed(3)} · 目标 ${L4.target.toFixed(1)} vs ${(tx4 - navL4).toFixed(1)}` : `无驱动（${JSON.stringify(window.__tabLensRM || null)} stop ${JSON.stringify(window.__tabLensStop || null)} err ${window.__tabLensErr || "-"}）`, !!L4 && nf <= 2 && L4.phase === "rm" && L4.rm === true && L4.p === 0 && Math.abs(L4.target - (tx4 - navL4)) <= 0.5 && L4.t0 - tDown <= 40);
      const sl = []; await new Promise((res) => { let first = null; const tick = (now) => { if (first === null) first = now; const L = window.__tabLens; sl.push({ t: (now - (L4 ? L4.t0 : tDown)) / 1000, cx: cx4(), w: rect().width, h: rect().height, p: L ? L.p : null, ph: L ? L.phase : null, on: nav.classList.contains("tl-on") }); if (now - first < 450) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
      num(`R59′b RM 滑动 中心 x 对 ζ.9/.2 闭式 rms（${sl.length} 帧，自驱动起点；R59″ 两条记录对同一闭式 rms .11 pt）`, 0, rms(sl.map((s) => s.cx - closedRM(c04, tx4 - navL4, s.t))), 1);
      check(`R59′b RM 全程不抬不拉伸：每帧 宽 = ${w04}、高 = ${h0}、p = 0（§12b ②：无 setLifted、无 .95 平台缩放）`, "every frame", sl.every((s) => Math.abs(s.w - w04) <= 0.5 && Math.abs(s.h - h0) <= 0.5 && s.p === 0) ? "every frame" : `OFF（宽 ${Math.max(...sl.map((s) => s.w)).toFixed(1)} 高 ${Math.max(...sl.map((s) => s.h)).toFixed(1)} p ${Math.max(...sl.map((s) => s.p || 0)).toFixed(3)}）`, sl.length > 10 && sl.every((s) => Math.abs(s.w - w04) <= 0.5 && Math.abs(s.h - h0) <= 0.5 && s.p === 0));
      check("R59′b RM 按住 450 ms：驱动仍在（.tl-on）、透镜停在按下项中心（|Δ| ≤ .5；选择在 touch-down 发生，抬手才换页）", "tl-on · |Δ| ≤ .5", `${nav.classList.contains("tl-on") ? "tl-on" : "off"} · |Δ| ${Math.abs(cx4() - (tx4 - navL4)).toFixed(2)}`, nav.classList.contains("tl-on") && Math.abs(cx4() - (tx4 - navL4)) <= 0.5);
      /* a drag under RM: the target follows the finger rule, still no lift */
      ev(tgt4, "pointermove", tx4 + 30, ty4, 21); await new Promise((r) => requestAnimationFrame(r)); const Lm4 = window.__tabLens;
      check("R59′b RM 拖动：目标 = 手指规则（x − a·W + W/2）、无 lift（高 54、p 0）", "目标 = 手指 + 30 · h 54 · p 0", Lm4 ? `目标 ${Lm4.target.toFixed(1)} vs ${(tx4 + 30 - navL4).toFixed(1)} · h ${rect().height.toFixed(1)} · p ${Lm4.p}` : "无驱动", !!Lm4 && Math.abs(Lm4.target - (tx4 + 30 - navL4)) <= 0.5 && Math.abs(rect().height - h0) <= 0.5 && Lm4.p === 0);
      ev(tgt4, "pointermove", tx4, ty4, 21); await sleep(300);
      ev(tgt4, "pointerup", tx4, ty4, 21); await sleep(600); const on4 = bs.find((b) => b.classList.contains("on"));
      check("R59′b RM 抬手：选中被按项、驱动停（无 .tl-on）、胶囊在其中心", `${tgt4.dataset.tab} · off · 中心`, `${on4 ? on4.dataset.tab : "-"} · ${nav.classList.contains("tl-on") ? "tl-on" : "off"} · |Δ| ${Math.abs(cx4() - (tx4 - navL4)).toFixed(2)}`, on4 === tgt4 && !nav.classList.contains("tl-on") && Math.abs(cx4() - (tx4 - navL4)) <= 1);
      delete seg.dataset.pe;
      /* back to the original tab, still under RM (the same path) */
      const sr4 = sel4.getBoundingClientRect(); ev(sel4, "pointerdown", sr4.left + sr4.width / 2, sr4.top + sr4.height / 2, 22); await sleep(350); ev(sel4, "pointerup", sr4.left + sr4.width / 2, sr4.top + sr4.height / 2, 22); await sleep(700); delete seg.dataset.pe;
      check("R59′b RM 再按回原项：回到原项、驱动停", `${sel4.dataset.tab} · off`, `${(bs.find((b) => b.classList.contains("on")) || {}).dataset?.tab || "-"} · ${nav.classList.contains("tl-on") ? "tl-on" : "off"}`, bs.find((b) => b.classList.contains("on")) === sel4 && !nav.classList.contains("tl-on"));
      /* the record itself against the same closed form (tools/touch/seg-native-r59-motion.json, tabhold: frames +75.3 … +275.2 ms after the down; start +42.6 — a 41 ms stall in the touch log — tap: +42.1 … +242.1, start +21.2) */
      const rec = [[75.3, 209.49], [91.9, 175.24], [108.6, 146.58], [125.3, 125.07], [142.0, 110.08], [158.6, 100.23], [175.3, 94.10], [192.0, 90.48], [208.7, 88.46], [225.2, 87.42], [241.9, 86.94], [258.5, 86.77], [275.2, 87.0]];
      const recRms = rms(rec.map(([t, x]) => x - closedRM(259, 87, (t - 42.6) / 1000)));
      num("R59′b 记录核：R59″ tabhold 13 帧（259 → 87）对 ζ.9/.2 闭式 rms（pt；ζ.85/.2 为 2.15）", 0, recRms, 0.2);
    } finally { window.__forceRM = null; } }
    /* ---- R0② the tab set changes under the bar (the user's bug 2: 切晚班再切早班 the capsule flashed downward — the bar was rebuilt): view.js keeps the
       nodes (R0①) and tells the driver with "tabs-changed"; per frame through 早 → 晚 → 早: nav's top unchanged, never display none, .plat / .glide / .seg
       the same elements, the button count never 0, the glide 54 high and on the selected button (≤ 1 pt), the driver idle (no __tabLens, no .tl-on) */
    { const qseg = document.querySelector("#queueseg"); const qbs = qseg ? [...qseg.querySelectorAll("button")] : [];
      if (qbs.length >= 2) {
        const plat = nav.querySelector(".plat"), gl0 = nav.querySelector(".glide"), sg0 = nav.querySelector(".seg"), top0 = nav.getBoundingClientRect().top, cur0 = qbs.findIndex((b) => b.classList.contains("on"));
        const bad = { top: 0, none: 0, node: 0, zero: 0, h: 0, pos: 0, drv: 0 }; let frames = 0, events = 0; const onEv = () => events++; nav.addEventListener("tabs-changed", onEv);
        const watch = (ms) => new Promise((res) => { let first = null; const tick = (now) => { if (first === null) first = now; frames++;
          const r = nav.getBoundingClientRect(), g = nav.querySelector(".glide"), on = nav.querySelector(".seg button.on"), n = nav.querySelectorAll(".seg button").length;
          if (Math.abs(r.top - top0) > 0.5) bad.top++; if (getComputedStyle(nav).display === "none") bad.none++;
          if (nav.querySelector(".plat") !== plat || g !== gl0 || nav.querySelector(".seg") !== sg0) bad.node++; if (n === 0) bad.zero++;
          if (g) { const gr = g.getBoundingClientRect(); if (Math.abs(gr.height - 54) > 0.5) bad.h++; if (on) { const or = on.getBoundingClientRect(); if (Math.abs(gr.left - or.left) > 1 || Math.abs(gr.width - or.width) > 1) bad.pos++; } }
          if (window.__tabLens || nav.classList.contains("tl-on")) bad.drv++;
          if (now - first < ms) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
        const other = qbs[cur0 === 0 ? 1 : 0], back = qbs[cur0];
        delete qseg.dataset.pe; other.click(); await watch(500); delete qseg.dataset.pe; back.click(); await watch(500);   // the press flag of an earlier synthetic press (no browser click consumed it) would eat the click
        nav.removeEventListener("tabs-changed", onEv);
        const tabsNow = [...nav.querySelectorAll(".seg button")].map((b) => b.dataset.tab).join(",");
        check(`R0② 切班次两次（${frames} 帧）：nav top 不变 / 无 display none / 节点不重建 / 按钮数不为 0 / glide 高 54 / glide 在选中项 / 驱动不起`, "全 0", `${JSON.stringify(bad)} · tabs-changed ×${events} · ${tabsNow}`, Object.values(bad).every((v) => v === 0));
        check("R0② 集合变时 nav 派发 tabs-changed（ui 807da64 接口）", "≥ 1", String(events), events >= 1 || tabsNow.split(",").length === 0);
      } else check("R0② 页面无两段可切（demo 应有早班/晚班）", "≥ 2 段", qbs.length + " 段", false); }
    if (typeof window.__tabKbd === "function") { window.__tabKbd(innerHeight - 300); await sleep(50); check("视口矮 300 后 nav.tabs display none（键盘规则）", "none", getComputedStyle(nav).display, getComputedStyle(nav).display === "none");
      window.__tabKbd(null); await sleep(50); const nb = nav.getBoundingClientRect(); check("复原后 nav.tabs 回到底部（innerHeight − bottom < 120）", "< 120", Math.round(innerHeight - nb.bottom), getComputedStyle(nav).display !== "none" && innerHeight - nb.bottom < 120); }
  });
})();
