/* topbar.js — the navigation bar's scroll behaviour (BOARD.md #4, 2026-09-20): large title → small title, the bar's bottom edge line,
   release snapping and the pull-down stretch, all from remote-ref/nav-bar-scroll-formula.md (§0–§3 decompiled UIKit, §10 probe reads).
   Takes over from view.js's onScroll (--bar / --big / --title); that entry keeps a one-line guard `if (window.Topbar) return;`.
   Geometry (§10, UIProbe largetitle page): the bar rests at 106 and collapses to 54 (_restingHeights [54, 106]); the large-title item's
   preferredHeight p = 52 = restingHeightOfTitleView, layoutMinimumHeight 0 (collapsible), b = 14. On this page the bar (.topbar) is the
   54-pt small bar and the large title (header h1) scrolls in the flow under it, so the collapse range p is measured once at rest:
   p = (h1 bottom) − (bar bottom); the native ratio (52 on a 106/54 bar) is not assumed (§10 note).
   Per scroll (§2.1/§2.4/§2.5): s = content scrolled past rest (1:1 with the finger, clamped to [0, p]); c = p − s;
   progress = c ≥ p − b ? 1 : (c ≤ 0 ? 0 : (c − b) / (p − b)); the switch is binary at progress < 0.05 (⇔ s > 0.95 (p − b)) and each
   title crosses over with a 0.2 s opacity transition (2.5; no translation — §6 item 8); the large title is clipped at the bar's bottom
   edge while it slides under (clipsToBounds, §4 item 1), not faded. Bottom edge line (§3): hidden while the content is at rest at the top
   (shouldHideAtTop), shown once scrolled — its fade, if any, is unread (instant here).
   Release snap (2.8): when a scroll ends inside the collapse range the target is the nearest resting point — midpoint rule; the curve of
   that deceleration retarget is unread — the page reuses its own measured UIScrollView top-spring (view.js springToTop, ω 12 /s).
   Pull-down stretch (2.7): scale = clamp(1 + (h − h_rest) / (displayScale × screenH × 0.66), 1, 1.1) with h − h_rest = the overscroll;
   the title's anchor point for that scale is unread (leading baseline used).
   Unread (left as the old behaviour / untouched): the pocket material (五个闭包), the replay layer, the edge line fade. */
