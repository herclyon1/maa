/* fluency-rec.js — the always-on gesture recorder on the user's own phone (dispatch BOARD/派单-0929夜.md 「中继一」, D96 the user 09-29 04:1x
   「做出能检测实际检测这两个的工具」; privacy and "send only when something happened" = D92, the same rules as crash-rec.js).
   Ported from ui 84051db web/fluency-rec.js (D79 K10–K12), trimmed to the three things asked for: glass-gesture stalls, taps that got no
   answer, repeated taps — plus script errors inside a gesture. The page self-check / display rules of 84051db (scan-rules.js) are not here.
   Why not an off-the-shelf library: BOARD/现成工具排查-0929.md 「真机记录」 (the browser APIs they are built on are not in iOS Safari).

   ONE GESTURE (pointerdown … the page quiet again for SETTLE_MS, at most HARD_MS) = one line, judged at once:
     long   a frame interval > 100 ms anywhere in the gesture (the main thread was blocked; 84051db rule "long")
     jank   a glass gesture (below) with a frame interval ≥ 50 ms (the threshold of remote-ref/tools/glass/gap.py, BOARD/派单-0929夜.md 数据节)
     choppy a glass gesture with ≥ 6 frame intervals in a row > 25 ms (the user said on 09-29 16:50 the segment looked like only 30 fps: 30 fps = 33 ms
            a frame, which jank's 50 ms never caught; one frame is 8.3 ms at 120 Hz and 16.7 ms at 60 Hz, so a smooth gesture at either rate never trips it)
     wait   the press itself reached the page > 100 ms late (pointerdown handled − event.timeStamp: the main thread was busy before the tap)
     slow   the first visible change > 200 ms after the lift (react; web.dev INP "good" = 200 ms; 84051db rule "slow")
     inp    the browser's own Event Timing entry for the press (input → next paint) > 200 ms — the standard API, where the phone has it
            (Safari 26.2+: webkit.org/blog/17640; the same 200 ms line)
     dead   a tab / segment / switch / button / menu item (not already on, not disabled) whose region showed no DOM / class / aria change, no
            overlay and no scroll within 1 s of the lift (84051db rule "dead", K10 1 s)
     rage   the same control pressed 3 times within 2 s (84051db rule "rage", K10)
     err    a script error / unhandled rejection between the press and the end of the gesture
   Glass gestures: the control is .menubtn / a .menu item / nav.tabs / .segctl / .sw / .navbtn #discard #save, or a glass overlay appeared
   (.menu-body, dialog#alert / #confirm, #toast.show) or the tap is on .menu-scrim (closing a menu) — the components of 数据's glass-check list.

   A line: at (Date.now()), pn, v, ctl (the control's on-screen words, whitelisted control kinds only, scrubbed), id (the element, for rage), kind, watched (ms the press was watched), glass, tab, wait, press,
   first, near, scene, et (Event Timing: name, dur, delay, proc), loaf (the ≤ 6 longest Long Animation Frames overlapping the gesture: at, dur, block, rs, sl,
   scripts [{src, pos, fn, inv, dur}]), prewarm_done / prewarm_left (the menu glass warm-up at the press), menu_maps (a menu button: {h, img, stroke} = its own maps cached at the press),
   alert_warm ({sz, img, stroke, cached, all: [{sz, img, stroke}…]}: the alert warm-up at the press), gpu_warm ({s0, state, at, end, yields, tries}: menu.js's GPU warm-up — s0 its state at the press,
   the rest at the line's end, at / end in ms since load (compare with pn and loaf)), nf, max, n50, n100, run25 (the longest run of intervals > 25 ms in a row), big (the longest 5 intervals with their ms after the press), err, bad,
   draws (WebGL draw calls onto a visible canvas inside the pressed control's region — the segment / tab-bar lens canvases — in the same frames as nf:
   the interval that straddles the press is left out of draws, dfr and d_rate alike; null when none: a control without a lens canvas, or a lens that never drew),
   dfr (rAF frames from the first to the last frame with such a draw), d_rate (frames with a draw ÷ dfr: 1 = the canvas was redrawn every frame the display
   gave the page, .5 = every other frame). fi (every frame interval)
   rides along only on a line with a hit, and only the first time for version × rule × control (K12), ≤ 600.
   NEVER RECORDED: input.value (never read), the screen, localStorage, the URL's query / hash (scrub(): everything from ? or # goes — the
   no-typing login link's key is in #k=), any 32+ character token, a fetch.

   SENDING (D92: only when something happened): the lines stay in memory (RING_N newest). The first hit schedules one upload SEND_MS later (every
   hit in that window goes with it); going to the background sends a pending hit at once (fetch keepalive, body ≤ 60 KB). One upload = the lines with a hit
   since the last upload + up to CTX_N not-yet-sent lines before each as context. At most DAY_MAX uploads and DAY_BYTES a day (ark-flu-day); every
   upload is queued in ark-flu-queue before its PUT and waits there on failure (the recorder's keys ≤ OWN_MAX bytes together, oldest dropped first, never another key) for the next start.
   Bucket = crash-rec's (anonymous PUT on diag/*, forbid-overwrite; ?diagbucket= / localStorage ark-diag-bucket override for the test bench).
   Keys diag/flu/<Tokyo YYYYMMDDHHMMSS>-<sid>-<n>.json; scripts/mac/diag-pull.py fetches them with the rest of diag/.
   Not in an iframe; under ?accept nothing but window.FluRules (choppy's counting, pure, for accept-flurec.js). window.FluRec = {lines, stats, queue(), flush(), day()}. Every handler is wrapped. */
