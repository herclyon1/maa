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
        const mv = await sampleX(400, tfm);
        num(`7b 拖动 中心 x 对 ζ.85/.2 闭式 rms（${mv.length} 帧，自移动前一帧的 x / v 起）`, 0, rms(mv.map((s) => s.cx - underDamped(xm, vm, want1, 0.85, 0.2, s.t))), 1);
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
        /* template: hidden mid-drag strips the driver */
        const b3 = bs.find((b) => b.classList.contains("on")); const r3 = b3.getBoundingClientRect(), x3 = r3.left + r3.width / 2, y3 = r3.top + r3.height / 2;
        ev(b3, "pointerdown", x3, y3, 7); await waitClass("lift-sel", 600); ev(b3, "pointermove", x3 + 20, y3, 7); await sleep(100);
        const hd = Object.getOwnPropertyDescriptor(Document.prototype, "hidden"); Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
        document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); await sleep(30);
        check("7b 拖动中 hidden → 驱动停", "无 .tl-on", nav.classList.contains("tl-on") ? "还在" : "无 .tl-on", !nav.classList.contains("tl-on"));
        delete document.hidden; if (hd) Object.defineProperty(Document.prototype, "hidden", hd);
        ev(b3, "pointerup", x3, y3, 7); await sleep(600);
      } }
    if (typeof window.__tabKbd === "function") { window.__tabKbd(innerHeight - 300); await sleep(50); check("视口矮 300 后 nav.tabs display none（键盘规则）", "none", getComputedStyle(nav).display, getComputedStyle(nav).display === "none");
      window.__tabKbd(null); await sleep(50); const nb = nav.getBoundingClientRect(); check("复原后 nav.tabs 回到底部（innerHeight − bottom < 120）", "< 120", Math.round(innerHeight - nb.bottom), getComputedStyle(nav).display !== "none" && innerHeight - nb.bottom < 120); }
  });
})();
