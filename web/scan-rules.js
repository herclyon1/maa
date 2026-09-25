/* scan-rules.js — the one rule set of D79 (BOARD/会议-全量扫-0926-结论.md K4): the full scan injects it into the simulator's standalone window
   (ev2.py, one Web Inspector connection for many steps), and the phone recorder runs the same rules on itself (K10 「页面自检」). Two parts:
   · ScanRules.display — the display rules (外观, K9). This part.
   · ScanRules.func    — the function rules: errors, dead taps, swallowed animations, covered controls, consistency (动效, K9; at the end of this file).

   ScanRules.display.run(opts) → { ms, n: {text, ctl}, out: [ {rule, level, where, text, box: [x, y, w, h], detail} ] }
     level "bug"  = a display bug, straight to the fix list (K8);
     level "diff" = listed in the 差异 column only, never a bug by itself: 外观 judges whether a person can see it; the ones nobody can see are not
                    fixed (K4, the user 09-24 21:45 「人看不出来的就不管了……不要吹毛求疵」).
     opts.rules  = a subset of rule ids (the phone runs at most once a second after a render settles and must stay ≤ 4 ms, K10 — it passes a
                   subset: ScanRules.display.bugRules, the six rules that can return "bug").
     opts.view   = true: only text and controls that reach into the screen's height (the phone; the full scan leaves it off and sees the whole page).
   Run it on a still frame only (after transitions end): a page mid-slide is partly off screen on purpose.
   Reads boxes and computed styles only: no screenshots, no input values (input / textarea / contenteditable text is never read), no storage.

   Rules (K4 「显示」):
   text-overlap   bug   two visible text runs overlap. Each line box (Range.getClientRects) is cut to the ancestors' overflow clip and trimmed
                        vertically to 0.8 em around its middle — a line box is the font's ascent + descent, taller than the ink, so two stacked
                        lines with a tight leading touch without touching ink (近似). A run hidden under a sheet / dialog is not "visible": the
                        topmost element at the run's centre (elementFromPoint) must be the run's element, its ancestor or its descendant.
                        A drawn copy is not a second text: a pair where one run sits under aria-hidden="true" and both say the same words is
                        skipped (the tab bar's selected copy .tcs over .tcg, view.js mkTab; the menu's glass page, menu.js .menu-glass-page).
                        Scrolled content under the floating tab bar is not an overlap while its scroller can still move it above the bar
                        (content scrolls under the bars on iOS, as in safe-area (b)); the same for ctl-overlap.
   ctl-overlap    bug   two visible controls' boxes overlap by more than 1 px each way (a control's own label and its ancestor / descendant
                        controls excepted). Controls = the selector of scripts/mac/sim-coords.py COLLECT, so 「控件」 is the same list everywhere.
   text-clip      bug   a line cut by an ancestor with overflow hidden / clip and no ellipsis (text-overflow: ellipsis or -webkit-line-clamp on
                        that ancestor or between it and the text). Scroll containers (overflow auto / scroll) are not clipping here: text scrolled
                        out of view is fine. A line clipped away completely is a collapsed / hidden part, not counted.
   text-ellipsis  diff  the same cut with an ellipsis: listed for 外观 (the user 09-23 18:45 「整个网站充斥着各自省略号，看不全信息」 → native
                        list cells wrap, textfit.css; whether a given ellipsis is native is 外观's call).
   h-overflow     bug   the page scrolls sideways (scrollWidth > innerWidth + 1), or a visible control / text line is cut by the screen's left or right edge by more than 0.5 px (K6②: 「横向溢出 1 px」 must go red;
                        partly on, partly off; fully off-screen parts are other pages and not counted).
   safe-area      bug   a visible, uncovered control reaches into the safe-area insets (status bar, home indicator, the sides in landscape) by more
                        than 1 px. The insets are read from env(safe-area-inset-*) on a probe. Not counted: (a) the floating tab bar (nav.tabs)
                        and its buttons at the bottom — the native bar sits in the bottom inset, its capsule's bottom edge 21 pt above the screen
                        bottom in a Home Screen web app (hig-kit/NUMBERS.md 「Tab bar (maa) › Position」, tokens.css --ios-tab-capsule-bottom;
                        probe: UITabBar platter y 873 of 956), so a tab control is red only when it reaches lower than that; (b) scrolled
                        content that its scroller can still move out of the inset (content scrolls under the bars on iOS; the edge
                        that stays is what counts).
   tap-size       bug   a control's tap box (its own box ∪ its <label>) smaller than 28 pt in width or height;
                  diff  smaller than 44 pt. Apple HIG › Accessibility › Mobility, table 「iOS, iPadOS: default control size 44x44 pt, minimum
                        control size 28x28 pt」 (developer.apple.com/tutorials/data/design/human-interface-guidelines/accessibility.json,
                        read 09-26 04:4x). A CSS px is a point in the standalone viewport-fit=cover window.
   font-size      diff  visible text whose font size is none of the iOS Large (default) Dynamic Type sizes 34 28 22 20 17 16 15 13 12 11 (HIG ›
                        Typography › Specifications, typography.json read 09-26 04:4x) or of the page's own --ios-*-size tokens.
   text-color     diff  visible text whose colour is none of the page's --ios-* colour tokens (tokens.css, read from :root at run time so dark
                        mode is covered); the contrast ratio against a solid background (WCAG 2.2 1.4.3) is put in detail when one can be read.
   A→B→A (not in run(): it needs pictures) — the scanner's step. For a control A reached two ways (straight in, and in → B → back), take one
                        `xcrun simctl io <udid> screenshot` of each at rest and compare the whole screen below the status bar:
                          areacmp.py direct.png aba.png --box 0 <3 × ScanRules.display.topInset()> <width> <height>
                        (remote-ref/tools/areacmp.py; its self-test must pass first). First line DIFFERENT = bug `aba`, with the heat image. */
