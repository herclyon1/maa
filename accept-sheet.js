/* accept-sheet.js — the picker sheet's drag-to-dismiss against sheet-native-formula.md §5 / §7b / §8b (BOARD.md #10 / #11): 1:1 follow,
   the .55 / 200 rubber band above the top, the .099 s projection and 1000 pt/s fling rule, the ζ 1 / .8 response .3441 settle, the dimming
   riding percentDisplayed, the corner fixed at 38. The logic is exercised through window.Sheet (the touch handlers' targets) and the
   wiring once with a real TouchEvent. */
ACCEPT.add(async function sheet({ check, num, sleep, settle }) {
  const S = window.Sheet, sh = document.querySelector("#picker");
  check("sheet.js：window.Sheet 已接在 #picker 上", "Sheet", S && sh ? "Sheet" : "缺", !!S && !!sh && typeof openPicker === "function");
  if (!S || !sh || typeof openPicker !== "function") return;
  /* Behaviour 5 (moved from accept.js 2026-09-20): the sheet element is hidden once the dismiss has travelled */
  await settle(() => !sh.hasAttribute("open"), 600); check("勾选页关闭后隐藏（open 去掉；等它自己关，≤ .6 s）", "hidden", sh.hasAttribute("open") ? "open" : "hidden", !sh.hasAttribute("open") && getComputedStyle(sh).display === "none");
  const card = sh.querySelector(".card"), dimEl = sh.querySelector(".dim"), bar = sh.querySelector(".pnav");
  const ty = () => { const m = getComputedStyle(card).transform; if (!m || m === "none") return 0; const a = m.match(/matrix\(([^)]+)\)/); return a ? parseFloat(a[1].split(",")[5]) : 0; };
  const crit = (t) => { const u = 2 * Math.PI / S.RESPONSE * t; return 1 - (1 + u) * Math.exp(-u); };
  const near3 = (want, got, tol) => Math.abs(want(0) - got) <= tol;   // el = the last tick's own time
  const rest = (maxMs) => settle(() => !sh.classList.contains("sheet-live"), maxMs);   // S1: sheet.js drops sheet-live when its spring rests (≤ the old fixed wait)
  const closed = (maxMs) => settle(() => !sh.hasAttribute("open") && !sh.classList.contains("sheet-live"), maxMs);
  const open = async () => { openPicker({ title: "验收", opts: [[["甲"], "a"], [["乙"], "b"]], on: ["a"] }, () => {});   // the present is a CSS transition (.in, view.js openPicker), not the driver
    await settle(() => card.getAnimations().length + dimEl.getAnimations().length > 0, 100); await settle(() => card.getAnimations().length + dimEl.getAnimations().length === 0, 650); };
  const settled = async (cap = 1500) => { const t0 = performance.now(); while (sh.classList.contains("sheet-live") && performance.now() - t0 < cap) await sleep(30); };   // the settle is wall-clock: wait for it instead of a fixed sleep (slow frames under load)
  await open();
  check("勾选页打开（index.html 自己的弹簧路径不变）", "in, open", `${sh.classList.contains("in") ? "in" : "-"}, ${sh.hasAttribute("open") ? "open" : "-"}`, sh.classList.contains("in") && sh.hasAttribute("open"));
  /* 1:1 follow on the bar after the pan's 10 pt hysteresis (S.PAN_HYST: the 100 move is within it, the 290 move is Δ 200 − 10), the dimming rides percentDisplayed */
  let t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null); S.move(220, 290, t + 200, null);
  num("下拉 200 pt（栏上）：扣 pan 迟滞 10 后 1:1 跟手 translateY 190（handlePan → draggingChanged；_removeHysteresisFromTranslation）", 190, ty(), .5);
  num("下拉 200 pt：遮罩 opacity = percentDisplayed = (956 − 252)/894 = .787", .787, parseFloat(getComputedStyle(dimEl).opacity), .01);
  check("拖动中顶角仍 38（§7b：圆角在动画中不变）", "38px", getComputedStyle(card).borderTopLeftRadius, getComputedStyle(card).borderTopLeftRadius === "38px");
  /* release at rest speed from 190: projection 252 → nearer large → back to 62 on ζ 1 / .3441 */
  S.move(220, 290, t + 400, null); S.move(220, 290, t + 600, null); S.end(false);   // two still samples: velocityInView = .2·0 + .8·0 = 0
  await sleep(100);
  { const el = S.state.elapsed, y = ty(); check(`松手（v 0，p′ 252 更近 large）：回 62，ζ 1 / .3441，+${Math.round(el * 1000)} ms 剩 ${Math.round((1 - crit(el)) * 100)} % 行程（按弹簧自己走过的时间）`, `${Math.round(190 * (1 - crit(el)))} ± 2`, Math.round(y), near3((d) => 190 * (1 - crit(el - d)), y, 2)); }
  await rest(600);
  check("回弹落定：translate 0、.in、驱动类去掉", "0 in rest", `${Math.round(ty())} ${sh.classList.contains("in") ? "in" : "-"} ${sh.classList.contains("sheet-live") ? "live" : "rest"}`, Math.abs(ty()) < .5 && sh.classList.contains("in") && !sh.classList.contains("sheet-live"));
  /* #11: the dimming and the corner along the travel — opacity = percentDisplayed at three positions (linear for the single detent),
     the corner 38 at all of them (§7b: static through the motion; its in-motion formula is unread) */
  { const pts = [100, 400, 800]; const got = [];
    t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null);
    for (const d of pts) { S.move(220, 90 + d, t + 16 + d, null); got.push([parseFloat(getComputedStyle(dimEl).opacity), getComputedStyle(card).borderTopLeftRadius]); }
    const wantDim = pts.map((d) => (956 - (62 + d - S.PAN_HYST)) / 894);   // the 100 move recognises the pan; every later Δ loses its 10 pt
    check("手指 100 / 400 / 800（卡片 90 / 390 / 790）：遮罩 opacity = percentDisplayed（.899 / .564 / .116）× 令牌 .2 或 .48 在 .dim 自身色里", wantDim.map((v) => v.toFixed(3)).join(" / "), got.map((g) => g[0].toFixed(3)).join(" / "), got.every((g, i) => Math.abs(g[0] - wantDim[i]) < .01));
    check("手指 100 / 400 / 800：顶角恒 38（§7b 圆角静态）", "38px ×3", got.map((g) => g[1]).join(" / "), got.every((g) => g[1] === "38px"));
    S.end(true); await rest(700); }
  /* rubber band above the top: finger −110 (the −10 move is within the hysteresis) → u 100 → d = 200(1 − 1/(1 + .55·100/200)) = 43.14 */
  t = performance.now(); S.begin(220, 200, bar, t); S.move(220, 190, t + 16, null); S.move(220, 90, t + 200, null);
  num("上拉 110 pt（扣迟滞 10 → u 100）：橡皮筋 d = E(1 − 1/(1 + .55u/E))，E 200 → 43.14（translateY −43.14）", -43.14, ty(), .3);
  S.end(true); await rest(600);
  /* a downward fling ≥ 1000 pt/s dismisses even from high up (ζ .8) */
  await new Promise((r) => { if (!sh.classList.contains("sheet-live")) r(); else setTimeout(r, 300); });
  t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null); S.move(220, 130, t + 32, null); S.move(220, 160, t + 48, null);   // ~1875 pt/s
  S.end(false);
  check("下甩 ≥ 1000 pt/s（p′ 仍近 large）：仍关闭，弹簧 ζ .8（_setInteractionEndedSpringParameters）", "dismiss ζ.8", `${S.state.target === S.DISMISS_Y ? "dismiss" : "large"} ζ${S.state.zeta}`, S.state.target === S.DISMISS_Y && S.state.zeta === .8);
  await closed(900);
  check("下甩落定：open 去掉、.in 去掉、sheet-open 去掉", "closed", `${sh.hasAttribute("open") ? "open" : "closed"} ${sh.classList.contains("in") ? "in" : ""} ${document.documentElement.classList.contains("sheet-open") ? "sheet-open" : ""}`.trim(), !sh.hasAttribute("open") && !sh.classList.contains("in") && !document.documentElement.classList.contains("sheet-open"));
  /* a slow release past the midpoint (projection nearer dismiss) dismisses with ζ 1 */
  await open();
  t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null); S.move(220, 590, t + 600, null); S.move(220, 590, t + 800, null); S.end(false);
  check("慢放：手指 +500 → 卡片 y 552（扣迟滞 10；p′ 552 更近 dismiss 956 −404 vs +490）：关闭，ζ 1", "dismiss ζ1", `${S.state.target === S.DISMISS_Y ? "dismiss" : "large"} ζ${S.state.zeta}`, S.state.target === S.DISMISS_Y && S.state.zeta === 1);
  await closed(900);
  /* an upward fling with no higher detent returns to 62 */
  await open();
  t = performance.now(); S.begin(220, 300, bar, t); S.move(220, 290, t + 16, null); S.move(220, 250, t + 32, null); S.move(220, 210, t + 48, null); S.end(false);
  check("上甩（无更高 detent）：回 62", "large", S.state.target === S.REST_Y ? "large" : "dismiss", S.state.target === S.REST_Y);
  await rest(700);
  /* the list at its top hands a downward drag to the sheet; scrolled, it keeps it */
  const list = sh.querySelector(".plist"); list.scrollTop = 0;
  t = performance.now(); S.begin(220, 400, list, t); S.move(220, 420, t + 16, null); S.move(220, 510, t + 100, null);
  check("列表在顶、向下拖 110：交给 sheet（扣迟滞 10 后跟手）", "跟手 100", Math.round(ty()), Math.abs(ty() - 100) < .5);
  S.end(true); await settled();
  /* the recognising move is no velocity sample (evidence/中继二-1002-sheet迟滞 ②): 9 pt fast, then one 151 pt step, lift → v 0, p′ 212 → back to 62;
     the same 9 pt, the recognising step and one more 20 pt / 16 ms (1250 pt/s) → dismiss ζ .8 */
  t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 99, t + 16, null); S.move(220, 250, t + 32, null); S.end(false);
  check("快前置 9 pt + 认定那一步 151 pt 就松手：认定那步不算速度 → v 0、p′ 212 → 回 62，ζ 1（原生 FL 组 12/12 回位）", "large ζ1", `${S.state.target === S.REST_Y ? "large" : "dismiss"} ζ${S.state.zeta}`, S.state.target === S.REST_Y && S.state.zeta === 1);
  await rest(700);
  t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 99, t + 16, null); S.move(220, 120, t + 32, null); S.move(220, 140, t + 48, null); S.end(false);
  check("快前置 9 pt + 认定一步 + 再一步 20 pt / 16 ms（1250 pt/s）：收起，ζ .8（原生 F2 组 4/4 收起）", "dismiss ζ.8", `${S.state.target === S.DISMISS_Y ? "dismiss" : "large"} ζ${S.state.zeta}`, S.state.target === S.DISMISS_Y && S.state.zeta === .8);
  await closed(900); await open();
  /* a touch on the sheet while it springs back (① there): within the 10 pt the spring runs on; at the recognising move the sheet is caught where
     the spring is (no jump), then 1:1 with the finger */
  t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null); S.move(220, 290, t + 200, null); S.move(220, 290, t + 400, null); S.move(220, 290, t + 600, null); S.end(false);
  await sleep(60);
  { t = performance.now(); S.begin(220, 500, bar, t); const a = ty(); S.move(220, 508, t + 16, null); await sleep(50); const b = ty();
    check("回弹中按下、手指移 8 pt（迟滞内）：sheet 照常回弹，不被停住", "仍在动、未认定", `${Math.abs(b - a) > 1 ? "仍在动" : "停了"}、${S.state.drag && !S.state.drag.taken ? "未认定" : "已认定"}`, Math.abs(b - a) > 1 && !!S.state.drag && !S.state.drag.taken && sh.classList.contains("sheet-live"));
    /* "where the spring is": the frame on screen. Both paths catch at it — WA on the animation's clock (catchSheet's waT = currentTime, what
       the style shows), rAF at its last frame — so the catch equals the transform read just before it, plus the 1 pt past the hysteresis */
    const tc = performance.now(), yw = ty();
    S.move(220, 511, tc, null); const c = ty();
    num("手指到 +11（认定，扣迟滞 10 → +1）：在屏上这一帧接住，不跳（接住前一帧画面 + 1）", yw + 1, c, .5);
    S.move(220, 531, performance.now() + 16, null);
    num("认定后手指再 +20：sheet 1:1 再 +20", c + 20, ty(), .5);
    S.end(true); await settled(); }
  /* wiring: a real touch sequence on the bar. Synthetic TouchEvents carry their creation time as timeStamp, so two moves dispatched in
     one task are ≤ 1 ms apart (v_i = 0 by the ≤ 1 ms rule) — unless the thread hiccups between them (GC, load): 50 pt over a few ms is a
     downward fling ≥ 1000 pt/s by the same rule the real finger obeys, and the sheet dismisses (night 16d1238 dark, 1 of 2 runs: "- rest").
     Two still samples 50 ms apart before the touchend make the release velocity 0 (velocityInView = .2·0 + .8·0) whatever the timing. */
  const touch = (type, x, y) => { const T = new Touch({ identifier: 1, target: bar, clientX: x, clientY: y }); bar.dispatchEvent(new TouchEvent(type, { bubbles: true, cancelable: true, touches: type === "touchend" ? [] : [T], targetTouches: type === "touchend" ? [] : [T], changedTouches: [T] })); };
  touch("touchstart", 220, 90); touch("touchmove", 220, 100); touch("touchmove", 220, 160);
  check("真实 touch 事件接线：栏上下拖 70 pt（扣迟滞 10）→ 驱动中 translateY 60", "live 60", `${sh.classList.contains("sheet-live") ? "live" : "rest"} ${Math.round(ty())}`, sh.classList.contains("sheet-live") && Math.abs(ty() - 60) < .5);
  await sleep(50); touch("touchmove", 220, 160); await sleep(50); touch("touchmove", 220, 160);
  touch("touchend", 220, 160); await settled();
  check("touchend 后回落定（两个静止样本 → v 0 → p′ 122 更近 large → 回 62）", "in rest", `${sh.classList.contains("in") ? "in" : "-"} ${sh.classList.contains("sheet-live") ? "live" : "rest"}`, sh.classList.contains("in") && !sh.classList.contains("sheet-live"));
  sh.querySelector(".pback").click(); await closed(600);
});
