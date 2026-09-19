/* accept-motion.js — acceptance for web/motion.js (BOARD.md #1): the spring step against the closed form, afterPaint after a painted
   frame, the browser-click swallow, the page's own click passing. B14's own rows (accept.js §5) are the behavioural acceptance. */
ACCEPT.add(async function motion({ check, num, sleep }) {
  const M = window.Motion;
  check("motion.js：window.Motion 四个入口", "spring afterPaint swallowNextClick click", M ? Object.keys(M).filter((k) => k !== "isSynthetic").join(" ") : "缺", !!M && ["spring", "afterPaint", "swallowNextClick", "click"].every((k) => typeof M[k] === "function"));
  if (!M) return;
  /* closed form from rest: critical q = 1 − (1 + ωt)e^{−ωt}; underdamped q = 1 − e^{−ζωt}(cos ω_d t + ζω/ω_d · sin ω_d t) */
  const crit = (r, t) => { const u = 2 * Math.PI / r * t; return 1 - (1 + u) * Math.exp(-u); };
  const under = (z, r, t) => { const w = 2 * Math.PI / r, wd = w * Math.sqrt(1 - z * z); return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + z * w / wd * Math.sin(wd * t)); };
  const run = (zr, T, steps) => { const s = { x: 0, v: 0 }; for (let i = 0; i < steps; i++) M.spring(s, 1, zr, T / steps); return s.x; };
  num("弹簧 ζ1/.3：.1 s 进度 62 %（1 − (1+ωt)e^{−ωt}，ω 20.94；60 步）", crit(.3, .1) * 100, run([1, .3], .1, 60) * 100, .2);
  num("弹簧 ζ1/.3：.2 s 92 %", crit(.3, .2) * 100, run([1, .3], .2, 60) * 100, .2);
  num("弹簧 ζ.625/.27（开关抬起）：.173 s 峰 108.1 %（欠阻尼闭式）", under(.625, .27, .173) * 100, run([.625, .27], .173, 60) * 100, .3);
  num("弹簧 ζ.7/.5（开关缩回）：.1 s 42 %", under(.7, .5, .1) * 100, run([.7, .5], .1, 60) * 100, .3);
  { const one = { x: 0, v: 0 }; M.spring(one, 1, [1, .3], .1); const two = { x: 0, v: 0 }; M.spring(two, 1, [1, .3], .05); M.spring(two, 1, [1, .3], .05);
    num("弹簧步进可拆（一步 .1 s = 两步 .05 s，续值续速）", one.x * 1000, two.x * 1000, .01); }
  /* afterPaint: at least one full frame between the call and the callback, and a rAF tick in between */
  { const t0 = performance.now(); let ticks = 0; const stop = performance.now() + 400; const count = (ts) => { ticks++; if (ts < stop) requestAnimationFrame(count); }; requestAnimationFrame(count);
    const t1 = await new Promise((r) => M.afterPaint(() => r(performance.now())));
    check("afterPaint：回调在下一帧画完之后（rAF→rAF：≥ 1 帧、≥ 8 ms）", "≥ 8 ms, ≥ 1 rAF", `${Math.round(t1 - t0)} ms, ${ticks} rAF`, t1 - t0 >= 8 && ticks >= 1); }
  /* the click swallow: a browser-style click 45 ms after the mark is swallowed; the page's own click passes; the mark clears itself */
  { const el = document.createElement("button"); el.style.cssText = "position:fixed;left:-9999px;top:0"; document.body.appendChild(el); let n = 0; el.addEventListener("click", () => n++);
    M.swallowNextClick(el, 300); await sleep(45); el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    check("swallowNextClick：打标后 45 ms 的浏览器 click 被吞（安卓补 click 40–60 ms）", 0, n, n === 0 && !el.dataset.rc);
    M.click(el); check("Motion.click：页面自己发的 click 不被吞", 1, n, n === 1);
    M.swallowNextClick(el, 100); await sleep(150); el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    check("swallowNextClick：超时（100 ms）后标记自清，之后的 click 正常", 2, n, n === 2);
    el.remove(); }
});
