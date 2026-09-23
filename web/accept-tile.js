/* accept-tile.js — acceptance of the tile / capsule press states (BOARD.md R6, R6′; tile.css). Registered through ACCEPT.add; runs in accept.js's page,
   light and dark, on synthetic controls in a fixed off-screen container under body (styled by the page's own sheets; nothing enters #app, so no other
   row's recording sees a layout change) so the rows do not depend on the current tab:
   ① a pressed tile (.pressed, the press state view.js installPressables sets) shows NO change — computed transform none and background = the resting
      tile's (state-tables/button.md R14′ ①); the :active override (transform none) is present in tile.css (the :active state itself cannot be set from
      script, so the rule is read from the sheet);
   ② the capsule = UIButton tinted (button.md R62 hooks; values = the R14 probe table through tokens.css's "capsule button" block): rest fill = the tint
      at α .18 (dark .25), at +90 ms still resting (150 ms delaysContentTouches), at +150 ms + 2 frames the held colours — fill α .1176 (dark .175),
      label α .75 (dark (.1, .612, 1)) — transform none, opacity 1; the release returns over .25 s ease-in-out (mid-way strictly between, rest at
      +300 ms); a 60 ms tap never shows the colour (R62 ①); the :active dim rule is overridden in the sheet;
   ③ the red capsule: the same tinted transformers on --bad — light α .75, dark .9·c + .1 (R86: chosen by configuration, not by colour).
   Every expected colour is produced by the page itself (a probe element with the same color-mix), never typed in. Real-device items (A23): the press
   onset on the phone against 150 ms + a frame; whether the held colour holds through the action on the phone (R62 ②: natively the page switches). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptTile(ctx) {
    const { check, num, col, sleep, settle, raf, sec, segRest, tabRest, fadeRest, at, pev, cs, px, T, near, rgb, same, fmt, satTop, varColor, probe, q, bs, onText, thisShift, R } = ctx;   // dark: the file's own below
    const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";
    /* the synthetic controls live in a fixed off-screen container under body (验收 08:5x): nothing is inserted into #app — its layout, view.js's observers
       and any other row's frame recording stay untouched; the page's sheets still style .tile / .capsule there (body-prefixed selectors) */
    const app = document.createElement("div"); app.className = "accept-tile-lab"; app.style.cssText = "position:fixed;left:-9999px;top:0;width:400px;pointer-events:none;"; document.body.appendChild(app);
    try {
    const sheet = [...document.styleSheets].find((s) => /tile\.css/.test(s.href || ""));
    let rules = [];
    try { rules = sheet ? [...sheet.cssRules] : []; } catch (e) { rules = []; }
    const ruleWith = (sel, prop, val) => rules.some((r) => r.selectorText && r.selectorText.includes(sel) && r.style && r.style.getPropertyValue(prop) === val);
    check("磁贴 / 胶囊钮 R6：tile.css 已链入", "tile.css", sheet ? "tile.css" : "缺", !!sheet);
    /* ① the tile */
    const rest = document.createElement("button"), pressed = document.createElement("button");
    rest.type = pressed.type = "button"; rest.className = pressed.className = "tile"; rest.textContent = pressed.textContent = "R6";
    app.appendChild(rest); app.appendChild(pressed);
    const frame = () => new Promise(requestAnimationFrame);
    /* colours compared numerically: during a transition (even a 0 s one inside its delay) Chrome serialises the computed colour in oklab, a
       resting one in rgb() or color(srgb …) — the three syntaxes are parsed to sRGB 0–255 + α here (oklab → linear sRGB by the standard matrices) */
    const toRGBA = (str) => {
      let m;
      if ((m = /^rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)$/.exec(str))) return [+m[1], +m[2], +m[3], m[4] == null ? 1 : +m[4]];
      if ((m = /^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)$/.exec(str))) return [255 * m[1], 255 * m[2], 255 * m[3], m[4] == null ? 1 : +m[4]];
      if ((m = /^oklab\(([-\d.]+) ([-\d.]+) ([-\d.]+)(?: \/ ([\d.]+))?\)$/.exec(str))) {
        const L = +m[1], a = +m[2], b = +m[3];
        const l_ = L + 0.3963377774 * a + 0.2158037573 * b, m_ = L - 0.1055613458 * a - 0.0638541728 * b, s_ = L - 0.0894841775 * a - 1.2914855480 * b;
        const l = l_ ** 3, mm = m_ ** 3, ss = s_ ** 3;
        const lr = 4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * ss, lg = -1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * ss, lb = -0.0041960863 * l - 0.7034186147 * mm + 1.7076147010 * ss;
        const gam = (c) => { c = Math.max(0, Math.min(1, c)); return 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055); };
        return [gam(lr), gam(lg), gam(lb), m[4] == null ? 1 : +m[4]];
      }
      return null;
    };
    const sameColor = (a, b) => { const A = toRGBA(a), B = toRGBA(b); return !!A && !!B && A.every((v, i) => Math.abs(v - B[i]) <= (i === 3 ? 0.01 : 1.5)); };
    try {
      await frame();
      const bg0 = getComputedStyle(rest).backgroundColor, tf0 = getComputedStyle(rest).transform;
      pressed.classList.add("pressed"); await frame(); await frame();
      const cp = getComputedStyle(pressed);
      check("磁贴 ① 按下态 = 无任何变化（R14′ ①：更新体不看 highlighted 位，fillColor / isSelected 只管动态色与选中视图）：.pressed 后 transform none、底色 = 静止磁贴的", `${tf0} · ${bg0}`, `${cp.transform} · ${cp.backgroundColor} · opacity ${cp.opacity}`, cp.transform === "none" && sameColor(cp.backgroundColor, bg0) && cp.opacity === "1");
      check("磁贴 ① :active 不缩放、index.html 的 8 % 填色已被 tile.css 盖掉（表里有 .tile:active → transform none 的规则）", "rule present", ruleWith(".tile:active", "transform", "none") ? "rule present" : "no rule", ruleWith(".tile:active", "transform", "none"));
    } finally { rest.remove(); pressed.remove(); }
    /* ② the capsule — UIButton tinted (button.md R14 table + R62): every expected colour is the token mixed by the page itself (a probe element) */
    const root = getComputedStyle(document.documentElement), tok = (n) => root.getPropertyValue(n).trim();
    const colorOf = (css) => { const pr = document.createElement("i"); pr.style.cssText = `position:fixed;left:-9999px;color:${css}`; document.body.appendChild(pr); const v = getComputedStyle(pr).color; pr.remove(); return v; };   // the page's own serialisation of a colour expression
    const mixOf = (tint, pct) => colorOf(`color-mix(in srgb, ${tint} ${pct}, transparent)`);
    const cap = document.createElement("button"), capRed = document.createElement("button");
    cap.type = capRed.type = "button"; cap.className = "capsule"; capRed.className = "capsule red"; cap.textContent = capRed.textContent = "R6";
    app.appendChild(cap); app.appendChild(capRed);
    try {
      await frame();
      const restA = tok(dark ? "--ios-capsule-rest-alpha-dark" : "--ios-capsule-rest-alpha"), heldA = tok(dark ? "--ios-capsule-pressed-alpha-dark" : "--ios-capsule-pressed-alpha"), textA = tok("--ios-capsule-pressed-text-alpha");
      const whiteMix = tok("--ios-capsule-pressed-text-white-mix"), addWhite = (tint) => colorOf(`color-mix(in srgb, ${tint} calc(100% - ${whiteMix}), white ${whiteMix})`);   // R6″: AddingWhite10 = .9·c + .1
      const wantRestBg = mixOf("var(--accent)", restA), wantHeldBg = mixOf("var(--accent)", heldA), wantHeldFg = dark ? addWhite("var(--accent)") : mixOf("var(--accent)", textA);
      const redRestA = dark ? tok("--ios-capsule-red-rest-alpha-dark") : restA, redHeldA = dark ? tok("--ios-capsule-red-pressed-alpha-dark") : heldA;   // R91: a systemRed tint rests at .2 in dark (× .7 held)
      const wantRedRest = mixOf("var(--bad)", redRestA), wantRedHeld = mixOf("var(--bad)", redHeldA), wantRedFg = dark ? addWhite("var(--bad)") : mixOf("var(--bad)", textA);
      const delayTok = tok("--ios-touch-capsule-press-delay");
      const c0 = getComputedStyle(cap), restBg = c0.backgroundColor, restFg = c0.color, r0 = getComputedStyle(capRed), redBg = r0.backgroundColor, redFg = r0.color;
      check(`胶囊钮 ② 令牌（tokens.css「capsule button」块，R6′ / R6″ / R91）：静止 α ${dark ? ".25（红 .2）" : ".18"}、按下 = 静止 × ${dark ? ".70 → .175（红 .14）" : ".65 → .117"}、字 ${dark ? "AddingWhite10 = .9·c + .1（R86 变换器 16）" : "α .75（变换器 14）"}、延迟 = --ios-touch-highlight-delay 150ms（UIScrollView delaysContentTouches，R62）`, `${dark ? "25% · 17.5%" : "18% · 11.76%"} · 10% · 150ms`, `${restA} · ${heldA} · ${whiteMix} · ${delayTok}`, restA === (dark ? "25%" : "18%") && heldA === (dark ? "17.5%" : "11.7%") && whiteMix === "10%" && delayTok === "150ms" && (!dark || (redRestA === "20%" && redHeldA === "14%")));
      check(`胶囊钮 ② 静止色按 tinted 表：底 = accent α ${dark ? ".25" : ".18"}（原 index.html 18 % / 红 16 % 被盖）、字 = accent；红变体底 = --bad α ${dark ? ".2（R91 systemRed 暗色）" : ".18"}`, `${wantRestBg} · ${wantRedRest}`, `${restBg} · ${redBg}`, sameColor(restBg, wantRestBg) && sameColor(redBg, wantRedRest));
      const t0 = performance.now(); cap.classList.add("pressed"); capRed.classList.add("pressed");
      await sleep(90); await frame();
      const cEarly = getComputedStyle(cap), early = { bg: cEarly.backgroundColor, fg: cEarly.color, t: performance.now() - t0 };
      check("胶囊钮 ② 按下 +90 ms 仍是静止色（150 ms 延迟内，UIScrollView delaysContentTouches；cell-native.md 行 12 探针首变帧 +174…175）", `${restBg} · ${restFg}`, `${early.bg} · ${early.fg} @ ${early.t.toFixed(0)} ms`, sameColor(early.bg, restBg) && sameColor(early.fg, restFg) && early.t < 150);
      await sleep(Math.max(0, 150 + 40 - (performance.now() - t0))); await frame(); await frame();
      const cLate = getComputedStyle(cap), late = { bg: cLate.backgroundColor, fg: cLate.color, tf: cLate.transform, op: cLate.opacity, t: performance.now() - t0 };
      check(`胶囊钮 ② 按下 +150 ms 后跳到 tinted 表的按下色（${dark ? "暗：底 α .25 → .175、字 .9·c + .1（R86 AddingWhite10；探针 (0,.569,1) → (.1,.612,1) ✓）" : "亮：底 α .18 → .1176、字 α → .75"}，R14 探针 / R62 PNG 逐值同），不缩放、不变暗`, `${wantHeldBg} · ${wantHeldFg} · none · 1`, `${late.bg} · ${late.fg} · ${late.tf} · ${late.op} @ ${late.t.toFixed(0)} ms`, sameColor(late.bg, wantHeldBg) && sameColor(late.fg, wantHeldFg) && late.tf === "none" && late.op === "1");
      const cRed = getComputedStyle(capRed);
      check(`胶囊钮 ③ 红变体同一 tinted 配置套在自己的 tint 上：底 --bad α ${dark ? ".2 × .70 = .14（R91）" : ".18 × .65 = .117"}、字 ${dark ? "--bad 往白混 10 %（R86：变换器按配置选，与颜色无关）" : "--bad α .75"}`, `${wantRedHeld} · ${wantRedFg}`, `${cRed.backgroundColor} · ${cRed.color}`, sameColor(cRed.backgroundColor, wantRedHeld) && sameColor(cRed.color, wantRedFg));
      /* the release: the action fires at the up; the colours return over .25 s ease-in-out (R14 timing: the same _UISystemBackgroundView, 15 frames) */
      const tR = performance.now(); cap.classList.remove("pressed"); capRed.classList.remove("pressed");
      await sleep(110); await frame();
      const mid = toRGBA(getComputedStyle(cap).backgroundColor), A = toRGBA(wantHeldBg), B = toRGBA(wantRestBg), tMid = performance.now() - tR;
      const between = !!mid && !!A && !!B && ((mid[3] - Math.min(A[3], B[3])) > 0.005 && (Math.max(A[3], B[3]) - mid[3]) > 0.005);
      await sleep(Math.max(0, 300 - (performance.now() - tR))); await frame();
      const cBack = getComputedStyle(cap);
      check(`胶囊钮 ② 松手回程 .25 s ease-in-out（R14 时序行：filled / plain / gray / tinted 同一 _UISystemBackgroundView，15 帧两头慢）：+${tMid.toFixed(0)} ms 底 α 在按下与静止之间，+300 ms 回静止`, `α between · rest`, `α ${mid ? mid[3].toFixed(3) : "?"} (held ${A ? A[3].toFixed(3) : "?"} → rest ${B ? B[3].toFixed(3) : "?"}) · ${cBack.backgroundColor} · ${cBack.color}`, between && sameColor(cBack.backgroundColor, restBg) && sameColor(cBack.color, restFg));
      /* R62 ①: a tap shorter than the delay never shows the colour (the action still fires: installPressables' click, not this sheet's) */
      cap.classList.add("pressed"); await sleep(60); const cShort = getComputedStyle(cap).backgroundColor; cap.classList.remove("pressed"); await sleep(120); await frame(); const cAfter = getComputedStyle(cap).backgroundColor; await sleep(150); const cAfter2 = getComputedStyle(cap).backgroundColor;
      check("胶囊钮 ② R62 ①：短于 150 ms 的点按（60 ms 抬手）全程无按下色（+60 / 抬手后 +120 / +270 都是静止色）", `${restBg} ×3`, `${cShort} · ${cAfter} · ${cAfter2}`, sameColor(cShort, restBg) && sameColor(cAfter, restBg) && sameColor(cAfter2, restBg));
      check("胶囊钮 ② tile.css 里有 .capsule:active → opacity 1（盖掉 index.html 的 button:active .6）", "rule present", ruleWith(".capsule:active", "opacity", "1") ? "rule present" : "no rule", ruleWith(".capsule:active", "opacity", "1"));
    } finally { cap.remove(); capRed.remove(); }
    } finally { app.remove(); }
    /* --- moved from accept.js 2026-09-20 (BOARD 收尾单 ②): the tile's static token rows and the §4 UIButton press on a synthetic tile / alert action --- */
    sec("static", { layer: "static", dark: true });
  const tile = document.querySelector(".tile");
  if (tile) {
    const r = tile.getBoundingClientRect();
    num("动作磁贴高 ≥ 80.33（--ios-tile-h，AX-57）", 80.33, Math.min(r.height, 80.33)); num("动作磁贴圆角 16（--ios-tile-radius，提醒事项 layer.cornerRadius）", 16, px(cs(tile).borderTopLeftRadius));
    num("磁贴间距 8（--ios-tile-gap）", 8, px(cs(tile.parentElement).columnGap));
    const ico = tile.querySelector(".tico"); if (ico) { const ir = ico.getBoundingClientRect(); num("磁贴徽章 48（--ios-tile-icon）", 48, ir.width); num("磁贴徽章 x 6（--ios-tile-icon-x）", 6, ir.left - r.left); num("磁贴徽章 y 2（--ios-tile-icon-y）", 2, ir.top - r.top); }
    const tt = tile.querySelector(".ttitle"); if (tt) { const tr = tt.getBoundingClientRect(); num("磁贴标题 17（--ios-tile-label-size）", 17, px(cs(tt).fontSize), 0.05); num("磁贴标题行框 20.33（--ios-tile-label-lh）", 20.33, px(cs(tt).lineHeight), 0.05); check("磁贴标题字重 600（--ios-tile-label-weight）", 600, cs(tt).fontWeight, String(cs(tt).fontWeight) === "600"); num("磁贴标题 x 12（--ios-tile-label-x）", 12, tr.left - r.left); num("磁贴标题 y 52（--ios-tile-label-top）", 52, tr.top - r.top); check("磁贴字族 ui-rounded 优先（--ios-tile-number-font）", "ui-rounded", cs(tt).fontFamily.slice(0, 10), /^ui-rounded/.test(cs(tt).fontFamily)); }
  }
  const numT = document.querySelector(".num");
  if (numT) {
    const r = numT.getBoundingClientRect();
    num("数字磁贴高 ≥ 80.33（--ios-tile-h）", 80.33, Math.min(r.height, 80.33)); num("数字磁贴圆角 16（--ios-tile-radius）", 16, px(cs(numT).borderTopLeftRadius));
    const big = numT.querySelector(".big"); if (big) { const br = big.getBoundingClientRect(); num("数字右内缩 10（--ios-tile-number-inset）", 10, r.right - br.right); num("数字顶 9（--ios-tile-number-top）", 9, br.top - r.top); num("数字字号 28（--ios-tile-number-size）", 28, px(cs(big).fontSize), 0.1); num("数字行框 33.67（--ios-tile-number-lh）", 33.67, px(cs(big).lineHeight), 0.05); check("数字字重 700（--ios-tile-number-weight）", 700, cs(big).fontWeight, String(cs(big).fontWeight) === "700"); }
    const ico = numT.querySelector(".nico"); if (ico) num("数字磁贴徽章 48（--ios-tile-icon）", 48, ico.getBoundingClientRect().width);
    const lab = numT.querySelector(".lab"); if (lab) { const lr = lab.getBoundingClientRect(); num("数字磁贴标签 17（--ios-tile-label-size）", 17, px(cs(lab).fontSize), 0.1); num("数字磁贴标签 x 12（--ios-tile-label-x）", 12, lr.left - r.left); num("数字磁贴标签 y 52（--ios-tile-label-top）", 52, lr.top - r.top); }
  }
  /* §4 UIButton on a synthetic tile; alert action on a synthetic open dialog */
  if (sec("press", { layer: "timing", dark: true })) {   // tile press (colours)
  const bLab = document.createElement("div"); bLab.style.cssText = "position:fixed;left:20px;top:300px;z-index:99;opacity:0";
  bLab.innerHTML = `<div class="group tiles"><button type="button" class="tile"><span class="ttitle">x</span></button></div>`; document.body.appendChild(bLab);
  const tile = bLab.querySelector(".tile"); let clicks = 0; tile.addEventListener("click", () => clicks++);
  const t3 = performance.now(); pev(tile, "pointerdown", at(tile)); const d3 = performance.now() - t3;
  check("按钮 U1 按下：立刻 highlighted（.pressed，--ios-touch-button-highlight-delay 0）", "pressed", tile.classList.contains("pressed") ? `pressed +${Math.round(d3 * 10) / 10} ms` : "not pressed", tile.classList.contains("pressed"));
  pev(tile, "pointermove", at(tile, .5, 1, 0, 50));
  check("按钮 U3 拖出边界 50 pt：仍高亮（余量 70）", "pressed", tile.classList.contains("pressed") ? "pressed" : "not pressed", tile.classList.contains("pressed"));
  pev(tile, "pointermove", at(tile, .5, 1, 0, 80));
  check("按钮 U3 拖出边界 80 pt：高亮灭（touchDragExit）", "not pressed", tile.classList.contains("pressed") ? "pressed" : "not pressed", !tile.classList.contains("pressed"));
  pev(tile, "pointermove", at(tile, .5, 1, 0, 30));
  check("按钮 U4 拖回：高亮亮（touchDragEnter）", "pressed", tile.classList.contains("pressed") ? "pressed" : "not pressed", tile.classList.contains("pressed"));
  pev(tile, "pointerup", at(tile, .5, 1, 0, 50)); await sleep(10);
  check("按钮 U3 在边界外 50 pt 抬手：触发一次（touchUpInside）", 1, clicks, clicks === 1);
  pev(tile, "pointerdown", at(tile)); pev(tile, "pointermove", at(tile, .5, 1, 0, 100)); pev(tile, "pointerup", at(tile, .5, 1, 0, 100)); await sleep(10);
  check("按钮 U6 在边界外 100 pt 抬手：不触发（touchUpOutside）", 1, clicks, clicks === 1 && !tile.classList.contains("pressed"));
  const dlg = document.createElement("dialog"); dlg.style.cssText = "position:fixed;left:20px;top:400px;z-index:99;opacity:0"; dlg.innerHTML = `<div class="acts"><button type="button" id="_a">a</button><button type="button" id="_b">b</button></div>`;
  document.body.appendChild(dlg); dlg.show(); const ba = dlg.querySelector("#_a"), bb = dlg.querySelector("#_b"); let ca = 0, cb = 0; ba.addEventListener("click", () => ca++); bb.addEventListener("click", () => cb++);
  pev(ba, "pointerdown", at(ba)); pev(ba, "pointermove", at(bb));
  check("弹窗按钮 A3 滑到相邻按钮：高亮转移", "b pressed", `${ba.classList.contains("pressed") ? "a" : ""}${bb.classList.contains("pressed") ? "b" : ""} pressed`, !ba.classList.contains("pressed") && bb.classList.contains("pressed"));
  pev(ba, "pointermove", at(bb, .5, 1, 0, 6));
  check("弹窗按钮 A4 出边 6 pt：高亮灭（无余量，--ios-touch-alert-slop 0）", "none pressed", `${ba.classList.contains("pressed") ? "a" : ""}${bb.classList.contains("pressed") ? "b" : ""} pressed`, !ba.classList.contains("pressed") && !bb.classList.contains("pressed"));
  pev(ba, "pointerup", at(bb, .5, 1, 0, 6)); await sleep(10);
  check("弹窗按钮 A2 出边抬手：不触发", "0 / 0", `${ca} / ${cb}`, ca === 0 && cb === 0);
  pev(ba, "pointerdown", at(ba)); pev(ba, "pointermove", at(bb)); pev(ba, "pointerup", at(bb)); await sleep(10);
  check("弹窗按钮 A3/A6 从 a 滑到 b 抬手：触发 b", "0 / 1", `${ca} / ${cb}`, ca === 0 && cb === 1);
  /* ghost click (data session 862de97): the action closes the dialog on the up, then the browser's own click lands on
     whatever is under the finger - a tile below opened a second dialog. The tile sits under button a; a's handler closes
     the dialog; the browser's click is replayed as a plain click on the element now at that point. */
  { const p = at(ba); ba.addEventListener("click", () => dlg.close(), { once: true }); const c0 = clicks;
    pev(ba, "pointerdown", p); pev(ba, "pointerup", p);                                    // the action closes the dialog on the up
    tile.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, clientX: p.x, clientY: p.y }));   // = the browser's click, now landing on the tile under the finger
    await sleep(10);
    check("弹窗按钮抬手关掉弹窗后，浏览器补的 click 不穿到底下的磁贴", `tile ${c0}, closed`, `tile ${clicks}, ${dlg.open ? "open" : "closed"}`, clicks === c0 && !dlg.open); }
  dlg.close(); dlg.remove(); bLab.remove(); }
  }, { layer: "static", dark: true });   // S4 file-level layer tags (S4-tags.md (e))
})();
