/* accept-flurec.js — the phone recorder's "choppy" rule (fluency-rec.js: a glass gesture with ≥ 6 frame intervals in a row > 25 ms) fed good and bad
   frame samples. The recorder itself does not run under ?accept; only its pure counting, window.FluRules, is there. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptFlurec(ctx) {
    const { check, sec } = ctx;
    if (!sec("flurec")) return;
    const R = window.FluRules;
    check("记录器：持续掉帧的计数接口在（window.FluRules）", "object", typeof R, !!R && typeof R.choppy === "function");
    if (!R) return;
    const rep = (ms, n) => Array(n).fill(ms);
    const judge = (ms, glass) => R.choppy({ glass, run25: R.runOver(ms, R.CHOPPY_MS) });
    const cases = [
      ["连续 6 帧 33 ms（30 帧）", rep(33.3, 6), "seg", true],
      ["120 Hz 里夹连续 6 帧 33 ms", [...rep(8.3, 10), ...rep(33.3, 6), ...rep(8.3, 10)], "seg", true],
      ["连续 6 帧 16.7 ms（60 Hz）", rep(16.7, 6), "seg", false],
      ["连续 6 帧 8.3 ms（120 Hz）", rep(8.3, 6), "seg", false],
      ["120 Hz 里单个 33 ms", [...rep(8.3, 10), 33.3, ...rep(8.3, 10)], "seg", false],
      ["连续 5 帧 33 ms（差一帧）", rep(33.3, 5), "seg", false],
      ["非玻璃手势连续 6 帧 33 ms", rep(33.3, 6), "", false],
    ];
    for (const [name, ms, glass, want] of cases) {
      const got = judge(ms, glass);
      check("记录器 choppy：" + name, want ? "命中" : "不命中", got ? "命中" : "不命中", got === want);
    }
  });
})();