(() => {
  "use strict";
  const root = document.documentElement;
  const bar = document.getElementById("topbar"), h1 = document.querySelector("header h1");
  if (!bar || !h1) return;
  const B = 14, THRESH = 0.05, FADE_S = 0.2, STRETCH_MAX = 1.1, STRETCH_K = 0.66;
  const ZONE_BELOW = 7.67;   // §10b ①: the large-title label box sits 3.67 under the bar zone and 7.67 above the zone's bottom (probe, 34 pt bold label 40.67 tall)
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let p = 52, restBottom = 0, barBottom = 0, dragging = false, snapping = false, snapRaf = 0, lastTouchEnd = -1e9;
  const api = { snap: true };   // snap: the 2.8 release retarget (accept-topbar.js turns it off while it scrolls programmatically)
  const measure = () => {   // at rest (scrollY 0): the collapse range p and where the bar's bottom edge is
    const y = window.scrollY, hr = h1.getBoundingClientRect(), br = bar.getBoundingClientRect();
    barBottom = br.bottom; restBottom = hr.bottom + y; p = Math.max(1, restBottom + ZONE_BELOW - barBottom);   // p = the title zone (label box + 7.67) = 52 in the native geometry (§10 / §10b)
  };
  /* §2.4/§2.5 progress → the two titles' alpha (binary, transitions in CSS) */
  const progressOf = (s) => { const c = p - s; return c >= p - B ? 1 : (c <= 0 ? 0 : (c - B) / (p - B)); };
  const snapTarget = (s) => (s < p / 2 ? 0 : p);   // 2.8: nearest resting point, midpoint rule (s in the collapse range)
  const stretchOf = (over) => clamp(1 + over / (devicePixelRatio * screen.height * STRETCH_K), 1, STRETCH_MAX);   // 2.7 (over = pull-down pt)
  const apply = () => {
    const y = window.scrollY; if (y === 0) measure();   // at rest the geometry is re-read (layout may have changed since load: fonts, data, header content)
    const s = clamp(y, 0, p), inline = s >= p - 0.5 ? 1 : 0;   // §10b ④ (probe): the switch when the zone is fully under the bar (s ≈ 52), not at §2.5's 0.95·(p − b) = 36 — R17 / 老网页 to reconcile; progressOf() kept for the record
    const clip = Math.max(0, barBottom - (restBottom - y - h1.offsetHeight));   // how much of the large title is under the bar (px from its top)
    const st = root.style;
    st.setProperty("--tb-s", s.toFixed(2)); st.setProperty("--tb-small", String(inline)); st.setProperty("--tb-large", String(1 - inline));
    st.setProperty("--tb-clip", Math.min(clip, h1.offsetHeight + 2).toFixed(2) + "px");
    st.setProperty("--tb-edge", y > 0.5 ? "1" : "0"); st.setProperty("--bar", y > 0.5 ? "1" : "0");   // the edge line: 0/1 here, its 0.517 s fade-in curve is in topbar.css (§10b ②)
    st.setProperty("--tb-stretch", "1");   // §10b ③ (probe): the large title does not scale when pulled past the top — it only translates with the content; stretchOf() (2.7) kept for the record
  };
  /* 2.8 release snap curve — nav-bar-scroll-formula.md §2.8b (decompiled, R45): §2.8 only moves the deceleration TARGET to the detent;
     the content then follows UIScrollView's standard deceleration to it: x(t) = target − Δ·r^(1000 t), r = 0.998 per ms
     (_adjustedDecelerationFactor when the velocity change is < .25), time constant ≈ 0.5 s, no overshoot.
     The probe's 22-sample table with an 11 % overshoot (§10b ④) was the navigation BAR's own height animation (54 → 111.67 → 106,
     ~1 s) that the large title rides on — not the scroll offset (the offset was already at the detent within 150 ms); kept here only
     as that record (BAR_T / BAR_P), not used. Its closed form is unread. */
  const SNAP_R = 0.998;
  const snapProgress = (ms) => (ms <= 0 ? 0 : 1 - Math.pow(SNAP_R, ms));   // §2.8b: progress = 1 − r^(ms)
  const SNAP_END_MS = Math.ceil(Math.log(0.5 / 200) / Math.log(SNAP_R));   // ≈ 3 s: 200 pt would be within 0.5 pt of the target
  const BAR_T = [0, 39, 73, 140, 173, 206, 239, 273, 306, 339, 373, 406, 439, 473, 506, 539, 573, 606, 639, 673, 706, 739, 773];
  const BAR_P = [0, .115, .278, .506, .712, .842, .962, 1.056, 1.103, 1.111, 1.107, 1.094, 1.081, 1.064, 1.051, 1.043, 1.030, 1.026, 1.017, 1.013, 1.009, 1.009, 1];
  /* 2.8 release snap: only when the scroll settled inside the collapse range and no finger is down */
  const settle = () => {
    if (dragging || snapping || !api.snap || performance.now() - lastTouchEnd > 1500) return;   // only after a finger just let go (2.8 is a drag-end retarget); programmatic scrolls (tab tap → top spring) are left alone
    const y = window.scrollY; if (!(y > 0.5 && y < p - 0.5)) return;
    const target = snapTarget(y), t0 = performance.now(), y0 = y;
    snapping = true;
    const f = (now) => {
      const yy = target + (y0 - target) * (1 - snapProgress(now - t0));
      if (Math.abs(yy - target) < 0.5 || now - t0 >= SNAP_END_MS) { window.scrollTo(0, target); snapping = false; apply(); return; }   // §2.8b: exponential approach; done within 0.5 pt
      window.scrollTo(0, yy); snapRaf = requestAnimationFrame(f);
    };
    snapRaf = requestAnimationFrame(f);
  };
  let settleTimer = 0;
  const onScroll = () => { apply(); clearTimeout(settleTimer); if ("onscrollend" in window) return; settleTimer = setTimeout(settle, 120); };
  addEventListener("scroll", onScroll, { passive: true });
  if ("onscrollend" in window) addEventListener("scrollend", () => { if (!dragging) settle(); });
  addEventListener("touchstart", () => { dragging = true; if (snapping) { cancelAnimationFrame(snapRaf); snapping = false; } }, { passive: true });
  addEventListener("touchend", () => { dragging = false; lastTouchEnd = performance.now(); }, { passive: true }); addEventListener("touchcancel", () => { dragging = false; lastTouchEnd = performance.now(); }, { passive: true });
  addEventListener("resize", () => { measure(); apply(); });
  addEventListener("load", () => { measure(); apply(); });   // the stylesheets are all in effect by then (a late topbar.css would leave p from index.html's geometry)
  measure(); apply();
  Object.assign(api, { measure, apply, progressOf, snapTarget, snapProgress, stretchOf, B, THRESH, FADE_S, ZONE_BELOW, SNAP_R, BAR_T, BAR_P }); Object.defineProperty(api, "p", { get: () => p }); window.Topbar = api;
})();