(function () {
  "use strict";
  const R = (window.ScanRules = window.ScanRules || {});
  R.SEL = R.SEL || 'button,a[href],input,select,textarea,summary,[role=button],[role=tab],[role=switch],[role=link],[role^=menuitem],[onclick],[tabindex]:not([tabindex="-1"])';

  const IOS_SIZES = [34, 28, 22, 20, 17, 16, 15, 13, 12, 11];
  const LIM = { px: 1, tapMin: 28, tapDefault: 44, em: 0.8 };
  const NOTEXT = "script,style,template,noscript,input,textarea,select,option,[contenteditable]";

  let cs; // per-run computed-style cache
  const st = (el) => { let s = cs.get(el); if (!s) { s = getComputedStyle(el); cs.set(el, s); } return s; };
  const inter = (a, b) => ({ left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) });
  const empty = (r) => r.right - r.left <= 0.5 || r.bottom - r.top <= 0.5;
  const box = (r) => [Math.round(r.left), Math.round(r.top), Math.round(r.right - r.left), Math.round(r.bottom - r.top)];
  const where = (el) => {
    let s = el.tagName.toLowerCase() + (el.id ? "#" + el.id : "");
    const c = typeof el.className === "string" ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : [];
    if (c.length) s += "." + c.join(".");
    const al = el.getAttribute("aria-label"); if (al) s += '[aria-label="' + al.slice(0, 20) + '"]';
    return s;
  };
  const words = (el) => el.closest(NOTEXT) ? "" : (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 24);

  // shown: not display:none / visibility:hidden / [hidden], and (for text) the product of the ancestors' opacity above 5 %.
  function shown(el, needOpacity) {
    if (!el.isConnected || el.closest("[hidden]")) return false;
    const s = st(el); if (s.visibility !== "visible" || s.display === "none") return false;
    if (!needOpacity) return true;
    let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const v = parseFloat(st(e).opacity); o *= isNaN(v) ? 1 : v; if (o < 0.05) break;
    }
    return o >= 0.05;
  }

  // clip: the element's box cut by every ancestor that clips it (overflow ≠ visible), per axis; an absolute element skips the static ancestors
  // up to its containing block, a fixed one stops (its containing block is the viewport). Returns the cut box and the nearest non-scrolling clipper.
  // self = true for a text line: the element that holds the text clips it too.
  function clip(el, r, self) {
    let out = { left: r.left, top: r.top, right: r.right, bottom: r.bottom }, hard = null;
    let pos = self ? "static" : st(el).position; if (pos === "fixed") return { r: out, hard };
    for (let a = self ? el : el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const s = st(a);
      if (pos === "absolute" && s.position === "static" && s.transform === "none") continue;
      const ox = s.overflowX, oy = s.overflowY;
      if (ox !== "visible" || oy !== "visible") {
        const b = a.getBoundingClientRect();
        if (ox !== "visible") { out.left = Math.max(out.left, b.left); out.right = Math.min(out.right, b.right); }
        if (oy !== "visible") { out.top = Math.max(out.top, b.top); out.bottom = Math.min(out.bottom, b.bottom); }
        const scroller = /auto|scroll/.test(ox + oy);
        if (!scroller && !hard && (r.left < b.left - LIM.px || r.right > b.right + LIM.px || r.top < b.top - LIM.px || r.bottom > b.bottom + LIM.px)) hard = a;
      }
      if (s.position === "fixed") break;
      if (s.position !== "static" || s.transform !== "none") pos = s.position;
    }
    return { r: out, hard };
  }

  // not covered: at one of five points along r's middle (10 … 90 %) the topmost element is el, its ancestor or its descendant. Five, not the
  // centre only: two runs that overlap cover each other's centre, and the overlap is what text-overlap / ctl-overlap look for.
  function onTop(el, r) {
    const y = (r.top + r.bottom) / 2; if (y < 0 || y >= innerHeight) return false;
    for (const f of [0.5, 0.1, 0.3, 0.7, 0.9]) {
      const x = r.left + (r.right - r.left) * f; if (x < 0 || x >= innerWidth) continue;
      const h = document.elementFromPoint(x, y);
      if (h && (h === el || el.contains(h) || h.contains(el))) return true;
    }
    return false;
  }

  let insets = null;
  const TABBAR = "nav.tabs";
  // the native floating tab bar's lowest edge above the screen bottom (tokens.css --ios-tab-capsule-bottom, 21 ← UITabBar platter y 873 / 956);
  // in Safari the bar sits higher (env(safe-area-inset-bottom) + 12), so the same limit holds there too
  const tabBottom = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-tab-capsule-bottom")) || 21;
  // how far el's scroller can still move it up (down = true) or down: 0 when el is fixed or nothing around it scrolls that way
  function scrollRoom(el, down) {
    for (let a = el; a && a !== document.documentElement && a !== document.body; a = a.parentElement) {
      const s = st(a); if (s.position === "fixed") return 0;
      if (/auto|scroll/.test(s.overflowY) && a.scrollHeight > a.clientHeight + 0.5) return down ? a.scrollHeight - a.clientHeight - a.scrollTop : a.scrollTop;
    }
    const d = document.scrollingElement || document.documentElement;
    return down ? d.scrollHeight - innerHeight - d.scrollTop : d.scrollTop;
  }
  // a pair of which one is in the tab bar and the other is page content its scroller can still move above the bar (r: the other's box)
  function underBar(a, b, ra, rb) {
    const ta = a.closest(TABBAR), tb = b.closest(TABBAR); if (!ta === !tb) return false;
    const bar = (ta || tb).getBoundingClientRect(), el = ta ? b : a, r = ta ? rb : ra;
    return scrollRoom(el, true) >= r.bottom - bar.top - LIM.px;
  }
  function readInsets() {
    const p = document.createElement("div");
    p.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;visibility:hidden;pointer-events:none;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)";
    document.body.appendChild(p); const s = getComputedStyle(p);
    const v = { top: parseFloat(s.paddingTop) || 0, right: parseFloat(s.paddingRight) || 0, bottom: parseFloat(s.paddingBottom) || 0, left: parseFloat(s.paddingLeft) || 0 };
    p.remove(); return v;
  }

  // the page's own tokens (tokens.css): colours normalised through a probe, sizes as numbers
  let tokKey = "", tokColors = null, tokSizes = null;
  function tokens() {
    const root = document.documentElement, key = root.getAttribute("data-theme") + "|" + matchMedia("(prefers-color-scheme: dark)").matches;
    if (key === tokKey) return;
    tokKey = key; tokColors = new Set(); tokSizes = new Set(IOS_SIZES);
    const rs = getComputedStyle(root), names = [];
    for (const sh of document.styleSheets) { let rules; try { rules = sh.cssRules; } catch (e) { continue; }
      for (const ru of rules) if (ru.style) for (let i = 0; i < ru.style.length; i++) { const n = ru.style[i]; if (n.startsWith("--ios-")) names.push(n); } }
    const p = document.createElement("span"); p.style.display = "none"; document.body.appendChild(p);
    for (const n of new Set(names)) {
      const v = rs.getPropertyValue(n).trim(); if (!v) continue;
      if (/-size$/.test(n) && /^[\d.]+px$/.test(v)) { tokSizes.add(parseFloat(v)); continue; }
      p.style.color = ""; p.style.color = v; if (p.style.color) tokColors.add(getComputedStyle(p).color);
    }
    p.remove();
  }

  const rgba = (c) => { const m = c.match(/[\d.]+/g); return m ? [+m[0], +m[1], +m[2], m[3] === undefined ? 1 : +m[3]] : null; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  function contrast(el, fg) {
    let bg = null;
    for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
      const s = st(a);
      if (s.backgroundImage !== "none" || (s.backdropFilter && s.backdropFilter !== "none") || (s.webkitBackdropFilter && s.webkitBackdropFilter !== "none")) return null;
      const c = rgba(s.backgroundColor); if (c && c[3] > 0) { if (c[3] < 1) return null; bg = c; break; }
    }
    if (!bg) return null;
    const f = [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
    const L1 = lum(f), L2 = lum(bg);
    return Math.round(((Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)) * 100) / 100;
  }

  // the text runs: one per non-blank text node, its line boxes, the element that holds it
  // view = true: only text whose element reaches into the screen's height (the phone's self-check, K10); off-screen rows are checked when
  // scrolled in. Measured on a 306-run / 153-control page at 375 × 812: the line boxes of off-screen runs are most of a run's cost.
  function textRuns(view) {
    const runs = [], rg = document.createRange(), vh = innerHeight, near = new Map();
    const inView = (el) => { let v = near.get(el); if (v === undefined) { const b = el.getBoundingClientRect(); v = b.bottom > 0 && b.top < vh; near.set(el, v); } return v; };
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: (n) => /\S/.test(n.data) && n.parentElement && !n.parentElement.closest(NOTEXT) ? 1 : 3 });
    for (let n = w.nextNode(); n && runs.length < 2000; n = w.nextNode()) {
      const el = n.parentElement; if ((view && !inView(el)) || !shown(el, true)) continue;
      rg.selectNodeContents(n);
      const lines = [...rg.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5);
      if (lines.length) runs.push({ n, el, lines });
    }
    return runs;
  }

  const RULES = ["text-overlap", "ctl-overlap", "text-clip", "text-ellipsis", "h-overflow", "safe-area", "tap-size", "font-size", "text-color"];

  function run(opts) {
    const t0 = performance.now(), want = new Set((opts && opts.rules) || RULES), out = [];
    cs = new Map(); insets = readInsets();
    const add = (rule, level, el, r, detail) => out.push({ rule, level, where: where(el), text: words(el), box: r ? box(r) : null, detail: detail || "" });
    const vw = innerWidth, vh = innerHeight;

    // text
    const runs = (want.has("text-overlap") || want.has("text-clip") || want.has("text-ellipsis") || want.has("h-overflow") || want.has("font-size") || want.has("text-color")) ? textRuns(opts && opts.view) : [];
    const vis = []; // visible, uncovered line pieces for the overlap check
    for (const t of runs) {
      const s = st(t.el), fs = parseFloat(s.fontSize) || 17;
      let top = false, anyVis = false;
      for (const L of t.lines) {
        const c = clip(t.el, L, true), r = c.r; if (empty(r)) continue;
        anyVis = true;
        if (c.hard && (want.has("text-clip") || want.has("text-ellipsis"))) {
          let ell = false; for (let a = t.el; a; a = a.parentElement) { const sa = st(a); if (sa.textOverflow === "ellipsis" || (sa.webkitLineClamp && sa.webkitLineClamp !== "none")) { ell = true; break; } if (a === c.hard) break; }
          const lost = Math.round(Math.max(r.left - L.left, L.right - r.right, r.top - L.top, L.bottom - r.bottom));
          if (ell && want.has("text-ellipsis")) add("text-ellipsis", "diff", t.el, L, "cut " + lost + " px by " + where(c.hard));
          else if (!ell && want.has("text-clip")) add("text-clip", "bug", t.el, L, "cut " + lost + " px by " + where(c.hard) + ", no ellipsis");
        }
        if (want.has("h-overflow") && ((r.left < -0.5 && r.right > 0.5) || (r.right > vw + 0.5 && r.left < vw - 0.5))) add("h-overflow", "bug", t.el, r, "text line past the screen edge");
        if (!top) top = onTop(t.el, r);
        const mid = (r.top + r.bottom) / 2, half = (fs * LIM.em) / 2;
        vis.push({ t, r: { left: r.left, right: r.right, top: Math.max(r.top, mid - half), bottom: Math.min(r.bottom, mid + half) } });
      }
      t.top = top;
      if (!anyVis || !top) continue;
      if (want.has("font-size")) { tokens(); if (![...tokSizes].some((v) => Math.abs(v - fs) < 0.26)) add("font-size", "diff", t.el, t.lines[0], fs + " px (iOS: " + IOS_SIZES.join(" ") + ")"); }
      if (want.has("text-color")) { tokens(); if (!tokColors.has(s.color)) { const k = contrast(t.el, rgba(s.color) || [0, 0, 0, 1]); add("text-color", "diff", t.el, t.lines[0], s.color + (k ? ", contrast " + k + ":1" : "")); } }
    }
    if (want.has("text-overlap")) {
      const v = vis.filter((p) => p.t.top).sort((a, b) => a.r.top - b.r.top), seen = new Set();
      for (let i = 0; i < v.length; i++) for (let j = i + 1; j < v.length && v[j].r.top < v[i].r.bottom; j++) {
        const a = v[i], b = v[j]; if (a.t === b.t) continue;
        if ((a.t.el.closest('[aria-hidden="true"]') || b.t.el.closest('[aria-hidden="true"]')) && a.t.n.data.trim() === b.t.n.data.trim()) continue;   // a drawn copy
        const k = inter(a.r, b.r); if (k.right - k.left <= LIM.px || k.bottom - k.top <= LIM.px) continue;
        if (underBar(a.t.el, b.t.el, a.r, b.r)) continue;
        const id = runs.indexOf(a.t) + ":" + runs.indexOf(b.t); if (seen.has(id)) continue; seen.add(id);
        add("text-overlap", "bug", a.t.el, k, "with " + where(b.t.el) + " 「" + words(b.t.el) + "」");
      }
    }

    // controls
    const ctlRules = ["ctl-overlap", "h-overflow", "safe-area", "tap-size"].some((x) => want.has(x));
    const ctls = [];
    if (ctlRules) for (const el of document.querySelectorAll(R.SEL)) {
      const raw = el.getBoundingClientRect(); if (empty(raw) || (opts && opts.view && (raw.bottom <= 0 || raw.top >= vh))) continue;
      if (!shown(el, false) || el.closest("[inert]") || el.disabled) continue;
      const r = clip(el, raw).r; if (empty(r)) continue;
      ctls.push({ el, raw, r, top: onTop(el, r) });
    }
    for (const c of ctls) {
      const r = c.r;
      if (want.has("h-overflow") && ((r.left < -0.5 && r.right > 0.5) || (r.right > vw + 0.5 && r.left < vw - 0.5))) add("h-overflow", "bug", c.el, r, "control past the screen edge");
      if (!c.top) continue;
      if (want.has("safe-area")) {
        const bad = [], tab = c.el.closest(TABBAR), floor = vh - (tab ? Math.min(insets.bottom, tabBottom()) : insets.bottom);
        if (insets.top > 0 && r.top < insets.top - LIM.px && scrollRoom(c.el, false) < insets.top - r.top) bad.push("top " + Math.round(insets.top - r.top));
        if (insets.bottom > 0 && r.bottom > floor + LIM.px && (tab || scrollRoom(c.el, true) < r.bottom - floor)) bad.push("bottom " + Math.round(r.bottom - floor));
        if (insets.left > 0 && r.left < insets.left - LIM.px) bad.push("left " + Math.round(insets.left - r.left));
        if (insets.right > 0 && r.right > vw - insets.right + LIM.px) bad.push("right " + Math.round(r.right - (vw - insets.right)));
        if (bad.length) add("safe-area", "bug", c.el, r, "into the inset by " + bad.join(", ") + " pt" + (tab ? " past the tab bar's native place, " + tabBottom() + " above the screen bottom" : "") + " (insets " + [insets.top, insets.right, insets.bottom, insets.left].join("/") + ")");
      }
      if (want.has("tap-size")) {
        let u = { left: c.raw.left, top: c.raw.top, right: c.raw.right, bottom: c.raw.bottom };
        const labs = [...(c.el.labels || [])]; const cl = c.el.closest("label"); if (cl) labs.push(cl);
        for (const l of labs) { const b = l.getBoundingClientRect(); if (!empty(b)) u = { left: Math.min(u.left, b.left), top: Math.min(u.top, b.top), right: Math.max(u.right, b.right), bottom: Math.max(u.bottom, b.bottom) }; }
        const w = u.right - u.left, h = u.bottom - u.top, m = Math.min(w, h);
        if (m < LIM.tapMin - 0.5) add("tap-size", "bug", c.el, u, Math.round(w) + "×" + Math.round(h) + " pt < HIG minimum 28×28");
        else if (m < LIM.tapDefault - 0.5) add("tap-size", "diff", c.el, u, Math.round(w) + "×" + Math.round(h) + " pt < HIG default 44×44");
      }
    }
    if (want.has("ctl-overlap")) {
      const v = ctls.filter((c) => c.top).sort((a, b) => a.r.top - b.r.top);
      for (let i = 0; i < v.length; i++) for (let j = i + 1; j < v.length && v[j].r.top < v[i].r.bottom; j++) {
        const a = v[i].el, b = v[j].el;
        if (a.contains(b) || b.contains(a) || [...(a.labels || [])].some((l) => l.contains(b)) || [...(b.labels || [])].some((l) => l.contains(a))) continue;
        const k = inter(v[i].r, v[j].r); if (k.right - k.left <= LIM.px || k.bottom - k.top <= LIM.px) continue;
        if (underBar(a, b, v[i].r, v[j].r)) continue;
        add("ctl-overlap", "bug", a, k, "with " + where(b) + " 「" + words(b) + "」");
      }
    }
    if (want.has("h-overflow")) { const sw = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth); if (sw > vw + 0.5) add("h-overflow", "bug", document.documentElement, null, "page scrolls sideways: scrollWidth " + sw + " > " + vw); }

    cs = null;
    return { ms: Math.round((performance.now() - t0) * 10) / 10, n: { text: runs.length, ctl: ctls.length }, out };
  }

  // the rules that can return level "bug" (text-ellipsis / font-size / text-color only ever return "diff"): the phone recorder keeps "bug" only,
  // so it runs this subset and skips the three diff-only rules (K10 「超 4 ms 减规则」).
  const BUG_RULES = ["text-overlap", "ctl-overlap", "text-clip", "h-overflow", "safe-area", "tap-size"];

  R.display = { run, rules: RULES, bugRules: BUG_RULES, limits: LIM, iosSizes: IOS_SIZES, topInset: () => readInsets().top };
  /* ScanRules.func — the function rules (动效, D79 K4 「功能」 / K9 / K10). The phone recorder (fluency-rec.js) and the full scan judge with the same
     functions, so a rule that turns red in the scan is the rule that fires on the user's phone.
  
     ScanRules.func = {
       control(el)     what the finger touched: { ctl (on-screen words, whitelisted control kinds only), kind, root, input, region, on, off }
       judge(L, hist)  a finished gesture's line → the names of the gesture rules it breaks (hist = the lines before it, oldest first)
       check()         the page rules on the page at rest → { hits: [{ rule, ctl, note }], ms }   (frame boxes and computed styles only, no pixels)
       page            [[name, fn]] the functional page rules (动效, K9)
       tabs, curTab, curShift, scene, OVERLAYS, txt   the page-model readers both sides share
     }
  
     Gesture rules (K4 「功能」 + K10; each names its source):
       err     a JS error / unhandled rejection / console.error / a fetch answered non-2xx or failed while online, in the gesture's window (K4)
       dead    an interactive control (tab / segment / switch / button / menu item — not the one already on, not a disabled one) and within 1 s of the
               press no DOM / class / aria change in its region, no overlay appeared, no scroll (K10: 1 s, 「页面该在一帧内给回应」, native sheets up
               + 54…65 ms, remote-ref/cell-native-shorttap.md; Sentry's dead click is the same test over 7 s, docs.sentry.io …/rage-clicks)
       rage    the same control pressed ≥ 3 times within 2 s (K10, 主持定 2 s)
       undo    a tab / segment switched to A and back within 2 s; a switch flipped and flipped back within 3 s (K10 「马上反悔」)
       reopen  pull to refresh (#ptr data-state 3, refresh.js setState) within 10 s of a tap, or within 10 s of coming back from a background stay
               of ≤ 30 s; a page reload in those windows too (K10 「重开」)
       long    a frame > 100 ms · slow  the first change > 200 ms after the press (web.dev INP 「good」) · late  an overlay on screen > 100 ms after
               the up (native + 54…65, cold + 90) · noanim  a switch changed and nothing animated on it (R5 / R8) · stall  an overlay appeared with no
               animation (R10's class) — D78's four, kept (K10 「保留 D78 原四项」)
     Page rules (run at rest, ≤ 1 per s, each run timed — K10 「页面自检」, over 4 ms the recorder backs off):
       tabfix  a tab in the tab bar whose page, in this shift, holds only entry rows (R1 「切换到晚班的时候不应该显示终末地」)
       tabmiss a section with content whose tab is not in the tab bar (R1 the other way round)
       swdraw  a switch drawn in the other state's knob position / colour (K4 「开关画出的 = 数据里的」; switches of one state are compared with the
               other state's, so it needs both on the page)
       blocked a control in the clear part of the screen whose centre hits something that is not it (K4 遮挡; a scrim left after its overlay closed
               lands here too)
     Not judged here: 「写进去的值 = 显示的值」 for text inputs — the recorder never reads input.value (D78); the scan checks it with its own state
     samples. Pure picture faults (white flash, double image) — K5. */
  {
    const txt = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 24);
    const rowLabel = (el) => { const r = el.closest(".row"); const l = r && r.querySelector("label"); return l ? txt(l.firstChild && l.firstChild.nodeType === 3 ? l.firstChild.textContent : l.textContent) : ""; };
    const REGION = "section, dialog, .sheet, .menu, #subpage, nav, .segctl, .row, header";
    const isOn = (el) => el.classList.contains("on") || el.getAttribute("aria-selected") === "true" || el.getAttribute("aria-current") === "page";
    const isOff = (el) => el.disabled || (el.matches && el.matches(":disabled")) || !!el.closest("[aria-disabled=true], [inert]");   // dead taps count only enabled controls (K4, 结论.md:14; 外观 §2 / §6)
    const control = (t) => {
      const none = { ctl: "", kind: "other", root: null };
      if (!t || !t.closest) return none;
      let el, c;
      if ((el = t.closest("nav.tabs button"))) c = { ctl: txt(el.dataset.tab || el.textContent), kind: "tab", root: t.closest("nav.tabs"), btn: el };
      else if ((el = t.closest(".segctl button"))) c = { ctl: txt(el.dataset.q || el.textContent), kind: "seg", root: el.closest(".segctl"), btn: el };
      else if ((el = t.closest(".sw, [role=switch]"))) c = { ctl: (rowLabel(el) || txt(el.getAttribute("aria-label"))) + "·开关", kind: "switch", root: el, btn: el.querySelector("input") || el, input: el.querySelector("input[type=checkbox]") || (el.matches("input") ? el : null) };
      else if ((el = t.closest("input, textarea, select"))) c = { ctl: rowLabel(el) + "·输入框", kind: "input", root: el, btn: el };   // never el.value
      else if ((el = t.closest("button, a, summary, [role=button], [role=tab], [role=menuitem]"))) c = { ctl: txt(el.getAttribute("aria-label") || el.textContent), kind: el.closest("[role=menu], .menu") ? "menu" : "button", root: el, btn: el };
      else if ((el = t.closest(".row"))) c = { ctl: rowLabel(el), kind: "row", root: el };
      else return none;
      c.region = c.root.closest(REGION) || c.root;
      c.on = c.btn ? isOn(c.btn) : false;
      c.off = c.btn ? isOff(c.btn) : false;
      return c;
    };
    const curTab = () => { const b = document.querySelector("nav.tabs button.on"); return b ? txt(b.dataset.tab || b.textContent) : ""; };
    const curShift = () => { const b = document.querySelector("#app > .segctl:not([hidden]) button.on"); return b ? txt(b.dataset.q || b.textContent) : ""; };
    const OVERLAYS = "dialog[open], .sheet, .menu, #subpage, #toast, [role=dialog], [role=menu]";
    const vis = (e) => { if (e.hidden || !e.getClientRects().length) return false; const cs = getComputedStyle(e); return cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity !== 0; };
    const scene = () => { const out = []; for (const e of document.querySelectorAll(OVERLAYS)) if (vis(e)) out.push(e.id ? "#" + e.id : e.tagName.toLowerCase() + (e.classList[0] ? "." + e.classList[0] : "")); return out.sort().join(" "); };
    const tabs = () => [...document.querySelectorAll("nav.tabs button")].map((b) => txt(b.dataset.tab || b.textContent));

    /* gesture rules: [name, (L, hist) => broken?] over the recorder's line (fluency-rec.js finish() builds it; the scan reads FluRec.lines) */
    const DEAD_KINDS = new Set(["tab", "seg", "switch", "button", "menu"]);
    const G = [
      ["err", (L) => !!L.err],
      ["long", (L) => L.n100 > 0],
      ["slow", (L) => L.react !== null && L.react > 200 && L.kind !== "input"],
      ["late", (L) => L.scene_up !== null && L.scene_up > 100],
      ["noanim", (L) => !!(L.sw && L.sw[0] !== L.sw[1] && !L.anim.ctl && !L.anim.ctl_ms)],
      ["stall", (L) => !!L.stall],
      ["dead", (L) => !!L.settled && DEAD_KINDS.has(L.kind) && !L.was_on && !L.disabled && (L.near === null || L.near > 1000)],
      ["rage", (L, h) => { if (!L.ctl || L.kind === "input" || L.kind === "reload") return false; const a = h[h.length - 1], b = h[h.length - 2]; return !!(a && b && a.ctl === L.ctl && b.ctl === L.ctl && L.at - b.at <= 2000); }],
      ["undo", (L, h) => { const p = h[h.length - 1]; if (!p || p.kind !== L.kind) return false;
        if (L.kind === "tab") return p.ctl !== p.tab && L.ctl === p.tab && L.at - p.at <= 2000;
        if (L.kind === "seg") return p.ctl !== p.shift && L.ctl === p.shift && L.at - p.at <= 2000;
        if (L.kind === "switch") return p.ctl === L.ctl && !!p.sw && !!L.sw && p.sw[0] !== p.sw[1] && L.sw[0] !== L.sw[1] && L.sw[1] === p.sw[0] && L.at - p.at <= 3000;
        return false; }],
      ["reopen", (L, h) => { if (!L.refresh) return false; const p = [...h].reverse().find((x) => !x.refresh && x.kind !== "reload");
        return !!(p && L.at - p.at <= 10e3) || !!(L.back && L.back.away <= 30e3 && L.at - L.back.at <= 10e3); }],
    ];
    const judge = (L, hist) => G.filter(([, f]) => { try { return f(L, hist || []); } catch (e) { return false; } }).map(([n]) => n);

    /* page rules: [name, () => [{ ctl, note }]] on the page at rest */
    const entryOnly = () => { const out = []; for (const t of tabs()) { const secs = [...document.querySelectorAll("#app > section")].filter((s) => s.dataset.tab === t && s.dataset.empty !== "1"); if (secs.length && secs.every((s) => s.dataset.tabfix)) out.push(t); } return out; };
    const P = [
      ["tabfix", () => entryOnly().map((t) => ({ ctl: t, note: "本班只剩入口行" }))],
      ["tabmiss", () => { const nav = document.querySelector("nav.tabs"); if (!nav || !vis(nav)) return []; const ts = new Set(tabs()), out = new Set();
        for (const s of document.querySelectorAll("#app > section[data-tab]")) if (s.dataset.empty !== "1" && !s.dataset.tabfix && !ts.has(s.dataset.tab)) out.add(s.dataset.tab);
        return [...out].map((t) => ({ ctl: t, note: "有内容但标签栏里没有" })); }],
      ["swdraw", () => { const look = (sw) => { const s = sw.querySelector("span"); if (!s) return ""; const a = getComputedStyle(s, "::after"); return `${a.translate}|${a.transform}|${a.left}|${getComputedStyle(s).color}`; };
        const on = new Map(), off = new Map();
        for (const sw of document.querySelectorAll(".sw")) { const i = sw.querySelector("input[type=checkbox]"); if (!i || !sw.getClientRects().length || sw.matches(".drive, .pressed")) continue;
          if (sw.getAnimations({ subtree: true }).some((a) => a.playState === "running")) continue;
          (i.checked ? on : off).set(sw, look(sw)); }
        if (!on.size || !off.size) return [];
        const count = (m) => { const c = {}; for (const v of m.values()) c[v] = (c[v] || 0) + 1; return c; };
        const cOn = count(on), cOff = count(off), out = [];
        for (const [m, other, c] of [[on, cOff, cOn], [off, cOn, cOff]]) for (const [sw, v] of m) if (other[v] && !(c[v] > other[v])) out.push({ ctl: rowLabel(sw) + "·开关", note: m === on ? "开着却画成关" : "关着却画成开" });
        return out; }],
      ["blocked", () => { const h = document.querySelector("header"), top = h && vis(h) ? h.getBoundingClientRect().bottom : 0;
        const nav = document.querySelector("nav.tabs"), bot = nav && vis(nav) ? nav.getBoundingClientRect().top : innerHeight;
        const layer = [...document.querySelectorAll(OVERLAYS)].filter((e) => vis(e) && e.id !== "toast").pop();
        const scope = layer ? [layer] : [document.getElementById("app"), nav].filter(Boolean), out = [];
        for (const root of scope) for (const el of root.querySelectorAll("button, .sw, [role=button], [role=switch], a[href], summary")) {
          if (!vis(el) || isOff(el) || getComputedStyle(el).pointerEvents === "none") continue;
          const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
          if (x < 0 || x > innerWidth || y < 0 || y > innerHeight || (!layer && !(nav && nav.contains(el)) && (y < top + 1 || y > bot - 1))) continue;   // under the bars on purpose
          const hit = document.elementFromPoint(x, y);
          if (!hit || el.contains(hit) || hit.contains(el)) continue;
          out.push({ ctl: control(el).ctl || txt(el.textContent), note: "中心点压着 " + (hit.id ? "#" + hit.id : hit.tagName.toLowerCase() + (hit.classList[0] ? "." + hit.classList[0] : "")) });
          if (out.length >= 5) break;
        }
        return out; }],
    ];
    const check = () => {
      const t0 = performance.now(), hits = [];
      for (const [rule, f] of P) { try { for (const x of f() || []) hits.push({ rule, ctl: x.ctl || "", note: x.note || "" }); } catch (e) { hits.push({ rule, ctl: "", note: "规则自身出错 " + txt(e.message) }); } }
      return { hits, ms: Math.round((performance.now() - t0) * 100) / 100 };
    };
    R.func = { control, judge, check, page: P, gesture: G, tabs, curTab, curShift, scene, OVERLAYS, txt, rowLabel };
  }
})();
