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
  /* ---- R3 the scroll pocket (BOARD round 2; material from the read keys only, A20) ----
     Layers (nav-pocket-sdfdump-2026-09-19.md §1 / §2, the dumps uiprobe-sdf-navpocket-{light,dark}.json; nav-bar-scroll-formula.md §3.3 / §3.4 / §6b):
     ScrollEdgeEffectView 440 × 116 (the status bar 62 + the collapsed bar 54), alpha 0 at rest at the top (shouldHideAtTop) / 1 once scrolled;
     under it, in z-order: the Replay layer — a CABackdropLayer 440 × 116 with backdrop enabled 0 (samples nothing) and a flat gradient white·white
     light / black·black dark, opacity .5 light / .6 dark (§6b: replayLightModeAlpha .5 / replayDarkModeAlpha .6; the dumps' opacity .5 / .6000);
     above it the blur backdrop (scale .5) with filters [variableBlur inputRadius 2 + inputMaskImage 1 × 384 + BlurFill 16 / darken .4 / lighten .6 /
     normal .25 (dark .6 / .4 / 0), colorMatrix diag 1.1969 / 1.0712 / 1.232 with bias .03 (the dump's 4 × 5), sdrNormalize clamp 1 / preserveHue 1];
     a ⅓ pt hairline at the bottom, black α .10 light / white α .10 dark.
     Here: a fixed layer at the top, height = safe-area-top + 54, opacity from --tb-edge (0 at rest, 1 once scrolled); inside it a clone of #app kept
     on the page's pixels (translateY(−scrollY) per scroll, re-cloned when #app's children change) through one SVG filter in the layers' order:
     the flat replay flood composited over the content first (it lies under the blur backdrop, so the backdrop samples it), then the blur
     (feGaussianBlur σ = 2 ÷ .5 = 4 pt: the radius is in samples of the half-resolution capture, the same reading as alert-pipeline-plan §1.3),
     BlurFill as in menu-card-material §7.2 (bf at σ 16 ÷ .5 = 32 pt — 近似 mip, as the read says), the colour matrix, then a hairline element.
     Not built: the variable blur's mask (the 1 × 384 column's values are not in the dump — 待读, an imgdump read; until then the blur is uniform
     over the pocket, which the read says it is NOT: the mask fades it); sdrNormalize (a no-op on 8-bit values); the status-bar replay layer
     (elsewhere, unread); backdrop-filter cannot take an SVG filter, hence the clone. */
  const POCKET = { light: { replay: [255, 255, 255, 0.5], blur: 2, scale: 0.5, bf: 16, darken: 0.4, lighten: 0.6, normal: 0.25, matrix: [1.1969, -0.1789, -0.018, 0, 0.03, -0.0531, 1.0712, -0.0181, 0, 0.03, -0.0532, -0.1787, 1.232, 0, 0.03], hairline: [0, 0, 0, 0.1] },
    dark: { replay: [0, 0, 0, 0.6], darken: 0.6, lighten: 0.4, normal: 0, hairline: [255, 255, 255, 0.1] } };
  const pocketTheme = () => (matchMedia("(prefers-color-scheme: dark)").matches && root.dataset.theme !== "light") || root.dataset.theme === "dark" ? "dark" : "light";
  const pocketKeys = (th) => ({ ...POCKET.light, ...(th === "dark" ? POCKET.dark : {}) });
  const NS = "http://www.w3.org/2000/svg";
  const pocketFilter = (th) => { const k = pocketKeys(th); let svg = document.getElementById("topbar-pocket-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "topbar-pocket-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const rp = k.replay, sig = k.blur / k.scale, bfs = k.bf / k.scale;
    svg.innerHTML = `<filter id="topbar-pocket-f" x="-10%" y="-25%" width="120%" height="150%" color-interpolation-filters="sRGB" data-theme="${th}" data-sigma="${sig}" data-bf-sigma="${bfs}">`
      + `<feFlood flood-color="rgb(${rp[0]},${rp[1]},${rp[2]})" flood-opacity="${rp[3]}" result="rp"/><feComposite in="rp" in2="SourceGraphic" operator="over" result="src"/>`   // the Replay layer under the blur backdrop
      + `<feGaussianBlur in="src" stdDeviation="${sig}" result="blur"/><feGaussianBlur in="src" stdDeviation="${bfs}" result="bf"/>`
      + `<feBlend in="blur" in2="bf" mode="darken" result="mn"/><feBlend in="blur" in2="bf" mode="lighten" result="mx"/>`
      + `<feComposite in="mn" in2="mx" operator="arithmetic" k2="${k.darken}" k3="${k.lighten}" result="dl"/><feComposite in="dl" in2="blur" operator="arithmetic" k2="1" k3="${1 - k.darken - k.lighten}" result="bfo"/>`
      + `<feComposite in="bfo" in2="bf" operator="arithmetic" k2="${1 - k.normal}" k3="${k.normal}" result="c"/>`
      + `<feColorMatrix in="c" type="matrix" values="${k.matrix.join(" ")} 0 0 0 1 0" result="cm"/></filter>`; return k; };
  const pocket = { el: null, copy: null, hair: null, theme: null, main: document.getElementById("app") };
  const pocketBuild = () => { if (!pocket.main) return; const th = pocketTheme(); const k = pocketFilter(th);
    if (!pocket.el) { pocket.el = document.createElement("div"); pocket.el.className = "topbar-pocket"; pocket.el.setAttribute("aria-hidden", "true"); pocket.hair = document.createElement("i"); pocket.hair.className = "topbar-pocket-hair"; document.body.appendChild(pocket.el); }
    if (pocket.copy) pocket.copy.remove(); const copy = pocket.main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, script, .menu, .menu-scrim, nav.tabs").forEach((e) => e.remove()); copy.className = "topbar-pocket-copy"; copy.inert = true;
    const mr = pocket.main.getBoundingClientRect(); copy.style.cssText = `position:absolute;left:${mr.left}px;top:0;width:${mr.width}px;pointer-events:none;filter:url(#topbar-pocket-f)`; pocket.el.appendChild(copy); pocket.el.appendChild(pocket.hair); pocket.copy = copy; pocket.theme = th; pocket.top0 = mr.top + window.scrollY;
    const h = k.hairline; pocket.hair.style.background = `rgba(${h[0]},${h[1]},${h[2]},${h[3]})`; pocketPlace(); };
  const pocketPlace = () => { if (!pocket.copy) return; pocket.copy.style.transform = `translateY(${(pocket.top0 - window.scrollY).toFixed(2)}px)`; };
  const pocketObs = new MutationObserver(() => { clearTimeout(pocket.t); pocket.t = setTimeout(pocketBuild, 60); });
  if (pocket.main) { pocketBuild(); pocketObs.observe(pocket.main, { childList: true, subtree: true, characterData: true }); addEventListener("scroll", pocketPlace, { passive: true }); try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", pocketBuild); } catch (e) {} }
  window.TopbarPocket = { keys: pocketKeys, theme: pocketTheme, rebuild: pocketBuild, get el() { return pocket.el; } };
  if ("onscrollend" in window) addEventListener("scrollend", () => { if (!dragging) settle(); });
  addEventListener("touchstart", () => { dragging = true; if (snapping) { cancelAnimationFrame(snapRaf); snapping = false; } }, { passive: true });
  addEventListener("touchend", () => { dragging = false; lastTouchEnd = performance.now(); }, { passive: true }); addEventListener("touchcancel", () => { dragging = false; lastTouchEnd = performance.now(); }, { passive: true });
  addEventListener("resize", () => { measure(); apply(); });
  addEventListener("load", () => { measure(); apply(); });   // the stylesheets are all in effect by then (a late topbar.css would leave p from index.html's geometry)
  measure(); apply();
  Object.assign(api, { measure, apply, progressOf, snapTarget, stretchOf, B, THRESH, FADE_S, ZONE_BELOW }); Object.defineProperty(api, "p", { get: () => p }); window.Topbar = api;
})();
