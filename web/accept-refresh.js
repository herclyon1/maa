/* accept-refresh.js — acceptance of the pull-to-refresh control (BOARD.md #8, night batch). Registered through ACCEPT.add; runs in accept.js's
   page (light and dark). Every expected number is the decompiled value of remote-ref/refresh-native-formula.md §2 recomputed here:
   ① threshold: Refresh.maxSnap() = 112.5 × max(H, 372) / 568 with H = the visual viewport's height (no title) — and not the old page's 72;
   ② reveal: at pull = maxSnap / 2 (show .5) the 8 arms' opacities are clamp(1 + i·(show − 1), 0, 1) × show = .5 / .25 / 0 / 0 …, state 1;
   ③ trigger with the finger still down at pull = maxSnap (f ≥ 1, isTracking): state 3 at once, no release needed; k = clamp(|v| × 48.333, 5, 150)
      (v 800 pt/s → 150), the rotation follows the ζ 1 / ω √150 = 12.25 spring to 3.1316 rad = 179.43° (closed form x(t) = target − Δ·e^(−ωt)(1 + ωt));
      sampled every frame for .8 s, rms ≤ 2°;
   ④ tick: after the spring settles the rotation advances in 45° steps every 125 ms, discrete — two reads 250 ms apart differ by 90 ± 45° and every
      read is base + n·45;
   ⑤ end: endRefreshing → state 4, the indicator's opacity reaches 0 within 0.3 s, then state 0 and rotation 0;
   ⑥ a release before f reached 1 (pull = maxSnap / 2, finger up) → state 0 and the refresh callback not called;
   ⑦ real-device template (the applicable ones): the old view.js path is off (its #ptr reference is null under the guard) so a pull cannot arm twice. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptRefresh(ctx) {
    const { check, num, sleep } = ctx;
    const R = window.Refresh;
    if (!R) { check("下拉刷新：Refresh 未装载（refresh.js）", "Refresh", "缺", false); return; }
    const ptr = document.getElementById("ptr"), ai = document.getElementById("ptrai"), arms = [...ai.querySelectorAll("i")];
    const H = window.visualViewport ? window.visualViewport.height : innerHeight, want = 112.5 * Math.max(H, 372) / 568;
    const rotOf = () => { const m = /rotate\(([-\d.]+)deg\)/.exec(ai.style.transform || ""); return m ? parseFloat(m[1]) : 0; };
    let calls = 0, done; R.onRefresh = () => { calls++; return new Promise((r) => { done = r; }); };
    try {
      R.reset();
      /* ① */
      num("下拉刷新 ① 阈值 maxSnap = 112.5 × max(H, 372) / 568（refresh-native-formula.md §2；H = 可视视口高 " + Math.round(H) + "，不是旧页的 72）", want, R.maxSnap(), 0.01);
      check("下拉刷新 ① 旧路径已让位（view.js 的 #ptr 引用为 null，不会再 72 pt 就 arm）", "no .arm", ptr.classList.contains("arm") ? "arm!" : "no .arm", !ptr.classList.contains("arm"));
      /* ② */
      R.__drive({ pull: want / 2, v: 0, down: true }); await new Promise(requestAnimationFrame);
      const got = arms.map((a) => parseFloat(a.style.opacity)), exp = arms.map((_, i) => Math.max(0, Math.min(1, 1 + i * (0.5 - 1))) * 0.5);
      check("下拉刷新 ② 拉到 maxSnap/2（show .5）：8 臂 α = clamp(1 + i·(show − 1), 0, 1) × show = .5 / .25 / 0 … 逐根点亮（§0 instanceAlphaOffset −1 → 0）、状态 1、未触发", exp.map((v) => v.toFixed(3)).join(" ") + " · state 1 · calls 0", got.map((v) => v.toFixed(3)).join(" ") + ` · state ${R.state} · calls ${calls}`, got.every((v, i) => Math.abs(v - exp[i]) < 0.002) && R.state === 1 && calls === 0);
      /* ⑥ release before f ≥ 1 */
      R.__drive({ down: false }); await new Promise(requestAnimationFrame);
      check("下拉刷新 ⑥ 未到阈值就松手：不触发（trigger 要 f ≥ 1 且手指在），回状态 0、臂灭", "state 0 · calls 0 · arms 0", `state ${R.state} · calls ${calls} · arm0 ${arms[0].style.opacity}`, R.state === 0 && calls === 0 && parseFloat(arms[0].style.opacity) === 0);
      /* ③ trigger with the finger down */
      R.__drive({ pull: want / 2, v: 800, down: true }); await new Promise(requestAnimationFrame);
      const t0 = performance.now(); R.__drive({ pull: want, v: 800, down: true });
      const stAt = R.state, k = R.lastK, w = Math.sqrt(150), target = 179.43;
      check("下拉刷新 ③ 手指仍在、拉到 maxSnap（f ≥ 1）：立刻进刷新（状态 3，不等松手），刷新回调调用 1 次，k = clamp(|v| 800 × 48.333, 5, 150) = 150", "state 3 · calls 1 · k 150", `state ${stAt} · calls ${calls} · k ${k}`, stAt === 3 && calls === 1 && k === 150);
      const samples = []; const tEnd = performance.now() + 800;
      while (performance.now() < tEnd) { await new Promise(requestAnimationFrame); samples.push({ t: (performance.now() - t0) / 1000, r: rotOf() }); }
      const closed = (t) => target - target * Math.exp(-w * t) * (1 + w * t);   // ζ 1 from 0 with v0 0: x = T − T·e^(−ωt)(1 + ωt)
      const springS = samples.filter((s) => s.t < 0.6), rms = Math.sqrt(springS.reduce((a, s) => a + Math.pow(s.r - closed(s.t), 2), 0) / Math.max(1, springS.length));
      num("下拉刷新 ③ 转起：旋转逐帧对临界弹簧 ω = √150 = 12.25 /s、目标 3.1316 rad = 179.43°（m 1、k 150、c 5000，allowsOverdamping 默认 false → ζ 1）：前 .6 s 的 rms（°）", 0, rms, 2);
      /* ④ tick */
      await sleep(400); const rA = rotOf(); await sleep(250); const rB = rotOf();
      const stepOK = Math.abs(((rB - rA) - 90)) <= 45 + 0.01, gridOK = Math.abs(((rA - target) / 45) - Math.round((rA - target) / 45)) < 0.02 && Math.abs(((rB - target) / 45) - Math.round((rB - target) / 45)) < 0.02;
      check("下拉刷新 ④ 刷新中每 125 ms 跳 45°（离散、1 s 一圈）：250 ms 内前后两读差 90 ± 45°，且都落在 179.43 + n·45 的格上", "Δ 90 ± 45 · on grid", `${rA.toFixed(1)} → ${rB.toFixed(1)} (Δ ${(rB - rA).toFixed(1)})`, stepOK && gridOK);
      /* ⑤ end */
      const tE = performance.now(); done(); await sleep(60);
      const st4 = R.state; let opAt = null; await sleep(300); const opEnd = parseFloat(ai.style.opacity || "1"); await sleep(120);
      check("下拉刷新 ⑤ 结束：状态 4（.3 s ease-in-out 淡出 + 再转 3.1316 rad）→ 状态 0，指示器回 0°、透明度回默认", "4 → 0 · rotation 0", `after 60 ms state ${st4} · after 360 ms opacity ${isNaN(opEnd) ? "(default)" : opEnd} · now state ${R.state} · rotation ${R.rotation}`, st4 === 4 && R.state === 0 && R.rotation === 0);
    } finally { R.onRefresh = null; R.reset(); }
  });
})();
