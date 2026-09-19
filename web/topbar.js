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
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let p = 52, restBottom = 0, barBottom = 0, dragging = false, snapping = false, snapRaf = 0, lastTouchEnd = -1e9;
  const api = { snap: true };   // snap: the 2.8 release retarget (accept-topbar.js turns it off while it scrolls programmatically)
  const measure = () => {   // at rest (scrollY 0): the collapse range p and where the bar's bottom edge is
    const y = window.scrollY, hr = h1.getBoundingClientRect(), br = bar.getBoundingClientRect();
    barBottom = br.bottom; restBottom = hr.bottom + y; p = Math.max(1, restBottom - barBottom);
  };
  /* §2.4/§2.5 progress → the two titles' alpha (binary, transitions in CSS) */
  const progressOf = (s) => { const c = p - s; return c >= p - B ? 1 : (c <= 0 ? 0 : (c - B) / (p - B)); };
  const snapTarget = (s) => (s < p / 2 ? 0 : p);   // 2.8: nearest resting point, midpoint rule (s in the collapse range)
  const stretchOf = (over) => clamp(1 + over / (devicePixelRatio * screen.height * STRETCH_K), 1, STRETCH_MAX);   // 2.7 (over = pull-down pt)
  const apply = () => {
    const y = window.scrollY;
    const s = clamp(y, 0, p), inline = progressOf(s) < THRESH ? 1 : 0;
    const clip = Math.max(0, barBottom - (restBottom - y - h1.offsetHeight));   // how much of the large title is under the bar (px from its top)
    const st = root.style;
    st.setProperty("--tb-s", s.toFixed(2)); st.setProperty("--tb-small", String(inline)); st.setProperty("--tb-large", String(1 - inline));
    st.setProperty("--tb-clip", Math.min(clip, h1.offsetHeight + 2).toFixed(2) + "px");
    st.setProperty("--tb-edge", y > 0.5 ? "1" : "0"); st.setProperty("--bar", y > 0.5 ? "1" : "0");   // the old glass/line hook follows the edge (binary; its fade is unread)
    st.setProperty("--tb-stretch", stretchOf(Math.max(0, -y)).toFixed(4));
  };
  /* 2.8 release snap: only when the scroll settled inside the collapse range and no finger is down */
  const settle = () => {
    if (dragging || snapping || !api.snap || performance.now() - lastTouchEnd > 1500) return;   // only after a finger just let go (2.8 is a drag-end retarget); programmatic scrolls (tab tap → top spring) are left alone
    const y = window.scrollY; if (!(y > 0.5 && y < p - 0.5)) return;
    const target = snapTarget(y), w = 12, t0 = performance.now(), y0 = y;   // w: the page's measured UIScrollView top-spring (view.js springToTop, 采样)
    snapping = true;
    const f = (now) => {
      const t = (now - t0) / 1000, k = (1 + w * t) * Math.exp(-w * t), yy = target + (y0 - target) * k;
      if (Math.abs(yy - target) < 0.5) { window.scrollTo(0, target); snapping = false; apply(); return; }
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
  measure(); apply();
  Object.assign(api, { measure, apply, progressOf, snapTarget, stretchOf, B, THRESH, FADE_S }); Object.defineProperty(api, "p", { get: () => p }); window.Topbar = api;
})();
