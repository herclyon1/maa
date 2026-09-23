/* accept-toast.js — G8 (2号): the toast (#toast) against the native HUD it maps to, UIAccessibilityHUDView (NATIVE-GAP G8;
   remote-ref/tools/uiprobe/uiprobe-subtree-g8-hud-light.json): centred on the screen (centre (220, 478) of 440×956), the inner UIVisualEffectView
   cornerRadius 17, no shadow. The material (luminanceCurveMap → colorSaturate → colorBrightness → gaussianBlur) is not wired yet: colorSaturate /
   colorBrightness still have no decompiled formula (asked of 数据 09-23 21:3x). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptToast(ctx) {
    const { check } = ctx;
    const tt = document.getElementById("toast");
    if (!tt) { check("轻提示外形：页面上没有 #toast", "有", "无", false); return; }
    const was = tt.classList.contains("show"); tt.style.transition = "none"; tt.classList.add("show");
    const r = tt.getBoundingClientRect(), cs = getComputedStyle(tt), dy = (r.top + r.bottom) / 2 - innerHeight / 2, rad = cs.borderTopLeftRadius, sh = cs.boxShadow;
    if (!was) tt.classList.remove("show"); void tt.offsetWidth; tt.style.transition = "";
    check("轻提示外形 = 原生 HUD：屏幕正中、圆角 17、无阴影（uiprobe-subtree-g8-hud-light.json，NATIVE-GAP G8）", "中线差 0 · 17px · none", `中线差 ${dy.toFixed(1)} · ${rad} · ${sh}`,
      Math.abs(dy) < 0.6 && rad === "17px" && sh === "none");
  });
})();
