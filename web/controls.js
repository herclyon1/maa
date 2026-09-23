/* controls.js — the press states of two controls, each a state machine on the page's pointer events (loaded after view.js: it uses
   view.js's press() / touchMs() / touchPx() helpers). Every number is a probe or decompile original recorded in remote-ref (the source is
   named where the number is used); nothing here is sampled or guessed. The colours / curves live in controls.css + tokens.css.
   B14 list-row press — remote-ref/cell-native.md §0 (iOS 27.0 probe, deep-hook diff), state-tables/cell.md, dispatch-B14-cell.md.
   B13 switch — dispatch-B13-switch.md (next commit). */
(() => {
  "use strict";

  /* ---------------- B14: UITableViewCell press on .row.nav / .sheet .row.check / .acts button (the blue / red action rows) ----------------
     Timeline (cell-native.md §0, state-tables/cell.md):
       down          nothing changes (UIScrollView delaysContentTouches: 150 ms — --ios-touch-highlight-delay)
       down +150 ms  the fill switches INSTANTLY to the highlight colour (no CAAnimation) and the separator goes to opacity 0 → class .hl
       up            the fade highlight → resting starts on the next frame (+4…17 ms): .5 s cubic-bezier(.42,0,.58,1) → class .hl-out
                     (UIView animateWithDuration:0.5 options:0, curve easeInOut, from deselectRow(animated:)); the selection (our click) fires
                     one frame after that — once the fade's first frame is on screen — because the page's actions block (confirm()) or
                     replace the frame (openPage), which the device check (数据 b14-cell-8bf3bcd.md) saw swallowing the highlight
       short tap     (up before +150 ms) UIKit does not wait for the delay: at the up it highlights, selects and adds the .5 s fade in one
                     turn (probe 60 / 30 ms taps: the fade's CAAnimation at up +17 / +19 ms, the first frame on screen = the highlight colour at
                     up +35 ms — remote-ref/cell-native-shorttap.md; cell-native.md §0's 133 ms tap is the same up +17). So at the up: .hl, a
                     style flush (the highlight becomes the transition's start value), .hl-out at once — the first painted frame is the fade's
                     first frame at the highlight colour — and the click after that paint. The phone delivers pointerdown only ~3 ms before the
                     pointerup of a quick tap (its 诊断记录 ark-diag 20260923-181332: down → up 3 ms), so waiting for the 150 ms timer after
                     the up put the highlight at up +150 and the click at +216 (user report 18:27 items 6–7: the sheet late, the tap half gone)
       cancel        scrolling ≥ 12 pt vertically (threshold 10 = --ios-touch-scroll-threshold) or the finger 15 pt outside the card's edge:
                     the highlight goes off INSTANTLY (.hl-cut kills the base transition of .acts button for that frame) and the up selects
                     nothing — UITableView touchesCancelled: (0x1c4b31830) / touchesMoved: (0x1c4b306a8) un-highlight through
                     _highlightRowAtIndexPath:{none} animated:__UIShouldAnimateDefaultCellHighlightAndSelection, and that function
                     (0x1c3f1c170) returns NO for every idiom but Vision (6) — old page session, iOS 27.0 UIKitCore
       a fast swipe (20 pt within 40 ms) is cancelled before the 150 ms fire, so it never highlights (C9)
     Horizontal movement inside the card (8 / 15 / 100 pt) keeps the press and still selects (C7 C10) — a browser would not deliver its own
     click after such a drag, so the click is ours (fired after the frames) and the browser's own click for the same touch is swallowed
     (data-rc on the row until it comes), the way view.js installPressables does it for UIButtons (data-pe). The alert's action buttons keep installPressables (dialog .acts button). */
  const ROW_SEL = ".row.nav, .sheet .row.check, .acts button";
  const ROW_MS = () => touchMs("--ios-touch-highlight-delay", 150);
  const ROW_FADE_MS = () => touchMs("--ios-motion-row-release-duration", 500);
  const ROW_SCROLL_PT = () => touchPx("--ios-touch-scroll-threshold", 10);
  const ROW_EDGE_PT = 15;   // state-tables/cell.md C11: 15 pt past the card's edge = cancel (no token: the probe's own step, not a UIKit constant read)
  /* the click the page fires, the swallow of the browser's own click (data-rc) and the after-paint scheduling live in motion.js (BOARD #1) */
  function fadeOut(el) {   // .hl → .hl-out in one style change, so the transition runs highlight → resting
    el.classList.add("hl-out"); el.classList.remove("hl");
    let done = false;
    const end = () => { if (done) return; done = true; el.removeEventListener("transitionend", onEnd); el.classList.remove("hl-out"); };
    const onEnd = (ev) => { if (ev.target === el && ev.propertyName === "background-color") end(); };
    el.addEventListener("transitionend", onEnd);
    setTimeout(end, ROW_FADE_MS() + 100);   // a fallback: the transition may be skipped (display change, reduced motion)
  }
  document.addEventListener("pointerdown", (e) => {
    const el = e.target.closest && e.target.closest(ROW_SEL); if (!el || el.disabled || el.closest("dialog")) return;
    if (!e.isPrimary || el.dataset.rp) return;
    const card = el.closest(".group, .plist, .card") || el.parentElement, cr = card.getBoundingClientRect();
    const x0 = e.clientX, y0 = e.clientY, T = ROW_SCROLL_PT();
    let lit = false, over = false, timer = 0;
    const select = () => Motion.click(el);
    /* each step AFTER A PAINT (Motion.afterPaint = rAF → rAF): the highlight paints, then the fade's start paints, then the selection runs —
       an action that blocks the main thread (confirm()) or replaces the content (openPage) cannot swallow either frame */
    const afterPaint = Motion.afterPaint;
    const release = () => { fadeOut(el); afterPaint(select); };   // the fade starts now (painted next frame), the selection after that paint
    const light = () => {   // +150 ms with the finger still down: the highlight, instant
      timer = 0; if (over) return; lit = true; el.classList.add("hl");
    };
    const cancel = () => {   // instant off (no transition even on .acts button, whose rest rule carries one), no select
      if (over) return; over = true; clearTimeout(timer); timer = 0; delete el.dataset.rp;
      if (lit) { lit = false; el.classList.add("hl-cut"); el.classList.remove("hl"); afterPaint(() => el.classList.remove("hl-cut")); }
    };
    if (!press(el, e, {
      move: (ev) => { if (over) return; if (Math.abs(ev.clientY - y0) > T || ev.clientX < cr.left - ROW_EDGE_PT || ev.clientX > cr.right + ROW_EDGE_PT) cancel(); },
      end: (ev, cancelled) => {
        if (cancelled) { cancel(); return; }
        if (over) return;
        over = true; delete el.dataset.rp;
        Motion.swallowNextClick(el);   // the browser's own click for this touch (Android: 40–60 ms after the up) is swallowed, ours follows after the frames
        if (!lit) {                     // a short tap: no wait for the timer — highlight now, flushed so the fade starts from it
          clearTimeout(timer); timer = 0; lit = true; el.classList.add("hl"); void getComputedStyle(el).backgroundColor;
        }
        release();
      },
    })) return;
    el.dataset.rp = "1";
    timer = setTimeout(light, ROW_MS());
  });
  /* a press the page never sees the end of (the app switched away mid-press, the pointer stream lost) would leave a row lit in its
     press colour for good — and a theme change would then show the old theme's colour on that one row (线上第四版 device report:
     「开始刷」 stayed dark after dark → light). The rest colour is the theme's --card token; every state class is stripped when the page
     hides or the theme changes, with no transition on that frame (nothing to animate: the press is over). */
  const stripRows = () => {
    for (const el of document.querySelectorAll(".hl, .hl-out, .hl-cut, [data-rp], [data-rc]")) {
      if (!el.matches(ROW_SEL)) continue;
      el.classList.add("hl-cut"); el.classList.remove("hl", "hl-out"); delete el.dataset.rp; delete el.dataset.rc;
      Motion.afterPaint(() => el.classList.remove("hl-cut"));
    }
  };
  document.addEventListener("visibilitychange", () => { if (document.hidden) stripRows(); });
  try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", stripRows); } catch (e) {}
})();
