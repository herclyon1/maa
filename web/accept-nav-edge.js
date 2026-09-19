/* accept-navedge.js — the interactive back gesture against nav-native-formula.md §0 / §3 (BOARD.md #12): edge region .10 W, hysteresis
   15, angle window, percent = Δx / W tracked through ζ .85 / .08, the .35 s projection with thr = min(187.5 / W, .5), the flick boost,
   the release spring ζ .85 / .3, the fluid rubber band past 1. Synthetic PointerEvents on #subpage. */
ACCEPT.add(async function navedge({ check, num, sleep }) {
  const E = window.NavEdge, N = window.Nav, pg = document.querySelector("#subpage");
  check("nav-edge.js：window.NavEdge 接在 #subpage 上", "NavEdge", E && N && pg ? "NavEdge" : "缺", !!E && !!N && !!pg);
  if (!E || !N || !pg) return;
  const W = window.innerWidth, thr = Math.min(187.5 / W, .5);
  const pev = (type, x, y, t, id = 5) => pg.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, clientX: x, clientY: y, isPrimary: true, button: 0, buttons: type === "pointerup" ? 0 : 1, pointerType: "touch" }));
  const tx = () => { const m = getComputedStyle(pg).transform; if (!m || m === "none") return 0; const a = m.match(/matrix\(([^)]+)\)/); return a ? parseFloat(a[1].split(",")[4]) : 0; };
  const open = async () => { N.open("验收", "<p>edge</p>"); await sleep(600); };
  num("识别区 = .10 W（IsLargeFormatPhone；.09 待 MG 读数）", W * .10, W * E.REGION, .01);
  num("松手阈值 thr = min(187.5 / W, .5)", Math.min(187.5 / W, .5), thr, .001);
  /* 1) outside the region: nothing */
  await open(); pev("pointerdown", 80, 400); pev("pointermove", 120, 400); pev("pointermove", 160, 400); pev("pointerup", 160, 400); await sleep(50);
  check("起手 x 80（区外 44）：不识别，页不动", "in, 0", `${pg.classList.contains("in") ? "in" : "-"}, ${Math.round(tx())}`, pg.classList.contains("in") && Math.abs(tx()) < .5);
  /* 2) inside the region but under the hysteresis: nothing yet; past it: began, the percent tracks Δx / W through ζ .85 / .08 */
  pev("pointerdown", 20, 400); pev("pointermove", 30, 400);
  check("区内起手、位移 10 < 迟滞 15：未 began", "rest", pg.classList.contains("nav-live") ? "live" : "rest", !pg.classList.contains("nav-live"));
  pev("pointermove", 40, 400);   // 20 ≥ 15 → began; the translation counts from here
  check("位移 20 ≥ 15 且在 155° 窗内：began，交互式 pop 开始（驱动中，p 从 1 起）", "live, p 1", `${pg.classList.contains("nav-live") ? "live" : "rest"}, p ${N.state.p.toFixed(2)}`, pg.classList.contains("nav-live") && Math.abs(N.state.p - 1) < .01);
  await sleep(30); pev("pointermove", 150, 400); await sleep(30); pev("pointermove", 260, 400); await sleep(250);   // q = 220/440 = .5, held: the tracking spring settles onto it
  { const q = (260 - 40) / W; check("拖到 Δx 220（q .5）停住 +250 ms：进度经 ζ .85/.08 跟到 q（顶页 x = W·q）", `${Math.round(W * q)} ± 3`, Math.round(tx()), Math.abs(tx() - W * q) <= 3 && Math.abs((1 - N.state.p) - q) < .01); }
  /* 3) slow release past thr → finish (pop completes) */
  pev("pointermove", 262, 400); await sleep(40); pev("pointermove", 264, 400); await sleep(40); pev("pointerup", 264, 400);
  { const L = E.last; check("慢放 q ≈ .51 > thr .426（proj = q + .35 v̄ + .06 ā）：完成 pop", `finish, proj > ${thr.toFixed(3)}`, `${L && L.finish ? "finish" : "cancel"}, proj ${L ? L.proj.toFixed(3) : "?"} n ${L ? L.n : "?"}`, !!L && L.finish && L.proj > thr); }
  await sleep(700);
  check("完成后：页 hidden、body.pushed 去掉", "hidden", pg.hidden ? "hidden" : "shown", pg.hidden && !document.body.classList.contains("pushed"));
  /* 4) slow release short of thr → cancel (back to shown) */
  await open(); pev("pointerdown", 20, 400); await sleep(100); pev("pointermove", 40, 400); await sleep(100); pev("pointermove", 60, 400); await sleep(100); pev("pointermove", 80, 400); await sleep(100); pev("pointermove", 100, 400); await sleep(100); pev("pointermove", 104, 400); await sleep(100); pev("pointerup", 104, 400);   // a slow finger: ~200 pt/s
  { const L = E.last; check("慢放 q ≈ .145 < thr：取消，回到显示", "cancel", L && !L.finish ? "cancel" : "finish", !!L && !L.finish); }
  await sleep(700);
  check("取消后：.page.in、body.pushed 回来、x 0", "in pushed 0", `${pg.classList.contains("in") ? "in" : "-"} ${document.body.classList.contains("pushed") ? "pushed" : "-"} ${Math.round(tx())}`, pg.classList.contains("in") && document.body.classList.contains("pushed") && Math.abs(tx()) < .5);
  /* 5) a flick: fast samples → v̄ ≥ 1.5 W/s keeps the edge-flick phase → v_out × 4.25, finish */
  pev("pointerdown", 20, 400); await sleep(12); pev("pointermove", 40, 400); await sleep(12); pev("pointermove", 80, 400); await sleep(12); pev("pointermove", 120, 400); await sleep(12); pev("pointermove", 160, 400); await sleep(12); pev("pointerup", 160, 400);   // ~3300 pt/s = 7.5 W/s from the first sample
  { const L = E.last; check("快甩（|v̄| ≥ 1.5 W/s 全程）：完成，传出速度 ×4.25", "finish, flick ×4.25", `${L && L.finish ? "finish" : "cancel"}, ${L && L.flick ? "flick" : "no flick"} v̄ ${L ? L.vBar.toFixed(2) : "?"} W/s`, !!L && L.finish && L.flick && L.vBar >= 1.5); }
  await sleep(700);
  /* 6) the rubber band past 1: q 1.5 → 1 + .5(1 − 1/(1 + .55·.5/.5)) = 1.177 */
  await open(); pev("pointerdown", 20, 400); pev("pointermove", 40, 400); await sleep(20); pev("pointermove", 300, 400); await sleep(20); pev("pointermove", 500, 400); await sleep(20); pev("pointermove", 40 + W * 1.5, 400); await sleep(300);
  num("拖过整宽 1.5 W：橡皮筋 1 + .5(1 − 1/(1 + .55·(q − 1)/.5)) = 1.177（顶页 x = W × 1.177）", W * E.rubber(1.5), tx(), 4);
  pev("pointerup", 40 + W * 1.5, 400); await sleep(800);
  check("整宽外松手：完成，hidden", "hidden", pg.hidden ? "hidden" : "shown", pg.hidden);
});
