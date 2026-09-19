/* accept-sheet.js — the picker sheet's drag-to-dismiss against sheet-native-formula.md §5 / §7b / §8b (BOARD.md #10 / #11): 1:1 follow,
   the .55 / 200 rubber band above the top, the .099 s projection and 1000 pt/s fling rule, the ζ 1 / .8 response .3441 settle, the dimming
   riding percentDisplayed, the corner fixed at 38. The logic is exercised through window.Sheet (the touch handlers' targets) and the
   wiring once with a real TouchEvent. */
ACCEPT.add(async function sheet({ check, num, sleep }) {
  const S = window.Sheet, sh = document.querySelector("#picker");
  check("sheet.js：window.Sheet 已接在 #picker 上", "Sheet", S && sh ? "Sheet" : "缺", !!S && !!sh && typeof openPicker === "function");
  if (!S || !sh || typeof openPicker !== "function") return;
  const card = sh.querySelector(".card"), dimEl = sh.querySelector(".dim"), bar = sh.querySelector(".pnav");
  const ty = () => { const m = getComputedStyle(card).transform; if (!m || m === "none") return 0; const a = m.match(/matrix\(([^)]+)\)/); return a ? parseFloat(a[1].split(",")[5]) : 0; };
  const crit = (t) => { const u = 2 * Math.PI / S.RESPONSE * t; return 1 - (1 + u) * Math.exp(-u); };
  const near3 = (want, got, tol) => Math.abs(want(0) - got) <= tol;   // el = the last tick's own time
  const open = async () => { openPicker({ title: "验收", opts: [[["甲"], "a"], [["乙"], "b"]], on: ["a"] }, () => {}); await sleep(650); };
  await open();
  check("勾选页打开（index.html 自己的弹簧路径不变）", "in, open", `${sh.classList.contains("in") ? "in" : "-"}, ${sh.hasAttribute("open") ? "open" : "-"}`, sh.classList.contains("in") && sh.hasAttribute("open"));
  /* 1:1 follow on the bar, the dimming rides percentDisplayed */
  let t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null); S.move(220, 290, t + 200, null);
  num("下拉 200 pt（栏上）：卡片 1:1 跟手 translateY 200（handlePan → draggingChanged）", 200, ty(), .5);
  num("下拉 200 pt：遮罩 opacity = percentDisplayed = (956 − 262)/894 = .776", .776, parseFloat(getComputedStyle(dimEl).opacity), .01);
  check("拖动中顶角仍 38（§7b：圆角在动画中不变）", "38px", getComputedStyle(card).borderTopLeftRadius, getComputedStyle(card).borderTopLeftRadius === "38px");
  /* release at rest speed from 200: projection 262 → nearer large → back to 62 on ζ 1 / .3441 */
  S.move(220, 290, t + 400, null); S.move(220, 290, t + 600, null); S.end(false);   // two still samples: velocityInView = .2·0 + .8·0 = 0
  await sleep(100);
  { const el = S.state.elapsed, y = ty(); check(`松手（v 0，p′ 262 更近 large）：回 62，ζ 1 / .3441，+${Math.round(el * 1000)} ms 剩 ${Math.round((1 - crit(el)) * 100)} % 行程（按弹簧自己走过的时间）`, `${Math.round(200 * (1 - crit(el)))} ± 2`, Math.round(y), near3((d) => 200 * (1 - crit(el - d)), y, 2)); }
  await sleep(600);
  check("回弹落定：translate 0、.in、驱动类去掉", "0 in rest", `${Math.round(ty())} ${sh.classList.contains("in") ? "in" : "-"} ${sh.classList.contains("sheet-live") ? "live" : "rest"}`, Math.abs(ty()) < .5 && sh.classList.contains("in") && !sh.classList.contains("sheet-live"));
  /* #11: the dimming and the corner along the travel — opacity = percentDisplayed at three positions (linear for the single detent),
     the corner 38 at all of them (§7b: static through the motion; its in-motion formula is unread) */
  { const pts = [100, 400, 800]; const got = [];
    t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null);
    for (const d of pts) { S.move(220, 90 + d, t + 16 + d, null); got.push([parseFloat(getComputedStyle(dimEl).opacity), getComputedStyle(card).borderTopLeftRadius]); }
    const wantDim = pts.map((d) => (956 - (62 + d)) / 894);
    check("行程 100 / 400 / 800：遮罩 opacity = percentDisplayed（.894 / .553 / .105）× 令牌 .2 或 .48 在 .dim 自身色里", wantDim.map((v) => v.toFixed(3)).join(" / "), got.map((g) => g[0].toFixed(3)).join(" / "), got.every((g, i) => Math.abs(g[0] - wantDim[i]) < .01));
    check("行程 100 / 400 / 800：顶角恒 38（§7b 圆角静态）", "38px ×3", got.map((g) => g[1]).join(" / "), got.every((g) => g[1] === "38px"));
    S.end(true); await sleep(700); }
  /* rubber band above the top: u 100 → d = 200(1 − 1/(1 + .55·100/200)) = 43.14 */
  t = performance.now(); S.begin(220, 200, bar, t); S.move(220, 190, t + 16, null); S.move(220, 100, t + 200, null);
  num("上拉 100 pt：橡皮筋 d = E(1 − 1/(1 + .55u/E))，E 200 → 43.14（translateY −43.14）", -43.14, ty(), .3);
  S.end(true); await sleep(600);
  /* a downward fling ≥ 1000 pt/s dismisses even from high up (ζ .8) */
  await new Promise((r) => { if (!sh.classList.contains("sheet-live")) r(); else setTimeout(r, 300); });
  t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null); S.move(220, 130, t + 32, null); S.move(220, 160, t + 48, null);   // ~1875 pt/s
  S.end(false);
  check("下甩 ≥ 1000 pt/s（p′ 仍近 large）：仍关闭，弹簧 ζ .8（_setInteractionEndedSpringParameters）", "dismiss ζ.8", `${S.state.target === S.DISMISS_Y ? "dismiss" : "large"} ζ${S.state.zeta}`, S.state.target === S.DISMISS_Y && S.state.zeta === .8);
  await sleep(900);
  check("下甩落定：open 去掉、.in 去掉、sheet-open 去掉", "closed", `${sh.hasAttribute("open") ? "open" : "closed"} ${sh.classList.contains("in") ? "in" : ""} ${document.documentElement.classList.contains("sheet-open") ? "sheet-open" : ""}`.trim(), !sh.hasAttribute("open") && !sh.classList.contains("in") && !document.documentElement.classList.contains("sheet-open"));
  /* a slow release past the midpoint (projection nearer dismiss) dismisses with ζ 1 */
  await open();
  t = performance.now(); S.begin(220, 90, bar, t); S.move(220, 100, t + 16, null); S.move(220, 590, t + 600, null); S.move(220, 590, t + 800, null); S.end(false);
  check("慢放到 y 562（p′ 562 更近 dismiss 956 −394 vs +500）：关闭，ζ 1", "dismiss ζ1", `${S.state.target === S.DISMISS_Y ? "dismiss" : "large"} ζ${S.state.zeta}`, S.state.target === S.DISMISS_Y && S.state.zeta === 1);
  await sleep(900);
  /* an upward fling with no higher detent returns to 62 */
  await open();
  t = performance.now(); S.begin(220, 300, bar, t); S.move(220, 290, t + 16, null); S.move(220, 250, t + 32, null); S.move(220, 210, t + 48, null); S.end(false);
  check("上甩（无更高 detent）：回 62", "large", S.state.target === S.REST_Y ? "large" : "dismiss", S.state.target === S.REST_Y);
  await sleep(700);
  /* the list at its top hands a downward drag to the sheet; scrolled, it keeps it */
  const list = sh.querySelector(".plist"); list.scrollTop = 0;
  t = performance.now(); S.begin(220, 400, list, t); S.move(220, 420, t + 16, null); S.move(220, 500, t + 100, null);
  check("列表在顶、向下拖：交给 sheet（跟手）", "跟手 100", Math.round(ty()), Math.abs(ty() - 100) < .5);
  S.end(true); await sleep(700);
  /* wiring: a real touch sequence on the bar */
  const touch = (type, x, y) => { const T = new Touch({ identifier: 1, target: bar, clientX: x, clientY: y }); bar.dispatchEvent(new TouchEvent(type, { bubbles: true, cancelable: true, touches: type === "touchend" ? [] : [T], targetTouches: type === "touchend" ? [] : [T], changedTouches: [T] })); };
  touch("touchstart", 220, 90); touch("touchmove", 220, 100); touch("touchmove", 220, 150);
  check("真实 touch 事件接线：栏上下拖 60 pt → 驱动中 translateY 60", "live 60", `${sh.classList.contains("sheet-live") ? "live" : "rest"} ${Math.round(ty())}`, sh.classList.contains("sheet-live") && Math.abs(ty() - 60) < .5);
  touch("touchend", 220, 150); await sleep(700);
  check("touchend 后回落定", "in rest", `${sh.classList.contains("in") ? "in" : "-"} ${sh.classList.contains("sheet-live") ? "live" : "rest"}`, sh.classList.contains("in") && !sh.classList.contains("sheet-live"));
  sh.querySelector(".pback").click(); await sleep(600);
});