(function () {
  try {
    if (window.top !== window || window.FluRec) return;
    /* choppy's counting: pure functions, set before the ?accept return so accept-flurec.js can feed them samples */
    const CHOPPY_MS = 25, CHOPPY_N = 6;
    const runOver = (ms, lim) => { let n = 0, best = 0; for (const x of ms) { n = x > lim ? n + 1 : 0; if (n > best) best = n; } return best; };
    const choppy = (L) => !!L.glass && L.run25 >= CHOPPY_N;
    window.FluRules = { runOver, choppy, CHOPPY_MS, CHOPPY_N };
    const q = new URLSearchParams(location.search);
    if (q.has("accept")) return;
    const RING_N = 300, CTX_N = 5, SETTLE_MS = 400, HARD_MS = 10e3, DEAD_MS = 1000, SEND_MS = 30e3, DAY_MAX = 12, DAY_BYTES = 1e6,
      BODY_MAX = 60e3, OWN_MAX = 60e3, FI_MAX = 600;
    const QKEY = "ark-flu-queue", DKEY = "ark-flu-day", SKEY = "ark-flu-fi";
    const get = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
    const set = (k, v) => { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } };
    const parse = (s, d) => { try { return s ? JSON.parse(s) : d; } catch (e) { return d; } };
    const BUCKET = (() => { let v = ""; try { v = q.get("diagbucket") || get("ark-diag-bucket") || ""; } catch (e) {}
      return (v || "https://ark-diag-1315873325.cos.ap-shanghai.myqcloud.com").trim().replace(/\/+$/, ""); })();
    const raf = window.requestAnimationFrame && window.requestAnimationFrame.bind(window), fetch0 = window.fetch && window.fetch.bind(window);
    if (!raf) return;
    const ver = (() => { try { const s = (document.currentScript && document.currentScript.src) || ""; const m = /[?&]v=([^&#]+)/.exec(s); return m ? m[1] : "local"; } catch (e) { return "?"; } })();
    const hex = (n) => { try { return Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, "0")).join(""); }
      catch (e) { let s = ""; while (s.length < n * 2) s += Math.random().toString(16).slice(2); return s.slice(0, n * 2); } };
    const sid = hex(4);
    const scrub = (s) => { try { return String(s == null ? "" : s).replace(/[?#][^\s"'`<>()[\]{}:,]*/g, "").replace(/[A-Za-z0-9_\-+=]{32,}/g, "[…]"); } catch (e) { return ""; } };
    const txt = (s, n) => scrub((s || "").replace(/\s+/g, " ").trim()).slice(0, n || 24);
    const on = (tgt, ev, fn, opt) => { try { tgt.addEventListener(ev, (e) => { try { fn(e); } catch (x) {} }, opt); } catch (e) {} };

    /* ---- the page model (84051db scan-rules.js ScanRules.func: control / scene / curTab, trimmed) ---- */
    const SECRET = /pin|密码|口令|password|passwd|key|token|secret/i;   // = crash-rec.js SECRET
    const rowLabel = (el) => { const r = el.closest(".row"); const l = r && r.querySelector("label"); return l ? txt(l.firstChild && l.firstChild.nodeType === 3 ? l.firstChild.textContent : l.textContent) : ""; };
    const REGION = "section, dialog, .sheet, .menu, #subpage, nav, .segctl, .row, header";
    const isOn = (el) => el.classList.contains("on") || el.getAttribute("aria-selected") === "true" || el.getAttribute("aria-current") === "page";
    const isOff = (el) => !!(el.disabled || el.getAttribute("aria-disabled") === "true" || el.closest("[inert]"));
    const GLASS_CTL = [[".menubtn", "menu"], [".menu button, .menu [role=menuitem]", "menu-item"], ["nav.tabs", "tab-lens"], [".segctl", "seg-lens"],
      [".sw, [role=switch]", "switch"], [".navbtn, #discard, #save", "glassbtn"], [".menu-scrim", "menu-close"]];
    const ids = new WeakMap(); let idN = 0;
    const idOf = (el) => { if (!el) return 0; let n = ids.get(el); if (!n) { n = ++idN; ids.set(el, n); } return n; };
    /* a press on the segment's lifted lens (i.lens and its layers cover the buttons while a previous press's lens is still up — a tap right after
       another) is still a press on the segment under the finger: the button whose x-range holds the press's x. The ranges are read (getBoundingClientRect)
       only when a gesture on that segment has settled, and kept per segment node until a resize (the page never scrolls sideways): reading them in the
       pointerdown would force a layout inside the very press being timed (the lens restyles every frame) and LoAF would charge it to this file. Without
       ranges yet, the press keeps its x and the button is found when the gesture settles (a gesture cut short by the next press stays ctl "") */
    const segX = new WeakMap(); let segGen = 0; on(window, "resize", () => { segGen++; });
    const segAt = (s, x, read) => { let c = segX.get(s); if (!c || c.gen !== segGen) { if (!read) return -1;
      c = { gen: segGen, r: [...s.querySelectorAll("button")].map((b) => { const q = b.getBoundingClientRect(); return [q.left, q.right]; }) }; segX.set(s, c); }
      return c.r.findIndex(([a, b]) => x >= a && x < b); };
    /* where a region is in the page, to find it again after a re-render swapped the node: view.js render() keeps #queueseg across a commit
       (replaceKeeping) but falls back to #app.innerHTML = html — a new segment and a new lens canvas — when the queue list or the tree shape changed */
    const keyOf = (el) => { if (el.id) return ["#" + CSS.escape(el.id), 0]; const s = el.tagName.toLowerCase() + (el.classList[0] ? "." + CSS.escape(el.classList[0]) : "");
      return [s, [...document.querySelectorAll(s)].indexOf(el)]; };
    const regionNow = (G) => { const R = G.c.region; if (!R || R.isConnected || !G.c.rk || G.c.rk[1] < 0) return R;
      const n = document.querySelectorAll(G.c.rk[0])[G.c.rk[1]]; if (n) G.c.region = n; return n || R; };
    const control = (t, x) => {
      const none = { ctl: "", kind: "other", root: null, region: null, on: false, off: false, glass: "" };
      if (!t || !t.closest) return none;
      let el, c;
      if ((el = t.closest("nav.tabs button"))) c = { ctl: txt(el.dataset.tab || el.textContent), kind: "tab", root: t.closest("nav.tabs"), btn: el };
      else if ((el = t.closest(".segctl button"))) c = { ctl: txt(el.dataset.q || el.textContent), kind: "seg", root: el.closest(".segctl"), btn: el };
      else if ((el = t.closest(".segctl"))) { const bs = [...el.querySelectorAll("button")], i = segAt(el, x, false);
        c = i >= 0 ? { ctl: txt(bs[i].dataset.q || bs[i].textContent), kind: "seg", root: el, btn: bs[i] }
          : { ctl: "", kind: "seg", root: el, x, bon: bs.map(isOn), boff: bs.map(isOff) }; }   // the buttons' state at the press, for was_on / disabled
      else if ((el = t.closest(".sw, [role=switch]"))) c = { ctl: (rowLabel(el) || txt(el.getAttribute("aria-label"))) + "·开关", kind: "switch", root: el, btn: el.querySelector("input") || el, input: el.querySelector("input[type=checkbox]") || (el.matches("input") ? el : null) };
      else if ((el = t.closest("input, textarea, select"))) c = { ctl: ([el.id, el.name, el.placeholder, el.getAttribute("aria-label")].some((s) => s && SECRET.test(s)) ? "[secret]" : rowLabel(el)) + "·输入框", kind: "input", root: el, btn: el };   // never el.value
      else if ((el = t.closest("button, a, summary, [role=button], [role=tab], [role=menuitem]"))) c = { ctl: txt(el.getAttribute("aria-label") || el.textContent), kind: el.closest("[role=menu], .menu") ? "menu" : "button", root: el, btn: el };
      else if ((el = t.closest(".row"))) c = { ctl: rowLabel(el), kind: "row", root: el };
      else return none;
      c.region = c.root.closest(REGION) || c.root; c.rk = keyOf(c.region);
      c.id = idOf(c.btn || c.root);
      c.on = c.btn ? isOn(c.btn) : false;
      c.off = c.btn ? isOff(c.btn) : false;
      c.glass = ""; for (const [s, g] of GLASS_CTL) if (t.closest(s)) { c.glass = g; break; }
      return c;
    };
    const curTab = () => { const b = document.querySelector("nav.tabs button.on"); return b ? txt(b.dataset.tab || b.textContent) : ""; };
    const OVERLAYS = "dialog[open], .sheet, .menu-body, #subpage, #toast.show, [role=dialog], [role=menu]";
    const GLASS_OV = [[".menu-body, [role=menu]", "menu"], ["dialog#alert, dialog#confirm", "alert"], ["#toast", "toast"]];
    const shown = (e) => { if (e.hidden || !e.getClientRects().length) return false; const cs = getComputedStyle(e); return cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity !== 0; };
    const scene = () => { const out = []; for (const e of document.querySelectorAll(OVERLAYS)) if (shown(e)) out.push(e.id ? "#" + e.id : e.tagName.toLowerCase() + (e.classList[0] ? "." + e.classList[0] : "")); return out.sort().join(" "); };
    const glassOf = (sel) => { for (const [s, g] of GLASS_OV) if (document.querySelector(sel) && document.querySelector(sel).matches(s)) return g; return ""; };

    /* ---- the rules ---- */
    const DEAD_KINDS = new Set(["tab", "seg", "switch", "button", "menu"]);
    const RULES = [
      ["err", (L) => !!L.err],
      ["long", (L) => L.n100 > 0],
      ["jank", (L) => !!L.glass && L.n50 > 0],
      ["choppy", choppy],
      ["wait", (L) => L.wait !== null && L.wait > 100],
      ["slow", (L) => L.react !== null && L.react > 200 && L.kind !== "input"],
      ["inp", (L) => !!L.et && L.et.dur > 200],
      ["dead", (L) => { if (!DEAD_KINDS.has(L.kind) || L.was_on || L.disabled) return false; const up = L.press || 0;   // counted from the lift: a button answers its click
        return L.near === null ? L.watched - up >= DEAD_MS : L.near - up > DEAD_MS; }],   // watched: a press cut short by the next one within 1 s of its lift is not judged
      ["rage", (L, h) => { if (!L.id || L.kind === "input" || L.kind === "other") return false; const a = h[h.length - 1], b = h[h.length - 2]; return !!(a && b && a.id === L.id && b.id === L.id && L.at - b.at <= 2000); }],   // the same element (its words may change with each press)
    ];
    const judge = (L, h) => RULES.filter(([, f]) => { try { return f(L, h); } catch (e) { return false; } }).map(([n]) => n);

    /* ---- errors ---- */
    const errs = [];
    const note = (m) => { errs.push(txt(m, 160)); if (errs.length > 200) errs.splice(0, 100); };
    on(window, "error", (e) => { if (e.target && e.target !== window) return; note((e.message || "error") + " @" + String(e.filename || "").split("/").pop() + ":" + (e.lineno || 0)); }, true);
    on(window, "unhandledrejection", (e) => note("promise: " + ((e.reason && e.reason.message) || String(e.reason))));

    /* ---- the browser's own interaction timing (Event Timing API, the INP basis; Safari 26.2+, BOARD/现成工具排查-0929.md): every
       pointer / click / key event whose input → next paint took ≥ 16 ms, kept briefly and matched to the gesture by its startTime ---- */
    const evs = [];
    try { if (window.PerformanceObserver && (PerformanceObserver.supportedEntryTypes || []).includes("event"))
      new PerformanceObserver((l) => { try { for (const e of l.getEntries()) { evs.push(e); } if (evs.length > 100) evs.splice(0, evs.length - 100); } catch (x) {} })
        .observe({ type: "event", buffered: false, durationThreshold: 16 }); } catch (e) {}
    const ET_NAMES = /^(pointerdown|pointerup|click|keydown|keyup)$/;   // not the mouse* compatibility events: iOS stamps them at the touch start, so their duration holds the finger's press
    const etOf = (from, to) => { let b = null; for (const e of evs) if (ET_NAMES.test(e.name) && e.startTime >= from - 5 && e.startTime <= to && (!b || e.duration > b.duration)) b = e;
      return b ? { name: b.name, dur: Math.round(b.duration), delay: Math.round(b.processingStart - b.startTime), proc: Math.round(b.processingEnd - b.processingStart) } : null; };
    const ET = !!(window.PerformanceObserver && (PerformanceObserver.supportedEntryTypes || []).includes("event"));

    /* ---- which script held a slow frame (Long Animation Frames API, W3C LoAF draft; Chrome 123+, not in Safari — there nothing is recorded):
       every frame over 50 ms, summarised on arrival — duration, blockingDuration, renderStart / styleAndLayoutStart (ms after the frame's start),
       the 5 longest PerformanceScriptTiming entries: file name only (no path / query / hash), sourceCharPosition, sourceFunctionName, invoker, duration ---- */
    const loafs = [], fileOf = (u) => txt(String(u || "").split(/[?#]/)[0].split("/").pop(), 40);
    const LOAF = !!(window.PerformanceObserver && (PerformanceObserver.supportedEntryTypes || []).includes("long-animation-frame"));
    try { if (LOAF) new PerformanceObserver((l) => { try { for (const e of l.getEntries()) {
        const t = e.startTime, rel = (x) => (x > 0 ? Math.round(x - t) : null);
        loafs.push({ t, dur: Math.round(e.duration), block: Math.round(e.blockingDuration || 0), rs: rel(e.renderStart), sl: rel(e.styleAndLayoutStart),
          scripts: [...(e.scripts || [])].sort((a, b) => b.duration - a.duration).slice(0, 5).map((x) => ({ src: fileOf(x.sourceURL), pos: x.sourceCharPosition, fn: txt(x.sourceFunctionName, 40),
            inv: txt(/:\/\//.test(x.invoker || "") ? fileOf(x.invoker) : x.invoker, 40), dur: Math.round(x.duration) })) }); }
        if (loafs.length > 60) loafs.splice(0, loafs.length - 60); } catch (x) {} }).observe({ type: "long-animation-frame", buffered: false }); } catch (e) {}
    const loafOf = (from, to) => loafs.filter((f) => f.t < to && f.t + f.dur > from).sort((a, b) => b.dur - a.dur).slice(0, 6).sort((a, b) => a.t - b.t)
      .map((f) => ({ at: Math.round(f.t - from), dur: f.dur, block: f.block, rs: f.rs, sl: f.sl, scripts: f.scripts }));   // at: ms after the press (negative = the frame began before it)
    /* was the menu's glass warm-up done at the press (menu.js warmUp; an open() that meets a half-built map finishes it synchronously) */
    const warmLeft = () => { try { const f = window.Menu && Menu.glass && Menu.glass.warmLeft; return f ? f() : undefined; } catch (e) { return undefined; } };
    /* the pressed menu's own maps at the press (Menu.glass.cachedFor, read-only; H = items × 42 + 20, the height warmUp keys by): warm-up done but these false =
       a menu the warm-up never saw (it keys only the main select.native heights 1.5 s after load, menu.js warmUp) */
    const menuMaps = (btn) => { try { const f = window.Menu && Menu.glass && Menu.glass.cachedFor, sel = btn && btn.matches(".menubtn") && btn.previousElementSibling;
      if (!f || !sel || sel.tagName !== "SELECT") return undefined; const h = sel.options.length * 42 + 20; return { h, ...f(h) }; } catch (e) { return undefined; } };
    /* the alert's warm-up (alert-glass.js warmUp, the last alert size in localStorage ark-alert-size): img / stroke = that size's maps prewarmed, cached = its images there now;
       all = every size warmUp queued (up to 3: the sizes opened before + the 1 / 2 / 3 message-line sizes), each {sz, img, stroke} done at the press (AlertGlass.warmed) */
    const alertWarm = () => { try { const A = window.AlertGlass, sz = localStorage.getItem("ark-alert-size"); if (!A || !sz) return undefined; const [w, h] = sz.split("x").map(Number);
      return { sz, img: A.prewarmed === sz, stroke: A.strokeWarmed === sz, cached: !!(A.cached && A.cached(w, h)), all: A.warmed }; } catch (e) { return undefined; } };
    /* the menu's GPU warm-up (menu.js gpuTry, off unless ?gpuwarm=1): the phone's 133–656 ms frames 0.4–10 s after load (block 0, rs ≈ dur, no script) in the
       warm-up builds could not be placed against it — the lines had no warm-up state (动效 09-30 03:45) */
    const gpuWarm = () => { try { const g = window.Menu && Menu.gpuWarm && Menu.gpuWarm(); return g || undefined; } catch (e) { return undefined; } };

    /* ---- canvas redraws (relay-2 09-30, for the acceptance session; the user said on 09-29 16:50 the segment looked like only 30 fps): fi only times the
       page's rAF, not whether the lens / glass canvas was actually redrawn in a frame. Every WebGL draw call made while the default framebuffer is bound
       (= onto the visible canvas, not into an FBO: lens-webgl.js pass 1 and the warm-up land in FBOs, pass 2 on the canvas) onto a canvas inside the
       current gesture's control region (regionNow: the live node, also after a re-render swapped it) counts one for that gesture (other canvases animating
       at the same time do not); frame() below attributes them to rAF frames. This script loads before every lens script (index.html), so the prototype
       wrap covers every context the page creates. ---- */
    try { for (const C of [window.WebGL2RenderingContext, window.WebGLRenderingContext]) {
      if (!C || !C.prototype || C.prototype.__fluWrap) continue; const P = C.prototype, bind0 = P.bindFramebuffer, fb = new WeakMap();
      P.bindFramebuffer = function (t, f) { try { if (t === this.FRAMEBUFFER || t === this.DRAW_FRAMEBUFFER) fb.set(this, f || null); } catch (e) {} return bind0.apply(this, arguments); };
      for (const n of ["drawArrays", "drawElements", "drawArraysInstanced", "drawElementsInstanced", "drawRangeElements"]) { const d0 = P[n]; if (typeof d0 !== "function") continue;
        P[n] = function () { try { const R = g && !fb.get(this) && regionNow(g); if (R && R.contains(this.canvas)) g.dn++; } catch (e) {} return d0.apply(this, arguments); }; }
      P.__fluWrap = true; } } catch (e) {}

    /* ---- one gesture ---- */
    const lines = [], stats = { sent: 0, failed: 0, capped: 0, last: null, lastErr: null, et: ET, loaf: LOAF };
    let g = null;
    const ovOn = (n) => n && n.nodeType === 1 && (n.matches(OVERLAYS) || !!n.closest(OVERLAYS));   // on or inside an overlay (cheap: the node and its ancestors)
    const ovTouch = (n) => ovOn(n) || (!!n && n.nodeType === 1 && !!n.querySelector(OVERLAYS));   // … or around one (a subtree query: only for added nodes)
    const mo = new MutationObserver((recs) => { try {
      if (!g) return; g.dirty = true;
      /* no subtree query per changed target: a tab / shift re-render changes hundreds (数据 09-30 flurec.py: 9.6 ms at 4× CPU on 早班); removed nodes cannot bring an overlay in */
      if (!g.sceneMs && !g.ovDirty) for (const r of recs) { if (ovOn(r.target) || (r.type === "childList" && [...r.addedNodes].some(ovTouch))) { g.ovDirty = true; break; } }
      const R = !g.nearT && regionNow(g);
      if (R) for (const r of recs) { const t = r.target; if (R.contains(t) || (r.type === "childList" && t.contains && t.contains(R))) { g.nearT = performance.now(); break; } }
    } catch (e) {} });
    const onAnim = (e) => { try { if (!g) return; g.dirty = true; if (!g.ovDirty && ovTouch(e.target)) g.ovDirty = true; const R = !g.nearT && regionNow(g); if (R && R.contains(e.target)) g.nearT = performance.now(); } catch (x) {} };
    const start = (e) => {
      if (g) finish(false);
      const t = performance.now(), c = control(e.target, e.clientX);
      const ts = Number.isFinite(e.timeStamp) && e.timeStamp > 0 && e.timeStamp <= t + 50 ? e.timeStamp : t;
      g = { c, at: Date.now(), pn: ts, down: true, up: 0, last: t, dirty: false, first: 0, nearT: 0, fi: [], prev: 0, wait: Math.round(t - ts), dn: 0, dPrev: 0, df: [],
        scene0: scene(), sceneMs: 0, sceneTo: "", glass: c.glass, tab: curTab(), errs0: errs.length, warm: warmLeft(), maps: menuMaps(c.btn), aw: alertWarm(), gw: gpuWarm() };
      mo.observe(document.documentElement, { attributes: true, childList: true, subtree: true, characterData: true });
      document.addEventListener("transitionrun", onAnim, true); document.addEventListener("animationstart", onAnim, true);
      /* one rAF chain per gesture: a chain stops as soon as its gesture is no longer the current one (before, a press that cut the previous gesture
         short left the old chain running on the new gesture, so each frame was recorded once per live chain — fi 0-intervals, nf × 3 in flu 164840) */
      const G = g, chain = (ts) => { if (g === G) frame(ts, chain); }; raf(chain);
    };
    const frame = (ts, chain) => { try {
      if (!g) return;
      const now = performance.now();
      if (g.prev) g.fi.push([Math.round((ts - g.prev) * 10) / 10, Math.round(g.prev - g.pn)]);
      g.prev = ts;
      if (g.dn !== g.dPrev) { g.df.push([g.fi.length - 1, g.dn - g.dPrev]); g.dPrev = g.dn; }   // the interval just ended had canvas draws: [its index in fi (−1 = before the first), how many]
      if (g.dirty) {
        if (!g.first) g.first = ts - g.pn;
        /* the overlay check reads computed style / client rects: in this rAF callback that forced a style + layout pass on every dirty frame (the page's
           animations dirty every frame) — 数据 09-30 flurec.py, 4× CPU: this chain 21–29 ms per tap. It is read after this frame's rendering instead
           (a task queued now runs after the frame is drawn, style and layout clean), and still stamped with this frame (ts / now) */
        if (!g.sceneMs && !g.scenePend && g.ovDirty) { const G = g, fts = ts, fnow = now; G.scenePend = 1; G.ovDirty = false;   // only when a change touched an overlay (on it, inside it or around it): a press that opens none reads none
          setTimeout(() => { try { G.scenePend = 0; if (g !== G || G.sceneMs) return;
            const s = scene(); const add = s.split(" ").filter((x) => x && !G.scene0.split(" ").includes(x));
            if (add.length) { G.sceneMs = fts - G.pn; G.sceneTo = s; if (!G.nearT) G.nearT = fnow;
              if (!G.glass) for (const a of add) { const gl = glassOf(a); if (gl) { G.glass = gl; break; } } } } catch (e) {} }, 0); }
        g.last = now; g.dirty = false;
      }
      const watchDead = !g.nearT && g.c.region && (g.down || now - g.up < DEAD_MS + 50);   // the dead-tap second runs from the lift
      if ((!g.down && now - g.last > SETTLE_MS && !watchDead) || now - g.pn > HARD_MS) finish(true); else raf(chain);
    } catch (e) { g = null; try { mo.disconnect(); } catch (x) {} } };
    const finish = (settled) => {
      const G = g, tEnd = performance.now(); g = null; mo.disconnect();
      document.removeEventListener("transitionrun", onAnim, true); document.removeEventListener("animationstart", onAnim, true);
      if (!G || (document.visibilityState !== "visible" && G.fi.length < 2)) return;
      if (settled && G.c.kind === "seg") { const s = regionNow(G);   // the page is quiet now: read (or reuse) the segment's button ranges, and name a lens press's button
        if (s && s.isConnected && s.matches(".segctl")) { const i = segAt(s, G.c.x === undefined ? -1 : G.c.x, true), b = i >= 0 && G.c.x !== undefined && s.querySelectorAll("button")[i];
          if (b) { G.c.ctl = txt(b.dataset.q || b.textContent); G.c.id = idOf(b); G.c.on = !!G.c.bon[i]; G.c.off = !!G.c.boff[i]; } } }
      const fi = G.fi.slice(1), ms = fi.map((x) => x[0]);   // the first interval straddles the press itself
      const L = { at: G.at, pn: Math.round(G.pn), v: ver, ctl: G.c.ctl, id: G.c.id || 0, kind: G.c.kind, watched: Math.round(tEnd - G.pn), glass: G.glass, tab: G.tab, wait: G.wait,
        press: G.up ? Math.round(G.up - G.pn) : null, first: G.first ? Math.round(G.first) : null,
        react: G.first ? Math.round(G.up && G.first > G.up - G.pn ? G.first - (G.up - G.pn) : G.first) : null, near: G.nearT ? Math.round(G.nearT - G.pn) : null,
        was_on: !!G.c.on, disabled: !!G.c.off, scene: G.sceneMs ? [G.scene0, G.sceneTo, Math.round(G.sceneMs)] : null,
        nf: ms.length, max: ms.length ? Math.round(Math.max(...ms)) : null, n50: ms.filter((x) => x >= 50).length, n100: ms.filter((x) => x > 100).length, run25: runOver(ms, CHOPPY_MS),
        big: fi.slice().sort((a, b) => b[0] - a[0]).slice(0, 5).filter((x) => x[0] >= 34), span: Math.round(Math.max(G.last - G.pn, 0)), settled, bad: [], et: ET ? etOf(G.pn, Math.max(G.last, G.pn + 50)) : undefined };
      { const df = G.df.filter(([i]) => i >= 1);   // the same frames as fi.slice(1) / nf, for draws as for dfr / d_rate
        L.draws = df.length ? df.reduce((a, [, n]) => a + n, 0) : null;
        L.dfr = df.length ? df[df.length - 1][0] - df[0][0] + 1 : null; L.d_rate = df.length ? Math.round(df.length / L.dfr * 100) / 100 : null; }
      if (G.warm !== undefined) { L.prewarm_done = G.warm === 0; L.prewarm_left = G.warm; }   // left: null = the warm-up had not started yet
      if (G.maps) L.menu_maps = G.maps;   // {h, img, stroke}: the pressed menu's glass / stroke map in the cache at the press
      if (G.aw) L.alert_warm = G.aw;
      { const g = gpuWarm(); if (g) L.gpu_warm = { s0: G.gw ? G.gw.state : null, state: g.state, at: g.at == null ? null : Math.round(g.at), end: g.end == null ? null : Math.round(g.end), yields: g.yields, tries: g.tries }; }
      if (LOAF) { const lf = loafOf(G.pn, tEnd); if (lf.length) L.loaf = lf; }
      const e = errs.slice(G.errs0); if (e.length) L.err = e.slice(0, 5);
      L.bad = judge(L, lines);
      if (L.bad.length) {                                          // frames ride along only the first time for version × rule × control (K12)
        const seen = parse(get(SKEY), []), ks = L.bad.map((r) => ver + "|" + r + "|" + L.ctl), fresh = ks.filter((k) => !seen.includes(k));
        if (fresh.length) { L.fi = ms.slice(0, FI_MAX); set(SKEY, JSON.stringify(seen.concat(fresh).slice(-200))); }
        pending = true; if (!sendT) sendT = setTimeout(() => flush(false), SEND_MS);   // hits within SEND_MS of the first go as one upload
      }
      lines.push(L); if (lines.length > RING_N) lines.splice(0, lines.length - RING_N);
      try { window.dispatchEvent(new CustomEvent("flurec", { detail: L })); } catch (x) {}
    };
    on(window, "pointerdown", (e) => { if (e.isPrimary !== false) start(e); }, true);
    const lift = () => { if (g && g.down) { g.down = false; g.up = performance.now(); g.last = g.up; } };
    on(window, "pointerup", lift, true); on(window, "pointercancel", lift, true);
    on(window, "scroll", () => { if (g) { g.dirty = true; if (!g.nearT) g.nearT = performance.now(); } }, { capture: true, passive: true });

    /* ---- storage (the recorder's own keys only) and sending ---- */
    const tokyo = (ms) => new Date(ms + 9 * 3600e3).toISOString().replace(/[-:T]/g, "").slice(0, 14);
    const day = () => { const d = tokyo(Date.now()).slice(0, 8), o = parse(get(DKEY), null); return o && o.d === d ? o : { d, n: 0, b: 0 }; };
    const readQ = () => { const a = parse(get(QKEY), []); return Array.isArray(a) ? a : []; };
    const writeQ = (a) => { for (;;) { const s = JSON.stringify(a), own = (get(DKEY) || "").length + (get(SKEY) || "").length;
      if ((s.length + own <= OWN_MAX || !a.length) && set(QKEY, s)) return; if (!a.length) return; a.shift(); } };
    let seq = 0, sentUpTo = -1, pending = false, sendT = 0, busy = false;
    const a11y = () => { const mm = (s) => { try { return matchMedia(s).matches; } catch (e) { return null; } }; return { reduce_motion: mm("(prefers-reduced-motion: reduce)"), reduce_transparency: mm("(prefers-reduced-transparency: reduce)") }; };
    const build = (why) => {                                        // the hit lines since the last upload + CTX_N lines before each
      const idx = new Set();
      lines.forEach((l, i) => { if (l.pn > sentUpTo && l.bad.length) for (let k = Math.max(0, i - CTX_N); k <= i; k++) if (lines[k].pn > sentUpTo) idx.add(k); });   // a line already sent is not sent again
      if (!idx.size) return null;
      let ls = [...idx].sort((a, b) => a - b).map((i) => lines[i]);
      const mk = () => JSON.stringify({ kind: "flu", why, v: ver, sid, sent: Date.now(), ua: navigator.userAgent, url: scrub(location.origin + location.pathname),
        dpr: devicePixelRatio, viewport: [innerWidth, innerHeight],
        standalone: (() => { try { return navigator.standalone === true || matchMedia("(display-mode: standalone)").matches; } catch (e) { return null; } })(), a11y: a11y(), lines: ls });
      let body = mk();
      if (body.length > BODY_MAX) { ls = ls.map((l) => { const { fi, ...r } = l; return r; }); body = mk(); }
      while (body.length > BODY_MAX && ls.length > 1) { ls = ls.slice(Math.ceil(ls.length / 4)); body = mk(); }
      return { body, upTo: lines[lines.length - 1].pn };
    };
    const put = async (key, body, keepalive) => {
      const r = await fetch0(`${BUCKET}/${key}`, { method: "PUT", keepalive: !!keepalive, headers: { "Content-Type": "application/json", "x-cos-forbid-overwrite": "true" }, body });
      return r.ok || r.status === 409;                                // 409 = an earlier try already landed
    };
    async function flush(keepalive) {
      clearTimeout(sendT); sendT = 0;
      if (!fetch0 || busy) return;
      busy = true;
      try {
        if (pending) { pending = false; const b = build(keepalive ? "background" : "hit");   // into the queue BEFORE the PUT: a page suspended or killed
          if (b) { sentUpTo = b.upTo; const q0 = readQ(); q0.push({ key: `diag/flu/${tokyo(Date.now())}-${sid}-${++seq}.json`, body: b.body }); writeQ(q0); } }   // mid-upload keeps it for the next start
        for (const it of readQ()) {
          const dd = day();
          if (dd.n >= DAY_MAX || dd.b + it.body.length > DAY_BYTES) { stats.capped++; stats.lastErr = "daily cap"; break; }   // it stays queued for tomorrow
          let ok = false;
          try { ok = await put(it.key, it.body, keepalive && it.body.length <= 64e3); if (!ok) stats.lastErr = "refused"; } catch (e) { stats.lastErr = txt(e && e.message || e, 80); }
          if (!ok) { stats.failed++; break; }                          // offline / refused: the rest waits for the next start
          stats.sent++; stats.last = it.key; dd.n++; dd.b += it.body.length; set(DKEY, JSON.stringify(dd));
          writeQ(readQ().filter((x) => x.key !== it.key));
        }
      } catch (e) {} finally { busy = false; }
    }
    const hide = () => { if (g) finish(false); if (pending) flush(true); };
    on(document, "visibilitychange", () => { if (document.visibilityState === "hidden") hide(); });
    on(window, "pagehide", hide);
    setTimeout(() => { if (readQ().length) flush(false); }, 2000);        // an upload left over from an earlier load
    on(window, "online", () => { if (readQ().length) flush(false); });

    window.FluRec = { lines, stats, sid, queue: readQ, flush: () => { pending = true; return flush(false); }, day };
  } catch (e) {}
})();
