/* accept-switch.js — the B13 switch rows (controls 3008bf5's accept.js, re-homed with the file split: BOARD.md #13; into night, not the
   release). Basis: switch-native-formula.md §0–§4 §9, dispatch-B13-switch.md §4. Helpers are local copies of accept.js's (pev / at / cs / px). */
ACCEPT.add(async function sw({ check, num, col, sleep }) {
  if (!window.Switch) { check("switch.js：window.Switch", "Switch", "缺", false); return; }
  const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";
  const T = { green: dark ? [48, 209, 88] : [52, 199, 89], swOff: dark ? [235, 235, 245, .298] : [60, 60, 67, .298] };
  const cs = (el, pseudo) => el ? getComputedStyle(el, pseudo || null) : null, px = (v) => parseFloat(v) || 0;
  /* the computed `scale` as [x, y]: Chrome serialises equal axes as one number ('scale: 1.5784 1.5784' → "1.5784", probed; accept.js:670) and identity as "none" —
     the R70′ style row went red on the frame where lift × flex made --ksx = --ksy (sc[1] undefined; BOARD A16) */
  const scaleOf = (el, pseudo) => { const v = cs(el, pseudo).scale; if (v === "none") return [1, 1]; const a = v.split(" ").map(Number); return a.length === 1 ? [a[0], a[0]] : a; };
  const at = (el, fx = .5, fy = .5, dx = 0, dy = 0) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width * fx + dx, y: r.top + r.height * fy + dy }; };
  const pev = (el, type, p, id = 11) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, clientX: p.x, clientY: p.y, isPrimary: true, button: 0, buttons: type === "pointerup" ? 0 : 1, pointerType: "touch" }));
  /* the resting well and the lifted lens, as B13's static rows (controls 3008bf5 accept.js) */
  const lab = document.createElement("div"); lab.style.cssText = "position:fixed;left:-9999px;top:0";
  lab.innerHTML = `<label class="sw"><input type="checkbox" checked><span></span></label><label class="sw"><input type="checkbox"><span></span></label>`; document.body.appendChild(lab);
  const [on, off] = lab.querySelectorAll(".sw span");
  col("开关开：井环色 = systemGreen（--ios-switch-on；_wellColorOn:YES）", T.green, cs(on).color);
  num("开关开：井环宽 15.5（--ios-switch-well-border-pressed；--wb inset 阴影）", 15.5, px(cs(on).getPropertyValue("--wb")), 0.05);
  col("开关关：井底色 = tertiaryLabel 灰（--ios-switch-off；_effectiveTintColor 0x1c41504bc）", T.swOff, cs(off).backgroundColor);
  num("开关关：井环宽 2（--ios-switch-well-border）", 2, px(cs(off).getPropertyValue("--wb")), 0.05);
  col("开关关：井环色 = 同一灰（_wellColorOn:NO = tint）", T.swOff, cs(off).color);
  num("开关开：圆钮位移 22（--ios-switch-travel = 63 − 37 − 2×2）", 22, px(cs(on, "::after").translate));
  const held = lab.querySelectorAll(".sw")[1]; held.classList.add("drive"); held.style.setProperty("--lift", "1"); held.style.setProperty("--ksx", String(58 / 37)); held.style.setProperty("--ksy", String(38.33 / 24));
  { const sc = scaleOf(held.querySelector("span"), "::after"); check("按住（lift 1）：旋钮 58×38.33（--ios-switch-knob-lift-w/-h：scale 1.5676 1.5971）", "1.5676 1.5971", cs(held.querySelector("span"), "::after").scale, Math.abs(sc[0] - 58 / 37) < .001 && Math.abs(sc[1] - 38.33 / 24) < .001); }
  held.classList.remove("drive"); held.style.removeProperty("--lift"); held.style.removeProperty("--ksx"); held.style.removeProperty("--ksy");
  check("开关开：井环宽 .39 s / 色 .18 s（--ios-motion-switch-well-grow-duration / -color-duration）", "--wb 0.39s, color 0.18s", `${cs(on).transitionProperty} ${cs(on).transitionDuration}`, cs(on).transitionProperty === "--wb, color" && cs(on).transitionDuration === "0.39s, 0.18s");
  check("开关关：井环宽 .365 s 延 .025 s / 色 .18 s（--ios-motion-switch-well-shrink-*）", "0.365s, 0.18s / 0.025s, 0s", `${cs(off).transitionDuration} / ${cs(off).transitionDelay}`, cs(off).transitionDuration === "0.365s, 0.18s" && cs(off).transitionDelay === "0.025s, 0s");
  lab.remove();
  /* §3 → B13 UISwitch (switch-native-formula.md §2–§4, dispatch-B13-switch.md §4) on a synthetic switch through controls.js.
     Springs: knob position ζ 1 / .3 (ω 20.94: .1 s 62 %, .2 s 92 %); lift ζ .625 / .27 from +10 ms (spec.small); un-lift ζ .7 / .5 at max(up, +10 + 220 ms). */
  const swLab = document.createElement("div"); swLab.style.cssText = "position:fixed;left:20px;top:200px;z-index:99;opacity:0";
  swLab.innerHTML = `<label class="sw"><input type="checkbox"><span></span></label>`; document.body.appendChild(swLab);
  const sw = swLab.querySelector(".sw"), inp = sw.querySelector("input"); let flips = 0; inp.addEventListener("change", () => flips++);
  const kn = () => sw.querySelector("span"), lift = () => parseFloat(sw.style.getPropertyValue("--lift")) || 0, kx = () => parseFloat(sw.style.getPropertyValue("--kx")) || 0;
  const posEl = () => (sw._sw && sw._sw.pos.el) || 0;   // the knob spring's own time since its retarget at the up (switch.js swSync / swAim): the check compares at it, not at the wall clock (the last tick is a frame timestamp, the check runs up to a frame later)
  const crit = (resp, t) => { const w = 2 * Math.PI / resp, u = w * t; return 1 - (1 + u) * Math.exp(-u); };   // critical spring progress
  const spr = (z, resp, t) => { const w = 2 * Math.PI / resp; if (z >= 1) return crit(resp, t); const wd = w * Math.sqrt(1 - z * z); return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t)); };   // damped spring progress from rest
  const wb = () => px(cs(kn()).getPropertyValue("--wb"));
  const tDown = performance.now(); pev(sw, "pointerdown", at(sw));
  check("开关 L200 按下 +0 ms：不翻、未 pressed、未抬", "off, rest", `${inp.checked ? "on" : "off"}, ${sw.classList.contains("pressed") ? "pressed" : "rest"}`, !inp.checked && !sw.classList.contains("pressed"));
  await sleep(40);
  check("开关 按下 +40 ms：pressed（.01 s longPress，--ios-touch-switch-press-delay；老页 195 ms 抬起已退）", "pressed", sw.classList.contains("pressed") ? "pressed" : "rest", sw.classList.contains("pressed"));
  await sleep(80);
  { const el = (performance.now() - tDown - 10) / 1000, l = lift(), want = Math.min(1, spr(.625, .27, el)), w = wb();
    check(`开关 按下 +${Math.round(el * 1000 + 10)} ms：抬起中，lift 进度 ≈ ${Math.round(want * 100)} %（spec.small liftSpring ζ .625 / .27 自 +10 ms；--ios-motion-switch-lift-*）`, `${Math.round(want * 100)} %（或前 3 帧内的值 ± 6）`, `${Math.round(l * 100)} %`, [0, .017, .033, .05].some((d) => Math.abs(l - Math.min(1, spr(.625, .27, el - d))) <= .06));   // the value is the last rAF tick's: up to ~3 frames behind in headless Chrome
    check("开关 按下 +120 ms：井环 2 → 15.5 在途（.39 s，--ios-motion-switch-well-grow-duration）", "2 < wb < 15.5", Math.round(w * 100) / 100, w > 2.5 && w < 15); }
  await sleep(120);
  { const sc = scaleOf(kn(), "::after"), el = (performance.now() - tDown - 10) / 1000, want = 1 + spr(.625, .27, el) * (58 / 37 - 1);
    check(`开关 按下 +${Math.round(el * 1000 + 10)} ms：过冲中（ζ .625 峰 +173 ms 1.081 → 58 → 59.7）scale x ≈ ${Math.round(want * 1000) / 1000}`, `${Math.round(want * 1000) / 1000} ± .02`, sc[0], Math.abs(sc[0] - want) <= .02 && lift() >= .95); }
  await sleep(220);
  { const sc = scaleOf(kn(), "::after"); check("开关 按下 +460 ms：旋钮落定 58×38.33（scale 1.5676 1.5971，± .003）", "1.5676 1.5971", cs(kn(), "::after").scale, Math.abs(sc[0] - 58 / 37) < .003 && Math.abs(sc[1] - 38.33 / 24) < .003); }
  num("开关 按下 +460 ms：井环到 15.5（.39 s 完）", 15.5, wb(), 0.05);
  const t2 = performance.now(); pev(sw, "pointerup", at(sw)); const d2 = performance.now() - t2;
  check("开关 S1 抬手：立刻翻转一次（pending 点按预置；--ios-touch-switch-flip-delay 0）", "on ×1", `${inp.checked ? "on" : "off"} ×${flips} +${Math.round(d2 * 10) / 10} ms`, inp.checked && flips === 1 && d2 < 50);
  await sleep(100);
  { const el = posEl(), k = kx(), want = 22 * crit(.3, el); check(`开关 抬手 +${Math.round(el * 1000)} ms（弹簧自己的时间）：旋钮行程 ${Math.round(want / 22 * 100)} %（ζ 1 / .3：.1 s 62 % = 13.6 pt）`, `${Math.round(want * 10) / 10} ± 1.2`, Math.round(k * 10) / 10, Math.abs(k - want) <= 1.2);
    const l = lift(), wantL = 1 - spr(.7, .5, el); check(`开关 抬手 +${Math.round(el * 1000)} ms：缩回中（抬手晚于按下 +.22 s → 立即；spec.small unLiftSpring ζ .7 / .5）lift ≈ ${Math.round(wantL * 100)} %`, `${Math.round(wantL * 100)} % ± 15（rAF 帧粒度）`, `${Math.round(l * 100)} %`, Math.abs(l - wantL) <= .15); }
  await sleep(100);
  { const el = posEl(), k = kx(), want = 22 * crit(.3, el); check(`开关 抬手 +${Math.round(el * 1000)} ms（弹簧自己的时间）：旋钮行程 ${Math.round(want / 22 * 100)} %（.2 s 92 % = 20.2 pt）`, `${Math.round(want * 10) / 10} ± 1`, Math.round(k * 10) / 10, Math.abs(k - want) <= 1); }
  await sleep(600);
  check("开关 抬手 +800 ms：落定 22、驱动结束（缩回 ζ .7 / .5 到 .4 % 需 .63 s）（.drive 去掉，静止规则接管）", "22, rest", `${Math.round(kx() * 100) / 100}, ${sw.classList.contains("drive") ? "drive" : "rest"}`, Math.abs(kx() - 22) < .05 && !sw.classList.contains("drive") && Math.abs(px(cs(kn(), "::after").translate) - 22) < .05);
  /* a 100 ms tap: the lens stays lifted until +230 ms (lensHangTime .22 from the lift at +10), then un-lifts */
  pev(sw, "pointerdown", at(sw)); await sleep(100); pev(sw, "pointerup", at(sw));
  check("开关 短点 100 ms 抬手：翻转（off ×2）", "off ×2", `${inp.checked ? "on" : "off"} ×${flips}`, !inp.checked && flips === 2);
  await sleep(100);
  check("开关 短点 按下 +200 ms：旋钮仍抬着（hang .22 s 未到）lift ≥ 90 %", "≥ 90 %", `${Math.round(lift() * 100)} %`, lift() >= .9);
  await sleep(130);
  check("开关 短点 按下 +330 ms：已在缩回（+230 起 ζ .7 / .5）lift < 85 %", "< 85 %", `${Math.round(lift() * 100)} %`, lift() < .85);
  await sleep(400);
  /* X: drag −10 (against the direction) and release - still flips (the tap's pending value) */
  pev(sw, "pointerdown", at(sw)); pev(sw, "pointermove", at(sw, .5, .5, -10, 0)); pev(sw, "pointerup", at(sw, .5, .5, -10, 0));
  check("开关 X 反方向拖 10 抬手：仍翻转", "on ×3", `${inp.checked ? "on" : "off"} ×${flips}`, inp.checked && flips === 3);
  await sleep(400);
  /* drag +30 from off in 1 pt steps: the flip at the 26th pt zeroes the translation; the knob's target = 42.5 + rb(4) */
  inp.checked = false;
  pev(sw, "pointerdown", at(sw)); await sleep(30);
  let flippedAt = 0; for (let d = 1; d <= 30; d++) { pev(sw, "pointermove", at(sw, .5, .5, d, 0)); if (!flippedAt && inp.checked) flippedAt = d; }
  check("开关 拖 +30（关 → 开）：过 25 即翻开（--ios-touch-switch-flip-distance）", "26", flippedAt, flippedAt === 26);
  await sleep(300);
  { const want = 22 + 12 * (1 - 1 / (1 + .55 * 4 / 12)); check("开关 拖 +30 停住：旋钮 = 42.5 + rb(4)（翻转清零后余 4：橡皮筋 12 / .55）", `${Math.round(want * 100) / 100} ± .3`, Math.round(kx() * 100) / 100, Math.abs(kx() - want) <= .3); }
  pev(sw, "pointerup", at(sw, .5, .5, 30, 0));
  check("开关 拖 +30 抬手：显示态已翻，不再翻（on，事件 ×4）", "on ×4", `${inp.checked ? "on" : "off"} ×${flips}`, inp.checked && flips === 4);
  await sleep(400);
  /* +47 in 1 pt steps from off: flip at 26, then 21 more past the end → 42.5 + rb(21); release: back to 42.5, no second flip */
  inp.checked = false;
  pev(sw, "pointerdown", at(sw)); await sleep(30);
  for (let d = 1; d <= 47; d++) pev(sw, "pointermove", at(sw, .5, .5, d, 0));
  await sleep(300);
  { const want = 22 + 12 * (1 - 1 / (1 + .55 * 21 / 12)); check("开关 拖到 +47 停住：旋钮 = 42.5 + rb(21)（超出端点的橡皮筋）", `${Math.round(want * 100) / 100} ± .3`, Math.round(kx() * 100) / 100, Math.abs(kx() - want) <= .3); }
  pev(sw, "pointerup", at(sw, .5, .5, 47, 0)); await sleep(300);
  check("开关 +47 抬手：回 42.5（位移 22）、仍 on（×5）", "22, on ×5", `${Math.round(kx() * 100) / 100}, ${inp.checked ? "on" : "off"} ×${flips}`, Math.abs(kx() - 22) < .3 && inp.checked && flips === 5);
  await sleep(200);
  /* N2–N4: beyond the far end (+40 > 25: flip) and back (−35 < −25: flip back) - no net flip, no event */
  inp.checked = false;
  pev(sw, "pointerdown", at(sw)); pev(sw, "pointermove", at(sw, .5, .5, 40, 0)); pev(sw, "pointermove", at(sw, .5, .5, 5, 0)); pev(sw, "pointerup", at(sw, .5, .5, 5, 0));
  check("开关 N2 拖过远端外 (+40) 再拖回 (+5) 抬手：翻两次抵消，不翻转、无事件", "off ×5", `${inp.checked ? "on" : "off"} ×${flips}`, !inp.checked && flips === 5);
  await sleep(400);
  /* X11: dragged beyond the far end and released there - flips */
  pev(sw, "pointerdown", at(sw)); pev(sw, "pointermove", at(sw, .5, .5, 40, 0)); pev(sw, "pointerup", at(sw, .5, .5, 40, 0));
  check("开关 X11 拖过远端外直接抬手：翻转", "on ×6", `${inp.checked ? "on" : "off"} ×${flips}`, inp.checked && flips === 6);
  await sleep(400);
  /* R70′ — the knob's flex while lifted (switch-native-formula.md §12 / §12a): active from pressed (+10 ms) to the un-lift, driven by the knob's own
     presented motion; a fast drag like the probe's (4 × 5.5 pt every 16 ms) stretches X and squashes Y (sX·sY ≈ 1) with a positive drift, then the
     reverse stretch while decelerating; the presented scale = lift × flex per frame; after the un-lift the floats return to 1 and the flex is off */
  if (window.Switch && Switch.flexOf) {
    inp.checked = true; pev(sw, "pointerdown", at(sw)); await sleep(60);
    const f0 = Switch.flexOf(sw);
    const want = typeof flexSpec === "function" ? flexSpec(58, 38.33) : null;
    check("开关 R70′ pressed 后 flex 激活（setLifted:YES → 激活模式 3），spec = liquidLensWithSize:(58 × 38.33) 的 smallLoupe → loupe 插值（t .0403，flex-interaction.md §7.4 = view.js flexSpec）：ζ .5777 / .4463、pts 13.63、.9 / 1.1、N 2020（§9 的 N 9697 经 R70″ 帧回放不合，§12b）", want ? `active · ${want.zeta.toFixed(4)}/${want.resp.toFixed(4)} · ${want.pts.toFixed(2)} · ${want.min}/${want.max} · ${want.N.toFixed(0)}` : "flexSpec", f0 ? `${f0.active ? "active" : "off"} · ${f0.spec.zeta.toFixed(4)}/${f0.spec.resp.toFixed(4)} · ${f0.spec.pts.toFixed(2)} · ${f0.spec.min}/${f0.spec.max} · ${f0.spec.N.toFixed(0)}` : "no flex", !!f0 && !!want && f0.active && Math.abs(f0.spec.zeta - want.zeta) < 1e-9 && Math.abs(f0.spec.resp - want.resp) < 1e-9 && Math.abs(f0.spec.N - want.N) < 1e-6 && Math.abs(f0.spec.N - 2020.15) < .5 && Math.abs(f0.spec.zeta - .5777) < .001);
    await sleep(200);   // lifted and still: no motion → identity
    { const f = Switch.flexOf(sw); check("开关 R70′ 抬起后静止：无运动 → sX = sY = 1、drift 0（源是旋钮自己的呈现运动，不是手指）", "1 · 1 · 0", f ? `${f.out.sx.toFixed(4)} · ${f.out.sy.toFixed(4)} · ${f.out.dx.toFixed(3)}` : "-", !!f && Math.abs(f.out.sx - 1) < .001 && Math.abs(f.out.sy - 1) < .001 && Math.abs(f.out.dx) < .01); }
    for (let i = 1; i <= 4; i++) { pev(sw, "pointermove", at(sw, .5, .5, -5.5 * i, 0)); await sleep(16); }   // the probe's fast drag: 22 pt in 4 steps / 64 ms (on → off direction)
    const fr = []; await new Promise((res) => { let first = null; const tick = (now) => { if (first === null) first = now; const f = Switch.flexOf(sw), sc = scaleOf(kn(), "::after"), l = lift(); fr.push({ t: now - first, f: f ? { ...f, trace: undefined } : null, sc, l, kdx: parseFloat(sw.style.getPropertyValue("--kdx")) || 0 }); if (now - first < 450) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
    const withF = fr.filter((s) => s.f), peak = withF.reduce((m, s) => Math.max(m, s.f.out.sx), 1), dip = withF.reduce((m, s) => Math.min(m, s.f.out.sy), 1), maxDx = withF.reduce((m, s) => Math.max(m, s.f.out.dx), 0);
    check("开关 R70′ 快拖中：X 伸 Y 缩（§3：加速沿 x），面积近守恒（§12a：1.028 × .9709 ≈ .998），drift 沿运动方向", "peak sX > 1.002 · dip sY < .998 · |sX·sY − 1| < .01 · drift ≠ 0", `peak ${peak.toFixed(4)} · dip ${dip.toFixed(4)} · area ${withF.every((s) => Math.abs(s.f.out.sx * s.f.out.sy - 1) < .01) ? "ok" : "OFF"} · max drift ${maxDx.toFixed(3)}`, withF.length > 10 && peak > 1.002 && dip < .998 && withF.every((s) => Math.abs(s.f.out.sx * s.f.out.sy - 1) < .01) && Math.abs(maxDx) > .01);
    /* A16 (red twice): between frames a pointer move retargets through swSync, which steps the springs WITHOUT writing — the state read here then differs from the
       style until the next tick; so the style is judged against the driver's last WRITE (its own frame values, A15), and the write against lift × flex */
    const withW = withF.filter((s) => s.f.written), bad = withW.filter((s) => !(Math.abs(s.sc[0] - s.f.written.ksx) < .002 && Math.abs(s.sc[1] - s.f.written.ksy) < .002 && Math.abs(s.kdx - s.f.written.kdx) < .002)), badW = withW.filter((s) => !(Math.abs(s.f.written.ksx - (1 + s.f.written.lift * (s.f.liftSX - 1)) * s.f.written.sx) < .001 && Math.abs(s.f.written.ksy - (1 + s.f.written.lift * (s.f.liftSY - 1)) * s.f.written.sy) < .001 && Math.abs(s.f.written.kdx - s.f.written.sx * s.f.written.dx) < .002));
    check("开关 R70′ 呈现 = 抬起缩放 × flex（--ksx / --ksy），平移 += sX·drift（--kdx）——逐帧：样式 = 驱动器最后一次写入值，写入值 = 抬起 × flex（A15）", "every frame", bad.length === 0 && badW.length === 0 ? "every frame" : `OFF: style≠written ${bad.length} 帧${bad[0] ? " (" + bad[0].sc[0].toFixed(4) + " vs " + bad[0].f.written.ksx + ")" : ""} · written≠lift×flex ${badW.length} 帧`, withW.length > 10 && bad.length === 0 && badW.length === 0);
    { const tr = Switch.flexOf(sw).trace, stepRef = (x, v, target, [z, r], dt) => { const w = 2 * Math.PI / r, dx = x - target; if (z < 1) { const wd = w * Math.sqrt(1 - z * z), B = (v + z * w * dx) / wd, e = Math.exp(-z * w * dt); return target + e * (dx * Math.cos(wd * dt) + B * Math.sin(wd * dt)); } const e = Math.exp(-w * dt), B = v + w * dx; return target + e * (dx + B * dt); };
      let maxErr = 0, n = 0; for (let i = 1; i < tr.length; i++) { const a0 = tr[i - 1], b0 = tr[i]; if (!(b0.dt > 0)) continue; const sp = [f0.spec.zeta, f0.spec.resp]; maxErr = Math.max(maxErr, Math.abs(stepRef(a0.sx, a0.vsx, b0.tSx, sp, b0.dt) - b0.sx), Math.abs(stepRef(a0.sy, a0.vsy, b0.tSy, sp, b0.dt) - b0.sy), Math.abs(stepRef(a0.dx, a0.vdx, b0.tDx, sp, b0.dt) - b0.dx)); n++; }
      check(`开关 R70′ 三个 flex 浮点逐帧 = spec 弹簧（ζ .5777 / .4463）解析一步（自上一帧值 / 速度向本帧目标；${n} 帧，最大差）`, "≤ 1e-6", maxErr.toExponential(2), n > 10 && maxErr <= 1e-6); }
    pev(sw, "pointercancel", at(sw, .5, .5, -22, 0)); await sleep(700);   // a cancel ends the press without a flip (the rows below count flips)
    { const f = Switch.flexOf(sw); check("开关 R70′ 抬手 → hang 后放下 → flex 关（激活模式回 1），浮点回 1 / 0，驱动结束", "off · 1 · 1 · 0 · rest", f ? `${f.active ? "active" : "off"} · ${f.out.sx.toFixed(4)} · ${f.out.sy.toFixed(4)} · ${f.out.dx.toFixed(3)} · ${sw.classList.contains("drive") ? "drive" : "rest"}` : "-", !!f && !f.active && Math.abs(f.out.sx - 1) < .002 && Math.abs(f.out.sy - 1) < .002 && Math.abs(f.out.dx) < .05 && !sw.classList.contains("drive")); }
    await sleep(100);
  }
  /* pointercancel: no flip, nothing pressed */
  pev(sw, "pointerdown", at(sw)); pev(sw, "pointercancel", at(sw));
  check("开关 pointercancel：不翻转、不 pressed", "on ×6, rest", `${inp.checked ? "on" : "off"} ×${flips}, ${sw.classList.contains("pressed") ? "pressed" : "rest"}`, inp.checked && flips === 6 && !sw.classList.contains("pressed"));
  await sleep(200);
  swLab.remove();
});
