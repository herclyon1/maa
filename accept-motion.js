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
  /* afterPaint: the callback runs in a LATER "update the rendering" than the call's own frame. HTML Standard, event loop processing model
     (html.spec.whatwg.org/multipage/webappapis.html#update-the-rendering, read 2026-09-20): "run the animation frame callbacks" first takes
     the keys of the callback map ("Let callbackHandles be the result of getting the keys of callbacks"), so a rAF registered inside a rAF
     callback is not in that frame's list and runs in a later update; within one update that step precedes "update the rendering or user
     interface of doc" (the paint), so the first frame is painted in between; every callback of one update gets the same timestamp
     ("passing in the relative high resolution time given frameTimestamp"), frameTimestamp being that update's own "last render opportunity
     time". Hence the proof of a frame in between is the timestamp: the inner callback's ts is later than the ts of a rAF registered in the
     same task as the afterPaint call (same update, same ts as afterPaint's outer rAF). No millisecond floor: under load headless Chrome's
     consecutive updates can be 1 ms apart (night b940684 light: "1 ms, 2 rAF" against the old "≥ 8 ms" — the interval is the display's
     property, not afterPaint's). */
  { let tA = 0; requestAnimationFrame((ts) => { tA = ts; });   // registered in the same task, before afterPaint's outer rAF → same update, same ts
    const tB = await new Promise((r) => M.afterPaint((ts) => r(ts)));
    check("afterPaint：回调落在比调用帧更晚的一次 update the rendering（内层 rAF 时间戳 > 同任务注册的 rAF 时间戳；不设毫秒下限）", "晚一帧", `${tB > tA ? "晚" : "同"}一帧（Δ ${(tB - tA).toFixed(1)} ms）`, tA > 0 && tB > tA); }
  /* the click swallow: a browser-style click 45 ms after the mark is swallowed; the page's own click passes; the mark clears itself */
  { const el = document.createElement("button"); el.style.cssText = "position:fixed;left:-9999px;top:0"; document.body.appendChild(el); let n = 0; el.addEventListener("click", () => n++);
    M.swallowNextClick(el, 300); await sleep(45); el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    check("swallowNextClick：打标后 45 ms 的浏览器 click 被吞（安卓补 click 40–60 ms）", 0, n, n === 0 && !el.dataset.rc);
    M.click(el); check("Motion.click：页面自己发的 click 不被吞", 1, n, n === 1);
    M.swallowNextClick(el, 100); await sleep(150); el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    check("swallowNextClick：超时（100 ms）后标记自清，之后的 click 正常", 2, n, n === 2);
    el.remove(); }
});
