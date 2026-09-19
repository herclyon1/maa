/* accept-tile.js — acceptance of the tile / capsule press states (BOARD.md R6; tile.css). Registered through ACCEPT.add; runs in accept.js's page,
   light and dark, on synthetic controls appended to #app (styled by the page's own sheets) so the rows do not depend on the current tab:
   ① a pressed tile (.pressed, the press state view.js installPressables sets) shows NO change — computed transform none and background = the resting
      tile's (state-tables/button.md R14′ ①); the :active override (transform none) is present in tile.css (the :active state itself cannot be set from
      script, so the rule is read from the sheet);
   ② the capsule: .pressed → at +90 ms still the resting colours (the recorded onset is +172 ms), at +172 ms + 2 frames the recorded pressed colours
      (light fill (220,240,255) / text (0,150,230); dark (10,49,71) / (0,170,255) — R14″ / R14‴, 【录像采样替代】), computed transform none and
      opacity 1 while pressed (the button:active .6 dim is overridden in the sheet); removing .pressed → the resting colours within a frame;
   ③ the red capsule keeps its resting colours while pressed (its pressed colours are unread — no state is drawn);
   Real-device items (A23), not judged here: the capsule's press onset on the phone against the recording's 172 / 155 ms; whether a quick tap
   (< 172 ms) natively shows the pressed colour at all (here it does not). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptTile(ctx) {
    const { check, sleep } = ctx;
    const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";
    const app = document.getElementById("app") || document.body;
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
      check("磁贴 ① :active 的 scale(.97) 与 8 % 填色已被 tile.css 盖掉（表里有 .tile:active → transform none 的规则）", "rule present", ruleWith(".tile:active", "transform", "none") ? "rule present" : "no rule", ruleWith(".tile:active", "transform", "none"));
    } finally { rest.remove(); pressed.remove(); }
    /* ② the capsule */
    const cap = document.createElement("button"), capRed = document.createElement("button");
    cap.type = capRed.type = "button"; cap.className = "capsule"; capRed.className = "capsule red"; cap.textContent = capRed.textContent = "R6";
    app.appendChild(cap); app.appendChild(capRed);
    try {
      await frame();
      const c0 = getComputedStyle(cap), restBg = c0.backgroundColor, restFg = c0.color, r0 = getComputedStyle(capRed), redBg = r0.backgroundColor, redFg = r0.color;
      const wantBg = dark ? "rgb(10, 49, 71)" : "rgb(220, 240, 255)", wantFg = dark ? "rgb(0, 170, 255)" : "rgb(0, 150, 230)";
      const t0 = performance.now(); cap.classList.add("pressed"); capRed.classList.add("pressed");
      await sleep(90); await frame();
      const cEarly = getComputedStyle(cap), early = { bg: cEarly.backgroundColor, fg: cEarly.color, t: performance.now() - t0 };
      check("胶囊钮 ② 按下 +90 ms 仍是静止色（录像首个变化帧在 +172 ms；页面 transition-delay 172 ms，【录像采样替代】）", `${restBg} · ${restFg}`, `${early.bg} · ${early.fg} @ ${early.t.toFixed(0)} ms`, sameColor(early.bg, restBg) && sameColor(early.fg, restFg) && early.t < 165);
      await sleep(Math.max(0, 172 + 40 - (performance.now() - t0))); await frame(); await frame();
      const cLate = getComputedStyle(cap), late = { bg: cLate.backgroundColor, fg: cLate.color, tf: cLate.transform, op: cLate.opacity, t: performance.now() - t0 };
      check(`胶囊钮 ② 按下 +172 ms 后跳到录像的按下色（${dark ? "暗 R14‴：底 (10,49,71)、字 (0,170,255)" : "亮 R14″：底 (220,240,255)、字 (0,150,230)"}），不缩放、不变暗（button:active .6 已盖掉）`, `${wantBg} · ${wantFg} · none · 1`, `${late.bg} · ${late.fg} · ${late.tf} · ${late.op} @ ${late.t.toFixed(0)} ms`, sameColor(late.bg, wantBg) && sameColor(late.fg, wantFg) && late.tf === "none" && late.op === "1");
      const cRed = getComputedStyle(capRed);
      check("胶囊钮 ③ 红色变体按下不画状态（按下色未读，留空待读）：底 / 字 = 静止色", `${redBg} · ${redFg}`, `${cRed.backgroundColor} · ${cRed.color}`, sameColor(cRed.backgroundColor, redBg) && sameColor(cRed.color, redFg));
      cap.classList.remove("pressed"); capRed.classList.remove("pressed"); await frame(); await frame();
      const cBack = getComputedStyle(cap);
      check("胶囊钮 ② 松手立即回静止色（回程未读，画成瞬回）", `${restBg} · ${restFg}`, `${cBack.backgroundColor} · ${cBack.color}`, sameColor(cBack.backgroundColor, restBg) && sameColor(cBack.color, restFg));
      check("胶囊钮 ② tile.css 里有 .capsule:active → opacity 1（盖掉 index.html 的 button:active .6）", "rule present", ruleWith(".capsule:active", "opacity", "1") ? "rule present" : "no rule", ruleWith(".capsule:active", "opacity", "1"));
    } finally { cap.remove(); capRed.remove(); }
  });
})();
