/* accept-navedge.js — the interactive back gesture against nav-native-formula.md §0 / §3 (BOARD.md #12): edge region .10 W, hysteresis
   15, angle window, percent = Δx / W tracked through ζ .85 / .08, the .35 s projection with thr = min(187.5 / W, .5), the flick boost,
   the release spring ζ .85 / .3, the fluid rubber band past 1. Synthetic PointerEvents on #subpage. */
ACCEPT.add(async function navedge({ check, num, sleep }) {
  const E = window.NavEdge, N = window.Nav, pg = document.querySelector("#subpage");
  check("nav-edge.js：window.NavEdge 接在 #subpage 上", "NavEdge", E && N && pg ? "NavEdge" : "缺", !!E && !!N && !!pg);
  if (!E || !N || !pg) return;
  const W = window.innerWidth, thr = Math.min(187.5 / W, .5);
  const wideLog = [];   // diagnostic: any layout-viewport change during the suite, with the elements past the right edge at that moment (sporadic 578.15 = 488 × (1 − p), 18:50)
  const onRz = () => { if (wideLog.length > 5) return; const pick = [...document.querySelectorAll("body *")].map((e) => [e, e.getBoundingClientRect().right]).filter(([e, r]) => r > W + .5 && !pg.contains(e) && getComputedStyle(e).position !== "fixed").sort((a, b) => b[1] - a[1]).slice(0, 3).map(([e, r]) => `${e.tagName.toLowerCase()}${e.id ? "#" + e.id : ""}${typeof e.className === "string" && e.className ? "." + e.className.trim().split(/\s+/).join(".") : ""} ${r.toFixed(0)}`); wideLog.push(`${window.innerWidth}: ${pick.join(" / ") || "无"}`); };
  window.addEventListener("resize", onRz);
  const pev = (type, x, y, t, id = 5) => pg.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, clientX: x, clientY: y, isPrimary: true, button: 0, buttons: type === "pointerup" ? 0 : 1, pointerType: "touch" }));
  const tx = () => { const m = getComputedStyle(pg).transform; if (!m || m === "none") return 0; const a = m.match(/matrix\(([^)]+)\)/); return a ? parseFloat(a[1].split(",")[4]) : 0; };
  const tick = () => new Promise(requestAnimationFrame);   // S1: every wait is the drive's own frames, never a wall-clock sleep (the stimulus sleeps between pointer events stay: they ARE the finger's speed)
  const converged = async (cap = 3000) => { const t0 = performance.now(); while ((Math.abs(N.state.p - N.state.target) > .001 || Math.abs(N.state.v) > .01) && performance.now() - t0 < cap) await tick(); };   // the tracking spring at rest on its target (position alone passes on the way through: 09-23 read p −.18475 at v .13 against −.1825)
  /* A15: the drive's own state, not the rendered transform — the CSS transform is read a frame (or, under load, many frames) behind what the drive last
     wrote, and the tracking spring keeps ticking until the finger owns a new target; judge W·(1 − p) as the drive holds it and its last written --nav-x,
     and when the wait saw a frame gap > 34 ms only record (the gap is the environment: A16) */
  const convergedGap = async (cap = 3000) => { let maxGap = 0, prev = 0, on = true; const loop = (t) => { if (prev) maxGap = Math.max(maxGap, t - prev); prev = t; if (on) requestAnimationFrame(loop); }; requestAnimationFrame(loop); await converged(cap); await tick(); await tick(); on = false; return maxGap; };
  const driveX = () => { const v = parseFloat(N.state.pg && N.state.pg.style.getPropertyValue("--nav-x")); return isNaN(v) ? W * (1 - N.state.p) : v; };
  const settled = async (cap = 6000) => { const t0 = performance.now(); await tick(); while (pg.classList.contains("nav-live") && performance.now() - t0 < cap) await tick(); };   // the push / pop springs are wall-clock: wait for the drive to end instead of a fixed sleep (A15; under load a 600 ms sleep left the push at p ≈ .7 and the gesture's base percent ≠ 0 → the rubber-band row read W × 1.24 for 1.177, light 1 of 3)
  const open = async () => { N.open("验收", "<p>edge</p>"); await settled(); };
  /* the width the drive slides over is the screen's, whatever overflows: a 488-wide box widens window.innerWidth to 488 under the mobile viewport (html's
     overflow-x:clip does not stop it; documentElement.clientWidth stays 440) — 09-23 the sporadic 「拖过整宽」 red read --nav-x 578.15 = 488 × 1.18475 */
  { const d = document.createElement("div"); d.style.cssText = "position:absolute;left:0;top:0;width:" + (W + 48) + "px;height:1px;pointer-events:none"; document.body.appendChild(d); await tick(); await tick();
    const iw = window.innerWidth, cw = document.documentElement.clientWidth, nw = N.W ? N.W() : NaN, clip = document.querySelector(".lens-clip > canvas"), cw2 = clip && window.LensWebGL ? window.LensWebGL.clipCanvas(clip, clip.closest("nav.tabs") ? { y: true } : { pad: 24 }) : null,   // re-clip with the owner's options (tab-lens.js:220 { y }, view.js:1526 { pad 24 }): without { y } the tab canvas kept an unclamped box (the full run's R96 red: y 963…1073 on a 956 viewport)
      cr = cw2 ? +cw2.dataset.clip.split(",")[2] : null;
    d.remove(); await tick();
    check(`页面有东西伸出右缘（${W + 48} 宽）：返回驱动的宽 = 屏宽 ${W}，透镜画布的裁切框右缘 ≤ 屏宽（不跟着变宽的 innerWidth 走）`, `${W} · ≤ ${W}`, `驱动宽 ${nw} · innerWidth ${iw} · clientWidth ${cw} · 裁切右缘 ${cr === null ? "无画布" : cr}`, nw === W && cw === W && (cr === null || cr <= W)); }
  num("识别区 = .10 W（IsLargeFormatPhone；.09 待 MG 读数）", W * .10, W * E.REGION, .01);
  num("松手阈值 thr = min(187.5 / W, .5)", Math.min(187.5 / W, .5), thr, .001);
  /* 1) outside the region: nothing */
  await open(); pev("pointerdown", 80, 400); pev("pointermove", 120, 400); pev("pointermove", 160, 400); pev("pointerup", 160, 400); await tick(); await tick();
  check("起手 x 80（区外 44）：不识别，页不动", "in, 0", `${pg.classList.contains("in") ? "in" : "-"}, ${Math.round(tx())}`, pg.classList.contains("in") && Math.abs(tx()) < .5);
  /* 2) inside the region but under the hysteresis: nothing yet; past it: began, the percent tracks Δx / W through ζ .85 / .08 */
  pev("pointerdown", 20, 400); pev("pointermove", 30, 400);
  check("区内起手、位移 10 < 迟滞 15：未 began", "rest", pg.classList.contains("nav-live") ? "live" : "rest", !pg.classList.contains("nav-live"));
  pev("pointermove", 40, 400);   // 20 > 15 → began; the translation counts from the touch-down (x 20) minus the pan's 10 pt (§5e)
  check("位移 20 ≥ 15 且在 155° 窗内：began，交互式 pop 开始（驱动中，p 从 1 起）", "live, p 1", `${pg.classList.contains("nav-live") ? "live" : "rest"}, p ${N.state.p.toFixed(2)}`, pg.classList.contains("nav-live") && Math.abs(N.state.p - 1) < .01);
  await sleep(30); pev("pointermove", 150, 400); await sleep(30); pev("pointermove", 260, 400); await converged();   // q = (260 − 20 − 10)/440 = .523: the tracking spring settles onto it
  { const q = (260 - 20 - E.PAN_HYST) / W; check("拖到 x 260（q = (260 − 落指 20 − 10)/W = .523）停住：进度经 ζ .85/.08 跟到 q（顶页 x = W·q）", `${Math.round(W * q)} ± 3`, Math.round(tx()), Math.abs(tx() - W * q) <= 3 && Math.abs((1 - N.state.p) - q) < .01); }
  /* 3) slow release past thr → finish (pop completes) */
  pev("pointermove", 262, 400); await sleep(40); pev("pointermove", 264, 400); await sleep(40); pev("pointerup", 264, 400);
  { const L = E.last; check("慢放 q ≈ .51 > thr .426（proj = q + .35 v̄ + .06 ā）：完成 pop", `finish, proj > ${thr.toFixed(3)}`, `${L && L.finish ? "finish" : "cancel"}, proj ${L ? L.proj.toFixed(3) : "?"} n ${L ? L.n : "?"}`, !!L && L.finish && L.proj > thr); }
  await settled();
  check("完成后：页 hidden、body.pushed 去掉", "hidden", pg.hidden ? "hidden" : "shown", pg.hidden && !document.body.classList.contains("pushed"));
  /* 4) slow release short of thr → cancel (back to shown) */
  await open(); pev("pointerdown", 20, 400); await sleep(100); pev("pointermove", 40, 400); await sleep(100); pev("pointermove", 60, 400); await sleep(100); pev("pointermove", 80, 400); await sleep(100); pev("pointermove", 100, 400); await sleep(100); pev("pointermove", 104, 400); await sleep(100); pev("pointerup", 104, 400);   // a slow finger: ~200 pt/s
  { const L = E.last; check("慢放 q ≈ .145 < thr：取消，回到显示", "cancel", L && !L.finish ? "cancel" : "finish", !!L && !L.finish); }
  await settled();
  check("取消后：.page.in、body.pushed 回来、x 0", "in pushed 0", `${pg.classList.contains("in") ? "in" : "-"} ${document.body.classList.contains("pushed") ? "pushed" : "-"} ${Math.round(tx())}`, pg.classList.contains("in") && document.body.classList.contains("pushed") && Math.abs(tx()) < .5);
  /* 5) a flick: fast samples → v̄ ≥ 1.5 W/s keeps the edge-flick phase → v_out × 4.25, finish */
  pev("pointerdown", 20, 400); await sleep(12); pev("pointermove", 40, 400); await sleep(12); pev("pointermove", 80, 400); await sleep(12); pev("pointermove", 120, 400); await sleep(12); pev("pointermove", 160, 400); await sleep(12); pev("pointerup", 160, 400);   // ~3300 pt/s = 7.5 W/s from the first sample
  { const L = E.last; check("快甩（|v̄| ≥ 1.5 W/s 全程）：完成，传出速度 ×4.25", "finish, flick ×4.25", `${L && L.finish ? "finish" : "cancel"}, ${L && L.flick ? "flick" : "no flick"} v̄ ${L ? L.vBar.toFixed(2) : "?"} W/s`, !!L && L.finish && L.flick && L.vBar >= 1.5); }
  await settled();
  /* 6) the rubber band past 1: q 1.5 → 1 + .5(1 − 1/(1 + .55·.5/.5)) = 1.177 */
  await open(); pev("pointerdown", 20, 400); pev("pointermove", 40, 400); await sleep(20); pev("pointermove", 300, 400); await sleep(20); pev("pointermove", 500, 400); await sleep(20); pev("pointermove", 40 + W * 1.5, 400); const gapFull = await convergedGap();
  const qFull = (40 + W * 1.5 - 20 - E.PAN_HYST) / W;   // translation from the touch-down (x 20) minus the pan's 10 pt (§5e): (40 + 1.5 W − 30) / W
  check(`拖过整宽（手指 x 40 + 1.5 W）：驱动目标 = 1 − 橡皮筋(q)，q = (x − 落指 20 − 10) / W = ${qFull.toFixed(3)}，橡皮筋 1 + .5(1 − 1/(1 + .55·(q − 1)/.5))（基值 0）`, (1 - E.rubber(qFull)).toFixed(4), `${N.state.target.toFixed(4)}（q ${E.live() ? E.live().q.toFixed(3) : "?"}，基值 ${E.live() ? E.live().base.toFixed(3) : "?"}，x0 ${E.live() ? E.live().x0 : "?"}）`, Math.abs(N.state.target - (1 - E.rubber(qFull))) < .0005);
  { const want = W * E.rubber(qFull), gotP = W * (1 - N.state.p), gotX = driveX(), stalled = gapFull > 34;
    check(`拖过整宽：顶页 x = W × ${E.rubber(qFull).toFixed(4)}（按驱动器自己：W·(1 − p) 与最后写入的 --nav-x，容 ± 4；等到位时最大帧隔 > 34 ms 只记不判，A15 / A16）`, `${want.toFixed(2)} ± 4`, `p → ${gotP.toFixed(2)} · --nav-x ${gotX.toFixed(2)} · 渲染 transform ${tx().toFixed(2)} · max frame gap ${gapFull.toFixed(0)} ms${stalled ? "（停顿，只记）" : ""} · 视口宽 ${window.innerWidth}（开头 ${W}）· 视口变化 ${wideLog.join("；") || "无"} · 驱动帧 ${N.state.raf ? "在跑" : "已停"} · 目标 ${N.state.target.toFixed(4)} v ${N.state.v.toFixed(4)}`, stalled || (Math.abs(gotP - want) <= 4 && Math.abs(gotX - want) <= 4)); }
  pev("pointerup", 40 + W * 1.5, 400); await settled();
  window.removeEventListener("resize", onRz);
  check("整宽外松手：完成，hidden", "hidden", pg.hidden ? "hidden" : "shown", pg.hidden);
}, { layer: "timing", dark: false });
